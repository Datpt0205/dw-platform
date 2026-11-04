# 02 — Thành viên cấp tenant và trạng thái

Status: resolved (2026-11-02, main)
Blocked by: 01, .claude/plans/studio/foundations-hardening/issues/02-hang-rao-du-lieu-va-danh-tinh.md, .claude/plans/studio/tenant-rbac/issues/01-mot-chu-cho-quyen.md, .claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md, .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md
Area: studio
Yêu cầu: R4.1, R4.2, R4.3, R4.4, R4.5, R4.7, R4.8, R5.1, G1, G2, OP4, OP5, OP6, OP7

## Mục tiêu

Vị thế của một người trong công ty thành một dòng `platform.tenant_members` có trạng thái `invited`, `active` hay
`suspended`; mọi membership treo vào dòng đó, và người không `active` bị cửa dựng AccessContext từ chối ở mọi workspace
của công ty (R4, R5, YC7). Cửa đó là chủ của câu "được hành động trong tenant"; `platform.effective_grants` của
tenant-rbac/02 là chủ của câu "giữ quyền gì". Ticket này dựng trên `_resolve_user` của foundations-hardening/02 và
bootstrap của tenant-rbac/01 (OPS-b), và chờ studio-skeleton/01, nơi `_TENANT_WIDE_ON_PURPOSE` và test phủ offboarding
ra đời, cùng foundations-hardening/07, vì cùng sửa lane offboarding và `test_offboarding.py`. Từ brief B2 ticket 05, không có quan hệ quản lý (W2).

## Việc cần làm

1. **Bảng.** Migration (id hex của `alembic revision`): `platform.tenant_members`:
    - `tenant_id uuid NOT NULL` FK `platform.tenants` `ON DELETE CASCADE`, `user_id uuid NOT NULL` FK `platform.users`
      `ON DELETE CASCADE`, `PRIMARY KEY (tenant_id, user_id)`, index `ix_tenant_members_user_id (user_id)`;
    - `status text NOT NULL` với `ck_tenant_members_status CHECK (status IN ('invited','active','suspended'))`, không
      default;
    - `status_changed_at`, `created_at`, `updated_at` (`timestamptz NOT NULL DEFAULT now()`), trigger `updated_at` nhường
      giá trị câu lệnh nêu (CLAUDE.md, "Data model rules"); trigger `BEFORE UPDATE OF status` đặt `status_changed_at`
      bằng `now()` khi `status` đổi giá trị, cũng nhường giá trị câu lệnh nêu, để mọi đường đổi trạng thái (hàm kích
      hoạt của bước 4, câu SQL của test, route W2) đều dời nó; người đọc: `source_key` của lời báo `principal_inactive`
      ở workflow-engine/04 (workflow-engine:R5.20).
      Cột quản lý trực tiếp, mã nhân sự và nguồn ghi đến ở W2 (ADR-0102 (Accepted) mục 3).
2. **RLS và quyền DB.** ENABLE và FORCE; `tenant_isolation_tenant_members` theo `app.tenant_id`;
   `tenant_members_self_select` FOR SELECT theo `app.principal_id`, cùng dạng `memberships_self_select`, để bootstrap thấy
   trạng thái của chính người đó ở mọi tenant. `dw_app` SELECT, INSERT, UPDATE, DELETE; `dw_provisioner` SELECT, INSERT;
   khẳng định trong `test_privileges.py`, `test_rls_coverage.py`. Trong `test_rls_coverage.py`: thêm
   `("tenant_members", "tenant_members_self_select")` vào `_PRINCIPAL_ONLY_ON_PURPOSE` kèm lý do (bootstrap đọc trạng thái
   của chính người đó trước khi biết tenant; chỉ SELECT), và `platform.tenant_members` vào `_TENANT_WIDE_ON_PURPOSE` của
   studio-skeleton/01 kèm lý do (vị thế của một người thuộc cả công ty, không thuộc workspace nào).
3. **Chuyển dữ liệu.** Một dòng cho mỗi cặp `(tenant_id, user_id)` có trong `platform.memberships`: `active` khi người
   dùng là `kind = 'service'` (tài khoản dịch vụ của digital-worker/01, `be93e0c26a4c`: trạng thái của nó là dòng này,
   ADR-0103 (Accepted) quyết 2; R6.1), hay khi người đó đã đăng nhập theo đúng luật của `member_status()`
   (`directory.py:27-39`; ADR-0102 (Accepted) Consequences), không thì `invited`. Sau đó
   `fk_memberships_tenant_members (tenant_id, user_id)` tới `platform.tenant_members` `ON DELETE CASCADE`, dùng index sẵn
   có `ix_memberships_tenant_user`.
