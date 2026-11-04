# 02 — Sổ tầm truy cập trong PostgreSQL: tính, lưu, đọc, vô hiệu hóa đồng bộ

Status: resolved
Blocked by: 01, .claude/plans/studio/tenant-rbac/issues/04-quyen-doi-tuong-va-truong-co-do-sau.md, .claude/plans/studio/org-and-principals/issues/02-thanh-vien-cap-tenant.md
Area: studio
Yêu cầu: R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.7, RA12, RA13, RA14, RA15, RA16

## Mục tiêu

Mỗi chủ thể có một dòng sổ tầm do đúng một hàm SQL tính từ quyền hiệu lực, đọc qua các hàm `studio.acl_*` mà policy
bản ghi của ticket 03 sẽ dùng, và mất hiệu lực trong cùng giao dịch với mọi thay đổi đầu vào, nên một thu hồi có tác
dụng từ câu lệnh kế tiếp (spec R5, ADR-0105 (Accepted) mục 4). Nhánh nhóm, cây workspace và quản lý thêm ở W2.

## Việc cần làm

0. Hình của sổ tầm là P0, tức ADR-0105 (Accepted) quyết 4 như viết (một dòng mỗi chủ thể, một mảng mỗi cặp hành động
   và nhánh), mốc mà record-access/01 đo ở smoke; dựng tạm như vậy và không chờ lần đo D12 của ticket 06. Một phương án
   thắng khác ở D12 (một dòng mỗi hành động L, khóa `bigint` K, `EXISTS` E) là việc của ticket 07 mới, áp bằng một
   revision sau, như custom-objects/07 làm với DDL bản ghi (gate 4/11/2026 (a); ADR-0105 (Accepted), Amendments
   2026-11-04). Smoke của record-access/01 cho L trang đầu toàn công ty nhanh khoảng 10 lần (`db/bench/record-access/
RESULTS.md`): ticket 06 chọn lại ở D12, ticket này không chọn theo số smoke.
1. Migration Alembic (id là hex ngẫu nhiên của alembic) trong schema `studio` của studio-skeleton:
    - `studio.access_epochs`: `tenant_id uuid` PK, FK `platform.tenants` `ON DELETE CASCADE`,
      `epoch bigint NOT NULL DEFAULT 0`, `changed_at timestamptz NOT NULL DEFAULT now()`.
    - `studio.principal_scopes`: `tenant_id`, `principal_id` (PK `(tenant_id, principal_id)`, FK ghép tới
      `platform.tenant_members (tenant_id, user_id)` `ON DELETE CASCADE`), `epoch bigint NOT NULL`,
      `version bigint NOT NULL`, `state text NOT NULL` với `ck_principal_scopes_state` (`valid`, `stale`),
      `computed_at timestamptz NOT NULL`, `valid_until timestamptz NULL` (`expires_at` sớm nhất của các lần gán vai trò
      đã góp vào dòng; gate (c)), `workspace_ids uuid[] NOT NULL` (workspace mà chủ thể là thành viên), và một
      `uuid[] NOT NULL DEFAULT '{}'` cho mỗi cặp hành động (`read`, `create`, `update`, `delete`, `assign`) và nhánh:
      `own` (object mà chủ thể giữ hành động ở độ sâu Của tôi trở lên, vì độ sâu cộng dồn, ADR-0104 (Accepted) quyết 3,
      nên người giữ `read` mức Workspace ở Marketing vẫn thấy lead mình phụ trách thuộc Sales; gate (d)), `keys`
      (`access_key` của cặp object và workspace neo của lần gán ở độ sâu Workspace của tôi), `tenant` (object ở độ sâu
      Toàn công ty); thêm mảng `create_own_keys`: `access_key` của cặp object và workspace neo của lần gán `create` ở độ
      sâu Của tôi, để lần tạo ở nhánh `own` chỉ nhận workspace neo của đúng object đó (gate (e)).
    - RLS ENABLE và FORCE. `studio.access_epochs`: một policy `tenant_isolation_access_epochs` theo tenant.
      `studio.principal_scopes` là bảng riêng của một người, nên mang đúng hình mà CLAUDE.md mục Tenancy and
      authorization ghi (ADR-0117 (Accepted)): `tenant_isolation_principal_scopes` theo tenant cộng một policy
      RESTRICTIVE `tenant AND (principal_id = app.user_id OR app.workspace_scope = 'tenant')`, setting đọc ở dạng
      `(SELECT ...)`; không policy gộp nào (gate (b), CRITICAL).
    - `dw_app` chỉ SELECT trên hai bảng; `dw_provisioner` và `dw_agent_ro` không quyền nào; khẳng định trong
      `packages/python/dw_platform/tests/integration/test_privileges.py`.
    - Hai bảng không có `workspace_id`: mỗi bảng một dòng trong danh sách bảng toàn tenant của
      `packages/python/dw_platform/tests/integration/test_rls_coverage.py` với lý do "sổ tầm dẫn xuất của một chủ thể và
      epoch của cả tenant" (DO-01).
    - Hai bảng vào `STUDIO_EXCLUSIONS` của test phủ offboarding (studio-skeleton/01), mỗi bảng đúng một cách của
      `OffboardingExclusion` (`offboarding.py:166-187`): `studio.principal_scopes` `cascade_from` `platform.tenant_members`
      ("dữ liệu dẫn xuất, không xóa bằng `dw_app`; đi theo cascade khi offboarding xóa thành viên"); `studio.access_epochs`
      `function` `studio.purge_access_epoch` (hàm SECURITY DEFINER thuộc `dw_migrator` nhận id tenant, theo tiền lệ
      `platform.purge_tenant_access_version` của tenant-rbac, `db/migrations/versions/b5677d345bc1_tenant_roles.py`), vì
      `kept` đòi một hạn lưu giữ đã thực thi mà một dòng đếm không có; hai bảng cũng vào `EXPORT_EXCLUSIONS` (dữ liệu
      dẫn xuất, không phải dữ liệu của công ty để xuất) (gate (f); thay lý do "giữ có chủ ý" của Đạt 24/10/2026, xem
      Quyết định của spec). Bước `studio.purge_access_epoch` đăng ký ở composition root của worker như
      `access_version_purge_step` của tenant-rbac, khai `tables` rỗng để test phủ không báo trùng với dòng loại trừ, và
      chạy sau mọi bước xóa của tenant (lượt xác nhận (n)).
