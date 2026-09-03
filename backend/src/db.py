"""SQLite 持久层：表结构、幂等写入与回放查询。

同步链路写库、API 读库都走这里；volume 单位统一为「手」。
"""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from .config import ensure_dirs, settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS symbols (
  code       TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  market     TEXT NOT NULL,
  enabled    INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS daily_summary (
  code         TEXT NOT NULL,
  trade_date   TEXT NOT NULL,
  pre_close    REAL,
  open         REAL,
  high         REAL,
  low          REAL,
  close        REAL,
  volume       REAL,
  amount       REAL,
  PRIMARY KEY (code, trade_date)
);

CREATE TABLE IF NOT EXISTS ticks (
  code         TEXT NOT NULL,
  trade_date   TEXT NOT NULL,
  seq          INTEGER NOT NULL,
  time         TEXT NOT NULL,
  price        REAL NOT NULL,
  volume       REAL NOT NULL,
  amount       REAL,
  side         TEXT,
  PRIMARY KEY (code, trade_date, seq)
);

CREATE TABLE IF NOT EXISTS minutes (
  code         TEXT NOT NULL,
  trade_date   TEXT NOT NULL,
  minute       TEXT NOT NULL,
  price        REAL NOT NULL,
  volume       REAL NOT NULL,
  amount       REAL,
  PRIMARY KEY (code, trade_date, minute)
);

CREATE TABLE IF NOT EXISTS sync_log (
  code         TEXT NOT NULL,
  trade_date   TEXT NOT NULL,
  status       TEXT NOT NULL,
  tick_count   INTEGER,
  minute_count INTEGER,
  message      TEXT,
  synced_at    TEXT NOT NULL,
  PRIMARY KEY (code, trade_date)
);

-- 单行元数据：记录已应用到的 schema 版本，禁止靠「删库重建」升级
CREATE TABLE IF NOT EXISTS schema_meta (
  id         INTEGER PRIMARY KEY CHECK (id = 1),
  version    INTEGER NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ticks_day ON ticks(code, trade_date);
CREATE INDEX IF NOT EXISTS idx_minutes_day ON minutes(code, trade_date);
"""

# 代码期望的库版本；新增迁移时递增，并在 MIGRATIONS 注册对应函数
TARGET_SCHEMA_VERSION = 2

# 首发关注股；init 时 upsert，不覆盖 enabled 以便用户手工停用
DEFAULT_SYMBOLS = [
    ("002594", "比亚迪", "SZ", 1),
]


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """打开 SQLite；WAL 便于 API 读与 sync 写并发。"""
    ensure_dirs()
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_conn(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """事务上下文：正常提交，异常回滚并关闭连接。"""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    """建表、跑迁移、确保默认 symbols 存在。启动 API / sync 均应调用。"""
    migrate(db_path)
    with get_conn(db_path) as conn:
        for code, name, market, enabled in DEFAULT_SYMBOLS:
            conn.execute(
                """
                INSERT INTO symbols(code, name, market, enabled)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                  name=excluded.name,
                  market=excluded.market
                """,
                (code, name, market, enabled),
            )


def _now_str() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def get_schema_version(db_path: Path | None = None) -> int:
    """当前库 schema 版本；无 meta 行视为 0（待迁移）。"""
    path = db_path or settings.db_path
    if not path.exists():
        return 0
    with get_conn(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              version INTEGER NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        row = conn.execute(
            "SELECT version FROM schema_meta WHERE id = 1"
        ).fetchone()
    return int(row["version"]) if row else 0


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        """
        INSERT INTO schema_meta(id, version, updated_at)
        VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          version=excluded.version,
          updated_at=excluded.updated_at
        """,
        (version, _now_str()),
    )


def _migrate_to_1(conn: sqlite3.Connection) -> None:
    """v1：基线表结构（CREATE IF NOT EXISTS）；已有库只打版本戳，不删数据。"""
    conn.executescript(SCHEMA)


def _migrate_to_2(conn: sqlite3.Connection) -> None:
    """v2：个股两融日表（东财 datacenter）；与分时归档按 (code, trade_date) 对齐。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS margin_daily (
          code         TEXT NOT NULL,
          trade_date   TEXT NOT NULL,
          rzye         REAL,
          rzmre        REAL,
          rzche        REAL,
          rzjme        REAL,
          rqye         REAL,
          rqyl         REAL,
          rqmcl        REAL,
          rqchl        REAL,
          rzrqye       REAL,
          rzyezb       REAL,
          synced_at    TEXT NOT NULL,
          PRIMARY KEY (code, trade_date)
        );
        CREATE INDEX IF NOT EXISTS idx_margin_day ON margin_daily(code, trade_date);
        """
    )


# version -> 迁移函数；只允许「向前」增量改表，禁止 DROP 整库
MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _migrate_to_1,
    2: _migrate_to_2,
}


def migrate(db_path: Path | None = None) -> int:
    """
    将库升级到 TARGET_SCHEMA_VERSION。
    已是最新则幂等；缺迁移函数则报错，避免静默跑飞。
    """
    ensure_dirs()
    with get_conn(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              version INTEGER NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        row = conn.execute(
            "SELECT version FROM schema_meta WHERE id = 1"
        ).fetchone()
        current = int(row["version"]) if row else 0

        if current > TARGET_SCHEMA_VERSION:
            raise RuntimeError(
                f"database schema_version={current} newer than code "
                f"TARGET_SCHEMA_VERSION={TARGET_SCHEMA_VERSION}; "
                "upgrade application first"
            )

        for version in range(current + 1, TARGET_SCHEMA_VERSION + 1):
            fn = MIGRATIONS.get(version)
            if fn is None:
                raise RuntimeError(f"missing migration for schema version {version}")
            fn(conn)
            _set_schema_version(conn, version)
            current = version

        # 空库且 TARGET=0 的极端情况；正常 TARGET>=1 时上面已写入 meta
        if current == 0:
            _set_schema_version(conn, TARGET_SCHEMA_VERSION)
            current = TARGET_SCHEMA_VERSION

    return current


def backup_db(*, tag: str | None = None) -> Path | None:
    """
    拷贝 SQLite 到 backups/db/。
    - 无 tag：按日覆盖名 archive_YYYYMMDD.db（每日 sync 用）
    - 有 tag：带时间戳 archive_{tag}_YYYYMMDD_HHMMSS.db（发版前不可互相覆盖）
    """
    ensure_dirs()
    db = Path(settings.db_path)
    if not db.exists():
        return None
    dest_dir = settings.backup_dir / "db"
    dest_dir.mkdir(parents=True, exist_ok=True)
    if tag:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in tag.strip()) or "bak"
        name = f"archive_{safe}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.db"
    else:
        name = f"archive_{datetime.now().strftime('%Y%m%d')}.db"
    dest = dest_dir / name
    # 先写临时文件再 replace，避免拷到一半进程被杀留下半截库
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    shutil.copy2(db, tmp)
    tmp.replace(dest)
    return dest


def list_symbols(enabled_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT code, name, market, enabled FROM symbols"
    if enabled_only:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY code"
    with get_conn() as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def get_symbol(code: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT code, name, market, enabled FROM symbols WHERE code = ?",
            (code,),
        ).fetchone()
    return dict(row) if row else None


def infer_market(code: str) -> str:
    """按 A 股代码前缀推断市场；无法识别时默认 SZ。"""
    c = code.strip()
    if c.startswith(("60", "68", "90")):
        return "SH"
    if c.startswith(("00", "30", "20")):
        return "SZ"
    if c.startswith(("43", "83", "87", "92")):
        return "BJ"
    return "SZ"


def upsert_symbol(
    code: str,
    name: str,
    market: str | None = None,
    *,
    enabled: int = 1,
) -> dict[str, Any]:
    """新增或更新关注股；已存在则更新名称/市场/启用状态。"""
    code = code.strip()
    if len(code) != 6 or not code.isdigit():
        raise ValueError("code must be 6 digits")
    mkt = (market or infer_market(code)).upper()
    if mkt not in ("SH", "SZ", "BJ"):
        raise ValueError("market must be SH / SZ / BJ")
    name = name.strip() or code
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO symbols(code, name, market, enabled)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
              name=excluded.name,
              market=excluded.market,
              enabled=excluded.enabled
            """,
            (code, name, mkt, 1 if enabled else 0),
        )
    row = get_symbol(code)
    assert row is not None
    return row


def set_symbol_enabled(code: str, enabled: bool) -> dict[str, Any] | None:
    """停用/启用；停用不删历史行情，只是每日 sync --all-enabled 会跳过。"""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE symbols SET enabled = ? WHERE code = ?",
            (1 if enabled else 0, code),
        )
        if cur.rowcount == 0:
            return None
    return get_symbol(code)


