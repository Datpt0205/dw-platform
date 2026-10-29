# 03 — Thu quyền ghi thừa của dw_app và RLS đọc setting một lần mỗi câu lệnh

Status: resolved (2026-10-29, main)
Blocked by: 01, 02, .claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md
Area: studio
Yêu cầu: R5.1, R5.2, R5.3, R5.4, G6, FH12, FH13, FH14

## Mục tiêu

Thông tin đăng nhập của ứng dụng không còn ghi được bảng người vận hành, gói dịch vụ và user ngoài
việc tạo user khi đăng nhập lần đầu; quyền của `dw_provisioner` có một nguồn; và nếu phép đo lặp lại
được lợi ích, mọi policy RLS đọc setting một lần mỗi câu lệnh, thành mẫu cho mọi policy Studio
(R5.1-R5.3, G6, FH12-FH14). Đo trước; dưới ngưỡng thì ghi "không áp dụng". usage-and-limits/01 chờ ticket
này, vì cả hai viết migration cho `platform.plans`: ticket này thu quyền ghi của `dw_app`, ticket kia thêm
khóa ngoại rồi gỡ cột `quotas`.

## Việc cần làm

Đo trước (R5.3):

1. Trên DB của `make infra-up`, tạo trong phiên đo (không qua migration) một bảng thử 200.000 dòng
   của một tenant, cùng dạng cột, index và policy với một bảng tenant có trang danh sách; kết nối bằng
   `dw_app`, đặt `app.tenant_id` theo giao dịch bằng `set_config(..., true)`. discovery/05 chạy trước
   trên thân đường găng (OPS-j): có `## Answer` với số đo dạng sub-SELECT thì trỏ về đó và chỉ đo phần
   còn thiếu.
2. `EXPLAIN (ANALYZE, BUFFERS)` một trang danh sách (ORDER BY theo index, LIMIT 50) với policy dạng
   theo dòng hiện có và với dạng `(SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)`;
   5 lần mỗi dạng, lấy trung vị; ghi số, plan và phiên bản PostgreSQL vào Comments.
3. Trung vị dạng sub-SELECT thấp hơn ít nhất 20% → làm bước 7-10. Dưới ngưỡng → ghi "không áp dụng"
   vào Comments và đề xuất rút R5.3 bằng `[Bỏ]` qua `writing-plan-specs`; bước 4-6 vẫn làm.

Quyền (R5.1, R5.2, G6):

4. Revision Alembic mới `db/migrations/versions/*_narrow_app_role_writes.py` (id ngẫu nhiên): REVOKE
   INSERT, UPDATE, DELETE, TRUNCATE trên `platform.platform_operators` và `platform.plans` khỏi
   `dw_app`; REVOKE UPDATE, DELETE, TRUNCATE trên `platform.users` khỏi `dw_app` (INSERT giữ cho
   đăng nhập lần đầu và lời mời); mỗi câu canh việc vai tồn tại như revision `648e2f7c3edb`;
   downgrade trả lại quyền của baseline.
5. Cùng revision: đặt quyền của `dw_provisioner` về đúng tập (bảng, quyền, cột) mà mọi đường dùng vai này
   thực sự chạy: `SqlProvisioningRepository`, bộ nạp `retention_terms` của job migrate
   (`retention_terms.py`, `82e168f6d189`), ghi danh tính đăng nhập của người vận hành (R4.4, FH11), và các
   grant sau baseline (`af8ee878b4ab`, `5d9d89ffc716`); liệt kê bằng cách đọc code của từng đường và ghi
   danh sách vào Comments; thu phần thừa mà baseline cấp; sửa `_WRITE_TABLES`, danh sách động từ và quyền theo cột (`GRANT UPDATE (<cột>)`) của
   `scripts/create_provisioner_role.py` về cùng tập.
6. `packages/python/dw_platform/tests/integration/test_privileges.py`: mỗi REVOKE ở bước 4 có một
   khẳng định câu lệnh (`permission denied`) và một khẳng định catalog `has_table_privilege` theo mẫu
   `test_the_application_cannot_rewrite_the_role_catalogue`; một test so tập `(bảng, quyền, cột)` của
   `dw_provisioner` trong catalog (gồm quyền theo cột của `information_schema.column_privileges`) với tập
   script khai (FH13), và một test chạy mỗi đường ở bước 5 dưới `dw_provisioner` thật.

Chuyển policy (R5.3), chỉ khi bước 3 qua ngưỡng:

7. Revision Alembic mới `db/migrations/versions/*_rls_settings_once_per_statement.py`: liệt kê mọi
   policy từ `pg_policies` lúc viết revision (27 ở baseline, các revision sau, mọi partition hiện có)
   và viết lại từng cái bằng `ALTER POLICY ... USING (...) WITH CHECK (...)`, mỗi
   `current_setting(...)` nằm trong một sub-SELECT; không thay chuỗi lúc chạy.
