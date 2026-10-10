"""Explicit structural fixtures for lessons 62/77/20."""

from datetime import datetime, timedelta

import pytest

from easy_tdx.chanlun.bi import _can_form_bi, find_bis
from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.fractal import find_fractals
from easy_tdx.chanlun.types import BI, FX, CLKline, Direction, FXType, Kline
from easy_tdx.chanlun.xd import find_xds
from easy_tdx.chanlun.zs import find_zss


def fx(mid, value, kind):
    high, low = (value, value - 1) if kind == FXType.DING else (value + 1, value)
    candles = [
        CLKline(i, datetime(2026, 1, 1) + timedelta(days=i), low, high, high, low, 0, index=i)
        for i in range(mid - 1, mid + 2)
    ]
    return FX(kind, candles[1], candles, value)


@pytest.mark.parametrize("middle,expected", [(3, False), (4, False), (5, True)])
def test_exact_independent_candle_count(middle, expected):
    assert (
        _can_form_bi(fx(1, 10, FXType.DI), fx(middle, 20, FXType.DING), ChanlunConfig()) is expected
    )


def test_inverted_or_contained_price_range_rejected():
    assert not _can_form_bi(fx(1, 20, FXType.DI), fx(8, 19, FXType.DING), ChanlunConfig())
    assert not _can_form_bi(fx(1, 20, FXType.DI), fx(8, 21, FXType.DING), ChanlunConfig())


def test_replacing_extreme_updates_shared_endpoint():
    points = [
        fx(1, 10, FXType.DI),
        fx(5, 20, FXType.DING),
        fx(9, 22, FXType.DING),
        fx(13, 12, FXType.DI),
    ]
    lines = find_bis(points)
    assert len(lines) == 2
    assert lines[0].end is lines[1].start is points[2]
    assert lines[0].high == 22


def test_too_close_opposite_does_not_freeze_extreme():
    points = [
        fx(1, 10, FXType.DI),
        fx(3, 20, FXType.DING),
        fx(5, 8, FXType.DI),
        fx(9, 22, FXType.DING),
    ]
    lines = find_bis(points)
    assert len(lines) == 1
    assert lines[0].start is points[2]


def test_confirmation_uses_first_raw_bar_of_merged_right_candle():
    points = [fx(1, 10, FXType.DI), fx(5, 20, FXType.DING), fx(9, 12, FXType.DI)]
    right = points[-1].klines[-1]
    right.k_index = 12
    right.klines = [Kline(i, right.date, 13, 13, 14, 12, 0) for i in [10, 11, 12]]
    pens = find_bis(points)
    assert pens[0].confirmed_index == 10
    assert pens[-1].confirmed_index is None


def test_raw_containment_is_not_a_fractal():
    candles = [fx(i + 1, v, FXType.DI).k for i, v in enumerate([10, 11, 12])]
    candles[1].high = 20
    assert not find_fractals(candles)


def lines_from_prices(prices):
    points = [
        fx(1 + 4 * i, price, FXType.DI if i % 2 == 0 else FXType.DING)
        for i, price in enumerate(prices)
    ]
    return [
        BI(
            a,
            b,
            Direction.UP if i % 2 == 0 else Direction.DOWN,
            index=i,
            high=max(a.val, b.val),
            low=min(a.val, b.val),
        )
        for i, (a, b) in enumerate(zip(points, points[1:]))
    ]


def test_centre_core_does_not_shrink_on_extension():
    lines = lines_from_prices([8, 12, 10, 14, 11, 15])
    centre = find_zss(lines)[0]
    assert (centre.zd, centre.zg) == (10, 12)
    assert (centre.dd, centre.gg) == (8, 15)
    assert centre.line_count == 5
    assert not centre.done


def test_failed_centre_seed_uses_sliding_window():
    lines = lines_from_prices([2, 5, 4, 10, 8, 12])
    lines[0].high, lines[0].low = 3, 2
    centres = find_zss(lines)
    assert len(centres) == 1
    assert centres[0].lines[0] is lines[2]
    assert (centres[0].zd, centres[0].zg) == (8, 10)


def test_zone_forms_before_it_exits():
    lines = lines_from_prices([8, 12, 10, 14, 13, 16])
    initial = find_zss(lines[:3])[0]
    exited = find_zss(lines)[0]
    assert not initial.done
    assert exited.done
    assert (initial.zd, initial.zg) == (exited.zd, exited.zg) == (10, 12)


def test_feature_no_gap_requires_three_features():
    lines = lines_from_prices([0, 10, 5, 12, 7, 9, 4])
    assert not find_xds(lines[:5])
    segments = find_xds(lines)
    assert len(segments) == 1
    assert segments[0].end is lines[2].end
    assert segments[0].evidence["case"] == "no_gap_fractal"
    assert segments[0].confirmed_index == lines[5].end.klines[-1].k_index


