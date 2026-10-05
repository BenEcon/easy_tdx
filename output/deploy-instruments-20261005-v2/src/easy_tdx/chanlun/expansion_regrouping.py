"""Constructive cross-centre regrouping candidates (not natural type completion).

Two mature base centres with separated cores and touching/overlapping envelopes
are only the eligibility gate. Search a continuous three-way partition, retaining
all connectors, whose components each contain exactly one unpromoted centre.
Even a successful partition does not establish that its components are completed
natural movement types, so these candidates MUST NOT enter recursive trading.
The separate dynamic research search may additionally admit directed chains of
unpromoted, strictly separated centres; fixed formation records stay unchanged.
"""
from __future__ import annotations

from collections.abc import Iterator
from functools import cache
from itertools import islice
from math import isclose

from easy_tdx.chanlun.anchors import extreme_index
from easy_tdx.chanlun.structure import (
    StructuralCentre,
    confirmed_segment_prefix,
    find_structural_centres,
    iter_structural_steps,
)
from easy_tdx.chanlun.types import XD


def _endpoint_checks(part: dict) -> tuple[float, float, bool, bool]:
    """Use identical directional-extreme tolerance in search and audit."""
    up = part['direction'] == 'up'
    start_extreme = part['low'] if up else part['high']
    end_extreme = part['high'] if up else part['low']
    return (
        start_extreme, end_extreme,
        isclose(part['start_value'], start_extreme, rel_tol=1e-9, abs_tol=1e-8),
        isclose(part['end_value'], end_extreme, rel_tol=1e-9, abs_tol=1e-8),
    )


def _endpoints_consistent(parts: list[dict]) -> bool:
    return all(all(_endpoint_checks(part)[2:]) for part in parts)


def _completion_audit(event: dict, available: list[XD], positions: dict[int, int]) -> dict:
    """Audit a frozen partition against currently observable continuation.

    Extreme-bounded geometry is a conservative prerequisite, NOT a theorem that
    every possible regrouping must meet. An opposite base segment proves only a
    lower-level turn. Neither condition establishes same-level type completion.
    Keep this evolving audit separate from immutable partition formation data.
    """
    parts = []
    source_parts = {index: ordinal for ordinal, part in enumerate(event['parts'])
                    for index in part['source_segment_indices']}
    for ordinal, part in enumerate(event['parts']):
        start_extreme, end_extreme, start_valid, end_valid = _endpoint_checks(part)
        after = positions[part['source_segment_indices'][-1]] + 1
        reverse = available[after] if after < len(available) else None
        has_reverse = reverse is not None and reverse.direction.value != part['direction']
        reasons = []
        if not start_valid:
            reasons.append('start_not_directional_extreme')
        if not end_valid:
            reasons.append('end_not_directional_extreme')
        if not has_reverse:
            reasons.append('no_confirmed_opposite_lower_unit')
        reasons.append('same_level_completion_unproven')
        parts.append({
            'part_index': ordinal,
            'source_segment_indices': list(part['source_segment_indices']),
            'start_extreme': start_extreme, 'end_extreme': end_extreme,
            'start_is_extreme': start_valid, 'end_is_extreme': end_valid,
            'opposite_segment_index': reverse.index if has_reverse else None,
            'opposite_known_index': reverse.confirmed_index if has_reverse else None,
            'opposite_evidence': {
                'segment_index': reverse.index, 'direction': reverse.direction.value,
                'start_index': extreme_index(reverse.start),
                'end_index': extreme_index(reverse.end),
                'start_value': reverse.start.val, 'end_value': reverse.end.val,
                'known_index': reverse.confirmed_index,
                # A/B typically reuse the next partition's first base segment.
                # This is NOT an independent completed type for each partition.
                'source_part_index': source_parts.get(reverse.index),
            } if has_reverse else None,
            'status': ('endpoint_conflict' if not (start_valid and end_valid) else
                       'awaiting_same_level_completion' if has_reverse else
                       'awaiting_opposite_lower_unit'),
            'blocking_reasons': reasons, 'natural_type_complete': False,
        })
    return {
        'candidate_id': event['id'],
        'as_of_index': available[-1].confirmed_index,
        'parts': parts, 'eligible_for_recursive_input': False,
    }


