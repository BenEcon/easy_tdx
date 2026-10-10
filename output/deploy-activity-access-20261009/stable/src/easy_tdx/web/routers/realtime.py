"""实时数据 WebSocket 路由。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import time
from typing import Any

from anyio import CancelScope
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from easy_tdx.web.realtime_limits import RealtimeLimits

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])
_SYMBOL = re.compile(r"^(SH|SZ|BJ)\d{6}$")


@router.websocket("/ws/realtime/{symbol}")
async def realtime_websocket(websocket: WebSocket, symbol: str) -> None:
    """WebSocket 实时行情订阅。

    连接后自动订阅指定标的的实时事件。
    symbol 格式: SZ000001, SH600000 等。

    客户端可发送 JSON 消息来控制订阅：
    - {"action": "subscribe", "symbol": "SZ000001"}
    - {"action": "unsubscribe", "symbol": "SZ000001"}

    服务端推送消息格式：
    - {"type": "tick", "market": "SZ", "code": "000001", "price": 10.5, ...}
    - {"type": "signal", "direction": "BUY", ...}
    """
    from easy_tdx.web.account_store import get_account_store
    from easy_tdx.web.routers.auth import SESSION_COOKIE

    store = get_account_store()
    token = websocket.cookies.get(SESSION_COOKIE, "")
    user = store.get_user_for_session(token)
    if user is None:
        await websocket.close(code=4401)
        return
    origin = websocket.headers.get("origin")
    scheme = "https" if websocket.url.scheme == "wss" else "http"
    allowed = {
        item.strip().rstrip("/")
        for item in os.environ.get("EASY_TDX_ALLOWED_ORIGINS", "").split(",")
        if item.strip()
    }
    allowed.add(f"{scheme}://{websocket.url.netloc}")
    if origin is not None and origin not in allowed:
        await websocket.close(code=4403)
        return
    if not _SYMBOL.fullmatch(symbol.upper()):
        await websocket.close(code=4400)
        return
    try:
        limits = RealtimeLimits(store.db_path)
        lease = limits.acquire(user.id)
    except sqlite3.Error:
        await websocket.close(code=1013, reason="实时服务忙，请稍后重试")
        return
    if lease is None:
        # Authenticated same-origin clients need a close frame, not opaque HTTP 403/1006.
        await websocket.accept()
        await websocket.close(code=4429, reason="实时连接数已达上限，请关闭其他订阅页面")
        return
    try:
        await _serve_realtime(websocket, symbol, store, token, limits, lease)
    finally:
        # Synchronous bounded cleanup also runs during task cancellation / failed accept.
        try:
            limits.release(lease)
        except sqlite3.Error:
            logger.warning("Realtime lease cleanup failed; lease will expire")


async def _serve_realtime(
    websocket: WebSocket,
    symbol: str,
    store: Any,
    token: str,
    limits: RealtimeLimits,
    lease: str,
) -> None:
    await websocket.accept()
    logger.info("WebSocket client connected for symbol: %s", symbol)

    # Try to get EventBus from app state
    event_bus = getattr(websocket.app.state, "event_bus", None)

    subscribed_symbols: set[str] = {symbol.upper()}

    async def _heartbeat() -> None:
        while True:
            await asyncio.sleep(limits.HEARTBEAT_SECONDS)
            try:
                valid = limits.renew(lease)
            except sqlite3.Error:
                valid = False
            if not valid or store.get_user_for_session(token) is None:
                await websocket.close(code=4401 if valid else 1013)
                return

    async def _push_snapshots() -> None:
        """事件总线未配置时，直接轮询共享行情客户端近似实时推送。"""
        if store.get_user_for_session(token) is None or not limits.renew(lease):
            await websocket.close(code=4401)
            raise WebSocketDisconnect(code=4401)
        client = getattr(websocket.app.state, "tdx_client", None)
        if client is None or not subscribed_symbols:
            return
        from easy_tdx.web.convert import market_from_str

        pairs: list[tuple[Any, str]] = []
        symbols: list[str] = []
        for subscribed in sorted(subscribed_symbols):
            market_name, code = subscribed[:2], subscribed[2:]
            if market_name not in {"SZ", "SH", "BJ"} or len(code) != 6:
                continue
            pairs.append((market_from_str(market_name), code))
            symbols.append(subscribed)
        if not pairs:
            return
        df = await asyncio.wait_for(client.get_security_quotes(pairs), timeout=5)
        records = df.to_dict(orient="records") if hasattr(df, "to_dict") else []
        if store.get_user_for_session(token) is None or not limits.renew(lease):
            await websocket.close(code=4401)
            raise WebSocketDisconnect(code=4401)
        for index, row in enumerate(records):
            clean: dict[str, Any] = {}
            for key, value in row.items():
                if hasattr(value, "item"):
                    value = value.item()
                elif hasattr(value, "isoformat"):
                    value = value.isoformat()
                clean[str(key)] = value
            subscribed = symbols[index] if index < len(symbols) else symbol.upper()
            await asyncio.wait_for(
                websocket.send_json(
                    {
                        "type": "tick",
                        "market": subscribed[:2],
                        "code": subscribed[2:],
                        "price": clean.get("price", clean.get("close", 0)),
                        "volume": clean.get("vol", clean.get("volume", 0)),
                        "timestamp": time.time(),
                        "data": clean,
                    }
                ),
                timeout=5,
            )

    async def _on_event(event: Any) -> None:
        """EventBus 回调 → 推送 WebSocket 消息。"""
        event_symbol = f"{event.market}{event.code}"
        if event_symbol in subscribed_symbols:
            try:
                if store.get_user_for_session(token) is None or not limits.renew(lease):
                    return
                msg = {
                    "type": event.event_type.value,
                    "market": event.market,
                    "code": event.code,
                    "price": event.price,
                    "volume": event.volume,
                    "timestamp": event.timestamp,
                    "data": event.data,
                }
                await asyncio.wait_for(websocket.send_json(msg), timeout=5)
            except Exception:
                logger.warning("Failed to send WebSocket message")

    # Subscribe to event bus if available
    heartbeat = asyncio.create_task(_heartbeat())
    try:
        if event_bus is not None:
            event_bus.subscribe_all(_on_event)
        while True:
            if store.get_user_for_session(token) is None:
                await websocket.close(code=4401)
                break
            # Receive client messages (subscribe/unsubscribe control)
            try:
                message = await asyncio.wait_for(
                    websocket.receive(), timeout=30.0 if event_bus is not None else 3.0
                )
                if message["type"] == "websocket.disconnect":
                    break
                if store.get_user_for_session(token) is None:
                    await websocket.close(code=4401)
                    break
                if not limits.consume(lease):
                    await websocket.close(code=4429, reason="订阅操作过于频繁，请稍后重试")
                    break
                raw = message.get("text")
                if raw is None:
                    await websocket.close(code=1003, reason="仅支持文本订阅消息")
                    break
                if len(raw.encode("utf-8")) > 4096:
                    await websocket.close(code=1009)
                    break
                data = json.loads(raw)
                if not isinstance(data, dict):
                    await websocket.send_json({"type": "error", "msg": "订阅消息必须为对象"})
                    continue
                action = data.get("action", "")

                if action == "subscribe":
                    value = data.get("symbol", "")
                    new_symbol = value.upper() if isinstance(value, str) else ""
                    if not _SYMBOL.fullmatch(new_symbol):
                        await websocket.send_json({"type": "error", "msg": "无效证券代码"})
                        continue
                    if new_symbol not in subscribed_symbols and len(subscribed_symbols) >= 32:
                        await websocket.send_json({"type": "error", "msg": "最多订阅 32 个标的"})
                        continue
                    if new_symbol:
                        subscribed_symbols.add(new_symbol)
                        await websocket.send_json(
                            {"type": "status", "msg": f"subscribed {new_symbol}"}
                        )

                elif action == "unsubscribe":
                    value = data.get("symbol", "")
                    old_symbol = value.upper() if isinstance(value, str) else ""
                    subscribed_symbols.discard(old_symbol)
                    await websocket.send_json(
                        {"type": "status", "msg": f"unsubscribed {old_symbol}"}
                    )

            except asyncio.TimeoutError:
                try:
                    if event_bus is None:
                        await _push_snapshots()
                    else:
                        await websocket.send_json({"type": "ping"})
                except Exception:
                    logger.warning("Realtime snapshot polling failed for %s", symbol, exc_info=True)
                    break
            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "msg": "invalid JSON"})

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected: %s", symbol)
    except asyncio.CancelledError:
        # ASGI shutdown/disconnect cancellation still must remove the event listener and lease.
        pass
    except Exception:
        logger.exception("WebSocket error for %s", symbol)
    finally:
        heartbeat.cancel()
        try:
            with CancelScope(shield=True):
                await asyncio.gather(heartbeat, return_exceptions=True)
                if (
                    websocket.application_state == WebSocketState.CONNECTED
                    and websocket.client_state == WebSocketState.CONNECTED
                ):
                    try:
                        await asyncio.wait_for(websocket.close(code=1013), timeout=2)
                    except (RuntimeError, OSError, asyncio.TimeoutError):
                        pass
        finally:
            if event_bus is not None:
                event_bus.unsubscribe_all(_on_event)
        logger.info("WebSocket connection closed: %s", symbol)
