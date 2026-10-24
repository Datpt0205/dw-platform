---
status: Accepted (Đạt, 2026-10-24, on the direction in the decision brief; details revisited when its wave starts)
date: 2026-10-24
source:
    - ../../.claude/plans/studio/workflow-engine/spec.md
    - ../../.claude/plans/studio/workflow-triggers/spec.md
    - ../../.claude/plans/studio/custom-objects/spec.md
    - ../../.claude/plans/studio/workflow-builder-ui/spec.md
    - ../../.claude/plans/studio/workflow-nodes/spec.md
    - 0112-workflows-compile-to-langgraph-one-effect-per-node.md
    - 0113-every-run-is-requested-and-queued-in-postgres.md
    - 0101-studio-canvas-is-an-allowlisted-ui-exception.md
---

# 0126. A long process is an object's lifecycle in stages: entering a Stage starts short workflows through a record event, and no run outlives its deadline

Numbered in the block 0100-0199 reserved for Studio (ADR-0100 records the block). It rests on Đạt's decision N5 of
2026-10-24, one of the coverage review's proposals N1-N10 of 2026-10-23, whose process research found that a business
process lasting months (a lead's way to a sale, a purchase, a hire) cannot live in one run. It is W2, requirement
YC102. The `workflow-engine` spec owns it; custom-objects and workflow-builder-ui own its two views.

## Context

- **A run cannot hold a process that lasts months.** From W2 every run has `deadline_at = admitted_at +
min(limits.max_run_seconds, plan ceiling)`, waits included, 30 days by default and at most 90 (ADR-0113 decision 3).
  A run finishes on the version and run manifest it started with (ADR-0109 decision 6), and moving a waiting run to a
  new version is a W3 row of workflow-engine, so a fix to a workflow reaches no record already inside one of its runs.
- **Sub-workflows do not stretch it.** A child run shares its root's run-as principal, budget lease and limits and
  nests at most 3 deep (ADR-0112 decision 6, ADR-0113 decision 9, requirements Q1), and the root's deadline counts its
  wait on the child (ADR-0113 decisions 3 and 4). The parent pins each child version at submit (DO-30), and each child
  has its own gate and second person (D11, ADR-0120), so changing one node of a child means publishing the child and
  submitting the parent again.
- **No wait may sit inside a parallel branch in v1** (ADR-0112 decision 3), so one run cannot let two people work on
  two parts of one record at once.
- **The parts already exist, in W2.** `trigger.record_event` fires on the false-to-true edge of a condition over `old`
  and `new`, never on the subscribing workflow's own writes (`suppressed_self`), never above chain depth 8
  (`suppressed_loop`, tenant admins notified) and at most 5 runs per hour per workflow and record
  (`suppressed_budget`); `RecordService` stamps `origin_run_id` and `chain_depth` from the run context, never from
  input (ADR-0113 decision 8). Such a run acts as the version's bound service principal (ADR-0103 decision 4). A
  picklist holds one of a fixed list of option keys, and a field in an indexed slot filters and sorts (ADR-0107
  decision 1).
- **Nothing names a part of a process.** `dw.workflow/v1` has no grouping of nodes, the canvas stores no positions
  (ADR-0101 decision 3), and the glossary gives "Giai đoạn" to the version stage (`draft` to `retired`, ADR-0120
  decision 1), the word a builder would otherwise reach for.

## Decision

1. **A long process is the lifecycle of one object.** Each record of the object goes through the process, and where it
   stands is the value of one picklist field of that object, its status field; each option of the status field is a
   Stage (Chặng). The record, in PostgreSQL under record access and field security (ADR-0105, ADR-0106), is the one
   owner of its Stage: no run, checkpoint or Studio table holds it, and Studio keeps no list of Stages beside the
   picklist's options (failure-modes #2).
2. **Entering a Stage starts short workflows through a record event.** A workflow that belongs to a Stage subscribes
   with `trigger.record_event` on the object, its condition being the status field equal to that Stage's option key,
   fired on the edge (`fire_when: becomes_true`, ADR-0113 decision 8). One Stage may start one or a few workflows, each
   a separate run requested through `RunRequestService` (ADR-0113 decision 1) on the version live when the event fires,
   acting as its bound service principal (ADR-0103 decision 4). The guards of ADR-0113 decision 8 apply unchanged. No
   trigger kind, node type, artifact kind or engine construct is added for Stages.
3. **Moving a record to another Stage is an ordinary record write.** A node writes the status field with
   `data.object.update` through `RecordsPort` (ADR-0112 decision 6), or a person changes it on the record form; either
   is a `RecordService` write with its validation, field security, record access, outbox event and audit (ADR-0107
   decision 3), and that write fires the next Stage's record event. A node's write carries its run's chain depth; a
   person's write starts a new chain.
4. **A run keeps its deadline.** ADR-0113 decision 3 stands: 30 days by default, at most 90, waits included. A process
   lasting months is a chain of short runs along the record's lifecycle: between two Stages the record waits, not a
   run, so no checkpoint is held for months; and each Stage entry runs the version live when it fires, so a changed
   process applies from the next Stage without moving waiting runs.
5. **Sub-workflows are for reuse only.** `flow.subworkflow` (W2) runs a part that several workflows share, as a child
   run under ADR-0113 decision 9; it is never the way to divide a long process into nested parts.
6. **Views by Stage carry no run meaning.** custom-objects shows an object's records grouped by the options of its
   status field: one keyset list per Stage through `RecordService`, filtered on the status field and so needing it in
   an indexed slot (ADR-0107 decision 1), with the capped count of custom-objects R8.8 and no aggregate query
   (ADR-0127 places aggregates in W3). workflow-builder-ui lets a builder put a Stage label on a node (Bước), an
   optional property of the node in the `dw.workflow/v1` document that the canvas and the outline view read to group
   nodes and collapse a group. Validation checks only its shape; the compiler, the run and `RecordService` never read
   it, so a label moves no record, and two documents that differ only in labels compile to the same graph.
7. **A Stage is not a version stage.** "Chặng" is the UI term, and the glossary records it with "Giai đoạn" among the
   words to avoid, since "Giai đoạn" stays the version stage of ADR-0120 decision 1. No column or code name `stage` is
   added for a Stage: `stage` is the version stage's column on `studio.artifact_versions`.

## Alternatives considered

- **One long run per record**, a workflow that waits weeks or months at each part. Rejected: the deadline caps a run
  at 90 days; a parked run holds its checkpoint and pinned version for the whole wait; and a fix reaches no record
  already inside a run until waiting runs can move versions (W3).
- **A higher deadline ceiling for long processes.** Rejected: the deadline is what bounds a parked run's checkpoint,
  waits and manifest (failure-modes #6); a higher ceiling moves the limit without removing it, and a run waiting a
  year keeps a year-old version.
- **Sub-workflows as the parts of a long process.** Rejected: children share the root's deadline and nest at most 3
  deep, and the parent pins each child at submit, so a change to one part takes two publishes; a Stage's workflow is
  published alone.
- **A stage construct in the engine**: groups of nodes in `dw.workflow/v1` with run semantics, or a state-machine
  artifact kind. Rejected: a second owner of where a record stands beside the record itself (failure-modes #2), and a
  new kind with its own validator, compiler and gate for what a picklist and a record event already express.
- **The Stage label beside the document**, in a store keyed by node id, as positions are kept out of it. Rejected:
  positions are computed by dagre and need no store (ADR-0101 decision 3); a label is typed by a person, and a store
  beside the version would drift from the nodes it labels and escape the review that approves them.
- **"Giai đoạn" for both.** Rejected: one word for two lifecycles, the version's and the record's, on the same
  screens.

## Consequences

- **Owners and wave.** workflow-engine owns this model, the unchanged deadline and the label's place in the
  `dw.workflow/v1` model it already owns; custom-objects owns the view by Stage; workflow-builder-ui owns the Stage
  label's grouping on the canvas and in the outline view; workflow-triggers' record-event trigger serves Stage entry as
  it is. All of it is W2 (YC102); W1 builds nothing for it. The glossary gains "Chặng" (Stage).
- **A Stage entry is never lost to a limit.** It is a `record_event` run: over a spent limit it waits in the queue
  until `resets_at`, and a freeze holds it until lifted (ADR-0113 decision 3, ADR-0120 decision 7; `CLAUDE.md`, Agent
  and tool rules).
- **Automatic moves are capped.** A record whose Stages advance by nodes more than 8 times in one chain stops at
  `suppressed_loop`, tenant admins notified (ADR-0113 decision 8); a person's write starts a new chain.
- **Parallel work is separate runs.** Several workflows subscribed to one Stage run as separate runs, each free to wait
  for a person, so one record gets parallel human work without a wait inside a parallel branch.
- **Each Stage changes alone.** A Stage's workflows are artifacts of their own, each published through its gate and a
  second person (D11), so changing one Stage touches only its workflows.
- **The view obeys field security.** A viewer from whom the status field is hidden gets no view by Stage (422
  `field_not_readable`, ADR-0106 decision 4).
- **History needs no new store.** The record history of the status field, when the field is tracked (ADR-0107
  decision 6, W2), says when a record entered each Stage; totals over it are reports (ADR-0127).
- **A label costs an evaluation.** Renaming a Stage label changes the definition hash, so the version passes the gate
  again like any other edit (ADR-0120 decision 3).
- **Tests that must exist** (W2), each red when its guard is removed: a node's write of the status field starts each
  workflow subscribed to the new Stage once; leaving and re-entering a Stage starts them again; the subscribing
  workflow's own write starts nothing; the ninth automatic move in one chain is suppressed; two documents that differ
  only in Stage labels compile to the same graph; a view by Stage for a viewer without read on the status field is
  refused.
- **Revisit** if W2 shows a record that must be in two Stages at once, which one status field cannot hold, or a real
  lifecycle stopped by the record-event guards of ADR-0113 decision 8.

### Contradictions and amendments

- `CLAUDE.md` does not change; ADR-0103 and ADR-0113 are reused unchanged, and ADR-0112 decision 1 gains one optional
  node property, the Stage label, which has no run meaning.
- Refines ADR-0101's reason against stored positions without contradicting it: a position changes on every drag and
  can be derived, so storing it would churn the hash; a label is typed once, is part of what a reviewer approves, and
  has no other home.
- The glossary's version stage (Giai đoạn) keeps its meaning; "Chặng" is added beside it, never in place of it.

## Open

1. **Which picklist is the status field** when an object has several: named once in the object's `dw.object/v1`
   version, or chosen by each view and each Stage-entry trigger (custom-objects with workflow-builder-ui, when W2
   starts).
2. **What a Stage label holds**: free text, or the option key of a Stage of the object the workflow's trigger names,
   checked at submit (workflow-builder-ui, when W2 starts).
