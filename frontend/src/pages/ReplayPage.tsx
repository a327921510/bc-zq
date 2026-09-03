/**
 * 分时复盘：选股/选日 → 摘要条 + 价量图 + 分价/成交明细。
 * 对应原单页主视图能力。
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Typography,
} from "antd";
import {
  LeftOutlined,
  ReloadOutlined,
  RightOutlined,
} from "@ant-design/icons";
import dayjs, { type Dayjs } from "dayjs";
import { fetchDay, fetchDays, fetchSymbols } from "../api";
import IntradayCharts from "../components/IntradayCharts";
import type { DayPayload, SymbolItem } from "../types";
import { fmt, fmtYi, isEnabled, sideLabel } from "../utils/format";

const { Text } = Typography;
const DATE_FMT = "YYYY-MM-DD";

export default function ReplayPage() {
  const [symbols, setSymbols] = useState<SymbolItem[]>([]);
  const [code, setCode] = useState<string>();
  const [datesAsc, setDatesAsc] = useState<string[]>([]);
  const [date, setDate] = useState<string>();
  const [day, setDay] = useState<DayPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("");

  const enabledSymbols = useMemo(
    () => symbols.filter((s) => isEnabled(s.enabled)),
    [symbols],
  );

  const currentName = useMemo(() => {
    const s = symbols.find((x) => x.code === code);
    return s?.name ?? "";
  }, [symbols, code]);

  const loadSymbols = useCallback(async () => {
    const list = await fetchSymbols();
    setSymbols(list);
    const enabled = list.filter((s) => isEnabled(s.enabled));
    const next =
      (code && enabled.some((s) => s.code === code) && code) || enabled[0]?.code;
    setCode(next);
    return next;
  }, [code]);

  const loadDates = useCallback(async (sym: string) => {
    const data = await fetchDays(sym);
    const asc = [...(data.dates || [])].sort();
    setDatesAsc(asc);
    if (!asc.length) {
      setDate(undefined);
      setDay(null);
      setError("暂无已归档交易日，请到「同步管理」手动同步");
      return null;
    }
    setError(null);
    const keep = date && asc.includes(date) ? date : asc[asc.length - 1];
    setDate(keep);
    return keep;
  }, [date]);

  const loadDayData = useCallback(async (sym: string, d: string) => {
    setLoading(true);
    setStatus("加载中…");
    try {
      const payload = await fetchDay(sym, d);
      setDay(payload);
      const sync = payload.sync;
      setStatus(
        sync
          ? `同步 ${sync.status} · ticks ${sync.tick_count} · minutes ${sync.minute_count}`
          : "已加载",
      );
      setError(null);
    } catch (e) {
      setDay(null);
      setError(String((e as Error).message || e));
      setStatus("失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const sym = await loadSymbols();
        if (!sym) {
          setError("无启用股票，请到「关注股票」添加");
          return;
        }
        const d = await loadDates(sym);
        if (d) await loadDayData(sym, d);
      } catch (e) {
        setError(String((e as Error).message || e));
      }
    })();
    // 仅首屏初始化
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onSymbolChange = async (next: string) => {
    setCode(next);
    try {
      const d = await loadDates(next);
      if (d) await loadDayData(next, d);
    } catch (e) {
      setError(String((e as Error).message || e));
    }
  };

  const onDateChange = async (next: string) => {
    setDate(next);
    if (code) await loadDayData(code, next);
  };

  const shiftDay = async (delta: number) => {
    if (!datesAsc.length || !date) return;
    let i = datesAsc.indexOf(date);
    if (i < 0) i = datesAsc.length - 1;
    i = Math.min(datesAsc.length - 1, Math.max(0, i + delta));
    await onDateChange(datesAsc[i]);
  };

  const reload = async () => {
    if (code && date) await loadDayData(code, date);
  };

  const summary = day?.summary;
  const chg =
    summary?.close != null && summary?.pre_close
      ? summary.close - summary.pre_close
      : null;
  const pct =
    chg != null && summary?.pre_close ? (chg / summary.pre_close) * 100 : null;
  const upColor = chg != null && chg >= 0 ? "#cf1322" : "#389e0d";

  // 仅已归档交易日可选；用 Set 供 DatePicker.disabledDate 快速判断
  const archivedDateSet = useMemo(() => new Set(datesAsc), [datesAsc]);

  const pvRows = useMemo(
    () => [...(day?.price_volume || [])].reverse(),
    [day],
  );
  const tickRows = useMemo(() => [...(day?.ticks || [])].reverse(), [day]);

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card size="small">
        <Space wrap>
          <Select
            style={{ width: 200 }}
            value={code}
            placeholder="选择股票"
            options={enabledSymbols.map((s) => ({
              value: s.code,
              label: `${s.code} ${s.name}`,
            }))}
            onChange={onSymbolChange}
          />
          <DatePicker
            style={{ width: 150 }}
            value={date ? dayjs(date) : null}
            placeholder="交易日"
            allowClear={false}
            disabled={!archivedDateSet.size}
            disabledDate={(d: Dayjs) => !archivedDateSet.has(d.format(DATE_FMT))}
            onChange={(d) => {
              if (d) void onDateChange(d.format(DATE_FMT));
            }}
          />
          <Button icon={<LeftOutlined />} onClick={() => shiftDay(-1)} disabled={!date}>
            上一交易日
          </Button>
          <Button icon={<RightOutlined />} onClick={() => shiftDay(1)} disabled={!date}>
            下一交易日
          </Button>
          <Button icon={<ReloadOutlined />} loading={loading} onClick={reload}>
            刷新
          </Button>
          <Text type="secondary">{status}</Text>
        </Space>
      </Card>

      {error ? <Alert type="warning" showIcon message={error} /> : null}

      <Card size="small">
        <Row gutter={[16, 8]}>
          <Col>
            <Statistic title="标的" value={`${code || "-"} ${currentName}`} />
          </Col>
          <Col>
            <Statistic title="昨收" value={fmt(summary?.pre_close)} />
          </Col>
          <Col>
            <Statistic title="开" value={fmt(summary?.open)} />
          </Col>
          <Col>
            <Statistic title="高" value={fmt(summary?.high)} valueStyle={{ color: "#cf1322" }} />
          </Col>
          <Col>
            <Statistic title="低" value={fmt(summary?.low)} valueStyle={{ color: "#389e0d" }} />
          </Col>
          <Col>
            <Statistic title="收" value={fmt(summary?.close)} valueStyle={{ color: upColor }} />
          </Col>
          <Col>
            <Statistic
              title="涨跌"
              value={
                chg == null
                  ? "-"
                  : `${chg >= 0 ? "+" : ""}${fmt(chg)} (${pct != null ? `${pct >= 0 ? "+" : ""}${fmt(pct)}%` : ""})`
              }
              valueStyle={{ color: upColor, fontSize: 18 }}
            />
          </Col>
          <Col>
            <Statistic
              title="量(手)"
              value={summary?.volume != null ? Math.round(summary.volume).toLocaleString() : "-"}
            />
          </Col>
          <Col>
            <Statistic
              title="额"
              value={
                summary?.amount != null ? `${(summary.amount / 1e8).toFixed(2)}亿` : "-"
              }
            />
          </Col>
        </Row>
      </Card>

      {day?.margin ? (
        <Card size="small" title="融资融券">
          <Row gutter={[16, 8]}>
            <Col>
              <Statistic title="融资余额" value={fmtYi(day.margin.rzye)} />
            </Col>
            <Col>
              <Statistic title="融资买入" value={fmtYi(day.margin.rzmre)} />
            </Col>
            <Col>
              <Statistic
                title="融资净买"
                value={fmtYi(day.margin.rzjme)}
                valueStyle={{
                  color:
                    day.margin.rzjme == null
                      ? undefined
                      : day.margin.rzjme >= 0
                        ? "#cf1322"
                        : "#389e0d",
                }}
              />
            </Col>
            <Col>
              <Statistic title="融券余额" value={fmtYi(day.margin.rqye)} />
            </Col>
            <Col>
              <Statistic
                title="融券余量"
                value={
                  day.margin.rqyl != null
                    ? Math.round(day.margin.rqyl).toLocaleString()
                    : "-"
                }
              />
            </Col>
            <Col>
              <Statistic title="两融余额" value={fmtYi(day.margin.rzrqye)} />
            </Col>
            <Col>
              <Statistic
                title="融资占流通%"
                value={day.margin.rzyezb != null ? fmt(day.margin.rzyezb) : "-"}
              />
            </Col>
          </Row>
        </Card>
      ) : day ? (
        <Alert
          type="info"
          showIcon
          message="当日暂无两融数据（通常次日 10:10 计划任务补拉；交易所约上午才公布）"
        />
      ) : null}

      <Row gutter={16}>
        <Col xs={24} lg={16}>
          <Card size="small" title="分时图" styles={{ body: { padding: 8 } }}>
            <IntradayCharts
              minutes={day?.minutes || []}
              preClose={summary?.pre_close}
            />
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card
            size="small"
            title="分价"
            styles={{ body: { padding: 0, maxHeight: 280, overflow: "auto" } }}
            style={{ marginBottom: 16 }}
          >
            <Table
              size="small"
              pagination={false}
              rowKey={(r) => String(r.price)}
              dataSource={pvRows}
              columns={[
                { title: "价格", dataIndex: "price", render: (v: number) => fmt(v) },
                {
                  title: "成交量(手)",
                  dataIndex: "volume",
                  align: "right",
                  render: (v: number) => Math.round(v).toLocaleString(),
                },
              ]}
            />
          </Card>
          <Card
            size="small"
            title="成交明细"
            styles={{ body: { padding: 0, maxHeight: 320, overflow: "auto" } }}
          >
            <Table
              size="small"
              pagination={false}
              rowKey={(_, i) => String(i)}
              dataSource={tickRows}
              columns={[
                { title: "时间", dataIndex: "time", width: 80 },
                {
                  title: "价格",
                  dataIndex: "price",
                  render: (v: number, r) => (
                    <span
                      style={{
                        color:
                          r.side === "B" ? "#cf1322" : r.side === "S" ? "#389e0d" : undefined,
                      }}
                    >
                      {fmt(v)}
                    </span>
                  ),
                },
                {
                  title: "量",
                  dataIndex: "volume",
                  align: "right",
                  render: (v: number) => Math.round(v),
                },
                {
                  title: "方向",
                  dataIndex: "side",
                  width: 48,
                  render: (s: string) => (
                    <span
                      style={{
                        color: s === "B" ? "#cf1322" : s === "S" ? "#389e0d" : undefined,
                      }}
                    >
                      {sideLabel(s)}
                    </span>
                  ),
                },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </Space>
  );
}