def _component_snapshot(first: XD, last: XD, centre: StructuralCentre,
                        low: float, high: float) -> dict:
    return {
        'seed_segment_indices': list(centre.seed_segments),
        'start_index': extreme_index(first.start), 'end_index': extreme_index(last.end),
        'start_value': first.start.val, 'end_value': last.end.val,
        'direction': 'up' if last.end.val > first.start.val else 'down',
        'known_index': last.confirmed_index, 'low': low, 'high': high,
        'zd': centre.zd, 'zg': centre.zg, 'natural_type_complete': False,
    }


def _component_prefixes(items: list[XD], start: int) -> dict[int, dict]:
    """Snapshot each eligible end after ONE lifecycle walk from this start.

    Only scalar geometry and the three seed IDs are retained. A second centre
    or nine admitted members disqualifies this and all longer prefixes, but
    must never erase eligible shorter ones. No live centre objects escape.
    """
    summaries: dict[int, dict] = {}
    first = items[start]
    low, high = first.low, first.high
    centre = None
    for stop, (current, active, _) in enumerate(iter_structural_steps(items[start:]), start + 1):
        low, high = min(low, current.low), max(high, current.high)
        if active is not None:
            if centre is None:
                centre = active
            elif active is not centre:
                break
        if centre is not None and len(centre.member_segments) >= 9:
            break
        if centre is None or first.start.val == current.end.val:
            continue
        direction = 'up' if current.end.val > first.start.val else 'down'
        if first.direction.value != direction or current.direction.value != direction:
            continue
        summaries[stop] = _component_snapshot(first, current, centre, low, high)
    return summaries


def _iter_trend_component_prefixes(items: list[XD], start: int) -> Iterator[
    tuple[int, dict | None]
]:
    """Permit a directed chain of strictly separated, unpromoted base centres.

    Centre envelopes grow monotonically: once separation is lost, a later
    suffix cannot repair this prefix. A promoted centre also disqualifies the
    whole component. These are candidate geometry rules, not completion rules.
    """
    first = items[start]
    low, high = first.low, first.high
    centres: list[StructuralCentre] = []
    up = first.direction.value == 'up'
    for stop, (current, active, _) in enumerate(
            iter_structural_steps(islice(items, start, None)), start + 1):
        low, high = min(low, current.low), max(high, current.high)
        if active is not None:
            if not centres or active is not centres[-1]:
                centres.append(active)
            if len(active.member_segments) >= 9:
                break
            if len(centres) > 1:
                previous = centres[-2]
                separated = active.dd > previous.gg if up else active.gg < previous.dd
                if not separated:
                    break
        if not centres or first.start.val == current.end.val:
            yield stop, None
            continue
        direction = 'up' if current.end.val > first.start.val else 'down'
        if direction != first.direction.value or current.direction.value != direction:
            yield stop, None
            continue
        summary = _component_snapshot(first, current, centres[0], low, high)
        summary['component_kind'] = ('trend_candidate' if len(centres) > 1
                                     else 'consolidation_candidate')
        summary['centre_chain'] = [{
            'seed_segment_indices': list(c.seed_segments), 'formed_index': c.formed_index,
            'zd': c.zd, 'zg': c.zg, 'low': c.dd, 'high': c.gg,
        } for c in centres]
        yield stop, summary


def _trend_component_prefixes(items: list[XD], start: int) -> dict[int, dict]:
    return {stop: summary for stop, summary in _iter_trend_component_prefixes(items, start)
            if summary is not None}


