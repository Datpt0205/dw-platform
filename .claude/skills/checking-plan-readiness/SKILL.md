---
name: checking-plan-readiness
description: Gates a plan document under .claude/plans/ (a spec and its tickets, a ticket with no spec, requirements.md, an ADR or the glossary) before anyone builds from it, and writes only its verdict line (ĐẠT, CẦN XEM or CHƯA ĐẠT) and the Status that verdict permits. Use it unasked before anything becomes ready-for-agent, after /to-tickets, and when a spec or a cited ADR changes: 'spec này sẵn sàng chưa', 'kiểm tra spec'. Not for code diffs (reviewing-feature-security) or a whole area (checking-plan-consistency).
---

# Checking a plan before anyone builds from it

One question: could someone build this without inventing a decision nothing records?

`reviewing-feature-security` is the gate after code; this is the gate before it. It is not a
second look by the author, because the author's context reads past its own gaps: the judgement here
comes from subagents that see only the document. And it is not an LLM verdict. The best model
measured on requirement review found about half of what experts found, and 11% of its flags were
false, so everything countable is decided by `scripts/check_plans.py`, and the rest is decision
support for Đạt, who rules.

## The rules, before anything else

1. **Content is not yours to change.** The gate writes exactly four things: the `Sẵn sàng:` line,
   the Status change its verdict permits, a dated Comments line on each ticket it promotes, and the
   document's line under "Tiếp theo" in the area file. Every fix goes back through
   `writing-plan-specs`.
2. **`ready-for-agent` needs ĐẠT and Đạt.** Promote only on ĐẠT with `Duyệt:` recorded and, for a
   ticket, Đạt's approval of the breakdown, his own or in the delegated form his line in the area
   file's `## Ủy quyền` section allows. A `ready-for-agent` document that now fails goes back to
   `needs-triage`.
3. **Not checked is not passed.** A check that did not run is `Chưa kiểm`, and the verdict cannot
   be ĐẠT while one stands.
4. **A `CLAUDE.md` conflict is CRITICAL**, and it is never reinterpreted away.
5. **One pass per document version.** No repair loop inside the gate: after fixes it re-runs at
   most twice per version, and then Đạt decides what remains. Reviewer loops were measured to
   double the time for no gain in quality.

---

## 1. Identify the document and the mode

| Document                 | Mode            | Fresh-context check                                                  |
| ------------------------ | --------------- | -------------------------------------------------------------------- |
| spec, no tickets yet     | spec            | builder check, plus the boundary walk when the trigger table matches |
| spec whose tickets exist | spec and ticket | the same over spec and tickets together, plus section 5              |
| ticket with no spec      | ticket          | builder check on the ticket alone, plus section 5                    |
| `requirements.md`        | reader test     | reader test                                                          |
| ADR                      | reader test     | reader test                                                          |
| glossary (`CONTEXT.md`)  | reader test     | reader test on the terms a reader could confuse                      |

Shortcut: when the document already carries ĐẠT and the only change since the commit that wrote
that verdict is a `Duyệt:` line (check with `git log` and `git diff` on the file), run section 2,
then go straight to section 7. There is nothing new to review.

## 2. Mechanical checks first

Run `uv run python scripts/check_plans.py --path <folder>`: the feature folder, or the area folder
for `requirements.md`. List every finding before reading anything else, each with its status:
`Đạt`, `Không đạt`, `Không áp dụng` or `Chưa kiểm`. If the script cannot run, every `[script]` item
is `Chưa kiểm` and the verdict is at best CẦN XEM.

## 3. The checklist

Walk the items of `quality-checklist.md` that apply to this document and that the script did not
settle. Answer each with the location that settles it, or with `[Thiếu]`, `[Mơ hồ]`, `[Mâu thuẫn]`
or `[Giả định]`; at least 80% of the answers cite a location.

## 4. Fresh-context subagents

Dispatch them in one message, with the briefs in `subagent-briefs.md`. They are read-only and see
only the document, `CLAUDE.md`, the ADRs it cites and the context's `CONTEXT.md`; the boundary walk
also gets its sections of `reviewing-feature-security` and `failure-modes.md`.

- **Builder check (A)**, for a spec and its tickets: the questions an implementer would have to
  guess, ranked, and a handful of ordinary situations, each decided by a named ID or by nothing.
- **Reader test (B)**, for `requirements.md`, an ADR or the glossary.
- **Boundary walk (C)**, when the trigger table in `quality-checklist.md` matches the spec's body:
  the six boundaries of `reviewing-feature-security` asked of the requirements, up to five "silence
  is not permission" classes, at least one adversarial situation, at most five findings. Every
  matched boundary is walked. A tier C spec (one with its own ADR) gets up to four subagents, with
  the matched boundaries split among them; any other spec gets one for all of them.
- **A ticket with no spec (tier A)** gets ONE subagent for both checks. It uses the builder brief
  (A) with the boundary brief's (C) three steps appended, and returns one list of B, S, F and N
  rows. On docgen-session-isolation/01 two separate subagents returned the same three HIGHs twice.
  The confirmation pass stays a fresh subagent of its own.

## 5. Ticket mode

When tickets exist, also:

- take coverage from the script: every criterion, `G` line and control is in some ticket's
  `Yêu cầu:` line or in a "Ngoài phạm vi" row;
