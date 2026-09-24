"""Lesson 33's extension/regrouping proof, independent of natural type endings.

Nine committed lower-level movements can supply three overlapping ranges;
27 can supply three such higher ranges, and so on. A proof of a higher centre
is NOT proof that its surrounding trend has ended. This module deliberately
does not turn ownership blocks or two neighbouring centres into completed types.
"""
from __future__ import annotations

from easy_tdx.chanlun.structure import confirmed_segment_prefix, find_structural_centres
from easy_tdx.chanlun.types import FX, XD, FXType


def _endpoint_index(point: FX) -> int:
    field = 'high' if point.fx_type == FXType.DING else 'low'
    tolerance = max(1e-8, abs(point.val) * 1e-9)
    matches = [bar.index for bar in point.k.klines
               if abs(getattr(bar, field) - point.val) <= tolerance]
    return matches[-1] if matches else point.k.k_index


def _proof(items: list[XD], level: int, known: dict[int, int]) -> dict | None:
    """Construct an explicit associative regrouping; never rely on count alone."""
    if len(items) != 3 ** level:
        return None
    if level == 1:
        children = []
        ranges = [(item.low, item.high) for item in items]
    else:
        size = len(items) // 3
        children = [_proof(items[i:i + size], level - 1, known)
                    for i in range(0, len(items), size)]
        if any(child is None for child in children):
            return None
        ranges = [(child['low'], child['high']) for child in children]
    zd, zg = max(low for low, _ in ranges), min(high for _, high in ranges)
    if zd >= zg:
        return None
    return {
        'id': f'extension:L{level}:{items[0].index}:{items[-1].index}',
        'level': level,
        'source_segment_indices': [item.index for item in items],
        'start_index': _endpoint_index(items[0].start),
        'end_index': _endpoint_index(items[-1].end),
        'known_index': max(known[item.index] for item in items),
        'zd': zd, 'zg': zg,
        'low': min(item.low for item in items),
        'high': max(item.high for item in items),
        'children': children,
        'child_ranges': [list(bounds) for bounds in ranges],
        'basis': 'associative_regrouping',
        'natural_type_complete': False,
    }


def extension_hierarchy(segments: list[XD], bar_count: int | None = None) -> dict:
    """Return immutable formation proofs at their earliest committed-prefix time.

    An unreturned departure is excluded, as are missing/invalid suffixes. Each
    proof uses a connected, non-overlapping partition of ONE extending centre.
    Short independent centres are never stitched together to manufacture nine.
    Prefix recomputation is intentional: final envelope membership must not be
    used to backdate the proof of an unsuccessful departure's reintegration.
    """
    available = confirmed_segment_prefix(segments, bar_count)
    by_id = {item.index: item for item in available}
    proofs: dict[str, dict] = {}
    membership_known: dict[int, dict[int, int]] = {}
    for size in range(3, len(available) + 1):
        prefix = available[:size]
        for centre in find_structural_centres(prefix):
            members = centre.member_segments
            known = membership_known.setdefault(centre.index, {})
            for index in members:
                known.setdefault(index, prefix[-1].confirmed_index)
            level, width = 2, 9
            while width <= len(members):
                source = members[:width]
                if source != list(range(source[0], source[0] + width)):
                    break
                key = f'extension:L{level}:{source[0]}:{source[-1]}'
                if key not in proofs:
                    proof = _proof([by_id[index] for index in source], level, known)
                    if proof is not None:
                        proof['base_centre_index'] = centre.index
                        proof['base_core'] = [centre.zd, centre.zg]
                        proof['rule'] = 'nine_movement_extension_v1'
                        proofs[key] = proof
                level, width = level + 1, width * 3
    return {
        'rule': 'nine_movement_extension_v1',
        'scope': 'extension_regrouping_proofs_only',
        'natural_type_recursion_ready': False,
        'accepted_segment_count': len(available),
        'rejected_suffix_count': len(segments) - len(available),
        'highest_proven_level': max((proof['level'] for proof in proofs.values()), default=0),
        'proofs': list(proofs.values()),
    }
