# 04 — Truy vấn bản ghi: cây lọc, sắp keyset có kiểu, đếm có trần

Status: resolved
Blocked by: 03
Area: studio
Yêu cầu: R3.3, R3.4, R3.6, R4.3, R8.1, R8.2, R8.3, R8.4, R8.5, R8.6, R8.7, R8.8, R8.9, R9.1, CO1, CO7, CO8, CO19

## Mục tiêu

Danh sách bản ghi lọc và sắp theo trường lọc được, theo thứ tự tiếng Việt, phân trang keyset không trùng không sót
và luôn có chỉ mục dưới RLS (R8), cùng chế độ đo trên mã thật mà ticket 09 chạy ở quy mô D12 (R9.1). Bước quy trình
`data.object.query` (workflow-nodes/04) và công cụ `obj.<api_name>.search` (tools-and-skills/03) dùng cùng trình biên
dịch này qua `RecordService`.

## Việc cần làm

1. `RecordQueryCompiler` trong `dw_studio.records.adapters` (chỗ duy nhất có SQL bản ghi) không là trình biên dịch thứ
   hai: nó dựng `QuerySchema` (`dw_kernel.filters`) theo người gọi từ describe của ticket 03, ánh xạ mỗi trường sang cột
   (`name`, `created_at`, `updated_at`, slot), rồi dùng nguyên phần app-standards/03 đã dựng: phân tích và giới hạn của
   `dw_kernel.filters` (sâu 5, 50 lá, `$in` 500 giá trị, chuỗi 1.024 byte; ADR-0108 (Accepted) quyết định 2), mã lý do
   của nó (`field_not_readable`, `field_not_filterable`, `operator_not_allowed`), `list_identity` và con trỏ v2 của
   `dw_kernel.pagination`, `keyset` của `dw_platform.adapters.persistence`, và `query_body` cùng bộ phân tích tham số
   của `apps/api/src/dw_api/dependencies/listing.py` (gate 4/11/2026 (d)). Chỉ tham số bind:
    - tổ hợp `$and`, `$or`; lá `{field: {op: value}}` với `$eq`, `$in`, `$lt`, `$lte`, `$gt`, `$gte` trên slot `t`,
      `u`, `i`, `f`, `d`, `z` và trên `name`, `created_at`, `updated_at`, chỉ `$eq` trên slot `b`; `$not`, `$ne`, và
      `$eq: null` hay `null` trong `$in` (chỉ mục từng phần của slot không mang `IS NULL`) → 422 `validation_failed` với
      `errors[].code` `operator_not_allowed` của kernel (Quyết định ngày 23/10/2026 của spec; gate (b));
    - kiểm từng nút với describe của người gọi trước khi sinh SQL: trường không tồn tại hay Đã ẩn → `field_not_readable`
      với con trỏ tới nút; trường đọc được nằm trong `data` → `field_not_filterable`; lỗi ở `order_by` và `fields` mang
      `errors[].parameter` như kernel trả, không con trỏ; không thân lỗi nào nhắc lại giá trị đã gửi;
    - giá trị so khớp đi qua cùng bộ ép kiểu và chuẩn hóa của `RecordService` trước phép so có kiểu của kernel: số điện
      thoại so theo E.164, email chữ thường, chữ NFC; số `exact` và tiền là chuỗi thập phân như lúc ghi (ticket 03,
      gate (e)) đổi ra số nguyên đã nhân `10^scale`; số JSON, hay giá trị không ép được → 422 `invalid_type` có con trỏ
      tới lá (gate (f));
    - luôn thêm `tenant_id = :tenant`, `object_id = :object` và `deleted_at IS NULL`;
    - `owner` và `workspace` lọc được với `$eq`, `$in` (chỉ mục `(tenant_id, owner_id, object_id, ...)` của
      record-access/03 và `(tenant_id, workspace_id)` của ticket 02); lọc theo một lựa chọn đã tắt của danh sách chọn
      được nhận, vì bộ ép kiểu của đường lọc chỉ kiểm khóa có tồn tại, không kiểm `active`, và lỗi độ dài hay số chữ số
      thập phân của giá trị lọc mang `invalid_type`.
      1a. Phần mở rộng kernel mà các gạch trên cần, nhỏ nhất và mặc định giữ nguyên hành vi của mọi danh sách khác
      (`dw_kernel.filters`, chủ là app-standards/03; lượt xác nhận (j)): `QueryField` thêm `null_allowed: bool = True`
      (bản ghi đặt sai, nên `$eq: null` và `null` trong `$in` trả `operator_not_allowed`) và một hàm ép giá trị lá tùy
      chọn, chạy trước so sánh có kiểu, ném `QueryProblem` mã `invalid_type` mới của `ReasonCode`; kiểm cấu trúc (sâu,
      số lá, `$in`, độ dài chuỗi) chạy trước kiểm từng lá, nên một cây sâu 6 trả `filter_too_deep` dù có lá sai kiểu;
      `query_json_schema(schema)` mới xuất lược đồ JSON của cây lọc cho một `QuerySchema`, với kiểu trên dây (số `exact`
      và tiền là chuỗi thập phân), là chủ duy nhất của lược đồ mà bước 5 dùng. `listing.py`: `query_body` nhận thêm
      `count`; `count` vào `params` của `list_identity`; route bản ghi dựng `QuerySchema` theo người gọi và `api_name` rồi
      gọi `parse_query`; `GET` nhận `filter` → 422 `parameter_not_accepted` với `errors[].parameter` `filter`, `order_by`
      ngoài `created_at`, `updated_at` → `parameter_not_accepted` với `errors[].parameter` `order_by`.