def delete_symbol(code: str, *, purge_data: bool = False) -> bool:
    """删除关注股。purge_data=True 时连带清该票全部归档与 sync_log。"""
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM symbols WHERE code = ?", (code,)
        ).fetchone()
        if not exists:
            return False
        if purge_data:
            for table in ("ticks", "minutes", "daily_summary", "sync_log", "margin_daily"):
                conn.execute(f"DELETE FROM {table} WHERE code = ?", (code,))
        conn.execute("DELETE FROM symbols WHERE code = ?", (code,))
    return True


def list_sync_logs(
    code: str | None = None,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """同步历史，新→旧；可按股票过滤。"""
    limit = max(1, min(limit, 500))
    with get_conn() as conn:
        if code:
            rows = conn.execute(
                """
                SELECT code, trade_date, status, tick_count, minute_count, message, synced_at
                FROM sync_log
                WHERE code = ?
                ORDER BY synced_at DESC, trade_date DESC
                LIMIT ?
                """,
                (code, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT code, trade_date, status, tick_count, minute_count, message, synced_at
                FROM sync_log
                ORDER BY synced_at DESC, trade_date DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def replace_day_data(
    *,
    code: str,
    trade_date: str,
    summary: dict[str, Any] | None,
    ticks: list[dict[str, Any]],
    minutes: list[dict[str, Any]],
    status: str,
    message: str = "",
) -> None:
    """同一交易日全量覆盖写入（先删后插），保证重复 sync 幂等。

    仅在调用方确认有可用数据时使用；失败场景应只写 sync_log，避免清空历史。
    """
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        # 先清当日三表，再插入，避免半旧半新
        conn.execute(
            "DELETE FROM ticks WHERE code = ? AND trade_date = ?",
            (code, trade_date),
        )
        conn.execute(
            "DELETE FROM minutes WHERE code = ? AND trade_date = ?",
            (code, trade_date),
        )
        conn.execute(
            "DELETE FROM daily_summary WHERE code = ? AND trade_date = ?",
            (code, trade_date),
        )

        if summary:
            conn.execute(
                """
                INSERT INTO daily_summary(
                  code, trade_date, pre_close, open, high, low, close, volume, amount
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    code,
                    trade_date,
                    summary.get("pre_close"),
                    summary.get("open"),
                    summary.get("high"),
                    summary.get("low"),
                    summary.get("close"),
                    summary.get("volume"),
                    summary.get("amount"),
                ),
            )

        if ticks:
            conn.executemany(
                """
                INSERT INTO ticks(code, trade_date, seq, time, price, volume, amount, side)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        code,
                        trade_date,
                        t["seq"],
                        t["time"],
                        t["price"],
                        t["volume"],
                        t.get("amount"),
                        t.get("side"),
                    )
                    for t in ticks
                ],
            )

        if minutes:
            conn.executemany(
                """
                INSERT INTO minutes(code, trade_date, minute, price, volume, amount)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        code,
                        trade_date,
                        m["minute"],
                        m["price"],
                        m["volume"],
                        m.get("amount"),
                    )
                    for m in minutes
                ],
            )

        conn.execute(
            """
            INSERT INTO sync_log(
              code, trade_date, status, tick_count, minute_count, message, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code, trade_date) DO UPDATE SET
              status=excluded.status,
              tick_count=excluded.tick_count,
              minute_count=excluded.minute_count,
              message=excluded.message,
              synced_at=excluded.synced_at
            """,
            (code, trade_date, status, len(ticks), len(minutes), message, now),
        )


def list_trade_dates(code: str) -> list[str]:
    """有分钟或明细任一归档的交易日，新→旧。"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT trade_date FROM minutes
            WHERE code = ?
            UNION
            SELECT DISTINCT trade_date FROM ticks WHERE code = ?
            ORDER BY trade_date DESC
            """,
            (code, code),
        ).fetchall()
    return [r[0] for r in rows]


def get_daily_summary(code: str, trade_date: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT code, trade_date, pre_close, open, high, low, close, volume, amount
            FROM daily_summary
            WHERE code = ? AND trade_date = ?
            """,
            (code, trade_date),
        ).fetchone()
    return dict(row) if row else None


def get_minutes(code: str, trade_date: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT minute, price, volume, amount
            FROM minutes
            WHERE code = ? AND trade_date = ?
            ORDER BY minute
            """,
            (code, trade_date),
        ).fetchall()
    return [dict(r) for r in rows]


def get_ticks(code: str, trade_date: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT seq, time, price, volume, amount, side
            FROM ticks
            WHERE code = ? AND trade_date = ?
            ORDER BY seq
            """,
            (code, trade_date),
        ).fetchall()
    return [dict(r) for r in rows]


def get_price_volume(code: str, trade_date: str) -> list[dict[str, Any]]:
    """分价表：按成交价汇总当日量（手）。"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT price, SUM(volume) AS volume
            FROM ticks
            WHERE code = ? AND trade_date = ?
            GROUP BY price
            ORDER BY price
            """,
            (code, trade_date),
        ).fetchall()
    return [dict(r) for r in rows]


