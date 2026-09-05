import L from "leaflet";
import { Marker, Polygon, Tooltip as LeafletTooltip } from "react-leaflet";
import { useMemo } from "react";

import type { PolygonGeometry } from "@/api/types";
import { polygonCenter, toLeafletRings } from "@/lib/geo";

export interface ShapeStyle {
  color: string;
  fillOpacity?: number;
  weight?: number;
  dashed?: boolean;
  /** Цвет бейджа с номером. По умолчанию совпадает с цветом контура. */
  badgeColor?: string;
}

interface FieldShapeProps {
  geometry: PolygonGeometry;
  style: ShapeStyle;
  /** Номер поля: тот же, что в правой панели и в списке приоритета выезда. */
  index?: number;
  label?: string;
  onClick?: () => void;
  interactive?: boolean;
}

export function FieldShape({
  geometry,
  style,
  index,
  label,
  onClick,
  interactive = true,
}: FieldShapeProps) {
  const rings = useMemo(() => toLeafletRings(geometry), [geometry]);
  const center = useMemo(() => polygonCenter(geometry), [geometry]);

  const badge = useMemo(() => {
    if (index === undefined) return null;
    return L.divIcon({
      className: "",
      html: `<span class="flex h-8 w-8 items-center justify-center rounded-full text-[14px] font-semibold text-white shadow-[0_1px_4px_rgba(0,0,0,0.35)]" style="background:${style.badgeColor ?? style.color}">${index}</span>`,
      iconSize: [32, 32],
      iconAnchor: [16, 16],
    });
  }, [index, style.color, style.badgeColor]);

  return (
    <>
      <Polygon
        positions={rings}
        pathOptions={{
          color: style.color,
          weight: style.weight ?? 2.5,
          fillColor: style.color,
          fillOpacity: style.fillOpacity ?? 0.35,
          dashArray: style.dashed ? "7 6" : undefined,
        }}
        eventHandlers={onClick ? { click: onClick } : undefined}
        interactive={interactive}
      >
        {label ? (
          <LeafletTooltip direction="top" opacity={1} className="agro-tooltip">
            {label}
          </LeafletTooltip>
        ) : null}
      </Polygon>
      {badge ? (
        <Marker
          position={center}
          icon={badge}
          interactive={Boolean(onClick)}
          eventHandlers={onClick ? { click: onClick } : undefined}
        />
      ) : null}
    </>
  );
}
