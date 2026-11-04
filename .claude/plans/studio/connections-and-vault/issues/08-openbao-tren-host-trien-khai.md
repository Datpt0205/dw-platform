# 08 — OpenBao trên host triển khai: nâng host, khóa niêm phong và AppRole thật, đích off-box, đo lại FOG-25

Status: ready-for-human (D14, Chờ Đạt 20: host, bí mật triển khai và đích off-box do người vận hành giữ)
Blocked by: 06
Area: studio
Yêu cầu: R2.1, R2.5, R2.7, R2.8, CV20

## Mục tiêu

Ticket 06 dựng và chứng minh OpenBao Transit trên compose của máy dev. Ticket này làm cùng việc đó trên host triển khai
thật, nơi chỉ người vận hành có quyền: nâng host trước khi OpenBao chạy (D14), giữ khóa niêm phong và thông tin xác
thực AppRole thật, cấu hình đích off-box thật, đo lại FOG-25 trên host, và diễn tập khôi phục từ một lượt sao lưu
off-box thật (spec R2; DO-47.1; ADR-0115 (Accepted) quyết 1, 7). Tách từ ticket 06 ở gate 4/11/2026 (spec, Quyết định
của ticket 06, (j)), vì không agent nào có host, bí mật hay đích ấy.

## Việc cần làm

1. Nâng host chính lên ít nhất 4 vCPU và 16 GB (D14) trước khi dịch vụ `openbao` chạy ở uat.
2. Trên host: đặt tệp khóa niêm phong ngoài volume dữ liệu của OpenBao và ngoài tập tệp mà job sao lưu chép; chạy
   `scripts/openbao_bootstrap.py` của ticket 06; đặt `role_id` và `secret_id` của bốn AppRole vào docker secret của host;
   xác nhận root token đã thu hồi.
3. Đặt `DW_KMS_PROVIDER=openbao` ở uat rồi production (overlay triển khai đòi biến đó, ticket 06 bước 2), triển khai.
4. Cấu hình đích off-box thật và bốn hạn giữ của `infra/backup/retention.env` trên host; chạy
   `scripts/check_backup_retention.py` trên cấu hình của host.
5. Đo lại FOG-25 (c) và (d) của ticket 06 bước 1 trên host; ghi số vào `## Answer` của discovery/21 và mục Open 5 của
   ADR-0115 (Accepted).
6. Diễn tập khôi phục trên host từ một lượt sao lưu off-box thật: khôi phục `dw` và snapshot của OpenBao, giải mã bí
   mật canary.

## Tiêu chí chấp nhận

- [ ] R2.1: ở uat, `GET /api/v1/ready` báo `kms` `ok`; token của `dw-api` gọi xóa một khóa `tenant-*` → 403 từ OpenBao.
- [ ] R2.5: khởi động lại cả host uat → `GET /api/v1/ready` báo `kms` `ok` mà không ai gõ lệnh mở niêm phong; sai nếu
      cần thao tác tay.
- [ ] R2.7 (CV20): `scripts/check_backup_retention.py` trên cấu hình của host xanh; hạn giữ snapshot off-box của kho khóa
      không dài hơn hạn của bản sao lưu `dw` off-box.
- [ ] R2.8 (CV20): diễn tập trên host từ một lượt sao lưu off-box giải mã được bí mật canary; kết quả và ngày ghi ở
      Comments.
- [ ] Xong: `scripts/check_backup_retention.py` xanh.

## Nguồn

- spec: R2, CV20, Ngoài phạm vi; ticket 06 (mọi bước trên compose); D14 (host); DO-47.1; ADR-0115 (Accepted) quyết 1,
  7, Open 5; discovery/21.

## Comments

- 2026-11-04 (agent, theo ủy quyền 31/10/2026): tách từ ticket 06 ở gate `checking-plan-readiness`: việc cần host
  triển khai, bí mật thật và đích off-box thật là việc của người (Chờ Đạt 20); ticket 06 dựng mọi phần còn lại trên
  compose. Không chạy gate cho ticket này: `ready-for-human`, không mã. Nếu sai thì: một agent có quyền vào host làm bước
  2-6 theo lệnh của người vận hành.
