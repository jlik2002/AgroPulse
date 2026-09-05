import type { Anomaly, Field, Observation, Risk } from "@/api/types";
import { Logo } from "@/components/layout/Logo";
import { NdviChart } from "@/components/charts/NdviChart";
import { FieldStatePanel } from "@/components/field/FieldStatePanel";
import { cn } from "@/lib/cn";
import {
  daysWord,
  formatDate,
  formatDayMonthLong,
  formatPercent,
  formatPeriod,
} from "@/lib/format";
import { statusOf } from "@/lib/status";

interface ReportPreviewProps {
  field: Field | null;
  client: string;
  periodFrom: string;
  periodTo: string;
  risk: Risk | undefined;
  anomaly: Anomaly | null;
  observations: Observation[];
  latest: Observation | null;
  deviation: number | null;
  peakRisk: { from: string; to: string } | null;
  totalPages: number;
}

/** Предпросмотр первой страницы отчёта.
 *
 *  Собирается из тех же значений, что уйдут в PDF, поэтому пользователь
 *  видит настоящий документ, а не абстрактный макет. Точная вёрстка PDF
 *  остаётся за WeasyPrint — здесь показывается её первая страница. */
export function ReportPreview({
  field,
  client,
  periodFrom,
  periodTo,
  risk,
  anomaly,
  observations,
  latest,
  deviation,
  peakRisk,
  totalPages,
}: ReportPreviewProps) {
  if (!field) return null;
  const style = statusOf(risk?.status ?? field.status);
  // Про пик риска пишем только тогда, когда риск действительно повышен:
  // на спокойном поле такая фраза противоречила бы выводу выше.
  const elevated = risk?.status === "critical" || risk?.status === "attention";

  return (
    <article className="flex h-full w-full flex-col bg-white px-9 py-8 text-ink">
      <header className="flex items-center justify-between border-b border-line-soft pb-4">
        <Logo size={24} />
        <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-ink-muted">
          Отчёт о состоянии поля
        </span>
      </header>

      <h1 className="mt-6 text-[28px] font-semibold leading-tight">{field.name}</h1>
      <p className="mt-1.5 text-[13px] text-ink-soft">
        {client ? `${client} · ` : ""}
        {formatPeriod(periodFrom, periodTo)}
      </p>

      <div
        className={cn(
          "mt-4 flex items-center gap-2.5 rounded-xl border px-4 py-2.5 text-[13.5px]",
          risk?.status === "critical"
            ? "border-danger-line bg-danger-tint text-danger-ink"
            : risk?.status === "attention"
              ? "border-warn-line bg-warn-soft text-warn-ink"
              : "border-ok-line bg-ok-soft text-ok-ink",
        )}
      >
        <span className="font-medium">{style.title}</span>
        {risk?.score !== null && risk?.score !== undefined ? (
          <>
            <span>·</span>
            <span>риск {Math.round(risk.score)} / 100</span>
          </>
        ) : null}
      </div>

      <h2 className="mt-6 text-[16px] font-semibold">Краткий вывод</h2>
      <div className="mt-2 space-y-1 text-[13px] leading-relaxed text-ink-soft">
        {anomaly ? (
          <p>
            С {formatDayMonthLong(anomaly.start_date)} наблюдается устойчивое снижение NDVI
            ({anomaly.duration_days} {daysWord(anomaly.duration_days)}).
          </p>
        ) : (
          <p>Устойчивых отклонений от собственной динамики поля не обнаружено.</p>
        )}
        {deviation !== null ? (
          <p>
            Максимальное отклонение от ожидаемой динамики — {formatPercent(Math.abs(deviation))}.
          </p>
        ) : null}
        {peakRisk && elevated ? (
          <p>
            Наиболее рискованный период прогноза — {formatDate(peakRisk.from)} —{" "}
            {formatDate(peakRisk.to)}.
          </p>
        ) : null}
        {risk?.insufficient_reason ? <p>{risk.insufficient_reason}</p> : null}
      </div>

      <div className="mt-6 grid flex-1 grid-cols-2 gap-5 border-t border-line-soft pt-5">
        <div className="flex min-h-0 flex-col">
          <h3 className="text-[13px] font-semibold">
            NDVI{latest ? ` (${formatDate(latest.date)})` : ""}
          </h3>
          <div className="mt-2 min-h-0 flex-1">
            <FieldStatePanel field={field} observation={latest} mode="ndvi" height={210} />
          </div>
        </div>

        <div className="flex min-h-0 flex-col">
          <h3 className="text-[13px] font-semibold">Динамика среднего NDVI</h3>
          <div className="mt-1 min-h-0 flex-1">
            <NdviChart
              observations={observations}
              anomalies={anomaly ? [anomaly] : []}
              showRestored={false}
              showForecast={false}
              height={190}
              compact
            />
          </div>
        </div>
      </div>

      <footer className="mt-5 flex items-center justify-between border-t border-line-soft pt-3 text-[11px] text-ink-muted">
        <span>Сформировано AgroPulse · {formatDate(new Date())}</span>
        <span>1 / {totalPages}</span>
      </footer>
    </article>
  );
}
