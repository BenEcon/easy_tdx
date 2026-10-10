"""Shared structural signals must not be backdated by downstream consumers."""

from types import SimpleNamespace

import pandas as pd
import pytest

from easy_tdx.chanlun.analyser import ChanlunAnalyser
from easy_tdx.factor.builtin.chanlun import ChanlunBiDir, ChanlunMMD


def signal(kind, known, strength="held_first_extreme"):
    return SimpleNamespace(
        mmd_type=SimpleNamespace(value=kind),
        confirmed_index=known,
        source="confirmed_segment_base_v1",
        bi=SimpleNamespace(),
        zs=None,
        evidence={"centre_segment_count": 3, "strength": strength},
    )


def test_mmd_factor_uses_confirmation_and_preserves_coincident_priority(monkeypatch):
    result = SimpleNamespace(
        mmds=[signal("3buy", 8), signal("2buy", 8), signal("1sell", 10), signal("1buy", None)]
    )
    monkeypatch.setattr(ChanlunAnalyser, "process_klines", lambda *_: result)
    values = ChanlunMMD().compute(pd.DataFrame(index=range(12)))
    assert values.tolist() == [0] * 8 + [3, 0, -1, 0]


def test_direction_factor_does_not_fill_unconfirmed_history(monkeypatch):
    result = SimpleNamespace(
        bis=[
            SimpleNamespace(direction="up", confirmed_index=4),
            SimpleNamespace(direction="down", confirmed_index=8),
            SimpleNamespace(direction="up", confirmed_index=None),
        ]
    )
    monkeypatch.setattr(ChanlunAnalyser, "process_klines", lambda *_: result)
    values = ChanlunBiDir().compute(pd.DataFrame(index=range(12)))
    assert values.tolist() == [0] * 4 + [1] * 4 + [-1] * 4


@pytest.mark.parametrize("allow_weak", [False, True])
def test_strategy_weak_second_filter_and_confirmation(monkeypatch, allow_weak):
    from easy_tdx.backtest.strategies.builtin import _chanlun_mmd_signal_arrays

    result = SimpleNamespace(mmds=[signal("2buy", 10, "weak_new_extreme")])
    monkeypatch.setattr(ChanlunAnalyser, "process_klines", lambda *_: result)
    values = [10.0] * 12
    buy, sell = _chanlun_mmd_signal_arrays(
        values,
        values,
        values,
        values,
        values,
        bi_rule="新笔",
        zs_min_lines=3,
        entry="全部买点",
        exit_="全部卖点",
        allow_weak_second=allow_weak,
    )
    assert buy.nonzero()[0].tolist() == ([10] if allow_weak else [])
    assert not sell.any()
