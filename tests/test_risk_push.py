# -*- coding: utf-8 -*-
"""
测试：第 4 步 风控 + 推送。
跑法（trading-bot 目录下）：python tests/test_risk_push.py
"""
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import risk_push


def make_signal():
    return {
        "symbol": "BTCUSDT", "direction": "long", "interval": "1h",
        "trend_4h": "long", "trend_reason": "价格在EMA50上方且EMA20>EMA50",
        "triggered": ["突破前高回踩确认", "放量突破"],
        "num_triggered": 2, "strength": "B",
        "entry": 80000.0, "stop": 79500.0, "atr": 400.0, "r": 500.0,
        "targets": {"1R": 80500.0, "2R": 81000.0, "3R": 81500.0},
        "nearest_resistance": 81200.0, "rr_ok": True,
        "time": "2026-10-27 15:00:00",
    }


def test_position():
    pos = risk_push.compute_position(80000, 79500, 50000, 0.01)
    assert abs(pos["risk_amount"] - 500.0) < 1e-6, "风险金额应 = 5万×1% = 500"
    assert abs(pos["qty"] - 1.0) < 1e-6, "数量应 = 500/500 = 1"
    assert abs(pos["notional"] - 80000.0) < 1e-6
    print(f"✅ 仓位测试通过：qty={pos['qty']}，风险金额={pos['risk_amount']}")


def test_leverage():
    lev = risk_push.recommend_leverage("BTCUSDT", 80000, 79500)
    assert lev["liq"] < 79500, "强平价必须在止损之外（之下）"
    assert lev["liq_below_stop"] > 0
    print(f"✅ 杠杆/强平价测试通过：推荐{lev['leverage']}x，强平价{lev['liq']:.0f}，"
          f"在止损之下 {lev['liq_below_stop']:.0f}")


def test_alert():
    sig = make_signal()
    pos = risk_push.compute_position(sig["entry"], sig["stop"], 50000, 0.01)
    lev = risk_push.recommend_leverage(sig["symbol"], sig["entry"], sig["stop"])
    text = risk_push.format_alert(sig, pos, lev)
    lines = text.splitlines()
    assert len(lines) <= config.ALERT_MAX_LINES, f"超过 {config.ALERT_MAX_LINES} 行：{len(lines)} 行"
    for kw in ["做多", "触发", "止损", "1R", "强度", "失效"]:
        assert kw in text, f"文案缺关键字 {kw}"
    print("✅ 推送文案测试通过：")
    print(text)


def test_risk_manager():
    tmp = Path(config.OUTPUT_DIR) / "test_risk_state.json"
    if tmp.exists():
        tmp.unlink()
    rm = risk_push.RiskManager(state_path=tmp)
    now = datetime(2026, 10, 27, 15, 0)   # 15:00 在「14-18点」可看时段内

    sig = make_signal()
    ok, _ = rm.check_push(sig, now=now)
    assert ok, "初始状态应能推"

    # 塞满 2 个未处理信号后，第 3 个应被拦
    rm.add_open_signal(sig)
    rm.add_open_signal(sig)
    ok, reason = rm.check_push(sig, now=now)
    assert not ok and "上限" in reason
    print(f"✅ 未处理信号上限测试通过：{reason}")

    # 清空，测连亏暂停
    rm.state["open_signals"] = []
    rm.record_result(-1.0)
    rm.record_result(-1.0)
    ok, reason = rm.check_push(sig, now=now)
    assert not ok and "暂停" in reason
    print(f"✅ 连亏暂停测试通过：{reason}")

    # 测单日亏损 3R 停推
    rm.state["paused_until"] = None
    rm.state["consecutive_losses"] = 0
    rm.state["daily_loss_r"] = 3.0
    ok, reason = rm.check_push(sig, now=now)
    assert not ok and "3.0R" in reason
    print(f"✅ 单日亏损停推测试通过：{reason}")

    if tmp.exists():
        tmp.unlink()


if __name__ == "__main__":
    test_position()
    test_leverage()
    test_alert()
    test_risk_manager()
    print("\n🎉 第 4 步全部测试通过")
