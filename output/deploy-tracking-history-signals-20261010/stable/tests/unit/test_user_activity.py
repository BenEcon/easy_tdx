"""New activity data is bounded, admin-only, source-limited and not fabricated."""

import sqlite3
from datetime import datetime
from unittest.mock import Mock

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from easy_tdx.web import account_store as accounts
from easy_tdx.web import activity_geo
from easy_tdx.web import user_activity as activity
from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.activity_queries import query_details, record_query
from easy_tdx.web.request_security import RequestSecurityMiddleware
from easy_tdx.web.routers import auth, user_activity


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = AccountStore(tmp_path / "accounts.db")
    monkeypatch.setattr(accounts, "_store", store)
    admin = store.create_user("admin", "activity-test-password", role="admin")
    member = store.create_user("member", "activity-test-password")
    app = FastAPI()
    app.add_middleware(RequestSecurityMiddleware, allowed_origins=[])
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(user_activity.router, prefix="/api/v1")
    router = APIRouter(dependencies=[Depends(record_query)])

    @router.post("/chanlun/analyze")
    def query(body: dict):
        if body.get("fail"):
            raise HTTPException(502, "node failed")
        return {"ok": True}

    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        yield store, admin, member, client, activity.get_activity_store()


def cookie(client, store, user):
    client.cookies.set(auth.SESSION_COOKIE, store.create_session(user.id))


def test_activity_routes_admin_only_and_heartbeat_cannot_choose_owner(setup):
    store, admin, member, client, log = setup
    for path in ("summary", "events"):
        assert client.get(f"/api/v1/admin/activity/{path}").status_code == 401
    cookie(client, store, member)
    assert client.get("/api/v1/admin/activity/events").status_code == 403
    assert client.post("/api/v1/admin/activity/events/1/location").status_code == 403
    assert (
        client.post(
            "/api/v1/auth/activity", json={}, headers={"X-Research-Owner": admin.id}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/auth/activity",
            json={"owner": admin.id},
            headers={"X-Research-Owner": member.id},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/auth/activity",
            json={},
            headers={"X-Research-Owner": member.id, "Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    result = client.post("/api/v1/auth/activity", json={}, headers={"X-Research-Owner": member.id})
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    assert log.summary(1)[member.id]["active_seconds"] == 0
    cookie(client, store, admin)
    for path in ("summary", "events"):
        result = client.get(f"/api/v1/admin/activity/{path}")
        assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    assert client.get("/api/v1/admin/activity/events?days=91").status_code == 422
    assert client.get("/api/v1/admin/activity/events?limit=101").status_code == 422
    store.update_user(admin.id, tracking_allowed=False)


@pytest.mark.parametrize("kind", ["login", "query"])
def test_summary_before_first_heartbeat(setup, kind):
    store, admin, member, client, log = setup
    log.record(member.id, kind, "127.0.0.1", "测试", "accepted", {})
    cookie(client, store, admin)
    result = client.get("/api/v1/admin/activity/summary")
    assert result.status_code == 200
    row = next(row for row in result.json()["items"] if row["id"] == member.id)
    assert row["active_seconds"] == 0
    assert row["recently_active"] is False
    assert row["logins" if kind == "login" else "queries"] == 1


def test_heartbeat_union_no_idle_backfill_restart_and_midnight(tmp_path, monkeypatch):
    log = activity.ActivityStore(tmp_path / "activity.db")
    now = [datetime.fromisoformat("2026-10-09T23:59:50+08:00").timestamp()]
    monkeypatch.setattr(activity.time, "time", lambda: now[0])
    log.heartbeat("alice")
    now[0] += 15
    log.heartbeat("alice")
    log.heartbeat("alice")
    assert log.summary(2)["alice"]["active_seconds"] == 15
    with log.connect() as db:
        assert [
            (r["day"], r["active_seconds"])
            for r in db.execute("SELECT * FROM activity_days ORDER BY day")
        ] == [("2026-10-09", 10), ("2026-10-10", 5)]
    now[0] += 1000
    log.heartbeat("alice")
    now[0] += 20
    log.heartbeat("alice", restart=True)
    assert log.summary(2)["alice"]["active_seconds"] == 15
    now[0] += 15
    log.heartbeat("alice")
    assert log.summary(2)["alice"]["active_seconds"] == 30


def test_login_records_server_peer_not_untrusted_headers_and_no_secrets(setup):
    _, _, member, client, log = setup
    with TestClient(client.app, client=("8.8.4.4", 5000)) as real:
        result = real.post(
            "/api/v1/auth/login",
            json={"username": "member", "password": "activity-test-password"},
            headers={"X-Forwarded-For": "1.1.1.1", "X-Real-IP": "9.9.9.9"},
        )
        assert result.status_code == 200
    record = log.events(days=1)["items"][0]
    assert record["owner"] == member.id and record["ip"] == "8.8.4.4"
    assert record["details"] == {} and "password" not in str(record)
    before = len(log.events(days=1)["items"])
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "member", "password": "incorrect-password"}
        ).status_code
        == 401
    )
    assert len(log.events(days=1)["items"]) == before


