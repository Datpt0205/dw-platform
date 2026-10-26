# 01 — Đo nền lưu trữ bản ghi trước khi chốt ADR (partition, ngân sách slot, unaccent, InitPlan)

Status: needs-triage
Area: studio
Yêu cầu: R9.1, R9.2, R9.4, R9.5, R9.6, R9.7, R9.8, R9.9, R9.10, R9.11, R9.12, CO27

## Mục tiêu

Cho Đạt số đo để chốt hai quyết định của ADR-0107 (Accepted) trước khi viết migration đầu của `studio.records`:
modulus 8 hay 4 của partition băm theo `tenant_id` (R9.2, R9.5) và tập slot mỗi họ (R9.4), cùng đường ghi và bảo trì
(R9.6 tới R9.12) và một lần đọc sớm YC20 (R9.1), trên DDL W1 cộng phần W2 đã biết, vì modulus và tập slot cố định từ
revision đầu (V4.32; ADR-0107 (Accepted) quyết 2). Ticket này là chủ duy nhất của harness, seed và tải: record-access/01
dùng lại chúng và chỉ thêm biến thể chính sách. Không mở lại ADR-0107 (Accepted); chỉ sửa phép đo và số. Đây là phép đo FOG-41 và
FOG-55 mà `.claude/plans/studio/discovery/issues/07-records-storage.md` giao cho ticket này.

## Việc cần làm

1. Máy đo là máy tham chiếu mà YC20 định nghĩa (host chính sau D14), cùng máy của record-access/01, với
   `postgres:16-alpine` của compose ghim theo digest. Ghi vào Comments: CPU, RAM, loại đĩa, digest của image,
   `shared_buffers`, `work_mem` và mọi dòng `postgresql.conf` khác mặc định.
2. Harness `scripts/bench_records_storage.py` và DDL của từng biến thể dưới `scripts/bench_records_storage/` (không phải
   revision Alembic), giữ trong repo để ticket 04 đo lại R9.1 trên mã thật và record-access/01 thêm biến thể chính sách
   mà không chép harness. Harness tạo database `dw_bench` bằng `dw_migrator` từ migration head rồi chạy DDL của biến
   thể. Biến thể, mỗi biến thể chạy ở modulus 8 (`studio.records_p0` tới `p7`) và modulus 4 (`p0` tới `p3`), không
   biến thể không partition (DO-15):
    - A0: DDL W1 đúng như mục Dữ liệu của spec: `studio.object_defs`, `studio.field_defs`, `studio.records` với tập slot
      đề xuất `t01`-`t24`, `i01`-`i12`, `f01`-`f08`, `d01`-`d08`, `z01`-`z08`, `b01`-`b08`, `u01`-`u04`, mỗi slot một
      chỉ mục từng phần `(tenant_id, object_id, <slot>, id) WHERE <slot> IS NOT NULL AND deleted_at IS NULL`, mỗi slot
      `u` thêm UNIQUE từng phần `(tenant_id, object_id, uNN) WHERE uNN IS NOT NULL AND deleted_at IS NULL`, chỉ mục hệ
      thống (PK, `create_key`, `created_at`, `updated_at`, `name`, `(tenant_id, workspace_id)` của FK tới workspace sở
      hữu), `access_key` và `owner_id` của record-access/03, `studio.record_write_keys` của mục Dữ liệu; policy
      RESTRICTIVE `tenant_isolation_records` dạng InitPlan trên bảng cha và mỗi partition, cộng các policy PERMISSIVE
      theo lệnh với ba nhánh tầm của W1 (mặc định toàn tenant, khóa workspace, của tôi; record-access/03).
    - A1: A0 cộng phần W2 đã biết (GIN `read_grants`, `name_key`, slot `l`, `m` cùng FK ghép; ADR-0105 (Accepted)
      quyết 3, ADR-0107 (Accepted) quyết 1, 4, 7) và policy sáu nhánh theo mẫu của ADR-0105 (Accepted) quyết 1
      (mặc định toàn tenant, khóa workspace, của tôi, của nhóm, cấp dưới, khóa chia sẻ). A1 quyết modulus.
    - A2: A1 với chỉ mục `updated_at` bằng BRIN thay btree.
    - A3: A1 bỏ chỉ mục của họ `b`.
    - C hẹp: pivot có kiểu, mỗi hàng pivot mang tầm truy cập của bản ghi; chỉ đo đường ghi và bảo trì.
    - JSONB: chỉ một lần `EXPLAIN` dưới `dw_app` cho một lọc trên `data`, ghi vào Comments lý do loại (hàm so sánh của
      `jsonb` không LEAKPROOF nên không chạy trước policy).
