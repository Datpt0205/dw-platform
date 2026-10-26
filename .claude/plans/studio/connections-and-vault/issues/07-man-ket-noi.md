# 07 — Màn Kết nối /studio/connections

Status: needs-triage
Blocked by: 04, 05, .claude/plans/studio/studio-skeleton/issues/03-seam-web-va-allowlist-antd.md
Area: studio
Yêu cầu: R5.7, R1.15

## Mục tiêu

Quản trị viên của một workspace thấy, thêm, kiểm, tắt, xin bật lại và thu hồi vì lộ Kết nối dùng chung trên trang
`/studio/connections`, trên các route mà ticket 04 đã ship; người thiếu quyền thấy nút bị tắt kèm lý do, còn API vẫn
chặn (spec R5.7, R1.15, mục Màn hình). Ticket tách từ bước 7 của ticket 04 (V4.31), để luật `connection_usable` và API
không chờ seam web của studio-skeleton/03.

## Việc cần làm

1. Trang `apps/web/app/studio/connections/page.tsx` dưới seam web và allowlist antd của studio-skeleton/03, chỉ dùng
   `antd` và `@ant-design/icons` (CLAUDE.md, mục Web UI; `apps/web/lib/__tests__/antd-only.test.ts`), gọi client sinh
   bởi `make generate-contracts` của ticket 04: `GET /api/v1/connections`, `GET /api/v1/connections/{id}`,
   `GET /api/v1/connections/{id}/dependents`, `GET /api/v1/connectors`.
2. antd `Table` với cột tên, trình kết nối, tài khoản ngoài, Phạm vi dùng chung, Connection status bằng chữ (không chỉ
   màu), lần dùng gần nhất qua `lib/dates.ts`; `Drawer` thêm kết nối (API key, basic) gửi `POST /api/v1/connections`
   kèm `Idempotency-Key`, trường bí mật là ô mật khẩu không bao giờ điền sẵn; bí mật đã lưu hiện "Đã cấu hình".
3. Trang chi tiết: sức khỏe, mã lỗi gần nhất, phạm vi đã cấp, "Được dùng bởi" (`.../dependents`), yêu cầu bật lại
   đang chờ (`connections.enable`), thời điểm thu hồi vì lộ gần nhất (`compromised_at`); nút "Kiểm" (`.../test`),
   "Tắt" (`.../disable`), "Bật lại" (`.../enable`, hiện 202 là "Đã gửi yêu cầu cho người thứ hai duyệt" và 409
   `no_checker_available` là lý do bằng chữ); xác nhận xóa nêu tên kết nối và danh sách phụ thuộc, 409
   `connection_in_use` hiện danh sách đó.
4. Nút "Thu hồi vì lộ" gọi `POST /api/v1/connections/{id}/revoke-credentials` (spec R1.15) sau một `Modal` xác nhận nói
   rằng mọi lượt chưa xong của kết nối sẽ dừng ở lời gọi ra ngoài kế tiếp, kể cả khi đã lưu mật khẩu mới; nút bật cho người giữ
   `connections.manage` (spec R1.15; Đạt, Q-h3).
5. Người thiếu `connections.manage` thấy các nút ghi bị tắt kèm lý do; ẩn hay tắt nút không phải phân quyền, API của
   ticket 04 vẫn chặn (CLAUDE.md, Tenancy and authorization). Thông báo qua `App.useApp()`.

## Tiêu chí chấp nhận

- [ ] R5.7: Playwright mở `/studio/connections` với một Kết nối của fixture → thấy tên, trình kết nối, tài khoản
      ngoài, phạm vi, trạng thái bằng chữ và "Được dùng bởi"; trường bí mật hiện "Đã cấu hình", HTML của trang không
      chứa giá trị canary; người thiếu `connections.manage` thấy nút bị tắt kèm lý do và `POST /api/v1/connections` của
      người đó vẫn trả 403; bỏ cột trạng thái bằng chữ hay điền sẵn ô bí mật → test đỏ.
- [ ] R1.15: Playwright bấm "Thu hồi vì lộ" rồi hủy xác nhận → route không được gọi; xác nhận → route được gọi đúng một
      lần và trang chi tiết hiện thời điểm thu hồi; bỏ bước xác nhận → ca hủy gọi route, test đỏ.
- [ ] Xong: `make ci && make test-web` xanh.

## Nguồn

- spec: R5.7, R1.15, mục Màn hình, mục API; ticket 04 (route, `compromised_at`, `make generate-contracts`);
  studio-skeleton/03 (seam web và allowlist antd).
- `apps/web/lib/__tests__/antd-only.test.ts`; CLAUDE.md, mục Web UI (antd v6, `App.useApp()`, `lib/dates.ts`).

## Comments

- 2026-10-25 (agent): ticket mới theo V4.31 của Đạt (lượt h), số và đường dẫn theo bảng ticket mới của lượt: bước 7 cũ
  của ticket 04 (màn `/studio/connections`) cùng R5.7 dời về đây; Blocked by 04 và studio-skeleton/03 theo bảng cạnh
  của lượt, cộng Blocked by 05 (ngoài bảng, đã chạy mô phỏng đồ thị của lượt: không vòng, độ sâu của
  marketing-pilot/03 không đổi) vì `Drawer` thêm kết nối đọc danh mục trình kết nối `GET /api/v1/connectors` mà ticket
  05 ship. Thêm nút "Thu hồi vì lộ" của V4.35 (R1.15), khóa của nút chờ Q3.
