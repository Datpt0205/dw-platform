# 02 — Vai trò của tenant là dữ liệu: gán vai trò, vai trò mẫu, hàm quyền hiệu lực và phiên bản quyền

Status: needs-triage
Blocked by: 01, .claude/plans/studio/org-and-principals/issues/02-thanh-vien-cap-tenant.md, .claude/plans/studio/foundations-hardening/issues/02-hang-rao-du-lieu-va-danh-tinh.md, .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md, .claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md
Area: studio
Yêu cầu: R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R3.8, R3.9, R3.10, R3.11, R3.12, R3.13, R3.14, R3.15, R4.1, R4.2, R5.1, R5.2, G1, RB5, RB6, RB7, RB8, RB9, RB10, RB11, RB12, RB13, RB14, RB34, RB37, RB38, RB39, RB40, RB41

## Mục tiêu

Vai trò thành dữ liệu của tenant, gán theo membership, và một hàm PostgreSQL trả quyền hiệu lực cho mọi đường đọc (R2,
R3); thay đổi quyền có hiệu lực từ request đầu tiên nhờ phiên bản quyền trong khóa cache (R4); tách nhiệm đọc quyền hiệu
lực (R5.1, R5.2). Công ty ra đời với hai chủ sở hữu, ở `setup` tới khi người thứ hai `active`, và người vận hành hay
nhân viên `support_staff` không bao giờ giữ quyền chủ trong công ty của khách (R3.1, R3.9-R3.13; V4.38, H-15). Gộp từ
brief B3 ticket 04, 05, 07. DO-09.1 và DO-32.2 đã quyết theo khuyến nghị (a) (Đạt, 23/10/2026);
xóa cache ở route khóa của foundations-hardening/02 là tạm và ticket này gỡ nó (`A:foundations-hardening:R3.3~tenant-rbac:R4.1`).

## Việc cần làm

1. **Danh mục.** `platform.permissions` thêm `tenant_grantable boolean NOT NULL` (migration ghi giá trị cho mọi dòng:
   `false` cho `platform.admin`, `true` cho phần còn lại; không default). Đọc bởi quyền tính động của `tenant_owner` (bước 7) và trigger của ticket 03.
   Mọi ticket khác chèn dòng vào `platform.permissions` chờ ticket này và nêu `tenant_grantable` cùng mọi cột NOT NULL
   khác trong câu INSERT (Quyết định 24/10/2026 của spec).
2. **Bảng vai trò.** `platform.tenant_roles`: `id uuid PRIMARY KEY`, `tenant_id uuid NOT NULL` FK `platform.tenants`
   `ON DELETE CASCADE`, `key text NOT NULL CHECK (key ~ '^[a-z][a-z0-9_]{1,62}$')`,
   `name text NOT NULL CHECK (btrim(name) <> '')`, `description text`,
   `kind text NOT NULL CHECK (kind IN ('role','permission_set'))`, `is_system boolean NOT NULL DEFAULT false`,
   `template_key text NULL`, `version integer NOT NULL DEFAULT 1`, `created_by uuid NULL` FK `platform.users`
   `ON DELETE SET NULL`, `created_at`, `updated_at` (`timestamptz NOT NULL DEFAULT now()`), `deleted_at timestamptz NULL`;
   `uq_tenant_roles_tenant_id_key UNIQUE (tenant_id, key)` gồm cả vai đã xóa mềm (khóa không dùng lại),
   `uq_tenant_roles_tenant_id_id UNIQUE (tenant_id, id)` cho FK kép; trigger `updated_at` nhường giá trị câu lệnh nêu
   (CLAUDE.md, "Data model rules"); index `created_by`.
3. **Quyền của vai trò.** `platform.tenant_role_permissions`: `tenant_id uuid NOT NULL`, `role_id uuid NOT NULL`,
   `permission_key text NOT NULL` FK `platform.permissions (key)` `ON DELETE RESTRICT`,
   `depth text NOT NULL CHECK (depth IN ('own','workspace','tenant'))` (W2 mở `team`, `workspace_subtree`),
   `PRIMARY KEY (role_id, permission_key)`; FK `(tenant_id, role_id)` tới `platform.tenant_roles (tenant_id, id)`
   `ON DELETE CASCADE`; index `(tenant_id, role_id)` và `(permission_key, tenant_id)`, dẫn bằng `permission_key` cho FK
   tới `platform.permissions` và vẫn phục vụ tra một khóa trong một tenant; trigger
   `ck_tenant_role_permissions_depth_kind` (R3.4: `tenant` chỉ `tenant`; `workspace` nhận `workspace`, `tenant`; `record`
   nhận cả ba), SQLSTATE 23514.
