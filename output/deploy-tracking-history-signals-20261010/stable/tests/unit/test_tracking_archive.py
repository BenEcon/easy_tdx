"""Tracking batches preserve full evidence and reuse immutable owner-scoped storage."""

import copy
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.research_archive import ArchiveError, ResearchArchive, encode_archive
from easy_tdx.web.routers.research_archive import build_router


def payload():
    target = {"kind": "stock", "market": "SZ", "code": "300750", "name": "宁德时代"}
    cutoff = "2026-10-10 10:00:00"
    return {
        "format": "tracking-analysis-v2",
        "group": {"id": "g", "name": "观察组", "targets": [target]},
        "revision": "r",
        "periods": ["DAY"],
        "cutoff": cutoff,
        "finished_at": "2026-10-10T02:00:30Z",
        "membership_observed_at": cutoff,
        "state": "completed",
        "phase": "分析完成",
        "error": "",
        "issues": [],
        "rows": [
            {
                "target": target,
                "sources": ["直接追踪"],
                "state": "done",
                "study": {
                    "as_of": cutoff,
                    "rule_version": "frozen-v1",
                    "parameters": {"window": 20},
                    "rows": [{"category": "DAY", "price": 12.123456789}],
                },
                "evidence": {
                    "adjust": "QFQ",
                    "requested_count": 800,
                    "series": [
                        {
                            "category": "DAY",
                            "snapshot": {
                                "metadata": {"actual_adjust": "QFQ", "category": "DAY"},
                                "bars": [
                                    {
                                        "datetime": "2026-10-09 00:00:00",
                                        "open": 12,
                                        "high": 13,
                                        "low": 11,
                                        "close": 12.123456789,
                                        "vol": 100,
                                    }
                                ],
                            },
                        }
                    ],
                },
            }
        ],
    }


def test_roundtrip_restart_duplicate_retry_and_owner_isolation(tmp_path):
    store = ResearchArchive(tmp_path / "history.db")
    key, original = str(uuid.uuid4()), payload()
    record, created = store.create("alice", key, "tracking", original, "batch")
    assert created
    original["rows"][0]["study"]["rows"][0]["price"] = 0
    reopened = ResearchArchive(store.path)
    assert reopened.get("alice", key)["payload"] == payload()
    assert reopened.create("alice", key, "tracking", payload(), "batch")[0] == record
    with pytest.raises(ArchiveError) as error:
        reopened.get("bob", key)
    assert error.value.status == 404
    assert reopened.list("bob")["items"] == []


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p["rows"][0].pop("evidence"),
        lambda p: p["rows"][0]["evidence"].update(adjust="NONE"),
        lambda p: p["rows"][0]["study"]["rows"][0].update(category="WEEK"),
        lambda p: p["rows"].append(copy.deepcopy(p["rows"][0])),
        lambda p: p["rows"][0].update(state="cancelled"),
        lambda p: p.update(state="pending"),
    ],
)
def test_reject_incomplete_or_inconsistent_evidence(change):
    data = payload()
    change(data)
    with pytest.raises(ArchiveError) as error:
        encode_archive("tracking", data, 1_000_000)
    assert error.value.status == 422


def test_cancelled_and_partial_records_are_not_complete():
    data = payload()
    data.update(state="cancelled", rows=[], membership_observed_at="")
    encode_archive("tracking", data, 1_000_000)
    data = payload()
    data.update(state="partial")
    data["rows"][0].update(state="error", error="missing one period")
    encode_archive("tracking", data, 1_000_000)


def test_api_requires_tracking_grant_and_preserves_read_access_after_revocation(tmp_path):
    accounts = AccountStore(tmp_path / "accounts.db")
    admin = accounts.create_user("admin", "test-strong-password", role="admin")
    member = accounts.create_user("member", "test-strong-password")
    current = [member]
    store = ResearchArchive(tmp_path / "archives.db")
    app = FastAPI()
    app.include_router(build_router(lambda: store, lambda: current[0]))
    with TestClient(app) as client:
        path = f"/research/archives/{uuid.uuid4()}"
        body = {"kind": "tracking", "name": "batch", "payload": payload()}
        assert client.put(path, json=body).status_code == 403
        accounts.update_user(member.id, tracking_allowed=True)
        current[0] = accounts.get_user(member.id)
        assert (
            client.put(path, json=body, headers={"X-Research-Owner": admin.id}).status_code == 409
        )
        assert client.put(path, json=body).status_code == 201
        accounts.update_user(member.id, tracking_allowed=False)
        current[0] = accounts.get_user(member.id)
        assert client.get(path).json()["payload"] == payload()
        assert client.put(path, json=body).status_code == 403
