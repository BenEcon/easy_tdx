"""Cookie-based application authentication and account administration API."""

from __future__ import annotations

import os
import re
from typing import Any, Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator

from easy_tdx.web.account_store import UserRecord, get_account_store
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


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=8, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class PasswordResetRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)


class PreferencesRequest(BaseModel):
    preferences: dict[str, Any] = Field(default_factory=dict)


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
) -> UserRecord:
    user = get_account_store().get_user_for_session(session or "")
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
        )
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
async def setup_admin(req: Credentials, response: Response) -> dict[str, Any]:
    store = get_account_store()
    if store.count_users() != 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="系统已经完成初始化")
    admin = store.create_user(req.username, req.password, role="admin")
    get_store().claim_unowned(admin.id)
    admin = store.authenticate(req.username, req.password) or admin
    token = store.create_session(admin.id)
    _set_session_cookie(response, token)
    return {"user": _public_user(admin), "message": "管理员账户已创建"}


@router.post("/auth/login")
async def login(req: Credentials, response: Response) -> dict[str, Any]:
    store = get_account_store()
    user = store.authenticate(req.username, req.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误，或账户已停用",
        )
    token = store.create_session(user.id)
    _set_session_cookie(response, token)
    return {"user": _public_user(user)}


@router.post("/auth/logout")
async def logout(
    response: Response,
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, bool]:
    get_account_store().delete_session(session or "")
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
    updated = get_account_store().set_preferences(user.id, req.preferences)
    return {"user": _public_user(updated)}


@router.post("/auth/change-password")
async def change_password(
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
    store.set_password(user.id, req.new_password)
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


@router.post("/admin/users", status_code=201)
async def create_user(
    req: CreateUserRequest,
    _: UserRecord = Depends(require_admin),
) -> dict[str, Any]:
    user = get_account_store().create_user(req.username, req.password, role=req.role)
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
    updated = store.update_user(user_id, role=req.role, active=req.active)
    return {"user": _public_user(updated, include_stats=True)}


@router.post("/admin/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    req: PasswordResetRequest,
    _: UserRecord = Depends(require_admin),
) -> dict[str, bool]:
    get_account_store().set_password(user_id, req.new_password)
    return {"ok": True}
