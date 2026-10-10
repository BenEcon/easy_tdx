"""Deterministic prefix analysis of a supplied, bounded market-data snapshot."""

from __future__ import annotations

from datetime import datetime
from time import monotonic
from typing import Any, Literal

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from easy_tdx.chanlun import ChanlunAnalyser
from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.exhaustive_recursion import GRAMMAR, exhaustive_leaf
from easy_tdx.chanlun.ownership_history import OwnershipHistoryMode
from easy_tdx.chanlun.release_review import POLICIES, review_changes, review_state
from easy_tdx.chanlun.released_recursion import released_movement_snapshot
from easy_tdx.chanlun.structure_filter import filter_base_outputs
from easy_tdx.web.research_cursor import decode_cursor, encode_cursor, fingerprint
from easy_tdx.web.resource_admission import BoundedComputeRoute
from easy_tdx.web.structure_settings import StructureSettings

router = APIRouter(tags=["chanlun"], route_class=BoundedComputeRoute)


class ReplayBar(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    vol: float = Field(default=0, ge=0)
    amount: float = Field(default=0, ge=0)
    is_closed: bool = True

    @model_validator(mode="after")
    def valid_candle(self) -> ReplayBar:
        if self.datetime.tzinfo is not None:
            raise ValueError("请使用交易所本地时间，不附带时区")
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("K 线高低价必须覆盖开盘和收盘价")
        return self


class ReplaySeries(BaseModel):
    code: str = Field(min_length=1, max_length=24)
    bars: list[ReplayBar] = Field(min_length=1, max_length=800)

    @model_validator(mode="after")
    def chronological(self) -> ReplaySeries:
        if any(a.datetime >= b.datetime for a, b in zip(self.bars, self.bars[1:])):
            raise ValueError("K 线时间必须严格递增，不可重复")
        return self


class ReplayRequest(ReplaySeries):
    structure_settings: StructureSettings = Field(default_factory=StructureSettings)
    category: Literal[
        "DAY", "WEEK", "MONTH", "YEAR", "MIN_1", "MIN_5", "MIN_15", "MIN_30", "MIN_60", "MIN_120"
    ] = "DAY"
    visible_count: int = Field(ge=1, le=800)

    @model_validator(mode="after")
    def valid_snapshot(self) -> ReplayRequest:
        if self.visible_count > len(self.bars):
            raise ValueError("回放位置超过快照长度")
        return self


@router.post("/chanlun/replay")
def replay_snapshot(
    req: ReplayRequest, ownership_history: OwnershipHistoryMode = "full"
) -> dict[str, Any]:
    # Deliberately slice before all inclusion, structure and MACD calculations.
    frame = pd.DataFrame([bar.model_dump() for bar in req.bars[: req.visible_count]])
    frequency = (
        req.category.removeprefix("MIN_") + "min"
        if req.category.startswith("MIN_")
        else req.category.lower()
    )
    analysed = ChanlunAnalyser(
        code=req.code, frequency=frequency, config=req.structure_settings.engine_config()
    ).process_klines(frame)
    result = filter_base_outputs(analysed, req.structure_settings.zs_min_lines).to_dict(
        ownership_history=ownership_history
    )
    result["structure_settings"] = req.structure_settings.model_dump()
    result["structure_settings_scope"] = (
        "strict_price_preserved_base_output_filter_not_recursive_seed"
    )
    result["replay"] = {
        "visible_count": req.visible_count,
        "total_count": len(req.bars),
        "as_of": req.bars[req.visible_count - 1].datetime.isoformat(sep=" "),
        "mode": "snapshot_prefix",
        "historical_data_vintage": False,
    }
    return result


class ComparisonReplayRequest(BaseModel):
    stock: ReplayRequest
    industry: ReplaySeries


class ReleaseHistoryRequest(ReplayRequest):
    start_count: int = Field(ge=1, le=800)

    @model_validator(mode="after")
    def bounded_batch(self) -> ReleaseHistoryRequest:
        if not self.start_count <= self.visible_count < self.start_count + 40:
            raise ValueError("每批最多重建 40 个连续原始行情前缀")
        return self


class ExhaustiveRequest(ReplayRequest):
    cursor: str | None = Field(default=None, max_length=524288)
    page_size: int = Field(default=2, ge=1, le=8)


class CandidateAuditRequest(ReplayRequest):
    solution_token: str | None = Field(default=None, max_length=524288)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)


