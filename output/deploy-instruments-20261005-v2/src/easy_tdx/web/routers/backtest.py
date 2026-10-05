"""回测路由：策略枚举、同步回测、后台任务回测、任务轮询。

设计要点：
- 回测是纯计算（不依赖行情连接的 lifespan），因此**不注入 tdx_client**——
  只有「按标的取行情」才需要 client，且必须在 async 上下文里取好数据后再
  交给后台线程跑回测（``get_security_bars`` 是 async，不能跨线程调用）。
- 后台任务用 :class:`~easy_tdx.web.task_runner.BacktestTaskRunner`，结果
  线程安全，重启即丢。
- 同步回测仅支持内联 OHLCV（前端已有数据），避免长任务阻塞 event loop。
"""

from __future__ import annotations

import inspect
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends

from easy_tdx.web.account_store import UserRecord
from easy_tdx.web.adjusted_bars import fetch_adjusted_bars
from easy_tdx.web.backtest_schemas import (
    BacktestRequest,
    BacktestResultResponse,
    MultiStrategyBacktestRequest,
    OptimizeAllBacktestRequest,
    OptimizeAllRankEntry,
    OptimizeAllResult,
    OptimizeBacktestRequest,
    PortfolioBacktestRequest,
    SignalScanRequest,
    StrategySchemaResponse,
    TaskListResponse,
    TaskStateResponse,
    TaskSubmitResponse,
    TaskSummary,
    serialize_result,
)
from easy_tdx.web.deps import get_client, get_mac_client_optional
from easy_tdx.web.routers.auth import get_current_user
from easy_tdx.web.task_runner import get_runner

router = APIRouter(tags=["backtest"])


# ── 策略枚举 ───────────────────────────────────────────────────────────────────


@router.get("/backtest/strategies", response_model=StrategySchemaResponse)
async def list_strategies() -> StrategySchemaResponse:
    """枚举所有预置策略及其参数 schema（供前端动态渲染策略选择 + 参数表单）。"""
    from easy_tdx.backtest.strategies import get_registry

    entries = get_registry().all()
    schemas = [e.to_schema() for e in entries]
    return StrategySchemaResponse(strategies=schemas, count=len(schemas))


# ── 同步回测（内联数据） ───────────────────────────────────────────────────────


@router.post("/backtest/run", response_model=BacktestResultResponse)
async def run_backtest(req: BacktestRequest) -> BacktestResultResponse:
    """同步回测（仅支持内联 OHLCV 数据）。

    适用于单标的快速回测（<3s）。需要取行情或长任务请用 ``/backtest/run/async``。
    """
    if req.ohlcv is None:
        raise ValueError(
            "同步回测（/backtest/run）必须提供 ohlcv 内联数据；取行情请用 /backtest/run/async"
        )

    df = _ohlcv_to_df(req.ohlcv)
    result_dict = _run_backtest(df, req)
    return BacktestResultResponse(**result_dict)


# ── 后台任务回测 ───────────────────────────────────────────────────────────────


@router.post("/backtest/run/async", response_model=TaskSubmitResponse, status_code=202)
async def run_backtest_async(
    req: BacktestRequest,
    client: Any = Depends(get_client),
    mac_client: Any | None = Depends(get_mac_client_optional),
) -> TaskSubmitResponse:
    """提交后台回测任务，立即返回 task_id。

    支持内联数据或按标的取行情。取行情在 async 上下文完成（client 是 async 的），
    之后回测在后台线程执行。通过 ``GET /backtest/tasks/{task_id}`` 轮询结果。
    """
    # 1. 取数据（async 上下文内完成）
    if req.ohlcv is not None:
        df = _ohlcv_to_df(req.ohlcv)
        bars_desc = f"{len(df)} 根"
    elif req.symbol is not None:
        if mac_client is None or "mac_client" not in inspect.signature(_fetch_bars).parameters:
            df = await _fetch_bars(client, req.symbol, req.category, req.count)
        else:
            df = await _fetch_bars(
                client,
                req.symbol,
                req.category,
                req.count,
                mac_client=mac_client,
                adjust=req.adjust,
            )
        bars_desc = f"{req.symbol} {req.category}×{req.count}"
    else:
        # BacktestRequest 校验器已保证二者至少其一，此处不可达
        raise ValueError("必须提供 ohlcv 或 symbol")

    # 2. 捕获回测所需的不可变快照（避免闭包捕获可变 req）
    snapshot = req.model_copy()
    description = f"{snapshot.strategy} | {bars_desc}"

    # 3. 提交后台任务
    runner = get_runner()
    task_id = runner.submit(lambda: _run_backtest(df, snapshot), description=description)
    state = runner.get(task_id)
    # 提交瞬间任务应是 pending/running；极端情况下线程已跑完则报实际状态
    status: Any = state.status if state.status in ("pending", "running") else "running"
    return TaskSubmitResponse(task_id=task_id, status=status)


