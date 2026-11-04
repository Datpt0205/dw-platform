# 03 — Chống leo thang quyền và API quản trị vai trò, gán vai trò, audit

Status: resolved (2026-11-05, main)
Blocked by: 02, .claude/plans/studio/app-standards/issues/01-vo-loi-problem-json.md, .claude/plans/studio/app-standards/issues/02-khoa-chong-lap-gan-nguoi-goi.md, .claude/plans/studio/app-standards/issues/03-quy-uoc-api-danh-sach-va-sua.md, .claude/plans/studio/org-and-principals/issues/03-tai-khoan-dich-vu-run-as.md
Area: studio
Yêu cầu: R3.3, R5.3, R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7, R7.1, R7.2, R7.3, R7.4, R7.5, R7.6, R7.7, R7.8, R8.1, R8.2, R8.3, R8.4, R8.5, R8.7, R8.8, R3.16, G2, RB8, RB14, RB15, RB16, RB17, RB18, RB19, RB20, RB21, RB22, RB23, RB24, RB25, RB26, RB32, RB36, RB42, RB43, RB48, RB49, RB50

## Mục tiêu

Quản trị viên công ty tạo, sửa, nhân bản, xóa mềm vai trò và gán vai trò qua API; mỗi thay đổi nới quyền do một người đề
xuất và một người khác xác nhận, thay đổi chỉ siết quyền do một người làm cộng audit (R7, D11: "đóng một người, mở hai
người"), không ai trao được quyền mình không giữ hay tự trao quyền, mỗi tenant luôn còn chủ sở hữu công ty (R6), mọi thay
đổi có audit cùng giao dịch, mutation theo ETag và `If-Match` (R8), mọi người ghi và người đọc
`memberships.role_keys`, `permission_set_keys` trong repo chuyển sang gán vai trò, và hai cột không còn là đường vòng
quanh hai người (R7.5) hay đường trao `platform_admin` (R6.2); khóa hai cột là ticket 06, chờ FOG-49. Gộp từ brief B3
ticket 06, 08. DO-32.1 đã quyết theo khuyến nghị (a) (Đạt, 23/10/2026): luật giữ quyền, quản trị viên tạo được quản
trị viên, `platform.roles.bind` gán vai trò không trọng yếu.

## Việc cần làm

1. **Khóa mới.** Migration thêm vào `platform.permissions`: `platform.roles.write` và `platform.roles.bind`, câu INSERT
   nêu mọi cột NOT NULL của danh mục (`label_vi`, `area`, `scope_kind` `tenant`, `risk` `critical`, `status`
   `active`, `owner_package`, `tenant_grantable` `true`; Quyết định 24/10/2026 của spec), và thêm `platform.roles.bind`
   mức `tenant` vào vai trò `org_admin` đã nhân bản của mọi tenant, trừ bản đang gán cho tài khoản dịch vụ (guard của
   org-and-principals/03 sẽ từ chối và dừng migration): migration đếm, in các tenant đó cho người vận hành và bỏ qua
   chúng, vì `tenant_owner` của chúng vẫn giữ `bind` qua quyền tính động (ADR-0104 (Accepted), Consequences); `tenant_owner`
   có cả hai qua quyền tính động.
2. **Một hàm từ chối.** `platform.rbac_refusals(p_tenant_id uuid, p_actor_id uuid, p_change jsonb)` trả
   `(reason_code, permission_key, depth)`: luật giữ quyền đọc `platform.holder_covers_grant` của org-and-principals/03
   (điều kiện bên trong của `platform.grants_cover`, mà `platform.uncovered_grants` cũng đọc) cho từng quyền mà thay đổi
   đưa vào, không chép phép so; `platform.roles.bind` phủ vai trò mà `platform.role_is_critical` của
   org-and-principals/03 trả false (DO-32.1; ticket 04 thêm vào hàm đó vai trò mang `fld.*` trên trường nhạy cảm); tự gán; vai trò hệ thống; khóa `tenant_grantable = false` và vai `platform_admin`. Neo của luật
   giữ quyền: với gán hay gỡ vai trò, workspace của gán đó; với thêm, nâng, bỏ hay hạ một khóa trong vai trò, workspace
   của từng gán hiện có của vai trò đó (người làm phải phủ ở mọi neo), và với vai trò chưa ai giữ, người làm giữ khóa ở
   mức bằng hoặc rộng hơn ở một neo bất kỳ, vì lần gán sau kiểm lại neo của nó (R6.1). Service gọi trước khi ghi (403 hay
   422 với `details.reason_code` và danh sách khóa); trigger BEFORE INSERT, UPDATE, DELETE trên
   `platform.tenant_roles`, `platform.tenant_role_permissions` và `platform.role_assignments` gọi cùng hàm, SQLSTATE
   23514, tên `rbac_refusals_<bảng>`; INSERT trên `platform.tenant_roles` là tạo vai trò, một ghi nới quyền (R7.1, R7.5).
   Người làm là `app.user_id`; ghi của `dw_app` thiếu nó bị từ chối; `dw_migrator` miễn theo
   `session_user` (tự audit), `dw_provisioner` chỉ được cài vai trò hệ thống và gán `tenant_owner` (Q1, Comments
   4/11/2026); chỉ lần ghi chỉ siết ở tenant `offboarding` hay `offboarded` miễn (lượt xóa của offboarding chỉ DELETE), lần ghi nới
   quyền ở đó vẫn bị xét như mọi nơi, còn tenant
   `setup` hay `locked` không miễn, vì ADR-0104 (Accepted) mục 6 áp hàm cho mọi người ghi trừ hai vai đó (R6.2); hàm lấy
   `FOR SHARE` trên gán vai trò của người làm, như `f381f1694395` làm với miễn trừ. Trigger tài khoản dịch vụ
   `guard_service_principal_grants` của org-and-principals/03 nằm trên cùng ba bảng; nó không chờ ticket này (OPS-b cạnh
   11, Quyết định 23/10/2026 của spec), còn ticket này chờ nó (Quyết định 3/11/2026 của spec, kiểm nhất quán): thứ tự
   bắn theo bảng chữ cái của tên là chủ ý, và test catalog của ticket này chỉ khẳng định trigger `rbac_refusals_*`.
   Khóa theo vai trò là một: dòng `platform.tenant_roles` `FOR NO KEY UPDATE`, mà trigger đó lấy trước khi đọc và lần
   xác nhận ở bước 4 lấy trước khi so `base_version`; không khóa advisory theo vai trò nào khác. Thứ tự khóa là của
   org-and-principals/03 bước 4: dòng vai trò (theo `id`) trước dòng `platform.tenant_access_versions` mà
   `trg_z_bump_access_version` UPDATE; lần xác nhận khóa dòng vai trò trước mọi lần ghi bảng quyền, trigger tăng
   `version` của bước 5 có tên đứng trước `trg_z_` nên khóa dòng vai trò trước dòng phiên bản, và tạo DW ở bước 11 giữ
   câu khóa vai trò đầu giao dịch của ticket kia (agent, theo ủy quyền 31/10/2026; Nếu sai thì: như ticket kia).
3. **Chủ sở hữu công ty cuối cùng.** Trigger AFTER `ck_role_assignments_last_owner` trên DELETE, UPDATE của
   `platform.role_assignments`, DELETE của `platform.memberships`, DELETE và UPDATE `status` của
   `platform.tenant_members`, DELETE của `platform.users`: tenant `active` hay `locked` phải còn ít nhất một chủ sở hữu
   `active`, đếm bằng `platform.active_tenant_owners` (ticket 02), không phép đếm thứ hai, sau khi khóa dòng
   `platform.tenants` `FOR UPDATE` như `complete_tenant_setup` của ticket 02, nên hai giao dịch gỡ hai chủ sở hữu cuối
   chạy lần lượt; cascade cũng tính. Tenant `setup` giữ luật riêng của R3.10, tenant `offboarding`, `offboarded` không bị
   xét. Trigger chỉ từ chối lần ghi gỡ một chủ sở hữu `active` (dòng OLD là gán `tenant_owner` của người `active`, hay
   membership, thành viên công ty, người dùng của người như vậy) mà sau lần ghi số đó là 0; tenant vốn không còn chủ sở
   hữu nào (như tenant seed không có `org_admin` ở `main`) không bị chặn mọi lần ghi. Gán `tenant_owner` có `expires_at`
   → 23514.
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
   `app.user_id`, `now() < expires_at`, và `app.user_id` giữ `required_permission` trên `platform.effective_grants`) hay sang `withdrawn` (`confirmed_by` NULL), `decided_at` là `now()`, không cột
   nào khác đổi, và mọi UPDATE của dòng có `OLD.status` khác `proposed` bị từ chối, kể cả UPDATE không đổi giá trị nào, vì nó làm mới
   `xmin` mà trigger bước 2 đọc (R7.8); DELETE bị từ chối khi
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
      `required_permission` và, sau khi khóa dòng vai trò `FOR NO KEY UPDATE` (bước 2), `base_version` còn đúng (409 `conflict`,
      `proposal_stale`, R8.7); UPDATE dòng sang `confirmed`, đặt
      `set_config('app.role_change_id', ..., true)`, rồi áp đúng thay đổi trong `payload` trong giao dịch của người
      duyệt, nên trigger bước 2 kiểm chính người duyệt. `payload` mang trọn thay đổi lúc đề xuất: với `role_create` là
      `role_id`, `key`, `name`, `description`, `kind` và tập `(permission_key, depth)` đầy đủ, chụp từ mẫu hay vai trò
      nguồn lúc đề xuất khi có `from_template`, `clone_of` (lần xác nhận không đọc lại nguồn); với `role_update` là
      `name`, `description` mới; với `role_permissions` là tập `(permission_key, depth)` đích; với `assignment_grant` như
      bước 6. `second_person_required`, `no_checker_available` và
      `proposal_expired` là `details.reason_code` dùng chung với cơ chế hai người của tenant-config, cùng hình 409
      `conflict` (Quyết định 23/10/2026 và 24/10/2026 của spec).
    - `POST /api/v1/admin/role-changes/{request_id}/withdraw` (người đề xuất hay người giữ `required_permission`; cùng
      khóa dòng; dòng đã đóng → 409 `conflict`, `proposal_closed`); `GET /api/v1/admin/role-changes`
      (`platform.roles.read`; đề xuất `proposed` chưa quá `expires_at`, phân trang theo index trên).
    - Trigger bước 2 từ chối ghi không chỉ siết quyền của `dw_app` khi `app.role_change_id` không trỏ tới đề xuất cùng
      tenant, có `proposed_by` khác `app.user_id`, đã `confirmed` bởi chính `app.user_id` trong chính giao dịch này
      (`confirmed_by = app.user_id` và `xmin` của dòng đề xuất bằng `pg_current_xact_id()::xid`, cùng phép như ngoại lệ
      DW ở bước 11; lần UPDATE sang `confirmed` và lần áp chạy ở giao dịch chính, không trong savepoint hay
      `begin_nested`, vì `xmin` của dòng ghi trong giao dịch con là xid con; chạy thử trên PostgreSQL 16 trước khi dựa
      vào, failure-modes #4), nên một đề xuất chỉ mở lần ghi trong giao dịch xác nhận nó, đúng một lần; hay khi lần ghi không phải
      lần ghi mà loại đề xuất cho phép trên đúng vai trò nó nêu, với đúng giá trị của `payload` (R7.5): `role_create`
      chỉ INSERT `platform.tenant_roles` với `id`, `key`, `name`, `description`, `kind` bằng `payload`, `template_key` bằng
      `payload` hay NULL, `deleted_at` NULL (`is_system` do trigger của ticket 02 suy từ khóa) và INSERT
      `platform.tenant_role_permissions` của vai trò đó với `(permission_key, depth)` thuộc tập của `payload`;
      `role_update` chỉ UPDATE `name`, `description` của `role_id` về giá trị của `payload`; `role_permissions` chỉ
      INSERT, UPDATE `platform.tenant_role_permissions` của `role_id` với `(permission_key, depth)` thuộc tập đích của
      `payload`, và DELETE khóa không thuộc tập đó; `assignment_grant` chỉ INSERT `platform.role_assignments` với
      `role_id` và `membership_id` của đề xuất. Trigger đọc đề xuất qua một hàm SECURITY DEFINER hẹp lọc tường minh
      `tenant_id = app.tenant_id`, nên phép lọc đó là lớp duy nhất giữ đề xuất của công ty khác ở đây (tiêu chí R3.3).
      UPDATE chỉ đổi `version`, `updated_at` (trigger tăng phiên bản của bước 5 và `touch_updated_at`), hay chỉ đặt
      `created_by`, `assigned_by` về NULL (khóa ngoại `ON DELETE SET NULL` khi xóa người dùng), là trung tính và
      trigger bước 2 cho qua; mọi phép so "không đổi cột nào khác" bỏ qua hai cột đó; ghi chỉ siết (DELETE trên `platform.role_assignments` hay `platform.tenant_role_permissions`, UPDATE hạ
      `depth`, UPDATE trên `platform.tenant_roles` chỉ đặt `deleted_at` từ NULL mà không đổi cột nào khác, DELETE trên
      `platform.tenant_roles`) chỉ cần `app.user_id` và qua `platform.rbac_refusals`, và ở tenant `offboarding`,
      `offboarded` không cần cả hai (lượt xóa của offboarding); UPDATE đặt `deleted_at` về NULL không phải ghi chỉ siết. Ngoại lệ
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
   trò cần thêm `platform.roles.bind` (R8.2), và mỗi gán hay gỡ qua `platform.rbac_refusals`. Một request kiểm mọi gán và gỡ của nó
   (`platform.rbac_refusals`, `platform.checker_candidates`, kiểm sớm tài khoản dịch vụ) trước lần ghi đầu; một lần từ
   chối → cả request bị từ chối với lỗi đó, không gỡ, không đề xuất, không người dùng, thành viên, membership hay thư
   mời nào được ghi, nên lời mời ở công ty không có người thứ hai trả 409 `no_checker_available` và không ghi gì
   (ADR-0104 (Accepted) mục 10). Đơn vị là một gán (một
   membership, một vai trò): mỗi gỡ áp ngay cộng một audit (bước 4); mỗi gán thêm là một đề xuất `assignment_grant` với
   `role_id` và `payload` `{membership_id, workspace_id, user_id}`; một request có ít nhất một đề xuất trả 202 với
   `applied` (các gán đã gỡ) và `proposals` (id đề xuất), một request chỉ gỡ trả 200 như hôm nay. Lời mời và
   `POST /api/v1/admin/members` ghi ngay người dùng `invite:`, thành viên công ty `invited`, membership và thư mời như
   hôm nay, vì membership không vai trò không cho quyền nào (R2.5); vai trò của người được mời, kể cả `member`, là đề
   xuất, nên người được mời đăng nhập trước lần xác nhận thì không giữ quyền nào; route trả 202 kèm `proposals`. Nghỉ
   hưu `forbid_escalation`, `is_administrative` (`membership_admin.py:53-65`) và bản chép ở `admin_console.py:318-326`
   cùng chỗ dùng ở `tenant_members.py:238-239` và `digital_workers.py:92`, `:397` (bước 11); Một vai trò có trong membership
   mà thân `PUT` bỏ đi là một lần gỡ, qua `platform.rbac_refusals` (403 `rbac_escalation` kèm khóa khi người gọi không
   giữ, R6.1, không đổi gì); `plan_memberships` thôi lặng lẽ giữ vai trò người gọi không quản được, và web gửi lại
   nguyên vai trò khóa (`assignable_by_me = false`). Gán cho người dùng loại `service` một vai trò mà `platform.role_is_critical`
   đúng → 422 `role_not_allowed_for_service` lúc đề xuất, không dòng đề xuất (lỗi sớm; trigger
   `guard_service_principal_grants` của org-and-principals/03 là chỗ quyết lúc xác nhận). Gán vai trò cho membership của principal một DW trả 409
   `dw_principal_roles_fixed` như hôm nay (digital-worker:R1.17).
7. **Lỗi.** 23514 của trigger dịch sang 403 `rbac_escalation`, `rbac_self_assignment`; 422 `rbac_not_grantable`;
   `ck_role_assignments_service_not_critical` (org-and-principals/03) sang 422 `role_not_allowed_for_service` theo tên
   ràng buộc, ở lần xác nhận cả `assignment_grant` lẫn `role_permissions`; 409
   `conflict` với `role_is_system`, `role_in_use`, `last_owner`, `role_limit_reached`, `second_person_required`,
   `no_checker_available`, `proposal_expired`, `proposal_stale`, `proposal_closed`, `ck_roles_sod_memberships` (tên
   luật, tối đa 20 người giữ); chỉ qua `details.reason_code`, không thêm mã vào `ErrorCode`. Tách nhiệm và `role_limit_reached` xét lúc áp, tức lúc
   xác nhận (lần đề xuất đã trả 202); mọi 23514 khác lúc xác nhận mà danh sách này không nêu → 409 `conflict` với
   `details.reason_code` `constraint_violation` và tên ràng buộc ở `details.constraint`, giao dịch lùi, đề xuất còn
   `proposed`, không bao giờ 500. 412 `precondition_failed`
   và 428 `precondition_required` là mã của `ErrorCode` mà app-standards/01 thêm (ADR-0108 (Accepted) mục 1).
8. **Audit cùng giao dịch:** `platform.role_change.proposed`, `.confirmed`, `.withdrawn`; khi áp:
   `platform.role.create`, `.update`, `.permissions_set` (thêm, bỏ, đổi mức), `.delete`,
   `platform.role_assignment.grant`, `.revoke`. `details`: id đề xuất, id và khóa vai trò, id workspace, id người dùng;
   không email, không tên. Nhãn tiếng Việt của mỗi hành động mới vào `configs/copy/audit_actions.d/tenant-rbac.yaml`.
9. **Cắt chuyển người ghi và người đọc cột cũ.** Khóa hai cột (bỏ trigger chép của ticket 02, xóa trắng,
   `ck_memberships_legacy_role_columns`) là ticket 06, chờ ticket 05 (FOG-49); ticket này không thêm ràng buộc nào lên
   hai cột ngoài trigger `guard_legacy_role_columns` và `guard_membership_identity` dưới đây. Mọi người ghi hai cột trong repo chuyển trong ticket này
   (`adapters/persistence/`): `membership_admin.py:92-130`, `tenant_members.py:263-268`, `admin_console_repo.py:248`
   (bước 6); `digital_workers_repo.py:146` (bước 11); `identity_provisioning.py:278`, đường
   `auto_provision_default_membership` của tenant demo, ghi membership không vai trò, vì gán `member` cần hai người, và
   `default_role` bỏ; `scripts/grant_platform_admin.py:30` ghi đúng `["platform_admin"]`, bỏ `org_admin`, vì đường vượt
   của G2 đã phủ nó; `seed_env.py:250`, `scripts/eval_wf_ai.py:80` và mọi fixture test ghi hai cột chuyển sang
   `dw_platform.testing.rbac.assign` dưới `dw_migrator`. Trigger chép `trg_memberships_legacy_role_columns`
   (`platform.sync_legacy_role_columns()`, SECURITY INVOKER, `b5677d345bc1_tenant_roles.py:663-720`) ở lại nguyên như
   ticket 02 dựng, và trigger bước 2 không cho nó ngoại lệ nào: lần INSERT, DELETE `platform.role_assignments` hay INSERT
   `platform.tenant_roles` (nhân bản mẫu qua `platform.install_role_template`) mà nó làm là lần ghi của chính người ghi
   cột, xét như mọi lần ghi khác, nên dưới `dw_app` một lần thêm khóa vào cột cũ không mang đề xuất → 23514
   `rbac_refusals_role_assignments` (hay `rbac_refusals_tenant_roles`), không dòng gán mới, còn một lần bỏ khóa là ghi
   chỉ siết; trigger bước 2 không miễn lần ghi nới quyền nào theo `pg_trigger_depth()`, theo hàm gọi hay theo bảng gốc
   (R7.5, RB48). Người đọc hai cột để quyết quyền chỉ còn `platform_admin` trong `role_keys` (`membership_lookup.py:125`,
   `:171-172`; G2, ADR-0104 (Accepted) Context), nên trigger `guard_legacy_role_columns` BEFORE INSERT, UPDATE OF
   `role_keys`, `permission_set_keys` trên `platform.memberships` từ chối với SQLSTATE 23514, ràng buộc
   `ck_memberships_legacy_role_writer`, lần ghi thêm một khóa vào một trong hai cột (có ở NEW, không có ở OLD; mọi khóa
   khi INSERT) trong hai trường hợp: khóa là `platform_admin` và `session_user` khác `dw_migrator` (ADR-0104 (Accepted)
   mục 8: giá trị do script nền tảng ghi); hay `session_user` khác `dw_app` và `dw_migrator`, vì lần ghi của
   `dw_provisioner` được `platform.rbac_refusals` miễn (mục 6) nên lần chép của nó thành gán vai trò không qua hai người,
   và sau bước này không người ghi nào của `dw_provisioner` còn ghi hai cột. Giữ hay gỡ khóa không bị xét.
   `scripts/grant_platform_admin.py` và `seed_env` chạy dưới `dw_migrator`; script thêm `platform_admin` vào `role_keys`
   đang có (`role_keys || '["platform_admin"]'` khi chưa có), không ghi đè, vì ghi đè khi trigger chép còn thì gỡ mọi gán
   đến từ cột của người đó (R6.2, R6.5, RB49). Ba cột định danh của membership (`tenant_id`, `workspace_id`, `user_id`)
   không đổi được sau INSERT: trigger `guard_membership_identity` BEFORE UPDATE OF ba cột đó trên `platform.memberships`
   từ chối với SQLSTATE 23514, ràng buộc `ck_memberships_identity_fixed`, khi giá trị đổi và `session_user` khác
   `dw_migrator`, vì gán vai trò bám `membership_id`, nên đổi `user_id` là chuyển mọi gán, kể cả `tenant_owner`, sang
   người khác mà không qua trigger bước 2, 3 (R6.2, R7.5, RB50); không code nào trong repo đổi ba cột đó (`sa.update`
   trên membership chỉ đặt `role_keys`, `permission_set_keys`, `manager_user_id`, `department`). Người đọc khác:
   directory, trang thứ bậc và `tenant_members.py:76`, `:126` đọc tên vai trò từ gán
   vai trò; `_select_workers` (`digital_workers_repo.py:384-397`) đọc khóa vai trò của principal từ gán vai trò của
   membership principal ở workspace của DW, vì bước 11 thôi ghi `role_keys` lúc tạo DW. Trang thành viên
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
    (`xmin` của dòng DW bằng `pg_current_xact_id()::xid`; chạy thử trên PostgreSQL 16 trước khi dựa vào, failure-modes #4),
    và dòng `platform.users` của principal cũng được INSERT trong giao dịch này: `created_at` của nó bằng `now()`, cột mà
    trigger `guard_user_created_at` BEFORE UPDATE trên `platform.users` không cho đổi (23514 `ck_users_created_at_fixed`,
    mọi vai trừ `dw_migrator`), không đo bằng `xmin` vì một UPDATE không đổi gì cũng làm mới nó; nên không ai trỏ một DW
    `draft` mới vào một tài khoản run-as đã có rồi gán vai trò cho nó một mình; `platform.rbac_refusals` vẫn chạy. Người thứ hai là lần
    `draft→operating` của digital-worker:R1.9: `_second_person` (`digital_workers.py:424-438`) giữ nhánh 409
    `principal_inactive` của org-and-principals/03 bước 10 trước phép so, rồi thay phép so `scopes` của workspace đang
    làm việc bằng `platform.grants_cover(tenant, người gọi, principal)` trên quyền hiệu lực; trạng thái `active` của
    principal và `platform.grants_cover` đọc trong một câu lệnh, một snapshot, vì `grants_cover` trên tập rỗng là true
    (agent, theo ủy quyền 31/10/2026; Nếu sai thì: giao dịch `REPEATABLE READ`). `_check_roles` đọc vai trò
    của tenant: khóa vai trò lạ → `role_unknown`, vai trò mà `platform.role_is_critical` đúng →
    `role_not_allowed_for_service`, và `is_critical_role` (`digital_workers.py:88`) nghỉ hưu
    (digital-worker:R1.15), luật giữ quyền của `platform.rbac_refusals` thay `forbid_escalation` và trả
    `grants_not_covered` như digital-worker:R1.10. `platform.dw_principal_roles_fixed()` chuyển sang
    `platform.role_assignments` qua trigger `trg_role_assignments_dw_principal_roles_fixed`, tên đứng sau
    `rbac_refusals_role_assignments` nên bắn sau nó: INSERT cho principal của DW không ở `draft` → 23514
    `ck_memberships_dw_principal_roles_fixed` với mọi người ghi trừ `dw_migrator`; gỡ vẫn được (digital-worker:R1.17). Lần
    ghi không đề xuất bị `rbac_refusals_role_assignments` từ chối trước; tên `ck_memberships_dw_principal_roles_fixed` chỉ
    thấy được khi lần ghi qua trigger bước 2 (một đề xuất `assignment_grant` đã xác nhận trong giao dịch, hay
    `dw_provisioner`).

## Tiêu chí chấp nhận

- [ ] R3.3 (RB8): người gọi của tenant A xác nhận, rút `request_id` của tenant B, đọc `GET /api/v1/admin/roles/{role_id}/assignments` với vai trò của B, hay gửi `PUT /api/v1/admin/members/{user_id}/memberships` với người của B → 404, 0 dòng đổi; `GET /api/v1/admin/role-changes` của A không có đề xuất của B; SQL thô dưới `dw_app` với `app.tenant_id` A đặt `app.role_change_id` là đề xuất của B rồi INSERT `platform.tenant_roles` với `id` là `payload` `role_id` của một đề xuất `role_create` của B → 23514; gỡ phép lọc `tenant_id` khỏi hàm đọc đề xuất → test SQL đỏ.
- [ ] R5.3 (RB14): đề xuất gán vai trò làm người nhận giữ hai vế một luật → 202; lần xác nhận → 409 nêu luật và id người giữ, giao dịch lùi, đề xuất còn `proposed`, không audit `.confirmed`; một 23514 khác lúc xác nhận (vai trò thử với một trigger từ chối riêng) → 409 `constraint_violation` kèm tên ràng buộc, không 500.
- [ ] R6.1 (RB15): người giữ `approvals.decide` mức `workspace` đề xuất vai trò có khóa đó mức `tenant` → 403 `rbac_escalation` kèm khóa; gỡ người nhận khỏi quyền mình không giữ → 403; người giữ khóa mức `workspace` ở A thêm khóa đó vào vai trò đang gán ở B → 403.
- [ ] R6.2 (RB15): cùng các thao tác bằng SQL thô dưới `dw_app` (có và không có `app.user_id`) → 23514, ở công ty `active`, `locked` và `setup` (ở `locked`, `setup` không ai giữ quyền nào, nên không lần xác nhận nào qua được guard của đề xuất: dòng đề xuất đã xác nhận được cắm khi tắt trigger, và lần ghi chạy dưới một phiên siêu người dùng mà trigger xét như `dw_app`; Comments 4/11/2026); mỗi ca nới quyền mang một `app.role_change_id` hợp lệ, xác nhận trong chính giao dịch bởi một người khác người đề xuất mà thiếu khóa, nên chỉ `platform.rbac_refusals` còn từ chối được, và khẳng định `rbac_escalation` trong DETAIL, khác lời từ chối hai người; có một ca INSERT `platform.tenant_roles` (`role_create` mang khóa người xác nhận không giữ); ở công ty `offboarding`, lần gỡ gán, bỏ khóa hay DELETE vai trò không có `app.user_id` → nhận, lần thêm khóa hay gán → 23514; gỡ lời gọi `platform.rbac_refusals` khỏi từng trigger → ca của bảng đó nhận, test SQL thô đỏ trong khi test qua service vẫn xanh; miễn cả lần ghi nới quyền ở `offboarding` → ca thêm nhận, test đỏ; nới miễn trừ thành "không `active`" → ca `locked` đỏ.
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
- [ ] R7.5 (RB21): SQL thô dưới `dw_app` ghi gán vai trò mới hay INSERT `platform.tenant_roles` không mang `app.role_change_id`, hay mang đề xuất do chính `app.user_id` đề xuất, hay mang đề xuất của vai trò X mà ghi vai trò Y, hay mang đề xuất `role_update` của X mà INSERT gán X hay thêm khóa vào X, hay mang đề xuất `role_permissions` của X còn `proposed` (người khác người đề xuất, chưa xác nhận trong giao dịch), hay đã xác nhận ở một giao dịch trước, hay xác nhận trong chính giao dịch mà thêm khóa hay mức khác tập của `payload` → 23514, và bỏ phép so `xmin` hay phép so `payload` khỏi trigger → ca tương ứng nhận, test đỏ; INSERT đề xuất có `proposed_by` khác `app.user_id` hay ở `confirmed`, UPDATE đề xuất sang `confirmed` bởi người giữ mọi khóa của thay đổi mà không giữ `required_permission`, `UPDATE ... SET decided_at = decided_at` trên đề xuất `confirmed` rồi áp `payload` ở giao dịch đó, UPDATE đề xuất `confirmed` về `proposed` → 23514; SQL thô gỡ gán vai trò có `app.user_id` → nhận; gỡ nhánh kiểm đề xuất hay nhánh khớp vai trò khỏi trigger → đỏ.
- [ ] R7.5 (RB21): tạo DW với vai trò `approver` của tenant → 201, principal có gán vai trò, không dòng đề xuất; người tạo tự `draft→operating` → 409 `second_person_required` (digital-worker:R1.9); SQL thô dưới `dw_app` gán thêm vai trò cho principal của DW `operating`, hay cho principal của DW `draft` bởi người không phải người tạo → 23514; SQL thô tạo một DW `draft` trỏ tới người dùng `human` rồi gán vai trò cho người đó (khóa ngoại tới `platform.service_principals` và guard của nó chặn trước dưới `dw_app`: cắm khi tắt trigger, Comments 4/11/2026), hay gán cho principal của một DW `draft` tạo ở giao dịch trước, hay tạo một DW `draft` mới trỏ vào một tài khoản run-as có từ giao dịch trước rồi gán vai trò cho nó → 23514 `rbac_refusals_role_assignments`; UPDATE `created_at` của người dùng đó về `now()` → 23514 `ck_users_created_at_fixed` (chỉ `dw_migrator` giữ UPDATE trên `platform.users`: ca chạy dưới phiên siêu người dùng); SQL thô mang một đề xuất `assignment_grant` xác nhận trong giao dịch gán vai trò cho principal của DW `operating` → 23514 `ck_memberships_dw_principal_roles_fixed`; mỗi ca đột biến dựng mọi vế khác của ngoại lệ cho đúng trong cùng giao dịch (DW tạo trong giao dịch rồi chuyển `operating` trong đó; DW tạo bởi A rồi đổi `app.user_id` sang B; tài khoản cũ trên DW mới), nên bỏ điều kiện `draft`, `created_by`, `kind`, cùng giao dịch của DW hay của người dùng khỏi ngoại lệ → ca tương ứng nhận, test đỏ; người thứ hai không giữ khóa của một vai trò đã gán cho principal → 403 `grants_not_covered`, đổi phép kiểm về `scopes` của workspace đang làm việc mà người đó có khóa ở workspace khác → test đỏ.
- [ ] R6.3 (RB16): theo org-and-principals:R6.4, đề xuất gán cho một tài khoản dịch vụ một vai trò mang khóa `critical` (như `platform.sod_waivers.write`) → 422 `role_not_allowed_for_service`, không dòng đề xuất; đề xuất gán vai trò không trọng yếu cho tài khoản đó, rồi một đề xuất `role_permissions` thêm khóa `critical` vào vai trò ấy được xác nhận trước → lần xác nhận gán trả 409 `conflict` `proposal_stale` (`version` của vai trò đã tăng, bước 5), không đổi gì, và đề xuất lại gán đó → 422 `role_not_allowed_for_service`, không dòng đề xuất; SQL thô dưới `dw_app` mang `app.role_change_id` của một đề xuất `assignment_grant` còn đúng `base_version` INSERT gán vai trò trọng yếu cho tài khoản dịch vụ → 23514 `ck_role_assignments_service_not_critical`, và service dịch tên đó sang 422; xác nhận đề xuất `role_permissions` thêm khóa `critical` vào vai trò đang gán cho tài khoản dịch vụ → 422, không đổi gì; gỡ kiểm sớm → ca đầu nhận 202 và test đỏ.
- [ ] R7.8 (RB43): hai kết nối xen kẽ có điều khiển: B xác nhận một đề xuất `role_permissions` thêm khóa không trọng yếu vào R và dừng ngay sau khi khóa dòng R (các câu của lần xác nhận chạy theo thứ tự của bước 4 trên một kết nối), A tạo DW với vai trò R (gán không đề xuất) tới khi `pg_locks` cho thấy A chờ khóa, B đi tiếp và commit → cả hai xong, không bên nào nhận 40P01; dời câu khóa vai trò đầu giao dịch của tạo DW xuống sau lần ghi `platform.tenant_members` → 40P01, test đỏ; test catalog khẳng định trigger tăng `version` của bước 5 trên `platform.tenant_role_permissions` xếp trước `trg_z_bump_access_version` theo tên, đổi tên nó sang sau → đỏ.
- [ ] R7.6 (RB32): gỡ gán vai trò, bỏ một khóa hay hạ mức một khóa trong vai trò → 200, áp ngay, đúng một audit, không dòng đề xuất, `version` của vai trò tăng một; xóa mềm một vai trò không còn người giữ → 200, áp ngay, đúng một audit `platform.role.delete`, không dòng đề xuất; vai trò còn người giữ → 409 `role_in_use`; SQL thô dưới `dw_app` đặt lại `deleted_at` về NULL không mang đề xuất → 23514; gỡ gán `tenant_owner` cuối vẫn 409 `last_owner`.
- [ ] R7.7 (RB36): `dw_app` DELETE một đề xuất của công ty `active` → 23514, dòng còn; cùng lệnh khi công ty `offboarding` → xóa được; offboarding một công ty có một đề xuất `proposed` và một đề xuất `confirmed` → lane `offboarding` xuất mỗi dòng một lần rồi xóa hết, dòng của công ty khác còn nguyên, test phủ offboarding (studio-skeleton:R4.3) xanh với `platform.role_change_requests` không có trong `STUDIO_EXCLUSIONS`; gỡ phép kiểm DELETE khỏi trigger → test đỏ.
- [ ] R7.8 (RB43): hai người khác người đề xuất xác nhận cùng một đề xuất đồng thời → đúng một lần áp, đúng một audit `.confirmed`, người kia 409 `conflict` với `details.reason_code` `proposal_closed`; xác nhận sau khi đề xuất đã rút → 409 `proposal_closed`, không đổi gì; người đề xuất bị `suspended` trước lần xác nhận → 409 `proposal_stale`; bỏ khóa dòng đề xuất hay điều kiện `status = 'proposed'` → test đồng thời đỏ.
- [ ] R8.1: `GET /api/v1/admin/roles` trả đủ trường; `assignable_by_me` bằng đúng kết quả `platform.rbac_refusals` cho cùng người gọi, người nhận giả định và workspace đang làm việc (test so sánh).
- [ ] R8.2 (RB24): người không có `platform.roles.write` gọi thẳng `PUT /api/v1/admin/roles/{role_id}/permissions`, `POST /api/v1/admin/roles` → 403, không đề xuất; người có `platform.members.write` mà không có `platform.roles.bind` gọi `PUT /api/v1/admin/members/{user_id}/memberships` thêm vai trò → 403, không đề xuất.
- [ ] R8.3 (RB25): đề xuất bị 409 → không audit; mỗi audit chỉ có id và mã (test quét `details` không có `@` hay tên).
- [ ] R8.4 (RB25): gửi lại cùng `Idempotency-Key` và thân → cùng kết quả, một audit.
- [ ] R8.5 (RB26): `PUT .../permissions` với `If-Match` cũ → 412 `precondition_failed`, không dòng đề xuất, quyền không đổi; bỏ so `If-Match` → test đỏ.
- [ ] R7.5 (RB48): SQL thô dưới `dw_app` với `app.user_id`, không `app.role_change_id`: UPDATE `memberships.role_keys`
      thêm `approver` (vai trò tenant đã có) hay `permission_set_keys` thêm `approver_boost` → 23514
      `rbac_refusals_role_assignments`, không dòng `platform.role_assignments` mới, cột không đổi; INSERT membership với
      `role_keys` `["member"]` → 23514; thêm khóa có mẫu mà tenant chưa có vai trò → 23514 `rbac_refusals_tenant_roles`,
      không vai trò mới; UPDATE bỏ `approver` của người khác, người làm giữ mọi khóa của nó → nhận, gán đó biến mất; cùng
      lần thêm dưới `dw_migrator` → nhận; cho trigger bước 2 miễn lần ghi lồng (`pg_trigger_depth() > 1`) hay lần ghi từ
      `platform.sync_legacy_role_columns()` → ca thêm khóa nhận, test đỏ.
- [ ] R6.2 (RB49): SQL thô dưới `dw_app` (có `app.user_id`) và dưới `dw_provisioner`, INSERT membership hay UPDATE
      `role_keys` thêm `platform_admin` → 23514 `ck_memberships_legacy_role_writer`, cột không đổi, AccessContext kế tiếp
      của người đó không có `platform_admin` trong `roles`; dưới `dw_provisioner` thêm `member` vào `role_keys` hay
      `approver_boost` vào `permission_set_keys` → 23514 cùng tên, không dòng gán mới; UPDATE `department` của membership
      đã giữ `["platform_admin"]` và UPDATE gỡ `platform_admin` dưới `dw_app` → nhận; cùng lần thêm dưới `dw_migrator` →
      nhận; chạy `scripts/grant_platform_admin.py` cho người đang giữ `["member"]` qua cột cũ → `role_keys`
      `["member", "platform_admin"]`, gán `member` còn; gỡ trigger hay bỏ nhánh `dw_provisioner` → ca tương ứng nhận, test
      đỏ.
- [ ] R7.5 (RB50): SQL thô dưới `dw_app` và `dw_provisioner` UPDATE `platform.memberships` đổi `user_id` (membership của
      một `tenant_owner` sang người khác), `workspace_id` hay `tenant_id` → 23514 `ck_memberships_identity_fixed`, gán
      vai trò vẫn của người cũ; UPDATE `manager_user_id` hay `department` → nhận; dưới `dw_migrator` → nhận; gỡ trigger →
      ca đổi `user_id` nhận, người mới giữ `tenant_owner`, test đỏ.
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
- `packages/python/dw_platform/src/dw_platform/application/role_assignments.py` (thay phần gán vai trò cũ của `tenant_members.py`, ở `94c43ee`); spec: R6.1.
- `packages/python/dw_platform/src/dw_platform/application/digital_workers.py:375-397`; spec: R7.5.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/digital_workers_repo.py:146`; spec: R7.5.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:248-280`; spec: R7.1.
- `scripts/grant_platform_admin.py:30`; spec: R6.2, G2.
- `db/migrations/versions/b5677d345bc1_tenant_roles.py:663-720`, `db/migrations/versions/b5677d345bc1_tenant_roles.py:1158-1160`; spec: R7.5 (RB48).
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:125`, `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:171-172`; spec: R6.2 (RB49), G2.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/digital_workers_repo.py:384-397`; spec: R7.5.
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
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): kiểm nhất quán với org-and-principals/03 (gate cùng ngày, hai agent
  không thấy nhau), ADR-0103 (Accepted), ADR-0104 (Accepted) và `CLAUDE.md`; 0 CRITICAL, năm HIGH chạm ticket này, sửa theo
  Quyết định 3/11/2026 (kiểm nhất quán) của spec. (HC1) luật giữ quyền chép "cùng phép so của `platform.grants_cover`"
  trong khi org-and-principals/03 đưa phép so đó vào `platform.uncovered_grants`: bước 2 đọc `platform.holder_covers_grant`
  của ticket kia. (HC2) "vai trò trọng yếu" cho `platform.roles.bind`, cho guard tài khoản dịch vụ và cho `_check_roles`
  của DW là một hàm, `platform.role_is_critical` (bước 2, 6, 11). (HC3) khóa dòng vai trò `FOR UPDATE` ở lần xác nhận cộng
  khóa advisory theo vai trò của trigger kia là bế tắc với lần tạo DW: một khóa, dòng vai trò `FOR NO KEY UPDATE` (bước 2,
  4), tiêu chí R7.8 mới. (HC4) `_second_person` giữ nhánh `principal_inactive` trước `platform.grants_cover` (bước 11).
  (HC5) mọi gán là đề xuất 202, nên tiêu chí R6.4 của org-and-principals/03 ("qua route gán vai trò → 422
  `role_not_allowed_for_service`") đỏ khi ticket này vào: bước 6 kiểm sớm lúc đề xuất, bước 7 dịch
  `ck_role_assignments_service_not_critical` lúc xác nhận, tiêu chí mới. Thứ tự: `Blocked by` thêm org-and-principals/03 (cạnh
  một chiều; OPS-b của Đạt, "ticket kia không chờ ticket này", giữ nguyên). Nếu sai thì: bỏ cạnh, và ticket này tạo hai hàm
  rồi viết lại `platform.uncovered_grants` và guard của org-and-principals/03 khi dựng trước.
- 2026-11-03 (agent): ĐẠT của gate ở trên đọc bản trước lượt kiểm nhất quán; bước 2, 4, 6, 7, 11, `Blocked by` và ba tiêu
  chí đổi theo năm HIGH trên, không đổi phạm vi. Ticket còn `needs-triage` chờ ticket 05; trước khi lên `ready-for-agent`
  cần một lượt xác nhận (checking-plan-readiness, chỉ đọc chỗ sửa), không còn "không cần gate lại" như dòng trên. MEDIUM,
  chưa sửa: (M11) `rbac_escalation` của `platform.rbac_refusals` trả `(khóa, độ sâu)`, bộ kiểm gắn của org-and-principals/03
  trả `(khóa, độ sâu, workspace neo)`: nên thêm `anchor_workspace_id` vào kết quả của hàm, một hình `details` cho một
  `reason_code`. (M12) bước 1 thêm `platform.roles.bind` (`critical`) vào `org_admin` của mọi tenant; nếu một tenant đã bỏ
  khóa `critical` khỏi bản `org_admin` của mình và gán nó cho một tài khoản dịch vụ, guard của org-and-principals/03 từ
  chối câu INSERT và migration dừng: nên đếm và in trước, như bước 4 của ticket kia. (M13) tenant-rbac/04 đưa `fld.*` vào
  bảng quyền mới (`platform.tenant_role_object_privileges`, `studio.field_permissions`): `platform.role_is_critical` phải
  đọc chúng và guard tài khoản dịch vụ cần trigger trên chúng; ticket 04 ngoài lượt kiểm này, báo
  `checking-plan-consistency`. (M14) `platform.dw_principal_roles_fixed()` chuyển sang `platform.role_assignments` vẫn tự
  hỏi "là principal của DW" bằng `EXISTS`, bên cạnh `platform.is_digital_worker_principal` của org-and-principals/03. (M15)
  `grants_not_covered` (DW) và `rbac_escalation` cho cùng luật phủ, giữ có chủ ý theo digital-worker:R1.10. (M9) của dòng
  trên đã sửa: digital-worker:R1.1 nay là gán vai trò.
- 2026-11-03 (agent): checking-plan-readiness, lượt xác nhận nhẹ chỉ trên chỗ 15e74b6 sửa (`Blocked by`, bước 2, 4, 6,
  7, 11, R6.3 (RB16), R7.8 (RB43) mới), đối chiếu code hiện có, một subagent builder; 0 CRITICAL, ba HIGH chạm ticket
  này, sửa theo ủy quyền 31/10/2026. (HX1) một khóa dòng vai trò chưa bỏ được 40P01: tạo DW giữ dòng
  `platform.tenant_access_versions` (`trg_z_bump_access_version` trên `tenant_members`, `memberships`) rồi chờ dòng vai
  trò, còn lần xác nhận giữ dòng vai trò rồi chờ dòng phiên bản. Thứ tự khóa ở org-and-principals/03 bước 4, bước 2 ở
  đây trỏ tới nó, và R7.8 mới viết lại thành xen kẽ có điều khiển: đột biến cũ (thêm lại khóa advisory) không phân biệt
  được, vì đúng thứ tự xen kẽ đó cũng bế tắc trên bản không đột biến. (HX2) R6.3 ca hai không tới được 422: xác nhận
  `role_permissions` tăng `version` của vai trò, nên đề xuất gán đã cũ và dừng ở `proposal_stale`; tiêu chí nay nói
  vậy, và ca dịch tên ràng buộc lúc xác nhận đi bằng SQL thô. (HX3) bước 11: `active` của principal và
  `platform.grants_cover` đọc trong một câu, không thì một lần `suspended` giữa hai câu mở lại lỗ phủ trên tập rỗng.
  Chủ và người đọc khớp giữa hai ticket: `platform.role_is_critical` và `platform.holder_covers_grant` do
  org-and-principals/03 tạo, ở đây chỉ đọc (bước 2, 6, 11), cạnh `Blocked by` một chiều; `principal_inactive` là 409
  `conflict` với `details.reason_code`, như `_conflict` (`digital_workers.py:227`). MEDIUM, chưa sửa: (M16) luật neo
  "vai trò chưa ai giữ, một neo bất kỳ" của bước 2 diễn bằng `EXISTS (SELECT 1 FROM platform.effective_grants(tenant,
người làm) h WHERE platform.holder_covers_grant(tenant, người làm, khóa, độ sâu, h.anchor_workspace_id))`, không truyền
  NULL làm "neo bất kỳ" vào hàm chung. (M17) `_check_roles` hôm nay đọc vai trò theo khóa (`RoleCatalogPort`), nên bước
  11 tra id vai trò của tenant trước khi gọi `platform.role_is_critical`; port mới hay thêm phương thức là việc của người
  dựng. Kết quả: ĐẠT cho chỗ sửa; Status giữ `needs-triage` tới khi ticket 05 (FOG-49) `resolved`, rồi lên
  `ready-for-agent` không cần gate lại nếu nội dung không đổi.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): tách khóa cột cũ sang ticket 06 (`Blocked by: 03, 05`), để ticket này
  không chờ FOG-49. Đọc ở `b3db72f`, code và migration: không gì còn đọc `memberships.role_keys` hay
  `permission_set_keys` để quyết quyền, trừ `platform_admin` ở `membership_lookup.py:125`, `:171-172` (G2), giá trị mà
  `ck_memberships_legacy_role_columns` vẫn cho. `platform.effective_grants`, `platform.assigned_grants` (tách nhiệm),
  `platform.scopes_in`, `effective_scopes()`, `scope_holders.py`, `platform.checker_candidates`, `/me`, `_second_person`
  và khóa cache đọc gán vai trò hay `platform.tenant_access_versions`; `_check_roles` đọc vai mẫu. Mọi khóa khác trong
  hai cột chỉ tới quyền qua trigger chép, mà lần ghi của nó đi qua trigger bước 2 dưới `session_user` của người ghi
  cột, nên chưa khóa cột vẫn không có đường vòng quanh hai người, miễn là trigger bước 2 không miễn nó (bước 9, RB48).
  Người hiển thị (directory, trang thứ bậc, danh sách thành viên, `_select_workers` của DW, mới thêm vào bước 9)
  chuyển ở đây. Thêm RB49: lỗ có từ trước, không do cách tách: `dw_app` ghi được `platform_admin` vào `role_keys` và
  khóa cột cho giá trị đó, nên cả hai nửa để ngỏ một đường trao đường vượt G2 mà R6.2, R6.5 cấm; trigger
  `guard_legacy_role_columns` đóng nó ở đây, không chờ FOG-49 (chỉ `dw_migrator` thêm `platform_admin`). Lưu ý cho dw-proterial: lần thêm vai trò qua cột cũ
  dưới `dw_app` bị từ chối từ ticket này (D11, không phải khóa cột); ticket 05 ghi điều đó. Ticket này không chờ ticket
  05 nữa. Nếu sai thì: nếu FOG-49 của Đạt nghĩa là không thay đổi nào của nền tảng được từ chối lần ghi vai trò của
  dw-proterial trước khi nó chuyển, ticket này về `needs-triage` tới khi ticket 05 `resolved`, như dòng 2026-11-03 ở
  trên, và ticket 06 gộp lại vào bước 9.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness trên bản tách (builder check, boundary walk
  ranh giới 1-2 và 3-6, rồi hai lượt xác nhận, mức tối đa của gate; script 24 Đạt). Sửa ở spec (ba dòng Quyết định
  4/11/2026), các bước 1-4, 6, 7, 9, 11, tiêu chí R5.3, R6.2, R7.5, RB48-RB50 mới, ticket 04 bước 7, 05, 06 và
  ADR-0104 (Accepted) Amendments 2026-11-04: ba CRITICAL (ADR nói dw-proterial chuyển trước khi ticket này từ chối;
  ngoại lệ DW nhận một tài khoản run-as đã có; một miễn trừ do chính lượt sửa thêm, gỡ gán do cascade không qua luật giữ
  quyền, trái ADR-0104 (Accepted) mục 6, lượt xác nhận đầu bắt và gỡ) và mười hai HIGH. Sửa sau lượt xác nhận
  thứ hai không có người đọc mới; người dựng đọc lại bước 2, 4, 11 và tiêu chí R6.2 (RB15), R7.5 (RB21) trước.
- 2026-11-04 (agent): câu hỏi cho Đạt, không chặn ticket. (Q1) `dw_provisioner` ghi thẳng `platform.tenant_roles`,
  `platform.tenant_role_permissions`, `platform.role_assignments` mà không qua `platform.rbac_refusals` hay hai người,
  đúng như ADR-0104 (Accepted) mục 6; khuyến nghị (B): một nhánh của trigger bước 2 chỉ cho vai đó gán `tenant_owner`
  và cài vai trò hệ thống lúc tạo công ty; (A) giữ như ADR. (Q2) lần xóa membership kéo theo gỡ gán vai trò qua luật
  giữ quyền như mọi lần gỡ (ADR-0104 (Accepted) mục 6), nên người xóa membership hay nghỉ hưu DW (`cfbd906be98b`) mà
  không giữ quyền của nó bị từ chối; khuyến nghị (A) giữ, người dựng thử đường nghỉ hưu DW và ghi ở đây nếu nó vỡ; (B)
  miễn cascade kèm một sửa đổi ADR.
- 2026-11-04 (agent): MEDIUM của gate, chưa sửa. (M18) Tới ticket 06, lần gỡ khóa qua cột cũ xóa gán theo khóa, nên một
  khóa cũ còn trong cột gỡ được một gán do hai người cấp qua API (chỉ siết, một người; SQL thô không có audit). (M19)
  `clone_of` mang id vai trò của công ty khác phải trả đúng câu trả lời của id không có, có test âm; `payload` `role_id`
  do server sinh. (M20) Membership hay thành viên đích của `assignment_grant` bị xóa hay `suspended` giữa lúc đề xuất và
  lúc xác nhận → 409 `proposal_stale`, không lỗi khóa ngoại 500. (M21) `GET /api/v1/admin/role-changes` nên trả
  `payload` để người xác nhận thấy đúng điều mình xác nhận. (M22) Đề xuất cộng dồn tới offboarding, không trần số đề
  xuất mở mỗi người. M1 và M6 ở trên vẫn đứng (hai đề xuất trùng).
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): đọc lại bước 2, 4, 11 và tiêu chí RB15, RB21 trước khi dựng, đối chiếu
  code. (1) Bước 4: khóa ngoại `ON DELETE SET NULL` của `tenant_roles.created_by` và `role_assignments.assigned_by` làm
  lần xóa một người dùng thành UPDATE trên hai bảng; bước 4 chỉ coi `version`, `updated_at` là trung tính, nên xóa bất kỳ
  người nào đã tạo vai trò hay gán vai trò sẽ bị từ chối như ghi nới quyền. Sửa: đặt hai cột đó về NULL là trung tính
  (bước 4 đã ghi). (2) RB15: ở công ty `locked`, `setup` `platform.effective_grants` rỗng, nên không lần xác nhận nào qua
  guard của đề xuất; "xác nhận trong chính giao dịch" ở đó không dựng được. Test cắm dòng đề xuất đã xác nhận khi tắt
  trigger (siêu người dùng, `session_replication_role`), lần ghi chạy dưới phiên đó, trigger xét như `dw_app`, luật giữ
  quyền từ chối (tiêu chí đã ghi). (3) Bước 2: `dw_provisioner` không còn miễn, theo Q1. (4) Bước 11: khóa ngoại
  `digital_workers → service_principals` và guard người chịu trách nhiệm chặn DW trỏ tới người dùng `human` dưới `dw_app`,
  nên nhánh `kind` là lớp thứ hai, thử bằng cách cắm khi tắt trigger; chỉ `dw_migrator` giữ UPDATE trên `platform.users`,
  nên `guard_user_created_at` giữ phiên khác (siêu người dùng) và câu "UPDATE không đổi gì làm mới `xmin`" không xảy ra
  dưới `dw_app` (RB21 đã ghi). (5) RB21: một đề xuất do chính `app.user_id` đề xuất không thể ở `confirmed` (CHECK
  `ck_role_change_requests_second_person`), nên nhánh `proposed_by <> app.user_id` của hàm đọc đề xuất là lớp thứ hai.
  (6) Bước 3 (ngoài phần được dặn, gặp khi dựng): lần xóa membership, thành viên công ty hay người dùng xóa gán theo
  cascade sau khi người đó đã biến mất, nên trigger AFTER trên `role_assignments` không biết người đó có `active` không.
  Sửa: trigger BEFORE DELETE trên `memberships` và `tenant_members` gỡ gán `tenant_owner` của chúng trước, như một câu
  riêng, khi người còn đó; xóa người dùng tới hai bảng đó qua cascade.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): quyết khi dựng. (D1) `platform.rbac_refusals` có tham số thứ tư
  `p_lock boolean DEFAULT true`: trigger khóa `FOR SHARE` gán của người làm; lần hỏi trước của service và
  `assignable_by_me` truyền false (đọc không khóa dòng). (D2) `platform.role_privileges(tenant, role)` lặp quyền tính
  động của `tenant_owner` cho luật giữ quyền; test `test_role_privileges_of_the_owner_match_its_effective_grants` giữ
  hai bản bằng nhau. (D3) `platform.role_template_privileges(template)` là chủ duy nhất của "mẫu mang gì, ở mức nào",
  `install_role_template` đọc nó, `GET /api/v1/admin/role-templates` chụp nó vào đề xuất (khóa `retired` bỏ, mẫu mang khóa
  không cấp được không hiện); SECURITY DEFINER vì `dw_provisioner` không đọc `platform.permission_sets`. (D4) `bind` vào
  cả mẫu `org_admin`, để bản nhân bản sau migration khớp bản cũ. (D5) `platform.check_owner_coverage` của ticket 02 bỏ
  qua tenant chưa có workspace: khóa `platform.roles.write` thành `active` làm seed (cài vai trò hệ thống trước
  workspace) ghi outbox không workspace, bảng từ chối; lỗi có từ ticket 02, khóa mới làm lộ. (D6) `PUT .../memberships`
  chỉ thay vai trò loại `role`, bộ quyền là của `PUT .../permission-sets` (chuyển từ `admin_console.py` sang
  `admin_members.py`, cùng service); workspace bị bỏ mất mọi gán, mỗi gán một lần gỡ được xét. (D7) Danh sách
  `ROLE_ROUTES_WITHOUT_BYPASS` ở `admin_roles.py`, gắn vào container nơi mount router; `get_access_context` đọc nó qua
  `route_template()` (đường dẫn đầy đủ từ `iter_route_contexts`, vì `scope["route"].path` của FastAPI 0.141 thiếu tiền tố
  `/api/v1`; lỗi này cũng làm danh sách route hỗ trợ không bao giờ khớp, sửa cùng). (D8) Đổi khóa vai trò không có route:
  `PATCH` chỉ nhận `name`, `description` (422 với cột khác); SQL thô đổi khóa bị trigger từ chối. (D9) Lần thử lại của
  route gán vai trò đọc lại đề xuất `assignment_grant` còn mở của người đó, nên trả cùng 202. (D10) Fixture test ghi hai
  cột cũ dưới `dw_migrator` ở lại tới ticket 06 (đã ghi ở Comments ticket 06). Nếu sai thì: (D1) hai hàm; (D2) gộp vào
  `assigned_grants`, đo FOG-38 lại; (D3) bỏ SECURITY DEFINER, cấp SELECT cho `dw_provisioner`; (D4) chỉ bản nhân bản;
  (D5) seed tạo workspace trước; (D6) `PUT .../memberships` thay mọi loại; (D7) dependency riêng trên từng router; (D8)
  route đổi khóa đi qua đề xuất; (D9) lưu trạng thái hiệu lực; (D10) chuyển ở đây.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): Q1 áp: `dw_provisioner` chỉ INSERT vai trò khóa `tenant_owner`, `member`,
  quyền của bản `member` tạo trong chính giao dịch, và gán `tenant_owner`; mọi ghi khác của nó trên ba bảng → 23514
  `rbac_refusals_<bảng>`, DETAIL `rbac_provisioner_scope` (test âm từng bảng). Q2 giữ: gỡ membership qua luật giữ quyền như
  mọi lần gỡ; nghỉ hưu DW thử tường minh (`test_work_queue_db.py`): Business Owner không giữ khóa của principal nhận 403
  `rbac_escalation`, Technical Owner giữ khóa nghỉ hưu được. Đây là MEDIUM (M23 dưới).
