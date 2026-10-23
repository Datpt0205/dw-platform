# Plan quality checklist

This file owns five things: the checklist items, the list of never-default topics (group 3), the
severity rules, the verdict rules, and the trigger table for the boundary walk. `checking-plan-readiness` uses all of it.
`writing-plan-specs` walks groups 1-4 as its self-review. `checking-plan-consistency` uses the
severity rules. Nothing else restates them.

The items check the writing, not the software. Each is a question about what the document says,
never "verify that X works": that is a test's job, later, against code.

## How to answer an item

- Answer with the location that settles it (`spec.md:41`, `R2.3`, a section name), or with one
  tag: `[Thiếu]` (missing), `[Mơ hồ]` (more than one reading), `[Mâu thuẫn]` (contradicts another
  line, a source, an ADR or `CLAUDE.md`) or `[Giả định]` (rests on an assumption nothing records).
  At least 80% of the answers cite a location; a bare tag is itself a finding.
- Each item ends in one status: `Đạt`, `Không đạt`, `Không áp dụng` (with a one-line reason) or
  `Chưa kiểm`. `Chưa kiểm` never counts as `Đạt`.
- `[script]` items are settled by `scripts/check_plans.py`: copy its result and do not re-judge it.
  `[script, W]` means the script warns and judgement decides. `[script, partial]` means the script
  settles the countable part and judgement the rest. `[judgement]` has no mechanical part.
- Never tick an item on someone's behalf, and never record a decision as Đạt's that he did not make.

## Which items apply

| Document                | Items                                                                     |
| ----------------------- | ------------------------------------------------------------------------- |
| spec, before tickets    | 2-27                                                                      |
| spec with its tickets   | 2-33                                                                      |
| ticket with no spec     | 3, 4, 11-20 its change touches, 29-33                                     |
| `requirements.md`       | 1-9, 11-23 and 25, asked of what is wanted rather than how it is built    |
| ADR                     | 3, 4, 21-23 and those of 11-20 its decision touches, plus the reader test |
| glossary (`CONTEXT.md`) | 3, 21 and 23, plus the reader test                                        |

---

## 1. Content

1. Does `requirements.md` say what and why with no stack: no framework, table, route, library or
   class? `[judgement]`
2. Is every required section present, in the template's order, and is none filled with "N/A",
   "Không áp dụng" or a leftover template token? `[script]`
3. Does any sentence restate `CLAUDE.md`, an ADR or `CONTEXT.md` instead of linking to it?
   `[judgement]`
4. Does every sentence decide or evidence something, so that deleting it would change a decision?
   `[judgement]`

## 2. Completeness

5. Is each criterion one EARS-VN sentence with one named subject and exactly one modal
   (`writing-plan-specs/ears-vn.md`)? `[script, W]`
6. Does every `KHI` have its `NẾU ... THÌ` error paths, every `TRONG KHI` its complement, and every
   `ĐỐI VỚI` its other branch? `[judgement]`
7. Does every number carry a unit, a scope (tenant, workspace or run), a time zone, and the
   behaviour exactly at the limit? `[judgement]`
8. Are the main, alternate, error, recovery and non-functional scenarios each covered by a
   criterion, or excluded by a "Ngoài phạm vi" row that says why and who owns it?
   `[script, partial]`
9. Does every `[CAN LAM RO: Q<n>]` point to an open `Q<n>`, and does every open question name an
   owner and say `Chặn:` or `Không đổi:`? `[script]`
10. Does each change to existing behaviour carry a delta mark with the earlier behaviour's
    `path:line`, and does behaviour that must survive have a `G<n>` line naming its regression
    test? `[judgement]`

## 3. Platform: the never-default topics

This group is the one list of the topics a plan never settles by default: `writing-plan-specs`
(rule 1) and the "Kiểm soát" section of `spec-template.md` point here instead of naming them. Each
item points to the place that owns its questions; ask those questions of the document, at
requirement level. A topic settled by inference rather than by a citation or by Đạt is CRITICAL.

11. Is the tenant and workspace scope of every datum, cache key and object path stated, with a
    cross-tenant negative test? (`reviewing-feature-security`, section 1) `[judgement]`
12. Who may act, approve or change each thing, and where is that enforced; which state
    transitions exist, and which states are terminal: is each settled by a citation or by Đạt,
    never inferred? (section 2) `[judgement]`
13. Does every side effect state its level, its approval policy, its idempotency key, its audit
    event in the same transaction and, for a background lane, the actor `system:<lane>`? (sections
    3 and 5) `[judgement]`
14. Are the untrusted inputs that reach prompts, tools or memory named, and is model output
    validated into a schema and resolved against real data? (section 4) `[judgement]`
