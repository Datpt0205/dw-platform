# 01 — Đo hình dạng RLS cho quyền trên bản ghi trước khi khóa thiết kế

Status: needs-triage
Area: studio
Yêu cầu: R9.1, R9.2, R9.3, R9.4, R9.5, R9.6, R9.7, R9.8, R9.9

## Mục tiêu

Mẫu policy của ticket 03 chỉ được khóa khi đã đo ở quy mô D12. Ticket này đo bộ policy RESTRICTIVE tenant cộng
PERMISSIVE theo lệnh của ADR-0105 (Accepted) mục 1, với đủ sáu nhánh tầm (mặc định toàn tenant, khóa workspace, của
tôi, của nhóm, cấp dưới, khóa chia sẻ) dù W1 chỉ dùng ba, để W2 thêm nhánh mà không đổi hình. Kết quả cho từng dòng
R9.1 tới R9.9 một con số, hay một phương án đã đo đạt ngưỡng.

## Việc cần làm

1. Tạo `db/bench/record-access/` (ngoài CI) với target `make bench-record-access`; script dựng một schema nháp riêng,
   không dùng migration của repo: bảng bản ghi `PARTITION BY HASH (tenant_id)` modulus 8 (ADR-0107 (Accepted) mục 2),
   cột `object_id`, `workspace_id`, `owner_id`, `owner_kind`, `access_key` (hai biến thể: `uuid` từ md5 của object và
   workspace sở hữu, và `bigint` ghép hai số nhỏ theo tenant), `read_grants`, `edit_grants`, `grants_valid_until`, các
   cột slot kiểu `text`, `bigint`, `date`; sổ tầm và các hàm `studio.acl_*` (`LANGUAGE sql STABLE`, SECURITY INVOKER,
   `search_path` cố định, trả mảng rỗng khi thiếu); một policy RESTRICTIVE tenant và bốn PERMISSIVE theo lệnh, mọi
   setting và mảng đọc ở dạng `(SELECT f())::uuid[]`; nhánh loại actor và giới hạn dữ liệu.
2. Dữ liệu theo D12, sinh có seed cố định: tenant T1 có 50 triệu bản ghi trên 50 object, riêng `mkt_lead` đúng 10
   triệu; 200 workspace thành cây sâu 6; 5.000 người; 300 nhóm; cây quản lý sâu 8; chia sẻ tay trên 0,4% và trên 5%
   bản ghi (hai lần chạy); 50 phiên bản quy tắc chia sẻ khớp 10% lead; một tài khoản dịch vụ tiếp nhận làm người phụ
   trách 1 triệu lead. Tenant T2 có 1 triệu bản ghi, `tenant_id` chọn để rơi cùng partition hash với T1.
3. Hồ sơ quyền, mỗi hồ sơ một chủ thể thật trong dữ liệu: Của tôi; Của nhóm tôi; Workspace của tôi (một workspace);
   Workspace của tôi và cấp dưới (40 workspace); Toàn công ty; `public_read` trên `mkt_lead`; quản lý có 50, 500 và
   5.000 cấp dưới; người nhận 500 chia sẻ; agent có giới hạn dữ liệu một object; tài khoản dịch vụ tiếp nhận.
4. Truy vấn cho mỗi hồ sơ, 20 lần sau một lần làm ấm, ghi p50, p95, p99 và `EXPLAIN (ANALYZE, BUFFERS)`: trang đầu
   50 dòng có và không có bộ lọc trên cột slot kiểu; trang keyset kế tiếp; tra một bản ghi theo id; đếm có trần
   `LIMIT 1001`; INSERT; UPDATE một cột slot; giao (đổi người phụ trách và workspace sở hữu); chia sẻ; DELETE. Cộng:
   thời gian tính sổ tầm một chủ thể; cửa sổ tầm khi dòng còn hiệu lực; tính lại 5.000 chủ thể sau một lần tăng epoch;
   một thu hồi commit giữa hai câu lệnh đọc trên hai kết nối.
