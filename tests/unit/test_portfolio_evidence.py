"""Exact portfolio inputs, slot mapping and both owner-scoped task stores."""

import copy
import json
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from easy_tdx.web import portfolio_evidence as evidence
from easy_tdx.web import task_runner, task_service
from easy_tdx.web.account_store import get_account_store
from easy_tdx.web.backtest_schemas import MultiStrategyBacktestRequest, PortfolioBacktestRequest
from easy_tdx.web.routers import auth, backtest
from easy_tdx.web.schemas import DataFrameResponse
from easy_tdx.web.task_dispatch import dispatch_task
from easy_tdx.web.task_payload import TaskInput, encode_task_input, input_fingerprint
from easy_tdx.web.task_runner import BacktestTaskRunner
from easy_tdx.web.task_store import TaskStore
from tests.unit.test_scan_evidence import frozen, terminal


def bundle(kind):
    shared = dict(
        cash=200000.25,
        commission=0.0003,
        min_commission=5.25,
        stamp_tax=0.001,
        slippage=0.0002,
        execution="next_open",
        adjust="QFQ",
    )
    if kind == "portfolio":
        cases = ["300450-qfq-20261002", "600699-qfq-20260929"]
        request = PortfolioBacktestRequest(
            stocks=["SZ:300450", "SH:600699"],
            strategy="ma_cross",
            params={"fast": 7, "slow": 31},
            category="DAY",
            **shared,
        )
    else:
        cases = ["stock-300750-day-20261009", "stock-300750-min_30-20261009"]
        request = MultiStrategyBacktestRequest(
            items=[
                dict(
                    symbol="SZ:300750",
                    category="DAY",
                    strategy="ma_cross",
                    strategy_label="日线观察",
                    params={"fast": 7, "slow": 31},
                ),
                dict(
                    symbol="SZ:300750",
                    category="MIN_30",
                    strategy="ma_cross",
                    strategy_label="分钟观察",
                    params={"fast": 3, "slow": 15},
                ),
            ],
            **shared,
        )
    frames = tuple(frozen(case)[0].frames[0] for case in cases)
    value = TaskInput(kind, "original-version", request.model_dump(), frames, {})
    result = json.loads(json.dumps(dispatch_task(value)))
    return value, result


@pytest.fixture(scope="module", params=["portfolio", "multi_strategy"])
def original(request):
    return bundle(request.param)


def test_all_members_and_actual_result_are_lossless(original):
    value, result = original
    receipt = evidence.portfolio_evidence(value, result)
    assert receipt["result"] == result
    assert receipt["request"] == value.request
    assert receipt["execution_version"] == "original-version"
    assert len(receipt["members"]) == 2
    for index, member in enumerate(receipt["members"]):
        assert member["index"] == index
        assert member["bars"] == DataFrameResponse.from_dataframe(value.frames[index]).data
        assert member["metadata"] == result["data_provenance"]["datasets"][index]["metadata"]
    assert set(result["individual_results"]) == {m["key"] for m in receipt["members"]}


@pytest.mark.parametrize("backend", ["memory", "durable"])
def test_real_cookie_owner_scope_restart_and_corruption(tmp_path, monkeypatch, original, backend):
    monkeypatch.setenv("EASY_TDX_TASK_BACKEND", backend)
    runner, store = BacktestTaskRunner(), TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr(task_runner, "_RUNNER", runner)
    monkeypatch.setattr(task_service, "get_durable_store", lambda: store)
    monkeypatch.setattr(evidence, "execution_version", lambda: "current-version")
    accounts = get_account_store()
    alice = accounts.create_user("combo-alice", "combo-test-password")
    bob = accounts.create_user("combo-bob", "combo-test-password")
    admin = accounts.create_user("combo-admin", "combo-test-password", role="admin")
    value, result = original
    encoded = encode_task_input(value)
    if backend == "memory":
        task_id = runner.submit(
            lambda: copy.deepcopy(result),
            owner_id=alice.id,
            frozen_input=(encoded, value.execution_version, input_fingerprint(encoded)),
        )
        assert terminal(runner, task_id).status == "done"
    else:
        row, _ = store.submit(alice.id, value)
        task_id = row["task_id"]
        lease = store.claim(value.execution_version, "worker")
        store.finish_after_exit(lease, result=result)
        store = TaskStore(store.path)
    app = FastAPI()
    app.include_router(backtest.router, prefix="/api/v1")
    url = f"/api/v1/backtest/tasks/{task_id}/portfolio-evidence"
    try:
        with TestClient(app) as client:
            assert client.get(url).status_code == 401
            for user in (bob, admin):
                client.cookies.set(auth.SESSION_COOKIE, accounts.create_session(user.id))
                assert client.get(url).status_code == 404
            client.cookies.set(auth.SESSION_COOKIE, accounts.create_session(alice.id))
            assert client.get(url, headers={"X-Task-Owner": bob.id}).status_code == 409
            response = client.get(url, headers={"X-Task-Owner": alice.id})
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["result"] == result
            assert data["execution_version"] == "original-version"
            assert data["current_execution_version"] == "current-version"
            assert response.headers["cache-control"] == "no-store"
            assert (
                "evidence_task_id"
                not in client.get(url.removesuffix("/portfolio-evidence")).json()["result"]
            )
            data["members"][0]["bars"][0]["close"] = 999
            assert client.get(url).json()["members"][0]["bars"][0]["close"] != 999
            if backend == "memory":
                runner.get(task_id).frozen_input = (
                    b"bad",
                    value.execution_version,
                    input_fingerprint(encoded),
                )
            else:
                with store.connect() as db:
                    db.execute("UPDATE tasks SET payload=? WHERE id=?", (b"bad", task_id))
            assert client.get(url).status_code == 409
    finally:
        runner.shutdown()


