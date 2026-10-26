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
- Measured again by the canvas research on 2026-10-24 against the same LangGraph 1.2.11, with langgraph-checkpoint 4.2.0
  on the in-memory saver (the research's set S22 and its review's probes of the same day; the Postgres saver with two
  workers is discovery 14's to measure): a waiting edge from the end of every lane (`add_edge([...], join)`) runs the
  join once even when the lanes are uneven, where plain edges run it twice; `defer=True` holds a nested join until an
  unrelated outer lane has finished; a switch inside a lane, closed by a no-op merge node and a waiting edge, joins
  once. Lanes compiled as plain branches of one graph run in lock-step, each superstep waiting for its slowest task (a
  lane of one 1.0 s step beside a lane of three 0.3 s steps took 1.61 s, and 1.01 s with each lane a subgraph), and a
  lane subgraph that shares a reducer key with its parent adds the parent's values again. In one graph an open wait in
  one lane holds the later steps of the others, so a second approver is asked only once the first has decided, and a
  failure in another lane surfaces only then. A step that ends the run inside a lane completes it without an error while
  the join and every later step never run. A loop that waits in each iteration gets a distinct interrupt id per
  iteration and runs each effect once per iteration, but `recursion_limit` counts per invoke: such a loop ran 20
  supersteps under a limit of 8 over 10 resumes, and raised only without the waits. After one lane raised,
  `invoke(None)` ran the failed node again and the sibling lane and the join once.
- `CLAUDE.md:246-247` keeps SQL and SDKs out of workflow nodes; `CLAUDE.md:68-69` puts every effect through policy,
  idempotency and audit. The pilot (D4) messages a lead only after a person approves.

## Decision

1. **The document is a tree of steps.** A workflow is a `dw.workflow/v1` document of kind `workflow` in the shared
   envelope (ADR-0109 (Accepted)): `triggers[]` and a tree `steps[]`. A step (Bước) is
   `{id, type, config, retry, timeout_s, on_error, description}`: an `id` matching `^[a-z][a-z0-9_]{0,39}$` that stays
   stable across versions, `type` as `name@major`, a `config` valid against the step type's JSON Schema, `retry`
   (`max_attempts` 1-5, fixed or exponential backoff), `timeout_s`, `on_error` (`fail`, `continue`, `route`, `incident`;
   decision 5), an optional `description` and, from W2, an optional Stage label (ADR-0126 (Accepted) decision 6). For
   each port its type declares, a step holds one lane, an ordered list of steps nested in it: the cases of a
   `logic.switch` with its default lane "Khác", the outcomes of a `human.approval` ("Duyệt", "Từ chối"; "Hết hạn" from
   W2), the lanes of a `logic.parallel`, the body of a `logic.loop`, the body of a `logic.map` (W2), and an error lane
   ("Khi lỗi") when `on_error` is `route`. The steps of a list run in order and every lane closes at the end of its
   step's block, so the tree is the whole topology: there is no `edges[]`, and no position enters the document, the
   canvas computing every position from the tree (ADR-0101 (Accepted) decision 3), so the definition hash changes when
   the tree does and never when the canvas does. The document also holds `variables[]`; `inputs` and `outputs`;
   `bindings[]`; `limits` (`max_steps`, `max_parallel`, `max_map_items`, `max_run_seconds`, `max_open_waits`);
   `outcomes[]` (a name and a CEL condition): when a run ends, workflow-engine evaluates each condition on the final
   state and writes the names that hold into the run's `outcomes text[]` on `platform.worker_runs`, only names the
   pinned document declares, as the validator guarantees at submit, and a scenario case of the quality gate compares
   its expected `outcome` with that column (V4.37, H-14); filtering `/runs` by outcome is W2. Every tenant value
   (connection, run-as principal, endpoint, schedule) is a binding name whose value is approved apart from the version
   (ADR-0110 (Accepted)).
2. **Step types are platform code** in one `NodeTypeRegistry`, built by one function, `build_node_registry(ports)`, at
   both composition roots (the API for the palette and the validator, the worker for execution). A `NodeTypeSpec`
   carries `type@major`, config and output schemas, the ports whose lanes a step of the type holds (decision 1), a
   `side_effect_level` from the existing vocabulary
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:19`), capability labels for ADR-0125, the error
   policies it allows, limits clamped by the plan, a `permission` and an `entitlement`, its behaviour per run mode
   (ADR-0111), a dependency extractor and `compile(config)`. The v1 catalogue has 32 types: six `trigger.*`, `ai.llm`,
   `ai.agent`, eight `data.*`, `tool.call`, `http.request`, `notify.send`, five `logic.*` (`logic.switch`,
   `logic.parallel`, `logic.loop`, `logic.break`, `logic.map`), two `time.*`, `human.approval`, `human.task`, three
   `flow.*` and `code.python`. A join is no type of its own: `logic.join` folds into the end of `logic.parallel`, whose
   join waits for every lane in W1. `logic.parallel` (YC108), `logic.loop` and `logic.break` (YC105) arrive in the W1
   tail, after the critical path to YC94, and no pilot ticket waits for them (V4.26), workflow-nodes registering the
   types and workflow-engine owning the block structure in the IR and the compiler; `logic.map` stays W2.
   `flow.subworkflow@1` (YC117) joins the same tail, no pilot ticket waiting for it either (V4.33): its step runs a
   child version pinned at submit (ADR-0109 decision 9), nested at most 3 deep (decision 6), and opens a `child_run`
   wait, so its type declares `opens_wait` true, workflow-nodes registering the type (workflow-nodes/08) and
   workflow-engine running the child run (workflow-engine/09). `logic.loop`
   is a bounded do-while ("Lặp lại khi …"): its body runs, then its condition decides whether the body runs again; its
   `max_iterations` is required and clamped by the plan, and at that count the step takes its `max_reached` lane ("Đã đủ
   N lần") or, when it declares none, fails the run with `loop_limit_reached` (V4.P11). `logic.break` ("Thoát vòng lặp")
   leaves its loop at once. In the same tail a `human.approval` whose `approval_rule` is `all` requires every one of
   several approvers (k = n, YC110, decision 7); k of n with k < n is W3. Tenants add tools (ADR-0116), never step
   types.
3. **One validator over the IR the compiler uses.** The tree lowers to one `WorkflowIR` (steps, ports, the edges the
   tree implies, dominator tree, branch-exclusivity sets), which the validator and the compiler both consume. Publishing
   runs one all-errors validator over it. It runs at submit, the first step of ADR-0120's path to live, as warnings on
   every draft save, and before a `simulate` run of a draft, where an error answers 422 with its `wf.*` codes and
   requests no run (ADR-0109 decision 6). It checks that every step is reachable (a step after a `flow.stop` or a
   `logic.break` in its list is not); every `logic.switch` is total, its default lane present; every `{{ }}` reference
   names a dominating step or is guarded by `has()`, a loop's body dominating what follows the loop except the steps a
   `logic.break` can skip; CEL types hold (ADR-0114); a variable has one writer per superstep, and no two lanes of one
   `logic.parallel` write the same variable; no wait (an approval, a task, a timer, the child run of a
   `flow.subworkflow` or an incident hold) sits inside a `map` body or a parallel lane in v1, while a loop body may
   hold waits; inside a parallel lane neither a `flow.stop`
   nor an error lane that ends the run leaves the lane before its end, so an error lane there only merges back
   (measured: such an exit completes the run as a success while the join and every later step never run); every
   `logic.break` sits in a loop body and in no parallel lane, even one inside that body; plan limits hold (the tree's
   step count and nesting depth); every connection, principal and endpoint is a declared binding. It returns
   `[{path, code, message_vi, message_en}]` with stable codes (`wf.unreachable_node`, `wf.router_not_total`,
   `wf.ref_not_dominating`, `wf.type_mismatch`, `wf.variable_conflict`, `wf.wait_in_map`, `wf.wait_in_parallel`,
   `wf.stop_in_parallel`, `wf.break_outside_loop`, `wf.limit_above_plan`, `wf.binding_undeclared`). Two checks of the
   graph form cannot fail on a tree, whose lanes always meet at the end of their block and whose only way back is a
   loop, so their codes,
   `wf.join_required` and workflow-engine's `wf.unbounded_cycle`, are retired and never reused. Keeping waits out of
   parallel lanes keeps every parked node in the root graph, where ADR-0109 decision 8's resume check looks for it,
   since each lane compiles to a subgraph with a checkpoint namespace of its own (decision 4). The validator also
   computes the tree's worst-case step count, each loop at its `max_iterations`, and warns with
   `wf.steps_may_exceed_limit` without refusing when it exceeds `limits.max_steps`: a product over nested loops would
   refuse modest flows, and the node wrapper's counter is the cap (decision 5). Its graph module (`reachable`,
   `dominators`, `paths_to`) also serves ADR-0125's capability analysis, so the two cannot see different graphs.
4. **Compilation.** Each published version, and each draft a `simulate` run pins (ADR-0109 decision 6), compiles from
   its `WorkflowIR` to a LangGraph `StateGraph`: one `LastValue` channel per step output (`out__<node_id>`, the step's
   id) and per variable; a `logic.switch` as a conditional edge whose lanes meet again at a no-op merge node the
   compiler adds; each lane of a `logic.parallel` as a subgraph node with a state schema of its own, whose outputs are
   exported to the parent's channels, the lanes meeting at the join through one waiting edge from the end of every lane
   (`add_edge([...], join)`), never `defer=True`, which stays only for a `map`'s fan-in, whose width only the run knows;
   a `logic.loop` as a bounded cycle in the graph that holds it, its body first and its condition after, with its
   iteration counter in a channel of its own, which `iteration_path` reads (decision 5), and a `logic.break` as a
   conditional edge to the loop's exit; a `map` as one `Send` per chunk of 20 items, with `max_parallel` as
   `max_concurrency` and child runs per chunk beyond `max_map_items` (at most 1,000); every wait, an incident hold
   included, an `interrupt()` as the first statement of its own node; `recursion_limit` always passed (`max_steps` plus
   the supersteps the compiler counts), though it bounds one invoke only, since it resets on every resume, so the run's
   step cap is the node wrapper's counter (decision 5). Every invoke passes `durability="sync"`, which the run
   manifest's engine section pins (ADR-0109 decision 8, V4.34), so a step's checkpoint is written before the next step
   dispatches an effect, where the library's default `async` widens the window in which a crash after an effect runs
   its node again. Context records the measurements behind these choices. Compiled
   graphs sit in a bounded per-process LRU of 256 keyed
   `(tenant_id, artifact_version_id, pinned_hash, compiler_version)`, where `pinned_hash` is the hash the run manifest
   pins: a sealed version's `definition_hash`, or the provisional hash of a draft's content (ADR-0109 decision 6). A
   draft keeps its id while it is edited and a run resolves only from its manifest (`CLAUDE.md`, Non-negotiable
   architecture), so a key without the hash would hand a new simulation the graph of older content. LangGraph is
   imported only in the runtime's adapters.
5. **A platform node wrapper, not LangGraph, owns retry, timeout, `on_error`, the step count and the one effect.** At
   start it asks `RunControlPort.require_open` (ADR-0120), checks the run's deadline and, from W2, cancellation
   (ADR-0113 decision 3), and counts the step on a counter the run keeps across every resume, stopping the run with
   `limit_exceeded`, without applying the step's `on_error`, once `limits.max_steps`, clamped by the plan, is spent; it
   resolves inputs by CEL, runs each attempt under `asyncio.timeout` and retries with backoff (each attempt a run
   step), an attempt whose outbound call returns the egress client's typed outcome (ADR-0115 (Accepted) decision 6)
   being retried only when that outcome is `not_dispatched`, or `rejected` with a code the Action declares retryable
   (V4.30), then applies `on_error`: `fail` raises; `continue` writes `{status: "error", error}` to the step's
   channel; `route`, from W1, writes it too and takes the step's error lane, which merges back below the step or ends
   the run (inside a parallel lane it only merges back, decision 3); `incident` ("Chờ xử lý", in the W1 tail) parks a
   `live` run `waiting` on a wait of kind `incident` (ADR-0113 (Accepted) decision 4) once the attempts are spent,
   "Chạy tiếp từ Bước lỗi" running the step again and "Kết thúc" failing the run, while a run in any other mode, with
   no person to resolve it, fails as under `fail`. An `outcome_unknown`, a call that may have reached the provider,
   applies no `on_error`: it is never written as `continue`'s error and never enters an error lane; the run parks
   `waiting` on an `outcome_review` wait (ADR-0113 (Accepted) decision 4), whose resolution records the step as
   succeeded, sends again under the same key or fails the step, and only that failure then follows `on_error`
   (V4.30); how a run parks for such a step inside a parallel lane, where no wait sits (decision 3), is Open 6 (Q-h5).
   A step's output carries `error` under `continue` and under `route` alike (workflow-nodes R1.5). An effect step
   calls its door once per attempt with the idempotency key `wf:{run_id}:{node_id}:{iteration_path}` (map index and
   loop counter, never the attempt), claimed first and fenced per ADR-0108: a node run again after a crash replays a
   call recorded `succeeded`, runs again a call that has no `dispatched` row and follows the Action's `on_unknown` for
   one recorded `dispatched` with no outcome (ADR-0108 decision 5), and a step run again from an incident keeps its
   key. Outputs are validated against the step's output schema off the event loop and capped at 64 KiB inline. In a
   `simulate` run a result the run pins for a step (a scenario case's pinned simulated result, V4.37) stands in for
   the simulated answer of the step's door once it validates against the step's output schema (H-18), the door still
   applying the run mode to every call it receives (ADR-0111).
6. **Every effect leaves through its kind's door**, each a narrow Protocol the consumer declares and the composition
   root satisfies: the ToolExecutor (connector actions and `tool.call`; `http.request` as an inline `http` tool frozen
   at submit, when the version is sealed, so its kind floor applies; a message to a non-member is a connector
   `message` action meeting ADR-0124's send floor inside the executor); `RecordsPort` (ADR-0107's `RecordService`);
   `MemberNotificationPort` for `notify.send`, which reaches tenant members only (an address-shaped recipient is
   refused at submit, a non-member at run time is dropped and counted); the `ModelResolver` (ADR-0118);
   `CodeSandboxPort` (ADR-0119); waits and child runs through ADR-0113's doors, child runs (sub-workflows, workflow
   tools, agent nodes, linked agents) nesting at most 3 deep, as ADR-0113 decision 9 and ADR-0117 decision 7 state
   (requirements Q1, YC45, YC57, YC117). A node holds no SQL, no provider SDK and no concrete adapter, and it hands
   the run mode to its door, which applies it (ADR-0111): a node never simulates an effect itself.
7. **Approval steps and human tasks are enforced on the server.** In a `live` run `human.approval` opens an approval of
   type `studio.step.approval` and waits for its decision; in any other run it waits for no decider and takes a
   simulated decision (ADR-0111 decision 5). A step whose `approval_rule` is `all` (k = n, in the W1 tail, decision 2)
   opens one approval for each of its assignees under one wait, which resolves when the last of them approves or at the
   first rejection, the approvals still pending then being cancelled; each is decided only by its own assignee, through
   the guard below, and `any`, the default, keeps one approval that any assignee decides. The API composition root adds
   `studio.step.` to `strict_approval_prefixes` with `|=` (beside `memory.`,
   `apps/api/src/dw_api/bootstrap/runtime.py:237-239`), so neither the run's requester nor its run-as principal decides,
   and registers `decision_guards["studio.step.approval"]`: the decider is a current assignee, still holds the stamped
   permission and can read every field the step stamped (ADR-0106 decision 6). From W2 the guard accepts, in place of a
   current assignee, a person holding that assignee's approval delegation (YC104) only while the person holds the
   stamped permission and `approvals.decide`, is not the run's requester (YC51) and acts between the delegation's start
   and end, audited; outside those conditions it still answers 403 (ADR-0104 decision 11). `required_scope` is mandatory
   (ADR-0004); assignees (users, teams or a CEL expression) only narrow it; candidates come from `effective_grants`
   (ADR-0104), never a copy; none left is `no_approver`, and publish refuses a version whose permission only the run-as
   principal holds. Expiry never approves: from W2, with YC52's deadlines and the timer lane, the run takes the step's
   `expired` lane ("Hết hạn") or fails with `approval_expired`; in W1 an approval has no deadline of its own, so nothing
   is sent until someone decides, and the run's deadline (ADR-0113 decision 3) ends a run still waiting, the approval
   cancelled with it. The approved node's arguments are rendered when the approval opens, stored with `subject_hash`,
   shown raw and executed exactly (`subject_changed` otherwise). Tasks reach people through a `/studio/tasks` inbox
   (`POST /api/v1/studio/tasks/{id}/submit`, a sub-resource as ADR-0108 spells custom methods, with If-Match and
   Idempotency-Key); a submission, or the decision that settles the step (under `all`, the last approval or the first
   rejection), resolves the wait and re-queues the run (ADR-0113).
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
11. **One execution semantics, held by golden traces.** What a run does with the tree is one section of
    workflow-engine's spec ("Ngữ nghĩa thực thi", V4.34), each rule with a golden trace that CI runs on every
    `WorkflowRunnerPort`, so an engine that replaced LangGraph would be held to the same traces: a block runs its steps
    in order, each effect one pass through its door under its key (decision 5); a `logic.switch` takes exactly one
    lane, its default required, its lanes meeting at the end of its block (decision 3); a `logic.parallel` runs every
    lane and ends when every lane has, and a lane that fails with no error lane to catch it cancels the lanes still
    running, audited `studio.branch.cancelled`, the error rising to the `logic.parallel` step; a variable has one
    writer in the block (`wf.variable_conflict`), and a record write in a lane is a PATCH of the fields it names, so
    two lanes that change different fields of one record keep both; `max_parallel` bounds a `map` only, from W2; a
    `logic.loop` runs at most `max_iterations` times and then takes `max_reached` or fails with `loop_limit_reached`,
    each iteration named by `iteration_path` (decision 2); an error lane runs when a failed step has spent its
    attempts, and an `outcome_unknown` never enters one (decision 5); a `flow.subworkflow` step runs its pinned child
    (ADR-0113 decision 9); and cancelling a run moves every `open` wait to `cancelled` in the same transaction
    (ADR-0113 decision 3). A rule the spec already states is cited there, never copied; the failing lane's propagation
    and the per-field PATCH are criteria of their own, each with its trace.

## Alternatives considered

- **Embed n8n, Dify, Windmill or Activepieces.** Rejected (stance S5): their licences forbid multi-tenant embedding or
  keep it in paid editions (n8n <https://docs.n8n.io/n8n-community-license/community-license/license-faq> and
  Activepieces <https://www.activepieces.com/docs/about/license>, as read by the research on 2026-10-22; Dify's and
  Windmill's terms are S5's reading, not re-read for this ADR), and each brings a second tenancy model.
- **A custom interpreter** (option C of V4.34, a token engine on Postgres). Not built: it would re-implement the
  checkpoint, interrupt and human-in-the-loop machinery LangGraph already gives
  (<https://docs.langchain.com/oss/python/langgraph/interrupts>), a reason that stays a claim until spike S-RT
  measures it, and whose numbers replace this line after the spike. S-RT is discovery 14 widened (two weeks in S0,
  beside foundations-hardening and app-standards, so the critical path does not lengthen), with six reference
  workflows RW1 to RW6 and thresholds T1 to T9. LangGraph on the tree (option A: each lane a subgraph,
  `durability="sync"`, decision 11's golden traces) is kept if it meets T1 to T8; if it misses T1, T2 or T7, C,
  designed on paper only until then, is built and measured on T1 to T9; if both miss, Temporal (option B) opens with
  an ADR of its own; T5 missed only because of the saver brings the blob-per-channel saver (decision 10) into W1 and
  keeps the engine.
- **LangGraph's own retry policy and error handler.** Rejected: no idempotency key per iteration, so a retried effect
  repeats; the handler's behaviour depends on topology (measured).
- **An effect inside a node (SQL, an SDK).** Rejected: it bypasses policy, run mode, idempotency and audit
  (`CLAUDE.md:246-247`).
- **Trusting `StateGraph.compile()`, or checks in the canvas only.** Rejected: the measured gaps; a check the API does
  not run is bypassable (failure-modes #5).
- **Tenant-defined node types.** Rejected: a second, unreviewed runtime; tools cover the need.
- **A graph document, `nodes[]` with `edges[]`** (decision 1 as accepted on 2026-10-23). Replaced by the step tree
  (V4.24): a free-form graph passes through unstructured states while it is edited, so its layout and its joins break
  mid-edit; drawing it in blocks would need a TypeScript copy of the server's dominator analysis (failure-modes #2); the
  canvas library has no keyboard path to connect a port; and n8n, whose branches run in canvas order, shows a position
  deciding what runs
  (<https://raw.githubusercontent.com/n8n-io/n8n-docs/main/docs/build/flow-logic/understand-execution-order.md>). Power
  Automate, the largest builder for business admins, is block-structured: a step is added with "+" below another, and
  scopes, conditions, switch cases and loops nest at most eight levels deep
  (<https://learn.microsoft.com/power-automate/scopes>). Both read on 2026-10-24.
- **Parallel lanes as plain branches of one graph, joined with `defer=True`** (decision 4's first form). Rejected:
  uneven lanes run in lock-step and a nested join waits for an unrelated lane (measured, Context).
- **Lane subgraphs that share the parent's state schema.** Rejected: a reducer key shared with the parent adds the
  parent's values again (measured, Context), so each lane has a state schema of its own (decision 4).
- **Waits inside parallel lanes**, so that each lane's approver approves. Rejected for v1: in one graph an open wait
  holds the other lanes, so the second approver is asked only after the first decides and a failure elsewhere surfaces
  only then (measured); a rejection cannot end the block early, and W1 has no route that cancels the approvals left open
  (ADR-0113 (Accepted) decision 3); with subgraph lanes both waits would open together, but the parked node would sit in
  a lane's checkpoint namespace, which ADR-0109 decision 8's resume check does not read. One `human.approval` that every
  one of several approvers must approve reaches the same outcome with one wait, as Windmill's `suspend.required_events`
  does (<https://www.windmill.dev/docs/flows/flow_approval>, read 2026-10-24).
- **`recursion_limit` as a run's step cap, or a static worst-case count that refuses at submit.** Rejected:
  `recursion_limit` resets on every resume (measured), and a product over nested loops would refuse modest flows under a
  plan ceiling of at most 500 steps a run (usage-and-limits' `max_steps_per_run`); the wrapper's counter caps, the
  static count warns.
- **Reopening a `failed` run at its failed step** for "Chạy tiếp từ Bước lỗi". Rejected: `failed` is terminal for the
  lanes that delete a run's checkpoints after it ends (decision 10) and that return its budget lease (ADR-0121
  (Accepted)), and reopening would add a writer of queued rows (ADR-0113 decision 1). Camunda keeps an instance whose
  job has no retries left at an incident and continues it once a person resolves the incident
  (<https://docs.camunda.io/docs/components/concepts/incidents/>, read 2026-10-24), which decision 5's `incident`
  follows.

## Consequences

- workflow-nodes owns the registry and the catalogue; workflow-engine owns the document, its lowering to the IR, the
  validator, the compiler and the node wrapper; workflow-builder-ui draws and edits the tree (ADR-0101 (Accepted)).
- A LangGraph upgrade is gated by golden parked-run fixtures resumed forward and backward in CI (ADR-0109's engine
  pin; LangGraph 1.2.11 and 1.2.16 resumed each other's runs when measured).
- The constructs of the W1 tail (V4.26: `logic.parallel`, the bounded loop with `logic.break`, `incident` and the step
  every approver must approve; V4.33: `flow.subworkflow`) come after the critical path to YC94, block no pilot ticket
  and lengthen W1 by about two to three weeks. Discovery 14 is spike S-RT (V4.34), the one owner of the runtime's
  measurements: it measures them again on the Postgres saver with two workers, starting from Context's in-memory
  results (joins by waiting edge over subgraph lanes, nested and inside a loop; a loop that waits, with the step
  counter; an incident and its resume), runs RW1 to RW6 against T1 to T9 (RW6 a sub-workflow three deep with a wait in
  a child and the parent cancelled midway), and runs V4.30's crash matrix, K1 to K6 plus a holder stalled past its
  claim and a send whose answer was lost, against a fake provider in three delivery modes (a provider key, a lookup,
  neither); workflow-engine/03 waits on its answer. Subgraph lanes carry the most risk, medium to high, since they
  change the compile model, the checkpoint namespaces and the run steps a lane writes.
- Migrations (Alembic, random revision ids): `studio.step_assignments`, `studio.step_approvals` and
  `studio.human_tasks` in the CLAUDE.md workspace policy shape; the approval status CHECK gains `expired`, which
  workflow-engine writes from W2; later the
  per-run checkpoint tables under RLS. `studio.code.author` and `studio.tasks.manage` join the catalogue (ADR-0104).
- Tests that must exist, each red when its guard is removed: a failing fixture per validator code; an architecture test
  that no node module imports SQLAlchemy, an SDK or a concrete adapter; a negative test at each door called directly
  (failure-modes #5); the crash matrix, in which an effect with a provider key or a lookup is applied once, one with
  neither is never sent again automatically and parks on `outcome_review` every time, an internal effect is never
  repeated and a fallback channel never delivers both (removing the dispatch log turns it red); an `outcome_unknown`
  taking neither `continue` nor an error lane; each rule of decision 11 as a golden trace on every runner, a failing
  lane cancelling the others with `studio.branch.cancelled` and two lanes changing different fields of one record
  keeping both among them; a `flow.subworkflow` step refused in a parallel lane with `wf.wait_in_parallel` and allowed
  in a loop body; a run that ends writing into `outcomes` only names its document declares; an expiry that never
  approves; a decider outside the
  assignees refused; a code node saved without `studio.code.author` refused; a non-allowlisted type in a checkpoint
  refusing to load; a join running once over uneven lanes and over a switch inside a lane; a `flow.stop` and an error
  lane that ends the run inside a parallel lane refused with `wf.stop_in_parallel`, a wait or an `incident` step there
  with `wf.wait_in_parallel`, and a `logic.break` there or outside every loop with `wf.break_outside_loop`; a loop that
  waits in every iteration stopped by the step counter, which `recursion_limit` alone does not stop; an effect inside a
  loop running once per iteration; an incident resumed running its step again under the same key, and one ended failing
  the run; a step every approver must approve resolving only after the last approval, and at the first rejection.
- Harder: every `NodeTypeSpec` attribute needs a named reader (failure-modes #1); node outputs must stay JSON-shaped;
  a node type's major version stays registered while any run or live version pins it.
- Harder: a tree cannot express a jump, or a merge across lanes. Returning to an earlier step is a loop around the steps
  between, rework that returns to different earlier steps by reason is nested loops, one for each step it can return to,
  which `logic.break` leaves early, and back-and-forth across days is a record's Stages (ADR-0126 (Accepted));
  workflow-builder-ui's spike tests this limit (fixture F9, a three-level approval whose rejection returns to different
  earlier steps by reason) before anything is built on the document. v1 neither imports nor exports BPMN: if a customer
  asks for it, W3 brings a server-side importer of a subset that restructures a model into the tree or refuses it with a
  stable code (V4.28), and `bpmn-auto-layout` (MIT) can build the diagram for an export. domain-packs' workflows (W2)
  are tree documents too.
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
6. **Q-h5 (Đạt, before workflow-engine/06 is ready; asked there as workflow-engine Q4): an unknown outcome inside a
   parallel lane.** An outbound call that ends `outcome_unknown` parks its run on an `outcome_review` wait (decision
   5), but no wait sits in a parallel lane, whose parked node would sit in a checkpoint namespace the resume check does
   not read (decision 3), and neither V4.30 nor V4.34 says how such a run parks, for a lane's own call or for one
   still in flight in a lane that decision 11 cancels. Proposed: submit refuses with `wf.wait_in_parallel` every
   effect step inside a parallel lane whose Action's `on_unknown` is `review`, as every Action's is in W1 (H-5), so
   in W1 every step that sends an email, and no unknown outcome can arise inside a lane; W2 looks at it again when
   waits open inside lanes. The other way: the unknown outcome is a failure of its lane that no error lane catches,
   the other lanes are cancelled (decision 11), and the run parks on one `outcome_review` wait set on the
   `logic.parallel` step in the root graph, where the resume check finds the parked node, the block running again
   once it is resolved, each effect with a recorded outcome replaying by its key and the unknown one following the
   decision. Answered 2026-10-26: as proposed (workflow-engine R2.20).

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
- Third consistency check (round 4), third pass, the planner's provisional call: decision 4 compiles the draft a
  `simulate` run pins too, and keys the compiled-graph cache
  `(tenant_id, artifact_version_id, pinned_hash, compiler_version)`, `pinned_hash` being the run manifest's
  `definition_hash` or a draft's provisional hash, as workflow-engine R4.2 does, because a draft keeps its id while
  it is edited and a run resolves only from its manifest (if it is wrong, the key keeps the version id alone and
  every draft save evicts that draft's graph).
- Third consistency check (round 4), sixth pass, Đạt's V4.14: decision 5 checks the run's deadline from W1 and
  cancellation from W2, since ADR-0113 decision 3 now ships `deadline_at` in W1 and keeps only the cancel route in W2,
  which replaces the first round-4 line above that placed both in W2; decision 7 adds that in W1 the run's deadline
  ends a run still waiting on an approval, which has no expiry of its own until W2 (DO-31).
- Third consistency check (round 4), seventh pass, Đạt's V4.24, V4.26 and V4.28 after the canvas research, with the
  planner's provisional calls named at its end: decision 1's document is a tree of steps, each holding one lane per port
  of its type, with no `edges[]` and no position, where it was a graph of `nodes[]` and `edges[]`; decision 2 folds
  `logic.join` into the end of `logic.parallel` and adds `logic.break`, the catalogue keeping 32 types, and brings
  `logic.parallel`, the bounded do-while `logic.loop` with `logic.break`, and a `human.approval` that every one of
  several approvers must approve into the W1 tail after the critical path to YC94, replacing the first line above, which
  kept `logic.loop` in W2 and every cycle out of W1 (N7); decision 3 lowers the tree to the IR, retires
  `wf.join_required` and `wf.unbounded_cycle`, which a tree cannot produce, adds `wf.wait_in_parallel`,
  `wf.stop_in_parallel` and `wf.break_outside_loop`, allows waits in a loop body while still refusing them in a parallel
  lane or a `map` body, and only warns on the static worst-case step count (`wf.steps_may_exceed_limit`); decision 4
  compiles each parallel lane as a subgraph joined by a waiting edge, where it used `defer=True`, and a loop as a
  bounded cycle; decision 5 brings `on_error: route` into W1, adds `incident` ("Chạy tiếp từ Bước lỗi", ADR-0113
  decision 4), which parks only a `live` run, and makes the wrapper's run-level counter the step cap, since
  `recursion_limit` resets on every resume, Context recording the measurements; decision 7 adds the step every approver
  must approve (`approval_rule` `all`) and names the `expired` lane; Alternatives and Consequences record what was
  rejected, the W1 tail's new measurement in discovery 14, the tree's limit (fixture F9) and that v1 has no BPMN
  (V4.28). The names `incident`, `wf.wait_in_parallel`, `wf.stop_in_parallel`, `wf.break_outside_loop` and
  `wf.steps_may_exceed_limit` are the planner's (if one is wrong, workflow-engine's validator table names it and this
  decision follows), and so are `approval_rule` and decision 7's one approval per assignee under one wait, as
  workflow-nodes R12 states them (if that is wrong, the step opens one approval holding a decision per assignee, as
  R12's fallback says, and decision 7 follows). Decision 7 also says that under `all` only the decision that settles the step resolves its wait, where it had said that any decision does.

## Amendments (2026-10-25)

- Third consistency check (round 4), eighth pass, Đạt's V4.30, V4.33, V4.34, V4.35 and V4.37 with the planner's calls
  H-9, H-10, H-14 and H-18: decision 1's `outcomes[]` gets its reader, the names whose condition holds on the final
  state being written into the run's `outcomes` and compared by the gate's scenario cases (H-14); decision 2 brings
  `flow.subworkflow@1` into the W1 tail, its step opening a `child_run` wait (V4.33), which decision 3 counts among the
  waits refused in a parallel lane, decision 3's code list also naming `wf.variable_conflict`, the code workflow-engine
  R2.7 gives two lanes writing one variable; decision 4 passes `durability="sync"` on every invoke, pinned in the run
  manifest's engine section (V4.34); decision 5 retries an outbound attempt only on `not_dispatched` or a retryable
  `rejected`, applies no `on_error` to an `outcome_unknown`, which parks the run on an `outcome_review` wait, and
  replaces "a retry after a crash replays the stored result" with ADR-0108 decision 5's three cases (V4.30), and in
  `simulate` it applies a result the run pins for a step (H-18); decision 11, new, makes the execution semantics one
  section of workflow-engine's spec, a golden trace per rule run on every runner, with a failing lane cancelling the
  others and a record write in a lane being a per-field PATCH (V4.34); Alternatives keep the custom interpreter
  unbuilt on a reason that spike S-RT's numbers replace, with V4.34's options and decision rule, and drop the
  secret-version lane from the reasons a `failed` run is not reopened, since no run pins a secret version any more
  (V4.35, H-10); Consequences make discovery 14 the spike S-RT, which also runs V4.30's crash matrix (H-9), and add
  the tests of these rules; Open 6 records, without deciding it, Đạt's Q-h5, how a run parks when an effect inside a
  parallel lane ends `outcome_unknown` (workflow-engine Q4), with the planner's proposal to refuse at submit an effect
  step whose Action's `on_unknown` is `review` inside a parallel lane.

## Amendments (2026-10-26)

- Đạt answered Open 6 (Q-h5) as proposed: submit refuses with `wf.wait_in_parallel` an effect step inside a parallel
  lane whose Action's `on_unknown` is `review`, so in W1 no unknown outcome arises inside a lane (workflow-engine R2.20).
  Q-h6: `flow.subworkflow` calls only a workflow that declares a `triggers[]` entry of kind `call`, which joins tier B,
  and submit refuses any other with `wf.subworkflow_not_callable` (workflow-engine R2.21, R8.7). The status stays
  Accepted.
