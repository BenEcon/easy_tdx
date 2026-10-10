"""Causal trend-only and mixed recursion under approved engineering rules.

This is NOT a complete natural Chan decomposition. The preserved trend-only
view excludes consolidations; the separate mixed view accepts the approved
single-centre closure. Regrouped centres remain incomplete in both views.
Missing spans split recursive input chains.
MACD uses the original chart series, measured over the current level's A/C spans;
it is not a resampled higher-timeframe indicator or a proof of theory equivalence.
"""

from __future__ import annotations

from bisect import bisect_left
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from easy_tdx.chanlun import candidate_audit as audit
from easy_tdx.chanlun.anchors import extreme_index
from easy_tdx.chanlun.divergence_signals import segment_evidence
from easy_tdx.chanlun.engineering_consolidations import (
    conflict_member_times,
    consolidation_candidates,
)
from easy_tdx.chanlun.expansion_regrouping import _endpoint_checks
from easy_tdx.chanlun.extension_recursion import centre_extension_proof, promoted_member_times
from easy_tdx.chanlun.recursive_structure import recursive_structure_layer
from easy_tdx.chanlun.structure import (
    StructuralCentre,
    confirmed_segment_prefix,
    iter_structural_steps,
)
from easy_tdx.chanlun.types import XD, Kline

if TYPE_CHECKING:
    from easy_tdx.chanlun.nested_recursion import _NestedScanCache

RULE = "approved_macd_reverse_v2"
MOVEMENT_RULE = "approved_mixed_macd_reverse_v1"


