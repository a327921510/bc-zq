/**
 * 与后端 API 对齐的类型定义（字段名保持 snake_case，便于直接消费 JSON）。
 */

export interface SymbolItem {
  code: string;
  name: string;
  market: string;
  enabled: number | boolean;
}

export interface DailySummary {
  code: string;
  trade_date: string;
  pre_close: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  amount: number | null;
}

export interface MinutePoint {
  code?: string;
  trade_date?: string;
  minute: string;
  price: number;
  volume: number;
  amount?: number | null;
}

export interface TickItem {
  code?: string;
  trade_date?: string;
  seq?: number;
  time: string;
  price: number;
  volume: number;
  amount?: number | null;
  side?: string | null;
}

export interface PriceVolumeItem {
  price: number;
  volume: number;
}

export interface SyncLogItem {
  code: string;
  trade_date: string;
  status: string;
  tick_count: number | null;
  minute_count: number | null;
  message: string | null;
  synced_at: string;
}

/** 个股单日融资融券（东财 datacenter）；金额单位为元。 */
export interface MarginDaily {
  code: string;
  trade_date: string;
  rzye: number | null;
  rzmre: number | null;
  rzche: number | null;
  rzjme: number | null;
  rqye: number | null;
  rqyl: number | null;
  rqmcl: number | null;
  rqchl: number | null;
  rzrqye: number | null;
  rzyezb: number | null;
  synced_at?: string;
}

export interface SyncResult {
  code: string;
  trade_date?: string | null;
  status: string;
  tick_count?: number | null;
  minute_count?: number | null;
  message?: string | null;
  name?: string | null;
  margin_count?: number | null;
  wait_seconds?: number;
  force_required?: boolean;
}

export interface SyncGuard {
  allowed: boolean;
  tip?: string;
  force_required?: boolean;
  wait_seconds?: number;
  last?: SyncLogItem | null;
}

export interface DayPayload {
  code: string;
  date: string;
  summary: DailySummary | null;
  minutes: MinutePoint[];
  ticks: TickItem[];
  price_volume: PriceVolumeItem[];
  margin: MarginDaily | null;
  sync: SyncLogItem | null;
}
