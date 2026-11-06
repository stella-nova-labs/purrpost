"""Image storage: an S3-compatible bucket (Railway) in production, a local folder in development."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from pathlib import Path
from urllib.parse import quote

from ..config import Settings


def _sign(secret: str, key: str, exp: int) -> str:
    return hmac.new(secret.encode(), f"{key}|{exp}".encode(), hashlib.sha256).hexdigest()[:32]


class LocalStorage:
    """Files under MEDIA_DIR, served by /media/<key>?exp=&sig= (signed, expiring URLs)."""

    public = False

    def __init__(self, settings: Settings) -> None:
        self.root = Path(settings.media_dir)
        self.base = settings.base_url
        self.secret = settings.encryption_key or settings.bot_token or "purrpost-dev"
        self.ttl = settings.presign_ttl_sec

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("bad key")
        return p

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(p.write_bytes, data)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def url(self, key: str, ttl: int | None = None) -> str:
        # Media URLs live a day in the app (cached images); presign_ttl applies to external fetchers
        exp = (int(time.time()) + (ttl or 86400)) // 3600 * 3600 + 3600  # round up: stable URLs for caching
        return f"/media/{quote(key)}?exp={exp}&sig={_sign(self.secret, key, exp)}"

    def check(self, key: str, exp: int, sig: str) -> bool:
        return exp > time.time() and hmac.compare_digest(sig, _sign(self.secret, key, exp))


class S3Storage:
    public = True

    def __init__(self, settings: Settings) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = settings.s3_bucket
        self.public_base = settings.s3_public_base_url.rstrip("/")
        self.ttl = settings.presign_ttl_sec
        self.s3 = boto3.client("s3", endpoint_url=settings.s3_endpoint or None, region_name=settings.s3_region,
                               aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key,
                               config=Config(signature_version="s3v4", s3={"addressing_style": settings.s3_url_style}))

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(self.s3.put_object, Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    async def get(self, key: str) -> bytes:
        obj = await asyncio.to_thread(self.s3.get_object, Bucket=self.bucket, Key=key)
        return await asyncio.to_thread(obj["Body"].read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.s3.delete_object, Bucket=self.bucket, Key=key)

    def url(self, key: str, ttl: int | None = None) -> str:
        if self.public_base:
            return f"{self.public_base}/{quote(key)}"
        return self.s3.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key},
                                              ExpiresIn=ttl or self.ttl)


def make_storage(settings: Settings) -> LocalStorage | S3Storage:
    return S3Storage(settings) if settings.s3_bucket else LocalStorage(settings)
