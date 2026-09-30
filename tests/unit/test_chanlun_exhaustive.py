"""Independent powerset oracle and causal, signed continuation acceptance."""

from copy import deepcopy
from itertools import combinations

import pytest

from easy_tdx.chanlun.exhaustive_recursion import SubsetTraversal, exhaustive_leaf
from easy_tdx.chanlun.released_recursion import released_movement_snapshot
from easy_tdx.web.research_cursor import decode_cursor, encode_cursor
from easy_tdx.web.routers.chanlun_replay import (
    CandidateAuditRequest,
    ExhaustiveRequest,
    replay_candidate_audit,
    replay_exhaustive,
)
from tests.unit.test_chanlun_released_recursion import release_fixture
from tests.unit.test_chanlun_replay import snapshot


@pytest.mark.parametrize("mirror", [False, True])
def test_actual_engine_exhausts_every_leaf_with_independent_first_layer_count(mirror):
    from easy_tdx.chanlun.engineering_consolidations import consolidation_candidates
    from easy_tdx.chanlun.engineering_trends import _candidates

    inputs = release_fixture(mirror)
    local = _candidates(*inputs, internal=True) + consolidation_candidates(*inputs)
    independent = sum(
        all(
            a["end_unit_index"] < b["start_unit_index"]
            or b["end_unit_index"] < a["start_unit_index"]
            for a, b in combinations(group, 2)
        )
        for count in range(len(local) + 1)
        for group in combinations(local, count)
    )
    path, paths, snapshots, highest = [], set(), set(), {}
    while path is not None:
        leaf = exhaustive_leaf(*inputs, path, trace=True)
        assert tuple(leaf["path"]) not in paths
        paths.add(tuple(leaf["path"]))
        from easy_tdx.web.research_cursor import fingerprint

        identity = fingerprint(leaf["snapshot"])
        assert identity not in snapshots
        snapshots.add(identity)
        level = leaf["snapshot"]["highest_completed_level"]
        highest[level] = highest.get(level, 0) + 1
        cover = [i for r in leaf["snapshot"]["source_cover"] for i in r["source_segment_indices"]]
        assert len(cover) == len(set(cover)) == len(inputs[0])
        assert all(r["outcome"] != "not_evaluated" for r in leaf["audit"]["attempts"])
        path = leaf["next_path"]
    # Exactly one base interpretation has a higher-level choice (include/omit M2).
    assert independent == 216 and len(paths) == independent + 1
    assert highest == {2: 1, 1: 215, 0: 1}


