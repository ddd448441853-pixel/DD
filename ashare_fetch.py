# -*- coding: utf-8 -*-
"""
ashare_fetch.py —— A 股行情获取（免费公开接口，无需 key）

数据源策略：新浪为主，东方财富为备（东财会按 IP 限流，新浪更宽松）。
  - 日线   ：新浪 scale=240 / 东财 klt=101
  - 60分钟 ：新浪 scale=60  / 东财 klt=60

只保留「已收盘」的 K 线，未收盘的那根丢掉。

secid 规则：1=沪市(sh)，0=深市(sz)。如 1.510300 / 0.159915。
"""
from __future__ import annotations

import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

import pandas as pd

import ashare_config

SINA_URL = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
EASTMONEY_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

_MIN_GAP = 0.6
_last_req = 0.0

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Referer": "https://finance.sina.com.cn/",
    "Accept": "*/*",
}


def now_beijing() -> datetime:
    """当前北京时间（不带时区），云端 UTC 也能算对。"""
    return (datetime.now(timezone.utc) + timedelta(hours=8)).replace(tzinfo=None)


def _throttle():
    global _last_req
    wait = _MIN_GAP - (time.time() - _last_req)
    if wait > 0:
        time.sleep(wait)
    _last_req = time.time()


def _secid_to_sina(secid: str) -> str:
    market, code = secid.split(".")
    return ("sh" if market == "1" else "sz") + code


def _http_json(url: str, timeout: int = 15):
    """带节流+重试的 GET，返回解析后的 JSON（失败返回 None）。"""
    for attempt in range(3):
        _throttle()
        req = urllib.request.Request(url, headers=_HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError):
            if attempt < 2:
                time.sleep(1.5)
                continue
            return None
    return None


def _sina_fetch(secid: str, klt: int) -> list[tuple] | None:
    scale = 240 if klt == 101 else 60
    url = f"{SINA_URL}?symbol={_secid_to_sina(secid)}&scale={scale}&ma=no&datalen=400"
    raw = _http_json(url)
    if not raw or not isinstance(raw, list):
        return None
    rows = []
    for it in raw:
        try:
            rows.append((it["day"], float(it["open"]), float(it["high"]),
                         float(it["low"]), float(it["close"]), float(it["volume"])))
        except (KeyError, ValueError, TypeError):
            continue
    return rows or None


def _eastmoney_fetch(secid: str, klt: int, lookback_days: int) -> list[tuple] | None:
    beg = (now_beijing() - timedelta(days=lookback_days)).strftime("%Y%m%d")
    url = (f"{EASTMONEY_URL}?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
           f"&fields2=f51,f52,f53,f54,f55,f56&klt={klt}&fqt=1"
           f"&beg={beg}&end=20500101&lmt=1000")
    raw = _http_json(url)
    try:
        klines = raw["data"]["klines"]
    except (TypeError, KeyError):
        return None
    rows = []
    for line in klines:
        p = line.split(",")
        # 东财顺序：日期, 开, 收, 高, 低, 量
        rows.append((p[0], float(p[1]), float(p[3]), float(p[4]), float(p[2]), float(p[5])))
    return rows or None


def fetch_klines(secid: str, klt: int, lookback_days: int = 400) -> pd.DataFrame | None:
    """
    拉 K 线（新浪优先，东财兜底），返回 DataFrame：
    open_time/open/high/low/close/volume/close_time，仅含已收盘 K 线。
    """
    rows = _sina_fetch(secid, klt)
    if rows is None:
        print(f"[新浪失败] {secid} klt={klt}，改用东财…")
        rows = _eastmoney_fetch(secid, klt, lookback_days)
    if rows is None:
        print(f"[A股数据全部失败] {secid} klt={klt}（标记未验证，不编造）")
        return None

    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["open_time"] = pd.to_datetime(df["ts"])
    if klt == 101:
        # 日线的收盘时刻是当天 15:00
        df["close_time"] = df["open_time"] + pd.Timedelta(hours=15)
    else:
        # 60 分钟 K 线标签即收盘时刻
        df["close_time"] = df["open_time"]

    now = now_beijing()
    df = df[df["close_time"] <= now].reset_index(drop=True)
    df = df.drop(columns=["ts"])
    df = df.sort_values("open_time").reset_index(drop=True)

    # 本地缓存（回放用）
    cache = ashare_config.BASE_DIR / "data" / f"ashare_{secid}_{klt}.csv"
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache, index=False)
    return df


def load_klines(secid: str, klt: int) -> pd.DataFrame | None:
    """读本地缓存。"""
    p = ashare_config.BASE_DIR / "data" / f"ashare_{secid}_{klt}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df["open_time"] = pd.to_datetime(df["open_time"])
    df["close_time"] = pd.to_datetime(df["close_time"])
    return df
