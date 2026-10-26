# Danh mục bước v1, ngôn ngữ biểu thức CEL và các bước con người

Status: needs-info (Q10)
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Người dựng không viết mã ghép một quy trình từ các Bước, thành một cây Bước (V4.24). Mỗi Loại bước là mã nền
tảng trong một sổ đăng ký duy nhất, mang schema cấu hình và đầu ra, các Nhánh ra mà mỗi Bước của loại mang
thành một làn Bước lồng trong nó, mức tác động, chính sách Khi lỗi và giới hạn; mỗi Bước có tối đa một tác
dụng phụ, đi qua đúng cửa của loại. Biểu thức và chuỗi có biến của công ty là CEL, tính ở máy chủ sau một
cổng, kiểm kiểu khi gửi kiểm định, có trần chi phí, không bao giờ chạy như mã và không bao giờ tính trong
trình duyệt. Các Bước phê duyệt là cổng do máy chủ thực thi. Lát Tiếp nhận lead của Marketing (D4) cần sáu
lát bước trong P1; bậc B của W1 (V4.26, V4.33), sau đường găng YC94 và không ticket thí điểm nào chờ, thêm Bước song
song, Bước vòng lặp, Thoát vòng lặp, Bước phê duyệt cần mọi người được giao và Bước Quy trình con; danh mục đầy đủ mà
ADR-0112 (Accepted) quyết 2 đếm là W2 trở đi.

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
  khác của loại), với `error` chỉ khi Khi lỗi đặt `continue` hay `route`, để Bước kế tiếp (`continue`) và các
  Bước của làn lỗi (`route`) đọc được lỗi.
- R1.6 Loại bước `logic.parallel@1`, `logic.loop@1` và `logic.break@1` PHẢI chỉ cho Khi lỗi `fail` và không
  công bố `error`, vì lỗi của một Bước trong làn hay trong thân của chúng đi theo Khi lỗi của chính Bước đó.

### R2 — Một tác dụng phụ mỗi bước, đúng cửa theo loại

Mỗi Bước đổi tối đa một thứ bên ngoài, qua cửa mà loại hiệu ứng đó sở hữu (NODE-02).

- R2.1 Mỗi Bước PHẢI có tối đa một tác dụng phụ, đi qua đúng cửa của loại: `ToolExecutor` cho tác động
  ngoài, `RecordsPort` cho bản ghi, cửa thông báo cho thành viên, bộ phân giải model cho model,
  `CodeSandboxPort` cho mã, cửa xin lượt con của workflow-engine cho lượt con của Bước Quy trình con (R13.5, R13.7).
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
  (workflow-engine:R4.5), không tự dựng khoá, và lệnh sửa một bản ghi có sẵn của nó chỉ mang các trường mà cấu hình
  của Bước nêu, không bao giờ cả bản ghi đã đọc, để hai làn song song sửa hai trường khác nhau của cùng một bản ghi
  đều giữ giá trị của mình (PATCH theo trường; workflow-engine:R7.3; V4.34).
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
- R6.4 NẾU người dự phòng cũng không hợp lệ, THÌ Bước `data.object.assign` PHẢI kết thúc với lỗi theo Khi lỗi
  của nó (làn lỗi khi `route`) và không giao bản ghi cho ai.
- R6.5 KHI Bước `data.object.assign` gọi dịch vụ giao, Bước đó PHẢI chuyển đúng khoá chống lặp mà wrapper nút dẫn
  (workflow-engine:R4.5), để một lần chạy lại sau khi worker chết phát lại người đã giao theo khoá đó, không chọn
  người kế tiếp trong vòng xoay (mức bảo đảm nội bộ của YC41; V4.30).

### R7 — ai.llm kiểm phía server, bao chứa, tôn trọng opt-out

Bước chấm điểm trả đầu ra theo lược đồ người dựng đặt, không để nội dung lead thành chỉ dẫn (YC47, YC48,
YC49, YC87; NODE-07, NODE-08).

- R7.1 KHI Bước `ai.llm` nhận câu trả lời của model, Bước đó PHẢI kiểm theo JSON Schema của công ty,
  sửa tối đa một lần, và khi vẫn sai thì trả `output_invalid` ở đầu ra `error` (R1.5), để với Khi lỗi `continue`
  hay `route` lượt chạy không dừng (YC47).
- R7.2 KHI Bước `ai.llm` dựng prompt, Bước đó PHẢI đưa mọi giá trị bản ghi vào prompt chỉ qua khối
  `<input>` thoát và cắt ở 16 KiB.
- R7.3 NẾU bản ghi mang cờ `ai_opt_out` hoặc `processing_restricted`, THÌ Bước `ai.llm` PHẢI bỏ qua
  bản ghi đó và không gọi model.
- R7.4 KHI Bước `ai.llm` chấm điểm lead, đầu vào gửi model PHẢI không chứa định danh trực tiếp (họ tên,
  số điện thoại, email, Zalo id), với số điện thoại và email trong văn bản tự do bị che.
- R7.5 KHI Bước `ai.llm` đưa một đối tượng hay một trường vào prompt, Bước đó PHẢI đưa `Mô tả cho AI`
  (`ai_description`) của đối tượng và của trường chỉ qua khối `<input>` thoát, cắt ở 16 KiB, như dữ liệu từ bên
  ngoài (YC101, YC48).

### R8 — tool.call qua ToolExecutor, với khoá chống lặp và mức bảo đảm của Hành động

Bước gọi công cụ đi qua một cửa với khoá chống lặp của wrapper nút; số lần nhà cung cấp áp dụng một tác động theo mức
bảo đảm mà hợp đồng giao nhận của Hành động khai, và một lời gọi không rõ kết quả làm theo `on_unknown` của Hành động,
mà ở W1 chỉ là `review` (H-5): không bao giờ tự gửi lại, lượt đỗ ở điểm chờ `outcome_review` của workflow-engine
(`.claude/plans/studio/workflow-engine/issues/08-tac-dong-khong-ro-ket-qua.md`) và không đi làn lỗi (YC41; V4.30;
NODE-11).

- R8.1 KHI Bước `tool.call` gọi một công cụ, Bước đó PHẢI gọi `ToolExecutor.execute` với đúng khoá chống lặp
  mà wrapper nút dẫn (workflow-engine:R4.5) và phiên bản công cụ đã ghim lúc gửi kiểm định.
- R8.2 KHI hai lần chạy song song của một Bước `tool.call` dùng cùng khoá chống lặp trong lúc claim của lần chạy đầu
  còn hạn, `ToolExecutor` PHẢI chỉ để một trong hai lần gọi handler của Hành động, là mức bảo đảm đồng thời của YC41
  (V4.30).
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
  (giữ `required_scope`, được giao, khác người tạo lượt chạy và chủ thể chạy), THÌ Bước phê duyệt PHẢI kết thúc
  với `no_approver`, đi làn lỗi khi Khi lỗi là `route` và làm lượt chạy `failed` khi là `fail` (R9.17), và không
  mở yêu cầu phê duyệt nào (ADR-0112 (Accepted) quyết 7).
- R9.14 NẾU một lệnh ghi của `dw_app` gắn tenant A đặt `run_id` của một dòng `studio.step_assignments` bằng id một
  lượt chạy của tenant B, hay `approval_request_id` của một dòng `studio.step_approvals` bằng id một yêu cầu phê duyệt
  của tenant B, THÌ PostgreSQL PHẢI từ chối lệnh đó bằng FK ghép của cột đó và không ghi dòng nào, vì kiểm khóa ngoại
  không qua RLS (CLAUDE.md, Tenancy and authorization).
- R9.15 KHI một lượt chạy sang `cancelled` theo bất kỳ đường nào, kể cả Tắt khẩn và quá hạn chót với `deadline_exceeded`
  (workflow-engine:R5.23), PostgreSQL PHẢI đặt mọi yêu cầu phê duyệt `studio.step.` đang `pending` của lượt đó sang
  `cancelled` trong cùng giao dịch, để không ai quyết được phê duyệt của một lượt đã kết thúc (V4.14).
- R9.16 KHI lượt chạy tiếp tục sau quyết định của một Bước phê duyệt ở chế độ `live`, Bước phê duyệt PHẢI chạy
  làn `approved` ("Duyệt") khi quyết định là duyệt và làn `rejected` ("Từ chối") khi là từ chối, không bao giờ làn
  kia, vì mỗi kết quả của phê duyệt là một Nhánh ra mang làn Bước của nó (V4.24).
