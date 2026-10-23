---
status: Proposed (direction chosen by the requester on 2026-10-22 and 2026-10-23; not yet reviewed by Đạt)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/usage-and-limits/spec.md
    - ../../db/migrations/versions/0013_drop_model_usage_ledger.py
    - ../../db/migrations/versions/2b5ff2bceb06_tenant_daily_spend_guard.py
    - ../../packages/python/dw_platform/src/dw_platform/application/entitlement.py
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/model/budget.py
---

# 0121. A per-call usage ledger returns as metering with named readers, and every hard limit is a Postgres lease reserved at run admission across one scope chain

Numbered in the block 0100-0199 reserved for Studio (ADR-0100 records the block). It reverses an
owner decision: migration `aefe7c1f5d9b` dropped the per-call ledger on 2026-09-21, misdescribed
as invoicing evidence and read only by a spend cap and an admin dashboard, because "Đạt asked for
the whole feature gone" (`0013_drop_model_usage_ledger.py:3-14`). The first point stays true,
named readers answer the second, and the migration bringing it back waits for Đạt (DO-21).

## Context

- **What bounds a tenant today.** `runs_per_day` from `DEFAULT_PLANS`
  (`dw_platform/application/entitlement.py:17-36`) on a UTC day (`dw_agent_runtime/allowance.py:63`),
  an in-process `RunBudgetLedger` bounding one run in one worker
  (`dw_agent_runtime/model/budget.py:61-68`), and `platform.tenant_daily_spend_guard`, "not a
  per-call event log" (`2b5ff2bceb06_tenant_daily_spend_guard.py:14-17`). Prices sit on model
  routes (`dw_agent_runtime/model/profiles.py:54-55`).
