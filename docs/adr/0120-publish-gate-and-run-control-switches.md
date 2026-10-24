---
status: Accepted (Đạt, 2026-10-23; amendments from the decision brief applied)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/agent-lifecycle/spec.md
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py
    - ../../packages/python/dw_platform/src/dw_platform/domain/approval.py
    - ../../apps/api/src/dw_api/bootstrap/runtime.py
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py
    - ../../packages/python/dw_evals/src/dw_evals/dataset.py
---

# 0120. A version becomes live only through a database-guarded stage machine, a passing gate on its exact effective hash and a second person's approval, and kill and freeze are switches that every door checks

Numbered in the block 0100-0199 reserved for Studio (ADR-0100 records the block). It rests on requester decision D11
(2026-10-23): every publish of an agent or workflow version and every lift of a kill needs a maker and a different
checker; a tenant with one admin cannot publish, and sales must say Studio needs at least two admins. The mechanism is
agent-proposed under stance S13, and the freeze follows DO-28 (C), confirmed on 2026-10-23. It completes ADR-0109, whose
envelope leaves "which version runs" to this stage contract. The `agent-lifecycle` spec owns it.

## Context

- **Nothing of a lifecycle exists.** No table holds a stage, a gate result, a kill or a freeze. The tenant lock
  refuses only new access contexts (`apps/api/src/dw_api/routes/v1/platform.py:189-204`), and `cancel_thread`
  cancels only in the process holding the task (`dw_agent_runtime/adapters/langgraph_runner.py:371`), behind
  `runs.cancel` (`apps/api/src/dw_api/routes/v1/runs.py:107-135`), which no seeded role holds.
