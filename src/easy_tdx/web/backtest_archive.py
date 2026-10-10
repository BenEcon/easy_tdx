"""Validate immutable single-strategy results; never execute uploaded strategy data."""

from __future__ import annotations

import math
import re
from typing import Any

from easy_tdx.web.research_archive import _PERIODS, ArchiveError, _archive_time, _bars

_METRICS = (
    "total_return annual_return max_drawdown max_dd_duration sharpe sortino calmar "
    "total_trades win_trades lose_trades rejected_trades win_rate profit_factor "
    "avg_win avg_loss max_win max_loss avg_holding_days volatility"
).split()


def _number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _require(condition: Any) -> None:
    if not condition:
        raise ValueError("invalid backtest archive")


def validate_backtest_archive(payload: dict[str, Any]) -> None:
    try:
        _require(payload["format"] == "backtest-research-v1")
        _require(isinstance(payload["title"], str) and 0 < len(payload["title"].strip()) <= 500)
        _archive_time(payload["savedAt"], clock=True)
        r, result, metadata = payload["request"], payload["result"], payload["metadata"]
        _require(all(isinstance(v, dict) for v in (r, result, metadata)))
        _require(isinstance(r["symbol"], str) and re.fullmatch(r"(SH|SZ|BJ):[0-9]{6}", r["symbol"]))
        _require(isinstance(r["category"], str) and r["category"] in _PERIODS)
        _require(isinstance(r["adjust"], str) and r["adjust"] in {"NONE", "QFQ", "HFQ"})
        _require(isinstance(r["strategy"], str) and r["strategy"].strip())
        _require(isinstance(r["params"], dict))
        _require(all(isinstance(v, str | bool) or _number(v) for v in r["params"].values()))
        _require(_number(r["cash"]) and r["cash"] > 0)
        _require(
            all(
                _number(r[k]) and r[k] >= 0
                for k in ("commission", "min_commission", "stamp_tax", "slippage")
            )
        )
        _require(isinstance(r["execution"], str) and r["execution"] in {"next_open", "next_close"})
        _require(_archive_time(r["start_date"]) <= _archive_time(r["end_date"]))
        _bars(r["ohlcv"], metadata)
        _require(metadata["category"] == r["category"])
        _require(metadata["actual_adjust"] == metadata["requested_adjust"] == r["adjust"])
        _require(isinstance(result["performance"], dict) and isinstance(result["config"], dict))
        _require(
            all(
                k in result["performance"]
                and (result["performance"][k] is None or _number(result["performance"][k]))
                for k in _METRICS
            )
        )
        _require(isinstance(result["positions"], list))
        _require(all(isinstance(row, dict) for row in result["positions"]))
        _require(isinstance(result["equity_curve"], list) and result["equity_curve"])
        _require(isinstance(result["trades"], list))
        times = {_archive_time(b["datetime"], clock=True) for b in r["ohlcv"]}
        prior = None
        for row in result["equity_curve"]:
            _require(isinstance(row, dict))
            stamp = _archive_time(row["datetime"], clock=True)
            _require(stamp in times and (prior is None or stamp > prior))
            _require(
                all(
                    _number(row[k])
                    for k in ("cash", "position_value", "total", "drawdown", "drawdown_pct")
                )
            )
            prior = stamp
        for row in result["trades"]:
            _require(isinstance(row, dict))
            _require(_archive_time(row["datetime"], clock=True) in times)
            _require(isinstance(row["direction"], str) and row["direction"] in {"BUY", "SELL"})
            _require(type(row["rejected"]) is bool)
            _require(
                all(_number(row[k]) for k in ("size", "price", "commission", "slippage", "pnl"))
            )
        if "radarSource" in payload:
            from easy_tdx.web.radar_archive import validate_radar_archive

            market, code = r["symbol"].split(":")
            validate_radar_archive(
                payload["radarSource"], {"kind": "stock", "market": market, "code": code}
            )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ArchiveError(422, "回测原档参数、行情、成交或净值记录不完整／不一致") from exc