- **What Studio needs (D6).** Limits and usage per workspace, agent, workflow and user, a usage
  dashboard and reconciliation, embedding, rerank and code sandbox included. A daily total
  attributes none of it; traces are sampled (`.claude/skills/reviewing-feature-security/SKILL.md:114`);
  a check after the call "is accounting, not a ceiling" (`:129-131`), as N parallel runs that each
  see money left all spend it; the spend ceiling once missed the agent loop (`failure-modes.md` #5).

## Decision

1. **The usage ledger.** `platform.usage_events` holds one usage event per metered call: `chat`,
   `embeddings`, `rerank`, `extraction`, `transcription`, `sandbox_exec`, `server_tool`, connector
   units (the manifest's `usage_unit`, for example `zns_message`) and the reaper's
   `unsettled_estimate`. A row names tenant, workspace, run, `root_run_id`, lease, node, the agent
   or workflow version, `purpose` (`run`, `test_run`, `builder_assist`, `eval_offline`,
   `eval_online`, `ingestion`, `retrieval`, `compaction`, `memory`), `payer` (`platform`, or
   `tenant` for BYOM), tokens, units and `cost_usd` with its `cost_source`, never content. Monthly
   partitions with a DEFAULT one, RLS forced on each, append-only for `dw_app`, kept 13 months (395
   days). Settlement is idempotent (`id` and `occurred_at` set before the call, insert
   `ON CONFLICT DO NOTHING`). It meters consumption and is never invoicing evidence.
2. **Its readers ship with it** (`failure-modes.md` #1): lease settlement and the reaper;
   `GET /api/v1/runs/{run_id}/usage`; the `usage_rollup` lane feeding `platform.usage_daily`,
   `GET /api/v1/usage/summary` and the usage dashboard; the operator reconciliation aggregate
   `platform.usage_provider_daily(day)` (SECURITY DEFINER, by provider and model, no tenant ids);
   the evaluation cost bound `agent-lifecycle` reads from `eval_offline` and `eval_online` rows; and
   cost per workflow outcome over the runs of one `root_run_id` (fees a tenant pays a provider
   directly, such as ZNS on its own account, stay outside it).
3. **One price book.** `configs/pricing/price_book@<semver>.yaml`, pinned in the release manifest,
   prices every metered operation by effective-dated entries per provider, model and usage type,
   cache state, sandbox CPU seconds and server tool calls included. Tenant BYOM entries live in
   `platform.tenant_price_entries`, resolved like `TenantOverlay`: the tenant's own, else the
   platform's, never another tenant's. Model profiles lose their prices in the same change; history
   is never re-priced. When `settings.is_deployed`, a platform-paid route without a price refuses
   startup; a BYOM route may stay unpriced (`cost_source = 'unpriced'`, token limits only).
4. **One limit scope chain.** Every limit is a policy at one scope of the chain plan, tenant,
   workspace and each ancestor (D1), agent or workflow, user, run (a child run shares its root's
   lease); a run proceeds only while every scope in the chain with a policy passes. Kinds are `hard`
   and `soft` in v1, `approval` in v1.5. Behavioural limits (steps, model and tool calls, wall
   clock, per-run cost and tokens) live in the agent or workflow version, clamped by plan maxima;
   operational limits on money, tokens, runs and concurrency per window live in audited
   `platform.limit_policies` rows a tenant admin changes without republishing. A policy may name its
   purposes, so builder assistance, test runs and evaluations get caps of their own. Threshold
   alerts emit `usage.limit.threshold_crossed` once per policy, window and threshold.
5. **Hard money and token limits are leases.** At admission, in one database transaction, the
   runner locks the chain's `platform.budget_counters` rows in canonical order (scope rank, then id,
   so admissions cannot deadlock), counts runs and concurrent runs, and opens one
   `platform.budget_leases` row per root run for no more than every scope has left. The lease caps
   each model call's `max_tokens`; each call settles idempotently into the ledger and the lease;
   counters move only at admission, top-up, a 60-second heartbeat roll and close. A wait for a
   person releases the lease and the resume opens a new one. A `ReapTarget` on the reaper lane
   settles crashed runs' leases as `system:reaper` (ADR 0011). Code sandbox CPU seconds and
   concurrency use the same leases (ADR 0119).
6. **When a limit is hit.** At admission an interactive conversation turn is refused with
   `QuotaExceededError` (HTTP 429, `details.reason_code = limit_exceeded`, metric, scope, window
   and reset time); a queued trigger run waits for the window or a raised limit (ADR 0113), never
   dropped. Mid-run the run stops at the next model call, tool call or node boundary with
   `limit_exceeded` and no retry, executed effects kept and audited; never a silent downgrade.
7. **One owner, no back door.** `RunBudgetLedger`, `RunBudgetMiddleware`, `DailyAllowance`,
   `RuntimeSeam.budget` and `platform.tenant_daily_spend_guard` are replaced in the same slice by a
   new package, `packages/python/dw_usage`; the runtime declares `LimitsPort` and knowledge
   `UsageMeterPort`, wired at the composition root as `RunAllowancePort` is today.
   `MeteredModelGateway`, `LimitedChatModelFactory`, `MeteredEmbeddingPort` and `MeteredRerankPort`
   are the only model-reaching doors; import-linter forbids the concrete adapters elsewhere.
8. **Valkey holds rate, never money or concurrency.** `RateLimiterPort` keeps GCRA buckets keyed
   by tenant and workspace, a provider governor with fair shares per tenant by plan, and dispatch
   pacing; without Valkey it falls back to per-process buckets (limit divided by replicas).
9. **One plan catalogue, in the database.** `platform.plans` and a typed `platform.plan_limits` (no
   RLS, `dw_app` SELECT only; NULL means no limit, a missing row refuses, per-run maxima NOT NULL)
   replace `DEFAULT_PLANS` and the `quotas` jsonb. Windows follow the tenant's time zone (default
   `Asia/Ho_Chi_Minh`) through one function, `window_for(tenant_id, window_kind, at)`; the ledger
   is kept in USD.

### Provisional calls (agent, 2026-10-23: option (a) of DO-50 and DO-43, pending the requester)

- Windows are cut in the tenant's time zone; a hard limit hit mid-run stops the run.
- Builder assistance, test runs and evaluations count against the tenant's limits under separate
  purpose caps and not toward runs per day; only root runs count toward runs per day.
- BYOM tokens count only against caps the tenant sets, and a failing tenant model never falls back
  to a platform-paid route (ADR 0118). If any of these is wrong, only that rule changes.

## Alternatives considered

- **Keep the ledger removed.** Rejected: limits, the usage dashboard, the evaluation cost bound and
  reconciliation would have no source.
- **Counters in Valkey.** Rejected: Valkey is never a source of truth (`CLAUDE.md:60`); LiteLLM's
  budgets read a Redis counter on the hot path whose restart can under-read spend
  (https://docs.litellm.ai/docs/proxy/users, fetched 2026-10-22).
- **Check spend after the call.** Rejected: it overspends by one loop's length, the agent loop's
  gap; the same page says `disable_budget_reservation` lets concurrent requests exceed a budget.
- **A rate limiter per cluster.** Rejected: two answers to one question, two failure behaviours.
- **Prices on model profiles.** Rejected: one fact in many places (`failure-modes.md` #2), no price
  for embedding, rerank or the code sandbox, and providers price by date and cache state
  (https://ai.google.dev/gemini-api/docs/pricing, fetched 2026-10-22).

## Consequences

- Migrations, as new alembic revisions: `platform.usage_events` (DEFAULT partition, forced RLS,
  append-only grants), `platform.usage_daily`, `platform.limit_policies`, `platform.budget_counters`,
  `platform.budget_leases`, `platform.plan_limits`, `platform.tenant_price_entries`; the partition
  function takes an array of append-only parents; `platform.tenant_daily_spend_guard` is dropped and
  `platform.plans.quotas` retired once its data has moved.
- Tests, each shown red with its guard removed: `test_rls_coverage.py` and `test_privileges.py`
  cover the new tables (no UPDATE or DELETE on `usage_events` for `dw_app`); parallel admissions
  never exceed a small ceiling; each model-reaching door refuses without a lease; the reaper settles
  a killed run's lease; an unpriced platform-paid route refuses a deployed startup; a missing
  `plan_limits` row refuses; with Valkey stopped, money and concurrency limits still hold.
- Harder: two small writes per model call (to be measured); a resumed run can be stopped by an
  exhausted month; model profiles change shape; `test_only_the_platform_lanes_are_wired` changes;
  offboarding exports the ledger and never purges it; its `user_id` is personal data, so erasure
  needs a decision (DO-52). `usage-and-limits` lands before any deployed Studio run is admitted.

### Contradictions and divergences

- _Contradicts migration `aefe7c1f5d9b` (`0013_drop_model_usage_ledger.py:3`, `:16`), the guard
  of `2b5ff2bceb06_tenant_daily_spend_guard.py:14-17` and `DEFAULT_PLANS`, but worth reopening
  because Studio needs a per-call source, now shipped with its readers, and a code copy of the plan
  catalogue drifts (`failure-modes.md` #2)._ `configs/policies/retention@1.7.0.yaml:72-73` goes too.
- Generalises `CLAUDE.md:220-224` (the plan's limit enforced where a run begins, through
  `RunAllowancePort`) into the `LimitsPort` scope chain; the runner stays the place.
- _Contradicts `CLAUDE.md:163` (every tenant-scoped table has `workspace_id`) for the tenant-level
  `platform.limit_policies` and `platform.budget_counters`, but worth reopening because a workspace
  is one scope of the chain, as with `platform.policy_overrides`
  (`45dc1b5e0125_platform_policy_overrides.py:35-38`)._
- _Contradicts `dw_agent_runtime/adapters/langgraph_runner.py:255-257` (no limit refuses a
  resume), but worth reopening because money spent after a resume is new spend; runs per day is
  still not counted again._
- _Contradicts ADR-0011's "Not applied, on purpose" list naming spend-guard counters
  (`0011-a-background-lane-audits-as-itself.md:40-43`), but worth reopening because an expired
  lease settles spend against a tenant's limits, so the reaper audits it as itself._
- si-platform: re-derived, as si-platform has no ledger (si-platform
  `packages/python/platform/si_agent_runtime/src/si_agent_runtime/adapters/telemetry_usage.py`);
  ports the limiter of si-platform `packages/python/hosts/si_api/src/si_api/http/rate_limit.py` and
  the typed table of si-platform `db/si/migrations/0043_plan_limits.sql`; GCRA in Valkey is new.

## Open

1. **DO-21, Đạt.** Accept the per-call ledger, reversing `aefe7c1f5d9b`, with decision 2's readers?
2. **DO-59, the requester with Đạt.** Plan numbers for cost, tokens, concurrency, RPM and TPM, and
   the unit tenants see and set (a USD estimate in the pilot, credits before selling).
3. **DO-50, the requester.** Mid-run stop in v1, approval kind in v1.5, never a silent downgrade;
   who pays builder assistance, test runs and evaluations (provisional (a) above; DO-29, Đạt).
4. **DO-43, the requester.** Do BYOM tokens count against plan caps? Provisional (a) above.
5. **DO-49, Đạt.** Per-process rate buckets while Valkey is unreachable, rather than failing closed.
6. **DO-07, Đạt with the requester.** D11 gives every tenant configuration change a maker and a
   checker; whether that covers every `platform.limit_policies` change or only loosening is open.
