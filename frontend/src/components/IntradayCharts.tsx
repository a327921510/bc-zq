/**
 * 分时价量图：ECharts 双图；涨跌色与 A 股习惯一致（红涨绿跌）。
 */

import { useMemo } from "react";
import ReactECharts from "echarts-for-react";
import type { MinutePoint } from "../types";
import { toChartSeries } from "../utils/format";

const AXIS_LABEL_TIMES = new Set(["09:30", "10:30", "11:30", "13:00", "14:00", "15:00"]);

interface Props {
  minutes: MinutePoint[];
  preClose: number | null | undefined;
  heightPrice?: number;
  heightVol?: number;
}

export default function IntradayCharts({
  minutes,
  preClose,
  heightPrice = 360,
  heightVol = 160,
}: Props) {
  const { cats, prices, vols } = useMemo(() => toChartSeries(minutes), [minutes]);

  const priceOption = useMemo(
    () => ({
      animation: false,
      grid: { left: 56, right: 24, top: 28, bottom: 28 },
      tooltip: { trigger: "axis" as const },
      xAxis: {
        type: "category" as const,
        data: cats,
        axisLabel: {
          interval: (_i: number, v: string) => AXIS_LABEL_TIMES.has(v),
        },
      },
      yAxis: {
        type: "value" as const,
        scale: true,
        splitLine: { show: true },
      },
      series: [
        {
          type: "line" as const,
          data: prices,
          showSymbol: false,
          lineStyle: { width: 1.5, color: "#1677ff" },
          markLine:
            preClose == null
              ? undefined
              : {
                  silent: true,
                  symbol: "none" as const,
                  lineStyle: { type: "dashed" as const, color: "#8c8c8c" },
                  data: [{ yAxis: preClose }],
                  label: { formatter: "昨收", color: "#8c8c8c" },
                },
        },
      ],
    }),
    [cats, prices, preClose],
  );

  const volOption = useMemo(
    () => ({
      animation: false,
      grid: { left: 56, right: 24, top: 12, bottom: 28 },
      tooltip: { trigger: "axis" as const },
      xAxis: {
        type: "category" as const,
        data: cats,
        axisLabel: {
          interval: (_i: number, v: string) => AXIS_LABEL_TIMES.has(v),
        },
      },
      yAxis: {
        type: "value" as const,
        axisLabel: {
          formatter: (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(1)}万` : String(v)),
        },
      },
      series: [
        {
          type: "bar" as const,
          barWidth: "60%",
          data: vols.map((v, i) => {
            const p = prices[i];
            const prev = i > 0 ? prices[i - 1] : p;
            const up = p >= prev;
            return {
              value: v,
              itemStyle: { color: up ? "rgba(207, 19, 34, 0.55)" : "rgba(56, 158, 13, 0.55)" },
            };
          }),
        },
      ],
    }),
    [cats, prices, vols],
  );

  return (
    <div>
      <ReactECharts option={priceOption} style={{ height: heightPrice }} notMerge />
      <ReactECharts option={volOption} style={{ height: heightVol }} notMerge />
    </div>
  );
}
