# Danh mục bước v1, ngôn ngữ biểu thức CEL và các bước con người

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Người dựng không viết mã ghép một quy trình từ các Bước. Mỗi Loại bước là mã nền tảng trong một sổ
đăng ký duy nhất, mang schema cấu hình và đầu ra, mức tác động, chính sách Khi lỗi và giới hạn; mỗi
Bước có tối đa một tác dụng phụ, đi qua đúng cửa của loại. Biểu thức và chuỗi có biến của công ty là
CEL, tính ở máy chủ sau một cổng, kiểm kiểu khi gửi kiểm định, có trần chi phí, không bao giờ chạy như mã
và không bao giờ tính trong trình duyệt. Các Bước phê duyệt là cổng do máy chủ thực thi. Lát Tiếp nhận
lead của Marketing (D4) cần sáu lát bước trong P1; danh mục đầy đủ mà ADR-0112 (Accepted) quyết 2 đếm là W2
trở đi.

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- Chưa có loại bước, ngôn ngữ biểu thức, sơ đồ hay việc cần làm nào của Studio; các bước dựng lại thứ
  đã có kiểm thử. `ToolExecutor.execute(...)` phân giải công cụ theo `(name, version)`, kiểm
  `required_scopes`, hỏi chính sách duyệt và từ chối lệnh gọi `external` hay `critical` không có khoá
  chống lặp (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:95`). Ràng buộc: bước
  gọi công cụ đi qua cửa này, không tự gọi nhà cung cấp.
- Vốn từ mức tác động là `SideEffectLevel = Literal["none", "internal", "external", "critical"]`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:19`). Ràng buộc: loại bước dùng
  lại nguyên vốn từ này.
- `platform.approval_requests` có `approval_type`, `requested_by`, `required_scope`, `payload`,
  `run_id`, `status`; không có cột người xử lý, hạn, nhắc, chuyển cấp hay hết hạn
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:217-235`). Thiếu: Bước
  phê duyệt cần dữ liệu giao, chuyển cấp và chủ thể đã khoá, nằm ở bảng Studio thêm.
- Composition root đặt `strict_approval_prefixes=frozenset({"memory."})` và `decision_guards`
  (`apps/api/src/dw_api/bootstrap/runtime.py:237-239`); CLAUDE.md (Agent and tool rules) bắt đây là cách duy
  nhất điều kiện ai được quyết định một loại phê duyệt. Ràng buộc: `studio.step.` thêm bằng `|=`.
- Mã quyết định Zalo chỉ cấp cho loại phê duyệt có tiền tố đã đăng ký người trả lời phiên bản chủ thể;
  loại không ai trả lời thì quyết định trên web
  (`apps/api/src/dw_api/bootstrap/wiring.py:314`). Ràng buộc: Bước phê duyệt dùng lại cơ chế này.
- `contain_untrusted(name, value)` thoát HTML và bọc giá trị trong `<input name="...">`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/prompts.py:35`), nhưng `render` dựng
  bằng `artifact.template.format(...)` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/prompts.py:168`),
  tức `str.format`. Ràng buộc: chấp nhận cho file nền tảng dưới `configs/prompts`; Thiếu: không dùng
  được cho văn bản một business admin gõ.
- `dw_kernel` giữ thuần stdlib bằng contract import-linter "Kernel is pure (stdlib only)", một denylist
  (`pyproject.toml:252-254`); chưa có thư viện CEL nào trong `uv.lock`, nên một thư viện mới chỉ hiện ra
  với guard khi được nêu tên ở contract. Ràng buộc: phải thêm tên import của cả hai binding CEL (dự kiến `cel` và
  `common_expression_language`, đo ở ticket 01) vào denylist mới thấy được chúng.
- `SqlNotificationRepository.deliver(...)` gửi tới thành viên workspace một lần theo `source_key`
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/notifications.py:103`); cửa đọc là
  `NotificationInboxPort` hẹp (`packages/python/dw_platform/src/dw_platform/application/notifications.py:40`).
  Ràng buộc: `notify.send` (W2) dùng cửa này.

## Mục tiêu

### R1 — Sổ đăng ký loại bước là nguồn duy nhất

Bảng bước, bộ kiểm, trình biên dịch và phân tích bộ ba đọc một `NodeTypeRegistry` (NODE-01).

- R1.1 KHI API danh mục `GET /api/v1/studio/node-types` và worker dựng danh mục loại bước, cả hai PHẢI
  dựng từ cùng một hàm và cho cùng một mã băm danh mục.
- R1.2 KHI API danh mục trả một Loại bước, API danh mục PHẢI trả schema cấu hình, schema đầu ra, Nhánh
  ra, nhãn tiếng Việt, Mức tác động, nhãn năng lực, giới hạn đã kẹp theo gói và lý do bị khoá cho người
  gọi.
- R1.3 [Bỏ] 23/10/2026: kiểm `type@major` chưa đăng ký là hàng `wf.unknown_node_type` trong bảng mã của
  workflow-engine:R2.14, từ chối lúc niêm phong, lưu nháp chỉ cảnh báo (phát hiện A về hai bảng mã).
- R1.4 Mỗi thuộc tính khai trong một mục `NodeTypeRegistry` PHẢI có đúng một nơi đọc trong danh mục,
  bộ kiểm, trình biên dịch hay phân tích bộ ba.
- R1.5 Mỗi Loại bước PHẢI công bố đầu ra là đối tượng có tên và kiểu (`response`, `metadata` và các tên
  khác của loại), với `error` chỉ khi Khi lỗi đặt `continue`.

### R2 — Một tác dụng phụ mỗi bước, đúng cửa theo loại

Mỗi Bước đổi tối đa một thứ bên ngoài, qua cửa mà loại hiệu ứng đó sở hữu (NODE-02).

- R2.1 Mỗi Bước PHẢI có tối đa một tác dụng phụ, đi qua đúng cửa của loại: `ToolExecutor` cho tác động
  ngoài, `RecordsPort` cho bản ghi, cửa thông báo cho thành viên, bộ phân giải model cho model,
  `CodeSandboxPort` cho mã.
- R2.2 Mô-đun một loại bước PHẢI không chứa SQL, không chứa SDK nhà cung cấp và không import adapter cụ
  thể.
- R2.3 NẾU một Bước không khai Khi lỗi, THÌ loại bước PHẢI mặc định về `fail` và không `continue`.
- R2.4 NẾU một Bước `logic.switch` không có Nhánh ra mặc định, THÌ bộ kiểm khi gửi kiểm định PHẢI trả
  `wf.router_not_total` (workflow-engine:R2.2) và không niêm phong.

### R3 — CEL kiểm kiểu khi gửi kiểm định, có trần chi phí

Biểu thức của công ty tính ở máy chủ, chỉ tham chiếu bước chắc chắn đã chạy trước (YC40; NODE-03,
NODE-04).

- R3.1 Văn bản của công ty PHẢI chỉ tính bằng CEL qua `ExpressionEngine` ở máy chủ, không bao giờ qua
  `str.format`, Jinja2 hay eval.
- R3.2 KHI bộ kiểm khi gửi kiểm định gặp một Biểu thức tham chiếu một bước không trội tại vị trí đó, bộ
  kiểm PHẢI trả `wf.ref_not_dominating` (workflow-engine:R2.5) và không niêm phong.
- R3.3 KHI bộ kiểm khi gửi kiểm định gặp một điều kiện không trả kiểu `bool`, bộ kiểm PHẢI trả
  `wf.type_mismatch` (workflow-engine:R2.6) và không niêm phong.
- R3.4 NẾU một Biểu thức khi tính vượt ngân sách khoảng 10.000 vòng hoặc cho kết quả tuần tự hóa vượt
  256 KiB, THÌ `ExpressionEngine` PHẢI trả `expression_budget_exceeded` và không treo worker.
- R3.5 `ExpressionEngine` PHẢI tính Biểu thức chỉ ở máy chủ, không bao giờ trong trình duyệt.
- R3.6 TRONG KHI `settings.is_deployed` đúng, composition root của API và worker PHẢI dựng `ExpressionEngine` trên
  `cel-expr-python`, không bao giờ trên bản Rust, vì CLAUDE.md mục Required stack chỉ ghim `cel-expr-python`
  (ADR-0114 (Accepted) quyết 2).

### R4 — Chuỗi có biến `{{ }}` dựng theo đích, prompt bao chứa

Giá trị của công ty chỉ vào văn bản qua một bộ dựng mẫu tính ở máy chủ, bao chứa khi vào prompt (YC48;
NODE-05, NODE-06).

- R4.1 KHI bộ dựng mẫu render một Chuỗi có biến, bộ dựng mẫu PHẢI tách bằng tokenizer nhận biết CEL và
  render theo đúng một trong sáu đích `prompt`, `text`, `html`, `url`, `header`, `json`.
- R4.2 KHI đích là `prompt`, bộ dựng mẫu PHẢI cắt mỗi giá trị ở 16 KiB và bao trong khối `<input>`
  thoát theo ADR-0010 (Accepted).
- R4.3 NẾU một mẫu đặt một Biểu thức vào vị trí host của một URL, THÌ bộ dựng mẫu PHẢI trả
  `templated_host` và không render.
- R4.4 NẾU một Biểu thức hay mẫu tham chiếu một Trường người chạy không đọc được, THÌ bộ kiểm PHẢI trả
  `field_not_readable` khi gửi kiểm định và `field_hidden` khi render, và không lộ giá trị.

### R5 — Bước dữ liệu đối tượng qua RecordsPort với quyền người chạy

Bước bản ghi đọc và ghi bằng quyền của người kích hoạt hay tài khoản dịch vụ chạy dưới danh nghĩa, giao
với giới hạn dữ liệu của phiên bản (YC19, YC94, YC95; NODE-09).

- R5.1 KHI một Bước `data.object.query`, `create`, `update` hay `upsert` chạy, Bước đó PHẢI đi qua
  `RecordsPort` với ngữ cảnh actor của lượt chạy và đúng khoá chống lặp mà wrapper nút dẫn
  (workflow-engine:R4.5), không tự dựng khoá.
