"""Build an explicit observation list from a frozen research result, never recompute."""

from __future__ import annotations

import json
import math
import re
import uuid
from typing import Any

from easy_tdx.web.research_archive import ArchiveError, _archive_time


def factor_tracking_group(
    record: dict[str, Any],
    *,
    name: str,
    score_key: str,
    symbols: list[str],
    labels: dict[str, str],
    digest: str,
    revision: int,
) -> dict[str, Any]:
    if record["state"] != "active":
        raise ArchiveError(409, "请先恢复原始研究存档，再建立追踪分组")
    if record["digest"] != digest or record["revision"] != revision:
        raise ArchiveError(409, "原始存档已变化，请重新打开后选择")
    payload = record["payload"]
    if record["kind"] != "factor" or payload.get("mode") != "evaluation":
        raise ArchiveError(422, "仅支持完整的因子截面研究原档")
    result = payload["result"]
    if not name.strip() or len(name) > 40:
        raise ArchiveError(422, "分组名称须为 1—40 字")
    if not 1 <= len(symbols) <= 20 or len(set(symbols)) != len(symbols):
        raise ArchiveError(422, "请明确选择 1—20 个不同标的")
    if set(labels) - set(symbols) or any(len(label) > 80 for label in labels.values()):
        raise ArchiveError(422, "显示名称只能属于所选标的，且最多 80 字")
    if score_key == "composite_score":
        composition = result.get("composition")
        if not composition or composition.get("error"):
            raise ArchiveError(422, "此原档没有可用的组合评分")
        rows, field = composition["latest"], "score"
        label = "固定权重组合评分"
    else:
        if score_key not in result["settings"]["factors"] or score_key in result["errors"]:
            raise ArchiveError(422, "此原档没有所选因子的有效结果")
        rows, field = result["latest"], score_key
        label = result["factor_definitions"][score_key].get("display_name", score_key)
        if not isinstance(label, str):
            label = score_key
    pool = [f"{s['market']}:{s['code']}" for s in result["settings"]["stocks"]]
    # Validate the lookup as a whole; duplicates must not silently overwrite a score.
    if (
        not isinstance(rows, list)
        or len(rows) != len(pool)
        or any(not isinstance(r, dict) or not isinstance(r.get("code"), str) for r in rows)
        or {r.get("code") for r in rows} != set(pool)
    ):
        raise ArchiveError(422, "原档最新评分与股票池不一致；未补算或修复")
    try:
        _archive_time(result["end"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ArchiveError(422, "原档缺少有效评分日期；未自动修复") from exc
    lookup = {r["code"]: r.get(field) for r in rows}
    targets, selection = [], []
    for symbol in sorted(symbols):
        # This bridge is for A-share equity research. Do not mislabel an index,
        # bond or fund merely because the legacy research input has no kind field.
        if not re.fullmatch(r"(?:SH:6\d{5}|SZ:(?:00|30)\d{4}|BJ:(?:43|83|87|92)\d{4})", symbol):
            raise ArchiveError(422, f"{symbol} 不是此入口支持的 A 股代码；请按正确类型手动追踪")
        score = lookup.get(symbol)
        if (
            isinstance(score, bool)
            or not isinstance(score, int | float)
            or not math.isfinite(score)
        ):
            raise ArchiveError(422, f"{symbol} 没有该观测日的有限评分；未填零或回退到旧日期")
        market, code = symbol.split(":")
        targets.append(
            {"kind": "stock", "market": market, "code": code, "name": labels.get(symbol, "")}
        )
        selection.append({"symbol": symbol, "score": score})
    identity = json.dumps([record["id"], digest, score_key, sorted(symbols)], separators=(",", ":"))
    return {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "easy-tdx:factor-tracking:" + identity)),
        "name": name.strip(),
        "targets": targets,
        "research_source": {
            "format": "factor-tracking-source-v1",
            "archive_id": record["id"],
            "archive_digest": digest,
            "archive_revision": revision,
            "title": payload["title"],
            "score_key": score_key,
            "score_label": label,
            "date": result["end"],
            "input_fingerprint": result["input_fingerprint"],
            "selection": selection,
            "provenance": "client_archive_not_server_verified",
            "names": "user_display_labels_not_historical_security_master",
        },
    }
