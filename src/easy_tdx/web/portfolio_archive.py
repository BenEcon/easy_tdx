"""Validate saved portfolio receipts without fetching, repairing or recomputing."""

from typing import Any

from easy_tdx.web.backtest_archive import _METRICS, _number, _require, validate_backtest_archive
from easy_tdx.web.research_archive import ArchiveError, _archive_time


def validate_portfolio_archive(payload: dict[str, Any]) -> None:
    try:
        _require(payload["format"] == "portfolio-research-v1")
        _require(isinstance(payload["title"], str) and 0 < len(payload["title"].strip()) <= 500)
        _archive_time(payload["savedAt"], clock=True)
        receipt = payload["receipt"]
        _require(isinstance(receipt, dict) and receipt["contract"] == "portfolio-evidence-v1")
        _require(receipt["kind"] in ("portfolio", "multi_strategy"))
        for key in ("task_id", "execution_version", "current_execution_version"):
            _require(isinstance(receipt[key], str) and receipt[key])
        _require(receipt["storage"] in ("memory", "persistent"))
        request, result, members = receipt["request"], receipt["result"], receipt["members"]
        _require(isinstance(request, dict) and isinstance(result, dict))
        _require(isinstance(members, list) and 1 <= len(members) <= 20)
        _require(_number(request["cash"]) and request["cash"] > 0)
        evidence = result["data_provenance"]
        _require(isinstance(evidence, dict) and evidence["request"] == request)
        datasets = evidence["datasets"]
        _require(isinstance(datasets, list) and len(datasets) == len(members))
        slots = request["stocks"] if receipt["kind"] == "portfolio" else request["items"]
        _require(isinstance(slots, list) and len(slots) == len(members))
        individuals, allocations = result["individual_results"], result["equity_allocation"]
        _require(isinstance(individuals, dict) and isinstance(allocations, dict))
        keys = set()
        for index, member in enumerate(members):
            _require(
                isinstance(member, dict)
                and type(member["index"]) is int
                and member["index"] == index
            )
            key, symbol, category = member["key"], member["symbol"], member["category"]
            _require(isinstance(key, str) and key and key not in keys)
            item = request if receipt["kind"] == "portfolio" else slots[index]
            _require(isinstance(item, dict))
            for date_key in ("start_date", "end_date"):
                if item.get(date_key) is not None:
                    _archive_time(item[date_key])
            _require(symbol == (slots[index] if receipt["kind"] == "portfolio" else item["symbol"]))
            _require(category == item["category"])
            _require(
                key == symbol.replace(":", "")
                if receipt["kind"] == "portfolio"
                else key.endswith("@" + symbol)
            )
            if receipt["kind"] == "multi_strategy" and item.get("strategy_label"):
                _require(key == item["strategy_label"] + "@" + symbol)
            dataset = datasets[index]
            _require(
                isinstance(dataset, dict)
                and dataset["label"] == key
                and dataset["symbol"] == symbol
            )
            _require(
                dataset["metadata"] == member["metadata"]
                and dataset["bar_count"] == len(member["bars"])
            )
            _require(_number(allocations[key]) and allocations[key] > 0)
            keys.add(key)
            # Reuse single-result structural checks; this temporary validation view
            # is never persisted or presented as the original submitted request.
            validate_backtest_archive(
                {
                    "format": "backtest-research-v1",
                    "title": key,
                    "savedAt": payload["savedAt"],
                    "metadata": member["metadata"],
                    "result": individuals[key],
                    "request": {
                        **request,
                        **item,
                        "symbol": symbol,
                        "category": category,
                        "cash": request["cash"] * allocations[key],
                        "ohlcv": member["bars"],
                        "start_date": item.get("start_date") or member["bars"][0]["datetime"][:10],
                        "end_date": item.get("end_date") or member["bars"][-1]["datetime"][:10],
                    },
                }
            )
        _require(keys == set(individuals) == set(allocations))
        _require(abs(sum(allocations.values()) - 1) < 1e-12)
        perf = result["total_performance"]
        _require(
            isinstance(perf, dict)
            and all(k in perf and (perf[k] is None or _number(perf[k])) for k in _METRICS)
        )
        _require(
            _number(perf["total_stocks"])
            and perf["total_stocks"] == len(members)
            and _number(perf["total_cash"])
            and perf["total_cash"] == request["cash"]
        )
        curve = result["combined_equity"]
        _require(isinstance(curve, list) and curve)
        prior = None
        for row in curve:
            _require(isinstance(row, dict))
            stamp = _archive_time(row["datetime"], clock=True)
            _require(prior is None or stamp > prior)
            _require(all(_number(row[k]) for k in ("total", "drawdown", "drawdown_pct")))
            prior = stamp
    except (KeyError, TypeError, ValueError, OverflowError, IndexError, AttributeError) as exc:
        raise ArchiveError(422, "组合原档的成员、参数、来源或完整结果不一致") from exc