def _research_input(req: ReplayRequest) -> tuple[str, ChanlunResult]:
    raw = [bar.model_dump(mode="json") for bar in req.bars[: req.visible_count]]
    identity = fingerprint(
        {
            "grammar": GRAMMAR,
            "code": req.code,
            "category": req.category,
            "bars": raw,
            "structure_settings": req.structure_settings.model_dump(),
        }
    )
    frame = pd.DataFrame(raw)
    frequency = (
        req.category.removeprefix("MIN_") + "min"
        if req.category.startswith("MIN_")
        else req.category.lower()
    )
    result = ChanlunAnalyser(
        code=req.code, frequency=frequency, config=req.structure_settings.engine_config()
    ).process_klines(frame)
    return identity, result


@router.post("/chanlun/replay/exhaustive")
def replay_exhaustive(req: ExhaustiveRequest) -> dict[str, Any]:
    identity, result = _research_input(req)
    try:
        cursor: dict[str, Any] = (
            decode_cursor(req.cursor, identity, "search")
            if req.cursor
            else {"path": [], "emitted": 0}
        )
        path: list[int] | None = cursor["path"]
        emitted: int = cursor["emitted"]
        records = []
        deadline = monotonic() + 2
        for _ in range(req.page_size):
            # None is terminal, never an empty path to restart from the root.
            assert path is not None
            leaf = exhaustive_leaf(result.xds, result.klines, result.macd, path)
            solution = {"fingerprint": identity, "kind": "solution", "path": leaf["path"]}
            records.append(
                {
                    "id": fingerprint(solution),
                    "ordinal": emitted + 1,
                    "solution_token": encode_cursor(solution),
                    "snapshot": leaf["snapshot"],
                }
            )
            emitted += 1
            path = leaf["next_path"]
            if path is None or monotonic() >= deadline:
                break
        next_cursor = (
            None
            if path is None
            else encode_cursor(
                {"fingerprint": identity, "kind": "search", "path": path, "emitted": emitted}
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "scope": GRAMMAR,
        "fingerprint": identity,
        "complete": path is None,
        "next_cursor": next_cursor,
        "emitted": emitted,
        "results": records,
        "eligible_for_trading": False,
        "theory_equivalence_claim": False,
        "historical_data_vintage": False,
        "coverage": "all_disjoint_subsets_on_fixed_base_including_unresolved",
    }


@router.post("/chanlun/replay/candidate-audit")
def replay_candidate_audit(req: CandidateAuditRequest) -> dict[str, Any]:
    identity, result = _research_input(req)
    try:
        token = (
            decode_cursor(req.solution_token, identity, "solution") if req.solution_token else None
        )
        if token:
            audit = exhaustive_leaf(
                result.xds, result.klines, result.macd, token["path"], trace=True
            )["audit"]
            assert audit is not None  # trace=True always supplies a fresh audit mapping.
        else:
            audit = {}
            released_movement_snapshot(result.xds, result.klines, result.macd, _audit=audit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    attempts = audit.pop("attempts")
    summary: dict[str, int] = {}
    for row in attempts:
        key = row["reason"] or "candidate_formed"
        summary[key] = summary.get(key, 0) + 1
    return {
        "scope": "actual_candidate_gate_trace_v1",
        "fingerprint": identity,
        "interpretation": "solution" if token else "default",
        "total_attempts": len(attempts),
        "offset": req.offset,
        "next_offset": (req.offset + req.limit if req.offset + req.limit < len(attempts) else None),
        "attempts": attempts[req.offset : req.offset + req.limit],
        "summary": summary,
        "input": audit,
        "eligible_for_trading": False,
        "as_of_index": req.visible_count - 1,
    }


def _release_prefix(req: ReplayRequest, count: int) -> dict[str, Any]:
    if count == 0:
        return released_movement_snapshot([], [], {})
    frame = pd.DataFrame([bar.model_dump() for bar in req.bars[:count]])
    frequency = (
        req.category.removeprefix("MIN_") + "min"
        if req.category.startswith("MIN_")
        else req.category.lower()
    )
    result = ChanlunAnalyser(
        code=req.code, frequency=frequency, config=req.structure_settings.engine_config()
    ).process_klines(frame)
    return released_movement_snapshot(result.xds, result.klines, result.macd)


@router.post("/chanlun/replay/release-history")
def replay_release_history(req: ReleaseHistoryRequest) -> dict[str, Any]:
    # Rebuild the boundary prefix as well, so independently requested batches
    # have the same changes as a single sequential traversal. No session cache.
    previous = review_state(_release_prefix(req, req.start_count - 1))
    events = []
    for count in range(req.start_count, req.visible_count + 1):
        current = review_state(_release_prefix(req, count))
        events.extend(
            review_changes(
                previous, current, count - 1, req.bars[count - 1].datetime.isoformat(sep=" ")
            )
        )
        previous = current
    return {
        "scope": "raw_prefix_release_history_v1",
        "start_count": req.start_count,
        "end_count": req.visible_count,
        "events": events,
        "historical_data_vintage": False,
        "eligible_for_trading": False,
    }


@router.post("/chanlun/replay/release-comparison")
def replay_release_comparison(req: ReplayRequest) -> dict[str, Any]:
    frame = pd.DataFrame([bar.model_dump() for bar in req.bars[: req.visible_count]])
    frequency = (
        req.category.removeprefix("MIN_") + "min"
        if req.category.startswith("MIN_")
        else req.category.lower()
    )
    result = ChanlunAnalyser(
        code=req.code, frequency=frequency, config=req.structure_settings.engine_config()
    ).process_klines(frame)
    variants = [
        {
            "policy": policy,
            "snapshot": released_movement_snapshot(
                result.xds, result.klines, result.macd, selection_policy=policy
            ),
        }
        for policy in POLICIES
    ]
    return {
        "scope": "bounded_selection_comparison_v1",
        "exhaustive": False,
        "default_policy": "earliest",
        "eligible_for_trading": False,
        "historical_data_vintage": False,
        "variants": variants,
    }


@router.post("/chanlun/replay/compare")
def replay_comparison(
    req: ComparisonReplayRequest, ownership_history: OwnershipHistoryMode = "full"
) -> dict[str, Any]:
    """Use the stock cutoff's timestamp, never its row count, for the industry."""
    cutoff = req.stock.bars[req.stock.visible_count - 1].datetime
    visible = [bar for bar in req.industry.bars if bar.datetime <= cutoff]
    industry = None
    if visible:
        result = replay_snapshot(
            ReplayRequest(
                code=req.industry.code,
                category=req.stock.category,
                bars=req.industry.bars,
                visible_count=len(visible),
                structure_settings=req.stock.structure_settings,
            ),
            ownership_history=ownership_history,
        )
        industry = {"bars": [bar.model_dump(mode="json") for bar in visible], "result": result}
    return {
        "stock": replay_snapshot(req.stock, ownership_history=ownership_history),
        "industry": industry,
        "alignment": {
            "as_of": cutoff.isoformat(sep=" "),
            "industry_as_of": visible[-1].datetime.isoformat(sep=" ") if visible else None,
            "status": "unavailable"
            if not visible
            else ("aligned" if visible[-1].datetime == cutoff else "earlier"),
        },
    }