4. **Gán vai trò.** `platform.memberships` thêm `uq_memberships_tenant_id_workspace_id_id UNIQUE (tenant_id, workspace_id, id)`.
   `platform.role_assignments`: `id uuid PRIMARY KEY`, `tenant_id`, `workspace_id`, `membership_id`, `role_id`
   (`uuid NOT NULL`), `assigned_by uuid NULL` FK `platform.users` `ON DELETE SET NULL`,
   `assigned_at timestamptz NOT NULL DEFAULT now()`,
   `expires_at timestamptz NULL CHECK (expires_at IS NULL OR expires_at > assigned_at)`,
   `UNIQUE (membership_id, role_id)`; FK `(tenant_id, workspace_id, membership_id)` tới `platform.memberships`
   `ON DELETE CASCADE` (workspace được gán vai trò luôn bằng workspace của membership, một sự thật); FK
   `(tenant_id, role_id)` tới `platform.tenant_roles` `ON DELETE CASCADE`; index `(tenant_id, role_id)`,
   `(tenant_id, workspace_id, membership_id)`, `assigned_by`. Trigger BEFORE DELETE trên `platform.tenant_roles` từ chối
   khi còn gán vai trò và tenant `active` (offboarding xóa không cần thứ tự).
5. **RLS và quyền DB.** ENABLE và FORCE, policy `tenant_isolation_<bảng>` chỉ theo `app.tenant_id` cho ba bảng; `dw_app`
   SELECT, INSERT, UPDATE, DELETE; `dw_provisioner` SELECT, INSERT; `dw_agent_ro` không gì; khẳng định trong
   `test_privileges.py`, `test_rls_coverage.py`. `platform.tenant_roles`, `platform.tenant_role_permissions` và
   `platform.tenant_access_versions` (bước 9) không có `workspace_id`: mỗi bảng một dòng trong danh sách bảng toàn tenant
   `_TENANT_WIDE_ON_PURPOSE` của `test_rls_coverage.py` (studio-skeleton/01, `studio-skeleton:R9.1`) với lý do "vai trò,
   quyền của vai trò và phiên bản quyền thuộc cả công ty; neo workspace nằm ở `platform.role_assignments`" (DO-01).
6. **Cài vai trò.** `platform.install_system_roles(p_tenant_id uuid)`: `tenant_owner` (`is_system`, không dòng quyền:
   tính động) và `member` (`is_system`, quyền nhân bản từ mẫu `member`). `platform.install_role_template(p_tenant_id uuid, p_template_key text) RETURNS uuid`:
   nhân bản `platform.roles` (loại `role`) hay `platform.permission_sets` (loại `permission_set`), mức theo `scope_kind`
   (`workspace` cho khóa `workspace`, `tenant` cho khóa `tenant`); mẫu sửa về sau không chạm bản đã nhân bản (R3.2), không
   đọc rơi về mẫu. `POST /api/v1/platform/tenants` gọi `install_system_roles` trong giao dịch tạo tenant (bước 16);
   `POST /api/v1/platform/tenants/{tenant_id}/org-admins` gán `tenant_owner` ở workspace `main` thay cho `org_admin`.
7. **Quyền hiệu lực** (ADR-0104 (Accepted) mục 5): `platform.effective_grants(p_tenant_id uuid, p_user_id uuid)` trả
   `(permission_key, depth, anchor_workspace_id, role_id)`; SQL, STABLE, SECURITY INVOKER; chỉ tính tenant `active`,
   thành viên công ty `active` (`platform.tenant_members`), vai trò chưa xóa, gán chưa quá `expires_at`; thêm quyền tính
   động của `tenant_owner` (mọi khóa `active` có `tenant_grantable` ở mức `tenant`). Bên cạnh:
   `platform.scopes_in(p_tenant_id, p_user_id, p_workspace_id)` (phép chiếu: mức `tenant` từ mọi neo, mức `workspace` khi
   neo là workspace đang làm việc, khóa `record` ở mọi mức), `platform.workspace_reach(p_tenant_id, p_user_id, p_permission_key)`
   (mức `tenant`: mọi workspace sống; `workspace`: neo; `own`: rỗng) và
   `platform.grants_cover(p_tenant_id, p_holder_id, p_subject_id) RETURNS boolean` (người giữ có mọi khóa của chủ thể ở mức
   bằng hoặc rộng hơn, cùng neo khi mức `workspace`), và
   `platform.checker_candidates(p_tenant_id uuid, p_permission_key text, p_proposer_id uuid, p_workspace_id uuid DEFAULT NULL) RETURNS SETOF uuid`
   (người `active` giữ khóa đó trên `platform.effective_grants`, khác người đề xuất; có `p_workspace_id` thì chỉ người
   giữ khóa với tới workspace đó), hàm SQL dùng chung cho `no_checker_available` của ticket 03 (toàn tenant), của
   tenant-config R8.5 (theo workspace của đề xuất) (`D:tenant-config/05~tenant-rbac:R7.1`) và của hai phê duyệt nghiêm
   `egress.allowed_host`, `connections.enable` của connections-and-vault (`connections-and-vault:R3.12`,
   `connections-and-vault:R5.13`). Không bản sao Python.
