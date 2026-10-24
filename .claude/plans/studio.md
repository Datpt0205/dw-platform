# Studio: tenant-built objects, workflows, agents and tools

Studio is the no-code capability through which a customer (tenant) builds the
data model, the workflows, the agents and the tool connections for its own
departments, starting with Marketing. It is platform code in this repository
(ADR-0100), not a business context and not a product repository. Nothing here
is built yet. Đạt accepted the ADR block on 2026-10-23 (0126 and 0127 on
2026-10-24), all but ADR-0119, which waits for the code-sandbox spike.

## State (2026-10-24): round 4 being applied after Đạt's decisions

- **Round 4 in progress (2026-10-24):** Đạt accepted the 13 recommendations
  of consistency round 3, splitting a spec past the size of
  `writing-plan-specs` when it reaches `checking-plan-readiness`
  (foundations-hardening first: R6-R10 and tickets 04-06 become
  `runtime-hardening`, numbers kept), and a fourth remediation round past the
  three-round limit of `checking-plan-consistency`. The decisions:
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

    Nine editors, each followed by a verifier, apply them with every round-3
    row; then the split, a fourth consistency check, and the readiness gate for
    app-standards, foundations-hardening and runtime-hardening.

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
- **Written:** `studio/requirements.md` (107 YC, 14 KQ); 28 ADRs in
  `docs/adr/0100`-`0127`; 25 feature specs with 97 first-wave tickets;
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

- **Đạt:** nothing open from consistency round 3 (decided 2026-10-24, State
  above). Next: `Duyệt` of each spec and of its ticket breakdown once it passes
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
  Page or OA (DO-48.2).

## Lộ trình

