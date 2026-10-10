"""Verify actual downloaded browser archives with no live data access."""
import copy
import json
import sys
from pathlib import Path
from unittest.mock import patch

from easy_tdx.factor.builtin.gtja191 import GTJAFactor, GTJAPanelFactor
from easy_tdx.web.factor_archive import validate_factor_archive
from easy_tdx.web.routers import research
from tests.unit.test_factor_archive import record

for path in map(Path, sys.argv[1:]):
    original = json.loads(path.read_text())
    before = copy.deepcopy(original)
    with patch.object(GTJAFactor, "compute", side_effect=AssertionError("read-only compute")), patch.object(
        GTJAPanelFactor, "compute_panel", side_effect=AssertionError("read-only compute")
    ):
        validate_factor_archive(original)
    with patch.object(research, "fetch_adjusted_bars", side_effect=AssertionError("live bars")):
        newer = research.recompute_factor_payload(record(original))
    validate_factor_archive(newer)
    for key in ("rows", "reports", "latest"):
        if key in original["result"]:
            assert newer["result"][key] == original["result"][key], (path.name, key)
    assert original == before
    print(path.name, "read-only/no-fetch replay/original preserved: PASS")
    if path.name == "gtja-conditional-series.json":
        result = original["result"]
        assert result["settings"]["factor_parameters"] == {"gtja191_132": {"window": 7}}
        assert result["factor_data_contract"]["amount_unit"] == "CNY"
        assert result["input_count"] == 160
        assert not result["errors"]
        print("settings:", result["settings"])
        print("unit provenance:", result["factor_data_contract"])
        print("definitions:", [(k, v["implementation_version"], v["resolved_parameters"], v["warmup_bars"])
                               for k, v in result["factor_definitions"].items()])
