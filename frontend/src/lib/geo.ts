/** Геометрические помощники: GeoJSON у нас, [широта, долгота] у Leaflet. */

import type { LatLngBoundsExpression, LatLngExpression } from "leaflet";

import type { PolygonGeometry } from "@/api/types";

/** GeoJSON хранит [долгота, широта], Leaflet ждёт [широта, долгота]. */
export function toLeafletRings(geometry: PolygonGeometry): LatLngExpression[][] {
  return geometry.coordinates.map((ring) =>
    ring.map(([lon, lat]) => [lat, lon] as LatLngExpression),
  );
}

export function fromLeafletRing(ring: { lat: number; lng: number }[]): PolygonGeometry {
  const coordinates = ring.map(({ lat, lng }) => [lng, lat]);
  // GeoJSON требует замкнутый контур; Leaflet последнюю точку не дублирует.
  const first = coordinates[0];
  const last = coordinates[coordinates.length - 1];
  if (first && last && (first[0] !== last[0] || first[1] !== last[1])) {
    coordinates.push([...first]);
  }
  return { type: "Polygon", coordinates: [coordinates] };
}

export function polygonBounds(geometry: PolygonGeometry): LatLngBoundsExpression | null {
  const points = geometry.coordinates.flat();
  if (points.length === 0) return null;
  let west = 180;
  let south = 90;
  let east = -180;
  let north = -90;
  for (const [lon, lat] of points) {
    west = Math.min(west, lon);
    east = Math.max(east, lon);
    south = Math.min(south, lat);
    north = Math.max(north, lat);
  }
  return [
    [south, west],
    [north, east],
  ];
}

export function combinedBounds(geometries: PolygonGeometry[]): LatLngBoundsExpression | null {
  const points = geometries.flatMap((geometry) => geometry.coordinates.flat());
  if (points.length === 0) return null;
  return polygonBounds({ type: "Polygon", coordinates: [points] });
}

export function polygonCenter(geometry: PolygonGeometry): [number, number] {
  const points = geometry.coordinates[0] ?? [];
  if (points.length === 0) return [0, 0];
  const sum = points.reduce(
    (acc, [lon, lat]) => [acc[0] + lon, acc[1] + lat] as [number, number],
    [0, 0] as [number, number],
  );
  return [sum[1] / points.length, sum[0] / points.length];
}