2. Sắp: W1 chỉ nhận `order_by` trên `name`, `created_at`, `updated_at`, ba cột NOT NULL đều có chỉ mục
   `(tenant_id, object_id, <cột>, id)`; mặc định `created_at desc` khi không gửi `order_by`; luôn thêm `id` cuối; `name`
   sắp với `COLLATE "vi-VN-x-icu"`; `order_by=name` khi `name` Đã ẩn với người gọi → `field_not_readable`. Sắp theo
   slot ra W2, khi ticket 07 hay 09 đo chỉ mục cho pha NULL (chỉ mục slot hiện chỉ mang giá trị khác NULL), nên describe
   ở W1 đánh dấu "sắp được" đúng ba cột đó (spec R8.2, R8.3; gate (b), (c)). Con trỏ mang dấu vân của cây lọc,
   `order_by`, `fields` và `count` qua `list_identity`; lệch → 422.
3. `limit` mặc định 50, tối đa 200; `count=none|exact`, `exact` đếm tới 10.000 trên toàn tập khớp mà người gọi đọc được
   (RLS áp cho cả câu đếm) rồi trả 10.000 kèm `count_capped: true`; `count` là phần của dấu vân con trỏ, nên trang sau
   gửi cùng `count`, và chỉ trang đầu (không `cursor`) đếm; trang sau không có `count`. Thân trang
   `{items, next_cursor, count?, count_capped?}`, `count_capped` có mặt cùng `count`; mỗi phần tử cùng hình với `GET` một bản
   ghi của ticket 03 (`id`, `version`, `etag`, `owner`, `workspace_id`, `fields` chỉ trường đọc được, `hidden_fields`),
   không `permissions`.
4. Route `GET /api/v1/studio/objects/{api_name}/records?order_by=&fields=&limit=&cursor=&count=` và
   `POST /api/v1/studio/objects/{api_name}/records/query` (cây lọc và mọi tham số trong thân, qua `query_body`), cùng
   trình biên dịch, cùng kiểm quyền đối tượng và RLS như ticket 03. `GET` không nhận `filter`, và chỉ nhận `order_by`
   `created_at` hay `updated_at`: giá trị lọc trên trường dữ liệu cá nhân và con trỏ mang `name` của dòng cuối nằm
   trong thân `POST`, không bao giờ trong URL, nơi access log, thuộc tính span và `Referer` giữ chúng
   (ADR-0106 (Accepted) quyết định 4; gate (g)). `api_name` không phải đối tượng của công ty người gọi → 404; thiếu
   `obj.<api_name>.read` → 403 `permission_denied` trước SQL (spec R3.3, R3.4).
