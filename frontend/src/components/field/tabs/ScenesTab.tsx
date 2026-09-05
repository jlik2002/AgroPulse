import { ChevronLeft, ChevronRight, CircleAlert, TrendingUp } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Anomaly, Field, Observation } from "@/api/types";
import type { FieldAnalysis } from "@/hooks/useFieldAnalysis";
import { FieldStatePanel, LAYER_OPTIONS, type LayerMode } from "@/components/field/FieldStatePanel";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Chip } from "@/components/ui/Chip";
import { Segmented } from "@/components/ui/Segmented";
import { Switch } from "@/components/ui/Switch";
import { EmptyState } from "@/components/ui/State";
import { cn } from "@/lib/cn";
import { formatDate, formatDayMonth, formatNumber, formatPercent } from "@/lib/format";
import { ndmiColor, ndviColor, SEVERITY_TITLES } from "@/lib/status";

interface ScenesTabProps {
  analysis: FieldAnalysis;
  /** Диапазон, на который нужно навести сравнение при переходе с динамики. */
  focus: { from: string; to: string } | null;
  onShowOnChart: () => void;
}

/** Сравнение состояния поля между двумя датами.
 *
 *  Обе панели показывают один и тот же участок в одинаковом масштабе —
 *  иначе разница в кадре читалась бы как разница в состоянии. */
