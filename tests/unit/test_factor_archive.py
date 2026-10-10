"""Frozen real inputs, immutable archives, isolated replay, no implicit execution."""

import copy
import json
import subprocess
import uuid

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from easy_tdx.factor.data import qualify_factor_fields
from easy_tdx.factor.snapshot import freeze_input, restore_input, snapshot_digest
from easy_tdx.web.factor_archive import validate_factor_archive
from easy_tdx.web.research_archive import ArchiveError, ArchiveLimits, ResearchArchive
from easy_tdx.web.routers import research
from easy_tdx.web.routers.research_archive import build_router
from tests.unit.test_factor_data import FILES, frozen


def payload():
    raw = frozen("0-000001-DAILY-NONE.json")
    frame = qualify_factor_fields(raw, raw, need_vwap=True)
    req = research.FactorComputeRequest(
        market="SZ",
        code="000001",
        count=160,
        adjust="NONE",
        factors=["alpha158_vwap0", "alpha158_ma5", "pe_ratio"],
        factor_parameters={"alpha158_ma5": {"window": 13}},
    )
    return {
        "format": "factor-research-v1",
        "mode": "series",
        "title": "冻结行情因子研究",
        "savedAt": "2026-10-10T12:00:00+08:00",
        "result": research._factor_result(req, frame).data,
    }


def record(source=None):
    return {
        "id": str(uuid.uuid4()),
        "digest": "a" * 64,
        "revision": 1,
        "payload": source or payload(),
    }


@pytest.mark.parametrize("filename", list(FILES))
def test_real_input_roundtrip_preserves_index_values_types_and_attrs(filename):
    original = frozen(filename)
    symbol = ("SH" if filename.startswith("1-") else "SZ") + ":" + filename.split("-")[1]
    source = freeze_input(symbol, original)
    # The user's browser parses/stringifies the server response before uploading.
    browser = subprocess.run(
        [
            "node",
            "-e",
            "let s='';process.stdin.on('data',c=>s+=c);"
            "process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s))))",
        ],
        input=json.dumps(source),
        text=True,
        capture_output=True,
        check=True,
    )
    restored = restore_input(json.loads(browser.stdout))
    pd.testing.assert_frame_equal(original, restored)
    assert restored.attrs == original.attrs
    assert source["digest"] == snapshot_digest(json.loads(browser.stdout))


def test_missing_nonfinite_large_integer_and_datetime_index_are_explicit():
    frame = pd.DataFrame(
        {"x": [np.nan, np.inf, -np.inf, -0.0], "large": pd.Series([2**60] * 4, dtype="int64")}
    )
    frame.index = pd.date_range("2020-01-01", periods=4, name="original")
    source = freeze_input("SZ:000001", frame)
    assert source["rows"][0][0] == {"special": "NaN"}
    restored = restore_input(json.loads(json.dumps(source, allow_nan=False)))
    pd.testing.assert_frame_equal(frame, restored, check_freq=False)
    assert np.signbit(restored.x.iloc[3])
    source["rows"][0][0] = None
    with pytest.raises(ValueError, match="摘要"):
        restore_input(source)


def test_full_precision_archive_and_current_replay_retain_frozen_defaults(tmp_path):
    source = payload()
    validate_factor_archive(source)
    store = ResearchArchive(tmp_path / "archives.db")
    key = str(uuid.uuid4())
    stored, _ = store.create("alice", key, "factor", source, "原档", "备注")
    original = store.get("alice", key)
    newer = research.recompute_factor_payload(original)
    validate_factor_archive(newer)
    assert newer["result"]["rows"] == source["result"]["rows"]
    assert newer["result"]["errors"] == source["result"]["errors"]
    assert newer["result"]["settings"]["factor_parameters"]["alpha158_ma5"] == {"window": 13}
    assert newer["recomputed_from"]["digest"] == stored["digest"]
    assert (
        newer["recomputed_from"]["original_definitions"]
        == original["payload"]["result"]["factor_definitions"]
    )
    assert store.get("alice", key) == original
    new_key = str(uuid.uuid4())
    store.create("alice", new_key, "factor", newer, "重算新版本", "")
    assert len(store.list("alice")["items"]) == 2
    with pytest.raises(ArchiveError) as error:
        store.get("bob", key)
    assert error.value.status == 404
    assert (
        store.get("alice", new_key)["payload"]["result"]["rows"]
        == original["payload"]["result"]["rows"]
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p["result"].pop("input_snapshots"),
        lambda p: p["result"]["rows"].pop(),
        lambda p: p["result"]["computed"].append("unknown"),
        lambda p: p["result"]["errors"].clear(),
        lambda p: p["result"]["settings"].update(code="600036"),
        lambda p: p["result"]["settings"].update(adjust="QFQ"),
        lambda p: p["result"]["factor_definitions"]["alpha158_ma5"].pop("resolved_parameters"),
        lambda p: p["result"]["input_snapshots"][0]["rows"].pop(),
        lambda p: p["result"]["input_snapshots"][0]["attrs"]["snapshot_metadata"].update(
            actual_adjust="QFQ"
        ),
        lambda p: p["result"]["rows"][0].update(datetime="2000-01-01"),
        lambda p: p["result"]["rows"][0].update(alpha158_ma5=float("inf")),
    ],
)
def test_incomplete_or_contradictory_archives_never_silently_repaired(change):
    source = payload()
    change(source)
    with pytest.raises(ArchiveError) as error:
        validate_factor_archive(source)
    assert error.value.status == 422


