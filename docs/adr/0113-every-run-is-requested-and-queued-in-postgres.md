---
status: Accepted (Đạt, 2026-10-23; amendments from the decision brief applied)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/workflow-engine/spec.md
    - ../../.claude/plans/studio/workflow-triggers/spec.md
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py
    - ../../packages/python/dw_platform/src/dw_platform/adapters/persistence/channel_deliveries.py
---

# 0113. Every Studio run is requested through one door and executed by the worker from a Postgres queue that is the run row itself; triggers and inbound events only request runs

Numbered 0113 in the block 0100-0199 that ADR-0100 reserves for Studio. Agent-proposed under stance S6; no requester
decision rests on it. Đạt accepted it on 2026-10-23 together with ADR-0121, whose `LimitsPort` its claim calls,
with the amendments listed under Acceptance; the calls it leaned on are answered in Open.

## Context

- Agent runs execute inline in the API, and the plan quota is enforced where a run begins (`CLAUDE.md:260-265`). The
  worker "hosts no graph" (`apps/worker/src/dw_worker/main.py:203-205`). A stale `platform.worker_runs` row is reaped
  only on the claim path, because "a cross-tenant reaper needs `BYPASSRLS`"
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py:216-220`).
- An approval resumes its run inline on the decider's request
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:268`): a crash after the decision commits
  strands a decided approval.
