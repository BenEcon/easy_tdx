"""Owner-only completed portfolio inputs; never fetch or execute replacement data."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import HTTPException

from easy_tdx.web import task_service
from easy_tdx.web.backtest_schemas import MultiStrategyBacktestRequest, PortfolioBacktestRequest
from easy_tdx.web.research_archive import _bars
from easy_tdx.web.research_provenance import frame_evidence
from easy_tdx.web.schemas import DataFrameResponse
from easy_tdx.web.task_payload import TaskInput
from easy_tdx.web.task_runner import get_runner
from easy_tdx.web.task_version import execution_version


def portfolio_evidence(value: TaskInput, result: dict[str, Any]) -> dict[str, Any]:
    if value.kind == "portfolio":
        portfolio = PortfolioBacktestRequest.model_validate(value.request)
        request = portfolio.model_dump()
        identities = [(symbol, portfolio.category) for symbol in portfolio.stocks]
        expected_keys: list[str] | None = [symbol.replace(":", "") for symbol in portfolio.stocks]
    elif value.kind == "multi_strategy":
        multi = MultiStrategyBacktestRequest.model_validate(value.request)
        request = multi.model_dump()
        identities = [(item.symbol, item.category) for item in multi.items]
        expected_keys = None  # Saved labels, never today's strategy registry.
    else:
        raise ValueError("该任务不是组合或多策略回测")
    evidence = result.get("data_provenance")
    if not isinstance(evidence, dict) or evidence.get("request") != request:
        raise ValueError("原组合结果与冻结请求不一致，不能拼接存档")
    datasets = evidence.get("datasets")
    individuals, allocation = result.get("individual_results"), result.get("equity_allocation")
    if (
        not isinstance(datasets, list)
        or len(datasets) != len(identities)
        or len(value.frames) != len(identities)
        or not isinstance(individuals, dict)
        or not isinstance(allocation, dict)
    ):
        raise ValueError("原组合成员、行情或资金分配没有完整对应")
    members = []
    keys: set[str] = set()
    for index, ((symbol, category), frame, dataset) in enumerate(
        zip(identities, value.frames, datasets, strict=True)
    ):
        if not isinstance(dataset, dict):
            raise ValueError("原组合行情来源不完整")
        key, metadata = dataset.get("label"), dataset.get("metadata")
        if (
            not isinstance(key, str)
            or not key
            or key in keys
            or dataset.get("symbol") != symbol
            or dataset.get("bar_count") != len(frame)
            or not isinstance(metadata, dict)
            or metadata.get("category") != category
            or (expected_keys is not None and key != expected_keys[index])
        ):
            raise ValueError("原组合成员身份、顺序或标签不一致／重复")
        if value.kind == "multi_strategy":
            label = request["items"][index].get("strategy_label")
            if not key.endswith("@" + symbol) or (label and key != f"{label}@{symbol}"):
                raise ValueError("原策略槽位标签与请求不一致")
        measured = frame_evidence(
            frame, category=category, adjust=request["adjust"], symbol=symbol, label=key
        )["metadata"]
        if (
            metadata.get("data_fingerprint") != measured.get("data_fingerprint")
            or metadata.get("last_closed_at") != measured.get("last_closed_at")
            or metadata.get("requested_adjust") != request["adjust"]
            or metadata.get("actual_adjust") != request["adjust"]
            or measured.get("actual_adjust") != request["adjust"]
        ):
            raise ValueError("原组合行情指纹、收盘时间或复权证据不一致")
        bars = DataFrameResponse.from_dataframe(frame).data
        _bars(bars, metadata)
        keys.add(key)
        members.append(
            {
                "index": index,
                "key": key,
                "symbol": symbol,
                "category": category,
                "bars": bars,
                "metadata": metadata,
            }
        )
    if keys != set(individuals) or keys != set(allocation):
        raise ValueError("原组合结果遗漏成员或出现额外成员，不能封存为完整结果")
    return {
        "contract": "portfolio-evidence-v1",
        "kind": value.kind,
        "execution_version": value.execution_version,
        "request": request,
        "members": members,
        "result": result,
    }


def read_portfolio_evidence(owner: str, task_id: str) -> dict[str, Any]:
    persistent = task_service.task_backend() == "durable"
    try:
        value, result = (
            task_service.get_durable_store() if persistent else get_runner()
        ).completed_input(owner, task_id)
        receipt = {
            **portfolio_evidence(value, result),
            "task_id": task_id,
            "storage": "persistent" if persistent else "memory",
            "current_execution_version": execution_version(),
        }
        if (
            len(json.dumps(receipt, ensure_ascii=False, allow_nan=False).encode())
            > 25 * 1024 * 1024
        ):
            raise HTTPException(
                413,
                "完整组合原档超过 25MiB，未截断成员或行情",
                headers={"Cache-Control": "no-store"},
            )
        return receipt
    except KeyError as exc:
        raise HTTPException(
            404,
            "原任务不存在、已清理或不属于当前账户；未改取最新行情",
            headers={"Cache-Control": "no-store"},
        ) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, str(exc), headers={"Cache-Control": "no-store"}) from exc
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(
            503, "原组合存储暂不可用；未改取最新行情", headers={"Cache-Control": "no-store"}
        ) from exc
