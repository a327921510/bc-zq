"""schema 迁移与备份。"""

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
    return path


def test_migrate_stamps_version_and_keeps_data(tmp_db: Path) -> None:
    dbmod.init_db(tmp_db)
    assert dbmod.get_schema_version(tmp_db) == dbmod.TARGET_SCHEMA_VERSION
    dbmod.replace_day_data(
        code="002594",
        trade_date="2026-07-21",
        summary={"close": 1.0},
        ticks=[],
        minutes=[{"minute": "09:30", "price": 1.0, "volume": 1, "amount": 1}],
        status="ok",
    )
    # 再次 migrate 幂等，且不丢数据
    assert dbmod.migrate(tmp_db) == dbmod.TARGET_SCHEMA_VERSION
    assert dbmod.get_minutes("002594", "2026-07-21")


def test_legacy_db_without_meta_gets_version(tmp_db: Path) -> None:
    # 模拟旧库：只有业务表、无 schema_meta
    conn = dbmod.connect(tmp_db)
    conn.executescript(
        """
        CREATE TABLE symbols (
          code TEXT PRIMARY KEY, name TEXT NOT NULL, market TEXT NOT NULL, enabled INTEGER
        );
        INSERT INTO symbols VALUES ('002594', '比亚迪', 'SZ', 1);
        """
    )
    conn.commit()
    conn.close()
    assert dbmod.get_schema_version(tmp_db) == 0
    assert dbmod.migrate(tmp_db) == dbmod.TARGET_SCHEMA_VERSION
    assert dbmod.get_symbol("002594")["name"] == "比亚迪"


def test_migrate_v2_adds_margin_table(tmp_db: Path) -> None:
    """已有 v1 库升级到 v2 应建 margin_daily，且不丢行情。"""
    dbmod.init_db(tmp_db)
    # 模拟卡在 v1：先把版本戳回退（表已齐全）
    with dbmod.get_conn(tmp_db) as conn:
        conn.execute(
            "UPDATE schema_meta SET version = 1, updated_at = ?",
            ("2026-01-01 00:00:00",),
        )
        conn.execute("DROP TABLE IF EXISTS margin_daily")
    assert dbmod.get_schema_version(tmp_db) == 1
    assert dbmod.migrate(tmp_db) == 2
    dbmod.upsert_margin_rows(
        [{"code": "002594", "trade_date": "2026-09-02", "rzye": 1.0}]
    )
    assert dbmod.get_margin("002594", "2026-09-02")["rzye"] == 1.0

    dbmod.init_db(tmp_db)
    p1 = dbmod.backup_db(tag="pre_deploy")
    p2 = dbmod.backup_db(tag="pre_deploy")
    assert p1 is not None and p2 is not None
    assert p1.exists() and p2.exists()
    assert p1.name != p2.name
    daily = dbmod.backup_db(tag=None)
    assert daily is not None and daily.name.startswith("archive_") and "pre_deploy" not in daily.name
