# 01 — Một vỏ lỗi problem+json cho mọi route

Status: resolved (2026-10-26, feat/app-standards-01)
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R1.6, R1.7, R1.8, R1.9, G1, G2, G3, APS1, APS2, APS11

## Mục tiêu

Lát này cho client, người tích hợp và trang web một hình lỗi duy nhất: mọi route, kể cả lỗi schema, đường lạ và sai method, trả mô tả lỗi problem+json giữ nguyên bốn trường đang được đọc (R1, G1 đến G3, ADR-0108 (Accepted) điểm 1). Biểu mẫu đọc được lỗi của từng trường thay vì "HTTP 422".

## Việc cần làm

1. Trước mọi thay đổi, viết `test_an_error_keeps_code_message_details_and_request_id` trong `apps/api/tests/contract/` trên vỏ hiện tại; test xanh ở commit gốc.
2. `apps/api/src/dw_api/errors.py`: model `Problem` (`type`, `title`, `status`, `detail`, `instance`, `code`, `message`, `details`, `request_id`, `trace_id`, `errors`) và model `ProblemError` (`pointer`, `parameter`, `header`, `code`, `detail`, với đúng một trong ba trường đầu); một hàm dựng duy nhất mà mọi handler gọi; bảng `title` tiếng Anh theo `ErrorCode`.
3. `packages/python/dw_kernel/src/dw_kernel/errors.py`: thêm `METHOD_NOT_ALLOWED = "method_not_allowed"` vào `ErrorCode`, ánh xạ 405 trong `_STATUS_BY_CODE`. Mã 412 và 428 vào cùng người đọc của chúng ở ticket 03.
4. `apps/api/src/dw_api/exception_handlers.py`: handler cho `DWError` (giữ `WWW-Authenticate` của 401), `RequestValidationError` (mỗi `loc` bắt đầu bằng `body` thành `pointer`, `query` hay `path` thành `parameter`, `header` thành `header`), `HTTPException` của Starlette (404 thành `not_found`, 405 thành `method_not_allowed`, giữ header của exception như `Allow`) và `Exception` (500, `internal`, không chuỗi nào của exception); `details` giữ kiểu JSON thay vì `str(v)`; mọi phản hồi lỗi mang `Content-Type: application/problem+json`. Handler phát lại của `ReplayedResponse` không đổi ở ticket này.
5. `trace_id` là id trace của span OpenTelemetry hiện hành, 32 ký tự hex, `null` khi không có span; `instance` là `urn:dw:request:` nối `request_id` của middleware.
6. OpenAPI: phản hồi mặc định 4XX và 5XX trỏ schema `Problem` trên mọi operation; bỏ `HTTPValidationError` và `ValidationError` khỏi `components`; `make generate-contracts` cập nhật `contracts/openapi/openapi.json` và client TypeScript sinh ra.
7. TypeScript: `packages/typescript/contracts/src/error.ts` thêm `problemSchema` không strict (trường mở rộng tùy chọn) và mã `MethodNotAllowed`; `packages/typescript/api-client/src/client.ts` parse mô tả lỗi khi `Content-Type` là `application/problem+json` và giữ `errors[]`; `packages/typescript/ui/src/region-state.tsx` thêm `method_not_allowed`; `apps/web/lib/error-message.ts` thêm `fieldErrors()` trả map từ `pointer` sang `errors[].code`.
8. Test: walker đọc `app.openapi()` (thấy router lồng, không duyệt `app.routes`) gọi mỗi operation có body với một body sai kiểu; một đường lạ; một method sai; route thử ném `IntegrityError` mang giá trị dòng; test client TypeScript với phản hồi 422 có `errors[]`.
9. Theo Q-01a và Q-01b (Đạt, 26/10/2026): `apps/api/src/dw_api/middleware/rate_limit.py` dựng 429 qua `problem_response`, giữ `Retry-After`; `apps/api/src/dw_api/middleware/request_id.py` chỉ nhận `X-Request-ID` khớp `[A-Za-z0-9._-]{1,128}`, không khớp thì sinh mới.

## Tiêu chí chấp nhận

- [x] R1.1 (APS1): mọi phản hồi lỗi của walker có `Content-Type: application/problem+json`; 422 có `type` `urn:dw:problem:validation_failed` và `instance` bằng `urn:dw:request:` nối `X-Request-ID` đã gửi; gỡ handler `RequestValidationError` thì walker đỏ.
- [x] R1.2: một `DWError` với `details={"limit": 3}` trả `details.limit` là số 3, không phải chuỗi; khi có span, `trace_id` có 32 ký tự hex; không có span thì `trace_id` là `null`.
- [x] R1.3 (APS1): body sai kiểu trả 422 với `errors[0].pointer` trỏ đúng trường; tham số query sai trả `errors[0].parameter`.
- [x] R1.4 (APS1): `GET /api/v1/khong-co` trả 404 problem+json với `code` `not_found`.
- [x] R1.5 (APS1): `DELETE` trên một đường chỉ có `GET` trả 405 `method_not_allowed` kèm header `Allow`.
- [x] R1.6 (APS2): route thử ném `IntegrityError` mang giá trị dòng trả 500 mà body không chứa câu SQL, tên bảng hay giá trị đó; gỡ handler `Exception` thì test đỏ.
- [x] R1.7: ảnh chụp OpenAPI không còn `HTTPValidationError`, và mọi operation có 4XX và 5XX trỏ `Problem`.
- [x] R1.8: client TypeScript nhận 422 có `errors[]` trả lỗi `validation_failed` giữ `errors[]`; client đọc `code` và `message` như cũ vẫn đúng.
- [x] R1.1: vượt giới hạn tốc độ trả 429 problem+json với `code` `rate_limited`, `details.limit_per_minute` là số và header `Retry-After`.
- [x] R1.9 (APS11): `X-Request-ID` có dấu cách hay ký tự ngoài bộ cho phép nhận `request_id` mới, giá trị đã gửi không có trong body hay header; một giá trị hợp lệ dài 128 ký tự được giữ, 129 ký tự thì không; gỡ phép kiểm bộ ký tự thì test đỏ.
- [x] G1: `test_me_without_a_verifiable_token_is_401_with_a_challenge` xanh trước và sau thay đổi.
- [x] G2: `test_an_error_keeps_code_message_details_and_request_id` xanh ở commit gốc và sau thay đổi.
- [x] G3: `test_the_typescript_error_codes_mirror_the_python_ones` xanh khi `method_not_allowed` có ở cả hai bên, đỏ khi chỉ có ở Python.
- [x] Xong: `make test-unit test-contract typecheck && pnpm -r --if-present test` xanh.

