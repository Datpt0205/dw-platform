# Go-live: production thật, khách trả tiền

Đích từ 6/11/2026 (Đạt): nền tảng chạy trên production thật để doanh nghiệp thuê bao và dựng DW chạy thật, không dừng ở test hay demo. Đây là ưu tiên hàng đầu, đứng trước phần còn lại của hàng đợi Studio. Yêu cầu ở [requirements.md](go-live/requirements.md).

## Trạng thái

Mới mở ngày 6/11/2026. Bốn spec đã viết, Hiện trạng đã kiểm chứng, chưa gate, chưa cắt ticket. Tám việc của Đạt ở `operator-tasks`.

Sản phẩm ngày đầu là Digital Worker chăm sóc lead, đã chạy thật một lần ở leadcare/02. Studio tới theo các bản cập nhật khi hàng đợi của nó xong; production không chờ trợ lý Marketing hay W2.

**Năm chỗ đang chặn production, đo trên code ngày 6/11/2026:**

| Chỗ chặn                                                                              | Ai gỡ                                                                   |
| ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| Người được mời không có cách nào có mật khẩu                                          | `customer-access`, `operator-tasks/05`                                  |
| DW không gửi được thư thật: `send_sink_only`, danh mục kết nối rỗng, chưa có kho khóa | `real-mail`, `studio/connections-and-vault` 05, 06, `operator-tasks/03` |
| Lệnh triển khai production không có HTTPS, không lùi được, không có sao lưu tự động   | `production-deploy`, `operator-tasks/03`                                |
| Mọi tuyến model thật khai nước ngoài, công ty mặc định `vn_only`                      | `operator-tasks/04`, `operator-tasks/02`                                |
| Không có chỗ ghi công ty nào còn hạn                                                  | `tenant-subscription`                                                   |

**Ranh giới không vượt:** dữ liệu cá nhân thật chỉ sau cổng E3 (ý kiến luật sư, DPA đã ký). Trước đó khách dùng production với dữ liệu giả lập. Chỉ Đạt được đổi cổng này, sau khi hỏi luật sư.

## Lộ trình

| Tính năng (thư mục)   | Ý định                                                                             | Yêu cầu cấp area                     | Trong; để cho                                                             | Phụ thuộc                             |
| --------------------- | ---------------------------------------------------------------------------------- | ------------------------------------ | ------------------------------------------------------------------------- | ------------------------------------- |
| `production-deploy`   | Một lệnh đưa bản đã kiểm lên production có HTTPS, lùi được, có sao lưu và cảnh báo | YC1, YC2, YC3, YC5, YC14, YC15, YC16 | Trong: lệnh, ảnh, sao lưu, cảnh báo, sổ tay; để cho Studio: OpenBao (YC4) | `operator-tasks`                      |
| `customer-access`     | Người được mời tự có mật khẩu và đăng nhập, chủ sở hữu chấp nhận điều khoản        | YC6, YC7, YC8, YC18                  | Trong: tài khoản, thư, điều khoản; để cho Studio: SSO                     | `production-deploy`, `operator-tasks` |
| `tenant-subscription` | Người vận hành ghi gói và kỳ, hết hạn giữ lượt mới, có bảng đối soát               | YC9, YC10, YC11, YC12, YC13          | Trong: sổ thuê bao, trạng thái, màn hình; để cho đợt sau: thanh toán      | `customer-access`                     |
| `real-mail`           | DW gửi và đọc thư thật qua hộp thư của công ty                                     | YC20                                 | Trong: công cụ gói, IMAP, phiên bản gói; để cho Studio: Hành động SMTP    | `operator-tasks`                      |
| `operator-tasks`      | Việc chỉ Đạt làm được: khách, luật sư, host, model, thư, pháp nhân, pentest, trực  | YC4, YC17, YC19                      | Trong: việc ngoài code                                                    | không                                 |

## ADR

Khối số dành riêng: 0200-0219.

| Số   | Tên                                                        | Tệp                                                                         |
| ---- | ---------------------------------------------------------- | --------------------------------------------------------------------------- |
| 0200 | Tài khoản khách qua một client quản trị Keycloak quyền hẹp | `docs/adr/0200-customer-accounts-through-a-narrow-keycloak-admin-client.md` |

## Tiếp theo

- `requirements.md`: Đạt duyệt hoặc ghi ủy quyền, rồi `checking-plan-readiness` (6/11/2026).
- [`production-deploy`](go-live/production-deploy/spec.md): gate, cắt ticket, dựng trước tiên (6/11/2026).
- [`customer-access`](go-live/customer-access/spec.md): viết ADR-0200, gate, cắt ticket (6/11/2026).
- [`tenant-subscription`](go-live/tenant-subscription/spec.md): gate, cắt ticket; migration theo chuỗi lần lượt (6/11/2026).
- [`real-mail`](go-live/real-mail/spec.md): gate, cắt ticket, dựng sau connections-and-vault/05 (6/11/2026).
- [`operator-tasks`](go-live/operator-tasks/issues/): tám việc của Đạt; 01, 02, 03 bắt đầu ngay vì chờ lâu nhất (6/11/2026).

## Đợt

Kiểm nhất quán chưa chạy.

- Đợt 1 (mở production cho khách đầu với dữ liệu giả lập): `production-deploy`, `customer-access`, `tenant-subscription`, `real-mail`, connections-and-vault 05 và 06, chạy lại `make demo-dw`. Đã viết spec.
- Đợt 2 (dữ liệu thật): cổng E3, pentest, `operator-tasks` 02, 04, 07. Chờ Đạt.
- Đợt 3 (khách tự dựng): 22 ticket của Studio tới đủ màn hình (`studio.md`, mục Hàng đợi). Đã có ticket.
- Đợt 4 (tự phục vụ): tự đăng ký, thanh toán, hóa đơn điện tử, khi có từ năm khách trả tiền. Chưa viết.

## Slice log

- 6/11/2026 mở area, theo lời Đạt: đích là production thật; requirements, bốn spec, tám việc của Đạt. Người đọc mới kiểm Hiện trạng: 4 chỗ sai, 2 chỗ chưa chính xác đã sửa; chỗ nặng nhất là `send_sink_only`, thành spec `real-mail`.
