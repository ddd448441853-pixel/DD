# -*- coding: utf-8 -*-
"""
indicators.py —— 第 2 步：指标计算

大白话：把原始 K 线「加工」成几个数学指标（尺子），
只算数、不给信号。这里造的尺子：
  EMA20 / EMA50（趋势方向）
  RSI(14)（超买超卖冷热计）
  ATR(14)（波动大小，用于定止损）
  近20根均量（判断是否放量）
  摆动高点 / 低点（结构位，用于定止损和支撑阻力）
"""
from __future__ import annotations

import pandas as pd

import config


def ema(series: pd.Series, period: int) -> pd.Series:
    """指数移动平均（EMA）。period=20 就是 EMA20。"""
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    """简单移动平均（SMA）。"""
    return series.rolling(period).mean()


def rsi(close: pd.Series, period: int) -> pd.Series:
    """
    RSI（相对强弱指标），0~100。
    用 Wilder 平滑（和主流看盘软件一致）。
    """
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi_val = 100.0 - 100.0 / (1.0 + rs)
    # 当 avg_loss=0（只涨不跌）时 RSI 应为 100
    rsi_val = rsi_val.where(avg_loss != 0, 100.0)
    return rsi_val


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    """
    ATR（平均真实波幅）：衡量最近波动有多大。
    TR = max(最高-最低, |最高-昨收|, |最低-昨收|)，再取 Wilder 平滑。
    """
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def volume_ma(df: pd.DataFrame, period: int) -> pd.Series:
    """成交量的简单移动平均（近 N 根均量）。"""
    return df["volume"].rolling(period).mean()


def _swing_low_mask(df: pd.DataFrame, k: int) -> pd.Series:
    """找出摆动低点：比左右各 k 根的最低点都低。返回布尔序列。"""
    low = df["low"]
    mask = pd.Series(True, index=df.index)
    for i in range(1, k + 1):
        mask &= (low <= low.shift(i)) & (low <= low.shift(-i))
    return mask


def _swing_high_mask(df: pd.DataFrame, k: int) -> pd.Series:
    """找出摆动高点：比左右各 k 根的最高点都高。返回布尔序列。"""
    high = df["high"]
    mask = pd.Series(True, index=df.index)
    for i in range(1, k + 1):
        mask &= (high >= high.shift(i)) & (high >= high.shift(-i))
    return mask


def recent_swing_low(df: pd.DataFrame, k: int = 3, before: int | None = None):
    """
    找「最近的摆动低点」：(序号, 价格)。
    before：只看序号 < before 的（用于回放时，避免用到未来数据）。
    找不到返回 None。
    """
    sub = df.iloc[:before] if before is not None else df
    mask = _swing_low_mask(sub, k)
    idxs = sub.index[mask]
    if len(idxs) == 0:
        return None
    last = idxs[-1]
    return int(sub.index.get_loc(last)), float(sub.loc[last, "low"])


def recent_swing_high(df: pd.DataFrame, k: int = 3, before: int | None = None):
    """找「最近的摆动高点」：(序号, 价格)。找不到返回 None。"""
    sub = df.iloc[:before] if before is not None else df
    mask = _swing_high_mask(sub, k)
    idxs = sub.index[mask]
    if len(idxs) == 0:
        return None
    last = idxs[-1]
    return int(sub.index.get_loc(last)), float(sub.loc[last, "high"])


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    给 K 线表一次性加上所有指标列，返回新表（不修改原表）。
    新增列：ema_fast, ema_slow, rsi, atr, vol_ma, vol_ratio
    """
    out = df.copy()
    out["ema_fast"] = ema(out["close"], config.EMA_FAST)          # EMA20
    out["ema_slow"] = ema(out["close"], config.EMA_SLOW)          # EMA50
    out["rsi"] = rsi(out["close"], config.RSI_PERIOD)             # RSI(14)
    out["atr"] = atr(out, config.ATR_PERIOD)                      # ATR(14)
    out["vol_ma"] = volume_ma(out, config.VOLUME_MA_PERIOD)       # 近20根均量
    out["vol_ratio"] = out["volume"] / out["vol_ma"]              # 量比（>1.5 视为放量）
    return out
