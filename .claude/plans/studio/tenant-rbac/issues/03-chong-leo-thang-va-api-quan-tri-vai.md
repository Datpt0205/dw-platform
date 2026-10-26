# 03 — Chống leo thang quyền và API quản trị vai trò, gán vai trò, audit

Status: needs-triage
Blocked by: 02, .claude/plans/studio/app-standards/issues/01-vo-loi-problem-json.md, .claude/plans/studio/app-standards/issues/02-khoa-chong-lap-gan-nguoi-goi.md, .claude/plans/studio/app-standards/issues/03-quy-uoc-api-danh-sach-va-sua.md
Area: studio
Yêu cầu: R5.3, R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7, R7.1, R7.2, R7.3, R7.4, R7.5, R7.6, R7.7, R8.1, R8.2, R8.3, R8.4, R8.5, R8.6, R8.7, R8.8, R3.16, G2, RB14, RB15, RB16, RB17, RB18, RB19, RB20, RB21, RB22, RB23, RB24, RB25, RB26, RB27, RB32, RB36, RB42

## Mục tiêu

Quản trị viên công ty tạo, sửa, nhân bản, xóa mềm vai trò và gán vai trò qua API; mỗi thay đổi nới quyền do một người đề
xuất và một người khác xác nhận, thay đổi chỉ siết quyền do một người làm cộng audit (R7, D11: "đóng một người, mở hai
người"), không ai trao được quyền mình không giữ hay tự trao quyền, mỗi tenant luôn còn chủ sở hữu công ty (R6), mọi thay
đổi có audit cùng giao dịch, mutation theo ETag và `If-Match`, các đường ghi cũ hết đường (R8). Gộp từ brief B3
ticket 06, 08. DO-32.1 đã quyết theo khuyến nghị (a) (Đạt, 23/10/2026): luật giữ quyền, quản trị viên tạo được quản
trị viên, `platform.roles.bind` gán vai trò không trọng yếu.

## Việc cần làm

1. **Khóa mới.** Migration thêm vào `platform.permissions`: `platform.roles.write` và `platform.roles.bind`, câu INSERT
   nêu mọi cột NOT NULL của danh mục (`label_vi`, `area`, `scope_kind` `tenant`, `risk` `critical`, `status`
   `active`, `owner_package`, `tenant_grantable` `true`; Quyết định 24/10/2026 của spec), và thêm `platform.roles.bind`
   mức `tenant` vào vai trò `org_admin` đã nhân bản của mọi tenant (ADR-0104 (Accepted), Consequences); `tenant_owner`
   có cả hai qua quyền tính động.
2. **Một hàm từ chối.** `platform.rbac_refusals(p_tenant_id uuid, p_actor_id uuid, p_change jsonb)` trả
   `(reason_code, permission_key, depth)`: luật giữ quyền qua cùng phép so của `platform.grants_cover` (ticket 02) trên
   workspace được gán vai trò của người nhận; `platform.roles.bind` phủ vai trò không có khóa `critical` (DO-32.1;
   ticket 04 thêm vào phép so vai trò mang `fld.*` trên trường nhạy cảm); tự gán;
   vai trò hệ thống; khóa `tenant_grantable = false` và vai `platform_admin`. Service gọi trước khi ghi (403 hay 422 với
   `details.reason_code` và danh sách khóa); trigger BEFORE INSERT, UPDATE, DELETE trên
   `platform.tenant_role_permissions`, `platform.role_assignments` và BEFORE UPDATE, DELETE trên `platform.tenant_roles`
   gọi cùng hàm, SQLSTATE 23514, tên `rbac_refusals_<bảng>`. Người làm là `app.user_id`; ghi của `dw_app` thiếu nó bị từ
   chối; `dw_provisioner`, `dw_migrator` miễn theo `session_user` (tự audit); tenant không `active` miễn (offboarding);
   hàm lấy `FOR SHARE` trên gán vai trò của người làm, như `f381f1694395` làm với miễn trừ. Trigger tài khoản dịch vụ của
   org-and-principals/03 nằm trên cùng hai bảng mà không chờ ticket này (OPS-b cạnh 11, Quyết định 23/10/2026 của spec):
   thứ tự bắn theo bảng chữ cái của tên là chủ ý, và test catalog của ticket này chỉ khẳng định trigger `rbac_refusals_*`.
3. **Chủ sở hữu công ty cuối cùng.** Trigger AFTER `ck_role_assignments_last_owner` trên DELETE, UPDATE của
   `platform.role_assignments`, DELETE của `platform.memberships`, DELETE và UPDATE `status` của
   `platform.tenant_members`, DELETE của `platform.users`: tenant `active` phải còn ít nhất một gán `tenant_owner` của thành
   viên `active`, cascade cũng tính. Gán `tenant_owner` có `expires_at` → 23514.
4. **Hai người khi nới, một người khi chỉ siết (D11, ADR-0104 (Accepted) mục 10).** Thay đổi chỉ siết quyền: gỡ gán vai
   trò; bỏ khóa hay hạ mức trong vai trò mà không thêm khóa hay nâng mức nào; xóa mềm một vai trò không còn người giữ
   (Quyết định 24/10/2026 của spec). Nó áp ngay trong giao dịch của người gửi (200, đúng một audit, không dòng đề xuất),
   vẫn qua `platform.rbac_refusals` và `ck_role_assignments_last_owner` (R7.6). Mọi thay đổi khác, kể cả một lần
   `PUT .../permissions` vừa bỏ vừa thêm, đi qua đề xuất dưới đây (R7.1).
   `platform.role_change_requests` (bảng toàn tenant: một dòng lý do trong danh sách của `test_rls_coverage.py`, DO-01):
   `id uuid PRIMARY KEY`, `tenant_id uuid NOT NULL` FK
   `platform.tenants` `ON DELETE CASCADE`,
   `kind text NOT NULL CHECK (kind IN ('role_create','role_update','role_permissions','assignment_grant'))` (xóa mềm vai
   trò và gỡ gán vai trò không qua đề xuất, nên không có loại đề xuất cho chúng),
   `payload jsonb NOT NULL`, `role_id uuid NULL`, `base_version integer NULL`, `required_permission text NOT NULL`,
   `proposed_by uuid NOT NULL`, `proposed_at timestamptz NOT NULL DEFAULT now()`,
   `expires_at timestamptz NOT NULL`, `ck_role_change_requests_expiry CHECK (expires_at = proposed_at + interval '7 days')`,
   `status text NOT NULL CHECK (status IN ('proposed','confirmed','withdrawn'))`, `confirmed_by uuid NULL`,
   `decided_at timestamptz NULL`, `ck_role_change_requests_second_person CHECK (confirmed_by IS NULL OR confirmed_by <> proposed_by)`;
   FK `(tenant_id, role_id)` tới `platform.tenant_roles` `ON DELETE CASCADE`; index `(tenant_id, status, proposed_at, id)`
   cho danh sách và `(tenant_id, role_id)` cho FK tới vai trò. RLS tenant; `dw_app` SELECT, INSERT, UPDATE chỉ trên
   `status`, `confirmed_by`, `decided_at`, và DELETE chỉ dùng được ở lượt xóa của offboarding: trigger
   `platform.guard_role_change_request()` BEFORE DELETE từ chối với SQLSTATE 23514 mọi DELETE khi
   `platform.tenants.status` của công ty khác `offboarding` (spec R7.7), cùng hình với `platform.guard_control_switch()`
   của agent-lifecycle (agent-lifecycle:R7.5); khẳng định quyền trong `test_privileges.py`. Hết hạn đọc từ `expires_at`,
   không có trạng thái thứ hai; dòng giữ làm hồ sơ tới khi offboarding xóa tenant, và lane offboarding xuất rồi xóa
   bảng dưới test phủ offboarding (studio-skeleton:R4.3) bằng bước mặc định của sổ bước xóa (foundations-hardening:R11.4);
   hai khóa ngoại của bảng đều `ON DELETE CASCADE` nên thứ tự suy từ `pg_constraint` không ràng nó, và ticket này không
   đăng ký bước nào.
    - Mutation nới quyền ở bước 5 và 6 ghi một đề xuất (202 kèm `id`) sau khi `platform.rbac_refusals` cho người đề xuất
      không trả gì; `platform.checker_candidates` (ticket 02) không trả ai cho `required_permission` → 409 `conflict` với
      `details.reason_code` `no_checker_available`, không ghi.
    - `POST /api/v1/admin/role-changes/{request_id}/confirm` (cùng quyền, `Idempotency-Key`): người khác người đề xuất
      (409 `conflict`, `details.reason_code` `second_person_required`), chưa quá `expires_at` (409 `conflict`,
      `proposal_expired`), `base_version` còn đúng (409 `conflict`, `proposal_stale`, R8.7); đặt
      `set_config('app.role_change_id', ..., true)` rồi áp thay đổi trong giao dịch của người duyệt, nên trigger bước 2
      kiểm chính người duyệt. `second_person_required`, `no_checker_available` và `proposal_expired` là
      `details.reason_code` dùng chung với cơ chế hai người của tenant-config, cùng hình 409 `conflict` (Quyết định
      23/10/2026 và 24/10/2026 của spec).
    - `POST /api/v1/admin/role-changes/{request_id}/withdraw` (người đề xuất hay người giữ cùng quyền);
      `GET /api/v1/admin/role-changes` (đề xuất còn mở, phân trang theo index trên).
    - Trigger bước 2 từ chối ghi không chỉ siết quyền của `dw_app` khi `app.role_change_id` không trỏ tới đề xuất
      `proposed`, chưa hết hạn, cùng tenant, có `proposed_by` khác `app.user_id` (R7.5); ghi chỉ siết (DELETE trên
      `platform.role_assignments` hay `platform.tenant_role_permissions`, UPDATE hạ `depth`, UPDATE trên
      `platform.tenant_roles` chỉ đặt `deleted_at` từ NULL mà không đổi cột nào khác) chỉ cần `app.user_id` và qua
      `platform.rbac_refusals`; UPDATE đặt `deleted_at` về NULL không phải ghi chỉ siết.
5. **Route vai trò** (mọi mutation có `Idempotency-Key`, phong bì lỗi của ADR-0108 (Accepted)):
   `GET /api/v1/admin/roles` (`platform.roles.read`; `id`, `key`, `name`, `description`, `kind`, `is_system`,
   `template_key`, `holder_count`, `version`, `assignable_by_me`, `updated_at`), `GET /api/v1/admin/roles/{role_id}` (kèm
   `ETag: "<version>"`), `GET /api/v1/admin/roles/{role_id}/assignments`, `GET /api/v1/admin/role-templates` (chỉ lớp
   nền tảng), `POST /api/v1/admin/roles` (`platform.roles.write`; `from_template` hay `clone_of`),
   `PATCH /api/v1/admin/roles/{role_id}` (`name`, `description`), `PUT /api/v1/admin/roles/{role_id}/permissions`
   (`{permissions: [{key, depth}]}`), `DELETE /api/v1/admin/roles/{role_id}` (xóa mềm, một người cộng audit
   `platform.role.delete`, R7.6; 409 `role_in_use` kèm số người giữ, 409 `role_is_system`). Mutation trên vai trò đã có so `If-Match` mạnh với `version` theo app-standards/03
   (ADR-0108 (Accepted) mục 3): lệch → 412 `precondition_failed` (R8.5), thiếu → 428 `precondition_required` (R8.8); đề
   xuất ghi `base_version` từ `If-Match`.
   `GET /api/v1/admin/permissions` thêm `allowed_depths` và `max_grantable_depth` tính bằng SQL từ quyền của người gọi;
   `assignable_by_me` tính bằng `platform.rbac_refusals`, không bản sao.
6. **Gán vai trò.** `PUT /api/v1/admin/members/{user_id}/memberships`, `POST /api/v1/admin/members`,
   `POST /api/v1/admin/invitations`, `PUT /api/v1/admin/members/{user_id}/permission-sets` đi qua một
   `RoleAssignmentService`: gán, kể cả gán `member` khi mời, ghi đề xuất; gỡ áp ngay cộng audit (bước 4); nghỉ hưu
   `forbid_escalation`, `is_administrative` (`membership_admin.py:49-65`) và bản chép ở `admin_console.py:295-304`;
   `plan_memberships` giữ nguyên vai trò người gọi không quản được.
7. **Lỗi.** 23514 của trigger dịch sang 403 `rbac_escalation`, `rbac_self_assignment`; 422 `rbac_not_grantable`; 409
   `conflict` với `role_is_system`, `role_in_use`, `last_owner`, `role_limit_reached`, `second_person_required`,
   `no_checker_available`, `proposal_expired`, `proposal_stale`, `ck_roles_sod_memberships` (tên luật, tối đa 20 người
   giữ); chỉ qua `details.reason_code`, không thêm mã vào `ErrorCode`. 412 `precondition_failed` và 428
   `precondition_required` là mã của `ErrorCode` mà app-standards/01 thêm (ADR-0108 (Accepted) mục 1).
8. **Audit cùng giao dịch:** `platform.role_change.proposed`, `.confirmed`, `.withdrawn`; khi áp:
   `platform.role.create`, `.update`, `.permissions_set` (thêm, bỏ, đổi mức), `.delete`,
   `platform.role_assignment.grant`, `.revoke`. `details`: id đề xuất, id và khóa vai trò, id workspace, id người dùng;
   không email, không tên.
9. **Cắt chuyển.** Điều kiện tiên quyết (FOG-49, Đạt 24/10/2026): người giữ dw-proterial đã chuyển dw-proterial khỏi
   việc ghi `memberships.role_keys` và `permission_set_keys` trước khi migration của bước này chạy; chưa xong thì
   ticket này không lên ready-for-agent. Bỏ trigger chép của ticket 02; `ck_memberships_legacy_role_columns`:
   `permission_set_keys = '[]'::jsonb` và `role_keys` chỉ được rỗng hay `["platform_admin"]` (giá trị script nền tảng ghi,
   giữ tới dòng W2); directory và trang thứ bậc đọc tên vai trò từ gán vai trò. Trang thành viên
   (`apps/web/components/admin/members-manager.tsx:34-39`) lấy vai trò từ `GET /api/v1/admin/roles`, khóa vai trò
   `assignable_by_me = false` kèm lý do, hiện "Chờ người thứ hai xác nhận" khi nhận 202; xóa `BASE_GRANTABLE_ROLES`,
   `ADMIN_GRANTABLE_ROLES`. `make generate-contracts`; client trong `packages/typescript/api-client`.
10. **Đường vượt không mở route vai trò** (spec R3.16; Đạt, Q-h7): kiểm vượt `platform_admin` của G2 bỏ qua một danh
    sách route khai một lần cạnh router (`/api/v1/admin/roles`, `/api/v1/admin/role-changes`,
    `/api/v1/admin/members/{user_id}/memberships`, `/api/v1/admin/members/{user_id}/permission-sets` và route con), nên ở
    đó người gọi chỉ qua khi tự giữ khóa của route qua `platform.effective_grants`; test so danh sách với router, đỏ khi
    một route vai trò mới không có trong danh sách.

## Tiêu chí chấp nhận

- [ ] R5.3 (RB14): gán vai trò làm người nhận giữ hai vế một luật → 409 nêu luật và id người giữ; giao dịch lùi.
- [ ] R6.1 (RB15): người giữ `approvals.decide` mức `workspace` đề xuất vai trò có khóa đó mức `tenant` → 403 `rbac_escalation` kèm khóa; gỡ người nhận khỏi quyền mình không giữ → 403.
- [ ] R6.2 (RB15): cùng các thao tác bằng SQL thô dưới `dw_app` (có và không có `app.user_id`) → 23514; gỡ lời gọi `platform.rbac_refusals` khỏi từng trigger → test SQL thô đỏ trong khi test qua service vẫn xanh.
- [ ] R6.3 (RB16): người giữ `platform.roles.bind` đề xuất gán `member` dù không giữ khóa của nó → nhận; gán vai trò có khóa `critical` mình không giữ → 403.
- [ ] R6.4 (RB17): tự đề xuất gán cho mình → 403 `rbac_self_assignment`; xác nhận đề xuất gán cho chính mình → 403; SQL thô với `app.user_id` là người nhận → 23514.
- [ ] R6.5 (RB18): đưa `platform.admin` vào vai trò hay gán `platform_admin` → 422 `rbac_not_grantable`; SQL thô → 23514.
- [ ] R6.6 (RB19): xóa, đổi khóa `member`, sửa quyền `tenant_owner` → 409 `role_is_system` qua API, 23514 qua SQL thô.
- [ ] R6.7 (RB20): gỡ gán `tenant_owner` cuối, xóa membership, thành viên công ty hay người dùng của chủ sở hữu công ty cuối cùng → 409 `last_owner`, không đổi gì; hai quản trị đồng thời gỡ hai chủ sở hữu cuối → đúng một bị từ chối (test đồng thời).
- [ ] R7.1 (RB21): mutation nới quyền (tạo vai trò, thêm khóa, gán vai trò, gán `member` khi mời) trả 202 và chưa đổi gì; người thứ hai xác nhận → đổi, một audit `.confirmed` và một audit thay đổi.
- [ ] R7.1 (RB32): `PUT .../permissions` vừa bỏ một khóa vừa thêm một khóa → 202 đề xuất, quyền chưa đổi; nâng mức `workspace` lên `tenant` → 202; phân loại thay đổi trộn là chỉ siết → test đỏ.
- [ ] R7.2 (RB21): người đề xuất tự xác nhận → 409 `conflict` với `details.reason_code` `second_person_required`; gỡ `ck_role_change_requests_second_person` và kiểm của service → test đỏ.
- [ ] R7.3 (RB22): tenant chỉ một người giữ `platform.roles.write` → thay đổi nới quyền trả 409 `conflict` với `details.reason_code` `no_checker_available`, không dòng đề xuất; cùng tenant gỡ một gán vai trò không phải chủ sở hữu cuối → 200.
- [ ] R7.4 (RB23): xác nhận ở `expires_at` cộng 1 giây → 409 `conflict` với `details.reason_code` `proposal_expired`; ở `expires_at` trừ 1 giây → nhận.
- [ ] R7.5 (RB21): SQL thô dưới `dw_app` ghi gán vai trò mới không mang `app.role_change_id`, hay mang đề xuất do chính `app.user_id` đề xuất → 23514; SQL thô gỡ gán vai trò có `app.user_id` → nhận; gỡ nhánh kiểm đề xuất khỏi trigger → đỏ.
- [ ] R7.6 (RB32): gỡ gán vai trò, bỏ một khóa hay hạ mức một khóa trong vai trò → 200, áp ngay, đúng một audit, không dòng đề xuất; xóa mềm một vai trò không còn người giữ → 200, áp ngay, đúng một audit `platform.role.delete`, không dòng đề xuất; vai trò còn người giữ → 409 `role_in_use`; SQL thô dưới `dw_app` đặt lại `deleted_at` về NULL không mang đề xuất → 23514; gỡ gán `tenant_owner` cuối vẫn 409 `last_owner`.
- [ ] R7.7 (RB36): `dw_app` DELETE một đề xuất của công ty `active` → 23514, dòng còn; cùng lệnh khi công ty `offboarding` → xóa được; offboarding một công ty có một đề xuất `proposed` và một đề xuất `confirmed` → lane `offboarding` xuất mỗi dòng một lần rồi xóa hết, dòng của công ty khác còn nguyên, test phủ offboarding (studio-skeleton:R4.3) xanh với `platform.role_change_requests` không có trong `STUDIO_EXCLUSIONS`; gỡ phép kiểm DELETE khỏi trigger → test đỏ.
- [ ] R8.1: `GET /api/v1/admin/roles` trả đủ trường; `assignable_by_me` bằng đúng kết quả `platform.rbac_refusals` cho cùng người gọi (test so sánh).
- [ ] R8.2 (RB24): người không có `platform.roles.write` gọi thẳng `PUT /api/v1/admin/roles/{role_id}/permissions`, `POST /api/v1/admin/roles` → 403, không đề xuất.
- [ ] R8.3 (RB25): đề xuất bị 409 → không audit; mỗi audit chỉ có id và mã (test quét `details` không có `@` hay tên).
- [ ] R8.4 (RB25): gửi lại cùng `Idempotency-Key` và thân → cùng kết quả, một audit.
- [ ] R8.5 (RB26): `PUT .../permissions` với `If-Match` cũ → 412 `precondition_failed`, không dòng đề xuất, quyền không đổi; bỏ so `If-Match` → test đỏ.
- [ ] R8.6 (RB27): ghi `permission_set_keys` khác rỗng hay `role_keys` chứa `member` → 23514 `ck_memberships_legacy_role_columns`.
- [ ] R8.7 (RB26): vai trò đổi `version` sau lúc đề xuất, rồi người thứ hai xác nhận → 409 `conflict` với `details.reason_code` `proposal_stale`, quyền không đổi; không route nào của ticket này trả `stale_version`.
- [ ] R8.8 (RB26): `PATCH /api/v1/admin/roles/{role_id}` không có `If-Match` → 428 `precondition_required`, không ghi gì.
- [ ] R3.16 (RB42): người có `platform_admin` và không khóa nào gọi `POST /api/v1/admin/roles`,
      `POST /api/v1/admin/roles/{role_id}/assignments` và `POST /api/v1/admin/role-changes/{request_id}/confirm` → 403,
      0 dòng đổi; bỏ danh sách route khỏi kiểm vượt → route vai trò cho qua, test đỏ.
- [ ] G2: `test_platform_admin_bypasses_scopes` xanh trước và sau cắt chuyển, trên một route không thuộc R3.16.
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
- `docs/adr/0012-a-sod-waiver-takes-two-people.md:26-36`; spec: R7.
- `docs/adr/0108-one-error-envelope-and-caller-bound-idempotency.md:71-74`; spec: R8.5, R8.8.
- ADR-0104 (Accepted) mục 6; ADR-0012 (Accepted); brief B3 mục 1.5 và ticket 06, 08, 13.

## Comments

- 2026-10-23 (agent): DO-32.1 và phạm vi D11 đã có lời đáp (Đạt và người đặt yêu cầu, 23/10/2026); Status về needs-triage. Thêm R7.6 (siết một người), R8.7, R8.8 (ETag theo ADR-0108 (Accepted)), cạnh Blocked by tới app-standards/01, /02, /03.
- 2026-10-24 (agent): Đạt quyết ngày 24/10/2026: xóa mềm vai trò là thay đổi chỉ siết, một người cộng audit (D11); mã hai người là 409 `conflict` với `details.reason_code`; vai trò đổi `version` giữa đề xuất và xác nhận trả `proposal_stale`; loại đề xuất bỏ `role_delete` và `assignment_revoke` vì không còn thay đổi nào đi qua đề xuất với hai loại đó.
- 2026-10-24 (agent): Điều kiện tiên quyết FOG-49 (Đạt, 24/10/2026): người giữ dw-proterial chuyển dw-proterial khỏi `memberships.role_keys` trước khi bước 9 khóa cột; ticket này chờ điều kiện đó ngoài Blocked by vì nó không phải một ticket của area.
- 2026-10-24 (agent): vòng sửa 4: câu INSERT của bước 1 nêu mọi cột NOT NULL của danh mục, `tenant_grantable` của ticket 02 gồm (`C:custom-objects/02~tenant-rbac/02`); ticket này đã chờ ticket 02 nên Blocked by không đổi.
- 2026-10-24 (agent): vòng sửa 4, lượt bốn: bước 4 thêm index `(tenant_id, role_id)` của `platform.role_change_requests` cho FK tới vai trò, vì index danh sách không dẫn bằng hai cột đó (CLAUDE.md, Data model rules; Quyết định 24/10/2026 của spec).
- 2026-10-24 (agent): bước 4 cấp DELETE cho `dw_app` trên `platform.role_change_requests` cùng trigger `platform.guard_role_change_request()` chỉ cho xóa khi công ty ở `offboarding`, vì lane offboarding chỉ xóa bảng mà `dw_app` có DELETE; tiêu chí mới R7.7 (RB36) mang ca âm của công ty `active` và lượt xóa (CLAUDE.md, Data model rules; Quyết định 24/10/2026 của spec).
- 2026-10-25 (agent): lượt h, theo H-2 (foundations-hardening): bước xóa `platform.role_change_requests` là bước mặc định
  của sổ bước xóa, thứ tự suy từ `pg_constraint`, thay câu về `_ORDERED_FIRST`; không đổi gì khác.
- 2026-10-26 (agent): áp Q-h7 của Đạt (theo khuyến nghị): bước 10 và tiêu chí R3.16 (RB42); G2 chỉ còn đúng cho route
  không thuộc R3.16. Không thêm cạnh.
