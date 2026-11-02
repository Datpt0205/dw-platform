"""Contract test: `contracts/jsonschema/pd_classification.json` is generated, never edited.

It is what the web's Vietnamese labels are tested against (compliance-pdpl
R1.3), so a hand edit there would let a label table pass against a list the
kernel does not hold. `scripts/generate_contracts.py --check`, which CI runs,
reports the file stale; this proves that, and that the schema leaves the
missing category to the owner's `pd_category_required` (R1.1).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from dw_kernel.personal_data import PdCategory, SensitiveType, SubjectIdentifierKind
from dw_platform.application.json_schema import problems

REPO_ROOT = Path(__file__).resolve().parents[4]
SNAPSHOT = REPO_ROOT / "contracts" / "jsonschema" / "pd_classification.json"

pytestmark = pytest.mark.contract

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from generate_contracts import (  # type: ignore[import-not-found]  # noqa: E402
    build_pd_classification,
    render,
    stale,
)


def _committed() -> dict[str, object]:
    assert SNAPSHOT.exists(), "run `make generate-contracts` to create the schema"
    loaded: dict[str, object] = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    return loaded


def test_the_committed_schema_is_the_generated_one() -> None:
    assert stale({SNAPSHOT: render(build_pd_classification())}) == []


def test_the_schema_carries_the_kernels_three_lists() -> None:
    properties = _committed()["properties"]
    assert isinstance(properties, dict)
    assert properties["pd_category"]["enum"] == [m.value for m in PdCategory]
    assert properties["sensitive_type"]["enum"] == [*(m.value for m in SensitiveType), None]
    assert properties["subject_identifier"]["enum"] == [
        *(m.value for m in SubjectIdentifierKind),
        None,
    ]


def test_a_hand_edited_enum_is_reported_stale(tmp_path: Path) -> None:
    """R1.4: the drift `--check` reports, on a copy with one value renamed."""
    edited = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    edited["properties"]["sensitive_type"]["enum"][0] = "race"
    copy = tmp_path / "pd_classification.json"
    copy.write_text(render(edited), encoding="utf-8")
    assert stale({copy: render(build_pd_classification())}) == [copy]


def test_a_field_without_a_category_passes_the_schema_and_a_wrong_value_does_not() -> None:
    """The missing category is the owner's `pd_category_required`, with its
    pointer, never the validator's `missing`; a value outside a list is the
    schema's own refusal."""
    schema = _committed()
    assert problems(schema, {}) == []
    assert problems(schema, {"pd_category": "sensitive", "sensitive_type": "health"}) == []
    assert problems(schema, {"pd_category": "secret"}) != []
    assert problems(schema, {"pd_category": "basic", "sensitive_type": "other"}) != []
