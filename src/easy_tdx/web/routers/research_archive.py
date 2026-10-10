"""Authenticated immutable research archive API."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from easy_tdx.web.account_store import AccountStore, UserRecord, get_account_store
from easy_tdx.web.archive_ingress import retain_current_archive_upload
from easy_tdx.web.research_archive import ArchiveError, ResearchArchive, get_research_archive
from easy_tdx.web.resource_admission import Admission, retain_current_admission
from easy_tdx.web.routers.auth import get_current_user


class CreateArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["chart", "study", "backtest", "portfolio", "factor", "tracking"]
    payload: dict[str, Any]
    name: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=4000)


class ChangeArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: StrictInt = Field(ge=1)
    action: Literal["edit", "delete", "restore", "purge"]
    name: str | None = Field(default=None, min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=4000)


class FactorTrackingSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=40)
    score_key: str = Field(min_length=1, max_length=100)
    symbols: list[str] = Field(min_length=1, max_length=20)
    labels: dict[str, str] = Field(default_factory=dict, max_length=20)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision: StrictInt = Field(ge=1)


def build_router(
    store_provider: Callable[[], ResearchArchive],
    identity: Callable[..., UserRecord],
    account_provider: Callable[[], AccountStore] = get_account_store,
) -> APIRouter:
    def matching_account(
        user: UserRecord = Depends(identity),
        expected: str | None = Header(default=None, alias="X-Research-Owner"),
    ) -> None:
        # The header only asserts the expected account; it never grants access.
        if expected is not None and expected != user.id:
            raise HTTPException(409, "登录账户已变化，请刷新页面后重试")

    router = APIRouter(
        prefix="/research/archives",
        tags=["research archives"],
        dependencies=[Depends(matching_account)],
    )

    def call(operation: Callable[[], Any], response: Response) -> Any:
        response.headers["Cache-Control"] = "no-store"
        retained: list[Admission] = []
        try:
            # Sync SQLite work can outlive its HTTP waiter. Keep both upload
            # memory capacity and the normal data slot until this thread exits.
            for retain in (retain_current_admission, retain_current_archive_upload):
                handle = retain()
                if handle is not None:
                    retained.append(handle)
            return operation()
        except ArchiveError as exc:
            raise HTTPException(
                exc.status, str(exc), headers={"Cache-Control": "no-store"}
            ) from exc
        except (sqlite3.Error, OSError) as exc:
            raise HTTPException(
                503, "研究存档暂不可用，请稍后重试", headers={"Cache-Control": "no-store"}
            ) from exc
        finally:
            for handle in retained:
                handle.release()

    @router.get("")
    def listing(response: Response, user: UserRecord = Depends(identity)) -> Any:
        return call(lambda: store_provider().list(user.id), response)

    @router.get("/{key}")
    def read(key: str, response: Response, user: UserRecord = Depends(identity)) -> Any:
        record = call(lambda: store_provider().get(user.id, key), response)
        response.headers["ETag"] = f'"{record["revision"]}"'
        return record

    @router.put("/{key}")
    def create(
        key: str, body: CreateArchive, response: Response, user: UserRecord = Depends(identity)
    ) -> Any:
        if body.kind == "tracking" and not user.can_track:
            raise HTTPException(403, "当前账户没有追踪分析权限")
        record, created = call(
            lambda: store_provider().create(
                user.id, key, body.kind, body.payload, body.name, body.note
            ),
            response,
        )
        response.status_code = 201 if created else 200
        response.headers["ETag"] = f'"{record["revision"]}"'
        return record

    @router.post("/{key}/actions")
    def mutate(
        key: str, body: ChangeArchive, response: Response, user: UserRecord = Depends(identity)
    ) -> Any:
        if body.action != "edit" and (body.name is not None or body.note is not None):
            raise HTTPException(422, "只有编辑操作可以提交名称或备注")
        record = call(
            lambda: store_provider().mutate(
                user.id, key, body.revision, body.action, name=body.name, note=body.note
            ),
            response,
        )
        response.headers["ETag"] = f'"{record["revision"]}"'
        return record

    @router.post("/{key}/tracking-group")
    def tracking_group(
        key: str,
        body: FactorTrackingSelection,
        response: Response,
        user: UserRecord = Depends(identity),
        expected: str = Header(alias="X-Research-Owner"),
    ) -> Any:
        from easy_tdx.web.factor_tracking import factor_tracking_group

        if not user.can_track:
            raise HTTPException(403, "当前账户没有追踪分析权限")

        def create_group() -> Any:
            record = store_provider().get(user.id, key)
            group = factor_tracking_group(record, **body.model_dump())
            try:
                saved, created = account_provider().append_tracking_group(user.id, group)
            except PermissionError as exc:
                raise ArchiveError(403, str(exc)) from exc
            except ValueError as exc:
                raise ArchiveError(422, str(exc)) from exc
            response.status_code = 201 if created else 200
            return {"group": saved, "created": created}

        return call(create_group, response)

    return router


router = build_router(get_research_archive, get_current_user)