8. **Người đọc.** `effective_scopes` thành adapter gọi `platform.scopes_in`; `_access_in` (`membership_lookup.py:80-106`)
   lấy quyền qua nó; `AccessContext.roles` là khóa vai trò gán ở workspace đang làm việc (W1 thêm `platform_admin` còn
   trong `role_keys`); `scope_holders.py` đọc `platform.effective_grants` và gỡ bộ lọc thành viên không `active` riêng mà
   org-and-principals/02 thêm, vì hàm đã lọc (R2.5); điều kiện `status = 'active'` trong join dựng AccessContext giữ
   nguyên, là cửa của org-and-principals R4.3 (`A:org-and-principals:R4.3~tenant-rbac:R2.5`); bootstrap thôi tự tính và bỏ
   `roles`, `scopes` khỏi từng membership (ADR-0104 (Accepted) mục 5).
9. **Phiên bản quyền.** `platform.tenant_access_versions`: `tenant_id uuid PRIMARY KEY` FK `platform.tenants`
   `ON DELETE CASCADE`, `version bigint NOT NULL DEFAULT 0`, `changed_at timestamptz NOT NULL DEFAULT now()`; RLS tenant;
   `dw_app` chỉ SELECT. `platform.bump_access_version()` SECURITY DEFINER, `search_path` ghim, gắn AFTER INSERT, UPDATE,
   DELETE trên `platform.tenant_roles`, `platform.tenant_role_permissions`, `platform.role_assignments`,
   `platform.memberships`, `platform.tenants`, `platform.entitlements` và `platform.tenant_members` (bảng của
   org-and-principals/02 có trước hàm này, nên trigger của nó gắn ở đây). Dòng phiên bản tạo cùng tenant và trong chuyển
   dữ liệu.
10. **Cache.** Khóa thành `ml:{tenant}:{version}:{workspace}:{issuer}:{subject}` (`application/cache.py:18-20`); đọc
    phiên bản trước dữ liệu trong cùng giao dịch; giải tuần tự hóa nghiêm, thiếu trường là trượt; bỏ mọi `delete_pattern`
    ở route (`admin_members.py`, `admin_console.py`, và `POST /api/v1/platform/tenants/{tenant_id}/lock`, `/unlock`,
    `/offboard` ở `apps/api/src/dw_api/routes/v1/platform.py` mà foundations-hardening/02 thêm tạm). FH8 của
    foundations-hardening giữ hành vi (khóa tenant → request kế tiếp 403); phép đột biến của nó thành gỡ trigger
    `platform.bump_access_version()` trên `platform.tenants`.
11. **`GET /api/v1/me`** thêm `grants` (`key`, `depth`, `anchor_workspace_id`), `access_version`, `platform_bypass`. Web:
    `hasScope` đọc `/me` của workspace đang làm việc, tải lại khi đổi workspace và khi gặp 403; xóa bản sao `platform_admin`
    ở `apps/web/lib/session.ts`, `apps/web/lib/auth/auth-context.tsx`, `apps/web/app/knowledge/page.tsx`; nav thôi lọc
    theo khóa vai (`apps/web/lib/nav/visibility.ts`). Vitest với `/me` giả.
12. **Tách nhiệm.** Viết lại `platform.sod_violation(p_tenant_id, p_user_id)` trên `platform.effective_grants`, bỏ quyền
    đến từ `tenant_owner`, giữ hợp đồng lỗi (23514, ràng buộc `ck_roles_sod_memberships`, tối đa 20 id trong DETAIL,
    `FOR SHARE` trên miễn trừ như `f381f1694395`); trigger AFTER INSERT, UPDATE trên `platform.role_assignments` và
    `platform.tenant_role_permissions`; bỏ trigger trên `platform.roles`, `platform.permission_sets`, thay bằng test
    "không mẫu nào phá luật" (mở rộng `test_no_single_role_or_permission_set_in_the_catalogue_breaks_a_rule`).
