# 02 — Idempotency-Key gắn người gọi, token rào, phát lại header, kiểm lại quyền

Status: needs-triage
Blocked by: 01
Area: studio
Yêu cầu: R1.10, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.10, R2.11, R2.12, R2.14, R2.16, R2.17, R2.18, R2.19, G4, G5, G6, APS3, APS4, APS5, APS6, APS12, APS13, APS15, APS17, APS19, APS20, APS21

## Mục tiêu

Lát này cho người gọi thử lại một yêu cầu ghi mà không sợ ghi hai lần, và chỉ chính họ, khi còn quyền, nhận lại câu trả lời đã lưu (R2, YC5): khóa gắn người gọi đã xác minh, lượt giành lại có token rào và chỉ cho chính chủ, lần phát lại kèm `ETag` và `Location` và kiểm lại quyền của route, khóa của tenant khác không chạm dòng của tenant này (ADR-0108 (Accepted) điểm 4). Đây là ticket duy nhất sửa lỗi phát lại cho người khác, kể cả khi runtime-hardening cũng ghi lỗi đó. Ticket này chờ ticket 01, vì 422 `idempotency_key_required` của R2.6 và lần phát lại đi qua vỏ problem+json của ticket đó, và hai ticket cùng sửa `apps/api/src/dw_api/exception_handlers.py`. Việc xóa khóa quá hạn là ticket 04.

## Việc cần làm

1. Migration mới, id hex ngẫu nhiên của `alembic revision -m "idempotency keys bound to the caller"`: thêm vào `platform.idempotency_keys` cột `caller_ref text NOT NULL DEFAULT ''`, `reservation_token uuid NOT NULL DEFAULT gen_random_uuid()`, `response_headers jsonb` với `CONSTRAINT ck_idempotency_keys_response_headers_object CHECK (response_headers IS NULL OR jsonb_typeof(response_headers) = 'object')` và `request_preconditions text NOT NULL DEFAULT ''`. Không policy nào cho `dw_app` đọc dòng của tenant khác (R2.12). Dòng cũ giữ `caller_ref = ''`.
2. `packages/python/dw_platform/src/dw_platform/application/idempotency.py`: `RequestFingerprint` thêm `caller_ref` và `preconditions` (giá trị `If-Match` và `If-None-Match` đã gửi, R2.1), `caller_ref` dựng từ `AccessContext` là `user:` nối `principal_id`, hay `support:` nối `grant_id` khi ngữ cảnh có grant `support`; phép so dấu vân tay gồm `caller_ref`, và `''` không bằng người gọi thật nào; `StoredResponse` thêm `headers` chỉ gồm `ETag` và `Location`; `reserve` và `take_over` trả token; `take_over` nhận dấu vân tay và chỉ giành dòng cùng `caller_ref` (R2.10), lượt giành lại cấp token mới, đặt `created_at` về lúc giành và giữ `caller_ref` (R2.4); `complete` và `release` nhận token.
3. `packages/python/dw_platform/src/dw_platform/adapters/persistence/idempotency_store.py`: ghi `caller_ref`, `reservation_token` và `request_preconditions`; `take_over` thêm điều kiện `caller_ref` bằng người gọi; `complete` và `release` thêm điều kiện `reservation_token` bằng token của chính yêu cầu; lưu `response_headers`.
4. `apps/api/src/dw_api/dependencies/idempotency.py`:
    - chụp `ETag` và `Location` của phản hồi đầu vào câu trả lời lưu; dấu vân tay đọc `If-Match` và `If-None-Match`;
    - route khai `action` của nó một lần, qua một hàm dựng dependency khóa nhận `action` (thay alias `RequireIdempotency` không đối số); dependency đó gọi `container.authorization.require(context=..., action=...)` trước khi giữ chỗ hay đọc dòng, cho lần gọi mới cũng như lần phát lại, nên người đã bị thu quyền nhận 403 `permission_denied` mà không nhận body đã lưu (R2.17); mỗi route đang nhận khóa (`apps/api/src/dw_api/routes/v1/admin_members.py`, `apps/api/src/dw_api/routes/v1/approvals.py`, `apps/api/src/dw_api/routes/v1/support.py`) khai đúng `action` mà handler của nó đã đòi;
    - test dựng ứng dụng duyệt mọi operation của `app.openapi()` (thấy router lồng, như walker của APS1) có tham số header `Idempotency-Key` và đỏ, nêu route, khi route đó không khai `action` (R2.18);
    - dependency khóa bắt buộc: thiếu header thì `DomainError` (`validation_failed`, 422) với `details.reason_code` `idempotency_key_required` và `errors[]` `{header: "Idempotency-Key", code: "idempotency_key_required"}` trước khi handler chạy (R2.6);
    - dependency khóa giữ thứ tự sau `RequireAccessContext` (R2.14).

    Handler phát lại trong `apps/api/src/dw_api/exception_handlers.py` gửi kèm `ETag` và `Location` đã lưu. Cùng tệp: mọi lỗi 4xx chỉ mang tên trường, vị trí và mã, không giá trị đã gửi, giá trị của dòng đã có, tên bảng hay tên ràng buộc; một vi phạm ràng buộc mà adapter dịch thành 409 hay 422 mang mã của nó, không mang `str(exc)` (R1.10).

