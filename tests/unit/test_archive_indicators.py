"""Saved chart parameters and every registered indicator share the real numerical engine."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from fastapi import Response
from pydantic import ValidationError

from easy_tdx.indicator import compute_indicators, list_indicators
from easy_tdx.web.archive_indicators import (
    SavedChartIndicators,
    SavedIndicator,
    recompute_chart_indicators,
)
from easy_tdx.web.routers.chanlun_archive import ArchiveRecomputeRequest, recompute_archive
from tests.unit.test_archive_recompute import request


@pytest.mark.parametrize("spec", list_indicators(), ids=lambda row: row["name"])
def test_every_registered_indicator_matches_real_engine_and_preserves_input(spec):
    bars = request()["chart"]["bars"]
    original = deepcopy(bars)
    item = {"type": spec["name"].lower(), "params": spec["default_params"]}
    settings = SavedChartIndicators(averages=[], indicators=[item])
    actual = recompute_chart_indicators(bars, settings)["indicators"][0]
    expected = compute_indicators(
        pd.DataFrame(bars).drop(columns="datetime"), [spec["name"]], keep_ohlcv=False
    )
    expected = expected.replace([np.inf, -np.inf], np.nan)
    assert actual["rows"] == expected.astype(object).where(pd.notna(expected), None).to_dict(
        "records"
    )
    assert actual["params"] == item["params"]
    assert len(actual["rows"]) == len(bars)
    assert bars == original


def test_complete_chart_version_digest_custom_and_duplicate_instances():
    raw = request()
    raw["chart_indicators"] = {
        "averages": [{"period": 5, "enabled": True}, {"period": 8000, "enabled": False}],
        "indicators": [
            {"type": "volume", "params": {}},
            {"type": "none", "params": {}},
            {"type": "rsi", "params": {"N": 6}},
            {"type": "rsi", "params": {"N": 12}},
            {"type": "macd", "params": {"SHORT": 12, "LONG": 26, "M": 9}},
        ],
    }
    original = deepcopy(raw)
    value = recompute_archive(ArchiveRecomputeRequest.model_validate(raw), Response())
    assert raw == original
    assert value["contract"] == "archive-recompute-v2"
    assert value["scope"] == "structure_macd_and_saved_chart_indicators"
    data = value["indicator_data"]
    assert data["averages"][0]["values"][:4] == [None] * 4
    assert (
        data["averages"][0]["values"][4]
        == sum(row["close"] for row in raw["chart"]["bars"][:5]) / 5
    )
    assert data["averages"][1]["values"] == [None] * 40
    assert data["indicators"][0]["rows"][0]["MAVOL5"] is None
    assert (
        data["indicators"][0]["rows"][4]["MAVOL5"]
        == sum(row["vol"] for row in raw["chart"]["bars"][:5]) / 5
    )
    assert data["indicators"][1]["rows"] == [{}] * 40
    assert data["indicators"][2]["rows"] != data["indicators"][3]["rows"]
    assert [row["MACD_DIF"] for row in data["indicators"][4]["rows"]] == value["result"]["macd"][
        "dif"
    ]
    raw["chart_indicators"]["averages"][0]["period"] = 6
    other = recompute_archive(ArchiveRecomputeRequest.model_validate(raw), Response())
    assert other["input_digest"] != value["input_digest"]


@pytest.mark.parametrize(
    "item",
    [
        {"type": "unknown", "params": {}},
        {"type": "rsi", "params": {}},
        {"type": "rsi", "params": {"N": True}},
        {"type": "rsi", "params": {"N": "5"}},
        {"type": "rsi", "params": {"N": 1.5}},
        {"type": "rsi", "params": {"N": 0}},
        {"type": "rsi", "params": {"N": 8001}},
        {"type": "rsi", "params": {"N": float("nan")}},
        {"type": "rsi", "params": {"N": 5, "UNKNOWN": 3}},
        {"type": "macd", "params": {"SHORT": 26, "LONG": 12, "M": 9}},
        {"type": "sar", "params": {"AF_STEP": 0.3, "AF_MAX": 0.2}},
        {"type": "volume", "params": {"N": 3}},
    ],
)
def test_reject_unavailable_or_invalid_original_parameters(item):
    with pytest.raises(ValidationError):
        SavedIndicator.model_validate(item)


def test_bounded_full_settings_and_no_study_indicator_injection():
    for value in [
        {"averages": [{"period": 5, "enabled": True}] * 2, "indicators": []},
        {"averages": [], "indicators": [{"type": "volume", "params": {}}] * 9},
        {"averages": [{"period": 5, "enabled": "true"}], "indicators": []},
    ]:
        with pytest.raises(ValidationError):
            SavedChartIndicators.model_validate(value)
    raw = request("study")
    raw["chart_indicators"] = {"averages": [], "indicators": []}
    with pytest.raises(ValidationError):
        ArchiveRecomputeRequest.model_validate(raw)
