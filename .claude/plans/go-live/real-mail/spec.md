# Digital Worker gửi và đọc thư thật qua hộp thư của công ty

Status: needs-triage
Area: go-live · Nhánh: `main` · Viết: 6/11/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Digital Worker chăm sóc lead là sản phẩm ngày đầu, nhưng hôm nay nó chỉ gửi được tới Mailpit: trên môi trường triển khai mọi lần gửi bị từ chối, nên chưa có gì để khách dùng thật. Chưa ticket nào của Studio gỡ chỗ này.

## Hiện trạng (đã kiểm ở `6fe88f7b` ngày 6/11/2026)

- `send_email` từ chối `send_sink_only` trên mọi môi trường triển khai, trước khi mở kết nối, bất kể cấu hình SMTP (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/pack_tools.py:170`). Thiếu: DW không có đường gửi thật.
- Bộ gửi mở `smtplib.SMTP` trần, không TLS, không đăng nhập (`packages/python/dw_connectors/src/dw_connectors/adapters/smtp_email.py:67`). Thiếu: không gửi được qua hộp thư thật nào.
- Đọc phản hồi chỉ có adapter Mailpit (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/pack_tools.py:289`). Thiếu: nhánh phân loại phản hồi của quy trình không chạy được trên hộp thư thật.
- Quy trình gọi `email.send@1.0.0` (`configs/packs/marketing/workflows/lead_care@1.0.0.yaml:71`) và `mailbox.fetch_reply@1.0.0` (`configs/packs/marketing/workflows/lead_care@1.0.0.yaml:80`). Thiếu: connections-and-vault/05 thêm hành động `smtp@1.0.0` nhưng không ticket nào chuyển gói này sang nó.
- API tạo kết nối dùng danh mục rỗng (`apps/api/src/dw_api/bootstrap/wiring.py:357`). Ràng buộc: tạo kết nối trả `connector_unknown` ở mọi môi trường cho tới connections-and-vault/05.
- SMTP của worker là hộp thư dev của gói (`apps/worker/src/dw_worker/settings.py:285`). Ràng buộc: không được biến biến môi trường này thành đường gửi production.

## Mục tiêu

### R1 — Gửi qua kết nối của công ty

DW gửi thư bằng hộp thư của chính công ty.

- R1.1 KHI quy trình gửi thư trên môi trường triển khai, công cụ PHẢI gửi qua Kết nối email của công ty mà DW được gắn.
- R1.2 NẾU DW chưa gắn Kết nối email, THÌ công cụ PHẢI từ chối với `email_connection_missing` và không gửi gì.
- R1.3 NẾU Kết nối thuộc công ty khác, THÌ công cụ PHẢI từ chối như chưa gắn và không gửi gì.
- R1.4 Mọi lần gửi thật PHẢI đi qua `ToolExecutor` và Sàn gửi tin như lần gửi tới Mailpit hôm nay.
- R1.5 NẾU Kết nối bị thu hồi hay bí mật bị đánh dấu lộ, THÌ lần gọi kế PHẢI dừng lượt và không gửi gì.

### R2 — Kênh an toàn

Thư và mật khẩu không đi trần.

- R2.1 Lần gửi thật PHẢI dùng TLS và đăng nhập bằng bí mật của Kết nối.
- R2.2 NẾU máy chủ không có STARTTLS hay SMTPS, THÌ lần gửi PHẢI từ chối với `email_tls_required` và không gửi mật khẩu.
- R2.3 Host của Kết nối PHẢI qua kiểm địa chỉ nội bộ của cửa gọi ra ngoài trước khi mở kết nối.

### R3 — Đọc phản hồi

DW thấy lead trả lời.

- R3.1 KHI quy trình đọc phản hồi, công cụ PHẢI đọc hộp thư của Kết nối chỉ ở chế độ chỉ đọc.
- R3.2 Công cụ PHẢI trả đúng thư từ địa chỉ của lead gửi sau mốc `since`.
- R3.3 Nội dung phản hồi PHẢI vào prompt trong khối `<input>` đã thoát.
- R3.4 NẾU hộp thư không đọc được, THÌ bước PHẢI bàn giao cho người và không coi là lead không trả lời.

### R4 — Gói mẫu chuyển sang đường thật

Công ty cài gói là chạy được.

- R4.1 Gói Marketing PHẢI có phiên bản quy trình dùng Hành động của Kết nối, với tham số Kết nối ở cấu hình DW.
- R4.2 NẾU một DW đang chạy phiên bản cũ, THÌ lượt đang chạy PHẢI tiếp tục theo phiên bản nó đã ghim.

## Hành vi giữ nguyên

