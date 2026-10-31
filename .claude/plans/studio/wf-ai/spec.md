# Trợ lý AI sửa quy trình mẫu của Digital Worker

Status: needs-triage
Area: studio · Nhánh: `main` · Viết: 31/10/2026
Duyệt: agent, tạm theo ủy quyền 27/10/2026
Sẵn sàng: chưa kiểm

Chủ của một Digital Worker muốn đổi quy trình mẫu nó chạy (thêm một lần nhắc, bỏ một bước, đổi thứ tự) mà không viết YAML. Theo D16 (3) và D18 (4), trợ lý AI hỏi lại khi chưa rõ, nêu kế hoạch, rồi đề xuất một bản sửa dạng diff để người duyệt, từ chối hay sửa tiếp; trợ lý chỉ soạn cây bước từ sổ loại bước và những công cụ, prompt mà quy trình gốc đã dùng, không bao giờ đổi loại quyết định, mức tự chủ, kết nối, model hay thông tin đăng nhập; bản sửa chỉ chạy thật khi bộ kiểm của wf-lite, luật sàn HITL và một lượt mô phỏng đều qua và một người khác người soạn duyệt (YC125).

## Hiện trạng (đã kiểm ở `6f54b92` ngày 31/10/2026)

- Quy trình của DW là tài liệu `dw.workflow/v1` do gói ship trong `configs/packs`, nạp, kiểm và ghim sha256 lúc khởi động (`packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/catalog.py:70-106`). Thiếu: không có phiên bản nào do tenant soạn; catalog chỉ đọc tệp.
- DW ghim quy trình bằng `workflow_key` và `workflow_version` (`packages/python/dw_platform/src/dw_platform/domain/digital_worker.py:107-108`). Ràng buộc: mọi đề xuất dựa trên tài liệu mà chính DW đang ghim.
- Bộ kiểm một lượt nhận tài liệu thô, sổ loại bước, công cụ và schema của kind, trả mọi lỗi `wf.*` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/validate.py:118-130`), kể cả luật sàn HITL `wf.hitl_gate_missing` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/validate.py:306-325`). Ràng buộc: đề xuất của trợ lý qua đúng bộ kiểm này, không bản thứ hai.
- Cây bước đọc qua sổ loại bước thành `outline` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/outline.py:56`). Ràng buộc: diff và màn hình đọc cây theo cùng cách.
- Model trả đầu ra có cấu trúc qua `ModelGateway.generate_structured` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/ports.py:56-62`); provider `mock` đọc fixture và bị cấm ở môi trường triển khai (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/model_stack.py:87-92`). Ràng buộc: lát này chạy được với `mock`; máy hiện tại không có model thật (Chờ Đạt 21).
- Biến của prompt là dữ liệu không tin, bọc `<input>`; chỉ biến mã dựng mới được `raw_variables` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/prompts.py:58-64`; ADR-0010 (Accepted)). Ràng buộc: câu của người dựng và tài liệu gốc vào prompt như dữ liệu.
- Chỉ Business Owner hay Technical Owner sửa được DW; người khác 403 `not_dw_owner`, người không đọc được 404 (`packages/python/dw_platform/src/dw_platform/application/digital_workers.py:303`). Ràng buộc: ai được nhờ trợ lý theo đúng luật này.
- Phát hành một phiên bản cần cổng qua trên đúng hash và người thứ hai duyệt (`docs/adr/0120-publish-gate-and-run-control-switches.md:78`; ADR-0120 (Accepted)). Thiếu: bộ máy vòng đời của ADR-0120 (Accepted) chưa dựng; lát này dựng phần tối thiểu cho quy trình của DW.
- Không có chạy mô phỏng nào trong `wflite` (đọc `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/compile.py:1`). Thiếu: R6.2.

## Mục tiêu

### R1 — Một lượt với trợ lý

Chủ của DW gửi một yêu cầu và nhận lại một câu hỏi hoặc một đề xuất.

- R1.1 KHI Business Owner hay Technical Owner của một DW gửi `POST /v1/digital-workers/{id}/workflow-assistant` với `instruction`, trợ lý PHẢI trả `kind` là `question` (một câu hỏi lại) hoặc `proposal` (kế hoạch tối đa 8 dòng, cây bước đề xuất, diff và danh sách lỗi).
- R1.2 NẾU người gọi đọc được DW mà không là Business Owner hay Technical Owner của nó, THÌ route PHẢI trả 403 `not_dw_owner` và không gọi model.
- R1.3 Trợ lý PHẢI lấy tài liệu gốc từ cặp `workflow_key@workflow_version` mà DW đang ghim, đọc phía server, bỏ qua mọi tài liệu, tenant hay workflow nêu trong thân yêu cầu.
- R1.4 NẾU `instruction` dài quá 4.000 ký tự, hay `history` có quá 10 lượt hoặc một lượt quá 4.000 ký tự, THÌ route PHẢI trả 422 `assistant_input_too_long` và không gọi model.
- R1.5 NẾU model không trả được đầu ra khớp schema sau các lần thử của gateway, THÌ route PHẢI trả 502 `upstream_unavailable` với `reason_code` `assistant_output_invalid` và không trả đề xuất nào.

