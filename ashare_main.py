# -*- coding: utf-8 -*-
"""
ashare_main.py —— A 股机器人主程序（日线定方向 + 60 分钟找进场）

用法：python ashare_main.py check

兼容性说明：
  这里特意写成「兼容新旧共用模块」——不依赖 risk_push/signals 的新参数，
  所以即使仓库里的共用文件是旧版，也能正常跑。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import config                      # 账户金额、单笔风险%
import ashare_config
import ashare_fetch
import indicators
import signals
import ashare_push
import risk_push
from journal import Journal

# ---- 用 A 股参数覆盖配置（兼容新旧 risk_push，不用 params 参数）----
config.MAX_OPEN_SIGNALS = ashare_config.RISK_PARAMS["max_open"]
config.MAX_CONSECUTIVE_LOSSES = ashare_config.RISK_PARAMS["max_consecutive"]
config.PAUSE_HOURS = ashare_config.RISK_PARAMS["pause_hours"]
config.DAILY_MAX_LOSS_R = ashare_config.RISK_PARAMS["daily_max_r"]
config.TRADER["check_hours"] = ashare_config.RISK_PARAMS["check_hours"]

# ---- 确保推送密钥从云端环境变量读进来（兼容老版 config.py）----
if os.environ.get("PUSH_WEBHOOK_URL"):
    config.PUSH_WEBHOOK_URL = os.environ["PUSH_WEBHOOK_URL"]
if os.environ.get("PUSH_CHANNEL") and hasattr(config, "PUSH_CHANNEL"):
    config.PUSH_CHANNEL = os.environ["PUSH_CHANNEL"]


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


def _note(jr: Journal, text: str):
    """写一条日志备注（兼容新旧 journal）。"""
    if hasattr(jr, "record_note"):
        jr.record_note(text)
    else:
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
        jr._md_append(f"- [{stamp}] {text}")


def _fix_stop(sig: dict, df_entry):
    """兜底：若止损跑到进场上方（老版信号模块可能出现），用最近低点重算。"""
    if sig["stop"] < sig["entry"]:
        return
    atr = sig["atr"]
    recent_low = float(df_entry["low"].iloc[-11:].min())
    stop = recent_low - config.ATR_STOP_MULT * atr
    if stop >= sig["entry"]:
        stop = sig["entry"] - 2 * atr
    r = sig["entry"] - stop
    sig["stop"] = stop
    sig["r"] = r
    sig["targets"] = {"1R": sig["entry"] + r, "2R": sig["entry"] + 2 * r, "3R": sig["entry"] + 3 * r}
    res = sig.get("nearest_resistance")
    sig["rr_ok"] = True if res is None else (res - sig["entry"]) >= config.MIN_RR * r


def _build_signal(secid, df_dir, df_entry):
    """调用信号模块（兼容新旧签名）。"""
    try:
        return signals.build_signal(secid, df_dir, df_entry,
                                    interval_label=ashare_config.ENTRY_LABEL, min_confirm=2)
    except TypeError:
        sig = signals.build_signal(secid, df_dir, df_entry)
        if sig is not None:
            sig["interval"] = ashare_config.ENTRY_LABEL
        return sig


def get_data():
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
    rm = risk_push.RiskManager(state_path=config.OUTPUT_DIR / "ashare_risk.json")
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

        bar_ts = str(df_entry["close_time"].iloc[-1])
        sig = _build_signal(secid, df_dir, df_entry)
        if sig is None:
            continue

        if sig["trend_4h"] == "range":
            if sig["is_signal"]:
                _note(jr, f"{name} 震荡期信号雏形，只记录不推送")
                print(f"   [{name}] 震荡期，只记录")
            continue

        if sig["trend_4h"] == "long" and sig["is_signal"]:
            if state.get(secid) == bar_ts:
                print(f"   [{name}] 这根 {bar_ts} 已检查过，跳过（防重复）")
                continue
            _fix_stop(sig, df_entry)
            ok, reason = rm.check_push(sig)
            if not ok:
                print(f"   [{name}] 被风控拦截：{reason}")
                _note(jr, f"{name} 信号被拦截：{reason}")
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
