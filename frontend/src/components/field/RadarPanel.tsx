import { Radar, TriangleAlert } from "lucide-react";

import type { Anomaly, RadarEvent, RadarSeries } from "@/api/types";
import { ChartLegend } from "@/components/charts/ChartLegend";
import { RadarChart } from "@/components/charts/RadarChart";
import { Card, CardHeader } from "@/components/ui/Card";
import { Tooltip } from "@/components/ui/Tooltip";
import { formatDayMonth, formatNumber, parseDate } from "@/lib/format";
import { CircleHelp } from "lucide-react";

interface RadarPanelProps {
  radar: RadarSeries | undefined;
  anomalies: Anomaly[];
  today?: string | null;
}

const ORBIT_LABELS: Record<string, string> = {
  ascending: "восходящая",
  descending: "нисходящая",
};

/** Радарный блок вкладки «Динамика».
 *
 *  Радар показан отдельно от NDVI, а не подмешан к нему, и это продуктовое
 *  решение: он измеряет другую величину — структуру полога и состояние
 *  поверхности, а не спектральное состояние листа. Ценность именно в том,
 *  что источники независимы, и совпадение события в обоих означает больше,
 *  чем любая из кривых по отдельности. */
export function RadarPanel({ radar, anomalies, today }: RadarPanelProps) {
  const points = radar?.points ?? [];
  const usable = points.filter((point) => point.vh_median_db !== null);

  if (usable.length === 0) {
    return (
      <Card>
        <CardHeader title="Радар Sentinel-1" subtitle="Независимая проверка состояния поля" />
        <p className="px-5 pb-5 pt-1 text-[15px] leading-relaxed text-ink-soft">
          Радарных наблюдений по этому полю нет. Выводы опираются только на
          оптический ряд, и подтвердить их вторым источником нельзя.
        </p>
      </Card>
    );
  }

  const orbits = new Set(
    usable.map((point) => `${point.orbit_direction ?? "?"}:${point.relative_orbit ?? "?"}`),
  );
  const dominant = usable[usable.length - 1];
  const events = radar?.events ?? [];

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            Радар Sentinel-1
            <Tooltip content="Радар измеряет структуру растительности и состояние поверхности. Он не зависит от облаков и работает ночью, поэтому подтверждает или опровергает то, что показала оптика.">
              <span className="text-ink-muted">
                <CircleHelp size={15} />
              </span>
            </Tooltip>
          </span>
        }
        subtitle={`Обратное рассеяние, дБ · ${usable.length} съёмок · орбита ${
          ORBIT_LABELS[dominant.orbit_direction ?? ""] ?? "неизвестна"
        }`}
      />
      <div className="p-5 pt-3">
        <RadarChart points={points} anomalies={anomalies} today={today} height={280} />
        <ChartLegend
          className="mt-3"
          items={[
            { label: "VH · структура растительности", color: "#1F7A4D", mark: "solid" },
            { label: "VV · поверхность почвы", color: "#B4531F", mark: "solid" },
            ...(anomalies.length > 0
              ? [{ label: "Отклонение NDVI от нормы", color: "#E5252C", mark: "span" as const }]
              : []),
          ]}
        />

        {orbits.size > 1 ? (
          <p className="mt-3 text-[13px] leading-relaxed text-ink-muted">
            Поле снимают {orbits.size} орбиты. Линией соединена только основная:
            у разных орбит разный угол падения луча, и их уровни сигнала напрямую
            не сравниваются. Точки остальных орбит показаны без линии.
          </p>
        ) : null}

        {events.length > 0 ? (
          <div className="mt-5 space-y-2.5">
            <h4 className="text-[15px] font-semibold text-ink">Резкие изменения сигнала</h4>
            {events.map((event) => (
              <RadarEventRow key={`${event.date}-${event.kind}`} event={event} />
            ))}
          </div>
        ) : null}
      </div>
    </Card>
  );
}

function RadarEventRow({ event }: { event: RadarEvent }) {
  const negative = event.kind === "vegetation_drop";
  return (
    <div className="flex items-start gap-3 rounded-xl border border-line bg-surface px-4 py-3">
      <span
        className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
          negative ? "bg-danger-soft text-danger" : "bg-brand-50 text-brand-700"
        }`}
      >
        {negative ? <TriangleAlert size={16} /> : <Radar size={16} />}
      </span>
      <div className="min-w-0">
        <p className="text-[14.5px] font-medium text-ink">
          {formatDayMonth(parseDate(event.date))} · {event.title}
        </p>
        <p className="mt-0.5 text-[13.5px] leading-relaxed text-ink-soft">
          Изменение {formatNumber(event.magnitude_db, 1)} дБ
          {event.score !== null
            ? ` · резче ${formatNumber(event.score * 100, 0)}% переходов этого поля`
            : ""}
        </p>
        {/* Скачок, который на следующей съёмке отыгрался назад, — это погода,
            а не событие на поле, и такие сюда не попадают. Но у последнего
            снимка орбиты проверить нечем, и об этом нужно сказать прямо. */}
        {!event.confirmed ? (
          <p className="mt-0.5 text-[13.5px] leading-relaxed text-ink-muted">
            Удержание нового уровня не подтверждено: следующей съёмки той же
            орбиты в ряду нет.
          </p>
        ) : null}
        {/* Радар не выбирает между причинами — он их перечисляет. */}
        <p className="mt-1 text-[13.5px] leading-relaxed text-ink-muted">
          Возможные причины: {event.hypotheses.join(", ")}.
        </p>
      </div>
    </div>
  );
}
