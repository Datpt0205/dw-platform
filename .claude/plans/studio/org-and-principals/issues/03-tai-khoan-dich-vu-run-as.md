# 03 — Tài khoản dịch vụ làm chủ thể chạy

Status: resolved
Blocked by: 02, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md, .claude/plans/studio/foundations-hardening/issues/02-hang-rao-du-lieu-va-danh-tinh.md, .claude/plans/studio/foundations-hardening/issues/03-quyen-dw-app-va-rls-initplan.md, .claude/plans/studio/app-standards/issues/01-vo-loi-problem-json.md, .claude/plans/studio/app-standards/issues/02-khoa-chong-lap-gan-nguoi-goi.md, .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md, .claude/plans/studio/digital-worker/issues/01-ho-so-dw-va-loai-quyet-dinh.md
Area: studio
Yêu cầu: R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.8, R6.9, R6.10, R6.11, R6.12, R6.13, R6.14, R6.15, R6.16, R6.17, R6.18, R6.19, R6.20, R7.1, R7.2, OP8, OP9, OP10, OP11, OP14, OP15, OP16, OP17, OP18

## Mục tiêu

Công ty có tài khoản dịch vụ: một dòng `platform.users` loại `service` thuộc tenant, giữ membership và vai trò như một
người, không bao giờ đăng nhập, không bao giờ giữ quyền trọng yếu, có một người chịu trách nhiệm là thành viên `active`,
và chỉ được gắn làm chủ thể chạy bởi người giữ mọi quyền của nó (R6, R7, YC8; ADR-0103 (Accepted) mục 2, 3, 4).
digital-worker/01 đã dựng phần tối thiểu (`be93e0c26a4c`: cột loại, `platform.service_principals`, trigger danh tính,
lọc `kind = 'human'` ở danh sách danh tính) cho service principal của Digital Worker; ticket này mở rộng chính các bảng
đó, không tạo lại (failure-modes #2). Việc gắn vào phiên bản và chạy lượt chạy dưới danh nghĩa nó thuộc
workflow-triggers và workflow-engine (R6.7); workflow-triggers đọc sự kiện `platform.service_principal.grants_changed` của
ticket này, và ticket đọc sự kiện đó của workflow-triggers chờ ticket này (DO-12). Khóa API của tài khoản dịch vụ và lane
`principal_ownership` ở W2 (ADR-0103 (Accepted) phần Consequences; DO-39.2). Công ty rời nền tảng thì lane offboarding
xóa người dùng loại `service` của nó qua một hàm SECURITY DEFINER hẹp, ở một bước đăng ký vào sổ bước xóa mà
foundations-hardening/07 dựng, thứ tự suy từ khóa ngoại `RESTRICT` và `NO ACTION` của `pg_constraint` (R6.8, R6.9;
foundations-hardening:R11.4; H-2). Bảng khác tham chiếu tài khoản dịch vụ bằng khóa ngoại ghép trong tenant (R6.10).

## Việc cần làm

Một revision Alembic (id hex của `alembic revision`; `down_revision` là head lúc commit, sau `555dad01f629` của ticket 04
nếu nó đã vào `main`).

1. **Người dùng loại dịch vụ: đã có, không đổi.** `platform.users.kind`, `owner_tenant_id`, `ck_users_kind`,
   `ck_users_service_has_owner_tenant`, khóa ngoại và `ix_users_owner_tenant_id` có từ
   `db/migrations/versions/be93e0c26a4c_platform_digital_workers.py:82-93`; giữ tên. Người dùng do route của bước 6 tạo
   có `subject` `service:<uuid>`, `email` NULL, `display_name` bằng `name`, `owner_tenant_id` lấy từ AccessContext, như
   `digital_workers_repo.py:115-124` (không bao giờ từ thân request).
2. **Dòng chi tiết: mở rộng `platform.service_principals`** (`be93e0c26a4c_platform_digital_workers.py:97-115`):
    - thêm `description text CHECK (description IS NULL OR char_length(description) <= 1000)`; `created_by uuid NULL` FK
      `platform.users` `ON DELETE SET NULL`, index `ix_service_principals_created_by`;
      `updated_at timestamptz NOT NULL DEFAULT now()` với trigger `touch_updated_at` (`platform.touch_updated_at()`);
    - thay `ck_service_principals_name` bằng `CHECK (btrim(name) <> '' AND char_length(name) <= 120)`, cùng tên; dòng cũ
      vi phạm làm migration dừng và in số dòng, không sửa tên tự động;
    - `uq_service_principals_tenant_id_name UNIQUE (tenant_id, name)`; trước khi thêm, mỗi dòng trùng `(tenant_id, name)`
      với một dòng sớm hơn (theo `created_at`, rồi `user_id`) đổi tên thành
      `left(name, 108) || ' (' || left(user_id::text, 8) || ')'` và migration in số dòng đã đổi; vi phạm ràng buộc này ở `POST` của bước 6 và ở tạo DW
      (`SqlDigitalWorkerRepository.create`) đều thành 409 `service_principal_name_taken`;
    - `uq_service_principals_tenant_id_user_id` đã có: đích của khóa ngoại ghép mà bảng khác dùng (R6.10), giữ;
    - không thêm khóa ngoại `(tenant_id, user_id)` tới `platform.tenant_members`: với nó, bước xóa
      `platform.tenant_members` của offboarding cascade vào tài khoản dịch vụ trước bước xóa `platform.digital_workers`
      (quyết định H8 của spec); một tài khoản không có dòng thành viên công ty đọc như không `active` (R6.17);
    - RLS (ENABLE, FORCE, policy tenant) và dòng `_TENANT_WIDE_ON_PURPOSE` của `test_rls_coverage.py` đã có, giữ;
    - `dw_app` giữ SELECT, INSERT, UPDATE, DELETE (`be93e0c26a4c_platform_digital_workers.py:389`): bảng ở trong
      catalog xóa được (bước mặc định, sau `platform.digital_workers` theo `fk_digital_workers_principal`), nên test phủ
      offboarding không cần dòng `STUDIO_EXCLUSIONS`;
    - R6.11: `platform.guard_service_user_tenant()`, SECURITY DEFINER, `search_path` cố định, thu EXECUTE khỏi `PUBLIC`,
      trigger BEFORE INSERT OR UPDATE OF `tenant_id`, `user_id` trên `platform.tenant_members`: người dùng loại
      `service` mà `tenant_id` khác `owner_tenant_id` → SQLSTATE 23514, ràng buộc `ck_tenant_members_service_own_tenant`,
      áp mọi người ghi; membership theo sau nhờ FK của ticket 02. Hoạt động hay tạm khóa vẫn là
      `platform.tenant_members.status`, một sự thật một chỗ.
3. **Không đăng nhập: phần còn thiếu.** Trigger `external_identities_human_only`
   (`be93e0c26a4c_platform_digital_workers.py:304`) đã từ chối danh tính cho người dùng không `human` ở mọi người ghi; nó
   là guard của R6.3, không thêm guard thứ hai và không sửa `platform.guard_privileged_login_identity()`. Nhánh issuer dev
   khớp `users.subject` mà không xét loại ở `membership_lookup.py:279-283` (`find_access`) và `identity_provisioning.py:181-186`
   (`_resolve_user`): nhánh đó chỉ khớp `kind = 'human'`, và khi `subject` thuộc một người dùng `service`, `_resolve_user`
   từ chối 403 và không tạo người dùng nào; nhánh email (`identity_provisioning.py:188-193`) cũng lọc `kind = 'human'`.
4. **Không quyền trọng yếu, và sự kiện khi quyền được gán tăng.** `platform.guard_service_principal_grants()`, SECURITY
   DEFINER, `search_path` cố định, thu EXECUTE khỏi `PUBLIC`, theo dạng của `platform.guard_operator_tenant_grants()`
   (`b5677d345bc1_tenant_roles.py:881`): trigger BEFORE INSERT OR UPDATE tên `guard_service_principal_grants` trên
   `platform.role_assignments` (người nhận loại `service` mà `platform.role_is_critical` của vai trò đúng), trên
   `platform.tenant_role_permissions` (thêm hay đổi sang khóa có `platform.permissions.risk = 'critical'` trong vai trò
   đang gán cho một tài khoản dịch vụ) và BEFORE UPDATE OF `deleted_at` trên `platform.tenant_roles` (khôi phục vai trò
   mà `platform.role_is_critical` đúng), SQLSTATE 23514, ràng buộc `ck_role_assignments_service_not_critical`, áp mọi
   người ghi kể cả `dw_provisioner`, `dw_migrator`. Migration tạo `platform.role_is_critical(p_tenant_id uuid, p_role_id
uuid) RETURNS boolean`, `LANGUAGE sql STABLE`: vai trò là `tenant_owner` hay có một khóa `risk = 'critical'`; đó là
   chủ duy nhất của "vai trò trọng yếu" (ADR-0104 (Accepted) quyết 6, Amendments 2026-11-03): luật `platform.roles.bind`
   của `platform.rbac_refusals`, `_check_roles` của route DW và kiểm sớm của route gán vai trò ở tenant-rbac/03 đọc nó,
   tenant-rbac/04 thêm `fld.*` trên trường nhạy cảm vào nó. Mỗi nhánh khóa dòng `platform.tenant_roles` của vai trò
   `FOR NO KEY UPDATE` trước khi đọc, nên gán vai trò và thêm khóa `critical` vào vai trò đó trong hai giao dịch đồng thời
   không cùng qua; không khóa advisory, vì tenant-rbac/03 khóa chính dòng đó lúc xác nhận, và một khóa advisory lấy trước
   `KEY SHARE` của khóa ngoại trong giao dịch này, cộng khóa dòng của giao dịch kia lấy trước khóa advisory, là bế tắc
   (40P01). Nhánh `platform.role_assignments` chỉ khóa khi người nhận là `kind = 'service'`, nhánh
   `platform.tenant_role_permissions` chỉ khi khóa đưa vào có `risk = 'critical'`, nhánh `platform.tenant_roles` đã giữ
   dòng qua chính câu UPDATE; gán vai trò cho người `human` không khóa gì. **Thứ tự khóa** (agent, theo ủy quyền
   31/10/2026): dòng `platform.tenant_roles` (nhiều dòng thì theo `id` tăng) luôn trước dòng
   `platform.tenant_access_versions` của tenant, mà `trg_z_bump_access_version` (`b5677d345bc1_tenant_roles.py:752`,
   `:1153`) UPDATE ở mọi lần ghi một bảng của `_BUMPED_TABLES`, gồm `platform.tenant_members` và `platform.memberships`.
   Tạo DW (`SqlDigitalWorkerRepository.create`, `digital_workers_repo.py:113-189`) ghi hai bảng đó trước gán vai trò, nên
   giữ dòng phiên bản rồi mới tới guard; người khóa dòng vai trò trước rồi mới ghi bảng quyền (xác nhận của tenant-rbac/03
   bước 4, mọi UPDATE `platform.tenant_roles`) đi ngược chiều, và hai bên vẫn bế tắc qua dòng phiên bản dù không còn khóa
   advisory. Vì vậy câu đầu của giao dịch tạo DW, sau `claim_effect_key` và trước `INSERT platform.users`, là `SELECT id
FROM platform.tenant_roles WHERE tenant_id = :t AND key = ANY(:role_keys) AND deleted_at IS NULL ORDER BY id FOR NO
KEY UPDATE` (`dw_app` có UPDATE trên bảng, `b5677d345bc1_tenant_roles.py:1251`); vai trò chưa có thì lần đồng bộ tạo
   mới, không ai khác thấy dòng đó; guard lấy lại khóa đã giữ, không chờ. Trigger nào khóa dòng vai trò trong một lần ghi
   bảng quyền có tên đứng trước `trg_z_` theo bảng chữ cái. Nếu sai thì: lần xác nhận của tenant-rbac/03 cập nhật dòng
   phiên bản trước khi khóa dòng vai trò, qua một hàm SECURITY DEFINER, vì `dw_app` không có UPDATE trên
   `platform.tenant_access_versions`. Trigger này
   riêng với trigger của `platform.rbac_refusals` (tenant-rbac/03), vốn miễn hai vai đó; ticket này không chờ tenant-rbac/03
   (Đạt chấp nhận, OPS-b), còn tenant-rbac/03 chờ ticket này vì đọc `platform.role_is_critical` và
   `platform.holder_covers_grant` của nó: tên của nó đứng trước `rbac_refusals_*` theo bảng chữ cái nên bắn trước; test catalog của
   ticket này chỉ khẳng định trigger `guard_service_principal_grants` có trên ba bảng. Kiểm `is_critical_role` của
   `digital_workers.py:88` ở lại làm lỗi sớm 422 của route DW tới khi tenant-rbac/03 bước 11 thay nó bằng
   `platform.role_is_critical`; trigger là chỗ quyết, và route gán vai trò của
   tenant-rbac cùng route DW đổi lỗi `ck_role_assignments_service_not_critical` thành 422
   `role_not_allowed_for_service` theo tên ràng buộc. Trước khi tạo trigger, migration dừng và in số dòng nếu một tài
   khoản dịch vụ đã giữ `tenant_owner` hay một khóa `critical`; không gỡ vai trò tự động. Trigger AFTER
   `service_principal_grants_changed` cùng họ (cùng khóa dòng vai trò) ghi một dòng `platform.outbox_events`
   `platform.service_principal.grants_changed` (`workspace_id` là `owning_workspace_id`, payload `tenant_id`,
   `service_principal_id`), theo dạng của `platform.tenant.owner_coverage_low` (`b5677d345bc1_tenant_roles.py:978`), cho
   mỗi tài khoản dịch vụ mà một dòng ghi làm quyền được gán (`platform.assigned_grants`) tăng: INSERT
   `platform.role_assignments`; UPDATE của nó đổi `role_id` hay đặt `expires_at` muộn hơn hoặc NULL; INSERT
   `platform.tenant_role_permissions`, hay UPDATE đổi khóa hoặc đào sâu `depth`, của vai trò đang gán cho tài khoản;
   UPDATE `platform.tenant_roles.deleted_at` từ khác NULL về NULL của vai trò đang gán cho tài khoản (R6.6); UPDATE đổi
   `membership_id`, `workspace_id` của `platform.role_assignments` hay `role_id` của `platform.tenant_role_permissions`
   tính như một lần gán mới. Danh sách ca này là định nghĩa của "tăng": một khóa tài khoản đã giữ qua vai trò khác vẫn
   phát một sự kiện, và người đọc chỉ đưa binding về duyệt lại. Người đọc là
   workflow-triggers, đưa binding `principal` về `binding_needs_review` tới khi người phủ đủ quyền duyệt lại (DO-12); sự
   kiện cho service principal của DW không có người đọc nào hành động, vì nó không gắn được (bước 7). Relay outbox không
   nhận loại sự kiện chưa có handler (`apps/worker/src/dw_worker/consumers/outbox.py:18-22`), nên tới khi handler của
   workflow-triggers vào, các dòng này nằm chờ, để handler đó thấy đủ lịch sử.
5. **Khóa quyền.** Migration thêm `platform.service_principals.manage` và `platform.service_principals.use` (`scope_kind`
   `workspace`, `risk` `elevated`, `tenant_grantable` true, `status` `active`) vào `platform.permissions` theo quy ước của
   `ebb17244abc6_permission_catalogue.py` và danh mục khóa của tenant-rbac/01. `dw.manage` vẫn là quyền tạo service
   principal của DW (digital-worker, quyết định 29/10/2026).
6. **Route** (phong bì lỗi của ADR-0108 (Accepted); `Idempotency-Key` gắn người gọi của app-standards:R2.2, tùy chọn
   trên `POST` như mọi lệnh tạo một dòng, ADR-0108 (Accepted) quyết 4):
    - `POST /api/v1/admin/service-principals` (`platform.service_principals.manage` với tới `owning_workspace_id`): thân
      `name`, `description`, `owning_workspace_id`, `owner_user_id`; trước hết kiểm workspace thuộc tenant người gọi (không
      thì 422 dưới đây), rồi mới tới tầm với (không thì 403); một giao dịch ghi người dùng loại `service` (bước 1),
      thành viên công ty `active` (`ensure_tenant_member`), membership ở workspace sở hữu (không vai trò), dòng chi tiết
      với `created_by` là người gọi, audit `platform.service_principal.created` chỉ có id. Workspace không thuộc tenant hay
      không tồn tại → 422 `validation_failed` với pointer `/owning_workspace_id`, như nhau; `owner_user_id` không là thành
      viên `human` `active` → 422 `owner_not_member` (bộ ghi đổi lỗi `ck_service_principals_accountable_owner` theo tên
      ràng buộc); tên trùng → 409 `service_principal_name_taken`. Vai trò gán qua API gán vai trò của tenant-rbac, hai
      người như mọi thành viên (D11).
    - `GET /api/v1/admin/service-principals`: chỉ tài khoản của tenant người gọi, không là service principal của DW, có
      workspace sở hữu trong `platform.workspace_reach` của người
      gọi cho `.manage` hay `.use` (R6.12); trả `id`, `name`, `description`, `owning_workspace_id`, `owner_user_id`,
      `owner_missing` (bằng `NOT platform.accountable_owner_present`), `status` (từ `platform.tenant_members`),
      `bindable_by_me`; sắp theo `name`, keyset trên `uq_service_principals_tenant_id_name`, tối đa 50 dòng một trang.
    - `PATCH /api/v1/admin/service-principals/{service_principal_id}` (`name`, `description`, `owner_user_id`): id không
      là tài khoản dịch vụ không phải DW của tenant người gọi → 404 `not_found` (R6.13); thiếu `.manage` với tới workspace
      sở hữu → 403 (R6.14); cùng lỗi 422, 409 như `POST`; audit `platform.service_principal.updated` chỉ có id (cả id người
      chịu trách nhiệm cũ và mới khi nó đổi). Không `If-Match` ở W1 (bảng không có phiên bản dòng): ghi sau thắng.
    - "Là service principal của DW" đọc qua `platform.is_digital_worker_principal(p_user_id uuid) RETURNS boolean`,
      SECURITY DEFINER, `search_path` cố định, thu EXECUTE khỏi `PUBLIC`, cấp EXECUTE cho `dw_app`: có dòng
      `platform.digital_workers` với `principal_user_id = p_user_id` và `tenant_id` bằng `app.tenant_id`; chỉ trả boolean.
      Một `NOT EXISTS` dưới RLS của người gọi không đủ, vì `platform.digital_workers` hẹp theo workspace
      (`be93e0c26a4c_platform_digital_workers.py:248`): DW ở workspace khác sẽ lọt.
7. **Bộ kiểm gắn.** `ServicePrincipalBindingGuard.require_bindable(context, service_principal_id)` trong `dw_platform`,
   theo thứ tự: (a) đọc tài khoản dưới RLS của người gọi; không thấy, là service principal của DW, hay là người dùng
   `human` (cờ DW qua `platform.is_digital_worker_principal`) → 404 `not_found`, không nêu quyền nào (R6.15); (b) thiếu `platform.service_principals.use` với tới workspace
   sở hữu → 403 `rbac_escalation` nêu khóa đó; (c) tài khoản không `active` → 409 `principal_inactive`; (d)
   `platform.accountable_owner_present` false → 409 `owner_missing` (R6.17); (e) `platform.uncovered_grants(tenant, người
gọi, tài khoản)` có dòng → 403 `rbac_escalation` kèm danh sách khóa thiếu (khóa, độ sâu, workspace neo). Migration tạo
   `platform.holder_covers_grant(p_tenant_id uuid, p_holder_id uuid, p_permission_key text, p_depth text,
p_anchor_workspace_id uuid) RETURNS boolean` từ điều kiện bên trong của `platform.grants_cover`
   (`b5677d345bc1_tenant_roles.py:455`: người giữ có khóa ở mức `tenant`, hay ở cùng neo với mức bằng hoặc rộng hơn),
   `platform.uncovered_grants(p_tenant_id uuid, p_holder_id uuid, p_subject_id uuid) RETURNS TABLE (permission_key,
depth, anchor_workspace_id)` là quyền hiệu lực của chủ thể mà hàm đó trả false, và viết lại `platform.grants_cover`
   thành `NOT EXISTS (SELECT 1 FROM platform.uncovered_grants(...))`, cùng nghĩa, để luật phủ quyền có một chủ: luật giữ
   quyền của `platform.rbac_refusals` (tenant-rbac/03) đọc `platform.holder_covers_grant` cho từng quyền một thay đổi
   đưa vào, không chép điều kiện; test của tenant-rbac/02 về `grants_cover` giữ xanh. `bindable_by_me` gọi cùng phương thức.
   Ticket này dựng bộ kiểm trong `apps/api/src/dw_api/bootstrap/wiring.py` cho `GET`; bên gắn (workflow-triggers, bộ
   kiểm binding của tenant-config) khai Protocol của mình ở ticket của họ và wiring đáp ứng bằng chính đối tượng này.
8. **Mặt danh tính lọc loại.** `/directory/candidates` đã lọc `tables.HUMAN` (`directory.py:109`): ticket thêm test.
   `GET /api/v1/platform/users` (`platform.py:101`, `provisioning_repo.py:178-187`) hôm nay chỉ lọc `email IS NOT NULL`:
   thêm `tables.HUMAN`. Một test liệt kê mọi câu đọc `platform.users` mà một route dùng.
9. **Offboarding.** Migration thêm `platform.purge_tenant_service_users(p_tenant uuid) RETURNS integer`, SECURITY
   DEFINER, `search_path` cố định, thu EXECUTE khỏi `PUBLIC`, cấp EXECUTE cho `dw_app`: từ chối với SQLSTATE 23514 khi
   `platform.tenants.status` của `p_tenant` khác `offboarding` (R6.9) hay khi `p_tenant` khác `app.tenant_id` của giao
   dịch (giao dịch xóa đặt nó, `offboarding.py:532`); không thì xóa dòng `platform.users` có
   `kind = 'service' AND owner_tenant_id = p_tenant` và trả số dòng đã xóa; `test_privileges.py` khẳng định `dw_app` có
   EXECUTE còn `PUBLIC` thì không. Ở composition root của worker (`apps/worker/src/dw_worker/main.py`), đăng ký vào
   `OffboardingPurgeSteps` một bước tên `platform.purge_tenant_service_users` (như `platform.purge_tenant_access_version`)
   khai `frozenset({"platform.users"})`, chạy hàm đó với `:t` trong giao dịch xóa. Thứ tự suy từ `pg_constraint`
   (`order_purge_steps`): bước chạy sau mọi bước xóa bảng giữ khóa ngoại `RESTRICT` hay `NO ACTION` tới `platform.users`
   (ba cột người của `platform.digital_workers`; `platform.support_grants.staff_user_id`, mà cascade từ
   `platform.workspaces` mang sang bước xóa workspace, nên `_refuse_blocked` của `offboarding.py:476-510` không chặn);
   dòng `platform.service_principals` đã đi ở bước mặc định của nó, sau `platform.digital_workers`; không danh sách tay
   nào đặt bước "sau cùng". Việc xóa đi qua hàm vì `dw_app` không có DELETE trên `platform.users`
   (foundations-hardening:R5.1), và dòng `platform.tenants` ở lại `offboarded` nên CASCADE của `owner_tenant_id` không bao
   giờ chạy. `test_offboarding.py` purge một tenant có một tài khoản dịch vụ, một DW và một dòng
   `platform.support_grants`, khẳng định không còn dòng
   `platform.service_principals` nào và không còn người dùng loại `service` nào của tenant đó, còn người dùng `human` và
   tài khoản dịch vụ của tenant khác giữ nguyên; cùng tệp, một bảng thử `platform.zz_service_user_holder` (`tenant_id`,
   cột `user_id` FK `platform.users` `ON DELETE RESTRICT` trỏ tài khoản dịch vụ, SELECT và DELETE cho `dw_app`), do
   `dw_migrator` tạo và commit trong fixture rồi xóa ở teardown (purge chạy ở giao dịch riêng nên không thấy bảng chưa
   commit); tên bước `platform.purge_tenant_service_users` xếp trước tên bảng thử theo bảng chữ cái, nên chỉ cạnh của
   catalog đặt bước sau nó; một test bắt câu lệnh bằng sự kiện `before_cursor_execute` khẳng định bước chạy sau câu xóa
   bảng thử đó.
10. **Người chịu trách nhiệm** (R6.16-R6.20; ADR-0103 (Accepted) quyết 3; quyết định 3/11/2026 của spec):
    - trước khi đổi khóa ngoại, migration đặt `owner_user_id = NULL` ở dòng không có dòng `platform.tenant_members`
      `(tenant_id, owner_user_id)` và in số dòng; rồi thay `fk_service_principals_owner_user_id_users` bằng FK
      `(tenant_id, owner_user_id)` tới `platform.tenant_members` `ON DELETE SET NULL (owner_user_id)`, tên theo
      `NAMING_CONVENTION`, và `ix_service_principals_owner_user_id` bằng index `(tenant_id, owner_user_id)`;
    - `platform.guard_accountable_owner()` (`be93e0c26a4c_platform_digital_workers.py:264`) viết lại, giữ nhánh
      `ck_service_principals_service_user` như cũ: INSERT với `owner_user_id` NULL bị từ chối; ở INSERT, và ở UPDATE khi
      `owner_user_id` đổi giá trị, mọi giá trị khác NULL phải là dòng `platform.tenant_members` `status = 'active'` của
      người dùng `human` cùng tenant (một UPDATE chỉ đổi tên không kiểm lại người chịu trách nhiệm); UPDATE về NULL được
      nhận, vì đó là hành động `SET NULL` của khóa ngoại, còn `PATCH` với `owner_user_id: null` trả 422
      `validation_failed` ở tầng request; lỗi giữ `ck_service_principals_accountable_owner`;
    - `platform.accountable_owner_present(p_tenant_id uuid, p_principal_id uuid) RETURNS boolean`, `LANGUAGE sql STABLE`,
      không SECURITY DEFINER: có dòng `platform.service_principals` với `owner_user_id` khác NULL và dòng
      `platform.tenant_members` của người đó `status = 'active'`. Hai người đọc: bộ kiểm gắn (bước 7, dưới RLS của người
      gọi) và `platform.dw_work_scopes_due` (`cfbd906be98b_platform_work_items.py:183-202`), mà migration viết lại để thay
      `p.owner_user_id IS NOT NULL` bằng hàm này (R6.18); nhánh thu hồi việc `in_progress` quá 15 phút giữ nguyên. Lần
      nhận dưới scope (`claim_due`, `work_queue_repo.py:240-243`) giữ cùng luật ở lớp thứ hai và đổi
      `_P.c.owner_user_id.is_not(None)` sang cùng hàm, vì một DW khác cùng workspace tới hạn làm hàm quét trả cặp đó;
    - `SqlDwMembershipCheck._standing` (`digital_workers_repo.py:458-473`), mà `standing` và `is_person_in` cùng đọc, join
      `platform.tenant_members` với `status = 'active'`: người không `active` đọc như không có membership, nên route DW trả
      422 `owner_not_member` (R6.19) và cửa hàng đợi trả `handoff_target_invalid` (R6.20) mà không thêm nhánh nào;
    - người đọc thứ ba của `standing` là `_second_person` (`digital_workers.py:424-438`, digital-worker:R1.9): principal
      của DW không `active` đọc như không có membership, nên quyền nó giữ là tập rỗng và mọi người gọi phủ được; hôm nay
      cũng thế, vì `platform.effective_grants` đã rỗng với thành viên không `active`. `_second_person` từ chối 409
      `principal_inactive` khi `standing` của principal là `None`, trước phép so quyền, như bước 7 (c) với bộ kiểm gắn;
      tenant-rbac/03 bước 11 giữ nhánh này khi chuyển phép so sang `platform.grants_cover`. `_standing` đọc loại, `status`
      và quyền trong một câu lệnh, một snapshot (agent, theo ủy quyền 31/10/2026): hôm nay quyền đọc ở câu thứ hai
      (`effective_scopes`), nên một lần `suspended` commit giữa hai câu cho `status` `active` cùng tập quyền rỗng, và lỗ
      trên mở lại. Một lần `suspended` sau câu đó, trước UPDATE `state`, không mở lỗ, vì phép so đã chạy trên quyền thật
      của principal. Nếu sai thì: `_standing` mở giao dịch `REPEATABLE READ`;
    - không lời báo nào ở W1: lane `principal_ownership` ở W2 (DO-39.2); `GET` của bước 6 trả `owner_missing`.

## Tiêu chí chấp nhận

- [x] R6.1: `POST /api/v1/admin/service-principals` → người dùng `service` (`subject` `service:<uuid>`, `email` NULL), thành viên công ty `active`, membership, dòng chi tiết có `owner_user_id` và `created_by`, và một audit cùng giao dịch; lỗi giữa giao dịch → không dòng nào; người không có `platform.service_principals.manage` → 403; `owning_workspace_id` của tenant khác và id ngẫu nhiên → cùng 422 `validation_failed`; tên trùng → 409 `service_principal_name_taken`.
- [x] R6.2 (OP8): token dev mang `subject` của tài khoản dịch vụ → 403 ở `bootstrap` và ở `find_access`, không AccessContext, không thêm dòng `platform.users` nào; gỡ điều kiện `kind = 'human'` khỏi một trong hai nhánh dev → test đỏ.
- [x] R6.3 (OP8): INSERT `platform.external_identities` cho tài khoản dịch vụ, dưới `dw_app` và `dw_provisioner` → trigger `external_identities_human_only` từ chối; gỡ trigger → đỏ.
- [x] R6.4 (OP9): dưới `dw_migrator` gán `tenant_owner` cho tài khoản dịch vụ → 23514; thêm khóa `critical` vào vai trò đang gán cho nó → 23514; khôi phục vai trò như thế đã xóa mềm → 23514; cùng thao tác qua route gán vai trò → 422 `role_not_allowed_for_service`; hai kết nối, mỗi bên mở giao dịch, một gán vai trò R cho tài khoản, một thêm khóa `critical` vào R, commit cả hai → đúng một bên nhận 23514; test catalog thấy trigger `guard_service_principal_grants` trên `platform.role_assignments`, `platform.tenant_role_permissions` và `platform.tenant_roles`; gỡ trigger, gỡ khóa dòng vai trò khỏi một nhánh, hay thay `platform.role_is_critical` bằng `false` → đỏ; kết nối B khóa dòng vai trò R `FOR NO KEY UPDATE` như lần xác nhận của tenant-rbac/03 (không UPDATE nó, vì UPDATE đã giữ cả dòng phiên bản) và chờ, A tạo DW với R qua `SqlDigitalWorkerRepository.create` tới khi `pg_locks` cho thấy A chờ khóa, B INSERT một khóa không trọng yếu vào R rồi commit → A xong, không bên nào nhận 40P01; dời câu khóa vai trò đầu giao dịch của tạo DW xuống sau `ensure_tenant_member` → 40P01, đỏ; gán vai trò cho người `human` không lấy khóa dòng vai trò (`pg_locks` trong giao dịch).
- [x] R6.5 (OP10): người gọi thiếu một khóa tài khoản đang giữ → 403 `rbac_escalation` nêu khóa đó, độ sâu và workspace neo; thiếu `platform.service_principals.use` → 403 nêu `platform.service_principals.use`; thay `platform.uncovered_grants` bằng tập rỗng → đỏ, kể cả ở các ca `grants_cover` của test tenant-rbac/02; `bindable_by_me` false cho tài khoản mà người gọi thiếu một khóa và true cho tài khoản họ phủ.
- [x] R6.6: gán vai trò cho tài khoản dịch vụ → đúng một dòng `platform.outbox_events` `platform.service_principal.grants_changed` cùng giao dịch; gia hạn `expires_at`, thêm khóa vào vai trò đang gán, đào sâu `depth`, khôi phục vai trò đã xóa mềm → mỗi lần một dòng; gán vai trò cho tài khoản `suspended` → một dòng; đưa tài khoản từ `suspended` về `active`, rút ngắn hạn, gỡ khóa hay UPDATE chỉ đổi `assigned_by` → 0 dòng; gỡ một trong các ca khỏi trigger → ca đó đỏ.
- [x] R6.8 (OP14): purge một tenant `offboarding` có một tài khoản dịch vụ, một DW và một dòng `platform.support_grants` → không còn dòng `platform.users` loại `service` có `owner_tenant_id` của tenant đó, không còn dòng `platform.service_principals` của nó, người dùng loại `human` và tài khoản dịch vụ của tenant khác còn; gỡ bước `platform.purge_tenant_service_users` khỏi sổ → `test_offboarding.py` đỏ; bảng thử `platform.zz_service_principal_holder` → bước chạy sau câu xóa bảng thử; đổi khai của bước sang bảng khác `platform.users` → ca thứ tự đó đỏ; tenant có dòng `platform.support_grants` → purge xong, không lỗi khóa ngoại.
- [x] R6.9 (OP14): gọi `platform.purge_tenant_service_users` dưới `dw_app` cho tenant `active` → 23514 và 0 dòng bị xóa; cho tenant `offboarding` khác `app.tenant_id` của giao dịch → 23514 và 0 dòng; gỡ kiểm trạng thái hay kiểm tenant khỏi hàm → test đỏ.
- [x] R6.10 (OP15): bảng thử có khóa ngoại ghép `(tenant_id, sp_id)` tới `platform.service_principals (tenant_id, user_id)`, INSERT `(tenant_B, tài khoản dịch vụ của A)` → lỗi FK, không dòng nào; test catalog thấy `uq_service_principals_tenant_id_user_id` trong `pg_constraint`; bỏ ràng buộc → test đỏ.
- [x] R6.11 (OP16): INSERT `platform.tenant_members (tenant_B, tài khoản dịch vụ của A)` dưới `dw_app` và `dw_provisioner` → 23514, 0 dòng; UPDATE `tenant_id` của dòng thành viên của nó sang B → 23514; gỡ trigger → đỏ.
- [x] R6.12 (OP17): quản trị viên tenant B gọi `GET` → không có tài khoản của A; người chỉ giữ `.use` ở workspace khác workspace sở hữu → không có tài khoản đó; người giữ `.manage` ở độ sâu tenant đứng ở W1 và một DW ở W2 → principal của DW không có; gỡ lọc tenant, lọc DW hay lọc tầm với, hay thay `platform.is_digital_worker_principal` bằng `NOT EXISTS` dưới RLS → đỏ.
- [x] R6.13 (OP17): `PATCH` id tài khoản của A (người gọi ở B), id service principal của một DW (cùng và khác workspace người gọi), id người dùng `human`, id ngẫu nhiên → cùng 404 `not_found`, dòng không đổi; gỡ lọc DW → đỏ.
- [x] R6.14 (OP17): `PATCH` của người không có `.manage` với tới workspace sở hữu → 403, dòng không đổi; gỡ kiểm → đỏ.
- [x] R6.15 (OP17): bộ kiểm gắn với bốn id của R6.13 → 404 không nêu khóa nào; bỏ bước (a) của bộ kiểm → ca id của A đỏ (vì `platform.grants_cover` trả `true` rỗng).
- [x] R6.16 (OP18): INSERT `platform.service_principals` với `owner_user_id` NULL, người `suspended`, người `invited`, người của tenant B, người dùng `service` → 23514; `PATCH` `owner_user_id` sang người `suspended` → 422 `owner_not_member`; xóa dòng thành viên công ty của người chịu trách nhiệm → `owner_user_id` về NULL, dòng tài khoản còn; gỡ điều kiện `status = 'active'` khỏi guard → đỏ.
- [x] R6.17 (OP18): người chịu trách nhiệm `suspended` → bộ kiểm gắn 409 `owner_missing` và `GET` trả `owner_missing` true; `owner_user_id` NULL → như trên; tài khoản `suspended` → 409 `principal_inactive`; gỡ điều kiện `status` khỏi `platform.accountable_owner_present` → đỏ.
- [x] R6.18 (OP18): DW `operating` có việc `open` tới hạn, người chịu trách nhiệm `suspended` → `platform.dw_work_scopes_due` không trả cặp của nó; một DW khác cùng workspace có việc tới hạn → `claim_due` nhận việc của DW kia, không nhận việc của DW này; người đó `active` lại → nhận ở lần quét kế; việc `in_progress` quá 15 phút của DW đó vẫn được trả; thay hàm bằng `owner_user_id IS NOT NULL` ở hàm quét → ca hàm quét đỏ; ở `claim_due` → ca `claim_due` đỏ.
- [x] R6.19 (OP18): tạo DW với Validator `suspended` → 422 `owner_not_member`, không dòng nào; gỡ join `status = 'active'` khỏi `_standing` → đỏ.
- [x] R6.19 (OP18): theo digital-worker:R1.9, principal của một DW `draft` bị `suspended`, người thứ hai không giữ khóa nào của nó gọi `draft→operating` → 409 `principal_inactive`, DW vẫn `draft`; principal `active` lại → 403 `grants_not_covered`; gỡ nhánh `principal_inactive` → ca đầu nhận 200 và test đỏ; bắt câu lệnh bằng `before_cursor_execute` trong `standing` → đúng một câu đọc, tách lại thành hai câu → đỏ.
- [x] R6.20 (OP18): bàn giao việc cho người `suspended` → `handoff_target_invalid`, việc không đổi; gỡ join `status = 'active'` khỏi `_standing` → đỏ.
- [x] R7.1 (OP11): quản trị viên tenant B gọi `GET /api/v1/directory/candidates` → không có tài khoản dịch vụ của A hay B; gỡ lọc `kind` → đỏ.
- [x] R7.2 (OP11): `GET /api/v1/platform/users` → không dòng `service`, kể cả một tài khoản dịch vụ thử có `email` khác NULL ghi bằng SQL; gỡ lọc `kind` → đỏ.
- [x] Xong: các cổng nhanh của ticket xanh (wave-close.md); `make ci` đầy đủ, mutate.py và đo trễ ở lúc đóng hàng đợi.

## Nguồn

- `db/migrations/versions/be93e0c26a4c_platform_digital_workers.py:82-115`, `:264`, `:304`, `:389`; spec: R6.1, R6.3, R6.16.
- `db/migrations/versions/cfbd906be98b_platform_work_items.py:183-202`; spec: R6.18.
- `db/migrations/versions/b5677d345bc1_tenant_roles.py:455`, `:881`, `:978`; spec: R6.4, R6.5, R6.6.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:279-283`; spec: R6.2.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:181-193`; spec: R6.2.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/digital_workers_repo.py:115-124`, `:458-473`; spec: R6.1, R6.19, R6.20.
- `apps/api/src/dw_api/routes/v1/directory.py:65-78`, `packages/python/dw_platform/src/dw_platform/adapters/persistence/directory.py:109`; spec: R7.1.
- `apps/api/src/dw_api/routes/v1/platform.py:101`, `packages/python/dw_platform/src/dw_platform/adapters/persistence/provisioning_repo.py:178-187`; spec: R7.2.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:530-537`, `apps/worker/src/dw_worker/main.py`; spec: R6.8, R6.9; foundations-hardening:R11.4.
- ADR-0103 (Accepted) mục 1, 2, 3, 4; brief B2 ticket 07 và mục 9.

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
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): gate checking-plan-readiness (builder check và boundary walk, ba subagent),
  3 CRITICAL và 6 HIGH, sửa hết; quyết định ghi ở Quyết định 3/11/2026 của spec. C1, C2: ghi chéo tenant có R6.11-R6.15,
  OP16, OP17 và test âm (bước 2, 6, 7). C3 và khoảng trống người chịu trách nhiệm hay người duyệt không `active`: bước 10,
  R6.16-R6.20, OP18. H1, H2: bước 1-3, 8 viết lại thành phần mở rộng trên `be93e0c26a4c` (tên ràng buộc, `subject`
  `service:`, trigger `external_identities_human_only`, DELETE của `dw_app` giữ nguyên, không `STUDIO_EXCLUSIONS`); khóa
  API và lane `principal_ownership` ở W2, nên ngoặc "(khóa API, binding, `owner_user_id` theo `tenant_members`, lane
  `principal_ownership`)" của dòng 2026-10-29 chỉ còn đúng ở `owner_user_id` theo `tenant_members` (bước 10) và bộ kiểm
  gắn (bước 7); service principal của DW không có trên mặt quản trị và không gắn được. H3: R6.6 theo quyền được gán, bộ
  kiểm gắn từ chối tài khoản không `active`. H4: khóa theo vai trò ở guard và trigger sự kiện. H5: danh sách khóa thiếu
  từ `platform.uncovered_grants`, `grants_cover` viết lại trên nó. H6: ca R6.8 "test phủ studio-skeleton:R4.2 đỏ" không
  đỏ được, thay bằng ca thứ tự. Nếu sai thì: xem từng dòng Quyết định 3/11/2026 của spec.