5. Ba route hiện nhận khóa (bước 4): với mỗi route, một test tích hợp giữ chỗ quá 5 phút sau khi hiệu ứng đã commit mà chưa `complete`, rồi gửi lại cùng khóa, và khẳng định hiệu ứng không có lần hai (R2.16); route nào không qua được thì hiệu ứng của nó ghi một khóa trong cùng giao dịch ghi, hay route đó thôi nhận `Idempotency-Key`; khi khóa của hiệu ứng thấy hiệu ứng đã có, route trả status và tài nguyên của hiệu ứng đó như lần đầu. Một test hai lượt giành lại song song của cùng người gọi: một thắng, một 409 `conflict` (R2.19).
6. `README.md`, mục "Idempotent requests": khóa gắn người gọi, người khác nhận 409, lần phát lại kèm `ETag` và `Location` và kiểm lại quyền của route, mọi route nhận khóa tự chống lặp hiệu ứng trong giao dịch ghi (R2.16); bảng route liệt kê đủ route đang nhận khóa.

## Tiêu chí chấp nhận

- [ ] R2.1 (APS3): cùng người gọi gửi lại cùng khóa và body sau một 201 nhận lại 201, body, `ETag` và `Location` đã lưu, và handler giả không chạy lần hai; cùng khóa và body với `If-Match` khác nhận 409 `idempotency_conflict`; bỏ `request_preconditions` khỏi phép so thì test đỏ.
- [ ] R2.2 (APS3): người B cùng tenant và workspace gửi khóa và body của người A nhận 409 `idempotency_conflict`, body của A không có trong phản hồi, handler không chạy; cùng người dưới một grant `support` khác cũng nhận 409; bỏ `caller_ref` khỏi phép so thì test đỏ.
- [ ] R2.3 (APS4): dòng có `caller_ref = ''` cùng body nhận 409 cho mọi người gọi; coi `''` là khớp mọi người thì test đỏ.
- [ ] R2.4: sau lượt giành lại của chính chủ, `reservation_token` của dòng khác token cũ, `created_at` là lúc giành và `caller_ref` không đổi.
- [ ] R2.5 (APS5): sau lượt giành lại, `complete` của yêu cầu cũ với token cũ không đổi `response_status` hay `response_body`, và `release` với token cũ không xóa dòng; bỏ điều kiện token khỏi `complete` hay khỏi `release` thì test tích hợp đỏ.
- [ ] R2.6 (APS6): route thử bắt buộc khóa, gọi thiếu header, trả 422 `validation_failed` với `details.reason_code` và `errors[0]` `{header: "Idempotency-Key", code: "idempotency_key_required"}` mà handler không chạy; gỡ dependency thì test đỏ.
- [ ] R2.10 (APS13): giữ chỗ của A quá 5 phút, B gửi cùng khóa nhận 409 `idempotency_conflict`; gọi thẳng `take_over` của kho với người gọi B không giành được, `caller_ref`, `reservation_token` và `created_at` không đổi; bỏ điều kiện người gọi khỏi `take_over` thì test tích hợp đỏ.
- [ ] R2.11 (APS12): tenant B gửi khóa và body tenant A đã dùng, handler chạy cho B, body của A không có trong phản hồi và dòng của A không đổi.
- [ ] R2.12 (APS12): kết nối `dw_app` với `app.tenant_id` của B, cả khi tự đặt `app.worker_drain = on`, đọc 0 dòng của A trong `platform.idempotency_keys`; thêm một policy cho đọc theo `app.worker_drain` thì test tích hợp đỏ.
- [ ] R2.14 (APS15): grant `support` bị thu hồi rồi gửi lại khóa đã dùng dưới grant đó nhận lỗi của bước dựng ngữ cảnh, không có body đã lưu, và không câu lệnh nào đọc `platform.idempotency_keys`; đặt dependency khóa trước `RequireAccessContext` thì test đỏ.
- [ ] R2.17 (APS17): người A dùng khóa thành công trên route thử, bị thu scope mà route đòi, gửi lại khóa đó nhận 403 `permission_denied` và không có body đã lưu trong phản hồi; bỏ phép kiểm quyền khỏi dependency thì test đỏ.
- [ ] R2.18 (APS19): một route thử nhận `Idempotency-Key` mà không khai `action` làm test dựng ứng dụng đỏ và nêu route đó; gỡ phép kiểm khai báo thì test đỏ.
- [ ] R2.16 (APS20): ở cả ba route hiện nhận khóa, gửi lại sau khi hiệu ứng đã commit mà chưa `complete` không tạo hiệu ứng lần hai và trả status cùng tài nguyên như lần đầu; gỡ khóa của hiệu ứng khỏi giao dịch ghi thì test đỏ.
- [ ] R2.19 (APS20): hai lượt giành lại song song thật của cùng người gọi trên một giữ chỗ quá 5 phút cho một lượt thắng và một 409 `conflict`, handler chạy một lần.
- [ ] R1.10 (APS21): route thử nhận body có trường sai kiểu mang `SECRET-123`, và một route thử vi phạm ràng buộc duy nhất: 422 và 409 không chứa `SECRET-123`, giá trị của dòng đã có, tên bảng hay tên ràng buộc; cho handler đưa `input` hay `str(exc)` vào `errors[]` hay `details` thì test đỏ.
- [ ] G4: `test_the_same_key_with_a_different_body_is_a_conflict` xanh trước và sau thay đổi.
- [ ] G5: `test_a_request_still_in_flight_is_refused_rather_than_run_again` xanh trước và sau thay đổi.
- [ ] G6: `test_a_failed_request_releases_its_key_so_the_retry_can_work` xanh trước và sau thay đổi.
- [ ] Xong: `make test-unit test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/application/idempotency.py:44-78`; spec: R2.1, R2.2, R2.4.
- `packages/python/dw_platform/src/dw_platform/application/idempotency.py:147-167`; spec: R2.2, R2.10.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/idempotency_store.py:103-164`; spec: R2.4, R2.5, R2.19.
- `apps/api/src/dw_api/dependencies/idempotency.py:70-90`, `apps/api/src/dw_api/dependencies/idempotency.py:217-248`; spec: R2.6, R2.14, R2.17.
- `packages/python/dw_platform/src/dw_platform/application/authorization.py:56-66`; spec: R2.17.
- `apps/api/src/dw_api/exception_handlers.py:14-26`; spec: R2.1.
- `db/migrations/sql/0002_http_idempotency.sql:22-79`; spec: R2.3, R2.11, R2.12.
- `README.md:124-158`; spec: R2.1.
- ADR-0108 (Accepted) điểm 4.

## Comments

- 2026-10-26 (agent): theo spec sửa ngày 26/10/2026 (R2.10 tới R2.14, APS12 tới APS15); phần dọn chờ Q2, và Q3 không đổi việc của ticket này.
- 2026-10-27 (agent): theo câu trả lời của Đạt cho Q2, Q3 và phát lại sau khi thu quyền: phần dọn (R2.8, R2.9, R2.13, R2.15, APS14) sang ticket 04; ticket này thêm R2.17 và APS17.
- 2026-10-27 (agent): theo lần sửa sau gate thứ ba (Đạt: "cứ tiếp tục theo khuyến nghị"): `action` khai một lần, R2.16 cho ba route hiện có, R2.18, R2.19, APS19, APS20.
- 2026-10-27 (agent): theo lần sửa sau gate thứ tư: R1.10 và APS21 ở ticket này vì nó sửa `exception_handlers.py`; test của R2.18 duyệt `app.openapi()`; APS3 và APS5 thử thêm điều kiện khác và `release`; R2.16 trả kết quả của hiệu ứng đã có.
