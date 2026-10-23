# Kích hoạt: chạy tay, Data Hub, sự kiện nhà cung cấp, lịch, sự kiện bản ghi

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Người dựng cần một quy trình chạy được không chỉ bằng tay mà còn khi một lead từ form website tới, và lượt chạy không người kích hoạt đó phải chạy dưới danh nghĩa một tài khoản dịch vụ có trách nhiệm, không phải người phát hành. Trình kích hoạt chỉ xin một lượt chạy qua `RunRequestService` của workflow-engine rồi ghi kết quả vào `studio.trigger_deliveries`, không bao giờ tự chạy; Data Hub nhận dữ liệu ngoài qua một endpoint có id công khai ngẫu nhiên, chữ ký Standard Webhooks, chống trùng và lưu giữ có hạn, lấy tenant từ chính endpoint chứ không từ payload, trả 2xx dưới một giây rồi chạy sau. Ý định: một cửa vào có chữ ký và chống trùng cho quy trình của một công ty, với danh tính chạy do hai người duyệt. W1 làm chạy tay, chạy thử, danh tính run-as và endpoint Data Hub cho form website; sự kiện nhà cung cấp, lịch, sự kiện bản ghi và quy trình làm công cụ là W2 (ADR-0113 (Proposed), ADR-0103 (Proposed)).

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- Webhook Zalo so sánh bí mật bằng `hmac.compare_digest` trước khi đọc thân (`apps/api/src/dw_api/routes/v1/zalo.py:181`), chặn thân theo luồng ở `MAX_WEBHOOK_BYTES = 64 * 1024` (`apps/api/src/dw_api/routes/v1/zalo.py:155`), kiểm thân theo schema rồi `enqueue` và trả 200 (`apps/api/src/dw_api/routes/v1/zalo.py:212-213`). Thiếu: cửa vào này theo nhà cung cấp, không có endpoint vào tổng quát theo tenant, trang lịch sử sự kiện hay tắt từng endpoint; bảng hàng đợi là mặt danh tính, không RLS (`db/migrations/versions/395acbcad324_platform_channel_inbound_updates.py:15`).
- `platform.tenants.timezone` tồn tại và chỉ cổng admin console đọc, ghi (`packages/python/dw_platform/src/dw_platform/adapters/persistence/admin_console_repo.py:253`); không bộ hẹn giờ nào đọc nó (grep `apscheduler`, `croniter` trên `packages`, `apps` không thấy gì). Thiếu: lịch chạy W2 cần múi giờ này.
- Không có tài khoản dịch vụ; lượt chạy cần một người, `requested_by` NOT NULL (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/runtime_tables.py:38`). Thiếu: lượt chạy theo webhook không có chủ thể để đứng tên; org-and-principals/03 dựng tài khoản dịch vụ.
- `platform.ensure_time_partitions` chỉ lặp một bảng cha (`db/migrations/sql/0013_partition_maintenance.sql:123`); studio-skeleton/01 đổi nó thành đọc sổ. Ràng buộc: `studio.inbound_events` và `studio.trigger_deliveries` vào sổ đó.

## Mục tiêu

### R1 — Sổ kích hoạt: trình kích hoạt chỉ xin lượt chạy

Mỗi lần kích hoạt materialize một đăng ký và mỗi kết quả thành một dòng lần kích hoạt; trình kích hoạt xin lượt chạy, không bao giờ tự chạy (YC46; ADR-0113 (Proposed) quyết 4).

- R1.1 KHI một phiên bản quy trình được kích hoạt, dịch vụ kích hoạt PHẢI ghi `studio.trigger_subscriptions` cho phiên bản đó và thu hồi đăng ký của phiên bản trước sang `retired` trong một giao dịch.
- R1.2 KHI một trình kích hoạt tạo một lượt chạy, trình kích hoạt PHẢI xin lượt chạy qua `RunRequestService` (workflow-engine:R3.3) và ghi một dòng `studio.trigger_deliveries` cho mỗi kết quả.
- R1.3 TRONG KHI phạm vi của một trình kích hoạt bị đóng băng, trình kích hoạt PHẢI giữ một lần kích hoạt với kết quả `held_frozen` và không xin lượt chạy.
- R1.4 NẾU agent hay quy trình của một trình kích hoạt bị tắt khẩn, THÌ trình kích hoạt PHẢI ghi lần kích hoạt `refused_killed` và không xin lượt chạy.
- R1.5 Chống trùng kích hoạt PHẢI đọc `request_key` của dòng lượt chạy làm nguồn duy nhất (workflow-engine:R3.6).

### R2 — Chạy tay và chạy thử

Người dựng chạy tay bản đang dùng và chạy thử một phiên bản ở chế độ an toàn, không bao giờ ở chế độ Thật (YC39; ADR-0113 (Proposed)).

- R2.1 KHI người giữ `studio.workflow.run` gửi `POST /api/v1/studio/workflows/{artifact_id}/runs`, API PHẢI xin một lượt chạy của bản đang dùng ở chế độ `live` qua `RunRequestService`, với `Idempotency-Key` bắt buộc (app-standards:R2.7).
- R2.2 NẾU thân của `POST /api/v1/studio/workflows/{artifact_id}/versions/{version_id}/test-runs` nêu chế độ `live`, THÌ API PHẢI trả 422 và không xin lượt chạy.
- R2.3 KHI người giữ `runs.test` gửi `POST .../versions/{version_id}/test-runs` với chế độ `test` hoặc `simulate`, API PHẢI xin một lượt chạy ở đúng chế độ đó qua `RunRequestService`.
- R2.4 NẾU đầu vào của chạy tay hay chạy thử sai schema của trình kích hoạt, THÌ API PHẢI trả 422 theo từng trường và không xin lượt chạy.
- R2.5 NẾU người gọi ở tenant B gọi `artifact_id` của tenant A, THÌ API PHẢI trả 404 và không xin lượt chạy.

### R3 — Danh tính chạy: tài khoản dịch vụ qua điểm gắn, không bao giờ người phát hành

Lượt chạy không người kích hoạt chạy dưới danh nghĩa một tài khoản dịch vụ do người giữ mọi quyền của nó gắn và người khác duyệt (YC8; D11; ADR-0103 (Proposed) quyết 4).

- R3.1 Điểm gắn kind `principal` PHẢI nhận giá trị là một tài khoản dịch vụ và kiểm `grants_cover` khi đề xuất, để Người đề xuất giữ mọi quyền của tài khoản đó (org-and-principals:R6.5).
- R3.2 ĐỐI VỚI lượt chạy không người kích hoạt (Data Hub, lịch, sự kiện bản ghi), runner PHẢI chạy dưới danh nghĩa tài khoản dịch vụ đã duyệt và không bao giờ dưới danh nghĩa người phát hành (record-access:R6.9; MP18).
- R3.3 ĐỐI VỚI lượt chạy chạy thử ở chế độ `test`, runner PHẢI chạy dưới danh nghĩa người thử.
- R3.4 NẾU một phiên bản đem kích hoạt mà điểm gắn `principal` chưa có giá trị đã duyệt, THÌ dịch vụ kích hoạt PHẢI từ chối với 409 `binding_unset` (tenant-config:R7.2) và không tạo đăng ký.
- R3.5 NẾU tài khoản dịch vụ chạy mất quyền đọc một trường mà điều kiện của trình kích hoạt dùng, THÌ dịch vụ kích hoạt PHẢI từ chối kích hoạt và không tạo đăng ký.

### R4 — Nguồn dữ liệu Data Hub: loại `endpoint` có id công khai ngẫu nhiên và schema

Một nguồn dữ liệu là thành phần loại `endpoint` với id công khai ≥ 130 bit và một schema mỗi trường mang loại dữ liệu cá nhân và một mô tả ngữ nghĩa cho AI (YC42, YC84; ADR-0113 (Proposed) quyết 5).

- R4.1 NẾU một trường của schema `dw.endpoint/v1` thiếu `pd_category`, THÌ loại `endpoint` PHẢI trả 422 `pd_category_required` có con trỏ tới trường và không niêm phong.
- R4.2 Schema của loại `endpoint` PHẢI là một danh sách trường phẳng, mỗi trường mang khóa, kiểu, `pd_category` và một mô tả ngữ nghĩa cho AI.
- R4.3 KHI một nguồn dữ liệu được tạo, dịch vụ Data Hub PHẢI cấp một id công khai ngẫu nhiên ít nhất 130 bit, khác quy ước id thành phần.
- R4.4 KHI người giữ `studio.datahub.manage` sao chép cURL của một nguồn dữ liệu, trang Data Hub PHẢI cho một request mẫu không chứa bí mật nào.
- R4.5 KHI người giữ `studio.datahub.manage` vô hiệu hóa một nguồn dữ liệu, dịch vụ Data Hub PHẢI ngừng nhận sự kiện của nguồn đó và giữ dữ liệu đã nhận.
- R4.6 NẾU người gọi xóa một nguồn dữ liệu còn đăng ký kích hoạt, THÌ API Data Hub PHẢI trả 409 `artifact_in_use` và không xóa.

### R5 — Ingress: tenant từ endpoint, chữ ký trước mọi xử lý, lưu rồi chạy sau

Data Hub nhận một sự kiện có chữ ký, lấy tenant từ endpoint, chống trùng, lưu rồi trả 2xx dưới một giây, và không tự bắt đầu lượt chạy nào (YC42, YC43, YC44; ADR-0113 (Proposed) quyết 5).

- R5.1 KHI một sự kiện tới `POST /api/v1/hooks/in/{public_id}`, Data Hub PHẢI lấy tenant từ nguồn dữ liệu được nhắm, không bao giờ từ payload.

Data Hub từ chối và không tạo lượt chạy khi:

| Mã   | NẾU sự kiện tới `POST /api/v1/hooks/in/{public_id}` | THÌ Data Hub trả                                         |
| ---- | --------------------------------------------------- | -------------------------------------------------------- |
| R5.2 | sai chữ ký Standard Webhooks hay token tĩnh         | 401, không lưu dòng mang payload, không lượt chạy        |
| R5.3 | lệch giờ quá ±5 phút                                | 401 `stale_timestamp`                                    |
| R5.4 | thân vượt trần kích thước                           | 413, không đọc hết thân                                  |
| R5.5 | sai lược đồ của nguồn dữ liệu                       | 422 cách ly (`quarantine`), không lặp lại giá trị đã gửi |
| R5.6 | id công khai không tồn tại hay đã vô hiệu           | cùng một mã lỗi và cùng một thân như nhau                |

- R5.7 KHI cùng một `webhook-id` tới lại trong 72 giờ, Data Hub PHẢI trả thành công kèm dấu `duplicate` và không tạo lead hay lượt chạy thứ hai.
- R5.8 KHI một sự kiện hợp lệ được nhận, Data Hub PHẢI lưu một dòng `studio.inbound_events` và trả 2xx trong p95 ≤ 1 giây mà không tự bắt đầu lượt chạy nào; làn `studio_inbound` xin lượt chạy sau.
- R5.9 NẾU một nguồn dữ liệu nhận quá 60 sự kiện mỗi phút (mặc định, công ty đổi được), THÌ Data Hub PHẢI từ chối phần vượt và không gọi AI.
- R5.10 Mô tả ngữ nghĩa AI của một trường PHẢI được đánh dấu là dữ liệu từ ngoài, nên khi vào prompt nó nằm trong khối `<input>` đã escape (ADR-0010 (Accepted); YC48).

### R6 — Lịch sử sự kiện và lưu giữ

Mọi kết quả hiện trong lịch sử sự kiện theo quyền người xem, và mỗi kho dữ liệu cá nhân mới có hạn lưu được một lane thực thi (YC88).

- R6.1 `studio.inbound_events` và `studio.trigger_deliveries` PHẢI mang `tenant_id`, RLS ENABLE và FORCE kể cả partition, và một dòng trong `platform.time_partitioned_tables` với partition DEFAULT.
- R6.2 NẾU người gọi không giữ `studio.datahub.read_payloads`, THÌ lịch sử sự kiện PHẢI không trả payload của sự kiện và che giá trị theo quyền trường của người xem (field-security).
- R6.3 `studio.inbound_events` PHẢI giữ 30 ngày trong thí điểm, do một lane đọc hạn lưu và thực thi.
- R6.4 `studio.inbound_dedupe` PHẢI giữ khóa chống trùng ít nhất 72 giờ, quét mỗi giờ.
- R6.5 KHI chủ thể dữ liệu yêu cầu xóa, cổng yêu cầu chủ thể dữ liệu PHẢI xóa payload của người đó trong `studio.inbound_events` (compliance-pdpl).

## Trong phạm vi

- Bảng và cột ở mục Dữ liệu; route ở mục API; trang ở mục Màn hình.
- Mã: dịch vụ kích hoạt ghi `studio.trigger_subscriptions` và `studio.trigger_deliveries`; route chạy tay và chạy thử; đăng ký kind `endpoint` (`dw.endpoint/v1`) vào `ArtifactKindRegistry`; kiểm điểm gắn kind `principal`; `studio.resolve_inbound_endpoint`; ingress `POST /api/v1/hooks/in/{public_id}`; làn `studio_inbound`; lane lưu giữ `studio.inbound_events` và khóa chống trùng.
- Audit: `studio.datahub.created`, `studio.datahub.disabled`, `studio.trigger.activated`, `studio.trigger.deactivated`.

## Ngoài phạm vi

| Việc                                                                                                  | Vì sao                                                                                          | Chủ                                                    |
| ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| Bộ kiểm chữ ký Standard Webhooks và cột bí mật `inbound_endpoint_id` trên `platform.secret_envelopes` | Kho bí mật và một client ra ngoài có một chủ (ADR-0115 (Proposed))                              | connections-and-vault                                  |
| Hàm định tuyến sự kiện nhà cung cấp, đăng ký ứng dụng Meta, cửa `POST /api/v1/hooks/providers/...`    | W2: Meta Lead Ads, Zalo OA (YC97)                                                               | connections-and-vault; workflow-triggers, đợt sau (W2) |
| Trang lịch sử sự kiện (màn hình lọc, liên kết lượt chạy)                                              | W2: phần lưu giữ ở W1, phần màn hình theo sau                                                   | workflow-triggers, đợt sau (W2)                        |
| Lịch chạy có cấu trúc (`schedule_spec`, làn `studio_schedules`, khóa `sched:<id>:<giờ UTC>`)          | YC46; cần `zoneinfo` kiểm ở ảnh worker (FOG F1)                                                 | workflow-triggers, đợt sau (W2)                        |
| Kích hoạt theo sự kiện bản ghi (outbox, CEL theo cạnh, chống tự kích hoạt, chuỗi sâu 8)               | YC46; cần outbox bản ghi v1 có trường nguồn gốc                                                 | workflow-triggers, đợt sau (W2); custom-objects        |
| Quy trình làm công cụ và kích hoạt từ agent (`workflow.run_status`, trả `waiting` khi còn chờ)        | YC46; cần kind công cụ `workflow` của tools-and-skills                                          | workflow-triggers, đợt sau (W2)                        |
| Chờ sự kiện tương quan (`wait.event`, `correlation_key` theo tenant)                                  | Cần làn hẹn giờ của workflow-engine W2                                                          | workflow-triggers, đợt sau (W3)                        |
| Cờ "Công khai" của đối thủ trên quy trình                                                             | Tầm thấy theo vai và workspace sở hữu, không một boolean hiển thị (ADR-0113 (Proposed))         | không làm                                              |
| Bộ giới hạn tốc độ dùng chung, `RateLimiterPort`                                                      | Giới hạn tốc độ có một chủ (ADR-0121 (Proposed))                                                | usage-and-limits                                       |
| Tài khoản dịch vụ, `grants_cover`, gán vai trò cho nó                                                 | Chủ thể có một chủ (ADR-0103 (Proposed))                                                        | org-and-principals                                     |
| Cửa nhận lượt chạy, hàng đợi, bản kê, chế độ chạy, binding set                                        | Hàng run và vỏ phiên bản có chủ (ADR-0113 (Proposed), ADR-0109 (Proposed), ADR-0110 (Proposed)) | workflow-engine, tenant-config                         |

## Dữ liệu

Mọi bảng mới: `tenant_id`, RLS ENABLE và FORCE, grant cùng migration, tên ràng buộc theo `NAMING_CONVENTION`, revision id hex ngẫu nhiên.

- `studio.trigger_subscriptions`: PK `(tenant_id, id)`; `artifact_id`, `artifact_version_id`; `trigger_kind text NOT NULL` CHECK (`manual`, `endpoint`, `provider_app`, `schedule`, `record_event`, `agent`); `status text NOT NULL` CHECK (`active`, `retired`), không DEFAULT; `run_as_principal_id uuid` NULL; `created_at`; partial unique một `active` mỗi `(tenant_id, artifact_id, trigger_kind)`; RLS tenant.
- `studio.trigger_deliveries`: PK `(tenant_id, id)`; `subscription_id`; `outcome text NOT NULL` CHECK (`run_requested`, `duplicate`, `held_frozen`, `refused_killed`, `quarantined`, `rejected`); `run_id uuid` NULL; `occurred_at timestamptz NOT NULL`; phân vùng tháng theo `occurred_at` có DEFAULT, RLS từng phân vùng, append-only, đăng ký `platform.time_partitioned_tables`.
- `studio.inbound_endpoints`: PK `(tenant_id, id)`; `artifact_id` FK tới thành phần kind `endpoint`; `public_id text NOT NULL` ngẫu nhiên ≥ 130 bit, UNIQUE toàn cục; `status text NOT NULL` CHECK (`active`, `disabled`); `inbound_endpoint_id` trỏ bí mật của connections-and-vault; `created_at`; RLS tenant.
- `studio.inbound_events`: PK `(tenant_id, id)`; `endpoint_id`; `webhook_id text`; `status text NOT NULL` CHECK (`accepted`, `quarantined`, `rejected`); `payload jsonb`; `error text` NULL; `received_at timestamptz NOT NULL`; phân vùng tháng theo `received_at` có DEFAULT, RLS từng phân vùng, đăng ký `platform.time_partitioned_tables`; `dw_app` không UPDATE payload; payload cần `studio.datahub.read_payloads`.
- `studio.inbound_dedupe`: PK `(tenant_id, endpoint_id, webhook_id)`; `expires_at timestamptz NOT NULL`; index `(expires_at)` cho lane quét; RLS tenant.
- Hàm `studio.resolve_inbound_endpoint(public_id text)` SECURITY DEFINER trả `(tenant_id, endpoint_id)`, theo quy tắc hàm definer; tenant không bao giờ lấy từ header hay payload.
- Điểm gắn kind `principal` vào `ConfigKindRegistry` của tenant-config; kind `endpoint` (`dw.endpoint/v1`) vào `ArtifactKindRegistry`.

## API

- `POST /api/v1/studio/workflows/{artifact_id}/runs` (quyền `studio.workflow.run`, `Idempotency-Key` bắt buộc).
- `POST /api/v1/studio/workflows/{artifact_id}/versions/{version_id}/test-runs` (quyền `runs.test`, chỉ `test` hoặc `simulate`).
- `POST /api/v1/hooks/in/{public_id}` (công khai, kiểm chữ ký trước mọi xử lý, 2xx dưới 1 giây).
- `GET /api/v1/studio/data-sources`, `POST /api/v1/studio/data-sources`, `GET|PATCH|DELETE .../{id}`, `POST .../{id}/disable` (quyền `studio.datahub.read`, `studio.datahub.manage`); lịch sử sự kiện payload cần `studio.datahub.read_payloads`.
- Lỗi theo vỏ problem+json của ADR-0108 (Proposed); `details.reason_code`: `stale_timestamp`, `signature_invalid`, `payload_too_large`, `schema_invalid`, `binding_unset`, `artifact_in_use`.

## Màn hình

- Trang "Nguồn dữ liệu" (`/studio/data-sources`): danh sách, bước "Cơ bản", bước "Schema" (khóa trường, kiểu, mô tả ngữ nghĩa AI, `pd_category`, bắt buộc), nút "Sao chép cURL", "Vô hiệu hóa", "Xóa"; không cuộn ngang ở 320 px. Trang lịch sử sự kiện là W2.

## Kiểm soát

| #    | Kiểm soát                       | Yêu cầu    | Test âm                                                                                                                                                       |
| ---- | ------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TR1  | Tenant chỉ đến từ endpoint      | R5.1       | Thân có `tenant_id` của tenant khác → bị bỏ qua, lượt chạy thuộc tenant của nguồn dữ liệu; đọc tenant từ payload → test đỏ                                    |
| TR2  | Chữ ký trước mọi xử lý          | R5.2       | Sai một byte chữ ký → 401, không dòng sự kiện mang payload, không lượt chạy; kiểm chữ ký sau khi lưu → test đỏ                                                |
| TR3  | Chống phát lại                  | R5.3       | Chữ ký đúng nhưng timestamp cũ 6 phút → 401 `stale_timestamp`; bỏ kiểm lệch giờ → test đỏ                                                                     |
| TR4  | Trần kích thước                 | R5.4       | Thân 65.537 byte → 413 mà không đọc hết thân                                                                                                                  |
| TR5  | Chống trùng 72 giờ              | R5.7       | Gửi lại sau 71 giờ → `duplicate`, không lượt chạy thứ hai; cùng `webhook-id` ở hai nguồn → hai sự kiện; bỏ chống trùng → test đỏ                              |
| TR6  | Không echo                      | R5.5       | Thân 422 không chứa giá trị nào đã gửi                                                                                                                        |
| TR7  | Id không dò được                | R5.6       | Id không tồn tại và id đã vô hiệu → cùng một mã lỗi, cùng một thân                                                                                            |
| TR8  | Run-as không là người phát hành | R3.2, R3.4 | Người phát hành rời tenant → lượt chạy vẫn chạy bằng tài khoản dịch vụ; kích hoạt thiếu điểm gắn `principal` → 409; gắn người phát hành làm chủ thể → test đỏ |
| TR9  | Kill thì không có lượt chạy     | R1.4       | Sự kiện sau tắt khẩn → lần kích hoạt `refused_killed`, không lượt chạy; bỏ kiểm tắt khẩn → test đỏ                                                            |
| TR10 | Mô tả ngữ nghĩa AI là dữ liệu   | R5.10      | Mô tả chứa lệnh chèn → chỉ xuất hiện trong khối `<input>` đã escape khi vào prompt; bỏ bọc → test đỏ                                                          |
| TR11 | Payload cần quyền riêng         | R6.2       | Người chỉ có `studio.datahub.read` không thấy payload trong lịch sử; bỏ kiểm quyền → test đỏ                                                                  |
| TR12 | Chạy thử không nhận chế độ Thật | R2.2       | `test-runs` với `live` → 422, không lượt chạy; bỏ kiểm chế độ → test đỏ                                                                                       |

## Tiêu chí thành công

- YC94 (W1): một lead có chữ ký từ form website tạo đúng một lượt chạy quy trình Tiếp nhận lead, mỗi lead một lượt, trong `live` và `test`.
- YC44 (W1): 100% sự kiện hoặc đã trả thành công, hoặc thành lead, hoặc nằm trong lịch sử sự kiện kèm lỗi đọc được.

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát TR1-TR12 có test âm đã thấy đỏ khi gỡ kiểm soát, ghi ở Comments của ticket cài nó.
- `make ci && make test-integration` xanh; form có chữ ký và lead thử tạo đúng một lượt chạy mỗi lead có test.
- `reviewing-feature-security` và `reviewing-deployment-security` đã chạy trên từng ticket; `.claude/plans/studio.md` ghi lát W1 đã xong.

## Phụ thuộc

- workflow-engine: `RunRequestService` và cột run Studio (`.claude/plans/studio/workflow-engine/issues/02-cot-run-va-cua-nhan-run.md`), làn `studio_runs` (`.claude/plans/studio/workflow-engine/issues/04-lan-studio-runs.md`); các mã workflow-engine:R3.3, R3.6.
- org-and-principals: tài khoản dịch vụ, `grants_cover`, kiểm gắn run-as (`.claude/plans/studio/org-and-principals/issues/03-tai-khoan-dich-vu-run-as.md`, org-and-principals:R6.5, R6.7).
- tenant-config: điểm gắn kind `principal` và binding set (`.claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md`, tenant-config:R7.2), vỏ phiên bản và kind (tenant-config/02), bản kê (tenant-config/04).
- connections-and-vault: bộ kiểm chữ ký Standard Webhooks và cột `inbound_endpoint_id` (`.claude/plans/studio/connections-and-vault/issues/03-egress-client-allowlist-va-chu-ky.md`).
- record-access: run không người kích hoạt dùng tầm của tài khoản dịch vụ (record-access:R6.9); studio-skeleton: schema `studio`, nhóm route, `ensure_time_partitions`; app-standards: problem+json và `Idempotency-Key` (app-standards:R2.7); compliance-pdpl: `pd_category` và cổng yêu cầu chủ thể dữ liệu.
- Kiểm lại khi: DO-06 chọn id kết nối trong phiên bản hay giờ lịch là phần phiên bản → R3.1, ticket 01; DO-12 chọn principal khác khuyến nghị → R3.2, ticket 01; DO-52 đổi hạn lưu → R6.3, R6.4, ticket 02; connections-and-vault đổi hình bộ kiểm chữ ký → R5.2, ticket 02.

## Câu hỏi còn mở

- Q1. Lượt chạy không người kích hoạt chạy dưới danh nghĩa tài khoản dịch vụ gắn theo phiên bản qua điểm gắn `principal`, không bao giờ người phát hành (DO-12, khuyến nghị a)? Chủ: Đạt và người yêu cầu. Chặn: R3.2, ticket 01.
- Q2. Tài liệu chỉ giữ tên điểm gắn còn giá trị nằm trong Bộ giá trị gắn được duyệt và ghim theo lượt chạy, và giờ của lịch là giá trị điểm gắn (DO-06, khuyến nghị a)? Chủ: Đạt. Chặn: R3.1, ticket 01.
- Q3. Thời hạn lưu của mọi kho mới là như khuyến nghị (sự kiện nhận 30 ngày, lần kích hoạt 90 ngày, khóa chống trùng 72 giờ) (DO-52)? Chủ: luật sư và Đạt. Chặn: R6.3, R6.4, ticket 02.

## Quyết định

- 23/10/2026 (người yêu cầu): D11: hai người luôn luôn; điểm gắn `principal` do người giữ mọi quyền của tài khoản dịch vụ đề xuất và người khác duyệt (YC8, ADR-0110 (Proposed)). Sửa: R3.1.
- 23/10/2026 (người yêu cầu): D12: 60 sự kiện mỗi phút là mặc định đổi được của một nguồn dữ liệu (R5.9); số đo p99 dưới 1 giây với 100 yêu cầu mỗi giây đo ở ticket 02.
- 23/10/2026 (agent, tạm): DO-12 theo khuyến nghị (a): lượt chạy không người chạy bằng tài khoản dịch vụ là dòng `platform.users` kind `service`. Sửa: R3.2. Nếu sai thì: R3.2 đổi chủ thể run-as và ticket 01 chờ lựa chọn mới.
- 23/10/2026 (agent, tạm): DO-06 theo khuyến nghị (a): tài liệu giữ tên điểm gắn, giá trị ghim theo lượt chạy; giờ của lịch là điểm gắn kind `schedule` (W2). Sửa: R3.1. Nếu sai thì: id kết nối và giờ nằm trong phiên bản.
- 23/10/2026 (agent, tạm): DO-52 theo khuyến nghị (a): `studio.inbound_events` 30 ngày, `studio.trigger_deliveries` 90 ngày, khóa chống trùng 72 giờ, do lane lưu giữ của telemetry-and-audit đọc. Sửa: R6.3, R6.4. Nếu sai thì: lane đọc hạn khác, R6.3 và R6.4 đổi số.
- 23/10/2026 (agent, tạm): DO-39 theo khuyến nghị (a): sự kiện vào tới một tenant bị khóa trả 503 và không lưu gì. Nếu sai thì: ingress thêm một nhánh lưu rồi giữ cho tới khi mở khóa.
- 23/10/2026 (agent, tạm): chữ ký theo Standard Webhooks (HMAC có timestamp) hoặc token tĩnh, qua một module kiểm của connections-and-vault, thứ tự theo ADR-0008 (Accepted). Sửa: R5.2, R5.3. Nếu sai thì: đổi sang sơ đồ chữ ký khác cùng vị trí trong ingress.
- 23/10/2026 (agent, tạm): học từ phân tích đối thủ (`discovery/config-chang.md`, mẫu học, không phải mã của họ): mỗi trường của nguồn dữ liệu mang một mô tả ngữ nghĩa cho AI (YC84, YC42, YC43), nhưng ở Studio mô tả là dữ liệu từ ngoài nên bọc `<input>` khi vào prompt (YC48) và thêm chữ ký, chống trùng, id ≥ 130 bit, `pd_category`. Sửa: R4.2, R5.10.
- 23/10/2026 (agent, tạm): học từ phân tích đối thủ: nút "Sao chép cURL" cấp cho integrator một request đúng, nhưng không chứa bí mật. Sửa: R4.4.
- 23/10/2026 (agent, tạm): Bỏ qua cờ "Công khai" của đối thủ trên quy trình (`discovery/config-chang.md`): Studio quyết tầm thấy theo vai và workspace sở hữu, không bằng một boolean hiển thị (thẻ EVAL của họ ghi "private" mà nhãn "Công khai" là hai nguồn một sự thật). Sửa: Ngoài phạm vi.

## Danh sách ticket

| #   | Ticket                                                                                                                                          |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Sổ kích hoạt, chạy tay và chạy mô phỏng, chạy dưới danh nghĩa tài khoản dịch vụ qua điểm gắn](issues/01-so-kich-hoat-chay-tay-va-danh-tinh.md) |
| 02  | [Data Hub: endpoint nhận dữ liệu, ingress, chống trùng, bảng sự kiện, làn studio_inbound](issues/02-data-hub-endpoint-va-ingress.md)            |
