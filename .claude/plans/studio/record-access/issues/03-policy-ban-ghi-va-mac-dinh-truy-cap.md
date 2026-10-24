# 03 — Cột truy cập, bộ policy trên bảng bản ghi, mặc định truy cập theo object và phạm vi toàn tenant cho lane

Status: needs-triage
Blocked by: 02, .claude/plans/studio/custom-objects/issues/02-luoc-do-dinh-nghia-object.md, .claude/plans/studio/foundations-hardening/issues/03-quyen-dw-app-va-rls-initplan.md, .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md
Area: studio
Yêu cầu: G1, R1.2, R1.3, R2.2, R2.3, R2.4, R3.1, R3.2, R3.3, R3.4, R3.5, R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, R5.2, R6.1, R6.2, R7.1, R7.2, R7.3, R9.10, RA1, RA2, RA4, RA5, RA6, RA7, RA8, RA9, RA10, RA11, RA13, RA17, RA22, RA23

## Mục tiêu

PostgreSQL quyết định ai thấy bản ghi nào cho mọi đường: bảng `studio.records` mang cột truy cập và đúng một bộ
policy RESTRICTIVE tenant cộng PERMISSIVE theo lệnh đọc sổ tầm của ticket 02; mặc định truy cập của object (cột của
custom-objects/02) vào sổ tầm; cửa API gắn loại actor `user`; offboarding và lane đã đăng ký đọc mọi bản ghi của một
tenant qua một helper duy nhất (spec R1 tới R4, R7, R9.10; ADR-0105 (Accepted) mục 1, 2 và 5).

## Việc cần làm

1. Migration trên `studio.records` của custom-objects ticket 02, áp cho bảng cha và mọi partition (tám, `studio.records_p0`
   tới `studio.records_p7`, hay bốn theo đường lui modulus 4 của `custom-objects:R9.5`); `owner_kind` với CHECK `user`,
   `team` và NOT NULL đã có từ custom-objects/02, ticket này không thêm lại:
    - cột sinh STORED `access_key` theo biến thể ticket 01 chọn (`uuid` từ
      `md5(object_id::text || '/' || workspace_id::text)` hay `bigint`);
    - index `(tenant_id, access_key, created_at DESC, id DESC)` và `(tenant_id, owner_id, object_id, created_at DESC, id DESC)`;
    - trigger BEFORE INSERT OR UPDATE OF `owner_id`, `owner_kind` gọi lỗi 23514 `ck_records_owner_in_tenant` khi người
      phụ trách không phải thành viên công ty `active` của tenant đang gắn; `team` bị từ chối cho tới W2;
    - quyền: `REVOKE UPDATE ON studio.records FROM dw_app`, rồi cấp UPDATE trên các cột dữ liệu, trừ `owner_id`,
      `owner_kind`, `workspace_id`, `object_id`; `REVOKE ALL` của `dw_app` trên từng partition; `dw_provisioner` không
      quyền nào trên `studio.records`.
2. `studio.object_defs.default_access` và `ck_object_defs_default_access` do custom-objects/02 tạo; ticket này chỉ đọc
   (`A:custom-objects:R1.4~record-access:R2.5`). Thêm nhánh mặc định vào `studio.compute_principal_scope()` của
   ticket 02: object `public_read` vào mảng `read`/`tenant` của người giữ `read` ở bất kỳ mức nào, object
   `public_read_write` vào mảng `update`/`tenant` của người giữ `update` ở bất kỳ mức nào; không bao giờ vào `delete`
   hay `assign`. Trigger AFTER UPDATE OF `default_access` trên `studio.object_defs` gọi `studio.bump_access_epoch()`.
3. `studio.acl_actor_kind()` (`LANGUAGE sql STABLE`, SECURITY INVOKER, `search_path` cố định): trả `user`, `agent` hay
   `workflow` theo `app.actor_kind`, chuỗi rỗng với giá trị khác.
4. Module mẫu policy, chủ duy nhất của văn bản policy, trong gói `dw_studio`: dựng `tenant_isolation_records`
   (RESTRICTIVE FOR ALL, USING và WITH CHECK `tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)`)
   và `record_access_records_select`, `_insert`, `_update`, `_delete` (PERMISSIVE, mỗi policy là
   `tenant AND (scope OR (actor_ok AND reach))`). `reach` cho lệnh: object trong `studio.acl_objects(<hành động>, 'tenant')`,
   `access_key` trong `studio.acl_keys(<hành động>)`, hoặc `owner_id = studio.acl_user()` với object trong
   `studio.acl_objects(<hành động>, 'own')`; ở INSERT, nhánh `own` còn đòi workspace sở hữu trong
   `studio.acl_workspaces('create')`. `actor_ok` ở ticket này là `studio.acl_actor_kind() = 'user'`. Mọi setting và mảng
   đọc ở dạng `(SELECT f())::uuid[]`. Migration và test cùng dựng văn bản từ module này.
