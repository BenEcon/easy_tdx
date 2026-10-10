"""Cookie-based application authentication and account administration API."""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Literal

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, Field, field_validator

from easy_tdx.web.account_store import (
    LoginThrottled,
    SetupAlreadyComplete,
    UserRecord,
    get_account_store,
)
from easy_tdx.web.strategy_store import get_store

router = APIRouter(tags=["accounts"])

SESSION_COOKIE = "easy_tdx_session"
SESSION_MAX_AGE = 30 * 24 * 60 * 60
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_\-.\u4e00-\u9fff]+$")


class Credentials(BaseModel):
    username: str = Field(..., min_length=2, max_length=40)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        clean = value.strip()
        if not USERNAME_PATTERN.fullmatch(clean):
            raise ValueError("用户名只能包含中英文、数字、点、横线或下划线")
        return clean


class CreateUserRequest(Credentials):
    role: Literal["admin", "user"] = "user"


class UserUpdateRequest(BaseModel):
    role: Literal["admin", "user"] | None = None
    active: bool | None = None
    tracking_allowed: bool | None = Field(default=None, strict=True)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=8, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class PasswordResetRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)


class PreferencesRequest(BaseModel):
    preferences: dict[str, Any] = Field(default_factory=dict)
    tracking_revision: str | None = Field(default=None, max_length=100)


def _public_user(user: UserRecord, *, include_stats: bool = False) -> dict[str, Any]:
    body = user.to_public_dict()
    if include_stats:
        body["saved_strategy_count"] = get_store().count_for_owner(user.id)
    return body


def _set_session_cookie(response: Response, token: str) -> None:
    secure = os.environ.get("EASY_TDX_SECURE_COOKIES", "").lower() in {"1", "true", "yes"}
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="lax")


def get_current_user(
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    tracking_owner: str | None = Header(default=None, alias="X-Tracking-Owner"),
) -> UserRecord:
    user = get_account_store().get_user_for_session(session or "")
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
        )
    if isinstance(tracking_owner, str):
        if tracking_owner != user.id:
            raise HTTPException(409, "账户已切换，追踪分析已停止")
        if not user.can_track:
            raise HTTPException(403, "追踪标的权限已撤销，分析已停止")
    return user


def require_admin(user: UserRecord = Depends(get_current_user)) -> UserRecord:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


@router.get("/auth/status")
async def auth_status(
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, Any]:
    store = get_account_store()
    user = store.get_user_for_session(session or "")
    return {
        "setup_required": store.count_users() == 0,
        "authenticated": user is not None,
        "user": _public_user(user) if user else None,
    }


@router.post("/auth/setup", status_code=201)
def setup_admin(req: Credentials, request: Request, response: Response) -> dict[str, Any]:
    store = get_account_store()
    if store.count_users() != 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="系统已经完成初始化")
    _reserve_attempt(req, request)
    try:
        admin = store.create_user(req.username, req.password, role="admin", initial=True)
    except SetupAlreadyComplete as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    get_store().claim_unowned(admin.id)
    admin = store.authenticate(req.username, req.password) or admin
    token = store.create_session(admin.id)
    _set_session_cookie(response, token)
    _record_login(admin, request)
    return {"user": _public_user(admin), "message": "管理员账户已创建"}


@router.post("/auth/login")
def login(req: Credentials, request: Request, response: Response) -> dict[str, Any]:
    store = get_account_store()
    _reserve_attempt(req, request)
    user = store.authenticate(req.username, req.password)
    store.audit_login(user)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误，或账户已停用",
        )
    token = store.create_session(user.id)
    _set_session_cookie(response, token)
    _record_login(user, request)
    return {"user": _public_user(user)}


def _record_login(user: UserRecord, request: Request) -> None:
    from easy_tdx.web.user_activity import get_activity_store

    try:
        get_activity_store().record(
            user.id, "login", request.client.host if request.client else "", "登录", "accepted"
        )
    except Exception:
        logging.getLogger(__name__).warning("Login activity could not be persisted", exc_info=True)


def _reserve_attempt(req: Credentials, request: Request) -> None:
    peer = request.client.host if request.client else "unknown"
    try:
        get_account_store().reserve_login_attempt(req.username, peer)
    except LoginThrottled as exc:
        raise HTTPException(
            status_code=429, detail=str(exc), headers={"Retry-After": str(exc.retry_after)}
        ) from exc


@router.post("/auth/logout")
async def logout(
    response: Response,
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, bool]:
    store = get_account_store()
    user = store.get_user_for_session(session or "")
    store.delete_session(session or "")
    if user:
        store.audit_operation("logout", user.id)
    _clear_session_cookie(response)
    return {"ok": True}