- R5.2 NẾU cấu hình một Bước bản ghi mang khoá `run_as` hay nêu một chủ thể khác người chạy của lượt,
  THÌ schema loại bước PHẢI từ chối cấu hình đó.
- R5.3 [Bỏ] 23/10/2026: giả lập ghi bản ghi nằm ở RecordService (custom-objects:R5.4), không trong Bước;
  Bước chỉ chuyển Chế độ chạy (R5.5).
- R5.4 KHI quy trình Tiếp nhận lead kiểm trùng, Bước bản ghi PHẢI so số điện thoại chuẩn hóa về `+84`
  rồi email chữ thường, không bao giờ chỉ theo tên.
- R5.5 KHI một Bước bản ghi gọi `RecordsPort`, Bước đó PHẢI chuyển nguyên Chế độ chạy của lượt chạy, để
  RecordService giả lập lệnh ghi ở `simulate` (custom-objects:R5.4).

### R6 — Giao người phụ trách theo quy tắc

Bước giao chọn một nhân viên Sales đủ quyền cho một lead đã chấm (YC50; NODE-10).

- R6.1 KHI Bước `data.object.assign` chọn người phụ trách, Bước đó PHẢI chỉ chọn thành viên công ty
  đang hoạt động đủ quyền làm người phụ trách bản ghi trong tầm giao, theo cùng hàm kiểm quyền
  `effective_grants` mà cửa đọc dùng.
- R6.2 KHI từ hai ứng viên trở lên cùng đủ điều kiện, Bước `data.object.assign` PHẢI chọn người lâu
  nhất chưa nhận (100 lead cho 3 ứng viên lệch tối đa 1).
- R6.3 NẾU không ứng viên nào hợp lệ, THÌ Bước `data.object.assign` PHẢI giao cho người dự phòng, là giá
  trị đã duyệt của một điểm gắn kind `principal` trong Bộ giá trị gắn (tenant-config:R8.1), khi người đó qua
  cùng kiểm `effective_grants` của R6.1, qua cùng dịch vụ giao của record-access, nơi ghi audit và outbox
  `studio.record.assigned` trong một giao dịch (record-access:R8.7, record-access:R8.8), và Bước không tự ghi audit.
- R6.4 NẾU người dự phòng cũng không hợp lệ, THÌ Bước `data.object.assign` PHẢI đi Nhánh ra lỗi và không
  giao bản ghi cho ai.

### R7 — ai.llm kiểm phía server, bao chứa, tôn trọng opt-out

Bước chấm điểm trả đầu ra theo lược đồ người dựng đặt, không để nội dung lead thành chỉ dẫn (YC47, YC48,
YC49, YC87; NODE-07, NODE-08).

- R7.1 KHI Bước `ai.llm` nhận câu trả lời của model, Bước đó PHẢI kiểm theo JSON Schema của công ty,
  sửa tối đa một lần, và khi vẫn sai thì trả `output_invalid` ở Nhánh ra lỗi mà lượt chạy không dừng.
- R7.2 KHI Bước `ai.llm` dựng prompt, Bước đó PHẢI đưa mọi giá trị bản ghi vào prompt chỉ qua khối
  `<input>` thoát và cắt ở 16 KiB.
- R7.3 NẾU bản ghi mang cờ `ai_opt_out` hoặc `processing_restricted`, THÌ Bước `ai.llm` PHẢI bỏ qua
  bản ghi đó và không gọi model.
- R7.4 KHI Bước `ai.llm` chấm điểm lead, đầu vào gửi model PHẢI không chứa định danh trực tiếp (họ tên,
  số điện thoại, email, Zalo id), với số điện thoại và email trong văn bản tự do bị che.
- R7.5 KHI Bước `ai.llm` đưa một đối tượng hay một trường vào prompt, Bước đó PHẢI đưa `Mô tả cho AI`
  (`ai_description`) của đối tượng và của trường chỉ qua khối `<input>` thoát, cắt ở 16 KiB, như dữ liệu từ bên
  ngoài (YC101, YC48).

### R8 — tool.call qua ToolExecutor, idempotent

Bước gọi công cụ đi qua một cửa, không lặp tác động khi chạy lại (YC41; NODE-11).

- R8.1 KHI Bước `tool.call` gọi một công cụ, Bước đó PHẢI gọi `ToolExecutor.execute` với đúng khoá chống lặp
  mà wrapper nút dẫn (workflow-engine:R4.5) và phiên bản công cụ đã ghim lúc gửi kiểm định.
- R8.2 KHI hai lần chạy song song dùng cùng khoá chống lặp, `ToolExecutor` PHẢI để tác động ngoài xảy
  ra đúng một lần.
- R8.3 NẾU người chạy thiếu quyền của công cụ, THÌ `ToolExecutor` PHẢI trả `permission_denied` tại
  executor, không phải tại Bước.
- R8.4 NẾU một Bước gửi tin tiếp thị tới người nhận chưa đồng ý, THÌ sàn gửi tin ở executor PHẢI trả
  `blocked:no_consent` (compliance-pdpl:R3.1) và không gửi, kể cả khi gọi thẳng công cụ.

### R9 — human.approval là cổng do máy chủ thực thi

Trang duyệt tin chỉ nhận quyết định của người giữ quyền khác người tạo lượt chạy, trên đúng tham số sẽ
thực thi (YC51; NODE-13, NODE-14, NODE-16).

- R9.1 KHI một Bước phê duyệt mở phê duyệt ở chế độ `live`, Bước đó PHẢI dùng `approval_type` dưới tiền tố nghiêm
  `studio.step.` với một `required_scope` bắt buộc, thu hẹp theo người hoặc Biểu thức ở W1.
- R9.2 NẾU người quyết định là người yêu cầu (người tạo lượt chạy) mà không giữ `required_scope`, hay giữ
  `required_scope` mà không được giao, THÌ luồng phê duyệt PHẢI trả 403 `permission_denied` và không quyết định;
  mọi người khác, vốn không thấy yêu cầu có tem, nhận 404 (ADR-0104 (Accepted) quyết 11; ADR-0004 (Accepted)).
- R9.3 NẾU mã băm chủ thể lúc thực thi khác mã băm đã duyệt, THÌ runtime PHẢI trả `subject_changed` và
  không thực thi, để tham số đã duyệt đúng là tham số được gửi.
- R9.4 NẾU phê duyệt hết hạn, THÌ Bước phê duyệt PHẢI đi Nhánh ra `expired` hoặc làm lượt chạy `failed`
  với `approval_expired`, và không bao giờ tự duyệt.
- R9.5 NẾU ngoài người chạy của lượt không ai giữ `required_scope` của một Bước phê duyệt, THÌ kiểm lúc gửi kiểm
  định mà spec này đăng ký cho loại `workflow` vào bảng kiểm theo loại của agent-lifecycle (agent-lifecycle:R2.7)
  PHẢI làm lệnh gửi trả 422 với `details.reason_code` `no_second_approver` và phiên bản không rời Nháp.
- R9.6 NẾU người quyết định giữ `required_scope` và là người tạo lượt chạy, THÌ luồng phê duyệt PHẢI trả
  409 `conflict` với `details.reason_code` `second_person_required` và không quyết định, vì `studio.step.` là tiền
  tố nghiêm (ADR-0112 (Accepted) quyết 7; ADR-0104 (Accepted) quyết 11).
- R9.7 KHI một Bước phê duyệt mở phê duyệt, Bước đó PHẢI đóng dấu vào yêu cầu tên mọi Trường mà trang
  duyệt hiển thị.
- R9.8 NẾU người quyết định không đọc được một Trường đã đóng dấu (luật của field-security:R4.5), THÌ
  `decision_guards` của `studio.step.approval` PHẢI trả 403 và không quyết định.
- R9.9 TRONG KHI lượt chạy ở chế độ `simulate`, KHI một Bước phê duyệt chạy, Bước đó PHẢI lấy quyết định giả lập
  cho chính Bước đó từ đầu vào của lượt mô phỏng (workflow-triggers:R2.7) hay từ Câu kiểm định của Cổng chất lượng
  (agent-lifecycle:R4.7), theo đúng từ vựng `approved` hay `rejected` mà tiêu chí này làm chủ và hai bên kia dùng
  nguyên, đi theo Nhánh ra của quyết định đó, không mở yêu cầu phê duyệt nào và không chờ người quyết
  (ADR-0111 (Accepted) quyết 5).
- R9.10 KHI một Bước phê duyệt dùng một quyết định giả lập, Bước đó PHẢI ghi audit `studio.step.approval.simulated`
  với `details.run_mode`, `details.decision` và nguồn của quyết định (biểu mẫu chạy mô phỏng hay Câu kiểm định)
  trong cùng giao dịch ghi kết quả của Bước.
- R9.11 NẾU lượt chạy ở chế độ `live`, THÌ Bước phê duyệt PHẢI mở yêu cầu phê duyệt thật và không đọc quyết định
  giả lập nào, kể cả khi đầu vào của lượt chạy mang một quyết định giả lập, để quyết định giả lập không bao giờ
  thỏa một phê duyệt `live`.
- R9.12 NẾU lượt chạy ở chế độ `simulate` tới một Bước phê duyệt mà không có quyết định giả lập cho Bước đó, THÌ
  Bước phê duyệt PHẢI làm lượt chạy `failed` với `details.reason_code` `simulated_decision_missing` và không bao
  giờ coi là đã duyệt.
- R9.13 NẾU lúc một Bước phê duyệt mở phê duyệt ở chế độ `live` mà `effective_grants` không còn ứng viên hợp lệ
  (giữ `required_scope`, được giao, khác người tạo lượt chạy và chủ thể chạy), THÌ Bước phê duyệt PHẢI đi Nhánh ra
  lỗi với `no_approver`, không nối Nhánh ra đó thì làm lượt chạy `failed` với `no_approver`, và không mở yêu cầu
  phê duyệt nào (ADR-0112 (Accepted) quyết 7).
