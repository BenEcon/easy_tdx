"""Execution identity includes dirty sources, numerical versions and file names."""

from easy_tdx.web import task_version


def test_source_and_runtime_version_fingerprints(tmp_path, monkeypatch):
    root = tmp_path / "easy_tdx"
    web = root / "web"
    web.mkdir(parents=True)
    module = web / "task_version.py"
    module.write_text("# version module\n")
    rules = root / "rules.py"
    rules.write_text("VALUE = 1\n")
    monkeypatch.setattr(task_version, "__file__", str(module))
    monkeypatch.setattr(task_version, "version", lambda name: "v1")
    first = task_version.execution_version()
    assert task_version.execution_version() == first
    rules.write_text("VALUE = 2\n")
    assert task_version.execution_version() != first
    rules.write_text("VALUE = 1\n")
    assert task_version.execution_version() == first
    (root / "unrelated.txt").write_text("not executable source")
    assert task_version.execution_version() == first
    rules.rename(root / "different_name.py")
    renamed = task_version.execution_version()
    assert renamed != first
    monkeypatch.setattr(task_version, "version", lambda name: "v2" if name == "pandas" else "v1")
    assert task_version.execution_version() != renamed
