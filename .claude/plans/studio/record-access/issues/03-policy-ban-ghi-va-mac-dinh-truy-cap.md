# 03 — Cột truy cập, bộ policy trên bảng bản ghi, mặc định truy cập theo object và phạm vi toàn tenant cho lane

Status: ready-for-agent
Blocked by: 02, .claude/plans/studio/custom-objects/issues/02-luoc-do-dinh-nghia-object.md, .claude/plans/studio/foundations-hardening/issues/03-quyen-dw-app-va-rls-initplan.md, .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md
Area: studio
Yêu cầu: G1, R1.2, R1.3, R2.2, R2.3, R2.4, R2.7, R3.1, R3.2, R3.3, R3.4, R3.5, R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, R5.2, R6.1, R6.2, R7.1, R7.2, R7.3, R9.10, RA1, RA2, RA4, RA5, RA6, RA7, RA8, RA9, RA10, RA11, RA13, RA17, RA22, RA23

## Mục tiêu

PostgreSQL quyết định ai thấy bản ghi nào cho mọi đường: bảng `studio.records` mang cột truy cập và đúng một bộ
policy RESTRICTIVE tenant cộng PERMISSIVE theo lệnh đọc sổ tầm của ticket 02; mặc định truy cập của object (cột của
custom-objects/02) vào sổ tầm; cửa API gắn loại actor `user`; offboarding và lane đã đăng ký đọc mọi bản ghi của một
tenant qua một helper duy nhất (spec R1 tới R4, R7, R9.10; ADR-0105 (Accepted) mục 1, 2 và 5).

## Việc cần làm

0. Mẫu policy dựng tạm theo P0, ADR-0105 (Accepted) quyết 1, 3, 4 như viết (`access_key` `uuid` sinh STORED, nhánh đọc
   mảng của một dòng sổ tầm), như ticket 02 bước 0; ticket này không chờ lần đo D12 của ticket 06, và ticket 07 mới áp
   phương án thắng ở D12 bằng một revision sau (gate 4/11/2026 (a); ADR-0105 (Accepted), Amendments 2026-11-04). Khi
   ticket 07 chọn khóa `bigint` (trục K của record-access/01, trigger BEFORE thay cột sinh), các điều kiện của nó nằm ở
   ticket 07, không ở đây.
1. Migration trên `studio.records` của custom-objects ticket 02 (`db/migrations/versions/16357d3dbff8_studio_object_
definitions_and_records.py`), áp cho bảng cha và mọi partition, đọc từ `pg_inherits` (bốn ở DDL tạm modulus 4,
   `custom-objects:R9.5`), không danh sách viết tay; `owner_kind` với CHECK `user`, `team` và NOT NULL đã có, ticket này
   không thêm lại:
    - cột sinh STORED `access_key uuid` bằng `studio.access_key(object_id, workspace_id)` của ticket 02, không chép công
      thức;
    - index `(tenant_id, access_key, created_at DESC, id DESC)` và `(tenant_id, owner_id, object_id, created_at DESC, id DESC)`;
    - trigger BEFORE INSERT OR UPDATE OF `owner_id`, `owner_kind` gọi lỗi 23514 `ck_records_owner_in_tenant` khi người
      phụ trách không phải thành viên công ty `active` của `NEW.tenant_id`; trigger là SECURITY DEFINER, đọc
      `platform.tenant_members` theo `NEW.tenant_id`, nên chạy đúng cả dưới hàm SECURITY DEFINER của ticket 05; trước
      khi đọc, `NEW.tenant_id` khác `app.tenant_id` → cùng lỗi 42501 như WITH CHECK, nên không ca nào của tenant khác
      biết được một người có là thành viên `active` của nó không (lượt xác nhận (m));
      `team` bị từ chối cho tới W2;
    - quyền đã có từ custom-objects/02 (`dw_app` UPDATE chỉ trên `name`, `data`, slot, `version`, `updated_*`,
      `deleted_*`; không quyền nào trên partition; khẳng định ở `_STUDIO_WRITES` của `test_privileges.py`): ticket này
      không cấp lại danh sách cột nào, chỉ thêm `access_key` vào phần khẳng định "không UPDATE" và test âm R1.3 cho cả
      bốn cột `owner_id`, `owner_kind`, `workspace_id`, `object_id` (gate (k)).
