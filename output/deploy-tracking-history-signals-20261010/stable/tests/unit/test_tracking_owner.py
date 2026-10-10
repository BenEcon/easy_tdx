"""Background tracking requests stay bound to the launching account and access grant."""

from tests.unit.test_user_activity import cookie, setup  # noqa: F401


def test_tracking_context_rejects_cookie_switch_and_revocation(setup):  # noqa: F811
    store, admin, member, client, log = setup
    headers = {"X-Tracking-Owner": member.id, "X-Query-Origin": "user"}
    cookie(client, store, admin)
    assert client.post("/api/v1/chanlun/analyze", json={}, headers=headers).status_code == 409
    assert log.events(days=1)["items"] == []
    cookie(client, store, member)
    assert client.post("/api/v1/chanlun/analyze", json={}, headers=headers).status_code == 403
    store.update_user(member.id, tracking_allowed=True)
    assert client.post("/api/v1/chanlun/analyze", json={}, headers=headers).status_code == 200
    store.update_user(member.id, tracking_allowed=False)
    assert client.post("/api/v1/chanlun/analyze", json={}, headers=headers).status_code == 403
    assert len(log.events(days=1)["items"]) == 1
    # Regular individual research still uses its original access policy.
    assert client.post("/api/v1/chanlun/analyze", json={}).status_code == 200
    cookie(client, store, admin)
    assert (
        client.post(
            "/api/v1/chanlun/analyze", json={}, headers={"X-Tracking-Owner": admin.id}
        ).status_code
        == 200
    )
