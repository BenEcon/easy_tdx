"""Actual indicator outputs on explicitly synthetic bars, for cross-language QA."""
import json
import sys

from easy_tdx.indicator import list_indicators
from easy_tdx.web.archive_indicators import SavedChartIndicators, recompute_chart_indicators
from tests.unit.test_chanlun_replay import snapshot

bars = [{**row, "datetime": row["datetime"].isoformat(sep=" "), "amount": 1000} for row in snapshot(160)]
specs = [{"type": "none", "params": {}}, {"type": "volume", "params": {}}] + [
    {"type": row["name"].lower(), "params": row["default_params"]} for row in list_indicators()
]
cases = []
for i in range(0, len(specs), 8):
    settings = SavedChartIndicators(averages=[{"period": 5, "enabled": True}, {"period": 17, "enabled": False}], indicators=specs[i:i+8])
    cases.append({"settings": settings.model_dump(), "output": recompute_chart_indicators(bars, settings)})
json.dump({"bars": bars, "cases": cases}, sys.stdout, ensure_ascii=False, allow_nan=False)