def get_sync_log(code: str, trade_date: str | None = None) -> list[dict[str, Any]]:
    """单票某日或该票近期日志；全量历史请用 list_sync_logs。"""
    with get_conn() as conn:
        if trade_date:
            rows = conn.execute(
                """
                SELECT code, trade_date, status, tick_count, minute_count, message, synced_at
                FROM sync_log
                WHERE code = ? AND trade_date = ?
                """,
                (code, trade_date),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT code, trade_date, status, tick_count, minute_count, message, synced_at
                FROM sync_log
                WHERE code = ?
                ORDER BY trade_date DESC
                LIMIT 30
                """,
                (code,),
            ).fetchall()
    return [dict(r) for r in rows]


def upsert_margin_rows(rows: list[dict[str, Any]]) -> int:
    """幂等写入多日两融；按 (code, trade_date) 覆盖。返回写入条数。"""
    if not rows:
        return 0
    now = _now_str()
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO margin_daily(
              code, trade_date, rzye, rzmre, rzche, rzjme,
              rqye, rqyl, rqmcl, rqchl, rzrqye, rzyezb, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code, trade_date) DO UPDATE SET
              rzye=excluded.rzye,
              rzmre=excluded.rzmre,
              rzche=excluded.rzche,
              rzjme=excluded.rzjme,
              rqye=excluded.rqye,
              rqyl=excluded.rqyl,
              rqmcl=excluded.rqmcl,
              rqchl=excluded.rqchl,
              rzrqye=excluded.rzrqye,
              rzyezb=excluded.rzyezb,
              synced_at=excluded.synced_at
            """,
            [
                (
                    r["code"],
                    r["trade_date"],
                    r.get("rzye"),
                    r.get("rzmre"),
                    r.get("rzche"),
                    r.get("rzjme"),
                    r.get("rqye"),
                    r.get("rqyl"),
                    r.get("rqmcl"),
                    r.get("rqchl"),
                    r.get("rzrqye"),
                    r.get("rzyezb"),
                    now,
                )
                for r in rows
                if r.get("code") and r.get("trade_date")
            ],
        )
    return len([r for r in rows if r.get("code") and r.get("trade_date")])


