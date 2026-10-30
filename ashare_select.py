# -*- coding: utf-8 -*-
"""
ashare_select.py —— A 股「尾盘选股」模式（每天 14:30 之后跑一次）

它和趋势信号机器人是两套东西：这里不盯 K 线形态，而是每天扫全市场，
按你给的 6 大硬性条件筛出尾盘候选票，推到你手机。

6 大条件（缺一不可）：
  1) 涨幅 3% ~ 5%
  2) 20 天内有过涨停（涨停基因）
  3) 量比 > 1.4
  4) 总市值 < 200 亿
  5) 换手率 5% ~ 10%
  6) 当天分时全天在均价线上方

另外：
  - 自动排除名称含 ST / 退市的票
  - 大盘大跌或跌停过多时，直接提醒「空仓日」

用法：python ashare_select.py
"""
from __future__ import annotations

import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import ashare_fetch
import risk_push
import config

CLIST_HOSTS = [
    "https://push2.eastmoney.com",
    "https://82.push2.eastmoney.com",
    "https://66.push2.eastmoney.com",
]
TRENDS_URL = "https://push2.eastmoney.com/api/qt/stock/trends2/get"
INDEX_SECID = "1.000001"      # 上证指数
TRENDS_UT = "fa5fd1943c7b386f172d6893dbfba10b"   # 东财分时接口必需令牌

# ---- 6 大条件阈值（想调就改这里）----
PCT_MIN, PCT_MAX = 3.0, 5.0           # 涨幅区间
VOL_RATIO_MIN = 1.4                    # 量比下限
TURNOVER_MIN, TURNOVER_MAX = 5.0, 10.0 # 换手率区间
MCAP_MAX = 200e8                       # 总市值上限（200 亿）
LIMIT_UP_DAYS = 20                     # 涨停基因回看天数
MAX_PICKS = 3                          # 最多推荐几只

# 大盘环境
INDEX_DROP_LIMIT = -1.5                # 上证跌超 1.5% 视为大跌
LIMIT_DOWN_WARN = 30                   # 跌停家数超过 30 视为情绪冰点


def _get(url: str):
    """复用 ashare_fetch 里带节流/重试的请求。"""
    return ashare_fetch._http_json(url)


def _secid(code: str) -> str:
    return ("1." if code.startswith(("6", "9")) else "0.") + code


def _limit_pct(code: str) -> float:
    """该股票的涨停幅度：创业板/科创板 20%，其余 10%。"""
    return 20.0 if code.startswith(("688", "300", "301")) else 10.0


def _page_url(host: str, pn: int, po: int) -> str:
    return (f"{host}/api/qt/clist/get?pn={pn}&pz=100&po={po}&np=1&fltt=2&invt=2&fid=f3"
            "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
            "&fields=f2,f3,f8,f10,f12,f14,f20,f21")


def _parse_page(raw) -> list[dict]:
    data = (raw or {}).get("data") or {}
    diff = data.get("diff") or []
    if isinstance(diff, dict):
        diff = list(diff.values())
    out = []
    for q in diff:
        try:
            out.append({
                "code": str(q["f12"]),
                "name": str(q["f14"]),
                "price": float(q["f2"]),
                "pct": float(q["f3"]),
                "turnover": float(q["f8"]),
                "vol_ratio": float(q["f10"]),
                "mcap": float(q["f20"]),
                "fcap": float(q["f21"]),
            })
        except (KeyError, TypeError, ValueError):
            continue       # 停牌/异常数据跳过
    return out


def fetch_gainers(min_pct: float = PCT_MIN, max_pages: int = 40) -> list[dict]:
    """按涨幅降序分页，收集涨幅 >= min_pct 的股票（涨到 <min_pct 就停）。多镜像兜底。"""
    for host in CLIST_HOSTS:
        out = []
        for pn in range(1, max_pages + 1):
            raw = _get(_page_url(host, pn, 1))
            if raw is None:
                break                      # 该镜像失败，换下一个
            page = _parse_page(raw)
            if not page:
                break
            out.extend(page)
            if page[-1]["pct"] < min_pct:  # 已按降序，后面不可能再有
                break
        if out:
            return out
    return []


