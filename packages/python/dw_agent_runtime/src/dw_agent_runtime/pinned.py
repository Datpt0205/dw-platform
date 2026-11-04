"""`PinnedResolver`: a Studio run resolves only what its manifest pinned
(tenant-config R6.3, R6.4; ADR-0109 decision 7).

Built once per run, and again on every resume in whatever process takes it,
by `PinnedResolver.load`, the one place a pinned hash is compared with a row's
content now: a version that was in `draft` when pinned, or was sent back to
`draft` after, and whose content has changed since, refuses the whole load
with `pinned_version_changed`, before anything is returned (decision 8's sixth
check, which workflow-engine/05 reads as `blocked`, `incompatible_resume`).
After `load` the resolver holds everything it can answer; it keeps no port, so
`resolve` never reads the database, and a key the manifest does not hold is a
`ConfigError` naming it, never a read of whatever is current (TC15).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dw_agent_runtime.ports import PinnedEntry, PinnedManifest, RunManifestPort
from dw_kernel.errors import ConfigError

# The closure kind whose entries carry a version row.
ARTIFACT = "artifact"


def _refuse(message: str, reason: str, **details: object) -> ConfigError:
    return ConfigError(message, details={"reason": reason, **details})


def _check(entry: PinnedEntry) -> None:
    row = entry.artifact
    if row is not None and row.current_hash is not None and row.current_hash != entry.content_hash:
        raise _refuse(
            "a pinned version changed after the run pinned it",
            "pinned_version_changed",
            kind=entry.kind,
            key=entry.key,
        )


class PinnedResolver:
    """The answers of one run manifest, read once."""

    def __init__(self, manifest: PinnedManifest) -> None:
        self._manifest = manifest
        self._entries: Mapping[tuple[str, str], PinnedEntry] = {
            (entry.kind, entry.key): entry for entry in manifest.closure
        }

    @classmethod
    async def load(cls, port: RunManifestPort, run_manifest_hash: str) -> PinnedResolver:
        manifest = await port.load(run_manifest_hash)
        if manifest is None:
            raise _refuse("no such run manifest", "manifest_not_found")
        if manifest.unread_keys:
            raise _refuse(
                "a version the run pinned cannot be read",
                "pinned_version_unreadable",
                versions=[str(version) for version in manifest.unread_keys],
            )
        if manifest.root.artifact is None:
            raise _refuse("the run's root version cannot be read", "pinned_version_unreadable")
        for entry in manifest.closure:
            if entry.kind == ARTIFACT and entry.artifact is None:
                raise _refuse(
                    "a version the run pinned cannot be read",
                    "pinned_version_unreadable",
                    key=entry.key,
                )
        for entry in (manifest.root, *manifest.closure):
            _check(entry)
        return cls(manifest)

    @property
    def hash(self) -> str:
        return self._manifest.hash

    @property
    def body(self) -> Mapping[str, Any]:
        return self._manifest.body

    @property
    def root(self) -> PinnedEntry:
        return self._manifest.root

    def resolve(self, kind: str, key: str) -> PinnedEntry:
        """The pinned entry for `(kind, key)`; an `artifact` one carries its row."""
        entry = self._entries.get((kind, key))
        if entry is None:
            raise ConfigError(
                "the run manifest does not pin this key",
                details={"reason": "key_not_pinned", "kind": kind, "key": key},
            )
        return entry
