# 06 — Đo hình dạng RLS bản ghi ở quy mô D12 trên máy tham chiếu

Status: ready-for-human (Chờ Đạt 23: máy tham chiếu của YC20)
Blocked by: 01, .claude/plans/studio/custom-objects/issues/01-do-nen-luu-tru-ban-ghi.md
Area: studio
Yêu cầu: R9.1, R9.2, R9.3, R9.4, R9.5, R9.6, R9.7, R9.8, R9.9

## Mục tiêu

Mẫu policy của ticket 03 chỉ được khóa khi đã đo ở quy mô D12 (ADR-0105 (Accepted) Consequences). Ticket 01 dựng các
biến thể chính sách và chạy chúng ở `--scale smoke` trên máy dev; ticket này chạy cùng lệnh ở `--scale d12` trên máy
tham chiếu mà YC20 định nghĩa (host chính sau D14), cùng máy với lần chạy D12 của custom-objects/01, xét từng dòng R9
với ngưỡng của nó, và ghi số cùng hình dạng được chọn vào ADR-0105 (Accepted). Phần của người là cấp máy (Chờ Đạt 23); phần còn
lại agent chạy được khi có máy.

## Việc cần làm

1. Đạt cấp máy tham chiếu và cách vào nó; agent ghi vào Comments CPU, RAM, loại đĩa, digest của image, chỗ trống trên
   đĩa trước lần chạy và mọi dòng `postgresql.conf` khác mặc định, theo bước 1 của custom-objects/01 (cấu hình host
   chạy: `infra/compose/docker-compose.yml` cộng `infra/compose/docker-compose.prod.yml`).
2. Chạy `make bench-record-access SCALE=d12 MODULUS=<m>` sau lần chạy `--scale d12` của custom-objects/01 trên cùng máy,
   với `<m>` là modulus mà dòng luật quyết bước 7 trong Comments của custom-objects/01 chọn cho lần chạy đó (mặc định
   của target là 8; khi luật quyết chọn 4, dòng Xong chạy với `MODULUS=4` và Comments ghi điều đó); ma trận, phép đo, cách tính độ trễ và tự kiểm là của
   ticket 01, không đổi.
3. Ghi số D12 vào `db/bench/record-access/RESULTS.md` dưới tiêu đề "d12, máy tham chiếu", cạnh mục smoke của ticket 01;
   chép bảng số và hình dạng được chọn vào mục Consequences của `docs/adr/0105-record-reach-is-decided-by-postgresql.md`
   qua `mattpocock-skills:domain-modeling`; một phương án thắng khác ADR-0105 (Accepted) quyết 1, 3 hay 4 sửa quyết
   định đó trong cùng lần ghi.
4. Phương án thắng của một trục khác phương án thắng của ticket 01 thì ghi vào Comments của ticket 02 và 03 trước khi
   chúng lên `ready-for-agent` (spec, Phụ thuộc, "Kiểm lại khi").

## Tiêu chí chấp nhận

- [ ] R9.1: trang đầu 50 dòng, có và không có bộ lọc, đạt p95 ≤ 50 ms với mọi hồ sơ của ticket 01 bước 4 trên máy
      tham chiếu, nóng và nguội, ở `--scale d12`; hồ sơ nào trượt có một phương án đã đo đạt ngưỡng trong `RESULTS.md`,
      không phải một ghi chú, hoặc, khi không phương án nào của ticket 01 đạt, một câu hỏi mở ở mục "Câu hỏi còn mở" của
      spec cho người đặt yêu cầu (đổi ngưỡng hay đổi hồ sơ, như DO-15 của custom-objects) với `Chặn: ticket 03`; sai nếu
      số đến từ máy dev, từ cluster dùng chung, hay từ seed hoặc harness khác của custom-objects/01, hay một hồ sơ trượt
      mà không có cả hai thứ đó.
- [ ] R9.2: tra một bản ghi theo id đạt p95 ≤ 5 ms với mọi hồ sơ, kể cả tài khoản dịch vụ sở hữu 10^6 lead.
- [ ] R9.3: trang keyset kế tiếp đạt p95 ≤ 50 ms với mọi hồ sơ.
- [ ] R9.4: đếm có trần `LIMIT 1001` đạt p95 ≤ 300 ms với mọi hồ sơ.
- [ ] R9.5: INSERT một bản ghi và UPDATE một cột slot đạt p95 ≤ 10 ms dưới WITH CHECK của policy, trong soak 2 giờ.
- [ ] R9.2: một dòng R9.2 tới R9.9 trượt ở mọi phương án đã đo thì spec có câu hỏi mở cho người đặt yêu cầu, như ở
      R9.1, với `Chặn: ticket 03`, và ticket này đóng với dòng "trượt" đó; sai nếu ticket đóng với một dòng trượt mà
      không có câu hỏi đó.
- [ ] R9.6: giao một bản ghi đạt p95 ≤ 20 ms; chia sẻ tay đo và ghi cùng bảng cho W2.
- [ ] R9.7: tính sổ tầm cho một chủ thể đạt p95 ≤ 50 ms, kể cả quản lý có 5.000 cấp dưới.
- [ ] R9.8: cửa sổ tầm khi dòng sổ tầm còn hiệu lực đạt p95 ≤ 1 ms.
- [ ] R9.9: tính lại sổ tầm của 5.000 chủ thể sau một lần tăng epoch xong trong ≤ 120 s tổng, bốn kết nối dưới tải hỗn
      hợp; thu hồi trên hai kết nối không bao giờ để câu lệnh sau commit thấy tầm cũ.
- [ ] R9.1: mục Consequences của ADR-0105 (Accepted) có bảng số D12 và hình dạng được chọn, kèm máy và commit đo; sai nếu một số
      trong đó là số smoke.
- [ ] Xong: `make bench-record-access SCALE=d12` xanh.

## Nguồn

- `docs/adr/0105-record-reach-is-decided-by-postgresql.md:134-139`; spec: R9.
- `.claude/plans/studio.md` mục Chờ Đạt, dòng 23 (máy tham chiếu); `.claude/plans/studio/requirements.md:312` (host hôm
  nay 2 vCPU / 8 GB); spec: R9.
- `.claude/plans/studio/custom-objects/issues/01-do-nen-luu-tru-ban-ghi.md` (bước 1 máy và cấu hình, bước 7 luật quyết
  modulus).

## Comments

- 2026-11-03 (agent, theo ủy quyền 31/10/2026): tách từ ticket 01 theo gate `checking-plan-readiness` (HIGH 1), vì lần
  đo D12 cần máy tham chiếu mà chỉ Đạt cấp được (Chờ Đạt 23), còn ticket 01 dựng và chạy được ở `--scale smoke` trên máy
  dev. Ticket 03 chờ ticket này; Blocked by chỉ trỏ ngược, nên ticket 03 ghi điều đó ở Comments. Nếu sai thì: gộp lại
  làm bước cuối của ticket 01.
