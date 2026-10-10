"""Result-bound data evidence; client uploads never become verified feed provenance."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pandas as pd

from easy_tdx.web.bar_snapshot import annotate_snapshot
from easy_tdx.web.schemas import DataFrameResponse


def frame_evidence(
    frame: pd.DataFrame, *, category: str, adjust: str, symbol: str | None, label: str
) -> dict[str, Any]:
    """Describe the exact computation input, not the last page or current form values."""
    records = DataFrameResponse.from_dataframe(frame).data
    metadata = deepcopy(frame.attrs.get("snapshot_metadata"))
    if not metadata:
        metadata = {
            "source": "UNVERIFIED_INPUT",
            "requested_adjust": adjust,
            "actual_adjust": "UNKNOWN",
            "category": category,
            "bar_time": "end",
        }
        metadata["source_note"] = "调用方提供的数据；来源、复权和采集时点未独立核验"
    measured = annotate_snapshot(
        records,
        metadata["category"],
        source=metadata["source"],
        requested_adjust=metadata["requested_adjust"],
        actual_adjust=metadata["actual_adjust"],
        bar_time=metadata.get("bar_time", "end"),
        now=pd.Timestamp(metadata["observed_at"]).to_pydatetime()
        if metadata.get("observed_at")
        else None,
    )["metadata"]
    fingerprint = measured["data_fingerprint"]
    if metadata.get("data_fingerprint") != fingerprint:
        metadata.setdefault("source_fingerprint", metadata.get("data_fingerprint"))
    if metadata.get("quality") and metadata["quality"] != measured["quality"]:
        metadata["collection_quality"] = metadata["quality"]
    metadata.update(measured)
    metadata.update(
        data_fingerprint=fingerprint,
        input_count=len(frame),
        range_start=str(records[0].get("datetime", records[0].get("date"))) if records else None,
        range_end=str(records[-1].get("datetime", records[-1].get("date"))) if records else None,
    )
    return {"label": label, "symbol": symbol, "bar_count": len(frame), "metadata": metadata}


def result_evidence(request: Any, datasets: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep parameters with results; mutable page controls are not historical evidence."""
    return {
        "contract_version": "research-input-v1",
        "request": request.model_dump(exclude={"ohlcv"}),
        "datasets": datasets,
        "historical_data_vintage": False,
    }
