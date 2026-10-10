"""Local-only browser check of real auth/middleware with isolated temporary data."""
import os
import tempfile
from pathlib import Path
from contextlib import asynccontextmanager

import pandas as pd

from easy_tdx.web.app import _create_app
from easy_tdx.web.deps import get_client, get_mac_client_optional
from qa_range_app import FixtureFeed

resume = os.environ.get("EASY_TDX_QA_CONFIG")
if resume:
    resume_path = Path(resume).resolve()
    assert resume_path.is_relative_to(Path(tempfile.gettempdir()).resolve())
    assert resume_path.name.startswith("tdx-security-qa-")
    assert (resume_path / "accounts.db").is_file()
os.environ["EASY_TDX_CONFIG_DIR"] = resume or tempfile.mkdtemp(prefix="tdx-security-qa-")
os.environ.pop("EASY_TDX_ADMIN_PASSWORD", None)
os.environ.pop("EASY_TDX_ALLOWED_ORIGINS", None)
os.environ.pop("EASY_TDX_SECURE_COOKIES", None)

app = _create_app(host="127.0.0.1", enable_mac=False)


@asynccontextmanager
async def offline_lifespan(_app):
    yield


app.router.lifespan_context = offline_lifespan
class SecurityFixtureFeed(FixtureFeed):
    async def get_security_quotes(self, pairs):
        return pd.DataFrame([
            dict(market=getattr(market, 'value', market), code=code,
                 name='模拟验收标的', price=39.2)
            for market, code in pairs
        ])


feed = SecurityFixtureFeed()
app.dependency_overrides[get_client] = lambda: feed
app.dependency_overrides[get_mac_client_optional] = lambda: feed