13. **Chuyển dữ liệu** (migration, `dw_migrator`): mỗi tenant cài vai trò hệ thống; mỗi khóa vai và bộ quyền mà membership
    đang dùng, trừ `platform_admin`, thành vai trò của tenant qua `install_role_template`; người giữ `org_admin` ở workspace
    `main` nhận `tenant_owner`, audit `platform.role_assignment.grant` qua `lane_audit_event` với actor
    `system:rbac_migration` (DO-32.2); migration in ra danh sách tenant còn dưới hai chủ sở hữu (mọi thay đổi nới quyền ở
    đó trả `no_checker_available` tới khi người vận hành cài người thứ hai) và tenant không có `org_admin` ở `main` (người
    vận hành gán qua `POST /api/v1/platform/tenants/{tenant_id}/org-admins`). Trigger AFTER một chiều trên
    `platform.memberships` (`role_keys`, `permission_set_keys`) chép sang `platform.role_assignments` cho các đường ghi
    cũ tới khi ticket 03 khóa cột; khóa lạ thì từ chối (lỗi to).
14. **Giới hạn.** Trigger BEFORE INSERT trên `platform.tenant_roles` với `pg_advisory_xact_lock(hashtext('tenant_roles:' || tenant_id))`:
    200 vai trò chưa xóa (gồm bộ quyền bổ sung) thì nhận, vai trò thứ 201 thì 23514 `role_limit_reached`.
15. Offboarding xuất bốn bảng mới (`platform.tenant_roles`, `platform.tenant_role_permissions`,
    `platform.role_assignments`, `platform.tenant_access_versions`; `test_offboarding.py`) và xóa ba bảng đầu, trên
    phần đọc catalog và `export_rows` mà foundations-hardening/07 đã viết lại, dưới test phủ offboarding của
    studio-skeleton/01 (`studio-skeleton:R4.3`). `platform.tenant_access_versions` giữ `dw_app` chỉ SELECT (bước 9) và
    vào `STUDIO_EXCLUSIONS` với lý do "một dòng đếm mỗi tenant giữ có chủ ý, không mang dữ liệu của tenant; dòng
    `platform.tenants` của tenant đã offboard còn ở `offboarded` nên dòng đếm còn theo", như `studio.access_epochs` của
    record-access (Quyết định 24/10/2026 của spec).
16. **Hai chủ sở hữu khi tạo công ty** (R3.1, R3.9-R3.11; V4.38). Revision (id hex của `alembic revision`):
    - `ck_tenants_status` thay bằng `CHECK (status IN ('setup', 'active', 'locked', 'offboarding', 'offboarded'))`
      (`db/migrations/versions/5d9d89ffc716_tenant_offboarding_requests.py:79-80`); trigger trạng thái của
      foundations-hardening/02 (`foundations-hardening:R3.2`) giữ nguyên. Một trigger BEFORE UPDATE OF `status` trên
      `platform.tenants` từ chối với SQLSTATE 23514 mọi bước vào `setup` từ trạng thái khác, vì `setup` chỉ có lúc tạo,
      và mọi bước rời `setup` sang trạng thái khác `active` và `offboarding`; người vận hành offboard một công ty `setup`
      qua luồng offboarding hiện có (spec R3.15; Đạt, Q-h2).
    - Luật chuyển (R3.10): `platform.complete_tenant_setup()` SECURITY DEFINER, `search_path` ghim, gắn AFTER UPDATE OF
      `status` trên `platform.tenant_members` khi `NEW.status = 'active'` và `OLD.status <> 'active'`: khi
      `platform.tenants.status` của dòng là `setup` và số thành viên công ty `active` có gán `tenant_owner` (đếm trên
      `platform.role_assignments` nối `platform.tenant_members`, không qua `platform.effective_grants`, vốn chỉ tính tenant
      `active`) lên hai, đặt `status = 'active'` trong cùng giao dịch và ghi audit `platform.tenant.setup_completed` đứng
      tên người vừa `active`, `details` là id hai chủ sở hữu, nhãn tiếng Việt của hành động vào mảnh
      `configs/copy/audit_actions.d/tenant-rbac.yaml` trong cùng thay đổi (H-21). Lần đăng nhập đầu của chủ sở hữu (`_resolve_user`, mà
      org-and-principals/02 cho đổi `invited` sang `active`, org-and-principals:R4.5) là đường kích hoạt; cửa
      AccessContext từ chối công ty không `active` ở mọi route (ADR-0102 (Accepted) quyết 6), trừ ngoại lệ của spec R3.14
      (Đạt, Q-h1): với công ty `setup`, cửa cho qua đúng lần đăng nhập đầu và lần nhận lời mời làm chủ của một trong hai
      chủ sở hữu được mời lúc tạo, cùng các route `/api/v1/platform/` của người vận hành, và từ chối mọi route khác như
      `locked`; test của luật chuyển chạy cả trên lệnh UPDATE của `platform.tenant_members` lẫn qua lần đăng nhập đầu.
    - Người vận hành và `support_staff` (R3.11): `platform.guard_operator_tenant_grants()`, trigger BEFORE INSERT, UPDATE
      trên `platform.role_assignments` (người được gán có dòng `platform.platform_operators` hay `platform.support_staff`, và
      vai trò là `tenant_owner` hay có `studio.publish.approve` hay `platform.roles.write` trong
      `platform.tenant_role_permissions`), trên `platform.tenant_role_permissions` (thêm một trong hai khóa vào vai trò
      đang gán cho người như vậy), và BEFORE INSERT trên `platform.platform_operators`, `platform.support_staff` (người
      đang giữ một trong ba quyền đó ở một tenant); SQLSTATE 23514, ràng buộc `ck_role_assignments_operator_not_owner`,
      áp cho mọi vai kể cả `dw_provisioner`, `dw_migrator`. Tên vai trò và hai khóa sống ở một chỗ, hàm này; test so
      hai khóa với danh mục khi chúng đã đăng ký. Đường vượt `platform_admin` không mở route quản trị vai trò (spec R3.16, ticket 03).
    - `POST /api/v1/platform/tenants` (`apps/api/src/dw_api/routes/v1/platform.py:154-166`): thân thêm `owners`, mảng
      đúng hai email khác nhau sau khi chuẩn hóa chữ thường; sai thì 422 `validation_failed`, không ghi gì (R3.9). Một
      giao dịch: tenant `setup`, `install_system_roles`, và với mỗi chủ sở hữu, theo đường mời hiện có, người dùng (có rồi
      thì dùng lại; chưa có thì `subject` `invite:`), thành viên công ty `invited`, membership ở `main` và gán
      `tenant_owner` như R3.8. Đối tác của khách (người ngoài công ty khách) đi cùng đường như mọi thành viên. Trigger của
      R3.11 từ chối → 409 `conflict` với `details.reason_code` `operator_not_assignable`, không ghi gì; route
      `.../org-admins` trả cùng mã. Phản hồi có `status`.
    - Migration chuyển dữ liệu (bước 13) không đổi tenant đã có sang `setup`; danh sách tenant dưới hai chủ sở hữu mà nó
      in ra vẫn là việc của người vận hành.
