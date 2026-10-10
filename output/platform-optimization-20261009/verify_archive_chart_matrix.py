"""Actual complete chart exports from hash-checked frozen cases, without network."""

import json

from easy_tdx.chanlun import ChanlunAnalyser
from tests.market_matrix import entries, load_case


records = []
for entry in entries():
    _, frame, snapshot = load_case(entry)
    result = ChanlunAnalyser(code=entry["code"], frequency=entry["category"]).process_klines(frame)
    records.append({"id": entry["id"], "bars": snapshot["data"], "result": result.to_dict()})
print(json.dumps(records, ensure_ascii=False, allow_nan=False))