@router.get("/backtest/tasks", response_model=TaskListResponse)
async def list_tasks(limit: int = 20) -> TaskListResponse:
    """列出最近 N 个任务摘要（按最近使用倒序，不含完整 result）。

    供对比页选择要对比的 task；选中后再逐个调 /tasks/{task_id} 拉详情。
    """
    import time

    runner = get_runner()
    states = runner.list_recent(limit)
    summaries = [
        TaskSummary(
            task_id=s.task_id,
            status=s.status,
            description=s.description,
            created_at=s.created_at,
            elapsed=(s.finished_at or time.time()) - (s.started_at or s.created_at),
        )
        for s in states
    ]
    return TaskListResponse(tasks=summaries, count=len(summaries))


@router.get("/backtest/tasks/{task_id}", response_model=TaskStateResponse)
async def get_task(task_id: str) -> TaskStateResponse:
    """查询后台回测任务状态。done 时 result 字段含完整回测结果。"""
    state = get_runner().peek(task_id)
    if state is None:
        # 未知 task → 404（通过 ValueError 走 400 handler；这里用 KeyError 由
        # 调用方判定。为保持语义清晰，统一抛 ValueError → HTTP 400）
        raise ValueError(f"未知任务 '{task_id}'")
    return TaskStateResponse(
        task_id=state.task_id,
        status=state.status,
        result=state.result,
        error=state.error,
        description=state.description,
        elapsed=(state.finished_at or _now()) - (state.started_at or state.created_at),
    )


# ── 组合回测 ───────────────────────────────────────────────────────────────────


@router.post("/backtest/portfolio/run/async", response_model=TaskSubmitResponse, status_code=202)
async def run_portfolio_backtest_async(
    req: PortfolioBacktestRequest,
    client: Any = Depends(get_client),
    mac_client: Any | None = Depends(get_mac_client_optional),
) -> TaskSubmitResponse:
    """提交组合（多标的）回测后台任务。

    逐个标的取行情（async），组装 StockData 列表后提交后台任务跑
    PortfolioBacktestEngine。通过 GET /backtest/tasks/{task_id} 轮询结果。
    """
    # 1. 逐个标的取行情（async 上下文内）
    if mac_client is None or "mac_client" not in inspect.signature(
        _fetch_portfolio_bars
    ).parameters:
        stock_data_list = await _fetch_portfolio_bars(
            client, req.stocks, req.category, req.start_date, req.end_date
        )
    else:
        stock_data_list = await _fetch_portfolio_bars(
            client,
            req.stocks,
            req.category,
            req.start_date,
            req.end_date,
            mac_client=mac_client,
            adjust=req.adjust,
        )
    if not stock_data_list:
        raise ValueError("所有标的均未取到有效行情数据")

    # 2. 捕获不可变快照
    snapshot = req.model_copy()
    description = f"{snapshot.strategy} | {len(stock_data_list)}只标的"

    # 3. 提交后台任务
    runner = get_runner()
    task_id = runner.submit(
        lambda: _run_portfolio_backtest(stock_data_list, snapshot),
        description=description,
    )
    state = runner.get(task_id)
    status: Any = state.status if state.status in ("pending", "running") else "running"
    return TaskSubmitResponse(task_id=task_id, status=status)


# ── 多策略组合回测（资金分仓） ───────────────────────────────────────────────


