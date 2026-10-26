# 01 — Đo hình dạng RLS cho quyền trên bản ghi trước khi khóa thiết kế

Status: needs-triage
Blocked by: .claude/plans/studio/custom-objects/issues/01-do-nen-luu-tru-ban-ghi.md
Area: studio
Yêu cầu: R9.1, R9.2, R9.3, R9.4, R9.5, R9.6, R9.7, R9.8, R9.9

## Mục tiêu

Mẫu policy của ticket 03 chỉ được khóa khi đã đo ở quy mô D12. Ticket này đo bộ policy RESTRICTIVE tenant cộng
PERMISSIVE theo lệnh của ADR-0105 (Accepted) mục 1, với đủ sáu nhánh tầm (mặc định toàn tenant, khóa workspace, của
tôi, của nhóm, cấp dưới, khóa chia sẻ) dù W1 chỉ dùng ba, để W2 thêm nhánh mà không đổi hình. Ticket đo trên đúng
harness, seed và tải của custom-objects/01, chủ duy nhất của chúng, cùng đủ chỉ mục slot của biến thể A1, và chỉ thêm
biến thể chính sách (V4.32; ADR-0105 (Accepted) Consequences; ADR-0107 (Accepted) quyết 2). Kết quả cho từng dòng R9.1
tới R9.9 một con số, hay một phương án đã đo đạt ngưỡng.

## Việc cần làm

1. Dùng `scripts/bench_records_storage.py`, DDL A1 dưới `scripts/bench_records_storage/` và `seed(scale)` của
   custom-objects/01 không đổi: không schema nháp riêng, không bộ gieo riêng, không chép harness. Ticket này thêm biến
   thể chính sách dưới `scripts/bench_records_storage/policy/` và target `make bench-record-access` gọi harness với các
   biến thể đó. Mỗi biến thể là A1 với policy sáu nhánh viết khác: `access_key` `uuid` từ md5 của object và workspace
   sở hữu, hay `bigint` ghép hai số nhỏ theo tenant; mảng theo nhánh trong một dòng sổ tầm, hay một dòng cho mỗi hành
   động; join bảng sổ tầm, `EXISTS`, hay mảng khóa trên bản ghi; có và không có câu gợi ý cho planner
   (`AND owner_id = <chủ thể>` dựng từ cùng hàm `studio.acl_*`). Sổ tầm và các hàm `studio.acl_*` (`LANGUAGE sql STABLE`,
   SECURITY INVOKER, `search_path` cố định, trả mảng rỗng khi thiếu), mọi setting và mảng đọc ở dạng
   `(SELECT f())::uuid[]`, nhánh loại actor và giới hạn dữ liệu.
2. Dữ liệu là seed T1, T2 và 98 tenant nhỏ của custom-objects/01, gồm 300 nhóm, cây quản lý sâu 8, chia sẻ tay trên
   0,4% và 5% bản ghi (hai lần chạy), 50 phiên bản quy tắc chia sẻ khớp 10% lead và tài khoản dịch vụ sở hữu 10^6 lead;
   ticket này không gieo dòng nào ngoài dòng sổ tầm mà biến thể chính sách của nó đọc, gieo bằng cùng hạt giống.
3. Hồ sơ quyền là danh sách của custom-objects/01 (Của tôi; Của nhóm tôi; Workspace của tôi; Workspace của tôi và cấp
   dưới trên 40 workspace; Toàn công ty; `public_read` trên `mkt_lead`; quản lý có 50, 500 và 5.000 cấp dưới; người nhận
   500 chia sẻ; agent có giới hạn dữ liệu một object; tài khoản dịch vụ tiếp nhận).
4. Dưới tải hỗn hợp của custom-objects/01 (50 phiên, 80/15/5, soak 2 giờ ở 200 lần ghi mỗi giây, một lần chạy nguội),
   đo cho mỗi hồ sơ và mỗi biến thể chính sách p50, p95, p99 trên ít nhất 1.000 mẫu, nóng và nguội, kèm
   `EXPLAIN (ANALYZE, BUFFERS)`: trang đầu 50 dòng có và không có bộ lọc trên cột slot kiểu; trang keyset kế tiếp; tra
   một bản ghi theo id; đếm có trần `LIMIT 1001`; INSERT; UPDATE một cột slot; giao (đổi người phụ trách và workspace
   sở hữu); chia sẻ; DELETE. Cộng: thời gian tính sổ tầm một chủ thể; cửa sổ tầm khi dòng còn hiệu lực; tính lại 5.000
   chủ thể sau một lần tăng epoch; một thu hồi commit giữa hai câu lệnh đọc trên hai kết nối; hành vi cắt partition và
   InitPlan dưới RESTRICTIVE cộng PERMISSIVE.
