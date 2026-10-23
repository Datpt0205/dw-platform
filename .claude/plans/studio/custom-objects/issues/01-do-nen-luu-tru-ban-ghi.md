# 01 — Đo nền lưu trữ bản ghi trước khi chốt ADR (partition, ngân sách slot, unaccent, InitPlan)

Status: needs-triage
Area: studio
Yêu cầu: R9.1, R9.2, R9.3, R9.4

## Mục tiêu

Cho Đạt số đo để chốt hai quyết định của ADR-0107 (Proposed) trước khi viết migration đầu của `studio.records`:
partition băm modulus 8 theo `tenant_id` hay không (R9.2, R9.3; DO-15, Q2 của spec) và ngân sách slot mỗi đối
tượng (R9.4), cùng một lần đọc sớm YC20 (R9.1) trên lược đồ ứng viên. Mọi số đo ở quy mô D12: 10 triệu bản ghi một
đối tượng, 50 triệu một công ty, 5.000 người dùng, 200 workspace, cây workspace sâu 6. Đây là phép đo FOG-41 và
FOG-55 mà `.claude/plans/studio/discovery/issues/07-records-storage.md` giao cho ticket này.

## Việc cần làm

1. Máy đo là máy tham chiếu của spec (host chính sau D14, ít nhất 4 vCPU, 16 GB) với `postgres:16-alpine` của
   compose. Ghi vào Comments: CPU, RAM, loại đĩa, digest của image, `shared_buffers`, `work_mem`.
2. Viết harness `scripts/bench_records_storage.py` và DDL ứng viên `scripts/bench_records_storage.sql` (không phải
   revision Alembic), giữ trong repo để ticket 04 đo lại R9.1 trên mã thật. Harness tạo database `dw_bench` bằng
   `dw_migrator` từ migration head rồi chạy DDL ứng viên: `studio.object_defs`, `studio.field_defs` và
   `studio.records` theo mục Dữ liệu của spec, với tập slot đề xuất `t01`-`t24`, `i01`-`i12`, `f01`-`f08`,
   `d01`-`d08`, `z01`-`z08`, `b01`-`b08`, `u01`-`u04`, mỗi slot một chỉ mục từng phần
   `(tenant_id, object_id, <slot>, id) WHERE <slot> IS NOT NULL AND deleted_at IS NULL`, mỗi slot `u` thêm UNIQUE
   từng phần `(tenant_id, object_id, uNN) WHERE uNN IS NOT NULL AND deleted_at IS NULL`; policy RESTRICTIVE
   `tenant_isolation_records` dạng InitPlan trên bảng cha và mỗi partition. Hai biến thể:
   `PARTITION BY HASH (tenant_id)` modulus 8 (`studio.records_p0` tới `studio.records_p7`) và không partition với
   cùng khóa tổng hợp.
3. Bộ gieo có hạt giống, viết thành hàm `seed(scale)` dùng lại được để record-access/01 đo quyền trên cùng dữ liệu:
   một công ty lớn có 5 đối tượng giống Lead, mỗi đối tượng 10 triệu bản ghi (50 triệu), 5.000 người dùng làm người
   phụ trách, 200 workspace trong cây sâu 6; 99 công ty nhỏ, mỗi công ty 10.000 bản ghi, rải trên cả 8 partition;
   tên tiếng Việt có dấu, có giá trị trùng và NULL ở mỗi họ slot.