- 2026-11-03 (agent): ghi chú MEDIUM của gate cho người dựng, chưa sửa: (M1) neo cũ của ticket đã thay bằng neo đọc ở
  `992bf74`; `Blocked by` giữ nguyên, mọi ticket trong đó đã `resolved`. (M2) hai mã cho một luật phủ quyền:
  `grants_not_covered` của route DW (`digital_workers.py:392-396`, so scope bằng Python) và `rbac_escalation` ở đây;
  `is_critical_role` của DW và `risk = 'critical'` ở trigger là hai định nghĩa "trọng yếu" (failure-modes #2): trigger
  quyết, nhưng hai bên có thể lệch nhau ở lỗi sớm; việc của một ticket tiếp của digital-worker. (M3) ADR-0102 (Accepted)
  quyết 6 nói giao dịch nộp offboarding tạm khóa mọi tài khoản dịch vụ; không ticket nào giữ việc đó, nhưng
  `platform.effective_grants` đã rỗng khi tenant không `active` và `RunControlPort` dừng theo `tenant_offboarding`, nên
  hiệu lực đã có; báo `checking-plan-consistency`. (M4) `platform.worker_runs.run_as_principal_id` (`cfbd906be98b`) không
  có khóa ngoại ghép tới `uq_service_principals_tenant_id_user_id` như R6.10 đòi ở bên tham chiếu; chủ là
  workflow-engine. (M5) digital-worker spec, hàng Ngoài phạm vi "Khóa API của service principal, gắn principal qua
  binding của phiên bản, lane `principal_ownership`" ghi chủ `org-and-principals/03`; khóa API và lane ở W2 (DO-39.2), báo
  `checking-plan-consistency`. (M6) ở W1 không ai được báo khi DW thôi nhận việc vì người chịu trách nhiệm không `active`;
  `GET` service principals không liệt kê principal của DW, nên màn DW nên hiện `owner_missing` (digital-worker/04). (M7)
  khóa `fld.*` trên trường nhạy cảm đếm là trọng yếu (ADR-0104 (Accepted) quyết 6) chưa có trong danh mục; "Kiểm lại khi"
  của spec giữ việc đó. (M8) `PATCH` không `If-Match` ở W1, ghi sau thắng (agent, tạm); nếu sai thì: thêm `row_version` và
  428 theo ADR-0108 (Accepted) quyết 3. (M9) đổi tên dòng trùng ở bước 2 chạm tên service principal của DW mà DW không
  đọc lại (`digital_workers.name` giữ tên gốc). (M10) Spec ngoài phạm vi R4.9 vẫn ghi "tài khoản dịch vụ W1 chưa có
  `owner_user_id`" trong lý do của V4.15 (quyết định của Đạt, không sửa ở đây); người nhận lời báo vẫn đúng. (M11) đo
  P50/P95/P99 ở cuối hàng đợi: `GET` service principals (gọi bộ kiểm cho mỗi dòng), `bootstrap` và `find_access` (thêm
  điều kiện loại), `platform.dw_work_scopes_due` (thêm một join), tạo DW (thêm trigger trên `platform.role_assignments`).
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): lượt xác nhận của gate (một subagent mới, đọc ticket, spec và mã được
  dẫn): 0 CRITICAL sau khi phân loại lại B1 thành HIGH (guard và test âm có, cơ chế đọc sai một ca); bốn HIGH, sửa theo
  quyết định H7-H10 của spec: cờ DW qua hàm SECURITY DEFINER (bước 6, 7), bỏ khóa ngoại tới `platform.tenant_members`
  (bước 2), bước `service_users` khai `platform.service_principals` (bước 9), bảng thử commit thật và tên xếp sau bước
  (bước 9). MEDIUM sửa luôn vì rẻ: guard người chịu trách nhiệm chỉ kiểm khi cột đổi và giữ nhánh cũ (bước 10); migration
  dừng nếu một tài khoản đã giữ khóa `critical`, và 23514 thành 422 `role_not_allowed_for_service` (bước 4); định nghĩa
  "tăng" là danh sách ca (bước 4); wiring chỉ dựng bộ kiểm (bước 7). Ghi nhận: R6.3, R6.10 và R7.1 đã đúng trước ticket
  (`be93e0c26a4c`, `directory.py:109`); tiêu chí của chúng là test hồi quy, đỏ khi gỡ guard. (M12) dòng outbox
  `platform.service_principal.grants_changed` nằm chờ tới handler của workflow-triggers, và handler đó phải nhận cả sự
  kiện của tài khoản không có binding nào (service principal của DW), nếu không chúng nằm mãi (failure-modes #6); báo
  `checking-plan-consistency`.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): lượt xác nhận thứ hai (subagent mới): 0 CRITICAL; ba HIGH, sửa theo
  quyết định H9, H10 của spec: bước giữ khai `platform.users` (lượt trước tưởng `platform.support_grants` chặn, nhưng nó
  cascade từ `platform.workspaces`; bỏ đổi đó), bước mang tên `platform.purge_tenant_service_users` để ca thứ tự đỏ được,
  `claim_due` đọc cùng hàm người chịu trách nhiệm với test riêng. MEDIUM sửa luôn: `POST` kiểm workspace thuộc tenant
  trước tầm với; Phụ thuộc của spec bỏ câu `STUDIO_EXCLUSIONS` cũ và ghi mã mới `service_principal_name_taken` của route
  DW; tiêu chí R6.6 bỏ ca "giao dịch lùi" (không đỏ được) và thêm ca gỡ từng nhánh. Không chạy lượt thứ ba (tối đa hai
  lượt mỗi phiên bản).