@router.post(
    "/backtest/multi-strategy/run/async", response_model=TaskSubmitResponse, status_code=202
)
async def run_multi_strategy_backtest_async(
    req: MultiStrategyBacktestRequest,
    client: Any = Depends(get_client),
    mac_client: Any | None = Depends(get_mac_client_optional),
) -> TaskSubmitResponse:
    """提交多策略组合回测后台任务（资金分仓 / 并行制）。

    勾选 N 个策略，各自在原标的（取最新行情）上独立回测，各拿总资金 1/N。
    单个策略取数失败则跳过（不中断整组），全部失败返回 400。结果为
    MultiStrategyResult（结构同 PortfolioResult），通过 GET /backtest/tasks/{task_id} 轮询。
    """
    if mac_client is None or "mac_client" not in inspect.signature(
        _fetch_multi_strategy_bars
    ).parameters:
        slots = await _fetch_multi_strategy_bars(client, req.items)
    else:
        slots = await _fetch_multi_strategy_bars(
            client, req.items, mac_client=mac_client, adjust=req.adjust
        )
    if not slots:
        raise ValueError("所有策略槽位均未取到有效行情数据")

    snapshot = req.model_copy()
    description = f"多策略组合 | {len(slots)}个策略"

    runner = get_runner()
    task_id = runner.submit(
        lambda: _run_multi_strategy_backtest(slots, snapshot),
        description=description,
    )
    state = runner.get(task_id)
    status: Any = state.status if state.status in ("pending", "running") else "running"
    return TaskSubmitResponse(task_id=task_id, status=status)


@router.post("/backtest/optimize/run/async", response_model=TaskSubmitResponse, status_code=202)
async def run_optimize_async(
    req: OptimizeBacktestRequest,
    client: Any = Depends(get_client),
    mac_client: Any | None = Depends(get_mac_client_optional),
) -> TaskSubmitResponse:
    """提交参数网格寻优后台任务。

    在单个标的上对策略参数做网格搜索。数据获取支持内联 ohlcv 或按 symbol 取行情。
    通过 GET /backtest/tasks/{task_id} 轮询结果。
    """
    # 1. 取数据
    if req.ohlcv is not None:
        df = _ohlcv_to_df(req.ohlcv)
        desc_bars = f"{len(df)} 根"
    elif req.symbol is not None:
        if mac_client is None or "mac_client" not in inspect.signature(_fetch_bars).parameters:
            df = await _fetch_bars(client, req.symbol, req.category, 800)
        else:
            df = await _fetch_bars(
                client,
                req.symbol,
                req.category,
                800,
                mac_client=mac_client,
                adjust=req.adjust,
            )
        desc_bars = f"{req.symbol}"
        if req.start_date or req.end_date:
            df = _filter_df_by_date(df, req.start_date, req.end_date)
    else:
        raise ValueError("必须提供 ohlcv 或 symbol")

    # 2. 捕获快照
    snapshot = req.model_copy()
    grid_size = 1
    for vals in snapshot.param_grid.values():
        grid_size *= len(vals)
    description = f"{snapshot.strategy} 寻优 | {desc_bars} | {grid_size}点"

    # 3. 提交后台任务
    runner = get_runner()
    task_id = runner.submit(
        lambda: _run_optimize(df, snapshot),
        description=description,
    )
    state = runner.get(task_id)
    status: Any = state.status if state.status in ("pending", "running") else "running"
    return TaskSubmitResponse(task_id=task_id, status=status)


# ── 一键寻优所有策略 ───────────────────────────────────────────────────────────


@router.post("/backtest/optimize-all/run/async", response_model=TaskSubmitResponse, status_code=202)
async def run_optimize_all_async(
    req: OptimizeAllBacktestRequest,
    client: Any = Depends(get_client),
    mac_client: Any | None = Depends(get_mac_client_optional),
) -> TaskSubmitResponse:
    """提交「一键寻优所有策略」后台任务。

    在单个标的上，对所有策略的预设参数网格（见 presets.STRATEGY_PRESETS）依次
    做网格寻优，取各策略最优点汇总成全局排名。数据获取支持内联 ohlcv 或按
    symbol 取行情。通过 GET /backtest/tasks/{task_id} 轮询结果。
    """
    # 1. 取数据
    if req.ohlcv is not None:
        df = _ohlcv_to_df(req.ohlcv)
        desc_bars = f"{len(df)} 根"
    elif req.symbol is not None:
        if mac_client is None or "mac_client" not in inspect.signature(_fetch_bars).parameters:
            df = await _fetch_bars(client, req.symbol, req.category, 800)
        else:
            df = await _fetch_bars(
                client,
                req.symbol,
                req.category,
                800,
                mac_client=mac_client,
                adjust=req.adjust,
            )
        desc_bars = f"{req.symbol}"
        if req.start_date or req.end_date:
            df = _filter_df_by_date(df, req.start_date, req.end_date)
    else:
        raise ValueError("必须提供 ohlcv 或 symbol")

    # 2. 捕获快照
    snapshot = req.model_copy()
    description = f"一键寻优全部策略 | {desc_bars}"

    # 3. 提交后台任务
    runner = get_runner()
    task_id = runner.submit(
        lambda: _run_optimize_all(df, snapshot),
        description=description,
    )
    state = runner.get(task_id)
    status: Any = state.status if state.status in ("pending", "running") else "running"
    return TaskSubmitResponse(task_id=task_id, status=status)


