# 03 — ETag và If-Match, phân trang keyset có kiểu, cây lọc JSON và kiểm hình kế hoạch trong CI

Status: needs-triage
Blocked by: 01, 02
Area: studio
Yêu cầu: R2.1, R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R3.8, R3.9, R3.10, R3.11, R3.12, R3.13, R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.7, R5.8, R5.9, R6.1, R6.2, G7, G8, APS7, APS8, APS9, APS10, APS16, APS18, APS22

## Mục tiêu

Lát này cho mọi route danh sách và route sửa một quy ước chung: ETag mạnh với `If-Match`, 412 và 428, JSON Merge Patch (R3); con trỏ keyset phiên bản 2 có kiểu, hai chiều, NULL cuối (R4); cây lọc JSON có giới hạn cùng `order_by` và `fields` (R5); và một kiểm hình kế hoạch trong CI làm đỏ mọi truy vấn phân trang không có index mang trọn (R6, ADR-0108 (Accepted) điểm 2 và 3). API bản ghi của custom-objects là người dùng đầu tiên; ở đây các quy ước được chứng minh trên route thử và trên năm route phân trang hiện có.

## Việc cần làm

1. `ErrorCode` thêm `PRECONDITION_FAILED = "precondition_failed"` (412) và `PRECONDITION_REQUIRED = "precondition_required"` (428), cùng bản TypeScript; `ERROR_STATE` ánh xạ `precondition_failed` sang vùng `conflict` và `precondition_required` sang vùng `error`.
2. Module thuần mới `dw_kernel.http_conditions`: định dạng ETag mạnh từ phiên bản; phân tích `If-Match` và `If-None-Match` (so mạnh, `*`, danh sách; ETag yếu không bao giờ khớp). Dependency API `RequireIfMatch` trả 428 khi thiếu hay khi là `*` (R3.8), và so phiên bản chỉ sau khi tài nguyên được nạp dưới quyền của người gọi, nên người không đọc được nhận phản hồi của id không tồn tại (R3.7); nó đứng sau dependency khóa chống lặp, nên lần phát lại của R2.1 không so lại điều kiện. Phép so nằm trong chính câu ghi (`UPDATE … WHERE id = :id AND version = :v`), không ghi được dòng nào thì 412 (R3.9). Hàm thuần `apply_merge_patch` theo RFC 7396, nhận `application/merge-patch+json` và `application/json`; `Content-Type` khác trả 415 `unsupported_media_type` (R3.10). R3 bật theo tài nguyên: một tài nguyên bật R3 thì route đọc nó gửi `ETag` và mọi route ghi nó bật `RequireIfMatch`; câu ghi không khớp dòng nào thì đọc lại dưới quyền của người gọi, không thấy thì trả phản hồi của id không tồn tại, thấy thì 412 (R3.13). Test dựng ứng dụng duyệt `app.openapi()` và đỏ, nêu route, khi một operation ghi (`PATCH`, `PUT`, `DELETE`, `POST` sub-resource) trả một schema có `version` mà không bật `RequireIfMatch` và không có tên trong danh sách miễn trừ kèm lý do; route hiện có như thế vào danh sách đó (R3.12).
3. CORS trong `apps/api/src/dw_api/main.py`: `_CORS_HEADERS` thêm `If-Match`, `If-None-Match`; `expose_headers` thêm `ETag`, `Location`.
4. Trước khi đổi định dạng con trỏ, viết `test_a_v1_cursor_still_resumes_where_it_left_off` với một con trỏ phiên bản 1 dựng tay; test xanh ở commit gốc. Rồi trong `packages/python/dw_kernel/src/dw_kernel/pagination.py`: con trỏ phiên bản 2 với `sort_value` có thẻ kiểu (`text`, `int`, `float`, `date`, `datetime`, `bool`, `null`) và pha `values` hay `nulls`; giải được con trỏ phiên bản 1; vẫn từ chối phiên bản 0 và phiên bản lạ; dấu vân tay tính trên JSON chuẩn, khóa đã sắp, của cây lọc, `order_by`, `fields` và route.
5. `packages/python/dw_platform/src/dw_platform/adapters/persistence/keyset.py`: thêm chiều tăng; NULL cuối thành hai pha có index (pha `values` rồi pha `nulls`); `id` luôn là khóa cuối; giữ `after_position` và `newest_first` cho năm route hiện có.
6. Module mới `dw_kernel.filters`, chỉ dùng thư viện chuẩn: mô hình cây lọc (`$and`, `$or`, `$not`; lá `{field: {op: value}}`), toán tử theo kiểu trừu tượng, giới hạn độ sâu 5, 50 lá, `$in` 500 giá trị, chuỗi 1.024 byte UTF-8, lỗi mang JSON pointer vào cây, xuất JSON Schema; trình phân tích `order_by` (AIP-132) và `fields`. Route chỉ nhận cây đã qua phép kiểm này, từ tham số `filter` của `GET` (JSON mã hóa URL) hay thành viên `filter` của thân `POST <danh sách>/query`, cùng một trình phân tích, pointer bắt đầu bằng `/filter` (R5.7); `order_by` chỉ một trường, hơn một trường thì 422 với `errors[].parameter` `order_by` (R5.9); mã lý do theo bảng ở mục API của spec (R5.8); ngữ pháp lá (một trường, một toán tử; dạng khác là `filter_malformed`), cách đếm độ sâu (số nút trên đường dài nhất từ gốc tới lá, có ví dụ ở mục API của spec) và lá, bảng toán tử theo kiểu và `{"$eq": null}` theo mục API của spec; giá trị lá luôn là tham số bind. Mọi 422 của cây lọc, `order_by` và `fields` mang `code` `validation_failed`, mã lý do ở `errors[].code`: trường không có trong lược đồ của route là `field_not_readable` (giống trường bị ẩn, custom-objects:R8.4), trường không lọc được là `field_not_filterable` (R5.6).
7. `tests/support/plan_shape.py`: bắt câu lệnh thật bằng sự kiện `before_cursor_execute` khi gọi phương thức repository dưới `dw_app` với `app.tenant_id` đặt sẵn; chạy `EXPLAIN (FORMAT JSON)` dưới `SET LOCAL enable_seqscan = off`; khai cho mỗi câu lệnh `tenant_id` và các cột vị từ của chính câu lệnh, không khai vế `workspace_id OR app.workspace_scope` của RLS (R6.1); bắt cả trang đầu lẫn trang có con trỏ; khẳng định mỗi cột vị từ khai báo nằm trong `Index Cond` hay `Recheck Cond`, mỗi cột sắp nằm trong `Index Cond` hay được một index scan giao đúng thứ tự, và không có nút `Sort` hay `Incremental Sort` trên khóa keyset. Áp cho năm route phân trang và danh sách audit theo lượt chạy; sửa index mà test tìm ra trong một migration mới (dự kiến `platform.feedback (tenant_id, created_at DESC, id DESC)` thay `ix_feedback_tenant_created`). Index `platform.audit_events (tenant_id, run_id, workspace_id, occurred_at)` trên bảng cha là index audit theo lượt chạy duy nhất của nền tảng: ticket này là chủ, ADR-0122 (Accepted) bỏ `ix_audit_events_run`, và telemetry-and-audit/02 chờ ticket này (OPS-b).
8. Test: test thuộc tính cho R4.2 trên bảng thử có giá trị trùng và NULL, cả hai chiều; test API trên một route thử có phiên bản cho R3.1 đến R3.5; test CORS cho R3.6.

