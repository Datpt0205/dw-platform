# 06 — tool.call qua ToolExecutor và human.approval với quyền bắt buộc, khóa tham số

Status: needs-triage
Blocked by: 03, .claude/plans/studio/workflow-engine/issues/05-cho-nguoi-va-ghim-phien-ban.md, .claude/plans/studio/tools-and-skills/issues/02-toolset-va-cong-cu-ghim.md
Area: studio
Yêu cầu: R8.1, R8.2, R8.3, R8.4, R9.1, R9.2, R9.3, R9.4, R9.5, WN6, WN7, WN8, WN9, WN10

## Mục tiêu

Bước `tool.call` đi qua `ToolExecutor` với khoá chống lặp; Bước phê duyệt là cổng do máy chủ thực thi,
với quyền bắt buộc, người duyệt khác người tạo lượt, tham số đã duyệt đúng là tham số được gửi
(workflow-nodes R8.1, R8.2, R8.3, R8.4, R9.1, R9.2, R9.3, R9.4, R9.5, WN6, WN7, WN8, WN9, WN10).

## Việc cần làm

1. `tool.call`: ghim phiên bản công cụ lúc phát hành; đối số qua đích `json` của bộ dựng mẫu; gọi
   `ToolExecutor.execute` với khoá `run_id:node_id:iteration`; nhận `subject` đã khoá sau phê duyệt.
   Thiếu quyền → `permission_denied` từ executor; sàn gửi tin ở đường messaging của executor
   (compliance-pdpl), không ở bước.
2. Bảng `studio.step_assignments` và `studio.step_approvals` (xem mục Dữ liệu của spec: `tenant_id`,
   `workspace_id`, `run_id`, `node_id`; `step_approvals` thêm `approval_request_id`, `subject_node_id`,
   `subject_hash`, CHECK `ck_step_approvals_subject_hash`; FK `ON DELETE CASCADE` có chỉ mục; RLS bật và
   FORCE; `updated_at` do trigger giữ nhường giá trị câu lệnh nêu). Migration sinh bằng
   `alembic revision -m "..."` nối tiếp baseline `0001`, id hex ngẫu nhiên.
3. `human.approval`: `approval_type` dưới tiền tố nghiêm `studio.step.`, thêm vào
   `strict_approval_prefixes` bằng `|=` ở composition root; `required_scope` bắt buộc, thu hẹp theo
   người, nhóm hoặc Biểu thức; một `decision_guards` entry từ chối người tạo lượt, người không được
   giao hoặc người không giữ scope. Mã băm chủ thể khoá ở `subject_node`.
4. Kiểm phát hành: chen bước sau phê duyệt làm đổi mã băm chủ thể → từ chối; ngoài người chạy của lượt
   không ai giữ `required_scope` → từ chối phát hành.
5. Bộ trả phiên bản chủ thể cho mã quyết định Zalo (W2 nối thêm nhắc, chuyển cấp); hết hạn → Nhánh ra
   `expired` hoặc `approval_expired`. Huỷ lượt chạy huỷ phê duyệt đang mở trong cùng giao dịch.

## Tiêu chí chấp nhận

- [ ] R8.1: `tool.call` gọi `ToolExecutor.execute` với khoá `run_id:node_id:iteration` và phiên bản
      công cụ đã ghim lúc phát hành.
- [ ] R8.2 (WN6): hai lần chạy song song cùng khoá → tác động ngoài xảy ra đúng một lần.
- [ ] R8.3 (WN7): người chạy thiếu quyền công cụ → `permission_denied` từ executor, không từ bước.
- [ ] R8.4 (WN7): `tool.call` ZNS tới số chưa đồng ý → `no_consent`; gọi thẳng công cụ (bỏ qua bước)
      cũng bị chặn; gỡ sàn gửi khỏi executor → test đỏ.
- [ ] R9.1: Bước phê duyệt mở `approval_type` dưới `studio.step.` với `required_scope` bắt buộc.
- [ ] R9.2 (WN8): nhân viên Sales (người tạo lượt) tự duyệt → 403; người không được giao → 403 qua
      `decision_guards`; gỡ guard → test đỏ.
- [ ] R9.3 (WN9): chen một bước sau khi duyệt → phát hành từ chối; mã băm chủ thể khác lúc thực thi →
      `subject_changed`.
- [ ] R9.4 (WN10): quá hạn → Nhánh ra `expired` hoặc `approval_expired`, không bao giờ `approved`.
- [ ] R9.5 (WN8): chỉ người chạy giữ `required_scope` → phát hành từ chối.
- [ ] R9.2: huỷ lượt chạy huỷ phê duyệt đang mở trong cùng giao dịch.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/workflows/test_tool_call_node.py packages/python/dw_studio/tests/workflows/test_human_approval_node.py` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:217-235`; spec: R9.1
  (`approval_requests` thiếu cột giao, hạn, chuyển cấp).
- `apps/api/src/dw_api/bootstrap/runtime.py:237-239`; spec: R9.2 (`strict_approval_prefixes`,
  `decision_guards`).
- `apps/api/src/dw_api/bootstrap/wiring.py:314`; spec: R9.4 (mã Zalo chỉ cho loại có người trả lời).
- ADR-0112 (Proposed) quyết 6; spec: R9.

## Comments
