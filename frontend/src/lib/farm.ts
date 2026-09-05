/** Подписи и цвета для реестра хозяйств.
 *
 *  Тот же принцип, что и в `status.ts`: цвет — дополнительный сигнал, рядом
 *  всегда стоит текст. Формулировки категорий не называют решения о деньгах —
 *  спутник даёт основание рассмотреть хозяйство, а не назначить выплату. */

import type { FarmTrust, ReviewCategory } from "@/api/types";

export interface CategoryStyle {
  title: string;
  /** Что предлагается сделать. Короткая форма для колонки реестра. */
  action: string;
  chip: string;
  dot: string;
}

export const REVIEW_CATEGORY: Record<ReviewCategory, CategoryStyle> = {
  urgent: {
    title: "Критическое устойчивое ухудшение",
    action: "Срочная проверка",
    chip: "bg-danger-soft text-danger-ink",
    dot: "bg-danger",
  },
  support: {
    title: "Умеренная подтверждённая аномалия",
    action: "Рассмотреть поддержку",
    chip: "bg-warn-soft text-warn-ink",
    dot: "bg-warn",
  },
  clarify: {
    title: "Отклонение не подтверждается",
    action: "Запросить сведения",
    chip: "bg-[#F2ECFB] text-[#65409F]",
    dot: "bg-[#7B49BF]",
  },
  monitor: {
    title: "Стабильное состояние",
    action: "Плановое наблюдение",
    chip: "bg-ok-soft text-ok-ink",
    dot: "bg-ok",
  },
  undetermined: {
    title: "Недостаточно данных",
    action: "Уточнить данные",
    chip: "bg-[#F1F2F4] text-ink-soft",
    dot: "bg-ink-faint",
  },
};

export const FARM_TRUST: Record<FarmTrust, { title: string; chip: string }> = {
  high: { title: "Высокое", chip: "bg-ok-soft text-ok-ink" },
  medium: { title: "Среднее", chip: "bg-warn-soft text-warn-ink" },
  low: { title: "Низкое", chip: "bg-[#F1F2F4] text-ink-soft" },
};

/** Цвет индекса потребности в поддержке. Пороги те же, что у балла поля:
 *  реестр и карточка поля не должны называть одно состояние по-разному. */
export function needTone(score: number | null | undefined): string {
  if (score === null || score === undefined) return "text-ink-muted";
  if (score >= 60) return "text-danger";
  if (score >= 30) return "text-warn";
  return "text-ok-ink";
}

export function farmsWord(count: number): string {
  const tens = count % 100;
  if (tens >= 11 && tens <= 14) return "хозяйств";
  const last = count % 10;
  if (last === 1) return "хозяйство";
  if (last >= 2 && last <= 4) return "хозяйства";
  return "хозяйств";
}
