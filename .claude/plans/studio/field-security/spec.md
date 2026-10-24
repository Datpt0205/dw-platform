# Bảo mật trường: Mở hoặc Bảo vệ, cấp theo vai, một hàm cho mọi đường

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Một nhân viên Sales xem một lead không được thấy số điện thoại hay email nếu vai của họ chưa được cấp, kể cả qua
agent chấm điểm, chuỗi mẫu của quy trình, trang duyệt hay lịch sử chạy. Spec này đưa mỗi trường về `open` hoặc
`secured` (dữ liệu cá nhân `secured` mặc định, nhạy cảm luôn `secured`; `access_mode` là thuộc tính trường trong
phiên bản `dw.object/v1`, mở cần người thứ hai, đóng một người cộng audit), một hàm `resolve_field_access` thuần là chủ
duy nhất của quyết định trường, và áp hàm đó ở mọi đường phát giá trị bản ghi (ADR-0106 (Accepted)). W1 che các trường
cá nhân của lead (điện thoại, email, họ tên) ở mọi đường của lát Marketing; ma trận vai, export, chỉ mục truy xuất và
audit đọc nhạy cảm là W2 ở Ngoài phạm vi. Ý định: không đường nào lấy được giá trị mà người xem không được thấy.

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- `ToolDefinition` khai `data_classification: frozenset[str]` mà không quyết định nào đọc
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:167`), cũng vậy ở `ToolSpec`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/tool_specs.py:54`). Ràng buộc: `pd_category` theo từng thuộc
  tính thay nó, có người đọc (ADR-0106 (Accepted) mục 1; failure-modes #1).
- Thang mật `internal`, `confidential`, `restricted` chấm tài liệu và trí nhớ, không chấm trường
  (`packages/python/dw_knowledge/src/dw_knowledge/contracts.py:23-37`). Ràng buộc: bảo mật trường là một trục riêng,
  không dùng lại thang này.
- Bộ che hứa "secrets/PII" nhưng chỉ che khóa bí mật theo mẫu tên
  (`packages/python/dw_observability/src/dw_observability/redaction.py:1`). Thiếu: không đâu che giá trị trường theo
  quyền của người xem.
- `studio.field_defs` giữ `pd_category`, `sensitive_type`, `subject_identifier` nhưng không có `access_mode`; custom-objects
  đẩy `access_mode`, quyền trường và `resolve_field_access` sang spec này
  (`.claude/plans/studio/custom-objects/spec.md:307`). Ràng buộc: spec này thêm `access_mode` và hàm quyết định.
- tenant-rbac tạo `studio.field_permissions` và cho `platform.effective_grants` trả `fld.<object>.<field>.read|edit`
  cộng dồn qua mọi vai (`.claude/plans/studio/tenant-rbac/issues/04-quyen-doi-tuong-va-truong-co-do-sau.md:30-45`).
  Ràng buộc: spec này đọc quyền trường hiệu lực, không tạo bảng quyền trường hay route cấp quyền.
- record-access giữ `studio.actor_boundary_fields` với `access` là `read` hay `edit` cho mỗi phiên bản agent hay quy
  trình, và ghi "field-security đọc `studio.actor_boundary_fields`" (`.claude/plans/studio/record-access/spec.md:379-380`).
  Ràng buộc: giao với giới hạn dữ liệu đọc bảng đó, không tự tính.
- Cấm truy cập của người vận hành theo tiền tố khóa, đã thêm `studio.`, `obj.`, `fld.`
  (`.claude/plans/studio/tenant-rbac/spec.md:30`). Ràng buộc: `fld.*` nằm ngoài tầm của người vận hành
  (ADR-0024 (Proposed)).

## Mục tiêu

### R1 — Mỗi trường Mở hoặc Bảo vệ, dữ liệu cá nhân đóng mặc định

Người dựng và quản trị viên công ty đặt mỗi trường ở `open` hoặc `secured` trong phiên bản `dw.object/v1`, với trường
dữ liệu cá nhân đóng sẵn và trường nhạy cảm không mở được (YC22); mở một trường `basic` đi qua người thứ hai, đóng một
trường một người cộng audit (D11, `custom-objects:R1.2`, `custom-objects:R1.7`).

- R1.1 `studio.field_defs` PHẢI giữ cho mỗi trường đúng một `access_mode` trong `open`, `secured`.
- R1.2 KHI một trường có `pd_category` khác `none` được tạo, `studio.field_defs` PHẢI đặt `access_mode` của trường đó
  là `secured`.
- R1.3 NẾU một lần ghi đặt `access_mode` là `open` cho một trường có `pd_category` là `sensitive`, THÌ PostgreSQL PHẢI
  từ chối với SQLSTATE 23514 `ck_field_defs_sensitive_is_secured` và không đổi gì.
- R1.4 [Bỏ] 23/10/2026: route `PUT .../fields/{field}/security` bỏ; `access_mode` là thuộc tính trường trong
  `dw.object/v1`, đổi qua phát hành của custom-objects (`D:field-security:R1.4~requirements.md:D11`).
- R1.5 [Bỏ] 23/10/2026: cùng lý do với R1.4; khóa `studio.field_security.manage` không có người đọc nên không đăng ký.
- R1.6 KHI một thay đổi `access_mode` được commit, quyết định truy cập trường PHẢI dùng giá trị mới từ câu lệnh đầu
  tiên của mọi yêu cầu bắt đầu sau commit, không chờ cache.

### R2 — Một quyết định trường duy nhất, thuần và có phiên bản

Mọi đường dùng cùng một quyết định cho "người gọi thấy hay sửa trường nào", tính từ `access_mode`, `pd_category`,
quyền trường hiệu lực của người gọi và giới hạn dữ liệu của lượt chạy (YC22, YC23).

- R2.1 Quyết định truy cập trường PHẢI trả cho mỗi trường của một đối tượng đúng một giá trị trong `hidden`, `read`,
  `edit`, kèm phiên bản metadata trường đã dùng.
- R2.2 ĐỐI VỚI một trường `open`, quyết định truy cập trường PHẢI trả `read` cho mọi người gọi đọc được bản ghi và
  `edit` cho người gọi sửa được bản ghi.
- R2.3 ĐỐI VỚI một trường `secured`, quyết định truy cập trường PHẢI trả `hidden` cho vai không được cấp `Xem` hay
  `Xem và sửa` trên trường đó.
- R2.4 KHI một người giữ `fld.<object>.<field>.read` từ một vai và `fld.<object>.<field>.edit` từ một vai khác, quyết
  định truy cập trường PHẢI trả `edit` cho trường đó.
- R2.5 ĐỐI VỚI một lượt chạy loại actor `agent` hay `workflow`, quyết định truy cập trường PHẢI trả giao của quyền
  trường của chủ thể với quyền trường của giới hạn dữ liệu, không bao giờ rộng hơn một trong hai.
- R2.6 ĐỐI VỚI một trường duy nhất, quyết định truy cập trường PHẢI trả ít nhất `read` cho mọi vai có quyền `create`
  hoặc `update` trên đối tượng, kể cả khi trường ở `secured` và chưa được cấp, nên một vai cần ẩn trường duy nhất thì
  không được giữ `create` hay `update` trên đối tượng đó.

### R3 — Áp ở API bản ghi: chiếu, truy vấn, ghi và describe

API bản ghi không để lọt giá trị `hidden` qua đọc, mô tả, lọc, sắp, nhóm, đếm hay ghi (YC23).

- R3.1 KHI API bản ghi trả danh sách hay một bản ghi, API bản ghi PHẢI vắng giá trị của mọi trường `hidden` với người
  gọi khỏi thân trả về và liệt kê trong `hidden_fields` tên mọi trường `hidden` của đối tượng, kể cả trường không có giá
  trị.
- R3.2 NẾU một cây lọc, `order_by`, nhóm hay đếm nhắc một trường `hidden` với người gọi, THÌ bộ biên dịch truy vấn PHẢI
  trả 422 `validation_failed` với `errors[].code` `field_not_readable` trỏ vào trường đó trước khi chạy truy vấn, kể cả
  khi không bản ghi nào khớp, và không trả dòng nào.
- R3.3 NẾU một lần ghi đặt giá trị cho một trường mà quyết định truy cập trường trả `read` hay `hidden` cho người gọi,
  THÌ adapter bản ghi PHẢI trả 403 `field_not_editable` trỏ tới đúng trường đó và không đổi bản ghi.
- R3.4 KHI API bản ghi trả `describe`, API bản ghi PHẢI đánh dấu mỗi trường của đối tượng là `hidden`, `read` hay
  `edit` theo quyết định truy cập trường của người gọi.

### R4 — Áp ở agent, quy trình, phê duyệt và lịch sử chạy

Công cụ của agent, chuỗi mẫu của quy trình, nội dung phê duyệt và lịch sử chạy không để lọt giá trị `hidden` với người
xem hay ngoài giới hạn dữ liệu (YC23, YC87, YC51).

- R4.1 KHI runtime dựng lược đồ công cụ đối tượng cho một lượt chạy, bộ dựng lược đồ công cụ PHẢI chỉ gồm các trường mà
  quyết định truy cập trường trả `read` hoặc `edit` cho giao của chủ thể với giới hạn dữ liệu của lượt chạy.
- R4.2 KHI một công cụ đối tượng trả kết quả cho một lượt chạy, công cụ đối tượng PHẢI vắng mọi trường `hidden` với
  giao của chủ thể và giới hạn dữ liệu.
- R4.3 NẾU một chuỗi mẫu `{{...}}` của một bước quy trình nhắc một trường `hidden` với chủ thể chạy, THÌ bước đó PHẢI
  lỗi `template_field_hidden` và không gửi gì.
- R4.4 KHI trang duyệt dựng nội dung một phê duyệt, trang duyệt PHẢI lấy giá trị trường sống theo quyền của người xem và
  hiện `Đã ẩn` cho trường người xem không đọc được.
- R4.5 KHI một bước phê duyệt mở một phê duyệt tham chiếu các trường, bộ chọn người duyệt PHẢI chỉ trả người giữ `Xem`
  trên mọi trường mà bước đó đóng dấu, theo cùng luật mà R4.7 áp ở lúc quyết.
- R4.6 KHI lịch sử chạy hiện đầu vào và đầu ra của một bước, lịch sử chạy PHẢI hiện tên trường và lấy giá trị sống theo
  quyền của người xem, không giá trị đóng dấu lúc lượt chạy chạy.
- R4.7 NẾU người quyết một phê duyệt `studio.step.approval` không giữ `Xem` trên mọi trường mà bước phê duyệt đóng dấu
  ở lúc quyết, THÌ guard quyết định của loại đó PHẢI trả 403 và không ghi quyết định.

### R5 — Một quyết định cho mọi đường

Thêm một đường ra giá trị bản ghi mà không gọi quyết định truy cập trường là một lỗ hổng, và adapter bản ghi là nơi
duy nhất đọc giá trị bản ghi (YC23).

- R5.1 Mọi đường phát một giá trị trường ra ngoài lượt chạy PHẢI lấy kết quả từ quyết định truy cập trường, không tự
  quyết định trường nào hiện.
- R5.2 Ngoài adapter bản ghi, không mô-đun nào PHẢI đọc bảng `studio.records` hay một cột slot của nó.

## Trong phạm vi

- Cột `studio.field_defs.access_mode` với `ck_field_defs_access_mode`, `ck_field_defs_sensitive_is_secured`, và trigger
  đặt `access_mode = 'secured'` khi `pd_category <> 'none'` lúc tạo trường; dịch vụ metadata của custom-objects ghi cột
  từ thuộc tính `access_mode` của phiên bản `dw.object/v1`.
- Hàm thuần `resolve_field_access(principal_grants, object_security, boundary) -> FieldAccess` và helper chiếu
  `visible_fields(principal, object)` trong gói truy cập Studio; kiểu `FieldAccess` (map trường sang `hidden`, `read`,
  `edit` kèm `fls_version`).
- Lớp áp `FieldAccess` trong adapter bản ghi và bộ biên dịch truy vấn (chọn cột đọc được, từ chối lọc hay sắp trên
  trường ẩn trước SQL, từ chối ghi theo trường, trả `hidden_fields`), trong bộ dựng lược đồ công cụ đối tượng và chiếu
  đầu ra công cụ, trong bộ dựng chuỗi mẫu `{{...}}`, trong bộ dựng nội dung phê duyệt và bộ chọn người duyệt, trong điều
  kiện đọc trường của `decision_guards["studio.step.approval"]` (DO-36), và trong lịch sử chạy.
- Component che giá trị `@dw/ui` ("Đã ẩn" kèm khóa) mà màn danh sách và màn bản ghi của custom-objects dùng.
- Test kiến trúc: chỉ adapter bản ghi đọc giá trị bản ghi và cột slot.

## Ngoài phạm vi

| Việc                                                                                                                                        | Vì sao                                                                                                                                                                                                                                           | Chủ                                      |
| ------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------- |
| Nội dung chỉ mục truy xuất chỉ gồm trường được phép; `fls_version` đánh chỉ mục lại                                                         | Chỉ mục truy xuất đến cùng knowledge; `fls_version` theo object (ADR-0106 (Accepted) mục 4)                                                                                                                                                      | field-security, đợt sau (W2)             |
| Màn cấu hình bảo mật trường (ma trận vai × trường), "Xem như vai"                                                                           | Cần đo hiệu năng ma trận ở 320 px; W1 giao route và hàm trước                                                                                                                                                                                    | field-security, đợt sau (W2)             |
| Export, lịch sử bản ghi, webhook theo quyền người xem lúc gửi                                                                               | Cần tác vụ nền export và endpoint webhook; chiếu theo principal của endpoint                                                                                                                                                                     | field-security, đợt sau (W2)             |
| Công thức thừa hưởng mức chặt nhất; audit `pd.read` cho phản hồi mang giá trị nhạy cảm, chỉ id bản ghi và tên trường                        | Trường công thức cần CEL; audit đọc nhạy cảm theo từng phản hồi là YC24 (W2), tên sự kiện theo ADR-0106 (Accepted) quyết 5                                                                                                                       | field-security, đợt sau (W2)             |
| Che một phần (bốn số cuối) và quyền "xem không che"                                                                                         | Cần một trục quyền mới; chưa có nhu cầu ở lát Marketing                                                                                                                                                                                          | field-security, đợt sau (W3)             |
| Không giá trị trường trong telemetry, log, audit và lỗi                                                                                     | Một chủ cho "không nội dung" dùng cùng hàm này (packet không cắt ticket riêng)                                                                                                                                                                   | telemetry-and-audit                      |
| `studio.field_permissions`; route cấp `fld.*` cho vai; chống cấp vượt quyền mình; người thứ hai khi cấp `fld.*`; người cấp `fld.*` đầu tiên | Quyền trường trong vai và chống leo thang có một chủ (ADR-0104 (Accepted), ADR-0106 (Accepted) mục 3); cấp `fld.*` là thay đổi vai trò hai người từ W1, kể cả trường nhạy cảm (DO-09.2); `tenant_owner` giữ mọi `fld.*` qua quyền tính động (N1) | tenant-rbac (R6.8, R7, R9.5, R9.6, R9.7) |
| Đổi `access_mode` qua phát hành `dw.object/v1`: mở trường `basic` cần người thứ hai, đóng trường một người cộng audit                       | Một đường ghi cho định nghĩa đối tượng (`D:field-security:R1.4~requirements.md:D11`)                                                                                                                                                             | custom-objects (R1.2, R1.7, R2.5)        |
| Danh mục `pd_category`, `sensitive_type`, `subject_identifier`; yêu cầu chủ thể dữ liệu; phát hiện Presidio                                 | Từ vựng dữ liệu cá nhân và DSR có một chủ (ADR-0106 (Accepted) mục 7, 9)                                                                                                                                                                         | compliance-pdpl                          |
| Cột `pd_category`, `sensitive_type`, `subject_identifier` trên `studio.field_defs`                                                          | Định nghĩa trường có một chủ (custom-objects R2.2)                                                                                                                                                                                               | custom-objects                           |
| Che số điện thoại, email trong văn bản tự do (lời nhắn, email)                                                                              | Che văn bản tự do là Presidio, không phải quyết định trường (ADR-0106 (Accepted) mục 9)                                                                                                                                                          | compliance-pdpl                          |
| Ẩn hay bắt buộc trường theo bố cục hay workspace                                                                                            | Overlay hiển thị, không phải kiểm soát truy cập                                                                                                                                                                                                  | custom-objects                           |
| Quyền trên bản ghi (ai thấy bản ghi nào)                                                                                                    | Quyền trên bản ghi có một chủ (ADR-0105 (Accepted))                                                                                                                                                                                              | record-access                            |
| Bảo mật trường bằng quyền cột của PostgreSQL                                                                                                | Quyền cột theo role DB, một `dw_app` cho mọi người; che cần giá trị (ADR-0106 (Accepted))                                                                                                                                                        | không làm                                |

## Dữ liệu

- `studio.field_defs` (custom-objects ticket 02 tạo): spec này thêm `access_mode text NOT NULL DEFAULT 'open'` với
  `ck_field_defs_access_mode CHECK (access_mode IN ('open','secured'))`; `ck_field_defs_sensitive_is_secured`
  `CHECK (pd_category <> 'sensitive' OR access_mode = 'secured')`; trigger `BEFORE INSERT` đặt `access_mode = 'secured'`
  khi `pd_category <> 'none'`. `dw_app` UPDATE thêm cột `access_mode` trong tập cột định nghĩa được sửa; người ghi duy
  nhất là dịch vụ metadata khi một phiên bản `dw.object/v1` lên Đang dùng.
- Thay đổi `access_mode` tăng phiên bản quyền của tenant (`platform.bump_access_version()` của tenant-rbac ticket 02)
  qua trigger trên `studio.field_defs`, để quyết định trường đọc lại từ câu lệnh kế tiếp (R1.6).
- Không bảng mới: quyền trường ở `studio.field_permissions` của tenant-rbac; `pd_category` và họ hàng ở
  `studio.field_defs` của custom-objects; giới hạn trường ở `studio.actor_boundary_fields` của record-access.

## API

- Spec này không mở route nào. `access_mode` đổi qua phát hành `dw.object/v1` (`custom-objects:R1.2`,
  `custom-objects:R1.7`); một phiên bản mở trường nhạy cảm bị trình kiểm của loại `object` trả 422 có con trỏ
  (`custom-objects:R2.5`).
- Cấp `fld.<object>.<field>.read|edit` cho vai đi qua `PUT /api/v1/admin/roles/{role_id}/permissions` của tenant-rbac
  ticket 04 (`field_permissions: [{field_id, access}]`), không qua route của spec này.
- Lỗi lọc, sắp trên trường `hidden` là 422 `validation_failed` với `errors[].code` `field_not_readable` và
  `errors[].pointer` (app-standards R1, ADR-0108 (Accepted) mục 1); ghi trường không sửa được là 403
  `field_not_editable`.

## Màn hình

- Component `@dw/ui` che giá trị: khi quyết định truy cập trường trả `hidden`, màn bản ghi và danh sách hiện `Đã ẩn`
  kèm biểu tượng khóa, không ô trống (custom-objects R10.3 dùng component này).

## Kiểm soát

| #    | Kiểm soát                                                       | Yêu cầu          | Test âm                                                                                                                                                                                                        |
| ---- | --------------------------------------------------------------- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FS1  | Dữ liệu cá nhân đóng mặc định; trường `secured` ẩn nếu chưa cấp | R1.2, R2.3       | trường `pd_category = 'basic'` chưa cấp → quyết định trả `hidden`, GET không có giá trị, `hidden_fields` có tên, lược đồ công cụ không có; đổi mặc định của `pd` khác `none` sang `open` → đỏ                  |
| FS2  | Một quyết định cho mọi đường; chỉ adapter đọc giá trị           | R5.1, R5.2       | MP6: gỡ áp quyết định ở một đường (chiếu REST, lược đồ công cụ, chuỗi mẫu, phê duyệt, lịch sử chạy) → test rò của đúng đường đó đỏ; mô-đun ngoài adapter đọc `studio.records` hay cột slot → test kiến trúc đỏ |
| FS3  | Không oracle qua lọc, sắp, nhóm, đếm                            | R3.2             | lọc theo `phone` ẩn → 422 `validation_failed` với `errors[].code` `field_not_readable` cả khi 0 bản ghi khớp; sắp theo trường ẩn → 422; gỡ kiểm trong bộ biên dịch → đỏ                                        |
| FS4  | Ghi trường không sửa được bị từ chối theo trường                | R3.3             | `PATCH {status, phone}` khi `phone` chỉ `read` → 403 `field_not_editable`, `status` không đổi; gỡ kiểm theo trường → đỏ                                                                                        |
| FS5  | API không trả giá trị `hidden`                                  | R3.1, R3.4       | quét JSON của list, get, describe → không có giá trị đã gieo của trường ẩn, mọi trường ẩn (cả trường trống) có tên trong `hidden_fields` và có `access: hidden` trong describe; gỡ chiếu cột → đỏ              |
| FS6  | Chuỗi mẫu không lộ trường ẩn                                    | R4.3             | `{{lead.phone}}` khi chủ thể chạy không đọc được → bước lỗi `template_field_hidden`, 0 lần gửi; gỡ kiểm mẫu → đỏ                                                                                               |
| FS7  | Trường duy nhất đọc được với người ghi                          | R2.6             | ẩn trường duy nhất với vai có quyền `create` → quyết định trả `read`; lỗi trùng của custom-objects không có giá trị, không id bản ghi kia; gỡ ngoại lệ trường duy nhất → đỏ                                    |
| FS8  | Agent và quy trình giao với giới hạn dữ liệu                    | R2.5, R4.1, R4.2 | lược đồ công cụ và đầu ra không có trường ngoài giới hạn dữ liệu hay ngoài quyền chủ thể; mở rộng giới hạn dữ liệu của phiên bản → test đỏ                                                                     |
| FS9  | Phê duyệt và lịch sử chạy che theo người xem                    | R4.4, R4.6       | người duyệt không có `Xem` trên `phone` thấy `Đã ẩn` trong nội dung tin nhắn chờ duyệt và trong lịch sử chạy; đóng dấu giá trị lúc lượt chạy chạy → đỏ                                                         |
| FS10 | Người duyệt giữ quyền đọc trường nội dung tham chiếu            | R4.5, R4.7       | phê duyệt tham chiếu `phone` → chỉ người giữ `fld.lead.phone.read` được chọn; người mất `fld.lead.phone.read` sau khi phê duyệt mở gọi `decide` → 403, phê duyệt vẫn chờ; gỡ điều kiện khỏi guard → đỏ         |
| FS11 | Nhạy cảm luôn `secured`                                         | R1.3             | `UPDATE studio.field_defs SET access_mode = 'open'` cho trường nhạy cảm → 23514 `ck_field_defs_sensitive_is_secured`; gỡ CHECK → đỏ                                                                            |
| FS12 | Đổi `access_mode` có hiệu lực từ câu lệnh kế tiếp               | R1.6             | phiên bản đóng `phone` lên Đang dùng ở giao dịch A → yêu cầu đầu tiên sau đó thấy `phone` là `hidden`; gỡ trigger tăng phiên bản trên `studio.field_defs` → đỏ                                                 |

## Tiêu chí thành công

- Test đầu-cuối của lát Marketing: một vai Sales không được cấp `fld.lead.phone.*` và `fld.lead.email.*` không thấy số
  điện thoại hay email của lead ở bất kỳ đường nào (API, describe, công cụ agent chấm điểm, chuỗi mẫu, trang duyệt,
  lịch sử chạy), góp vào YC23.
- Chiếu trường là chọn cột và từ chối lọc, sắp lúc biên dịch, không thêm chi phí mỗi dòng; số đo trang bản ghi của
  record-access R9 và custom-objects R9 chạy với quyền trường áp vẫn giữ ngưỡng YC20.

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát FS1-FS12 có test âm đã thấy đỏ khi gỡ kiểm soát, ghi ở Comments của ticket cài
  nó.
- `make ci` và `make test-integration` xanh; `reviewing-feature-security` và `reviewing-deployment-security` đã chạy
  cho ticket 02; kiểm mutation MP6 ghi lại một lần đỏ cho mỗi đường áp (FS2).

## Phụ thuộc

- custom-objects: `studio.field_defs` với `pd_category`, `sensitive_type`, `subject_identifier` và `(tenant_id, id)`
  là mã trường (ticket 02); adapter bản ghi, bộ biên dịch truy vấn, `describe` và bộ chiếu lược đồ gọi
  `resolve_field_access` (`custom-objects:R3.2`, `custom-objects:R6.6`, `custom-objects:R8.4`, ticket 03, 04);
  `access_mode` là thuộc tính trường của `dw.object/v1`, mở hay đóng trường đi qua phát hành của custom-objects
  (`custom-objects:R1.2`, `custom-objects:R1.7`, `custom-objects:R2.5`).
- tenant-rbac: `platform.effective_grants` trả `fld.<object>.<field>.read|edit` cộng dồn (`tenant-rbac:R9.6`), chống
  cấp quyền trường vượt quyền mình (`tenant-rbac:R9.5`), `bind` không phủ vai trò mang `fld.*` trên trường nhạy cảm
  (`tenant-rbac:R6.8`), hai người khi cấp `fld.*` (`tenant-rbac:R7.1`), `tenant_owner` giữ mọi `fld.*` trên mọi trường
  sống qua quyền tính động (`tenant-rbac:R9.7`), và `platform.bump_access_version()` (ticket 02, 04); cấm khóa `studio.`,
  `fld.` khỏi người vận hành (`tenant-rbac:R1.5`).
- record-access: `studio.actor_boundary_fields` và ngữ cảnh actor (`app.actor_kind`, `app.boundary_id`) ở mọi cửa
  (`record-access:R6.4`, ticket 04) cho giao với giới hạn dữ liệu.
- compliance-pdpl: `dw_kernel.personal_data` là chủ của `pd_category`, `sensitive_type`, `subject_identifier`
  (`.claude/plans/studio/compliance-pdpl/issues/01-tu-vung-du-lieu-ca-nhan.md`, ADR-0106 (Accepted) mục 1).
- tools-and-skills: lược đồ và đầu ra công cụ đối tượng gọi quyết định trường
  (`.claude/plans/studio/tools-and-skills/issues/03-cong-cu-du-lieu-doi-tuong.md`).
- workflow-nodes: bộ dựng chuỗi mẫu `{{...}}` và bước tool-call, human-approval gọi quyết định trường
  (`.claude/plans/studio/workflow-nodes/issues/03-pham-vi-bien-va-buoc-logic.md`,
  `.claude/plans/studio/workflow-nodes/issues/06-tool-call-va-human-approval.md`); bước phê duyệt đóng dấu tên trường và
  workflow-nodes/06 sở hữu `decision_guards["studio.step.approval"]`, spec này thêm điều kiện đọc trường vào guard đó,
  đọc database qua guard async của tenant-config/05 (DO-36).
- telemetry-and-audit: lịch sử chạy theo bước lấy giá trị trường sống theo người xem
  (`.claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md`).
- app-standards: problem+json (R1) cho mã lỗi lọc, sắp, ghi của API bản ghi.
- Kiểm lại khi: `platform.effective_grants` hay `studio.actor_boundary_fields` đổi hình → ticket 01, 02; luật sư trả lời
  DO-34.2 hay FOG-74 làm một trường thí điểm thành `sensitive` → chỉ đổi `pd_category` qua phiên bản `dw.object/v1` mới,
  không đổi mã của spec này.

## Câu hỏi còn mở

## Quyết định

- 22/10/2026 (người yêu cầu): D3: quyết định trường áp cả cho agent và kết quả tìm kiếm; D4: lát Marketing là ví dụ
  chạy, che điện thoại, email, họ tên của lead. Sửa: R1, R2, R4.
- 23/10/2026 (agent, tạm): theo ADR-0106 (Accepted) mục 2, đổi `access_mode` của một trường `basic` chỉ cần người giữ
  `studio.field_security.manage` cộng audit, không phải maker-checker của ADR-0110 (Accepted); cấp `fld.*` cho vai vẫn
  đi qua đường hai người của tenant-rbac. Sửa: R1.4. Nếu sai thì: route `PUT .../security` đi qua đề xuất và xác nhận
  của hai người như thay đổi cấu hình tenant.
- 23/10/2026 (agent, tạm): DO-36 theo khuyến nghị (a): người duyệt phải giữ `Xem` trên mọi trường nội dung phê duyệt
  tham chiếu, ứng viên duyệt tìm theo mức truy cập qua quyền hiệu lực. Sửa: R4.5. Nếu sai thì: người duyệt quyết trên
  dấu `Đã ẩn` và ứng viên thu về workspace của lượt chạy.
- 23/10/2026 (agent, tạm): `studio.field_permissions`, route cấp `fld.*` cho vai và chống cấp quyền trường vượt quyền
  mình thuộc tenant-rbac ticket 04, không phải spec này; brief B4 đặt chúng ở field-security ticket 01, nhưng
  tenant-rbac đã nhận và đã lên đĩa (`tenant-rbac:R9.5`, `tenant-rbac:R9.6`). Nếu sai thì: spec này nhận lại bảng quyền
  trường và route cấp quyền.
- 23/10/2026 (agent, tạm): đối chiếu chang.fpt.net: "Phân quyền & hành vi" của họ chỉ chặn ai mở agent, không có quyền
  trên trường hay phân loại dữ liệu cá nhân (config-chang.md mục 2, mục 5); Studio giữ thiết kế riêng — quyết định
  trường bằng một hàm theo ADR-0106 (Accepted) — là Cải tiến, không phải mẫu học theo hay mã của họ. Không đổi: R2,
  R4.1.
- 23/10/2026 (Đạt): DO-34.1 (a): trường `basic` và `sensitive` đều `secured` khi tạo; `basic` mở được theo D11;
  `sensitive` không bao giờ mở. Thí điểm phải cấp `fld.*` họ tên cho vai cần đọc. Hai câu con còn lại đã có chủ: audit đọc
  nhạy cảm theo từng phản hồi là YC24 (W2), người thứ hai khi cấp đọc trường nhạy cảm có từ W1 qua tenant-rbac. Câu hỏi
  luật sư (DO-34.2, FOG-74) chỉ đổi dữ liệu trường, không chặn ticket W1. Hỏi: Q1. Sửa: Phụ thuộc.
- 23/10/2026 (người đặt yêu cầu và Đạt): Phạm vi D11 và `D:field-security:R1.4~requirements.md:D11` (a): `access_mode` là
  thuộc tính trường trong `dw.object/v1`; mở một trường `basic` cần người thứ hai qua phát hành, đóng một trường một
  người cộng audit ("đóng một người, mở hai người"); route `PUT .../security` và khóa `studio.field_security.manage`
  bỏ; spec này giữ quyết định trường và CHECK nhạy cảm. Bỏ quyết tạm một người ngày 23/10/2026. Sửa: R1, R1.4, R1.5,
  FS12, Trong phạm vi, Ngoài phạm vi, Dữ liệu, API, ticket 01.
- 23/10/2026 (Đạt): DO-09.2 (a): cấp `fld.*` là thay đổi vai trò hai người của tenant-rbac từ W1, nên người thứ hai khi
  cấp đọc trường nhạy cảm không còn là v1.5; vai trò mang `fld.*` trên trường nhạy cảm tính là trọng yếu với
  `platform.roles.bind` (DO-32.1). Sửa: Ngoài phạm vi.
- 23/10/2026 (Đạt): ADR-0106 (Accepted) và OPS-a.2: tên ràng buộc theo `NAMING_CONVENTION` trên `studio.field_defs` là
  `ck_field_defs_access_mode`, `ck_field_defs_sensitive_is_secured`. Sửa: R1.3, FS11, Trong phạm vi, Dữ liệu, ticket 01.
- 23/10/2026 (Đạt): `B:custom-objects:R6.5~field-security:R3.3` (a): tên trường ẩn công khai, giá trị ẩn; `hidden_fields`
  liệt kê mọi trường ẩn của đối tượng kể cả trường trống; describe liệt kê trường ẩn với `access: hidden`; ghi trường
  ẩn trả 403 `field_not_editable`. Sửa: R3.1, R3.4, FS5, ticket 02.
- 23/10/2026 (Đạt): DO-36 (a): spec này là chủ luật người duyệt phải giữ `Xem` trên mọi trường mà bước phê duyệt đóng
  dấu; bộ chọn người duyệt và guard `decision_guards["studio.step.approval"]` của workflow-nodes/06 gọi cùng hàm, nên
  người mất quyền đọc sau khi phê duyệt mở bị từ chối tại `decide` (YC14); tenant-rbac R2.2 chỉ trỏ tới. Sửa: R4.5,
  R4.7, FS10, Trong phạm vi, Phụ thuộc, ticket 02.
- 23/10/2026 (agent, tạm): lỗi lọc, sắp trên trường ẩn là 422 `validation_failed` với `errors[].code`
  `field_not_readable` và `errors[].pointer`, theo app-standards R1 và ADR-0108 (Accepted) mục 1
  (`B:app-standards:R1.3~custom-objects:R8.4`). Sửa: R3.2, FS3, API. Nếu sai thì: `field_not_readable` thành `code` cấp
  trên và mục API trích lại.
- 23/10/2026 (agent, tạm): ticket 01 chờ record-access/04 vì R2.5 đọc `studio.actor_boundary_fields`
  (`I:field-security/01~record-access/04`); ticket 01 không còn route nên không chờ app-standards. Sửa: ticket 01. Nếu sai
  thì: bỏ cạnh khi giới hạn dữ liệu đến từ bảng khác.
- 24/10/2026 (Đạt): N1: quyền tính động của `tenant_owner` gồm mọi `fld.*` trên mọi trường sống (`tenant-rbac:R9.7`), nên
  chủ sở hữu công ty cấp được `fld.*` đầu tiên trên một trường `secured`, và đưa `fld.*` vào vai khác vẫn đi đường hai
  người của tenant-rbac; quyết định truy cập trường không đổi vì nó đọc quyền hiệu lực
  (`D:field-security:DO-34~tenant-rbac:R9.5`). Sửa: Ngoài phạm vi, Phụ thuộc.
- 24/10/2026 (Đạt): R2.6 nêu hệ quả của ngoại lệ trường duy nhất: vai cần ẩn trường duy nhất thì không giữ `create` hay
  `update` trên đối tượng; marketing-pilot ghi quyền đối tượng của vai Cộng tác viên Marketing cho khớp
  (`B:field-security:R2.6~marketing-pilot:dữ-liệu`). Sửa: R2.6.

## Danh sách ticket

| #   | Ticket                                                                                                     |
| --- | ---------------------------------------------------------------------------------------------------------- |
| 01  | [Mô hình bảo mật trường và hàm quyết định duy nhất visible_fields](issues/01-mo-hinh-bao-mat-truong.md)    |
| 02  | [Áp bảo mật trường ở API bản ghi, agent, workflow, phê duyệt và lịch sử chạy](issues/02-ap-o-moi-duong.md) |