- 2026-11-05 (agent): MEDIUM, chưa sửa. (M23, Q2) Nghỉ hưu DW gỡ membership của principal, mỗi gán qua luật giữ quyền:
  Business Owner không giữ khóa của principal nhận 403 `rbac_escalation`, chỉ người giữ khóa (hay `bind` với vai trò không
  trọng yếu) nghỉ hưu được; đúng quyết Q2 (A), nhưng R1.12 của digital-worker nói chủ DW nghỉ hưu được. (M24) Người tạo DW
  giữ `platform.roles.bind` gán cho principal được vai trò không trọng yếu mình không giữ (luật `bind` của
  `platform.rbac_refusals`), khác câu "người tạo giữ mọi quyền" của digital-worker:R1.10; người thứ hai vẫn phải phủ qua
  `platform.grants_cover`. (M25) `PUT .../memberships` thay vai trò mọi workspace một lần mà không có `If-Match`: hai
  người sửa cùng lúc, lần sau ghi đè lần trước ở workspace kia. (M26) `GET /api/v1/admin/permission-sets` còn đọc mẫu
  `platform.permission_sets`, còn `PUT .../permission-sets` nhận vai trò loại `permission_set` của công ty; web đọc
  `GET /api/v1/admin/roles` cho cả hai, route cũ không còn người đọc. (M27) Trang thành viên cần `platform.roles.read` để
  gán vai trò. (M28) Lần thử lại của route gán vai trò trả đề xuất `assignment_grant` còn mở của người đó, gồm đề xuất của
  request khác. (M1, M6 của gate) hai đề xuất trùng: lần xác nhận thứ hai gặp khóa duy nhất → 409 `conflict` với
  `details.reason_code` `already_applied` hay `role_key_taken`, không 500.