2. View đầu vào là hợp đồng với tenant-rbac và org-and-principals: `studio.v_principal_grants` (dòng của
   `platform.effective_grants` cho tenant và chủ thể lấy từ setting, khóa `obj.<api_name>.<action>` đổi ra `object_id`
   qua `studio.object_defs`, kèm `expires_at` của lần gán) và `studio.v_principal_workspaces` (workspace chưa lưu trữ mà
   chủ thể là thành viên, chỉ khi thành viên công ty ở trạng thái `active`). Lọc tenant nằm đúng một chỗ, trong mỗi
   view, theo `app.tenant_id`; hàm tính chỉ đọc view (gate (h)). Hai view và hàm tính thuộc `dw_migrator`, không cấp gì
   cho `dw_app`, `dw_agent_ro` hay `PUBLIC`; EXECUTE của `studio.compute_principal_scope()` thu khỏi PUBLIC, chỉ hàm
   cửa gọi nó; `test_privileges.py` khẳng định (gate, MEDIUM M1).
3. `studio.compute_principal_scope()`: `LANGUAGE sql STABLE`, không tham số, tenant từ `app.tenant_id` và chủ thể từ
   `app.user_id`; tính các mức `own`, `workspace`, `tenant` mà ADR-0104 (Accepted) giao cho W1, `create_own_keys` và
   `valid_until`; mức khác không cho tầm nào ở W1; lần gán neo ở một workspace đã lưu trữ không góp gì (không nhánh
   nào, không `valid_until`), và workspace đã lưu trữ không vào `workspace_ids`. Khóa `access_key` của một cặp object và
   workspace tính bằng hàm `studio.access_key(object_id uuid, workspace_id uuid)` (IMMUTABLE, `md5(object_id::text ||
'/' || workspace_id::text)::uuid`) mà ticket này tạo, và cột sinh của ticket 03 gọi cùng hàm đó, một chủ của công
   thức (lượt xác nhận (o)).
