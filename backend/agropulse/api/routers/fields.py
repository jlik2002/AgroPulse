"""Эндпоинты полей: добавление, редактирование, удаление, запуск обработки.

Поле — центральная сущность продукта, поэтому управление контурами вынесено
в отдельный ресурс со своим жизненным циклом, а не спрятано внутрь проекта.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from agropulse.db.models import Field as FieldModel
from agropulse.db.models import FieldStatus, Observation, Project, ValueType
from agropulse.db.session import get_db
from agropulse.geometry import GeometryError, to_geojson, to_wkt_element, validate_polygon
from agropulse.schemas.field import (
    FieldCreate,
    FieldRead,
    FieldUpdate,
    ObservationRead,
    TimeseriesRead,
)
from agropulse.tasks.pipeline import process_field

router = APIRouter(tags=["fields"])


def _to_read_model(field: FieldModel) -> dict:
    """Собрать ответ, подменив геометрию из WKB на GeoJSON."""
    data = {
        column.name: getattr(field, column.name)
        for column in FieldModel.__table__.columns
        if column.name != "geom"
    }
    data["geometry"] = to_geojson(field.geom)
    return data


def get_field_or_404(field_id: uuid.UUID, db: Session) -> FieldModel:
    field = db.get(FieldModel, field_id)
    if field is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="поле не найдено")
    return field


@router.post(
    "/projects/{project_id}/fields",
    response_model=FieldRead,
    status_code=status.HTTP_201_CREATED,
)
def create_field(
    project_id: uuid.UUID, payload: FieldCreate, db: Session = Depends(get_db)
) -> dict:
    """Добавить поле в проект.

    Полигон приходит либо нарисованным вручную, либо выбранным из открытого
    источника контуров — различие сохраняется в поле `source`.
    """
    if db.get(Project, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="проект не найден")

    try:
        geom, area_ha = validate_polygon(payload.geometry)
    except GeometryError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    field = FieldModel(
        project_id=project_id,
        name=payload.name,
        geom=to_wkt_element(geom),
        area_ha=area_ha,
        crop=payload.crop,
        sowing_date=payload.sowing_date,
        source=payload.source,
        external_ref=payload.external_ref,
        status=FieldStatus.PENDING,
    )
    db.add(field)
    db.commit()
    db.refresh(field)
    return _to_read_model(field)


@router.get("/projects/{project_id}/fields", response_model=list[FieldRead])
def list_fields(project_id: uuid.UUID, db: Session = Depends(get_db)) -> list[dict]:
    if db.get(Project, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="проект не найден")
    fields = db.scalars(
        select(FieldModel)
        .where(FieldModel.project_id == project_id)
        .order_by(FieldModel.created_at)
    ).all()
    return [_to_read_model(f) for f in fields]


@router.get("/fields/{field_id}", response_model=FieldRead)
def read_field(field_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    return _to_read_model(get_field_or_404(field_id, db))


@router.patch("/fields/{field_id}", response_model=FieldRead)
def update_field(
    field_id: uuid.UUID, payload: FieldUpdate, db: Session = Depends(get_db)
) -> dict:
    field = get_field_or_404(field_id, db)

    if payload.geometry is not None:
        try:
            geom, area_ha = validate_polygon(payload.geometry)
        except GeometryError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        field.geom = to_wkt_element(geom)
        field.area_ha = area_ha
        # Контур изменился — ранее собранные наблюдения относятся к другой области
        # и больше не действительны.
        db.query(Observation).filter(Observation.field_id == field.id).delete()
        field.status = FieldStatus.PENDING
        field.risk_score = None
        field.risk_breakdown = None

    for attribute in ("name", "crop", "sowing_date"):
        value = getattr(payload, attribute)
        if value is not None:
            setattr(field, attribute, value)

    db.commit()
    db.refresh(field)
    return _to_read_model(field)


@router.delete("/fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_field(field_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    field = get_field_or_404(field_id, db)
    db.delete(field)
    db.commit()


@router.get("/fields/{field_id}/timeseries", response_model=TimeseriesRead)
def read_timeseries(field_id: uuid.UUID, db: Session = Depends(get_db)) -> TimeseriesRead:
    """Временной ряд поля со сводкой качества данных."""
    field = get_field_or_404(field_id, db)
    observations = db.scalars(
        select(Observation)
        .where(Observation.field_id == field_id)
        .order_by(Observation.date, Observation.value_type)
    ).all()

    observed = [o for o in observations if o.value_type == ValueType.OBSERVED]
    with_ndvi = [o for o in observed if o.ndvi_mean is not None]
    valid_fractions = [o.valid_fraction for o in with_ndvi if o.valid_fraction is not None]

    stats = {
        "total_points": len(observations),
        "observed": len(observed),
        "restored": sum(1 for o in observations if o.value_type == ValueType.RESTORED),
        "forecast": sum(1 for o in observations if o.value_type == ValueType.FORECAST),
        "scenes_with_ndvi": len(with_ndvi),
        "mean_valid_fraction": (
            round(sum(valid_fractions) / len(valid_fractions), 4) if valid_fractions else None
        ),
    }

    return TimeseriesRead(
        field_id=field.id,
        field_name=field.name,
        period_from=field.project.period_from,
        period_to=field.project.period_to,
        observations=[ObservationRead.model_validate(o) for o in observations],
        stats=stats,
    )


@router.post("/fields/{field_id}/process", status_code=status.HTTP_202_ACCEPTED)
def start_processing(field_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    """Поставить полную обработку поля в очередь.

    Отвечаем сразу: обработка занимает минуты и выполняется воркером. Ход
    выполнения по стадиям доступен через поток событий проекта.
    """
    field = get_field_or_404(field_id, db)
    task = process_field.delay(str(field.id))
    return {"field_id": str(field.id), "task_id": task.id}


@router.post("/projects/{project_id}/process", status_code=status.HTTP_202_ACCEPTED)
def start_project_processing(project_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    """Поставить обработку всех полей проекта.

    Поля обрабатываются независимыми задачами: отказ по одному полю не должен
    останавливать остальные.
    """
    if db.get(Project, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="проект не найден")

    fields = db.scalars(
        select(FieldModel).where(FieldModel.project_id == project_id)
    ).all()
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="в проекте нет полей")

    tasks = [
        {"field_id": str(f.id), "task_id": process_field.delay(str(f.id)).id}
        for f in fields
    ]
    return {"project_id": str(project_id), "tasks": tasks}