def test_feature_gap_waits_for_reverse_fractal():
    lines = lines_from_prices([0, 10, 5, 15, 12, 14, 8, 11, 9, 13])
    assert not find_xds(lines[:6])
    segments = find_xds(lines)
    assert segments
    assert segments[0].end is lines[2].end
    assert segments[0].evidence["case"] == "gap_reverse_fractal"
    assert segments[0].confirmed_index == lines[8].end.klines[-1].k_index
    evidence = segments[0].evidence
    assert len(evidence["features"]) == len(evidence["reverse_features"]) == 3
    assert evidence["supporting_pen"] == 8
    for feature in evidence["features"] + evidence["reverse_features"]:
        assert feature["high_pen"] in feature["pen_indices"]
        assert feature["low_pen"] in feature["pen_indices"]
        assert feature["high"] == lines[feature["high_pen"]].high
        assert feature["low"] == lines[feature["low_pen"]].low


def test_feature_inclusion_preserves_all_member_pens():
    from easy_tdx.chanlun.xd import _features

    lines = lines_from_prices([0, 10, 5, 9, 6, 12, 7])
    snapshots = list(_features(lines, 0, Direction.UP))
    feature = snapshots[1][0][0]
    assert feature.members == (1, 3)
    assert feature.high_at == 1
    assert feature.low_at == 3
    assert (feature.low, feature.high) == (6, 10)
    assert snapshots[0][0][0].members == (1,)  # prior evidence is immutable


def test_segment_mirror_symmetry():
    lines = lines_from_prices([0, 10, 5, 12, 7, 9, 4])
    original = find_xds(lines)
    # Reverse every price coordinate and direction, keeping endpoint identity.
    for point in {id(p): p for b in lines for p in (b.start, b.end)}.values():
        point.val = -point.val
        point.fx_type = FXType.DING if point.fx_type == FXType.DI else FXType.DI
    for line in lines:
        line.high, line.low = -line.low, -line.high
        line.direction = Direction.DOWN if line.direction == Direction.UP else Direction.UP
    mirrored = find_xds(lines)
    assert len(original) == len(mirrored) == 1
    assert mirrored[0].direction == Direction.DOWN
    assert mirrored[0].confirmed_index == original[0].confirmed_index


def test_same_direction_breakout_is_not_segment_completion():
    assert not find_xds(lines_from_prices([0, 10, 5, 12]))


def test_later_gap_confirmation_cannot_rewrite_earlier_segment():
    prices = [
        0,
        11,
        9,
        10,
        -2,
        3,
        -1,
        3,
        0,
        12,
        10,
        21,
        9,
        18,
        16,
        26,
        19,
        20,
        19,
        21,
        17,
        21,
        12,
        22,
        21,
    ]
    lines = lines_from_prices(prices)
    final = find_xds(lines)
    assert final
    for n in range(6, len(lines) + 1):
        cutoff = lines[n - 1].end.klines[-1].k_index

        def signature(items):
            return [(s.start.k.index, s.end.k.index, s.confirmed_index) for s in items]

        assert signature(find_xds(lines[:n])) == signature(
            [s for s in final if s.confirmed_index <= cutoff]
        )


def test_completed_pen_prefix_replay_randomized():
    import random

    rng = random.Random(42)
    for _ in range(100):
        prices = [0]
        for i in range(24):
            prices.append(prices[-1] + (1 if i % 2 == 0 else -1) * rng.randint(1, 12))
        lines = lines_from_prices(prices)
        final = find_xds(lines)
        for n in range(6, len(lines) + 1):
            cutoff = lines[n - 1].end.klines[-1].k_index

            def signature(items):
                return [(s.start.k.index, s.end.k.index, s.confirmed_index) for s in items]

            assert signature(find_xds(lines[:n])) == signature(
                [s for s in final if s.confirmed_index <= cutoff]
            ), (prices, n)


def test_feature_evidence_uses_original_pen_ids_after_slicing():
    lines = lines_from_prices([0, 10, 5, 12, 7, 9, 4])
    for line in lines:
        line.index += 40
    (segment,) = find_xds(lines)
    evidence = segment.evidence
    assert evidence["start_pen"] == 40
    assert evidence["end_pen"] == 42
    assert evidence["feature_pen_indices"] == [41, 43, 45]
    assert evidence["supporting_pen"] == 45


def test_endpoint_pruning_preserves_exhaustive_earliest_confirmation():
    import random

    from easy_tdx.chanlun.xd import _endpoint, _initial_overlap

    rng = random.Random(928)
    for _ in range(30):
        prices = [100]
        for i in range(45):
            prices.append(prices[-1] + (1 if i % 2 == 0 else -1) * rng.randint(1, 12))
        lines = lines_from_prices(prices)
        # Include equal-time ties and non-monotonic synthetic known times so
        # pruning cannot rely on the natural ordering of the real pipeline.
        for line in lines:
            line.confirmed_index = rng.choice([200, 250, 300])
        candidates = [
            (start, _endpoint(lines, start))
            for start in range(len(lines) - 2)
            if _initial_overlap(lines, start)
        ]
        candidates = [(start, end) for start, end in candidates if end is not None]
        found = find_xds(lines)
        if not candidates:
            assert not found
            continue
        start, endpoint = min(candidates, key=lambda pair: (pair[1][1], pair[0]))
        assert found[0].start is lines[start].start
        assert found[0].end is lines[endpoint[0] - 1].end
        assert found[0].confirmed_index == endpoint[1]
        assert found[0].evidence == endpoint[2]
