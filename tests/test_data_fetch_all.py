# -*- coding: utf-8 -*-
"""
测试：一键拉全（所有标的 × 所有周期）。
跑法（trading-bot 目录下）：python tests/test_data_fetch_all.py
"""
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import data_fetch


def test_fetch_all():
    result = data_fetch.fetch_all(market="spot")
    for symbol in config.SYMBOLS:
        assert symbol in result, f"缺标的 {symbol}"
        for interval in (config.INTERVAL_DIRECTION, config.INTERVAL_ENTRY):
            df = result[symbol][interval]
            assert df is not None, f"{symbol} {interval} 拉取失败"
            assert len(df) >= 100, f"{symbol} {interval} K线太少: {len(df)}"
            print(f"   {symbol} {interval}: {len(df)} 根，最新收盘 {df['close'].iloc[-1]} @ {df['close_time'].iloc[-1]}")
    print("✅ 一键拉全测试通过：所有标的 × 周期 数据齐备")


if __name__ == "__main__":
    test_fetch_all()
