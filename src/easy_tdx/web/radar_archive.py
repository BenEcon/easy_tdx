"""Shape and internal consistency, NOT authentication of uploaded scan provenance.

Independent from the task store: imports and reads must survive task deletion
and code upgrades without executing a strategy or fetching replacement prices.
"""

from __future__ import annotations

import re
from typing import Any

from easy_tdx.web.research_archive import ArchiveError, _archive_time, _bars, _dump
from easy_tdx.web.signal_scan import normalize_symbol


def validate_radar_archive(source: Any, target: dict[str, Any]) -> None:
    try:
        _validate(source, target)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, OverflowError) as exc:
        raise ArchiveError(422, "原扫描来源、信号、行情或任务引用不一致；未保存混合来源") from exc


def _validate(source: Any, target: dict[str, Any]) -> None:
    if not isinstance(source, dict) or source.get("contract") != "radar-archive-v1":
        raise ValueError("source")
    review, receipt = source["review"], source["receipt"]
    if not isinstance(review, dict) or not isinstance(receipt, dict):
        raise ValueError("source objects")
    reference, row, metadata = review["evidence"], receipt["row"], receipt["metadata"]
    if not all(isinstance(v, dict) for v in (reference, row, metadata)):
        raise ValueError("source objects")
    if (
        receipt["contract"] != "radar-evidence-v1"
        or not isinstance(reference["taskId"], str)
        or not re.fullmatch(r"[a-f0-9]{32}", reference["taskId"])
        or type(reference["rowIndex"]) is not int
        or not 0 <= reference["rowIndex"] <= 999999
        or receipt["task_id"] != reference["taskId"]
        or type(receipt["row_index"]) is not int
        or receipt["row_index"] != reference["rowIndex"]
        or type(receipt["window_bars"]) is not int
        or not 1 <= receipt["window_bars"] <= 30
        or receipt["storage"] not in ("memory", "persistent")
        or any(
            not isinstance(receipt[k], str) or not 1 <= len(receipt[k]) <= 256
            for k in ("execution_version", "current_execution_version")
        )
    ):
        raise ValueError("task reference")
    code, adjust, category = review["symbol"], review["adjust"], review["category"]
    if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code):
        raise ValueError("symbol")
    symbol = normalize_symbol(code)
    if (
        target.get("kind") != "stock"
        or target.get("code") != code
        or target.get("market") != symbol.split(":")[0]
        or row["symbol"] != symbol
        or row["strategy"] != review["strategy"]
        or not isinstance(review["strategy"], str)
        or not re.fullmatch(r"[\w.-]{1,100}", review["strategy"], re.ASCII)
        or not isinstance(review["name"], str)
        or row.get("error")
        or row["category"] != category
        or category not in ("DAY", "WEEK", "MONTH", "MIN_1", "MIN_5", "MIN_15", "MIN_30", "MIN_60")
        or adjust not in ("QFQ", "HFQ", "NONE")
        or not isinstance(review["params"], dict)
        or any(type(v) not in (int, float, bool, str) for v in review["params"].values())
        or _dump(row["params"]) != _dump(review["params"])
        or not isinstance(review["fingerprint"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", review["fingerprint"])
    ):
        raise ValueError("identity")
    cutoff = _archive_time(review["asOf"])
    if (
        review["asOf"] != cutoff.strftime("%Y-%m-%d %H:%M:%S")
        or not isinstance(review["signalDate"], str)
        or (
            review["signalDate"]
            and review["signalDate"]
            != _archive_time(review["signalDate"]).strftime("%Y-%m-%d %H:%M:%S")
        )
    ):
        raise ValueError("review timestamps")
    for md in (metadata, row["metadata"]):
        if (
            not isinstance(md, dict)
            or md["category"] != category
            or md["actual_adjust"] != adjust
            or md["requested_adjust"] != adjust
            or md["data_fingerprint"] != review["fingerprint"]
            or _archive_time(md["last_closed_at"]) != cutoff
            or (isinstance(md.get("quality"), dict) and md["quality"].get("status") == "error")
        ):
            raise ValueError("metadata")
    bars = receipt["bars"]
    _bars(bars, metadata)
    if not 2 <= len(bars) <= 800:
        raise ValueError("bars")
    for bar in bars:
        if (
            bar.get("is_closed") is not True
            or not _archive_time(bar["datetime"]) <= _archive_time(bar["period_end"]) <= cutoff
            or bar["low"] <= 0
            or any(type(bar[k]) not in (int, float) or bar[k] < 0 for k in ("vol", "amount"))
        ):
            raise ValueError("closed bars")
    if _archive_time(bars[-1]["period_end"]) != cutoff:
        raise ValueError("cutoff")
    recent = row["recent_signals"]
    window = {
        _archive_time(b["datetime"]).replace(second=0, microsecond=0)
        for b in bars[-receipt["window_bars"] :]
    }
    if not isinstance(recent, list):
        raise ValueError("signals")
    for event in recent:
        if (
            not isinstance(event, dict)
            or event["direction"] not in ("BUY", "SELL")
            or _archive_time(event["date"]).replace(second=0, microsecond=0) not in window
        ):
            raise ValueError("signals outside window")
    latest = recent[-1] if recent else None
    if (
        row["latest_signal"] != (latest["direction"] if latest else None)
        or (latest and _archive_time(row["signal_date"]) != _archive_time(latest["date"]))
        or (not latest and row["signal_date"] is not None)
        or row["position"] not in ("holding", "flat")
        or type(row["last_close"]) not in (int, float)
        or row["last_close"] != bars[-1]["close"]
        or _archive_time(row["last_bar_date"]).replace(second=0, microsecond=0)
        != _archive_time(bars[-1]["datetime"]).replace(second=0, microsecond=0)
    ):
        raise ValueError("summary")
    direction = {"买入": "BUY", "卖出": "SELL", "无指定信号": None}[review["signal"]]
    if review["signalDate"] and not any(
        _archive_time(event["date"]) == _archive_time(review["signalDate"])
        and (direction is None or event["direction"] == direction)
        for event in recent
    ):
        raise ValueError("selected signal")
