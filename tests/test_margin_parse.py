"""两融字段解析（不依赖外网）。"""

from __future__ import annotations

from backend.src.fetch.eastmoney import _parse_margin_row


def test_parse_margin_row_normalizes_fields() -> None:
    row = _parse_margin_row(
        {
            "DATE": "2026-09-02 00:00:00",
            "SCODE": "002594",
            "SECNAME": "比亚迪",
            "RZYE": 12869000029,
            "RZMRE": 210883230,
            "RZCHE": 346840105,
            "RZJME": -135956875,
            "RQYE": 41100060,
            "RQYL": 473503,
            "RQMCL": 38200,
            "RQCHL": 9200,
            "RZRQYE": 12910100089,
            "RZYEZB": 4.25171916,
        }
    )
    assert row["code"] == "002594"
    assert row["trade_date"] == "2026-09-02"
    assert row["name"] == "比亚迪"
    assert row["rzye"] == 12869000029
    assert row["rzjme"] == -135956875
    assert row["rzyezb"] == 4.25171916