| Tính năng (thư mục)     | Ý định                                                                                                                                                             | Yêu cầu cấp area                                                                                                   | Trong; để cho  | Phụ thuộc                                                                                                                                                                                                                                                                                                                                 |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `studio-skeleton`       | Cho Studio một chỗ ở trong repo (một distribution, schema `studio`, seam API/web, luật compose) mà mọi spec khác xây lên, không seam rỗng                          | YC1, YC2, YC3, YC6, YC69                                                                                           | trong (W1, W2) | không                                                                                                                                                                                                                                                                                                                                     |
| `foundations-hardening` | Sửa các lỗi đã đo trong nền tảng hiện có mà Studio sẽ đứng lên, mỗi lỗi có test âm đã thấy đỏ                                                                      | YC4, YC5, YC41, YC63                                                                                               | trong (W1, W2) | không                                                                                                                                                                                                                                                                                                                                     |
| `app-standards`         | Mọi route mới của Studio và nền tảng nói cùng một quy ước HTTP: một vỏ lỗi, khóa chống lặp gắn người gọi, ETag, keyset có kiểu                                     | YC1, YC3, YC5, YC27                                                                                                | trong (W1, W2) | `foundations-hardening`                                                                                                                                                                                                                                                                                                                   |
| `org-and-principals`    | Cho tenant một mô hình chủ thể đủ cho D1: thành viên cấp tenant, tài khoản dịch vụ làm run-as, rồi cây workspace, nhóm, quản lý và SSO ở v1                        | YC7, YC8, YC9, YC10, YC11                                                                                          | trong (W1, W2) | `foundations-hardening`, `tenant-rbac`                                                                                                                                                                                                                                                                                                    |
| `tenant-rbac`           | Vai là dữ liệu của tenant, mỗi quyền có độ sâu, một hàm quyền hiệu lực trong PostgreSQL, chống leo thang                                                           | YC12, YC13, YC14, YC15, YC16, YC22, YC82                                                                           | trong (W1, W2) | `custom-objects`, `org-and-principals`                                                                                                                                                                                                                                                                                                    |
| `record-access`         | Ai thấy bản ghi nào được quyết định trong PostgreSQL bằng RLS trên một sổ tầm truy cập, không ở ứng dụng                                                           | YC3, YC6, YC12, YC14, YC17, YC18, YC19, YC20, YC21, YC50, YC57, YC82                                               | trong (W1, W2) | `custom-objects`, `foundations-hardening`, `org-and-principals`, `tenant-rbac`                                                                                                                                                                                                                                                            |
| `field-security`        | Một hàm quyết định trường nào người gọi thấy hay sửa, áp ở mọi đường ra kể cả agent, workflow, phê duyệt và lịch sử run                                            | YC20, YC22, YC23, YC24, YC51, YC87                                                                                 | trong (W1, W2) | `compliance-pdpl`, `custom-objects`, `telemetry-and-audit`, `tenant-rbac`, `tools-and-skills`, `workflow-nodes`                                                                                                                                                                                                                           |
| `custom-objects`        | Tenant định nghĩa object và field làm metadata trên bảng cố định; mọi đọc ghi bản ghi đi qua một RecordService                                                     | YC3, YC6, YC17, YC20, YC23, YC24, YC25, YC26, YC27, YC28, YC29, YC84, YC95, YC101, YC102, YC103                    | trong (W1, W2) | `app-standards`, `compliance-pdpl`, `field-security`, `org-and-principals`, `record-access`, `studio-skeleton`, `tenant-config`                                                                                                                                                                                                           |
| `tenant-config`         | Một vỏ phiên bản chung cho mọi thứ tenant dựng, chế độ chạy do server đặt, và mỗi lượt chạy ghim đúng thứ nó dùng                                                  | YC30, YC31, YC32, YC33, YC34, YC35, YC36, YC37, YC75                                                               | trong (W1, W2) | `connections-and-vault`, `foundations-hardening`, `studio-skeleton`                                                                                                                                                                                                                                                                       |
| `domain-packs`          | Gói nền tảng (Marketing trước) cài vào tenant chỉ qua API công khai thành bản sao có nguồn gốc; cập nhật là đề xuất vào bản nháp                                   | YC38                                                                                                               | trong (W2)     | `agent-builder`, `custom-objects`, `tenant-config`, `tenant-rbac`, `workflow-engine`                                                                                                                                                                                                                                                      |
| `workflow-engine`       | Quy trình là tài liệu `dw.workflow/v1` biên dịch mỗi phiên bản thành StateGraph, chạy ở worker từ hàng đợi Postgres, chờ người bền vững                            | YC32, YC33, YC34, YC39, YC41, YC45, YC81, YC94, YC100, YC102, YC105                                                | trong (W1, W2) | `agent-lifecycle`, `foundations-hardening`, `tenant-config`, `usage-and-limits`, `workflow-nodes`                                                                                                                                                                                                                                         |
| `workflow-triggers`     | Trigger chỉ xin run, không tự chạy; Data Hub nhận dữ liệu ngoài qua endpoint có chữ ký, chống trùng và lưu giữ có hạn                                              | YC8, YC42, YC43, YC44, YC46, YC72, YC84, YC88, YC97, YC98, YC103, YC106                                            | trong (W1, W2) | `connections-and-vault`, `org-and-principals`, `tenant-config`, `workflow-engine`                                                                                                                                                                                                                                                         |
| `workflow-nodes`        | Các loại bước là mã nền tảng trong một sổ đăng ký; CEL là ngôn ngữ biểu thức duy nhất; bước con người là cổng do server thực thi                                   | YC19, YC40, YC41, YC45, YC47, YC48, YC49, YC50, YC51, YC52, YC53, YC57, YC69, YC87, YC94, YC95, YC98, YC104, YC105 | trong (W1, W2) | `compliance-pdpl`, `custom-objects`, `field-security`, `model-connections`, `record-access`, `studio-skeleton`, `tools-and-skills`, `workflow-engine`                                                                                                                                                                                     |
| `workflow-builder-ui`   | Người dựng không viết mã vẽ quy trình trên canvas, cấu hình bước bằng biểu mẫu, chạy thử `simulate` và gửi phát hành                                               | YC33, YC39, YC40, YC75, YC102                                                                                      | trong (W1, W2) | `agent-lifecycle`, `studio-skeleton`, `telemetry-and-audit`, `workflow-engine`, `workflow-nodes`, `workflow-triggers`                                                                                                                                                                                                                     |
| `connections-and-vault` | Bí mật của tenant mã hóa phong bì dưới khóa tenant trong OpenBao; mọi lời gọi ra ngoài đi qua một egress client; trình kết nối là manifest biên dịch thành công cụ | YC24, YC34, YC42, YC48, YC61, YC62, YC63, YC64, YC65, YC97, YC107                                                  | trong (W1, W2) | `foundations-hardening`, `studio-skeleton`, `tenant-config`, `tenant-rbac`, `tools-and-skills`                                                                                                                                                                                                                                            |
| `tools-and-skills`      | Mọi công cụ đi qua một ToolExecutor tự kiểm JSON Schema và chính sách; công cụ theo loại, kỹ năng theo Agent Skills                                                | YC19, YC23, YC46, YC48, YC59, YC60, YC64, YC66, YC67, YC69, YC86, YC96                                             | trong (W1, W2) | `custom-objects`, `field-security`, `foundations-hardening`, `model-connections`, `tenant-config`                                                                                                                                                                                                                                         |
| `mcp-client`            | Nền tảng là client MCP qua SDK chính thức trong một dịch vụ cô lập, định nghĩa công cụ ghim băm và duyệt hai người                                                 | YC68                                                                                                               | trong (W2)     | `agent-lifecycle`, `connections-and-vault`, `tools-and-skills`, `usage-and-limits`                                                                                                                                                                                                                                                        |
| `agent-builder`         | Agent là tài liệu `dw.agent/v1` trong vỏ chung, biên dịch theo (tenant, phiên bản) trong runner hiện có, chạy ở worker                                             | YC19, YC48, YC54, YC55, YC56, YC57, YC78, YC93, YC96                                                               | trong (W1, W2) | `compliance-pdpl`, `model-connections`, `record-access`, `studio-skeleton`, `tenant-config`, `tools-and-skills`, `workflow-engine`                                                                                                                                                                                                        |
| `model-connections`     | Một ModelResolver theo tenant trả lời mọi cửa model; tenant kết nối model của mình qua một lane LiteLLM không trạng thái                                           | YC32, YC58, YC79, YC85, YC91                                                                                       | trong (W1, W2) | `compliance-pdpl`, `connections-and-vault`, `usage-and-limits`                                                                                                                                                                                                                                                                            |
| `code-sandbox`          | Mã của tenant chạy trong container riêng mới mỗi lần (không mạng, giới hạn CPU, bộ nhớ, pid, đĩa, thời gian)                                                       | YC69                                                                                                               | trong (W1, W2) | `studio-skeleton`, `usage-and-limits`                                                                                                                                                                                                                                                                                                     |
| `agent-lifecycle`       | Phiên bản đi qua một máy trạng thái do database canh; chỉ live khi cổng qua trên đúng hash và người khác tác giả duyệt; đóng băng và tắt kiểm ở mọi cửa            | YC10, YC30, YC60, YC70, YC71, YC72, YC73, YC74, YC75, YC82, YC93                                                   | trong (W1, W2) | `agent-builder`, `compliance-pdpl`, `studio-skeleton`, `tenant-config`, `workflow-engine`                                                                                                                                                                                                                                                 |
| `usage-and-limits`      | Sổ sử dụng theo lượt gọi (D6) là nguồn cho hạn mức, màn sử dụng và đối soát; hạn mức giữ trước bằng lease Postgres khi nhận run                                    | YC44, YC76, YC77, YC78, YC79                                                                                       | trong (W1, W2) | `agent-builder`, `org-and-principals`, `studio-skeleton`, `tenant-rbac`, `workflow-engine`                                                                                                                                                                                                                                                |
| `telemetry-and-audit`   | Span theo OTel GenAI không nội dung; lịch sử chạy cho tenant từ Postgres dưới RLS; audit tra cứu được                                                              | YC23, YC80, YC81, YC82, YC83, YC88                                                                                 | trong (W1, W2) | `field-security`, `usage-and-limits`, `workflow-engine`                                                                                                                                                                                                                                                                                   |
| `compliance-pdpl`       | Dữ liệu cá nhân được phân loại một chủ, tuyến model theo vùng, gửi tin marketing qua một sàn có đồng ý, phiên bản có phân tích bộ ba nguy hiểm khi xuất bản        | YC22, YC24, YC49, YC67, YC71, YC82, YC84, YC85, YC86, YC88, YC89, YC90, YC91, YC92, YC93                           | trong (W1, W2) | `agent-builder`, `agent-lifecycle`, `custom-objects`, `model-connections`, `tools-and-skills`, `workflow-engine`                                                                                                                                                                                                                          |
| `marketing-pilot`       | Chứng minh Studio đầu-cuối chỉ qua bề mặt tenant: lead từ form website tới email đầu tiên đã duyệt, không có mã marketing trong nền tảng                           | YC2, YC3, YC4, YC29, YC47, YC74, YC87, YC89, YC92, YC94, YC95, YC96, YC97, YC98, YC99, YC100                       | trong (W1, W2) | `agent-builder`, `agent-lifecycle`, `compliance-pdpl`, `connections-and-vault`, `custom-objects`, `field-security`, `org-and-principals`, `record-access`, `telemetry-and-audit`, `tenant-config`, `tenant-rbac`, `tools-and-skills`, `usage-and-limits`, `workflow-builder-ui`, `workflow-engine`, `workflow-nodes`, `workflow-triggers` |

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

