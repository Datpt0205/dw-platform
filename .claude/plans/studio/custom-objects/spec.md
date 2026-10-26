# Đối tượng tùy biến: định nghĩa, một dịch vụ bản ghi, API và giao diện sinh từ metadata

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Công ty tự định nghĩa đối tượng và trường của mình (Lead và Campaign của Marketing trước tiên, D4) mà không
cần nhà vận hành hay migration: định nghĩa là dữ liệu trên các bảng cố định do migration tạo, và mọi đường
đọc ghi bản ghi (route, bước quy trình, công cụ agent, lane) đi qua một `RecordService` (ADR-0107 (Accepted)),
theo quy ước API của ADR-0108 (Accepted). W1 làm Lead và Campaign thành đối tượng của công ty, một
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
  Ràng buộc: `dw_app` không có quyền trên partition thì mỗi bản ghi xuất một lần qua bảng cha; danh sách viết tay đó bỏ ở
  foundations-hardening/07, nên mỗi bảng mới có một bước trong sổ bước xóa ở composition root của worker, thứ tự suy từ
  khóa ngoại RESTRICT và NO ACTION của `pg_constraint` (foundations-hardening:R11.4, foundations-hardening:R11.5; H-2).
- Con trỏ trang chỉ mang `datetime` (`packages/python/dw_kernel/src/dw_kernel/pagination.py:108-118`), trang tối
  đa 200 (`packages/python/dw_kernel/src/dw_kernel/pagination.py:47-48`). Thiếu: con trỏ có kiểu của
  app-standards/03.
- Vỏ lỗi là `ErrorResponse{code, message, details, request_id}` (`apps/api/src/dw_api/errors.py:28-34`), mã
  `permission_denied` đã có (`packages/python/dw_kernel/src/dw_kernel/errors.py:20`). Ràng buộc: lỗi theo
  problem+json của ADR-0108 (Accepted), giữ mã hiện có.
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
- R1.2 KHI người giữ `studio.objects.manage` Gửi kiểm định một bản nháp `dw.object/v1` hợp lệ qua
  `POST /api/v1/studio/objects/{artifact_id}/versions/{version_id}/submit` mà bộ so sánh của loại `object` không báo
  chỉ siết, lệnh Gửi kiểm định PHẢI đưa phiên bản sang Chờ duyệt với một phê duyệt `studio.publish.object`, không qua
  Cổng chất lượng, để phiên bản chỉ lên Đang dùng khi một người thứ hai duyệt theo ADR-0120 (Accepted) mục 2.
- R1.3 NẾU người gọi không giữ `studio.objects.manage`, THÌ API Studio PHẢI trả 403 `permission_denied` khi tạo,
  lưu nháp hay Gửi kiểm định thành phần loại `object` và không ghi gì.
- R1.4 KHI tài liệu tạo đối tượng không nêu mặc định truy cập, dịch vụ metadata PHẢI đặt `default_access` là
  `private`.
- R1.5 KHI hai phiên bản thêm trường lọc được vào cùng một đối tượng đồng thời, dịch vụ metadata PHẢI cấp cho
  mỗi trường một slot khác nhau.
- R1.6 NẾU đối tượng không còn slot trống thuộc họ mà một trường lọc được đòi, THÌ dịch vụ metadata PHẢI từ chối
  phiên bản bằng 422 có con trỏ tới trường và không đổi định nghĩa nào.
- R1.7 TRONG KHI nền tảng không Đóng băng, KHI người giữ `studio.objects.manage` Gửi kiểm định một bản nháp
  `dw.object/v1` mà bộ so sánh của loại `object` báo chỉ siết, kể cả lúc công ty đang Đóng băng, lệnh Gửi kiểm định
  PHẢI đưa phiên bản từ Nháp lên Đang dùng trong giao dịch của người gửi, không mở phê duyệt, với đúng một audit
  `studio.version.published` có người gửi là actor và `details.path` `tighten_only` do agent-lifecycle ghi
  (`agent-lifecycle:R2.9`).
- R1.8 Bộ so sánh của loại `object` PHẢI báo một phiên bản là chỉ siết khi và chỉ khi đối tượng đã có phiên bản Đang
  dùng và mọi khác biệt với phiên bản đó là một trường từ `open` sang `secured` hay `default_access` hẹp hơn theo thứ tự
  `public_read_write`, `public_read`, `private`.

### R2 — Trường có tên bất biến, kiểu cố định và loại dữ liệu cá nhân

Mỗi trường mang tên API bất biến, một kiểu của nền tảng và loại dữ liệu cá nhân, và đối tượng cùng mỗi trường có thể
mang một Mô tả cho AI (YC25, YC84, YC101).

- R2.1 Trình kiểm của loại `object` PHẢI chỉ nhận kiểu `text`, `number` (`exact` hoặc `float`), `currency`,
  `date`, `datetime`, `boolean`, `picklist`, `email`, `phone`, `url` cho trường công ty định nghĩa, và trả 422
  cho kiểu khác.
- R2.2 NẾU một trường thiếu `pd_category`, THÌ trình kiểm của loại `object` PHẢI trả 422 `validation_failed` với
  `errors[].code` `pd_category_required` (compliance-pdpl:R1.1) có con trỏ tới trường (app-standards:R1.3) và không phát hành gì.
- R2.3 NẾU `api_name` của đối tượng hay trường không khớp `^[a-z][a-z0-9_]{1,39}$` (40 ký tự thì nhận, 41 thì
  không), THÌ trình kiểm của loại `object` PHẢI trả 422 có con trỏ tới tên đó.
- R2.4 NẾU một phiên bản đổi `api_name` của đối tượng, hay `api_name` hoặc kiểu của một trường đã phát hành, THÌ
  trình kiểm của loại `object` PHẢI trả 422 và không phát hành gì.
- R2.5 NẾU một phiên bản đặt `access_mode` là `open` cho một trường có `pd_category` là `sensitive`, hay cho một trường
  mới có `pd_category` khác `none`, THÌ trình kiểm của loại `object` PHẢI trả 422 có con trỏ tới trường và không phát
  hành gì.
- R2.6 NẾU `ai_description` của đối tượng hay của một trường dài hơn 500 ký tự tính trên chuỗi NFC (500 thì nhận, 501
  thì 422; bỏ trống thì nhận), THÌ trình kiểm của loại `object` PHẢI trả 422 có con trỏ tới chỗ đó và không phát hành
  gì.

### R3 — Describe và danh mục đối tượng theo người gọi

Người dùng, giao diện, công cụ và bước quy trình biết đúng những trường người gọi được thấy (YC23, YC27).

- R3.1 KHI người giữ `obj.<api_name>.read` gọi `GET /api/v1/studio/objects/{api_name}/describe`, API bản ghi
  PHẢI trả `ai_description` của đối tượng và mỗi trường người đó đọc được với `api_name`, nhãn `vi`, `ai_description`,
  kiểu, `access` (`read` hay `edit`), các cờ bắt buộc, sửa được, lọc được, sắp được, và các lựa chọn đang bật.
- R3.2 KHI một trường Đã ẩn với người gọi, describe PHẢI trả trường đó chỉ với `api_name`, nhãn `vi` và `access` là
  `hidden`.
- R3.3 NẾU `api_name` không phải đối tượng của công ty người gọi, THÌ describe PHẢI trả 404.
- R3.4 NẾU người gọi không giữ `obj.<api_name>.read` trên một đối tượng của công ty mình, THÌ API bản ghi PHẢI
  trả 403 `permission_denied` ở describe và mọi route bản ghi của đối tượng đó trước khi đọc bản ghi nào.
- R3.5 KHI người dùng gọi `GET /api/v1/studio/objects`, API bản ghi PHẢI trả đúng các đối tượng người đó giữ
  `obj.<api_name>.read`.
- R3.6 KHI một công cụ hay bước quy trình xin lược đồ của một đối tượng, bộ chiếu lược đồ PHẢI trả JSON Schema
  2020-12 cho tạo, sửa và truy vấn theo `schema_version`, chỉ gồm trường người gọi đọc được, và với tạo, sửa chỉ
  trường người gọi sửa được.
- R3.7 KHI một công cụ hay bước quy trình xin lược đồ của một đối tượng, bộ chiếu lược đồ PHẢI trả `ai_description` của
  đối tượng và của mỗi trường người gọi đọc được tách khỏi JSON Schema, không đặt vào `title`, `description` hay nhãn
  của lược đồ, để bên dùng bao nó là dữ liệu từ bên ngoài (YC48, YC101).

### R4 — Lưu trữ bản ghi cô lập theo công ty

Bản ghi của một công ty không đọc, ghi hay xuất được từ công ty khác (YC3, YC6, YC17).

- R4.1 Bảng `studio.records` PHẢI từ chối mọi dòng thiếu người phụ trách (`owner_kind`, `owner_id`) hay
  workspace sở hữu.
- R4.2 NẾU một kết nối có quyền đọc mà không đặt `app.tenant_id`, THÌ mọi bảng của spec này, kể cả từng partition
  của `studio.records`, PHẢI trả 0 dòng.
- R4.3 NẾU người gọi ở công ty B đọc, sửa hay xóa một bản ghi của công ty A, THÌ API bản ghi PHẢI trả 404 và
  không đổi gì.
- R4.4 KHI lane `offboarding` chạy cho một công ty, lane `offboarding` PHẢI xuất mỗi dòng của công ty đó trong các
  bảng của spec này đúng một lần rồi xóa hết các dòng đó.
- R4.5 NẾU một yêu cầu mang header `X-DW-Support-Grant` tới một route bản ghi, THÌ API bản ghi PHẢI trả 403
  `support_context_not_allowed` và không đọc bản ghi nào (ADR-0107 (Accepted) quyết định 8).
- R4.6 NẾU một lần ghi của công ty A vào bảng của spec này, hay vào cột `to_field_id` của `studio.dependencies`, trỏ qua
  khóa ngoại tới thành phần, định nghĩa, trường hay workspace của công ty B, THÌ PostgreSQL PHẢI từ chối lần ghi đó và
  không ghi dòng nào.

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
- R5.9 KHI một Bước quy trình sửa một bản ghi qua `RecordsPort` bằng lệnh `update`, hay bằng lệnh `upsert` khớp một bản
  ghi có sẵn, với khóa `wf:{run_id}:{node_id}:{iteration_path}` mà wrapper nút dẫn (workflow-nodes:R5.1), RecordService
  PHẢI ghi khóa đó cùng kết quả của lần sửa (id bản ghi, `version` sau lần sửa, `created`) trong cùng giao dịch với bản
  ghi, sự kiện outbox và audit (mức bảo đảm nội bộ của YC41; V4.30).
- R5.10 KHI RecordService nhận lại một khóa `wf:` đã ghi theo R5.9 từ cùng chủ thể chạy, RecordService PHẢI trả kết quả
  đã lưu của lần đầu, đánh dấu `replayed: true`, trước khi ép kiểu hay áp đầu vào mới, và không ghi bản ghi, sự kiện hay
  audit nào; lệnh `create` của Bước đã có hành vi này qua `create_key` (R5.3).
