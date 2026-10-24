# 07 — Offboarding xuất mỗi dòng một lần, đọc theo lô keyset

Status: needs-triage
Blocked by: .claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md
Area: studio
Yêu cầu: R11.1, R11.2, R11.3, G8, FH30, FH31

## Mục tiêu

Gói xuất của một công ty rời nền tảng có mỗi dòng đúng một lần, kể cả dòng của bảng phân vùng, và lane
`offboarding` đọc mỗi bảng theo lô keyset thay vì giữ cả bảng trong bộ nhớ (R11, G8, FH30, FH31; YC6, D12).
Audit `tenant.offboarding.purged` vẫn đứng tên người vận hành đã yêu cầu và thêm `details.lane` bằng
`offboarding` (R11.3; `CLAUDE.md`, "Agent and tool rules"; ADR-0011 (Accepted)). Bản vá xuất một lần
không dựa vào việc studio-skeleton/01 làm partition không đọc được theo tên dưới `dw_app`, nhưng ticket
này chờ studio-skeleton/01 vì cả hai sửa `offboarding.py` và test của nó: studio-skeleton/01 thêm
`STUDIO_EXCLUSIONS` và test phủ dùng chính hai truy vấn catalog mà ticket này đổi. record-access/03 và
custom-objects/02 chờ ticket này.

## Việc cần làm

1. Viết trước test âm `test_a_partitioned_table_is_exported_once` trong
   `packages/python/dw_platform/tests/integration/test_offboarding.py`: một bảng phân vùng thử (theo
   khoảng trên `created_at`, có `tenant_id`, policy `tenant_isolation_*` trên bảng cha và trên từng
   partition, `dw_app` có SELECT trên bảng cha và trên partition), một dòng của tenant ở partition tháng
   và một ở DEFAULT; khẳng định mỗi dòng có đúng một lần trong kết quả xuất. Test phải đỏ trên mã hiện
   có, vì dòng được xuất hai lần; ghi kết quả vào Comments. Bảng thử bị xóa ở teardown, vì test catalog
   của studio-skeleton/01 đỏ với một bảng phân vùng có DEFAULT mà sổ không có dòng (studio-skeleton:R3.4).
2. `SqlTenantOffboarding`: `_CATALOG_COLUMNS` thêm điều kiện `NOT c.relispartition`, nên danh mục xuất
   và danh mục xóa chỉ gồm bảng cha.
3. Đo trước bằng catalog rằng mọi bảng mà danh mục xuất trả có khóa chính (`pg_index.indisprimary`);
   bảng nào không có thì ghi Comments và báo Đạt, không đọc cả bảng trong một câu lệnh.
4. `export_rows` đọc mỗi bảng theo lô keyset trên khóa chính, mỗi câu lệnh có dạng
   `WHERE tenant_id = :t AND (<khóa chính>) > (:cuối lô trước) ORDER BY <khóa chính> LIMIT 1000`;
   khóa chính đọc từ catalog, cả lượt trong một giao dịch như hôm nay. Trả các lô theo bảng thay vì
   một danh sách mọi dòng; `OffboardingStorePort` và `_build_bundle` của lane worker ghi từng lô vào
   mục ndjson của bảng đó.
5. Giữ actor của audit `tenant.offboarding.purged` là người vận hành đã yêu cầu (ADR-0011 (Accepted),
   mục "Not applied"); `_record_purge_audit` ghi `details` là `{"lane": "offboarding"}` thay cho `{}`,
   vì lane thi hành quyết định của một người thì audit người đó và nêu tên mình ở `details.lane`
   (`CLAUDE.md`, "Agent and tool rules").
6. Test: test ở bước 1 xanh sau bản vá; bảng thử 2.500 dòng xuất đủ 2.500 dòng, mỗi dòng một lần, qua 3
   câu lệnh đọc mà không câu nào trả quá 1.000 dòng (bắt câu lệnh bằng sự kiện `before_cursor_execute`);
   `apps/worker/tests/unit/test_offboarding_consumer.py` theo chữ ký mới.

## Tiêu chí chấp nhận

- [ ] R11.1 (FH30): `test_a_partitioned_table_is_exported_once` đỏ trên mã trước bản vá (ghi Comments)
      và xanh sau; bỏ điều kiện `NOT c.relispartition` khỏi danh mục thì test đỏ lại.
- [ ] R11.2: bảng thử 2.500 dòng xuất đúng 2.500 dòng qua 3 câu lệnh đọc, câu nào cũng trả không quá
      1.000 dòng; đổi về một câu `SELECT` cho cả bảng thì test đỏ.
- [ ] R11.3 (FH31): sau `purge_rows`, audit `tenant.offboarding.purged` của tenant có `details.lane` bằng
      `offboarding`; ghi lại `details` rỗng thì test đỏ.
- [ ] G8 (FH31): `test_purge_records_an_audit_event_before_deleting_anything` xanh trước và sau thay đổi;
      đổi actor sang `system_actor('offboarding')` thì test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:68-101`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:162-181`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:217-247`
- `db/migrations/sql/0013_partition_maintenance.sql:73-76`
- `apps/worker/src/dw_worker/consumers/offboarding.py:142-192`
- `packages/python/dw_platform/tests/integration/test_offboarding.py:287-319`
- `docs/adr/0011-a-background-lane-audits-as-itself.md:44-45`
- spec: R11, G8, FH30.

## Comments