- 2026-11-03 (agent): bảng cặp không có đường phụ thuộc. 03 và 04: cả hai đọc `platform.tenant_members`,
  `platform.workspaces`, không bên nào đổi hai bảng đó (cảnh báo `collision` của script); chung đầu chuỗi migration và
  có thể `wiring.py`: 04 đang dựng, 03 dựng sau khi 04 vào `main`, không chạy song song, `down_revision` trỏ head lúc
  commit. 03 và connections-and-vault/02 (`ready-for-agent`): chung đầu chuỗi migration, `test_privileges.py` (hàm
  SECURITY DEFINER thu khỏi `PUBLIC`) và có thể `test_offboarding_coverage.py`; không chạy song song. 03 và
  digital-worker/01: 01 đã `resolved`, nằm trong Blocked by; 03 viết lại `platform.dw_work_scopes_due`,
  `guard_accountable_owner` và `_standing` của nó.
- 2026-11-03 (agent): ticket này thêm một revision Alembic và ba route (`/api/v1/admin/service-principals`), nên dựng
  với `test_rls_coverage.py`, `test_privileges.py`, `test_offboarding_coverage.py`, snapshot OpenAPI và kiểu TS.
- 2026-11-03 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): kiểm nhất quán với tenant-rbac/03 (gate cùng ngày, hai agent không
  thấy nhau), ADR-0103 (Accepted), ADR-0104 (Accepted) và `CLAUDE.md`; 0 CRITICAL, bốn HIGH chạm ticket này, sửa theo
  Quyết định 3/11/2026 (kiểm nhất quán) của spec. (HC1) luật phủ quyền có hai chủ: `platform.uncovered_grants` ở đây và
  "cùng phép so của `platform.grants_cover`" chép vào `platform.rbac_refusals`: bước 7 tách điều kiện thành
  `platform.holder_covers_grant`, mà cả hai đọc. (HC2) "vai trò trọng yếu" có ba định nghĩa (`is_critical_role` theo tên
  và tiền tố, `risk = 'critical'` trong guard, luật `platform.roles.bind` của `rbac_refusals`, mà tenant-rbac/04 mở rộng
  với `fld.*` nhạy cảm, nên chắc chắn lệch): bước 4 tạo `platform.role_is_critical`, một chủ. (HC3) hai khóa trên một lần
  ghi: khóa advisory theo vai trò ở đây và khóa dòng vai trò của lần xác nhận ở tenant-rbac/03, cộng `KEY SHARE` của khóa
  ngoại, là bế tắc giữa tạo DW và xác nhận một thay đổi trên cùng vai trò: bước 4 dùng khóa dòng `FOR NO KEY UPDATE`,
  tenant-rbac/03 khóa cùng dòng đó. (HC4) `_second_person` của DW phủ trên tập rỗng khi principal không `active`, cùng lỗ
  mà bước 7 (c) đóng cho bộ kiểm gắn: bước 10 thêm nhánh 409 `principal_inactive`, tiêu chí digital-worker:R1.9. Thứ tự:
  ticket này dựng trước tenant-rbac/03, cạnh mới ở `Blocked by` của tenant-rbac/03; ticket này không thêm cạnh. Nếu sai
  thì: HC1, HC2 thì tenant-rbac/03 tách hai hàm khi dựng và viết lại guard ở đây; HC3 thì lần xác nhận của tenant-rbac/03
  lấy khóa advisory trước khóa dòng; HC4 thì `_second_person` so trên `platform.assigned_grants`.