- **Two-person decisions already exist.** A strict approval type refuses its requester and demands a comment
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:115-130`), also on a rejection, so its
  requester cannot withdraw it through `decide` (`:226-227`); per-type `decision_guards` run before anything is written
  (`:228-230`), as memory review does (`apps/api/src/dw_api/bootstrap/runtime.py:237-239`); a run-less approval
  announces `<type>.decided` through the outbox (CLAUDE.md:274-279). `ApprovalRequest.cancel()` exists with no
  production caller (`packages/python/dw_platform/src/dw_platform/domain/approval.py:132`).
- **The gap.** The competitor teardown shows a Publish button on versions that failed evaluation: a gate in the UI
  only. Repeated trials (pass^k) and abstaining judges follow
  https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents (2026-01-09, cited by the research).

## Decision

1. **One stage machine, guarded by the database.** Stages `draft`, `evaluating`, `awaiting_approval`, `live` and
   `retired` live on `studio.artifact_versions` (ADR-0109): `stage` NOT NULL with a CHECK and no default, read back
   from `pg_constraint` against a `VersionStage` StrEnum; `definition_hash` required outside `draft`; `gate_run_id`
   and `publish_approval_id`, composite FKs `(tenant_id, gate_run_id)` to `studio.gate_runs` and
   `(tenant_id, publish_approval_id)` to `platform.approval_requests`, each to its target's `UNIQUE (tenant_id, id)`
   (added in the same revision where the target lacks it, since a foreign key check does not pass through RLS),
   ON DELETE RESTRICT and required from `awaiting_approval` on (a version published on the tighten-only branch below
   keeps `publish_approval_id` NULL),
   `gate_run_id` only for a kind with a quality gate; `contributor_ids` never empty. One trigger,
   `studio.guard_version_stage()`, allows only: insert as `draft`; `draft` to `evaluating`; `evaluating` back to
   `draft` (gate failed, errored, cancelled or withdrawn); `evaluating` to `awaiting_approval` (gate passed on this
   version's effective hash, approval pending); `awaiting_approval` back to `draft` (rejected, cancelled, expired, or
   approved after the live version changed, decision 2); `awaiting_approval` to `live` (approved by a decider who is
   neither submitter nor contributor, the gate's evidence still matching, and `compared_live_hash` still the hash of
   the live version this publish replaces, which the same transaction retires first, both NULL when it replaces
   none); `live` to `retired`. Its rule is per kind: a kind without a quality gate, an object definition (ADR-0107),
   a tool (ADR-0116, from W2, when the `tool` kind registers) or a Data Hub endpoint (ADR-0113 decision 6), goes from
   `draft` to `awaiting_approval` directly and needs only the second person. One branch serves a kind
   without a quality gate whose kind registers a tighten-only comparator, in v1 the object definition alone: a
   `dw.object/v1` version whose comparator reports that every change against the live version only tightens (a field
   closed, `default_access` narrowed, a permission removed) goes from `draft` to `live` at submit, by one person,
   audited (D11 as the requester and Đạt scoped it, closing with one person; ADR-0106 decision 2). `LifecycleService`
   records at every submit, of every kind, `compared_live_hash`, the `definition_hash` of the version live at submit
   (NULL while none is), and for a kind that registers a comparator its result in `tighten_only boolean`; the trigger
   allows `draft` to `live` only for a kind without a quality gate, with `tighten_only` true and `compared_live_hash`
   still the hash of the live version this publish replaces (retired in the same transaction), so a stale or missing
   comparison takes the approval, and it holds `awaiting_approval` to `live` to the same `compared_live_hash` rule,
   both NULL when the publish replaces none, so a candidate never replaces a live version it was not compared with.
   A version that loosens anything, and a first version with nothing live to compare against, go through
   `awaiting_approval`; a tool and an endpoint never take the branch, neither kind registering a comparator (a second
   person approves every tool version, ADR-0116 decision 9). A refusal raises SQLSTATE 23514 on
   `ck_artifact_versions_stage_transition`, mapped by name as ADR-0012 does.
   Partial unique indexes allow one `live` and one candidate per artifact; publishing retires the previous live
   version in the same transaction. Version numbers come from `last_version_no`, never reused. A rollback is a new
   version copied from an old one, reusing its gate evidence when the effective hash is equal. `LifecycleService`
   writes; the trigger is the backstop.
2. **Publishing takes a passing gate and a second person (D11).** Moving a version to `awaiting_approval` opens, in
   the same transaction, a run-less approval `studio.publish.agent`, `studio.publish.workflow`,
   `studio.publish.object` (an object definition, under D11), `studio.publish.endpoint` (a Data Hub endpoint) or,
   from W2, `studio.publish.tool` (a tool of any kind but `mcp`, whose approval is ADR-0116 decision 9's
   `studio.mcp.tool_approval`) whose payload holds identifiers only: version, `version_no`, `definition_hash`, for a
   gated kind `gate_run_id` with the AI risk tier and analysis outcome (ADR-0125), and `author_ids`. It is stamped
   `required_scope = 'studio.publish.approve'` (ADR-0004: no role stands in, `platform_admin` included; support
   contexts never carry `approvals.*`, ADR-0024 decision 6). That one permission answers who publishes every kind,
   an MCP tool being ADR-0116's one named exception: an endpoint's submit needs `studio.datahub.manage`, a key to
   submit with and never a second stamp; a kind's own condition (workflow-nodes' for workflows) is a check
   registered through a Protocol at the composition root, like `decision_guards`, never a permission key of its own.
   The strict prefixes `studio.publish.` and `studio.lifecycle.` are added with `|=` where Studio is wired, and the
   decision guard `require_not_author` refuses a decider in `payload.author_ids` and a payload without them (fail
   closed). The submitter is the approval's `requested_by`, and the strict prefix's check runs before any guard
   (ADR-0104 decision 11), so a submitter deciding is refused 409 `conflict` with `second_person_required` and only a
   contributor who did not submit meets the guard's `author_cannot_approve`; a requester deciding their own
   `studio.lifecycle.revive` or `studio.lifecycle.unfreeze` gets `second_person_required` too. A worker handler for
   each `studio.publish.<kind>.decided` settles idempotently on the approval id:
   approved retires the previous live version and makes this one `live` in one transaction, audits
   `studio.version.published` with the decider as actor, the lane in `details.lane` (ADR-0011: a lane carrying out
   one person's decision audits that person) and `details.path = 'approved'`, and emits `studio.version.live`;
   approved on a base that has moved, its `compared_live_hash` no longer the hash of the live version the publish
   would replace (decision 1), publishes nothing and returns the candidate to `draft` with `details.reason_code`
   `base_changed`, audited `studio.version.returned_to_draft` with the decider as actor and the lane in
   `details.lane`, so the builder submits it again against the new live version; rejected returns it to `draft`. On
   decision 1's tighten-only branch no approval opens: `LifecycleService` retires the previous live version and makes
   this one `live` in the submit transaction, audits `studio.version.published` with the submitter as actor and
   `details.path = 'tighten_only'`, and emits `studio.version.live` the same way.
   `POST .../versions/{id}/withdraw` cancels the pending approval with `ApprovalRequest.cancel()` and returns the
   version to `draft`; a lane cancels expired publish approvals, auditing as `system:<lane>` because it acts on its
   own. Publish also needs every required binding approved (ADR-0110) and an accountable owner (ADR-0103; else 409
   `owner_missing`, live versions still running).
3. **The quality gate.** A gate run executes the version's sealed tenant evaluation sets (from W2; in W1 only the
   security suite runs, and the key's dataset list is empty) and a platform security suite generated from its closure
   by `configs/evals/studio_security_suite@1.0.0.yaml` (prompt injection through the user message, untrusted tool
   output and retrieval; cross-tenant canaries; missing evidence; an effect without approval), which must pass at
   100%. Trials are normal runs in `simulate` mode (ADR-0111). The gate policy is versioned data
   (`configs/policies/studio_gate@1.0.0.yaml`, pinned in the release manifest with the suite; tenants tighten only)
   that declares only fields with a reader: in W1 `pass_k` = 3 (a case tagged `consistency` passes only if all k
   trials pass), a per-trial cost ceiling of USD 0.10, a worst-case cap of USD 10 per gate run and publish approval
   expiry after 14 days; minimum cases, pass rate and stale-draft days join in W2 with their readers (DO-29.1). The
   numbers are revisited after FOG-64, by a new policy version. Before the first model call the lane ends a gate run
   whose worst case is above the cap `error` with `limit_exceeded`. The gate run takes its lease through `LimitsPort`
   with purpose `eval_offline` (ADR-0121, DO-21.4); refused for what is left of the tenant's limits, an evaluation
   purpose cap among them from W2 (ADR-0121 decision 4), it ends the same way. Neither refusal carries an HTTP
   status, since no caller waits on the lane (DO-21.3). Verdicts are `pass`, `fail`, `unknown` (blocks like `fail`)
   and `error`. Evidence counts only for its exact key: the effective hash of ADR-0109 decision 6 (the definition
   hash plus the overlay entries, so a tenant override of a platform prompt voids older evidence, DO-27.1), the gate
   policy, the security suite and the dataset content hashes; a passing run with the same key is reused. The gate run
   records the run-time resolutions it saw (tenant overrides, MCP definitions, bindings, knowledge index).
4. **`dw_evals` is extended, not replaced.** `Observation`, `ObservationGrader`, `JudgePort`, `EvalTargetPort`, an
   async `run_cases` with trials and a pure `gate.py` (`GatePolicy`, `evaluate_gate`, the one function deciding
   "does this pass") are added; `SECURITY_CATEGORIES` (`packages/python/dw_evals/src/dw_evals/dataset.py:25`),
   `run_dataset` and `scripts/run_evals.py` keep their CI behaviour. Studio graders keyed `studio.<gate>` live in the Studio
   package and are merged at the worker's composition root; `dw_evals` imports no Studio package.
5. **Kill and freeze are switches, never stages.** `platform.control_switches` (tenant RLS, FORCEd) holds
   `scope_type` (`tenant`, `agent`, `workflow`, and `tool` for a tool's suspension, ADR-0116), `target_id`, `action`
   (`freeze` or `kill`), `origin` (`tenant`, `platform`), a reason code and text, and set and lift columns, one open
   switch per target; the trigger
   `platform.guard_control_switch()` allows an open insert and one lift, a platform-origin row lifted only by the
   provisioner. `platform.platform_freezes` (no tenant, `dw_app` SELECT only) holds at most one open platform freeze.
   "Killed" is a display state derived by one view, never stored on a version.
6. **Every door asks one `RunControlPort`.** Declared in `dw_agent_runtime.ports`, its
   `require_open(run_context, *, artifacts=())` raises `RunHaltedError` (409, `details.reason_code`
   `platform_frozen`, `tenant_frozen`, `artifact_killed`, `control_state_unavailable`, `principal_inactive` when the
   principal a run acts as, a person or a service principal, is no longer an active member (ADR-0113 decision 3
   shapes it per `trigger_kind`), and ADR-0102's `tenant_locked`, `tenant_offboarding`,
   `workspace_archived`). The doors: ingress and the run queue claim
   (ADR-0113), runner start, stream and resume, node start (ADR-0112), `ApproveAndResumeService.decide`, a
   `RunControlMiddleware` in agent and sub-agent stacks, the structured gateway and compaction, the `ToolExecutor`
   before its scope check (`deny_frozen`, `deny_killed`), and every lane sending a queued effect (among them
   connections-and-vault's lane that sends queued messages, agent-lifecycle R8.4), each given the port by injection,
   never a default (as `langgraph_runner.py:108-112` gets `allowance` and `budget`). The answer comes
   from a per-tenant snapshot with a 5 s TTL, invalidated by `pg_notify('dw_control_switch', ...)`, that refuses
   after 30 s without a refresh: fail closed, unlike the access-context cache (ADR-0024 decision 4).
7. **What each switch does.** A kill (one holder of `studio.lifecycle.kill` in the artifact's workspace) refuses new
   and queued `live` and `test` runs, cancelling the queued ones rather than holding them, stops running runs at the
   next door as `cancelled`, has a lane cancel the artifact's waiting runs with their approvals and disable its
   triggers, refuses its inbound events (`refused_killed`, ADR-0113), and still allows `simulate` runs so a fix can
   be evaluated. Lifting it is a strict `studio.lifecycle.revive` run-less approval stamped `studio.lifecycle.kill`: a
   second person (D11). A tenant freeze (one holder of `studio.lifecycle.freeze` at tenant depth, reason required)
   and a platform freeze (operators through the provisioning context, which a tenant admin cannot lift) refuse
   interactive runs not yet started (`chat`, `manual`, `test`, `replay`, `fork`; ADR-0113 decision 3), submissions,
   gate runs and publishes with `tenant_frozen` or `platform_frozen`, except that under a tenant freeze a
   `dw.object/v1` version may still take decision 1's tighten-only branch, since it only removes access, the change
   an incident most needs, while a platform freeze refuses that branch too; keep a queued trigger run (`datahub`,
   `provider_app`, `schedule`, `record_event`) queued, as a held inbound event is, to start in arrival order once
   lifted (ADR-0113 decision 3); cancel running runs at the next door; keep paused runs paused and refuse decisions
   on them; and hold inbound events to start in arrival order once lifted (ADR-0113) (DO-28 (C)). Lifting a tenant
   freeze is a strict `studio.lifecycle.unfreeze` run-less approval stamped `studio.lifecycle.freeze`, whose
   `.decided` handler lifts it: a second person (D11). A freeze has no time limit, so the retention lane skips the
   inbound events it holds and counts them (ADR-0122 decision 7). A provider call already in flight finishes and is
   recorded. Each change is audited in its own transaction (platform freezes in `platform.provisioning_audit`), and
   `dw_control_refusals_total{door, reason_code}` counts refusals.
8. **Lifecycle findings** derive from the dependency index (ADR-0109) by events plus an hourly sweep: a component
   newer, retired or killed, `mcp_definition_changed`, `tenant_override_stale`, `eval_stale`, `eval_below_threshold`,
   `binding_degraded` and `publish_failed`; an acknowledgement needs a reason and expires within 30 days.

## Alternatives considered

- **A stage machine in service code only.** Rejected: any writer, a buggy lane included, could make a version live
  (failure-modes #5).
- **"Killed" as a version stage.** Rejected: it would not reach paused runs on older versions, and reviving would
  need a fake transition.
- **Self-approval in a one-admin tenant**, two people only above two admins, or operators deciding. Rejected: D11
  and ADR-0012 refuse a one-person waiver, a rule that switches itself off fails open, and ADR-0004 and ADR-0024
  decision 6 keep operators out of tenant approvals.
- **A freeze that lets running work finish.** Rejected: an incident brake must stop effects.
- **A freeze that cancels every queued run, or holds every one** (DO-28 (A), (B)). Rejected: cancelling a Data Hub
  run loses a lead its sender was already answered 2xx for (YC44, KQ7), and holding a chat leaves its caller waiting
  without knowing why.
- **Gate evidence keyed by version id.** Rejected: a changed dependency would not invalidate it.
- **Switches in Valkey, or built on the tenant lock.** Rejected: Valkey is never a source of truth (CLAUDE.md:64),
  and the lock touches neither runs nor lanes.

## Consequences

- A tenant needs two people holding publish rights before it publishes anything; sales says so (D11).
- Every door gains a `RunControlPort` check and a negative test on its own path that sets the switch mid-run, not
  through the layer above it (failure-modes #5). Model calls outside runs (ingestion embeddings, rerank) are a named
  blind spot in v1.
- Gate runs cost the tenant money and stay flaky until k and the thresholds are measured (FOG-64);
  `studio.gate_case_results` is range-partitioned by month. W1 needs the switches, the guarded stage, the 100%
  security gate and two-person publish for the slice; tenant evaluation sets, findings and judges are W2.

### Contradictions and amendments

- _Amends CLAUDE.md:70-71 ("a release manifest pins the set a run used"), worth reopening because a Studio version is
  tenant data the repository-derived manifest cannot hold: a run gains a second pin, its run manifest with the
  definition hash, and the amendment is made with ADR-0109's acceptance._
- Agrees with ADR-0109 decision 6 since 2026-10-23: evidence is keyed by the effective hash, the key question of
  FOG-66 that DO-27.1 settled, and the gate run still records the run-time resolutions it saw.
- Studio evaluation sets live in PostgreSQL, not `evals/datasets/` (CLAUDE.md:37-41 stays the rule for code
  contexts); the platform suite extends CLAUDE.md:335-336 to every Studio version. CLAUDE.md:274-279, ADR-0004,
  ADR-0011 and ADR-0012 are reused unchanged; S13's "killed" beside the stages is refined, not contradicted.
- si-platform: ports the CHECK read back against the enum and never-reused version numbers from si-platform
  `docs/adr/0044-approval-runs-narrowed-by-the-record-workspace-history-append-only-unpartitioned.md`; diverges from
  its per-engine version tables (`db/si/migrations/0003_approval.sql:33`) and from si-platform
  `docs/adr/0047-two-person-setup-changes-are-decided-and-applied-in-one-transaction.md`: here the conflict check runs
  before the decision, and a failed settlement leaves a visible `publish_failed` finding.

## Open

1. **DO-07** (Đạt with the requester): direction answered by D11 on 2026-10-23 (publish and revive always take two
   people; a one-admin tenant cannot publish; revisit after the pilot only with evidence). Đạt's review is owed.
   Answered 2026-10-23: Đạt accepts D11 as the requester scoped it, closing with one person and opening with two.
2. **DO-28** (requester, then Đạt): provisional call (agent, 2026-10-23, option (a)): a freeze cancels running runs at
   the next door, keeps paused runs paused and refuses decisions. If wrong: a resumable park needs a `frozen` run
   status and a resume lane, after agent-lifecycle 01's resume prototype (v1.5). Answered 2026-10-23: option (a)
   stands for running and paused runs, and option C splits runs not yet started by `trigger_kind` (decision 7); the
   resumable park stays v1.5.
3. **DO-29** (Đạt): gate numbers and who pays. Recommended: 10 cases, 90%, k = 3, USD 0.10 per trial, USD 10 per gate
   run, 14 days to a stale draft, 14 days of publish approval; the tenant pays its own evaluations under a separate
   purpose cap (DO-50, provisional), the platform pays re-evaluations it triggers up to a cap. FOG-64 measures it.
   Answered 2026-10-23: W1's policy holds only the fields W1 reads (decision 3, DO-29.1); the tenant pays its own
   evaluations and the platform the re-evaluations it triggers, W1 needing only the `eval_offline` purpose, while
   purpose caps and the platform's capped share come in W2 (DO-29.2 (a)).
4. **FOG-65** (prototype): NOTIFY latency and reconnects, and whether 30 s is the right fail-closed bound.
5. **FOG-66** (grilling): who counts as an author when a version comes from builder assistance or a template, and
   which run-time resolutions (tenant override, MCP definition, knowledge content, provider model alias) make a live
   version not actually evaluated; its answer also settles the evidence key against ADR-0109. Partly answered
   2026-10-23: the evidence key is the effective hash, so a tenant override voids older evidence (DO-27.1). Still
   open: authorship, and which other run-time resolutions do the same.
6. Owned elsewhere, read here: DO-05 (Đạt: one envelope carrying this stage contract, ADR-0109); DO-39 (an
   accountable owner leaving blocks publishing, ADR-0103). Answered 2026-10-23: DO-05 as stated (DO-05 (a)); DO-39
   as stated, from W2 with YC10 (DO-39.2 (a)).

## Acceptance (2026-10-23)

Accepted by Đạt on 2026-10-23 with these amendments from the decision brief:

- Title and decisions 1 and 3: gate evidence is keyed by the effective hash of ADR-0109 decision 6, no longer by the
  definition hash (FOG-66's key, DO-27.1).
- Decision 1: the trigger's rule is per kind, and a kind without a quality gate (an object definition, a tool) goes
  from `draft` to `awaiting_approval` with only the second person (D11 for object definitions; the MCP stage-machine
  item, option (a)).
- Decision 2: `studio.publish.object` joins the approval types; one permission answers who publishes every kind, a
  kind's own condition registering at the composition root; the publish handler audits the decider with the lane in
  `details.lane`, and the expiry lane audits as itself (OPS-a.1).
- Decision 3: W1's `studio_gate@1.0.0` holds only fields with a W1 reader, with its numbers (DO-29.1); the gate's
  spend goes through a `LimitsPort` lease of purpose `eval_offline` (DO-21.4), and a refusal for its limit ends the
  gate run `error`, replacing the 429 (DO-21.3).
- Decision 5: `scope_type` gains `tool`, a tool's suspension.
- Decision 6: `principal_inactive` joins the reason codes (H:org-and-principals:R4.6 (b)).
- Decision 7: a freeze refuses interactive runs not yet started and holds queued trigger runs until it lifts, while a
  kill still cancels; this replaces "refuse new runs" (DO-28 (C)).
- Alternatives and Contradictions: DO-28's rejected options recorded; the difference with ADR-0109 is gone.
- Open: DO-07, DO-28, DO-29, DO-05 and DO-39 answered; FOG-66 answered for the evidence key; FOG-65 stays open.

## Amendments (2026-10-24)

Amended by Đạt on 2026-10-24, who accepted every recommendation the second consistency check left open, with the
D11 cases scoped by the requester and Đạt:

- Decision 1: a `dw.object/v1` version that only tightens goes from `draft` to `live` by one person, audited; the
  trigger reads `tighten_only` and `compared_live_hash`, and every version that loosens anything still waits for a
  second person (Q-R6; the D11 case on narrowing `default_access`; B:agent-lifecycle:R1.6~custom-objects:R1.7).
- Decision 2: `studio.version.published` names the decider on the approved path and the submitter on the
  tighten-only path, with `details.path` `approved` or `tighten_only`.
- Decision 3: a worst case above the gate run's cap ends the run `error` with `limit_exceeded`; the 422 goes, since
  no caller waits on the lane (F:ADR-0120~agent-lifecycle:R4.4).
- Decision 6: the lane that sends queued messages is connections-and-vault's, and it asks the port like every door.
- Decision 7: lifting a tenant freeze takes a second person through `studio.lifecycle.unfreeze`, as agent-lifecycle
  R7.10 and R7.11 already say (D:ADR-0120~agent-lifecycle:R7.10); a freeze has no time limit, and the retention lane
  skips the events it holds; `replay` and `fork` are interactive runs (ADR-0113 decision 3).
- Third consistency check (round 4), Đạt's V4.1, V4.2, V4.3, V4.8 and V4.9: decisions 1 and 2 add the Data Hub
  endpoint as a kind without a quality gate, published through `studio.publish.endpoint`
  (D:ADR-0120\~workflow-triggers:spec), `compared_live_hash` on every submit with `base_changed` for a candidate
  approved after its base moved (D:ADR-0120\~tenant-config:R2.16), and `studio.publish.tool` for every tool kind but
  `mcp`, the one named exception to the one publish permission (A:mcp-client:R3.1\~tools-and-skills:spec); decision
  7 lets the object definition's tighten-only branch through a tenant freeze, never a platform one
  (F:ADR-0120\~custom-objects:R1.7); decision 6's `principal_inactive` names a service principal too, which ADR-0113
  decision 3 now holds for trigger runs (B:ADR-0120\~workflow-engine:R5.15).
- Third consistency check (round 4), second pass, the planner's provisional calls: decision 1's `compared_live_hash`
  rule compares with the live version this publish replaces, or, on the approval path, with none (the tighten-only
  branch always replaces one), because the partial unique index on `live` makes the publish retire that version
  before the candidate becomes `live`, so when the trigger runs no "current" live version is left to compare with
  (if it is wrong, the rule follows the order in which the publish transaction retires and sets); decision 2
  states that a submitter deciding meets the strict prefix's `second_person_required` before the
  `require_not_author` guard, which answers `author_cannot_approve` to any other author, in the order ADR-0104
  decision 11 gives (V4.P9; if it is wrong, each approval type names its own code through its `decision_guards`
  entry), and names the audit of a `base_changed` return, `studio.version.returned_to_draft`, the action
  agent-lifecycle already writes for a return to `draft`; decisions 1 and 2 place the `tool` kind and
  `studio.publish.tool` in W2, when that kind registers, completing V4.1 and V4.3 (if it is wrong, the ticket that
  registers the `tool` kind, with the submit key it declares, moves to W1); decision 3's gate run is refused for what
  is left of the tenant's limits, an evaluation purpose cap among them only from W2, as ADR-0121 decision 4 now says
  (V4.P6).
- Third consistency check (round 4), third pass: decision 1's `gate_run_id` and `publish_approval_id` are composite
  foreign keys `(tenant_id, <column>)` to their targets' `UNIQUE (tenant_id, id)`, added in the same revision where
  `studio.gate_runs` or `platform.approval_requests` lacks it, because a foreign key check does not pass through RLS
  and a one-column key would let a version name another tenant's gate run or approval.
