# 03 — Chống leo thang quyền và API quản trị vai trò, gán vai trò, audit

Status: needs-info (DO-32)
Blocked by: 02
Area: studio
Yêu cầu: R5.3, R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7, R7.1, R7.2, R7.3, R7.4, R7.5, R8.1, R8.2, R8.3, R8.4, R8.5, R8.6, G2, RB14, RB15, RB16, RB17, RB18, RB19, RB20, RB21, RB22, RB23, RB24, RB25, RB26, RB27

## Mục tiêu

Quản trị viên công ty tạo, sửa, nhân bản, xóa mềm vai trò và gán vai trò qua API, mỗi thay đổi do một người đề xuất và một
người khác xác nhận (R7, D11), không ai trao được quyền mình không giữ hay tự trao quyền, mỗi tenant luôn còn chủ sở hữu công ty (R6),
mọi thay đổi có audit cùng giao dịch và các đường ghi cũ hết đường (R8). Gộp từ brief B3 ticket 06, 08. Chờ DO-32 (Q2):
`platform.roles.bind` và việc quản trị viên tạo quản trị viên.

## Việc cần làm

1. **Khóa mới.** Migration thêm vào `platform.permissions`: `platform.roles.write` và `platform.roles.bind` (loại
   `tenant`, `critical`, `tenant_grantable`), và thêm `platform.roles.bind` mức `tenant` vào vai trò `org_admin` đã nhân
   bản của mọi tenant (ADR-0104 (Proposed), Consequences); `tenant_owner` có cả hai qua quyền tính động.
2. **Một hàm từ chối.** `platform.rbac_refusals(p_tenant_id uuid, p_actor_id uuid, p_change jsonb)` trả
   `(reason_code, permission_key, depth)`: luật giữ quyền qua cùng phép so của `platform.grants_cover` (ticket 02) trên
   workspace được gán vai trò của người nhận; `platform.roles.bind` phủ vai trò không có khóa `critical` (Q2); tự gán;
   vai trò hệ thống; khóa `tenant_grantable = false` và vai `platform_admin`. Service gọi trước khi ghi (403 hay 422 với
   `details.reason_code` và danh sách khóa); trigger BEFORE INSERT, UPDATE, DELETE trên
   `platform.tenant_role_permissions`, `platform.role_assignments` và BEFORE UPDATE, DELETE trên `platform.tenant_roles`
   gọi cùng hàm, SQLSTATE 23514. Người làm là `app.user_id`; ghi của `dw_app` thiếu nó bị từ chối; `dw_provisioner`,
   `dw_migrator` miễn theo `session_user` (tự audit); tenant không `active` miễn (offboarding); hàm lấy `FOR SHARE` trên
   gán vai trò của người làm, như `f381f1694395` làm với miễn trừ.
3. **Chủ sở hữu công ty cuối cùng.** Trigger AFTER `ck_role_assignments_last_owner` trên DELETE, UPDATE của
   `platform.role_assignments`, DELETE của `platform.memberships`, DELETE và UPDATE `status` của
   `platform.tenant_members`, DELETE của `platform.users`: tenant `active` phải còn ít nhất một gán `tenant_owner` của thành
   viên `active`, cascade cũng tính. Gán `tenant_owner` có `expires_at` → 23514.
4. **Hai người (D11).** `platform.role_change_requests`: `id uuid PRIMARY KEY`, `tenant_id uuid NOT NULL` FK
   `platform.tenants` `ON DELETE CASCADE`,
   `kind text NOT NULL CHECK (kind IN ('role_create','role_update','role_permissions','role_delete','assignment_grant','assignment_revoke'))`,
   `payload jsonb NOT NULL`, `role_id uuid NULL`, `base_version integer NULL`, `required_permission text NOT NULL`,
   `proposed_by uuid NOT NULL`, `proposed_at timestamptz NOT NULL DEFAULT now()`,
   `expires_at timestamptz NOT NULL`, `ck_role_change_requests_expiry CHECK (expires_at = proposed_at + interval '7 days')`,
   `status text NOT NULL CHECK (status IN ('proposed','confirmed','withdrawn'))`, `confirmed_by uuid NULL`,
   `decided_at timestamptz NULL`, `ck_role_change_requests_second_person CHECK (confirmed_by IS NULL OR confirmed_by <> proposed_by)`;
   FK `(tenant_id, role_id)` tới `platform.tenant_roles` `ON DELETE CASCADE`; index `(tenant_id, status, proposed_at, id)`
   cho danh sách. RLS tenant; `dw_app` SELECT, INSERT và UPDATE chỉ trên `status`, `confirmed_by`, `decided_at`. Hết hạn
   đọc từ `expires_at`, không có trạng thái thứ hai; dòng giữ làm hồ sơ tới khi offboarding xóa tenant.
    - Mutation ở bước 5 và 6 ghi một đề xuất (202 kèm `id`) sau khi `platform.rbac_refusals` cho người đề xuất không trả
      gì; không còn người `active` nào khác giữ `required_permission` (đọc qua `platform.effective_grants`) → 409
      `no_checker_available`, không ghi.
    - `POST /api/v1/admin/role-changes/{request_id}/confirm` (cùng quyền, `Idempotency-Key`): người khác người đề xuất
      (409 `second_person_required`), chưa quá `expires_at` (409 `proposal_expired`), `base_version` còn đúng (409
      `stale_version`); đặt `set_config('app.role_change_id', ..., true)` rồi áp thay đổi trong giao dịch của người
      duyệt, nên trigger bước 2 kiểm chính người duyệt.
    - `POST /api/v1/admin/role-changes/{request_id}/withdraw` (người đề xuất hay người giữ cùng quyền);
      `GET /api/v1/admin/role-changes` (đề xuất còn mở, phân trang theo index trên).
    - Trigger bước 2 từ chối ghi của `dw_app` khi `app.role_change_id` không trỏ tới đề xuất `proposed`, chưa hết hạn,
      cùng tenant, có `proposed_by` khác `app.user_id` (R7.5).
