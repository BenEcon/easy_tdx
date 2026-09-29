"""Auditable base centres built from confirmed segments, not display timeframes.

This is the base of recursion, not an implementation of all higher-level types.
Pen overlap zones stay separate for backwards-compatible auxiliary display.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from math import isfinite
from numbers import Integral

from easy_tdx.chanlun.anchors import extreme_index
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
    member_admissions: list[dict] = field(default_factory=list)


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


def _admission(segment: XD, witness: XD, reason: str) -> dict:
    return {'segment_index': segment.index, 'segment_confirmed_index': segment.confirmed_index,
            'admitted_index': witness.confirmed_index,
            'admission_segment_index': witness.index, 'reason': reason}


def _include(centre: StructuralCentre, segment: XD, witness: XD, reason: str) -> None:
    if segment.index not in centre.member_segments:
        centre.member_segments.append(segment.index)
        centre.member_admissions.append(_admission(segment, witness, reason))
        centre.dd = min(centre.dd, segment.low)
        centre.gg = max(centre.gg, segment.high)


def _valid_index(value: object) -> bool:
    return isinstance(value, Integral) and not isinstance(value, bool) and value >= 0


def _iter_confirmed_segments(segments: Iterable[XD], bar_count: int | None = None) -> Iterator[XD]:
    """Stop at the first invalid link on BOTH merged and raw candle timelines.

    A matching merged ordinal and price alone cannot identify a shared endpoint:
    separate copies must also agree on their raw extreme and merged-tail index.
    Missing source candles retain the common extreme_index fallback convention.
    """
    previous: XD | None = None
    previous_end: int | None = None
    for segment in segments:
        known = segment.confirmed_index
        if not _valid_index(known) or (bar_count is not None and known >= bar_count):
            break
        if not all(_valid_index(value) for value in (
                segment.index, segment.start.k.index, segment.end.k.index,
                segment.start.k.k_index, segment.end.k.k_index)):
            break
        start, end = segment.start.val, segment.end.val
        if (not all(isfinite(value) for value in (start, end, segment.low, segment.high))
                or segment.start.k.index >= segment.end.k.index
                or known < segment.end.k.k_index
                or not segment.low <= min(start, end) <= max(start, end) <= segment.high
                or start == end
                or segment.direction != (Direction.UP if end > start else Direction.DOWN)):
            break
        raw_start, raw_end = extreme_index(segment.start), extreme_index(segment.end)
        if (not _valid_index(raw_start) or not _valid_index(raw_end)
                or not (raw_start <= segment.start.k.k_index < raw_end
                        <= segment.end.k.k_index <= known)):
            break
        if previous is not None:
            connected = (previous.end.k.index == segment.start.k.index
                         and previous.end.val == segment.start.val
                         and previous.end.k.k_index == segment.start.k.k_index
                         and previous_end == raw_start)
            if (not connected or segment.index != previous.index + 1
                    or previous.direction == segment.direction
                    or segment.confirmed_index < previous.confirmed_index):
                break
        previous, previous_end = segment, raw_end
        yield segment


def confirmed_segment_prefix(segments: list[XD], bar_count: int | None = None) -> list[XD]:
    """Materialize the full valid prefix; retain the public batch/list contract."""
    return list(_iter_confirmed_segments(segments, bar_count))


def iter_structural_steps(segments: Iterable[XD]) -> Iterator[
    tuple[XD, StructuralCentre | None, StructuralCentre | None]
]:
    """Advance the base lifecycle exactly once per accepted confirmed segment.

    Yield (current segment, active/just-exited centre, previous exited centre).
    Centre objects are live, not snapshots: consumers must read/copy evidence
    before advancing. No unfinished or disconnected input is bridged. Core and
    boundary-touch rules are identical to the batch interface below. Validate
    each link immediately before use, so an early-stopping partition search
    never scans an unused suffix. Inputs must remain unchanged during iteration.
    """
    centre: StructuralCentre | None = None
    prior: StructuralCentre | None = None
    pending: XD | None = None
    seed: list[XD] = []
    for current in _iter_confirmed_segments(segments):
        if centre is None:
            seed = (seed + [current])[-3:]
            if len(seed) == 3:
                zd, zg = max(s.low for s in seed), min(s.high for s in seed)
                if zd < zg:
                    centre = StructuralCentre(
                        prior.index + 1 if prior else 0, zd, zg,
                        min(s.low for s in seed), max(s.high for s in seed),
                        [s.index for s in seed], [s.index for s in seed],
                        current.confirmed_index,
                    )
                    centre.member_admissions = [
                        _admission(s, current, 'seed_formation') for s in seed]
                    if prior:
                        centre.relation_at_formation = _relation(centre, prior)
                    _transition(centre, 'formed', current)
                    _record_relation(centre, prior, current)
                    seed = []
        else:
            if pending is not None:
                departure = pending
                up = departure.direction == Direction.UP
                stayed_out = (current.direction != departure.direction
                              and (current.low >= centre.zg if up else current.high <= centre.zd))
                if stayed_out:
                    centre.return_segment = current.index
                    centre.exited_index = current.confirmed_index
                    _transition(centre, 'exited', current)
                else:
                    _include(centre, departure, current, 'failed_departure_return')
                    centre.departure_segment = None
                    centre.departure_direction = None
                pending = None
            if centre.state != 'exited':
                outward = ((current.direction == Direction.UP and current.end.val > centre.zg)
                           or (current.direction == Direction.DOWN
                               and current.end.val < centre.zd))
                if outward:
                    pending = current
                    centre.departure_segment = current.index
                    centre.departure_direction = current.direction.value
                    _transition(centre, 'departed', current)
                else:
                    _include(centre, current, current, 'extension')
                    _transition(centre, 'extended', current)
            _record_relation(centre, prior, current)
        yield current, centre, prior
        if centre is not None and centre.state == 'exited':
            # The return starts the next seed; the departure remains a connector.
            prior, centre = centre, None
            seed = [current]


def find_structural_centres(segments: list[XD]) -> list[StructuralCentre]:
    """First-three fixed core; exit needs the first completed opposite return.

    A return touching the core boundary is accepted (>= / <=). Collect the live
    objects only here, where callers explicitly request their final batch state.
    """
    centres: list[StructuralCentre] = []
    for _, centre, _ in iter_structural_steps(segments):
        if centre is not None and (not centres or centres[-1] is not centre):
            centres.append(centre)
    return centres
