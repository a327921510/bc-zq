"""腾讯行情解析与双源编排单测：不访问外网。"""

from __future__ import annotations

from typing import Any

import pytest

from backend.src.fetch import day as day_mod
from backend.src.fetch import tencent as tx


def test_parse_tencent_minute_cumulative_delta() -> None:
    day, mins = tx.parse_tencent_minute_lines(
        [
            "0930 83.20 810 6739200.00",
            "0931 83.17 4329 36020440.75",
            "1200 83.00 5000 40000000.00",  # 午休丢弃
            "1300 82.50 4500 37000000.00",  # 累计回落也允许（差分 floor 0）
        ]
    )
    assert day is None
    assert [m["minute"] for m in mins] == ["09:30", "09:31", "13:00"]
    assert mins[0]["volume"] == 810
    assert mins[1]["volume"] == 4329 - 810
    assert mins[1]["amount"] == pytest.approx(36020440.75 - 6739200.00)


def test_parse_tencent_detail_and_side() -> None:
    ticks = tx.parse_tencent_detail_chunk(
        "0/09:30:03/83.18/0.00/418/3477042/B|1/09:30:06/83.16/-0.02/384/3191317/M"
    )
    assert len(ticks) == 2
    assert ticks[0]["side"] == "B"
    assert ticks[0]["volume"] == 418
    assert ticks[0]["amount"] == 3477042
    assert ticks[1]["side"] == "N"  # M → N


def test_parse_tencent_quote_fields() -> None:
    # 精简字段表：按下标填够 38 项
    fields = [""] * 38
    fields[1] = "比亚迪"
    fields[2] = "002594"
    fields[3] = "82.02"
    fields[4] = "83.35"
    fields[5] = "83.20"
    fields[30] = "20260929161500"
    fields[33] = "83.42"
    fields[34] = "81.70"
    fields[35] = "82.02/216056/1776358464"
    fields[36] = "216056"
    q = tx.parse_tencent_quote_fields(fields)
    assert q["name"] == "比亚迪"
    assert q["price"] == 82.02
    assert q["pre_close"] == 83.35
    assert q["amount"] == 1776358464
    assert tx._trade_date_from_qt_datetime(q["datetime"]) == "2026-09-29"


def test_fetch_day_falls_back_to_eastmoney(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise ConnectionError("curl 56")

    def em_ok(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {
            "code": "002594",
            "market": "SZ",
            "trade_date": "2026-09-29",
            "trends_date": "2026-09-29",
            "summary": {},
            "ticks": [{"seq": 0}],
            "minutes": [{"minute": "09:30"}],
            "raw_path": "/tmp/x.json",
            "name": "比亚迪",
            "errors": [],
            "source": "eastmoney",
        }

    monkeypatch.setattr(day_mod.tencent, "fetch_day", boom)
    monkeypatch.setattr(day_mod.eastmoney, "fetch_day", em_ok)
    out = day_mod.fetch_day("002594", "SZ")
    assert out["source"] == "eastmoney"
    assert out["errors"][0].startswith("tencent:")


def test_fetch_day_uses_tencent_when_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    def tx_ok(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {
            "code": "002594",
            "ticks": [{"seq": 1}],
            "minutes": [{"minute": "09:30"}],
            "errors": [],
            "source": "tencent",
        }

    def em_should_not(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise AssertionError("eastmoney should not run")

    monkeypatch.setattr(day_mod.tencent, "fetch_day", tx_ok)
    monkeypatch.setattr(day_mod.eastmoney, "fetch_day", em_should_not)
    out = day_mod.fetch_day("002594", "SZ")
    assert out["source"] == "tencent"
