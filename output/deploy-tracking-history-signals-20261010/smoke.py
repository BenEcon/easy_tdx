"""Release image + real loopback HTTP + disposable accounts; never production data."""
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
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
    # Seed an old-format account database and verify migration without granting access.
    from easy_tdx.web.account_store import AccountStore
    old = AccountStore(Path(config) / "accounts.db")
    password = secrets.token_urlsafe(24)
    admin = old.create_user("release-admin", password, role="admin", initial=True)
    member = old.create_user("release-member", password)
    with sqlite3.connect(old.db_path) as db:
        db.execute("ALTER TABLE users DROP COLUMN tracking_allowed")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(path, body=None, cookie=None, method=None, extra=None, origin="https://tdx.bowenv.com"):
        headers = {"Origin": origin, "Content-Type": "application/json", "X-Forwarded-Proto": "https"}
        if cookie: headers["Cookie"] = cookie
        headers.update(extra or {})
        req = urllib.request.Request("http://127.0.0.1:18096/api/v1" + path, headers=headers,
                                     data=None if body is None else json.dumps(body).encode(), method=method)
        try: response = opener.open(req, timeout=90)
        except urllib.error.HTTPError as error: response = error
        content = response.read()
        return response.status, response.headers, json.loads(content) if content else None
    def start():
        process = subprocess.Popen([sys.executable, __file__, "serve"], env=env)
        for _ in range(150):
            if process.poll() is not None: raise AssertionError("isolated server exited")
            try:
                status, _, data = request("/auth/status")
                assert status == 200 and not data["setup_required"]
                return process
            except (urllib.error.URLError, ConnectionError): time.sleep(.1)
        process.terminate()
        raise AssertionError("server did not start")
    def login(username):
        status, headers, data = request("/auth/login", {"username":username,"password":password})
        assert status == 200, (status,data)
        cookie = headers["Set-Cookie"]
        assert all(term in cookie for term in ("Secure","HttpOnly","SameSite=lax"))
        return cookie.split(";",1)[0],data["user"]
    process = start()
    try:
        ac, au = login("release-admin")
        mc, mu = login("release-member")
        assert au["role"] == "admin" and mu["tracking_allowed"] is False
        assert request("/auth/me",cookie=ac,extra={"X-Tracking-Owner":mu["id"]})[0] == 409
        assert request("/auth/me",cookie=mc,extra={"X-Tracking-Owner":mu["id"]})[0] == 403
        assert request("/auth/me",cookie=ac,extra={"X-Tracking-Owner":au["id"]})[0] == 200
        for path in ("/admin/activity/summary", "/admin/activity/events"):
            assert request(path)[0] == 401
            assert request(path,cookie=mc)[0] == 403
            assert request(path,cookie=ac)[0] == 200
        assert request("/chanlun/replay", {}, ac, origin="https://untrusted.invalid")[0] == 403
        assert request("/chanlun/replay", {})[0] == 401
        groups = {"tracking_groups":{"groups":[{"name":"preserved"}]}}
        assert request("/auth/me/preferences", {"preferences":groups},mc,"PUT")[0] == 403
        assert request(f"/admin/users/{mu['id']}", {"tracking_allowed":True},mc,"PATCH")[0] == 403
        assert request(f"/admin/users/{mu['id']}", {"tracking_allowed":True},ac,"PATCH")[0] == 200
        assert request("/auth/me",cookie=mc,extra={"X-Tracking-Owner":mu["id"]})[0] == 200
        assert request("/auth/me/preferences", {"preferences":groups},mc,"PUT")[0] == 200
        assert request(f"/admin/users/{mu['id']}", {"tracking_allowed":False},ac,"PATCH")[0] == 200
        assert request("/auth/me",cookie=mc,extra={"X-Tracking-Owner":mu["id"]})[0] == 403
        print("PASS tracking owner binding, access grant and revoke",flush=True)
        assert request("/auth/me/preferences", {"preferences":{"tracking_groups":{}}},mc,"PUT")[0] == 403
        assert request("/auth/me",cookie=mc)[2]["user"]["preferences"] == groups
        assert request("/auth/activity", {},mc,extra={"X-Research-Owner":mu["id"]})[0] == 200
        assert request("/auth/activity", {},mc,extra={"X-Research-Owner":au["id"]})[0] == 409
        print("PASS legacy migration, secure authentication, grant/revoke/preserve, admin-only activity",flush=True)
        day_study = day_bars = None
        for path in sorted((root/"cases").glob("*.json")):
            if path.name.startswith("."):
                continue  # macOS AppleDouble metadata is not a market fixture.
            fixture=json.loads(path.read_text())
            bars=fixture.get("bars",fixture.get("data"))
            closed=[bar for bar in bars if bar.get("is_closed") is not False]
            category=fixture.get("category") or path.stem
            status,_,result=request("/chanlun/replay?ownership_history=summary",{"code":"300750","category":category,"bars":closed,"visible_count":len(closed)},mc)
            assert status == 200 and "bcs" in result,(category,status,result)
            status,_,study=request("/chanlun/observations",{"as_of":"2026-10-09 23:59:59","series":[{"code":"300750","category":category,"bars":closed,"bar_time":"end"}],"ma_periods":[5,10,20,30,60,120,250]},mc)
            assert status == 200 and len(study["rows"]) == 1 and study["eligible_for_trading"] is False,(status,study)
            assert "buy_sell_points" in study["rows"][0]
            for point in study["rows"][0]["buy_sell_points"]:
                assert point["date"] <= point["confirmed_date"] <= point["known_at"] <= study["as_of"]
                assert point["family"] in ("structure", "macd")
            if category == "DAY":
                day_study, day_bars = study, closed
            print("PASS actual HTTP replay/observations",category,len(closed),flush=True)
        events=request("/admin/activity/events",cookie=ac)[2]["items"]
        queries=[item for item in events if item["kind"]=="query"]
        assert len(queries)==10 and all("bars" not in item["details"] for item in queries)
        assert request(f"/admin/activity/events/{events[-1]['id']}/location",{},ac)[2]["state"] == "local"
        key=str(uuid.uuid4())
        payload={"schema":1,"title":"release QA","cutoff":"2026-10-09 15:00:00","target":{"kind":"stock","market":"SZ","code":"300750"},"charts":[{"category":"DAY","bars":[{"datetime":"2026-10-09 00:00:00","open":100.123456,"high":102,"low":99,"close":101}],"result":{"bis":[],"xds":[],"zss":[],"bcs":[],"mmds":[]}}],"opaque":"x"*(11*1024*1024)}
        payload.update(preferences={"maPeriods":[5,10]}, layers={"bis":True})
        payload["charts"][0]["metadata"]={"actual_adjust":"QFQ","source":"release-test"}
        created=request(f"/research/archives/{key}",{"kind":"chart","payload":payload,"name":"release QA"},mc,"PUT")
        assert created[0] == 201,(created[0],created[2])
        assert request(f"/research/archives/{key}",cookie=ac)[0] == 404
        assert request(f"/research/archives/{key}",cookie=mc)[2]["payload"] == payload
        assert day_study and day_bars
        target={"kind":"stock","market":"SZ","code":"300750","name":"合成验收"}
        tracking={"format":"tracking-analysis-v2","group":{"id":"qa","name":"发布验收","targets":[target]},
                  "revision":"qa","periods":["DAY"],"cutoff":day_study["as_of"],"finished_at":"2026-10-10T03:00:00Z",
                  "membership_observed_at":day_study["as_of"],"state":"completed","phase":"完成","error":"","issues":[],
                  "rows":[{"target":target,"sources":["直接追踪"],"state":"done","study":day_study,
                           "evidence":{"adjust":"QFQ","requested_count":800,"series":[{"category":"DAY","snapshot":{"bars":day_bars,"metadata":{"category":"DAY","actual_adjust":"QFQ","bar_time":"end"}}}]}}]}
        history_key=str(uuid.uuid4())
        body={"kind":"tracking","payload":tracking,"name":"tracking QA"}
        assert request(f"/research/archives/{history_key}",body,mc,"PUT")[0] == 403
        assert request(f"/admin/users/{mu['id']}", {"tracking_allowed":True},ac,"PATCH")[0] == 200
        assert request(f"/research/archives/{history_key}",body,mc,"PUT",extra={"X-Research-Owner":au["id"]})[0] == 409
        assert request(f"/research/archives/{history_key}",body,mc,"PUT",extra={"X-Research-Owner":mu["id"]})[0] == 201
        assert request(f"/research/archives/{history_key}",body,mc,"PUT")[0] == 200
        assert request(f"/research/archives/{history_key}",cookie=ac)[0] == 404
        assert request(f"/research/archives/{history_key}",cookie=mc)[2]["payload"] == tracking
        process.terminate();process.wait(timeout=20);process=start()
        assert request(f"/research/archives/{history_key}",cookie=mc)[2]["payload"] == tracking
        print("PASS tracking raw evidence, signal dates, permission, idempotence, owner isolation, restart persistence",flush=True)
        assert request(f"/research/archives/{key}",cookie=mc)[2]["payload"] == payload
        assert request("/auth/me",cookie=mc)[2]["user"]["preferences"] == groups
        assert request("/admin/activity/events",cookie=ac)[2]["items"] == events
        assert request("/auth/logout",{},mc)[0] == 200
        assert request("/auth/me",cookie=mc)[0] == 401
        print("PASS query metadata, 11 MiB archive, owner isolation, restart persistence, logout",flush=True)
    finally:
        process.terminate();process.wait(timeout=20)