- 2026-11-03 (agent): ĐẠT của dòng trên đọc bản trước lượt kiểm nhất quán; bước 4, 7, 10 và hai tiêu chí đổi theo bốn HIGH
  trên, không đổi phạm vi, route hay bảng. Nên một lượt xác nhận (checking-plan-readiness, chỉ đọc chỗ sửa) trước khi dựng;
  Status giữ `ready-for-agent`. MEDIUM, chưa sửa: (M13) `platform.is_digital_worker_principal` ở đây và phép `EXISTS`
  trong `platform.dw_principal_roles_fixed()` (`be93e0c26a4c_platform_digital_workers.py:340`), mà tenant-rbac/03 bước 11
  chuyển sang `platform.role_assignments`, là hai câu trả lời "là principal của DW"; hàm ở đây đọc `app.tenant_id`, mà
  `dw_provisioner` có thể không đặt, nên gộp cần hàm nhận tenant làm tham số. (M14) danh sách khóa thiếu của `rbac_escalation`
  ở đây có `(khóa, độ sâu, workspace neo)`, của `platform.rbac_refusals` chỉ `(khóa, độ sâu)`: một `reason_code`, hai hình
  `details`; ghi ở Comments của tenant-rbac/03.
- 2026-11-03 (agent): checking-plan-readiness, lượt xác nhận nhẹ chỉ trên chỗ 15e74b6 sửa (bước 4, 7, 10, R6.4, R6.19
  thứ hai), đối chiếu code hiện có, một subagent builder; 0 CRITICAL, hai HIGH chạm ticket này, sửa theo ủy quyền
  31/10/2026. (HX1) một khóa dòng vai trò chưa đủ: `trg_z_bump_access_version` UPDATE dòng
  `platform.tenant_access_versions` ở mọi lần ghi bảng quyền, tạo DW giữ dòng đó từ `tenant_members` rồi mới khóa vai
  trò, còn lần xác nhận của tenant-rbac/03 khóa vai trò rồi mới ghi bảng quyền: vẫn 40P01. Bước 4 thêm thứ tự khóa (vai
  trò theo `id` trước dòng phiên bản), câu khóa vai trò đầu giao dịch tạo DW, khóa chỉ ở nhánh cần, và R6.4 thêm ca hai
  kết nối có đột biến phân biệt. `KEY SHARE` của khóa ngoại không xung đột với `FOR NO KEY UPDATE`, nên chu trình
  advisory cũ đã hết thật. (HX2) `_standing` đọc `status` và quyền ở hai câu, nên `principal_inactive` còn một cửa
  sổ đua: bước 10 đọc chúng trong một câu, R6.19 thêm ca bắt câu lệnh. Nhánh `principal_inactive` đóng lỗ ở cửa duy nhất
  tới `operating` (`DigitalWorkerService.change_state`, `digital_workers.py:327`). MEDIUM, chưa sửa: (M15) nhánh
  `platform.tenant_role_permissions` của guard so `risk = 'critical'` của khóa mới thay vì gọi `platform.role_is_critical`,
  vì trigger BEFORE không thấy dòng mới; đó là phần chênh của cùng định nghĩa, nhưng khi tenant-rbac/04 mở rộng hàm thì
  nhánh này phải theo: dựng nó AFTER ROW gọi `platform.role_is_critical(NEW.tenant_id, NEW.role_id)`, hay ghi một test so
  hai bên. (M16) `draft→operating` chỉ được giữ ở service: UPDATE `state` thô dưới `dw_app` qua cả
  `second_person_required` lẫn `principal_inactive` (failure-modes #5); có từ digital-worker/01, không do lượt này, nên ghi
  cho `checking-plan-consistency` của digital-worker. (M17) R6.4 "cùng thao tác qua route gán vai trò" chỉ dựng được
  cho ca gán: chưa có route thêm khóa hay khôi phục vai trò trước tenant-rbac/03. Kết quả: ĐẠT cho chỗ sửa;
  Status giữ `ready-for-agent`.
- 2026-11-03 (agent): dựng xong, `resolved`. Revision `557e6907195e` (sau `67071483caa6`); ba route
  `POST`, `GET /api/v1/admin/service-principals`, `PATCH /api/v1/admin/service-principals/{service_principal_id}`;
  `ServicePrincipalBindingGuard` dựng ở `wiring.py` (`container.service_principal_binding`). Lỗ của
  `_second_person` đã đóng: `_standing` đọc loại, `status` và quyền trong một câu (`_STANDING`), principal không
  `active` → 409 `principal_inactive` trước phép so. Hai đột biến đã thấy đỏ bằng tay: dời `lock_roles` xuống sau
  `ensure_tenant_member` → test hai kết nối nhận 40P01 thật ("deadlock detected"); gỡ nhánh `principal_inactive` →
  DW lên `operating` (DID NOT RAISE). `reviewing-feature-security` (đọc): cô lập tenant (mọi câu qua
  `tenant_session`, cờ DW qua `platform.is_digital_worker_principal`, test âm từ tenant B ở GET, PATCH, bộ kiểm gắn,
  `tenant_members`, khóa ngoại ghép), phân quyền (`.manage` với tới workspace sở hữu kiểm ở service, nơi ghi; tenant
  của người dùng mới từ AccessContext, thân `extra=forbid`), audit cùng giao dịch, outbox cùng giao dịch, mặc định
  đóng (không thấy dòng → 404, không dòng thành viên → không `active`); nội dung không tin cậy và tự chủ không áp
  (tên, mô tả không vào prompt, audit chỉ có id; chưa gắn vào lượt chạy nào). `mutations/03.yaml`: 45 đột biến, chưa
  chạy (lúc đóng hàng đợi).
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): quyết định khi dựng.
  (D1) Bước xóa `platform.purge_tenant_service_users` đăng ký trong `OffboardingPurgeSteps.platform()` cạnh
  `platform.purge_tenant_access_version`, không trong `main.py`: `build_purge_steps` của worker trả chính tập đó và
  test phủ offboarding đọc cùng tập. Nếu sai thì: chuyển lời gọi `register` sang `build_purge_steps`.
  (D2) Khóa ngoại người chịu trách nhiệm tên `fk_service_principals_tenant_id_tenant_members` (cột đầu `tenant_id`
  theo `NAMING_CONVENTION`), index `ix_service_principals_tenant_id_owner_user_id`; lỗi của hàm purge mang ràng buộc
  `ck_users_service_purge`. Nếu sai thì: đổi tên trong một revision mới.
  (D3) Trigger sự kiện khóa dòng vai trò ở MỌI lần thêm hay đổi quyền trong vai trò (không chỉ khóa `critical`)
  trước khi đọc người giữ: gán vai trò cho tài khoản và thêm một khóa thường cùng lúc không làm mất sự kiện. Guard
  vẫn chỉ khóa khi khóa đưa vào là `critical`. "Tài khoản dịch vụ giữ vai trò" có một chủ:
  `platform.service_holders_of_role`. Nếu sai thì: chỉ khóa khi có người giữ, chấp nhận cửa sổ đua đó.
  (D4) "Gán cho người `human` không khóa dòng vai trò" kiểm bằng `FOR NO KEY UPDATE NOWAIT` từ kết nối thứ hai,
  không bằng `pg_locks`: khóa dòng không hiện trong `pg_locks` khi không ai chờ, và khóa bảng `RowShareLock` của
  khóa ngoại và của `FOR NO KEY UPDATE` giống nhau. Nếu sai thì: dùng `pgrowlocks`.
  (D5) Danh sách sắp theo `name` một mình (duy nhất trong công ty), nên `uq_service_principals_tenant_id_name`
  mang trang; `ListPage.request` thêm `sort_type` (mặc định `DATETIME`), route này dùng `TEXT`; route vào
  `plan_shape.REGISTERED` và `test_plan_shape.py` có 120 tài khoản thử. Tối đa 50 dòng một trang ở service.
  Nếu sai thì: sắp `(name, user_id)` với index mới.
  (D6) 403 thiếu `.manage` dùng hình chung `permission_denied` (`action`, `resource_type`); 422 workspace là
  `RequestValidationError` ở route, `type` `workspace_unknown`, pointer `/owning_workspace_id`. Nếu sai thì: một
  exception handler riêng cho `WorkspaceNotInTenantError`.
  (D7) `GET` trả `status` null khi tài khoản không còn dòng `platform.tenant_members`. Nếu sai thì: trả `suspended`.
  (D8) Bảng thử của R6.8 tên `platform.zz_service_user_holder` (bước 9; tiêu chí R6.8 ghi `zz_service_principal_holder`,
  cùng vai trò, cùng thứ tự chữ cái).
  (D9) Tên tài khoản duy nhất buộc sửa ba chỗ thử đã có: tên DW thử theo khóa (`test_digital_workers_db.py`),
  tên ba principal trong `test_plan_shape.py`, và `test_the_critical_role_check_names_a_planted_principal`
  (`test_privileges.py`) tắt thêm `guard_service_principal_grants` trong giao dịch rút lại, vì nó thử lưới bên dưới
  guard. Đơn vị `test_a_business_owner_without_dw_manage_changes_state` thêm standing của principal.
  (D10) Bước 8: `test_user_reads.py` quét AST mọi hàm và hằng của `adapters/persistence` có `platform.users`; mỗi
  cái lọc người (`tables.HUMAN`) hay có trong danh sách với lý do. Test quét nguồn nên đột biến của nó chạy tại chỗ
  bằng tay (đã thấy đỏ), không qua mutate.py.
  (D11) Lỗi "tách lại thành hai câu" của R6.19 trong `03.yaml` là thêm một câu `SELECT 1` sau câu đọc: cùng tác
  dụng lên test đếm câu.
