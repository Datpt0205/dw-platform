# 02 — Sổ tầm truy cập trong PostgreSQL: tính, lưu, đọc, vô hiệu hóa đồng bộ

Status: needs-triage
Blocked by: 01, .claude/plans/studio/tenant-rbac/issues/04-quyen-doi-tuong-va-truong-co-do-sau.md, .claude/plans/studio/org-and-principals/issues/02-thanh-vien-cap-tenant.md
Area: studio
Yêu cầu: R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.7, RA12, RA13, RA14, RA15, RA16

## Mục tiêu

Mỗi chủ thể có một dòng sổ tầm do đúng một hàm SQL tính từ quyền hiệu lực, đọc qua các hàm `studio.acl_*` mà policy
bản ghi của ticket 03 sẽ dùng, và mất hiệu lực trong cùng giao dịch với mọi thay đổi đầu vào, nên một thu hồi có tác
dụng từ câu lệnh kế tiếp (spec R5, ADR-0105 (Accepted) mục 4). Nhánh nhóm, cây workspace và quản lý thêm ở W2.

## Việc cần làm

1. Migration Alembic (id là hex ngẫu nhiên của alembic) trong schema `studio` của studio-skeleton:
    - `studio.access_epochs`: `tenant_id uuid` PK, FK `platform.tenants` `ON DELETE CASCADE`,
      `epoch bigint NOT NULL DEFAULT 0`, `changed_at timestamptz NOT NULL DEFAULT now()`.
    - `studio.principal_scopes`: `tenant_id`, `principal_id` (PK `(tenant_id, principal_id)`, FK ghép tới
      `platform.tenant_members (tenant_id, user_id)` `ON DELETE CASCADE`), `epoch bigint NOT NULL`,
      `version bigint NOT NULL`, `state text NOT NULL` với `ck_principal_scopes_state` (`valid`, `stale`),
      `computed_at timestamptz NOT NULL`, `workspace_ids uuid[] NOT NULL`, và một `uuid[] NOT NULL DEFAULT '{}'` cho
      mỗi cặp hành động (`read`, `create`, `update`, `delete`, `assign`) và nhánh (`own`: object được làm ở mức Của
      tôi; `keys`: `access_key` của cặp object và workspace được gán vai trò; `tenant`: object ở mức Toàn công ty).
    - RLS ENABLE và FORCE; một policy `tenant_isolation_access_epochs` theo tenant; một policy
      `tenant_isolation_principal_scopes` với `tenant AND (principal_id = app.user_id OR app.workspace_scope = 'tenant')`,
      setting đọc ở dạng `(SELECT ...)`.
    - `dw_app` chỉ SELECT trên hai bảng; `dw_provisioner` và `dw_agent_ro` không quyền nào; khẳng định trong
      `packages/python/dw_platform/tests/integration/test_privileges.py`.
    - Hai bảng không có `workspace_id`: mỗi bảng một dòng trong danh sách bảng toàn tenant của
      `packages/python/dw_platform/tests/integration/test_rls_coverage.py` với lý do "sổ tầm dẫn xuất của một chủ thể và
      epoch của cả tenant" (DO-01).
    - Hai bảng vào `STUDIO_EXCLUSIONS` của test phủ offboarding (studio-skeleton/01), mỗi bảng một lý do
      (`B:record-access:R5.5~studio-skeleton:R4.1`, `B:foundations-hardening:R3.2~record-access:dữ-liệu`):
      `studio.principal_scopes` "dữ liệu dẫn xuất, không xóa bằng `dw_app`; đi theo cascade khi offboarding xóa
      `platform.tenant_members`"; `studio.access_epochs` "một dòng đếm mỗi tenant giữ có chủ ý, không mang dữ liệu của
      tenant; dòng `platform.tenants` của tenant đã offboard còn ở `offboarded` nên dòng đếm còn theo".
2. View đầu vào là hợp đồng với tenant-rbac và org-and-principals: `studio.v_principal_grants` (dòng của
   `platform.effective_grants` cho tenant và chủ thể lấy từ setting, khóa `obj.<api_name>.<action>` đổi ra `object_id`
   qua `studio.object_defs`) và `studio.v_principal_workspaces` (workspace mà chủ thể là thành viên, chỉ khi thành viên
   công ty ở trạng thái `active`).
3. `studio.compute_principal_scope()`: `LANGUAGE sql STABLE`, không tham số, tenant từ `app.tenant_id` và chủ thể từ
   `app.user_id`, lọc `tenant_id` tường minh ở mọi truy vấn con; tính các mức `own`, `workspace`, `tenant` mà
   ADR-0104 (Accepted) giao cho W1; mức khác không cho tầm nào ở W1.
4. `studio.ensure_principal_scope()`: SECURITY DEFINER thuộc `dw_migrator`, không tham số, `search_path` cố định,
   EXECUTE thu khỏi PUBLIC và cấp cho `dw_app`; tạo dòng epoch của tenant khi thiếu (`ON CONFLICT DO NOTHING`); khi
   dòng của chủ thể thiếu, `stale` hay khác epoch thì tính lại và upsert có compare-and-set theo `version` và `epoch`
   đã đọc lúc bắt đầu, nên một lần tính bắt đầu trước thu hồi không bao giờ ghi được dòng `valid`.
5. Hàm đọc `studio.acl_user()`, `studio.acl_workspaces(action text)`, `studio.acl_objects(action text, arm text)`,
   `studio.acl_keys(action text)`: `LANGUAGE sql STABLE`, SECURITY INVOKER, `search_path` cố định; chỉ đọc dòng của
   chủ thể đang gắn với `state = 'valid'` và epoch bằng epoch của tenant; trả `'{}'` khi thiếu bất cứ gì.