2. `studio.object_defs.default_access` và `ck_object_defs_default_access` do custom-objects/02 tạo; ticket này chỉ đọc
   (`A:custom-objects:R1.4~record-access:R2.5`). Thêm nhánh mặc định vào `studio.compute_principal_scope()` của
   ticket 02: object `public_read` vào mảng `read`/`tenant` của người giữ `read` ở bất kỳ mức nào; object
   `public_read_write` vào mảng `read`/`tenant` của người giữ `read` và mảng `update`/`tenant` của người giữ `update` ở
   bất kỳ mức nào trong `own`, `workspace`, `tenant` (mức `team`, `workspace_subtree` không cho gì ở W1, như ticket 02),
   vì `public_read_write` bao `public_read` (gate (c)); không bao giờ vào `delete` hay `assign`. Trigger AFTER UPDATE OF
   `default_access` trên `studio.object_defs`, `WHEN (OLD.default_access IS DISTINCT FROM NEW.default_access)`, vì móc
   phát hành luôn đặt cột này, gọi `studio.bump_access_epoch()` (lượt xác nhận (n)). Oracle Python và test
   vi sai của ticket 02 thêm nhánh này, với `default_access` ngẫu nhiên.
3. `studio.acl_actor_kind()` (`LANGUAGE sql STABLE`, SECURITY INVOKER, `search_path` cố định): trả `user`, `agent` hay
   `workflow` theo `app.actor_kind`, chuỗi rỗng với giá trị khác hay khi thiếu.
4. Module mẫu policy, chủ duy nhất của văn bản policy, trong gói `dw_studio`: dựng `tenant_isolation_records`
   (RESTRICTIVE FOR ALL, USING và WITH CHECK `tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)`)
   và `record_access_records_select`, `_insert`, `_update`, `_delete` (PERMISSIVE, mỗi policy là
   `tenant AND (scope OR (actor_ok AND reach))`). Module xuất `reach_sql(<lệnh>)` cho `select`, `insert`, `update`,
   `delete`, `assign`, và `soft_delete` (`reach(update) AND reach(delete)`, điều kiện xóa mềm mà `permissions.delete` của
   RecordService đọc; người giữ `delete` mà không giữ tầm `update` không xóa mềm được, lượt xác nhận (o)), mà policy, RecordService (`permissions`, custom-objects/03) và hàm giao (ticket 05) cùng dùng, không
   bản thứ hai (gate (l)):
    - `select`, `update`, `delete`, `assign`: object trong `studio.acl_objects(<lệnh>, 'tenant')`, `access_key` trong
      `studio.acl_keys(<lệnh>)`, hoặc `owner_id = studio.acl_user()` với object trong `studio.acl_objects(<lệnh>, 'own')`;
    - `insert`: object trong `studio.acl_objects('create', 'tenant')`, `access_key` trong `studio.acl_keys('create')`,
      hoặc `owner_id = studio.acl_user()` với `access_key` trong `studio.acl_create_own_keys()` (tầm tạo theo từng object,
      ticket 02 bước 5);
    - xóa mềm là một câu UPDATE (custom-objects:R5.5), nên WITH CHECK của `record_access_records_update` là
      `tenant AND (scope OR (actor_ok AND reach(update) AND (deleted_at IS NULL OR reach(delete))))`: dòng mới có
      `deleted_at` khác NULL phải nằm trong tầm `delete`; USING giữ `reach(update)` (gate (b), CRITICAL; spec R2.7).
      `actor_ok` ở ticket này là `studio.acl_actor_kind() = 'user'`. Mọi setting và mảng đọc ở dạng `(SELECT f())::uuid[]`.
      Revision không import gói (quy ước của các revision, `16357d3dbff8...py`): nó chép văn bản mà module dựng lúc viết
      revision; test catalog của bước 7 so văn bản trong catalog với văn bản module dựng, lệch là đỏ, nên đổi module sau
      này buộc một revision mới. `tenant_isolation_records` đã có trên bảng cha và mọi partition với đúng văn bản đó: giữ,
      không dựng lại (gate (h)).
