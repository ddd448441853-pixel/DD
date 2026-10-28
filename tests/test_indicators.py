# -*- coding: utf-8 -*-
"""
测试：第 2 步 指标计算。
跑法（trading-bot 目录下）：python tests/test_indicators.py
用第 1 步缓存的真实 BTC 1h 数据 + 一份合成数据，双重验证。
"""
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

import data_fetch
import indicators


def test_on_real_data():
    df = data_fetch.load_klines("spot", "BTCUSDT", "1h")
    assert df is not None, "没有缓存数据，请先跑 test_data_fetch.py"
    out = indicators.compute_indicators(df)

    # 列齐全
    for col in ["ema_fast", "ema_slow", "rsi", "atr", "vol_ma", "vol_ratio"]:
        assert col in out.columns, f"缺列 {col}"

    # 数值范围合理（去掉预热期的 NaN 再查）
    assert out["rsi"].dropna().between(0, 100).all(), "RSI 超出 0~100"
    assert (out["atr"].dropna() > 0).all(), "ATR 出现非正数"
    assert (out["ema_fast"].dropna() > 0).all() and (out["ema_slow"].dropna() > 0).all()

    # 预热后（最后 50 根）不应有 NaN
    tail = out.iloc[-50:]
    for col in ["ema_fast", "ema_slow", "rsi", "atr", "vol_ma", "vol_ratio"]:
        assert tail[col].notna().all(), f"{col} 在尾部出现 NaN"

    # 摆动点能找到
    sl = indicators.recent_swing_low(out)
    sh = indicators.recent_swing_high(out)
    assert sl is not None and sh is not None, "找不到摆动点"

    print("✅ 指标计算测试通过（真实 BTC 1h 数据）")
    last = out.iloc[-1]
    print(f"   EMA20={last['ema_fast']:.2f}  EMA50={last['ema_slow']:.2f}"
          f"  RSI={last['rsi']:.1f}  ATR={last['atr']:.2f}")
    print(f"   最近摆动低点=#{sl[0]} 价{sl[1]:.2f}  最近摆动高点=#{sh[0]} 价{sh[1]:.2f}")


def test_on_synthetic_data():
    """合成数据自检：纯上涨 → RSI 应偏高、EMA20 应在 EMA50 之上。"""
    n = 200
    close = np.linspace(100, 300, n)  # 一路涨
    high = close + 5
    low = close - 5
    volume = np.full(n, 100.0)
    df = pd.DataFrame({
        "open": close - 1, "high": high, "low": low,
        "close": close, "volume": volume,
    })
    out = indicators.compute_indicators(df)
    assert out["rsi"].iloc[-1] > 60, "纯上涨行情 RSI 应该偏高"
    assert out["ema_fast"].iloc[-1] > out["ema_slow"].iloc[-1], "上涨时 EMA20 应在 EMA50 之上"
    assert out["atr"].iloc[-1] > 0
    print("✅ 指标计算自检通过（合成上涨数据：RSI 高、EMA20>EMA50）")


if __name__ == "__main__":
    test_on_real_data()
    test_on_synthetic_data()