def test_queries_record_success_and_failure_not_body_or_anonymous_calls(setup):
    store, _, member, client, log = setup
    assert client.post("/api/v1/chanlun/analyze", json={}).status_code == 401
    assert not log.events(days=1)["items"]
    cookie(client, store, member)
    body = {
        "code": "300750",
        "category": "DAY",
        "password": "secret",
        "bars": [{"close": 999}],
        "note": "private",
        "strategy_source": "print(secret)",
    }
    assert client.post("/api/v1/chanlun/analyze", json=body).status_code == 200
    assert client.post("/api/v1/chanlun/analyze", json={**body, "fail": True}).status_code == 502
    records = log.events(days=1)["items"]
    assert [r["outcome"] for r in records] == ["failed", "accepted"]
    assert all(r["details"] == {"code": "300750", "category": "DAY"} for r in records)
    assert log.summary(1)[member.id]["queries"] == 2


def test_metadata_nested_bounded_whitelist():
    data = query_details(
        {
            "series": [
                {"code": "stock:SZ:300750", "category": "DAY", "bars": [{"password": "secret"}]}
            ]
            * 101,
            "count": True,
            "code": "<script>x</script>",
            "as_of": "invalid",
            "notes": "private",
        }
    )
    assert data["series_total"] == 101 and len(data["series"]) == 100
    assert set(data) == {"series", "series_total"}
    assert data["series"][0] == {"code": "stock:SZ:300750", "category": "DAY"}


def test_keyset_summary_counts_and_retention(tmp_path, monkeypatch):
    log = activity.ActivityStore(tmp_path / "activity.db")
    monkeypatch.setattr(activity, "EVENT_LIMIT", 3)
    for i in range(5):
        log.record("alice", "query", "8.8.4.4", "行情", "accepted", {"code": str(i)})
    page = log.events(days=1, limit=2)
    assert len(page["items"]) == 2
    next_page = log.events(days=1, before=page["next_cursor"])
    assert len(next_page["items"]) == 1
    assert len({r["id"] for r in page["items"] + next_page["items"]}) == 3
    assert log.summary(1)["alice"]["queries"] == 5
    with log.connect() as db:
        db.execute("UPDATE activity_events SET occurred=0")
    log.record("bob", "login", "127.0.0.1", "登录", "accepted")
    assert len(log.events(days=90)["items"]) == 1


def test_geo_only_recorded_ips_local_skip_cache_and_limits(setup, monkeypatch):
    store, admin, _, client, log = setup
    cookie(client, store, admin)
    lookup = Mock(return_value={"state": "ok", "label": "美国 · 示例城市", "isp": "测试运营商"})
    monkeypatch.setattr(user_activity, "lookup_location", lookup)
    assert client.post("/api/v1/admin/activity/events/999/location").status_code == 404
    log.record(admin.id, "login", "127.0.0.1", "登录", "accepted")
    eid = log.events(days=1)["items"][0]["id"]
    assert client.post(f"/api/v1/admin/activity/events/{eid}/location").json()["state"] == "local"
    lookup.assert_not_called()
    log.record(admin.id, "login", "8.8.4.4", "登录", "accepted")
    eid = log.events(days=1)["items"][0]["id"]
    for _ in range(2):
        result = client.post(f"/api/v1/admin/activity/events/{eid}/location")
        assert (
            result.status_code == 200
            and result.json()["state"] == "ok"
            and result.json()["checked_at"] > 0
        )
    assert lookup.call_count == 1
    assert log.reserve_geo("1.1.1.1")["state"] == "limited"
    with log.connect() as db:
        db.execute("UPDATE activity_geo SET expires=0")
    assert log.events(days=1)["items"][0]["location"] is None


