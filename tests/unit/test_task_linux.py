"""Linux-only native exit/limit proofs, independent of application heartbeats."""

import multiprocessing
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from easy_tdx.web.task_guard import TaskGuard, guard_path

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux kernel contracts")


def _stopped_child_parent(path, pipe):
    guard = TaskGuard.acquire(Path(path), create=True)
    code = (
        "import os,signal,sys; from pathlib import Path; "
        "from easy_tdx.web.task_worker import _parent_guard; "
        "from easy_tdx.web.task_guard import verify_inherited_guard; "
        "verify_inherited_guard(int(sys.argv[1]),Path(sys.argv[2])); "
        "_parent_guard(os.getppid()); print('armed',flush=True); "
        "os.kill(os.getpid(),signal.SIGSTOP); sys.stdin.buffer.read()"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(guard.fd), path],
        pass_fds=(guard.fd,),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    guard.close()
    assert child.stdout.readline() == b"armed\n"
    pid, status = os.waitpid(child.pid, os.WUNTRACED)
    assert pid == child.pid and os.WIFSTOPPED(status)
    pipe.send(child.pid)
    pipe.recv()  # This parent is killed; the stopped child cannot run a pipe watcher.


def test_parent_death_signal_kills_even_a_stopped_child(tmp_path):
    path = guard_path(tmp_path / "db", "linux-parent-death")
    context = multiprocessing.get_context("spawn")
    parent_pipe, peer = context.Pipe()
    parent = context.Process(target=_stopped_child_parent, args=(str(path), peer))
    parent.start()
    child_pid = None
    released = None
    try:
        assert parent_pipe.poll(15)
        child_pid = parent_pipe.recv()
        assert TaskGuard.acquire(path) is None
        parent.kill()
        parent.join(5)
        assert parent.exitcode == -signal.SIGKILL
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            released = TaskGuard.acquire(path)
            if released is not None:
                break
            time.sleep(0.02)
        assert released is not None, "Stopped child survived Linux parent-death SIGKILL"
    finally:
        if parent.is_alive():
            parent.kill()
        parent.join(5)
        if released is None and child_pid is not None:
            probe = TaskGuard.acquire(path)
            if probe is None:
                # Only this isolated test's communicated child, while its lock
                # proves the attempt still lives. Production never kills PIDs.
                os.kill(child_pid, signal.SIGKILL)
            else:
                probe.close()
        if released is not None:
            released.close()
        parent_pipe.close()
        peer.close()


def test_linux_address_space_limit_rejects_large_native_mapping():
    code = (
        "import mmap\n"
        "from easy_tdx.web.task_worker import _limits\n"
        "_limits(5, 128 * 1024**2)\n"
        "try:\n"
        "    memory = mmap.mmap(-1, 256 * 1024**2)\n"
        "except (OSError, MemoryError):\n"
        "    print('native allocation refused')\n"
        "else:\n"
        "    raise SystemExit('address space budget did not apply')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b"native allocation refused\n"