5. Cửa API Studio: `TenantScope` không thêm trường nào; `bind_actor(session, kind)` trong `tenant_session.py` là chỗ duy
   nhất đặt `app.actor_kind`, bằng `set_config(..., true)`; ticket này chỉ cho kind `user`, ticket 04 mở rộng nó với
   `agent`, `workflow`, `app.boundary_id`, `app.run_mode`. Helper phiên của route Studio trong `dw_studio`, cửa duy
   nhất gọi `bind_actor(session, 'user')`, gắn rồi gọi `SELECT studio.ensure_principal_scope()` trước câu lệnh đầu tiên
   của mỗi giao dịch của một yêu cầu đã xác thực; `TenantScope.from_access_context` không gắn loại actor, nên mọi đường
   khác (phiên của lượt chạy, ngữ cảnh hỗ trợ, adapter của `dw_platform`) đọc 0 bản ghi tới khi ticket 04 gắn chúng.
   Test kiến trúc: `bind_actor` với `user` chỉ từ module helper đó; một `set_config('app.actor_kind'` ngoài
   `bind_actor` → đỏ (gate (e)). Phép quét đọc `packages/`, `apps/`, `db/migrations/` và `scripts/`, trừ danh sách cho
   phép có lý do từng dòng: `scripts/bench_records_storage/` (database đo riêng, không phải ứng dụng) và helper test
   `dw_studio.testing` mà test của ticket gọi để gắn `user` (lượt xác nhận (p)).
6. Phạm vi toàn tenant: `tenant_wide_scope(session, tenant_id, lane, registry)` trong
   `packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_session.py` là chỗ duy nhất đặt
   `app.workspace_scope`, bằng `set_config('app.workspace_scope', 'tenant', true)`; `registry` là một
   `TenantWideScopeRegistry` đóng băng, dựng một lần ở composition root của worker (`apps/worker/src/dw_worker/main.py`),
   mỗi mục `{lane, reason, reads_private_tables}`, W1 có `offboarding`, tiêm qua constructor vào `SqlTenantOffboarding`
   (không biến toàn cục); hàm từ chối lane không có trong `registry` trước khi đặt gì. Tiến trình API không dựng
   `registry`. `SqlTenantOffboarding` dùng helper thay cho `_SET_TENANT_ALL_WORKSPACES`. Test kiến trúc: hàm dựng
   `TenantWideScopeRegistry(` chỉ ở composition root của worker và trong test (gate (f)). Test quét mã nguồn, SQL trong
   chuỗi và migration bắt mọi dạng đặt setting này ngoài helper: `set_config('app.workspace_scope'`, `SET` và
   `SET LOCAL app.workspace_scope`, `ALTER ROLE ... SET app.workspace_scope`, `ALTER DATABASE ... SET`, và
   `options`/`PGOPTIONS` trong DSN; danh sách cho phép ghi lý do từng dòng như `_PRINCIPAL_ONLY_ON_PURPOSE`. Mỗi mục của
   `registry` thiếu lý do hay thiếu `reads_private_tables` → lỗi lúc dựng (DO-13.1, ADR-0105 (Accepted) mục 5). Giao
   dịch kế tiếp trên cùng kết nối sau một giao dịch qua `tenant_wide_scope` thấy `app.workspace_scope` rỗng (gate (g)).