@pytest.mark.parametrize(
    "change", ["request", "order", "frame", "missing", "extra", "duplicate", "adjust"]
)
def test_inconsistent_inputs_or_results_cannot_claim_complete(original, change):
    value, result = copy.deepcopy(original)
    if change == "request":
        result["data_provenance"]["request"]["cash"] += 1
    elif change == "order":
        result["data_provenance"]["datasets"].reverse()
    elif change == "frame":
        value.frames[0].loc[0, "close"] += 0.01
    elif change == "missing":
        result["individual_results"].pop(next(iter(result["individual_results"])))
    elif change == "extra":
        result["equity_allocation"]["not-a-member"] = 0
    elif change == "duplicate":
        result["data_provenance"]["datasets"][1]["label"] = result["data_provenance"]["datasets"][
            0
        ]["label"]
    elif change == "adjust":
        result["data_provenance"]["datasets"][0]["metadata"]["actual_adjust"] = "NONE"
    with pytest.raises(ValueError):
        evidence.portfolio_evidence(value, result)


def test_duplicate_slot_identity_is_rejected_not_silently_overwritten(original):
    value, _ = original
    request = copy.deepcopy(value.request)
    if value.kind == "portfolio":
        request["stocks"][1] = request["stocks"][0]
    else:
        request["items"][1] = copy.deepcopy(request["items"][0])
    with pytest.raises(ValueError, match="重复"):
        dispatch_task(replace(value, request=request, frames=(value.frames[0], value.frames[0])))


def test_source_read_is_resource_limited_not_cheap_polling():
    from easy_tdx.web.resource_admission import resource_for

    assert resource_for("/api/v1/backtest/tasks/test/portfolio-evidence", "GET") == "data"
    assert resource_for("/api/v1/backtest/tasks/test", "GET") is None


def test_actual_submit_uses_same_frozen_input_for_execution_and_receipt(monkeypatch, original):
    from easy_tdx.backtest.multi_strategy_engine import StrategySlot
    from easy_tdx.backtest.portfolio_engine import StockData
    from easy_tdx.backtest.strategies import get_registry
    from easy_tdx.web.deps import get_client, get_mac_client_optional

    monkeypatch.setenv("EASY_TDX_TASK_BACKEND", "memory")
    runner = BacktestTaskRunner()
    monkeypatch.setattr(task_runner, "_RUNNER", runner)
    value, expected = original
    frames = copy.deepcopy(value.frames)

    async def stocks(*args, **kwargs):
        return [
            StockData(code=s.split(":")[1], market=s.split(":")[0], df=f)
            for s, f in zip(value.request["stocks"], frames)
        ]

    async def slots(*args, **kwargs):
        return [
            StrategySlot(
                label=item["strategy_label"],
                symbol=item["symbol"],
                strategy=get_registry().get(item["strategy"]).build(item["params"]),
                df=f,
            )
            for item, f in zip(value.request["items"], frames)
        ]

    monkeypatch.setattr(backtest, "_fetch_portfolio_bars", stocks)
    monkeypatch.setattr(backtest, "_fetch_multi_strategy_bars", slots)
    accounts = get_account_store()
    user = accounts.create_user("submit-owner", "test-only-password")
    app = FastAPI()
    app.dependency_overrides[get_client] = lambda: object()
    app.dependency_overrides[get_mac_client_optional] = lambda: None
    app.include_router(backtest.router, prefix="/api/v1")
    try:
        with TestClient(app) as client:
            client.cookies.set(auth.SESSION_COOKIE, accounts.create_session(user.id))
            route = "portfolio" if value.kind == "portfolio" else "multi-strategy"
            submitted = client.post(f"/api/v1/backtest/{route}/run/async", json=value.request)
            assert submitted.status_code == 202, submitted.text
            task_id = submitted.json()["task_id"]
            assert terminal(runner, task_id).status == "done"
            response = client.get(f"/api/v1/backtest/tasks/{task_id}/portfolio-evidence")
            assert response.status_code == 200, response.text
            assert response.json()["result"] == expected
            frames[0].loc[0, "close"] = 999
            second = client.get(f"/api/v1/backtest/tasks/{task_id}/portfolio-evidence").json()
            assert second == response.json()
    finally:
        runner.shutdown()
