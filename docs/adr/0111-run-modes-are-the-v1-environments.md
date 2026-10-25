---
status: Accepted (Đạt, 2026-10-23; amendments from the decision brief applied)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/tenant-config/spec.md
    - ../../.claude/plans/studio/workflow-engine/spec.md
    - ../../.claude/plans/studio/tools-and-skills/spec.md
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py # RunContext, ToolDefinition
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py
---

# 0111. Environments in v1 are versions and a server-fixed run mode (live, test, simulate) inside one tenant, enforced where effects happen; a workspace is never an environment

Numbered in the block 0100-0199 reserved for Studio (ADR 0100 records the block). It rests on the requester's D1 (a
workspace is a business unit that owns data, so it cannot also be an environment), on stance S3 for the split between
v1 and v2, and on the provisional call on DO-26.

## Context

- **A builder must try a workflow without touching the world.** The pilot workflow (D4) scores a lead, writes a
  record, assigns it and messages the lead on Zalo or by email after an approval; the builder runs it before it is live,
  and the quality gate runs it many times (ADR 0120).
- **Nothing in a run says how real it is.** `RunContext`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:98-148`) and `platform.worker_runs`
  (`db/migrations/sql/0001_platform_baseline.sql:447-471`) carry no mode, the ToolExecutor performs every call policy
  allows (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:77-95`), and `tool_executions.status` has
  no CHECK (`0001_platform_baseline.sql:423`). Four places build a `RunContext`, the resume among them
  (`approval_flow.py:269` and `:382`, `apps/api/src/dw_api/bootstrap/container.py:211`,
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_usage.py:188`).
- **Providers' test modes cannot be the guard.** Events sent with Meta's `test_event_code` "are not dropped" and feed
  ad targeting (https://developers.facebook.com/docs/marketing-api/conversions-api/using-the-api); the Zalo ZNS API
  guide shows no test switch (https://zalo.solutions/business-message/guidelines/gui-api), and whether ZNS has a
  development mode is unverified (FOG-04). Both documented on 2026-10-22 (`.claude/plans/studio/discovery/research.md`
  section 14). LangGraph re-executes the nodes after the checkpoint a run is replayed from, so a replay re-fires
  effects (measured in planning on 2026-10-22).
- **Products give an environment its own data container** (Power Platform environments, HubSpot sandboxes;
  research.md section 14). The research recommended a sandbox workspace for v1 (`research.md:338`); under D1 a
  workspace sits in the business-unit tree and inside tenant-depth roles, and object definitions are tenant-wide
  (ADR 0107).

## Decision

1. **One typed run mode that fails safe.** `RunMode` (`live`, `test`, `simulate`) lives in `dw_kernel`, and its module
   joins `WATCHED_LITERALS` (`scripts/verify_invariants.py:109-112`) so that every value needs a reader.
   `platform.worker_runs.run_mode` is NOT NULL with a CHECK and no default (existing rows backfilled `live`).
   `RunContext.run_mode` defaults to `simulate`, the fail-safe value, as `autonomy_ceiling` fails closed
   (`contracts.py:141`), and every construction sets it, the resume included. The run manifest records it (ADR 0109).
2. **The server fixes it at admission, and it only gets safer.** The run request door (ADR 0113) sets it: triggers and
   manual runs of the live version are `live`; the test-run endpoint accepts only `test` or `simulate` (`live` is 422),
   and the builder starts only those; evaluations are `simulate`; a replay or a fork is `simulate` unless a holder of
   `runs.replay_live` asks for `live` in a dialog that names the effect nodes that will run; a child run takes
   `child_mode(parent, requested)`, the safer of the two (safest first: `simulate`, `test`, `live`). No caller picks
   `live`.
3. **Enforced where effects leave, never in a node.** In `simulate` the ToolExecutor executes only tools whose kind
   declares `simulate_safe` (read kinds, and platform tools with `side_effect_level = none`), the RecordService
   validates a write fully and returns the would-be record without persisting it (ADR 0107), the egress client refuses
   every purpose except `model` and read-only actions (`egress_blocked:run_mode`, ADR 0115), and reads and model calls
   run for real, under the tester's access (for a gate trial, the access of the principal the gate lane requests it as)
   intersected with the run's boundary and under the tester's allowance; the boundary of a root not live yet, a draft or
   a sealed candidate in its gate run, is the provisional one its run door derives (ADR 0103 decision 5), which no
   `live` run reads under. Every other tool call is an intercepted call: recorded in `tool_executions` with status
   `simulated` (that column's first CHECK), audited as `tool.simulated` with the reason, and answered with the node's or
   tool's mock output, validated against its output schema and shaped like the mocks of evaluation cases, or with a
   placeholder generated from the schema, marked `simulated: true`.
4. **`test` adds real messages to allowlisted people only.** It also executes connector actions whose kind declares
   `test_capable`, on test-enabled connections, to recipients on the test recipient allowlist: `studio.test_recipients`,
   tenant-wide normalised addresses (E.164, lower-case email, provider user id), expiring within 90 days and
   revocable; an empty list sends nothing. The egress client re-checks these rules. Internal effects, record writes
   included, are intercepted as in `simulate`, with nothing persisted in v1 (DO-26). A `critical` effect keeps its
   approval (CLAUDE.md:68-69), routed to the tester. Connector manifests declare `test_isolation` (`isolated`,
   `partial` or `none`; unknown is `none`) and, per messaging action, its recipient argument.
5. **A non-live run stays with its tester.** Its notifications, and any approval it opens, reach only the tester, in
   the app, never through a chat channel. A `human.approval` step of a `simulate` run, and of a `test` run from W2,
   waits for no real decider: its decision is simulated, taken from the test-run form (the tester chooses `approved`
   or `rejected`, the values workflow-nodes owns) or from the quality gate's evaluation case, audited
   `studio.step.approval.simulated`, and it never
   satisfies a `live` approval. In a mode other than `live` the ToolExecutor applies the run mode before a tool's
   approval policy, so a call it intercepts opens no approval and only a call that really executes meets its approval
   (decision 4). Spans, audit events and the usage ledger carry `run_mode`; business metrics exclude non-live runs and
   cost metrics include them (ADR 0121, ADR 0122).
6. **No environment container in v1.** Draft, submit and publish (ADR 0120) plus run modes are the v1 environments.
   Tenant-level changes (roles, tenant config versions, object schema) are not staged; they pass approval, version
   history and rollback (ADR 0104, ADR 0110, ADR 0107). A workspace is never an environment (D1, ADR 0102).
7. **v2 adds sandbox tenants (W3).** `platform.tenants.kind` is `production` or `sandbox`, linked by operator-created
   `platform.tenant_links`. A sandbox tenant is seeded from a `dw.package/v1` of production's live versions plus
   synthetic data only, and never runs `live`. Promotion is by package: requested in production, re-gated against
   production's dependency index, open runs and plan limits, approved by someone other than the requester (strict
   prefix `studio.promotion.`), imported by the lane `studio_promotion`, which carries out that recorded approval and
   so audits in the name of the person who approved the promotion, with `details.lane = studio_promotion`
   (ADR 0011), and published only when every required binding has a production value (ADR 0110).

## Alternatives considered

- **A sandbox workspace in v1** (the research's recommendation). Rejected: it needs per-workspace object definitions,
  contradicting S3, and D1 makes a workspace a business unit.
- **A client-chosen run mode.** Rejected: a caller could pick `live`.
- **Mode checks inside nodes.** Rejected: agent tool calls and workflow-as-tool would bypass them (failure-modes #5).
- **Real test records tagged and purged later.** Rejected: test data mixes into production data, and a purge that
  misses one leaves a made-up lead in a salesperson's queue.
- **Trusting providers' test modes.** Rejected by the Meta and Zalo evidence above.
- **An environment column on every table.** Rejected: every policy, unique key, foreign key and cache key changes, and
  one missing predicate leaks.
- **Refusing instead of intercepting in `test`.** Rejected: the test would stop at its first effect, where an
  intercepted call keeps it useful and visible.
- **A sandbox tenant in v1.** Rejected: provisioning, SSO, a per-tenant key, billing and a cross-tenant import lane are
  too much for the first release.

## Consequences

- tools-and-skills classifies `simulate_safe` and `test_capable` per tool kind (ADR 0116); connections-and-vault keeps
  test-enabled connections, the allowlist and the egress checks (ADR 0115); workflow-builder-ui and agent-lifecycle
  share one mock output shape; workflow-engine fixes the mode at the door (ADR 0113).
- Phasing: `simulate` with interception in the executor in W1 P0 (tenant-config/03); `test` with the allowlist and the
  egress check in W2; a run-scoped scratch for reading a run's own intercepted writes (FOG-60) in W3 (v1.5), and
  sandbox tenants in W3 (v2, decision 7).
- Tests, each shown red by removing its guard: a test run requested as `live` is 422; a `simulate` run of a workflow
  with a Zalo step sends nothing (a recording egress double sees no call); a child of a `simulate` run asking for
  `live` runs `simulate`; a `RunContext` built without a mode intercepts; a replay of a run that sent a message sends
  nothing; a `test` message to an address off the allowlist is intercepted; a resumed run keeps its mode.
- Harder: a schema change to a tenant-wide object cannot be rehearsed in v1 (custom-objects' gated rules and impact
  analysis mitigate); a workflow that creates a record and reads it back cannot be tested end to end until the scratch
  ships; test runs and evaluations still spend model tokens, paid from the tenant budget, under purpose caps from W2
  (DO-50, provisional; ADR 0121 decision 4); v2 adds the first cross-tenant write lane besides offboarding.
- The value `test` collides with the deployment profile `test` (CLAUDE.md:325-330): a different concept, kept apart by
  the typed `RunMode` and the glossary and never compared with the settings profile; deployment gates stay on
  `settings.is_deployed` (`apps/api/src/dw_api/settings.py:323`). Worth keeping because the UI says "Chạy thử", never
  the code value. Nothing else is contradicted: the policy shape of CLAUDE.md:198-207 is unchanged, and the research
  recommendation set aside above is planning, not a decision of record.
- si-platform: none; si-platform has no run modes. Our workspace is neither an RLS boundary nor an environment, unlike
  si-platform `docs/adr/0030-workspace-is-the-rls-boundary-accounts-are-tenant-wide.md` (ADR 0102 records that
  divergence).

## Open

1. **DO-26 (requester for the behaviour, Đạt for the name; before P1).** Provisional (agent, tạm theo khuyến nghị,
   2026-10-23, option (a)): a record write in a `test` run is intercepted like `simulate` and the run keeps its would-be
   writes, a run-scoped scratch follows in W3 (v1.5), and `test` keeps its name with a typed `RunMode`. If wrong: (b)
   real records tagged `test` need a purge lane and a filter in every list; (c) the run-scoped scratch is built now and
   the value becomes `trial`. Answered 2026-10-23: option (a); W1 opens `simulate` only, the test-run door answering
   422 to `test` until W2, the egress client refusing in `simulate` every purpose except `model` and read-only actions
   (decision 3, ADR 0115 decision 6), and the executor still intercepting a `test` run like `simulate` if one arrives
   (DO-26.1 (a)); `test` keeps its name with a typed `RunMode`, the UI saying "Chạy thử" (DO-26.2 (a)).
2. **DO-55 (counsel and requester, before P1).** Consent wording and validity for employees' contact data used as test
   recipients, and who may add them (proposed: tenant admins, 90 days).
3. **DO-62 (requester and counsel, before GA).** v2 sandbox tenants: billing and quota, who creates them (proposed:
   operators only) and what data they hold (proposed: synthetic only, since a masked copy of production is a new
   purpose under PDPL). Answered 2026-10-23: operators alone create them, they hold synthetic data only, and their
   quota is their own, never counted against the production tenant (DO-62 (a)); not urgent, since they are W3.
4. **FOG-60 (prototype)** for the run-scoped scratch through the records gateway, and **FOG-04 (research)** for
   whether ZNS has a test or development mode that would earn a `test_isolation` of `partial`.

## Acceptance (2026-10-23)

- Status Accepted by Đạt; the decisions are accepted as written, since the phasing already opens `simulate` only in
  W1 and `test` with its recipient list in W2 (DO-26.1 (a)). No `CLAUDE.md` line changes (`CLAUDE.md`,
  Environments, held as written at acceptance).
- Open 1 answered (DO-26.1 (a), DO-26.2 (a)) and Open 3 answered (DO-62 (a)); Open 2 waits until `test` opens in W2.

## Amendments (2026-10-24)

- Đạt accepted the open recommendations of the second consistency check; the status stays Accepted.
- Decision 5: a `human.approval` step of a `simulate` run, and of a `test` run from W2, takes a simulated decision
  from the test-run form or the gate's evaluation case, audited `studio.step.approval.simulated`, never satisfying a
  `live` approval; outside `live` the executor applies the run mode before a tool's approval policy (N2).
- Open 1: in `simulate` the egress client refuses every purpose except `model` and read-only actions, as decision 3
  and ADR 0115 decision 6 say, not every call of every mode but `live`
  (B:connections-and-vault:R3.5~tenant-config:R5.4); the run-scoped scratch is W3 (v1.5) in Open 1 and in
  Consequences alike.
- Third consistency check (round 4): decision 7's promotion import audits the person who approved the promotion,
  naming the lane in `details.lane = studio_promotion`, because the lane carries out that person's recorded decision
  (ADR 0011; `CLAUDE.md`, Agent and tool rules), no longer as `system:studio-promotion`
  (E:ADR-0111\~CLAUDE.md#agent-and-tool-rules, one of that check's CRITICAL rows); decision 5's simulated decision
  takes the values `approved` and `rejected` that workflow-nodes owns (B:agent-lifecycle:R4.7\~workflow-nodes:R9.9).
- Third consistency check (round 4), second pass: Consequences place the purpose caps that test runs and
  evaluations spend under in W2, as ADR 0121 decision 4 now does (V4.P6, the planner's provisional call; if it is
  wrong, W1 takes the purpose caps and this sentence loses its "from W2").
- Third consistency check (round 4), fourth pass: Acceptance cites `CLAUDE.md` by its section, Environments, and
  says that section held at acceptance, instead of the lines `:278-283`, which after the `CLAUDE.md` amendments made
  at acceptance held Data model rules.
- Third consistency check (round 4), sixth pass, Đạt's V4.22: decision 3's reads run under the tester's access
  intersected with the run's boundary, a draft root's being the provisional boundary its run door derives from the
  draft's closure (ADR 0103 decision 5), which no `live` run reads under.
- Third consistency check (round 4), seventh pass, the planner's provisional call (G-1): decision 3 gives the
  provisional boundary to every root that is not live yet, a sealed candidate in its gate run as well as a draft, and
  names whose access a gate trial reads under, the principal the gate lane requests it as (ADR 0103 decision 5, ADR 0120
  decision 3), extending the sixth pass's line above (if it is wrong, a version's boundary is written when it is sealed
  and its gate trials read under it).
