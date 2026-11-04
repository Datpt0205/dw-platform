# Bảo mật trường: Mở hoặc Bảo vệ, cấp theo vai, một hàm cho mọi đường

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: agent, tạm theo ủy quyền 4/11/2026
Sẵn sàng: ĐẠT (4/11/2026; 0 CRITICAL, 0 HIGH; ticket 01-02)

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
- Đọc thêm ở `aa630da` ngày 4/11/2026: custom-objects/02 đã dựng (`65bddef`). Mô hình tài liệu `dw.object/v1` có
  `access_mode` với mặc định `secured` khi `pd_category` khác `none`
  (`packages/python/dw_studio/src/dw_studio/records/domain/document.py:157`), trình kiểm từ chối trường nhạy cảm `open`
  và trường mới có dữ liệu cá nhân `open` (`packages/python/dw_studio/src/dw_studio/records/domain/rules.py:225`), bộ so
  sánh đánh dấu `open` sang `secured` là chỉ siết (`packages/python/dw_studio/src/dw_studio/records/domain/rules.py:403`);
  `name_field` không mang `access_mode`. Thiếu: `FieldDefinition` và các thuộc tính sửa được của móc không có
  `access_mode` (`packages/python/dw_studio/src/dw_studio/records/application/metadata.py:53`), nên chưa gì ghi cột.
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
- R1.7 KHI revision thêm cột `access_mode` chạy trên các dòng `studio.field_defs` đã có, revision đó PHẢI đặt `secured`
  cho mọi dòng có `pd_category` khác `none` và `open` cho dòng còn lại, trước khi thêm `ck_field_defs_sensitive_is_secured`.
- R1.8 KHI một phiên bản `dw.object/v1` lên Đang dùng, dịch vụ metadata PHẢI ghi `access_mode` của mọi trường theo tài
  liệu đã parse, và của trường `name` là `secured` khi `pd_category` của `name_field` khác `none`, `open` khi bằng
  `none`, vì `name_field` không mang `access_mode`; nâng `pd_category` của `name_field` từ `none` vì thế đóng `name`.

### R2 — Một quyết định trường duy nhất, thuần và có phiên bản

Mọi đường dùng cùng một quyết định cho "người gọi thấy hay sửa trường nào", tính từ `access_mode`, `pd_category`,
quyền trường hiệu lực của người gọi và giới hạn dữ liệu của lượt chạy (YC22, YC23).

- R2.1 Quyết định truy cập trường PHẢI trả cho mỗi trường của một đối tượng đúng một giá trị trong `hidden`, `read`,
  `edit`, kèm phiên bản metadata trường đã dùng.
- R2.2 ĐỐI VỚI một trường `open`, quyết định truy cập trường PHẢI trả `read` cho người gọi giữ `obj.<object>.read` và
  `edit` cho người gọi giữ khóa của hành động ghi đang xét (`obj.<object>.update`, hay `obj.<object>.create` ở R2.7);
  tầm tới từng bản ghi là của RLS (ADR-0105 (Accepted)), không của quyết định này, nên `FieldAccess` tính theo đối
  tượng, không theo bản ghi.
- R2.3 ĐỐI VỚI một trường `secured`, quyết định truy cập trường PHẢI trả `hidden` cho vai không được cấp `Xem` hay
  `Xem và sửa` trên trường đó.
- R2.4 KHI một người giữ `fld.<object>.<field>.read` từ một vai và `fld.<object>.<field>.edit` từ một vai khác, quyết
  định truy cập trường PHẢI trả `edit` cho trường đó khi người đó giữ khóa của hành động ghi đang xét, và `read` khi
  không; `fld.*` không có mức riêng (luôn `tenant`, tenant-rbac/04 bước 5) và chỉ tính khi người đó giữ
  `obj.<object>.read` (ADR-0106 (Accepted) quyết 3).