def _partition(items: list[XD], *, allow_trends: bool = False) -> list[dict] | None:
    """Search one already validated span; each caller owns its time boundary."""
    if len(items) < 9:
        return None

    @cache
    def prefixes(start: int) -> dict[int, dict]:
        return (_trend_component_prefixes(items, start) if allow_trends
                else _component_prefixes(items, start))

    @cache
    def component(start: int, stop: int) -> dict | None:
        # Small frozen windows commonly finish after just a few probes. Avoid
        # walking unused suffixes there; both paths share identical snapshots.
        if allow_trends or len(items) > 24:
            return prefixes(start).get(stop)
        chunk = items[start:stop]
        first, last = chunk[0], chunk[-1]
        if first.start.val == last.end.val:
            return None
        direction = 'up' if last.end.val > first.start.val else 'down'
        if first.direction.value != direction or last.direction.value != direction:
            return None
        centres = find_structural_centres(chunk)
        if len(centres) != 1 or len(centres[0].member_segments) >= 9:
            return None
        return _component_snapshot(first, last, centres[0],
                                   min(item.low for item in chunk),
                                   max(item.high for item in chunk))

    def materialize(first: int, second: int, parts: list[dict]) -> list[dict]:
        bounds = (0, first, second, len(items))
        return [{**part, 'source_segment_indices': [item.index for item in items[a:b]]}
                for part, a, b in zip(parts, bounds[:-1], bounds[1:], strict=True)]

    # Prefer a partition that passes the same endpoint prerequisite as the audit.
    # Keep the first geometric match as evidence if no such partition exists.
    # Within either class, ascending cuts are a stable tie break for THIS frozen
    # interval, not a claim of unique or completed natural Chan decomposition.
    fallback = None
    for first in range(3, len(items) - 5):
        a = component(0, first)
        if a is None:
            continue
        for second in range(first + 3, len(items) - 2):
            b = component(first, second)
            if b is None:
                continue
            c = component(second, len(items))
            if c is None:
                continue
            if a['direction'] != c['direction'] or a['direction'] == b['direction']:
                continue
            parts = [a, b, c]
            if max(part['low'] for part in parts) < min(part['high'] for part in parts):
                if _endpoints_consistent(parts):
                    return materialize(first, second, parts)
                if fallback is None:
                    fallback = first, second, parts
    return materialize(*fallback) if fallback is not None else None


def _research_partition(items: list[XD]) -> list[dict] | None:
    """Retain an existing endpoint-consistent answer, else widen the search.

    Search multi-centre trend components only when the single-centre model has
    no consistent answer. Never replace an existing geometric fallback by a
    different conflicting fallback. Fixed formation records keep the old model.
    """
    if len(items) < 9 or items[0].direction != items[-1].direction:
        return None
    original = _partition(items)
    if original and _endpoints_consistent(original):
        return original
    wider = _partition(items, allow_trends=True)
    if wider and _endpoints_consistent(wider):
        return wider
    return original or wider


def expansion_regrouping(segments: list[XD], bar_count: int | None = None) -> dict:
    available = confirmed_segment_prefix(segments, bar_count)
    positions = {item.index: pos for pos, item in enumerate(available)}
    candidates = []
    centres = find_structural_centres(available)
    for left, right in zip(centres, centres[1:]):
        if right.relation_current != 'expansion_candidate':
            continue
        event = {
            'id': f'expansion:{left.seed_segments[0]}:{right.seed_segments[0]}',
            'centre_indices': [left.index, right.index],
            'envelope_overlap': [max(left.dd, right.dd), min(left.gg, right.gg)],
            'status': 'awaiting_centre_exit',
            'known_index': None, 'source_segment_indices': [],
            'parts': [], 'candidate_core': None,
            'partition_selection': None,
            'natural_type_complete': False, 'higher_level_confirmed': False,
        }
        candidates.append(event)
        if left.state != 'exited' or right.state != 'exited':
            continue
        event['known_index'] = right.exited_index
        # The proof spans the left seed through the right exit's completed
        # return. This is an alternative regrouping, not a change of ownership.
        start, stop = positions[left.seed_segments[0]], positions[right.return_segment] + 1
        source = available[start:stop]
        event['source_segment_indices'] = [item.index for item in source]
        if any(len(centre.member_segments) >= 9 for centre in (left, right)):
            event['status'] = 'requires_higher_level_inputs'
            continue
        parts = _partition(source)
        if parts is None:
            event['status'] = 'no_three_range_partition'
            continue
        event['status'] = 'partition_found_awaiting_type_completion'
        event['parts'] = parts
        event['partition_selection'] = (
            'endpoint_consistent_preferred' if _endpoints_consistent(parts)
            else 'geometric_fallback_with_conflicts'
        )
        event['candidate_core'] = [max(part['low'] for part in parts),
                                   min(part['high'] for part in parts)]
    return {
        'rule': 'cross_centre_three_range_search_v2',
        'scope': 'regrouping_candidates_not_completed_types',
        'accepted_segment_count': len(available),
        'rejected_suffix_count': len(segments) - len(available),
        'candidates': candidates,
        'completion_audits': [_completion_audit(event, available, positions)
                              for event in candidates if event['parts']],
    }
