# 03 — Tài khoản dịch vụ làm chủ thể chạy

Status: needs-triage
Blocked by: 02, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md, .claude/plans/studio/foundations-hardening/issues/02-hang-rao-du-lieu-va-danh-tinh.md, .claude/plans/studio/foundations-hardening/issues/03-quyen-dw-app-va-rls-initplan.md, .claude/plans/studio/app-standards/issues/01-vo-loi-problem-json.md, .claude/plans/studio/app-standards/issues/02-khoa-chong-lap-gan-nguoi-goi.md, .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md, .claude/plans/studio/digital-worker/issues/01-ho-so-dw-va-loai-quyet-dinh.md
Area: studio
Yêu cầu: R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.8, R6.9, R6.10, R7.1, R7.2, OP8, OP9, OP10, OP11, OP14, OP15

## Mục tiêu

Công ty có tài khoản dịch vụ: một dòng `platform.users` loại `service` thuộc tenant, giữ membership và vai trò như một
người, không bao giờ đăng nhập, không bao giờ giữ quyền trọng yếu, và chỉ được gắn làm chủ thể chạy bởi người giữ mọi quyền
của nó (R6, R7, YC8; ADR-0103 (Accepted) mục 2, 4). Việc gắn vào phiên bản và chạy lượt chạy dưới danh nghĩa nó thuộc
workflow-triggers và workflow-engine (R6.7); workflow-triggers đọc sự kiện `platform.service_principal.grants_changed` của
ticket này, và ticket đọc sự kiện đó của workflow-triggers chờ ticket này (DO-12). Công ty rời nền tảng thì lane
offboarding xóa người dùng loại `service` của nó qua một hàm SECURITY DEFINER hẹp, ở một bước đăng ký vào sổ bước xóa
mà foundations-hardening/07 dựng, thứ tự suy từ khóa ngoại `RESTRICT` và `NO ACTION` của `pg_constraint` (R6.8, R6.9;
foundations-hardening:R11.4; H-2); ticket này chờ foundations-hardening/07 vì cùng sửa lane offboarding và
`test_offboarding.py`, và không chờ usage-and-limits/02, ticket cũng đăng ký một bước vào sổ đó. Bảng khác tham chiếu tài khoản dịch vụ bằng khóa ngoại ghép trong tenant (R6.10). Từ brief B2 ticket 07; DO-12 và DO-17 đã có câu trả lời ngày 23/10/2026.

## Việc cần làm

1. **Người dùng loại dịch vụ.** Migration (id hex của `alembic revision`): `platform.users` thêm
   `kind text NOT NULL DEFAULT 'human'` với `ck_users_kind CHECK (kind IN ('human','service'))`,
   `owner_tenant_id uuid NULL` FK `platform.tenants` `ON DELETE CASCADE`, index `ix_users_owner_tenant_id`, và
   `ck_users_service_owner CHECK ((kind = 'service') = (owner_tenant_id IS NOT NULL))` để một dòng nửa vời bị từ chối.
2. **Dòng chi tiết.** `platform.service_principals`: `user_id uuid PRIMARY KEY` FK `platform.users` `ON DELETE CASCADE`,
   `tenant_id uuid NOT NULL`, `owning_workspace_id uuid NOT NULL`,
   `name text NOT NULL CHECK (btrim(name) <> '' AND char_length(name) <= 120)`,
   `description text CHECK (description IS NULL OR char_length(description) <= 1000)`, `created_by uuid NULL` FK
   `platform.users` `ON DELETE SET NULL`, `created_at`, `updated_at` (`timestamptz NOT NULL DEFAULT now()`);
   `uq_service_principals_tenant_id_name UNIQUE (tenant_id, name)`;
   `uq_service_principals_tenant_id_user_id UNIQUE (tenant_id, user_id)`, đích của khóa ngoại ghép mà bảng khác dùng để
   tham chiếu tài khoản dịch vụ trong cùng tenant, thay cho khóa ngoại một cột tới `user_id` (R6.10); FK
   `(tenant_id, user_id)` tới `platform.tenant_members`
   `ON DELETE CASCADE`; FK `(tenant_id, owning_workspace_id)` tới `platform.workspaces (tenant_id, id)` (ràng buộc
   `uq_workspaces_tenant_id_id` của ticket 01) `ON DELETE RESTRICT`; index `(tenant_id, owning_workspace_id)`,
   `created_by`. RLS ENABLE và FORCE, chỉ policy tenant; bảng toàn tenant, nên thêm `platform.service_principals` vào
   `_TENANT_WIDE_ON_PURPOSE` của studio-skeleton/01 kèm lý do (một tài khoản dịch vụ thuộc cả công ty, workspace sở hữu chỉ
   để kiểm quyền quản lý và gắn). `dw_app` SELECT, INSERT, UPDATE, không DELETE: offboarding xóa dòng theo cascade của
   khóa ngoại tới `platform.tenant_members` khi xóa bảng đó, nên `platform.service_principals` vào `STUDIO_EXCLUSIONS` của
   studio-skeleton/01 với lý do ấy (studio-skeleton:R4.3).
   Hoạt động hay tạm khóa là `platform.tenant_members.status`, một sự thật một chỗ. Trigger từ chối dòng thành viên công
   ty của người dùng loại `service` ở tenant khác `owner_tenant_id`.