export function ScenesTab({ analysis, focus, onShowOnChart }: ScenesTabProps) {
  const [mode, setMode] = useState<LayerMode>("ndvi");
  const [compare, setCompare] = useState(true);
  const [leftDate, setLeftDate] = useState<string | null>(null);
  const [rightDate, setRightDate] = useState<string | null>(null);
  const stripRef = useRef<HTMLDivElement>(null);
  const rightRef = useRef<HTMLButtonElement>(null);

  const field = analysis.field.data;
  const scenes = useMemo(
    () => analysis.series.observed.filter((point) => point.ndvi_mean !== null),
    [analysis.series.observed],
  );
  const worst = analysis.worst;

  // Предлагаемая пара «до аномалии / последнее наблюдение»: именно она
  // отвечает на вопрос «что изменилось».
  useEffect(() => {
    if (scenes.length === 0) return;
    const last = scenes[scenes.length - 1];
    const anchor = focus?.from ?? worst?.start_date;
    const before = anchor
      ? [...scenes].reverse().find((scene) => scene.date < anchor)
      : scenes[Math.max(0, scenes.length - 4)];
    setLeftDate((current) => current ?? (before ?? scenes[0]).date);
    setRightDate((current) => current ?? (focus?.to ?? last.date));
  }, [scenes, worst, focus]);

  // Правый снимок обычно последний в ленте: без прокрутки он остаётся за краем,
  // и выбранная пара выглядит незаданной.
  useEffect(() => {
    rightRef.current?.scrollIntoView({ block: "nearest", inline: "center" });
  }, [rightDate]);

  if (!field) return null;
  if (scenes.length === 0) {
    return (
      <Card>
        <EmptyState
          title="Пригодных снимков нет"
          description="За выбранный период не нашлось наблюдений с достаточным покрытием. Сравнивать нечего — расширьте период анализа."
        />
      </Card>
    );
  }

  const left = scenes.find((scene) => scene.date === leftDate) ?? scenes[0];
  const right = scenes.find((scene) => scene.date === rightDate) ?? scenes[scenes.length - 1];

  const delta =
    left.ndvi_mean !== null && right.ndvi_mean !== null
      ? right.ndvi_mean - left.ndvi_mean
      : null;

  const expectedDeviation = deviationFromExpected(right);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-[22px] font-semibold text-ink">Снимки и сравнение</h2>
        <div className="flex items-center gap-5">
          <Segmented
            value={mode}
            options={LAYER_OPTIONS}
            onChange={(value) => setMode(value as LayerMode)}
            size="sm"
          />
          <Switch checked={compare} onChange={setCompare} label="Сравнить" />
        </div>
      </div>

      {/* --- лента доступных снимков --- */}
      <Card className="flex items-center gap-3 px-4 py-4">
        <Button
          variant="outline"
          size="icon"
          aria-label="Предыдущие снимки"
          onClick={() => scroll(stripRef, -1)}
        >
          <ChevronLeft size={18} />
        </Button>

        <div
          ref={stripRef}
          className="flex min-w-0 flex-1 items-start gap-6 overflow-x-auto px-1 py-1 scroll-thin"
        >
          {scenes.map((scene) => (
            <SceneThumb
              key={scene.date}
              innerRef={scene.date === rightDate ? rightRef : undefined}
              scene={scene}
              mode={mode}
              selected={scene.date === left.date || scene.date === right.date}
              side={scene.date === left.date ? "left" : scene.date === right.date ? "right" : null}
              badge={sceneBadge(scene, scenes, worst?.start_date ?? null)}
              onSelect={() => {
                // Клик задаёт правую (более позднюю) дату, если она позже левой.
                if (scene.date > left.date) setRightDate(scene.date);
                else setLeftDate(scene.date);
              }}
            />
          ))}
        </div>

        <Button
          variant="outline"
          size="icon"
          aria-label="Следующие снимки"
          onClick={() => scroll(stripRef, 1)}
        >
          <ChevronRight size={18} />
        </Button>
      </Card>

      {/* --- панели сравнения --- */}
      <div className={cn("grid gap-4", compare ? "grid-cols-2" : "grid-cols-1")}>
        <ScenePane field={field} scene={left} mode={mode} role={roleOf(left, scenes, worst)} />
        {compare ? (
          <ScenePane field={field} scene={right} mode={mode} role={roleOf(right, scenes, worst)} />
        ) : null}
      </div>

      {/* --- итог сравнения --- */}
      {compare ? (
        <Card className="flex flex-wrap items-center gap-x-10 gap-y-5 px-6 py-5">
          <Metric
            value={delta === null ? "—" : `${delta > 0 ? "+" : "−"}${formatNumber(Math.abs(delta))}`}
            unit="NDVI"
            label="Изменение между снимками"
            tone={delta !== null && delta < 0 ? "danger" : "ok"}
          />
          <span className="h-12 w-px bg-line" />
          <Metric
            value={
              expectedDeviation === null
                ? "—"
                : `${expectedDeviation > 0 ? "+" : "−"}${formatPercent(Math.abs(expectedDeviation))}`
            }
            label={
              expectedDeviation !== null && expectedDeviation < 0
                ? "Ниже ожидаемой динамики"
                : "Относительно ожидаемой динамики"
            }
            tone={expectedDeviation !== null && expectedDeviation < 0 ? "danger" : "ok"}
          />
          <span className="h-12 w-px bg-line" />

          <div className="flex items-center gap-3.5">
            <span
              className={cn(
                "flex h-10 w-10 shrink-0 items-center justify-center rounded-full",
                worst ? "bg-danger-soft text-danger" : "bg-ok-soft text-ok",
              )}
            >
              <CircleAlert size={20} />
            </span>
            <p className="max-w-[280px] text-[15px] font-medium leading-snug text-ink">
              {worst
                ? `${SEVERITY_TITLES[worst.severity]} — отклонение до z = ${formatNumber(worst.max_zscore)}`
                : "Отклонений от нормы поля не найдено"}
            </p>
          </div>

          <Button className="ml-auto" onClick={onShowOnChart}>
            <TrendingUp size={17} />
            Показать на графике
          </Button>
        </Card>
      ) : null}
    </div>
  );
}

function ScenePane({
  field,
  scene,
  mode,
  role,
}: {
  field: Field;
  scene: Observation;
  mode: LayerMode;
  role: SceneRole | null;
}) {
  return (
    <div className="relative">
      <FieldStatePanel field={field} observation={scene} mode={mode} height={380} />
      <div className="pointer-events-none absolute left-4 top-4 z-map rounded-xl bg-white/95 px-4 py-3 shadow-card">
        <div className="flex items-center gap-3">
          <span className="text-[16px] font-semibold text-ink">{formatDate(scene.date)}</span>
          {role ? (
            <Chip size="sm" className={role.chip}>
              {role.title}
            </Chip>
          ) : null}
        </div>
        <p className="mt-1 text-[13px] text-ink-soft">
          Облачность {formatPercent(scene.cloud_fraction)} · Покрытие{" "}
          {formatPercent(scene.valid_fraction)}
        </p>
      </div>
    </div>
  );
}

