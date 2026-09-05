/** Подтверждённость аномалии независимыми источниками — разбор для интерфейса.
 *
 *  Отвечает не на тот же вопрос, что риск. Риск говорит, насколько плохо;
 *  подтверждённость — насколько это правда. Оси независимые, и сливать их
 *  в одно число нельзя: получилось бы значение, по которому не понять ни
 *  того, ни другого.
 *
 *  По той же причине число 0..100 на экран не выводится. Рядом уже стоит
 *  риск по шкале 0..100, и два одинаковых на вид балла читались бы как
 *  «один больше другого», не значая ничего. Число остаётся в API и в PDF,
 *  где по нему можно сортировать; интерфейс получает слова и перечень
 *  свидетельств. */

import type { Anomaly } from "@/api/types";

/** Что сказал радар по окну события. */
export type RadarVerdict = "agrees" | "silent" | "no_data";

export type CorroborationTone = "good" | "warn" | "muted" | "danger";

export interface EvidenceItem {
  label: string;
  /** Вклад в балл: положительный — свидетельство за, отрицательный — против. */
  weight: number;
}

export interface CorroborationView {
  /** Короткая формулировка для строки в карточке. */
  title: string;
  /** Пояснение: почему именно так. Без него число и цвет ничего не значат. */
  detail: string;
  tone: CorroborationTone;
  score: number | null;
  verdict: RadarVerdict | null;
  /** Перечень свидетельств со знаками, из которых сложился балл. */
  evidence: EvidenceItem[];
  /** Радар в окне был и события не подтвердил — повод проверить данные,
   *  а не ехать в поле. */
  disputed: boolean;
}

const EVIDENCE_LABELS: Record<string, string> = {
  optical: "Видно в измеренных точках NDVI",
  radar: "Радар показывает то же",
  persistence: "Держится несколько дат съёмки",
  weather: "Погода объясняет",
  clouds: "Окно закрыто облаками",
  mixed_orbit: "Пригодной к сравнению съёмки в окне почти нет",
};

/** Порядок вывода свидетельств: сначала подтверждающие, потом ослабляющие.
 *  Иначе список читается как перечень претензий. */
const EVIDENCE_ORDER = ["optical", "radar", "persistence", "weather", "clouds", "mixed_orbit"];

/** Разобрать подтверждённость аномалии.
 *
 *  `null` вместо аномалии — обычное состояние: у поля может не быть события,
 *  а у события, посчитанного до появления радара, не быть оценки. Второе
 *  честнее показать как «не проверялось», чем как низкую подтверждённость. */
export function corroborationOf(anomaly: Anomaly | null | undefined): CorroborationView | null {
  if (!anomaly) return null;

  const factors = (anomaly.factors ?? {}) as Record<string, unknown>;
  const score = anomaly.corroboration;

  if (score === null || score === undefined) {
    return {
      title: "Подтверждение не проверялось",
      detail: "поле считалось до подключения радара — запустите анализ повторно",
      tone: "muted",
      score: null,
      verdict: null,
      evidence: [],
      disputed: false,
    };
  }

  const verdict = asVerdict(factors.corroboration_radar);
  const level = typeof factors.corroboration_level === "string" ? factors.corroboration_level : "";
  const evidence = readEvidence(factors.corroboration_parts);
  const detail = readDetail(factors.corroboration_notes);

  // Радар в окне был и события не показал — единственный случай, когда
  // низкая оценка означает «вероятно, этого не было». Все остальные
  // означают лишь «мы не смогли проверить», и понижать по ним приоритет
  // поля нельзя: подтверждённость проседает от облачности, то есть тогда,
  // когда оптика слабее всего и смотреть надо больше, а не меньше.
  const disputed = verdict === "silent" && level === "weak";

  if (disputed) {
    return {
      title: "Радар это не подтверждает",
      detail: "снимки в окне есть, изменений структуры они не показывают",
      tone: "danger",
      score,
      verdict,
      evidence,
      disputed: true,
    };
  }

  if (level === "high") {
    return {
      title: "Подтверждено",
      detail: detail || "сошлись независимые источники",
      tone: "good",
      score,
      verdict,
      evidence,
      disputed: false,
    };
  }

  if (level === "possible") {
    return {
      title: "Подтверждено частично",
      detail: detail || "сошлись не все источники",
      tone: "warn",
      score,
      verdict,
      evidence,
      disputed: false,
    };
  }

  return {
    title: verdict === "no_data" ? "Проверить радаром не удалось" : "Подтверждение слабое",
    detail: detail || "независимых свидетельств почти нет",
    tone: "warn",
    score,
    verdict,
    evidence,
    disputed: false,
  };
}

function asVerdict(value: unknown): RadarVerdict | null {
  return value === "agrees" || value === "silent" || value === "no_data" ? value : null;
}

function readEvidence(value: unknown): EvidenceItem[] {
  if (!value || typeof value !== "object") return [];
  const parts = value as Record<string, unknown>;
  return EVIDENCE_ORDER.filter((key) => typeof parts[key] === "number").map((key) => ({
    label: EVIDENCE_LABELS[key] ?? key,
    weight: parts[key] as number,
  }));
}

/** Первое примечание, объясняющее оценку. Их может быть несколько, но в строке
 *  карточки помещается одно — остальные видны в разборе свидетельств. */
function readDetail(value: unknown): string {
  if (!Array.isArray(value)) return "";
  const first = value.find((item) => typeof item === "string" && item.trim());
  return typeof first === "string" ? first : "";
}