8. Cùng revision: viết lại bản ba tham số `platform._ensure_one_partition(schema_name, parent, month)` của
   studio-skeleton/01 để partition tạo sau nhận policy dạng mới; giữ nguyên việc thu mọi quyền của
   `dw_app` trên partition (DO-02.2), việc đọc sổ `platform.time_partitioned_tables` và việc chuyển dòng
   kẹt ở DEFAULT.
9. `packages/python/dw_platform/tests/integration/test_rls_coverage.py`: test mới đỏ khi một
   `current_setting(` trong `qual` hay `with_check` của `pg_policies` nằm ngoài sub-SELECT; bộ khớp
   hình workspace nhận dạng bọc; `_TRUSTED_SETTINGS` vẫn thấy tên setting.
10. Policy do ticket khác tạo sau khi revision này vào nhánh chính phải theo dạng mới, vì test ở bước
    9 đỏ với dạng cũ; policy tạo trước đó được revision này chuyển.

## Tiêu chí chấp nhận

- [x] R5.1 (FH12): bằng `dw_app`: INSERT `platform.platform_operators`, UPDATE `platform.plans`,
      UPDATE và DELETE `platform.users` → `permission denied`; `has_table_privilege` sai cho từng quyền
      bị thu; khôi phục một GRANT → test đỏ.
- [x] R5.1: đăng nhập lần đầu, lời mời và nối lại Zalo vẫn xanh (`test_identity_provisioning.py`,
      `test_tenant_members.py`, `test_zalo_link_repo.py`) dưới quyền mới.
- [x] R5.2 (FH13): thêm một bảng vào `_WRITE_TABLES` mà migration không cấp → test so quyền đỏ; bỏ
      một quyền khỏi migration mà script còn cấp → đỏ.
- [x] R5.4 (FH13): thu quyền ghi `platform.retention_terms` của `dw_provisioner` → test của bộ nạp retention
      dưới `dw_provisioner` đỏ; thu INSERT danh tính đăng nhập → test ghi danh tính người vận hành đỏ.
- [x] R5.3 (FH14): sau revision bước 7, ALTER một policy về dạng theo dòng → test ở bước 9 đỏ; một
      partition tạo bằng `platform.ensure_time_partitions` mang dạng mới. Nếu bước 3 dưới ngưỡng,
      Comments có số đo và đề xuất rút R5.3.
- [x] G6: `test_a_connection_that_never_scopes_itself_reads_nothing` và mọi test RLS hiện có xanh
      sau revision bước 7.
- [x] Xong: `make test-unit test-contract test-architecture && uv run pytest -m integration packages/python/dw_platform apps/api` xanh.

## Nguồn

- `db/migrations/sql/0001_platform_grants.sql:31-32`
- `db/migrations/sql/0001_platform_grants.sql:45-46`
- `db/migrations/sql/0001_platform_grants.sql:64-74`
- `scripts/create_provisioner_role.py:107-115`
- `packages/python/dw_platform/tests/integration/test_privileges.py:45-56`
- `apps/api/src/dw_api/dependencies/auth.py:159-163`
- `db/migrations/sql/0001_platform_baseline.sql:773`
- `db/migrations/sql/0013_partition_maintenance.sql:32`
- `db/migrations/sql/0013_partition_maintenance.sql:74`
- `packages/python/dw_platform/tests/integration/test_rls_coverage.py:95`
- `packages/python/dw_platform/tests/integration/test_rls_coverage.py:427-447`
- spec: R5, G6, FH12-FH14; ADR-0105 (Accepted) quyết định 1; si-platform
  `db/si/migrations/0057_record_tenant_policies_initplan.sql` (dạng và số đo).

## Comments

