"""Auditable base centres built from confirmed segments, not display timeframes.

This is the base of recursion, not an implementation of all higher-level types.
Pen overlap zones stay separate for backwards-compatible auxiliary display.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from numbers import Integral

from easy_tdx.chanlun.types import XD, Direction


@dataclass
class StructuralCentre:
    index: int
    zd: float
    zg: float
    dd: float
    gg: float
    seed_segments: list[int]
    member_segments: list[int]
    formed_index: int
    state: str = 'formed'
    departure_segment: int | None = None
    departure_direction: str | None = None
    return_segment: int | None = None
    exited_index: int | None = None
    relation_at_formation: str = 'initial'
    transitions: list[dict] = field(default_factory=list)
    relation_current: str = 'initial'
    relation_history: list[dict] = field(default_factory=list)


def _relation(centre: StructuralCentre, prior: StructuralCentre) -> str:
    if centre.dd > prior.gg:
        return 'separated_up'
    if centre.gg < prior.dd:
        return 'separated_down'
    if centre.zd > prior.zg or centre.zg < prior.zd:
        return 'expansion_candidate'
    return 'overlapping'


def _record_relation(centre: StructuralCentre, prior: StructuralCentre | None,
                     segment: XD) -> None:
    """Snapshot committed members only; pending departures stay outside the envelope.

    Exit freezes this base-centre grouping, NOT a completed higher-level type.
    In particular, two exited centres are insufficient to claim full recursion.
    """
    if prior is None:
        return
    relation = _relation(centre, prior)
    centre.relation_current = relation
    both_exited = centre.state == prior.state == 'exited'
    previous = centre.relation_history[-1] if centre.relation_history else None
    if previous and (previous['relation'], previous['both_exited']) == (relation, both_exited):
        return
    low, high = max(centre.dd, prior.dd), min(centre.gg, prior.gg)
    centre.relation_history.append({
        'relation': relation, 'known_index': segment.confirmed_index,
        'segment_index': segment.index, 'previous_centre': prior.index,
        'previous_envelope': [prior.dd, prior.gg],
        'current_envelope': [centre.dd, centre.gg],
        'envelope_overlap': [low, high] if low <= high else None,
        'member_segments': list(centre.member_segments),
        'both_exited': both_exited, 'higher_level_confirmed': False,
    })


def _transition(centre: StructuralCentre, state: str, segment: XD) -> None:
    centre.state = state
    centre.transitions.append({'state': state, 'known_index': segment.confirmed_index,
                               'segment_index': segment.index})


def _include(centre: StructuralCentre, segment: XD) -> None:
    if segment.index not in centre.member_segments:
        centre.member_segments.append(segment.index)
        centre.dd = min(centre.dd, segment.low)
        centre.gg = max(centre.gg, segment.high)


def confirmed_segment_prefix(segments: list[XD], bar_count: int | None = None) -> list[XD]:
    """Stop at the first invalid link; never silently bridge an incomplete chain."""
    available: list[XD] = []
    for segment in segments:
        known = segment.confirmed_index
        if (not isinstance(known, Integral) or isinstance(known, bool) or known < 0
                or (bar_count is not None and known >= bar_count)):
            break
        if (not isinstance(segment.index, Integral) or isinstance(segment.index, bool)
                or segment.index < 0):
            break
        start, end = segment.start.val, segment.end.val
        if (not all(isfinite(value) for value in (start, end, segment.low, segment.high))
                or segment.start.k.index >= segment.end.k.index
                or known < segment.end.k.k_index
                or not segment.low <= min(start, end) <= max(start, end) <= segment.high
                or start == end
                or segment.direction != (Direction.UP if end > start else Direction.DOWN)):
            break
        if available:
            previous = available[-1]
            connected = (previous.end.k.index == segment.start.k.index
                         and previous.end.val == segment.start.val)
            if (not connected or segment.index != previous.index + 1
                    or previous.direction == segment.direction
                    or segment.confirmed_index < previous.confirmed_index):
                break
        available.append(segment)
    return available


def find_structural_centres(segments: list[XD]) -> list[StructuralCentre]:
    """First-three fixed core; exit requires a completed first opposite return.

Unknown/disconnected input terminates the chain instead of bridging missing data.
The first departure is held separately and is folded into the envelope only if
its return re-enters the core. A boundary touch on return is accepted (>= / <=).
"""
    available = confirmed_segment_prefix(segments)
    centres: list[StructuralCentre] = []
    cursor = 0
    while cursor + 3 <= len(available):
        seed = available[cursor:cursor + 3]
        zd, zg = max(s.low for s in seed), min(s.high for s in seed)
        if zd >= zg:
            cursor += 1
            continue
        centre = StructuralCentre(len(centres), zd, zg, min(s.low for s in seed),
                                  max(s.high for s in seed), [s.index for s in seed],
                                  [s.index for s in seed], seed[-1].confirmed_index)
        prior = centres[-1] if centres else None
        if prior:
            centre.relation_at_formation = _relation(centre, prior)
        _transition(centre, 'formed', seed[-1])
        _record_relation(centre, prior, seed[-1])
        pending: int | None = None
        j = cursor + 3
        while j < len(available):
            current = available[j]
            if pending is not None:
                departure = available[pending]
                up = departure.direction == Direction.UP
                stayed_out = (current.direction != departure.direction
                              and (current.low >= zg if up else current.high <= zd))
                if stayed_out:
                    centre.return_segment = current.index
                    centre.exited_index = current.confirmed_index
                    _transition(centre, 'exited', current)
                    _record_relation(centre, prior, current)
                    break
                _include(centre, departure)
                centre.departure_segment = None
                centre.departure_direction = None
                pending = None
            outward = ((current.direction == Direction.UP and current.end.val > zg)
                       or (current.direction == Direction.DOWN and current.end.val < zd))
            if outward:
                pending = j
                centre.departure_segment = current.index
                centre.departure_direction = current.direction.value
                _transition(centre, 'departed', current)
            else:
                _include(centre, current)
                _transition(centre, 'extended', current)
            _record_relation(centre, prior, current)
            j += 1
        centres.append(centre)
        if centre.state != 'exited':
            break
        # The departure connects centres. The completed return can start the next
        # triple; including the departure would force both envelopes to overlap.
        cursor = j
    return centres
