/** Подложки карты. Обе доступны без ключей API — это было условием выбора:
 *  сервис должен запускаться по README, не требуя регистрации в картографии. */

export type BasemapKind = "map" | "satellite";

export interface Basemap {
  url: string;
  attribution: string;
  maxZoom: number;
}

export const BASEMAPS: Record<BasemapKind, Basemap> = {
  map: {
    url: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
    attribution: "&copy; OpenStreetMap, &copy; CARTO",
    maxZoom: 19,
  },
  satellite: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "Esri, Maxar, Earthstar Geographics",
    maxZoom: 19,
  },
};

export const BASEMAP_OPTIONS = [
  { value: "map" as const, label: "Карта" },
  { value: "satellite" as const, label: "Спутник" },
];
