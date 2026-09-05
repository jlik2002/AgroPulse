import type { EChartsOption } from "echarts";
import { useMemo } from "react";

import type { Anomaly, Observation } from "@/api/types";
import { CHART, TOOLTIP_BASE } from "@/components/charts/echarts";
import { EChart } from "@/components/charts/EChart";
import { formatDayMonth, formatNumber, formatPercent, parseDate, toIsoDate } from "@/lib/format";
import { VALUE_TYPE } from "@/lib/status";

export interface NdviChartProps {
  observations: Observation[];
  anomalies?: Anomaly[];
  /** Дата вертикальной линии «сегодня» — граница факта и прогноза. */
  today?: string | null;
  showExpected?: boolean;
  showRestored?: boolean;
  showForecast?: boolean;
  height?: number;
  /** Компактный режим для карточки «Динамика NDVI» на обзоре поля. */
  compact?: boolean;
}

export function NdviChart({
  observations,
  anomalies = [],
  today,
  showExpected = true,
  showRestored = true,
  showForecast = true,
  height = 300,
  compact = false,
}: NdviChartProps) {
  const option = useMemo<EChartsOption>(() => {
    const sorted = [...observations].sort((a, b) => a.date.localeCompare(b.date));
    const byDate = new Map(sorted.map((point) => [point.date, point]));
    // Ось времени получает метки в локальной полуночи: разбор ISO-строки самим
    // ECharts трактует её как UTC и сдвигает точки на день назад.
    const x = (value: string) => parseDate(value).getTime();

    const observed = sorted
      .filter((point) => point.value_type === "observed" && point.ndvi_mean !== null)
      .map((point) => [x(point.date), point.ndvi_mean as number]);

    // Восстановленные значения рисуются только на своих датах: разрывы между
    // ними размыкают линию, поэтому подряд идущие пропуски дают сплошной
    // пунктирный отрезок, а одиночные — отдельные кружки.
    const restoredPoints = sorted.filter((point) => point.value_type === "restored");
    const restored = showRestored
      ? sorted
          .filter((point) => point.ndvi_mean !== null && point.value_type !== "forecast")
          .map((point) =>
            point.value_type === "restored"
              ? [x(point.date), point.ndvi_mean as number]
              : [x(point.date), null],
          )
      : [];
    // При посуточном восстановлении кружков были бы сотни — они бы слиплись
    // в сплошную полосу и скрыли наблюдения под собой.
    const restoredSymbolSize = compact || restoredPoints.length > 40 ? 0 : 7;

    const expected = showExpected
      ? sorted
          .filter((point) => point.ndvi_lo !== null && point.ndvi_hi !== null)
          .map((point) => [
            x(point.date),
            ((point.ndvi_lo as number) + (point.ndvi_hi as number)) / 2,
          ])
      : [];

    const forecastPoints = sorted.filter(
      (point) => point.value_type === "forecast" && point.ndvi_mean !== null,
    );
    // Прогноз стыкуем с последним наблюдением: разрыв читался бы как пропуск данных.
    const lastFact = [...sorted]
      .reverse()
      .find((point) => point.value_type !== "forecast" && point.ndvi_mean !== null);
    const forecastSeed = lastFact && showForecast ? [lastFact, ...forecastPoints] : forecastPoints;

    const forecast = showForecast
      ? forecastSeed.map((point) => [x(point.date), point.ndvi_mean as number])
      : [];
    const bandLow = showForecast
      ? forecastSeed.map((point) => [x(point.date), point.ndvi_lo ?? point.ndvi_mean ?? null])
      : [];
    const bandSpan = showForecast
      ? forecastSeed.map((point) => [
          x(point.date),
          point.ndvi_hi !== null && point.ndvi_lo !== null
            ? point.ndvi_hi - point.ndvi_lo
            : 0,
        ])
      : [];

    // label отключён явно: по умолчанию ECharts подписывает границы области
    // значением оси, и на оси времени это сырой таймстемп.
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
          lineStyle: { color: CHART.colors.anomalyEdge, type: "dashed" as const, width: 1.4 },
          label: { show: false },
        },
        {
          xAxis: x(anomaly.end_date),
          lineStyle: { color: CHART.colors.anomalyEdge, type: "dashed" as const, width: 1.4 },
          label: { show: false },
        },
      ]),
      ...(today
        ? [
            {
              xAxis: x(today),
              lineStyle: { color: CHART.colors.today, type: "dashed" as const, width: 1.4 },
              label: compact
                ? { show: false }
                : {
                    show: true,
                    formatter: "Сегодня",
                    position: "insideEndTop" as const,
                    // Без rotate подпись вертикальной линии встаёт боком.
                    rotate: 0,
                    color: "#3F4756",
                    fontSize: 11.5,
                  },
            },
          ]
        : []),
    ];

    return {
      animationDuration: 400,
      grid: {
        left: compact ? 38 : 44,
        right: compact ? 46 : 20,
        top: 18,
        bottom: 28,
        containLabel: false,
      },
      tooltip: {
        ...TOOLTIP_BASE,
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: "#C9CDD4", width: 1 } },
        formatter: (params: unknown) => {
          const items = params as { axisValue: number }[];
          const stamp = items?.[0]?.axisValue;
          const point = stamp ? byDate.get(toIsoDate(new Date(stamp))) : undefined;
          if (!point) return "";
          return tooltipHtml(point);
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
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        min: 0,
        max: (value: { max: number }) => Math.min(1, Math.ceil((value.max + 0.1) * 10) / 10),
        interval: 0.2,
        axisLabel: {
          ...CHART.axisLabel,
          formatter: (value: number) => formatNumber(value, 1),
        },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: true, lineStyle: CHART.splitLine.lineStyle },
      },
      series: [
        // Нижняя граница коридора прогноза — прозрачная подложка стека.
        ...(showForecast && bandLow.length
          ? [
              {
                name: "band-low",
                type: "line" as const,
                data: bandLow,
                stack: "forecast-band",
                lineStyle: { opacity: 0 },
                showSymbol: false,
                silent: true,
                z: 1,
              },
              {
                name: "Диапазон прогноза",
                type: "line" as const,
                data: bandSpan,
                stack: "forecast-band",
                lineStyle: { opacity: 0 },
                areaStyle: { color: CHART.colors.forecastBand },
                showSymbol: false,
                silent: true,
                z: 1,
              },
            ]
          : []),
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
        ...(restored.length
          ? [
              {
                name: "Восстановленное",
                type: "line" as const,
                data: restored,
                connectNulls: false,
                symbol: "circle",
                symbolSize: restoredSymbolSize,
                itemStyle: { color: "#FFFFFF", borderColor: CHART.colors.restored, borderWidth: 2 },
                lineStyle: { color: CHART.colors.restored, width: 2, type: "dashed" as const },
                // Выше линии наблюдений: пропуски, восстановленные посуточно,
                // идут почти по той же траектории, и снизу их было бы не видно.
                z: 5,
              },
            ]
          : []),
        {
          name: "Наблюдаемое",
          type: "line",
          data: observed,
          symbol: "circle",
          symbolSize: compact ? 0 : 6,
          itemStyle: { color: CHART.colors.observed },
          lineStyle: { color: CHART.colors.observed, width: 2.4 },
          z: 4,
          markArea: markAreas.length ? { silent: true, data: markAreas as never } : undefined,
          markLine: markLines.length
            ? { silent: true, symbol: "none", data: markLines as never }
            : undefined,
        },
        ...(forecast.length
          ? [
              {
                name: "Прогноз",
                type: "line" as const,
                data: forecast,
                symbol: "circle",
                symbolSize: compact ? 0 : 5,
                itemStyle: { color: CHART.colors.forecast },
                lineStyle: { color: CHART.colors.forecast, width: 2.2 },
                z: 4,
              },
            ]
          : []),
      ],
    };
  }, [observations, anomalies, today, showExpected, showRestored, showForecast, compact]);

  return <EChart option={option} height={height} />;
}

