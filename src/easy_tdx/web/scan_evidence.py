"""Read-only, owner-scoped original radar inputs. Never fetch replacement prices."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from typing import Any

from fastapi import HTTPException

from easy_tdx.web import task_service
from easy_tdx.web.backtest_schemas import SignalScanRequest
from easy_tdx.web.research_provenance import frame_evidence
from easy_tdx.web.schemas import DataFrameResponse
from easy_tdx.web.signal_scan import SCAN_BARS
from easy_tdx.web.task_dispatch import _scan_data
from easy_tdx.web.task_payload import TaskInput
from easy_tdx.web.task_runner import get_runner
from easy_tdx.web.task_version import execution_version


def evidence_row(value: TaskInput, result: dict[str, Any], index: int) -> dict[str, Any]:
    if value.kind != "signal_scan":
        raise ValueError("该任务不是信号扫描")
    request = SignalScanRequest.model_validate(value.request)
    bars, targets = _scan_data(value)
    rows = result.get("rows")
    if not isinstance(rows, list) or len(rows) != len(targets):
        raise ValueError("原扫描结果与冻结输入不完整对应")
    if type(index) is not int or not 0 <= index < len(targets):
        raise ValueError("扫描条目不存在")
    target, row = targets[index], rows[index]
    if not isinstance(row, dict) or any(
        row.get(k) != v for k, v in asdict(target).items() if k != "error"
    ):
        raise ValueError("原扫描条目身份或参数不一致")
    frame = bars.get((target.symbol, target.category))
    if target.error or row.get("error") or frame is None or not 2 <= len(frame) <= SCAN_BARS:
        raise ValueError("该条目没有成功扫描的原行情")
    metadata = frame.attrs.get("snapshot_metadata")
    required = {
        "category",
        "source",
        "requested_adjust",
        "actual_adjust",
        "observed_at",
        "data_fingerprint",
        "last_closed_at",
    }
    if (
        not isinstance(metadata, dict)
        or not required <= metadata.keys()
        or row.get("metadata") != metadata
    ):
        raise ValueError("原行情缺少一致的来源证据")
    measured = frame_evidence(
        frame,
        category=target.category,
        adjust=request.adjust,
        symbol=target.symbol,
        label="原雷达行情",
    )["metadata"]
    if (
        metadata.get("category") != target.category
        or metadata.get("actual_adjust") != request.adjust
        or metadata.get("requested_adjust") != request.adjust
        or measured["data_fingerprint"] != metadata.get("data_fingerprint")
        or measured["last_closed_at"] != metadata.get("last_closed_at")
        or measured["quality"]["status"] == "error"
        or "is_closed" not in frame
        or any(flag is not True for flag in frame["is_closed"].tolist())
    ):
        raise ValueError("原行情指纹、收盘状态或复权证据不一致")
    return {
        "contract": "radar-evidence-v1",
        "row_index": index,
        "row": row,
        "window_bars": request.window_bars,
        "execution_version": value.execution_version,
        "bars": DataFrameResponse.from_dataframe(frame).data,
        "metadata": metadata,
    }


def read_scan_evidence(owner: str, task_id: str, index: int) -> dict[str, Any]:
    persistent = task_service.task_backend() == "durable"
    try:
        value, result = (
            task_service.get_durable_store() if persistent else get_runner()
        ).completed_input(owner, task_id)
        evidence = evidence_row(value, result, index)
    except KeyError as exc:
        raise HTTPException(
            404,
            "原扫描任务不存在、已被清理或不属于当前账户；未改取最新行情",
            headers={"Cache-Control": "no-store"},
        ) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, str(exc), headers={"Cache-Control": "no-store"}) from exc
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(
            503, "原扫描存储暂不可用；未改取最新行情", headers={"Cache-Control": "no-store"}
        ) from exc
    return {
        **evidence,
        "task_id": task_id,
        "storage": "persistent" if persistent else "memory",
        "current_execution_version": execution_version(),
    }
