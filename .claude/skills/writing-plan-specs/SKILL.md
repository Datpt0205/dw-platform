---
name: writing-plan-specs
description: Writes and revises the plan documents under .claude/plans/ in the house Vietnamese format (an area's requirements.md, each feature's spec.md) and owns their templates and the ticket template. Use to write or revise a spec or high-level requirements, or to write back answers to its open questions: 'viết spec', 'đặc tả', 'viết yêu cầu', 'sửa spec', 'làm rõ spec', 'trả lời câu hỏi mở'. Not for tickets (/to-tickets), the discovery map (/wayfinder), glossary terms or ADRs (domain-modeling), or code.
---

# Writing plan specs

A spec here is read by an agent that cannot ask its author anything. Every gap it meets, it fills
with a guess, and the guesses that hurt are the ones nobody sees: a tenant boundary assumed, an
approver inferred, a default that fails open. So this skill writes down decisions that were already
made, in a form a test can falsify, and refuses to make the ones that belong to Đạt.

It is also the one owner of the plan formats. Before it, nothing owned them, and fifteen specs spell
the controls heading three ways and "done" two ways. The templates in this folder are the format
now; nothing else restates them, and `scripts/check_plans.py` reads them rather than keeping its
own copy.

## The rules, before anything else

1. **Never guess a never-default answer.** The topics are group 3 of
   `.claude/skills/checking-plan-readiness/quality-checklist.md`, their one owner. Each is settled
   by a citation (a `CLAUDE.md` section, an ADR with its status, code at `path:line`) or by Đạt.
   Otherwise it gets `[CAN LAM RO: Q<n>]`. Authorization and state transitions are never settled
   by inference, however obvious the answer looks.
2. **Every line can fail a test.** Criteria are EARS-VN (`ears-vn.md`): one subject, one trigger,
   one `PHẢI`. Every `NẾU ... THÌ` that guards a never-default topic becomes a "Kiểm soát" row with
   its negative test.
3. **Link, never restate.** `CLAUDE.md`, an ADR or the context's `CONTEXT.md` already owns its fact;
   cite it. A second copy is the drift `failure-modes.md` #2 counts.
4. **Approval is Đạt's word; readiness is the gate's.** This skill sets `Status:` to `needs-triage`
   or `needs-info`, never `ready-for-agent`. It writes `Duyệt:` only when Đạt approves the written
   document, or when the area file records his delegation for that kind of document. It writes
   `Sẵn sàng:` only to reset it to `chưa kiểm`.
5. **A question turn writes nothing.** The draft, markers included, is written and committed in a
   turn of its own, or held until the answers come; the turn that asks Đạt only asks. The answers
   are applied in the next turn, together with the area file, and committed. A question round that
   leaves edits uncommitted makes `session-stop.sh` fire on every round.

---

## 1. Before writing: are the decisions there, and how big is this?

Decisions must already exist, from a `grilling` session, the area's wayfinder map,
`requirements.md` or this conversation. This skill records; it does not interview.

- If the request is foggy (more than three never-default unknowns, or nothing recorded), call
  `mattpocock-skills:grilling`, or tell Đạt to run `/grill-with-docs` or `/wayfinder`.
- If the plugin is not installed (`claude plugin list` shows it failed to load), stop and print
  `claude plugin install mattpocock-skills@claude-plugins-official --scope project`. Never improvise
  an interview in its place.

Size the work before writing a line, and say the size in one sentence:

| Tier | Signal                                                                                      | What gets written                                                      |
| ---- | ------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| A    | the change fits one sentence                                                                | a ticket only, in a folder with no `spec.md`: hand it to `/to-tickets` |
| B    | a feature of a few tickets                                                                  | a spec                                                                 |
| C    | a new seam, a new trust boundary, a cross-context dependency or an irreversible data choice | a spec plus its ADRs, through `mattpocock-skills:domain-modeling`      |

A tier A ticket follows `ticket-template.md` with `Yêu cầu: không (<lý do>)`; every ticket check
runs on it, and its own approval and gate lines in Comments stand in for a spec's (the template
says how). Several intents means the roadmap row in the area file changes first, then one spec each. A spec
past about 10 requirements, 8 tickets or 250 lines is two specs.

## 2. Modes

- **Spec mode** writes `.claude/plans/<area>/<feature-slug>/spec.md` from `spec-template.md`.
- **Requirements mode** writes `.claude/plans/<area>/requirements.md` from
  `requirements-template.md`, plus the area file's sections from the same file.
- **Revise mode** applies answers or checker findings to an existing document (section 7).

## 3. Spec mode

**Ground "Hiện trạng" first.** Write the questions a neutral fact-finder would ask (how does X work,
where does it live, what touches it) without saying what will be built: a question that knows the
answer it wants will find it. Read the code; cite `path:line` from the repository root, one anchor
per code span; stamp the heading with the short sha and the date you read. Then send one fresh
subagent to re-open every load-bearing citation and return each as verified, disputed or
overturned, and fix what it overturns. Tag each item `Thiếu`, `Chưa rõ` or `Ràng buộc`; a `Chưa rõ`
becomes an open question or a research ticket on the map, never a guess.

