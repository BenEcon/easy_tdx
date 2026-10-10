"""Whole-domain release under the explicitly approved engineering completion rule.

An ownership range is not a completed movement. Only an independently detected
parent can cover it and release its sources. Old interpreters remain independent.
This module makes no claim of a unique decomposition or original-theory equivalence.
"""

from collections.abc import Callable
from copy import deepcopy
from typing import Any, TypedDict

from easy_tdx.chanlun.anchors import extreme_index
from easy_tdx.chanlun.engineering_consolidations import consolidation_candidates
from easy_tdx.chanlun.engineering_trends import _candidates, _chains
from easy_tdx.chanlun.extension_recursion import extension_hierarchy
from easy_tdx.chanlun.layered_ownership import _claim_events, _domains
from easy_tdx.chanlun.recursive_structure import recursive_structure_layer
from easy_tdx.chanlun.release_review import POLICIES, select_for_review
from easy_tdx.chanlun.structure import confirmed_segment_prefix
from easy_tdx.chanlun.types import XD, Kline

RULE = "whole_domain_parent_release_v1"


class Placement(TypedDict):
    accepted: bool
    reason: str | None
    conflicts: list[dict[str, str]]
    enclosing_domain_ids: list[str]
    released_domain_ids: list[str]
    known_index: int
    eligible_for_external_recursion: bool


class SourceCover(TypedDict):
    movement_id: str | None
    status: str
    level: int
    source_segment_indices: list[int]
    start_index: int
    end_index: int


def _source(records: dict[int, dict[str, Any]], indices: list[int]) -> list[int]:
    return [source for i in indices for source in records[i]["source_segment_indices"]]


def _ownership_domains(
    chain: list[XD], records: dict[int, dict[str, Any]], input_level: int
) -> list[dict[str, Any]]:
    """Actual claims and strongest proven upgrade, never a source-count shortcut."""
    claims: dict[str, dict[str, Any]] = {}
    times: dict[str, int] = {}
    admitted: dict[int, int] = {}
    active: list[dict[str, Any]] = []
    for known, batch in sorted(_claim_events(chain).items()):
        for claim in batch:
            claims[claim["key"]] = claim
            times[claim["key"]] = known
            for index in claim["sources"]:
                admitted.setdefault(index, known)
        next_active = []
        for domain in _domains(claims):
            previous = [
                old for old in active if set(old["sources"]).intersection(domain["sources"])
            ]
            domain["context_known_index"] = (
                previous[0]["context_known_index"] if len(previous) == 1 else known
            )
            next_active.append(domain)
        active = next_active
    proofs = extension_hierarchy(chain)["proofs"]
    domains = []
    for domain in active:
        indices = set(domain["sources"])
        relevant = [p for p in proofs if set(p["source_segment_indices"]) <= indices]
        required = max([input_level + 2, *(input_level + p["level"] for p in relevant)])
        known = max(
            [*(times[key] for key in domain["claims"]), *(p["known_index"] for p in relevant)]
        )
        sources = _source(records, domain["sources"])
        domains.append(
            {
                "id": f"release-domain:M{input_level}:{sources[0]}:{sources[-1]}:at:{known}",
                "input_level": input_level,
                "required_parent_level": required,
                "known_index": known,
                "source_segment_indices": sources,
                "context_known_index": domain["context_known_index"],
                "member_admissions": [
                    {
                        "source_segment_indices": list(records[i]["source_segment_indices"]),
                        "admitted_index": admitted[i],
                    }
                    for i in domain["sources"]
                ],
                "source_unit_ids": [records[i]["id"] for i in domain["sources"]],
                "claim_kinds": sorted({claims[key]["kind"] for key in domain["claims"]}),
                "proof_ids": [p["id"] for p in relevant],
                "natural_type_complete": False,
            }
        )
    return domains


