"""聚合与解析单测：不访问外网。"""

from __future__ import annotations

from backend.src.aggregate import (
    map_side,
    minutes_from_ticks,
    parse_details,
    parse_trends,
    price_volume_from_ticks,
    trading_minutes,
)


def test_trading_minutes_count() -> None:
    # 09:30-11:30 与 13:00-15:00 含端点各 121 分钟 → 242
    assert len(trading_minutes()) == 242
    assert trading_minutes()[0] == "09:30"
    assert "11:30" in trading_minutes()
    assert "12:00" not in trading_minutes()
    assert trading_minutes()[-1] == "15:00"


def test_map_side() -> None:
    assert map_side(1) == "B"
    assert map_side(2) == "S"
    assert map_side(4) == "N"
    assert map_side("x") == "N"


def test_parse_details_amount_and_side() -> None:
    ticks = parse_details(["09:30:03,10.00,2,1,1", "09:30:06,9.50,3,1,2"])
    assert len(ticks) == 2
    assert ticks[0]["side"] == "B"
    assert ticks[0]["amount"] == 2000.0  # 10 * 2 手 * 100
    assert ticks[1]["side"] == "S"


def test_parse_trends_skips_lunch() -> None:
    lines = [
        "2026-07-21 09:30,10,10.1,10.2,9.9,100,1000,10.05",
        "2026-07-21 12:00,10,10,10,10,1,1,10",  # 休市应丢弃
        "2026-07-21 13:00,10,10.2,10.3,10,50,500,10.1",
    ]
    day, mins = parse_trends(lines)
    assert day == "2026-07-21"
    assert [m["minute"] for m in mins] == ["09:30", "13:00"]
    assert mins[0]["price"] == 10.1


def test_minutes_from_ticks_forward_fill() -> None:
    ticks = [
        {"time": "09:30:10", "price": 10.0, "volume": 1, "amount": 1000},
        {"time": "09:30:40", "price": 10.2, "volume": 2, "amount": 2040},
        {"time": "09:32:00", "price": 10.3, "volume": 1, "amount": 1030},
    ]
    mins = minutes_from_ticks(ticks)
    by_m = {m["minute"]: m for m in mins}
    assert by_m["09:30"]["price"] == 10.2
    assert by_m["09:30"]["volume"] == 3
    # 09:31 无成交：价沿用、量为 0
    assert by_m["09:31"]["price"] == 10.2
    assert by_m["09:31"]["volume"] == 0
    assert by_m["09:32"]["price"] == 10.3


def test_price_volume_from_ticks() -> None:
    ticks = [
        {"price": 10.0, "volume": 1},
        {"price": 10.0, "volume": 2},
        {"price": 9.5, "volume": 4},
    ]
    pv = price_volume_from_ticks(ticks)
    assert pv == [{"price": 9.5, "volume": 4}, {"price": 10.0, "volume": 3}]