def test_archive_loading_does_not_require_current_registry(tmp_path, monkeypatch):
    source = payload()
    import easy_tdx.factor

    monkeypatch.setattr(
        easy_tdx.factor, "get_factor", lambda *a: pytest.fail("read must not execute")
    )
    store = ResearchArchive(tmp_path / "archives.db")
    key = str(uuid.uuid4())
    store.create("alice", key, "factor", source, "只读", "")
    validate_factor_archive(store.get("alice", key)["payload"])


def test_unknown_settings_remain_readable_but_cannot_be_ignored_during_replay():
    source = payload()
    source["result"]["settings"]["future_semantics"] = "preserve"
    validate_factor_archive(source)
    with pytest.raises(ValueError, match="不兼容"):
        research.recompute_factor_payload(record(source))


def test_replay_uses_archived_default_not_changed_class_default(monkeypatch):
    from easy_tdx.factor import get_factor

    frame = frozen("0-000001-DAILY-NONE.json")
    req = research.FactorComputeRequest(
        market="SZ", code="000001", adjust="NONE", count=160, factors=["momentum_20d"]
    )
    source = payload()
    source["result"] = research._factor_result(req, frame).data
    monkeypatch.setattr(get_factor("momentum_20d"), "window", 80)
    replay = research.recompute_factor_payload(record(source))
    assert replay["result"]["settings"]["factor_parameters"] == {"momentum_20d": {"window": 20}}
    assert replay["result"]["rows"] == source["result"]["rows"]


def test_factor_archive_in_paired_backup_and_restore(tmp_path):
    from easy_tdx.web import research_backup
    from easy_tdx.web.account_store import AccountStore

    directory = tmp_path / "source"
    account = AccountStore(directory / "accounts.db").create_user(
        "alice", "Local-archive-test-2026", role="admin"
    )
    store = ResearchArchive(directory / "research_archives.db")
    key = str(uuid.uuid4())
    store.create(account.id, key, "factor", payload(), "因子原档", "")
    research_backup.create_backup(directory, tmp_path / "backup")
    research_backup.restore_backup(tmp_path / "backup", tmp_path / "restored")
    restored = ResearchArchive(tmp_path / "restored" / "research_archives.db")
    assert restored.get(account.id, key) == store.get(account.id, key)


def test_factor_archives_reuse_api_account_guards_quotas_and_recycle(tmp_path):
    from types import SimpleNamespace

    store = ResearchArchive(tmp_path / "archives.db", ArchiveLimits(owner_items=1))

    def identity():
        return SimpleNamespace(id="alice")

    app = FastAPI()
    app.include_router(build_router(lambda: store, identity))
    client = TestClient(app)
    key = str(uuid.uuid4())
    body = {"kind": "factor", "payload": payload(), "name": "原档"}
    assert (
        client.put(
            f"/research/archives/{key}", json=body, headers={"X-Research-Owner": "bob"}
        ).status_code
        == 409
    )
    assert client.put(f"/research/archives/{key}", json=body).status_code == 201
    assert client.put(f"/research/archives/{key}", json=body).status_code == 200
    assert client.put(f"/research/archives/{uuid.uuid4()}", json=body).status_code == 413
    original = client.get(f"/research/archives/{key}").json()
    assert client.get(f"/research/archives/{key}").headers["cache-control"] == "no-store"
    assert (
        client.post(
            f"/research/archives/{key}/actions", json={"action": "delete", "revision": 1}
        ).status_code
        == 200
    )
    removed = client.get(f"/research/archives/{key}").json()
    assert removed["payload"] == original["payload"]
    restored = client.post(
        f"/research/archives/{key}/actions",
        json={"action": "restore", "revision": removed["revision"]},
    ).json()
    assert restored["state"] == "active" and restored["digest"] == original["digest"]


