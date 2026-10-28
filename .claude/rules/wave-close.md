# What a ticket does, and what waits for the wave's close

**Scope: every session, on purpose.** No `paths:` frontmatter: it decides how
much checking a ticket carries, whatever part of the tree it touches.

Đạt, 2026-10-28: tickets must close faster, without sloppy work. The rule is to
keep, per ticket, every check that finds a bug in _this_ ticket's code, and to
move to the end of the wave the checks whose cost is fixed per run and whose
finding is still attributable afterwards (one commit per ticket on `main`).

**This rule wins over a ticket's own "Xong" line.** Many tickets end with
"Xong: `make test-unit test-contract test-integration` xanh"; read it as the
fast gates below plus the integration suites of the packages the ticket
touched. The whole `make test-integration`, the latency of operations whose
database access did not change, `/code-review` of the diff and
`checking-plan-consistency` are not run per ticket: they run once, at the
wave's close, and a ticket is not left open waiting for them.

## Per ticket — never deferred

1. **Readiness: one gate, one confirmation.** `checking-plan-readiness` runs
   once. Its CRITICAL and HIGH findings are fixed (on delegation, with the
   recommendation), then one confirmation pass reads only those fixes. MEDIUMs
   go to the ticket's Comments for whoever builds it. A second full gate runs
   only if the confirmation finds a new CRITICAL. (Ticket 03 of app-standards
   took eight rounds; most of what they found surfaced in code anyway.)
2. **Tests for every R and G of the ticket**, the G tests written first where
   the ticket says so.
3. **`reviewing-feature-security`** and the **mutation check scoped to the
   ticket's APS**: one batch script that breaks each control, runs only the
   tests that guard it, and restores it. This is where tests that cannot fail
   are found; it is never deferred.
4. **Fast gates**: ruff, format, `python -m mypy`, `make test-unit`,
   `make test-contract`, `make test-architecture`, and the integration suites
   of the packages the ticket touched (not the whole `make test-integration`).
5. **Latency** only when `latency.md` "When" says so.
6. Ticket `resolved`, Comments with what was done differently, Slice log,
   commit, push.

## At the wave's close — once, before the wave is called done

1. The whole `make test-integration` on the full data plane (Qdrant, the S3
   store and the docgen sandbox image up), every failure explained.
2. P50/P95/P99 of every operation and page the wave touched, against the
   wave's starting commit (`git archive`, measured with nothing else running).
3. `/code-review` (or the plugin's `code-review`) over the wave's diff,
   with the specs' paths, and `reviewing-deployment-security` if the wave
   added a route, an image, a compose service or an outbound URL.
4. `checking-plan-consistency` for the area, and `scripts/check_plans.py`.
5. A regression found here is bisected to its ticket's commit and fixed in a
   follow-up ticket, recorded in that ticket's Comments.

**Ask:** would deferring this check let a bug ship that this ticket's own
tests cannot see? If yes, it is per ticket.