4. **Người ghi.** Mỗi đường ghi membership ghi dòng thành viên công ty trước, cùng giao dịch
   (`INSERT ... ON CONFLICT (tenant_id, user_id) DO NOTHING`; dòng đã có giữ trạng thái của nó, kể cả `suspended`):
    - ghi `invited`: lời mời của `tenant_members` (`tenant_members.py:148`, R4.4, kể cả người đã đăng nhập ở công ty
      khác), `membership_admin` (`membership_admin.py:115`) và `grant_role` của `provisioning_repo`
      (`provisioning_repo.py:295`); người đó thành `active` ở lần đăng nhập kế tiếp (đoạn dưới), nên mọi lần kích hoạt
      người là một câu UPDATE mà trigger của tenant-rbac/02 thấy;
    - ghi `active`: `_provision_default_membership` (người vừa đăng nhập), `scripts/grant_platform_admin.py` (lệnh của
      người vận hành), `seed_env` (dữ liệu dev; gieo lại đặt dòng của nó về `active` bằng `ON CONFLICT ... DO UPDATE`)
      và `SqlDigitalWorkerRepository.create` (`digital_workers_repo.py:135`), vì tài khoản dịch vụ là thành viên công ty
      `active` (R6.1; ADR-0103 (Accepted) quyết 2);
    - mọi đường ghi `platform.memberships` có lúc dựng mà danh sách trên chưa nêu (tìm `insert(tables.memberships` và
      `INSERT INTO platform.memberships`), như `scripts/demo_dw_seed.py` của leadcare/02 nếu đã có, theo luật của
      đường gần nhất ở trên; fixture test ghi membership bằng SQL thô ghi dòng thành viên công ty trước, qua một helper.

    **Kích hoạt.** Ở mỗi lần đăng nhập, `bootstrap` (`identity_provisioning.py:111-160`) gọi, ngay sau `_resolve_user` và
    trước `_read_memberships`, trong cùng giao dịch nối danh tính, hàm `platform.activate_invited_members(p_user_id uuid)
RETURNS integer` (SECURITY DEFINER, `SET search_path = pg_catalog, platform`, REVOKE khỏi PUBLIC, EXECUTE chỉ cho
    `dw_app`): một câu `UPDATE platform.tenant_members SET status = 'active' WHERE user_id = p_user_id AND status =
'invited'` ở mọi tenant của người đó, không bao giờ từ `suspended`, vì mở lại cần hai người (D11) và `_resolve_user`
    chạy trước khi có `app.tenant_id`. Không thêm policy ghi nào theo `app.principal_id`: `tenant_members_self_select`
    chỉ SELECT, nên không kết nối nào tự đổi trạng thái của chính mình. Cách này phủ cả nhánh nối danh tính của người được
    mời lẫn nhánh dev (`identity_provisioning.py:172-177`), nơi người dùng gieo sẵn không có dòng
    `platform.external_identities` và nhận `invited` ở bước 3. Đó là lần kích hoạt mà luật chuyển `setup` → `active` của
    tenant-rbac (tenant-rbac:R3.10; V4.38) đọc, qua trigger mà tenant-rbac/02, ticket sau ticket này, gắn lên bảng; ticket
    này không đọc trạng thái `setup` và không đổi `platform.tenants`.

5. **Người đọc.** Dựng AccessContext (`membership_lookup.py:80-106`) join `platform.tenant_members` và đòi
   `status = 'active'`, thiếu dòng là từ chối (fail closed), nên mọi route cần AccessContext, kể cả `GET /api/v1/me`, trả
   403 cho người không `active`; `member_status()` đọc cột thay cho suy luận; `GET /api/v1/admin/members`,
   `GET /api/v1/directory/members` dùng nó; `_read_memberships` của bootstrap, theo bản của tenant-rbac/01, bỏ tenant nơi
   người đó không `active`. Không thêm bộ lọc riêng ở `scope_holders.py`: tenant-rbac/02 đổi nó sang đọc
   `platform.effective_grants`, vốn bỏ thành viên không `active` (tenant-rbac:R2.5).
