# 02 — Bản nháp và mô phỏng

Status: ready-for-agent
Blocked by: 01
Area: studio
Yêu cầu: R6.1, R6.2, R6.7, R6.9, R6.12, R6.13, R6.15, WAI9, WAI13, WAI15

## Mục tiêu

Chủ DW lưu một cây bước thành bản nháp duy nhất của DW, kiểm lại phía server, và chạy thử nó trên một việc mẫu mà không gì đi ra ngoài và không gọi model (R6.1, R6.2, R6.7, R6.9, R6.12, R6.13, R6.15).

## Việc cần làm

1. Migration (`alembic revision -m "dw workflow drafts"`): `platform.dw_workflow_drafts` (`tenant_id`, `workspace_id`, `dw_id`, khóa chính `(tenant_id, dw_id)`, `content jsonb` not null, `content_sha256 text` CHECK 64 hex, `base_sha256 text` CHECK 64 hex, `saved_by uuid` not null, `author_ids uuid[]` not null CHECK không rỗng, `state text` CHECK in (`draft`, `submitted`), `reason text` null CHECK in (`base_changed`, `content_changed`) hay null, `created_at`, `updated_at` timestamptz với trigger nhường giá trị nêu), FK tới `platform.digital_workers` ON DELETE CASCADE có index; `platform.dw_workflow_simulations` (`tenant_id`, `workspace_id`, `dw_id`, khóa chính `(tenant_id, dw_id)`, `content_sha256`, `outcome text` CHECK in (`passed`, `failed`), `trail jsonb`, `tool_calls jsonb`, `failed_step text` null, `error text` null, `created_at`), FK như trên. RLS ENABLE và FORCE, policy `tenant AND (workspace OR scope)` theo `CLAUDE.md` "Tenancy and authorization"; quyền `dw_app` trong migration và `test_privileges.py`; `test_rls_coverage.py` xanh.
2. Hash: `workflow_sha256(document)` = sha256 của `canonical_json` của tài liệu; catalog trả cùng hash cho bản gói (thêm trường, không thay sha256 tệp đang ghim lượt chạy).
3. `PUT /api/v1/digital-workers/{dw_id}/workflow-draft` (thân `{steps}`): `require_owner`; dựng tài liệu từ gốc DW đang ghim và chạy kiểm của ticket 01 (R6.1); lỗi thì 422 `draft_not_publishable` với `problems`, không ghi (R6.7); thêm người lưu vào `author_ids`, đặt `state` `draft`; `GET` cùng đường. Audit `dw.workflow.draft_saved` cùng giao dịch (R6.12); `Idempotency-Key` (R6.15).
4. `POST /api/v1/digital-workers/{dw_id}/workflow-draft/simulate`: biên dịch bản nháp bằng bộ dựng của wf-lite với `SimulatedToolPort` (ghi đầu vào, trả mẫu sinh từ schema đầu ra của công cụ) và `SimulatedModelPort` (trả mẫu sinh từ `output_schema` của bước, `confidence` 1); `human.approval` duyệt nguyên đề xuất; `time.wait` bỏ qua; việc mẫu là `examples[0]` của schema của kind hoặc mẫu sinh từ schema; trần 200 bước; thay dòng mô phỏng của DW (R6.2); bước lỗi hay vượt trần thì `failed` với bước và lỗi (R6.9). Audit `dw.workflow.simulated`; `Idempotency-Key`.
5. Test integration: tenant B gọi `PUT`, `GET`, `simulate` theo id DW của A: 404, 0 dòng (WAI15); `PUT` cây bỏ cổng của `send`: 422, 0 dòng (WAI13); mô phỏng có `send`: `ToolExecutor` giả và gateway giả 0 lần gọi (WAI9); `mutations/02.yaml`. Độ trễ theo `latency.md` (route mới, truy vấn mới).

## Tiêu chí chấp nhận

- [ ] R6.1: lưu hai lần bởi hai owner: một dòng, nội dung lần hai, `author_ids` có cả hai, hash khớp `workflow_sha256` của tài liệu dựng lại.
- [ ] R6.7 (WAI13): `PUT` cây có `send` ngoài lane `approved`: 422 `draft_not_publishable` có `wf.hitl_gate_missing`, 0 dòng bản nháp.
- [ ] R6.2 (WAI9): mô phỏng bản nháp có `send`: `passed`, `tool_calls` có `email.send` với đề xuất đã duyệt, `ToolExecutor` và gateway 0 lần gọi; gỡ cổng giả thì test đỏ.
- [ ] R6.9: bản nháp có `logic.switch` trên trường mẫu không khớp lane nào mà thiếu mặc định không qua R6.7; bước ném lỗi trong mô phỏng: `failed` với `failed_step`.
- [ ] R6.12: mỗi lần lưu và mô phỏng: một dòng audit cùng giao dịch, đứng tên người gọi.
- [ ] R6.13 (WAI15): tenant B: 404 trên ba route, 0 dòng đọc được dưới tenant B; `test_rls_coverage.py` liệt kê hai bảng.
- [ ] R6.15: `PUT` lặp cùng khóa và cùng thân: một lần lưu; cùng khóa khác thân: 422 theo app-standards/02.
- [ ] Xong: `make test-unit test-contract test-architecture` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/compile.py:1`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/catalog.py:70-106`; spec: R6.1, R6.2, R6.7, R6.9, R6.12, R6.13, R6.15, WAI9, WAI13, WAI15.

## Comments

- 2026-10-31 (agent): viết cùng spec.
- 2026-11-02 (agent): viết lại sau gate CHƯA ĐẠT: kiểm lại phía server, mô phỏng không gọi model, RLS, audit, `Idempotency-Key`.
- 2026-11-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
