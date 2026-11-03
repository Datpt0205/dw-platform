# 03 — Chống leo thang quyền và API quản trị vai trò, gán vai trò, audit

Status: needs-triage
Blocked by: 02, .claude/plans/studio/app-standards/issues/01-vo-loi-problem-json.md, .claude/plans/studio/app-standards/issues/02-khoa-chong-lap-gan-nguoi-goi.md, .claude/plans/studio/app-standards/issues/03-quy-uoc-api-danh-sach-va-sua.md
Area: studio
Yêu cầu: R3.3, R5.3, R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7, R7.1, R7.2, R7.3, R7.4, R7.5, R7.6, R7.7, R7.8, R8.1, R8.2, R8.3, R8.4, R8.5, R8.6, R8.7, R8.8, R3.16, G2, RB8, RB14, RB15, RB16, RB17, RB18, RB19, RB20, RB21, RB22, RB23, RB24, RB25, RB26, RB27, RB32, RB36, RB42, RB43

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
   `(reason_code, permission_key, depth)`: luật giữ quyền qua cùng phép so của `platform.grants_cover` (ticket 02);
   `platform.roles.bind` phủ vai trò không có khóa `critical` (DO-32.1; ticket 04 thêm vào phép so vai trò mang `fld.*`
   trên trường nhạy cảm); tự gán; vai trò hệ thống; khóa `tenant_grantable = false` và vai `platform_admin`. Neo của luật
   giữ quyền: với gán hay gỡ vai trò, workspace của gán đó; với thêm, nâng, bỏ hay hạ một khóa trong vai trò, workspace
   của từng gán hiện có của vai trò đó (người làm phải phủ ở mọi neo), và với vai trò chưa ai giữ, người làm giữ khóa ở
   mức bằng hoặc rộng hơn ở một neo bất kỳ, vì lần gán sau kiểm lại neo của nó (R6.1). Service gọi trước khi ghi (403 hay
   422 với `details.reason_code` và danh sách khóa); trigger BEFORE INSERT, UPDATE, DELETE trên
   `platform.tenant_roles`, `platform.tenant_role_permissions` và `platform.role_assignments` gọi cùng hàm, SQLSTATE
   23514, tên `rbac_refusals_<bảng>`; INSERT trên `platform.tenant_roles` là tạo vai trò, một ghi nới quyền (R7.1, R7.5).
   Người làm là `app.user_id`; ghi của `dw_app` thiếu nó bị từ chối; `dw_provisioner`, `dw_migrator` miễn theo
   `session_user` (tự audit); chỉ tenant ở `offboarding` hay `offboarded` miễn (lượt xóa của offboarding), còn tenant
   `setup` hay `locked` không miễn, vì ADR-0104 (Accepted) mục 6 áp hàm cho mọi người ghi trừ hai vai đó (R6.2); hàm lấy
   `FOR SHARE` trên gán vai trò của người làm, như `f381f1694395` làm với miễn trừ. Trigger tài khoản dịch vụ của
   org-and-principals/03 nằm trên cùng hai bảng mà không chờ ticket này (OPS-b cạnh 11, Quyết định 23/10/2026 của spec):
   thứ tự bắn theo bảng chữ cái của tên là chủ ý, và test catalog của ticket này chỉ khẳng định trigger `rbac_refusals_*`.
