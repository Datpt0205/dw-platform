# 02 — Bản nháp và mô phỏng

Status: needs-triage
Blocked by: 01
Area: studio
Yêu cầu: R6.1, R6.2, WAI9

## Mục tiêu

Chủ DW lưu một đề xuất `publishable` của trợ lý thành bản nháp duy nhất của DW và chạy thử nó trên một việc mẫu mà không gì đi ra ngoài (R6.1, R6.2).

## Việc cần làm

1. Migration (`alembic revision -m "dw workflow drafts"`): bảng `platform.dw_workflow_drafts` (`tenant_id`, `workspace_id`, `dw_id` khóa chính cùng `tenant_id`, `content jsonb` not null, `content_sha256 text` 64 hex, `base_sha256 text` 64 hex, `author_id uuid` not null, `state text` CHECK in (`draft`, `submitted`), `reason text` null, `created_at`, `updated_at` timestamptz với trigger nhường giá trị nêu), FK tới `platform.digital_workers` ON DELETE CASCADE có index; `platform.dw_workflow_simulations` (`tenant_id`, `workspace_id`, `dw_id`, `content_sha256`, `outcome text` CHECK in (`passed`, `failed`), `trail jsonb`, `tool_calls jsonb`, `created_at`), khóa chính `(tenant_id, dw_id, content_sha256)`. RLS ENABLE và FORCE, policy tenant và workspace theo `CLAUDE.md` "Tenancy and authorization"; quyền `dw_app` trong migration và `test_privileges.py`; dọn khi offboarding theo sổ bước xóa của worker.
2. `PUT /api/v1/digital-workers/{dw_id}/workflow-draft` (thân là đề xuất của ticket 01: `steps`; server dựng lại tài liệu từ gốc và chạy lại kiểm của ticket 01, 422 `draft_not_publishable` khi còn lỗi), `GET` cùng đường, chỉ Business Owner hay Technical Owner; `Idempotency-Key` theo app-standards/02.
3. `POST /api/v1/digital-workers/{dw_id}/workflow-draft/simulate`: biên dịch bản nháp bằng bộ dựng của wf-lite với một `SimulatedToolPort` ghi đầu vào và trả một mẫu theo schema đầu ra của công cụ, không gọi `ToolExecutor`; `human.approval` duyệt nguyên đề xuất, `time.wait` bỏ qua; việc mẫu là `example` của schema của kind hoặc mẫu sinh từ schema; lưu kết quả theo `content_sha256`.
4. Test integration RLS (tenant B không đọc bản nháp hay mô phỏng), test mô phỏng với `email.send` khẳng định `ToolExecutor` giả 0 lần gọi; `mutations/02.yaml`.

## Tiêu chí chấp nhận

- [ ] R6.1: lưu hai lần một DW: một dòng, nội dung lần hai; tenant B: 404 và 0 dòng đọc được.
- [ ] R6.2 (WAI9): mô phỏng bản nháp có `send`: `outcome` `passed`, `tool_calls` có `email.send` với đầu vào đã duyệt, `ToolExecutor` 0 lần gọi; gỡ `SimulatedToolPort` thì test đỏ.
- [ ] Xong: `make test-unit test-contract test-architecture` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/compile.py:1`; spec: R6.1, R6.2, WAI9.

## Comments

- 2026-10-31 (agent): viết cùng spec.
