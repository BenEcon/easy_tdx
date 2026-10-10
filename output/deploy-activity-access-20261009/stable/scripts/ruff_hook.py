"""PostToolUse hook: 对 Edit/Write 修改的 .py 文件自动运行 ruff check + format。

stdin 接收 JSON: {"tool_name": "Edit"|"Write", "tool_input": {"file_path": "..."}}
"""

import json
import subprocess
import sys


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path.endswith(".py"):
        return

    # ruff check --fix（自动修复 lint 问题）
    r = subprocess.run(
        ["ruff", "check", "--fix", file_path],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if r.returncode != 0 and r.stdout.strip():
        print(f"[ruff check] {file_path}:\n{r.stdout.strip()}")

    # ruff format
    r = subprocess.run(
        ["ruff", "format", file_path],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if r.returncode != 0 and r.stdout.strip():
        print(f"[ruff format] {file_path}:\n{r.stdout.strip()}")


if __name__ == "__main__":
    main()