3. **Chủ sở hữu công ty cuối cùng.** Trigger AFTER `ck_role_assignments_last_owner` trên DELETE, UPDATE của
   `platform.role_assignments`, DELETE của `platform.memberships`, DELETE và UPDATE `status` của
   `platform.tenant_members`, DELETE của `platform.users`: tenant `active` hay `locked` phải còn ít nhất một chủ sở hữu
   `active`, đếm bằng `platform.active_tenant_owners` (ticket 02), không phép đếm thứ hai, sau khi khóa dòng
   `platform.tenants` `FOR UPDATE` như `complete_tenant_setup` của ticket 02, nên hai giao dịch gỡ hai chủ sở hữu cuối
   chạy lần lượt; cascade cũng tính. Tenant `setup` giữ luật riêng của R3.10, tenant `offboarding`, `offboarded` không bị
   xét. Gán `tenant_owner` có `expires_at` → 23514.
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
   `ck_role_change_requests_required_permission CHECK (required_permission = CASE WHEN kind = 'assignment_grant' THEN 'platform.roles.bind' ELSE 'platform.roles.write' END)`,
   `proposed_by uuid NOT NULL`, `proposed_at timestamptz NOT NULL DEFAULT now()`,
   `expires_at timestamptz NOT NULL`, `ck_role_change_requests_expiry CHECK (expires_at = proposed_at + interval '7 days')`,
   `status text NOT NULL CHECK (status IN ('proposed','confirmed','withdrawn'))`, `confirmed_by uuid NULL`,
   `decided_at timestamptz NULL`, `ck_role_change_requests_second_person CHECK (confirmed_by IS NULL OR confirmed_by <> proposed_by)`;
   FK `(tenant_id, role_id)` tới `platform.tenant_roles` `ON DELETE CASCADE`; index `(tenant_id, status, proposed_at, id)`
   cho danh sách và `(tenant_id, role_id)` cho FK tới vai trò. `proposed_by`, `confirmed_by` là id người làm như
   `actor_id` của audit, không khóa ngoại, để dòng còn làm hồ sơ khi người dùng bị xóa. RLS tenant; `dw_app` SELECT,
   INSERT, UPDATE chỉ trên `status`, `confirmed_by`, `decided_at`, và DELETE chỉ dùng được ở lượt xóa của offboarding.
   Trigger `platform.guard_role_change_request()` BEFORE INSERT, UPDATE, DELETE, SQLSTATE 23514, giữ máy trạng thái của
   đề xuất như ADR-0012 (Accepted) giữ miễn trừ: INSERT chỉ ở `proposed`, `confirmed_by` và `decided_at` NULL, và với
   `dw_app` có `proposed_by` bằng `app.user_id` và `proposed_at` bằng `now()`; UPDATE chỉ từ `proposed` sang `confirmed` (`confirmed_by` bằng
   `app.user_id`, `now() < expires_at`) hay sang `withdrawn` (`confirmed_by` NULL), `decided_at` là `now()`, không cột
   nào khác đổi, và dòng `confirmed` hay `withdrawn` không đổi nữa (R7.8); DELETE bị từ chối khi
   `platform.tenants.status` của công ty khác `offboarding` (spec R7.7), cùng hình với `platform.guard_control_switch()`
   của agent-lifecycle (agent-lifecycle:R7.5); khẳng định quyền trong `test_privileges.py`. Hết hạn đọc từ `expires_at`,
   không có trạng thái thứ hai; dòng giữ làm hồ sơ tới khi offboarding xóa tenant, và lane offboarding xuất rồi xóa
   bảng dưới test phủ offboarding (studio-skeleton:R4.3) bằng bước mặc định của sổ bước xóa (foundations-hardening:R11.4);
   hai khóa ngoại của bảng đều `ON DELETE CASCADE` nên thứ tự suy từ `pg_constraint` không ràng nó, và ticket này không
   đăng ký bước nào.
    - Mutation nới quyền ở bước 5 và 6 ghi một đề xuất (202 kèm `id`) sau khi `platform.rbac_refusals` cho người đề xuất
      không trả gì; `platform.checker_candidates(tenant, required_permission, người đề xuất)` (ticket 02) không trả ai →
      409 `conflict` với `details.reason_code` `no_checker_available`, không ghi. `role_id` là vai trò được sửa hay được
      gán; `role_create` để `role_id` NULL và đặt id của vai trò mới vào `payload` `role_id` lúc đề xuất. `base_version`
      là `version` của vai trò lúc đề xuất: từ `If-Match` với mutation trên vai trò đã có, đọc dưới khóa dòng với
      `assignment_grant`, NULL với `role_create`.
    - `POST /api/v1/admin/role-changes/{request_id}/confirm` (`required_permission` của đề xuất, `Idempotency-Key`):
      khóa dòng đề xuất `FOR UPDATE`, rồi theo thứ tự: không thấy dòng dưới RLS → 404 `not_found`; người xác nhận không
      giữ `required_permission` → 403 `permission_denied`; người khác người đề xuất (409 `conflict`,
      `details.reason_code` `second_person_required`); dòng còn `proposed` (409 `conflict`, `proposal_closed`), chưa
      quá `expires_at` (409 `conflict`, `proposal_expired`); người đề xuất còn là thành viên `active` giữ
      `required_permission` và, sau khi khóa dòng vai trò `FOR UPDATE`, `base_version` còn đúng (409 `conflict`,
      `proposal_stale`, R8.7); đặt
      `set_config('app.role_change_id', ..., true)`, áp thay đổi trong giao dịch của người duyệt, nên trigger bước 2
      kiểm chính người duyệt, rồi UPDATE dòng sang `confirmed`. `second_person_required`, `no_checker_available` và
      `proposal_expired` là `details.reason_code` dùng chung với cơ chế hai người của tenant-config, cùng hình 409
      `conflict` (Quyết định 23/10/2026 và 24/10/2026 của spec).
    - `POST /api/v1/admin/role-changes/{request_id}/withdraw` (người đề xuất hay người giữ `required_permission`; cùng
      khóa dòng; dòng đã đóng → 409 `conflict`, `proposal_closed`); `GET /api/v1/admin/role-changes`
      (`platform.roles.read`; đề xuất `proposed` chưa quá `expires_at`, phân trang theo index trên).
    - Trigger bước 2 từ chối ghi không chỉ siết quyền của `dw_app` khi `app.role_change_id` không trỏ tới đề xuất
      `proposed`, chưa hết hạn, cùng tenant, có `proposed_by` khác `app.user_id`, hay khi lần ghi không phải lần ghi mà
      loại đề xuất cho phép trên đúng vai trò nó nêu (R7.5): `role_create` chỉ INSERT `platform.tenant_roles` với `id`
      bằng `payload` `role_id` và INSERT `platform.tenant_role_permissions` của vai trò đó; `role_update` chỉ UPDATE
      `name`, `description` của `role_id`; `role_permissions` chỉ INSERT, UPDATE, DELETE
      `platform.tenant_role_permissions` của `role_id`; `assignment_grant` chỉ INSERT `platform.role_assignments` với
      `role_id` và `membership_id` của đề xuất. Trigger đọc đề xuất qua một hàm SECURITY DEFINER hẹp lọc tường minh
      `tenant_id = app.tenant_id`, nên phép lọc đó là lớp duy nhất giữ đề xuất của công ty khác ở đây (tiêu chí R3.3).
      UPDATE chỉ đổi `version`, `updated_at` (trigger tăng phiên bản của bước 5 và `touch_updated_at`) là trung tính và
      trigger bước 2 cho qua; mọi phép so "không đổi cột nào khác" bỏ qua hai cột đó; ghi chỉ siết (DELETE trên `platform.role_assignments` hay `platform.tenant_role_permissions`, UPDATE hạ
      `depth`, UPDATE trên `platform.tenant_roles` chỉ đặt `deleted_at` từ NULL mà không đổi cột nào khác) chỉ cần
      `app.user_id` và qua `platform.rbac_refusals`; UPDATE đặt `deleted_at` về NULL không phải ghi chỉ siết. Ngoại lệ
      duy nhất là gán vai trò cho principal của DW ở bước 11.
