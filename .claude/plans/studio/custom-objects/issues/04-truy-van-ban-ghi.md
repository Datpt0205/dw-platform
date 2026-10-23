# 04 — Truy vấn bản ghi: cây lọc, sắp keyset có kiểu, đếm có trần

Status: needs-info (DO-16)
Blocked by: 03
Area: studio
Yêu cầu: R8.1, R8.2, R8.3, R8.4, R8.5, R8.6, R8.7, R8.8, R8.9, R9.1, CO7, CO19

## Mục tiêu

Danh sách bản ghi lọc và sắp theo trường lọc được, theo thứ tự tiếng Việt, phân trang keyset không trùng không sót
và luôn có chỉ mục dưới RLS (R8), cùng số đo YC20 trên mã thật ở quy mô D12 (R9.1). Bước quy trình
`data.object.query` (workflow-nodes/04) và công cụ `obj.<api_name>.search` (tools-and-skills/03) dùng cùng trình biên
dịch này qua `RecordService`.

## Việc cần làm

1. `RecordQueryCompiler` trong `dw_studio.records.adapters` (chỗ duy nhất có SQL bản ghi) biên dịch cây lọc JSON của
   app-standards/03 sang SQLAlchemy Core, chỉ dùng tham số bind:
    - tổ hợp `$and`, `$or`; lá `{field: {op: value}}` với `$eq`, `$in`, `$lt`, `$lte`, `$gt`, `$gte` trên slot `t`,
      `u`, `i`, `f`, `d`, `z`, `b` và trên `name`, `created_at`, `updated_at`; `$not`, `$ne` → 422
      `operator_not_supported` (Quyết định ngày 23/10/2026 của spec);
    - giới hạn của ADR-0108 (Proposed) quyết định 2: sâu tối đa 5, tối đa 50 lá, `$in` tối đa 500 giá trị, chuỗi tối
      đa 1.024 byte; vượt → 422 có con trỏ JSON tới nút vượt;
    - kiểm từng nút với describe của người gọi trước khi sinh SQL: trường không tồn tại hay Đã ẩn → cùng 422
      `field_not_readable`; trường đọc được nằm trong `data` → 422 `field_not_filterable`;
    - giá trị so khớp đi qua cùng bộ ép kiểu và chuẩn hóa của `RecordService` (số điện thoại so theo E.164);
    - luôn thêm `tenant_id = :tenant`, `object_id = :object` và `deleted_at IS NULL`.
2. Sắp: `order_by` theo AIP-132 trên trường sắp được (`name`, `created_at`, `updated_at`, slot), luôn thêm `id` cuối;
   chữ sắp với `COLLATE "vi-VN-x-icu"`; NULL ở cuối bằng hai pha `values`, `nulls` của con trỏ v2 (app-standards/03);
   con trỏ mang dấu vân của cây lọc và `order_by`, lệch → 422.
3. `limit` mặc định 50, tối đa 200; `count=none|exact`, `exact` đếm tới 10.000 rồi trả 10.000 kèm
   `count_capped: true`; `fields` chỉ nhận trường đọc được.
4. Route `GET /api/v1/studio/objects/{api_name}/records?filter=&order_by=&fields=&limit=&cursor=&count=` (`filter` là
   JSON mã hóa URL) và `POST /api/v1/studio/objects/{api_name}/records/query` (cây lọc trong thân), cùng trình biên
   dịch, cùng kiểm quyền đối tượng và RLS như ticket 03.
5. Test hình kế hoạch qua harness của app-standards/03: ma trận mọi toán tử nhân mọi họ slot nhân sắp tăng và giảm,
   chạy câu lệnh bắt từ trình biên dịch bằng `dw_app` dưới RLS với `SET LOCAL enable_seqscan = off`; mỗi vị từ và cột
   sắp phải là `Index Cond`, `Recheck Cond`, hoặc một index scan giao đúng thứ tự.
6. Đo lại R9.1 bằng `scripts/bench_records_storage.py` của ticket 01 trên lược đồ, trình biên dịch và policy thật của
   record-access/03, với người gọi ở mỗi mức truy cập; ghi số vào Comments.

## Tiêu chí chấp nhận

- [ ] R8.1: danh sách trả bản ghi chưa xóa người gọi đọc được, đúng cây lọc và `order_by`; bản ghi đã xóa mềm không
      có; `limit=200` thì nhận, `limit=201` → 422.
- [ ] R8.2: sắp theo `name` trả "An, Ánh, Ân, Bình, Đạt" và "Dũng, Đức, Em" đúng thứ tự; test so với danh sách viết
      sẵn, không so với `sorted()` của Python.
- [ ] R8.3: ba trang liên tiếp trên dữ liệu có giá trị trùng và NULL → hợp ba trang bằng tập khớp, không phần tử nào
      lặp, NULL ở cuối.
- [ ] R8.4 (CO7): lọc, sắp và `fields` trên trường lạ `khong_co` và trường Đã ẩn `phone` → cùng 422
      `field_not_readable`, cùng thông điệp, không câu lệnh SQL nào chạy.
- [ ] R8.5: lọc trên một trường đọc được nằm trong `data` → 422 `field_not_filterable`.
- [ ] R8.6: cây sâu 6, cây 51 lá, `$in` 501 giá trị, chuỗi 1.025 byte → mỗi trường hợp 422 với con trỏ đúng nút;
      sâu 5, 50 lá, 500 giá trị, 1.024 byte thì nhận.
- [ ] R8.7: `cursor` của trang trước đi kèm một cây lọc khác → 422.
- [ ] R8.8: 10.000 bản ghi khớp → `count` 10000, không cờ; 10.001 → `count` 10000 và `count_capped: true`.
- [ ] R8.9 (CO19): ma trận hình kế hoạch xanh; biên dịch thử một vị từ qua `data->>` → test đỏ; bỏ
      `tenant_id = :tenant` khỏi một câu lệnh → test đỏ.
- [ ] R9.1: ở quy mô D12, mỗi mức truy cập có trang đầu 50 dòng p95 ≤ 50 ms và `GET` một bản ghi p95 ≤ 5 ms, số và
      `EXPLAIN` ở Comments; sai nếu đo ở quy mô nhỏ hơn D12.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `packages/python/dw_kernel/src/dw_kernel/pagination.py:108-118`; `packages/python/dw_kernel/src/dw_kernel/pagination.py:47-48`;
  spec: R8.1, R8.3.
- `CLAUDE.md:246-249`; spec: R8.9.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_members.py:46`; spec: R8.2.
- ADR-0108 (Proposed) quyết định 2; ADR-0107 (Proposed) quyết định 2, 7; ADR-0106 (Proposed) quyết định 4.

## Comments
