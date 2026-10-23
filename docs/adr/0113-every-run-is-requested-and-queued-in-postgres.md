---
status: Proposed (agent-proposed on 2026-10-23; not yet reviewed by Đạt)
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
decision rests on it, and the provisional calls it leans on are marked in Open.

## Context

- Agent runs execute inline in the API, and the plan quota is enforced where a run begins (`CLAUDE.md:220-224`). The
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
   resolves the version (only the live version runs `live`), fixes the run mode (ADR-0111), resolves the run-as
   principal (ADR-0103), builds the run manifest (ADR-0109) and inserts the row `queued`
   `ON CONFLICT (tenant_id, request_key) DO NOTHING`, returning the existing run. The queue is `platform.worker_runs`,
   which gains `trigger_kind`, `trigger_ref`, `inbound_event_id`, `request_key` (partial unique per tenant),
   `parent_run_id`, `root_run_id`, `chain_depth`, `run_as_principal_id`, `priority` (0 interactive, 1 background, 2
   eval), `available_at`, `lease_owner`, `lease_until`, `attempt`, `deadline_at`, `cancel_requested_at` and the
   statuses `queued`, `waiting` and `blocked`. An architecture test allows no other writer of a queued Studio row.
2. **A fair claim without BYPASSRLS.** SECURITY DEFINER `platform.studio_run_scopes_due(p_limit)` returns the tenant
   ids with due work, identifiers only (the pattern of `platform.channel_delivery_scopes_due`,
   `packages/python/dw_platform/src/dw_platform/adapters/persistence/channel_deliveries.py:47`). Per tenant, under
   `set_config('app.tenant_id', ..., true)`, an RLS-bound claim (an `UPDATE` over `SELECT ... FOR UPDATE SKIP LOCKED`)
   takes at most `ceil(batch / tenants)` rows by `(priority, available_at)`. Measured on 2026-10-22: behind one
   tenant's 100,000-row backlog, another tenant's first claim took 0.9 s, against 4.8 s first-in-first-out.
