# 02 — Vai trò của tenant là dữ liệu: gán vai trò, vai trò mẫu, hàm quyền hiệu lực và phiên bản quyền

Status: resolved (2026-11-02, main)
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
8. **Người đọc.** `effective_scopes` thành adapter gọi `platform.scopes_in`; `_access_in` (`membership_lookup.py:59-190`)
   lấy quyền qua nó; `AccessContext.roles` là khóa vai trò gán ở workspace đang làm việc (W1 thêm `platform_admin` còn
   trong `role_keys`); `scope_holders.py` đọc `platform.effective_grants`, không thêm bộ lọc thành viên không `active` nào
   của riêng nó (hôm nay nó không có bộ lọc đó: org-and-principals/02 cố ý không thêm, nên người `suspended` còn được trả
   tới ticket này), vì hàm đã lọc (R2.5); điều kiện `status = 'active'` trong join dựng AccessContext giữ
   nguyên, là cửa của org-and-principals R4.3 (`A:org-and-principals:R4.3~tenant-rbac:R2.5`); bootstrap thôi tự tính và bỏ
   `roles`, `scopes` khỏi từng membership (ADR-0104 (Accepted) mục 5). Hai người đọc khác của `effective_scopes` cũng đọc
   qua adapter đó, không đọc `role_keys`: `SqlDwMembershipCheck._standing` (`digital_workers_repo.py:438-473`, quyền của
   người được đặt vào DW) và `SqlDwBoundary.boundary` (`digital_workers_repo.py:560-607`, quyền của chủ thể DW khi chạy),
   mỗi cái cho workspace của nó. `DigitalWorkerService._check_roles` (`role_catalog`, vai trò mẫu) và
   `platform.dw_principal_roles_fixed()` (`be93e0c26a4c`) ở lại trên `memberships.role_keys` trong ticket này, vì đó vẫn là
   đường ghi mà trigger của bước 13 chép sang; ticket 03 (khóa cột) và org-and-principals/03 (trigger tài khoản dịch vụ trên
   `platform.role_assignments`) dời chúng.
9. **Phiên bản quyền.** `platform.tenant_access_versions`: `tenant_id uuid PRIMARY KEY` FK `platform.tenants`
   `ON DELETE CASCADE`, `version bigint NOT NULL DEFAULT 0`, `changed_at timestamptz NOT NULL DEFAULT now()`; RLS tenant;
   `dw_app` chỉ SELECT. `platform.bump_access_version()` SECURITY DEFINER, `search_path` ghim, gắn AFTER INSERT, UPDATE,
   DELETE trên `platform.tenant_roles`, `platform.tenant_role_permissions`, `platform.role_assignments`,
   `platform.memberships`, `platform.tenants`, `platform.entitlements` và `platform.tenant_members` (bảng của
   org-and-principals/02 có trước hàm này, nên trigger của nó gắn ở đây). Dòng phiên bản chỉ ra đời ở hai chỗ: trong chuyển
   dữ liệu cho mỗi tenant có sẵn, và do chính hàm này khi trigger AFTER INSERT trên `platform.tenants` bắn (nên không vai
   nào, kể cả `dw_provisioner`, cần INSERT trên bảng); mọi lần bắn khác chỉ UPDATE dòng có sẵn, nên các lần xóa sau lượt
   xóa dòng đó của offboarding (bước 15) không tạo lại nó.
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
    "không mẫu nào phá luật" (mở rộng `test_no_single_role_or_permission_set_in_the_catalogue_breaks_a_rule`). Bỏ
    `trg_memberships_separation_of_duties`, `platform.enforce_separation_of_duties()` và bản `sod_violation(jsonb, ...)`
    cũ, vì đường ghi `role_keys` cũ tới `platform.role_assignments` qua trigger của bước 13 và bị xét ở đó. Các route ghi
    membership hôm nay trả 409 `{rule, reason}` nhờ `separation_of_duties_conflict`
    (`adapters/persistence/separation_of_duties.py:32-42`), vốn chỉ nhận ràng buộc mang tên luật mà trigger cũ nêu; nó
    nhận thêm `ck_roles_sod_memberships`, với tên luật lấy từ lỗi (trigger mới đặt tên luật vào HINT, DETAIL giữ danh sách
    id), để các route đó giữ đúng 409 ấy thay vì 500. Viết lại
    `platform.refuse_revoking_a_waiver_in_use()` (`6b26771e549d`) để đếm người của tenant mà quyền hiệu lực, trừ quyền của
    `tenant_owner`, phá luật của miễn trừ, cùng một phép xét với `platform.sod_violation`, không đếm membership theo
    `role_keys`; giữ ràng buộc `ck_sod_waivers_not_in_use`, DETAIL là số đếm, và 409 của
    `separation_of_duties_repo.py:157-162` giữ nguyên hình (khóa `details.memberships` nay đếm người).
13. **Chuyển dữ liệu** (migration, `dw_migrator`): mỗi tenant cài vai trò hệ thống; mỗi khóa vai và bộ quyền mà membership
    đang dùng, trừ `platform_admin`, thành vai trò của tenant qua `install_role_template`; người giữ `org_admin` ở workspace
    `main` nhận `tenant_owner`, audit `platform.role_assignment.grant` qua `lane_audit_event` với actor
    `system:rbac_migration` (DO-32.2); migration in ra danh sách tenant còn dưới hai chủ sở hữu (mọi thay đổi nới quyền ở
    đó trả `no_checker_available` tới khi người vận hành cài người thứ hai) và tenant không có `org_admin` ở `main` (người
    vận hành gán qua `POST /api/v1/platform/tenants/{tenant_id}/org-admins`). Trigger AFTER INSERT, UPDATE OF
    `role_keys`, `permission_set_keys` một chiều trên `platform.memberships` chép phần chênh của hai cột sang gán vai trò
    của membership đó, trừ `platform_admin`, cho các đường ghi cũ tới khi ticket 03 khóa cột: khóa có ở NEW mà không ở
    OLD thì chèn gán, khóa có ở OLD mà không ở NEW thì xóa gán, trong cùng câu lệnh (một lần gỡ vai qua đường cũ là một
    lần thu hồi thật); gán không đến từ hai cột (`tenant_owner` của bước 6, 13, 16) không bao giờ bị trigger chạm. Ticket
    03 gỡ trigger này trước khi xóa trắng hai cột cho `ck_memberships_legacy_role_columns`, kẻo lần xóa đó thu hồi mọi
    vai trò. Khóa mà tenant chưa có vai trò nhưng có vai trò mẫu (`platform.roles`, `platform.permission_sets`) thì nhân bản
    trước qua `platform.install_role_template` (ADR-0104 (Accepted) mục 2, "on request"; không đọc rơi về mẫu); khóa không
    là vai trò của tenant cũng không là mẫu thì từ chối với SQLSTATE 23514 (lỗi to).
14. **Giới hạn.** Trigger BEFORE INSERT trên `platform.tenant_roles` với `pg_advisory_xact_lock(hashtext('tenant_roles:' || tenant_id))`:
    200 vai trò chưa xóa (gồm bộ quyền bổ sung) thì nhận, vai trò thứ 201 thì 23514 `role_limit_reached`.
