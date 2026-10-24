---
status: Accepted (Đạt, 2026-10-23; amendments from the decision brief applied)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/workflow-engine/spec.md
    - ../../.claude/plans/studio/workflow-nodes/spec.md
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/checkpoint.py
    - ../../apps/api/src/dw_api/bootstrap/runtime.py
---

# 0112. A workflow is a dw.workflow/v1 document validated in one pass and compiled per published version to a LangGraph StateGraph, with one side effect per node leaving through the door its kind owns

Numbered 0112 in the block 0100-0199 that ADR-0100 reserves for Studio. It rests on the requester's D2 (business
admins build with nodes, forms and simple expressions; a code node only behind a dedicated permission and a plan
entitlement) and D7 (every code execution in its own fresh container); the engine's shape is stance S6.

## Context

- The runtime runs only graphs registered in Python: `LangGraphWorkflowRunner` compiles into a never-evicting
  `_compiled` dict (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:127`) and
  `hosts()` answers only for registered graphs (`langgraph_runner.py:172-178`). A tenant's change would be a deploy.
- The checkpoint saver builds its own `JsonPlusSerializer()` (`adapters/checkpoint.py:60`): the library's default decides what loads.
- Measured by the Studio workflow research against the locked LangGraph on 2026-10-22: it accepts unreachable nodes;
  an unconnected router port fails only at run time; two plain edges from parallel branches run a node twice; code
  placed before `interrupt()` runs again on resume; `recursion_limit` is 1,000 in the docs and 10,007 in the code; the
  `error_handler` is skipped when two tasks share a superstep; `RetryPolicy` has no idempotency key per iteration.
- `CLAUDE.md:246-247` keeps SQL and SDKs out of workflow nodes; `CLAUDE.md:68-69` puts every effect through policy,
  idempotency and audit. The pilot (D4) messages a lead only after a person approves.

## Decision

1. **The document.** A workflow is a `dw.workflow/v1` document of kind `workflow` in the shared envelope (ADR-0109):
   `triggers[]`; `nodes[]`, each with an `id` matching `^[a-z][a-z0-9_]{0,39}$` that stays stable across versions,
   `type` as `name@major`, a `config` valid against the node type's JSON Schema, `retry` (`max_attempts` 1-5, fixed
   or exponential backoff), `timeout_s` and `on_error` (`fail`, `continue`, `route`); `edges[]` (`from`, `port`,
   `to`); `variables[]`; `inputs` and `outputs`; `bindings[]`; `limits` (`max_steps`, `max_parallel`, `max_map_items`,
   `max_run_seconds`, `max_open_waits`); `outcomes[]` (a name and a CEL condition). Every tenant value (connection,
   run-as principal, endpoint, schedule) is a binding name whose value is approved apart from the version
   (ADR-0110). Canvas positions stay outside the document, so moving a node never changes the definition hash.
2. **Node types are platform code** in one `NodeTypeRegistry`, built by one function, `build_node_registry(ports)`, at
   both composition roots (the API for the palette and the validator, the worker for execution). A `NodeTypeSpec`
   carries `type@major`, config and output schemas, a `side_effect_level` from the existing vocabulary
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:19`), capability labels for ADR-0125, the
   error policies it allows, limits clamped by the plan, a `permission` and an `entitlement`, its behaviour per run
   mode (ADR-0111), a dependency extractor and `compile(config)`. The v1 catalogue has 32 types: six `trigger.*`,
   `ai.llm`, `ai.agent`, eight `data.*`, `tool.call`, `http.request`, `notify.send`, five `logic.*`, two `time.*`,
   `human.approval`, `human.task`, three `flow.*` and `code.python`. The fifth `logic.*` is `logic.loop`, whose
   `max_iterations` is required and clamped by the plan; it arrives in W2 (YC105), workflow-nodes registering the type
   and workflow-engine owning the loop's structure in the IR and the compiler. Tenants add tools (ADR-0116), never
   node types.