5. `ObjectSchemaProjector` của ticket 02 thay lược đồ `query` phẳng bằng lược đồ JSON của cây lọc mà kernel xuất cho
   `QuerySchema` của người gọi, nên công cụ `obj.<api_name>.search`, bước `data.object.query` và route dùng một ngữ pháp
   (gate (h)).
6. Test hình kế hoạch qua `tests/support/plan_shape.py` của app-standards/03: ma trận mọi toán tử nhân mọi họ slot nhân
   ba cột sắp tăng và giảm, dưới bốn hồ sơ của record-access:R9.10 (Của tôi, Workspace của tôi, Toàn công ty,
   `public_read`), chạy câu lệnh bắt từ trình biên dịch bằng `dw_app` dưới RLS với `SET LOCAL enable_seqscan = off`; mỗi
   vị từ là `Index Cond` hay `Recheck Cond`, trừ khi planner đi chỉ mục tầm của RLS (`owner_id`, `access_key`) ở hồ
   sơ Của tôi hay Workspace của tôi: khi đó vị từ slot là Filter trên tập tầm, được nhận, và Index Cond của nút quét
   phải dẫn bằng `tenant_id`; cột sắp do chỉ mục giao đúng thứ tự khi không có cây lọc hay khi cây lọc chỉ nêu chính cột
   sắp; khi lọc trên một slot và sắp theo cột khác, ca đó chạy với `enable_sort` bật qua một `Expectation` mới của
   `plan_shape` khẳng định một Sort top-N có nút con là một quét chỉ mục dẫn bằng `tenant_id` (gate (c); lượt xác nhận
   (k)); không Seq Scan nào trên `studio.records` hay partition.
7. Số đo trên mã thật ở quy mô smoke: thêm vào harness của custom-objects/01 một chế độ đường thật, áp `db/migrations`
   vào database đo (DDL tạm A0 modulus 4 của ticket 02, không biến thể nào của harness), gieo định nghĩa qua móc phát
   hành của ticket 02 với phê duyệt fixture, vai, lần gán và thành viên bằng SQL của `dw_migrator` vào bảng thật (dữ liệu
   gieo, không phải thứ đang đo), và bản ghi qua `RecordService`; đo trong tiến trình qua `RecordService` và
   `RecordQueryCompiler`, không qua route, ở bốn hồ sơ của record-access:R9.10, cùng một lần soak và một lần nhập theo
   cỡ smoke để đi qua đường của R9.6, R9.10 (lượt xác nhận (l)); đọc và ghi qua `RecordService` và `RecordQueryCompiler` thay câu SQL
   của harness, bật bằng cờ `--real-path`, cho trang đầu 50 dòng, `GET` một bản ghi, tạo và sửa một trường, ở mỗi hồ
   sơ quyền; chạy
   `--scale smoke` trên máy dev, ghi số vào Comments dưới nhãn "smoke, máy dev, không phải số D12", không so với ngưỡng
   R9. Lần chạy `--scale d12` cùng chế độ đó (R9.1, R9.6, R9.10) là ticket 09 (`ready-for-human`, Chờ Đạt 23) (gate (a)).

## Tiêu chí chấp nhận

- [ ] R8.1: danh sách trả bản ghi chưa xóa người gọi đọc được, đúng cây lọc và `order_by`; bản ghi đã xóa mềm không
      có; không gửi `order_by` → theo `created_at` giảm dần; `limit=200` thì nhận, `limit=201` → 422.
- [ ] R3.3: người của công ty B gọi `GET .../records`, `POST .../records/query` và `count=exact` với `api_name` chỉ
      công ty A có → 404, không SQL bản ghi nào chạy.