def count_limit_down() -> int | None:
    """
    统计跌停家数。只取「涨幅升序第 1 页」（最多 100 只最惨的），足够判断「跌停>=30」。
    失败或排序异常返回 None（未知），绝不用 0 冒充。
    """
    for host in CLIST_HOSTS:
        raw = _get(_page_url(host, 1, 0))
        if raw is None:
            continue
        page = _parse_page(raw)
        if not page:
            continue
        if page[0]["pct"] > 0:        # 升序页却以涨开头 => 排序异常
            return None
        n = 0
        for q in page:
            if q["code"].startswith(("300", "301", "688")):
                if q["pct"] <= -19.0:
                    n += 1
            elif q["pct"] <= -9.5:
                n += 1
        return n
    return None


def has_limit_up_20d(code: str) -> bool:
    """20 个交易日内是否出现过涨停。"""
    df = ashare_fetch.fetch_klines(_secid(code), 101, lookback_days=90)
    if df is None or len(df) < 3:
        return False
    recent = df.tail(LIMIT_UP_DAYS + 1)
    pct = recent["close"].pct_change() * 100
    return bool((pct >= _limit_pct(code) - 0.25).any())


VWAP_MAX_BELOW_RATIO = 0.08   # 允许约 8% 的分钟低于均价；越小越严格（0.02≈几乎全天在上方）


def above_vwap_today(code: str) -> bool:
    """
    当天分时是否「基本一直在均价线上方」：
      - 低于均价的分钟占比 <= VWAP_MAX_BELOW_RATIO
      - 且尾盘（最新一分钟）必须在均价上方
    """
    url = (f"{TRENDS_URL}?ut={TRENDS_UT}&secid={_secid(code)}&fields1=f1,f2,f3,f4,f5,f6,f7,f8"
           "&fields2=f51,f52,f53,f54,f55,f56,f57,f58&iscr=0&ndays=1")
    raw = _get(url)
    trends = ((raw or {}).get("data") or {}).get("trends") or []
    total = below = 0
    last_close = last_avg = None
    for line in trends:
        p = line.split(",")
        if len(p) < 8:
            continue
        try:
            close = float(p[2])      # 该分钟收盘
            avg = float(p[7])        # 均价线
        except ValueError:
            continue
        total += 1
        if close < avg * 0.995:      # 比均价低 0.5% 以上才算「跌下去」
            below += 1
        last_close, last_avg = close, avg
    if total == 0 or last_close is None:
        return False
    if last_close < last_avg:        # 尾盘必须仍在均价上方
        return False
    return (below / total) <= VWAP_MAX_BELOW_RATIO


def get_index_pct() -> float | None:
    """上证指数当日涨跌幅（%）。"""
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={INDEX_SECID}&fltt=2&fields=f170"
    raw = _get(url)
    try:
        return float(raw["data"]["f170"])
    except (TypeError, KeyError, ValueError):
        return None


def screen() -> tuple[list[dict], dict]:
    """执行选股，返回 (候选列表, 市场环境信息)。"""
    idx_pct = get_index_pct()
    lim_down = count_limit_down()

    market = {
        "index_pct": idx_pct,
        "limit_down": lim_down,
        "empty_day": (idx_pct is not None and idx_pct < INDEX_DROP_LIMIT) or (lim_down is not None and lim_down >= LIMIT_DOWN_WARN),
    }
    if market["empty_day"]:
        return [], market          # 空仓日不跑第二轮，省请求、防限流

    gainers = fetch_gainers()

    # 第一层：实时指标硬筛
    stage1 = []
    for q in gainers:
        name = q["name"]
        if "ST" in name or "退" in name:
            continue
        if not (PCT_MIN <= q["pct"] <= PCT_MAX):
            continue
        if q["vol_ratio"] < VOL_RATIO_MIN:
            continue
        if not (TURNOVER_MIN <= q["turnover"] <= TURNOVER_MAX):
            continue
        if q["mcap"] >= MCAP_MAX:
            continue
        stage1.append(q)

    # 第二层：涨停基因 + 分时均价线
    final = []
    for q in stage1:
        if not has_limit_up_20d(q["code"]):
            continue
        if not above_vwap_today(q["code"]):
            continue
        final.append(q)

    final.sort(key=lambda x: x["vol_ratio"], reverse=True)
    return final[:MAX_PICKS], market


