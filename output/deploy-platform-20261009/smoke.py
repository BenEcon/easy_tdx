"""Actual production image, isolated accounts and frozen real market snapshots."""
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

if len(sys.argv) > 1 and sys.argv[1] == "serve":
    import uvicorn
    from easy_tdx.web.app import _create_app
    uvicorn.run(_create_app(host="127.0.0.1", enable_mac=False), host="127.0.0.1", port=18096,
                lifespan="off", log_level="error", forwarded_allow_ips="127.0.0.1")
    raise SystemExit

root = Path(__file__).parent
with tempfile.TemporaryDirectory(prefix="release-qa-") as config:
    env = dict(os.environ, EASY_TDX_CONFIG_DIR=config, EASY_TDX_SECURE_COOKIES="1",
               EASY_TDX_ALLOWED_ORIGINS="https://tdx.bowenv.com", EASY_TDX_TASK_BACKEND="memory")
    process = subprocess.Popen([sys.executable, __file__, "serve"], env=env)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(path, body=None, cookie=None, origin="https://tdx.bowenv.com"):
        headers = {"Origin": origin, "Content-Type": "application/json", "X-Forwarded-Proto": "https"}
        if cookie:
            headers["Cookie"] = cookie
        req = urllib.request.Request("http://127.0.0.1:18096" + path, headers=headers,
                                     data=None if body is None else json.dumps(body).encode())
        try:
            response = opener.open(req, timeout=90)
        except urllib.error.HTTPError as error:
            response = error
        content = response.read()
        return response.status, response.headers, json.loads(content) if content else None
    try:
        for _ in range(100):
            try:
                status, _, data = request("/api/v1/auth/status")
                assert status == 200 and data["setup_required"]
                break
            except (urllib.error.URLError, ConnectionError):
                time.sleep(.1)
        else:
            raise AssertionError("isolated server did not start")
        password = secrets.token_urlsafe(24)
        status, headers, data = request("/api/v1/auth/setup", {"username": "release-qa", "password": password})
        assert status == 201, (status, data)
        cookie = headers["Set-Cookie"]
        assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
        cookie = cookie.split(";", 1)[0]
        assert request("/api/v1/auth/me", cookie=cookie)[0] == 200
        assert request("/api/v1/chanlun/replay", {}, cookie=cookie, origin="https://untrusted.invalid")[0] == 403
        assert request("/api/v1/chanlun/replay", {})[0] == 401
        for path in sorted((root / "cases").glob("[!.]*.json")):
            fixture = json.loads(path.read_text())
            bars = fixture.get("bars", fixture.get("data"))
            category = fixture.get("category") or path.stem.split("-")[-1]
            code = "300750"
            closed = [bar for bar in bars if bar.get("is_closed") is not False]
            req = {"code": code, "category": category, "bars": closed, "visible_count": len(closed)}
            status, _, result = request("/api/v1/chanlun/replay?ownership_history=summary", req, cookie)
            assert status == 200 and result["code"] == code and "bcs" in result, (category, status, result)
            status, _, study = request("/api/v1/chanlun/observations", {
                "as_of": "2026-10-09 23:59:59", "series": [{"code": code, "category": category, "bars": closed, "bar_time": "end"}],
                "ma_periods": [5, 10, 20, 30, 60, 120, 250]}, cookie)
            assert status == 200 and len(study["rows"]) == 1, (category, status, study)
            assert study["eligible_for_trading"] is False
            json.dumps(study, allow_nan=False)
            print("PASS actual HTTP replay/observations:", category, len(closed), flush=True)
        assert request("/api/v1/auth/logout", {}, cookie)[0] == 200
        assert request("/api/v1/auth/me", cookie=cookie)[0] == 401
        print("PASS isolated authentication, secure cookies, origin checks, protected API, logout", flush=True)
    finally:
        process.terminate()
        process.wait(timeout=20)
