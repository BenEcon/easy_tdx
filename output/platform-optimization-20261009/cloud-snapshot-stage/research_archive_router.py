"""Staged HTTP adapter. Mount behind the existing origin/body/resource middleware."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from research_archive import ArchiveError, ResearchArchive

from easy_tdx.web.account_store import UserRecord


class CreateArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["chart", "study"]
    payload: dict[str, Any]
    name: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=4000)


class ChangeArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: StrictInt = Field(ge=1)
    action: Literal["edit", "delete", "restore", "purge"]
    name: str | None = Field(default=None, min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=4000)


def build_router(
    store_provider: Callable[[], ResearchArchive], identity: Callable[..., UserRecord]
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
        try:
            return operation()
        except ArchiveError as exc:
            raise HTTPException(
                exc.status, str(exc), headers={"Cache-Control": "no-store"}
            ) from exc
        except (sqlite3.Error, OSError) as exc:
            raise HTTPException(
                503, "研究存档暂不可用，请稍后重试", headers={"Cache-Control": "no-store"}
            ) from exc

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

    return router