@router.post("/auth/logout-all")
def logout_all(response: Response, user: UserRecord = Depends(get_current_user)) -> dict[str, bool]:
    get_account_store().invalidate_user_sessions(user.id)
    get_account_store().audit_operation("logout_all", user.id)
    _clear_session_cookie(response)
    return {"ok": True}


@router.get("/auth/me")
async def me(user: UserRecord = Depends(get_current_user)) -> dict[str, Any]:
    return {"user": _public_user(user, include_stats=True)}


@router.put("/auth/me/preferences")
async def save_preferences(
    req: PreferencesRequest,
    user: UserRecord = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        updated = get_account_store().set_preferences(
            user.id,
            req.preferences,
            expected_tracking_revision=req.tracking_revision,
            require_tracking_revision=True,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        from easy_tdx.web.account_store import TrackingRevisionConflict

        raise HTTPException(
            409 if isinstance(exc, TrackingRevisionConflict) else 422, str(exc)
        ) from exc
    return {"user": _public_user(updated)}


@router.patch("/auth/me/preferences")
def patch_preferences(
    req: PreferencesRequest,
    request: Request,
    user: UserRecord = Depends(get_current_user),
) -> dict[str, Any]:
    # The header is not authentication: it binds a queued browser write to the
    # already authenticated cookie owner, including cross-tab login changes.
    if request.headers.get("x-preferences-owner") != user.id:
        raise HTTPException(409, "登录账户已变化或缺少偏好归属，请刷新页面后重试")
    try:
        updated = get_account_store().set_preferences(
            user.id,
            req.preferences,
            merge=True,
            expected_tracking_revision=req.tracking_revision,
            require_tracking_revision=True,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        from easy_tdx.web.account_store import TrackingRevisionConflict

        raise HTTPException(
            409 if isinstance(exc, TrackingRevisionConflict) else 422, str(exc)
        ) from exc
    return {"user": _public_user(updated)}


@router.post("/auth/change-password")
def change_password(
    req: PasswordChangeRequest,
    response: Response,
    user: UserRecord = Depends(get_current_user),
) -> dict[str, Any]:
    store = get_account_store()
    if store.authenticate(user.username, req.current_password) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码不正确")
    if req.current_password == req.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="新密码不能与当前密码相同"
        )
    store.set_password(user.id, req.new_password, actor_id=user.id)
    token = store.create_session(user.id)
    _set_session_cookie(response, token)
    return {"ok": True}


@router.get("/admin/users")
async def list_users(_: UserRecord = Depends(require_admin)) -> dict[str, Any]:
    users = [_public_user(user, include_stats=True) for user in get_account_store().list_users()]
    return {
        "users": users,
        "count": len(users),
        "active_count": sum(1 for user in users if user["active"]),
    }


@router.get("/admin/audit")
def list_audit(
    before: int | None = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=100),
    action: str | None = Query(None, max_length=40, pattern=r"^[a-z_]+$"),
    outcome: Literal["success", "denied", "failed"] | None = None,
    _: UserRecord = Depends(require_admin),
) -> dict[str, Any]:
    return get_account_store().list_audit(
        before=before, limit=limit, action=action, outcome=outcome
    )


@router.post("/admin/users", status_code=201)
def create_user(
    req: CreateUserRequest,
    admin: UserRecord = Depends(require_admin),
) -> dict[str, Any]:
    user = get_account_store().create_user(
        req.username, req.password, role=req.role, actor_id=admin.id
    )
    return {"user": _public_user(user, include_stats=True)}


@router.patch("/admin/users/{user_id}")
async def update_user(
    user_id: str,
    req: UserUpdateRequest,
    admin: UserRecord = Depends(require_admin),
) -> dict[str, Any]:
    store = get_account_store()
    target = store.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账户不存在")
    removing_admin = target.role == "admin" and (req.role == "user" or req.active is False)
    if removing_admin and store.count_active_admins() <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="必须至少保留一位启用的管理员"
        )
    if user_id == admin.id and req.active is False:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能停用当前登录账户")
    updated = store.update_user(
        user_id,
        role=req.role,
        active=req.active,
        tracking_allowed=req.tracking_allowed,
        actor_id=admin.id,
    )
    return {"user": _public_user(updated, include_stats=True)}


@router.post("/admin/users/{user_id}/reset-password")
def reset_password(
    user_id: str,
    req: PasswordResetRequest,
    admin: UserRecord = Depends(require_admin),
) -> dict[str, bool]:
    get_account_store().set_password(user_id, req.new_password, actor_id=admin.id)
    return {"ok": True}