def get_margin(code: str, trade_date: str) -> dict[str, Any] | None:
    """单票单日两融；无记录返回 None。"""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT code, trade_date, rzye, rzmre, rzche, rzjme,
                   rqye, rqyl, rqmcl, rqchl, rzrqye, rzyezb, synced_at
            FROM margin_daily
            WHERE code = ? AND trade_date = ?
            """,
            (code, trade_date),
        ).fetchone()
    return dict(row) if row else None


def list_margin(
    code: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 60,
) -> list[dict[str, Any]]:
    """单票两融历史，新→旧。"""
    limit = max(1, min(limit, 500))
    clauses = ["code = ?"]
    params: list[Any] = [code]
    if start_date:
        clauses.append("trade_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("trade_date <= ?")
        params.append(end_date)
    params.append(limit)
    sql = f"""
        SELECT code, trade_date, rzye, rzmre, rzche, rzjme,
               rqye, rqyl, rqmcl, rqchl, rzrqye, rzyezb, synced_at
        FROM margin_daily
        WHERE {" AND ".join(clauses)}
        ORDER BY trade_date DESC
        LIMIT ?
    """
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="DB utilities")
    parser.add_argument(
        "command",
        choices=["init", "migrate", "backup", "version"],
        help="init=建库+迁移; migrate=只升级 schema; backup=拷贝库; version=打印版本",
    )
    parser.add_argument(
        "--tag",
        default=None,
        help="backup 时附加标签，生成带时间戳文件（如 pre_deploy）",
    )
    args = parser.parse_args()
    if args.command == "init":
        init_db()
        print(f"initialized: {settings.db_path} schema_version={get_schema_version()}")
        for s in list_symbols():
            print(f"  {s['code']} {s['name']} ({s['market']})")
    elif args.command == "migrate":
        ver = migrate()
        print(f"migrated: {settings.db_path} schema_version={ver}")
    elif args.command == "backup":
        path = backup_db(tag=args.tag)
        if path:
            print(f"backup: {path}")
        else:
            print(f"no database at {settings.db_path}", flush=True)
            raise SystemExit(1)
    elif args.command == "version":
        print(get_schema_version())


if __name__ == "__main__":
    main()
