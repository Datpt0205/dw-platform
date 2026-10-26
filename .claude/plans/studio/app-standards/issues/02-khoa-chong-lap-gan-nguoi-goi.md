# 02 — Idempotency-Key gắn người gọi, token rào, phát lại header, dọn sau 24 giờ

Status: needs-info
Blocked by: 01
Area: studio
Yêu cầu: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.8, R2.9, R2.10, R2.11, R2.12, R2.13, R2.14, G4, G5, G6, APS3, APS4, APS5, APS6, APS12, APS13, APS14, APS15

## Mục tiêu

Lát này cho người gọi thử lại một yêu cầu ghi mà không sợ ghi hai lần, và chỉ chính họ nhận lại câu trả lời đã lưu (R2, YC5): khóa gắn người gọi đã xác minh, lượt giành lại có token rào, lần phát lại kèm `ETag` và `Location`, và khóa bị xóa sau 24 giờ (ADR-0108 (Accepted) điểm 4). Đây là ticket duy nhất sửa lỗi phát lại cho người khác, kể cả khi runtime-hardening cũng ghi lỗi đó. Ticket này chờ ticket 01, vì 422 `idempotency_key_required` của R2.6 và lần phát lại đi qua vỏ problem+json của ticket đó, và hai ticket cùng sửa `apps/api/src/dw_api/exception_handlers.py`. Phần dọn (bước 1 về cơ chế dọn, bước 5, R2.8, R2.9, R2.13, APS14) chờ Q2 của spec, và có thể tách thành ticket riêng.

## Việc cần làm

1. Migration mới, id hex ngẫu nhiên của `alembic revision -m "idempotency keys bound to the caller"`: thêm vào `platform.idempotency_keys` cột `caller_ref text NOT NULL DEFAULT ''`, `reservation_token uuid NOT NULL DEFAULT gen_random_uuid()` `response_headers jsonb` với `CONSTRAINT ck_idempotency_keys_response_headers_object CHECK (response_headers IS NULL OR jsonb_typeof(response_headers) = 'object')` và `request_preconditions text NOT NULL DEFAULT ''`; cơ chế dọn xuyên tenant theo Q2 của spec, không policy nào cho `dw_app` đọc dòng của tenant khác (R2.12). Dòng cũ giữ `caller_ref = ''`.
2. `packages/python/dw_platform/src/dw_platform/application/idempotency.py`: `RequestFingerprint` thêm `caller_ref` và `preconditions` (giá trị `If-Match` và `If-None-Match` đã gửi, R2.1), dựng từ `AccessContext` là `user:` nối `principal_id`, hay `support:` nối `grant_id` khi ngữ cảnh có grant `support`; phép so dấu vân tay gồm `caller_ref`, và `''` không bằng người gọi thật nào; `StoredResponse` thêm `headers` chỉ gồm `ETag` và `Location`; `reserve` và `take_over` trả token; `take_over` nhận dấu vân tay và chỉ giành dòng cùng `caller_ref` (R2.10), lượt giành lại cấp token mới và giữ `caller_ref`; `complete` và `release` nhận token; hằng `IDEMPOTENCY_KEY_TTL = timedelta(hours=24)` cạnh `STALE_RESERVATION`.
3. `packages/python/dw_platform/src/dw_platform/adapters/persistence/idempotency_store.py`: ghi `caller_ref`, `reservation_token` và `request_preconditions`; `take_over` thêm điều kiện `caller_ref` bằng người gọi; `complete` và `release` thêm điều kiện `reservation_token` bằng token của chính yêu cầu; lưu `response_headers`.
4. `apps/api/src/dw_api/dependencies/idempotency.py`: chụp `ETag` và `Location` của phản hồi đầu vào câu trả lời lưu; thêm dependency khóa bắt buộc, thiếu header thì `DomainError` (`validation_failed`, 422) với `details.reason_code` `idempotency_key_required` và `errors[]` `{header: "Idempotency-Key", code: "idempotency_key_required"}` trước khi handler chạy (R2.6); dấu vân tay đọc `If-Match` và `If-None-Match`; dependency khóa giữ thứ tự sau `RequireAccessContext` (R2.14). Handler phát lại trong `apps/api/src/dw_api/exception_handlers.py` gửi kèm `ETag` và `Location` đã lưu.
5. Lane `idempotency_sweep` trong `apps/worker/src/dw_worker/main.py`, đăng ký như các lane dọn khác với `RETENTION_INTERVAL_SECONDS`; gọi cơ chế dọn mà Q2 của spec chọn, cơ chế đó chỉ trả số dòng (R2.13); ghi số dòng vào log, không ghi audit (ADR-0011 (Accepted), mục "Not applied"). Tập lane trong `test_only_the_platform_lanes_are_wired` thêm `idempotency_sweep`.
6. `README.md`, mục "Idempotent requests": khóa gắn người gọi, người khác nhận 409, lần phát lại kèm `ETag` và `Location`, khóa bị xóa sau 24 giờ; bảng route liệt kê đủ route đang nhận khóa.