- R5.11 NẾU một khóa `wf:` đã ghi theo R5.9 đến từ một chủ thể khác chủ thể đã dùng nó, THÌ RecordService PHẢI trả 409
  `idempotency_conflict` và không ghi gì (ADR-0108 (Accepted) quyết 4).

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
- R6.5 NẾU body có trường không tồn tại trên đối tượng, THÌ RecordService PHẢI trả 422 `validation_failed` với
  `errors[].code` `unknown_field` có con trỏ tới trường và không ghi gì.
- R6.6 NẾU body có trường người gọi không sửa được (Đã ẩn hay chỉ đọc), THÌ RecordService PHẢI trả 403
  `field_not_editable` có con trỏ tới trường và không ghi gì.
- R6.7 NẾU `PATCH` có `owner` hay `workspace_id`, THÌ RecordService PHẢI trả 422 `validation_failed` với
  `errors[].code` `field_not_writable` có con trỏ tới thuộc tính đó và không ghi gì.
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
- R7.6 NẾU một người gọi đã nhận 20 lần 409 `duplicate_value` trên một đối tượng trong 10 phút trượt gần nhất (theo
  công ty, người gọi và đối tượng; lần thứ 20 vẫn là 409), THÌ API bản ghi PHẢI trả 429 kèm `Retry-After` cho mọi lần
  ghi kế tiếp của người đó lên đối tượng đó, trùng hay không, tới khi cửa sổ còn dưới 20 lần, và không ghi gì.
- R7.7 NẾU `POST .../records/upsert` thiếu `Idempotency-Key`, THÌ API bản ghi PHẢI trả 422 với
  `details.reason_code` `idempotency_key_required` (app-standards:R2.6) và không ghi gì.
- R7.8 KHI API bản ghi trả 429 vì giới hạn dò trùng, API bản ghi PHẢI ghi đúng một audit
  `studio.record.duplicate_throttled` chỉ gồm đối tượng và người gọi.

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
  PHẢI trả 422 `validation_failed` với `errors[].code` `field_not_readable` trỏ vào nút đó và không chạy truy vấn.
- R8.5 NẾU cây lọc hay `order_by` nhắc trường đọc được mà không lọc được, THÌ API bản ghi PHẢI trả 422
  `validation_failed` với `errors[].code` `field_not_filterable` trỏ vào nút đó.
- R8.6 NẾU cây lọc sâu hơn 5 tầng, có hơn 50 lá, một `$in` hơn 500 giá trị hay một chuỗi hơn 1.024 byte (đúng
  bằng các giới hạn đó thì nhận), THÌ API bản ghi PHẢI trả 422 có con trỏ tới nút vượt.
- R8.7 NẾU `cursor` đi kèm cây lọc hay `order_by` khác trang trước, THÌ API bản ghi PHẢI trả 422.
- R8.8 KHI `count=exact`, API bản ghi PHẢI trả số bản ghi khớp tới 10.000, và 10.000 kèm `count_capped: true`
  khi vượt.
- R8.9 Mọi câu lệnh trình biên dịch truy vấn sinh ra PHẢI nêu `tenant_id` và có mọi vị từ và cột sắp mang bởi
  chỉ mục khi chạy bằng `dw_app` dưới RLS.

### R9 — Lưu trữ đo ở quy mô D12

Lưu trữ được chốt bằng số đo ở quy mô D12, không bằng ước đoán (YC20, D12). Mọi số đo đến từ một harness và một seed
mà ticket 01 là chủ duy nhất và record-access/01 dùng lại (V4.32; ADR-0107 (Accepted) quyết 2), trên DDL W1 cộng phần
W2 đã biết, dưới tải hỗn hợp của ticket 01 (50 phiên; 80% đọc ở mọi hồ sơ quyền, 15% sửa một trường, 5% tạo; soak 2
giờ ở 200 lần ghi mỗi giây; một lần chạy nguội), mỗi p95 trên ít nhất 1.000 mẫu cả nóng lẫn nguội, mỗi khẳng định
"dùng chỉ mục" kèm `EXPLAIN (ANALYZE, BUFFERS)`.

- R9.1 Ở quy mô D12 (10 triệu bản ghi một đối tượng, 50 triệu một công ty), API bản ghi PHẢI trả trang đầu 50
  dòng trong p95 ≤ 50 ms và `GET` một bản ghi trong p95 ≤ 5 ms, đo phía máy chủ trên máy tham chiếu mà YC20 định
  nghĩa (host chính sau D14), ở mỗi mức truy cập của ADR-0104 (Accepted).
- R9.2 ĐỐI VỚI phép đo mà biến thể A1 của ticket 01 (DDL W1 cộng phần W2 đã biết và policy sáu nhánh) ở modulus 8
  đạt mọi ngưỡng có số của R9, giữ planning p95 ≤ 5 ms cho truy vấn ba vị từ, `CacheMemoryContext` ≤ 64 MB mỗi backend,
  và cho một lợi ích bảo trì đo được so với modulus 4, migration PHẢI tạo `studio.records` với
  `PARTITION BY HASH (tenant_id)` modulus 8 từ revision đầu.
- R9.3 [Bỏ] 23/10/2026: nhánh không chia partition trái D12 (phân vùng băm từ revision đầu); đường lui là modulus 4
  (R9.5, DO-15).
- R9.4 Bảng `studio.records` PHẢI có đúng tập slot ticket 01 chốt, mỗi slot một chỉ mục từng phần
  `(tenant_id, object_id, <slot>, id) WHERE <slot> IS NOT NULL AND deleted_at IS NULL`.
- R9.5 ĐỐI VỚI phép đo mà A1 ở modulus 8 không đạt điều kiện của R9.2 trong khi A1 ở modulus 4 đạt mọi ngưỡng đọc của
  R9, migration PHẢI tạo `studio.records` với `PARTITION BY HASH (tenant_id)` modulus 4 (`studio.records_p0` tới
  `studio.records_p3`) từ revision đầu.

Đường ghi và bảo trì, đo trên A1 dưới tải của ticket 01; mỗi dòng là một tiêu chí, và một dòng trượt kích hoạt luật quyết
của ticket 01 (A2, A3, giảm số slot mỗi họ, `wal_compression`, rồi mới xét pivot cho trường tràn):

| Mã    | Chỉ số đo                                                                                                            | Ngưỡng          |
| ----- | -------------------------------------------------------------------------------------------------------------------- | --------------- |
| R9.6  | WAL bền vững trong soak 2 giờ ở 200 lần ghi mỗi giây, tính cả bản ghi, outbox, audit và khóa `wf:` của R5.9          | ≤ 20 MB/s       |
| R9.7  | Một vòng autovacuum trên partition của tenant T1 trong soak, với số dead tuple không tăng dần qua các vòng           | < 30 phút       |
| R9.8  | q-error p95 của lọc ba vị từ trên slot dùng chung, và không truy vấn nào chậm hơn 10 lần kế hoạch tốt nhất của nó    | ≤ 10            |
| R9.9  | p95 trang đầu và `GET` của tenant T2 khi T1 đang nhập, vacuum hay tổng hợp                                           | ngưỡng của R9.1 |
| R9.10 | Nhập 10^6 bản ghi qua RecordService                                                                                  | ≥ 1.000 hàng/s  |
| R9.11 | Promote một trường từ `data` sang slot hay purge một trường trên 10^7 hàng, với p95 nền ≤ 1,5 lần bình thường        | ≤ 2 giờ mỗi lần |
| R9.12 | Tạo bản ghi con của một Campaign có 10^5 con khi 32 người ghi đồng thời (DDL W2 của A1), không lần chờ khóa > 100 ms | p95 ≤ 10 ms     |

### R10 — Danh sách và biểu mẫu antd sinh từ describe

Người dùng xem, tạo và sửa bản ghi trên màn sinh từ describe, theo quyền của mình (YC27).

- R10.1 KHI người giữ `obj.<api_name>.read` mở `/studio/objects/[api_name]`, trang danh sách PHẢI hiện bản ghi
  người đó đọc được, nạp thêm theo `cursor`, với cột và nhãn tiếng Việt lấy từ describe.
- R10.2 KHI một nhân viên Sales chỉ có quyền đọc Lead ở mức Của tôi mở danh sách Lead, trang danh sách PHẢI chỉ
  hiện lead đang giao cho người đó.
- R10.3 KHI một trường Đã ẩn với người xem, trang danh sách và trang bản ghi PHẢI hiện "Đã ẩn" có biểu tượng khóa và
  không có giá trị, kể cả khi trường đó trống.
- R10.4 KHI một trường chỉ đọc với người xem, biểu mẫu PHẢI khóa trường đó kèm lý do trong `Tooltip`.
- R10.5 KHI máy chủ trả 422, biểu mẫu PHẢI gắn mỗi lỗi vào trường theo `errors[].pointer`.
- R10.6 KHI máy chủ trả 412, biểu mẫu PHẢI hiện vùng xung đột có cả hai giá trị và giữ nội dung đã gõ.
- R10.7 Ở bề rộng 320 px, trang danh sách và trang bản ghi PHẢI không cuộn ngang và có đúng một `h1`.

## Trong phạm vi

- Bảng `studio.object_defs`, `studio.field_defs`, `studio.picklist_options`, `studio.records` và các partition
  `studio.records_p0` tới `studio.records_p7` (tới `p3` khi R9.5 chọn modulus 4); cột `to_field_id` của
  `studio.dependencies` cùng FK ghép và index của nó; khóa quyền `studio.objects.manage`.
- Loại thành phần `object` (`dw.object/v1`) trong `ArtifactKindRegistry` và dòng `object` của `studio.artifact_kinds`
  (không có Cổng chất lượng): mục đăng ký nêu `studio.objects.manage` là khóa đọc, khóa ghi và khóa gửi của loại,
  bộ so sánh chỉ siết (R1.8) và dịch vụ metadata là móc phát hành, chỉ áp định nghĩa và không ghi
  `studio.version.published`, mà agent-lifecycle là người ghi duy nhất ở cả hai nhánh; tài liệu mang `default_access`,
  `ai_description` của đối tượng và `access_mode`, `ai_description` của mỗi trường; loại phê duyệt
  `studio.publish.object` cho phát hành nới (R1.2), phát hành chỉ siết một người (R1.7).
- `RecordService`, bộ chiếu lược đồ `ObjectSchemaProjector`, trình biên dịch truy vấn; route
  `GET /api/v1/studio/objects`, `GET .../{api_name}/describe`, `GET|POST .../records`, `POST .../records/query`,
  `POST .../records/upsert`, `GET|PATCH|DELETE .../records/{record_id}`.
- Sự kiện `studio.record.created|updated|deleted`; audit `studio.object.created`, `studio.object.updated`,
  `studio.field.created`, `studio.field.updated`, `studio.picklist.updated`, `studio.record.created`,
  `studio.record.updated`, `studio.record.deleted`, `studio.record.duplicate_refused`,
  `studio.record.duplicate_throttled`.
- Bảng `studio.record_write_keys`: khóa `wf:` của mỗi lệnh sửa bản ghi do một Bước quy trình gửi (R5.9 tới R5.11), mà
  lần giao của record-access/05 cũng ghi vào (record-access:R8.11), cùng mảnh lưu giữ của nó.
