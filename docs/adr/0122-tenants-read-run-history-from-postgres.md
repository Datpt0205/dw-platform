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
   Payloads are redacted at write (secrets and credential references dropped, `sensitive` fields
   masked, each decision recorded) and masked again at read by the viewer's field permissions
   (ADR 0106). Previews up to 4 KB stay inline; larger bodies are stored by reference under
   `tenants/{tenant_id}/workspaces/{workspace_id}/run-steps/`. `GET /api/v1/runs` and
   `GET /api/v1/runs/{id}/steps` serve it; a payload needs `runs.read_payloads` and every payload
   view is audited as `run.payload.viewed`. Builder test results and quality gate evidence are read
   from it; neither keeps a store of its own.
5. **Content capture stays with the tenant, briefly (W2).** A tenant may opt in through the audited
   policy `telemetry.content_capture`: model messages and tool arguments of `model_call` steps are
   kept by reference in that tenant's run history for at most 7 days, readable only by holders of
   `runs.read_content` in the tenant, never by operators or support staff. A span only ever
   carries a reference.
6. **Audit becomes queryable and exportable.** `GET /api/v1/audit/events` gains server-side filters
   (action, actor, resource, run, and a window of at most 93 days, default 7) over a new index on
   the partitioned parent, `ix_audit_events_action`, and the one run index,
   `platform.audit_events (tenant_id, run_id, occurred_at)`, which app-standards 03 owns. One action
   catalogue, `configs/copy/audit_actions@1.0.0.yaml`, gives every action its Vietnamese label, and
   an AST test fails an emitted action the catalogue lacks. Studio configuration changes audit
   before and after values as identifiers and numbers, never business data. An audit export
   (`POST /api/v1/audit/exports`, permission `audit.export`, rows in `platform.audit_exports`,
   written by the worker lane `audit_export`) is gated by the `audit_export` feature, its first
   reader.
7. **One retention policy, one owner, a remover for every store.**
   `configs/policies/retention@1.8.0.yaml` replaces 1.7.0, and telemetry-and-audit owns the file:
   compliance-pdpl adds its stores' rows in 1.9.0, after it. The terms are provisional, versioned
   data, UNVERIFIED until counsel confirms them before shadow runs; counsel changes a number with a
   new policy version, never with code (DO-52 (a)). Run steps keep 30 days, as YC88 asks, so a lane
   deletes them: dropping a monthly partition would keep rows for 30 to 61 days. Unfinished runs are
   never touched, and each row below has a remover, a lane that reads its term (YC88), and a test.

| Store                                                                  | Term                                                                                     | Remover                                 |
| ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | --------------------------------------- |
| usage events (`platform.usage_events`)                                 | 395 days                                                                                 | DROP PARTITION                          |
| usage rollups (`platform.usage_daily`)                                 | 760 days                                                                                 | lane DELETE                             |
| `platform.budget_leases`                                               | 30 days after close                                                                      | lane DELETE                             |
| run steps (`platform.run_steps`)                                       | 30 days (YC88)                                                                           | lane DELETE                             |
| step payload objects                                                   | 30 days                                                                                  | lane deletes objects                    |
| run payload columns (`input`, `result`, `error`)                       | 90 days after terminal                                                                   | lane clears                             |
| run rows (`platform.worker_runs`)                                      | 395 days after terminal, skipping runs that memory references                            | lane DELETE                             |
| tool outputs (`platform.tool_executions.output`)                       | 30 days                                                                                  | lane clears                             |
| Langfuse data                                                          | 30 days                                                                                  | mechanism open                          |
| inbound events (`studio.inbound_events`)                               | 30 days                                                                                  | lane DELETE                             |
| trigger deliveries (`studio.trigger_deliveries`)                       | 90 days                                                                                  | lane DELETE                             |
| checkpoints                                                            | 24 hours after the run ends                                                              | lane DELETE                             |
| inbound event dedupe keys                                              | 72 hours                                                                                 | lane DELETE                             |
| contact suppressions (`platform.contact_suppressions`, address hashes) | while the tenant is a customer; only offboarding or a data subject's request removes one | offboarding purge, data-subject erasure |
| conversations (`studio.conversations`, `studio.conversation_messages`) | a provisional term Đạt sets, owed                                                        | lane DELETE                             |
| audit log (`platform.audit_events`)                                    | 1095 days, unchanged                                                                     | DROP PARTITION                          |

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

- `telemetry-and-audit` owns `platform.run_steps`, `StepRecorderPort` and the retention policy;
  `workflow-builder-ui` and `agent-lifecycle` read steps instead of storing their own results.
- Migrations: `platform.run_steps` (monthly partitions made by `platform.ensure_time_partitions`,
  RLS enabled and forced on parent, DEFAULT and each partition), `platform.audit_exports`,
  `platform.outbox_events.trace_parent` and `ix_audit_events_action`; the run index on
  `platform.audit_events` is app-standards 03's, and telemetry-and-audit 02 waits for it.
- Tests that must exist, each red with its guard removed: the semconv contract test and the AST
  emitter test; a log test that fails on an email-shaped value or a query string; cross-tenant
  negative tests on `/api/v1/runs` and the steps route; a viewer without read on a `sensitive`
  field sees it masked in a payload; the Langfuse processor drops `user.id` and content; one test
  per retention row proving its remover runs, with
  `test_the_pinned_retention_policy_promises_only_classes_code_can_assign` changed on purpose.
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
  because step volume is unbounded (`CLAUDE.md:288`) and D1's workspace tree is narrowed in
  queries rather than by a workspace RLS boundary.

## Open

1. **DO-52, counsel and Đạt.** Retention terms, and erasure of `user_id` in the usage ledger and
   run history. DO-52's own proposal keeps terminal run rows 180 days and tool outputs with the
   run, where decision 7 says 395 days and 30 days; counsel's answer settles both. Partly answered
   2026-10-23 (DO-52 (a)): decision 7's table is the provisional set, its own numbers standing where
   it names a store and DO-52's filling the stores it lacked, plus the two rows it was missing
   (contact suppressions, conversations). Still with counsel: the final terms and the erasure of
   `user_id`; still owed by Đạt: the conversation term.
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
- Decision 7: one owner of the retention file (telemetry-and-audit, 1.8.0; compliance-pdpl adds
  1.9.0); the terms are provisional versioned data that counsel changes by a new version; run steps
  go from 90 to 30 days by lane (YC88); rows added for trigger deliveries, contact suppressions and
  conversations (DO-52 (a)).
- Open: DO-52 partly answered; both DO-51 questions answered.
