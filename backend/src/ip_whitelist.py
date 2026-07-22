"""
IP 白名单：解析与 Nginx 同款的 ops/allowed_ips.conf（allow / deny），
供 FastAPI 在未走 Nginx 或需应用层兜底时复用同一份名单。
"""

from __future__ import annotations

import ipaddress
import logging
import re
from pathlib import Path

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# 与 Nginx 片段对齐：allow 1.2.3.4; 或 allow 10.0.0.0/8;
_ALLOW_RE = re.compile(
    r"^\s*allow\s+(\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?)\s*;\s*(?:#.*)?$",
    re.IGNORECASE,
)
_DENY_ALL_RE = re.compile(r"^\s*deny\s+all\s*;\s*(?:#.*)?$", re.IGNORECASE)


def parse_allowed_networks(path: Path) -> list[ipaddress.IPv4Network]:
    """
    读取白名单文件，返回允许的网段列表。
    无文件或解析结果为空时返回空列表（启用中间件后即拒绝全部，避免误开）。
    """
    if not path.is_file():
        logger.warning("IP whitelist file missing: %s", path)
        return []

    networks: list[ipaddress.IPv4Network] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if _DENY_ALL_RE.match(line):
            continue
        m = _ALLOW_RE.match(line)
        if not m:
            continue
        try:
            networks.append(ipaddress.ip_network(m.group(1), strict=False))
        except ValueError:
            logger.warning("skip invalid allow entry: %s", line)
    return networks


def client_ip_allowed(ip_str: str, networks: list[ipaddress.IPv4Network]) -> bool:
    """判断单个 IPv4 是否落在任一 allow 网段内。"""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if not isinstance(addr, ipaddress.IPv4Address):
        return False
    return any(addr in net for net in networks)


def resolve_client_ip(request: Request) -> str:
    """
    取访客公网 IP。
    仅当直连来自本机（Nginx 反代）时才信任 X-Real-IP / X-Forwarded-For，
    避免公网直打伪造头绕过白名单。
    """
    peer = request.client.host if request.client else ""
    if peer in ("127.0.0.1", "::1"):
        xri = request.headers.get("x-real-ip")
        if xri:
            return xri.strip().split(",")[0].strip()
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return peer


class IpWhitelistMiddleware(BaseHTTPMiddleware):
    """
    应用层 IP 门禁：与 Nginx include 的 allowed_ips.conf 共用同一文件。
    生产仍应以 Nginx 白名单为主；本中间件为兜底（如误开 8000）。
    """

    def __init__(self, app: ASGIApp, whitelist_path: Path) -> None:
        super().__init__(app)
        self.whitelist_path = whitelist_path
        self._networks = parse_allowed_networks(whitelist_path)
        self._mtime: float | None = self._file_mtime()

    def _file_mtime(self) -> float | None:
        try:
            return self.whitelist_path.stat().st_mtime
        except OSError:
            return None

    def _reload_if_changed(self) -> None:
        # 宝塔改文件后无需重启 uvicorn：下次请求发现 mtime 变化即重载名单
        mtime = self._file_mtime()
        if mtime != self._mtime:
            self._networks = parse_allowed_networks(self.whitelist_path)
            self._mtime = mtime
            logger.info(
                "IP whitelist reloaded from %s (%d entries)",
                self.whitelist_path,
                len(self._networks),
            )

    async def dispatch(self, request: Request, call_next) -> Response:
        self._reload_if_changed()
        ip = resolve_client_ip(request)
        if not client_ip_allowed(ip, self._networks):
            return JSONResponse(
                status_code=403,
                content={"detail": "forbidden: ip not in whitelist"},
            )
        return await call_next(request)