- R2.5 ĐỐI VỚI một lượt chạy loại actor `agent` hay `workflow`, quyết định truy cập trường PHẢI trả giao của quyền
  trường của chủ thể với quyền trường của mọi giới hạn dữ liệu trong chuỗi `studio.boundary_chain` của lượt
  (record-access/04 bước 3), không bao giờ rộng hơn một trong hai; R2.6 áp ở phía chủ thể trước phép giao, nên giới hạn
  bỏ một trường duy nhất thì trường đó `hidden` với lượt.
- R2.6 ĐỐI VỚI một trường duy nhất, quyết định truy cập trường PHẢI trả ít nhất `read` cho mọi vai có quyền `create`
  hoặc `update` trên đối tượng, kể cả khi trường ở `secured` và chưa được cấp, nên một vai cần ẩn trường duy nhất thì
  không được giữ `create` hay `update` trên đối tượng đó.
- R2.7 KHI bên gọi hỏi quyết định truy cập trường cho hành động `create`, quyết định truy cập trường PHẢI trả `edit` cho
  trường mà R2.2 tới R2.6 cho ghi với khóa `obj.<object>.create` thay `obj.<object>.update`, không đòi tầm sửa trên bản
  ghi vì bản ghi chưa có (custom-objects/03 bước 7a (r)).
- R2.8 NẾU loại actor của lượt là `agent` hay `workflow` mà chuỗi giới hạn đọc ra rỗng, một mắt xích không đọc được,
  hay một trường không có dòng `studio.actor_boundary_fields` ở mọi mắt xích, THÌ quyết định truy cập trường PHẢI trả
  `hidden` cho trường đó, kể cả trường `open`, và không bao giờ coi lượt như actor `user`.
- R2.9 Quyết định truy cập trường PHẢI được tính trong giao dịch của mỗi yêu cầu hay mỗi lời gọi công cụ, từ
  `access_mode` sống của `studio.field_defs`, quyền hiệu lực sống của công ty đang gắn và giới hạn của lượt, không từ
  bản kê lượt chạy và không từ một bộ đệm sống quá giao dịch, nên một trường đóng hay một quyền thu sau khi lượt bắt
  đầu có hiệu lực từ lời gọi kế tiếp.
- R2.10 NẾU một người là thành viên của hai công ty và chỉ giữ `fld.<object>.<field>.read` ở công ty A, THÌ quyết định
  truy cập trường ở công ty B PHẢI trả `hidden` cho trường cùng tên của B.

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
- R4.3 NẾU một chuỗi mẫu `{{...}}` hay một Biểu thức của một bước quy trình nhắc một trường mà quyết định truy cập trường
  của lượt (chủ thể giao giới hạn, R2.5) trả `hidden`, THÌ bước đó PHẢI lỗi `field_hidden` (workflow-nodes:R4.4,
  ADR-0106 (Accepted) sửa 4/11/2026) và không gửi gì.
- R4.4 KHI trang duyệt dựng nội dung một phê duyệt, trang duyệt PHẢI lấy giá trị sống của các trường mà bước hiển thị
  theo quyền của người xem và hiện `Đã ẩn` cho trường người xem không đọc được; đối số đã render của chủ thể mà
  workflow-nodes/06 lưu chỉ hiện cho người qua `payload_guards`, tức đọc được mọi trường đóng dấu.
- R4.5 KHI một bước phê duyệt mở một phê duyệt tham chiếu các trường, bộ chọn người duyệt PHẢI chỉ trả người giữ `Xem`
  trên mọi trường mà bước đó đóng dấu ở `payload.stamped_fields` (dạng `<object>.<field>`, workflow-nodes/06), theo
  cùng hàm mà R4.7 áp ở lúc quyết.
- R4.6 KHI lịch sử chạy hiện đầu vào và đầu ra của một bước, lịch sử chạy PHẢI che lại theo quyền của người xem lúc
  đọc, bằng quyết định truy cập trường, payload mà telemetry-and-audit đã lưu che lúc ghi (ADR-0106 (Accepted) quyết 4
  sửa 27/10/2026; ADR-0122 (Accepted) quyết 4; telemetry-and-audit:R3.3, R3.14).
