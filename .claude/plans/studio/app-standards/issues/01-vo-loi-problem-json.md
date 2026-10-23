# 01 — Một vỏ lỗi problem+json cho mọi route

Status: needs-info (DO-16)
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R1.6, R1.7, R1.8, G1, G2, G3, APS1, APS2

## Mục tiêu

Lát này cho client, người tích hợp và trang web một hình lỗi duy nhất: mọi route, kể cả lỗi schema, đường lạ và sai method, trả mô tả lỗi problem+json giữ nguyên bốn trường đang được đọc (R1, G1 đến G3, ADR-0108 (Proposed) điểm 1). Biểu mẫu đọc được lỗi của từng trường thay vì "HTTP 422".

## Việc cần làm

1. Trước mọi thay đổi, viết `test_an_error_keeps_code_message_details_and_request_id` trong `apps/api/tests/contract/` trên vỏ hiện tại; test xanh ở commit gốc.
2. `apps/api/src/dw_api/errors.py`: model `Problem` (`type`, `title`, `status`, `detail`, `instance`, `code`, `message`, `details`, `request_id`, `trace_id`, `errors`) và model `ProblemError` (`pointer`, `parameter`, `header`, `code`, `detail`, với đúng một trong ba trường đầu); một hàm dựng duy nhất mà mọi handler gọi; bảng `title` tiếng Anh theo `ErrorCode`.
3. `packages/python/dw_kernel/src/dw_kernel/errors.py`: thêm `METHOD_NOT_ALLOWED = "method_not_allowed"` vào `ErrorCode`, ánh xạ 405 trong `_STATUS_BY_CODE`. Mã 412 và 428 vào cùng người đọc của chúng ở ticket 03.
4. `apps/api/src/dw_api/exception_handlers.py`: handler cho `DWError` (giữ `WWW-Authenticate` của 401), `RequestValidationError` (mỗi `loc` bắt đầu bằng `body` thành `pointer`, `query` hay `path` thành `parameter`, `header` thành `header`), `HTTPException` của Starlette (404 thành `not_found`, 405 thành `method_not_allowed`, giữ header của exception như `Allow`) và `Exception` (500, `internal`, không chuỗi nào của exception); `details` giữ kiểu JSON thay vì `str(v)`; mọi phản hồi lỗi mang `Content-Type: application/problem+json`. Handler phát lại của `ReplayedResponse` không đổi ở ticket này.
5. `trace_id` là id trace của span OpenTelemetry hiện hành, 32 ký tự hex, `null` khi không có span; `instance` là `urn:dw:request:` nối `request_id` của middleware.
6. OpenAPI: phản hồi mặc định 4XX và 5XX trỏ schema `Problem` trên mọi operation; bỏ `HTTPValidationError` và `ValidationError` khỏi `components`; `make generate-contracts` cập nhật `contracts/openapi/openapi.json` và client TypeScript sinh ra.
7. TypeScript: `packages/typescript/contracts/src/error.ts` thêm `problemSchema` không strict (trường mở rộng tùy chọn) và mã `MethodNotAllowed`; `packages/typescript/api-client/src/client.ts` parse mô tả lỗi khi `Content-Type` là `application/problem+json` và giữ `errors[]`; `packages/typescript/ui/src/region-state.tsx` thêm `method_not_allowed`; `apps/web/lib/error-message.ts` thêm `fieldErrors()` trả map từ `pointer` sang `errors[].code`.
8. Test: walker đọc `app.openapi()` (thấy router lồng, không duyệt `app.routes`) gọi mỗi operation có body với một body sai kiểu; một đường lạ; một method sai; route thử ném `IntegrityError` mang giá trị dòng; test client TypeScript với phản hồi 422 có `errors[]`.

## Tiêu chí chấp nhận

- [ ] R1.1 (APS1): mọi phản hồi lỗi của walker có `Content-Type: application/problem+json`; 422 có `type` `urn:dw:problem:validation_failed` và `instance` bằng `urn:dw:request:` nối `X-Request-ID` đã gửi; gỡ handler `RequestValidationError` thì walker đỏ.
- [ ] R1.2: một `DWError` với `details={"limit": 3}` trả `details.limit` là số 3, không phải chuỗi; khi có span, `trace_id` có 32 ký tự hex; không có span thì `trace_id` là `null`.
- [ ] R1.3 (APS1): body sai kiểu trả 422 với `errors[0].pointer` trỏ đúng trường; tham số query sai trả `errors[0].parameter`.
- [ ] R1.4 (APS1): `GET /api/v1/khong-co` trả 404 problem+json với `code` `not_found`.
- [ ] R1.5 (APS1): `DELETE` trên một đường chỉ có `GET` trả 405 `method_not_allowed` kèm header `Allow`.
- [ ] R1.6 (APS2): route thử ném `IntegrityError` mang giá trị dòng trả 500 mà body không chứa câu SQL, tên bảng hay giá trị đó; gỡ handler `Exception` thì test đỏ.
- [ ] R1.7: ảnh chụp OpenAPI không còn `HTTPValidationError`, và mọi operation có 4XX và 5XX trỏ `Problem`.
- [ ] R1.8: client TypeScript nhận 422 có `errors[]` trả lỗi `validation_failed` giữ `errors[]`; client đọc `code` và `message` như cũ vẫn đúng.
- [ ] G1: `test_me_without_a_verifiable_token_is_401_with_a_challenge` xanh trước và sau thay đổi.
- [ ] G2: `test_an_error_keeps_code_message_details_and_request_id` xanh ở commit gốc và sau thay đổi.
- [ ] G3: `test_the_typescript_error_codes_mirror_the_python_ones` xanh khi `method_not_allowed` có ở cả hai bên, đỏ khi chỉ có ở Python.
- [ ] Xong: `make test-unit test-contract typecheck && pnpm -r --if-present test` xanh.

## Nguồn

- `apps/api/src/dw_api/errors.py:9-38`; spec: R1.1, R1.2.
- `apps/api/src/dw_api/exception_handlers.py:13-49`; spec: R1.3, R1.4, R1.5, R1.6, G1.
- `apps/api/src/dw_api/middleware/request_id.py:16-18`; spec: R1.1.
- `packages/python/dw_kernel/src/dw_kernel/errors.py:13-30`; spec: R1.5.
- `packages/typescript/api-client/src/client.ts:270-282`, `packages/typescript/contracts/src/error.ts:7-12`, `packages/typescript/ui/src/region-state.tsx:29-48`; spec: R1.8.
- `apps/api/tests/contract/test_error_codes.py:41`; spec: G3.
- ADR-0108 (Proposed) điểm 1.

## Comments
