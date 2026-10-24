---
status: Accepted (Đạt, 2026-10-23; amendments from the decision brief applied)
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
3. **Settings beside the versions.** `studio.agent_settings` (tenant-only RLS like the envelope, and
   listed as tenant-wide with that reason under amendment A6, ADR-0100):
   `artifact_id` (composite FK to `studio.artifacts`, `ON DELETE CASCADE`), `audience` jsonb
   (`dw.audience/v1`, ADR-0102), `owner_user_id` (the accountable owner under ADR-0103's column
   contract), `enabled boolean NOT NULL` with no default, `row_version`. A change is audited as
   `studio.agent.settings_changed` and makes no version: who may invoke an agent is not what it does.
   The data boundary is derived at publish from the toolset's object tools (object, action) and
   `field_caps`, and the `agent` kind's publish hook (ADR-0109 decision 1), which agent-builder
   supplies, writes it into `studio.actor_boundaries` (ADR-0103, ADR-0105) through record-access's
   `ActorBoundaryPort`, inside the publish transaction that agent-lifecycle opens. The same derivation
   gives a draft that roots a `simulate` run, agent-lifecycle's dry evaluation of a draft among them,
   its provisional boundary at the run door (ADR-0103 decision 5), which no `live` run reads under.
   agent-builder registers `studio.agents.read`, `studio.agents.author` and
   `studio.agents.manage_settings`; submit, approve, retire, kill and freeze stay with ADR-0120.
4. **Instructions are linted text inside a platform frame, never a text template.** The system
   message is the frame prompt `studio.agent_frame@1.0.0` (under `configs/prompts/studio/`, rendered by
   `PromptRegistry`, every value contained per ADR-0010; only the code-built `current_date` and
   `current_time` are `raw_variables`, with a reason), then a `<tenant_instructions>` block holding the
   tenant's text verbatim, escaped so it cannot close its block. Platform variables are a closed set of
   chips (`current_date`, `current_time`, `user_display_name`, `workspace_name`, `agent_name`, `locale`)
   rendered in the frame only. The validator, at save and submit, reports every error at once: at most
   16,000 characters, NFC, no C0 control but newline and tab, `{{` or `{name}`-shaped text refused as
   `instructions.template_syntax`, the delimiters `<tenant_instructions`, `<input` and `<tool_output`
   refused; sub-agents obey the same rules. One assembler, `assemble_system_prompt`, beside
   `contain_untrusted`, serves agents and workflow AI nodes.
5. **Compiled per version inside the existing runner, in the worker.** A `StudioGraphSource` beside
   `GraphRegistry` answers `hosts()` for any `RunContext.artifact` of kind `agent`. A sealed version, and a
   draft only as the root of a `simulate` run (ADR-0109 decision 6), compiles per
   `(tenant_id, agent_version_id, pinned_hash)` into an LRU of at most 256 entries, keyed by tenant from the
   start (`CLAUDE.md`, Per-tenant artifacts), `pinned_hash` being the hash the run manifest pins: a sealed
   version's `definition_hash`, or the provisional hash of a draft's content. A draft keeps its id while it
   is edited and a run resolves only from its manifest (`CLAUDE.md`, Non-negotiable architecture), so a key
   without the hash would hand a new simulation the graph of older content. A version loads under RLS and is
   refused when the hash recomputed from what it loaded differs from `pinned_hash`. It is assembled
   on the platform's `create_agent` stack: pinned tools (ADR-0116), run control (ADR-0120),
   `StudioModelSelection` outermost, then `ResidencyGate` (ADR-0123), then limits and the run budget
   (`LimitsMiddleware`, ADR-0121), one approval per step, tool errors, model retry and compaction;
   with the residency gate before the limits, a call it refuses holds no lease. The model is chosen
   per call from the route pinned in the run manifest (ADR-0118), through a client keyed
   `(tenant_id, route, secret_version)`; the compiled graph holds no credential. Every run is
   requested through `RunRequestService` (ADR-0113) with `trigger_kind` `chat`, `agent_node`,
   `agent_link` or `eval`; the API never executes an agent inline. Tool approvals use the non-strict
   prefix `studio.agent.tool.`, so the invoker may approve their own ask-before step. `RunContext`
   gains `artifact`, `run_mode` (ADR-0111) and `route_class` (ADR-0123); the tool session binds
   `app.actor_kind = 'agent'` and `app.boundary_id`.
