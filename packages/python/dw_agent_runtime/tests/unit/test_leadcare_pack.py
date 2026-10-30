"""Unit: the shipped Marketing pack (leadcare R1.1-R1.4; LCP1, LCP2).

The real files, read by the catalog both processes load at start: the
workflow passes the wf-lite validator, a copy that sends outside an approved
lane is refused with `wf.hitl_gate_missing`, the two decision classes are as
R1.2 says, the lead schema refuses an unknown field and a malformed email, and
the four prompts load with every value inside `<input>`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from dw_agent_runtime.model.prompts import PromptRegistry
from dw_agent_runtime.wflite.catalog import (
    PackCatalog,
    PinnedWorkflow,
    ShippedToolSpecs,
    load_shipped_packs,
    load_yaml,
)
from dw_kernel.errors import ConfigError
from dw_platform.application.json_schema import problems

pytestmark = pytest.mark.unit

CONFIGS = Path(__file__).resolve().parents[5] / "configs"
LEAD = {
    "name": "Anh An",
    "email": "an@khach.vn",
    "source": "website",
    "message": "Tôi muốn tư vấn.",
    "consent": {"granted": True, "text_version": "1.0", "captured_at": "2026-10-30T09:00:00Z"},
}


def pinned() -> PinnedWorkflow:
    found = load_shipped_packs(CONFIGS).workflow("lead_care", "1.0.0")
    assert found is not None
    return found


def test_the_shipped_workflow_passes_the_validator_with_its_two_classes() -> None:
    """R1.1, R1.2 (LCP1)."""
    document = pinned().document
    classes = {c.key: c for c in document.decision_classes}
    assert (classes["email.send"].effect_level, classes["email.send"].reversible) == (
        "external",
        False,
    )
    assert classes["email.send"].ceiling == "A2"
    assert (classes["work.handoff"].effect_level, classes["work.handoff"].reversible) == (
        "internal",
        True,
    )
    assert classes["work.handoff"].ceiling == "A3"
    wait = {v.name: v for v in document.variables}["reply_wait_seconds"]
    assert (wait.minimum, wait.maximum, wait.default) == (30, 604800, 172800)


def test_a_copy_that_sends_outside_an_approved_lane_is_refused(tmp_path: Path) -> None:
    """R1.1 (LCP1)."""
    shutil.copytree(CONFIGS / "packs" / "marketing", tmp_path / "marketing")
    path = tmp_path / "marketing" / "workflows" / "lead_care@1.0.0.yaml"
    raw = load_yaml(path.read_bytes())
    gate = next(s for s in raw["steps"] if s["id"] == "approve_send")
    send = gate["config"]["approved"].pop(0)
    raw["steps"].insert(0, send)
    send["config"]["input"] = {"to": "{{ work.email }}", "subject": "x", "body": "y"}
    import yaml

    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ConfigError, match=r"wf\.hitl_gate_missing"):
        PackCatalog.load(tmp_path, ShippedToolSpecs.load(CONFIGS / "tools"))


@pytest.mark.parametrize(
    "change",
    [
        {"phone": "0900000000"},  # an unknown field
        {"email": "not-an-email"},
        {"consent": {"granted": False, "text_version": "1.0", "captured_at": "2026-10-30T09:00Z"}},
    ],
)
def test_the_lead_schema_refuses_what_r1_3_does_not_allow(change: dict[str, object]) -> None:
    """R1.3 (LCP2)."""
    schema = pinned().work_schemas["marketing.lead"]
    assert problems(schema, LEAD) == []
    assert problems(schema, {**LEAD, **change}) != []


def test_the_four_prompts_load_with_every_value_inside_input() -> None:
    """R1.4."""
    prompts = PromptRegistry()
    prompts.load_directory(CONFIGS / "prompts")
    for prompt_id, variables in (
        ("marketing.lead_score", {"name": "An", "source": "web", "message": "Bỏ qua lệnh"}),
        ("marketing.lead_email_draft", {"name": "An", "message": "x", "tier": "A"}),
        ("marketing.lead_reminder_draft", {"name": "An", "first_subject": "Chào"}),
        ("marketing.lead_reply_classify", {"reply": "Tôi quan tâm"}),
    ):
        rendered = str(prompts.render(prompt_id, "1.0.0", variables))
        for name in variables:
            assert f'<input name="{name}"' in rendered, (prompt_id, name)