- 2026-10-29 (agent, tạm theo ủy quyền): chờ thêm ticket 02, vì hai ticket cùng chạm quyền của `dw_app` trên `platform.users` và `platform.external_identities` (cảnh báo collision của `scripts/check_plans.py` sau bản sửa gate của ticket 02). Nếu sai thì: bỏ 02 khỏi Blocked by.
- 2026-10-29 (agent): gate `checking-plan-readiness` lượt 1: R5.2 phủ mọi đường dùng `dw_provisioner` (HIGH, đã sửa ở spec và bước 5-6). MEDIUM để người làm xử lý khi gặp: danh sách policy của partition phải đọc catalog lúc upgrade (không danh sách tĩnh, tập partition ở uat và production khác máy dev); test so `qual` trước và sau khi bỏ lớp bọc, và một test âm tenant B đọc và ghi dòng của A sau revision; đo R5.3 trên dạng `tenant AND (workspace OR scope)`, Execution Time không gồm planning; hàm tự đọc setting bên trong policy cũng phải bọc `(SELECT f())`; bảng mới không tự nhận quyền ghi của `dw_app` qua `ALTER DEFAULT PRIVILEGES` (test catalog liệt kê bảng `dw_app` không được ghi).
- 2026-10-29 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-10-29 (agent): đo trước (bước 1-3), PostgreSQL 16.15, bảng thử trong schema riêng của `dw_test`, 200.000 dòng một tenant trên 20 workspace cộng 200.000 dòng tenant khác, index `(tenant_id, workspace_id, created_at DESC, id DESC)`, policy dạng `tenant AND (workspace OR scope)`, đọc bằng `dw_app` với `app.tenant_id` và `app.workspace_id` đặt theo giao dịch, trang `ORDER BY created_at DESC, id DESC LIMIT 50`, `EXPLAIN (ANALYZE, BUFFERS)`, Execution Time không gồm planning, 5 lần sau một lượt làm nóng: dạng theo dòng trung vị 224,0 ms (173,5-254,1; plan `Limit / Gather Merge`), dạng sub-SELECT trung vị 84,2 ms (72,1-87,1; plan `Limit / Result` với InitPlan), giảm 62%, qua ngưỡng 20%, nên bước 7-10 đã làm. discovery/05 chưa có `## Answer` nên đo đủ.
- 2026-10-29 (agent): quyền của `dw_provisioner` theo mọi đường dùng vai (đọc mã): `SqlProvisioningRepository` (tenants SELECT/INSERT/UPDATE, workspaces SELECT/INSERT, entitlements SELECT/INSERT, memberships SELECT/INSERT/UPDATE, users SELECT, plans SELECT, roles SELECT, platform_operators SELECT/INSERT/DELETE, support_staff SELECT/INSERT/DELETE, support_grants SELECT và UPDATE năm cột phân công, audit_events INSERT, provisioning_audit SELECT/INSERT, tenant_offboarding_requests SELECT/INSERT), bộ nạp `retention_terms` (SELECT/INSERT/UPDATE/DELETE), danh tính đăng nhập của người vận hành (external_identities SELECT/INSERT, R4.4). Thu phần thừa của baseline: DELETE trên tenants, workspaces, entitlements, memberships; INSERT/UPDATE/DELETE trên users và plans; UPDATE trên platform_operators; UPDATE/DELETE trên provisioning_audit; UPDATE trên tenant_offboarding_requests. Làm khác chữ của bước: quyền theo cột của `support_grants` vào cả migration lẫn script; `REVOKE ALL` rồi `GRANT` đúng tập trong revision, nên catalog sau upgrade đúng bằng tập khai; test so ba nguồn (catalog, migration, script) theo (bảng, quyền, cột). Danh sách policy là 50 policy của bảng không phải partition lúc viết revision, mỗi cái có biểu thức cũ và mới viết sẵn (không thay chuỗi lúc chạy); partition (khác nhau giữa môi trường) được tìm trong catalog lúc upgrade và nhận cùng một vị từ tĩnh; `platform._ensure_one_partition` viết lại với vị từ mới.
- 2026-10-29 (agent): mutation check 7/7 đỏ (`mutations/03.yaml`, tại chỗ sau một lượt đối chứng xanh; DB test dựng và migrate lại mỗi phiên nên đột biến trong migration có tác dụng). `reviewing-feature-security`: cô lập tenant (policy cùng nghĩa, mọi test RLS cũ xanh, G6 xanh), phân quyền (mỗi quyền bị thu có test âm câu lệnh và catalog), mặc định (revision canh vai tồn tại; partition tạo sau nhận dạng mới); không áp autonomy, nội dung không tin cậy, audit (không đường ghi mới). Cổng: ruff, format, mypy, `make test-unit`, `make test-contract`, `make test-architecture`, integration của `dw_platform` và `apps/api` xanh.
- 2026-10-29 (agent): P50/P95/P99 (ms), app thật qua httpx, PostgreSQL thật, 1.000 dòng mỗi bảng, 300 yêu cầu mỗi route, so với `0556079` xuất bằng `git archive`, đo tuần tự:

    | Operation                         | Trước (P50/P95/P99) | Sau (P50/P95/P99)  |
    | --------------------------------- | ------------------- | ------------------ |
    | `GET /api/v1/approvals`           | 33,7 / 42,2 / 49,9  | 32,6 / 42,9 / 58,0 |
    | `GET /api/v1/audit/events`        | 32,9 / 40,2 / 45,2  | 32,0 / 41,0 / 50,2 |
    | `GET /api/v1/feedback`            | 35,1 / 48,8 / 62,9  | 35,1 / 45,2 / 51,8 |
    | `GET /api/v1/knowledge/documents` | 39,0 / 47,1 / 51,5  | 39,6 / 49,3 / 52,5 |
    | `GET /api/v1/memory/items`        | 34,3 / 41,9 / 49,4  | 35,4 / 44,3 / 51,4 |

    Mọi route trong ngân sách; không P95 nào chậm hơn 20% (lớn nhất +5,6% ở memory). Ở 1.000 dòng mỗi bảng, khác biệt giữa hai dạng nằm trong nhiễu; lợi ích đo được ở 200.000 dòng ở dòng Comments đầu.
