"""东财 fetch 包入口。"""

from .eastmoney import fetch_day, fetch_margin_for_sync

__all__ = ["fetch_day", "fetch_margin_for_sync"]