6. **Phiên bản quyền.** Trigger `platform.bump_access_version()` trên bảng này do tenant-rbac/02 gắn (hàm ra đời ở đó,
   sau ticket này); ticket này không đụng cache.
7. Offboarding xuất và xóa `platform.tenant_members` (`test_offboarding.py`).

## Tiêu chí chấp nhận

- [x] R4.1 (OP4): sau chuyển dữ liệu, mọi cặp `(tenant_id, user_id)` của membership có đúng một dòng, dòng của người dùng `kind = 'service'` là `active` và của người chưa từng đăng nhập là `invited`; INSERT membership không có dòng thành viên công ty → lỗi FK; mọi đường ghi ở bước 4 có test tạo membership mới thành công với đúng trạng thái bước 4 nêu, kể cả tạo DW mới → dòng `active` của tài khoản dịch vụ.
- [x] R4.1: (bước 1) UPDATE `status` sang giá trị khác → `status_changed_at` tiến; UPDATE giữ nguyên `status` → `status_changed_at` không đổi; câu lệnh nêu `status_changed_at` → giữ giá trị đó; gỡ trigger → test đỏ.
- [x] R4.2 (OP4): DELETE dòng thành viên công ty có membership ở hai workspace → 0 membership còn lại, cùng câu lệnh.
- [x] R4.3 (OP5): đặt `suspended` bằng SQL rồi dựng AccessContext không qua cache → `GET /api/v1/me` và một route có kiểm quyền ở cả hai workspace của người đó trả 403; xóa dòng → 403; gỡ điều kiện `status = 'active'` ở join dựng AccessContext → test đỏ.
- [x] R4.4: `POST /api/v1/admin/invitations` cho email mới → dòng `invited`; cho người đã đăng nhập ở tenant khác → dòng `invited`, rồi lần `GET /api/v1/auth/bootstrap` kế tiếp của người đó → `active` và workspace mới có trong kết quả; lỗi giữa giao dịch → không có dòng nào.
- [x] R4.5: người được mời đăng nhập lần đầu → dòng thành `active` trong cùng giao dịch với dòng `platform.external_identities`; người `invited` ở tenant A và `suspended` ở tenant B đăng nhập → A `active`, B vẫn `suspended`; bỏ `AND status = 'invited'` khỏi `platform.activate_invited_members` → test đỏ; kết nối `dw_app` chỉ đặt `app.principal_id` chạy UPDATE dòng `platform.tenant_members` của chính người đó → 0 dòng.
- [x] R4.7 (OP6): kết nối `app.tenant_id` A đọc thành viên của B → 0 dòng; kết nối không đặt tenant → 0 dòng; self-select chỉ trả dòng của chính người đó.
- [x] R4.8 (OP7): người `suspended` ở tenant A, `active` ở tenant B → bootstrap chỉ có workspace của B; gỡ điều kiện → đỏ.
- [x] R5.1: test so sánh: với mọi người của tenant seed, `status` của `GET /api/v1/admin/members` và `GET /api/v1/directory/members` bằng cột `status`.
- [x] G1: `test_an_invited_person_signs_in_and_finds_their_workspace` xanh trước và sau.
- [x] G2: `test_revoke_removes_a_membership` xanh trước và sau; thành viên công ty còn lại sau khi gỡ membership cuối.
- [x] Xong: `make ci` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_members.py:1-8`; spec: R4.1.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/directory.py:27-28`; spec: R5.1.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:105-106`; spec: R4.3.
- `apps/api/src/dw_api/routes/v1/me.py:27-28`; spec: R4.3.
- `packages/python/dw_platform/tests/integration/test_rls_coverage.py:108-131`; spec: R4.7.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_admin.py:109`; spec: R4.1.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:201-222`; spec: R4.1, R4.5.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/provisioning_repo.py:287`; spec: R4.1.
- `packages/python/dw_platform/src/dw_platform/testing/seed_env.py:227`; spec: R4.1.
- `scripts/grant_platform_admin.py:74`; spec: R4.1.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/digital_workers_repo.py:135`; spec: R4.1, R6.1;
  ADR-0103 (Accepted) quyết 2.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:111-160`; spec: R4.5, R4.8.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:172-177`; spec: R4.5.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_members.py:148`; spec: R4.4.
