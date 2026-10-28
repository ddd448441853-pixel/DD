# -*- coding: utf-8 -*-
"""
测试：第 1 步 数据获取。

跑法（在 trading-bot 目录下）：
    python tests/test_data_fetch.py
通过 = 打印 ✅，失败 = 抛异常并显示原因。
"""
import sys
from pathlib import Path

# Windows 控制台默认 GBK，会打不出中文/emoji；这里强制 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import data_fetch


def test_fetch():
    df = data_fetch.fetch_klines("BTCUSDT", "1h", market="spot", limit=200)
    assert df is not None, "拉取失败：可能没网或被限制访问"

    # 1) 列要齐全
    for col in ["open", "high", "low", "close", "volume", "open_time"]:
        assert col in df.columns, f"缺列 {col}"

    # 2) 数值要合理：最高 >= 最低，最高 >= 开/收，最低 <= 开/收
    assert (df["high"] >= df["low"]).all(), "出现 最高价 < 最低价 的异常数据"
    assert (df["high"] >= df["open"]).all() and (df["high"] >= df["close"]).all()
    assert (df["low"] <= df["open"]).all() and (df["low"] <= df["close"]).all()
    assert (df["close"] > 0).all(), "出现非正数收盘价"

    # 3) K 线数量要够（用于后续算 EMA/ATR/RSI）
    assert len(df) >= 100, f"K 线太少：只有 {len(df)} 根"

    print("✅ 数据获取测试通过")
    print(f"   标的：BTC/USDT  周期：1h  共 {len(df)} 根 K 线")
    print(f"   最新一根收盘时间：{df['close_time'].iloc[-1]}")
    print(f"   最新收盘价：{df['close'].iloc[-1]}")
    return df


if __name__ == "__main__":
    test_fetch()
