# 01 — Hồ sơ Digital Worker, service principal tối thiểu, loại quyết định và mức tự chủ có hiệu lực

Status: resolved
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

- [x] R1.1: tạo DW hợp lệ trả 201; cùng giao dịch có dòng DW `draft`, user `kind = 'service'` với `owner_tenant_id`, dòng `service_principals` và membership của principal; thân có `tenant_id` khác bị bỏ qua.
- [x] R1.2 (DWK1): Validator là user của tenant B → 422 `owner_not_member`; Validator không giữ `approvals.decide` → 422 `validator_cannot_decide`; không dòng nào.
- [x] R1.3: công cụ không có spec → 422 `tool_unknown`; `work_kinds` rỗng → 422 `work_kinds_empty`.
- [x] R1.5 (DWK3): tenant B và workspace khác đọc id DW của A → 404; đọc thẳng `platform.digital_workers` và `platform.dw_decision_classes` không ngữ cảnh → 0 dòng.
- [x] R1.6 (DWK4): người giữ `dw.manage` không là chủ gọi `/state` → 403 `not_dw_owner`, trạng thái không đổi; BO là thành viên thường (không `dw.manage`) gọi `/state` → được.
- [x] R1.7 (DWK5): `retired→operating` → 409 `invalid_transition`.
- [x] R1.8: đổi trạng thái ghi `dw.state_changed` đứng tên người đổi; giao dịch lỗi thì không dòng audit.
- [x] R1.9 (DWK23): người tạo gọi `draft→operating` → 409 `second_person_required`; TO không giữ scope của vai của principal → 403 `grants_not_covered`; TO khác người tạo, phủ quyền → `operating`.
- [x] R1.10 (DWK24): người tạo không giữ một scope của vai gán cho principal → 403 `grants_not_covered`, không dòng nào.
- [x] R1.11 (DWK25): chèn `platform.external_identities` cho principal của DW → lỗi trigger; `/directory/candidates` và `/admin/members` không có principal đó.
- [x] R1.15 (DWK33): gán `org_admin` hay vai có scope `admin.*` cho principal → 422 `role_not_allowed_for_service`, không dòng nào.
- [x] R1.16 (DWK33): `owner_user_id` là user của tenant B, hay user `kind = 'service'` → lỗi trigger `platform.guard_accountable_owner()`.
- [x] R1.13 (DWK4): TO đổi Validator sang một thành viên khác → người mới, audit `dw.people_changed`; người không là chủ → 403; Validator mới ngoài workspace → 422.
- [x] R2.1: mỗi loại quyết định trong thân thành một dòng `platform.dw_decision_classes`.
- [x] R2.2: `earned_level` A3 với trần A2 → 422 `above_ceiling`, không dòng DW nào.
- [x] R2.3 (DWK6): trần tenant A1, đã kiếm A3, trần loại A4 → `A1`; loại không tồn tại → `A0`.
- [x] R2.4 (DWK7): `critical` ở A4 đòi người; `external` không đảo được ở A3 đòi người; đảo được ở A3 không đòi; `test_autonomy_policy.py` xanh không sửa.
- [x] R1.17 (DWK36): `PUT /admin/members` thêm vai cho principal của DW → 409 `dw_principal_roles_fixed`, membership không đổi; tạm ngưng → được.
- [x] R1.18 (DWK41): gán `org_admin` cho principal bằng vai migrator → test catalog đỏ và nêu DW; gỡ → xanh.
- [x] Xong: `make test-unit test-contract test-architecture` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/autonomy.py:71-94`; `packages/python/dw_kernel/src/dw_kernel/autonomy.py:17`; `db/migrations/versions/0006_autonomy.py:51`; `docs/adr/0103-runs-act-as-a-principal-within-a-boundary.md:52-77`; spec: R1, R2, DWK1, DWK3-DWK7, DWK23-DWK25. R1.4, R1.12, R1.14 ở ticket 02.

## Comments

- 2026-10-29 (agent): viết lại theo gate `checking-plan-readiness` lượt 1 (định danh DW là service principal tối thiểu theo ADR-0103 (Accepted) quyết 2; hai người khi vào chạy; luật phủ). org-and-principals/03 chờ ticket này và mở rộng cùng bảng.
- 2026-10-29 (agent): theo lượt xác nhận của gate: Business Owner chỉ ở `platform.service_principals.owner_user_id` với trigger `platform.guard_accountable_owner()`; vai tới hạn bị cấm cho principal (R1.15, R1.16, DWK33).
- 2026-10-29 (agent): theo gate lượt 2: route thành viên từ chối ghi membership của user `kind = 'service'` (R1.17, DWK36); bốn người phải `kind = 'human'`; mọi route theo id trả 404 trước 403 (R1.5).
- 2026-10-29 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-10-30 (agent): code và test xong (`5e1ca10`). Làm khác spec, có lý do:
  - `dw_app` giữ DELETE trên `service_principals`, `digital_workers`, `dw_decision_classes`. Spec ghi "DELETE không
    cấp (offboarding xóa bằng vai của nó)", nhưng offboarding ở repo này chạy bằng `dw_app` và chỉ xóa bảng tenant mà
    `dw_app` có DELETE (`offboarding.py`, `_CATALOG_PURGEABLE`); thiếu quyền đó thì `digital_workers` giữ workspace bằng
    RESTRICT và không tenant nào có DW offboard được. Không đường ứng dụng nào xóa dòng. Test:
    `test_offboarding_exports_and_purges_a_tenant_holding_a_dw`.
  - Khóa ngoại ghép mang `tenant_id`: `digital_workers (tenant_id, workspace_id)` tới workspace,
    `(tenant_id, principal_user_id)` tới `service_principals`, `dw_decision_classes (tenant_id, workspace_id, dw_id)`
    tới DW (spec ghi khóa một cột): khóa ngoại không đi qua RLS, như `3f1cb1d4cece`.
  - Scope quản trị: nền tảng dùng tiền tố `platform.` (`is_administrative`), spec ghi `admin.*`; R1.15 và phép kiểm
    catalog R1.18 xét cả hai. `tenant_owner` chưa có trong danh mục vai, vẫn bị cấm theo tên.
  - Membership không có "tạm ngưng" ở repo này; R1.17 cho thu hẹp vai và gỡ membership, từ chối thêm vai, bộ quyền,
    workspace (trigger `ck_memberships_dw_principal_roles_fixed`, cả `dw_app` lẫn `dw_provisioner`).
  - Lọc `kind = 'human'` cũng ở sơ đồ tổ chức (`hierarchy_repo`) và `SqlScopeHolders.holding` (ai được báo việc);
    `holds`/`scopes_of` không lọc vì ticket 02 hỏi chúng về chính principal. Bộ lọc ở `/directory/candidates` là phòng
    thủ thêm: principal không có email nên truy vấn đó vốn đã loại nó, đột biến không đỏ được.
  - `DecisionAutonomy` chưa có cổng nào gọi: `DecisionGate` của ticket 02 là người đọc (failure-modes #1, ghi ở đây
    để ticket 02 nối).
  - `ToolCatalogPort` là `ToolRegistry.has_tool` (tên công cụ đã đăng ký, mọi phiên bản), đọc lúc hỏi.
  - Sau offboarding, dòng `platform.users` của principal còn lại như mọi user người (bảng định danh không có
    `tenant_id`); xóa theo `owner_tenant_id ON DELETE CASCADE` khi dòng tenant bị xóa.
- 2026-10-30 (agent): `reviewing-feature-security`: sáu ranh giới; untrusted content không áp (không lời gọi model,
  mandate và tham số chưa vào prompt nào). Một lỗ hổng không đóng ở ticket này: `dw_app` chèn được user `service`
  nêu `owner_tenant_id` bất kỳ (bảng `users` không RLS); nó không thành principal ở tenant khác vì trigger đòi
  `owner_tenant_id = NEW.tenant_id` (có test).
- 2026-10-30 (agent): mutation check `mutations/01.yaml`: 22/22 đỏ, đối chứng xanh. Lượt đầu bốn nhóm đối chứng đỏ
  vì `scripts/mutate.py` chép `dw_platform` ra thư mục tạm và `retention_policy` tìm `configs/` theo `parents[5]`;
  sửa `run_local` đặt `DW_REPO_ROOT` (chỉ khi có overlay), chạy lại cả bộ.
- 2026-10-30 (agent): độ trễ, app ASGI thật trên PostgreSQL compose, ấm, 200 lần mỗi operation sau 20 lần khởi động,
  một tenant 200 thành viên, so với `711dbc5` (`git archive`); P50/P95/P99 ms trước → sau:
  `GET /admin/members` 38,3/47,3/61,3 → 38,4/49,9/65,6; `GET /directory/members` 36,7/46,6/52,8 → 36,0/45,5/50,9;
  `GET /directory/candidates` 33,7/42,9/49,4 → 33,4/42,0/48,8; `GET /admin/hierarchy` 33,9/43,0/47,7 →
  33,4/42,9/51,4; `PUT /admin/members/{id}/memberships` (trigger mới trên `memberships`) 63,1/77,3/91,4 →
  62,8/79,7/87,0. Mới: `POST /digital-workers` 77,2/92,8/98,3; `GET /digital-workers` 40,3/49,6/57,6;
  `GET /digital-workers/{id}` 32,3/39,0/46,4; `POST /digital-workers/{id}/state` 60,8/74,9/83,2. Trong ngân sách,
  không P95 nào kém hơn 20%.
- 2026-10-30 (agent): cổng nhanh xanh: ruff, format, mypy (470 tệp), `make test-unit`, `make test-contract`,
  `make test-architecture`; integration của `dw_platform`, `apps/api`, `dw_agent_runtime` xanh. `make
  test-integration` đầy đủ và `/code-review` chờ lúc đóng đợt (`wave-close.md`). Ticket resolved (`5e1ca10`,
  `827556e`, `cd19cfe`).