3. Bộ gieo có hạt giống `seed(scale)`, một seed duy nhất mà record-access/01 dùng lại không đổi:
    - T1: 5×10^7 bản ghi trên 50 đối tượng, `mkt_lead` 10^7; cùng cột `t01` giữ picklist ít giá trị ở đối tượng này và
      email gần như duy nhất ở đối tượng khác; có NULL, giá trị trùng và tên tiếng Việt có dấu ở mỗi họ slot.
    - T2: 10^6 bản ghi, `tenant_id` chọn để rơi cùng partition hash với T1.
    - 98 tenant nhỏ rải trên mọi partition.
    - Tổ chức của T1: 5.000 người, 200 workspace trong cây sâu 6, một tài khoản dịch vụ sở hữu 10^6 lead, một Campaign
      có 10^5 lead con; cùng dữ liệu mà các nhánh của policy sáu nhánh đọc (300 nhóm, cây quản lý sâu 8, chia sẻ tay trên
      0,4% và 5% bản ghi, 50 phiên bản quy tắc chia sẻ khớp 10% lead), để record-access/01 không gieo dữ liệu riêng.
4. Tải, dưới `dw_app` với FORCE RLS, mỗi giao dịch đặt `app.tenant_id`, `app.user_id`, `app.actor_kind`:
    - 50 phiên đồng thời, tham số rút ngẫu nhiên; 80% đọc ở mọi hồ sơ quyền, mỗi hồ sơ một chủ thể thật trong seed (Của tôi;
      Của nhóm tôi; Workspace của tôi trên một workspace; Workspace của tôi và cấp dưới trên 40 workspace; Toàn công ty;
      `public_read` trên `mkt_lead`; quản lý có 50, 500 và 5.000 cấp dưới; người nhận 500 chia sẻ; agent có giới hạn dữ
      liệu một đối tượng; tài khoản dịch vụ sở hữu 10^6 lead), kể cả sắp theo slot khi tầm hẹp; 15% sửa một trường theo luồng chấm điểm AI
      (qua `RecordsPort` với khóa `wf:`, nên mỗi lần sửa ghi một dòng `studio.record_write_keys`, R5.9); 5% tạo mới.
    - Một soak 2 giờ ở 200 lần ghi mỗi giây; một lần chạy nguội sau khi khởi động lại PostgreSQL và xóa cache của hệ
      điều hành. Mỗi p95 trên ít nhất 1.000 mẫu, cả nóng lẫn nguội.
5. Đo, cho mỗi biến thể và modulus, ngưỡng theo bảng mục 4.5 của bản trả lời (V4.32):
    - trang đầu 50 dòng p95 ≤ 50 ms ở mọi hồ sơ quyền và `GET` p95 ≤ 5 ms (R9.1); tạo mới và sửa một trường p95 ≤ 10 ms
      (record-access:R9.5);
    - planning p95 của truy vấn ba vị từ trên ba slot khác họ (custom và generic plan, có và không có `tenant_id = $1`)
      ≤ 5 ms, `CacheMemoryContext` mỗi backend sau khi chạm mọi partition ≤ 64 MB (`pg_backend_memory_contexts`) (R9.2);
    - tỉ lệ HOT của lần sửa chỉ chạm `data`, A1 so với A2 (dự đoán A1 ≈ 0%, A2 > 0%);
    - WAL bền vững (R9.6), autovacuum (R9.7), q-error (R9.8), T2 khi T1 bận (R9.9), nhập qua RecordService (R9.10),
      promote và purge trên 10^7 hàng (R9.11), 32 người ghi vào con của một Campaign (R9.12);
    - tổng hợp với `studio.acl_*` PARALLEL SAFE so với mặc định: kế hoạch có Gather không và kết quả có bằng nhau không,
      chỉ báo cáo, Đạt đặt ngưỡng (ADR-0127 (Accepted), Open 1);
    - giữ các phép đo cũ: `ORDER BY name` với `COLLATE "vi-VN-x-icu"` dưới RLS có dùng chỉ mục không và thứ tự "An,
      Ánh, Ân, Bình, Đạt"; policy dạng InitPlan so với dạng đọc setting theo từng dòng của
      `db/migrations/sql/0001_platform_baseline.sql`; chi phí `pg_advisory_xact_lock_shared` trên (công ty, đối tượng)
      mỗi lần ghi; `INSERT ... ON CONFLICT (tenant_id, object_id, u01) WHERE u01 IS NOT NULL AND deleted_at IS NULL DO
UPDATE` dưới policy theo từng lệnh (câu 3 của discovery/10); trigger `platform.touch_updated_at()` trên bảng cha
      có chạy cho dòng ở partition và nhường giá trị câu lệnh nêu không; `CREATE EXTENSION unaccent` bằng `dw_migrator`
      ở compose và ở CI, và cột STORED sinh từ hàm bọc IMMUTABLE với `COLLATE "C"` (FOG-55); đếm bản ghi cho hạn mức lưu
      trữ: dòng bộ đếm so với ước lượng `reltuples` (câu 4 của discovery/07).
