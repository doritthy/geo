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


# ---------- streaming helpers (large BIM / point cloud uploads, 3D Tiles) ----------


def upload_fileobj(key: str, fileobj, content_type: str = "application/octet-stream") -> None:
    settings = get_settings()
    _client().upload_fileobj(fileobj, settings.S3_BUCKET, key, ExtraArgs={"ContentType": content_type})


def download_to_file(key: str, path: str) -> None:
    settings = get_settings()
    _client().download_file(settings.S3_BUCKET, key, path)


def open_stream(key: str):
    """Returns (streaming body, content length) for proxying an object."""
    settings = get_settings()
    obj = _client().get_object(Bucket=settings.S3_BUCKET, Key=key)
    return obj["Body"], obj.get("ContentLength")


def upload_directory(prefix: str, directory: str, workers: int = 8) -> int:
    """Uploads every file under `directory` to `prefix/<relative path>`."""
    import mimetypes
    import os
    from concurrent.futures import ThreadPoolExecutor

    jobs = []
    for dirpath, _, files in os.walk(directory):
        for name in files:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, directory).replace(os.sep, "/")
            jobs.append((full, f"{prefix.rstrip('/')}/{rel}"))

    settings = get_settings()
    client = _client()

    def put(job):
        full, key = job
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        client.upload_file(full, settings.S3_BUCKET, key, ExtraArgs={"ContentType": ctype})

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(put, jobs))
    return len(jobs)


def delete_prefix(prefix: str) -> None:
    settings = get_settings()
    client = _client()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.S3_BUCKET, Prefix=prefix):
        keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        for i in range(0, len(keys), 1000):
            try:
                client.delete_objects(Bucket=settings.S3_BUCKET, Delete={"Objects": keys[i : i + 1000]})
            except ClientError:
                pass