15. Is it said what removes everything the feature creates, and when? (section 6;
    `failure-modes.md` #6) `[judgement]`
16. Does every default, fallback and unreadable value fail closed? (`failure-modes.md` #7)
    `[judgement]`
17. Does every declared field, setting or status have a named reader? (`failure-modes.md` #1)
    `[judgement]`
18. Do versioned artifacts resolve through the tenant overlay, falling back to the platform and
    never sideways? (`CLAUDE.md`, "Per-tenant artifacts") `[judgement]`
19. Is plan quota and spend enforced where a run starts? (`CLAUDE.md`, "Agent and tool rules")
    `[judgement]`
20. Do new prompts, tools or retrieval paths come with eval cases for prompt injection,
    cross-tenant access and missing evidence? (`CLAUDE.md`, "Observability and evaluation")
    `[judgement]`
21. Are domain terms used as `CONTEXT.md` defines them, and is each new term flagged for
    `mattpocock-skills:domain-modeling`? `[judgement]`
22. Does every cited ADR exist with the status the citation gives, and is nothing built silently
    on a Questioned or Superseded ADR? (`docs/agents/domain.md`) `[script, partial]`
23. Does anything conflict with `CLAUDE.md`? `[judgement]`

## 4. Readiness

24. Can the first slice be built and shown working on its own? `[judgement]`
25. Is every vague word replaced by a number, an operation or a named control, or justified in the
    same sentence? `[script, W]`
26. Does every `NẾU ... THÌ` that guards a never-default topic have a "Kiểm soát" row naming its IDs
    and a negative test that would go red without the control? `[script, partial]`
27. Do the "Hiện trạng" anchors resolve, and does the heading carry the commit and date that were
    read? `[script]`

## 5. Tickets

The gate only, once tickets exist.

28. Is every criterion, `G` line and control in some ticket's `Yêu cầu:` line or in a "Ngoài phạm
    vi" row? `[script]`
29. Can every acceptance criterion fail? It names the observation that would make it false, and it
    is not already true at the base commit, not satisfiable only by another ticket, and not a
    restatement of the request. `[judgement]`
30. Does the ticket that implements each control carry its negative test, and does every ticket
    have tests and exactly one runnable `Xong:` line? `[script, partial]`
31. Does any ticket defer part of its work (the deferral words of `ticket-template.md`, "Việc cần
    làm") without a second ticket for the rest? Split, never shrink. `[judgement]`
32. Do dependencies point only backward, do tickets with no dependency path between them share none
    of the resources `ticket-template.md` lists, and does shared setup sit in the earliest ticket?
    Start the pair table from the script's collision candidates; "no collision" without its rows
    does not count. `[script, partial]`
33. Are data constraints (lengths, enums, uniqueness, nullability, collation) quoted verbatim from
    the spec? `[judgement]`

---

## Severity

Severity is by impact, never by how easy the fix is. When unsure, take the lower one.

- **CRITICAL**
    - a conflict with `CLAUDE.md`. It is never reinterpreted away: changing the rule is a separate
      `CLAUDE.md` change or a superseding ADR, made first;
    - a conflict with an Accepted ADR that no superseding ADR covers;
    - a guard on a never-default topic without a control and a negative test;
    - a never-default topic settled by inference;
    - in ticket mode, a first-slice criterion with no ticket;
    - a document at `ready-for-agent` without the verdict and approval it needs.
- **HIGH**
    - an ambiguous or untestable criterion;
    - requirements that conflict with each other;
    - an open question that would change scope;
    - building on a Questioned or Superseded ADR without saying so;
    - a dependency cycle, or a collision between tickets with no dependency path;
    - any other failed enforcing check of the script.
- **MEDIUM**: drift (a term, a name, a stale copy), a vague word, a missing complement or error
  path, any script warning.
- **LOW**: wording.

Twenty-five or more CRITICAL plus HIGH means the document goes back to writing; the gate stops and
says so rather than listing them.

## Verdict

- **ĐẠT**: no CRITICAL; no HIGH, except those whose risk Đạt accepted in "Quyết định"; no open
  question without `Không đổi:`; no `[CAN LAM RO]` marker; and every `[script]` item ran.
- **CẦN XEM**: no CRITICAL, but HIGH findings Đạt has not ruled on, or a check that did not run.
  Đạt decides each HIGH: fix it, or accept the risk. Only Đạt records an accepted risk; the agent
  may propose one.
- **CHƯA ĐẠT**: any CRITICAL, or 25 or more CRITICAL plus HIGH.

A CRITICAL cannot be accepted as a risk. It is fixed, or the rule it breaks is changed in its own
owner first.

## Trigger table for the boundary walk

Match case-insensitively and as whole words on the document's body, leaving out the header lines
and the who-field of "Quyết định" lines: `ghi` matches "ghi audit", never "nghiệm" or "nghiên".
Any match means that boundary is walked. Judgement may add a boundary the keywords missed; it never
removes one a keyword matched. Most specs match all six; the subagent cap in `subagent-briefs.md`
(C) splits them among subagents and never drops one.

| Keywords                                                          | Boundary in `reviewing-feature-security` |
| ----------------------------------------------------------------- | ---------------------------------------- |
| tenant, workspace, RLS, cache, object path, export, offboarding   | 1. Tenant isolation                      |
| scope, vai, quyền, duyệt, approve, admin, waiver, support         | 2. Authorization                         |
| tool, agent, gửi, send, ghi, write, webhook, external, spend      | 3. Autonomy and approval                 |
| prompt, model, retrieval, memory, embedding, document, connector  | 4. Untrusted content                     |
| audit, lịch sử, evidence, provenance, version, manifest           | 5. Provenance and audit                  |
| retention, xóa, delete, purge, partition, TTL, fallback, mặc định | 6. Resource lifecycle and defaults       |
