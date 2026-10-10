"""Lossless mixed-resolution source covers, NOT completed natural-type inputs.

An extension proof is indivisible here. Nested parent/child proofs cannot own
the same source twice; a proof crossing a requested window cannot be clipped.
The caller supplies an already validated confirmed chain and the interpretation
roles. These roles remain provisional even when the source cover is complete.
"""

from __future__ import annotations

from typing import Any, TypedDict

from easy_tdx.chanlun.types import XD


class RoleSpan(TypedDict):
    role: str
    source_segment_indices: list[int]


def mixed_source_cover(
    items: list[XD],
    proofs: list[dict[str, Any]],
    roles: dict[int, str],
    known: int,
    interpretation_id: str,
) -> dict[str, Any]:
    ids = [item.index for item in items]
    result: dict[str, Any] = {
        "rule": "indivisible_source_cover_v1",
        "interpretation_id": interpretation_id,
        "as_of_index": known,
        "source_segment_indices": ids,
        "status": "covered",
        "blocks": [],
        "conflicts": [],
        "joint_regrouping_required": False,
        "natural_type_complete": False,
        "eligible_for_recursive_input": False,
    }
    if not items:
        return result
    visible = [
        p
        for p in proofs
        if p["known_index"] <= known
        and p["source_segment_indices"][0] <= ids[-1]
        and p["source_segment_indices"][-1] >= ids[0]
    ]
    maximal = [
        p
        for p in visible
        if not any(
            q["level"] > p["level"]
            and q["source_segment_indices"][0] <= p["source_segment_indices"][0]
            and q["source_segment_indices"][-1] >= p["source_segment_indices"][-1]
            for q in visible
        )
    ]
    maximal.sort(key=lambda p: (p["source_segment_indices"][0], p["id"]))
    for i, proof in enumerate(maximal):
        source = proof["source_segment_indices"]
        reason = (
            "proof_crosses_window"
            if source[0] < ids[0] or source[-1] > ids[-1]
            else "overlapping_proofs"
            if i and maximal[i - 1]["source_segment_indices"][-1] >= source[0]
            else None
        )
        if reason:
            result["conflicts"].append(
                {
                    "reason": reason,
                    "proof_id": proof["id"],
                    "source_segment_indices": list(source),
                    "known_index": proof["known_index"],
                }
            )
    if result["conflicts"]:
        result["status"] = "blocked"
        result["joint_regrouping_required"] = True
        return result

    by_start = {p["source_segment_indices"][0]: p for p in maximal}
    positions = {item.index: pos for pos, item in enumerate(items)}
    blocks = result["blocks"]
    pos = 0
    while pos < len(items):
        item = items[pos]
        selected_proof = by_start.get(item.index)
        if selected_proof is None:
            stop = pos + 1
            while (
                stop < len(items)
                and items[stop].index not in by_start
                and roles[items[stop].index] == roles[item.index]
            ):
                stop += 1
        else:
            stop = positions[selected_proof["source_segment_indices"][-1]] + 1
        source_items = items[pos:stop]
        source = [s.index for s in source_items]
        spans: list[RoleSpan] = []
        for index in source:
            role = roles[index]
            if spans and spans[-1]["role"] == role:
                spans[-1]["source_segment_indices"].append(index)
            else:
                spans.append({"role": role, "source_segment_indices": [index]})
        joint = selected_proof is not None and len(spans) > 1
        blocks.append(
            {
                "kind": "extension_proof" if selected_proof else "base_run",
                "proof_id": selected_proof["id"] if selected_proof else None,
                "level": selected_proof["level"] if selected_proof else 0,
                "source_segment_indices": source,
                "known_index": selected_proof["known_index"]
                if selected_proof
                else source_items[-1].confirmed_index,
                "low": min(s.low for s in source_items),
                "high": max(s.high for s in source_items),
                "role_spans": spans,
                "crosses_role_boundary": joint,
                "natural_type_complete": False,
            }
        )
        result["joint_regrouping_required"] |= joint
        pos = stop
    return result
