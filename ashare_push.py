# -*- coding: utf-8 -*-
"""
ashare_push.py —— A 股版的仓位计算 + 推送文案

和加密版最大的不同：
  - A 股没有杠杆、没有强制平仓 → 不算强平价，只算「买多少手」
  - 股票/ETF 最小 100 股为 1 手 → 仓位向下取整到 100 股
  - 不能超过账户现金（A 股不能加杠杆）
"""
from __future__ import annotations

import math


def _p(x: float) -> str:
    """价格显示：小额（ETF）留 3 位，大额留 2 位。"""
    return f"{x:.3f}" if abs(x) < 10 else f"{x:,.2f}"


def compute_position(entry: float, stop: float, account: float,
                     risk_pct: float, lot: int = 100) -> dict:
    """
    按风险算仓位，再按「100 股 1 手」取整，并受账户现金上限约束。
    """
    stop_distance = entry - stop
    if stop_distance <= 0:
        raise ValueError("止损必须在进场价之下")
    risk_amount = account * risk_pct
    qty_raw = risk_amount / stop_distance
    qty = math.floor(qty_raw / lot) * lot

    # A 股不能加杠杆：市值不能超过账户现金
    max_qty = math.floor(account / entry / lot) * lot
    capped = qty > max_qty
    qty = min(qty, max_qty)

    lots = qty // lot
    cost = qty * entry
    return {
        "qty": qty,
        "lots": lots,
        "cost": cost,
        "risk_amount": risk_amount,
        "stop_distance": stop_distance,
        "capped": capped,
        "insufficient": qty < lot,
    }


def format_alert(signal: dict, pos: dict, name: str, risk_pct: float) -> str:
    """A 股版推送文案（10 行内）。"""
    s = signal
    entry = s["entry"]
    entry_lo = entry - 0.2 * s["atr"]
    entry_hi = entry + 0.2 * s["atr"]

    lines = []
    lines.append(f"【{name} | 做多 | {s['interval']}】")
    lines.append(f"触发：{'、'.join(s['triggered'])}（{s['num_triggered']}/4条）")
    lines.append(f"进场区间：{_p(entry_lo)} ~ {_p(entry_hi)}")
    lines.append(f"止损：{_p(s['stop'])}（距进场 {_p(s['r'])} = 1R）")
    lines.append(f"目标：1R {_p(s['targets']['1R'])} / 2R {_p(s['targets']['2R'])} / 3R {_p(s['targets']['3R'])}")
    if s["nearest_resistance"] is not None:
        lines.append(f"最近阻力：{_p(s['nearest_resistance'])}")
    if pos["insufficient"]:
        lines.append("仓位：资金不足 1 手，仅观察")
    else:
        cap = "（受账户现金上限约束）" if pos["capped"] else ""
        lines.append(
            f"仓位：约 {pos['lots']} 手（{pos['qty']} 股，约 {pos['cost']:,.0f} 元，风险 {risk_pct:.0%}）{cap}"
        )
    rr_note = "" if s["rr_ok"] else " ⚠盈亏比不足，降级观察"
    lines.append(f"强度：{s['strength']}{rr_note}")
    lines.append(f"简评：{s['trend_reason']}；{'、'.join(s['triggered'])}。")
    lines.append(f"失效：跌破止损 {_p(s['stop'])} 即失效。")
    return "\n".join(lines)
