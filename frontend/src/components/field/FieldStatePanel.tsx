import type { Field, Observation } from "@/api/types";
import { FieldShape } from "@/components/map/FieldShapes";
import { FitBounds, MapCanvas } from "@/components/map/MapCanvas";
import { Tooltip } from "@/components/ui/Tooltip";
import { cn } from "@/lib/cn";
import { formatNumber } from "@/lib/format";
import { polygonBounds } from "@/lib/geo";
import { ndmiColor, ndviColor } from "@/lib/status";
import { Info } from "lucide-react";

export type LayerMode = "rgb" | "ndvi" | "ndmi";

/** Слой RGB отключён до появления настоящих тайлов снимков.
 *
 *  Сервис считает индексы как среднее по контуру и растры в хранилище не
 *  выкладывает. Прозрачный контур поверх обзорной подложки Esri показывал бы
 *  одну и ту же недатированную мозаику для любой даты — и в режиме сравнения
 *  две «разные» даты выглядели бы одинаково. Пункт оставлен в раскладке,
 *  чтобы не менять состав переключателя, когда слой появится. */
export const LAYER_OPTIONS = [
  {
    value: "rgb" as const,
    label: "RGB",
    disabled: true,
    title: "Снимок в естественных цветах за дату пока недоступен",
  },
  { value: "ndvi" as const, label: "NDVI" },
  { value: "ndmi" as const, label: "NDMI" },
];

interface FieldStatePanelProps {
  field: Field;
  /** Наблюдение, состояние которого показывается на карте. */
  observation: Observation | null;
  mode: LayerMode;
  className?: string;
  /** Высота задаётся числом: у Leaflet контейнер должен иметь измеримую
   *  высоту, иначе он инициализируется нулевым и тайлы не грузятся. */
  height?: number;
}

/** Состояние поля на карте.
 *
 *  Сервис рассчитывает индексы как среднее по контуру, попиксельные растры
 *  в хранилище не выкладываются, поэтому контур заливается цветом среднего
 *  значения выбранного индекса. Подпись под легендой говорит об этом прямо:
 *  выдавать среднее за карту неоднородности поля было бы неверно. */
export function FieldStatePanel({
  field,
  observation,
  mode,
  className,
  height = 340,
}: FieldStatePanelProps) {
  const bounds = polygonBounds(field.geometry);

  const value =
    mode === "ndvi" ? observation?.ndvi_mean : mode === "ndmi" ? observation?.ndmi_mean : null;

  const fill =
    mode === "rgb"
      ? { color: "#FFFFFF", fillOpacity: 0.05, weight: 3 }
      : {
          color: mode === "ndvi" ? ndviColor(value) : ndmiColor(value),
          fillOpacity: 0.75,
          weight: 3,
        };

  return (
    <div
      className={cn("relative overflow-hidden rounded-xl border border-line", className)}
      style={{ height }}
    >
      <MapCanvas basemap="satellite" className="h-full" static>
        <FitBounds bounds={bounds} padding={26} maxZoom={16} />
        <FieldShape geometry={field.geometry} style={{ ...fill, weight: 3 }} interactive={false} />
      </MapCanvas>

      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-map p-4">
        {mode === "rgb" ? (
          <div className="pointer-events-auto inline-flex items-center gap-2 rounded-lg bg-white/95 px-3.5 py-2 text-[13px] text-ink-soft shadow-card">
            Обзорная подложка: снимка за выбранную дату нет
          </div>
        ) : (
          <div className="pointer-events-auto inline-block rounded-xl bg-white/95 px-4 py-3 shadow-card">
            <div className="flex items-center gap-3">
              <span className="text-[12.5px] text-ink-soft">
                {mode === "ndvi" ? "Низкий" : "Сухо"}
              </span>
              <span
                className="h-2.5 w-44 rounded-full"
                style={{
                  background:
                    mode === "ndvi"
                      ? "linear-gradient(90deg,#C72C22,#E86A29,#F0BD3C,#8CBE4A,#1A7A3E,#0B4A29)"
                      : "linear-gradient(90deg,#C49A58,#8FA47A,#0A7682)",
                }}
              />
              <span className="text-[12.5px] text-ink-soft">
                {mode === "ndvi" ? "Высокий" : "Влажно"}
              </span>
              <Tooltip
                content={`Контур залит цветом среднего значения ${mode.toUpperCase()} по полю за выбранную дату. Это средняя оценка, а не карта неоднородности участка.`}
              >
                <span className="ml-1 text-ink-muted">
                  <Info size={15} />
                </span>
              </Tooltip>
            </div>
            {value !== null && value !== undefined ? (
              <p className="mt-2 text-[13px] text-ink-soft">
                Среднее по полю:{" "}
                <span className="font-semibold text-ink tnum">{formatNumber(value)}</span>
              </p>
            ) : (
              <p className="mt-2 text-[13px] text-ink-muted">
                {observation?.missing_reason ?? "Значение за выбранную дату недоступно"}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
