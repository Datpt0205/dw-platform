# 01 — Hồ sơ Digital Worker, loại quyết định và mức tự chủ có hiệu lực

Status: needs-triage
Blocked by: .claude/plans/studio/foundations-hardening/issues/03-quyen-dw-app-va-rls-initplan.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.5, R1.6, R1.7, R1.8, R2.1, R2.2, R2.3, R2.4, DWK1, DWK3, DWK4, DWK5, DWK6, DWK7

## Mục tiêu

Business Owner và Technical Owner tạo và vận hành một DW là dữ liệu của công ty, đứng tên chính nó, với
loại quyết định có trần và mức đã kiếm, và một hàm duy nhất trả mức tự chủ có hiệu lực (R1, R2,
ADR-0128 (Proposed) quyết 1-4).

## Việc cần làm

1. Migration (`alembic revision -m "platform digital workers"`, id hex ngẫu nhiên): bảng
   `platform.digital_workers` và `platform.dw_decision_classes` đúng mục Dữ liệu của spec (cột, CHECK,
   FK có `ON DELETE`, index mỗi FK, trigger `updated_at` nhường giá trị câu lệnh nêu), RLS ENABLE và
   FORCE với policy workspace một hình của `CLAUDE.md`; quyền `dw_app` SELECT, INSERT, UPDATE; thêm
   `dw.read` vào mọi vai thành viên và `dw.read`, `dw.manage` vào `org_admin` trong `platform.roles`;
   grant được `dw_platform/tests/integration/test_privileges.py` khẳng định.
2. `dw_kernel/autonomy.py`: hàm `requires_person(effect_rung, level)` và bảng bậc, chuyển từ
   `dw_agent_runtime/autonomy.py` (một chủ); `AutonomyApprovalPolicy.requires_approval` gọi hàm đó,
   test cũ `test_autonomy_policy.py` giữ xanh không sửa.
3. `dw_platform/domain/digital_worker.py`: `DigitalWorker`, `DecisionClass`, bảng chuyển trạng thái
   `draft→operating`, `operating→paused`, `paused→operating`, `*→retired` trừ `retired`.
4. `dw_platform/application/digital_workers.py`: `DigitalWorkerService` (`create`, `get`, `list`,
   `change_state`), Protocol `DigitalWorkerRepositoryPort`, `ToolCatalogPort` (công cụ có tồn tại không,
   scope nó đòi), `MembershipCheckPort`; `DecisionAutonomy.effective_level(dw_id, key)` = mức thấp nhất
   của trần, mức đã kiếm và `platform.tenants.max_autonomy_level`, `A0` khi thiếu; `requires_person`
   theo R2.4 (`external` + `reversible` là bậc ngoài có khóa).
5. `dw_platform/adapters/persistence/digital_workers_repo.py`: repository SQL; audit `dw.created`,
   `dw.state_changed` trong cùng giao dịch.
6. Route `apps/api/src/dw_api/routes/v1/digital_workers.py`: `POST /v1/digital-workers`,
   `GET /v1/digital-workers`, `GET /v1/digital-workers/{id}`, `POST /v1/digital-workers/{id}/state`
   theo app-standards (problem+json, `Idempotency-Key`, keyset), mã lỗi đúng mục API của spec; nối ở
   `apps/api/src/dw_api/bootstrap/wiring.py`.
7. Test âm DWK1, DWK3-DWK7; tenant B không đọc được (DWK3) cả qua API lẫn đọc thẳng bảng không đặt ngữ cảnh.

## Tiêu chí chấp nhận

- [ ] R1.1: tạo DW hợp lệ trả 201, dòng `draft`, id do server sinh, tenant và workspace từ ngữ cảnh; thân có `tenant_id` khác bị bỏ qua.
- [ ] R1.2 (DWK1): Validator là user của tenant B → 422 `owner_not_member`, không dòng nào.
- [ ] R1.3: công cụ không có spec → 422 `tool_unknown`; `work_kinds` rỗng → 422 `work_kinds_empty`.
- [ ] R1.5 (DWK3): tenant B và workspace khác đọc id DW của A → 404; đọc thẳng bảng không ngữ cảnh → 0 dòng.
- [ ] R1.6 (DWK4): người giữ `dw.manage` không là chủ gọi `/state` → 403 `not_dw_owner`, trạng thái không đổi.
- [ ] R1.7 (DWK5): `retired→operating` → 409 `invalid_transition`.
- [ ] R1.8: đổi trạng thái ghi `dw.state_changed` đứng tên người đổi; giao dịch lỗi thì không dòng audit.
- [ ] R2.1: mỗi loại quyết định trong thân thành một dòng `platform.dw_decision_classes`.
- [ ] R2.2: `earned_level` A3 với trần A2 → 422 `above_ceiling`, không dòng DW nào.
- [ ] R2.3 (DWK6): trần tenant A1, đã kiếm A3, trần loại A4 → `A1`; loại không tồn tại → `A0`.
- [ ] R2.4 (DWK7): `critical` ở A4 đòi người; `external` không đảo được ở A3 đòi người; đảo được ở A3 không đòi; `test_autonomy_policy.py` xanh không sửa.
- [ ] Xong: `make test-unit test-contract test-architecture` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/autonomy.py:71-133`; `packages/python/dw_kernel/src/dw_kernel/autonomy.py:17`; `db/migrations/versions/0006_autonomy.py:51`; spec: R1, R2, DWK1, DWK3-DWK7; R1.4 và DWK2 ở ticket 02, nơi lane dựng ngữ cảnh lượt chạy.

## Comments