15. Offboarding xuất bốn bảng mới (`platform.tenant_roles`, `platform.tenant_role_permissions`,
    `platform.role_assignments`, `platform.tenant_access_versions`; `test_offboarding.py`) và xóa cả bốn, trên
    phần đọc catalog và `export_rows` mà foundations-hardening/07 đã viết lại, dưới test phủ offboarding của
    studio-skeleton/01 (`studio-skeleton:R4.3`). Ba bảng đầu đi bước xóa mặc định (`dw_app` có DELETE).
    `platform.tenant_access_versions` giữ `dw_app` chỉ SELECT (bước 9; ADR-0104 (Accepted) mục 7) và mất dòng của nó qua
    một bước xóa đăng ký trong `OffboardingPurgeSteps.platform()` (`offboarding.py:255-265`), như
    `platform.purge_tenant_marketing` của `marketing_purge_step()`: `platform.purge_tenant_access_version(p_tenant_id uuid)`
    SECURITY DEFINER, `search_path` ghim, REVOKE khỏi PUBLIC, EXECUTE chỉ cho `dw_app`, xóa dòng của tenant đó và từ chối
    với SQLSTATE 23514 khi `platform.tenants.status` khác `offboarding`; bước khai `tables` là
    `{"platform.tenant_access_versions"}`, nên test phủ thấy bảng được xóa mà không cần dòng `STUDIO_EXCLUSIONS` nào
    (`OffboardingExclusion` đòi đúng một cách xóa, và `kept` đòi một thời hạn lưu giữ có `enforced`, `offboarding.py:163-189`).
    Sau lượt xóa, bộ đọc AccessContext không thấy dòng phiên bản thì đọc thẳng PostgreSQL và không ghi cache (đóng khi
    thiếu, R4.2).
16. **Hai chủ sở hữu khi tạo công ty** (R3.1, R3.9-R3.11; V4.38). Revision (id hex của `alembic revision`):
    - `ck_tenants_status` thay bằng `CHECK (status IN ('setup', 'active', 'locked', 'offboarding', 'offboarded'))`
      (`db/migrations/versions/5d9d89ffc716_tenant_offboarding_requests.py:79-80`); trigger trạng thái của
      foundations-hardening/02 (`foundations-hardening:R3.2`) giữ nguyên. Một trigger BEFORE UPDATE OF `status` trên
      `platform.tenants` từ chối với SQLSTATE 23514 mọi bước vào `setup` từ trạng thái khác, vì `setup` chỉ có lúc tạo,
      và mọi bước rời `setup` sang trạng thái khác `active` và `offboarding`; người vận hành offboard một công ty `setup`
      qua luồng offboarding hiện có (spec R3.15; Đạt, Q-h2).
    - Luật chuyển (R3.10): `platform.complete_tenant_setup()` SECURITY DEFINER, `search_path` ghim, gắn trên mọi lệnh ghi
      có thể đưa số đó lên hai: AFTER UPDATE OF `status` trên `platform.tenant_members` khi `NEW.status = 'active'` và
      `OLD.status <> 'active'`, và AFTER INSERT OR UPDATE OF `role_id`, `membership_id` trên `platform.role_assignments`
      khi vai trò mới là `tenant_owner` (gán chủ cho người đã `active`). Ba người ghi INSERT thẳng dòng `active`
      (`_provision_default_membership`, `scripts/grant_platform_admin.py`, `seed_env`; MEDIUM 10 của gate
      org-and-principals/02) được phủ bởi trigger trên `platform.role_assignments`: khóa ngoại membership → thành viên công
      ty buộc dòng thành viên có trước mọi gán, nên một INSERT trên `platform.tenant_members` không bao giờ là lệnh ghi
      cuối đưa số lên hai, và không gắn trigger INSERT ở đó. Hàm khóa dòng tenant (`SELECT ... FROM platform.tenants WHERE id = ... FOR UPDATE`) trước khi
      đếm, nên hai lần kích hoạt hai chủ sở hữu trong hai giao dịch đồng thời xếp hàng và giao dịch sau đếm thấy cả hai
      (mỗi câu của plpgsql lấy snapshot mới); khi `platform.tenants.status` là `setup` và số thành viên công ty `active` có
      gán `tenant_owner` (đếm trên `platform.role_assignments` nối `platform.tenant_members`, không qua
      `platform.effective_grants`, vốn chỉ tính tenant `active`) từ hai trở lên, đặt `status = 'active'` (`WHERE status =
'setup'`) trong cùng giao dịch và ghi audit `platform.tenant.setup_completed` đứng tên người mà dòng của lệnh ghi
      nêu (người vừa `active`, hay người vừa được gán chủ), `details` là id hai chủ sở hữu, nhãn tiếng Việt của hành động
      vào mảnh `configs/copy/audit_actions.d/tenant-rbac.yaml` trong cùng thay đổi (H-21). Lần đăng nhập đầu của chủ sở
      hữu là đường kích hoạt thường: `bootstrap` gọi `platform.activate_invited_members` (org-and-principals:R4.5) ở mọi
      tenant của người đó, không xét trạng thái tenant.
    - Cửa của công ty `setup` (R3.14; Đạt, Q-h1) không cần nhánh mới: `_access_in` đã từ chối mọi tenant có
      `tenant_status != 'active'` (`membership_lookup.py:117`), nên mọi route dựng AccessContext, kể cả `GET /api/v1/me`,
      từ chối công ty `setup` như `locked`. Ngoại lệ là những đường không dựng AccessContext: lần đăng nhập đầu và lần nhận
      lời mời làm chủ là `GET /api/v1/auth/bootstrap` (chỉ `RequireVerifiedIdentity`, `auth.py:48-58`), nơi hàm kích hoạt
      chạy và workspace của công ty `setup` vẫn được liệt kê như hôm nay; route của người vận hành dùng
      `RequireProvisioningContext` (`platform.py:3-5`). Không thêm điều kiện trạng thái tenant vào
      `platform.activate_invited_members` hay vào cửa của người chủ sở hữu; test của luật chuyển chạy cả trên lệnh ghi
      SQL lẫn qua lần đăng nhập đầu.
    - Người vận hành và `support_staff` (R3.11): `platform.guard_operator_tenant_grants()`, trigger BEFORE INSERT, UPDATE
      trên `platform.role_assignments` (người được gán có dòng `platform.platform_operators` hay `platform.support_staff`, và
      vai trò là `tenant_owner` hay có `studio.publish.approve` hay `platform.roles.write` trong
      `platform.tenant_role_permissions`), trên `platform.tenant_role_permissions` (thêm một trong hai khóa vào vai trò
      đang gán cho người như vậy), và BEFORE INSERT trên `platform.platform_operators`, `platform.support_staff` (người
      đang giữ một trong ba quyền đó ở một tenant); SQLSTATE 23514, ràng buộc `ck_role_assignments_operator_not_owner`,
      áp cho mọi vai kể cả `dw_provisioner`, `dw_migrator`. Tên vai trò và hai khóa sống ở một chỗ, hàm này; test so
      hai khóa với danh mục khi chúng đã đăng ký. Đường vượt `platform_admin` không mở route quản trị vai trò (spec R3.16, ticket 03).
      Một nhân viên `support_staff` không bao giờ được thêm membership mới (`platform.refuse_support_staff_membership()`,
      `ck_memberships_not_support_staff`, `af8ee878b4ab`; 409 `support_staff_not_member` của `support_staff_not_member()`,
      `support_access.py:125-130`), nên ở `POST /api/v1/platform/tenants` cửa đó từ chối trước và là chủ của câu trả lời;
      nhánh `platform.support_staff` của hàm này giữ hai đường cửa đó không thấy: người có membership từ trước khi vào danh
      sách (`provisioning.py:458-460`) được gán vai trò, và INSERT `platform.support_staff` cho người đang giữ quyền.
      `POST /api/v1/platform/operators` và `POST /api/v1/platform/support-staff` (`provisioning_repo.py:368-375`, `:412-418`)
      đổi 23514 của hàm này thành 409 `conflict` với `details.reason_code` `operator_not_assignable`, không để thành 500.
    - `POST /api/v1/platform/tenants` (`apps/api/src/dw_api/routes/v1/platform.py:155-168`): thân thêm `owners`, mảng
      đúng hai email khác nhau sau khi chuẩn hóa chữ thường; sai thì 422 `validation_failed`, không ghi gì (R3.9). Một
      giao dịch trong `SqlProvisioningRepository.create_tenant` (`provisioning_repo.py:144-172`, nay ghi `active`): tenant
      `setup`, `install_system_roles`, và với mỗi chủ sở hữu, theo cách `tenant_members.invite` ghi (`tenant_members.py:149-185`),
      người dùng (có rồi thì dùng lại; chưa có thì `subject` `invite:<uuid>`), thành viên công ty `invited`, membership ở
      `main` và gán `tenant_owner` như R3.8. Đối tác của khách (người ngoài công ty khách) đi cùng đường như mọi thành
      viên. Trigger của R3.11 từ chối → 409 `conflict` với `details.reason_code` `operator_not_assignable`, không ghi gì;
      route `.../org-admins` trả cùng mã. Phản hồi có `status`.
    - Quyền DB của `dw_provisioner` cho đường này, khai trong tuple `PROVISIONER` của revision này cạnh tuple cùng tên của
      `0fdd32a39d87` và `349080a62e41`, chép vào `GRANTS` của `scripts/create_provisioner_role.py`, giữ bằng
      `test_the_provisioner_holds_exactly_what_its_code_runs`: SELECT, INSERT trên ba bảng của bước 5; INSERT trên
      `platform.users` (người dùng `invite:` của chủ sở hữu chưa từng đăng nhập; hôm nay chỉ SELECT); SELECT trên
      `platform.permissions` (trigger mức của bước 3 và `install_system_roles` đọc `scope_kind`; ADR-0104 (Accepted) mục 1
      đã nêu quyền này, ticket 01 chưa cấp vì code của vai này chưa đọc). Không INSERT trên
      `platform.tenant_access_versions`: dòng do `platform.bump_access_version()` tạo (bước 9).
    - Migration chuyển dữ liệu (bước 13) không đổi tenant đã có sang `setup`; danh sách tenant dưới hai chủ sở hữu mà nó
      in ra vẫn là việc của người vận hành.
