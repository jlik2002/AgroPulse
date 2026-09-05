import type { EChartsOption } from "echarts";
import { useMemo } from "react";

import type { Anomaly, RadarPoint } from "@/api/types";
import { CHART, TOOLTIP_BASE, valueScale } from "@/components/charts/echarts";
import { EChart } from "@/components/charts/EChart";
import { formatDayMonth, formatNumber, parseDate } from "@/lib/format";

interface RadarChartProps {
  points: RadarPoint[];
  anomalies?: Anomaly[];
  today?: string | null;
  height?: number;
}

/** Минимальный размах оси, дБ. Радарный сигнал поля за сезон меняется
 *  на единицы децибел, и растянутая на весь диапазон ось превратила бы
 *  реальный сезонный ход в прямую линию. */
const SPAN_DB = 6;

/** Радарный ряд Sentinel-1: VV и VH в децибелах на общей оси времени.
 *
 *  Линией соединяются только снимки одной орбиты — той, что покрывает поле
 *  чаще. Точки остальных орбит показаны отдельными маркерами без линии,
 *  и это не оформительское решение: у разных орбит разный угол падения луча,
 *  и соединять их линией значило бы рисовать событие там, где сменилась
 *  геометрия съёмки. */
export function RadarChart({ points, anomalies = [], today, height = 280 }: RadarChartProps) {
  const option = useMemo<EChartsOption>(() => {
    const x = (value: string) => parseDate(value).getTime();
    const usable = points.filter((point) => point.vh_median_db !== null);

    const dominant = dominantOrbit(usable);
    const main = usable.filter((point) => orbitKey(point) === dominant);
    const other = usable.filter((point) => orbitKey(point) !== dominant);

    const values = usable.flatMap((point) =>
      [point.vv_median_db, point.vh_median_db].filter((v): v is number => v !== null),
    );
    const scale = valueScale(values, { minSpan: SPAN_DB });

    const line = (source: RadarPoint[], key: "vv_median_db" | "vh_median_db") =>
      source
        .map((point) => [x(point.date), point[key]])
        .filter(([, value]) => value !== null);

    const markAreas = anomalies.map((anomaly) => [
      {
        xAxis: x(anomaly.start_date),
        itemStyle: { color: CHART.colors.anomaly },
        label: { show: false },
      },
      { xAxis: x(anomaly.end_date), label: { show: false } },
    ]);

    const markLines = today
      ? [
          {
            xAxis: x(today),
            lineStyle: { color: CHART.colors.today, type: "dashed" as const, width: 1.2 },
            label: { show: false },
          },
        ]
      : [];

    return {
      animationDuration: 300,
      grid: { left: 46, right: 16, top: 16, bottom: 28, containLabel: false },
      tooltip: {
        ...TOOLTIP_BASE,
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: "#C9CDD4", width: 1 } },
        formatter: (params: unknown) => {
          const items = params as { axisValue: number; seriesName: string; value: [number, number] }[];
          if (!items?.length) return "";
          const head = `<div style="font-weight:600;margin-bottom:4px">${formatDayMonth(
            new Date(items[0].axisValue),
          )}</div>`;
          const rows = items
            .filter((item) => item.value?.[1] !== null && item.value?.[1] !== undefined)
            .map(
              (item) =>
                `<div>${item.seriesName}: ${formatNumber(item.value[1], 1)} дБ</div>`,
            )
            .join("");
          return head + rows;
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
        min: scale.min,
        max: scale.max,
        interval: scale.interval,
        axisLabel: {
          ...CHART.axisLabel,
          formatter: (value: number) => `${formatNumber(value, 0)}`,
        },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: true, lineStyle: CHART.splitLine.lineStyle },
      },
      series: [
        {
          name: "VH · растительность",
          type: "line",
          data: line(main, "vh_median_db"),
          smooth: 0.2,
          symbolSize: 5,
          lineStyle: { color: CHART.colors.radarVh, width: 2 },
          itemStyle: { color: CHART.colors.radarVh },
          markArea: markAreas.length ? { silent: true, data: markAreas as never } : undefined,
          markLine: markLines.length
            ? { silent: true, symbol: "none", data: markLines as never }
            : undefined,
        },
        {
          name: "VV · поверхность",
          type: "line",
          data: line(main, "vv_median_db"),
          smooth: 0.2,
          symbolSize: 5,
          lineStyle: { color: CHART.colors.radarVv, width: 2 },
          itemStyle: { color: CHART.colors.radarVv },
        },
        // Другие орбиты — точками и без линии: их уровни с основной серией
        // напрямую не сопоставимы.
        {
          name: "VH · другая орбита",
          type: "scatter",
          data: line(other, "vh_median_db"),
          symbolSize: 5,
          itemStyle: { color: CHART.colors.radarVh, opacity: 0.35 },
        },
        {
          name: "VV · другая орбита",
          type: "scatter",
          data: line(other, "vv_median_db"),
          symbolSize: 5,
          itemStyle: { color: CHART.colors.radarVv, opacity: 0.35 },
        },
      ],
    };
  }, [points, anomalies, today]);

  return <EChart option={option} height={height} />;
}

function orbitKey(point: RadarPoint): string {
  return `${point.orbit_direction ?? "?"}:${point.relative_orbit ?? "?"}`;
}

/** Орбита, покрывающая поле чаще остальных. Именно её ряд соединяется линией. */
function dominantOrbit(points: RadarPoint[]): string | null {
  const counts = new Map<string, number>();
  for (const point of points) {
    const key = orbitKey(point);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  let best: string | null = null;
  let bestCount = 0;
  for (const [key, count] of counts) {
    if (count > bestCount) {
      best = key;
      bestCount = count;
    }
  }
  return best;
}