5. **Route vai trò** (mọi mutation có `Idempotency-Key`, phong bì lỗi của ADR-0108 (Proposed)):
   `GET /api/v1/admin/roles` (`platform.roles.read`; `id`, `key`, `name`, `description`, `kind`, `is_system`,
   `template_key`, `holder_count`, `version`, `assignable_by_me`, `updated_at`), `GET /api/v1/admin/roles/{role_id}`,
   `GET /api/v1/admin/roles/{role_id}/assignments`, `GET /api/v1/admin/role-templates` (chỉ lớp nền tảng),
   `POST /api/v1/admin/roles` (`platform.roles.write`; `from_template` hay `clone_of`),
   `PATCH /api/v1/admin/roles/{role_id}` (`name`, `description`, `version`),
   `PUT /api/v1/admin/roles/{role_id}/permissions` (`{version, permissions: [{key, depth}]}`),
   `DELETE /api/v1/admin/roles/{role_id}` (xóa mềm; 409 `role_in_use` kèm số người giữ, 409 `role_is_system`).
   `GET /api/v1/admin/permissions` thêm `allowed_depths` và `max_grantable_depth` tính bằng SQL từ quyền của người gọi;
   `assignable_by_me` tính bằng `platform.rbac_refusals`, không bản sao.
6. **Gán vai trò.** `PUT /api/v1/admin/members/{user_id}/memberships`, `POST /api/v1/admin/members`,
   `POST /api/v1/admin/invitations`, `PUT /api/v1/admin/members/{user_id}/permission-sets` ghi đề xuất gán và gỡ qua một
   `RoleAssignmentService`, kể cả gán `member` khi mời; nghỉ hưu `forbid_escalation`, `is_administrative`
   (`membership_admin.py:49-65`) và bản chép ở `admin_console.py:295-304`; `plan_memberships` giữ nguyên vai trò người gọi
   không quản được.
7. **Lỗi.** 23514 của trigger dịch sang 403 `rbac_escalation`, `rbac_self_assignment`; 422 `rbac_not_grantable`; 409
   `role_is_system`, `last_owner`, `role_limit_reached`, `stale_version`, `ck_roles_sod_memberships` (tên luật, tối đa 20
   người giữ); chỉ qua `details.reason_code`, không thêm mã vào `ErrorCode`.
8. **Audit cùng giao dịch:** `platform.role_change.proposed`, `.confirmed`, `.withdrawn`; khi áp:
   `platform.role.create`, `.update`, `.permissions_set` (thêm, bỏ, đổi mức), `.delete`,
   `platform.role_assignment.grant`, `.revoke`. `details`: id đề xuất, id và khóa vai trò, id workspace, id người dùng;
   không email, không tên.
9. **Cắt chuyển.** Bỏ trigger chép của ticket 02; `ck_memberships_legacy_role_columns`:
   `permission_set_keys = '[]'::jsonb` và `role_keys` chỉ được rỗng hay `["platform_admin"]` (giá trị script nền tảng ghi,
   giữ tới dòng W2); directory và trang thứ bậc đọc tên vai trò từ gán vai trò. Trang thành viên
   (`apps/web/components/admin/members-manager.tsx:34-39`) lấy vai trò từ `GET /api/v1/admin/roles`, khóa vai trò
   `assignable_by_me = false` kèm lý do, hiện "Chờ người thứ hai xác nhận" khi nhận 202; xóa `BASE_GRANTABLE_ROLES`,
   `ADMIN_GRANTABLE_ROLES`. `make generate-contracts`; client trong `packages/typescript/api-client`.

## Tiêu chí chấp nhận