## Nguồn

- `apps/api/src/dw_api/errors.py:9-38`; spec: R1.1, R1.2.
- `apps/api/src/dw_api/exception_handlers.py:13-49`; spec: R1.3, R1.4, R1.5, R1.6, G1.
- `apps/api/src/dw_api/middleware/request_id.py:16-18`; spec: R1.1.
- `packages/python/dw_kernel/src/dw_kernel/errors.py:13-30`; spec: R1.5.
- `packages/typescript/api-client/src/client.ts:270-282`, `packages/typescript/contracts/src/error.ts:7-12`, `packages/typescript/ui/src/region-state.tsx:29-48`; spec: R1.8.
- `apps/api/tests/contract/test_error_codes.py:41`; spec: G3.
- ADR-0108 (Accepted) điểm 1.

## Comments

- 2026-10-26 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-10-26 (agent): Xong. Mọi tiêu chí xanh, kể cả dòng Xong. Đột biến đã thấy đỏ: APS1 (gỡ handler `RequestValidationError` → walker và test R1.3 đỏ); APS2 (gỡ handler `Exception` → đỏ vì content-type; handler trả `str(exc)` → đỏ vì lộ câu SQL); G1 (bỏ `WWW-Authenticate`); G3 (mã chỉ có ở Python); R1.2 (`details` chuỗi hóa lại); R1.8 (client bỏ qua problem+json). Walker thay dependency xác thực bằng ngữ cảnh giả, vì xác thực chạy trước khi kiểm body: không thay thì chỉ `/dev/session` tới được 422. Với ngữ cảnh giả, cả 25 operation có body đều trả 422 problem+json.
- 2026-10-26 (agent): Câu hỏi cho Đạt, Q-01a. 429 của `RateLimitMiddleware` (`apps/api/src/dw_api/middleware/rate_limit.py:61-70`) tự dựng body cũ, `application/json`, không qua handler nào. R1.1 nói "khi một route trả lỗi", còn hàng 429 ở Ngoài phạm vi hoãn quy ước 429 sang W2, nên ticket để nguyên như đã viết, và client vẫn đọc được body đó. Đề xuất đổi R1.1: 429 của middleware dựng qua `problem_response`, chỉ thêm trường.
- 2026-10-26 (agent): Câu hỏi cho Đạt, Q-01b. `X-Request-ID` do client gửi, tới 128 ký tự bất kỳ (`apps/api/src/dw_api/middleware/request_id.py:17`), đi nguyên vào `instance` = `urn:dw:request:` nối giá trị đó, nên `instance` có thể không là URI hợp lệ (ví dụ có dấu cách). Ticket giữ nguồn như Hiện trạng ràng buộc. Đề xuất: middleware chỉ nhận `[A-Za-z0-9._-]{1,128}`, không khớp thì sinh mới.
- 2026-10-26 (agent, tạm): `HTTPException` có mã khác 404/405 mang mã đầu tiên của status đó trong `_STATUS_BY_CODE` (`code_for`), không có thì `internal` và giữ status; hôm nay không route nào ném nó. Lỗi schema ở `cookie` thành `parameter`. Nếu sai thì: một nhánh trong `code_for` hay `_located`, không đổi hình lỗi.
- 2026-10-26 (agent): Ghi chú khi dựng. `_STATUS_BY_CODE` nằm ở `apps/api/src/dw_api/errors.py`, không ở `dw_kernel` như bước 3 viết, nên ánh xạ 405 thêm ở đó. Client có năm bản sao của đoạn đọc lỗi, một bản đã lệch (`code: "http_error"`), nên gom về một `apiErrorFrom`. Phản hồi lỗi nay mang `X-Request-ID` cả với 500, vốn được trả ngoài middleware. `trace_id` sẽ là `null` cho tới khi API có span của server: hôm nay API chưa có instrumentation OpenTelemetry cho FastAPI (phụ thuộc telemetry-and-audit).
- 2026-10-26 (agent): Q-01a và Q-01b Đạt trả lời theo đề xuất, nên spec thêm R1.1 (429), R1.9 và APS11 và về `Duyệt: chưa`. Bước 9 làm trên cùng nhánh theo lời Đạt ("làm cho tôi"), trước lần duyệt lại. 429 của bộ giới hạn tốc độ dựng qua `problem_response`; test đỏ trước khi sửa. `X-Request-ID` ngoài `[A-Za-z0-9._-]{1,128}` được thay bằng uuid mới. Đột biến APS11 (trả về phép kiểm cũ chỉ theo độ dài) làm test đỏ ở dấu cách, markup và ký tự tiếng Việt.
