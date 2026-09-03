"""同步入口：分时收盘归档 + 两融独立补拉。

- 分时：交易日收盘后拉东财当日明细/分时（免费源不能回补历史明细）。
- 两融：交易所通常次日上午才更新 T 日，由独立任务在约 10:10 补拉；
  失败不清空已有行情；分时任务默认不拉两融，避免 16:00 白跑。
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


def sync_margin_one(code: str, trade_date: str | None = None) -> dict[str, Any]:
    """仅同步个股两融（可回补近几日）；不打分时接口。

    trade_date 可选：优先确保该日落库；缺省则拉近 lookback 窗口内有的日期。
    """
    init_db()
    symbol = get_symbol(code)
    if not symbol:
        raise ValueError(f"unknown symbol: {code} (add via API or db init first)")

    result = fetch_margin_for_sync(code, trade_date=trade_date)
    rows = result.get("rows") or []
    n = upsert_margin_rows(rows) if rows else 0
    msg_parts = [f"margin_rows={n}"]
    if result.get("raw_path"):
        msg_parts.append(f"raw={result['raw_path']}")
    if result.get("errors"):
        msg_parts.append(f"warnings={result['errors']}")
    msg = "; ".join(msg_parts)

    # 无行视为失败，便于计划任务日志告警；周末/无更新日可能经常为 0
    status = "ok" if n > 0 else "fail"
    if result.get("errors") and n > 0:
        status = "partial"

    return {
        "code": code,
        "trade_date": trade_date or (rows[0]["trade_date"] if rows else _today()),
        "status": status,
        "tick_count": None,
        "minute_count": None,
        "message": msg,
        "name": symbol.get("name"),
        "margin_count": n,
    }


def sync_one(
    code: str,
    trade_date: str | None = None,
    *,
    with_margin: bool = False,
) -> dict[str, Any]:
    """同步单票分时；默认不拉两融（两融改由次日上午独立任务）。

    with_margin=True 时顺带补两融，供手工补数；失败不拖垮分时入库。
    """
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

        margin_count = 0
        if status == "fail":
            _log_fail(code, resolved, msg)
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

        if with_margin:
            margin_info = sync_margin_one(code, trade_date=resolved)
            margin_count = int(margin_info.get("margin_count") or 0)
            margin_note = margin_info.get("message") or ""
            if margin_note and status != "fail":
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
            "margin_count": margin_count,
        }
    except Exception as e:
        day = trade_date or _today()
        _log_fail(code, day, str(e))
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync Eastmoney intraday / margin archive")
    parser.add_argument("--code", help="stock code, e.g. 002594")
    parser.add_argument(
        "--date",
        dest="trade_date",
        help="YYYY-MM-DD；分时仅为标签日；两融可按该日优先补拉",
    )
    parser.add_argument("--all-enabled", action="store_true", help="sync all enabled symbols")
    parser.add_argument("--backup", action="store_true", help="copy db after successful sync")
    # 两融独立任务：次日上午用，不打分时接口
    parser.add_argument(
        "--margin-only",
        action="store_true",
        help="仅同步两融（推荐计划任务 10:10），不拉分时/明细",
    )
    parser.add_argument(
        "--with-margin",
        action="store_true",
        help="分时同步时顺带拉两融（手工补数用；日常收盘任务勿开）",
    )
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
            if args.margin_only:
                info = sync_margin_one(code, trade_date=args.trade_date)
                print(
                    f"[margin] {info['code']} {info.get('name') or ''} "
                    f"{info['trade_date']} margin={info.get('margin_count', 0)} "
                    f"status={info['status']} {info.get('message') or ''}"
                )
            else:
                info = sync_one(
                    code,
                    trade_date=args.trade_date,
                    with_margin=bool(args.with_margin),
                )
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
