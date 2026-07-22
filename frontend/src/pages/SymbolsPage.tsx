/**
 * 关注股票管理：增删、启停；添加时可立刻同步当日。
 */

import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  message,
} from "antd";
import {
  createSymbol,
  deleteSymbol,
  fetchSymbols,
  patchSymbol,
  postSync,
} from "../api";
import type { SymbolItem } from "../types";
import { isEnabled, summarizeSyncResults } from "../utils/format";

export default function SymbolsPage() {
  const [list, setList] = useState<SymbolItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm();

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setList(await fetchSymbols());
    } catch (e) {
      message.error(String((e as Error).message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onAdd = async () => {
    const values = await form.validateFields();
    const code = String(values.code || "").trim();
    if (!/^\d{6}$/.test(code)) {
      message.error("请输入 6 位股票代码");
      return;
    }
    setSubmitting(true);
    try {
      const data = await createSymbol({
        code,
        name: values.name?.trim() || null,
        market: values.market || null,
        sync_now: true,
      });
      let sync = data.sync;
      if (sync && sync.status === "skipped" && sync.force_required) {
        const ok = await new Promise<boolean>((resolve) => {
          Modal.confirm({
            title: "强制同步？",
            content: sync?.message || "距上次同步过近",
            onOk: () => resolve(true),
            onCancel: () => resolve(false),
          });
        });
        if (ok) {
          const forced = await postSync({ code, force: true });
          sync = (forced.results || [])[0] || sync;
        }
      }
      const text = sync ? summarizeSyncResults([sync]) : `已添加 ${code}`;
      if (sync?.status === "fail") message.error(text);
      else message.success(text);
      form.resetFields();
      await refresh();
    } catch (e) {
      message.error(String((e as Error).message || e));
    } finally {
      setSubmitting(false);
    }
  };

  const onToggle = async (row: SymbolItem) => {
    try {
      await patchSymbol(row.code, { enabled: !isEnabled(row.enabled) });
      message.success(`${row.code} 已更新`);
      await refresh();
    } catch (e) {
      message.error(String((e as Error).message || e));
    }
  };

  const onDelete = async (row: SymbolItem) => {
    // 两步确认对齐原逻辑：先确认删除，再选是否 purge 归档
    const go = await new Promise<boolean>((resolve) => {
      Modal.confirm({
        title: `从关注列表删除 ${row.code}？`,
        okText: "继续",
        cancelText: "取消",
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });
    if (!go) return;

    const purge = await new Promise<boolean>((resolve) => {
      Modal.confirm({
        title: `是否同时清空 ${row.code} 已归档的分时/明细？`,
        content: "确定 = 清空归档；取消 = 仅移除关注，保留数据",
        okText: "清空归档",
        cancelText: "仅移除关注",
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });

    try {
      await deleteSymbol(row.code, purge);
      message.success(`已删除 ${row.code}${purge ? "（含归档）" : ""}`);
      await refresh();
    } catch (e) {
      message.error(String((e as Error).message || e));
    }
  };

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card title="添加关注" size="small">
        <Form form={form} layout="inline" onFinish={onAdd}>
          <Form.Item
            name="code"
            rules={[
              { required: true, message: "请输入代码" },
              { pattern: /^\d{6}$/, message: "6 位数字" },
            ]}
          >
            <Input placeholder="代码 002594" maxLength={6} style={{ width: 120 }} />
          </Form.Item>
          <Form.Item name="name">
            <Input placeholder="名称（可空）" style={{ width: 140 }} />
          </Form.Item>
          <Form.Item name="market">
            <Select
              allowClear
              placeholder="市场自动"
              style={{ width: 120 }}
              options={[
                { value: "SZ", label: "SZ" },
                { value: "SH", label: "SH" },
                { value: "BJ", label: "BJ" },
              ]}
            />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={submitting}>
              添加并同步
            </Button>
          </Form.Item>
        </Form>
      </Card>

      <Card title="关注列表" size="small">
        <Table
          rowKey="code"
          loading={loading}
          dataSource={list}
          pagination={false}
          columns={[
            { title: "代码", dataIndex: "code", width: 100 },
            { title: "名称", dataIndex: "name" },
            { title: "市场", dataIndex: "market", width: 80 },
            {
              title: "启用",
              dataIndex: "enabled",
              width: 90,
              render: (v: number | boolean) =>
                isEnabled(v) ? <Tag color="success">是</Tag> : <Tag>否</Tag>,
            },
            {
              title: "操作",
              width: 180,
              render: (_, row) => (
                <Space>
                  <Button size="small" onClick={() => onToggle(row)}>
                    {isEnabled(row.enabled) ? "停用" : "启用"}
                  </Button>
                  <Button size="small" danger onClick={() => onDelete(row)}>
                    删除
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      </Card>
    </Space>
  );
}