17. **Dưới hai người** (R3.12, R3.13; H-15). `platform.tenants.owner_coverage_low_since timestamptz NULL`. Trigger AFTER
    INSERT, UPDATE, DELETE theo câu lệnh (bảng chuyển tiếp) trên `platform.role_assignments`,
    `platform.tenant_role_permissions`, `platform.tenant_roles`, `platform.tenant_members` gọi
    `platform.check_owner_coverage(p_tenant_id)` một lần cho mỗi tenant của câu lệnh: với tenant `active`, đếm người
    `active` giữ `studio.publish.approve` và người `active` giữ `platform.roles.write` trên `platform.effective_grants`,
    chỉ với những khóa trong hai khóa đó mà danh mục có ở `status` `active`: khóa chưa đăng ký (cả hai lúc ticket này
    xong: `platform.roles.write` đến với ticket 03, `studio.publish.approve` với cụm Studio của nó) không ai giữ được, nên
    không được đếm, không đặt cột và không gây cảnh báo; nếu không, mọi tenant `active` bị báo ở lần ghi vai trò đầu tiên.
    Một trong các số được đếm dưới hai mà cột NULL → đặt cột bằng `now()` và ghi outbox `platform.tenant.owner_coverage_low`
    (`tenant_id`, khóa nào dưới hai, giá trị cột vừa đặt) cùng giao dịch; mọi số được đếm từ hai trở lên (hay không còn
    khóa nào để đếm) mà cột khác NULL → đặt NULL. Handler của sự kiện, đăng ký ở composition root của worker, gửi một
    thông báo cho mỗi người giữ `platform.members.write` ở độ sâu công ty, như `workflow-engine:R5.20`, qua cửa ghi duy
    nhất của bảng thông báo, `platform.deliver_notification` (câu `DELIVER_NOTIFICATION`,
    `adapters/persistence/notifications.py:26-29`; `application/notifications.py` là hộp thư của người đọc và không gửi
    gì): `SqlNotificationRepository` thêm `deliver_in(scope: TenantScope, ...)` chạy cùng câu đó, `deliver` gọi nó, vì
    lane không có AccessContext. Mỗi người nhận được gửi ở workspace neo quyền `platform.members.write` của họ
    (`anchor_workspace_id` của `platform.effective_grants`; id nhỏ nhất khi có nhiều neo), một lần gọi cho mỗi workspace,
    với `source_key` `platform.tenant.owner_coverage_low:<tenant_id>:<owner_coverage_low_since>` lấy từ sự kiện, nên
    một sự kiện được xử lý lại không gửi lần hai, còn mỗi lần xuống mới là một thông báo mới. `GET /api/v1/platform/tenants` trả
    `owner_coverage_low_since` cạnh `status`; `apps/web/app/platform/page.tsx` có bộ lọc "Đang thiết lập" (`setup`) và
    "Dưới hai người", antd `Table` và `Tag`. Số đo của trigger trên tenant 5.000 người ghi ở Comments cùng số đo FOG-38.

## Tiêu chí chấp nhận

