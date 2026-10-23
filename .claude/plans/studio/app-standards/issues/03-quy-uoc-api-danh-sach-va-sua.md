# 03 — ETag và If-Match, phân trang keyset có kiểu, cây lọc JSON và kiểm hình kế hoạch trong CI

Status: needs-triage
Blocked by: 01
Area: studio
Yêu cầu: R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R4.1, R4.2, R4.3, R4.4, R4.5, R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R6.1, R6.2, G7, G8, APS7, APS8, APS9, APS10

## Mục tiêu

Lát này cho mọi route danh sách và route sửa một quy ước chung: ETag mạnh với `If-Match`, 412 và 428, JSON Merge Patch (R3); con trỏ keyset phiên bản 2 có kiểu, hai chiều, NULL cuối (R4); cây lọc JSON có giới hạn cùng `order_by` và `fields` (R5); và một kiểm hình kế hoạch trong CI làm đỏ mọi truy vấn phân trang không có index mang trọn (R6, ADR-0108 (Accepted) điểm 2 và 3). API bản ghi của custom-objects là người dùng đầu tiên; ở đây các quy ước được chứng minh trên route thử và trên năm route phân trang hiện có.

## Việc cần làm

1. `ErrorCode` thêm `PRECONDITION_FAILED = "precondition_failed"` (412) và `PRECONDITION_REQUIRED = "precondition_required"` (428), cùng bản TypeScript; `ERROR_STATE` ánh xạ `precondition_failed` sang vùng `conflict` và `precondition_required` sang vùng `error`.
2. Module thuần mới `dw_kernel.http_conditions`: định dạng ETag mạnh từ phiên bản; phân tích `If-Match` và `If-None-Match` (so mạnh, `*`, danh sách; ETag yếu không bao giờ khớp). Dependency API `RequireIfMatch` trả 428 khi thiếu và 412 khi lệch, trước handler. Hàm thuần `apply_merge_patch` theo RFC 7396, nhận `application/merge-patch+json` và `application/json`.
3. CORS trong `apps/api/src/dw_api/main.py`: `_CORS_HEADERS` thêm `If-Match`, `If-None-Match`; `expose_headers` thêm `ETag`, `Location`.
4. Trước khi đổi định dạng con trỏ, viết `test_a_v1_cursor_still_resumes_where_it_left_off` với một con trỏ phiên bản 1 dựng tay; test xanh ở commit gốc. Rồi trong `packages/python/dw_kernel/src/dw_kernel/pagination.py`: con trỏ phiên bản 2 với `sort_value` có thẻ kiểu (`text`, `int`, `float`, `date`, `datetime`, `bool`, `null`) và pha `values` hay `nulls`; giải được con trỏ phiên bản 1; vẫn từ chối phiên bản 0 và phiên bản lạ; dấu vân tay tính trên JSON chuẩn, khóa đã sắp, của cây lọc, `order_by`, `fields` và route.
5. `packages/python/dw_platform/src/dw_platform/adapters/persistence/keyset.py`: thêm chiều tăng; NULL cuối thành hai pha có index (pha `values` rồi pha `nulls`); `id` luôn là khóa cuối; giữ `after_position` và `newest_first` cho năm route hiện có.
6. Module mới `dw_kernel.filters`, chỉ dùng thư viện chuẩn: mô hình cây lọc (`$and`, `$or`, `$not`; lá `{field: {op: value}}`), toán tử theo kiểu trừu tượng, giới hạn độ sâu 5, 50 lá, `$in` 500 giá trị, chuỗi 1.024 byte UTF-8, lỗi mang JSON pointer vào cây, xuất JSON Schema; trình phân tích `order_by` (AIP-132) và `fields`. Route chỉ nhận cây đã qua phép kiểm này. Mọi 422 của cây lọc, `order_by` và `fields` mang `code` `validation_failed`, mã lý do ở `errors[].code`: trường không có trong lược đồ của route là `field_not_readable` (giống trường bị ẩn, custom-objects:R8.4), trường không lọc được là `field_not_filterable` (R5.6).
7. `tests/support/plan_shape.py`: bắt câu lệnh thật bằng sự kiện `before_cursor_execute` khi gọi phương thức repository dưới `dw_app` với `app.tenant_id` đặt sẵn; chạy `EXPLAIN (FORMAT JSON)` dưới `SET LOCAL enable_seqscan = off`; khẳng định mỗi cột vị từ và cột sắp khai báo nằm trong `Index Cond` hay `Recheck Cond`, và không có nút `Sort` trên khóa keyset. Áp cho năm route phân trang và danh sách audit theo lượt chạy; sửa index mà test tìm ra trong một migration mới (dự kiến `platform.feedback (tenant_id, created_at DESC, id DESC)` thay `ix_feedback_tenant_created`). Index `platform.audit_events (tenant_id, run_id, occurred_at)` trên bảng cha là index audit theo lượt chạy duy nhất của nền tảng: ticket này là chủ, ADR-0122 (Accepted) bỏ `ix_audit_events_run`, và telemetry-and-audit/02 chờ ticket này (OPS-b).
8. Test: test thuộc tính cho R4.2 trên bảng thử có giá trị trùng và NULL, cả hai chiều; test API trên một route thử có phiên bản cho R3.1 đến R3.5; test CORS cho R3.6.

