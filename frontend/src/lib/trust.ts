/** Можно ли верить найденному событию — разбор для интерфейса.
 *
 *  Один сигнал вместо трёх прежних. `confidence` был длительностью,
 *  переодетой в уверенность; подтверждённость по сумме баллов списывала
 *  облачное окно трижды и выносила «слабо» событию, на котором сошлись
 *  радар и погода; понижение при несовпадении фазы сезона не показывалось
 *  вовсе. Числа на выходе нет намеренно: веса прежней суммы назначались,
 *  а не измерялись.
 *
 *  Главное правило подачи: вердикт молчит, когда всё в порядке. Метка,
 *  стоящая на каждой карточке, перестаёт читаться — как предупреждение,
 *  которое видишь каждый день. Поэтому «подтверждено» показывается одной
 *  строкой без нажима, а место на экране занимает только то, что меняет
 *  решение: расхождение с радаром и невозможность проверить. */

import type { Anomaly } from "@/api/types";

export type TrustLevel = "confirmed" | "unverified" | "disputed";

export type TrustTone = "good" | "warn" | "muted";

export interface TrustView {
  level: TrustLevel | null;
  /** Короткая формулировка: что мы утверждаем о самом выводе. */
  title: string;
  /** Одна фраза, объясняющая вердикт. Без неё ярлык ничего не значит. */
  detail: string;
  tone: TrustTone;
  /** Все основания — для развёрнутого разбора на странице поля. */
  reasons: string[];
  /** Вердикт меняет решение и потому требует места на экране. */
  actionable: boolean;
}

interface TrustFactors {
  level?: unknown;
  reasons?: unknown;
  observations?: unknown;
}

const TITLES: Record<TrustLevel, string> = {
  confirmed: "Подтверждено",
  unverified: "Проверить не удалось",
  disputed: "Радар не подтверждает",
};

const TONES: Record<TrustLevel, TrustTone> = {
  confirmed: "good",
  unverified: "muted",
  disputed: "warn",
};

/** Разобрать вердикт аномалии.
 *
 *  `null` — обычное состояние: у поля может не быть события, а у события,
 *  посчитанного до появления вердикта, не быть оценки. Второе честнее
 *  показать как «не проверялось», чем как недоверие. */
export function trustOf(anomaly: Anomaly | null | undefined): TrustView | null {
  if (!anomaly) return null;

  const factors = ((anomaly.factors ?? {}) as Record<string, unknown>).trust as
    | TrustFactors
    | undefined;
  const level = asLevel(anomaly.trust ?? factors?.level);

  if (!level) {
    return {
      level: null,
      title: "Не проверялось",
      detail: "поле считалось до подключения проверки — запустите анализ повторно",
      tone: "muted",
      reasons: [],
      actionable: true,
    };
  }

  const reasons = Array.isArray(factors?.reasons)
    ? (factors.reasons as unknown[]).filter((item): item is string => typeof item === "string")
    : [];

  return {
    level,
    title: TITLES[level],
    detail: reasons[0] ?? "",
    tone: TONES[level],
    reasons,
    // «Подтверждено» решения не меняет: это штатный исход, и занимать им
    // место значит приучить не читать эту строку вовсе.
    actionable: level !== "confirmed",
  };
}

function asLevel(value: unknown): TrustLevel | null {
  return value === "confirmed" || value === "unverified" || value === "disputed" ? value : null;
}