5. **Route vai trò** (mọi mutation có `Idempotency-Key`, phong bì lỗi của ADR-0108 (Accepted)):
   `GET /api/v1/admin/roles` (`platform.roles.read`; `id`, `key`, `name`, `description`, `kind`, `is_system`,
   `template_key`, `holder_count`, `version`, `assignable_by_me`, `updated_at`), `GET /api/v1/admin/roles/{role_id}` (kèm
   `ETag: "<version>"`), `GET /api/v1/admin/roles/{role_id}/assignments`, `GET /api/v1/admin/role-templates` (chỉ lớp
   nền tảng), `POST /api/v1/admin/roles` (`platform.roles.write`; `from_template` hay `clone_of`),
   `PATCH /api/v1/admin/roles/{role_id}` (`name`, `description`), `PUT /api/v1/admin/roles/{role_id}/permissions`
   (`{permissions: [{key, depth}]}`), `DELETE /api/v1/admin/roles/{role_id}` (xóa mềm, một người cộng audit
   `platform.role.delete`, R7.6; 409 `role_in_use` kèm số người giữ, 409 `role_is_system`). Mutation trên vai trò đã có so `If-Match` mạnh với `version` theo app-standards/03
   (ADR-0108 (Accepted) mục 3): lệch → 412 `precondition_failed` (R8.5), thiếu → 428 `precondition_required` (R8.8); đề
   xuất ghi `base_version` từ `If-Match`. `version` tăng ở cơ sở dữ liệu, vì `b5677d345bc1` tạo cột mà không có người
   tăng nào: trigger BEFORE UPDATE trên `platform.tenant_roles` tăng `version` khi một cột khác `version`, `updated_at`
   đổi và câu lệnh không tự đặt `version`, và trigger AFTER INSERT, UPDATE, DELETE trên
   `platform.tenant_role_permissions` tăng `version` của vai trò cha, nên mọi lần áp, kể cả thay đổi chỉ siết một người
   và SQL thô, đổi ETag và làm đề xuất cũ thành `proposal_stale`; Merge Patch không đổi giá trị nào không tăng `version`
   (app-standards:R3.16).
   `GET /api/v1/admin/permissions` thêm `allowed_depths` và `max_grantable_depth` tính bằng SQL từ quyền của người gọi;
   `assignable_by_me` tính bằng `platform.rbac_refusals`, không bản sao, với người nhận giả định khác người gọi ở
   workspace đang làm việc của người gọi.
6. **Gán vai trò.** `PUT /api/v1/admin/members/{user_id}/memberships`, `POST /api/v1/admin/members`,
   `POST /api/v1/admin/invitations`, `PUT /api/v1/admin/members/{user_id}/permission-sets` đi qua một
   `RoleAssignmentService`. Phần membership và thành viên giữ khóa của route hôm nay (`platform.members.write`); phần vai
   trò cần thêm `platform.roles.bind` (R8.2), và mỗi gán hay gỡ qua `platform.rbac_refusals`. Đơn vị là một gán (một
   membership, một vai trò): mỗi gỡ áp ngay cộng một audit (bước 4); mỗi gán thêm là một đề xuất `assignment_grant` với
   `role_id` và `payload` `{membership_id, workspace_id, user_id}`; một request có ít nhất một đề xuất trả 202 với
   `applied` (các gán đã gỡ) và `proposals` (id đề xuất), một request chỉ gỡ trả 200 như hôm nay. Lời mời và
   `POST /api/v1/admin/members` ghi ngay người dùng `invite:`, thành viên công ty `invited`, membership và thư mời như
   hôm nay, vì membership không vai trò không cho quyền nào (R2.5); vai trò của người được mời, kể cả `member`, là đề
   xuất, nên người được mời đăng nhập trước lần xác nhận thì không giữ quyền nào; route trả 202 kèm `proposals`. Nghỉ
   hưu `forbid_escalation`, `is_administrative` (`membership_admin.py:53-65`) và bản chép ở `admin_console.py:318-326`
   cùng chỗ dùng ở `tenant_members.py:238-239` và `digital_workers.py:92`, `:397` (bước 11); `plan_memberships` giữ
   nguyên vai trò người gọi không quản được. Gán vai trò cho membership của principal một DW trả 409
   `dw_principal_roles_fixed` như hôm nay (digital-worker:R1.17).