## Tiêu chí chấp nhận

- [ ] R3.1: route thử trả `ETag: "7"` cho phiên bản 7.
- [ ] R3.2 (APS7): `If-Match: "6"` và `If-Match: W/"7"` đều trả 412 `precondition_failed`, phiên bản vẫn là 7 và không có dòng audit mới; gỡ phép so trong dependency thì test đỏ.
- [ ] R3.3 (APS7): route bắt buộc điều kiện, gọi thiếu `If-Match`, trả 428 `precondition_required` và không đổi gì.
- [ ] R3.4: `If-None-Match: *` trên tài nguyên đã có trả 412 và không tạo dòng nào.
- [ ] R3.5: Merge Patch `{"a": null, "b": {"c": 1}}` xóa `a`, trộn `b` và giữ các trường khác, với cả hai `Content-Type`.
- [ ] R3.6: preflight CORS cho phép `If-Match`; phản hồi lộ `ETag` và `Location`.
- [ ] R4.1: trang kế mang con trỏ phiên bản 2 có thẻ kiểu, pha và `id`.
- [ ] R4.2: test thuộc tính phân trang 1.000 dòng có giá trị trùng và 10% NULL, chiều tăng và giảm, kích thước trang từ 1 đến 50: mỗi dòng xuất hiện đúng một lần, NULL ở cuối.
- [ ] R4.3: con trỏ cấp cho cây lọc khác, `order_by` khác hay `fields` khác đều trả 422.
- [ ] R4.4 (APS8): con trỏ người A nhận ở workspace W1, dùng bởi người B chỉ thuộc W2, trả trang chỉ gồm dòng B đọc được; đổi truy vấn để lấy phạm vi từ con trỏ thì test đỏ.
- [ ] R4.5: cùng cây lọc với thứ tự khóa khác nhau cho cùng dấu vân tay.
- [ ] R5.1 (APS9): độ sâu 6, 51 lá, `$in` 501 giá trị, chuỗi 1.025 byte đều trả 422 với `errors[].pointer` đúng nút và không câu SQL nào chạy; độ sâu 5, 50 lá, 500 giá trị, 1.024 byte được nhận; gỡ giới hạn thì test đỏ.
- [ ] R5.2: lá dùng `$gt` trên trường `bool` trả 422 với pointer vào lá đó.
- [ ] R5.3: `order_by=name desc, created_at` sắp đúng và câu SQL sinh ra kết thúc bằng `id`.
- [ ] R5.4: `order_by` nêu trường không sắp được trả 422 với `errors[].parameter` bằng `order_by`.
- [ ] R5.5: `fields=name` trả chỉ `name` và `id`.
- [ ] R5.6: lá nêu trường không lọc được trả 422 với `code` `validation_failed` và `errors[0].code` `field_not_filterable`; lá nêu trường không có trong lược đồ của route trả `errors[0].code` `field_not_readable`; đặt mã lý do vào `code` cấp trên thì test đỏ.
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