3. **Không đăng nhập.** Mở rộng `platform.guard_privileged_login_identity()` (foundations-hardening/02): từ chối dòng
   `platform.external_identities` cho người dùng loại `service`. Tra cứu danh tính (`membership_lookup.py:200-202`,
   `_resolve_user` ở `identity_provisioning.py`) chỉ khớp `kind = 'human'`; `subject` của tài khoản dịch vụ là `svc:`
   kèm uuid và không token nào khớp được.
4. **Không quyền trọng yếu.** `platform.guard_service_principal_grants()`: trigger BEFORE INSERT, UPDATE tên
   `guard_service_principal_grants` trên `platform.role_assignments` (người nhận loại `service` mà vai trò là
   `tenant_owner` hay có khóa `risk = 'critical'`) và trên `platform.tenant_role_permissions` (thêm khóa `critical` vào vai
   trò đang gán cho một tài khoản dịch vụ), SQLSTATE 23514, ràng buộc `ck_role_assignments_service_not_critical`, áp cho mọi
   người ghi kể cả `dw_provisioner`, `dw_migrator`. Trigger này riêng với trigger của `platform.rbac_refusals`
   (tenant-rbac/03), vốn miễn hai vai đó, và hai ticket không chờ nhau (Đạt chấp nhận, OPS-b): tên của nó đứng trước
   `rbac_refusals_*` của tenant-rbac/03 theo bảng chữ cái nên bắn trước và lỗi tài khoản dịch vụ được báo trước; test catalog của
   ticket này chỉ khẳng định trigger `guard_service_principal_grants` có trên hai bảng. Trigger AFTER cùng họ ghi outbox
   `platform.service_principal.grants_changed` (`tenant_id`, `service_principal_id`) khi quyền hiệu lực của tài khoản dịch
   vụ tăng; người đọc là workflow-triggers, đưa binding `principal` về `binding_needs_review` tới khi người phủ đủ quyền
   duyệt lại (DO-12).
5. **Khóa quyền.** Migration thêm `platform.service_principals.manage` và `platform.service_principals.use` (loại
   `workspace`, `elevated`, `tenant_grantable`) vào danh mục quyền theo quy ước của tenant-rbac/01.
6. **Route** (`Idempotency-Key` trên mutation, phong bì lỗi của ADR-0108 (Accepted)):
    - `POST /api/v1/admin/service-principals` (`platform.service_principals.manage` với tới `owning_workspace_id`): thân
      `name`, `description`, `owning_workspace_id`; một giao dịch ghi người dùng loại `service`, thành viên công ty `active`,
      membership ở workspace sở hữu (không vai trò), dòng chi tiết, audit `platform.service_principal.created` chỉ có id.
      Vai trò gán qua API gán vai trò của tenant-rbac, hai người như mọi thành viên (D11).
    - `GET /api/v1/admin/service-principals` (`.manage` hay `.use`): `id`, `name`, `description`, `owning_workspace_id`,
      `status`, `bindable_by_me`; sắp theo `name`, keyset trên `uq_service_principals_tenant_id_name`.
    - `PATCH /api/v1/admin/service-principals/{service_principal_id}` (`name`, `description`), audit
      `platform.service_principal.updated`.
7. **Bộ kiểm gắn.** `ServicePrincipalBindingGuard.require_bindable(context, service_principal_id)` trong `dw_platform`:
   `platform.service_principals.use` với tới workspace sở hữu, rồi `platform.grants_cover(tenant, người gọi, tài khoản)`
   (tenant-rbac/02); thiếu thì 403 `rbac_escalation` kèm khóa thiếu. `bindable_by_me` gọi cùng phương thức. Bên gắn
   (workflow-triggers, bộ kiểm binding của tenant-config) khai Protocol của mình; `apps/api/src/dw_api/bootstrap/wiring.py`
   đáp ứng.
