# 01 — Đo nền lưu trữ bản ghi trước khi chốt ADR (partition, ngân sách slot, unaccent, InitPlan)

Status: resolved (2026-11-04, main)
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
    - Cấu hình đo là cấu hình host chạy: `infra/compose/docker-compose.yml` cộng `infra/compose/docker-compose.prod.yml`
      (PostgreSQL giới hạn 2 GB, `docker-compose.prod.yml:55-59`; mặc định của image cộng `wal_level=logical`,
      `docker-compose.yml:57`). Một cấu hình chỉnh tay chỉ là một dòng thêm của bảng số, không thay dòng đó, và dùng nó
      là một thay đổi của các tệp compose với quyết định riêng.
    - Máy tham chiếu chưa có: host hôm nay là 2 vCPU / 8 GB (`.claude/plans/studio/requirements.md:312`), và máy dev
      (Docker Desktop, VM 7,9 GB, khoảng 66 GB trống trên ổ hệ thống ngày 2/11/2026) không phải nó. Ở máy dev, harness,
      seed, tải, tự kiểm của bước 6 và các phép đo không phụ thuộc quy mô của bước 5 (mục "giữ các phép đo cũ", JSONB)
      chạy ở `--scale smoke` (10^6 bản ghi của T1, cùng hình dạng phân bố) trên một container PostgreSQL riêng của
      harness (cùng digest, cổng và volume riêng), không trên cluster dùng chung của các làn khác, vì lần chạy nguội khởi
      động lại PostgreSQL. Lần chạy `--scale d12` chờ máy tham chiếu do Đạt cấp; không số nào của máy dev thay số D12.
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
      (với khóa `wf:`, nên mỗi lần sửa ghi một dòng `studio.record_write_keys`, R5.9); 5% tạo mới.
    - RecordService và `RecordsPort` chưa có (ticket 03 dựng, sau ticket 02 chờ ticket này), nên mọi lần ghi của tải, của
      nhập (R9.10) và của R9.12 đi qua đường ghi mô phỏng của harness: một giao dịch dưới `dw_app` với đúng các câu lệnh
      ghi mà pipeline của ADR-0107 (Accepted) quyết 3 chạy, theo thứ tự: `pg_advisory_xact_lock_shared` trên (công ty,
      đối tượng), đọc `schema_version`, ghi `studio.records`, ghi `studio.record_write_keys` khi lệnh là sửa có khóa
      `wf:`, một dòng `platform.outbox_events` và một dòng `platform.audit_events`. Không COPY, không vai bỏ qua RLS,
      không bớt câu lệnh nào. Ticket 04 đo lại R9.6 và R9.10 qua RecordService thật.
    - Một soak 2 giờ ở 200 lần ghi mỗi giây; một lần chạy nguội sau khi khởi động lại PostgreSQL và xóa cache của hệ
      điều hành. Mỗi p95 trên ít nhất 1.000 mẫu, cả nóng lẫn nguội.
