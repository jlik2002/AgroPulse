"""Генерация PDF-отчётов.

Отчёт собирается как HTML и рендерится WeasyPrint. Такой путь выбран ради
оформления: разметка и CSS дают полноценную типографику и вёрстку таблиц,
тогда как рисование отчёта примитивами заняло бы кратно больше кода
при худшем результате.

Пояснительные тексты запрашиваются у языковой модели и вставляются только
после сверки чисел. Отсутствие текста не мешает отчёту: числовая часть
самодостаточна, а на месте пояснения появляется указание причины.

Данные модуль не читает: он получает их подготовленными (`reports/data.py`).
Запрос внутри рендера превратил бы сводный отчёт по хозяйству в N+1.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from agropulse.db.models import Anomaly, Field, ForecastRun, ValueType
from agropulse.llm import narrative
from agropulse.reports import charts
from agropulse.reports.data import FieldData, ProjectData

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"

STATUS_TITLES = {
    "critical": "Критический",
    "attention": "Требует внимания",
    "normal": "Аномалий не обнаружено",
    "insufficient_data": "Недостаточно данных",
    "pending": "Не обработано",
    "failed": "Ошибка обработки",
}

SEVERITY_TITLES = {
    "moderate": "Угнетение биомассы",
    "critical": "Критическая аномалия",
}

DIRECTION_TITLES = {
    "declining": "Снижение",
    "improving": "Восстановление",
    "stable": "Без существенных изменений",
}

RISK_LEVEL_TITLES = {
    "high": "Высокий",
    "moderate": "Умеренный",
    "low": "Низкий",
}

SATELLITE_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"

_environment = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
)


def _css() -> str:
    return (TEMPLATES_DIR / "base.css").read_text(encoding="utf-8")


def _render_pdf(html: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html).write_pdf()


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


# ----------------------------------------------------------------------
# Отчёт по полю
# ----------------------------------------------------------------------


def build_field_report(data: FieldData, client: str | None = None) -> bytes:
    """Аналитический отчёт по одному полю."""
    field = data.field
    observations = data.observations
    anomalies = data.anomalies
    forecast_run = data.forecast_run

    in_period = data.in_period
    observed = [
        (o.date, o.ndvi_mean)
        for o in in_period
        if o.value_type == ValueType.OBSERVED and o.ndvi_mean is not None
    ]
    restored = [
        (o.date, o.ndvi_mean)
        for o in in_period
        if o.value_type == ValueType.RESTORED and o.ndvi_mean is not None
    ]
    forecast_points = [
        (o.date, o.ndvi_mean, o.ndvi_lo, o.ndvi_hi)
        for o in observations
        if o.value_type == ValueType.FORECAST and o.ndvi_mean is not None
    ]

    breakdown = field.risk_breakdown or {}
    climatology = breakdown.get("climatology") or {}
    data_quality = field.data_quality or {}

    valid_values = [
        o.valid_fraction
        for o in in_period
        if o.value_type == ValueType.OBSERVED and o.valid_fraction is not None
    ]

    quality = {
        "scenes_total": data_quality.get("scenes_total", len(observations)),
        "scenes_usable": data_quality.get("scenes_usable", len(observed)),
        "observed": len(observed),
        "restored": len(restored),
        # Сумма передаётся готовой: считать её самостоятельно модели запрещено,
        # а упомянуть общий объём ряда она захочет закономерно.
        "total_points": len(observed) + len(restored),
        "valid_fraction": (
            round(sum(valid_values) / len(valid_values), 3) if valid_values else "—"
        ),
        "seasons": climatology.get("seasons_used", "—"),
        "satellite_source": data_quality.get("satellite_source") or "—",
        "weather_source": data_quality.get("weather_source") or "—",
    }

    # --- пояснительные тексты ---
    payload = _field_payload(field, quality, anomalies, forecast_run, breakdown)
    summary = narrative.field_summary(payload)
    checklist_result = narrative.checklist(payload) if anomalies else None

    anomaly_blocks = []
    for anomaly in anomalies:
        factors = anomaly.factors or {}
        explanation = narrative.anomaly_explanation(_anomaly_payload(field, anomaly))
        anomaly_blocks.append(
            {
                "start_date": anomaly.start_date.isoformat(),
                "end_date": anomaly.end_date.isoformat(),
                "duration_days": anomaly.duration_days,
                "max_zscore": _round(anomaly.max_zscore),
                "severity_title": SEVERITY_TITLES.get(
                    anomaly.severity.value, anomaly.severity.value
                ),
                "restored_fraction": _round(anomaly.restored_fraction),
                "confidence": _round(anomaly.confidence),
                "phase_mismatch": bool(factors.get("phase_mismatch")),
                "hypotheses": factors.get("hypotheses") or [],
                "explanation": explanation.text,
            }
        )

    weather_days = [o.date for o in in_period if o.temperature is not None]
    weather_svg = (
        charts.weather_chart(
            weather_days,
            [o.temperature for o in in_period if o.temperature is not None],
            [o.precipitation for o in in_period if o.temperature is not None],
        )
        if len(weather_days) > 2
        else None
    )

    html = _environment.get_template("field_report.html").render(
        css=_css(),
        client=client,
        field={
            "name": field.name,
            "area_ha": _round(field.area_ha, 1),
            "crop": field.crop,
            "sowing_date": field.sowing_date.isoformat() if field.sowing_date else None,
        },
        period_from=data.period_from.isoformat(),
        period_to=data.period_to.isoformat(),
        generated_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
        status=field.status.value,
        status_title=STATUS_TITLES.get(field.status.value, field.status.value),
        risk_score=field.risk_score,
        risk_confidence=breakdown.get("confidence"),
        insufficient_reason=breakdown.get("insufficient_reason"),
        summary_text=summary.text,
        summary_skipped=summary.skipped_reason,
        quality=quality,
        ndvi_chart=charts.ndvi_chart(
            observed, restored, forecast_points,
            [(a.start_date, a.end_date) for a in anomalies],
        ),
        weather_chart=weather_svg,
        anomalies=anomaly_blocks,
        checklist=_parse_checklist(checklist_result),
        forecast=_forecast_block(forecast_run),
        risk_chart=(
            charts.risk_breakdown_chart(breakdown["weights"])
            if breakdown.get("weights")
            else None
        ),
        risk_explanation=breakdown.get("explanation") or [],
        methodology={"collection": SATELLITE_COLLECTION},
    )
    return _render_pdf(html)


def _field_payload(
    field: Field,
    quality: dict,
    anomalies: list[Anomaly],
    forecast_run: ForecastRun | None,
    breakdown: dict,
) -> dict:
    """Компактный JSON для языковой модели.

    Передаётся только то, что уже рассчитано и проверено: модель не должна
    получать сырые ряды, из которых у неё возникнет соблазн что-то вывести.
    """
    return {
        "field_name": field.name,
        "area_ha": _round(field.area_ha, 1),
        "crop": field.crop,
        "status": STATUS_TITLES.get(field.status.value),
        "risk_score": field.risk_score,
        "risk_confidence": breakdown.get("confidence"),
        "risk_explanation": breakdown.get("explanation"),
        "insufficient_reason": breakdown.get("insufficient_reason"),
        "data_quality": quality,
        "anomalies": [
            {
                "start_date": a.start_date.isoformat(),
                "end_date": a.end_date.isoformat(),
                "duration_days": a.duration_days,
                "max_zscore": _round(a.max_zscore),
                "severity": SEVERITY_TITLES.get(a.severity.value),
                "confidence": _round(a.confidence),
                "factors": a.factors,
            }
            for a in anomalies
        ],
        "forecast": _forecast_block(forecast_run),
    }


def _anomaly_payload(field: Field, anomaly: Anomaly) -> dict:
    factors = anomaly.factors or {}
    return {
        "field_name": field.name,
        "crop": field.crop,
        "start_date": anomaly.start_date.isoformat(),
        "end_date": anomaly.end_date.isoformat(),
        "duration_days": anomaly.duration_days,
        "max_zscore": _round(anomaly.max_zscore),
        "mean_zscore": _round(anomaly.mean_zscore),
        "severity": SEVERITY_TITLES.get(anomaly.severity.value),
        "restored_fraction": _round(anomaly.restored_fraction),
        "confidence": _round(anomaly.confidence),
        "phase_mismatch": bool(factors.get("phase_mismatch")),
        "factors": factors,
    }


def _forecast_block(forecast_run: ForecastRun | None) -> dict:
    if forecast_run is None:
        return {
            "horizon_days": 14,
            "points": 0,
            "insufficient_reason": "прогноз не рассчитывался",
        }
    return {
        "horizon_days": forecast_run.horizon_days or 14,
        "points": forecast_run.horizon_days or 0,
        "direction_title": DIRECTION_TITLES.get(forecast_run.direction or "", "—"),
        "risk_title": RISK_LEVEL_TITLES.get(forecast_run.risk_level or "", "—"),
        "confidence": _round(forecast_run.confidence),
        "model_version": forecast_run.model_version or "—",
        "insufficient_reason": forecast_run.insufficient_reason,
    }


def _parse_checklist(result: narrative.Narrative | None) -> list[str]:
    """Разобрать список пунктов, полученный от модели."""
    if result is None or not result.text:
        return []
    items = []
    for line in result.text.splitlines():
        cleaned = line.strip().lstrip("-–—•*").strip()
        if cleaned:
            items.append(cleaned)
    return items


# ----------------------------------------------------------------------
# Сводный отчёт
# ----------------------------------------------------------------------


def build_project_report(data: ProjectData, client: str | None = None) -> bytes:
    """Сводный отчёт по хозяйству с очередью на осмотр."""
    rows, cards = [], []
    for field_data in data.fields:
        field = field_data.field
        anomalies = field_data.anomalies
        in_period = field_data.in_period
        observed = [
            (o.date, o.ndvi_mean)
            for o in in_period
            if o.value_type == ValueType.OBSERVED and o.ndvi_mean is not None
        ]
        restored = [
            (o.date, o.ndvi_mean)
            for o in in_period
            if o.value_type == ValueType.RESTORED and o.ndvi_mean is not None
        ]
        breakdown = field.risk_breakdown or {}

        rows.append(
            {
                "field": field,
                "name": field.name,
                "area_ha": _round(field.area_ha, 1),
                "crop": field.crop,
                "status": field.status.value,
                "status_title": STATUS_TITLES.get(field.status.value, field.status.value),
                "risk_score": field.risk_score,
                "anomalies_count": len(anomalies),
                "observed_points": len(observed),
                "reason": breakdown.get("insufficient_reason") or "—",
                "explanation": breakdown.get("explanation") or [],
                "worst": anomalies[0] if anomalies else None,
                "observed": observed,
                "restored": restored,
                "anomaly_spans": [(a.start_date, a.end_date) for a in anomalies],
            }
        )

    ranked = sorted(
        (r for r in rows if r["risk_score"] is not None),
        key=lambda r: r["risk_score"],
        reverse=True,
    )
    for position, row in enumerate(ranked, start=1):
        row["rank"] = position
    without_risk = [r for r in rows if r["risk_score"] is None]

    # Подробные карточки только для проблемных полей: сводный отчёт должен
    # оставаться обозримым, даже когда полей много.
    for row in ranked:
        if row["status"] not in ("critical", "attention"):
            continue
        cards.append(
            {
                "name": row["name"],
                "status": row["status"],
                "status_title": row["status_title"],
                "worst": (
                    {
                        "start_date": row["worst"].start_date.isoformat(),
                        "end_date": row["worst"].end_date.isoformat(),
                        "duration_days": row["worst"].duration_days,
                        "max_zscore": _round(row["worst"].max_zscore),
                    }
                    if row["worst"]
                    else None
                ),
                "explanation": row["explanation"],
                "chart": charts.ndvi_chart(
                    row["observed"], row["restored"], [], row["anomaly_spans"]
                ),
            }
        )

    counts = {
        "critical": sum(1 for r in rows if r["status"] == "critical"),
        "attention": sum(1 for r in rows if r["status"] == "attention"),
        "normal": sum(1 for r in rows if r["status"] == "normal"),
        "insufficient_data": sum(1 for r in rows if r["status"] == "insufficient_data"),
    }

    summary = narrative.project_summary(
        {
            "period": f"{data.period_from} — {data.period_to}",
            "counts": counts,
            "fields": [
                {
                    "name": r["name"],
                    "status": r["status_title"],
                    "risk_score": r["risk_score"],
                    "anomalies": r["anomalies_count"],
                    "area_ha": r["area_ha"],
                }
                for r in ranked + without_risk
            ],
        }
    )

    html = _environment.get_template("project_report.html").render(
        css=_css(),
        client=client,
        period_from=data.period_from.isoformat(),
        period_to=data.period_to.isoformat(),
        generated_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
        total_fields=len(rows),
        counts=counts,
        summary_text=summary.text,
        summary_skipped=summary.skipped_reason,
        ranked=ranked,
        without_risk=without_risk,
        cards=cards,
    )
    return _render_pdf(html)