## Tiêu chí chấp nhận

- [ ] R3.1: tài nguyên thử đã bật R3 trả `ETag: "7"` cho phiên bản 7 ở cả `GET` lẫn phản hồi của `PATCH`.
- [ ] R3.13 (APS16): tài nguyên bị xóa hay ra khỏi tầm với của người gọi giữa lúc nạp và lúc ghi thì câu ghi không khớp dòng nào và người gọi nhận phản hồi của id không tồn tại; tài nguyên còn đọc được mà phiên bản đã đổi thì nhận 412; trả 412 ở cả hai trường hợp thì test đỏ.
- [ ] R3.2 (APS7): `If-Match: "6"` và `If-Match: W/"7"` đều trả 412 `precondition_failed`, phiên bản vẫn là 7 và không có dòng audit mới; gỡ phép so trong dependency thì test đỏ.
- [ ] R3.3 (APS7): route bắt buộc điều kiện, gọi thiếu `If-Match`, trả 428 `precondition_required` và không đổi gì.
- [ ] R3.4: `If-None-Match: *` trên tài nguyên đã có trả 412 và không tạo dòng nào.
- [ ] R3.5: Merge Patch `{"a": null, "b": {"c": 1}}` xóa `a`, trộn `b` và giữ các trường khác, với cả hai `Content-Type`.
- [ ] R3.6: preflight CORS cho phép `If-Match`; phản hồi lộ `ETag` và `Location`.
- [ ] R3.7 (APS16): người B không đọc được tài nguyên X gửi `If-Match` khớp và lệch tới X nhận đúng phản hồi của một id không tồn tại; người ở tenant B gửi `If-Match` tới id của một tài nguyên tenant A cũng nhận phản hồi đó; so điều kiện trước khi nạp tài nguyên thì test đỏ.
- [ ] R3.9 (APS18): hai `PATCH` chạy song song thật (hai kết nối, một rào đồng bộ trước câu ghi) cùng `If-Match: "7"` cho một thành công và một 412 `precondition_failed`, và phiên bản là 8; tách phép so khỏi câu `UPDATE` thì test đỏ.
- [ ] R3.11 (APS16): người ở tenant B tạo với `If-None-Match: *` một tài nguyên có id trùng id của tenant A thì tài nguyên được tạo trong tenant B, không 412, và dòng của tenant A không đổi.
- [ ] R3.12 (APS22): thêm một route thử `PATCH` trả tài nguyên có `version` mà không bật `RequireIfMatch` làm test dựng ứng dụng đỏ và nêu route đó; gỡ phép kiểm thì test đỏ.
- [ ] R3.10: `PATCH` với `Content-Type: application/json-patch+json` trả 415 `unsupported_media_type` và phiên bản không đổi.
- [ ] R3.8 (APS7): route bắt buộc điều kiện nhận `If-Match: *` trả 428 `precondition_required` và không đổi gì; nhận `*` thì test đỏ.
- [ ] R2.1: `PATCH` mang `If-Match: "6"` và `Idempotency-Key` thành công (phiên bản lên 7), gửi lại nguyên yêu cầu nhận 200 đã lưu, không 412.
- [ ] R4.1: trang kế mang con trỏ phiên bản 2 có thẻ kiểu, pha và `id`.
- [ ] R4.2: test thuộc tính phân trang 1.000 dòng có giá trị trùng và 10% NULL, chiều tăng và giảm, kích thước trang từ 1 đến 50: mỗi dòng xuất hiện đúng một lần, NULL ở cuối.
- [ ] R4.3: con trỏ cấp cho cây lọc khác, `order_by` khác hay `fields` khác đều trả 422.
- [ ] R4.4 (APS8): con trỏ người A nhận ở workspace W1, dùng bởi người B chỉ thuộc W2, trả 422 của R4.3 hay một trang chỉ gồm dòng B đọc được, không bao giờ một dòng B không đọc được; con trỏ tenant A nhận được dùng bởi người ở tenant B trả 422 hay một trang chỉ gồm dòng của tenant B; đổi truy vấn để lấy phạm vi từ con trỏ thì test đỏ.
- [ ] R4.5: cùng cây lọc với thứ tự khóa khác nhau cho cùng dấu vân tay.
- [ ] R4.6: con trỏ không phải JSON base64url, thẻ kiểu không hợp kiểu, pha lạ, pha `nulls` mang giá trị, `id` không là uuid đều trả 422 `validation_failed` và không câu SQL nào chạy.
- [ ] R5.1 (APS9): độ sâu 6, 51 lá, `$in` 501 giá trị, chuỗi 1.025 byte đều trả 422 với `errors[].pointer` đúng nút và không câu SQL nào chạy; độ sâu 5, 50 lá, 500 giá trị, 1.024 byte được nhận; gỡ giới hạn thì test đỏ.
- [ ] R5.2: lá dùng `$gt` trên trường `bool` trả 422 với pointer vào lá đó.
- [ ] R5.3: `order_by=name desc` sắp đúng và câu SQL sinh ra kết thúc bằng `id`.
- [ ] R5.4: `order_by` nêu trường không sắp được trả 422 với `errors[].parameter` bằng `order_by`.
- [ ] R5.5: `fields=name` trả chỉ `name` và `id`.
- [ ] R5.6: lá nêu trường không lọc được trả 422 với `code` `validation_failed` và `errors[0].code` `field_not_filterable`; lá nêu trường không có trong lược đồ của route trả `errors[0].code` `field_not_readable`; đặt mã lý do vào `code` cấp trên thì test đỏ.
- [ ] R5.7: cùng một cây lọc sai qua `GET ?filter=` và qua thân `POST <danh sách>/query` cho cùng `errors[]`, pointer bắt đầu bằng `/filter`.
- [ ] R5.8: độ sâu 6, 51 lá, `$in` 501 giá trị, chuỗi 1.025 byte và `$gt` trên `bool` cho đúng `filter_too_deep`, `filter_too_many_leaves`, `filter_in_too_many_values`, `filter_string_too_long`, `operator_not_allowed` ở `errors[0].code`.
- [ ] R5.8: lá `{"a": {"$eq": 1}, "b": {"$eq": 2}}`, lá `{"age": {"$gt": 1, "$lt": 5}}`, `{"$and": []}` và giá trị chuỗi cho một trường `int` đều trả 422 với `errors[0].code` `filter_malformed` và pointer tới nút đó, không câu SQL nào chạy.
- [ ] R5.9: `order_by=name desc, created_at` trả 422 với `errors[0].parameter` `order_by` và `errors[0].code` `order_by_too_many_fields`, không câu SQL nào chạy.
- [ ] R6.1 (APS10): gỡ index trang feedback trong giao dịch test làm kiểm hình kế hoạch đỏ, nêu câu lệnh và cột; bảng nhỏ không qua mặt nhờ `enable_seqscan = off`.
- [ ] R6.2: kiểm hình kế hoạch xanh trên năm route phân trang và danh sách audit theo lượt chạy sau khi sửa index.
- [ ] G7: `test_a_v1_cursor_still_resumes_where_it_left_off` xanh ở commit gốc và sau thay đổi.
- [ ] G8: `test_a_cursor_from_an_older_format_version_is_refused` xanh trước và sau thay đổi.
- [ ] Xong: `make test-unit test-contract test-integration` xanh.