3. **One validator over the graph the compiler uses.** Publishing runs one all-errors validator over a `WorkflowIR`
   (nodes, ports, edges, dominator tree, branch-exclusivity sets) that the compiler also consumes. It runs at submit,
   the first step of ADR-0120's path to live, as warnings on every draft save, and before a `simulate` run of a
   draft, where an error answers 422 with its `wf.*` codes and requests no run (ADR-0109 decision 6). It checks that
   every node is reachable from a trigger; every router is total (a `default` port, every port connected or ended);
   cycles pass only through a `logic.loop` with `max_iterations`, so a graph has none before W2; parallel branches
   merge only through a join; every `{{ }}` reference names a dominating node or is guarded by `has()`; CEL types
   hold (ADR-0114); a variable has one writer per superstep; no wait sits inside a `map` body or a parallel branch in
   v1; plan limits hold; every connection, principal and endpoint is a declared binding. It returns
   `[{path, code, message_vi, message_en}]` with stable codes
   (`wf.unreachable_node`, `wf.router_not_total`, `wf.join_required`, `wf.ref_not_dominating`, `wf.type_mismatch`,
   `wf.wait_in_map`, `wf.limit_above_plan`, `wf.binding_undeclared`). Its graph module (`reachable`, `dominators`,
   `paths_to`) also serves ADR-0125's capability analysis, so the two cannot see different graphs.
4. **Compilation.** A published version compiles to a LangGraph `StateGraph`: one `LastValue` channel per node output
   (`out__<node_id>`) and per variable; `defer=True` for joins; a `map` as one `Send` per chunk of 20 items, with
   `max_parallel` as `max_concurrency` and child runs per chunk beyond `max_map_items` (at most 1,000); every wait an
   `interrupt()` as the first statement of its own node; `recursion_limit` always passed (`max_steps` plus the
   supersteps the compiler counts). Compiled graphs sit in a bounded per-process LRU of 256 keyed
   `(tenant_id, artifact_version_id, compiler_version)`. LangGraph is imported only in the runtime's adapters.
5. **A platform node wrapper, not LangGraph, owns retry, timeout, `on_error` and the one effect.** At start it asks
   `RunControlPort.require_open` (ADR-0120) and, from W2, checks cancellation and the deadline (ADR-0113 decision 3);
   it resolves inputs by CEL, runs each attempt under `asyncio.timeout`, retries with backoff (each attempt a run
   step), then applies `on_error`: `fail` raises, `continue` writes `{status: "error", error}` to the node's channel,
   `route` also takes the `error` port. An effect node calls its door once per attempt with the idempotency key
   `wf:{run_id}:{node_id}:{iteration_path}` (map index and loop counter, never the attempt), claimed first and fenced
   per ADR-0108, so a retry after a crash replays the stored result. Outputs are validated against the node's output
   schema off the event loop and capped at 64 KiB inline.
6. **Every effect leaves through its kind's door**, each a narrow Protocol the consumer declares and the composition
   root satisfies: the ToolExecutor (connector actions and `tool.call`; `http.request` as an inline `http` tool frozen
   at submit, when the version is sealed, so its kind floor applies; a message to a non-member is a connector
   `message` action meeting ADR-0124's send floor inside the executor); `RecordsPort` (ADR-0107's `RecordService`);
   `MemberNotificationPort` for `notify.send`, which reaches tenant members only (an address-shaped recipient is
   refused at submit, a non-member at run time is dropped and counted); the `ModelResolver` (ADR-0118);
   `CodeSandboxPort` (ADR-0119); waits and child runs through ADR-0113's doors, child runs (sub-workflows, workflow
   tools, agent nodes, linked agents) nesting at most 3 deep, as ADR-0113 decision 9 and ADR-0117 decision 7 state
   (requirements Q1, YC45, YC57). A node holds no SQL, no provider SDK and no concrete adapter, and it hands the run
   mode to its door, which applies it (ADR-0111): a node never simulates an effect itself.
