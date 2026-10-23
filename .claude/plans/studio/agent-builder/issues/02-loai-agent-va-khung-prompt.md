# 02 — Loại `agent`, cài đặt agent, khung và bộ ráp prompt

Status: needs-info (DO-05)
Blocked by: 01, .claude/plans/studio/tenant-config/issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R2.1, R2.2, R2.3, AB1, AB2, AB10

## Mục tiêu

Cho người dựng tạo và sửa một tài liệu `dw.agent/v1` qua API công khai với cài đặt sử dụng tách khỏi phiên bản, và cho một khung prompt nền tảng ráp chỉ dẫn tenant như dữ liệu từ bên ngoài. Chứng minh R1 và R2 của spec và cài kiểm soát AB1, AB2, AB10.

## Việc cần làm

1. Khai `AgentDocument` (`extra="forbid"`, số thập phân dạng chuỗi) cho kind `agent`; đăng ký loại vào `ArtifactKindRegistry` của `tenant-config` với validator trả mọi lỗi `{path, code, message}` cùng lúc và một extractor phụ thuộc có fixture.
2. Migration `studio.agent_settings` (revision hex của alembic): cột `tenant_id`, `workspace_id`, `agent_id`, `audience jsonb`, `accountable_user_id`, `enabled boolean NOT NULL` (không `DEFAULT`), `row_version`, `created_at/updated_at timestamptz`; RLS bật và FORCE với policy theo `tenant_id` và hình workspace; FK khai `ON DELETE` và có chỉ mục; trigger `updated_at` nhường giá trị câu lệnh nêu; grant cho `dw_app`, `dw_agent_ro`.
3. Đăng ký khóa quyền `studio.agent.read`, `studio.agent.author`, `studio.agent.settings.manage` vào danh mục quyền của `tenant-rbac` với test phủ.
4. Route `/api/v1/studio/agents`: `POST` tạo (422 `{path, code, message}`, 422 `reason_code=audience_empty` khi `Người được dùng` rỗng), `GET` đọc theo `studio.agent.read`, `PATCH /{id}` sửa nháp với `row_version` (409 `reason_code=stale_row_version`), `PATCH /{id}/settings` audit `studio.agent.settings_changed`.
5. Prompt `studio.agent_frame@1.0.0` trong `configs/prompts/studio/`; hàm `assemble_system_prompt` cạnh `contain_untrusted` đặt chỉ dẫn và mọi giá trị chèn trong một khối dữ liệu ngoài cắt ở 16 KiB, với một tập biến hệ thống đóng và một linter có mã lỗi; không đi qua `str.format` trên văn bản tenant.

## Tiêu chí chấp nhận

- [ ] R1.1: `POST /api/v1/studio/agents` hợp lệ tạo tài liệu kind `agent` và một dòng `studio.agent_settings`, ghi audit `studio.agent.created`; sai nếu không có dòng settings hoặc không có audit.
- [ ] R1.2: `PATCH` nháp với `row_version` cũ trả 409 và không ghi; sai nếu ghi đè bản mới.
- [ ] R1.3: tài liệu có khóa ngoài lược đồ trả 422 kèm `{path, code, message}`; sai nếu nhận khóa lạ.
- [ ] R1.4 (AB10): INSERT `studio.agent_settings` thiếu `enabled` bị PostgreSQL từ chối; gỡ `NOT NULL` khỏi `enabled` → test đỏ.
- [ ] R1.5 (AB10): tạo agent với `Người được dùng` rỗng trả 422 `audience_empty` và không tạo; sai nếu tạo được.
- [ ] R2.1 (AB1): chỉ dẫn `{x.__class__.__mro__}` và JSON `{"a": 1}` tới model nguyên văn trong khối dữ liệu ngoài, cắt ở 16 KiB; gỡ bước bọc khối → test đỏ.
- [ ] R2.2 (AB2): chỉ dẫn chứa chuỗi đóng khối của khung trả 422; gỡ thoát ký tự → test đỏ.
- [ ] R2.3 (AB1): prompt tham chiếu một biến ngoài tập biến hệ thống đóng trả 422; sai nếu dựng được prompt.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests -k "agent_kind or agent_frame or agent_settings"` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/prompts.py:35`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/prompts.py:168`; `db/migrations/versions/855ae928c3fa_platform_in_app_notifications.py:46`; spec: R1.1, R1.2, R1.3, R1.4, R1.5, R2.1, R2.2, R2.3, AB1, AB2, AB10.

## Comments
