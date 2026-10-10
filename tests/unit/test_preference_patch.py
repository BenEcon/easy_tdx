"""Owner-bound field patches preserve unrelated preferences and tracking access."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from easy_tdx.web import account_store
from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.errors import register_exception_handlers
from easy_tdx.web.request_security import RequestSecurityMiddleware
from easy_tdx.web.routers import auth


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = AccountStore(tmp_path / "accounts.db")
    monkeypatch.setattr(account_store, "_store", store)
    alice = store.create_user("alice", "preference-test-password", role="admin")
    bob = store.create_user("bob", "preference-test-password")
    app = FastAPI()
    app.add_middleware(RequestSecurityMiddleware, allowed_origins=[])
    register_exception_handlers(app)
    app.include_router(auth.router, prefix="/api/v1")
    with TestClient(app) as client:
        client.cookies.set(auth.SESSION_COOKIE, store.create_session(alice.id))
        yield store, alice, bob, client


def patch(client, owner, preferences):
    return client.patch(
        "/api/v1/auth/me/preferences",
        headers={"X-Preferences-Owner": owner},
        json={"preferences": preferences},
    )


def test_patches_preserve_unrelated_device_keys_and_legacy_put(setup):
    store, alice, _, client = setup
    store.set_preferences(alice.id, {"workspace": {"line": 2}, "adjust_mode": "QFQ"})
    assert patch(client, alice.id, {"adjust_mode": "HFQ"}).status_code == 200
    assert patch(client, alice.id, {"sidebar_collapsed": True}).status_code == 200
    assert store.get_user(alice.id).preferences == {
        "workspace": {"line": 2},
        "adjust_mode": "HFQ",
        "sidebar_collapsed": True,
    }
    response = client.put("/api/v1/auth/me/preferences", json={"preferences": {"legacy": True}})
    assert response.status_code == 200
    assert store.get_user(alice.id).preferences == {"legacy": True}


def test_owner_required_and_cookie_switch_cannot_write_old_owner_patch(setup):
    store, alice, bob, client = setup
    assert (
        client.patch("/api/v1/auth/me/preferences", json={"preferences": {"x": 1}}).status_code
        == 409
    )
    assert patch(client, bob.id, {"x": 1}).status_code == 409
    client.cookies.clear()
    client.cookies.set(auth.SESSION_COOKIE, store.create_session(bob.id))
    assert patch(client, alice.id, {"private": "alice"}).status_code == 409
    assert store.get_user(bob.id).preferences == {}
    client.cookies.clear()
    assert patch(client, alice.id, {"x": 1}).status_code == 401


def test_tracking_restriction_and_existing_groups_preserved(setup):
    store, _, bob, client = setup
    store.update_user(bob.id, tracking_allowed=True)
    store.set_preferences(bob.id, {"tracking_groups": {"groups": ["saved"]}})
    store.update_user(bob.id, tracking_allowed=False)
    client.cookies.clear()
    client.cookies.set(auth.SESSION_COOKIE, store.create_session(bob.id))
    assert patch(client, bob.id, {"adjust_mode": "NONE"}).status_code == 200
    assert patch(client, bob.id, {"tracking_groups": {}}).status_code == 403
    assert store.get_user(bob.id).preferences["tracking_groups"] == {"groups": ["saved"]}


def test_merged_size_limit_atomic_failure_and_nonfinite_rejection(setup):
    store, alice, _, client = setup
    store.set_preferences(alice.id, {"original": "a" * 40000})
    response = patch(client, alice.id, {"new": "b" * 40000})
    assert response.status_code == 400
    assert store.get_user(alice.id).preferences == {"original": "a" * 40000}
    with pytest.raises(ValueError):
        store.set_preferences(alice.id, {"invalid": float("nan")}, merge=True)
    assert "invalid" not in store.get_user(alice.id).preferences


def test_concurrent_independent_patches_do_not_lose_keys(setup):
    store, alice, _, _ = setup

    def write(index):
        other = AccountStore(store.db_path)
        other.set_preferences(alice.id, {f"key{index}": index}, merge=True)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write, range(20)))
    assert store.get_user(alice.id).preferences == {f"key{i}": i for i in range(20)}


def test_disabled_user_cannot_write_even_after_prior_identity_read(setup):
    store, _, bob, _ = setup
    store.update_user(bob.id, active=False)
    with pytest.raises(PermissionError):
        store.set_preferences(bob.id, {"x": 1}, merge=True)


def test_patch_does_not_bypass_cookie_origin_protection(setup):
    store, alice, _, client = setup
    response = client.patch(
        "/api/v1/auth/me/preferences",
        headers={"Origin": "https://untrusted.example", "X-Preferences-Owner": alice.id},
        json={"preferences": {"sidebar_collapsed": True}},
    )
    assert response.status_code == 403
    assert store.get_user(alice.id).preferences == {}