- R4.7 NẾU người quyết một phê duyệt `studio.step.approval` không giữ `Xem` trên mọi trường mà bước phê duyệt đóng dấu
  ở lúc quyết, THÌ guard quyết định của loại đó PHẢI trả 403 và không ghi quyết định.
- R4.8 NẾU tham số lọc, sắp, nhóm hay đếm mà model đưa cho một công cụ đối tượng nhắc một trường `hidden` với giao của
  chủ thể và giới hạn, THÌ công cụ đối tượng PHẢI từ chối với `field_not_readable` trước khi chạy truy vấn và không trả
  dòng nào, qua cùng bộ biên dịch truy vấn của R3.2.

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
- Hàm thuần `resolve_field_access(principal_grants, object_security, boundary, action) -> FieldAccess` và helper chiếu
  `visible_fields(principal, object)` trong gói truy cập Studio; kiểu `FieldAccess` (map trường sang `hidden`, `read`,
  `edit` kèm `fls_version`, là `schema_version` của đối tượng); helper thuần `reads_all(accesses, stamped_fields)` cho
  luật người duyệt (R4.5, R4.7); một dịch vụ đọc đầu vào của hàm trong giao dịch của bên gọi (R2.9).
- Lớp áp `FieldAccess` trong adapter bản ghi và bộ biên dịch truy vấn (chọn cột đọc được, từ chối lọc hay sắp trên
  trường ẩn trước SQL, từ chối ghi theo trường, trả `hidden_fields`), trong bộ dựng lược đồ công cụ đối tượng và chiếu
  đầu ra công cụ, trong bộ dựng chuỗi mẫu `{{...}}`, trong bộ dựng nội dung phê duyệt và bộ chọn người duyệt, trong điều
  kiện đọc trường của `decision_guards["studio.step.approval"]` (DO-36), và trong lịch sử chạy.
- Component che giá trị `@dw/ui` ("Đã ẩn" kèm khóa) mà màn danh sách và màn bản ghi của custom-objects dùng.
- Test kiến trúc: chỉ adapter bản ghi đọc giá trị bản ghi và cột slot.

## Ngoài phạm vi

