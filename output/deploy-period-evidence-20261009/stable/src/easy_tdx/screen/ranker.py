"""回测排名引擎 — 对扫描结果做历史回测并按指标排名。

核心流程：
1. 读取 scan 输出的 JSON（文件或 stdin）
2. 每只股票：read_daily_bars() → DataFrame → BacktestEngine.run() → performance
3. 按 --sort 指标排序（默认 sharpe）
4. 可选在线获取股票名称
5. 输出排名表或 JSON
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.strategy import Strategy
from easy_tdx.offline.daily_bar import read_daily_bars
from easy_tdx.offline.paths import resolve_vipdoc

from .scanner import _bars_to_df


@dataclass
class RankEntry:
    """排名条目。

    Attributes:
        rank: 排名位置
        code: 6 位股票代码
        market: 市场（SZ/SH）
        name: 股票名称（可能为空）
        signal_date: 信号日期
        last_close: 最后收盘价
        performance: 绩效指标字典
    """

    rank: int
    code: str
    market: str
    name: str
    signal_date: int
    last_close: float
    performance: dict[str, float]


class SignalRanker:
    """信号排名器。

    用法::

        ranker = SignalRanker(strategy_cls=RSIStrategy)
        entries = ranker.rank(signals)
        for e in entries[:10]:
            print(f"#{e.rank} {e.market}{e.code} sharpe={e.performance['sharpe']:.2f}")
    """

    def __init__(
        self,
        strategy_cls: type[Strategy],
        vipdoc_path: str | Path | None = None,
        cash: float = 1_000_000.0,
        commission: float = 0.0003,
        count: int = 0,
    ) -> None:
        """初始化排名器。

        Args:
            strategy_cls: 策略类
            vipdoc_path: vipdoc 目录路径
            cash: 初始资金
            commission: 佣金率
            count: 使用最近 N 条 K 线，0=全部
        """
        self._strategy_cls = strategy_cls
        self._vipdoc = resolve_vipdoc(vipdoc_path)
        self._cash = cash
        self._commission = commission
        self._count = count

    def rank(
        self,
        signals: list[dict[str, Any]],
        sort_by: str = "sharpe",
        sort_reverse: bool = False,
        top_n: int = 0,
        progress_callback: Any = None,
    ) -> list[RankEntry]:
        """对信号列表做回测排名。

        Args:
            signals: scan 输出的信号列表
                [{"code": "000001", "market": "SZ", "signal_date": 20260610, ...}]
            sort_by: 排序指标（默认 sharpe）
            sort_reverse: True 则升序（用于 max_drawdown 等越小越好的指标）
            top_n: 只返回前 N 名，0=全部
            progress_callback: 进度回调(current, total, code)

        Returns:
            RankEntry 列表
        """
        entries: list[RankEntry] = []
        total = len(signals)

        for idx, sig in enumerate(signals):
            code = sig["code"]
            market = sig["market"]
            signal_date = sig.get("signal_date", 0)
            last_close = sig.get("last_close", 0.0)

            if progress_callback:
                progress_callback(idx, total, f"{market}{code}")

            try:
                perf = self._backtest_one(market, code)
                if perf is not None:
                    entries.append(
                        RankEntry(
                            rank=0,  # 排名在排序后赋值
                            code=code,
                            market=market,
                            name="",
                            signal_date=signal_date,
                            last_close=last_close,
                            performance=perf,
                        )
                    )
            except Exception:
                continue

        if progress_callback:
            progress_callback(total, total, "done")

        # 排序
        entries.sort(
            key=lambda e: e.performance.get(sort_by, 0.0),
            reverse=not sort_reverse,
        )

        # 赋值排名
        for i, entry in enumerate(entries):
            entry.rank = i + 1

        # 截取 top_n
        if top_n > 0:
            entries = entries[:top_n]

        return entries

    def _backtest_one(self, market: str, code: str) -> dict[str, float] | None:
        """对单只股票做回测。

        Args:
            market: 市场（SZ/SH）
            code: 6 位股票代码

        Returns:
            绩效指标字典，数据不足时返回 None
        """
        exchange = market.lower()
        filepath = self._vipdoc / exchange / "lday" / f"{exchange}{code}.day"

        if not filepath.is_file():
            return None

        bars = read_daily_bars(filepath)
        if len(bars) < 30:
            return None

        df = _bars_to_df(bars)
        if df.empty:
            return None

        # 截取最近 count 条
        if self._count > 0 and len(df) > self._count:
            df = df.iloc[-self._count :].reset_index(drop=True)

        engine = BacktestEngine(
            strategy=self._strategy_cls,
            cash=self._cash,
            commission=self._commission,
        )
        result = engine.run(df)
        return result.performance

    def enrich_names(self, entries: list[RankEntry]) -> list[RankEntry]:
        """通过在线查询补齐股票名称。

        仅对排名中的股票查询，通常只有几十只。

        分批查询（每批最多 80 只），避免超出 MAC 协议单次报价上限导致末尾名字丢失。

        Args:
            entries: 排名列表

        Returns:
            补齐名称后的列表（原地修改）
        """
        if not entries:
            return entries

        try:
            from easy_tdx.cli.parsers import parse_market
            from easy_tdx.mac.client import MacClient

            # 批量查询
            pairs = [(parse_market(e.market), e.code) for e in entries]

            client = MacClient.from_best_host()
            try:
                client.connect()
                # 分批查询：MAC 协议单次最多 80 只，超出部分会被服务器丢弃
                import pandas as pd

                frames: list[pd.DataFrame] = []
                for i in range(0, len(pairs), 80):
                    batch = pairs[i : i + 80]
                    frames.append(client.get_stock_quotes(batch))
                quotes_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            finally:
                client.close()

            if quotes_df.empty or "name" not in quotes_df.columns:
                return entries

            # 构建 "SZ000001" → name 映射
            # MacQuoteField.market 是 int (0=SZ, 1=SH)，需转为字符串
            _market_map = {0: "SZ", 1: "SH"}
            name_map: dict[str, str] = {}
            for _, row in quotes_df.iterrows():
                mkt_int = row.get("market", -1)
                mkt_str = _market_map.get(mkt_int, str(mkt_int))
                key = f"{mkt_str}{row.get('code', '')}"
                name_map[key] = str(row.get("name", ""))

            for entry in entries:
                key = f"{entry.market}{entry.code}"
                if key in name_map:
                    entry.name = name_map[key]

        except Exception:
            # 名称查询失败不影响主流程
            pass

        return entries

    @staticmethod
    def to_json(
        entries: list[RankEntry],
        strategy_name: str,
        sort_by: str,
    ) -> str:
        """将排名结果序列化为 JSON 字符串。

        Args:
            entries: 排名列表
            strategy_name: 策略名称
            sort_by: 排序指标

        Returns:
            JSON 字符串
        """
        data = {
            "strategy": strategy_name,
            "sort_by": sort_by,
            "total_ranked": len(entries),
            "ranking": [
                {
                    "rank": e.rank,
                    "code": e.code,
                    "market": e.market,
                    "name": e.name,
                    "signal_date": e.signal_date,
                    "last_close": e.last_close,
                    "performance": e.performance,
                }
                for e in entries
            ],
        }
        return json.dumps(data, ensure_ascii=False, indent=2, default=_json_default)

    @staticmethod
    def to_table(entries: list[RankEntry], sort_by: str) -> str:
        """将排名结果格式化为表格字符串。

        Args:
            entries: 排名列表
            sort_by: 排序指标

        Returns:
            表格字符串
        """
        if not entries:
            return "无有效排名结果"

        sort_label = f"{sort_by} 降序"
        lines = [
            f"[*] 信号排名 (按 {sort_label}, 共 {len(entries)} 只)",
            "═" * 90,
            f"{'排名':>4}  {'代码':<10} {'名称':<10} {'总收益率':>10} {'年化收益':>10} "
            f"{'最大回撤':>10} {'夏普':>8} {'胜率':>8} {'交易':>6}",
            "─" * 90,
        ]

        for e in entries:
            medal = (
                " *1*"
                if e.rank == 1
                else " *2*"
                if e.rank == 2
                else " *3*"
                if e.rank == 3
                else "    "
            )
            perf = e.performance
            label = f"{e.market}{e.code}"
            name = e.name[:8] if e.name else ""
            lines.append(
                f"{medal}{e.rank:>2}  {label:<10} {name:<10} "
                f"{perf.get('total_return', 0):>9.2%} "
                f"{perf.get('annual_return', 0):>9.2%} "
                f"{perf.get('max_drawdown', 0):>9.2%} "
                f"{perf.get('sharpe', 0):>8.2f} "
                f"{perf.get('win_rate', 0):>7.1%} "
                f"{perf.get('total_trades', 0):>6}"
            )

        return "\n".join(lines)


def _json_default(obj: Any) -> Any:
    """JSON 序列化辅助。"""
    if hasattr(obj, "item"):
        return obj.item()
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def load_signals(source: str) -> tuple[list[dict[str, Any]], str, str]:
    """从文件或 stdin 加载信号 JSON。

    Args:
        source: JSON 文件路径，"-" 表示 stdin

    Returns:
        (signals, strategy_name, strategy_file)
    """
    if source == "-":
        data = json.load(sys.stdin)
    else:
        filepath = Path(source)
        if not filepath.is_file():
            raise FileNotFoundError(f"信号文件不存在: {source}")
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)

    signals = data.get("signals", [])
    strategy_name = data.get("strategy", "unknown")
    strategy_file = data.get("strategy_file", "")
    return signals, strategy_name, strategy_file
