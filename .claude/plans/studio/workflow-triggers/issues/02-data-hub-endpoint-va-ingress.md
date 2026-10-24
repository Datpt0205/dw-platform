# 02 — Nguồn dữ liệu: cửa nhận, chống trùng, bảng sự kiện, làn studio_inbound và lưu giữ

Status: needs-triage
Blocked by: 01, .claude/plans/studio/connections-and-vault/issues/02-kho-bi-mat-va-openbao.md, .claude/plans/studio/connections-and-vault/issues/03-egress-client-allowlist-va-chu-ky.md, .claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md, .claude/plans/studio/usage-and-limits/issues/05-cong-gioi-han-toc-do-theo-tien-trinh.md
Area: studio
Yêu cầu: R1.6, R1.7, R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.7, R5.8, R5.9, R5.10, R5.11, R6.1, R6.2, R6.3, R6.4, R6.6, R6.7, R6.8, R6.9, TR1, TR2, TR3, TR4, TR5, TR6, TR7, TR10, TR11, TR13, TR14, TR15

## Mục tiêu

Dựng Nguồn dữ liệu cho form website: loại `endpoint` có id công khai ngẫu nhiên và schema mỗi trường mang `pd_category` cùng mô tả ngữ nghĩa AI, cửa nhận có chữ ký và chống trùng lấy tenant từ Nguồn dữ liệu, lưu rồi chạy sau, giữ sự kiện khi Đóng băng rồi chạy lại theo thứ tự, với route đọc lịch sử lọc theo độ sâu và lưu giữ có hạn (R1.6, R1.7, R4, R5, R6 của spec; R6.5 là W2).

## Việc cần làm

