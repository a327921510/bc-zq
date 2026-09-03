"""HTTP API：回放读档 + 关注股管理 + 手动同步。

同进程托管 frontend/dist；写操作走 SQLite，同步会请求东财（可能较慢）。
"""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .base_path import BasePathMiddleware, normalize_base_path
from .config import ROOT_DIR, ensure_dirs, settings
from .db import (
    delete_symbol,
    get_daily_summary,
    get_margin,
    get_minutes,
    get_price_volume,
    get_symbol,
    get_sync_log,
    get_ticks,
    infer_market,
    init_db,
    list_margin,
    list_symbols,
    list_sync_logs,
    list_trade_dates,
    set_symbol_enabled,
    upsert_symbol,
)
from .fetch.eastmoney import UA, fetch_quote
from .ip_whitelist import IpWhitelistMiddleware
from .sync import sync_one
from .sync_guard import batch_gap_sleep, evaluate_sync, wait_eastmoney_gap

# 避免页面连点触发并行 sync 把 SQLite / 东财打爆
_sync_lock = threading.Lock()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    ensure_dirs()
    init_db()
    yield


app = FastAPI(
    title="BYD Intraday Archive",
    version="0.1.0",
    lifespan=lifespan,
)

# 本地前后端联调；生产由 Nginx 同源反代，CORS 影响有限
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 与 Nginx include 的 allowed_ips.conf 共用；默认关，生产可在 .env 打开作兜底
if settings.ip_whitelist_enabled:
    app.add_middleware(IpWhitelistMiddleware, whitelist_path=settings.ip_whitelist_path)

# 最后注册 = 最外层：先剥 /zq 再进 CORS / 路由
_base = normalize_base_path(settings.base_path)
if _base:
    app.add_middleware(BasePathMiddleware, base_path=_base)


class SymbolCreate(BaseModel):
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")
    name: str | None = None
    market: str | None = Field(None, description="SH / SZ / BJ；省略则按代码前缀推断")
    enabled: bool = True
    # 新增后立刻拉当日（免费源仅当日），方便马上回放
    sync_now: bool = True


class SymbolPatch(BaseModel):
    name: str | None = None
    market: str | None = None
    enabled: bool | None = None


class SyncRequest(BaseModel):
    code: str | None = Field(None, min_length=6, max_length=6, pattern=r"^\d{6}$")
    all_enabled: bool = False
    trade_date: str | None = Field(
        None,
        description="YYYY-MM-DD 标签日；东财明细仍是当前会话，不能真回补历史",
    )
    # True 时忽略冷却 /「近期已成功」跳过（仍受全局请求间隔约束）
    force: bool = False


def _resolve_name(code: str, market: str, name: str | None) -> str:
    """优先用调用方传入的名称；否则问东财报价，再退回代码本身。"""
    if name and name.strip():
        return name.strip()
    try:
        wait_eastmoney_gap()
        with httpx.Client(headers=UA, timeout=settings.http_timeout) as client:
            quote = fetch_quote(client, code, market)
        if quote.get("name"):
            return str(quote["name"])
    except Exception:
        pass
    return code


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/symbols")
def api_symbols(enabled_only: bool = Query(False)) -> list[dict[str, Any]]:
    return list_symbols(enabled_only=enabled_only)


