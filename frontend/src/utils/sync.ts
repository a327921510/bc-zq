/**
 * 手动同步公共流程：单票先问 guard，需要时确认强制；批量二次确认。
 */

import { Modal } from "antd";
import { fetchSyncGuard, postSync } from "../api";
import type { SyncResult } from "../types";
import { summarizeSyncResults } from "../utils/format";

function confirm(content: string): Promise<boolean> {
  return new Promise((resolve) => {
    Modal.confirm({
      title: "确认",
      content,
      okText: "确定",
      cancelText: "取消",
      onOk: () => resolve(true),
      onCancel: () => resolve(false),
    });
  });
}

export type RunSyncOutcome =
  | { cancelled: true; message: string }
  | { cancelled: false; results: SyncResult[]; summary: string; hasFail: boolean; hasSkipped: boolean };

export async function runSync(payload: {
  code?: string;
  all_enabled?: boolean;
  force?: boolean;
}): Promise<RunSyncOutcome> {
  let force = !!payload.force;

  if (payload.code && !force) {
    try {
      const g = await fetchSyncGuard(payload.code);
      if (!g.allowed) {
        const ok = await confirm(
          `${g.tip || "距上次同步过近"}\n\n是否强制同步？\n（仍会保留请求间隔，请勿连续强制）`,
        );
        if (!ok) {
          return { cancelled: true, message: "已取消同步（频控保护）" };
        }
        force = true;
      }
    } catch {
      /* guard 失败时仍允许尝试同步 */
    }
  }

  if (payload.all_enabled && !force) {
    const ok = await confirm(
      "将同步全部启用股票。\n• 票与票之间自动停顿\n• 近期已成功同步的会跳过（避免打扰行情源）\n• 需要重拉某票请单独同步并确认强制\n\n继续？",
    );
    if (!ok) {
      return { cancelled: true, message: "已取消批量同步" };
    }
  }

  const data = await postSync({ ...payload, force });
  const results = data.results || [];
  return {
    cancelled: false,
    results,
    summary: summarizeSyncResults(results),
    hasFail: results.some((r) => r.status === "fail"),
    hasSkipped: results.some((r) => r.status === "skipped"),
  };
}