8. **Mặt danh tính lọc loại.** `/directory/candidates` (`directory.py:65-78` và adapter của nó),
   `GET /api/v1/platform/users` (`platform.py:94`) và bootstrap chỉ trả `kind = 'human'`; test liệt kê mọi câu đọc
   `platform.users` mà một route dùng.
9. **Offboarding.** Migration của bước 1 thêm `platform.purge_tenant_service_users(p_tenant uuid) RETURNS integer`,
   SECURITY DEFINER, `search_path` cố định, thu EXECUTE khỏi `PUBLIC`, cấp EXECUTE cho `dw_app`: từ chối với SQLSTATE
   23514 khi `platform.tenants.status` của `p_tenant` khác `offboarding` (R6.9); không thì xóa dòng `platform.users` có
   `kind = 'service' AND owner_tenant_id = p_tenant` và trả số dòng đã xóa; `test_privileges.py` khẳng định `dw_app` có
   EXECUTE còn `PUBLIC` thì không (CLAUDE.md, Data model rules). Ở composition root của worker
   (`apps/worker/src/dw_worker/main.py`), đăng ký vào sổ bước xóa của foundations-hardening/07 một bước
   `service_users` khai bảng `platform.users`, chạy `platform.purge_tenant_service_users(:t)` trong giao dịch xóa. Thứ tự
   của bước suy từ `pg_constraint` (foundations-hardening:R11.4): nó chạy sau mọi bước xóa bảng giữ khóa ngoại
   `ON DELETE RESTRICT` hay `NO ACTION` tới `platform.users` (như `run_as_principal_id` của workflow-triggers), vì
   bảng đó giữ tài khoản dịch vụ tới khi chính nó bị xóa; không danh sách tay nào đặt nó "sau cùng", và nó không cần
   biết bước `platform.purge_tenant_append_only` của usage-and-limits/02. Việc xóa đi qua hàm vì `dw_app` không có
   DELETE trên `platform.users` (foundations-hardening:R5.1), và dòng `platform.tenants` ở lại `offboarded` nên CASCADE
   của `owner_tenant_id` không bao giờ chạy. `platform.service_principals` không có bước riêng: dòng của nó đi theo
   `CASCADE` từ `platform.tenant_members` (và từ `platform.users`), nên khóa ngoại `RESTRICT` của nó tới workspace sở
   hữu được thứ tự suy mang sang các bước đó, chạy trước bước xóa `platform.workspaces`. `test_offboarding.py` purge một
   tenant có tài khoản dịch vụ và khẳng định không còn dòng `platform.service_principals` nào và không còn người dùng
   loại `service` nào của tenant đó, còn người dùng loại `human` và tài khoản dịch vụ của tenant khác giữ nguyên; cùng
   tệp, một bảng thử giữ khóa ngoại `RESTRICT` tới tài khoản dịch vụ, tạo trong giao dịch test, và một test bắt câu
   lệnh bằng sự kiện `before_cursor_execute` khẳng định bước `service_users` chạy sau câu xóa bảng thử đó.

## Tiêu chí chấp nhận

