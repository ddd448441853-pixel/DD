# -*- coding: utf-8 -*-
"""
signals.py —— 第 3 步：信号判断（机器人的「大脑」）

大白话：用第 2 步的指标，判断「现在该不该提醒你」。
分两层：
  1) 大方向（4h）：看多 / 看空 / 震荡
  2) 进场（1h）：四条规则至少满足两条，才算信号

只做多（long_only）：只有 4h 看多时才可能产生信号；
4h 震荡 → 只记录不推送；4h 看空 → 逆势，直接不产生信号。

信号里顺带算出：止损、1R/2R/3R 目标、最近阻力，判断盈亏比够不够。
"""
from __future__ import annotations

import pandas as pd

import config
import indicators


# ---------- 4h 大方向 ----------

def trend_state(df4h: pd.DataFrame) -> tuple[str, str]:
    """
    判断 4h 大方向。返回 (方向, 原因)。
    方向：'long' / 'short' / 'range'
    """
    last = df4h.iloc[-1]
    price = last["close"]
    ema20 = last["ema_fast"]
    ema50 = last["ema_slow"]
    if price > ema50 and ema20 > ema50:
        return "long", "价格在EMA50上方且EMA20>EMA50"
    if price < ema50 and ema20 < ema50:
        return "short", "价格在EMA50下方且EMA20<EMA50"
    return "range", "EMA20与EMA50缠绕，方向不明（震荡）"


# ---------- 1h 四条进场条件（只做多） ----------

def _touched_ema_zone(df: pd.DataFrame, idx: int) -> bool:
    """条件①：最近几根里，低点是否回踩进 EMA20~EMA50 之间。"""
    for j in range(max(1, idx - config.PULLBACK_LOOKBACK), idx + 1):
        ema20 = df["ema_fast"].iloc[j]
        ema50 = df["ema_slow"].iloc[j]
        low = df["low"].iloc[j]
        if low <= ema20 and low >= ema50:
            return True
    return False


def _bullish_reversal(df: pd.DataFrame, idx: int) -> bool:
    """条件①的「反转K线」：前一根阴线，当前阳线且收复前一根开盘价。"""
    c = df.iloc[idx]
    p = df.iloc[idx - 1]
    return p["close"] < p["open"] and c["close"] > c["open"] and c["close"] > p["open"]


def _breakout_retest(df: pd.DataFrame, idx: int) -> bool:
    """条件②：突破前高后回踩确认（收盘仍站在前高之上）。"""
    sh = indicators.recent_swing_high(df, k=config.SWING_LOOKBACK, before=idx)
    if sh is None:
        return False
    _, high_price = sh
    recent = df.iloc[idx - 2: idx + 1]     # 最近3根（含当前）
    broke = bool(recent["close"].max() > high_price)
    retested = bool(recent["low"].min() <= high_price)
    held = bool(df["close"].iloc[idx] > high_price)
    return broke and retested and held


def _rsi_turn_up_from_oversold(df: pd.DataFrame, idx: int) -> bool:
    """条件③之一：RSI 最近从超卖区（<30）拐头向上、回到 30 上方。"""
    for j in range(max(1, idx - 3), idx + 1):
        if df["rsi"].iloc[j - 1] < config.RSI_OVERSOLD and df["rsi"].iloc[j] >= config.RSI_OVERSOLD:
            return True
    return False


def _bullish_divergence(df: pd.DataFrame, idx: int) -> bool:
    """条件③之二：价格创新低，但 RSI 没创新低（底背离）。"""
    sub = df.iloc[max(0, idx - config.DIVERGENCE_LOOKBACK): idx]
    if len(sub) < config.SWING_LOOKBACK * 2 + 2:
        return False
    mask = indicators._swing_low_mask(sub, config.SWING_LOOKBACK)
    idxs = sub.index[mask]
    if len(idxs) < 2:
        return False
    # 取最后两个摆动低点比较
    a = int(sub.index.get_loc(idxs[-2]))
    b = int(sub.index.get_loc(idxs[-1]))
    price_lower = bool(sub["low"].iloc[b] < sub["low"].iloc[a])
    rsi_higher = bool(sub["rsi"].iloc[b] > sub["rsi"].iloc[a])
    return price_lower and rsi_higher


def _volume_breakout(df: pd.DataFrame, idx: int) -> bool:
    """条件④：放量（>1.5倍20均量）且收盘突破前 N 根最高价。"""
    vol_ratio = df["vol_ratio"].iloc[idx]
    if pd.isna(vol_ratio) or vol_ratio < config.VOLUME_SPIKE_MULT:
        return False
    prior_high = df["high"].iloc[max(0, idx - config.BREAKOUT_LOOKBACK): idx].max()
    return bool(df["close"].iloc[idx] > prior_high)


