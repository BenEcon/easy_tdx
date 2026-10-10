"""Causal, revisable cross-centre interpretations, separate from trading signals.

Formation records in expansion_regrouping remain unchanged. This view searches
anchored starts and later ends and may replace the partition as evidence arrives.
Its revisions are research interpretations, NOT completed natural movement types.
Every call rebuilds the ledger from the supplied confirmed prefix; no user,
symbol or future-data cache is involved.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from easy_tdx.chanlun.expansion_regrouping import (
    _completion_audit,
    _endpoints_consistent,
    expansion_regrouping,
)
from easy_tdx.chanlun.extension_recursion import extension_hierarchy
from easy_tdx.chanlun.mixed_sources import mixed_source_cover
from easy_tdx.chanlun.partition_search import ResearchPartitionSearch
from easy_tdx.chanlun.structure import confirmed_segment_prefix, find_structural_centres
from easy_tdx.chanlun.types import XD


def _preferred_proofs(
    proofs: list[dict[str, Any]], first: int, last: int, known: int
) -> list[dict[str, Any]]:
    """Keep maximal visible proofs overlapping this interpretation, not its tail."""
    visible = [
        proof
        for proof in proofs
        if proof["known_index"] <= known
        and proof["source_segment_indices"][0] <= last
        and proof["source_segment_indices"][-1] >= first
    ]
    return [
        proof
        for proof in visible
        if not any(
            parent["level"] > proof["level"]
            and parent["source_segment_indices"][0] <= proof["source_segment_indices"][0]
            and parent["source_segment_indices"][-1] >= proof["source_segment_indices"][-1]
            for parent in visible
        )
    ]


def _search_start(
    items: list[XD], starts: list[int], stop: int, search: ResearchPartitionSearch | None = None
) -> tuple[int, list[dict[str, Any]] | None]:
    """Keep the origin unless a later anchored start repairs endpoint geometry.

    Every permitted start still belongs to the original left centre; this must
    not slide into unrelated later centres. Never move merely to obtain another
    conflicting fallback. Within the consistent class retain the most sources.
    """
    origin = starts[0]
    search = search if search is not None else ResearchPartitionSearch(items)
    fallback = search.partition(origin, stop)
    if fallback and _endpoints_consistent(fallback):
        return origin, fallback
    for start in starts[1:]:
        if stop - start < 9:
            break
        parts = search.partition(start, stop)
        if parts and _endpoints_consistent(parts):
            return start, parts
    return origin, fallback


def _cover_at(
    available: list[XD],
    first: int,
    proofs: list[dict[str, Any]],
    revision: dict[str, Any],
    known: int,
) -> dict[str, Any]:
    roles = {index: "retained_prefix" for index in revision["retained_prefix_segment_indices"]}
    roles.update({index: "unresolved_selection" for index in revision["source_segment_indices"]})
    for ordinal, part in enumerate(revision["parts"]):
        roles.update({index: f"part_{ordinal}" for index in part["source_segment_indices"]})
    visible = [
        item
        for item in available[first:]
        if item.confirmed_index is not None and item.confirmed_index <= known
    ]
    for item in visible:
        roles.setdefault(item.index, "pending_tail")
    return mixed_source_cover(visible, proofs, roles, known, revision["id"])


def _audit_at(
    available: list[XD], revision: dict[str, Any], known: int, cover: dict[str, Any]
) -> dict[str, Any]:
    visible = [
        item
        for item in available
        if item.confirmed_index is not None and item.confirmed_index <= known
    ]
    positions = {item.index: pos for pos, item in enumerate(visible)}
    audit = _completion_audit(revision, visible, positions)
    audit["interpretation_id"] = audit.pop("candidate_id")
    audit["rule"] = "version_bound_completion_audit_v1"
    audit["as_of_index"] = known
    # A higher proof is an indivisible input, not completion of a flat part.
    # Retain every blocker rather than allowing valid endpoints to hide it.
    reasons = []
    if not revision["parts"]:
        reasons.append("no_current_partition")
    if revision["higher_proof_ids"]:
        reasons.append("higher_proof_requires_regrouping")
    if revision["retained_prefix_segment_indices"]:
        reasons.append("retained_prefix_unresolved")
    if cover["status"] != "covered":
        reasons.append("source_cover_conflict")
    if cover["joint_regrouping_required"]:
        reasons.append("indivisible_proof_crosses_boundary")
    reasons.append("same_level_completion_unproven")
    audit["blocking_reasons"] = reasons
    audit["natural_type_complete"] = False
    return audit


def regrouping_versions(segments: list[XD], bar_count: int | None = None) -> dict[str, Any]:
    """Version current partitions without rewriting their historical formation.

    Within the conservative three-component search, prefer consistent
    endpoints, then the latest valid end. The existing earliest-cut tie break is
    retained for any one start/end. A moved start must remain within the original
    left centre's members and pass endpoint checks; the detached prefix remains
    unresolved, never a fabricated completed trend. At equal endpoint quality
    and end, prefer the earliest start. Unconsumed sources remain a pending tail.
    A later conflicting cut cannot replace a consistent interpretation. A visible
    higher-level extension proof takes priority over flat redivision of its input.
    Components may be one-centre consolidations or strictly separated directed
    centre chains. Prefer an existing consistent single-centre solution before
    widening the model. These are implementation choices, not a uniqueness theorem.
    """
    available = confirmed_segment_prefix(segments, bar_count)
    formations = expansion_regrouping(available)["candidates"]
    proofs = extension_hierarchy(available)["proofs"]
    centres = {centre.index: centre for centre in find_structural_centres(available)}
    positions = {item.index: pos for pos, item in enumerate(available)}
    cases = []
    search = ResearchPartitionSearch(available)
    for formation in formations:
        if formation["known_index"] is None:
            continue
        first = positions[formation["source_segment_indices"][0]]
        start_ids = centres[formation["centre_indices"][0]].member_segments
        starts = [positions[index] for index in start_ids]
        initial_stop = positions[formation["source_segment_indices"][-1]] + 1
        revisions: list[dict[str, Any]] = []
        selected: list[dict[str, Any]] = []
        selected_first = first
        selected_stop = initial_stop
        selected_consistent = False
        signature = None
        # A source-confirmation group is atomic: never expose an intermediate
        # interpretation that no raw-bar replay could actually have observed.
        for stop in range(initial_stop, len(available) + 1):
            known = available[stop - 1].confirmed_index
            assert known is not None  # Confirmed prefix guarantees actual decision times.
            blocked = _preferred_proofs(
                proofs, available[first].index, available[stop - 1].index, known
            )
            if not blocked:
                start, parts = _search_start(available, starts, stop, search)
                consistent = bool(parts and _endpoints_consistent(parts))
                if parts and (consistent or not selected_consistent):
                    selected, selected_first, selected_stop = parts, start, stop
                    selected_consistent = consistent
            # Priority covers the selected span AND its retained prefix. Moving
            # a start must not evade an upgrade. An unrelated pending suffix
            # still cannot supersede this interpretation.
            priority = _preferred_proofs(
                proofs, available[first].index, available[selected_stop - 1].index, known
            )
            if stop < len(available) and available[stop].confirmed_index == known:
                continue
            status = (
                "requires_higher_level_inputs"
                if priority
                else "endpoint_consistent_draft"
                if selected_consistent
                else "endpoint_conflict_draft"
                if selected
                else "awaiting_partition"
            )
            proof_ids = [proof["id"] for proof in priority]
            new_signature = (
                status,
                tuple(tuple(p["source_segment_indices"]) for p in selected),
                tuple(proof_ids),
            )
            if signature == new_signature:
                continue
            reason = (
                "initial_interpretation"
                if not revisions
                else "higher_centre_priority"
                if priority
                else "endpoint_conflicts_resolved"
                if selected_consistent and revisions[-1]["status"] == "endpoint_conflict_draft"
                else "later_boundary_regrouping"
            )
            previous_start = (
                positions[revisions[-1]["source_segment_indices"][0]] if revisions else first
            )
            if not priority and previous_start != selected_first:
                reason = "start_boundary_regrouping"
            version = len(revisions) + 1
            revisions.append(
                {
                    "id": f"{formation['id']}:v{version}",
                    "version": version,
                    "supersedes": revisions[-1]["id"] if revisions else None,
                    "known_index": known,
                    "reason": reason,
                    "status": status,
                    "source_segment_indices": [
                        item.index for item in available[selected_first:selected_stop]
                    ],
                    "retained_prefix_segment_indices": [
                        item.index for item in available[first:selected_first]
                    ],
                    "prefix_role": "unresolved_prior_sources",
                    "start_change": (
                        {
                            "previous_start_segment_index": available[previous_start].index,
                            "current_start_segment_index": available[selected_first].index,
                            "detached_segment_indices": [
                                item.index for item in available[previous_start:selected_first]
                            ],
                            "reincorporated_segment_indices": [
                                item.index for item in available[selected_first:previous_start]
                            ],
                        }
                        if previous_start != selected_first
                        else None
                    ),
                    "parts": deepcopy(selected) if not priority else [],
                    "candidate_core": (
                        [max(p["low"] for p in selected), min(p["high"] for p in selected)]
                        if selected and not priority
                        else None
                    ),
                    "higher_proof_ids": proof_ids,
                    "natural_type_complete": False,
                    "eligible_for_recursive_input": False,
                }
            )
            signature = new_signature
        for revision in revisions:
            revision["mixed_source_cover"] = _cover_at(
                available, first, proofs, revision, revision["known_index"]
            )
            revision["completion_audit"] = _audit_at(
                available, revision, revision["known_index"], revision["mixed_source_cover"]
            )
        latest_known = available[-1].confirmed_index
        assert latest_known is not None
        current_cover = _cover_at(available, first, proofs, revisions[-1], latest_known)
        cases.append(
            {
                "candidate_id": formation["id"],
                "origin_start_segment_index": available[first].index,
                "start_anchor_segment_indices": list(start_ids),
                "formation_known_index": formation["known_index"],
                "as_of_index": available[-1].confirmed_index,
                "current_revision_id": revisions[-1]["id"],
                "revisions": revisions,
                "mixed_source_cover": current_cover,
                "completion_audit": _audit_at(
                    available, revisions[-1], latest_known, current_cover
                ),
                "pending_segment_indices": [item.index for item in available[selected_stop:]],
            }
        )
    return {
        "rule": "causal_regrouping_versions_v3",
        "scope": "revisable_interpretations_not_completed_types",
        "history_policy": "rebuild_same_input_prefix_same_rule",
        "natural_type_recursion_ready": False,
        "accepted_segment_count": len(available),
        "rejected_suffix_count": len(segments) - len(available),
        "cases": cases,
    }