- [ ] R6.1: `POST /api/v1/admin/service-principals` → người dùng `service`, thành viên công ty `active`, membership, dòng chi tiết và một audit cùng giao dịch; lỗi giữa giao dịch → không dòng nào; người không có `platform.service_principals.manage` → 403.
- [ ] R6.2 (OP8): token dev mang `subject` của tài khoản dịch vụ → 403, không AccessContext; gỡ điều kiện `kind = 'human'` khỏi tra cứu → test đỏ.
- [ ] R6.3 (OP8): INSERT `platform.external_identities` cho tài khoản dịch vụ, dưới `dw_app` và `dw_provisioner` → trigger từ chối; gỡ nhánh `kind` khỏi guard → đỏ.
- [ ] R6.4 (OP9): dưới `dw_migrator` gán `tenant_owner` cho tài khoản dịch vụ → 23514; thêm khóa `critical` vào vai trò đang gán cho nó → 23514; test catalog thấy trigger `guard_service_principal_grants` trên `platform.role_assignments` và `platform.tenant_role_permissions`; gỡ trigger → đỏ.
- [ ] R6.5 (OP10): người gọi thiếu một khóa tài khoản đang giữ → 403 `rbac_escalation` nêu khóa đó; thiếu `platform.service_principals.use` → 403; thay `platform.grants_cover` bằng `true` → đỏ; `bindable_by_me` bằng đúng kết quả của bộ kiểm.
- [ ] R6.6: gán vai trò cho tài khoản dịch vụ → đúng một sự kiện outbox `platform.service_principal.grants_changed` cùng giao dịch; giao dịch lùi → không sự kiện.
- [ ] R6.8 (OP14): purge một tenant `offboarding` có một tài khoản dịch vụ → không còn dòng `platform.users` loại `service` có `owner_tenant_id` của tenant đó, không còn dòng `platform.service_principals` của nó, người dùng loại `human` và tài khoản dịch vụ của tenant khác còn; gỡ bước `service_users` khỏi sổ → `test_offboarding.py` đỏ; bảng thử giữ khóa ngoại `RESTRICT` tới tài khoản dịch vụ → bước chạy sau câu xóa bảng thử, và đổi khai của bước sang bảng khác `platform.users` → test phủ của studio-skeleton:R4.2 đỏ, nêu bước.
- [ ] R6.9 (OP14): gọi `platform.purge_tenant_service_users` dưới `dw_app` cho tenant `active` → 23514 và 0 dòng bị xóa; gỡ kiểm trạng thái khỏi hàm → test đỏ.
- [ ] R6.10 (OP15): bảng thử có khóa ngoại ghép `(tenant_id, sp_id)` tới `platform.service_principals (tenant_id, user_id)`, INSERT `(tenant_B, tài khoản dịch vụ của A)` → lỗi FK, không dòng nào; test catalog thấy `uq_service_principals_tenant_id_user_id` trong `pg_constraint`; bỏ ràng buộc → test đỏ.
- [ ] R7.1 (OP11): quản trị viên tenant B gọi `GET /api/v1/directory/candidates` → không có tài khoản dịch vụ của A hay B; gỡ lọc `kind` → đỏ.
- [ ] R7.2 (OP11): `GET /api/v1/platform/users` → không dòng `service`.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `db/migrations/sql/0001_platform_baseline.sql:438-444`; spec: R6.1.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:200-202`; spec: R6.2.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:121`; spec: R6.2.
- `apps/api/src/dw_api/routes/v1/directory.py:65-78`; spec: R7.1.
- `apps/api/src/dw_api/routes/v1/platform.py:94`; spec: R7.2.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/runtime_tables.py:38`; spec: R6.7.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:183-194`, `apps/worker/src/dw_worker/main.py:403-405`; spec: R6.8, R6.9; foundations-hardening:R11.4.
- ADR-0103 (Accepted) mục 1, 2, 4; brief B2 ticket 07 và mục 9.

## Comments

- 2026-10-24 (agent): vòng sửa 4, lượt hai: lời gọi `platform.purge_tenant_service_users` chạy sau cùng trong giao dịch
  xóa, sau `platform.purge_tenant_append_only` và mọi bảng của tenant, nên Blocked by thêm usage-and-limits/02 (hai
  ticket cùng sửa `purge_rows`); bước 2 thêm `uq_service_principals_tenant_id_user_id`, đích của khóa ngoại ghép từ bảng
  khác, với R6.10 và OP15 (Quyết định 24/10/2026 của spec).
- 2026-10-25 (agent): lượt h, theo H-2 (quyết định tạm cùng ngày của spec): Blocked by gỡ usage-and-limits/02 theo bảng
  cạnh của lượt h; bước 9 đăng ký bước `service_users` vào sổ bước xóa của foundations-hardening/07, thứ tự suy từ
  `pg_constraint`, thay lời gọi "sau cùng, sau `platform.purge_tenant_append_only`" và mục `_ORDERED_FIRST`; R6.8 thay ca
  "câu lệnh xóa cuối" bằng ca bước chạy sau bảng giữ khóa ngoại tới tài khoản dịch vụ; dòng Comments ngày 24/10/2026 về
  cạnh tới usage-and-limits/02 không còn áp.
- 2026-10-29 (agent): digital-worker/01 dựng phần tối thiểu của service principal theo ADR-0103 (Accepted) quyết 2 (`platform.users.kind`, `owner_tenant_id`, `platform.service_principals`, trigger từ chối danh tính đăng nhập, danh sách danh tính lọc `kind = 'human'`) cho định danh Digital Worker (D17); ticket này chờ nó và mở rộng chính các bảng đó (khóa API, binding, `owner_user_id` theo `tenant_members`, lane `principal_ownership`), không tạo lại.
