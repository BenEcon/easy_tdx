"""Acceptance reports must not claim completion on partial or failed execution."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from easy_tdx.web import task_version
from easy_tdx.web.routers import chanlun_replay
from tests import market_matrix


@pytest.fixture
def verifier(monkeypatch, tmp_path):
    path = Path(__file__).parents[2] / "scripts/verify_real_market_matrix.py"
    spec = importlib.util.spec_from_file_location("real_matrix_verifier", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    entry = next(row for row in market_matrix.entries() if row["id"].startswith("stock-300750-day"))
    _, _, snapshot = market_matrix.load_case(entry)
    sample = {**entry, "count": 3}
    monkeypatch.setattr(market_matrix, "entries", lambda: [sample])
    monkeypatch.setattr(
        market_matrix,
        "load_case",
        lambda row: (
            None,
            None,
            {
                "data": snapshot["data"][:3],
            },
        ),
    )
    monkeypatch.setattr(task_version, "execution_version", lambda: "test-execution-v1")
    output = tmp_path / "acceptance.json"
    monkeypatch.setattr(sys, "argv", [str(path), "--output", str(output)])
    return module, output


def test_all_prefixes_finish_before_passed_and_identical_resume(verifier, monkeypatch):
    module, output = verifier
    module.main()
    report = json.loads(output.read_text())
    assert report["status"] == "passed"
    case = next(iter(report["cases"].values()))
    assert case["status"] == "passed"
    assert [row["count"] for row in case["prefixes"]] == [1, 2, 3]
    assert all(len(row["result_sha256"]) == 64 for row in case["prefixes"])
    with pytest.raises(FileExistsError):
        module.main()
    monkeypatch.setattr(sys, "argv", ["verify", "--output", str(output), "--resume"])
    module.main()
    assert json.loads(output.read_text())["cases"] == report["cases"]


def test_future_leakage_writes_failed_not_passed_and_cannot_resume(verifier, monkeypatch):
    module, output = verifier
    actual = chanlun_replay.replay_snapshot

    def leaking(request, **kwargs):
        result = actual(request, **kwargs)
        if len(request.bars) > request.visible_count:
            result["bi_count"] += 1
        return result

    monkeypatch.setattr(chanlun_replay, "replay_snapshot", leaking)
    with pytest.raises(AssertionError, match="future suffix"):
        module.main()
    report = json.loads(output.read_text())
    assert report["status"] == "failed"
    assert report["failure"]["prefix"] == 1
    assert next(iter(report["cases"].values()))["prefixes"] == []
    monkeypatch.setattr(sys, "argv", ["verify", "--output", str(output), "--resume"])
    with pytest.raises(ValueError, match="previous verification failed"):
        module.main()


def test_changed_execution_never_publishes_success(verifier, monkeypatch):
    module, output = verifier
    versions = iter(["test-execution-v1", "test-execution-v2"])
    monkeypatch.setattr(task_version, "execution_version", lambda: next(versions))
    with pytest.raises(ValueError, match="changed during verification"):
        module.main()
    assert json.loads(output.read_text())["status"] == "failed"


def test_resume_rejects_changed_manifest_identity(verifier, monkeypatch):
    module, output = verifier
    module.main()
    report = json.loads(output.read_text())
    report["identity"]["manifest_sha256"] = "unrelated-manifest"
    output.write_text(json.dumps(report))
    monkeypatch.setattr(sys, "argv", ["verify", "--output", str(output), "--resume"])
    with pytest.raises(ValueError, match="Source/runtime changed"):
        module.main()
    assert json.loads(output.read_text()) == report
