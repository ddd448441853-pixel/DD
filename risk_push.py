# -*- coding: utf-8 -*-
"""
risk_push.py —— 第 4 步：风控 + 推送

大白话：信号是「该不该看」，这里是「该不该推给你 + 推多少」。

包含：
  1) 仓位计算（按风险算，不按感觉）
  2) 杠杆 + 强平价估算（强平价必须在止损之外）
  3) 风控闸门（最多2个未处理信号 / 连亏2笔暂停12h / 单日亏3R停推 / 重大数据±1h不推）
  4) 固定格式的推送文案（10 行内）
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import config


# ============ 1) 仓位计算 ============

def compute_position(entry: float, stop: float, account: float, risk_pct: float) -> dict:
    """
    仓位 = 账户金额 × 单笔风险% ÷ (进场价 - 止损价)
    返回：数量（基础币）、名义价值、实际风险金额、止损距离。
    """
    stop_distance = entry - stop          # 每单位最多亏多少
    if stop_distance <= 0:
        raise ValueError("止损必须在进场价之下（做多）")
    risk_amount = account * risk_pct      # 这笔最多亏多少钱
    qty = risk_amount / stop_distance     # 数量 = 能亏的钱 ÷ 每单位亏损
    notional = qty * entry
    return {
        "qty": qty,
        "notional": notional,
        "risk_amount": risk_amount,
        "stop_distance": stop_distance,
    }


# ============ 2) 杠杆 + 强平价 ============

def max_safe_leverage(entry: float, stop: float, mmr: float) -> float:
    """
    做多逐仓（USDT 本位）强平价近似：liq ≈ entry × (1 − 1/L + mmr)
    要求 liq < 止损 → 反解出最大杠杆 L_max = 1 / (mmr + (entry−stop)/entry)
    """
    r_ratio = (entry - stop) / entry
    denom = mmr + r_ratio
    if denom <= 0:
        return 1.0
    return 1.0 / denom


def liquidation_price(entry: float, leverage: float, mmr: float) -> float:
    """估算做多逐仓强平价（忽略手续费和资金费，作为安全参考）。"""
    return entry * (1.0 - 1.0 / leverage + mmr)


def recommend_leverage(symbol: str, entry: float, stop: float) -> dict:
    """
    挑一个「强平价在止损之外」的杠杆档位，并给出该档位下的强平价和离止损的距离。
    """
    mmr = config.MAINTENANCE_MARGIN.get(symbol, config.MAINTENANCE_MARGIN["DEFAULT"])
    lmax = max_safe_leverage(entry, stop, mmr) * config.LEVERAGE_SAFETY
    # 选不超过安全上限的最大常用档位
    leverage = 1
    for lv in config.LEVERAGE_OPTIONS:
        if lv <= lmax:
            leverage = lv
    liq = liquidation_price(entry, leverage, mmr)
    return {
        "leverage": leverage,
        "liq": liq,
        "liq_below_stop": stop - liq,          # 正数 = 强平价在止损之下（安全）
        "max_safe": lmax,
    }


# ============ 3) 风控闸门 ============

class RiskManager:
    """
    记录并执行风控规则。状态持久化到 output/risk_state.json，
    机器人重启也不丢（连亏、当日亏损、暂停时间都记得）。
    """

    def __init__(self, state_path: Path | None = None):
        self.state_path = state_path or (config.OUTPUT_DIR / "risk_state.json")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load()

    def _load(self) -> dict:
        default = {
            "open_signals": [],        # 未处理信号 [{symbol, time, entry, stop}]
            "consecutive_losses": 0,
            "daily_loss_r": 0.0,
            "last_day": "",
            "paused_until": None,      # ISO 时间字符串
        }
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                default.update(data)
            except (json.JSONDecodeError, OSError):
                pass
        return default

    def save(self):
        self.state_path.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _today(self) -> str:
        return datetime.now().astimezone().strftime("%Y-%m-%d")

    def _roll_day(self):
        today = self._today()
        if self.state["last_day"] != today:
            self.state["last_day"] = today
            self.state["daily_loss_r"] = 0.0   # 新的一天，重置当日亏损

    @staticmethod
    def _in_event_window(now: datetime) -> bool:
        for ev in config.EVENTS:
            t = datetime.fromisoformat(ev["time"])
            if t - timedelta(hours=1) <= now <= t + timedelta(hours=1):
                return True
        return False

    @staticmethod
    def _in_check_hours(now: datetime) -> bool:
        h = now.hour
        return any(lo <= h <= hi for lo, hi in config.TRADER["check_hours"])

    def check_push(self, signal: dict, now: datetime | None = None) -> tuple[bool, str]:
        """
        判断一个信号「现在能不能推」。
        返回 (能不能推, 原因)。不能推时给明原因，供记录。
        """
        now = now or datetime.now().astimezone()
        if now.tzinfo is None:   # 没带时区就当本地时间，避免比较报错
            now = now.replace(tzinfo=datetime.now().astimezone().tzinfo)
        self._roll_day()

        if self.state["paused_until"]:
            paused = datetime.fromisoformat(self.state["paused_until"])
            if now < paused:
                return False, f"连亏暂停中，至 {paused:%m-%d %H:%M} 前只发复盘提醒"

        if len(self.state["open_signals"]) >= config.MAX_OPEN_SIGNALS:
            return False, f"未处理信号已达 {config.MAX_OPEN_SIGNALS} 个上限"

        if self.state["daily_loss_r"] >= config.DAILY_MAX_LOSS_R:
            return False, f"当日累计亏损已达 {config.DAILY_MAX_LOSS_R}R，停止推送"

        if self._in_event_window(now):
            return False, "重大数据公布前后 1 小时，不推新信号（只提醒风险）"

        if not self._in_check_hours(now):
            return False, "不在你能看手机的时段（只记录，不打扰）"

        return True, "通过风控"

    def add_open_signal(self, signal: dict):
        self.state["open_signals"].append({
            "symbol": signal["symbol"],
            "time": str(signal["time"]),
            "entry": signal["entry"],
            "stop": signal["stop"],
        })
        # 只保留最近 MAX_OPEN_SIGNALS 个，避免无限增长
        self.state["open_signals"] = self.state["open_signals"][-config.MAX_OPEN_SIGNALS:]
        self.save()

    def record_result(self, r_multiple: float):
        """
        我回复「开了/没开」后调用：记录这一笔的结果（R 倍数）。
        亏损 → 连亏+1、当日亏损累计；盈利 → 连亏清零。
        """
        self._roll_day()
        if r_multiple < 0:
            self.state["consecutive_losses"] += 1
            self.state["daily_loss_r"] += abs(r_multiple)
            if self.state["consecutive_losses"] >= config.MAX_CONSECUTIVE_LOSSES:
                self.state["paused_until"] = (
                    datetime.now().astimezone() + timedelta(hours=config.PAUSE_HOURS)
                ).isoformat()
        else:
            self.state["consecutive_losses"] = 0
        self.save()


# ============ 4) 推送文案 ============

def format_alert(signal: dict, pos: dict, lev: dict) -> str:
    """按固定格式生成推送文案，控制在 10 行内。"""
    s = signal
    entry = s["entry"]
    triggered = "、".join(s["triggered"])
    entry_lo = entry - 0.2 * s["atr"]
    entry_hi = entry + 0.2 * s["atr"]

    lines = []
    lines.append(f"【{s['symbol'].replace('USDT', '/USDT')} | 做多 | {s['interval']}】")
    lines.append(f"触发：{triggered}（{s['num_triggered']}/4条）")
    lines.append(f"进场区间：{entry_lo:,.0f} ~ {entry_hi:,.0f}")
    lines.append(f"止损：{s['stop']:,.0f}（距进场 {s['r']:,.0f} = 1R）")
    lines.append(f"目标：1R {s['targets']['1R']:,.0f} / 2R {s['targets']['2R']:,.0f} / 3R {s['targets']['3R']:,.0f}")
    if s["nearest_resistance"] is not None:
        lines.append(f"最近阻力：{s['nearest_resistance']:,.0f}")
    lines.append(
        f"仓位：{pos['qty']:.4f}（风险1%，强平 {lev['liq']:,.0f}，在止损之下 {lev['liq_below_stop']:,.0f}）"
    )
    rr_note = "" if s["rr_ok"] else " ⚠盈亏比不足，降级观察"
    lines.append(f"强度：{s['strength']}{rr_note}")
    lines.append(f"简评：4h{s['trend_reason']}；{'、'.join(s['triggered'])}。")
    lines.append(f"失效：跌破止损 {s['stop']:,.0f} 即失效。")
    return "\n".join(lines)


def _build_payload(channel: str, text: str):
    """不同推送渠道要的报文格式不一样，这里统一拼好。返回 (body字节, Content-Type)。"""
    import urllib.parse
    if channel == "serverchan":
        # Server酱：form 表单，title 简短标题 + desp 正文
        body = urllib.parse.urlencode({"title": "交易提醒", "desp": text}).encode("utf-8")
        return body, "application/x-www-form-urlencoded"
    if channel in ("wecom", "dingtalk"):
        # 企业微信/钉钉群机器人：JSON text 消息
        body = json.dumps({"msgtype": "text", "text": {"content": text}}).encode("utf-8")
        return body, "application/json"
    # generic：直接 POST 一个 {"text": ...}
    return json.dumps({"text": text}).encode("utf-8"), "application/json"


def push(alert_text: str, symbol: str) -> None:
    """
    推送：写进 output/alerts.md 存档 + 打印到屏幕；
    若配置了 PUSH_WEBHOOK_URL，则按 PUSH_CHANNEL 的格式发到手机。
    """
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log_file = config.OUTPUT_DIR / "alerts.md"
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    with log_file.open("a", encoding="utf-8") as f:
        f.write(f"\n--- {stamp} {symbol} ---\n{alert_text}\n")

    print("\n" + alert_text + "\n")

    if config.PUSH_WEBHOOK_URL:
        try:
            body, ctype = _build_payload(config.PUSH_CHANNEL, alert_text)
            req = urllib.request.Request(
                config.PUSH_WEBHOOK_URL, data=body, headers={"Content-Type": ctype},
            )
            urllib.request.urlopen(req, timeout=10)
            print("[推送成功]")
        except Exception as e:
            print(f"[推送失败] {e}")