### R2 — Chỉ soạn từ cái đã có

Trợ lý chỉ đổi cây bước; mọi thứ khác của quy trình gốc giữ nguyên (D16 (3), D18 (4)).

- R2.1 Đề xuất PHẢI giữ nguyên `schema`, `key`, `version`, `triggers`, `variables`, `decision_classes` và `work_kinds` của tài liệu gốc và chỉ thay `steps`.
- R2.2 NẾU một bước `tool.call` của đề xuất gọi công cụ mà tài liệu gốc không gọi ở bước nào, THÌ trợ lý PHẢI thêm lỗi `wf.tool_not_in_base` cho bước đó.
- R2.3 NẾU một bước `ai.llm` của đề xuất nêu prompt mà tài liệu gốc không dùng ở bước nào, THÌ trợ lý PHẢI thêm lỗi `wf.prompt_not_in_base` cho bước đó.
- R2.4 NẾU đầu ra của model có trường ngoài cây bước, kế hoạch và câu hỏi, THÌ trợ lý PHẢI coi đầu ra đó là không khớp schema theo R1.5.

### R3 — Bộ kiểm của nền tảng trên mọi đề xuất

- R3.1 KHI có đề xuất, trợ lý PHẢI chạy bộ kiểm của wf-lite (wf-lite:R3.1) trên tài liệu đề xuất với sổ loại bước, công cụ và schema của kind của tài liệu gốc, gộp lỗi của nó với lỗi của R2, và trả `publishable` đúng khi và chỉ khi danh sách lỗi rỗng.

### R4 — Diff để người đọc

- R4.1 Đề xuất PHẢI kèm diff theo `id` bước: bước thêm, bước bỏ, bước đổi `config` hay `description`, và bước đổi chỗ (lane hay vị trí), mỗi mục nêu đường dẫn lane theo `outline`.

### R5 — Đầu vào không tin

- R5.1 `instruction`, `history` và tài liệu gốc PHẢI vào prompt `wf_ai.workflow_edit` chỉ như biến bọc `<input>` của một prompt không có `raw_variables`.
- R5.2 Bộ eval `evals/datasets/wf_ai` PHẢI có ca chèn lệnh trong `instruction` và trong `description` của tài liệu gốc (bỏ cổng duyệt, gọi công cụ khác, đổi loại quyết định).
- R5.3 NẾU một đề xuất có lỗi `wf.hitl_gate_missing` hay `wf.tool_not_in_base`, hay đổi gì ngoài `steps`, THÌ grader `wf_ai.frozen` PHẢI chấm ca đó đỏ.

### R6 — Bản nháp, mô phỏng và phát hành

Đề xuất được lưu, chạy thử và phát hành bởi người thứ hai (ADR-0120 (Accepted) quyết 2).

- R6.1 KHI chủ DW lưu một đề xuất `publishable`, nền tảng PHẢI lưu một bản nháp duy nhất của DW với nội dung, sha256 của nội dung, sha256 của tài liệu gốc và người soạn; lưu đè bản nháp cũ của chính DW đó.
- R6.2 KHI chủ DW chạy mô phỏng một bản nháp, nền tảng PHẢI chạy nó trên một việc mẫu khớp schema của kind, mọi `tool.call` ghi lại đầu vào và trả mẫu theo schema đầu ra của công cụ mà không gọi `ToolExecutor`, mọi `human.approval` duyệt nguyên đề xuất, mọi `time.wait` bỏ qua, rồi lưu kết quả và `trail` theo sha256 của nội dung.
- R6.3 NẾU bản nháp được gửi duyệt mà chưa có lượt mô phỏng thành công trên đúng sha256 nội dung đó, THÌ nền tảng PHẢI trả 409 `simulation_required` và không mở approval.
- R6.4 KHI chủ DW gửi duyệt, nền tảng PHẢI mở approval `dw.workflow.publish` theo luật strict, chỉ Validator hay Technical Owner của DW quyết và không bao giờ người soạn.
- R6.5 KHI approval được duyệt, nền tảng PHẢI ghi phiên bản của tenant bất biến và chuyển ghim của DW sang nó trong cùng giao dịch; việc đang chạy giữ phiên bản đã ghim lúc bắt đầu.
- R6.6 NẾU lúc duyệt ghim của DW đã khác tài liệu gốc của bản nháp, THÌ nền tảng PHẢI trả bản nháp về trạng thái nháp với lý do `base_changed` và không đổi ghim.