- `requirements.md`: `checking-plan-readiness` sau lượt sửa các dòng của kiểm nhất quán vòng 3 (24/10/2026).
- ADR 0100-0127: Accepted trừ 0119 (0126, 0127 ngày 24/10/2026); 0107, 0114, 0115 chờ số đo của custom-objects/01, FOG-50, spike 21; 0119 chờ code-sandbox/01; các câu sửa ADR của vòng 3 chờ Đạt (24/10/2026).
- `docs/platform/CONTEXT.md`: chạy reader test của `checking-plan-readiness` trên thuật ngữ dễ nhầm (23/10/2026).
- [`studio-skeleton`](studio/studio-skeleton/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`foundations-hardening`](studio/foundations-hardening/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`app-standards`](studio/app-standards/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`org-and-principals`](studio/org-and-principals/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`tenant-rbac`](studio/tenant-rbac/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`record-access`](studio/record-access/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`field-security`](studio/field-security/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`custom-objects`](studio/custom-objects/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`tenant-config`](studio/tenant-config/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`domain-packs`](studio/domain-packs/spec.md): chỉ có phạm vi W2; cắt ticket khi đợt 2 bắt đầu (23/10/2026).
- [`workflow-engine`](studio/workflow-engine/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`workflow-triggers`](studio/workflow-triggers/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`workflow-nodes`](studio/workflow-nodes/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`workflow-builder-ui`](studio/workflow-builder-ui/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`connections-and-vault`](studio/connections-and-vault/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`tools-and-skills`](studio/tools-and-skills/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`mcp-client`](studio/mcp-client/spec.md): chỉ có phạm vi W2; cắt ticket khi đợt 2 bắt đầu (23/10/2026).
- [`agent-builder`](studio/agent-builder/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`model-connections`](studio/model-connections/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`code-sandbox`](studio/code-sandbox/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`agent-lifecycle`](studio/agent-lifecycle/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`usage-and-limits`](studio/usage-and-limits/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`telemetry-and-audit`](studio/telemetry-and-audit/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`compliance-pdpl`](studio/compliance-pdpl/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).
- [`marketing-pilot`](studio/marketing-pilot/spec.md): sửa các dòng của kiểm nhất quán vòng 3, rồi `checking-plan-readiness` cho từng ticket W1 (24/10/2026).