- [x] R2.2 (RB5): người có `approvals.decide` chỉ qua `approver_boost`: AccessContext, `/me`, người giữ quyền, tách nhiệm và `SqlDwMembershipCheck.standing` cùng thấy khóa, và một chủ thể DW có khóa chỉ qua `platform.role_assignments` (chèn bằng SQL) có khóa đó trong `SqlDwBoundary.boundary`; đổi `platform.effective_grants` bỏ bộ quyền bổ sung → mọi test đó đỏ.
- [x] R2.2: `platform.checker_candidates` cho một khóa trả đúng tập người `active` mà `scope_holders.py` trả cho cùng khóa, trừ người đề xuất; thành viên `suspended` không có trong kết quả.
- [x] R2.3: khóa mức `tenant` gán ở A có trong `GET /api/v1/me` khi làm việc ở B.
- [x] R2.4 (RB6): `approvals.decide` mức `workspace` gán ở A vắng ở `/me` của B; bỏ điều kiện neo trong `platform.scopes_in` → đỏ.
- [x] R2.5 (RB7): qua đường SQL, `platform.effective_grants` của thành viên `suspended`, tenant `locked`, vai trò xóa mềm, gán quá `expires_at` → khóa vắng, và `scope_holders.py` không còn bộ lọc riêng mà vẫn không trả người đó; gỡ từng điều kiện trong hàm → đỏ.
- [x] R2.6: Vitest: nav và trang admin đọc `/me` giả; grep không còn chuỗi `platform_admin` trong `apps/web` ngoài test; bootstrap không còn `roles`, `scopes`.
- [x] R2.7 (RB34): migration thử đăng ký một khóa `active` có `tenant_grantable` sau khi gán `tenant_owner` → `platform.effective_grants` và `/me` của người đó có khóa ở mức `tenant`, `platform.tenant_role_permissions` không có dòng nào cho `tenant_owner`; `platform.admin` (`tenant_grantable` sai) và một khóa `retired` vắng; bỏ điều kiện `tenant_grantable` hay `status` khỏi quyền tính động ở bước 7 → test đỏ.
- [x] R3.1 (RB37): `POST /api/v1/platform/tenants` với hai chủ sở hữu → tenant mới ở `setup`, có đúng `tenant_owner` và `member`, `is_system`, hai thành viên công ty `invited` mỗi người giữ `tenant_owner` ở `main`; lỗi giữa giao dịch → không có tenant, vai trò hay thành viên; `ck_tenants_status` thiếu `setup` → INSERT từ chối, test đỏ.
- [x] R3.1: UPDATE một tenant `active` sang `setup` dưới `dw_provisioner` → 23514, trạng thái giữ; gỡ trigger → test đỏ.
- [x] R3.9 (RB37): một chủ sở hữu, ba, hay hai email chỉ khác hoa thường → 422 `validation_failed`, 0 dòng `platform.tenants`; bỏ kiểm → ca một chủ sở hữu được nhận, test đỏ.
- [x] R3.10 (RB38): kích hoạt chủ sở hữu thứ nhất bằng UPDATE `platform.tenant_members` → tenant giữ `setup`; kích hoạt người thứ hai → tenant `active` và một audit `platform.tenant.setup_completed` trong cùng giao dịch; lùi giao dịch đó → tenant `setup`, không audit; thành viên `active` không giữ `tenant_owner` → tenant giữ `setup`; gỡ trigger → test đỏ.
- [x] R3.10 (RB38): chủ sở hữu thứ nhất `active`; INSERT thẳng một dòng `platform.tenant_members` `active` và membership (như `grant_platform_admin.py`) rồi gán `tenant_owner` cho người đó → tenant `active`, một audit đứng tên người đó; gỡ trigger trên `platform.role_assignments` → tenant giữ `setup`, test đỏ. Hai giao dịch: T1 kích hoạt chủ sở hữu A chưa commit, T2 kích hoạt B (chờ khóa), T1 commit, T2 commit → tenant `active`; bỏ `FOR UPDATE` trên dòng tenant → T2 không chờ, đếm một, tenant giữ `setup`, test đỏ.
- [x] R3.11 (RB39): dưới `dw_provisioner` và `dw_migrator`, gán `tenant_owner` cho người vận hành → 23514; `POST /api/v1/platform/tenants` với email của một người vận hành làm chủ sở hữu → 409 `operator_not_assignable`, 0 dòng; với email của một nhân viên `support_staff` → 409 `support_staff_not_member` của cửa membership có sẵn, 0 dòng; thêm `studio.publish.approve` hay `platform.roles.write` (khóa thử nếu cụm chủ chưa đăng ký) vào vai trò đang gán cho người vận hành → 23514; INSERT `platform.platform_operators` hay `platform.support_staff` cho một `tenant_owner` → 23514, và `POST /api/v1/platform/operators`, `POST /api/v1/platform/support-staff` cho người đó → 409 `operator_not_assignable`, không 500; gán `tenant_owner` cho một nhân viên `support_staff` có membership từ trước khi vào danh sách → 23514; đối tác ngoài công ty khách làm chủ sở hữu thứ hai → nhận; gỡ trigger hay bỏ nhánh `platform.support_staff` → hai ca `support_staff` cuối được nhận, test đỏ.
- [x] R3.12 (RB40): khóa thử `platform.roles.write` đăng ký `active` trong giao dịch của test (cụm chủ chưa đăng ký); tenant `active` với hai người giữ nó; gỡ gán của một người → đúng một thông báo cho mỗi người giữ `platform.members.write` ở độ sâu công ty, ở workspace neo quyền đó của người nhận, kể cả người nhận không có membership ở `main`, `owner_coverage_low_since` có giá trị; xử lý lại cùng sự kiện outbox → không thông báo thứ hai; gỡ thêm một gán → không thông báo thứ hai; gán lại cho hai người → cột về NULL; xuống lần nữa → một thông báo mới; bỏ kiểm cột trước khi ghi outbox → thông báo thứ hai, test đỏ. Khi cả hai khóa chưa có trong danh mục, gỡ một gán vai trò → không outbox, cột NULL; đếm khóa chưa đăng ký là 0 → test đỏ.
- [x] R3.13 (RB40): `GET /api/v1/platform/tenants` trả `status` `setup` cho tenant mới và `owner_coverage_low_since` cho tenant dưới hai người; Vitest: màn `apps/web/app/platform` lọc "Đang thiết lập" và "Dưới hai người" trên dữ liệu giả.
- [x] R3.14 (RB41): công ty `setup` vừa tạo; chủ sở hữu thứ nhất đăng nhập lần đầu và nhận lời mời → được, công ty
      giữ `setup`; sau đó người đó gọi `/me`, tạo một lời mời khác, xin một lượt chạy hay gửi phát hành → từ chối như
      `locked`; người vận hành gọi `GET /api/v1/platform/tenants` → được; chủ sở hữu thứ hai đăng nhập lần đầu → công
      ty `active` (R3.10); thêm điều kiện tenant `active` vào `platform.activate_invited_members` (đóng ngoại lệ đăng
      nhập đầu) → không chủ sở hữu nào kích hoạt được, test đỏ; đổi phép kiểm của `_access_in` từ `!= 'active'` thành
      `= 'locked'` → lượt chạy được nhận, test đỏ.
- [x] R3.15 (RB41): UPDATE `status` `setup` → `locked` → 23514, không đổi gì; người vận hành offboard công ty `setup` →
      `offboarding`; UPDATE `active` → `setup` → 23514; gỡ trigger → bước `setup` → `locked` được nhận, test đỏ.