4. `studio.ensure_principal_scope()`: SECURITY DEFINER thuộc `dw_migrator`, không tham số, `search_path` cố định,
   EXECUTE thu khỏi PUBLIC và cấp cho `dw_app`. `app.user_id` rỗng, hay chủ thể không có dòng `platform.tenant_members`
   ở tenant đang gắn (nhân viên hỗ trợ, lane không người): không làm gì và không lỗi, để `studio.acl_*` trả `'{}'` và
   policy cho 0 bản ghi (spec R4.4; gate (i)). Khi dòng của chủ thể thiếu, `stale`, khác epoch hay đã quá
   `valid_until`: đọc `version` và `epoch` (thiếu dòng là "vắng"), tính, rồi ghi có compare-and-set: dòng đã có thì
   `UPDATE ... WHERE version = <đã đọc>`, dòng vắng thì `INSERT ... ON CONFLICT DO NOTHING`; thua thì không ghi gì, dòng
   giữ trạng thái khác `valid` và lần gọi kế tiếp tính lại (gate (g)). Không tạo dòng epoch ở đây.
5. Hàm đọc `studio.acl_user()`, `studio.acl_objects(action text, arm text)`, `studio.acl_keys(action text)`,
   `studio.acl_create_own_keys()`: `LANGUAGE sql STABLE`, SECURITY INVOKER, `search_path` cố định; chỉ đọc dòng của chủ
   thể đang gắn với `state = 'valid'`, epoch bằng epoch của tenant (thiếu dòng epoch là 0) và `valid_until` NULL hay sau
   `now()`; trả `'{}'` khi thiếu bất cứ gì. Không có `studio.acl_workspaces(action)`: tầm tạo trên một cặp object và
   workspace đọc qua `acl_keys('create')`, `acl_create_own_keys()` và `acl_objects('create', 'tenant')`, theo từng object
   (gate (e)); `workspace_ids` có bên đọc là kiểm người nhận của ticket 05.
6. Trigger AFTER INSERT, UPDATE, DELETE cùng giao dịch, qua hai hàm SECURITY DEFINER không nhận tên bảng từ người gọi:
   `studio.mark_principal_stale()` cho thay đổi của một chủ thể: upsert dòng của chủ thể với `state = 'stale'`,
   `version + 1` (`INSERT ... ON CONFLICT DO UPDATE`, nên một thu hồi commit giữa lúc một lần tính bắt đầu và lúc nó ghi
   để lại dòng `stale` mà lần ghi vắng-dòng của bước 4 vấp; gate (g)), chỉ khi dòng `platform.tenant_members` của chủ
   thể còn ở tenant đó: khi lần gỡ thành viên cascade xóa `platform.memberships` và `platform.role_assignments`, trigger
   của hai bảng đó không làm gì, vì cascade của bước 1 đã xóa dòng sổ tầm và không dòng `valid` nào ghi được cho người
   không còn là thành viên (lượt xác nhận (k)); `studio.bump_access_epoch()` cho thay đổi cấu trúc: upsert dòng epoch
   của tenant với `epoch + 1`, nên không lần tăng nào mất khi dòng chưa có, và không làm gì khi
   `platform.tenants.status` là `offboarding` hay `offboarded`, nên các lần xóa của lane `offboarding` sau bước
   `studio.purge_access_epoch` không tạo lại dòng (lượt xác nhận (l)). Bảng và hàm, đọc từ
   một bảng khai báo mà test của bước 7 cũng đọc (gate (j)):
    - `studio.mark_principal_stale()`: `platform.role_assignments`, `platform.memberships`, `platform.tenant_members`
      (đổi trạng thái; xóa thì cascade của bước 1 xóa dòng sổ tầm, trigger không chèn lại);
    - `studio.bump_access_epoch()`: `platform.tenant_role_permissions`, `platform.tenant_roles`, `platform.tenants`
      (đổi trạng thái), `platform.entitlements`, `platform.workspaces` (lưu trữ hay xóa; bảng không mang trigger
      `platform.bump_access_version()` nên được nêu riêng), và `studio.object_defs` (INSERT và DELETE: đối tượng mới hay
      mất đổi tầm sinh từ khóa động của tenant-rbac/04; UPDATE OF `default_access` là của ticket 03);
    - mọi bảng mang trigger của `platform.bump_access_version()` (ADR-0104 (Accepted) mục 7, `_BUMPED_TABLES` của
      `b5677d345bc1_tenant_roles.py`) có đúng một dòng trong bảng khai báo, kể cả dòng "không phải đầu vào của tầm bản
      ghi" kèm lý do (vd. bảng quyền trường của tenant-rbac/04).
      Bảng khai báo là bảng `studio.access_input_tables` (`table_name` PK, `trigger_function` CHECK hai tên trên hay
      `none`, `reason` NOT NULL), như `platform.time_partitioned_tables`: revision này chèn các dòng trên và dựng trigger từ
      chúng; một spec sau gắn `platform.bump_access_version()` lên bảng mới thì thêm một dòng trong revision tạo bảng đó,
      không sửa revision này (lượt xác nhận (m)). `dw_app` chỉ SELECT; bảng không có `tenant_id` (danh mục của nền tảng).
