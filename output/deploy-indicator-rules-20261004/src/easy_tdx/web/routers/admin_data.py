"""管理员数据中心：集中展示连接、离线数据和研究能力状态。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request

from easy_tdx.web.account_store import UserRecord
from easy_tdx.web.routers.auth import require_admin

router = APIRouter(tags=["admin-data"])


@router.get("/admin/data/status")
async def data_status(
    request: Request,
    _: UserRecord = Depends(require_admin),
) -> dict[str, Any]:
    """返回运行时数据连接、离线 vipdoc 与持久化目录状态。"""
    from easy_tdx.factor import list_factors
    from easy_tdx.offline.paths import detect_tdx_home

    tdx_home = detect_tdx_home()
    vipdoc = tdx_home / "vipdoc" if tdx_home else None
    vipdoc_ready = bool(vipdoc and vipdoc.is_dir())
    sh_files = len(list((vipdoc / "sh" / "lday").glob("*.day"))) if vipdoc_ready else 0
    sz_files = len(list((vipdoc / "sz" / "lday").glob("*.day"))) if vipdoc_ready else 0
    config_dir = Path(os.environ.get("EASY_TDX_CONFIG_DIR", str(Path.home() / ".easy_tdx")))

    capabilities = [
        {
            "name": "标准行情",
            "key": "tdx",
            "ready": request.app.state.tdx_client is not None,
            "detail": "K线、分时、逐笔与证券目录",
        },
        {
            "name": "高级行情",
            "key": "mac",
            "ready": request.app.state.mac_client is not None,
            "detail": "板块、资金流、竞价与市场排行",
        },
        {
            "name": "扩展市场",
            "key": "ex",
            "ready": request.app.state.ex_client is not None,
            "detail": "港股、期货与外盘（7727）",
        },
        {
            "name": "本地离线库",
            "key": "offline",
            "ready": vipdoc_ready,
            "detail": (
                f"沪市 {sh_files} / 深市 {sz_files} 个日线文件"
                if vipdoc_ready
                else "设置 TDX_HOME 并挂载 vipdoc 后启用"
            ),
        },
        {
            "name": "市场强度扫描",
            "key": "strength",
            "ready": vipdoc_ready,
            "detail": "依赖本地日线库",
        },
        {
            "name": "量化因子",
            "key": "factors",
            "ready": True,
            "detail": f"已注册 {len(list_factors())} 个内置因子",
        },
        {
            "name": "账户持久化",
            "key": "accounts",
            "ready": config_dir.is_dir(),
            "detail": str(config_dir),
        },
    ]
    return {
        "capabilities": capabilities,
        "tdx_home": str(tdx_home) if tdx_home else None,
        "vipdoc": str(vipdoc) if vipdoc_ready else None,
        "offline": {"ready": vipdoc_ready, "sh_daily_files": sh_files, "sz_daily_files": sz_files},
        "config_dir": str(config_dir),
    }
