"""回测路由：策略枚举、同步回测、后台任务回测、任务轮询。

设计要点：
- 回测是纯计算（不依赖行情连接的 lifespan），因此**不注入 tdx_client**——
  只有「按标的取行情」才需要 client，且必须在 async 上下文里取好数据后再
  交给后台线程跑回测（``get_security_bars`` 是 async，不能跨线程调用）。
- 后台任务按显式配置使用持久队列或旧内存执行器；不因存储失败静默回退。
- 同步回测仅支持内联 OHLCV（前端已有数据），避免长任务阻塞 event loop。
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from easy_tdx.computation import computation_checkpoint
from easy_tdx.web import task_service
from easy_tdx.web.account_store import UserRecord, get_account_store
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
from easy_tdx.web.market_data import closed_frame
from easy_tdx.web.research_provenance import frame_evidence, result_evidence
from easy_tdx.web.resource_admission import run_compute
from easy_tdx.web.routers.auth import get_current_user
from easy_tdx.web.task_payload import TaskInput
from easy_tdx.web.task_runner import get_runner

router = APIRouter(tags=["backtest"])


def get_task_user(request: Request, user: UserRecord = Depends(get_current_user)) -> UserRecord:
    expected = request.headers.get("x-task-owner")
    if expected is not None and expected != user.id:
        raise HTTPException(409, "登录账户已变化，请重新提交或打开任务")
    return user


async def _submit_research(
    user: UserRecord,
    description: str,
    build_input: Callable[[str], TaskInput],
    legacy: Callable[[], dict[str, Any]],
    *,
    retain_input: bool = False,
) -> TaskSubmitResponse:
    if task_service.task_backend() == "durable":
        state, reused = await run_compute(
            lambda: task_service.submit_frozen(user.id, description, build_input)
        )
        return TaskSubmitResponse(
            task_id=state["task_id"], status=state["status"], storage="persistent", reused=reused
        )
    runner = get_runner()
    if retain_input:
        from easy_tdx.web.task_dispatch import dispatch_task
        from easy_tdx.web.task_payload import (
            decode_task_input,
            encode_task_input,
            input_fingerprint,
        )
        from easy_tdx.web.task_version import execution_version

        version = execution_version()
        frozen = build_input(version)
        payload = await run_compute(lambda: encode_task_input(frozen))
        fingerprint = input_fingerprint(payload)
        task_id = runner.submit(
            lambda: dispatch_task(
                decode_task_input(payload, execution_version=version, fingerprint=fingerprint)
            ),
            description=description,
            owner_id=user.id,
            frozen_input=(payload, version, fingerprint),
            kind=frozen.kind,
        )
    else:
        task_id = runner.submit(legacy, description=description, owner_id=user.id)
    return TaskSubmitResponse(task_id=task_id, status=runner.get(task_id).status)


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
async def run_backtest(
    req: BacktestRequest, _user: UserRecord = Depends(get_task_user)
) -> BacktestResultResponse:
    """同步回测（仅支持内联 OHLCV 数据）。

    适用于单标的快速回测（<3s）。需要取行情或长任务请用 ``/backtest/run/async``。
    """
    if req.ohlcv is None:
        raise ValueError(
            "同步回测（/backtest/run）必须提供 ohlcv 内联数据；取行情请用 /backtest/run/async"
        )

    df = _ohlcv_to_df(req.ohlcv, category=req.category, adjust=req.adjust)
    df = _filter_df_by_date(df, req.start_date, req.end_date)
    result_dict = await run_compute(lambda: _run_backtest(df, req))
    return BacktestResultResponse(**result_dict)


# ── 后台任务回测 ───────────────────────────────────────────────────────────────


@router.post("/backtest/run/async", response_model=TaskSubmitResponse, status_code=202)
async def run_backtest_async(
    req: BacktestRequest,
    client: Any = Depends(get_client),
    mac_client: Any | None = Depends(get_mac_client_optional),
    user: UserRecord = Depends(get_task_user),
) -> TaskSubmitResponse:
    """提交后台回测任务，立即返回 task_id。

    支持内联数据或按标的取行情。取行情在 async 上下文完成（client 是 async 的），
    之后回测在后台线程执行。通过 ``GET /backtest/tasks/{task_id}`` 轮询结果。
    """
    # 1. 取数据（async 上下文内完成）
    if req.ohlcv is not None:
        df = _ohlcv_to_df(req.ohlcv, category=req.category, adjust=req.adjust)
        df = _filter_df_by_date(df, req.start_date, req.end_date)
        bars_desc = f"{len(df)} 根"
    elif req.symbol is not None:
        if req.start_date or req.end_date:
            market, code = req.symbol.split(":", 1)
            df = await _history_frame(
                client,
                mac_client,
                market,
                code,
                req.category,
                req.adjust,
                req.start_date,
                req.end_date,
            )
        elif "mac_client" not in inspect.signature(_fetch_bars).parameters:
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
    return await _submit_research(
        user,
        description,
        lambda version: TaskInput("backtest", version, snapshot.model_dump(), (df,), {}),
        lambda: _run_backtest(df, snapshot),
    )


@router.get("/backtest/tasks", response_model=TaskListResponse)
async def list_tasks(
    limit: int = Query(20, ge=1, le=100), user: UserRecord = Depends(get_task_user)
) -> TaskListResponse:
    """列出最近 N 个任务摘要（按最近使用倒序，不含完整 result）。

    供对比页选择要对比的 task；选中后再逐个调 /tasks/{task_id} 拉详情。
    """
    import time

    if task_service.task_backend() == "durable":
        rows = await run_in_threadpool(task_service.read_tasks, user.id, limit)
        summaries = [TaskSummary(**row, storage="persistent") for row in rows]
        return TaskListResponse(tasks=summaries, count=len(summaries), storage="persistent")
    runner = get_runner()
    states = runner.list_recent(limit, owner_id=user.id)
    summaries = [
        TaskSummary(
            task_id=s.task_id,
            status=s.status,
            kind=s.kind,
            progress=s.progress,
            description=s.description,
            created_at=s.created_at,
            elapsed=(s.finished_at or time.time()) - (s.started_at or s.created_at),
        )
        for s in states
    ]
    return TaskListResponse(tasks=summaries, count=len(summaries))


@router.get("/backtest/tasks/{task_id}", response_model=TaskStateResponse)
async def get_task(task_id: str, user: UserRecord = Depends(get_task_user)) -> TaskStateResponse:
    """查询后台回测任务状态。done 时 result 字段含完整回测结果。"""
    if task_service.task_backend() == "durable":
        state_dict = await run_in_threadpool(task_service.read_task, user.id, task_id)
        if (
            state_dict.get("kind") == "signal_scan"
            and state_dict.get("status") == "done"
            and isinstance(state_dict.get("result"), dict)
        ):
            state_dict["result"] = {**state_dict["result"], "evidence_task_id": task_id}
        return TaskStateResponse(**state_dict, storage="persistent")
    state = get_runner().peek(task_id)
    if state is None or state.owner_id != user.id:
        # Same response for missing and foreign tasks; never disclose ownership.
        raise HTTPException(404, "任务不存在或不属于当前账户")
    return TaskStateResponse(
        task_id=state.task_id,
        status=state.status,
        kind=state.kind,
        progress=state.progress,
        result={**state.result, "evidence_task_id": task_id}
        if state.status == "done"
        and state.result is not None
        and state.frozen_input
        and isinstance(state.result.get("rows"), list)
        else state.result,
        error=state.error,
        description=state.description,
        elapsed=(state.finished_at or _now()) - (state.started_at or state.created_at),
    )


@router.get("/backtest/tasks/{task_id}/portfolio-evidence")
async def get_portfolio_evidence(
    task_id: str, response: Response, user: UserRecord = Depends(get_task_user)
) -> dict[str, Any]:
    from easy_tdx.web.portfolio_evidence import read_portfolio_evidence

    response.headers["Cache-Control"] = "no-store"
    return await run_in_threadpool(read_portfolio_evidence, user.id, task_id)


@router.post("/backtest/tasks/{task_id}/cancel", response_model=TaskStateResponse)
async def cancel_task(task_id: str, user: UserRecord = Depends(get_task_user)) -> TaskStateResponse:
    if task_service.task_backend() == "durable":
        state_dict = await run_in_threadpool(task_service.cancel_task, user.id, task_id)
        return TaskStateResponse(**state_dict, storage="persistent")
    runner = get_runner()
    state = runner.peek(task_id)
    if state is None or state.owner_id != user.id:
        raise HTTPException(404, "任务不存在或不属于当前账户")
    previous = state.status
    try:
        runner.cancel(task_id)
    except KeyError as exc:
        raise HTTPException(404, "任务不存在或不属于当前账户") from exc
    if previous in {"pending", "running"}:
        get_account_store().audit_operation("task_cancel", user.id, details={"task_id": task_id})
    # Keep the captured object: a concurrent completion may evict the historical
    # entry, but this request must still acknowledge its actual cancellation state.
    return TaskStateResponse(**state.to_dict())


@router.get("/backtest/tasks/{task_id}/scan-evidence/{row_index}")
async def scan_evidence(
    task_id: str, row_index: int, response: Response, user: UserRecord = Depends(get_task_user)
) -> dict[str, Any]:
    from easy_tdx.web.scan_evidence import read_scan_evidence

    response.headers["Cache-Control"] = "no-store"
    return await run_compute(lambda: read_scan_evidence(user.id, task_id, row_index))


@router.delete("/backtest/tasks/{task_id}", status_code=204, response_model=None)
async def delete_task(task_id: str, user: UserRecord = Depends(get_task_user)) -> None:
    """Explicit owner deletion of terminal task records, not saved strategies."""
    if task_service.task_backend() != "durable":
        raise HTTPException(409, "当前使用内存任务记录，无持久记录可删除")
    await run_in_threadpool(task_service.delete_task, user.id, task_id)


# ── 组合回测 ───────────────────────────────────────────────────────────────────


@router.post("/backtest/portfolio/run/async", response_model=TaskSubmitResponse, status_code=202)
async def run_portfolio_backtest_async(
    req: PortfolioBacktestRequest,
    client: Any = Depends(get_client),
    mac_client: Any | None = Depends(get_mac_client_optional),
    user: UserRecord = Depends(get_task_user),
) -> TaskSubmitResponse:
    """提交组合（多标的）回测后台任务。

    逐个标的取行情（async），组装 StockData 列表后提交后台任务跑
    PortfolioBacktestEngine。通过 GET /backtest/tasks/{task_id} 轮询结果。
    """
    # 1. 逐个标的取行情（async 上下文内）
    if "mac_client" not in inspect.signature(_fetch_portfolio_bars).parameters:
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
    return await _submit_research(
        user,
        description,
        lambda version: TaskInput(
            "portfolio",
            version,
            snapshot.model_dump(),
            tuple(stock.df for stock in stock_data_list),
            {},
        ),
        lambda: _run_portfolio_backtest(stock_data_list, snapshot),
        retain_input=True,
    )


# ── 多策略组合回测（资金分仓） ───────────────────────────────────────────────


@router.post(
    "/backtest/multi-strategy/run/async", response_model=TaskSubmitResponse, status_code=202
)
async def run_multi_strategy_backtest_async(
    req: MultiStrategyBacktestRequest,
    client: Any = Depends(get_client),
    mac_client: Any | None = Depends(get_mac_client_optional),
    user: UserRecord = Depends(get_task_user),
) -> TaskSubmitResponse:
    """提交多策略组合回测后台任务（资金分仓 / 并行制）。

    勾选 N 个策略，各自在原标的（取最新行情）上独立回测，各拿总资金 1/N。
    任一策略取数失败即停止，不能改变资金分仓。结果为
    MultiStrategyResult（结构同 PortfolioResult），通过 GET /backtest/tasks/{task_id} 轮询。
    """
    if "mac_client" not in inspect.signature(_fetch_multi_strategy_bars).parameters:
        slots = await _fetch_multi_strategy_bars(client, req.items)
    else:
        slots = await _fetch_multi_strategy_bars(
            client, req.items, mac_client=mac_client, adjust=req.adjust
        )
    if not slots:
        raise ValueError("所有策略槽位均未取到有效行情数据")

    snapshot = req.model_copy()
    description = f"多策略组合 | {len(slots)}个策略"

    return await _submit_research(
        user,
        description,
        lambda version: TaskInput(
            "multi_strategy", version, snapshot.model_dump(), tuple(slot.df for slot in slots), {}
        ),
        lambda: _run_multi_strategy_backtest(slots, snapshot),
        retain_input=True,
    )


@router.post("/backtest/optimize/run/async", response_model=TaskSubmitResponse, status_code=202)
async def run_optimize_async(
    req: OptimizeBacktestRequest,
    client: Any = Depends(get_client),
    mac_client: Any | None = Depends(get_mac_client_optional),
    user: UserRecord = Depends(get_task_user),
) -> TaskSubmitResponse:
    """提交参数网格寻优后台任务。

    在单个标的上对策略参数做网格搜索。数据获取支持内联 ohlcv 或按 symbol 取行情。
    通过 GET /backtest/tasks/{task_id} 轮询结果。
    """
    # 1. 取数据
    df = await _optimize_input(client, mac_client, req)
    desc_bars = f"{req.symbol or '内联数据'} · {len(df)} 根"

    # 2. 捕获快照
    snapshot = req.model_copy()
    grid_size = 1
    for vals in snapshot.param_grid.values():
        grid_size *= len(vals)
    description = f"{snapshot.strategy} 寻优 | {desc_bars} | {grid_size}点"

    # 3. 提交后台任务
    return await _submit_research(
        user,
        description,
        lambda version: TaskInput("optimize", version, snapshot.model_dump(), (df,), {}),
        lambda: _run_optimize(df, snapshot),
    )


# ── 一键寻优所有策略 ───────────────────────────────────────────────────────────


@router.post("/backtest/optimize-all/run/async", response_model=TaskSubmitResponse, status_code=202)
async def run_optimize_all_async(
    req: OptimizeAllBacktestRequest,
    client: Any = Depends(get_client),
    mac_client: Any | None = Depends(get_mac_client_optional),
    user: UserRecord = Depends(get_task_user),
) -> TaskSubmitResponse:
    """提交「一键寻优所有策略」后台任务。

    在单个标的上，对所有策略的预设参数网格（见 presets.STRATEGY_PRESETS）依次
    做网格寻优，取各策略最优点汇总成全局排名。数据获取支持内联 ohlcv 或按
    symbol 取行情。通过 GET /backtest/tasks/{task_id} 轮询结果。
    """
    # 1. 取数据
    df = await _optimize_input(client, mac_client, req)
    desc_bars = f"{req.symbol or '内联数据'} · {len(df)} 根"

    # 2. 捕获快照
    snapshot = req.model_copy()
    description = f"一键寻优全部策略 | {desc_bars}"

    # 3. 提交后台任务
    return await _submit_research(
        user,
        description,
        lambda version: TaskInput("optimize_all", version, snapshot.model_dump(), (df,), {}),
        lambda: _run_optimize_all(df, snapshot),
    )


# ── 信号雷达（一键扫描已保存策略）────────────────────────────────────────────


@router.post("/backtest/signal-scan/run/async", response_model=TaskSubmitResponse, status_code=202)
async def run_signal_scan_async(
    req: SignalScanRequest,
    client: Any = Depends(get_client),
    mac_client: Any | None = Depends(get_mac_client_optional),
    user: UserRecord = Depends(get_task_user),
) -> TaskSubmitResponse:
    """提交「信号雷达」后台任务：扫描策略库全部已保存策略的最近买卖信号。

    single/portfolio/multi 统一展开成"策略×标的"子任务，按 (symbol, category)
    去重取最近 800 根 K 线（async 上下文内完成），后台线程内逐条跑信号流程
    （与回测引擎同口径，含仓位跟踪）。只扫信号、不重跑回测、不改业绩快照。
    结果为 SignalScanResult，通过 GET /backtest/tasks/{task_id} 轮询。
    """
    from easy_tdx.web.signal_scan import expand_targets, fetch_scan_bars, run_scan
    from easy_tdx.web.strategy_store import get_store
    from easy_tdx.web.task_dispatch import scan_task_input

    records = get_store().list_all(user.id)
    if not records:
        raise ValueError("策略库为空，请先在回测页保存策略")

    targets = expand_targets(records)
    if "mac_client" not in inspect.signature(fetch_scan_bars).parameters:
        bars = await fetch_scan_bars(client, targets)
    else:
        bars = await fetch_scan_bars(client, targets, mac_client=mac_client, adjust=req.adjust)
    description = (
        f"信号扫描 | {len(records)}条策略 · {len(targets)}个子任务 · 窗口{req.window_bars}根"
    )

    return await _submit_research(
        user,
        description,
        lambda version: scan_task_input(version, req, bars, targets),
        lambda: run_scan(bars, targets, req.window_bars),
        retain_input=True,
    )


# ── 内部实现 ───────────────────────────────────────────────────────────────────


def _run_backtest(df: pd.DataFrame, req: BacktestRequest) -> dict[str, Any]:
    """执行回测并返回清洗后的结果字典（后台线程内调用）。"""
    from easy_tdx.backtest import BacktestEngine
    from easy_tdx.backtest.performance_sampling import performance_frame
    from easy_tdx.backtest.strategies import get_registry

    df = performance_frame(df, req.category)

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
    evidence = result_evidence(
        req,
        [
            frame_evidence(
                df,
                category=req.category,
                adjust=req.adjust,
                symbol=req.symbol,
                label=req.strategy,
            )
        ],
    )
    result = engine.run(df, checkpoint_key="backtest/signals")
    evidence["performance_basis"] = result.config.get("performance_basis")
    response = serialize_result(result)
    response["data_provenance"] = evidence
    from easy_tdx.web.task_version import execution_version

    response["execution_version"] = execution_version()
    return response


def _ohlcv_to_df(
    records: list[dict[str, Any]], *, category: str = "DAY", adjust: str = "UNKNOWN"
) -> pd.DataFrame:
    """把内联 OHLCV 记录列表转为 DataFrame，校验必需列并把 datetime 转为真正的时间类型。

    StrategyDataProxy 依赖 datetime 列为 datetime64/pandas Timestamp 才能正确
    编码为 YYYYMMDD 整数；若内联数据传字符串日期，这里负责转换。
    """
    required = {"datetime", "open", "high", "low", "close", "vol", "amount"}
    df = pd.DataFrame(records)
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"ohlcv 缺少必需列: {sorted(missing)}；需要 {sorted(required)}")
    from easy_tdx.web.bar_snapshot import annotate_snapshot

    snapshot = annotate_snapshot(
        records,
        category,
        source="CLIENT_INPUT",
        requested_adjust=adjust,
        actual_adjust="UNKNOWN",
        bar_time="end",
    )
    if snapshot["metadata"]["quality"]["errors"]:
        raise ValueError(
            "ohlcv 质量检查失败：" + "；".join(snapshot["metadata"]["quality"]["errors"])
        )
    df = pd.DataFrame(snapshot["data"])
    df.attrs["snapshot_metadata"] = snapshot["metadata"]
    df.attrs["snapshot_metadata"]["source_note"] = (
        "浏览器上传数据；来源与复权未独立核验，未当作服务端行情证明"
    )
    df = closed_frame(df)
    if len(df) < 2:
        raise ValueError(f"ohlcv 至少需要 2 根 K 线，当前 {len(df)} 根")
    # 上面已拒绝无单位数字与无效时间；不要用 errors=coerce 静默引入 NaT。
    if not pd.api.types.is_datetime64_any_dtype(df["datetime"]):
        df["datetime"] = pd.to_datetime(df["datetime"], errors="raise")
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
    df = await fetch_adjusted_bars(client, mac_client, market_str, code, category, 0, count, adjust)
    df = closed_frame(df)
    if len(df) == 0:
        raise ValueError(f"标的 {symbol} 未取到任何 K 线数据")
    return df


def _run_portfolio_backtest(
    stock_data_list: list[Any], req: PortfolioBacktestRequest
) -> dict[str, Any]:
    """执行组合回测并返回清洗后的结果字典（后台线程内调用）。"""
    from dataclasses import replace

    from easy_tdx.backtest.performance_sampling import performance_frame
    from easy_tdx.backtest.portfolio_engine import PortfolioBacktestEngine
    from easy_tdx.backtest.strategies import get_registry

    stock_data_list = [
        replace(stock, df=performance_frame(stock.df, req.category)) for stock in stock_data_list
    ]

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
    evidence = result_evidence(
        req,
        [
            frame_evidence(
                stock.df,
                category=req.category,
                adjust=req.adjust,
                symbol=f"{stock.market}:{stock.code}",
                label=f"{stock.market}{stock.code}",
            )
            for stock in stock_data_list
        ],
    )
    result = engine.run()
    evidence["performance_basis"] = result.performance_basis
    response = serialize_result(result)
    response["data_provenance"] = evidence
    response["data_provenance"]["alignment"] = "independent_equity_union_forward_fill"
    return response


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

    与个股页面共用重叠复核分页；任一标的失败时停止，不能静默改变用户组合。
    """
    from easy_tdx.backtest.portfolio_engine import StockData

    stock_data_list: list[StockData] = []
    for symbol in stocks:
        market_str, code = symbol.split(":", 1)
        df = await _history_frame(
            client, mac_client, market_str, code, category, adjust, start_date, end_date
        )
        stock_data_list.append(
            StockData(code=code, market=market_str, df=df.reset_index(drop=True))
        )
    return stock_data_list


