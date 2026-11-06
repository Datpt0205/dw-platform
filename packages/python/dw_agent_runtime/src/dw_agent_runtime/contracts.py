"""Immutable, versioned runtime contracts.

Changing a prompt, tool or graph requires a new version — these models are
frozen and carry explicit version fields that feed the release manifest.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dw_kernel.autonomy import FAIL_CLOSED_LEVEL, AutonomyLevel
from dw_kernel.residency import RouteClass
from dw_kernel.run_mode import RunMode

_SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"
# What a run is keyed on: a semver, or one with build metadata. A tenant's
# published workflow runs as `<pack semver>+t<n>.<content sha256>`, so two
# tenants' `+t1` never share a graph unless their documents are the same
# (wf-ai R6.5, `dw_agent_runtime.wflite.versions`).
_RUN_VERSION_PATTERN = r"^\d+\.\d+\.\d+(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$"
_SLUG_PATTERN = r"^[a-z][a-z0-9_]*$"

SideEffectLevel = Literal["none", "internal", "external", "critical"]
ApprovalPolicy = Literal["never", "conditional", "always"]

# What reaches a model of a tool (ADR-0116 decisions 5, 6; tools-and-skills
# R4.3, R4.5): a name of at most 64 characters, and at most 40 tools in all.
# Read by the Studio seal (`dw_studio.core.domain.toolset`) and the Studio
# assembler (`adapters.studio_tools`) alike, so the two cannot disagree.
MAX_TOOL_NAME_CHARS: Final = 64
MAX_MODEL_TOOLS: Final = 40
# What a provider accepts as a tool's name, and so all a model-facing name
# may hold: it is written into the `<tool_output source="...">` block as is.
MODEL_TOOL_NAME: Final = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_NAME_SEPARATOR = "__"
# A JSON Pointer (RFC 6901) into a tool's output: "" is the whole of it.
_JSON_POINTER_PATTERN = r"^(/([^~/]|~[01])*)*$"
# The model-facing view's ceilings (ADR-0116 decision 5; YC48): a tool's own
# cap in characters, under a hard one of 16 KiB of UTF-8 bytes.
DEFAULT_MAX_OUTPUT_CHARS: Final = 8_000
MAX_OUTPUT_BYTES: Final = 16_384


def model_facing_name(tool_name: str) -> str:
    """Providers accept ``[a-zA-Z0-9_-]`` only, so the namespace dot cannot survive."""
    return tool_name.replace(".", _NAME_SEPARATOR)


# The side effects a tool may have and still claim it never needs a person.
_NEVER_IS_HONEST_FOR: Final = frozenset({"none", "internal"})


def approval_policy_disagrees_with_side_effect(
    *, approval_policy: str, side_effect_level: str
) -> bool:
    """Whether a tool's declared policy contradicts what it says it does.

    `always` and `conditional` are both decisions: ask every time, or let the
    autonomy ladder decide. `never` is not a decision — a tool's author does not
    get to lower the tenant's ceiling, so a `never` on a tool that reaches
    outside would be read as `conditional` and silently mean nothing. That is how
    `conditional` and `never` came to be indistinguishable: one of them was being
    accepted and never read.

    So `never` keeps a meaning that IS read: a claim that this tool cannot do
    anything a person would need to approve. The claim has to be true, and that
    is checkable — `none` or `internal` and nothing further out. A `never` on an
    external tool is a mislabelled tool, refused here rather than quietly
    downgraded to the ladder.

    One function because two models enforce it: the spec a context writes, and
    the definition the executor runs.
    """
    return approval_policy == "never" and side_effect_level not in _NEVER_IS_HONEST_FOR


class WorkerDefinition(BaseModel):
    """Immutable description of a deployable Digital Worker."""

    model_config = ConfigDict(frozen=True)

    worker_id: str
    worker_version: str = Field(pattern=_RUN_VERSION_PATTERN)
    domain: str = Field(pattern=_SLUG_PATTERN)
    graph_version: str = Field(pattern=_RUN_VERSION_PATTERN)
    prompt_bundle_version: str = Field(pattern=_SEMVER_PATTERN)
    # None only for a worker that calls no tool at all (a plain graph, not an
    # agent loop) — never a placeholder for one that does. `platform.worker_
    # runs.toolset_version` is nullable for the identical reason (migration
    # 0005): inventing a version for something that was not there is worse
    # than admitting it was not. A worker that returns a value here still
    # owes the release manifest a real, resolvable `Toolset`
    # (`test_manifest_contains_every_required_section`) — this does not
    # relax that for anything that actually offers a tool.
    toolset_version: str | None = Field(default=None, pattern=_SEMVER_PATTERN)
    policy_version: str = Field(pattern=_SEMVER_PATTERN)
    memory_policy_version: str = Field(pattern=_SEMVER_PATTERN)
    default_model_profile: str
    supported_channels: frozenset[str]
    autonomy_level: AutonomyLevel
    # deepagents compiles with recursion_limit=9999; a runaway turn would burn
    # that whole budget before LangGraph stopped it.
    recursion_limit: int = Field(default=50, gt=0, le=500)
    # The registry prompt an agent-loop worker's system message is rendered
    # from (`AgentSpec.prompt_id`/`prompt_version`), and the pin the runner
    # records the loop's spend under. None for a plain graph, which has no loop
    # prompt - never a placeholder version for one that does.
    agent_prompt_id: str | None = None
    agent_prompt_version: str | None = Field(default=None, pattern=_SEMVER_PATTERN)

    @model_validator(mode="after")
    def _agent_prompt_is_one_pin(self) -> WorkerDefinition:
        if (self.agent_prompt_id is None) != (self.agent_prompt_version is None):
            raise ValueError("agent_prompt_id and agent_prompt_version are set together")
        return self

    @field_validator("worker_id", "default_model_profile")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class DeclaredLimits(BaseModel):
    """The behavioural limits a version declares for one run of it
    (usage-and-limits R6.4; ADR-0121 decision 4): read from what the run
    pinned, clamped by the plan where the run is admitted and resumed into
    `RunLimits`. A field the version does not declare is `None`, and the
    plan's ceiling holds for it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_steps: int | None = Field(default=None, ge=1)
    max_model_calls: int | None = Field(default=None, ge=1)
    max_tool_calls: int | None = Field(default=None, ge=1)
    max_cost_usd: Decimal | None = Field(default=None, gt=0)
    max_tokens: int | None = Field(default=None, ge=1)