## Đợt

Kiểm nhất quán 24/10/2026: 8 CRITICAL, 25 HIGH, 38 MEDIUM, 2 LOW; phủ YC 107/107, tiêu chí 955/1021.

- Đợt 1 (W1: P0 nền móng và lát Marketing P1): 23 spec, 97 ticket, chưa ticket nào `ready-for-agent`.
    - Ba vòng sửa của đợt đã dùng hết (vòng 1 ngày 23/10, vòng 2 và 3 ngày 24/10): phát hiện 139, 99 rồi
      73; CRITICAL 15, 7 rồi 8. Theo luật của `checking-plan-consistency`, phần còn lại đưa lên Đạt.
    - Sửa theo ADR và `CLAUDE.md` đã chấp nhận (7 CRITICAL): cột hàng đợi theo ADR-0113, mã `wf.*` theo
      ADR-0112, năm kiểm khi tiếp tục theo ADR-0109, AAD của phong bì theo ADR-0115, Protocol kiểm điểm gắn
      khi gửi và khi phát hành theo ADR-0120, index cho route danh sách lượt kiểm định, kết quả ca và tin
      nhắn (Data model rules), lane promotion của ADR-0111 audit đứng tên người duyệt (ADR-0011). Cùng loại:
      các cạnh Blocked by (`offboarding.py`, tệp retention, danh mục quyền) và phần lớn dòng HIGH, MEDIUM.
    - Chờ Đạt (13 câu, có khuyến nghị ở mục Decisions owed): vòng đời của loại `endpoint` (CRITICAL); mất cập
      nhật ở nhánh chỉ siết; loại phê duyệt cho phiên bản công cụ; chạy mô phỏng trên bản Nháp; khóa duyệt
      của hai phê duyệt mới; 412 cho `stale_version`; Q2 của `domain-packs`; nhánh chỉ siết khi Đóng băng;
      lượt của tài khoản dịch vụ bị tạm khóa; người duyệt thay (W2); lý do chặn `recipient_cap`; tên cột hạn
      mức; trần nội dung tin nhắn.
    - Về lại roadmap (4 dòng MEDIUM): cột Phụ thuộc lệch các cạnh ticket; YC101 thiếu ở hai hàng, YC102 ở hàng
      `workflow-triggers`; chữ "simulate" và "gửi phát hành" ở hàng `workflow-builder-ui`; 17 trong 25 spec quá
      250 dòng (10 spec vẫn quá khi bỏ Hiện trạng và Quyết định), `foundations-hardening` có 11 nhóm yêu cầu.
    - Đi trước được: `app-standards` (một dòng HIGH, cạnh 01 → 02) và `foundations-hardening` (hai dòng HIGH,
      cạnh với tenant-config/04 và với chín ticket sửa `offboarding.py`), không dòng CRITICAL nào chạm. Thêm
      các cạnh đó rồi chạy `checking-plan-readiness` cho từng ticket.
- Đợt 2 (W2: v1 GA): phần W2 của mọi spec ở trên, cùng `domain-packs` và `mcp-client` (chỉ có phạm vi W2: 66
  tiêu chí chưa ticket trong số đo ở trên). Cắt ticket khi đợt 1 hết dòng CRITICAL và lần kiểm nhất quán sau
  đó không còn dòng HIGH nào chưa có quyết định.
- Đợt 3 (W3: v1.5, v2): mỗi mục thành spec riêng khi tới lượt; ghi ở mục Ngoài phạm vi của từng spec.

## Slice log

No slice built yet. Each resolved ticket adds one line here: the commit hash and one sentence.
