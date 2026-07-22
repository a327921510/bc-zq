"""同步频控单测。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backend.src import db as dbmod
from backend.src import sync_guard
from backend.src.config import settings


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "test.db"
    monkeypatch.setattr(dbmod.settings, "db_path", path)
    monkeypatch.setattr(dbmod.settings, "data_dir", tmp_path)
    monkeypatch.setattr(dbmod.settings, "backup_dir", tmp_path / "backups")
    monkeypatch.setattr(settings, "sync_cooldown_seconds", 60)
    monkeypatch.setattr(settings, "sync_ok_reuse_seconds", 300)
    dbmod.init_db(path)
    return path


def _write_log(status: str, seconds_ago: int) -> None:
    ts = (datetime.now() - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%d %H:%M:%S")
    with dbmod.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO sync_log(code, trade_date, status, tick_count, minute_count, message, synced_at)
            VALUES ('002594', '2026-07-21', ?, 1, 1, 't', ?)
            ON CONFLICT(code, trade_date) DO UPDATE SET
              status=excluded.status, synced_at=excluded.synced_at
            """,
            (status, ts),
        )


def test_recent_ok_requires_force(tmp_db: Path) -> None:
    _write_log("ok", 30)
    g = sync_guard.evaluate_sync("002594", force=False)
    assert g["allowed"] is False
    assert g["force_required"] is True
    assert g["reason"] == "recent_ok"
    assert sync_guard.evaluate_sync("002594", force=True)["allowed"] is True


def test_cooldown_after_fail(tmp_db: Path) -> None:
    _write_log("fail", 10)
    g = sync_guard.evaluate_sync("002594", force=False)
    assert g["allowed"] is False
    assert g["reason"] == "cooldown"


def test_allowed_when_old_enough(tmp_db: Path) -> None:
    _write_log("ok", 1000)
    assert sync_guard.evaluate_sync("002594", force=False)["allowed"] is True
