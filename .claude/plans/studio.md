# Studio: tenant-built objects, workflows, agents and tools

Studio is the no-code capability through which a customer (tenant) builds the
data model, the workflows, the agents and the tool connections for its own
departments, starting with Marketing. It is platform code in this repository
(ADR-0100), not a business context and not a product repository. Nothing here
is built yet. Đạt accepted the ADR block on 2026-10-23 (0126 and 0127 on
2026-10-24), all but ADR-0119, which waits for the code-sandbox spike.

## State (2026-10-26): pass h applied V4.30-V4.41 and Q-h1 to Q-h11

- **Round 4 in progress (2026-10-24):** Đạt accepted the 13 recommendations
  of consistency round 3, splitting a spec past the size of
  `writing-plan-specs` when it reaches `checking-plan-readiness`
  (foundations-hardening first: R6-R10 and tickets 04-06 become
  `runtime-hardening`, numbers kept), and a fourth remediation round past the
  three-round limit of `checking-plan-consistency`. Documents cite the
  decisions as `V4.1`-`V4.13` (numbered as below) and the planner's choices
  for rows with several fixes as `V4.P1`-`V4.P14`, never as bare `D<n>`,
  which names the requester's directions D1-D14 below. The decisions:
    1. `endpoint` has no quality gate and goes live on a second person's
       approval, `studio.publish.endpoint` stamped `studio.publish.approve`
       like every kind (ADR-0120 d2); `studio.datahub.manage` is the key to
       submit. The report had said "stamped `studio.datahub.manage`"; the stamp
       follows ADR-0120 d2 so as not to open a second answer to who publishes.
    2. Every submit records `compared_live_hash`; approving a candidate whose
       base changed returns it to draft with `base_changed` (ADR-0120 d1-d2).
    3. MCP tools keep `studio.mcp.tool_approval`; every other tool kind opens
       `studio.publish.tool` (ADR-0116 d9).
    4. A draft can be simulated, pinned under a provisional content hash.
    5. `connections.enable` stamped `connections.manage`,
       `egress.allowed_host` stamped `integrations.admin` (ADR-0115).
    6. A stale save is 412 `precondition_failed`, reason `stale_version`.
    7. domain-packs Q2: installing a pack over existing `mkt_` objects attaches
       provenance; differences arrive as a proposal in a draft.
    8. The tighten-only branch of an object version passes a tenant freeze.
    9. Trigger runs of an inactive service account stay queued and alert the
       owner; `binding_needs_review` joins ADR-0113 d3's table.
    10. Approval delegation (W2): stamped key, not the run's creator,
        time-boxed.
    11. `recipient_cap` joins ADR-0124 d1's block reasons.
    12. `platform.limit_policies` keeps its `scope_*` columns (ADR-0121 d4).
    13. Message content at most 16 KiB; citations and feedback in W2.

    The planner's choices, each logged `(agent, tạm)` with `Nếu sai thì:`:
    V4.P1 one versioned retention file, its editing tickets chained from
    usage-and-limits/02; V4.P2 key-registering tickets wait for tenant-rbac/02;
    V4.P3 studio-skeleton/03 waits for tenant-rbac/02; V4.P4
    telemetry-and-audit/02 waits for workflow-engine/05; V4.P5 offboarding
    deletes a tenant's service users through a narrow SECURITY DEFINER
    function; V4.P6 user-scoped limits, concurrency caps, purposes and
    thresholds move to W2 (YC79); V4.P7 custom-objects R3.1-R3.6 move to its
    ticket 03; V4.P8 no conversation delete route in W1; V4.P9 a strict-prefix
    self-decision is `second_person_required` for every type; V4.P10
    `studio.*` keys have exactly three segments, plural areas but `publish`,
    `lifecycle`, `datahub`, `code`, `mcp`; V4.P11 `logic.loop` at its cap
    takes `max_reached`, else `loop_limit_reached` (W2); V4.P12
    workflow-engine/01 waits for agent-lifecycle/03; V4.P13 both CEL bindings
    behind `ExpressionEngine` as ADR-0114 d2 says, deployed profiles pinned to
    `cel-expr-python`; V4.P14 tenant-config/04 waits for
    runtime-hardening/03.

    Đạt's decisions on the verifiers' ten questions (2026-10-24, as
    recommended): V4.14 `deadline_at` in W1 as ADR-0113 d3 first wrote it,
    the cancel route still W2; V4.15 a held run of an inactive service
    account notifies the tenant-depth holders of `platform.members.write`;
    V4.16 `binding_needs_review` holds trigger runs queued instead of
    rejecting them; V4.17 one unpublished version (draft or candidate) per
    artifact, `candidate_pending` otherwise; V4.18 an approved publish that
    cannot apply returns to draft with its reason; V4.19
    `studio.agents.manage_settings` confirmed; V4.20 an old signing secret
    is refused 24 hours after rotation, a replaced connection secret is
    revoked at once, a lane deletes both once no unfinished run pins them;
    V4.21 counsel's retention terms live in `platform.retention_terms`,
    loaded by the provisioner from the pinned policy, read by every
    no-argument purge; V4.22 a simulated draft reads under a provisional
    boundary derived from its closure, intersected with the tester's
    access, never used live; V4.23 while a publish approval is pending, its
    stamp holder reads the candidate and its diff through agent-lifecycle.

    Đạt's canvas and control-flow decisions (2026-10-24, as recommended
    after the canvas research): V4.24 a workflow is a step tree drawn as a
    structured canvas, steps placed in slots and never wired by hand, which
    reverses ADR-0112 d1's graph document; V4.25 `@xyflow/react` alone, with
    dagre dropped for a pure deterministic layout module (AntV X6, Rete.js and
    bpmn-js rejected on sourced reasons); V4.26 W1 grows by about two to
    three weeks to hold parallel lanes with an all-join compiled as
    subgraphs, a bounded loop with waits and a break, resume from a failed
    step as an incident, and an approval step that needs every one of
    several approvers, while waits inside parallel lanes stay out; V4.27 an
    agent drafts the canvas vocabulary in the spike for Đạt's review; V4.28
    no BPMN in v1, a server-side importer of a subset in W3 if a customer
    asks; V4.29 (the UI direction) antd stays the one component system, the
    Studio screens follow the references Đạt sent (the chang.fpt.net
    teardown; Dify, Windmill, Activepieces and Camunda for the canvas) for
    layout and interaction and look better through the antd theme, never
    copying another product's identity, look or code; a library that
    supports antd without a competing component set may join through its
    own ADR and allowlist entry, app-wide or for one path (a CLAUDE.md "Web
    UI" amendment, with V4.25's); motion beyond antd's waits for a later
    decision, the motion research kept as its input.

    The seventh pass applied V4.24-V4.29 on 2026-10-25. Documents cite
    V4.26's tier B (bậc B), the W1 tail no pilot ticket waits for, as
    B1-B3: B1 `logic.parallel@1`, each lane a subgraph joined once by a
    waiting edge, with no wait and no run end inside a lane; B2
    `logic.loop@1`, a do-while capped by `max_iterations` that may wait in
    its body and leaves by `logic.break`, under a run-level step counter; B3
    a failed step whose `on_error` is `incident` parks its run on an
    `incident` wait that a person resolves ("Chạy tiếp từ Bước lỗi" or
    "Kết thúc"); with them an approval step whose `approval_rule` is `all`.
    The planner's calls of that pass, each logged `(agent, tạm)` with
    `Nếu sai thì:`, are cited as G-1-G-5: G-1 every simulated run whose root
    is not live (a draft, or a sealed candidate in a gate run or a trial)
    reads under V4.22's provisional boundary; G-2 agent-builder's
    conversation purge reads its term from `platform.retention_terms`
    (V4.21); G-3 studio-skeleton's delete-order line follows ADR-0109's
    Consequences; G-4 the notice of a `principal_inactive` hold goes to the
    tenant-depth holders of `platform.members.write` without calling them
    the people who can reactivate the account, W1 having no such route; G-5
    editing a published workflow opens a new draft, or says to withdraw the
    pending candidate first (V4.17). Five tickets were added (102 in W1)
    and YC108-YC110 written. Its own follow-ups: the three positional
    traits of `NodeTypeSpec` (`opens_wait`, `ends_run`, `exits_loop`) are
    required fields from workflow-nodes/02, since workflow-engine/06 reads
    them before workflow-nodes/07 exists; a decision short of the last
    approval under `all` resolves no wait (ADR-0113 d4); usage-and-limits/04
    hands `max_steps` to the step counter, not to `recursion_limit`; the
    outcome that workflow-engine/07 adds to `StepWaitLookupPort` reaches its
    one real adapter in the same ticket, which now waits for
    workflow-nodes/06; marketing-pilot/03 waits for workflow-builder-ui/04,
    the tier-A grammar that draws its approval and switch lanes; the run
    view selects an iteration and no longer a lane; one simulated decision
    serves every iteration of an approval in a loop body, a list per
    iteration being W2.

    Nine editors, each followed by a verifier, applied them with every round-3
    row on 2026-10-24 (checker 24/24 in every folder). Their verifiers found
    where a decision had not reached a spec it never named, a few design
    errors the fixes exposed (the envelope AAD carried the KEK version, which
    the rewrap lane changes), and six state-transition questions for Đạt
    (Decisions owed). The second pass (committed) fixed all but those six:
    the AAD binds the secret's own version, conversations delete through one
    narrow function, both CEL bindings ship as ADR-0114 says, a simulated
    draft passes the submit validator first, and the V4 labels replaced the
    colliding ones. Its verifiers raised a seventh question (old secret
    versions) and mechanical rows the third pass applied (committed: publish
    hooks, one `data-sources` route, `ON DELETE` on every FK, composite FKs
    between tenant tables). Its verifiers found an index missing on some
    FKs, cross-tenant negative tests missing for the new composite keys, and
    two errors of the planner's own: the agent read key moved against Đạt's
    line, and the purge's term in code against ADR-0122 d7 (question 8). The
    fourth pass (committed) fixed the first three; its verifiers, told to
    report only CRITICAL and HIGH, found CLAUDE.md musts still unmet (DELETE
    privileges that the offboarding purge needs, cross-tenant negative tests
    on agent-builder's routes, two tenant-wide tables without a reason) and
    questions 9 and 10. A short fifth pass applied those musts only, the
    sixth V4.14-V4.23 and the seventh V4.24-V4.29 (above). The split of
    foundations-hardening followed on 2026-10-25: R6-R10, G7, FH15-FH29,
    FH32 and tickets 04-06 became runtime-hardening, the R and G numbers
    kept and the controls kept as RH15-RH29 and RH32, its tickets
    numbered 01-03 because the checker counts every ticket folder from 01;
    G5 stays in both, since a ticket of each can break the resume of an
    approved run.

    Đạt's decisions on the answer to ChatGPT's architecture review
    (2026-10-25, "theo khuyến nghị hết cho tôi"), applied by pass h: V4.30
    YC41's promise becomes levels of guarantee, internal effects exactly
    once, an external one exactly once when its Action declares a provider
    key or a lookup, otherwise never resent on an unknown outcome but parked
    on an `outcome_review` wait that a holder of `runs.reconcile` settles
    (another person than the requester for a critical effect), with a
    `delivery` block in `dw.connector/v1`, a `dispatched` row before every
    call and typed egress results; V4.31 the false edges go, five bundled
    tickets split, W1 exits twice, W1a (the pilot on profile `test`,
    `marketing-pilot/05`) and W1b (uat, the assistant, `marketing-pilot/06`),
    behind three gates, E1 before the first effect, E2 before a deployed
    environment, E3 before real personal data; V4.32 typed slots stay, one
    harness and one seed measure the W1 and W2 DDL; V4.33
    `flow.subworkflow`, up to three levels, joins tier B; V4.34 LangGraph
    stays behind the two-week S-RT spike (discovery/14), `durability="sync"`
    pinned and the execution semantics proved by golden traces; V4.35 the run
    manifest pins the connection and binding set, not the secret version, and
    revocation for compromise stops unfinished runs; V4.36 `run_steps` gains
    `attempt`, `port` and `child_run_id`, a reason-code catalogue and no Fork
    from a step; V4.37 deterministic scenario cases at the workflow gate and a
    review screen with the read-only canvas, a diff layer, gate results and
    cost; V4.38 a tenant is created with two owners and stays `setup` until
    the second is active, a partner may be the second person, an operator
    never; V4.39 a purchase-request probe runs in CI from W1, and a
    `transactional` rule waits for counsel before W2; V4.40 field lineage at
    submit, recipients checked at every destination and no write-down (W2,
    before its destinations); V4.41 a holder of `studio.workflows.test` reads
    the steps of the simulated runs they requested. The planner's calls of
    pass h, each logged `(agent, tạm)` with `Nếu sai thì:`, are cited as
    H-1-H-18: H-1 a retention fragment per store, the format, loader and
    terms table in telemetry-and-audit/01; H-2 the offboarding steps ordered
    from the RESTRICT edges; H-3 the executor's guard registry in
    tools-and-skills/01; H-4 prices leave the model profiles in
    usage-and-limits/02 first; H-5 W1 implements the internal, unkeyed and
    concurrent levels only, the keyed level and `studio_reconcile` with the
    first keyed connector (W2), no compensation block; H-6 an unresolved
    effect at the deadline audits `run.effect_unresolved`; H-7 a fake
    `RecordsPort` with a contract suite; H-8 `runs.reconcile` registered by
    workflow-engine/08; H-9 S-RT is discovery/14; H-10 a call uses the latest
    unrevoked secret version and records it, a replaced version is purged
    after 24 hours; H-11 no `branch_key`; H-12 telemetry-and-audit owns the
    reason-code catalogue; H-13 "Chạy lại mô phỏng" replaces Fork (W2); H-14
    a run records its reached `outcomes[]`; H-15 the below-two alert goes to
    tenant-depth holders of `platform.members.write`; H-16 a `domain-probe`
    folder; H-17 `/runs` unchanged for builders; H-18 the node wrapper applies
    pinned simulated results. After its first wave (2026-10-25) and second
    (2026-10-26), H-19-H-36: H-19 `studio.workflows.test` registered by
    workflow-engine/01; H-20 `ix_worker_runs_page` in workflow-engine/02;
    H-21 the label catalogues as fragments; H-22 a kill or freeze audits an
    unresolved effect under the person who set it; H-23 scenario cases are
    rows; H-24 E2's TLS is a certificate and HSTS on the uat host; H-25 a
    tenant model key's version waits for W2; H-26 a pinned result never
    stands in for an approval; H-27 usage-and-limits/02 waits for
    telemetry-and-audit/01; H-28 `compromised_at`; H-29 no `transactional`
    consent purpose; H-30 `RecordsPort` and `RecordAssignPort` are declared
    in workflow-engine/03; H-31 `days: indefinite` for a store kept without a
    term; H-32 a platform freeze audits under the operator who set it
    (`CLAUDE.md`, Agent and tool rules); H-33 a fragment `enforced: false`
    names who owes its purger, and `make retention-unenforced` is E3's
    evidence; H-34 an HTTP `create_key` carries `http:` and the caller;
    H-35 the purger registry lives in telemetry-and-audit/01; H-36 a
    fragment whose term Đạt answered is enforced. Result: 117 YC, 27 specs
    (`domain-probe` new), 113 W1 tickets with no cycle, the longest chain 18
    and `marketing-pilot/03` at depth 15 (21 before). Then a fourth
    consistency check, and the readiness gate for app-standards,
    foundations-hardening and runtime-hardening.

- **Round 3 applied on 2026-10-24:** Đạt took every recommendation still open
  (`studio/discovery` coverage review N1-N10, the two CRITICAL rows of round 2,
  four numbers, five D11 cases, two owners). New: ADR-0126 (a long process is
  an object's lifecycle in stages, W2) and ADR-0127 (reports through the
  platform aggregate API; a semantic layer such as Cube reads only a
  per-tenant analytics store; no ETL in v1); YC101-YC107; discovery ticket 30
  (aggregate queries under RLS at D12 scale); two tickets added (97 in W1: 95
  needs-triage, 2 ready-for-human). Round-2 findings with a clear fix
  applied. Checker 24/24, harness 303/303.

- **Accepted on 2026-10-23:** Đạt took every recommendation of the decision
  brief (165 items, each checked by a skeptic agent) except the repositories,
  which stay public. Applied the same night: 25 ADRs Accepted (0107, 0114 and
  0115 on a measurement condition; 0119 held Proposed); `CLAUDE.md` amended in
  about fifteen places (tenant-wide tables, two pins, the React Flow canvas,
  the record policy template, `LimitsPort`, the ADR-0011 lane exception, the
  partition revoke, the residency gate, condition 5 for a second language);
  requirements, glossary, the 25 specs and their tickets updated, four tickets
  added (95 in W1: 91 needs-triage, 2 needs-info, 2 ready-for-human); 595 ADR
  citations synced to their files and 121 `CLAUDE.md:<line>` citations moved
  to the amended lines. Checker 24/24, harness 303/303.
- **Declared ahead of code:** `CLAUDE.md` now states rules no code enforces yet
  (`tenant_wide_scope()`, the antd allowlist, `LimitsPort`, the partition
  revoke, the tenant-wide list in `test_rls_coverage.py`, the residency gate).
  Each lands with its W1 ticket; until then they are declared, not enforced
  (failure-modes #1).
- **Checked:** round 3 (2026-10-24), the last of the three remediation rounds
  `checking-plan-consistency` allows a wave, found 73 rows (8 CRITICAL, 25
  HIGH, 38 MEDIUM, 2 LOW), down from 139 and 99. Seven CRITICAL rows have
  their fix written in an accepted ADR or in `CLAUDE.md`; one CRITICAL and
  twelve other rows need Đạt (below). Four rows go back to the roadmap: its
  Phụ thuộc column, YC101 missing on two rows and YC102 on one, one row's
  wording, and spec size: 17 of 25 specs pass the 250 lines of
  `writing-plan-specs`, ten of them even without their measured state and
  decision log, and foundations-hardening has eleven requirement groups.

- **Direction from the requester** (2026-10-22 and 2026-10-23), D1-D14,
  recorded in the ADRs that rest on them: workspace is the data-owning unit
  (D1); builders are business admins working no-code (D2); record access needs
  owner and default access, hierarchy, sharing and field security (D3); the
  Marketing pilot is the first slice (D4); si-platform is reference plus
  selective port (D5); the per-call usage ledger returns (D6); the code node
  ships in v1, one container per run (D7); tenants connect their own models
  through a separate stateless LiteLLM lane (D8, D13); two people always
  (D11); 10 million records per object (D12); a resized host plus a separate
  VM for tenant code (D14).
- **Written:** `studio/requirements.md` (117 YC, 14 KQ); 28 ADRs in
  `docs/adr/0100`-`0127`; 27 feature specs with 113 first-wave tickets;
  `studio/discovery/` (brainstorm, research index, the chang.fpt.net teardown
  and config analysis, the wayfinder map with 30 tickets); the platform
  glossary `docs/platform/CONTEXT.md`.
- **Tooling installed with it:** the planning skills `writing-plan-specs`,
  `checking-plan-readiness`, `checking-plan-consistency`, the checker
  `scripts/check_plans.py` with its harness (`make test-plans`, in `make ci`),
  two CI steps (the checker advisory, the harness enforcing), and the overrides
  in `docs/agents/`.
- **Outside the repository:** an SRS v0.1 in Word compiled from the blueprint
  (`C:\Users\phung\Documents\Studio-SRS-v0.1.docx`, 56 pages); it is a reading
  copy and is rebuilt as v1.0 from `requirements.md` and the specs.
- **Remote:** `origin` is `https://github.com/Datpt0205/dw-platform` since
  2026-10-23; the previous remote is kept as `codebase` for fetching only, its
  push URL disabled. Both repositories are public by Đạt's choice (2026-10-23).

## Decisions owed

- **Đạt:** nothing open from round 4. The ten questions its verifiers raised
  were decided on 2026-10-24 as recommended ("cứ làm theo khuyến nghị"):
  V4.14-V4.23 under State, being applied.
- **Canvas and control flow, decided (2026-10-24, "theo khuyến nghị hết"):**
  V4.24-V4.29 under State, applied by round 4's seventh pass
  (2026-10-25).
- **Review answers, decided (2026-10-25, "theo khuyến nghị hết cho tôi"):**
  the eleven rows from the answer to ChatGPT's review and the builders' read
  of simulated runs are V4.30-V4.41 under State, applied in pass h
  (2026-10-26).
- **Pass h's questions, decided (2026-10-26, "theo khuyến nghị hết cho
  tôi"):** Q-h1 to Q-h11 as recommended, each logged `(Đạt)` in its owning
  spec: a `setup` tenant behaves as `locked` but for the two owners' first
  sign-in and the operators' routes, and leaves only for `active` or
  `offboarding` (tenant-rbac R3.14, R3.15; ADR-0102); a holder of
  `connections.manage` revokes for compromise alone; no payload of an own
  simulated run without `runs.read_payloads`; submit refuses an unkeyed
  effect step in a parallel lane (workflow-engine R2.20) and a sub-workflow
  call to a workflow without a `triggers[]` entry of kind `call` (R2.21,
  R8.7); the role routes refuse the `platform_admin` bypass (tenant-rbac
  R3.16); a workflow with no scenario case fails its gate
  (`scenario_missing`), cases read and written under the `workflow` kind's
  keys; `score_reason` is a protected field; the `platform.usage_events`
  fragment stays `enforced: false` until counsel.
- **Đạt, for W2 (domain-packs, `needs-info`):** Q4, whether the pack
  installer may use its own reserved prefix through the public routes, and
  Q5, which route writes `origin` on components that already exist.
- **Then:** `Duyệt` of each spec and of its ticket breakdown once it passes
  `checking-plan-readiness`, which no ticket reaches `ready-for-agent` without.
- **Acted on, not decided:** the platform team curates the MCP catalogue
  (DO-46.1), and whoever
  keeps dw-proterial moves it off `memberships.role_keys` before
  tenant-rbac/03 locks the column (FOG-49). W1 cannot raise a limit or loosen
  residency (no two-person path yet), so the pilot's ceilings must be right
  when seeded.
- **Requester:** the pilot team, approver and sponsor by name (DO-22); pricing
  before GA (DO-59.2).
- **Counsel:** the PDPL processing-service certificate (DO-53, Decree
  356/2025/ND-CP, Art. 21-27) before any real personal data; roles and DPA
  (DO-54.2); the incident-notice term (DO-56.2); Art. 4 of Decree 356 for
  field defaults (DO-34.2); the AI Law (DO-60); fan-out to two tenants of one
  Page or OA (DO-48.2); the legal basis for transactional messages under Law
  91/2025 and Decree 356 before the `transactional` rule (V4.39).

## Lộ trình

| Tính năng (thư mục)     | Ý định                                                                                                                                                             | Yêu cầu cấp area                                                                                                                                      | Trong; để cho  | Phụ thuộc                                                                                                                                                                                                                                                                                                                                 |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `studio-skeleton`       | Cho Studio một chỗ ở trong repo (một distribution, schema `studio`, seam API/web, luật compose) mà mọi spec khác xây lên, không seam rỗng                          | YC1, YC2, YC3, YC6, YC69                                                                                                                              | trong (W1, W2) | `runtime-hardening`, `tenant-config`, `tenant-rbac`                                                                                                                                                                                                                                                                                       |
| `foundations-hardening` | Sửa các lỗi đã đo ở hàng rào tenant, danh tính, quyền của `dw_app` và offboarding của nền tảng mà Studio đứng lên, mỗi lỗi có test âm đã thấy đỏ                   | YC4                                                                                                                                                   | trong (W1, W2) | `studio-skeleton`                                                                                                                                                                                                                                                                                                                         |
| `runtime-hardening`     | Sửa các lỗi đã đo ở đường hiệu ứng, biên mạng, run và outbox của nền tảng: công cụ chạy một lần, không gọi ra địa chỉ nội bộ, run và sự kiện không kẹt             | YC4, YC5, YC41, YC63                                                                                                                                  | trong (W1, W2) | `foundations-hardening`, `org-and-principals`, `tenant-config`                                                                                                                                                                                                                                                                            |
| `app-standards`         | Mọi route mới của Studio và nền tảng nói cùng một quy ước HTTP: một vỏ lỗi, khóa chống lặp gắn người gọi, ETag, keyset có kiểu                                     | YC1, YC3, YC5, YC27                                                                                                                                   | trong (W1, W2) | không                                                                                                                                                                                                                                                                                                                                     |
| `org-and-principals`    | Cho tenant một mô hình chủ thể đủ cho D1: thành viên cấp tenant, tài khoản dịch vụ làm run-as, rồi cây workspace, nhóm, quản lý và SSO ở v1                        | YC7, YC8, YC9, YC10, YC11, YC114                                                                                                                      | trong (W1, W2) | `app-standards`, `foundations-hardening`, `studio-skeleton`, `tenant-rbac`                                                                                                                                                                                                                                                                |
| `tenant-rbac`           | Vai là dữ liệu của tenant, mỗi quyền có độ sâu, một hàm quyền hiệu lực trong PostgreSQL, chống leo thang                                                           | YC12, YC13, YC14, YC15, YC16, YC22, YC82, YC114                                                                                                       | trong (W1, W2) | `app-standards`, `custom-objects`, `foundations-hardening`, `org-and-principals`, `studio-skeleton`                                                                                                                                                                                                                                       |
| `record-access`         | Ai thấy bản ghi nào được quyết định trong PostgreSQL bằng RLS trên một sổ tầm truy cập, không ở ứng dụng                                                           | YC3, YC6, YC12, YC14, YC17, YC18, YC19, YC20, YC21, YC50, YC57, YC82, YC113                                                                           | trong (W1, W2) | `app-standards`, `custom-objects`, `foundations-hardening`, `org-and-principals`, `tenant-config`, `tenant-rbac`                                                                                                                                                                                                                          |
| `field-security`        | Một hàm quyết định trường nào người gọi thấy hay sửa, áp ở mọi đường ra kể cả agent, workflow, phê duyệt và lịch sử run                                            | YC20, YC22, YC23, YC24, YC51, YC87, YC113                                                                                                             | trong (W1, W2) | `compliance-pdpl`, `custom-objects`, `record-access`, `telemetry-and-audit`, `tenant-rbac`, `tools-and-skills`, `workflow-nodes`                                                                                                                                                                                                          |
| `custom-objects`        | Tenant định nghĩa object và field làm metadata trên bảng cố định; mọi đọc ghi bản ghi đi qua một RecordService                                                     | YC3, YC6, YC17, YC20, YC23, YC24, YC25, YC26, YC27, YC28, YC29, YC84, YC95, YC101, YC102, YC103                                                       | trong (W1, W2) | `agent-lifecycle`, `app-standards`, `compliance-pdpl`, `field-security`, `foundations-hardening`, `org-and-principals`, `record-access`, `studio-skeleton`, `telemetry-and-audit`, `tenant-config`, `tenant-rbac`, `usage-and-limits`                                                                                                     |
| `tenant-config`         | Một vỏ phiên bản chung cho mọi thứ tenant dựng, chế độ chạy do server đặt, và mỗi lượt chạy ghim đúng thứ nó dùng                                                  | YC30, YC31, YC32, YC33, YC34, YC35, YC36, YC37, YC75                                                                                                  | trong (W1, W2) | `app-standards`, `connections-and-vault`, `foundations-hardening`, `org-and-principals`, `runtime-hardening`, `studio-skeleton`, `tenant-rbac`                                                                                                                                                                                            |
| `domain-packs`          | Gói nền tảng (Marketing trước) cài vào tenant chỉ qua API công khai thành bản sao có nguồn gốc; cập nhật là đề xuất vào bản nháp                                   | YC38                                                                                                                                                  | trong (W2)     | `agent-builder`, `custom-objects`, `tenant-config`, `tenant-rbac`, `workflow-engine`                                                                                                                                                                                                                                                      |
| `workflow-engine`       | Quy trình là tài liệu `dw.workflow/v1` biên dịch mỗi phiên bản thành StateGraph, chạy ở worker từ hàng đợi Postgres, chờ người bền vững                            | YC32, YC33, YC34, YC39, YC41, YC45, YC81, YC94, YC100, YC102, YC105, YC108, YC109, YC110, YC117                                                       | trong (W1, W2) | `agent-lifecycle`, `connections-and-vault`, `record-access`, `runtime-hardening`, `tenant-config`, `tenant-rbac`, `usage-and-limits`, `workflow-nodes`                                                                                                                                                                                    |
| `workflow-triggers`     | Trigger chỉ xin run, không tự chạy; Data Hub nhận dữ liệu ngoài qua endpoint có chữ ký, chống trùng và lưu giữ có hạn                                              | YC8, YC42, YC43, YC44, YC46, YC72, YC84, YC88, YC97, YC98, YC102, YC103, YC106                                                                        | trong (W1, W2) | `agent-lifecycle`, `connections-and-vault`, `org-and-principals`, `telemetry-and-audit`, `tenant-config`, `usage-and-limits`, `workflow-engine`                                                                                                                                                                                           |
| `workflow-nodes`        | Các loại bước là mã nền tảng trong một sổ đăng ký; CEL là ngôn ngữ biểu thức duy nhất; bước con người là cổng do server thực thi                                   | YC19, YC40, YC41, YC45, YC47, YC48, YC49, YC50, YC51, YC52, YC53, YC57, YC69, YC87, YC94, YC95, YC98, YC101, YC104, YC105, YC108, YC110, YC113, YC117 | trong (W1, W2) | `agent-builder`, `agent-lifecycle`, `compliance-pdpl`, `custom-objects`, `field-security`, `model-connections`, `record-access`, `studio-skeleton`, `tenant-config`, `tools-and-skills`, `workflow-engine`                                                                                                                                |
| `workflow-builder-ui`   | Người dựng không viết mã dựng quy trình trên sơ đồ có cấu trúc (đặt bước vào ô), cấu hình bước bằng biểu mẫu, chạy mô phỏng và gửi kiểm định                       | YC33, YC39, YC40, YC75, YC102, YC105, YC108, YC109, YC110, YC116, YC117                                                                               | trong (W1, W2) | `agent-lifecycle`, `studio-skeleton`, `telemetry-and-audit`, `workflow-engine`, `workflow-nodes`, `workflow-triggers`                                                                                                                                                                                                                     |
| `connections-and-vault` | Bí mật của tenant mã hóa phong bì dưới khóa tenant trong OpenBao; mọi lời gọi ra ngoài đi qua một egress client; trình kết nối là manifest biên dịch thành công cụ | YC24, YC34, YC42, YC48, YC61, YC62, YC63, YC64, YC65, YC97, YC107                                                                                     | trong (W1, W2) | `foundations-hardening`, `org-and-principals`, `runtime-hardening`, `studio-skeleton`, `tenant-config`, `tenant-rbac`, `tools-and-skills`                                                                                                                                                                                                 |
| `tools-and-skills`      | Mọi công cụ đi qua một ToolExecutor tự kiểm JSON Schema và chính sách; công cụ theo loại, kỹ năng theo Agent Skills                                                | YC19, YC23, YC46, YC48, YC59, YC60, YC64, YC66, YC67, YC69, YC86, YC96, YC101                                                                         | trong (W1, W2) | `custom-objects`, `field-security`, `model-connections`, `runtime-hardening`, `tenant-config`                                                                                                                                                                                                                                             |
| `mcp-client`            | Nền tảng là client MCP qua SDK chính thức trong một dịch vụ cô lập, định nghĩa công cụ ghim băm và duyệt hai người                                                 | YC68                                                                                                                                                  | trong (W2)     | `agent-lifecycle`, `connections-and-vault`, `tools-and-skills`, `usage-and-limits`                                                                                                                                                                                                                                                        |
| `agent-builder`         | Agent là tài liệu `dw.agent/v1` trong vỏ chung, biên dịch theo (tenant, phiên bản) trong runner hiện có, chạy ở worker                                             | YC19, YC48, YC54, YC55, YC56, YC57, YC78, YC93, YC96                                                                                                  | trong (W1, W2) | `agent-lifecycle`, `app-standards`, `compliance-pdpl`, `model-connections`, `org-and-principals`, `record-access`, `studio-skeleton`, `telemetry-and-audit`, `tenant-config`, `tenant-rbac`, `tools-and-skills`, `usage-and-limits`, `workflow-engine`                                                                                    |
| `model-connections`     | Một ModelResolver theo tenant trả lời mọi cửa model; tenant kết nối model của mình qua một lane LiteLLM không trạng thái                                           | YC32, YC58, YC79, YC85, YC91                                                                                                                          | trong (W1, W2) | `tenant-config`, `usage-and-limits`                                                                                                                                                                                                                                                                                                       |
| `code-sandbox`          | Mã của tenant chạy trong container riêng mới mỗi lần (không mạng, giới hạn CPU, bộ nhớ, pid, đĩa, thời gian)                                                       | YC69                                                                                                                                                  | trong (W1, W2) | không                                                                                                                                                                                                                                                                                                                                     |
| `agent-lifecycle`       | Phiên bản đi qua một máy trạng thái do database canh; chỉ live khi cổng qua trên đúng hash và người khác tác giả duyệt; đóng băng và tắt kiểm ở mọi cửa            | YC10, YC30, YC60, YC70, YC71, YC72, YC73, YC74, YC75, YC82, YC93, YC115, YC116                                                                        | trong (W1, W2) | `compliance-pdpl`, `foundations-hardening`, `org-and-principals`, `runtime-hardening`, `studio-skeleton`, `telemetry-and-audit`, `tenant-config`, `tenant-rbac`, `tools-and-skills`, `usage-and-limits`, `workflow-builder-ui`, `workflow-engine`                                                                                         |
| `usage-and-limits`      | Sổ sử dụng theo lượt gọi (D6) là nguồn cho hạn mức, màn sử dụng và đối soát; hạn mức giữ trước bằng lease Postgres khi nhận run                                    | YC44, YC76, YC77, YC78, YC79                                                                                                                          | trong (W1, W2) | `agent-builder`, `compliance-pdpl`, `foundations-hardening`, `org-and-principals`, `studio-skeleton`, `telemetry-and-audit`, `tenant-rbac`, `workflow-engine`                                                                                                                                                                             |
| `telemetry-and-audit`   | Span theo OTel GenAI không nội dung; lịch sử chạy cho tenant từ Postgres dưới RLS; audit tra cứu được                                                              | YC23, YC80, YC81, YC82, YC83, YC88, YC109                                                                                                             | trong (W1, W2) | `app-standards`, `field-security`, `studio-skeleton`, `tenant-rbac`, `usage-and-limits`, `workflow-engine`                                                                                                                                                                                                                                |
| `compliance-pdpl`       | Dữ liệu cá nhân được phân loại một chủ, tuyến model theo vùng, gửi tin marketing qua một sàn có đồng ý, phiên bản có phân tích bộ ba nguy hiểm khi xuất bản        | YC22, YC24, YC49, YC67, YC71, YC82, YC84, YC85, YC86, YC88, YC89, YC90, YC91, YC92, YC93, YC112, YC113                                                | trong (W1, W2) | `agent-builder`, `agent-lifecycle`, `custom-objects`, `model-connections`, `telemetry-and-audit`, `tenant-config`, `tools-and-skills`, `usage-and-limits`, `workflow-engine`                                                                                                                                                              |
| `marketing-pilot`       | Chứng minh Studio đầu-cuối chỉ qua bề mặt tenant: lead từ form website tới email đầu tiên đã duyệt, không có mã marketing trong nền tảng                           | YC2, YC3, YC4, YC29, YC47, YC74, YC87, YC89, YC92, YC94, YC95, YC96, YC97, YC98, YC99, YC100, YC114, YC115                                            | trong (W1, W2) | `agent-builder`, `agent-lifecycle`, `compliance-pdpl`, `connections-and-vault`, `custom-objects`, `field-security`, `org-and-principals`, `record-access`, `telemetry-and-audit`, `tenant-config`, `tenant-rbac`, `tools-and-skills`, `usage-and-limits`, `workflow-builder-ui`, `workflow-engine`, `workflow-nodes`, `workflow-triggers` |
| `domain-probe`          | Một miền thứ hai (Đề nghị mua hàng) dựng chỉ qua API công khai của Studio trong CI, để nền tảng không mang mã của miền nào                                         | YC111                                                                                                                                                 | trong (W1)     | `agent-lifecycle`, `marketing-pilot`, `workflow-engine`, `workflow-nodes`                                                                                                                                                                                                                                                                 |

## ADR

Khối số dành riêng: 0100-0199.

| Số   | Tên                                                                                                                                         | Tệp                                                                                            |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| 0100 | Studio is platform code in this repository                                                                                                  | `docs/adr/0100-studio-is-platform-code-in-this-repository.md`                                  |
| 0101 | The Studio builder canvas uses @xyflow/react laid out by @dagrejs/dagre on one path                                                         | `docs/adr/0101-studio-canvas-is-an-allowlisted-ui-exception.md`                                |
| 0102 | A workspace is a nested                                                                                                                     | `docs/adr/0102-workspace-is-a-nested-data-owning-unit.md`                                      |
| 0103 | Only people and service principals act                                                                                                      | `docs/adr/0103-runs-act-as-a-principal-within-a-boundary.md`                                   |
| 0104 | Roles are tenant data built from a migration-owned permission catalogue                                                                     | `docs/adr/0104-tenant-roles-with-depth-and-one-effective-grants-owner.md`                      |
| 0105 | PostgreSQL decides which records a principal reaches                                                                                        | `docs/adr/0105-record-reach-is-decided-by-postgresql.md`                                       |
| 0106 | Every field carries a personal-data category                                                                                                | `docs/adr/0106-field-access-follows-personal-data-category.md`                                 |
| 0107 | Tenant objects are metadata over fixed migration-created tables                                                                             | `docs/adr/0107-custom-objects-over-fixed-tables-one-record-service.md`                         |
| 0108 | Every platform route speaks one problem+json envelope and one set of list and mutation conventions                                          | `docs/adr/0108-one-error-envelope-and-caller-bound-idempotency.md`                             |
| 0109 | Studio definitions are versioned documents in one shared envelope                                                                           | `docs/adr/0109-versioned-documents-one-envelope-and-run-manifest.md`                           |
| 0110 | A tenant's configuration                                                                                                                    | `docs/adr/0110-tenant-configuration-is-maker-checker-and-bindings.md`                          |
| 0111 | Environments in v1 are versions and a server-fixed run mode (live                                                                           | `docs/adr/0111-run-modes-are-the-v1-environments.md`                                           |
| 0112 | A workflow is a dw.workflow/v1 document validated in one pass and compiled per published version to a LangGraph StateGraph                  | `docs/adr/0112-workflows-compile-to-langgraph-one-effect-per-node.md`                          |
| 0113 | Every Studio run is requested through one door and executed by the worker from a Postgres queue that is the run row itself                  | `docs/adr/0113-every-run-is-requested-and-queued-in-postgres.md`                               |
| 0114 | CEL is the one expression language for tenant text                                                                                          | `docs/adr/0114-cel-is-the-one-expression-language.md`                                          |
| 0115 | Tenant credentials are envelope-encrypted under a per-tenant key                                                                            | `docs/adr/0115-tenant-credentials-vault-and-one-egress-client.md`                              |
| 0116 | A tool is tenant data of a registered kind that reaches the model only as a pinned version                                                  | `docs/adr/0116-tools-are-tenant-data-through-one-executor.md`                                  |
| 0117 | An agent is a form-configured dw.agent/v1 document compiled per version inside the existing runner                                          | `docs/adr/0117-agents-are-form-configured-documents.md`                                        |
| 0118 | Every model door asks one tenant-aware ModelResolver                                                                                        | `docs/adr/0118-one-model-resolver-and-tenant-models-via-litellm.md`                            |
| 0119 | Every execution of tenant code runs in its own fresh gVisor container launched by a first-party sandbox-runner                              | `docs/adr/0119-each-code-execution-gets-a-fresh-gvisor-container.md`                           |
| 0120 | A version goes live only through a database-guarded stage machine                                                                           | `docs/adr/0120-publish-gate-and-run-control-switches.md`                                       |
| 0121 | A per-call usage ledger returns as metering with named readers                                                                              | `docs/adr/0121-usage-ledger-returns-and-limits-are-postgres-leases.md`                         |
| 0122 | Tenants read run history                                                                                                                    | `docs/adr/0122-tenants-read-run-history-from-postgres.md`                                      |
| 0123 | The data plane stays in Vietnam                                                                                                             | `docs/adr/0123-data-stays-in-vietnam-and-model-calls-pass-a-residency-gate.md`                 |
| 0124 | A marketing message reaches a person only through a platform send floor checked in the ToolExecutor against a platform-owned consent ledger | `docs/adr/0124-marketing-messages-pass-a-platform-send-floor.md`                               |
| 0125 | Every agent and workflow version is analysed at publish                                                                                     | `docs/adr/0125-untrusted-private-external-paths-need-a-person.md`                              |
| 0126 | A long process is an object's lifecycle in stages                                                                                           | `docs/adr/0126-a-long-process-is-an-object-lifecycle-in-stages.md`                             |
| 0127 | Reports go through the platform aggregate API, and a semantic layer reads only a per-tenant analytics store                                 | `docs/adr/0127-reports-through-the-platform-aggregate-api-and-a-per-tenant-analytics-store.md` |

## Tiếp theo

- `requirements.md`: `checking-plan-readiness` sau kiểm nhất quán vòng 4; YC111-YC117 thêm ở lượt h (26/10/2026).
- ADR 0100-0127: Accepted trừ 0119 (0126, 0127 ngày 24/10/2026); 0107, 0114, 0115 chờ số đo của custom-objects/01, FOG-50, spike 21; 0119 chờ code-sandbox/01; mỗi lượt sửa của vòng 4 ghi ở mục Amendments của ADR mà nó chạm (25/10/2026).
- `docs/platform/CONTEXT.md`: chạy reader test của `checking-plan-readiness` trên thuật ngữ dễ nhầm (23/10/2026).
- [`studio-skeleton`](studio/studio-skeleton/spec.md): `checking-plan-readiness` cho spec và ticket 01: CẦN XEM (27/10/2026; 0 CRITICAL, 8 HIGH). Đạt nhận mọi khuyến nghị cùng ngày (câu 1 B: dòng loại trừ offboarding có cấu trúc, catalog xác nhận; câu 2 B: không vai nào ngoài chủ sở hữu giữ quyền trên partition; câu 3 A: 401 trước khi đọc body; câu 4 A: `registered_by` trong dòng báo đỏ) và mọi cách sửa HIGH, MEDIUM; đã sửa spec, ticket 01, 02, 04. Gate chạy lại trên `fa812f9` (lượt chạy lại thứ nhất): CẦN XEM (0 CRITICAL, 11 HIGH); Đạt nhận mọi khuyến nghị (27/10/2026: `EXPORT_EXCLUSIONS` tách khỏi loại trừ xóa, danh sách có trước luật khóa bằng OID, `kept` nêu khóa mảnh retention) và ủy quyền làm theo khuyến nghị của gate về sau mà không hỏi lại; đã sửa spec, ticket 01, 02. Lượt chạy lại thứ hai trên `bce52d4`: CHƯA ĐẠT (1 CRITICAL: R2.8 đòi `tenant_id` trên mọi bảng `studio` trái bảng tham chiếu `studio.artifact_kinds` của ADR-0109 (Accepted) quyết 1; 5 HIGH: token không hợp lệ giữa R6.5 và R6.8, quyền kế thừa qua thành viên vai, `_PLATFORM_PREDATING` với R4.5, ca dương của tiêu chí R4.1 và R4.3, phạm vi luật của R8). Đã sửa theo khuyến nghị (ủy quyền 27/10/2026) trên spec, ticket 01, 02, 04. Đạt chọn chạy thêm một lượt (A, 27/10/2026): gate trên `d9fc4da` CẦN XEM (0 CRITICAL, 6 HIGH: quyền theo cột, UPDATE cả bảng của `dw_app`, ngoại lệ compose không khóa, `network_mode`/`privileged` lách luật compose, schema của R3.6, xác thực trước body với một bộ xác minh). Đã sửa theo khuyến nghị; ba lần xác nhận sửa bằng subagent ngữ cảnh mới (trên `e9084eb`, `2639c06`, `dfed956`) tìm thêm chín điểm, đều đã sửa. Verdict ĐẠT (27/10/2026; 0 CRITICAL, 0 HIGH; ticket 01), dựa trên lượt gate `d9fc4da` và các lần xác nhận đó theo phương án A của Đạt, không phải một lượt đọc mở mới. Đạt duyệt spec và cách chia ticket 01-04 (27/10/2026); ticket 01 đã code (27/10/2026): kiểm tra đăng ký, schema `studio`, sổ partition, test phủ offboarding, bước CI số ADR; `reviewing-feature-security` xong. CI trên `b6d065d` xanh ở bộ tích hợp đầy đủ; ticket 01 đóng (27/10/2026). Tiếp theo ticket 02 (chờ tenant-config/02 cùng lần push), và gate cho ticket 03, 04 trước khi code.
- [`foundations-hardening`](studio/foundations-hardening/spec.md): tách xong (R6-R10 và ticket 04-06 sang `runtime-hardening`); kiểm nhất quán vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`runtime-hardening`](studio/runtime-hardening/spec.md): tách từ `foundations-hardening` (số R, G và kiểm soát giữ nguyên, ticket 04-06 thành 01-03); kiểm nhất quán vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`app-standards`](studio/app-standards/spec.md): ticket 01 xong ở `feat/app-standards-01` (`41a8c37`, `996d5f1`). R2-R5 đã sửa theo hai lần kiểm 26/10/2026 và theo câu trả lời của Đạt ngày 27/10/2026 (Q2: việc dọn tách sang ticket 04, chờ telemetry-and-audit/01; Q3: route bắt buộc khóa tự chống lặp hiệu ứng; phát lại kiểm lại quyền; index audit theo lượt chạy mang `workspace_id`, ADR-0122 sửa cùng). Spec `needs-triage`, `Duyệt: Đạt 27/10/2026`. `checking-plan-readiness` cho spec và ticket 02: CẦN XEM (0 CRITICAL, 6 HIGH); Đạt nhận mọi khuyến nghị ("cứ tiếp tục theo khuyến nghị"); gate trên `f9c5fa4` CẦN XEM (0 CRITICAL, 8 HIGH), đã sửa; gate trên `f412ba4` CẦN XEM (0 CRITICAL, 6 HIGH). Theo phương án A của Đạt, sáu HIGH đó và hai MEDIUM đã sửa, các MEDIUM còn lại Đạt nhận rủi ro; Đạt duyệt spec và cách chia ticket 01-04 (27/10/2026); gate trên `25e81be` CẦN XEM (0 CRITICAL, 5 HIGH), Đạt nhận năm khuyến nghị và spec đã sửa (R2.21-R2.23, R3.8, R5.10, R5.11, APS23-APS25, ticket 02 phủ chín operation), nên `Duyệt: chưa` lại. Gate trên `940a88f` (lượt chạy lại thứ nhất): CẦN XEM (27/10/2026; 0 CRITICAL, 5 HIGH: khóa hiệu ứng chưa có chỗ lưu, phạm vi và hạn; G4 với R2.16 khi đổi body sau G6; `trace_id` từ `traceparent` với R1.10; body đã lưu chỉ riêng người gọi nhờ `claim`; `If-None-Match: *` dò tồn tại ngoài trần của ADR-0105 quyết định 8). Đạt nhận năm khuyến nghị và spec đã sửa (`platform.effect_keys`, R2.24-R2.26, R3.14 giao custom-objects, APS26-APS28). Gate trên `fb6a69c` (lượt chạy lại thứ hai, cuối cho phiên bản này): CẦN XEM (27/10/2026; 0 CRITICAL, 4 HIGH, cả bốn quanh `platform.effect_keys`: đích của khóa thiếu đường cụ thể, query và workspace; offboarding thiếu DELETE; ADR-0122 quyết định 7 đòi mảnh lưu giữ cùng thay đổi tạo kho, nên ticket 02 đụng telemetry-and-audit/01; route `include_in_schema=False` lọt khỏi test dựng ứng dụng). Đạt chọn đường (1) và phương án A: `request_hash` thay `body_hash`, DELETE cho offboarding, route ngoài schema, mảnh và bộ xóa của `platform.effect_keys` sang ticket 02, nên ticket 02 chờ thêm telemetry-and-audit/01 (R2.27, R2.28, APS29-APS31). Gate trên `1080b25`: CẦN XEM (27/10/2026; 0 CRITICAL, 3 HIGH: phép đọc lại `result` của `platform.effect_keys` không có R và không nói trả gì khi không thấy; R2.26 không nói phép quét thấy bảng bằng cách nào; R2.21 không biểu diễn được quyền tùy body như `POST /support/grants`). Đạt nhận cả ba khuyến nghị (R2.29, R2.30, R2.21 và R2.26 sửa, APS32, APS33). Gate trên `6785b1b`: CẦN XEM (27/10/2026; 0 CRITICAL, 3 HIGH: dòng `platform.effect_keys` hết hạn trước dòng khóa HTTP mà giành lại đã làm mới; `platform.effect_keys` không có `workspace_id` hay hình policy; giá trị của `GET ?filter=` và `cursor` vào URL mà không gì chặn khỏi log). Đạt nhận ba HIGH và ba MEDIUM rẻ (R2.31-R2.33, R5.12, APS34-APS37). Gate trên `538d2cb`: CẦN XEM (27/10/2026; 0 CRITICAL, 3 HIGH: `workspace_id` trong khóa chính của `platform.effect_keys` làm APS24 và R2.32 trái nhau và cho hiệu ứng tenant-wide chạy lại từ workspace khác; thứ tự giữa tra khóa hiệu ứng và so `If-Match`; R2.16 hứa không lặp cho cả hiệu ứng rời giao dịch). Đạt nhận ba khuyến nghị (R2.32 rút lại, R2.34, R2.35, APS35, APS38, APS39). Gate trên `2492c15`: CẦN XEM (27/10/2026; 0 CRITICAL, 1 HIGH: `result` của `platform.effect_keys` chỉ mang một `id`, nên route batch của R2.7 không phát lại được theo R2.16 và R2.29). Đạt nhận khuyến nghị: R2.16 chỉ cho operation có một tài nguyên, batch thuộc spec mở route. Gate trên `c6e4b2c`: CẦN XEM (27/10/2026; 0 CRITICAL, 3 HIGH: cột `workspace_id` của `platform.effect_keys` không ai đọc và hai lượt kiểm đọc là trái `CLAUDE.md`; giới hạn cây lọc và tham số bind chỉ ràng buộc route HTTP, không ràng buộc tool của agent; phát lại body ở lớp HTTP không ghi `pd.read` của ADR-0106 quyết định 5). Đạt chọn đường (2): ba khuyến nghị đã áp (bỏ `workspace_id` khỏi `platform.effect_keys`, R5.13, R2.36 giao custom-objects), các MEDIUM còn lại Đạt nhận rủi ro, và Đạt duyệt spec (`Duyệt: Đạt 27/10/2026`). Gate cho ticket 02 trên `85aee2a` (bản Đạt duyệt): CHƯA ĐẠT (27/10/2026; 1 CRITICAL, 7 HIGH trên yêu cầu của ticket 02). CRITICAL: R2.9 và R2.13 (bộ xóa chỉ ghi số dòng vào log, không audit) theo ADR-0011 (Accepted) mục "Not applied", nhưng `CLAUDE.md` (Agent and tool rules) bắt mọi lane tự hành động audit như chính nó và không ghi miễn trừ đó; R2.25 của ticket 02 cùng hình. Câu hỏi cho Đạt: (A, khuyến nghị) ghi miễn trừ của ADR-0011 cho dòng vận hành vào `CLAUDE.md` trước, hay (B) hàm xóa trả số dòng theo tenant và lane ghi `retention.purged` như telemetry-and-audit R5.15. HIGH: mốc 24 giờ của lần phát lại chỉ dựa vào bộ xóa mà chưa lane nào chạy (lane của `RetentionPurgerRegistry` là telemetry-and-audit/03), nên cần một R cho `claim` và phép tra coi dòng quá hạn là hết hạn; bước 5 bỏ ngỏ dòng `platform.effect_keys` là bắt buộc ở mọi operation hay chỉ ở operation trượt test, và cho phép "thôi nhận khóa"; `result.id` của `PUT .../memberships`, quyết định duyệt và bốn chuyển trạng thái grant chưa định nghĩa; R2.34 (APS38) cần `RequireIfMatch` của ticket 03 và bộ đếm của custom-objects; ngữ cảnh của lời gọi `decide` không qua HTTP (lane của worker) với R2.22; chỗ chèn dòng khóa hiệu ứng so với ràng buộc duy nhất của chính hiệu ứng (APS37); R2.25 xóa "mọi dòng" trái R2.31. Ngoài phạm vi ticket 02, chuyển cho gate của ticket 03: R5.13 không có kiểm soát cho đường không qua HTTP tự dựng `WHERE` (HIGH), đua hai `If-None-Match: *` cùng id. Tiếp theo: Đạt trả lời câu CRITICAL; sửa bảy HIGH theo khuyến nghị qua `writing-plan-specs` trong cùng lượt, rồi gate chạy lại cho ticket 02.
- [`org-and-principals`](studio/org-and-principals/spec.md): kiểm nhất quán vòng 4 sau các lượt sửa của vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`tenant-rbac`](studio/tenant-rbac/spec.md): kiểm nhất quán vòng 4 sau các lượt sửa của vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`record-access`](studio/record-access/spec.md): kiểm nhất quán vòng 4 sau các lượt sửa của vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`field-security`](studio/field-security/spec.md): kiểm nhất quán vòng 4 sau các lượt sửa của vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`custom-objects`](studio/custom-objects/spec.md): kiểm nhất quán vòng 4 sau các lượt sửa của vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`tenant-config`](studio/tenant-config/spec.md): kiểm nhất quán vòng 4 sau các lượt sửa của vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`domain-packs`](studio/domain-packs/spec.md): chỉ có phạm vi W2; cắt ticket khi đợt 2 bắt đầu (23/10/2026).
- [`workflow-engine`](studio/workflow-engine/spec.md): kiểm nhất quán vòng 4 sau các lượt sửa của vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`workflow-triggers`](studio/workflow-triggers/spec.md): kiểm nhất quán vòng 4 sau các lượt sửa của vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`workflow-nodes`](studio/workflow-nodes/spec.md): kiểm nhất quán vòng 4 sau các lượt sửa của vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`workflow-builder-ui`](studio/workflow-builder-ui/spec.md): kiểm nhất quán vòng 4 sau các lượt sửa của vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`connections-and-vault`](studio/connections-and-vault/spec.md): kiểm nhất quán vòng 4 sau các lượt sửa của vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`tools-and-skills`](studio/tools-and-skills/spec.md): kiểm nhất quán vòng 4 sau các lượt sửa của vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`mcp-client`](studio/mcp-client/spec.md): chỉ có phạm vi W2; cắt ticket khi đợt 2 bắt đầu (23/10/2026).
- [`agent-builder`](studio/agent-builder/spec.md): kiểm nhất quán vòng 4 sau các lượt sửa của vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`model-connections`](studio/model-connections/spec.md): kiểm nhất quán vòng 4 sau các lượt sửa của vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`code-sandbox`](studio/code-sandbox/spec.md): kiểm nhất quán vòng 4 sau các lượt sửa của vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`agent-lifecycle`](studio/agent-lifecycle/spec.md): kiểm nhất quán vòng 4 sau các lượt sửa của vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`usage-and-limits`](studio/usage-and-limits/spec.md): kiểm nhất quán vòng 4 sau các lượt sửa của vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`telemetry-and-audit`](studio/telemetry-and-audit/spec.md): `checking-plan-readiness` cho spec và ticket 01: CHƯA ĐẠT (27/10/2026; 2 CRITICAL, 11 HIGH). Đạt nhận mọi khuyến nghị cùng ngày (câu 1 B: lane DELETE Bước chạy ở ngày 30, bỏ qua lượt chưa kết thúc; câu 2 A: ADR-0106 quyết 4 theo ADR-0122 cho payload lịch sử chạy; câu 3 A: một danh sách định danh cho phép; câu 4 B: `dw_node_failure_total` sang workflow-engine/03, cạnh mới từ ticket 01). Đã sửa spec, ticket 01-03, ADR-0106 và workflow-engine/03; Đạt duyệt spec và cách chia ticket 01-04 trên bản đã sửa (27/10/2026). Gate chạy lại trên `e4070f4` (lượt chạy lại thứ nhất): CẦN XEM (0 CRITICAL, 8 HIGH). Đạt nhận mọi khuyến nghị (27/10/2026: giá trị không có `field_id` bị che; năm MEDIUM rẻ sửa, các MEDIUM còn lại nhận rủi ro); đã sửa spec, ticket 01-04 và workflow-engine/03; Đạt duyệt bản này (27/10/2026). Gate chạy lại lần cuối trên `e6135bd`: CẦN XEM (0 CRITICAL, 6 HIGH: che lúc đọc không đóng khi lỗi, mã lỗi lúc chạy không quy về catalog, `runs.read` chéo workspace và loại khóa, bên đọc khác của cột payload, bộ lọc danh sách với kiểm hình kế hoạch, chữ "chạm tới" của R3.6). Đạt chọn phương án A (27/10/2026): sáu HIGH và ba MEDIUM rẻ đã sửa, các MEDIUM còn lại nhận rủi ro, không chạy thêm gate cho phiên bản này; Đạt duyệt bản đã sửa (27/10/2026, `1f492e2`). Gate cho ticket 01 trên `ff1312f`: ĐẠT (27/10/2026; 0 CRITICAL, 0 HIGH trên R1.1-R1.5, R5.6, R5.9-R5.14 và kiểm soát của chúng), ticket 01 lên `ready-for-agent`. Cùng lượt, năm subagent nêu 13 HIGH ngoài phạm vi ticket 01, chuyển cho gate của ticket 02-04: route `/timeline` có sẵn không lọc theo độ sâu và trả 403 thay 404; thiếu test âm chéo công ty cho route payload và `?include=payload`; `details.reason_code` của 404 cách ly có thể khác 404 id không tồn tại; `worker_runs.input` không sau `runs.read_payloads`; `pd.read` của ADR-0106 quyết 5 cạnh `run.payload.viewed`; bộ xóa của cột payload lượt chạy, dòng lượt chạy và `usage_daily` không có tiêu chí; `dw_agent_ro` đọc `run_steps` và cột payload; kênh của `field_id` do bên gọi đưa; actor và action khi lane đọc payload (R4.14, CLAUDE.md lane audit); `step_started` với CHECK `status`; `pd_category` của schema công cụ có tính là siêu dữ liệu trường không; tập trạng thái "đã kết thúc" (`dead_lettered`); `started_at` bền của `model_call` và `tool_call`. Ticket 01 đã code trên `main` (27/10/2026): `make ci` xanh, bộ tích hợp xanh trên mọi suite PostgreSQL (Qdrant, kho đối tượng và ảnh sandbox docgen không chạy ở checkout này), mutation check 31 kiểm soát đều đỏ khi gỡ. Việc thay `retention@1.7.0.yaml` bằng `retention@1.8.0.yaml` làm tám neo trong kế hoạch trỏ tệp không còn (`check_plans`, kiểm advisory ở CI): `telemetry-and-audit/spec.md:46`, `telemetry-and-audit/issues/03:328`, studio-skeleton spec và ticket 01, runtime-hardening spec, compliance-pdpl/06, discovery/20, /26 và `research.md`; sửa qua `writing-plan-specs` khi chạm tài liệu đó. Ticket 01 đóng sau CI trên `63755ce`. Tiếp theo: ticket 02 và 03, mỗi ticket một lượt `checking-plan-readiness` ngay trước khi code, khi các ticket chặn nó xong.
- [`compliance-pdpl`](studio/compliance-pdpl/spec.md): kiểm nhất quán vòng 4 sau các lượt sửa của vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`marketing-pilot`](studio/marketing-pilot/spec.md): kiểm nhất quán vòng 4 sau các lượt sửa của vòng 4, rồi `checking-plan-readiness` cho từng ticket W1 (25/10/2026).
- [`domain-probe`](studio/domain-probe/spec.md): mới ở lượt h (V4.39, H-16); kiểm nhất quán vòng 4, rồi `checking-plan-readiness` cho ticket 01 (26/10/2026).

