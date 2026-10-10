"""Bound request bodies and reject cross-origin cookie-authenticated writes."""

import asyncio
from collections.abc import Callable

from fastapi import HTTPException
from starlette.datastructures import URL, Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestSecurityMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        allowed_origins: list[str],
        max_body: int = 8 * 1024 * 1024,
        archive_uploads: bool = False,
    ) -> None:
        self.app = app
        self.allowed_origins = set(allowed_origins)
        self.max_body = max_body
        self.archive_uploads = archive_uploads

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        from easy_tdx.web.archive_ingress import request_upload_context
        from easy_tdx.web.resource_admission import request_admission_context

        # HTTP/1.1 pipelining may spawn this task inside the preceding response's
        # context, before its upload guard exits. Start with independent handles;
        # do not silently ignore expired leases inside actual work or free the
        # prior request's leases here.
        with request_admission_context(), request_upload_context():
            await self._handle_api_request(scope, receive, send)

    async def _handle_api_request(self, scope: Scope, receive: Receive, send: Send) -> None:
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
        from easy_tdx.web.archive_ingress import (
            ARCHIVE_BODY_LIMIT,
            ARCHIVE_BODY_TIMEOUT,
            archive_upload_guard,
            is_archive_upload,
        )

        upload = self.archive_uploads and is_archive_upload(scope)
        if upload:
            limit = ARCHIVE_BODY_LIMIT
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
        if upload:
            try:
                async with archive_upload_guard(scope) as admission:
                    await self._buffer_and_dispatch(
                        scope,
                        receive,
                        send,
                        limit,
                        timeout=ARCHIVE_BODY_TIMEOUT,
                        check=admission.check,
                    )
            except HTTPException as exc:
                await JSONResponse(
                    {"detail": exc.detail},
                    exc.status_code,
                    headers={"Cache-Control": "no-store", **(exc.headers or {})},
                )(scope, receive, send)
        else:
            await self._buffer_and_dispatch(scope, receive, send, limit)

    async def _buffer_and_dispatch(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        limit: int,
        *,
        timeout: float | None = None,
        check: Callable[[], None] | None = None,
    ) -> None:
        body = bytearray()
        deadline = asyncio.get_running_loop().time() + timeout if timeout is not None else None
        while True:
            try:
                message = (
                    await asyncio.wait_for(receive(), deadline - asyncio.get_running_loop().time())
                    if deadline is not None
                    else await receive()
                )
            except asyncio.TimeoutError:
                await JSONResponse({"detail": "存档上传超时，请重试"}, 408)(scope, receive, send)
                return
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
                await JSONResponse({"detail": "请求内容过大"}, 413)(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def bounded_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        if check is not None:
            check()
        await self.app(scope, bounded_receive, send)
