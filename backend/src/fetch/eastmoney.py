"""东财网页行情适配器：拉当日明细 / 分时 / 报价，以及数据中心两融明细。

注意：免费 details 只覆盖「当前交易日会话」，不能按历史日期回补。
两融（RPTA_WEB_RZRQ_GGMX）可按历史日回补，但交易所通常次日上午才更新 T 日。
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from ..aggregate import minutes_from_ticks, parse_details, parse_trends
from ..config import ensure_dirs, settings
from ..sync_guard import wait_eastmoney_gap

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}

# 部分网络下 push2 / push2his 会 Empty reply；push2delay 通常可用，作首选并回退
PUSH_HOSTS = (
    "push2delay.eastmoney.com",
    "push2.eastmoney.com",
)
HIS_HOSTS = (
    "push2delay.eastmoney.com",
    "push2his.eastmoney.com",
)


def secid(code: str, market: str) -> str:
    """东财 secid：沪市 1.xxxxxx，深市 0.xxxxxx。"""
    prefix = "1" if market.upper() == "SH" else "0"
    return f"{prefix}.{code}"


def _get_json(
    client: httpx.Client,
    path: str,
    params: dict[str, Any],
    *,
    hosts: tuple[str, ...] = PUSH_HOSTS,
) -> dict[str, Any]:
    """按 host 列表依次 GET；单 host 内短重试，应对东财偶发断连。"""
    last_err: Exception | None = None
    for host in hosts:
        url = f"https://{host}{path}"
        for attempt in range(2):
            try:
                resp = client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_err = e
                if attempt < 1:
                    time.sleep(0.5 * (attempt + 1))
    assert last_err is not None
    raise last_err


def fetch_details(client: httpx.Client, code: str, market: str) -> list[str]:
    """当日成交明细原始行列表（pos=0 尽量拉全量）。"""
    data = _get_json(
        client,
        "/api/qt/stock/details/get",
        {
            "fields1": "f1,f2,f3,f4",
            "fields2": "f51,f52,f53,f54,f55",
            "mpi": "2000",
            "secid": secid(code, market),
            "pos": "0",
        },
    )
    details = (data.get("data") or {}).get("details") or []
    return list(details)


def fetch_trends(
    client: httpx.Client, code: str, market: str, ndays: int = 1
) -> tuple[dict[str, Any], list[str]]:
    """分时 trends2；多日优先走 his 域名，失败再回退 delay。"""
    hosts = PUSH_HOSTS if ndays <= 1 else HIS_HOSTS
    data = _get_json(
        client,
        "/api/qt/stock/trends2/get",
        {
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "secid": secid(code, market),
            "ndays": str(ndays),
            "iscr": "0",
        },
        hosts=hosts,
    )
    payload = data.get("data") or {}
    trends = payload.get("trends") or []
    meta = {
        "name": payload.get("name"),
        "pre_close": payload.get("preClose"),
        "code": payload.get("code"),
    }
    return meta, list(trends)


def fetch_quote(client: httpx.Client, code: str, market: str) -> dict[str, Any]:
    """快照报价；字段号为东财约定（f47=量手，f48=额）。"""
    data = _get_json(
        client,
        "/api/qt/stock/get",
        {
            "secid": secid(code, market),
            "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f168,f170",
            "fltt": "2",
            "invt": "2",
        },
    )
    d = data.get("data") or {}
    return {
        "name": d.get("f58"),
        "code": d.get("f57"),
        "price": d.get("f43"),
        "high": d.get("f44"),
        "low": d.get("f45"),
        "open": d.get("f46"),
        "volume": d.get("f47"),
        "amount": d.get("f48"),
    }


def save_raw(code: str, trade_date: str, payload: dict[str, Any]) -> Path:
    """原始响应落盘，便于接口改版后对照重放。"""
    ensure_dirs()
    day_dir = settings.backup_dir / "raw" / code
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"{trade_date}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 两融：走东财数据中心（与 push2 行情域名不同）；交易所通常次日上午才更新 T 日
# ---------------------------------------------------------------------------

DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
# 个股融资融券明细报表名（东财网页「数据中心 → 融资融券」同源）
MARGIN_REPORT = "RPTA_WEB_RZRQ_GGMX"


def _parse_margin_row(row: dict[str, Any]) -> dict[str, Any]:
    """东财大写字段 → 入库用 snake_case；DATE 截成 YYYY-MM-DD。"""
    raw_date = str(row.get("DATE") or "")
    trade_date = raw_date[:10] if len(raw_date) >= 10 else raw_date
    return {
        "code": str(row.get("SCODE") or ""),
        "trade_date": trade_date,
        "name": row.get("SECNAME"),
        "rzye": row.get("RZYE"),
        "rzmre": row.get("RZMRE"),
        "rzche": row.get("RZCHE"),
        "rzjme": row.get("RZJME"),
        "rqye": row.get("RQYE"),
        "rqyl": row.get("RQYL"),
        "rqmcl": row.get("RQMCL"),
        "rqchl": row.get("RQCHL"),
        "rzrqye": row.get("RZRQYE"),
        "rzyezb": row.get("RZYEZB"),  # 融资余额占流通市值比（%）
    }


def fetch_margin(
    client: httpx.Client,
    code: str,
    *,
    trade_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    page_size: int = 50,
) -> list[dict[str, Any]]:
    """拉取个股两融明细；可按单日或日期区间过滤。

    无日期条件时返回该票最新 page_size 条（按 DATE 降序）。
    """
    filters = [f'(SCODE="{code}")']
    if trade_date:
        filters.append(f"(DATE='{trade_date}')")
    else:
        if start_date:
            filters.append(f"(DATE>='{start_date}')")
        if end_date:
            filters.append(f"(DATE<='{end_date}')")

    params = {
        "reportName": MARGIN_REPORT,
        "columns": "ALL",
        "filter": "".join(filters),
        "pageNumber": "1",
        "pageSize": str(max(1, min(page_size, 500))),
        "sortColumns": "DATE",
        "sortTypes": "-1",
        "source": "WEB",
        "client": "WEB",
    }
    resp = client.get(
        DATACENTER_URL,
        params=params,
        headers={**UA, "Referer": "https://data.eastmoney.com/"},
    )
    resp.raise_for_status()
    payload = resp.json()
    rows = ((payload.get("result") or {}).get("data")) or []
    return [_parse_margin_row(r) for r in rows if r]


def save_raw_margin(code: str, tag: str, rows: list[dict[str, Any]]) -> Path:
    """两融原始解析结果落盘，与分时 raw 分文件，避免互相覆盖。"""
    ensure_dirs()
    day_dir = settings.backup_dir / "raw" / code
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"margin_{tag}.json"
    path.write_text(
        json.dumps({"source": "eastmoney_datacenter", "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def fetch_margin_for_sync(
    code: str,
    *,
    trade_date: str | None = None,
    lookback_days: int = 10,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """同步用：优先拉指定日；并补近 lookback_days 自然日区间（覆盖 T+1 才出的两融）。

    返回 {rows, raw_path, errors}；空结果不抛错，由调用方记 warning。
    """
    from datetime import timedelta

    own = client is None
    client = client or httpx.Client(
        headers=UA,
        timeout=settings.http_timeout,
        follow_redirects=True,
    )
    errors: list[str] = []
    collected: dict[str, dict[str, Any]] = {}
    try:
        end = date.today()
        start = end - timedelta(days=max(1, lookback_days))
        try:
            wait_eastmoney_gap()
            for row in fetch_margin(
                client,
                code,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                page_size=50,
            ):
                if row.get("trade_date") and row.get("code"):
                    collected[row["trade_date"]] = row
        except Exception as e:
            errors.append(f"margin_range:{e}")

        # 指定日若不在区间结果里，再单日补一次（容错 filter 边界）
        if trade_date and trade_date not in collected:
            try:
                wait_eastmoney_gap()
                for row in fetch_margin(client, code, trade_date=trade_date, page_size=5):
                    if row.get("trade_date") and row.get("code"):
                        collected[row["trade_date"]] = row
            except Exception as e:
                errors.append(f"margin_day:{e}")

        rows = sorted(collected.values(), key=lambda r: r["trade_date"], reverse=True)
        tag = trade_date or end.isoformat()
        raw_path = save_raw_margin(code, tag, rows) if rows else None
        return {"rows": rows, "raw_path": str(raw_path) if raw_path else None, "errors": errors}
    finally:
        if own:
            client.close()


def fetch_day(
    code: str,
    market: str,
    *,
    trade_date: str | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """拉取「当前会话」日数据并解析为入库结构。

    分接口容错：trends/quote 失败仍可用 details；两者皆空则抛错。
    trade_date 仅作标签；真正日期以 trends 解析结果或系统当日为准。
    """
    own = client is None
    client = client or httpx.Client(
        headers=UA,
        timeout=settings.http_timeout,
        follow_redirects=True,
    )
    try:
        errors: list[str] = []
        meta: dict[str, Any] = {}
        trend_lines: list[str] = []
        try:
            wait_eastmoney_gap()
            meta, trend_lines = fetch_trends(client, code, market, ndays=1)
        except Exception as e:
            errors.append(f"trends:{e}")

        detail_lines: list[str] = []
        try:
            wait_eastmoney_gap()
            detail_lines = fetch_details(client, code, market)
        except Exception as e:
            errors.append(f"details:{e}")

        quote: dict[str, Any] = {}
        try:
            wait_eastmoney_gap()
            quote = fetch_quote(client, code, market)
        except Exception as e:
            errors.append(f"quote:{e}")

        if not detail_lines and not trend_lines:
            raise RuntimeError("; ".join(errors) or "empty response from eastmoney")

        ticks = parse_details(detail_lines)
        parsed_date, minutes = parse_trends(trend_lines)
        # 无分时则用明细合成，保证回放页有价量轴
        if not minutes and ticks:
            minutes = minutes_from_ticks(ticks)

        resolved_date = trade_date or parsed_date or date.today().isoformat()

        open_p = minutes[0]["price"] if minutes else quote.get("open")
        close_p = minutes[-1]["price"] if minutes else quote.get("price")
        high_p = max((m["price"] for m in minutes), default=quote.get("high"))
        low_p = min((m["price"] for m in minutes), default=quote.get("low"))
        vol = sum(m["volume"] for m in minutes) if minutes else quote.get("volume")
        amt = sum(m.get("amount") or 0 for m in minutes) if minutes else quote.get("amount")

        # 量额优先用分钟合计，避免误用报价字段（曾出现 f60 映射错误）
        summary = {
            "pre_close": meta.get("pre_close"),
            "open": quote.get("open") or open_p,
            "high": quote.get("high") or high_p,
            "low": quote.get("low") or low_p,
            "close": quote.get("price") or close_p,
            "volume": vol if minutes else quote.get("volume"),
            "amount": amt if minutes else quote.get("amount"),
        }

        raw = {
            "source": "eastmoney",
            "code": code,
            "market": market,
            "trade_date": resolved_date,
            "trends_meta": meta,
            "trends": trend_lines,
            "details": detail_lines,
            "quote": quote,
            "errors": errors,
        }
        raw_path = save_raw(code, resolved_date, raw)

        return {
            "code": code,
            "market": market,
            "trade_date": resolved_date,
            "trends_date": parsed_date,
            "summary": summary,
            "ticks": ticks,
            "minutes": minutes,
            "raw_path": str(raw_path),
            "name": meta.get("name") or quote.get("name"),
            "errors": errors,
        }
    finally:
        if own:
            client.close()
