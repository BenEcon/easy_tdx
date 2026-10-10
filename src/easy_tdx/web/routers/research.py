"""量化研究 Web 路由：因子计算、组合权重与风险分析。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from easy_tdx.factor.benchmark import (
    needs_benchmark,
    validate_benchmark_pool,
    validate_frozen_benchmark,
)
from easy_tdx.factor.composition import CompositionConfig, normalize_composition
from easy_tdx.factor.validation import ValidationConfig
from easy_tdx.web.account_store import UserRecord
from easy_tdx.web.adjusted_bars import fetch_adjusted_bars
from easy_tdx.web.backtest_schemas import TaskSubmitResponse
from easy_tdx.web.deps import get_client, get_mac_client_optional
from easy_tdx.web.market_data import closed_frame
from easy_tdx.web.routers.auth import get_current_user
from easy_tdx.web.routers.backtest import _submit_research, get_task_user
from easy_tdx.web.schemas import DataFrameResponse, DictResponse, StockIdentifier

router = APIRouter(tags=["research"])


class FactorRecomputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_archive_id: UUID


class FactorRecomputeTaskRequest(FactorRecomputeRequest):
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_revision: int = Field(strict=True, ge=1)


def validate_factor_recompute_input(
    req: FactorRecomputeTaskRequest, record: dict[str, Any]
) -> None:
    """Verify the frozen archive, not a later database revision or live market data."""
    from easy_tdx.web.research_archive import _dump

    if set(record) != {"id", "digest", "revision", "payload"} or (
        record["id"] != str(req.source_archive_id)
        or record["digest"] != req.expected_digest
        or type(record["revision"]) is not int
        or record["revision"] != req.expected_revision
    ):
        raise ValueError("重算冻结来源与提交时的存档版本不符")
    digest = hashlib.sha256(_dump(record["payload"]).encode("utf-8")).hexdigest()
    if digest != req.expected_digest:
        raise ValueError("重算冻结存档摘要不符，不能采用改变后的内容")


def recompute_factor_payload(record: dict[str, Any]) -> dict[str, Any]:
    """New result from frozen inputs, never a refresh or an overwrite of the source."""
    from easy_tdx.factor.research import cross_section_report
    from easy_tdx.factor.snapshot import freeze_input, restore_input
    from easy_tdx.progress import report_progress
    from easy_tdx.web.factor_archive import validate_factor_archive

    source = record["payload"]
    validate_factor_archive(source)
    original = source["result"]
    settings = dict(original["settings"])
    expected_fields = (
        set(FactorComputeRequest.model_fields)
        if source["mode"] == "series"
        else set(FactorEvaluationRequest.model_fields) | {"category"}
    )
    legacy_fields = (
        expected_fields - set(settings)
        if set(settings) <= expected_fields
        and expected_fields - set(settings)
        <= (
            {"validation", "horizons", "composition", "benchmark"}
            if source["mode"] == "evaluation"
            else {"benchmark"}
        )
        else set()
    )
    legacy_validation = "validation" in legacy_fields
    if legacy_validation:
        # Known old schema was full-sample only; do not introduce a new holdout.
        settings["validation"] = None
    if "horizons" in legacy_fields:
        settings["horizons"] = None  # Known old schema had exactly one requested horizon.
    if "composition" in legacy_fields:
        settings["composition"] = None  # Never invent a combination for a historical archive.
    if "benchmark" in legacy_fields:
        settings["benchmark"] = None  # Old archives never implicitly selected an index.
    if set(settings) != expected_fields:
        raise ValueError("原配置字段与当前实现不兼容；未补入默认值或忽略未知字段")
    # Freeze defaults too: a new release's defaults must not alter this replay.
    settings["factor_parameters"] = {
        name: definition["resolved_parameters"]
        for name, definition in original["factor_definitions"].items()
    }
    frames = {s["symbol"]: restore_input(s) for s in original["input_snapshots"]}
    if source["mode"] == "series":
        request = FactorComputeRequest.model_validate(settings)
        result = _factor_result(request, next(iter(frames.values()))).data
    else:
        request_evaluation = FactorEvaluationRequest.model_validate(
            {k: v for k, v in settings.items() if k != "category"}
        )
        validate_benchmark_pool(frames.values(), request_evaluation.benchmark)
        result = cross_section_report(
            frames,
            request_evaluation.factors,
            request_evaluation.horizon,
            request_evaluation.groups,
            request_evaluation.preprocess,
            factor_parameters=request_evaluation.factor_parameters,
            horizons=request_evaluation.horizons,
            composition=request_evaluation.composition.model_dump()
            if request_evaluation.composition
            else None,
            validation=request_evaluation.validation.model_dump()
            if request_evaluation.validation
            else None,
        )
        result["settings"].update(settings)
        report_progress("archive", 0, len(frames))
        result["input_snapshots"] = [
            freeze_input(symbol, frame) for symbol, frame in frames.items()
        ]
        report_progress("archive", len(frames), len(frames))
        result["adjust"] = request_evaluation.adjust
        result["provenance"] = original["provenance"]
    payload = {
        "format": "factor-research-v1",
        "mode": source["mode"],
        "title": source["title"],
        "savedAt": datetime.now(timezone.utc).isoformat(),
        "result": result,
        "recomputed_from": {
            "archive_id": record["id"],
            "digest": record["digest"],
            "revision": record["revision"],
            "input_policy": "frozen_inputs_current_implementation",
            "provenance": "client_archive_not_server_verified",
            "original_definitions": original["factor_definitions"],
            "original_statistics_version": original.get("statistics_version", "legacy-unrecorded"),
            "configuration_migration": "legacy_full_sample_to_explicit_validation_none"
            if legacy_validation
            else None,
            "horizon_migration": "legacy_single_horizon_to_explicit_horizons_none"
            if "horizons" in legacy_fields
            else None,
            "benchmark_migration": "legacy_no_benchmark_to_explicit_none"
            if "benchmark" in legacy_fields
            else None,
            "composition_migration": "legacy_without_composition_to_explicit_none"
            if "composition" in legacy_fields
            else None,
        },
    }
    validate_factor_archive(payload)
    return payload


@router.post(
    "/research/factors/recompute/async", response_model=TaskSubmitResponse, status_code=202
)
async def factor_recompute_async(
    req: FactorRecomputeTaskRequest,
    response: Response,
    user: UserRecord = Depends(get_task_user),
    expected: str | None = Header(default=None, alias="X-Research-Owner"),
) -> TaskSubmitResponse:
    from easy_tdx.web.research_archive import ArchiveError, get_research_archive
    from easy_tdx.web.resource_admission import run_compute
    from easy_tdx.web.task_payload import TaskInput

    response.headers["Cache-Control"] = "no-store"
    if expected != user.id:
        raise HTTPException(409, "登录账户已变化，请刷新后重试")

    def capture() -> dict[str, Any]:
        record = get_research_archive().get(user.id, str(req.source_archive_id))
        if record["kind"] != "factor" or record["state"] != "active":
            raise ArchiveError(422, "仅能重算当前账户的有效因子存档")
        if record["digest"] != req.expected_digest or record["revision"] != req.expected_revision:
            raise ArchiveError(409, "存档版本已变化，请重新打开原档后提交；未启动重算")
        # Deliberately retain the complete read-only source, including its old
        # formula definitions, input types and legacy configuration migrations.
        return {key: record[key] for key in ("id", "digest", "revision", "payload")}

    try:
        record = await run_compute(capture)
        return await _submit_research(
            user,
            f"因子存档重算 · {record['payload']['title']}",
            lambda version: TaskInput(
                "factor_recompute", version, req.model_dump(mode="json"), (), {"record": record}
            ),
            lambda: recompute_factor_payload(record),
            retain_input=True,
        )
    except ArchiveError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("/research/factors/recompute", response_model=DictResponse)
async def factor_recompute(
    req: FactorRecomputeRequest,
    response: Response,
    user: UserRecord = Depends(get_current_user),
    expected: str | None = Header(default=None, alias="X-Research-Owner"),
) -> DictResponse:
    from easy_tdx.web.research_archive import ArchiveError, get_research_archive
    from easy_tdx.web.resource_admission import run_compute

    response.headers["Cache-Control"] = "no-store"
    if expected != user.id:
        raise HTTPException(409, "登录账户已变化，请刷新后重试")

    def execute() -> dict[str, Any]:
        record = get_research_archive().get(user.id, str(req.source_archive_id))
        if record["kind"] != "factor" or record["state"] != "active":
            raise ArchiveError(422, "仅能重算当前账户的有效因子存档")
        return recompute_factor_payload(record)

    try:
        return DictResponse(data=await run_compute(execute))
    except ArchiveError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, f"当前实现无法按原配置重算，原档未改变：{exc}") from exc


class FactorComputeRequest(BaseModel):
    market: str = Field(..., pattern=r"^(SZ|SH|BJ)$")
    code: str = Field(..., min_length=6, max_length=6)
    category: Literal["DAY", "WEEK", "MONTH", "MIN_1", "MIN_5", "MIN_15", "MIN_30", "MIN_60"] = (
        "DAY"
    )
    count: int = Field(default=300, ge=60, le=800)
    factors: list[str] = Field(..., min_length=1, max_length=12)
    factor_parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    adjust: Literal["NONE", "QFQ", "HFQ"] = "QFQ"
    benchmark: Literal["SH:000001", "SZ:399001", "SH:000300", "SZ:399006"] | None = None

    @model_validator(mode="after")
    def validate_factors(self) -> FactorComputeRequest:
        from easy_tdx.factor import get_factor
        from easy_tdx.factor.catalog import canonical_factor_name, describe_factor
        from easy_tdx.factor.configuration import configured_selection

        configured_selection(self.factors, self.factor_parameters)
        if needs_benchmark(self.factors) != (self.benchmark is not None):
            raise ValueError("基准依赖因子须选择基准指数；其他因子不接受未使用的基准配置")

        if len({canonical_factor_name(n) for n in self.factors}) != len(self.factors):
            raise ValueError("不能重复选择同一因子或其兼容别名")
        for name in self.factors:
            definition = describe_factor(get_factor(name))
            if self.category not in definition["supported_categories"]:
                raise ValueError(f"{name} 不支持 {self.category}；未静默转换周期")
        return self


class FactorEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stocks: list[StockIdentifier] = Field(..., min_length=5, max_length=20)
    factors: list[str] = Field(..., min_length=1, max_length=4)
    factor_parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    count: int = Field(default=300, ge=80, le=800)
    horizon: Literal[1, 5, 10, 20] = 5
    horizons: list[int] | None = Field(default=None, min_length=1, max_length=4)
    groups: Literal[3, 5] = 5
    preprocess: Literal["raw", "mad_zscore"] = "raw"
    adjust: Literal["NONE", "QFQ", "HFQ"] = "QFQ"
    validation: ValidationConfig | None = None
    composition: CompositionConfig | None = None
    benchmark: Literal["SH:000001", "SZ:399001", "SH:000300", "SZ:399006"] | None = None

    @field_validator("horizons", mode="before")
    @classmethod
    def strict_horizons(cls, value: Any) -> Any:
        if value is not None and (
            not isinstance(value, list) or any(type(h) is not int for h in value)
        ):
            raise ValueError("远期窗口必须为整数列表")
        return value

    @model_validator(mode="after")
    def validate_selection(self) -> FactorEvaluationRequest:
        from easy_tdx.factor import get_factor
        from easy_tdx.factor.catalog import canonical_factor_name, describe_factor
        from easy_tdx.factor.configuration import configured_selection
        from easy_tdx.factor.horizons import normalize_horizons

        configured_selection(self.factors, self.factor_parameters)
        if needs_benchmark(self.factors) != (self.benchmark is not None):
            raise ValueError("基准依赖因子须选择基准指数；其他因子不接受未使用的基准配置")
        if self.composition is not None:
            self.composition = CompositionConfig.model_validate(
                normalize_composition(self.composition.model_dump(), self.factors)
            )
        if self.horizons is not None:
            self.horizons = normalize_horizons(self.horizon, self.horizons)

        if len({(s.market, s.code) for s in self.stocks}) != len(self.stocks):
            raise ValueError("检验标的不能重复")
        if len({canonical_factor_name(n) for n in self.factors}) != len(self.factors):
            raise ValueError("检验因子不能重复")
        for name in self.factors:
            definition = describe_factor(get_factor(name))
            from easy_tdx.factor.catalog import availability_reason

            reason = availability_reason(definition, self.adjust, evaluation=True)
            if reason:
                raise ValueError(reason)
        return self


class PortfolioRiskRequest(BaseModel):
    stocks: list[StockIdentifier] = Field(..., min_length=2, max_length=20)
    method: Literal["equal", "factor_weighted", "risk_parity", "mean_variance"] = "risk_parity"
    category: Literal["DAY"] = "DAY"
    count: int = Field(default=300, ge=60, le=800)
    adjust: Literal["NONE", "QFQ", "HFQ"] = "QFQ"

    @model_validator(mode="after")
    def unique_assets(self) -> PortfolioRiskRequest:
        if len({s.code for s in self.stocks}) != len(self.stocks):
            raise ValueError("组合标的代码不得重复；当前风险模型按股票代码标识资产")
        return self


def _json_safe_frame(df: pd.DataFrame) -> pd.DataFrame:
    clean = df.replace([np.inf, -np.inf], np.nan)
    return clean.astype(object).where(pd.notna(clean), None)


@router.get("/research/factors")
async def factor_list() -> list[dict[str, Any]]:
    """列出全部内置量化因子及其输入字段。"""
    from easy_tdx.factor import list_factors

    return list_factors()


async def _benchmark_source(
    symbol: str | None, category: str, count: int, client: Any, mac_client: Any
) -> pd.DataFrame | str | None:
    if symbol is None:
        return None
    from easy_tdx.web.factor_benchmark import load_factor_benchmark

    try:
        return await load_factor_benchmark(symbol, category, count, client, mac_client)
    except Exception as exc:
        return f"基准指数取数失败：{getattr(exc, 'detail', None) or str(exc) or type(exc).__name__}"


def _attach_benchmark_source(
    frame: pd.DataFrame, symbol: str | None, source: pd.DataFrame | str | None
) -> pd.DataFrame:
    if symbol is None:
        return frame
    from easy_tdx.factor.benchmark import FIELDS, attach_benchmark

    reason = source if isinstance(source, str) else "基准指数缺少原始行情"
    if isinstance(source, pd.DataFrame):
        try:
            return attach_benchmark(frame, source, symbol)
        except ValueError as exc:
            reason = f"基准指数对齐失败：{exc}"
    result = frame.copy(deep=True)
    result.attrs["factor_input_errors"] = {
        **frame.attrs.get("factor_input_errors", {}),
        **dict.fromkeys(FIELDS, reason),
    }
    return result


async def _factor_fields(
    df: pd.DataFrame,
    factors: list[str],
    client: Any,
    mac_client: Any,
    market: str,
    code: str,
    category: str,
    count: int,
    adjust: str,
) -> pd.DataFrame:
    """Internal data qualification, not another user query or a chart mutation."""
    from easy_tdx.factor import get_factor
    from easy_tdx.factor.data import qualify_factor_fields

    needed = set().union(*(set(get_factor(name).inputs) for name in factors))
    qualified_fields = {"volume", "vwap"}.intersection(needed)
    if any(name.startswith("gtja191_") and "amount" in get_factor(name).inputs for name in factors):
        qualified_fields.add("amount")
    if not qualified_fields:
        return df
    out = df.copy()
    out.attrs.pop("factor_data_contract", None)
    out.attrs.pop("factor_input_errors", None)
    # Never trust a preexisting canonical field from an unqualified feed.
    out = out.drop(columns=["volume", "vwap"], errors="ignore")
    errors: dict[str, str] = {}
    if "vwap" in needed and adjust != "NONE":
        errors["vwap"] = "VWAP 当前仅支持不复权；缺少复权成交价变换依据"
        if not {"volume", "amount"}.intersection(qualified_fields):
            out.attrs["factor_input_errors"] = errors
            return out
    try:
        raw = (
            out
            if adjust == "NONE"
            else closed_frame(
                await fetch_adjusted_bars(
                    client, mac_client, market, code, category, 0, count, "NONE"
                )
            )
        )
        out = qualify_factor_fields(out, raw, need_vwap="vwap" in needed and adjust == "NONE")
        out.attrs["factor_data_contract"]["instrument"] = f"{market}:{code}"
    except Exception as exc:
        # Field-specific failures must not suppress unrelated price factors.
        reason = getattr(exc, "detail", None) or str(exc) or type(exc).__name__
        errors.update(
            {field: f"量额核验失败：{reason}" for field in qualified_fields if field not in errors}
        )
    if errors:
        out.attrs["factor_input_errors"] = errors
    return out


@router.post("/research/factors/evaluate", response_model=DictResponse)
async def factor_evaluate(
    req: FactorEvaluationRequest,
    client: Any = Depends(get_client),
    mac_client: Any | None = Depends(get_mac_client_optional),
) -> DictResponse:
    from easy_tdx.web.resource_admission import run_compute

    frames = await _evaluation_frames(req, client, mac_client)
    return DictResponse(data=await run_compute(lambda: evaluation_result(req, frames)))


@router.post("/research/factors/evaluate/async", response_model=TaskSubmitResponse, status_code=202)
async def factor_evaluate_async(
    req: FactorEvaluationRequest,
    response: Response,
    client: Any = Depends(get_client),
    mac_client: Any | None = Depends(get_mac_client_optional),
    user: UserRecord = Depends(get_task_user),
) -> TaskSubmitResponse:
    """Freeze all qualified inputs before enqueueing; workers never fetch live data."""
    from easy_tdx.web.task_payload import TaskInput

    response.headers["Cache-Control"] = "no-store"
    snapshot = req.model_copy(deep=True)
    frames = await _evaluation_frames(snapshot, client, mac_client)
    return await _submit_research(
        user,
        f"因子检验 · {len(snapshot.stocks)} 只标的 · {len(snapshot.factors)} 个因子",
        lambda version: TaskInput(
            "factor_evaluation",
            version,
            snapshot.model_dump(),
            tuple(frames.values()),
            {"symbols": list(frames)},
        ),
        lambda: evaluation_result(snapshot, frames),
        retain_input=True,
    )


async def _evaluation_frames(
    req: FactorEvaluationRequest, client: Any, mac_client: Any
) -> dict[str, pd.DataFrame]:
    frames = {}
    benchmark = await _benchmark_source(req.benchmark, "DAY", req.count, client, mac_client)
    for stock in req.stocks:
        df = closed_frame(
            await fetch_adjusted_bars(
                client, mac_client, stock.market, stock.code, "DAY", 0, req.count, req.adjust
            )
        )
        symbol = f"{stock.market}:{stock.code}"
        if df.empty or len(df) < 60:
            raise ValueError(f"{symbol} 已收盘日线不足 60 根；未静默跳过该标的")
        metadata = df.attrs.get("snapshot_metadata")
        if not isinstance(metadata, dict) or metadata.get("actual_adjust") != req.adjust:
            raise ValueError(f"{symbol} 复权来源不一致或缺失；已停止检验")
        quality = metadata.get("quality", {})
        if isinstance(quality, dict) and quality.get("status") == "error":
            raise ValueError(f"{symbol} 行情质量检查失败；已停止检验")
        df = await _factor_fields(
            df,
            req.factors,
            client,
            mac_client,
            stock.market,
            stock.code,
            "DAY",
            req.count,
            req.adjust,
        )
        frames[symbol] = _attach_benchmark_source(df, req.benchmark, benchmark)
    return frames


def evaluation_result(
    req: FactorEvaluationRequest, frames: dict[str, pd.DataFrame]
) -> dict[str, Any]:
    """Identical synchronous/queued result contract including full archive inputs."""
    from easy_tdx.computation import computation_checkpoint
    from easy_tdx.factor.research import cross_section_report
    from easy_tdx.factor.snapshot import freeze_input
    from easy_tdx.progress import report_progress

    computation_checkpoint()
    expected = [f"{stock.market}:{stock.code}" for stock in req.stocks]
    if list(frames) != expected:
        raise ValueError("因子冻结行情与完整股票池顺序不匹配")
    validate_benchmark_pool(frames.values(), req.benchmark)
    result = cross_section_report(
        frames,
        req.factors,
        req.horizon,
        req.groups,
        req.preprocess,
        factor_parameters=req.factor_parameters,
        horizons=req.horizons,
        composition=req.composition.model_dump() if req.composition else None,
        validation=req.validation.model_dump() if req.validation else None,
    )
    result["settings"].update(
        category="DAY",
        count=req.count,
        adjust=req.adjust,
        stocks=[stock.model_dump() for stock in req.stocks],
        benchmark=req.benchmark,
    )
    computation_checkpoint()
    snapshots = []
    report_progress("archive", 0, len(frames))
    for position, (symbol, frame) in enumerate(frames.items(), 1):
        snapshots.append(freeze_input(symbol, frame))
        report_progress("archive", position, len(frames))
    result["input_snapshots"] = snapshots
    result["provenance"] = [
        {
            "code": symbol,
            "count": len(df),
            "metadata": df.attrs.get("snapshot_metadata"),
            "factor_data_contract": df.attrs.get("factor_data_contract"),
            "factor_input_errors": df.attrs.get("factor_input_errors", {}),
        }
        for symbol, df in frames.items()
    ]
    result["adjust"] = req.adjust
    computation_checkpoint()
    return result


@router.post("/research/factors/compute", response_model=DictResponse)
async def factor_compute(
    req: FactorComputeRequest,
    client: Any = Depends(get_client),
    mac_client: Any | None = Depends(get_mac_client_optional),
) -> DictResponse:
    """获取单股行情并计算一个或多个内置因子。"""
    from easy_tdx.web.resource_admission import run_compute

    df = await _series_frame(req, client, mac_client)
    if df.empty:
        return DictResponse(
            data={
                "rows": [],
                "count": 0,
                "errors": {},
                "metadata": df.attrs.get("snapshot_metadata"),
            }
        )
    return await run_compute(lambda: _factor_result(req, df))


async def _series_frame(req: FactorComputeRequest, client: Any, mac_client: Any) -> pd.DataFrame:
    df = await fetch_adjusted_bars(
        client, mac_client, req.market, req.code, req.category, 0, req.count, req.adjust
    )
    df = closed_frame(df)
    if "date" in df.columns and "datetime" not in df.columns:
        df = df.rename(columns={"date": "datetime"})
    if df.empty:
        return df

    df = await _factor_fields(
        df,
        req.factors,
        client,
        mac_client,
        req.market,
        req.code,
        req.category,
        req.count,
        req.adjust,
    )

    benchmark = await _benchmark_source(req.benchmark, req.category, req.count, client, mac_client)
    return _attach_benchmark_source(df, req.benchmark, benchmark)


def validate_series_task_frame(req: FactorComputeRequest, df: pd.DataFrame) -> None:
    if df.empty or len(df) > req.count:
        raise ValueError("因子序列没有已收盘行情或行情超出请求范围；未截断或补造")
    metadata = df.attrs.get("snapshot_metadata")
    if not isinstance(metadata, dict) or metadata.get("actual_adjust") != req.adjust:
        raise ValueError("因子序列复权来源不一致或缺失；已停止计算")
    quality = metadata.get("quality", {})
    if isinstance(quality, dict) and quality.get("status") == "error":
        raise ValueError("因子序列行情质量检查失败；已停止计算")


@router.post("/research/factors/compute/async", response_model=TaskSubmitResponse, status_code=202)
async def factor_compute_async(
    req: FactorComputeRequest,
    response: Response,
    client: Any = Depends(get_client),
    mac_client: Any | None = Depends(get_mac_client_optional),
    user: UserRecord = Depends(get_task_user),
) -> TaskSubmitResponse:
    from easy_tdx.web.task_payload import TaskInput

    response.headers["Cache-Control"] = "no-store"
    snapshot = req.model_copy(deep=True)
    df = await _series_frame(snapshot, client, mac_client)
    validate_series_task_frame(snapshot, df)
    return await _submit_research(
        user,
        f"因子序列 · {snapshot.market}:{snapshot.code} · {snapshot.category}"
        f" · {len(snapshot.factors)} 个因子",
        lambda version: TaskInput(
            "factor_series",
            version,
            snapshot.model_dump(),
            (df,),
            {"symbol": f"{snapshot.market}:{snapshot.code}", "category": snapshot.category},
        ),
        lambda: _factor_result(snapshot, df).data,
        retain_input=True,
    )


def _factor_result(req: FactorComputeRequest, df: pd.DataFrame) -> DictResponse:
    from easy_tdx.factor import FactorEngine
    from easy_tdx.factor.snapshot import freeze_input
    from easy_tdx.progress import report_progress

    validate_frozen_benchmark(df, req.benchmark)
    engine = FactorEngine()
    result = df.copy()
    errors: dict[str, str] = {}
    computed: list[str] = []
    definitions: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    report_progress("factor_series", 0, len(req.factors))
    for position, factor_name in enumerate(req.factors, 1):
        try:
            from easy_tdx.factor import get_factor
            from easy_tdx.factor.catalog import availability_reason, describe_factor
            from easy_tdx.factor.configuration import configure_factor

            parameters = req.factor_parameters.get(factor_name)
            definition = describe_factor(get_factor(factor_name), parameters)
            definitions[factor_name] = definition
            reason = availability_reason(definition, req.adjust)
            if reason:
                raise ValueError(reason)
            input_errors = df.attrs.get("factor_input_errors", {})
            for field in definition["inputs"]:
                if field in input_errors:
                    raise ValueError(input_errors[field])
            result = engine.compute_single(result, [configure_factor(factor_name, parameters)])
            computed.append(factor_name)
            finite = np.isfinite(pd.to_numeric(result[factor_name], errors="coerce"))
            valid_count = int(finite.sum())
            diagnostics[factor_name] = {
                "valid_count": valid_count,
                "missing_count": len(df) - valid_count,
                "coverage": valid_count / len(df) if len(df) else 0,
                "status": "available" if valid_count else "no_valid_values",
                "reason": ""
                if valid_count
                else (
                    "需要足够基准下跌样本且样本内指数收益方差非零；"
                    "缺失后重新积累，未自动补数或缩小窗口"
                )
                if definition.get("family") == "benchmark_filtered_beta"
                else "预热不足、缺失或零分母导致没有有效值；未以 0 替代",
            }
        except Exception as exc:
            errors[factor_name] = str(exc)
        # Outside per-factor diagnostics: loss of task accounting must fail the task.
        report_progress("factor_series", position, len(req.factors), factor_name)

    requested_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
        *computed,
    ]
    keep = [column for column in requested_columns if column in result.columns]
    output = _json_safe_frame(result[keep].reset_index(drop=True))
    settings = req.model_dump()
    fingerprint = hashlib.sha256(pd.util.hash_pandas_object(df, index=True).values.tobytes())
    fingerprint.update(
        json.dumps({"settings": settings, "definitions": definitions}, sort_keys=True).encode()
    )
    fingerprint.update(json.dumps(df.attrs.get("factor_data_contract"), sort_keys=True).encode())
    if "factor_benchmark" in df.attrs:
        fingerprint.update(json.dumps(df.attrs["factor_benchmark"], sort_keys=True).encode())
    report_progress("archive", 0, 1)
    snapshots = [freeze_input(f"{req.market}:{req.code}", df)]
    report_progress("archive", 1, 1)
    return DictResponse(
        data={
            "rows": DataFrameResponse.from_dataframe(output).data,
            "count": len(output),
            "computed": computed,
            "errors": errors,
            "metadata": df.attrs.get("snapshot_metadata"),
            "factor_data_contract": df.attrs.get("factor_data_contract"),
            "factor_input_errors": df.attrs.get("factor_input_errors", {}),
            "input_count": len(df),
            "settings": settings,
            "factor_definitions": definitions,
            "diagnostics": diagnostics,
            "input_fingerprint": fingerprint.hexdigest(),
            "output_truncated": False,
            "input_snapshots": snapshots,
        }
    )


@router.post("/research/portfolio-risk", response_model=DictResponse)
async def portfolio_risk(
    req: PortfolioRiskRequest,
    client: Any = Depends(get_client),
    mac_client: Any | None = Depends(get_mac_client_optional),
) -> DictResponse:
    """基于在线日线计算组合权重、相关性、年化波动与风险贡献。"""
    from easy_tdx.web.resource_admission import run_compute

    series: list[pd.Series] = []
    asset_rows: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    for stock in req.stocks:
        df = await fetch_adjusted_bars(
            client,
            mac_client,
            stock.market,
            stock.code,
            req.category,
            0,
            req.count,
            req.adjust,
        )
        df = closed_frame(df)
        if df.empty or "close" not in df.columns:
            raise ValueError(f"{stock.market}:{stock.code} 无有效收盘行情；未跳过该资产")
        provenance.append(
            {
                "market": stock.market,
                "code": stock.code,
                "count": len(df),
                "metadata": df.attrs.get("snapshot_metadata"),
            }
        )
        time_col = "datetime" if "datetime" in df.columns else "date"
        close = pd.Series(
            pd.to_numeric(df["close"], errors="coerce").to_numpy(),
            index=pd.to_datetime(df[time_col]),
            name=stock.code,
        ).sort_index()
        series.append(close)

    return await run_compute(lambda: _risk_result(req, series, asset_rows, provenance))


def _risk_result(
    req: PortfolioRiskRequest,
    series: list[pd.Series],
    asset_rows: list[dict[str, Any]],
    provenance: list[dict[str, Any]],
) -> DictResponse:
    from easy_tdx.portfolio import RiskModel, get_optimizer

    # Align price observations before computing returns, so missing observations
    # never become zero returns or mismatched holding-period returns across assets.
    prices = pd.concat(series, axis=1).sort_index()
    raw_returns = prices.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    from datetime import timedelta

    from easy_tdx.web.trading_calendar import missing_sessions

    # If every asset lacks a date, outer alignment alone cannot reveal the gap.
    # A multi-session return must not be annualized as one daily observation.
    calendar_gap_returns = []
    for previous, current in zip(prices.index, prices.index[1:]):
        if missing_sessions(
            previous.date() + timedelta(days=1), current.date() - timedelta(days=1), set()
        ):
            raw_returns.loc[current] = np.nan
            calendar_gap_returns.append(str(current))
    returns = raw_returns.dropna(how="any")
    if len(returns) < 2:
        raise ValueError("共同有效日收益不足 2 条，不能估计组合风险；未用零收益填充缺失行情")
    for stock in req.stocks:
        ret = returns[stock.code]
        annual_return = float(ret.mean(skipna=True) * 252)
        volatility = float(ret.std(skipna=True) * np.sqrt(252))
        asset_rows.append(
            {
                "code": stock.code,
                "market": stock.market,
                "annual_return": annual_return,
                "volatility": volatility,
                "score": annual_return / volatility if volatility > 0 else 0.0,
            }
        )

    scores = pd.DataFrame(asset_rows)
    weights = get_optimizer(req.method).optimize(scores, n_stocks=len(scores))
    risk_model = RiskModel()
    covariance = risk_model.estimate_covariance(returns)
    risk = risk_model.portfolio_risk(weights, covariance)

    codes = [c for c in weights if c in covariance.columns]
    if codes:
        w = np.array([weights[c] for c in codes])
        cov = covariance.loc[codes, codes].to_numpy()
        contribution = np.abs(w * (cov @ w))
        contribution = contribution / contribution.sum() if contribution.sum() > 0 else contribution
        contribution_map = {code: float(contribution[i]) for i, code in enumerate(codes)}
    else:
        contribution_map = {}
    for row in asset_rows:
        row["weight"] = float(weights.get(str(row["code"]), 0.0))
        row["risk_contribution"] = contribution_map.get(str(row["code"]), 0.0)

    correlation = returns.corr().round(4)
    correlation.index.name = "code"
    correlation_rows = DataFrameResponse.from_dataframe(correlation.reset_index()).data
    return DictResponse(
        data={
            "weights": weights,
            "risk": risk,
            "assets": asset_rows,
            "correlation": correlation_rows,
            "observations": len(returns),
            "method": req.method,
            "provenance": provenance,
            "alignment": {
                "policy": "common_observed_daily_returns_no_fill",
                "excluded_observations": len(raw_returns) - len(returns),
                "start": str(returns.index[0]),
                "end": str(returns.index[-1]),
                "annualization": 252,
                "calendar_gap_returns": calendar_gap_returns,
                "note": "仅使用共同有效日收益，不补零；年化按 252 个交易日，非未来收益预测。",
            },
        }
    )
