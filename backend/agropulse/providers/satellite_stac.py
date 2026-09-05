"""Источник спутниковых наблюдений через STAC.

ВНИМАНИЕ: модуль в пайплайн не подключён. Он написан и проверен как запасной
канал на случай отказа Earth Engine, но в цепочку источников
(`providers/chain.py`) сознательно не включён — достаточно дописать его туда,
когда понадобится.

Работает с каталогом Earth Search (Element 84) поверх открытого архива
Sentinel-2 L2A в AWS. Ключевое отличие от Earth Engine: здесь нет серверных
вычислений, поэтому растры читаются напрямую и индексы считаются локально.

Из-за этого источник заметно медленнее и включается только когда Earth Engine
недоступен — нет ключа, исчерпана квота, отказ сервиса. Зато он не требует
регистрации вообще, что делает решение независимым от одного поставщика.

Две оптимизации делают чтение приемлемым по времени:

* читается только окно снимка по границам полигона, а не сцена целиком;
* данные децимируются до разрешения SCL (20 м). Для среднего по полю разница
  с исходными 10 м пренебрежима, а объём чтения падает вчетверо.
"""

from __future__ import annotations

import logging
from datetime import date

import httpx
import numpy as np

from agropulse.config import get_settings
from agropulse.providers.base import ProviderError, SatelliteObservation
from agropulse.providers.satellite_gee import MIN_VALID_FRACTION, SCL_CLOUD, SCL_INVALID

logger = logging.getLogger(__name__)

STAC_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"
COLLECTION = "sentinel-2-l2a"

# Ключи ассетов в Earth Search v1. Запасные имена — на случай смены схемы каталога.
ASSET_ALIASES = {
    "blue": ("blue", "B02"),
    "red": ("red", "B04"),
    "nir": ("nir", "B08"),
    "swir16": ("swir16", "B11"),
    "scl": ("scl", "SCL"),
}

# Сцены с почти полной облачностью читать бессмысленно — отсекаем на поиске,
# чтобы не тратить время на скачивание заведомо непригодных растров.
MAX_SCENE_CLOUD_COVER = 80

# Верхняя граница числа обрабатываемых сцен за один вызов.
MAX_SCENES = 80

REFLECTANCE_SCALE = 0.0001


