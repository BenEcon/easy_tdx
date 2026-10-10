from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from easy_tdx.web.account_store import UserRecord
from easy_tdx.web.routers import server
from easy_tdx.web.routers.auth import get_current_user


@pytest.fixture
def server_app(monkeypatch):
    app = FastAPI()
    app.state.tdx_client = None
    app.include_router(server.router, prefix="/api/v1")
    actor = {"user": None}

    def identity():
        if actor["user"] is None:
            raise HTTPException(401, "请先登录")
        return actor["user"]

    app.dependency_overrides[get_current_user] = identity
    monkeypatch.setattr(server, "get_known_hosts", lambda: ["1.2.3.4"])
    monkeypatch.setattr(server, "get_best_host", lambda: "1.2.3.4")
    probe = Mock(return_value=[("1.2.3.4", 0.05)])
    monkeypatch.setattr(server, "ping_all", probe)
    with TestClient(app) as client:
        yield app, client, actor, probe


def test_regular_users_read_but_cannot_probe_or_switch_global_server(server_app):
    _, client, actor, probe = server_app
    assert client.get("/api/v1/server/hosts").status_code == 401
    actor["user"] = UserRecord(id="user", username="User")
    assert client.get("/api/v1/server/hosts").status_code == 200
    assert client.post("/api/v1/server/test", json={}).status_code == 403
    assert client.post("/api/v1/server/switch", json={"host": "1.2.3.4"}).status_code == 403
    probe.assert_not_called()


def test_admin_probes_only_configured_nodes_with_bounded_time_and_single_flight(server_app):
    app, client, actor, probe = server_app
    actor["user"] = UserRecord(id="admin", username="Admin", role="admin")
    for payload in (
        {"hosts": ["127.0.0.1"]},
        {"timeout": 0},
        {"timeout": 11},
        {"hosts": ["1.2.3.4"] * 129},
    ):
        assert client.post("/api/v1/server/test", json=payload).status_code == 422
    probe.assert_not_called()
    response = client.post("/api/v1/server/test", json={"hosts": ["1.2.3.4", "1.2.3.4"]})
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert probe.call_args.args[0] == ["1.2.3.4"]
    app.state.server_probe_task = SimpleNamespace(done=lambda: False)
    busy = client.post("/api/v1/server/test", json={})
    assert busy.status_code == 429 and busy.headers["retry-after"] == "10"
    assert probe.call_count == 1


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_probe_timeout_rejected(timeout):
    with pytest.raises(ValueError):
        server.ServerTestRequest(timeout=timeout)
