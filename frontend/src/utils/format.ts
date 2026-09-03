/** 数值与同步结果的展示格式化。 */

import type { SyncResult } from "../types";

export function fmt(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return "-";
  return Number(n).toFixed(digits);
}

/** 金额（元）→ 亿元展示；两融余额常用。 */
export function fmtYi(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return "-";
  return `${(Number(n) / 1e8).toFixed(digits)}亿`;
}

export function sideLabel(side: string | null | undefined): string {
  if (side === "B") return "买";
  if (side === "S") return "卖";
  return "中";
}

export function isEnabled(v: number | boolean | undefined): boolean {
  return v === true || v === 1;
}

export function summarizeSyncResults(results: SyncResult[] | null | undefined): string {
  return (results || [])
    .map(
      (r) =>
        `${r.code} ${r.trade_date || ""} → ${r.status}` +
        (r.tick_count != null ? ` ticks=${r.tick_count}` : "") +
        (r.message ? ` (${String(r.message).slice(0, 80)})` : ""),
    )
    .join("；");
}

/** 将分钟点转为图表 category / 价 / 量序列（午休不插断点，线连续）。 */
export function toChartSeries(
  minutes: { minute: string; price: number; volume: number }[],
): { cats: string[]; prices: number[]; vols: number[] } {
  return {
    cats: minutes.map((m) => m.minute),
    prices: minutes.map((m) => m.price),
    vols: minutes.map((m) => m.volume),
  };
}
