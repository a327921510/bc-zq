/**
 * 同步管理：手动同步当前/全部 + 同步历史。
 * 频控与强制同步逻辑与原抽屉一致。
 */

import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { fetchSymbols, fetchSyncLogs } from "../api";
import type { SyncLogItem, SymbolItem } from "../types";
import { isEnabled } from "../utils/format";
import { runSync } from "../utils/sync";

const { Paragraph, Text } = Typography;

function statusTag(status: string) {
  const map: Record<string, string> = {
    ok: "success",
    fail: "error",
    partial: "warning",
    skipped: "default",
  };
  return <Tag color={map[status] || "processing"}>{status}</Tag>;
}

export default function SyncPage() {
  const [symbols, setSymbols] = useState<SymbolItem[]>([]);
  const [code, setCode] = useState<string>();
  const [filterCode, setFilterCode] = useState<string | undefined>();
  const [logs, setLogs] = useState<SyncLogItem[]>([]);
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<{ text: string; type?: "success" | "error" | "info" } | null>(
    null,
  );

  const refreshSymbols = useCallback(async () => {
    const list = await fetchSymbols();
    setSymbols(list);
    const enabled = list.filter((s) => isEnabled(s.enabled));
    setCode((prev) => {
      if (prev && enabled.some((s) => s.code === prev)) return prev;
      return enabled[0]?.code;
    });
  }, []);

  const refreshLogs = useCallback(async () => {
    setLoadingLogs(true);
    try {
      const data = await fetchSyncLogs(filterCode, 80);
      setLogs(data.items || []);
    } catch (e) {
      message.error(String((e as Error).message || e));
    } finally {
      setLoadingLogs(false);
    }
  }, [filterCode]);

  useEffect(() => {
    void refreshSymbols().catch((e) => message.error(String(e.message || e)));
  }, [refreshSymbols]);

  useEffect(() => {
    void refreshLogs();
  }, [refreshLogs]);

  const doSync = async (payload: { code?: string; all_enabled?: boolean }) => {
    setSyncing(true);
    setSyncMsg({ text: "同步中，请稍候（票间有停顿）…", type: "info" });
    try {
      const outcome = await runSync(payload);
      if (outcome.cancelled) {
        setSyncMsg({ text: outcome.message, type: "error" });
        return;
      }
      setSyncMsg({
        text: outcome.summary,
        type: outcome.hasFail ? "error" : outcome.hasSkipped ? "info" : "success",
      });
      if (outcome.hasFail) message.error("同步存在失败项");
      else if (!outcome.hasSkipped) message.success("同步完成");
      await refreshLogs();
      await refreshSymbols();
    } catch (e) {
      const tip = String((e as Error).message || e);
      setSyncMsg({ text: tip, type: "error" });
      message.error(tip);
    } finally {
      setSyncing(false);
    }
  };

  const enabledOptions = symbols
    .filter((s) => isEnabled(s.enabled))
    .map((s) => ({ value: s.code, label: `${s.code} ${s.name}` }));

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card title="手动同步" size="small">
        <Paragraph type="secondary" style={{ marginBottom: 12 }}>
          免费源只能拉<strong>当前交易日会话</strong>。请勿频繁点击：同一股票冷却约 2
          分钟；若近期已成功同步，默认 10 分钟内跳过（可确认后强制）。批量同步票间会自动停顿，降低被行情源限流风险。
        </Paragraph>
        <Space wrap>
          <Select
            style={{ width: 200 }}
            placeholder="当前股票"
            value={code}
            options={enabledOptions}
            onChange={setCode}
          />
          <Button
            type="primary"
            loading={syncing}
            onClick={() => {
              if (!code) {
                message.warning("请先选择股票");
                return;
              }
              void doSync({ code });
            }}
          >
            同步当前股票
          </Button>
          <Button loading={syncing} onClick={() => void doSync({ all_enabled: true })}>
            同步全部启用
          </Button>
        </Space>
        {syncMsg ? (
          <Alert
            style={{ marginTop: 12 }}
            type={syncMsg.type === "error" ? "error" : syncMsg.type === "success" ? "success" : "info"}
            showIcon
            message={<Text style={{ wordBreak: "break-all" }}>{syncMsg.text}</Text>}
          />
        ) : null}
      </Card>

      <Card
        title="同步历史"
        size="small"
        extra={
          <Space>
            <Select
              allowClear
              placeholder="全部股票"
              style={{ width: 180 }}
              value={filterCode}
              options={symbols.map((s) => ({
                value: s.code,
                label: `${s.code} ${s.name}`,
              }))}
              onChange={(v) => setFilterCode(v)}
            />
            <Button onClick={() => void refreshLogs()}>刷新日志</Button>
          </Space>
        }
      >
        <Table
          rowKey={(r) => `${r.code}-${r.trade_date}-${r.synced_at}`}
          loading={loadingLogs}
          dataSource={logs}
          size="small"
          pagination={{ pageSize: 20 }}
          columns={[
            { title: "时间", dataIndex: "synced_at", width: 170 },
            { title: "代码", dataIndex: "code", width: 90 },
            { title: "交易日", dataIndex: "trade_date", width: 110 },
            {
              title: "状态",
              dataIndex: "status",
              width: 90,
              render: (s: string) => statusTag(s),
            },
            { title: "ticks", dataIndex: "tick_count", width: 80 },
            { title: "minutes", dataIndex: "minute_count", width: 90 },
            {
              title: "说明",
              dataIndex: "message",
              ellipsis: true,
              render: (m: string | null) => m || "-",
            },
          ]}
        />
      </Card>
    </Space>
  );
}
