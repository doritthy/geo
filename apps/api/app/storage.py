import io
from functools import lru_cache

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import get_settings


@lru_cache
def _client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def ensure_bucket() -> None:
    settings = get_settings()
    client = _client()
    try:
        client.head_bucket(Bucket=settings.S3_BUCKET)
    except ClientError:
        try:
            client.create_bucket(Bucket=settings.S3_BUCKET)
        except ClientError:
            pass


def upload_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    settings = get_settings()
    _client().put_object(Bucket=settings.S3_BUCKET, Key=key, Body=data, ContentType=content_type)


def get_bytes(key: str) -> bytes:
    settings = get_settings()
    obj = _client().get_object(Bucket=settings.S3_BUCKET, Key=key)
    return obj["Body"].read()


def get_stream(key: str) -> io.BytesIO:
    return io.BytesIO(get_bytes(key))


def presigned_url(key: str, expires_in: int = 3600) -> str:
    settings = get_settings()
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": key},
        ExpiresIn=expires_in,
    )


def delete_object(key: str) -> None:
    settings = get_settings()
    try:
        _client().delete_object(Bucket=settings.S3_BUCKET, Key=key)
    except ClientError:
        pass
