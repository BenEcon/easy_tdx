"""Lossless ownership of the confirmed base chain; not recursive trend types.

This fixed grouping retains connectors and unresolved pieces explicitly. A
centre's confirmed return belongs to the next group, not both groups. Consumers
must recompute a historical prefix: open ownership can change as bars arrive.
"""
from __future__ import annotations

from easy_tdx.chanlun.structure import confirmed_segment_prefix, find_structural_centres
from easy_tdx.chanlun.types import XD


def decompose_base_chain(segments: list[XD], bar_count: int | None = None) -> dict:
    available = confirmed_segment_prefix(segments, bar_count)
    centres = find_structural_centres(available)
    # role, centre id, ownership frozen, decision time
    owners: dict[int, tuple[str, int | None, bool, int]] = {}
    for centre in centres:
        closed = centre.state == 'exited'
        known = centre.transitions[-1]['known_index']
        for index in centre.member_segments:
            owners[index] = ('centre_members', centre.index, closed, known)
        if centre.departure_segment is not None:
            owners[centre.departure_segment] = (
                'connector' if closed else 'pending_departure', centre.index, closed, known)

    blocks: list[dict] = []
    for segment in available:
        role, centre, frozen, known = owners.get(
            segment.index, ('unassigned', None, False, segment.confirmed_index))
        identity = (role, centre, frozen)
        previous = blocks[-1] if blocks else None
        if previous and (previous['role'], previous['centre_index'],
                         previous['ownership_frozen']) == identity:
            block = previous
            block['segment_indices'].append(segment.index)
            block['known_index'] = max(block['known_index'], known)
            block['end_index'] = segment.end.k.k_index
            block['high'] = max(block['high'], segment.high)
            block['low'] = min(block['low'], segment.low)
        else:
            blocks.append({
                'role': role, 'centre_index': centre, 'ownership_frozen': frozen,
                'segment_indices': [segment.index], 'known_index': known,
                'start_index': segment.start.k.k_index, 'end_index': segment.end.k.k_index,
                'high': segment.high, 'low': segment.low,
                'recursive_type_complete': False,
            })
    return {
        'rule': 'fixed_base_ownership_v1', 'recursive_levels_ready': False,
        'input_segment_count': len(segments), 'accepted_segment_count': len(available),
        'rejected_suffix_count': len(segments) - len(available),
        'as_of_index': available[-1].confirmed_index if available else None,
        'blocks': blocks,
    }
