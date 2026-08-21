"""信号雷达：一键扫描策略库全部已保存策略的最近买卖信号。

流程（与「策略库 → 重跑到今天」同一套信号口径）：
1. ``expand_targets``: 把已保存策略（single/portfolio/multi 三种 kind）统一展开成
   "策略×标的" 子任务列表；数据损坏的条目展开为带 error 的行，不中断整批。
2. ``fetch_scan_bars``: 按 (symbol, category) 去重取最近 K 线（async，event loop 内
   调用；单页 800 根足够覆盖内置策略全部参数的指标预热）。
3. ``run_scan``: 后台线程内逐 target 构建策略实例，跑一遍 bar-by-bar 信号流程
   （复用 combo._update_position 跟踪仓位，与 BacktestEngine 同口径），
   汇总最近 ``window`` 根内的买卖信号、结束仓位与最新收盘价。

只扫信号、不重跑完整回测，也不改写策略库保存的业绩快照。
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from easy_tdx.backtest.combo import _update_position
from easy_tdx.backtest.strategy import Strategy
from easy_tdx.web.strategy_store import SavedStrategy

logger = logging.getLogger(__name__)

# 每标的取的 K 线根数：标准协议单次上限 800 根，足够内置策略最慢参数（如慢线 250）预热。
SCAN_BARS = 800

# 仓位跟踪用的佣金率（与 combo.extract_factor_signals 默认一致，只影响全仓股数估算）
_COMMISSION = 0.0003

# 市场前缀纠错规则（与前端 web-ui/src/market.ts detectMarket 保持一致）：
# 北交所 43/83/87/92/93/4xx/8xx；沪市 6xx/9xx/5xx（含沪市基金）；其余深市。
_BJ_PREFIX = re.compile(r"^(43|83|87|92|93|4|8)")
_SH_PREFIX = re.compile(r"^[695]")


def _detect_market(code: str) -> str:
    """按 6 位代码推断市场（SH/SZ/BJ），规则与前端 detectMarket 一致。"""
    if not re.fullmatch(r"\d{6}", code):
        return "SZ"
    if _BJ_PREFIX.match(code):
        return "BJ"
    if _SH_PREFIX.match(code):
        return "SH"
    return "SZ"


def normalize_symbol(raw: str) -> str:
    """纠正历史保存策略的市场前缀（如 SZ:515080 → SH:515080）。

    早期前端曾按市场前缀漏判沪市基金，导致部分历史保存的 symbol 错标，
    后端按错配市场取到 0 根 K 线被静默跳过。这里按代码段重判市场兜底。
    """
    code = raw.split(":", 1)[-1].strip() if raw else ""
    if not code:
        return raw
    return f"{_detect_market(code)}:{code}"


# ── 展开子任务 ────────────────────────────────────────────────────────────────


@dataclass
class ScanTarget:
    """一个待扫描的"策略×标的"子任务（由已保存策略展开而来）。

    ``error`` 非空表示展开阶段就发现问题（缺 symbol / 组合数据损坏），
    run_scan 会把它原样写进结果行，不参与取数与信号计算。
    """

    strategy_id: str  # 所属已保存策略 id
    strategy_name: str  # 所属已保存策略名（展示用）
    kind: str  # single | portfolio | multi
    strategy: str  # 策略注册表 key（如 ma_cross）
    strategy_label: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    symbol: str = ""  # 归一化后的 "市场:代码"
    category: str = "DAY"
    error: str | None = None


def expand_targets(records: list[SavedStrategy]) -> list[ScanTarget]:
    """把全部已保存策略展开成"策略×标的"子任务列表。

    - single: 1 条（context.symbol）
    - portfolio: context.stocks 每只一条（同 strategy + params）
    - multi: context.items 每条一 target（各自带 strategy/params/symbol）
    - 缺关键字段的条目展开为 error 行（保证结果表能看到"这条策略有问题"）
    """
    targets: list[ScanTarget] = []
    for rec in records:
        ctx = rec.context or {}
        if rec.kind == "multi":
            items = ctx.get("items")
            if not isinstance(items, list) or not items:
                targets.append(
                    ScanTarget(
                        strategy_id=rec.id,
                        strategy_name=rec.name,
                        kind=rec.kind,
                        strategy=rec.strategy,
                        error="组合缺少策略明细（items），可能数据损坏",
                    )
                )
                continue
            for item in items:
                if not isinstance(item, dict):
                    targets.append(_error_target(rec, "组合条目数据损坏"))
                    continue
                symbol = item.get("symbol")
                if not item.get("strategy") or not symbol:
                    targets.append(_error_target(rec, "组合条目缺少 strategy/symbol"))
                    continue
                targets.append(
                    ScanTarget(
                        strategy_id=rec.id,
                        strategy_name=rec.name,
                        kind=rec.kind,
                        strategy=str(item["strategy"]),
                        strategy_label=str(item.get("strategy_label") or ""),
                        params=item.get("params") or {},
                        symbol=normalize_symbol(str(symbol)),
                        category=str(item.get("category") or "DAY"),
                    )
                )
        else:
            # single 与 portfolio 同构：portfolio 把同策略铺到多只标的
            stocks = ctx.get("stocks") if rec.kind == "portfolio" else None
            symbols = [str(s) for s in stocks] if isinstance(stocks, list) and stocks else None
            if symbols is None:
                symbol = ctx.get("symbol")
                if not symbol:
                    targets.append(_error_target(rec, "缺少标的上下文（symbol）"))
                    continue
                symbols = [str(symbol)]
            for sym in symbols:
                targets.append(
                    ScanTarget(
                        strategy_id=rec.id,
                        strategy_name=rec.name,
                        kind=rec.kind,
                        strategy=rec.strategy,
                        strategy_label=rec.strategy_label,
                        params=rec.params or {},
                        symbol=normalize_symbol(sym),
                        category=str(ctx.get("category") or "DAY"),
                    )
                )
    return targets


def _error_target(rec: SavedStrategy, message: str) -> ScanTarget:
    """构造一条展开失败的 error 行（保留策略身份，便于在结果表定位）。"""
    return ScanTarget(
        strategy_id=rec.id,
        strategy_name=rec.name,
        kind=rec.kind,
        strategy=rec.strategy,
        error=message,
    )


# ── 取行情 ────────────────────────────────────────────────────────────────────


async def fetch_scan_bars(
    client: Any,
    targets: list[ScanTarget],
) -> dict[tuple[str, str], pd.DataFrame | None]:
    """按 (symbol, category) 去重取最近 ``SCAN_BARS`` 根 K 线（async，event loop 内调用）。

    同一标的被多个策略引用时只取一次。单个标的取数失败/数据无效记 None
    （不中断整批），run_scan 会给相关行统一标 error。
    """
    from easy_tdx.web.convert import category_from_str, market_from_str

    bars: dict[tuple[str, str], pd.DataFrame | None] = {}
    for t in targets:
        key = (t.symbol, t.category)
        if key in bars or t.error:
            continue
        try:
            market_str, code = t.symbol.split(":", 1)
            df = await client.get_security_bars(
                market_from_str(market_str),
                code,
                category_from_str(t.category),
                0,
                SCAN_BARS,
            )
        except Exception as exc:  # noqa: BLE001 — 单标的失败不中断整批
            logger.warning("信号扫描取数失败 %s: %s", t.symbol, exc)
            bars[key] = None
            continue
        if not isinstance(df, pd.DataFrame) or len(df) < 2 or "close" not in df.columns:
            bars[key] = None
            continue
        # 列归一化：日线返回 date 列，_bind_data 需要 datetime；页内已正序但保险再排一次
        if "datetime" not in df.columns and "date" in df.columns:
            df = df.copy()
            df["datetime"] = df["date"]
        if "datetime" not in df.columns:
            bars[key] = None
            continue
        bars[key] = df.sort_values("datetime").reset_index(drop=True)
    return bars


# ── 信号评估 ──────────────────────────────────────────────────────────────────


def evaluate_signals(
    strategy: Strategy,
    df: pd.DataFrame,
    window: int,
) -> dict[str, Any]:
    """在 df 上单遍跑策略的 bar-by-bar 信号流程，返回最近 window 根内的信号摘要。

    复现 BacktestEngine._generate_signals / combo.extract_factor_signals 的
    信号收集 + 仓位跟踪（``_update_position``），保证扫描结果与真实回测一致。
    """
    n = len(df)
    strat = strategy
    strat._bind_data(df)
    strat._cash = 100_000.0
    strat._position_size = 0.0
    strat._call_init()

    close_arr = df["close"].to_numpy()
    dt_col = df["datetime"]
    start = max(0, n - window)
    recent: list[dict[str, Any]] = []

    for i in range(n):
        strat._set_bar_index(i)
        strat._call_next()
        signals = strat._clear_signals()
        if signals and i >= start:
            date = str(dt_col.iloc[i])[:16]
            for sig in signals:
                recent.append({"date": date, "direction": sig.direction})
        _update_position(strat, signals, close_arr[i], _COMMISSION)

    return {
        "recent_signals": recent,
        "latest_signal": recent[-1]["direction"] if recent else None,
        "signal_date": recent[-1]["date"] if recent else None,
        # 结束仓位（容忍浮点误差）：>0 视为策略当前持仓
        "position": "holding" if strat._position_size > 0.5 else "flat",
        "last_close": float(close_arr[-1]),
        "last_bar_date": str(dt_col.iloc[-1])[:16],
    }


# ── 汇总扫描 ──────────────────────────────────────────────────────────────────


def run_scan(
    bars: dict[tuple[str, str], pd.DataFrame | None],
    targets: list[ScanTarget],
    window: int,
) -> dict[str, Any]:
    """后台线程内执行：逐 target 构建策略实例并评估信号，汇总成扫描结果。

    单个 target 失败（未知策略/参数非法/取数为空/计算异常）记为该行的
    error，不影响其余行。返回结构对应 SignalScanResult schema。
    """
    from easy_tdx.backtest.strategies import get_registry

    registry = get_registry()
    rows: list[dict[str, Any]] = []
    t0 = time.time()

    for t in targets:
        row: dict[str, Any] = {
            "strategy_id": t.strategy_id,
            "strategy_name": t.strategy_name,
            "kind": t.kind,
            "strategy": t.strategy,
            "strategy_label": t.strategy_label,
            "params": t.params,
            "symbol": t.symbol,
            "category": t.category,
            "latest_signal": None,
            "signal_date": None,
            "recent_signals": [],
            "position": None,
            "last_close": None,
            "last_bar_date": None,
            "error": None,
        }
        try:
            if t.error:
                raise ValueError(t.error)
            df = bars.get((t.symbol, t.category))
            if df is None:
                raise ValueError("未取到有效 K 线（停牌/代码失效/取数失败）")
            try:
                entry = registry.get(t.strategy)
            except KeyError as exc:
                raise ValueError(f"未知策略 '{t.strategy}'（可能为旧版本保存）") from exc
            strategy = entry.build(t.params)
            row.update(evaluate_signals(strategy, df, window))
        except Exception as exc:  # noqa: BLE001 — 单行失败不中断整批
            row["error"] = str(exc) or type(exc).__name__
            logger.warning("信号扫描失败 %s@%s: %s", t.strategy, t.symbol, exc)
        rows.append(row)

    buy_count = sum(1 for r in rows if any(s["direction"] == "BUY" for s in r["recent_signals"]))
    sell_count = sum(1 for r in rows if any(s["direction"] == "SELL" for s in r["recent_signals"]))
    error_count = sum(1 for r in rows if r["error"])
    return {
        "rows": rows,
        "total": len(rows),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "error_count": error_count,
        "elapsed": round(time.time() - t0, 2),
    }