- [ ] R4.3 (CO1): khi cả hai công ty có cùng `api_name`, người của B nhận chỉ bản ghi của B, `count` chỉ đếm bản ghi
      của B; bản ghi ngoài tầm của người gọi không có trong trang lẫn trong `count`.
- [ ] R3.4 (CO8): người thiếu `obj.<api_name>.read` gọi hai route danh sách → 403 `permission_denied` trước SQL; gỡ
      kiểm khóa đọc → test đỏ.
- [ ] R8.2: sắp theo `name` trả "An, Ánh, Ân, Bình, Đạt" và "Dũng, Đức, Em" đúng thứ tự; test so với danh sách viết
      sẵn, không so với `sorted()` của Python.
- [ ] R8.3: ba trang liên tiếp theo `name` trên dữ liệu có giá trị trùng → hợp ba trang bằng tập khớp, không phần tử nào
      lặp; `order_by` trên một slot → 422.
- [ ] R8.4 (CO7): lọc, sắp và `fields` trên trường lạ `khong_co` và trên trường Đã ẩn `phone` → 422
      `validation_failed` với `errors[].code` `field_not_readable`, con trỏ tới đúng nút cho cây lọc và
      `errors[].parameter` cho `order_by`, `fields`, không câu lệnh SQL nào chạy; bỏ kiểm trường Đã ẩn trước SQL → test
      đỏ.
- [ ] R8.5: lọc trên một trường đọc được nằm trong `data` → 422 `validation_failed` với `errors[].code`
      `field_not_filterable` và con trỏ tới lá đó.
- [ ] R8.6: cây sâu 6, cây 51 lá, `$in` 501 giá trị, chuỗi 1.025 byte → mỗi trường hợp 422 với con trỏ đúng nút;
      sâu 5, 50 lá, 500 giá trị, 1.024 byte thì nhận; `$ne`, `$eq: null` → 422 `operator_not_allowed`.
- [ ] R8.7: `cursor` của trang trước đi kèm một cây lọc khác, hay một `count` khác → 422.
- [ ] R8.8: 10.000 bản ghi khớp → `count` 10000, không cờ; 10.001 → `count` 10000 và `count_capped: true`.
- [ ] R8.9 (CO19): ma trận hình kế hoạch xanh ở bốn hồ sơ; biên dịch thử một vị từ qua `data->>` → test đỏ; test đơn
      vị trên văn bản câu lệnh mà trình biên dịch sinh: mọi câu có `tenant_id = :tenant`, bỏ nó khỏi trình biên dịch →
      test đỏ (RLS vẫn che nên test chức năng không đỏ được; lượt xác nhận (m)).
- [ ] R8.1: Lead lưu "+84901234567", lọc `{"phone": {"$eq": "0901 234 567"}}` qua `POST .../query` → có Lead đó;
      lọc tiền `{"amount": {"$gte": "1000.50"}}` trên trường `scale` 2 → so với 100050; `{"$gte": 1000.5}` → 422
      `invalid_type`.
- [ ] R8.4: `GET .../records?filter=...` → 422 với `errors[].parameter` `filter`; `GET ...?order_by=name` → 422;
      cùng truy vấn qua `POST .../query` → 200.
- [ ] R3.6: lược đồ `query` của bộ chiếu là lược đồ cây lọc của kernel cho người gọi, không có trường Đã ẩn; một cây
      lọc hợp lệ theo lược đồ đó được route nhận.
- [ ] R9.1: chế độ đường thật của harness chạy `--scale smoke` thoát 0, đi qua `RecordService` (một bộ đếm lời gọi
      của service khác 0 ở mọi phép đo), số ở Comments dưới nhãn smoke; sai nếu số nào được so với ngưỡng R9 hay ghi vào
      ADR.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `packages/python/dw_kernel/src/dw_kernel/pagination.py:108-118`; `packages/python/dw_kernel/src/dw_kernel/pagination.py:47-48`;
  spec: R8.1, R8.3.
