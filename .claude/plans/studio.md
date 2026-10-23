# Studio: tenant-built objects, workflows, agents and tools

Studio is the no-code capability through which a customer (tenant) builds the
data model, the workflows, the agents and the tool connections for its own
departments, starting with Marketing. It is platform code in this repository
(ADR-0100), not a business context and not a product repository. Nothing here
is built yet, and nothing is reviewed by Đạt: every ADR in the block 0100-0199
is Proposed.

## State (2026-10-23): planning written, not yet reviewed

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
- **Written:** `studio/requirements.md` (100 YC, 14 KQ); 26 ADRs in
  `docs/adr/0100`-`0125`; 25 feature specs with 91 first-wave tickets;
  `studio/discovery/` (brainstorm, research index, the chang.fpt.net teardown
  and config analysis, the wayfinder map with 29 tickets); the platform
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
  push URL disabled.

## Decisions owed

- **Đạt:** review the ADR set, starting with the ones that reverse a recorded
  decision: 0104 (tenant roles as data, amends ADR-0012 and the premise of
  migration 648e2f7c3edb) and 0121 (the usage ledger returns, reversing the
  2026-09-21 removal). The full list of owed decisions, with owners and
  urgency, is in `requirements.md` (Câu hỏi còn mở) and in each spec.
- **Requester, to confirm provisional calls:** the 20 calls taken as option (a)
  on 2026-10-23 (listed in `requirements.md`, Quyết định); the W1 budget of
  about 4 months and 9 months for v1; the verdicts on nine brainstorm ideas; D11
  extended to role changes in W1 (a one-admin tenant cannot change roles until a
  second owner exists).
- **Counsel:** whether Studio needs the PDPL processing-service certificate
  (Decree 356/2025/ND-CP, Art. 21-27) before any pilot on real personal data.

## Lộ trình

