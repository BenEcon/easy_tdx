"""UI settings preserve strict prices and remain bound to each frozen request."""

from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import ValidationError

from easy_tdx.chanlun import ChanlunAnalyser
from easy_tdx.chanlun.structure_filter import filter_base_outputs
from easy_tdx.web.routers.chanlun_replay import (
    ComparisonReplayRequest,
    ReplayRequest,
    _research_input,
    replay_comparison,
    replay_snapshot,
)
from easy_tdx.web.structure_settings import StructureSettings


def bars():
    return [
        dict(
            datetime=t,
            open=20 + i % 7,
            close=20 + i % 7,
            high=21 + i % 7,
            low=19 + i % 7,
            vol=100,
            amount=1000,
        )
        for i, t in enumerate(pd.date_range("2026-01-01", periods=36))
    ]


@pytest.mark.parametrize(
    "value",
    [
        dict(bi_type="invalid"),
        dict(zs_min_lines=2),
        dict(zs_min_lines=7),
        dict(zs_min_lines=3.5),
        dict(zs_min_lines=True),
        dict(zs_min_lines="4"),
        dict(fx_strict=False),
        dict(macd_fast=5),
    ],
)
def test_reject_weakened_or_invalid_settings(value):
    with pytest.raises(ValidationError):
        StructureSettings(**value)


@pytest.mark.parametrize("rule", ["new", "old", "simple"])
def test_replay_and_comparison_keep_config_and_prefix(rule):
    settings = StructureSettings(bi_type=rule, zs_min_lines=4)
    req = ReplayRequest(code="SH600000", bars=bars(), visible_count=24, structure_settings=settings)
    actual = replay_snapshot(req)
    config = settings.engine_config()
    assert config.fx_strict is True and config.macd_fast == 12
    expected = filter_base_outputs(
        ChanlunAnalyser(code=req.code, frequency="day", config=config).process_klines(
            pd.DataFrame(bars()[:24])
        ),
        4,
    ).to_dict()
    assert {
        k: v
        for k, v in actual.items()
        if k not in ("replay", "structure_settings", "structure_settings_scope")
    } == expected
    pair = replay_comparison(
        ComparisonReplayRequest(stock=req, industry=dict(code="board", bars=bars()))
    )
    assert pair["industry"]["result"]["structure_settings"] == settings.model_dump()
    assert pair["stock"] == actual
    assert pair["industry"]["result"]["replay"]["visible_count"] == 24
    changed = req.model_copy(
        update={"structure_settings": StructureSettings(bi_type=rule, zs_min_lines=5)}
    )
    assert _research_input(req)[0] != _research_input(changed)[0]


def test_filter_uses_confirmed_signal_evidence_not_later_centre_size():
    def signal(n):
        return SimpleNamespace(
            source="confirmed_segment_base_v1", evidence={"centre_segment_count": n}
        )

    weak, strong = signal(3), signal(5)
    macd = SimpleNamespace(evidence={"area": 2})
    original_segments = [object()]
    result = SimpleNamespace(
        structural_centres=[SimpleNamespace(member_segments=list(range(5)))],
        structural_signals=[weak, strong],
        mmds=[weak, strong],
        bcs=[weak, strong, macd],
        xds=original_segments,
    )
    filter_base_outputs(result, 4)
    assert len(result.structural_centres) == 1
    assert result.mmds == [strong] and result.structural_signals == [strong]
    assert result.bcs == [strong, macd]
    assert result.xds is original_segments


@pytest.mark.parametrize("kind", ["chart", "study"])
def test_saved_settings_recompute_with_original_bars(kind):
    from copy import deepcopy

    from fastapi import Response

    from easy_tdx.web.routers.chanlun_archive import ArchiveRecomputeRequest, recompute_archive
    from tests.unit.test_archive_recompute import request

    raw = request(kind)
    raw[kind]["structure_settings"] = dict(bi_type="old", zs_min_lines=5)
    original = deepcopy(raw)
    output = recompute_archive(ArchiveRecomputeRequest.model_validate(raw), Response())
    if kind == "chart":
        assert output["result"]["structure_settings"] == raw[kind]["structure_settings"]
        assert output["scope"] == "structure_and_macd_saved_settings"
    else:
        assert (
            output["result"]["parameters"]["structure_settings"] == raw[kind]["structure_settings"]
        )
    assert raw == original


@pytest.mark.parametrize("rule", ["new", "old", "simple"])
def test_every_ui_rule_preserves_strict_price_gate(rule):
    from easy_tdx.chanlun.bi import _can_form_bi
    from easy_tdx.chanlun.types import FXType
    from tests.unit.test_chanlun_rules_regression import fx

    config = StructureSettings(bi_type=rule).engine_config()
    assert not _can_form_bi(fx(1, 20, FXType.DI), fx(8, 19, FXType.DING), config)
    assert not _can_form_bi(fx(1, 20, FXType.DI), fx(8, 21, FXType.DING), config)
