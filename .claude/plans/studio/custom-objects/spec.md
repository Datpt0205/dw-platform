# Đối tượng tùy biến: định nghĩa, một dịch vụ bản ghi, API và giao diện sinh từ metadata

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Công ty tự định nghĩa đối tượng và trường của mình (Lead và Campaign của Marketing trước tiên, D4) mà không
cần nhà vận hành hay migration: định nghĩa là dữ liệu trên các bảng cố định do migration tạo, và mọi đường
đọc ghi bản ghi (route, bước quy trình, công cụ agent, lane) đi qua một `RecordService` (ADR-0107 (Proposed)),
theo quy ước API của ADR-0108 (Proposed). W1 làm Lead và Campaign thành đối tượng của công ty, một
`RecordService` có Tạo hoặc cập nhật để kiểm trùng, truy vấn và giao diện danh sách tối thiểu; phần còn lại
là W2, W3 ở Ngoài phạm vi.

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- Chỉ có ba schema `knowledge`, `memory`, `platform` (`db/migrations/sql/0001_platform_baseline.sql:1-7`).
  Thiếu: chưa có bảng định nghĩa đối tượng hay bảng bản ghi; schema `studio` do studio-skeleton/01 tạo.
- `dw_app` có DML, không có `CREATE` (`db/migrations/sql/0001_platform_grants.sql:27-46`). Ràng buộc: không
  bảng, cột hay chỉ mục nào được tạo lúc chạy.