async def _history_frame(
    client: Any,
    mac_client: Any,
    market: str,
    code: str,
    category: str,
    adjust: str,
    start: str | None,
    end: str | None,
) -> pd.DataFrame:
    from datetime import date

    from easy_tdx.web.market_range import load_equity_range

    try:
        snapshot = await load_equity_range(
            client,
            mac_client,
            market,
            code,
            category,
            adjust,
            date.fromisoformat(start) if start else None,
            date.fromisoformat(end) if end else None,
        )
    except Exception as exc:
        raise ValueError(
            f"{market}:{code} 行情取数失败，研究未执行：{getattr(exc, 'detail', str(exc))}"
        ) from exc
    if len(snapshot["data"]) < 2:
        raise ValueError(f"{market}:{code} 有效收盘行情不足 2 根，研究未执行；未跳过该标的")
    df = pd.DataFrame(snapshot["data"])
    if "datetime" not in df and "date" in df:
        df["datetime"] = df["date"]
    # Range snapshots are JSON records. Restore typed bar identity before the
    # strategy/engine boundary, retaining intraday times rather than YYYYMMDD.
    # load_equity_range already validates local dates; never coerce bad dates.
    df["datetime"] = pd.to_datetime(df["datetime"], errors="raise")
    df.attrs["snapshot_metadata"] = snapshot["metadata"]
    return df


