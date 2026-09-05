import {
  Clock,
  Cloud,
  CloudRain,
  CloudSun,
  Droplets,
  Info,
  RefreshCw,
  Sun,
  Thermometer,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { downloadFile } from "@/api/client";
import type { Observation } from "@/api/types";
import { useProjectContext } from "@/app/ProjectContext";
import { ChartLegend } from "@/components/charts/ChartLegend";
import { ForecastChart } from "@/components/charts/ForecastChart";
import { FieldHeader } from "@/components/field/FieldHeader";
import { InspectionChecklist } from "@/components/field/InspectionChecklist";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { Modal } from "@/components/ui/Modal";
import { ErrorState, Loading, Notice } from "@/components/ui/State";
import { useFieldAnalysis } from "@/hooks/useFieldAnalysis";
import { cn } from "@/lib/cn";
import {
  daysWord,
  formatDate,
  formatDateRangeShort,
  formatDayMonth,
  formatNumber,
  formatPercent,
} from "@/lib/format";
import { DIRECTION_TITLES, RISK_LEVEL_TITLES } from "@/lib/status";

const TABS = [
  { key: "overview", label: "Обзор" },
  { key: "scenes", label: "Снимки" },
  { key: "dynamics", label: "Динамика" },
  { key: "data", label: "Данные" },
] as const;

/** Прогноз риска на 14 дней.
 *
 *  Прогноз не подаётся как гарантированный результат: вместе с линией всегда
 *  показывается диапазон возможных значений, уверенность и ограничения. */
export function ForecastPage() {
  const { fieldId = "" } = useParams();
  const navigate = useNavigate();
  const { project } = useProjectContext();
  const analysis = useFieldAnalysis(fieldId);
  const [checklist, setChecklist] = useState(false);
  const [method, setMethod] = useState(false);

  const field = analysis.field.data;
  const forecast = analysis.forecast.data;
  const risk = analysis.risk.data;
  const points = analysis.series.forecast;

  const factors = useMemo(
    () => buildFactors(forecast?.factors ?? null, risk?.breakdown ?? null),
    [forecast?.factors, risk?.breakdown],
  );
  const dayRisk = useMemo(
    () => buildDayRisk(points, forecast?.risk_level ?? null),
    [points, forecast?.risk_level],
  );

  if (analysis.isPending) return <Loading text="Загружаем прогноз" />;
  if (analysis.isError || !field) {
    return (
      <div className="px-9 py-9">
        <ErrorState title="Не удалось открыть прогноз" error={analysis.error} />
      </div>
    );
  }

  const level = forecast?.risk_level ?? null;
  const peak = analysis.peakRisk;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <FieldHeader
        projectId={project.id}
        field={field}
        tabs={TABS}
        activeTab="overview"
        breadcrumbTail="Прогноз"
        onTabChange={(key) => navigate(`/p/${project.id}/field/${field.id}?tab=${key}`)}
        onExportCsv={() =>
          void downloadFile(`/fields/${field.id}/export.csv`, undefined, `${field.name}.csv`)
        }
        onReport={() => navigate(`/p/${project.id}/reports?field=${field.id}`)}
      />

      <div className="space-y-4 px-9 py-6">
        {/* --- итог прогноза --- */}
        <div
          className={cn(
            "flex flex-wrap items-center gap-x-10 gap-y-5 rounded-2xl border px-6 py-5",
            level === "high" ? "border-warn-line bg-warn-soft/50" : "border-line bg-white",
          )}
        >
          <div className="min-w-[300px] flex-1">
            <Chip
              size="sm"
              className={
                level === "high"
                  ? "bg-danger-soft text-danger-ink"
                  : level === "moderate"
                    ? "bg-warn-soft text-warn-ink"
                    : "bg-ok-soft text-ok-ink"
              }
              dot={level === "high" ? "bg-danger" : level === "moderate" ? "bg-warn" : "bg-ok"}
            >
              {level ? `${RISK_LEVEL_TITLES[level] ?? level} риск` : "Риск не рассчитан"}
            </Chip>
            <h2 className="mt-2.5 text-[24px] font-semibold leading-tight text-ink">
              {forecast?.direction
                ? (DIRECTION_TITLES[forecast.direction] ?? forecast.direction)
                : "Прогноз не построен"}
            </h2>
            <p className="mt-1 text-[14.5px] text-ink-soft">
              {peak
                ? `Наиболее рискованный период — ${formatDateRangeShort(peak.from, peak.to)}`
                : (forecast?.insufficient_reason ?? "Недостаточно свежих наблюдений для прогноза")}
            </p>
          </div>

          <span className="h-14 w-px bg-line" />

          <div>
            <p className="text-[14px] text-ink-soft">Риск</p>
            <p className="mt-1">
              <span
                className={cn(
                  "text-[32px] font-semibold leading-none tnum",
                  (risk?.score ?? 0) >= 70
                    ? "text-danger"
                    : (risk?.score ?? 0) >= 40
                      ? "text-warn"
                      : "text-ok-ink",
                )}
              >
                {risk?.score === null || risk?.score === undefined ? "—" : Math.round(risk.score)}
              </span>
              <span className="ml-1.5 text-[17px] text-ink-muted">/ 100</span>
            </p>
          </div>

          <span className="h-14 w-px bg-line" />

          <div>
            <p className="text-[14px] text-ink-soft">Уверенность прогноза</p>
            <p className="mt-1">
              <span
                className={cn(
                  "text-[32px] font-semibold leading-none tnum",
                  (forecast?.confidence ?? 0) >= 0.8
                    ? "text-ok-ink"
                    : (forecast?.confidence ?? 0) >= 0.6
                      ? "text-warn"
                      : "text-danger",
                )}
              >
                {forecast?.confidence !== null && forecast?.confidence !== undefined
                  ? formatPercent(forecast.confidence)
                  : "—"}
              </span>
              <span className="ml-2 text-[15px] text-ink-soft">
                · {confidenceWord(forecast?.confidence ?? null)}
              </span>
            </p>
          </div>

          <Button className="ml-auto" size="lg" onClick={() => setChecklist(true)}>
            Что проверить при выезде
          </Button>
        </div>

        <div className="grid grid-cols-[1fr_400px] gap-4">
          <Card>
            <CardHeader title="Прогноз NDVI" />
            <div className="p-5 pt-3">
              {points.length > 0 ? (
                <>
                  <ForecastChart
                    history={analysis.series.historical.slice(-8)}
                    forecast={points}
                    today={analysis.series.today}
                    height={300}
                  />
                  <ChartLegend
                    className="mt-3"
                    items={[
                      { label: "Наблюдаемое", color: "#0F4730", mark: "solid" },
                      { label: "Прогноз", color: "#7B49BF", mark: "solid" },
                      { label: "Диапазон прогноза", color: "#7B49BF", mark: "area" },
                      { label: "Ожидаемая динамика", color: "#9CA1AC", mark: "dashed" },
                    ]}
                  />
                </>
              ) : (
                <Notice tone="warn" icon={<Info size={17} />}>
                  Прогноз не построен: {forecast?.insufficient_reason ?? "недостаточно наблюдений"}.
                  Он появится после следующего пригодного снимка.
                </Notice>
              )}
            </div>
          </Card>

          <div className="space-y-4">
            <Card>
              {/* Заголовок следует за источником: если прогон прогноза не сохранил
                  своих факторов, показывается разложение текущего риска, и
                  называть его причинами прогноза было бы неверно. */}
              <CardHeader
                title={
                  forecast?.factors ? "Что влияет на прогноз" : "Что влияет на оценку риска"
                }
              />
              <ul className="space-y-3.5 p-5 pt-4">
                {factors.length === 0 ? (
                  <li className="text-[14px] text-ink-muted">
                    Значимых факторов риска не выявлено.
                  </li>
                ) : (
                  factors.map((factor) => (
                    <li key={factor.key} className="flex items-center gap-3">
                      <span
                        className={cn(
                          "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
                          factor.tone,
                        )}
                      >
                        {factor.icon}
                      </span>
                      <span className="min-w-0 flex-1 text-[14.5px] text-ink">{factor.title}</span>
                      <span
                        className={cn(
                          "shrink-0 text-[13.5px] font-medium",
                          factor.strength === "сильное влияние"
                            ? "text-danger"
                            : factor.strength === "среднее влияние"
                              ? "text-warn"
                              : "text-ink-muted",
                        )}
                      >
                        {factor.strength}
                      </span>
                    </li>
                  ))
                )}
              </ul>
            </Card>

            <Card>
              <CardHeader
                title={
                  <span className="flex items-center gap-2">
                    Ограничения
                    <Info size={15} className="text-ink-muted" />
                  </span>
                }
              />
              <div className="space-y-2.5 p-5 pt-3 text-[14px] leading-relaxed text-ink-soft">
                {!field.crop ? (
                  <p>Культура не указана — прогноз основан на собственной истории поля</p>
                ) : null}
                {forecast?.insufficient_reason ? <p>{forecast.insufficient_reason}</p> : null}
                {analysis.nextScene ? (
                  <p>Следующий снимок ожидается около {formatDate(analysis.nextScene)}</p>
                ) : null}
                {(analysis.timeseries.data?.stats.restored ?? 0) > 0 ? (
                  <p>
                    Часть ряда восстановлена моделью — надёжность прогноза ограничена качеством
                    исходных наблюдений
                  </p>
                ) : null}
                <button
                  type="button"
                  onClick={() => setMethod(true)}
                  className="text-[14px] font-medium text-series-restored underline underline-offset-4"
                >
                  Как рассчитан прогноз
                </button>
              </div>
            </Card>
          </div>
        </div>

        {points.length > 0 ? (
          <section>
            <h3 className="mb-3 text-[20px] font-semibold text-ink">Прогноз по дням</h3>
            <div className="flex gap-2.5 overflow-x-auto pb-2 scroll-thin">
              {points.map((point) => {
                const tier = dayRisk.get(point.date) ?? "Средний";
                const isPeak =
                  level === "high" &&
                  peak !== null &&
                  point.date >= peak.from &&
                  point.date <= peak.to &&
                  tier === "Высокий";
                return (
                  <DayCard key={point.date} point={point} tier={tier} peak={isPeak} />
                );
              })}
            </div>
            <p className="mt-3 flex items-center justify-center gap-2 text-[14px] text-ink-muted">
              <RefreshCw size={16} />
              Прогноз обновится после нового спутникового наблюдения
            </p>
          </section>
        ) : null}
      </div>

      <InspectionChecklist
        open={checklist}
        onOpenChange={setChecklist}
        anomaly={analysis.worst}
        risk={risk}
      />

      <Modal
        open={method}
        onOpenChange={setMethod}
        title="Как рассчитан прогноз"
        className="w-[min(560px,calc(100vw-32px))]"
      >
        <div className="space-y-3 text-[14.5px] leading-relaxed text-ink-soft">
          <p>
            Прогноз строится на 14 дней вперёд от последнего пригодного наблюдения. Вход —
            восстановленный ряд NDVI поля, его собственная сезонная норма и прогноз погоды.
          </p>
          <p>
            Вместе со значением возвращается коридор вероятных значений. Он расширяется с
            горизонтом: чем дальше дата, тем меньше данных её подкрепляет.
          </p>
          <p>
            Уверенность прогноза{" "}
            {forecast?.confidence !== null && forecast?.confidence !== undefined
              ? formatPercent(forecast.confidence)
              : "не рассчитана"}{" "}
            учитывает плотность наблюдений, долю восстановленных значений и длину доступной
            истории поля.
          </p>
          {forecast?.model_version ? (
            <p className="text-ink-muted">Версия модели: {forecast.model_version}</p>
          ) : null}
        </div>
      </Modal>
    </div>
  );
}