def evaluate_entry(df1h: pd.DataFrame, idx: int) -> dict[str, bool]:
    """在 1h 的第 idx 根，判断四条进场条件各自是否成立。"""
    return {
        "回踩EMA后反转": _touched_ema_zone(df1h, idx) and _bullish_reversal(df1h, idx),
        "突破前高回踩确认": _breakout_retest(df1h, idx),
        "RSI超卖拐头+背离": _rsi_turn_up_from_oversold(df1h, idx) and _bullish_divergence(df1h, idx),
        "放量突破": _volume_breakout(df1h, idx),
    }


# ---------- 止损 / 目标 / R ----------

def nearest_resistance_above(df1h: pd.DataFrame, entry: float, idx: int):
    """找进场价上方「最近」的阻力（最近一个高于 entry 的摆动高点）。没有则 None。"""
    sub = df1h.iloc[:idx + 1]
    mask = indicators._swing_high_mask(sub, config.SWING_LOOKBACK)
    highs = sub.loc[mask, "high"]
    above = highs[highs > entry]
    if len(above) == 0:
        return None
    return float(above.iloc[-1])


def compute_stop_targets(df1h: pd.DataFrame, idx: int) -> dict:
    """
    按规则算 止损 / 目标 / R：
      止损 = 最近摆动低点 − 0.5×ATR
      R = 进场价 − 止损价
      目标 = 进场 + R / 2R / 3R
    """
    entry = float(df1h["close"].iloc[idx])
    atr_now = float(df1h["atr"].iloc[idx])

    sl = indicators.recent_swing_low(df1h, k=config.SWING_LOOKBACK, before=idx + 1)
    if sl is None:
        sl = (idx, entry)  # 兜底：找不到摆动低点就用当前价（理论上极少发生）
    stop = sl[1] - config.ATR_STOP_MULT * atr_now

    r_dist = entry - stop
    if r_dist <= 0:
        r_dist = atr_now  # 兜底：异常时用 1 个 ATR 当 R，避免除零

    res = nearest_resistance_above(df1h, entry, idx)
    return {
        "entry": entry,
        "stop": stop,
        "atr": atr_now,
        "r": r_dist,
        "target_1r": entry + r_dist,
        "target_2r": entry + 2 * r_dist,
        "target_3r": entry + 3 * r_dist,
        "nearest_resistance": res,
    }


# ---------- 汇总：一个信号 ----------

def build_signal(symbol: str, df4h: pd.DataFrame, df1h: pd.DataFrame,
                 at: int | None = None) -> dict | None:
    """
    综合判断一个标的当前是否产生「可推送的多头信号」。
    返回信号字典；不满足则返回 None。
    """
    idx = at if at is not None else len(df1h) - 1

    # 大方向必须用「该 1h 收盘时刻之前」的 4h 数据，避免回放时偷看未来
    ts = df1h["close_time"].iloc[idx]
    trend_df = df4h[df4h["close_time"] <= ts]
    if len(trend_df) == 0:
        trend_df = df4h  # 兜底：实在没有就用全部
    trend, trend_reason = trend_state(trend_df)
    # 只做多：4h 看空直接不产生信号（逆势）
    if trend == "short":
        return None

    conds = evaluate_entry(df1h, idx)
    triggered = [name for name, ok in conds.items() if ok]
    n = len(triggered)

    stop_info = compute_stop_targets(df1h, idx)
    rr_ok = True
    res = stop_info["nearest_resistance"]
    if res is not None:
        rr_ok = (res - stop_info["entry"]) >= config.MIN_RR * stop_info["r"]

    is_signal = n >= config.ENTRY_MIN_CONFIRM
    # 震荡期：只记录不推送 → 在这里用 trend_ok 标记，交给上层决定推不推
    signal = {
        "symbol": symbol,
        "direction": "long",
        "interval": config.INTERVAL_ENTRY,
        "trend_4h": trend,
        "trend_reason": trend_reason,
        "conditions": conds,
        "triggered": triggered,
        "num_triggered": n,
        "is_signal": is_signal,
        "strength": "A" if n >= 4 else ("B" if n == 3 else "C"),
        "entry": stop_info["entry"],
        "stop": stop_info["stop"],
        "atr": stop_info["atr"],
        "r": stop_info["r"],
        "targets": {
            "1R": stop_info["target_1r"],
            "2R": stop_info["target_2r"],
            "3R": stop_info["target_3r"],
        },
        "nearest_resistance": res,
        "rr_ok": rr_ok,
        "time": df1h["close_time"].iloc[idx],
    }
    return signal
