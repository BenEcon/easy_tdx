"""Loopback-only acceptance: actual login/routes, temporary data, no market startup."""

import os
import tempfile
from contextlib import asynccontextmanager

_data = tempfile.TemporaryDirectory(prefix="tdx-formal-archive-")
os.environ["EASY_TDX_CONFIG_DIR"] = _data.name
os.environ.pop("EASY_TDX_ADMIN_PASSWORD", None)
os.environ.pop("EASY_TDX_ALLOWED_ORIGINS", None)
os.environ.pop("EASY_TDX_SECURE_COOKIES", None)

from easy_tdx.web.account_store import get_account_store
from easy_tdx.web.app import _create_app

get_account_store().create_user("archive-qa", "Local-archive-QA-only-2026!", role="admin", initial=True)
get_account_store().create_user("archive-other", "Local-archive-QA-only-2026!", role="user")
app = _create_app(host="127.0.0.1", enable_mac=False)
app.state.tdx_client = None
app.state.mac_client = None
app.state.ex_client = None


@asynccontextmanager
async def local_only_lifespan(_app):
    yield


app.router.lifespan_context = local_only_lifespan