7. `packages/python/dw_platform/tests/integration/test_rls_coverage.py`: tập policy và văn bản đúng mẫu trên mọi bảng
   có cột `access_key` và mọi partition của nó, đọc từ `pg_inherits`; mọi hàm mà policy bản ghi phụ thuộc (tìm qua
   `pg_depend`) là STABLE, SECURITY INVOKER, `search_path` cố định; `_TRUSTED_SETTINGS` và
   `scope_outside_a_tenant_clause` biết setting mới và các hàm `studio.acl_*`; quy tắc "bảng thu hẹp phải đọc phạm vi"
   phủ cả bảng thu hẹp theo `app.user_id` hay theo một hàm `studio trong schema `studio`; bảng của `platform` giữ quy tắc hiện có (lượt xác nhận (q)).acl_*`. Sau migration, test đọc lại một dòng qua từng
   policy để policy tạo hỏng không qua được vì trả 0. Bảng thử mang từng hình sai (thêm một PERMISSIVE chỉ theo tenant,
   `tenant_isolation_<t>` thành PERMISSIVE, một `studio.acl_*` VOLATILE hay SECURITY DEFINER), dựng và lùi như
   `test_rls_coverage.py:450-496`, phải bị test bắt; dưới `dw_app`, `tenant_wide_scope` cho tenant A đọc đủ bản ghi của A
   và 0 bản ghi của B (DO-13.2).
8. (Bỏ 23/10/2026) Route `PATCH /api/v1/studio/objects/{api_name}/access` và khóa `studio.sharing.manage` không làm:
   mặc định truy cập chỉ đổi qua phát hành `dw.object/v1` của custom-objects (`A:custom-objects:R1.4~record-access:R2.5`).
9. Test hình kế hoạch trong CI ở 10^5 bản ghi, chạy `EXPLAIN` với lựa chọn tự do của planner (không qua `bind` của
   `tests/support/plan_shape.py`, vốn tắt seqscan và làm phép đột biến không đỏ được; lượt xác nhận (r)), trên câu trang
   chuẩn mà custom-objects/04 sẽ sinh (lọc `tenant_id`, `object_id`, `deleted_at IS NULL`, sắp `created_at DESC, id DESC`,
   `LIMIT 50`), viết trong test vì trình biên dịch chưa có, với các hồ sơ Của tôi, Workspace của tôi, Toàn công ty và
   `public_read`: không Seq Scan trên `studio.records` hay partition; custom-objects/04 chạy lại cùng bốn hồ sơ trên câu
   trình biên dịch sinh (custom-objects:R8.9). Test khẳng định "không Seq Scan", không khẳng định chỉ mục nào được chọn:
   lợi ích của chỉ mục `access_key` là việc của lần đo D12 (ticket 06), vì ở 10^5 planner có thể chọn chỉ mục theo
   object (gate (i)).
10. CLAUDE.md mục Tenancy đã ghi hình policy thứ hai cho bảng bản ghi và người được đặt `app.workspace_scope`
    (DO-13.1, DO-13.2, 23/10/2026); test của bước 6 và bước 7 là phần kiểm của hai câu đó.

## Tiêu chí chấp nhận

- [ ] R1.2 (RA1): INSERT với `owner_id` là người của tenant B, hay một thành viên bị tạm khóa, hay `owner_kind = 'team'`
      → 23514 `ck_records_owner_in_tenant`; cùng ca qua một hàm SECURITY DEFINER thử → 23514; gỡ trigger → test đỏ.
- [ ] R1.3 (RA2): `dw_app` UPDATE thẳng `owner_id`, `owner_kind`, `workspace_id`, `object_id` hay `access_key` →
      permission denied; cấp lại UPDATE trên cột đó → test đỏ.
- [ ] R2.2 (RA4): object `private`: người giữ `read` mức Của tôi đọc bản ghi của người khác → 0 dòng; đổi sang
      `public_read` → 1 dòng, UPDATE → 0 dòng; bỏ nhánh mặc định khỏi hàm tính → test đỏ.
- [ ] R2.3 (RA4): `public_read_write`: người giữ `read` và `update` mức Của tôi UPDATE theo id bản ghi của người khác →
      1 dòng; người chỉ giữ `read` đọc được nó; bỏ `public_read_write` khỏi mảng `read`/`tenant` → ca UPDATE trả 0, test
      đỏ.