7. **Approval steps and human tasks are enforced on the server.** In a `live` run `human.approval` opens an approval
   of type `studio.step.approval` and waits for its decision; in any other run it waits for no decider and takes a
   simulated decision (ADR-0111 decision 5). The API composition root adds `studio.step.` to `strict_approval_prefixes`
   with `|=` (beside `memory.`, `apps/api/src/dw_api/bootstrap/runtime.py:237-239`), so neither the run's requester
   nor its run-as principal decides, and registers `decision_guards["studio.step.approval"]`: the decider is a current
   assignee, still holds the stamped permission and can read every field the step stamped (ADR-0106 decision 6).
   From W2 the guard accepts, in place of a current assignee, a person holding that assignee's approval delegation
   (YC104) only while the person holds the stamped permission and `approvals.decide`, is not the run's requester
   (YC51) and acts between the delegation's start and end, audited; outside those conditions it still answers 403
   (ADR-0104 decision 11).
   `required_scope` is mandatory (ADR-0004); assignees (users, teams or a CEL expression) only narrow it; candidates
   come from `effective_grants` (ADR-0104), never a copy; none left is `no_approver`, and publish refuses a version
   whose permission only the run-as principal holds. Expiry never approves: from W2, with YC52's deadlines and the
   timer lane, the run follows an `expired` edge or fails with `approval_expired`; in W1 an approval waits with no
   deadline, so nothing is sent until someone decides. The approved node's arguments are rendered when the approval
   opens, stored with `subject_hash`, shown raw and executed exactly (`subject_changed` otherwise). Tasks reach people
   through a `/studio/tasks` inbox (`POST /api/v1/studio/tasks/{id}/submit`, a sub-resource as ADR-0108 spells
   custom methods, with If-Match and Idempotency-Key); a submission or decision resolves the wait and re-queues the
   run (ADR-0113).
8. **AI nodes validate on the server.** `ai.llm` gets its model per call from the `ModelResolver`; its structured
   output is validated against the tenant's JSON Schema (ADR-0116's profile, at most 32 KiB and depth 5,
   `additionalProperties: false` forced) by the platform validator, with one repair attempt, then `output_invalid`.
   Before the call it asks `RecordsPort.processing_flags` for the records its inputs reference and refuses with
   `ai_opt_out` when one carries `ai_opt_out` or `processing_restricted` (ADR-0106). `ai.agent` runs a pinned
   published agent version as a child run (ADR-0113, ADR-0117) whose run principal must be in the agent's audience;
   an output derived from untrusted input stays untrusted.
9. **The code node.** `code.python@1` runs tenant Python 3.12 (`def main(input: dict) -> dict`) through
   `CodeSandboxPort` in ADR-0119's fresh container per code execution: JSON in and out of at most 1 MiB, a mandatory
   `output_schema`, no network, no environment, sandbox profiles `py-small` (0.5 vCPU, 256 MiB, 30 s) and `py-medium`
   (1 vCPU, 512 MiB, 120 s). Adding a code node or changing its source in a draft needs `studio.code.author`,
   enforced in the draft-save service by comparing code nodes with the stored draft; the `code_node` entitlement is
   checked at submit and at admission (`entitlement_denied`). Each code execution is audited with `code_sha256` and
   the image digest (D2, D7).
10. **Checkpoints.** P1 keeps the current saver with a 64 KiB state cap enforced as a refusal (`output_too_large`) and
    deserialization against an explicit allowlist: the composition root builds the serializer with an explicit
    `allowed_msgpack_modules` and injects it (the process-wide `LANGGRAPH_STRICT_MSGPACK` flag is not used). The
    later blob-per-channel saver adds `tenant_id` and `workspace_id` under RLS ENABLE and FORCE to LangGraph's
    checkpoint, blob and write tables, holds JSON-native state, stores values above 64 KiB by reference under
    `tenants/{tenant_id}/workspaces/{workspace_id}/runs/{run_id}/state/`, and deletes a run's rows 24 hours after it
    ends. The format is pinned per run (ADR-0109), so pilot runs finish on the format they started on.

