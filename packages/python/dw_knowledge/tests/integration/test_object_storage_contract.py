"""The object-storage adapter against whatever S3 server the stack runs.

Every storage caller in this platform (knowledge artifacts, feedback
attachments, offboarding export bundles) goes through `ObjectStoragePort`,
and every unit test of those callers uses a fake. So nothing else asks the
real server whether the adapter's promises hold: a missing bucket is created,
bytes round-trip, a prefix lists every key under it at any depth and nothing
outside it, a missing key reads as `NotFoundError`, a delete removes, a request
that carries no signature is refused, a bucket nobody created lists nothing
(`ABSENT_STORE_RULE`), and a stream larger than one part goes up in parts.

This is the test to run against a new server before the stack moves to it. The
S3 server is replaceable: MinIO withdrew its images from two registries in one
year. The contract is not replaceable.
"""

from __future__ import annotations

import asyncio
import io
import os
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator

import pytest
from absent_store import a_missing_bucket_lists_nothing
from minio import Minio
from runtime_harness import runtime_urls

from dw_kernel.errors import NotFoundError
from dw_knowledge.adapters.minio_storage import MinioObjectStorageAdapter

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client() -> Minio:
    urls = runtime_urls()
    return Minio(
        urls.minio_endpoint,
        access_key=urls.minio_access_key,
        secret_key=urls.minio_secret_key,
        secure=False,
    )


@pytest.fixture
def storage(client: Minio) -> Iterator[MinioObjectStorageAdapter]:
    """A bucket of its own that does not exist yet, removed afterwards."""
    bucket = f"dw-contract-{uuid.uuid4().hex[:12]}"
    yield MinioObjectStorageAdapter(client=client, bucket=bucket)
    if client.bucket_exists(bucket):
        for obj in client.list_objects(bucket, recursive=True):
            client.remove_object(bucket, obj.object_name)
        client.remove_bucket(bucket)


def test_a_write_creates_the_missing_bucket_and_the_bytes_round_trip(
    storage: MinioObjectStorageAdapter,
) -> None:
    data = "hồ sơ dự thầu, bản 1".encode()

    uri = asyncio.run(storage.put_object("t1/w1/doc.txt", data, "text/plain"))

    assert uri == f"s3://{storage.bucket}/t1/w1/doc.txt"
    assert asyncio.run(storage.get_object("t1/w1/doc.txt")) == data


def test_a_prefix_lists_every_key_under_it_at_any_depth_and_nothing_else(
    storage: MinioObjectStorageAdapter,
) -> None:
    """Offboarding exports and purges a tenant by listing its prefix, so a key
    two levels down that the listing misses is data left behind."""
    mine = ["tenant-a/w1/doc-1.pdf", "tenant-a/w1/doc-2/page-1.png", "tenant-a/w2/x.txt"]
    theirs = ["tenant-b/w1/doc-1.pdf", "tenant-ab/w1/doc.pdf"]
    for key in mine + theirs:
        asyncio.run(storage.put_object(key, b"x", "application/octet-stream"))

    listed = asyncio.run(storage.list_objects("tenant-a/"))

    assert sorted(listed) == sorted(mine)


def test_a_missing_key_reads_as_not_found(storage: MinioObjectStorageAdapter) -> None:
    asyncio.run(storage.put_object("t1/present.txt", b"x", "text/plain"))

    with pytest.raises(NotFoundError):
        asyncio.run(storage.get_object("t1/absent.txt"))


def test_a_delete_removes_the_object(storage: MinioObjectStorageAdapter) -> None:
    asyncio.run(storage.put_object("t1/gone.txt", b"x", "text/plain"))

    asyncio.run(storage.delete_object("t1/gone.txt"))

    with pytest.raises(NotFoundError):
        asyncio.run(storage.get_object("t1/gone.txt"))
    assert asyncio.run(storage.list_objects("t1/")) == []


def test_the_store_refuses_an_unsigned_request(client: Minio) -> None:
    """With no identity configured, SeaweedFS's S3 gateway allows every request,
    its documented allow-all mode, and a default that fails open. Compose
    requires the credentials (`:?`). This asserts the running server actually
    enforces them, so a store started without them fails here instead of
    serving every tenant's objects to anyone who asks."""
    endpoint = runtime_urls().minio_endpoint
    bucket = f"dw-anon-{uuid.uuid4().hex[:12]}"

    for method, path in (("PUT", f"/{bucket}"), ("GET", "/")):
        request = urllib.request.Request(f"http://{endpoint}{path}", method=method)
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(request, timeout=10)
        assert refused.value.code == 403, (method, path)

    assert not client.bucket_exists(bucket)


def test_a_bucket_nobody_made_lists_nothing(storage: MinioObjectStorageAdapter) -> None:
    """foundations-hardening R11.12 (FH39): the `feedback` bucket exists only after
    the first attachment, and offboarding a company that never uploaded one used to
    fail at this list with NoSuchBucket (discovery 09)."""
    asyncio.run(a_missing_bucket_lists_nothing(storage))
    assert not asyncio.run(storage.has_object("t1/absent.zip"))


def test_a_stream_larger_than_one_part_goes_up_in_parts(
    storage: MinioObjectStorageAdapter, client: Minio
) -> None:
    """R11.9: the offboarding bundle is uploaded from a file it cannot hold in
    memory. 11 MiB is more than two 5 MiB parts; an object uploaded in parts carries
    an ETag ending in `-<parts>`, which a single PUT does not (measured on
    SeaweedFS 4.48, 5/11/2026)."""
    data = os.urandom(11 * 1024 * 1024)

    uri = asyncio.run(
        storage.put_stream("t1/bundle.zip", io.BytesIO(data), len(data), "application/zip")
    )

    assert uri == f"s3://{storage.bucket}/t1/bundle.zip"
    etag = client.stat_object(storage.bucket, "t1/bundle.zip").etag
    assert etag is not None and etag.endswith("-3"), etag
    assert asyncio.run(storage.get_object("t1/bundle.zip")) == data
    assert asyncio.run(storage.has_object("t1/bundle.zip"))
