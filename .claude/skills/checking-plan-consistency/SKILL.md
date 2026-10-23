---
name: checking-plan-consistency
description: Reads a whole planning area under .claude/plans/ as a set (requirements.md, the specs, ticket headers, ADRs, glossary, CLAUDE.md) and reports contradictions between documents, read-only, ranked by severity, and refreshes the area's wave plan. Use after each wave of specs, before cutting the next wave's tickets, when an ADR changes status, and before calling planning done: 'kiểm tra nhất quán', 'các spec có mâu thuẫn không'. Not for one document's readiness (checking-plan-readiness).
---

# Checking an area's plans against each other

Every spec can pass its own gate and the set can still be wrong: two of twenty specs owning one
route, a producer and a consumer disagreeing on an event's fields, a studio spec quietly deciding
again something `CLAUDE.md` reserves to the platform, a glossary term drifting, a spec built on a
Questioned ADR. No single author can see these, because each is a fact about two documents. This
skill reads the area as a set.

It changes no content, and its findings are decision support: model recall on this kind of review
is about half, so Đạt picks what gets fixed, and every fix goes through `writing-plan-specs`.

## The rules, before anything else

1. **Read-only.** It writes two things in `.claude/plans/<area>.md`, the outcome line and the wave
   plan under "Đợt", and nothing in any spec, ticket, ADR or glossary.
2. **A `CLAUDE.md` conflict is CRITICAL**, and never reinterpreted. Every other severity follows
   the "Severity" section of `.claude/skills/checking-plan-readiness/quality-checklist.md`, so the
   two checkers speak one vocabulary.
3. **At most 50 findings, with stable IDs**: an ID is built from what the finding compares, not
   from where it sits in the report, so fixing one finding or editing a line elsewhere does not
   renumber the rest, and "sửa B:alpha:R2.1~beta:R1.3" still means the same finding after a re-run.
4. **A decomposition problem is not patched locally.** Two specs that should be one, or a gap that
   no spec owns, goes back to the roadmap row or the wayfinder map.
5. **At most three remediation rounds per wave.** After that, escalate to Đạt with what remains.

---

## 1. Mechanical checks

Run `uv run python scripts/check_plans.py --area <area>` and take its findings as given: IDs,
links, statuses, dependency cycles, coverage (YC to roadmap, criteria and controls to tickets),
anchors, stray trackers, duplicate ADR numbers, collision candidates. A check that did not run is
reported as `Chưa kiểm`, never as clean.

## 2. Inventories

Build these in the session. They are working memory, not output; never echo them raw.

- The roadmap rows, the `YC` and `KQ` IDs, and each spec's `R`, `G` and control IDs.
- Each ticket's header lines: `Status`, `Blocked by`, `Yêu cầu`.
- The ADRs: number, status, and the decision rule each states.
- The glossary terms and the synonyms each avoids (the `CONTEXT.md` that `CONTEXT-MAP.md` names).
- The MUST statements of `CLAUDE.md` that the area touches.

## 3. Reviewer subagents

One read-only subagent per wave, or per about eight specs. Give it the wave's specs and their ticket
headers, `requirements.md`, the ADRs they cite, `CONTEXT.md`, `CLAUDE.md`, and a compact list from
the inventories of what every other wave owns and the contracts it states, so a contradiction across
waves is visible too. It reads each spec in this order: "Trong phạm vi" and "Ngoài phạm vi",
"Kiểm soát", the criteria that carry a contract, "Phụ thuộc", then the ticket headers. It returns
only rows, at most ten per pass, in Vietnamese:

`<pass> | <path:line> | <path:line of the other side, or -> | <what disagrees> | <proposed severity>`

- **A. Duplication:** one capability or one requirement owned by two specs; one fact written in two
  places.
- **B. Contracts:** producer against consumer, for routes, payload fields, event types,
  `details.reason_code` values, audit event names and scopes.
- **C. Boundary partition and ticket collisions:** a pair table of the specs, and of the tickets
  with no dependency path between them, that touch one resource of the kinds
  `writing-plan-specs/ticket-template.md` lists. "Clean" without the rows does not count.