5. So sánh và ghi phương án thắng: khóa `uuid` với `bigint`; mảng theo nhánh trong một dòng sổ tầm với một dòng cho mỗi
   hành động; join bảng sổ tầm, `EXISTS` và mảng khóa trên bản ghi; có và không có câu gợi ý cho planner
   (`AND owner_id = <chủ thể>` dựng từ cùng hàm `studio.acl_*`); hành vi cắt partition và InitPlan dưới RESTRICTIVE
   cộng PERMISSIVE.
6. Máy tham chiếu là máy YC20 định nghĩa (host chính sau D14, `postgres:16-alpine` của compose; Quyết định ngày
   24/10/2026 của spec). Ghi máy, phiên bản, cấu hình `postgresql.conf` khác mặc định, số đo và kế hoạch vào
   `db/bench/record-access/RESULTS.md`; chép bảng số đo và hình dạng được chọn vào mục Consequences của
   `docs/adr/0105-record-reach-is-decided-by-postgresql.md` và vào Comments của ticket này.
7. Tự kiểm trong script: thoát mã khác 0 khi một phiên không gắn tenant, không gắn loại actor, không có dòng sổ tầm,
   mang epoch cũ, hay chạy trên một policy tạo hỏng mà vẫn ra dòng, và khi một dòng của T2 xuất hiện trong phiên của
   T1.

## Tiêu chí chấp nhận

- [ ] R9.1: trang đầu 50 dòng, có và không có bộ lọc, đạt p95 ≤ 50 ms với mọi hồ sơ của bước 3 trên máy tham chiếu;
      hồ sơ nào trượt có một phương án đã đo đạt ngưỡng trong `RESULTS.md`, không phải một ghi chú.
- [ ] R9.1: script tự kiểm của bước 7 thoát khác 0 khi bỏ mệnh đề tenant khỏi policy RESTRICTIVE (kiểm chéo tenant
      đỏ) và khi bỏ điều kiện `grants_valid_until` khỏi nhánh chia sẻ (kiểm hết hạn đỏ); lần chạy ghi trong Comments.
- [ ] R9.2: tra một bản ghi theo id đạt p95 ≤ 5 ms với mọi hồ sơ, kể cả tài khoản dịch vụ sở hữu 1 triệu lead.
- [ ] R9.3: trang keyset kế tiếp đạt p95 ≤ 50 ms với mọi hồ sơ.
- [ ] R9.4: đếm có trần `LIMIT 1001` đạt p95 ≤ 300 ms với mọi hồ sơ.
- [ ] R9.5: INSERT một bản ghi và UPDATE một cột slot đạt p95 ≤ 10 ms dưới WITH CHECK của policy.
- [ ] R9.6: giao một bản ghi đạt p95 ≤ 20 ms; chia sẻ tay đo và ghi cùng bảng cho W2.
- [ ] R9.7: tính sổ tầm cho một chủ thể đạt p95 ≤ 50 ms, kể cả quản lý có 5.000 cấp dưới.
- [ ] R9.8: cửa sổ tầm khi dòng sổ tầm còn hiệu lực đạt p95 ≤ 1 ms.
- [ ] R9.9: tính lại sổ tầm của 5.000 chủ thể sau một lần tăng epoch xong trong ≤ 120 s tổng; thu hồi trên hai kết
      nối không bao giờ để câu lệnh sau commit thấy tầm cũ.
- [ ] Xong: `make bench-record-access` xanh.

## Nguồn

- `docs/adr/0105-record-reach-is-decided-by-postgresql.md:31-33`; spec: R9.
- `docs/adr/0105-record-reach-is-decided-by-postgresql.md:125-128`; spec: R9.1, R9.2.
- `db/migrations/sql/0001_platform_baseline.sql:770` (policy tenant chưa ở dạng InitPlan); spec: R9.1.

## Comments

- 2026-10-23 (agent): cỡ dữ liệu theo D12 (người yêu cầu, 23/10/2026), trả lời DO-14: 10 triệu bản ghi mỗi object,
  50 triệu mỗi tenant, 5.000 người, 200 workspace, cây sâu 6.
- 2026-10-24 (agent): máy đo là máy tham chiếu của YC20 (host chính sau D14), cùng máy của custom-objects/01, thay máy
  2 vCPU, 8 GB của quyết tạm ngày 23/10/2026 (Đạt, 24/10/2026).