- 2026-11-05 (agent): resolved. Revision `d2b57239ef50` (hai khóa, `platform.role_change_requests` cùng guard, RLS, quyền,
  `platform.role_privileges`, `platform.role_template_privileges`, `platform.rbac_refusals`, `platform.rbac_guard` trên ba
  bảng, trigger phiên bản, chủ sở hữu cuối, guard DW chuyển sang gán vai trò, ba guard của cột cũ, định danh membership và
  `created_at`), `RoleAdminService`, `RoleAssignmentService` cùng hai adapter và `role_refusals.py` (một bản dịch 23514 cho
  mọi người ghi), route `/api/v1/admin/roles`, `/role-templates`, `/role-changes`, bốn route gán vai trò qua service mới
  (202 kèm `proposals`), `ROLE_ROUTES_WITHOUT_BYPASS`, DW tạo gán vai trò trong giao dịch của nó và `draft→operating` hỏi
  `platform.grants_cover`, người đọc hiển thị chuyển sang gán vai trò, `grant_platform_admin.py` thêm không ghi đè,
  `seed_env` gán vai trò, trang thành viên đọc vai trò công ty. Test: `test_role_administration_db.py` 36 (SQL thô dưới
  `dw_app`, `dw_provisioner`, siêu người dùng), `test_role_admin_api.py` 28, `test_role_routes_without_bypass.py` 6;
  suite có sẵn chuyển sang hợp đồng mới (dw_platform 414 tệp đổi xanh, apps/api integration 200, worker
  `test_owner_coverage_db.py`), unit toàn repo 2953 xanh (độ phủ 76,86%), Vitest web 283. Bộ mới xanh ngay lần đầu, nên
  phá tay 16 mục của `mutations/03.yaml` (sao lưu, đột biến, chạy, chép trả): cả 16 đỏ, năm mục xem lý do là `DID NOT
RAISE`, không phải migration vỡ; người dựng test API phá tay thêm danh sách bỏ vượt, kiểm người thứ hai, so
  `base_version`, chỗ khóa vai trò của tạo DW (`DeadlockDetectedError`). `mutations/03.yaml` 51 mục, mỗi `old` đúng
  một lần, chưa chạy cả. reviewing-feature-security đọc theo bảng Kiểm soát RB8, RB14-RB26, RB32, RB36, RB42, RB43,
  RB48-RB50: mỗi hàng có test âm ở trigger và ở route (tenant khác, người không quyền, tự gán, đường tài khoản run-as,
  `dw_app` ghi thẳng cột cũ). Người dựng test API bắt một lỗi CRITICAL trước commit: `scope["route"].path` thiếu tiền tố
  `/api/v1`, nên danh sách bỏ vượt không bao giờ khớp; đã sửa (D7) và test đỏ khi bỏ.
- 2026-11-05 (agent): nợ lúc đóng hàng: `scripts/mutate.py` cho `mutations/03.yaml` (51); `make test-integration` đầy đủ;
  P50/P95/P99 của `GET /api/v1/admin/roles` (`assignable_by_me` cho 200 vai trò trong một câu, M2), `GET .../permissions`
  (`max_grantable_depth`), `POST /admin/roles`, `PUT .../permissions`, xác nhận, `PUT .../memberships`, lời mời và tạo DW,
  so với `94c43ee`; Playwright trang thành viên (sáng, tối, desktop, dưới 992px); `/code-review`;
  reviewing-deployment-security (route mới); checking-plan-consistency cho tenant-rbac (ticket 04 bước 7 đọc
  `platform.rbac_guard` và `platform.role_change_in_force` của ticket này).
