"""MinIO 连接管理器 — 基于线程池的异步包装."""

import asyncio
from typing import Any

from minio import Minio
from minio.commonconfig import CopySource

from mcp_minio.config import MinioConfig


class MinioConnection:
    """MinIO 连接管理器.

    minio-py SDK 是同步的, 通过 asyncio.to_thread 包装为异步调用,
    避免阻塞事件循环.
    """

    def __init__(self, config: MinioConfig | None = None):
        self._config = config or MinioConfig()
        self._client: Minio | None = None

    @property
    def config(self) -> MinioConfig:
        return self._config

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    def _require_client(self) -> Minio:
        if self._client is None:
            raise RuntimeError("未连接 MinIO, 请先调用 minio_connect")
        return self._client

    # ── 连接生命周期 ──

    async def connect(self, **overrides: Any) -> None:
        if self._client is not None:
            await self.disconnect()

        endpoint = overrides.get("endpoint", self._config.endpoint)
        access_key = overrides.get("access_key", self._config.access_key)
        secret_key = overrides.get("secret_key", self._config.secret_key)
        secure = overrides.get("secure", self._config.secure)
        region = overrides.get("region", self._config.region) or None

        def _create() -> Minio:
            client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure, region=region)
            client.list_buckets()  # 验证连接
            return client

        try:
            self._client = await asyncio.to_thread(_create)
        except Exception as e:
            self._client = None
            raise ConnectionError(f"连接 MinIO 失败: {e}") from e

    async def disconnect(self) -> None:
        self._client = None

    # ── Bucket 操作 ──

    async def list_buckets(self) -> list[dict[str, Any]]:
        def _do() -> list[dict[str, Any]]:
            buckets = self._require_client().list_buckets()
            return [{"name": b.name, "creation_date": str(b.creation_date)} for b in buckets]
        return await asyncio.to_thread(_do)

    async def bucket_exists(self, name: str) -> bool:
        def _do() -> bool:
            try:
                return self._require_client().bucket_exists(name)
            except ValueError:
                return False
        return await asyncio.to_thread(_do)

    async def make_bucket(self, name: str) -> None:
        return await asyncio.to_thread(self._require_client().make_bucket, name)

    async def remove_bucket(self, name: str) -> None:
        return await asyncio.to_thread(self._require_client().remove_bucket, name)

    # ── Object 操作 ──

    async def put_object(self, bucket: str, name: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        import io
        def _do() -> None:
            self._require_client().put_object(bucket, name, io.BytesIO(data), len(data), content_type=content_type)
        return await asyncio.to_thread(_do)

    async def get_object(self, bucket: str, name: str) -> bytes | None:
        def _do() -> bytes | None:
            try:
                response = self._require_client().get_object(bucket, name)
                return response.read()
            except Exception:
                return None
        return await asyncio.to_thread(_do)

    async def remove_object(self, bucket: str, name: str) -> None:
        return await asyncio.to_thread(self._require_client().remove_object, bucket, name)

    async def list_objects(self, bucket: str, prefix: str = "", *, recursive: bool = False, max_keys: int = 100) -> list[dict[str, Any]]:
        def _do() -> list[dict[str, Any]]:
            objs = self._require_client().list_objects(bucket, prefix=prefix or None, recursive=recursive)
            result = []
            for i, obj in enumerate(objs):
                if i >= max_keys:
                    break
                result.append({
                    "name": obj.object_name, "size": obj.size,
                    "last_modified": str(obj.last_modified), "etag": obj.etag,
                    "is_dir": obj.is_dir,
                })
            return result
        return await asyncio.to_thread(_do)

    async def stat_object(self, bucket: str, name: str) -> dict[str, Any] | None:
        def _do() -> dict[str, Any] | None:
            try:
                stat = self._require_client().stat_object(bucket, name)
                return {
                    "name": stat.object_name, "size": stat.size,
                    "content_type": stat.content_type, "etag": stat.etag,
                    "last_modified": str(stat.last_modified),
                    "metadata": dict(stat.metadata or {}),
                }
            except Exception:
                return None
        return await asyncio.to_thread(_do)

    async def copy_object(self, src_bucket: str, src_name: str, dst_bucket: str, dst_name: str) -> None:
        def _do() -> None:
            self._require_client().copy_object(dst_bucket, dst_name, CopySource(src_bucket, src_name))
        return await asyncio.to_thread(_do)

    # ── Presigned URL ──

    async def presigned_get_url(self, bucket: str, name: str, expires: int = 3600) -> str:
        from datetime import timedelta
        return await asyncio.to_thread(self._require_client().presigned_get_object, bucket, name, expires=timedelta(seconds=expires))

    async def presigned_put_url(self, bucket: str, name: str, expires: int = 3600) -> str:
        from datetime import timedelta
        return await asyncio.to_thread(self._require_client().presigned_put_object, bucket, name, expires=timedelta(seconds=expires))
