# Chuẩn ứng dụng nền tảng: vỏ lỗi, khóa chống lặp, ETag, phân trang, lọc

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Mọi route mới của Studio và của nền tảng nói cùng một quy ước HTTP: một mô tả lỗi problem+json, khóa chống lặp gắn người gọi đã xác minh, ETag với `If-Match`, phân trang keyset có kiểu, cây lọc JSON và một kiểm hình kế hoạch truy vấn trong CI (ADR-0108 (Accepted)). API bản ghi của custom-objects, vỏ phiên bản của tenant-config và mọi API quản trị của lát Marketing dùng các quy ước này, nên spec này đi trước chúng. Ý định: một quy ước HTTP cho mọi route, để không spec nào tự đặt hình lỗi, khóa hay con trỏ của riêng nó.

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- `ErrorResponse` gồm `code`, `message`, `details`, `request_id` và tự nhận là vỏ lỗi duy nhất (`apps/api/src/dw_api/errors.py:28-34`). Ràng buộc: client đang đọc bốn trường này, nên vỏ mới chỉ được thêm.
- Chỉ có handler cho `ReplayedResponse`, `DWError` và `Exception` (`apps/api/src/dw_api/exception_handlers.py:14`, `apps/api/src/dw_api/exception_handlers.py:28`, `apps/api/src/dw_api/exception_handlers.py:41`). Thiếu: lỗi schema, đường lạ và sai method trả hình riêng của FastAPI.
- `details` bị chuỗi hóa (`apps/api/src/dw_api/exception_handlers.py:33`). Thiếu: `details` có cấu trúc.
- Mọi 401 kèm `WWW-Authenticate: Bearer` (`apps/api/src/dw_api/exception_handlers.py:37-38`). Ràng buộc: giữ header này.
- `request_id` lấy từ `X-Request-ID` khi không quá 128 ký tự, không thì sinh mới (`apps/api/src/dw_api/middleware/request_id.py:16-18`). Ràng buộc: đây là nguồn của `instance`.
- Client web thay một lỗi không parse được bằng `code` `internal` và `message` "HTTP" nối mã trạng thái (`packages/typescript/api-client/src/client.ts:270-282`). Thiếu: người dùng thấy "HTTP 422" thay vì lỗi của trường.
- Schema zod của lỗi không strict (`packages/typescript/contracts/src/error.ts:7-12`). Ràng buộc: thêm trường không làm vỡ client cũ.
- `ErrorCode` không có mã cho 405, 412, 428 (`packages/python/dw_kernel/src/dw_kernel/errors.py:13-30`). Thiếu: sai method và điều kiện ghi chưa có mã máy đọc được.
- `ERROR_STATE` buộc map mọi mã lỗi bằng `satisfies` (`packages/typescript/ui/src/region-state.tsx:29-48`). Ràng buộc: mã mới phải có vùng hiển thị.
- `RequestFingerprint` gồm method, đường, workspace và băm body, không có người gọi (`packages/python/dw_platform/src/dw_platform/application/idempotency.py:47-68`). Thiếu: người khác cùng tenant và workspace gửi lại khóa và body thì nhận câu trả lời đã lưu, còn handler cùng phép kiểm quyền của nó không chạy.
- `complete` và `release` chỉ so `completed_at IS NULL` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/idempotency_store.py:130-164`), và giữ chỗ bị giành lại sau 5 phút (`packages/python/dw_platform/src/dw_platform/application/idempotency.py:44`). Thiếu: không có token rào.
- Câu trả lời lưu chỉ gồm status và body (`packages/python/dw_platform/src/dw_platform/application/idempotency.py:71-78`), và lần phát lại chỉ kèm `Idempotency-Key` (`apps/api/src/dw_api/exception_handlers.py:22-26`). Thiếu: `ETag`, `Location`.
- Bảng khóa hứa một lượt xóa theo tuổi và có index `created_at` cho nó (`db/migrations/sql/0002_http_idempotency.sql:67-70`). Thiếu: chưa gì xóa, nên khóa và body đã lưu ở lại mãi (failure-modes #6).
- Khóa dài tối đa 255 ký tự (`apps/api/src/dw_api/dependencies/idempotency.py:76`), và query string thuộc đích của khóa (`apps/api/src/dw_api/dependencies/idempotency.py:191-200`). Ràng buộc: hai luật này giữ nguyên.
- Lane dọn hàng vận hành ghi số đếm, không ghi audit từng dòng (`docs/adr/0011-a-background-lane-audits-as-itself.md:38-43`). Ràng buộc: lane dọn khóa theo cùng cách.
- Lane dọn checkpoint đọc mọi tenant qua policy `worker_drain_` (`db/migrations/versions/7bbd071748ca_run_checkpoints_worker_drain_and_sweep_.py:46-58`). Ràng buộc: mẫu cho lane dọn khóa.
- CORS cho phép `Idempotency-Key` mà không có `If-Match` (`apps/api/src/dw_api/main.py:52-60`), và chỉ lộ `X-Request-ID`, `Retry-After` (`apps/api/src/dw_api/main.py:112`). Thiếu: trình duyệt không gửi được `If-Match` và không đọc được `ETag`, `Location`.
- Con trỏ chỉ mang `datetime` (`packages/python/dw_kernel/src/dw_kernel/pagination.py:107-119`), từ chối mọi phiên bản khác 1 (`packages/python/dw_kernel/src/dw_kernel/pagination.py:50-53`) và chuỗi hóa giá trị lọc trong dấu vân tay (`packages/python/dw_kernel/src/dw_kernel/pagination.py:91-104`). Thiếu: con trỏ cho cột không phải thời gian.
- Vị từ và thứ tự keyset chỉ có chiều giảm (`packages/python/dw_platform/src/dw_platform/adapters/persistence/keyset.py:22-53`). Thiếu: chiều tăng và NULL cuối.
- Năm route phân trang hiện có: duyệt, audit, feedback (`packages/python/dw_platform/src/dw_platform/adapters/persistence/repositories.py:177-184`, `packages/python/dw_platform/src/dw_platform/adapters/persistence/repositories.py:253-257`, `packages/python/dw_platform/src/dw_platform/adapters/persistence/repositories.py:374-376`), tài liệu tri thức (`packages/python/dw_knowledge/src/dw_knowledge/gateway.py:447-451`) và mục memory (`packages/python/dw_memory/src/dw_memory/service.py:780-784`). Ràng buộc: kiểm hình kế hoạch phủ cả năm.
- Feedback sắp theo `created_at DESC, id DESC` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/repositories.py:376`) trên index `(tenant_id, created_at)` không mang `id` (`db/migrations/sql/0001_platform_baseline.sql:665`). Thiếu: thứ tự trang không có index mang trọn.
- Danh sách audit theo lượt chạy lọc `run_id` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/repositories.py:234-246`), mà không index audit nào mang `run_id` (`db/migrations/sql/0001_platform_baseline.sql:656`, `db/migrations/versions/6d4aed20ccf2_platform_approval_and_audit_pages_carry_.py:102-105`). Thiếu: không index nào thu hẹp truy vấn đó theo `run_id`.
- Chuyển trạng thái viết là `POST` sub-resource có động từ, ví dụ `/workspaces/{workspace_id}/archive` (`apps/api/src/dw_api/routes/v1/admin_console.py:230`). Ràng buộc: cách viết custom method của nền tảng.

## Mục tiêu

### R1 — Mọi lỗi là một mô tả lỗi problem+json [Sửa]

Trước đây: lỗi trả `ErrorResponse` dạng `application/json`, còn lỗi schema, đường lạ và sai method trả hình của FastAPI (`apps/api/src/dw_api/exception_handlers.py:28-39`).

Client và người tích hợp đọc mọi lỗi theo một hình máy đọc được, mà không mất trường nào đang đọc.

- R1.1 KHI một route trả lỗi, API PHẢI trả `Content-Type: application/problem+json` với `type` là `urn:dw:problem:` nối mã lỗi, `title` tiếng Anh cố định theo mã, `status` bằng mã HTTP, `detail`, và `instance` là `urn:dw:request:` nối `request_id`.
- R1.2 KHI một route trả lỗi, mô tả lỗi PHẢI mang các trường mở rộng `code`, `message` bằng `detail`, `details` dạng JSON có cấu trúc, `request_id` và `trace_id` (id trace OpenTelemetry đang chạy, `null` khi không có).
- R1.3 KHI body, tham số hay header sai schema, API PHẢI trả 422 với `code` `validation_failed` và `errors[]`, mỗi phần tử có đúng một trong `pointer` (JSON pointer vào body), `parameter`, `header`, kèm `code` và `detail`.
- R1.4 KHI người gọi gọi một đường không tồn tại, API PHẢI trả 404 problem+json với `code` `not_found`.
- R1.5 KHI người gọi dùng một method mà đường đó không có, API PHẢI trả 405 problem+json với `code` `method_not_allowed` và header `Allow`.
- R1.6 NẾU handler ném một lỗi bất ngờ, THÌ API PHẢI trả 500 problem+json với `code` `internal` mà không có stack trace, câu SQL, tên bảng hay giá trị của dòng vi phạm ràng buộc.
- R1.7 Tài liệu OpenAPI PHẢI khai schema `Problem` cho mọi phản hồi 4XX và 5XX của mọi operation và không còn `HTTPValidationError`.
- R1.8 KHI API trả 422 có `errors[]`, client web PHẢI trả một lỗi mang `code` `validation_failed` và `errors[]` đã parse, không thay bằng `internal`.

### R2 — Khóa chống lặp gắn người gọi đã xác minh, có rào và hết hạn [Sửa]

Trước đây: dấu vân tay không có người gọi (`packages/python/dw_platform/src/dw_platform/application/idempotency.py:47-68`) và `complete` không so token (`packages/python/dw_platform/src/dw_platform/adapters/persistence/idempotency_store.py:130-150`).

Người gọi thử lại một yêu cầu ghi nhận lại kết quả lần đầu, và chỉ chính người đó (YC5).

- R2.1 KHI cùng người gọi gửi lại cùng `Idempotency-Key` với cùng method, đường, workspace và body sau khi lần đầu thành công, API PHẢI trả lại status, body, `ETag` và `Location` đã lưu mà không chạy handler lần hai.
- R2.2 NẾU một người gọi khác trong cùng tenant, khác `principal_id` hay khác grant `support` của ADR-0024 (Proposed), gửi một `Idempotency-Key` đã dùng, THÌ API PHẢI trả 409 `idempotency_conflict`, không trả body đã lưu và không chạy handler.
- R2.3 NẾU dòng của khóa được ghi trước thay đổi này (`caller_ref` rỗng), THÌ API PHẢI trả 409 `idempotency_conflict` cho mọi người gọi gửi lại khóa đó và không phát lại.
- R2.4 KHI một yêu cầu giành lại một giữ chỗ đã quá 5 phút, kho khóa PHẢI thay token rào của dòng bằng một token mới.
- R2.5 NẾU yêu cầu đã mất giữ chỗ gọi hoàn tất hay nhả khóa bằng token cũ, THÌ kho khóa PHẢI không ghi và không xóa dòng của khóa đó.
- R2.6 NẾU một route bắt buộc khóa chống lặp nhận yêu cầu thiếu `Idempotency-Key`, THÌ API PHẢI trả 422 với `details.reason_code` `idempotency_key_required` và không chạy handler.
- R2.7 ĐỐI VỚI `POST` khởi một tác vụ chạy nền, một batch hay một upsert, route đó PHẢI bắt buộc `Idempotency-Key`.
- R2.8 KHI lane `idempotency_sweep` chạy, lane `idempotency_sweep` PHẢI xóa mọi dòng của `platform.idempotency_keys` có `created_at` cũ hơn 24 giờ, ở mọi tenant, và giữ mọi dòng khác.
- R2.9 KHI lane `idempotency_sweep` xóa dòng, lane `idempotency_sweep` PHẢI ghi số dòng đã xóa vào log và không ghi dòng audit nào (ADR-0011 (Accepted), mục "Not applied").

### R3 — ETag, If-Match và JSON Merge Patch cho route sửa

Người sửa một tài nguyên có phiên bản bản ghi không ghi đè thay đổi của người khác mà không biết.

- R3.1 KHI API trả một tài nguyên có phiên bản bản ghi, API PHẢI gửi `ETag` mạnh là phiên bản đó trong ngoặc kép, ví dụ `"7"`.
- R3.2 NẾU `If-Match` không khớp mạnh với phiên bản hiện tại, kể cả khi nó là một ETag yếu như `W/"7"`, THÌ API PHẢI trả 412 `precondition_failed` và không đổi tài nguyên, phiên bản hay audit nào.
- R3.3 NẾU một route mà tài nguyên bắt buộc điều kiện nhận yêu cầu ghi thiếu `If-Match`, THÌ API PHẢI trả 428 `precondition_required` và không đổi gì.
- R3.4 NẾU yêu cầu tạo mang `If-None-Match: *` mà tài nguyên đã tồn tại, THÌ API PHẢI trả 412 `precondition_failed` và không tạo gì.
- R3.5 KHI `PATCH` gửi body `application/merge-patch+json` hay `application/json`, API PHẢI áp ngữ nghĩa RFC 7396: khóa mang `null` xóa trường, khóa vắng giữ nguyên, đối tượng lồng được trộn.
- R3.6 API PHẢI cho trình duyệt gửi `If-Match`, `If-None-Match` và đọc `ETag`, `Location` qua CORS.

### R4 — Phân trang keyset có kiểu, không trùng không sót

Người đọc danh sách sắp theo một trường, tăng hay giảm, nhận mỗi dòng đúng một lần (YC27).

- R4.1 KHI một route danh sách còn trang kế, API PHẢI trả con trỏ phiên bản 2 mang giá trị sắp có thẻ kiểu (`text`, `int`, `float`, `date`, `datetime`, `bool`, `null`), pha `values` hay `nulls`, và `id` của dòng cuối.
- R4.2 KHI người gọi duyệt hết một danh sách sắp theo cột có giá trị trùng và NULL, theo chiều tăng hay giảm, API PHẢI trả mỗi dòng đúng một lần và xếp mọi dòng NULL sau mọi dòng có giá trị.
- R4.3 NẾU một con trỏ được cấp cho truy vấn khác (route, cây lọc, `order_by` hay `fields` khác), THÌ API PHẢI trả 422 `validation_failed` và không trả dòng nào.
- R4.4 NẾU một người gọi gửi con trỏ do người khác nhận, THÌ API PHẢI chỉ trả những dòng chính người gọi đó đọc được theo quyền hiện tại của họ.
- R4.5 KHI hai yêu cầu gửi cùng một cây lọc với thứ tự khóa JSON khác nhau, API PHẢI nhận con trỏ của yêu cầu này cho yêu cầu kia.

### R5 — Cây lọc JSON, `order_by` và `fields`

Route danh sách nhận một ngôn ngữ chọn bản ghi có giới hạn, với lỗi trỏ đúng chỗ (ADR-0108 (Accepted) điểm 2).

- R5.1 NẾU cây lọc vượt một giới hạn (độ sâu quá 5, quá 50 lá, `$in` quá 500 giá trị, chuỗi quá 1.024 byte UTF-8), THÌ route danh sách PHẢI trả 422 với `errors[].pointer` trỏ vào nút vượt và không chạy truy vấn; cây đúng bằng giới hạn được nhận.
- R5.2 NẾU cây lọc nêu trường không lọc được hay toán tử không hợp kiểu của trường, THÌ route danh sách PHẢI trả 422 với `errors[].pointer` trỏ vào lá đó.
- R5.3 KHI người gọi gửi `order_by` theo AIP-132, ví dụ `name desc, created_at`, route danh sách PHẢI sắp theo đúng các trường đó và luôn thêm `id` làm khóa cuối.
- R5.4 NẾU `order_by` nêu trường không sắp được, THÌ route danh sách PHẢI trả 422 với `errors[].parameter` bằng `order_by`.
- R5.5 KHI người gọi gửi `fields`, route danh sách PHẢI chỉ trả các trường được nêu cùng `id`.
- R5.6 KHI route danh sách trả 422 cho cây lọc, `order_by` hay `fields`, route danh sách PHẢI đặt `code` là `validation_failed` và mã lý do của từng lỗi, như `field_not_readable` hay `field_not_filterable`, vào `errors[].code`.

### R6 — Kiểm hình kế hoạch truy vấn trong CI

Một truy vấn phân trang không có index mang trọn làm CI đỏ, kể cả khi bảng thử nhỏ (`CLAUDE.md` "Data model rules").

- R6.1 NẾU kế hoạch của một câu lệnh phân trang lấy từ mã repository, chạy dưới vai `dw_app` với `app.tenant_id` đặt sẵn và `enable_seqscan = off`, có cột vị từ không nằm trong `Index Cond` hay `Recheck Cond`, hay có nút `Sort` trên khóa sắp, THÌ kiểm hình kế hoạch PHẢI đỏ và nêu câu lệnh cùng cột.
- R6.2 Kiểm hình kế hoạch PHẢI chạy trên năm route phân trang hiện có và trên danh sách audit theo lượt chạy.

## Hành vi giữ nguyên

- G1 KHI API trả 401, API PHẢI TIẾP TỤC gửi `WWW-Authenticate: Bearer` (test: `test_me_without_a_verifiable_token_is_401_with_a_challenge`).
- G2 KHI một client đọc `code`, `message`, `details` và `request_id` của một lỗi, API PHẢI TIẾP TỤC trả bốn trường đó với cùng tên và nghĩa (test: `test_an_error_keeps_code_message_details_and_request_id`, viết trước thay đổi và xanh ở commit gốc).
- G3 KHI một mã lỗi có ở Python mà không có ở TypeScript, test hợp đồng PHẢI TIẾP TỤC đỏ (test: `test_the_typescript_error_codes_mirror_the_python_ones`).
- G4 KHI cùng người gọi gửi cùng khóa với body khác, API PHẢI TIẾP TỤC trả 409 `idempotency_conflict` (test: `test_the_same_key_with_a_different_body_is_a_conflict`).
- G5 KHI khóa còn được giữ bởi một yêu cầu đang chạy, API PHẢI TIẾP TỤC trả 409 `conflict` mà không chạy handler (test: `test_a_request_still_in_flight_is_refused_rather_than_run_again`).
- G6 KHI lần đầu thất bại với 5xx, API PHẢI TIẾP TỤC nhả khóa để lần thử lại chạy được (test: `test_a_failed_request_releases_its_key_so_the_retry_can_work`).
- G7 KHI người gọi gửi một con trỏ phiên bản 1, route danh sách PHẢI TIẾP TỤC trả trang kế từ đúng vị trí đó (test: `test_a_v1_cursor_still_resumes_where_it_left_off`, viết trước thay đổi và xanh ở commit gốc).
- G8 KHI người gọi gửi một con trỏ phiên bản 0 hay phiên bản lạ, API PHẢI TIẾP TỤC từ chối với `validation_failed` (test: `test_a_cursor_from_an_older_format_version_is_refused`).

## Trong phạm vi

- Mô tả lỗi problem+json, các handler và schema `Problem` trong OpenAPI; mã `method_not_allowed`, `precondition_failed`, `precondition_required` cùng bản TypeScript; client web đọc `errors[]`.
- Khóa chống lặp: cột `caller_ref`, `reservation_token`, `response_headers` của `platform.idempotency_keys`, policy drain, lane `idempotency_sweep`, dependency khóa bắt buộc.
- ETag, `If-Match`, `If-None-Match`, JSON Merge Patch và CORS cho các header đó.
- Con trỏ phiên bản 2, keyset hai chiều với NULL cuối, cây lọc JSON, `order_by`, `fields`.
- Kiểm hình kế hoạch trong CI và các index mà nó đòi sửa.

## Ngoài phạm vi

| Việc                                                                                     | Vì sao                                                                                                                            | Chủ                                 |
| ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------- |
| R2.7: từng route bắt buộc `Idempotency-Key` (`POST` khởi tác vụ chạy nền, batch, upsert) | mỗi route chứng minh ở spec mở nó; spec này giao dependency khóa bắt buộc                                                         | custom-objects, tenant-config       |
| Tác vụ chạy nền chuẩn                                                                    | W2                                                                                                                                | app-standards, đợt sau (W2)         |
| Quy ước 429 và header RateLimit chung                                                    | W2; ngoại lệ W1: bộ giới hạn của custom-objects:R7.6 trả 429 kèm `Retry-After` qua `RateLimiterPort` của usage-and-limits (DO-49) | app-standards, đợt sau (W2)         |
| Chính sách ngừng hỗ trợ: báo trước ít nhất 6 tháng trước khi gỡ một route                | W2 (DO-16)                                                                                                                        | app-standards, đợt sau (W2)         |
| Giới hạn kích thước body                                                                 | W2; nhóm `/api/v1/studio` có trần riêng từ W1                                                                                     | app-standards, đợt sau (W2)         |
| OpenAPI theo tenant và HTTP QUERY                                                        | W3                                                                                                                                | app-standards, đợt sau (W3)         |
| Khóa chống lặp của tool, nhận trước (`platform.tool_execution_claims`)                   | ADR-0108 (Accepted) điểm 5                                                                                                        | runtime-hardening, ticket 01        |
| Ngữ pháp khóa cho hiệu ứng của lượt chạy                                                 | ADR-0108 (Accepted) điểm 6                                                                                                        | workflow-engine                     |
| Biến trong cây lọc, chuỗi lọc OData hay AIP-160                                          | chưa route nào đọc; chuỗi có thể đến sau và dịch về cây                                                                           | custom-objects                      |
| `Cache-Control: no-store` cho tài nguyên có bảo vệ theo trường                           | thuộc route bản ghi                                                                                                               | custom-objects, field-security      |
| Bộ đếm giới hạn theo tenant (`RateLimiterPort`), sửa bộ giới hạn tốc độ theo địa chỉ     | không thuộc quy ước HTTP chung (DO-49)                                                                                            | usage-and-limits, runtime-hardening |
| Dịch văn bản lỗi phía máy chủ (`Accept-Language`)                                        | web dựng văn bản từ `code`                                                                                                        | không làm                           |
| OData, GraphQL                                                                           | ngôn ngữ chọn bản ghi là cây lọc                                                                                                  | không làm                           |

## Dữ liệu

- `platform.idempotency_keys` thêm `caller_ref text NOT NULL DEFAULT ''` (`user:` nối `principal_id`, hay `support:` nối `grant_id` khi người gọi làm việc dưới grant của ADR-0024 (Proposed)), `reservation_token uuid NOT NULL DEFAULT gen_random_uuid()`, `response_headers jsonb` với `CHECK (response_headers IS NULL OR jsonb_typeof(response_headers) = 'object')`, chỉ giữ `ETag` và `Location`. Dòng cũ mang `caller_ref = ''`, không bằng người gọi thật nào.
- Policy `worker_drain_idempotency_keys` đọc `app.worker_drain`, theo mẫu lane dọn checkpoint.
- Index cho kiểm hình kế hoạch do test quyết; dự kiến `platform.feedback (tenant_id, created_at DESC, id DESC)` thay `ix_feedback_tenant_created`. Index `platform.audit_events (tenant_id, run_id, occurred_at)` trên bảng cha là index audit theo lượt chạy duy nhất của nền tảng, chủ là ticket 03 (ADR-0122 (Accepted) bỏ `ix_audit_events_run`).

## API

- Mô tả lỗi: `type`, `title`, `status`, `detail`, `instance`, cùng `code`, `message`, `details`, `request_id`, `trace_id`, `errors[]`. Mã mới: `method_not_allowed` (405), `precondition_failed` (412), `precondition_required` (428); `details.reason_code` `idempotency_key_required` (422).
- Header: `ETag`, `If-Match`, `If-None-Match`, `Location`; CORS cho phép `If-Match`, `If-None-Match` và lộ `ETag`, `Location`.
- Danh sách: `cursor` (phiên bản 2), `filter` (cây JSON), `order_by`, `fields`, `limit` (mặc định 50, tối đa 200, như `packages/python/dw_kernel/src/dw_kernel/pagination.py` đang có). Custom method là `POST` sub-resource theo cách viết của nền tảng, ví dụ `/records/batch-create`.

## Kiểm soát

| #     | Kiểm soát                                     | Yêu cầu                | Test âm                                                                                                                                                                                        |
| ----- | --------------------------------------------- | ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| APS1  | Một mô tả lỗi cho mọi route                   | R1.1, R1.3, R1.4, R1.5 | Walker đọc `app.openapi()` (thấy router lồng) gọi mỗi operation với body sai kiểu, cùng một đường lạ và một method sai: mọi phản hồi là problem+json; gỡ handler `RequestValidationError` → đỏ |
| APS2  | Lỗi 500 không lộ chi tiết nội bộ              | R1.6                   | Route thử ném `IntegrityError` mang giá trị dòng → 500 không chứa SQL, tên bảng hay giá trị; gỡ handler `Exception` → đỏ                                                                       |
| APS3  | Phát lại chỉ cho người đã dùng khóa           | R2.2                   | Người B cùng tenant và workspace gửi khóa và body của A → 409, handler không chạy, body của A không có trong phản hồi; bỏ `caller_ref` khỏi phép so → đỏ                                       |
| APS4  | Dòng khóa cũ không phát lại                   | R2.3                   | Dòng có `caller_ref = ''` cùng body → 409; coi `''` là khớp mọi người → đỏ                                                                                                                     |
| APS5  | Giành lại có rào                              | R2.5                   | Sau giành lại, `complete` của chủ cũ với token cũ không ghi; bỏ điều kiện token → đỏ                                                                                                           |
| APS6  | Route bắt buộc khóa không chạy khi thiếu khóa | R2.6                   | Route thử bắt buộc, gọi thiếu header → 422 `idempotency_key_required`, handler không chạy; gỡ dependency → đỏ                                                                                  |
| APS7  | 412 và 428 không ghi gì                       | R3.2, R3.3             | `If-Match` lệch hay yếu → 412, phiên bản không đổi, không dòng audit nào; gỡ phép so → đỏ                                                                                                      |
| APS8  | Con trỏ không cấp quyền                       | R4.4                   | Con trỏ người A nhận ở workspace W1 dùng bởi người B chỉ thuộc W2 → trang chỉ có dòng B đọc được; lấy phạm vi từ con trỏ → đỏ                                                                  |
| APS9  | Cây lọc có giới hạn                           | R5.1                   | Độ sâu 6, 51 lá, `$in` 501 giá trị, chuỗi 1.025 byte → 422 và không câu SQL nào chạy; gỡ giới hạn → đỏ                                                                                         |
| APS10 | Kiểm hình kế hoạch đỏ được                    | R6.1                   | Gỡ index trang feedback trong giao dịch test → đỏ; bảng nhỏ không qua mặt nhờ `enable_seqscan = off` và phép kiểm `Index Cond`                                                                 |

## Tiêu chí xong

- Mọi tiêu chí R và G có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát.
- `make ci` và `make test-integration` xanh; `make generate-contracts` không còn đổi gì trong ảnh chụp OpenAPI và client TypeScript.

## Phụ thuộc

- runtime-hardening: lỗi idempotency mà hai spec cùng thấy chỉ được sửa ở ticket 02 của spec này.
- foundations-hardening: walker của APS1 đọc `app.openapi()`, thấy router lồng dưới FastAPI 0.141.1.
- telemetry-and-audit: span OpenTelemetry mà `trace_id` đọc.
- `AccessContext` do nền tảng dựng từ token đã xác minh: nguồn duy nhất của `caller_ref` (`principal_id`, grant của ADR-0024 (Proposed)).
- telemetry-and-audit ticket 02 chờ ticket 03, vì index audit theo lượt chạy có một chủ ở đây (OPS-b).
- Ticket 02 chờ ticket 01: 422 `idempotency_key_required` của R2.6 và handler phát lại của R2.1 trả qua vỏ problem+json của R1, và hai ticket cùng sửa `apps/api/src/dw_api/exception_handlers.py` (C:app-standards/01~app-standards/02).
- Kiểm lại khi: ADR-0108 (Accepted) đổi trạng thái hay nội dung → cả spec; custom-objects đổi hình cây lọc hay danh sách → R4, R5, ticket 03; custom-objects hay field-security thêm mã lý do cho cây lọc → R5.6, ticket 03; một route phân trang mới → R6.2; một spec mở route bắt buộc khóa → R2.7.

## Câu hỏi còn mở

## Quyết định

- 22/10/2026 (người đặt yêu cầu): D5: port sửa đổi ngày 20/10/2026 về idempotency và token giữ chỗ của si-platform (`docs/adr/0045-one-idempotency-key-store-handed-to-modules-by-the-host.md`, `db/si/migrations/0041_idempotency_reservation_token.sql` trong repo si-platform), dựng lại thành migration Alembic trên `platform`.
- 23/10/2026 (người đặt yêu cầu): D12: 10 triệu bản ghi mỗi đối tượng và 50 triệu mỗi tenant; vì vậy kiểm hình kế hoạch là cổng CI chạy mỗi lần, không là một lần đo.
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: ADR-0108 (Accepted) điểm 4 lưu người gọi thành cột `caller_ref` so riêng, thiết kế ban đầu của spec băm người gọi vào dấu vân tay; theo ADR-0108 (Accepted), để 409 nói được phần nào khác.
- 23/10/2026 (agent, tạm): DO-57 theo khuyến nghị (a): giao diện v1 chỉ tiếng Việt qua khóa thông điệp; web dựng văn bản từ `code` và `errors[].code`, còn `title` giữ tiếng Anh cố định cho máy đọc. Nếu sai thì: thêm bản dịch theo cùng khóa ở web, không đổi mô tả lỗi.
- 23/10/2026 (agent, tạm): lane tên `idempotency_sweep`; thời hạn 24 giờ là hằng trong mã cạnh `STALE_RESERVATION`, không vào `retention@1.7.0.yaml`, vì đây là bộ đệm phát lại chứ không là câu hỏi tuân thủ (tiền lệ `channel_link_nonces_retention`). Nếu sai thì: thời hạn vào tệp chính sách và lane đọc nó.
- 23/10/2026 (agent, tạm): giới hạn chuỗi 1 KB của cây lọc là 1.024 byte UTF-8. Nếu sai thì: đổi một hằng và test APS9.
- 23/10/2026 (Đạt): DO-16 theo (a): problem+json của RFC 9457 cộng trường mở rộng cho toàn nền tảng, custom method là `POST` sub-resource như `/records/batch-create`, và báo trước ít nhất 6 tháng khi ngừng một route (W2); với 422, member `detail` đổi từ mảng của FastAPI thành chuỗi và chi tiết nằm ở `errors[]`, và không client nào trong repo đọc `detail` cũ. Hỏi: Q1. Sửa: hàng ngừng hỗ trợ ở Ngoài phạm vi; ticket 01 và 03 hết chờ.
- 23/10/2026 (Đạt): DO-57 theo (a), xác nhận dòng tạm cùng ngày: web dựng văn bản tiếng Việt từ `code` và `errors[].code`, `title` giữ tiếng Anh cố định cho máy đọc.
- 23/10/2026 (Đạt): ADR-0122 (Accepted) và OPS-b: index audit theo lượt chạy `platform.audit_events (tenant_id, run_id, occurred_at)` có một chủ là ticket 03; ADR-0122 (Accepted) bỏ `ix_audit_events_run`, và telemetry-and-audit/02 chờ ticket 03. Sửa: Dữ liệu, Phụ thuộc, ticket 03.
- 23/10/2026 (Đạt): DO-49 theo (a): giới hạn theo tenant đi qua `RateLimiterPort` của usage-and-limits; ở W1 bộ giới hạn của custom-objects:R7.6 trả 429 kèm `Retry-After` qua port đó, là ngoại lệ W1 của hàng 429 ở Ngoài phạm vi. Sửa: Ngoài phạm vi.
- 23/10/2026 (Đạt): DO-03.2 theo (a): port mã thuần của si-platform cần thỏa thuận viết, ghim commit và dòng đầu `Ported from si-platform`; ticket 02 dựng lại thiết kế idempotency của si-platform thành migration và mã mới, không chép mã, nên không chờ thỏa thuận.
- 23/10/2026 (agent, tạm): mã lý do của từng lỗi cây lọc, `order_by` hay `fields` (`field_not_readable`, `field_not_filterable`) nằm ở `errors[].code`, còn `code` cấp trên là `validation_failed`, theo cách sửa thứ nhất của phát hiện B:app-standards:R1.3~custom-objects:R8.4; custom-objects và field-security trích nguyên văn R5.6. Sửa: thêm R5.6, ticket 03. Nếu sai thì: hai mã thành `code` cấp trên và R1.3 nêu ngoại lệ.

## Danh sách ticket

| #   | Ticket                                                                                                                                |
| --- | ------------------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Một vỏ lỗi problem+json cho mọi route](issues/01-vo-loi-problem-json.md)                                                             |
| 02  | [Idempotency-Key gắn người gọi, token rào, phát lại header, dọn sau 24 giờ](issues/02-khoa-chong-lap-gan-nguoi-goi.md)                |
| 03  | [ETag và If-Match, phân trang keyset có kiểu, cây lọc JSON và kiểm hình kế hoạch trong CI](issues/03-quy-uoc-api-danh-sach-va-sua.md) |
