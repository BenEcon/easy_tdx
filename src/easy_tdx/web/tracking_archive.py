"""Validate immutable tracking batches without fetching or recalculating markets."""

from __future__ import annotations

import re
from typing import Any

from easy_tdx.web.research_archive import _PERIODS, ArchiveError, _archive_time, _bars


def validate_tracking_archive(payload: dict[str, Any]) -> None:
    def require(ok: Any) -> None:
        if not ok:
            raise ValueError("inconsistent tracking archive")

    def target(value: Any) -> tuple[str, str, str, str]:
        require(isinstance(value, dict))
        kind, market, code = value["kind"], value["market"], value["code"]
        require(kind in {"stock", "index", "board", "fund"})
        require(isinstance(code, str) and re.fullmatch(r"\d{6}", code))
        require(isinstance(value["name"], str) and len(value["name"]) <= 80)
        if kind == "board":
            require(isinstance(market, str) and re.fullmatch(r"[\w.-]{1,16}", market))
            require(value.get("boardType") in {"HY", "HY2", "GN", "FG", "DQ"})
        else:
            require(market in {"SH", "SZ", "BJ"})
        return kind, market, code, value.get("boardType", "")

    try:
        require(payload["format"] == "tracking-analysis-v2")
        group, periods, rows, issues = (payload[k] for k in ("group", "periods", "rows", "issues"))
        require(isinstance(group, dict) and isinstance(group["id"], str) and group["id"])
        require(isinstance(group["name"], str) and 0 < len(group["name"].strip()) <= 40)
        require(isinstance(group["targets"], list) and group["targets"])
        group_keys = [target(t) for t in group["targets"]]
        require(len(set(group_keys)) == len(group_keys))
        require(isinstance(periods, list) and 1 <= len(periods) <= 9)
        require(all(isinstance(p, str) and p in _PERIODS for p in periods))
        require(len(set(periods)) == len(periods))
        _archive_time(payload["cutoff"])
        _archive_time(payload["finished_at"])
        require(isinstance(payload["membership_observed_at"], str))
        if payload["membership_observed_at"]:
            _archive_time(payload["membership_observed_at"])
        require(payload["state"] in {"completed", "partial", "failed", "cancelled"})
        require(all(isinstance(payload[k], str) for k in ("phase", "error", "revision")))
        require(isinstance(rows, list) and isinstance(issues, list))
        for issue in issues:
            require(target(issue["target"]) in group_keys and issue["target"]["kind"] == "board")
            require(isinstance(issue["reason"], str) and issue["reason"])
        seen = set()
        for row in rows:
            key = target(row["target"])
            require(key not in seen)
            seen.add(key)
            require(isinstance(row["sources"], list) and row["sources"])
            require(all(isinstance(s, str) and s for s in row["sources"]))
            require(row["state"] in {"done", "error", "cancelled"})
            available = set()
            evidence = row.get("evidence")
            if evidence is not None:
                require(isinstance(evidence, dict) and evidence["requested_count"] == 800)
                require(evidence["adjust"] == ("QFQ" if key[0] == "stock" else "NONE"))
                require(isinstance(evidence["series"], list))
                for item in evidence["series"]:
                    category, snap = item["category"], item["snapshot"]
                    require(category in periods and category not in available)
                    available.add(category)
                    _bars(snap["bars"], snap["metadata"])
                    require(snap["metadata"]["actual_adjust"] == evidence["adjust"])
                    require(snap["metadata"]["category"] == category)
            study = row.get("study")
            if study is not None:
                require(isinstance(study, dict) and study["as_of"] == payload["cutoff"])
                require(isinstance(study["rule_version"], str))
                require(isinstance(study["rows"], list) and len(study["rows"]) == len(periods))
                categories = set()
                for result in study["rows"]:
                    category = result["category"]
                    require(category in periods and category not in categories)
                    categories.add(category)
                    require(
                        (isinstance(result.get("error"), str) and result["error"].strip())
                        or category in available
                    )
            if row["state"] == "done":
                require(study is not None and all(not r.get("error") for r in study["rows"]))
            if row["state"] == "error":
                require(isinstance(row.get("error"), str) and row["error"])
        if payload["state"] == "completed":
            require(rows and all(r["state"] == "done" for r in rows))
            require(not issues and not payload["error"])
            require(set(group_keys).issubset(seen))
        if payload["state"] == "partial":
            require(issues or any(r["state"] == "error" for r in rows))
        if payload["state"] == "failed":
            require(payload["error"].strip())
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
        raise ArchiveError(422, "追踪分析记录不完整、缺少原行情或状态不一致") from exc