def _placement(
    candidate: dict[str, Any], witness: dict[str, Any], domains: list[dict[str, Any]]
) -> Placement:
    """Classify validated complete records; this is NOT a completion detector.

    A source crossing only part of a domain cannot leave that domain. A witness
    is outside price coverage and may be internal to the same enclosing owner,
    unowned, or independently complete above every domain that it fully covers.
    """
    source = set(candidate["source_segment_indices"])
    reverse = set(witness["source_segment_indices"])
    enclosing, released, conflicts = [], [], []
    known = max(candidate["original_known_index"], witness["known_index"])
    for domain in domains:
        owned = set(domain["source_segment_indices"])
        if not source.intersection(owned):
            continue
        if owned <= source and candidate["level"] >= domain["required_parent_level"]:
            known = max(known, domain["known_index"])
            released.append(domain["id"])
        elif source <= owned:
            # Later growth must not delay every old child to the final member's
            # time: that collapses distinct confirmation batches and can erase
            # valid internal M2/M3 structures before a release is even tested.
            relevant = [
                entry["admitted_index"]
                for entry in domain["member_admissions"]
                if source.intersection(entry["source_segment_indices"])
            ]
            known = max(known, domain["context_known_index"], *relevant)
            enclosing.append(domain["id"])
        else:
            conflicts.append(("partial_domain_coverage", domain["id"]))
    for domain in domains:
        owned = set(domain["source_segment_indices"])
        if not reverse.intersection(owned) or domain["id"] in enclosing:
            continue
        if owned <= reverse and witness["level"] >= domain["required_parent_level"]:
            known = max(known, domain["known_index"])
            continue
        conflicts.append(("foreign_internal_witness", domain["id"]))
    return {
        "accepted": not conflicts,
        "reason": conflicts[0][0] if conflicts else None,
        "conflicts": [{"reason": reason, "domain_id": identity} for reason, identity in conflicts],
        "enclosing_domain_ids": enclosing,
        "released_domain_ids": released,
        "known_index": known,
        "eligible_for_external_recursion": not conflicts and not enclosing,
    }


def _requirements(
    candidate: dict[str, Any],
    witness: dict[str, Any],
    children: list[dict[str, Any]],
    domains: list[dict[str, Any]],
    placement: Placement,
) -> list[str]:
    """Propagate quarantined price/confirmation dependencies until fully covered."""
    required = {
        identity
        for child in [*children, witness]
        for identity in child.get("required_domain_ids", [])
    }
    required.update(placement.get("enclosing_domain_ids", []))
    required.update(item["domain_id"] for item in placement["conflicts"])
    source = set(candidate["source_segment_indices"])
    return [
        domain["id"]
        for domain in domains
        if domain["id"] in required
        and not (
            set(domain["source_segment_indices"]) <= source
            and candidate["level"] >= domain["required_parent_level"]
        )
    ]


def _finalize_placements(
    levels: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    domains: list[dict[str, Any]],
) -> None:
    """Propagate newly discovered higher owners through every confirmation edge.

    Every edge points one level down, including reverse witnesses, so this is
    topologically ordered. Testing only each parent's direct geometry would
    miss a remote grandchild witness absorbed by a later-discovered domain.
    """
    domain_times = {domain["id"]: domain["known_index"] for domain in domains}
    for layer in levels:
        for record in layer["types"]:
            witness = records[record["opposite_id"]]
            children = [records[identity] for identity in record["child_ids"]]
            final = _placement(record, witness, domains)
            final["known_index"] = max(
                final["known_index"],
                *(
                    child.get("current_placement", {}).get("known_index", child["known_index"])
                    for child in [*children, witness]
                ),
                *(domain_times[c["domain_id"]] for c in final["conflicts"]),
            )
            record["required_domain_ids"] = _requirements(record, witness, children, domains, final)
            record["current_placement"] = final
            record["eligible_for_external_recursion"] = (
                final["accepted"]
                and final["eligible_for_external_recursion"]
                and not record["required_domain_ids"]
            )


