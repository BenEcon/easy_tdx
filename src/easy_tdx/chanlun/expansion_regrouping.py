"""Constructive cross-centre regrouping candidates (not natural type completion).

Two mature base centres with separated cores and touching/overlapping envelopes
are only the eligibility gate. Search a continuous three-way partition, retaining
all connectors, whose components each contain exactly one unpromoted centre.
Even a successful partition does not establish that its components are completed
natural movement types, so these candidates MUST NOT enter recursive trading.
"""
from __future__ import annotations

from functools import cache
from math import isclose

from easy_tdx.chanlun.extension_recursion import _endpoint_index
from easy_tdx.chanlun.structure import confirmed_segment_prefix, find_structural_centres
from easy_tdx.chanlun.types import XD


def _completion_audit(event: dict, available: list[XD], positions: dict[int, int]) -> dict:
    """Audit a frozen partition against currently observable continuation.

    Extreme-bounded geometry is a conservative prerequisite, NOT a theorem that
    every possible regrouping must meet. An opposite base segment proves only a
    lower-level turn. Neither condition establishes same-level type completion.
    Keep this evolving audit separate from immutable partition formation data.
    """
    parts = []
    for ordinal, part in enumerate(event['parts']):
        up = part['direction'] == 'up'
        start_extreme = part['low'] if up else part['high']
        end_extreme = part['high'] if up else part['low']
        start_valid = isclose(part['start_value'], start_extreme, rel_tol=1e-9, abs_tol=1e-8)
        end_valid = isclose(part['end_value'], end_extreme, rel_tol=1e-9, abs_tol=1e-8)
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


def _partition(items: list[XD]) -> list[dict] | None:
    @cache
    def component(start: int, stop: int) -> dict | None:
        chunk = items[start:stop]
        if chunk[0].start.val == chunk[-1].end.val:
            return None
        direction = 'up' if chunk[-1].end.val > chunk[0].start.val else 'down'
        if chunk[0].direction.value != direction or chunk[-1].direction.value != direction:
            return None
        centres = find_structural_centres(chunk)
        if len(centres) != 1 or len(centres[0].member_segments) >= 9:
            return None
        centre = centres[0]
        return {
            'source_segment_indices': [item.index for item in chunk],
            'seed_segment_indices': list(centre.seed_segments),
            'start_index': _endpoint_index(chunk[0].start),
            'end_index': _endpoint_index(chunk[-1].end),
            'start_value': chunk[0].start.val, 'end_value': chunk[-1].end.val,
            'direction': direction,
            'known_index': chunk[-1].confirmed_index,
            'low': min(item.low for item in chunk),
            'high': max(item.high for item in chunk),
            'zd': centre.zd, 'zg': centre.zg,
            'natural_type_complete': False,
        }

    # Stable tie break for THIS immutable source interval, not a claim that this
    # is the only possible Chan decomposition. All three parts have >=3 inputs.
    for first in range(3, len(items) - 5):
        a = component(0, first)
        if a is None:
            continue
        for second in range(first + 3, len(items) - 2):
            b, c = component(first, second), component(second, len(items))
            if b is None or c is None:
                continue
            if a['direction'] != c['direction'] or a['direction'] == b['direction']:
                continue
            parts = [a, b, c]
            if max(part['low'] for part in parts) < min(part['high'] for part in parts):
                return parts
    return None


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
        event['candidate_core'] = [max(part['low'] for part in parts),
                                   min(part['high'] for part in parts)]
    return {
        'rule': 'cross_centre_three_range_search_v1',
        'scope': 'regrouping_candidates_not_completed_types',
        'accepted_segment_count': len(available),
        'rejected_suffix_count': len(segments) - len(available),
        'candidates': candidates,
        'completion_audits': [_completion_audit(event, available, positions)
                              for event in candidates if event['parts']],
    }
