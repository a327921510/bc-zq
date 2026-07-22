"""东财原始行情 → 本地结构：明细解析、分钟聚合、分价汇总。

不依赖网络；供 fetch / sync / 降级路径（无 trends 时用 ticks 合成分钟）复用。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

# A 股连续竞价时段（含端点）；集合竞价明细可能早于 09:30，画分时图时排除
MORNING = ("09:30", "11:30")
AFTERNOON = ("13:00", "15:00")


def _hhmm_to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def trading_minutes() -> list[str]:
    """生成连续竞价分钟轴（含 09:30/11:30/13:00/15:00），共 242 点。"""
    out: list[str] = []
    for start, end in (MORNING, AFTERNOON):
        for total in range(_hhmm_to_min(start), _hhmm_to_min(end) + 1):
            out.append(f"{total // 60:02d}:{total % 60:02d}")
    return out


def map_side(raw: Any) -> str:
    """东财 details 方向码 → 统一 B/S/N。

    约定：1=买盘，2=卖盘；其余（含集合竞价 4 等）记为中性 N。
    """
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return "N"
    if v == 1:
        return "B"
    if v == 2:
        return "S"
    return "N"


def parse_details(raw_lines: list[str]) -> list[dict[str, Any]]:
    """解析东财成交明细行：`时间,价,量,笔数?,方向`。

    volume 为手；amount 按 价×量×100（股）估算，接口本身不给金额时用。
    """
    ticks: list[dict[str, Any]] = []
    for i, line in enumerate(raw_lines):
        parts = line.split(",")
        if len(parts) < 3:
            continue
        time_s = parts[0].strip()
        price = float(parts[1])
        volume = float(parts[2])
        side = map_side(parts[4] if len(parts) > 4 else None)
        # 1 手 = 100 股
        amount = round(price * volume * 100, 2)
        ticks.append(
            {
                "seq": i,
                "time": time_s,
                "price": price,
                "volume": volume,
                "amount": amount,
                "side": side,
            }
        )
    return ticks


def _in_session(minute: str) -> bool:
    m = minute[:5]
    return MORNING[0] <= m <= MORNING[1] or AFTERNOON[0] <= m <= AFTERNOON[1]


def parse_trends(raw_lines: list[str]) -> tuple[str | None, list[dict[str, Any]]]:
    """解析东财 trends2 分时行。

    当日格式：`YYYY-MM-DD HH:MM,open,close,high,low,volume,amount,avg`
    多日历史偶发 close=0，此时回退用 avg 作为画图价。
    """
    minutes: list[dict[str, Any]] = []
    trade_date: str | None = None
    for line in raw_lines:
        parts = line.split(",")
        if len(parts) < 7:
            continue
        dt = parts[0].strip()
        if " " not in dt:
            continue
        date_s, minute = dt.split(" ", 1)
        minute = minute[:5]
        if not _in_session(minute):
            continue
        trade_date = trade_date or date_s
        close_p = float(parts[2]) if parts[2] not in ("", "-") else 0.0
        avg_p = float(parts[7]) if len(parts) > 7 and parts[7] not in ("", "-") else 0.0
        # close 为 0 时用均价兜底（历史 ndays 常见）
        price = close_p or avg_p
        minutes.append(
            {
                "minute": minute,
                "price": price,
                "volume": float(parts[5]),
                "amount": float(parts[6]),
            }
        )
    return trade_date, minutes


def minutes_from_ticks(ticks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """明细降级合成 1 分钟序列：分钟末价 + 量求和，空分钟前向填充价、量记 0。

    用于 trends 接口失败但仍有 details 时，保证回放页仍有分时线。
    """
    buckets: dict[str, dict[str, float]] = {}
    for t in ticks:
        time_s = t["time"]
        if len(time_s) < 5:
            continue
        minute = time_s[:5]
        if not _in_session(minute):
            continue
        b = buckets.setdefault(minute, {"price": 0.0, "volume": 0.0, "amount": 0.0})
        # ticks 已按时间序；同分钟内后写覆盖 → 分钟末价
        b["price"] = float(t["price"])
        b["volume"] += float(t["volume"])
        b["amount"] += float(t.get("amount") or 0.0)

    out: list[dict[str, Any]] = []
    last_price: float | None = None
    for m in trading_minutes():
        if m in buckets:
            last_price = buckets[m]["price"]
            out.append(
                {
                    "minute": m,
                    "price": buckets[m]["price"],
                    "volume": buckets[m]["volume"],
                    "amount": buckets[m]["amount"],
                }
            )
        elif last_price is not None:
            out.append(
                {
                    "minute": m,
                    "price": last_price,
                    "volume": 0.0,
                    "amount": 0.0,
                }
            )
    return out


def price_volume_from_ticks(ticks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """内存版分价汇总（与 SQL GROUP BY price 同口径，便于单测）。"""
    agg: dict[float, float] = defaultdict(float)
    for t in ticks:
        agg[float(t["price"])] += float(t["volume"])
    return [{"price": p, "volume": v} for p, v in sorted(agg.items())]