1. Đăng ký kind `endpoint` (`dw.endpoint/v1`) vào `ArtifactKindRegistry` với khóa đọc `studio.datahub.read`, khóa ghi và khóa gửi `studio.datahub.manage` (tenant-config:R2.15), và migration của ticket này INSERT dòng `endpoint` vào `studio.artifact_kinds` với `has_quality_gate = true`, vì ADR-0120 (Accepted) quyết 1 chỉ cho đối tượng và công cụ là loại không có Cổng chất lượng (OPS-b, tenant-config:R2.14); schema trường phẳng `{khóa, kiểu, pd_category, mô tả ngữ nghĩa AI, bắt buộc}`; thiếu `pd_category` → 422 `pd_category_required` (YC84). Mô tả ngữ nghĩa AI đánh dấu dữ liệu từ ngoài, bọc `<input>` khi vào prompt (ADR-0010 (Accepted)).
2. `studio.inbound_endpoints` với `public_id` ngẫu nhiên ≥ 130 bit, UNIQUE toàn cục, không có `workspace_id` và có một dòng lý do trong danh sách bảng toàn tenant của `test_rls_coverage.py` (cấu hình của thành phần; DO-01); `studio.resolve_inbound_endpoint(public_id)` SECURITY DEFINER trả `(tenant_id, endpoint_id)`; trong cùng migration, `platform.secret_envelopes` của connections-and-vault/02 thêm `inbound_endpoint_id uuid` NULL, FK `(tenant_id, inbound_endpoint_id)` tới `studio.inbound_endpoints (tenant_id, id)` ON DELETE CASCADE có index, và CHECK một chủ thể thành `num_nonnulls(connection_id, inbound_endpoint_id) = 1` (ADR-0115 (Accepted) quyết 1); sinh bí mật một lần qua `platform.put_secret` với chủ thể `inbound_endpoint_id`, xoay có chồng lấn 24 giờ; trang danh sách, "Cơ bản", "Schema", "Sao chép cURL" không chứa bí mật, "Vô hiệu hóa", "Xóa" khi không còn đăng ký; quyền `studio.datahub.read`, `studio.datahub.manage`, `studio.datahub.read_payloads`, đăng ký trong migration của ticket này theo quy ước `studio.<areas>.<verb>` của tenant-rbac/01. `DELETE .../data-sources/{id}` gọi dịch vụ xóa mềm của tenant-config/02, nên Nơi đang dùng quyết `artifact_in_use` (R4.6).
3. `POST /api/v1/hooks/in/{public_id}`: lấy tenant từ Nguồn dữ liệu (không từ payload); công ty không `active` (bị khóa hay đang offboarding) → 503 có `Retry-After`, không lưu dòng nào (DO-39.1); kiểm chữ ký Standard Webhooks hoặc token tĩnh trước mọi xử lý (module của connections-and-vault/03); lệch giờ ±5 phút; trần kích thước; sai lược đồ → 422 `schema_invalid`, sự kiện lưu ở `quarantined` kèm lỗi, không echo; id không dò được → cùng mã cùng thân; 2xx với p99 dưới 1 giây ở 100 yêu cầu mỗi giây rồi chạy sau.
4. `studio.inbound_dedupe` (≥ 72 giờ; không có `workspace_id`, một dòng lý do trong danh sách bảng toàn tenant: khóa không có dữ liệu cá nhân); `studio.inbound_events` có `workspace_id uuid NOT NULL` (ảnh chụp workspace sở hữu của Nguồn dữ liệu lúc nhận) và index `(tenant_id, endpoint_id, received_at DESC, id DESC)`, phân vùng tháng có DEFAULT, RLS chỉ theo tenant từng phân vùng, đăng ký `platform.time_partitioned_tables`; làn `studio_inbound` chuyển sự kiện thành yêu cầu run cho từng đăng ký với `request_key` `<subscription_id>:<event_id>`, hỏi `RunControlPort` mỗi chu kỳ: đang Đóng băng thì để nguyên sự kiện (một lần kích hoạt `held_frozen` lúc bắt đầu giữ), gỡ thì xin lượt chạy theo `received_at` (R1.6); giới hạn 60 sự kiện mỗi phút qua `RateLimiterPort` của usage-and-limits/05 (usage-and-limits:R7.1, usage-and-limits:R7.2), khóa `(tenant_id, endpoint_id)`, không theo bearer; W1 dùng adapter bộ đếm theo tiến trình, GCRA trên Valkey ở W2 (DO-49).
5. Lưu giữ (DO-52): bộ xóa của `studio.inbound_events` (30 ngày, xóa bằng lệnh xóa chứ không DROP PARTITION, vì phân vùng tháng chỉ cho 30-61 ngày; bỏ qua sự kiện mà một lượt chạy `queued` có `request_key` của nó; bỏ qua sự kiện còn bị giữ khi Đóng băng, tức có lần kích hoạt `held_frozen` mà chưa có lượt chạy được xin, dù quá hạn, và đếm chúng vào metric của lane, vì Đóng băng không có trần thời gian, R1.7), của `studio.trigger_deliveries` (90 ngày) và của `studio.inbound_dedupe` (72 giờ, mỗi giờ), đăng ký với lane lưu giữ của telemetry-and-audit/03; ticket này thêm ba dòng `studio.inbound_events`, `studio.trigger_deliveries`, `studio.inbound_dedupe` với thời hạn tạm của chúng vào một bản mới của tệp chính sách retention, mỗi dòng dưới khóa `schema.table` của bảng (telemetry-and-audit:R5.6), trong cùng thay đổi, không ghi cứng trong mã. Cổng yêu cầu chủ thể dữ liệu xóa payload một người là W2 (R6.5, cùng YC90).
6. Route `GET /api/v1/studio/data-sources/{id}/events` (quyền `studio.datahub.read`; keyset trên `(received_at DESC, id DESC)` qua index ở bước 4): chỉ trả sự kiện có `workspace_id` trong độ sâu quyền `studio.datahub.read` của người gọi (R6.6), lỗi đọc được của sự kiện `quarantined`, payload chỉ khi người gọi giữ `studio.datahub.read_payloads` và che theo quyền trường (R6.2, R6.9); `make generate-contracts`.

## Tiêu chí chấp nhận