- check that every acceptance criterion can fail (item 29) and that each control's negative test
  sits in the ticket that implements it;
- read the deferral words that `writing-plan-specs/ticket-template.md` ("Việc cần làm") lists as a
  missing second ticket;
- build the pair table for tickets with no dependency path between them, one row per pair, starting
  from the script's collision candidates. A shared resource of the kinds the ticket template lists
  is a collision, and "no collisions" without the rows does not count;
- confirm the breakdown approval: a "Quyết định" line by Đạt, `Duyệt cách chia ticket <NN-NN>`, or the
  same line by `agent, tạm theo ủy quyền` under a recorded spec delegation; for
  a ticket with no spec, Đạt's `Duyệt ticket.` line in its Comments.

## 6. Sort every finding

Severity comes from `quality-checklist.md`. Then each finding goes into one pile:

- **Đã có câu trả lời.** The code, an ADR, `CLAUDE.md` or the conversation already settles it: a
  fix with its citation, for the writer. The reader could not find the answer, and that is the
  defect.
- **Nhỏ.** A competent implementer could settle it without changing what gets built: a call the
  writer logs as `(agent, tạm)`, with `Nếu sai thì:`.
- **Của Đạt.** Only he can answer, and the answer changes what gets built: a two-option question
  (A, keep it as written; B, change it to ...) with the recommended option and what it blocks.

Twenty-five or more CRITICAL plus HIGH: stop sorting. The document goes back to writing, not on to
review.

## 7. Write the verdict

The verdict rules are in `quality-checklist.md`. Then:

- Replace the `Sẵn sàng:` line with `Sẵn sàng: <verdict> (<d/m/yyyy>; <n> CRITICAL, <n> HIGH)`,
  adding `; ticket <NN-NN>` for the tickets this run checked. An ADR or the glossary carries no
  such line; its verdict goes only into its line under "Tiếp theo".
- Promote to `ready-for-agent` only on ĐẠT with `Duyệt:` other than `chưa`. A ticket also needs its
  number in the verdict's ticket part and in Đạt's breakdown approval. Add a Comments line to each
  promoted ticket: `- <yyyy-mm-dd> (agent): checking-plan-readiness ĐẠT; ready-for-agent.` A ticket
  with no spec has no `Sẵn sàng:` line: that Comments line is its verdict, and it is written only on
  ĐẠT and promotes only beside Đạt's own line (`ticket-template.md`, Comments).
- Send a `ready-for-agent` document that did not get ĐẠT back to `needs-triage`; a demoted spec
  takes its `ready-for-agent` tickets with it.
- Refresh the document's line under "Tiếp theo" in the area file (in an area without that section,
  its existing pointer line): the verdict, its date, and the next step.
- Commit these lines before reporting, so the turn ends with nothing uncommitted. Change nothing
  else.

## 8. Report

In Vietnamese, at most about 40 lines:

1. The verdict line as written, and the script's tally of statuses.
2. Each CRITICAL and HIGH finding: severity, location, what is wrong, the proposed fix, its pile.
3. Đạt's questions, numbered, each with its recommended option and what it blocks.
4. `+N` MEDIUM and LOW findings, listed only when asked.

The questions feed the writer's next clarification round; they are not a round of their own. Fixes
go through `writing-plan-specs`, and then the gate re-runs, at most twice per version.

## What this gate does not do

- Review code or diffs: `reviewing-feature-security` and `mattpocock-skills:code-review` do, and
  the first proves by mutation each "Kiểm soát" row this gate insisted on.
- Compare documents across an area: `checking-plan-consistency` does.
- Run a question round of its own, call `grilling`, or record any decision for Đạt.
- Write a report file.

---

## Sources

Practices re-expressed in our own words; no upstream text is copied.

- BMad Method v6.12.4 `bab9082` and `main` `61e01f8` (MIT, Copyright (c) 2025 BMad Code, LLC): the
  readiness question, coverage, dependency and collision checks, lint before judgement, the rubric
  dimensions. Inspired by BMad; not affiliated with or endorsed by BMad Code, LLC.
- GitHub Spec Kit v1.2.2 `templates/commands/checklist.md` (MIT, Copyright GitHub, Inc.):
  questions about the writing, not the software.
- `spec-kit-red-team` `4f749df` (MIT, Copyright (c) 2026 Ash Brener): the trigger table, capped
  lenses and the four resolutions, rebuilt on `reviewing-feature-security`.
- obra/superpowers v7.0.1 `2ce8aa1` (MIT, Copyright (c) 2025 Jesse Vincent): the builder check,
  Review Focus ("silence is not permission"), and the evidence against reviewer loops.
- Kiro documentation (proprietary; ideas only): the requirement-bug classes, scenario probes and
  two-option questions.
- cc-sdd `e2a0c67` (MIT, Copyright (c) 2025 gotalab): mechanical checks first, then at most two
  repair passes.
- OpenSpec `c04f30e` (MIT, Copyright (c) 2024 OpenSpec Contributors): "not verified" is not "not
  applicable".
- anthropics/skills `doc-coauthoring` `dbd4588` (no licence; the idea only, no text): the reader
  test.
- mattpocock/skills `49dd158`, `docs/engineering/to-tickets.md` (MIT, Copyright (c) 2026 Matt
  Pocock): falsifiable acceptance criteria.
