"""Conflict details describe an immutable decision; they never change its gates."""

from copy import deepcopy
from importlib import import_module

import pytest

from easy_tdx.chanlun.nested_recursion import nested_candidates
from tests.unit.test_chanlun_engineering_movements import CONSOLIDATION
from tests.unit.test_chanlun_nested_ownership import current, records_for, run
from tests.unit.test_chanlun_owner_witness import install_base_claims
from tests.unit.test_chanlun_signal_levels import fixture


@pytest.mark.parametrize("fault", ["partial", "witness"])
@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("offset", [0, 37])
def test_nested_conflicts_name_exact_sources_and_separate_reverse_evidence(
    monkeypatch, fault, mirror, offset
):
    items, bars, macd = fixture(CONSOLIDATION, 0, 4, mirror)
    for item in items:
        item.index += offset
    source = [offset + 2, offset + 3] if fault == "partial" else list(range(offset, offset + 5))
    claims = [{"key": "a", "kind": "expansion", "sources": source}]
    if fault == "witness":
        claims.append({"key": "b", "kind": "expansion", "sources": [offset + 5]})
    module = import_module("easy_tdx.chanlun.layered_ownership")
    monkeypatch.setattr(module, "_claim_events", lambda _: {125: claims})
    records = records_for(items)
    candidates, owners, blocked = nested_candidates(items, bars, macd, records, 1, "root")
    assert not candidates
    detail = blocked[0]["ownership_conflict"]
    assert detail == {
        "input_level": 1,
        "source_segment_indices": list(range(offset, offset + 5)),
        "source_domains": [source],
        "opposite": {
            "unit_id": f"input:{offset + 5}",
            "source_segment_indices": [offset + 5],
            "known_index": 125,
            "owner_source_segment_indices": [offset + 5] if fault == "witness" else None,
        },
    }
    before = deepcopy((records, owners))
    detail["opposite"]["source_segment_indices"].clear()
    detail["source_domains"][0].clear()
    assert (records, owners) == before


@pytest.mark.parametrize("mirror", [False, True])
def test_later_foreign_expansion_does_not_rewrite_an_unchanged_owner_or_its_evidence(
    monkeypatch, mirror
):
    items, bars, macd = fixture(CONSOLIDATION + [22, 27, 21, 25], 0, 4, mirror)
    install_base_claims(monkeypatch, items)
    module = import_module("easy_tdx.chanlun.layered_ownership")
    original = module._claim_events

    def claims(chain):
        events = original(chain)
        if chain and chain[0] is items[0] and 140 in events:
            events[140] = [{"key": "b", "kind": "expansion", "sources": list(range(5, 9))}]
        return events

    monkeypatch.setattr(module, "_claim_events", claims)
    before = current(run(items, bars[:136], macd))[0]
    later = current(run(items, bars[:141], macd))[0]
    assert later == before
    assert later["known_index"] == 135
    assert later["blocked_ownership_candidates"][0]["ownership_conflict"]["opposite"][
        "owner_source_segment_indices"
    ] == [5, 6, 7]
    assert current(run(items, bars[:141], macd))[1]["source_segment_indices"] == [5, 6, 7, 8]
