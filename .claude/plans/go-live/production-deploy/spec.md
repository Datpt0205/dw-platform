# Triển khai production và giữ nó chạy

Status: needs-triage
Area: go-live · Nhánh: `main` · Viết: 6/11/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Người vận hành cần một lệnh đưa một bản đã kiểm lên production có HTTPS, quay về được khi hỏng, có sao lưu ngoài host và có cảnh báo tới người trực, vì khách vào dùng thật không thể chờ một host dựng tay.

## Hiện trạng (đã kiểm ở `6fe88f7b` ngày 6/11/2026)

- `deploy.sh` chọn overlay production nhưng không áp `docker-compose.host.yml` (`scripts/deploy.sh:24`), và không có lệnh nào trong repo áp nó. Thiếu: lần triển khai theo lệnh này không có Caddy.
- Base compose coi TLS là nginx trên server, nằm ngoài repo (`infra/compose/docker-compose.yml:197`). Thiếu: lớp HTTPS của một lần triển khai không có trong repo, nên không ai dựng lại được nó từ repo.
- Thư mục triển khai mặc định còn tên cũ `base_agent` (`scripts/deploy.sh:18`), và workflow gọi đúng đường dẫn đó (`.github/workflows/deploy.yml:61`). Chưa rõ: có host nào đang chạy ở đó không.
- Ảnh được dựng ngay trên host lúc triển khai (`scripts/deploy.sh:40`) sau `git reset --hard` (`scripts/deploy.sh:34`). Thiếu: không có bản đóng gói đã kiểm để lùi về; ảnh của bản cũ bị ghi đè, chỉ commit còn lại.
- Overlay production định cỡ cho máy 2 vCPU / 8 GB (`infra/compose/docker-compose.prod.yml:24`). Ràng buộc: D14 đòi ít nhất 4 vCPU / 16 GB trước khi OpenBao chạy.
- Sao lưu là một dòng cron cài tay với đường dẫn cũ (`scripts/backup_postgres.sh:20`). Thiếu: không có gì báo khi một đêm không có bản sao lưu.
- Diễn tập khôi phục mới trong cùng cluster (`.claude/plans/ops-hardening.md:70`), và chưa có dashboard (`.claude/plans/ops-hardening.md:78`). Thiếu: chưa từng dựng lại từ số không.
- `build_kms` chỉ biết `local`, còn lại trả kho luôn từ chối (`packages/python/dw_platform/src/dw_platform/adapters/kms.py:124`). Ràng buộc: khóa của công ty trên production chờ connections-and-vault/06 và /08.
- `validate_for_profile` từ chối khởi động với model giả, embedding băm, thiếu Qdrant, khóa ký ngắn và các cấu hình khác (`apps/api/src/dw_api/settings.py:398`). Ràng buộc: `DW_KMS_PROVIDER=none` và thiếu máy chủ thư vẫn khởi động được, nên lệnh triển khai phải tự chặn.

## Mục tiêu

### R1 — Một lệnh có HTTPS

Người vận hành chạy một lệnh và có đủ ba tên miền của ADR-0009 (Accepted).

- R1.1 KHI người vận hành triển khai uat hay production, lệnh triển khai PHẢI áp cả overlay môi trường lẫn overlay host.
- R1.2 NẾU thiếu một biến bắt buộc của môi trường đích, THÌ lệnh triển khai PHẢI dừng trước khi đụng tới dịch vụ đang chạy, kèm tên biến thiếu.
- R1.4 NẾU `DW_KMS_PROVIDER` của production không phải kho khóa thật, THÌ lệnh triển khai PHẢI dừng trước khi đụng tới dịch vụ đang chạy.
- R1.3 Đường dẫn triển khai PHẢI đọc từ cấu hình của host, không mang tên cũ trong repo.

### R2 — Bản đóng gói đã kiểm

Mỗi bản là một bộ ảnh có digest, dựng một lần, chạy ở uat rồi mới lên production.

- R2.1 KHI một tag phát hành được đẩy, CI PHẢI dựng và đẩy ảnh api, worker, web, docgen lên registry với digest ghi trong bản kê phát hành.
- R2.2 KHI triển khai production, host PHẢI kéo ảnh theo digest và không dựng ảnh.
- R2.3 NẾU digest chưa chạy khỏe trên uat, THÌ lệnh triển khai production PHẢI từ chối.

### R3 — Quay về được

Bản lỗi không làm khách mất dịch vụ lâu.

- R3.1 KHI triển khai production, lệnh triển khai PHẢI tạo một bản sao lưu trước khi chạy migration.
- R3.2 NẾU các ứng dụng không khỏe trong hạn chờ, THÌ lệnh triển khai PHẢI đưa ứng dụng về digest trước và báo thất bại.
- R3.3 NẾU bản mới có migration, THÌ lệnh quay về PHẢI nói rõ bản sao lưu nào cần khôi phục và không tự khôi phục.
- R3.4 KHI người vận hành chạy lệnh quay về, nền tảng PHẢI chạy lại digest trước trong 30 phút.

### R4 — Sao lưu ngoài host

Dữ liệu sống sót khi host mất.

