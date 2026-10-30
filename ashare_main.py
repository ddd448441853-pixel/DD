# -*- coding: utf-8 -*-
"""
ashare_main.py —— A 股机器人主程序（日线定方向 + 60 分钟找进场）

用法：python ashare_main.py check

设计要点：
  - 每根 60 分钟 K 线收盘后检查（10:30 / 11:30 / 14:00 / 15:00）
  - 同一根 K 线只处理一次（避免重复推送）
  - 复用指标/信号/风控模块，但用 A 股自己的仓位和文案
"""
from __future__ import annotations

import json
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import config                      # 账户金额、单笔风险% 复用
import ashare_config
import ashare_fetch
import indicators
import signals
import ashare_push
import risk_push
from journal import Journal


def _state_path():
    return config.OUTPUT_DIR / "ashare_last.json"


def _load_state() -> dict:
    p = _state_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_state(state: dict):
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def get_data():
    """拉每只标的的日线 + 60分钟，算好指标。"""
    out = []
    for item in ashare_config.WATCHLIST:
        secid = item["secid"]
        df_dir = ashare_fetch.fetch_klines(secid, ashare_config.KL_DEPT_DIRECTION,
                                           ashare_config.LOOKBACK_DIRECTION)
        df_entry = ashare_fetch.fetch_klines(secid, ashare_config.KL_DEPT_ENTRY,
                                             ashare_config.LOOKBACK_ENTRY)
        if df_dir is not None:
            df_dir = indicators.compute_indicators(df_dir)
        if df_entry is not None:
            df_entry = indicators.compute_indicators(df_entry)
        out.append((item, df_dir, df_entry))
    return out


def run_check():
    print(f"===== A股盯盘 {datetime.now().astimezone():%Y-%m-%d %H:%M} =====")
    rm = risk_push.RiskManager(
        state_path=config.OUTPUT_DIR / "ashare_risk.json",
        params=ashare_config.RISK_PARAMS,
    )
    jr = Journal(
        trades_file=config.OUTPUT_DIR / "ashare_trades.jsonl",
        md_file=config.BASE_DIR / "交易日志_A股.md",
    )
    state = _load_state()

    for item, df_dir, df_entry in get_data():
        secid, name = item["secid"], item["name"]
        if df_dir is None or df_entry is None:
            print(f"[{name}] 数据缺失，跳过（未验证）")
            continue

        trend, reason = signals.trend_state(df_dir)
        print(f"[{name}] {ashare_config.DIRECTION_LABEL}={trend}（{reason}）")

        # 当前处理到的 60m K 线时间（用于去重）
        bar_ts = str(df_entry["close_time"].iloc[-1])

        sig = signals.build_signal(
            secid, df_dir, df_entry,
            interval_label=ashare_config.ENTRY_LABEL, min_confirm=2,
        )
        if sig is None:
            continue

        if sig["trend_4h"] == "range":
            if sig["is_signal"]:
                jr.record_note(f"{name} 震荡期信号雏形，只记录不推送")
                print(f"   [{name}] 震荡期，只记录")
            continue

        if sig["trend_4h"] == "long" and sig["is_signal"]:
            if state.get(secid) == bar_ts:
                print(f"   [{name}] 这根 {bar_ts} 已检查过，跳过（防重复）")
                continue
            ok, reason = rm.check_push(sig)
            if not ok:
                print(f"   [{name}] 被风控拦截：{reason}")
                jr.record_note(f"{name} 信号被拦截：{reason}")
                state[secid] = bar_ts
                _save_state(state)
                continue

            pos = ashare_push.compute_position(
                sig["entry"], sig["stop"],
                config.TRADER["account_size"], config.TRADER["risk_percent"],
            )
            alert = ashare_push.format_alert(
                sig, pos, name, config.TRADER["risk_percent"])
            risk_push.push(alert, secid)
            jr.record_signal(sig)
            if sig["rr_ok"]:
                rm.add_open_signal(sig)
                print(f"   [{name}] ✅ 已推送（{sig['num_triggered']}条）")
            else:
                print(f"   [{name}] ⚠ 盈亏比不足，降级观察")
            state[secid] = bar_ts
            _save_state(state)
        else:
            print(f"   [{name}] 无信号（{sig['num_triggered']}条，需≥2条）")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        run_check()
    else:
        print("用法：python ashare_main.py check")
