# Bộ máy quy trình tối thiểu: tài liệu `dw.workflow/v1` do gói ship sẵn, biên dịch sang StateGraph

Status: needs-triage
Area: studio · Nhánh: `main` · Viết: 29/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Digital Worker đầu tiên chạy một quy trình xác định làm xương sống, agent chỉ ở bước cần phán đoán (D15). Theo đường C của D17, quy trình là một tài liệu `dw.workflow/v1` do gói ship sẵn trong `configs/packs/`, tenant chỉ chỉnh tham số, và bộ máy chạy nó là tập con đúng hình của ADR-0112 (Accepted): cùng cây `steps[]`, cùng tên loại bước, cùng mã `wf.*`, cùng cách biên dịch, để workflow-engine sau này mở rộng chứ không viết lại. Spec này không có bản nháp, phiên bản do tenant dựng hay cổng phát hành: đó là workflow-engine và agent-lifecycle.

## Hiện trạng (đã kiểm ở `8508502` ngày 29/10/2026)

- `GraphRegistry` ánh xạ `(worker_id, graph_version)` tới một hàm dựng `StateGraph` chưa biên dịch và báo lỗi lúc khởi động khi thiếu (`packages/python/dw_agent_runtime/src/dw_agent_runtime/registry.py:29-47`). Ràng buộc: graph biên dịch từ tài liệu đăng ký qua cửa này.
- `LangGraphWorkflowRunner` bắt đầu, chạy tiếp và đọc trạng thái lượt chạy có checkpoint (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:290`, `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:525`, `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:581`). Ràng buộc: wf-lite chạy trên runner này, không runner thứ hai.
- Mọi interrupt của graph thành một approval với `approval_type`, `reason`, `required_scope` từ giá trị interrupt (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:609-660`), hết bước thì `result` là trạng thái cuối (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:671-673`). Thiếu: một chờ hẹn giờ không phải approval.
- Model trả đầu ra có cấu trúc qua `ModelGateway.generate_structured` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/ports.py:51-62`), prompt qua `PromptRegistry` bọc biến trong `<input>` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/prompts.py:88`). Ràng buộc: bước `ai.llm` dùng hai cửa này.
- Công cụ khai ở `configs/tools` qua `ToolSpecRegistry` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/tool_specs.py:110`), chạy qua một `ToolExecutor` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:79`). Ràng buộc: bước `tool.call` không có cửa hiệu ứng nào khác.
- ADR-0112 (Accepted) quyết 1-4 định hình tài liệu, sổ loại bước, bộ kiểm một lượt và cách biên dịch (`docs/adr/0112-workflows-compile-to-langgraph-one-effect-per-node.md:47-135`). Ràng buộc: wf-lite là tập con, không tên hay mã nào trái ADR đó.
- Không có biểu thức CEL nào chạy được trong repo (ADR-0114 (Accepted) chờ FOG-50; `docs/adr/0114-cel-is-the-one-expression-language.md:1`). Ràng buộc: `logic.switch` của wf-lite chỉ so bằng một giá trị.

## Mục tiêu

### R1 — Tài liệu `dw.workflow/v1` của gói

Gói ship quy trình của DW thành một tệp YAML mà nền tảng đọc, kiểm và ghim.

- R1.1 `PackCatalog` PHẢI nạp mọi tệp `configs/packs/<pack>/workflows/<key>@<semver>.yaml` thành tài liệu có `schema: dw.workflow/v1`, `key`, `version`, `triggers[]`, `steps[]`, `variables[]`, `decision_classes[]` và `work_kinds[]`, cùng sha256 của tệp.
- R1.2 NẾU tài liệu có khóa cấp trên cùng lạ, thiếu khóa bắt buộc, hay `key@version` không khớp tên tệp, THÌ `PackCatalog` PHẢI báo `wf.schema_invalid` với đường dẫn tới chỗ sai và không nạp tài liệu.
- R1.3 Một bước PHẢI có dạng `{id, type, config, description?}` với `id` khớp `^[a-z][a-z0-9_]{0,39}$`, duy nhất trong tài liệu, và `type` dạng `name@major`.
- R1.4 `PackCatalog` PHẢI nạp JSON Schema của mỗi `work_kinds[].schema` từ `configs/packs/<pack>/schemas/` và trả nó qua `WorkKindSchemas` (digital-worker:R3.3).

### R2 — Sổ loại bước

Bộ kiểm và trình biên dịch đọc cùng một sổ (ADR-0112 (Accepted) quyết 2).

- R2.1 `build_node_registry` PHẢI trả đúng sáu loại `trigger.work_item@1`, `ai.llm@1`, `tool.call@1`, `human.approval@1`, `time.wait@1`, `logic.switch@1`, mỗi loại mang schema config, schema đầu ra, các cổng (lane) và `side_effect_level`.
- R2.2 NẾU một bước có `type` không trong sổ, hay `config` không khớp schema config của loại, THÌ bộ kiểm PHẢI trả `wf.unknown_type` hay `wf.config_invalid` cho bước đó.

### R3 — Bộ kiểm một lượt

Mọi lỗi của một tài liệu được báo cùng lúc, trước khi worker nhận việc nào (ADR-0112 (Accepted) quyết 3).

- R3.1 Bộ kiểm PHẢI trả mọi lỗi một lượt dạng `[{path, code, message_vi, message_en}]`, danh sách rỗng khi tài liệu hợp lệ.
- R3.2 NẾU một tham chiếu `{{ steps.<id>.<trường> }}` nêu một bước không đứng trước nó trên mọi đường từ gốc, THÌ bộ kiểm PHẢI trả `wf.ref_not_dominating`.
- R3.3 NẾU một `logic.switch` thiếu lane mặc định, THÌ bộ kiểm PHẢI trả `wf.router_not_total`.
- R3.4 NẾU một `tool.call` nêu công cụ không có trong `ToolSpecRegistry`, hay một bước nêu `decision_class` không khai trong `decision_classes[]`, THÌ bộ kiểm PHẢI trả `wf.tool_unknown` hay `wf.decision_class_undeclared`.
- R3.5 NẾU một tài liệu trong `configs/packs/` có lỗi, THÌ API và worker PHẢI không khởi động, báo đường dẫn tệp và mã lỗi.

### R4 — Luật sàn HITL theo loại quyết định

Không tài liệu nào để một hiệu ứng ra ngoài xảy ra mà không có cổng của loại quyết định của nó (D16).

- R4.1 NẾU một `tool.call` gọi công cụ có `side_effect_level` `external` hay `critical` mà không có `human.approval` cùng `decision_class` đứng trước nó trên mọi đường từ gốc, THÌ bộ kiểm PHẢI trả `wf.hitl_gate_missing`.
- R4.2 NẾU `side_effect_level` của công cụ cao hơn `effect_level` của loại quyết định mà bước `tool.call` khai, THÌ bộ kiểm PHẢI trả `wf.effect_above_class`.

### R5 — Bước AI có đầu ra cấu trúc

Bước `ai.llm` phán đoán trong khung: prompt có phiên bản, đầu ra có schema, độ chắc chắn dưới ngưỡng thì bàn giao.

- R5.1 KHI một bước `ai.llm@1` chạy, bước PHẢI gọi `ModelGateway.generate_structured` với prompt `id@version` qua `PromptRegistry`, mọi giá trị tham chiếu bọc trong `<input>`, và ghi đầu ra đã kiểm theo `output_schema` của bước vào kênh `out__<id>`.
- R5.2 NẾU đầu ra không khớp `output_schema` sau số lần thử của gateway, THÌ lượt chạy PHẢI bàn giao việc qua `WorkQueue.hand_off` với `problem` nêu bước và mã `model_output_invalid`, và không chạy bước nào sau đó.
- R5.3 NẾU `confidence` trong đầu ra thấp hơn `min_confidence` của bước, THÌ lượt chạy PHẢI bàn giao việc với gói có đầu ra của bước làm `context` và không chạy bước nào sau đó.

### R6 — Biên dịch và chạy trên runner hiện có

Mỗi tài liệu biên dịch một lần thành StateGraph, chạy, dừng ở chỗ chờ và chạy tiếp sau checkpoint (ADR-0112 (Accepted) quyết 4).

- R6.1 Trình biên dịch PHẢI dựng `StateGraph` với một kênh `out__<id>` mỗi bước, `logic.switch` là cạnh có điều kiện tới lane rồi một nút gộp, và mỗi chờ là `interrupt()` ở dòng đầu nút của nó, đăng ký qua `GraphRegistry` với `worker_id` `dw:<key>` và `graph_version` là `version` của tài liệu.
- R6.2 KHI lane `dw_work` yêu cầu lượt chạy cho một việc, bộ khởi chạy PHẢI kiểm `parameters` của DW theo `variables[]` và sự có mặt trên DW của mọi `decision_class` tài liệu dùng, và NẾU sai THÌ PHẢI chuyển việc sang `failed` với `parameter_invalid` hay `decision_class_missing` mà không chạy bước nào.
- R6.9 NẾU một loại quyết định trên DW có `effect_level` khác của tài liệu, `ceiling` cao hơn của tài liệu, hay `reversible` đúng khi tài liệu nói sai, THÌ bộ khởi chạy PHẢI chuyển việc sang `failed` với `decision_class_mismatch` mà không chạy bước nào.
- R6.3 KHI một bước `human.approval@1` chạy, bước PHẢI hỏi `DecisionGate` (digital-worker:R5.1) và đi lane "Duyệt" ngay khi cổng trả `auto`, còn không thì interrupt với approval `dw.decision`, việc sang `waiting_approval`, rồi đi lane "Duyệt" hay "Từ chối" theo quyết định khi chạy tiếp.
- R6.4 KHI một bước `tool.call@1` chạy, bước PHẢI gọi công cụ qua `ToolExecutor` với khóa chống lặp `<run_id>:<step_id>`; NẾU công cụ không có trong `allowed_tools` của DW, THÌ bước PHẢI từ chối `tool_not_allowed` mà không gọi `ToolExecutor`.
- R6.5 KHI một bước `time.wait@1` chạy, bước PHẢI interrupt với `wake_at`, runner PHẢI ghi việc `waiting_timer` với `wake_at` thay vì mở approval, và lane `dw_timers` PHẢI chạy tiếp mỗi lượt có `wake_at` đã qua đúng một lần.
- R6.6 Mỗi nút PHẢI thêm vào kênh `trail` của lượt chạy một mục `{step_id, type, status, at}` (chỉ định danh và trạng thái, không nội dung), và `GET /v1/work-items/{id}` PHẢI trả `trail` đó.
- R6.7 KHI lượt chạy của một việc kết thúc `completed` mà không bàn giao, hay `failed`, bộ khởi chạy PHẢI chuyển việc sang `done` hay `failed` tương ứng và ghi `closed_at`.
- R6.8 Mọi lần gọi graph của wf-lite PHẢI truyền `durability="sync"` và `recursion_limit`, để checkpoint của một bước được ghi trước khi bước sau gây hiệu ứng.

## Hành vi giữ nguyên

- G1 KHI một graph mã của context dừng ở interrupt không có `wait: timer`, runner PHẢI TIẾP TỤC mở approval như hôm nay (test: `packages/python/dw_agent_runtime/tests/unit/test_approval_flow.py`).

## Trong phạm vi

- Mô-đun `dw_agent_runtime.wflite` (tài liệu, sổ loại bước, bộ kiểm, trình biên dịch, nút), `PackCatalog` đọc `configs/packs/**`, lane `dw_timers` của worker, khóa `wait: timer` của interrupt trong runner, trường `trail` của `GET /v1/work-items/{id}`.

## Ngoài phạm vi

| Việc                                                              | Vì sao                                           | Chủ                              |
| ----------------------------------------------------------------- | ------------------------------------------------ | -------------------------------- |
| Bản nháp, phiên bản do tenant dựng, cổng phát hành, mô phỏng      | D17: gói ship sẵn trước                          | workflow-engine, agent-lifecycle |
| CEL và 26 loại bước còn lại của ADR-0112 (Accepted)               | lát đầu chỉ cần sáu; CEL chờ ADR-0114 (Accepted) | workflow-nodes                   |
| Song song, vòng lặp, quy trình con, `on_error`, `retry` theo bước | bậc B và workflow-engine                         | workflow-engine                  |
| `platform.run_steps` và màn Lịch sử chạy theo bước                | `trail` trong trạng thái lượt chạy đủ cho màn DW | telemetry-and-audit/03           |
| Gói Marketing, prompt, công cụ email                              | nội dung của DW đầu tiên                         | `leadcare`                       |
| Chờ sự kiện tương quan (thư trả lời đến thì chạy tiếp)            | W3; lát đầu hỏi hộp thư sau một bước hẹn giờ     | đợt sau                          |

## Kiểm soát

| #     | Kiểm soát                                                      | Yêu cầu    | Test âm                                                                                                                    |
| ----- | -------------------------------------------------------------- | ---------- | -------------------------------------------------------------------------------------------------------------------------- |
| WFL1  | tài liệu sai hình không được nạp                               | R1.2       | tệp có khóa lạ và tệp tên lệch phiên bản: `wf.schema_invalid`, catalog không có tài liệu đó                                |
| WFL2  | loại bước lạ hay config sai bị từ chối                         | R2.2       | bước `http.request@1` và `ai.llm@1` thiếu `prompt`: hai lỗi đúng mã                                                        |
| WFL3  | tham chiếu tới bước không đứng trước bị từ chối                | R3.2       | tham chiếu tới bước ở lane khác của switch: `wf.ref_not_dominating`                                                        |
| WFL4  | switch phải có lane mặc định                                   | R3.3       | switch không `default`: `wf.router_not_total`                                                                              |
| WFL5  | công cụ và loại quyết định phải được khai                      | R3.4       | công cụ không có spec, loại không khai: hai lỗi đúng mã                                                                    |
| WFL6  | tài liệu lỗi chặn khởi động                                    | R3.5       | thêm một tệp lỗi vào thư mục gói tạm: dựng ứng dụng API và worker đều ném lỗi nêu tệp                                      |
| WFL7  | hiệu ứng ra ngoài phải có cổng cùng loại quyết định đứng trước | R4.1       | `tool.call` email không có `human.approval` trước, và có cổng nhưng ở lane khác: `wf.hitl_gate_missing`                    |
| WFL8  | công cụ không được vượt mức hiệu ứng của loại quyết định       | R4.2       | công cụ `external` dưới loại `internal`: `wf.effect_above_class`                                                           |
| WFL9  | đầu ra model sai schema thì bàn giao, không chạy tiếp          | R5.2       | model giả trả JSON thiếu trường: việc `handed_off`, bước sau không có trong `trail`                                        |
| WFL10 | độ chắc chắn dưới ngưỡng thì bàn giao                          | R5.3       | `confidence` 0,4 với ngưỡng 0,7: việc `handed_off`, công cụ gửi không được gọi                                             |
| WFL11 | tham số sai hay thiếu loại quyết định thì không chạy bước nào  | R6.2       | DW thiếu loại `email.send`: việc `failed` `decision_class_missing`, `trail` rỗng                                           |
| WFL12 | cổng đòi người thì không đi tiếp trước quyết định              | R6.3       | mức hiệu lực A2 với loại `external`: lượt chạy `waiting_approval`, công cụ gửi chưa được gọi                               |
| WFL13 | công cụ ngoài `allowed_tools` không được gọi                   | R6.4       | DW không có `email.send` trong `allowed_tools`: bước từ chối, `ToolExecutor` không được gọi                                |
| WFL14 | chờ hẹn giờ không mở approval và chỉ được chạy tiếp một lần    | R6.5       | interrupt `wait: timer`: không dòng approval nào; hai lane `dw_timers` song song: một lần chạy tiếp                        |
| WFL15 | `trail` không mang nội dung                                    | R6.6       | đầu ra model có email người: không chuỗi nào của đầu ra xuất hiện trong `trail` trả về                                     |
| WFL16 | hiệu ứng không lặp lại khi chạy tiếp sau sự cố                 | R6.4, R6.8 | dừng tiến trình sau bước gửi, chạy tiếp: `ToolExecutor` thấy khóa đã dùng, công cụ được gọi một lần                        |
| WFL17 | DW không nới loại quyết định của tài liệu                      | R6.9       | DW khai `email.send` là `none` hay `reversible: true` trái tài liệu: việc `failed` `decision_class_mismatch`, `trail` rỗng |

## Tiêu chí xong

- Mọi tiêu chí R và G có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (`scripts/mutate.py`).
- `make test-unit test-contract test-architecture` xanh và integration của `dw_agent_runtime`, `apps/worker` xanh.

## Phụ thuộc

- ADR-0112 (Accepted) quyết 1-4, ADR-0128 (Proposed), ADR-0010 (Accepted) cho biến prompt không tin cậy.
- digital-worker:R3.3, digital-worker:R4.1, digital-worker:R5.1 (`WorkKindSchemas`, `WorkQueue.hand_off`, `DecisionGate`).
- `GraphRegistry`, `LangGraphWorkflowRunner`, `ModelGateway`, `PromptRegistry`, `ToolSpecRegistry`, `ToolExecutor`.
- Kiểm lại khi: workflow-engine/01 dựng `WorkflowIR` → wf-lite chuyển sang IR đó; ADR-0114 (Accepted) có CEL → `logic.switch` nhận biểu thức; telemetry-and-audit/03 có `platform.run_steps` → R6.6 chuyển nguồn.

## Câu hỏi còn mở

## Quyết định

- 29/10/2026 (agent, tạm): Sổ có sáu loại, thêm `logic.switch@1` (chỉ so bằng một giá trị, lane mặc định bắt buộc) vào năm loại của hàng đợi, vì chăm sóc lead phải rẽ theo phân loại phản hồi và theo duyệt hay từ chối. Nếu sai thì: bỏ `logic.switch`, chăm sóc lead luôn nhắc rồi bàn giao, và nhánh theo phân loại chuyển vào gói bàn giao.
- 29/10/2026 (agent, tạm): `trail` trong trạng thái lượt chạy thay cho một bảng bước, vì `platform.run_steps` là của telemetry-and-audit/03 và hai bảng bước là hai câu trả lời. Nếu sai thì: wf-lite tạo `platform.run_steps` tối thiểu và telemetry-and-audit/03 mở rộng nó.
- 29/10/2026 (agent, tạm): "Chờ phản hồi" là `time.wait` rồi một công cụ đọc hộp thư, không là chờ sự kiện tương quan (W3). Nếu sai thì: thêm loại `event.wait@1` với khóa tương quan và cửa nhận thư trả lời.

## Danh sách ticket

| #   | Ticket                                                                                  |
| --- | --------------------------------------------------------------------------------------- |
| 01  | [Tài liệu, sổ loại bước, bộ kiểm, luật sàn HITL](issues/01-tai-lieu-so-buoc-bo-kiem.md) |
| 02  | [Biên dịch, chạy, chờ và chạy tiếp](issues/02-bien-dich-va-chay.md)                     |
