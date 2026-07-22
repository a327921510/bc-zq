/**
 * 业务 API：关注股 / 同步 / 回放读档。
 */

import { api, jsonBody } from "./client";
import type {
  DayPayload,
  SyncGuard,
  SyncLogItem,
  SyncResult,
  SymbolItem,
} from "../types";

export function fetchSymbols(enabledOnly = false) {
  const q = enabledOnly ? "?enabled_only=true" : "";
  return api<SymbolItem[]>(`/api/symbols${q}`);
}

export function createSymbol(payload: {
  code: string;
  name?: string | null;
  market?: string | null;
  sync_now?: boolean;
}) {
  return api<{ symbol: SymbolItem; sync: SyncResult | null }>("/api/symbols", {
    method: "POST",
    ...jsonBody(payload),
  });
}

export function patchSymbol(
  code: string,
  payload: { name?: string; market?: string; enabled?: boolean },
) {
  return api<SymbolItem>(`/api/symbols/${encodeURIComponent(code)}`, {
    method: "PATCH",
    ...jsonBody(payload),
  });
}

export function deleteSymbol(code: string, purgeData: boolean) {
  return api<{ ok: boolean; code: string; purged: boolean }>(
    `/api/symbols/${encodeURIComponent(code)}?purge_data=${purgeData ? "true" : "false"}`,
    { method: "DELETE" },
  );
}

export function fetchSyncLogs(code?: string, limit = 80) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (code) params.set("code", code);
  return api<{ items: SyncLogItem[] }>(`/api/sync/logs?${params}`);
}

export function fetchSyncGuard(code: string) {
  return api<SyncGuard>(`/api/sync/guard?code=${encodeURIComponent(code)}`);
}

export function postSync(payload: {
  code?: string;
  all_enabled?: boolean;
  force?: boolean;
}) {
  return api<{ results: SyncResult[] }>("/api/sync", {
    method: "POST",
    ...jsonBody(payload),
  });
}

export function fetchDays(code: string) {
  return api<{ code: string; dates: string[] }>(
    `/api/days?code=${encodeURIComponent(code)}`,
  );
}

export function fetchDay(code: string, date: string) {
  return api<DayPayload>(
    `/api/day?code=${encodeURIComponent(code)}&date=${encodeURIComponent(date)}`,
  );
}
