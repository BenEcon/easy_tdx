"""Explicit frozen-score selection, permissions, atomic append and retry safety."""

import copy
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from easy_tdx.factor.snapshot import restore_input
from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.factor_tracking import factor_tracking_group
from easy_tdx.web.research_archive import ArchiveError, ResearchArchive
from easy_tdx.web.routers import auth, research
from easy_tdx.web.routers.research_archive import build_router


@pytest.fixture(scope="module")
def source():
    payload = json.loads(Path("tests/fixtures/factor_archive/multi-horizon.json").read_text())
    settings = payload["result"]["settings"].copy()
    settings.pop("category")
    settings.update(factors=["momentum_20d", "volatility_20d"], factor_parameters={})
    settings["composition"] = {
        "method": "rank_centered",
        "components": [
            {"name": "momentum_20d", "weight": 3.0, "direction": 1},
            {"name": "volatility_20d", "weight": 1.0, "direction": -1},
        ],
    }
    frames = {s["symbol"]: restore_input(s) for s in payload["result"]["input_snapshots"]}
    payload["result"] = research.evaluation_result(
        research.FactorEvaluationRequest(**settings), frames
    )
    return payload


@pytest.fixture
def setup(tmp_path, monkeypatch, source):
    accounts = AccountStore(tmp_path / "accounts.db")
    admin = accounts.create_user("Admin", "A-testing-password!", role="admin")
    user = accounts.create_user("User", "A-testing-password!", role="user")
    other = accounts.create_user("Other", "A-testing-password!", role="admin")
    monkeypatch.setattr(auth, "get_account_store", lambda: accounts)
    store = ResearchArchive(tmp_path / "archives.db")
    key = str(uuid.uuid4())
    store.create(admin.id, key, "factor", source, "原始研究", "")
    record = store.get(admin.id, key)
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(
        build_router(lambda: store, auth.get_current_user, lambda: accounts), prefix="/api/v1"
    )
    with TestClient(app) as client:
        client.cookies.set(auth.SESSION_COOKIE, accounts.create_session(admin.id))
        yield client, accounts, store, record, admin, user, other


def choice(record):
    return {
        "name": "评分观察",
        "score_key": "composite_score",
        "symbols": [record["payload"]["result"]["composition"]["latest"][0]["code"]],
        "labels": {},
        "digest": record["digest"],
        "revision": record["revision"],
    }


def test_server_uses_original_scores_and_retry_does_not_replace_edits(setup):
    client, accounts, store, record, admin, *_ = setup
    before = copy.deepcopy(record)
    url = f"/api/v1/research/archives/{record['id']}/tracking-group"
    headers = {"X-Research-Owner": admin.id}
    first = client.post(url, json=choice(record), headers=headers)
    assert first.status_code == 201 and first.headers["cache-control"] == "no-store"
    group = first.json()["group"]
    assert (
        group["research_source"]["selection"][0]["score"]
        == record["payload"]["result"]["composition"]["latest"][0]["score"]
    )
    saved = accounts.get_user(admin.id).preferences
    saved["tracking_groups"]["groups"][0]["name"] = "后来编辑"
    accounts.set_preferences(admin.id, {**saved, "unrelated": "preserve"})
    retry = client.post(url, json={**choice(record), "name": "不覆盖"}, headers=headers)
    assert retry.status_code == 200 and retry.json()["created"] is False
    assert retry.json()["group"]["name"] == "后来编辑"
    assert accounts.get_user(admin.id).preferences["unrelated"] == "preserve"
    assert store.get(admin.id, record["id"]) == before


def test_route_permissions_owner_assertion_revision_and_deleted_source(setup):
    client, accounts, store, record, admin, user, other = setup
    url = f"/api/v1/research/archives/{record['id']}/tracking-group"
    data = choice(record)
    assert client.post(url, json=data).status_code == 422
    assert client.post(url, json=data, headers={"X-Research-Owner": other.id}).status_code == 409
    assert (
        client.post(
            url, json={**data, "revision": 2}, headers={"X-Research-Owner": admin.id}
        ).status_code
        == 409
    )
    assert (
        client.post(
            url, json={**data, "owner": other.id}, headers={"X-Research-Owner": admin.id}
        ).status_code
        == 422
    )
    for actor, status in [(user, 403), (other, 404)]:
        client.cookies.set(auth.SESSION_COOKIE, accounts.create_session(actor.id))
        assert (
            client.post(url, json=data, headers={"X-Research-Owner": actor.id}).status_code
            == status
        )
        assert not accounts.get_user(actor.id).preferences
    client.cookies.set(auth.SESSION_COOKIE, accounts.create_session(admin.id))
    store.mutate(admin.id, record["id"], 1, "delete")
    assert client.post(url, json=data, headers={"X-Research-Owner": admin.id}).status_code == 409
    assert not accounts.get_user(admin.id).preferences


@pytest.mark.parametrize(
    "change",
    [
        lambda b: b.update(symbols=[]),
        lambda b: b.update(symbols=b["symbols"] * 2),
        lambda b: b.update(symbols=["SH:000001"]),
        lambda b: b.update(symbols=["SH:510300"]),
        lambda b: b.update(symbols=["SZ:300750"]),
        lambda b: b.update(score_key="absent"),
        lambda b: b.update(labels={"SH:000001": "指数"}),
        lambda b: b.update(name="   "),
    ],
)
def test_selection_is_explicit_and_never_silently_shrunk(setup, change):
    record = setup[3]
    body = choice(record)
    change(body)
    with pytest.raises(ArchiveError):
        factor_tracking_group(record, **body)


