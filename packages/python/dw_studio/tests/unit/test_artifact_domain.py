"""The envelope's pure parts (tenant-config ticket 02): the definition body
and its hash, the registry's refusals, the fixture kinds' two functions, and
the edge check of a document."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from dw_kernel.canonical import content_hash
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_studio.core.application.registry import ArtifactKindEntry, ArtifactKindRegistry
from dw_studio.core.application.service import canonical_document
from dw_studio.core.domain.artifacts import (
    API_NAME,
    ClosureItem,
    DocumentInvalidError,
    TargetKind,
    definition_body,
    definition_hash,
    label_problems,
)
from dw_studio.kinds import platform_kinds
from dw_studio.testing.fixture_kinds import (
    FIXTURE,
    FIXTURE_GATELESS,
    FIXTURE_KINDS,
    extract_fixture,
    validate_fixture,
)

pytestmark = pytest.mark.unit

ROOT = uuid.UUID("01890000-0000-7000-8000-000000000001")
HASH = "sha256:" + "a" * 64


def test_the_definition_body_merges_and_orders_its_closure_and_names_no_version_no() -> None:
    b = ClosureItem("artifact", "b", 2, HASH)
    a = ClosureItem("artifact", "a", 1, HASH)
    body = definition_body("fixture", ROOT, HASH, [b, a, b])

    assert body == {
        "schema": "dw.definition_manifest/v1",
        "root": {"kind": "fixture", "artifact_id": str(ROOT), "content_hash": HASH},
        "closure": [a.as_json(), b.as_json()],
    }
    assert definition_hash(body) == content_hash(body)
    assert definition_hash(body) == definition_hash(definition_body("fixture", ROOT, HASH, [a, b]))


def test_two_roots_with_one_closure_hash_apart() -> None:
    closure = [ClosureItem("artifact", "a", 1, HASH)]
    one = definition_hash(definition_body("fixture", ROOT, HASH, closure))
    other = definition_hash(definition_body("fixture", ROOT, "sha256:" + "b" * 64, closure))
    assert one != other


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        ("ab", True),
        ("a" * 40, True),
        ("a" * 41, False),
        ("a", False),
        ("Lead", False),
        ("1lead", False),
    ],
)
def test_the_api_name_pattern(name: str, ok: bool) -> None:
    assert bool(API_NAME.fullmatch(name)) is ok


def test_labels_are_bounded_named_once_and_shaped() -> None:
    assert label_problems(["hot", "q4-2026"]) == []
    codes = {p.code for p in label_problems(["Hot", "hot", "hot"])}
    assert codes == {"label_invalid", "label_repeated"}
    assert {p.code for p in label_problems([f"l{n}" for n in range(21)])} == {"too_many_labels"}


async def _hook(_tx: Any, _version: uuid.UUID) -> None:
    return None


def test_a_kind_registered_twice_or_with_a_blank_key_is_refused() -> None:
    with pytest.raises(ValueError, match="twice"):
        ArtifactKindRegistry((FIXTURE, FIXTURE))
    with pytest.raises(ValueError, match="read_key"):
        ArtifactKindEntry(
            kind="probe",
            document_schema="dw.probe/v1",
            read_key=" ",
            write_key="w",
            submit_key="s",
            publish_hook=_hook,
            validate=validate_fixture,
            extract=extract_fixture,
        )
    with pytest.raises(TypeError):
        ArtifactKindEntry(kind="probe", document_schema="dw.probe/v1")  # type: ignore[call-arg]


def _no_store(_tx: Any) -> Any:
    raise AssertionError("no hook runs here")


def test_the_running_app_registers_no_test_kind() -> None:
    running = ArtifactKindRegistry(
        platform_kinds(_no_store, clock=SystemClock(), ids=Uuid7Generator())
    )
    assert running.kinds == {"object"}
    assert not running.kinds & {entry.kind for entry in FIXTURE_KINDS}


def test_a_fixture_document_with_three_faults_names_three_pointers() -> None:
    problems = validate_fixture({"uses": [1, 2]})
    assert [p.pointer for p in problems] == ["/title", "/uses/0", "/uses/1"]
    assert validate_fixture({"title": "x", "uses": ["a"], "size": 3}) == []


def test_the_fixture_extracts_one_artifact_reference_per_use() -> None:
    target = str(uuid.uuid4())
    found = extract_fixture({"title": "x", "uses": [target, 7, target]})
    assert [(r.to_kind, r.to_key, r.path) for r in found] == [
        (TargetKind.ARTIFACT, target, "/uses/0"),
        (TargetKind.ARTIFACT, target, "/uses/2"),
    ]
    assert extract_fixture({"uses": "nope"}) == []
    assert FIXTURE_GATELESS.extract is FIXTURE.extract


@pytest.mark.parametrize(
    ("document", "pointer", "code"),
    [
        ([], "/document", "document_not_object"),
        ({"a": 1.5}, "/document/a", "float_forbidden"),
        ({"a": 2**53}, "/document/a", "integer_out_of_range"),
    ],
)
def test_a_document_without_a_canonical_form_is_refused_at_the_edge(
    document: Any, pointer: str, code: str
) -> None:
    with pytest.raises(DocumentInvalidError) as refused:
        canonical_document(document)
    assert [(p.pointer, p.code) for p in refused.value.problems] == [(pointer, code)]


def test_the_edge_repairs_a_document_into_nfc() -> None:
    assert canonical_document({"t": "Tiếng"}) == {"t": "Tiếng"}