7. Test catalog: mỗi bảng của bảng khai báo mang đúng trigger gọi đúng hàm của dòng nó; một bảng mang
   `platform.bump_access_version()` mà không có dòng → test nêu tên bảng; một bảng gắn sai hàm → đỏ.
8. Oracle Python chỉ dùng trong test, trong gói `testing` của `dw_studio`: sinh tổ chức ngẫu nhiên (người, workspace,
   vai trò, mức truy cập, gán vai trò có và không hạn) và tính tầm bằng Python cho test vi sai; ticket 03 mở rộng nó với
   nhánh mặc định truy cập.

## Tiêu chí chấp nhận

- [ ] R5.1 (RA12): test vi sai trên ≥ 500 tổ chức ngẫu nhiên: mọi `studio.acl_*` khớp oracle ở mọi hành động và
      nhánh; hai tenant có cấu trúc giống hệt không lẫn id của nhau; bỏ lọc tenant khỏi `studio.v_principal_grants` →
      test hai tenant đỏ.
- [ ] R5.1 (RA12): chủ thể A của tenant T đọc `studio.principal_scopes` → chỉ dòng của A; dòng của B cùng
      tenant → 0 dòng; gỡ policy RESTRICTIVE, hay đổi nó thành PERMISSIVE → A đọc được dòng của B, và luật hình bảng
      riêng của một người trong `test_rls_coverage.py` (luật có sẵn cho bảng của ADR-0117 (Accepted), bảng này vào danh
      sách của nó) đỏ.
- [ ] R5.2 (RA13): với mỗi loại thay đổi (gỡ và tạm khóa thành viên công ty, gỡ thành viên workspace, gỡ lần gán vai
      trò, hạ mức truy cập trong vai trò, khóa công ty, lưu trữ workspace, tạo hay xóa một đối tượng) commit ở giao dịch
      A, lần gọi cửa sổ tầm đầu tiên của giao dịch B trả tầm mới; gỡ trigger trên một bảng → test của loại đó và test
      catalog đỏ.
- [ ] R5.3 (RA14): không có dòng, dòng `stale`, epoch cũ hay `valid_until` đã qua → mọi `studio.acl_*` trả `'{}'`; trả
      tầm của dòng cũ thay vì mảng rỗng → test đỏ.
- [ ] R5.3: lần gán vai trò hết hạn lúc T, không lệnh ghi nào sau đó: trước T tầm có, sau T câu lệnh đầu tiên
      của chủ thể tính lại và không còn tầm của lần gán đó; bỏ so `valid_until` → test đỏ.
- [ ] R5.4 (RA15): hai kết nối đan xen, dòng đã có: lần tính bắt đầu, thu hồi commit, lần tính ghi → dòng khác `valid`;
      cùng ca khi chủ thể chưa có dòng nào → dòng `stale`, không `valid`; bỏ compare-and-set hay đổi upsert của
      `mark_principal_stale` thành UPDATE thuần → ca tương ứng đỏ; tăng epoch của tenant chưa có dòng epoch → dòng có
      epoch 1.
