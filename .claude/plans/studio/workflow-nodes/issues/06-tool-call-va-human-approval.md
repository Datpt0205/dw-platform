# 06 — tool.call qua ToolExecutor và human.approval với quyền bắt buộc, khóa tham số

Status: needs-triage
Blocked by: 03, .claude/plans/studio/workflow-engine/issues/05-cho-nguoi-va-ghim-phien-ban.md, .claude/plans/studio/tools-and-skills/issues/02-toolset-va-cong-cu-ghim.md, .claude/plans/studio/compliance-pdpl/issues/04-san-gui-tin-marketing.md, .claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md
Area: studio
Yêu cầu: R8.1, R8.2, R8.3, R8.4, R9.1, R9.2, R9.3, R9.5, R9.6, R9.7, R9.8, WN6, WN7, WN8, WN9, WN17

## Mục tiêu

Bước `tool.call` đi qua `ToolExecutor` với khoá chống lặp; Bước phê duyệt là cổng do máy chủ thực thi,
với quyền bắt buộc, người duyệt khác người tạo lượt, tham số đã duyệt đúng là tham số được gửi
(workflow-nodes R8.1, R8.2, R8.3, R8.4, R9.1, R9.2, R9.3, R9.5, R9.6, R9.7, R9.8, WN6, WN7, WN8, WN9, WN17).
Hết hạn phê duyệt (R9.4, WN10) ở W2.

## Việc cần làm

1. `tool.call`: ghim phiên bản công cụ lúc gửi kiểm định; đối số qua đích `json` của bộ dựng mẫu; gọi
   `ToolExecutor.execute` với khoá `run_id:node_id:iteration`; nhận `subject` đã khoá sau phê duyệt.
   Thiếu quyền → `permission_denied` từ executor; sàn gửi tin ở đường messaging của executor
   (compliance-pdpl), không ở bước.
2. Bảng `studio.step_assignments` và `studio.step_approvals` (xem mục Dữ liệu của spec: `tenant_id`,
   `workspace_id`, `run_id`, `node_id`; `step_approvals` thêm `approval_request_id`, `subject_node_id`,
   `subject_hash`, CHECK `ck_step_approvals_subject_hash`; FK `ON DELETE CASCADE` có chỉ mục; RLS bật và
   FORCE; `updated_at` do trigger giữ nhường giá trị câu lệnh nêu). Migration sinh bằng
   `alembic revision -m "..."` nối tiếp baseline `0001`, id hex ngẫu nhiên.
3. `human.approval`: mở yêu cầu phê duyệt có `approval_type` dưới tiền tố nghiêm `studio.step.`, thêm vào
   `strict_approval_prefixes` bằng `|=` ở composition root của API và worker; workflow-engine/05 giữ dòng
   chờ và handler theo tiền tố; `required_scope` bắt buộc, thu hẹp theo người, nhóm hoặc Biểu thức; đóng
   dấu vào yêu cầu tên mọi Trường trang duyệt hiển thị (R9.7). Một mục
   `decision_guards['studio.step.approval']` qua guard async `ApprovalDecisionGuard` của tenant-config/05 trả
   403 cho người không được giao và người không đọc được một Trường đã đóng dấu (R9.8, luật của
   field-security:R4.5); người thiếu `required_scope` nhận 403 ở kiểm tem; người tạo lượt chạy giữ scope
   nhận 409 ở luật tiền tố nghiêm (bảng mã ở ADR-0004 (Accepted)). Mã băm chủ thể khoá ở `subject_node`.
4. Kiểm khi gửi kiểm định: chen bước sau phê duyệt làm đổi mã băm chủ thể → từ chối. Kiểm phát hành theo
   loại `workflow` (R9.5): ngoài người chạy của lượt không ai giữ `required_scope` → trả lỗi; đăng ký qua
   Protocol mà agent-lifecycle khai, ở composition root; không có khóa `studio.workflows.publish`.
5. Bộ trả phiên bản chủ thể cho mã quyết định Zalo (W2 nối thêm nhắc, chuyển cấp và hết hạn; W1 phê duyệt
   chờ không hạn, DO-31). Huỷ lượt chạy huỷ phê duyệt đang mở trong cùng giao dịch.

## Tiêu chí chấp nhận

- [ ] R8.1: `tool.call` gọi `ToolExecutor.execute` với khoá `run_id:node_id:iteration` và phiên bản
      công cụ đã ghim lúc gửi kiểm định.
- [ ] R8.2 (WN6): hai lần chạy song song cùng khoá → tác động ngoài xảy ra đúng một lần.
- [ ] R8.3 (WN7): người chạy thiếu quyền công cụ → `permission_denied` từ executor, không từ bước.
- [ ] R8.4 (WN7): `tool.call` `email.send` của `smtp@1.0.0` tới địa chỉ chưa đồng ý → `blocked:no_consent`;
      gọi thẳng công cụ (bỏ qua bước) cũng bị chặn; gỡ sàn gửi khỏi executor → test đỏ.
- [ ] R9.1: Bước phê duyệt mở `approval_type` dưới `studio.step.` với `required_scope` bắt buộc.
- [ ] R9.2 (WN8): người không được giao → 403 qua `decision_guards`; người thiếu `required_scope` → 403;
      gỡ guard → test đỏ.
- [ ] R9.6 (WN8): nhân viên Sales tạo lượt chạy và giữ `required_scope` tự duyệt → 409; bỏ `studio.step.`
      khỏi tiền tố nghiêm → test đỏ.
- [ ] R9.7: yêu cầu phê duyệt bước mang danh sách tên Trường mà trang duyệt hiển thị.
- [ ] R9.8 (WN17): người được giao không đọc được `phone` đã đóng dấu quyết → 403, yêu cầu vẫn `pending`;
      gỡ điều kiện đọc trường khỏi guard → test đỏ.
- [ ] R9.3 (WN9): chen một bước sau khi duyệt → gửi kiểm định từ chối; mã băm chủ thể khác lúc thực thi →
      `subject_changed`.
- [ ] R9.5 (WN8): chỉ người chạy giữ `required_scope` → kiểm theo loại đã đăng ký trả lỗi và phát hành bị
      từ chối; gỡ đăng ký kiểm → test đỏ.
- [ ] R9.2: huỷ lượt chạy huỷ phê duyệt đang mở trong cùng giao dịch.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/workflows/test_tool_call_node.py packages/python/dw_studio/tests/workflows/test_human_approval_node.py` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:217-235`; spec: R9.1
  (`approval_requests` thiếu cột giao, hạn, chuyển cấp).
- `apps/api/src/dw_api/bootstrap/runtime.py:237-239`; spec: R9.2 (`strict_approval_prefixes`,
  `decision_guards`).
- `apps/api/src/dw_api/bootstrap/wiring.py:314`; spec: R9.4 (mã Zalo chỉ cho loại có người trả lời).
- ADR-0112 (Accepted) quyết 7; spec: R9.

## Comments

- 2026-10-23 (agent): theo phiếu 23/10/2026: hết hạn phê duyệt sang W2 (DO-31); bảng mã từ chối người quyết ở ADR-0004 (Accepted) tách R9.2 (403) và R9.6 (409); người duyệt phải đọc được Trường đóng dấu qua guard async (DO-36), nên ticket chờ tenant-config/05; khóa phát hành chung, R9.5 là kiểm đăng ký qua Protocol; chờ compliance-pdpl/04 và test WN7 dùng `email.send` của `smtp@1.0.0` (DO-48.1).
