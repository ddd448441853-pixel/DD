# -*- coding: utf-8 -*-
"""
journal.py —— 第 5 步：日志 + 复盘

大白话：记流水账 + 定期体检。
  - 交易日志.md：我回复「开了/没开」后，记录标的/方向/进场/止损/目标/结果/R倍数/市场状态/情绪
  - 没开的信号也记录，并事后跟踪「如果开了会走到几 R」
  - 每天早 9 点复盘；每满 20 个信号用累计数据建议调参

机器内部另存一份结构化 trades.jsonl，方便算统计；交易日志.md 是给人看的。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import config


class Journal:
    def __init__(self, trades_file: Path | None = None, md_file: Path | None = None):
        self.trades_file = trades_file or (config.OUTPUT_DIR / "trades.jsonl")
        self.md_file = md_file or config.JOURNAL_FILE
        self.trades_file.parent.mkdir(parents=True, exist_ok=True)

    # ---------- 底层读写 ----------

    def _read_trades(self) -> list[dict]:
        if not self.trades_file.exists():
            return []
        out = []
        with self.trades_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return out

    def _append_trade(self, trade: dict):
        with self.trades_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(trade, ensure_ascii=False) + "\n")

    def _md_append(self, text: str):
        self.md_file.parent.mkdir(parents=True, exist_ok=True)
        with self.md_file.open("a", encoding="utf-8") as f:
            f.write(text + "\n")

    def record_note(self, text: str):
        """记一条带时间的备注（比如「震荡期，只记录不推送」）。"""
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
        self._md_append(f"- [{stamp}] {text}")

    # ---------- 记录信号 / 结果 ----------

    def record_signal(self, signal: dict) -> str:
        """
        记录一个新信号（未处理）。返回信号 id。
        """
        tid = signal.get("id") or (
            datetime.now().astimezone().strftime("%Y%m%d-%H%M") + "-" + signal["symbol"]
        )
        trade = {
            "id": tid,
            "time": str(signal["time"]),
            "symbol": signal["symbol"],
            "direction": signal["direction"],
            "entry": signal["entry"],
            "stop": signal["stop"],
            "targets": signal["targets"],
            "triggered": signal["triggered"],
            "strength": signal["strength"],
            "opened": None,            # None=未处理 True=开了 False=没开
            "result_r": None,
            "exit_price": None,
            "market_state": signal.get("trend_4h", ""),
            "emotion": "",
            "note": "",
        }
        self._append_trade(trade)
        self._md_append(
            f"### {tid}  {signal['symbol']} 做多（未处理）\n"
            f"- 进场 {signal['entry']:,.0f} / 止损 {signal['stop']:,.0f} / "
            f"目标 1R {signal['targets']['1R']:,.0f}, 2R {signal['targets']['2R']:,.0f}, 3R {signal['targets']['3R']:,.0f}\n"
            f"- 触发：{'、'.join(signal['triggered'])}\n"
            f"- 市场状态：{signal.get('trend_4h', '')}"
        )
        return tid

    def record_outcome(self, tid: str, opened: bool, result_r: float | None = None,
                       exit_price: float | None = None, emotion: str = "", note: str = ""):
        """
        我回复「开了/没开」后调用：
        - 开了：给 result_r（最终 R 倍数，赚为正、亏为负）
        - 没开：opened=False，之后由 followup() 补「后续走势」
        """
        trades = self._read_trades()
        for t in trades:
            if t["id"] == tid:
                t["opened"] = opened
                t["result_r"] = result_r
                t["exit_price"] = exit_price
                t["emotion"] = emotion
                t["note"] = note
        self._rewrite(trades)
        verdict = "开了" if opened else "没开"
        rstr = f"{result_r:+}R" if result_r is not None else "待定"
        self._md_append(
            f"→ 结果：{verdict}，R = {rstr}，情绪备注：{emotion or '无'}，{note}"
        )

    def _rewrite(self, trades: list[dict]):
        self.trades_file.write_text("", encoding="utf-8")
        for t in trades:
            self._append_trade(t)

    # ---------- 没开信号的「后续走势」 ----------

    def followup(self, tid: str, df1h) -> dict | None:
        """
        对「没开」的信号，计算信号之后价格最高/最低走到几 R（检验规则）。
        df1h：该标的的 1h K 线（含指标列更好，这里只用 high/low）。
        """
        trades = self._read_trades()
        trade = next((t for t in trades if t["id"] == tid), None)
        if trade is None or trade["opened"] is not False:
            return None
        ts = trade["time"]
        sub = df1h[df1h["open_time"] > ts]
        if len(sub) == 0:
            return None
        entry = trade["entry"]
        r = entry - trade["stop"]
        if r <= 0:
            return None
        high = float(sub["high"].max())
        low = float(sub["low"].min())
        max_r = (high - entry) / r
        min_r = (low - entry) / r
        res = {"max_high": high, "min_low": low, "max_r": round(max_r, 2), "min_r": round(min_r, 2)}
        for t in trades:
            if t["id"] == tid:
                t["note"] += f" 后续：最高 {high:,.0f}（{max_r:+.1f}R），最低 {low:,.0f}（{min_r:+.1f}R）"
        self._rewrite(trades)
        return res

    # ---------- 统计 ----------

    def stats(self) -> dict:
        trades = [t for t in self._read_trades() if t["result_r"] is not None]
        wins = [t for t in trades if t["result_r"] > 0]
        losses = [t for t in trades if t["result_r"] <= 0]
        total_r = sum(t["result_r"] for t in trades)
        n = len(trades)
        return {
            "total": n,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": (len(wins) / n) if n else 0.0,
            "total_r": total_r,
            "avg_r": (total_r / n) if n else 0.0,
            "expectancy": total_r,   # 累计 R，正=赚钱
        }

    # ---------- 每日复盘 ----------

    def daily_review(self, target_date: str, signals_md: str) -> str:
        """
        生成每日复盘文案。
        target_date：复盘日期（如 '2026-10-27'）
        signals_md：该日信号的人读描述（由上层 main.py 组装）
        """
        st = self.stats()
        return (
            f"📋 每日复盘（{target_date}）\n"
            f"{signals_md}\n"
            f"累计：{st['total']} 笔，胜 {st['wins']} / 负 {st['losses']}，"
            f"累计 {st['total_r']:+.1f}R\n"
        )

    # ---------- 每满 20 个信号的汇总 ----------

    def summary_20(self) -> str | None:
        """每满 20 个已结算信号，用累计数据给一次调参建议（调不调由我决定）。"""
        st = self.stats()
        if st["total"] == 0 or st["total"] % 20 != 0:
            return None
        lines = [
            f"📊 累计 20 信号汇总（共 {st['total']} 笔已结算）",
            f"- 胜率 {st['win_rate']:.0%}，累计 {st['total_r']:+.1f}R，平均每笔 {st['avg_r']:+.2f}R",
        ]
        if st["expectancy"] <= 0:
            lines.append("- 建议：累计 R 为负，可考虑收紧（提高进场条件到 3 条 / 只做 A、B 级信号），是否调整由你决定。")
        else:
            lines.append("- 现状：累计 R 为正，规则先保持，继续观察。")
        return "\n".join(lines)