# ── 信号雷达（一键扫描已保存策略）────────────────────────────────────────────


@router.post("/backtest/signal-scan/run/async", response_model=TaskSubmitResponse, status_code=202)
async def run_signal_scan_async(
    req: SignalScanRequest,
    client: Any = Depends(get_client),
    mac_client: Any | None = Depends(get_mac_client_optional),
    user: UserRecord = Depends(get_current_user),
) -> TaskSubmitResponse:
    """提交「信号雷达」后台任务：扫描策略库全部已保存策略的最近买卖信号。

    single/portfolio/multi 统一展开成"策略×标的"子任务，按 (symbol, category)
    去重取最近 800 根 K 线（async 上下文内完成），后台线程内逐条跑信号流程
    （与回测引擎同口径，含仓位跟踪）。只扫信号、不重跑回测、不改业绩快照。
    结果为 SignalScanResult，通过 GET /backtest/tasks/{task_id} 轮询。
    """
    from easy_tdx.web.signal_scan import expand_targets, fetch_scan_bars, run_scan
    from easy_tdx.web.strategy_store import get_store

    records = get_store().list_all(user.id)
    if not records:
        raise ValueError("策略库为空，请先在回测页保存策略")

    targets = expand_targets(records)
    if mac_client is None or "mac_client" not in inspect.signature(fetch_scan_bars).parameters:
        bars = await fetch_scan_bars(client, targets)
    else:
        bars = await fetch_scan_bars(client, targets, mac_client=mac_client, adjust=req.adjust)
    description = (
        f"信号扫描 | {len(records)}条策略 · {len(targets)}个子任务 · 窗口{req.window_bars}根"
    )

    runner = get_runner()
    task_id = runner.submit(
        lambda: run_scan(bars, targets, req.window_bars),
        description=description,
    )
    state = runner.get(task_id)
    status: Any = state.status if state.status in ("pending", "running") else "running"
    return TaskSubmitResponse(task_id=task_id, status=status)


# ── 内部实现 ───────────────────────────────────────────────────────────────────


def _run_backtest(df: pd.DataFrame, req: BacktestRequest) -> dict[str, Any]:
    """执行回测并返回清洗后的结果字典（后台线程内调用）。"""
    from easy_tdx.backtest import BacktestEngine
    from easy_tdx.backtest.strategies import get_registry

    # 解析策略 + 校验参数（registry 抛 KeyError，统一转 ValueError → HTTP 400）
    try:
        entry = get_registry().get(req.strategy)
    except KeyError as exc:
        raise ValueError(str(exc)) from exc
    strategy = entry.build(req.params)

    engine = BacktestEngine(
        strategy=strategy,
        cash=req.cash,
        commission=req.commission,
        min_commission=req.min_commission,
        stamp_tax=req.stamp_tax,
        slippage=req.slippage,
        execution=req.execution,
    )
    result = engine.run(df)
    return serialize_result(result)


def _ohlcv_to_df(records: list[dict[str, Any]]) -> pd.DataFrame:
    """把内联 OHLCV 记录列表转为 DataFrame，校验必需列并把 datetime 转为真正的时间类型。

    StrategyDataProxy 依赖 datetime 列为 datetime64/pandas Timestamp 才能正确
    编码为 YYYYMMDD 整数；若内联数据传字符串日期，这里负责转换。
    """
    required = {"datetime", "open", "high", "low", "close", "vol", "amount"}
    df = pd.DataFrame(records)
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"ohlcv 缺少必需列: {sorted(missing)}；需要 {sorted(required)}")
    if len(df) < 2:
        raise ValueError(f"ohlcv 至少需要 2 根 K 线，当前 {len(df)} 根")
    # 确保 datetime 是真正的时间类型（容忍字符串/数值输入）
    if not pd.api.types.is_datetime64_any_dtype(df["datetime"]):
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    return df