17. **Dưới hai người** (R3.12, R3.13; H-15). `platform.tenants.owner_coverage_low_since timestamptz NULL`. Trigger AFTER
    INSERT, UPDATE, DELETE theo câu lệnh (bảng chuyển tiếp) trên `platform.role_assignments`,
    `platform.tenant_role_permissions`, `platform.tenant_roles`, `platform.tenant_members` gọi
    `platform.check_owner_coverage(p_tenant_id)` một lần cho mỗi tenant của câu lệnh: với tenant `active`, đếm người
    `active` giữ `studio.publish.approve` và người `active` giữ `platform.roles.write` trên `platform.effective_grants`;
    một trong hai số dưới hai mà cột NULL → đặt cột bằng `now()` và ghi outbox `platform.tenant.owner_coverage_low`
    (`tenant_id`, khóa nào dưới hai) cùng giao dịch; cả hai từ hai trở lên mà cột khác NULL → đặt NULL. Handler của sự
    kiện, đăng ký ở composition root của worker, gửi qua dịch vụ thông báo của nền tảng
    (`packages/python/dw_platform/src/dw_platform/application/notifications.py`) một thông báo cho mỗi người giữ
    `platform.members.write` ở độ sâu công ty, như `workflow-engine:R5.20`. `GET /api/v1/platform/tenants` trả
    `owner_coverage_low_since` cạnh `status`; `apps/web/app/platform/page.tsx` có bộ lọc "Đang thiết lập" (`setup`) và
    "Dưới hai người", antd `Table` và `Tag`. Số đo của trigger trên tenant 5.000 người ghi ở Comments cùng số đo FOG-38.

## Tiêu chí chấp nhận

