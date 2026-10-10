"""Explicit transport trust, identical in normal and reload CLI paths."""

from unittest.mock import Mock

import pytest
import uvicorn
from click.testing import CliRunner

import easy_tdx.web
from easy_tdx.cli.cmd_web import serve
from easy_tdx.cli.proxy import validated_forwarded_allow_ips


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", ""),
        ("  ", ""),
        ("127.0.0.1, ::1", "127.0.0.1,::1"),
        ("172.22.0.1,172.22.0.1", "172.22.0.1"),
        ("2001:0db8::1", "2001:db8::1"),
        ("192.0.2.0/24,2001:db8::/32", "192.0.2.0/24,2001:db8::/32"),
    ],
)
def test_literal_addresses_are_canonical_and_empty_disables_trust(raw, expected):
    assert validated_forwarded_allow_ips(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "*",
        "127.0.0.1,*",
        "0.0.0.0/0",
        "::/0",
        "0.0.0.0",
        "::",
        "224.0.0.1",
        "localhost",
        "https://proxy.example",
        "/tmp/proxy.sock",
        "192.0.2.1/24",
        "127.0.0.1,",
        ",127.0.0.1",
        "127.0.0.1,,::1",
        "127.0.0.1:8000",
        "fe80::1%en0",
        "0.0.0.0/1,128.0.0.0/1",
        "::/1,8000::/1",
        "x" * 8193,
        ",".join(["127.0.0.1"] * 65),
    ],
)
def test_ambiguous_or_unbounded_trust_is_rejected(raw):
    with pytest.raises(ValueError):
        validated_forwarded_allow_ips(raw)


@pytest.mark.parametrize("reload", [False, True])
@pytest.mark.parametrize(
    "env,args,expected,enabled",
    [
        ({}, [], "127.0.0.1,::1", True),
        ({"FORWARDED_ALLOW_IPS": "172.22.0.1"}, [], "172.22.0.1", True),
        ({"FORWARDED_ALLOW_IPS": "172.22.0.1"}, ["--forwarded-allow-ips", "::1"], "::1", True),
        ({}, ["--no-proxy-headers"], "127.0.0.1,::1", False),
        ({}, ["--forwarded-allow-ips", ""], "", False),
    ],
)
def test_cli_passes_validated_trust_without_losing_transport_limits(
    monkeypatch, reload, env, args, expected, enabled
):
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    run = Mock()
    monkeypatch.setattr(uvicorn, "run", run)
    monkeypatch.setattr(easy_tdx.web, "create_app", Mock(return_value=object()))
    result = CliRunner().invoke(
        serve, ["--no-open-browser", *(["--reload"] if reload else []), *args], env=env
    )
    assert result.exit_code == 0, result.output
    options = run.call_args.kwargs
    assert options["forwarded_allow_ips"] == expected
    assert options["proxy_headers"] is enabled
    assert options["ws_max_size"] == 4096 and options["ws_per_message_deflate"] is False


def test_invalid_environment_fails_before_app_or_browser_start(monkeypatch):
    run, create, browser = Mock(), Mock(), Mock()
    monkeypatch.setattr(uvicorn, "run", run)
    monkeypatch.setattr(easy_tdx.web, "create_app", create)
    monkeypatch.setattr("webbrowser.open", browser)
    result = CliRunner().invoke(serve, [], env={"FORWARDED_ALLOW_IPS": "*"})
    assert result.exit_code == 2 and "可信代理" in result.output
    run.assert_not_called()
    create.assert_not_called()
    browser.assert_not_called()
