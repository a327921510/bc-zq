"""分时日同步编排：腾讯为主，失败回退东财。

两融仍走东财数据中心（见 eastmoney.fetch_margin_for_sync）。
"""

from __future__ import annotations

from typing import Any

import httpx

from . import eastmoney, tencent


def fetch_day(
    code: str,
    market: str,
    *,
    trade_date: str | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """先腾讯后东财；任一侧只要有 ticks/minutes 即成功。

    腾讯失败信息写入 errors / message 前缀，便于同步历史排查。
    """
    tencent_err: str | None = None
    try:
        result = tencent.fetch_day(
            code, market, trade_date=trade_date, client=client
        )
        if result.get("ticks") or result.get("minutes"):
            return result
        tencent_err = "tencent:empty ticks and minutes"
    except Exception as e:
        tencent_err = f"tencent:{e}"

    try:
        result = eastmoney.fetch_day(
            code, market, trade_date=trade_date, client=client
        )
    except Exception as e:
        parts = [p for p in (tencent_err, f"eastmoney:{e}") if p]
        raise RuntimeError("; ".join(parts)) from e

    errors = list(result.get("errors") or [])
    if tencent_err:
        errors.insert(0, tencent_err)
    result["errors"] = errors
    result["source"] = result.get("source") or "eastmoney"
    return result


def fetch_quote(
    code: str,
    market: str,
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """解析股票名称等：腾讯优先，东财兜底。"""
    try:
        own = client is None
        http_client = client or tencent.make_tencent_client()
        try:
            return tencent.fetch_quote(http_client, code, market)
        finally:
            if own:
                http_client.close()
    except Exception:
        pass

    own = client is None
    http_client = client or eastmoney.make_em_client()
    try:
        return eastmoney.fetch_quote(http_client, code, market)
    finally:
        if own:
            http_client.close()
