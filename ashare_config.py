# -*- coding: utf-8 -*-
"""
ashare_config.py —— A 股机器人参数（只改这里）

标的用 secid：1=沪市，0=深市。想加个股，例如：
  贵州茅台 600519 → "1.600519"
  平安银行 000001 → "0.000001"
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# 监控标的（默认挑 3 只最活跃的宽基 ETF：成交大、流动性好、不用怕单只个股暴雷）
WATCHLIST = [
    {"secid": "1.510300", "name": "沪深300ETF"},
    {"secid": "1.510500", "name": "中证500ETF"},
    {"secid": "0.159915", "name": "创业板ETF"},
]

# 周期：日线定方向 + 60 分钟找进场（A股 T+1，做中线更稳妥）
KL_DEPT_DIRECTION = 101   # 日线
KL_DEPT_ENTRY = 60        # 60 分钟
DIRECTION_LABEL = "日线"
ENTRY_LABEL = "60m"

# 数据回溯天数（够算 EMA/RSI/ATR 就行，不用拉全历史）
LOOKBACK_DIRECTION = 900  # 日线约 2.5 年
LOOKBACK_ENTRY = 150      # 60分钟约 3 个月

# 风控（A股版：中等严格）
RISK_PARAMS = {
    "max_open": 3,            # 最多 3 个未处理信号
    "max_consecutive": 3,     # 连亏 3 笔暂停
    "pause_hours": 12,        # 暂停 12 小时
    "daily_max_r": 3.0,       # 单日亏 3R 停推
    "check_hours": [(9, 15)], # 只在 A 股交易时段（9:00-15:59）推
}

# A 股交易时段（北京时间）
SESSIONS = [("09:30", "11:30"), ("13:00", "15:00")]
