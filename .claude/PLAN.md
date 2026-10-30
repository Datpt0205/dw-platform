# Plan — index

`.claude/hooks/session-start.sh` reads this file whole at session start and
warns past 80 lines, because an index that grows stops being read. It holds
four things: where each area stands, what is next, what Đạt still owes, and
how a feature is checked. Detail lives in the area file. History lives in
git: every slice's commit message, and the pre-split narrative at
`git show 84e3f6a:.claude/PLAN.md`.

## Areas

| Area                               | File                                | State                                                             |
| ---------------------------------- | ----------------------------------- | ----------------------------------------------------------------- |
| Ops hardening                      | `.claude/plans/ops-hardening.md`    | Done; numbers owed                                                |
| Agent runtime and memory (Mốc 0–6) | `.claude/plans/platform-runtime.md` | Named gaps; docgen sessions isolated (ADR 0025)                   |
| Web UI shell (Ant Design v6)       | `.claude/plans/web-ui.md`           | antd everywhere, CSP done                                         |
| Chat channels (Zalo)               | `.claude/plans/channels.md`         | Upstreamed; live run owed                                         |
| Studio → Digital Workers (D15)     | `.claude/plans/studio.md`           | skeleton/01, telemetry/01, app-standards/01-04, foundations/01-02 |

After working in an area, update its file. Update this index only when an
area's state, the next step or a decision owed changes. A new area gets its
own file and a row here.

## Now (2026-10-29)

- **Platform seed, no bounded context.** Products live in their own repos
  (first: `https://github.com/Datpt0205/platform-bidding`); the removed Supply
  Chain context left its platform pieces, listed in `platform-runtime.md`.
- **Digital Workers first (D15, 2026-10-29).** Studio turns to the CASANOS
  Digital Worker: agentic within bounds, owning a queue, never a chat
  assistant; the Marketing pilot becomes a lead-care DW at A2, and a thin DW
  slice that really runs (with screens) comes before the rest of Studio.
  D17/D18 (Đạt, 2026-10-29): path C, a DW core plus a minimal `dw.workflow/v1`
  engine running a shipped lead-care pack; YC118-YC125, ADR-0128 (Proposed),
  specs `digital-worker`, `wf-lite`, `leadcare` gated and ready for agent.
  **Next:** the unattended queue in `studio.md` (foundations-hardening 07 and
  03, org-and-principals 01, runtime-hardening 01 and
  digital-worker 01-02, wf-lite 01 done; wf-lite 02 in progress, phases C-D left).

## Decisions Đạt owes

- **Runtime:**
    - a plan quota on direct model calls (`runs_per_day`/`spend_usd_per_day`
      are enforced only in the runner);
    - the model profile and key for uat/production (local runs on `luna`,
      gpt-5.6-luna, `make check-model`; the key is only in local `.env`);
    - the rerank key for uat/production (local reranks through FPT Cloud,
      `make check-rerank`; the key is only in local `.env`);
    - whether CI runs the web vitest suite and the Playwright specs (`web-ui/antd-shell` ticket 10).
    - how many independent documents a memory needs to be written without
      review (`MemoryWritePolicy.auto_write_sources`, 2 since 2026-10-06).
- **Ops:**
    - spend guard dollar thresholds per plan;
    - a retention term for offboarding export bundles;
    - how many superseded document versions to keep.
- **Platform:**
    - backfill ADRs with a status (`docs/agents/domain.md`): 46 citations of
      ADR-001..003 point at documents this repo never had.
    - Studio (`studio.md`): each spec's `Duyệt`.
    - Studio: ask dw-proterial whether their IdP sends `email_verified` (DO-17.1, foundations-hardening/02 step 19).

## How a feature is checked here

1. `scripts/verify_invariants.py`: mechanical checks, run in CI and in the
   commit hook.
2. `.claude/hooks/pre-commit-gate.sh`: runs layer 1, then asks only the
   questions this diff earns.
3. `.claude/skills/reviewing-feature-security/`:
    - six trust boundaries, with a negative test at each;
    - a mutation check (`scripts/mutate.py`), then P50/P95/P99 (`latency.md`; a wave's close: `wave-close.md`);
    - run before calling a feature done, without being asked.
4. `.claude/skills/reviewing-deployment-security/`: deployed-profile exposure,
   secrets, CORS, outbound URLs, and a scan of every new image.
5. `mattpocock-skills` (`/ask-matt` routes): the flow from grilling to
   `/implement` and `/code-review`; `CLAUDE.md` "Agent skills" places
   layers 1–4 inside it. Installed per checkout, not by the repo: check
   with `claude plugin list`.

`.claude/rules/failure-modes.md` holds the counts behind layers 1–3. Layer 2
guarantees the questions get raised, not that they get answered truthfully.
No layer replaces running the thing.