- Collation tiếng Việt đã dùng là `"vi-VN-x-icu"`
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_members.py:46`). Ràng buộc: chữ sắp
  theo đúng collation này, không collation thứ hai.
- Policy tenant hiện có đọc setting theo từng dòng (`db/migrations/sql/0001_platform_baseline.sql:770`).
  Ràng buộc: bảng của spec dùng dạng InitPlan `(SELECT ...)` mà foundations-hardening/03 đo và làm mẫu.
- `platform.workspaces` không có `UNIQUE (tenant_id, id)` (`db/migrations/sql/0001_platform_baseline.sql:478-485`).
  Thiếu: FK tổng hợp tới workspace sở hữu cần khóa của org-and-principals/01.
- `test_rls_coverage.py` lấy bảng của công ty từ catalog, kể cả bảng partition
  (`packages/python/dw_platform/tests/integration/test_rls_coverage.py:50-55`). Ràng buộc: mọi partition của
  `studio.records` qua cùng test này.
- Offboarding chọn bảng có policy `tenant_isolation_%` mà `dw_app` đọc được
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:68-86`) và xóa bằng `dw_app`
  theo `_ORDERED_FIRST` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:108-114`).
  Ràng buộc: `dw_app` không có quyền trên partition thì mỗi bản ghi xuất một lần qua bảng cha; bảng mới phải vào
  thứ tự xóa.
- Con trỏ trang chỉ mang `datetime` (`packages/python/dw_kernel/src/dw_kernel/pagination.py:108-118`), trang tối
  đa 200 (`packages/python/dw_kernel/src/dw_kernel/pagination.py:47-48`). Thiếu: con trỏ có kiểu của
  app-standards/03.
- Vỏ lỗi là `ErrorResponse{code, message, details, request_id}` (`apps/api/src/dw_api/errors.py:28-34`), mã
  `permission_denied` đã có (`packages/python/dw_kernel/src/dw_kernel/errors.py:20`). Ràng buộc: lỗi theo
  problem+json của ADR-0108 (Proposed), giữ mã hiện có.
- Trigger `platform.touch_updated_at()` nhường giá trị câu lệnh nêu
  (`db/migrations/versions/0004_touch_updated_at_yields.py:44`). Ràng buộc: bảng của spec dùng lại trigger này.
- `SUPPORT_ALLOWED_ROUTES` rỗng (`apps/api/src/dw_api/bootstrap/wiring.py:110`). Ràng buộc: ngữ cảnh hỗ trợ
  không tới route bản ghi nào ở W1.
- `formatMoney` nhận số JS (`apps/web/lib/money.ts:21`). Thiếu: tiền đến dạng chuỗi cần bộ định dạng chuỗi.
- Bộ lọc phải tìm "Hà Nội" từ "ha noi" (`.claude/rules/ui-quality.md:266`); xung đột hiện cả hai giá trị
  (`.claude/rules/ui-quality.md:111`). Ràng buộc: W1 không có ô tìm vì tìm không dấu ở W2.
- Image `postgres:16-alpine` (`infra/compose/docker-compose.yml:45`). Ràng buộc: đo và chạy trên PostgreSQL 16.
- Thời gian lập kế hoạch với 8 partition và khoảng 80 chỉ mục dưới RLS, và `unaccent` dưới `dw_migrator`, chưa
  đo (`.claude/plans/studio/discovery/issues/07-records-storage.md:10-16`). Chưa rõ: ticket 01 đo.
- Chuẩn hóa số điện thoại Việt Nam và upsert dưới policy theo từng lệnh chưa đo
  (`.claude/plans/studio/discovery/issues/10-dedupe-and-upsert.md:10-15`). Chưa rõ: marketing-pilot/01 đo câu 1;
  ticket 03 dựng theo câu 3.

## Mục tiêu

### R1 — Định nghĩa đối tượng qua API công khai, không DDL

Quản trị viên công ty tạo đối tượng và trường mà không cần nhà vận hành hay migration (YC25, D2).

- R1.1 KHI một phiên bản `dw.object/v1` lên giai đoạn Đang dùng, dịch vụ metadata PHẢI áp đối tượng, trường và
  danh sách chọn của phiên bản đó vào định nghĩa của công ty trong cùng giao dịch, không tạo bảng, cột hay chỉ mục.
- R1.2 KHI người giữ `studio.objects.manage` phát hành một bản nháp `dw.object/v1` hợp lệ, API thành phần PHẢI
  đưa phiên bản đó lên Đang dùng [CAN LAM RO: Q1].
- R1.3 NẾU người gọi không giữ `studio.objects.manage`, THÌ API thành phần PHẢI trả 403 `permission_denied` khi
  tạo, lưu nháp hay phát hành thành phần loại `object` và không ghi gì.
- R1.4 KHI tài liệu tạo đối tượng không nêu mặc định truy cập, dịch vụ metadata PHẢI đặt `default_access` là
  `private`.
- R1.5 KHI hai phiên bản thêm trường lọc được vào cùng một đối tượng đồng thời, dịch vụ metadata PHẢI cấp cho
  mỗi trường một slot khác nhau.
- R1.6 NẾU đối tượng không còn slot trống thuộc họ mà một trường lọc được đòi, THÌ dịch vụ metadata PHẢI từ chối
  phiên bản bằng 422 có con trỏ tới trường và không đổi định nghĩa nào.

### R2 — Trường có tên bất biến, kiểu cố định và loại dữ liệu cá nhân

Mỗi trường mang tên API bất biến, một kiểu của nền tảng và loại dữ liệu cá nhân (YC25, YC84).

- R2.1 Trình kiểm của loại `object` PHẢI chỉ nhận kiểu `text`, `number` (`exact` hoặc `float`), `currency`,
  `date`, `datetime`, `boolean`, `picklist`, `email`, `phone`, `url` cho trường công ty định nghĩa, và trả 422
  cho kiểu khác.
- R2.2 NẾU một trường thiếu `pd_category`, THÌ trình kiểm của loại `object` PHẢI trả 422 `pd_category_required`
  có con trỏ tới trường và không phát hành gì.
- R2.3 NẾU `api_name` của đối tượng hay trường không khớp `^[a-z][a-z0-9_]{1,39}$` (40 ký tự thì nhận, 41 thì
  không), THÌ trình kiểm của loại `object` PHẢI trả 422 có con trỏ tới tên đó.
- R2.4 NẾU một phiên bản đổi `api_name` của đối tượng, hay `api_name` hoặc kiểu của một trường đã phát hành, THÌ
  trình kiểm của loại `object` PHẢI trả 422 và không phát hành gì.

### R3 — Describe và danh mục đối tượng theo người gọi

Người dùng, giao diện, công cụ và bước quy trình biết đúng những trường người gọi được thấy (YC23, YC27).

- R3.1 KHI người giữ `obj.<api_name>.read` gọi `GET /api/v1/studio/objects/{api_name}/describe`, API bản ghi
  PHẢI trả mỗi trường người đó đọc được với `api_name`, nhãn `vi`, kiểu, các cờ bắt buộc, sửa được, lọc được,
  sắp được, và các lựa chọn đang bật.
- R3.2 NẾU một trường Đã ẩn với người gọi, THÌ describe PHẢI không có trường đó.
- R3.3 NẾU `api_name` không phải đối tượng của công ty người gọi, THÌ describe PHẢI trả 404.
- R3.4 NẾU người gọi không giữ `obj.<api_name>.read` trên một đối tượng của công ty mình, THÌ API bản ghi PHẢI
  trả 403 `permission_denied` ở describe và mọi route bản ghi của đối tượng đó trước khi đọc bản ghi nào.
- R3.5 KHI người dùng gọi `GET /api/v1/studio/objects`, API bản ghi PHẢI trả đúng các đối tượng người đó giữ
  `obj.<api_name>.read`.
- R3.6 KHI một công cụ hay bước quy trình xin lược đồ của một đối tượng, bộ chiếu lược đồ PHẢI trả JSON Schema
  2020-12 cho tạo, sửa và truy vấn theo `schema_version`, chỉ gồm trường người gọi đọc được, và với tạo, sửa chỉ
  trường người gọi sửa được.

### R4 — Lưu trữ bản ghi cô lập theo công ty

Bản ghi của một công ty không đọc, ghi hay xuất được từ công ty khác (YC3, YC6, YC17).

- R4.1 Bảng `studio.records` PHẢI từ chối mọi dòng thiếu người phụ trách (`owner_kind`, `owner_id`) hay
  workspace sở hữu.
- R4.2 NẾU một kết nối không đặt `app.tenant_id`, THÌ mọi bảng của spec này PHẢI trả 0 dòng, kể cả khi đọc
  thẳng một partition của `studio.records`.
- R4.3 NẾU người gọi ở công ty B đọc, sửa hay xóa một bản ghi của công ty A, THÌ API bản ghi PHẢI trả 404 và
  không đổi gì.
- R4.4 KHI lane `offboarding` chạy cho một công ty, lane `offboarding` PHẢI xuất mỗi dòng của công ty đó trong các
  bảng của spec này đúng một lần rồi xóa hết các dòng đó.
- R4.5 NẾU một yêu cầu mang header `X-DW-Support-Grant` tới một route bản ghi, THÌ API bản ghi PHẢI trả 403
  `support_context_not_allowed` và không đọc bản ghi nào (ADR-0107 (Proposed) quyết định 8).

### R5 — Ghi bản ghi qua một RecordService

Mọi đường ghi chạy cùng một bộ kiểm, quyền và quyết định trường, và phát cùng sự kiện (YC26, D3).

- R5.1 KHI người giữ `obj.<api_name>.create` gửi `POST /api/v1/studio/objects/{api_name}/records` hợp lệ,
  RecordService PHẢI tạo bản ghi có người phụ trách là người gọi, workspace sở hữu là workspace đang làm việc và
  `version` 1, rồi trả 201 kèm `ETag`.
- R5.2 KHI một bản ghi được tạo, sửa hay xóa mềm, RecordService PHẢI ghi bản ghi, sự kiện outbox
  `studio.record.created`, `.updated` hay `.deleted` có `changed_fields`, và audit cùng tên chỉ mang khóa trường,
  trong một giao dịch.
- R5.3 KHI cùng `create_key` được gửi lại, kể cả đồng thời, RecordService PHẢI trả bản ghi đã tạo và không tạo
  dòng thứ hai.
- R5.4 TRONG KHI lượt chạy ở chế độ `simulate` hay `test`, RecordService PHẢI kiểm đủ và trả bản ghi giả định
  mà không ghi dòng, sự kiện hay audit nào.
- R5.5 KHI người giữ `obj.<api_name>.delete` xóa một bản ghi, RecordService PHẢI đặt `deleted_at`, `deleted_by`
  và giữ dòng.
- R5.6 Mọi đường ghi bản ghi PHẢI đi qua RecordService: không mô-đun nào ngoài adapter bản ghi có SQL nhắc
  `studio.records`.
- R5.7 NẾU bản ghi không tồn tại, thuộc công ty khác hay người gọi không đọc được, THÌ API bản ghi PHẢI trả cùng
  một 404, cùng mã và cùng thông điệp.
- R5.8 NẾU người gọi đọc được bản ghi nhưng không có quyền sửa hay xóa nó, THÌ API bản ghi PHẢI trả 403 và không
  đổi gì.

### R6 — Giá trị ép kiểu và chuẩn hóa một lần, mọi lỗi trả cùng lúc

Một lần lưu nhận mọi lỗi của nó, và giá trị lưu ở một dạng chuẩn (YC23, YC95).

- R6.1 NẾU một lần lưu có lỗi kiểu, bắt buộc, độ dài hay danh sách chọn, THÌ RecordService PHẢI trả 422 với mọi
  lỗi trong `errors[]`, mỗi lỗi một con trỏ `/fields/<api_name>`, và không ghi gì.
- R6.2 RecordService PHẢI lưu chữ ở dạng NFC, email ở chữ thường và số điện thoại ở dạng E.164: "0901 234 567"
  lưu thành "+84901234567".
- R6.3 NẾU số `exact` hay tiền có số chữ số thập phân lớn hơn `scale` của trường, THÌ RecordService PHẢI trả 422
  có con trỏ tới trường: `"1000.5"` vào trường VND `scale` 0 bị từ chối.
- R6.4 KHI đọc giá trị của trường số `exact` hay tiền, API bản ghi PHẢI trả chuỗi có đúng `scale` chữ số thập
  phân: `"0.1"` ở `scale` 2 đọc lại là `"0.10"`.
- R6.5 NẾU body có trường không tồn tại hoặc Đã ẩn với người gọi, THÌ RecordService PHẢI trả cùng một 422, cùng
  mã và cùng thông điệp, và không ghi gì.
- R6.6 NẾU body có trường người gọi đọc được nhưng không sửa được, THÌ RecordService PHẢI trả 403
  `field_not_editable` có con trỏ tới trường và không ghi gì.
- R6.7 NẾU `PATCH` có `owner` hay `workspace_id`, THÌ RecordService PHẢI trả 422 `field_not_writable` và không
  ghi gì.
- R6.8 NẾU `If-Match` của `PATCH` hay `DELETE` khác phiên bản hiện tại, THÌ RecordService PHẢI trả 412
  `precondition_failed` và không đổi `version`.

### R7 — Trường duy nhất và Tạo hoặc cập nhật

Quy trình Tiếp nhận lead kiểm trùng theo số điện thoại rồi email mà không lộ bản ghi trùng (YC95).

- R7.1 NẾU giá trị của một trường duy nhất đã có ở một bản ghi chưa xóa của cùng đối tượng, THÌ RecordService
  PHẢI trả 409 `duplicate_value` có con trỏ tới trường, không nêu giá trị hay bản ghi nào, và không ghi gì.
- R7.2 KHI người gọi gửi `POST /api/v1/studio/objects/{api_name}/records/upsert` theo một trường duy nhất,
  RecordService PHẢI tạo bản ghi và trả 201 `created: true` khi giá trị đã chuẩn hóa chưa có, hoặc sửa bản ghi
  đang có và trả 200 `created: false`.
- R7.3 KHI hai lần Tạo hoặc cập nhật cùng một giá trị đã chuẩn hóa chạy đồng thời, RecordService PHẢI để lại đúng
  một bản ghi: "0901 234 567" và "+84901234567" là một Lead, cùng tên khác số là hai Lead.
- R7.4 NẾU bản ghi trùng tồn tại mà người gọi không sửa được, THÌ Tạo hoặc cập nhật PHẢI trả cùng 409
  `duplicate_value` như R7.1 và không đổi gì.
- R7.5 KHI RecordService trả 409 `duplicate_value`, RecordService PHẢI ghi audit `studio.record.duplicate_refused`
  chỉ gồm đối tượng, khóa trường và người gọi.
- R7.6 NẾU một người gọi nhận 409 `duplicate_value` quá số lần cho phép trên một đối tượng trong một cửa sổ
  [CAN LAM RO: Q3], THÌ API bản ghi PHẢI trả 429 kèm `Retry-After` cho lần ghi kế tiếp và không ghi gì.
- R7.7 NẾU `POST .../records/upsert` thiếu `Idempotency-Key`, THÌ API bản ghi PHẢI trả 422
  `idempotency_key_required` và không ghi gì.

### R8 — Truy vấn bản ghi có chỉ mục dưới RLS

Danh sách lọc và sắp theo trường lọc được, theo thứ tự tiếng Việt, không trùng không sót (YC27, YC23).

- R8.1 KHI người giữ `obj.<api_name>.read` gọi `GET .../records` hay `POST .../records/query`, API bản ghi PHẢI
  trả các bản ghi chưa xóa người đó đọc được theo cây lọc, sắp theo `order_by` rồi `id`, tối đa `limit` (mặc
  định 50; 200 thì nhận, 201 thì 422).
- R8.2 KHI sắp theo `name` hay một trường chữ, API bản ghi PHẢI theo thứ tự tiếng Việt: "An, Ánh, Ân, Bình,
  Đạt", và "Đức" sau "Dũng", trước "Em".
- R8.3 KHI người gọi đi hết các trang bằng `cursor`, API bản ghi PHẢI trả mỗi bản ghi khớp đúng một lần, kể cả
  khi giá trị sắp trùng nhau hay NULL, với NULL ở cuối.
- R8.4 NẾU cây lọc, `order_by` hay `fields` nhắc trường không tồn tại hoặc Đã ẩn với người gọi, THÌ API bản ghi
  PHẢI trả cùng một 422 `field_not_readable` và không chạy truy vấn.
- R8.5 NẾU cây lọc hay `order_by` nhắc trường đọc được mà không lọc được, THÌ API bản ghi PHẢI trả 422
  `field_not_filterable`.
- R8.6 NẾU cây lọc sâu hơn 5 tầng, có hơn 50 lá, một `$in` hơn 500 giá trị hay một chuỗi hơn 1.024 byte (đúng
  bằng các giới hạn đó thì nhận), THÌ API bản ghi PHẢI trả 422 có con trỏ tới nút vượt.
- R8.7 NẾU `cursor` đi kèm cây lọc hay `order_by` khác trang trước, THÌ API bản ghi PHẢI trả 422.
- R8.8 KHI `count=exact`, API bản ghi PHẢI trả số bản ghi khớp tới 10.000, và 10.000 kèm `count_capped: true`
  khi vượt.
- R8.9 Mọi câu lệnh trình biên dịch truy vấn sinh ra PHẢI nêu `tenant_id` và có mọi vị từ và cột sắp mang bởi
  chỉ mục khi chạy bằng `dw_app` dưới RLS.

### R9 — Lưu trữ đo ở quy mô D12

Lưu trữ được chốt bằng số đo ở quy mô D12, không bằng ước đoán (YC20, D12).

- R9.1 Ở quy mô D12 (10 triệu bản ghi một đối tượng, 50 triệu một công ty), API bản ghi PHẢI trả trang đầu 50
  dòng trong p95 ≤ 50 ms và `GET` một bản ghi trong p95 ≤ 5 ms, đo phía máy chủ trên máy tham chiếu, ở mỗi mức
  truy cập của ADR-0104 (Proposed).
- R9.2 ĐỐI VỚI phép đo giữ được planning p95 ≤ 5 ms cho truy vấn ba vị từ với đủ chỉ mục slot và
  `CacheMemoryContext` ≤ 64 MB mỗi backend, migration PHẢI tạo `studio.records` với
  `PARTITION BY HASH (tenant_id)` modulus 8 từ revision đầu.
- R9.3 ĐỐI VỚI phép đo trượt một trong hai ngưỡng đó, migration PHẢI tạo `studio.records` không chia partition,
  giữ cùng khóa tổng hợp có `tenant_id`.
- R9.4 Bảng `studio.records` PHẢI có đúng tập slot ticket 01 chốt, mỗi slot một chỉ mục từng phần
  `(tenant_id, object_id, <slot>, id) WHERE <slot> IS NOT NULL AND deleted_at IS NULL`.

### R10 — Danh sách và biểu mẫu antd sinh từ describe

Người dùng xem, tạo và sửa bản ghi trên màn sinh từ describe, theo quyền của mình (YC27).

- R10.1 KHI người giữ `obj.<api_name>.read` mở `/studio/objects/[api_name]`, trang danh sách PHẢI hiện bản ghi
  người đó đọc được, nạp thêm theo `cursor`, với cột và nhãn tiếng Việt lấy từ describe.
- R10.2 KHI một nhân viên Sales chỉ có quyền đọc Lead ở mức Của tôi mở danh sách Lead, trang danh sách PHẢI chỉ
  hiện lead đang giao cho người đó.
- R10.3 KHI một trường Đã ẩn với người xem, trang bản ghi PHẢI hiện "Đã ẩn" có biểu tượng khóa và không có giá
  trị.
- R10.4 KHI một trường chỉ đọc với người xem, biểu mẫu PHẢI khóa trường đó kèm lý do trong `Tooltip`.
- R10.5 KHI máy chủ trả 422, biểu mẫu PHẢI gắn mỗi lỗi vào trường theo `errors[].pointer`.
- R10.6 KHI máy chủ trả 412, biểu mẫu PHẢI hiện vùng xung đột có cả hai giá trị và giữ nội dung đã gõ.
- R10.7 Ở bề rộng 320 px, trang danh sách và trang bản ghi PHẢI không cuộn ngang và có đúng một `h1`.

## Trong phạm vi

- Bảng `studio.object_defs`, `studio.field_defs`, `studio.picklist_options`, `studio.records` và các partition
  `studio.records_p0` tới `studio.records_p7`; khóa quyền `studio.objects.manage`.
- Loại thành phần `object` (`dw.object/v1`) trong `ArtifactKindRegistry`, với dịch vụ metadata là móc phát hành.
- `RecordService`, bộ chiếu lược đồ `ObjectSchemaProjector`, trình biên dịch truy vấn; route
  `GET /api/v1/studio/objects`, `GET .../{api_name}/describe`, `GET|POST .../records`, `POST .../records/query`,
  `POST .../records/upsert`, `GET|PATCH|DELETE .../records/{record_id}`.
- Sự kiện `studio.record.created|updated|deleted`; audit `studio.object.*`, `studio.field.*`,
  `studio.picklist.updated`, `studio.record.*`, `studio.record.duplicate_refused`.
- Màn `/studio/objects/[api_name]`, chi tiết, tạo và sửa; harness đo `scripts/bench_records_storage.py`.

## Ngoài phạm vi

| Việc                                                                     | Vì sao                                                                   | Chủ                            |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------ | ------------------------------ |
| Tìm tên tiếng Việt không dấu theo tiền tố từ                             | Cần `unaccent`, `name_key`, bảng từ khóa; W1 không có ô tìm              | custom-objects, đợt sau (W2)   |
| Lịch sử thay đổi theo trường                                             | Cần `ensure_time_partitions` tổng quát và hạn lưu (DO-52)                | custom-objects, đợt sau (W2)   |
| Trường tham chiếu, chủ – chi tiết, ràng buộc khi xóa                     | Slot `l`, `m` và FK tổng hợp chưa cần cho Lead, Campaign                 | custom-objects, đợt sau (W2)   |
| Thùng rác và purge lane; nút xóa trên giao diện                          | Bản ghi xóa mềm ở W1 nằm tới purge W2 hay offboarding; chưa có khôi phục | custom-objects, đợt sau (W2)   |
| Mã ngoài, số tự động, batch ≤ 200                                        | W1 chỉ cần trường duy nhất và Tạo hoặc cập nhật                          | custom-objects, đợt sau (W2)   |
| Văn bản dài, chọn nhiều; quy tắc kiểm tra bằng CEL                       | `ExpressionEngine` của workflow-nodes (DO-38); nghĩa quy tắc (DO-37)     | custom-objects, đợt sau (W2)   |
| Nhập, xuất CSV qua tác vụ nền; dạng xem và bộ lọc đã lưu                 | Tác vụ nền của app-standards; ai được xuất dữ liệu cá nhân (DO-61)       | custom-objects, đợt sau (W2)   |
| Tiến hóa lược đồ; trình dựng đối tượng, trường và bố cục                 | Xóa, purge, đổi kiểu trường cần chỉ mục phụ thuộc và lane purge          | custom-objects, đợt sau (W2)   |
| Nguồn gốc và nhãn "AI" cho trường do AI ghi (YC29)                       | Chưa có agent ghi trường ở W1                                            | custom-objects, đợt sau (W2)   |
| Loại bản ghi, công thức và roll-up, tìm toàn văn, XLSX, tenant cá voi    | Chưa có nhu cầu ở lát Marketing                                          | custom-objects, đợt sau (W3)   |
| Hạn mức gói cho số đối tượng và trường                                   | Mặc định gói chưa quyết (DO-59); W1 chặn bằng ngân sách slot (R1.6)      | usage-and-limits, đợt sau (W2) |
| Policy tầm, `access_key`, chia sẻ, giao người phụ trách                  | Quyền trên bản ghi có một chủ (ADR-0105 (Proposed))                      | record-access                  |
| `access_mode`, quyền trường, `resolve_field_access`                      | Quyết định trường có một chủ (ADR-0106 (Proposed))                       | field-security                 |
| Khóa `obj.<api_name>.<action>`, vai và độ sâu                            | Danh mục quyền có một chủ (ADR-0104 (Proposed))                          | tenant-rbac                    |
| Vỏ phiên bản, chỉ mục phụ thuộc, route `/api/v1/studio/artifacts`        | Một vỏ cho mọi loại (ADR-0109 (Proposed))                                | tenant-config                  |
| Bọc giá trị bản ghi khi vào prompt; công cụ dữ liệu đối tượng            | Giá trị bản ghi là đầu vào không tin; chủ là đường công cụ               | tools-and-skills               |
| Tạo bảng, cột, chỉ mục lúc chạy; đối tượng theo workspace; business hook | ADR-0107 (Proposed) bác; hook không có người đăng ký (failure-modes #1)  | không làm                      |
| Đa tiền tệ trên một bản ghi; báo cáo và tổng hợp group-by                | Cần quyết quyết định trường cho số tổng hợp                              | đợt sau (v2)                   |

## Dữ liệu

Mọi bảng mang `tenant_id`, id UUIDv7, RLS ENABLE và FORCE, policy dạng InitPlan
`tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)`, tên ràng buộc theo
`NAMING_CONVENTION`, `created_at`, `created_by`, `updated_at`, `updated_by` (`updated_at` do
`platform.touch_updated_at()` giữ). Bảng định nghĩa không có `workspace_id` (ADR-0107 (Proposed) quyết định 1).

- `studio.object_defs`: PK `(tenant_id, id)`; FK `(tenant_id, id)` tới `studio.artifacts` ON DELETE RESTRICT;
  `api_name` CHECK `^[a-z][a-z0-9_]{1,39}$`, UNIQUE `(tenant_id, api_name)`; `labels` jsonb có khóa `vi` khác
  rỗng; `default_access` NOT NULL DEFAULT `'private'` CHECK `private`, `public_read`, `public_read_write`;
  `schema_version` integer ≥ 1; `next_field_no` integer ≥ 1.
- `studio.field_defs`: PK `(tenant_id, id)`, `id` là mã trường; FK `(tenant_id, object_id)` ON DELETE CASCADE;
  `api_name` như trên, UNIQUE `(tenant_id, object_id, api_name)`; `type` CHECK `text`, `number`, `currency`,
  `date`, `datetime`, `boolean`, `picklist`, `email`, `phone`, `url`, `owner`, `workspace`, `user` (bằng enum
  trong mã); `pd_category` NOT NULL CHECK `none`, `basic`, `sensitive`, cùng `sensitive_type` và
  `subject_identifier` theo `dw_kernel.personal_data`; `required`, `is_unique`, `indexed` boolean NOT NULL;
  `max_length` 1..255; `number_mode` `exact`, `float`; `scale` 0..6; `currency_code` `^[A-Z]{3}$`;
  `storage_kind` `system`, `slot`, `data`; `slot` `^(t|u|i|f|d|z|b)[0-9]{2}$` đúng họ của kiểu (`t`, `u`: chữ,
  email, điện thoại, url, `t` thêm danh sách chọn; `i`: số `exact`, tiền; `f`: số `float`; `d`: ngày; `z`: ngày
  giờ; `b`: đúng sai); `field_no` không dùng lại; UNIQUE `(tenant_id, object_id, slot) WHERE slot IS NOT NULL`
  và `(tenant_id, object_id, field_no)`.
- `studio.picklist_options`: PK `(tenant_id, field_id, key)`; FK tới `studio.field_defs` ON DELETE CASCADE;
  `key` `^[a-z0-9_]{1,40}$`; `labels` có `vi`; `position`; `active` boolean NOT NULL.
- `studio.records`: PK `(tenant_id, id)`; `object_id` FK tới `studio.object_defs` ON DELETE RESTRICT;
  `workspace_id` FK `(tenant_id, workspace_id)` tới `platform.workspaces` ON DELETE RESTRICT; `owner_kind` NOT
  NULL CHECK `user`, `team`; `owner_id` NOT NULL; `name` `COLLATE "vi-VN-x-icu"` NOT NULL, 1..255 ký tự;
  `version` ≥ 1; `create_key` ≤ 255 byte, UNIQUE
  `(tenant_id, object_id, create_key) WHERE create_key IS NOT NULL`; `data` jsonb object ≤ 32.768 byte; slot `t`
  (`COLLATE "vi-VN-x-icu"`) và `u` là text
  `octet_length ≤ 1024`, `i` bigint, `f` float8, `d` date, `z` timestamptz, `b` boolean; UNIQUE
  `(tenant_id, object_id, uNN) WHERE uNN IS NOT NULL AND deleted_at IS NULL`; `deleted_at`, `deleted_by`; chỉ
  mục `(tenant_id, object_id, created_at DESC, id DESC)`, `(tenant_id, object_id, updated_at DESC, id DESC)`,
  `(tenant_id, object_id, name, id)` và chỉ mục từng phần của mỗi slot (R9.4).
- Quyền: `dw_app` có SELECT, INSERT, DELETE trên bốn bảng (DELETE cho offboarding); UPDATE trên định nghĩa trừ
  cột khóa; UPDATE trên `studio.records` chỉ ở `name`, `data`, slot, `version`, `updated_*`, `deleted_*`; không
  quyền nào trên partition; không gì cho `dw_provisioner`, `dw_agent_ro` hay `PUBLIC` (ADR-0105 (Proposed)
  quyết định 1 và 3). `studio.records` và mỗi partition có policy RESTRICTIVE `tenant_isolation_records`;
  policy PERMISSIVE theo tầm do record-access/03 thêm.

## Kiểm soát

| #    | Kiểm soát                                                 | Yêu cầu          | Test âm                                                                                                                                                                |
| ---- | --------------------------------------------------------- | ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CO1  | Cô lập công ty trên mọi bảng của spec, kể cả partition    | R4.2, R4.3       | A đọc, sửa, xóa bản ghi của B → 404; INSERT với `tenant_id` của B → RLS từ chối; đọc thẳng `studio.records_p3` không đặt tenant → 0 dòng                               |
| CO2  | Không DDL lúc chạy                                        | R1.1             | `dw_app` chạy `CREATE TABLE`, `CREATE INDEX` trong `studio` → bị từ chối; phát hành đối tượng 20 trường không đổi số quan hệ của `studio` trong `pg_class`             |
| CO3  | Chỉ người giữ `studio.objects.manage` sửa định nghĩa      | R1.3             | Người thiếu khóa lưu nháp, phát hành `dw.object/v1` → 403, không dòng nào mới trong `studio.artifact_versions`; gỡ kiểm khóa → test đỏ                                 |
| CO4  | Hai trường không chung slot                               | R1.5             | Hai phát hành song song thêm trường lọc được → hai slot khác; gỡ UNIQUE từng phần trên `slot` → test đỏ                                                                |
| CO5  | Trường luôn có loại dữ liệu cá nhân                       | R2.2             | Trường thiếu `pd_category` → 422 `pd_category_required`, không áp gì; CHECK khác danh sách của kernel → test đỏ                                                        |
| CO6  | Tên API và kiểu trường bất biến                           | R2.4             | Phiên bản đổi `api_name` hay kiểu của trường đã phát hành → 422; gỡ bước so với phiên bản đang dùng → test đỏ                                                          |
| CO7  | Trường Đã ẩn không thành cách dò                          | R3.2, R6.5, R8.4 | Lọc, sắp, `fields`, ghi trên trường Đã ẩn và trên trường lạ → cùng mã, cùng thông điệp; describe không có trường Đã ẩn                                                 |
| CO8  | Từ chối ở mức đối tượng đứng trước tồn tại                | R3.4             | Người thiếu `obj.<api_name>.read` gọi describe, GET một id có và một id không có → cùng 403                                                                            |
| CO9  | Bản ghi không đọc được không lộ tồn tại                   | R5.7             | GET, PATCH, DELETE id không đọc được và id không tồn tại → cùng 404, cùng thông điệp                                                                                   |
| CO10 | Một đường ghi                                             | R5.6             | Thêm một mô-đun có SQL nhắc `studio.records` ngoài adapter bản ghi → test kiến trúc đỏ                                                                                 |
| CO11 | Ghi, sự kiện và audit trong một giao dịch                 | R5.2             | Ép lỗi khi chèn outbox → không bản ghi, không audit; tách ghi outbox ra giao dịch khác → test đỏ                                                                       |
| CO12 | Gửi lại không tạo trùng                                   | R5.3             | Hai lần tạo song song cùng `create_key` → một dòng; gỡ UNIQUE `create_key` → test đỏ                                                                                   |
| CO13 | Mô phỏng và Chạy thử không ghi                            | R5.4             | RecordService ở `simulate` và `test` → 0 dòng, 0 outbox, 0 audit; gỡ bước chế độ chạy → test đỏ                                                                        |
| CO14 | Người phụ trách và workspace sở hữu không đổi qua `PATCH` | R6.7             | `PATCH` có `owner` → 422 `field_not_writable`; `dw_app` UPDATE cột `owner_id` → permission denied                                                                      |
| CO15 | Khóa lạc quan                                             | R6.8             | `If-Match` cũ → 412, `version` giữ nguyên; bỏ so phiên bản → test đỏ                                                                                                   |
| CO16 | Trùng không lộ bản ghi                                    | R7.1, R7.4       | Trùng với bản ghi người gọi không đọc được → 409 không id, không giá trị, có audit; trả id → test đỏ                                                                   |
| CO17 | Tạo hoặc cập nhật không đua                               | R7.3             | Hai lần upsert song song cùng số đã chuẩn hóa → một dòng; bỏ UNIQUE của slot `u` → test đỏ                                                                             |
| CO18 | Giới hạn dò trùng theo người                              | R7.6             | Vượt ngưỡng 409 → 429 kèm `Retry-After`; gỡ bộ giới hạn → test đỏ                                                                                                      |
| CO19 | Truy vấn sinh ra luôn có chỉ mục dưới RLS                 | R8.9             | Ma trận toán tử × họ slot × chiều sắp qua harness hình kế hoạch; biên dịch một vị từ qua `data->>` → test đỏ                                                           |
| CO20 | Offboarding xuất đúng một lần                             | R4.4             | Công ty có bản ghi ở hai workspace → số dòng xuất bằng số dòng tạo, sau purge 0; cấp SELECT trên một partition cho `dw_app` → đếm đôi, test đỏ                         |
| CO21 | Policy tenant là RESTRICTIVE                              | R4.2             | Thêm policy PERMISSIVE `USING (true)` lên `studio.records` → test catalog đỏ                                                                                           |
| CO22 | Ngữ cảnh hỗ trợ không tới route bản ghi                   | R4.5             | Yêu cầu có header `X-DW-Support-Grant` hợp lệ gọi `GET .../records/{record_id}` → 403 `support_context_not_allowed`; thêm route vào `SUPPORT_ALLOWED_ROUTES` → test đỏ |

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát, ghi ở Comments của ticket.
- `make ci` và `make test-integration` xanh; `make test-web` xanh cho ticket 05; số đo R9.1 ghi ở Comments của
  ticket 01 và 04.
- `reviewing-feature-security` và `reviewing-deployment-security` đã chạy cho ticket 02 tới 05.

## Phụ thuộc

- Gói và seam: `dw_studio.records`, `build_studio`, nhóm route `/api/v1/studio` (studio-skeleton/02); schema
  `studio` và test thứ tự offboarding (studio-skeleton/01); mục điều hướng và allowlist antd (studio-skeleton/03).
- Vỏ phiên bản, `ArtifactKindRegistry`, dịch vụ phát hành, `studio.dependencies` (tenant-config/02,
  ADR-0109 (Proposed)); `RunMode` trên lượt chạy (tenant-config/03, ADR-0111 (Proposed)).
- `uq_workspaces_tenant_id_id` (org-and-principals/01); `dw_kernel.personal_data` (compliance-pdpl/01,
  ADR-0106 (Proposed)).
- Khóa `obj.<api_name>.<action>` sinh từ định nghĩa của spec này (tenant-rbac/04); policy PERMISSIVE, cột tầm,
  `studio.assign_record` (record-access/03 và 05); `resolve_field_access`, `access_mode` (field-security/01).
- `Idempotency-Key` gắn người gọi (app-standards/02); ETag, `If-Match`, con trỏ keyset có kiểu, cây lọc JSON,
  harness hình kế hoạch (app-standards/03); problem+json (app-standards/01).
- Bên dùng khai Protocol, gốc ghép đáp bằng `RecordService`: `RecordsPort` (workflow-nodes/04),
  `ObjectDataPort` và bộ chiếu lược đồ (tools-and-skills/03); gieo Lead, Campaign qua API công khai
  (marketing-pilot/02).
- Kiểm lại khi: một trong ADR-0104 (Proposed), ADR-0105 (Proposed), ADR-0106 (Proposed), ADR-0108 (Proposed),
  ADR-0109 (Proposed), ADR-0120 (Proposed) đổi hình hợp đồng → ticket 02 tới 05; số đo ticket 01 hay DO-15 đổi
  partition → R9.2, R9.3, ticket 02; trả lời Q1 → R1.2, ticket 02; trả lời Q3 → R7, ticket 03.

## Câu hỏi còn mở

- Q1. Thay đổi định nghĩa đối tượng (tạo, thêm trường, sửa nhãn, đổi `default_access`) có là thay đổi cần người
  thứ hai của D11, tức phiên bản `dw.object/v1` đi qua `awaiting_approval` của ADR-0120 (Proposed) với một loại
  duyệt riêng và không có cổng đánh giá, hay lên Đang dùng khi người giữ `studio.objects.manage` phát hành?
  Chủ: người đặt yêu cầu (nghĩa của D11) và Đạt. Chặn: R1.2, ticket 02.
- Q2. DO-15: chia `studio.records` 8 partition băm theo `tenant_id` từ revision đầu và ở PostgreSQL 16 trong v1,
  theo số đo ticket 01? Chủ: Đạt. Chặn: R9.2, R9.3, ticket 02.
- Q3. DO-35: trường duy nhất toàn đối tượng với 409 không lộ bản ghi trùng, cách dò tồn tại là rủi ro còn lại có
  audit; ngưỡng và cửa sổ của giới hạn theo người là bao nhiêu? Chủ: Đạt và người đặt yêu cầu. Chặn: R7.6,
  ticket 03.
- Q4. DO-16: bản ghi dưới `/api/v1/studio/...`, problem+json toàn nền tảng, phương thức riêng viết
  `/records/batch-create`, báo ngừng ít nhất 6 tháng? Chủ: Đạt. Chặn: ticket 04, 05.
- Q5. DO-01: chấp nhận Studio là năng lực nền tảng với bảng định nghĩa toàn công ty không thu hẹp theo
  `workspace_id`, sửa CLAUDE.md theo ADR khi chấp nhận? Chủ: Đạt. Chặn: ticket 02 qua studio-skeleton/01.
- Q6. DO-03: được port `si_metadata/values.py` của si-platform theo điều khoản nào? Chủ: Đạt cùng PO và SA của
  si-platform. Không đổi: hành vi của R6.2 tới R6.4; không được port thì viết lại theo cùng bộ test vector.
- Q7. DO-52: hạn của thùng rác và lịch sử thay đổi? Chủ: luật sư và Đạt. Không đổi: W1 không xóa vĩnh viễn bản
  ghi nào ngoài offboarding; hạn chỉ đặt cho purge lane của W2.
- Q8. DO-09: vai của công ty thành dữ liệu? Chủ: Đạt. Không đổi: khóa quyền và nơi kiểm của spec này; chỉ đổi
  cách vai nhận khóa.

## Quyết định

- 22/10/2026 (người đặt yêu cầu): D1 workspace sở hữu dữ liệu, bản ghi có người phụ trách và workspace sở hữu;
  D2 người dựng là quản trị viên không viết mã; D3 quyết định trường áp cả cho agent; D4 Marketing là lát đầu; D5
  si-platform là nguồn tham khảo và port chọn lọc. Sửa: R1, R4.1, R5, R6.2.
- 23/10/2026 (người đặt yêu cầu): D11 mọi thay đổi cấu hình cần người đề xuất và người duyệt khác nhau; D12 10
  triệu bản ghi một đối tượng, 50 triệu một công ty, 5.000 người dùng, 200 workspace, cây sâu 6, partition băm
  theo công ty từ revision đầu. Hỏi: Q1. Sửa: R9, ticket 01.
- 23/10/2026 (agent, tạm): theo khuyến nghị (a) của DO-08, `api_name` bất biến từ lần phát hành đầu. Sửa: R2.4.
  Nếu sai thì: đổi tên được, nhưng thành thành phần mới cộng di chuyển dữ liệu.
- 23/10/2026 (agent, tạm): theo khuyến nghị (a) của DO-26, chế độ `test` chặn ghi bản ghi như `simulate` ở W1.
  Sửa: R5.4. Nếu sai thì: ticket 03 ghi vào vùng nháp theo lượt chạy (FOG-60).
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: brief B5 nói khóa `studio.setup.objects`, brief B3 và tenant-rbac/01
  nói `studio.objects.manage` theo dạng `studio.<area>.<verb>`; theo tenant-rbac.
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: B5-E bỏ phiên bản nháp và phát hành cho đối tượng,
  ADR-0109 (Proposed) và roadmap đặt `object` là một loại trong `ArtifactKindRegistry`; theo ADR-0109 (Proposed).
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: ADR-0107 (Proposed) nói slot `u` từ P2, roadmap đưa trường duy nhất
  và Tạo hoặc cập nhật vào ticket 03 của W1 cho YC95; theo roadmap.
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: tóm tắt roadmap của ticket 05 nói trường ẩn vắng,
  ADR-0106 (Proposed) quyết định 4 nói giao diện hiện "Đã ẩn" có khóa, không để trống; theo ADR-0106 (Proposed).
- 23/10/2026 (agent, tạm): ticket 02 tạo `owner_kind`, `owner_id`, `workspace_id`; cột tầm `access_key`,
  `read_grants`, `edit_grants`, `grants_valid_until` (ADR-0105 (Proposed) quyết định 2 và 3) vào cùng policy đọc
  chúng ở record-access. Nếu sai thì: ticket 02 tạo luôn bốn cột đó.
- 23/10/2026 (agent, tạm): khi tạo, người phụ trách là người gọi và workspace sở hữu là workspace đang làm việc,
  theo thiết kế B4 của record-access; policy chèn của ADR-0105 (Proposed) vẫn đòi cả hai trong tầm tạo. Sửa: R5.1.
  Nếu sai thì: body tạo nhận `owner` và `workspace_id`.
- 23/10/2026 (agent, tạm): sự kiện `studio.record.*` v1 mang khóa trường, không mang giá trị; `prior` của brief B5
  đợi bước kích hoạt theo sự kiện bản ghi ở W2. Sửa: R5.2. Nếu sai thì: thêm `prior` và đưa outbox vào bảng
  dispatch yêu cầu chủ thể dữ liệu của ADR-0106 (Proposed).
- 23/10/2026 (agent, tạm): `name_key`, `studio.search_key` và `unaccent` ra cùng tìm không dấu ở W2 vì W1 không
  có người đọc (failure-modes #1); ticket 01 vẫn đo `unaccent`. Nếu sai thì: ticket 02 thêm cột sinh `name_key`.
- 23/10/2026 (agent, tạm): máy tham chiếu của YC20 là host chính sau D14 (ít nhất 4 vCPU, 16 GB) với
  `postgres:16-alpine`; cấu hình thật ghi ở Comments ticket 01. Sửa: R9.1. Nếu sai thì: đo lại trên máy Đạt chỉ
  định.
- 23/10/2026 (agent, tạm): cây lọc W1 nhận `$and`, `$or` và lá `$eq`, `$in`, `$lt`, `$lte`, `$gt`, `$gte`;
  `$not` và `$ne` trả 422 vì chỉ mục btree không mang được (ADR-0108 (Proposed) quyết định 2). Sửa: R8.9. Nếu sai
  thì: thêm hai toán tử khi có dạng mang bởi chỉ mục.

## Danh sách ticket

| #   | Ticket                                                                                                                           |
| --- | -------------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Đo nền lưu trữ bản ghi trước khi chốt ADR (partition, ngân sách slot, unaccent, InitPlan)](issues/01-do-nen-luu-tru-ban-ghi.md) |
| 02  | [Định nghĩa object và trường, bảng bản ghi, describe và chiếu JSON Schema](issues/02-luoc-do-dinh-nghia-object.md)               |
| 03  | [RecordService: tạo, đọc, sửa, xóa mềm, trường duy nhất và upsert](issues/03-record-service.md)                                  |
| 04  | [Truy vấn bản ghi: cây lọc, sắp keyset có kiểu, đếm có trần](issues/04-truy-van-ban-ghi.md)                                      |
| 05  | [Danh sách và biểu mẫu antd sinh từ describe](issues/05-danh-sach-va-bieu-mau-antd.md)                                           |