- [ ] R5.3 (RB14): gán vai trò làm người nhận giữ hai vế một luật → 409 nêu luật và id người giữ; giao dịch lùi.
- [ ] R6.1 (RB15): người giữ `approvals.decide` mức `workspace` đề xuất vai trò có khóa đó mức `tenant` → 403 `rbac_escalation` kèm khóa; gỡ người nhận khỏi quyền mình không giữ → 403.
- [ ] R6.2 (RB15): cùng các thao tác bằng SQL thô dưới `dw_app` (có và không có `app.user_id`) → 23514; gỡ lời gọi `platform.rbac_refusals` khỏi từng trigger → test SQL thô đỏ trong khi test qua service vẫn xanh.
- [ ] R6.3 (RB16): người giữ `platform.roles.bind` đề xuất gán `member` dù không giữ khóa của nó → nhận; gán vai trò có khóa `critical` mình không giữ → 403.
- [ ] R6.4 (RB17): tự đề xuất gán cho mình → 403 `rbac_self_assignment`; xác nhận đề xuất gán cho chính mình → 403; SQL thô với `app.user_id` là người nhận → 23514.
- [ ] R6.5 (RB18): đưa `platform.admin` vào vai trò hay gán `platform_admin` → 422 `rbac_not_grantable`; SQL thô → 23514.
- [ ] R6.6 (RB19): xóa, đổi khóa `member`, sửa quyền `tenant_owner` → 409 `role_is_system` qua API, 23514 qua SQL thô.
- [ ] R6.7 (RB20): gỡ gán `tenant_owner` cuối, xóa membership, thành viên công ty hay người dùng của chủ sở hữu công ty cuối cùng → 409 `last_owner`, không đổi gì; hai quản trị đồng thời gỡ hai chủ sở hữu cuối → đúng một bị từ chối (test đồng thời).
- [ ] R7.1 (RB21): mutation vai trò trả 202 và vai trò chưa đổi; người thứ hai xác nhận → đổi, một audit `.confirmed` và một audit thay đổi.
- [ ] R7.2 (RB21): người đề xuất tự xác nhận → 409 `second_person_required`; gỡ `ck_role_change_requests_second_person` và kiểm của service → test đỏ.
- [ ] R7.3 (RB22): tenant chỉ một người giữ `platform.roles.write` → 409 `no_checker_available`, không dòng đề xuất.
- [ ] R7.4 (RB23): xác nhận ở `expires_at` cộng 1 giây → 409 `proposal_expired`; ở `expires_at` trừ 1 giây → nhận.
- [ ] R7.5 (RB21): SQL thô dưới `dw_app` ghi gán vai trò không mang `app.role_change_id`, hay mang đề xuất do chính `app.user_id` đề xuất → 23514; gỡ nhánh kiểm này khỏi trigger → đỏ.
- [ ] R8.1: `GET /api/v1/admin/roles` trả đủ trường; `assignable_by_me` bằng đúng kết quả `platform.rbac_refusals` cho cùng người gọi (test so sánh).
- [ ] R8.2 (RB24): người không có `platform.roles.write` gọi thẳng `PUT /api/v1/admin/roles/{role_id}/permissions`, `POST /api/v1/admin/roles` → 403, không đề xuất.
- [ ] R8.3 (RB25): đề xuất bị 409 → không audit; mỗi audit chỉ có id và mã (test quét `details` không có `@` hay tên).
- [ ] R8.4 (RB25): gửi lại cùng `Idempotency-Key` và thân → cùng kết quả, một audit.
- [ ] R8.5 (RB26): `version` cũ khi đề xuất hay khi xác nhận → 409 `stale_version`, quyền không đổi.
- [ ] R8.6 (RB27): ghi `permission_set_keys` khác rỗng hay `role_keys` chứa `member` → 23514 `ck_memberships_legacy_role_columns`.
- [ ] G2: `test_platform_admin_bypasses_scopes` xanh trước và sau cắt chuyển.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/application/membership_admin.py:49-65`; spec: R6.1.
- `packages/python/dw_platform/src/dw_platform/application/admin_console.py:295-304`; spec: R6.1.
- `packages/python/dw_platform/src/dw_platform/application/tenant_members.py:221`; spec: R6.1.
- `db/migrations/versions/f381f1694395_platform_sod_waiver_second_person_and_.py:73-84`; spec: R6.2.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_session.py:23-27`; spec: R6.2, R7.5.
- `apps/api/src/dw_api/routes/v1/admin_console.py:242`; spec: R8.1.
- `apps/api/src/dw_api/routes/v1/admin_members.py:201`; spec: R7.1.
- `apps/web/components/admin/members-manager.tsx:34-39`; spec: R8.2.
- `docs/adr/0012-a-sod-waiver-takes-two-people.md:24-34`; spec: R7.
- ADR-0104 (Proposed) mục 6; ADR-0012 (Accepted); brief B3 mục 1.5 và ticket 06, 08, 13.

## Comments