- R9.14 NẾU một lệnh ghi của `dw_app` gắn tenant A đặt `run_id` của một dòng `studio.step_assignments` bằng id một
  lượt chạy của tenant B, hay `approval_request_id` của một dòng `studio.step_approvals` bằng id một yêu cầu phê duyệt
  của tenant B, THÌ PostgreSQL PHẢI từ chối lệnh đó bằng FK ghép của cột đó và không ghi dòng nào, vì kiểm khóa ngoại
  không qua RLS (CLAUDE.md, Tenancy and authorization).
- R9.15 KHI một lượt chạy sang `cancelled` theo bất kỳ đường nào, kể cả Tắt khẩn và quá hạn chót với `deadline_exceeded`
  (workflow-engine:R5.23), PostgreSQL PHẢI đặt mọi yêu cầu phê duyệt `studio.step.` đang `pending` của lượt đó sang
  `cancelled` trong cùng giao dịch, để không ai quyết được phê duyệt của một lượt đã kết thúc (V4.14).

## Trong phạm vi

- `NodeTypeRegistry` và `build_node_registry(ports)` dựng ở cả hai composition root; sáu lát loại bước
  W1: `data.transform`, `logic.switch`, `flow.stop`, `data.object.query|create|update|upsert`,
  `data.object.assign`, `ai.llm`, `tool.call`, `human.approval`, cùng hình chiếu `trigger.endpoint`.
- `ExpressionEngine` (Protocol ở `dw_kernel.expressions`; hai adapter `CelCppEngine` và `CelRustEngine` ở
  `dw_studio.core.adapters.cel`, gói duy nhất import thư viện CEL theo hợp đồng import-linter của studio-skeleton:R5.6
  mà spec này viết, qua một bộ test hợp đồng, composition root chọn theo setting, profile triển khai chỉ
  `cel-expr-python`, R3.6) và
  thư viện `dw.cel/v1`;
  bảng ánh xạ kiểu; bộ dựng Chuỗi có biến `{{ }}` theo sáu đích.
- Bảng `studio.step_assignments`, `studio.step_approvals` (chủ duy nhất của liên kết từ Bước phê duyệt tới yêu cầu
  phê duyệt, nối với dòng chờ của workflow-engine qua `(run_id, interrupt_id)`), và `StepWaitLookupPort` mà
  workflow-engine khai, đáp ứng từ bảng đó.
- Mở yêu cầu phê duyệt `studio.step.`: tiền tố nghiêm `studio.step.` thêm bằng `|=` và một mục
  `decision_guards['studio.step.approval']` (được giao, đọc được mọi Trường đóng dấu) ở composition root;
  kiểm còn ứng viên lúc mở phê duyệt (`no_approver`, R9.13); kiểm lúc gửi kiểm định của loại `workflow`
  (`no_second_approver`) đăng ký vào bảng kiểm theo loại của agent-lifecycle (R9.5); hủy yêu cầu đang mở cùng lượt chạy
  bị hủy, kể cả lượt quá hạn chót (R9.15).
- Quyết định giả lập của Bước phê duyệt trong lượt mô phỏng và audit `studio.step.approval.simulated` (R9.9-R9.12).
- Route `GET /api/v1/studio/node-types`, `POST /api/v1/studio/expressions/check`,
  `POST /api/v1/studio/expressions/evaluate`, `GET /api/v1/studio/workflows/{id}/draft/scope`.

## Ngoài phạm vi

| Việc                                                                                                                                                                                                                                                                                                                                                                                                             | Vì sao                                                                                                                                                                                                                                                 | Chủ                                                             |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------- |
| Tài liệu `dw.workflow/v1`, bộ kiểm toàn đồ thị và bảng mã `wf.*` của nó, trình biên dịch, hàng run, điểm chờ và handler của phê duyệt bước, hẹn giờ                                                                                                                                                                                                                                                              | Là hợp đồng và máy chạy của quy trình                                                                                                                                                                                                                  | `workflow-engine`                                               |
| Trình kích hoạt và Nguồn dữ liệu (Data Hub), ánh xạ payload vào `input_schema`                                                                                                                                                                                                                                                                                                                                   | Là cửa vào của quy trình                                                                                                                                                                                                                               | `workflow-triggers`                                             |
| Định nghĩa công cụ và Bộ công cụ theo loại, `ToolExecutor`, `ToolSpec`                                                                                                                                                                                                                                                                                                                                           | Công cụ là dữ liệu tenant qua một executor (ADR-0116 (Accepted))                                                                                                                                                                                       | `tools-and-skills`                                              |
| Sàn gửi tin tiếp thị (ngưỡng, đồng ý) trong đường gửi của executor                                                                                                                                                                                                                                                                                                                                               | Một chủ cho sàn gửi (DO-3)                                                                                                                                                                                                                             | `compliance-pdpl`                                               |
| Container mã dùng một lần, `CodeSandboxPort`                                                                                                                                                                                                                                                                                                                                                                     | Hạ tầng cách ly tách riêng                                                                                                                                                                                                                             | `code-sandbox`                                                  |
| Lịch sử chạy theo bước, span, bảng điều khiển sử dụng                                                                                                                                                                                                                                                                                                                                                            | Đọc từ Postgres dưới RLS (ADR-0122 (Accepted))                                                                                                                                                                                                         | `telemetry-and-audit`                                           |
| `notify.send` chỉ tới thành viên; run không-live chỉ Danh sách người nhận thử                                                                                                                                                                                                                                                                                                                                    | B7b-nodes 11                                                                                                                                                                                                                                           | đợt sau (W2, `workflow-nodes`)                                  |
| Bước phê duyệt: nhắc, chuyển cấp, hết hạn, mã quyết định Zalo                                                                                                                                                                                                                                                                                                                                                    | B7b-nodes 12 (phần còn lại), 16                                                                                                                                                                                                                        | đợt sau (W2, `workflow-nodes`)                                  |
| `http.request`; `ai.agent`                                                                                                                                                                                                                                                                                                                                                                                       | B7b-nodes 13, 14                                                                                                                                                                                                                                       | đợt sau (W2, `workflow-nodes`)                                  |
| `logic.parallel`, `logic.join`, `logic.map`; `time.delay`, `time.wait_until`                                                                                                                                                                                                                                                                                                                                     | B7b-nodes 15, 16                                                                                                                                                                                                                                       | đợt sau (W2, `workflow-nodes`)                                  |
| `human.task` và hộp "Việc của tôi", `studio.human_tasks`                                                                                                                                                                                                                                                                                                                                                         | B7b-nodes 17                                                                                                                                                                                                                                           | đợt sau (W2, `workflow-nodes`)                                  |
| `flow.subworkflow`, `trigger.call`, `flow.return`                                                                                                                                                                                                                                                                                                                                                                | B7b-nodes 18                                                                                                                                                                                                                                           | đợt sau (W2, `workflow-nodes`)                                  |
| `code.python` và khóa `studio.code.author`, mà spec này đăng ký cùng Loại bước; quyền lợi `code_node` do `CodeExecutionService` của code-sandbox kiểm trước runner                                                                                                                                                                                                                                               | B7b-nodes 19 (D7); khóa có một chủ là spec này, quyền lợi có một chủ là code-sandbox (code-sandbox:R2.3)                                                                                                                                               | đợt sau (W2, `workflow-nodes`); `code-sandbox`                  |
| `trigger.manual`, `trigger.schedule`, `trigger.record_event`; `data.object.get`, `delete`                                                                                                                                                                                                                                                                                                                        | B7b-nodes 20                                                                                                                                                                                                                                           | đợt sau (W2, `workflow-nodes`)                                  |
| R7.3: Bước `ai.llm` bỏ qua bản ghi mang cờ `ai_opt_out` hay `processing_restricted`, không gọi model                                                                                                                                                                                                                                                                                                             | Cờ Hạn chế xử lý và yêu cầu chủ thể dữ liệu là W2 của compliance-pdpl; W1 chỉ chạy trên lead giả lập (YC89; Q9 của phiếu)                                                                                                                              | đợt sau (W2, `workflow-nodes`)                                  |
| WN14: test âm của R7.3, lead `ai_opt_out` không có lời gọi model nào                                                                                                                                                                                                                                                                                                                                             | Đi cùng R7.3 sang W2 (Q9 của phiếu)                                                                                                                                                                                                                    | đợt sau (W2, `workflow-nodes`)                                  |
| R9.4: phê duyệt hết hạn đi Nhánh ra `expired` hoặc làm lượt chạy `failed` với `approval_expired`                                                                                                                                                                                                                                                                                                                 | YC52 và lane hẹn giờ ở W2; ở W1 Bước phê duyệt không có hạn riêng, còn phê duyệt mở mà không ai quyết bị hủy cùng lượt chạy khi lượt tới hạn chót `deadline_at` của workflow-engine, 30 ngày sau lần nhận (R9.15; workflow-engine:R5.22; V4.14; DO-31) | đợt sau (W2, `workflow-nodes`); `workflow-engine` ghi `expired` |
| WN10: test âm của R9.4, quá hạn không bao giờ thành `approved`                                                                                                                                                                                                                                                                                                                                                   | Đi cùng R9.4 sang W2 (DO-31)                                                                                                                                                                                                                           | đợt sau (W2, `workflow-nodes`)                                  |
| Kết quả giả lập ghim theo Bước cho lệnh gọi giả lập và bảng chạy mô phỏng                                                                                                                                                                                                                                                                                                                                        | W1 dùng giá trị sinh từ output schema (tenant-config:R5.3); bảng thuật ngữ đặt chủ ở spec này                                                                                                                                                          | đợt sau (W2, `workflow-nodes`)                                  |
| Lịch làm việc và ngày lễ của công ty cho `time.add_workdays`                                                                                                                                                                                                                                                                                                                                                     | BS35 giao chủ ở spec này, dữ liệu từ discovery 27 (FOG-16); cần trước khi cắt ticket W2 (YC98)                                                                                                                                                         | đợt sau (W2, `workflow-nodes`)                                  |
| Giao theo nhóm: ứng viên hay người dự phòng là một nhóm                                                                                                                                                                                                                                                                                                                                                          | Nhóm của org-and-principals là W2; W1 giao trong thành viên workspace giữ quyền (Q6 của phiếu)                                                                                                                                                         | đợt sau (W2, `workflow-nodes`)                                  |
| Bước phê duyệt thu hẹp người duyệt theo nhóm; giá trị `team` của `assignee_kind`                                                                                                                                                                                                                                                                                                                                 | Nhóm của org-and-principals là W2; W1 chỉ nhận người và Biểu thức (R9.1)                                                                                                                                                                               | đợt sau (W2, `workflow-nodes`)                                  |
| Duyệt thay: người duyệt đặt một người duyệt thay cho phê duyệt của mình trong một khoảng thời gian có hạn khi vắng mặt, có audit khi đặt, gỡ và mỗi quyết định của người duyệt thay (YC104); người duyệt thay phải giữ khóa đóng dấu của loại phê duyệt và `approvals.decide`, không phải người tạo lượt chạy (YC51), và chỉ được giao có thời hạn (từ, đến), có audit; ngoài các điều kiện đó guard vẫn trả 403 | N7 của Đạt ngày 24/10/2026 và V4.10; ADR-0112 (Accepted) quyết 7 và ADR-0104 (Accepted) quyết 11 ghi điều kiện từ W2; "Duyệt thay" khác "Ủy quyền" dùng kết nối của bảng thuật ngữ                                                                     | đợt sau (W2, `workflow-nodes`)                                  |
| Bước `logic.loop` chạy lại một đoạn quy trình theo điều kiện, với `max_iterations` khai trong Bước mà lượt chạy không bao giờ vượt; đến `max_iterations` thì Bước đi Nhánh ra `max_reached`, không nối Nhánh ra đó thì lượt chạy `failed` với `error.code` `loop_limit_reached` (YC105)                                                                                                                          | N7 của Đạt ngày 24/10/2026; V4.P11; cấu trúc vòng lặp có trần do workflow-engine biên dịch                                                                                                                                                             | đợt sau (W2, `workflow-nodes`); `workflow-engine`               |
| Duyệt song song k trên n người được giao                                                                                                                                                                                                                                                                                                                                                                         | Nguyên liệu chung của các gói Nhân sự, Mua hàng, Tài chính, ghi ở Không làm sau gói Bán hàng (N9 của Đạt ngày 24/10/2026)                                                                                                                              | đợt sau (W3, `workflow-nodes`); `workflow-engine`               |
| Bảng quyết định, hay ma trận duyệt chọn người duyệt theo ngưỡng                                                                                                                                                                                                                                                                                                                                                  | Nguyên liệu chung của các gói Nhân sự, Mua hàng, Tài chính, ghi ở Không làm sau gói Bán hàng (N9 của Đạt ngày 24/10/2026)                                                                                                                              | đợt sau (W3, `workflow-nodes`)                                  |
| Phiên bản chính mới của loại bước; nội dung giàu bằng python-liquid                                                                                                                                                                                                                                                                                                                                              | B7b-nodes 21, 22                                                                                                                                                                                                                                       | đợt sau (W3, `workflow-nodes`)                                  |