- 2026-11-03 (agent): để lại, chưa làm. Route gán vai trò R6.4 chỉ dựng được qua `PUT /admin/members/{user_id}/memberships`
  (vai trò mẫu có khóa `critical` → 422 `role_not_allowed_for_service`); thêm khóa hay khôi phục vai trò qua route
  chờ tenant-rbac/03 (M17). `provisioning_repo.find_user_by_email` và `_owner_user` không lọc loại: liệt kê có lý do,
  guard từ chối `tenant_owner` cho tài khoản dịch vụ. `PUT` thành viên với một membership rỗng vai trò gặp
  `uq_memberships_scope_user` (có trước ticket này: `_write` coi `before` rỗng là chưa có dòng), nên test R6.4 qua
  route dùng workspace thứ hai. M2, M13, M15, M16 như ghi trên. Lúc đóng hàng đợi: `scripts/mutate.py
.claude/plans/studio/org-and-principals/mutations/03.yaml`, đo P50/P95/P99 theo M11 (thêm `GET` service
  principals, `POST`, `PATCH`).
- 2026-11-03 (agent): cổng của ticket: ruff, format, mypy (624 tệp), lint-imports, `verify_architecture.py`,
  `verify_invariants.py`, unit của `dw_platform`, `dw_api`, `dw_worker`, `dw_kernel`, `-m contract`, và tích hợp
  `test_service_principals_db.py`, `test_digital_workers_db.py`, `test_work_queue_db.py`, `test_offboarding.py`,
  `test_offboarding_coverage.py`, `test_privileges.py`, `test_rls_coverage.py`, `test_tenant_roles.py`,
  `test_permission_catalogue.py`, `test_service_principals_api.py`, `test_tenant_roles_api.py`, `test_plan_shape.py`
  xanh. Đỏ có trước ticket, không do nó: `test_tenant_roles_migration.py` (hai ca) chạy SAU `test_tenant_roles.py`
  trong cùng phiên thì `install_system_roles` của BACKFILL gặp tenant 200 vai trò mà
  `test_the_201st_role_is_refused_and_two_racing_for_the_200th_get_one` để lại (`role_limit_reached`); chạy riêng thì
  xanh. Việc của tenant-rbac/02, cho lúc đóng hàng đợi.
