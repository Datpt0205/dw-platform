---
status: Proposed
date: 2026-11-04
source:
    - ../../.claude/plans/studio/requirements.md
    - ../../.claude/plans/studio/autonomy-evidence/spec.md
    - ../../.claude/plans/studio/digital-worker/spec.md
    - 0128-digital-workers-follow-the-casanos-standard.md
---

# 0129. A Digital Worker earns autonomy per decision class from evidence, and loses it on a bad signal

Numbered in the block 0100-0199 reserved for Studio (ADR-0100 (Accepted) decision 9). It records D19 of 2026-11-04
(Đạt): fewer human checks come from evidence, never from removing a check. It builds on ADR-0128 (Proposed), whose
decisions 3, 5, 8 and 9 it extends and none of which it changes. Proposed until Đạt reads it.

## Context

ADR-0128 gives a Digital Worker (DW) one earned level per decision class, raised only by its Business Owner with a
second person's approval and lowered by one person at once (decision 5), and a scorecard computed from data (decision
9). What the code has today (read at `9d5f06f`, 2026-11-04):

- The gate writes one audit row `dw.decision.auto` per decision a DW takes alone, naming the decision class, and opens a
  `dw.decision` approval for every other one (`packages/python/dw_platform/src/dw_platform/application/decision_gate.py:85-143`).
- A decision records whether the person edited the proposal (`platform.approval_decisions.edited`,
  `packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:411-415`).
- The scorecard counts approvals as proposed, edited and rejected for the DW as a whole, not per class, and does not
  count the decisions taken alone (`packages/python/dw_platform/src/dw_platform/adapters/persistence/dw_autonomy_repo.py:61-131`).
- A raise is opened only by the Business Owner and decided by the Validator or the Technical Owner
  (`packages/python/dw_platform/src/dw_platform/application/dw_autonomy.py:64-73`, `:219-246`).
- The ladder lets A3 take a reversible external decision alone and only A4 an irreversible one; nothing takes a
  `critical` one alone (`packages/python/dw_kernel/src/dw_kernel/autonomy.py:58-99`).

So a Business Owner who wants a DW to ask less has one lever, a raise on judgement, with nothing on the screen saying
whether this class has earned it, and nothing that takes the level back when the DW starts getting it wrong. The
cheap way out, lowering the HITL floor or letting a class run unasked, is what D19 rules out.

## Decision

1. **Evidence is kept per decision class, and computed.** For each class of a DW, over a window: the decisions it took
   alone (the `dw.decision.auto` audit rows), the ones it asked about (`dw.decision` approvals, each marked whether the
   ladder required a person or it was sampled, decision 5 below), and of those asked, approved as proposed, approved
   edited and rejected. The class's _auto rate_ is alone over alone plus asked; its _edit rate_ is edited over
   approved. Both are read from the audit trail and the approval decisions, which already hold every fact, never from a
   counter of their own and never from what the DW reports (ADR-0128 decision 9). The auto rate is D19's measure (KQ16)
   and the edit rate its counter-measure.
2. **A raise is proposed on evidence.** A class becomes eligible when the last N decisions of it that a person
   decided, at its current earned level and since its last level change, were all approved as proposed. An edit or a
   rejection restarts the count; so does any change of level. Only a decision of the DW's Validator or Business Owner
   counts, which is who the gate admits (ADR-0128 decision 8). N is a platform policy value a tenant may only raise
   (ADR-0110 (Accepted)), and is left empty until it is measured (decision 7).
3. **The system opens the raise; two people still make it.** A worker lane, acting as itself (ADR-0011), opens a
   `dw.autonomy.raise` for an eligible class, one level up, never above the class's ceiling, never while another raise
   of that class is pending (the index of digital-worker R8.4), and never when the tenant's autonomy ceiling already
   caps the class's effective level, where a raise would change nothing. The lane is not a person, so ADR-0128 decision
   5 and D11 still ask for two: the Business Owner adopts the proposal, which makes them its proposer, and the
   Validator or the Technical Owner then approves it as today. Adopting does not change the level; its decision opens
   the person-proposed raise through the type's `.decided` handler, so the existing admission, staleness check and
   audit decide it. Declining the proposal restarts the class's count.