## Dữ liệu

- `studio.step_assignments`: giao của một Bước phê duyệt cho người. Cột `tenant_id`,
  `workspace_id`, `run_id`, `node_id`, `assignee_kind` CHECK (`user`) ở W1, không DEFAULT (nhóm là W2),
  `assignee_id`, `required_scope`, `created_at timestamptz`. RLS bật và FORCE; policy thu hẹp theo `app.tenant_id`.
  FK ghép `(tenant_id, run_id)` tới `platform.worker_runs (tenant_id, id)` (`uq_worker_runs_tenant_id_id` của
  workflow-engine/02) `ON DELETE CASCADE`, với chỉ mục `(tenant_id, run_id, node_id)` là chỉ mục của nó.
- `studio.step_approvals`: chủ duy nhất của liên kết một Bước phê duyệt với `platform.approval_requests`, và giữ
  mã băm chủ thể đã khoá. Cột `tenant_id`, `workspace_id`, `run_id`, `node_id`, `interrupt_id text NOT NULL`,
  `approval_request_id`, `subject_node_id`, `subject_hash`, `created_at timestamptz`. CHECK
  `ck_step_approvals_subject_hash` (mã băm khác null khi đã khoá). FK ghép `(tenant_id, workspace_id, approval_request_id)`
  tới `platform.approval_requests (tenant_id, workspace_id, id)` qua `uq_approval_requests_tenant_id_workspace_id_id`,
  ràng buộc đã có mà `platform.approval_view_receipts` và tenant-config/05 cũng dùng, nên ticket 06 không thêm UNIQUE
  nào lên bảng đó, `ON DELETE CASCADE`, có chỉ mục `(tenant_id, workspace_id, approval_request_id)`; FK
  `(tenant_id, run_id, interrupt_id)` tới `platform.run_waits (tenant_id, run_id, interrupt_id)` `ON DELETE CASCADE`,
  có chỉ mục `(tenant_id, run_id, interrupt_id)`, nên dòng chờ không giữ id
  yêu cầu nào (workflow-engine:R6.2). RLS bật và FORCE. `updated_at` do trigger giữ, nhường giá trị câu lệnh nêu.

## API

- `GET /api/v1/studio/node-types` (quyền `studio.workflows.edit`): danh mục loại bước đã kẹp theo gói,
  kèm lý do bị khoá cho người gọi. Mã lỗi `wf.unknown_node_type` (`details.reason_code`, bảng mã của
  workflow-engine:R2.14).
- `POST /api/v1/studio/expressions/check` và `POST /api/v1/studio/expressions/evaluate` (dạng
  sub-resource của ADR-0108 (Accepted); quyền `studio.workflows.edit`, giới hạn tần suất theo người): kiểm
  hoặc tính một Biểu thức với mẫu người gọi gõ, hoặc đầu ra bước đã ghi mà người gọi đọc được (đã che).
  Không bao giờ tính trong trình duyệt. Mã lỗi `wf.ref_not_dominating`, `wf.type_mismatch` (bảng mã
  của workflow-engine:R2.5, R2.6), `field_not_readable`, `expression_budget_exceeded`, `templated_host`.
- `GET /api/v1/studio/workflows/{id}/draft/scope?node=` (quyền `studio.workflows.edit`): cây biến có
  kiểu chỉ gồm bước trội tại vị trí đó.
- Quyền dùng lại: `studio.workflows.edit` do workflow-engine/01 đăng ký; phát hành quy trình dùng khóa
  chung `studio.publish.approve` của agent-lifecycle, không có khóa phát hành riêng theo loại;
  `studio.tasks.manage` và `studio.code.author` thuộc W2.
- Mã spec này thêm: `no_second_approver` (422 ở lệnh gửi kiểm định của agent-lifecycle, R9.5),
  `simulated_decision_missing` (lượt mô phỏng `failed`, R9.12), `no_approver` (Nhánh ra lỗi hay lượt `failed` lúc mở
  phê duyệt, R9.13); người quyết bị từ chối nhận 404, 409 `conflict` với `details.reason_code`
  `second_person_required` hay 403 `permission_denied` theo ADR-0104 (Accepted) quyết 11 (R9.2, R9.6, R9.8).

## Kiểm soát

