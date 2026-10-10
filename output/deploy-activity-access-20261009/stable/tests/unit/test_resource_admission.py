"""Quota ownership spans HTTP preparation and real worker lifetime, not polling."""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from easy_tdx.web import account_store as accounts
from easy_tdx.web import resource_admission as admission
from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.app import _create_app
from easy_tdx.web.deps import get_client, get_mac_client_optional
from easy_tdx.web.task_runner import BacktestTaskRunner


def count(store):
    with store.connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM resource_leases").fetchone()[0]


def handle(tmp_path):
    store = admission.ResourceStore(tmp_path / "resources.db")
    return admission.Admission(store, store.acquire("alice", "compute"))


def test_shared_atomic_admission_user_and_global_caps(tmp_path, monkeypatch):
    stores = [admission.ResourceStore(tmp_path / "resources.db") for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        leases = list(pool.map(lambda store: store.acquire("alice", "compute"), stores))
    assert len([lease for lease in leases if lease]) == 3
    for index in range(5):
        assert stores[0].acquire(f"user{index}", "compute")
    assert stores[1].acquire("another", "compute") is None
    assert stores[1].acquire("alice", "data")  # Separate bounded data pool.
    monkeypatch.setattr(admission.time, "time", lambda: 10**12)
    assert not stores[0].renew(next(lease for lease in leases if lease))
    assert stores[0].acquire("alice", "compute")


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["timeout", "cancel"])
async def test_offloaded_work_keeps_slot_after_http_waiter_leaves(tmp_path, stop):
    lease = handle(tmp_path)
    token = admission._current.set(lease)
    entered, finish = Event(), Event()

    def work():
        entered.set()
        assert finish.wait(3)
        return {"partial": True}

    task = asyncio.create_task(admission.run_compute(work, timeout=0.1 if stop == "timeout" else 3))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        if stop == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(HTTPException) as error:
                await task
            assert error.value.status_code == 504
        admission._current.reset(token)
        lease.release()  # HTTP dependency exits, worker still owns another reference.
        assert count(lease.store) == 1
    finally:
        finish.set()
    for _ in range(100):
        if count(lease.store) == 0:
            break
        await asyncio.sleep(0.01)
    assert count(lease.store) == 0


def test_event_loop_shutdown_cannot_release_running_native_work(tmp_path):
    lease = handle(tmp_path)
    entered, finish = Event(), Event()

    def work():
        entered.set()
        assert finish.wait(3)
        return {}

    async def request():
        token = admission._current.set(lease)
        task = asyncio.create_task(admission.run_compute(work))
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        admission._current.reset(token)
        lease.release()

    try:
        asyncio.run(request())  # Closes the event loop with native work still running.
        assert count(lease.store) == 1
    finally:
        finish.set()
        admission.shutdown_compute_pool()
    assert count(lease.store) == 0


def test_background_job_retains_slot_until_actual_exit_and_pending_cancel(tmp_path):
    lease = handle(tmp_path)
    token = admission._current.set(lease)
    entered, finish = Event(), Event()
    runner = BacktestTaskRunner(max_workers=1)

    def work():
        entered.set()
        assert finish.wait(3)
        return {"done": True}

    try:
        first = runner.submit(work, owner_id="alice")
        assert entered.wait(1)
        second = runner.submit(lambda: {}, owner_id="alice")
        admission._current.reset(token)
        lease.release()
        assert count(lease.store) == 1
        assert runner.cancel(second).status == "cancelled"
        assert count(lease.store) == 1
        assert runner.cancel(first).status == "cancelling"
        assert count(lease.store) == 1
    finally:
        finish.set()
        runner.shutdown()
    assert count(lease.store) == 0


def test_failed_submission_releases_retained_reference(tmp_path):
    lease = handle(tmp_path)
    token = admission._current.set(lease)
    runner = BacktestTaskRunner()
    runner.shutdown()
    try:
        with pytest.raises(RuntimeError):
            runner.submit(lambda: {})
    finally:
        admission._current.reset(token)
        lease.release()
    assert count(lease.store) == 0


def test_lease_loss_never_publishes_success(tmp_path):
    lease = handle(tmp_path)
    lease.store.release(lease.lease)
    lease.renew()
    with pytest.raises(HTTPException, match="503"):
        lease.check()
    lease.release()


@pytest.fixture
def boundary(tmp_path, monkeypatch):
    store = AccountStore(tmp_path / "accounts.db")
    monkeypatch.setattr(accounts, "_store", store)
    user = store.create_user("alice", "safe-password")
    app = _create_app(host="127.0.0.1", enable_mac=False)
    upstream = AsyncMock()
    app.dependency_overrides[get_client] = lambda: upstream
    app.dependency_overrides[get_mac_client_optional] = lambda: upstream
    client = TestClient(app)
    client.cookies.set("easy_tdx_session", store.create_session(user.id))
    return client, admission.ResourceStore(store.db_path), upstream, user