## Đợt

Kiểm nhất quán 24/10/2026: 8 CRITICAL, 25 HIGH, 38 MEDIUM, 2 LOW; phủ YC 107/107, tiêu chí 955/1021.

- 26/10/2026 (Đạt): bỏ kiểm nhất quán vòng 4 cho cả area ("ok" với khuyến nghị): `check_plans.py` sạch,
  mâu thuẫn còn lại nằm ở ticket còn xa, và chỗ spec sai lộ ra khi dựng thì ghi ở Comments của ticket. Thay vào đó
  `checking-plan-readiness` chạy cho từng ticket ngay trước khi code; `checking-plan-consistency` chạy lại khi một ADR
  đổi trạng thái hay khi đợt 2 bắt đầu. Ba cảnh báo collision (agent-lifecycle 04~~05, custom-objects 03~~06,
  workflow-engine 07~08) xử lý khi tới các ticket đó. Code bắt đầu ở ticket không chờ ai: `app-standards/01`,
  `studio-skeleton/01`, `foundations-hardening`; mỗi spec cần `Duyệt` của Đạt và `Duyệt cách chia ticket` trước khi
  ticket lên `ready-for-agent`.
- Đợt 1 (W1: P0 nền móng và lát Marketing P1): 25 spec, 113 ticket sau lượt h (111 `needs-triage`, 2 `ready-for-human`; bậc B của V4.26 và V4.33 ở trong), chưa ticket nào `ready-for-agent`.
    - Ba vòng sửa của đợt đã dùng hết (vòng 1 ngày 23/10, vòng 2 và 3 ngày 24/10): phát hiện 139, 99 rồi
      73; CRITICAL 15, 7 rồi 8. Theo luật của `checking-plan-consistency`, phần còn lại đưa lên Đạt.
    - Sửa theo ADR và `CLAUDE.md` đã chấp nhận (7 CRITICAL): cột hàng đợi theo ADR-0113, mã `wf.*` theo
      ADR-0112, năm kiểm khi tiếp tục theo ADR-0109, AAD của phong bì theo ADR-0115, Protocol kiểm điểm gắn
      khi gửi và khi phát hành theo ADR-0120, index cho route danh sách lượt kiểm định, kết quả ca và tin
      nhắn (Data model rules), lane promotion của ADR-0111 audit đứng tên người duyệt (ADR-0011). Cùng loại:
      các cạnh Blocked by (`offboarding.py`, tệp retention, danh mục quyền) và phần lớn dòng HIGH, MEDIUM.
    - 13 câu đã chờ Đạt (vòng đời của `endpoint` là dòng CRITICAL) được Đạt quyết ngày 24/10/2026 (V4.1-V4.13)
      và đang áp ở vòng sửa thứ tư mà Đạt cho phép; dòng kết quả trên đây đổi sau lần kiểm nhất quán vòng 4.
    - Về lại roadmap (4 dòng MEDIUM): cột Phụ thuộc lệch các cạnh ticket; YC101 thiếu ở hai hàng, YC102 ở hàng
      `workflow-triggers`; chữ "simulate" và "gửi phát hành" ở hàng `workflow-builder-ui`; 17 trong 25 spec quá
      250 dòng (10 spec vẫn quá khi bỏ Hiện trạng và Quyết định), `foundations-hardening` có 11 nhóm yêu cầu.
    - Đi trước được: `app-standards` (một dòng HIGH, cạnh 01 → 02) và `foundations-hardening`, nay cùng `runtime-hardening` (hai dòng HIGH,
      cạnh với tenant-config/04 và với chín ticket sửa `offboarding.py`), không dòng CRITICAL nào chạm. Thêm
      các cạnh đó rồi chạy `checking-plan-readiness` cho từng ticket.
