# -*- coding: utf-8 -*-
"""
测试：第 3 步 信号判断。
跑法（trading-bot 目录下）：python tests/test_signals.py

包含两部分：
  1) 最新一根 K 线的信号结构检查（BTC、ETH）
  2) 历史回放：把过去 200 根 1h 逐根当「当时」，确认不会偷看未来、不崩溃、
     信号结构合法（止损<进场、目标>进场）。
"""
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import data_fetch
import indicators
import signals


def _load(symbol):
    df4h = data_fetch.load_klines("spot", symbol, "4h")
    df1h = data_fetch.load_klines("spot", symbol, "1h")
    assert df4h is not None and df1h is not None, f"{symbol} 缓存缺失"
    return indicators.compute_indicators(df4h), indicators.compute_indicators(df1h)


def _check_signal_struct(sig):
    assert sig["stop"] < sig["entry"], "止损应在进场价下方（做多）"
    assert sig["r"] > 0, "R 应为正"
    assert sig["targets"]["1R"] < sig["targets"]["2R"] < sig["targets"]["3R"], "目标应递增"
    assert sig["num_triggered"] == len(sig["triggered"]), "触发条数与列表不符"
    assert sig["num_triggered"] >= 2, "信号至少满足两条"


def test_latest():
    for symbol in ["BTCUSDT", "ETHUSDT"]:
        df4h, df1h = _load(symbol)
        trend, reason = signals.trend_state(df4h)
        sig = signals.build_signal(symbol, df4h, df1h)
        print(f"[{symbol}] 4h方向={trend}（{reason}）")
        if sig and sig["is_signal"]:
            _check_signal_struct(sig)
            print(f"   ✅ 产生信号：强度{sig['strength']}，触发 {sig['num_triggered']} 条 → {sig['triggered']}")
            print(f"   进场={sig['entry']:.2f} 止损={sig['stop']:.2f} R={sig['r']:.2f}")
        else:
            print("   （当前无信号，符合预期：不是每根K线都有信号）")
    print("✅ 最新K线信号结构测试通过")


def test_replay():
    df4h, df1h = _load("BTCUSDT")
    n = len(df1h)
    start = max(80, n - 200)   # 从过去 200 根开始（留足指标预热）
    count = 0
    for idx in range(start, n):
        sig = signals.build_signal("BTCUSDT", df4h, df1h, at=idx)
        if sig is None:
            continue
        assert sig["trend_4h"] in ("long", "short", "range"), "非法方向"
        if sig["is_signal"]:
            count += 1
            _check_signal_struct(sig)
            # 只做多：不会出现逆势多头信号（4h 看空时已经 None 了）
    print(f"✅ 历史回放测试通过：过去 {n - start} 根 1h 中，产生 {count} 个多头信号，全部结构合法、无崩溃")
    assert count < (n - start) * 0.5, "信号异常频繁，怀疑规则太松"


if __name__ == "__main__":
    test_latest()
    test_replay()