def _candidates(
    items: list[XD],
    bars: list[Kline],
    macd: dict[str, list[float]],
    *,
    internal: bool = False,
    trace: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Scan possible starts, freezing evidence at the opposite-unit confirmation.

    A same-time upgrade/overlap invalidates the entire confirmation batch. Later
    upgrades never retrospectively erase an earlier engineering completion.
    """
    if not all(macd.get(key) for key in ("dif", "dea", "hist")):
        for start, first in enumerate(items) if trace is not None else ():
            audit.pruned(
                trace, "trend", first, items[start:], "macd_series_missing", first.confirmed_index
            )
        return []
    lookup = {s.index: s for s in items}
    candidates: list[dict[str, Any]] = []
    for start, first in enumerate(items):
        centres: list[StructuralCentre] = []
        pending: dict[str, Any] | None = None
        pending_row: dict[str, Any] | None = None
        found_rows: list[dict[str, Any] | None] = []
        found: list[dict[str, Any]] = []
        invalid_at = None
        terminal_at = None
        low, high = first.low, first.high
        for current, centre, _ in iter_structural_steps(items[start:]):
            assert current.confirmed_index is not None  # iter_structural_steps validates it.
            if terminal_at is not None and current.confirmed_index > terminal_at:
                audit.pruned(
                    trace,
                    "trend",
                    first,
                    [s for s in items if s.index >= current.index],
                    "start_extreme_irrecoverable",
                    terminal_at,
                )
                break
            row = audit.attempt(trace, "trend", first, current)
            low, high = min(low, current.low), max(high, current.high)
            if centre is not None:
                if not centres or centres[-1] is not centre:
                    centres.append(centre)
                promoted = (
                    len(centre.member_segments) >= 9
                    and centre_extension_proof(centre, lookup) is not None
                )
                separated = len(centres) < 2 or (
                    centre.dd > centres[-2].gg
                    if first.direction.value == "up"
                    else centre.gg < centres[-2].dd
                )
                if promoted or not separated:
                    invalid_at = current.confirmed_index
                    audit.decision(
                        row,
                        "centre_upgraded" if promoted else "centres_not_separated",
                        centre_count=len(centres),
                        zd=centre.zd,
                        zg=centre.zg,
                    )
                    audit.invalidate([*found_rows, pending_row], invalid_at)
                    audit.pruned(
                        trace,
                        "trend",
                        first,
                        [s for s in items if s.index > current.index],
                        "invalidated_start_suffix",
                        invalid_at,
                    )
                    break
            if pending is not None:
                if current.direction != first.direction:
                    found.append(
                        {
                            **pending,
                            "known_index": current.confirmed_index,
                            "opposite_unit_index": current.index,
                            "opposite_start_index": extreme_index(current.start),
                            "opposite_end_index": extreme_index(current.end),
                        }
                    )
                    audit.confirmed(pending_row, current)
                    found_rows.append(pending_row)
                else:
                    audit.decision(pending_row, "next_unit_not_opposite", unit_index=current.index)
                pending = None
                pending_row = None
            # Once the start ceases to be the directional extreme no longer
            # prefix can restore it. A pending prior end was handled above.
            start_ok = _endpoint_checks(
                {
                    "start_value": first.start.val,
                    "end_value": current.end.val,
                    "direction": first.direction.value,
                    "low": low,
                    "high": high,
                }
            )[2]
            if not start_ok:
                terminal_at = current.confirmed_index
                audit.decision(
                    row,
                    "start_not_directional_extreme",
                    start_value=first.start.val,
                    low=low,
                    high=high,
                )
                continue
            if (
                len(centres) < 2
                or centre is None
                or centre.state != "departed"
                or centre.departure_segment != current.index
                or current.direction != first.direction
            ):
                audit.decision(
                    row,
                    "structure_gates_not_met",
                    centre_count=len(centres),
                    two_centres=len(centres) >= 2,
                    centre_departed=centre is not None and centre.state == "departed",
                    current_is_departure=(
                        centre is not None and centre.departure_segment == current.index
                    ),
                    same_direction=current.direction == first.direction,
                )
                continue
            geometry = {
                "start_value": first.start.val,
                "end_value": current.end.val,
                "direction": first.direction.value,
                "low": low,
                "high": high,
            }
            if not all(_endpoint_checks(geometry)[2:]):
                audit.decision(row, "end_not_directional_extreme", **geometry)
                continue
            entry = lookup.get(centre.seed_segments[0] - 1)
            if entry is None or entry.direction != current.direction:
                audit.decision(
                    row, "missing_matching_entry", expected_entry_index=centre.seed_segments[0] - 1
                )
                continue
            evidence = segment_evidence(
                bars,
                macd,
                (extreme_index(entry.start), extreme_index(entry.end)),
                (extreme_index(current.start), extreme_index(current.end)),
                current.direction.value,
                **({"audit": row["macd_checks"]} if row is not None else {}),
            )
            if evidence is None:
                audit.decision(row, "macd_gates_not_met")
                continue
            pending = {
                **geometry,
                "start_unit_index": first.index,
                "end_unit_index": current.index,
                "start_index": extreme_index(first.start),
                "end_index": extreme_index(current.end),
                "divergence_known_index": current.confirmed_index,
                "a_unit_index": entry.index,
                "c_unit_index": current.index,
                "macd_evidence": evidence,
                "centres": [
                    {
                        "source_unit_indices": list(c.member_segments),
                        "zd": c.zd,
                        "zg": c.zg,
                        "low": c.dd,
                        "high": c.gg,
                        "formed_index": c.formed_index,
                    }
                    for c in centres
                ],
            }
            pending_row = row
            audit.pending(row, evidence)
        candidates.extend(c for c in found if invalid_at is None or c["known_index"] < invalid_at)
    # Re-starting a local partition must not downgrade an already proven centre
    # from the original chain, including members admitted AFTER the first nine
    # proof sources. Check actual ownership time, not final membership alone.
    # Only the separate ownership interpreter may collect local evidence. Its
    # caller must quarantine it inside a causal owner; normal recursion keeps
    # the original guard. Local centre/endpoint/MACD gates above still apply.
    if internal:
        return candidates
    protected = promoted_member_times(items)
    retained = [
        c
        for c in candidates
        if not any(
            known <= c["known_index"] and c["start_unit_index"] <= index <= c["end_unit_index"]
            for index, known in protected.items()
        )
    ]
    if trace is not None:
        keys = {(c["start_unit_index"], c["end_unit_index"], c["known_index"]) for c in retained}
        for row in trace:
            if (
                row["outcome"] == "candidate"
                and (row["start_unit_index"], row["end_unit_index"], row["confirmed_index"])
                not in keys
            ):
                audit.decision(row, "protected_promoted_sources")
    return retained


def _chains(
    units: list[XD], records: dict[int, dict[str, Any]], *, respect_ownership: bool = False
) -> list[list[XD]]:
    chains: list[list[XD]] = []
    for unit in units:
        previous = chains[-1][-1] if chains else None
        contiguous = previous is not None and (
            records[previous.index]["source_segment_indices"][-1] + 1
            == records[unit.index]["source_segment_indices"][0]
        )
        if previous is not None and contiguous and respect_ownership:
            contiguous = records[previous.index].get("current_owner_id") == records[unit.index].get(
                "current_owner_id"
            )
        if (
            previous is None
            or not contiguous
            or len(confirmed_segment_prefix([previous, unit])) != 2
        ):
            chains.append([])
        chains[-1].append(unit)
    return chains


def engineering_trend_hierarchy(
    segments: list[XD], bars: list[Kline], macd: dict[str, list[float]]
) -> dict[str, Any]:
    """Preserved trend-only interpretation for comparison and compatibility."""
    return _hierarchy(segments, bars, macd, mixed=False)


def engineering_movement_hierarchy(
    segments: list[XD], bars: list[Kline], macd: dict[str, list[float]]
) -> dict[str, Any]:
    """Separate approved trend/consolidation interpretation; no trading export."""
    return _hierarchy(segments, bars, macd, mixed=True)


def _select_owned_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prioritize availability, reject actual overlap, then restore spatial order.

    Admission can delay an earlier span beyond its right-hand neighbours. A
    single last-end cursor would silently drop that disjoint span. Selection
    does not authorize joining it: _chains still checks time and ownership.
    """
    starts: list[int] = []
    selected: list[dict[str, Any]] = []
    for candidate in sorted(
        candidates, key=lambda c: (c["known_index"], c["start_unit_index"], c["end_unit_index"])
    ):
        start, end = candidate["start_unit_index"], candidate["end_unit_index"]
        position = bisect_left(starts, start)
        if (position and selected[position - 1]["end_unit_index"] >= start) or (
            position < len(starts) and starts[position] <= end
        ):
            continue
        starts.insert(position, start)
        selected.insert(position, candidate)
    return selected


def _hierarchy(
    segments: list[XD],
    bars: list[Kline],
    macd: dict[str, list[float]],
    *,
    mixed: bool,
    internal_seed: list[dict[str, Any]] | None = None,
    owner_id: str | None = None,
    nested: bool = False,
    scan_cache: _NestedScanCache | None = None,
) -> dict[str, Any]:
    """Recurse through disjoint types permitted by the selected interpretation.

    Earliest confirmation wins; equal-time ties prefer earliest spatial start,
    then shortest end. This is a deterministic engineering interpretation, not
    an assertion of unique natural decomposition. Each level strictly contracts.
    """
    accepted = confirmed_segment_prefix(segments, len(bars))
    chains = [accepted] if accepted else []
    records: dict[int, dict[str, Any]] = {
        s.index: {"id": f"segment:{s.index}", "source_segment_indices": [s.index]} for s in accepted
    }
    levels = []
    structure_layers = []
    nested_owners, blocked_candidates = [], []
    level = 1
    while chains:
        # Keep the last observable structural layer even when no next trend
        # completes. Never mix separate chains or import unresolved base spans.
        if level > 1:
            structure_layers.append(
                recursive_structure_layer(
                    chains, records, level - 1, namespace="M" if mixed else "T"
                )
            )
            if mixed:
                structure_layers[-1]["scope"] = "centres_on_completed_engineering_movements"
        available = {s.index: s for chain in chains for s in chain}
        candidates = []
        for chain in chains:
            if level == 1 and internal_seed is not None:
                candidates.extend(deepcopy(internal_seed))
                continue
            if nested and owner_id is not None and level > 1:
                from easy_tdx.chanlun.nested_recursion import nested_candidates

                parent_id = records[chain[0].index].get("current_owner_id", owner_id)
                current, owners, blocked = nested_candidates(
                    chain, bars, macd, records, level - 1, parent_id, scan_cache=scan_cache
                )
                candidates.extend(current)
                nested_owners.extend(owners)
                blocked_candidates.extend(blocked)
                continue
            current = _candidates(chain, bars, macd)
            if mixed:
                current = [{**c, "kind": "trend"} for c in current]
                current.extend(consolidation_candidates(chain, bars, macd))
                protected = conflict_member_times(chain)
                current = [
                    c
                    for c in current
                    if not any(
                        known <= c["known_index"]
                        and c["start_unit_index"] <= index <= c["end_unit_index"]
                        for index, known in protected.items()
                    )
                ]
            candidates.extend(current)
        if nested and owner_id is not None:
            selected = _select_owned_candidates(candidates)
        else:
            # Preserve the older T/M and first-generation ownership views.
            candidates.sort(
                key=lambda c: (c["known_index"], c["start_unit_index"], c["end_unit_index"])
            )
            selected = []
            last_end = -1
            for candidate in candidates:
                if candidate["start_unit_index"] <= last_end:
                    continue
                selected.append(candidate)
                last_end = candidate["end_unit_index"]
        if not selected:
            break
        next_units, next_records = [], {}
        for ordinal, candidate in enumerate(selected):
            children = list(range(candidate["start_unit_index"], candidate["end_unit_index"] + 1))
            sources = [i for child in children for i in records[child]["source_segment_indices"]]
            record = {
                **candidate,
                "id": f"trend:L{level}:{sources[0]}:{sources[-1]}",
                "level": level,
                "kind": "trend",
                "rule": RULE,
                "engineering_complete": True,
                "theory_equivalence_claim": False,
                "eligible_for_trend_recursion": True,
                "source_segment_indices": sources,
                "child_ids": [records[i]["id"] for i in children],
                "opposite_id": records[candidate["opposite_unit_index"]]["id"],
            }
            if mixed:
                record.update(
                    {
                        "id": f"movement:{candidate['kind']}:L{level}:{sources[0]}:{sources[-1]}",
                        "kind": candidate["kind"],
                        "rule": MOVEMENT_RULE,
                        "eligible_for_trend_recursion": False,
                        "eligible_for_movement_recursion": True,
                    }
                )
            if owner_id is not None:
                context = candidate.get("current_owner_id", owner_id)
                record.update(
                    {
                        "id": f"{context}/{record['id']}",
                        "owner_id": context,
                        "eligible_for_movement_recursion": False,
                        "eligible_for_internal_recursion": True,
                        "eligible_for_external_recursion": False,
                    }
                )
                if nested:
                    record["current_owner_id"] = context
                    record["current_owner_known_index"] = record["known_index"]
            first, last = available[children[0]], available[children[-1]]
            # Internal geometry adapter only: never exported as a base XD/pen.
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
        chains = _chains(next_units, next_records, respect_ownership=nested)
        records = next_records
        level += 1
    result = {
        "rule": RULE,
        "scope": "engineering_trends_only",
        "macd_basis": "original_series_current_level_leg_spans",
        "selection_policy": "earliest_confirmation_then_start_then_end",
        "promotion_scope": "all_admitted_members_at_candidate_confirmation",
        "natural_type_recursion_ready": False,
        "accepted_segment_count": len(accepted),
        "rejected_suffix_count": len(segments) - len(accepted),
        "highest_completed_trend_level": len(levels),
        "levels": levels,
        "structure_layers": structure_layers,
        "remaining_input_ids": [records[s.index]["id"] for chain in chains for s in chain],
        "blocking_scopes": [
            "consolidation_completion",
            "expansion_regrouping_completion",
            "mixed_type_natural_decomposition",
        ],
    }
    if mixed:
        result.update(
            {
                "rule": MOVEMENT_RULE,
                "scope": "engineering_mixed_movements",
                "highest_completed_movement_level": result.pop("highest_completed_trend_level"),
                "conflict_policy": "original_chain_promotion_and_expansion_at_confirmation",
                "blocking_scopes": [
                    "expansion_regrouping_completion",
                    "full_natural_decomposition",
                ],
            }
        )
    if nested:
        result["nested_owners"] = nested_owners
        result["blocked_ownership_candidates"] = blocked_candidates
    # Internal seeds were detached on entry; every later scan returns fresh
    # evidence (including cache hits). Records and provenance are built here,
    # with no mutable references to the caller's inputs or another revision.
    # Transfer this owned tree to the version builder instead of copying each
    # revision again. layered_movement_ownership still detaches its final output.
    # Preserve the independent public T/M interpreters' original copy boundary.
    return result if internal_seed is not None else deepcopy(result)
