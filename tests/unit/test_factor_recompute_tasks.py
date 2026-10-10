"""Explicit frozen archive replay uses the existing isolated task control plane."""

import copy
import json
import time
from dataclasses import replace
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest

from easy_tdx.progress import progress_scope
from easy_tdx.web import research_archive, task_store
from easy_tdx.web.factor_archive import validate_factor_archive
from easy_tdx.web.research_archive import ArchiveLimits, ResearchArchive, encode_archive
from easy_tdx.web.routers import auth, research
from easy_tdx.web.task_dispatch import dispatch_task
from easy_tdx.web.task_payload import TaskInput
from easy_tdx.web.task_runner import BacktestTaskRunner
from easy_tdx.web.task_store import TaskStore
from easy_tdx.web.task_supervisor import TaskSupervisor
from easy_tdx.web.user_activity import get_activity_store
from tests.unit.test_factor_series_tasks import site, value  # noqa: F401
from tests.unit.test_factor_tasks import round_trip

URL = "/api/v1/research/factors/recompute/async"


@pytest.fixture(params=["series", "multi-horizon"])
def replay(request):
    payload = json.loads(
        (Path(__file__).parents[1] / f"fixtures/factor_archive/{request.param}.json").read_text()
    )
    _, digest = encode_archive("factor", payload, ArchiveLimits().object_bytes)
    key = str(uuid4())
    record = {"id": key, "revision": 1, "digest": digest, "payload": payload}
    return TaskInput(
        "factor_recompute",
        "test-v1",
        {"source_archive_id": key, "expected_digest": digest, "expected_revision": 1},
        (),
        {"record": record},
    )


def test_replay_task_matches_sync_preserves_source_and_lineage_without_lookup(replay, monkeypatch):
    source = copy.deepcopy(replay.context["record"])
    expected = research.recompute_factor_payload(source)
    monkeypatch.setattr(
        research_archive, "get_research_archive", lambda: pytest.fail("no re-fetch")
    )
    events = []
    with progress_scope(events.append):
        actual = dispatch_task(round_trip(replay))
    validate_factor_archive(actual)
    assert actual["savedAt"]
    actual["savedAt"] = expected["savedAt"]
    assert actual == expected
    assert replay.context["record"] == source
    assert (
        actual["recomputed_from"]["original_definitions"]
        == source["payload"]["result"]["factor_definitions"]
    )
    assert events[-1]["phase"] == "result_validation" and events[-1]["completed"] == 1


@pytest.mark.parametrize(
    "bad", ["digest", "revision", "id", "payload", "extra", "missing", "frames"]
)
def test_replay_frozen_identity_or_content_mismatch_rejected_before_execution(
    replay,
    value,  # noqa: F811 - imported pytest fixture
    monkeypatch,
    bad,
):
    request, context = copy.deepcopy(replay.request), copy.deepcopy(replay.context)
    frames = ()
    if bad == "digest":
        context["record"]["digest"] = "0" * 64
    elif bad == "revision":
        context["record"]["revision"] = True
    elif bad == "id":
        context["record"]["id"] = str(uuid4())
    elif bad == "payload":
        context["record"]["payload"]["title"] = "altered after capture"
    elif bad == "extra":
        request["extra"] = 1
    elif bad == "missing":
        request.pop("expected_revision")
    else:
        frames = value.frames
    monkeypatch.setattr(
        research, "recompute_factor_payload", lambda *a: pytest.fail("must reject first")
    )
    with pytest.raises(ValueError):
        dispatch_task(replace(replay, request=request, context=context, frames=frames))


def test_replay_endpoint_captures_expected_owned_revision_and_excludes_automatic_activity(
    site,  # noqa: F811 - imported pytest fixture
    replay,
    tmp_path,
    monkeypatch,
):
    client, accounts, alice, bob, _ = site
    store = ResearchArchive(tmp_path / "archives.db")
    monkeypatch.setattr(research_archive, "get_research_archive", lambda: store)
    key = replay.request["source_archive_id"]
    store.create(alice.id, key, "factor", replay.context["record"]["payload"], "原档", "")
    before = store.get(alice.id, key)
    headers = {"X-Task-Owner": alice.id, "X-Research-Owner": alice.id}
    assert client.post(URL, json=replay.request).status_code == 409
    assert (
        client.post(
            URL, json=replay.request, headers={**headers, "X-Task-Owner": bob.id}
        ).status_code
        == 409
    )
    assert (
        client.post(
            URL, json={**replay.request, "expected_revision": 2}, headers=headers
        ).status_code
        == 409
    )
    assert (
        client.post(
            URL, json={**replay.request, "expected_digest": "0" * 64}, headers=headers
        ).status_code
        == 409
    )
    assert get_activity_store().events(days=1)["items"] == []
    for origin in ["system", "user"]:
        submitted = client.post(
            URL, json=replay.request, headers={**headers, "X-Query-Origin": origin}
        )
        assert submitted.status_code == 202, submitted.text
        assert submitted.headers["Cache-Control"] == "no-store"
        task_url = f"/api/v1/backtest/tasks/{submitted.json()['task_id']}"
        assert client.get(task_url).json()["kind"] == "factor_recompute"
    assert store.get(alice.id, key) == before
    events = get_activity_store().events(days=1)["items"]
    assert len(events) == 1 and events[0]["details"]["source_archive_id"] == key
    client.cookies.set(auth.SESSION_COOKIE, accounts.create_session(bob.id))
    assert client.get(task_url).status_code == 404
    assert client.post(task_url + "/cancel").status_code == 404
    assert (
        client.post(URL, json=replay.request, headers={"X-Research-Owner": bob.id}).status_code
        == 404
    )


def test_replay_real_worker_complete_envelope_reopen_and_dedup(replay, tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    supervisor = TaskSupervisor(store, owner_active=lambda owner: owner == "alice")
    try:
        frozen = replace(replay, execution_version=supervisor.version)
        state, _ = store.submit("alice", frozen)
        supervisor.step()
        deadline = time.monotonic() + 40
        while supervisor.active_count and time.monotonic() < deadline:
            supervisor.step(admit=False)
            time.sleep(0.02)
        assert supervisor.active_count == 0
        result = TaskStore(store.path).get("alice", state["task_id"])
        assert result["status"] == "done", result.get("error")
        validate_factor_archive(result["result"])
        assert result["result"]["recomputed_from"]["digest"] == replay.request["expected_digest"]
        reused, hit = store.submit("alice", frozen)
        assert hit and reused["task_id"] == state["task_id"]
        with pytest.raises(KeyError):
            store.get("bob", state["task_id"])
    finally:
        supervisor.close()


def test_replay_cancellation_and_complete_envelope_limit(replay, monkeypatch):
    original = research.recompute_factor_payload
    reached, release = Event(), Event()

    def delayed(*args):
        reached.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(research, "recompute_factor_payload", delayed)
    runner = BacktestTaskRunner(max_workers=1)
    try:
        task = runner.submit(lambda: dispatch_task(replay), owner_id="alice")
        assert reached.wait(2)
        runner.cancel(task)
        release.set()
        deadline = time.monotonic() + 5
        while runner.get(task).status == "cancelling" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert runner.get(task).status == "cancelled" and runner.get(task).result is None
        monkeypatch.setattr(task_store, "MAX_RESULT_BYTES", 128)
        with pytest.raises(ValueError, match="完整结果超过"):
            dispatch_task(replay)
    finally:
        release.set()
        runner.shutdown()
