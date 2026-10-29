---
status: Proposed
date: 2026-10-29
source:
    - ../../.claude/plans/studio/requirements.md
    - ../../.claude/plans/studio/digital-worker/spec.md
    - ../../.claude/plans/studio/wf-lite/spec.md
    - ../../.claude/plans/studio/leadcare/spec.md
    - 0103-runs-act-as-a-principal-within-a-boundary.md
    - 0112-workflows-compile-to-langgraph-one-effect-per-node.md
    - 0113-every-run-is-requested-and-queued-in-postgres.md
---

# 0128. A Digital Worker is a governed platform record that owns a queue: the CASANOS standard mapped onto this platform

Numbered in the block 0100-0199 reserved for Studio (ADR-0100 (Accepted) decision 9). It records D15 of 2026-10-29
(Đạt, after the CASANOS workshop of 2026-10-22, CASAN Vol. III 0.0.4) and D17 of the same day, which the agent took
provisionally while Đạt was away ("agent, tạm theo khuyến nghị, chờ Đạt"). Proposed until Đạt reads it; the specs that
build on it say so in their Phụ thuộc.

## Context

The CASANOS deck (slides 8-11 and 16) defines a Digital Worker (DW) as AI capability plus a role plus governance: a
company asset that owns a recurring job, whose accountability stays with named people. Slide 11 is a standard every FPT
platform must meet: eight attributes a DW carries, eight things the platform provides, and eight rules every DW follows,
"no platform may remove a required part, weaken a mandatory control or skip the required evidence". Slide 16 lists the
core objects (Worker, Role, Task, Run, Workflow, Goal/KPI/budget, Context, Evidence) and a seven-step task sequence
(route, authorize, assemble context, prepare and check, approve, act and verify, record and learn).

