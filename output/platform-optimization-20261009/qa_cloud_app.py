"""Local cloud archive UI acceptance, temporary DB and explicit QA identities."""
import sys
from pathlib import Path

import qa_tracking_app as qa
from easy_tdx.web.request_security import RequestSecurityMiddleware
from easy_tdx.web.routers.auth import get_current_user

sys.path.insert(0, str(Path(__file__).parent / "cloud-snapshot-stage"))
from research_archive import ResearchArchive
from research_archive_router import build_router

app = qa.app
archives = ResearchArchive(Path(qa.CONFIG.name) / "research-archives.db")

def identity():
    return qa.store.get_user(qa.owner)

app.dependency_overrides[get_current_user] = identity
cloud = build_router(lambda: archives, get_current_user)
prior = list(app.router.routes)
app.router.routes = []
app.include_router(cloud, prefix="/api/v1")
app.router.routes += prior
app.add_middleware(RequestSecurityMiddleware, allowed_origins=[], max_body=26 * 1024 * 1024)
