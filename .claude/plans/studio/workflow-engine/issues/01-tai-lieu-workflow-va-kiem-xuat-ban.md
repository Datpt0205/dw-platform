# 01 — Tài liệu dw.workflow/v1, loại workflow, bộ kiểm khi gửi kiểm định và WorkflowIR

Status: needs-triage
Blocked by: .claude/plans/studio/tenant-config/issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md, .claude/plans/studio/workflow-nodes/issues/02-so-dang-ky-buoc-va-mau-chuoi.md, .claude/plans/studio/agent-lifecycle/issues/03-hop-dong-vong-doi-va-niem-phong.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.8, R2.9, R2.10, R2.11, R2.12, R2.13, R2.14, WE14

## Mục tiêu

Cho loại thành phần `workflow` một mô hình tài liệu kiểu hóa và một bộ kiểm trả mọi lỗi trên cùng `WorkflowIR` mà trình biên dịch dùng, để một quy trình sai đồ thị, sai biểu thức hay cắm thẳng id kết nối không niêm phong được (R1, R2 của spec).

## Việc cần làm

1. Trong `packages/python/dw_studio/src/dw_studio/workflows/`: model Pydantic đóng băng của `dw.workflow/v1` (`document.py`) với `triggers[]`, `nodes[]` (mỗi node `id`, `type` dạng `^[a-z_]+@[1-9][0-9]*$`, `config`, `retry`, `timeout_ms`, `on_error` trong `fail`, `continue`), `edges[]` (cạnh mang cổng ra `hot`, `default`, `error`), `variables[]`, `limits` (`max_steps`, `max_nesting`), và JSON Schema xuất ra. Từ chối số thực và chuỗi không NFC tại model (R1.2); dạng chuẩn do `dw_kernel.canonical` của tenant-config/01 băm.
2. `WorkflowIR` (`ir.py`) và module đồ thị (`graph.py`): `reachable(entry)`, `dominators()`, `paths_to(node)`, tập nhánh loại trừ của router; trình biên dịch của ticket 03 dựng từ cùng `WorkflowIR` này (R2.12, WE14).
3. Bộ kiểm khi gửi kiểm định (`validator.py`) trả mọi lỗi của bảng R2 (R2.1-R2.10, R2.14) trong `errors[]`, mỗi lỗi một con trỏ JSON, không dừng ở lỗi đầu (R2.11); chế độ cảnh báo khi lưu nháp (R2.13). Mã lỗi `wf.*` song ngữ vi/en là bảng mã duy nhất, gồm tám mã ổn định của ADR-0112 (Accepted) quyết 3 và ba mã mở rộng `wf.unbounded_cycle`, `wf.variable_conflict`, `wf.unknown_node_type`: workflow-nodes dẫn chiếu mã này, không đặt mã thứ hai. `wf.unknown_node_type` đọc tập `type@major` từ `NodeTypeRegistry` của workflow-nodes/02.
4. Bộ trích phụ thuộc thuần (`dependencies.py`) ghi `node_type`, `artifact` (kể cả Nguồn dữ liệu kind `endpoint` mà trình kích hoạt dùng) và `binding` vào `studio.dependencies` của tenant-config (R1.3); `wf.binding_undeclared` khi gặp UUID kết nối hay principal ở chỗ phải là tên điểm gắn (R2.9).
5. Đăng ký `workflow` vào `ArtifactKindRegistry` tại seam composition root của tenant-config, gắn bộ kiểm và bộ trích, với khóa đọc `studio.workflows.read`, khóa ghi `studio.workflows.edit` và khóa gửi `studio.versions.submit` (R1.5, tenant-config:R2.15); bước niêm phong của tenant-config/02 gọi bộ kiểm này (R1.4). Migration của ticket này INSERT dòng `workflow` vào `studio.artifact_kinds` với `has_quality_gate = true` (OPS-b, tenant-config:R2.14) và đăng ký `studio.workflows.read`, `studio.workflows.edit` vào danh mục quyền theo quy ước khóa của tenant-rbac/01; câu INSERT vào `platform.permissions` nêu mọi cột NOT NULL không DEFAULT lúc đó: `key`, `area`, `label_vi`, `scope_kind`, `risk`, `status`, `owner_package` (tenant-rbac/01) và `tenant_grantable` (tenant-rbac/02), giá trị theo luật phân loại ở bước 3 của tenant-rbac/01 và bước 1 của tenant-rbac/02, nên ticket này chờ tenant-rbac/02 (P2). `studio.versions.submit` do agent-lifecycle/03 đăng ký, nên ticket này chờ ticket đó và không đăng ký lại (P12).
6. `NodeTypeRegistry` của workflow-nodes cấp schema config, output và chính sách lỗi của từng `type@major`; ticket này dùng ba loại node giả cho fixture cho tới khi loại thật tới.
7. Fixture: tài liệu mẫu của quy trình Tiếp nhận lead làm fixture biên dịch và chạy ở ticket 03.