| Việc                                                                                                                                                                                                                                                                                                        | Vì sao                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | Chủ                                      |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| Nội dung chỉ mục truy xuất chỉ gồm trường được phép; `fls_version` đánh chỉ mục lại                                                                                                                                                                                                                         | Chỉ mục truy xuất đến cùng knowledge; `fls_version` theo object (ADR-0106 (Accepted) mục 4)                                                                                                                                                                                                                                                                                                                                                                                                                          | field-security, đợt sau (W2)             |
| Màn cấu hình bảo mật trường (ma trận vai × trường), "Xem như vai"                                                                                                                                                                                                                                           | Cần đo hiệu năng ma trận ở 320 px; W1 giao route và hàm trước                                                                                                                                                                                                                                                                                                                                                                                                                                                        | field-security, đợt sau (W2)             |
| Export, lịch sử bản ghi, webhook theo quyền người xem lúc gửi                                                                                                                                                                                                                                               | Cần tác vụ nền export và endpoint webhook; chiếu theo principal của endpoint                                                                                                                                                                                                                                                                                                                                                                                                                                         | field-security, đợt sau (W2)             |
| Công thức thừa hưởng mức chặt nhất; audit `pd.read` cho phản hồi mang giá trị nhạy cảm, chỉ id bản ghi và tên trường                                                                                                                                                                                        | Trường công thức cần CEL; audit đọc nhạy cảm theo từng phản hồi là YC24 (W2), tên sự kiện theo ADR-0106 (Accepted) quyết 5                                                                                                                                                                                                                                                                                                                                                                                           | field-security, đợt sau (W2)             |
| W2: kiểm người nhận ở mọi đích (thông báo cho thành viên, bước agent, tin nội bộ, lookup, tìm kiếm) theo tập nguồn gốc trường mà Phân tích năng lực tính lúc gửi kiểm định, đầu ra `ai.llm` và agent mang hợp tập nguồn gốc của mọi đầu vào; che `name` của lookup theo quyền trường ở bản ghi đích (YC113) | V4.40, trước khi các đích W2 ra: ở W1 R4.3 kiểm chuỗi mẫu theo chủ thể chạy và các đích đó chưa có, còn luật riêng của lát thí điểm giữ W1 (marketing-pilot); ADR-0106 (Accepted) quyết 4; thử bằng đột biến từng đích kiểu MP6 (gỡ kiểm ở một đích thì test rò của đích đó đỏ) và 100% quy trình mẫu của gói Marketing qua được gửi kiểm định; tính nguồn gốc là của compliance-pdpl, luật không ghi xuống ở Bước `data.object.*` là của workflow-nodes, `field_id` trên `studio.record_terms` là của record-access | field-security, đợt sau (W2)             |
| Che một phần (bốn số cuối) và quyền "xem không che"                                                                                                                                                                                                                                                         | Cần một trục quyền mới; chưa có nhu cầu ở lát Marketing                                                                                                                                                                                                                                                                                                                                                                                                                                                              | field-security, đợt sau (W3)             |
| Không giá trị trường trong telemetry, log, audit và lỗi                                                                                                                                                                                                                                                     | Một chủ cho "không nội dung" dùng cùng hàm này (packet không cắt ticket riêng)                                                                                                                                                                                                                                                                                                                                                                                                                                       | telemetry-and-audit                      |
| `studio.field_permissions`; route cấp `fld.*` cho vai; chống cấp vượt quyền mình; người thứ hai khi cấp `fld.*`; người cấp `fld.*` đầu tiên                                                                                                                                                                 | Quyền trường trong vai và chống leo thang có một chủ (ADR-0104 (Accepted), ADR-0106 (Accepted) mục 3); cấp `fld.*` là thay đổi vai trò hai người từ W1, kể cả trường nhạy cảm (DO-09.2); `tenant_owner` giữ mọi `fld.*` qua quyền tính động (N1)                                                                                                                                                                                                                                                                     | tenant-rbac (R6.8, R7, R9.5, R9.6, R9.7) |
| Đổi `access_mode` qua phát hành `dw.object/v1`: mở trường `basic` cần người thứ hai, đóng trường một người cộng audit                                                                                                                                                                                       | Một đường ghi cho định nghĩa đối tượng (`D:field-security:R1.4~requirements.md:D11`)                                                                                                                                                                                                                                                                                                                                                                                                                                 | custom-objects (R1.2, R1.7, R2.5)        |
| Danh mục `pd_category`, `sensitive_type`, `subject_identifier`; yêu cầu chủ thể dữ liệu; phát hiện Presidio                                                                                                                                                                                                 | Từ vựng dữ liệu cá nhân và DSR có một chủ (ADR-0106 (Accepted) mục 7, 9)                                                                                                                                                                                                                                                                                                                                                                                                                                             | compliance-pdpl                          |
| Cột `pd_category`, `sensitive_type`, `subject_identifier` trên `studio.field_defs`                                                                                                                                                                                                                          | Định nghĩa trường có một chủ (custom-objects R2.2)                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | custom-objects                           |
| Che số điện thoại, email trong văn bản tự do (lời nhắn, email)                                                                                                                                                                                                                                              | Che văn bản tự do là Presidio, không phải quyết định trường (ADR-0106 (Accepted) mục 9)                                                                                                                                                                                                                                                                                                                                                                                                                              | compliance-pdpl                          |
| Ẩn hay bắt buộc trường theo bố cục hay workspace                                                                                                                                                                                                                                                            | Overlay hiển thị, không phải kiểm soát truy cập                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | custom-objects                           |
| Quyền trên bản ghi (ai thấy bản ghi nào)                                                                                                                                                                                                                                                                    | Quyền trên bản ghi có một chủ (ADR-0105 (Accepted))                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | record-access                            |
| Che lại body phát lại theo quyền trường hiện tại khi phát lại ở lớp HTTP trong 24 giờ (app-standards R2.17)                                                                                                                                                                                                 | Rủi ro Đạt nhận ngày 27/10/2026 (app-standards, Quyết định 27/10/2026): body chỉ trả cho đúng người gọi đã nhận nó và quyền của route được kiểm lại; route trả giá trị `sensitive` không lưu body (app-standards R2.36, custom-objects)                                                                                                                                                                                                                                                                              | không làm ở W1                           |
| Bảo mật trường bằng quyền cột của PostgreSQL                                                                                                                                                                                                                                                                | Quyền cột theo role DB, một `dw_app` cho mọi người; che cần giá trị (ADR-0106 (Accepted))                                                                                                                                                                                                                                                                                                                                                                                                                            | không làm                                |

