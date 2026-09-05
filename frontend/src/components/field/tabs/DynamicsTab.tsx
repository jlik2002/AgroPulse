import { ChevronRight, TriangleAlert } from "lucide-react";
import { useState } from "react";

import type { FieldAnalysis } from "@/hooks/useFieldAnalysis";
import { ChartLegend } from "@/components/charts/ChartLegend";
import { MiniSeriesChart } from "@/components/charts/MiniSeriesChart";
import { NdviChart } from "@/components/charts/NdviChart";
import { Card, CardHeader } from "@/components/ui/Card";
import { Checkbox } from "@/components/ui/Checkbox";
import { Tooltip } from "@/components/ui/Tooltip";
import { formatDateRangeShort, formatPeriod } from "@/lib/format";
import { CircleHelp } from "lucide-react";

interface DynamicsTabProps {
  analysis: FieldAnalysis;
  onOpenScenes: (range: { from: string; to: string } | null) => void;
}

/** Подробная временная картина: NDVI, происхождение каждого значения,
 *  прогноз и погодный контекст на общей оси времени. */
export function DynamicsTab({ analysis, onOpenScenes }: DynamicsTabProps) {
  const [showExpected, setShowExpected] = useState(true);
  const [showWeather, setShowWeather] = useState(true);
  const [showRestored, setShowRestored] = useState(true);

  const timeseries = analysis.timeseries.data;
  const anomalies = analysis.anomalies.data ?? [];
  const worst = analysis.worst;

  const weatherObservations = analysis.series.all;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-5">
          <h2 className="text-[22px] font-semibold text-ink">Динамика и погодный контекст</h2>
          <span className="rounded-xl border border-line bg-white px-3.5 py-2 text-[14px] text-ink">
            {formatPeriod(
              timeseries?.period_from,
              analysis.series.lastForecast?.date ?? timeseries?.period_to,
            )}
          </span>
        </div>

        <div className="flex items-center gap-3">
          <Toggle label="Ожидаемая кривая" checked={showExpected} onChange={setShowExpected} />
          <Toggle label="Погода" checked={showWeather} onChange={setShowWeather} />
          <Toggle label="Восстановленные" checked={showRestored} onChange={setShowRestored} />
        </div>
      </div>

      <Card>
        <CardHeader
          title="NDVI"
          subtitle="Наблюдения, восстановленные значения и прогноз на 14 дней"
        />
        <div className="p-5 pt-3">
          <NdviChart
            observations={analysis.series.all}
            anomalies={anomalies}
            today={analysis.series.today}
            showExpected={showExpected}
            showRestored={showRestored}
            height={340}
          />
          <ChartLegend
            className="mt-3"
            items={[
              { label: "Наблюдаемое", color: "#0F4730", mark: "solid" },
              ...(showRestored
                ? [{ label: "Восстановленное", color: "#2A74DD", mark: "dashed-dot" as const }]
                : []),
              ...(showExpected
                ? [{ label: "Ожидаемая динамика", color: "#9CA1AC", mark: "dashed" as const }]
                : []),
              { label: "Прогноз", color: "#7B49BF", mark: "solid" },
              { label: "Диапазон прогноза", color: "#7B49BF", mark: "area" },
            ]}
          />
        </div>
      </Card>

      {showWeather ? (
        <div className="grid grid-cols-4 gap-4">
          <Card>
            <CardHeader
              title={
                <span className="flex items-center gap-2 text-[15px]">
                  NDMI · влажность
                  <Tooltip content="Индекс влагосодержания растительности. Снижается при водном стрессе раньше, чем NDVI.">
                    <span className="text-ink-muted">
                      <CircleHelp size={15} />
                    </span>
                  </Tooltip>
                </span>
              }
            />
            <div className="px-3 pb-4 pt-1">
              <MiniSeriesChart
                observations={weatherObservations}
                metric="ndmi"
                anomalies={anomalies}
                today={analysis.series.today}
              />
            </div>
          </Card>

          <Card>
            <CardHeader title={<span className="text-[15px]">Температура, °C</span>} />
            <div className="px-3 pb-4 pt-1">
              <MiniSeriesChart
                observations={weatherObservations}
                metric="temperature"
                anomalies={anomalies}
                today={analysis.series.today}
              />
            </div>
          </Card>

          <Card>
            <CardHeader title={<span className="text-[15px]">Осадки, мм</span>} />
            <div className="px-3 pb-4 pt-1">
              <MiniSeriesChart
                observations={weatherObservations}
                metric="precipitation"
                anomalies={anomalies}
                today={analysis.series.today}
              />
            </div>
          </Card>

          <Card className="flex flex-col justify-between border-danger-line bg-danger-tint p-5">
            {worst ? (
              <>
                <div className="flex items-start gap-3.5">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-danger-soft text-danger">
                    <TriangleAlert size={20} />
                  </span>
                  <p className="text-[16px] font-semibold leading-snug text-ink">
                    {coincidenceText(analysis)}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    onOpenScenes({ from: worst.start_date, to: worst.end_date })
                  }
                  className="mt-4 flex items-center gap-1.5 text-left text-[14px] font-medium text-brand-700 hover:underline"
                >
                  Посмотреть снимки за {formatDateRangeShort(worst.start_date, worst.end_date)}
                  <ChevronRight size={16} />
                </button>
              </>
            ) : (
              <p className="text-[15px] leading-relaxed text-ink-soft">
                Совпадений снижения NDVI с погодными условиями не зафиксировано:
                аномальных периодов в ряду нет.
              </p>
            )}
          </Card>
        </div>
      ) : null}
    </div>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <span className="rounded-xl border border-line bg-white px-3.5 py-2">
      <Checkbox label={label} checked={checked} onChange={onChange} />
    </span>
  );
}

/** Формулировка совпадения. Сервис показывает совпадение во времени,
 *  но не выдаёт его за доказанную причину — это принцип интерфейса. */
function coincidenceText(analysis: FieldAnalysis): string {
  const worst = analysis.worst;
  if (!worst) return "Аномальных периодов не найдено";

  const inside = analysis.series.historical.filter(
    (point) => point.date >= worst.start_date && point.date <= worst.end_date,
  );
  const temperatures = inside
    .map((point) => point.temperature)
    .filter((value): value is number => value !== null);
  const rain = inside
    .map((point) => point.precipitation)
    .filter((value): value is number => value !== null);

  const hot =
    temperatures.length > 0 &&
    temperatures.reduce((sum, value) => sum + value, 0) / temperatures.length >= 27;
  const dry = rain.length > 0 && rain.reduce((sum, value) => sum + value, 0) < 10;

  if (hot && dry) return "Снижение NDVI совпало с жаркой и сухой погодой";
  if (dry) return "Снижение NDVI совпало с дефицитом осадков";
  if (hot) return "Снижение NDVI совпало с повышенной температурой";
  return "Снижение NDVI не совпало с выраженными погодными факторами";
}