What this repository already has (read at `8508502`, 2026-10-29): a worker definition with an autonomy level A0-A4
(`packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:50-82`), a per-call approval policy over that
level (`packages/python/dw_agent_runtime/src/dw_agent_runtime/autonomy.py:96-140`), durable checkpointed runs that pause
for an approval and resume (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:85`), one
`ToolExecutor` for every effect, an append-only audit trail, and runs that record the versions they used
(`platform.worker_runs`). What it lacks: a DW as a record a tenant owns, named owners, decision classes, a shared queue,
handoffs and a scorecard. Nothing in it is a chat product, and D15 says it must not become one.

## Decision

1. **A DW is a row, not a code artifact.** `platform.digital_workers` holds one DW per row, in one workspace whose
   queue it works: a key, a name, a mandate, the work kinds it may hold, the tools it may use, the workflow version it
   runs (a shipped `dw.workflow/v1` document in the first slice, D17), its parameters, its lifecycle state and its four
   people. The DW's identity is the row's own id, written as `requested_by` on every run it makes and as the actor of
   every audit event it causes; it never borrows a person's id (YC118). It holds no login and no membership; it has
   exactly the scopes its allowed tools require, computed, never stored, so no one can widen it by editing a list.
   org-and-principals/03 later backs the id with a `platform.service_principals` row; until then this is the "minimal
   principal" of D17.
2. **Four people, as functions, not roles.** Business Owner (mandate, autonomy, scorecard, answers for outcomes),
   Technical Owner (builds, monitors, recovers; never widens authority), Work Assigner (puts work in the queue) and
   Validator (decides proposals and receives handoffs). Each is a user of the tenant; one person may hold several. A
   function is checked where its action happens, never inferred from a role key.
3. **Autonomy is per decision class, and the effective level is the lowest of three.** A DW has decision classes
   (`lead.score`, `email.send`, ...), each with the effect level it may reach (`none`, `internal`, `external`,
   `critical`), whether it is reversible, a ceiling and an earned level. The level a run uses for a class is the lowest
   of the class's ceiling, the earned level and the tenant's autonomy ceiling: slide 9's rule that the platform allows
   the lower of what the organisation is ready to govern and what the worker has earned. Whether that level lets an
   action happen without a person is decided by the same ladder that decides it for tools (`autonomy.py`), with a
   reversible external class ranked as the idempotent external rung; there is no second table.
4. **A0-A5 maps onto A0-A4.** CASANOS A0-A1 (observe or draft) is A0-A1, A2 (propose, people decide) is A2, A3 (act
   and report, reversible actions) is A3, and A4-A5 (operate end to end) is A4. A5 is not offered: the kernel's five
   levels (`packages/python/dw_kernel/src/dw_kernel/autonomy.py:17`) stay the one list, and a sixth would be a level
   the runtime cannot tell apart from A4.
5. **Raising autonomy takes a second person; lowering does not.** The Business Owner proposes a higher earned level;
   it takes effect only when another person approves it (D11's two-person rule for loosening). Lowering takes effect at
   the next run. Both are audited as the person who decided.
6. **One shared queue.** `platform.work_items` is the queue people and DWs share (slide 11 "no hidden work"): every DW
   run is started for one work item and recorded on it, and a work item is held by exactly one DW or one person until
   it is done, failed, cancelled or handed off. A DW may hold only the work kinds its mandate lists.
7. **Escalation hands off with a packet.** On low confidence, a ceiling it may not pass, an irreversible action it
   may not take, or a reply it cannot classify, a DW hands the item to a person with a packet of problem, context, what
   was tried and its recommendation (slide 11 rules), and stops.
8. **Approval reuses the platform's door.** A decision class whose effective level requires a person opens an
   approval of type `dw.decision` on the run, decided through `ApproveAndResumeService` like every other approval, its
   guard admitting only the DW's Validator or Business Owner. No second approval mechanism exists for DWs.
9. **The scorecard is computed, never reported.** Items, completion, handoffs, approval outcomes and model cost come
   from the run history, the approval decisions and the run's recorded cost, never from numbers the DW writes about
   itself.
10. **Stop and reverse.** A DW in state `paused` starts no run and takes no effect: the worker lane and the tool door
    both check it. Override is the Validator's decision on a pending approval; rollback of a sent message is not
    possible and is why `email.send` is irreversible.
11. **Lifecycle.** CASANOS's propose, design, build, certify, operate, retire maps onto ADR-0120's stage machine when
    a tenant builds a DW in Studio. A DW running a shipped workflow (D17) has `draft`, `operating`, `paused` and
    `retired`; certification is the workflow's validator plus the HITL floor (wf-lite) until Studio's quality gate
    exists.

### The standard, row by row

| CASANOS (slide 11)                    | Here                                                                                    |
| ------------------------------------- | --------------------------------------------------------------------------------------- |
| Identity: own non-human ID, version   | decision 1; the workflow version pinned on the row and on every run                     |
| Mandate and scope                     | `mandate`, `work_kinds`, `allowed_tools` on the row (decision 1, 6)                     |
| Objectives: KPIs, scorecard           | decision 9; KPI targets are W2                                                          |
| Authority: A0-A5 per decision         | decisions 3-5                                                                           |
| Resources: data, tools, models, money | `allowed_tools`; the model profile of the workflow; the tenant's spend guard            |
| People                                | decision 2                                                                              |
| Platform: identity and access         | decision 1, least privilege by construction                                             |
| Platform: shared work queue           | decision 6                                                                              |
| Platform: delegation and approval     | decisions 3, 8                                                                          |
| Platform: evaluation gates            | wf-lite validator and HITL floor now; Studio's quality gate (ADR-0120 (Accepted)) later |
| Platform: audit trail                 | `platform.audit_events`, `platform.worker_runs`, `platform.tool_executions`             |
| Platform: stop and reverse            | decision 10                                                                             |
| Rule: stay in the envelope            | work kinds and tools enforced at the queue and the tool door                            |
| Rule: own work to the end             | decision 6                                                                              |
| Rule: escalate on triggers            | decision 7                                                                              |
| Rule: hand off with a packet          | decision 7                                                                              |
| Rule: leave evidence                  | every effect through `ToolExecutor`; every decision audited                             |
| Rule: follow the lifecycle            | decision 11                                                                             |

Slide 16's seven steps: route is the queue and the worker lane; authorize is the scopes computed from tools plus the
decision-class gate; assemble context is the work item's payload, validated against the pack's JSON Schema; prepare
and check is the structured, schema-validated model output with its confidence; approve is decision 8, bound to the
run, the proposal and its expiry; act and verify is `ToolExecutor`; record and learn is the audit trail and the
scorecard.

## Alternatives considered

- **A DW as a worker YAML in `configs/workers`.** Rejected: a tenant cannot own, pause or re-delegate a file in the
  checkout, and the four people are tenant data.
- **A DW as a Studio `dw.agent/v1` document now.** Rejected for the first slice by D17: it waits on tenant-config,
  agent-lifecycle and the Studio skeleton; the row here becomes the runtime record those documents publish into.
- **A sixth autonomy level for A5.** Rejected (decision 4).
- **A DW-specific approval inbox.** Rejected (decision 8): a second door is a second answer to who may decide.

## Consequences

- Positive: the CASANOS standard has a named owner for each part, and a DW's authority is visible as data a reviewer
  can read.
- Negative: until org-and-principals/03 the DW id is a principal with no row in a principals table; a check that wants
  "is this a known principal" must ask `platform.digital_workers` as well.
- Negative: the scorecard's cost column reads the run's own recorded cost until usage-and-limits/02's ledger exists,
  then moves to the ledger.

## Open

1. A5: offer it once the kernel has a meaning for it distinct from A4 (Đạt).
2. Whether the Work Assigner may assign work kinds outside the mandate with the Business Owner's approval (W2).