- Màn `/studio/objects/[api_name]`, chi tiết, tạo và sửa; harness đo `scripts/bench_records_storage.py` cùng seed có
  hạt giống, là chủ duy nhất của phép đo lưu trữ mà record-access/01 dùng lại (V4.32).

## Ngoài phạm vi

| Việc                                                                                                                  | Vì sao                                                                                                                                                                                                                                    | Chủ                                                 |
| --------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| Tìm tên tiếng Việt không dấu theo tiền tố từ                                                                          | Cần `unaccent`, `name_key`, bảng từ khóa; W1 không có ô tìm                                                                                                                                                                               | custom-objects, đợt sau (W2)                        |
| Lịch sử thay đổi theo trường                                                                                          | Cần `ensure_time_partitions` tổng quát và hạn lưu (DO-52)                                                                                                                                                                                 | custom-objects, đợt sau (W2)                        |
| Trường tham chiếu, chủ – chi tiết, ràng buộc khi xóa                                                                  | Slot `l`, `m` và FK tổng hợp chưa cần cho Lead, Campaign                                                                                                                                                                                  | custom-objects, đợt sau (W2)                        |
| Thùng rác và purge lane; nút xóa trên giao diện                                                                       | Bản ghi xóa mềm ở W1 nằm tới purge W2 hay offboarding; chưa có khôi phục                                                                                                                                                                  | custom-objects, đợt sau (W2)                        |
| Mã ngoài, số tự động, batch ≤ 200                                                                                     | W1 chỉ cần trường duy nhất và Tạo hoặc cập nhật                                                                                                                                                                                           | custom-objects, đợt sau (W2)                        |
| Văn bản dài, chọn nhiều; quy tắc kiểm tra bằng CEL                                                                    | `ExpressionEngine` của workflow-nodes (DO-38); Điều kiện để lưu được nghĩa "phải đúng", vector port từ si-platform, cùng YC28 (DO-37)                                                                                                     | custom-objects, đợt sau (W2)                        |
| Nhập, xuất CSV qua tác vụ nền; dạng xem và bộ lọc đã lưu                                                              | Tác vụ nền của app-standards; xuất cần quyền riêng `obj.<api_name>.export` có audit, trường Bảo vệ chỉ xuất cho người đọc được không che (DO-61)                                                                                          | custom-objects, đợt sau (W2)                        |
| Tiến hóa lược đồ; trình dựng đối tượng, trường và bố cục                                                              | Xóa, purge, đổi kiểu trường cần chỉ mục phụ thuộc và lane purge; hướng dẫn tạo trường của trình dựng ghi rằng tên trường là công khai với người đọc được đối tượng, kể cả khi giá trị bị ẩn (`B:custom-objects:R6.5~field-security:R3.3`) | custom-objects, đợt sau (W2)                        |
| Nguồn gốc và nhãn "AI" cho trường do AI ghi (YC29)                                                                    | W1 chỉ chạy trên dữ liệu giả lập (YC89) nên không người thật nào thấy điểm AI; W1 truy nguồn điểm qua Lịch sử chạy (Q5)                                                                                                                   | custom-objects, đợt sau (W2)                        |
| Màn xem theo Chặng: danh sách bản ghi nhóm theo giá trị của trường trạng thái (YC102)                                 | Quy trình lớn là vòng đời của một đối tượng có trường trạng thái, mỗi giá trị là một Chặng, vào một Chặng thì sự kiện bản ghi chạy quy trình ngắn (ADR-0126 (Accepted)); nhãn Chặng trên Bước là của workflow-builder-ui                  | custom-objects, đợt sau (W2)                        |
| Nút "Chạy quy trình" trên trang bản ghi (YC103)                                                                       | Trình kích hoạt Biểu mẫu nội bộ dựng trên `trigger.manual` của workflow-triggers, biểu mẫu antd sinh từ `input_schema`, mở cho thành viên giữ `studio.workflows.run`                                                                      | custom-objects cùng workflow-triggers, đợt sau (W2) |
| Loại bản ghi, công thức và roll-up, tìm toàn văn, XLSX, tenant cá voi                                                 | Chưa có nhu cầu ở lát Marketing                                                                                                                                                                                                           | custom-objects, đợt sau (W3)                        |
| Kiểu trường tệp đính kèm                                                                                              | Nguyên liệu chung của gói Nhân sự, Mua hàng, Tài chính, vốn ở Không làm sau gói Bán hàng của domain-packs (W3); W1 không có kiểu trường này (R2.1)                                                                                        | custom-objects, đợt sau (W3)                        |
| Hạn mức gói cho số đối tượng và trường                                                                                | Mặc định gói chưa quyết (DO-59); W1 chặn bằng ngân sách slot (R1.6)                                                                                                                                                                       | usage-and-limits, đợt sau (W2)                      |
| Policy tầm, `access_key`, chia sẻ, giao người phụ trách                                                               | Quyền trên bản ghi có một chủ (ADR-0105 (Accepted))                                                                                                                                                                                       | record-access                                       |
| `access_mode`, quyền trường, `resolve_field_access`                                                                   | Quyết định trường có một chủ (ADR-0106 (Accepted))                                                                                                                                                                                        | field-security                                      |
| Khóa `obj.<api_name>.<action>`, vai và độ sâu                                                                         | Danh mục quyền có một chủ (ADR-0104 (Accepted))                                                                                                                                                                                           | tenant-rbac                                         |
| Vỏ phiên bản, chỉ mục phụ thuộc, route `/api/v1/studio/artifacts`                                                     | Một vỏ cho mọi loại (ADR-0109 (Accepted))                                                                                                                                                                                                 | tenant-config                                       |
| Bọc giá trị bản ghi khi vào prompt; công cụ dữ liệu đối tượng                                                         | Giá trị bản ghi là đầu vào không tin; chủ là đường công cụ                                                                                                                                                                                | tools-and-skills                                    |
| Tạo bảng, cột, chỉ mục lúc chạy; đối tượng theo workspace; business hook                                              | ADR-0107 (Accepted) bác; hook không có người đăng ký (failure-modes #1)                                                                                                                                                                   | không làm                                           |
| Báo cáo qua API tổng hợp của nền tảng trên RecordService: measure, dimension, time dimension, filter trên khóa trường | Giữ nguyên RLS bản ghi và bảo mật trường cho số tổng hợp (ADR-0127 (Accepted)); đo truy vấn tổng hợp dưới RLS ở cỡ D12 trước (`.claude/plans/studio/discovery/issues/30-aggregate-queries-under-rls.md`)                                  | custom-objects, đợt sau (W3, v1.5)                  |
| Kho phân tích riêng theo tenant cho lớp ngữ nghĩa như Cube; ETL, đồng bộ hay kho dữ liệu                              | Không bộ máy phân tích nào nối PostgreSQL hệ thống ghi chép; kho chỉ do một lane xuất qua RecordService và v1 không làm ETL hay kho dữ liệu (ADR-0127 (Accepted))                                                                         | đợt sau (sau v1)                                    |
| Đa tiền tệ trên một bản ghi                                                                                           | Chưa có nhu cầu ở lát Marketing                                                                                                                                                                                                           | đợt sau (v2)                                        |

## Dữ liệu

Mọi bảng mang `tenant_id`, id UUIDv7, RLS ENABLE và FORCE, policy dạng InitPlan
`tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)`, tên ràng buộc theo
`NAMING_CONVENTION`, `created_at`, `created_by`, `updated_at`, `updated_by` (`updated_at` do
`platform.touch_updated_at()` giữ). Bảng định nghĩa không có `workspace_id` (ADR-0107 (Accepted) quyết định 1):
`studio.object_defs`, `studio.field_defs`, `studio.picklist_options` vào lớp bảng toàn tenant mà CLAUDE.md mục Tenancy
ghi (DO-01, ADR-0100 (Accepted)), mỗi bảng một dòng lý do trong danh sách của `test_rls_coverage.py`.

- `studio.object_defs`: PK `(tenant_id, id)`; FK `(tenant_id, id)` tới `studio.artifacts (tenant_id, id)`
  (`uq_artifacts_tenant_id_id` của tenant-config/02) ON DELETE RESTRICT;
  `api_name` CHECK `^[a-z][a-z0-9_]{1,39}$`, UNIQUE `(tenant_id, api_name)`; `labels` jsonb có khóa `vi` khác
  rỗng; `default_access` NOT NULL DEFAULT `'private'` CHECK `private`, `public_read`, `public_read_write`;
  `ai_description` text NULL CHECK `char_length(ai_description) <= 500`; `schema_version` integer ≥ 1; `next_field_no`
  integer ≥ 1.
- `studio.field_defs`: PK `(tenant_id, id)`, `id` là mã trường; FK `(tenant_id, object_id)` tới
  `studio.object_defs (tenant_id, id)` ON DELETE CASCADE;
  `api_name` như trên, UNIQUE `(tenant_id, object_id, api_name)`; `ai_description` text NULL CHECK
  `char_length(ai_description) <= 500`; `type` CHECK `text`, `number`, `currency`,
  `date`, `datetime`, `boolean`, `picklist`, `email`, `phone`, `url`, `owner`, `workspace`, `user` (bằng enum
  trong mã); `pd_category` NOT NULL CHECK `none`, `basic`, `sensitive`, cùng `sensitive_type` và
  `subject_identifier` theo `dw_kernel.personal_data`; `required`, `is_unique`, `indexed` boolean NOT NULL;
  `max_length` 1..255; `number_mode` `exact`, `float`; `scale` 0..6; `currency_code` `^[A-Z]{3}$`;
  `storage_kind` `system`, `slot`, `data`; `slot` `^(t|u|i|f|d|z|b)[0-9]{2}$` đúng họ của kiểu (`t`, `u`: chữ,
  email, điện thoại, url, `t` thêm danh sách chọn; `i`: số `exact`, tiền; `f`: số `float`; `d`: ngày; `z`: ngày
  giờ; `b`: đúng sai); `field_no` không dùng lại; UNIQUE `(tenant_id, object_id, slot) WHERE slot IS NOT NULL`
  và `(tenant_id, object_id, field_no)`.
- `studio.picklist_options`: PK `(tenant_id, field_id, key)`; FK `(tenant_id, field_id)` tới
  `studio.field_defs (tenant_id, id)` ON DELETE CASCADE;
  `key` `^[a-z0-9_]{1,40}$`; `labels` có `vi`; `position`; `active` boolean NOT NULL.
- `studio.records`: PK `(tenant_id, id)`; `object_id` FK `(tenant_id, object_id)` tới
  `studio.object_defs (tenant_id, id)` ON DELETE RESTRICT; `workspace_id` FK `(tenant_id, workspace_id)` tới
  `platform.workspaces (tenant_id, id)` ON DELETE RESTRICT; `owner_kind` NOT
  NULL CHECK `user`, `team`; `owner_id` NOT NULL; `name` `COLLATE "vi-VN-x-icu"` NOT NULL, 1..255 ký tự;
  `version` ≥ 1; `create_key` ≤ 255 byte, UNIQUE
  `(tenant_id, object_id, create_key) WHERE create_key IS NOT NULL`; `data` jsonb object ≤ 32.768 byte; slot `t`
  (`COLLATE "vi-VN-x-icu"`) và `u` là text
  `octet_length ≤ 1024`, `i` bigint, `f` float8, `d` date, `z` timestamptz, `b` boolean; UNIQUE
  `(tenant_id, object_id, uNN) WHERE uNN IS NOT NULL AND deleted_at IS NULL`; `deleted_at`, `deleted_by`; chỉ
  mục `(tenant_id, object_id, created_at DESC, id DESC)`, `(tenant_id, object_id, updated_at DESC, id DESC)` (btree, hay BRIN trên
  `updated_at` khi luật quyết của ticket 01 chọn A2),
  `(tenant_id, object_id, name, id)`, `(tenant_id, workspace_id)` cho FK tới workspace sở hữu, và chỉ mục từng phần
  của mỗi slot (R9.4).
- `studio.record_write_keys`: PK `(tenant_id, write_key)`; `write_key` text 1..255 byte CHECK bắt đầu bằng `wf:`;
  `record_id` FK `(tenant_id, record_id)` tới `studio.records (tenant_id, id)` ON DELETE CASCADE, index
  `(tenant_id, record_id)`; `op` NOT NULL CHECK `update`, `upsert`, `assign`; `version` integer NOT NULL ≥ 1 (phiên bản
  bản ghi sau lần ghi); `created` boolean NOT NULL DEFAULT false; `owner_kind`, `owner_id`, `workspace_id` NULL, cả ba
  NOT NULL khi `op` là `assign` (CHECK); `actor_id` uuid NOT NULL (chủ thể chạy đã dùng khóa); `created_at` timestamptz
  NOT NULL DEFAULT now(). Không có `workspace_id`: một dòng là khóa của một chủ thể chạy, nên bảng có một dòng lý do
  trong danh sách của `test_rls_coverage.py` và, cạnh policy tenant, một policy RESTRICTIVE dạng bảng riêng của một người
  (CLAUDE.md, Tenancy and authorization; ADR-0117 (Accepted)), `tenant AND (actor_id = app.user_id OR scope)`. Chỉ thêm
  và xóa: `dw_app` có SELECT, INSERT, DELETE (DELETE cho offboarding và lane lưu giữ), không UPDATE. Mảnh lưu giữ `configs/policies/retention.d/studio.record_write_keys.yaml` (định dạng của
  telemetry-and-audit/01) giữ dòng 31 ngày, dài hơn hạn chót 30 ngày của một lượt chạy (workflow-engine:R5.22), và một
  test đọc cả hai số, đỏ khi thời hạn của mảnh không dài hơn hạn chót.
- `studio.dependencies` (bảng của tenant-config/02): spec này thêm `to_field_id uuid` NULL, FK ghép
  `(tenant_id, to_field_id)` tới `studio.field_defs (tenant_id, id)` ON DELETE RESTRICT, index `(tenant_id, to_field_id)`
  (ADR-0109 (Accepted) quyết 5), trong revision tạo `studio.field_defs`.
- Quyền: `dw_app` có SELECT, INSERT, DELETE trên `studio.object_defs`, `studio.field_defs`, `studio.picklist_options` và
  `studio.records` (DELETE cho offboarding); UPDATE trên định nghĩa trừ
  cột khóa; UPDATE trên `studio.records` chỉ ở `name`, `data`, slot, `version`, `updated_*`, `deleted_*`; không
  quyền nào trên partition, kể cả SELECT mà quyền mặc định của schema `studio` cấp (DO-02.2); không gì cho
  `dw_provisioner`, `dw_agent_ro` hay `PUBLIC` (ADR-0105 (Accepted) quyết định 1 và 3). `studio.records` và mỗi partition có policy RESTRICTIVE `tenant_isolation_records`;
  policy PERMISSIVE theo tầm do record-access/03 thêm.

## Kiểm soát

| #    | Kiểm soát                                                           | Yêu cầu            | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ---- | ------------------------------------------------------------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| CO1  | Cô lập công ty trên mọi bảng của spec, kể cả partition              | R4.2, R4.3, R4.6   | A đọc, sửa, xóa bản ghi của B → 404; INSERT với `tenant_id` của B → RLS từ chối; INSERT bản ghi hay trường của A với `object_id` của B, lựa chọn của A với `field_id` của B, định nghĩa đối tượng của A với `id` của thành phần của B, bản ghi của A với `workspace_id` của B, hay dòng `studio.dependencies` của A với `to_field_id` của B → lỗi FK ghép, không dòng nào; đổi một FK ghép thành FK một cột → test đỏ; vai thử NOBYPASSRLS có SELECT đọc thẳng `studio.records_p3` không đặt tenant → 0 dòng; `dw_app` đọc thẳng partition → permission denied (`record-access:R4.3`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| CO2  | Không DDL lúc chạy                                                  | R1.1               | `dw_app` chạy `CREATE TABLE`, `CREATE INDEX` trong `studio` → bị từ chối; phát hành đối tượng 20 trường không đổi số quan hệ của `studio` trong `pg_class`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| CO3  | Chỉ người giữ `studio.objects.manage` sửa định nghĩa                | R1.3               | Người thiếu khóa lưu nháp, Gửi kiểm định `dw.object/v1` → 403, không dòng nào mới trong `studio.artifact_versions`; gỡ kiểm khóa → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| CO4  | Hai trường không chung slot                                         | R1.5               | Hai phát hành song song thêm trường lọc được → hai slot khác; gỡ UNIQUE từng phần trên `slot` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| CO5  | Trường luôn có loại dữ liệu cá nhân                                 | R2.2               | Trường thiếu `pd_category` → 422 `validation_failed` với `errors[].code` `pd_category_required`, không áp gì; CHECK khác danh sách của kernel → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| CO6  | Tên API và kiểu trường bất biến                                     | R2.4               | Phiên bản đổi `api_name` hay kiểu của trường đã phát hành → 422; gỡ bước so với phiên bản đang dùng → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| CO7  | Giá trị trường Đã ẩn không lọt qua describe, lọc, sắp, ghi          | R3.2, R6.6, R8.4   | Lọc, sắp, `fields` trên trường Đã ẩn → 422 `field_not_readable` trước SQL; ghi trường Đã ẩn → 403 `field_not_editable`; describe trả trường Đã ẩn chỉ với `api_name`, nhãn, `access: hidden`; một giá trị của trường Đã ẩn có trong phản hồi → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| CO8  | Từ chối ở mức đối tượng đứng trước tồn tại                          | R3.4               | Người thiếu `obj.<api_name>.read` gọi describe, GET một id có và một id không có → cùng 403                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| CO9  | Bản ghi không đọc được không lộ tồn tại                             | R5.7               | GET, PATCH, DELETE id không đọc được và id không tồn tại → cùng 404, cùng thông điệp                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| CO10 | Một đường ghi                                                       | R5.6               | Thêm một mô-đun có SQL nhắc `studio.records` ngoài adapter bản ghi → test kiến trúc đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| CO11 | Ghi, sự kiện và audit trong một giao dịch                           | R5.2               | Ép lỗi khi chèn outbox → không bản ghi, không audit; tách ghi outbox ra giao dịch khác → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| CO12 | Gửi lại không tạo trùng                                             | R5.3               | Hai lần tạo song song cùng `create_key` → một dòng; gỡ UNIQUE `create_key` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| CO13 | Mô phỏng và Chạy thử không ghi                                      | R5.4               | RecordService ở `simulate` và `test` → 0 dòng, 0 outbox, 0 audit; gỡ bước chế độ chạy → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| CO14 | Người phụ trách và workspace sở hữu không đổi qua `PATCH`           | R6.7               | `PATCH` có `owner` → 422 `validation_failed` với `errors[].code` `field_not_writable` và con trỏ `/owner`; `dw_app` UPDATE cột `owner_id` → permission denied                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| CO15 | Khóa lạc quan                                                       | R6.8               | `If-Match` cũ → 412, `version` giữ nguyên; bỏ so phiên bản → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| CO16 | Trùng không lộ bản ghi                                              | R7.1, R7.4         | Trùng với bản ghi người gọi không đọc được → 409 không id, không giá trị, có audit; trả id → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| CO17 | Tạo hoặc cập nhật không đua                                         | R7.3               | Hai lần upsert song song cùng số đã chuẩn hóa → một dòng; bỏ UNIQUE của slot `u` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| CO18 | Giới hạn dò trùng theo người                                        | R7.6, R7.8         | 20 lần 409 trong 10 phút trượt → lần 409 thứ 20 vẫn 409; lần ghi kế tiếp, trùng hay không, → 429 kèm `Retry-After`, không ghi, đúng một audit `studio.record.duplicate_throttled`; người gọi khác hay đối tượng khác không bị chặn; gỡ lời gọi `RateLimiterPort` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| CO19 | Truy vấn sinh ra luôn có chỉ mục dưới RLS                           | R8.9               | Ma trận toán tử × họ slot × chiều sắp qua harness hình kế hoạch; biên dịch một vị từ qua `data->>` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| CO20 | Offboarding xuất đúng một lần                                       | R4.4               | Công ty có bản ghi ở hai workspace → số dòng xuất bằng số dòng tạo, sau purge 0; cấp SELECT trên một partition cho `dw_app` → đếm đôi, test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| CO21 | Policy tenant là RESTRICTIVE                                        | R4.2               | Thêm policy PERMISSIVE `USING (true)` lên `studio.records` → test catalog đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| CO22 | Ngữ cảnh hỗ trợ không tới route bản ghi                             | R4.5               | Yêu cầu có header `X-DW-Support-Grant` hợp lệ gọi `GET .../records/{record_id}` → 403 `support_context_not_allowed`; thêm route vào `SUPPORT_ALLOWED_ROUTES` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| CO23 | Nới định nghĩa cần người thứ hai, chỉ siết một người                | R1.2, R1.7, R1.8   | Phiên bản thêm một trường, mở một trường `basic` hay đổi `ai_description` → Chờ duyệt, định nghĩa không đổi tới khi người khác duyệt; phiên bản chỉ đóng `phone` → Đang dùng ngay, `tighten_only` đúng, đúng một dòng `studio.version.published` có người gửi là actor và `details.path` `tighten_only`; công ty Đóng băng: phiên bản chỉ đóng `phone` → Đang dùng, phiên bản thêm một trường → 409 `tenant_frozen`, giữ Nháp; nền tảng Đóng băng: phiên bản chỉ siết → 409 `platform_frozen`, giữ Nháp; phiên bản vừa đóng `phone` vừa đổi nhãn → Chờ duyệt; trong lúc phiên bản thêm một trường chờ duyệt, tạo một bản Nháp mới cho đối tượng (để chỉ đóng `phone`) → 409 `conflict` với `details.reason_code` `candidate_pending`, không phiên bản mới, Bản ứng viên và định nghĩa không đổi; rút Bản ứng viên về Nháp, sửa nó thành chỉ đóng `phone` rồi Gửi kiểm định → Đang dùng; coi thay đổi trộn là chỉ siết, cho nhánh chỉ siết qua Đóng băng của nền tảng, để móc phát hành ghi thêm `studio.version.published` hay cho tạo bản Nháp khi Bản ứng viên chờ → test đỏ |
| CO24 | Không mở trường nhạy cảm, không tạo trường dữ liệu cá nhân ở `open` | R2.5               | Phiên bản đặt `open` cho trường `sensitive` hay cho trường mới `basic` → 422 có con trỏ, không phát hành; gỡ bước kiểm → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| CO25 | Mô tả cho AI là dữ liệu, tách khỏi lược đồ và không lộ trường Đã ẩn | R3.7               | Trường có `ai_description` chứa `</input>` và "bỏ qua mọi chỉ dẫn" → JSON Schema của bộ chiếu không có chuỗi đó ở `title`, `description` hay nhãn, giá trị chỉ có trong `ai_description` tách riêng; trường Đã ẩn với người gọi không có `ai_description` ở describe lẫn bộ chiếu; ghép `ai_description` vào `description` của lược đồ → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| CO26 | Lệnh sửa của một Bước có hiệu lực một lần                           | R5.9, R5.10, R5.11 | Chạy lại một Bước `update` sau khi worker chết giữa commit của lần sửa và checkpoint, cùng khóa `wf:` → `version` tăng một lần, một sự kiện `studio.record.updated`, một audit, kết quả mang `replayed: true`; tách lần ghi khóa ra giao dịch riêng hay gỡ bước tra khóa → lần chạy lại sửa lần hai, test đỏ; cùng khóa từ một chủ thể khác → 409 `idempotency_conflict`, 0 dòng đổi; gỡ policy RESTRICTIVE theo chủ thể → chủ thể khác đọc được dòng khóa, test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| CO27 | Phép đo lưu trữ thấy được thứ nó đo                                 | R9.2, R9.5, R9.6   | Harness tự kiểm: một lần chạy kiểm bỏ chỉ mục btree `updated_at` của A1 thì tỉ lệ HOT của lần sửa chỉ chạm `data` phải lớn hơn 0, còn 0 thì bộ đếm HOT mù và harness thoát khác 0; một khẳng định "dùng chỉ mục" không kèm `EXPLAIN (ANALYZE, BUFFERS)`, hay một biến thể chỉ đo ở một modulus → harness thoát khác 0                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát, ghi ở Comments của ticket.
- `make ci` và `make test-integration` xanh; `make test-web` xanh cho ticket 05; số đo R9.1 ghi ở Comments của
  ticket 01 và 04.
- `reviewing-feature-security` và `reviewing-deployment-security` đã chạy cho ticket 02 tới 06.

## Phụ thuộc

- Gói và seam: `dw_studio.records`, `build_studio`, nhóm route `/api/v1/studio` (studio-skeleton/02); schema
  `studio` và test thứ tự offboarding (studio-skeleton/01); mục điều hướng và allowlist antd (studio-skeleton/03).
- Vỏ phiên bản, `ArtifactKindRegistry` (khóa đọc, khóa ghi, khóa gửi, cờ Cổng chất lượng và móc phát hành của mỗi
  loại, ADR-0109 (Accepted) quyết 1; `tenant-config:R2.11`, `tenant-config:R2.12`, `tenant-config:R2.14`,
  `tenant-config:R2.15`; bước niêm phong của nhánh chỉ siết, `tenant-config:R2.16`, còn việc chuyển giai đoạn là của
  `LifecycleService` ở agent-lifecycle dưới đây), `studio.artifact_kinds`,
  `studio.dependencies` (tenant-config/02, ADR-0109 (Accepted); cột `to_field_id` mà mục Dữ liệu của tenant-config giao
  cho spec này vào ticket 02, cùng bảng field); mỗi thành phần có tối đa một phiên bản ở `draft`, `evaluating` hay
  `awaiting_approval` cùng tối đa một bản `live` (`tenant-config:R2.20`; ADR-0120 (Accepted) quyết 1), nên tạo bản
  Nháp mới khi Bản ứng viên đang chờ trả 409 `conflict` với `details.reason_code` `candidate_pending`
  (`tenant-config:R2.22`), và muốn sửa thì rút Bản ứng viên về Nháp (`agent-lifecycle:R2.4`); `RunMode` trên lượt chạy
  (tenant-config/03, ADR-0111 (Accepted)); Bước bản
  ghi của workflow-nodes chỉ chuyển `RunMode` qua `RecordsPort`, RecordService là chỗ giả lập duy nhất (R5.4).
- agent-lifecycle (ticket 06 chờ agent-lifecycle/03, /04): route Gửi kiểm định
  `POST /api/v1/studio/objects/{artifact_id}/versions/{version_id}/submit` kiểm khóa gửi mà `ArtifactKindRegistry` khai
  cho loại (`studio.objects.manage`; `agent-lifecycle:R2.1`); máy giai đoạn `studio.guard_version_stage()` với
  `draft → awaiting_approval` cho loại không có Cổng chất lượng và nhánh chỉ siết `draft → live` kiểm `tighten_only`
  cùng `compared_live_hash` mà `LifecycleService` ghi lúc gửi theo bộ so sánh của loại (`agent-lifecycle:R1.6`,
  `agent-lifecycle:R1.7`, `agent-lifecycle:R2.8`, `agent-lifecycle:R2.9`, `agent-lifecycle:R5.6`, ADR-0120 (Accepted)
  mục 1); phê duyệt `studio.publish.object` mở trong giao dịch gửi với `author_ids`, và handler
  `studio.publish.object.decided` đưa phiên bản lên Đang dùng rồi gọi móc phát hành mà mục `ArtifactKindRegistry` của
  loại mang, trong cùng giao dịch (`agent-lifecycle:R5.1`, `agent-lifecycle:R5.5`, ADR-0120 (Accepted) mục 2), trừ khi
  phiên bản Đang dùng mà lần phát hành này thay không còn là bản đã so lúc gửi: khi đó handler không phát hành mà đưa
  phiên bản về Nháp với `base_changed` (`agent-lifecycle:R5.9`), một hàng rào mà đường W1 không còn dẫn tới vì mỗi thành
  phần có tối đa một bản chưa phát hành; nhánh chỉ siết gọi cùng móc đó trong giao dịch của
  người gửi (`agent-lifecycle:R2.9`); agent-lifecycle ghi đúng một
  `studio.version.published` ở cả hai nhánh, móc phát hành chỉ áp định nghĩa (`agent-lifecycle:R2.9`,
  `agent-lifecycle:R5.5`); Đóng băng của công ty để nhánh chỉ siết đi qua, Đóng băng của nền tảng thì không, và mọi
  lần Gửi kiểm định khác bị từ chối (`agent-lifecycle:R7.9`, ADR-0120 (Accepted) mục 7).
- telemetry-and-audit/01: định dạng mảnh lưu giữ, bộ nạp `platform.retention_terms` và test phủ "mỗi kho có mảnh" mà
  mảnh của `studio.record_write_keys` dùng (H-1), nên ticket 03 chờ ticket đó; lane lưu giữ xóa dòng quá hạn của bảng
  (telemetry-and-audit/03). record-access/05 ghi khóa `wf:` của lần giao vào cùng bảng (record-access:R8.11), nên
  ticket đó chờ ticket 03.
- record-access/01 đo policy trên harness và seed của ticket 01, chỉ thêm biến thể chính sách, và chép số đo vào mục
  Consequences của ADR-0105 (Accepted) (V4.32), nên record-access/01 chờ ticket 01.
- usage-and-limits: `RateLimiterPort` W1 cho R7.6 (usage-and-limits/05) với khóa có kiểu (công ty, người gọi, đối
  tượng), cửa sổ trượt 10 phút (`usage-and-limits:R7.2`) và một lần hỏi trước mỗi lần ghi không tính vào giới hạn
  (`usage-and-limits:R7.3`); mất
  Valkey thì mỗi tiến trình giữ một xô ở hạn mức chia số replica (DO-49).
- foundations-hardening/07 (offboarding đọc theo lô và sổ bước xóa, foundations-hardening:R11.4, foundations-hardening:R11.5,
  FH33; H-2): ticket 02 chờ nó vì đăng ký bước xóa của các bảng của spec này vào sổ đó; ticket 03 đăng ký bước của
  `studio.record_write_keys`.
- `uq_workspaces_tenant_id_id` (org-and-principals/01); `dw_kernel.personal_data` (compliance-pdpl/01,
  ADR-0106 (Accepted)).
- Danh mục quyền `platform.permissions` (tenant-rbac/01, `tenant-rbac:R1.1`) với cột `tenant_grantable`
  (tenant-rbac/02): ticket 02 chờ cả hai vì đăng ký `studio.objects.manage`, câu INSERT nêu mọi cột NOT NULL của
  danh mục lúc đó.
- Khóa `obj.<api_name>.<action>` sinh từ định nghĩa của spec này (tenant-rbac/04); policy PERMISSIVE, cột tầm,
  `studio.assign_record` (record-access/03 và 05); `resolve_field_access`, `access_mode` (field-security/01). Describe,
  danh mục đối tượng và bộ chiếu theo quyền (R3.1 tới R3.6, phần theo quyền của R3.7) dựng trên khóa đọc đối tượng và
  `resolve_field_access` ở ticket 03, ticket đã chờ record-access/03 và field-security/01.
- `Idempotency-Key` gắn người gọi (app-standards/02); ETag, `If-Match`, con trỏ keyset có kiểu, cây lọc JSON,
  harness hình kế hoạch (app-standards/03); problem+json (app-standards/01).
- Bên dùng khai Protocol, gốc ghép đáp bằng `RecordService`: `RecordsPort`, mà workflow-engine/03 khai trong
  `dw_studio.workflows.ports` cùng bản giả và bộ contract test, và workflow-nodes/04 chạy bộ đó trên `RecordService`
  thật (H-30, H-7), kể cả ca chạy lại cùng khóa `wf:` của R5.10 (workflow-engine:R4.22),
  `ObjectDataPort` và bộ chiếu lược đồ (tools-and-skills/03; `ai_description` bao là dữ liệu từ bên ngoài, YC48);
  gieo Lead, Campaign qua API công khai: `POST /api/v1/studio/artifacts` (kind `object`),
  `PUT /api/v1/studio/artifacts/{id}/draft` rồi route Gửi kiểm định ở trên, không có `POST /api/v1/studio/objects`
  (marketing-pilot/02 chờ ticket 06).
- Kiểm lại khi: một trong ADR-0104 (Accepted), ADR-0105 (Accepted), ADR-0106 (Accepted), ADR-0108 (Accepted),
  ADR-0109 (Accepted), ADR-0120 (Accepted) đổi hình hợp đồng → ticket 02 tới 06; số đo ticket 01 cho A1 trượt ngưỡng
  đọc ở cả modulus 8 lẫn modulus 4 → quay lại người đặt yêu cầu (DO-15), R9.2, R9.5, ticket 02; luật quyết của ticket 01
  chọn A2, A3, ít slot hơn hay pivot cho trường tràn → mục Dữ liệu, R9.4, ticket 02; workflow-engine đổi ngữ pháp khóa
  `wf:` hay hạn chót 30 ngày (workflow-engine:R5.22) → R5.9 tới R5.11, mảnh lưu giữ của `studio.record_write_keys`,
  ticket 03; usage-and-limits đổi hình
  `RateLimiterPort` → R7.6, R7.8, ticket 03; agent-lifecycle đổi route Gửi kiểm định, `tighten_only` hay handler
  `studio.publish.object.decided` → R1.2, R1.7, ticket 06; tenant-config đổi luật một bản chưa phát hành mỗi thành phần
  hay mã `candidate_pending`, hay agent-lifecycle đổi lệnh rút → CO23, ticket 06; ADR-0120 (Accepted) mục 7 đổi luật
  Đóng băng của nhánh chỉ siết → R1.7, CO23, ticket 06; tenant-rbac đổi cột NOT NULL của danh mục → ticket 02; workflow-engine/03 bỏ cạnh tới record-access/04 và
  custom-objects/03 → ticket 06 có thể nhập lại ticket 02; foundations-hardening/03 rút `foundations-hardening:R5.3`
  (dạng InitPlan) → mục Dữ liệu, ticket 02; tenant-config/02 đổi hình `studio.dependencies` hay khóa ngoại
  RESTRICT của nó, hay foundations-hardening/07 đổi hình sổ bước xóa → mục Dữ liệu, R4.6, ticket 02, 03.

## Câu hỏi còn mở

- Q7. DO-52: hạn của thùng rác và lịch sử thay đổi? Chủ: luật sư và Đạt. Không đổi: W1 không xóa vĩnh viễn bản
  ghi nào ngoài offboarding; hạn chỉ đặt cho purge lane của W2.

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
  ADR-0109 (Accepted) và roadmap đặt `object` là một loại trong `ArtifactKindRegistry`; theo ADR-0109 (Accepted).
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: ADR-0107 (Accepted) nói slot `u` từ P2, roadmap đưa trường duy nhất
  và Tạo hoặc cập nhật vào ticket 03 của W1 cho YC95; theo roadmap.
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: tóm tắt roadmap của ticket 05 nói trường ẩn vắng,
  ADR-0106 (Accepted) quyết định 4 nói giao diện hiện "Đã ẩn" có khóa, không để trống; theo ADR-0106 (Accepted).
- 23/10/2026 (agent, tạm): ticket 02 tạo `owner_kind`, `owner_id`, `workspace_id`; cột tầm `access_key`,
  `read_grants`, `edit_grants`, `grants_valid_until` (ADR-0105 (Accepted) quyết định 2 và 3) vào cùng policy đọc
  chúng ở record-access. Nếu sai thì: ticket 02 tạo luôn bốn cột đó.
- 23/10/2026 (agent, tạm): khi tạo, người phụ trách là người gọi và workspace sở hữu là workspace đang làm việc,
  theo thiết kế B4 của record-access; policy chèn của ADR-0105 (Accepted) vẫn đòi cả hai trong tầm tạo. Sửa: R5.1.
  Nếu sai thì: body tạo nhận `owner` và `workspace_id`.
- 23/10/2026 (agent, tạm): sự kiện `studio.record.*` v1 mang khóa trường, không mang giá trị; `prior` của brief B5
  đợi bước kích hoạt theo sự kiện bản ghi ở W2. Sửa: R5.2. Nếu sai thì: thêm `prior` và đưa outbox vào bảng
  dispatch yêu cầu chủ thể dữ liệu của ADR-0106 (Accepted).
- 23/10/2026 (agent, tạm): `name_key`, `studio.search_key` và `unaccent` ra cùng tìm không dấu ở W2 vì W1 không
  có người đọc (failure-modes #1); ticket 01 vẫn đo `unaccent`. Nếu sai thì: ticket 02 thêm cột sinh `name_key`.
- 23/10/2026 (agent, tạm): máy tham chiếu của YC20 là host chính sau D14 (ít nhất 4 vCPU, 16 GB) với
  `postgres:16-alpine`; cấu hình thật ghi ở Comments ticket 01. Sửa: R9.1. Nếu sai thì: đo lại trên máy Đạt chỉ
  định.
- 23/10/2026 (agent, tạm): cây lọc W1 nhận `$and`, `$or` và lá `$eq`, `$in`, `$lt`, `$lte`, `$gt`, `$gte`;
  `$not` và `$ne` trả 422 vì chỉ mục btree không mang được (ADR-0108 (Accepted) quyết định 2). Sửa: R8.9. Nếu sai
  thì: thêm hai toán tử khi có dạng mang bởi chỉ mục.
- 23/10/2026 (người đặt yêu cầu và Đạt): Phạm vi D11 và `D:field-security:R1.4~requirements.md:D11` (a): phát hành
  `dw.object/v1` cần người thứ hai; tài liệu mang `default_access` của đối tượng và `access_mode` của mỗi trường; mở cần
  hai người, chỉ siết một người cộng audit ("đóng một người, mở hai người"); công ty một quản trị viên không phát hành
  được đối tượng. Theo DO-05 (a) (một vỏ phiên bản, `live` lưu một lần) và
  `D:mcp-client:R3.4~tenant-config:studio.artifact_versions`, loại không có Cổng chất lượng đi `draft`, Chờ duyệt, Đang
  dùng với phê duyệt `studio.publish.object` (ADR-0120 (Accepted) mục 2); người duyệt giữ khóa chung
  `studio.publish.approve` (`D:agent-lifecycle:R2.1~workflow-nodes:R9.5`). Hỏi: Q1. Sửa: R1.2, R1.7, R2.5, CO23, CO24,
  Trong phạm vi, Phụ thuộc, ticket 02.
- 23/10/2026 (Đạt): `A:custom-objects:R1.4~record-access:R2.5` (a): `default_access` chỉ ghi qua tài liệu `dw.object/v1`;
  ticket 02 là người tạo duy nhất cột và `ck_object_defs_default_access`, record-access chỉ đọc và gắn trigger tăng
  epoch; route `PATCH .../access` không làm. Sửa: R1.4 (giữ).
- 23/10/2026 (Đạt): DO-15 (a): `studio.records` phân vùng băm modulus 8 trên PostgreSQL 16 từ revision đầu nếu ticket 01
  đạt ngưỡng ADR-0107 (Accepted); modulus 4 là đường lui hợp D12; bỏ nhánh không phân vùng; cả hai trượt thì quay lại
  người đặt yêu cầu; số đo vào Comments của ticket 01 trước khi ticket 02 lên ready-for-agent. Hỏi: Q2. Sửa: R9.3, R9.5,
  ticket 01, 02.
- 23/10/2026 (Đạt): DO-16.1 (a) và ADR-0108 (Accepted) với DO-16 (a): mọi route bản ghi dưới `/api/v1/studio/`,
  problem+json RFC 9457 cộng thêm, phương thức riêng là sub-resource `/records/batch-create`, báo ngừng ít nhất 6 tháng.
  Hỏi: Q4. Sửa: ticket 04, 05.
- 23/10/2026 (Đạt): DO-01 (a): Studio là năng lực nền tảng; ba bảng định nghĩa vào lớp bảng toàn tenant
  (ADR-0100 (Accepted)). Hỏi: Q5. Sửa: Dữ liệu, ticket 02.
- 23/10/2026 (Đạt): DO-03.2 (a): port mã thuần kèm test của si-platform có thỏa thuận viết của PO và SA si-platform:
  ghim commit mỗi lần, dòng đầu `Ported from si-platform`, không đồng bộ; mã gắn database, vai hay migration đánh số
  luôn viết lại; thỏa thuận chưa có trước P1 thì viết lại theo cùng bộ test vector. Hỏi: Q6. Sửa: ticket 03.
- 23/10/2026 (Đạt): DO-09.1 (a): vai trò là dữ liệu tenant; khóa quyền và nơi kiểm của spec này không đổi. Hỏi: Q8.
- 23/10/2026 (Đạt): DO-35 (a): trường duy nhất toàn đối tượng; 409 `duplicate_value` chung không nêu id hay giá trị với
  mọi người gọi (R7.1); giới hạn theo người; audit; kiểm trùng của quy trình tiếp nhận chạy dưới tài khoản dịch vụ
  (ADR-0105 (Accepted) mục 8). Ngưỡng và cửa sổ của giới hạn còn chờ Đạt đặt (Q3). Sửa: Câu hỏi còn mở.
- 23/10/2026 (Đạt): DO-49 (a): R7.6 dùng `RateLimiterPort` của usage-and-limits, không bộ đếm Valkey riêng. Sửa:
  CO18, Phụ thuộc, ticket 03.
- 23/10/2026 (Đạt): `B:custom-objects:R6.5~field-security:R3.3` (a): tên trường Đã ẩn công khai, giá trị ẩn; describe
  liệt kê trường Đã ẩn với `access: hidden`; ghi trường Đã ẩn trả 403 `field_not_editable`, trường lạ 422
  `unknown_field`; CO7 bỏ giả định chống dò; hướng dẫn tạo trường nói tên trường là công khai. Sửa: R3.1, R3.2, R6.5,
  R6.6, R8.4, R10.3, CO7, Ngoài phạm vi, ticket 02 tới 05.
- 23/10/2026 (Đạt): DO-02.2 (a): `dw_app` không có quyền nào trên partition, kể cả SELECT mặc định của schema `studio`;
  R4.2 nêu vai đọc thử. Sửa: R4.2, CO1, Dữ liệu, ticket 02.
- 23/10/2026 (Đạt): `D:custom-objects:R5.4~workflow-nodes:R5.3` (a), DO-26.1 (A) và ADR-0111 (Accepted): RecordService là
  chỗ giả lập duy nhất cho mọi đường ghi bản ghi, Bước chỉ chuyển `RunMode` qua `RecordsPort`; W1 chỉ mở `simulate`,
  cửa chạy thử trả 422 với `test` tới W2, RecordService vẫn giả lập `test` như `simulate` nếu một lượt `test` tới.
  Sửa: Phụ thuộc, ticket 03.
- 23/10/2026 (Đạt): DO-08 (a): xác nhận `api_name` bất biến sau lần phát hành đầu. Sửa: R2.4 (giữ).
- 23/10/2026 (Đạt): Q5 (a): nguồn gốc và nhãn "AI" của trường do AI ghi ở W2 cùng YC29; lý do ở Ngoài phạm vi sửa. Sửa:
  Ngoài phạm vi.
- 23/10/2026 (Đạt): DO-37 (a) và DO-61 (a): Điều kiện để lưu được nghĩa "phải đúng", viết bằng CEL; xuất dữ liệu cần
  quyền riêng có audit. Sửa: Ngoài phạm vi.
- 23/10/2026 (Đạt): OPS-b cạnh 4: `ck_artifacts_kind` thành FK tới `studio.artifact_kinds`; ticket 02 thêm một dòng
  `object`, test ở composition root so registry với các dòng. Sửa: Trong phạm vi, ticket 02.
- 23/10/2026 (agent, tạm): lỗi lọc, sắp và trường lạ là 422 `validation_failed` với `errors[].code`
  `field_not_readable`, `field_not_filterable`, `unknown_field` và con trỏ, theo app-standards R1 và ADR-0108 (Accepted)
  mục 1 (`B:app-standards:R1.3~custom-objects:R8.4`). Sửa: R6.5, R8.4, R8.5. Nếu sai thì: các mã thành `code` cấp trên.
- 23/10/2026 (agent, tạm): Trong phạm vi liệt kê đúng tên audit spec này tạo; `studio.record.assigned` của record-access
  (`A:custom-objects:spec~record-access:spec`). Sửa: Trong phạm vi.
- 23/10/2026 (agent, tạm): describe trả trường Đã ẩn chỉ với `api_name`, nhãn và `access`, không kiểu, cờ hay lựa chọn,
  để lộ ít nhất về một trường người gọi không đọc được. Sửa: R3.2. Nếu sai thì: thêm kiểu và cờ vào trường Đã ẩn.
- 24/10/2026 (Đạt): Q-R6, phát hành chỉ siết: phiên bản `dw.object/v1` mà bộ so sánh của loại báo chỉ siết (đóng
  trường, thu hẹp `default_access`) đi `draft → live` bởi một người có audit, mọi phiên bản có nới quyền vẫn
  `draft → awaiting_approval → live` qua người thứ hai; điều kiện trigger kiểm được là cột `tighten_only` do
  LifecycleService tính khi gửi, kèm mã băm của phiên bản Đang dùng đã so; `studio.version.published` ghi người gửi là
  actor và `details.path` `tighten_only` ở nhánh này, người duyệt và `approved` khi qua phê duyệt; ADR-0120 (Accepted)
  mục 1 có nhánh này, D11 "thu hẹp `default_access`" là một người cộng audit (`B:agent-lifecycle:R1.6~custom-objects:R1.7`).
  Sửa: R1.2, R1.7, R1.8, CO23, Trong phạm vi, Phụ thuộc, ticket 02, 06.
- 24/10/2026 (Đạt): agent-lifecycle là chủ route Gửi kiểm định của loại không có Cổng chất lượng
  (`POST /api/v1/studio/objects/{artifact_id}/versions/{version_id}/submit`, khóa của loại do `ArtifactKindRegistry`
  khai), của payload `author_ids` và handler `studio.publish.object.decided` cho mọi loại theo ADR-0120 (Accepted) mục
  2; spec này giữ loại phê duyệt `studio.publish.object`, bộ so sánh và móc phát hành; ticket nối loại `object` vào
  đường đó chờ agent-lifecycle/03, /04 (`B:agent-lifecycle:api~custom-objects:R1.2`,
  `B:agent-lifecycle:R5.1~custom-objects/02`). Sửa: R1.2, R1.3, Phụ thuộc, ticket 06.
- 24/10/2026 (Đạt): mục `ArtifactKindRegistry` của loại `object` khai `studio.objects.manage` là khóa đọc, khóa ghi và
  khóa gửi, và dòng `object` của `studio.artifact_kinds` khai không có Cổng chất lượng (`has_quality_gate = false`)
  (`B:tenant-config:R2.11~workflow-engine:trong-phạm-vi`, `B:agent-lifecycle:R1.6~tenant-config:dữ-liệu`). Sửa: Trong
  phạm vi, Phụ thuộc, ticket 02.
- 24/10/2026 (Đạt): N3: đối tượng và mỗi trường có Mô tả cho AI (`ai_description`, tối đa 500 ký tự, không bắt buộc) từ
  W1; describe và bộ chiếu lược đồ trả nó tách khỏi lược đồ để công cụ đối tượng (tools-and-skills/03) và bước `ai.llm`
  bao nó là dữ liệu từ bên ngoài theo YC48; đổi `ai_description` không phải thay đổi chỉ siết. YC101. Sửa: R2.6, R3.1,
  R3.7, CO23, CO25, Dữ liệu, Trong phạm vi, ticket 02.
- 24/10/2026 (Đạt): DO-35, số tạm (UNVERIFIED, chờ luật sư khi có dữ liệu thật): tối đa 20 lần 409 `duplicate_value` mỗi
  người, mỗi đối tượng, trong cửa sổ trượt 10 phút; vượt thì 429 và audit. `RateLimiterPort` nhận khóa có kiểu (công ty,
  người gọi, đối tượng) (`B:custom-objects:R7.6~usage-and-limits:R7.2`). Hỏi: Q3. Sửa: R7.6, R7.8, CO18, Trong phạm vi,
  Phụ thuộc, Câu hỏi còn mở, ticket 03.
- 24/10/2026 (Đạt): máy tham chiếu có một chủ là YC20 của requirements.md, theo D14; R9.1 và ticket 01 trích YC20
  (`A:custom-objects:quyết-định~record-access:quyết-định`). Sửa: R9.1, ticket 01.
- 24/10/2026 (Đạt): N5, N6, N9, N10: màn xem theo Chặng (YC102, ADR-0126 (Accepted)) và nút "Chạy quy trình" trên trang
  bản ghi (YC103) ở W2; kiểu trường tệp đính kèm ở W3, nguyên liệu chung của các gói sau gói Bán hàng; báo cáo qua API
  tổng hợp trên RecordService ở W3 (v1.5), không ETL, đồng bộ hay kho dữ liệu ở v1 (ADR-0127 (Accepted)). Sửa: Ngoài
  phạm vi.
- 24/10/2026 (Đạt): ticket 02 chờ foundations-hardening/07, vì cả hai sửa `offboarding.py` và cần một thứ tự sửa
  (`C:foundations-hardening/07~record-access/03`). Sửa: Phụ thuộc, ticket 02.
- 24/10/2026 (agent, tạm): đường phát hành qua agent-lifecycle (R1.2, R1.7 và phần gửi của R1.3) tách khỏi ticket 02
  sang ticket 06 mới, chờ ticket 02 và agent-lifecycle/03, /04: đặt cạnh agent-lifecycle/04 ở ticket 02 khép vòng
  ticket 02 → agent-lifecycle/04 → workflow-engine/04 → workflow-engine/03 → record-access/04 → record-access/03 →
  record-access/02 → tenant-rbac/04 → ticket 02, vì workflow-engine/03 chờ record-access/04 và custom-objects/03
  (`I:record-access:R6.4~workflow-engine:R4.9`); ticket 02 giữ bộ so sánh (R1.8) và móc phát hành, kiểm R1.1 bằng
  fixture phê duyệt `approved`, nên các ticket bản ghi, quyền và bảo mật trường không chờ Cổng chất lượng. Sửa: Phụ
  thuộc, Tiêu chí xong, ticket 02, 06. Nếu sai thì: ticket 02 nhận lại R1.2, R1.7 và cạnh tới agent-lifecycle/03, /04
  khi workflow-engine/03 không còn chờ record-access/04 hay custom-objects/03, và ticket 06 rút.
- 24/10/2026 (Đạt): nhánh chỉ siết của phiên bản `dw.object/v1` đi qua được Đóng băng của công ty, vì nó chỉ bớt quyền,
  là việc cần nhất trong sự cố; mọi lần Gửi kiểm định, Lượt kiểm định và phát hành khác vẫn bị từ chối `tenant_frozen`,
  và Đóng băng của nền tảng (`platform_frozen`) vẫn từ chối cả nhánh này; ADR-0120 (Accepted) mục 7 và
  agent-lifecycle sửa cùng. Sửa: R1.7, CO23, Phụ thuộc, ticket 06.
- 24/10/2026 (agent, tạm): describe, danh mục đối tượng, bộ chiếu lược đồ theo quyền (R3.1 tới R3.6) và phần theo quyền
  của R3.7 (trường Đã ẩn không có `ai_description`) chuyển từ ticket 02 sang ticket 03, ticket đã chờ record-access/03 và
  field-security/01, vì chúng cần khóa `obj.<api_name>.read` của tenant-rbac/04 và `resolve_field_access` của
  field-security/01, mà cả hai chờ ticket 02; ticket 02 giữ bộ chiếu dựng JSON Schema từ định nghĩa cùng phần tách
  `ai_description` khỏi lược đồ của R3.7 (`I:custom-objects/02~tenant-rbac/01`). Sửa: Phụ thuộc, Danh sách ticket,
  ticket 02, 03. Nếu sai thì: ticket 04 nhận R3.1 tới R3.6 thay ticket 03, và cạnh của ticket 03 không đổi.
- 24/10/2026 (agent, tạm): ticket 02 chờ tenant-rbac/01 (tạo `platform.permissions`) và tenant-rbac/02 (thêm cột
  `tenant_grantable` NOT NULL không default), và câu INSERT đăng ký `studio.objects.manage` nêu mọi cột NOT NULL của
  danh mục lúc đó, theo quy ước của tenant-rbac và ADR-0104 (Accepted) quyết 1 (`C:custom-objects/02~tenant-rbac/02`,
  `I:custom-objects/02~tenant-rbac/01`). Sửa: Phụ thuộc, ticket 02. Nếu sai thì: tenant-rbac/01 tạo luôn
  `tenant_grantable`, ticket 02 chỉ chờ tenant-rbac/01.
- 24/10/2026 (agent, tạm): `pd_category_required` có một hình trong area: 422 `validation_failed` với mã ở
  `errors[].code` và con trỏ tới trường (app-standards:R1.3), không ở `details.reason_code`; compliance-pdpl là chủ mã
  (compliance-pdpl:R1.1), spec này dẫn cùng hình. Sửa: R2.2, ticket 02. Nếu sai thì: R2.2, CO5 và ticket 02 đổi theo
  hình mà compliance-pdpl chốt.
- 24/10/2026 (agent, tạm): móc phát hành của loại `object` (dịch vụ metadata) là một trường của mục
  `ArtifactKindRegistry` mà tenant-config/02 thêm, như ADR-0109 (Accepted) quyết 1 đặt móc phát hành của loại
  trong mục đăng ký; agent-lifecycle gọi móc đó trong giao dịch phát hành, ở handler `studio.publish.object.decided`
  và ở nhánh chỉ siết (`agent-lifecycle:R5.5`, `agent-lifecycle:R2.9`); spec này cấp móc và không tự nối nó vào
  handler. Sửa: Phụ thuộc, ticket 02. Nếu sai thì: ticket 06 nối móc vào handler và nhánh chỉ siết bằng mã riêng của
  loại, và mục đăng ký không mang móc.
- 24/10/2026 (Đạt): V4.17: mỗi thành phần có tối đa một phiên bản ở `draft`, `evaluating` hay `awaiting_approval`
  (chỉ mục duy nhất một phần, `tenant-config:R2.20`) cùng tối đa một bản `live` (ADR-0120 (Accepted) quyết 1); tạo bản
  Nháp mới khi đang có Bản ứng viên trả 409 `conflict` với `details.reason_code` `candidate_pending`
  (`tenant-config:R2.22`), muốn sửa thì rút Bản ứng viên về Nháp (`agent-lifecycle:R2.4`); ca tranh chấp của V4.2 (một phiên bản chỉ siết lên Đang dùng trong lúc
  phiên bản nới chờ duyệt) không còn xảy ra được, nên rời CO23 và ticket 06, thay bằng ca 409 `candidate_pending`, còn
  kiểm gốc `compared_live_hash` của handler giữ như hàng rào (`agent-lifecycle:R5.9`); dòng thay dòng tạm cùng ngày đã
  đưa ca tranh chấp vào CO23 và ticket 06. Sửa: CO23, Phụ thuộc, ticket 06.
- 24/10/2026 (agent, tạm): không có dịch vụ phát hành nào: mục `ArtifactKindRegistry` của loại mang móc phát hành do
  chủ loại cấp, agent-lifecycle gọi móc đó trong giao dịch phát hành, và `LifecycleService` là bên duy nhất ghi `live`
  (ADR-0109 (Accepted) quyết 1, ADR-0120 (Accepted) quyết 1); Phụ thuộc bỏ "dịch vụ phát hành" khỏi phần của
  tenant-config/02, dòng Quyết định 24/10/2026 về móc phát hành nói ADR-0109 (Accepted) đặt móc phát hành của loại
  trong mục đăng ký, và tiêu chí R1.1 của ticket 02 gọi móc qua mục đăng ký trong giao dịch do fixture mở. Sửa: Phụ
  thuộc, Quyết định, ticket 02. Nếu sai thì: tenant-config có một dịch vụ phát hành gọi móc, Phụ thuộc dẫn lại nó, và
  ticket 02 kiểm R1.1 qua dịch vụ đó.
- 24/10/2026 (agent, tạm): mọi khóa ngoại giữa hai bảng của tenant ở mục Dữ liệu là FK ghép tới khóa `(tenant_id, id)`
  của bảng đích, nêu rõ đích: `studio.object_defs` tới `studio.artifacts (tenant_id, id)` (`uq_artifacts_tenant_id_id`
  của tenant-config/02), `studio.field_defs` và `studio.records` tới `studio.object_defs (tenant_id, id)`,
  `studio.picklist_options` tới `studio.field_defs (tenant_id, id)`, và `object_id` của `studio.records` không còn viết
  như FK một cột, vì kiểm khóa ngoại không đi qua RLS nên FK một cột để một công ty trỏ tới dòng của công ty khác
  (CLAUDE.md, Tenancy and authorization: test âm cho ghi chéo tenant là bắt buộc; Data model rules); CO1 thêm ca
  `object_id` của công ty khác. Sửa: Dữ liệu, CO1, ticket 02. Nếu sai thì: Dữ liệu và ticket 02 trở lại FK theo cột của
  bảng đích, và CO1 bỏ ca đó.
- 24/10/2026 (agent, tạm): `studio.records` có index `(tenant_id, workspace_id)` cho FK ghép tới `platform.workspaces`,
  vì khóa ngoại nào cũng có index ở phía mình (CLAUDE.md, Data model rules) và không index nào của bảng dẫn bằng hai cột
  đó; index vào DDL ứng viên của ticket 01, nên số chỉ mục, thời gian lập kế hoạch, HOT và WAL mà ticket đó đo đã gồm nó
  (R9.2, R9.4). Sửa: Dữ liệu, ticket 01, 02. Nếu sai thì: một index danh sách dẫn bằng `(tenant_id, workspace_id)` thay
  index riêng này, theo số đo của ticket 01.
- 24/10/2026 (agent, tạm): các FK ghép của spec này có tiêu chí riêng R4.6 dưới kiểm soát CO1, với một ca âm cho mỗi FK:
  `object_id` của bản ghi và trường, `field_id` của lựa chọn (chưa có ca âm nào trước đây), `id` của định nghĩa đối tượng
  tới thành phần, `workspace_id` của bản ghi và `to_field_id` của `studio.dependencies`; trong ticket 02 ca `object_id`
  rời tiêu chí R4.2, vì R4.2 nói về kết nối không đặt tenant chứ không về khóa ngoại (CLAUDE.md, Tenancy and
  authorization: test âm cho ghi chéo tenant là bắt buộc; failure-modes #3). Sửa: R4.6, CO1, ticket 02. Nếu sai thì:
  R4.6 rút bằng `[Bỏ]` và ca âm về tiêu chí R4.2 của ticket 02.
- 24/10/2026 (agent, tạm): spec này làm chủ cột `to_field_id` của `studio.dependencies` cùng FK ghép
  `(tenant_id, to_field_id)` tới `studio.field_defs (tenant_id, id)` ON DELETE RESTRICT và index
  `(tenant_id, to_field_id)` (ADR-0109 (Accepted) quyết 5), trong revision của ticket 02, ticket tạo `studio.field_defs`,
  như mục Dữ liệu và ticket 02 của tenant-config giao; bốn bảng của spec này có một bước trong sổ bước xóa
  (H-2; foundations-hardening:R11.4), mà thứ tự suy từ `pg_constraint` đặt sau bước của `studio.dependencies`, để lane
  `offboarding` xóa dòng phụ thuộc trước trường mà FK RESTRICT giữ
  (studio-skeleton:R4.2). Sửa: Trong phạm vi, Dữ liệu, R4.6, CO1, Phụ thuộc, ticket 02. Nếu sai thì: cột và FK vào một
  ticket sau của tenant-config chờ ticket 02 ở đây, và câu giao của tenant-config đổi theo.
- 24/10/2026 (agent, tạm): Phụ thuộc nêu `tenant-config:R2.16` là bước niêm phong của nhánh chỉ siết, không phải bước
  chuyển giai đoạn: dịch vụ vỏ phiên bản của tenant-config niêm phong (`seal`, mã băm, `row_version`), `LifecycleService`
  của agent-lifecycle chuyển `draft → live` và trigger là hàng rào cuối (ADR-0120 (Accepted) quyết 1). Sửa: Phụ thuộc.
  Nếu sai thì: Phụ thuộc nêu lại nhánh chỉ siết là của vỏ phiên bản, theo `tenant-config:R2.16`.
- 25/10/2026 (Đạt): V4.32: giữ slot có kiểu, không mở lại ADR-0107 (Accepted), chỉ sửa phép đo và số: ticket 01 là chủ duy nhất của một harness và một seed (T1 5×10^7 bản ghi trên 50 đối tượng, `mkt_lead` 10^7, cùng cột `t01` giữ picklist ít giá trị ở đối tượng này và email gần như duy nhất ở đối tượng khác, có NULL, trùng và tiếng Việt có dấu; T2 10^6 bản ghi chung partition; 98 tenant nhỏ; 5.000 người, 200 workspace sâu 6 cấp, một tài khoản dịch vụ sở hữu 10^6 lead, một Campaign 10^5 lead con) trên máy của YC20 với ảnh ghim digest, record-access/01 dùng lại và chỉ thêm biến thể chính sách; biến thể A0, A1 (quyết modulus), A2 (BRIN `updated_at`), A3 (bỏ chỉ mục họ `b`), C hẹp (pivot có kiểu mang tầm, chỉ đường ghi và bảo trì), JSONB (một `EXPLAIN` dưới `dw_app` ghi lý do loại), mỗi biến thể ở modulus 8 và 4; tải 50 phiên 80/15/5, soak 2 giờ ở 200 lần ghi mỗi giây, một lần chạy nguội; ngưỡng theo bảng mục 4.5 của bản trả lời; luật quyết: giữ A1 khi mọi dòng có ngưỡng đạt, chỉ đường ghi trượt thì thử A2, A3, giảm số slot mỗi họ, `wal_compression`, rồi mới pivot cho trường tràn; số 3 và 3,4 lần của ADR-0107 (Accepted) thay bằng số đo hay xóa; modulus 8 chỉ khi A1 đạt ngưỡng và cho lợi ích bảo trì đo được, không thì 4; mọi khẳng định "dùng chỉ mục" kèm `EXPLAIN (ANALYZE, BUFFERS)`; ticket 02 vẫn chờ ticket 01. Sửa: R9 (đoạn mở, R9.2, R9.5, thêm R9.6 tới R9.12), Trong phạm vi, Kiểm soát (CO27), Phụ thuộc, ticket 01.
- 25/10/2026 (Đạt): V4.30: mức bảo đảm nội bộ cho bản ghi: RecordService ghi khóa `wf:` của Bước cùng giao dịch với lệnh `update` (và `upsert` khớp bản ghi có sẵn) và phát lại kết quả đã lưu khi gặp lại khóa, để một lần chạy lại sau K4 không sửa lần hai; lệnh `create` đã làm vậy qua `create_key` (R5.3, ticket 03 bước 2), nên chỉ dẫn chiếu; phần `assign` đi qua dịch vụ giao của record-access (record-access:R8.11). Sửa: R5.9 tới R5.11, Trong phạm vi, Dữ liệu, Kiểm soát (CO26), Phụ thuộc, ticket 03.
- 25/10/2026 (agent, tạm): khóa của lệnh sửa nằm ở bảng riêng `studio.record_write_keys` (PK `(tenant_id, write_key)`, chỉ thêm và xóa, policy RESTRICTIVE theo chủ thể chạy dạng bảng riêng của một người, mảnh lưu giữ 31 ngày dài hơn hạn chót 30 ngày của lượt chạy), không phải cột trên `studio.records`, vì một cột "khóa của lần ghi cuối" bị lần ghi sau của làn khác hay của người ghi đè rồi để lần chạy lại sửa lần hai, và không phân vùng theo tháng, vì khóa chính phải duy nhất trên mọi partition để lần chạy lại ở ranh giới tháng vẫn gặp khóa; bảng bị giới hạn bởi mảnh lưu giữ nên không phải bảng không giới hạn mà CLAUDE.md buộc phân vùng; lần giao của record-access/05 ghi vào cùng bảng với `op` `assign` (một chủ cho "khóa của một lần ghi bản ghi", failure-modes #2); bảng vào phép đo đường ghi của ticket 01 (R9.6). Sửa: R5.9 tới R5.11, Dữ liệu, CO26, ticket 01, 03. Nếu sai thì: khóa vào `platform.idempotency_keys` của ADR-0108 (Accepted) quyết 4 với hạn lưu nâng từ 24 giờ lên 31 ngày cho khóa `wf:`, và record-access/05 dùng cùng bảng đó.
- 26/10/2026 (agent, tạm): H-34, `create_key` từ HTTP: route tạo ghép `http:`, `caller_ref` của app-standards/02 và
  `Idempotency-Key` làm `create_key`, vì `create_key` là UNIQUE theo (tenant, object) mà không theo người gọi, nên
  một `Idempotency-Key` trùng khóa `wf:` của một lượt chạy (khóa đoán được từ id lượt và id Bước) sẽ trả bản ghi
  lượt đó tạo cho người gọi khác (R5.3; ADR-0108 (Accepted) quyết 6). Sửa: ticket 03. Nếu sai thì: route từ chối
  422 một `Idempotency-Key` bắt đầu bằng `wf:`, và hai người gọi cùng khóa nhận 409 từ app-standards/02.

## Danh sách ticket

| #   | Ticket                                                                                                                                 |
| --- | -------------------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Đo nền lưu trữ bản ghi trước khi chốt ADR (partition, ngân sách slot, unaccent, InitPlan)](issues/01-do-nen-luu-tru-ban-ghi.md)       |
| 02  | [Định nghĩa object và trường, bảng bản ghi và chiếu JSON Schema từ định nghĩa](issues/02-luoc-do-dinh-nghia-object.md)                 |
| 03  | [RecordService: tạo, đọc, sửa, xóa mềm, trường duy nhất, upsert và describe theo người gọi](issues/03-record-service.md)               |
| 04  | [Truy vấn bản ghi: cây lọc, sắp keyset có kiểu, đếm có trần](issues/04-truy-van-ban-ghi.md)                                            |
| 05  | [Danh sách và biểu mẫu antd sinh từ describe](issues/05-danh-sach-va-bieu-mau-antd.md)                                                 |
| 06  | [Phát hành đối tượng qua vòng đời phiên bản: chỉ siết một người, nới qua người thứ hai](issues/06-phat-hanh-doi-tuong-qua-vong-doi.md) |