@app.post("/api/symbols")
def api_create_symbol(body: SymbolCreate) -> dict[str, Any]:
    """增加关注股；可选立刻 sync 当日。"""
    market = (body.market or infer_market(body.code)).upper()
    try:
        row = upsert_symbol(
            body.code,
            _resolve_name(body.code, market, body.name),
            market,
            enabled=1 if body.enabled else 0,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    sync_result: dict[str, Any] | None = None
    if body.sync_now and body.enabled:
        sync_result = _run_sync(body.code, None, force=False)
        row = get_symbol(body.code) or row
    return {"symbol": row, "sync": sync_result}


@app.patch("/api/symbols/{code}")
def api_patch_symbol(code: str, body: SymbolPatch) -> dict[str, Any]:
    cur = get_symbol(code)
    if not cur:
        raise HTTPException(404, f"symbol not found: {code}")
    try:
        if body.name is not None or body.market is not None:
            upsert_symbol(
                code,
                body.name if body.name is not None else cur["name"],
                body.market if body.market is not None else cur["market"],
                enabled=cur["enabled"],
            )
        if body.enabled is not None:
            set_symbol_enabled(code, body.enabled)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    row = get_symbol(code)
    assert row is not None
    return row


@app.delete("/api/symbols/{code}")
def api_delete_symbol(
    code: str,
    purge_data: bool = Query(
        False,
        description="True 时删除该票全部 ticks/minutes/summary/sync_log",
    ),
) -> dict[str, Any]:
    if not delete_symbol(code, purge_data=purge_data):
        raise HTTPException(404, f"symbol not found: {code}")
    return {"ok": True, "code": code, "purged": purge_data}


@app.get("/api/sync/logs")
def api_sync_logs(
    code: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    return {"items": list_sync_logs(code=code, limit=limit)}


@app.get("/api/sync/guard")
def api_sync_guard(code: str = Query(..., min_length=6, max_length=6)) -> dict[str, Any]:
    """查询某票是否可立刻同步及提示文案（供前端展示）。"""
    return evaluate_sync(code, force=False)


@app.post("/api/sync")
def api_sync(body: SyncRequest) -> dict[str, Any]:
    """手动同步：单票或全部 enabled；阻塞直到完成。受频控约束。"""
    if body.all_enabled:
        symbols = list_symbols(enabled_only=True)
        if not symbols:
            raise HTTPException(400, "no enabled symbols")
        codes = [s["code"] for s in symbols]
    elif body.code:
        if not get_symbol(body.code):
            raise HTTPException(404, f"symbol not found: {body.code}")
        codes = [body.code]
    else:
        raise HTTPException(400, "provide code or all_enabled=true")
    return {"results": _run_sync_batch(codes, body.trade_date, force=body.force)}


def _skipped_result(code: str, guard: dict[str, Any]) -> dict[str, Any]:
    last = guard.get("last") or {}
    return {
        "code": code,
        "trade_date": last.get("trade_date"),
        "status": "skipped",
        "tick_count": last.get("tick_count"),
        "minute_count": last.get("minute_count"),
        "message": guard.get("tip") or "skipped by sync guard",
        "name": None,
        "wait_seconds": guard.get("wait_seconds", 0),
        "force_required": bool(guard.get("force_required")),
    }


def _run_sync_batch(
    codes: list[str],
    trade_date: str | None,
    *,
    force: bool = False,
) -> list[dict[str, Any]]:
    """同一时刻只允许一路同步；票间停顿；冷却期内默认 skipped。"""
    if not _sync_lock.acquire(blocking=False):
        return [
            {
                "code": c,
                "trade_date": trade_date,
                "status": "fail",
                "tick_count": None,
                "minute_count": None,
                "message": "another sync is running，请稍后再试",
                "name": None,
            }
            for c in codes
        ]
    try:
        results: list[dict[str, Any]] = []
        ran_any = False
        for i, code in enumerate(codes):
            guard = evaluate_sync(code, force=force)
            if not guard["allowed"]:
                results.append(_skipped_result(code, guard))
                continue
            if ran_any:
                batch_gap_sleep()
            try:
                results.append(sync_one(code, trade_date=trade_date))
                ran_any = True
            except Exception as e:
                results.append(
                    {
                        "code": code,
                        "trade_date": trade_date,
                        "status": "fail",
                        "tick_count": None,
                        "minute_count": None,
                        "message": str(e),
                        "name": None,
                    }
                )
                ran_any = True
        return results
    finally:
        _sync_lock.release()


def _run_sync(code: str, trade_date: str | None, *, force: bool = False) -> dict[str, Any]:
    return _run_sync_batch([code], trade_date, force=force)[0]

@app.get("/api/days")
def api_days(code: str = Query(..., min_length=6, max_length=6)) -> dict[str, Any]:
    return {"code": code, "dates": list_trade_dates(code)}


@app.get("/api/summary")
def api_summary(
    code: str = Query(...),
    date: str = Query(..., alias="date", description="YYYY-MM-DD"),
) -> dict[str, Any]:
    row = get_daily_summary(code, date)
    if not row:
        raise HTTPException(404, f"no summary for {code} {date}")
    return row


@app.get("/api/minutes")
def api_minutes(code: str = Query(...), date: str = Query(...)) -> dict[str, Any]:
    rows = get_minutes(code, date)
    if not rows:
        raise HTTPException(404, f"no minutes for {code} {date}")
    return {"code": code, "date": date, "items": rows}


@app.get("/api/ticks")
def api_ticks(code: str = Query(...), date: str = Query(...)) -> dict[str, Any]:
    rows = get_ticks(code, date)
    if not rows:
        raise HTTPException(404, f"no ticks for {code} {date}")
    return {"code": code, "date": date, "items": rows}


@app.get("/api/price-volume")
def api_price_volume(code: str = Query(...), date: str = Query(...)) -> dict[str, Any]:
    rows = get_price_volume(code, date)
    if not rows:
        raise HTTPException(404, f"no price-volume for {code} {date}")
    return {"code": code, "date": date, "items": rows}


@app.get("/api/margin")
def api_margin(
    code: str = Query(..., min_length=6, max_length=6),
    date: str | None = Query(None, description="YYYY-MM-DD；省略则返回近期列表"),
    limit: int = Query(30, ge=1, le=200),
) -> dict[str, Any]:
    """个股两融：指定日返回单条，否则返回近期列表。"""
    if date:
        row = get_margin(code, date)
        if not row:
            raise HTTPException(404, f"no margin for {code} {date}")
        return {"code": code, "date": date, "item": row}
    return {"code": code, "items": list_margin(code, limit=limit)}


@app.get("/api/day")
def api_day(code: str = Query(...), date: str = Query(...)) -> dict[str, Any]:
    """回放页一次取齐：摘要 + 分钟 + 明细 + 分价 + 两融 + 同步状态。"""
    minutes = get_minutes(code, date)
    ticks = get_ticks(code, date)
    if not minutes and not ticks:
        raise HTTPException(404, f"no data for {code} {date}")
    return {
        "code": code,
        "date": date,
        "summary": get_daily_summary(code, date),
        "minutes": minutes,
        "ticks": ticks,
        "price_volume": get_price_volume(code, date),
        "margin": get_margin(code, date),
        "sync": (get_sync_log(code, date) or [None])[0],
    }


FRONTEND_DIR = ROOT_DIR / "frontend" / "dist"
_ASSETS = FRONTEND_DIR / "assets"
if _ASSETS.is_dir():
    app.mount("/assets", StaticFiles(directory=_ASSETS), name="assets")


def _frontend_index() -> FileResponse:
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(404, "frontend/dist/index.html missing")
    return FileResponse(index_path)


@app.get("/")
def index() -> FileResponse:
    return _frontend_index()


@app.get("/{full_path:path}")
def spa_fallback(full_path: str) -> FileResponse:
    """React Router 刷新时回退到 index.html；API / 静态资源已由更具体路由处理。"""
    # 避免把缺失的 api 路径误当成前端路由
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(404, "not found")
    candidate = FRONTEND_DIR / full_path
    if candidate.is_file():
        return FileResponse(candidate)
    return _frontend_index()
