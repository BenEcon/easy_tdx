"""Isolated UI acceptance: frozen market input, real scan/replay/backtest engines.

No production accounts or network data. Task transport and account identity are QA-only.
"""
import asyncio
import json
from fastapi import APIRouter, HTTPException
from qa_evidence_app import app, bars, entries, load_case, ROOT, user
from easy_tdx.web.routers.backtest import list_strategies, run_backtest
from easy_tdx.web.backtest_schemas import BacktestRequest
from easy_tdx.web.signal_scan import ScanTarget, run_scan
from easy_tdx.web.bar_snapshot import annotate_snapshot
from easy_tdx.web.market_data import closed_frame
from datetime import datetime

qa = APIRouter(prefix="/api/v1")

@qa.put("/auth/me/preferences")
def preferences(body: dict):
    user["preferences"] = body["preferences"]
    return {"user":user}

entry = next(row for row in entries() if row["id"] == "stock-300750-min_30-20261009")
_, frame, source = load_case(entry)
frame = frame[frame.datetime <= "2026-09-30 14:30:00"].copy()
frozen = annotate_snapshot(frame.to_dict("records"), "MIN_30", source="MAC", requested_adjust="QFQ", actual_adjust="QFQ", bar_time="end", now=datetime(2026, 9, 30, 14, 30))
frame.attrs["snapshot_metadata"] = frozen["metadata"]
frame = closed_frame(frame)
day_entry = next(row for row in entries() if row["code"] == "600699" and row["category"] == "DAY")
_, day_frame, _ = load_case(day_entry)
day_frame = day_frame.iloc[:647].copy()
day_frozen = annotate_snapshot(day_frame.to_dict("records"), "DAY", source="MAC", requested_adjust="QFQ", actual_adjust="QFQ", bar_time="end", now=datetime(2026, 2, 10, 16))
day_frame.attrs["snapshot_metadata"] = day_frozen["metadata"]
day_frame = closed_frame(day_frame)
targets = [ScanTarget(strategy_id="chanlun_mmd", strategy_name="本机真实 chanlun_mmd", kind="single", strategy="chanlun_mmd", strategy_label="缠论买卖点", symbol="SH:600699", category="DAY"),
           ScanTarget(strategy_id="ma_cross", strategy_name="本机真实 ma_cross", kind="single", strategy="ma_cross", strategy_label="均线交叉", symbol="SZ:300750", category="MIN_30")]
scan_result = run_scan({("SZ:300750", "MIN_30"): frame, ("SH:600699", "DAY"):day_frame}, targets, 5)
(ROOT / "output/platform-optimization-20261009/radar-qa-result.json").write_text(json.dumps(scan_result, ensure_ascii=False, indent=2), encoding="utf-8")

@qa.post("/backtest/signal-scan/run/async")
async def submit():
    await asyncio.sleep(2)
    return {"task_id":"qa-radar"}

@qa.get("/backtest/tasks/qa-radar")
def task():
    return {"task_id":"qa-radar", "status":"done", "result":scan_result}

@qa.get("/backtest/strategies")
async def strategies():
    return await list_strategies()

@qa.post("/backtest/run")
async def backtest(req: BacktestRequest):
    return await run_backtest(req)

@qa.get("/bars/range")
def bar_range(category: str = "DAY", code: str = "300750", adjust: str = "QFQ"):
    if adjust != "QFQ":
        raise HTTPException(503, "本机仅提供冻结 QFQ 行情")
    return bars(category, code)

app.router.routes = qa.routes + app.router.routes
