import {
  ChevronRight,
  CircleHelp,
  CircleAlert,
  FileText,
  Sprout,
  TriangleAlert,
  TrendingUp,
  CircleCheck,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useProjectSummary } from "@/api/queries";
import type { FieldSummary } from "@/api/types";
import { useProjectContext } from "@/app/ProjectContext";
import { FieldShape } from "@/components/map/FieldShapes";
import { FitBounds, MapCanvas } from "@/components/map/MapCanvas";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { EmptyState, ErrorState, Loading } from "@/components/ui/State";
import { cn } from "@/lib/cn";
import {
  formatArea,
  formatDateRangeShort,
  formatPercent,
  formatPeriod,
  daysWord,
} from "@/lib/format";
import { combinedBounds } from "@/lib/geo";
import { dataQualityTitle, riskTone, SEVERITY_TITLES, statusOf } from "@/lib/status";

/** Сводный дашборд: что требует внимания и куда ехать в первую очередь.
 *
 *  Поля ранжируются по составному риску. Цвет — дополнительный сигнал,
 *  рядом всегда стоит текстовый статус. */
export function SummaryPage() {
  const navigate = useNavigate();
  const { project, fields, indexOf } = useProjectContext();
  const summary = useProjectSummary(project.id, { refetchInterval: 20_000 });
  const [hovered, setHovered] = useState<string | null>(null);

  const geometryOf = useMemo(
    () => new Map(fields.map((field) => [field.id, field.geometry])),
    [fields],
  );

  const bounds = useMemo(
    () => combinedBounds(fields.map((field) => field.geometry)),
    [fields],
  );

  const events = useMemo(() => buildEvents(summary.data?.fields ?? []), [summary.data]);

  if (summary.isPending) return <Loading text="Собираем сводку" />;
  if (summary.isError) {
    return (
      <div className="mx-auto max-w-2xl px-9 py-12">
        <ErrorState error={summary.error} />
      </div>
    );
  }

  const data = summary.data;
  const title = project.name?.trim() || "Проект без названия";

  return (
    <div className="px-9 py-7">
      <div className="flex items-start justify-between gap-8">
        <div>
          <h1 className="text-[30px] font-semibold leading-tight text-ink">{title}</h1>
          <p className="mt-1.5 text-[15px] text-ink-muted">
            Анализ за {formatPeriod(data.period_from, data.period_to)}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-3">
          <Button variant="outline" size="lg" asChild>
            <Link to={`/p/${project.id}/reports`}>
              <FileText size={18} />
              Сформировать отчёт
            </Link>
          </Button>
          <Button size="lg" asChild>
            <Link to={`/p/${project.id}/fields`}>Новый анализ</Link>
          </Button>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-4 gap-4">
        <StatCard
          icon={<Sprout size={22} />}
          tone="brand"
          value={data.total_fields}
          label="Всего полей"
        />
        <StatCard
          icon={<TriangleAlert size={22} />}
          tone="danger"
          value={data.critical}
          label="Критическое"
        />
        <StatCard
          icon={<CircleAlert size={22} />}
          tone="warn"
          value={data.attention}
          label="Требует внимания"
        />
        <StatCard
          icon={<CircleHelp size={22} />}
          tone="muted"
          value={data.insufficient_data}
          label="Недостаточно данных"
        />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4">
        {/* --- карта состояния --- */}
        <Card className="flex flex-col">
          <CardHeader title="Состояние полей на карте" />
          <div className="relative m-5 mt-4 flex-1 overflow-hidden rounded-xl border border-line">
            <MapCanvas basemap="satellite" className="min-h-[360px]">
              <FitBounds bounds={bounds} padding={30} />
              {data.fields.map((row) => {
                const geometry = geometryOf.get(row.field_id);
                if (!geometry) return null;
                const style = statusOf(row.status);
                return (
                  <FieldShape
                    key={row.field_id}
                    geometry={geometry}
                    index={indexOf(row.field_id)}
                    style={{
                      color: style.map,
                      fillOpacity: hovered === row.field_id ? 0.72 : 0.55,
                      weight: 2.5,
                    }}
                    label={`${row.name} · ${style.title}`}
                    onClick={() => navigate(`/p/${project.id}/field/${row.field_id}`)}
                  />
                );
              })}
            </MapCanvas>

            <div className="absolute bottom-4 left-4 z-[500] flex items-center gap-5 rounded-xl bg-white/95 px-4 py-2.5 shadow-card">
              <LegendDot color="#E5252C" label="Критическое" />
              <LegendDot color="#E9A317" label="Требует внимания" />
              <LegendDot color="#0F4730" label="Без аномалий" />
            </div>
          </div>
        </Card>

        {/* --- приоритет выезда --- */}
        <Card className="flex flex-col">
          <CardHeader
            title="Приоритет выезда"
            subtitle="Начните с поля с наибольшим риском"
          />
          <div className="space-y-3 p-5 pt-4">
            {data.fields.length === 0 ? (
              <EmptyState
                title="В проекте пока нет обработанных полей"
                description="Добавьте поля на карте и запустите анализ."
              />
            ) : (
              data.fields.map((row) => (
                <PriorityCard
                  key={row.field_id}
                  row={row}
                  onHover={setHovered}
                  href={`/p/${project.id}/field/${row.field_id}`}
                />
              ))
            )}
          </div>
        </Card>
      </div>

      {events.length > 0 ? (
        <Card className="mt-4">
          <CardHeader
            title="Последние события"
            action={
              <Link
                to={`/p/${project.id}/data`}
                className="flex items-center gap-1.5 text-[14px] font-medium text-brand-700 hover:underline"
              >
                Смотреть все
                <ChevronRight size={16} />
              </Link>
            }
          />
          <ul className="divide-y divide-line-soft px-5 pb-2 pt-3">
            {events.map((event) => (
              <li key={event.key} className="flex items-center gap-3.5 py-3">
                <span className={cn("shrink-0", event.tone)}>{event.icon}</span>
                <span className="min-w-0 flex-1 text-[14px] text-ink">{event.text}</span>
                <span className="shrink-0 text-[13px] text-ink-muted">{event.when}</span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}

function StatCard({
  icon,
  tone,
  value,
  label,
}: {
  icon: React.ReactNode;
  tone: "brand" | "danger" | "warn" | "muted";
  value: number;
  label: string;
}) {
  const tones = {
    brand: "bg-ok-soft text-brand-700",
    danger: "bg-danger-soft text-danger",
    warn: "bg-warn-soft text-warn",
    muted: "bg-[#F1F2F4] text-ink-muted",
  } as const;

  return (
    <Card className="flex items-center gap-4 px-5 py-4">
      <span className={cn("flex h-12 w-12 items-center justify-center rounded-full", tones[tone])}>
        {icon}
      </span>
      <span>
        <span className="block text-[26px] font-semibold leading-none text-ink tnum">{value}</span>
        <span className="mt-1.5 block text-[14px] text-ink-soft">{label}</span>
      </span>
    </Card>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-2 text-[13px] text-ink">
      <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
      {label}
    </span>
  );
}

function PriorityCard({
  row,
  onHover,
  href,
}: {
  row: FieldSummary;
  onHover: (id: string | null) => void;
  href: string;
}) {
  const style = statusOf(row.status);
  const anomaly = row.worst_anomaly;

  const reason = anomaly
    ? `NDVI ниже нормы ${anomaly.duration_days} ${daysWord(anomaly.duration_days)} подряд`
    : row.status === "insufficient_data"
      ? "Пригодных снимков недостаточно для вывода"
      : "Отклонений от ожидаемой динамики не найдено";

  return (
    <div
      onMouseEnter={() => onHover(row.field_id)}
      onMouseLeave={() => onHover(null)}
      className={cn(
        "rounded-2xl border border-l-[3px] border-line bg-white px-5 py-4 transition-shadow hover:shadow-card",
        style.border,
      )}
    >
      <div className="flex items-start gap-4">
        <span
          className={cn(
            "flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-[15px] font-semibold",
            row.inspection_rank ? style.chip : "bg-[#F1F2F4] text-ink-muted",
          )}
        >
          {row.inspection_rank ? `#${row.inspection_rank}` : "—"}
        </span>

        <div className="min-w-0 flex-1">
          <p className="truncate text-[18px] font-semibold leading-snug text-ink">{row.name}</p>
          <p className="mt-0.5 text-[14px] text-ink-soft">
            {formatArea(row.area_ha)} · {row.crop ?? "культура не указана"}
          </p>
          <Chip className={cn("mt-2", style.chip)} size="sm">
            {style.title}
          </Chip>
        </div>

        <div className="shrink-0 text-right">
          <p className="text-[13px] text-ink-muted">Риск</p>
          <p className="mt-0.5">
            <span className={cn("text-[28px] font-semibold leading-none tnum", riskTone(row.risk_score))}>
              {row.risk_score === null ? "—" : Math.round(row.risk_score)}
            </span>
            <span className="ml-1 text-[15px] text-ink-muted">/ 100</span>
          </p>
        </div>
      </div>

      <div className="mt-3.5 space-y-2">
        <p className="flex items-start gap-2.5 text-[14px] text-ink">
          <TrendingUp size={17} className={cn("mt-0.5 shrink-0", style.accent)} />
          {reason}
        </p>
        <div className="flex items-center gap-2.5">
          <CircleCheck size={17} className="shrink-0 text-ok" />
          <span className="text-[14px] text-ink-soft">
            Качество данных: {dataQualityTitle(row.mean_valid_fraction)}
            {row.mean_valid_fraction !== null
              ? ` · покрытие ${formatPercent(row.mean_valid_fraction)}`
              : ""}
          </span>
          <Button size="sm" variant={row.inspection_rank === 1 ? "primary" : "ghost"} asChild className="ml-auto">
            <Link to={href}>Открыть поле</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}

interface SummaryEvent {
  key: string;
  icon: React.ReactNode;
  tone: string;
  text: string;
  when: string;
}

/** Лента событий собирается из результатов анализа, а не из отдельного журнала:
 *  пользователю важны найденные аномалии и поля без данных. */
function buildEvents(rows: FieldSummary[]): SummaryEvent[] {
  const events: SummaryEvent[] = [];

  for (const row of rows) {
    if (row.worst_anomaly) {
      const anomaly = row.worst_anomaly;
      events.push({
        key: `${row.field_id}-anomaly`,
        icon: <TriangleAlert size={18} />,
        tone: anomaly.severity === "critical" ? "text-danger" : "text-warn",
        text: `${row.name} — ${SEVERITY_TITLES[anomaly.severity].toLowerCase()}, ${anomaly.duration_days} ${daysWord(anomaly.duration_days)}`,
        when: formatDateRangeShort(anomaly.start_date, anomaly.end_date),
      });
    } else if (row.status === "insufficient_data") {
      events.push({
        key: `${row.field_id}-insufficient`,
        icon: <CircleHelp size={18} />,
        tone: "text-ink-muted",
        text: `${row.name} — пригодных снимков недостаточно для вывода`,
        when: `${row.observed_points} наблюдений`,
      });
    }
  }

  return events.slice(0, 6);
}
