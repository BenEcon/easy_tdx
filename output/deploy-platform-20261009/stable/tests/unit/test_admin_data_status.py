"""Optional offline data paths must not be dereferenced when unavailable."""

from types import SimpleNamespace

import pytest

from easy_tdx.web.routers.admin_data import data_status


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["missing_home", "missing_vipdoc", "ready"])
async def test_offline_status_with_optional_directory(tmp_path, monkeypatch, state):
    tdx_home = None if state == "missing_home" else tmp_path
    monkeypatch.setattr("easy_tdx.offline.paths.detect_tdx_home", lambda: tdx_home)
    if state == "ready":
        for exchange, count in (("sh", 2), ("sz", 3)):
            directory = tmp_path / "vipdoc" / exchange / "lday"
            directory.mkdir(parents=True)
            for i in range(count):
                (directory / f"{i:06}.day").touch()
            (directory / "ignored.txt").touch()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(tdx_client=None, mac_client=None, ex_client=None))
    )
    result = await data_status(request)
    assert result["offline"] == {
        "ready": state == "ready",
        "sh_daily_files": 2 if state == "ready" else 0,
        "sz_daily_files": 3 if state == "ready" else 0,
    }
    assert result["vipdoc"] == (str(tmp_path / "vipdoc") if state == "ready" else None)