- [ ] R4.1: trường schema thiếu `pd_category` → 422 `pd_category_required` có con trỏ, không niêm phong.
- [ ] R4.2: schema `endpoint` là danh sách trường phẳng, mỗi trường có khóa, kiểu, `pd_category`, mô tả ngữ nghĩa AI.
- [ ] R4.3: nguồn dữ liệu mới có `public_id` ngẫu nhiên ≥ 130 bit, khác quy ước id thành phần.
- [ ] R4.4: "Sao chép cURL" cho request mẫu không chứa bí mật nào.
- [ ] R4.5: vô hiệu hóa một nguồn → ngừng nhận, dữ liệu đã nhận còn.
- [ ] R4.6: xóa một Nguồn dữ liệu mà phiên bản `live` của một quy trình trỏ tới (Nơi đang dùng) → 409 `artifact_in_use`, không xóa; đưa phiên bản đó sang `retired` rồi xóa → được.
- [ ] R5.1 (TR1): thân có `tenant_id` của tenant khác → bị bỏ qua, lượt chạy thuộc tenant của nguồn dữ liệu; đọc tenant từ payload → test đỏ.
- [ ] R5.2 (TR2): sai một byte chữ ký → 401, không dòng sự kiện mang payload, không lượt chạy; kiểm chữ ký sau khi lưu → test đỏ.
- [ ] R5.3 (TR3): timestamp cũ 6 phút → 401 `stale_timestamp`; bỏ kiểm lệch giờ → test đỏ.
- [ ] R5.4 (TR4): thân 65.537 byte → 413 mà không đọc hết thân.
- [ ] R5.5 (TR6): sai lược đồ → 422 `schema_invalid`, sự kiện ở `quarantined` kèm lỗi, thân không chứa giá trị nào đã gửi.
- [ ] R5.6 (TR7): id không tồn tại và id đã vô hiệu → cùng một mã lỗi, cùng một thân.
- [ ] R5.7 (TR5): gửi lại cùng `webhook-id` sau 71 giờ → `duplicate`, không lượt chạy thứ hai; cùng `webhook-id` ở hai nguồn → hai sự kiện; bỏ chống trùng → test đỏ.
- [ ] R5.8: sự kiện hợp lệ → lưu `inbound_events`, 2xx p99 dưới 1 giây với 100 yêu cầu mỗi giây trên máy dev; tắt worker → sự kiện vẫn 2xx và chạy sau.
- [ ] R5.9: 61 sự kiện trong một phút tới một Nguồn dữ liệu → sự kiện thứ 61 nhận 429 có `Retry-After`, không gọi AI; cùng lúc một Nguồn dữ liệu khác vẫn nhận.
- [ ] R5.10 (TR10): mô tả chứa lệnh chèn → chỉ xuất hiện trong khối `<input>` đã escape khi vào prompt; bỏ bọc → test đỏ.
- [ ] R5.11 (TR13): khóa công ty rồi gửi sự kiện có chữ ký đúng → 503 có `Retry-After`, không dòng `studio.inbound_events`, không lượt chạy; công ty `offboarding` → như vậy; bỏ kiểm trạng thái công ty → test đỏ.
- [ ] R6.1: `inbound_events` và `trigger_deliveries` có RLS trên partition DEFAULT; test phủ RLS trên partition DEFAULT.
- [ ] R6.2 (TR11): người chỉ có `studio.datahub.read` gọi `GET .../data-sources/{id}/events` → không thấy payload; bỏ kiểm quyền → test đỏ.
- [ ] R6.3: sự kiện quá 30 ngày bị bộ xóa xóa khi lane lưu giữ chạy, kể cả sự kiện nằm cùng phân vùng tháng với sự kiện chưa quá hạn; dòng `studio.inbound_events` có trong tệp `retention`.
- [ ] R6.4: khóa chống trùng quá 72 giờ bị bộ xóa quét xóa trong lượt chạy mỗi giờ của lane.
- [ ] R6.6 (TR14): người giữ `studio.datahub.read` mức `workspace` ở ws1 gọi route lịch sử của một Nguồn dữ liệu có sự kiện cũ ghi `workspace_id` của ws2 → không thấy các sự kiện đó; bỏ lọc `workspace_id` → test đỏ.
- [ ] R6.9: route lịch sử trả sự kiện của đúng Nguồn dữ liệu đó theo `received_at` giảm dần, trang hai theo con trỏ không lặp sự kiện nào của trang một, sự kiện `quarantined` mang lỗi đọc được; `EXPLAIN` của truy vấn trang dùng index `(tenant_id, endpoint_id, received_at DESC, id DESC)`.
- [ ] R6.7: lần kích hoạt quá 90 ngày bị bộ xóa xóa; lần kích hoạt 89 ngày còn nguyên.
- [ ] R6.8: sự kiện quá 30 ngày mà một lượt chạy `queued` (giữ tới `resets_at`) còn trỏ tới → bộ xóa giữ nó; lượt chạy rời `queued` → lần chạy sau của lane xóa nó.
- [ ] R1.6 (TR15): Đóng băng, gửi ba sự kiện, gỡ Đóng băng → ba lượt chạy theo thứ tự `received_at`, mỗi sự kiện một lượt, mỗi sự kiện một lần kích hoạt `held_frozen`; bỏ bước chạy lại → test đỏ.
- [ ] R1.7 (TR15): sự kiện bị giữ quá 30 ngày → bộ xóa bỏ qua nó và metric của lane đếm nó; gỡ Đóng băng sau đó → xin đúng một lượt chạy cho nó; gỡ điều kiện bỏ qua sự kiện bị giữ → test đỏ.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `apps/api/src/dw_api/routes/v1/zalo.py:155`, `apps/api/src/dw_api/routes/v1/zalo.py:181`; `db/migrations/sql/0013_partition_maintenance.sql:123`; spec: R4, R5, R6, TR1-TR7, TR10, TR11.
- connections-and-vault/02 (`platform.secret_envelopes`, hàm bí mật), connections-and-vault/03 (module chữ ký); usage-and-limits `RateLimiterPort`; compliance-pdpl (`pd_category`); telemetry-and-audit:R5.5 (bỏ qua sự kiện bị giữ); ADR-0113 (Accepted) quyết 5; ADR-0115 (Accepted) quyết 1.