| Tính năng (thư mục)     | Ý định                                                                                                                                                             | Yêu cầu cấp area                                                                                     | Trong; để cho  | Phụ thuộc                                                                                                                                                                                                                                                                                                                                 |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `studio-skeleton`       | Cho Studio một chỗ ở trong repo (một distribution, schema `studio`, seam API/web, luật compose) mà mọi spec khác xây lên, không seam rỗng                          | YC1, YC2, YC3, YC6, YC69                                                                             | trong (W1, W2) | không                                                                                                                                                                                                                                                                                                                                     |
| `foundations-hardening` | Sửa các lỗi đã đo trong nền tảng hiện có mà Studio sẽ đứng lên, mỗi lỗi có test âm đã thấy đỏ                                                                      | YC4, YC5, YC41, YC63                                                                                 | trong (W1, W2) | không                                                                                                                                                                                                                                                                                                                                     |
| `app-standards`         | Mọi route mới của Studio và nền tảng nói cùng một quy ước HTTP: một vỏ lỗi, khóa chống lặp gắn người gọi, ETag, keyset có kiểu                                     | YC1, YC3, YC5, YC27                                                                                  | trong (W1, W2) | `foundations-hardening`                                                                                                                                                                                                                                                                                                                   |
| `org-and-principals`    | Cho tenant một mô hình chủ thể đủ cho D1: thành viên cấp tenant, tài khoản dịch vụ làm run-as, rồi cây workspace, nhóm, quản lý và SSO ở v1                        | YC7, YC8, YC9, YC10, YC11                                                                            | trong (W1, W2) | `foundations-hardening`, `tenant-rbac`                                                                                                                                                                                                                                                                                                    |
| `tenant-rbac`           | Vai là dữ liệu của tenant, mỗi quyền có độ sâu, một hàm quyền hiệu lực trong PostgreSQL, chống leo thang                                                           | YC12, YC13, YC14, YC15, YC16, YC22, YC82                                                             | trong (W1, W2) | `custom-objects`, `org-and-principals`                                                                                                                                                                                                                                                                                                    |
| `record-access`         | Ai thấy bản ghi nào được quyết định trong PostgreSQL bằng RLS trên một sổ tầm truy cập, không ở ứng dụng                                                           | YC3, YC6, YC12, YC14, YC17, YC18, YC19, YC20, YC21, YC50, YC57, YC82                                 | trong (W1, W2) | `custom-objects`, `foundations-hardening`, `org-and-principals`, `tenant-rbac`                                                                                                                                                                                                                                                            |
| `field-security`        | Một hàm quyết định trường nào người gọi thấy hay sửa, áp ở mọi đường ra kể cả agent, workflow, phê duyệt và lịch sử run                                            | YC20, YC22, YC23, YC24, YC51, YC87                                                                   | trong (W1, W2) | `compliance-pdpl`, `custom-objects`, `telemetry-and-audit`, `tenant-rbac`, `tools-and-skills`, `workflow-nodes`                                                                                                                                                                                                                           |
| `custom-objects`        | Tenant định nghĩa object và field làm metadata trên bảng cố định; mọi đọc ghi bản ghi đi qua một RecordService                                                     | YC3, YC6, YC17, YC20, YC23, YC24, YC25, YC26, YC27, YC28, YC29, YC84, YC95                           | trong (W1, W2) | `app-standards`, `compliance-pdpl`, `field-security`, `org-and-principals`, `record-access`, `studio-skeleton`, `tenant-config`                                                                                                                                                                                                           |
| `tenant-config`         | Một vỏ phiên bản chung cho mọi thứ tenant dựng, chế độ chạy do server đặt, và mỗi lượt chạy ghim đúng thứ nó dùng                                                  | YC30, YC31, YC32, YC33, YC34, YC35, YC36, YC37, YC75                                                 | trong (W1, W2) | `connections-and-vault`, `foundations-hardening`, `studio-skeleton`                                                                                                                                                                                                                                                                       |
| `domain-packs`          | Gói nền tảng (Marketing trước) cài vào tenant chỉ qua API công khai thành bản sao có nguồn gốc; cập nhật là đề xuất vào bản nháp                                   | YC38                                                                                                 | trong (W2)     | `agent-builder`, `custom-objects`, `tenant-config`, `tenant-rbac`, `workflow-engine`                                                                                                                                                                                                                                                      |
| `workflow-engine`       | Quy trình là tài liệu `dw.workflow/v1` biên dịch mỗi phiên bản thành StateGraph, chạy ở worker từ hàng đợi Postgres, chờ người bền vững                            | YC32, YC33, YC34, YC39, YC41, YC45, YC81, YC94, YC100                                                | trong (W1, W2) | `agent-lifecycle`, `foundations-hardening`, `tenant-config`, `usage-and-limits`, `workflow-nodes`                                                                                                                                                                                                                                         |
| `workflow-triggers`     | Trigger chỉ xin run, không tự chạy; Data Hub nhận dữ liệu ngoài qua endpoint có chữ ký, chống trùng và lưu giữ có hạn                                              | YC8, YC42, YC43, YC44, YC46, YC72, YC84, YC88, YC97, YC98                                            | trong (W1, W2) | `connections-and-vault`, `org-and-principals`, `tenant-config`, `workflow-engine`                                                                                                                                                                                                                                                         |
| `workflow-nodes`        | Các loại bước là mã nền tảng trong một sổ đăng ký; CEL là ngôn ngữ biểu thức duy nhất; bước con người là cổng do server thực thi                                   | YC19, YC40, YC41, YC45, YC47, YC48, YC49, YC50, YC51, YC52, YC53, YC57, YC69, YC87, YC94, YC95, YC98 | trong (W1, W2) | `compliance-pdpl`, `custom-objects`, `field-security`, `model-connections`, `record-access`, `studio-skeleton`, `tools-and-skills`, `workflow-engine`                                                                                                                                                                                     |
| `workflow-builder-ui`   | Người dựng không viết mã vẽ quy trình trên canvas, cấu hình bước bằng biểu mẫu, chạy thử `simulate` và gửi phát hành                                               | YC33, YC39, YC40, YC75                                                                               | trong (W1, W2) | `agent-lifecycle`, `studio-skeleton`, `telemetry-and-audit`, `workflow-engine`, `workflow-nodes`, `workflow-triggers`                                                                                                                                                                                                                     |
| `connections-and-vault` | Bí mật của tenant mã hóa phong bì dưới khóa tenant trong OpenBao; mọi lời gọi ra ngoài đi qua một egress client; trình kết nối là manifest biên dịch thành công cụ | YC24, YC34, YC42, YC48, YC61, YC62, YC63, YC64, YC65, YC97                                           | trong (W1, W2) | `foundations-hardening`, `studio-skeleton`, `tenant-config`, `tenant-rbac`, `tools-and-skills`                                                                                                                                                                                                                                            |
| `tools-and-skills`      | Mọi công cụ đi qua một ToolExecutor tự kiểm JSON Schema và chính sách; công cụ theo loại, kỹ năng theo Agent Skills                                                | YC19, YC23, YC46, YC48, YC59, YC60, YC64, YC66, YC67, YC69, YC86, YC96                               | trong (W1, W2) | `custom-objects`, `field-security`, `foundations-hardening`, `model-connections`, `tenant-config`                                                                                                                                                                                                                                         |
| `mcp-client`            | Nền tảng là client MCP qua SDK chính thức trong một dịch vụ cô lập, định nghĩa công cụ ghim băm và duyệt hai người                                                 | YC68                                                                                                 | trong (W2)     | `agent-lifecycle`, `connections-and-vault`, `tools-and-skills`, `usage-and-limits`                                                                                                                                                                                                                                                        |
| `agent-builder`         | Agent là tài liệu `dw.agent/v1` trong vỏ chung, biên dịch theo (tenant, phiên bản) trong runner hiện có, chạy ở worker                                             | YC19, YC48, YC54, YC55, YC56, YC57, YC78, YC93, YC96                                                 | trong (W1, W2) | `compliance-pdpl`, `model-connections`, `record-access`, `studio-skeleton`, `tenant-config`, `tools-and-skills`, `workflow-engine`                                                                                                                                                                                                        |
| `model-connections`     | Một ModelResolver theo tenant trả lời mọi cửa model; tenant kết nối model của mình qua một lane LiteLLM không trạng thái                                           | YC32, YC58, YC79, YC85, YC91                                                                         | trong (W1, W2) | `compliance-pdpl`, `connections-and-vault`, `usage-and-limits`                                                                                                                                                                                                                                                                            |
| `code-sandbox`          | Mã của tenant chạy trong container riêng mới mỗi lần (không mạng, giới hạn CPU, bộ nhớ, pid, đĩa, thời gian)                                                       | YC69                                                                                                 | trong (W1, W2) | `studio-skeleton`, `usage-and-limits`                                                                                                                                                                                                                                                                                                     |
| `agent-lifecycle`       | Phiên bản đi qua một máy trạng thái do database canh; chỉ live khi cổng qua trên đúng hash và người khác tác giả duyệt; đóng băng và tắt kiểm ở mọi cửa            | YC10, YC30, YC60, YC70, YC71, YC72, YC73, YC74, YC75, YC82, YC93                                     | trong (W1, W2) | `agent-builder`, `compliance-pdpl`, `studio-skeleton`, `tenant-config`, `workflow-engine`                                                                                                                                                                                                                                                 |
| `usage-and-limits`      | Sổ sử dụng theo lượt gọi (D6) là nguồn cho hạn mức, màn sử dụng và đối soát; hạn mức giữ trước bằng lease Postgres khi nhận run                                    | YC44, YC76, YC77, YC78, YC79                                                                         | trong (W1, W2) | `agent-builder`, `org-and-principals`, `studio-skeleton`, `tenant-rbac`, `workflow-engine`                                                                                                                                                                                                                                                |
| `telemetry-and-audit`   | Span theo OTel GenAI không nội dung; lịch sử chạy cho tenant từ Postgres dưới RLS; audit tra cứu được                                                              | YC23, YC80, YC81, YC82, YC83, YC88                                                                   | trong (W1, W2) | `field-security`, `usage-and-limits`, `workflow-engine`                                                                                                                                                                                                                                                                                   |
| `compliance-pdpl`       | Dữ liệu cá nhân được phân loại một chủ, tuyến model theo vùng, gửi tin marketing qua một sàn có đồng ý, phiên bản có phân tích bộ ba nguy hiểm khi xuất bản        | YC22, YC24, YC49, YC67, YC71, YC82, YC84, YC85, YC86, YC88, YC89, YC90, YC91, YC92, YC93             | trong (W1, W2) | `agent-builder`, `agent-lifecycle`, `custom-objects`, `model-connections`, `tools-and-skills`, `workflow-engine`                                                                                                                                                                                                                          |
| `marketing-pilot`       | Chứng minh Studio đầu-cuối chỉ qua bề mặt tenant: lead từ form website tới email đầu tiên đã duyệt, không có mã marketing trong nền tảng                           | YC2, YC3, YC4, YC29, YC47, YC74, YC87, YC89, YC92, YC94, YC95, YC96, YC97, YC98, YC99, YC100         | trong (W1, W2) | `agent-builder`, `agent-lifecycle`, `compliance-pdpl`, `connections-and-vault`, `custom-objects`, `field-security`, `org-and-principals`, `record-access`, `telemetry-and-audit`, `tenant-config`, `tenant-rbac`, `tools-and-skills`, `usage-and-limits`, `workflow-builder-ui`, `workflow-engine`, `workflow-nodes`, `workflow-triggers` |