3. **Admission at dispatch, fenced claims, a deadline for every run.** At claim, `RunControlPort.require_open`
   (ADR-0120), then `LimitsPort.admit` (ADR-0121): a window or concurrency refusal re-queues with a later
   `available_at`, a hard refusal fails the run with `limit_exceeded`. A claim lease (`lease_owner`, `lease_until`; not
   ADR-0121's budget lease) lasts 60 s with a 15 s heartbeat; state and checkpoint writes are fenced by
   `(lease_owner, attempt)`, so a stale holder's writes fail. Lane `studio_run_reaper` re-queues expired claims with
   backoff `min(2^attempt * 5 s, 10 min)` plus jitter; after 5 attempts the run is dead-lettered (`dead_lettered`,
   audit `run.dead_lettered`, outbox `studio.run.dead_lettered`). `POST /api/v1/runs/{run_id}/cancel` (`runs.cancel`)
   sets `cancel_requested_at` and notifies on `dw_run_state` (`run_store.py:51-53`), which `RunStateListener`
   (`adapters/run_events.py:96`) turns into a task cancel; queued and waiting runs are cancelled in the database with
   their open waits and approvals. `deadline_at = admitted_at + min(limits.max_run_seconds, plan ceiling)`, waits
   included (default 30 days, at most 90), is checked at node start, at resume and by the reaper (`deadline_exceeded`).
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
   previous live version's rows retire in the same transaction. Every outcome is one `studio.trigger_deliveries` row
   (monthly range partitions with a DEFAULT partition, RLS on every partition): `run_requested`, `duplicate`,
   `rejected`, `quarantined`, `held_frozen`, `refused_killed`, `skipped_overlap`, `missed`, `suppressed_self`,
   `suppressed_loop`, `suppressed_budget`, `limit_refused`. Idempotency is the run row's `request_key`, because a
   unique index cannot span partitions: `<subscription_id>:<event_id>`, and for a schedule fire
   `sched:<subscription_id>:<nominal UTC time>`, so a second replica's fire of one occurrence is refused. Under a
   freeze (ADR-0120) an inbound event is stored and started in arrival order once the freeze lifts; a killed
   workflow's events are refused (`refused_killed`) while the sender is still answered 2xx, so it keeps the endpoint.
6. **Inbound ingress stores and answers, and starts nothing.** A Data Hub endpoint is a Studio artifact of kind
   `endpoint` (`dw.endpoint/v1`) with a public id of `ep_` and 26 Crockford base32 characters (130 random bits),
   resolved before any tenant context by SECURITY DEFINER `studio.resolve_inbound_endpoint(p_public_id)` (ids and
   settings only). `POST /api/v1/hooks/in/{public_id}` resolves (unknown or disabled: the same 404), rate-limits (429
   with `Retry-After`), caps the body (65,536 bytes by default, 262,144 at most; 413), verifies through the one
   signature-verifier module (ADR-0115) over the exact bytes with a 5-minute tolerance (a static token before the body
   is read, ADR-0008's order), validates (422 without echo, or quarantine), deduplicates in `studio.inbound_dedupe` for
   at least 72 hours and stores the `studio.inbound_events` row in one transaction, then answers 2xx in under 1 s at
   p99. No model or provider call runs on this path; the `studio_inbound` lane hands accepted events to the door.
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
   refused at publish; run taint flows both ways; its run mode is never less safe than its parent's; a child waiting
   for a person reports `waiting`, never success. Only root runs count toward runs per day (ADR-0121).
10. **Chat runs in the worker.** A conversation turn is a run of trigger kind `chat` requested through the door and
    executed by the worker; the client polls in P1, and streaming arrives in P2 over an ephemeral Valkey relay that is
    never the source of truth. The API never executes an agent inline.

## Alternatives considered

- **An external queue (Celery, a Valkey stream).** Rejected: Valkey is never a source of truth (`CLAUDE.md:60`), and a
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
- Reinforces `CLAUDE.md:220-224`. Follows `docs/adr/0008-chat-updates-poll-locally-webhook-when-hosted.md` for inbound
  endpoints and `docs/adr/0006-provider-neutral-channel-delivery-outbox.md` for the outbox shape; neither changes.
  ADR-0008's queue is identity plane without RLS
  (`db/migrations/versions/395acbcad324_platform_channel_inbound_updates.py:15`); Data Hub inbound events are tenant
  rows behind an identifiers-only lookup instead.
- Contradicts `apps/worker/src/dw_worker/main.py:203-205` ("The platform worker hosts no graph") and
  `run_store.py:216-220` (a cross-tenant reaper needs `BYPASSRLS`); worth changing, because a run executed in the API
  has no fair claim and no crash recovery, and an identifiers-only definer function reaps without bypassing RLS.
- si-platform: re-derived; si-platform has nothing to port for a run queue.

## Open

1. **DO-41 (Đạt).** Runs wait in place with compaction in v1, and the segment model only if measurement asks for it?
2. **DO-44 (Đạt with the requester; counsel for conversations).** Chat runs in the worker through `RunRequestService`,
   with polling in P1?
3. **DO-48 (requester; counsel on fan-out).** Does the same Page or OA connected by two tenants fan out to both,
   silently? Provisional call (agent, 2026-10-23): fan out to both, counsel to confirm.
4. **DO-52 (counsel and Đạt).** Retention for inbound events (30 days proposed), trigger deliveries (90 days), terminal
   runs (180 days), checkpoints (24 hours after the run ends) and inbound dedupe rows (72 hours).
5. **Related provisional calls (agent, 2026-10-23).** DO-28: a freeze cancels running runs at the next door, keeps
   waiting runs waiting and refuses decisions. DO-39: inbound events for a locked tenant are refused with 503 and
   nothing is stored.