function DayCard({
  point,
  tier,
  peak,
}: {
  point: Observation;
  tier: string;
  peak: boolean;
}) {
  const tone =
    tier === "Высокий"
      ? "border-danger-line bg-danger-tint"
      : tier === "Повышенный"
        ? "border-warn-line bg-warn-soft/60"
        : "border-line bg-white";

  const textTone =
    tier === "Высокий" ? "text-danger" : tier === "Повышенный" ? "text-warn" : "text-ink-soft";

  return (
    <div
      className={cn(
        "flex w-[104px] shrink-0 flex-col items-center gap-1.5 rounded-xl border px-2 py-3",
        tone,
        peak && "ring-2 ring-danger",
      )}
    >
      <span className="text-[13px] text-ink-soft">{formatDayMonth(point.date)}</span>
      {peak ? (
        <span className="rounded-md bg-danger-soft px-1.5 py-0.5 text-[11px] font-medium text-danger-ink">
          Пик риска
        </span>
      ) : null}
      <WeatherIcon precipitation={point.precipitation} temperature={point.temperature} />
      <span className="text-[14px] text-ink tnum">
        {point.temperature === null ? "—" : `${Math.round(point.temperature)}°`}
      </span>
      <span className={cn("text-[17px] font-semibold tnum", textTone)}>
        {formatNumber(point.ndvi_mean)}
      </span>
      <span className={cn("text-[12.5px]", textTone)}>{tier}</span>
    </div>
  );
}

