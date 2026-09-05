import type { EChartsOption } from "echarts";
import { useMemo } from "react";

import type { Observation } from "@/api/types";
import { CHART, TOOLTIP_BASE } from "@/components/charts/echarts";
import { EChart } from "@/components/charts/EChart";
import { formatDayMonth, formatNumber, parseDate } from "@/lib/format";

interface ForecastChartProps {
  /** Хвост фактических наблюдений — контекст, из которого растёт прогноз. */
  history: Observation[];
  forecast: Observation[];
  today?: string | null;
  height?: number;
}

/** График прогноза: линия, коридор вероятных значений и ожидаемая динамика.
 *  Прогноз не подаётся как гарантия — коридор показывается всегда. */
export function ForecastChart({ history, forecast, today, height = 300 }: ForecastChartProps) {
  const option = useMemo<EChartsOption>(() => {
    const x = (value: string) => parseDate(value).getTime();

    const factual = history
      .filter((point) => point.ndvi_mean !== null)
      .map((point) => [x(point.date), point.ndvi_mean as number]);

    const lastFact = history.filter((point) => point.ndvi_mean !== null).at(-1);
    const seed = lastFact ? [lastFact, ...forecast] : forecast;

    const line = seed
      .filter((point) => point.ndvi_mean !== null)
      .map((point) => [x(point.date), point.ndvi_mean as number]);

    const bandLow = seed.map((point) => [x(point.date), point.ndvi_lo ?? point.ndvi_mean ?? null]);
    const bandSpan = seed.map((point) => [
      x(point.date),
      point.ndvi_hi !== null && point.ndvi_lo !== null ? point.ndvi_hi - point.ndvi_lo : 0,
    ]);

    const expected = [...history, ...forecast]
      .filter((point) => point.ndvi_lo !== null && point.ndvi_hi !== null && point.value_type !== "forecast")
      .map((point) => [x(point.date), ((point.ndvi_lo as number) + (point.ndvi_hi as number)) / 2]);

    return {
      animationDuration: 400,
      grid: { left: 46, right: 24, top: 26, bottom: 30, containLabel: false },
      tooltip: {
        ...TOOLTIP_BASE,
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: "#C9CDD4", width: 1 } },
        formatter: (params: unknown) => {
          const items = params as { axisValue: number; seriesName: string; value: [number, number] }[];
          const stamp = items?.[0]?.axisValue;
          if (!stamp) return "";
          const point = [...history, ...forecast].find(
            (candidate) => x(candidate.date) === stamp,
          );
          if (!point) return "";
          const range =
            point.ndvi_lo !== null && point.ndvi_hi !== null
              ? `<div style="color:#7B808F;margin-top:4px">вероятный диапазон ${formatNumber(point.ndvi_lo)}–${formatNumber(point.ndvi_hi)}</div>`
              : "";
          return `<div style="font-weight:600;margin-bottom:5px">${formatDayMonth(new Date(stamp))}</div><b>${formatNumber(point.ndvi_mean)}</b>${range}`;
        },
      },
      xAxis: {
        type: "time",
        axisLabel: {
          ...CHART.axisLabel,
          hideOverlap: true,
          formatter: (value: number) => formatDayMonth(new Date(value)),
        },
        axisLine: { show: true, lineStyle: CHART.axisLine.lineStyle },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { ...CHART.axisLabel, formatter: (value: number) => formatNumber(value, 2) },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: true, lineStyle: CHART.splitLine.lineStyle },
      },
      series: [
        {
          name: "band-low",
          type: "line",
          data: bandLow,
          stack: "band",
          lineStyle: { opacity: 0 },
          showSymbol: false,
          silent: true,
          z: 1,
        },
        {
          name: "Диапазон прогноза",
          type: "line",
          data: bandSpan,
          stack: "band",
          lineStyle: { opacity: 0 },
          areaStyle: { color: CHART.colors.forecastBand },
          showSymbol: false,
          silent: true,
          z: 1,
        },
        ...(expected.length
          ? [
              {
                name: "Ожидаемая динамика",
                type: "line" as const,
                data: expected,
                smooth: 0.35,
                showSymbol: false,
                lineStyle: { color: CHART.colors.expected, width: 2, type: "dashed" as const },
                z: 2,
              },
            ]
          : []),
        {
          name: "Наблюдаемое",
          type: "line",
          data: factual,
          symbol: "circle",
          symbolSize: 6,
          itemStyle: { color: CHART.colors.observed },
          lineStyle: { color: CHART.colors.observed, width: 2.4 },
          z: 3,
          markLine: today
            ? {
                silent: true,
                symbol: "none",
                data: [
                  {
                    xAxis: x(today),
                    lineStyle: { color: CHART.colors.today, type: "dashed" as const, width: 1.4 },
                    label: {
                      show: true,
                      formatter: `Сегодня · ${formatDayMonth(today)}`,
                      position: "insideEndTop" as const,
                      // Без rotate подпись вертикальной линии встаёт боком.
                      rotate: 0,
                      color: "#3F4756",
                      fontSize: 11.5,
                    },
                  },
                ] as never,
              }
            : undefined,
        },
        {
          name: "Прогноз",
          type: "line",
          data: line,
          symbol: "circle",
          symbolSize: 5,
          itemStyle: { color: CHART.colors.forecast },
          lineStyle: { color: CHART.colors.forecast, width: 2.2 },
          z: 3,
        },
      ],
    };
  }, [history, forecast, today]);

  return <EChart option={option} height={height} />;
}