- [ ] R5.3: kết nối gắn tenant và `app.user_id` của người không phải thành viên công ty, hay không gắn
      `app.user_id`, gọi `studio.ensure_principal_scope()` → không lỗi, không dòng nào, `studio.acl_*` trả `'{}'`.
- [ ] R5.1: người giữ `read` mức Workspace neo ở Marketing phụ trách một lead của Sales → `acl_objects('read',
'own')` có Lead; người giữ `create` mức Của tôi ở Marketing trên Lead và ở Sales trên Campaign →
      `acl_create_own_keys()` có khóa (Lead, Marketing) và (Campaign, Sales), không có (Lead, Sales).
- [ ] R5.5 (RA16): `dw_app` INSERT, UPDATE, DELETE trên `studio.principal_scopes` và `studio.access_epochs` →
      permission denied; `test_privileges.py` khẳng định chỉ có SELECT, và không quyền nào trên hai view và hàm tính.
- [ ] R5.6: gỡ một thành viên công ty chưa từng có dòng sổ tầm, có membership ở hai workspace và hai lần gán → lần gỡ
      thành công, không lỗi khóa ngoại; offboarding xong → 0 dòng `studio.access_epochs` của tenant, kể cả sau các lần
      xóa của lane chạy sau bước `studio.purge_access_epoch`.
- [ ] R5.6: xóa thành viên công ty của một chủ thể → dòng sổ tầm của người đó biến mất trong cùng giao dịch; thành viên
      bị tạm khóa → dòng thành `stale` và tầm tính lại rỗng; offboarding một tenant → 0 dòng của tenant đó ở cả hai bảng,
      test phủ offboarding xanh với hai bảng trong `STUDIO_EXCLUSIONS` theo cách của bước 1; bỏ một bảng khỏi danh sách,
      hay gỡ bước `studio.purge_access_epoch` → test đỏ.
- [ ] R5.7 (RA12): câu INSERT vào `studio.principal_scopes` bằng vai sở hữu hàm (`dw_migrator`) với `tenant_id` của A và
      `principal_id` của người chỉ là thành viên công ty B → lỗi khóa ngoại 23503 trên FK ghép, không dòng nào;
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
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk, hai subagent, vì ticket thêm
  migration), đọc cùng `db/bench/record-access/RESULTS.md`, Comments của ticket 01 và catalog của tenant-rbac
  (`b5677d345bc1`): 1 CRITICAL, 9 HIGH, sửa theo khuyến nghị (Quyết định 4/11/2026 của spec, nhãn ở bước): (b)
  CRITICAL, hình bảng riêng của một người cho `studio.principal_scopes`; (a) dựng tạm theo P0, ticket 07 áp D12; (c)
  `valid_until`; (d) nhánh `own` cộng dồn độ sâu; (e) tầm tạo theo cặp object và workspace; (f) loại trừ offboarding
  qua hàm; (g) compare-and-set khi chưa có dòng; (h) lọc tenant một chỗ; (i) cửa không làm gì với người ngoài; (j)
  bảng khai báo bảng đầu vào.