async def _optimize_input(client: Any, mac_client: Any, req: Any) -> pd.DataFrame:
    if req.ohlcv is not None:
        frame = _ohlcv_to_df(req.ohlcv, category=req.category, adjust=req.adjust)
        frame = _filter_df_by_date(frame, req.start_date, req.end_date)
    elif req.start_date or req.end_date:
        market, code = req.symbol.split(":", 1)
        frame = await _history_frame(
            client, mac_client, market, code, req.category, req.adjust, req.start_date, req.end_date
        )
    else:
        frame = await _fetch_bars(
            client, req.symbol, req.category, req.count, mac_client=mac_client, adjust=req.adjust
        )
    if len(frame) < 2:
        raise ValueError("请求区间有效收盘行情不足 2 根，寻优未执行")
    return frame


async def _fetch_multi_strategy_bars(
    client: Any,
    items: list[Any],
    *,
    mac_client: Any | None = None,
    adjust: str = "QFQ",
) -> list[Any]:
    """逐个策略槽位取行情 + 构造策略实例，组装 StrategySlot 列表（async）。

    每条 item 自带 symbol（如 "SH:601088"）、category、start/end_date、strategy+params。
    单条取数或策略构造失败即停止，不能默默改变资金分仓。返回的 StrategySlot 已绑定好策略
    实例与 df，可直接交给后台线程跑引擎（避免把 async client 带进线程）。
    """
    from easy_tdx.backtest.multi_strategy_engine import StrategySlot
    from easy_tdx.backtest.strategies import get_registry

    registry = get_registry()
    slots: list[StrategySlot] = []
    for item in items:
        # 1. 策略错误不能默默改变资金分仓。
        try:
            entry = registry.get(item.strategy)
        except KeyError as exc:
            raise ValueError(f"未知策略 {item.strategy}，组合未执行") from exc
        # 2. 与个股页、组合回测共用区间口径。
        market_str, code = item.symbol.split(":", 1)
        df = await _history_frame(
            client,
            mac_client,
            market_str,
            code,
            item.category,
            adjust,
            item.start_date,
            item.end_date,
        )
        # 3. 构造策略实例（参数非法跳过该条）
        try:
            strategy = entry.build(item.params)
        except ValueError as exc:
            raise ValueError(f"{item.strategy} 参数无效，组合未执行：{exc}") from exc
        label = item.strategy_label or entry.label
        slots.append(StrategySlot(label=label, symbol=item.symbol, strategy=strategy, df=df))
    return slots


