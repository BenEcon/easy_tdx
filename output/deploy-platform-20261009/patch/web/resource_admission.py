"""Shared admission before data retrieval, retained until actual work stops.

Leases are not a persistent job queue or hard process isolation. A bounded
heartbeat thread keeps native/threaded work charged after its HTTP waiter exits.
"""

from __future__ import annotations

import asyncio
import inspect
import sqlite3
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from functools import wraps
from pathlib import Path
from threading import Condition, Lock, Thread
from typing import Any, TypeVar

from fastapi import Depends, HTTPException, Request
from fastapi.routing import APIRoute

from easy_tdx.computation import ComputationControl, ComputationStopped, computation_scope
from easy_tdx.web.account_store import UserRecord, get_account_store
from easy_tdx.web.routers.auth import get_current_user

T = TypeVar("T")
LIMITS = {"data": (4, 24), "compute": (3, 8)}  # per account, installation
LEASE_SECONDS = 90
RENEW_SECONDS = 15
_current: ContextVar[Admission | None] = ContextVar("research_admission", default=None)
_condition = Condition()
_handles: set[Admission] = set()
_maintainer: Thread | None = None
_pool_lock = Lock()
_pool: ThreadPoolExecutor | None = None


def _compute_pool() -> ThreadPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="research-compute")
        return _pool


def shutdown_compute_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.shutdown(wait=True, cancel_futures=True)
            _pool = None


def resource_for(path: str, method: str) -> str | None:
    path = path.removeprefix("/api/v1").rstrip("/")
    # Control-plane operations must remain available when research is saturated.
    if any(
        path == prefix or path.startswith(prefix + "/")
        for prefix in ("/auth", "/admin", "/strategies", "/server", "/backtest/tasks")
    ):
        return None
    if path in {"/backtest/strategies", "/indicator/list", "/research/factors"}:
        return None
    if method == "POST" and any(
        path.startswith(prefix)
        for prefix in ("/backtest/", "/chanlun/", "/indicator/", "/research/")
    ):
        return "compute"
    return "data"


class ResourceStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        with self.connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS resource_leases (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, resource TEXT NOT NULL,
                expires REAL NOT NULL)""")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=2)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def acquire(self, owner: str, resource: str) -> str | None:
        now = time.time()
        per_user, total_limit = LIMITS[resource]
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM resource_leases WHERE expires <= ?", (now,))
            total, own = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(owner = ?), 0) FROM resource_leases "
                "WHERE resource=?",
                (owner, resource),
            ).fetchone()
            if total >= total_limit or own >= per_user:
                return None
            lease = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO resource_leases VALUES (?, ?, ?, ?)",
                (lease, owner, resource, now + LEASE_SECONDS),
            )
            return lease

    def renew(self, lease: str) -> bool:
        now = time.time()
        with self.connect() as conn:
            return (
                conn.execute(
                    "UPDATE resource_leases SET expires=? WHERE id=? AND expires>?",
                    (now + LEASE_SECONDS, lease, now),
                ).rowcount
                == 1
            )

    def release(self, lease: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM resource_leases WHERE id=?", (lease,))


def _maintain() -> None:
    while True:
        with _condition:
            _condition.wait(timeout=RENEW_SECONDS if _handles else None)
            current = list(_handles)
        for admission in current:
            admission.renew()


class Admission:
    def __init__(self, store: ResourceStore, lease: str) -> None:
        global _maintainer
        self.store, self.lease = store, lease
        self._lock = Lock()
        self._refs = 1
        self._lost = False
        with _condition:
            _handles.add(self)
            if _maintainer is None:
                _maintainer = Thread(target=_maintain, name="research-lease-heartbeat", daemon=True)
                _maintainer.start()
            _condition.notify()

    def check(self) -> None:
        with self._lock:
            if self._lost or not self._refs:
                raise HTTPException(503, "研究资源租约已失效，未发布计算结果，请重新提交")

    def retain(self) -> Admission:
        with self._lock:
            if self._lost or not self._refs:
                raise HTTPException(503, "研究资源租约已失效，请重新提交")
            self._refs += 1
        return self

    def renew(self) -> None:
        with self._lock:
            if not self._refs or self._lost:
                return
            try:
                self._lost = not self.store.renew(self.lease)
            except sqlite3.Error:
                self._lost = True

    def release(self) -> None:
        with self._lock:
            if not self._refs:
                return
            self._refs -= 1
            if self._refs:
                return
            try:
                self.store.release(self.lease)
            except sqlite3.Error:
                pass  # Fail closed: unreleased slots remain charged until expiry.
        with _condition:
            _handles.discard(self)


def retain_current_admission() -> Admission | None:
    admission = _current.get()
    return admission.retain() if admission else None


async def admit_research(
    request: Request,
    user: UserRecord = Depends(get_current_user),
) -> AsyncIterator[None]:
    resource = resource_for(request.url.path, request.method)
    if resource is None:
        yield
        return
    try:
        store = ResourceStore(get_account_store().db_path)
        lease = store.acquire(user.id, resource)
    except sqlite3.Error as exc:
        raise HTTPException(503, "资源配额暂不可用，请稍后重试") from exc
    if lease is None:
        raise HTTPException(
            429, "研究请求已达并发上限，请等待现有请求或任务结束", headers={"Retry-After": "5"}
        )
    admission = Admission(store, lease)
    token = _current.set(admission)
    try:
        yield
        admission.check()
    finally:
        _current.reset(token)
        admission.release()


async def run_compute(func: Callable[[], T], *, timeout: float = 120) -> T:
    """Keep the lease until the thread ends, even on timeout/disconnect cancellation."""
    admission = retain_current_admission()
    control = ComputationControl(deadline=time.monotonic() + timeout)

    def work() -> T:
        if admission:
            admission.check()
        with computation_scope(control):
            result = func()
        if admission:
            admission.check()
        return result

    try:
        worker = _compute_pool().submit(copy_context().run, work)
    except BaseException:
        if admission:
            admission.release()
        raise
    if admission:
        # Concurrent Future completion means the real thread exited (or never started).
        # Cancellation of an asyncio wrapper alone must not free the resource slot.
        worker.add_done_callback(lambda _future: admission.release())
    task = asyncio.wrap_future(worker)

    def finished(future: asyncio.Future[T]) -> None:
        if not future.cancelled():
            future.exception()  # Retrieve errors from a worker whose HTTP waiter already left.

    task.add_done_callback(finished)
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    except asyncio.TimeoutError as exc:
        control.request("timed_out")
        raise HTTPException(
            504, "计算等待超时；工作线程退出前继续占用配额，未返回部分结果"
        ) from exc
    except asyncio.CancelledError:
        control.request()
        worker.cancel()  # Only pending work can be cancelled immediately.
        raise
    except ComputationStopped as exc:
        raise HTTPException(504, str(exc)) from exc


class BoundedComputeRoute(APIRoute):
    """Wrap synchronous compute routes without changing their directly callable functions."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        endpoint = kwargs.get("endpoint")
        if endpoint is not None and not inspect.iscoroutinefunction(endpoint):

            @wraps(endpoint)
            async def bounded(*positional: Any, **named: Any) -> Any:
                return await run_compute(lambda: endpoint(*positional, **named))

            # Resolve forward annotations in the original module, not this wrapper's globals.
            bounded.__signature__ = inspect.signature(endpoint, eval_str=True)  # type: ignore[attr-defined]
            kwargs["endpoint"] = bounded
        super().__init__(*args, **kwargs)