- 2026-11-04 (agent): MEDIUM, đã sửa: (M1) quyền của view và hàm tính. MEDIUM để lại: (M2) lần thua compare-and-set đọc
  tầm rỗng tới lần gọi kế tiếp, không thử lại trong giao dịch; (M3) chi phí tính lại khi vai đổi liên tục không có trần
  ngoài R9.9, đo ở ticket 06; (M4) hai kết nối cùng tính cho một chủ thể: một thắng, bên thua đọc dòng đã commit.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận: 0 CRITICAL, 6 HIGH, sửa: (k) trigger chủ thể không chèn khi thành viên đã bị gỡ; (l)
  tăng epoch bỏ qua công ty `offboarding`, `offboarded`; (m) bảng khai báo là `studio.access_input_tables`; (n) bước
  `studio.purge_access_epoch` khai `tables` rỗng, chạy cuối; (o) `studio.access_key()` một chủ của công thức; RA12 của
  spec theo cửa không lỗi. Sửa luôn: lần gán neo ở workspace đã lưu trữ không góp gì. Sửa của lượt này không có người đọc
  mới: nhận rủi ro (agent, theo ủy quyền 31/10/2026). Nếu sai thì: ghi ở đây khi dựng. Thứ tự dựng: sau 01 (đã xong), tenant-rbac/04,
  org-and-principals/02; trước 03.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): quyết khi dựng, mỗi điều một dòng. (D1) khóa `obj.*` đổi ra
  `object_id` qua `platform.object_permission_keys(tenant)` của tenant-rbac/04, chủ duy nhất của khóa, thay vì nối
  `studio.object_defs` theo `api_name` lần hai; lọc tenant là CTE `ctx` của mỗi view; đột biến "bỏ lọc tenant" là đổi
  phép nối khóa sang một ánh xạ không có tenant, và test hai tenant đỏ. Nếu sai thì: view nối `studio.object_defs` theo
  `api_name` và `ctx.tenant_id`. (D2) bảng khai báo có thêm `platform.tenant_role_object_privileges` (`bump_access_epoch`):
  bảng này ra đời ở tenant-rbac/04 sau gate và là đầu vào chính; `studio.field_defs`, `studio.field_permissions` là
  `none` kèm lý do (bảo mật trường, ADR-0106 (Accepted)). Nếu sai thì: một revision sau đổi dòng và trigger. (D3) bảng khai báo có
  thêm cột `events`, viết như `pg_get_triggerdef` in ra để test catalog so một chuỗi: `platform.tenants` và
  `platform.tenant_members` chỉ `UPDATE OF status`, `platform.workspaces` `DELETE OR UPDATE OF archived_at`,
  `studio.object_defs` `INSERT OR DELETE`, còn lại `INSERT OR DELETE OR UPDATE`; CHECK trên tập giá trị và
  `(trigger_function = 'none') = (events IS NULL)`. Nếu sai thì: bỏ cột, mọi trigger bắt cả ba lệnh. (D4) lần chuyển
  công ty sang `offboarding` vẫn tăng epoch (đọc `OLD.status` trên `platform.tenants`), mọi lần sau đó thì không (l):
  nếu không, dòng `valid` cũ vẫn đọc được sau khi công ty rời đi. Nếu sai thì: đọc trạng thái mới như bảng khác.
  (D5) `studio.v_principal_workspaces` đòi cả công ty `active`, như `platform.effective_grants`, nên khóa công ty làm
  rỗng cả `workspace_ids`. Nếu sai thì: bỏ điều kiện công ty. (D6) KHÔNG thêm hai bảng vào `EXPORT_EXCLUSIONS`: lane
  xuất mọi bảng có policy `tenant_isolation_%` mà `dw_app` SELECT được, và R4.5 của test phủ offboarding đỏ khi một
  loại trừ xuất nêu bảng lane có xuất; hai bảng đi vào gói xuất như dữ liệu của công ty. Nếu sai thì: lane đọc
  `EXPORT_EXCLUSIONS` và bỏ qua các bảng đó, R4.5 đổi theo. (D7) bước `studio.purge_access_epoch` đăng ký trong
  `OffboardingPurgeSteps.platform()` cạnh `access_version_purge_step`, nơi composition root của worker và test phủ cùng
  đọc; `tables` rỗng nên thứ tự theo tên, không phải cuối: không mang tải vì (l) (đột biến bỏ (l) đỏ, tức có lần xóa
  chạy sau bước). Nếu sai thì: `order_purge_steps` nhận một bước "cuối cùng". (D8) EXECUTE của `studio.access_key`
  chưa cấp cho `dw_app`: cột sinh của ticket 03 quyết khi cần. (D9) "luật có sẵn" cho bảng riêng của một người chưa có
  trong `test_rls_coverage.py` (chưa bảng nào của ADR-0117 (Accepted) được dựng): thêm `_PRIVATE_TO_ONE_PERSON` và
  `private_table_violations` (đúng một PERMISSIVE theo tenant, đúng một RESTRICTIVE `tenant AND (owner OR scope)`,
  RESTRICTIVE đọc `app.user_id` mà không có tên trong danh sách thì nêu tên) cùng test sáu hình sai; policy tên
  `owner_or_scope_principal_scopes`. (D10) `studio.acl_user()` trả `principal_id` của dòng hợp lệ, NULL khi thiếu;
  `acl_objects` nhận nhánh `own`, `tenant`, nhánh `keys` đọc qua `acl_keys`. (D11) `mark_principal_stale` bắt cả INSERT
  của `memberships` và `role_assignments`, nên cài đặt một người để lại dòng `stale`; dòng `stale` giữ mảng cũ, không
  bao giờ được đọc.