## Comments

- 2026-10-23 (agent): ticket còn needs-info vì DO-52 (hạn lưu của sự kiện nhận, lần kích hoạt, khóa chống trùng) chờ luật sư và Đạt; thiết kế theo khuyến nghị (a), lane đọc hạn từ chính sách.
- 2026-10-23 (agent): DO-52 đã có lời đáp cho W1 (Đạt 23/10/2026, số tạm, luật sư chốt trước chạy bóng), nên ticket về `needs-triage`. Theo phiếu cùng ngày: chờ telemetry-and-audit/03 (lane lưu giữ và tệp `retention`); p99 ở 100 yêu cầu mỗi giây (Q2 của requirements); giới hạn 60 sự kiện mỗi phút ở W1 qua `RateLimiterPort` (Q3, DO-49); 503 cho công ty không `active` (DO-39.1); `workspace_id` trên `studio.inbound_events` (DO-01); làn `studio_inbound` giữ và chạy lại sự kiện khi Đóng băng (H:agent-lifecycle:R7.2~workflow-triggers:R1.3). Chờ usage-and-limits/05, ticket W1 giao `RateLimiterPort` với bộ đếm theo tiến trình.
- 2026-10-24 (agent): theo quyết định của Đạt ngày 24/10/2026: ticket thêm cột `inbound_endpoint_id` và CHECK chủ thể nới rộng vào `platform.secret_envelopes` và chờ connections-and-vault/02; route `GET .../data-sources/{id}/events` cho R6.2, R6.6, R6.9; bộ xóa bỏ qua và đếm sự kiện còn bị giữ (R1.7); ba dòng thời hạn vào tệp `retention` trong cùng thay đổi; R6.5 sang W2 cùng YC90. Dòng `endpoint` nêu `has_quality_gate = true` theo ADR-0120 (Accepted) quyết 1; cách một phiên bản Nguồn dữ liệu qua cổng chưa có spec nào nói, đã báo ở lần sửa vòng 3.
