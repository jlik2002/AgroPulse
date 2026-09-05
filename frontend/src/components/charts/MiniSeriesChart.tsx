import type { EChartsOption } from "echarts";
import { useMemo } from "react";

import type { Anomaly, Observation } from "@/api/types";
import { CHART, TOOLTIP_BASE } from "@/components/charts/echarts";
import { EChart } from "@/components/charts/EChart";
import { formatDayMonth, formatNumber, parseDate } from "@/lib/format";

type Metric = "ndmi" | "temperature" | "precipitation";

interface MiniSeriesChartProps {
  observations: Observation[];
  metric: Metric;
  anomalies?: Anomaly[];
  today?: string | null;
  height?: number;
}

const METRICS: Record<
  Metric,
  { color: string; kind: "line" | "bar"; digits: number; unit: string; min?: number; max?: number }
> = {
  ndmi: { color: CHART.colors.ndmi, kind: "line", digits: 2, unit: "", min: 0, max: 1 },
  temperature: { color: CHART.colors.temp, kind: "line", digits: 0, unit: "°C" },
  precipitation: { color: CHART.colors.precip, kind: "bar", digits: 0, unit: " мм", min: 0 },
};

/** Небольшие графики погодного контекста под основным: NDMI, температура,
 *  осадки. Ось времени у них общая с NDVI — так видно совпадение событий. */
export function MiniSeriesChart({
  observations,
  metric,
  anomalies = [],
  today,
  height = 128,
}: MiniSeriesChartProps) {
  const option = useMemo<EChartsOption>(() => {
    const config = METRICS[metric];
    const x = (value: string) => parseDate(value).getTime();

    const data = [...observations]
      .sort((a, b) => a.date.localeCompare(b.date))
      .map((point) => {
        const value =
          metric === "ndmi"
            ? point.ndmi_mean
            : metric === "temperature"
              ? point.temperature
              : point.precipitation;
        return [x(point.date), value];
      })
      .filter(([, value]) => value !== null && value !== undefined);

    const markAreas = anomalies.map((anomaly) => [
      {
        xAxis: x(anomaly.start_date),
        itemStyle: { color: CHART.colors.anomaly },
        label: { show: false },
      },
      { xAxis: x(anomaly.end_date), label: { show: false } },
    ]);

    const markLines = [
      ...anomalies.flatMap((anomaly) => [
        {
          xAxis: x(anomaly.start_date),
          lineStyle: { color: CHART.colors.anomalyEdge, type: "dashed" as const, width: 1.2 },
          label: { show: false },
        },
        {
          xAxis: x(anomaly.end_date),
          lineStyle: { color: CHART.colors.anomalyEdge, type: "dashed" as const, width: 1.2 },
          label: { show: false },
        },
      ]),
      ...(today
        ? [
            {
              xAxis: x(today),
              lineStyle: { color: CHART.colors.today, type: "dashed" as const, width: 1.2 },
              label: { show: false },
            },
          ]
        : []),
    ];

    return {
      animationDuration: 300,
      grid: { left: 34, right: 10, top: 12, bottom: 24, containLabel: false },
      tooltip: {
        ...TOOLTIP_BASE,
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: "#C9CDD4", width: 1 } },
        formatter: (params: unknown) => {
          const items = params as { axisValue: number; value: [number, number] }[];
          const item = items?.[0];
          if (!item) return "";
          return `<div style="font-weight:600;margin-bottom:4px">${formatDayMonth(new Date(item.axisValue))}</div>${formatNumber(item.value[1], config.digits)}${config.unit}`;
        },
      },
      xAxis: {
        type: "time",
        axisLabel: {
          ...CHART.axisLabel,
          fontSize: 11,
          hideOverlap: true,
          formatter: (value: number) => formatDayMonth(new Date(value)),
        },
        axisLine: { show: true, lineStyle: CHART.axisLine.lineStyle },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        min: config.min,
        max: config.max,
        splitNumber: 2,
        axisLabel: {
          ...CHART.axisLabel,
          fontSize: 11,
          formatter: (value: number) => formatNumber(value, config.digits),
        },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: true, lineStyle: CHART.splitLine.lineStyle },
      },
      series: [
        {
          type: config.kind,
          data,
          smooth: config.kind === "line" ? 0.25 : undefined,
          showSymbol: false,
          barMaxWidth: 5,
          lineStyle: { color: config.color, width: 2 },
          itemStyle: { color: config.color, borderRadius: config.kind === "bar" ? [2, 2, 0, 0] : 0 },
          markArea: markAreas.length ? { silent: true, data: markAreas as never } : undefined,
          markLine: markLines.length
            ? { silent: true, symbol: "none", data: markLines as never }
            : undefined,
        },
      ],
    };
  }, [observations, metric, anomalies, today]);

  return <EChart option={option} height={height} />;
}
