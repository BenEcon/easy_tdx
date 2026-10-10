"""服务器设置路由：列出/测速/切换标准 TDX 行情服务器。

让用户在 web UI 上看到候选 host 列表、一键测速、点选切换——解决"有些 IP
能连通有些不能"的问题（不同地区/运营商对通达信各服务器连通性不同）。
切换是热重连（``reconnect_to``），无需重启服务。
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from easy_tdx.config import get_best_host, get_known_hosts, get_port, save_best_host
from easy_tdx.transport.sync import ping_all
from easy_tdx.web.account_store import UserRecord, get_account_store
from easy_tdx.web.routers.auth import get_current_user, require_admin

router = APIRouter(tags=["server"])


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #


class HostInfo(BaseModel):
    """单个 host 的状态信息。"""

    host: str
    latency_ms: int | None = None  # None = 未测速或不可达
    reachable: bool = False
    is_current: bool = False


class HostListResponse(BaseModel):
    """GET /server/hosts 的响应。"""

    hosts: list[HostInfo]
    current_host: str
    total: int


class ServerTestRequest(BaseModel):
    """POST /server/test 的请求。"""

    hosts: list[str] | None = Field(default=None, min_length=1, max_length=128)
    timeout: float = Field(default=5.0, ge=0.1, le=10.0, allow_inf_nan=False)


class ServerSwitchRequest(BaseModel):
    """POST /server/switch 的请求。"""

    host: str = Field(min_length=1, max_length=253)


class SwitchResponse(BaseModel):
    """POST /server/switch 的响应。"""

    ok: bool
    host: str
    message: str


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.get(
    "/server/hosts", response_model=HostListResponse, dependencies=[Depends(get_current_user)]
)
async def list_hosts(request: Request) -> HostListResponse:
    """列出所有候选 host + 当前正在使用的 host。

    不做测速（避免 50+ host 全 ping 让首屏卡几秒）。前端点"测试全部"按钮
    后调 ``POST /server/test`` 获取延迟。
    """
    candidates = get_known_hosts()
    current = _get_current_host(request)

    host_infos = [HostInfo(host=h, is_current=(h == current)) for h in candidates]
    return HostListResponse(hosts=host_infos, current_host=current, total=len(host_infos))


@router.post("/server/test", response_model=list[HostInfo], dependencies=[Depends(require_admin)])
async def test_hosts(
    req: ServerTestRequest, request: Request, admin: UserRecord = Depends(require_admin)
) -> list[HostInfo]:
    """并发 ping 测试 host 列表，返回延迟和可达性。

    用 ``asyncio.to_thread`` 包装同步的 ``ping_all``（它内部用
    ThreadPoolExecutor 并发），避免阻塞事件循环。
    """
    candidates = get_known_hosts()
    hosts = list(dict.fromkeys(req.hosts if req.hosts is not None else candidates))
    if len(hosts) > 128 or any(host not in candidates for host in hosts):
        raise HTTPException(422, "只允许测试配置中的行情节点，单次最多 128 个")
    port = get_port()
    current = _get_current_host(request)

    # ping_all 是同步阻塞函数，放到线程池跑
    active = getattr(request.app.state, "server_probe_task", None)
    if active is not None and not active.done():
        raise HTTPException(429, "已有节点测速在执行，请稍后重试", headers={"Retry-After": "10"})

    async def probe_and_audit() -> Any:
        try:
            ranked = await asyncio.to_thread(ping_all, hosts, port, req.timeout)
        except Exception:
            get_account_store().audit_operation(
                "server_test", admin.id, outcome="failed", details={"node_count": len(hosts)}
            )
            raise
        get_account_store().audit_operation(
            "server_test",
            admin.id,
            details={
                "node_count": len(hosts),
                "reachable_count": len(ranked),
            },
        )
        return ranked

    probe = asyncio.create_task(probe_and_audit())
    probe.add_done_callback(_consume_result)
    request.app.state.server_probe_task = probe
    # A disconnected HTTP client must not release the concurrency slot while
    # its actual socket probes are still running in the worker thread.
    ranked = await asyncio.shield(probe)

    # ranked 是 [(host, latency_sec)]，已按延迟升序排列，只含可达的
    reachable_map = {h: round(s * 1000) for h, s in ranked}

    # 按原始 hosts 顺序返回（保持列表稳定），但把可达的排前面
    result = []
    for h in hosts:
        latency_ms = reachable_map.get(h)
        result.append(
            HostInfo(
                host=h,
                latency_ms=latency_ms,
                reachable=latency_ms is not None,
                is_current=(h == current),
            )
        )

    # 可达的排前面（按延迟升序），不可达的排后面
    result.sort(key=lambda x: (x.reachable is False, x.latency_ms or 999999))
    return result


@router.post("/server/switch", response_model=SwitchResponse, dependencies=[Depends(require_admin)])
async def switch_host(
    req: ServerSwitchRequest, request: Request, admin: UserRecord = Depends(require_admin)
) -> SwitchResponse:
    """切换到指定 host（热重连，无需重启服务）。

    顺序：先 reconnect_to 成功 → 再 save_best_host 持久化。
    如果 reconnect 失败，不 save（避免污染 config，用户可再选别的）。
    """
    candidates = get_known_hosts()
    if req.host not in candidates:
        return SwitchResponse(
            ok=False,
            host=req.host,
            message=f"主机 {req.host} 不在候选列表里，无法切换",
        )

    client = request.app.state.tdx_client
    if client is None:
        return SwitchResponse(ok=False, host=req.host, message="TDX 客户端未初始化")

    active = getattr(request.app.state, "server_switch_task", None)
    if active is not None and not active.done():
        raise HTTPException(429, "已有节点切换在执行", headers={"Retry-After": "5"})
    previous = _get_current_host(request)

    async def switch_and_audit() -> SwitchResponse:
        try:
            await client.reconnect_to(req.host)
            # Do not persist a target until reconnect succeeds.
            save_best_host(req.host)
        except Exception:
            get_account_store().audit_operation(
                "server_switch",
                admin.id,
                outcome="failed",
                details={
                    "node_before": previous,
                    "node_after": req.host,
                },
            )
            return SwitchResponse(ok=False, host=req.host, message="节点切换失败，请刷新状态后重试")
        get_account_store().audit_operation(
            "server_switch",
            admin.id,
            details={
                "node_before": previous,
                "node_after": req.host,
            },
        )
        return SwitchResponse(ok=True, host=req.host, message=f"已切换到 {req.host}")

    task = asyncio.create_task(switch_and_audit())
    task.add_done_callback(_consume_result)
    request.app.state.server_switch_task = task
    return await asyncio.shield(task)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _consume_result(task: asyncio.Task[Any]) -> None:
    """Retrieve detached errors when the HTTP caller has already disconnected."""
    if not task.cancelled():
        task.exception()


def _get_current_host(request: Request) -> str:
    """获取当前 TDX 客户端实际连接的 host。"""
    client = getattr(request.app.state, "tdx_client", None)
    if client is not None:
        # AsyncTdxClient._host 是实际连接的 host（reconnect_to 会更新它）
        return getattr(client, "_host", get_best_host())
    return get_best_host()