- [ ] R2.2 (RB5): người có `approvals.decide` chỉ qua `approver_boost`: AccessContext, `/me`, người giữ quyền và tách nhiệm cùng thấy khóa; đổi `platform.effective_grants` bỏ bộ quyền bổ sung → mọi test đó đỏ.
- [ ] R2.2: `platform.checker_candidates` cho một khóa trả đúng tập người `active` mà `scope_holders.py` trả cho cùng khóa, trừ người đề xuất; thành viên `suspended` không có trong kết quả.
- [ ] R2.3: khóa mức `tenant` gán ở A có trong `GET /api/v1/me` khi làm việc ở B.
- [ ] R2.4 (RB6): `approvals.decide` mức `workspace` gán ở A vắng ở `/me` của B; bỏ điều kiện neo trong `platform.scopes_in` → đỏ.
- [ ] R2.5 (RB7): qua đường SQL, `platform.effective_grants` của thành viên `suspended`, tenant `locked`, vai trò xóa mềm, gán quá `expires_at` → khóa vắng, và `scope_holders.py` không còn bộ lọc riêng mà vẫn không trả người đó; gỡ từng điều kiện trong hàm → đỏ.
- [ ] R2.6: Vitest: nav và trang admin đọc `/me` giả; grep không còn chuỗi `platform_admin` trong `apps/web` ngoài test; bootstrap không còn `roles`, `scopes`.
- [ ] R2.7 (RB34): migration thử đăng ký một khóa `active` có `tenant_grantable` sau khi gán `tenant_owner` → `platform.effective_grants` và `/me` của người đó có khóa ở mức `tenant`, `platform.tenant_role_permissions` không có dòng nào cho `tenant_owner`; `platform.admin` (`tenant_grantable` sai) và một khóa `retired` vắng; bỏ điều kiện `tenant_grantable` hay `status` khỏi quyền tính động ở bước 7 → test đỏ.
- [ ] R3.1 (RB37): `POST /api/v1/platform/tenants` với hai chủ sở hữu → tenant mới ở `setup`, có đúng `tenant_owner` và `member`, `is_system`, hai thành viên công ty `invited` mỗi người giữ `tenant_owner` ở `main`; lỗi giữa giao dịch → không có tenant, vai trò hay thành viên; `ck_tenants_status` thiếu `setup` → INSERT từ chối, test đỏ.
- [ ] R3.1: UPDATE một tenant `active` sang `setup` dưới `dw_provisioner` → 23514, trạng thái giữ; gỡ trigger → test đỏ.
- [ ] R3.9 (RB37): một chủ sở hữu, ba, hay hai email chỉ khác hoa thường → 422 `validation_failed`, 0 dòng `platform.tenants`; bỏ kiểm → ca một chủ sở hữu được nhận, test đỏ.
- [ ] R3.10 (RB38): kích hoạt chủ sở hữu thứ nhất bằng UPDATE `platform.tenant_members` → tenant giữ `setup`; kích hoạt người thứ hai → tenant `active` và một audit `platform.tenant.setup_completed` trong cùng giao dịch; lùi giao dịch đó → tenant `setup`, không audit; thành viên `active` không giữ `tenant_owner` → tenant giữ `setup`; gỡ trigger → test đỏ.
- [ ] R3.11 (RB39): dưới `dw_provisioner` và `dw_migrator`, gán `tenant_owner` cho người vận hành → 23514; `POST /api/v1/platform/tenants` với email của một nhân viên `support_staff` làm chủ sở hữu → 409 `operator_not_assignable`, 0 dòng; thêm `studio.publish.approve` hay `platform.roles.write` (khóa thử nếu cụm chủ chưa đăng ký) vào vai trò đang gán cho người vận hành → 23514; INSERT `platform.platform_operators` cho một `tenant_owner` → 23514; đối tác ngoài công ty khách làm chủ sở hữu thứ hai → nhận; gỡ trigger hay bỏ nhánh `platform.support_staff` → test đỏ.
- [ ] R3.12 (RB40): tenant `active` với hai người giữ `platform.roles.write`; gỡ gán của một người → đúng một thông báo cho mỗi người giữ `platform.members.write` ở độ sâu công ty, `owner_coverage_low_since` có giá trị; gỡ thêm một gán → không thông báo thứ hai; gán lại cho hai người → cột về NULL; xuống lần nữa → một thông báo mới; bỏ kiểm cột trước khi ghi outbox → thông báo thứ hai, test đỏ.
- [ ] R3.13 (RB40): `GET /api/v1/platform/tenants` trả `status` `setup` cho tenant mới và `owner_coverage_low_since` cho tenant dưới hai người; Vitest: màn `apps/web/app/platform` lọc "Đang thiết lập" và "Dưới hai người" trên dữ liệu giả.
- [ ] R3.14 (RB41): công ty `setup` vừa tạo; chủ sở hữu thứ nhất đăng nhập lần đầu và nhận lời mời → được, công ty
      giữ `setup`; sau đó người đó gọi `/me`, tạo một lời mời khác, xin một lượt chạy hay gửi phát hành → từ chối như
      `locked`; người vận hành gọi `GET /api/v1/platform/tenants` → được; chủ sở hữu thứ hai đăng nhập lần đầu → công
      ty `active` (R3.10); bỏ ngoại lệ đăng nhập đầu → không chủ sở hữu nào kích hoạt được, test đỏ; bỏ nhánh `setup`
      của cửa → lượt chạy được nhận, test đỏ.