- Studio adds many ways to start a run: chat, a manual start, an agent node, a linked agent, a workflow tool, an
  evaluation, Data Hub endpoints, provider-app events, schedules and record events. Each one that starts a run itself
  is a door that can skip admission, freezes and limits (failure-modes #5), and workflows wait days for people.
- Provider apps deliver every tenant's events to one app-level URL: Meta signs with `X-Hub-Signature-256`, retries for
  36 hours and batches up to 1,000 updates (<https://developers.facebook.com/docs/graph-api/webhooks/getting-started>,
  read by the research on 2026-10-22); Zalo's `X-ZEvent-Signature` formula is unverified (FOG-04).

## Decision

1. **One door, and the queue is the run row.** `RunRequestService.request(RunRequest)` is the only way a Studio run
   starts, for `trigger_kind` `chat`, `manual`, `test`, `agent_node`, `agent_link`, `agent_tool` (a workflow tool),
   `subworkflow`, `eval`, `replay`, `fork` and the triggers `datahub`, `provider_app`, `schedule`, `record_event`. It
   resolves the version (only the live version runs `live`, and a draft only `simulate`, ADR-0109 decision 6), fixes
   the run mode (ADR-0111), resolves the run-as principal (ADR-0103), builds the run manifest (ADR-0109) and inserts
   the row `queued` `ON CONFLICT (tenant_id, request_key) DO NOTHING`, returning the existing run. The queue is
   `platform.worker_runs`, which gains `trigger_kind`, `trigger_ref` (from W2, since nothing in W1 reads it),
   `inbound_event_id`, `request_key` (partial unique per tenant), `parent_run_id`, `root_run_id`, `chain_depth`,
   `run_as_principal_id`, `priority` (0 interactive, 1 background, 2 eval), `available_at`, `lease_owner`,
   `lease_until`, `attempt`, `deadline_at` and `cancel_requested_at` (both from W2, decision 3), and the statuses
   `queued`, `waiting`, `blocked` and `dead_lettered`. An architecture test allows no other writer of a queued Studio
   row.
2. **A fair claim without BYPASSRLS.** SECURITY DEFINER `platform.studio_run_scopes_due(p_limit)` returns the tenant
   ids with due work, identifiers only (the pattern of `platform.channel_delivery_scopes_due`,
   `packages/python/dw_platform/src/dw_platform/adapters/persistence/channel_deliveries.py:47`). Per tenant, under
   `set_config('app.tenant_id', ..., true)`, an RLS-bound claim (an `UPDATE` over `SELECT ... FOR UPDATE SKIP LOCKED`)
   takes at most `ceil(batch / tenants)` rows by `(priority, available_at)`. Measured on 2026-10-22: behind one
   tenant's 100,000-row backlog, another tenant's first claim took 0.9 s, against 4.8 s first-in-first-out.
3. **Admission at dispatch, fenced claims, and from W2 a deadline for every run.** At claim the `studio_runs` lane asks
   `RunControlPort.require_open` (ADR-0120), then `LimitsPort.admit` (ADR-0121). That claim is the one place a Studio
   run is admitted; a child run shares its root's lease and is not admitted again (decision 9). One table keyed by
   `trigger_kind` shapes every refusal, for freezes and limits alike, and gives every kind of decision 1 its row:
   `chat`, `manual`, `test`, `replay` and `fork` are interactive runs; `datahub`, `provider_app`, `schedule` and
   `record_event` are trigger runs; `eval` is an evaluation trial; and a child run (`subworkflow`, `agent_node`,
   `agent_link`, `agent_tool`) is never admitted on its own, so only its root's row applies. From W2 (YC79), missing
   concurrency re-queues every kind with a later `available_at`. A freeze re-queues a trigger run with a later
   `available_at`, so that it starts in arrival order once the freeze lifts, and ends an interactive run or an
   evaluation trial at once as `cancelled` with `tenant_frozen` or `platform_frozen`. A spent hard limit
   re-queues a `datahub`, `provider_app` or `record_event` run until the window's `resets_at`, never dropping it;
   records a `schedule` fire (W2) as `limit_refused` and skips it instead of holding it, because holding every missed
   fire would release them all at once when the next window begins; ends an interactive run `failed` with
   `limit_exceeded` and `resets_at` (a conversation shows it as a `notice`); and ends an evaluation's gate run `error`
   with `limit_exceeded` (ADR-0120). `principal_inactive`, the run-as principal no longer `active`, keeps a
   `datahub`, `provider_app` or `record_event` run `queued`, as a freeze holds a trigger run, and alerts the
   accountable owner (ADR-0103); once the principal is active again the held runs start in arrival order, and a
   person may cancel them, audited, their inbound events staying replayable (one at a time through the cancel route
   from W2; in W1 a kill of the artifact cancels them, ADR-0120 decision 7); it ends a run of every other kind
   `cancelled`, a `schedule` fire included. `binding_needs_review` refuses an unattended run before it is requested
   while its service principal's grants have grown since its `principal` binding was approved, its trigger delivery
   recorded `rejected`, until someone who covers the new grants approves the binding again (ADR-0103 decision 4).
   `control_state_unavailable` re-queues any kind with a later `available_at`, refusing it without dropping it. A
   killed artifact's queued runs are cancelled, never held. A claim lease
   (`lease_owner`, `lease_until`; not ADR-0121's budget lease) lasts 60 s with a 15 s heartbeat; state and
   checkpoint writes are fenced by `(lease_owner, attempt)`, so a stale holder's writes fail. Lane
   `studio_run_reaper` re-queues expired claims with backoff `min(2^attempt * 5 s, 10 min)` plus jitter; after 5
   attempts the run is dead-lettered (`dead_lettered`,
   audit `run.dead_lettered`, outbox `studio.run.dead_lettered`). From W2, with workflow-engine's W2 row,
   `POST /api/v1/runs/{run_id}/cancel` (`runs.cancel`) sets `cancel_requested_at` and notifies on `dw_run_state`
   (`run_store.py:51-53`), which `RunStateListener` (`adapters/run_events.py:96`) turns into a task cancel, queued
   and waiting runs being cancelled in the database with their open waits and approvals; and, as ADR-0126 (Accepted)
   states, `deadline_at = admitted_at + min(limits.max_run_seconds, plan ceiling)`, waits included (default 30 days,
   at most 90), is checked at node start, at resume and by the reaper (`deadline_exceeded`). W1 has neither, and nothing
   there bounds a wait: a step approval waits with no deadline (ADR-0112 decision 7, DO-31), and only a kill cancels
   an artifact's waiting runs (ADR-0120 decision 7). Once the deadline ships its bound stays: a process that lasts
   months is a chain of short runs over one record's lifecycle in stages (ADR-0126 (Accepted)), never one run.
4. **A run waits in place.** Each wait is an `interrupt()` plus a durable `platform.run_waits` row (RLS ENABLE and
   FORCE; `kind` `approval`, `task`, `timer`, `child_run`; `status` `open`, `resolved`, `consumed`, `expired`,
   `cancelled`; unique `(tenant_id, run_id, interrupt_id)`); several may be open. A decision, a due timer or a child
   run's end is written in the deciding transaction (the wait `resolved`, the run `queued`): `ApproveAndResumeService`
   gets a dispatch table of in-transaction decision handlers keyed by approval-type prefix (`studio.step.` to the
   Studio handler), registered at the composition root like `strict_approval_prefixes` and written where the run-less
   outbox event already is (`approval_flow.py:245`), never the inline resume. The runner resumes by interrupt id
   (`Command(resume={interrupt_id: envelope})`), never with an empty map (measured: the run silently parks again). A
   run turning `waiting` keeps only its latest checkpoint (compaction; measured 45 KB to 14 KB per parked run). The
   segment model (a wait ends the thread, its state moves to a `dw.continuation/v1` row) is the named next design,
   adopted only if measurement shows parked runs outgrowing compaction.
5. **Triggers request runs and never start them.** When a version becomes live, its triggers are materialised as
   `studio.trigger_subscriptions` rows (`datahub`, `provider_app`, `schedule`, `record_event`, `agent_tool`), and the
   previous live version's rows retire in the same transaction: the `workflow` kind's publish hook (ADR-0109
   decision 1), which workflow-engine supplies, calls a `TriggerActivationPort` that workflow-engine declares and
   workflow-triggers satisfies by writing those rows, the composition root joining the two. Every outcome is one
   `studio.trigger_deliveries` row (monthly range partitions with a DEFAULT partition, RLS on every partition):
   `run_requested`, `duplicate`, `rejected`, `quarantined`, `held_frozen`, `refused_killed`, `skipped_overlap`,
   `missed`, `suppressed_self`, `suppressed_loop`, `suppressed_budget`, `limit_refused`. Idempotency is the run
   row's `request_key`, because a unique index cannot span partitions: `<subscription_id>:<event_id>`, and for a
   schedule fire `sched:<subscription_id>:<nominal UTC time>`, so a second replica's fire of one occurrence is
   refused. Under a
   freeze (ADR-0120) an inbound event is stored and held, with one `held_frozen` delivery written when the hold
   starts: the `studio_inbound` lane asks `RunControlPort` each cycle, leaves held events alone while the freeze holds
   and, once it lifts, requests their runs in `received_at` order. A freeze has no time limit, so the retention lane
   skips a held event whatever its age and counts it (ADR-0122 decision 7). A killed workflow's events are refused
   (`refused_killed`) while the sender is still answered 2xx, so it keeps the endpoint.
6. **Inbound ingress stores and answers, and starts nothing.** A Data Hub endpoint is a Studio artifact of kind
   `endpoint` (`dw.endpoint/v1`) with a public id of `ep_` and 26 Crockford base32 characters (130 random bits),
   resolved before any tenant context by SECURITY DEFINER `studio.resolve_inbound_endpoint(p_public_id)` (ids and
   settings only). `POST /api/v1/hooks/in/{public_id}` resolves (unknown, disabled, or with no `live` version yet: the
   same 404 `not_found`, nothing stored, the last case counted on a metric, closed while missing), rate-limits (429
   with `Retry-After`), caps the body (65,536 bytes by default, 262,144 at most; 413), verifies through the one
   signature-verifier module (ADR-0115) over the exact bytes with a 5-minute tolerance (a static token before the body
   is read, ADR-0008's order), validates against the `live` version's schema (422 without echo, or quarantine),
   deduplicates in `studio.inbound_dedupe` for at least 72 hours and stores the `studio.inbound_events` row in one
   transaction, then answers 2xx in under 1 s at p99, measured at 100 requests per second. No model or provider call
   runs on this path; the `studio_inbound` lane hands accepted events to the door.
7. **Provider-app events are routed by the account they name.** `POST /api/v1/hooks/providers/{provider_app_key}`
   (with Meta's `GET` handshake) verifies with the provider app's secret before anything else, then routes each entry
   by its external account (a Page, an OA) through SECURITY DEFINER
   `platform.resolve_provider_event_routes(p_connector_key, p_oauth_client_id, p_external_account_ref)` to every
   active connection that proved control of that account by OAuth (ADR-0115), stored under each routed tenant only. An
   entry no connection holds is dropped and counted (`dw_provider_events_unrouted_total`), never stored without a
   tenant. No request names a tenant: the signature makes the provider the asserting party, and only an OAuth-proven
   connection writes the account-to-tenant mapping.
8. **Record events fire on an edge.** A condition over `old` and `new` fires only on false-to-true
   (`fire_when: becomes_true`; `is_true` opt-in), never on the subscribing workflow's own writes (`suppressed_self`),
   never above chain depth 8 (`suppressed_loop`, tenant admins notified) and at most 5 runs per hour per workflow and
   record (`suppressed_budget`). `RecordService` stamps `origin_run_id`, `chain_depth` and `correlation_id` from the
   run context, never from input.
9. **Child runs.** A sub-workflow, a workflow tool, a linked agent and an agent node start a child run through the same
   door. The child shares the root's run-as principal, budget lease and limits; depth is at most 3 and cycles are
   refused at submit; run taint flows both ways; its run mode is never less safe than its parent's; a child waiting
   for a person reports `waiting`, never success. Only root runs count toward runs per day (ADR-0121).
10. **Chat runs in the worker.** A conversation turn is a run of trigger kind `chat` requested through the door and
    executed by the worker; the client polls in P1, and streaming arrives in P2 over an ephemeral Valkey relay that is
    never the source of truth. The API never executes an agent inline.
11. **Which rows carry a workspace.** `studio.inbound_events` and `studio.trigger_deliveries` carry `workspace_id`, a
    snapshot of the workspace that owns the endpoint or the subscription when the row is written, as
    `platform.worker_runs.workspace_id` is the run's, under tenant-only RLS as that table has: personal payloads are
    filtered by workspace depth through an index and found per data subject (YC90), and the event history (W2) reads
    the column on deliveries. `platform.run_waits` (a child of its run, deleted with it), `studio.inbound_dedupe` (a
    72-hour key holding no personal data) and the configuration rows of `studio.trigger_subscriptions` and
    `studio.inbound_endpoints` are tenant-wide, each listed with its reason under amendment A6 (ADR-0100).

## Alternatives considered

- **An external queue (Celery, a Valkey stream).** Rejected: Valkey is never a source of truth (`CLAUDE.md:64`), and a
  second store of run state would drift from the run row. Temporal is a second runtime and system of record; it stays
  the escape hatch behind `WorkflowRunnerPort`.
- **Triggers start runs inline.** Rejected: it bypasses admission, freezes and limits (failure-modes #5).
- **Agents run in the API process.** Rejected: no fairness, no claim lease, no crash recovery, and a second door with
  its own admission.
- **The segment model now.** Rejected for v1: a second state format and a seeding path before measurement shows parked
  runs outgrowing compaction; the pilot parks hundreds of runs, not tens of thousands.
- **A first-in-first-out claim, or BYPASSRLS for the reaper.** Rejected: measured starvation; BYPASSRLS is the
  migrator's alone, and an identifiers-only definer function is enough.
- **Telling the second tenant that an account is already connected.** Rejected: it would reveal the first tenant.

## Consequences

- agent-builder, workflow-triggers, agent-lifecycle (gate trials) and tools-and-skills (workflow tools) all enter
  through workflow-engine's door. connections-and-vault supplies the provider route function and the
  signature-verifier module; workflow-triggers owns the ingress path.
- Migrations: the new `platform.worker_runs` columns and CHECKs (with `uq_worker_runs_tenant_id_id` for the composite
  foreign key of `parent_run_id`); `platform.run_waits`; `studio.trigger_subscriptions`, `studio.inbound_endpoints`,
  `studio.inbound_dedupe`; `studio.trigger_deliveries` and `studio.inbound_events` partitioned monthly through
  `platform.ensure_time_partitions`; the definer functions. Lanes `studio_runs`, `studio_run_reaper`,
  `studio_inbound`, `studio_schedules` and, in P2, `studio_timers`.
- Tests that must exist, each red when its guard is removed: no second writer of queued rows; one tenant's backlog
  not starving another; a stale holder's write refused by the fence; a decided approval surviving a crash before
  resume; an empty resume map refused; a forged provider event never routed; tenant A's Page never reaching tenant B;
  a schedule fired by two replicas running once; a record-event chain stopping at depth 8; a waiting child reporting
  `waiting`.
- Harder: every new start path must go through the door; each linked-agent call pays queue latency; P1 has no token
  streaming.
- Reinforces `CLAUDE.md:260-265`, whose port becomes `LimitsPort` with ADR-0121. Follows
  `docs/adr/0008-chat-updates-poll-locally-webhook-when-hosted.md` for inbound endpoints and
  `docs/adr/0006-provider-neutral-channel-delivery-outbox.md` for the outbox shape; neither changes.
  ADR-0008's queue is identity plane without RLS
  (`db/migrations/versions/395acbcad324_platform_channel_inbound_updates.py:15`); Data Hub inbound events are tenant
  rows behind an identifiers-only lookup instead.
- Contradicts `apps/worker/src/dw_worker/main.py:203-205` ("The platform worker hosts no graph") and
  `run_store.py:216-220` (a cross-tenant reaper needs `BYPASSRLS`); worth changing, because a run executed in the API
  has no fair claim and no crash recovery, and an identifiers-only definer function reaps without bypassing RLS.
- si-platform: re-derived; si-platform has nothing to port for a run queue.

## Open

1. **DO-41 (Đạt).** Runs wait in place with compaction in v1, and the segment model only if measurement asks for it?
   Answered 2026-10-23: yes (DO-41 (a)); the segment model waits until UAT measurement asks for it.
2. **DO-44 (Đạt with the requester; counsel for conversations).** Chat runs in the worker through `RunRequestService`,
   with polling in P1? Answered 2026-10-23: yes, with server-sent events over an ephemeral Valkey relay in P2 (DO-44.1
   (a), the line Đạt confirmed in agent-builder's spec); who may read a conversation is ADR-0117's.
3. **DO-48 (requester; counsel on fan-out).** Does the same Page or OA connected by two tenants fan out to both,
   silently? Answered 2026-10-23, provisionally (DO-48.2 (a)): fan out to both, so decision 7 stands. Provider-event
   routing (W2) stays off until counsel's opinion (compliance-pdpl 02) and discovery 18's third question are in; if
   counsel refuses the fan-out, decision 7 is redesigned under the constraint that no tenant learns of another (the
   last alternative above), never as a refusal at connect.
4. **DO-52 (counsel and Đạt).** Retention for inbound events (30 days proposed), trigger deliveries (90 days), terminal
   runs (180 days), checkpoints (24 hours after the run ends) and inbound dedupe rows (72 hours). Answered 2026-10-23,
   provisionally (DO-52 (a)): the terms are versioned data in ADR-0122's retention policy, UNVERIFIED until counsel
   confirms them before shadow runs: inbound events 30 days, trigger deliveries 90 days, checkpoints 24 hours after the
   run ends and dedupe rows 72 hours, while terminal runs keep ADR-0122's 395 days.
5. **Related provisional calls (agent, 2026-10-23).** DO-28: a freeze cancels running runs at the next door, keeps
   waiting runs waiting and refuses decisions. DO-39: inbound events for a locked tenant are refused with 503 and
   nothing is stored. Answered 2026-10-23: DO-28 keeps both and takes option C for runs not yet started (decision 3,
   ADR-0120 decision 7); DO-39 holds from W1 for a locked or offboarding tenant (DO-39.1 (a)).

## Acceptance (2026-10-23)

Accepted by Đạt on 2026-10-23, together with ADR-0121, with these amendments from the decision brief:

- Decision 3: the `studio_runs` lane's claim is the one place a Studio run is admitted, and one table keyed by
  `trigger_kind` shapes every refusal. A freeze or a spent hard limit re-queues a trigger run with a later
  `available_at` and ends an interactive run at once; a `schedule` fire refused for its window is recorded
  `limit_refused`; an evaluation's gate run ends `error`; a killed artifact's queued runs are cancelled. This replaces
  "a hard refusal fails the run" (DO-28 (C), DO-21.3 (a)).
- Decision 5: the `studio_inbound` lane asks `RunControlPort` each cycle and requests the runs of held events in
  `received_at` order once a freeze lifts (H:agent-lifecycle:R7.2~workflow-triggers:R1.3 (a)).
- Decision 6: the p99 bound is measured at 100 requests per second (requirements Q2 (a)).
- Decision 11, new: inbound events and trigger deliveries carry `workspace_id` under tenant-only RLS, while run waits,
  dedupe keys and trigger configuration are tenant-wide under amendment A6 (the CRITICAL on `platform.run_waits`,
  option (a)).
- Open: DO-41, DO-44, DO-48, DO-52, DO-28 and DO-39 answered.

## Amendments (2026-10-24)

Amended by Đạt on 2026-10-24, who accepted every recommendation the second consistency check left open:

- Decision 3: a `schedule` fire on a spent window is recorded `limit_refused` and skipped, with its reason, and
  `CLAUDE.md` (Agent and tool rules) now names this exception beside "a triggered one waits in the queue, never
  dropped" (Q-R7, DO-21.3).
- Decision 3: the refusal table gives every `trigger_kind` of decision 1 a row: `replay` and `fork` are shaped as
  interactive runs, a child run is never admitted on its own, and `principal_inactive` and
  `control_state_unavailable` have their rows (B:ADR-0113~workflow-engine:R3.1).
- Decision 3: the run deadline stays at 30 days by default and 90 at most; a long process is a chain of short runs
  over a record's lifecycle (N5, ADR-0126 (Accepted)).
- Decision 5: a freeze has no time limit, and the retention lane skips the events it holds and counts them
  (B:agent-lifecycle:R7.2~telemetry-and-audit:R5.5).
- Third consistency check (round 4): decision 3's `principal_inactive` holds a `datahub`, `provider_app` or
  `record_event` run `queued` and alerts the accountable owner, ending only the other kinds, and
  `binding_needs_review` gets its row (Đạt's V4.9; B:ADR-0120\~workflow-engine:R5.15,
  F:ADR-0113\~org-and-principals:R4.6); the cancel route, `cancel_requested_at` and `deadline_at` are W2, the
  deadline matching ADR-0126 (Accepted), so a held run is cancelled one at a time from W2 and by a kill in W1, and
  decision 3 states that nothing bounds a W1 wait (F:ADR-0113\~workflow-engine:R3.1, a CRITICAL row); decision 9
  refuses cycles at submit, where ADR-0112 decision 3's validator runs (G:ADR-0112\~ADR-0113).
- Third consistency check (round 4), second pass, the planner's provisional calls: decision 3's re-queue for missing
  concurrency arrives from W2 with the concurrency caps of YC79, ADR-0121 decisions 4 to 6 now saying the same
  (V4.P6; if it is wrong, W1 takes the concurrency caps and this row with them); decision 1's `trigger_ref` comes
  from W2, nothing in W1 reading it (failure-modes #1), its statuses name `dead_lettered`, which decision 3's
  reaper already writes, and the door resolves a draft for `simulate` only, as ADR-0109 decision 6 now admits
  (completing Đạt's V4.4); decision 6 answers an event for an endpoint with no `live` version the same 404, storing
  nothing and counting it, and validates against the `live` version's schema (if it is wrong, such an event is held
  until a version goes live).
- Third consistency check (round 4), third pass: decision 5 names who writes a workflow version's trigger
  subscriptions in its publish transaction, the `workflow` kind's publish hook (ADR-0109 decision 1) calling a
  `TriggerActivationPort` that workflow-engine, its consumer, declares and workflow-triggers satisfies, the
  composition root joining the two (`CLAUDE.md`, Non-negotiable architecture); the `endpoint` kind's hook stays
  workflow-triggers' own.
