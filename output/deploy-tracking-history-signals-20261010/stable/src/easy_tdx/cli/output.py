"""CLI 输出格式化：JSON（默认）、表格、CSV。"""

from __future__ import annotations

import click
import pandas as pd


def format_output(df: pd.DataFrame, fmt: str = "json") -> str:
    """将 DataFrame 格式化为指定输出格式。"""
    if df.empty:
        return "[]" if fmt == "json" else ""

    if fmt == "json":
        result: str = df.to_json(orient="records", force_ascii=False, date_format="iso")
        return result
    if fmt == "csv":
        return str(df.to_csv(index=False))
    if fmt == "table":
        return _render_table(df)
    raise click.UsageError(f"不支持的输出格式: {fmt}")


def print_output(df: pd.DataFrame, fmt: str = "json") -> None:
    """格式化并输出 DataFrame 到 stdout。"""
    text = format_output(df, fmt)
    if text:
        click.echo(text)


def print_error(msg: str) -> None:
    """输出错误消息到 stderr。"""
    click.echo(f"错误: {msg}", err=True)


def _render_table(df: pd.DataFrame) -> str:
    """将 DataFrame 渲染为人类可读的文本表格。"""
    return _render_table_impl(df, truncate=30)


def _render_table_full(df: pd.DataFrame) -> str:
    """渲染表格但**不截断**长文本列（适用于 url/title 等长字段）。"""
    return _render_table_impl(df, truncate=None)


def _render_table_impl(df: pd.DataFrame, truncate: int | None) -> str:
    """表格渲染实现。``truncate=None`` 时不截断 object 列。"""
    if df.empty:
        return "(无数据)"

    display_df = df.copy()
    for col in display_df.columns:
        if display_df[col].dtype == object and truncate is not None:
            display_df[col] = display_df[col].astype(str).str.slice(0, truncate)

    try:
        import tabulate

        return str(tabulate.tabulate(display_df, headers="keys", tablefmt="grid", showindex=False))
    except ImportError:
        lines: list[str] = []
        cols = list(display_df.columns)
        header = " | ".join(str(c) for c in cols)
        cap = truncate if truncate is not None else 100
        sep = "-+-".join("-" * min(len(str(c)), cap) for c in cols)
        lines.append(header)
        lines.append(sep)
        for _, row in display_df.iterrows():
            line = " | ".join(str(v)[:cap] for v in row.values)
            lines.append(line)
        return "\n".join(lines)
