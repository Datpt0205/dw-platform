---
status: Proposed (direction chosen by the requester on 2026-10-22 and 2026-10-23; not yet reviewed by Đạt)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/agent-builder/spec.md
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/agent_factory.py
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/sub_agents.py
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/model/prompts.py
    - ../../db/migrations/versions/855ae928c3fa_platform_in_app_notifications.py
---

# 0117. An agent is a form-configured dw.agent/v1 document compiled per version inside the existing runner, and agents and workflows join only through the Agent node and workflow-as-tool

Numbered in the block 0100-0199 reserved for Studio (ADR-0100 records the block). It rests on requester
decision D2 (2026-10-22): builders are business admins working without code, through forms, simple
expressions, domain packs and builder assistance. It builds on ADR-0109 (the envelope and the run
manifest), ADR-0103 (a run acts as a principal within a boundary) and ADR-0113 (one run request door).
The `agent-builder` spec owns it.

## Context

Paths are under `packages/python/dw_agent_runtime/src/dw_agent_runtime/` unless they start at the
repository root. External facts were gathered by the Studio research on 2026-10-22, not re-verified here.

- The runtime hosts only code-defined workers: `GraphRegistry` keys a graph by
  `(worker_id, graph_version)` with no tenant (`registry.py:28-47`), the compile cache `_compiled` has
  the same key and never evicts (`adapters/langgraph_runner.py:127`), and `hosts()` answers only for
  registered graphs (`adapters/langgraph_runner.py:172-178`). A tenant's agent cannot be registered in
  Python per version.
- Agents are built on `create_agent`, never `create_deep_agent`, whose builtin tools reach outside the
  `ToolExecutor` (`adapters/agent_factory.py:28-36`). A sub-agent may only narrow its parent's tools
  (`adapters/sub_agents.py:95-101`), and the parent's middleware does not wrap the child's model call
  (`adapters/sub_agents.py:15-21`).
- ADR-0010 contains every interpolated prompt value (`contain_untrusted`, `model/prompts.py:35`);
  instructions are free text, and as a text template they could address what the platform renders.
- Nothing stores conversations. Run rows carry `input` and `result`
  (`db/migrations/sql/0001_platform_baseline.sql:455-456`) that every run reader sees, and
  `platform.feedback` (`:230-241`) is a bug inbox. The precedent for a table private to one person is
  `platform.notifications` (`db/migrations/versions/855ae928c3fa_platform_in_app_notifications.py:15-18`).
