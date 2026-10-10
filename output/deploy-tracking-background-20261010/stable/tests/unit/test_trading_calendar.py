"""Exchange notices and historical boundaries, independent of vendor quotations."""

from datetime import date, datetime

import pandas as pd
import pytest

from easy_tdx.backtest.performance_sampling import sample_equity
from easy_tdx.web.bar_snapshot import annotate_snapshot, period_end, quality_report
from easy_tdx.web.trading_calendar import HOLIDAY_RANGES, VERSION, is_session, last_session


@pytest.mark.parametrize(
    "closed,reopen",
    [
        ("2020-01-01", "2020-01-02"),
        ("2020-01-31", "2020-02-03"),
        ("2020-04-06", "2020-04-07"),
        ("2020-05-05", "2020-05-06"),
        ("2020-06-26", "2020-06-29"),
        ("2020-10-08", "2020-10-09"),
        ("2021-01-01", "2021-01-04"),
        ("2021-02-17", "2021-02-18"),
        ("2021-04-05", "2021-04-06"),
        ("2021-05-05", "2021-05-06"),
        ("2021-06-14", "2021-06-15"),
        ("2021-09-21", "2021-09-22"),
        ("2021-10-07", "2021-10-08"),
        ("2022-01-03", "2022-01-04"),
        ("2022-02-04", "2022-02-07"),
        ("2022-04-05", "2022-04-06"),
        ("2022-05-04", "2022-05-05"),
        ("2022-06-03", "2022-06-06"),
        ("2022-09-12", "2022-09-13"),
        ("2022-10-07", "2022-10-10"),
        ("2023-01-02", "2023-01-03"),
        ("2023-01-27", "2023-01-30"),
        ("2023-04-05", "2023-04-06"),
        ("2023-05-03", "2023-05-04"),
        ("2023-06-23", "2023-06-26"),
        ("2023-10-06", "2023-10-09"),
    ],
)
def test_notice_closures_and_first_sessions(closed, reopen):
    assert is_session(date.fromisoformat(closed)) is False
    assert is_session(date.fromisoformat(reopen)) is True


@pytest.mark.parametrize("year", range(2020, 2027))
def test_all_weekends_stay_closed_even_when_civil_makeup_workdays(year):
    for day in pd.date_range(f"{year}-01-01", f"{year}-12-31"):
        if day.weekday() >= 5:
            assert is_session(day.date()) is False


@pytest.mark.parametrize(
    "label,category,end",
    [
        ("2020-01-01", "MONTH", "2020-01-23"),
        ("2020-01-20", "WEEK", "2020-01-23"),
        ("2021-09-01", "MONTH", "2021-09-30"),
        ("2022-04-01", "MONTH", "2022-04-29"),
        ("2023-09-25", "WEEK", "2023-09-28"),
        ("2023-07-01", "SEASON", "2023-09-28"),
        ("2023-01-01", "YEAR", "2023-12-29"),
    ],
)
def test_period_completion_uses_actual_last_session(label, category, end):
    assert period_end(datetime.fromisoformat(label), category) == datetime.fromisoformat(
        end + " 15:00:00"
    )


def test_2020_emergency_closure_preserves_week_and_true_observation_count():
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2020-01-17", "2020-01-23", "2020-02-07"]),
            "total": [100, 102, 101],
        }
    )
    values, basis = sample_equity(frame, category="WEEK", category_source="explicit")
    assert list(values) == [100, 102, 102, 101]
    assert basis["unavailable_reason"] is None
    assert basis["observed_sample_count"] == 3
    assert basis["calendar_version"] == VERSION
    assert basis["closed_period_samples"][0]["datetime"] == "2020-02-02T15:00:00"
    assert len(frame) == 3


@pytest.mark.parametrize("day", ["2019-12-31", "2019-12-29", "2027-01-04"])
def test_unknown_years_never_assume_known_calendar(day):
    parsed = date.fromisoformat(day)
    assert is_session(parsed) is None
    assert last_session(parsed, parsed) is None


def test_quality_reports_unknown_interior_year_not_only_endpoints(monkeypatch):
    monkeypatch.delitem(HOLIDAY_RANGES, 2021)
    rows = [
        dict(datetime=day, open=1, high=1, low=1, close=1) for day in ["2020-12-31", "2022-01-04"]
    ]
    assert quality_report(rows, "DAY")["calendar_unverified_years"] == [2021]


def test_snapshot_exposes_calendar_coverage_and_keeps_unknown_limit():
    data = [dict(datetime="2020-01-01", open=1, high=1, low=1, close=1)]
    snapshot = annotate_snapshot(
        data,
        "MONTH",
        source="test",
        requested_adjust="NONE",
        actual_adjust="NONE",
        now=datetime(2020, 1, 23, 15),
    )
    assert snapshot["data"][0]["is_closed"] is True
    meta = snapshot["metadata"]
    assert meta["calendar_covered_years"] == list(range(2020, 2027))
    assert "2020" in meta["completion_note"] and "未覆盖" in meta["completion_note"]
    assert meta["calendar_version"] == VERSION