- `CLAUDE.md:290-293`; spec: R8.9.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_members.py:46`; spec: R8.2.
- ADR-0108 (Accepted) quyết định 2; ADR-0107 (Accepted) quyết định 2, 7; ADR-0106 (Accepted) quyết định 4.

## Comments

- 2026-10-23 (agent): DO-16.1 (a) và ADR-0108 (Accepted) với DO-16 (a) đã có lời đáp (Đạt, 23/10/2026); Status về needs-triage. Mã lỗi lọc, sắp thành `errors[].code` dưới `validation_failed`; tên trường Đã ẩn là công khai (`B:custom-objects:R6.5~field-security:R3.3`).
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate của ticket 01, HIGH 3: RecordService chưa có khi ticket 01 đo, nên ticket 01 đo R9.6 và R9.10 trên đường ghi mô phỏng của harness, và ticket này đo lại hai dòng đó qua RecordService thật (bước 6). Nếu sai thì: ticket 03 đo lại hai dòng đó, và bước 6 trở về chỉ R9.1.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk, hai subagent, vì ticket thêm
  route), đọc cùng phần app-standards/03 đã dựng (`dw_kernel.filters`, `dw_kernel.pagination`, `listing.py`,
  `plan_shape.py`) và harness của ticket 01: 1 CRITICAL, 8 HIGH, sửa theo khuyến nghị (Quyết định 4/11/2026 của spec):
  (i) CRITICAL, test âm chéo công ty, thiếu khóa đọc và ngoài tầm cho hai route danh sách và `count`; (a) R9.1, R9.6,
  R9.10 ở D12 sang ticket 09 mới, ticket này dựng chế độ đường thật và chạy smoke; (b) W1 sắp theo ba cột hệ thống, lá
  `null` → 422; (c) hình kế hoạch khi lọc và sắp khác cột; (d) dùng lại kernel và `listing.py`; (f) giá trị lọc qua bộ
  ép kiểu; (g) giá trị và con trỏ không vào URL; (h) một ngữ pháp truy vấn. Thay Comments 2026-11-02: số D12 của R9.6,
  R9.10 trên mã thật là của ticket 09; ticket này chạy đường của chúng ở smoke.
- 2026-11-04 (agent): MEDIUM để lại: (M1) không trần thời gian câu lệnh hay giới hạn tốc độ cho danh sách và
  `count=exact`; ticket 09 đo `count` ở D12, `statement_timeout` của vai `dw_app` là của foundations-hardening; (M2)
  quyền kiểm lại ở mỗi trang vì route chạy lại kiểm (ADR-0108 (Accepted) quyết 2), không ràng con trỏ với người gọi;
  (M3) câu gợi ý "Của tôi" của phương án W (record-access/01) không đưa vào trình biên dịch tới khi ticket 09 đo; (M4) cặp
  với ticket 07 (`studio.records`) nay có phụ thuộc: ticket 07 chờ ticket này.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận: 0 CRITICAL, 4 HIGH, sửa: (j) phần mở rộng nhỏ nhất của kernel (`null_allowed`, hàm ép
  lá, mã `invalid_type`, `query_json_schema`) và của `listing.py` (`count` trong thân và trong dấu vân, `GET` không nhận
  `filter`), bước 1a; (k) `Expectation` mới của `plan_shape` cho Sort top-N và vị từ slot là Filter dưới chỉ mục tầm;
  (l) cách gieo và đo của chế độ đường thật; (m) test văn bản cho `tenant_id = :tenant`. Sửa luôn: `owner`, `workspace`
  lọc được; lọc lựa chọn đã tắt; chỉ trang đầu đếm. Sửa của lượt này không có người đọc mới: nhận rủi ro (agent, theo ủy quyền 31/10/2026). Nếu sai
  thì: ghi ở đây khi dựng. Thứ tự dựng: sau 03; trước 05, 07, 09.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-06 (agent, lane 2): dựng. `dw_kernel.filters` thêm `null_allowed`, `coerce` (lỗi → `invalid_type` mới của
  `ReasonCode`), kiểm giới hạn cả cây trước mọi lá (`_bounds`) và `query_json_schema`; mọi danh sách khác giữ hành vi
  (test kernel cũ xanh nguyên). `RecordService.query(door, api_name, parse, count=)`: một giao dịch, `_enter` (404, 403)
  rồi quyết định trường rồi `parse(QuerySchema của người gọi)` rồi SQL; `parse` là `RawListQuery.parse` của
  `listing.py` cho route, `parse_query` cho cửa khác. `RecordQueryCompiler` (adapter) chỉ bọc phạm vi
  `tenant_id = :tenant AND object_id = :object AND deleted_at IS NULL` quanh `compile_filter` và pha `values` của
  `keyset_phases`. `listing.py`: `RawListQuery`, `read_query_body(counts=)` (mà `query_body` cũ dùng lại),
  `counted_listing(url_sortable=)` cho `GET`. Hai route vào `plan_shape.EXEMPT` với lý do (ma trận riêng của Studio);
  `conventions.write_routes` coi `POST <list>/query` là đọc cả khi chính danh sách là tài nguyên có phiên bản (qua
  upsert), có test riêng.
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): làm khác ticket. (1) `QuerySchema` dựng ở tầng application
  (`records/application/record_query.py`), không trong adapter, vì bộ chiếu (application) cũng xuất lược đồ JSON từ nó
  (bước 5); adapter chỉ biên dịch. Nếu sai thì: chuyển hàm dựng vào adapter và bộ chiếu nhận lược đồ qua port. (2) Con
  trỏ của lỗi giá trị (`invalid_type`, `operator_not_allowed` của `null`) trỏ tới toán hạng (`/filter/amount/$gte`),
  như mọi lỗi giá trị khác của kernel, không tới nút lá. Nếu sai thì: một dòng ở `_value` và `_null`. (3) Lá
  `workspace` không có chỉ mục mang cả `object_id`: `(tenant_id, workspace_id)` thiếu `object_id`, chỉ mục sắp thiếu
  `workspace_id`, nên ma trận giữ lá này ở "quét dẫn bằng `tenant_id`, không Seq Scan, luật sắp", không đòi vị từ ở
  Index Cond; mọi lá khác ở mọi họ slot, mọi chiều sắp và bốn hồ sơ đều đạt đầy đủ. Nếu sai thì: ticket 07 thêm chỉ mục
  `(tenant_id, object_id, workspace_id, id)` hay lá biên dịch sang `access_key`. (4) Giá trị lọc 1.024 byte qua giới
  hạn nhưng không trường nào giữ được (`max_length` tối đa 255 ký tự), nên route trả `invalid_type` của chính trường,
  còn 1.025 byte trả `filter_string_too_long`; kernel thử đúng biên ở test đơn vị. (5) Ma trận chọn giá trị biên chọn
  lọc (vài dòng mỗi chủ), vì biên khớp gần hết bảng thì planner đi chỉ mục sắp, đúng ở mọi quy mô, mà không vị từ nào ở
  Index Cond. (6) Lần soak của đường thật ghi qua cửa người (không khóa `wf:`), nên WAL chưa tính
  `studio.record_write_keys` của R5.9; ticket 09 đo lần chạy có cửa lượt.
- 2026-11-06 (agent): kiểm. Unit kernel, Studio, API, harness xanh; tích hợp mới `test_record_query.py` 14,
  `test_record_query_plan_shape.py` 3 (ma trận 1.464 ca × trang và đếm, cùng hai bản thử đỏ được: vị từ qua `data`,
  chỉ mục slot bị bỏ), `test_studio_record_lists.py` 12; sửa `test_record_service.py` (hai dòng, hình lược đồ mới);
  chạy lại `test_plan_shape.py`, `test_conditional_writes_and_queries.py`, `test_studio_records.py`,
  `test_studio_publish.py`, `test_studio_lifecycle.py` xanh. `reviewing-feature-security`: (1) tenant: B gọi
  `api_name` chỉ A có → 404 trước SQL bản ghi, cùng `api_name` → chỉ của B và `count` chỉ của B, mọi câu nêu
  `tenant_id = :tenant` (test văn bản); (2) quyền: thiếu khóa đọc → 403 trước SQL, trường Đã ẩn → 422 trước SQL, ngoài
  tầm không có trong trang lẫn `count`; (3) không công cụ hay quyền tự hành mới (lược đồ cho công cụ là của
  tools-and-skills/03); (4) không bộ nhớ, tri thức, bằng chứng; (5) không migration, hai route đọc sau cổng Studio,
  giá trị lọc và con trỏ `name` chỉ trong thân `POST`; (6) không cache mới (cache bộ chiếu giữ khóa có tenant), container
  chỉ của harness. `mutations/04.yaml` 18 đột biến, mỗi `old` khớp đúng một lần, chưa chạy. Hoãn tới đóng hàng: mutate
  (18), `make test-integration` đầy đủ, P50/P95/P99 của `GET .../records` và `POST .../records/query` (và describe vì
  cờ `sortable` đổi) so với commit bắt đầu hàng đợi.
- 2026-11-06 (agent): R9.1, chế độ đường thật, **smoke, máy dev, không phải số D12** (không so với ngưỡng R9 nào; số
  D12 là của ticket 09). `uv run python scripts/bench_records_storage.py --scale smoke --real-path`, thoát 0; container
  riêng `dwbench-postgres` (PostgreSQL 16.15 alpine, giới hạn của overlay prod, `shared_buffers` 160MB) trên Windows 11,
  Ryzen 7 7735U 16 luồng, đo cùng lúc với một lượt test tích hợp ở cluster khác (máy bận). `db/migrations` ở head (DDL
  tạm A0 modulus 4), định nghĩa qua móc phát hành với phê duyệt fixture, người và vai bằng SQL của `dw_migrator`; 20.000
  bản ghi nhập qua `RecordService.create` (8 phiên): 61,6 hàng/s. Mỗi ô 1.000 mẫu, đo trong tiến trình quanh lời gọi
  `RecordService` (gồm mở, gắn và commit giao dịch của cửa), bộ đếm lời gọi khác 0 ở mọi ô (trang đầu 1.001 vì một lần
  lấy id):

    | Hồ sơ         | Trang đầu 50 p50/p95/p99 ms | GET p50/p95/p99    | Tạo p50/p95/p99     | Sửa một trường p50/p95/p99 |
    | ------------- | --------------------------- | ------------------ | ------------------- | -------------------------- |
    | Của tôi       | 34,6 / 47,3 / 55,6          | 41,3 / 56,7 / 67,4 | 59,7 / 81,2 / 93,3  | 87,3 / 116,3 / 133,4       |
    | Workspace     | 32,1 / 43,5 / 52,2          | 33,6 / 45,9 / 55,7 | 55,9 / 76,7 / 93,3  | 77,3 / 106,7 / 119,5       |
    | Toàn công ty  | 31,7 / 46,3 / 65,7          | 33,3 / 49,7 / 73,7 | 55,9 / 80,7 / 161,2 | 75,1 / 116,5 / 196,5       |
    | `public_read` | 34,7 / 50,0 / 61,5          | 39,6 / 57,7 / 69,1 | 61,2 / 86,4 / 105,5 | 82,5 / 120,0 / 142,1       |

    Soak 300 s, 50 phiên nhắm 200 lần sửa/s qua `RecordService.update`: đạt 53,0 lần/s (19 lần 412 do hai phiên sửa cùng
    bản ghi), WAL 0,28 MB/s. Bản ghi chạy và báo cáo: `real_path.md`, `real_path.json` dưới `--out`.