5. Đo theo ma trận sau, ngưỡng theo bảng mục 4.5 của bản trả lời (V4.32):
    - Ma trận: phép đọc (R9.1, R9.2, R9.8, R9.9) và tỉ lệ HOT trên A0 tới A3 ở cả hai modulus; soak 2 giờ, đường ghi và
      bảo trì (R9.6, R9.7, R9.10, R9.11, R9.12) trên A1 và C hẹp ở cả hai modulus, vì modulus 8 cần lợi ích bảo trì đo
      được so với 4; soak của A2, A3 và các bước sau của luật quyết (bước 7) chỉ chạy khi luật quyết tới bước đó, ở cả
      hai modulus. "Mỗi biến thể có số ở cả hai modulus" của bước 6 nói về mỗi ô của ma trận này.
    - trang đầu 50 dòng p95 ≤ 50 ms ở mọi hồ sơ quyền và `GET` p95 ≤ 5 ms (R9.1); tạo mới và sửa một trường p95 ≤ 10 ms
      (record-access:R9.5);
    - planning p95 của truy vấn ba vị từ trên ba slot khác họ (custom và generic plan, có và không có `tenant_id = $1`)
      ≤ 5 ms, `CacheMemoryContext` mỗi backend sau khi chạm mọi partition ≤ 64 MB (`pg_backend_memory_contexts`) (R9.2);
    - tỉ lệ HOT của lần sửa chỉ chạm `data`, A1 so với A2 (dự đoán A1 ≈ 0%, A2 > 0%);
    - WAL bền vững (R9.6), autovacuum (R9.7), q-error (R9.8), T2 khi T1 bận (R9.9), nhập qua đường ghi mô phỏng (R9.10),
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
   thì harness thoát khác 0. Mã thoát chỉ nói phép đo có thấy và có đủ không: một ngưỡng trượt không làm harness thoát
   khác 0, mà thành dòng "trượt" trong bảng số để luật quyết của bước 7 đọc.
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
- [x] R9.4: UNIQUE từng phần trên `u01` của bảng partition, `ON CONFLICT` dưới policy theo lệnh, trigger `updated_at`
      trên partition, `CREATE EXTENSION unaccent` dưới `dw_migrator` và cột sinh `COLLATE "C"`: mỗi mục ghi chạy được
      hay không, kèm lỗi nguyên văn khi không.
- [ ] R9.1: trang đầu 50 dòng p95 ở mọi hồ sơ quyền và `GET` một bản ghi p95 trên seed T1, nóng và nguội, mỗi p95 trên ít
      nhất 1.000 mẫu, so với 50 ms và 5 ms, mỗi khẳng định "dùng chỉ mục" có `EXPLAIN (ANALYZE, BUFFERS)`; sai nếu đo ở
      quy mô nhỏ hơn D12 hay chỉ đo nóng.
- [x] R9.1: `ORDER BY name` dưới RLS dùng chỉ mục và trả "An, Ánh, Ân, Bình, Đạt" đúng thứ tự; sai nếu kế hoạch có
      `Sort` trên cả tập khớp.
- [ ] R9.6: WAL bền vững của soak 2 giờ ở 200 lần ghi mỗi giây, tính cả bản ghi, outbox, audit và `studio.record_write_keys`,
      so với 20 MB/s; sai nếu lần đo bỏ một trong bốn nguồn ghi đó.
- [ ] R9.7: số dead tuple trên partition của T1 qua các vòng autovacuum trong soak và độ dài mỗi vòng, so với "không tăng
      dần" và 30 phút; sai nếu đo ngoài soak.
- [ ] R9.8: q-error p95 của lọc ba vị từ trên slot dùng chung (cột `t01` mang hai phân bố) so với 10, kèm truy vấn chậm
      nhất so với kế hoạch tốt nhất của nó; sai nếu chỉ đo trên đối tượng có một phân bố.
- [ ] R9.9: p95 trang đầu và `GET` của T2 trong lúc T1 nhập, vacuum và tổng hợp, so với ngưỡng của R9.1; sai nếu T2 không cùng partition với T1.
- [ ] R9.10: thời gian nhập 10^6 bản ghi qua đường ghi mô phỏng của bước 4, so với 1.000 hàng/s; sai nếu lần nhập dùng
      COPY, một vai bỏ qua RLS hay bớt một câu lệnh của giao dịch đó.
- [ ] R9.11: thời gian promote một trường từ `data` sang slot và purge một trường trên 10^7 hàng, cùng p95 nền trong lúc
      chạy, so với 2 giờ và 1,5 lần; sai nếu không có p95 nền.
- [ ] R9.12: p95 tạo bản ghi con của Campaign 10^5 con với 32 người ghi đồng thời trên A1, và lần chờ khóa dài nhất, so
      với 10 ms và 100 ms; sai nếu đo trên A0, nơi chưa có slot `l`, `m`.
