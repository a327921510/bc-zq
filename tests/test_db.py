"""SQLite 入库行为单测：使用临时库，不碰正式 data/archive.db。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.src import db as dbmod


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "test.db"
    monkeypatch.setattr(dbmod.settings, "db_path", path)
    monkeypatch.setattr(dbmod.settings, "data_dir", tmp_path)
    monkeypatch.setattr(dbmod.settings, "backup_dir", tmp_path / "backups")
    dbmod.init_db(path)
    return path


def test_init_has_byd(tmp_db: Path) -> None:
    symbols = dbmod.list_symbols()
    assert any(s["code"] == "002594" for s in symbols)


def test_replace_day_data_idempotent(tmp_db: Path) -> None:
    ticks = [
        {
            "seq": 0,
            "time": "09:30:00",
            "price": 10.0,
            "volume": 1,
            "amount": 1000,
            "side": "B",
        }
    ]
    minutes = [{"minute": "09:30", "price": 10.0, "volume": 1, "amount": 1000}]
    summary = {
        "pre_close": 9.9,
        "open": 10.0,
        "high": 10.0,
        "low": 10.0,
        "close": 10.0,
        "volume": 1,
        "amount": 1000,
    }
    dbmod.replace_day_data(
        code="002594",
        trade_date="2026-07-21",
        summary=summary,
        ticks=ticks,
        minutes=minutes,
        status="ok",
        message="first",
    )
    # 第二次覆盖不应翻倍
    dbmod.replace_day_data(
        code="002594",
        trade_date="2026-07-21",
        summary=summary,
        ticks=ticks + [{**ticks[0], "seq": 1, "time": "09:30:03"}],
        minutes=minutes,
        status="ok",
        message="second",
    )
    assert len(dbmod.get_ticks("002594", "2026-07-21")) == 2
    assert dbmod.get_price_volume("002594", "2026-07-21") == [
        {"price": 10.0, "volume": 2}
    ]
    assert dbmod.list_trade_dates("002594") == ["2026-07-21"]


def test_upsert_and_delete_symbol(tmp_db: Path) -> None:
    row = dbmod.upsert_symbol("600519", "贵州茅台", "SH")
    assert row["code"] == "600519"
    assert row["market"] == "SH"
    assert dbmod.infer_market("000001") == "SZ"

    dbmod.replace_day_data(
        code="600519",
        trade_date="2026-07-21",
        summary={"close": 1.0},
        ticks=[],
        minutes=[{"minute": "09:30", "price": 1.0, "volume": 1, "amount": 1}],
        status="ok",
    )
    assert dbmod.list_sync_logs(code="600519")
    assert dbmod.delete_symbol("600519", purge_data=False)
    assert dbmod.get_symbol("600519") is None
    # 仅删关注时行情仍在
    assert dbmod.get_minutes("600519", "2026-07-21")

    dbmod.upsert_symbol("600519", "贵州茅台", "SH")
    assert dbmod.delete_symbol("600519", purge_data=True)
    assert dbmod.get_minutes("600519", "2026-07-21") == []
    assert dbmod.list_sync_logs(code="600519") == []


def test_set_symbol_enabled(tmp_db: Path) -> None:
    dbmod.set_symbol_enabled("002594", False)
    assert dbmod.get_symbol("002594")["enabled"] == 0
    assert all(s["code"] != "002594" for s in dbmod.list_symbols(enabled_only=True))


def test_upsert_margin_idempotent(tmp_db: Path) -> None:
    rows = [
        {
            "code": "002594",
            "trade_date": "2026-09-02",
            "rzye": 1e10,
            "rzmre": 1e8,
            "rzche": 2e8,
            "rzjme": -1e8,
            "rqye": 4e7,
            "rqyl": 470000,
            "rqmcl": 38000,
            "rqchl": 9000,
            "rzrqye": 1.01e10,
            "rzyezb": 4.2,
        }
    ]
    assert dbmod.upsert_margin_rows(rows) == 1
    assert dbmod.upsert_margin_rows([{**rows[0], "rzye": 2e10}]) == 1
    got = dbmod.get_margin("002594", "2026-09-02")
    assert got is not None
    assert got["rzye"] == 2e10
    assert got["rzjme"] == -1e8
    assert dbmod.list_margin("002594", limit=5)[0]["trade_date"] == "2026-09-02"


def test_purge_symbol_clears_margin(tmp_db: Path) -> None:
    dbmod.upsert_margin_rows(
        [{"code": "002594", "trade_date": "2026-09-02", "rzye": 1.0}]
    )
    assert dbmod.get_margin("002594", "2026-09-02")
    dbmod.delete_symbol("002594", purge_data=True)
    assert dbmod.get_margin("002594", "2026-09-02") is None