@pytest.mark.asyncio
async def test_recompute_owner_scope_and_no_market_requests(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from fastapi import HTTPException, Response

    from easy_tdx.web import research_archive

    store = ResearchArchive(tmp_path / "archives.db")
    key = str(uuid.uuid4())
    store.create("alice", key, "factor", payload(), "原档", "")
    monkeypatch.setattr(research_archive, "get_research_archive", lambda: store)
    monkeypatch.setattr(research, "fetch_adjusted_bars", lambda *a: pytest.fail("no live prices"))
    req = research.FactorRecomputeRequest(source_archive_id=key)
    for user, expected, status in [
        ("bob", "bob", 404),
        ("alice", None, 409),
        ("alice", "bob", 409),
    ]:
        with pytest.raises(HTTPException) as caught:
            await research.factor_recompute(req, Response(), SimpleNamespace(id=user), expected)
        assert caught.value.status_code == status
    result = await research.factor_recompute(req, Response(), SimpleNamespace(id="alice"), "alice")
    assert result.data["recomputed_from"]["archive_id"] == key
    assert len(store.list("alice")["items"]) == 1  # Explicit save is separate.


def test_recompute_http_requires_login_owner_assertion_and_own_archive(tmp_path, monkeypatch):
    from easy_tdx.web import account_store, research_archive
    from easy_tdx.web.resource_admission import resource_for
    from easy_tdx.web.routers.auth import SESSION_COOKIE

    accounts = account_store.AccountStore(tmp_path / "accounts.db")
    alice = accounts.create_user("alice", "Local-archive-http-2026")
    bob = accounts.create_user("bob", "Local-archive-http-2026")
    monkeypatch.setattr(account_store, "_store", accounts)
    store = ResearchArchive(tmp_path / "archives.db")
    monkeypatch.setattr(research_archive, "get_research_archive", lambda: store)
    key = str(uuid.uuid4())
    store.create(alice.id, key, "factor", payload(), "原档", "")
    app = FastAPI()
    app.include_router(research.router, prefix="/api/v1")
    client = TestClient(app)
    endpoint = "/api/v1/research/factors/recompute"
    body = {"source_archive_id": key}
    assert resource_for(endpoint, "POST") == "compute"
    assert client.post(endpoint, json=body).status_code == 401
    client.cookies.set(SESSION_COOKIE, accounts.create_session(bob.id))
    assert client.post(endpoint, json=body, headers={"X-Research-Owner": bob.id}).status_code == 404
    client.cookies.set(SESSION_COOKIE, accounts.create_session(alice.id))
    assert client.post(endpoint, json=body).status_code == 409
    response = client.post(endpoint, json=body, headers={"X-Research-Owner": alice.id})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["data"]["recomputed_from"]["archive_id"] == key
    assert len(store.list(alice.id)["items"]) == 1


@pytest.mark.asyncio
async def test_evaluation_freezes_each_input_and_replays_full_pool(monkeypatch):
    stocks = [{"market": "SZ", "code": f"00000{i}"} for i in range(1, 6)]

    async def fetch(*args):
        frame = frozen("0-000001-DAILY-NONE.json").copy()
        # Synthetic cross-section based on real bars, NOT a real five-stock pool.
        frame[["open", "high", "low", "close"]] *= 1 + int(args[3][-1]) / 100
        return frame

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda df: df)
    req = research.FactorEvaluationRequest(
        stocks=stocks,
        factors=["momentum_20d"],
        count=160,
        adjust="NONE",
        factor_parameters={"momentum_20d": {"window": 7}},
    )
    result = (await research.factor_evaluate(req, None, None)).data
    source = {
        "format": "factor-research-v1",
        "mode": "evaluation",
        "title": "合成池验收",
        "savedAt": "2026-10-10T10:00:00Z",
        "result": result,
    }
    validate_factor_archive(source)
    before = copy.deepcopy(source)
    new = research.recompute_factor_payload(record(source))
    assert new["result"]["reports"] == source["result"]["reports"]
    assert new["result"]["latest"] == source["result"]["latest"]
    assert source == before
    assert len(new["result"]["input_snapshots"]) == 5
    assert new["recomputed_from"]["original_statistics_version"] == result["statistics_version"]

    # Legacy results remain immutable even if the old numerical rule was wrong.
    legacy = copy.deepcopy(source)
    legacy["result"].pop("statistics_version")
    legacy["result"].pop("numeric_policy")
    legacy["result"]["reports"][0]["rank_ic_mean"] = -0.5855400437691199
    frozen_legacy = copy.deepcopy(legacy)
    validate_factor_archive(legacy)
    revised = research.recompute_factor_payload(record(legacy))
    assert legacy == frozen_legacy
    assert revised["recomputed_from"]["original_statistics_version"] == "legacy-unrecorded"
    assert revised["result"]["statistics_version"] == "factor-cross-section-numerics-v2"
    assert revised["result"]["reports"][0]["rank_ic_mean"] is None
