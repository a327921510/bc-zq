"""BASE_PATH 规范化与剥前缀中间件。"""

from __future__ import annotations

import asyncio

from backend.src.base_path import BasePathMiddleware, normalize_base_path


def test_normalize_base_path() -> None:
    assert normalize_base_path(None) == ""
    assert normalize_base_path("") == ""
    assert normalize_base_path("/") == ""
    assert normalize_base_path("zq") == "/zq"
    assert normalize_base_path("/zq/") == "/zq"
    assert normalize_base_path("/zq") == "/zq"


def test_base_path_middleware_strips_prefix() -> None:
    seen: dict[str, object] = {}

    async def inner(scope, _receive, _send):  # type: ignore[no-untyped-def]
        seen["path"] = scope["path"]
        seen["raw_path"] = scope.get("raw_path")

    app = BasePathMiddleware(inner, "/zq")

    async def hit(path: str, raw: bytes | None = None) -> None:
        scope = {
            "type": "http",
            "path": path,
            "raw_path": raw if raw is not None else path.encode(),
        }
        await app(scope, None, None)  # type: ignore[arg-type]

    asyncio.run(hit("/zq/api/health"))
    assert seen["path"] == "/api/health"
    assert seen["raw_path"] == b"/api/health"

    asyncio.run(hit("/zq"))
    assert seen["path"] == "/"

    asyncio.run(hit("/zq/"))
    assert seen["path"] == "/"
    assert seen["raw_path"] == b"/"
