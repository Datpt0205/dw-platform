# 02 — Data Hub: endpoint nhận dữ liệu, ingress, chống trùng, bảng sự kiện, làn studio_inbound

Status: needs-info (DO-52)
Blocked by: 01, .claude/plans/studio/connections-and-vault/issues/03-egress-client-allowlist-va-chu-ky.md
Area: studio
Yêu cầu: R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.7, R5.8, R5.9, R5.10, R6.1, R6.2, R6.3, R6.4, R6.5, TR1, TR2, TR3, TR4, TR5, TR6, TR7, TR10, TR11

## Mục tiêu

Dựng nguồn dữ liệu Data Hub cho form website: loại `endpoint` có id công khai ngẫu nhiên và schema mỗi trường mang `pd_category` cùng mô tả ngữ nghĩa AI, ingress có chữ ký và chống trùng lấy tenant từ endpoint, lưu rồi chạy sau, với lịch sử và lưu giữ có hạn (R4, R5, R6 của spec).

## Việc cần làm

1. Đăng ký kind `endpoint` (`dw.endpoint/v1`) vào `ArtifactKindRegistry`; schema trường phẳng `{khóa, kiểu, pd_category, mô tả ngữ nghĩa AI, bắt buộc}`; thiếu `pd_category` → 422 `pd_category_required` (YC84). Mô tả ngữ nghĩa AI đánh dấu dữ liệu từ ngoài, bọc `<input>` khi vào prompt (ADR-0010 (Accepted)).
2. `studio.inbound_endpoints` với `public_id` ngẫu nhiên ≥ 130 bit, UNIQUE toàn cục; `studio.resolve_inbound_endpoint(public_id)` SECURITY DEFINER trả `(tenant_id, endpoint_id)`; sinh bí mật một lần, xoay có chồng lấn 24 giờ (cột bí mật của connections-and-vault/03); trang danh sách, "Cơ bản", "Schema", "Sao chép cURL" không chứa bí mật, "Vô hiệu hóa", "Xóa" khi không còn đăng ký; quyền `studio.datahub.read`, `studio.datahub.manage`, `studio.datahub.read_payloads`.
3. `POST /api/v1/hooks/in/{public_id}`: lấy tenant từ endpoint (không từ payload); kiểm chữ ký Standard Webhooks hoặc token tĩnh trước mọi xử lý (module của connections-and-vault/03); lệch giờ ±5 phút; trần kích thước; sai lược đồ → cách ly không echo; id không dò được → cùng mã cùng thân; 2xx dưới 1 giây rồi chạy sau.
4. `studio.inbound_dedupe` (≥ 72 giờ, quét mỗi giờ); `studio.inbound_events` phân vùng tháng có DEFAULT, RLS từng phân vùng, đăng ký `platform.time_partitioned_tables`; làn `studio_inbound` chuyển sự kiện thành yêu cầu run cho từng đăng ký; bộ giới hạn tốc độ 60 sự kiện mỗi phút (usage-and-limits `RateLimiterPort`).
5. Lưu giữ 30 ngày cho `inbound_events`, lane đọc hạn và thực thi; cổng yêu cầu chủ thể dữ liệu xóa payload một người (compliance-pdpl).

## Tiêu chí chấp nhận

- [ ] R4.1: trường schema thiếu `pd_category` → 422 `pd_category_required` có con trỏ, không niêm phong.
- [ ] R4.2: schema `endpoint` là danh sách trường phẳng, mỗi trường có khóa, kiểu, `pd_category`, mô tả ngữ nghĩa AI.
- [ ] R4.3: nguồn dữ liệu mới có `public_id` ngẫu nhiên ≥ 130 bit, khác quy ước id thành phần.
- [ ] R4.4: "Sao chép cURL" cho request mẫu không chứa bí mật nào.
- [ ] R4.5: vô hiệu hóa một nguồn → ngừng nhận, dữ liệu đã nhận còn.
- [ ] R4.6: xóa một nguồn còn đăng ký → 409 `artifact_in_use`, không xóa.
- [ ] R5.1 (TR1): thân có `tenant_id` của tenant khác → bị bỏ qua, lượt chạy thuộc tenant của nguồn dữ liệu; đọc tenant từ payload → test đỏ.
- [ ] R5.2 (TR2): sai một byte chữ ký → 401, không dòng sự kiện mang payload, không lượt chạy; kiểm chữ ký sau khi lưu → test đỏ.
- [ ] R5.3 (TR3): timestamp cũ 6 phút → 401 `stale_timestamp`; bỏ kiểm lệch giờ → test đỏ.
- [ ] R5.4 (TR4): thân 65.537 byte → 413 mà không đọc hết thân.
- [ ] R5.5 (TR6): sai lược đồ → 422 `quarantine`, thân không chứa giá trị nào đã gửi.
- [ ] R5.6 (TR7): id không tồn tại và id đã vô hiệu → cùng một mã lỗi, cùng một thân.
- [ ] R5.7 (TR5): gửi lại cùng `webhook-id` sau 71 giờ → `duplicate`, không lượt chạy thứ hai; cùng `webhook-id` ở hai nguồn → hai sự kiện; bỏ chống trùng → test đỏ.
- [ ] R5.8: sự kiện hợp lệ → lưu `inbound_events`, 2xx p99 dưới 1 giây với 100 yêu cầu mỗi giây trên máy dev; tắt worker → sự kiện vẫn 2xx và chạy sau.
- [ ] R5.9: quá 60 sự kiện mỗi phút → phần vượt bị từ chối, không gọi AI.
- [ ] R5.10 (TR10): mô tả chứa lệnh chèn → chỉ xuất hiện trong khối `<input>` đã escape khi vào prompt; bỏ bọc → test đỏ.
- [ ] R6.1: `inbound_events` và `trigger_deliveries` có RLS trên partition DEFAULT; test phủ RLS trên partition DEFAULT.
- [ ] R6.2 (TR11): người chỉ có `studio.datahub.read` không thấy payload trong lịch sử; bỏ kiểm quyền → test đỏ.
- [ ] R6.3: sự kiện quá 30 ngày bị lane lưu giữ xóa.
- [ ] R6.4: khóa chống trùng quá 72 giờ bị lane quét xóa.
- [ ] R6.5: yêu cầu chủ thể dữ liệu xóa payload của một người trong `inbound_events`.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `apps/api/src/dw_api/routes/v1/zalo.py:155`, `apps/api/src/dw_api/routes/v1/zalo.py:181`; `db/migrations/sql/0013_partition_maintenance.sql:123`; spec: R4, R5, R6, TR1-TR7, TR10, TR11.
- connections-and-vault/03 (module chữ ký, cột bí mật); usage-and-limits `RateLimiterPort`; compliance-pdpl (`pd_category`, DSR); ADR-0113 (Proposed) quyết 5.

## Comments

- 2026-10-23 (agent): ticket còn needs-info vì DO-52 (hạn lưu của sự kiện nhận, lần kích hoạt, khóa chống trùng) chờ luật sư và Đạt; thiết kế theo khuyến nghị (a), lane đọc hạn từ chính sách.
