# -*- coding: utf-8 -*-
"""
main.py —— 把五个模块组装成一个能跑的机器人。

大白话：这是机器人的「总开关」。它做三件事：
  1) run_check()      每根 1h 收盘后跑一次：拉数据→算指标→判信号→过风控→推送/记录
  2) run_daily_review() 每天早上 9 点：发复盘
  3) run_followup()    事后跟踪「没开」的信号走到几 R

用法（在 trading-bot 目录下）：
  python main.py check     # 手动触发一次盯盘
  python main.py review    # 手动触发一次复盘
  python main.py followup  # 手动触发后续走势跟踪
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import config
import data_fetch
import indicators
import signals
import risk_push
from journal import Journal


def get_data() -> tuple[dict, dict]:
    """
    拉最新数据（失败则回退本地缓存，并标「未验证」）。
    返回 (data, verified)：data[symbol][interval] = 带指标的 df；verified 记录是否实时。
    """
    fetched = data_fetch.fetch_all(market="spot")
    data, verified = {}, {}
    for sym in config.SYMBOLS:
        data[sym] = {}
        for itv in (config.INTERVAL_DIRECTION, config.INTERVAL_ENTRY):
            df = fetched[sym][itv]
            ok = df is not None
            if df is None:
                df = data_fetch.load_klines("spot", sym, itv)   # 回退缓存
            if df is not None:
                df = indicators.compute_indicators(df)
            data[sym][itv] = df
            verified[(sym, itv)] = ok
    return data, verified


def run_check(push_enabled: bool = True) -> None:
    """每根 1h 收盘后检查一次。"""
    print(f"===== 盯盘检查 {datetime.now().astimezone():%Y-%m-%d %H:%M} =====")
    data, verified = get_data()
    rm = risk_push.RiskManager()
    jr = Journal()

    for sym in config.SYMBOLS:
        df4h = data[sym][config.INTERVAL_DIRECTION]
        df1h = data[sym][config.INTERVAL_ENTRY]
        if df4h is None or df1h is None:
            print(f"[{sym}] 数据缺失（未验证），跳过，不硬给信号")
            continue

        trend, reason = signals.trend_state(df4h)
        fresh = "实时" if verified[(sym, config.INTERVAL_ENTRY)] else "缓存（未验证）"
        print(f"[{sym}] 4h={trend}（{reason}）| 数据：{fresh}")

        sig = signals.build_signal(sym, df4h, df1h)
        if sig is None:
            continue  # 4h 看空（逆势），不产生信号

        if sig["trend_4h"] == "range":
            # 震荡期：只记录，不推送
            if sig["is_signal"]:
                jr.record_note(f"{sym} 震荡期出现多头信号雏形（触发{sig['num_triggered']}条），按规则只记录不推送")
                print(f"   [{sym}] 震荡期，只记录不推送")
            continue

        if sig["trend_4h"] == "long" and sig["is_signal"]:
            if not push_enabled:
                print(f"   [{sym}] 检测到信号（未推送，push_enabled=False）")
                continue
            ok, reason = rm.check_push(sig)
            if not ok:
                print(f"   [{sym}] 有信号但被风控拦截：{reason}")
                jr.record_note(f"{sym} 信号被风控拦截：{reason}")
                continue
            pos = risk_push.compute_position(
                sig["entry"], sig["stop"],
                config.TRADER["account_size"], config.TRADER["risk_percent"],
            )
            lev = risk_push.recommend_leverage(sym, sig["entry"], sig["stop"])
            alert = risk_push.format_alert(sig, pos, lev)
            risk_push.push(alert, sym)
            jr.record_signal(sig)
            rm.add_open_signal(sig)
            print(f"   [{sym}] ✅ 已推送 + 已记录（{sig['num_triggered']}条：{'、'.join(sig['triggered'])}）")
        else:
            print(f"   [{sym}] 无进场信号（{sig['num_triggered']}条，需≥{config.ENTRY_MIN_CONFIRM}条）")


def run_followup() -> None:
    """跟踪「没开」的信号，事后补「如果开了走到几 R」。"""
    print("===== 后续走势跟踪 =====")
    jr = Journal()
    data, _ = get_data()
    trades = jr._read_trades()
    for t in trades:
        if t["opened"] is False:
            df1h = data.get(t["symbol"], {}).get(config.INTERVAL_ENTRY)
            if df1h is not None:
                res = jr.followup(t["id"], df1h)
                if res:
                    print(f"   {t['id']} {t['symbol']}: 最高 +{res['max_r']}R，最低 {res['min_r']}R")


def run_testpush() -> None:
    """发一条测试消息，验证手机推送通道通了没。"""
    risk_push.push(
        "【测试】你的交易提醒机器人已上线，推送通道正常。\n"
        "以后出现符合规则的机会（附进场区/止损/目标/仓位）会在这里通知你，开不开单永远你决定。",
        "测试",
    )


def run_daily_review() -> None:
    """早上 9 点复盘。"""
    now = datetime.now().astimezone()
    yday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"===== 每日复盘 {yday} =====")
    jr = Journal()
    data, _ = get_data()

    # 昨日信号简述
    lines = []
    for t in jr._read_trades():
        if t["time"].startswith(yday):
            r = t["result_r"]
            rstr = f"{r:+}R" if r is not None else "未处理"
            lines.append(f"- {t['symbol']} {t['direction']}：触发{'、'.join(t['triggered'])}，结果 {rstr}")
    signals_md = "\n".join(lines) if lines else "- 昨日无信号"
    review = jr.daily_review(yday, signals_md)

    # 今日方向与关键价位
    for sym in config.SYMBOLS:
        df4h = data[sym][config.INTERVAL_DIRECTION]
        df1h = data[sym][config.INTERVAL_ENTRY]
        if df4h is not None and df1h is not None:
            trend, reason = signals.trend_state(df4h)
            last = df1h.iloc[-1]
            review += (f"\n[{sym}] 今日 4h={trend}；EMA20={last['ema_fast']:,.0f} "
                       f"EMA50={last['ema_slow']:,.0f}；现价 {last['close']:,.0f}")
        else:
            review += f"\n[{sym}] 数据缺失（未验证）"

    # 今日事件
    events = [e for e in config.EVENTS if e["time"].startswith(now.strftime("%Y-%m-%d"))]
    review += "\n今日注意事件：" + ("、".join(f"{e['name']} {e['time'][11:16]}" for e in events) if events else "无（详见 EVENTS）")

    print(review)
    # 写进复盘存档
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (config.OUTPUT_DIR / "reviews.md").open("a", encoding="utf-8").write(
        f"\n--- {now:%Y-%m-%d %H:%M} ---\n{review}\n")
    # 推到手机
    risk_push.push(review, "每日复盘")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        run_check()
    elif cmd == "review":
        run_daily_review()
    elif cmd == "followup":
        run_followup()
    elif cmd == "testpush":
        run_testpush()
    else:
        print("用法：python main.py [check|review|followup|testpush]")
