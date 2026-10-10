"""Recompute archived inputs explicitly, preserve the original and disclose runtime identity."""

from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from pydantic import ValidationError

from easy_tdx.web.routers import chanlun_archive as module
from easy_tdx.web.routers.chanlun_observations import observations
from easy_tdx.web.routers.chanlun_replay import replay_snapshot
from tests.unit.test_chanlun_replay import snapshot


def request(kind="chart", category="DAY"):
    bars = [dict(row, amount=1000) for row in snapshot(40)]
    if kind == "chart":
        payload = {"code": "test", "category": category, "bars": bars, "visible_count": 40}
    else:
        payload = {
            "as_of": "2026-03-01 15:00:00",
            "series": [{"code": "test", "category": category, "bars": bars, "bar_time": "start"}],
            "volume_multiple": 2,
            "squeeze_quantile": 0.2,
            "ma_periods": [5, 10],
            "window_bars": 20,
            "window_start": None,
            "window_end": None,
        }
    return {"request_id": str(uuid4()), "kind": kind, kind: payload}


@pytest.mark.parametrize(
    "kind,category", [("chart", "DAY"), ("chart", "MIN_120"), ("study", "DAY")]
)
def test_real_recompute_matches_current_engine_without_changing_input(kind, category):
    raw = request(kind, category)
    original = deepcopy(raw)
    parsed = module.ArchiveRecomputeRequest.model_validate(raw)
    response = Response()
    value = module.recompute_archive(parsed, response)
    expected = (
        replay_snapshot(parsed.chart, "summary") if kind == "chart" else observations(parsed.study)
    )
    assert value["result"] == expected
    assert value["request_id"] == raw["request_id"]
    assert value["execution_version"].startswith("research-execution-v1:")
    assert len(value["input_digest"]) == 64
    assert value["historical_data_vintage"] is False
    assert response.headers["cache-control"] == "no-store"
    assert raw == original
    repeated = module.recompute_archive(parsed, Response())
    assert repeated == value


@pytest.mark.parametrize(
    "case",
    ["partial", "missing_volume", "missing_amount", "oversized", "both", "wrong_kind", "extra"],
)
def test_no_implicit_truncation_zero_filling_or_mixed_inputs(case):
    raw = request()
    if case == "partial":
        raw["chart"]["visible_count"] = 20
    elif case == "missing_volume":
        del raw["chart"]["bars"][0]["vol"]
    elif case == "missing_amount":
        del raw["chart"]["bars"][0]["amount"]
    elif case == "oversized":
        raw["chart"]["bars"] = snapshot(801)
    elif case == "both":
        raw["study"] = request("study")["study"]
    elif case == "wrong_kind":
        raw["kind"] = "study"
    else:
        raw["overwrite_archive"] = True
    with pytest.raises(ValidationError):
        module.ArchiveRecomputeRequest.model_validate(raw)


@pytest.mark.parametrize(
    "field", ["volume_multiple", "window_start", "window_end", "ma_periods", "bar_time"]
)
def test_missing_study_parameters_are_not_replaced_by_defaults(field):
    raw = request("study")
    if field == "bar_time":
        del raw["study"]["series"][0][field]
    else:
        del raw["study"][field]
    with pytest.raises(ValidationError):
        module.ArchiveRecomputeRequest.model_validate(raw)


def test_source_change_during_execution_rejects_result(monkeypatch):
    versions = iter(["before", "after"])
    monkeypatch.setattr(module, "execution_version", lambda: next(versions))
    with pytest.raises(HTTPException) as error:
        module.recompute_archive(
            module.ArchiveRecomputeRequest.model_validate(request()), Response()
        )
    assert error.value.status_code == 409


def test_120_minute_replay_uses_actual_period_without_relabelling():
    from easy_tdx.web.routers.chanlun_replay import ReplayRequest

    raw = request(category="MIN_120")["chart"]
    parsed = ReplayRequest.model_validate(raw)
    assert replay_snapshot(parsed)["frequency"] == "120min"


def test_formal_route_requires_auth_and_uses_compute_admission(tmp_path, monkeypatch):
    from easy_tdx.web import account_store
    from easy_tdx.web.app import _create_app
    from easy_tdx.web.resource_admission import admit_research, resource_for

    accounts = account_store.AccountStore(tmp_path / "accounts.db")
    monkeypatch.setattr(account_store, "_store", accounts)
    app = _create_app(host="127.0.0.1", enable_mac=False)
    client = TestClient(app)
    body = module.ArchiveRecomputeRequest.model_validate(request()).model_dump(mode="json")
    assert client.post("/api/v1/chanlun/archive-recompute", json=body).status_code == 401
    route = next(
        row for row in app.routes if getattr(row, "path", "") == "/api/v1/chanlun/archive-recompute"
    )
    assert admit_research in [dep.call for dep in route.dependant.dependencies]
    assert resource_for(route.path, "POST") == "compute"
    user = accounts.create_user("qa-user", "recompute-test-password")
    client.cookies.set("easy_tdx_session", accounts.create_session(user.id))
    for expected in [None, "another-user"]:
        headers = {"X-Query-Origin": "user"}
        if expected:
            headers["X-Research-Owner"] = expected
        assert client.post(route.path, json=body, headers=headers).status_code == 409
    result = client.post(
        route.path,
        json=body,
        headers={"X-Query-Origin": "user", "X-Research-Owner": user.id},
    )
    assert result.status_code == 200 and result.json()["contract"] == "archive-recompute-v1"
    from easy_tdx.web.user_activity import get_activity_store

    entries = get_activity_store().events(days=1, owner=user.id, kind="query")["items"]
    assert len(entries) == 1 and entries[0]["details"]["code"] == "test"
    assert "bars" not in entries[0]["details"]