- [x] R9.2 (CO27): chạy kiểm bỏ chỉ mục btree `updated_at` của A1 → tỉ lệ HOT > 0; cho bộ đếm HOT trả 0 cố định →
      harness thoát khác 0; xóa `EXPLAIN (ANALYZE, BUFFERS)` của một khẳng định "dùng chỉ mục" khỏi báo cáo → harness thoát
      khác 0.
- [x] R9.2 (CO27): một ngưỡng trượt (ví dụ đặt ngưỡng planning 0 ms) → harness vẫn thoát 0 và bảng số ghi dòng đó
      "trượt"; một ô của ma trận bước 5 thiếu số → harness thoát khác 0.
- [ ] R9.1: lần chạy `--scale d12` ở dòng Xong chạy trên máy tham chiếu của bước 1, và mã thoát 0 của nó nghĩa là đủ ô
      của ma trận bước 5 và tự kiểm của bước 6 đạt; sai nếu số D12 đến từ máy dev hay từ cluster dùng chung.
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
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness`, chỉ kiểm người dựng (ticket không thêm revision Alembic hay route; DDL đo nằm trong `scripts/bench_records_storage/` trên database `dw_bench` riêng; không đi ranh giới), ở `d85e0d2`. Neo của Nguồn và Hiện trạng còn đúng; `check_plans.py` 23 Đạt, 1 cảnh báo collision của ticket 06 với 03, không của ticket này. 0 CRITICAL, 5 HIGH, đã sửa như dưới.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 1: máy tham chiếu của YC20 (host đã nâng theo D14) chưa có, host hôm nay 2 vCPU / 8 GB (`requirements.md:312`); máy dev đo ngày 2/11/2026 là Ryzen 7 7735U 8 nhân, 15,2 GB RAM, VM Docker Desktop 7,9 GB, khoảng 66 GB trống trên C:, chưa đủ cho seed D12 ước 75 tới 100 GB mỗi lần dựng một biến thể (ước tính, chưa đo); và lần chạy nguội khởi động lại PostgreSQL, nên nếu chạy trên cluster dùng chung thì làm hỏng test của các làn khác. Sửa: bước 1 nói máy dev chạy harness, tự kiểm và các phép đo không phụ thuộc quy mô ở `--scale smoke` trên container riêng của harness, còn lần `--scale d12` chờ máy tham chiếu do Đạt cấp; Xong nêu máy đó. Nếu sai thì: Đạt chỉ định máy khác (dòng Quyết định 23/10/2026 của spec, "đo lại trên máy Đạt chỉ định"), và bước 1 ghi máy đó.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 2: ticket bảo ghi các dòng `postgresql.conf` khác mặc định mà không nói đo với cấu hình nào, trong khi host chạy PostgreSQL giới hạn 2 GB với cấu hình mặc định của image (`docker-compose.prod.yml:55-59`, `docker-compose.yml:57`; đo ngày 2/11/2026: `shared_buffers` 128MB, `work_mem` 4MB); số đo với cấu hình chỉnh tay không đúng cho host. Sửa: bước 1 đo với base cộng overlay prod, cấu hình chỉnh tay chỉ là một dòng thêm và dùng nó cần quyết định riêng. Nếu sai thì: đo với cấu hình Đạt đặt, và cấu hình đó vào tệp compose trước lần đo.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 3: tải 15% sửa đi "qua `RecordsPort`", R9.10 "nhập qua RecordService; sai nếu nhập đi vòng qua RecordService", nhưng cả hai chưa có (không có trong `packages/` hay `apps/` ở `d85e0d2`; ticket 03 dựng chúng sau ticket 02, mà ticket 02 chờ ticket này), nên tiêu chí R9.10 không đạt được. Sửa: bước 4 định nghĩa đường ghi mô phỏng theo pipeline của ADR-0107 (Accepted) quyết 3 (khóa advisory, `schema_version`, bản ghi, `studio.record_write_keys`, `platform.outbox_events`, `platform.audit_events`, một giao dịch dưới `dw_app`), tiêu chí R9.10 đổi theo, và ticket 04 (bước 6, R9.6, R9.10) đo lại qua RecordService thật. Nếu sai thì: ticket 03 đo lại R9.6 và R9.10, và ticket 04 trở về chỉ R9.1.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 4: bước 5 nói "cho mỗi biến thể và modulus" cả soak 2 giờ, promote và purge trên 10^7 hàng, trong khi bảng R9 của spec đo đường ghi trên A1 và luật quyết chỉ thử A2, A3 khi đường ghi của A1 trượt; đoán sai thì thời gian máy gấp bốn tới tám lần hoặc thiếu số cho luật quyết modulus. Sửa: ma trận ở đầu bước 5 (đọc và HOT trên A0 tới A3, đường ghi và bảo trì trên A1 và C hẹp, cả hai modulus; A2, A3 chỉ khi luật quyết tới). Nếu sai thì: soak chạy trên mọi biến thể ở cả hai modulus, và bước 1 ghi thời gian máy ước tính.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 5: dòng Xong "xanh" không nói một ngưỡng trượt có làm harness thoát khác 0 không; nếu có thì ticket không đóng được đúng khi luật quyết cần A2, A3 hay modulus 4. Sửa: bước 6 nói mã thoát chỉ phản ánh tự kiểm và đủ ô, ngưỡng trượt thành dòng "trượt"; thêm tiêu chí CO27 cho hai ca đó; Xong nêu nghĩa của mã thoát 0. Nếu sai thì: harness có cờ `--strict` làm ngưỡng trượt thoát khác 0, và Xong chạy không có cờ đó.
- 2026-11-02 (agent): MEDIUM, chưa sửa, cho người dựng: (a) `pg_backend_memory_contexts` không đọc được bằng `dw_app` (đo ngày 2/11/2026: `has_table_privilege('dw_app', 'pg_backend_memory_contexts', 'SELECT')` là false; PostgreSQL 16 chỉ cho superuser và `pg_read_all_stats`), nên đo `CacheMemoryContext` trong một phiên superuser `SET ROLE dw_app`, chạy truy vấn chạm mọi partition, `RESET ROLE` rồi đọc view trong cùng backend, hay `pg_log_backend_memory_contexts(pid)`; không cấp `pg_read_all_stats` cho `dw_app`, vì vai đó dùng chung cả cluster. (b) Bảng mà DDL đo cần nhưng chưa có ở migration head: `studio.artifacts` (tenant-config/02), nhóm, cây quản lý, chia sẻ, quy tắc chia sẻ, `studio.principal_scopes` và hàm `studio.acl_*` (record-access); DDL của harness mang bản thay tối thiểu dưới `scripts/bench_records_storage/`, mảng tầm của mỗi chủ thể tính sẵn bởi bộ gieo theo hình của ADR-0105 (Accepted) quyết 4; chi phí tính tầm là của record-access/01. (c) Mẫu nguội chưa định nghĩa: đề xuất sau khi khởi động lại container và `sync; echo 3 > /proc/sys/vm/drop_caches` (host Linux; trên Docker Desktop qua một container `--privileged`), mỗi hồ sơ quyền 1.000 khóa ngẫu nhiên chưa đọc từ lần khởi động lại. (d) Mục tổng hợp với `studio.acl_*` PARALLEL SAFE dẫn ADR-0127 (Accepted) Open 1, nhưng Open 1 là ngưỡng PA3 theo số của discovery/30 và ADR không nói PARALLEL SAFE; hình truy vấn tổng hợp (cả cho R9.9) chưa nêu: đề xuất `count(*) GROUP BY t01` và `sum(i01) GROUP BY date_trunc('month', z01)` trên `mkt_lead` ở hồ sơ Toàn công ty, dẫn `.claude/plans/studio/discovery/issues/30-aggregate-queries-under-rls.md`. (e) Bước 7 bảo thay số "3 lần và 3,4 lần" của ADR-0107 (Accepted), nhưng sửa đổi 25/10/2026 của ADR đã bỏ hai số đó; số của C hẹp vào một mục sửa đổi mới. (f) "bảng mục 4.5 của bản trả lời (V4.32)" không có trong repo; ngưỡng có chủ là R9.1, R9.2, R9.6 tới R9.12 của spec. (g) Không nói gì xóa `dw_bench` (failure-modes #6): đề xuất DROP sau mỗi ô của ma trận và khi thoát, dữ liệu dựng lại từ `seed(scale)`; bước 1 ghi chỗ trống trên đĩa trước lần chạy. (h) Neo `infra/compose/docker-compose.yml:45` là dòng `postgres:`, image ở dòng 46 (`postgres:16.15-alpine@sha256:0cefaabd...`, đã ghim digest; CI dùng cùng tệp, `.github/workflows/ci.yml:254`).
- 2026-11-02 (agent): đo sẵn ở compose ngày 2/11/2026 (PostgreSQL 16.15), cho mục "giữ các phép đo cũ": `CREATE EXTENSION unaccent` dưới `dw_migrator` chạy được (`unaccent` 1.1 là extension tin cậy; chạy trong giao dịch rồi ROLLBACK); collation `vi-VN-x-icu` có và `ORDER BY` trả "An, Ánh, Ân, Bình, Đạt"; `dw_migrator` có CREATEDB (`infra/compose/init/init-databases.sh:9`). Chưa đo: chỉ mục có được dùng dưới RLS, cột sinh `COLLATE "C"`, CI.
- 2026-11-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent. Harness, seed, tải và tự kiểm dựng và chạy được ở máy dev (`--scale smoke`); lần chạy `--scale d12` và dòng Xong chờ máy tham chiếu của YC20 do Đạt cấp.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): đóng ở `--scale smoke` trên máy dev. Lần chạy `--scale d12`, các tiêu chí chỉ máy tham chiếu chứng minh được (R9.1 trang đầu và GET ở D12, R9.2, R9.5, R9.4 tập slot, R9.6 tới R9.12, R9.1 lần chạy d12) và dòng Xong tách sang ticket 08 (`ready-for-human`, Chờ Đạt 23), như record-access/01 đã tách sang record-access/06; ticket 07 và record-access/06 đọc kết luận ở ticket 08. Nếu sai thì: ticket 08 gộp lại, ticket này mở lại tới khi có máy.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): modulus 8 là lần chạy smoke thứ ba ngày 3/11/2026 (template ở head trước tenant-config/02, `studio.artifacts` còn là bản thay); modulus 4 chạy lại ngày 4/11/2026 ở head có `studio.artifacts` thật (revision 67071483caa6), sau khi bản thay bị bỏ vì DDL của harness đụng bảng thật (`DuplicateTableError: relation "artifacts" already exists`, cả năm ô). Mã harness của hai lần giống nhau trừ chỗ đó; bảng đó chỉ là đích FK của `studio.object_defs`, không nằm trên đường đọc hay ghi bản ghi. Hai báo cáo gộp bằng chính `Report` của harness: đủ ô ở cả hai modulus, mã thoát gộp 0. Nếu sai thì: chạy lại modulus 8 ở head (khoảng 2,5 giờ) và thay cột m8.
- 2026-11-04 (agent): máy dev, không phải máy tham chiếu: Windows 11, Ryzen 7 7735U 16 luồng, Docker Desktop VM 16 CPU 7,9 GB, ổ còn 64 tới 66 GB; container riêng `dwbench-postgres` (127.0.0.1:25442), `postgres:16.15-alpine@sha256:0cefaabd882e42bcb2a2f3dc56d3ce4770560ba62fd7f197f1a2e008fd5731ab`, giới hạn 2 GiB của overlay prod, `wal_level=logical`, `shared_buffers` 128MB, `work_mem` 4MB, mọi dòng khác mặc định của image (locale, `dynamic_shared_memory_type=posix`); riêng smoke: `autovacuum_vacuum_scale_factor` và `autovacuum_vacuum_insert_scale_factor` 0,008 trên partition của T1 vì soak rút 24 lần. Seed: T1 10^6 bản ghi trên 50 object, T2 cùng partition với T1 ở mọi ô. Vòng khứ hồi `SELECT 1` p50 0,75 tới 1,61 ms.
- 2026-11-04 (agent): hai phát hiện mà harness đã mang theo. (1) Compose không đặt `shm_size`, nên /dev/shm là 64 MB của Docker; `CREATE INDEX` và VACUUM song song xin 64 MB bộ nhớ chia sẻ động và vỡ với "could not resize shared memory segment"; mọi phiên của harness đặt `max_parallel_maintenance_workers = 0` (autovacuum không bao giờ song song), host chạy có cùng giới hạn. (2) Bảng khóa chung có 6.400 chỗ (`max_locks_per_transaction` 64 x `max_connections` 100); một giao dịch trang đầu giữ 217 khóa quan hệ với custom plan và 894 với generic plan ở modulus 8 (A1; A0 173/768, A3 201/822), 217 và 498 ở modulus 4 (A0 173/428, A3 201/458), nên 50 phiên trên generic plan vượt bảng khóa và trả "out of shared memory" (23 lỗi trong soak của A1 m8). Hai điều này cần quyết định riêng trên tệp compose trước D12 (ticket 08).
- 2026-11-04 (agent): bảng số smoke, mỗi ô của ma trận ở cả hai modulus (ms trừ khi ghi khác; `*` dừng sớm vì hơn 5% của 1.000 mẫu đã trên ngưỡng, ✓ đạt, ✗ trượt; dòng trang và GET là p95 thấp nhất tới cao nhất qua 16 hồ sơ, kèm hồ sơ tệ nhất):

  | Chỉ số | A0 m8 | A1 m8 | A2 m8 | A3 m8 | C m8 | A0 m4 | A1 m4 | A2 m4 | A3 m4 | C m4 |
  | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
  | page_warm p95 ms (thấp–cao) | 124–18568 (team_sort_slot) | 189–50117 (manager_5000) | 133–59161 (manager_5000) | 244–59654 (manager_5000) | — | 143–21341 (workspace_40) | 121–45595 (manager_5000) | 104–∞ (manager_5000) | 120–44341 (manager_5000) | — |
  | page_cold p95 ms (thấp–cao) | 129–15559 (team_sort_slot) | 273–20049 (own_sort_slot) | 219–13041 (own_sort_slot) | 204–17135 (own_sort_slot) | — | 87–14792 (team_sort_slot) | 114–13363 (own_sort_slot) | 123–11477 (own_sort_slot) | 117–11794 (own_sort_slot) | — |
  | get_warm p95 ms (thấp–cao) | 116–2083 (workspace_1) | 136–2350 (workspace_1) | 108–2628 (agent_one_object) | 122–4435 (agent_one_object) | — | 39–2808 (manager_5000) | 59–1218 (workspace_40) | 76–993 (service_account) | 61–1176 (share_recipient) | — |
  | get_cold p95 ms (thấp–cao) | 117–1436 (company_name) | 127–2725 (public_read) | 63–2133 (workspace_40) | 106–2212 (service_account) | — | 52–1085 (public_read) | 80–1128 (workspace_40) | 54–1197 (company_name) | 44–804 (workspace_40) | — |
  | write_update_p95 | 438.1* ✗ | 602.4* ✗ | 506.6* ✗ | 603.2* ✗ | — | 411.5* ✗ | 387.1* ✗ | 326.7* ✗ | 306.7* ✗ | — |
  | write_create_p95 | 500.7* ✗ | 457.3* ✗ | 327.9* ✗ | 491.3* ✗ | — | 364.7* ✗ | 310* ✗ | 252.7* ✗ | 307.8* ✗ | — |
  | planning_custom_tenant | 2.591 ✓ | 3.287 ✓ | 3.559 ✓ | 3.243 ✓ | — | 2.115 ✓ | 2.438 ✓ | 1.911 ✓ | 1.883 ✓ | — |
  | planning_custom_no_tenant | 16.48 ✗ | 24.33 ✗ | 19.36 ✗ | 20.73 ✗ | — | 6.231 ✗ | 8.756 ✗ | 5.234 ✗ | 6.051 ✗ | — |
  | planning_generic_tenant | 17.79 ✗ | 24.31 ✗ | 26.64 ✗ | 22.65 ✗ | — | 7.39 ✗ | 8.35 ✗ | 6.698 ✗ | 6.457 ✗ | — |
  | planning_generic_no_tenant | 17.32 ✗ | 25.53 ✗ | 20.5 ✗ | 21.23 ✗ | — | 6.935 ✗ | 8.982 ✗ | 5.654 ✗ | 6.429 ✗ | — |
  | cache_memory_mb | 12 ✓ | 12.6 ✓ | 12.6 ✓ | 12.39 ✓ | — | 6.27 ✓ | 6.91 ✓ | 6.91 ✓ | 6.8 ✓ | — |
  | qerror_p95 | 1014 ✗ | 886 ✗ | 881.6 ✗ | 868.5 ✗ | — | 1102 ✗ | 913.4 ✗ | 912.2 ✗ | 926 ✗ | — |
  | slowest_vs_best | 3.34 ✓ | 4.73 ✓ | 1.86 ✓ | 1.6 ✓ | — | 1.83 ✓ | 2.06 ✓ | 1.76 ✓ | 2.4 ✓ | — |
  | t2_page_busy | 754.5* ✗ | 364.8* ✗ | 314.3* ✗ | 94.52* ✗ | — | 67.2* ✗ | 263.3* ✗ | 55.52* ✗ | 56.64* ✗ | — |
  | t2_get_busy | 942.8* ✗ | 1097* ✗ | 1024* ✗ | 1266* ✗ | — | 412.7* ✗ | 390.8* ✗ | 283.8* ✗ | 332.8* ✗ | — |
  | hot_ratio | 0 | 0 | 0.9445 | 0 | — | 0 | 0 | 0.9555 | 0 | — |
  | wal_mb_per_s | — | 13.4 ✓ | — | — | 6.286 ✓ | — | 15.51 ✓ | — | — | 10.47 ✓ |
  | soak_writes_per_s | — | 70.1 | — | — | 99.1 | — | 80.8 | — | — | 166.7 |
  | dead_tuple_growth | — | 3.53 ✗ | — | — | 1.276e+04 ✗ | — | 4.64 ✗ | — | — | 6889 ✗ |
  | autovacuum_cycle_max_min | — | 0 ✗ | — | — | 0 ✗ | — | 0.03 ✓ | — | — | 0 ✗ |
  | import_rows_per_s | — | 198.6 ✗ | — | — | 74.1 ✗ | — | 269.8 ✗ | — | — | 118.7 ✗ |
  | promote_hours | — | 0.4085 ✓ | — | — | 0.0704 ✓ | — | 0.3426 ✓ | — | — | 0.0356 ✓ |
  | purge_hours | — | 0.3282 ✓ | — | — | 0.0195 ✓ | — | 0.3241 ✓ | — | — | 0.0138 ✓ |
  | promote_background_ratio | — | 1.28 ✓ | — | — | 1.25 ✓ | — | 1.16 ✓ | — | — | 1.05 ✓ |
  | purge_background_ratio | — | 1.05 ✓ | — | — | 1.05 ✓ | — | 1.16 ✓ | — | — | 1.09 ✓ |
  | campaign_create_p95 | — | 214.4 ✗ | — | — | 496.8 ✗ | — | 163.3 ✗ | — | — | 681.5 ✗ |
  | lock_wait_max_ms | — | 13.02 ✓ | — | — | 142.5 ✗ | — | 13.9 ✓ | — | — | 47.37 ✓ |

- 2026-11-04 (agent): phép đo cũ, đo ở A1 cả hai modulus: `ORDER BY name` dưới RLS dùng `records_p*_tenant_id_object_id_name_id_idx`, không Sort trên cả tập khớp, trả "An, Ánh, Ân, Bình, Đạt"; policy InitPlan trang đầu/GET p95 15,0/13,3 ms (m8), 10,9/6,6 ms (m4), dạng đọc setting từng dòng 16,5/13,7 và 9,3/5,4 ms (một phiên, 1.000 mẫu); `pg_advisory_xact_lock_shared` thêm 0,06 tới 0,24 ms mỗi giao dịch ghi; `ON CONFLICT ... DO UPDATE` dưới policy theo lệnh chạy được (lần 1 version 1, lần 2 version 2), còn `RETURNING (xmax = 0)` trên bảng partition lỗi nguyên văn "cannot retrieve a system column in this context", nên thêm hay sửa đọc từ `version = 1`; trigger `platform.touch_updated_at()` trên bảng cha chạy cho dòng ở partition và nhường giá trị câu lệnh nêu; `CREATE EXTENSION unaccent` dưới `dw_migrator` chạy được (1.1); cột STORED `name_key` `COLLATE "C"` từ hàm IMMUTABLE chạy được (`search_key('Đạt Ánh Nguyễn')` = 'dat anh nguyen'); `reltuples` của partition lệch 0,5 tới 0,9% và không tách được T1 (14 và 27 tenant chung partition), nên hạn mức cần dòng bộ đếm; JSONB: `jsonb_object_field_text` và `jsonb_contains` không LEAKPROOF, kế hoạch không dùng GIN trên `data`, lý do loại đứng; tổng hợp PARALLEL SAFE có Gather và nhanh gần gấp đôi (821/701 so với 1.705/1.451 ms ở m8), kết quả bằng nhau.
- 2026-11-04 (agent): tự kiểm CO27: bỏ btree `updated_at` của A1 cho HOT 0,9555 (m8) và 0,961 (m4) trên 2.000 lần sửa chỉ chạm `data`, trong khi A1 có btree đó cho 0 và A2 (BRIN) cho 0,9445 và 0,9555: bộ đếm thấy. Test của harness (`records_bench/tests`, 30, nay trong testpaths với marker unit nên CI chạy) chứng minh bộ đếm mù, khẳng định thiếu `EXPLAIN (ANALYZE, BUFFERS)`, ô thiếu số và một modulus đều thoát 1, ngưỡng trượt vẫn thoát 0; `mutations/01.yaml` 14 đột biến, áp được, chưa chạy (chờ đóng hàng đợi).
- 2026-11-04 (agent): luật quyết bước 7 trên bảng gộp smoke: A1 trượt ngưỡng đọc ở cả hai modulus (trang đầu, GET, ghi dưới 50 phiên trên máy dev, q-error, planning generic), nên ở smoke luật nói "quay lại người đặt yêu cầu (DO-15)" và không chọn modulus; lợi ích bảo trì của 8 so với 4: promote +19%, purge +1% (8 không tốt hơn), vòng autovacuum không đo được ở m8; BRIN (A2) có HOT nhưng trang mới cập nhật p95 18 và 15 giây nên giữ btree. Đây là số smoke trên máy dev quá tải ở 50 phiên, không thay số D12 và không mở DO-15: quyết định chờ ticket 08.
- 2026-11-04 (agent): resolved. Không revision, không route. Cổng: ruff, format, mypy (harness), 30 test của harness xanh. Container `dwbench-postgres` và volume của nó đã xóa. Commit `5ad9dff` (harness), commit đóng ticket này.
