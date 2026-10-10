"""Authenticate and reserve shared capacity before buffering an archive upload."""

import asyncio
import sqlite3
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.types import Scope

from easy_tdx.web.account_store import get_account_store
from easy_tdx.web.resource_admission import Admission, ResourceStore
from easy_tdx.web.routers.auth import SESSION_COOKIE, get_current_user

ARCHIVE_BODY_LIMIT = 26 * 1024 * 1024  # 25 MiB payload plus JSON envelope.
ARCHIVE_BODY_TIMEOUT = 30.0
_current_upload: ContextVar[Admission | None] = ContextVar("archive_upload", default=None)


def retain_current_archive_upload() -> Admission | None:
    admission = _current_upload.get()
    return admission.retain() if admission else None


def is_archive_upload(scope: Scope) -> bool:
    if scope["method"] != "PUT":
        return False
    prefix = "/api/v1/research/archives/"
    path = scope["path"]
    if not isinstance(path, str) or not path.startswith(prefix):
        return False
    key = path[len(prefix) :]
    try:
        return str(uuid.UUID(key)) == key
    except ValueError:
        return False


@asynccontextmanager
async def archive_upload_guard(scope: Scope) -> AsyncIterator[Admission]:
    request = Request(scope)

    def reserve() -> Admission:
        # Explicit Cookie argument: do not invoke the FastAPI dependency default.
        user = get_current_user(request.cookies.get(SESSION_COOKIE))
        expected = request.headers.get("X-Research-Owner")
        if expected is not None and expected != user.id:
            raise HTTPException(409, "登录账户已变化，请刷新页面后重试")
        try:
            store = ResourceStore(get_account_store().db_path)
            lease = store.acquire(user.id, "archive_upload")
        except (sqlite3.Error, OSError) as exc:
            raise HTTPException(503, "存档上传配额暂不可用，请稍后重试") from exc
        if lease is None:
            raise HTTPException(
                429, "存档上传已达并发上限，请稍后重试", headers={"Retry-After": "5"}
            )
        return Admission(store, lease)

    # A raw ASGI/asyncio cancellation can arrive during the SQLite operation.
    # Keep that operation alive, then release any slot it acquired after we left.
    reservation = asyncio.create_task(run_in_threadpool(reserve))
    try:
        admission = await asyncio.shield(reservation)
    except asyncio.CancelledError:

        def release_late(task: asyncio.Task[Admission]) -> None:
            if not task.cancelled() and task.exception() is None:
                task.result().release()

        reservation.add_done_callback(release_late)
        raise
    token = _current_upload.set(admission)
    try:
        yield admission
    finally:
        _current_upload.reset(token)
        admission.release()