def _run_multi_strategy_backtest(
    slots: list[Any], req: MultiStrategyBacktestRequest
) -> dict[str, Any]:
    """执行多策略组合回测并返回清洗后的结果字典（后台线程内调用）。"""
    from dataclasses import replace

    from easy_tdx.backtest.multi_strategy_engine import MultiStrategyEngine
    from easy_tdx.backtest.performance_sampling import performance_frame

    slots = [
        replace(slot, df=performance_frame(slot.df, item.category))
        for slot, item in zip(slots, req.items, strict=True)
    ]

    engine = MultiStrategyEngine(
        strategies=slots,
        total_cash=req.cash,
        commission=req.commission,
        min_commission=req.min_commission,
        stamp_tax=req.stamp_tax,
        slippage=req.slippage,
        execution=req.execution,
    )
    evidence = result_evidence(
        req,
        [
            frame_evidence(
                slot.df,
                category=item.category,
                adjust=req.adjust,
                symbol=slot.symbol,
                label=f"{slot.label}@{slot.symbol}",
            )
            for slot, item in zip(slots, req.items, strict=True)
        ],
    )
    result = engine.run()
    evidence["performance_basis"] = result.performance_basis
    response = serialize_result(result)
    response["data_provenance"] = evidence
    response["data_provenance"]["alignment"] = "independent_equity_union_forward_fill"
    return response


