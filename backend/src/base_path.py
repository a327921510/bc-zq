"""
把对外 URL 前缀（如 /zq）从 ASGI path 上剥掉，路由仍按根路径编写。

同机多应用时 Nginx 反代 /zq/ → uvicorn，浏览器访问 /zq/...，
应用内部继续匹配 /api、/assets、SPA 路由。

注意：只改 path/raw_path，不要写 scope["root_path"]，否则 Starlette Mount
（StaticFiles）会匹配失败。
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


def normalize_base_path(raw: str | None) -> str:
    """返回带前导 /、无尾斜杠的前缀；空串表示挂在站点根。"""
    if raw is None:
        return ""
    p = raw.strip()
    if not p or p == "/":
        return ""
    if not p.startswith("/"):
        p = "/" + p
    return p.rstrip("/")


class BasePathMiddleware:
    """请求 path 以 base_path 开头时改写为去掉前缀后的路径。"""

    def __init__(self, app: ASGIApp, base_path: str) -> None:
        self.app = app
        self.base_path = normalize_base_path(base_path)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.base_path and scope["type"] in ("http", "websocket"):
            path = scope.get("path") or ""
            if path == self.base_path or path.startswith(self.base_path + "/"):
                scope = dict(scope)
                scope["path"] = path[len(self.base_path) :] or "/"
                # Mount/StaticFiles 同时看 raw_path（字节），必须一并剥离
                raw = scope.get("raw_path")
                if isinstance(raw, (bytes, bytearray)):
                    prefix = self.base_path.encode("ascii")
                    if raw.startswith(prefix):
                        scope["raw_path"] = bytes(raw[len(prefix) :] or b"/")
        await self.app(scope, receive, send)
