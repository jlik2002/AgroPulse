/** Подписи и цвета статусов.
 *
 *  Принцип макетов: цвет — только дополнительный сигнал, рядом всегда стоит
 *  текст. Поэтому каждая запись обязательно несёт `title`. */

import type { AnomalySeverity, FieldStatus, ValueType } from "@/api/types";

export interface StatusStyle {
  title: string;
  /** Цвет заливки контура на карте. */
  map: string;
  chip: string;
  dot: string;
  border: string;
  accent: string;
}

export const FIELD_STATUS: Record<FieldStatus, StatusStyle> = {
  critical: {
    title: "Критическое",
    map: "#E5252C",
    chip: "bg-danger-soft text-danger-ink",
    dot: "bg-danger",
    border: "border-l-danger",
    accent: "text-danger",
  },
  attention: {
    title: "Требует внимания",
    map: "#E9A317",
    chip: "bg-warn-soft text-warn-ink",
    dot: "bg-warn",
    border: "border-l-warn",
    accent: "text-warn",
  },
  normal: {
    title: "Аномалий нет",
    map: "#0F4730",
    chip: "bg-ok-soft text-ok-ink",
    dot: "bg-ok",
    border: "border-l-ok",
    accent: "text-ok-ink",
  },
  insufficient_data: {
    title: "Недостаточно данных",
    map: "#98A0AE",
    chip: "bg-[#F1F2F4] text-ink-soft",
    dot: "bg-ink-faint",
    border: "border-l-ink-faint",
    accent: "text-ink-soft",
  },
  pending: {
    title: "Не обработано",
    map: "#98A0AE",
    chip: "bg-[#F1F2F4] text-ink-soft",
    dot: "bg-ink-faint",
    border: "border-l-line",
    accent: "text-ink-muted",
  },
  failed: {
    title: "Ошибка обработки",
    map: "#98A0AE",
    chip: "bg-[#F1F2F4] text-ink-soft",
    dot: "bg-ink-faint",
    border: "border-l-ink-faint",
    accent: "text-ink-soft",
  },
};

export function statusOf(status: FieldStatus | undefined | null): StatusStyle {
  return FIELD_STATUS[status ?? "pending"];
}

export const SEVERITY_TITLES: Record<AnomalySeverity, string> = {
  moderate: "Угнетение биомассы",
  critical: "Критическая аномалия",
};

export const VALUE_TYPE: Record<ValueType, { title: string; chip: string; stroke: string }> = {
  observed: {
    title: "Наблюдаемое",
    chip: "bg-ok-soft text-ok-ink",
    stroke: "#0F4730",
  },
  restored: {
    title: "Восстановленное",
    chip: "bg-[#EAF1FD] text-[#1E5FC0]",
    stroke: "#2A74DD",
  },
  forecast: {
    title: "Прогноз",
    chip: "bg-[#F2ECFB] text-[#65409F]",
    stroke: "#7B49BF",
  },
};

export const DIRECTION_TITLES: Record<string, string> = {
  declining: "Ухудшение, вероятно, продолжится",
  improving: "Ожидается восстановление",
  stable: "Существенных изменений не ожидается",
};

export const RISK_LEVEL_TITLES: Record<string, string> = {
  high: "Высокий",
  moderate: "Повышенный",
  low: "Низкий",
};

/** Цвет числового значения риска: 0–100. */
export function riskTone(score: number | null | undefined): string {
  if (score === null || score === undefined) return "text-ink-muted";
  if (score >= 70) return "text-danger";
  if (score >= 40) return "text-warn";
  return "text-ok-ink";
}

/** Словесная оценка качества данных по средней доле пригодных пикселей. */
export function dataQualityTitle(meanValidFraction: number | null | undefined): string {
  if (meanValidFraction === null || meanValidFraction === undefined) return "неизвестно";
  if (meanValidFraction >= 0.8) return "высокое";
  if (meanValidFraction >= 0.5) return "среднее";
  return "низкое";
}

/** Цветовая шкала NDVI: красный — жёлтый — зелёный, как в легенде макета. */
export function ndviColor(value: number | null | undefined): string {
  if (value === null || value === undefined) return "#98A0AE";
  const stops: [number, [number, number, number]][] = [
    [0.0, [199, 44, 34]],
    [0.2, [232, 106, 41]],
    [0.4, [240, 189, 60]],
    [0.6, [140, 190, 74]],
    [0.8, [26, 122, 62]],
    [1.0, [11, 74, 41]],
  ];
  const clamped = Math.min(1, Math.max(0, value));
  for (let index = 1; index < stops.length; index += 1) {
    const [stop, color] = stops[index];
    if (clamped <= stop) {
      const [prevStop, prevColor] = stops[index - 1];
      const ratio = (clamped - prevStop) / (stop - prevStop);
      const mixed = prevColor.map((channel, i) =>
        Math.round(channel + (color[i] - channel) * ratio),
      );
      return `rgb(${mixed.join(", ")})`;
    }
  }
  return "rgb(11, 74, 41)";
}

/** Шкала NDMI: сухо — влажно. Отдельная от NDVI, чтобы их не путали. */
export function ndmiColor(value: number | null | undefined): string {
  if (value === null || value === undefined) return "#98A0AE";
  const clamped = Math.min(1, Math.max(0, (value + 0.2) / 0.8));
  const from = [196, 154, 88];
  const to = [10, 118, 130];
  const mixed = from.map((channel, index) =>
    Math.round(channel + (to[index] - channel) * clamped),
  );
  return `rgb(${mixed.join(", ")})`;
}
