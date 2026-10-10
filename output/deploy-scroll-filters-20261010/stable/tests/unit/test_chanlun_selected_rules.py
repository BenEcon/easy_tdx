"""0928 selections: strict pen prices, contextual inclusion, display-only tail."""

from datetime import datetime, timedelta

import pytest

from easy_tdx.chanlun.bi import _can_form_bi
from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.kline_merge import merge_klines
from easy_tdx.chanlun.types import BI, FX, CLKline, Direction, FXType, Kline
from easy_tdx.chanlun.xd import _endpoint, find_unfinished_xd, find_xds


def pens(prices):
    points = []
    for i, value in enumerate(prices):
        kind = FXType.DI if (prices[1] > prices[0]) == (i % 2 == 0) else FXType.DING
        k = CLKline(
            i * 4,
            datetime(2026, 1, 1) + timedelta(days=i),
            value,
            value,
            value + (kind == FXType.DI),
            value - (kind == FXType.DING),
            0,
            index=i * 4,
        )
        points.append(FX(kind, k, [k, k, k], value))
    return [
        BI(
            a,
            b,
            Direction.UP if b.val > a.val else Direction.DOWN,
            index=i,
            high=max(a.val, b.val),
            low=min(a.val, b.val),
            confirmed_index=i * 4 + 8,
        )
        for i, (a, b) in enumerate(zip(points, points[1:]))
    ]


@pytest.mark.parametrize("sign", [1, -1])
@pytest.mark.parametrize(
    "prices,end",
    [
        ([0, 10, 5, 12, 3, 8, 1], 12),
        ([0, 10, 5, 12, 3, 8, 4, 9, 2], 12),
    ],
)
def test_boundary_inclusion_direct_and_delayed_break(prices, end, sign):
    lines = pens([sign * p for p in prices])
    # Pin the segment's start: global window initialisation may select a
    # different already-confirmed start while this candidate is still waiting.
    pivot, known, evidence = _endpoint(lines, 0)
    assert lines[pivot].start.val == sign * end
    assert evidence["case"] == "boundary_inclusion_break"
    assert evidence["special_inclusion"] is True
    assert known == lines[-1].confirmed_index
    assert evidence["features"][0]["pen_indices"] == [1]
    assert evidence["features"][1]["pen_indices"] == [3]


@pytest.mark.parametrize(
    "prices",
    [
        [0, 10, 5, 12, 3, 8],  # only two reverse pens
        [0, 10, 5, 12, 3, 8, 4],  # inside the first attack
        [0, 10, 5, 12, 3, 8, 4, 13, 2],  # new high invalidates 12 first
    ],
)
def test_incomplete_or_invalidated_attack_cannot_confirm_old_pivot(prices):
    assert all(s.end.val != 12 for s in find_xds(pens(prices)))


def test_price_condition_stays_strict():
    lines = pens([12, 20])
    bottom, top = lines[0].start, lines[0].end
    bottom.k.low, bottom.k.high = 12, 14
    top.k.low, top.k.high = 10, 20
    assert not _can_form_bi(bottom, top, ChanlunConfig(bi_type="simple"))


def test_initial_inclusion_is_independent_of_candle_colour():
    def run(reverse):
        bars = [
            Kline(
                i,
                datetime(2026, 1, 1) + timedelta(days=i),
                hi if reverse else lo,
                lo if reverse else hi,
                hi,
                lo,
                1,
            )
            for i, (lo, hi) in enumerate([(10, 15), (11, 14), (12, 16), (13, 15)])
        ]
        return merge_klines(bars)

    for result in (run(False), run(True)):
        assert [(k.low, k.high) for k in result] == [(11, 14), (13, 16)]
        assert result[0].klines[0].index == 1
        assert result[1].merged_count == 2


def test_candidate_promotes_and_is_separate_from_confirmed_list():
    lines = pens([0, 10, 5, 12, 3, 8, 1])
    early = find_xds(lines[:3])
    tail = find_unfinished_xd(lines[:3], early)
    assert not early and tail.end.val == 12 and tail.confirmed_index is None
    final = find_xds(lines)
    assert final[0].end is tail.end
    new_tail = find_unfinished_xd(lines, final)
    assert new_tail.start is final[-1].end
    assert new_tail.direction != final[-1].direction
    assert new_tail not in final
    assert find_unfinished_xd(lines[:2], []) is None


def test_new_branch_is_prefix_stable():
    for prices in ([0, 10, 5, 12, 3, 8, 1, 9, 4, 11], [0, 10, 5, 12, 3, 8, 4, 9, 2, 13, 5, 15]):
        lines = pens(prices)
        final = find_xds(lines)

        def sig(items):
            return [(s.start.val, s.end.val, s.confirmed_index) for s in items]

        for n in range(3, len(lines) + 1):
            assert sig(find_xds(lines[:n])) == sig(
                [s for s in final if s.confirmed_index <= lines[n - 1].confirmed_index]
            )


def sample_bars():
    import pandas as pd

    values = [102, 101]
    points = [100, 110, 105, 112, 103, 108, 101, 106, 102]
    for a, b in zip(points, points[1:]):
        values.extend(a + (b - a) * j / 6 for j in range(6))
    values += [102, 103, 104]
    return pd.DataFrame(
        [
            dict(datetime=d, open=p, close=p, high=p + 0.1, low=p - 0.1, vol=1000)
            for d, p in zip(pd.date_range("2026-01-01", periods=len(values)), values)
        ]
    )


def test_full_pipeline_candidate_is_display_only_and_replay_promotes_it():
    from easy_tdx.chanlun import ChanlunAnalyser

    df = sample_bars()
    r = ChanlunAnalyser("FIXTURE", "daily").process_klines(df)
    assert r.xds[0].evidence["special_inclusion"]
    known = r.xds[0].confirmed_index
    before = ChanlunAnalyser("FIXTURE", "daily").process_klines(df.iloc[:known])
    after = ChanlunAnalyser("FIXTURE", "daily").process_klines(df.iloc[: known + 1])
    assert not before.xds and before.unfinished_xd.end.val == r.xds[0].end.val
    assert after.xds[0].end.val == before.unfinished_xd.end.val
    assert after.unfinished_xd.start.val == after.xds[-1].end.val
    d = r.to_dict()
    assert d["unfinished_xd"]["confirmed_index"] is None
    assert d["unfinished_xd"]["done"] is False
    r.unfinished_xd = None
    clean = r.to_dict()
    for key in (
        "xds",
        "xd_count",
        "structural_centres",
        "structural_signals",
        "mmds",
        "base_decomposition",
        "extension_hierarchy",
        "expansion_regrouping",
    ):
        assert d[key] == clean[key]
    assert ChanlunAnalyser("FIXTURE", "daily").process_klines(df.iloc[:0]).unfinished_xd is None
