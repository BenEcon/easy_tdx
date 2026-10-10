"""Local POSIX execution liveness locks, never heartbeat/PID death guesses.

Only supported on a private local filesystem shared by this host's workers.
Never unlink a guard: replacing its inode would invalidate the death proof.
Raw descriptors are deliberately not released by object finalizers. A child
inherits the attempt descriptor across exec and holds it until actual OS exit.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from easy_tdx.web.task_store import TaskLease

GUARD_PROTOCOL = "flock-v1"


class UnsafeTaskGuard(ValueError):
    """Missing or changed execution evidence must fail closed."""


def guard_path(database: Path, worker_id: str, lease: TaskLease | None = None) -> Path:
    database = database.resolve()
    identity = (
        ["owner", worker_id]
        if lease is None
        else ["attempt", worker_id, lease.task_id, str(lease.generation), lease.token]
    )
    name = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    return database.with_name(database.name + ".locks") / name


def _directory(path: Path, *, create: bool) -> None:
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise UnsafeTaskGuard("执行锁目录必须为当前用户私有真实目录")


def _verify(fd: int, path: Path) -> None:
    opened, current = os.fstat(fd), path.lstat()
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(current.st_mode)
        or opened.st_uid != os.getuid()
        or opened.st_mode & 0o077
        or opened.st_nlink != 1
        or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
    ):
        raise UnsafeTaskGuard("执行锁文件身份或权限异常，不能证明执行已停止")


class TaskGuard:
    def __init__(self, fd: int) -> None:
        self.fd = fd

    def close(self) -> None:
        if self.fd >= 0:
            # Do NOT LOCK_UN: another process may hold an inherited copy of the
            # same open-file description. Only its final close releases flock.
            os.close(self.fd)
            self.fd = -1

    @classmethod
    def acquire(cls, path: Path, *, create: bool = False) -> TaskGuard | None:
        import fcntl

        _directory(path.parent, create=create)
        flags = os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW
        if create:
            flags |= os.O_CREAT | os.O_EXCL
        fd = os.open(path, flags, 0o600)
        try:
            _verify(fd, path)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                return None
            _verify(fd, path)
        except BaseException:
            os.close(fd)
            raise
        return cls(fd)


def verify_inherited_guard(fd: int, path: Path) -> None:
    """Validate the already-held inherited descriptor without unlocking it."""
    import fcntl

    _directory(path.parent, create=False)
    _verify(fd, path)
    # A separately opened descriptor must be unable to take the held lock.
    probe = TaskGuard.acquire(path)
    if probe is not None:
        probe.close()
        raise UnsafeTaskGuard("工作进程没有继承有效执行锁")
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.set_inheritable(fd, False)
