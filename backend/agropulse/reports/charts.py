"""Графики для PDF-отчётов.

Рисуются в SVG и встраиваются в HTML напрямую: WeasyPrint отрисует вектор
без потери качества при любом масштабе, а промежуточные PNG-файлы не нужны.

Главное требование к графику NDVI — визуально различать происхождение значений.
Наблюдения, восстановленные значения и прогноз обязаны отличаться, иначе
пользователь не поймёт, где факт, а где расчёт.
"""

from __future__ import annotations

import io
import logging
from datetime import date

import matplotlib

# Backend без графической подсистемы: код выполняется в контейнере воркера.
matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

logger = logging.getLogger(__name__)

COLOR_OBSERVED = "#1f6f3d"
COLOR_RESTORED = "#7cb342"
COLOR_FORECAST = "#f57c00"
COLOR_NORM = "#9e9e9e"
COLOR_ANOMALY = "#d32f2f"

FIGURE_WIDTH = 9.0
FIGURE_HEIGHT = 3.4


def _render(figure) -> str:
    buffer = io.StringIO()
    figure.savefig(buffer, format="svg", bbox_inches="tight")
    plt.close(figure)
    svg = buffer.getvalue()
    # Убираем XML-пролог: SVG встраивается внутрь HTML-документа.
    return svg[svg.index("<svg") :]


def ndvi_chart(
    observed: list[tuple[date, float]],
    restored: list[tuple[date, float]],
    forecast: list[tuple[date, float, float | None, float | None]],
    anomalies: list[tuple[date, date]],
    expected: list[tuple[date, float, float]] | None = None,
) -> str:
    """График NDVI с разделением типов значений.

    `expected` — коридор собственной нормы поля (дата, нижняя граница,
    верхняя). Без него отчёт и интерфейс показывали бы разное: на экране
    ожидаемая динамика есть, а в PDF отклонение не с чем сравнить.
    """
    figure, axes = plt.subplots(figsize=(FIGURE_WIDTH, FIGURE_HEIGHT))

    # Аномальные периоды рисуются первыми, чтобы заливка легла под линии.
    for start, end in anomalies:
        axes.axvspan(start, end, color=COLOR_ANOMALY, alpha=0.12, zorder=0)

    if expected:
        days = [item[0] for item in expected]
        lows = [item[1] for item in expected]
        highs = [item[2] for item in expected]
        middles = [(low + high) / 2 for low, high in zip(lows, highs, strict=True)]
        axes.fill_between(days, lows, highs, color=COLOR_NORM, alpha=0.18, zorder=1)
        axes.plot(
            days, middles, color=COLOR_NORM, linewidth=1.2, linestyle="--",
            label="ожидаемая динамика", zorder=2,
        )

    # Восстановленные значения показываются полыми маркерами, а не только
    # пунктирной линией: линия прячется под соседними точками, и различить
    # факт от расчёта становится невозможно. Продуктовое требование прямое —
    # пользователь обязан видеть происхождение каждой точки.
    if restored:
        axes.plot(
            [d for d, _ in restored], [v for _, v in restored],
            color=COLOR_RESTORED, linewidth=1.0, linestyle="--", alpha=0.8, zorder=2,
        )
        axes.scatter(
            [d for d, _ in restored], [v for _, v in restored],
            facecolors="none", edgecolors=COLOR_RESTORED, s=14, linewidths=0.9,
            label="восстановленные", zorder=3,
        )
    if observed:
        axes.plot(
            [d for d, _ in observed], [v for _, v in observed],
            color=COLOR_OBSERVED, linewidth=0.8, alpha=0.35, zorder=4,
        )
        axes.scatter(
            [d for d, _ in observed], [v for _, v in observed],
            color=COLOR_OBSERVED, s=22, label="наблюдения", zorder=5,
        )
    if forecast:
        days = [item[0] for item in forecast]
        values = [item[1] for item in forecast]
        axes.plot(days, values, color=COLOR_FORECAST, linewidth=1.8,
                  linestyle=":", marker="^", markersize=3.5, label="прогноз", zorder=5)
        lows = [item[2] for item in forecast]
        highs = [item[3] for item in forecast]
        if all(value is not None for value in lows + highs):
            axes.fill_between(days, lows, highs, color=COLOR_FORECAST, alpha=0.15, zorder=1)

    axes.set_ylabel("NDVI")
    axes.set_ylim(-0.1, 1.0)
    axes.grid(True, alpha=0.25, linewidth=0.5)
    axes.legend(loc="upper left", fontsize=8, framealpha=0.9)
    axes.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    figure.autofmt_xdate(rotation=0, ha="center")
    return _render(figure)


def weather_chart(
    days: list[date], temperature: list[float | None], precipitation: list[float | None]
) -> str:
    """Температура и осадки — погодный контекст аномалий."""
    figure, axes = plt.subplots(figsize=(FIGURE_WIDTH, 2.2))

    bars = axes.twinx()
    bars.bar(days, [p or 0.0 for p in precipitation], color="#4a90d9", alpha=0.5, width=1.0)
    bars.set_ylabel("осадки, мм", color="#4a90d9", fontsize=8)
    bars.tick_params(axis="y", labelsize=7, colors="#4a90d9")

    axes.plot(days, temperature, color="#e65100", linewidth=1.2)
    axes.set_ylabel("температура, °C", color="#e65100", fontsize=8)
    axes.tick_params(axis="y", labelsize=7, colors="#e65100")
    axes.grid(True, alpha=0.2, linewidth=0.5)
    axes.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    axes.set_zorder(bars.get_zorder() + 1)
    axes.patch.set_visible(False)
    figure.autofmt_xdate(rotation=0, ha="center")
    return _render(figure)


def risk_breakdown_chart(breakdown: dict[str, float]) -> str:
    """Вклад факторов в составной риск."""
    titles = {
        "anomaly_severity": "Глубина отклонения",
        "anomaly_duration": "Длительность",
        "recent_trend": "Текущее состояние",
        "moisture": "Влажность растительности",
        "weather": "Погодные факторы",
    }
    items = [(titles.get(key, key), value) for key, value in breakdown.items()]
    items.sort(key=lambda item: item[1])

    figure, axes = plt.subplots(figsize=(FIGURE_WIDTH, 2.0))
    axes.barh([name for name, _ in items], [value for _, value in items], color="#1f6f3d")
    axes.set_xlabel("вклад в балл риска", fontsize=8)
    axes.tick_params(labelsize=8)
    axes.grid(True, axis="x", alpha=0.25, linewidth=0.5)
    return _render(figure)
