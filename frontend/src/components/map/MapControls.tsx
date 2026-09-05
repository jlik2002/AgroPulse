import L from "leaflet";
import { Crosshair, Minus, Plus } from "lucide-react";
import { useEffect } from "react";
import { useMap } from "react-leaflet";

import { cn } from "@/lib/cn";

/** Собственный блок зума вместо стандартного leaflet-контрола:
 *  на макете это отдельная белая карточка со скруглением 12. */
export function ZoomControls({ onLocate, className }: { onLocate?: () => void; className?: string }) {
  const map = useMap();

  return (
    <div
      className={cn(
        "flex flex-col overflow-hidden rounded-xl border border-line bg-white shadow-card",
        className,
      )}
    >
      <ControlButton label="Приблизить" onClick={() => map.zoomIn()}>
        <Plus size={18} />
      </ControlButton>
      <span className="mx-2 h-px bg-line-soft" />
      <ControlButton label="Отдалить" onClick={() => map.zoomOut()}>
        <Minus size={18} />
      </ControlButton>
      {onLocate ? (
        <>
          <span className="mx-2 h-px bg-line-soft" />
          <ControlButton label="Показать все поля" onClick={onLocate}>
            <Crosshair size={18} />
          </ControlButton>
        </>
      ) : null}
    </div>
  );
}

function ControlButton({
  children,
  label,
  onClick,
}: {
  children: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      className="flex h-11 w-11 items-center justify-center text-ink transition-colors hover:bg-[#F3F4F6]"
    >
      {children}
    </button>
  );
}

/** Масштабная линейка в левом нижнем углу. Берём штатный контрол Leaflet:
 *  он сам пересчитывает деление при зуме, а внешний вид задаётся в index.css. */
export function ScaleBar() {
  const map = useMap();

  useEffect(() => {
    // Штатный контрол подписывает деление как «m» и «km». Переопределяем
    // только форматирование подписи, вся логика подбора шага остаётся его.
    const RussianScale = L.Control.Scale.extend({
      _updateMetric(this: L.Control.Scale, maxMeters: number) {
        const control = this as unknown as {
          _getRoundNum: (value: number) => number;
          _updateScale: (element: HTMLElement, text: string, ratio: number) => void;
          _mScale: HTMLElement;
        };
        const meters = control._getRoundNum(maxMeters);
        const label = meters < 1000 ? `${meters} м` : `${meters / 1000} км`;
        control._updateScale(control._mScale, label, meters / maxMeters);
      },
    });

    const control = new RussianScale({
      imperial: false,
      position: "bottomleft",
      maxWidth: 120,
    } as L.Control.ScaleOptions);
    control.addTo(map);
    return () => {
      control.remove();
    };
  }, [map]);

  return null;
}