## Dữ liệu

- `studio.field_defs` (custom-objects ticket 02 tạo): spec này thêm `access_mode text NOT NULL DEFAULT 'open'` với
  `ck_field_defs_access_mode CHECK (access_mode IN ('open','secured'))`; `ck_field_defs_sensitive_is_secured`
  `CHECK (pd_category <> 'sensitive' OR access_mode = 'secured')`; trigger `BEFORE INSERT` đặt `access_mode = 'secured'`
  khi `pd_category <> 'none'`. Revision điền lại các dòng đã có theo R1.7 trước khi thêm CHECK. `dw_app` UPDATE thêm cột
  `access_mode` trong tập cột định nghĩa được sửa; người ghi duy nhất là dịch vụ metadata khi một phiên bản
  `dw.object/v1` lên Đang dùng (R1.8).
- Thay đổi `access_mode` tăng phiên bản quyền của tenant (`platform.bump_access_version()` của tenant-rbac ticket 02)
  qua constraint trigger hoãn tới commit `trg_z_bump_access_version_access_mode AFTER UPDATE OF access_mode` trên `studio.field_defs`, tên xếp cuối như mọi
  trigger cùng hàm (`db/migrations/versions/b5677d345bc1_tenant_roles.py:1153`), để quyết định trường đọc lại từ câu
  lệnh kế tiếp (R1.6).
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

