import "@geoman-io/leaflet-geoman-free";

import type { Layer, Polygon as LeafletPolygon } from "leaflet";
import { useEffect } from "react";
import { useMap } from "react-leaflet";

import type { PolygonGeometry } from "@/api/types";
import { fromLeafletRing } from "@/lib/geo";

interface DrawLayerProps {
  active: boolean;
  onCreate: (geometry: PolygonGeometry) => void;
}

/** Ручное рисование контура через leaflet-geoman.
 *
 *  Нарисованный слой сразу удаляется с карты: контур уходит наверх как
 *  GeoJSON и возвращается уже полем проекта со своим номером и стилем.
 *  Иначе на карте оставались бы две геометрии поверх друг друга. */
export function DrawLayer({ active, onCreate }: DrawLayerProps) {
  const map = useMap();

  useEffect(() => {
    const handleCreate = (event: { layer: Layer }) => {
      const layer = event.layer as LeafletPolygon;
      const rings = layer.getLatLngs() as { lat: number; lng: number }[][];
      const outer = rings[0];
      layer.remove();
      if (outer && outer.length >= 3) onCreate(fromLeafletRing(outer));
    };

    map.on("pm:create", handleCreate);
    return () => {
      map.off("pm:create", handleCreate);
    };
  }, [map, onCreate]);

  useEffect(() => {
    if (active) {
      map.pm.enableDraw("Polygon", {
        snappable: true,
        snapDistance: 12,
        continueDrawing: false,
        templineStyle: { color: "#FFFFFF", weight: 2.5, dashArray: "7 6" },
        hintlineStyle: { color: "#FFFFFF", weight: 2, dashArray: "7 6" },
        pathOptions: {
          color: "#FFFFFF",
          weight: 2.5,
          dashArray: "7 6",
          fillColor: "#0F4730",
          fillOpacity: 0.28,
        },
      });
    } else {
      map.pm.disableDraw();
    }

    return () => {
      map.pm.disableDraw();
    };
  }, [active, map]);

  return null;
}