def released_movement_snapshot(
    segments: list[XD],
    bars: list[Kline],
    macd: dict[str, list[float]],
    *,
    selection_policy: str = "earliest",
    _selector: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    _audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bottom-up same-level recursion with whole-domain cross-boundary parents.

    Base segments are the configured minimum input. Missing completed spans,
    endpoint/chronology breaks, and mixed-level gaps are never padded with fake
    movements. The selected interpretation contracts at every layer. A later
    snapshot may revise ownership; callers must retain earlier as-of snapshots.
    """
    if selection_policy not in POLICIES:
        raise ValueError("unknown research selection policy")
    input_rejections: list[dict[str, Any]] | None = [] if _audit is not None else None
    accepted = confirmed_segment_prefix(
        segments, len(bars), **({"audit": input_rejections} if _audit is not None else {})
    )
    if _audit is not None:
        _audit.update(
            accepted_segment_count=len(accepted),
            rejected_suffix_count=len(segments) - len(accepted),
            attempts=[],
            layers=[],
            input_rejections=input_rejections,
            chain_boundaries=[],
        )
    chains = [accepted] if accepted else []
    records: dict[int, dict[str, Any]] = {
        s.index: {
            "id": f"segment:{s.index}",
            "level": 0,
            "source_segment_indices": [s.index],
            "known_index": s.confirmed_index,
        }
        for s in accepted
    }
    all_records = {r["id"]: r for r in records.values()}
    domains: list[dict[str, Any]] = []
    levels: list[dict[str, Any]] = []
    structures: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    level = 1
    while chains:
        available = {s.index: s for chain in chains for s in chain}
        if level > 1:
            structures.append(recursive_structure_layer(chains, records, level - 1, namespace="R"))
            structures[-1]["scope"] = "centres_on_locally_completed_movements"
        for chain in chains:
            domains.extend(_ownership_domains(chain, records, level - 1))
        candidates = []
        layer_trace: list[dict[str, Any]] = []
        for chain in chains:
            trace: list[dict[str, Any]] | None = [] if _audit is not None else None
            local = [
                {**c, "kind": "trend"}
                for c in _candidates(
                    chain,
                    bars,
                    macd,
                    internal=True,
                    **({"trace": trace} if trace is not None else {}),
                )
            ]
            local += consolidation_candidates(
                chain, bars, macd, **({"trace": trace} if trace is not None else {})
            )
            if trace is not None:
                for row in trace:
                    row["level"] = level
                    row["source_first"] = records[row["start_unit_index"]][
                        "source_segment_indices"
                    ][0]
                    row["source_last"] = records[row["end_unit_index"]]["source_segment_indices"][
                        -1
                    ]
                layer_trace.extend(trace)
            for candidate in local:
                children = list(
                    range(candidate["start_unit_index"], candidate["end_unit_index"] + 1)
                )
                candidate = {
                    **candidate,
                    "level": level,
                    "source_segment_indices": _source(records, children),
                    "original_known_index": candidate["known_index"],
                    "child_ids": [records[i]["id"] for i in children],
                    "opposite_id": records[candidate["opposite_unit_index"]]["id"],
                }
                witness = records[candidate["opposite_unit_index"]]
                placement = _placement(candidate, witness, domains)
                required = _requirements(
                    candidate, witness, [records[i] for i in children], domains, placement
                )
                if not placement["accepted"]:
                    blocked.append(
                        {
                            "level": level,
                            "source_segment_indices": candidate["source_segment_indices"],
                            "original_known_index": candidate["original_known_index"],
                            **placement,
                        }
                    )
                # Preserve local geometry as conditional evidence. Discarding
                # it here would make complete cross-domain parents impossible;
                # neither this unit nor any parent may export unmet obligations.
                candidates.append(
                    {
                        **candidate,
                        "known_index": placement.get("known_index", candidate["known_index"]),
                        "ownership_check": placement,
                        "required_domain_ids": required,
                        "eligible_for_external_recursion": (
                            placement["accepted"]
                            and placement["eligible_for_external_recursion"]
                            and not required
                        ),
                    }
                )
        selected = (
            _selector(candidates)
            if _selector is not None
            else select_for_review(candidates, selection_policy)
        )
        if _audit is not None:
            for row in layer_trace:
                matches = [
                    c
                    for c in candidates
                    if c["kind"] == row["kind"]
                    and c["start_unit_index"] == row["start_unit_index"]
                    and c["end_unit_index"] == row["end_unit_index"]
                    and c["original_known_index"] == row.get("confirmed_index")
                ]
                if matches:
                    row["selection"] = (
                        "selected" if any(c in selected for c in matches) else "omitted"
                    )
                    row["ownership_checks"] = [deepcopy(c["ownership_check"]) for c in matches]
                    row["required_domain_ids"] = sorted(
                        {d for c in matches for d in c["required_domain_ids"]}
                    )
            _audit["attempts"].extend(layer_trace)
            _audit["layers"].append(
                {
                    "level": level,
                    "input_count": len(available),
                    "chain_count": len(chains),
                    "candidate_count": len(candidates),
                    "selected_count": len(selected),
                    "attempt_count": len(layer_trace),
                }
            )
        if not selected:
            break
        next_units, next_records = [], {}
        for ordinal, candidate in enumerate(selected):
            sources = candidate["source_segment_indices"]
            record = {
                **candidate,
                "id": f"released:{candidate['kind']}:M{level}:{sources[0]}:{sources[-1]}",
                "rule": RULE,
                "engineering_complete": True,
                "theory_equivalence_claim": False,
                "eligible_for_trading": False,
            }
            first = available[candidate["start_unit_index"]]
            last = available[candidate["end_unit_index"]]
            next_units.append(
                XD(
                    first.start,
                    last.end,
                    first.direction,
                    index=ordinal,
                    low=record["low"],
                    high=record["high"],
                    confirmed_index=record["known_index"],
                )
            )
            next_records[ordinal] = record
            all_records[record["id"]] = record
        covered = {
            i for c in selected for i in range(c["start_unit_index"], c["end_unit_index"] + 1)
        }
        levels.append(
            {
                "level": level,
                "input_count": len(available),
                "input_chain_count": len(chains),
                "types": list(next_records.values()),
                "unresolved_input_ids": [records[i]["id"] for i in available if i not in covered],
            }
        )
        # Crossing a former boundary is now allowed for a prospective parent,
        # but only _placement can release it after complete coverage is proven.
        chains = _chains(next_units, next_records)
        if _audit is not None:
            for left, right in zip(chains, chains[1:]):
                a, b = left[-1], right[0]
                first = next_records[a.index]["source_segment_indices"][-1]
                last = next_records[b.index]["source_segment_indices"][0]
                rejected: list[dict[str, Any]] = []
                confirmed_segment_prefix([a, b], audit=rejected)
                _audit["chain_boundaries"].append(
                    {
                        "level": level + 1,
                        "left_source": first,
                        "right_source": last,
                        "reason": "unresolved_source_gap"
                        if last != first + 1
                        else "source_chain_disconnected",
                        "input_rejections": rejected,
                        "effect": "all_cross_boundary_windows_not_evaluated",
                    }
                )
        records = next_records
        level += 1

    _finalize_placements(levels, all_records, domains)
    if _audit is not None:
        _audit["final_placements"] = [
            {
                "id": r["id"],
                "level": r["level"],
                "source_segment_indices": list(r["source_segment_indices"]),
                "current_placement": deepcopy(r["current_placement"]),
                "required_domain_ids": list(r["required_domain_ids"]),
            }
            for layer in levels
            for r in layer["types"]
        ]
    active: dict[str, dict[str, Any]] = {}
    for layer in levels:
        for record in layer["types"]:
            final = record["current_placement"]
            internal = final["accepted"] and set(record["required_domain_ids"]) <= set(
                final["enclosing_domain_ids"]
            )
            if not (record["eligible_for_external_recursion"] or internal):
                continue
            sources = set(record["source_segment_indices"])
            # A deferred parent must not hide legal lower completions. A later
            # eligible ancestor replaces every covered descendant, including
            # those beneath a deferred intermediate node absent from active.
            active = {
                identity: old
                for identity, old in active.items()
                if not sources.intersection(old["source_segment_indices"])
            }
            active[record["id"]] = record
    frontier = sorted(active, key=lambda identity: active[identity]["source_segment_indices"][0])
    external = [
        identity for identity in frontier if active[identity]["eligible_for_external_recursion"]
    ]
    pending = [identity for identity in frontier if identity not in external]
    closed_by = {
        owner: identity
        for identity in external
        for owner in active[identity]["current_placement"]["released_domain_ids"]
    }
    for domain in domains:
        domain["released_by_id"] = closed_by.get(domain["id"])
        domain["status"] = "released_by_parent" if domain["released_by_id"] else "retained"
    for record in all_records.values():
        if record["level"] > 0:
            record["on_frontier"] = record["id"] in active
            source = set(record["source_segment_indices"])
            record["represented_by_id"] = next(
                (
                    identity
                    for identity in frontier
                    if source <= set(active[identity]["source_segment_indices"])
                ),
                None,
            )
            if not record["on_frontier"]:
                record["eligible_for_external_recursion"] = False
    covered = {i for identity in frontier for i in all_records[identity]["source_segment_indices"]}
    by_source = {
        i: identity
        for identity in frontier
        for i in all_records[identity]["source_segment_indices"]
    }
    cover: list[SourceCover] = []
    for item in accepted:
        identity = by_source.get(item.index)
        if cover and cover[-1]["movement_id"] == identity:
            block = cover[-1]
            block["source_segment_indices"].append(item.index)
            block["end_index"] = extreme_index(item.end)
        else:
            movement = all_records.get(identity) if identity is not None else None
            cover.append(
                {
                    "movement_id": identity,
                    "status": (
                        "external_completed"
                        if identity in external
                        else "internal_completed"
                        if movement
                        else "unresolved"
                    ),
                    "level": movement["level"] if movement else 0,
                    "source_segment_indices": [item.index],
                    "start_index": extreme_index(item.start),
                    "end_index": extreme_index(item.end),
                }
            )
    return deepcopy(
        {
            "rule": RULE,
            "scope": "approved_whole_domain_release",
            "as_of_index": len(bars) - 1 if bars else None,
            "accepted_segment_count": len(accepted),
            "rejected_suffix_count": len(segments) - len(accepted),
            "levels": levels,
            "highest_completed_level": len(levels),
            "structure_layers": structures,
            "domains": domains,
            "blocked_candidates": blocked,
            "frontier_ids": frontier,
            "external_frontier_ids": external,
            "internal_frontier_ids": pending,
            "source_cover": cover,
            "highest_external_level": max((all_records[i]["level"] for i in external), default=0),
            "deferred_ids": [
                r["id"]
                for r in all_records.values()
                if r["level"] and r["represented_by_id"] is None
            ],
            "unresolved_segment_indices": [s.index for s in accepted if s.index not in covered],
            "theory_equivalence_claim": False,
            "natural_type_recursion_ready": False,
            "eligible_for_trading": False,
        }
    )