### R7 — Màn hình

- R7.1 Trang `/digital-workers/[id]/assistant` PHẢI hiện các lượt, kế hoạch, diff, lỗi bằng chữ và các nút lưu, mô phỏng, gửi duyệt.
- R7.2 Thẻ approval `dw.workflow.publish` trên `/approvals` PHẢI hiện diff và kết quả mô phỏng.

## Trong phạm vi

- Route `POST /v1/digital-workers/{id}/workflow-assistant`, prompt `configs/prompts/wf_ai/workflow_edit@1.0.0.yaml`, fixture mock của nó, bộ eval `evals/datasets/wf_ai` và grader `wf_ai.*`.
- Hàm diff cây bước và kiểm "chỉ từ cái đã có" trong `dw_agent_runtime.wflite`.
- Bảng bản nháp, kết quả mô phỏng và phiên bản quy trình của tenant; approval `dw.workflow.publish`; cách catalog trả phiên bản tenant theo ghim của DW.
- Trang `/digital-workers/[id]/assistant` và thẻ approval.

## Ngoài phạm vi

| Việc                                                              | Vì sao                                                         | Chủ                  |
| ----------------------------------------------------------------- | -------------------------------------------------------------- | -------------------- |
| Tài liệu và ảnh quy trình làm đầu vào của trợ lý (D18 (4))        | cần đọc tệp và ảnh qua cửa tri thức; lát này chỉ nhận chữ      | đợt sau              |
| Dựng quy trình từ mô tả trống                                     | D16 (2): sau sửa gói mẫu                                       | đợt sau (W3)         |
| Thêm công cụ, prompt, biến, loại quyết định hay trigger mới       | D18 (4); prompt và công cụ mới là phiên bản của nền tảng       | không làm            |
| Canvas kéo thả                                                    | D16 (4)                                                        | workflow-builder-ui  |
| Bộ máy vòng đời chung của Studio (đóng băng, rút lại, nhiều loại) | ADR-0120 (Accepted) cho mọi loại; lát này chỉ quy trình của DW | agent-lifecycle      |
| Chạy eval với model thật                                          | không có khóa model trên máy (Chờ Đạt 21)                      | đợt sau, khi có khóa |

## API

- `POST /v1/digital-workers/{id}/workflow-assistant`: thân `{instruction, history[]}`, mỗi lượt `{role: "user" | "assistant", text}`; trả `{kind, question?, plan[], steps?, diff?, problems[], publishable}`. 404 khi không đọc được DW, 403 `not_dw_owner`, 422 `assistant_input_too_long`, 404 `workflow_not_shipped`, 502 `upstream_unavailable` (`assistant_output_invalid`). Không ghi gì, nên không `Idempotency-Key`.
- Route của R6 viết ở ticket 02-03.

## Kiểm soát

| #     | Kiểm soát                                                                | Yêu cầu    | Test âm                                                                                          |
| ----- | ------------------------------------------------------------------------ | ---------- | ------------------------------------------------------------------------------------------------ |
| WAI1  | Chỉ Business Owner hay Technical Owner nhờ được trợ lý, kiểm trước model | R1.2       | Validator gọi route: 403 `not_dw_owner`, gateway giả không được gọi lần nào                      |
| WAI2  | Tài liệu gốc từ ghim của DW, không từ thân yêu cầu                       | R1.3       | thân nêu `workflow_key` khác: đề xuất vẫn dựa trên tài liệu DW ghim                              |
| WAI3  | Đầu vào quá dài bị từ chối trước model                                   | R1.4       | `instruction` 4.001 ký tự: 422, gateway giả không được gọi                                       |
| WAI4  | Ngoài `steps` không gì của gốc đổi                                       | R2.1, R2.4 | gateway giả trả cây bước kèm `decision_classes` sửa: đề xuất mang `decision_classes` của gốc     |
| WAI5  | Công cụ ngoài tài liệu gốc là lỗi                                        | R2.2       | đề xuất gọi `email.send` khi gốc không gọi: `wf.tool_not_in_base`, `publishable` sai             |
| WAI6  | Prompt ngoài tài liệu gốc là lỗi                                         | R2.3       | đề xuất nêu prompt khác: `wf.prompt_not_in_base`, `publishable` sai                              |
| WAI7  | Bộ kiểm của wf-lite chạy trên mọi đề xuất, kể cả luật sàn HITL           | R3.1       | đề xuất đưa `email.send` ra khỏi lane `approved`: `wf.hitl_gate_missing`, `publishable` sai      |
| WAI8  | Câu của người và tài liệu gốc chỉ vào prompt như `<input>`               | R5.1       | prompt dựng với `instruction` chứa `</input>`: chuỗi bị escape trong khối `<input>`              |
| WAI9  | Mô phỏng không gửi gì ra ngoài                                           | R6.2       | mô phỏng bản nháp có `email.send`: `ToolExecutor` không được gọi, Mailpit không có thư           |
| WAI10 | Gửi duyệt cần mô phỏng thành công trên đúng nội dung                     | R6.3       | sửa bản nháp sau mô phỏng rồi gửi: 409 `simulation_required`, không approval                     |
| WAI11 | Người soạn không duyệt được bản của mình                                 | R6.4       | người soạn là Technical Owner quyết: 409 `second_person_required`, ghim không đổi                |
| WAI12 | Ghim chỉ đổi khi duyệt, và không đổi khi gốc đã khác                     | R6.5, R6.6 | đổi ghim của DW sau khi gửi rồi duyệt: `base_changed`, ghim giữ giá trị mới, không phiên bản mới |

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (`mutations/NN.yaml`).
- `make test-unit test-contract test-architecture` và integration của các gói chạm xanh; `pnpm --filter @dw/web test` xanh cho ticket có màn hình.