| #    | Kiểm soát                                                                                                                                      | Yêu cầu                 | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| WN1  | Văn bản công ty không qua `str.format`, Jinja2 hay eval                                                                                        | R3.1                    | Mẫu `{0}{x.__class__}` ra nguyên văn; gỡ tokenizer nhận biết CEL → test kiến trúc đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| WN2  | Mọi giá trị vào prompt được bao chứa và cắt 16 KiB, kể cả `Mô tả cho AI`                                                                       | R4.2, R7.2, R7.5        | `</input>` trong lời nhắn lead hay trong `ai_description` của một trường không đóng được khối; gỡ `contain_untrusted` ở đích prompt hay ở mục bối cảnh → đỏ                                                                                                                                                                                                                                                                                                                                                                                      |
| WN3  | Đầu ra model kiểm phía server                                                                                                                  | R7.1                    | Model giả trả `score=150` hai lần → `output_invalid` và đi Nhánh ra lỗi; gỡ kiểm JSON Schema → đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| WN4  | Bước bản ghi chỉ là chủ thể chạy; không khoá `run_as`                                                                                          | R5.2                    | Cấu hình có `run_as` → schema từ chối; chủ thể thiếu quyền → `permission_denied`                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| WN5  | Trường bị ẩn không vào mẫu hay Biểu thức                                                                                                       | R4.4                    | Tham chiếu `phone` không đọc được → `field_not_readable` lúc gửi kiểm định, `field_hidden` lúc render; gỡ kiểm → đỏ                                                                                                                                                                                                                                                                                                                                                                                                                              |
| WN6  | Tác động ngoài qua `ToolExecutor`, idempotent                                                                                                  | R8.2                    | Hai lần chạy song song cùng khoá do wrapper nút dẫn (workflow-engine:R4.5) → một lần gửi; Bước tự dựng khoá khác → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                       |
| WN7  | Quyền công cụ và sàn gửi tin kiểm ở executor, không ở Bước                                                                                     | R8.3, R8.4              | Thiếu quyền → `permission_denied` từ executor; `email.send` của `smtp@1.0.0` tới địa chỉ chưa đồng ý → `blocked:no_consent`; gọi thẳng công cụ cũng bị chặn                                                                                                                                                                                                                                                                                                                                                                                      |
| WN8  | Người duyệt giữ quyền, được giao, khác người tạo lượt; còn ứng viên lúc mở phê duyệt; không gửi kiểm định khi không có người thứ hai giữ scope | R9.2, R9.5, R9.6, R9.13 | Người tạo lượt giữ scope tự duyệt → 409 `second_person_required`; người tạo lượt thiếu scope, hay người giữ scope mà không được giao → 403; người khác không giữ tem → 404; chỉ người chạy giữ scope → lệnh gửi kiểm định trả 422 `no_second_approver`, phiên bản ở Nháp; người được giao duy nhất rời công ty sau khi phát hành → lúc mở phê duyệt Bước đi Nhánh ra lỗi với `no_approver`, hay lượt `failed` với `no_approver` khi không nối Nhánh ra đó, không yêu cầu nào mở; gỡ guard, gỡ đăng ký kiểm hay gỡ kiểm ứng viên lúc mở → test đỏ |
| WN9  | Tham số đã duyệt là tham số được thực thi                                                                                                      | R9.3                    | Chen một Bước sau khi duyệt → gửi kiểm định từ chối; mã băm chủ thể khác → `subject_changed`                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| WN10 | Hết hạn không bao giờ tự duyệt                                                                                                                 | R9.4                    | Quá hạn → Nhánh ra `expired` hoặc `approval_expired`, không bao giờ có `approved`                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| WN11 | Mặc định đóng: Khi lỗi và nhánh switch                                                                                                         | R2.3, R2.4              | Không khai Khi lỗi → `fail`; `logic.switch` thiếu nhánh mặc định → `wf.router_not_total`, không niêm phong                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| WN12 | Biểu thức có trần chi phí, không treo                                                                                                          | R3.4                    | Map lồng 3 cấp 22 phần tử → `expression_budget_exceeded` ở cả hai adapter; gỡ ngân sách vòng ở `CelCppEngine`, hay tiền-kiểm AST ở `CelRustEngine` → đỏ                                                                                                                                                                                                                                                                                                                                                                                          |
| WN13 | Host không nằm trong mẫu                                                                                                                       | R4.3                    | `https://{{ trigger.input.host }}/` → `templated_host`, không render                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| WN14 | Bước AI tôn trọng opt-out                                                                                                                      | R7.3                    | Lead `ai_opt_out` → không có lời gọi model nào                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| WN15 | Mỗi thuộc tính loại bước có nơi đọc                                                                                                            | R1.4                    | Thêm một thuộc tính không ai đọc vào `NodeTypeRegistry` → test bảng thuộc-tính-tới-nơi-đọc đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| WN16 | Ứng viên giao và người dự phòng đủ quyền theo `effective_grants`, giao qua một dịch vụ                                                         | R6.1, R6.3, R6.4        | Người không giữ quyền làm người phụ trách bản ghi không bao giờ được chọn, kể cả khi là người dự phòng; người dự phòng không hợp lệ → Nhánh ra lỗi; lần giao của Bước có đúng một audit và một outbox `studio.record.assigned`, do dịch vụ giao của record-access ghi; gỡ kiểm quyền → đỏ                                                                                                                                                                                                                                                        |
| WN17 | Người duyệt đọc được mọi Trường mà trang duyệt hiển thị                                                                                        | R9.7, R9.8              | Bước phê duyệt đóng dấu `phone`; người được giao không đọc được `phone` quyết → 403 tại `decide`, yêu cầu vẫn `pending`; gỡ điều kiện đọc trường khỏi guard → test đỏ                                                                                                                                                                                                                                                                                                                                                                            |
| WN18 | Quyết định giả lập không bao giờ thỏa một phê duyệt `live`, và thiếu thì không coi là đã duyệt                                                 | R9.11, R9.12            | Lượt `live` có quyết định giả lập `approved` trong đầu vào → yêu cầu phê duyệt thật được mở, lượt chạy chờ; lượt `simulate` thiếu quyết định cho một Bước phê duyệt → `failed` `simulated_decision_missing`, Nhánh ra duyệt không chạy; gỡ kiểm chế độ ở Bước → test đỏ                                                                                                                                                                                                                                                                          |
| WN19 | Profile triển khai chỉ tính Biểu thức bằng `cel-expr-python`                                                                                   | R3.6                    | Setting chọn `CelRustEngine` khi `settings.is_deployed` → bị từ chối, test đỏ khi giá trị của profile triển khai trỏ sang bản Rust; ngoài profile triển khai setting chọn được `CelRustEngine` và bộ test hợp đồng chạy với nó; gỡ kiểm `settings.is_deployed` → profile triển khai dựng được bản Rust, test đỏ                                                                                                                                                                                                                                  |
| WN20 | Giao và phê duyệt của Bước không trỏ được tới lượt chạy hay yêu cầu của công ty khác                                                           | R9.14                   | `dw_app` gắn tenant A chèn dòng `step_assignments` mang `run_id` của một lượt chạy tenant B, hay dòng `step_approvals` mang `approval_request_id` của một yêu cầu tenant B → lỗi FK, không dòng nào được ghi; đổi một trong hai FK về FK một cột → ca của nó qua, test đỏ                                                                                                                                                                                                                                                                        |
| WN21 | Phê duyệt bước của lượt đã hủy không còn quyết được, kể cả lượt quá hạn chót                                                                   | R9.15                   | Lượt chờ ở một Bước phê duyệt bị reaper kết thúc vì `deadline_exceeded` → yêu cầu `studio.step.` của nó `cancelled` trong cùng giao dịch, người được giao quyết sau đó bị từ chối, yêu cầu vẫn `cancelled`; Tắt khẩn một lượt đang chờ → như vậy; gỡ trigger hủy yêu cầu → yêu cầu còn `pending`, test đỏ                                                                                                                                                                                                                                        |

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (chứng minh bằng
  `reviewing-feature-security` ở thời điểm code).