4. Đo bằng `dw_app` dưới FORCE RLS, mỗi giao dịch đặt `app.tenant_id`:
    - thời gian lập kế hoạch p50 và p95 của truy vấn ba vị từ trên ba slot khác họ, với custom plan và generic plan,
      có và không có `tenant_id = $1`;
    - `CacheMemoryContext` mỗi backend sau khi chạm cả 8 partition (`pg_backend_memory_contexts`);
    - trang đầu 50 dòng sắp `created_at DESC, id DESC`, sắp `name`, lọc một slot `t` và một slot `i`, và `GET` theo
      `(tenant_id, id)`: p50, p95, p99 phía máy chủ;
    - `ORDER BY name` với `COLLATE "vi-VN-x-icu"` dưới RLS: có dùng chỉ mục không, và thứ tự "An, Ánh, Ân, Bình,
      Đạt";
    - tỉ lệ HOT và WAL của hỗn hợp cập nhật kiểu Lead (đổi `data`, đổi một slot) ở fillfactor 100 và 70;
    - chi phí policy dạng InitPlan so với dạng đọc setting theo từng dòng của
      `db/migrations/sql/0001_platform_baseline.sql`;
    - chi phí `pg_advisory_xact_lock_shared` trên (công ty, đối tượng) mỗi lần ghi;
    - `INSERT ... ON CONFLICT (tenant_id, object_id, u01) WHERE u01 IS NOT NULL AND deleted_at IS NULL DO UPDATE`
      dưới policy theo từng lệnh (câu 3 của discovery/10);
    - trigger `platform.touch_updated_at()` trên bảng cha có chạy cho dòng ở partition và nhường giá trị câu lệnh
      nêu không;
    - `CREATE EXTENSION unaccent` bằng `dw_migrator` ở compose và ở CI, và cột STORED sinh từ hàm bọc IMMUTABLE với
      `COLLATE "C"` (FOG-55, cho tìm không dấu ở W2);
    - đếm bản ghi cho hạn mức lưu trữ: dòng bộ đếm so với ước lượng `reltuples` (câu 4 của discovery/07).
5. Ghi kết quả vào Comments của ticket này và của discovery/07: bảng số đo, lệnh chạy, `EXPLAIN (ANALYZE, BUFFERS)`
   cho mỗi khẳng định "dùng chỉ mục", ngưỡng nào đạt và ngưỡng nào trượt. Đề xuất sửa quyết định 1 (ngân sách slot)
   và 2 (partition) của ADR-0107 (Proposed) theo số, qua `mattpocock-skills:domain-modeling`; Đạt quyết DO-15.

## Tiêu chí chấp nhận

- [ ] R9.2: planning p95 của truy vấn ba vị từ (custom và generic plan) và `CacheMemoryContext` mỗi backend với 8
      partition có trong Comments kèm lệnh đo, và kết luận đạt hay trượt so với 5 ms và 64 MB; sai nếu một số
      không có lệnh hay kế hoạch đi kèm.
- [ ] R9.3: cùng các số đó đo trên biến thể không partition, đặt cạnh biến thể 8 partition trong một bảng; sai nếu
      chỉ một biến thể được đo.
- [ ] R9.4: ngân sách slot đề xuất cho mỗi họ, kèm số chỉ mục trên một bảng, tỉ lệ HOT và WAL đã đo; sai nếu ngân
      sách không dẫn số đo nào.
- [ ] R9.4: UNIQUE từng phần trên `u01` của bảng partition, `ON CONFLICT` dưới policy theo lệnh, trigger
      `updated_at` trên partition, `CREATE EXTENSION unaccent` dưới `dw_migrator` và cột sinh `COLLATE "C"`: mỗi
      mục ghi chạy được hay không, kèm lỗi nguyên văn khi không.
- [ ] R9.1: trang đầu 50 dòng p95 và `GET` một bản ghi p95 ở quy mô D12 với policy tenant, so với 50 ms và 5 ms,
      mỗi khẳng định "dùng chỉ mục" có `EXPLAIN`; sai nếu đo ở quy mô nhỏ hơn D12.
- [ ] R9.1: `ORDER BY name` dưới RLS dùng chỉ mục và trả "An, Ánh, Ân, Bình, Đạt" đúng thứ tự; sai nếu kế hoạch có
      `Sort` trên cả tập khớp.
- [ ] Xong: `uv run python scripts/bench_records_storage.py --scale d12` xanh.

## Nguồn

- `.claude/plans/studio/discovery/issues/07-records-storage.md:10-18`; spec: R9.1, R9.2, R9.3, R9.4, Q2.
- `.claude/plans/studio/discovery/issues/10-dedupe-and-upsert.md:14-15`; spec: R7.3.
- `db/migrations/sql/0001_platform_grants.sql:27-46`; `db/migrations/sql/0001_platform_baseline.sql:770`.
- `db/migrations/versions/0004_touch_updated_at_yields.py:44`; `infra/compose/docker-compose.yml:45`.
- ADR-0107 (Proposed) quyết định 1, 2 và Open 2.

## Comments