- 2026-11-05 (agent): reviewing-feature-security: tách tenant (twin hai tenant, FK ghép R5.7, cửa với người ngoài) và
  phân quyền (`dw_app` không ghi, không gọi hàm tính, view không ai đọc) có test âm; vòng đời: dòng do cửa hay trigger
  tạo, đi theo cascade với thành viên hay hàm purge, mọi mặc định đóng (thiếu dòng, stale, epoch cũ, quá hạn, hành động
  lạ đều là `'{}'`). Tác tử, nội dung không tin cậy, audit không áp dụng: không đường tác tử, không mô hình; sổ tầm là
  dữ liệu dẫn xuất, lần purge nằm trong lượt offboarding đã có audit. `mutations/02.yaml` 17 mục, chưa chạy
  `scripts/mutate.py`; phá tay 7 mục (lọc tenant của view, RESTRICTIVE thành PERMISSIVE, trigger `role_assignments`,
  compare-and-set, upsert của trigger chủ thể, (l), bước purge), cả 7 đỏ.
- 2026-11-05 (agent): MEDIUM. (M5, mới) test vi sai 500 tổ chức mất khoảng 100 giây trên máy dev Windows (một vòng hỏi
  mỗi câu lệnh), một phần lớn của bộ tích hợp Studio. (M6, mới) chưa mã ứng dụng nào gọi cửa hay `studio.acl_*`: người
  đọc là policy của ticket 03, `bind_actor` của ticket 04 và kiểm người nhận (`workspace_ids`) của ticket 05;
  failure-modes #1 đứng mở tới đó. (M7, mới) mọi thay đổi `platform.tenant_role_permissions` (khóa nền tảng, không phải
  `obj.*`) cũng tăng epoch theo danh sách của ticket: tính lại thừa, không sai. M2-M4 như gate.
- 2026-11-05 (agent): resolved. Revision `f6ea6e818d0c` (`f11d7f1`). Test: `test_principal_scopes.py` 36 ca (vi sai
  500 tổ chức ngẫu nhiên với oracle `dw_studio.testing.reach`, twin hai tenant, dòng riêng của một người, tám loại thay
  đổi R5.2 và đối tượng mới, bốn dòng hỏng R5.3, hết hạn không lệnh ghi, hai ca đan xen R5.4 bằng hai kết nối và khóa
  dòng, epoch đầu là 1, người ngoài, `dw_app` không ghi, gỡ thành viên, offboarding, R5.7, test catalog bước 7 và ba
  lỗi cài), `test_reach_oracle.py` 6 ca đơn vị; `test_privileges.py`, `test_rls_coverage.py` (luật bảng riêng của một
  người), `test_offboarding_coverage.py` thêm hai bảng. Cổng: unit 3262 qua, phủ 76,61%; tích hợp studio, platform,
  usage, api, worker 1601 qua (trừ `test_keycloak_realm_live.py`), mypy, ruff, lint-imports, verify_invariants,
  verify_architecture, check_hygiene, release manifest, gitleaks, check_plans xanh.
- 2026-11-05 (agent): nợ lúc đóng hàng: `scripts/mutate.py` cho `mutations/02.yaml` (17); `make test-integration` đầy
  đủ; P50/P95/P99 của các đường ghi mang trigger mới (gán và gỡ vai trò, thành viên workspace và công ty, quyền đối
  tượng, phát hành đối tượng, lưu trữ workspace), so với `f815ab5`; `/code-review`; không route nên không
  reviewing-deployment-security.
