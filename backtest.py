# -*- coding: utf-8 -*-
"""
backtest.py —— 端到端历史回放验证

大白话：把机器人「送回过去」，用真实历史 K 线逐根跑，
看看当时它给出的信号，如果真开了，最后会走到 1R/2R/3R 还是打止损。
目的：检验规则灵不灵，不是算收益、更不承诺收益。

跑法（trading-bot 目录下）：python backtest.py

重要假设（保守）：
  - 以「信号那根 1h 的收盘价」作为进场；
  - 同一根 K 线里若同时触及止损和目标，按「先打止损」处理（更保守）；
  - 只做多，4h 看空时不给信号。
"""
from __future__ import annotations

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import config
import data_fetch
import indicators
import signals


def simulate_long(df1h, idx, entry, stop, targets):
    """从 idx 之后逐根看：先触发什么。返回 (R结果, 结局)。None=数据末尾还没触发。"""
    r = entry - stop
    t1, t2, t3 = targets["1R"], targets["2R"], targets["3R"]
    for j in range(idx + 1, len(df1h)):
        low, high = df1h["low"].iloc[j], df1h["high"].iloc[j]
        if low <= stop:            # 保守：先看是否打止损
            return -1.0, "止损"
        if high >= t3:
            return 3.0, "3R"
        if high >= t2:
            return 2.0, "2R"
        if high >= t1:
            return 1.0, "1R"
    return None, "未触发"


def run(symbol):
    df4h = data_fetch.load_klines("spot", symbol, "4h")
    df1h = data_fetch.load_klines("spot", symbol, "1h")
    if df4h is None or df1h is None:
        print(f"[{symbol}] 缓存缺失，请先跑 test_data_fetch.py")
        return []
    df4h = indicators.compute_indicators(df4h)
    df1h = indicators.compute_indicators(df1h)

    results = []
    n = len(df1h)
    for idx in range(80, n - 1):   # 80 起留足指标预热；-1 保证后面还有K线可看结果
        sig = signals.build_signal(symbol, df4h, df1h, at=idx)
        if sig is None or not sig["is_signal"]:
            continue
        r, reason = simulate_long(df1h, idx, sig["entry"], sig["stop"], sig["targets"])
        results.append({
            "time": str(sig["time"]),
            "trend": sig["trend_4h"],
            "strength": sig["strength"],
            "num": sig["num_triggered"],
            "triggered": sig["triggered"],
            "rr_ok": sig["rr_ok"],
            "outcome": reason,
            "r": r,
        })
    return results


def summarize(label, rows):
    if not rows:
        return
    total = len(rows)
    settled = [x for x in rows if x["r"] is not None]
    wins = [x for x in settled if x["r"] > 0]
    total_r = sum(x["r"] for x in settled)
    from collections import Counter
    dist = Counter(x["outcome"] for x in rows)
    print(f"\n【{label}】共 {total} 个")
    print(f"  结局分布：{dict(dist)}")
    if settled:
        print(f"  胜率 {len(wins)/len(settled):.0%}，累计 {total_r:+.1f}R（{len(settled)} 笔已出结果）")
    # 触发条件频率
    conds = Counter()
    for x in rows:
        for c in x["triggered"]:
            conds[c] += 1
    print(f"  触发条件频率：{dict(conds)}")


def main():
    print("===== 历史回放验证（约最近 500 根 1h ≈ 3 周）=====")
    for symbol in config.SYMBOLS:
        rows = run(symbol)
        pushed = [x for x in rows if x["trend"] == "long" and x["rr_ok"]]
        downgraded = [x for x in rows if x["trend"] == "long" and not x["rr_ok"]]
        ranging = [x for x in rows if x["trend"] == "range"]
        summarize(f"{symbol} 可推送信号", pushed)
        summarize(f"{symbol} 盈亏比不足（降级观察）", downgraded)
        summarize(f"{symbol} 震荡期（只记录）", ranging)
    print("\n注：样本较小（约3周），只用于快速检验规则，不代表长期表现、不承诺收益。")


if __name__ == "__main__":
    main()