def test_geo_provider_is_fixed_bounded_and_validated(monkeypatch):
    original = httpx.Client
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "success": True,
                "ip": "8.8.4.4",
                "country": "美国",
                "region": "加州",
                "city": "城市",
                "connection": {"isp": "Example"},
            },
        )

    monkeypatch.setattr(
        activity_geo.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    assert activity_geo.lookup_location("8.8.4.4")["state"] == "ok"
    assert len(calls) == 1 and calls[0].url.host == "ipwho.is" and calls[0].url.scheme == "https"
    assert activity_geo.lookup_location("http://localhost/secret")["state"] == "unavailable"
    assert activity_geo.lookup_location("::1")["state"] == "local" and len(calls) == 1


def test_tracking_permission_migration_grant_revoke_and_atomic_preferences(setup):
    store, admin, member, client, _ = setup
    assert not member.can_track and admin.can_track
    cookie(client, store, member)
    assert (
        client.patch(
            f"/api/v1/admin/users/{member.id}", json={"tracking_allowed": True}
        ).status_code
        == 403
    )
    assert (
        client.put(
            "/api/v1/auth/me/preferences",
            json={"preferences": {"tracking_allowed": True, "tracking_groups": {}}},
        ).status_code
        == 403
    )
    cookie(client, store, admin)
    assert (
        client.patch(
            f"/api/v1/admin/users/{member.id}", json={"tracking_allowed": "true"}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/v1/admin/users/{member.id}", json={"tracking_allowed": True}
        ).status_code
        == 200
    )
    cookie(client, store, member)
    saved = {"tracking_groups": {"groups": [{"name": "保留"}]}}
    assert client.put("/api/v1/auth/me/preferences", json={"preferences": saved}).status_code == 200
    store.update_user(member.id, tracking_allowed=False, actor_id=admin.id)
    assert (
        client.put(
            "/api/v1/auth/me/preferences",
            json={"preferences": {**saved, "sidebar_collapsed": True}},
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/api/v1/auth/me/preferences", json={"preferences": {"tracking_groups": {}}}
        ).status_code
        == 403
    )
    assert store.get_user(member.id).preferences["tracking_groups"] == saved["tracking_groups"]
    fresh = AccountStore(store.db_path)
    assert not fresh.get_user(member.id).can_track
    assert any(
        item["details"].get("tracking_before") is True
        and item["details"].get("tracking_after") is False
        for item in store.list_audit()["items"]
    )


def test_tracking_migrates_legacy_database_without_enabling_users(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.executescript(AccountStore._SCHEMA)
    store = AccountStore(path)
    assert store.create_user("old", "activity-test-password").tracking_allowed is False
    with store._connect() as db:
        assert "tracking_allowed" in [row[1] for row in db.execute("PRAGMA table_info(users)")]


def test_heartbeat_is_bounded_across_concurrent_devices(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    log = activity.ActivityStore(tmp_path / "activity.db")
    clock = [1_791_550_000.0]
    monkeypatch.setattr(activity.time, "time", lambda: clock[0])
    log.heartbeat("alice")
    clock[0] += 15
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: log.heartbeat("alice"), range(30)))
    assert log.summary(1)["alice"]["active_seconds"] == 15


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"Location": "http://localhost/secret"}),
        httpx.Response(429),
        httpx.Response(200, content=b"x" * 17000),
        httpx.Response(200, json={"success": True, "ip": "1.1.1.1", "country": "wrong ip"}),
        httpx.Response(200, json={"success": "true", "ip": "8.8.4.4", "country": "wrong type"}),
    ],
)
def test_geo_bad_provider_data_never_becomes_a_location(monkeypatch, response):
    original = httpx.Client
    monkeypatch.setattr(
        activity_geo.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(lambda _: response), **kwargs),
    )
    assert activity_geo.lookup_location("8.8.4.4")["state"] == "unavailable"
