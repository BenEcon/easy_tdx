"""Complete multi-member archives preserve actual engine output and owner scope."""

import copy
import json
import uuid

import pytest

from easy_tdx.web.portfolio_evidence import portfolio_evidence
from easy_tdx.web.research_archive import ArchiveError, ResearchArchive, encode_archive
from tests.unit.test_portfolio_evidence import bundle
from tests.unit.test_research_archive_api import app_client as archive_app_client
from tests.unit.test_research_archive_api import login

app_client = archive_app_client


def portfolio_payload(kind):
    value, result = bundle(kind)
    return {
        "format": "portfolio-research-v1",
        "title": "完整组合原档",
        "savedAt": "2026-10-10T04:00:00Z",
        "receipt": {
            **portfolio_evidence(value, result),
            "task_id": "original-task",
            "storage": "memory",
            "current_execution_version": "current-version",
        },
    }


@pytest.fixture(scope="module", params=["portfolio", "multi_strategy"])
def original(request):
    return portfolio_payload(request.param)


def test_cookie_roundtrip_and_restore_without_original_task(app_client, original):
    client, _, sessions, _, _ = app_client
    login(client, sessions)
    url = f"/api/v1/research/archives/{uuid.uuid4()}"
    response = client.put(url, json={"kind": "portfolio", "payload": original, "name": "原档"})
    assert response.status_code == 201, response.text
    assert client.get(url).json()["payload"] == original
    for username in ("Bob", "Admin"):
        login(client, sessions, username)
        assert client.get(url).status_code == 404
    login(client, sessions)
    for rev, action in ((1, "delete"), (2, "restore")):
        assert (
            client.post(url + "/actions", json={"revision": rev, "action": action}).status_code
            == 200
        )
    assert client.get(url).json()["payload"] == original


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "extra",
        "order",
        "allocation",
        "metadata",
        "curve",
        "date",
        "request",
        "member_result",
    ],
)
def test_incomplete_or_mismatched_archives_rejected(original, change):
    payload = copy.deepcopy(original)
    r = payload["receipt"]
    if change == "missing":
        r["members"].pop()
    elif change == "extra":
        r["result"]["individual_results"]["extra"] = r["result"]["individual_results"][
            r["members"][0]["key"]
        ]
    elif change == "order":
        r["members"].reverse()
    elif change == "allocation":
        r["result"]["equity_allocation"][r["members"][0]["key"]] = 0.4
    elif change == "metadata":
        r["members"][0]["metadata"]["actual_adjust"] = "NONE"
    elif change == "curve":
        r["result"]["combined_equity"][1]["datetime"] = r["result"]["combined_equity"][0][
            "datetime"
        ]
    elif change == "date":
        item = r["request"] if r["kind"] == "portfolio" else r["request"]["items"][0]
        item["start_date"] = ""
        r["result"]["data_provenance"]["request"] = copy.deepcopy(r["request"])
    elif change == "request":
        r["request"]["cash"] = True
    else:
        r["result"]["individual_results"][r["members"][0]["key"]]["equity_curve"] = []
    with pytest.raises(ArchiveError) as failure:
        encode_archive("portfolio", payload, 25 * 1024 * 1024)
    assert failure.value.status == 422


def test_unknown_fields_null_metrics_and_backup_are_lossless(tmp_path, original):
    from easy_tdx.web.account_store import AccountStore
    from easy_tdx.web.research_backup import create_backup, restore_backup

    payload = copy.deepcopy(original)
    payload["receipt"]["result"]["future"] = {"precision": 0.0000000123456789}
    payload["receipt"]["result"]["total_performance"]["sharpe"] = None
    encoded, _ = encode_archive("portfolio", payload, 25 * 1024 * 1024)
    assert json.loads(encoded) == payload
    source = tmp_path / "source"
    source.mkdir()
    user = AccountStore(source / "accounts.db").create_user(
        "alice", "Test-password-only!", role="admin"
    )
    key = str(uuid.uuid4())
    ResearchArchive(source / "research_archives.db").create(
        user.id, key, "portfolio", payload, "原档"
    )
    create_backup(source, tmp_path / "backup")
    restore_backup(tmp_path / "backup", tmp_path / "restore")
    assert (
        ResearchArchive(tmp_path / "restore/research_archives.db").get(user.id, key)["payload"]
        == payload
    )