async def _fetch_bars(
    client: Any,
    symbol: str,
    category: str,
    count: int,
    *,
    mac_client: Any | None = None,
    adjust: str = "QFQ",
) -> pd.DataFrame:
    """按标的取 K 线（async，必须在 event loop 内调用）。"""
    market_str, code = symbol.split(":", 1)
    df = await fetch_adjusted_bars(
        client, mac_client, market_str, code, category, 0, count, adjust
    )
    if len(df) == 0:
        raise ValueError(f"标的 {symbol} 未取到任何 K 线数据")
    return df


def _run_portfolio_backtest(
    stock_data_list: list[Any], req: PortfolioBacktestRequest
) -> dict[str, Any]:
    """执行组合回测并返回清洗后的结果字典（后台线程内调用）。"""
    from easy_tdx.backtest.portfolio_engine import PortfolioBacktestEngine
    from easy_tdx.backtest.strategies import get_registry

    try:
        entry = get_registry().get(req.strategy)
    except KeyError as exc:
        raise ValueError(str(exc)) from exc
    strategy = entry.build(req.params)

    engine = PortfolioBacktestEngine(
        strategy=strategy,
        stocks=stock_data_list,
        total_cash=req.cash,
        commission=req.commission,
        min_commission=req.min_commission,
        stamp_tax=req.stamp_tax,
        slippage=req.slippage,
        execution=req.execution,
    )
    result = engine.run()
    return serialize_result(result)


async def _fetch_portfolio_bars(
    client: Any,
    stocks: list[str],
    category: str,
    start_date: str | None,
    end_date: str | None,
    *,
    mac_client: Any | None = None,
    adjust: str = "QFQ",
) -> list[Any]:
    """逐个标的取 K 线并组装 StockData 列表（async，必须在 event loop 内调用）。

    当 start_date 超出单次 800 根覆盖范围时，自动翻页拉取（与前端 fetchBars
    同逻辑）。单个标的取数失败时跳过（不中断整个组合），全部失败返回空列表。
    """
    from easy_tdx.backtest.portfolio_engine import StockData
    max_pages = 10  # 翻页上限：10 × 800 = 8000 根
    stock_data_list: list[StockData] = []
    for symbol in stocks:
        market_str, code = symbol.split(":", 1)
        frames: list[pd.DataFrame] = []
        for page in range(max_pages):
            try:
                page_df = await fetch_adjusted_bars(
                    client,
                    mac_client,
                    market_str,
                    code,
                    category,
                    page * 800,
                    800,
                    adjust,
                )
            except Exception:
                break  # 单页失败则停止该标的的翻页
            if len(page_df) == 0:
                break
            frames.append(page_df)
            # 已覆盖到 start_date（本页最早一根 ≤ start_date）则停止
            if start_date and len(page_df) > 0:
                dt_col = "datetime" if "datetime" in page_df.columns else "date"
                oldest = str(page_df[dt_col].iloc[-1])[:10]
                if oldest <= start_date:
                    break
            if len(page_df) < 800:
                break  # 数据起点

        if not frames:
            continue
        df = pd.concat(frames, ignore_index=True)
        # 列名归一化：日线返回 date，分钟线返回 datetime
        if "datetime" not in df.columns and "date" in df.columns:
            df = df.copy()
            df["datetime"] = df["date"]
        # 翻页拼接后按时间正序排序（页间逆序）
        df = df.sort_values("datetime").reset_index(drop=True)
        # 日期范围过滤
        if start_date or end_date:
            dt_str = df["datetime"].astype(str).str.slice(0, 10)
            mask = pd.Series(True, index=df.index)
            if start_date:
                mask &= dt_str >= start_date
            if end_date:
                mask &= dt_str <= end_date
            df = df[mask]
        if len(df) < 2:
            continue
        stock_data_list.append(
            StockData(code=code, market=market_str, df=df.reset_index(drop=True))
        )
    return stock_data_list