| #    | Kiểm soát                                                       | Yêu cầu                | Test âm                                                                                                                                                                                                                                    |
| ---- | --------------------------------------------------------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| FS1  | Dữ liệu cá nhân đóng mặc định; trường `secured` ẩn nếu chưa cấp | R1.2, R2.3             | trường `pd_category = 'basic'` chưa cấp → quyết định trả `hidden`, GET không có giá trị, `hidden_fields` có tên, lược đồ công cụ không có; đổi mặc định của `pd` khác `none` sang `open` → đỏ                                              |
| FS2  | Một quyết định cho mọi đường; chỉ adapter đọc giá trị           | R5.1, R5.2             | MP6: gỡ áp quyết định ở một đường (chiếu REST, lược đồ công cụ, chuỗi mẫu, phê duyệt, lịch sử chạy) → test rò của đúng đường đó đỏ; mô-đun ngoài adapter đọc `studio.records` hay cột slot → test kiến trúc đỏ                             |
| FS3  | Không oracle qua lọc, sắp, nhóm, đếm                            | R3.2                   | lọc theo `phone` ẩn → 422 `validation_failed` với `errors[].code` `field_not_readable` cả khi 0 bản ghi khớp; sắp theo trường ẩn → 422; gỡ kiểm trong bộ biên dịch → đỏ                                                                    |
| FS4  | Ghi trường không sửa được bị từ chối theo trường                | R3.3                   | `PATCH {status, phone}` khi `phone` chỉ `read` → 403 `field_not_editable`, `status` không đổi; gỡ kiểm theo trường → đỏ                                                                                                                    |
| FS5  | API không trả giá trị `hidden`                                  | R3.1, R3.4             | quét JSON của list, get, describe → không có giá trị đã gieo của trường ẩn, mọi trường ẩn (cả trường trống) có tên trong `hidden_fields` và có `access: hidden` trong describe; gỡ chiếu cột → đỏ                                          |
| FS6  | Chuỗi mẫu không lộ trường ẩn                                    | R4.3                   | `{{lead.phone}}` khi chủ thể chạy không đọc được, hay khi giới hạn của lượt bỏ `phone` → bước lỗi `field_hidden`, 0 lần gửi; gỡ kiểm mẫu → đỏ                                                                                              |
| FS7  | Trường duy nhất đọc được với người ghi                          | R2.6                   | ẩn trường duy nhất với vai có quyền `create` → quyết định trả `read`; lỗi trùng của custom-objects không có giá trị, không id bản ghi kia; gỡ ngoại lệ trường duy nhất → đỏ                                                                |
| FS8  | Agent và quy trình giao với giới hạn dữ liệu                    | R2.5, R2.8, R4.1, R4.2 | lược đồ công cụ và đầu ra không có trường ngoài giới hạn dữ liệu hay ngoài quyền chủ thể; lượt `agent` có chuỗi giới hạn rỗng → mọi trường `hidden`; mở rộng giới hạn dữ liệu của phiên bản, hay coi chuỗi rỗng như actor `user` → test đỏ |
| FS9  | Phê duyệt và lịch sử chạy che theo người xem                    | R4.4, R4.6             | người duyệt không có `Xem` trên `phone` thấy `Đã ẩn` cho trường hiển thị của tin nhắn chờ duyệt; người xem lịch sử chạy không có `Xem` trên `phone` thấy `Đã ẩn` tại giá trị `phone` đã lưu; gỡ che lúc đọc → đỏ                           |
| FS10 | Người duyệt giữ quyền đọc trường nội dung tham chiếu            | R4.5, R4.7             | phê duyệt tham chiếu `phone` → chỉ người giữ `fld.lead.phone.read` được chọn; người mất `fld.lead.phone.read` sau khi phê duyệt mở gọi `decide` → 403, phê duyệt vẫn chờ; gỡ điều kiện khỏi guard → đỏ                                     |
| FS11 | Nhạy cảm luôn `secured`                                         | R1.3                   | `UPDATE studio.field_defs SET access_mode = 'open'` cho trường nhạy cảm → 23514 `ck_field_defs_sensitive_is_secured`; gỡ CHECK → đỏ                                                                                                        |
| FS12 | Đổi `access_mode` có hiệu lực từ câu lệnh kế tiếp               | R1.6, R2.9             | phiên bản đóng `phone` lên Đang dùng ở giao dịch A → yêu cầu đầu tiên sau đó, và lời gọi công cụ kế tiếp của một lượt đã chạy từ trước, thấy `phone` là `hidden`; gỡ trigger tăng phiên bản trên `studio.field_defs` → đỏ                  |
| FS13 | Quyền trường không đi chéo công ty                              | R2.10                  | một người là thành viên hai công ty cùng đối tượng `lead`, giữ `fld.lead.phone.read` chỉ ở A → ở B `phone` là `hidden`, GET của B không có giá trị; đọc quyền không lọc theo công ty đang gắn → đỏ                                         |
| FS14 | Không oracle qua tham số công cụ do model đưa                   | R4.8                   | công cụ đối tượng nhận lọc theo `phone` mà giới hạn bỏ → `field_not_readable`, 0 dòng; gỡ `FieldAccess` của lượt khỏi bộ biên dịch ở đường công cụ → đỏ                                                                                    |
| FS15 | Trường dữ liệu cá nhân có sẵn và trường `name` không mở lặng lẽ | R1.7, R1.8             | dòng `basic` có trước revision → sau revision là `secured`; phiên bản nâng `pd_category` của `name_field` từ `none` lên `basic` → dòng `name` là `secured`; bỏ bước điền lại hay suy ra của `name` → đỏ                                    |