- Đợt 2 (W2: v1 GA): phần W2 của mọi spec ở trên, cùng `domain-packs` và `mcp-client` (chỉ có phạm vi W2: 66
  tiêu chí chưa ticket trong số đo ở trên). Cắt ticket khi đợt 1 hết dòng CRITICAL và lần kiểm nhất quán sau
  đó không còn dòng HIGH nào chưa có quyết định.
- Đợt 3 (W3: v1.5, v2): mỗi mục thành spec riêng khi tới lượt; ghi ở mục Ngoài phạm vi của từng spec.

## Ủy quyền

- Ủy quyền duyệt: Đạt, spec, từ 27/10/2026
- Ủy quyền duyệt: Đạt, requirements, từ 27/10/2026

## Slice log

Each resolved ticket adds one line here: the commit hash and one sentence.

- `41a8c37` app-standards/01: mọi route trả một mô tả lỗi problem+json (lỗi schema, đường lạ, sai method, 500 không lộ gì), OpenAPI khai `Problem` cho 4XX và 5XX, client web giữ `errors[]`.
- `996d5f1` app-standards/01 bước 9: 429 của bộ giới hạn tốc độ là problem+json; `X-Request-ID` chỉ nhận `[A-Za-z0-9._-]{1,128}` (Q-01a, Q-01b).
- `ee3420c` telemetry-and-audit/01: semconv GenAI ghim commit với ảnh chụp sinh từ YAML thượng nguồn, span và log chỉ định danh trên mọi exporter, ba metric có nơi phát, mảnh retention một kho một tệp, `platform.retention_terms` nạp lúc triển khai và `platform.retention_term_days`.