- [ ] R2.4 (RA4): `public_read_write`: người giữ `update` mức Của tôi DELETE bản ghi của người khác → 0 dòng bị ảnh
      hưởng, bản ghi còn nguyên.
- [ ] R2.7 (RA4): `public_read_write`: cùng người UPDATE `deleted_at = now()` (xóa mềm) bản ghi đó → WITH CHECK
      từ chối 42501, `deleted_at` vẫn NULL; DELETE thật → 0 dòng; người giữ `update` mức Workspace và `delete` mức Của tôi
      xóa mềm bản ghi của đồng nghiệp cùng workspace → 42501; người có tầm `delete` → được; gỡ nhánh `delete` khỏi WITH
      CHECK của `_update` → ca đầu thành công, test đỏ.
- [ ] R3.1 (RA5): vai trò `read` mức Của tôi: SELECT bản ghi của đồng nghiệp cùng workspace → 0 dòng, bản ghi của mình
      → 1 dòng; UPDATE và xóa mềm theo cùng mức cho cùng kết quả.
- [ ] R3.2 (RA6): mức Workspace của tôi được gán ở Marketing: bản ghi của Marketing → thấy, bản ghi của Sales → 0 dòng.
- [ ] R3.3 (RA6): mức Toàn công ty: thấy bản ghi của cả Marketing và Sales.
- [ ] R3.4 (RA6): người có hai lần gán (Của tôi ở Sales, Workspace ở Marketing) thấy hợp hai tầm; đổi workspace đang
      làm việc giữa hai yêu cầu → cùng tập bản ghi.
- [ ] R3.5 (RA7): INSERT với workspace sở hữu ngoài tầm `create`, với người phụ trách khác mình ở mức Của tôi, hay với
      cặp (Lead, Sales) khi `create` mức Của tôi của người gọi neo ở Marketing cho Lead và ở Sales cho Campaign → 42501,
      0 dòng mới.
- [ ] R4.1 (RA8): thêm một policy PERMISSIVE trên `studio.records` → test catalog đỏ; sửa văn bản lệch mẫu → đỏ; một
      hàm `studio.acl_*` mất STABLE hay `search_path` cố định → đỏ; đọc lại một dòng qua từng policy sau migration; ba
      bảng thử mang hình sai (PERMISSIVE chỉ theo tenant, `tenant_isolation_<t>` thành PERMISSIVE, `studio.acl_*`
      VOLATILE hay SECURITY DEFINER) → mỗi bảng bị test catalog bắt; đổi `reach_sql` của module mà không có revision mới
      → test so văn bản đỏ.
- [ ] R4.2 (RA9): `dw_app` gắn tenant A: SELECT theo id bản ghi của B → 0 dòng; INSERT với `tenant_id` của B → lỗi
      WITH CHECK; bỏ mệnh đề tenant khỏi policy RESTRICTIVE → test đỏ.
- [ ] R4.3 (RA10): `dw_app` SELECT hay INSERT trên mọi partition đọc từ `pg_inherits` theo tên → permission denied; cấp
      lại SELECT trên một partition → test đỏ.
- [ ] R4.4 (RA11): chủ thể chỉ có `platform_admin`, không lần gán nào → 0 bản ghi; chủ thể là `support_staff`, không là
      thành viên công ty → 0 bản ghi, không lỗi (ticket 02 bước 4).
- [ ] R4.5 (RA11): `has_table_privilege('dw_provisioner', 'studio.records', 'SELECT')` → false, cũng vậy với
      `studio.principal_scopes` và `studio.access_epochs`.
- [ ] R4.6 (RA9): kết nối `dw_app` không gắn `app.tenant_id` → 0 dòng.
- [ ] R5.2 (RA13): đổi `default_access` từ `public_read` về `private` ở giao dịch A → câu lệnh đầu của giao dịch B
      của người chỉ với tới qua mặc định → 0 dòng; gỡ trigger trên `studio.object_defs` → test đỏ.