def test_full_compute_quota_rejects_before_fetch_and_keeps_control_plane_available(boundary):
    client, store, upstream, user = boundary
    for _ in range(3):
        assert store.acquire(user.id, "compute")
    response = client.post(
        "/api/v1/backtest/run/async", json={"strategy": "ma_cross", "symbol": "SZ:000001"}
    )
    assert response.status_code == 429
    assert response.headers["retry-after"] == "5"
    assert not upstream.mock_calls
    assert client.get("/api/v1/backtest/tasks").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/backtest/tasks/missing/cancel").status_code == 404


def test_full_data_quota_rejects_range_before_first_page(boundary):
    client, store, upstream, user = boundary
    for _ in range(4):
        assert store.acquire(user.id, "data")
    response = client.get("/api/v1/bars/range?market=SZ&code=000001&category=DAY&adjust=QFQ")
    assert response.status_code == 429
    assert not upstream.mock_calls


def test_bad_request_and_handler_error_release_request_slot(boundary):
    client, store, _, _ = boundary
    assert client.post("/api/v1/backtest/run", json={}).status_code == 422
    assert count(store) == 0
    assert (
        client.post(
            "/api/v1/backtest/run", json={"strategy": "ma_cross", "symbol": "SZ:000001"}
        ).status_code
        == 400
    )
    assert count(store) == 0


def test_all_business_routes_have_admission_and_sync_research_is_offloaded(boundary):
    client, _, _, _ = boundary
    import inspect

    found = 0
    for route in client.app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/v1/"):
            continue
        if admission.resource_for(route.path, next(iter(route.methods))) is None:
            continue
        assert admission.admit_research in [dep.call for dep in route.dependant.dependencies], (
            route.path
        )
        if route.path.startswith(("/api/v1/chanlun/replay", "/api/v1/chanlun/observations")):
            assert inspect.iscoroutinefunction(route.endpoint), route.path
            found += 1
    assert found >= 7


def test_wrapped_sync_route_preserves_schema_and_original_direct_call():
    from pydantic import BaseModel

    class Input(BaseModel):
        number: int

    router = APIRouter(route_class=admission.BoundedComputeRoute)

    def original(req):
        return {"number": req.number + 1}

    original.__annotations__ = {"req": Input, "return": dict}
    router.post("/compute")(original)
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).post("/compute", json={"number": 2})
    assert response.json() == {"number": 3}
    assert original(Input(number=3)) == {"number": 4}
    assert TestClient(app).post("/compute", json={"number": "bad"}).status_code == 422


def inline_request():
    return {
        "strategy": "ma_cross",
        "ohlcv": [
            {
                "datetime": day,
                "open": 10,
                "high": 12,
                "low": 9,
                "close": 11,
                "vol": 100,
                "amount": 1100,
            }
            for day in ("2026-08-03", "2026-08-04")
        ],
    }


def test_http_submission_transfers_lease_to_actual_background_job(boundary, monkeypatch):
    from easy_tdx.web.routers import backtest

    client, store, _, _ = boundary
    runner = BacktestTaskRunner(max_workers=1)
    entered, finish = Event(), Event()

    def work(*args):
        entered.set()
        assert finish.wait(3)
        return {}

    monkeypatch.setattr(backtest, "get_runner", lambda: runner)
    monkeypatch.setattr(backtest, "_run_backtest", work)
    try:
        response = client.post("/api/v1/backtest/run/async", json=inline_request())
        assert response.status_code == 202, response.text
        assert entered.wait(1)
        assert count(store) == 1  # The submitting HTTP response has already completed.
        task_id = response.json()["task_id"]
        cancelled = client.post(f"/api/v1/backtest/tasks/{task_id}/cancel")
        assert cancelled.json()["status"] == "cancelling"
        assert count(store) == 1
    finally:
        finish.set()
        runner.shutdown()
    assert count(store) == 0


@pytest.mark.asyncio
async def test_synchronous_backtest_keeps_event_loop_available(boundary, monkeypatch):
    import httpx

    from easy_tdx.web.routers import backtest

    client, _, _, _ = boundary
    entered, finish = Event(), Event()
    original = backtest._run_backtest

    def work(*args):
        entered.set()
        assert finish.wait(3)
        return original(*args)

    monkeypatch.setattr(backtest, "_run_backtest", work)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=client.app),
        base_url="http://testserver",
        cookies=client.cookies,
    ) as browser:
        started = time.monotonic()
        task = asyncio.create_task(browser.post("/api/v1/backtest/run", json=inline_request()))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            response = await asyncio.wait_for(browser.get("/api/v1/auth/me"), timeout=1)
            assert response.status_code == 200
            assert time.monotonic() - started < 2
        finally:
            finish.set()
        assert (await task).status_code == 200
