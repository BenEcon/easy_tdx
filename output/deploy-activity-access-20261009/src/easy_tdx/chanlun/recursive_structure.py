"""Centre lifecycles on completed engineering types, not on invented segments.

Consume each continuous, same-level chain independently. A centre or extension
proof never becomes a completed consolidation/type merely by being exported.
The XD objects are internal geometry adapters; all public provenance uses the
actual child type IDs and their original base-segment ownership.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from easy_tdx.chanlun.anchors import extreme_index
from easy_tdx.chanlun.extension_recursion import extension_hierarchy
from easy_tdx.chanlun.structure import find_structural_centres
from easy_tdx.chanlun.types import XD


def recursive_structure_layer(
    chains: list[list[XD]],
    records: dict[int, dict[str, Any]],
    input_level: int,
    *,
    namespace: str = "T",
) -> dict[str, Any]:
    """Internal adapter: caller supplies validated, source-contiguous chains."""

    def ids(indices: list[int]) -> list[str]:
        return [records[i]["id"] for i in indices]

    def sources(indices: list[int]) -> list[int]:
        return [s for i in indices for s in records[i]["source_segment_indices"]]

    def optional_id(index: int | None) -> str | None:
        identity: str | None = records[index]["id"] if index is not None else None
        return identity

    def admissions(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "unit_id": records[e["segment_index"]]["id"],
                "unit_confirmed_index": e["segment_confirmed_index"],
                "admitted_index": e["admitted_index"],
                "witness_id": records[e["admission_segment_index"]]["id"],
                "reason": e["reason"],
            }
            for e in entries
        ]

    def proof_snapshot(proof: dict[str, Any]) -> dict[str, Any]:
        base = sources(proof["source_segment_indices"])
        return {
            "id": f"recursive-extension:{namespace}{input_level}:"
            f"{proof['level']}:{base[0]}:{base[-1]}",
            "input_level": input_level,
            "relative_depth": proof["level"],
            "source_unit_ids": ids(proof["source_segment_indices"]),
            "source_segment_indices": base,
            "start_index": proof["start_index"],
            "end_index": proof["end_index"],
            "known_index": proof["known_index"],
            "zd": proof["zd"],
            "zg": proof["zg"],
            "low": proof["low"],
            "high": proof["high"],
            "member_admissions": admissions(proof["member_admissions"]),
            "children": [proof_snapshot(child) for child in proof["children"]],
            "natural_type_complete": False,
            "eligible_for_trend_recursion": False,
        }

    result = []
    for chain in chains:
        lookup = {s.index: s for s in chain}
        centres = find_structural_centres(chain)
        centre_ids = {
            c.index: f"recursive-centre:{namespace}{input_level}:"
            f"{sources(c.seed_segments)[0]}:{sources(c.seed_segments)[-1]}"
            for c in centres
        }
        snapshots = []
        for centre in centres:
            members = centre.member_segments
            snapshots.append(
                {
                    "id": centre_ids[centre.index],
                    "input_level": input_level,
                    "state": centre.state,
                    "zd": centre.zd,
                    "zg": centre.zg,
                    "low": centre.dd,
                    "high": centre.gg,
                    "seed_unit_ids": ids(centre.seed_segments),
                    "source_unit_ids": ids(members),
                    "source_segment_indices": sources(members),
                    "start_index": extreme_index(lookup[members[0]].start),
                    "end_index": extreme_index(lookup[members[-1]].end),
                    "formed_index": centre.formed_index,
                    "exited_index": centre.exited_index,
                    "known_index": centre.transitions[-1]["known_index"],
                    "departure_id": optional_id(centre.departure_segment),
                    "return_id": optional_id(centre.return_segment),
                    "member_admissions": admissions(centre.member_admissions),
                    "transitions": [
                        {
                            "state": t["state"],
                            "known_index": t["known_index"],
                            "unit_id": records[t["segment_index"]]["id"],
                        }
                        for t in centre.transitions
                    ],
                    "relation_current": centre.relation_current,
                    "relation_history": [
                        {
                            "relation": h["relation"],
                            "known_index": h["known_index"],
                            "previous_centre_id": centre_ids[h["previous_centre"]],
                            "witness_id": records[h["segment_index"]]["id"],
                            "previous_envelope": h["previous_envelope"],
                            "current_envelope": h["current_envelope"],
                            "envelope_overlap": h["envelope_overlap"],
                            "source_unit_ids": ids(h["member_segments"]),
                            "both_exited": h["both_exited"],
                            "higher_level_confirmed": False,
                        }
                        for h in centre.relation_history
                    ],
                    "natural_type_complete": False,
                    "eligible_for_trend_recursion": False,
                }
            )
        result.append(
            {
                "id": f"recursive-chain:{namespace}{input_level}:{sources([chain[0].index])[0]}",
                "input_ids": ids([s.index for s in chain]),
                "as_of_index": chain[-1].confirmed_index,
                "centres": snapshots,
                "extension_proofs": [
                    proof_snapshot(p) for p in extension_hierarchy(chain)["proofs"]
                ],
            }
        )
    return deepcopy(
        {
            "input_level": input_level,
            "chains": result,
            "scope": "centres_on_completed_engineering_trends",
            "natural_type_recursion_ready": False,
        }
    )