- [ ] R3.15 (RB41): UPDATE `status` `setup` → `locked` → 23514, không đổi gì; người vận hành offboard công ty `setup` →
      `offboarding`; UPDATE `active` → `setup` → 23514; gỡ trigger → bước `setup` → `locked` được nhận, test đỏ.
- [ ] R3.2 (RB10): migration thử sửa mẫu `approver` → vai trò `approver` đã nhân bản giữ nguyên quyền và mức.
- [ ] R3.3 (RB8): kết nối `app.tenant_id` A đọc vai trò, quyền, gán của B → 0 dòng; INSERT gán với `role_id` của B → FK kép từ chối; kết nối không đặt tenant → 0 dòng.
- [ ] R3.4 (RB9): `platform.roles.write` mức `workspace` → 23514; khóa `workspace` mức `own` → 23514; gỡ trigger → đỏ.
- [ ] R3.5: test so sánh trên dữ liệu seed: `scopes` của mọi membership trước và sau migration bằng nhau.
- [ ] R3.6: tenant seed có `org_admin` ở `main` → người đó giữ `tenant_owner`, có đúng một audit với `details.actor` là `system:rbac_migration`; tenant seed chỉ một chủ sở hữu và tenant seed không có `org_admin` ở `main` có tên trong danh sách migration in ra.
- [ ] R3.7 (RB11): vai trò thứ 201 → 23514 `role_limit_reached`; hai giao dịch đồng thời ở vai trò thứ 200 → đúng một thành công; gỡ khóa tư vấn → đỏ.
- [ ] R3.8: `POST /api/v1/platform/tenants/{tenant_id}/org-admins` → người đó giữ `tenant_owner`, `role_keys` không có `org_admin`.
- [ ] R4.1 (RB12): gỡ gán vai trò bằng SQL thô khi cache còn → request kế tiếp 403 trong vòng 1 giây; operator khóa tenant qua `POST /api/v1/platform/tenants/{tenant_id}/lock` khi route không còn `delete_pattern` → request kế tiếp 403 (FH8 vẫn xanh); gỡ trigger tăng phiên bản → đỏ.
- [ ] R4.2 (RB13): bản ghi cache của bản triển khai cũ (thiếu `grants`) hay mang phiên bản cũ → trượt và dựng lại, không mặc định.
- [ ] R5.1 (RB14): vai trò tenant mang cả hai vế một luật, hai vế gán ở hai workspace → 23514 kèm id; sửa vai trò làm 2 người vi phạm → DETAIL có 2 id; luật đã miễn trừ và xác nhận → nhận; gỡ trigger AFTER → đỏ.
- [ ] R5.2: người giữ `tenant_owner` không bị luật chặn; thêm vai trò thường phá luật cho người đó → 23514.
- [ ] G1: `test_the_admin_who_proposed_a_waiver_cannot_confirm_it` xanh trước và sau thay đổi.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `db/migrations/sql/0001_platform_baseline.sql:262-273`; spec: R3, R4.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:80-106`; spec: R2.2.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/scope_holders.py:67-70`; spec: R2.2.
- `packages/python/dw_platform/src/dw_platform/application/cache.py:18-20`; spec: R4.1.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/caching_lookup.py:27`; spec: R4.2.
- `apps/api/src/dw_api/routes/v1/me.py:27-38`; spec: R2.6.
- `apps/web/lib/session.ts:177-181`; spec: R2.6.
- `apps/api/src/dw_api/routes/v1/platform.py:257`; spec: R3.8.
- `apps/api/src/dw_api/routes/v1/platform.py:154-166`, `apps/api/src/dw_api/routes/v1/platform.py:26-34`; spec: R3.1, R3.9, R3.13.
- `db/migrations/versions/5d9d89ffc716_tenant_offboarding_requests.py:79-80`; spec: R3.1.
- `db/migrations/sql/0001_platform_baseline.sql:340-345`, `db/migrations/versions/af8ee878b4ab_platform_support_staff_and_support_.py:195`; spec: R3.11.
- `packages/python/dw_platform/src/dw_platform/application/notifications.py:40`; spec: R3.12.
- `apps/api/src/dw_api/routes/v1/platform.py:189-232`; spec: R4.1 (route khóa, mở khóa, offboard).
- `db/migrations/versions/f381f1694395_platform_sod_waiver_second_person_and_.py:55-58`; spec: R5.1.
- `packages/python/dw_platform/tests/integration/test_separation_of_duties.py:278-282`; spec: R5.1.
- `packages/python/dw_platform/tests/integration/test_rls_coverage.py:44-59`; spec: Hiện trạng (lớp bảng toàn tenant).
- ADR-0104 (Accepted) mục 2, 3, 5, 7, 9, 10; ADR-0012 (Accepted); ADR-0024 (Proposed) quyết 6; brief B3 mục 1.2-1.7.

## Comments

- 2026-10-23 (agent): DO-09.1, DO-32.2, `A:org-and-principals:R4.3~tenant-rbac:R2.5`, `A:foundations-hardening:R3.3~tenant-rbac:R4.1`, `D:tenant-config/05~tenant-rbac:R7.1` và DO-01 đã có lời đáp (Đạt, 23/10/2026); Status về needs-triage, thêm foundations-hardening/02 vào Blocked by.
- 2026-10-24 (agent): vòng sửa 4: Blocked by thêm foundations-hardening/07 (cùng sửa `offboarding.py` và `test_offboarding.py`, `C:foundations-hardening/07~tenant-rbac/02`) và studio-skeleton/01 (danh sách `_TENANT_WIDE_ON_PURPOSE` và test phủ offboarding, `I:org-and-principals/02~studio-skeleton/01`); bước 1 ghi rằng mọi ticket đăng ký khóa chờ ticket này và nêu `tenant_grantable` trong INSERT (`C:custom-objects/02~tenant-rbac/02`); studio-skeleton/03 chờ ticket này (`C:studio-skeleton/03~tenant-rbac/01`), nên bước 11 viết lại `apps/web/lib/nav/visibility.ts` trước khi mục Studio có mặt; `platform.checker_candidates` của bước 7 cũng trả lời `no_checker_available` của connections-and-vault (`connections-and-vault:R3.9`, `connections-and-vault:R5.10`).
- 2026-10-24 (agent): kiểm vòng sửa 4: bước 15 đếm lại thành bốn bảng mới và nêu tên chúng (bước 2, 3, 4, 9), thay cho "năm bảng" cũ; dòng Phụ thuộc của spec sửa cùng.
- 2026-10-24 (agent): vòng sửa 4, lượt hai: bước 7 dẫn `connections-and-vault:R3.12`, `connections-and-vault:R5.13`, hai tiêu chí `no_checker_available` của connections-and-vault, thay cho R3.9, R5.10 là lệnh gửi (Quyết định 24/10/2026 của spec).
- 2026-10-24 (agent): vòng sửa 4, lượt ba: luật quyền tính động của `tenant_owner` ở bước 7 là tiêu chí R2.7 của spec với kiểm soát RB34; dòng `Yêu cầu:` và một tiêu chí chấp nhận thêm theo, bước 7 không đổi (Quyết định 24/10/2026 của spec).
- 2026-10-24 (agent): vòng sửa 4, lượt bốn: bước 3 đổi index `(tenant_id, permission_key)` thành `(permission_key, tenant_id)`, để FK `permission_key` tới `platform.permissions` có index dẫn bằng cột của nó (CLAUDE.md, Data model rules; Quyết định 24/10/2026 của spec).
- 2026-10-24 (agent): bước 15 thôi nói offboarding xóa `platform.tenant_access_versions`, vì `dw_app` chỉ SELECT trên bảng đó (bước 9) và lane offboarding chỉ xóa bảng mà `dw_app` có DELETE; dòng đếm được xuất, giữ có chủ ý và vào `STUDIO_EXCLUSIONS` kèm lý do, như `studio.access_epochs` của record-access (CLAUDE.md, Data model rules; Quyết định 24/10/2026 của spec).
- 2026-10-25 (agent): lượt h, theo V4.38 của Đạt và H-15 cùng các dòng tạm cùng ngày của spec: bước 16 (hai chủ sở hữu,
  `setup` trong `ck_tenants_status`, luật chuyển trên `platform.tenant_members`, trigger cho người vận hành và
  `support_staff`) và bước 17 (cảnh báo dưới hai người, cột và màn vận hành); tiêu chí R3.1 viết lại, thêm R3.9-R3.13 và
  RB37-RB40. Đường kích hoạt qua đăng nhập đầu khi công ty còn `setup` chờ Q1, bước rời `setup` khác `active` chờ Q2,
  đường vượt `platform_admin` chờ Q3 (đã đáp ngày 26/10, dòng sau). Không thêm cạnh Blocked by: org-and-principals/02 đã là tổ tiên.
- 2026-10-26 (agent): áp Q-h1, Q-h2 của Đạt (theo khuyến nghị): bước 16 mở ngoại lệ đăng nhập đầu và nhận lời mời của hai
  chủ sở hữu trong `setup` (R3.14) và cho `setup` → `offboarding` qua luồng của người vận hành, từ chối mọi lối ra khác
  `active` (R3.15); thêm tiêu chí R3.14, R3.15 và RB41. Không thêm cạnh.
