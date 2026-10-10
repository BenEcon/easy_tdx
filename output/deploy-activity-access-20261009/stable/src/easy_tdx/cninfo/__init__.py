"""巨潮资讯网（cninfo）公告检索 —— 独立于 TDX 协议的 HTTP 数据源。

零额外依赖（标准库 urllib），无需连接 TDX 服务器即可使用。

用法::

    from easy_tdx.cninfo import CninfoClient

    df = CninfoClient().get_announcements("688017", count=30)
    # → DataFrame[title, type, date, url]
"""

from __future__ import annotations

from .client import CninfoClient
from .models import Announcement, CninfoError

__all__ = ["CninfoClient", "Announcement", "CninfoError"]