- **D. Platform concerns specified again:** tenancy, authorization, audit, approval, spend,
  evidence, memory writes, retrieval filters. What `CLAUDE.md` says a second language must not take
  over, a second spec must not take over either: deciding one of these again is a second answer to
  a question that must have one.
- **E. `CLAUDE.md` non-negotiables:** each conflict, with the section it breaks.
- **F. ADRs:** each decision several specs follow has exactly one home; the status a spec cites
  matches the ADR file; nothing builds on a Questioned or Superseded ADR without saying so.
- **G. Terminology:** a term used against its `CONTEXT.md` definition, or a synonym the glossary
  avoids.
- **H. Coverage, both ways:** a YC that no roadmap row serves and no "Không làm" line defers; a KQ
  with no way to measure it; a roadmap row with no spec, or a spec with no row; a deferred item a
  later spec absorbed without saying so.
- **I. Dependencies and waves:** "Phụ thuộc" against `Blocked by` against what the text actually
  references; a dependency nobody declared; a cycle; a wave that needs something a later wave
  builds.

## 4. Merge

In the main context:

- Drop duplicates and keep the more severe copy. Apply the severity rules; any `CLAUDE.md` conflict
  is CRITICAL.
- Give each finding its stable ID from its content: the pass letter, then the two things it
  compares, each as `<feature-slug>:<ID>` (or the file path when the side has no ID), sorted and
  joined by `~`: `B:alpha:R2.1~beta:R1.3`. A finding about one place has one side
  (`H:requirements.md:YC4`). Only when two findings get the same ID does a counter follow, in
  path:line order: `#2`. Line numbers never enter an ID, so an edit above a finding does not move
  it.
- Keep at most 50 rows, most severe first. Past 50, say how many were cut and at which severity.
- Add the coverage metrics: YC served, criteria and controls covered by tickets, KQ with a measure,
  specs per wave.
- End with the next actions: what goes to `writing-plan-specs`, what goes back to the roadmap or the
  map, and which questions only Đạt can answer.

## 5. Write the outcome

Only these two things, in `.claude/plans/<area>.md`, then commit:

- the outcome line at the top of "Đợt", replacing the previous one:
  `Kiểm nhất quán <d/m/yyyy>: <n> CRITICAL, <n> HIGH, <n> MEDIUM, <n> LOW; phủ YC <x>/<y>, tiêu chí <x>/<y>.`
- the wave plan below it, refreshed: which specs are ready to ticket next, and what blocks the
  rest.

The report itself goes to chat, in Vietnamese: the rows, the metrics, the next actions. Edits stay
proposals until Đạt picks the rows; then `writing-plan-specs` applies them, and this skill runs
again on the changed wave.

## When to run it

After each wave of specs has been through `checking-plan-readiness`; before `/to-tickets` for the
next wave; whenever an ADR changes status (`docs/agents/domain.md`); and before calling an area's
planning complete. It never calls `grilling` or `domain-modeling` itself.

---

## Sources

Practices re-expressed in our own words; no upstream text is copied.

- GitHub Spec Kit v1.2.2 `templates/commands/analyze.md` (MIT, Copyright GitHub, Inc.): the passes,
  constitution conflicts as CRITICAL, at most 50 findings, stable IDs, read-only.
- cc-sdd `e2a0c67`, `kiro-spec-batch` (MIT, Copyright (c) 2025 gotalab): the cross-spec checks, at
  most three rounds, decomposition sent back to the map.
- BMad Method v6.12.4 `bab9082` (MIT, Copyright (c) 2025 BMad Code, LLC): one home per shared
  decision, collisions, coverage across the tree. Inspired by BMad; not affiliated with or endorsed
  by BMad Code, LLC.
- obra/superpowers v7.0.1 `2ce8aa1`, `subagent-driven-development/references/preflight.md` (MIT,
  Copyright (c) 2025 Jesse Vincent): a scan without its rows is not a scan.