/** Подсказка макета: дата, значение, тип происхождения и покрытие. */
function tooltipHtml(point: Observation): string {
  const type = VALUE_TYPE[point.value_type];
  const rows: string[] = [
    `<div style="font-weight:600;margin-bottom:6px">${formatDayMonth(parseDate(point.date))}</div>`,
    `<div style="display:flex;gap:18px;justify-content:space-between"><span>NDVI</span><b>${formatNumber(point.ndvi_mean)}</b></div>`,
  ];
  if (point.ndmi_mean !== null) {
    rows.push(
      `<div style="display:flex;gap:18px;justify-content:space-between"><span>NDMI</span><b>${formatNumber(point.ndmi_mean)}</b></div>`,
    );
  }
  rows.push(
    `<div style="display:flex;align-items:center;gap:7px;margin-top:5px"><span style="width:8px;height:8px;border-radius:50%;background:${type.stroke};display:inline-block"></span><span>${type.title}</span></div>`,
  );
  if (point.valid_fraction !== null) {
    rows.push(
      `<div style="display:flex;gap:18px;justify-content:space-between;margin-top:3px"><span>Покрытие</span><b>${formatPercent(point.valid_fraction)}</b></div>`,
    );
  } else if (point.missing_reason) {
    rows.push(
      `<div style="margin-top:3px;color:#7B808F">${escapeHtml(point.missing_reason)}</div>`,
    );
  }
  return rows.join("");
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"]/g, (char) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char] ?? char,
  );
}