- [ ] R6.1 (RA17): gắn tenant và chủ thể đúng, không gắn `app.actor_kind` → 0 dòng và INSERT bị từ chối;
      `app.actor_kind = 'admin'` → 0 dòng; giao dịch qua `tenant_wide_scope` không gắn loại actor → thấy mọi bản ghi của
      tenant (R7.1).
- [ ] R6.2: phiên Studio mở từ một yêu cầu đã xác thực có `app.actor_kind = 'user'`, `app.user_id` là người
      gọi và dòng sổ tầm `valid` trước câu lệnh đầu tiên; bỏ lời gọi cửa sổ tầm → yêu cầu đọc 0 bản ghi và test đỏ; một
      `TenantScope.from_access_context` của lượt chạy agent, không qua helper Studio → 0 bản ghi; thêm
      `bind_actor(session, 'user')` vào một module ngoài helper → test kiến trúc đỏ.
- [ ] R7.1 (RA22): giao dịch qua `tenant_wide_scope` cho tenant A đọc mọi bản ghi của A, kể cả bản ghi chủ thể không
      với tới, và 0 bản ghi của B; giao dịch kế tiếp trên cùng kết nối, gắn tenant B qua cửa API → `app.workspace_scope`
      rỗng, chỉ bản ghi trong tầm; đặt setting bằng `set_config(..., false)` trong helper → test đỏ.
- [ ] R7.2 (RA22): lane không có trong `registry` → lỗi, `app.workspace_scope` không đổi; thêm một
      `set_config('app.workspace_scope', ...)`, một `SET LOCAL app.workspace_scope` hay một `ALTER ROLE ... SET` ngoài
      helper → test quét mã đỏ; một mục `registry` thiếu lý do hay thiếu `reads_private_tables` → lỗi lúc dựng; dựng
      `TenantWideScopeRegistry` trong một module ngoài composition root của worker → test kiến trúc đỏ.
- [ ] R7.3 (RA23): tenant có bản ghi của ba người phụ trách, một người đã rời tenant, trên các partition hash → bản
      xuất có mỗi bản ghi đúng một lần; sau purge còn 0 bản ghi của tenant.
- [ ] G1 (RA23): `test_export_rows_returns_only_this_tenants_data` và
      `test_purge_rows_respects_fk_order_and_leaves_the_other_tenant_alone` xanh với helper mới; bản ghi của tenant
      khác không đổi.
- [ ] R9.10: test hình kế hoạch ở 10^5 bản ghi không có Seq Scan với mọi hồ sơ; xóa mọi chỉ mục của
      `studio.records` dẫn bằng `(tenant_id, object_id)` và chỉ mục `access_key` → test đỏ.
