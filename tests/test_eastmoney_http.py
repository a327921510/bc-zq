"""东财 HTTP 回退逻辑单测：不访问外网。"""

from __future__ import annotations

from typing import Any

import pytest

from backend.src.fetch import eastmoney as em


def test_get_json_falls_back_across_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    """首 host 断连后应切到下一 host，并最终返回 JSON。"""
    calls: list[str] = []

    def fake_request(
        url: str,
        params: dict[str, Any],
        *,
        client: Any = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        calls.append(url)
        if "push2delay" in url:
            raise ConnectionError("Server disconnected without sending a response.")
        return {"data": {"ok": True}}

    monkeypatch.setattr(em, "_request_json", fake_request)
    monkeypatch.setattr(em, "_PER_HOST_ATTEMPTS", 1)
    # 跳过真实 sleep
    monkeypatch.setattr(em.time, "sleep", lambda _s: None)

    data = em._get_json(None, "/api/qt/stock/get", {"secid": "0.002594"})
    assert data["data"]["ok"] is True
    assert any("push2delay" in u for u in calls)
    assert any("push2.eastmoney.com" in u for u in calls)


def test_request_json_uses_httpx_when_cffi_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未装 curl_cffi 时走 httpx 回退。"""

    def boom(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise ImportError("no curl_cffi")

    class FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"rc": 0, "data": {"f58": "测试"}}

    class FakeClient:
        def get(self, url: str, params: Any = None, headers: Any = None) -> FakeResp:
            assert "eastmoney" in url
            return FakeResp()

        def close(self) -> None:
            return None

    monkeypatch.setattr(em, "_get_via_curl_cffi", boom)
    out = em._request_json(
        "https://push2delay.eastmoney.com/api/qt/stock/get",
        {"secid": "0.002594"},
        client=FakeClient(),  # type: ignore[arg-type]
    )
    assert out["data"]["f58"] == "测试"
