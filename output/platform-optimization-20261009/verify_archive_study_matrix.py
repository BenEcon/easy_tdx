"""Generate actual multi-period outputs from unchanged, hash-checked frozen cases."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from easy_tdx.web.routers.chanlun_observations import StudyRequest, observations
from tests.market_matrix import entries, load_case


results = []
for entry in entries():
    _, _, snapshot = load_case(entry)
    observed = datetime.fromisoformat(entry["observed_at"])
    if observed.tzinfo:
        observed = observed.astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    request = StudyRequest(
        as_of=observed,
        series=[{
            "code": entry["code"], "category": entry["category"],
            "bars": snapshot["data"], "bar_time": "end",
        }],
    )
    results.append({"id": entry["id"], "result": observations(request)})
print(json.dumps(results, ensure_ascii=False, allow_nan=False))
