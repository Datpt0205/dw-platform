"""MinIO/S3 object storage adapter. The MinIO SDK is blocking, so calls run in
a worker thread. Keys are tenant-prefixed by the gateway.

Implements ``ObjectStoragePort``, and ``put_stream``/``has_object`` for a caller
that uploads a file it cannot hold in memory (the offboarding lane's
``ExportSinkPort``, foundations-hardening R11.9). Behind both, the store's
contract test (``tests/integration/test_object_storage_contract.py``) runs
against the S3 server compose runs."""

from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from typing import BinaryIO

from minio import Minio
from minio.error import MinioException, S3Error

from dw_kernel.errors import InfrastructureError, NotFoundError


@dataclass
class MinioObjectStorageAdapter:
    """Implements ``ObjectStoragePort``."""

    client: Minio
    bucket: str

    def _ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def _put_sync(self, key: str, data: bytes, content_type: str) -> str:
        self._ensure_bucket()
        self.client.put_object(
            self.bucket,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return f"s3://{self.bucket}/{key}"

    def _get_sync(self, key: str) -> bytes:
        response = self.client.get_object(self.bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    async def put_object(self, key: str, data: bytes, content_type: str) -> str:
        try:
            return await asyncio.to_thread(self._put_sync, key, data, content_type)
        except MinioException as exc:
            raise InfrastructureError("object storage write failed", details={"key": key}) from exc

    async def get_object(self, key: str) -> bytes:
        try:
            return await asyncio.to_thread(self._get_sync, key)
        except MinioException as exc:
            raise NotFoundError(
                "artifact not found in object storage", details={"key": key}
            ) from exc

    def _put_stream_sync(self, key: str, data: BinaryIO, length: int, content_type: str) -> str:
        self._ensure_bucket()
        # A known length past one part (5 MiB) goes up as a multipart upload, at
        # most three parts in flight (minio 7.2.20), and the SDK aborts the upload
        # when a part fails; nothing reads the stream whole.
        self.client.put_object(self.bucket, key, data, length=length, content_type=content_type)
        return f"s3://{self.bucket}/{key}"

    async def put_stream(self, key: str, data: BinaryIO, length: int, content_type: str) -> str:
        """Upload `length` bytes read from `data`, in parts when larger than one."""
        try:
            return await asyncio.to_thread(self._put_stream_sync, key, data, length, content_type)
        except MinioException as exc:
            raise InfrastructureError("object storage write failed", details={"key": key}) from exc

    def _has_sync(self, key: str) -> bool:
        try:
            self.client.stat_object(self.bucket, key)
        except S3Error as exc:
            # The codes SeaweedFS answers a HEAD of a missing key and bucket with
            # (measured 5/11/2026); anything else is a store that cannot answer.
            if exc.code in ("NoSuchKey", "NoSuchBucket"):
                return False
            raise
        return True

    async def has_object(self, key: str) -> bool:
        """Whether `key` is in the bucket; a store that cannot answer raises."""
        try:
            return await asyncio.to_thread(self._has_sync, key)
        except MinioException as exc:
            raise InfrastructureError("object storage stat failed", details={"key": key}) from exc

    def _list_sync(self, prefix: str) -> list[str]:
        # ABSENT_STORE_RULE: a bucket nobody created yet (feedback's is made on
        # its first upload) lists nothing, rather than NoSuchBucket.
        if not self.client.bucket_exists(self.bucket):
            return []
        return [
            obj.object_name
            for obj in self.client.list_objects(self.bucket, prefix=prefix, recursive=True)
        ]

    async def list_objects(self, prefix: str) -> list[str]:
        try:
            return await asyncio.to_thread(self._list_sync, prefix)
        except MinioException as exc:
            raise InfrastructureError(
                "object storage list failed", details={"prefix": prefix}
            ) from exc

    async def delete_object(self, key: str) -> None:
        try:
            await asyncio.to_thread(self.client.remove_object, self.bucket, key)
        except MinioException as exc:
            raise InfrastructureError("object storage delete failed", details={"key": key}) from exc
