"""Characteristic-sequence segments (lessons 67/78).

Only confirmed segments are returned. A turn of one pen is not confirmation.
The unresolved tail is deliberately not drawn as a completed segment.
"""
from __future__ import annotations

from dataclasses import dataclass

from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.types import BI, XD, Direction


@dataclass
class Feature:
    high: float
    low: float
    high_at: int
    low_at: int
    last: int
    members: tuple[int, ...]


def _feature_evidence(sequence: list[Feature], bis: list[BI]) -> list[dict]:
    return [{'low': item.low, 'high': item.high,
             'pen_indices': [bis[i].index for i in item.members],
             'high_pen': bis[item.high_at].index, 'low_pen': bis[item.low_at].index}
            for item in sequence[-3:]]


def _features(bis: list[BI], start: int, direction: Direction):
    """Yield a fresh snapshot after each opposite-direction pen, preserving provenance."""
    sequence: list[Feature] = []
    for i in range(start, len(bis)):
        bi = bis[i]
        if bi.direction == direction:
            continue
        item = Feature(bi.high, bi.low, i, i, i, (i,))
        if sequence:
            prev = sequence[-1]
            included = ((prev.high >= item.high and prev.low <= item.low)
                        or (item.high >= prev.high and item.low <= prev.low))
            if included:
                upward = (prev.high > sequence[-2].high if len(sequence) > 1
                          else direction == Direction.UP)
                high_from = item if (item.high >= prev.high if upward
                                     else item.high <= prev.high) else prev
                low_from = item if (item.low >= prev.low if upward
                                    else item.low <= prev.low) else prev
                sequence[-1] = Feature(high_from.high, low_from.low,
                                       high_from.high_at, low_from.low_at, i,
                                       prev.members + item.members)
            else:
                sequence.append(item)
        else:
            sequence.append(item)
        yield sequence.copy(), i


def _turn(sequence: list[Feature], direction: Direction) -> bool:
    if len(sequence) < 3:
        return False
    a, b, c = sequence[-3:]
    if direction == Direction.UP:
        return b.high > max(a.high, c.high) and b.low > max(a.low, c.low)
    return b.high < min(a.high, c.high) and b.low < min(a.low, c.low)


def _initial_overlap(bis: list[BI], start: int) -> bool:
    seed = bis[start:start + 3]
    return len(seed) == 3 and min(b.high for b in seed) > max(b.low for b in seed)


def _endpoint(bis: list[BI], start: int):
    direction = bis[start].direction
    best = None
    for sequence, now in _features(bis, start, direction):
        if not _turn(sequence, direction):
            continue
        a, b, c = sequence[-3:]
        pivot = b.high_at if direction == Direction.UP else b.low_at
        # The opposite pen starts at the extremum. The segment ends BEFORE that pen.
        if pivot - start < 3 or (pivot - start) % 2 != 1:
            continue
        end_price = bis[pivot].start.val
        relevant = bis[start:pivot]
        if direction == Direction.UP:
            if end_price <= bis[start].start.val or end_price < max(p.high for p in relevant):
                continue
            gap = b.low > a.high
        else:
            if end_price >= bis[start].start.val or end_price > min(p.low for p in relevant):
                continue
            gap = b.high < a.low
        confirmation = now
        reverse_features = []
        if gap:
            reverse = Direction.DOWN if direction == Direction.UP else Direction.UP
            if not _initial_overlap(bis, pivot):
                continue
            confirmation = None
            for other, later in _features(bis, pivot, reverse):
                # Invalidated before a reverse feature fractal can confirm it.
                crossed = (bis[later].high > end_price if direction == Direction.UP
                           else bis[later].low < end_price)
                if crossed:
                    break
                if later >= now and _turn(other, reverse):
                    confirmation = later
                    reverse_features = _feature_evidence(other, bis)
                    break
            if confirmation is None:
                continue
        # Original-bar date on which the last supporting pen became observable.
        confirmed = max(p.confirmed_index if p.confirmed_index is not None
                        else p.end.klines[-1].k_index
                        for p in bis[start:confirmation + 1])
        candidate = pivot, confirmed, {
            'rule': 'feature_sequence_v1',
            'case': 'gap_reverse_fractal' if gap else 'no_gap_fractal',
            'feature_intervals': [[x.low, x.high] for x in (a, b, c)],
            'feature_pen_indices': [x.last for x in (a, b, c)],
            'start_pen': start, 'end_pen': pivot - 1,
            'features': _feature_evidence(sequence, bis),
            'reverse_features': reverse_features,
            'supporting_pen': bis[confirmation].index,
        }
        # A candidate waiting for a future reverse fractal must not displace
        # another candidate that had already confirmed earlier in real time.
        if best is None or confirmed < best[1]:
            best = candidate
    return best


def find_xds(bis: list[BI], config: ChanlunConfig | None = None) -> list[XD]:
    """Find connected, alternating confirmed segments; do not skip an unresolved tail."""
    result: list[XD] = []
    candidates = [(start, _endpoint(bis, start)) for start in range(len(bis) - 2)
                  if _initial_overlap(bis, start)]
    candidates = [(start, end) for start, end in candidates if end is not None]
    if not candidates:
        return result
    # Initialise by earliest observable confirmation, not by an earlier start
    # whose completion only becomes visible far into the future.
    start, _ = min(candidates, key=lambda pair: (pair[1][1], pair[0]))
    while start + 3 <= len(bis):
        if not _initial_overlap(bis, start):
            if result:
                break
            start += 1
            continue
        endpoint = _endpoint(bis, start)
        if endpoint is None:
            if result:
                break
            start += 1
            continue
        pivot, confirmed, evidence = endpoint
        if result:
            confirmed = max(confirmed, result[-1].confirmed_index)
        lines = bis[start:pivot]
        result.append(XD(start=lines[0].start, end=lines[-1].end,
                         direction=lines[0].direction, index=len(result),
                         high=max(line.high for line in lines),
                         low=min(line.low for line in lines), lines=lines,
                         confirmed_index=confirmed, evidence=evidence))
        start = pivot
    return result