5. So sánh và ghi phương án thắng của mỗi trục ở bước 1. Máy tham chiếu là máy của custom-objects/01 (máy YC20, host
   chính sau D14, ảnh ghim digest). Ghi máy, phiên bản, cấu hình `postgresql.conf` khác mặc định, số đo và kế hoạch vào
   `db/bench/record-access/RESULTS.md`; chép bảng số đo và hình dạng được chọn vào mục Consequences của
   `docs/adr/0105-record-reach-is-decided-by-postgresql.md` qua `mattpocock-skills:domain-modeling`, và vào Comments của
   ticket này.
6. Tự kiểm trong script: thoát mã khác 0 khi một phiên không gắn tenant, không gắn loại actor, không có dòng sổ tầm,
   mang epoch cũ, hay chạy trên một policy tạo hỏng mà vẫn ra dòng, khi một dòng của T2 xuất hiện trong phiên của T1,
   và khi một biến thể chính sách chạy trên DDL khác A1 của custom-objects/01.

## Tiêu chí chấp nhận

- [ ] R9.1: trang đầu 50 dòng, có và không có bộ lọc, đạt p95 ≤ 50 ms với mọi hồ sơ của bước 3 trên máy tham chiếu,
      nóng và nguội, trên DDL A1; hồ sơ nào trượt có một phương án đã đo đạt ngưỡng trong `RESULTS.md`, không phải một
      ghi chú; sai nếu số đo trên seed hay harness khác của custom-objects/01.
- [ ] R9.1: script tự kiểm của bước 6 thoát khác 0 khi bỏ mệnh đề tenant khỏi policy RESTRICTIVE (kiểm chéo tenant
      đỏ), khi bỏ điều kiện `grants_valid_until` khỏi nhánh chia sẻ (kiểm hết hạn đỏ) và khi trỏ biến thể chính sách vào
      DDL A0; lần chạy ghi trong Comments.
- [ ] R9.2: tra một bản ghi theo id đạt p95 ≤ 5 ms với mọi hồ sơ, kể cả tài khoản dịch vụ sở hữu 10^6 lead.
- [ ] R9.3: trang keyset kế tiếp đạt p95 ≤ 50 ms với mọi hồ sơ.
- [ ] R9.4: đếm có trần `LIMIT 1001` đạt p95 ≤ 300 ms với mọi hồ sơ.
- [ ] R9.5: INSERT một bản ghi và UPDATE một cột slot đạt p95 ≤ 10 ms dưới WITH CHECK của policy, trong soak của
      custom-objects/01.
- [ ] R9.6: giao một bản ghi đạt p95 ≤ 20 ms; chia sẻ tay đo và ghi cùng bảng cho W2.
- [ ] R9.7: tính sổ tầm cho một chủ thể đạt p95 ≤ 50 ms, kể cả quản lý có 5.000 cấp dưới.
- [ ] R9.8: cửa sổ tầm khi dòng sổ tầm còn hiệu lực đạt p95 ≤ 1 ms.
- [ ] R9.9: tính lại sổ tầm của 5.000 chủ thể sau một lần tăng epoch xong trong ≤ 120 s tổng; thu hồi trên hai kết
      nối không bao giờ để câu lệnh sau commit thấy tầm cũ.
- [ ] Xong: `make bench-record-access` xanh.

## Nguồn

- `docs/adr/0105-record-reach-is-decided-by-postgresql.md:31-33`; spec: R9.
- `docs/adr/0105-record-reach-is-decided-by-postgresql.md:134-139`; spec: R9 (V4.32: một harness, một seed).
- `db/migrations/sql/0001_platform_baseline.sql:770` (policy tenant chưa ở dạng InitPlan); spec: R9.1.
- `.claude/plans/studio/custom-objects/issues/01-do-nen-luu-tru-ban-ghi.md` (harness, seed, tải, hồ sơ quyền);
  ADR-0107 (Accepted) quyết 2.

## Comments

- 2026-10-23 (agent): cỡ dữ liệu theo D12 (người yêu cầu, 23/10/2026), trả lời DO-14: 10 triệu bản ghi mỗi object,
  50 triệu mỗi tenant, 5.000 người, 200 workspace, cây sâu 6.
- 2026-10-24 (agent): máy đo là máy tham chiếu của YC20 (host chính sau D14), cùng máy của custom-objects/01, thay máy
  2 vCPU, 8 GB của quyết tạm ngày 23/10/2026 (Đạt, 24/10/2026).
- 2026-10-25 (agent): lượt h, theo V4.32 của Đạt: ticket dùng lại harness, seed, tải và hồ sơ quyền của
  custom-objects/01 và chỉ thêm biến thể chính sách, thay cho schema nháp `db/bench/record-access/` với vài cột slot và
  bộ gieo riêng của bước 1 và 2 cũ, nên policy sáu nhánh được đo cùng đủ chỉ mục slot của A1 (bản trả lời phản biện, mục
  4.4 điểm 3 và 4); p95 trên ít nhất 1.000 mẫu nóng và nguội thay cho 20 lần sau một lần làm ấm. Blocked by thêm
  custom-objects/01, cạnh ngoài bảng mục B, đã chạy g.py: không đổi độ sâu của `marketing-pilot/03` (15) hay chuỗi dài
  nhất (18).
