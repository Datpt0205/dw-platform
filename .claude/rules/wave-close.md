# What a ticket does, and what waits for the queue's close

**Scope: every session, on purpose.** No `paths:` frontmatter: it decides how
much checking a ticket carries, whatever part of the tree it touches.

Đạt, 2026-11-02, replacing his 2026-10-28 split: finish the API and UI tickets
first, audit later. A ticket keeps the checks that read its own code and run
in seconds; every check whose cost is fixed per run (the mutation runs, the
whole integration suite, latency, screenshots) runs once, after the last ticket
of the queue is done. One commit per ticket on `main` keeps a late finding
attributable.

**This rule wins over a ticket's own "Xong" line.** Many tickets end with
"Xong: `make test-unit test-contract test-integration` xanh"; read it as the
per-ticket gates below. The rest runs at the queue's close, and a ticket is not
left open waiting for it.

## Per ticket — never deferred

1. **Readiness, only for a ticket not yet gated.** A ticket of a spec already
   ĐẠT is not gated again. A `needs-triage` ticket gets `checking-plan-readiness`
   once, in one subagent that does the builder check and the boundary walk
   together; its CRITICAL and HIGH findings are fixed (on delegation, with the
   recommendation), MEDIUMs go to the ticket's Comments.
2. **Tests for every R and G of the ticket**, the G tests written first where
   the ticket says so, with a negative test for every row of its "Kiểm soát"
   (another tenant, a caller without the right).
3. **`reviewing-feature-security`, read**: walk the ticket's "Kiểm soát" rows
   against the code. Write `mutations/<NN>.yaml`, one mutation per control, but
   do not run it yet.
4. **Fast gates**: ruff, format, `python -m mypy`, the unit tests of the
   packages the ticket touched, the ticket's own integration tests, and, when
   it adds a migration, `test_rls_coverage.py`, `test_privileges.py` and
   `test_offboarding_coverage.py`. A changed route regenerates the OpenAPI
   snapshot and the TS types. The pre-commit hook runs as always.
5. Ticket `resolved`, short Comments with what was done differently, one Slice
   log line, commit, push, next ticket.

## At the queue's close — once, before the queue is called done

1. `scripts/mutate.py` for every `mutations/<NN>.yaml` the queue wrote.
2. The whole `make test-integration` on the full data plane (Qdrant, the S3
   store and the docgen sandbox image up), pytest without `-q` so the totals
   print, every failure explained.
3. P50/P95/P99 of every operation and page the queue touched, against the
   queue's starting commit (`latency.md`).
4. Playwright screenshots, light and dark, desktop and below 992px, of every
   new screen, checked against design v3.
5. `/code-review` (or the plugin's `code-review`) over the queue's diff, with
   the specs' paths, and `reviewing-deployment-security` if it added a route,
   an image, a compose service or an outbound URL; `checking-plan-consistency`
   for the area, and `scripts/check_plans.py`.
6. A defect found here is bisected to its ticket's commit, fixed in a new
   commit, and recorded in that ticket's Comments.

**Ask:** would deferring this check let a bug ship that nobody will look for at
the queue's close? If yes, it is per ticket.