class RunContext(BaseModel):
    """Per-run trusted context, created at the boundary and passed explicitly."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    # Unset means the run is its own thread; conversations pass a shared one.
    thread_id: UUID | None = None
    tenant_id: UUID
    workspace_id: UUID
    actor_id: UUID
    # Who asked for the run when that is not `actor_id`: a lane starting a
    # Digital Worker's run on its own stands as itself, `system_actor(<lane>)`
    # (digital-worker R1.4, ADR 0011). Unset: the actor asked.
    requested_by: UUID | None = None
    # The service principal the run acts as (ADR-0103 decision 4, ADR-0113
    # decision 1). The tool executor reads a DW's boundary by it (R6).
    run_as_principal_id: UUID | None = None
    # The sha256 of the workflow document a wf-lite run started from, pinned on
    # its run row (wf-lite R6.14, ADR-0109); None for a run of a code graph.
    definition_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    # The run manifest a Studio run pinned (`platform.worker_runs.
    # run_manifest_hash`, ADR-0109 decision 7); None for any other run. Such a
    # run resolves a tool only from what it pinned: `ToolExecutor` refuses one
    # it is not handed (tools-and-skills R4.1; DO-05). Set where a Studio run
    # is taken and resumed (agent-builder/03).
    run_manifest_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    # The Studio component the run runs (`platform.worker_runs.artifact_id`),
    # read from its row where a Studio run is taken and resumed; None for any
    # other run. `RunControlPort` asks about its kill at every door, so no
    # door has to name it (agent-lifecycle R8.1, R8.5).
    artifact_id: UUID | None = None
    worker_id: str
    worker_version: str = Field(pattern=_RUN_VERSION_PATTERN)
    channel: str
    plan_id: str
    roles: frozenset[str]
    scopes: frozenset[str]
    # How far up the classification ladder this run may read. Retrieval derives
    # its allowed classifications from it, so a run that does not carry it reads
    # nothing above "internal" - the default is the narrowest value on purpose,
    # so a construction site that forgets it under-retrieves instead of leaking.
    clearance: str = "internal"
    # The record-visibility roll-up (ADR-003), carried through so a run's CRM
    # reads narrow to the same owner subtree the REST endpoints do. Dropping
    # these silently defaulted every run to "open"/no-limit, so a chat run in a
    # restricted tenant read the whole workspace's records — the roll-up the
    # direct API enforces for the same user. Narrowest-safe defaults: an "open"
    # run with no visible set behaves as before for system/background runs.
    record_visibility: str = "open"
    visible_owners: frozenset[UUID] | None = None
    trace_id: str
    locale: str = "vi-VN"
    # The record this run is about, for surfaces that watch one of them. A page
    # showing a lead has to learn that a run touching THAT lead started or
    # finished, and it cannot learn it from a run id it has never seen. Left
    # unset by runs that are not about a single record - a conversation turn is
    # its own subject and needs no second name.
    subject_ref: str | None = None
    # The most autonomy the tenant allows, carried in from AccessContext by the
    # boundary that builds this context. Narrowest by default, same reasoning as
    # `clearance`: a construction site that forgets it gets a run that asks about
    # everything — loud in the first test — instead of one that quietly ignores
    # the ceiling a customer set.
    autonomy_ceiling: AutonomyLevel = FAIL_CLOSED_LEVEL
    # The mode the run runs in, set by the server where a run starts and read
    # back from the run row where it resumes (tenant-config R4, ADR-0111).
    # `simulate` by default, the closed value, as `autonomy_ceiling` is: a
    # construction site that forgets it gets a run whose tools are answered by
    # samples, loud in the first test, instead of one that acts on the world.
    run_mode: RunMode = "simulate"
    # The level this run actually runs at, and the policy version that turns it
    # into decisions. Set by the runner when the run starts — the lower of the
    # worker's declared level and the ceiling above — stamped on the run row,
    # and replayed from that row on resume. None means the run never went
    # through the runner, and the policy treats that as ask-everything.
    autonomy_level: AutonomyLevel | None = None
    approval_policy_version: str | None = None
    # The strictest data route class of the tenant, the workspace and the
    # version, pinned where the run is admitted and read back from the run row
    # where it resumes (compliance-pdpl R2.1; ADR-0123 decisions 3, 6). Every
    # model door's `ResidencyGate` reads it. `vn_only` by default, the narrowest
    # value, as `clearance` is: a construction site that forgets it sends to
    # Vietnamese routes only, never abroad.
    route_class: RouteClass = "vn_only"
    # The root of the run's tree (`platform.worker_runs.root_run_id`), whose
    # one lease every run of the tree spends against (usage-and-limits R5.6;
    # ADR-0113 decision 9). None: the run is its own root.
    root_run_id: UUID | None = None
    # The gate run an attempt of a gate or a trial gate belongs to
    # (agent-lifecycle R4.4, R4.8): the attempt spends against that gate run's
    # `eval_offline` lease, never admits one of its own. Set by
    # agent-lifecycle/06; None for every other run.
    gate_run_id: UUID | None = None
    # The attempt's own spend ceiling inside its gate run's lease
    # (agent-lifecycle R4.5): `before_call` clamps by what is left of it. None:
    # no ceiling beyond the lease's.
    cost_ceiling_usd: Decimal | None = Field(default=None, ge=0)
    # What the version this run runs declares of its behavioural limits, from
    # what the run pinned, set where the run is taken and resumed; `LimitsPort`
    # clamps it by the plan at each `admit` and `resume` (usage-and-limits
    # R6.4). Empty, the plan's ceilings hold: no version declares any in W1
    # until workflow-engine's document `limits` and agent-builder's W2
    # section set it.
    declared_limits: DeclaredLimits = Field(default_factory=DeclaredLimits)

    @property
    def lease_root(self) -> UUID:
        """Whose lease this run's model calls spend: its gate run's, else its
        tree's root, else its own (usage-and-limits R5.6)."""
        return self.gate_run_id or self.root_run_id or self.run_id


