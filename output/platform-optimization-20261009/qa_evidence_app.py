"""Local UI acceptance only: frozen real bars, actual replay, isolated mock identity."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
CONFIG = tempfile.TemporaryDirectory(prefix="tdx-evidence-qa-")
os.environ["EASY_TDX_CONFIG_DIR"] = CONFIG.name

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from easy_tdx.web.routers.chanlun_replay import router
from easy_tdx.web.routers.chanlun_observations import router as observations_router
from tests.market_matrix import entries, load_case

app = FastAPI()
app.include_router(router, prefix="/api/v1")
app.include_router(observations_router, prefix="/api/v1")
app.mount("/assets", StaticFiles(directory=ROOT / "web-ui/dist/assets"))
entry = next(row for row in entries() if row["id"] == "stock-300750-day-20261009")
snapshot = load_case(entry)[2]
user = dict(id="evidence-local-qa", username="本机证据验收", role="admin", preferences={}, active=True)

@app.get("/api/v1/auth/status")
def status():
    return dict(user=user, authenticated=True, setup_required=False)

@app.get("/api/v1/bars")
def bars(category: str = "DAY", code: str = "300750"):
    import json
    from fastapi import HTTPException
    match = next((row for row in entries() if row["code"] == code and row["category"] == category and row["adjust"] == "QFQ"), None)
    if match:
        return load_case(match)[2]
    minute = ROOT / "output/platform-optimization-20261009" / f"overview-300750-{category}.json"
    if code == "300750" and category in ("MIN_15", "MIN_5") and minute.is_file():
        return json.loads(minute.read_text())
    raise HTTPException(status_code=503, detail="本机验收：该周期冻结行情尚未提供")

@app.api_route("/api/v1/{path:path}", methods=["GET", "POST", "PATCH", "PUT"])
def other(path: str):
    if path.startswith("auth/me"):
        return {"user": user}
    return {"data": [], "count": 0}

@app.get("/{path:path}")
def index(path: str):
    return FileResponse(ROOT / "web-ui/dist/index.html")