7. **Lỗi.** 23514 của trigger dịch sang 403 `rbac_escalation`, `rbac_self_assignment`; 422 `rbac_not_grantable`; 409
   `conflict` với `role_is_system`, `role_in_use`, `last_owner`, `role_limit_reached`, `second_person_required`,
   `no_checker_available`, `proposal_expired`, `proposal_stale`, `proposal_closed`, `ck_roles_sod_memberships` (tên
   luật, tối đa 20 người giữ); chỉ qua `details.reason_code`, không thêm mã vào `ErrorCode`. 412 `precondition_failed`
   và 428 `precondition_required` là mã của `ErrorCode` mà app-standards/01 thêm (ADR-0108 (Accepted) mục 1).
8. **Audit cùng giao dịch:** `platform.role_change.proposed`, `.confirmed`, `.withdrawn`; khi áp:
   `platform.role.create`, `.update`, `.permissions_set` (thêm, bỏ, đổi mức), `.delete`,
   `platform.role_assignment.grant`, `.revoke`. `details`: id đề xuất, id và khóa vai trò, id workspace, id người dùng;
   không email, không tên. Nhãn tiếng Việt của mỗi hành động mới vào `configs/copy/audit_actions.d/tenant-rbac.yaml`.
9. **Cắt chuyển.** Ticket chờ ticket 05 (FOG-49, Đạt 24/10/2026: người giữ dw-proterial đã chuyển dw-proterial khỏi
   việc ghi `memberships.role_keys` và `permission_set_keys`). Một revision, theo đúng thứ tự: bỏ trigger chép của ticket
   02; xóa trắng hai cột (`role_keys` chỉ giữ `platform_admin` nếu có), vì xóa khi trigger chép còn thì nó gỡ gán vai
   trò (Comments của ticket 02, HIGH 12); rồi thêm `ck_memberships_legacy_role_columns`:
   `permission_set_keys = '[]'::jsonb` và `role_keys` chỉ được rỗng hay `["platform_admin"]` (giá trị script nền tảng ghi,
   giữ tới dòng W2). Mọi người ghi hai cột chuyển trong ticket này (`adapters/persistence/`): `membership_admin.py:92-130`,
   `tenant_members.py:263-268`, `admin_console_repo.py:248` (bước 6); `digital_workers_repo.py:146` (bước 11);
   `identity_provisioning.py:266`, đường `auto_provision_default_membership` của tenant demo, ghi membership không vai
   trò, vì gán `member` cần hai người, và `default_role` bỏ; `scripts/grant_platform_admin.py:30` ghi đúng
   `["platform_admin"]`, bỏ `org_admin`, vì đường vượt của G2 đã phủ nó; `seed_env.py:250`, `scripts/eval_wf_ai.py:80`
   và mọi fixture test ghi hai cột chuyển sang `dw_platform.testing.rbac.assign` dưới `dw_migrator`. Người đọc:
   directory, trang thứ bậc và `tenant_members.py:76`, `:126` đọc tên vai trò từ gán vai trò. Trang thành viên
   (`apps/web/components/admin/members-manager.tsx:34-39`) lấy vai trò từ `GET /api/v1/admin/roles`, khóa vai trò
   `assignable_by_me = false` kèm lý do, hiện "Chờ người thứ hai xác nhận" khi nhận 202; xóa `BASE_GRANTABLE_ROLES`,
   `ADMIN_GRANTABLE_ROLES`. `make generate-contracts`; client trong `packages/typescript/api-client`.
10. **Đường vượt không mở route vai trò** (spec R3.16; Đạt, Q-h7): kiểm vượt `platform_admin` của G2 bỏ qua một danh
    sách route khai một lần cạnh router (`/api/v1/admin/roles`, `/api/v1/admin/role-changes`,
    `/api/v1/admin/members/{user_id}/memberships`, `/api/v1/admin/members/{user_id}/permission-sets`,
    `POST /api/v1/admin/members`, `/api/v1/admin/invitations` và route con), nên ở đó người gọi chỉ qua khi tự giữ khóa
    của route qua `platform.effective_grants`; test so danh sách với router, đỏ khi một route vai trò mới không có trong
    danh sách.