6. **Conversation content has one store, private to its owner.** `studio.conversations`
   (`workspace_id`, `agent_artifact_id`, `owner_user_id`, `status` CHECK (`active`, `archived`) with no
   default, `active_run_id`) and `studio.conversation_messages` (`seq`, `role` CHECK (`user`,
   `assistant`, `notice`, `summary`), `content` capped at 16 KiB (16,384 bytes of UTF-8, CHECK
   `octet_length(content) <= 16384`; a longer message is answered 422 `validation_failed` pointing at
   `content`), `reason_code` (CHECK over agent-builder's codes) and `resets_at`, both NULL unless `role`
   is `notice` (CHECK), so a notice carries its code and its reset time beside `content`, never inside it,
   `run_id`, `agent_version_id`, `citations` (W2), `activity` naming tools and workflows, never
   arguments). A model reply longer than the cap has no request to answer, so it is stored cut
   to its first 16,384 bytes at a UTF-8 character boundary and followed by a `notice` message with
   `reason_code` `reply_truncated`; the chat agent's output-token cap is set so a reply normally fits.
   A message carries its conversation's `workspace_id` and `owner_user_id` through a composite foreign
   key, `ON DELETE RESTRICT`, so the two copies cannot differ and no `dw_app` delete of a conversation
   removes its append-only messages (ADR-0122 decision 7 removes expired ones).
   Messages are range-partitioned by month with a DEFAULT partition, registered by one row in
   `platform.time_partitioned_tables`, and no partition grants `dw_app` anything, so a partition read
   by name shows nobody's messages (DO-02.2). RLS: the workspace shape of CLAUDE.md:198-207 as the
   PERMISSIVE policy plus a RESTRICTIVE policy of the form `tenant AND (owner OR scope)`,
   `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid AND (owner_user_id = NULLIF(current_setting('app.user_id', true), '')::uuid OR current_setting('app.workspace_scope', true) = 'tenant')`,
   so an unset user reads nothing and only a lane listed in the registry of `tenant_wide_scope()` (in
   W1, offboarding) reads past the owner. Every lane added to that registry reads every person's
   conversations, so its entry says whether it needs to and is reviewed as opening them (DO-13.1). No
   tenant role reads another person's conversation (DO-44). From W2, if counsel holds that a data
   subject's request covers conversation content, the data protection officer's audited lane retrieves
   the messages concerning that data subject through a SECURITY DEFINER function that returns content
   by data subject, audits the call, notifies the person whose conversation it reads, and never sets
   `app.workspace_scope` (DO-44.2 (c)). Run rows hold ids only. One run per conversation turn, claimed
   on `active_run_id`, else 409 `conversation_busy`. From W2, with citations (YC56), citation markers
   (`[[rec:<id>]]`, `[[doc:<evidence_id>]]`) are checked against the evidence the turn recorded and an
   unmatched one is dropped and counted, and feedback goes to `studio.message_feedback` (`up` or
   `down` with a `reason_code`), read by the quality panel and online evaluation sampling.
7. **A linked agent is a child run; an agent with links orchestrates.** Each link becomes a platform
   tool `ask__<api_name>` (kind `builtin`) run by the `ToolExecutor`: it requests a child run of the
   linked version pinned in the root run manifest, parks the parent on a `child_run` wait, and resumes
   it with the answer wrapped as untrusted output. The child keeps its own toolset and boundary, acts
   for the root's user, shares the root's lease, runs at chain depth at most 3 and never less safe in
   run mode; taint flows both ways. Submit refuses a cycle in `studio.dependencies` (ADR-0113
   decision 9) and a link to an agent without the `link` surface. An in-process sub-agent names a
   subset of its parent's tools, its own stack carrying run control, `StudioModelSelection`,
   `ResidencyGate` and the budget in decision 5's order. An agent with `links` pins only tools of
   side-effect level `none` or `read` plus workflow tools (`links.effect_tool_on_router`).

## Alternatives considered

- **An agent canvas.** Rejected: two ways to express control flow for business builders, and graph
  agents blur where effects happen.
- **Tenant instructions as a text template.** Rejected: template injection; ADR-0010 would not hold.
- **Conversations visible to workspace admins.** Rejected: a person's conversation is theirs under the
  PDPL (Law 91/2025/QH15); from W2 only decision 6's audited data-subject lane reads one, if counsel
  requires it.
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
- Migrations: revisions for `studio.agent_settings`, `studio.conversations` and
  `studio.conversation_messages`, and in W2 `studio.message_feedback`, RLS forced, grants in the same
  revision.
- Tests that must exist, each shown red with its guard removed: a second person in the same workspace
  reads none of another's conversation; a transaction with no `app.user_id` reads nothing; a partition
  of `studio.conversation_messages` read by name returns nothing to `dw_app`; text holding
  `{{`, `{name}` or `</tenant_instructions>` is refused or contained; a compiled version is never served
  to another tenant; an agent with links pinning a write tool is refused at submit; a killed linked
  agent is refused inside its running parent.
- P1 polls instead of streaming tokens (docs/adr/0008-chat-updates-poll-locally-webhook-when-hosted.md
  is the precedent); P2 relays events over an ephemeral Valkey channel, the transcript staying the truth
  (CLAUDE.md:64). The first use of a version pays its compile (agent-builder 01, FOG-36).
- Harder: no tenant role reads a person's conversation to investigate a complaint in v1; every link
  call pays queue latency; a tenant cannot change the frame; conversations are kept 90 days, a
  provisional UNVERIFIED term in the retention policy until counsel confirms it (DO-52, ADR-0122).

### Contradictions and amendments

- Reinforces CLAUDE.md:54 ("never a super-agent").
- _Contradicts CLAUDE.md:198-207 (`app.workspace_scope` read only inside `tenant AND (workspace OR scope)`,
  enforced by `packages/python/dw_platform/tests/integration/test_rls_coverage.py:427-433`), worth
  reopening because a conversation is narrowed to its owner while offboarding must still export it. The
  owner policy keeps the tenant clause beside the scope, `tenant AND (owner OR scope)`, so the test that
  holds the scope beside a pure tenant clause passes it as written; CLAUDE.md is amended to name the
  owner form beside the workspace form._
- _Contradicts CLAUDE.md:213-216 (every versioned prompt resolves through `TenantOverlay`), worth
  reopening because the frame is the containment: `studio.agent_frame` resolves at the platform layer
  only, the question ADR-0110 already asks about tenant overrides of platform prompts._
- `configs/workers/README.md:14-17` is stale on autonomy and is corrected by foundations-hardening.
- si-platform: re-derived; si-platform has one platform agent and no tenant agents.

## Open

1. **DO-44** (Đạt with the requester; counsel for conversations): may any tenant role read other
   people's conversations (O5)? Recommended: none in v1, an audited export with a reason and a notice
   to the person in v1.5; and `chat` runs in the worker with polling in P1 (O4). Blocks agent-builder 04.
   Answered 2026-10-23, the line Đạt confirmed in agent-builder's spec: `chat` runs in the worker,
   polling in P1 and server-sent events over an ephemeral Valkey relay in P2 (DO-44.1 (a)); no tenant
   role reads another person's conversation, and from W2 decision 6's audited data-subject lane may
   (DO-44.2 (c)). Still with counsel: whether a data subject's request covers conversation content; if
   it does not, no lane is added.
2. Owned elsewhere, read here: DO-05 (Đạt: versions in the one envelope, ADR-0109); DO-40 (Đạt and
   the requester: the audience as a typed condition list); DO-30, a provisional call by the agent on
   2026-10-23 following the recommendation (linked versions pinned at submit, drift proposes the
   update; if overturned, links follow the live version). Answered 2026-10-23: all three as stated
   (DO-05 (a), DO-40 (a), DO-30 (a)).

## Acceptance (2026-10-23)

Accepted by Đạt on 2026-10-23 with these amendments from the decision brief:

- Decision 6: a message carries `workspace_id` and `owner_user_id` from its conversation through a
  composite foreign key; messages are partitioned by month with a DEFAULT partition, registered by one
  row, and their partitions grant `dw_app` nothing (DO-02.2); the RESTRICTIVE policy gains its tenant
  clause, `tenant AND (owner OR scope)`, which the scope test requires (the CRITICAL on
  `agent-builder:R4.1`, option (a)); only a lane in the `tenant_wide_scope()` registry reads past the
  owner, at that stated cost (DO-13.1 (a)); no tenant role reads another's conversation, and from W2 an
  audited data-subject lane may, if counsel requires it (DO-44.2 (c)).
- Alternatives and Consequences: follow decision 6, with a test on partitions read by name; the
  conversation retention term is DO-52's to set.
- Contradictions: the owner policy passes the scope test as written; CLAUDE.md names the owner form.
- Open: DO-44 answered except counsel's part; DO-05, DO-40 and DO-30 answered.

## Amendments (2026-10-24)

Amended by Đạt on 2026-10-24, who accepted every recommendation the second consistency check left
open:

- Decision 3: permission keys name their area in the plural, `studio.<areas>.<verb>`, so
  agent-builder registers `studio.agents.read`, `studio.agents.author` and
  `studio.agents.manage_settings`; `studio.agent_settings` keeps `artifact_id`, `owner_user_id` and
  tenant-only RLS as decision 3 says, and joins the list of tenant-wide tables with its reason
  (F:ADR-0117~agent-builder:dữ-liệu).
- Consequences: conversations are kept 90 days, provisional and UNVERIFIED (DO-52).
- Third consistency check (round 4): the settings key is `studio.agents.manage_settings` in decision 3
  and above, since tenant-rbac's convention allows exactly three segments, `studio.<area>.<verb>`
  (V4.P10, the planner's provisional call, G:ADR-0117\~tenant-rbac:trong-phạm-vi; if it is wrong,
  tenant-rbac admits four segments and the key keeps its earlier four-segment name); decision 6 caps
  `content` at 16 KiB with a CHECK and a 422, and places `citations`, the citation check and
  `studio.message_feedback` in W2 (Đạt's V4.13; F:ADR-0117\~agent-builder:spec); decision 7 refuses a
  cycle at submit, as ADR-0113 decision 9 now says (G:ADR-0112\~ADR-0113).
- Third consistency check (round 4), second pass, the planner's provisional calls: decision 5 places
  `ResidencyGate` right after `StudioModelSelection` and before `LimitsMiddleware`, and decision 7
  gives a sub-agent's own stack the same gate, so no model call passes around it; decisions 4 and 7
  and the tests check at submit, where the version is sealed and ADR-0116 decision 1 checks, no longer
  "at publish"; decision 6 gives the message foreign key `ON DELETE RESTRICT`, so no `dw_app` delete
  of a conversation removes its messages and expired ones leave through ADR-0122 decision 7's purge
  function (if it is wrong, the foreign key cascades and the messages stop being append-only), and
  stores a model reply over 16 KiB cut at a character boundary with a `reply_truncated` notice (if it
  is wrong, the turn ends `failed` with `reply_too_long`).
- Third consistency check (round 4), third pass, the planner's provisional call: decision 6 gives a
  message `reason_code` and `resets_at`, set only on a `notice` (CHECK), which the notice of a failed
  turn (with `limit_exceeded`, its `resets_at`) and the `reply_truncated` notice use, so no code travels
  inside `content` (if it is wrong, a notice's code and reset time are text in `content` that a reader
  parses).
- Third consistency check (round 4), fourth pass, the planner's provisional calls: decision 5 compiles an
  agent draft too, only as the root of a `simulate` run (ADR-0109 decision 6), agent-lifecycle's dry
  evaluation of a draft among them, as Đạt's V4.4 lets a workflow draft run, and keys the compiled-graph
  cache `(tenant_id, agent_version_id, pinned_hash)`, `pinned_hash` being the run manifest's
  `definition_hash` or the draft's provisional hash, as ADR-0112 decision 4 keys a workflow's, because a
  draft keeps its id while it is edited (if it is wrong, an agent draft runs nothing, dry evaluations take
  sealed versions only, and the key keeps the version id alone); decision 3 names who writes an agent's
  rows in `studio.actor_boundaries`, the `agent` kind's publish hook that agent-builder supplies, through
  record-access's `ActorBoundaryPort` in the publish transaction, as record-access states (if it is wrong,
  agent-lifecycle calls the port after the kind's hook).
- Third consistency check (round 4), sixth pass, Đạt's V4.19 and V4.22: Đạt confirms the settings key
  `studio.agents.manage_settings`, so the first round-4 line above records his decision, no longer the
  planner's provisional V4.P10, and its fallback to a four-segment name lapses; decision 3's derivation
  of the boundary also gives an agent draft that roots a `simulate` run its provisional boundary at the
  run door (ADR-0103 decision 5), never used by a `live` run.
