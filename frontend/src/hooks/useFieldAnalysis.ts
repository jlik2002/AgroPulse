/** Сборка всего, что нужно страницам поля, одним хуком.
 *
 *  Обзор, снимки, динамика, данные и прогноз опираются на один и тот же
 *  временной ряд. Читать его каждой вкладкой отдельно значило бы гонять
 *  сотни точек по сети при каждом переключении. */

import { useMemo } from "react";

import {
  useAnomalies,
  useField,
  useForecast,
  useRadar,
  useRisk,
  useTimeseries,
} from "@/api/queries";
import type { Observation } from "@/api/types";
import {
  maxDeviation,
  nextSceneDate,
  peakRiskWindow,
  splitSeries,
  worstAnomaly,
} from "@/lib/series";

export function useFieldAnalysis(fieldId: string | undefined) {
  const field = useField(fieldId);
  const timeseries = useTimeseries(fieldId);
  const anomalies = useAnomalies(fieldId);
  const radar = useRadar(fieldId);
  const risk = useRisk(fieldId);
  const forecast = useForecast(fieldId);

  const series = useMemo(() => splitSeries(timeseries.data), [timeseries.data]);

  const derived = useMemo(() => {
    const worst = worstAnomaly(anomalies.data);
    return {
      worst,
      deviation: maxDeviation(series.historical),
      nextScene: nextSceneDate(series.observed),
      peakRisk: peakRiskWindow(series.forecast),
      /** Наблюдение, показываемое на карте состояния поля по умолчанию. */
      latest: series.lastObserved as Observation | null,
    };
  }, [anomalies.data, series]);

  return {
    field,
    timeseries,
    anomalies,
    radar,
    risk,
    forecast,
    series,
    ...derived,
    isPending: field.isPending || timeseries.isPending,
    isError: field.isError || timeseries.isError,
    error: field.error ?? timeseries.error,
  };
}

export type FieldAnalysis = ReturnType<typeof useFieldAnalysis>;
