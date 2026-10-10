"""Regression from the real browser: snapshot annotations are not numeric factors."""

import numpy as np
import pandas as pd

from easy_tdx.backtest.strategy import StrategyDataProxy
from easy_tdx.web.backtest_schemas import BacktestRequest
from easy_tdx.web.routers.backtest import _ohlcv_to_df, _run_backtest


def sample():
    dates = pd.bdate_range("2026-08-03", periods=40)
    price = 10 + np.sin(np.arange(40) / 3)
    return pd.DataFrame(
        dict(
            datetime=dates,
            open=price,
            close=price,
            high=price + 1,
            low=price - 1,
            vol=10000,
            amount=price * 10000,
        )
    )


def test_snapshot_annotations_do_not_enter_numeric_strategy_arrays():
    frame = sample()
    frame["period_end"] = frame.datetime.dt.strftime("%Y-%m-%d 15:00:00")
    frame["is_closed"] = True
    frame["custom_factor"] = 1.25
    frame.attrs["snapshot_metadata"] = {"fingerprint": "test-only"}
    proxy = StrategyDataProxy(frame)
    assert "period_end" not in proxy._arrays
    assert "is_closed" not in proxy._arrays
    assert np.all(proxy._arrays["custom_factor"] == 1.25)
    assert "period_end" in frame  # Do not destroy provenance on the source frame.
    assert frame.attrs["snapshot_metadata"]["fingerprint"] == "test-only"


def test_browser_shaped_inline_request_matches_plain_backtest():
    records = (
        sample().assign(datetime=lambda df: df.datetime.dt.strftime("%Y-%m-%d")).to_dict("records")
    )
    request = BacktestRequest(strategy="ma_cross", ohlcv=records)
    plain = _run_backtest(_ohlcv_to_df(records), request)
    annotated = [
        dict(row, period_end=f"{row['datetime']} 15:00:00", is_closed=True) for row in records
    ]
    result = _run_backtest(_ohlcv_to_df(annotated), request)
    assert result.pop("data_provenance")["datasets"][0]["bar_count"] == len(records)
    plain.pop("data_provenance")
    assert result == plain


def test_server_frame_annotations_match_plain_backtest():
    frame = sample()
    request = BacktestRequest(strategy="ma_cross", symbol="SZ:000001")
    plain = _run_backtest(frame, request)
    frame["period_end"] = frame.datetime.dt.strftime("%Y-%m-%d 15:00:00")
    frame["is_closed"] = True
    result = _run_backtest(frame, request)
    assert result.pop("data_provenance")["datasets"][0]["bar_count"] == len(frame)
    plain.pop("data_provenance")
    # Availability is now preserved for downstream combination. It is not a
    # numeric strategy factor and must not change any original result field.
    for row, source in zip(result["equity_curve"], frame.to_dict("records"), strict=True):
        assert row.pop("period_end") == source["period_end"]
        assert row.pop("is_closed") is True
    assert result == plain