- R9.17 NẾU cấu hình một Bước phê duyệt đặt Khi lỗi khác `fail` hay `route`, THÌ schema của `human.approval@1`
  PHẢI từ chối cấu hình đó, để một Bước phê duyệt lỗi không bao giờ cho lượt chạy đi tiếp như thể đã có quyết định
  (failure-modes #7).

### R10 — Bước song song `logic.parallel@1`, gộp ở Điểm nối khi mọi làn xong

Người dựng chạy các làn Bước cùng lúc và đi tiếp đúng một lần khi mọi làn đã xong, ở bậc B của W1 (YC108; V4.24,
V4.26). Spec này đăng ký loại; cách chạy của khối (mỗi làn theo nhịp riêng, Bước sau Điểm nối chạy đúng một lần) là
của trình biên dịch của workflow-engine (workflow-engine:R4.14, workflow-engine:R4.15; ADR-0112 (Accepted) quyết 2, 4).

- R10.1 Schema cấu hình của `logic.parallel@1` PHẢI nhận từ 2 làn trở lên, mỗi làn một Nhánh ra có khóa khớp
  `^[a-z][a-z0-9_]{0,39}$` và duy nhất trong Bước, và từ chối cấu hình một làn hay hai làn cùng khóa.
- R10.2 NẾU một tài liệu mang Bước `logic.join@1`, THÌ bộ kiểm khi gửi kiểm định PHẢI trả `wf.unknown_node_type`
  (workflow-engine:R2.14) và không niêm phong, vì Điểm nối là cuối các làn của Bước song song, không là Loại bước
  riêng (V4.24).
- R10.3 NẾU một Bước `flow.stop` nằm ở bất kỳ độ sâu nào trong một làn của Bước song song, kể cả trong làn lỗi của
  một Bước trong làn đó, THÌ bộ kiểm khi gửi kiểm định PHẢI trả `wf.stop_in_parallel` (workflow-engine:R2.15) và
  không niêm phong, vì một lối kết thúc lượt trong làn cho lượt `completed` mà Điểm nối và các Bước sau không chạy
  (đo được; ADR-0112 (Accepted) quyết 3).
- R10.4 NẾU một Bước phê duyệt nằm ở bất kỳ độ sâu nào trong một làn của Bước song song, THÌ bộ kiểm khi gửi kiểm
  định PHẢI trả `wf.wait_in_parallel` (workflow-engine:R2.16) và không niêm phong, vì mỗi làn biên dịch thành một
  subgraph có namespace checkpoint riêng, nên một Bước đỗ trong làn nằm ngoài đồ thị gốc, nơi kiểm (b) của
  workflow-engine:R6.7 tìm node đang đỗ (ADR-0112 (Accepted) quyết 3, 4); cho mọi người cùng duyệt là R12.

### R11 — Bước vòng lặp `logic.loop@1` có trần và Thoát vòng lặp `logic.break@1`

Người dựng chạy lại một đoạn quy trình, kể cả vòng làm lại có phê duyệt, và ra sớm bằng Thoát vòng lặp, mà lượt
chạy không bao giờ vượt số vòng khai trong Bước, ở bậc B của W1 (YC105; V4.26). Spec này đăng ký hai loại; cách
chạy (thân chạy ít nhất một lần kiểu do-while, chạm `max_iterations` thì làn `max_reached` hay `loop_limit_reached`
theo V4.P11, Thoát vòng lặp rời vòng lặp gần nhất, mỗi vòng một khóa chống lặp và một điểm chờ riêng) là của
trình biên dịch và wrapper nút của workflow-engine (workflow-engine:R4.16 tới R4.19, workflow-engine:R6.17;
ADR-0112 (Accepted) quyết 2, 4, 5).

- R11.1 Schema cấu hình của `logic.loop@1` PHẢI bắt buộc một điều kiện "Lặp lại khi …" bằng CEL và `max_iterations`
  là số nguyên từ 1 trở lên (1 thì nhận, 0 thì từ chối), và từ chối cấu hình thiếu một trong hai.
- R11.2 Loại bước `logic.loop@1` PHẢI khai Nhánh ra `body` (thân) bắt buộc và Nhánh ra `max_reached` ("Đã đủ N
  lần") tùy chọn, để một Bước không mang làn `max_reached` làm lượt `failed` với `loop_limit_reached` ở trần
  (V4.P11).
- R11.3 NẾU một Bước Thoát vòng lặp không nằm trong thân của Bước vòng lặp nào, hay nằm ở bất kỳ độ sâu nào trong
  một làn của Bước song song, THÌ bộ kiểm khi gửi kiểm định PHẢI trả `wf.break_outside_loop` (workflow-engine:R2.17)
  và không niêm phong, vì Thoát vòng lặp chỉ ở trong thân vòng lặp và ngoài làn song song (V4.26).

### R12 — Bước phê duyệt cần mọi người được giao (k = n)

Người dựng đặt cho một Bước phê duyệt n người duyệt bắt buộc, mỗi người quyết đúng phần của mình, với một điểm
chờ: làn Duyệt chỉ khi cả n đã duyệt, làn Từ chối ở lần từ chối đầu tiên, ở bậc B của W1 (YC110, YC51; V4.26;
ADR-0112 (Accepted) quyết 7); k < n là W3 (Ngoài phạm vi).

- R12.1 Schema cấu hình của `human.approval@1` PHẢI nhận `approval_rule` là `any` (một người được giao duyệt là
  đủ), `all` (mọi người được giao phải duyệt) hay vắng mặt, đọc vắng mặt là `any`, và từ chối mọi giá trị khác, để
  tài liệu `human.approval@1` có trước khóa này giữ nguyên hành vi.
- R12.2 KHI một Bước phê duyệt `all` mở phê duyệt ở chế độ `live`, Bước đó PHẢI mở đúng một yêu cầu phê duyệt
  `studio.step.` cho mỗi người được giao khác nhau, cùng một điểm chờ và cùng mã băm chủ thể, trong một giao dịch,
  kể cả khi Bước chạy lại sau khi worker chết.
- R12.3 NẾU lúc một Bước phê duyệt `all` mở phê duyệt ở chế độ `live` có một người được giao không qua kiểm ứng
  viên của R9.13, THÌ Bước phê duyệt PHẢI kết thúc với `no_approver` như R9.13 và không mở yêu cầu nào, không bao
  giờ bỏ người đó rồi mở yêu cầu cho những người còn lại (failure-modes #7).
- R12.4 NẾU người quyết một yêu cầu của Bước phê duyệt `all` không phải người được giao của chính yêu cầu đó, THÌ
  `decision_guards` của `studio.step.approval` PHẢI trả 403 `permission_denied` và không quyết định, kể cả khi người
  đó được giao một yêu cầu khác của cùng Bước.
- R12.5 KHI một yêu cầu phê duyệt `studio.step.` được quyết, `StepWaitLookupPort` PHẢI trả cùng
  `(run_id, interrupt_id)` kết quả của điểm chờ: với `any` là chính quyết định đó; với `all` là `approved` khi mọi
  yêu cầu của điểm chờ đã duyệt, `rejected` ở lần từ chối đầu tiên, `pending` khi còn yêu cầu chưa quyết mà chưa ai
  từ chối.
- R12.6 KHI hai yêu cầu cuối của một điểm chờ `all` được duyệt trong hai giao dịch đồng thời, `StepWaitLookupPort`
  PHẢI trả `approved` cho đúng một trong hai lần quyết, để điểm chờ đóng đúng một lần và không kẹt `open`.
- R12.7 KHI điểm chờ của một Bước phê duyệt `all` rời `open` ở lần từ chối đầu tiên, PostgreSQL PHẢI đặt mọi yêu
  cầu `pending` còn lại của điểm chờ đó sang `cancelled` trong cùng giao dịch, để không ai quyết được phần của một
  điểm chờ đã đóng.
- R12.8 KHI một Bước phê duyệt `all` tiếp tục sau điểm chờ, Bước đó PHẢI đọc kết quả từ trạng thái các yêu cầu của
  điểm chờ, không từ giá trị tiếp tục, và chạy làn `approved` chỉ khi cả n yêu cầu đã duyệt, làn `rejected` khi một
  yêu cầu đã bị từ chối.
- R12.9 NẾU một Bước phê duyệt `all` tiếp tục khi còn yêu cầu chưa quyết mà chưa yêu cầu nào bị từ chối, THÌ Bước
  phê duyệt PHẢI làm lượt chạy `failed` với `error.code` `approval_incomplete` và không chạy làn nào, để làn Duyệt
  không chạy được dù điểm chờ bị đóng sớm ở nơi khác (failure-modes #5).

### R13 — Bước Quy trình con `flow.subworkflow@1`

Người dựng gọi một Quy trình dùng chung làm Quy trình con: lượt cha chờ lượt con ở một điểm chờ `child_run` rồi đọc
đầu ra có kiểu của nó, ở bậc B của W1, không ticket thí điểm nào chờ (YC117; V4.33). Spec này đăng ký loại; lượt con
(ghim lúc gửi kiểm định, lồng tối đa 3 cấp, hủy lượt cha thì mọi lượt con dừng trong ≤ 5 giây, điểm chờ `child_run`)
là của workflow-engine (`.claude/plans/studio/workflow-engine/issues/09-quy-trinh-con.md`; ADR-0109 (Accepted) quyết
9; ADR-0113 (Accepted) quyết 4, 9).

- R13.1 Schema cấu hình của `flow.subworkflow@1` PHẢI bắt buộc `workflow`, là `api_name` khớp
  `^[a-z][a-z0-9_]{1,39}$` của Quy trình được gọi [CAN LAM RO: Q10], nhận `inputs` là đối tượng từ tên trường tới
  Biểu thức, và từ chối mọi khóa khác, kể cả khóa chọn phiên bản, vì phiên bản con chỉ do lần gửi kiểm định ghim qua
  phụ thuộc mà bộ trích của loại trả (ADR-0109 (Accepted) quyết 4, 9).
- R13.2 Loại bước `flow.subworkflow@1` PHẢI công bố đầu ra `outputs`, có kiểu theo khai `outputs` của phiên bản con
  đã ghim (ADR-0112 (Accepted) quyết 1), và `outcomes`, danh sách tên các mục `outcomes[]` đúng khi lượt con kết thúc,
  cùng `error` theo R1.5.
- R13.3 NẾU một Bước `flow.subworkflow@1` nằm ở bất kỳ độ sâu nào trong một làn của Bước song song, THÌ bộ kiểm khi
  gửi kiểm định PHẢI trả `wf.wait_in_parallel` (workflow-engine:R2.16) và không niêm phong, vì Bước đó mở một điểm chờ
  `child_run` như mọi Bước chờ (V4.33).
- R13.4 NẾU cấu hình một Bước `flow.subworkflow@1` đặt Khi lỗi `incident`, THÌ schema của `flow.subworkflow@1` PHẢI
  từ chối cấu hình đó, vì sự cố đặt ở Bước lỗi bên trong Quy trình con, nơi Chạy tiếp từ Bước lỗi chạy lại đúng Bước
  đó (workflow-engine:R6.19).
- R13.5 KHI một Bước `flow.subworkflow@1` xin lượt con, Bước đó PHẢI chuyển nguyên Chế độ chạy của lượt cha cho cửa xin
  lượt con và không tự đặt chế độ, để lượt con của một lượt `simulate` không bao giờ chạy `live` (ADR-0113 (Accepted)
  quyết 9; ADR-0112 (Accepted) quyết 6).
- R13.6 NẾU `inputs` của một Bước `flow.subworkflow@1` thiếu một trường bắt buộc, mang một trường mà khai `inputs` của
  phiên bản con không có, hay có một Biểu thức không trả đúng kiểu trường đó khai, THÌ bộ kiểm khi gửi kiểm định PHẢI
  trả `wf.type_mismatch` (workflow-engine:R2.6) với con trỏ tới trường đó và không niêm phong.
- R13.7 KHI một Bước `flow.subworkflow@1` xin lượt con, Bước đó PHẢI chuyển đúng khoá chống lặp mà wrapper nút dẫn
  (workflow-engine:R4.5) cho cửa xin lượt con, để một lần chạy lại sau khi worker chết phát lại lượt con đã xin, không
  xin lượt con thứ hai (mức bảo đảm nội bộ của YC41; V4.30).

## Trong phạm vi

- `NodeTypeRegistry` và `build_node_registry(ports)` dựng ở cả hai composition root, với Nhánh ra của mỗi loại là
  một làn Bước lồng trong Bước của tài liệu dạng cây (V4.24) và đầu ra `error` dưới Khi lỗi `continue` hay `route`
  (R1.5); sáu lát loại bước W1: `data.transform`, `logic.switch`, `flow.stop`, `data.object.query|create|update|upsert`,
  `data.object.assign`, `ai.llm`, `tool.call`, `human.approval` với hai làn `approved`, `rejected` (R9.16), cùng hình
  chiếu `trigger.endpoint`.
- Bậc B của W1, sau đường găng YC94, không ticket thí điểm nào chờ (V4.26): `logic.parallel@1` (Bước song song, gộp
  kiểu all ở Điểm nối cuối các làn; không có loại `logic.join`), `logic.loop@1` (Bước vòng lặp có trần, kiểu
  do-while, cho chờ trong thân), `logic.break@1` (Thoát vòng lặp) và quy tắc `approval_rule` `all` của
  `human.approval@1` (mọi người được giao phải duyệt, một điểm chờ, k = n), với cột `assignee_id` của
  `studio.step_approvals` và kết quả của điểm chờ qua `StepWaitLookupPort` (R1.6, R10, R11, R12); cùng bậc đó,
  `flow.subworkflow@1` (Bước Quy trình con: cấu hình, đầu ra, ba tính chất vị trí với `opens_wait` đúng, Khi lỗi cho
  phép, bộ trích phụ thuộc và nhãn năng lực của loại; R13; V4.33).
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

| Việc                                                                                                                                                                                                                                                                                                                                                                                                             | Vì sao                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | Chủ                                                                                                 |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Tài liệu `dw.workflow/v1` dạng cây Bước, phép hạ cây sang `WorkflowIR`, bộ kiểm khi gửi kiểm định và bảng mã `wf.*` của nó, trình biên dịch, kể cả cấu trúc khối của bậc B (làn song song và Điểm nối, vòng lặp có trần, Thoát vòng lặp, làn lỗi), hàng run, điểm chờ và handler của phê duyệt bước, sự cố và Chạy tiếp từ Bước lỗi, hẹn giờ                                                                     | Là hợp đồng và máy chạy của quy trình (ADR-0112 (Accepted) quyết 3-5)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | `workflow-engine`                                                                                   |
| Trình kích hoạt và Nguồn dữ liệu (Data Hub), ánh xạ payload vào `input_schema`                                                                                                                                                                                                                                                                                                                                   | Là cửa vào của quy trình                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | `workflow-triggers`                                                                                 |
| Định nghĩa công cụ và Bộ công cụ theo loại, `ToolExecutor`, `ToolSpec`                                                                                                                                                                                                                                                                                                                                           | Công cụ là dữ liệu tenant qua một executor (ADR-0116 (Accepted))                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | `tools-and-skills`                                                                                  |
| Sàn gửi tin tiếp thị (ngưỡng, đồng ý) trong đường gửi của executor                                                                                                                                                                                                                                                                                                                                               | Một chủ cho sàn gửi (DO-3)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | `compliance-pdpl`                                                                                   |
| Container mã dùng một lần, `CodeSandboxPort`                                                                                                                                                                                                                                                                                                                                                                     | Hạ tầng cách ly tách riêng                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | `code-sandbox`                                                                                      |
| Lịch sử chạy theo bước, span, bảng điều khiển sử dụng                                                                                                                                                                                                                                                                                                                                                            | Đọc từ Postgres dưới RLS (ADR-0122 (Accepted))                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | `telemetry-and-audit`                                                                               |
| `notify.send` chỉ tới thành viên; run không-live chỉ Danh sách người nhận thử                                                                                                                                                                                                                                                                                                                                    | B7b-nodes 11                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | đợt sau (W2, `workflow-nodes`)                                                                      |
| Bước phê duyệt: nhắc, chuyển cấp, hết hạn, mã quyết định Zalo                                                                                                                                                                                                                                                                                                                                                    | B7b-nodes 12 (phần còn lại), 16                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | đợt sau (W2, `workflow-nodes`)                                                                      |
| `http.request`; `ai.agent`                                                                                                                                                                                                                                                                                                                                                                                       | B7b-nodes 13, 14                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | đợt sau (W2, `workflow-nodes`)                                                                      |
| `logic.map`; `time.delay`, `time.wait_until`                                                                                                                                                                                                                                                                                                                                                                     | B7b-nodes 15, 16; YC45; `logic.parallel` vào bậc B của W1 (R10) và `logic.join` gộp vào cuối các làn của nó (V4.24, V4.26)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | đợt sau (W2, `workflow-nodes`)                                                                      |
| `human.task` và hộp "Việc của tôi", `studio.human_tasks`                                                                                                                                                                                                                                                                                                                                                         | B7b-nodes 17                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | đợt sau (W2, `workflow-nodes`)                                                                      |
| `trigger.call`, `flow.return`                                                                                                                                                                                                                                                                                                                                                                                    | B7b-nodes 18; `flow.subworkflow` vào bậc B của W1 (R13; V4.33), còn Quy trình nào gọi được làm Quy trình con chờ Q10                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | đợt sau (W2, `workflow-nodes`)                                                                      |
| `code.python` và khóa `studio.code.author`, mà spec này đăng ký cùng Loại bước; quyền lợi `code_node` do `CodeExecutionService` của code-sandbox kiểm trước runner                                                                                                                                                                                                                                               | B7b-nodes 19 (D7); khóa có một chủ là spec này, quyền lợi có một chủ là code-sandbox (code-sandbox:R2.3)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | đợt sau (W2, `workflow-nodes`); `code-sandbox`                                                      |
| `trigger.manual`, `trigger.schedule`, `trigger.record_event`; `data.object.get`, `delete`                                                                                                                                                                                                                                                                                                                        | B7b-nodes 20                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | đợt sau (W2, `workflow-nodes`)                                                                      |
| R7.3: Bước `ai.llm` bỏ qua bản ghi mang cờ `ai_opt_out` hay `processing_restricted`, không gọi model                                                                                                                                                                                                                                                                                                             | Cờ Hạn chế xử lý và yêu cầu chủ thể dữ liệu là W2 của compliance-pdpl; W1 chỉ chạy trên lead giả lập (YC89; Q9 của phiếu)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | đợt sau (W2, `workflow-nodes`)                                                                      |
| WN14: test âm của R7.3, lead `ai_opt_out` không có lời gọi model nào                                                                                                                                                                                                                                                                                                                                             | Đi cùng R7.3 sang W2 (Q9 của phiếu)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | đợt sau (W2, `workflow-nodes`)                                                                      |
| R9.4: phê duyệt hết hạn đi Nhánh ra `expired` hoặc làm lượt chạy `failed` với `approval_expired`                                                                                                                                                                                                                                                                                                                 | YC52 và lane hẹn giờ ở W2; ở W1 Bước phê duyệt không có hạn riêng, còn phê duyệt mở mà không ai quyết bị hủy cùng lượt chạy khi lượt tới hạn chót `deadline_at` của workflow-engine, 30 ngày sau lần nhận (R9.15; workflow-engine:R5.22; V4.14; DO-31)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | đợt sau (W2, `workflow-nodes`); `workflow-engine` ghi `expired`                                     |
| WN10: test âm của R9.4, quá hạn không bao giờ thành `approved`                                                                                                                                                                                                                                                                                                                                                   | Đi cùng R9.4 sang W2 (DO-31)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | đợt sau (W2, `workflow-nodes`)                                                                      |
| W2: Kết quả giả lập ghim theo Bước nhập trong bảng chạy mô phỏng của builder (thân `test-runs`); ở W1 kết quả ghim chỉ đến từ ca kịch bản của Cổng chất lượng                                                                                                                                                                                                                                                    | V4.37 kéo kết quả ghim về W1 cho ca kịch bản: wrapper nút áp nó ở `simulate` thay phần giả lập của loại, sau khi kiểm với schema đầu ra của Bước, không loại Bước nào tự đọc nó, và lane `studio_gate` chuyển nó từ ca kịch bản vào lần thử (H-18; workflow-engine:R4.27, workflow-engine:R4.28; `.claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md`, `.claude/plans/studio/agent-lifecycle/issues/06-cong-chat-luong-va-ca-kich-ban.md`); wrapper từ chối kết quả ghim cho một Bước `human.approval`, nên quyết định giả lập của R9.9 vẫn là đầu vào duy nhất của Bước đó (H-26; workflow-engine:R4.29); route `test-runs` giữ W2 cho kết quả ghim, nên ngoài ca kịch bản W1 dùng giá trị sinh từ output schema (tenant-config:R5.3) | `workflow-engine`, `agent-lifecycle` (W1); đợt sau (W2, `workflow-triggers`, `workflow-builder-ui`) |
| W2: không ghi xuống: Bước `data.object.*` từ chối ghi một giá trị có nguồn gốc từ một trường Bảo vệ vào một trường Mở, theo tập nguồn gốc trường mà Phân tích năng lực tính lúc gửi kiểm định (YC113)                                                                                                                                                                                                            | V4.40: làm trước khi các đích W2 ra (`notify.send`, `ai.agent`, tin nội bộ, lookup, tìm kiếm); tới lúc đó luật riêng của lát thí điểm giữ W1 an toàn (marketing-pilot)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | đợt sau (W2, `workflow-nodes`); `compliance-pdpl` (tập nguồn gốc), `field-security`                 |
| Quyết định giả lập cho Bước phê duyệt bên trong Quy trình con của một lượt mô phỏng                                                                                                                                                                                                                                                                                                                              | W1: lượt con `simulate` tới một Bước phê duyệt không có quyết định thì `failed` với `simulated_decision_missing` (R9.12), không bao giờ coi là đã duyệt, còn ca kịch bản của Cổng chất lượng ghim kết quả cho chính Bước Quy trình con, mà wrapper áp như cho mọi Bước có hiệu ứng (H-18; workflow-engine:R4.27); quyết định theo id Bước của Quy trình con đổi thân `test-runs` (workflow-triggers:R2.7)                                                                                                                                                                                                                                                                                                                                                      | đợt sau (W2, `workflow-nodes`); `workflow-triggers`                                                 |
| Lịch làm việc và ngày lễ của công ty cho `time.add_workdays`                                                                                                                                                                                                                                                                                                                                                     | BS35 giao chủ ở spec này, dữ liệu từ discovery 27 (FOG-16); cần trước khi cắt ticket W2 (YC98)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | đợt sau (W2, `workflow-nodes`)                                                                      |
| Giao theo nhóm: ứng viên hay người dự phòng là một nhóm                                                                                                                                                                                                                                                                                                                                                          | Nhóm của org-and-principals là W2; W1 giao trong thành viên workspace giữ quyền (Q6 của phiếu)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | đợt sau (W2, `workflow-nodes`)                                                                      |
| Bước phê duyệt thu hẹp người duyệt theo nhóm; giá trị `team` của `assignee_kind`                                                                                                                                                                                                                                                                                                                                 | Nhóm của org-and-principals là W2; W1 chỉ nhận người và Biểu thức (R9.1)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | đợt sau (W2, `workflow-nodes`)                                                                      |
| Duyệt thay: người duyệt đặt một người duyệt thay cho phê duyệt của mình trong một khoảng thời gian có hạn khi vắng mặt, có audit khi đặt, gỡ và mỗi quyết định của người duyệt thay (YC104); người duyệt thay phải giữ khóa đóng dấu của loại phê duyệt và `approvals.decide`, không phải người tạo lượt chạy (YC51), và chỉ được giao có thời hạn (từ, đến), có audit; ngoài các điều kiện đó guard vẫn trả 403 | N7 của Đạt ngày 24/10/2026 và V4.10; ADR-0112 (Accepted) quyết 7 và ADR-0104 (Accepted) quyết 11 ghi điều kiện từ W2; "Duyệt thay" khác "Ủy quyền" dùng kết nối của bảng thuật ngữ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | đợt sau (W2, `workflow-nodes`)                                                                      |
| Duyệt k trên n người được giao với k < n: một điểm chờ đóng khi đủ k người đã duyệt                                                                                                                                                                                                                                                                                                                              | Nguyên liệu chung của các gói Nhân sự, Mua hàng, Tài chính, ghi ở Không làm sau gói Bán hàng (N9 của Đạt ngày 24/10/2026); k = n là R12, ở bậc B của W1 (V4.26)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | đợt sau (W3, `workflow-nodes`); `workflow-engine`                                                   |
| Bảng quyết định, hay ma trận duyệt chọn người duyệt theo ngưỡng                                                                                                                                                                                                                                                                                                                                                  | Nguyên liệu chung của các gói Nhân sự, Mua hàng, Tài chính, ghi ở Không làm sau gói Bán hàng (N9 của Đạt ngày 24/10/2026)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | đợt sau (W3, `workflow-nodes`)                                                                      |
| Phiên bản chính mới của loại bước; nội dung giàu bằng python-liquid                                                                                                                                                                                                                                                                                                                                              | B7b-nodes 21, 22                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | đợt sau (W3, `workflow-nodes`)                                                                      |
| Một quyết định giả lập cho mỗi lần lặp của một Bước phê duyệt trong thân vòng lặp, để lượt mô phỏng và Câu kiểm định thử được vòng làm lại bị từ chối rồi được duyệt                                                                                                                                                                                                                                             | W1 cấp một quyết định cho mọi lần lặp của Bước (R9.9): vòng làm lại thử được nhánh duyệt (thoát ở vòng 1) và nhánh từ chối tới `max_reached`; một danh sách theo lần lặp đổi thân của `test-runs` (workflow-triggers:R2.7) và Câu kiểm định (agent-lifecycle:R4.7)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | `workflow-nodes`, W2                                                                                |

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
  Ticket 07 thêm `assignee_id uuid` NULL, người duyệt bắt buộc của yêu cầu khi `approval_rule` là `all` (NULL khi
  `any`), với UNIQUE `(tenant_id, run_id, interrupt_id, assignee_id)`, để một điểm chờ không có hai yêu cầu cho cùng
  một người (R12.2, R12.4).

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
  `simulated_decision_missing` (lượt mô phỏng `failed`, R9.12), `no_approver` (làn lỗi hay lượt `failed` lúc mở
  phê duyệt, R9.13, R12.3), `approval_incomplete` (lượt `failed` khi Bước phê duyệt `all` tiếp tục mà còn yêu cầu
  chưa quyết, R12.9); người quyết bị từ chối nhận 404, 409 `conflict` với `details.reason_code`
  `second_person_required` hay 403 `permission_denied` theo ADR-0104 (Accepted) quyết 11 (R9.2, R9.6, R9.8, R12.4).
  Các mã `wf.stop_in_parallel`, `wf.wait_in_parallel`, `wf.break_outside_loop` và `wf.type_mismatch` của R10.3,
  R10.4, R11.3, R13.3, R13.6 và mã `loop_limit_reached` của R11.2 là của workflow-engine (bảng `wf.*` và trình biên
  dịch; ADR-0112 (Accepted) quyết 3, 4), không phải mã spec này thêm; Bước Quy trình con không thêm mã nào.

## Kiểm soát

| #    | Kiểm soát                                                                                                                                      | Yêu cầu                           | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| WN1  | Văn bản công ty không qua `str.format`, Jinja2 hay eval                                                                                        | R3.1                              | Mẫu `{0}{x.__class__}` ra nguyên văn; gỡ tokenizer nhận biết CEL → test kiến trúc đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| WN2  | Mọi giá trị vào prompt được bao chứa và cắt 16 KiB, kể cả `Mô tả cho AI`                                                                       | R4.2, R7.2, R7.5                  | `</input>` trong lời nhắn lead hay trong `ai_description` của một trường không đóng được khối; gỡ `contain_untrusted` ở đích prompt hay ở mục bối cảnh → đỏ                                                                                                                                                                                                                                                                                                                                                                                                                         |
| WN3  | Đầu ra model kiểm phía server                                                                                                                  | R7.1                              | Model giả trả `score=150` hai lần → `output_invalid` ở đầu ra `error`, làn lỗi chạy với Khi lỗi `route`, lượt chạy không dừng; gỡ kiểm JSON Schema → đỏ                                                                                                                                                                                                                                                                                                                                                                                                                             |
| WN4  | Bước bản ghi chỉ là chủ thể chạy; không khoá `run_as`                                                                                          | R5.2                              | Cấu hình có `run_as` → schema từ chối; chủ thể thiếu quyền → `permission_denied`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| WN5  | Trường bị ẩn không vào mẫu hay Biểu thức                                                                                                       | R4.4                              | Tham chiếu `phone` không đọc được → `field_not_readable` lúc gửi kiểm định, `field_hidden` lúc render; gỡ kiểm → đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| WN6  | Tác động ngoài qua `ToolExecutor`; hai lời gọi cùng khoá không cùng gửi khi claim còn hạn                                                      | R8.2                              | Hai lần chạy song song cùng khoá do wrapper nút dẫn (workflow-engine:R4.5), lần sau trong lúc claim của lần đầu còn hạn → nhà cung cấp giả nhận đúng một lời gọi; Bước tự dựng khoá khác → hai lời gọi, test đỏ                                                                                                                                                                                                                                                                                                                                                                     |
| WN7  | Quyền công cụ và sàn gửi tin kiểm ở executor, không ở Bước                                                                                     | R8.3, R8.4                        | Thiếu quyền → `permission_denied` từ executor; `email.send` của `smtp@1.0.0` tới địa chỉ chưa đồng ý → `blocked:no_consent`; gọi thẳng công cụ cũng bị chặn                                                                                                                                                                                                                                                                                                                                                                                                                         |
| WN8  | Người duyệt giữ quyền, được giao, khác người tạo lượt; còn ứng viên lúc mở phê duyệt; không gửi kiểm định khi không có người thứ hai giữ scope | R9.2, R9.5, R9.6, R9.13           | Người tạo lượt giữ scope tự duyệt → 409 `second_person_required`; người tạo lượt thiếu scope, hay người giữ scope mà không được giao → 403; người khác không giữ tem → 404; chỉ người chạy giữ scope → lệnh gửi kiểm định trả 422 `no_second_approver`, phiên bản ở Nháp; người được giao duy nhất rời công ty sau khi phát hành → lúc mở phê duyệt Bước đi làn lỗi với `no_approver` khi Khi lỗi là `route`, hay lượt `failed` với `no_approver` khi là `fail`, không yêu cầu nào mở; gỡ guard, gỡ đăng ký kiểm hay gỡ kiểm ứng viên lúc mở → test đỏ                              |
| WN9  | Tham số đã duyệt là tham số được thực thi                                                                                                      | R9.3                              | Chen một Bước sau khi duyệt → gửi kiểm định từ chối; mã băm chủ thể khác → `subject_changed`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| WN10 | Hết hạn không bao giờ tự duyệt                                                                                                                 | R9.4                              | Quá hạn → Nhánh ra `expired` hoặc `approval_expired`, không bao giờ có `approved`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| WN11 | Mặc định đóng: Khi lỗi, nhánh switch, và Khi lỗi mà loại không cho                                                                             | R1.6, R2.3, R2.4, R9.17, R13.4    | Không khai Khi lỗi → `fail`; `logic.switch` thiếu nhánh mặc định → `wf.router_not_total`, không niêm phong; Bước phê duyệt khai `continue`, Bước vòng lặp khai `route`, hay Bước Quy trình con khai `incident` → schema từ chối; gỡ danh sách Khi lỗi cho phép khỏi mục của loại → các cấu hình đó qua, test đỏ                                                                                                                                                                                                                                                                     |
| WN12 | Biểu thức có trần chi phí, không treo                                                                                                          | R3.4                              | Map lồng 3 cấp 22 phần tử → `expression_budget_exceeded` ở cả hai adapter; gỡ ngân sách vòng ở `CelCppEngine`, hay tiền-kiểm AST ở `CelRustEngine` → đỏ                                                                                                                                                                                                                                                                                                                                                                                                                             |
| WN13 | Host không nằm trong mẫu                                                                                                                       | R4.3                              | `https://{{ trigger.input.host }}/` → `templated_host`, không render                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| WN14 | Bước AI tôn trọng opt-out                                                                                                                      | R7.3                              | Lead `ai_opt_out` → không có lời gọi model nào                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| WN15 | Mỗi thuộc tính loại bước có nơi đọc                                                                                                            | R1.4                              | Thêm một thuộc tính không ai đọc vào `NodeTypeRegistry` → test bảng thuộc-tính-tới-nơi-đọc đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| WN16 | Ứng viên giao và người dự phòng đủ quyền theo `effective_grants`, giao qua một dịch vụ                                                         | R6.1, R6.3, R6.4                  | Người không giữ quyền làm người phụ trách bản ghi không bao giờ được chọn, kể cả khi là người dự phòng; người dự phòng không hợp lệ → Bước lỗi theo Khi lỗi, làn lỗi chạy với `route`, không ai được giao; lần giao của Bước có đúng một audit và một outbox `studio.record.assigned`, do dịch vụ giao của record-access ghi; gỡ kiểm quyền → đỏ                                                                                                                                                                                                                                    |
| WN17 | Người duyệt đọc được mọi Trường mà trang duyệt hiển thị                                                                                        | R9.7, R9.8                        | Bước phê duyệt đóng dấu `phone`; người được giao không đọc được `phone` quyết → 403 tại `decide`, yêu cầu vẫn `pending`; gỡ điều kiện đọc trường khỏi guard → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                               |
| WN18 | Quyết định giả lập không bao giờ thỏa một phê duyệt `live`, và thiếu thì không coi là đã duyệt                                                 | R9.11, R9.12                      | Lượt `live` có quyết định giả lập `approved` trong đầu vào → yêu cầu phê duyệt thật được mở, lượt chạy chờ; lượt `simulate` thiếu quyết định cho một Bước phê duyệt → `failed` `simulated_decision_missing`, Nhánh ra duyệt không chạy; gỡ kiểm chế độ ở Bước → test đỏ                                                                                                                                                                                                                                                                                                             |
| WN19 | Profile triển khai chỉ tính Biểu thức bằng `cel-expr-python`                                                                                   | R3.6                              | Setting chọn `CelRustEngine` khi `settings.is_deployed` → bị từ chối, test đỏ khi giá trị của profile triển khai trỏ sang bản Rust; ngoài profile triển khai setting chọn được `CelRustEngine` và bộ test hợp đồng chạy với nó; gỡ kiểm `settings.is_deployed` → profile triển khai dựng được bản Rust, test đỏ                                                                                                                                                                                                                                                                     |
| WN20 | Giao và phê duyệt của Bước không trỏ được tới lượt chạy hay yêu cầu của công ty khác                                                           | R9.14                             | `dw_app` gắn tenant A chèn dòng `step_assignments` mang `run_id` của một lượt chạy tenant B, hay dòng `step_approvals` mang `approval_request_id` của một yêu cầu tenant B → lỗi FK, không dòng nào được ghi; đổi một trong hai FK về FK một cột → ca của nó qua, test đỏ                                                                                                                                                                                                                                                                                                           |
| WN21 | Phê duyệt bước của lượt đã hủy không còn quyết được, kể cả lượt quá hạn chót                                                                   | R9.15                             | Lượt chờ ở một Bước phê duyệt bị reaper kết thúc vì `deadline_exceeded` → yêu cầu `studio.step.` của nó `cancelled` trong cùng giao dịch, người được giao quyết sau đó bị từ chối, yêu cầu vẫn `cancelled`; Tắt khẩn một lượt đang chờ → như vậy; gỡ trigger hủy yêu cầu → yêu cầu còn `pending`, test đỏ                                                                                                                                                                                                                                                                           |
| WN22 | Điểm nối không là Loại bước riêng                                                                                                              | R10.2                             | Tài liệu mang `logic.join@1` → `wf.unknown_node_type`, không niêm phong; đăng ký một mục `logic.join@1` vào registry → tài liệu đó niêm phong, test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                              |
| WN23 | Không lối kết thúc lượt nào trong làn song song                                                                                                | R10.3                             | `flow.stop` ở làn 2, hay trong làn lỗi của một Bước ở làn 2 → `wf.stop_in_parallel`, không niêm phong; `flow.stop` ở làn gốc sau Bước song song → niêm phong; gỡ kiểm, hay đặt tính chất kết thúc lượt của `flow.stop@1` về sai → tài liệu có `flow.stop` trong làn niêm phong và lượt của nó `completed` mà Điểm nối và Bước sau không chạy, test đỏ                                                                                                                                                                                                                               |
| WN24 | Không chờ trong làn song song                                                                                                                  | R10.4                             | Bước phê duyệt ở làn 2, kể cả trong thân một Bước vòng lặp nằm trong làn đó → `wf.wait_in_parallel`, không niêm phong; cùng Bước phê duyệt trong thân một Bước vòng lặp ngoài mọi làn song song → niêm phong; gỡ kiểm, hay đặt tính chất mở điểm chờ của `human.approval@1` về sai → tài liệu có phê duyệt trong làn niêm phong, test đỏ                                                                                                                                                                                                                                            |
| WN25 | Bước vòng lặp luôn có trần khai trong Bước                                                                                                     | R11.1                             | Cấu hình thiếu `max_iterations`, `max_iterations = 0` hay thiếu điều kiện → schema từ chối; `max_iterations = 1` → nhận; bỏ `max_iterations` khỏi danh sách khóa bắt buộc của schema → cấu hình thiếu nó qua, test đỏ                                                                                                                                                                                                                                                                                                                                                               |
| WN26 | Thoát vòng lặp chỉ trong thân vòng lặp và ngoài làn song song                                                                                  | R11.3                             | Thoát vòng lặp ở làn gốc, hay trong một `logic.switch` ngoài mọi vòng lặp, hay trong một làn song song, kể cả của một vòng lặp nằm trọn trong làn → `wf.break_outside_loop`, không niêm phong; trong làn `rejected` của một Bước phê duyệt ở thân → niêm phong; gỡ kiểm, hay đặt tính chất thoát vòng lặp của `logic.break@1` về sai → các tài liệu đó niêm phong, test đỏ                                                                                                                                                                                                          |
| WN27 | Làn Duyệt chỉ chạy khi quyết định là duyệt                                                                                                     | R9.16                             | Lượt `live`, quyết định `rejected` → làn `rejected` chạy, `tool.call` trong làn `approved` có 0 lời gọi; `approved` → làn `approved` chạy, làn `rejected` không chạy; đảo ánh xạ từ quyết định sang làn → test đỏ                                                                                                                                                                                                                                                                                                                                                                   |
| WN28 | Mỗi người duyệt bắt buộc quyết đúng phần của mình, và không ai bị bỏ bớt                                                                       | R12.3, R12.4                      | Bước `all` giao A, B, C: B quyết yêu cầu của A → 403, yêu cầu của A vẫn `pending`; C rời công ty trước lúc mở, hay C là người của công ty khác → `no_approver`, 0 yêu cầu được mở; một dòng `studio.step_approvals` của điểm chờ vắng `assignee_id` → A, B và C quyết yêu cầu đó đều 403; gỡ điều kiện người được giao của chính yêu cầu khỏi guard, hay cho guard đọc dòng vắng `assignee_id` thành `any` → B duyệt hai phần, test đỏ; cho Bước bỏ C rồi mở hai yêu cầu → test đỏ                                                                                                  |
| WN29 | Làn Duyệt của Bước `all` chỉ chạy khi cả n đã duyệt, và điểm chờ đóng đúng một lần                                                             | R12.2, R12.5, R12.6, R12.8, R12.9 | Bước `all` giao A, B, C: A, B duyệt → `pending`, lượt chờ; C duyệt → `approved`, làn `approved` chạy một lần; B, C duyệt trong hai giao dịch xen kẽ theo thứ tự cố định sau A → đúng một lần quyết trả `approved`, dòng chờ `resolved` một lần; worker chết sau khi mở → chạy lại vẫn đúng 3 yêu cầu; bỏ khóa hàng → cả hai trả `pending` và dòng chờ kẹt `open`, test đỏ; handler giả đóng điểm chờ ở lần duyệt đầu → lượt `failed` với `approval_incomplete`, làn `approved` không chạy; cho Bước đọc giá trị tiếp tục thay trạng thái các yêu cầu → làn `approved` chạy, test đỏ |
| WN30 | Không ai quyết được phần của một điểm chờ đã đóng                                                                                              | R12.7                             | Bước `all` giao A, B, C: A từ chối → `rejected`, yêu cầu của B và C `cancelled` trong cùng giao dịch, làn `rejected` chạy; B quyết sau đó → bị từ chối, yêu cầu vẫn `cancelled`; cho trigger hủy chỉ nghe `cancelled` như ticket 06 → yêu cầu của B còn `pending`, test đỏ                                                                                                                                                                                                                                                                                                          |
| WN31 | Bước song song, Bước vòng lặp và quy tắc duyệt chỉ nhận dạng cấu hình đã khai                                                                  | R10.1, R11.2, R12.1               | `logic.parallel@1` một làn, hay hai làn cùng khóa → schema từ chối; Bước vòng lặp không mang làn `body` → `wf.router_not_total`, không niêm phong; `approval_rule` `k_of_n` → schema từ chối; bỏ kiểm khóa làn duy nhất, đặt `body` về Nhánh ra tùy chọn, hay bỏ tập giá trị cho phép của `approval_rule` → ca của nó qua, `k_of_n` thì Bước chạy như `any`, test đỏ                                                                                                                                                                                                                |
| WN32 | Bước Quy trình con chỉ nhận cấu hình đã khai: không khóa phiên bản, đầu vào khớp khai của phiên bản con                                        | R13.1, R13.6                      | Cấu hình thiếu `workflow`, hay có khóa `version` hoặc `live` → schema từ chối; `inputs` thiếu một trường bắt buộc, mang một trường lạ, hay có Biểu thức trả `string` cho một trường `int` của phiên bản con → `wf.type_mismatch` với con trỏ tới trường đó, không niêm phong; bỏ `additionalProperties: false` khỏi schema, hay bỏ kiểm `inputs` theo khai của phiên bản con → ca của nó qua, test đỏ                                                                                                                                                                               |
| WN33 | Bước Quy trình con là một Bước chờ: không trong làn song song, được trong thân vòng lặp                                                        | R13.3                             | Bước Quy trình con ở làn 2 của một Bước song song, kể cả trong thân một Bước vòng lặp nằm trong làn đó → `wf.wait_in_parallel`, không niêm phong; cùng Bước trong thân một Bước vòng lặp ngoài mọi làn song song → niêm phong; đặt `opens_wait` của `flow.subworkflow@1` về sai → tài liệu có Quy trình con trong làn niêm phong, test đỏ                                                                                                                                                                                                                                           |
| WN34 | Lượt con chạy đúng Chế độ chạy của lượt cha, không bao giờ `live` dưới một lượt `simulate`                                                     | R13.5                             | Lượt cha `simulate` gọi một Quy trình con có `tool.call` `email.send` của `smtp@1.0.0` → lượt con ở `simulate`, 0 email rời egress; cho Bước chuyển `live`, hay bỏ chuyển chế độ để cửa dùng mặc định → test đỏ                                                                                                                                                                                                                                                                                                                                                                     |
| WN35 | Bước Quy trình con không bao giờ trỏ tới Quy trình của công ty khác                                                                            | R13.1                             | Tenant A gửi kiểm định một Quy trình có Bước Quy trình con nêu `api_name` chỉ có ở tenant B → không niêm phong, không phụ thuộc nào trỏ tới thành phần của tenant B, 0 dòng `worker_runs` ở tenant B; tenant A có cùng `api_name` → phụ thuộc và lượt con trỏ tới thành phần của tenant A; phân giải phụ thuộc dưới một vai bỏ qua RLS → phụ thuộc trỏ tới tenant B, test đỏ                                                                                                                                                                                                        |

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
  công cụ ghim; không định nghĩa bảng của nó ở đây. Mức bảo đảm đồng thời mà R8.2 thử là bước giành lượt và nhật ký lần
  gửi `dispatched` của executor (`.claude/plans/studio/runtime-hardening/issues/01-toolexecutor-gianh-luot-khong-cua-sau.md`,
  xếp vào sổ guard của tools-and-skills/01; V4.30, H-3).
- `workflow-engine`, phần V4.30, V4.33, V4.34 và V4.37: điểm chờ `outcome_review` cho lời gọi không rõ kết quả, mà
  wrapper nút không cho đi làn lỗi (`.claude/plans/studio/workflow-engine/issues/08-tac-dong-khong-ro-ket-qua.md`);
  lượt con của Bước Quy
  trình con: ghim phiên bản con lúc gửi kiểm định từ phụ thuộc của loại, lồng tối đa 3 cấp, chu trình bị từ chối, hủy dây
  chuyền trong ≤ 5 giây, điểm chờ `child_run`, và `outputs`, `outcomes` của lượt con chuyển về lượt cha khi lượt con kết
  thúc (`.claude/plans/studio/workflow-engine/issues/09-quy-trinh-con.md`; ADR-0113 (Accepted) quyết 9); phần V4.37:
  wrapper nút áp kết quả giả lập ghim của một Bước có hiệu ứng ở `simulate`, kể cả Bước Quy trình con, sau khi kiểm với
  schema đầu ra của Bước (workflow-engine:R4.27, workflow-engine:R4.28; H-18), và từ chối nó cho Bước phê duyệt
  (workflow-engine:R4.29; H-26); phần V4.34: hai làn song song sửa cùng một bản ghi đều giữ giá trị của mình, dựa vào
  lệnh sửa chỉ mang các trường của Bước mà R5.1 bảo đảm (workflow-engine:R7.3).
- `workflow-engine` (batch 2): tài liệu `dw.workflow/v1` dạng cây Bước, mỗi Nhánh ra của một loại là một làn lồng
  trong Bước (V4.24), bộ kiểm khi gửi kiểm định trên `WorkflowIR` dẫn từ cây, với hàm dominator và bảng mã
  `wf.*` (workflow-engine:R2.2, R2.5, R2.6, R2.14; `wf.stop_in_parallel`, `wf.wait_in_parallel` và
  `wf.break_outside_loop` ở workflow-engine:R2.15, R2.16, R2.17; ADR-0112 (Accepted) quyết 3), đọc Nhánh ra và tính
  chất vị trí của loại từ `NodeTypeRegistry` (R1.4), bộ bọc node áp `retry`/`timeout`/Khi lỗi, kể cả làn lỗi của
  `route` từ W1, và dẫn khóa chống lặp duy nhất của mọi hiệu ứng (workflow-engine:R4.5), cấu trúc khối của bậc B
  trong IR và trình biên dịch (mỗi làn song song một subgraph gộp bằng waiting edge, vòng lặp có trần với bộ đếm bước
  theo lượt, workflow-engine:R4.14 tới R4.20; ADR-0112 (Accepted) quyết 4-5;
  `.claude/plans/studio/workflow-engine/issues/06-song-song-vong-lap-co-tran-va-nhanh-loi.md`), điểm chờ và handler
  phê duyệt bước (workflow-engine:R6.2) với `platform.run_waits` mà `studio.step_approvals` trỏ tới và
  `StepWaitLookupPort` mà spec này đáp ứng, handler chỉ đặt dòng chờ `resolved` khi port trả kết quả khác `pending`
  và giữ dòng chờ `open` khi là `pending` (R12.5; workflow-engine:R6.3, workflow-engine:R6.29;
  ADR-0112 (Accepted) quyết 7; `.claude/plans/studio/workflow-engine/issues/07-chay-tiep-tu-buoc-loi.md`),
  `uq_worker_runs_tenant_id_id` mà FK ghép của `studio.step_assignments` trỏ tới
  (workflow-engine/02), ghim phiên bản, khóa `studio.workflows.edit` (workflow-engine/01), và hạn chót `deadline_at`
  của lượt chạy, mà lượt quá hạn sang `cancelled` với `deadline_exceeded` và trigger hủy dòng chờ đi theo, nơi R9.15
  nghe (workflow-engine:R5.22, workflow-engine:R5.23, workflow-engine:R6.13).
- `custom-objects`: `RecordService` đáp ứng `RecordsPort`, giả lập ghi ở `simulate` (custom-objects:R5.4) và
  cây lọc (custom-objects:R5.6, custom-objects:R8.9;
  `.claude/plans/studio/custom-objects/issues/04-truy-van-ban-ghi.md`); `Mô tả cho AI` của đối tượng và trường
  mà R7.5 đọc (YC101; `.claude/plans/studio/custom-objects/issues/02-luoc-do-dinh-nghia-object.md`); khoá `wf:` của Bước
  ghi cùng giao dịch với lệnh ghi và phát lại kết quả đã lưu khi gặp lại khoá, kể cả `update`, là mức bảo đảm nội bộ
  mà R5.1 dựa vào (V4.30 mục 10; phần `assign` của mục đó đi qua dịch vụ giao của record-access, R6.5), và bộ contract
  test của `RecordsPort` ở ticket 04 chạy trên `RecordService` thật cùng bản giả mà workflow-engine/03 dùng (H-7).
- `record-access`: ngữ cảnh actor và Giới hạn dữ liệu ở mọi cửa (record-access:R6.4), và giao người phụ
  trách qua một dịch vụ giao ghi audit và outbox `studio.record.assigned` (record-access:R8.1, record-access:R8.7,
  record-access:R8.8; `.claude/plans/studio/record-access/issues/05-giao-nguoi-phu-trach.md`), mà Bước giao gọi
  qua một Protocol spec này khai, với khoá chống lặp của Bước mà lần giao ghi cùng giao dịch và phát lại khi gặp lại
  (R6.5; V4.30).
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
  `ai_opt_out`/`processing_restricted` ở W2; Phân tích năng lực đọc nhãn năng lực của `flow.subworkflow@1` là tín hiệu
  của phiên bản con đã ghim, bắc cầu qua closure của nó, như `ai.agent` mang tín hiệu của agent, và một loại nó chưa biết
  tính đủ ba tín hiệu (ADR-0125 (Accepted) quyết 1, 2;
  `.claude/plans/studio/compliance-pdpl/issues/05-phan-tich-bo-ba-khi-xuat-ban.md`).
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
  R9.6, ticket 06; workflow-engine đổi trạng thái của lượt quá hạn chót hay trigger hủy dòng chờ → R9.15, ticket 06; studio-skeleton đổi gói của adapter CEL ở R5.6 → Trong phạm vi, ticket 01;
  workflow-engine đổi lược đồ cây Bước, tên ba mã `wf.*` của bậc B, cách biên dịch làn song song, vòng lặp hay làn
  lỗi, hay cách handler theo tiền tố `studio.step.` đọc kết quả của `StepWaitLookupPort` → R1.5, R1.6, R10, R11, R12,
  ticket 02, 07; workflow-engine/09 đổi cách ghim phiên bản con, điểm chờ `child_run`, cửa xin lượt con hay cách
  chuyển `outputs` và `outcomes` của lượt con, hay Q10 được trả lời → R13, ticket 08; runtime-hardening/01 hay
  connections-and-vault đổi mức bảo đảm của lời gọi (claim, `dispatched`, kết quả có kiểu) → R8.2, WN6, ticket 06;
  dịch vụ giao của record-access hay `RecordService` thôi phát lại theo khoá → R5.1, R6.5, ticket 04; workflow-engine
  đổi luật ghi bản ghi trong làn song song (workflow-engine:R7.3) → R5.1, ticket 04;
  wrapper nút của workflow-engine không áp kết quả ghim cho Bước Quy trình con (workflow-engine:R4.27), hay không từ chối
  nó cho Bước phê duyệt (workflow-engine:R4.29; H-26) → hai dòng Ngoài phạm vi về kết quả ghim và quyết định giả lập trong Quy trình con, R9.9,
  ticket 08.

## Câu hỏi còn mở

- Q10. Quy trình nào gọi được làm Quy trình con ở W1: chỉ Quy trình tự khai cho gọi bằng Trình kích hoạt
  `trigger.call` (kéo `trigger.call` từ W2 về bậc B cùng ticket 08, như agent chỉ được liên kết khi khai bề mặt `link`,
  ADR-0117 (Accepted) quyết 7), hay mọi Quy trình có bản Đang dùng của cùng công ty? Chủ: Đạt. Chặn: R13.1, ticket 08.

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
- 24/10/2026 (Đạt): V4.24: tài liệu quy trình là cây Bước, vẽ thành sơ đồ có cấu trúc; mỗi Nhánh ra mà một Loại bước
  khai là một làn Bước lồng trong Bước (các nhánh của `logic.switch` cùng làn mặc định "Khác", làn `approved` và
  `rejected` của phê duyệt, các làn song song, thân vòng lặp, làn lỗi khi Khi lỗi là `route`), không còn `edges[]`;
  `logic.join` gộp vào cuối các làn của `logic.parallel`; không lối nào kết thúc lượt trong một làn song song. Các
  dòng trên nói "Nhánh ra lỗi" đọc là làn lỗi, có khi Khi lỗi là `route`, và "không nối Nhánh ra đó" đọc là Bước
  không mang làn đó. Sửa: đoạn mở đầu, R1.5, R6.4, R7.1, R9.13, thêm R9.16, R10.2, R10.3, Trong phạm vi, Ngoài phạm
  vi (`logic.join`), Phụ thuộc, WN3, WN8, WN16, thêm WN22, WN23, WN27, ticket 02, 03, 04, 05, 06, 07.
- 24/10/2026 (Đạt): V4.26: W1 thêm khoảng 2-3 tuần cho bậc B, sau đường găng YC94 và không ticket thí điểm nào chờ:
  `logic.parallel@1` gộp kiểu all, mỗi làn một subgraph, không chờ trong làn song song; `logic.loop@1` có trần, kiểu
  do-while, cho chờ trong thân, với `logic.break@1` chỉ trong thân và ngoài làn song song, chạm `max_iterations` thì
  làn `max_reached` hay `loop_limit_reached`; Bước phê duyệt mà mọi người được giao phải duyệt là một Bước
  `human.approval` với một điểm chờ (k = n), đóng khi mọi người duyệt hay ở lần từ chối đầu tiên; k < n vẫn W3;
  `on_error: route` vào W1, nên `error` có dưới cả `continue` lẫn `route`. Dòng N7 ngày 24/10/2026 đọc thành: Bước
  vòng lặp ở W1 (bậc B), Duyệt thay vẫn W2; dòng N9 cùng ngày đọc thành: duyệt k trên n với k < n ở W3; dòng ngày
  23/10/2026 về đầu ra `error` đọc thành `error` dưới `continue` hay `route`; dòng V4.P11 nay ở R11.2 cho Nhánh ra và
  ở trình biên dịch của workflow-engine cho cách chạy. Sửa: R1.5, thêm R1.6, R10, R11, R12, Trong phạm vi, Ngoài
  phạm vi (`logic.parallel`, `logic.loop`, k trên n), Dữ liệu, API, Phụ thuộc, WN11, thêm WN22-WN31, ticket 07.
- 24/10/2026 (agent, tạm): ba loại điều khiển và quy tắc `all` vào ticket mới 07, không mở rộng ticket 03, vì
  marketing-pilot/03 chờ workflow-nodes/04, 05 và 06, ba ticket đều chờ ticket 03, nên bậc B trong ticket 03 làm
  đường găng YC94 chờ bậc B, trái V4.26; ticket 07 chờ ticket 03 và 06, còn ticket 03 chỉ đổi chữ theo cây Bước.
  Sửa: ticket 03, 07, Danh sách ticket. Nếu sai thì: ticket 03 mang ba loại điều khiển, ticket 06 mang quy tắc `all`,
  và đường găng YC94 dài thêm phần đó.
- 24/10/2026 (agent, tạm): spec này đăng ký ba loại điều khiển (cấu hình, Nhánh ra, Khi lỗi cho phép, tính chất vị
  trí) và mô tả kiểm vị trí của các loại nó sở hữu bằng mã của bảng `wf.*`, như R2.4 làm với `logic.switch`; cách
  chạy của khối (gộp ở Điểm nối, nhịp riêng của làn, do-while, trần, Thoát vòng lặp, khóa và điểm chờ theo vòng) có
  một chủ là trình biên dịch và wrapper nút của workflow-engine (ADR-0112 (Accepted) quyết 2, 4, 5), nên spec này
  không chép các tiêu chí đó (failure-modes #2). Sửa: R10, R11, ticket 07. Nếu sai thì: R10, R11 thêm tiêu chí cách
  chạy, mỗi tiêu chí dẫn tiêu chí của workflow-engine, và ticket 07 chờ ticket biên dịch khối của workflow-engine.
- 24/10/2026 (agent, tạm): `human.approval@1` chỉ cho Khi lỗi `fail` hay `route` (R9.17), nên `no_approver` đi làn
  lỗi hay làm lượt `failed` (R9.13), không bao giờ để lượt đi tiếp như đã có quyết định; `logic.parallel@1`,
  `logic.loop@1` và `logic.break@1` chỉ cho `fail` (R1.6), vì lỗi của một Bước trong làn hay trong thân đi theo Khi
  lỗi của chính Bước đó (failure-modes #7). Sửa: thêm R1.6, R9.17, R9.13, WN11, ticket 06, 07. Nếu sai thì: Bước phê
  duyệt nhận cả `continue` hay `incident` và R9.13 nói `no_approver` đi đâu với mỗi giá trị, còn Bước song song nhận
  `route` như một khối thử.
- 24/10/2026 (agent, tạm): làn `max_reached` là Nhánh ra tùy chọn của `logic.loop@1` (R11.2): Bước không mang làn đó
  thì lượt `failed` với `loop_limit_reached` ở trần, mang làn đó, kể cả rỗng, thì lượt chạy làn rồi đi tiếp, vì cây
  Bước không có "Nhánh ra không nối" mà dòng V4.P11 dùng. Sửa: R11.2, ticket 07. Nếu sai thì: làn `max_reached` luôn
  có mặt, và một làn rỗng làm lượt `failed` với `loop_limit_reached`.
- 24/10/2026 (agent, tạm): quy tắc `all` mở một yêu cầu `studio.step.` cho mỗi người được giao, cùng một điểm chờ, nối
  qua `studio.step_approvals` mang `assignee_id`, với guard chỉ nhận người được giao của chính yêu cầu, nhận ra quy
  tắc `all` ở một điểm chờ có từ hai yêu cầu trở lên, nên ở đó một dòng vắng `assignee_id` không ai quyết được và
  không bao giờ đọc thành `any` (R12.2, R12.4), vì `platform.approval_requests` giữ một quyết định mỗi yêu cầu và mọi
  luật của R9 (tem, 404, 403, 409, Trường đóng dấu, mã băm chủ thể) áp nguyên cho từng yêu cầu; một người được giao
  không hợp lệ lúc mở là `no_approver`, không bị bỏ bớt (R12.3); `StepWaitLookupPort` trả kết quả của điểm chờ dưới
  khóa hàng các dòng `studio.step_approvals` của nó (R12.5, R12.6), handler của workflow-engine chỉ đóng điểm chờ khi
  kết quả khác `pending`, và Bước tự đọc lại trạng thái các yêu cầu lúc tiếp tục, `approval_incomplete` khi chưa đủ
  (R12.8, R12.9; failure-modes #5); vắng `approval_rule` là `any`, để lượt và phiên bản `human.approval@1` có trước
  ticket 07 giữ nguyên hành vi trong cùng phiên bản chính. Sửa: R12, Dữ liệu, API, Phụ thuộc, WN28, WN29, WN30,
  ticket 07. Nếu sai thì: một yêu cầu cho cả Bước với một bảng quyết định theo người của spec này, guard và
  `StepWaitLookupPort` đọc bảng đó.
- 24/10/2026 (agent, tạm): mỗi mục `NodeTypeSpec` khai ba tính chất vị trí, mở điểm chờ, kết thúc lượt chạy và thoát
  vòng lặp, mà bộ kiểm của workflow-engine đọc để trả `wf.wait_in_parallel`, `wf.stop_in_parallel`,
  `wf.break_outside_loop` (và `wf.wait_in_map` từ W2), thay một danh sách tên loại trong bộ kiểm, vì W2 thêm loại chờ
  (`time.delay`, `time.wait_until`, `human.task`) và một loại mới chỉ khai tính chất của nó (R1.4, WN15). Sửa:
  Phụ thuộc, ticket 07. Nếu sai thì: bộ kiểm của workflow-engine giữ danh sách tên loại, và ticket 07 bỏ ba tính chất.
- 25/10/2026 (agent, tạm): ba tính chất vị trí là trường bắt buộc không có giá trị mặc định của `NodeTypeSpec` từ
  ticket 02, và mỗi ticket đăng ký một loại khai cả ba (`flow.stop@1` `ends_run` ở ticket 03, `human.approval@1`
  `opens_wait` ở ticket 06, `logic.break@1` `exits_loop` ở ticket 07), vì bộ kiểm của workflow-engine/06 đọc chúng mà
  ticket 07 chờ ticket đó, và một mặc định sai để một loại chờ mới của W2 lọt `wf.wait_in_parallel` (failure-modes
  #7); phép hạ của workflow-engine/01 đọc `ends_run` và `exits_loop` thay tên `flow.stop` và `logic.break`. Sửa: Phụ
  thuộc, ticket 02, 03, 06, 07; workflow-engine/01, 06. Nếu sai thì: workflow-engine/06 thêm ba trường với mặc định
  sai, và ticket 07 đặt giá trị của ba loại.
- 25/10/2026 (agent, tạm): ở W1 một quyết định giả lập phục vụ mọi lần lặp của một Bước phê duyệt trong thân vòng lặp
  (R9.9 lấy quyết định "cho chính Bước đó"), và một danh sách quyết định theo lần lặp là W2 (Ngoài phạm vi), vì nó đổi
  thân của `test-runs` và Câu kiểm định ở hai spec khác. Sửa: Ngoài phạm vi. Nếu sai thì: R9.9 nhận một danh sách theo
  lần lặp, lần lặp vượt danh sách dùng quyết định cuối, và workflow-triggers:R2.7 cùng agent-lifecycle:R4.7 đổi theo.
- 25/10/2026 (Đạt): V4.30: lời hứa "đúng một lần" thành bốn mức bảo đảm gọi bằng tên (nội bộ, có khóa hay tra cứu,
  không khóa, đồng thời), với khối `delivery` của trình kết nối, kết quả có kiểu của egress, nhật ký lần gửi
  `dispatched`, tiếp quản claim theo `on_unknown` và điểm chờ `outcome_review` cho lời gọi không rõ kết quả; với spec
  này, R8.2 nói mức đồng thời, R8 nói số lần nhà cung cấp áp dụng theo hợp đồng giao nhận của Hành động và lời gọi
  không rõ kết quả đỗ ở `outcome_review` thay vì đi làn lỗi, và mức nội bộ của lần giao cần khoá của Bước (R6.5).
  Sửa: R6, thêm R6.5, R8, R8.2, WN6, Phụ thuộc, ticket 04, 06.
- 25/10/2026 (Đạt): V4.33: `flow.subworkflow@1` vào bậc B của W1, không ticket thí điểm nào chờ; lượt con ghim lúc
  gửi kiểm định, lồng tối đa 3 cấp, hủy lượt cha thì mọi lượt con dừng trong ≤ 5 giây; Bước mở một điểm chờ
  `child_run`, nên `opens_wait` của nó đúng, nó bị từ chối trong làn song song (`wf.wait_in_parallel`) và được trong
  thân vòng lặp; YC117 tách phần quy trình con khỏi YC45. Sửa: đoạn mở đầu, R2.1, thêm R13, Trong phạm vi, Ngoài phạm
  vi (`trigger.call`, `flow.return`), API, WN11, thêm WN32, WN33, WN34, Phụ thuộc, Câu hỏi còn mở, Danh sách ticket,
  thêm ticket 08.
- 25/10/2026 (Đạt): V4.34: giữ LangGraph sau spike S-RT, `durability="sync"`, và ngữ nghĩa thực thi có golden trace ở
  workflow-engine, trong đó lệnh ghi bản ghi trong một làn song song là PATCH theo trường; với spec này, R5.1 nói lệnh
  sửa một bản ghi có sẵn của Bước bản ghi chỉ mang các trường cấu hình của Bước nêu, là chỗ workflow-engine:R7.3 dựa
  vào. Sửa: R5.1, Phụ thuộc, ticket 04.
- 25/10/2026 (Đạt): V4.37: ca kịch bản tất định ở Cổng chất lượng W1 mang kết quả giả lập ghim theo Bước, nên kết quả
  ghim về W1 cho ca kịch bản; dòng 23/10/2026 "Kết quả giả lập ghim theo Bước do spec này làm ở W2" đọc thành: ở W1
  kết quả ghim đến từ ca kịch bản và wrapper nút áp nó (H-18), còn nhập kết quả ghim trong bảng chạy mô phỏng của
  builder vẫn W2. Sửa: Ngoài phạm vi.
- 25/10/2026 (Đạt): V4.40: Phân tích năng lực tính tập nguồn gốc trường lúc gửi kiểm định, bảo mật trường kiểm người
  nhận ở mọi đích, và Bước `data.object.*` không ghi từ một trường Bảo vệ sang một trường Mở, ở W2 trước khi các đích
  W2 ra; ở W1 spec này chỉ thêm dòng Ngoài phạm vi có đợt và chủ (YC113). Sửa: Ngoài phạm vi.
- 25/10/2026 (agent, tạm): H-7: `RecordsPort` khai cùng một bộ contract test ở ticket 04, chạy trên mọi bản cài, bản
  giả mà workflow-engine/03 dùng để thử workflow-engine:R4.7 và `RecordService` thật, với ca `simulate` không ghi gì
  (custom-objects:R5.4) và ca phát lại theo khoá (V4.30), để bản giả không trôi khỏi bản thật; ticket 04 thêm cạnh tới
  workflow-engine/03, nơi bản giả ra đời, vì hai ticket chưa có đường nào nối nhau, nên bộ không chạy được trên bản giả
  khi ticket 04 đến trước (đã mô phỏng đồ thị: không vòng, `marketing-pilot/03` vẫn ở độ sâu 15, ticket 04 vẫn ở độ sâu
  14). Sửa: Phụ thuộc, ticket 04. Nếu sai thì: workflow-engine/03 chờ custom-objects/03 như trước, bộ contract test chỉ
  chạy trên `RecordService`, và ticket 04 bỏ cạnh tới workflow-engine/03.
- 25/10/2026 (agent, tạm): H-18: kết quả giả lập ghim theo Bước do wrapper nút của workflow-engine/03 áp ở `simulate`,
  sau khi kiểm với schema đầu ra của Bước, không loại Bước nào của spec này tự đọc; ca kịch bản mang nó và lane
  `studio_gate` của agent-lifecycle/06 chuyển nó vào lần thử; route `test-runs` giữ W2 cho kết quả ghim; spec này chỉ
  ghi dẫn chiếu ở Ngoài phạm vi. Sửa: Ngoài phạm vi. Nếu sai thì: mỗi loại Bước tự đọc kết quả ghim của mình, mục
  `NodeTypeSpec` của mỗi loại có tác động thêm hành vi đó, và dòng Ngoài phạm vi thành tiêu chí của spec này.
- 25/10/2026 (agent, tạm): Mâu thuẫn nguồn: V4.30 nói `update` và `assign` qua `RecordsPort`, dòng của Đạt ngày
  24/10/2026 nói Bước giao gọi `AssignRecordService` của record-access/05 qua `RecordAssignPort`; theo dòng 24/10/2026
  cho cửa và theo V4.30 cho mức bảo đảm: R5.1 chuyển khoá `wf:` cho bốn Bước bản ghi qua `RecordsPort`, R6.5 chuyển
  cùng khoá qua `RecordAssignPort`, để một lần chạy lại sau K4 phát lại người đã giao; `AssignRecordService` của
  record-access/05 ghi khoá cùng giao dịch với lần giao và phát lại người đã giao, phần mà V4.30 mục 10 viết cho
  `RecordService` của custom-objects, và bộ contract test của ticket 04 phủ cả hai cổng, bản giả lẫn bản thật, vì ca
  `assign` của workflow-engine/03 chạy trên bản giả. Sửa: thêm R6.5, Phụ thuộc, ticket 04.
  Nếu sai thì: lần giao đi qua `RecordsPort` như bốn Bước bản ghi, R6.5 rút, R5.1 nêu cả `assign`, và `RecordAssignPort`
  chỉ còn ở phía `RecordService`.
- 25/10/2026 (agent, tạm): áp V4.33 cho loại: `flow.subworkflow@1` có `side_effect_level` `internal`, vì xin lượt con là
  một lần ghi trong nền tảng qua cửa xin lượt con mà R2.1 nay nêu, đi theo khoá của Bước ở mức bảo đảm nội bộ (V4.30),
  còn tác động của lượt con đi qua cửa của chính nó; không Nhánh ra nào ngoài làn lỗi khi `route`; Khi lỗi cho `fail`, `continue` và `route` mà không cho
  `incident`, vì Chạy tiếp từ Bước lỗi ở lượt cha chạy lại Bước với cùng khoá (workflow-engine:R6.19) nên chỉ phát lại
  lượt con đã kết thúc, còn sự cố đặt ở Bước lỗi bên trong Quy trình con thì lượt con đỗ và lượt cha chờ
  (ADR-0113 (Accepted) quyết 9); nhãn năng lực là tín hiệu của phiên bản con đã ghim, bắc cầu, như `ai.agent`
  (ADR-0125 (Accepted) quyết 1, 2); đầu ra là `outputs` và `outcomes` của lượt con (H-14), không thêm id lượt con;
  ticket 08 chờ thêm ticket 03 (cây kiểu và `draft/scope`) và ticket 07 (`logic.parallel@1`, `logic.loop@1` mà tiêu chí
  của R13.3 dựng tài liệu với), ngoài các cạnh của mục C của lượt (đã mô phỏng đồ thị: không vòng, `marketing-pilot/03`
  vẫn ở độ sâu 15); tham chiếu `api_name` mới có ca âm liên tenant (WN35; CLAUDE.md, Tenancy and authorization).
  Sửa: R2.1, R13, WN11, WN32, WN33, WN34, thêm WN35, ticket 08. Nếu sai thì: `incident` được cho kèm một luật của
  workflow-engine/09 rằng Chạy tiếp xin lượt con mới dưới khoá có lần thử, nhãn năng lực của loại là đủ ba tín hiệu,
  và ticket 08 chỉ chờ ticket 02 và workflow-engine/09 với danh mục giả cho hai loại của ticket 07.
- 25/10/2026 (agent, tạm): ở W1 Quy trình con của một lượt mô phỏng không nhận quyết định giả lập cho Bước phê duyệt
  của nó, nên lượt con tới Bước đó thì `failed` với `simulated_decision_missing` (R9.12), không bao giờ coi là đã duyệt,
  còn ca kịch bản thử Quy trình cha bằng kết quả ghim cho chính Bước Quy trình con, mà wrapper nút áp như cho mọi Bước
  có hiệu ứng (H-18; workflow-engine:R4.27), vì quyết định theo id Bước của Quy trình con đổi thân `test-runs` của
  workflow-triggers. Sửa: Ngoài phạm vi, Phụ thuộc. Nếu sai thì: thân `test-runs` và Câu kiểm định nhận quyết định theo
  đường dẫn id Bước cha và id Bước con ở W1, và R9.9 đổi theo; còn nếu workflow-engine:R4.27 không áp kết quả ghim cho
  Bước Quy trình con, ca kịch bản ở W1 chỉ thử được Quy trình cha mà Quy trình con không có Bước phê duyệt.
- 25/10/2026 (agent, tạm): H-26: một kết quả giả lập ghim không bao giờ thay quyết định giả lập của một Bước
  `human.approval`: wrapper nút từ chối kết quả ghim cho Bước phê duyệt, nên quyết định của R9.9 vẫn là đầu vào duy nhất
  của Bước đó; phần từ chối là của wrapper (workflow-engine:R4.29, ticket 03 của spec đó), nên spec này chỉ ghi dẫn
  chiếu, R9.9 không đổi. Sửa: Ngoài phạm vi, Phụ thuộc. Nếu sai thì: schema ca kịch bản của agent-lifecycle/06 từ chối
  kết quả ghim cho Bước phê duyệt thay wrapper, và hai chỗ dẫn chiếu đổi theo.
- 26/10/2026 (agent, tạm): H-21: mỗi ticket của spec này ghi một mã lý do hay lỗi mới lên lượt hay Bước chạy
  (`simulated_decision_missing`, `no_approver`, `approval_incomplete`, `output_invalid`, `subject_changed` và các mã sau)
  thêm nhãn tiếng Việt của mã đó vào mảnh `configs/copy/run_reason_codes.d/workflow-nodes.yaml` trong cùng thay đổi, và
  test của telemetry-and-audit:R1.9 thấy cả mã do loại Bước trả về. Sửa: Quyết định. Nếu sai thì: nhãn ở bảng mã `wf.*`
  của workflow-engine.

## Danh sách ticket

| #   | Ticket                                                                                               |
| --- | ---------------------------------------------------------------------------------------------------- |
| 01  | [CEL và cổng ExpressionEngine](issues/01-cel-va-expression-engine.md)                                |
| 02  | [Sổ đăng ký loại bước và mẫu chuỗi](issues/02-so-dang-ky-buoc-va-mau-chuoi.md)                       |
| 03  | [Phạm vi biến và các bước logic](issues/03-pham-vi-bien-va-buoc-logic.md)                            |
| 04  | [Bước dữ liệu đối tượng và giao](issues/04-buoc-du-lieu-doi-tuong-va-giao.md)                        |
| 05  | [Bước ai.llm](issues/05-buoc-ai-llm.md)                                                              |
| 06  | [tool.call và human.approval](issues/06-tool-call-va-human-approval.md)                              |
| 07  | [Song song, vòng lặp và phê duyệt cần mọi người](issues/07-song-song-vong-lap-va-duyet-moi-nguoi.md) |
| 08  | [Bước Quy trình con flow.subworkflow@1](issues/08-flow-subworkflow.md)                               |
