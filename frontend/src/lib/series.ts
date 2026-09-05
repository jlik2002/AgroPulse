/** Разбор временного ряда: то, что нужно графикам, таблицам и карточкам.
 *
 *  Считается один раз на странице поля и переиспользуется вкладками —
 *  иначе каждая пересчитывала бы одно и то же по сотням точек. */

import type { Anomaly, Observation, Timeseries } from "@/api/types";
import { parseDate, toIsoDate } from "@/lib/format";

export interface SeriesSplit {
  observed: Observation[];
  restored: Observation[];
  forecast: Observation[];
  /** Наблюдения и восстановленные значения одним рядом, по возрастанию даты. */
  historical: Observation[];
  all: Observation[];
  lastObserved: Observation | null;
  firstForecast: Observation | null;
  lastForecast: Observation | null;
  /** Граница «сегодня» на графиках: последнее наблюдение или начало прогноза. */
  today: string | null;
}

export function splitSeries(timeseries: Timeseries | undefined): SeriesSplit {
  // Бэкенд отдаёт весь ряд поля, включая историю прошлых сезонов: она нужна
  // ему для построения нормы. Пользователю на графиках и в таблице показывается
  // выбранный период анализа плюс горизонт прогноза — иначе кривая текущего
  // сезона утонула бы в пяти предыдущих.
  const from = timeseries?.period_from ?? "";
  const to = timeseries?.period_to ?? "";
  const all = [...(timeseries?.observations ?? [])]
    .filter(
      (point) =>
        point.value_type === "forecast" || (point.date >= from && point.date <= to),
    )
    .sort((a, b) => a.date.localeCompare(b.date));
  const observed = all.filter((point) => point.value_type === "observed");
  const restored = all.filter((point) => point.value_type === "restored");
  const forecast = all.filter((point) => point.value_type === "forecast");
  const historical = all.filter((point) => point.value_type !== "forecast");

  const lastObserved = observed.length ? observed[observed.length - 1] : null;
  const firstForecast = forecast.length ? forecast[0] : null;

  return {
    observed,
    restored,
    forecast,
    historical,
    all,
    lastObserved,
    firstForecast,
    lastForecast: forecast.length ? forecast[forecast.length - 1] : null,
    today: lastObserved?.date ?? firstForecast?.date ?? null,
  };
}

/** Ожидаемая сезонная динамика: середина коридора нормы климатологии.
 *  Бэкенд отдаёт границы в `ndvi_lo` / `ndvi_hi` для исторических точек. */
export function expectedCurve(points: Observation[]): { date: string; value: number }[] {
  return points
    .filter(
      (point) =>
        point.value_type !== "forecast" && point.ndvi_lo !== null && point.ndvi_hi !== null,
    )
    .map((point) => ({
      date: point.date,
      value: ((point.ndvi_lo as number) + (point.ndvi_hi as number)) / 2,
    }));
}

/** Средний интервал между съёмками — по нему оцениваем дату следующего снимка. */
export function revisitDays(observed: Observation[]): number | null {
  if (observed.length < 3) return null;
  const gaps: number[] = [];
  for (let index = 1; index < observed.length; index += 1) {
    const previous = parseDate(observed[index - 1].date).getTime();
    const current = parseDate(observed[index].date).getTime();
    gaps.push(Math.round((current - previous) / 86_400_000));
  }
  gaps.sort((a, b) => a - b);
  const median = gaps[Math.floor(gaps.length / 2)];
  return median > 0 ? median : null;
}

/** Ожидаемая дата следующего снимка: последнее наблюдение плюс типичный
 *  интервал повторной съёмки. Это оценка по каденции ряда, а не обещание
 *  сервиса, поэтому дата не подтягивается к сегодняшнему дню — иначе на
 *  архивном периоде она уезжала бы в текущий год. */
export function nextSceneDate(observed: Observation[]): string | null {
  const cadence = revisitDays(observed);
  const last = observed[observed.length - 1];
  if (!cadence || !last) return null;

  const date = parseDate(last.date);
  date.setDate(date.getDate() + cadence);
  return toIsoDate(date);
}

/** Самая тяжёлая аномалия: список бэкенд уже сортирует, берём первую. */
export function worstAnomaly(anomalies: Anomaly[] | undefined): Anomaly | null {
  return anomalies && anomalies.length ? anomalies[0] : null;
}

/** Максимальное отклонение факта от ожидаемой динамики, в долях. */
export function maxDeviation(points: Observation[]): number | null {
  let worst: number | null = null;
  for (const point of points) {
    if (point.ndvi_mean === null || point.ndvi_lo === null || point.ndvi_hi === null) continue;
    const expected = (point.ndvi_lo + point.ndvi_hi) / 2;
    if (expected <= 0) continue;
    const deviation = (point.ndvi_mean - expected) / expected;
    if (worst === null || deviation < worst) worst = deviation;
  }
  return worst;
}

/** Период максимального риска в прогнозе — окно с наименьшим ожидаемым NDVI. */
export function peakRiskWindow(
  forecast: Observation[],
  windowSize = 5,
): { from: string; to: string; index: number } | null {
  const points = forecast.filter((point) => point.ndvi_mean !== null);
  if (points.length === 0) return null;
  if (points.length <= windowSize) {
    return { from: points[0].date, to: points[points.length - 1].date, index: 0 };
  }

  let bestIndex = 0;
  let bestSum = Number.POSITIVE_INFINITY;
  for (let index = 0; index + windowSize <= points.length; index += 1) {
    const sum = points
      .slice(index, index + windowSize)
      .reduce((acc, point) => acc + (point.ndvi_mean as number), 0);
    if (sum < bestSum) {
      bestSum = sum;
      bestIndex = index;
    }
  }
  return {
    from: points[bestIndex].date,
    to: points[bestIndex + windowSize - 1].date,
    index: bestIndex,
  };
}