- R4.1 Sao lưu Postgres và kho đối tượng PHẢI chạy mỗi ngày bằng một dịch vụ trong compose production, không bằng cron cài tay.
- R4.2 NẾU không có bản sao lưu thành công trong 26 giờ, THÌ giám sát PHẢI phát cảnh báo.
- R4.3 Bản sao lưu PHẢI nằm ngoài host production.
- R4.4 KHI chạy diễn tập, lệnh diễn tập PHẢI dựng lại dịch vụ trên một host trống từ bản sao lưu và ghi thời gian dựng lại.

### R5 — Cảnh báo tới người

Khi dịch vụ ngừng có người biết.

- R5.1 Một kiểm tra từ ngoài host PHẢI gọi ba tên miền mỗi phút.
- R5.2 KHI kiểm tra ngoài host hỏng liên tiếp 3 lần, người trực PHẢI nhận được cảnh báo trên kênh đã cấu hình.
- R5.3 NẾU kênh cảnh báo không cấu hình, THÌ lệnh triển khai production PHẢI từ chối.

### R6 — Sổ tay vận hành

Người trực không phải đoán.

- R6.1 Repo PHẢI có sổ tay cho triển khai, quay về, khôi phục, xoay bí mật, đóng băng và ứng phó khi lộ dữ liệu.
- R6.2 KHI một lệnh trong sổ tay đổi tên, kiểm tra tài liệu PHẢI đỏ.

## Trong phạm vi

- `scripts/deploy.sh`, `.github/workflows/deploy.yml`, `.github/workflows/release.yml`, `infra/compose/docker-compose.prod.yml`, `infra/compose/docker-compose.uat.yml`, dịch vụ sao lưu trong compose, kiểm tra ngoài host, `docs/platform/runbooks/`.

## Ngoài phạm vi

| Việc                        | Vì sao                     | Chủ                            |
| --------------------------- | -------------------------- | ------------------------------ |
| OpenBao và proxy ra ngoài   | Đã có spec và ticket riêng | `studio/connections-and-vault` |
| Nâng host, tên miền, bí mật | Chỉ người vận hành giữ     | `go-live/operator-tasks`       |
| Nhiều host, tự co giãn      | Chưa có tải đòi điều đó    | đợt sau                        |
| Tài khoản khách             | Một spec riêng             | `go-live/customer-access`      |

## Kiểm soát

| #   | Kiểm soát                                             | Yêu cầu | Test âm                                                                                       |
| --- | ----------------------------------------------------- | ------- | --------------------------------------------------------------------------------------------- |
| PD1 | Lệnh production không chạy nếu thiếu overlay host     | R1.1    | Chạy lệnh ở chế độ thử với tệp host bị gỡ; gỡ kiểm thì lệnh in cấu hình không có Caddy, đỏ    |
| PD2 | Biến thiếu dừng lệnh trước khi đụng dịch vụ           | R1.2    | Bỏ một biến; lệnh thoát khác 0, không lệnh `up` nào chạy; gỡ kiểm thì `up` chạy, đỏ           |
| PD3 | Host production không dựng ảnh                        | R2.2    | Soi cấu hình production: không dịch vụ ứng dụng nào có `build`; thêm lại thì đỏ               |
| PD4 | Digest chưa khỏe trên uat bị từ chối                  | R2.3    | Gọi lệnh với digest không có dòng uat khỏe; thoát khác 0; gỡ kiểm thì đi tiếp, đỏ             |
| PD5 | Bản lỗi tự về digest trước                            | R3.2    | Dựng một ảnh không khỏe trên compose; digest đang chạy về bản trước; gỡ kiểm thì kẹt, đỏ      |
| PD6 | Quay về không tự khôi phục database                   | R3.3    | Quay về một bản có migration; không `pg_restore` nào chạy, in tên bản sao lưu; đỏ khi tự chạy |
| PD7 | Không cấu hình kênh cảnh báo thì không lên production | R5.3    | Bỏ biến kênh; lệnh production từ chối; gỡ kiểm thì đi tiếp, đỏ                                |
| PD8 | Production không chạy khi chưa có kho khóa thật       | R1.4    | Đặt `DW_KMS_PROVIDER=none`; lệnh production thoát khác 0; gỡ kiểm thì `up` chạy, đỏ           |

## Tiêu chí thành công

- Góp vào KQ3 và KQ4 của `requirements.md`.

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát.
- `make ci` xanh, và một lần triển khai thật lên uat ghi ở Comments của ticket cuối.

## Phụ thuộc

- ADR-0009 (Accepted): hình ba tên miền sau Caddy.
- ADR-0115 (Accepted) và `studio/connections-and-vault`: kho khóa.
- `operator-tasks/03`: host, tên miền, bí mật.
- Kiểm lại khi: đổi registry ảnh hay rời compose → R2, R3.

## Câu hỏi còn mở

## Quyết định

- 6/11/2026 (agent, tạm): Giữ compose trên một host, không chuyển Kubernetes. Sửa: Ngoài phạm vi. Nếu sai thì: ADR mới và viết lại R1, R2.
- 6/11/2026 (agent, tạm): Registry ảnh là GitHub Container Registry của repo `Datpt0205/dw-platform`. Nếu sai thì: đổi một biến ở `release.yml` và `deploy.sh`.
- 6/11/2026 (agent, tạm): Quay về không tự khôi phục database, vì khôi phục làm mất dữ liệu khách ghi sau bản sao lưu; người vận hành quyết. Nếu sai thì: thêm cờ tự khôi phục cho bản chưa nhận ghi nào.

## Danh sách ticket
