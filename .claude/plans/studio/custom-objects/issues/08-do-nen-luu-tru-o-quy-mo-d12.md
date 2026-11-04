# 08 — Đo nền lưu trữ bản ghi ở quy mô D12 trên máy tham chiếu

Status: ready-for-human (Chờ Đạt 23: máy tham chiếu của YC20)
Blocked by: 01
Area: studio
Yêu cầu: R9.1, R9.2, R9.4, R9.5, R9.6, R9.7, R9.8, R9.9, R9.10, R9.11, R9.12, CO27

## Mục tiêu

Ticket 01 dựng harness, seed, tải và tự kiểm của phép đo lưu trữ bản ghi và chạy chúng ở `--scale smoke` trên máy dev
(số trong Comments của ticket 01, không phải số D12). Ticket này chạy cùng lệnh ở `--scale d12` trên máy tham chiếu mà
YC20 định nghĩa (host chính sau D14), xét từng dòng có ngưỡng, áp luật quyết bước 7 của ticket 01, và ghi số cùng kết
luận để ticket 07 đưa DDL của `studio.records` về đúng kết luận đó (R9.1, R9.2, R9.4, R9.5; ADR-0107 (Accepted) quyết 1,
2). Phần của người là cấp máy (Chờ Đạt 23); phần còn lại agent chạy được khi có máy.

## Việc cần làm

1. Đạt cấp máy tham chiếu và cách vào nó; agent ghi vào Comments CPU, RAM, loại đĩa, digest của image, chỗ trống trên
   đĩa trước lần chạy và mọi dòng `postgresql.conf` khác mặc định, theo bước 1 của ticket 01 (cấu hình host chạy:
   `infra/compose/docker-compose.yml` cộng `infra/compose/docker-compose.prod.yml`).
2. Chạy `uv run python scripts/bench_records_storage.py --scale d12 --variants all` trên máy đó, trong container riêng
   của harness; ma trận, phép đo, tự kiểm và mã thoát là của ticket 01 bước 5 tới 7, không đổi.
3. Ghi bảng số và dòng luật quyết bước 7 vào Comments ở đây và của
   `.claude/plans/studio/discovery/issues/07-records-storage.md`; đề xuất sửa số của ADR-0107 (Accepted) quyết 1 (ngân
   sách slot) và 2 (partition) theo số đo, và số của C hẹp vào một mục sửa đổi mới của ADR đó, qua
   `mattpocock-skills:domain-modeling` (ticket 01 bước 7 và MEDIUM (e) của gate ticket 01).
4. Chạy trước `make bench-record-access SCALE=d12` của record-access/06 trên cùng máy, vì lần chạy đó lấy modulus từ
   dòng luật quyết ở đây.

## Tiêu chí chấp nhận

- [ ] R9.1: trang đầu 50 dòng p95 ở mọi hồ sơ quyền và `GET` một bản ghi p95 trên seed T1 ở `--scale d12`, nóng và
      nguội, mỗi p95 trên ít nhất 1.000 mẫu, so với 50 ms và 5 ms, mỗi khẳng định "dùng chỉ mục" có
      `EXPLAIN (ANALYZE, BUFFERS)`; sai nếu số đến từ máy dev hay từ cluster dùng chung.
- [ ] R9.2: planning p95 của truy vấn ba vị từ (custom và generic plan) và `CacheMemoryContext` mỗi backend của A1 ở
      modulus 8 có trong Comments kèm lệnh đo, kết luận đạt hay trượt so với 5 ms và 64 MB, và lợi ích bảo trì đo được so
      với modulus 4; sai nếu modulus 8 được chọn mà không có số của lợi ích bảo trì.
- [ ] R9.5: cùng các số đó của A0 tới A3 ở modulus 4 đặt cạnh modulus 8 trong một bảng, kèm modulus được chọn theo luật
      quyết bước 7 của ticket 01; sai nếu một biến thể chỉ có số ở một modulus.
- [ ] R9.4: tập slot đề xuất cho mỗi họ, kèm số chỉ mục trên một bảng và tỉ lệ HOT của A1 và A2 ở D12; sai nếu tập slot
      không dẫn số đo nào.
- [ ] R9.6: WAL bền vững của soak 2 giờ ở 200 lần ghi mỗi giây, tính cả bản ghi, outbox, audit và
      `studio.record_write_keys`, so với 20 MB/s.
- [ ] R9.7: dead tuple trên partition của T1 qua các vòng autovacuum trong soak 2 giờ và độ dài mỗi vòng, so với
      "không tăng dần" và 30 phút.
- [ ] R9.8: q-error p95 của lọc ba vị từ trên slot dùng chung so với 10, kèm truy vấn chậm nhất so với kế hoạch tốt
      nhất của nó.
- [ ] R9.9: p95 trang đầu và `GET` của T2 trong lúc T1 nhập, vacuum và tổng hợp, so với ngưỡng của R9.1.
- [ ] R9.10: thời gian nhập 10^6 bản ghi qua đường ghi mô phỏng, so với 1.000 hàng/s.
- [ ] R9.11: thời gian promote và purge một trường trên 10^7 hàng, cùng p95 nền trong lúc chạy, so với 2 giờ và 1,5 lần.
- [ ] R9.12: p95 tạo bản ghi con của Campaign 10^5 con với 32 người ghi đồng thời trên A1, và lần chờ khóa dài nhất, so
      với 10 ms và 100 ms.
- [ ] CO27: mã thoát 0 của lần chạy nghĩa là đủ ô của ma trận bước 5 của ticket 01 ở cả hai modulus và tự kiểm HOT đạt;
      sai nếu mã thoát 0 đến từ lần chạy thiếu một modulus.
- [ ] Xong: `uv run python scripts/bench_records_storage.py --scale d12 --variants all` xanh.

## Nguồn

- `.claude/plans/studio/custom-objects/issues/01-do-nen-luu-tru-ban-ghi.md:18-30` (máy đo, cấu hình, smoke so với d12);
  spec: R9.1, R9.2, R9.4, R9.5.
- `.claude/plans/studio/custom-objects/issues/01-do-nen-luu-tru-ban-ghi.md:96-108` (tự kiểm và luật quyết bước 6, 7);
  spec: R9.6 tới R9.12, CO27.
- `.claude/plans/studio/record-access/issues/06-do-rls-ban-ghi-o-quy-mo-d12.md:21-25`; ADR-0107 (Accepted) quyết 1, 2.

## Comments

- 2026-11-04 (agent, theo ủy quyền 31/10/2026): tách từ ticket 01 khi ticket 01 đóng ở `--scale smoke`: lần chạy
  `--scale d12`, các tiêu chí chỉ máy tham chiếu chứng minh được và dòng Xong của ticket 01 sang đây, như record-access/01
  đã tách lần chạy D12 của nó sang record-access/06. Ticket 07 đọc kết luận ở đây; nó không ghi 08 ở `Blocked by`
  vì phụ thuộc trong thư mục chỉ trỏ ngược (ticket-template), nên Comments của 07 nói điều đó. Nếu sai thì: gộp lại vào
  ticket 01, ticket 01 mở lại tới khi có máy, và ticket 07 đọc Comments của ticket 01.
