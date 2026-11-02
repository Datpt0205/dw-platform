# Latency before done — P50, P95, P99 of what a change touched

**Scope: every session, on purpose.** No `paths:` frontmatter, like
`failure-modes.md` and `code-quality.md`: a change anywhere can make a route or a
page slower, and the tests that prove it correct do not see it.

Đạt, 2026-10-28: a feature must not get unreasonably slow. A feature that works
and got slow is not finished.

## When: once, after every ticket of the queue

Đạt, 2026-11-02, replacing his 2026-10-28 split: no ticket measures its own
latency, not even one that changes how a request reaches the database. Every
operation and page the queue's tickets touched is measured in one pass after
the last of them is done (`.claude/rules/wave-close.md`), against the commit
the queue started from. A per-ticket commit makes a late regression
attributable by bisecting, so deferring the measurement loses no information,
only latency of finding out; the regression is fixed in a new commit and
recorded in the original ticket's Comments.

## The step

After the deferred mutation pass of `wave-close.md`, before the queue is
called done:

1. **List what the change touched**: every API operation whose handler, service,
   repository, query or migration changed, and every page or interaction whose
   code or data changed.
2. **Measure each**, warm, against the real app and a real PostgreSQL, never a
   fake: at least 200 requests per operation (P99 means nothing below that),
   with data shaped like the route's real use (the rows a list pages through, the
   key an idempotent write carries).
    - API: a script driving the real ASGI app over httpx, as
      `apps/api/tests/integration` does, or uvicorn plus HTTP.
    - Web: Playwright (the MCP or the repo's specs), time to the page's main
      content and to each changed interaction.
3. **Compare with the queue's starting commit**, measured the same way on a
   checkout of it (`git archive <commit> | tar -x -C <scratch dir>`, never a worktree or a
   `git stash` in a tree something else is running in).
4. **Write the numbers down**: P50, P95, P99 before and after, per operation, in
   the Comments of the ticket that touched it and in the closing report.

## Budgets

Provisional, until Đạt sets real ones:

| What                      | P95      | P99   |
| ------------------------- | -------- | ----- |
| An API operation, locally | ≤ 300 ms | ≤ 1 s |
| A page interaction        | ≤ 1 s    | ≤ 2 s |

And a P95 more than 20% worse than the starting commit's needs a reason written
next to the numbers, or a fix, before the queue is called done. A missed budget is
reported plainly with its numbers; it is not rounded into "fine".

**Ask:** which operation did this change make do more work per request (one more
query, one more round trip, one more lock), and what did that cost at P99?
