"""`dw.run_manifest/v1` (tenant-config R6.1, R6.8; TC15, TC32)."""

from __future__ import annotations

import copy
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from dw_kernel.canonical import content_hash
from dw_studio.core.domain.run_manifest import RunManifest

pytestmark = pytest.mark.unit

H = "sha256:" + "a" * 64


def body(**root: Any) -> dict[str, Any]:
    return {
        "schema": "dw.run_manifest/v1",
        "release_manifest_ref": "sha256:" + "e" * 64,
        "run_mode": "live",
        "root": {
            "kind": "fixture",
            "artifact_id": str(uuid.UUID(int=1)),
            "version_id": str(uuid.UUID(int=2)),
            "version_no": 3,
            "definition_hash": H,
            **root,
        },
        "closure": [
            {"kind": "artifact", "key": str(uuid.UUID(int=4)), "version": 1, "content_hash": H}
        ],
        "engine": {"durability": "sync"},
    }


def test_a_sealed_roots_body_round_trips_and_names_no_stage() -> None:
    manifest = RunManifest.model_validate(body())
    assert manifest.as_body() == body()
    assert content_hash(manifest.as_body()) == content_hash(body())


def test_a_draft_root_carries_its_stage_and_no_number() -> None:
    draft = body(version_no=None, stage="draft")
    assert RunManifest.model_validate(draft).as_body()["root"] == draft["root"]
    for wrong in (body(stage="draft"), body(version_no=None)):
        with pytest.raises(ValidationError):
            RunManifest.model_validate(wrong)


@pytest.mark.parametrize(
    "engine",
    [{"durability": "async"}, {}, {"durability": "sync", "compiler_version": "1"}],
    ids=["async", "missing", "extra"],
)
def test_the_engine_takes_sync_and_nothing_else(engine: dict[str, Any]) -> None:
    """R6.8 (TC32)."""
    wrong = body()
    wrong["engine"] = engine
    with pytest.raises(ValidationError):
        RunManifest.model_validate(wrong)


@pytest.mark.parametrize("at", ["top", "root", "closure"])
def test_a_key_nobody_reads_is_refused_at_every_level(at: str) -> None:
    """TC15: a `secret_version` cannot ride in, at any level."""
    wrong = copy.deepcopy(body())
    target = {"top": wrong, "root": wrong["root"], "closure": wrong["closure"][0]}[at]
    target["secret_version"] = 7
    with pytest.raises(ValidationError):
        RunManifest.model_validate(wrong)


def test_another_schema_or_mode_is_refused() -> None:
    for key, value in (("schema", "dw.run_manifest/v2"), ("run_mode", "dry")):
        wrong = body()
        wrong[key] = value
        with pytest.raises(ValidationError):
            RunManifest.model_validate(wrong)
