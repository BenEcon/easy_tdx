"""Lesson 33's extension/regrouping proof, independent of natural type endings.

Nine committed lower-level movements can supply three overlapping ranges;
27 can supply three such higher ranges, and so on. A proof of a higher centre
is NOT proof that its surrounding trend has ended. This module deliberately
does not turn ownership blocks or two neighbouring centres into completed types.
"""

from __future__ import annotations

from typing import Any

from easy_tdx.chanlun.anchors import extreme_index
from easy_tdx.chanlun.structure import (
    StructuralCentre,
    confirmed_segment_prefix,
    find_structural_centres,
)
from easy_tdx.chanlun.types import FX, XD


def _endpoint_index(point: FX) -> int:
    """Compatibility wrapper; all structural consumers share the raw anchor."""
    return extreme_index(point)


def _proof(
    items: list[XD], level: int, admissions: dict[int, dict[str, Any]]
) -> dict[str, Any] | None:
    """Construct an explicit associative regrouping; never rely on count alone."""
    if len(items) != 3**level:
        return None
    children: list[dict[str, Any]] = []
    if level == 1:
        ranges = [(item.low, item.high) for item in items]
    else:
        size = len(items) // 3
        for i in range(0, len(items), size):
            child = _proof(items[i : i + size], level - 1, admissions)
            if child is None:
                return None
            children.append(child)
        ranges = [(child["low"], child["high"]) for child in children]
    zd, zg = max(low for low, _ in ranges), min(high for _, high in ranges)
    if zd >= zg:
        return None
    return {
        "id": f"extension:L{level}:{items[0].index}:{items[-1].index}",
        "level": level,
        "source_segment_indices": [item.index for item in items],
        "start_index": _endpoint_index(items[0].start),
        "end_index": _endpoint_index(items[-1].end),
        "known_index": max(admissions[item.index]["admitted_index"] for item in items),
        # A return outside this node may be needed to admit its final member.
        # It is confirmation evidence, never an extra geometric source member.
        "member_admissions": [admissions[item.index].copy() for item in items],
        "zd": zd,
        "zg": zg,
        "low": min(item.low for item in items),
        "high": max(item.high for item in items),
        "children": children,
        "child_ranges": [list(bounds) for bounds in ranges],
        "basis": "associative_regrouping",
        "natural_type_complete": False,
    }


def centre_extension_proof(
    centre: StructuralCentre, by_id: dict[int, XD], level: int = 2
) -> dict[str, Any] | None:
    """Prove the admitted prefix of a live or final centre, never count alone.

    Usable by the signal pass without rebuilding its already visited lifecycle.
    A waiting departure is absent from member_segments and cannot supply an
    early upgrade. The returned proof is detached from the live admission ledger.
    """
    if level < 2:
        raise ValueError("Extension promotion starts at level 2")
    width = 3**level
    source = centre.member_segments[:width]
    if len(source) != width or source != list(range(source[0], source[0] + width)):
        return None
    admissions = {entry["segment_index"]: entry for entry in centre.member_admissions}
    proof = _proof([by_id[index] for index in source], level, admissions)
    if proof is not None:
        proof["base_centre_index"] = centre.index
        proof["base_core"] = [centre.zd, centre.zg]
        proof["rule"] = "nine_movement_extension_v1"
    return proof


def promoted_member_times(segments: list[XD], bar_count: int | None = None) -> dict[int, int]:
    """Earliest time each member belongs to a proven promoted centre.

    The first nine members prove promotion, but do not bound its later ownership.
    Every admitted member is protected from a fresh same-level local restart at
    max(promotion time, admission time). A pending departure or an external return
    is NOT an owned member. Final membership must never backdate this guard.
    This is the engineering recursion's conservative level policy, not a claim
    that lower-level structures cannot exist inside a higher-level centre.
    """
    available = confirmed_segment_prefix(segments, bar_count)
    by_id = {item.index: item for item in available}
    times = {}
    for centre in find_structural_centres(available):
        proof = centre_extension_proof(centre, by_id)
        if proof is None:
            continue
        for entry in centre.member_admissions:
            times[entry["segment_index"]] = max(proof["known_index"], entry["admitted_index"])
    return times


def extension_hierarchy(segments: list[XD], bar_count: int | None = None) -> dict[str, Any]:
    """Return immutable formation proofs at their earliest committed-prefix time.

    An unreturned departure is excluded, as are missing/invalid suffixes. Each
    proof uses a connected, non-overlapping partition of ONE extending centre.
    Short independent centres are never stitched together to manufacture nine.
    The lifecycle ledger records the actual admission time of each member.
    Final membership alone is insufficient: a failed departure is only admitted
    when its return confirms, not when the departure itself became observable.
    """
    available = confirmed_segment_prefix(segments, bar_count)
    by_id = {item.index: item for item in available}
    proofs: dict[str, dict[str, Any]] = {}
    for centre in find_structural_centres(available):
        members = centre.member_segments
        level, width = 2, 9
        while width <= len(members):
            source = members[:width]
            if source != list(range(source[0], source[0] + width)):
                break
            proof = centre_extension_proof(centre, by_id, level)
            if proof is not None:
                proofs[proof["id"]] = proof
            level, width = level + 1, width * 3
    return {
        "rule": "nine_movement_extension_v1",
        "scope": "extension_regrouping_proofs_only",
        "natural_type_recursion_ready": False,
        "accepted_segment_count": len(available),
        "rejected_suffix_count": len(segments) - len(available),
        "highest_proven_level": max((proof["level"] for proof in proofs.values()), default=0),
        "proofs": list(proofs.values()),
    }