**Write "Mục tiêu".** Each requirement is `### R<n> — <tên>`, one line of who gets what, then its
criteria `R<n>.<m>` in EARS-VN. Against existing behaviour, mark the heading `[Sửa]`, `[Bỏ]` or
`[Đổi tên]` with the earlier behaviour's `path:line`; behaviour that must survive gets a `G<n>` line
with its regression test. IDs are never renumbered once cited; a withdrawn one keeps its line with
`[Bỏ]`.

**Settle or mark the never-default topics** (rule 1). Any other gap gets a provisional call in
"Quyết định": dated, `(agent, tạm)`, with `Nếu sai thì:` saying what changes if it is wrong. More
than three `[CAN LAM RO]` markers means the draft is not ready to show: go back to grilling or the
map, or split the spec.

**Fill "Kiểm soát".** One row per guarding `NẾU ... THÌ` criterion and per anti-goal (a failure even
if it works), with a control prefix unique in the area, the IDs it guards in `Yêu cầu`, and a
negative test that would go red if the control were removed. At code time the mutation check in
`reviewing-feature-security` proves each row; a row whose test cannot be imagined red is not a
control yet.

**Fill the rest** as the template says: "Trong phạm vi" (what this spec owns: tables, routes, ports,
events, screens), "Ngoài phạm vi" (each row with why and who owns it), "Phụ thuộc" (only platform
seams, consumer-declared Protocols and other specs' criteria by ID, plus a `Kiểm lại khi:` line),
"Tiêu chí xong", and "Câu hỏi còn mở" (owner, and `Chặn:` or `Không đổi:`).

## 4. Self-review, inline, once

1. Run `uv run python scripts/check_plans.py --path <folder>` and fix every finding it reports.
2. Walk groups 1-4 of `.claude/skills/checking-plan-readiness/quality-checklist.md` against the
   draft, then `.claude/rules/failure-modes.md` #1-#7 against each control. For each control,
   answer, in one line in your head, not in the document:
    - who reads it;
    - what owns the fact;
    - can its test fail;
    - what reaches the effect around it;
    - what removes what it creates;
    - what happens when the value is missing.

    The same holds for a ticket with no spec. On docgen-session-isolation/01 every HIGH the gate
    found was one of these shapes: a default that failed open, a guard reachable around, and a uid
    reused with residue.

3. Cut every sentence that restates `CLAUDE.md`, an ADR or `CONTEXT.md`, and link instead. A
   sentence that neither decides nor evidences anything goes.
4. Fix inline. There is no review loop here: independent review is the gate's job, once per
   version, and a reviewer loop was measured to double the time for no gain in quality.

## 5. Requirements mode

The same discipline one level up, with no stack: what and why only, so no "Hiện trạng" anchors and
no controls. Rule 1 still holds, asked of what users need. In place of section 3:

- State the problem in the problem space, with the cost of inaction.
- `YC<n>` requirements in EARS-VN; `KQ<n>` outcomes with a unit, a baseline or `chưa biết`, a
  target, a counter-measure and how each is measured.
- Evidence tagged with its source (or `GIẢ ĐỊNH`) and confidence; "Bằng chứng ngược" is mandatory.
- Two or three options, always including `Nhỏ nhất làm được` and `Không làm gì`, each with a time
  budget; then the template's skeptical questions, each answered.
- **Preservation pass.** One fresh subagent per input (`discovery/brainstorm.md`, the decisions in
  `discovery/map.md`, each file in `discovery/research/`) returns only the load-bearing claims that
  landed nowhere. Land each, or log its deliberate drop in "Quyết định".
- A verdict per candidate feature, as a "Quyết định" line in the template's fixed form: `làm`
  becomes a roadmap row and needs evidence `đủ` or better, `cần làm rõ` becomes a `Q<n>`, and `dừng`
  becomes a "Không làm" line.
- Write the roadmap rows and the reserved ADR number block into the area file's sections.

## 6. The clarification round

Only when markers or never-default gaps remain after self-review, and once per document version.

- Look first: the code, `CLAUDE.md`, the ADRs, the conversation. A question the repository already
  answers spends Đạt's attention, which is the budget this whole pipeline runs on.
- At most five independent questions, ranked by impact times uncertainty. Each is a full sentence
  naming its ID, with `Vì sao quan trọng:`, `Đề xuất:` (a recommended option and its reason, so
  "đồng ý" accepts it), and two to five options or a short free answer.
- Who may act, approve or change something, and state transitions, are always asked.
- Layout, feel and state-model questions go to `mattpocock-skills:prototype` instead.
- A question several specs share is asked once, and its answer becomes one ADR (Proposed) or one
  glossary term through `mattpocock-skills:domain-modeling`, with the ADR number taken from the
  block reserved in the area file.
- Ask in Vietnamese, in chat, and write nothing in that turn (rule 5).

## 7. Writing answers back (revise mode)

In the turn after the answers:

- Log each answer in "Quyết định": dated, who decided, `Hỏi: Q<n>.`, `Sửa: <mục hoặc mã>.` A
  suggestion Đạt declines is logged as `Không nhận:` so it is not raised again without new evidence.
- Apply each answer where it belongs. Remove the text it contradicts, its marker and the answered
  question; never leave the old and new versions side by side.
- A change to "Mục tiêu", "Hành vi giữ nguyên", either scope section, "Kiểm soát" or "Phụ thuộc"
  resets `Sẵn sàng:` to `chưa kiểm` and `Duyệt:` to `chưa`, and sets a `ready-for-agent` spec and its
  `ready-for-agent` tickets back to `needs-triage`. An approval covers the text Đạt read, not this
  one.
- Gate findings arrive the same way: a fix with a citation is applied; a minor call is logged
  `(agent, tạm)`; a question for Đạt goes into the next round.
- Build discoveries arrive as ticket Comments (`Đề xuất đổi R2.1: ...`). Apply them at the source
  once Đạt agrees: product scope in `requirements.md`, a cross-spec rule in an ADR, one feature in
  its spec.

## 8. Closing

- `Status: needs-triage`, or `needs-info` while a question without `Không đổi:` stands.
- Refresh the roadmap row and the feature's one line under "Tiếp theo" in the area file: one line
  per feature folder, never one per ticket.
- Run prettier on the touched files (`pnpm exec prettier --write <files>`), then commit the
  documents together with the area file.
- Run `checking-plan-readiness` on the document. Once Đạt approves a spec, tell him to run
  `/to-tickets` for it: tickets follow `ticket-template.md` and start at `needs-triage`.

## What this skill does not do

- Interview, map an area or slice tickets: `grilling` and `/grill-with-docs`, `/wayfinder` and
  `/to-tickets` do. Glossary terms and ADRs are written through `mattpocock-skills:domain-modeling`,
  under the overrides in `docs/agents/domain.md`.
- Use `/to-spec`: its English, path-free template contradicts this one and publishes straight to
  `ready-for-agent`, past every gate.
- Judge its own output. `checking-plan-readiness` does that with fresh eyes, and
  `checking-plan-consistency` across the area.
- Write report files, or anything outside the layout in `docs/agents/issue-tracker.md`.

It calls these plugin skills by name: `grilling` (fog), `prototype` (questions a sentence cannot
settle), `domain-modeling` (terms and ADRs), `research` (facts outside the repository, saved to
`.claude/plans/<area>/discovery/research/<slug>.md`) and `codebase-design` (two designs for a tier C
ADR's options). Its "Kiểm soát" rows are what `reviewing-feature-security` later proves by mutation,
and its IDs are what `mattpocock-skills:code-review` quotes when it is given the spec's path.

---

## Sources

Practices re-expressed in our own words; no upstream text is copied.

- GitHub Spec Kit v1.2.2, `dc2cec4` (MIT, Copyright GitHub, Inc.): capped clarification markers,
  success criteria, the clarify taxonomy and write-back, the roadmap pass, the assess funnel.
- `speckit-grill-me` `595ae51` (MIT): authorization and state transitions are never inferred.
- EARS: Mavin, Wilkinson, Harwood and Novak, "Easy Approach to Requirements Syntax", IEEE RE 2009,
  DOI 10.1109/RE.2009.9. Lint signals after `spec-kit-ears` `d570162` (MIT).
- cc-sdd `e2a0c67` (MIT, Copyright (c) 2025 gotalab): the subject rule, boundary commitments, gap
  tags.
- OpenSpec `c04f30e` (MIT, Copyright (c) 2024 OpenSpec Contributors): delta marks, the removal
  check, deferrable open questions.
- Kiro documentation (proprietary; ideas only): the unchanged-behaviour clause.
- BMad Method v6.12.4 `bab9082` and `main` `61e01f8` (MIT, Copyright (c) 2025 BMad Code, LLC):
  source-citing IDs, the marker vocabulary, the preservation pass, intent-blind research with a
  verifier, the skeptical question bank. Inspired by BMad; not affiliated with or endorsed by BMad
  Code, LLC.
- obra/superpowers v7.0.1 `2ce8aa1` (MIT, Copyright (c) 2025 Jesse Vincent): look before asking,
  provenance marking, sizing, the inline self-review.
- mattpocock/skills `49dd158` (MIT, Copyright (c) 2026 Matt Pocock): the spec as a decision record,
  facts versus decisions. `grilling`, `domain-modeling`, `prototype`, `research` and
  `codebase-design` are called, not copied.