- [x] R3.2 (RB10): migration thử sửa mẫu `approver` → vai trò `approver` đã nhân bản giữ nguyên quyền và mức.
- [x] R3.3 (RB8): kết nối `app.tenant_id` A đọc vai trò, quyền, gán của B → 0 dòng; INSERT gán với `role_id` của B → FK kép từ chối; kết nối không đặt tenant → 0 dòng.
- [x] R3.4 (RB9): `platform.roles.write` mức `workspace` → 23514; khóa `workspace` mức `own` → 23514; gỡ trigger → đỏ.
- [x] R3.5: test so sánh trên dữ liệu seed và trên tenant cài sẵn có người giữ `org_admin` ở `main`, người có membership ở hai workspace với khóa mức `tenant` ở một, và người chỉ có bộ quyền bổ sung: với mọi membership, khóa trước migration (trừ `platform.admin` của `platform_admin`) đều còn sau migration, và mỗi khóa mới đến từ `tenant_owner` mà R3.6 gán hay từ một khóa mức `tenant` gán ở workspace khác (R2.3); membership không thuộc hai trường hợp đó có tập khóa bằng nhau; migration bỏ chuyển bộ quyền bổ sung → test đỏ.
- [x] R4.1: đường ghi cũ: đổi vai của `tenant_members.py:255-270` bỏ `approver` khỏi `role_keys` → gán vai trò đó biến mất trong cùng câu lệnh và request kế tiếp không có `approvals.decide`, còn gán `tenant_owner` của cùng membership ở lại; `PUT /api/v1/admin/members/{user_id}/permission-sets` bỏ `approver_boost` → gán đó biến mất; `membership_admin` gán `director` ở tenant chưa có vai trò đó → vai trò được nhân bản từ mẫu rồi gán; khóa không là vai trò cũng không là mẫu → 23514; trigger chỉ chèn mà không xóa, hay xóa cả gán không đến từ hai cột → test đỏ.
- [x] R3.6: tenant seed có `org_admin` ở `main` → người đó giữ `tenant_owner`, có đúng một audit với `details.actor` là `system:rbac_migration`; tenant seed chỉ một chủ sở hữu và tenant seed không có `org_admin` ở `main` có tên trong danh sách migration in ra.
- [x] R3.7 (RB11): vai trò thứ 201 → 23514 `role_limit_reached`; hai giao dịch đồng thời ở vai trò thứ 200 → đúng một thành công; gỡ khóa tư vấn → đỏ.
- [x] R3.8: `POST /api/v1/platform/tenants/{tenant_id}/org-admins` → người đó giữ `tenant_owner`, `role_keys` không có `org_admin`.
- [x] R4.1 (RB12): gỡ gán vai trò bằng SQL thô khi cache còn → request kế tiếp 403 trong vòng 1 giây; operator khóa tenant qua `POST /api/v1/platform/tenants/{tenant_id}/lock` khi route không còn `delete_pattern` → request kế tiếp 403 (FH8 vẫn xanh); gỡ trigger tăng phiên bản → đỏ.
- [x] R4.2 (RB13): bản ghi cache của bản triển khai cũ (thiếu `grants`) hay mang phiên bản cũ → trượt và dựng lại, không mặc định.
- [x] R4.2: offboard một tenant có vai trò, gán và dòng phiên bản → bốn bảng mới 0 dòng của tenant đó và có trong bản xuất, dòng phiên bản không sinh lại dù bước xóa của nó chạy trước bước xóa gán vai trò; `platform.purge_tenant_access_version` cho tenant `active` → 23514, dòng còn; tenant không có dòng phiên bản → bộ đọc AccessContext đọc thẳng PostgreSQL, không ghi cache; `bump_access_version` chèn dòng ở mọi lần bắn → dòng sinh lại, test đỏ.
- [x] R5.1 (RB14): vai trò tenant mang cả hai vế một luật, hai vế gán ở hai workspace → 23514 kèm id; sửa vai trò làm 2 người vi phạm → DETAIL có 2 id; luật đã miễn trừ và xác nhận → nhận; gỡ trigger AFTER → đỏ. Người giữ hai vế ở hai workspace nhờ miễn trừ đã xác nhận: thu hồi miễn trừ → 23514 `ck_sod_waivers_not_in_use`, API 409 với `details.memberships` 1; `platform.refuse_revoking_a_waiver_in_use()` đếm theo membership như cũ → thu hồi được nhận, test đỏ. Đường ghi cũ (lời mời hay đổi vai) làm một người giữ hai vế → 409 với `details.rule` như hôm nay; `separation_of_duties_conflict` không nhận `ck_roles_sod_memberships` → 500, test đỏ.
- [x] R5.2: người giữ `tenant_owner` không bị luật chặn; thêm vai trò thường phá luật cho người đó → 23514.
- [x] G1: `test_the_admin_who_proposed_a_waiver_cannot_confirm_it` xanh trước và sau thay đổi.
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
- 2026-11-02 (agent): checking-plan-readiness, gate đủ (builder check và boundary walk một lượt, không subagent), đọc
  ở `ffe5cd8` trên code của tenant-rbac/01 (`00a5d8e`) và org-and-principals/02 (`5a0f8e9`). Script 24 Đạt, 0 cảnh báo.
  Tìm 0 CRITICAL, 12 HIGH; cả 12 sửa theo khuyến nghị (các dòng sau), MEDIUM ghi dưới, chưa sửa.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 1: luật chuyển `setup` → `active` chỉ gắn AFTER UPDATE trên
  `platform.tenant_members`, hẹp hơn R3.10 ("một lệnh ghi"): ba người ghi INSERT thẳng dòng `active` (MEDIUM 10 của gate
  org-and-principals/02) và một lần gán `tenant_owner` cho người đã `active` đưa số chủ sở hữu lên hai mà không trigger nào
  thấy, công ty kẹt ở `setup` (failure-modes #5). Sửa: bước 16 gắn hàm cả AFTER INSERT OR UPDATE gán `tenant_owner` trên
  `platform.role_assignments` (khóa ngoại buộc dòng thành viên có trước mọi gán, nên trigger này phủ ba người ghi INSERT
  `active`; lượt xác nhận bỏ nhánh INSERT trên `platform.tenant_members` vì không bao giờ là lệnh ghi cuối); một tiêu chí
  R3.10 thêm. Nếu sai thì: mọi người ghi `active` đổi sang ghi `invited` rồi kích hoạt bằng UPDATE, và trigger trên
  `platform.role_assignments` bỏ.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 2: hai chủ sở hữu đăng nhập lần đầu cùng lúc: mỗi giao dịch chỉ
  thấy người của mình `active`, đếm một, không ai đặt `active`, và không lệnh ghi nào về sau kích hoạt lại, nên công ty kẹt
  ở `setup` (người vận hành không mở khóa được: `set_tenant_status` chỉ nhận `active`, `locked`). Sửa: hàm khóa dòng tenant
  `FOR UPDATE` trước khi đếm, UPDATE `WHERE status = 'setup'`; tiêu chí hai giao dịch có phép đột biến. Nếu sai thì: một
  khóa tư vấn theo tenant thay cho khóa dòng.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 3: quyền DB của `dw_provisioner` cho bước 16 không được nêu, mà đường
  tạo công ty chạy bằng vai này: hôm nay nó chỉ SELECT `platform.users` (`0fdd32a39d87`), nên không tạo được người dùng
  `invite:` của chủ sở hữu chưa đăng nhập; không SELECT `platform.permissions` (ticket 01), mà trigger mức và
  `install_system_roles` đọc `scope_kind`; ai chèn dòng phiên bản cũng chưa ai nói. Sửa: bước 16 khai INSERT
  `platform.users` và SELECT `platform.permissions` trong tuple `PROVISIONER` và `create_provisioner_role.py`; bước 9 cho
  `bump_access_version()` chèn dòng khi tenant ra đời. Nếu sai thì: hai việc đó qua một hàm SECURITY DEFINER hẹp, vai giữ
  nguyên quyền.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 4: R3.5 mâu thuẫn với R3.6, R2.3 và G2 (spec, dòng Quyết định cùng
  ngày); test R3.5 "trên dữ liệu seed" chỉ xanh vì seed không có `org_admin` và chỉ một workspace. Sửa: R3.5 của spec và
  tiêu chí R3.5 (tenant cài sẵn có ba ca). Nếu sai thì: xem dòng spec.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 5: bước 8 bỏ sót hai người đọc `effective_scopes` ở
  `digital_workers_repo.py` (`SqlDwMembershipCheck._standing`, `SqlDwBoundary.boundary`), nên đổi chữ ký làm vỡ chúng hay
  để lại một bản thứ hai của "người này giữ gì" đọc `role_keys` (failure-modes #2; ADR-0104 (Accepted) mục 5); khi ticket 03
  khóa cột, ranh giới của mọi DW thành rỗng. Sửa: bước 8 cho cả hai đọc qua adapter, `_check_roles` và
  `dw_principal_roles_fixed` ở lại trên `role_keys` tới ticket 03 và org-and-principals/03; tiêu chí R2.2 thêm hai ca. Nếu
  sai thì: hai người đọc đó giữ `role_keys` và ticket 03 dời chúng cùng lúc khóa cột.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 6: bước 12 không nhắc `platform.refuse_revoking_a_waiver_in_use()`
  (`6b26771e549d`), vẫn đếm từng membership theo `role_keys`: người giữ hai vế ở hai workspace nhờ miễn trừ thì miễn trừ
  thu hồi được, và người đó giữ cả hai vế sau đó (R5.1 có hai câu trả lời). Bước 12 cũng không nói số phận của trigger tách
  nhiệm trên `platform.memberships`. Sửa: bước 12 viết lại hàm đếm người trên quyền hiệu lực, bỏ trigger cũ; lượt xác
  nhận thêm: `separation_of_duties_conflict` nhận `ck_roles_sod_memberships`, vì bỏ trigger cũ làm các route ghi membership
  mất 409 `{rule, reason}`; tiêu chí R5.1 thêm hai ca. Nếu sai thì: thu hồi miễn trừ đang được dựa vào là việc của ticket
  03, có test ở đó.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 7: lúc ticket này xong, danh mục không có `platform.roles.write` lẫn
  `studio.publish.approve` (26 khóa của `ebb17244abc6`), nên `check_owner_coverage` đếm 0 cho cả hai và báo mọi tenant
  `active` ở lần ghi vai trò đầu tiên; tiêu chí R3.12 dùng một khóa chưa tồn tại. Sửa: bước 17 chỉ đếm khóa danh mục có ở
  `active`; tiêu chí R3.12 đăng ký khóa thử như R3.11 và thêm ca "chưa đăng ký → không cảnh báo". Nếu sai thì: hàm đếm khóa
  chưa đăng ký là 0 và ticket 02 chờ ticket đăng ký hai khóa.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 8: bước 17 gửi "qua `application/notifications.py`", là hộp thư của
  người đọc; người gửi duy nhất là `SqlNotificationRepository.deliver`, đòi AccessContext (lane không có) và gửi trong một
  workspace với một `source_key`, nên người nhận giữ quyền mức `tenant` không có membership ở workspace đã chọn mất thông
  báo im lặng, và `source_key` quyết lần gửi lại. Sửa: `deliver_in(TenantScope, ...)`, gửi ở workspace neo quyền của người
  nhận, `source_key` theo `owner_coverage_low_since`; tiêu chí R3.12 thêm hai ca. Nếu sai thì: gửi ở `main` cho mọi người
  nhận, và người nhận không có membership ở `main` được thêm vào danh sách của màn vận hành.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 9: bước 16 viết "cửa cho qua đúng lần đăng nhập đầu và lần nhận lời
  mời làm chủ", đọc được thành một nhánh mới trong `_access_in` cho hai chủ sở hữu, trong khi cửa đã từ chối mọi tenant
  khác `active` và lần đăng nhập đầu là `GET /api/v1/auth/bootstrap`, không dựng AccessContext; hai phép đột biến của tiêu
  chí R3.14 trỏ tới một nhánh không có. Sửa: bước 16 nói ngoại lệ là cấu trúc (bootstrap và route người vận hành không qua
  cửa), không thêm nhánh; hai phép đột biến trỏ tới `activate_invited_members` và phép so của `_access_in`. Nếu sai thì:
  Đạt muốn chủ sở hữu gọi được `/me` trong `setup`, và R3.14 đổi trước.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 10: tiêu chí R3.11 đòi 409 `operator_not_assignable` khi tạo công ty
  với email của một `support_staff`, nhưng cửa membership có sẵn (`ck_memberships_not_support_staff`, `af8ee878b4ab`) từ
  chối trước với `support_staff_not_member`, nên tiêu chí không xanh được mà không đổi cửa đó, và phép đột biến "bỏ nhánh
  `support_staff`" không làm đỏ ca này (failure-modes #3); `POST .../operators`, `.../support-staff` không bắt 23514 mới, ra 500. Sửa: ca tạo công ty mong mã có sẵn, nhánh `support_staff` được thử ở hai đường cửa membership không thấy, hai route
  đổi 23514 thành 409. Nếu sai thì: `platform.refuse_support_staff_membership()` nhường cho trigger mới và mã thống nhất
  thành `operator_not_assignable`.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 11: bước 15 đặt `platform.tenant_access_versions` vào
  `STUDIO_EXCLUSIONS` với lý do "giữ có chủ ý", dạng mà `OffboardingExclusion` không có (spec, dòng Quyết định cùng ngày).
  Sửa: bước 15 dùng một bước xóa của nền tảng qua hàm SECURITY DEFINER, bước 9 chỉ chèn dòng khi tenant ra đời; một tiêu chí
  R4.2 thêm. Nếu sai thì: xem dòng spec.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 12: trigger "một chiều chép" của bước 13 không nói lần bỏ một khóa
  khỏi `role_keys` có xóa gán không (chỉ chèn thì một lần gỡ vai qua `membership_admin` không thu hồi gì, R4.1), và "khóa lạ
  thì từ chối" từ chối cả khóa có vai trò mẫu mà tenant chưa nhân bản: mọi tenant tạo sau ticket này chỉ có `tenant_owner`,
  `member`, nên gán `approver` qua màn quản trị hiện có, `seed_env` và mọi fixture ghi `role_keys` khác `member` đều lỗi.
  Sửa: trigger chép phần chênh OLD/NEW của hai cột (chèn và xóa), không chạm gán không đến từ hai cột (`tenant_owner`;
  lượt xác nhận đổi "đúng bằng" thành phần chênh, vì "đúng bằng" xóa `tenant_owner` ở lần đổi vai kế tiếp), nhân bản mẫu
  khi cần, chỉ từ chối khóa không là vai trò cũng không là mẫu; ticket 03 gỡ trigger trước khi xóa trắng hai cột; một tiêu
  chí R4.1 thêm. Nếu sai thì: tenant mới cài mọi vai trò mẫu lúc tạo và trigger chỉ từ chối khóa không có vai trò của
  tenant.
- 2026-11-02 (agent): MEDIUM của gate cho người dựng, chưa sửa. (M1) neo đã trôi ở Nguồn: `membership_lookup.py:80-106` →
  `_access_in` `:59-190`; `scope_holders.py:67-70` → `:74-77`; `platform.py:154-166` → `:155-168`, `:257` → `:272-283`,
  `:189-232` → `:190-247`, `:26-34` → `:27-35`; `admin_members.py:80-84` → `:108-114`, `:133-139`, `:245-252`;
  `0001_platform_baseline.sql:262-273` → `:265-276`. (M2) R2.6 đòi grep không còn `platform_admin` trong `apps/web`, mà
  bước 11 chỉ nêu ba tệp; còn `components/admin/members-manager.tsx:39-49` (mời vai `platform_admin`),
  `components/session-chip.tsx:22-31`, `lib/nav/roles.ts:26-29` (nhãn của khóa vai W1 còn giữ), `app/approvals/page.tsx:80`
  (chú thích): đọc `platform_bypass` của `/me`; nhãn ở `roles.ts` nên ở lại và grep miễn tệp đó. (M3) R3.15: CSDL vẫn nhận
  `setup` → `active` từ mọi vai khi chưa đủ hai chủ sở hữu (dịch vụ chặn qua `only_from`, `provisioning.py:307`, nhưng trả
  `tenant_offboarding` cho công ty `setup`); nên cho trigger trạng thái đòi cùng phép đếm của `complete_tenant_setup` (một
  hàm đếm dùng chung) và trả `tenant_setup` ở khóa, mở khóa. (M4) R3.11 có cuộc đua: INSERT `platform.platform_operators`
  và gán `tenant_owner` cho cùng người trong hai giao dịch đồng thời đều qua trigger BEFORE; khóa tư vấn theo `user_id` ở
  cả hai nhánh. (M5) PostgreSQL không cho trigger có bảng chuyển tiếp mang nhiều hơn một sự kiện (failure-modes #4: chạy thử
  trước), nên bước 17 là ba trigger mỗi bảng. (M6) tách nhiệm không xét lại khi một người `suspended` được kích hoạt lại
  (UPDATE `platform.tenant_members`), trong khi `effective_grants` bỏ qua họ lúc thu hồi miễn trừ; W1 chỉ SQL đặt được
  `suspended`. (M7) trigger `bump_access_version` trên `platform.tenants` bắn ở mọi cột (đổi tên, `owner_coverage_low_since`),
  xóa cache cả tenant; chấp nhận được, ghi trong số đo FOG-38. (M8) đăng ký một khóa mới (migration INSERT
  `platform.permissions`) không gọi `check_owner_coverage`, nên cảnh báo đầu đến ở lần ghi vai trò kế tiếp. (M9) ticket lớn
  (17 bước); cách chia giữ nguyên vì nhiều ticket dẫn "ticket 02", nhưng bước 16, 17 tách được nếu dựng chậm (dòng duyệt
  cách chia của spec). (M10) `studio.access_epochs` của record-access dẫn cùng dạng `STUDIO_EXCLUSIONS` "giữ có chủ ý" mà
  HIGH 11 thấy không dựng được: báo người gọi, ngoài thư mục này. (M11) đo P50/P95/P99 và FOG-38 ở cuối wave (Đạt,
  2/11/2026), không mỗi ticket; ticket đổi đường tới CSDL ở mọi request (một lần đọc phiên bản, hàm SQL thay hai truy vấn).
- 2026-11-02 (agent): bảng cặp ticket `ready-for-agent` không có đường phụ thuộc với ticket này: connections-and-vault/02
  — `test_rls_coverage.py` (`_TENANT_WIDE_ON_PURPOSE`), `test_privileges.py`, `tables.py`, `offboarding.py`
  (`STUDIO_EXCLUSIONS` của nó, `OffboardingPurgeSteps.platform()` của ticket này), đầu chuỗi Alembic; org-and-principals/04
  — `test_privileges.py`, đầu chuỗi Alembic; usage-and-limits/01 — `test_privileges.py`, `tables.py`; web-ui/antd-shell/06 —
  `apps/web/app/platform/page.tsx`; web-ui/antd-shell/14 và platform-runtime/support-access/03 — `apps/web/lib/session.ts`,
  `apps/web/lib/auth/auth-context.tsx`. Mọi va chạm là thêm dòng cạnh nhau trong cùng tệp, không cùng một quyết định;
  ticket xong sau trỏ lại `down_revision` và gộp dòng. Không dựng song song với connections-and-vault/02 trong cùng cây
  (cùng `offboarding.py`).
- 2026-11-02 (agent): lượt xác nhận của gate, chỉ đọc chỗ sửa của HIGH 1-12: không CRITICAL mới; ba lỗi trong chính chỗ
  sửa đã sửa ngay (trigger cũ của bước 13 "đúng bằng" sẽ xóa `tenant_owner` → phần chênh; nhánh INSERT trên
  `platform.tenant_members` của HIGH 1 không bao giờ là lệnh ghi cuối → bỏ; bỏ trigger tách nhiệm trên membership làm 409
  của route ghi membership thành 500 → `separation_of_duties_conflict` nhận `ck_roles_sod_memberships`). HIGH 1-12 đóng.
  Ticket thêm một revision Alembic (bốn bảng, cột `tenant_grantable`, `owner_coverage_low_since`, `setup` trong
  `ck_tenants_status`, các hàm và trigger, chuyển dữ liệu, quyền `dw_provisioner`), đổi `GET /api/v1/me`,
  `POST /api/v1/platform/tenants` (thân `owners`), `GET /api/v1/platform/tenants`, `.../org-admins`, `.../operators`,
  `.../support-staff`, và đổi đường tới CSDL ở mọi request (đọc phiên bản, hàm SQL dựng AccessContext).
- 2026-11-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): tách nhiệm đọc `platform.assigned_grants(tenant)` (mọi quyền
  một gán vai trò mang, gồm quyền tính động của `tenant_owner`, bất kể trạng thái người hay tenant), lớp ngay dưới
  `platform.effective_grants` (chỉ thêm điều kiện thành viên `active`, tenant `active`), thay vì đọc thẳng
  `effective_grants` như bước 12 viết: `effective_grants` bỏ người `invited` và tenant `setup`, nên lời mời qua đường
  `role_keys` cũ (tiêu chí R5.1) và mọi gán ở công ty `setup` sẽ mang được hai vế một luật mà không bị xét; cách này
  cũng đóng M6 (kích hoạt lại người `suspended` không cần xét lại vì họ vẫn được tính). `refuse_revoking_a_waiver_in_use()`
  đếm người theo cùng lớp đó. Một chủ duy nhất của "gán vai trò mang khóa gì" vẫn giữ (`effective_grants` đọc
  `assigned_grants`). Nếu sai thì: `sod_held_keys` đọc `effective_grants` và lời mời mang hai vế phải bị chặn ở dịch vụ.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): `is_system` do trigger BEFORE suy từ khóa (`tenant_owner`, `member`
  là hệ thống, khóa khác không), không do người ghi; `install_system_roles` nhờ vậy không cần UPDATE (dw_provisioner chỉ
  SELECT, INSERT), và vai trò `member` nhân bản theo yêu cầu ở tenant của fixture cũng là hệ thống. Nếu sai thì: một hàm
  nhân bản nội bộ nhận cờ `is_system`, chỉ `dw_provisioner` gọi được.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): trigger cột cũ (bước 13) từ chối `tenant_owner` trong `role_keys`
  (`ck_memberships_role_keys_known`) để không lần ghi cột nào gỡ được gán chủ sở hữu, và chỉ chạy DELETE khi lần ghi thật
  sự bỏ một khóa (dw_provisioner không có DELETE). `install_role_template` từ chối mẫu mang khóa `tenant_grantable` sai
  (`ck_tenant_role_permissions_grantable`), phần của R6.5 mà ticket 03 mở rộng. Nếu sai thì: bỏ hai phép từ chối này,
  ticket 03 khóa cột.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): tên hai khóa của R3.11/R3.12 sống ở `platform.owner_permission_keys()`
  (IMMUTABLE), mà `guard_operator_tenant_grants()` và `check_owner_coverage()` cùng đọc; test khẳng định hai thân hàm
  không tự viết khóa. Nếu sai thì: chép hai khóa vào thân hàm guard và hàm đếm đọc từ đó.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): lỗi tách nhiệm mới: MESSAGE là mô tả luật, HINT là khóa luật, DETAIL
  tối đa 20 user id; `separation_of_duties_conflict` nhận `ck_roles_sod_memberships`, trả `{rule, reason, holders}`.
  Nếu sai thì: MESSAGE nêu khóa luật và `reason` đọc từ HINT.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): theo khuyến nghị M3, `guard_tenant_setup()` cũng đòi hai chủ sở hữu
  `active` cho `setup` → `active` (một hàm đếm chung, `platform.active_tenant_owners`), và khóa, mở khóa một công ty
  `setup` trả 409 `tenant_setup` thay cho `tenant_offboarding`; màn vận hành ẩn nút Khóa cho công ty `setup`. Theo M4,
  khóa tư vấn theo `user_id` ở nhánh gán vai trò và nhánh thêm người vận hành, `support_staff`. Theo M5 (đã chạy thử trên
  PostgreSQL 16.15: "transition tables cannot be specified for triggers with more than one event"), ba trigger mỗi bảng.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): `platform.scopes_in` cho khóa `record` ở mọi mức và mọi neo (tầm với bản
  ghi là của `workspace_reach`); `checker_candidates` có `p_workspace_id` theo tầm với (mức `tenant`, hay mức `workspace`
  neo ở đó), không đòi membership ở workspace đó, còn `scope_holders.py` trả thành viên của workspace theo `scopes_in`; hai
  câu trả lời trùng nhau khi người giữ có membership ở workspace (tiêu chí R2.2 thử đúng ca đó). Người nhận cảnh báo của
  bước 17 được gửi ở workspace neo nhỏ nhất. Nếu sai thì: `checker_candidates` thêm điều kiện membership ở workspace.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): `platform.purge_tenant_access_version` còn đòi `app.tenant_id` là tenant
  được xóa (như `purge_tenant_marketing`), vì hàm SECURITY DEFINER bỏ qua RLS. Chuyển dữ liệu không cho người vận hành hay
  `support_staff` làm `tenant_owner` (R3.11) và tạo trigger xét quyền sau phần chuyển, nên người đang giữ hai vế ở hai
  workspace ở lại như `f381f1694395` để lại membership; downgrade không dựng lại tách nhiệm theo membership cũ.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): `CachePort.delete_pattern` và hai hàm mẫu khóa bị bỏ, không người gọi nào
  còn; cổng đọc phiên bản tách thành `VersionedMembershipLookupPort` (chỉ bộ cache đọc), `DbAccessContextFactory` giữ
  cổng hẹp. Bản ghi cache mang `access_version` của nó; khác khóa là trượt. Nếu sai thì: giữ `delete_pattern` cho W2.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): fixture của các test có sẵn tạo vai trò mẫu với khóa ngoài danh mục
  (`email.send`, `x.read`, `x.write`, `test.*`), mà FK `permission_key` nay từ chối; `dw_platform.testing.rbac.catalogue_test_keys`
  đăng ký chúng `retired` kèm lý do (không code nào kiểm, nên ba luật của `test_permission_catalogue.py` vẫn giữ). Ba test
  trigger mẫu của `f381f1694395` trong `test_sod_waivers.py` bị bỏ cùng trigger; `test_no_single_role_or_permission_set...`
  thay bằng `sod_rule_broken` trên mẫu. `test_provisioning.py` tạo tenant với hai chủ sở hữu rồi kích hoạt cả hai (như
  lần đăng nhập đầu) để có tenant `active`. Web: `knowledge/page.tsx` mời xuất bản dùng chung theo `scopes` có
  `knowledge.publish_global` (cổng tri thức kiểm đúng scope đó, không có đường vượt), thay cho `hasRole("platform_admin")`.
