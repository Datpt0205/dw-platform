# 01 — Hồ sơ Digital Worker, service principal tối thiểu, loại quyết định và mức tự chủ có hiệu lực

Status: ready-for-agent
Blocked by: .claude/plans/studio/foundations-hardening/issues/03-quyen-dw-app-va-rls-initplan.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.5, R1.6, R1.7, R1.8, R1.9, R1.10, R1.11, R1.13, R1.15, R1.16, R1.17, R2.1, R2.2, R2.3, R2.4, DWK1, DWK3, DWK4, DWK5, DWK6, DWK7, DWK23, DWK24, DWK25, DWK33, DWK36, R1.18, DWK41

## Mục tiêu

Business Owner và Technical Owner tạo và vận hành một DW là dữ liệu của công ty, có service principal
của riêng nó theo ADR-0103 (Accepted) quyết 2, với loại quyết định có trần và mức đã kiếm, và một hàm
duy nhất trả mức tự chủ có hiệu lực (R1, R2, ADR-0128 (Proposed) quyết 1-4).

## Việc cần làm

1. Migration (`alembic revision -m "platform digital workers"`, id hex ngẫu nhiên), đúng mục Dữ liệu
   của spec: `platform.users.kind` và `owner_tenant_id` với CHECK; `platform.service_principals`;
   `platform.digital_workers`; `platform.dw_decision_classes` (CHECK, FK có `ON DELETE`, index mỗi FK,
   trigger `updated_at` nhường giá trị câu lệnh nêu); RLS ENABLE và FORCE với policy workspace một
   hình của `CLAUDE.md`, `platform.service_principals` theo tenant và ghi vào danh sách bảng toàn tenant
   của `test_rls_coverage.py` kèm lý do; trigger trên `platform.external_identities` từ chối dòng cho
   user `kind = 'service'`; quyền `dw_app` SELECT, INSERT, UPDATE; thêm `dw.read` vào mọi vai thành
   viên và `dw.manage` vào `org_admin` trong `platform.roles`; grant được `test_privileges.py` khẳng định.
2. `dw_kernel/autonomy.py`: hàm `requires_person(effect_rung, level)` và bảng bậc, chuyển từ
   `dw_agent_runtime/autonomy.py` (một chủ); `AutonomyApprovalPolicy.requires_approval` gọi hàm đó,
   `test_autonomy_policy.py` giữ xanh không sửa.
3. `dw_platform/domain/digital_worker.py`: `DigitalWorker`, `DecisionClass`, bảng chuyển trạng thái
   DW của R1.7.
4. `dw_platform/application/digital_workers.py`: `DigitalWorkerService` (`create`, `get`, `list`,
   `change_state`, `replace_people`), Protocol `DigitalWorkerRepositoryPort`, `ToolCatalogPort`
   (công cụ có tồn tại không), `MembershipCheckPort` (membership và scope của một user ở workspace);
   `create` kiểm luật phủ (người tạo giữ mọi scope của `role_keys`, R1.10) và `forbid_escalation`;
   `DecisionAutonomy.effective_level(dw_id, key)` và `requires_person` theo R2.3, R2.4.
5. `dw_platform/adapters/persistence/digital_workers_repo.py`: một giao dịch ghi user `kind = 'service'`,
   `platform.service_principals`, membership của principal, dòng DW và các loại quyết định, audit
   `dw.created`; `dw.state_changed`, `dw.people_changed` cùng giao dịch với thay đổi.
6. Danh sách của mặt danh tính lọc `kind = 'human'`: `/directory/candidates`, `/admin/members` và
   mọi truy vấn cùng loại trong `dw_platform/adapters/persistence/directory.py` và `membership_admin.py`.
7. Route `apps/api/src/dw_api/routes/v1/digital_workers.py`: `POST /v1/digital-workers`,
   `GET /v1/digital-workers`, `GET /v1/digital-workers/{id}`, `POST /v1/digital-workers/{id}/state`,
   `PUT /v1/digital-workers/{id}/people`, theo app-standards (problem+json, `Idempotency-Key`, keyset),
   mã lỗi đúng mục API của spec; nối ở `apps/api/src/dw_api/bootstrap/wiring.py`.
8. Test âm DWK1, DWK3 (DW và loại quyết định), DWK4-DWK7, DWK23-DWK25.
9. Theo gate lượt 2 và lượt xác nhận: `membership_admin` từ chối thêm vai hay bộ quyền cho principal của một DW
   (R1.17, 409 `dw_principal_roles_fixed`), vẫn cho tạm ngưng và gỡ; test catalog trong `test_privileges.py` (hay
   `test_rls_coverage.py`) liệt kê membership của principal của DW giữ vai tới hạn và đỏ khi có (R1.18, DWK41).

