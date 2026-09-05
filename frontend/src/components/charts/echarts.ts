/** Регистрация только используемых модулей ECharts.
 *  Полная сборка тянет карты, 3D и гео — в приложении они не нужны. */

import * as echarts from "echarts/core";
import { BarChart, LineChart, ScatterChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  LineChart,
  BarChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  CanvasRenderer,
]);

export { echarts };

/** Оформление осей и подсказок, общее для всех графиков.
 *  Значения сняты с макетов: тонкие серые линии сетки, чёрные подписи. */
export const CHART = {
  font: "Inter Variable, Inter, system-ui, sans-serif",
  axisLabel: { color: "#3F4756", fontSize: 12, fontFamily: "Inter Variable, Inter, sans-serif" },
  splitLine: { lineStyle: { color: "#EEF0F3", width: 1 } },
  axisLine: { lineStyle: { color: "#D8DCE2" } },
  colors: {
    observed: "#0F4730",
    restored: "#2A74DD",
    forecast: "#7B49BF",
    forecastBand: "rgba(123, 73, 191, 0.14)",
    expected: "#9CA1AC",
    ndmi: "#0FA3A0",
    temp: "#FB541C",
    precip: "#1674E2",
    anomaly: "rgba(229, 37, 44, 0.07)",
    anomalyEdge: "#E5252C",
    today: "#7B808F",
  },
} as const;

export const TOOLTIP_BASE = {
  backgroundColor: "#FFFFFF",
  borderColor: "#E4E7EB",
  borderWidth: 1,
  padding: [10, 12] as [number, number],
  textStyle: { color: "#0B0B0B", fontSize: 12.5, fontFamily: CHART.font },
  extraCssText: "border-radius:10px;box-shadow:0 12px 32px rgba(16,24,40,0.12);",
};
