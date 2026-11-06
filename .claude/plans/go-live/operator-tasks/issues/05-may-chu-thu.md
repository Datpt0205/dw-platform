# 05 — Máy chủ thư của nền tảng và hộp thư gửi của khách

Status: ready-for-human
Area: go-live
Yêu cầu: không (việc chỉ Đạt làm được, không có spec)

## Mục tiêu

Thư mời, đặt lại mật khẩu và thư của DW tới hộp thư thật không vào spam.

## Việc cần làm

1. Chọn dịch vụ gửi thư cho tên miền nền tảng; cấu hình SPF, DKIM, DMARC.
2. Giao thông tin SMTP cho biến của customer-access R3.1.
3. Với khách đầu: lấy thông tin hộp thư gửi của chính khách (`requirements.md`, YC4).
4. Khi xong: một thư thử tới Gmail và Outlook vào hộp chính, ghi ở Comments.

## Tiêu chí chấp nhận

- [ ] Xong: `python scripts/check_plans.py --area go-live` xanh.

## Nguồn

- `.claude/plans/go-live/customer-access/spec.md`, R3.

## Comments