## Phụ thuộc

- wf-lite:R3.1 (bộ kiểm một lượt), wf-lite:R4.1 (luật sàn HITL), sổ loại bước `build_node_registry`, `outline` của digital-worker/04.
- `ModelGateway` và `PromptRegistry` của runtime; `DigitalWorkerService.require_owner` (digital-worker:R1.5, digital-worker:R1.6).
- Luật strict và `ApproveAndResumeService` của approval không lượt chạy, như `dw.autonomy.raise` (digital-worker:R8.3).
- Kiểm lại khi: sổ loại bước thêm loại hay đổi lane → ticket 01 (diff) và 02 (mô phỏng); agent-lifecycle dựng bộ máy vòng đời của ADR-0120 (Accepted) → ticket 03 chuyển sang nó.

## Câu hỏi còn mở

Không có.

## Quyết định

- 31/10/2026 (agent, tạm theo ủy quyền): trợ lý chỉ đổi `steps`; công cụ và prompt giới hạn ở những gì tài liệu gốc đã dùng, không mở rộng tới `allowed_tools` của DW, vì D18 (4) cấm đổi kết nối và một công cụ mới với tài liệu là một quyền mới với quy trình. Sửa: R2. Nếu sai thì: R2.2 so với `allowed_tools` của DW thay vì tài liệu gốc.
- 31/10/2026 (agent, tạm theo ủy quyền): lượt trao đổi không lưu phía server; client gửi lại `history` dạng chữ, tối đa 10 lượt, vì lịch sử chỉ là câu của người và của model, không quyết gì, còn tài liệu gốc luôn đọc lại từ ghim. Sửa: R1.1, R1.4. Nếu sai thì: bảng phiên trợ lý theo DW với hạn giữ.
- 31/10/2026 (agent, tạm theo ủy quyền): ai được nhờ trợ lý là người sửa được DW hôm nay (Business Owner, Technical Owner); ai duyệt phát hành là Validator hay Technical Owner khác người soạn, như đề nghị nâng tự chủ (digital-worker:R8.3), theo người thứ hai của ADR-0120 (Accepted) quyết 2. Sửa: R1.2, R6.4. Nếu sai thì: đổi `deciders` của `DwDecisionAdmission` cho `dw.workflow.publish`.
- 31/10/2026 (agent, tạm theo ủy quyền): mô phỏng không gọi model thật khi provider là `mock`, và với model thật thì gọi qua cùng gateway và hạn mức như lượt chạy; công cụ luôn giả. Sửa: R6.2. Nếu sai thì: mô phỏng cũng giả bước `ai.llm` bằng mẫu theo `output_schema`.
- 31/10/2026 (agent, tạm theo ủy quyền): Duyệt cách chia ticket 01-04: 01 lượt trợ lý không lưu (R1-R5), 02 bản nháp và mô phỏng (R6.1-R6.2), 03 gửi duyệt và phát hành (R6.3-R6.6), 04 màn hình (R7).

## Danh sách ticket

| #   | Ticket                                                     |
| --- | ---------------------------------------------------------- |
| 01  | [Một lượt với trợ lý, không lưu](issues/01-luot-tro-ly.md) |
| 02  | [Bản nháp và mô phỏng](issues/02-ban-nhap-mo-phong.md)     |
| 03  | [Gửi duyệt và phát hành](issues/03-phat-hanh.md)           |
| 04  | [Màn hình trợ lý và thẻ duyệt](issues/04-man-hinh.md)      |
