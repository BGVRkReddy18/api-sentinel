"""SSRF protection: stop a public deployment from being used to probe internal networks.

Without this, anyone with write access could register http://169.254.169.254/ (cloud metadata),
http://localhost:5432 or 10.x addresses and use Sentinel to scan the host's private network.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeTargetError(ValueError):
    pass


async def ensure_public_target(url: str) -> None:
    host = urlsplit(url).hostname
    if not host:
        raise UnsafeTargetError("URL has no host")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeTargetError(f"cannot resolve host {host!r}") from exc
    for info in infos:
        address = ipaddress.ip_address(str(info[4][0]).split("%")[0])  # strip IPv6 zone id
        if not address.is_global:
            raise UnsafeTargetError(f"{host} resolves to non-public address {address}")
