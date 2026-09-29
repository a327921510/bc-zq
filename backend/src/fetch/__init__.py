"""行情 fetch：分时日数据（腾讯→东财）+ 两融（东财）。"""

from .day import fetch_day, fetch_quote
from .eastmoney import fetch_margin_for_sync

__all__ = ["fetch_day", "fetch_quote", "fetch_margin_for_sync"]