- [ ] Xong: `make ci test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_session.py:23-27`; spec: R6.2.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/uow.py:58`; spec: R6.2.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:51-54`; spec: R7.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:68-86`; spec: R7.3, G1.
- `packages/python/dw_platform/tests/integration/test_rls_coverage.py:95-99`; spec: R4.1.
- `packages/python/dw_platform/tests/integration/test_rls_coverage.py:395-424`; spec: R4.1, R7.1.
- `packages/python/dw_platform/tests/integration/test_offboarding.py:190`; spec: G1.
- `db/migrations/sql/0013_partition_maintenance.sql:63-83`; spec: R4.3.
- `packages/python/dw_platform/tests/integration/test_rls_coverage.py:450-496`; spec: R4.1 (bảng thử dựng rồi lùi).
- `docs/adr/0105-record-reach-is-decided-by-postgresql.md:46-68`; spec: R2, R3, R4.
- `docs/adr/0105-record-reach-is-decided-by-postgresql.md:85-92`; spec: R7.

## Comments

- 2026-10-23 (agent): needs-info chờ DO-13 (Đạt): lane Studio dùng lại `app.workspace_scope` qua helper có danh sách
  đăng ký (sửa CLAUDE.md 174-175), dịch vụ ngôn ngữ khác chỉ đọc giá trị bản ghi qua API, nhân viên hỗ trợ không đọc
  bản ghi Studio ở v1. Câu hỏi D11 cho route mặc định truy cập là Q3 của spec.
- 2026-10-23 (agent): DO-13.1, DO-13.2, DO-13.3 và `A:custom-objects:R1.4~record-access:R2.5` đã có lời đáp (Đạt,
  23/10/2026); Status về needs-triage. Bỏ R1.1, R2.1, R2.5, R2.6, RA3 khỏi ticket: cột `owner_kind`, `default_access`
  thuộc custom-objects/02, route `PATCH .../access` không làm.
- 2026-10-24 (agent): thêm foundations-hardening/07 vào Blocked by (Đạt, 24/10/2026): bước 6 chuyển
  `SqlTenantOffboarding` sang `tenant_wide_scope` trong `offboarding.py`, tệp mà ticket đó viết lại phần đọc catalog và
  `export_rows`. Lane offboarding audit đứng tên người vận hành đã yêu cầu, `details.lane` là `offboarding` (Quyết định
  24/10/2026 của spec); helper của bước 6 không đổi vì nó không ghi audit.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): theo gate của ticket 01, lần đo D12 tách thành ticket 06
  (`ready-for-human`, Chờ Đạt 23). Mẫu policy chỉ khóa ở D12 (ADR-0105 (Accepted) Consequences), nên ticket này không lên
  `ready-for-agent` khi ticket 06 chưa `resolved`; Blocked by chỉ trỏ ngược nên điều đó ghi ở đây. Nếu sai thì: ticket
  này khóa mẫu theo số smoke của ticket 01 và ticket 06 thành "Kiểm lại khi" của nó.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk, hai subagent, vì ticket thêm
  migration), đọc cùng `16357d3dbff8` và `RESULTS.md`: 1 CRITICAL, 11 HIGH, sửa theo khuyến nghị (Quyết định 4/11/2026
  của spec): (b) CRITICAL, xóa mềm qua WITH CHECK tầm `delete` (spec R2.7 mới); (a) dựng tạm theo P0, không chờ ticket
  06, thay dòng Comments 3/11/2026; (c) `public_read_write` bao `public_read`; (e) `bind_actor` một chỗ gắn loại actor;
  (f) sổ phạm vi toàn tenant tiêm từ worker; (g) setting một giao dịch, test quét mọi dạng; (h) revision chép văn bản
  module; (i) R9.10 không Seq Scan; (k) quyền cột đã có; (l) `reach_sql` dùng chung; R6.1 ngoài phạm vi toàn tenant.
- 2026-11-04 (agent): MEDIUM để lại: (M1) INSERT ở mức Workspace của tôi hay Toàn công ty với người phụ trách khác mình
  được policy nhận (RecordService luôn đặt người gọi, custom-objects:R5.1); (M2) partition mới do custom-objects/07 tạo
  nhận policy qua ticket 07 của cả hai khu vực, test catalog đọc `pg_inherits`; (M3) người giữ `delete` mà không giữ tầm
  `update` không xóa mềm được, theo ý của `soft_delete`.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận: 0 CRITICAL, 6 HIGH, sửa: (m) trigger người phụ trách không thành chỗ dò chéo tenant;
  (n) trigger `default_access` có `WHEN ... IS DISTINCT FROM`; (o) `reach_sql('soft_delete')`; (p) phạm vi và danh sách
  cho phép của phép quét; (q) quy tắc "bảng thu hẹp phải đọc phạm vi" chỉ mở cho schema `studio`; (r) R9.10 với lựa
  chọn tự do của planner. Sửa luôn: nhánh mặc định chỉ ở ba mức của W1; cột `access_key` qua `studio.access_key()`. Sửa
  của lượt này không có người đọc mới: nhận rủi ro (agent, theo ủy quyền 31/10/2026). Nếu sai thì: ghi ở đây khi dựng. Thứ tự dựng: sau 02,
  custom-objects/02 (đã xong), foundations-hardening/03, /07 (đã xong); trước 04, 05, 07, custom-objects/03.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
