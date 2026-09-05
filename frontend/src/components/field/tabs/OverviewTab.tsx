import {
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CloudRain,
  TriangleAlert,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import type { FieldAnalysis } from "@/hooks/useFieldAnalysis";
import { ChartLegend } from "@/components/charts/ChartLegend";
import { NdviChart } from "@/components/charts/NdviChart";
import { EvidencePanel } from "@/components/field/EvidencePanel";
import { FieldStatePanel, LAYER_OPTIONS, type LayerMode } from "@/components/field/FieldStatePanel";
import { InspectionChecklist } from "@/components/field/InspectionChecklist";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { Segmented } from "@/components/ui/Segmented";
import { cn } from "@/lib/cn";
import { trustOf } from "@/lib/trust";
import {
  daysWord,
  formatDateRangeShort,
  formatDayMonthLong,
  formatPercent,
  formatPeriod,
} from "@/lib/format";
import { dataQualityTitle, riskTone, RISK_LEVEL_TITLES, statusOf } from "@/lib/status";

interface OverviewTabProps {
  analysis: FieldAnalysis;
  projectId: string;
  onOpenTab: (tab: string) => void;
}

/** Обзор поля: сначала вывод и рекомендуемое действие, затем доказательства. */
export function OverviewTab({ analysis, projectId, onOpenTab }: OverviewTabProps) {
  const [mode, setMode] = useState<LayerMode>("ndvi");
  const [checklist, setChecklist] = useState(false);

  const field = analysis.field.data;
  const risk = analysis.risk.data;
  const forecast = analysis.forecast.data;
  const timeseries = analysis.timeseries.data;
  const worst = analysis.worst;
  if (!field) return null;

  const style = statusOf(risk?.status ?? field.status);
  // Доля пригодных пикселей считается по периоду анализа, а не по всей
  // истории поля: в сводке подпись «Качество данных» означает ровно это,
  // и две разные цифры под одним названием сбивали бы с толку.
  const validFractions = analysis.series.observed
    .map((point) => point.valid_fraction)
    .filter((value): value is number => value !== null);
  const meanValid = validFractions.length
    ? validFractions.reduce((sum, value) => sum + value, 0) / validFractions.length
    : null;
  const quality = dataQualityTitle(meanValid);
  const qualityGood = (meanValid ?? 0) >= 0.8;
  // Качество данных относится к периоду целиком, вердикт — к самому событию.
  // Когда событие есть, вопрос «можно ли ему верить» важнее, и «Качество
  // анализа» в шапке уступает ему место: два показателя об одном и том же
  // рядом друг с другом складывались в шум, а не в картину.
  const trust = trustOf(worst);

  return (
    <div className="space-y-4">
      {/* --- итог --- */}
      <div
        className={cn(
          "flex flex-wrap items-center gap-x-8 gap-y-5 rounded-2xl border border-l-[4px] bg-white px-6 py-5",
          style.border,
          risk?.status === "critical"
            ? "border-danger-line bg-danger-tint/40"
            : risk?.status === "attention"
              ? "border-warn-line bg-warn-soft/40"
              : "border-line",
        )}
      >
        <div className="shrink-0">
          <Chip className={style.chip} size="sm">
            {style.title}
          </Chip>
          <p className="mt-2">
            <span className={cn("text-[42px] font-semibold leading-none tnum", riskTone(risk?.score))}>
              {risk?.score === null || risk?.score === undefined ? "—" : Math.round(risk.score)}
            </span>
            <span className="ml-1.5 text-[20px] text-ink-muted">/ 100</span>
          </p>
        </div>

        <span className="h-14 w-px bg-line" />

        <div className="min-w-[260px] flex-1">
          <p className="text-[19px] font-semibold leading-snug text-ink">
            {worst
              ? `Устойчивое ухудшение с ${formatDayMonthLong(worst.start_date)}`
              : risk?.insufficient_reason
                ? "Данных недостаточно для вывода"
                : "Отклонений от ожидаемой динамики нет"}
          </p>
          <p className="mt-1 text-[14px] text-ink-soft">
            {worst
              ? `NDVI ниже ожидаемой динамики ${worst.duration_days} ${daysWord(worst.duration_days)} подряд`
              : (risk?.explanation?.[0] ??
                (risk?.insufficient_reason ?? "Ряд наблюдений соответствует норме поля"))}
          </p>
        </div>

        <span className="h-14 w-px bg-line" />

        <div className="shrink-0">
          <p className="text-[14px] text-ink-soft">Риск на ближайшие 14 дней</p>
          <p className="mt-1 text-[15px]">
            <span
              className={cn(
                "font-semibold",
                forecast?.risk_level === "high"
                  ? "text-danger"
                  : forecast?.risk_level === "moderate"
                    ? "text-warn"
                    : "text-ink",
              )}
            >
              {forecast?.risk_level
                ? RISK_LEVEL_TITLES[forecast.risk_level] ?? forecast.risk_level
                : "Не рассчитан"}
            </span>
            {analysis.peakRisk ? (
              <>
                <span className="mx-2 text-ink-muted">·</span>
                <span className="text-ink">
                  {formatDateRangeShort(analysis.peakRisk.from, analysis.peakRisk.to)}
                </span>
              </>
            ) : null}
          </p>
        </div>

        <div className="ml-auto flex shrink-0 items-center gap-5">
          {trust ? (
            <span className="flex items-center gap-2 text-[14px] text-ink-soft">
              {trust.tone === "good" ? (
                <CircleCheck size={18} className="text-ok" />
              ) : trust.tone === "warn" ? (
                <TriangleAlert size={18} className="text-warn" />
              ) : (
                <CircleAlert size={18} className="text-ink-muted" />
              )}
              {trust.title}
            </span>
          ) : (
            <span className="flex items-center gap-2 text-[14px] text-ink-soft">
              {qualityGood ? (
                <CircleCheck size={18} className="text-ok" />
              ) : (
                <CircleAlert size={18} className="text-warn" />
              )}
              Качество анализа: {quality}
            </span>
          )}
          <Button onClick={() => setChecklist(true)}>Что проверить при выезде</Button>
        </div>
      </div>

      {/* --- доказательства --- */}
      {trust ? <EvidencePanel trust={trust} /> : null}

      <div className="grid grid-cols-2 gap-4">
        <Card className="flex flex-col">
          <CardHeader
            title="Состояние поля"
            action={
              <Segmented
                value={mode}
                options={LAYER_OPTIONS}
                onChange={(value) => setMode(value as LayerMode)}
                size="sm"
              />
            }
          />
          <div className="p-5 pt-4">
            <FieldStatePanel field={field} observation={analysis.latest} mode={mode} height={344} />
          </div>
        </Card>

        <Card className="flex flex-col">
          <CardHeader
            title="Динамика NDVI"
            subtitle={formatPeriod(timeseries?.period_from, timeseries?.period_to)}
          />
          <div className="flex flex-1 flex-col p-5 pt-3">
            <NdviChart
              observations={analysis.series.historical}
              anomalies={analysis.anomalies.data ?? []}
              today={null}
              showRestored={false}
              showForecast={false}
              height={300}
              compact
            />
            <div className="mt-3 flex items-center justify-between gap-4">
              <ChartLegend
                items={[
                  { label: "Наблюдаемое", color: "#0F4730", mark: "solid" },
                  { label: "Ожидаемая динамика", color: "#9CA1AC", mark: "dashed" },
                  // Красная заливка — самый заметный элемент графика, и до сих
                  // пор единственный, который ничем не объяснялся.
                  ...((analysis.anomalies.data?.length ?? 0) > 0
                    ? [
                        {
                          label: "Отклонение от нормы",
                          color: "#E5252C",
                          mark: "span" as const,
                        },
                      ]
                    : []),
                ]}
              />
              <button
                type="button"
                onClick={() => onOpenTab("dynamics")}
                className="flex shrink-0 items-center gap-1.5 text-[14px] font-medium text-brand-700 hover:underline"
              >
                Открыть подробную динамику
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
        </Card>
      </div>

      {/* --- переходы к деталям --- */}
      <div className="grid grid-cols-3 gap-4">
        <LinkCard
          icon={<TriangleAlert size={22} />}
          tone="danger"
          title={
            (analysis.anomalies.data?.length ?? 0) > 0
              ? `Найдено ${analysis.anomalies.data?.length} ${anomalyWord(analysis.anomalies.data?.length ?? 0)}`
              : "Аномалий не найдено"
          }
          subtitle={
            worst
              ? `Максимальное отклонение ${analysis.deviation !== null ? formatPercent(Math.abs(analysis.deviation)) : "—"} от ожидаемой динамики`
              : "Ряд соответствует норме поля"
          }
          onClick={() => onOpenTab("dynamics")}
        />
        <LinkCard
          icon={<CircleAlert size={22} />}
          tone="warn"
          title="Прогноз на 14 дней"
          // Формулировки описывают ожидаемую динамику и не переходят
          // к причинам и назначениям: тех же правил держатся промпты LLM.
          subtitle={
            forecast?.insufficient_reason ??
            (forecast?.direction === "declining"
              ? "Ожидается дальнейшее снижение NDVI"
              : forecast?.direction === "improving"
                ? "Ожидается восстановление вегетации"
                : "Существенных изменений не ожидается")
          }
          to={`/p/${projectId}/field/${field.id}/forecast`}
        />
        <LinkCard
          icon={<CloudRain size={22} />}
          tone="info"
          title="Погодный контекст"
          subtitle={weatherSummary(analysis)}
          onClick={() => onOpenTab("dynamics")}
        />
      </div>

      <InspectionChecklist
        open={checklist}
        onOpenChange={setChecklist}
        anomaly={worst}
        risk={risk}
      />
    </div>
  );
}

function LinkCard({
  icon,
  tone,
  title,
  subtitle,
  onClick,
  to,
}: {
  icon: React.ReactNode;
  tone: "danger" | "warn" | "info";
  title: string;
  subtitle: string;
  onClick?: () => void;
  to?: string;
}) {
  const tones = {
    danger: "bg-danger-soft text-danger",
    warn: "bg-warn-soft text-warn",
    info: "bg-[#EAF1FD] text-series-precip",
  } as const;

  const content = (
    <>
      <span className={cn("flex h-11 w-11 shrink-0 items-center justify-center rounded-full", tones[tone])}>
        {icon}
      </span>
      <span className="min-w-0 flex-1 text-left">
        <span className="block text-[16px] font-semibold text-ink">{title}</span>
        <span className="mt-0.5 block truncate text-[13.5px] text-ink-soft">{subtitle}</span>
      </span>
      <ChevronRight size={19} className="shrink-0 text-ink-muted" />
    </>
  );

  const className =
    "card flex w-full items-center gap-4 px-5 py-4 transition-shadow hover:shadow-pop";

  return to ? (
    <Link to={to} className={className}>
      {content}
    </Link>
  ) : (
    <button type="button" onClick={onClick} className={className}>
      {content}
    </button>
  );
}

function anomalyWord(count: number): string {
  const tens = count % 100;
  if (tens >= 11 && tens <= 14) return "аномалий";
  const last = count % 10;
  if (last === 1) return "аномалия";
  if (last >= 2 && last <= 4) return "аномалии";
  return "аномалий";
}

/** Короткая сводка погоды внутри аномального периода — только по фактам ряда. */
function weatherSummary(analysis: FieldAnalysis): string {
  const worst = analysis.worst;
  const points = analysis.series.historical.filter(
    (point) =>
      worst && point.date >= worst.start_date && point.date <= worst.end_date,
  );
  if (!worst || points.length === 0) return "Температура и осадки за период анализа";

  const temperatures = points
    .map((point) => point.temperature)
    .filter((value): value is number => value !== null);
  const precipitation = points
    .map((point) => point.precipitation)
    .filter((value): value is number => value !== null);

  if (temperatures.length === 0 && precipitation.length === 0) {
    return "Погодные данные за период недоступны";
  }

  const meanTemp = temperatures.length
    ? Math.round(temperatures.reduce((sum, value) => sum + value, 0) / temperatures.length)
    : null;
  const totalRain = precipitation.length
    ? Math.round(precipitation.reduce((sum, value) => sum + value, 0))
    : null;

  const parts: string[] = [];
  if (meanTemp !== null) parts.push(`средняя температура ${meanTemp} °C`);
  if (totalRain !== null) parts.push(`осадки ${totalRain} мм`);
  return `За период аномалии: ${parts.join(", ")}`;
}
