# Subagent briefs

The three fresh-context checks of `checking-plan-readiness`. The author's context reads past its
own gaps; a reader who has only the document cannot, and that is the whole value of these checks.
So each subagent:

- is read-only, and reads only the files its brief lists;
- is told nothing about what the author meant: a reader who knows the intent fills the gaps the
  check exists to find;
- returns compact rows, never a report. The main context merges the rows, and every extra line is
  paid for twice.

Dispatch every brief a run needs in one message. Copy the brief, fill each `<...>`, add nothing.
Rows are written in Vietnamese, the language of the documents; IDs, file paths, verdict words and
severity words stay exactly as written.

## A. Builder check

For a spec, and for its tickets once they are cut.

```text
You are the engineer who will implement <spec path> in this repository. You cannot ask its author
or anyone else anything: you have only the files below. Read them and plan the work in your head.

Read only: <spec path>; <its issues/*.md, or "no tickets yet">; CLAUDE.md; the ADRs it cites:
<paths, or "none">; <the context's CONTEXT.md path, or "no glossary yet">.

Return, in Vietnamese, nothing but these rows:

1. Up to 10 questions you would have to guess the answer to, where a wrong guess changes what gets
   built, most important first:
   B<n> | <location: section or ID> | <the question> | <what gets built wrong if you guess wrong>
   Skip what the document leaves to the implementer on purpose, what any competent engineer could
   settle without changing the result, and wording. If nothing important is left, return the
   single row: B0 | - | không còn câu hỏi quan trọng | -

2. Two or three ordinary situations the criteria should accept and one or two they should refuse,
   each with the ID that decides it:
   S<n> | nhận or từ chối | <a concrete situation> | <the deciding ID, or KHÔNG CÓ>
   A situation no ID decides, or one decided against what a reasonable user would expect, is the
   point of this list: mark it KHÔNG CÓ, or add four words on why it surprises.

Do not edit anything, do not propose a redesign, do not summarise the document.
```

## B. Reader test

For `requirements.md`, an ADR, or the glossary once its terms are stable.

Before dispatching, the main context writes 5-10 questions the document's real readers will bring,
and its own one-line answer to each from the author's intent (the conversation, the "Quyết định"
log). The answers stay out of the brief. Questions worth asking:

- an ADR: what may I no longer do; what would make this decision wrong; which option was rejected,
  and why;
- the glossary: one question per pair of terms a reader could confuse;
- `requirements.md`: is X in scope; who is the user of Y; what must never happen; how will we know
  it worked.

```text
You are reading <document path> for the first time, because you have to act on it. Read only that
file<, and CLAUDE.md for an ADR>. Answer each question below from the document alone, never from
what you know elsewhere.

<numbered questions>

Return, in Vietnamese, nothing but these rows:

T<n> | <your answer, one sentence> | <where the document says it, or KHÔNG THẤY> | <what you had to assume, or không>

then up to five rows for anything ambiguous, contradictory or resting on an unstated assumption:

M<n> | <location> | <what is ambiguous or contradictory>
```

After it returns, compare each answer with the intended one. A wrong answer, a `KHÔNG THẤY` or an
assumption is a finding against the section that should have answered it.

## C. Boundary walk

For a spec whose body matches the trigger table in `quality-checklist.md`, which is nearly every
studio spec. Walk every matched boundary, plus any that judgement adds. A tier C spec (one with its
own ADR: a new seam, trust boundary, cross-context dependency or irreversible data choice) gets up
to four subagents, and the matched boundaries are split among them, so six boundaries go to four
subagents as two pairs and two singles; none is dropped to fit the cap. Any other spec gets one
subagent for all of them.

```text
You are reviewing <spec path> for what a second tenant, a careless caller or an attacker could do
with what it allows or leaves unsaid. These are requirements, not code: ask whether the document
decides each thing, not whether code would do it.

Read only: <spec path>; CLAUDE.md; sections <n, n> of
.claude/skills/reviewing-feature-security/SKILL.md; .claude/rules/failure-modes.md; the
"Severity" section of .claude/skills/checking-plan-readiness/quality-checklist.md; the ADRs it
cites: <paths, or "none">; <the context's CONTEXT.md path, or "no glossary yet">.

1. For each boundary section named above, put its questions to the document: does a criterion or a
   "Kiểm soát" row decide the matter, and does that row carry a negative test?
2. Silence is not permission. List up to five classes of input or failure the document implies but
   no criterion or control covers, most likely first. Prompt yourself with failure-modes.md: a
   default that fails open, one fact with two owners, a check reachable around, something created
   and never destroyed, a field nobody reads.
3. Run at least one adversarial situation: a caller from another tenant, a replayed
   Idempotency-Key, two identical requests at the same moment, or a cache entry written before this
   change. Name the ID that decides it, or say none does.

Return, in Vietnamese, nothing but these rows. At most five F rows, most severe first:

F<n> | <boundary 1-6> | <location> | <what the document leaves unsaid or allows wrongly> | <CRITICAL, HIGH, MEDIUM or LOW> | <one of: sửa spec; câu hỏi mở; rủi ro để Đạt quyết; ngoài phạm vi, chủ là <owner>>
N<n> | <input or failure class> | <what a reasonable user would expect to happen>
S<n> | <the adversarial situation> | <the deciding ID, or KHÔNG CÓ>

Severity follows the section you were given; a conflict with CLAUDE.md is CRITICAL; when unsure,
take the lower one. Cite boundary questions by section number instead of repeating them. Do not
edit anything.
```

## Merging the rows

- Drop duplicates across subagents and keep the more severe copy.
- Each row becomes one finding, sorted into the three piles of `checking-plan-readiness`, step 6.
  A row that names no location the main context can find is dropped, not guessed at.
- An `F` row's resolution is a proposal. "Rủi ro để Đạt quyết" becomes a question to Đạt; only he
  records an accepted risk.
- A subagent that failed or returned nothing usable leaves its check at `Chưa kiểm`, and the
  verdict cannot be ĐẠT while it stands. Record it; never drop it silently, and never re-run it in
  a loop.
