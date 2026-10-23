# 01 — Tài liệu dw.workflow/v1, loại workflow, bộ kiểm khi phát hành và WorkflowIR

Status: needs-info (DO-05, DO-06)
Blocked by: .claude/plans/studio/tenant-config/issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md, .claude/plans/studio/workflow-nodes/issues/02-so-dang-ky-buoc-va-mau-chuoi.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.8, R2.9, R2.10, R2.11, R2.12, R2.13, WE14

## Mục tiêu

Cho loại thành phần `workflow` một mô hình tài liệu kiểu hóa và một bộ kiểm trả mọi lỗi trên cùng `WorkflowIR` mà trình biên dịch dùng, để một quy trình sai đồ thị, sai biểu thức hay cắm thẳng id kết nối không niêm phong được (R1, R2 của spec).

## Việc cần làm

1. Trong `packages/python/dw_studio/src/dw_studio/workflows/`: model Pydantic đóng băng của `dw.workflow/v1` (`document.py`) với `triggers[]`, `nodes[]` (mỗi node `id`, `type` dạng `^[a-z_]+@[1-9][0-9]*$`, `config`, `retry`, `timeout_ms`, `on_error` trong `fail`, `continue`), `edges[]` (cạnh mang cổng ra `hot`, `default`, `error`), `variables[]`, `limits` (`max_steps`, `max_nesting`), và JSON Schema xuất ra. Từ chối số thực và chuỗi không NFC tại model (R1.2); dạng chuẩn do `dw_kernel.canonical` của tenant-config/01 băm.
2. `WorkflowIR` (`ir.py`) và module đồ thị (`graph.py`): `reachable(entry)`, `dominators()`, `paths_to(node)`, tập nhánh loại trừ của router; trình biên dịch của ticket 03 dựng từ cùng `WorkflowIR` này (R2.12, WE14).
3. Bộ kiểm xuất bản (`validator.py`) trả mọi lỗi của bảng R2.1-R2.10 trong `errors[]`, mỗi lỗi một con trỏ JSON, không dừng ở lỗi đầu (R2.11); chế độ cảnh báo khi lưu nháp (R2.13). Mã lỗi `wf.*` song ngữ vi/en.
4. Bộ trích phụ thuộc thuần (`dependencies.py`) ghi `node_type`, `artifact`, `binding` vào `studio.dependencies` của tenant-config (R1.3); `wf.inline_binding` khi gặp UUID kết nối hay principal ở chỗ phải là tên điểm gắn (R2.9).
5. Đăng ký `workflow` vào `ArtifactKindRegistry` tại seam composition root của tenant-config, gắn bộ kiểm và bộ trích; bước niêm phong của tenant-config/02 gọi bộ kiểm này (R1.4).
6. `NodeTypeRegistry` của workflow-nodes cấp schema config, output và chính sách lỗi của từng `type@major`; ticket này dùng ba loại node giả cho fixture cho tới khi loại thật tới.
7. Fixture: tài liệu mẫu của quy trình Tiếp nhận lead làm fixture biên dịch và chạy ở ticket 03.

## Tiêu chí chấp nhận

- [ ] R1.1: tài liệu thiếu `type@major`, `retry`, `timeout` hay `on_error` của một node → 422 có con trỏ tới node.
- [ ] R1.2: tài liệu có `{"score": 1.0}` → từ chối tại model với `float_forbidden`; chuỗi NFD → `not_nfc`; không mã băm nào.
- [ ] R1.3: niêm phong một nháp → `studio.dependencies` có dòng `node_type`, `artifact`, `binding` đúng của tài liệu; làm hỏng bộ trích của loại fixture → test fixture đỏ.
- [ ] R1.4: tập `kind` của `ArtifactKindRegistry` (kiểm bằng CHECK của tenant-config) có `workflow`; niêm phong `workflow` gọi bộ kiểm của ticket này.
- [ ] R2.1: node không tới được từ node vào → `wf.unreachable` có con trỏ tới node.
- [ ] R2.2: router không phủ một giá trị → `wf.router_not_total`.
- [ ] R2.3 (WE14): hai cạnh thường vào một node không qua điểm nối → `wf.join_required`; bỏ kiểm này → test "hai cạnh vào một node chạy hai lần" của ticket 03 đỏ.
- [ ] R2.4: chu trình không nằm trong vòng lặp có trần → `wf.unbounded_cycle`.
- [ ] R2.5: tham chiếu `{{ }}` tới biến không bị thống trị → `wf.reference_not_dominated`.
- [ ] R2.6: biểu thức CEL sai kiểu → `wf.cel_type_error`.
- [ ] R2.7: hai node ghi cùng một biến trong một superstep → `wf.variable_conflict`.
- [ ] R2.8: bước chờ trong thân map → `wf.wait_in_map`.
- [ ] R2.9: UUID của một kết nối ở chỗ phải là tên điểm gắn → `wf.inline_binding` có con trỏ.
- [ ] R2.10: tài liệu vượt trần gói về số node → `wf.plan_limit`.
- [ ] R2.11: tài liệu có sáu lỗi → bộ kiểm trả cả sáu trong một lần, mỗi lỗi một con trỏ.
- [ ] R2.12: bộ kiểm và trình biên dịch dựng từ cùng một `WorkflowIR`; cho chúng dùng hai mô hình đồ thị khác → fixture compile mọi ca kiểm đỏ.
- [ ] R2.13: lưu nháp có một node không tới được → lưu được, trả cảnh báo, không chặn.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:294`; spec: R1, R2, WE14.
- tenant-config:R2.6 (bước niêm phong gọi bộ kiểm), R3.1 (Nơi đang dùng), R1.2 (dạng chuẩn); ADR-0112 (Proposed) quyết 1, 3.

## Comments