class STACSatelliteProvider:
    """Реализация SatelliteProvider поверх STAC и COG."""

    name = "s2_stac"

    def is_available(self) -> bool:
        # Ни ключей, ни регистрации не требуется.
        return True

    def fetch_series(
        self, geometry: dict, date_from: date, date_to: date
    ) -> list[SatelliteObservation]:
        items = self._search(geometry, date_from, date_to)
        if not items:
            return []

        from agropulse.providers.satellite_gee import _aggregate_by_date

        raw: list[dict] = []
        for item in items[:MAX_SCENES]:
            try:
                summary = self._summarize_item(item, geometry)
            except Exception as exc:
                # Отдельная непрочитанная сцена не повод терять весь ряд.
                logger.warning("Сцена %s не прочитана: %s", item.get("id"), exc)
                continue
            if summary is not None:
                raw.append(summary)

        if not raw:
            raise ProviderError("ни одну сцену не удалось прочитать")
        return _aggregate_by_date(raw, source=self.name)

    # ------------------------------------------------------------------

    def _search(self, geometry: dict, date_from: date, date_to: date) -> list[dict]:
        settings = get_settings()
        body = {
            "collections": [COLLECTION],
            "intersects": geometry,
            "datetime": f"{date_from.isoformat()}T00:00:00Z/{date_to.isoformat()}T23:59:59Z",
            "query": {"eo:cloud_cover": {"lt": MAX_SCENE_CLOUD_COVER}},
            "limit": 100,
        }
        items: list[dict] = []
        url: str | None = STAC_SEARCH_URL

        try:
            with httpx.Client(
                timeout=settings.http_timeout_seconds,
                headers={"User-Agent": settings.http_user_agent},
            ) as client:
                while url and len(items) < MAX_SCENES:
                    response = client.post(url, json=body)
                    response.raise_for_status()
                    payload = response.json()
                    items.extend(payload.get("features", []))
                    # Постраничная выдача STAC: ссылка с rel=next.
                    url = next(
                        (
                            link["href"]
                            for link in payload.get("links", [])
                            if link.get("rel") == "next"
                        ),
                        None,
                    )
        except httpx.HTTPError as exc:
            raise ProviderError(f"поиск в каталоге STAC не выполнен: {exc}") from exc

        items.sort(key=lambda i: i["properties"]["datetime"])
        return items

    def _summarize_item(self, item: dict, geometry: dict) -> dict | None:
        """Свести одну сцену к средним значениям индексов по полигону."""
        import rasterio
        from rasterio.features import geometry_mask
        from rasterio.warp import transform_geom
        from rasterio.windows import from_bounds
        from shapely.geometry import shape

        assets = item.get("assets", {})
        hrefs = {name: _asset_href(assets, aliases) for name, aliases in ASSET_ALIASES.items()}
        if any(href is None for href in hrefs.values()):
            logger.debug("Сцена %s: не хватает ассетов", item.get("id"))
            return None

        # Опции GDAL: архив Sentinel-2 в AWS открытый, подпись не нужна;
        # запрет обхода каталога убирает лишние запросы на каждое открытие файла.
        gdal_env = {
            "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
            "AWS_NO_SIGN_REQUEST": "YES",
            "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
            "GDAL_HTTP_MAX_RETRY": "3",
            "GDAL_HTTP_RETRY_DELAY": "1",
        }

        with rasterio.Env(**gdal_env):
            # SCL (20 м) задаёт сетку, в которую приводятся остальные каналы.
            with rasterio.open(hrefs["scl"]) as source:
                projected = transform_geom("EPSG:4326", source.crs, geometry)
                bounds = shape(projected).bounds
                window = from_bounds(*bounds, transform=source.transform).round_lengths()
                window = window.round_offsets()
                if window.width < 1 or window.height < 1:
                    return None

                scl = source.read(1, window=window, boundless=True, fill_value=0)
                window_transform = source.window_transform(window)

            shape_2d = scl.shape
            inside = ~geometry_mask(
                [projected], out_shape=shape_2d, transform=window_transform, invert=False
            )
            if not inside.any():
                return None

            bands: dict[str, np.ndarray] = {}
            for name in ("blue", "red", "nir", "swir16"):
                with rasterio.open(hrefs[name]) as source:
                    band_window = from_bounds(*bounds, transform=source.transform)
                    bands[name] = source.read(
                        1,
                        window=band_window,
                        out_shape=shape_2d,
                        boundless=True,
                        fill_value=0,
                    ).astype("float32") * REFLECTANCE_SCALE

        valid = inside & ~np.isin(scl, SCL_INVALID)
        cloud = inside & np.isin(scl, SCL_CLOUD)

        total = int(inside.sum())
        valid_fraction = float(valid.sum()) / total
        cloud_fraction = float(cloud.sum()) / total

        summary = {
            "date": item["properties"]["datetime"][:10],
            "scene_id": item.get("id"),
            "valid_fraction": round(valid_fraction, 4),
            "cloud_fraction": round(cloud_fraction, 4),
            "ndvi": None,
            "ndmi": None,
            "evi": None,
        }
        if valid_fraction < MIN_VALID_FRACTION:
            return summary

        blue, red, nir, swir = (bands["blue"], bands["red"], bands["nir"], bands["swir16"])
        summary["ndvi"] = _masked_mean(_normalized_difference(nir, red), valid)
        summary["ndmi"] = _masked_mean(_normalized_difference(nir, swir), valid)
        with np.errstate(divide="ignore", invalid="ignore"):
            evi = 2.5 * (nir - red) / (nir + 6.0 * red - 7.5 * blue + 1.0)
        summary["evi"] = _masked_mean(evi, valid)
        return summary


def _asset_href(assets: dict, aliases: tuple[str, ...]) -> str | None:
    for alias in aliases:
        asset = assets.get(alias)
        if asset and asset.get("href"):
            return asset["href"]
    return None


def _normalized_difference(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    denominator = first + second
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(denominator == 0, np.nan, (first - second) / denominator)


def _masked_mean(values: np.ndarray, mask: np.ndarray) -> float | None:
    selected = values[mask]
    selected = selected[np.isfinite(selected)]
    if selected.size == 0:
        return None
    return round(float(selected.mean()), 6)
