# 02 — Bản nháp và mô phỏng

Status: resolved (2026-11-02, main)
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

- [x] R6.1: lưu hai lần bởi hai owner: một dòng, nội dung lần hai, `author_ids` có cả hai, hash khớp `workflow_sha256` của tài liệu dựng lại.
- [x] R6.7 (WAI13): `PUT` cây có `send` ngoài lane `approved`: 422 `draft_not_publishable` có `wf.hitl_gate_missing`, 0 dòng bản nháp.
- [x] R6.2 (WAI9): mô phỏng bản nháp có `send`: `passed`, `tool_calls` có `email.send` với đề xuất đã duyệt, `ToolExecutor` và gateway 0 lần gọi; gỡ cổng giả thì test đỏ.
- [x] R6.9: bản nháp có `logic.switch` trên trường mẫu không khớp lane nào mà thiếu mặc định không qua R6.7; bước ném lỗi trong mô phỏng: `failed` với `failed_step`.
- [x] R6.12: mỗi lần lưu và mô phỏng: một dòng audit cùng giao dịch, đứng tên người gọi.
- [x] R6.13 (WAI15): tenant B: 404 trên ba route, 0 dòng đọc được dưới tenant B; `test_rls_coverage.py` liệt kê hai bảng.
- [x] R6.15: `PUT` lặp cùng khóa và cùng thân: một lần lưu; cùng khóa khác thân: 422 theo app-standards/02.
- [x] Xong: `make test-unit test-contract test-architecture` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/compile.py:1`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/catalog.py:70-106`; spec: R6.1, R6.2, R6.7, R6.9, R6.12, R6.13, R6.15, WAI9, WAI13, WAI15.

## Comments

- 2026-10-31 (agent): viết cùng spec.
- 2026-11-02 (agent): viết lại sau gate CHƯA ĐẠT: kiểm lại phía server, mô phỏng không gọi model, RLS, audit, `Idempotency-Key`.
- 2026-11-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-02 (agent): resolved (`d46e5c0` bộ mô phỏng, `12e74bd` bản nháp, route, migration).
    - Khác ticket (agent, theo ủy quyền 31/10/2026): FK tới `digital_workers` là RESTRICT, không CASCADE, như mọi cạnh tới bảng đó; offboarding xếp thứ tự xóa từ catalog (test coverage xanh). Nếu sai thì: đổi sang CASCADE trong một revision mới. `WfPorts` nhận Protocol hẹp (executor, gate, hand-off, tool models) để bộ mô phỏng thay vào không cần ép kiểu. Bộ mô phỏng kiểm đầu vào của công cụ theo `input_model` như executor làm trước tiên, nên bản nháp tham chiếu sai kiểu thì `failed` ngay khi mô phỏng. Hàm kiểm bản đề xuất (`checked_proposal`, `bases_of`) tách khỏi trợ lý, trợ lý và bản nháp dùng chung. `workflow_sha256` là sha256 của JSON chuẩn hóa, một cách băm cho gốc và bản nháp. `PUT` và `simulate` đã từ chối khi `submitted` (R6.8 của ticket 03, test ở ticket 03).
    - Tìm thấy và sửa: `scripts/mutate.py` không đột biến được tệp CRLF khi `old` nhiều dòng (đọc bytes thô), nên báo "không bắt" cho đột biến chưa từng xảy ra; nay đọc như phép kiểm lúc nạp và từ chối đột biến không đổi gì (failure-modes #3, lần 6).
    - Test: unit `test_wflite_simulate.py` 5 ca; integration `apps/api/tests/integration/test_wf_ai_drafts.py` 6 ca; `test_privileges.py` thêm một ca; `test_idempotency_declarations.py` thêm hai route.
    - Mutation `mutations/02.yaml`: 6/6 đỏ, đối chứng xanh (01 chạy lại 10/10).
    - `reviewing-feature-security`: tenant (hai bảng RLS bật và FORCE theo dạng workspace, tenant B nhận 404 trên ba route và đọc 0 dòng, đột biến policy thấy đỏ); phân quyền (chỉ chủ DW qua `require_owner`, Validator 403); tự chủ (mô phỏng không gọi `ToolExecutor` hay model, không thư nào trong `marketing_send_log`); nội dung không tin (server dựng lại tài liệu, không nhận tài liệu từ client); audit (`dw.workflow.draft_saved`, `dw.workflow.simulated` cùng giao dịch ghi); vòng đời (một bản nháp và một kết quả mô phỏng mỗi DW, ghi đè; offboarding xóa theo catalog; trần 200 bước).
    - Độ trễ (200 lời gọi ấm sau 20 lời gọi khởi động, uvicorn thật, PostgreSQL thật, DB `dw_ui04` với 6.000 việc): `PUT workflow-draft` P50/P95/P99 165,5/193,5/208,2 ms; `GET workflow-draft` 57,6/70,2/91,8 ms; `POST simulate` 217,9/250,6/478,6 ms. Route mới, không số của cha; trong ngân sách.
    - Cổng: ruff, format, mypy, `make test-unit`, `test-contract` (snapshot OpenAPI và kiểu TS sinh lại), `test-architecture`, `verify_invariants.py`; integration của `dw_platform`, `dw_agent_runtime`, `apps/api`: 768 passed, 3 skipped.
