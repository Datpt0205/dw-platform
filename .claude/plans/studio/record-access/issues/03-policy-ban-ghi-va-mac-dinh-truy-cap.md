# 03 — Cột truy cập, bộ policy trên bảng bản ghi, mặc định truy cập theo object và phạm vi toàn tenant cho lane

Status: needs-info (DO-13)
Blocked by: 02, .claude/plans/studio/custom-objects/issues/02-luoc-do-dinh-nghia-object.md, .claude/plans/studio/foundations-hardening/issues/03-quyen-dw-app-va-rls-initplan.md
Area: studio
Yêu cầu: G1, R1.1, R1.2, R1.3, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R3.1, R3.2, R3.3, R3.4, R3.5, R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, R5.2, R6.1, R6.2, R7.1, R7.2, R7.3, R9.10, RA1, RA2, RA3, RA4, RA5, RA6, RA7, RA8, RA9, RA10, RA11, RA13, RA17, RA22, RA23

## Mục tiêu

PostgreSQL quyết định ai thấy bản ghi nào cho mọi đường: bảng `studio.records` mang cột truy cập và đúng một bộ
policy RESTRICTIVE tenant cộng PERMISSIVE theo lệnh đọc sổ tầm của ticket 02; object có mặc định truy cập; cửa API gắn
loại actor `user`; offboarding và lane đã đăng ký đọc mọi bản ghi của một tenant qua một helper duy nhất (spec R1 tới
R4, R7, R9.10; ADR-0105 (Proposed) mục 1, 2 và 5).

## Việc cần làm

1. Migration trên `studio.records` của custom-objects ticket 02, áp cho bảng cha và tám partition `studio.records_p0`
   tới `studio.records_p7`:
    - thêm `owner_kind text NOT NULL DEFAULT 'user'` với `ck_records_owner_kind` (`user`, `team`); cột sinh STORED
      `access_key` theo biến thể ticket 01 chọn (`uuid` từ `md5(object_id::text || '/' || workspace_id::text)` hay
      `bigint`);
    - index `(tenant_id, access_key, created_at DESC, id DESC)` và `(tenant_id, owner_id, object_id, created_at DESC, id DESC)`;
    - trigger BEFORE INSERT OR UPDATE OF `owner_id`, `owner_kind` gọi lỗi 23514 `ck_records_owner_in_tenant` khi người
      phụ trách không phải thành viên công ty `active` của tenant đang gắn; `team` bị từ chối cho tới W2;
    - quyền: `REVOKE UPDATE ON studio.records FROM dw_app`, rồi cấp UPDATE trên các cột dữ liệu, trừ `owner_id`,
      `owner_kind`, `workspace_id`, `object_id`; `REVOKE ALL` của `dw_app` trên từng partition; `dw_provisioner` không
      quyền nào trên `studio.records`.
2. `studio.object_defs.default_access text NOT NULL DEFAULT 'private'` với `ck_object_defs_default_access`
   (`private`, `public_read`, `public_read_write`). Thêm nhánh mặc định vào `studio.compute_principal_scope()` của
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
   test đỏ, danh sách cho phép ghi lý do từng dòng như `_PRINCIPAL_ONLY_ON_PURPOSE`.
7. `packages/python/dw_platform/tests/integration/test_rls_coverage.py`: tập policy và văn bản đúng mẫu trên mọi bảng
   có cột `access_key` và mọi partition của nó; mọi hàm mà policy bản ghi phụ thuộc (tìm qua `pg_depend`) là STABLE,
   SECURITY INVOKER, `search_path` cố định; `_TRUSTED_SETTINGS` và `scope_outside_a_tenant_clause` biết setting mới và
   các hàm `studio.acl_*`; quy tắc "bảng thu hẹp phải đọc phạm vi" phủ cả bảng thu hẹp theo `app.user_id` hay theo một
   hàm `studio.acl_*`. Sau migration, test đọc lại một dòng qua từng policy để policy tạo hỏng không qua được vì trả 0.
8. Route `PATCH /api/v1/studio/objects/{api_name}/access`: migration thêm khóa `studio.sharing.manage` vào
   `platform.permissions` (mức `tenant`, người đọc là route này); `Idempotency-Key` qua `get_idempotent_operation`;
   thân `{"default_access": "..."}`; ghi giá trị, audit `studio.object.access_changed` (`object_id`, trước, sau, không
   gì khác) và tăng epoch trong một giao dịch; 422 với giá trị lạ; `make generate-contracts`.
