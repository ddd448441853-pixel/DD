# -*- coding: utf-8 -*-
"""
测试：第 5 步 日志 + 复盘。
跑法（trading-bot 目录下）：python tests/test_journal.py
"""
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import config
from journal import Journal


def make_signal(symbol="BTCUSDT", entry=80000.0, stop=79500.0):
    return {
        "symbol": symbol, "direction": "long", "time": "2026-10-27 10:00:00",
        "entry": entry, "stop": stop,
        "targets": {"1R": entry + 500, "2R": entry + 1000, "3R": entry + 1500},
        "triggered": ["突破前高回踩确认", "放量突破"], "strength": "B",
        "trend_4h": "long",
    }


def test_journal():
    tmp_trades = Path(config.OUTPUT_DIR) / "test_trades.jsonl"
    tmp_md = Path(config.OUTPUT_DIR) / "test_journal.md"
    for p in (tmp_trades, tmp_md):
        if p.exists():
            p.unlink()

    j = Journal(trades_file=tmp_trades, md_file=tmp_md)

    # 记录两个信号，一个开了(+1R)，一个没开
    id1 = j.record_signal(make_signal("BTCUSDT"))
    id2 = j.record_signal(make_signal("ETHUSDT", entry=2300.0, stop=2275.0))
    j.record_outcome(id1, opened=True, result_r=1.0, exit_price=80500.0, emotion="有点慌")
    j.record_outcome(id2, opened=False)

    # 统计：只有开了的那笔计入
    st = j.stats()
    assert st["total"] == 1, "只统计已结算的"
    assert st["wins"] == 1 and abs(st["total_r"] - 1.0) < 1e-6
    print(f"✅ 日志记录/统计测试通过：{st}")

    # 没开信号的「后续走势」
    df = pd.DataFrame({
        "open_time": pd.to_datetime(["2026-10-27 11:00", "2026-10-27 12:00", "2026-10-27 13:00"]),
        "high": [2320.0, 2360.0, 2330.0],
        "low": [2290.0, 2300.0, 2310.0],
    })
    fu = j.followup(id2, df)
    assert fu is not None and fu["max_r"] > 1.0, "最高应超过 1R"
    print(f"✅ 后续走势跟踪测试通过：最高 +{fu['max_r']}R，最低 {fu['min_r']}R")

    # md 文件内容检查
    md = tmp_md.read_text(encoding="utf-8")
    assert "BTCUSDT" in md and "开了" in md and "没开" in md
    print("✅ 交易日志.md 写入测试通过")

    # 每满 20 个信号汇总：现在只有 1 笔，应返回 None
    assert j.summary_20() is None

    # 模拟凑满 20 笔已结算
    for i in range(19):
        tid = j.record_signal(make_signal("BTCUSDT"))
        j.record_outcome(tid, opened=True, result_r=(1.0 if i % 2 == 0 else -1.0))
    s20 = j.summary_20()
    assert s20 is not None and "汇总" in s20
    print(f"✅ 每满20信号汇总测试通过：\n{s20}")

    for p in (tmp_trades, tmp_md):
        if p.exists():
            p.unlink()


if __name__ == "__main__":
    test_journal()
    print("\n🎉 第 5 步全部测试通过")