5. Cửa API Studio: `TenantScope` thêm `actor_kind`; `_BIND_SCOPE` của `tenant_session.py` gắn `app.actor_kind`;
   `TenantScope.from_access_context` đặt `user`; helper phiên Studio của `dw_studio` gọi
   `SELECT studio.ensure_principal_scope()` ngay sau khi gắn, trước câu lệnh đầu tiên.
6. Phạm vi toàn tenant: `tenant_wide_scope(session, tenant_id, lane)` trong
   `packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_session.py` là chỗ duy nhất đặt
   `app.workspace_scope`; nó từ chối lane không có trong `frozenset` đăng ký dựng ở composition root
   (`apps/worker/src/dw_worker/main.py`), W1 có `offboarding`; `SqlTenantOffboarding` dùng helper thay cho
   `_SET_TENANT_ALL_WORKSPACES`. Test quét mã nguồn và migration: mọi lệnh đặt `app.workspace_scope` ngoài helper làm
   test đỏ, danh sách cho phép ghi lý do từng dòng như `_PRINCIPAL_ONLY_ON_PURPOSE`. Mỗi dòng của danh sách đăng ký
   mang lý do và nêu lane có cần đọc bảng riêng tư theo chủ (hội thoại, sổ tầm) không, vì lane trong danh sách thấy cả
   các bảng đó (DO-13.1, ADR-0105 (Accepted) mục 5); thiếu một trong hai thì test đỏ.
7. `packages/python/dw_platform/tests/integration/test_rls_coverage.py`: tập policy và văn bản đúng mẫu trên mọi bảng
   có cột `access_key` và mọi partition của nó; mọi hàm mà policy bản ghi phụ thuộc (tìm qua `pg_depend`) là STABLE,
   SECURITY INVOKER, `search_path` cố định; `_TRUSTED_SETTINGS` và `scope_outside_a_tenant_clause` biết setting mới và
   các hàm `studio.acl_*`; quy tắc "bảng thu hẹp phải đọc phạm vi" phủ cả bảng thu hẹp theo `app.user_id` hay theo một
   hàm `studio.acl_*`. Sau migration, test đọc lại một dòng qua từng policy để policy tạo hỏng không qua được vì trả 0.
   Bảng thử mang từng hình sai (thêm một PERMISSIVE chỉ theo tenant, `tenant_isolation_<t>` thành PERMISSIVE, một
   `studio.acl_*` VOLATILE hay SECURITY DEFINER), dựng và lùi như `test_rls_coverage.py:450-496`, phải bị test bắt;
   dưới `dw_app`, `tenant_wide_scope` cho tenant A đọc đủ bản ghi của A và 0 bản ghi của B (DO-13.2).
8. (Bỏ 23/10/2026) Route `PATCH /api/v1/studio/objects/{api_name}/access` và khóa `studio.sharing.manage` không làm:
   mặc định truy cập chỉ đổi qua phát hành `dw.object/v1` của custom-objects (`A:custom-objects:R1.4~record-access:R2.5`).
9. Test hình kế hoạch trong CI ở 10^5 bản ghi: mỗi truy vấn trang của RecordService, chạy với các hồ sơ Của tôi,
   Workspace của tôi, Toàn công ty và `public_read`, không có Seq Scan trên `studio.records` hay partition.
10. CLAUDE.md mục Tenancy đã ghi hình policy thứ hai cho bảng bản ghi và người được đặt `app.workspace_scope`
    (DO-13.1, DO-13.2, 23/10/2026); test của bước 6 và bước 7 là phần kiểm của hai câu đó.

## Tiêu chí chấp nhận

- [ ] R1.2 (RA1): INSERT với `owner_id` là người của tenant B, hay một thành viên bị tạm khóa, hay `owner_kind = 'team'`
      → 23514 `ck_records_owner_in_tenant`; gỡ trigger → test đỏ.
- [ ] R1.3 (RA2): `dw_app` UPDATE thẳng `owner_id` hay `workspace_id` → permission denied; cấp lại UPDATE trên cột đó
      → test đỏ.
- [ ] R2.2 (RA4): object `private`: người giữ `read` mức Của tôi đọc bản ghi của người khác → 0 dòng; đổi sang
      `public_read` → 1 dòng, UPDATE → 0 dòng; bỏ nhánh mặc định khỏi hàm tính → test đỏ.
