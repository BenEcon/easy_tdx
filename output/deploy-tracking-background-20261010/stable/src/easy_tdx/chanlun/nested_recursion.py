"""Higher-input ownership, not promotion-as-completion or cross-owner joining."""

from copy import deepcopy
from typing import Any

from easy_tdx.chanlun.engineering_consolidations import consolidation_candidates
from easy_tdx.chanlun.ownership_conflicts import ownership_conflict
from easy_tdx.chanlun.types import XD, Kline

ScanResult = tuple[dict[int, list[dict[str, Any]]], list[dict[str, Any]]]
ScanKey = tuple[tuple[int, int, int, str, float, float, int | None], ...]


def _scan(items: list[XD], bars: list[Kline], macd: dict[str, list[float]]) -> ScanResult:
    from easy_tdx.chanlun.engineering_trends import _candidates
    from easy_tdx.chanlun.layered_ownership import _claim_events

    local = [{**c, "kind": "trend"} for c in _candidates(items, bars, macd, internal=True)]
    local += consolidation_candidates(items, bars, macd)
    return _claim_events(items), local


class _NestedScanCache:
    """Analysis-local geometric work only; never cache IDs or ownership decisions.

    All chains come from the same fixed base objects and chart series. Validated
    adapters only inspect bars through their own end anchors, so extra bars in
    later revisions cannot change a scan of identical confirmed inputs. Endpoint
    identity preserves the raw/merged anchor geometry used by validation.
    Detached results prevent a later revision or date annotation mutating another.
    """

    def __init__(self, bars: list[Kline], macd: dict[str, list[float]]) -> None:
        self.bars = bars
        self.macd = macd
        self.entries: dict[ScanKey, ScanResult] = {}

    def scan(self, items: list[XD]) -> ScanResult:
        key = tuple(
            (s.index, id(s.start), id(s.end), s.direction.value, s.low, s.high, s.confirmed_index)
            for s in items
        )
        if key not in self.entries:
            self.entries[key] = _scan(items, self.bars, self.macd)
        return deepcopy(self.entries[key])


def nested_candidates(
    items: list[XD],
    bars: list[Kline],
    macd: dict[str, list[float]],
    records: dict[int, dict[str, Any]],
    input_level: int,
    parent_id: str,
    *,
    scan_cache: _NestedScanCache | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    # Runtime imports keep the original interpreters independent and unchanged.
    from easy_tdx.chanlun.layered_ownership import _domains

    events, local = scan_cache.scan(items) if scan_cache is not None else _scan(items, bars, macd)
    claims: dict[str, dict[str, Any]] = {}
    admitted: dict[int, int] = {}
    active: list[dict[str, Any]] = []

    def identity(domain: dict[str, Any]) -> str:
        first = records[domain["sources"][0]]["source_segment_indices"][0]
        last = records[domain["sources"][-1]]["source_segment_indices"][-1]
        return f"{parent_id}/nested:M{input_level}:{first}:{last}:at:{domain['known_index']}"

    for known, batch in sorted(events.items()):
        for claim in batch:
            claims[claim["key"]] = claim
            for index in claim["sources"]:
                admitted.setdefault(index, known)
        next_active = []
        for domain in _domains(claims):
            source_set = set(domain["sources"])
            prior = [old for old in active if source_set.intersection(old["sources"])]
            domain["known_index"] = prior[0]["known_index"] if len(prior) == 1 else known
            domain["id"] = identity(domain)
            # Compact evidence only: retain actual creation/expansion/merge
            # batches, not repeated full snapshots or inferred completion.
            history = {event["id"]: event for old in prior for event in old["lifecycle_events"]}
            if not (len(prior) == 1 and prior[0]["id"] == domain["id"]):
                inherited = {i for old in prior for i in old["sources"]}
                history[domain["id"]] = {
                    "id": domain["id"],
                    "known_index": known,
                    "kind": "merged" if len(prior) > 1 else "expanded" if prior else "formed",
                    "previous_owner_ids": [old["id"] for old in prior],
                    "first_source_segment_index": records[domain["sources"][0]][
                        "source_segment_indices"
                    ][0],
                    "last_source_segment_index": records[domain["sources"][-1]][
                        "source_segment_indices"
                    ][-1],
                    "source_unit_count": len(source_set),
                    "added_unit_ids": [
                        records[i]["id"] for i in domain["sources"] if i not in inherited
                    ],
                }
            domain["lifecycle_events"] = sorted(
                history.values(),
                key=lambda event: (event["known_index"], event["first_source_segment_index"]),
            )
            next_active.append(domain)
        active = next_active

    owners = []
    for domain in active:
        sources = [s for i in domain["sources"] for s in records[i]["source_segment_indices"]]
        owner_id = domain["id"]
        admissions = []
        for index in domain["sources"]:
            effective = max(domain["known_index"], admitted[index])
            record = records[index]
            # Change current placement, not original completion or original ID.
            record["current_owner_id"] = owner_id
            record["current_owner_known_index"] = max(record["known_index"], effective)
            record["ownership_transfers"] = [
                *record.get("ownership_transfers", []),
                {
                    "from_owner_id": parent_id,
                    "to_owner_id": owner_id,
                    "known_index": effective,
                },
            ]
            admissions.append(
                {
                    "unit_id": record["id"],
                    "admitted_index": effective,
                    "unit_confirmed_index": record["known_index"],
                }
            )
        owners.append(
            {
                "id": owner_id,
                "parent_owner_id": parent_id,
                "input_level": input_level,
                "known_index": domain["known_index"],
                "source_segment_indices": sources,
                "source_unit_ids": [records[i]["id"] for i in domain["sources"]],
                "member_admissions": admissions,
                "lifecycle_events": domain["lifecycle_events"],
                "claim_kinds": sorted({claims[key]["kind"] for key in domain["claims"]}),
                "natural_type_complete": False,
                "eligible_for_external_recursion": False,
            }
        )

    candidates, blocked = [], []
    for candidate in local:
        indices = set(range(candidate["start_unit_index"], candidate["end_unit_index"] + 1))
        hits = [domain for domain in active if indices.intersection(domain["sources"])]
        if hits and (len(hits) != 1 or not indices.issubset(hits[0]["sources"])):
            blocked.append(
                {
                    "source_unit_ids": [records[i]["id"] for i in sorted(indices)],
                    "original_known_index": candidate["known_index"],
                    "reason": "crosses_current_ownership_boundary",
                    "ownership_conflict": ownership_conflict(
                        candidate, records, input_level, active
                    ),
                }
            )
            continue
        witness_owner = next(
            (d["id"] for d in active if candidate["opposite_unit_index"] in d["sources"]), None
        )
        if witness_owner is not None and (not hits or witness_owner != hits[0]["id"]):
            blocked.append(
                {
                    "source_unit_ids": [records[i]["id"] for i in sorted(indices)],
                    "original_known_index": candidate["known_index"],
                    "reason": "opposite_witness_owned_by_another_domain",
                    "ownership_conflict": ownership_conflict(
                        candidate, records, input_level, active
                    ),
                }
            )
            continue
        current_owner = hits[0]["id"] if hits else parent_id
        ownership_known = (
            max(hits[0]["known_index"], *(admitted[i] for i in indices))
            if hits
            else max(records[i].get("ownership_known_index", 0) for i in indices)
        )
        candidates.append(
            {
                **candidate,
                "original_known_index": candidate["known_index"],
                "ownership_known_index": ownership_known,
                "known_index": max(candidate["known_index"], ownership_known),
                "current_owner_id": current_owner,
            }
        )
    return candidates, deepcopy(owners), blocked