6. Trigger AFTER INSERT, UPDATE, DELETE cùng giao dịch, qua hai hàm SECURITY DEFINER không nhận tên bảng từ người gọi:
   `studio.mark_principal_stale()` cho thay đổi của một chủ thể (trạng thái thành viên công ty, thành viên workspace,
   gán vai trò của người đó: `state = 'stale'`, `version + 1`) và `studio.bump_access_epoch()` cho thay đổi cấu trúc
   (quyền trong vai trò, xóa vai trò, lưu trữ hay xóa workspace: `epoch + 1`). Gắn trên mọi bảng đang mang trigger của
   `platform.bump_access_version()` (ADR-0104 (Accepted) mục 7).
7. Test catalog: mọi bảng mang trigger của `platform.bump_access_version()` cũng mang một trigger sổ tầm; một bảng
   thiếu thì test nêu tên bảng.
8. Oracle Python chỉ dùng trong test, trong gói `testing` của `dw_studio`: sinh tổ chức ngẫu nhiên (người, workspace,
   vai trò, mức truy cập, gán vai trò) và tính tầm bằng Python cho test vi sai.

## Tiêu chí chấp nhận

- [ ] R5.1 (RA12): test vi sai trên ≥ 500 tổ chức ngẫu nhiên: mọi `studio.acl_*` khớp oracle ở mọi hành động và
      nhánh; hai tenant có cấu trúc giống hệt không lẫn id của nhau; bỏ lọc tenant trong
      `studio.compute_principal_scope()` → test hai tenant đỏ.
- [ ] R5.2 (RA13): với mỗi loại thay đổi (gỡ và tạm khóa thành viên công ty, gỡ thành viên workspace, gỡ lần gán vai
      trò, hạ mức truy cập trong vai trò) commit ở giao dịch A, lần gọi cửa sổ tầm đầu tiên của giao dịch B trả tầm
      mới; gỡ trigger trên một bảng → test của loại đó và test catalog đỏ.
- [ ] R5.3 (RA14): không có dòng, dòng `stale` hay epoch cũ → mọi `studio.acl_*` trả `'{}'`; trả tầm của dòng cũ thay
      vì mảng rỗng → test đỏ.
- [ ] R5.4 (RA15): hai kết nối đan xen: lần tính bắt đầu, thu hồi commit, lần tính ghi → dòng khác `valid`; bỏ
      compare-and-set → test đỏ.
- [ ] R5.5 (RA16): `dw_app` INSERT, UPDATE, DELETE trên `studio.principal_scopes` và `studio.access_epochs` →
      permission denied; `test_privileges.py` khẳng định chỉ có SELECT.
- [ ] R5.6: xóa thành viên công ty của một chủ thể → dòng sổ tầm của người đó biến mất trong cùng giao dịch; thành viên
      bị tạm khóa → dòng thành `stale` và tầm tính lại rỗng; offboarding một tenant → 0 dòng `studio.principal_scopes`
      của tenant đó và đúng một dòng `studio.access_epochs` của nó còn lại, và test phủ offboarding xanh với hai bảng
      trong `STUDIO_EXCLUSIONS` kèm đúng lý do của mỗi bảng; bỏ một bảng khỏi danh sách → test đỏ.
- [ ] R5.7 (RA12): `app.tenant_id` của tenant A, `app.user_id` của người chỉ là thành viên công ty B, gọi
      `studio.ensure_principal_scope()` → lỗi khóa ngoại 23503 trên FK ghép, không dòng `studio.principal_scopes` nào;
      migration thử đổi FK ghép thành FK một cột `principal_id` tới `platform.users` → test đỏ.
- [ ] Xong: `make ci test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/caching_lookup.py:27`; spec: R5.2.
- `db/migrations/sql/0012_partition_maintenance.sql:45-48`; spec: R5.5.
- `docs/adr/0105-record-reach-is-decided-by-postgresql.md:77-84`; spec: R5.1, R5.3, R5.4.
- `docs/adr/0104-tenant-roles-with-depth-and-one-effective-grants-owner.md:70-80`; spec: R5.1.
- `docs/adr/0104-tenant-roles-with-depth-and-one-effective-grants-owner.md:94-101`; spec: R5.2.

## Comments

- 2026-10-23 (agent): DO-14 đã quyết bằng D12 (người yêu cầu, 23/10/2026); DO-11 theo khuyến nghị (a), tạm: mặc định
  công khai là toàn tenant (nhánh của nó thêm ở ticket 03).
- 2026-10-23 (agent): DO-11 (a) đã được Đạt xác nhận ngày 23/10/2026; thêm dòng lớp bảng toàn tenant (DO-01) và
  `STUDIO_EXCLUSIONS` cho hai bảng sổ tầm.
- 2026-10-24 (agent): lý do loại trừ của `studio.access_epochs` sửa thành dòng đếm giữ có chủ ý (Đạt, 24/10/2026):
  offboarding giữ dòng `platform.tenants` ở `offboarded`, nên không cascade nào xóa dòng epoch của tenant đó.
- 2026-10-24 (agent): vòng sửa 4, lượt bốn: tiêu chí R5.7 dưới RA12 là ca âm chéo tenant của FK ghép
  `(tenant_id, principal_id)` mà bước 1 tạo: sổ tầm của tenant A cho người chỉ là thành viên công ty B bị từ chối
  (Quyết định 24/10/2026 của spec).
