# Kích hoạt: chạy tay, Nguồn dữ liệu, sự kiện nhà cung cấp, lịch, sự kiện bản ghi

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Người dựng cần một quy trình chạy được không chỉ bằng tay mà còn khi một lead từ form website tới, và lượt chạy không người kích hoạt đó phải chạy dưới danh nghĩa một tài khoản dịch vụ có trách nhiệm, không phải người phát hành. Trình kích hoạt chỉ xin một lượt chạy qua `RunRequestService` của workflow-engine rồi ghi kết quả vào `studio.trigger_deliveries`, không bao giờ tự chạy; Nguồn dữ liệu nhận dữ liệu ngoài qua một URL có id công khai ngẫu nhiên, chữ ký Standard Webhooks, chống trùng và lưu giữ có hạn, lấy tenant từ chính Nguồn dữ liệu chứ không từ payload, trả 2xx với p99 dưới một giây rồi chạy sau. Ý định: một cửa vào có chữ ký và chống trùng cho quy trình của một công ty, với danh tính chạy do hai người duyệt. W1 làm chạy tay, chạy thử ở chế độ `simulate`, danh tính run-as và Nguồn dữ liệu cho form website; sự kiện nhà cung cấp, lịch, sự kiện bản ghi và quy trình làm công cụ là W2 (ADR-0113 (Accepted), ADR-0103 (Accepted)).

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- Webhook Zalo so sánh bí mật bằng `hmac.compare_digest` trước khi đọc thân (`apps/api/src/dw_api/routes/v1/zalo.py:181`), chặn thân theo luồng ở `MAX_WEBHOOK_BYTES = 64 * 1024` (`apps/api/src/dw_api/routes/v1/zalo.py:155`), kiểm thân theo schema rồi `enqueue` và trả 200 (`apps/api/src/dw_api/routes/v1/zalo.py:212-213`). Thiếu: cửa vào này theo nhà cung cấp, không có endpoint vào tổng quát theo tenant, trang lịch sử sự kiện hay tắt từng endpoint; bảng hàng đợi là mặt danh tính, không RLS (`db/migrations/versions/395acbcad324_platform_channel_inbound_updates.py:15`).
- `platform.tenants.timezone` tồn tại và chỉ cổng admin console đọc, ghi (`packages/python/dw_platform/src/dw_platform/adapters/persistence/admin_console_repo.py:253`); không bộ hẹn giờ nào đọc nó (grep `apscheduler`, `croniter` trên `packages`, `apps` không thấy gì). Thiếu: lịch chạy W2 cần múi giờ này.
- Không có tài khoản dịch vụ; lượt chạy cần một người, `requested_by` NOT NULL (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/runtime_tables.py:38`). Thiếu: lượt chạy theo webhook không có chủ thể để đứng tên; org-and-principals/03 dựng tài khoản dịch vụ.
- `platform.ensure_time_partitions` chỉ lặp một bảng cha (`db/migrations/sql/0013_partition_maintenance.sql:123`); studio-skeleton/01 đổi nó thành đọc sổ. Ràng buộc: `studio.inbound_events` và `studio.trigger_deliveries` vào sổ đó.

## Mục tiêu

### R1 — Sổ kích hoạt: trình kích hoạt chỉ xin lượt chạy

Mỗi lần kích hoạt materialize một đăng ký và mỗi kết quả thành một dòng lần kích hoạt; trình kích hoạt xin lượt chạy, không bao giờ tự chạy (YC46; ADR-0113 (Accepted) quyết 4).

- R1.1 KHI một phiên bản quy trình thành Đang dùng, dịch vụ kích hoạt PHẢI ghi `studio.trigger_subscriptions` cho phiên bản đó và thu hồi đăng ký của phiên bản trước sang `retired` trong một giao dịch.
- R1.2 KHI một trình kích hoạt tạo một lượt chạy, trình kích hoạt PHẢI xin lượt chạy qua `RunRequestService` (workflow-engine:R3.3) và ghi một dòng `studio.trigger_deliveries` cho mỗi kết quả.
- R1.3 TRONG KHI phạm vi của một trình kích hoạt bị đóng băng, trình kích hoạt PHẢI ghi đúng một lần kích hoạt `held_frozen` cho mỗi sự kiện lúc bắt đầu giữ, không ghi lại mỗi chu kỳ, và không xin lượt chạy.
- R1.4 NẾU agent hay quy trình của một trình kích hoạt bị tắt khẩn, THÌ trình kích hoạt PHẢI ghi lần kích hoạt `refused_killed` và không xin lượt chạy.
- R1.5 Chống trùng kích hoạt PHẢI đọc `request_key` của dòng lượt chạy làm nguồn duy nhất (workflow-engine:R3.6).
- R1.6 KHI Đóng băng của phạm vi được gỡ, làn `studio_inbound` PHẢI xin lượt chạy cho các sự kiện đã giữ theo thứ tự `received_at`, mỗi sự kiện đúng một lần (agent-lifecycle:R7.2).
- R1.7 Sự kiện bị giữ khi Đóng băng PHẢI chịu cùng hạn lưu của R6.3, nên sự kiện giữ quá 30 ngày bị bộ xóa dọn và không bao giờ được xin lượt chạy.

### R2 — Chạy tay và chạy thử

Người dựng chạy tay bản đang dùng và chạy thử một phiên bản ở chế độ an toàn, không bao giờ ở chế độ Thật (YC39; ADR-0113 (Accepted)).

- R2.1 KHI người giữ `studio.workflows.run` gửi `POST /api/v1/studio/workflows/{artifact_id}/runs`, API PHẢI xin một lượt chạy của bản đang dùng ở chế độ `live` qua `RunRequestService`, với `Idempotency-Key` bắt buộc (app-standards:R2.7).
- R2.2 NẾU thân của `POST /api/v1/studio/workflows/{artifact_id}/versions/{version_id}/test-runs` nêu chế độ `live`, THÌ API PHẢI trả 422 và không xin lượt chạy.
- R2.3 KHI người giữ `studio.workflows.test` gửi `POST .../versions/{version_id}/test-runs` với chế độ `simulate`, API PHẢI xin một lượt chạy ở chế độ `simulate` qua `RunRequestService`.
- R2.4 NẾU đầu vào của chạy tay hay chạy thử sai schema của trình kích hoạt, THÌ API PHẢI trả 422 theo từng trường và không xin lượt chạy.
- R2.5 NẾU người gọi ở tenant B gọi `artifact_id` của tenant A, THÌ API PHẢI trả 404 và không xin lượt chạy.
- R2.6 NẾU thân của `POST .../versions/{version_id}/test-runs` nêu chế độ `test`, THÌ API PHẢI trả 422 và không xin lượt chạy, tới khi W2 mở Danh sách người nhận thử (DO-26.1).

### R3 — Danh tính chạy: tài khoản dịch vụ qua điểm gắn, không bao giờ người phát hành

Lượt chạy không người kích hoạt chạy dưới danh nghĩa một tài khoản dịch vụ do người giữ mọi quyền của nó gắn và người khác duyệt (YC8; D11; ADR-0103 (Accepted) quyết 4).

- R3.1 Điểm gắn kind `principal` dùng làm danh tính chạy PHẢI nhận giá trị là một tài khoản dịch vụ và kiểm `grants_cover` khi đề xuất, để Người đề xuất giữ mọi quyền của tài khoản đó (org-and-principals:R6.5).
- R3.2 ĐỐI VỚI lượt chạy không người kích hoạt (Nguồn dữ liệu, lịch, sự kiện bản ghi), runner PHẢI chạy dưới danh nghĩa tài khoản dịch vụ đã duyệt và không bao giờ dưới danh nghĩa người phát hành (record-access:R6.9; MP18).
- R3.3 ĐỐI VỚI lượt chạy thử (chế độ `simulate` ở W1), runner PHẢI chạy dưới danh nghĩa người thử.
- R3.4 NẾU phiên bản quy trình đem phát hành có điểm gắn `principal` chưa có giá trị đã duyệt, THÌ dịch vụ kích hoạt PHẢI không tạo đăng ký nào, vì việc phát hành trả 409 `binding_unset` (tenant-config:R7.2).
- R3.5 NẾU tài khoản dịch vụ chạy mất quyền đọc một trường mà điều kiện của trình kích hoạt dùng, THÌ dịch vụ kích hoạt PHẢI không tạo đăng ký cho phiên bản đó.

### R4 — Nguồn dữ liệu: loại `endpoint` có id công khai ngẫu nhiên và schema

Một nguồn dữ liệu là thành phần loại `endpoint` với id công khai ≥ 130 bit và một schema mỗi trường mang loại dữ liệu cá nhân và một mô tả ngữ nghĩa cho AI (YC42, YC84; ADR-0113 (Accepted) quyết 5).

- R4.1 NẾU một trường của schema `dw.endpoint/v1` thiếu `pd_category`, THÌ loại `endpoint` PHẢI trả 422 `pd_category_required` có con trỏ tới trường và không niêm phong.
- R4.2 Schema của loại `endpoint` PHẢI là một danh sách trường phẳng, mỗi trường mang khóa, kiểu, `pd_category` và một mô tả ngữ nghĩa cho AI.
- R4.3 KHI một Nguồn dữ liệu được tạo, dịch vụ Nguồn dữ liệu PHẢI cấp một id công khai ngẫu nhiên ít nhất 130 bit, khác quy ước id thành phần.
- R4.4 KHI người giữ `studio.datahub.manage` sao chép cURL của một Nguồn dữ liệu, trang Nguồn dữ liệu PHẢI cho một request mẫu không chứa bí mật nào.
- R4.5 KHI người giữ `studio.datahub.manage` vô hiệu hóa một Nguồn dữ liệu, dịch vụ Nguồn dữ liệu PHẢI ngừng nhận sự kiện của nguồn đó và giữ dữ liệu đã nhận.
- R4.6 NẾU người gọi xóa một Nguồn dữ liệu mà Nơi đang dùng còn một phiên bản quy trình `evaluating`, `awaiting_approval` hay `live` trỏ tới (tenant-config:R3.3), THÌ API Nguồn dữ liệu PHẢI trả 409 `artifact_in_use` và không xóa.

### R5 — Ingress: tenant từ Nguồn dữ liệu, chữ ký trước mọi xử lý, lưu rồi chạy sau

Cửa nhận của Nguồn dữ liệu nhận một sự kiện có chữ ký, lấy tenant từ Nguồn dữ liệu, chống trùng, lưu rồi trả 2xx với p99 dưới một giây, và không tự bắt đầu lượt chạy nào (YC42, YC43, YC44; ADR-0113 (Accepted) quyết 5).

- R5.1 KHI một sự kiện tới `POST /api/v1/hooks/in/{public_id}`, cửa nhận của Nguồn dữ liệu PHẢI lấy tenant từ Nguồn dữ liệu được nhắm, không bao giờ từ payload.

Cửa nhận từ chối và không tạo lượt chạy khi:

| Mã    | NẾU sự kiện tới `POST /api/v1/hooks/in/{public_id}`                     | THÌ cửa nhận trả                                                                                            |
| ----- | ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| R5.2  | sai chữ ký Standard Webhooks hay token tĩnh                             | 401, không lưu dòng mang payload, không lượt chạy                                                           |
| R5.3  | lệch giờ quá ±5 phút                                                    | 401 `stale_timestamp`                                                                                       |
| R5.4  | thân vượt trần kích thước                                               | 413, không đọc hết thân                                                                                     |
| R5.5  | sai lược đồ của Nguồn dữ liệu                                           | 422 `schema_invalid`, sự kiện lưu ở trạng thái `quarantined` kèm lỗi đọc được, không lặp lại giá trị đã gửi |
| R5.6  | id công khai không tồn tại hay đã vô hiệu                               | cùng một mã lỗi và cùng một thân như nhau                                                                   |
| R5.11 | công ty của Nguồn dữ liệu không `active` (bị khóa hay đang offboarding) | 503 có `Retry-After`, không lưu dòng nào, không lượt chạy                                                   |

- R5.7 KHI cùng một `webhook-id` tới lại trong 72 giờ, cửa nhận PHẢI trả thành công kèm dấu `duplicate` và không tạo lead hay lượt chạy thứ hai.
- R5.8 KHI một sự kiện hợp lệ được nhận, cửa nhận PHẢI lưu một dòng `studio.inbound_events` và trả 2xx với p99 dưới 1 giây ở 100 yêu cầu mỗi giây, không tự bắt đầu lượt chạy nào; làn `studio_inbound` xin lượt chạy sau.
- R5.9 NẾU một Nguồn dữ liệu nhận quá 60 sự kiện mỗi phút (đếm riêng cho từng Nguồn dữ liệu; mặc định, công ty đổi được), THÌ cửa nhận PHẢI từ chối phần vượt với 429 có `Retry-After` và không gọi AI.
- R5.10 Mô tả ngữ nghĩa AI của một trường PHẢI được đánh dấu là dữ liệu từ ngoài, nên khi vào prompt nó nằm trong khối `<input>` đã escape (ADR-0010 (Accepted); YC48).

### R6 — Lịch sử sự kiện và lưu giữ

Mọi kết quả hiện trong lịch sử sự kiện theo quyền người xem, và mỗi kho dữ liệu cá nhân mới có hạn lưu được một lane thực thi (YC88).

- R6.1 `studio.inbound_events` và `studio.trigger_deliveries` PHẢI mang `tenant_id` và `workspace_id` (ảnh chụp workspace sở hữu lúc ghi), RLS ENABLE và FORCE chỉ theo tenant kể cả partition, và một dòng trong `platform.time_partitioned_tables` với partition DEFAULT.
- R6.2 NẾU người gọi không giữ `studio.datahub.read_payloads`, THÌ lịch sử sự kiện PHẢI không trả payload của sự kiện và che giá trị theo quyền trường của người xem (field-security).
- R6.3 `studio.inbound_events` PHẢI giữ 30 ngày trong thí điểm (hạn tạm của DO-52, luật sư chốt trước chạy bóng), do bộ xóa của spec này mà lane lưu giữ của telemetry-and-audit chạy (telemetry-and-audit:R5.1).
- R6.4 `studio.inbound_dedupe` PHẢI giữ khóa chống trùng ít nhất 72 giờ, do bộ xóa của spec này mà lane lưu giữ chạy mỗi giờ.
- R6.5 KHI chủ thể dữ liệu yêu cầu xóa, cổng yêu cầu chủ thể dữ liệu PHẢI xóa payload của người đó trong `studio.inbound_events` (compliance-pdpl).
- R6.6 NẾU một sự kiện nhận thuộc workspace ngoài độ sâu quyền `studio.datahub.read` của người gọi, THÌ lịch sử sự kiện PHẢI không trả sự kiện đó.
- R6.7 `studio.trigger_deliveries` PHẢI giữ 90 ngày (hạn tạm của DO-52), do bộ xóa của spec này mà lane lưu giữ của telemetry-and-audit chạy.
- R6.8 NẾU một sự kiện nhận đã quá hạn lưu mà còn một lượt chạy `queued` xin cho nó, THÌ bộ xóa PHẢI giữ sự kiện đó tới khi lượt chạy rời `queued`.

## Trong phạm vi

- Bảng và cột ở mục Dữ liệu; route ở mục API; trang ở mục Màn hình.
- Mã: dịch vụ kích hoạt ghi `studio.trigger_subscriptions` và `studio.trigger_deliveries`; route chạy tay và chạy thử; đăng ký kind `endpoint` (`dw.endpoint/v1`) vào `ArtifactKindRegistry` và một dòng `studio.artifact_kinds`; kiểm `grants_cover` cho điểm gắn kind `principal` dùng làm danh tính chạy, đăng ký vào bộ kiểu Điểm gắn của `binding_set` (tenant-config/05); `studio.resolve_inbound_endpoint`; ingress `POST /api/v1/hooks/in/{public_id}`; làn `studio_inbound`, kể cả giữ và chạy lại sự kiện khi Đóng băng; bộ xóa của `studio.inbound_events`, `studio.trigger_deliveries` và `studio.inbound_dedupe`, đăng ký với lane lưu giữ của telemetry-and-audit.
- Khóa quyền đăng ký trong migration của spec này (quy ước của tenant-rbac/01): `studio.workflows.run`, `studio.workflows.test` (ticket 01); `studio.datahub.read`, `studio.datahub.manage`, `studio.datahub.read_payloads` (ticket 02).
- Audit: `studio.datahub.created`, `studio.datahub.disabled`, `studio.trigger.activated`, `studio.trigger.deactivated`.

## Ngoài phạm vi

| Việc                                                                                                                                                             | Vì sao                                                                                                | Chủ                                                    |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| Bộ kiểm chữ ký Standard Webhooks và cột bí mật `inbound_endpoint_id` trên `platform.secret_envelopes`                                                            | Kho bí mật và một client ra ngoài có một chủ (ADR-0115 (Accepted))                                    | connections-and-vault                                  |
| Hàm định tuyến sự kiện nhà cung cấp, đăng ký ứng dụng Meta, cửa `POST /api/v1/hooks/providers/...`                                                               | W2: Meta Lead Ads, Zalo OA (YC97)                                                                     | connections-and-vault; workflow-triggers, đợt sau (W2) |
| Trang lịch sử sự kiện (màn hình lọc, liên kết lượt chạy, lọc lần kích hoạt theo độ sâu trên `workspace_id`)                                                      | W2: phần lưu giữ ở W1, phần màn hình theo sau                                                         | workflow-triggers, đợt sau (W2)                        |
| Lịch chạy có cấu trúc (`schedule_spec`, làn `studio_schedules`, khóa `sched:<id>:<giờ UTC>`); hết hạn mức của kỳ thì ghi lần kích hoạt `limit_refused` (DO-21.3) | YC46; cần `zoneinfo` kiểm ở ảnh worker (FOG F1)                                                       | workflow-triggers, đợt sau (W2)                        |
| Kích hoạt theo sự kiện bản ghi (outbox, CEL theo cạnh, chống tự kích hoạt, chuỗi sâu 8)                                                                          | YC46; cần outbox bản ghi v1 có trường nguồn gốc                                                       | workflow-triggers, đợt sau (W2); custom-objects        |
| Quy trình làm công cụ và kích hoạt từ agent (`workflow.run_status`, trả `waiting` khi còn chờ)                                                                   | YC46; cần kind công cụ `workflow` của tools-and-skills                                                | workflow-triggers, đợt sau (W2)                        |
| Chờ sự kiện tương quan (`wait.event`, `correlation_key` theo tenant)                                                                                             | Cần làn hẹn giờ của workflow-engine W2                                                                | workflow-triggers, đợt sau (W3)                        |
| Cờ "Công khai" của đối thủ trên quy trình                                                                                                                        | Tầm thấy theo vai và workspace sở hữu, không một boolean hiển thị (ADR-0113 (Accepted))               | không làm                                              |
| Bộ giới hạn tốc độ dùng chung, `RateLimiterPort` (W1: bộ đếm theo tiến trình chia hạn mức cho số bản sao; W2: GCRA trên Valkey)                                  | Giới hạn tốc độ có một chủ (ADR-0121 (Accepted); DO-49)                                               | usage-and-limits                                       |
| W2: chạy thử chế độ `test` với Danh sách người nhận thử                                                                                                          | DO-26.1; Danh sách người nhận thử là W2 của tenant-config                                             | workflow-triggers, đợt sau (W2)                        |
| Lane lưu giữ và tệp `retention`                                                                                                                                  | telemetry-and-audit là chủ lane và tệp; compliance-pdpl khai lớp lịch sử sự kiện trong tệp đó (DO-52) | telemetry-and-audit; compliance-pdpl                   |
| Tài khoản dịch vụ, `grants_cover`, gán vai trò cho nó                                                                                                            | Chủ thể có một chủ (ADR-0103 (Accepted))                                                              | org-and-principals                                     |
| Cửa nhận lượt chạy, hàng đợi, bản kê, chế độ chạy, binding set                                                                                                   | Hàng run và vỏ phiên bản có chủ (ADR-0113 (Accepted), ADR-0109 (Accepted), ADR-0110 (Accepted))       | workflow-engine, tenant-config                         |

## Dữ liệu

Mọi bảng mới: `tenant_id`, RLS ENABLE và FORCE chỉ theo tenant, grant cùng migration, tên ràng buộc theo `NAMING_CONVENTION`, revision id hex ngẫu nhiên. `studio.trigger_subscriptions`, `studio.inbound_endpoints` và `studio.inbound_dedupe` không có `workspace_id` và có một dòng lý do trong danh sách bảng toàn tenant của `test_rls_coverage.py` (cấu hình của thành phần; khóa chống trùng 72 giờ không có dữ liệu cá nhân; DO-01).

- `studio.trigger_subscriptions`: PK `(tenant_id, id)`; `artifact_id`, `artifact_version_id`; `trigger_kind text NOT NULL` CHECK (`datahub`, `provider_app`, `schedule`, `record_event`, `agent_tool`) theo ADR-0113 (Accepted) quyết 5; `status text NOT NULL` CHECK (`active`, `retired`), không DEFAULT; `run_as_principal_id uuid` NULL; `created_at`; partial unique một `active` mỗi `(tenant_id, artifact_id, trigger_kind)`; RLS tenant.
- `studio.trigger_deliveries`: PK `(tenant_id, id)`; `subscription_id`; `workspace_id uuid NOT NULL` (ảnh chụp workspace sở hữu của quy trình lúc ghi; bên đọc: trang lịch sử sự kiện ở W2); `outcome text NOT NULL` CHECK (`run_requested`, `duplicate`, `held_frozen`, `refused_killed`, `quarantined`, `rejected`); `run_id uuid` NULL; `occurred_at timestamptz NOT NULL`; phân vùng tháng theo `occurred_at` có DEFAULT, RLS từng phân vùng, append-only, đăng ký `platform.time_partitioned_tables`.
- `studio.inbound_endpoints`: PK `(tenant_id, id)`; `artifact_id` FK tới thành phần kind `endpoint`; `public_id text NOT NULL` ngẫu nhiên ≥ 130 bit, UNIQUE toàn cục; `status text NOT NULL` CHECK (`active`, `disabled`); `inbound_endpoint_id` trỏ bí mật của connections-and-vault; `created_at`; RLS tenant.
- `studio.inbound_events`: PK `(tenant_id, id)`; `endpoint_id`; `workspace_id uuid NOT NULL` (ảnh chụp workspace sở hữu của Nguồn dữ liệu lúc nhận; bên đọc: R6.6), index `(tenant_id, workspace_id, received_at DESC)`; `webhook_id text`; `status text NOT NULL` CHECK (`accepted`, `quarantined`, `rejected`); `payload jsonb`; `error text` NULL; `received_at timestamptz NOT NULL`; phân vùng tháng theo `received_at` có DEFAULT, RLS từng phân vùng, đăng ký `platform.time_partitioned_tables`; `dw_app` không UPDATE payload; payload cần `studio.datahub.read_payloads`.
- `studio.inbound_dedupe`: PK `(tenant_id, endpoint_id, webhook_id)`; `expires_at timestamptz NOT NULL`; index `(expires_at)` cho lane quét; RLS tenant.
- Hàm `studio.resolve_inbound_endpoint(public_id text)` SECURITY DEFINER trả `(tenant_id, endpoint_id)`, theo quy tắc hàm definer; tenant không bao giờ lấy từ header hay payload.
- Điểm gắn kind `principal`: kiểm `grants_cover` đăng ký vào bộ kiểu Điểm gắn của `binding_set` (tenant-config/05), không vào `ConfigKindRegistry`; kind `endpoint` (`dw.endpoint/v1`) vào `ArtifactKindRegistry` và một dòng `studio.artifact_kinds`.

## API

- `POST /api/v1/studio/workflows/{artifact_id}/runs` (quyền `studio.workflows.run`, `Idempotency-Key` bắt buộc).
- `POST /api/v1/studio/workflows/{artifact_id}/versions/{version_id}/test-runs` (quyền `studio.workflows.test`; W1 chỉ `simulate`, `test` trả 422 tới W2).
- `POST /api/v1/hooks/in/{public_id}` (công khai, kiểm chữ ký trước mọi xử lý, 2xx với p99 dưới 1 giây; 429 có `Retry-After` khi vượt giới hạn tốc độ; 503 có `Retry-After` khi công ty không `active`).
- `GET /api/v1/studio/data-sources`, `POST /api/v1/studio/data-sources`, `GET|PATCH|DELETE .../{id}`, `POST .../{id}/disable` (quyền `studio.datahub.read`, `studio.datahub.manage`); `DELETE` gọi cùng dịch vụ xóa mềm theo Nơi đang dùng của tenant-config; lịch sử sự kiện payload cần `studio.datahub.read_payloads`.
- Lỗi theo vỏ problem+json của ADR-0108 (Accepted); `details.reason_code`: `stale_timestamp`, `signature_invalid`, `payload_too_large`, `schema_invalid`, `binding_unset`, `artifact_in_use`.

## Màn hình

- Trang "Nguồn dữ liệu" (`/studio/data-sources`): danh sách, bước "Cơ bản", bước "Schema" (khóa trường, kiểu, mô tả ngữ nghĩa AI, `pd_category`, bắt buộc), nút "Sao chép cURL", "Vô hiệu hóa", "Xóa"; không cuộn ngang ở 320 px. Trang lịch sử sự kiện là W2.

## Kiểm soát

| #    | Kiểm soát                                                           | Yêu cầu    | Test âm                                                                                                                                                                                                |
| ---- | ------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| TR1  | Tenant chỉ đến từ endpoint                                          | R5.1       | Thân có `tenant_id` của tenant khác → bị bỏ qua, lượt chạy thuộc tenant của nguồn dữ liệu; đọc tenant từ payload → test đỏ                                                                             |
| TR2  | Chữ ký trước mọi xử lý                                              | R5.2       | Sai một byte chữ ký → 401, không dòng sự kiện mang payload, không lượt chạy; kiểm chữ ký sau khi lưu → test đỏ                                                                                         |
| TR3  | Chống phát lại                                                      | R5.3       | Chữ ký đúng nhưng timestamp cũ 6 phút → 401 `stale_timestamp`; bỏ kiểm lệch giờ → test đỏ                                                                                                              |
| TR4  | Trần kích thước                                                     | R5.4       | Thân 65.537 byte → 413 mà không đọc hết thân                                                                                                                                                           |
| TR5  | Chống trùng 72 giờ                                                  | R5.7       | Gửi lại sau 71 giờ → `duplicate`, không lượt chạy thứ hai; cùng `webhook-id` ở hai nguồn → hai sự kiện; bỏ chống trùng → test đỏ                                                                       |
| TR6  | Không echo                                                          | R5.5       | Thân 422 không chứa giá trị nào đã gửi                                                                                                                                                                 |
| TR7  | Id không dò được                                                    | R5.6       | Id không tồn tại và id đã vô hiệu → cùng một mã lỗi, cùng một thân                                                                                                                                     |
| TR8  | Run-as không là người phát hành                                     | R3.2, R3.4 | Người phát hành rời tenant → lượt chạy vẫn chạy bằng tài khoản dịch vụ; phát hành phiên bản thiếu điểm gắn `principal` → 409 `binding_unset`, không đăng ký; gắn người phát hành làm chủ thể → test đỏ |
| TR9  | Kill thì không có lượt chạy                                         | R1.4       | Sự kiện sau tắt khẩn → lần kích hoạt `refused_killed`, không lượt chạy; bỏ kiểm tắt khẩn → test đỏ                                                                                                     |
| TR10 | Mô tả ngữ nghĩa AI là dữ liệu                                       | R5.10      | Mô tả chứa lệnh chèn → chỉ xuất hiện trong khối `<input>` đã escape khi vào prompt; bỏ bọc → test đỏ                                                                                                   |
| TR11 | Payload cần quyền riêng                                             | R6.2       | Người chỉ có `studio.datahub.read` không thấy payload trong lịch sử; bỏ kiểm quyền → test đỏ                                                                                                           |
| TR12 | Chạy thử không nhận chế độ Thật                                     | R2.2       | `test-runs` với `live` → 422, không lượt chạy; bỏ kiểm chế độ → test đỏ                                                                                                                                |
| TR13 | Công ty không `active` không nhận sự kiện                           | R5.11      | Khóa công ty rồi gửi sự kiện có chữ ký đúng → 503 có `Retry-After`, không dòng `studio.inbound_events`, không lượt chạy; bỏ kiểm trạng thái công ty → test đỏ                                          |
| TR14 | Lịch sử sự kiện lọc theo độ sâu quyền đọc                           | R6.6       | Người giữ `studio.datahub.read` mức `workspace` ở ws1 đọc lịch sử → không thấy sự kiện của ws2; bỏ lọc `workspace_id` → test đỏ                                                                        |
| TR15 | Sự kiện giữ khi Đóng băng chạy lại đúng thứ tự, mỗi sự kiện một lần | R1.6       | Đóng băng, gửi ba sự kiện, gỡ Đóng băng → ba lượt chạy theo thứ tự `received_at`, mỗi sự kiện một lượt; bỏ bước chạy lại → test đỏ                                                                     |

## Tiêu chí thành công

- YC94 (W1): một lead có chữ ký từ form website tạo đúng một lượt chạy quy trình Tiếp nhận lead, mỗi lead một lượt, ở chế độ `live` (chạy thử ở W1 chỉ `simulate`).
- YC44 (W1): 100% sự kiện hoặc đã trả thành công, hoặc thành lead, hoặc nằm trong lịch sử sự kiện kèm lỗi đọc được.

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát TR1-TR15 có test âm đã thấy đỏ khi gỡ kiểm soát, ghi ở Comments của ticket cài nó.
- `make ci && make test-integration` xanh; form có chữ ký và lead thử tạo đúng một lượt chạy mỗi lead có test.
- `reviewing-feature-security` và `reviewing-deployment-security` đã chạy trên từng ticket; `.claude/plans/studio.md` ghi lát W1 đã xong.

## Phụ thuộc

- workflow-engine: `RunRequestService` và cột run Studio (`.claude/plans/studio/workflow-engine/issues/02-cot-run-va-cua-nhan-run.md`), làn `studio_runs` (`.claude/plans/studio/workflow-engine/issues/04-lan-studio-runs.md`); các mã workflow-engine:R3.3, R3.6.
- org-and-principals: tài khoản dịch vụ, `grants_cover`, kiểm gắn run-as (`.claude/plans/studio/org-and-principals/issues/03-tai-khoan-dich-vu-run-as.md`, org-and-principals:R6.5, R6.7).
- tenant-config: binding set và bộ kiểu Điểm gắn nơi kiểm của kind `principal` đăng ký (`.claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md`, tenant-config:R7.2), vỏ phiên bản, bảng `studio.artifact_kinds` và dịch vụ xóa mềm theo Nơi đang dùng (tenant-config/02, tenant-config:R3.3), bản kê (tenant-config/04).
- telemetry-and-audit: lane lưu giữ và tệp `retention` (telemetry-and-audit:R5.1, `.claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md`); compliance-pdpl khai lớp lịch sử sự kiện trong tệp đó.
- usage-and-limits: `RateLimiterPort` với bộ đếm theo tiến trình ở W1, khóa theo Nguồn dữ liệu (usage-and-limits:R7.1, usage-and-limits:R7.2; `.claude/plans/studio/usage-and-limits/issues/05-cong-gioi-han-toc-do-theo-tien-trinh.md`; DO-49; Q3 của requirements).
- agent-lifecycle: `RunControlPort` cho làn `studio_inbound` khi giữ và chạy lại sự kiện (agent-lifecycle:R7.2).
- connections-and-vault: bộ kiểm chữ ký Standard Webhooks và cột `inbound_endpoint_id` (`.claude/plans/studio/connections-and-vault/issues/03-egress-client-allowlist-va-chu-ky.md`).
- record-access: run không người kích hoạt dùng tầm của tài khoản dịch vụ (record-access:R6.9); studio-skeleton: schema `studio`, nhóm route, `ensure_time_partitions`; app-standards: problem+json và `Idempotency-Key` (app-standards:R2.7); compliance-pdpl: `pd_category` và cổng yêu cầu chủ thể dữ liệu.
- Kiểm lại khi: luật sư đổi hạn lưu (DO-52) → R6.3, R6.4, R6.7, ticket 02; connections-and-vault đổi hình bộ kiểm chữ ký → R5.2, ticket 02; usage-and-limits đổi hình `RateLimiterPort` → R5.9, ticket 02; W2 mở chế độ `test` → R2.3, R2.6, R3.3, ticket 01.

## Câu hỏi còn mở

## Quyết định

- 23/10/2026 (người yêu cầu): D11: hai người luôn luôn; điểm gắn `principal` do người giữ mọi quyền của tài khoản dịch vụ đề xuất và người khác duyệt (YC8, ADR-0110 (Accepted)). Sửa: R3.1.
- 23/10/2026 (agent, tạm): 60 sự kiện mỗi phút là mặc định đổi được của một nguồn dữ liệu (R5.9); số đo p99 dưới 1 giây với 100 yêu cầu mỗi giây đo ở ticket 02. Dòng này trước ghi nhầm là D12 của người yêu cầu; D12 là quy mô, không phải hai số này.
- 23/10/2026 (agent, tạm): DO-12 theo khuyến nghị (a): lượt chạy không người chạy bằng tài khoản dịch vụ là dòng `platform.users` kind `service`. Sửa: R3.2. Nếu sai thì: R3.2 đổi chủ thể run-as và ticket 01 chờ lựa chọn mới.
- 23/10/2026 (agent, tạm): DO-06 theo khuyến nghị (a): tài liệu giữ tên điểm gắn, giá trị ghim theo lượt chạy; giờ của lịch là điểm gắn kind `schedule` (W2). Sửa: R3.1. Nếu sai thì: id kết nối và giờ nằm trong phiên bản.
- 23/10/2026 (agent, tạm): DO-52 theo khuyến nghị (a): `studio.inbound_events` 30 ngày, `studio.trigger_deliveries` 90 ngày, khóa chống trùng 72 giờ, do lane lưu giữ của telemetry-and-audit đọc. Sửa: R6.3, R6.4. Nếu sai thì: lane đọc hạn khác, R6.3 và R6.4 đổi số.
- 23/10/2026 (agent, tạm): DO-39 theo khuyến nghị (a): sự kiện vào tới một tenant bị khóa trả 503 và không lưu gì. Nếu sai thì: ingress thêm một nhánh lưu rồi giữ cho tới khi mở khóa.
- 23/10/2026 (agent, tạm): chữ ký theo Standard Webhooks (HMAC có timestamp) hoặc token tĩnh, qua một module kiểm của connections-and-vault, thứ tự theo ADR-0008 (Accepted). Sửa: R5.2, R5.3. Nếu sai thì: đổi sang sơ đồ chữ ký khác cùng vị trí trong ingress.
- 23/10/2026 (agent, tạm): học từ phân tích đối thủ (`discovery/config-chang.md`, mẫu học, không phải mã của họ): mỗi trường của nguồn dữ liệu mang một mô tả ngữ nghĩa cho AI (YC84, YC42, YC43), nhưng ở Studio mô tả là dữ liệu từ ngoài nên bọc `<input>` khi vào prompt (YC48) và thêm chữ ký, chống trùng, id ≥ 130 bit, `pd_category`. Sửa: R4.2, R5.10.
- 23/10/2026 (agent, tạm): học từ phân tích đối thủ: nút "Sao chép cURL" cấp cho integrator một request đúng, nhưng không chứa bí mật. Sửa: R4.4.
- 23/10/2026 (agent, tạm): Bỏ qua cờ "Công khai" của đối thủ trên quy trình (`discovery/config-chang.md`): Studio quyết tầm thấy theo vai và workspace sở hữu, không bằng một boolean hiển thị (thẻ EVAL của họ ghi "private" mà nhãn "Công khai" là hai nguồn một sự thật). Sửa: Ngoài phạm vi.
- 23/10/2026 (Đạt): DO-12 (a) và DO-17.2 (a): lượt chạy không người kích hoạt chạy dưới danh nghĩa tài khoản dịch vụ, một dòng `platform.users` loại `service` cộng `platform.service_principals`, gắn theo phiên bản qua điểm gắn `principal` đã duyệt và không rộng hơn người đề xuất; chưa gắn thì không phát hành (`binding_unset`). Hỏi: Q1. Sửa: R3.2, R3.4, ticket 01.
- 23/10/2026 (Đạt): DO-06 (a): tài liệu giữ tên điểm gắn, giá trị ghim theo lượt chạy; giờ của lịch là điểm gắn kind `schedule` khi lịch ra ở W2. Hỏi: Q2. Sửa: ticket 01.
- 23/10/2026 (Đạt): DO-52 (a): sự kiện nhận 30 ngày, lần kích hoạt 90 ngày, khóa chống trùng 72 giờ là số tạm trong tệp `retention` do telemetry-and-audit/03 làm chủ, luật sư chốt trước chạy bóng; lane lưu giữ của telemetry-and-audit chạy bộ xóa của spec này; 30 ngày trên phân vùng tháng xóa bằng lệnh xóa của bộ xóa, không bằng DROP PARTITION; bộ xóa không xóa sự kiện mà một lượt chạy `queued` còn trỏ tới (H:workflow-triggers:DO-52~workflow-triggers:trong-phạm-vi). Hỏi: Q3. Sửa: R6.3, R6.4, R6.7, R6.8, Trong phạm vi, Ngoài phạm vi, ticket 02.
- 23/10/2026 (Đạt): Q2 của requirements (a): Nguồn dữ liệu trả lời với p99 dưới 1 giây, đo ở 100 yêu cầu mỗi giây. Sửa: R5.8.
- 23/10/2026 (Đạt): Q3 của requirements (a) và DO-49 (a): giới hạn 60 sự kiện mỗi phút có từ W1, qua `RateLimiterPort` của usage-and-limits với bộ đếm theo tiến trình, đếm riêng từng Nguồn dữ liệu; GCRA trên Valkey ở W2. Sửa: R5.9, Ngoài phạm vi, Phụ thuộc, ticket 02.
- 23/10/2026 (Đạt): DO-39.1 (a): sự kiện tới một công ty không `active` (bị khóa hay đang offboarding) nhận 503, không lưu gì; dòng này vào bảng R5 từ W1. Sửa: R5.11, TR13, ticket 02.
- 23/10/2026 (Đạt): DO-26.1 (A): W1 chỉ mở chạy thử `simulate`; route chạy thử trả 422 với `test` tới W2, là hợp đồng duy nhất của quyền và chế độ chạy thử. Sửa: R2.3, R2.6, R3.3, Tiêu chí thành công, Ngoài phạm vi, ticket 01.
- 23/10/2026 (Đạt): DO-01 (a), tách theo loại dòng: `studio.inbound_events` và `studio.trigger_deliveries` mang `workspace_id` (ảnh chụp lúc ghi) với RLS chỉ theo tenant; `studio.trigger_subscriptions`, `studio.inbound_endpoints`, `studio.inbound_dedupe` vào lớp bảng toàn tenant (E:CLAUDE.md#tenancy-and-authorization~workflow-engine:platform.run_waits). Sửa: R6.1, R6.6, TR14, Dữ liệu, ticket 01, 02.
- 23/10/2026 (Đạt): làn `studio_inbound` hỏi `RunControlPort` mỗi chu kỳ; đang Đóng băng thì để nguyên sự kiện, gỡ thì xin lượt chạy theo `received_at`; sự kiện giữ quá hạn lưu bị dọn (H:agent-lifecycle:R7.2~workflow-triggers:R1.3). Sửa: R1.3, R1.6, R1.7, TR15, ticket 02.
- 23/10/2026 (Đạt): OPS-b: kind `endpoint` là một dòng `studio.artifact_kinds` mà ticket 02 INSERT. Sửa: Dữ liệu, ticket 02.
- 23/10/2026 (Đạt): DO-21.3 (a): lịch (W2) hết hạn mức của kỳ thì ghi lần kích hoạt `limit_refused`. Sửa: Ngoài phạm vi.
- 23/10/2026 (agent, tạm): điểm gắn kind `principal` cũng là người dự phòng của bước giao (Q6 của phiếu), nên R3.1 chỉ buộc tài khoản dịch vụ cho điểm gắn dùng làm danh tính chạy. Sửa: R3.1. Nếu sai thì: người dự phòng dùng một kind điểm gắn riêng và R3.1 về như cũ.
- 23/10/2026 (agent, tạm): sửa phát hiện B:tenant-config:dữ-liệu~workflow-triggers:dữ-liệu: kiểm của kind `principal` đăng ký vào bộ kiểu Điểm gắn của `binding_set`, không vào `ConfigKindRegistry`. Sửa: Trong phạm vi, Dữ liệu, ticket 01.
- 23/10/2026 (agent, tạm): sửa phát hiện A:tenant-config:R3.3~workflow-triggers:R4.6: xóa Nguồn dữ liệu đi qua dịch vụ xóa mềm và Nơi đang dùng của tenant-config, không theo `studio.trigger_subscriptions`. Sửa: R4.6, API, ticket 02.
- 23/10/2026 (agent, tạm): sửa phát hiện B:tenant-rbac:quy-ước~workflow-triggers:R2.1: khóa theo dạng `studio.<area>.<verb>`, `studio.workflow.run` thành `studio.workflows.run`, `runs.test` thành `studio.workflows.test`, mỗi khóa có ticket đăng ký. Sửa: R2.1, R2.3, Trong phạm vi, API, ticket 01, 02. Nếu sai thì: đổi tên theo danh mục của tenant-rbac.
- 23/10/2026 (agent, tạm): sửa phát hiện B:workflow-triggers:R5.5~workflow-triggers:api: sai lược đồ trả 422 `schema_invalid` và lưu sự kiện ở `quarantined`. Sửa: R5.5, ticket 02.
- 23/10/2026 (agent, tạm): sửa phát hiện lệch tập `trigger_kind` giữa mục Dữ liệu và ADR-0113 (Accepted): `trigger_kind` của đăng ký theo đúng tập của quyết 5 trong ADR đó; chạy tay không có đăng ký. Sửa: Dữ liệu, ticket 01.
- 23/10/2026 (agent, tạm): sửa phát hiện `G:CONTEXT.md#publish~workflow-triggers:R1.1` và `G:CONTEXT.md#data-hub-endpoint~workflow-triggers:R4.5`: "phiên bản được kích hoạt" thành "thành Đang dùng" và "đem phát hành"; "Data Hub" đứng một mình thành "Nguồn dữ liệu" hay "cửa nhận của Nguồn dữ liệu". Sửa: R1.1, R3.2, R3.4, R3.5, R4, R5, tiêu đề.

## Danh sách ticket

| #   | Ticket                                                                                                                                          |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Sổ kích hoạt, chạy tay và chạy mô phỏng, chạy dưới danh nghĩa tài khoản dịch vụ qua điểm gắn](issues/01-so-kich-hoat-chay-tay-va-danh-tinh.md) |
| 02  | [Nguồn dữ liệu: cửa nhận, chống trùng, bảng sự kiện, làn studio_inbound và lưu giữ](issues/02-data-hub-endpoint-va-ingress.md)                  |