## Tiêu chí chấp nhận

- [ ] R1.1: tài liệu thiếu `type@major`, `retry`, `timeout` hay `on_error` của một node → 422 có con trỏ tới node.
- [ ] R1.2: tài liệu có `{"score": 1.0}` → từ chối tại model với `float_forbidden`; chuỗi NFD → `not_nfc`; không mã băm nào.
- [ ] R1.3: niêm phong một nháp có trình kích hoạt dùng một Nguồn dữ liệu → `studio.dependencies` có dòng `node_type`, `artifact` (kể cả Nguồn dữ liệu đó), `binding` đúng của tài liệu; làm hỏng bộ trích của loại fixture → test fixture đỏ.
- [ ] R1.4: `ArtifactKindRegistry` và các dòng `studio.artifact_kinds` cùng có `workflow` (test so hai tập của tenant-config/02); niêm phong `workflow` gọi bộ kiểm của ticket này.
- [ ] R1.5: mục `workflow` khai ba khóa đúng tên và dòng `studio.artifact_kinds` có `has_quality_gate = true`; test kiểm quyền tham số hóa của tenant-config/02 chạy cho `workflow`: thiếu `studio.workflows.read` → `GET` thành phần 404, có khóa đọc mà thiếu `studio.workflows.edit` → `PUT` nháp 403; gỡ khóa đọc khỏi mục → test registry đỏ.
- [ ] R2.1: node không tới được từ node vào → `wf.unreachable_node` có con trỏ tới node.
- [ ] R2.2: router không phủ một giá trị → `wf.router_not_total`.
- [ ] R2.3 (WE14): hai cạnh thường vào một node không qua điểm nối → `wf.join_required`; bỏ kiểm này → test "hai cạnh vào một node chạy hai lần" của ticket 03 đỏ.
- [ ] R2.4: chu trình không nằm trong vòng lặp có trần → `wf.unbounded_cycle`.
- [ ] R2.5: tham chiếu `{{ }}` tới biến không bị thống trị → `wf.ref_not_dominating`.
- [ ] R2.6: biểu thức CEL sai kiểu → `wf.type_mismatch`.
- [ ] R2.7: hai node ghi cùng một biến trong một superstep → `wf.variable_conflict`.
- [ ] R2.8: bước chờ trong thân map → `wf.wait_in_map`.
- [ ] R2.9: UUID của một kết nối ở chỗ phải là tên điểm gắn → `wf.binding_undeclared` có con trỏ.
- [ ] R2.10: tài liệu vượt trần gói về số node → `wf.limit_above_plan`.
- [ ] R2.11: tài liệu có sáu lỗi → bộ kiểm trả cả sáu trong một lần, mỗi lỗi một con trỏ.
- [ ] R2.12: bộ kiểm và trình biên dịch dựng từ cùng một `WorkflowIR`; cho chúng dùng hai mô hình đồ thị khác → fixture compile mọi ca kiểm đỏ.
- [ ] R2.13: lưu nháp có một node không tới được → lưu được, trả cảnh báo, không chặn.
- [ ] R2.14: niêm phong tài liệu có node `foo@1` chưa đăng ký → `wf.unknown_node_type` có con trỏ tới node, không niêm phong; lưu nháp cùng tài liệu chỉ cảnh báo.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:294`; spec: R1, R2, WE14.
- tenant-config:R2.6 (bước niêm phong gọi bộ kiểm), R3.1 (Nơi đang dùng), R1.2 (dạng chuẩn); ADR-0112 (Accepted) quyết 1, 3.

## Comments

- 2026-10-23 (agent): DO-05 và DO-06 đã có lời đáp (Đạt 23/10/2026), nên ticket về `needs-triage`. Theo phiếu cùng ngày: bảng mã `wf.*` duy nhất kể cả `wf.unknown_node_type` (A:workflow-engine:R2.2~workflow-nodes:R1.3), dòng `workflow` trong `studio.artifact_kinds` (OPS-b), khóa `studio.workflows.edit` đăng ký ở đây.
- 2026-10-24 (agent): theo quyết định của Đạt ngày 24/10/2026: loại `workflow` khai khóa đọc `studio.workflows.read` mà ticket này đăng ký, khóa ghi và khóa gửi (R1.5), và dòng `studio.artifact_kinds` nêu `has_quality_gate`.
- 2026-10-24 (agent): vòng sửa thứ tư: năm mã `wf.*` đổi theo ADR-0112 (Accepted) quyết 3 (phát hiện F về ADR-0112 (Accepted) và R2); ticket chờ agent-lifecycle/03, nơi đăng ký `studio.versions.submit` (P12, I:agent-lifecycle/03~workflow-engine/01), và tenant-rbac/02, vì câu INSERT khóa nêu `tenant_grantable` (P2); khóa dẫn quy ước của tenant-rbac/01 (P10).