- Test âm chạy ở Chế độ chạy `live` với adapter giả tôn trọng hợp đồng, không chỉ ở `simulate`
  (`failure-modes.md` #3).
- `make ci` xanh, gồm test kiến trúc cấm SQL, SDK nhà cung cấp, `jinja2` và `.format(` trên giá trị
  trong `dw_studio`.

## Phụ thuộc

- `studio-skeleton`: gói `dw_studio` và seam API (`.claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md`),
  và bố cục gói mà studio-skeleton làm chủ: adapter CEL ở `dw_studio.core.adapters.cel` (studio-skeleton:R5.6), hợp
  đồng import-linter của tiêu chí đó giao cho ticket 01 của spec này ở Ngoài phạm vi của studio-skeleton.
- `tools-and-skills` (batch 2, đang viết song song): `ToolExecutor`, `ToolSpec`, hồ sơ schema và Bộ
  công cụ ghim; không định nghĩa bảng của nó ở đây.
- `workflow-engine` (batch 2): tài liệu `dw.workflow/v1`, bộ kiểm toàn đồ thị với hàm dominator và bảng mã
  `wf.*` (workflow-engine:R2.2, R2.5, R2.6, R2.14), bộ bọc node áp `retry`/`timeout`/Khi lỗi và dẫn khóa chống
  lặp duy nhất của mọi hiệu ứng (workflow-engine:R4.5), điểm chờ và handler phê duyệt bước
  (workflow-engine:R6.2) với `platform.run_waits` mà `studio.step_approvals` trỏ tới và `StepWaitLookupPort` mà
  spec này đáp ứng, `uq_worker_runs_tenant_id_id` mà FK ghép của `studio.step_assignments` trỏ tới
  (workflow-engine/02), ghim phiên bản, khóa `studio.workflows.edit` (workflow-engine/01), và hạn chót `deadline_at`
  của lượt chạy, mà lượt quá hạn sang `cancelled` với `deadline_exceeded` và trigger hủy dòng chờ đi theo, nơi R9.15
  nghe (workflow-engine:R5.22, workflow-engine:R5.23, workflow-engine:R6.13).
- `custom-objects`: `RecordService` đáp ứng `RecordsPort`, giả lập ghi ở `simulate` (custom-objects:R5.4) và
  cây lọc (custom-objects:R5.6, custom-objects:R8.9;
  `.claude/plans/studio/custom-objects/issues/04-truy-van-ban-ghi.md`); `Mô tả cho AI` của đối tượng và trường
  mà R7.5 đọc (YC101; `.claude/plans/studio/custom-objects/issues/02-luoc-do-dinh-nghia-object.md`).
- `record-access`: ngữ cảnh actor và Giới hạn dữ liệu ở mọi cửa (record-access:R6.4), và giao người phụ
  trách qua một dịch vụ giao ghi audit và outbox `studio.record.assigned` (record-access:R8.1, record-access:R8.7,
  record-access:R8.8; `.claude/plans/studio/record-access/issues/05-giao-nguoi-phu-trach.md`), mà Bước giao gọi
  qua một Protocol spec này khai.
- `agent-builder`: bộ ráp `assemble_system_prompt` cạnh `contain_untrusted` và linter chặn `<input`,
  `<tenant_instructions`, phục vụ cả Bước `ai.llm` (ADR-0117 (Accepted) quyết 4;
  `.claude/plans/studio/agent-builder/issues/02-loai-agent-va-khung-prompt.md`); spec này dùng khung prompt riêng,
  không linter riêng.
- `workflow-triggers`: route `.../test-runs` đưa quyết định giả lập của mỗi Bước phê duyệt vào đầu vào của lượt mô
  phỏng (workflow-triggers:R2.7, workflow-triggers:R2.8).
- `tenant-config`: Chế độ chạy `live`/`test`/`simulate` và chặn tác động ở executor (tenant-config:R5.1),
  Bản kê lượt chạy ghim `dw.cel/v1` (tenant-config:R6.1), điểm gắn kind `principal` cho người dự phòng và
  guard async `ApprovalDecisionGuard` (`.claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md`).
- `field-security` (batch 2): `visible_fields` cho kiểm khi gửi kiểm định và render; luật người duyệt phải
  đọc được mọi Trường của phê duyệt (field-security:R4.5).
- `model-connections` (batch 2): bộ phân giải model theo tenant cho `ai.llm`.
- `compliance-pdpl` (batch 2): sàn gửi tin ở executor với mã `blocked:no_consent` (compliance-pdpl:R3.1,
  `.claude/plans/studio/compliance-pdpl/issues/04-san-gui-tin-marketing.md`); cờ
  `ai_opt_out`/`processing_restricted` ở W2.
- `org-and-principals`: tài khoản dịch vụ làm chủ thể chạy (org-and-principals:R6.7); nhóm cho người xử
  lý và ứng viên giao ở W2.
- `tenant-rbac`: `effective_grants` (tenant-rbac:R2) cho ứng viên giao, người dự phòng và ứng viên duyệt, kể cả kiểm
  còn ứng viên lúc mở phê duyệt (R9.13).
- `agent-lifecycle`: khóa phát hành chung `studio.publish.approve`, bảng kiểm theo loại chạy lúc gửi kiểm định
  mà R9.5 đăng ký vào (agent-lifecycle:R2.7; `.claude/plans/studio/agent-lifecycle/issues/03-hop-dong-vong-doi-va-niem-phong.md`,
  ticket 06 chờ ticket đó; ADR-0120 (Accepted) quyết 2), Câu kiểm định của Cổng chất lượng mang quyết định giả
  lập cho Bước phê duyệt (agent-lifecycle:R4.7), D11 hai người cho phát hành (agent-lifecycle:R5.2).
- Mã từ chối người quyết: 404 ngoài tầm thấy, 409 `conflict` cho luật tách nhiệm, với `details.reason_code`
  `second_person_required` mà `_enforce_strict_rules` của tenant-config/05 đặt cho luật tiền tố nghiêm của mọi loại
  phê duyệt, 403 `permission_denied` khi thấy mà thiếu quyền, không được giao hay không đọc được Trường đóng dấu
  (ADR-0104 (Accepted) quyết 11; tem và tầm thấy của ADR-0004 (Accepted)).
- Kiểm lại khi: `workflow-engine` đổi hình hàm dominator, bảng mã `wf.*`, khóa chống lặp, `StepWaitLookupPort`
  hay hợp đồng `dw.workflow/v1`; `tools-and-skills` đổi chữ ký `ToolExecutor.execute`; `record-access` đổi hình
  `RecordsPort`, dịch vụ giao hay ngữ cảnh actor → kiểm lại 01-06; agent-lifecycle đổi bảng kiểm theo loại hay
  cách Câu kiểm định mang quyết định giả lập → R9.5, R9.9, ticket 06; agent-builder đổi `assemble_system_prompt`
  hay linter → R7, ticket 05; số đo FOG-50 trượt (ADR-0114 (Accepted) quyết 2) → R3.6, ticket 01, và chuyển profile
  triển khai sang bản Rust sửa CLAUDE.md mục Required stack trong cùng thay đổi (V4.P13); tenant-config/05 đổi mã của luật tiền tố nghiêm →
  R9.6, ticket 06; workflow-engine đổi trạng thái của lượt quá hạn chót hay trigger hủy dòng chờ → R9.15, ticket 06; studio-skeleton đổi gói của adapter CEL ở R5.6 → Trong phạm vi, ticket 01.

## Câu hỏi còn mở

## Quyết định

- 23/10/2026 (Đạt): workflow-nodes sở hữu `ExpressionEngine`; Protocol ở `dw_kernel.expressions`, adapter
  ở `dw_studio`. Hỏi: DO-1. Sửa: R3, Trong phạm vi.
- 23/10/2026 (Đạt): D11 hai người cho mọi phát hành; phát hành quy trình cần một người khác người chạy
  giữ `required_scope`. Sửa: R9.5, WN8.
- 23/10/2026 (agent, tạm theo khuyến nghị (a)): DO-11 — mặc định truy cập `public` là toàn tenant; quan
  hệ quản lý cho đọc và sửa (không xóa) có công tắc theo object; khi giao, mặc định giữ workspace sở
  hữu. Hỏi: DO-11. Sửa: R5, R6. Nếu sai thì: đổi ngữ nghĩa tầm mà ứng viên giao và bước bản ghi dựa vào.
- 23/10/2026 (agent, tạm theo khuyến nghị (a)): DO-30 — phiên bản quy trình con và agent-node ghim lúc
  gửi kiểm định, không "theo bản đang chạy". Hỏi: DO-30. Sửa: R8 (ghim công cụ), Ngoài phạm vi
  (`ai.agent`). Nếu sai thì: bước gọi con phân giải phiên bản live lúc chạy.
- 23/10/2026 (agent, tạm theo khuyến nghị (a)): DO-31 — phê duyệt hết hạn làm lượt chạy `failed` với
  `approval_expired` khi không có Nhánh ra `expired`; không gì tự duyệt khi quá giờ. Hỏi: DO-31. Sửa:
  R9.4, WN10. Nếu sai thì: đổi cách xử lý cạnh hết hạn thiếu.
- 23/10/2026 (agent, tạm theo khuyến nghị (a)): DO-36 — người duyệt phải giữ quyền đọc các Trường phê
  duyệt hiển thị; ứng viên duyệt theo độ sâu vai qua `effective_grants`. Hỏi: DO-36. Sửa: R9.1, R9.2.
  Nếu sai thì: giới hạn ứng viên duyệt về đúng workspace của lượt chạy.
- 23/10/2026 (agent, tạm theo khuyến nghị (a)): DO-37 — quy tắc kiểm hợp lệ nghĩa là "điều kiện để lưu
  được" (true là hợp lệ), viết bằng CEL với vector test đã port của si-platform. Hỏi: DO-37. Sửa: R3.
  Nếu sai thì: đổi sang ngữ nghĩa "lỗi khi" và cân nhắc port thẳng `rules.py`.
- 23/10/2026 (agent, tạm theo khuyến nghị (a)): DO-18 — nurture ở W2; mỗi tin ra ngoài trong pilot qua
  một phê duyệt trong hàng đợi bàn phím nhanh, không duyệt hàng loạt. Hỏi: DO-18. Sửa: Ngoài phạm vi.
  Nếu sai thì: xét duyệt theo mẫu có lấy mẫu sau khi có số đo shadow.
- 23/10/2026 (agent, tạm): Học theo mẫu đầu ra node kiểu hóa của phân tích chang.fpt.net (config-chang.md
  mẫu 2): mỗi Loại bước công bố đầu ra có tên và kiểu, `error` là đầu ra tùy chọn dưới Khi lỗi
  `continue` (YC47). Đây là mẫu học được, không phải mã của họ. Sửa: R1.5. Nếu sai thì: bỏ `error` tùy
  chọn, mọi lỗi đi Nhánh ra lỗi cố định.
- 23/10/2026 (agent, tạm): Học theo mẫu "mô tả ngữ nghĩa AI cho từng trường" (config-chang.md mẫu 1):
  mục bối cảnh của `ai.llm` mang một nhãn mô tả cho model, nhưng nhãn đó cũng là dữ liệu từ ngoài nên
  bao chứa khi vào prompt (YC48). Đây là mẫu học được, không phải mã của họ. Sửa: R7.2. Nếu sai thì: bỏ
  nhãn mô tả khỏi mục bối cảnh.
- 23/10/2026 (Đạt): xác nhận nội dung dòng "workflow-nodes sở hữu `ExpressionEngine`; Protocol ở
  `dw_kernel.expressions`, adapter ở `dw_studio`" ghi ngày 23/10/2026 ở trên.
- 23/10/2026 (người đặt yêu cầu và Đạt): xác nhận nội dung dòng D11 ở trên: hai người cho mọi phát hành;
  phát hành quy trình cần một người khác người chạy giữ `required_scope`.
- 23/10/2026 (Đạt): DO-38 (a) và ADR-0114 (Accepted): `cel-expr-python==0.1.3` (C++) là mặc định,
  `common-expression-language==0.10.0` (Rust) là dự phòng qua cùng bộ test hợp đồng, nếu số đo FOG-50 giữ
  được; luật chọn sau nhánh thử ghi ở ticket 01. Hỏi: Q1. Sửa: ticket 01.
- 23/10/2026 (Đạt): DO-03.2 (a): port mã si-platform theo thỏa thuận viết với chủ mã: ghim commit mỗi lần,
  dòng đầu `Ported from si-platform`, không đồng bộ; vector test `rules.py` lấy hợp lệ, chưa có thỏa thuận
  trước P1 thì viết lại theo cùng vector. Sửa: ticket 01.
- 23/10/2026 (Đạt): xác nhận các quyết định tạm DO-30 (a), DO-31 (A), DO-36 (A), DO-37 (a), DO-18 (a) ở
  trên; DO-31 đổi: hết hạn phê duyệt dời sang W2 cùng YC52 và lane hẹn giờ, W1 phê duyệt chờ không hạn
  (H:workflow-nodes:R9.4). Sửa: Ngoài phạm vi (R9.4, WN10), ticket 06.
- 23/10/2026 (Đạt): DO-36 (A): field-security là chủ luật người duyệt phải đọc được trường
  (field-security:R4.5); Bước phê duyệt đóng dấu tên Trường và `decision_guards` của `studio.step.approval`
  từ chối ở `decide` người thiếu quyền đọc, qua guard async của tenant-config/05. Sửa: R9.7, R9.8, WN17,
  ticket 06.
- 23/10/2026 (Đạt): Q6 (a): người dự phòng là một điểm gắn kind `principal` trong Bộ giá trị gắn duyệt hai
  người, kiểm bằng `effective_grants` như mọi ứng viên; không hợp lệ thì đi Nhánh ra lỗi; nhóm ở W2; spec này
  là chủ quy tắc giao. Sửa: R6.2, R6.3, R6.4, WN16, Ngoài phạm vi, ticket 04.
- 23/10/2026 (Đạt): Q9 (a): cờ Hạn chế xử lý, sổ sự cố và yêu cầu chủ thể ở W2, nên R7.3 và WN14 dời sang
  W2. Sửa: Ngoài phạm vi, Phụ thuộc, ticket 05.
- 23/10/2026 (Đạt): giả lập ghi bản ghi nằm ở RecordService; Bước bản ghi chỉ chuyển Chế độ chạy qua
  `RecordsPort` (D:custom-objects:R5.4~workflow-nodes:R5.3). Sửa: R5.3, R5.5, ticket 04.
- 23/10/2026 (Đạt): khóa phát hành chung `studio.publish.approve` của agent-lifecycle; bỏ
  `studio.workflows.publish`; R9.5 thành kiểm theo loại spec này đăng ký qua Protocol ở composition root
  (D:agent-lifecycle:R2.1~workflow-nodes:R9.5). Sửa: R9.5, API, Trong phạm vi, ticket 06.
- 23/10/2026 (Đạt): spec này mở phê duyệt bước, workflow-engine giữ điểm chờ và handler; mã từ chối người
  quyết theo một bảng ở ADR-0004 (Accepted): ngoài tầm thấy 404, mọi luật tách nhiệm 409, thấy được mà
  thiếu quyền hay không được giao 403 (B:workflow-engine:R6.2~workflow-nodes:R9.2). Sửa: R9.2, R9.6, WN8,
  ticket 06.
- 23/10/2026 (Đạt): Kết quả giả lập ghim theo Bước do spec này làm ở W2; W1 dùng giá trị sinh từ output
  schema (H:CONTEXT.md#mock-output~workflow-engine:ngoài-phạm-vi). Sửa: Ngoài phạm vi.
- 23/10/2026 (Đạt): BS (b): spec này là chủ lịch làm việc và ngày lễ cho `time.add_workdays` (BS35), làm
  ở W2 trước khi cắt ticket W2. Sửa: Ngoài phạm vi.
- 23/10/2026 (Đạt): DO-48.1 (a): thí điểm dùng SMTP chung, nên test WN7 dùng `email.send` của `smtp@1.0.0`
  thay ZNS (W2). Sửa: WN7, ticket 06.
- 23/10/2026 (Đạt): ADR-0108 (Accepted): route biểu thức theo dạng sub-resource `/expressions/check`,
  `/expressions/evaluate`. Sửa: Trong phạm vi, API, ticket 01.
- 23/10/2026 (agent, tạm): theo phát hiện `A:workflow-engine:R2.2~workflow-nodes:R1.3` mà ADR-0112 (Accepted)
  đóng: R2.4, R3.2, R3.3 trả mã của bảng `wf.*` ở workflow-engine:R2; kiểm `type@major` chưa đăng ký rời
  spec này sang workflow-engine:R2.14 nên R1.3 rút; "bộ kiểm phát hành" đổi thành "bộ kiểm khi gửi kiểm
  định" (`G:CONTEXT.md#submit~workflow-builder-ui:BU3`). Sửa: R1.3, R2.4, R3, R4.4, API, WN5, WN9, WN11, ticket
  02, 03. Nếu sai thì: spec này giữ bảng mã riêng và workflow-engine dẫn chiếu nó.
- 23/10/2026 (agent, tạm): sửa phát hiện B:compliance-pdpl:CP7~workflow-nodes:R8.4: dùng đúng mã
  `blocked:no_consent` của compliance-pdpl. Sửa: R8.4, WN7, ticket 06.
- 23/10/2026 (agent, tạm): sửa phát hiện I:compliance-pdpl/04~workflow-nodes/06: ticket 06 chờ
  compliance-pdpl/04 (sàn gửi tin thật). Sửa: ticket 06.
- 23/10/2026 (agent, tạm): Phụ thuộc trỏ D11 cho phát hành về agent-lifecycle:R5.2 thay tenant-rbac:R7.1, vì
  tenant-rbac:R7.1 là luật hai người cho đổi vai trò. Sửa: Phụ thuộc.
- 24/10/2026 (Đạt): N2: trong lượt `simulate` (và `test` từ W2) Bước phê duyệt không chờ người quyết thật; quyết
  định giả lập lấy từ biểu mẫu chạy mô phỏng (người thử chọn duyệt hay từ chối) hay từ Câu kiểm định của Cổng chất
  lượng, ghi audit `studio.step.approval.simulated`, không bao giờ thỏa một phê duyệt `live`
  (D:workflow-nodes:R9.6~workflow-triggers:R3.3). Sửa: R9.1, R9.9, R9.10, R9.11, WN18, Trong phạm vi, Phụ thuộc,
  ticket 06.
- 24/10/2026 (agent, tạm): lượt mô phỏng tới một Bước phê duyệt mà không có quyết định giả lập cho Bước đó thì
  `failed` với `simulated_decision_missing`, không chọn nhánh nào thay người thử (failure-modes #7); route
  `.../test-runs` đã từ chối thân thiếu quyết định (workflow-triggers:R2.8), nên ca này chỉ tới từ một Câu kiểm định
  thiếu quyết định. Sửa: R9.12, WN18, API, ticket 06. Nếu sai thì: Bước đi Nhánh ra từ chối thay vì làm lượt
  `failed`.
- 24/10/2026 (Đạt): N3: Bước `ai.llm` đọc `Mô tả cho AI` của đối tượng và trường như dữ liệu từ bên ngoài, bao như
  YC48 (YC101, W1). Sửa: R7.5, WN2, Phụ thuộc, ticket 05.
- 24/10/2026 (Đạt): Bước `ai.llm` dùng `assemble_system_prompt` và linter của agent-builder/02 (ADR-0117 (Accepted)
  quyết 4): khung prompt riêng thì được, linter riêng thì không; ticket 05 chờ agent-builder/02
  (A:agent-builder:R2.2~workflow-nodes/05). Sửa: Phụ thuộc, ticket 05.
- 24/10/2026 (Đạt): R9.5 là kiểm lúc gửi kiểm định đăng ký vào bảng kiểm theo loại của agent-lifecycle:R2.7, trả 422
  `no_second_approver`; dòng này thay cách gọi "kiểm phát hành" của dòng ngày 23/10/2026 về khóa phát hành chung;
  ticket 06 chờ agent-lifecycle/03 (B:agent-lifecycle:R2.7~workflow-nodes:R9.5). Sửa: R9.5, WN8, API, Trong phạm
  vi, Phụ thuộc, ticket 06.
- 24/10/2026 (Đạt): người yêu cầu thiếu `required_scope`, hay người giữ `required_scope` mà không được giao, nhận
  403; mọi người khác không thấy yêu cầu có tem nên nhận 404; bảng ba mã nằm ở ADR-0104 (Accepted) quyết 11, còn
  ADR-0004 (Accepted) giữ tem và tầm thấy; dòng ngày 23/10/2026 dẫn bảng ở ADR-0004 (Accepted) đọc theo chỗ mới
  (phát hiện D về ADR-0004 (Accepted) và R9.2; phát hiện F về ADR-0004 (Accepted) và workflow-engine). Sửa: R9.2,
  R9.6, WN8, API, Phụ thuộc, ticket 06.
- 24/10/2026 (Đạt): khóa chống lặp của mọi hiệu ứng có một ngữ pháp do workflow-engine:R4.5 làm chủ, vì wrapper nút
  dẫn khóa; Bước không tự viết khóa (B:workflow-engine:R4.5~workflow-nodes:R5.1). Sửa: R5.1, R8.1, WN6, ticket 04, 06.
- 24/10/2026 (Đạt): Bước giao gọi dịch vụ giao của record-access qua một Protocol spec này khai, không gọi
  `studio.assign_record` và không tự ghi audit, nên audit và outbox `studio.record.assigned` có một người ghi
  (B:record-access:R8.7~workflow-nodes:R6.3). Sửa: R6.3, WN16, Phụ thuộc, ticket 04.
- 24/10/2026 (Đạt): ở W1 Bước phê duyệt chỉ thu hẹp theo người và Biểu thức, `assignee_kind` CHECK chỉ `user`;
  nhóm vào dòng W2 (H:workflow-nodes:R9.1~workflow-nodes:ngoài-phạm-vi). Sửa: R9.1, Dữ liệu, Ngoài phạm vi,
  ticket 06.
- 24/10/2026 (Đạt): `studio.step_approvals.approval_request_id` là chủ duy nhất của liên kết từ Bước phê duyệt tới
  yêu cầu, nối với dòng chờ qua FK `(tenant_id, run_id, interrupt_id)`, và spec này đáp ứng `StepWaitLookupPort` của
  workflow-engine (A:workflow-engine:dữ-liệu~workflow-nodes:dữ-liệu). Sửa: Dữ liệu, Trong phạm vi, Phụ thuộc,
  ticket 06.
- 24/10/2026 (Đạt): N7: Duyệt thay (YC104) và Bước `logic.loop` có `max_iterations` (YC105) là W2 của spec này,
  vòng lặp cùng workflow-engine; N9: duyệt song song k trên n, cùng workflow-engine, và bảng quyết định hay ma trận
  duyệt theo ngưỡng là W3, nguyên liệu chung của các gói sau gói Bán hàng. Sửa: Ngoài phạm vi.
- 24/10/2026 (Đạt): ticket 06 chỉ thêm đúng một dòng `|=` cho `studio.step.` và một mục `decision_guards` của
  `studio.step.approval`, không sửa dòng của ticket khác, kèm test khẳng định tập tiền tố có `studio.step.`; theo cách
  sửa thứ hai của C:agent-lifecycle:R7.10~tenant-config:R8.8, như agent-lifecycle/04, không thêm cạnh Blocked by vì
  cạnh agent-lifecycle/04 tới ticket 06 tạo vòng. Sửa: ticket 06.
- 24/10/2026 (Đạt): V4.10: người duyệt thay (W2, YC104) phải giữ khóa đóng dấu của loại phê duyệt và
  `approvals.decide`, không phải người tạo lượt chạy (YC51), và chỉ được giao có thời hạn (từ, đến), có audit;
  ngoài các điều kiện đó guard vẫn trả 403 như ADR-0104 (Accepted) quyết 11; ADR-0112 (Accepted) quyết 7 và
  ADR-0104 (Accepted) quyết 11 ghi điều kiện từ W2, nên không còn câu hỏi mở cho Đạt (phát hiện D về
  ADR-0112 (Accepted) và spec này). Sửa: Ngoài phạm vi.
- 24/10/2026 (agent, tạm): V4.P9: lần từ chối của tiền tố nghiêm mang `details.reason_code` `second_person_required`
  cho mọi loại phê duyệt, do `_enforce_strict_rules` của tenant-config/05 đặt, còn `author_cannot_approve` là mã
  của guard tác giả `studio.publish.`; ADR-0104 (Accepted) quyết 11 ghi tên đó (phát hiện
  B:packages:spec~tenant-config/05). Sửa: R9.6, API, WN8, Phụ thuộc, ticket 06. Nếu sai thì: R9.6 trả 409 không
  mã như trước và WN8 bỏ khẳng định mã.
- 24/10/2026 (agent, tạm): V4.P11: `logic.loop` đến `max_iterations` thì đi Nhánh ra `max_reached`; không nối Nhánh
  ra đó thì lượt chạy `failed` với `error.code` `loop_limit_reached`; bảng thuật ngữ thêm mục Bước vòng lặp
  (phát hiện G:docs:spec~workflow-nodes:spec). Sửa: Ngoài phạm vi. Nếu sai thì: lượt luôn `failed` ở trần, hay
  Bước luôn đi Nhánh ra lỗi.
- 24/10/2026 (agent, tạm): V4.P13: workflow-nodes/01 ship cả `CelCppEngine` (`cel-expr-python`, ghim chính xác) và
  `CelRustEngine` (`common-expression-language==0.10.0`) sau `ExpressionEngine`, một bộ test hợp đồng cho cả hai,
  composition root chọn theo setting, như ADR-0114 (Accepted) quyết 2; ở profile triển khai (`settings.is_deployed`)
  setting phải chọn `cel-expr-python`, và một test đỏ khi nó trỏ sang bản Rust; chuyển profile triển khai sang bản
  Rust thì sửa CLAUDE.md mục Required stack trong cùng thay đổi (phát hiện E về CLAUDE.md mục Required stack và
  ticket 01). Lượt b của vòng 4 sửa dòng này: bản lượt a, W1 chỉ ship `cel-expr-python` và không setting, trái
  ADR-0114 (Accepted) quyết 2. Sửa: Hiện trạng, R3.6, Trong phạm vi, WN12, WN19, Phụ thuộc, ticket 01. Nếu sai thì: ticket 01
  chỉ ship `CelCppEngine`, không setting, và ADR-0114 (Accepted) quyết 2 bỏ bản dự phòng cùng setting.
- 24/10/2026 (agent, tạm): sửa phát hiện CRITICAL F về ADR-0112 (Accepted) và workflow-engine:R2: R3.2, R3.3 và
  API dùng `wf.ref_not_dominating`, `wf.type_mismatch` của ADR-0112 (Accepted) quyết 3 qua bảng mã của
  workflow-engine:R2. Sửa: R3.2, R3.3, API, ticket 03.
- 24/10/2026 (agent, tạm): sửa phát hiện B:agent-lifecycle:R4.7~workflow-nodes:R9.9: từ vựng quyết định giả lập
  `approved`, `rejected` có một chủ là R9.9; workflow-triggers:R2.7 và agent-lifecycle:R4.7 dùng nguyên. Sửa: R9.9.
- 24/10/2026 (agent, tạm): sửa phát hiện A về ADR-0112 (Accepted) và đoạn mở đầu: số Loại bước của danh mục đầy
  đủ dẫn từ ADR-0112 (Accepted) quyết 2, không chép. Sửa: đoạn mở đầu.
- 24/10/2026 (agent, tạm): sửa phát hiện F về ADR-0112 (Accepted) và R9.5: lúc mở phê duyệt mà `effective_grants`
  không còn ứng viên hợp lệ thì Bước đi Nhánh ra lỗi với `no_approver`, không nối Nhánh ra đó thì lượt `failed`
  với `no_approver` (ADR-0112 (Accepted) quyết 7). Sửa: R9.13, Trong phạm vi, API, WN8, Phụ thuộc, ticket 06.
- 24/10/2026 (agent, tạm): sửa phát hiện G:CONTEXT.md#run-mode~tenant-config:spec: bảng của kết quả giả lập ghim
  gọi là bảng chạy mô phỏng. Sửa: Ngoài phạm vi.
- 24/10/2026 (agent, tạm): sửa phát hiện A:code-sandbox:R2.3~workflow-nodes:spec: spec này đăng ký khóa
  `studio.code.author` cùng Loại bước `code.python` ở W2, còn `CodeExecutionService` của code-sandbox kiểm quyền
  lợi `code_node` trước runner. Sửa: Ngoài phạm vi.
- 24/10/2026 (agent, tạm): lượt c của vòng 4: `studio.step_assignments.run_id` là FK ghép `(tenant_id, run_id)` tới
  `uq_worker_runs_tenant_id_id` của workflow-engine/02, và `studio.step_approvals.approval_request_id` là FK ghép
  `(tenant_id, workspace_id, approval_request_id)` qua `uq_approval_requests_tenant_id_workspace_id_id` đã có
  (`db/migrations/versions/e399be8c0a2d_platform_approval_view_receipts_and_.py:127-129`), vì kiểm khóa ngoại không qua
  RLS nên một FK một cột để dòng của một công ty trỏ tới lượt chạy hay yêu cầu phê duyệt của công ty khác (CLAUDE.md,
  Tenancy and authorization); `studio.step_approvals` mang `workspace_id`, nên đi qua UNIQUE đã có mà
  `platform.approval_view_receipts` và tenant-config/05 dùng, ticket 06 không thêm UNIQUE nào lên
  `platform.approval_requests`, và FK ba cột còn buộc dòng `step_approvals` cùng workspace với yêu cầu; vỏ phiên bản
  toàn tenant không mang cột đó, nên agent-lifecycle/03 thêm `uq_approval_requests_tenant_id_id` cho FK của
  `publish_approval_id`. Sửa: Dữ liệu, Phụ thuộc, ticket 06. Nếu sai thì: FK hai cột `(tenant_id, approval_request_id)`
  qua `uq_approval_requests_tenant_id_id` mà agent-lifecycle/03 thêm, ticket 06 đã chờ ticket đó.
- 24/10/2026 (agent, tạm): lượt c của vòng 4: `CelCppEngine` và `CelRustEngine` ở `dw_studio.core.adapters.cel`, vì
  studio-skeleton làm chủ bố cục gói và R5.6 của nó chỉ cho gói đó import thư viện CEL; ticket 01 viết hợp đồng
  import-linter đó với tên module import thật của hai binding, như Ngoài phạm vi của studio-skeleton giao
  (studio-skeleton:R5.6); Protocol vẫn ở `dw_kernel.expressions` như dòng của Đạt ngày 23/10/2026. Sửa: Trong phạm vi,
  Phụ thuộc, ticket 01. Nếu sai thì: adapter ở một gói khác của `dw_studio`, và studio-skeleton:R5.6 đổi tên gói trong
  cùng thay đổi.
- 24/10/2026 (agent, tạm): các dòng Quyết định của spec này và Comments của ticket 01, 06 mà lượt b, c của vòng 4
  viết thôi dẫn mã mục riêng của hai lượt đó, nội dung giữ nguyên, vì nhãn duy nhất của vòng 4 là `V4.n` và `V4.Pn`
  mà area file định nghĩa (`.claude/plans/studio.md`, mục State, Round 4). Sửa: Quyết định, ticket 01, 06. Nếu sai
  thì: các dòng đó dẫn lại mã mục, kèm một bảng mã trong area file.
- 24/10/2026 (agent, tạm): hai FK ghép mới, `studio.step_assignments.run_id` và
  `studio.step_approvals.approval_request_id`, có một tiêu chí từ chối chéo tenant và một kiểm soát với test đột biến,
  vì test âm cho đọc và ghi chéo tenant là bắt buộc (CLAUDE.md, Tenancy and authorization) và một FK ghép chưa thấy đỏ
  khi đổi về FK một cột là test không hỏng được (failure-modes #3); ca âm của ticket 06 rời tiêu chí R9.1 sang tiêu chí
  mới; FK của `studio.step_approvals` tới dòng chờ nêu chỉ mục `(tenant_id, run_id, interrupt_id)`, vì mọi khóa ngoại
  có chỉ mục dẫn bằng cột của nó (CLAUDE.md, Data model rules). Sửa: thêm R9.14, thêm WN20, Dữ liệu, ticket 06. Nếu
  sai thì: ca âm về tiêu chí R9.1 của ticket 06, không kiểm soát riêng.
- 24/10/2026 (Đạt): V4.14: mọi lượt chạy có hạn chót `deadline_at` ở W1 (workflow-engine:R5.22), mặc định 30 ngày, tối
  đa 90, gồm cả thời gian chờ; quá hạn thì lượt kết thúc với `deadline_exceeded`, chờ và phê duyệt đang mở của nó bị
  hủy cùng; route hủy vẫn là W2; hết hạn riêng của Bước phê duyệt (R9.4, WN10) vẫn ở W2 cùng YC52, nên dòng DO-31 ngày
  23/10/2026 "W1 phê duyệt chờ không hạn" đọc thành: Bước phê duyệt không có hạn riêng, còn phê duyệt mở bị hủy cùng
  lượt ở hạn chót. Sửa: R9.15, Trong phạm vi, Ngoài phạm vi (R9.4), WN21, Phụ thuộc, ticket 06.
- 24/10/2026 (agent, tạm): áp V4.14: phê duyệt đang mở bị hủy theo dòng chờ của nó, bằng một trigger nghe dòng
  `platform.run_waits` sang `cancelled` (workflow-engine:R6.13) và đặt yêu cầu `pending` nối qua `studio.step_approvals`
  sang `cancelled` trong cùng giao dịch, vì lượt quá hạn chót sang `cancelled` (workflow-engine:R5.23) và dòng chờ của
  nó bị hủy ở đó, nên mọi đường hủy, kể cả lane Tắt khẩn, đi qua cùng một chỗ (failure-modes #5); việc "huỷ lượt chạy
  huỷ phê duyệt đang mở" mà ticket 06 đã ghi thành tiêu chí R9.15 có kiểm soát riêng. Sửa: R9.15, WN21, ticket 06. Nếu
  sai thì: dịch vụ hủy lượt của workflow-engine gọi hủy yêu cầu qua một Protocol mà spec này đáp ứng, và R9.15 đổi
  chủ thể.

## Danh sách ticket

| #   | Ticket                                                                         |
| --- | ------------------------------------------------------------------------------ |
| 01  | [CEL và cổng ExpressionEngine](issues/01-cel-va-expression-engine.md)          |
| 02  | [Sổ đăng ký loại bước và mẫu chuỗi](issues/02-so-dang-ky-buoc-va-mau-chuoi.md) |
| 03  | [Phạm vi biến và các bước logic](issues/03-pham-vi-bien-va-buoc-logic.md)      |
| 04  | [Bước dữ liệu đối tượng và giao](issues/04-buoc-du-lieu-doi-tuong-va-giao.md)  |
| 05  | [Bước ai.llm](issues/05-buoc-ai-llm.md)                                        |
| 06  | [tool.call và human.approval](issues/06-tool-call-va-human-approval.md)        |