## Tiêu chí chấp nhận

- [ ] R2.1: cùng người gọi gửi lại cùng khóa và body sau một 201 nhận lại 201, body, `ETag` và `Location` đã lưu, và handler giả không chạy lần hai; cùng khóa và body với `If-Match` khác nhận 409 `idempotency_conflict`.
- [ ] R2.2 (APS3): người B cùng tenant và workspace gửi khóa và body của người A nhận 409 `idempotency_conflict`, body của A không có trong phản hồi, handler không chạy; cùng người dưới một grant `support` khác cũng nhận 409; bỏ `caller_ref` khỏi phép so thì test đỏ.
- [ ] R2.3 (APS4): dòng có `caller_ref = ''` cùng body nhận 409 cho mọi người gọi; coi `''` là khớp mọi người thì test đỏ.
- [ ] R2.4: sau lượt giành lại, `reservation_token` của dòng khác token cũ.
- [ ] R2.5 (APS5): sau lượt giành lại, `complete` của yêu cầu cũ với token cũ không đổi `response_status` hay `response_body`, và `release` với token cũ không xóa dòng; bỏ điều kiện token thì test tích hợp đỏ.
- [ ] R2.6 (APS6): route thử bắt buộc khóa, gọi thiếu header, trả 422 `validation_failed` với `details.reason_code` và `errors[0]` `{header: "Idempotency-Key", code: "idempotency_key_required"}` mà handler không chạy; gỡ dependency thì test đỏ.
- [ ] R2.8 (APS14): dòng có `created_at` 25 giờ trước bị xóa, dòng 1 giờ trước còn, ở hai tenant khác nhau trong cùng một lượt; nới điều kiện tuổi thì test đỏ.
- [ ] R2.10 (APS13): giữ chỗ của A quá 5 phút, B gửi cùng khóa nhận 409 `idempotency_conflict`; gọi thẳng `take_over` của kho với người gọi B không giành được, `caller_ref`, `reservation_token` và `created_at` không đổi; bỏ điều kiện người gọi khỏi `take_over` thì test tích hợp đỏ.
- [ ] R2.11 (APS12): tenant B gửi khóa và body tenant A đã dùng, handler chạy cho B, body của A không có trong phản hồi và dòng của A không đổi.
- [ ] R2.12 (APS12): kết nối `dw_app` với `app.tenant_id` của B, cả khi tự đặt `app.worker_drain = on`, đọc 0 dòng của A trong `platform.idempotency_keys`; thêm một policy cho đọc theo `app.worker_drain` thì test tích hợp đỏ.
- [ ] R2.13 (APS14): cơ chế dọn trả số dòng và không trả cột nào; cho nó trả dòng thì test đỏ.
- [ ] R2.14 (APS15): grant `support` bị thu hồi rồi gửi lại khóa đã dùng dưới grant đó nhận lỗi của bước dựng ngữ cảnh, không có body đã lưu, và không câu lệnh nào đọc `platform.idempotency_keys`; đặt dependency khóa trước `RequireAccessContext` thì test đỏ.
- [ ] R2.9: lượt dọn ghi số dòng đã xóa vào log và không thêm dòng nào vào `platform.audit_events`.
- [ ] G4: `test_the_same_key_with_a_different_body_is_a_conflict` xanh trước và sau thay đổi.
- [ ] G5: `test_a_request_still_in_flight_is_refused_rather_than_run_again` xanh trước và sau thay đổi.
- [ ] G6: `test_a_failed_request_releases_its_key_so_the_retry_can_work` xanh trước và sau thay đổi.
- [ ] Xong: `make test-unit test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/application/idempotency.py:44-78`; spec: R2.1, R2.2, R2.4.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/idempotency_store.py:103-164`; spec: R2.4, R2.5.
- `apps/api/src/dw_api/dependencies/idempotency.py:70-90`; spec: R2.6.
- `apps/api/src/dw_api/exception_handlers.py:14-26`; spec: R2.1.
- `db/migrations/sql/0002_http_idempotency.sql:22-79`; spec: R2.3, R2.8.
- `db/migrations/sql/0002_http_idempotency.sql:39`, `db/migrations/sql/0002_http_idempotency.sql:76-79`; spec: R2.11, R2.12.
- `packages/python/dw_platform/src/dw_platform/application/idempotency.py:147-167`; spec: R2.2, R2.10.
- `db/migrations/versions/855ae928c3fa_platform_in_app_notifications.py:27-29`; spec: R2.8, Q2.
- `apps/worker/src/dw_worker/main.py:472-531`, `apps/worker/tests/unit/test_worker.py:103-158`; spec: R2.8.
- `docs/adr/0011-a-background-lane-audits-as-itself.md:38-43`; spec: R2.9.
- `README.md:124-158`; spec: R2.1.
- ADR-0108 (Accepted) điểm 4.

## Comments

- 2026-10-26 (agent): theo spec sửa ngày 26/10/2026 (R2.10 tới R2.14, APS12 tới APS15); phần dọn chờ Q2, và Q3 không đổi việc của ticket này.