6. Tự kiểm của harness (CO27): một lần chạy kiểm bỏ chỉ mục btree `updated_at` của A1 phải cho tỉ lệ HOT lớn hơn 0 ở
   lần sửa chỉ chạm `data`, không thì harness thoát khác 0 vì bộ đếm HOT mù (failure-modes #3); mỗi khẳng định "dùng
   chỉ mục" trong báo cáo phải kèm `EXPLAIN (ANALYZE, BUFFERS)` của nó, và mỗi biến thể có số ở cả hai modulus, không
   thì harness thoát khác 0.
7. Luật quyết (V4.32), ghi vào Comments cùng bảng số: giữ A1 khi mọi dòng có ngưỡng đạt; chỉ đường ghi trượt thì thử lần
   lượt A2, A3, giảm số slot mỗi họ, `wal_compression`, và chỉ khi vẫn trượt mới xét pivot cho các trường tràn; chọn BRIN
   (A2) khi HOT > 0 và trang "mới cập nhật" vẫn ≤ 50 ms p95; modulus 8 chỉ khi A1 đạt ngưỡng và cho lợi ích bảo trì đo
   được (vacuum, purge, promote), không thì modulus 4; A1 trượt ngưỡng đọc ở cả hai modulus thì quay lại người đặt yêu
   cầu (DO-15). Đề xuất sửa số của ADR-0107 (Accepted) quyết 1 (ngân sách slot) và 2 (partition) theo số đo, và thay số
   "3 lần dung lượng chỉ mục và 3,4 lần chi phí ghi" của pivot ở mục Alternatives bằng số đo của C hẹp hay xóa đi, qua
   `mattpocock-skills:domain-modeling`. Số đo vào Comments của ticket này và của discovery/07 trước khi ticket 02 lên
   `ready-for-agent`.

## Tiêu chí chấp nhận

- [ ] R9.2: planning p95 của truy vấn ba vị từ (custom và generic plan) và `CacheMemoryContext` mỗi backend của A1 ở
      modulus 8 có trong Comments kèm lệnh đo, cùng kết luận đạt hay trượt so với 5 ms và 64 MB và lợi ích bảo trì đo được
      so với modulus 4; sai nếu một số không có lệnh hay kế hoạch đi kèm, hay modulus 8 được chọn mà không có số của lợi
      ích bảo trì.
- [ ] R9.5: cùng các số đó của A0 tới A3 ở modulus 4 đặt cạnh modulus 8 trong một bảng, kèm modulus được chọn theo luật
      quyết của bước 7; sai nếu một biến thể chỉ có số ở một modulus.
- [ ] R9.4: tập slot đề xuất cho mỗi họ, kèm số chỉ mục trên một bảng (mọi chỉ mục của DDL A0 và A1, kể cả index
      `(tenant_id, workspace_id)` của FK tới workspace) và tỉ lệ HOT của A1 và A2; sai nếu tập slot không dẫn số đo nào.
- [ ] R9.4: UNIQUE từng phần trên `u01` của bảng partition, `ON CONFLICT` dưới policy theo lệnh, trigger `updated_at`
      trên partition, `CREATE EXTENSION unaccent` dưới `dw_migrator` và cột sinh `COLLATE "C"`: mỗi mục ghi chạy được
      hay không, kèm lỗi nguyên văn khi không.
- [ ] R9.1: trang đầu 50 dòng p95 ở mọi hồ sơ quyền và `GET` một bản ghi p95 trên seed T1, nóng và nguội, mỗi p95 trên ít
      nhất 1.000 mẫu, so với 50 ms và 5 ms, mỗi khẳng định "dùng chỉ mục" có `EXPLAIN (ANALYZE, BUFFERS)`; sai nếu đo ở
      quy mô nhỏ hơn D12 hay chỉ đo nóng.
- [ ] R9.1: `ORDER BY name` dưới RLS dùng chỉ mục và trả "An, Ánh, Ân, Bình, Đạt" đúng thứ tự; sai nếu kế hoạch có
      `Sort` trên cả tập khớp.
- [ ] R9.6: WAL bền vững của soak 2 giờ ở 200 lần ghi mỗi giây, tính cả bản ghi, outbox, audit và `studio.record_write_keys`,
      so với 20 MB/s; sai nếu lần đo bỏ một trong bốn nguồn ghi đó.
- [ ] R9.7: số dead tuple trên partition của T1 qua các vòng autovacuum trong soak và độ dài mỗi vòng, so với "không tăng
      dần" và 30 phút; sai nếu đo ngoài soak.
- [ ] R9.8: q-error p95 của lọc ba vị từ trên slot dùng chung (cột `t01` mang hai phân bố) so với 10, kèm truy vấn chậm
      nhất so với kế hoạch tốt nhất của nó; sai nếu chỉ đo trên đối tượng có một phân bố.
- [ ] R9.9: p95 trang đầu và `GET` của T2 trong lúc T1 nhập, vacuum và tổng hợp, so với ngưỡng của R9.1; sai nếu T2 không cùng partition với T1.
- [ ] R9.10: thời gian nhập 10^6 bản ghi qua RecordService, so với 1.000 hàng/s; sai nếu nhập đi vòng qua RecordService.
- [ ] R9.11: thời gian promote một trường từ `data` sang slot và purge một trường trên 10^7 hàng, cùng p95 nền trong lúc
      chạy, so với 2 giờ và 1,5 lần; sai nếu không có p95 nền.
- [ ] R9.12: p95 tạo bản ghi con của Campaign 10^5 con với 32 người ghi đồng thời trên A1, và lần chờ khóa dài nhất, so
      với 10 ms và 100 ms; sai nếu đo trên A0, nơi chưa có slot `l`, `m`.
- [ ] R9.2 (CO27): chạy kiểm bỏ chỉ mục btree `updated_at` của A1 → tỉ lệ HOT > 0; cho bộ đếm HOT trả 0 cố định →
      harness thoát khác 0; xóa `EXPLAIN (ANALYZE, BUFFERS)` của một khẳng định "dùng chỉ mục" khỏi báo cáo → harness thoát
      khác 0.
- [ ] Xong: `uv run python scripts/bench_records_storage.py --scale d12 --variants all` xanh.

## Nguồn

- `.claude/plans/studio/discovery/issues/07-records-storage.md:10-18`; spec: R9.1, R9.2, R9.4, R9.5.
- `.claude/plans/studio/discovery/issues/10-dedupe-and-upsert.md:14-15`; spec: R7.3.
- `db/migrations/sql/0001_platform_grants.sql:27-46`; `db/migrations/sql/0001_platform_baseline.sql:770`.
- `db/migrations/versions/0004_touch_updated_at_yields.py:44`; `infra/compose/docker-compose.yml:45`.
- ADR-0107 (Accepted) quyết 1, 2 và Open 2; ADR-0105 (Accepted) quyết 1, 3 và Consequences; ADR-0127 (Accepted) Open 1;
  spec: R9.6 tới R9.12, CO27; bản trả lời phản biện, mục 4.4 và 4.5 (V4.32).

## Comments

- 2026-10-23 (agent): DO-15 (a) đã quyết (Đạt, 23/10/2026): biến thể không partition thay bằng modulus 4, đường lui hợp D12; R9.3 bỏ, R9.5 thêm.
- 2026-10-24 (agent): máy đo trích YC20 (Đạt, 24/10/2026), một chủ cho máy tham chiếu mà record-access/01 cũng đo trên đó.
- 2026-10-24 (agent): vòng sửa 4, lượt bốn: DDL ứng viên của bước 2 gồm index `(tenant_id, workspace_id)` của FK tới workspace sở hữu, nên số chỉ mục, thời gian lập kế hoạch, HOT và WAL đo ở đây đã tính nó (Quyết định 24/10/2026 của spec).
- 2026-10-24 (agent): kiểm vòng sửa 4, lượt bốn: tiêu chí R9.4 đếm mọi chỉ mục của DDL ứng viên, kể cả index `(tenant_id, workspace_id)`, thay cho danh sách ba nhóm (chỉ mục danh sách, index đó, chỉ mục slot) bỏ sót khóa chính và UNIQUE từng phần của `create_key`, vì số chỉ mục, HOT và WAL đo trên cả bảng.
- 2026-10-25 (agent): lượt h, theo V4.32 của Đạt: ticket này là chủ duy nhất của harness, seed và tải mà record-access/01 dùng lại (seed T1 50 đối tượng thay cho 5 đối tượng × 10^7 và 99 công ty nhỏ của bước 3 cũ); DDL đo là A0 tới A3, C hẹp và JSONB ở modulus 8 và 4 thay cho hai biến thể chỉ có policy tenant; HOT đo A1 so với A2 thay cho "fillfactor 100 và 70", vì btree trên `updated_at` làm mọi UPDATE không HOT nên phép đo cũ chỉ ra được 0 (failure-modes #3; CO27); tải hỗn hợp và lần chạy nguội thay cho p95 của 20 lần nóng; ngưỡng đường ghi và bảo trì là R9.6 tới R9.12; modulus theo luật quyết mới (R9.2, R9.5). Tải sửa một trường ghi cả `studio.record_write_keys` của V4.30 (R5.9). Không thêm cạnh; record-access/01 nay chờ ticket này.
