"""A new HTTP request must never borrow its transport parent's resource handles."""

import asyncio
import json
import uuid
from contextvars import ContextVar

import httpx
import pytest
from starlette.responses import JSONResponse

from easy_tdx.web import account_store as accounts
from easy_tdx.web import archive_ingress, resource_admission
from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.app import _create_app
from easy_tdx.web.request_security import RequestSecurityMiddleware
from tests.unit.test_research_archive import payload


@pytest.mark.asyncio
@pytest.mark.parametrize("released", [False, True])
async def test_archive_get_does_not_retain_another_requests_upload(tmp_path, monkeypatch, released):
    store = AccountStore(tmp_path / "accounts.db")
    monkeypatch.setattr(accounts, "_store", store)
    user = store.create_user("reader", "safe-reader-password")
    resource = resource_admission.ResourceStore(store.db_path)
    inherited = resource_admission.Admission(
        resource, resource.acquire("another", "archive_upload")
    )
    if released:
        inherited.release()
    retained = []
    original = resource_admission.Admission.retain

    def capture(self):
        retained.append(self)
        return original(self)

    monkeypatch.setattr(resource_admission.Admission, "retain", capture)
    token = archive_ingress._current_upload.set(inherited)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_create_app(host="127.0.0.1", enable_mac=False)),
            base_url="http://testserver",
            cookies={"easy_tdx_session": store.create_session(user.id)},
        ) as client:
            # A server may create a pipelined request task from the prior response's context.
            response = await asyncio.create_task(client.get("/api/v1/research/archives"))
        assert response.status_code == 200, response.text
        assert response.json()["items"] == []
        assert inherited not in retained
        assert len(retained) == 1  # This GET still retains its OWN normal data lease.
        assert archive_ingress._current_upload.get() is inherited
        with resource.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM resource_leases").fetchone()[0] == (
                0 if released else 1
            )
    finally:
        archive_ingress._current_upload.reset(token)
        inherited.release()


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["success", "error", "cancel"])
async def test_request_boundary_clears_only_our_handles_and_restores_parent(tmp_path, ending):
    resource = resource_admission.ResourceStore(tmp_path / "resources.db")
    ordinary = resource_admission.Admission(resource, resource.acquire("parent", "compute"))
    upload = resource_admission.Admission(resource, resource.acquire("parent", "archive_upload"))
    trace = ContextVar("unrelated_trace", default=None)
    ordinary_token = resource_admission._current.set(ordinary)
    upload_token = archive_ingress._current_upload.set(upload)
    trace_token = trace.set("keep-request-instrumentation")
    entered = asyncio.Event()

    async def endpoint(scope, receive, send):
        assert resource_admission._current.get() is None
        assert archive_ingress._current_upload.get() is None
        assert trace.get() == "keep-request-instrumentation"
        entered.set()
        if ending == "error":
            raise RuntimeError("handler failed")
        if ending == "cancel":
            await asyncio.Event().wait()
        await JSONResponse({"ok": True})(scope, receive, send)

    app = RequestSecurityMiddleware(endpoint, [])

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        pass

    async def request():
        try:
            await app(
                {"type": "http", "path": "/api/v1/auth/me", "method": "GET", "headers": []},
                receive,
                send,
            )
        finally:
            assert resource_admission._current.get() is ordinary
            assert archive_ingress._current_upload.get() is upload
            assert trace.get() == "keep-request-instrumentation"

    task = asyncio.create_task(request())
    try:
        if ending == "cancel":
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif ending == "error":
            with pytest.raises(RuntimeError, match="handler failed"):
                await task
        else:
            await task
        # Resetting request-local references must not release someone else's live work.
        ordinary.check()
        upload.check()
        assert ordinary._refs == upload._refs == 1
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        resource_admission._current.reset(ordinary_token)
        archive_ingress._current_upload.reset(upload_token)
        trace.reset(trace_token)
        ordinary.release()
        upload.release()


@pytest.mark.asyncio
async def test_real_h11_pipeline_upload_then_directory_and_detail(tmp_path, monkeypatch):
    """Exercise the server's real response callback/task inheritance without a socket."""
    from uvicorn import Config
    from uvicorn.protocols.http.h11_impl import H11Protocol
    from uvicorn.server import ServerState

    store = AccountStore(tmp_path / "accounts.db")
    monkeypatch.setattr(accounts, "_store", store)
    user = store.create_user("pipeline", "safe-pipeline-password")
    session = store.create_session(user.id)
    app = _create_app(host="127.0.0.1", enable_mac=False)
    state = ServerState()
    protocol = H11Protocol(Config(app, lifespan="off", ws="none", log_config=None), state, {})

    class Transport(asyncio.Transport):
        def __init__(self):
            self.output = bytearray()
            self.closed = asyncio.Event()

        def get_extra_info(self, name, default=None):
            return {"sockname": ("127.0.0.1", 8768), "peername": ("127.0.0.1", 12345)}.get(
                name, default
            )

        def write(self, data):
            self.output.extend(data)

        def close(self):
            self.closed.set()

        def is_closing(self):
            return self.closed.is_set()

        def pause_reading(self):
            pass

        def resume_reading(self):
            pass

    transport = Transport()
    protocol.connection_made(transport)
    key = str(uuid.uuid4())
    body = json.dumps({"kind": "chart", "name": "pipeline", "payload": payload()}).encode()
    common = f"Host: testserver\r\nCookie: easy_tdx_session={session}\r\n"
    request = (
        f"PUT /api/v1/research/archives/{key} HTTP/1.1\r\n"
        + common
        + f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
    ).encode() + body
    request += ("GET /api/v1/research/archives HTTP/1.1\r\n" + common + "\r\n").encode()
    request += (
        f"GET /api/v1/research/archives/{key} HTTP/1.1\r\n" + common + "Connection: close\r\n\r\n"
    ).encode()
    try:
        protocol.data_received(request)
        await asyncio.wait_for(transport.closed.wait(), 5)
        if state.tasks:
            await asyncio.wait_for(asyncio.gather(*list(state.tasks)), 5)
        responses = bytes(transport.output).split(b"HTTP/1.1 ")[1:]
        assert [row.split(b"\r\n", 1)[0] for row in responses] == [
            b"201 Created",
            b"200 OK",
            b"200 OK",
        ], bytes(transport.output).decode()
        assert json.loads(responses[1].split(b"\r\n\r\n", 1)[1])["items"][0]["id"] == key
        assert json.loads(responses[2].split(b"\r\n\r\n", 1)[1])["payload"] == payload()
        with resource_admission.ResourceStore(store.db_path).connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM resource_leases").fetchone()[0] == 0
    finally:
        protocol.connection_lost(None)
        for task in list(state.tasks):
            task.cancel()
        await asyncio.gather(*list(state.tasks), return_exceptions=True)