- 2026-11-02 (agent): resolved. Dựng đủ 17 bước trong revision `b5677d345bc1` (bốn bảng, cột, hàm, trigger, chuyển dữ
  liệu, quyền `dw_provisioner`), bộ đọc AccessContext trên `scopes_in`/`effective_grants`, khóa cache có phiên bản, `/me`
  có `grants`, `access_version`, `platform_bypass`, bootstrap bỏ `roles`, `scopes`, tạo công ty với hai chủ sở hữu ở `setup`,
  `.../org-admins` gán `tenant_owner`, 409 `operator_not_assignable`, bước xóa phiên bản của offboarding, handler cảnh báo
  dưới hai người, web đọc `/me` (tải lại khi đổi workspace và khi gặp 403), màn vận hành có hai bộ lọc. CLAUDE.md mục
  Tenancy thêm một dòng (ADR-0104 (Accepted), Consequences). Test: `test_tenant_roles.py` 41, `test_tenant_roles_migration.py` 2,
  `test_tenant_roles_api.py` 13, `test_owner_coverage_db.py` 1, `test_rls_coverage.py`, `test_privileges.py`, `test_offboarding_coverage.py`, `test_offboarding.py` 104; cả suite integration dw_platform 610 xanh, 1 đỏ có sẵn ngoài ticket (`test_restore_drill`, `marketing_send_log_default_pkey`); integration apps/api cùng `test_channel_decisions.py` 196; unit dw_platform,
  apps/api, apps/worker xanh; Vitest web 26 tệp, 148 test. Mutation `mutations/02.yaml` 40 mục, viết, chưa chạy (mỗi `old`
  kiểm đúng một lần). reviewing-feature-security đọc theo bảng Kiểm soát RB5-RB14, RB34, RB37-RB41: mỗi hàng có test âm
  (tenant khác, người không quyền, vai trò không bỏ qua RLS). reviewing-deployment-security cho các route đổi: chỉ đổi thân
  và phản hồi, không route, ảnh, dịch vụ hay URL ra ngoài mới; `/me` chỉ thêm id và mã khóa, không email.