- The market separates processes from agents: OpenAI shuts its Agent Builder canvas on 2026-11-30
  (https://developers.openai.com/api/docs/deprecations); the Flowise agent canvas was archived on
  2026-08-13 (https://github.com/FlowiseAI/Flowise/discussions/6727); Copilot Studio split
  deterministic workflows from goal-seeking harnesses
  (https://learn.microsoft.com/en-us/microsoft-copilot-studio/harnesses-overview, 2026-10-19).

## Decision

1. **Two kinds of automation.** Deterministic workflows are drawn on the canvas (`dw.workflow/v1`,
   ADR-0112); agents are configured by forms; there is no agent canvas. They join only through the
   `ai.agent` node in a workflow (outputs `response`, `tool_calls`, `document_refs`, `metadata` and an
   error port) and through a published workflow exposed to agents as a workflow tool. A child run
   carries the root run's id, and its limits and run mode may only become safer (ADR-0113).
2. **An agent is a document.** Kind `agent` registers in `ArtifactKindRegistry` (ADR-0109): schema
   `dw.agent/v1` with `extra="forbid"`, an all-errors validator and a pure dependency extractor.
   Sections: `display`, `instructions`, `model.profile`, `toolset` (connections by binding name,
   ADR-0110), `knowledge`, `links`, `sub_agents`, `field_caps`, `limits` (steps, model calls, tool calls,
   seconds, and `max_cost_usd` as a decimal string, clamped by `platform.plan_limits`),
   `delegation.ask_before` and `route_class` (both tighten-only), `conversation`, `surfaces` (a subset
   of `chat`, `workflow_node`, `link`), `output_schema`, `ai_risk_tier`, `purpose`. There is no
   `studio.agent_versions` table.
3. **Settings beside the versions.** `studio.agent_settings` (tenant-only RLS like the envelope):
   `artifact_id` (composite FK to `studio.artifacts`, `ON DELETE CASCADE`), `audience` jsonb
   (`dw.audience/v1`, ADR-0102), `owner_user_id` (the accountable owner under ADR-0103's column
   contract), `enabled boolean NOT NULL` with no default, `row_version`. A change is audited as
   `studio.agent.settings_changed` and makes no version: who may invoke an agent is not what it does.
   The data boundary is derived at publish from the toolset's object tools (object, action) and
   `field_caps` into `studio.actor_boundaries` (ADR-0103, ADR-0105). agent-builder registers
   `studio.agent.read`, `studio.agent.author` and `studio.agent.settings.manage`; submit, approve,
   retire, kill and freeze stay with ADR-0120.
4. **Instructions are linted text inside a platform frame, never a text template.** The system
   message is the frame prompt `studio.agent_frame@1.0.0` (under `configs/prompts/studio/`, rendered by
   `PromptRegistry`, every value contained per ADR-0010; only the code-built `current_date` and
   `current_time` are `raw_variables`, with a reason), then a `<tenant_instructions>` block holding the
   tenant's text verbatim, escaped so it cannot close its block. Platform variables are a closed set of
   chips (`current_date`, `current_time`, `user_display_name`, `workspace_name`, `agent_name`, `locale`)
   rendered in the frame only. The validator, at save and publish, reports every error at once: at most
   16,000 characters, NFC, no C0 control but newline and tab, `{{` or `{name}`-shaped text refused as
   `instructions.template_syntax`, the delimiters `<tenant_instructions`, `<input` and `<tool_output`
   refused; sub-agents obey the same rules. One assembler, `assemble_system_prompt`, beside
   `contain_untrusted`, serves agents and workflow AI nodes.
5. **Compiled per version inside the existing runner, in the worker.** A `StudioGraphSource` beside
   `GraphRegistry` answers `hosts()` for any `RunContext.artifact` of kind `agent`. A version compiles
   per `(tenant_id, agent_version_id)` into an LRU of at most 256 entries (CLAUDE.md:198), loads under
   RLS, and is refused when its stored `definition_hash` differs from a recomputed one. It is assembled
   on the platform's `create_agent` stack: pinned tools (ADR-0116), run control (ADR-0120),
   `StudioModelSelection` outermost, then limits and the run budget (ADR-0121), one approval per step,
   tool errors, model retry and compaction. The model is chosen per call from the route pinned in the
   run manifest (ADR-0118), through a client keyed `(tenant_id, route, secret_version)`; the compiled
   graph holds no credential. Every run is requested through `RunRequestService` (ADR-0113) with
   `trigger_kind` `chat`, `agent_node`, `agent_link` or `eval`; the API never executes an agent inline.
   Tool approvals use the non-strict prefix `studio.agent.tool.`, so the invoker may approve their own
   ask-before step. `RunContext` gains `artifact`, `run_mode` (ADR-0111) and `route_class` (ADR-0123);
   the tool session binds `app.actor_kind = 'agent'` and `app.boundary_id`.
6. **Conversation content has one store, private to its owner.** `studio.conversations`
   (`workspace_id`, `agent_artifact_id`, `owner_user_id`, `status` CHECK (`active`, `archived`) with no
   default, `active_run_id`) and `studio.conversation_messages` (`seq`, `role` CHECK (`user`,
   `assistant`, `notice`, `summary`), capped `content`, `run_id`, `agent_version_id`, `citations`,
   `activity` naming tools and workflows, never arguments). RLS: the workspace shape of
   CLAUDE.md:172-177 as the PERMISSIVE policy plus a RESTRICTIVE policy
   `owner_user_id = NULLIF(current_setting('app.user_id', true), '')::uuid OR current_setting('app.workspace_scope', true) = 'tenant'`,
   so an unset user reads nothing and only the offboarding lane reads past the owner. Run rows hold ids
   only. One run per conversation turn, claimed on `active_run_id`, else 409 `conversation_busy`.
   Citation markers (`[[rec:<id>]]`, `[[doc:<evidence_id>]]`) are checked against the evidence the turn
   recorded and an unmatched one is dropped and counted. Feedback goes to `studio.message_feedback`
   (`up` or `down` with a `reason_code`), read by the quality panel and online evaluation sampling.
7. **A linked agent is a child run; an agent with links orchestrates.** Each link becomes a platform
   tool `ask__<api_name>` (kind `builtin`) run by the `ToolExecutor`: it requests a child run of the
   linked version pinned in the root run manifest, parks the parent on a `child_run` wait, and resumes
   it with the answer wrapped as untrusted output. The child keeps its own toolset and boundary, acts
   for the root's user, shares the root's lease, runs at chain depth at most 3 and never less safe in
   run mode; taint flows both ways. Publish refuses a cycle in `studio.dependencies` and a link to an
   agent without the `link` surface. An in-process sub-agent names a subset of its parent's tools, its
   own stack carrying run control, `StudioModelSelection` and the budget. An agent with `links` pins
   only tools of side-effect level `none` or `read` plus workflow tools (`links.effect_tool_on_router`).

## Alternatives considered

- **An agent canvas.** Rejected: two ways to express control flow for business builders, and graph
  agents blur where effects happen.
- **Tenant instructions as a text template.** Rejected: template injection; ADR-0010 would not hold.
- **Conversations visible to workspace admins.** Rejected: a person's conversation is theirs under the
  PDPL (Law 91/2025/QH15); an audited export with notice to the person comes later.
- **Deep agents with builtins.** Rejected under stance S8; see ADR-0116.
- **Audience inside the version.** Rejected: changing who may use an agent would need a quality gate
  and a second approver for no safety gain.
- **One LangGraph thread per conversation, or content in `worker_runs.result`.** Rejected: two copies
  of one transcript, a checkpoint growing with every step, and run readers reading private content.
- **A linked agent as a subgraph of its parent.** Rejected: one run, inside the parent's boundary.

## Consequences

- agent-builder owns `studio.agent_settings`, the agents' rows in `studio.actor_boundaries` (the table
  is record-access's, ADR-0105), the frame prompt and the conversation store. ModelResolver (ADR-0118)
  and freezes (ADR-0120) reach every model call, sub-agents included, through middleware.
- Migrations: revisions for `studio.agent_settings`, `studio.conversations`,
  `studio.conversation_messages` and `studio.message_feedback`, RLS forced, grants in the same revision.
- Tests that must exist, each shown red with its guard removed: a second person in the same workspace
  reads none of another's conversation; a transaction with no `app.user_id` reads nothing; text holding
  `{{`, `{name}` or `</tenant_instructions>` is refused or contained; a compiled version is never served
  to another tenant; an agent with links pinning a write tool is refused at publish; a killed linked
  agent is refused inside its running parent.
- P1 polls instead of streaming tokens (docs/adr/0008-chat-updates-poll-locally-webhook-when-hosted.md
  is the precedent); P2 relays events over an ephemeral Valkey channel, the transcript staying the truth
  (CLAUDE.md:60). The first use of a version pays its compile (agent-builder 01, FOG-36).
- Harder: no tenant role reads a person's conversation to investigate a complaint in v1; every link
  call pays queue latency; a tenant cannot change the frame; a conversation retention term is owed.

### Contradictions and amendments

- Reinforces CLAUDE.md:50 ("never a super-agent").
- _Contradicts CLAUDE.md:172-177 (`app.workspace_scope` read only inside `tenant AND (workspace OR scope)`,
  enforced by `packages/python/dw_platform/tests/integration/test_rls_coverage.py:427-433`), worth
  reopening because a conversation is narrowed to its owner while offboarding must still export it: the
  owner policy is a second shape, the test learns it, and CLAUDE.md is amended with it._
- _Contradicts CLAUDE.md:181-184 (every versioned prompt resolves through `TenantOverlay`), worth
  reopening because the frame is the containment: `studio.agent_frame` resolves at the platform layer
  only, the question ADR-0110 already asks about tenant overrides of platform prompts._
- `configs/workers/README.md:14-17` is stale on autonomy and is corrected by foundations-hardening.
- si-platform: re-derived; si-platform has one platform agent and no tenant agents.

## Open

1. **DO-44** (Đạt with the requester; counsel for conversations): may any tenant role read other
   people's conversations (O5)? Recommended: none in v1, an audited export with a reason and a notice
   to the person in v1.5; and `chat` runs in the worker with polling in P1 (O4). Blocks agent-builder 04.
2. Owned elsewhere, read here: DO-05 (Đạt: versions in the one envelope, ADR-0109); DO-40 (Đạt and
   the requester: the audience as a typed condition list); DO-30, a provisional call by the agent on
   2026-10-23 following the recommendation (linked versions pinned at submit, drift proposes the
   update; if overturned, links follow the live version).