function SceneThumb({
  scene,
  mode,
  selected,
  side,
  badge,
  onSelect,
  innerRef,
}: {
  scene: Observation;
  mode: LayerMode;
  selected: boolean;
  side: "left" | "right" | null;
  badge: string | null;
  onSelect: () => void;
  innerRef?: React.Ref<HTMLButtonElement>;
}) {
  const value = mode === "ndmi" ? scene.ndmi_mean : scene.ndvi_mean;
  const color = mode === "ndmi" ? ndmiColor(value) : ndviColor(value);

  return (
    <button
      ref={innerRef}
      type="button"
      onClick={onSelect}
      className={cn(
        "flex shrink-0 flex-col items-center gap-1.5 rounded-xl px-2.5 py-2 transition-colors",
        selected && (side === "right" ? "bg-danger-tint" : "bg-brand-50"),
      )}
    >
      <span
        className={cn(
          "text-[13px] font-medium",
          side === "right" ? "text-danger-ink" : selected ? "text-brand-800" : "text-ink-soft",
        )}
      >
        {formatDayMonth(scene.date)}
      </span>
      <span
        className={cn(
          "h-11 w-11 rounded-full border-2 transition-transform",
          selected ? "scale-110 border-white shadow-pop" : "border-transparent",
        )}
        style={{ backgroundColor: mode === "rgb" ? "#6B7A5E" : color }}
      />
      <span className="text-[12.5px] text-ink-muted tnum">{formatPercent(scene.valid_fraction)}</span>
      {badge ? (
        <span
          className={cn(
            "rounded-md px-1.5 py-0.5 text-[11.5px] font-medium",
            side === "right" ? "bg-danger-soft text-danger-ink" : "bg-ok-soft text-ok-ink",
          )}
        >
          {badge}
        </span>
      ) : null}
    </button>
  );
}

function Metric({
  value,
  unit,
  label,
  tone,
}: {
  value: string;
  unit?: string;
  label: string;
  tone: "ok" | "danger";
}) {
  return (
    <div>
      <p className={cn("text-[30px] font-semibold leading-none tnum", tone === "danger" ? "text-danger" : "text-ok-ink")}>
        {value}
        {unit ? <span className="ml-1.5 text-[19px] font-medium">{unit}</span> : null}
      </p>
      <p className="mt-2 text-[14px] text-ink-soft">{label}</p>
    </div>
  );
}

interface SceneRole {
  title: string;
  chip: string;
}

/** Роль снимка определяется его местом в ряду, а не стороной экрана.
 *  Иначе после обмена панелей местами более ранний снимок оказывался бы
 *  подписан «Последнее наблюдение», а поле без аномалий получало бы
 *  красную метку на ровном месте. */
function roleOf(
  scene: Observation,
  scenes: Observation[],
  worst: Anomaly | null,
): SceneRole | null {
  if (scenes.length > 0 && scene.date === scenes[scenes.length - 1].date) {
    return { title: "Последнее наблюдение", chip: "bg-[#F1F2F4] text-ink-soft" };
  }
  if (worst) {
    const before = [...scenes].reverse().find((item) => item.date < worst.start_date);
    if (before && before.date === scene.date) {
      return { title: "До аномалии", chip: "bg-ok-soft text-ok-ink" };
    }
    if (scene.date >= worst.start_date && scene.date <= worst.end_date) {
      return { title: "Внутри аномалии", chip: "bg-danger-soft text-danger-ink" };
    }
  }
  return null;
}

function sceneBadge(
  scene: Observation,
  scenes: Observation[],
  anomalyStart: string | null,
): string | null {
  if (scene.date === scenes[scenes.length - 1].date) return "Последний снимок";
  if (!anomalyStart) return null;
  const before = [...scenes].reverse().find((candidate) => candidate.date < anomalyStart);
  return before && before.date === scene.date ? "До аномалии" : null;
}

function deviationFromExpected(scene: Observation): number | null {
  if (scene.ndvi_mean === null || scene.ndvi_lo === null || scene.ndvi_hi === null) return null;
  const expected = (scene.ndvi_lo + scene.ndvi_hi) / 2;
  if (expected <= 0) return null;
  return (scene.ndvi_mean - expected) / expected;
}

function scroll(ref: React.RefObject<HTMLDivElement>, direction: 1 | -1) {
  ref.current?.scrollBy({ left: direction * 320, behavior: "smooth" });
}
