import type { LatLngBoundsExpression, Map as LeafletMap } from "leaflet";
import { useEffect } from "react";
import { MapContainer, TileLayer, useMap } from "react-leaflet";

import { BASEMAPS, type BasemapKind } from "@/components/map/basemaps";
import { cn } from "@/lib/cn";

interface MapCanvasProps {
  center?: [number, number];
  zoom?: number;
  basemap?: BasemapKind;
  className?: string;
  children?: React.ReactNode;
  /** Карта-иллюстрация: без перетаскивания и зума колесом. */
  static?: boolean;
  onReady?: (map: LeafletMap) => void;
}

// Центр по умолчанию — юг России: там лежат демонстрационные поля проекта.
const DEFAULT_CENTER: [number, number] = [45.35, 39.05];

export function MapCanvas({
  center = DEFAULT_CENTER,
  zoom = 12,
  basemap = "satellite",
  className,
  children,
  static: isStatic = false,
  onReady,
}: MapCanvasProps) {
  const layer = BASEMAPS[basemap];

  return (
    <MapContainer
      center={center}
      zoom={zoom}
      zoomControl={false}
      attributionControl
      scrollWheelZoom={!isStatic}
      dragging={!isStatic}
      doubleClickZoom={!isStatic}
      className={cn("h-full w-full", className)}
    >
      <TileLayer
        key={basemap}
        url={layer.url}
        attribution={layer.attribution}
        maxZoom={layer.maxZoom}
      />
      {onReady ? <MapReady onReady={onReady} /> : null}
      {children}
    </MapContainer>
  );
}

function MapReady({ onReady }: { onReady: (map: LeafletMap) => void }) {
  const map = useMap();
  useEffect(() => {
    onReady(map);
    // Контейнер карты часто появляется вместе с раскладкой страницы, и Leaflet
    // успевает измерить его нулевым. Пересчёт после кадра убирает серые поля.
    const timer = window.setTimeout(() => map.invalidateSize(), 80);
    return () => window.clearTimeout(timer);
  }, [map, onReady]);
  return null;
}

interface FitBoundsProps {
  bounds: LatLngBoundsExpression | null;
  padding?: number;
  maxZoom?: number;
  /** Подгонять только один раз: иначе карта «прыгала» бы после каждого зума. */
  once?: boolean;
}

export function FitBounds({ bounds, padding = 40, maxZoom = 16, once = false }: FitBoundsProps) {
  const map = useMap();
  const key = bounds ? JSON.stringify(bounds) : null;

  useEffect(() => {
    if (!bounds) return;
    map.fitBounds(bounds, { padding: [padding, padding], maxZoom, animate: !once });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, map]);

  return null;
}

/** Плавный перелёт к найденному региону. */
export function FlyTo({ center, zoom }: { center: [number, number] | null; zoom?: number }) {
  const map = useMap();
  const key = center ? center.join(",") : null;

  useEffect(() => {
    if (!center) return;
    map.flyTo(center, zoom ?? map.getZoom(), { duration: 0.8 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, map]);

  return null;
}
