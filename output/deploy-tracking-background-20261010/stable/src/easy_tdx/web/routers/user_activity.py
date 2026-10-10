"""Own presence heartbeat and administrator-only activity reports."""

from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from easy_tdx.web.account_store import UserRecord, get_account_store
from easy_tdx.web.activity_geo import local_location, lookup_location
from easy_tdx.web.routers.auth import get_current_user, require_admin
from easy_tdx.web.user_activity import RETENTION_DAYS, get_activity_store

router = APIRouter(tags=["activity"])


class HeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    restart: bool = Field(default=False, strict=True)


@router.post("/auth/activity")
def heartbeat(
    body: HeartbeatRequest,
    request: Request,
    response: Response,
    user: UserRecord = Depends(get_current_user),
) -> dict[str, Any]:
    if request.headers.get("x-research-owner") != user.id:
        raise HTTPException(409, "登录账户已变化，未记录到其他账户")
    response.headers["Cache-Control"] = "no-store"
    get_activity_store().heartbeat(user.id, restart=body.restart)
    return {
        "ok": True,
        "tracking_allowed": user.tracking_allowed,
        "role": user.role,
        "active": user.active,
    }


@router.get("/admin/activity/summary")
def summary(
    response: Response,
    days: int = Query(7, ge=1, le=90),
    offset: int = Query(0, ge=0, le=100_000),
    user_id: str | None = Query(None, max_length=40),
    _: UserRecord = Depends(require_admin),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    users = get_account_store().list_users()
    if user_id:
        users = [user for user in users if user.id == user_id]
    stats = get_activity_store().summary(days)
    items = []
    for user in users[offset : offset + 50]:
        row = stats.get(user.id, {})
        items.append(
            {
                "id": user.id,
                "username": user.username,
                "active_seconds": row.get("active_seconds", 0),
                "queries": row.get("queries", 0),
                "logins": row.get("logins", 0),
                "last_seen": row.get("last_seen"),
                "recently_active": user.active and time.time() - (row.get("last_ping") or 0) <= 45,
            }
        )
    return {
        "items": items,
        "total": len(users),
        "next_offset": offset + 50 if offset + 50 < len(users) else None,
        "days": days,
        "retention_days": RETENTION_DAYS,
    }


@router.get("/admin/activity/events")
def events(
    response: Response,
    days: int = Query(7, ge=1, le=90),
    user_id: str | None = Query(None, max_length=40),
    kind: Literal["login", "query"] | None = None,
    before: int | None = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=100),
    _: UserRecord = Depends(require_admin),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    result = get_activity_store().events(
        days=days, owner=user_id, kind=kind, before=before, limit=limit
    )
    users = {user.id: user.username for user in get_account_store().list_users()}
    for item in result["items"]:
        item["username"] = users.get(item["owner"], "已删除账户")
        item["location"] = local_location(item["ip"]) or item["location"]
    return result


@router.post("/admin/activity/events/{event_id}/location")
def location(
    event_id: int, response: Response, _: UserRecord = Depends(require_admin)
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    store = get_activity_store()
    ip = store.event_ip(event_id)
    if ip is None:
        raise HTTPException(404, "记录不存在或已过保留期限")
    result = local_location(ip)
    if result:
        return result
    result = store.reserve_geo(ip)
    if result is not None:
        return result
    result = lookup_location(ip)
    return store.save_geo(ip, result)