- `.claude/plans/studio/workflow-engine/issues/04-lan-studio-runs.md` bước 3 (`source_key` đọc `status_changed_at`);
  workflow-engine:R5.20.
- `db/migrations/sql/0001_platform_baseline.sql:671`; spec: R4.2.
- `db/migrations/sql/0001_platform_baseline.sql:818`; spec: R4.8.
- ADR-0102 (Accepted) mục 3; brief B2 mục 1.2, 1.3 và ticket 05.

## Comments

- 2026-10-25 (agent): lượt h, theo V4.38 của Đạt: lần đổi `invited` sang `active` ở bước 4 là lần kích hoạt mà luật
  chuyển `setup` → `active` của tenant-rbac đọc (tenant-rbac:R3.10), gắn ở tenant-rbac/02, ticket đã chờ ticket này; không
  thêm cạnh Blocked by.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate CRITICAL C1: "một câu `UPDATE` trên `platform.tenant_members`" trong
  `_resolve_user` không có đường RLS: hàm chạy trước khi `bootstrap` đặt `app.tenant_id` (`identity_provisioning.py:111-
120`), `tenant_members_self_select` chỉ SELECT, nên câu đó cập nhật 0 dòng, và người dựng phải tự chế một policy ghi
  theo `app.principal_id` hay một câu không lọc `status`, cả hai cho phép đổi `suspended` sang `active` không qua hai
  người (D11). Sửa: bước 4 "Kích hoạt": hàm SECURITY DEFINER `platform.activate_invited_members` chỉ đổi `invited` sang
  `active`, gọi ở mỗi lần `bootstrap` ngay sau `_resolve_user`, không policy ghi theo principal; tiêu chí R4.5 thêm ca
  `suspended` ở tenant khác giữ nguyên, phép đột biến bỏ `AND status = 'invited'`, và UPDATE theo principal → 0 dòng.
  Nếu sai thì: `bootstrap` đọc các tenant của người đó qua `tenant_members_self_select`, rồi với từng tenant đặt
  `app.tenant_id` bằng `set_config(..., true)` và UPDATE dưới policy tenant, cùng điều kiện `status = 'invited'`.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH H1: digital-worker/01 (`be93e0c26a4c`, 30/10/2026) đã thêm
  `platform.users.kind`, `platform.service_principals` và một đường ghi membership thứ sáu,
  `SqlDigitalWorkerRepository.create` (`digital_workers_repo.py:135`), bước 4 không nêu, nên tạo DW sẽ lỗi FK; và luật
  chuyển dữ liệu của bước 3 cho tài khoản dịch vụ (chưa từng đăng nhập) `invited`, trái R6.1 và ADR-0103 (Accepted)
  quyết 2 (trạng thái của tài khoản dịch vụ là dòng này), nên mọi lượt chạy DW sẽ bị `principal_inactive` khi
  agent-lifecycle/01 đọc cột. Sửa: bước 3 cho `kind = 'service'` là `active`, bước 4 thêm người ghi đó với `active`, tiêu
  chí R4.1 thêm hai ca. Nếu sai thì: tài khoản dịch vụ không có dòng thành viên công ty và R6.1, ADR-0103 (Accepted) quyết 2 đổi
  trước.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH H2: trạng thái ban đầu của từng người ghi không được nêu
  (`membership_admin`, `seed_env`, `grant_platform_admin.py`), `provisioning_repo` ghi `active` cho người có thể chưa đăng
  nhập (dòng INSERT `active` mà trigger AFTER UPDATE của tenant-rbac/02 không thấy), và người đã đăng nhập ở công ty khác
  được mời theo R4.4 sẽ ở `invited` mãi, vì chỉ lần nối danh tính kích hoạt; người dùng dev gieo sẵn không có dòng
  `platform.external_identities` nên bước 3 cho họ `invited` mà nhánh dev không bao giờ kích hoạt. Sửa: bước 4 chia
  người ghi `invited` và `active`, `seed_env` gieo lại về `active`, và lần kích hoạt chạy ở mọi lần đăng nhập (C1); tiêu
  chí R4.4 thêm ca người đã đăng nhập. R4.4 của spec giữ nguyên chữ. Nếu sai thì: mọi người ghi theo luật của bước 3
  (`active` khi đã có danh tính đăng nhập), R4.4 thêm nhánh đó, và tenant-rbac/02 gắn luật `setup` lên cả INSERT.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH H3: `status_changed_at` có người đọc (khóa chống lặp
  `source_key` của workflow-engine/04, workflow-engine:R5.20, có test "kích hoạt lại rồi tạm khóa lần nữa → thêm đúng một
  thông báo") mà ticket chỉ cho nó `DEFAULT now()`, nên lần đổi trạng thái thứ hai giữ giá trị cũ và lời báo thứ hai mất
  (failure-modes #1). Sửa: bước 1 thêm trigger `BEFORE UPDATE OF status` dời cột khi `status` đổi, nhường giá trị câu
  lệnh nêu, và một tiêu chí có phép đột biến. Nếu sai thì: mỗi đường đổi trạng thái tự đặt cột, và workflow-engine/04 đổi
  `source_key`.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH H4 (đụng độ không đường phụ thuộc): leadcare/02
  (`ready-for-agent`) viết `scripts/demo_dw_seed.py`, một đường ghi membership mới, và không có đường phụ thuộc với ticket
  này; xong trước thì bước 4 không thấy nó, xong sau thì nó lỗi FK ở `make demo-dw`, nơi CI không chạy. Sửa: bước 4 thêm
  luật "mọi đường ghi có lúc dựng" kèm cách tìm và nêu tên tệp đó. Không sửa leadcare/02 (ngoài phạm vi lượt này; báo
  người gọi). Nếu sai thì: thêm cạnh Blocked by giữa hai ticket theo thứ tự Đạt chọn.
- 2026-11-02 (agent): ghi chú MEDIUM của gate cho người dựng, chưa sửa: (M1) neo đã trôi: `membership_lookup.py:80-106`
  nay là phép join ở `:81-103` và phép kiểm ở `:104-107` của `_access_in`, hàm mà cả `find_access` lẫn
  `find_linked_access` (lệnh qua chat) dùng, nên một điều kiện phủ cả hai cửa; `membership_admin.py:109` → `:115`;
  `identity_provisioning.py:201-222` → `_resolve_user` `:163-225` và `_provision_default_membership` `:240-260`;
  `provisioning_repo.py:287` → `:295`; `test_rls_coverage.py:108-131` → `:110-134`; Hiện trạng của spec (`ab33703`) còn
  ghi "không có tài khoản dịch vụ" và `platform.users` không cột loại, đã cũ từ `be93e0c26a4c` (việc của gate ticket 03).
  (M2) `scripts/create_provisioner_role.py` (`GRANTS`) cần dòng `platform.tenant_members` `SELECT, INSERT`, vì
  `test_privileges.py` giữ script và catalog bằng nhau. (M3) 23 tệp test ghi `platform.memberships` bằng SQL thô hay
  `insert(tables.memberships)`; FK làm chúng đỏ cho tới khi có helper ghi dòng thành viên công ty. (M4)
  `SqlDwMembershipCheck.is_person_in` và `standing` (`digital_workers_repo.py:433-467`) cùng
  `platform.guard_accountable_owner()` (`be93e0c26a4c`) nhận người không `active` làm Business Owner hay Validator của DW,
  trong khi ADR-0103 (Accepted) quyết 3 nói mọi giá trị là thành viên người `active` với FK tới `platform.tenant_members`:
  không ticket nào giữ việc đó (failure-modes #2, giao việc cho người rồi từ chối người đó); ở W1 `suspended` chỉ đặt
  được bằng SQL; đề nghị ticket 03 hay một ticket tiếp của digital-worker. (M5) bước 7 không có tiêu chí: offboarding suy
  bảng từ catalog (`offboarding.py:117`), nên quyền DELETE của `dw_app` là đủ; nên thêm ca "offboard tenant có thành viên
  công ty → 0 dòng, có trong bản xuất". `order_purge_steps` không mang tầm CASCADE sang bảng của bước khác (membership là
  một bước riêng): hôm nay an toàn vì khóa ngoại duy nhất tới `platform.memberships` là CASCADE
  (`fk_channel_preferences_tenant_id_memberships`); một khóa RESTRICT sau này tới membership làm offboarding từ chối.
  (M6) ticket đổi cách request tới DB (join ở `_access_in` và `_read_memberships`, một UPDATE mỗi lần bootstrap): đo
  P50/P95/P99 ở cuối wave (Đạt, 2/11/2026), với 5.000 thành viên công ty (Tiêu chí xong của spec, D12). (M7) test của G2
  là test unit với repo giả (`apps/api/tests/unit/test_admin_members_endpoint.py:179`); nửa "thành viên công ty còn lại"
  cần test integration trên PostgreSQL. (M8) mời lại người còn dòng thành viên công ty mà không còn membership (dư của
  G2): `ON CONFLICT DO NOTHING` giữ trạng thái cũ, người `suspended` vẫn `suspended` trong khi lời mời trả thành công; dòng
  đó không ai xóa tới offboarding (failure-modes #6), việc của route gỡ ở W2. (M9) nhánh dev của `find_access`
  (`membership_lookup.py:208-214`) và `_resolve_user` (`:172-177`) khớp `users.subject` không xét `kind`, nên token dev
  mang subject `service:<uuid>` tới được tài khoản dịch vụ, nay `active`; chỉ ở `local`; thuộc R6.2, OP8 của ticket 03.
  (M10) cho tenant-rbac/02: mọi lần kích hoạt người nay là UPDATE qua hàm của bước 4, nên trigger AFTER UPDATE OF
  `status` của nó thấy; ba người ghi INSERT `active` (`seed_env`, `grant_platform_admin.py`,
  `_provision_default_membership`) không qua trigger đó.
- 2026-11-02 (agent): lượt xác nhận của gate, chỉ đọc năm chỗ sửa C1, H1-H4: không CRITICAL mới; C1, H1-H4 đóng. Hàm
  kích hoạt đứng trước `_read_memberships`, nên R4.8 thấy tenant vừa kích hoạt; nó dùng `ix_tenant_members_user_id` của
  bước 1; tiêu chí UPDATE theo principal đỏ nếu ai thêm policy ghi theo `app.principal_id`; trigger `status_changed_at`
  của H3 dời cột ở cả lần kích hoạt. Một đổi hành vi có chủ ý: người đã đăng nhập mà `membership_admin` hay `grant_role`
  thêm vào công ty vào được ở lần bootstrap kế tiếp, không ngay lập tức; web gọi bootstrap ở mỗi lần nạp và sau lần làm
  mới token (`apps/web/lib/auth/auth-context.tsx:172`, `:217`), nên người dùng không phải làm gì thêm.
- 2026-11-02 (agent): ticket này thêm một revision Alembic (bảng, RLS, chuyển dữ liệu, FK từ `platform.memberships`, hai
  trigger, hàm `platform.activate_invited_members`) và đổi cách request tới DB (join ở cửa AccessContext và bootstrap,
  một UPDATE mỗi lần đăng nhập); không thêm khóa quyền nào, nên `platform.permissions` và `test_permission_catalogue.py`
  không đổi.
- 2026-11-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): dòng `in_ws1[requester] == "invited"  # seeded without a sign-in` của
  G1 (`test_tenant_members.py`) nay là `"active"`: fixture `support_world` ghi người của nó là thành viên công ty `active`
  (họ phải qua cửa AccessContext để dựng ngữ cảnh quản trị), và R5.1 đọc cột thay cho suy từ lần đăng nhập, nên tiền đề
  của dòng đó là đúng cái ticket này đổi; phần còn lại của G1 giữ nguyên chữ và xanh. Nếu sai thì: fixture ghi
  `requester` là `invited` và test dựng AccessContext của nó bằng tay, không qua `SqlMembershipLookup`.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): `test_provisioning.py::test_locking_a_tenant_denies_its_members` thêm
  một lần `bootstrap` sau `assign_org_admin`: `grant_role` ghi `invited` (bước 4), nên người đã đăng nhập vào được ở lần
  đăng nhập kế tiếp, đúng đổi hành vi có chủ ý mà lượt xác nhận của gate nêu. Nếu sai thì: `grant_role` ghi `active` cho
  người đã có danh tính đăng nhập (lúc đó trigger AFTER UPDATE của tenant-rbac/02 không thấy lần kích hoạt đó, H2).
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): quyền `dw_provisioner` SELECT, INSERT trên bảng mới khai trong tuple
  `PROVISIONER` của migration `349080a62e41`, cạnh tuple cùng tên của `0fdd32a39d87`;
  `test_the_provisioner_holds_exactly_what_its_code_runs` so catalog với hợp của hai tuple, và
  `scripts/create_provisioner_role.py` (`GRANTS`) có dòng đó (M2). Nếu sai thì: một migration sửa tuple của
  `0fdd32a39d87` (không được: revision cũ bất biến) hay test đọc một danh sách khác.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): câu chuyển dữ liệu của bước 3 là hằng `BACKFILL` của migration, có
  `ON CONFLICT DO NOTHING` (vô hại trên CSDL thật, nơi bảng còn rỗng), để test chạy nó trên người cài sẵn với khóa ngoại
  tạm gỡ trong một giao dịch rollback: CSDL test được migrate rỗng, nên không có membership cũ nào cho câu đó chuyển.
  Hàm trigger tên `platform.touch_status_changed_at()`. `member_status()` là truy vấn con tương quan trên
  `platform.memberships` theo khóa chính của bảng mới, thay cho một phép join ở hai người gọi. Người ghi của code ứng dụng
  là `tenant_member_rows.ensure_tenant_member`; helper của fixture là `dw_platform.testing.members` (M3: 23 tệp đổi).
  `grant_platform_admin.py` ghi `active` với `ON CONFLICT DO NOTHING` như luật chung của bước 4 (dòng `suspended` giữ
  nguyên; mở lại cần hai người). Nếu sai thì: đổi từng chỗ, không đổi hành vi.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): R4.4 và R5.1 được kiểm ở tầng repository/dịch vụ trên PostgreSQL thật
  (như G1), không qua HTTP: route mời và hai route danh sách là lớp mỏng chép `status` nguyên vẹn; R4.3 kiểm qua app thật
  (`apps/api/tests/integration/test_member_status_door.py`, không cache). R5.1 so trên tenant A của `support_world` (sáu
  người, có `suspended` và `invited`), không trên tenant seed. Nếu sai thì: thêm test HTTP cho hai route và lời mời.