def _run_optimize(df: pd.DataFrame, req: OptimizeBacktestRequest) -> dict[str, Any]:
    """执行参数网格寻优并返回清洗后的结果字典（后台线程内调用）。"""
    from easy_tdx.backtest.optimizer import ParamGridOptimizer
    from easy_tdx.backtest.performance_sampling import performance_frame

    df = performance_frame(df, req.category)

    optimizer = ParamGridOptimizer(
        strategy_name=req.strategy,
        param_grid=req.param_grid,
        df=df,
        cash=req.cash,
        commission=req.commission,
        min_commission=req.min_commission,
        stamp_tax=req.stamp_tax,
        slippage=req.slippage,
        execution=req.execution,
    )
    evidence = result_evidence(
        req,
        [
            frame_evidence(
                df,
                category=req.category,
                adjust=req.adjust,
                symbol=req.symbol,
                label=req.strategy,
            )
        ],
    )
    result = optimizer.run()
    evidence["performance_basis"] = result.performance_basis
    response = result.to_dict()
    response["data_provenance"] = evidence
    return response


def _optimize_one_strategy(
    strategy_name: str,
    grid: dict[str, list[Any]],
    df: pd.DataFrame,
    cash: float,
    commission: float,
    slippage: float,
    execution: str,
    min_commission: float = 5.0,
    stamp_tax: float = 0.001,
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
            min_commission=min_commission,
            stamp_tax=stamp_tax,
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
        "metric_status": result.best.metric_status,
        "grid_points": len(result.results),
    }


