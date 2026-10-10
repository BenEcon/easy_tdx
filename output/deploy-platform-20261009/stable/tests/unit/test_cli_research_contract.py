"""CLI invokes real engines; only vendor transport/strategy discovery are replaced."""

import csv
import io
import json
import math
import subprocess
import sys
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner

from easy_tdx.backtest import cli as commands
from easy_tdx.backtest.cli_data import load_cli_frame
from easy_tdx.backtest.reporting import metric_text, strict_json
from easy_tdx.backtest.strategies.builtin import MaCrossStrategy
from easy_tdx.cli import cmd_run_all
from easy_tdx.mac.enums import Adjust, Period


def bars(category="DAY"):
    if category == "WEEK":
        dates = pd.date_range("2025-07-04", periods=10, freq="W-FRI")
    elif category == "MONTH":
        dates = pd.date_range("2025-01-31", periods=10, freq="ME")
    elif category == "MIN_30":
        dates = pd.to_datetime(
            [
                f"2025-09-{day} {clock}"
                for day in [8, 9, 10, 11]
                for clock in [
                    "10:00",
                    "10:30",
                    "11:00",
                    "11:30",
                    "13:30",
                    "14:00",
                    "14:30",
                    "15:00",
                ]
            ]
        )
    else:
        dates = pd.date_range("2025-09-08", periods=10, freq="B")
    values = 10 + np.sin(np.arange(len(dates)))
    return pd.DataFrame(
        dict(
            datetime=dates,
            open=values,
            high=values + 1,
            low=values - 1,
            close=values,
            vol=1000,
            amount=10000,
        )
    )


@pytest.mark.parametrize("command", ["single", "combo", "portfolio", "run-all"])
@pytest.mark.parametrize(
    "period,category,annual",
    [
        ("DAILY", "DAY", 252),
        ("WEEKLY", "WEEK", 52),
        ("MONTHLY", "MONTH", 12),
        ("30MIN", "MIN_30", 252),
    ],
)
def test_all_cli_entry_points_bind_real_period(
    monkeypatch, tmp_path, command, period, category, annual
):
    frame = bars(category)
    original = frame.copy(deep=True)
    client = Mock()
    client.get_stock_kline.return_value = frame
    monkeypatch.setattr("easy_tdx.cli.conn.get_mac_client", lambda: nullcontext(client))
    monkeypatch.setattr(commands, "_load_strategy_from_file", lambda _: MaCrossStrategy)
    monkeypatch.setattr(
        commands, "_load_combo_strategies", lambda _: [MaCrossStrategy, MaCrossStrategy]
    )
    options = ["--period", period, "--cash", "100000"]
    runner = CliRunner()
    if command == "run-all":
        (tmp_path / "ma.py").write_text("# discovery only\n")
        monkeypatch.setattr(cmd_run_all, "_load_strategy_class", lambda _: MaCrossStrategy)
        captured = []

        def ranking(rows, results):
            captured.extend(results.values())
            return True

        monkeypatch.setattr(cmd_run_all, "_print_ranking", ranking)
        result = runner.invoke(
            cmd_run_all.run_all, ["SH", "600699", "--strategies-dir", str(tmp_path), *options]
        )
        assert result.exit_code == 0, result.exception
        basis = captured[0].config["performance_basis"]
    else:
        if command == "portfolio":
            result = runner.invoke(
                commands.portfolio, ["--stocks", "SH:600699", "--strategy-file", "ma.py", *options]
            )
        else:
            strategy_opt = (
                ["--combo-strategies", "ma.py,ma.py"]
                if command == "combo"
                else ["--strategy-file", "ma.py"]
            )
            result = runner.invoke(commands.backtest, ["SH", "600699", *strategy_opt, *options])
        assert result.exit_code == 0, result.exception
        payload = json.loads(
            result.stdout, parse_constant=lambda s: pytest.fail(f"invalid JSON {s}")
        )
        basis = (
            payload["performance_basis"]
            if command == "portfolio"
            else payload["config"]["performance_basis"]
        )
    assert basis["input_category"] == category
    assert basis["annual_periods"] == annual
    assert basis["unavailable_reason"] is None
    assert basis["observed_sample_count"] == (4 if category == "MIN_30" else 10)
    assert client.get_stock_kline.call_args.kwargs["bar_time"] == "start"
    pd.testing.assert_frame_equal(frame, original, check_exact=True)
    assert not frame.attrs


def test_open_bars_filtered_before_strategy_and_provenance_preserved():
    frame = bars("MIN_30").iloc[:8]
    client = Mock()
    client.get_stock_kline.return_value = frame
    result = load_cli_frame(
        client, 1, "600699", Period.MIN_30, Adjust.QFQ, 8, now=datetime(2025, 9, 8, 11, 15)
    )
    assert len(result) == 3 and result.datetime.iloc[-1] == pd.Timestamp("2025-09-08 11:00")
    meta = result.attrs["snapshot_metadata"]
    assert meta["excluded_open_count"] == 5
    assert meta["actual_adjust"] == "QFQ"
    assert meta["historical_data_vintage"] is False
    assert meta["source_fingerprint"] != meta["data_fingerprint"]
    assert len(frame) == 8 and "is_closed" not in frame


@pytest.mark.parametrize("issue", ["adjust", "bad-price", "false-true", "custom", "too-few"])
def test_invalid_cli_market_inputs_do_not_reach_engines(issue):
    frame = bars()
    client = Mock()
    client.get_stock_kline.return_value = frame
    period = Period.DAILY
    if issue == "adjust":
        frame.attrs["actual_adjust"] = "NONE"
    elif issue == "bad-price":
        frame.loc[0, "close"] = np.nan
    elif issue == "false-true":
        frame["is_closed"] = [False] + [True] * 9
    elif issue == "custom":
        period = Period.MINS
    else:
        frame["is_closed"] = [True] + [False] * 9
    with pytest.raises(ValueError):
        load_cli_frame(client, 1, "600699", period, Adjust.QFQ, 10)
    if issue == "custom":
        client.get_stock_kline.assert_not_called()


