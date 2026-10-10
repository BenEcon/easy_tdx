"""Unit tests must not read or migrate the developer's real account/config databases."""

import pytest


@pytest.fixture(autouse=True)
def isolated_user_configuration(tmp_path, monkeypatch):
    from easy_tdx import config
    from easy_tdx.web import account_store, strategy_store

    root = tmp_path / "isolated-config"
    monkeypatch.setenv("EASY_TDX_CONFIG_DIR", str(root))
    # Config caches these paths at import time; environment override alone is insufficient.
    monkeypatch.setattr(config, "_CONFIG_DIR", root)
    monkeypatch.setattr(config, "_CONFIG_FILE", root / "config.json")
    monkeypatch.setattr(account_store, "_store", None)
    monkeypatch.setattr(strategy_store, "_store", None)
