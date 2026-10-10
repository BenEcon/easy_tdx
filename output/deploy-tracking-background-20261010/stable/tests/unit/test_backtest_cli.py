"""回测 CLI 命令测试。"""

from __future__ import annotations

from click.testing import CliRunner


class TestBacktestCLI:
    """测试回测 CLI 命令。"""

    def test_help(self):
        """测试 --help 显示帮助。"""
        from easy_tdx.backtest.cli import backtest

        runner = CliRunner()
        result = runner.invoke(backtest, ["--help"])
        assert result.exit_code == 0
        assert "回测引擎" in result.output
        assert "--strategy-file" in result.output
        assert "--cash" in result.output
        assert "--commission" in result.output

    def test_missing_strategy_fails(self):
        """测试不指定策略则失败。"""
        from easy_tdx.backtest.cli import backtest

        runner = CliRunner()
        result = runner.invoke(backtest, ["SZ", "000001"])
        assert result.exit_code == 1
        assert "必须指定" in result.output or "错误" in result.output
