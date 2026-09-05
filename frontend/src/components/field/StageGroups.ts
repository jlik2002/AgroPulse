/** Пять шагов обработки, которые видит пользователь.
 *
 *  Внутри пайплайна стадий девять — они нужны для диагностики и логов.
 *  На экране они сгруппированы так, как это описано в макете «Обработка
 *  данных»: пользователю важен смысл шага, а не устройство очереди. */

import type { StageState } from "@/api/types";

export interface StageGroup {
  key: string;
  title: string;
  /** Стадии бэкенда, из которых складывается шаг. */
  stages: string[];
  icon: "satellite" | "cloud" | "leaf" | "trend" | "chart";
}

export const STAGE_GROUPS: StageGroup[] = [
  {
    key: "search",
    title: "Поиск спутниковых снимков",
    stages: ["search_scenes"],
    icon: "satellite",
  },
  {
    key: "cloud",
    title: "Проверка покрытия и облачности",
    stages: ["cloud_masking"],
    icon: "cloud",
  },
  {
    key: "indices",
    title: "Расчёт индексов и получение погоды",
    stages: ["indices", "weather"],
    icon: "leaf",
  },
  {
    key: "series",
    title: "Восстановление ряда и поиск аномалий",
    stages: ["timeseries", "gap_filling", "anomalies"],
    icon: "trend",
  },
  {
    key: "forecast",
    title: "Прогноз и подготовка результатов",
    stages: ["risk_forecast", "visualization"],
    icon: "chart",
  },
];

export interface GroupState {
  group: StageGroup;
  status: "pending" | "running" | "done" | "failed";
  progress: number;
  /** Пояснение под заголовком: берём сообщение самой свежей стадии шага. */
  message: string | null;
  error: string | null;
}

export function groupStages(stages: StageState[]): GroupState[] {
  const byName = new Map(stages.map((stage) => [stage.stage, stage]));

  return STAGE_GROUPS.map((group) => {
    const members = group.stages
      .map((name) => byName.get(name))
      .filter((stage): stage is StageState => Boolean(stage));

    if (members.length === 0) {
      return { group, status: "pending" as const, progress: 0, message: null, error: null };
    }

    const failed = members.find((stage) => stage.status === "failed");
    if (failed) {
      return {
        group,
        status: "failed" as const,
        progress: 1,
        message: failed.message,
        error: failed.error,
      };
    }

    const done = members.filter((stage) => stage.status === "done").length;
    const running = members.find((stage) => stage.status === "running");
    const progress = (done + (running ? running.progress : 0)) / group.stages.length;

    const latest = running ?? members[members.length - 1];

    if (done === group.stages.length) {
      return { group, status: "done" as const, progress: 1, message: latest.message, error: null };
    }
    if (running || done > 0) {
      return {
        group,
        status: "running" as const,
        progress,
        message: latest.message,
        error: null,
      };
    }
    return { group, status: "pending" as const, progress: 0, message: null, error: null };
  });
}