@pytest.mark.parametrize("bad", [None, True, float("nan"), float("inf")])
def test_missing_or_invalid_score_is_not_zero_or_previous_date(setup, bad):
    record = copy.deepcopy(setup[3])
    record["payload"]["result"]["composition"]["latest"][0]["score"] = bad
    with pytest.raises(ArchiveError, match="有限评分"):
        factor_tracking_group(record, **choice(record))


def test_single_factor_keeps_raw_precision_and_atomic_append_preserves_both(setup):
    _, accounts, _, record, admin, user, _ = setup
    one = factor_tracking_group(record, **{**choice(record), "score_key": "momentum_20d"})
    two = factor_tracking_group(record, **choice(record))
    assert one["id"] != two["id"]
    assert (
        one["research_source"]["selection"][0]["score"]
        == record["payload"]["result"]["latest"][0]["momentum_20d"]
    )
    with ThreadPoolExecutor(2) as pool:
        saved = list(pool.map(lambda g: accounts.append_tracking_group(admin.id, g), [one, two]))
    assert all(created for _, created in saved)
    assert len(accounts.get_user(admin.id).preferences["tracking_groups"]["groups"]) == 2
    with pytest.raises(PermissionError):
        accounts.append_tracking_group(user.id, one)
    accounts.set_preferences(admin.id, {"tracking_groups": {"version": 99, "groups": []}})
    with pytest.raises(ValueError, match="未覆盖"):
        accounts.append_tracking_group(admin.id, one)


def test_oversize_append_rolls_back_without_harming_source(setup):
    _, accounts, store, record, admin, *_ = setup
    group = factor_tracking_group(record, **choice(record))
    original = {
        "tracking_groups": {"version": 1, "revision": "old", "groups": [], "padding": "x" * 40000}
    }
    accounts.set_preferences(admin.id, original)
    with pytest.raises(ValueError, match="40KB"):
        accounts.append_tracking_group(admin.id, group)
    assert accounts.get_user(admin.id).preferences == original
    assert store.get(admin.id, record["id"]) == record


def test_stale_preferences_cannot_remove_a_new_factor_group(setup):
    from easy_tdx.web.account_store import TrackingRevisionConflict

    _, accounts, _, record, admin, *_ = setup
    group = factor_tracking_group(record, **choice(record))
    accounts.append_tracking_group(admin.id, group)
    saved = accounts.get_user(admin.id).preferences
    with pytest.raises(TrackingRevisionConflict):
        accounts.set_preferences(
            admin.id,
            {"tracking_groups": {"version": 1, "revision": "stale", "groups": []}},
            merge=True,
            expected_tracking_revision="",
            require_tracking_revision=True,
        )
    assert accounts.get_user(admin.id).preferences == saved
    updated = copy.deepcopy(saved)
    updated["tracking_groups"]["groups"][0]["name"] = "经过版本核验的编辑"
    accounts.set_preferences(
        admin.id,
        updated,
        expected_tracking_revision=saved["tracking_groups"]["revision"],
        require_tracking_revision=True,
    )
    assert (
        accounts.get_user(admin.id).preferences["tracking_groups"]["groups"][0]["name"]
        == "经过版本核验的编辑"
    )


def test_http_revision_conflict_and_explicit_allowed_user(setup):
    client, accounts, store, record, admin, user, _ = setup
    group = factor_tracking_group(record, **choice(record))
    accounts.append_tracking_group(admin.id, group)
    saved = accounts.get_user(admin.id).preferences
    headers = {"X-Preferences-Owner": admin.id}
    body = {
        "preferences": {"tracking_groups": {"version": 1, "revision": "old", "groups": []}},
        "tracking_revision": "",
    }
    assert (
        client.patch("/api/v1/auth/me/preferences", json=body, headers=headers).status_code == 409
    )
    assert accounts.get_user(admin.id).preferences == saved
    changed = copy.deepcopy(saved)
    changed["tracking_groups"]["revision"] = str(uuid.uuid4())
    changed["tracking_groups"]["groups"][0]["name"] = "新名称"
    assert (
        client.patch(
            "/api/v1/auth/me/preferences",
            json={
                "preferences": changed,
                "tracking_revision": saved["tracking_groups"]["revision"],
            },
            headers=headers,
        ).status_code
        == 200
    )
    # A designated regular user has the same own-archive operation, no admin override.
    accounts.update_user(user.id, tracking_allowed=True)
    client.cookies.set(auth.SESSION_COOKIE, accounts.create_session(user.id))
    store.create(user.id, record["id"], "factor", record["payload"], "自己的原档", "")
    result = client.post(
        f"/api/v1/research/archives/{record['id']}/tracking-group",
        json=choice(record),
        headers={"X-Research-Owner": user.id},
    )
    assert result.status_code == 201
    accounts.update_user(user.id, tracking_allowed=False)
    assert (
        client.post(
            f"/api/v1/research/archives/{record['id']}/tracking-group",
            json=choice(record),
            headers={"X-Research-Owner": user.id},
        ).status_code
        == 403
    )


@pytest.mark.parametrize("rows", [[1], [{"code": ["SZ:000001"]}]])
def test_legacy_malformed_latest_is_explicit_not_internal_error(setup, rows):
    record = copy.deepcopy(setup[3])
    body = {**choice(record), "score_key": "momentum_20d"}
    record["payload"]["result"]["latest"] = rows
    with pytest.raises(ArchiveError, match="股票池不一致"):
        factor_tracking_group(record, **body)