11. **Principal của DW** (ADR-0104 (Accepted), Amendments 2026-11-03). `DigitalWorkerService.create` ghi dòng DW `draft`
    trước membership của principal, rồi ghi `platform.role_assignments` cho từng khóa của `role_keys` (khóa vai trò của
    tenant, không vai mẫu) trong cùng giao dịch, không đề xuất: trigger bước 2 nhận lần gán không đề xuất này chỉ khi
    membership là của `principal_user_id` của một DW ở `draft` có `created_by` bằng `app.user_id`, người dùng đó là
    `kind = 'service'` có dòng `platform.service_principals`, và dòng DW được tạo trong chính giao dịch này
    (`xmin` của dòng DW bằng `pg_current_xact_id()::xid`; chạy thử trên PostgreSQL 16 trước khi dựa vào, failure-modes #4), và `platform.rbac_refusals` vẫn chạy. Người thứ hai là lần
    `draft→operating` của digital-worker:R1.9: `_second_person` (`digital_workers.py:424-438`) thay phép so `scopes` của
    workspace đang làm việc bằng `platform.grants_cover(tenant, người gọi, principal)` trên quyền hiệu lực. `_check_roles` đọc vai trò của tenant: khóa vai trò lạ →
    `role_unknown`, vai trò có khóa `risk = 'critical'` hay là `tenant_owner` → `role_not_allowed_for_service`
    (digital-worker:R1.15), luật giữ quyền của `platform.rbac_refusals` thay `forbid_escalation` và trả
    `grants_not_covered` như digital-worker:R1.10. `platform.dw_principal_roles_fixed()` chuyển sang
    `platform.role_assignments`: INSERT cho principal của DW không ở `draft` → 23514
    `ck_memberships_dw_principal_roles_fixed` với mọi người ghi trừ `dw_migrator`; gỡ vẫn được (digital-worker:R1.17).

## Tiêu chí chấp nhận

- [ ] R3.3 (RB8): người gọi của tenant A xác nhận, rút `request_id` của tenant B, đọc `GET /api/v1/admin/roles/{role_id}/assignments` với vai trò của B, hay gửi `PUT /api/v1/admin/members/{user_id}/memberships` với người của B → 404, 0 dòng đổi; `GET /api/v1/admin/role-changes` của A không có đề xuất của B; SQL thô dưới `dw_app` với `app.tenant_id` A đặt `app.role_change_id` là đề xuất của B rồi INSERT `platform.tenant_roles` với `id` là `payload` `role_id` của một đề xuất `role_create` của B → 23514; gỡ phép lọc `tenant_id` khỏi hàm đọc đề xuất → test SQL đỏ.
- [ ] R5.3 (RB14): gán vai trò làm người nhận giữ hai vế một luật → 409 nêu luật và id người giữ; giao dịch lùi.
- [ ] R6.1 (RB15): người giữ `approvals.decide` mức `workspace` đề xuất vai trò có khóa đó mức `tenant` → 403 `rbac_escalation` kèm khóa; gỡ người nhận khỏi quyền mình không giữ → 403; người giữ khóa mức `workspace` ở A thêm khóa đó vào vai trò đang gán ở B → 403.
- [ ] R6.2 (RB15): cùng các thao tác bằng SQL thô dưới `dw_app` (có và không có `app.user_id`) → 23514, ở công ty `active`, `locked` và `setup`; cùng lệnh ở công ty `offboarding` → nhận; gỡ lời gọi `platform.rbac_refusals` khỏi từng trigger → test SQL thô đỏ trong khi test qua service vẫn xanh; nới miễn trừ thành "không `active`" → ca `locked` đỏ.
- [ ] R6.3 (RB16): người giữ `platform.roles.bind` đề xuất gán `member` dù không giữ khóa của nó → nhận; gán vai trò có khóa `critical` mình không giữ → 403.
- [ ] R6.4 (RB17): tự đề xuất gán cho mình → 403 `rbac_self_assignment`; xác nhận đề xuất gán cho chính mình → 403; SQL thô với `app.user_id` là người nhận → 23514.
- [ ] R6.5 (RB18): đưa `platform.admin` vào vai trò hay gán `platform_admin` → 422 `rbac_not_grantable`; SQL thô → 23514.
- [ ] R6.6 (RB19): xóa, đổi khóa `member`, sửa quyền `tenant_owner` → 409 `role_is_system` qua API, 23514 qua SQL thô.
- [ ] R6.7 (RB20): gỡ gán `tenant_owner` cuối, xóa membership, thành viên công ty hay người dùng của chủ sở hữu công ty cuối cùng → 409 `last_owner`, không đổi gì, ở công ty `active` và `locked`; hai quản trị đồng thời gỡ hai chủ sở hữu cuối → đúng một bị từ chối (test đồng thời); bỏ khóa dòng tenant → test đồng thời đỏ.
- [ ] R7.1 (RB21): mutation nới quyền (tạo vai trò, thêm khóa, gán vai trò, gán `member` khi mời) trả 202 và chưa đổi quyền nào (người được mời có membership mà `GET /api/v1/me` không có khóa nào); người thứ hai xác nhận → đổi, một audit `.confirmed` và một audit thay đổi; người chỉ giữ `platform.roles.bind` xác nhận đề xuất `role_permissions`, hay người chỉ giữ `platform.roles.write` xác nhận đề xuất `assignment_grant` → 403, không đổi gì.
- [ ] R7.1 (RB32): `PUT .../permissions` vừa bỏ một khóa vừa thêm một khóa → 202 đề xuất, quyền chưa đổi; nâng mức `workspace` lên `tenant` → 202; phân loại thay đổi trộn là chỉ siết → test đỏ; `PUT /api/v1/admin/members/{user_id}/memberships` gỡ vai trò A và thêm vai trò B → 202, A đã gỡ, B là một đề xuất.
- [ ] R7.2 (RB21): người đề xuất tự xác nhận → 409 `conflict` với `details.reason_code` `second_person_required`; gỡ `ck_role_change_requests_second_person` và kiểm của service → test đỏ.
- [ ] R7.3 (RB22): tenant chỉ một người giữ `platform.roles.write` → thay đổi nới quyền trả 409 `conflict` với `details.reason_code` `no_checker_available`, không dòng đề xuất; cùng tenant gỡ một gán vai trò không phải chủ sở hữu cuối → 200.
- [ ] R7.4 (RB23): xác nhận ở `expires_at` cộng 1 giây → 409 `conflict` với `details.reason_code` `proposal_expired`; ở `expires_at` trừ 1 giây → nhận.
- [ ] R7.5 (RB21): SQL thô dưới `dw_app` ghi gán vai trò mới hay INSERT `platform.tenant_roles` không mang `app.role_change_id`, hay mang đề xuất do chính `app.user_id` đề xuất, hay mang đề xuất của vai trò X mà ghi vai trò Y, hay mang đề xuất `role_update` của X mà INSERT gán X hay thêm khóa vào X → 23514; INSERT đề xuất có `proposed_by` khác `app.user_id` hay ở `confirmed`, UPDATE đề xuất `confirmed` về `proposed` → 23514; SQL thô gỡ gán vai trò có `app.user_id` → nhận; gỡ nhánh kiểm đề xuất hay nhánh khớp vai trò khỏi trigger → đỏ.
- [ ] R7.5 (RB21): tạo DW với vai trò `approver` của tenant → 201, principal có gán vai trò, không dòng đề xuất; người tạo tự `draft→operating` → 409 `second_person_required` (digital-worker:R1.9); SQL thô dưới `dw_app` gán thêm vai trò cho principal của DW `operating`, hay cho principal của DW `draft` bởi người không phải người tạo → 23514; SQL thô tạo một DW `draft` trỏ tới người dùng `human` rồi gán vai trò cho người đó, hay gán cho principal của một DW `draft` tạo ở giao dịch trước → 23514; mỗi ca khẳng định tên ràng buộc (`rbac_refusals_role_assignments` khác `ck_memberships_dw_principal_roles_fixed`), nên bỏ điều kiện `draft`, `created_by`, `kind` hay cùng giao dịch khỏi ngoại lệ → test đỏ; người thứ hai không giữ khóa của một vai trò đã gán cho principal → 403 `grants_not_covered`, đổi phép kiểm về `scopes` của workspace đang làm việc mà người đó có khóa ở workspace khác → test đỏ.
- [ ] R7.6 (RB32): gỡ gán vai trò, bỏ một khóa hay hạ mức một khóa trong vai trò → 200, áp ngay, đúng một audit, không dòng đề xuất, `version` của vai trò tăng một; xóa mềm một vai trò không còn người giữ → 200, áp ngay, đúng một audit `platform.role.delete`, không dòng đề xuất; vai trò còn người giữ → 409 `role_in_use`; SQL thô dưới `dw_app` đặt lại `deleted_at` về NULL không mang đề xuất → 23514; gỡ gán `tenant_owner` cuối vẫn 409 `last_owner`.
- [ ] R7.7 (RB36): `dw_app` DELETE một đề xuất của công ty `active` → 23514, dòng còn; cùng lệnh khi công ty `offboarding` → xóa được; offboarding một công ty có một đề xuất `proposed` và một đề xuất `confirmed` → lane `offboarding` xuất mỗi dòng một lần rồi xóa hết, dòng của công ty khác còn nguyên, test phủ offboarding (studio-skeleton:R4.3) xanh với `platform.role_change_requests` không có trong `STUDIO_EXCLUSIONS`; gỡ phép kiểm DELETE khỏi trigger → test đỏ.
- [ ] R7.8 (RB43): hai người khác người đề xuất xác nhận cùng một đề xuất đồng thời → đúng một lần áp, đúng một audit `.confirmed`, người kia 409 `conflict` với `details.reason_code` `proposal_closed`; xác nhận sau khi đề xuất đã rút → 409 `proposal_closed`, không đổi gì; người đề xuất bị `suspended` trước lần xác nhận → 409 `proposal_stale`; bỏ khóa dòng đề xuất hay điều kiện `status = 'proposed'` → test đồng thời đỏ.
- [ ] R8.1: `GET /api/v1/admin/roles` trả đủ trường; `assignable_by_me` bằng đúng kết quả `platform.rbac_refusals` cho cùng người gọi, người nhận giả định và workspace đang làm việc (test so sánh).
- [ ] R8.2 (RB24): người không có `platform.roles.write` gọi thẳng `PUT /api/v1/admin/roles/{role_id}/permissions`, `POST /api/v1/admin/roles` → 403, không đề xuất; người có `platform.members.write` mà không có `platform.roles.bind` gọi `PUT /api/v1/admin/members/{user_id}/memberships` thêm vai trò → 403, không đề xuất.
- [ ] R8.3 (RB25): đề xuất bị 409 → không audit; mỗi audit chỉ có id và mã (test quét `details` không có `@` hay tên).
- [ ] R8.4 (RB25): gửi lại cùng `Idempotency-Key` và thân → cùng kết quả, một audit.
- [ ] R8.5 (RB26): `PUT .../permissions` với `If-Match` cũ → 412 `precondition_failed`, không dòng đề xuất, quyền không đổi; bỏ so `If-Match` → test đỏ.
- [ ] R8.6 (RB27): ghi `permission_set_keys` khác rỗng hay `role_keys` chứa `member` → 23514 `ck_memberships_legacy_role_columns`.
- [ ] R8.7 (RB26): vai trò đổi `version` sau lúc đề xuất, rồi người thứ hai xác nhận → 409 `conflict` với `details.reason_code` `proposal_stale`, quyền không đổi; một người bỏ khóa K (chỉ siết, 200) giữa lúc đề xuất `PUT .../permissions` giữ K và lúc xác nhận → `proposal_stale`, K không trở lại; gỡ trigger tăng `version` trên `platform.tenant_role_permissions` → test đỏ; không route nào của ticket này trả `stale_version`.
- [ ] R8.8 (RB26): `PATCH /api/v1/admin/roles/{role_id}` không có `If-Match` → 428 `precondition_required`, không ghi gì.
- [ ] R3.16 (RB42): người có `platform_admin` và không khóa nào gọi `POST /api/v1/admin/roles`,
      `PUT /api/v1/admin/members/{user_id}/memberships`, `POST /api/v1/admin/invitations` và
      `POST /api/v1/admin/role-changes/{request_id}/confirm` → 403, 0 dòng đổi; bỏ danh sách route khỏi kiểm vượt →
      route vai trò cho qua, test đỏ.
- [ ] G2: `test_platform_admin_bypasses_scopes` xanh trước và sau cắt chuyển, trên một route không thuộc R3.16.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/application/membership_admin.py:53-65`; spec: R6.1.
- `packages/python/dw_platform/src/dw_platform/application/admin_console.py:318-326`; spec: R6.1.
- `packages/python/dw_platform/src/dw_platform/application/tenant_members.py:221-239`; spec: R6.1.
- `packages/python/dw_platform/src/dw_platform/application/digital_workers.py:375-397`; spec: R7.5.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/digital_workers_repo.py:146`; spec: R7.5.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:248-270`; spec: R8.6.
- `scripts/grant_platform_admin.py:30`; spec: R8.6, G2.
- `db/migrations/versions/be93e0c26a4c_platform_digital_workers.py:330-366`; spec: R7.5.
- `db/migrations/versions/b5677d345bc1_tenant_roles.py:97-121`; spec: R8.5, R8.7.
- `db/migrations/versions/b5677d345bc1_tenant_roles.py:455-519`; spec: R6.1, R6.7, R7.3.
- `db/migrations/versions/f381f1694395_platform_sod_waiver_second_person_and_.py:73-84`; spec: R6.2.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_session.py:23-27`; spec: R6.2, R7.5.
- `apps/api/src/dw_api/routes/v1/admin_console.py:256`; spec: R8.1.
- `apps/api/src/dw_api/routes/v1/admin_members.py:240`; spec: R7.1.
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
- 2026-11-03 (agent): checking-plan-readiness, builder check và boundary walk (ba subagent: builder, ranh giới 1-2,
  ranh giới 3-6), đọc ở `992bf74` trên code của ticket 02 (`bd8c607`). Ticket thêm một revision Alembic
  (`platform.role_change_requests`, hai khóa danh mục, các hàm và trigger, khóa cột cũ) và route (`/api/v1/admin/roles`
  và con, `/api/v1/admin/role-changes` và con, đổi phản hồi của bốn route gán vai trò), nên đủ hai phép kiểm. Script: hai
  lỗi ở ticket 02 (dòng Xong, ADR thiếu trạng thái), hai HIGH, đã sửa. Tìm thêm 2 CRITICAL, 9 HIGH; mọi cái sửa theo khuyến nghị ở
  spec (Quyết định 3/11/2026) và các bước 2-6, 8-11 ở trên; MEDIUM ghi dưới, chưa sửa.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): điều kiện FOG-49 thôi là câu "chưa xong thì không lên ready-for-agent"
  (dòng 24/10/2026 ở trên) đứng một mình: nó thành ticket 05 `ready-for-human`. Blocked by chỉ trỏ ngược
  (`scripts/check_plans.py`), nên ticket này không ghi 05 ở đó; nó giữ `needs-triage` dù gate ĐẠT, và lên
  `ready-for-agent` khi ticket 05 `resolved`, theo đúng câu của Đạt. Nếu sai thì: ticket 05 gộp lại thành điều kiện
  trong bước 9.