## Tiêu chí chấp nhận

- [ ] R1.1: tạo DW hợp lệ trả 201; cùng giao dịch có dòng DW `draft`, user `kind = 'service'` với `owner_tenant_id`, dòng `service_principals` và membership của principal; thân có `tenant_id` khác bị bỏ qua.
- [ ] R1.2 (DWK1): Validator là user của tenant B → 422 `owner_not_member`; Validator không giữ `approvals.decide` → 422 `validator_cannot_decide`; không dòng nào.
- [ ] R1.3: công cụ không có spec → 422 `tool_unknown`; `work_kinds` rỗng → 422 `work_kinds_empty`.
- [ ] R1.5 (DWK3): tenant B và workspace khác đọc id DW của A → 404; đọc thẳng `platform.digital_workers` và `platform.dw_decision_classes` không ngữ cảnh → 0 dòng.
- [ ] R1.6 (DWK4): người giữ `dw.manage` không là chủ gọi `/state` → 403 `not_dw_owner`, trạng thái không đổi; BO là thành viên thường (không `dw.manage`) gọi `/state` → được.
- [ ] R1.7 (DWK5): `retired→operating` → 409 `invalid_transition`.
- [ ] R1.8: đổi trạng thái ghi `dw.state_changed` đứng tên người đổi; giao dịch lỗi thì không dòng audit.
- [ ] R1.9 (DWK23): người tạo gọi `draft→operating` → 409 `second_person_required`; TO không giữ scope của vai của principal → 403 `grants_not_covered`; TO khác người tạo, phủ quyền → `operating`.
- [ ] R1.10 (DWK24): người tạo không giữ một scope của vai gán cho principal → 403 `grants_not_covered`, không dòng nào.
- [ ] R1.11 (DWK25): chèn `platform.external_identities` cho principal của DW → lỗi trigger; `/directory/candidates` và `/admin/members` không có principal đó.
- [ ] R1.15 (DWK33): gán `org_admin` hay vai có scope `admin.*` cho principal → 422 `role_not_allowed_for_service`, không dòng nào.
- [ ] R1.16 (DWK33): `owner_user_id` là user của tenant B, hay user `kind = 'service'` → lỗi trigger `platform.guard_accountable_owner()`.
- [ ] R1.13 (DWK4): TO đổi Validator sang một thành viên khác → người mới, audit `dw.people_changed`; người không là chủ → 403; Validator mới ngoài workspace → 422.
- [ ] R2.1: mỗi loại quyết định trong thân thành một dòng `platform.dw_decision_classes`.
- [ ] R2.2: `earned_level` A3 với trần A2 → 422 `above_ceiling`, không dòng DW nào.
- [ ] R2.3 (DWK6): trần tenant A1, đã kiếm A3, trần loại A4 → `A1`; loại không tồn tại → `A0`.
- [ ] R2.4 (DWK7): `critical` ở A4 đòi người; `external` không đảo được ở A3 đòi người; đảo được ở A3 không đòi; `test_autonomy_policy.py` xanh không sửa.
- [ ] R1.17 (DWK36): `PUT /admin/members` thêm vai cho principal của DW → 409 `dw_principal_roles_fixed`, membership không đổi; tạm ngưng → được.
- [ ] R1.18 (DWK41): gán `org_admin` cho principal bằng vai migrator → test catalog đỏ và nêu DW; gỡ → xanh.
- [ ] Xong: `make test-unit test-contract test-architecture` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/autonomy.py:71-133`; `packages/python/dw_kernel/src/dw_kernel/autonomy.py:17`; `db/migrations/versions/0006_autonomy.py:51`; `docs/adr/0103-runs-act-as-a-principal-within-a-boundary.md:52-77`; spec: R1, R2, DWK1, DWK3-DWK7, DWK23-DWK25. R1.4, R1.12, R1.14 ở ticket 02.

## Comments

- 2026-10-29 (agent): viết lại theo gate `checking-plan-readiness` lượt 1 (định danh DW là service principal tối thiểu theo ADR-0103 (Accepted) quyết 2; hai người khi vào chạy; luật phủ). org-and-principals/03 chờ ticket này và mở rộng cùng bảng.
- 2026-10-29 (agent): theo lượt xác nhận của gate: Business Owner chỉ ở `platform.service_principals.owner_user_id` với trigger `platform.guard_accountable_owner()`; vai tới hạn bị cấm cho principal (R1.15, R1.16, DWK33).
- 2026-10-29 (agent): theo gate lượt 2: route thành viên từ chối ghi membership của user `kind = 'service'` (R1.17, DWK36); bốn người phải `kind = 'human'`; mọi route theo id trả 404 trước 403 (R1.5).
- 2026-10-29 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