function WeatherIcon({
  precipitation,
  temperature,
}: {
  precipitation: number | null;
  temperature: number | null;
}) {
  const size = 26;
  if (precipitation !== null && precipitation >= 3) {
    return <CloudRain size={size} className="text-series-precip" />;
  }
  if (precipitation !== null && precipitation >= 0.5) {
    return <Cloud size={size} className="text-ink-muted" />;
  }
  if (temperature !== null && temperature >= 30) {
    return <Sun size={size} className="text-warn" />;
  }
  return <CloudSun size={size} className="text-warn" />;
}

interface FactorRow {
  key: string;
  title: string;
  icon: React.ReactNode;
  tone: string;
  strength: string;
}

/** Что влияет на прогноз.
 *
 *  Основной источник — факторы самого прогона прогноза: текущее отставание от
 *  нормы, ожидаемое изменение за горизонт и свежесть последнего наблюдения.
 *  Именно из них модель и строит линию. Разложение составного риска берётся
 *  только как запасной вариант — оно объясняет текущее состояние, а не будущее,
 *  и карточка в этом случае называется иначе. */
function buildFactors(
  forecastFactors: Record<string, unknown> | null,
  breakdown: Record<string, number> | null,
): FactorRow[] {
  if (forecastFactors) {
    const rows: FactorRow[] = [];
    const deviation = numberOf(forecastFactors.deviation_from_norm);
    const change = numberOf(forecastFactors.change_over_horizon);
    const staleness = numberOf(forecastFactors.staleness_days);

    if (deviation !== null) {
      rows.push({
        key: "deviation",
        title: `Отклонение от нормы: ${formatNumber(deviation, 2)}`,
        icon: deviation < 0 ? <TrendingDown size={18} /> : <TrendingUp size={18} />,
        tone: deviation < 0 ? "bg-danger-soft text-danger" : "bg-ok-soft text-brand-700",
        // Пороги те же, по которым модель назначает уровень риска прогноза.
        strength: influence(Math.abs(deviation), 0.1, 0.05),
      });
    }
    if (change !== null) {
      rows.push({
        key: "change",
        title: `Ожидаемое изменение за горизонт: ${formatNumber(change, 2)}`,
        icon: change < 0 ? <TrendingDown size={18} /> : <TrendingUp size={18} />,
        tone: "bg-warn-soft text-warn",
        strength: influence(Math.abs(change), 0.05, 0.02),
      });
    }
    if (staleness !== null) {
      rows.push({
        key: "staleness",
        title: `Последнему наблюдению ${staleness} ${daysWord(staleness)}`,
        icon: <Clock size={18} />,
        tone: "bg-[#F1F2F4] text-ink-soft",
        strength: influence(staleness, 15, 7),
      });
    }
    if (rows.length > 0) return rows;
  }

  if (!breakdown) return [];

  const meta: Record<string, { title: string; icon: React.ReactNode; tone: string }> = {
    recent_trend: {
      title: "Нисходящий тренд NDVI",
      icon: <TrendingDown size={18} />,
      tone: "bg-ok-soft text-brand-700",
    },
    anomaly_severity: {
      title: "Глубина найденной аномалии",
      icon: <TrendingDown size={18} />,
      tone: "bg-danger-soft text-danger",
    },
    anomaly_duration: {
      title: "Длительность аномального периода",
      icon: <TrendingUp size={18} />,
      tone: "bg-warn-soft text-warn",
    },
    moisture: {
      title: "Снижение влажности по NDMI",
      icon: <Droplets size={18} />,
      tone: "bg-[#E6F5F5] text-series-ndmi",
    },
    weather: {
      title: "Погодные условия периода",
      icon: <Thermometer size={18} />,
      tone: "bg-[#FDECE5] text-series-temp",
    },
  };

  const entries = Object.entries(breakdown).filter(([, value]) => value > 0);
  if (entries.length === 0) return [];
  const max = Math.max(...entries.map(([, value]) => value));

  return entries
    .sort((a, b) => b[1] - a[1])
    .map(([key, value]) => {
      const info = meta[key] ?? {
        title: key,
        icon: <TrendingUp size={18} />,
        tone: "bg-[#F1F2F4] text-ink-soft",
      };
      const ratio = max > 0 ? value / max : 0;
      return {
        key,
        title: info.title,
        icon: info.icon,
        tone: info.tone,
        strength:
          ratio >= 0.66 ? "сильное влияние" : ratio >= 0.33 ? "среднее влияние" : "слабое влияние",
      };
    });
}

