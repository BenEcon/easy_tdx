"""Bound request bodies and reject cross-origin cookie-authenticated writes."""

from starlette.datastructures import URL, Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestSecurityMiddleware:
    def __init__(
        self, app: ASGIApp, allowed_origins: list[str], max_body: int = 8 * 1024 * 1024
    ) -> None:
        self.app = app
        self.allowed_origins = set(allowed_origins)
        self.max_body = max_body

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            origin = headers.get("origin")
            url = URL(scope=scope)
            same_origin = f"{url.scheme}://{url.netloc}"
            # Missing Origin is accepted for non-browser clients; modern browsers
            # supply Origin or Sec-Fetch-Site. Never trust forwarded headers here.
            forbidden = (
                origin is not None and origin not in self.allowed_origins | {same_origin}
            ) or (origin is None and headers.get("sec-fetch-site") == "cross-site")
            if forbidden:
                await JSONResponse({"detail": "不允许来自此网页来源的操作"}, 403)(
                    scope, receive, send
                )
                return
        limit = (
            min(self.max_body, 8192) if scope["path"].startswith("/api/v1/auth/") else self.max_body
        )
        # Preferences intentionally has its existing 64 KB storage allowance.
        if scope["path"] == "/api/v1/auth/me/preferences":
            limit = 70 * 1024
        try:
            length = int(headers.get("content-length", "0"))
            if length < 0:
                raise ValueError
        except ValueError:
            await JSONResponse({"detail": "无效的请求长度"}, 400)(scope, receive, send)
            return
        if length > limit:
            await JSONResponse({"detail": "请求内容过大"}, 413)(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > limit:
                await JSONResponse({"detail": "请求内容过大"}, 413)(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        delivered = False

        async def bounded_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
