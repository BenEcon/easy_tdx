"""Code grouping is full-scope, market-aware, deduplicated and administrator-only."""

import json
import time

from easy_tdx.web.activity_targets import query_targets, targets_json
from easy_tdx.web.user_activity import ActivityStore
from tests.unit.test_user_activity import cookie, setup  # noqa: F401


def test_identities_and_no_market_guess():
    result = query_targets(
        {
            "market": "SZ",
            "code": "000001",
            "stock_code": "000001",
            "stocks": [["SH", "000001"], {"market": "SZ", "code": "000001"}],
            "series": [
                {"code": "index:SH:000001"},
                {"code": "board:SH:881001"},
                {"code": "SZ300750"},
            ],
            "symbol": "SH:600000,300450",
            "board_code": "881001",
        }
    )
    assert {row["key"] for row in result} == {
        "SZ:000001",
        "SH:000001",
        "BOARD:881001",
        "SZ:300750",
        "SH:600000",
        "SZ:300450",
    }
    assert query_targets({"code": "000001"}) == [
        {"key": "?:000001", "code": "000001", "market": "?"}
    ]
    assert query_targets({"symbol": "SH:000001,000001"})[-1]["market"] == "?"
    assert (
        query_targets({"kind": "board", "market": "SH", "code": "881001"})[0]["key"]
        == "BOARD:881001"
    )
    assert query_targets({"codes": ["<script>", None, {}, "bad:many:colons:here"]}) == []
    assert targets_json("bad JSON") == "[]"
    assert targets_json("null") == "[]"


def test_groups_all_pages_deduplicate_and_filter(tmp_path):
    store = ActivityStore(tmp_path / "activity.db")
    for _ in range(56):
        store.record(
            "alice",
            "query",
            "",
            "分析",
            "accepted",
            {"code": "000001", "market": "SZ", "stocks": [["SZ", "000001"], ["SH", "000001"]]},
        )
    store.record("bob", "query", "", "分析", "failed", {"market": "SZ", "code": "000001"})
    store.record("bob", "query", "", "概览", "accepted")
    store.record("bob", "login", "", "登录", "accepted")
    with store.connect() as db:
        db.execute(
            "INSERT INTO activity_events(owner,occurred,kind,ip,feature,outcome,details) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                "legacy",
                time.time(),
                "query",
                "",
                "旧版",
                "accepted",
                json.dumps({"code": "000001", "market": "SZ"}),
            ),
        )
    groups = store.code_groups(days=1, limit=1)
    assert groups["next_offset"] == 1
    assert groups["items"][0]["queries"] == 57
    assert groups["items"][0]["users"] == 2
    assert groups["items"][0]["key"] == "SZ:000001"
    assert store.code_groups(days=1, offset=1, limit=1)["items"][0]["queries"] == 56
    assert store.code_groups(days=1, code="000001")["items"][1]["market"] == "SH"
    assert store.code_groups(days=1, code="SH:000001", owner="bob")["items"] == []
    page = store.events(days=1, code="SZ:000001", limit=50)
    assert len(page["items"]) == 50
    rest = store.events(days=1, code="SZ:000001", before=page["next_cursor"])
    assert len(rest["items"]) == 7
    assert not {e["id"] for e in page["items"]} & {e["id"] for e in rest["items"]}
    assert all(e["targets"] for e in page["items"])
    assert store.events(days=1, code="0000")["items"] == []
    assert store.events(days=1, kind="login", code="000001")["items"] == []
    assert store.code_groups(days=1, code="000001' OR 1=1 --")["items"] == []
    with store.connect() as db:
        db.execute(
            "UPDATE activity_events SET occurred=? WHERE owner='alice'", (time.time() - 3 * 86400,)
        )
    assert store.code_groups(days=1)["items"][0]["queries"] == 1


def test_group_routes_permissions_and_bounds(setup):  # noqa: F811
    accounts, admin, member, client, log = setup
    assert client.get("/api/v1/admin/activity/codes").status_code == 401
    cookie(client, accounts, member)
    assert client.get("/api/v1/admin/activity/codes").status_code == 403
    cookie(client, accounts, admin)
    log.record(member.id, "query", "", "分析", "accepted", {"code": "300750", "market": "SZ"})
    response = client.get("/api/v1/admin/activity/codes?code=SZ:300750")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["items"][0]["queries"] == 1
    assert (
        client.get("/api/v1/admin/activity/events?code=300750").json()["items"][0]["targets"][0][
            "key"
        ]
        == "SZ:300750"
    )
    for suffix in ("code=x%27", "days=91", "offset=-1", "limit=101"):
        assert client.get(f"/api/v1/admin/activity/codes?{suffix}").status_code == 422
    assert client.get("/api/v1/admin/activity/events?code=x%27").status_code == 422


def test_group_identity_is_not_json_array_position(tmp_path):
    store = ActivityStore(tmp_path / "activity.db")
    for market, code in [("SZ", "300750"), ("SZ", "300450"), ("SH", "000001"), ("SZ", "000001")]:
        store.record("alice", "query", "", "分析", "accepted", {"market": market, "code": code})
    store.record(
        "bob", "query", "", "批量", "accepted", {"stocks": [["SZ", "300750"], ["SZ", "300450"]]}
    )
    store.record("bob", "query", "", "板块", "accepted", {"board_code": "881001"})
    groups = {row["key"]: row["queries"] for row in store.code_groups(days=1)["items"]}
    assert groups == {
        "SZ:300750": 2,
        "SZ:300450": 2,
        "SH:000001": 1,
        "SZ:000001": 1,
        "BOARD:881001": 1,
    }