async def _fetch_multi_strategy_bars(
    client: Any,
    items: list[Any],
    *,
    mac_client: Any | None = None,
    adjust: str = "QFQ",
) -> list[Any]:
    """逐个策略槽位取行情 + 构造策略实例，组装 StrategySlot 列表（async）。

    每条 item 自带 symbol（如 "SH:601088"）、category、start/end_date、strategy+params。
    单条取数或策略构造失败则跳过（不中断整组）。返回的 StrategySlot 已绑定好策略
    实例与 df，可直接交给后台线程跑引擎（避免把 async client 带进线程）。
    """
    from easy_tdx.backtest.multi_strategy_engine import StrategySlot
    from easy_tdx.backtest.strategies import get_registry
    registry = get_registry()
    slots: list[StrategySlot] = []
    for item in items:
        # 1. 解析策略（未知策略跳过）
        try:
            entry = registry.get(item.strategy)
        except KeyError:
            continue
        # 2. 逐页取行情（覆盖 start_date，最多 10 页 = 8000 根）
        market_str, code = item.symbol.split(":", 1)
        frames: list[pd.DataFrame] = []
        for page in range(10):
            try:
                page_df = await fetch_adjusted_bars(
                    client,
                    mac_client,
                    market_str,
                    code,
                    item.category,
                    page * 800,
                    800,
                    adjust,
                )
            except Exception:
                break
            if len(page_df) == 0:
                break
            frames.append(page_df)
            if item.start_date and len(page_df) > 0:
                dt_col = "datetime" if "datetime" in page_df.columns else "date"
                oldest = str(page_df[dt_col].iloc[-1])[:10]
                if oldest <= item.start_date:
                    break
            if len(page_df) < 800:
                break
        if not frames:
            continue
        df = pd.concat(frames, ignore_index=True)
        if "datetime" not in df.columns and "date" in df.columns:
            df = df.copy()
            df["datetime"] = df["date"]
        df = df.sort_values("datetime").reset_index(drop=True)
        # 日期范围过滤
        if item.start_date or item.end_date:
            df = _filter_df_by_date(df, item.start_date, item.end_date)
        if len(df) < 2:
            continue
        # 3. 构造策略实例（参数非法跳过该条）
        try:
            strategy = entry.build(item.params)
        except ValueError:
            continue
        label = item.strategy_label or entry.label
        slots.append(StrategySlot(label=label, symbol=item.symbol, strategy=strategy, df=df))
    return slots


def _run_multi_strategy_backtest(
    slots: list[Any], req: MultiStrategyBacktestRequest
) -> dict[str, Any]:
    """执行多策略组合回测并返回清洗后的结果字典（后台线程内调用）。"""
    from easy_tdx.backtest.multi_strategy_engine import MultiStrategyEngine

    engine = MultiStrategyEngine(
        strategies=slots,
        total_cash=req.cash,
        commission=req.commission,
        min_commission=req.min_commission,
        stamp_tax=req.stamp_tax,
        slippage=req.slippage,
        execution=req.execution,
    )
    result = engine.run()
    return serialize_result(result)


def _run_optimize(df: pd.DataFrame, req: OptimizeBacktestRequest) -> dict[str, Any]:
    """执行参数网格寻优并返回清洗后的结果字典（后台线程内调用）。"""
    from easy_tdx.backtest.optimizer import ParamGridOptimizer

    optimizer = ParamGridOptimizer(
        strategy_name=req.strategy,
        param_grid=req.param_grid,
        df=df,
        cash=req.cash,
        commission=req.commission,
        slippage=req.slippage,
        execution=req.execution,
    )
    result = optimizer.run()
    return result.to_dict()


def _optimize_one_strategy(
    strategy_name: str,
    grid: dict[str, list[Any]],
    df: pd.DataFrame,
    cash: float,
    commission: float,
    slippage: float,
    execution: str,
) -> dict[str, Any] | None:
    """跑单个策略的网格寻优，返回其最优点摘要（模块顶层，可被 ProcessPoolExecutor pickle）。

    必须是模块级顶层函数：Windows 下 ProcessPoolExecutor 用 spawn 方式启动子进程，
    子进程按 ``module.qualname`` 重新 import 本函数。lambda / 闭包 / 嵌套函数不可 pickle。

    策略类（``registry.get(name).build()``）在子进程内构造，从不跨进程传递，
    因此天然避开了 screen scanner 当年遇到的"策略类不可 pickle"问题。
    返回纯 dict（所有值都是 JSON 原生类型），可安全 pickle 回主进程。
    """
    from easy_tdx.backtest.optimizer import ParamGridOptimizer

    try:
        optimizer = ParamGridOptimizer(
            strategy_name=strategy_name,
            param_grid=grid,
            df=df,
            cash=cash,
            commission=commission,
            slippage=slippage,
            execution=execution,
        )
    except ValueError:
        # 单策略网格超限（不应发生，预设已控制规模）→ 跳过
        return None

    result = optimizer.run()
    if result.best is None:
        return None

    return {
        "strategy": strategy_name,
        "params": result.best.params,
        "total_return": result.best.total_return,
        "sharpe": result.best.sharpe,
        "max_drawdown": result.best.max_drawdown,
        "total_trades": result.best.total_trades,
        "win_rate": result.best.win_rate,
        "profit_factor": result.best.profit_factor,
        "grid_points": len(result.results),
    }


