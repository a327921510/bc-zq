"""东财网页行情适配器：拉当日明细 / 分时 / 报价，落 raw JSON 后交给入库。

注意：免费 details 只覆盖「当前交易日会话」，不能按历史日期回补。
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
