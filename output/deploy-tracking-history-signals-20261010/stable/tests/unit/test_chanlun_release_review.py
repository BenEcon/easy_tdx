"""Research selections never replace defaults; history rebuilds raw prefixes."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from easy_tdx.chanlun.engineering_trends import _select_owned_candidates
from easy_tdx.chanlun.release_review import (
    POLICIES,
    review_changes,
    review_state,
    select_for_review,
)
from easy_tdx.chanlun.released_recursion import released_movement_snapshot
from easy_tdx.web.routers.chanlun_replay import (
    ReleaseHistoryRequest,
    ReplayRequest,
    _release_prefix,
    replay_release_comparison,
    replay_release_history,
)
from tests.unit.test_chanlun_released_frontend import verify
from tests.unit.test_chanlun_released_recursion import release_fixture
from tests.unit.test_chanlun_replay import snapshot


def test_selection_alternatives_and_default_equivalence():
    candidates = [
        dict(start_unit_index=0, end_unit_index=4, known_index=10),
        dict(start_unit_index=0, end_unit_index=8, known_index=20),
        dict(start_unit_index=5, end_unit_index=9, known_index=30),
    ]
    saved = deepcopy(candidates)
    assert select_for_review(candidates, "earliest") == _select_owned_candidates(candidates)
    assert select_for_review(candidates, "widest") == [candidates[1]]
    assert select_for_review(candidates, "latest") == [candidates[0], candidates[2]]
    assert candidates == saved
    with pytest.raises(ValueError):
        select_for_review(candidates, "invented")


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("policy", POLICIES)
def test_research_recursion_still_passes_actual_source_guard(policy, mirror):
    fixture = release_fixture(mirror)
    data = released_movement_snapshot(*fixture, selection_policy=policy)
    verify(data, len(fixture[1]))
    assert data["eligible_for_trading"] is False
    if policy == "earliest":
        assert data == released_movement_snapshot(*fixture)


def test_history_compact_diff_preserves_before_and_after():
    data = released_movement_snapshot(*release_fixture())
    state = review_state(data)
    changes = review_changes({}, state, 310, "2026-01-01")
    assert changes and all(c["change"] == "added" and c["before"] is None for c in changes)
    assert review_changes(state, deepcopy(state), 311, "2026-01-02") == []
    removed = review_changes(state, {}, 312, "2026-01-03")
    assert all(c["change"] == "removed" and c["after"] is None for c in removed)
    state[next(iter(state))]["source_segment_indices"].clear()
    assert all(r["source_segment_indices"] for layer in data["levels"] for r in layer["types"])


def test_history_batches_equal_independent_raw_prefix_rebuild():
    rows = snapshot()
    req = ReleaseHistoryRequest(code="test", bars=rows, start_count=30, visible_count=49)
    actual = replay_release_history(req)
    before = review_state(_release_prefix(req, 29))
    expected = []
    for n in range(30, 50):
        after = review_state(_release_prefix(req, n))
        date = req.bars[n - 1].datetime.isoformat(sep=" ")
        expected += review_changes(before, after, n - 1, date)
        before = after
    assert actual["events"] == expected
    a = replay_release_history(req.model_copy(update={"visible_count": 39}))
    b = replay_release_history(req.model_copy(update={"start_count": 40}))
    assert a["events"] + b["events"] == actual["events"]


def test_history_never_passes_future_rows_to_analyser(monkeypatch):
    from easy_tdx.web.routers import chanlun_replay as module

    original = module.ChanlunAnalyser.process_klines
    sizes = []

    def checked(self, frame):
        sizes.append(len(frame))
        return original(self, frame)

    monkeypatch.setattr(module.ChanlunAnalyser, "process_klines", checked)
    replay_release_history(
        ReleaseHistoryRequest(code="test", bars=snapshot(), start_count=20, visible_count=23)
    )
    assert sizes == [19, 20, 21, 22, 23]


def test_history_observes_real_engine_release_at_its_prefix_not_before(monkeypatch):
    from easy_tdx.web.routers import chanlun_replay as module

    items, bars, macd = release_fixture()
    completed = released_movement_snapshot(items, bars, macd)
    confirmation = completed["levels"][-1]["types"][0]["known_index"]

    def prefix(req, count):
        return released_movement_snapshot(
            items, bars[:count], {k: v[:count] for k, v in macd.items()}
        )

    # Isolate timeline transport with actual engine prefixes. Raw-OHLC boundary
    # and frozen-market coverage are tested separately, not claimed by this fixture.
    monkeypatch.setattr(module, "_release_prefix", prefix)
    request = ReleaseHistoryRequest(
        code="constructed",
        bars=snapshot(len(bars)),
        start_count=confirmation,
        visible_count=confirmation + 2,
    )
    events = replay_release_history(request)["events"]
    released = [
        e for e in events if e["after"] and e["after"].get("status") == "released_by_parent"
    ]
    assert released and all(e["index"] >= confirmation for e in released)
    assert any(e["before"] and e["before"].get("status") == "retained" for e in released)


@pytest.mark.parametrize("start,end", [(0, 10), (2, 1), (1, 41), (40, 81)])
def test_history_batch_bounds(start, end):
    with pytest.raises(ValidationError):
        ReleaseHistoryRequest(code="test", bars=snapshot(), start_count=start, visible_count=end)


def test_future_price_mutation_cannot_change_research_or_history():
    rows = snapshot()
    req = ReplayRequest(code="test", bars=rows, visible_count=30)
    expected = replay_release_comparison(req)
    history = replay_release_history(ReleaseHistoryRequest(**req.model_dump(), start_count=20))
    for bar in rows[30:]:
        for key in ("open", "high", "low", "close"):
            bar[key] *= 100
    later = ReplayRequest(code="test", bars=rows, visible_count=30)
    assert replay_release_comparison(later) == expected
    later_history = ReleaseHistoryRequest(**later.model_dump(), start_count=20)
    assert replay_release_history(later_history) == history
    assert expected["exhaustive"] is False and expected["default_policy"] == "earliest"


def test_research_routes_registered_and_bounded():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from easy_tdx.web.routers.chanlun import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)
    body = ReplayRequest(code="test", bars=snapshot(), visible_count=20).model_dump(mode="json")
    assert client.post("/api/v1/chanlun/replay/release-comparison", json=body).status_code == 200
    path = "/api/v1/chanlun/replay/release-history"
    assert client.post(path, json={**body, "start_count": 1}).status_code == 200
    assert client.post(path, json={**body, "start_count": 21}).status_code == 422
