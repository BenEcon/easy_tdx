"""Version task execution by installed code and numerical runtime, not Git HEAD."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def execution_version() -> str:
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    files = sorted(root.rglob("*.py"))
    if not files:
        raise RuntimeError("执行源码不可校验，拒绝复用持久化任务")
    for path in files:
        relative = path.relative_to(root).as_posix().encode()
        contents = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(contents).to_bytes(8, "big"))
        digest.update(contents)
    libraries = {}
    for name in ("easy-tdx", "numpy", "pandas", "scipy", "pydantic", "tzdata"):
        try:
            libraries[name] = version(name)
        except PackageNotFoundError:
            libraries[name] = "not-installed"
    runtime = {
        "python": sys.version,
        "platform": sys.platform,
        "machine": platform.machine(),
        "libraries": libraries,
    }
    digest.update(json.dumps(runtime, sort_keys=True).encode())
    return "research-execution-v1:" + digest.hexdigest()
