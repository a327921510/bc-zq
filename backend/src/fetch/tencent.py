"""腾讯财经网页行情适配器：当日分时 / 成交明细 / 报价。

免费接口同样只覆盖「当前交易日会话」，不能按历史日回补明细。
机房 IP 上通常比东财 push2 更稳，作为主源；失败由上层回退东财。
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

import httpx

from ..aggregate import minutes_from_ticks
from ..config import settings
from ..sync_guard import wait_eastmoney_gap
from .eastmoney import save_raw

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://gu.qq.com/",
    "Connection": "close",
    "Accept": "*/*",
}

# 明细分页：空响应表示翻完；安全上限防止异常死循环
_DETAIL_MAX_PAGES = 200


def tencent_code(code: str, market: str) -> str:
    """腾讯代码：深市 szxxxxxx / 沪市 shxxxxxx。"""
    prefix = "sh" if market.upper() == "SH" else "sz"
    return f"{prefix}{code}"


def make_tencent_client() -> httpx.Client:
    return httpx.Client(
        headers=UA,
        timeout=settings.http_timeout,
        follow_redirects=True,
        limits=httpx.Limits(max_keepalive_connections=0, max_connections=20),
    )


def map_tencent_side(raw: Any) -> str:
    """腾讯明细方向：B/S；M（中性盘）及其余 → N。"""
    s = str(raw or "").strip().upper()
    if s == "B":
        return "B"
    if s == "S":
        return "S"
    return "N"


def parse_tencent_quote_fields(fields: list[str]) -> dict[str, Any]:
    """解析 qt.gtimg.cn / minute.qt 下标字段（~ 或 list）。"""
    def _f(i: int) -> str:
        return fields[i] if len(fields) > i else ""

    def _num(i: int) -> float | None:
        raw = _f(i).strip()
        if not raw or raw == "-":
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    # v[35] 形如 现价/量手/成交额元
    amount = None
    slash = _f(35)
    if "/" in slash:
        parts = slash.split("/")
        if len(parts) >= 3:
            try:
                amount = float(parts[2])
            except ValueError:
                amount = None
    if amount is None:
        # v[37] 常为成交额（万元）
        wan = _num(37)
        if wan is not None:
            amount = wan * 10000

    return {
        "name": _f(1) or None,
        "code": _f(2) or None,
        "price": _num(3),
        "pre_close": _num(4),
        "open": _num(5),
        "volume": _num(36) if _num(36) is not None else _num(6),
        "amount": amount,
        "high": _num(33),
        "low": _num(34),
        "datetime": _f(30) or None,
    }


def parse_tencent_minute_lines(
    lines: list[str],
) -> tuple[str | None, list[dict[str, Any]]]:
    """解析分时行：`HHMM price cum_vol cum_amount`（量额为累计，需差分）。

    返回 (trade_date占位 None, minutes)；日期由报价 datetime 补。
    """
    minutes: list[dict[str, Any]] = []
    prev_vol = 0.0
    prev_amt = 0.0
    for line in lines:
        parts = str(line).split()
        if len(parts) < 4:
            continue
        hm = parts[0].strip()
        if len(hm) != 4 or not hm.isdigit():
            continue
        minute = f"{hm[:2]}:{hm[2:]}"
        # 与东财一致：只保留连续竞价时段
        if not (("09:30" <= minute <= "11:30") or ("13:00" <= minute <= "15:00")):
            continue
        try:
            price = float(parts[1])
            cum_vol = float(parts[2])
            cum_amt = float(parts[3])
        except ValueError:
            continue
        vol = max(0.0, cum_vol - prev_vol)
        amt = max(0.0, cum_amt - prev_amt)
        prev_vol, prev_amt = cum_vol, cum_amt
        minutes.append(
            {"minute": minute, "price": price, "volume": vol, "amount": amt}
        )
    return None, minutes


def parse_tencent_detail_chunk(chunk: str) -> list[dict[str, Any]]:
    """解析一页明细：`seq/time/price/change/vol/amount/side|...`。"""
    ticks: list[dict[str, Any]] = []
    for item in chunk.split("|"):
        item = item.strip()
        if not item:
            continue
        parts = item.split("/")
        if len(parts) < 7:
            continue
        try:
            seq = int(parts[0])
            price = float(parts[2])
            volume = float(parts[4])
            amount = float(parts[5])
        except ValueError:
            continue
        ticks.append(
            {
                "seq": seq,
                "time": parts[1].strip(),
                "price": price,
                "volume": volume,
                "amount": amount,
                "side": map_tencent_side(parts[6]),
            }
        )
    return ticks


def _trade_date_from_qt_datetime(raw: str | None) -> str | None:
    """`20260929161500` → `2026-09-29`。"""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return None


def fetch_quote(client: httpx.Client, code: str, market: str) -> dict[str, Any]:
    """腾讯实时报价（GBK 文本）。"""
    sym = tencent_code(code, market)
    resp = client.get(f"https://qt.gtimg.cn/q={sym}")
    resp.raise_for_status()
    text = resp.content.decode("gbk", errors="replace").strip()
    # v_sz002594="..."
    m = re.search(r'="([^"]*)"', text)
    if not m:
        raise ValueError(f"tencent quote empty for {sym}")
    fields = m.group(1).split("~")
    return parse_tencent_quote_fields(fields)


def fetch_minutes(
    client: httpx.Client, code: str, market: str
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """当日分时；顺带取出内嵌 qt 报价字段。"""
    sym = tencent_code(code, market)
    resp = client.get(
        "https://web.ifzq.gtimg.cn/appstock/app/minute/query",
        params={"code": sym},
    )
    resp.raise_for_status()
    payload = resp.json()
    block = ((payload.get("data") or {}).get(sym) or {})
    raw_lines = ((block.get("data") or {}).get("data")) or []
    raw_lines = list(raw_lines)

    quote: dict[str, Any] = {}
    qt = (block.get("qt") or {}).get(sym) or []
    if isinstance(qt, list) and qt:
        quote = parse_tencent_quote_fields([str(x) for x in qt])

    _, minutes = parse_tencent_minute_lines(raw_lines)
    return quote, minutes, raw_lines


def fetch_details(
    client: httpx.Client,
    code: str,
    market: str,
    trade_date: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """翻页拉全部分成交明细；trade_date 为 YYYY-MM-DD。"""
    sym = tencent_code(code, market)
    day = trade_date.replace("-", "")
    ticks: list[dict[str, Any]] = []
    raw_pages: list[str] = []
    for page in range(_DETAIL_MAX_PAGES):
        wait_eastmoney_gap()
        resp = client.get(
            "https://stock.gtimg.cn/data/index.php",
            params={
                "appn": "detail",
                "action": "data",
                "c": sym,
                "d": day,
                "p": str(page),
            },
        )
        resp.raise_for_status()
        # 该接口常为 GBK；空 body = 没有更多页
        body = resp.content.decode("gbk", errors="replace").strip()
        if not body:
            break
        raw_pages.append(body)
        m = re.search(r'=\[[0-9]+,"(.*)"\]\s*;?\s*$', body, re.DOTALL)
        if not m:
            # 兼容无引号转义的简单形态
            m2 = re.search(r'=\[[0-9]+,"(.*)"\]', body, re.DOTALL)
            if not m2:
                break
            chunk = m2.group(1)
        else:
            chunk = m.group(1)
        # JS 字符串里的 \" 极少；直接按 | 切
        page_ticks = parse_tencent_detail_chunk(chunk)
        if not page_ticks:
            break
        ticks.extend(page_ticks)
    ticks.sort(key=lambda t: t["seq"])
    return ticks, raw_pages


def fetch_day(
    code: str,
    market: str,
    *,
    trade_date: str | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """拉取腾讯「当前会话」日数据，输出结构与东财 fetch_day 对齐。"""
    own = client is None
    http_client = client or make_tencent_client()
    errors: list[str] = []
    try:
        quote: dict[str, Any] = {}
        minutes: list[dict[str, Any]] = []
        raw_minute_lines: list[str] = []
        try:
            wait_eastmoney_gap()
            quote, minutes, raw_minute_lines = fetch_minutes(http_client, code, market)
        except Exception as e:
            errors.append(f"minutes:{e}")

        # 报价兜底（minute 内嵌 qt 失败时）
        if not quote.get("name") and not quote.get("price"):
            try:
                wait_eastmoney_gap()
                quote = fetch_quote(http_client, code, market)
            except Exception as e:
                errors.append(f"quote:{e}")

        resolved = (
            trade_date
            or _trade_date_from_qt_datetime(quote.get("datetime"))
            or date.today().isoformat()
        )

        ticks: list[dict[str, Any]] = []
        raw_detail_pages: list[str] = []
        try:
            ticks, raw_detail_pages = fetch_details(
                http_client, code, market, resolved
            )
        except Exception as e:
            errors.append(f"details:{e}")

        if not minutes and ticks:
            minutes = minutes_from_ticks(ticks)

        if not ticks and not minutes:
            raise RuntimeError("; ".join(errors) or "empty response from tencent")

        open_p = minutes[0]["price"] if minutes else quote.get("open")
        close_p = minutes[-1]["price"] if minutes else quote.get("price")
        high_p = max((m["price"] for m in minutes), default=quote.get("high"))
        low_p = min((m["price"] for m in minutes), default=quote.get("low"))
        vol = sum(m["volume"] for m in minutes) if minutes else quote.get("volume")
        amt = sum(m.get("amount") or 0 for m in minutes) if minutes else quote.get("amount")

        summary = {
            "pre_close": quote.get("pre_close"),
            "open": quote.get("open") or open_p,
            "high": quote.get("high") or high_p,
            "low": quote.get("low") or low_p,
            "close": quote.get("price") or close_p,
            "volume": vol if minutes else quote.get("volume"),
            "amount": amt if minutes else quote.get("amount"),
        }

        raw = {
            "source": "tencent",
            "code": code,
            "market": market,
            "trade_date": resolved,
            "quote": quote,
            "minutes_raw": raw_minute_lines,
            "details_pages": len(raw_detail_pages),
            "errors": errors,
        }
        raw_path = save_raw(code, resolved, raw)

        return {
            "code": code,
            "market": market,
            "trade_date": resolved,
            "trends_date": resolved,
            "summary": summary,
            "ticks": ticks,
            "minutes": minutes,
            "raw_path": str(raw_path),
            "name": quote.get("name"),
            "errors": errors,
            "source": "tencent",
        }
    finally:
        if own:
            http_client.close()
