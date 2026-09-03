"""每日收盘同步入口：拉东财 → 入库 → 可选备份 DB。

失败只更新 sync_log，不清空已有当日行情，避免接口抖动丢档。
两融走东财 datacenter，交易所通常 T+1 上午才更新；失败不拖垮分时同步。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from typing import Any

from .config import ROOT_DIR, ensure_dirs
from .db import (
    backup_db,
    get_conn,
    get_symbol,
    init_db,
    list_symbols,
    replace_day_data,
    upsert_margin_rows,
    upsert_symbol,
)
from .fetch.eastmoney import fetch_day, fetch_margin_for_sync


def _today() -> str:
    return date.today().isoformat()


def _log_fail(code: str, trade_date: str, message: str) -> None:
    """仅记失败日志，不 DELETE 行情表。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO sync_log(
              code, trade_date, status, tick_count, minute_count, message, synced_at
            ) VALUES (?, ?, 'fail', NULL, NULL, ?, ?)
            ON CONFLICT(code, trade_date) DO UPDATE SET
              status='fail',
              message=excluded.message,
              synced_at=excluded.synced_at
            """,
            (code, trade_date, message, now),
        )


def _sync_margin(code: str, trade_date: str | None) -> dict[str, Any]:
    """尽力拉近几日两融并入库；空数据 / 异常只记结果，不抛给上层。"""
    try:
        result = fetch_margin_for_sync(code, trade_date=trade_date)
        rows = result.get("rows") or []
        n = upsert_margin_rows(rows) if rows else 0
        msg_parts = [f"margin_rows={n}"]
        if result.get("raw_path"):
            msg_parts.append(f"raw={result['raw_path']}")
        if result.get("errors"):
            msg_parts.append(f"warnings={result['errors']}")
        return {
            "ok": n > 0,
            "count": n,
            "message": "; ".join(msg_parts),
            "has_trade_date": bool(
                trade_date and any(r.get("trade_date") == trade_date for r in rows)
            ),
        }
    except Exception as e:
        return {"ok": False, "count": 0, "message": f"margin:{e}", "has_trade_date": False}


def sync_one(code: str, trade_date: str | None = None) -> dict[str, Any]:
    """同步单票；有数据则幂等覆盖，空结果 / 异常则 fail 且保留旧数据。"""
    init_db()
    symbol = get_symbol(code)
    if not symbol:
        raise ValueError(f"unknown symbol: {code} (add via API or db init first)")

    market = symbol["market"]
    try:
        result = fetch_day(code, market, trade_date=trade_date)
        resolved = result["trade_date"]

        # 免费源无法按任意历史日取明细；请求日与源日期不一致标 partial
        if trade_date and result.get("trends_date") and trade_date != result["trends_date"]:
            msg = (
                f"requested {trade_date} but source returned {result['trends_date']}; "
                "stored as source date"
            )
            status = "partial"
        else:
            msg = f"raw={result['raw_path']}"
            status = "ok" if result["ticks"] or result["minutes"] else "fail"
            if result.get("errors"):
                status = "partial" if status == "ok" else status
                msg = f"{msg}; warnings={result['errors']}"
            if not result["ticks"] and not result["minutes"]:
                msg = "empty ticks and minutes"

        if status == "fail":
            _log_fail(code, resolved, msg)
            # 分时失败仍尝试补两融（历史日可回补）
            margin_info = _sync_margin(code, trade_date or resolved)
        else:
            replace_day_data(
                code=code,
                trade_date=resolved,
                summary=result["summary"],
                ticks=result["ticks"],
                minutes=result["minutes"],
                status=status,
                message=msg,
            )
            # 同步成功时用行情源名称回写，便于新增时只填代码
            fetched_name = result.get("name")
            if fetched_name and fetched_name != symbol.get("name"):
                upsert_symbol(
                    code,
                    fetched_name,
                    market=market,
                    enabled=int(symbol.get("enabled", 1)),
                )
            margin_info = _sync_margin(code, resolved)
            # 两融信息追加进 sync_log message，便于排查；不改 status
            if margin_info.get("message"):
                margin_note = margin_info["message"]
                with get_conn() as conn:
                    row = conn.execute(
                        "SELECT message FROM sync_log WHERE code=? AND trade_date=?",
                        (code, resolved),
                    ).fetchone()
                    old = (row["message"] if row else "") or msg
                    conn.execute(
                        """
                        UPDATE sync_log SET message = ?
                        WHERE code = ? AND trade_date = ?
                        """,
                        (f"{old}; {margin_note}", code, resolved),
                    )
                msg = f"{msg}; {margin_note}"

        return {
            "code": code,
            "trade_date": resolved,
            "status": status,
            "tick_count": len(result["ticks"]),
            "minute_count": len(result["minutes"]),
            "message": msg,
            "name": result.get("name") or symbol.get("name"),
            "margin_count": margin_info.get("count", 0),
        }
    except Exception as e:
        day = trade_date or _today()
        _log_fail(code, day, str(e))
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync Eastmoney intraday archive")
    parser.add_argument("--code", help="stock code, e.g. 002594")
    parser.add_argument(
        "--date",
        dest="trade_date",
        help="label date YYYY-MM-DD（源仍是当日会话，不能真回补历史）",
    )
    parser.add_argument("--all-enabled", action="store_true", help="sync all enabled symbols")
    parser.add_argument("--backup", action="store_true", help="copy db after successful sync")
    args = parser.parse_args(argv)

    ensure_dirs()
    init_db()

    if args.all_enabled:
        symbols = list_symbols(enabled_only=True)
    elif args.code:
        symbols = [get_symbol(args.code)]
        if not symbols[0]:
            print(f"unknown symbol: {args.code}", file=sys.stderr)
            return 1
    else:
        parser.error("provide --code or --all-enabled")
        return 2

    failed = 0
    for sym in symbols:
        code = sym["code"]
        try:
            info = sync_one(code, trade_date=args.trade_date)
            print(
                f"[ok] {info['code']} {info.get('name') or ''} "
                f"{info['trade_date']} ticks={info['tick_count']} "
                f"minutes={info['minute_count']} margin={info.get('margin_count', 0)} "
                f"status={info['status']}"
            )
            if info["status"] == "fail":
                failed += 1
        except Exception as e:
            failed += 1
            print(f"[fail] {code}: {e}", file=sys.stderr)

    if args.backup and failed == 0:
        path = backup_db(tag=None)
        if path:
            print(f"[backup] {path}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT_DIR))
    raise SystemExit(main())