## Alternatives considered

- **Embed n8n, Dify, Windmill or Activepieces.** Rejected (stance S5): their licences forbid multi-tenant embedding or
  keep it in paid editions (n8n <https://docs.n8n.io/n8n-community-license/community-license/license-faq> and
  Activepieces <https://www.activepieces.com/docs/about/license>, as read by the research on 2026-10-22; Dify's and
  Windmill's terms are S5's reading, not re-read for this ADR), and each brings a second tenancy model.
- **A custom interpreter.** Rejected: it would re-implement the checkpoint, interrupt and human-in-the-loop machinery
  LangGraph already gives (<https://docs.langchain.com/oss/python/langgraph/interrupts>).
- **LangGraph's own retry policy and error handler.** Rejected: no idempotency key per iteration, so a retried effect
  repeats; the handler's behaviour depends on topology (measured).
- **An effect inside a node (SQL, an SDK).** Rejected: it bypasses policy, run mode, idempotency and audit
  (`CLAUDE.md:246-247`).
- **Trusting `StateGraph.compile()`, or checks in the canvas only.** Rejected: the measured gaps; a check the API does
  not run is bypassable (failure-modes #5).
- **Tenant-defined node types.** Rejected: a second, unreviewed runtime; tools cover the need.

## Consequences

- workflow-nodes owns the registry and the catalogue; workflow-engine owns the IR, the validator, the compiler and the
  node wrapper.
- A LangGraph upgrade is gated by golden parked-run fixtures resumed forward and backward in CI (ADR-0109's engine
  pin; LangGraph 1.2.11 and 1.2.16 resumed each other's runs when measured).
- Migrations (Alembic, random revision ids): `studio.step_assignments`, `studio.step_approvals` and
  `studio.human_tasks` in the CLAUDE.md workspace policy shape; the approval status CHECK gains `expired`, which
  workflow-engine writes from W2; later the
  per-run checkpoint tables under RLS. `studio.code.author` and `studio.tasks.manage` join the catalogue (ADR-0104).
- Tests that must exist, each red when its guard is removed: a failing fixture per validator code; an architecture
  test that no node module imports SQLAlchemy, an SDK or a concrete adapter; a negative test at each door called
  directly (failure-modes #5); a crash after an effect replaying one effect; an expiry that never approves; a decider
  outside the assignees refused; a code node saved without `studio.code.author` refused; a non-allowlisted type in a
  checkpoint refusing to load.
- Harder: every `NodeTypeSpec` attribute needs a named reader (failure-modes #1); node outputs must stay JSON-shaped;
  a node type's major version stays registered while any run or live version pins it.
- Reinforces `CLAUDE.md:246-247`; extends `docs/adr/0010-prompt-variables-are-untrusted-by-default.md` to workflow AI
  nodes through ADR-0114. `CLAUDE.md:70-71` (a release manifest pins graphs) gives way for tenant versions to the run
  manifest, the amendment ADR-0109 carries.
- Contradicts `CLAUDE.md:243-244` ("LLM output is always validated into a Pydantic schema") for tenant-defined schemas,
  which the platform's JSON Schema validator checks instead, because a Pydantic model made at run time comes back as a
  plain dict after a checkpoint (measured by the tools research). The amendment, due on acceptance and before
  workflow-nodes/05 is ready, reads: "LLM output is always validated into a schema the platform owns: a Pydantic model
  for code-defined schemas, the platform's JSON Schema validator for tenant-defined ones." ADR-0116 carries the same
  amendment.
- si-platform: re-derives the engine on LangGraph (D5) instead of si-platform's phase-A approval walker (si-platform
  `docs/adr/0043-record-approval-engine-is-a-platform-package-served-by-one-module.md`), keeping its structural
  checker (issue codes, Vietnamese and English messages) as a pattern reference.

## Open

1. **DO-30 (requester).** Are sub-workflow and agent-node versions pinned, drift proposing the update, or do they
   follow the live version? Provisional call (agent, 2026-10-23): pinned at submit. Answered 2026-10-23: pinned at
   submit (DO-30 (a)).
2. **DO-31 (requester).** Does an expired approval with no `expired` edge end the run failed with `approval_expired`?
   Provisional call: yes; nothing approves on time-out. Answered 2026-10-23: yes (DO-31 (a)); expiry itself arrives
   in W2 with YC52 and the timer lane, and a W1 approval waits with no deadline.
3. **DO-18 (requester, then Đạt).** May nurture use a batch approval against `.claude/rules/ui-quality.md:225`
   ("Verification, correction and approval are never bulk actions")? Provisional call: nurture in W2, every outbound
   message approved in the pilot, one approval per message in a fast keyboard queue. Answered 2026-10-23: nurture in
   W2 and one approval per message, never a batch; approval by sampled template is weighed only on shadow-run data
   (DO-18 (a)).
4. **DO-45 (requester for languages and billing, Đạt for container lifetime).** Code node languages and packages in
   v1? Provisional call: Python 3.12 only, no JavaScript, the package list set with code-sandbox. Answered 2026-10-23:
   Python 3.12 only, no JavaScript and no skill scripts, billed by reserved vCPU and GB over run time (DO-45.1 (a));
   one container per code execution in v1, a per-agent-session container decided only in W3 (DO-45.2 (a)).
5. **FOG-37 (prototype).** Which msgpack allowlist the platform's real checkpoint state types need.

## Acceptance (2026-10-23)

- Status Accepted by Đạt with the decision brief's amendments.
- Decision 6: child runs nest at most 3 deep, answering requirements Q1 as ADR-0113 and ADR-0117 do; a node hands
  the run mode to its door (D:custom-objects:R5.4~workflow-nodes:R5.3 (a)).
- Decision 7: the task route is `POST /api/v1/studio/tasks/{id}/submit` (DO-16.2 (a)); the step approval's guard
  adds the field-read condition (DO-36 (a)); expiry arrives in W2 and a W1 approval waits with no deadline
  (DO-31 (a)).
- Consequences: the `CLAUDE.md:243-244` amendment text recorded; the `expired` status written by workflow-engine from
  W2.
- Open 1 to 4 answered.

## Amendments (2026-10-24)

- Đạt accepted the open recommendations of the second consistency check; the status stays Accepted.
- Decisions 2 and 3: the step type `logic.loop`, with a required `max_iterations`, joins the catalogue in W2 (YC105),
  registered by workflow-nodes, its loop structure owned by workflow-engine; the v1 catalogue has 32 types, and a
  graph has no cycle before W2 (N7).
- Decision 7: a `human.approval` step outside a `live` run waits for no decider and takes a simulated decision, as
  ADR-0111 decision 5 states (N2).
- Third consistency check (round 4): decision 7 states from W2 the conditions under which an approval delegation
  stands in for a current assignee, 403 outside them (Đạt's V4.10; D:ADR-0112\~workflow-nodes:spec); decision 5
  checks cancellation and the deadline from W2, when ADR-0113 decision 3's cancel route and `deadline_at` arrive
  (F:ADR-0113\~workflow-engine:R3.1).
- Third consistency check (round 4), second pass: decision 3's validator also runs before a `simulate` run of a
  draft, refusing it 422 with its `wf.*` codes and requesting no run, as ADR-0109 decision 6 now admits a draft root
  (completing Đạt's V4.4, YC40); decisions 6 and 9 freeze an inline `http` tool, refuse an address-shaped recipient
  and check the `code_node` entitlement at submit, when the version is sealed and this validator runs, no longer
  "at publish" (ADR-0116 decision 1).