@pytest.mark.parametrize("command", [commands.backtest, commands.portfolio])
@pytest.mark.parametrize("output", ["json", "csv", "table"])
def test_zero_trade_results_have_explicit_state_and_real_output_format(
    monkeypatch, command, output
):
    client = Mock()
    client.get_stock_kline.return_value = bars()
    monkeypatch.setattr("easy_tdx.cli.conn.get_mac_client", lambda: nullcontext(client))
    monkeypatch.setattr(commands, "_load_strategy_from_file", lambda _: MaCrossStrategy)
    args = ["SH", "600699"] if command is commands.backtest else ["--stocks", "SH:600699"]
    result = CliRunner().invoke(command, [*args, "--strategy-file", "ma.py", "--output", output])
    assert result.exit_code == 0, result.exception
    if output == "json":
        payload = json.loads(result.stdout, parse_constant=lambda s: pytest.fail(s))
        basis = (
            payload["config"]["performance_basis"]
            if command is commands.backtest
            else payload["performance_basis"]
        )
        assert basis["metric_status"]["win_rate"]["state"] == "unavailable"
    elif output == "csv":
        rows = list(csv.DictReader(io.StringIO(result.stdout)))
        win = next(row for row in rows if row["metric"] == "win_rate")
        assert win["value"] == "" and win["state"] == "unavailable" and win["reason"]
    else:
        assert "—" in result.stdout and "绩效采样" in result.stdout
        assert "nan" not in result.stdout and "999" not in result.stdout


def test_metric_formatter_and_json_preserve_zero_and_real_999():
    assert [metric_text(v) for v in [None, math.nan, math.inf, -math.inf, 0, 999]] == [
        "—",
        "—",
        "∞",
        "−∞",
        "0.00",
        "999.00",
    ]
    assert json.loads(
        strict_json({"x": np.float32(np.inf), "t": pd.Timestamp("2025-01-01"), "z": 0})
    ) == {"x": None, "t": "2025-01-01T00:00:00", "z": 0}


def test_run_all_never_awards_999_for_zero_drawdown(capsys):
    row = dict(
        strategy="idle",
        total_return=0,
        annual_return=0,
        max_drawdown=0,
        sharpe=math.nan,
        sortino=math.nan,
        calmar=math.nan,
        win_rate=math.nan,
        profit_factor=math.nan,
        total_trades=0,
        volatility=0,
    )
    assert cmd_run_all._print_ranking([row], {}) is True
    output = capsys.readouterr().out
    assert "暂不评分" in output and "999" not in output and "nan" not in output
    assert cmd_run_all._print_ranking([{**row, "total_return": math.nan}], {}) is False
    assert "[BEST]" not in capsys.readouterr().out


def test_precomputed_indicators_do_not_erase_weekly_period(monkeypatch):
    client = Mock()
    client.get_stock_kline.return_value = bars("WEEK")
    monkeypatch.setattr("easy_tdx.cli.conn.get_mac_client", lambda: nullcontext(client))
    monkeypatch.setattr(commands, "_load_strategy_from_file", lambda _: MaCrossStrategy)
    result = CliRunner().invoke(
        commands.backtest,
        ["SH", "600699", "--strategy-file", "ma.py", "--period", "WEEKLY", "--indicators", "MACD"],
    )
    assert result.exit_code == 0, result.exception
    basis = json.loads(result.stdout)["config"]["performance_basis"]
    assert basis["input_category"] == "WEEK" and basis["annual_periods"] == 52


def test_real_vendor_cli_and_web_have_identical_metrics(monkeypatch):
    from easy_tdx.web.backtest_schemas import BacktestRequest
    from easy_tdx.web.routers.backtest import _run_backtest

    path = Path(__file__).parents[1] / "fixtures/chanlun/600699-qfq-20260929.json"
    payload = json.loads(path.read_text())
    frame = pd.DataFrame(payload["bars"])
    frame.datetime = pd.to_datetime(frame.datetime)
    client = Mock()
    client.get_stock_kline.return_value = frame
    monkeypatch.setattr("easy_tdx.cli.conn.get_mac_client", lambda: nullcontext(client))
    monkeypatch.setattr(commands, "_load_strategy_from_file", lambda _: MaCrossStrategy)
    result = CliRunner().invoke(
        commands.backtest,
        ["SH", "600699", "--strategy-file", "ma.py", "--adjust", "QFQ", "--count", "800"],
    )
    assert result.exit_code == 0, result.exception
    actual = json.loads(result.stdout)
    prepared = load_cli_frame(client, 1, "600699", Period.DAILY, Adjust.QFQ, 800)
    web = _run_backtest(
        prepared, BacktestRequest(strategy="ma_cross", symbol="SH:600699", cash=100000)
    )
    assert actual["performance"] == web["performance"]
    assert actual["config"]["performance_basis"] == web["data_provenance"]["performance_basis"]
    assert actual["trades"] == web["trades"]


def test_cli_import_and_help_do_not_require_web_extra():
    script = """
import importlib.abc
import sys
class NoWeb(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'fastapi', 'pydantic', 'uvicorn'}:
            raise ImportError('optional Web dependency requested: ' + fullname)
sys.meta_path.insert(0, NoWeb())
from easy_tdx.backtest.cli import backtest
from click.testing import CliRunner
result = CliRunner().invoke(backtest, ['--help'])
assert result.exit_code == 0, result.exception
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