- 2026-11-03 (agent): MEDIUM của gate cho người dựng, chưa sửa. (M1) Hai đề xuất mở cho cùng một khóa vai trò hay cùng
  một gán: lần xác nhận thứ hai gặp `uq_tenant_roles_tenant_id_key` hay `uq_role_assignments_membership_id_role_id`;
  nên dịch sang 409 `conflict` chung của ADR-0108 (Accepted), không 500. (M2) `GET /api/v1/admin/roles` không phân trang
  vì R3.7 giới hạn 200 vai trò; nếu test của app-standards/03 đòi keyset thì ghi vào danh sách miễn trừ kèm lý do;
  `assignable_by_me` cho 200 vai trò nên tính trong một câu SQL, không 200 lần gọi, và đo P95 ở lúc đóng hàng
  (`latency.md`). (M3) `role_in_use` của DELETE mềm là phép kiểm của service, chạy đua được với một lần xác nhận gán vai
  trò đó; kết quả đóng (vai trò đã xóa mềm không cho quyền, R2.5), nhưng nên khóa dòng vai trò `FOR UPDATE` ở cả hai
  đường. (M4) SQL thô dưới `dw_app` của một người giữ các khóa mà không giữ `platform.roles.write` hay `bind` vẫn gỡ được
  gán hay bỏ được khóa (cơ sở dữ liệu chỉ giữ luật giữ quyền, khóa của route ở service); chấp nhận, vì chỉ siết. (M5) Gán
  `tenant_owner` qua API: luật giữ quyền chỉ cho người phủ mọi quyền tính động của nó, tức một `tenant_owner` khác, cộng
  người thứ hai; nên có một test, đường `.../org-admins` của người vận hành giữ nguyên. (M6) Khóa chống lặp sống 24 giờ,
  đề xuất 7 ngày: gửi lại sau 24 giờ ghi đề xuất thứ hai; M1 giữ lần xác nhận thứ hai. (M7) Danh sách route của bước 10
  không đến được `ScopeAuthorizationService.is_allowed` (nó không biết route); một dependency đánh dấu request là một
  cách, test so danh sách với router giữ nó. (M8) Ticket lớn (11 bước); cách chia giữ vì bước 9, 11 không tách sau được
  (dòng duyệt cách chia của spec). (M9) `digital-worker:R1.1` còn viết "membership với `role_keys`"; báo người gọi, ngoài
  thư mục này.