## ADR

Khối số dành riêng: 0100-0199.

| Số   | Tên                                                                                                                                         | Tệp                                                                            |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| 0100 | Studio is platform code in this repository                                                                                                  | `docs/adr/0100-studio-is-platform-code-in-this-repository.md`                  |
| 0101 | The Studio builder canvas uses @xyflow/react laid out by @dagrejs/dagre on one path                                                         | `docs/adr/0101-studio-canvas-is-an-allowlisted-ui-exception.md`                |
| 0102 | A workspace is a nested                                                                                                                     | `docs/adr/0102-workspace-is-a-nested-data-owning-unit.md`                      |
| 0103 | Only people and service principals act                                                                                                      | `docs/adr/0103-runs-act-as-a-principal-within-a-boundary.md`                   |
| 0104 | Roles are tenant data built from a migration-owned permission catalogue                                                                     | `docs/adr/0104-tenant-roles-with-depth-and-one-effective-grants-owner.md`      |
| 0105 | PostgreSQL decides which records a principal reaches                                                                                        | `docs/adr/0105-record-reach-is-decided-by-postgresql.md`                       |
| 0106 | Every field carries a personal-data category                                                                                                | `docs/adr/0106-field-access-follows-personal-data-category.md`                 |
| 0107 | Tenant objects are metadata over fixed migration-created tables                                                                             | `docs/adr/0107-custom-objects-over-fixed-tables-one-record-service.md`         |
| 0108 | Every platform route speaks one problem+json envelope and one set of list and mutation conventions                                          | `docs/adr/0108-one-error-envelope-and-caller-bound-idempotency.md`             |
| 0109 | Studio definitions are versioned documents in one shared envelope                                                                           | `docs/adr/0109-versioned-documents-one-envelope-and-run-manifest.md`           |
| 0110 | A tenant's configuration                                                                                                                    | `docs/adr/0110-tenant-configuration-is-maker-checker-and-bindings.md`          |
| 0111 | Environments in v1 are versions and a server-fixed run mode (live                                                                           | `docs/adr/0111-run-modes-are-the-v1-environments.md`                           |
| 0112 | A workflow is a dw.workflow/v1 document validated in one pass and compiled per published version to a LangGraph StateGraph                  | `docs/adr/0112-workflows-compile-to-langgraph-one-effect-per-node.md`          |
| 0113 | Every Studio run is requested through one door and executed by the worker from a Postgres queue that is the run row itself                  | `docs/adr/0113-every-run-is-requested-and-queued-in-postgres.md`               |
| 0114 | CEL is the one expression language for tenant text                                                                                          | `docs/adr/0114-cel-is-the-one-expression-language.md`                          |
| 0115 | Tenant credentials are envelope-encrypted under a per-tenant key                                                                            | `docs/adr/0115-tenant-credentials-vault-and-one-egress-client.md`              |
| 0116 | A tool is tenant data of a registered kind that reaches the model only as a pinned version                                                  | `docs/adr/0116-tools-are-tenant-data-through-one-executor.md`                  |
| 0117 | An agent is a form-configured dw.agent/v1 document compiled per version inside the existing runner                                          | `docs/adr/0117-agents-are-form-configured-documents.md`                        |
| 0118 | Every model door asks one tenant-aware ModelResolver                                                                                        | `docs/adr/0118-one-model-resolver-and-tenant-models-via-litellm.md`            |
| 0119 | Every execution of tenant code runs in its own fresh gVisor container launched by a first-party sandbox-runner                              | `docs/adr/0119-each-code-execution-gets-a-fresh-gvisor-container.md`           |
| 0120 | A version goes live only through a database-guarded stage machine                                                                           | `docs/adr/0120-publish-gate-and-run-control-switches.md`                       |
| 0121 | A per-call usage ledger returns as metering with named readers                                                                              | `docs/adr/0121-usage-ledger-returns-and-limits-are-postgres-leases.md`         |
| 0122 | Tenants read run history                                                                                                                    | `docs/adr/0122-tenants-read-run-history-from-postgres.md`                      |
| 0123 | The data plane stays in Vietnam                                                                                                             | `docs/adr/0123-data-stays-in-vietnam-and-model-calls-pass-a-residency-gate.md` |
| 0124 | A marketing message reaches a person only through a platform send floor checked in the ToolExecutor against a platform-owned consent ledger | `docs/adr/0124-marketing-messages-pass-a-platform-send-floor.md`               |
| 0125 | Every agent and workflow version is analysed at publish                                                                                     | `docs/adr/0125-untrusted-private-external-paths-need-a-person.md`              |

## Tiếp theo

- `requirements.md`: Đạt duyệt yêu cầu cấp area và các quyết định tạm của agent (23/10/2026).
- ADR 0100-0125: Đạt xem bộ ADR, nhất là các ADR đảo quyết định cũ (0104 sửa ADR-0012, 0121 đưa lại sổ sử dụng) (23/10/2026).
- `docs/platform/CONTEXT.md`: chạy reader test của `checking-plan-readiness` trên thuật ngữ dễ nhầm (23/10/2026).
- [`studio-skeleton`](studio/studio-skeleton/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`foundations-hardening`](studio/foundations-hardening/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`app-standards`](studio/app-standards/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`org-and-principals`](studio/org-and-principals/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`tenant-rbac`](studio/tenant-rbac/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`record-access`](studio/record-access/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`field-security`](studio/field-security/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`custom-objects`](studio/custom-objects/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`tenant-config`](studio/tenant-config/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`domain-packs`](studio/domain-packs/spec.md): chỉ có phạm vi W2; cắt ticket khi đợt 2 bắt đầu (23/10/2026).
- [`workflow-engine`](studio/workflow-engine/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`workflow-triggers`](studio/workflow-triggers/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`workflow-nodes`](studio/workflow-nodes/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`workflow-builder-ui`](studio/workflow-builder-ui/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`connections-and-vault`](studio/connections-and-vault/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`tools-and-skills`](studio/tools-and-skills/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`mcp-client`](studio/mcp-client/spec.md): chỉ có phạm vi W2; cắt ticket khi đợt 2 bắt đầu (23/10/2026).
- [`agent-builder`](studio/agent-builder/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`model-connections`](studio/model-connections/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`code-sandbox`](studio/code-sandbox/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`agent-lifecycle`](studio/agent-lifecycle/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`usage-and-limits`](studio/usage-and-limits/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`telemetry-and-audit`](studio/telemetry-and-audit/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`compliance-pdpl`](studio/compliance-pdpl/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).
- [`marketing-pilot`](studio/marketing-pilot/spec.md): Đạt duyệt spec, rồi `checking-plan-readiness` cho từng ticket W1 (23/10/2026).

## Đợt

Kiểm nhất quán 23/10/2026: 15 CRITICAL, 50 HIGH, 65 MEDIUM, 9 LOW; phủ YC 100/100, tiêu chí 825/890.

- Đợt 1 (W1: P0 nền móng và lát Marketing P1): 23 spec, 91 ticket, chưa ticket nào `ready-for-agent`.
    - Đi trước được: `foundations-hardening` và `app-standards`, không dòng CRITICAL nào chạm. Sửa các dòng
      HIGH của hai spec này, rồi chạy `checking-plan-readiness` cho chúng.
    - Chờ Đạt chấp nhận ADR và sửa `CLAUDE.md` trước (9 dòng CRITICAL). DO-01, bảng định nghĩa toàn tenant
      (ADR-0100, ADR-0107): `tenant-config`, `custom-objects`, `tenant-rbac`, `studio-skeleton`, và qua
      `studio.artifacts` gần như mọi spec còn lại. ADR-0104 sửa ADR-0012: `tenant-rbac`. ADR-0105 và DO-13:
      `record-access`. ADR-0109 và ADR-0120 (hai ghim): `tenant-config`, `agent-lifecycle`. ADR-0121:
      `usage-and-limits`. ADR-0101 và DO-42: `workflow-builder-ui`.
    - Chờ chọn thêm `workspace_id` hay đưa vào ngoại lệ của DO-01 (4 dòng CRITICAL): bảng lượt chạy và sự kiện
      vào (`workflow-engine`, `workflow-triggers`), tin nhắn hội thoại (`agent-builder`), sổ đồng ý
      (`compliance-pdpl`), bảng vai trò và thành viên (`tenant-rbac`, `org-and-principals`, `record-access`).
    - Sửa thẳng trong spec (2 dòng CRITICAL): actor của lane ở `agent-lifecycle/05`, tên ràng buộc ở
      `org-and-principals` R1.1.
- Đợt 2 (W2: v1 GA): phần W2 của mọi spec ở trên, cùng `domain-packs` và `mcp-client` (chỉ có phạm vi W2: 65
  tiêu chí chưa ticket trong số đo ở trên). Cắt ticket khi đợt 1 hết dòng CRITICAL và lần kiểm nhất quán sau
  đó không còn dòng HIGH nào chưa có quyết định.
- Đợt 3 (W3: v1.5, v2): mỗi mục thành spec riêng khi tới lượt; ghi ở mục Ngoài phạm vi của từng spec.

## Slice log

No slice built yet. Each resolved ticket adds one line here: the commit hash and one sentence.