def _run_optimize_all(
    df: pd.DataFrame, req: OptimizeAllBacktestRequest, *, process_budget: int | None = None
) -> dict[str, Any]:
    """对所有策略的预设网格逐策略寻优，汇总成全局排名（后台线程内调用）。

    遍历 ``STRATEGY_PRESETS`` 中每个策略，用其预设参数网格跑
    :class:`ParamGridOptimizer`，取各策略的最优点（best）组装排名。单个策略
    无有效结果（如全网格回测失败）则跳过。

    并发：``req.workers >= 2`` 时用 ``ProcessPoolExecutor`` 跨进程并行寻优
    （回测是 CPU-bound，numpy/pandas 持 GIL，线程无加速，必须用进程）。
    ``workers`` 为 0 或 1 时串行。进程池在函数内 ``with`` 创建/销毁，对前端
    轮询与 task_runner 透明。
    """
    from easy_tdx.backtest.performance_sampling import input_sampling_basis, performance_frame
    from easy_tdx.backtest.strategies import get_registry
    from easy_tdx.backtest.strategies.presets import STRATEGY_PRESETS

    df = performance_frame(df, req.category)

    if process_budget is not None and (type(process_budget) is not int or process_budget < 1):
        raise ValueError("执行进程预算必须为正整数")
    workers = min(req.workers, process_budget) if process_budget is not None else req.workers
    evidence = result_evidence(
        req,
        [
            frame_evidence(
                df,
                category=req.category,
                adjust=req.adjust,
                symbol=req.symbol,
                label="全部策略寻优",
            )
        ],
    )
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
    if workers >= 2:
        import concurrent.futures

        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
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
                    req.min_commission,
                    req.stamp_tax,
                ): name
                for name, grid in jobs
            }
            for future in concurrent.futures.as_completed(futures):
                computation_checkpoint()
                res = future.result()
                if res is not None:
                    raw_results.append(res)
    else:
        for name, grid in jobs:
            computation_checkpoint()
            res = _optimize_one_strategy(
                name,
                grid,
                df,
                req.cash,
                req.commission,
                req.slippage,
                req.execution,
                req.min_commission,
                req.stamp_tax,
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
            metric_status=res.get("metric_status", {}),
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
    response = result_obj.model_dump()
    evidence["performance_basis"] = input_sampling_basis(df)
    response["data_provenance"] = evidence
    return serialize_result(response)


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
    selected = df[mask].reset_index(drop=True)
    if len(selected) < 2:
        raise ValueError("请求区间有效收盘行情不足 2 根，研究未执行")
    from copy import deepcopy

    selected.attrs = deepcopy(df.attrs)
    if "snapshot_metadata" in selected.attrs:
        selected.attrs["snapshot_metadata"].update(requested_start=start, requested_end=end)
    return selected


def _now() -> float:
    """获取当前时间戳（隔离 import，便于测试）。"""
    import time

    return time.time()
