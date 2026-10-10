"""Derive distinct queried instruments from allow-listed metadata, never raw bodies."""

from __future__ import annotations

import json
import re
from typing import Any

_PART = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")


def query_targets(details: dict[str, Any]) -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}

    def add(value: Any, market: Any = None) -> None:
        if not isinstance(value, str):
            return
        for token in value.split(",")[:100]:
            token_market = market
            parts = token.strip().split(":")
            if len(parts) == 3 and parts[0] in {"stock", "index", "board", "fund"}:
                token_market, code = ("BOARD" if parts[0] == "board" else parts[1]), parts[2]
            elif len(parts) == 2:
                token_market, code = parts
            elif len(parts) == 1:
                code = parts[0]
                match = re.fullmatch(r"(SH|SZ|BJ)(\d{6})", code, re.I)
                if match:
                    token_market, code = match.groups()
            else:
                continue
            if not _PART.fullmatch(code):
                continue
            venue = (
                token_market.upper()
                if isinstance(token_market, str) and _PART.fullmatch(token_market)
                else "?"
            )
            key = f"{venue}:{code}"
            found[key] = {"key": key, "code": code, "market": venue}

    primary_market = "BOARD" if details.get("kind") == "board" else details.get("market")
    add(details.get("code"), primary_market)
    add(details.get("symbol"), primary_market)
    add(details.get("stock_code"), details.get("stock_market", details.get("market")))
    for key in ("board_code", "board_symbol"):
        add(details.get(key), "BOARD")
    for key in ("stocks", "symbols", "codes", "series"):
        values = details.get(key)
        if not isinstance(values, list):
            continue
        for value in values[:100]:
            if isinstance(value, dict):
                add(value.get("code"), value.get("market", details.get("market")))
            elif isinstance(value, list) and len(value) == 2:
                add(value[1], value[0])
            else:
                add(value, details.get("market"))
    return list(found.values())


def targets_json(encoded: str) -> str:
    try:
        details = json.loads(encoded)
        targets = query_targets(details) if isinstance(details, dict) else []
    except (ValueError, TypeError):
        targets = []
    return json.dumps(targets, ensure_ascii=False)
