# -*- coding: utf-8 -*-
"""
config.py —— 机器人所有「可调参数」都集中在这里。

大白话：以后你想改规则（比如换标的、改风险、改推送时段），
第一件事就是改这个文件，同时记得同步更新《交易档案.md》。
"""
import os
from pathlib import Path

# ---- 路径 ----
BASE_DIR = Path(__file__).resolve().parent          # trading-bot 目录（也是云端仓库根目录）
DATA_DIR = BASE_DIR / "data"                        # 本地 K 线缓存（用于回放/回测）
OUTPUT_DIR = BASE_DIR / "output"                    # 推送存档、风控状态、结构化交易记录
JOURNAL_FILE = BASE_DIR / "交易日志.md"              # 交易日志，放在项目里（随仓库一起存云端）

# ---- 我的基本情况（来自 交易档案.md 的访谈结果）----
TRADER = {
    "experience": "新手",            # 完全新手：说明用大白话，风控提示保守
    "direction": "long_only",        # 只做多：空头信号一律不推
    "risk_percent": 0.01,            # 单笔风险 1%
    "account_size": 50000.0,         # 示例账户 5 万；正式使用时改成你的真实金额
    "check_hours": [(8, 12), (14, 18)],  # 能看手机的时段（24小时制，闭区间）
}

# ---- 监控标的 ----
SYMBOLS = ["BTCUSDT", "ETHUSDT"]

# ---- 数据源（Binance 公开接口，无需 API Key）----
# 按顺序尝试，谁通就用谁。data-api.binance.vision 是官方「只读行情」镜像站，
# 只能看行情、不能下单，正好符合「绝不下单」的要求；部分网络下主站可能连不上。
SPOT_BASE_URLS = [
    "https://data-api.binance.vision/api/v3/klines",   # 官方行情镜像（推荐，通常更稳）
    "https://api.binance.com/api/v3/klines",           # 现货主站
]
FUTURES_BASE_URLS = [
    "https://fapi.binance.com/fapi/v1/klines",         # U 本位永续
]
INTERVAL_DIRECTION = "4h"   # 大方向周期
INTERVAL_ENTRY = "1h"       # 进场周期
KLINES_LIMIT = 500          # 每次拉取多少根 K 线

# ---- 指标参数 ----
EMA_FAST = 20               # 快线 EMA 周期
EMA_SLOW = 50               # 慢线 EMA 周期
RSI_PERIOD = 14             # RSI 周期
ATR_PERIOD = 14             # ATR 周期
VOLUME_MA_PERIOD = 20       # 成交量均线周期
VOLUME_SPIKE_MULT = 1.5     # 放量倍数（> 近20根均量的1.5倍）

# ---- 进场条件（1h，至少满足 2 条才算信号）----
ENTRY_MIN_CONFIRM = 2
RSI_OVERSOLD = 30           # RSI 超卖阈值
RSI_OVERBOUGHT = 70         # RSI 超买阈值
SWING_LOOKBACK = 3          # 摆动点判定的左右回看根数
PULLBACK_LOOKBACK = 5       # 判断「回踩 EMA」回看几根
BREAKOUT_LOOKBACK = 20      # 判断「突破前高/放量突破」回看几根
DIVERGENCE_LOOKBACK = 60    # 判断 RSI 背离回看几根

# ---- 止损与 R ----
ATR_STOP_MULT = 0.5         # 止损 = 结构位外侧 + 0.5×ATR
MIN_RR = 1.5                # 最近阻力离进场 < 1.5R → 盈亏比不足，降级观察

# ---- 风控 ----
MAX_OPEN_SIGNALS = 2        # 同一时间最多 2 个未处理信号
MAX_CONSECUTIVE_LOSSES = 2  # 连续亏损 2 笔 → 暂停推送
PAUSE_HOURS = 12            # 暂停 12 小时
DAILY_MAX_LOSS_R = 3.0      # 单日累计亏损达 3R → 当天停止推送

# ---- 推送（文字控制在 10 行内）----
ALERT_MAX_LINES = 10
LEVERAGE_OPTIONS = [1, 2, 3, 5, 10]   # 可选杠杆档位
LEVERAGE_SAFETY = 0.85               # 留安全余量：只推荐「最大安全杠杆×0.85」以内的档位
# 维持保证金率（近似，Binance 最低档）：用于估算强平价
MAINTENANCE_MARGIN = {"BTCUSDT": 0.005, "ETHUSDT": 0.01, "DEFAULT": 0.005}
# 推送渠道：serverchan(Server酱，推荐，微信收) / wecom(企业微信) / dingtalk(钉钉) / generic
# 云端：用环境变量 PUSH_WEBHOOK_URL、PUSH_CHANNEL 注入（GitHub Secret），本地：直接改下面两行
PUSH_CHANNEL = os.environ.get("PUSH_CHANNEL") or "serverchan"
PUSH_WEBHOOK_URL = os.environ.get("PUSH_WEBHOOK_URL") or None
# 重大事件（CPI、议息等）：前后 1 小时不推新信号。
# 时间用北京时间字符串；日常由「Grok 实时搜索」补充，这里先手动维护。
EVENTS = [
    # {"name": "美联储议息会议", "time": "2026-11-05 02:00"},
    # {"name": "美国CPI", "time": "2026-11-12 20:30"},
]