- 2026-11-03 (agent): bảng cặp với ticket không có đường phụ thuộc tới ticket này, đang dựng hay `ready-for-agent`:
  org-and-principals/04 — đầu chuỗi Alembic, `test_privileges.py`, `apps/api/src/dw_api/exception_handlers.py` (ticket
  này dịch 23514 sang lỗi); connections-and-vault/02 — đầu chuỗi Alembic, `test_rls_coverage.py`
  (`_TENANT_WIDE_ON_PURPOSE`), `test_privileges.py`, `test_offboarding_coverage.py`, `tables.py`,
  `apps/api/src/dw_api/settings.py` (ticket này bỏ `default_role`), `digital_workers_repo.py` (ticket này sửa `:146` và
  luồng tạo, ticket kia dùng `:548`). Mọi va chạm là thêm dòng cạnh nhau, không cùng một quyết định; ticket xong sau trỏ
  lại `down_revision` và gộp dòng. Không dựng song song với connections-and-vault/02 trong cùng cây (bốn tệp chung);
  với org-and-principals/04 được, mỗi bên kéo rebase trước khi đẩy.
- 2026-11-03 (agent): lượt xác nhận của gate (một subagent mới, chỉ đọc chỗ sửa): không CRITICAL mới; năm HIGH trong
  chính chỗ sửa đã sửa ngay (lần tăng `version` là UPDATE trung tính; mỗi loại đề xuất chỉ mở lần ghi của nó; ngoại lệ DW
  đòi người dùng `service`, dòng `platform.service_principals` và DW tạo cùng giao dịch; `draft→operating` so bằng
  `platform.grants_cover`; hàm đọc đề xuất lọc `tenant_id` tường minh để ca chéo tenant đỏ được) và ba MEDIUM (khóa dòng
  vai trò trước khi so `base_version`, `proposed_at = now()` lúc INSERT, test DW khẳng định tên ràng buộc). Script sau
  sửa: xem dòng kế.
- 2026-11-03 (agent): script sau sửa: 24 Đạt, 0 Không đạt, 0 cảnh báo. MEDIUM thêm (M10): `install_role_template`
  của ticket 02 tự sinh id (`gen_random_uuid()`), nên đường `from_template` của bước 5 cần truyền `payload` `role_id`
  vào nó để trigger khớp vai trò của đề xuất `role_create`.
- 2026-11-03 (agent): checking-plan-readiness ĐẠT; giữ `needs-triage` tới khi ticket 05 (FOG-49) `resolved`, rồi lên
  `ready-for-agent` không cần gate lại nếu nội dung không đổi.
