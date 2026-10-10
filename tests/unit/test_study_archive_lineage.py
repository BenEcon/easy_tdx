"""Full selected-period coverage and independent scan lineage in research archives."""

import copy
import uuid

import pytest

from easy_tdx.web.research_archive import ArchiveError, ResearchArchive
from tests.unit.test_radar_archive import radar_payload
from tests.unit.test_research_archive_api import app_client as archive_app_client
from tests.unit.test_research_archive_api import login

app_client = archive_app_client


def study_payload(empty=False):
    chart = radar_payload()
    return {
        "format": "chanlun-research-snapshot-v2",
        "code": chart["target"]["code"],
        "instrument": chart["target"],
        "as_of": chart["cutoff"],
        "adjust": "QFQ",
        "radarSource": chart["radarSource"],
        "collection": {
            "contract": "study-collection-v1",
            "selected_periods": ["WEEK", "DAY"],
            "execution": "not_started" if empty else "completed",
        },
        "result": {
            "rows": [
                {"category": "WEEK", "error": "原节点取数失败", "failure_stage": "collection"},
                {"category": "DAY", "error": "原计算未返回"},
            ]
        },
        "series": []
        if empty
        else [
            {
                "category": "DAY",
                "snapshot": {
                    "bars": chart["charts"][0]["bars"],
                    "metadata": chart["charts"][0]["metadata"],
                },
            }
        ],
    }


@pytest.mark.parametrize("empty", [False, True])
def test_cookie_roundtrip_preserves_failures_original_input_and_owner_boundary(app_client, empty):
    client, _, sessions, _, _ = app_client
    login(client, sessions)
    data = study_payload(empty)
    key = str(uuid.uuid4())
    url = f"/api/v1/research/archives/{key}"
    response = client.put(url, json={"kind": "study", "payload": data, "name": "完整周期记录"})
    assert response.status_code == 201, response.text
    assert client.get(url).json()["payload"] == data
    assert client.get(url).json()["provenance"] == "client_archive_not_server_verified"
    for name in ("Bob", "Admin"):
        login(client, sessions, name)
        assert client.get(url).status_code == 404


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_row",
        "extra_row",
        "missing_selection",
        "duplicate",
        "foreign_source",
        "wrong_code",
        "wrong_reference",
        "fake_success",
        "no_collection",
        "false_completed",
        "bad_collection",
        "bad_stage",
        "bad_period",
        "unselected_series",
    ],
)
def test_malformed_coverage_or_lineage_cannot_be_uploaded(tmp_path, mutation):
    data = study_payload(empty=mutation in {"fake_success", "no_collection", "false_completed"})
    if mutation == "missing_row":
        data["result"]["rows"].pop()
    elif mutation == "extra_row":
        data["result"]["rows"].append({"category": "MONTH", "error": "extra"})
    elif mutation == "missing_selection":
        data["collection"]["selected_periods"].append("MONTH")
    elif mutation == "duplicate":
        data["collection"]["selected_periods"] = ["DAY", "DAY"]
    elif mutation == "foreign_source":
        data["instrument"]["market"] = "SH"
    elif mutation == "wrong_code":
        data["code"] = "300750"
    elif mutation == "wrong_reference":
        data["radarSource"]["receipt"]["task_id"] = "b" * 32
    elif mutation == "fake_success":
        data["result"]["rows"][0].pop("error")
    elif mutation == "no_collection":
        data.pop("collection")
    elif mutation == "false_completed":
        data["collection"]["execution"] = "completed"
    elif mutation == "bad_collection":
        data["collection"] = None
    elif mutation == "bad_stage":
        data["collection"]["execution"] = "unknown"
    elif mutation == "bad_period":
        data["collection"]["selected_periods"][0] = {}
    else:
        data["series"][0]["category"] = "MONTH"
    store = ResearchArchive(tmp_path / "archives.db")
    with pytest.raises(ArchiveError) as exc:
        store.create("alice", str(uuid.uuid4()), "study", data, "invalid")
    assert exc.value.status == 422
    assert store.list("alice")["items"] == []


def test_legacy_study_is_preserved_without_inventing_missing_selection(tmp_path):
    data = study_payload()
    data.pop("radarSource")
    data.pop("collection")
    before = copy.deepcopy(data)
    store = ResearchArchive(tmp_path / "archives.db")
    row, _ = store.create("alice", str(uuid.uuid4()), "study", data, "旧档")
    assert store.get("alice", row["id"])["payload"] == before
