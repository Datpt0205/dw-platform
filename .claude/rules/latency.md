# Latency before done — P50, P95, P99 of what a change touched

**Scope: every session, on purpose.** No `paths:` frontmatter, like
`failure-modes.md` and `code-quality.md`: a change anywhere can make a route or a
page slower, and the tests that prove it correct do not see it.

Đạt, 2026-10-28: a feature must not get unreasonably slow. A feature that works
and got slow is not finished.

## When: per ticket, or once per wave

Đạt, 2026-10-28, for speed without losing the check: a ticket measures its own
operations before it closes **only when it changes how a request reaches the
database** — a migration or index, a query or repository method, a list's
ordering or filter, a lock, or one more statement on a request path. Every
other ticket (a new route over existing queries, configuration, UI, docs)
closes without numbers, and its operations are measured with the rest at the
end of the wave (`.claude/rules/wave-close.md`), against the wave's starting
commit. A per-ticket commit makes a wave-end regression attributable by
bisecting, so deferring the measurement loses no information, only latency of
finding out.

## The step

After the mutation check of `reviewing-feature-security`, before a ticket is
closed (or at the wave's close, per the section above):

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
3. **Compare with the parent commit**, measured the same way on a checkout of it
   (`git archive <parent> | tar -x -C <scratch dir>`, never a worktree or a
   `git stash` in a tree something else is running in).
4. **Write the numbers down**: P50, P95, P99 before and after, per operation, in
   the ticket's Comments and in the closing report.

## Budgets

Provisional, until Đạt sets real ones:

| What                      | P95      | P99   |
| ------------------------- | -------- | ----- |
| An API operation, locally | ≤ 300 ms | ≤ 1 s |
| A page interaction        | ≤ 1 s    | ≤ 2 s |

And a P95 more than 20% worse than the parent commit's needs a reason written
next to the numbers, or a fix, before the ticket closes. A missed budget is
reported plainly with its numbers; it is not rounded into "fine".

**Ask:** which operation did this change make do more work per request (one more
query, one more round trip, one more lock), and what did that cost at P99?