- G1 KHI chạy ngoài môi trường triển khai với hộp thư dev, công cụ PHẢI TIẾP TỤC gửi tới Mailpit (test: `test_the_mail_is_from_the_dw_to_the_lead_with_the_ai_marks`).
- G2 KHI người nhận khác địa chỉ của lead, công cụ PHẢI TIẾP TỤC từ chối `recipient_mismatch` (test: `test_a_recipient_other_than_the_lead_is_refused`).
- G3 KHI lead chưa đồng ý, công cụ PHẢI TIẾP TỤC từ chối `consent_missing` (test: `test_a_lead_without_consent_is_refused`).

## Trong phạm vi

- Đường gửi và đọc của công cụ gói, adapter IMAP chỉ đọc, phiên bản mới của `configs/packs/marketing/workflows/lead_care`, tham số Kết nối của DW.

## Ngoài phạm vi

| Việc                     | Vì sao                        | Chủ                                   |
| ------------------------ | ----------------------------- | ------------------------------------- |
| Manifest, Hành động SMTP | Đã có ticket                  | `studio/connections-and-vault` 05     |
| Kho khóa OpenBao         | Đã có ticket                  | `studio/connections-and-vault` 06, 08 |
| Sàn gửi tin              | Đã xong                       | `studio/compliance-pdpl` 08           |
| Gmail, Outlook API       | SMTP và IMAP đủ cho khách đầu | đợt sau                               |

## Kiểm soát

| #   | Kiểm soát                                            | Yêu cầu | Test âm                                                                                       |
| --- | ---------------------------------------------------- | ------- | --------------------------------------------------------------------------------------------- |
| RM1 | Chưa gắn Kết nối thì không gửi                       | R1.2    | Profile triển khai, DW không Kết nối; `email_connection_missing`, bộ gửi giả 0 lần; gỡ thì đỏ |
| RM2 | Kết nối của công ty khác không dùng được             | R1.3    | DW của B trỏ Kết nối của A; từ chối, 0 lần giải mã bí mật; gỡ kiểm thì gửi, đỏ                |
| RM3 | Biến SMTP môi trường không phải đường gửi production | R1.1    | Profile triển khai với `SMTP_HOST` thật, không Kết nối; 0 lần gửi; gỡ kiểm thì gửi, đỏ        |
| RM4 | Thu hồi có hiệu lực ở lần gọi kế                     | R1.5    | Thu hồi giữa hai bước; lần gửi kế dừng lượt; gỡ kiểm thì gửi, đỏ                              |
| RM5 | Không gửi mật khẩu trên kênh trần                    | R2.2    | Máy chủ giả không có STARTTLS; không lệnh `AUTH` nào; gỡ kiểm thì `AUTH` đi, đỏ               |
| RM6 | Host nội bộ bị chặn                                  | R2.3    | Kết nối trỏ `169.254.169.254`; từ chối trước khi mở kết nối; gỡ kiểm thì mở, đỏ               |
| RM7 | Hộp thư chỉ đọc, chỉ đúng người                      | R3.1    | IMAP giả ghi lệnh; không `STORE`, `DELETE`, `EXPUNGE`; thêm lệnh ghi thì đỏ                   |
| RM8 | Phản hồi của lead là dữ liệu không tin cậy           | R3.3    | Phản hồi chứa lệnh tiêm vào; prompt bọc trong `<input>` đã thoát; gỡ bọc thì đỏ               |
| RM9 | Hộp thư lỗi không thành "không trả lời"              | R3.4    | IMAP giả ném lỗi; bước bàn giao cho người; gỡ kiểm thì đi nhánh không trả lời, đỏ             |

## Tiêu chí thành công

- Góp vào KQ1 của `requirements.md`.

## Tiêu chí xong

- Mọi tiêu chí R và G có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát.
- `make ci` xanh, và một lead giả lập đi trọn vòng trên uat với hộp thư thử thật, ghi ở Comments.

## Phụ thuộc

- connections-and-vault R6, R7 của `studio/connections-and-vault`: Hành động `smtp@1.0.0`, Kết nối.
- ADR-0115 (Accepted): bí mật và cửa gọi ra ngoài.
- ADR-0124 (Accepted): Sàn gửi tin.
- Kiểm lại khi: connections-and-vault/05 đổi hình Hành động → R1, R4.

## Câu hỏi còn mở

## Quyết định

- 6/11/2026 (agent, tạm): Đọc phản hồi bằng IMAP qua cùng Kết nối, vì SMTP và IMAP là hai giao thức mọi hộp thư doanh nghiệp đều có. Nếu sai thì: bỏ bước đọc phản hồi ở phiên bản gói mới, người xem hộp thư và bàn giao tay.
- 6/11/2026 (agent, tạm): Kết nối gắn ở cấu hình DW, cạnh `sender_address`. Nếu sai thì: gắn theo binding của tenant-config/05.

## Danh sách ticket
