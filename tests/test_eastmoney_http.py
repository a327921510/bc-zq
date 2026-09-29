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
    monkeypatch.setattr(em, "_sticky_host", None)
    monkeypatch.setattr(em.time, "sleep", lambda _s: None)
    monkeypatch.setattr(em.random, "uniform", lambda _a, _b: 0.0)

    data = em._get_json(None, "/api/qt/stock/get", {"secid": "0.002594"})
    assert data["data"]["ok"] is True
    assert any("push2delay" in u for u in calls)
    assert any("push2.eastmoney.com" in u for u in calls)
    assert em._sticky_host == "push2.eastmoney.com"


def test_get_json_prefers_sticky_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """粘滞 host 应优先被请求。"""
    calls: list[str] = []

    def fake_request(
        url: str,
        params: dict[str, Any],
        *,
        client: Any = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        calls.append(url.split("/")[2])
        return {"data": {"ok": True}}

    monkeypatch.setattr(em, "_request_json", fake_request)
    monkeypatch.setattr(em, "_sticky_host", "82.push2.eastmoney.com")
    monkeypatch.setattr(em, "_PER_HOST_ATTEMPTS", 1)

    em._get_json(None, "/api/qt/stock/get", {"secid": "0.002594"})
    assert calls[0] == "82.push2.eastmoney.com"


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


def test_request_json_does_not_fallback_httpx_after_cffi_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cffi 已装且断连时，不再浪费一次必挂的 httpx。"""

    def cffi_fail(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise ConnectionError("curl: (56) Connection closed abruptly")

    def httpx_should_not_run(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise AssertionError("httpx fallback should be skipped")

    monkeypatch.setattr(em, "_get_via_curl_cffi", cffi_fail)
    monkeypatch.setattr(em, "_get_via_httpx", httpx_should_not_run)

    with pytest.raises(ConnectionError, match="curl: \\(56\\)"):
        em._request_json(
            "https://push2delay.eastmoney.com/api/qt/stock/get",
            {"secid": "0.002594"},
        )
