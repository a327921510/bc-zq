/**
 * 轻量 fetch 封装：统一错误文案，204 返回 null。
 * 路径带 Vite base（生产 /zq），与 Nginx 子路径部署对齐。
 */

/** Vite base 形如 `/zq/`，API 前缀去掉尾斜杠 → `/zq` */
const BASE = (import.meta.env.BASE_URL || "/").replace(/\/$/, "");

async function parseError(res: Response): Promise<string> {
  try {
    const j = (await res.json()) as { detail?: unknown };
    if (typeof j.detail === "string") return j.detail;
    if (j.detail != null) return JSON.stringify(j.detail);
  } catch {
    try {
      return await res.text();
    } catch {
      /* ignore */
    }
  }
  return res.statusText || `HTTP ${res.status}`;
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  // path 约定以 /api 开头；拼上 BASE 后为 /zq/api/...
  const url = path.startsWith("http") ? path : `${BASE}${path}`;
  const res = await fetch(url, options);
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  if (res.status === 204) {
    return null as T;
  }
  return res.json() as Promise<T>;
}

export function jsonBody(data: unknown): RequestInit {
  return {
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  };
}