def format_alert(cands: list[dict], market: dict) -> str:
    now = ashare_fetch.now_beijing()          # 用北京时间，避免云端显示成 UTC
    ld = market["limit_down"]
    ld_s = f"跌停 {ld} 家" if ld is not None else "跌停数未知"
    lines = [f"📈 尾盘选股 {now:%m-%d %H:%M}"]

    if market["empty_day"]:
        lines.append("⚠️ 大盘大跌 / 跌停过多，今日建议【空仓】，只做观察。")
        if market["index_pct"] is not None:
            lines.append(f"上证 {market['index_pct']:+.2f}%，{ld_s}")
        lines.append("心法：不赌涨跌，只赚纪律和先手的钱。")
        return "\n".join(lines)

    if not cands:
        lines.append("今日无符合 6 条件的票，空仓等明天。")
        if market["index_pct"] is not None:
            lines.append(f"（上证 {market['index_pct']:+.2f}%，{ld_s}）")
        return "\n".join(lines)

    lines.append(f"符合 6 条件 {len(cands)} 只（按量比排序）：")
    for i, c in enumerate(cands, 1):
        mcap_yi = c["mcap"] / 1e8
        lines.append(
            f"{i}. {c['name']}({c['code']}) {c['price']:.2f}元 "
            f"涨{c['pct']:.1f}% 量比{c['vol_ratio']:.2f} "
            f"换手{c['turnover']:.1f}% 市值{mcap_yi:.0f}亿"
        )
    lines.append("买入：只买1-3只，总仓位≤5成，不补仓。")
    lines.append("明日：高开/强势冲高卖；弱势低开立刻走；10:00前清仓。")
    lines.append("单笔亏损≤2%。心法：不赌涨跌，只赚纪律和先手的钱。")
    return "\n".join(lines)


def debug_run():
    """全盘诊断：逐关打印通过数量（不受空仓日拦截）。"""
    print("===== 尾盘选股 · 全盘诊断 =====")
    idx_pct = get_index_pct()
    lim_down = count_limit_down()
    print(f"上证涨跌: {idx_pct}    跌停家数: {lim_down}")

    gainers = fetch_gainers()
    print(f"全市场（涨幅>=3%）: {len(gainers)} 只")

    c1 = [x for x in gainers if PCT_MIN <= x["pct"] <= PCT_MAX]
    print(f"关1 涨幅{PCT_MIN}-{PCT_MAX}%: {len(c1)}")

    c2 = [x for x in c1 if x["vol_ratio"] >= VOL_RATIO_MIN]
    print(f"关2 量比>{VOL_RATIO_MIN}: {len(c2)}")

    c3 = [x for x in c2 if TURNOVER_MIN <= x["turnover"] <= TURNOVER_MAX]
    print(f"关3 换手{TURNOVER_MIN}-{TURNOVER_MAX}%: {len(c3)}")

    c4 = [x for x in c3 if x["mcap"] < MCAP_MAX and "ST" not in x["name"] and "退" not in x["name"]]
    print(f"关4 市值<200亿/非ST: {len(c4)}")

    lu = []
    for x in c4:
        if has_limit_up_20d(x["code"]):
            lu.append(x)
            print(f"  ✔ 涨停基因: {x['name']}({x['code']})")
    print(f"关5 20天内有过涨停: {len(lu)}")

    final = []
    for x in lu:
        ok = above_vwap_today(x["code"])
        print(f"  分时均价线 {x['name']}({x['code']}): {'✔ 通过' if ok else '✘ 不通过'}")
        if ok:
            final.append(x)
    print(f"关6 分时在均价线上方: {len(final)}")

    if final:
        final.sort(key=lambda x: x["vol_ratio"], reverse=True)
        print("\n最终候选（不受空仓日拦截）：")
        for i, x in enumerate(final[:MAX_PICKS], 1):
            print(f"  {i}. {x['name']}({x['code']}) 价{x['price']:.2f} 涨{x['pct']:.1f}% "
                  f"量比{x['vol_ratio']:.2f} 换手{x['turnover']:.1f}% 市值{x['mcap']/1e8:.0f}亿")
    else:
        print("\n最终候选：0 只（无票同时满足 6 条）")


def run():
    print(f"===== 尾盘选股 {datetime.now().astimezone():%Y-%m-%d %H:%M} =====")
    cands, market = screen()
    risk_push.push(format_alert(cands, market), "尾盘选股")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "debug":
        debug_run()
    else:
        run()
