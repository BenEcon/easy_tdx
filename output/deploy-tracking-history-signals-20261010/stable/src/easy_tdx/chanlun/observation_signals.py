"""Expose existing chart signals; do not infer trading points from observations."""

from copy import deepcopy
from typing import Any

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.anchors import extreme_index


def observation_signals(result: ChanlunResult, start_date: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def add(
        kind: str,
        family: str,
        side: str,
        anchor: int,
        known: int,
        price: float,
        source: str,
        reason: str,
        evidence: dict[str, Any],
    ) -> None:
        if not 0 <= anchor <= known < len(result.klines):
            return
        date, confirmed = str(result.klines[anchor].date), str(result.klines[known].date)
        # An older extremum newly confirmed in this window must remain visible.
        if date < start_date and confirmed < start_date:
            return
        records.append(
            {
                "type": kind,
                "family": family,
                "side": side,
                "status": "confirmed",
                "date": date,
                "confirmed_date": confirmed,
                "price": price,
                "source": source,
                "reason": reason,
                "evidence": deepcopy(evidence),
            }
        )

    for point in result.mmds:
        if point.bi is None or point.confirmed_index is None:
            continue
        add(
            point.mmd_type.value,
            "structure",
            "buy" if point.mmd_type.value.endswith("buy") else "sell",
            extreme_index(point.bi.end),
            point.confirmed_index,
            point.bi.end.val,
            point.source,
            point.msg,
            point.evidence,
        )
    # Exactly the chart's M1 eligibility, kept separate from structure one-class points.
    for item in result.bcs:
        anchor, known = item.signal_index, item.confirmed_index
        if not (
            item.bc
            and item.bc_type.value == "macd_wave"
            and item.status == "confirmed"
            and item.direction in ("up", "down")
            and anchor is not None
            and known is not None
            and 0 <= anchor < known < len(result.klines)
        ):
            continue
        buy = item.direction == "down"
        price = result.klines[anchor].low if buy else result.klines[anchor].high
        add(
            "M1",
            "macd",
            "buy" if buy else "sell",
            anchor,
            known,
            price,
            "macd_wave",
            "标准 MACD 波段已确认提示，非缠论结构一类点",
            item.evidence,
        )
    return sorted(records, key=lambda item: (item["confirmed_date"], item["date"]), reverse=True)
