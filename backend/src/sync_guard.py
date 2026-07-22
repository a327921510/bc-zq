"""同步频控：降低对东财免费接口的请求频率，降低被限流 / 拉黑风险。

仅约束经 API 触发的手动同步；CLI cron 仍可直接调 sync_one（计划任务一天一次）。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

from .config import settings
from .db import list_sync_logs

_lock = threading.Lock()
# 任意一次真正打东财之间的全局间隔
_last_eastmoney_at: float = 0.0


def _parse_synced_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw[:19], fmt)
        except ValueError:
            continue
    return None


def last_sync_row(code: str) -> dict[str, Any] | None:
    rows = list_sync_logs(code=code, limit=1)
    return rows[0] if rows else None


def evaluate_sync(code: str, *, force: bool = False) -> dict[str, Any]:
    """
    判断该票是否允许立刻同步。
    返回: allowed / reason / wait_seconds / last / tip
    """
    cooldown = max(0, int(settings.sync_cooldown_seconds))
    ok_reuse = max(0, int(settings.sync_ok_reuse_seconds))
    row = last_sync_row(code)
    now = datetime.now()
    base: dict[str, Any] = {
        "code": code,
        "allowed": True,
        "reason": "ok",
        "wait_seconds": 0,
        "force_required": False,
        "last": row,
        "tip": (
            f"请勿频繁同步：同一股票冷却 {cooldown}s；"
            f"近期已成功同步建议间隔 {ok_reuse}s；批量同步票间会自动停顿。"
        ),
    }
    if force or not row:
        return base

    synced_at = _parse_synced_at(row.get("synced_at"))
    if not synced_at:
        return base

    elapsed = max(0.0, (now - synced_at).total_seconds())
    status = (row.get("status") or "").lower()

    # 刚成功拉过：默认跳过，需 force 才重打东财
    if status in ("ok", "partial") and elapsed < ok_reuse:
        wait = int(ok_reuse - elapsed) + 1
        return {
            **base,
            "allowed": False,
            "reason": "recent_ok",
            "wait_seconds": wait,
            "force_required": True,
            "tip": (
                f"{code} 约 {int(elapsed)}s 前已同步成功（{row.get('trade_date')}），"
                f"为避免打扰行情源，请 {wait}s 后再试，或确认后强制同步。"
            ),
        }

    # 任意最近一次尝试（含 fail）的短冷却，防止连点重试打爆
    if elapsed < cooldown:
        wait = int(cooldown - elapsed) + 1
        return {
            **base,
            "allowed": False,
            "reason": "cooldown",
            "wait_seconds": wait,
            "force_required": True,
            "tip": (
                f"{code} 距上次同步仅 {int(elapsed)}s，"
                f"请等待 {wait}s（冷却 {cooldown}s），勿连续点击。"
            ),
        }

    return base


def wait_eastmoney_gap() -> None:
    """两次实际请求东财之间的最小间隔（进程内）。"""
    global _last_eastmoney_at
    gap = max(0.0, float(settings.sync_request_gap_seconds))
    with _lock:
        now = time.monotonic()
        delay = gap - (now - _last_eastmoney_at)
        if delay > 0:
            time.sleep(delay)
        _last_eastmoney_at = time.monotonic()


def batch_gap_sleep() -> None:
    """批量同步相邻股票之间的停顿。"""
    gap = max(0.0, float(settings.sync_batch_gap_seconds))
    if gap > 0:
        time.sleep(gap)
