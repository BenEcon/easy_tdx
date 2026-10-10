"""Validate explicitly trusted proxy addresses before starting the web server.

Only the transport layer may interpret forwarding headers. The application must
not independently trust X-Forwarded-For or CDN headers supplied by a client.
"""

from ipaddress import IPv4Network, IPv6Network, collapse_addresses, ip_address, ip_network


def validated_forwarded_allow_ips(value: str) -> str:
    """Canonical IP/CIDR list, or empty to disable trust; never accept all peers.

    Reject typos rather than letting Uvicorn interpret them as trusted literals.
    This TCP server does not listen on Unix sockets or resolve proxy hostnames.
    """
    if not value.strip():
        return ""
    if len(value) > 8192:
        raise ValueError("可信代理配置过长")
    entries = value.split(",")
    if len(entries) > 64:
        raise ValueError("可信代理最多配置 64 个 IP 或 CIDR")
    canonical: list[str] = []
    ipv4: list[IPv4Network] = []
    ipv6: list[IPv6Network] = []
    for raw in entries:
        item = raw.strip()
        if not item or item == "*" or "%" in item:
            raise ValueError("可信代理必须是明确的 IP 或 CIDR，不能使用通配符或空项")
        try:
            if "/" in item:
                network = ip_network(item, strict=True)
                if network.is_unspecified or network.is_multicast:
                    raise ValueError
                text = str(network)
            else:
                address = ip_address(item)
                if address.is_unspecified or address.is_multicast:
                    raise ValueError
                network = ip_network(address)
                text = str(address)
        except ValueError as exc:
            raise ValueError(f"无效的可信代理 IP 或 CIDR：{item}") from exc
        if network.prefixlen == 0:
            raise ValueError("不能信任所有来源，请只填写实际反向代理的 IP 或 CIDR")
        if isinstance(network, IPv4Network):
            ipv4.append(network)
        else:
            ipv6.append(network)
        if text not in canonical:
            canonical.append(text)
    # Also reject a split spelling of trust-all, e.g. two complementary /1s.
    if any(network.prefixlen == 0 for network in collapse_addresses(ipv4)) or any(
        network.prefixlen == 0 for network in collapse_addresses(ipv6)
    ):
        raise ValueError("可信代理范围合并后覆盖所有来源，请缩小范围")
    return ",".join(canonical)