9. Test hình kế hoạch trong CI ở 10^5 bản ghi: mỗi truy vấn trang của RecordService, chạy với các hồ sơ Của tôi,
   Workspace của tôi, Toàn công ty và `public_read`, không có Seq Scan trên `studio.records` hay partition.
10. Bản sửa `CLAUDE.md:172-175` (hình policy thứ hai cho bảng bản ghi, người được đặt `app.workspace_scope`) gửi Đạt;
    gộp cùng lúc ADR-0105 (Proposed) được chấp nhận và DO-13 được trả lời.

## Tiêu chí chấp nhận

- [ ] R1.1: test catalog: `owner_id`, `owner_kind`, `workspace_id`, `object_id` là NOT NULL trên bảng cha và tám
      partition; INSERT thiếu `owner_id` → 23502.
- [ ] R1.2 (RA1): INSERT với `owner_id` là người của tenant B, hay một thành viên bị tạm khóa, hay `owner_kind = 'team'`
      → 23514 `ck_records_owner_in_tenant`; gỡ trigger → test đỏ.
- [ ] R1.3 (RA2): `dw_app` UPDATE thẳng `owner_id` hay `workspace_id` → permission denied; cấp lại UPDATE trên cột đó
      → test đỏ.
- [ ] R2.1: object mới có `default_access = 'private'`; `dw_app` ghi `'public'` → 23514 `ck_object_defs_default_access`.
- [ ] R2.2 (RA4): object `private`: người giữ `read` mức Của tôi đọc bản ghi của người khác → 0 dòng; đổi sang
      `public_read` → 1 dòng, UPDATE → 0 dòng; bỏ nhánh mặc định khỏi hàm tính → test đỏ.
- [ ] R2.3 (RA4): `public_read_write`: người giữ `update` mức Của tôi UPDATE bản ghi của người khác → 1 dòng.
- [ ] R2.4 (RA4): `public_read_write`: cùng người DELETE bản ghi đó → 0 dòng bị ảnh hưởng, bản ghi còn nguyên.
- [ ] R2.5 (RA3): `PATCH .../access` hợp lệ → 200, giá trị mới, đúng một audit `studio.object.access_changed`, epoch
      tăng trong cùng giao dịch; lỗi giả lập sau khi ghi audit → giao dịch lùi, 0 audit, giá trị cũ.
- [ ] R2.6 (RA3): người không có `studio.sharing.manage` → 403, `default_access` không đổi, 0 audit; gỡ kiểm quyền →
      test đỏ.
- [ ] R3.1 (RA5): vai trò `read` mức Của tôi: SELECT bản ghi của đồng nghiệp cùng workspace → 0 dòng, bản ghi của mình
      → 1 dòng; UPDATE và DELETE theo cùng mức cho cùng kết quả.
- [ ] R3.2 (RA6): mức Workspace của tôi được gán ở Marketing: bản ghi của Marketing → thấy, bản ghi của Sales → 0 dòng.
- [ ] R3.3 (RA6): mức Toàn công ty: thấy bản ghi của cả Marketing và Sales.
- [ ] R3.4 (RA6): người có hai lần gán (Của tôi ở Sales, Workspace ở Marketing) thấy hợp hai tầm; đổi workspace đang
      làm việc giữa hai yêu cầu → cùng tập bản ghi.
- [ ] R3.5 (RA7): INSERT với workspace sở hữu ngoài tầm `create`, hay với người phụ trách khác mình ở mức Của tôi →
      42501, 0 dòng mới.
- [ ] R4.1 (RA8): thêm một policy PERMISSIVE trên `studio.records` → test catalog đỏ; sửa văn bản lệch mẫu → đỏ; một
      hàm `studio.acl_*` mất STABLE hay `search_path` cố định → đỏ; đọc lại một dòng qua từng policy sau migration.
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
      `set_config('app.workspace_scope', ...)` ngoài helper → test quét mã đỏ.
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
- `apps/api/src/dw_api/dependencies/idempotency.py:217`; spec: R2.5.
- `docs/adr/0105-record-reach-is-decided-by-postgresql.md:46-66`; spec: R2, R3, R4.
- `docs/adr/0105-record-reach-is-decided-by-postgresql.md:83-87`; spec: R7.

## Comments

- 2026-10-23 (agent): needs-info chờ DO-13 (Đạt): lane Studio dùng lại `app.workspace_scope` qua helper có danh sách
  đăng ký (sửa CLAUDE.md 174-175), dịch vụ ngôn ngữ khác chỉ đọc giá trị bản ghi qua API, nhân viên hỗ trợ không đọc
  bản ghi Studio ở v1. Câu hỏi D11 cho route mặc định truy cập là Q3 của spec.
