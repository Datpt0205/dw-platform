# 02 — Idempotency-Key gắn người gọi, token rào, phát lại header, dọn sau 24 giờ

Status: needs-triage
Blocked by: 01
Area: studio
Yêu cầu: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.8, R2.9, G4, G5, G6, APS3, APS4, APS5, APS6

## Mục tiêu

Lát này cho người gọi thử lại một yêu cầu ghi mà không sợ ghi hai lần, và chỉ chính họ nhận lại câu trả lời đã lưu (R2, YC5): khóa gắn người gọi đã xác minh, lượt giành lại có token rào, lần phát lại kèm `ETag` và `Location`, và khóa bị xóa sau 24 giờ (ADR-0108 (Accepted) điểm 4). Đây là ticket duy nhất sửa lỗi phát lại cho người khác, kể cả khi runtime-hardening cũng ghi lỗi đó. Ticket này chờ ticket 01, vì 422 `idempotency_key_required` của R2.6 và lần phát lại đi qua vỏ problem+json của ticket đó, và hai ticket cùng sửa `apps/api/src/dw_api/exception_handlers.py`.

## Việc cần làm

1. Migration mới, id hex ngẫu nhiên của `alembic revision -m "idempotency keys bound to the caller"`: thêm vào `platform.idempotency_keys` cột `caller_ref text NOT NULL DEFAULT ''`, `reservation_token uuid NOT NULL DEFAULT gen_random_uuid()` và `response_headers jsonb` với `CONSTRAINT ck_idempotency_keys_response_headers_object CHECK (response_headers IS NULL OR jsonb_typeof(response_headers) = 'object')`; policy `worker_drain_idempotency_keys` với `current_setting('app.worker_drain', true) = 'on'`, theo mẫu migration `7bbd071748ca`. Dòng cũ giữ `caller_ref = ''`.
2. `packages/python/dw_platform/src/dw_platform/application/idempotency.py`: `RequestFingerprint` thêm `caller_ref`, dựng từ `AccessContext` là `user:` nối `principal_id`, hay `support:` nối `grant_id` khi ngữ cảnh có grant `support`; phép so dấu vân tay gồm `caller_ref`, và `''` không bằng người gọi thật nào; `StoredResponse` thêm `headers` chỉ gồm `ETag` và `Location`; `reserve` và `take_over` trả token, lượt giành lại cấp token mới; `complete` và `release` nhận token; hằng `IDEMPOTENCY_KEY_TTL = timedelta(hours=24)` cạnh `STALE_RESERVATION`.
3. `packages/python/dw_platform/src/dw_platform/adapters/persistence/idempotency_store.py`: ghi `caller_ref` và `reservation_token`; `complete` và `release` thêm điều kiện `reservation_token` bằng token của chính yêu cầu; lưu `response_headers`.
4. `apps/api/src/dw_api/dependencies/idempotency.py`: chụp `ETag` và `Location` của phản hồi đầu vào câu trả lời lưu; thêm dependency khóa bắt buộc, thiếu header thì `DomainError` với `details.reason_code` `idempotency_key_required` (422) trước khi handler chạy. Handler phát lại trong `apps/api/src/dw_api/exception_handlers.py` gửi kèm `ETag` và `Location` đã lưu.
5. Lane `idempotency_sweep` trong `apps/worker/src/dw_worker/main.py`, đăng ký như các lane dọn khác với `RETENTION_INTERVAL_SECONDS`; adapter đặt `app.worker_drain` theo giao dịch và xóa theo lô các dòng có `created_at` cũ hơn `IDEMPOTENCY_KEY_TTL`; ghi số dòng vào log, không ghi audit (ADR-0011 (Accepted), mục "Not applied"). Tập lane trong `test_only_the_platform_lanes_are_wired` thêm `idempotency_sweep`.
6. `README.md`, mục "Idempotent requests": khóa gắn người gọi, người khác nhận 409, lần phát lại kèm `ETag` và `Location`, khóa bị xóa sau 24 giờ; bảng route liệt kê đủ route đang nhận khóa.

## Tiêu chí chấp nhận

- [ ] R2.1: cùng người gọi gửi lại cùng khóa và body sau một 201 nhận lại 201, body, `ETag` và `Location` đã lưu, và handler giả không chạy lần hai.
- [ ] R2.2 (APS3): người B cùng tenant và workspace gửi khóa và body của người A nhận 409 `idempotency_conflict`, body của A không có trong phản hồi, handler không chạy; cùng người dưới một grant `support` khác cũng nhận 409; bỏ `caller_ref` khỏi phép so thì test đỏ.
- [ ] R2.3 (APS4): dòng có `caller_ref = ''` cùng body nhận 409 cho mọi người gọi; coi `''` là khớp mọi người thì test đỏ.
- [ ] R2.4: sau lượt giành lại, `reservation_token` của dòng khác token cũ.
- [ ] R2.5 (APS5): sau lượt giành lại, `complete` của yêu cầu cũ với token cũ không đổi `response_status` hay `response_body`, và `release` với token cũ không xóa dòng; bỏ điều kiện token thì test tích hợp đỏ.
- [ ] R2.6 (APS6): route thử bắt buộc khóa, gọi thiếu header, trả 422 `idempotency_key_required` mà handler không chạy; gỡ dependency thì test đỏ.
- [ ] R2.8: dòng có `created_at` 25 giờ trước bị xóa, dòng 1 giờ trước còn, ở hai tenant khác nhau trong cùng một lượt.
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
- `db/migrations/versions/7bbd071748ca_run_checkpoints_worker_drain_and_sweep_.py:46-58`; spec: R2.8.
- `apps/worker/src/dw_worker/main.py:472-531`, `apps/worker/tests/unit/test_worker.py:103-158`; spec: R2.8.
- `docs/adr/0011-a-background-lane-audits-as-itself.md:38-43`; spec: R2.9.
- `README.md:124-158`; spec: R2.1.
- ADR-0108 (Accepted) điểm 4.

## Comments