- 2026-11-03 (agent): gate của ticket 03 trả dòng Xong về dạng một lệnh mà `scripts/check_plans.py` đòi; điều dòng đó
  từng ghi giữ ở đây: gate theo ticket đã xanh (ruff, format, mypy, lint-imports, verify_invariants,
  verify_architecture, unit dw_platform, apps/api, apps/worker, Vitest web, integration của ticket và
  `test_rls_coverage.py`, `test_privileges.py`, `test_offboarding_coverage.py`); chờ lúc đóng hàng: `scripts/mutate.py`
  trên `mutations/02.yaml`, `make test-integration` đầy đủ, P50/P95/P99 (kèm số đo FOG-38 trên tenant 5.000 người,
  M11), ảnh Playwright của màn `/platform`, `/code-review`.
- 2026-11-05 (agent): M11, phần FOG-38: đã đo ở discovery 08 (`db/bench/rbac/RESULTS.md`), công ty 5.000 người, 200
  workspace, ở head. Đọc `tenant_access_versions` mỗi request 0,12 ms p95 phía máy chủ; `effective_grants` 9,9 ms p95 với
  người 30 vai trò ở 10 workspace (1.358 dòng); `GET /api/v1/me` cache nóng P95/P99 237/264 ms, ngay sau tăng version
  267/317 ms (đạt ngân sách tạm); đuôi là GC của Python, `gc.freeze()` sau khởi động đưa P95 về 30 ms. Bước 17 của ticket
  này tốn nhất ở quy mô: `check_owner_coverage` chạy ở mỗi lệnh trên bảng vai trò, 18 ms mỗi lệnh ở 5.000 thành viên, 59%
  của một lần gán 1.000 người (30,2 giây). M7 (trigger trên `platform.tenants` tăng version ở mọi cột) không đo riêng; giá
  của một lần tăng version là mỗi người trượt cache một lần, cột "ngay sau tăng version" ở trên. Lần gán hay sửa vai trò lớn khóa dòng version của công ty tới commit, mọi lần ghi quyền khác của công ty chờ (30
  giây). Đề xuất ticket theo dõi (người điều phối mở): `check_owner_coverage` một lần mỗi giao dịch (trigger ràng buộc
  hoãn tới commit), `_HELD` gọi `scopes_in` trong FROM (28 ms p50 so với 6,7 ms của `effective_grants`), `gc.freeze()` ở
  lifespan của API. Phần P50/P95/P99 so với commit đầu hàng đợi của M11 vẫn của lúc đóng hàng.