## Tiêu chí thành công

- Test đầu-cuối của lát Marketing: một vai chỉ giữ `obj.lead.read` (không `create` hay `update`, nên R2.6 không áp) và
  không được cấp `fld.lead.phone.*`, `fld.lead.email.*` không thấy số điện thoại hay email của lead ở bất kỳ đường nào
  (API, describe, công cụ agent chấm điểm, chuỗi mẫu, trang duyệt, lịch sử chạy), góp vào YC23.
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
  workflow-nodes/06 sở hữu `decision_guards["studio.step.approval"]` và `payload_guards["studio.step.approval"]`, gọi
  `reads_all` của ticket 01 trên `payload.stamped_fields` (luật của R4.5, R4.7), đọc database qua guard async của
  tenant-config/05 (DO-36); ticket 02 thêm bộ lọc ứng viên của R4.5 vào ảnh chụp ứng viên của workflow-nodes/06; mã
  lỗi Bước `field_hidden` thuộc bảng mã của workflow-nodes (R4.4).
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
- 25/10/2026 (Đạt): V4.40: bảo mật trường kiểm người nhận ở mọi đích theo tập nguồn gốc trường tính lúc gửi kiểm định, và che `name` của lookup theo quyền trường ở bản ghi đích, đợt W2 trước khi các đích W2 ra (`notify.send`, `ai.agent`, tin nội bộ, lookup, tìm kiếm); ở W1 chỉ dòng Ngoài phạm vi có đợt và chủ, R4.3 giữ kiểm theo chủ thể chạy, luật riêng của lát thí điểm giữ W1 (YC113; ADR-0106 (Accepted) quyết 4). Sửa: Ngoài phạm vi.
- 4/11/2026 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` của spec và ticket 01, 02 (builder check;
  boundary walk ranh giới 1-3 và 4-6 vì ticket 01 có migration; script 24 Đạt). CRITICAL 1: R4.6 và FS9 đòi lịch sử
  chạy lấy giá trị sống, trái ADR-0106 (Accepted) quyết 4 sửa 27/10/2026 (payload lưu che lúc ghi, che lại lúc đọc,
  theo ADR-0122 (Accepted) quyết 4); R4.6 và FS9 viết lại theo ADR. Nếu sai thì: ADR-0106 (Accepted) quyết 4 đổi lại trước, rồi
  R4.6. CRITICAL 2: lược đồ công cụ "khóa theo `fls_version`" không có công ty, trái `CLAUDE.md` (cache keys), và không
  kiểm soát nào có test âm chéo công ty; nay không đệm lược đồ đã lọc (bộ đệm đầy đủ của custom-objects/03 có
  `tenant_id`), thêm R2.10 và FS13. Nếu sai thì: một bộ đệm theo người gọi có khóa gồm công ty, chủ thể, phiên bản
  quyền và giới hạn.
- 4/11/2026 (agent, theo ủy quyền 31/10/2026): cùng gate, HIGH, mỗi cái sửa theo khuyến nghị:
  (1) nhánh `create` mà custom-objects/03 bước 7a (r) cần: R2.7, tham số `action`;
  (2) `edit` chỉ khi giữ khóa `obj.*` của hành động, `read` chỉ khi giữ `obj.<object>.read`, `FieldAccess` theo đối
  tượng, tầm theo bản ghi là của RLS (ADR-0106 (Accepted) quyết 3): R2.2, R2.4;
  (3) `boundary=None` của lượt `agent` hay `workflow` mở: giao mọi mắt xích của `studio.boundary_chain`, rỗng hay thiếu
  dòng → `hidden` kể cả trường `open`: R2.5, R2.8, FS8;
  (4) R2.5 với R2.6: giới hạn thắng, R2.6 chỉ ở phía chủ thể: R2.5;
  (5) `ADD COLUMN ... DEFAULT 'open'` mở mọi trường dữ liệu cá nhân đã có, và `name` không mang `access_mode` trong tài
  liệu: R1.7, R1.8, FS15;
  (6) lượt đọc quyền sống chứ không theo bản kê, không bộ đệm quá giao dịch (quyền không phải thành phần ghim của bản
  kê, ADR-0109 (Accepted)): R2.9;
  (7) một tên lỗi `field_hidden`, cho cả chuỗi mẫu lẫn Biểu thức, trên quyết định của lượt (chủ thể giao giới hạn);
  ADR-0106 (Accepted) quyết 4 sửa 4/11/2026: R4.3, FS6;
  (8) tham số lọc do model đưa cho công cụ đối tượng qua cùng bộ biên dịch: R4.8, FS14;
  (9) luật người duyệt đọc `payload.stamped_fields` qua `reads_all` của ticket 01; guard là của workflow-nodes/06,
  ticket 02 thêm bộ lọc ứng viên; đối số đã render của chủ thể chỉ qua `payload_guards` (ADR-0106 (Accepted) sửa 4/11/2026): R4.4,
  R4.5, Phụ thuộc;
  (10) cột `data` không trả nguyên, `name` theo `FieldAccess`: ticket 02 bước 1;
  (11) một chỗ không thuần đọc đầu vào của hàm, `fls_version` là `schema_version`: Trong phạm vi, ticket 01 bước 3;
  (12) Tiêu chí thành công dùng vai chỉ `obj.lead.read`, vì R2.6 làm `phone` duy nhất hiện ra với vai có `update`.
  Nếu sai thì: lỗi lộ ra khi dựng, ghi ở Comments của ticket và sửa ở đây.
- 4/11/2026 (agent, theo ủy quyền 31/10/2026): lượt xác nhận của gate (builder check mới trên bản đã sửa) tìm 4 HIGH,
  sửa ở ticket 01 bước 3 (chi tiết ở Comments của nó): nhánh `create` không đòi `obj.<object>.read`; khóa đọc từ
  `platform.effective_grants` trong giao dịch, hợp mọi neo; `for_person` cho ứng viên duyệt; `owner`, `workspace` ngoài
  `FieldAccess`. Một phiên bản nâng `pd_category` của một trường có sẵn từ `none` mà tài liệu vẫn ghi `access_mode:
open` là một trường `basic` mở, hợp lệ vì phiên bản đó không chỉ siết nên đi qua người thứ hai (D11; bộ so sánh của
  custom-objects/02), còn tài liệu bỏ trống `access_mode` thì mặc định `secured`. Sửa của lượt này không có người đọc
  mới: nhận rủi ro (agent, theo ủy quyền 31/10/2026). Nếu sai thì: lỗi lộ ra khi dựng, ghi ở Comments và sửa ở đây.
- 4/11/2026 (agent, tạm theo ủy quyền): Duyệt cách chia ticket 01-02. Cùng lượt duyệt spec (`Duyệt:` ở đầu). Ticket 01 là mô
  hình, migration và hàm; ticket 02 là lớp áp ở mọi đường, sau mọi ticket dựng đường đó; theo `## Ủy quyền` của
  studio.md (Đạt, 31/10/2026). Nếu sai thì: Đạt duyệt lại và ticket về `needs-triage`.

## Danh sách ticket

| #   | Ticket                                                                                                     |
| --- | ---------------------------------------------------------------------------------------------------------- |
| 01  | [Mô hình bảo mật trường và hàm quyết định duy nhất visible_fields](issues/01-mo-hinh-bao-mat-truong.md)    |
| 02  | [Áp bảo mật trường ở API bản ghi, agent, workflow, phê duyệt và lịch sử chạy](issues/02-ap-o-moi-duong.md) |
