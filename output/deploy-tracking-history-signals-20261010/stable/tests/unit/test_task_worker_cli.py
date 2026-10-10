"""Standalone daemon runs without HTTP and uses the actual account store."""

import os
import signal
import subprocess
import sys
import time

import pandas as pd
import pytest
from click.testing import CliRunner

from easy_tdx.cli import cli
from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.backtest_schemas import BacktestRequest
from easy_tdx.web.task_payload import TaskInput
from easy_tdx.web.task_store import TaskStore
from easy_tdx.web.task_version import execution_version


def test_worker_command_is_registered_and_does_not_run_on_help():
    result = CliRunner().invoke(cli, ["research-worker", "--help"])
    assert result.exit_code == 0
    assert "--database" in result.output


def test_worker_rejects_mismatched_account_directory(tmp_path):
    path = tmp_path / "tasks.db"
    TaskStore(path)
    result = CliRunner().invoke(cli, ["research-worker", "--database", str(path)])
    assert result.exit_code != 0
    assert "错配账户" in result.output


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX worker resource limits")
def test_real_worker_daemon_completes_job_without_http_or_upstream(tmp_path, monkeypatch):
    root = tmp_path / "worker-config"
    root.mkdir(mode=0o700)
    monkeypatch.setenv("EASY_TDX_CONFIG_DIR", str(root))
    account = AccountStore(root / "accounts.db")
    user = account.create_user("qa_worker", "TemporaryOnly-20261009", role="admin")
    store = TaskStore(root / "research-tasks.db")
    frame = pd.DataFrame(
        {
            "datetime": pd.bdate_range("2026-01-05", periods=30),
            "open": [30.0] * 30,
            "high": [31.0] * 30,
            "low": [29.0] * 30,
            "close": [30.5] * 30,
            "vol": [1000] * 30,
            "amount": [30500.0] * 30,
        }
    )
    request = BacktestRequest(strategy="ma_cross", symbol="SZ:300750")
    record, _ = store.submit(
        user.id, TaskInput("backtest", execution_version(), request.model_dump(), (frame,), {})
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "easy_tdx",
            "research-worker",
            "--database",
            str(store.path),
            "--poll-interval",
            "0.02",
        ],
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            result = store.get(user.id, record["task_id"])
            if result["status"] in {"done", "failed", "cancelled", "timed_out"}:
                break
            assert process.poll() is None, "daemon exited unexpectedly"
            time.sleep(0.02)
        assert result["status"] == "done", result
        assert "data_provenance" in result["result"]
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=8) == 0
        assert TaskStore(store.path).get(user.id, record["task_id"])["result"] == result["result"]
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
