"""Detached, as-of range evidence for an already rejected candidate.

This describes the decision; it must never participate in selection, version
signatures or completion. Ranges avoid inventing IDs for foreign root versions.
"""

from copy import deepcopy
from typing import Any


def ownership_conflict(
    candidate: dict[str, Any],
    records: dict[int, dict[str, Any]],
    input_level: int,
    domains: list[dict[str, Any]],
) -> dict[str, Any]:
    indices = set(range(candidate["start_unit_index"], candidate["end_unit_index"] + 1))
    witness_index = candidate["opposite_unit_index"]

    def sources(indices: list[int]) -> list[int]:
        return [source for index in indices for source in records[index]["source_segment_indices"]]

    witness = records[witness_index]
    witness_domain = next(
        (domain for domain in domains if witness_index in domain["sources"]), None
    )
    return deepcopy(
        {
            "input_level": input_level,
            "source_segment_indices": sources(sorted(indices)),
            "source_domains": [
                sources(domain["sources"])
                for domain in domains
                if indices.intersection(domain["sources"])
            ],
            "opposite": {
                "unit_id": witness["id"],
                "source_segment_indices": witness["source_segment_indices"],
                "known_index": witness["known_index"],
                "owner_source_segment_indices": (
                    sources(witness_domain["sources"]) if witness_domain else None
                ),
            },
        }
    )
