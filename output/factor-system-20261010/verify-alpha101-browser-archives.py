"""Actual browser exports: read-only must not call kernels, replay must not fetch."""
import copy
import json
import sys
from pathlib import Path
from unittest.mock import patch

from easy_tdx.factor.builtin.alpha101 import Alpha101Factor, Alpha101PanelFactor
from easy_tdx.web.factor_archive import validate_factor_archive
from easy_tdx.web.routers import research
from tests.unit.test_factor_archive import record

for path in map(Path,sys.argv[1:]):
    original=json.loads(path.read_text())
    before=copy.deepcopy(original)
    with patch.object(Alpha101Factor,"compute",side_effect=AssertionError("read computed")), patch.object(Alpha101PanelFactor,"compute_panel",side_effect=AssertionError("read computed")):
        validate_factor_archive(original)
    with patch.object(research,"fetch_adjusted_bars",side_effect=AssertionError("live fetched")):
        newer=research.recompute_factor_payload(record(original))
    validate_factor_archive(newer)
    for key in ("rows","reports","latest"):
        if key in original["result"]:
            assert newer["result"][key]==original["result"][key],(path.name,key)
    assert original==before
    print(path.name,"read-only/no-fetch replay/original preserved: PASS")
