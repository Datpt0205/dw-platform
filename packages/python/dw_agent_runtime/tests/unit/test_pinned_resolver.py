"""`PinnedResolver` over a spy port (tenant-config R6.3, R6.4; TC15).

The database half, a real `SqlRunManifestStore` and resumes in a fresh
process, is `dw_studio`'s `test_run_manifest.py`.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from dw_agent_runtime.pinned import PinnedResolver
from dw_agent_runtime.ports import PinnedEntry, PinnedManifest, PinnedVersion
from dw_kernel.errors import ConfigError

pytestmark = pytest.mark.unit

H_ROOT = "sha256:" + "a" * 64
H_T1 = "sha256:" + "b" * 64
H_OTHER = "sha256:" + "f" * 64
ROOT_ID, T1_ID = uuid.uuid4(), uuid.uuid4()


def version(
    artifact_id: uuid.UUID, *, stage: str = "live", current_hash: str | None = None
) -> PinnedVersion:
    return PinnedVersion(
        id=uuid.uuid4(),
        artifact_id=artifact_id,
        version_no=None if stage == "draft" else 1,
        stage=stage,
        content_hash=None,
        definition_hash=None,
        document_schema="dw.fixture/v1",
        document={"title": "v1"},
        current_hash=current_hash,
    )


def manifest(
    *,
    root: PinnedVersion | None = None,
    target: PinnedVersion | str | None = "default",
    unread: tuple[uuid.UUID, ...] = (),
) -> PinnedManifest:
    t1 = version(T1_ID) if target == "default" else target
    assert not isinstance(t1, str)
    return PinnedManifest(
        hash=H_OTHER,
        body={"schema": "dw.run_manifest/v1"},
        root=PinnedEntry("fixture", str(ROOT_ID), 1, H_ROOT, root or version(ROOT_ID)),
        closure=(
            PinnedEntry("artifact", str(T1_ID), 1, H_T1, t1),
            PinnedEntry("platform_artifact", "prompts/x", 2, None),
        ),
        unread_keys=unread,
    )


class SpyPort:
    def __init__(self, answer: PinnedManifest | None) -> None:
        self.answer = answer
        self.calls: list[str] = []

    async def load(self, run_manifest_hash: str) -> PinnedManifest | None:
        self.calls.append(run_manifest_hash)
        return self.answer


async def refused(port: SpyPort) -> dict[str, Any]:
    with pytest.raises(ConfigError) as caught:
        await PinnedResolver.load(port, H_OTHER)
    return caught.value.details


async def test_a_hash_this_tenant_does_not_hold_is_manifest_not_found() -> None:
    assert (await refused(SpyPort(None)))["reason"] == "manifest_not_found"


async def test_a_key_the_manifest_does_not_pin_is_refused_without_a_read() -> None:
    """R6.3: `details.key`, and the port is never asked again after `load`."""
    port = SpyPort(manifest())
    resolver = await PinnedResolver.load(port, H_OTHER)
    assert port.calls == [H_OTHER]

    unpinned = str(uuid.uuid4())
    with pytest.raises(ConfigError) as caught:
        resolver.resolve("artifact", unpinned)
    assert caught.value.details["key"] == unpinned
    assert caught.value.details["reason"] == "key_not_pinned"
    with pytest.raises(ConfigError):
        resolver.resolve("fixture", str(T1_ID))  # the right key under another kind
    assert port.calls == [H_OTHER]


async def test_a_pinned_key_answers_with_its_entry_and_row() -> None:
    resolver = await PinnedResolver.load(SpyPort(manifest()), H_OTHER)
    entry = resolver.resolve("artifact", str(T1_ID))
    assert entry.content_hash == H_T1 and entry.artifact is not None
    assert entry.artifact.document == {"title": "v1"}
    other = resolver.resolve("platform_artifact", "prompts/x")
    assert other.version == 2 and other.artifact is None
    assert resolver.root.key == str(ROOT_ID)


async def test_a_draft_root_whose_content_changed_refuses_the_whole_load() -> None:
    """R6.4: no content of any entry comes back."""
    port = SpyPort(manifest(root=version(ROOT_ID, stage="draft", current_hash=H_OTHER)))
    details = await refused(port)
    assert details["reason"] == "pinned_version_changed"
    assert details["key"] == str(ROOT_ID)


async def test_a_draft_root_hashed_the_same_loads() -> None:
    port = SpyPort(manifest(root=version(ROOT_ID, stage="draft", current_hash=H_ROOT)))
    resolver = await PinnedResolver.load(port, H_OTHER)
    assert resolver.root.artifact is not None


async def test_a_closure_row_sent_back_to_draft_and_edited_refuses() -> None:
    port = SpyPort(manifest(target=version(T1_ID, stage="draft", current_hash=H_OTHER)))
    details = await refused(port)
    assert details == {
        "reason": "pinned_version_changed",
        "kind": "artifact",
        "key": str(T1_ID),
    }


async def test_a_key_row_that_cannot_be_read_refuses() -> None:
    lost = uuid.uuid4()
    assert (await refused(SpyPort(manifest(unread=(lost,)))))["versions"] == [str(lost)]
    assert (await refused(SpyPort(manifest(target=None))))["key"] == str(T1_ID)