def test_signed_api_batches_match_direct_enumeration_and_trace_exact_branch(monkeypatch):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from easy_tdx.web.routers import chanlun_replay as module

    inputs = release_fixture()
    monkeypatch.setattr(
        module,
        "_research_input",
        lambda req: (
            "fixed-test-snapshot",
            SimpleNamespace(xds=inputs[0], klines=inputs[1], macd=inputs[2]),
        ),
    )
    app = FastAPI()
    app.include_router(module.router)
    client = TestClient(app)
    req = ExhaustiveRequest(
        code="constructed", bars=snapshot(), visible_count=80, page_size=8
    ).model_dump(mode="json")
    cursor, count, token = None, 0, None
    while True:
        response = client.post("/chanlun/replay/exhaustive", json={**req, "cursor": cursor})
        assert response.status_code == 200
        data = response.json()
        assert [r["ordinal"] for r in data["results"]] == list(
            range(count + 1, data["emitted"] + 1)
        )
        count = data["emitted"]
        token = data["results"][-1]["solution_token"]
        cursor = data["next_cursor"]
        assert data["complete"] is (cursor is None)
        if data["complete"]:
            break
    assert count == 217
    audited = client.post("/chanlun/replay/candidate-audit", json={**req, "solution_token": token})
    assert audited.status_code == 200
    assert audited.json()["interpretation"] == "solution"
    assert all(r.get("selection") != "selected" for r in audited.json()["attempts"])
    assert (
        client.post("/chanlun/replay/exhaustive", json={**req, "cursor": token}).status_code == 422
    )
    assert (
        client.post(
            "/chanlun/replay/candidate-audit", json={**req, "solution_token": token + "x"}
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "spans",
    [
        [],
        [(0, 4)],
        [(0, 4), (5, 9)],
        [(0, 4), (0, 8), (5, 9), (10, 14)],
        [(0, 4), (0, 4), (2, 6), (7, 11)],
    ],
)
def test_all_disjoint_subsets_match_independent_powerset(spans):
    candidates = [
        {"id": i, "start_unit_index": a, "end_unit_index": b, "known_index": i}
        for i, (a, b) in enumerate(spans)
    ]
    expected = set()
    for count in range(len(candidates) + 1):
        for group in combinations(candidates, count):
            if all(
                a["end_unit_index"] < b["start_unit_index"]
                or b["end_unit_index"] < a["start_unit_index"]
                for a, b in combinations(group, 2)
            ):
                expected.add(tuple(sorted(c["id"] for c in group)))
    path, actual = [], []
    while path is not None:
        selector = SubsetTraversal(path)
        actual.append(tuple(sorted(c["id"] for c in selector(candidates))))
        path = selector.next_path()
    assert len(actual) == len(set(actual))
    assert set(actual) == expected


def test_dependent_second_layer_is_recomputed_for_every_first_layer_choice():
    def candidate(i):
        return {"id": i, "start_unit_index": i, "end_unit_index": i, "known_index": i}

    path, leaves = [], []
    while path is not None:
        selector = SubsetTraversal(path)
        first = selector([candidate(0), candidate(1)])
        second = selector([candidate(7), candidate(8)]) if len(first) == 2 else []
        leaves.append((tuple(x["id"] for x in first), tuple(x["id"] for x in second)))
        path = selector.next_path()
    assert set(leaves) == {
        ((0, 1), (7, 8)),
        ((0, 1), (7,)),
        ((0, 1), (8,)),
        ((0, 1), ()),
        ((0,), ()),
        ((1,), ()),
        ((), ()),
    }
    assert len(leaves) == 7


@pytest.mark.parametrize("mirror", [False, True])
def test_real_engine_search_starts_with_default_and_resumes_without_mutation(mirror):
    inputs = release_fixture(mirror)
    first = exhaustive_leaf(*inputs, trace=True)
    assert first["snapshot"] == released_movement_snapshot(*inputs)
    saved = deepcopy(first)
    second = exhaustive_leaf(*inputs, first["next_path"], trace=True)
    assert second["path"] != first["path"]
    assert first == saved
    assert exhaustive_leaf(*inputs, first["path"])["snapshot"] == first["snapshot"]
    assert all(row["outcome"] != "not_evaluated" for row in first["audit"]["attempts"])


def test_invalid_paths_are_rejected():
    for path in [[True], [2], ["1"], [-1]]:
        with pytest.raises(ValueError):
            SubsetTraversal(path)
    selector = SubsetTraversal([1])
    selector([])
    with pytest.raises(ValueError):
        selector.next_path()


def test_checkpoints_are_signed_and_bound_to_snapshot_and_purpose():
    token = encode_cursor({"kind": "search", "fingerprint": "a", "path": [1, 0], "emitted": 3})
    assert decode_cursor(token, "a", "search")["path"] == [1, 0]
    for damaged, identity, kind in [
        (token + "x", "a", "search"),
        (token, "b", "search"),
        (token, "a", "solution"),
        ("invalid", "a", "search"),
    ]:
        with pytest.raises(ValueError):
            decode_cursor(damaged, identity, kind)


def test_real_ohlc_empty_candidate_search_completes_and_audit_is_pageable():
    req = ExhaustiveRequest(code="test", bars=snapshot(), visible_count=80)
    result = replay_exhaustive(req)
    assert result["complete"] is True and result["next_cursor"] is None
    assert result["emitted"] == len(result["results"]) == 1
    token = result["results"][0]["solution_token"]
    audit = replay_candidate_audit(
        CandidateAuditRequest(
            code=req.code, bars=req.bars, visible_count=80, solution_token=token, limit=1
        )
    )
    assert audit["fingerprint"] == result["fingerprint"]
    assert audit["interpretation"] == "solution"
    assert len(audit["attempts"]) <= 1


def test_future_rows_do_not_affect_search_identity_or_audit():
    bars = snapshot()
    before = replay_exhaustive(ExhaustiveRequest(code="test", bars=bars, visible_count=40))
    for row in bars[40:]:
        for key in ("open", "high", "low", "close"):
            row[key] *= 200
    after = replay_exhaustive(ExhaustiveRequest(code="test", bars=bars, visible_count=40))
    assert after == before