4. **A bad signal lowers the level at once.** Lowering takes one person (ADR-0128 decision 5), so the platform may do
   it on its own rule. A signal is: a person rejecting a decision of a class whose effective level would have let it
   run alone (a sampled decision, decision 5), or the edit rate of a class's last M sampled decisions passing a
   threshold. On a signal the class drops to the highest level at which the ladder still asks a person for it (A3 for
   an irreversible external class, A2 for a reversible one, A1 for an internal one), in the transaction of the decision
   that carried the signal, so no other gate of the DW runs alone on the old level. The lowering audits as the system
   actor of the rule's lane, naming the approval that carried the signal; a raise pending for that class goes stale by
   the existing check. M and the threshold are policy values left empty until measured.
5. **At A3 and A4 a person reviews by exception, plus a sample.** Where the ladder lets a class run alone at A3 or A4,
   the gate still asks a person, before the effect, for a sampled share of its decisions, through the same
   `dw.decision` approval marked `sampled`. Whether one decision is sampled is a deterministic function of its run,
   step and class against the rate, so a resume or retry asks the same question and nothing the model writes can steer
   it. The exceptions of ADR-0128 decision 7 still hand the item to a person whatever the level. The rate is a policy
   value left empty until measured; a rate that cannot be read samples every decision. This reopens DO-18 (every pilot
   message approved) as Q11 of `requirements.md`, for Đạt.
6. **Nothing here loosens a floor.** No decision of this ADR lets a `critical` class run alone, removes the
   `dw.decision` gate, lowers a ceiling's meaning or makes a raise a one-person act. A class whose ceiling is below the
   level evidence would earn stays at its ceiling: the evidence shows on the scorecard and nothing is proposed.
7. **The numbers are measured, then set by Đạt.** N, the sampling rate, M and the edit-rate threshold are measured on
   the lead-care DW running the 200 synthetic leads of marketing-pilot/01, with every proposal decided by a real person
   rather than a script, since a scripted approver produces the evidence it was written to produce. Until a value is
   set, its policy entry is empty, and an empty value fails closed: no raise is proposed, every A3 and A4 decision is
   sampled, and the edit-rate signal fires on any edit.

## Alternatives considered

- **Raise automatically once the evidence is there.** Rejected: a loosening with no person is what D11 and ADR-0128
  decision 5 forbid.
- **A system-proposed raise decided by the Validator or the Technical Owner alone.** Rejected: the lane is not a
  person, so one approval would make a loosening a one-person act.
- **Sample after the effect.** Rejected for every class: an irreversible effect reviewed afterwards is a report, not a
  check, and one rule for every class keeps the gate one answer.
- **A counter table of decisions per class.** Rejected: the audit trail and the approval decisions already hold each
  fact, and a counter is a second copy that drifts (`failure-modes.md` #2). The audit is read through an index.
- **Lower one rung on a signal.** Rejected: one rung down from A4 still lets a reversible external class run alone, so
  the signal would change nothing; dropping to the highest level that asks restores the person exactly.

## Consequences

- Positive: the Business Owner sees per class why a DW asks and what it would take to ask less, and a class that starts
  failing goes back to a person without anyone noticing first.
- Negative: evidence rewards approving. A person who approves without reading inflates it. Opening an approval's page
  records a view receipt (`platform.approval_view_receipts`), but a decision from the inbox records none and KQ2's
  "decided within seconds of opening" has no threshold yet, so this ADR does not discount such approvals (Open 2).
- Negative: until the numbers are set, every A3 and A4 decision asks a person, which is stricter than today's
  behaviour for a class already at A3.
- Negative: a DW's ceilings are fixed with its configuration (digital-worker, Quyết định of gate round 2), and the
  Marketing pack gives `email.send` a ceiling of A2, so the lead-care DW cannot earn past A2 on sending without a new DW
  or a way to change a ceiling (Open 1).

## Open

1. Whether a ceiling may change on a live DW, with two people, or only by making a new DW (Đạt).
2. How an approval decided without reading is recognised and kept out of the evidence (W2, with KQ2's measurement).
3. The values of N, the sampling rate, M and the edit-rate threshold (decision 7).
