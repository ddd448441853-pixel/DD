# -*- coding: utf-8 -*-
"""
data_fetch.py —— 第 1 步：数据获取

大白话：让机器人去 Binance 公开接口「下载历史 K 线」，
拿到 开盘价/最高价/最低价/收盘价/成交量（OHLCV）。
公开数据不需要 API Key，只能看、不能下单，安全。
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from pathlib import Path

import pandas as pd

import config

# Binance K 线接口返回的每一根 K 线是 12 个值的数组，含义如下：
KLINE_FIELDS = [
    "open_time",        # 0 开盘时间（毫秒）
    "open",             # 1 开盘价
    "high",             # 2 最高价
    "low",              # 3 最低价
    "close",            # 4 收盘价
    "volume",           # 5 成交量（基础币）
    "close_time",       # 6 收盘时间（毫秒）
    "quote_volume",     # 7 成交额（计价币，如 USDT）
    "trades",           # 8 成交笔数
    "taker_buy_base",   # 9 主动买入量（基础币）
    "taker_buy_quote",  # 10 主动买入额
    "ignore",           # 11 忽略
]


def _build_url(base: str, symbol: str, interval: str, limit: int) -> str:
    """根据 接口地址、标的、周期 拼出请求地址。"""
    return f"{base}?symbol={symbol}&interval={interval}&limit={limit}"


def _base_urls(market: str) -> list[str]:
    """现货/永续各自的一组候选接口地址，按顺序尝试。"""
    return config.SPOT_BASE_URLS if market == "spot" else config.FUTURES_BASE_URLS


def _cache_path(market: str, symbol: str, interval: str) -> Path:
    """本地缓存文件路径，用来回放和回测。"""
    return config.DATA_DIR / f"{market}_{symbol}_{interval}.csv"


def fetch_klines(symbol: str, interval: str, market: str = "spot",
                 limit: int | None = None, timeout: int = 15) -> pd.DataFrame | None:
    """
    拉取 K 线，成功返回 DataFrame（列含 open/high/low/close/volume/open_time 等）。
    失败返回 None（并在控制台打印原因），绝不编造数据。

    返回的 DataFrame 里：
      open_time / close_time  是时间（K 线开盘/收盘时刻）
      open/high/low/close     是价格
      volume                  是成交量
    """
    limit = limit or config.KLINES_LIMIT

    raw = None
    last_err = None
    for base in _base_urls(market):
        url = _build_url(base, symbol, interval, limit)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            break  # 成功就跳出，不再尝试下一个地址
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            last_err = e
            print(f"[数据获取失败] {base} ({symbol} {interval}): {e}，尝试下一个地址…")
        except json.JSONDecodeError as e:
            last_err = e
            print(f"[数据解析失败] {symbol} {interval}: {e}")
            break

    if raw is None:
        print(f"[全部数据源失败] {symbol} {interval} ({market})，已标记为「未验证」: {last_err}")
        return None

    if not raw:
        print(f"[空数据] {symbol} {interval} 接口返回为空")
        return None

    # 转成表格，并把价格/成交量变成数字
    df = pd.DataFrame(raw, columns=KLINE_FIELDS)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")

    # 丢掉价格/成交量缺失的坏行
    df = df.dropna(subset=["open", "high", "low", "close", "volume"]).reset_index(drop=True)

    # 存一份本地缓存，方便断网回放和历史回测
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(_cache_path(market, symbol, interval), index=False)

    return df


def load_klines(market: str, symbol: str, interval: str) -> pd.DataFrame | None:
    """从本地缓存读 K 线（回放/回测用），没缓存则返回 None。"""
    p = _cache_path(market, symbol, interval)
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df["open_time"] = pd.to_datetime(df["open_time"])
    df["close_time"] = pd.to_datetime(df["close_time"])
    return df


def fetch_all(market: str = "spot") -> dict:
    """
    按配置一次拉全所有「标的 × 周期」的 K 线。
    返回形如 { "BTCUSDT": {"4h": df, "1h": df}, "ETHUSDT": {...} }
    拉不到的记为 None（已在上游标「未验证」，不编造）。
    """
    result = {}
    for symbol in config.SYMBOLS:
        result[symbol] = {}
        for interval in (config.INTERVAL_DIRECTION, config.INTERVAL_ENTRY):
            result[symbol][interval] = fetch_klines(symbol, interval, market=market)
    return result
