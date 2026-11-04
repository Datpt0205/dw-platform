# 09 — Đo đường thật của bản ghi (RecordService và trình biên dịch truy vấn) ở quy mô D12

Status: ready-for-human (Chờ Đạt 23: máy tham chiếu của YC20)
Blocked by: 04, 08
Area: studio
Yêu cầu: R9.1, R9.6, R9.10

## Mục tiêu

Ticket 08 đo harness của ticket 01 ở `--scale d12` trên đường SQL của harness; ticket 04 thêm vào cùng harness một chế
độ đường thật, đọc và ghi qua `RecordService` và `RecordQueryCompiler` trên lược đồ của `db/migrations`, và chạy nó ở
`--scale smoke` trên máy dev. Ticket này chạy chế độ đường thật ở `--scale d12` trên máy tham chiếu mà YC20 định nghĩa
(host chính sau D14), trong cùng đợt dùng máy với ticket 08, và xét R9.1, R9.6, R9.10 trên mã thật (spec R9; gate ticket
04, 4/11/2026 (a)). Phần của người là cấp máy (Chờ Đạt 23); phần còn lại agent chạy được khi có máy.

## Việc cần làm

1. Trên máy và cấu hình mà ticket 08 bước 1 đã ghi, sau lần chạy của ticket 08, chạy chế độ đường thật của ticket 04
   ở `--scale d12` với modulus mà dòng luật quyết của ticket 08 chọn, ở mọi hồ sơ quyền của harness; ma trận hồ sơ, seed
   và cách tính p95 là của ticket 01, không đổi.
2. Ghi số vào Comments ở đây và vào Comments của ticket 04, đặt cạnh số đường SQL của ticket 08 cho cùng dòng; số đường
   thật, không phải số của ticket 08, là số mà R9.1, R9.6, R9.10 xét.
3. Một dòng trượt ngưỡng: ghi phương án đã đo (biến thể của ticket 08, câu gợi ý cho planner của record-access/01) đạt
   ngưỡng, hoặc, khi không phương án nào đạt, một câu hỏi mở ở mục "Câu hỏi còn mở" của spec cho người đặt yêu cầu (đổi
   ngưỡng hay đổi hồ sơ, như DO-15) với `Chặn: marketing-pilot`.

## Tiêu chí chấp nhận

- [ ] R9.1: trang đầu 50 dòng qua `RecordQueryCompiler` và `GET` một bản ghi qua `RecordService`, ở mọi hồ sơ quyền,
      `--scale d12`, nóng và nguội, mỗi p95 trên ít nhất 1.000 mẫu, so với 50 ms và 5 ms, mỗi khẳng định "dùng chỉ mục" có
      `EXPLAIN (ANALYZE, BUFFERS)`; sai nếu số đến từ máy dev, từ đường SQL của harness, hay từ lược đồ không do
      `db/migrations` tạo.
- [ ] R9.6: WAL bền vững của soak 2 giờ ở 200 lần ghi mỗi giây, mỗi lần ghi qua `RecordService` (bản ghi, outbox, audit,
      `studio.record_write_keys`), so với 20 MB/s, đặt cạnh số của ticket 08.
- [ ] R9.10: thời gian nhập 10^6 bản ghi qua `RecordService`, so với 1.000 hàng/s, đặt cạnh số của ticket 08.
- [ ] R9.1: một dòng trượt có phương án đã đo đạt ngưỡng, hay câu hỏi mở của bước 3; sai nếu ticket đóng với một dòng
      trượt mà không có một trong hai.
- [ ] Xong: `uv run python scripts/bench_records_storage.py --scale d12 --real-path` xanh.

## Nguồn

- `.claude/plans/studio/custom-objects/issues/04-truy-van-ban-ghi.md` (bước 7, chế độ đường thật); spec: R9.1, R9.6,
  R9.10.
- `.claude/plans/studio/custom-objects/issues/08-do-nen-luu-tru-o-quy-mo-d12.md` (máy, cấu hình, luật quyết modulus).

## Comments

- 2026-11-04 (agent, theo ủy quyền 31/10/2026): tách từ ticket 04 theo gate `checking-plan-readiness` (HIGH (a)), vì
  R9.1, R9.6, R9.10 trên mã thật cần máy tham chiếu mà chỉ Đạt cấp được (Chờ Đạt 23), như ticket 08 tách từ ticket 01.
  Ticket 04 dựng chế độ đường thật và chạy nó ở `--scale smoke`. Nếu sai thì: gộp lại làm bước cuối của ticket 04, và
  ticket 04 đứng mở tới khi có máy.
