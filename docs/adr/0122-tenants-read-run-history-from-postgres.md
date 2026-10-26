---
status: Accepted (Đạt, 2026-10-23; amendments from the decision brief applied)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/telemetry-and-audit/spec.md
    - ../../packages/python/dw_observability/src/dw_observability/metrics.py
    - ../../configs/policies/retention@1.7.0.yaml
    - ../../infra/compose/docker-compose.yml
---

# 0122. Tenants read run history, usage and audit only from PostgreSQL under RLS; telemetry carries identifiers only, and Langfuse is an operator tool

Numbered in the block 0100-0199 reserved for Studio (ADR-0100 records the block). It pairs with
ADR 0121, which owns the usage ledger whose screens and retention this ADR also covers.

## Context

- A builder needs to see what a run did, step by step, and the test panel needs per-step results.
  Nothing tenant-facing holds that today. Checkpoints are serialized state bound to LangGraph's
  internals, unmasked and deleted after the run; traces are sampled and sit in a backend with no
  tenant access control.
- Langfuse runs in compose on floating major tags (`infra/compose/docker-compose.yml:532`, `:563`)
  beside ClickHouse 24.8 (`:510`), although `CLAUDE.md:128-129` says to pin versions. Langfuse's
  open-source edition has no RLS, data retention, server-side masking or project roles; those are
  Enterprise features (https://langfuse.com/self-hosting/license-key, fetched 2026-10-22).
- Seven `dw_*` metrics are declared and never emitted (`dw_observability/metrics.py:12-22`), which
  a name grep cannot see (`failure-modes.md` #0). Usage spans set the deprecated `gen_ai.system`
  (`dw_agent_runtime/adapters/telemetry_usage.py:60`). The GenAI conventions are all at
  "Development" status and moved to their own repository
  (https://opentelemetry.io/docs/specs/semconv/gen-ai/, fetched 2026-10-22).
- The audit log cannot be filtered by action, actor or run, and the `audit_export` feature that
  plans grant (`dw_platform/application/entitlement.py:33`) is read by no production code.
- The retention policy grounds the audit term in Decree 13/2023
  (`configs/policies/retention@1.7.0.yaml:116-118`), no longer in force since the PDPL and Decree
  356/2025/ND-CP took effect on 2026-01-01.

## Decision

1. **Telemetry through one mapping module.** `dw_observability/semconv.py` owns every span name,
   attribute key and GenAI metric name, pinned to one commit of
   `open-telemetry/semantic-conventions-genai` (`GENAI_SEMCONV_COMMIT`); a contract test runs the
   gateway, middleware, executor and runner against a recording port and fails on any emitted name
   outside the pinned snapshot. The span tree is real: `invoke_workflow`, `dw.node` per node
   attempt, `invoke_agent`, `chat` opened before the model call, `execute_tool`, and `retrieval`
   without query text. Spans and metrics carry identifiers only (tenant, workspace, run, node,
   version, cost, price-book version), never a user id and never content; per-tenant numbers come
   from the usage ledger, not metric labels. One W3C trace runs from the browser through the API,
   `platform.outbox_events` (a new `trace_parent`) and the worker, and logs are JSON lines limited
   to an allow-list of identifier fields.
2. **Operator metrics keep their names.** `dw_*` Prometheus names stay the operator contract. Of
   the seven unemitted metrics, `dw_run_duration_seconds`, `dw_tool_call_total`,
   `dw_approval_wait_seconds` and `dw_node_failure_total` get emitters, and
   `dw_retrieval_hit_rate`, `dw_human_intervention_rate` and `dw_task_success_rate` are deleted; an
   AST test fails any declared name that has no emitter.
3. **Langfuse is an operator tool.** Self-hosted in Vietnam and pinned by digest, moving to v4 with
   ClickHouse 25.12 or later before v3 security patches end in January 2027
   (https://langfuse.com/self-hosting/upgrade/upgrade-guides/upgrade-v3-to-v4, fetched 2026-10-22);
   reached only through the operators' sign-in, never a tenant realm. One span processor adds the
   Langfuse keys and drops `user.id` and every content attribute, so no other code knows Langfuse.
4. **Run history is a tenant-facing product store.** `platform.run_steps`, partitioned by month on
   `started_at` with a DEFAULT partition and tenant RLS on every partition, holds one run step per
   `node`, `model_call`, `tool_call`, `approval` or `sub_run`, written through `StepRecorderPort`.
   From the migration that creates it, a step carries `attempt` (an integer of at least 1, held by
   a CHECK), `port` (the branch out that the step took: a `switch` branch key, an approval's
   decision lane or the error lane) and `child_run_id` (a composite foreign key
   `(tenant_id, child_run_id)` to `platform.worker_runs`, its `ON DELETE` declared, indexed),
   beside `lane_path` and `iteration_path`; a parallel lane is named by its `lane_path`, so no
   `branch_key` repeats it (V4.36, H-11). A step that waits has its row from the moment it parks,
   so `/runs/[id]`, drawn as a tree (antd `Tree`), shows where a run waits and why it is held.
   Every `reason_code` and `error.code` that workflow-engine, the lanes and the doors that take
   runs write has its Vietnamese label in one catalogue, fragments `configs/copy/run_reason_codes.d/<spec>.yaml`
   that each spec adds in the change that writes the code, merged by telemetry-and-audit's loader and pinned by the
   hash of the set, beside decision 6's action catalogue, and a test fails a code the catalogue lacks, codes a node
   type returns included (H-12, H-21).
   Payloads are redacted at write (secrets and credential references dropped, `sensitive` fields
   masked, each decision recorded) and masked again at read by the viewer's field permissions
   (ADR 0106). Previews up to 4 KB stay inline; larger bodies are stored by reference under
   `tenants/{tenant_id}/workspaces/{workspace_id}/run-steps/`. `GET /api/v1/runs` and
   `GET /api/v1/runs/{id}/steps` serve it; a payload needs `runs.read_payloads` and every payload
   view is audited as `run.payload.viewed`. A holder of `studio.workflows.test` reads the steps and
   the detail of a `simulate` run they requested (`requested_by`), while a `live` run still needs
   `runs.read` and field security applies as everywhere; without `runs.read`, another person's run
   and a `live` run answer 404 as if absent, as another tenant's run always does. In W1
   `GET /api/v1/runs` stays behind `runs.read`, and a builder reaches their simulated run by the
   id the `test-runs` route returns (V4.41, H-17). Builder test results and quality gate evidence
   are read from it; neither keeps a store of its own. No run starts again from one of a past
   run's steps: "Chạy tách từ bước" (Fork from step) is gone, since running past steps again
   would resend their effects under new keys; "Chạy lại mô phỏng" (W2) starts a new `simulate` run
   of the same pinned version with the same input, and "Chạy tiếp từ Bước lỗi" continues a run in
   place (H-13).
5. **Content capture stays with the tenant, briefly (W2).** A tenant may opt in through the audited
   policy `telemetry.content_capture`: model messages and tool arguments of `model_call` steps are
   kept by reference in that tenant's run history for at most 7 days, readable only by holders of
   `runs.read_content` in the tenant, never by operators or support staff. A span only ever
   carries a reference.
6. **Audit becomes queryable and exportable.** `GET /api/v1/audit/events` gains server-side filters
   (action, actor, resource, run, and a window of at most 93 days, default 7) over a new index on
   the partitioned parent, `ix_audit_events_action`, and the one run index,
   `platform.audit_events (tenant_id, run_id, occurred_at)`, which app-standards 03 owns. One action
   catalogue, fragments `configs/copy/audit_actions.d/<spec>.yaml` merged and hashed the same way (H-21), gives every
   action its Vietnamese label, and
   an AST test fails an emitted action the catalogue lacks. Studio configuration changes audit
   before and after values as identifiers and numbers, never business data. An audit export
   (`POST /api/v1/audit/exports`, permission `audit.export`, rows in `platform.audit_exports`,
   written by the worker lane `audit_export`) is gated by the `audit_export` feature, its first
   reader.
7. **One retention policy, one owner, a remover for every store.** The policy is one fragment per
   store, `configs/policies/retention.d/<schema>.<table>.yaml` (a store that is not a table takes a
   prefixed name, such as `objects.run_step_payloads.yaml`), each holding the fields of today's
   keyed entry (the term, the remover and the `enforced` gate), and the release manifest pins the
   hash of the fragment set in place of a file's semver, so a compliance question gets one answer,
   the set a deployment pinned (V4.31, H-1). telemetry-and-audit owns the fragments' format and the
   retention lane (V4.21). Its ticket 01, the spec's earliest, ships the format, the loader of
   `platform.retention_terms` with its tests (telemetry-and-audit R5.9-R5.12), the term reader
   `platform.retention_term_days(text)` and the coverage test that every `append_only` store has a
   fragment, and it adds the `platform.audit_events` fragment and removes studio-skeleton/01's
   provisional mapping of `retention@1.7.0`; its ticket 03 keeps the lane and the slice's purge
   functions. Each ticket that registers a store adds that store's fragment in the same change, so
   the catalog test that every registered table has a term (studio-skeleton R3.7), which reads the
   fragment set, passes from the registration on, and no chain of tickets waits on one file's
   versions. A store that ships later brings its fragment with it, the per-tenant analytics store
   of ADR-0127 (Accepted) included (W3). The terms are provisional data, UNVERIFIED until counsel
   confirms them before shadow runs; counsel changes a number by changing its fragment, which the
   next release pins in the set's new hash, never with code (DO-52 (a)). A narrow purge function
   that clears or deletes rows, such as the two below for tool outputs and for conversations, takes
   no argument, so no caller can widen it, and reads its term from `platform.retention_terms`
   (`schema.table` and term, no tenant), which the provisioner loads at deploy from the fragment
   set the deployment pins and `dw_app` may only read; a function whose row is missing fails and
   deletes nothing (`failure-modes.md` #7), a test fails when that table and the pinned set differ
   (`failure-modes.md` #2), and only `platform.drop_expired_partitions` below takes its cutoffs from
   the lane. Run steps keep 30 days, as YC88 asks, so a lane deletes them: dropping a monthly
   partition would keep rows for 30 to 61 days. Unfinished runs are never touched, and each row
   below has a remover, a lane that reads its term (YC88), and a test.

| Store                                                                  | Term                                                                                     | Remover                                                     |
| ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| usage events (`platform.usage_events`)                                 | 395 days                                                                                 | DROP PARTITION                                              |
| usage rollups (`platform.usage_daily`)                                 | 760 days                                                                                 | lane DELETE                                                 |
| `platform.budget_counters`                                             | 395 days (13 months) after the window ends                                               | lane DELETE                                                 |
| `platform.budget_leases`                                               | 30 days after close                                                                      | lane DELETE                                                 |
| run steps (`platform.run_steps`)                                       | 30 days (YC88)                                                                           | lane DELETE                                                 |
| step payload objects                                                   | 30 days                                                                                  | lane deletes objects                                        |
| run payload columns (`input`, `result`, `error`)                       | 90 days after terminal                                                                   | lane clears                                                 |
| run rows (`platform.worker_runs`)                                      | 395 days after terminal, skipping runs that memory references                            | lane DELETE                                                 |
| tool outputs (`platform.tool_executions.output`)                       | 30 days, read from `platform.retention_terms`                                            | lane clears through a no-argument SECURITY DEFINER function |
| Langfuse data                                                          | 30 days                                                                                  | mechanism open                                              |
| inbound events (`studio.inbound_events`)                               | 30 days                                                                                  | lane DELETE                                                 |
| trigger deliveries (`studio.trigger_deliveries`)                       | 90 days                                                                                  | lane DELETE                                                 |
| checkpoints                                                            | 24 hours after the run ends                                                              | lane DELETE                                                 |
| inbound event dedupe keys                                              | 72 hours                                                                                 | lane DELETE                                                 |
| contact suppressions (`platform.contact_suppressions`, address hashes) | while the tenant is a customer; only offboarding or a data subject's request removes one | offboarding purge, data-subject erasure                     |
| conversations (`studio.conversations`, `studio.conversation_messages`) | 90 days (DO-52), read from `platform.retention_terms`                                    | lane through a no-argument SECURITY DEFINER function        |
| audit log (`platform.audit_events`)                                    | 1095 days, unchanged                                                                     | DROP PARTITION                                              |

The lane deleting inbound events skips one that a `queued` run still points to or that a freeze
holds, and counts the held ones on a metric: a freeze has no time limit (ADR 0120 decision 7), and a
held event's sender was already answered 2xx. `dw_app` holds no UPDATE on `platform.tool_executions`
(runtime-hardening R6.3), so the lane clears `output` through a narrow SECURITY DEFINER function
that takes no argument, reads its term from `platform.retention_terms` and nulls that one column
past it. Conversation messages are append-only for `dw_app` and point at their conversation through
a composite foreign key `ON DELETE RESTRICT` (ADR 0117 decision 6), so the lane removes expired
conversations through one narrow SECURITY DEFINER function, `studio.purge_expired_conversations()`,
owned by compliance-pdpl 06. It takes no argument, so no caller can widen it to recent rows, as
`platform.prune_notifications()` does
(`db/migrations/versions/855ae928c3fa_platform_in_app_notifications.py:28-29`), and it reads its
term, the `studio.conversation_messages` row of `platform.retention_terms`, so a new number from
counsel reaches it with the next pinned fragment set and no code; like every Studio function it revokes
all from PUBLIC and grants EXECUTE to the role the lane calls it as (ADR-0100 decision 4). In every
tenant it deletes the messages created before the cutoff that term gives, then the conversations
that have no message left and whose last activity is before it, and the lane audits as itself
(`system:<lane>`, ADR 0011) with the row counts. The DROP PARTITION rows go through
`platform.drop_expired_partitions(cutoffs jsonb)`, one cutoff per parent read from its fragment,
which usage-and-limits 02 owns in W1.

## Alternatives considered

- **Tenant-facing Langfuse.** Rejected: content in a third-party store without per-tenant RLS, and
  operators could read runs, which ADR 0024 forbids (support grants carry no `runs.` permission).
- **Content in spans.** Rejected: PDPL exposure in a backend with no tenant access control.
- **Run history read from checkpoints.** Rejected: a format bound to LangGraph's internals,
  unmasked, and deleted 24 hours after the run.
- **An auto-instrumentor, or `opentelemetry-util-genai` as the emitter.** Rejected: double spans,
  tenant attributes taken from wherever the library finds them, and metric names that already lag
  the spec (measured on the 1.2b0 wheel on 2026-10-22).

## Consequences

- `telemetry-and-audit` owns `platform.run_steps`, `StepRecorderPort`, the retention fragments'
  format with `platform.retention_terms`, its loader and the tests that hold the table, the pinned
  set and the registered stores together (its ticket 01, H-1), decision 6's action catalogue,
  which its ticket 03 creates together with the AST test, and the reason-code catalogue (H-12);
  `workflow-builder-ui` and `agent-lifecycle` read steps instead of storing their own results.
- Migrations: `platform.run_steps` (monthly partitions made by `platform.ensure_time_partitions`,
  RLS enabled and forced on parent, DEFAULT and each partition, `attempt`, `port` and
  `child_run_id` in its creating revision), `platform.audit_exports`,
  `platform.retention_terms` (SELECT only for `dw_app`), `platform.outbox_events.trace_parent` and
  `ix_audit_events_action`; the run index on `platform.audit_events` is app-standards 03's, and
  telemetry-and-audit 02 waits for it.
- Tests that must exist, each red with its guard removed: the semconv contract test and the AST
  emitter test; a log test that fails on an email-shaped value or a query string; cross-tenant
  negative tests on `/api/v1/runs` and the steps route; a builder holding only `studio.workflows.test`
  reading the steps of a `simulate` run they requested, while another person's run and a `live`
  run answer them 404 (V4.41); a viewer without read on a `sensitive` field sees it masked in a
  payload; the Langfuse processor drops `user.id` and content; a step row with an `attempt` below
  1 refused, a waiting step's row present from the moment it parks, and a `reason_code` or
  `error.code` without a label failing the catalogue test (V4.36, H-12); one test per retention
  row proving its remover runs, with
  `test_the_pinned_retention_policy_promises_only_classes_code_can_assign` changed on purpose;
  `platform.retention_terms` holding a term other than the pinned fragment set's failing its test;
  every `append_only` store holding a fragment, the coverage test turning red when one is removed
  (H-1).
- Harder: every run writes step rows and objects; a run older than its term can no longer be
  inspected; operators debugging a tenant's run see identifiers only, and any operator need to see
  content would be a new decision, since ADR 0024 stays as it is.

### Contradictions and divergences

- Keeps `CLAUDE.md:127` ("optional Langfuse") and narrows it to an operator-only tool; no
  contradiction.
- _Contradicts `configs/policies/retention@1.7.0.yaml:116-118`, which grounds the audit term in
  Decree 13/2023, but worth reopening because that decree no longer governs: the citation is
  re-based on the PDPL and Decree 356/2025/ND-CP once counsel names the article (DO-52)._
- Leaves `docs/adr/0024-customer-granted-support-access.md` unchanged: its decision 6 (`:64-70`)
  keeps `runs.` permissions out of support grants, so captured content stays out of staff reach.
- si-platform: aligns with si-platform `docs/adr/0039-structured-logs-to-loki-ids-only.md` (JSON
  logs with identifiers only, `traceparent` from browser to worker), re-derived here and keeping the
  OTLP span export this repository already has; diverges from si-platform
  `docs/adr/0044-approval-runs-narrowed-by-the-record-workspace-history-append-only-unpartitioned.md`,
  because step volume is unbounded (`CLAUDE.md:294`) and D1's workspace tree is narrowed in
  queries rather than by a workspace RLS boundary.

## Open

1. **DO-52, counsel and Đạt.** Retention terms, and erasure of `user_id` in the usage ledger and
   run history. DO-52's own proposal keeps terminal run rows 180 days and tool outputs with the
   run, where decision 7 says 395 days and 30 days; counsel's answer settles both. Partly answered
   2026-10-23 (DO-52 (a)): decision 7's table is the provisional set, its own numbers standing where
   it names a store and DO-52's filling the stores it lacked, plus the two rows it was missing
   (contact suppressions, conversations). Still with counsel: the final terms and the erasure of
   `user_id`. Answered 2026-10-24 by Đạt for the conversation term: 90 days, provisional and
   UNVERIFIED like the rest (DO-52).
2. **DO-51, counsel and the requester.** Is content capture allowed, who enables it, and for how
   long (at most 7 days here)? Answered 2026-10-23 (DO-51.1 (a)): allowed as decision 5 says, in
   W2, the tenant opting in, audited, for at most 7 days and read only within the tenant; counsel
   only confirms the processing notice to leads.
3. **DO-51, counsel and the requester.** May tenant admins see usage per named user (behind
   `usage.read` at tenant depth)? Answered 2026-10-23 (DO-51.2 (c)): not in W1, where usage groups
   by workspace, agent, workflow and purpose only; per named user in W2 with YC79, once counsel
   confirms the notice to employees.

## Acceptance (2026-10-23)

Accepted by Đạt on 2026-10-23 with these amendments from the decision brief:

- Decision 5: content capture is W2 (DO-51.1 (a)).
- Decision 6: one run index on `platform.audit_events`, owned by app-standards 03, replaces
  `ix_audit_events_run` (OPS-b).
- Decision 7: one owner of the retention file's format (telemetry-and-audit), each ticket that
  registers a table releasing a new version; the terms are provisional versioned data that counsel
  changes by a new version; run steps go from 90 to 30 days by lane (YC88); rows added for trigger
  deliveries, contact suppressions and conversations (DO-52 (a)).
- Open: DO-52 partly answered; both DO-51 questions answered.

## Amendments (2026-10-24)

Amended by Đạt on 2026-10-24, who accepted every recommendation the second consistency check left
open:

- Decision 7: telemetry-and-audit owns the file's format (one entry per `schema.table`) and its
  lane, and each ticket that registers a table adds that table's term in the same change.
- Decision 7 and Open 1: conversations are kept 90 days, provisional and UNVERIFIED (DO-52;
  H:compliance-pdpl:R5.1~requirements.md:419).
- Decision 7: `platform.budget_counters` is kept 13 months, provisional and UNVERIFIED (ADR 0121;
  D:ADR-0121~usage-and-limits:R5.7).
- Decision 7: tool outputs are cleared through a narrow SECURITY DEFINER function, since `dw_app`
  holds no UPDATE on `platform.tool_executions` (H:ADR-0122~runtime-hardening:R6.3).
- Decision 7: the lane skips inbound events a freeze holds and counts them, a freeze having no time
  limit (B:agent-lifecycle:R7.2~telemetry-and-audit:R5.5).
- Decision 7: DROP PARTITION goes through `platform.drop_expired_partitions(cutoffs jsonb)`, which
  usage-and-limits 02 owns in W1.
- Third consistency check (round 4): decision 7 and the Acceptance line drop the numbers 1.8.0 and
  1.9.0, since every ticket that registers a table releases a new version in telemetry-and-audit's
  format, and decision 7 names the chain of tickets that edit the file, usage-and-limits/02's version
  being the first keyed by `schema.table` (F:ADR-0122~telemetry-and-audit:spec); the chain is V4.P1, the
  planner's provisional call, and if it is wrong the file splits per table and decision 7 changes.
- Third consistency check (round 4), second pass, the planner's provisional calls: decision 7's chain
  under V4.P1 starts at usage-and-limits/02, and studio-skeleton/01, which registers
  `platform.audit_events` first, edits no file but reads that term from `retention@1.7.0` through a
  mapping that usage-and-limits/02 removes, the one exception, stated in ADR-0100 decision 7 too (if
  this head is wrong, studio-skeleton/01 releases the first version with `platform.audit_events`
  keyed by `schema.table`, and usage-and-limits/02 adds only its own tables); conversations leave
  through `studio.purge_expired_conversations`, a narrow SECURITY DEFINER function of
  compliance-pdpl 06, since their messages are append-only for `dw_app` and the messages' foreign key
  to their conversation is `ON DELETE RESTRICT` (if it is wrong, `dw_app` deletes conversations
  through a cascading foreign key and the messages stop being append-only).
- Third consistency check (round 4), third pass, the planner's provisional calls: decision 7's purge
  function takes no argument and holds the 90-day term itself, as `platform.prune_notifications()`
  does, so no caller can widen it to recent rows, with a test that fails when that term and the
  retention policy's `studio.conversation_messages` row differ (`failure-modes.md` #2), and it
  removes the conversations that have no message left and whose last activity is before the cutoff
  (if it is wrong, the function takes the cutoff as its argument again and the lane reads it from the
  policy); Consequences name telemetry-and-audit, through its ticket 03, as the owner of decision 6's
  action catalogue and its AST test, which no ticket created before.
- Third consistency check (round 4), sixth pass, Đạt's V4.21: counsel's terms reach the narrow purge
  functions through `platform.retention_terms`, which the provisioner loads at deploy from the
  pinned policy version and `dw_app` only reads, with a test that fails when the table and the
  pinned file differ, telemetry-and-audit owning the table, its loader and the test; every narrow
  function that clears or deletes rows, the conversation and tool-output functions among them, takes
  no argument and reads its own term there, failing when its row is missing, and
  `platform.drop_expired_partitions` alone still takes its cutoffs from the lane. This replaces the
  third pass's 90-day term held inside the conversation function, a number only code could change,
  against decision 7's rule that counsel changes a number with a new policy version (DO-52 (a)).

## Amendments (2026-10-25)

Amended by Đạt on 2026-10-25, who accepted the recommendation on each of the twelve decisions owed
(V4.30-V4.41), eleven from the answer to ChatGPT's architecture review and one on a builder's read
of simulated runs, applied with the planner's provisional calls H-1-H-18:

- Third consistency check (round 4), eighth pass, Đạt's V4.31, V4.36 and V4.41 and the planner's
  provisional calls H-1, H-11, H-12, H-13 and H-17: decision 7's policy is one fragment per store
  under `configs/policies/retention.d/`, the release manifest pinning the set's hash, each ticket
  that registers a store adding its fragment in the same change, with telemetry-and-audit keeping
  the format and the lane and its ticket 01 shipping the format, the loader, the term reader and the
  drift and coverage tests, the `platform.audit_events` fragment and the removal of
  studio-skeleton/01's mapping of `retention@1.7.0`; this replaces the one versioned file and the
  chain of tickets that the lines of 2026-10-24 name under V4.P1 (if H-1 is wrong, one versioned
  file with that chain). Decision 4 gives `platform.run_steps` `attempt`, `port` and `child_run_id`
  from its creating migration and no `branch_key`, a row for a step that waits, the run drawn as a
  tree with where it waits and why, one reason-code catalogue with Vietnamese labels, a builder's
  read of the `simulate` runs they requested, and no Fork from a step, "Chạy lại mô phỏng" (W2)
  taking its place (if H-11 is wrong, `branch_key` is the last element of `lane_path`; if H-12 is
  wrong, the labels sit in workflow-engine's table of `wf.*` codes; if H-13 is wrong, Fork stays in
  W2 running `simulate` only; if H-17 is wrong, `/runs` shows a holder of `studio.workflows.test`
  the simulated runs they requested). Consequences follow.
- Pass h, after wave 1 (H-21): the action and reason-code catalogues are fragments per spec, merged and hashed like
  decision 7's retention fragments, so no chain of tickets edits one catalogue file.