/** Уровень риска по дням.
 *
 *  Абсолютную оценку даёт бэкенд — это `risk_level` прогона, посчитанный по
 *  отставанию от нормы. Внутри горизонта прогноза мы только упорядочиваем дни
 *  по ожидаемому NDVI. Нормировать по min/max самого горизонта нельзя: при
 *  прогнозе 0,78 → 0,82 треть дней всё равно попадала бы в «Высокий», и
 *  благополучное поле краснело бы без всякого повода. */
function buildDayRisk(points: Observation[], level: string | null): Map<string, string> {
  const result = new Map<string, string>();
  const values = points
    .map((point) => point.ndvi_mean)
    .filter((value): value is number => value !== null);
  if (values.length === 0) return result;

  // Шкала подписей соответствует уровню риска всего прогноза.
  const scale =
    level === "high"
      ? ["Высокий", "Повышенный", "Средний"]
      : level === "moderate"
        ? ["Повышенный", "Средний", "Средний"]
        : ["Низкий", "Низкий", "Низкий"];

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;

  for (const point of points) {
    if (point.ndvi_mean === null) continue;
    const ratio = (point.ndvi_mean - min) / span;
    result.set(point.date, ratio <= 0.33 ? scale[0] : ratio <= 0.66 ? scale[1] : scale[2]);
  }
  return result;
}

/** Значение фактора приезжает из JSON, поэтому тип не гарантирован. */
function numberOf(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Словесная сила влияния по двум порогам. */
function influence(value: number, strong: number, medium: number): string {
  if (value >= strong) return "сильное влияние";
  if (value >= medium) return "среднее влияние";
  return "слабое влияние";
}

function confidenceWord(confidence: number | null): string {
  if (confidence === null) return "не рассчитана";
  if (confidence >= 0.8) return "высокая";
  if (confidence >= 0.6) return "средняя";
  return "низкая";
}
