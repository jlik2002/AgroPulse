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

export interface AxisScale {
  min: number;
  max: number;
  interval: number;
}

interface ScaleOptions {
  /** Минимальный размах оси. Защита от обратной крайности: ряд, колеблющийся
   *  на сотые доли, не должен растягиваться на всю высоту и выглядеть событием. */
  minSpan: number;
  /** Физические границы величины, за которые ось выходить не должна. */
  limit?: [number, number];
  /** Желаемое число делений. Шаг подбирается ближайший «круглый». */
  ticks?: number;
}

/** Диапазон оси значений по самим данным.
 *
 *  Привязка нижней границы к нулю кажется честной, но для индексов вредна:
 *  поле, прошедшее сезон в коридоре 0,55–0,70, на шкале 0..1 выглядит прямой
 *  линией, и просадка, ради которой график и рисуется, теряется в толщине
 *  штриха. Поэтому ось подгоняется под данные, а `minSpan` не даёт перегнуть
 *  в другую сторону. */
export function valueScale(values: number[], options: ScaleOptions): AxisScale {
  const { minSpan, limit, ticks = 4 } = options;

  const finite = values.filter((value) => Number.isFinite(value));
  if (finite.length === 0) {
    const [low] = limit ?? [0, 0];
    return { min: low ?? 0, max: (low ?? 0) + minSpan, interval: minSpan / ticks };
  }

  let low = Math.min(...finite);
  let high = Math.max(...finite);

  // Расширяем до минимального размаха симметрично относительно середины ряда.
  const deficit = minSpan - (high - low);
  if (deficit > 0) {
    low -= deficit / 2;
    high += deficit / 2;
  }

  // Небольшой отступ, чтобы крайние точки не лежали на рамке.
  const padding = (high - low) * 0.08;
  low -= padding;
  high += padding;

  const step = niceStep((high - low) / ticks);
  low = Math.floor(low / step) * step;
  high = Math.ceil(high / step) * step;

  if (limit) {
    low = Math.max(low, limit[0]);
    high = Math.min(high, limit[1]);
  }

  // Шаг и границы округляем: иначе 0.1 * 3 даёт подпись «0.30000000000000004».
  const digits = step < 1 ? Math.max(0, -Math.floor(Math.log10(step)) + 1) : 2;
  return {
    min: round(low, digits),
    max: round(high, digits),
    interval: round(step, digits),
  };
}

/** Ближайший «круглый» шаг: 1, 2 или 5 на соответствующем порядке. */
function niceStep(raw: number): number {
  if (!(raw > 0)) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalized = raw / magnitude;
  const factor = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return factor * magnitude;
}

function round(value: number, digits: number): number {
  const scale = 10 ** digits;
  return Math.round(value * scale) / scale;
}
