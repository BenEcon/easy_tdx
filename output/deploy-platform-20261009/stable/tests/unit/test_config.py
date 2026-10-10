"""config.py 单元测试 —— 覆盖环境变量覆盖、config.json 原子读写、save_best_host 补全逻辑。

之前这三块（env 覆盖 / config.json 读写 / save_best_host 合并）零测试，
本文件补齐该缺口（审计报告 #9）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from easy_tdx import config as cfg

# --------------------------------------------------------------------------- #
# 辅助：把 config 模块的 _CONFIG_FILE / _CONFIG_DIR 重定向到临时目录
# --------------------------------------------------------------------------- #


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 config 模块的重定向到 tmp_path，测试间互不影响。"""
    monkeypatch.setattr(cfg, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg, "_CONFIG_FILE", tmp_path / "config.json")
    return tmp_path


# --------------------------------------------------------------------------- #
# 环境变量覆盖（EASY_TDX_HOST / PORT / TIMEOUT）
# --------------------------------------------------------------------------- #


class TestEnvOverride:
    def test_env_host_overrides_config(
        self, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # config.json 写入一个 host，但 env 应优先
        (isolated_config / "config.json").write_text(json.dumps({"best_host": "1.1.1.1"}), "utf-8")
        monkeypatch.setenv("EASY_TDX_HOST", "9.9.9.9")
        assert cfg.get_best_host() == "9.9.9.9"

    def test_env_port_overrides_config(
        self, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EASY_TDX_PORT", "8888")
        assert cfg.get_port() == 8888

    def test_env_timeout_overrides_config(
        self, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EASY_TDX_TIMEOUT", "42.5")
        assert cfg.get_timeout() == 42.5

    def test_env_known_hosts_csv(
        self, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EASY_TDX_KNOWN_HOSTS", "a.com, b.com ,,c.com")
        assert cfg.get_known_hosts() == ["a.com", "b.com", "c.com"]


# --------------------------------------------------------------------------- #
# config.json 读写 + 默认兜底
# --------------------------------------------------------------------------- #


class TestConfigReadWrite:
    def test_no_config_file_uses_fallback(self, isolated_config: Path) -> None:
        # 无 config.json 时返回内嵌默认值
        assert cfg.get_best_host() == cfg._FALLBACK_HOSTS[0]
        assert cfg.get_port() == cfg._FALLBACK_PORT
        assert cfg.get_known_hosts() == list(cfg._FALLBACK_HOSTS)

    def test_config_json_host(self, isolated_config: Path) -> None:
        # best_host 必须在 known_hosts 里才能通过污染校验（v1.19.4 新增）。
        # 用 known_hosts 里的一个 host，确保不被重置。
        (isolated_config / "config.json").write_text(
            json.dumps(
                {
                    "best_host": "203.0.0.1",
                    "known_hosts": ["203.0.0.1"],
                    "port": 7709,
                    "timeout": 12.0,
                }
            ),
            "utf-8",
        )
        assert cfg.get_best_host() == "203.0.0.1"
        assert cfg.get_port() == 7709
        assert cfg.get_timeout() == 12.0

    def test_load_corrupt_json_returns_empty(self, isolated_config: Path) -> None:
        # 损坏的 JSON 不应崩溃，应回退到默认
        (isolated_config / "config.json").write_text("{not valid json", "utf-8")
        assert cfg.get_best_host() == cfg._FALLBACK_HOSTS[0]


# --------------------------------------------------------------------------- #
# save_best_host 首次写入补全逻辑
# --------------------------------------------------------------------------- #


class TestSaveBestHost:
    def test_first_write_completes_defaults(self, isolated_config: Path) -> None:
        cfg.save_best_host("180.153.18.170")
        data = json.loads((isolated_config / "config.json").read_text("utf-8"))
        assert data["best_host"] == "180.153.18.170"
        # 首次写入应补全所有默认字段
        assert data["known_hosts"] == list(cfg._FALLBACK_HOSTS)
        assert data["calc_hosts"] == list(cfg._FALLBACK_CALC_HOSTS)
        assert data["mac_hosts"] == list(cfg._FALLBACK_MAC_HOSTS)
        assert data["ex_hosts"] == list(cfg._FALLBACK_EX_HOSTS)
        assert data["mac_ex_hosts"] == list(cfg._FALLBACK_MAC_EX_HOSTS)
        assert data["port"] == cfg._FALLBACK_PORT
        assert "best_host_updated_at" in data

    def test_second_write_preserves_existing(self, isolated_config: Path) -> None:
        # 预置已存在的 known_hosts，save_best_host 不应覆盖它
        existing = {
            "known_hosts": ["custom.host"],
            "port": 9999,
        }
        (isolated_config / "config.json").write_text(json.dumps(existing), "utf-8")
        cfg.save_best_host("new.host")
        data = json.loads((isolated_config / "config.json").read_text("utf-8"))
        assert data["best_host"] == "new.host"
        # 已有字段应保留，不被默认值覆盖
        assert data["known_hosts"] == ["custom.host"]
        assert data["port"] == 9999
        # 但缺失的字段应补全
        assert "calc_hosts" in data

    def test_atomic_write(self, isolated_config: Path) -> None:
        # 写入后不应残留 .tmp 文件（原子替换）
        cfg.save_best_host("x.host")
        assert not (isolated_config / "config.json.tmp").exists()
        assert (isolated_config / "config.json").exists()


# --------------------------------------------------------------------------- #
# best_host 交叉污染校验（v1.19.4 回归守卫）
# --------------------------------------------------------------------------- #


class TestBestHostPollutionGuard:
    """MacClient.from_best_host 曾误调 save_best_host 把 MAC 服务器写入
    best_host，导致标准 TdxClient 用错协议请求 MAC 服务器返回空 body。
    get_best_host 现在含校验：缓存 host 不在标准列表里时自动重置。
    """

    def test_mac_host_in_best_host_gets_reset(
        self, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """best_host 被污染成 MAC host（不在标准列表）→ 自动重置。"""
        polluted = {
            "best_host": "121.36.248.138",  # MAC host
            "known_hosts": ["180.153.18.170", "115.238.56.198"],
        }
        (isolated_config / "config.json").write_text(json.dumps(polluted), "utf-8")
        monkeypatch.delenv("EASY_TDX_HOST", raising=False)

        result = cfg.get_best_host()
        assert result != "121.36.248.138", "MAC host 应被重置"
        assert result in polluted["known_hosts"] or result in cfg._FALLBACK_HOSTS

    def test_valid_host_not_reset(
        self, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """best_host 是合法标准 host → 不重置。"""
        (isolated_config / "config.json").write_text(
            json.dumps({"best_host": "180.153.18.170", "known_hosts": ["180.153.18.170"]}),
            "utf-8",
        )
        monkeypatch.delenv("EASY_TDX_HOST", raising=False)
        assert cfg.get_best_host() == "180.153.18.170"

    def test_reset_persists_to_config(self, isolated_config: Path) -> None:
        """重置后的 host 应写回 config.json，下次读不需再校验。"""
        (isolated_config / "config.json").write_text(
            json.dumps({"best_host": "121.36.248.138"}), "utf-8"
        )
        cfg.get_best_host()  # 触发重置
        data = json.loads((isolated_config / "config.json").read_text("utf-8"))
        assert data["best_host"] != "121.36.248.138"


class TestMacHostSeparation:
    """MAC 协议的 best host 应独立于标准 TDX 的 best_host。"""

    def test_save_best_mac_host_does_not_touch_best_host(self, isolated_config: Path) -> None:
        """save_best_mac_host 不应修改 best_host 字段。"""
        cfg.save_best_host("180.153.18.170")
        cfg.save_best_mac_host("121.36.248.138")
        data = json.loads((isolated_config / "config.json").read_text("utf-8"))
        assert data["best_host"] == "180.153.18.170"
        assert data["best_mac_host"] == "121.36.248.138"

    def test_get_best_mac_host_returns_mac_host(self, isolated_config: Path) -> None:
        """get_best_mac_host 返回的是 MAC host 字段，不是标准 host。"""
        cfg.save_best_mac_host("123.60.47.136")
        assert cfg.get_best_mac_host() == "123.60.47.136"
