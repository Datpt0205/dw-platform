"""`dw.agent/v1`: the document of an agent version (ADR-0117 decision 2;
agent-builder ticket 02 step 1).

Only the sections W1 reads (the spec's "Trong phạm vi"): `display`,
`instructions`, `model.profile`, `toolset`, `field_caps`, `route_class` and
`purpose`, beside the `bindings[]` every kind's document may declare
(tenant-config R7). A W2 section (`limits`, `knowledge`, `links`,
`sub_agents`, `delegation`, `surfaces`, `conversation`, `output_schema`,
`ai_risk_tier`) joins with the ticket that reads it (failure-modes #1), so
until then it is a key outside the schema: a warning at save, a 422 at seal.
No W1 section holds a decimal; one that does carries it as a string.

Two pure functions are the kind's registry entry's `validate` and `extract`:
`validate_agent` returns every problem at once, the shape's, the toolset's
(`validate_toolset`, never a copy) and the instruction rules' (one code per
rule, `lint_instructions` of the runtime, which the `ai.llm` step shares);
`extract_agent` returns the toolset's references (`extract_toolset`) and the
frame the run renders, `studio.agent_frame@1.0.0`, so the closure and a run's
manifest pin both.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, StringConstraints, ValidationError

from dw_agent_runtime.model.prompts import lint_instructions
from dw_studio.core.domain.artifacts import DocumentProblem, Reference, TargetKind, Usage
from dw_studio.core.domain.toolset import TOOLSET_POINTER, extract_toolset, validate_toolset

AGENT_KIND: Final = "agent"
AGENT_DOCUMENT_SCHEMA: Final = "dw.agent/v1"
# The frame every agent version's system message is assembled in (ADR-0117
# decision 4), pinned as a platform artifact by the seal and the run manifest.
AGENT_FRAME_ID: Final = "studio.agent_frame"
AGENT_FRAME_VERSION: Final = "1.0.0"
AGENT_FRAME_KEY: Final = f"{AGENT_FRAME_ID}@{AGENT_FRAME_VERSION}"
INSTRUCTIONS_POINTER: Final = "/instructions"

# The data routes a version may tighten to (compliance-pdpl; ADR-0123): one
# looser than the company's is compliance-pdpl R2.4's to refuse at submit.
RouteClass = Literal["vn_only", "cross_border_minimised", "cross_border_full"]

# An object's or a field's API name (ADR-0107; `ck_artifacts_api_name`).
_ApiName = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]{1,39}$")]
# A platform model profile's id (`configs/models/<id>.yaml`); whether the
# company's plan offers it is the resolver's question at run (model-connections
# R2.2), not the document's.
_ProfileId = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]{0,62}$")]


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Display(_Section):
    """What a person sees the agent as; `name` is the frame's `agent_name`."""

    name: StrictStr = Field(min_length=1, max_length=120)


class ModelChoice(_Section):
    profile: _ProfileId


class AgentDocument(_Section):
    """`dw.agent/v1` in W1. `toolset` and `bindings` are typed by their own
    checks (`validate_toolset`, the envelope's `parse_declarations`), so a
    wrong one is named once, by its owner."""

    display: Display
    instructions: StrictStr
    model: ModelChoice
    toolset: Any = None
    # The fields an object's tools may read, by object (agent-builder/05 reads
    # it into the version's data boundary): an allow-list, empty for none.
    field_caps: dict[_ApiName, tuple[_ApiName, ...]] = Field(default_factory=dict)
    # Absent: no tighter than the company's and the workspace's route.
    route_class: RouteClass | None = None
    purpose: StrictStr | None = Field(default=None, max_length=500)
    bindings: Any = None


_CODES: Final[Mapping[str, str]] = {
    "missing": "required",
    "extra_forbidden": "not_allowed",
    "literal_error": "value_not_allowed",
    "string_pattern_mismatch": "value_not_allowed",
    "string_too_short": "too_short",
    "string_too_long": "too_long",
}


def _pointer(location: Sequence[int | str]) -> str:
    # A mapping key that is wrong is located at the key itself (`[key]` is
    # pydantic's marker, not a member of the document).
    parts = (
        str(part).replace("~", "~0").replace("/", "~1") for part in location if part != "[key]"
    )
    return "".join(f"/{part}" for part in parts)


def _shape_problems(document: Any) -> list[DocumentProblem]:
    try:
        AgentDocument.model_validate(document)
    except ValidationError as exc:
        # A fixed sentence per code, never pydantic's message: it may echo the value.
        return [
            DocumentProblem(
                _pointer(tuple(item["loc"])),
                _CODES.get(item["type"], "wrong_type"),
                "the value is not one this document takes",
            )
            for item in exc.errors()
        ]
    return []


def instruction_problems(text: str, *, at: str = INSTRUCTIONS_POINTER) -> list[DocumentProblem]:
    """ADR-0117 decision 4's rules, each broken one a problem at `at`."""
    return [
        DocumentProblem(at, finding.code, finding.detail) for finding in lint_instructions(text)
    ]


def validate_agent(document: Any) -> list[DocumentProblem]:
    """The registry's `validate` for `agent`: pure, every problem at once
    (R1.3, R1.6, R2.4)."""
    if not isinstance(document, dict):
        return [DocumentProblem("", "document_not_object", "a document is a JSON object")]
    problems = _shape_problems(document)
    if "toolset" in document:
        problems += validate_toolset(document["toolset"], at=TOOLSET_POINTER)
    instructions = document.get("instructions")
    if isinstance(instructions, str):
        problems += instruction_problems(instructions)
    return problems


def agent_model_profiles(document: Any) -> frozenset[str]:
    """The registry's `model_profiles` for `agent` (model-connections/02 step
    5; ADR-0118 Amendments 2026-11-04): the profile the version names, which
    the run manifest pins by value (`engine.model_routes`); none for a
    document without one, whose calls are then refused `key_not_pinned`."""
    model = document.get("model") if isinstance(document, dict) else None
    profile = model.get("profile") if isinstance(model, dict) else None
    return frozenset({profile}) if isinstance(profile, str) and profile else frozenset()


def extract_agent(document: Any) -> list[Reference]:
    """The registry's `extract` for `agent`: the toolset's references and the
    frame. `bindings[]` the envelope adds itself (`binding_references`)."""
    if not isinstance(document, dict):
        return []
    found = [
        Reference(TargetKind.PLATFORM_ARTIFACT, AGENT_FRAME_KEY, Usage.READ, INSTRUCTIONS_POINTER)
    ]
    if "toolset" in document:
        found += extract_toolset(document["toolset"], at=TOOLSET_POINTER)
    return found


__all__ = [
    "AGENT_DOCUMENT_SCHEMA",
    "AGENT_FRAME_ID",
    "AGENT_FRAME_KEY",
    "AGENT_FRAME_VERSION",
    "AGENT_KIND",
    "AgentDocument",
    "agent_model_profiles",
    "extract_agent",
    "instruction_problems",
    "validate_agent",
]
