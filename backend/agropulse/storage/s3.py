"""Объектное хранилище артефактов: PDF-отчёты, превью снимков, выгрузки CSV.

Локальная файловая система сознательно не используется. В Kubernetes поды api и
worker масштабируются горизонтально, и файл, записанный одним подом, не будет
виден другому. S3-совместимый интерфейс работает одинаково в docker compose
(MinIO) и в кластере, поэтому код везде один и тот же.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from agropulse.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache
def get_s3_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
        # MinIO работает только с подписью v4 и path-style адресацией бакета.
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def ensure_bucket() -> None:
    """Создать бакет, если его ещё нет. Вызывается при старте приложения."""
    settings = get_settings()
    client = get_s3_client()
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        client.create_bucket(Bucket=settings.s3_bucket)
        logger.info("Создан бакет %s", settings.s3_bucket)


def put_object(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    settings = get_settings()
    get_s3_client().put_object(
        Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type
    )
    return key


def get_object(key: str) -> bytes:
    settings = get_settings()
    response = get_s3_client().get_object(Bucket=settings.s3_bucket, Key=key)
    return response["Body"].read()


def build_url(key: str, expires_in: int | None = None) -> str:
    """Ссылка на артефакт.

    Если задан публичный базовый адрес (в кластере это внешний домен MinIO или CDN),
    отдаём прямую ссылку. Иначе — временную presigned-ссылку.
    """
    settings = get_settings()
    if settings.s3_public_base_url:
        return f"{settings.s3_public_base_url.rstrip('/')}/{settings.s3_bucket}/{key}"
    return get_s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=expires_in or settings.s3_url_expires_seconds,
    )


def healthcheck() -> bool:
    """Доступность хранилища для /health/ready.

    Любая ошибка означает «не готов»: проба обязана ответить, а не упасть,
    иначе под выпадет из балансировки по таймауту, а не по существу.
    """
    try:
        get_s3_client().head_bucket(Bucket=get_settings().s3_bucket)
        return True
    except Exception as exc:
        logger.warning("s3_unavailable", extra={"error": str(exc)})
        return False