class MessageSpec(BaseModel):
    """What a tool that sends a message declares (compliance-pdpl R3.2,
    CP28): its channel, and every field of its input that holds an address
    (to, cc, bcc). The ToolExecutor sends it through the Send floor of
    ADR-0124, one address per call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: Literal["zns", "email", "sms", "messenger", "zalo_oa"]
    recipient_fields: tuple[str, ...] = Field(min_length=1)


class ToolResponse(BaseModel):
    """What of a tool's output reaches the model (ADR-0116 decision 5,
    tools-and-skills R5.1): the parts `fields` points at, the whole output
    when empty, cut at `max_output_chars`. Read by `contain_tool_output`
    alone."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fields: tuple[str, ...] = Field(default=(), max_length=50)
    max_output_chars: int = Field(default=DEFAULT_MAX_OUTPUT_CHARS, ge=1, le=MAX_OUTPUT_BYTES)

    @field_validator("fields")
    @classmethod
    def _pointers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for pointer in value:
            if not pointer or re.fullmatch(_JSON_POINTER_PATTERN, pointer) is None:
                raise ValueError("each response field is a non-empty JSON Pointer")
        if len(set(value)) != len(value):
            raise ValueError("a response field is named twice")
        return value


class ToolDefinition(BaseModel):
    """Versioned tool contract enforced by the tool executor."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: str = Field(pattern=_SEMVER_PATTERN)
    description: str
    input_schema_ref: str
    output_schema_ref: str
    required_scopes: frozenset[str]
    side_effect_level: SideEffectLevel
    approval_policy: ApprovalPolicy
    timeout_seconds: int = Field(gt=0, le=600)
    max_retries: int = Field(ge=0, le=10)
    idempotent: bool
    data_classification: frozenset[str]
    # Set for a tool that sends a message; its spec must say either way.
    message: MessageSpec | None = None
    # Whether the tool runs for real outside `live` (tenant-config R5.4): only
    # a tool with no effect, so the default is no and a definition that does
    # not say is intercepted (R5.5).
    simulate_safe: bool = False
    # What of the output the model reads, for a tool the Studio assembler
    # builds (tools-and-skills R5.1); a code-defined worker's tool keeps its
    # whole output (spec, Out of scope).
    response: ToolResponse = ToolResponse()

    @field_validator("name")
    @classmethod
    def _tool_name_is_namespaced(cls, value: str) -> str:
        if "." not in value or value.startswith(".") or value.endswith("."):
            raise ValueError("tool name must be namespaced like 'task.prepare'")
        return value

    @model_validator(mode="after")
    def _never_only_where_it_is_true(self) -> ToolDefinition:
        if approval_policy_disagrees_with_side_effect(
            approval_policy=self.approval_policy,
            side_effect_level=self.side_effect_level,
        ):
            raise ValueError(
                f"approval_policy 'never' claims this tool needs no person, but "
                f"side_effect_level is '{self.side_effect_level}'. Use "
                f"'conditional' to let the autonomy level decide, or 'always' to "
                f"ask every time."
            )
        return self

    def intercepted_in(self, run_mode: RunMode) -> bool:
        """Whether a call of this tool in a run of `run_mode` is answered by a
        sample instead of running (tenant-config R5.1): any mode but `live`,
        unless the tool is `simulate_safe`. The one answer the executor, the
        agent's tool wrapper and its approval middleware all read, so a call
        intercepted at the executor never opens an approval first (R5.6)."""
        return run_mode != "live" and not self.simulate_safe

    def always_requires_approval(self) -> bool:
        """Whether this tool asks for a person at EVERY autonomy level.

        The two floors, and only them: declared `always`, or a `critical` side
        effect. It used to be named `requires_approval` and to be the whole
        decision, which is how a worker's autonomy level came to be read by
        nothing. Whether a given call asks depends on the run — use
        `AutonomyApprovalPolicy.decide`. This answers only what is true of the tool
        regardless of who runs it, which is what an inventory screen can know.
        """
        return self.approval_policy == "always" or self.side_effect_level == "critical"