## Nguồn

- `packages/python/dw_kernel/src/dw_kernel/errors.py:13-30`, `packages/typescript/ui/src/region-state.tsx:29-48`; spec: R3.2, R3.3.
- `apps/api/src/dw_api/main.py:52-60`, `apps/api/src/dw_api/main.py:107-113`; spec: R3.6.
- `packages/python/dw_kernel/src/dw_kernel/pagination.py:47-53`, `packages/python/dw_kernel/src/dw_kernel/pagination.py:91-119`, `packages/python/dw_kernel/src/dw_kernel/pagination.py:185-210`; spec: R4.1, R4.3, G7, G8.
- `packages/python/dw_kernel/tests/unit/test_pagination.py:103-112`; spec: G8.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/keyset.py:22-53`; spec: R4.2.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/repositories.py:234-260`, `packages/python/dw_platform/src/dw_platform/adapters/persistence/repositories.py:364-378`; spec: R6.2.
- `db/migrations/sql/0001_platform_baseline.sql:656`, `db/migrations/sql/0001_platform_baseline.sql:665`, `db/migrations/versions/6d4aed20ccf2_platform_approval_and_audit_pages_carry_.py:102-105`; spec: R6.1.
- ADR-0108 (Accepted) điểm 2 và 3.

## Comments

- 2026-10-26 (agent): theo spec sửa ngày 26/10/2026 (R3.7, R3.8, R4.6, R5.7 tới R5.9, APS16; R5.3 còn một trường); chờ ticket 02 vì test R2.1 cùng `If-Match` cần cột `request_preconditions`.
- 2026-10-27 (agent): theo spec sửa ngày 27/10/2026: R3.9 và APS18, test âm xuyên tenant cho APS8 và APS16, index audit theo lượt chạy mang `workspace_id`, cách đếm và bảng toán tử của cây lọc.
- 2026-10-27 (agent): theo lần sửa sau gate thứ ba: R3.10, ngữ pháp lá và `filter_malformed`, APS8 nhận 422 hay một trang của người gọi, R3 chỉ cho route bật `RequireIfMatch`.
- 2026-10-27 (agent): theo lần sửa sau gate thứ tư: R3.11, R3.12 và APS22; kiểm hình kế hoạch bắt cả trang đầu, cột sắp được index giao thứ tự là đạt.
- 2026-10-27 (agent): theo phương án A của Đạt: R3 bật theo tài nguyên (R3.1 cho cả `GET`), R3.13, cách đếm độ sâu có ví dụ.
