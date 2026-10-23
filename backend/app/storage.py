import hashlib
from pathlib import Path

import boto3

from app.config import get_settings
from app.errors import AppError


class Storage:
    def put(self, key: str, data: bytes, content_type: str) -> None:
        raise NotImplementedError

    def get(self, key: str) -> bytes:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def kind(self) -> str:
        raise NotImplementedError


class LocalStorage(Storage):
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if not key or ".." in key.split("/"):
            raise AppError("invalid_storage_key", "Storage key is not allowed.", 400)
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root)):
            raise AppError("invalid_storage_key", "Storage key escapes the volume.", 400)
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise AppError("file_missing", "Stored file is missing.", 404)
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()

    def kind(self) -> str:
        return "local"


class S3Storage(Storage):
    def __init__(self) -> None:
        settings = get_settings()
        self.bucket = settings.object_storage_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.object_storage_endpoint,
            aws_access_key_id=settings.object_storage_access_key,
            aws_secret_access_key=settings.object_storage_secret_key,
            region_name=settings.object_storage_region,
        )

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def kind(self) -> str:
        return "s3"


def get_storage() -> Storage:
    settings = get_settings()
    if settings.object_storage_configured():
        return S3Storage()
    if settings.app_env == "production":
        raise AppError(
            "storage_not_configured",
            "Production requires S3-compatible object storage. Local disk is not durable on serverless hosts.",
            500,
        )
    return LocalStorage(settings.storage_local_path)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
