"""Explicit administrator lookup of recorded public IPs over a fixed HTTPS endpoint."""

from __future__ import annotations

import ipaddress
import json
from typing import Any

import httpx


def local_location(ip: str) -> dict[str, Any] | None:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return {"state": "unavailable", "label": "未取得有效 IP"}
    if not address.is_global:
        return {"state": "local", "label": "本地／内网／保留地址，不查询外部归属地"}
    return None


def lookup_location(ip: str) -> dict[str, Any]:
    local = local_location(ip)
    if local:
        return local
    try:
        # No URL chosen by the caller, no redirects, no credentials or usernames.
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
            with client.stream(
                "GET",
                f"https://ipwho.is/{ip}",
                params={"lang": "zh-CN", "fields": "ip,success,country,region,city,connection.isp"},
            ) as response:
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 16_384:
                        raise ValueError("oversized provider response")
                data = json.loads(raw)
        if (
            not isinstance(data, dict)
            or data.get("success") is not True
            or ipaddress.ip_address(data.get("ip", "")) != ipaddress.ip_address(ip)
        ):
            raise ValueError("unusable provider response")
        values = [data.get(key) for key in ("country", "region", "city")]
        parts = list(
            dict.fromkeys(
                value.strip()[:120] for value in values if isinstance(value, str) and value.strip()
            )
        )
        connection = data.get("connection")
        isp = connection.get("isp") if isinstance(connection, dict) else None
        if not parts:
            raise ValueError("missing location")
        return {
            "state": "ok",
            "label": " · ".join(parts),
            "isp": isp[:160] if isinstance(isp, str) else "",
        }
    except (httpx.HTTPError, ValueError, TypeError):
        return {"state": "unavailable", "label": "归属地服务暂不可用，稍后重试"}
