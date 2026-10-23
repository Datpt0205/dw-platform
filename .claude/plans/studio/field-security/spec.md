# Bảo mật trường: Mở hoặc Bảo vệ, cấp theo vai, một hàm cho mọi đường

Status: needs-info (DO-34)
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Một nhân viên Sales xem một lead không được thấy số điện thoại hay email nếu vai của họ chưa được cấp, kể cả qua
agent chấm điểm, chuỗi mẫu của quy trình, trang duyệt hay lịch sử chạy. Spec này đưa mỗi trường về `open` hoặc
`secured` (dữ liệu cá nhân `secured` mặc định, nhạy cảm luôn `secured`), một hàm `resolve_field_access` thuần là chủ
duy nhất của quyết định trường, và áp hàm đó ở mọi đường phát giá trị bản ghi (ADR-0106 (Proposed)). W1 che các trường
cá nhân của lead (điện thoại, email, họ tên) ở mọi đường của lát Marketing; ma trận vai, export, chỉ mục truy xuất và
audit đọc nhạy cảm là W2 ở Ngoài phạm vi. Ý định: không đường nào lấy được giá trị mà người xem không được thấy.

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- `ToolDefinition` khai `data_classification: frozenset[str]` mà không quyết định nào đọc
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:167`), cũng vậy ở `ToolSpec`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/tool_specs.py:54`). Ràng buộc: `pd_category` theo từng thuộc
  tính thay nó, có người đọc (ADR-0106 (Proposed) mục 1; failure-modes #1).
- Thang mật `internal`, `confidential`, `restricted` chấm tài liệu và trí nhớ, không chấm trường
  (`packages/python/dw_knowledge/src/dw_knowledge/contracts.py:23-37`). Ràng buộc: bảo mật trường là một trục riêng,
  không dùng lại thang này.
- Bộ che hứa "secrets/PII" nhưng chỉ che khóa bí mật theo mẫu tên
  (`packages/python/dw_observability/src/dw_observability/redaction.py:1`). Thiếu: không đâu che giá trị trường theo
  quyền của người xem.
- `studio.field_defs` giữ `pd_category`, `sensitive_type`, `subject_identifier` nhưng không có `access_mode`; custom-objects
  đẩy `access_mode`, quyền trường và `resolve_field_access` sang spec này
  (`.claude/plans/studio/custom-objects/spec.md:266`). Ràng buộc: spec này thêm `access_mode` và hàm quyết định.
- tenant-rbac tạo `studio.field_permissions` và cho `platform.effective_grants` trả `fld.<object>.<field>.read|edit`
  cộng dồn qua mọi vai (`.claude/plans/studio/tenant-rbac/issues/04-quyen-doi-tuong-va-truong-co-do-sau.md:29-39`).
  Ràng buộc: spec này đọc quyền trường hiệu lực, không tạo bảng quyền trường hay route cấp quyền.
- record-access giữ `studio.actor_boundary_fields` với `access` là `read` hay `edit` cho mỗi phiên bản agent hay quy
  trình, và ghi "field-security đọc `studio.actor_boundary_fields`" (`.claude/plans/studio/record-access/spec.md:356`).
  Ràng buộc: giao với giới hạn dữ liệu đọc bảng đó, không tự tính.
- Cấm truy cập của người vận hành theo tiền tố khóa, đã thêm `studio.`, `obj.`, `fld.`
  (`.claude/plans/studio/tenant-rbac/spec.md:30`). Ràng buộc: `studio.field_security.manage` và `fld.*` nằm ngoài tầm
  của người vận hành (ADR-0024 (Proposed)).

## Mục tiêu

### R1 — Mỗi trường Mở hoặc Bảo vệ, dữ liệu cá nhân đóng mặc định

Người dựng và quản trị viên công ty đặt mỗi trường ở `open` hoặc `secured`, với trường dữ liệu cá nhân đóng sẵn và
trường nhạy cảm không mở được (YC22).

- R1.1 `studio.field_defs` PHẢI giữ cho mỗi trường đúng một `access_mode` trong `open`, `secured`.
- R1.2 KHI một trường có `pd_category` khác `none` được tạo, `studio.field_defs` PHẢI đặt `access_mode` của trường đó
  là `secured`.
- R1.3 NẾU một lần ghi đặt `access_mode` là `open` cho một trường có `pd_category` là `sensitive`, THÌ PostgreSQL PHẢI
  từ chối với SQLSTATE 23514 `ck_fields_sensitive_is_secured` và không đổi gì.
- R1.4 KHI người giữ `studio.field_security.manage` gửi `PUT /api/v1/studio/objects/{api_name}/fields/{field}/security`
  đặt `access_mode` là `open` cho một trường `basic`, API chế độ trường PHẢI đổi `access_mode` và ghi một sự kiện audit
  `studio.field_security.changed` chỉ mang id và khóa trường trong một giao dịch.
- R1.5 NẾU người gọi không giữ `studio.field_security.manage`, THÌ API chế độ trường PHẢI trả 403 `permission_denied`
  và không đổi gì.
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
  hoặc `update` trên đối tượng, kể cả khi trường ở `secured` và chưa được cấp.

### R3 — Áp ở API bản ghi: chiếu, truy vấn, ghi và describe

API bản ghi không để lọt giá trị `hidden` qua đọc, mô tả, lọc, sắp, nhóm, đếm hay ghi (YC23).

- R3.1 KHI API bản ghi trả danh sách hay một bản ghi, API bản ghi PHẢI vắng mọi trường `hidden` với người gọi khỏi
  thân trả về và liệt kê tên các trường đó trong `hidden_fields`.
- R3.2 NẾU một cây lọc, `order_by`, nhóm hay đếm nhắc một trường `hidden` với người gọi, THÌ bộ biên dịch truy vấn PHẢI
  trả 422 `field_not_readable` trước khi chạy truy vấn, kể cả khi không bản ghi nào khớp, và không trả dòng nào.
- R3.3 NẾU một lần ghi đặt giá trị cho một trường mà quyết định truy cập trường trả `read` hay `hidden` cho người gọi,
  THÌ adapter bản ghi PHẢI trả 403 `field_not_editable` trỏ tới đúng trường đó và không đổi bản ghi.
- R3.4 KHI API bản ghi trả `describe`, API bản ghi PHẢI vắng mọi trường `hidden` với người gọi và đánh dấu mỗi trường
  còn lại là `read` hay `edit`.

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
- R4.5 KHI một quy trình mở một phê duyệt tham chiếu các trường, quy trình PHẢI chỉ chọn người duyệt giữ `Xem` trên mọi
  trường mà nội dung phê duyệt tham chiếu.
- R4.6 KHI lịch sử chạy hiện đầu vào và đầu ra của một bước, lịch sử chạy PHẢI hiện tên trường và lấy giá trị sống theo
  quyền của người xem, không giá trị đóng dấu lúc lượt chạy chạy.

### R5 — Một quyết định cho mọi đường

Thêm một đường ra giá trị bản ghi mà không gọi quyết định truy cập trường là một lỗ hổng, và adapter bản ghi là nơi
duy nhất đọc giá trị bản ghi (YC23).

- R5.1 Mọi đường phát một giá trị trường ra ngoài lượt chạy PHẢI lấy kết quả từ quyết định truy cập trường, không tự
  quyết định trường nào hiện.
- R5.2 Ngoài adapter bản ghi, không mô-đun nào PHẢI đọc bảng `studio.records` hay một cột slot của nó.

## Trong phạm vi

- Cột `studio.field_defs.access_mode` với `ck_fields_access_mode`, `ck_fields_sensitive_is_secured`, và trigger đặt
  `access_mode = 'secured'` khi `pd_category <> 'none'` lúc tạo trường.
- Hàm thuần `resolve_field_access(principal_grants, object_security, boundary) -> FieldAccess` và helper chiếu
  `visible_fields(principal, object)` trong gói truy cập Studio; kiểu `FieldAccess` (map trường sang `hidden`, `read`,
  `edit` kèm `fls_version`).
- Route `PUT /api/v1/studio/objects/{api_name}/fields/{field}/security`; khóa quyền `studio.field_security.manage`
  (loại `tenant`) đăng ký trong migration của spec này; audit và outbox `studio.field_security.changed`.
- Lớp áp `FieldAccess` trong adapter bản ghi và bộ biên dịch truy vấn (chọn cột đọc được, từ chối lọc hay sắp trên
  trường ẩn trước SQL, từ chối ghi theo trường, trả `hidden_fields`), trong bộ dựng lược đồ công cụ đối tượng và chiếu
  đầu ra công cụ, trong bộ dựng chuỗi mẫu `{{...}}`, trong bộ dựng nội dung phê duyệt và bộ chọn người duyệt, và trong
  lịch sử chạy.
- Component che giá trị `@dw/ui` ("Đã ẩn" kèm khóa) mà màn danh sách và màn bản ghi của custom-objects dùng.
- Test kiến trúc: chỉ adapter bản ghi đọc giá trị bản ghi và cột slot.

## Ngoài phạm vi

| Việc                                                                                                           | Vì sao                                                                                                | Chủ                          |
| -------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ---------------------------- |
| Nội dung chỉ mục truy xuất chỉ gồm trường được phép; `fls_version` đánh chỉ mục lại                            | Chỉ mục truy xuất đến cùng knowledge; `fls_version` theo object (ADR-0106 (Proposed) mục 4)           | field-security, đợt sau (W2) |
| Màn cấu hình bảo mật trường (ma trận vai × trường), "Xem như vai"                                              | Cần đo hiệu năng ma trận ở 320 px; W1 giao route và hàm trước                                         | field-security, đợt sau (W2) |
| Export, lịch sử bản ghi, webhook theo quyền người xem lúc gửi                                                  | Cần tác vụ nền export và endpoint webhook; chiếu theo principal của endpoint                          | field-security, đợt sau (W2) |
| Công thức thừa hưởng mức chặt nhất; audit `studio.record.sensitive_read`; người thứ hai cho cấp quyền nhạy cảm | Trường công thức cần CEL; audit đọc nhạy cảm và người thứ hai là v1.5 (ADR-0106 (Proposed) mục 5)     | field-security, đợt sau (W2) |
| Che một phần (bốn số cuối) và quyền "xem không che"                                                            | Cần một trục quyền mới; chưa có nhu cầu ở lát Marketing                                               | field-security, đợt sau (W3) |
| Không giá trị trường trong telemetry, log, audit và lỗi                                                        | Một chủ cho "không nội dung" dùng cùng hàm này (packet không cắt ticket riêng)                        | telemetry-and-audit          |
| `studio.field_permissions`; route cấp `fld.*` cho vai; chống cấp vượt quyền mình                               | Quyền trường trong vai và chống leo thang có một chủ (ADR-0104 (Proposed), ADR-0106 (Proposed) mục 3) | tenant-rbac (R9.5, R9.6)     |
| Danh mục `pd_category`, `sensitive_type`, `subject_identifier`; yêu cầu chủ thể dữ liệu; phát hiện Presidio    | Từ vựng dữ liệu cá nhân và DSR có một chủ (ADR-0106 (Proposed) mục 7, 9)                              | compliance-pdpl              |
| Cột `pd_category`, `sensitive_type`, `subject_identifier` trên `studio.field_defs`                             | Định nghĩa trường có một chủ (custom-objects R2.2)                                                    | custom-objects               |
| Che số điện thoại, email trong văn bản tự do (lời nhắn, email)                                                 | Che văn bản tự do là Presidio, không phải quyết định trường (ADR-0106 (Proposed) mục 9)               | compliance-pdpl              |
| Ẩn hay bắt buộc trường theo bố cục hay workspace                                                               | Overlay hiển thị, không phải kiểm soát truy cập                                                       | custom-objects               |
| Quyền trên bản ghi (ai thấy bản ghi nào)                                                                       | Quyền trên bản ghi có một chủ (ADR-0105 (Proposed))                                                   | record-access                |
| Bảo mật trường bằng quyền cột của PostgreSQL                                                                   | Quyền cột theo role DB, một `dw_app` cho mọi người; che cần giá trị (ADR-0106 (Proposed))             | không làm                    |

## Dữ liệu

- `studio.field_defs` (custom-objects ticket 02 tạo): spec này thêm `access_mode text NOT NULL DEFAULT 'open'` với
  `ck_fields_access_mode CHECK (access_mode IN ('open','secured'))`; `ck_fields_sensitive_is_secured`
  `CHECK (pd_category <> 'sensitive' OR access_mode = 'secured')`; trigger `BEFORE INSERT` đặt `access_mode = 'secured'`
  khi `pd_category <> 'none'`. `dw_app` UPDATE thêm cột `access_mode` trong tập cột định nghĩa được sửa.
- Thay đổi `access_mode` tăng phiên bản quyền của tenant (`platform.bump_access_version()` của tenant-rbac ticket 02)
  qua trigger trên `studio.field_defs`, để quyết định trường đọc lại từ câu lệnh kế tiếp (R1.6).
- Không bảng mới: quyền trường ở `studio.field_permissions` của tenant-rbac; `pd_category` và họ hàng ở
  `studio.field_defs` của custom-objects; giới hạn trường ở `studio.actor_boundary_fields` của record-access.

## API

- `PUT /api/v1/studio/objects/{api_name}/fields/{field}/security`: khóa `studio.field_security.manage` mức `tenant`,
  `Idempotency-Key` (app-standards R2.1), thân `{"access_mode": "open" | "secured"}`; 200 với `access_mode` và
  `fls_version` mới; 403 `permission_denied`; 404 khi đối tượng hay trường không có trong tenant người gọi; 422
  `sensitive_field_cannot_open` khi mở một trường nhạy cảm; problem+json theo app-standards R1.
- Cấp `fld.<object>.<field>.read|edit` cho vai đi qua `PUT /api/v1/admin/roles/{role_id}/permissions` của tenant-rbac
  ticket 04 (`field_permissions: [{field_id, access}]`), không qua route của spec này.

## Màn hình

- Component `@dw/ui` che giá trị: khi quyết định truy cập trường trả `hidden`, màn bản ghi và danh sách hiện `Đã ẩn`
  kèm biểu tượng khóa, không ô trống (custom-objects R10.3 dùng component này).

## Kiểm soát

| #    | Kiểm soát                                                       | Yêu cầu          | Test âm                                                                                                                                                                                                        |
| ---- | --------------------------------------------------------------- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FS1  | Dữ liệu cá nhân đóng mặc định; trường `secured` ẩn nếu chưa cấp | R1.2, R2.3       | trường `pd_category = 'basic'` chưa cấp → quyết định trả `hidden`, GET không có giá trị, `hidden_fields` có tên, lược đồ công cụ không có; đổi mặc định của `pd` khác `none` sang `open` → đỏ                  |
| FS2  | Một quyết định cho mọi đường; chỉ adapter đọc giá trị           | R5.1, R5.2       | MP6: gỡ áp quyết định ở một đường (chiếu REST, lược đồ công cụ, chuỗi mẫu, phê duyệt, lịch sử chạy) → test rò của đúng đường đó đỏ; mô-đun ngoài adapter đọc `studio.records` hay cột slot → test kiến trúc đỏ |
| FS3  | Không oracle qua lọc, sắp, nhóm, đếm                            | R3.2             | lọc theo `phone` ẩn → 422 `field_not_readable` cả khi 0 bản ghi khớp; sắp theo trường ẩn → 422; gỡ kiểm trong bộ biên dịch → đỏ                                                                                |
| FS4  | Ghi trường không sửa được bị từ chối theo trường                | R3.3             | `PATCH {status, phone}` khi `phone` chỉ `read` → 403 `field_not_editable`, `status` không đổi; gỡ kiểm theo trường → đỏ                                                                                        |
| FS5  | API không trả giá trị `hidden`                                  | R3.1, R3.4       | quét JSON của list, get, describe → không có giá trị đã gieo của trường ẩn, mọi trường ẩn có tên trong `hidden_fields`; gỡ chiếu cột → đỏ                                                                      |
| FS6  | Chuỗi mẫu không lộ trường ẩn                                    | R4.3             | `{{lead.phone}}` khi chủ thể chạy không đọc được → bước lỗi `template_field_hidden`, 0 lần gửi; gỡ kiểm mẫu → đỏ                                                                                               |
| FS7  | Trường duy nhất đọc được với người ghi                          | R2.6             | ẩn trường duy nhất với vai có quyền `create` → quyết định trả `read`; lỗi trùng của custom-objects không có giá trị, không id bản ghi kia; gỡ ngoại lệ trường duy nhất → đỏ                                    |
| FS8  | Agent và quy trình giao với giới hạn dữ liệu                    | R2.5, R4.1, R4.2 | lược đồ công cụ và đầu ra không có trường ngoài giới hạn dữ liệu hay ngoài quyền chủ thể; mở rộng giới hạn dữ liệu của phiên bản → test đỏ                                                                     |
| FS9  | Phê duyệt và lịch sử chạy che theo người xem                    | R4.4, R4.6       | người duyệt không có `Xem` trên `phone` thấy `Đã ẩn` trong nội dung tin nhắn chờ duyệt và trong lịch sử chạy; đóng dấu giá trị lúc lượt chạy chạy → đỏ                                                         |
| FS10 | Người duyệt giữ quyền đọc trường nội dung tham chiếu            | R4.5             | phê duyệt tham chiếu `phone` → chỉ người giữ `fld.lead.phone.read` được chọn; một người thiếu quyền được chọn → test đỏ                                                                                        |
| FS11 | Nhạy cảm luôn `secured`                                         | R1.3             | `UPDATE studio.field_defs SET access_mode = 'open'` cho trường nhạy cảm → 23514 `ck_fields_sensitive_is_secured`; gỡ CHECK → đỏ                                                                                |
| FS12 | Đổi `access_mode` chỉ với quyền, có audit, hiệu lực ngay        | R1.4, R1.5, R1.6 | `PUT .../security` không có `studio.field_security.manage` → 403, không đổi, 0 audit; đổi xong → yêu cầu kế tiếp dùng giá trị mới; gỡ tăng phiên bản → đỏ                                                      |

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
  `resolve_field_access` (`custom-objects:R3.2`, `custom-objects:R6.6`, `custom-objects:R8.4`, ticket 04).
- tenant-rbac: `platform.effective_grants` trả `fld.<object>.<field>.read|edit` cộng dồn (`tenant-rbac:R9.6`), chống
  cấp quyền trường vượt quyền mình (`tenant-rbac:R9.5`), và `platform.bump_access_version()` (ticket 02, 04); danh mục
  quyền nhận khóa `studio.field_security.manage` (`tenant-rbac:R1.1`); cấm khóa `studio.`, `fld.` khỏi người vận hành
  (`tenant-rbac:R1.5`).
- record-access: `studio.actor_boundary_fields` và ngữ cảnh actor (`app.actor_kind`, `app.boundary_id`) ở mọi cửa
  (`record-access:R6.4`, ticket 04) cho giao với giới hạn dữ liệu.
- compliance-pdpl: `dw_kernel.personal_data` là chủ của `pd_category`, `sensitive_type`, `subject_identifier`
  (`.claude/plans/studio/compliance-pdpl/issues/01-tu-vung-du-lieu-ca-nhan.md`, ADR-0106 (Proposed) mục 1).
- tools-and-skills: lược đồ và đầu ra công cụ đối tượng gọi quyết định trường
  (`.claude/plans/studio/tools-and-skills/issues/03-cong-cu-du-lieu-doi-tuong.md`).
- workflow-nodes: bộ dựng chuỗi mẫu `{{...}}` và bước tool-call, human-approval gọi quyết định trường
  (`.claude/plans/studio/workflow-nodes/issues/03-pham-vi-bien-va-buoc-logic.md`,
  `.claude/plans/studio/workflow-nodes/issues/06-tool-call-va-human-approval.md`).
- telemetry-and-audit: lịch sử chạy theo bước lấy giá trị trường sống theo người xem
  (`.claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md`).
- app-standards: problem+json (R1), `Idempotency-Key` gắn người gọi (R2) cho route cấu hình.
- Kiểm lại khi: ADR-0106 (Proposed) đổi trạng thái, `platform.effective_grants` hay `studio.actor_boundary_fields` đổi
  hình, hay trả lời DO-34, DO-36 → ticket 01, 02.

## Câu hỏi còn mở

- Q1. DO-34: dữ liệu cá nhân cơ bản, kể cả họ tên, có `secured` mặc định và admin mở được kèm audit; đọc giá trị nhạy
  cảm có phải ghi một sự kiện audit mỗi phản hồi chỉ gồm id và tên trường; cấp `Xem` trên trường nhạy cảm có cần người
  thứ hai (v1.5)? Chủ: luật sư và người yêu cầu. Chặn: R1.2, R2.3.

## Quyết định

- 22/10/2026 (người yêu cầu): D3: quyết định trường áp cả cho agent và kết quả tìm kiếm; D4: lát Marketing là ví dụ
  chạy, che điện thoại, email, họ tên của lead. Sửa: R1, R2, R4.
- 23/10/2026 (agent, tạm): theo ADR-0106 (Proposed) mục 2, đổi `access_mode` của một trường `basic` chỉ cần người giữ
  `studio.field_security.manage` cộng audit, không phải maker-checker của ADR-0110 (Proposed); cấp `fld.*` cho vai vẫn
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
  trường bằng một hàm theo ADR-0106 (Proposed) — là Cải tiến, không phải mẫu học theo hay mã của họ. Không đổi: R2,
  R4.1.

## Danh sách ticket

| #   | Ticket                                                                                                     |
| --- | ---------------------------------------------------------------------------------------------------------- |
| 01  | [Mô hình bảo mật trường và hàm quyết định duy nhất visible_fields](issues/01-mo-hinh-bao-mat-truong.md)    |
| 02  | [Áp bảo mật trường ở API bản ghi, agent, workflow, phê duyệt và lịch sử chạy](issues/02-ap-o-moi-duong.md) |