def _run_optimize_all(df: pd.DataFrame, req: OptimizeAllBacktestRequest) -> dict[str, Any]:
    """对所有策略的预设网格逐策略寻优，汇总成全局排名（后台线程内调用）。

    遍历 ``STRATEGY_PRESETS`` 中每个策略，用其预设参数网格跑
    :class:`ParamGridOptimizer`，取各策略的最优点（best）组装排名。单个策略
    无有效结果（如全网格回测失败）则跳过。

    并发：``req.workers >= 2`` 时用 ``ProcessPoolExecutor`` 跨进程并行寻优
    （回测是 CPU-bound，numpy/pandas 持 GIL，线程无加速，必须用进程）。
    ``workers`` 为 0 或 1 时串行。进程池在函数内 ``with`` 创建/销毁，对前端
    轮询与 task_runner 透明。
    """
    from easy_tdx.backtest.strategies import get_registry
    from easy_tdx.backtest.strategies.presets import STRATEGY_PRESETS

    registry = get_registry()
    # 过滤出已注册的策略 + 解析 label（label 必须在主进程取，避免子进程各自解析不一致）
    jobs: list[tuple[str, dict[str, list[Any]]]] = []
    labels: dict[str, str] = {}
    for strategy_name, grid in STRATEGY_PRESETS.items():
        if strategy_name not in registry.names():
            continue
        labels[strategy_name] = registry.get(strategy_name).label
        jobs.append((strategy_name, grid))

    # 跑寻优：串行 or 进程池并行
    raw_results: list[dict[str, Any]] = []
    if req.workers and req.workers >= 2:
        import concurrent.futures

        with concurrent.futures.ProcessPoolExecutor(max_workers=req.workers) as executor:
            futures = {
                executor.submit(
                    _optimize_one_strategy,
                    name,
                    grid,
                    df,
                    req.cash,
                    req.commission,
                    req.slippage,
                    req.execution,
                ): name
                for name, grid in jobs
            }
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res is not None:
                    raw_results.append(res)
    else:
        for name, grid in jobs:
            res = _optimize_one_strategy(
                name, grid, df, req.cash, req.commission, req.slippage, req.execution
            )
            if res is not None:
                raw_results.append(res)

    # 组装排名（主进程统一构造 Pydantic 模型，保证类型一致）
    ranking: list[OptimizeAllRankEntry] = []
    per_strategy: dict[str, OptimizeAllRankEntry] = {}
    total_grid = 0
    for res in raw_results:
        strategy_name = res["strategy"]
        entry = OptimizeAllRankEntry(
            strategy=strategy_name,
            strategy_label=labels[strategy_name],
            params=res["params"],
            total_return=res["total_return"],
            sharpe=res["sharpe"],
            max_drawdown=res["max_drawdown"],
            total_trades=res["total_trades"],
            win_rate=res["win_rate"],
            profit_factor=res["profit_factor"],
            grid_points=res["grid_points"],
        )
        ranking.append(entry)
        per_strategy[strategy_name] = entry
        total_grid += res["grid_points"]

    # 按 total_return 降序
    ranking.sort(key=lambda r: r.total_return, reverse=True)
    best = ranking[0] if ranking else None

    result_obj = OptimizeAllResult(
        ranking=ranking,
        best=best,
        per_strategy=per_strategy,
        total_grid_points=total_grid,
    )
    return result_obj.model_dump()


def _filter_df_by_date(df: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    """按日期范围过滤 DataFrame（闭区间，比较 YYYY-MM-DD）。"""
    if not start and not end:
        return df
    dt_col = "datetime" if "datetime" in df.columns else "date"
    dt_str = df[dt_col].astype(str).str.slice(0, 10)
    mask = pd.Series(True, index=df.index)
    if start:
        mask &= dt_str >= start
    if end:
        mask &= dt_str <= end
    return df[mask].reset_index(drop=True)


def _now() -> float:
    """获取当前时间戳（隔离 import，便于测试）。"""
    import time

    return time.time()