- 2026-11-02 (agent): resolved. Làm: migration `349080a62e41` (bảng, RLS, chuyển dữ liệu, FK
  `fk_memberships_tenant_members`, trigger `updated_at` và `status_changed_at`, `platform.activate_invited_members`),
  bảy người ghi của bước 4 (không có `scripts/demo_dw_seed.py` trong cây lúc dựng), cửa AccessContext (`_access_in`, phủ
  cả `find_linked_access`), `_read_memberships`, `member_status()`, `MemberStatus` thêm `suspended`; offboarding thấy bảng
  từ catalog. Test mới: `test_tenant_member_status.py` 20 (R4.1-R4.5, R4.7, R4.8, R5.1, G2 nửa integration),
  `test_member_status_door.py` 4 (R4.3 qua HTTP), `test_offboarding.py` +1 (bước 7, M5), `test_privileges.py` +1,
  `test_digital_workers_db.py` +1 khẳng định (DW mới → `active`); 23 tệp fixture ghi dòng thành viên công ty qua helper.
  Chạy: ruff, format, mypy, lint-imports, verify_invariants xanh; unit + contract của dw_platform và api 584 xanh;
  integration dw_platform 534 xanh, 1 đỏ có từ trước (`test_permission_catalogue.py` đỏ khi chạy sau
  `test_digital_workers_db.py`, vì vai thử `email.send` của test DW ở lại CSDL phiên; xanh khi chạy riêng; không do ticket
  này), api 137 + 4 xanh, worker 43 xanh, runtime 27 xanh. Các nửa "gỡ … → đỏ" của tiêu chí nằm trong
  `mutations/02.yaml` (24 phép, mỗi kiểm soát một), viết chưa chạy: chạy ở cuối wave. reviewing-feature-security, đọc
  các kiểm soát: tenant (RLS ENABLE/FORCE, policy tenant, self-select chỉ SELECT, test đọc chéo tenant và không đặt
  tenant), người không đủ quyền (UPDATE theo principal → 0 dòng; hàm kích hoạt chỉ `dw_app` gọi được, chỉ `invited` →
  `active`), người `suspended` (403 ở `/me` và route có kiểm scope ở hai workspace; bootstrap bỏ công ty đó; kích hoạt
  không mở lại). Chưa làm (đúng ticket): M4 (DW owner/validator không `active`) cho ticket 03; đo P50/P95/P99 (M6) ở cuối
  wave.