- [ ] R2.3 (RA4): `public_read_write`: người giữ `update` mức Của tôi UPDATE bản ghi của người khác → 1 dòng.
- [ ] R2.4 (RA4): `public_read_write`: cùng người DELETE bản ghi đó → 0 dòng bị ảnh hưởng, bản ghi còn nguyên.
- [ ] R3.1 (RA5): vai trò `read` mức Của tôi: SELECT bản ghi của đồng nghiệp cùng workspace → 0 dòng, bản ghi của mình
      → 1 dòng; UPDATE và DELETE theo cùng mức cho cùng kết quả.
- [ ] R3.2 (RA6): mức Workspace của tôi được gán ở Marketing: bản ghi của Marketing → thấy, bản ghi của Sales → 0 dòng.
- [ ] R3.3 (RA6): mức Toàn công ty: thấy bản ghi của cả Marketing và Sales.
- [ ] R3.4 (RA6): người có hai lần gán (Của tôi ở Sales, Workspace ở Marketing) thấy hợp hai tầm; đổi workspace đang
      làm việc giữa hai yêu cầu → cùng tập bản ghi.
- [ ] R3.5 (RA7): INSERT với workspace sở hữu ngoài tầm `create`, hay với người phụ trách khác mình ở mức Của tôi →
      42501, 0 dòng mới.
- [ ] R4.1 (RA8): thêm một policy PERMISSIVE trên `studio.records` → test catalog đỏ; sửa văn bản lệch mẫu → đỏ; một
      hàm `studio.acl_*` mất STABLE hay `search_path` cố định → đỏ; đọc lại một dòng qua từng policy sau migration; ba
      bảng thử mang hình sai (PERMISSIVE chỉ theo tenant, `tenant_isolation_<t>` thành PERMISSIVE, `studio.acl_*`
      VOLATILE hay SECURITY DEFINER) → mỗi bảng bị test catalog bắt.
- [ ] R4.2 (RA9): `dw_app` gắn tenant A: SELECT theo id bản ghi của B → 0 dòng; INSERT với `tenant_id` của B → lỗi
      WITH CHECK; bỏ mệnh đề tenant khỏi policy RESTRICTIVE → test đỏ.
- [ ] R4.3 (RA10): `dw_app` SELECT hay INSERT trên `studio.records_p0` theo tên → permission denied; cấp lại SELECT
      trên partition → test đỏ.
- [ ] R4.4 (RA11): chủ thể chỉ có `platform_admin`, không lần gán nào → 0 bản ghi; chủ thể là `support_staff` → 0 bản
      ghi.
- [ ] R4.5 (RA11): `has_table_privilege('dw_provisioner', 'studio.records', 'SELECT')` → false, cũng vậy với
      `studio.principal_scopes` và `studio.access_epochs`.
- [ ] R4.6 (RA9): kết nối `dw_app` không gắn `app.tenant_id` → 0 dòng.
- [ ] R5.2 (RA13): đổi `default_access` từ `public_read` về `private` ở giao dịch A → câu lệnh đầu của giao dịch B
      của người chỉ với tới qua mặc định → 0 dòng; gỡ trigger trên `studio.object_defs` → test đỏ.
- [ ] R6.1 (RA17): gắn tenant và chủ thể đúng, không gắn `app.actor_kind` → 0 dòng và INSERT bị từ chối;
      `app.actor_kind = 'admin'` → 0 dòng.
- [ ] R6.2: phiên Studio mở từ một `AccessContext` có `app.actor_kind = 'user'`, `app.user_id` là người gọi và dòng sổ
      tầm `valid` trước câu lệnh đầu tiên; bỏ lời gọi cửa sổ tầm → yêu cầu đọc 0 bản ghi và test đỏ.
- [ ] R7.1 (RA22): giao dịch qua `tenant_wide_scope` cho tenant A đọc mọi bản ghi của A, kể cả bản ghi chủ thể không
      với tới, và 0 bản ghi của B.
- [ ] R7.2 (RA22): lane không có trong danh sách → lỗi, `app.workspace_scope` không đổi; thêm một
      `set_config('app.workspace_scope', ...)` ngoài helper → test quét mã đỏ; một dòng danh sách thiếu lý do hay thiếu
      ghi lane có đọc bảng riêng tư theo chủ không → test đỏ.
- [ ] R7.3 (RA23): tenant có bản ghi của ba người phụ trách, một người đã rời tenant, trên các partition hash → bản
      xuất có mỗi bản ghi đúng một lần; sau purge còn 0 bản ghi của tenant.
- [ ] G1 (RA23): `test_export_rows_returns_only_this_tenants_data` và
      `test_purge_rows_respects_fk_order_and_leaves_the_other_tenant_alone` xanh với helper mới; bản ghi của tenant
      khác không đổi.
- [ ] R9.10: test hình kế hoạch ở 10^5 bản ghi không có Seq Scan với mọi hồ sơ; xóa index `access_key` → test đỏ.
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
