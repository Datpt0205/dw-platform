# Bộ máy quy trình tối thiểu: tài liệu `dw.workflow/v1` do gói ship sẵn, biên dịch sang StateGraph

Status: needs-triage
Area: studio · Nhánh: `main` · Viết: 29/10/2026
Duyệt: agent, tạm theo ủy quyền 29/10/2026
Sẵn sàng: ĐẠT (29/10/2026; 0 CRITICAL, 0 HIGH; ticket 01-02)

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

- R1.1 `PackCatalog` PHẢI nạp mọi tệp `configs/packs/<pack>/workflows/<key>@<semver>.yaml` thành tài liệu có `schema: dw.workflow/v1`, `key`, `version`, `triggers[]`, `steps[]`, `variables[]`, `decision_classes[]` (`key`, `effect_level`, `reversible`, `ceiling`) và `work_kinds[]`, cùng sha256 của tệp.
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
- R3.2 NẾU một tham chiếu `{{ steps.<id>.<trường> }}` nêu một bước không đứng trước nó trên mọi đường từ gốc, hay nêu trường không có trong schema đầu ra của bước đó, THÌ bộ kiểm PHẢI trả `wf.ref_not_dominating` hay `wf.ref_unknown`.
- R3.3 NẾU một `logic.switch` thiếu lane mặc định, THÌ bộ kiểm PHẢI trả `wf.router_not_total`.
- R3.4 NẾU một `tool.call` nêu công cụ không có trong `ToolSpecRegistry`, hay một bước nêu `decision_class` không khai trong `decision_classes[]`, THÌ bộ kiểm PHẢI trả `wf.tool_unknown` hay `wf.decision_class_undeclared`.
- R3.5 NẾU một tài liệu trong `configs/packs/` có lỗi, THÌ API và worker PHẢI không khởi động, báo đường dẫn tệp và mã lỗi.
- R3.6 NẾU một tham chiếu `{{ params.<tên> }}` nêu tên không có trong `variables[]`, hay `{{ work.<trường> }}` nêu trường không có trong `properties` của schema của kind mà `trigger.work_item` nhận, THÌ bộ kiểm PHẢI trả `wf.param_undeclared` hay `wf.ref_unknown`.
- R3.7 NẾU một giá trị chuỗi chứa tham chiếu `{{ }}` cùng chữ khác, THÌ bộ kiểm PHẢI trả `wf.config_invalid`: tham chiếu chỉ thay nguyên một giá trị, không chèn vào chuỗi (ADR-0114 (Accepted): không ngôn ngữ mẫu thứ hai).
- R3.8 NẾU một bước `ai.llm` khai `min_confidence` mà `output_schema` không đòi trường `confidence` kiểu số 0-1, THÌ bộ kiểm PHẢI trả `wf.config_invalid`.

### R4 — Luật sàn HITL theo loại quyết định

Không tài liệu nào để một hiệu ứng ra ngoài xảy ra mà không có cổng của loại quyết định của nó (D16).

- R4.1 NẾU một `tool.call` gọi công cụ có `side_effect_level` `external` hay `critical` mà không nằm trong lane `approved` (trực tiếp hay lồng) của một `human.approval` cùng `decision_class`, THÌ bộ kiểm PHẢI trả `wf.hitl_gate_missing`.
- R4.3 NẾU `input` của một `tool.call` có cổng theo R4.1 không đúng bằng `{{ steps.<cổng>.proposal }}` của `human.approval` gác nó, THÌ bộ kiểm PHẢI trả `wf.unapproved_input` (D18).
- R4.2 NẾU `side_effect_level` của công cụ cao hơn `effect_level` của loại quyết định mà bước `tool.call` khai, THÌ bộ kiểm PHẢI trả `wf.effect_above_class`.

### R5 — Bước AI có đầu ra cấu trúc

Bước `ai.llm` phán đoán trong khung: prompt có phiên bản, đầu ra có schema, độ chắc chắn dưới ngưỡng thì bàn giao.

- R5.1 KHI một bước `ai.llm@1` chạy, bước PHẢI gọi `ModelGateway.generate_structured` với prompt `id@version` qua `PromptRegistry`, mọi giá trị tham chiếu bọc trong `<input>`, và ghi đầu ra đã kiểm theo `output_schema` của bước vào kênh `out__<id>`.
- R5.2 NẾU đầu ra không khớp `output_schema` sau số lần thử của gateway, THÌ lượt chạy PHẢI bàn giao việc cho Validator của DW với gói của R6.20 mang mã `model_output_invalid`, và không chạy bước nào sau đó.
- R5.3 NẾU `confidence` trong đầu ra thấp hơn `min_confidence` của bước, THÌ lượt chạy PHẢI bàn giao việc cho Validator của DW với gói của R6.20 mang mã `low_confidence` và đầu ra của bước, và không chạy bước nào sau đó.

### R6 — Biên dịch và chạy trên runner hiện có

Mỗi tài liệu biên dịch một lần thành StateGraph, chạy, dừng ở chỗ chờ và chạy tiếp sau checkpoint (ADR-0112 (Accepted) quyết 4).

- R6.1 Trình biên dịch PHẢI dựng `StateGraph` với một kênh `out__<id>` mỗi bước, `logic.switch` là cạnh có điều kiện tới lane rồi một nút gộp, và mỗi chờ là `interrupt()` ở dòng đầu nút của nó, đăng ký qua `GraphRegistry` với `worker_id` `dw:<key>` và `graph_version` là `version` của tài liệu.
- R6.2 NẾU `parameters` của DW không khớp `variables[]` của tài liệu hay DW thiếu một `decision_class` mà tài liệu dùng, THÌ bộ khởi chạy PHẢI chuyển việc sang `failed` với `parameter_invalid` hay `decision_class_missing` mà không chạy bước nào.
- R6.9 NẾU một loại quyết định trên DW có `effect_level` khác của tài liệu, `ceiling` cao hơn của tài liệu, hay `reversible` đúng khi tài liệu nói sai, THÌ bộ khởi chạy PHẢI chuyển việc sang `failed` với `decision_class_mismatch` mà không chạy bước nào.
- R6.3 KHI một bước `human.approval@1` chạy, bước PHẢI hỏi `DecisionGate` (digital-worker:R5.1) và đi lane "Duyệt" ngay khi cổng trả `auto`, còn không thì interrupt với approval `dw.decision`, việc sang `waiting_approval`, rồi đi lane "Duyệt" hay "Từ chối" theo quyết định khi chạy tiếp.
- R6.10 KHI một bước `human.approval@1` chạy tiếp với quyết định duyệt, bước PHẢI ghi vào `out__<id>.proposal` bản `edited_proposal` khi có, không thì đề xuất gốc, để bước sau tham chiếu đúng nội dung đã được duyệt (D18).
- R6.4 KHI một bước `tool.call@1` chạy, bước PHẢI gọi công cụ qua `ToolExecutor` với khóa chống lặp `wf:<run_id>:<step_id>:` của ADR-0112 (Accepted) quyết 5 (đường lặp rỗng ở lát này).
- R6.11 [Bỏ] 29/10/2026: chuyển về cửa công cụ, digital-worker:R6.2, theo gate lượt 1 (một chủ cho ranh giới công cụ).
- R6.5 KHI một bước `time.wait@1` interrupt với `wake_at`, runner PHẢI ghi việc `waiting_timer` với `wake_at` thay vì mở approval.
- R6.12 Lane `dw_timers` PHẢI chạy tiếp mỗi lượt có `wake_at` đã qua đúng một lần, qua hàm SECURITY DEFINER `platform.dw_timer_scopes_due(limit)` trả cặp `(tenant_id, workspace_id)` rồi một lần nhận `FOR UPDATE SKIP LOCKED` dưới `app.tenant_id` và `app.workspace_id`, dời `wake_at` thêm 15 phút trong giao dịch nhận (thuê), với lần chạy tiếp thứ hai của một lượt không còn chờ là no-op ở runner.
- R6.6 Mỗi nút PHẢI thêm vào kênh `trail` của lượt chạy một mục `{step_id, type, status, at}` (chỉ định danh và trạng thái, không nội dung).
- R6.13 `GET /v1/work-items/{id}` PHẢI trả `trail` của lượt chạy gắn với việc, đọc dưới ngữ cảnh tenant và workspace của người gọi như chính việc.
- R6.7 KHI lượt chạy của một việc kết thúc `completed` mà không bàn giao, bộ khởi chạy PHẢI chuyển việc sang `done` và ghi `closed_at`, và chuyển việc sang `failed` khi runner kết thúc lượt `failed` vì lỗi ngoài bước (hạ tầng, checkpoint).
- R6.8 Mọi lần gọi graph của wf-lite PHẢI truyền `durability="sync"` và `recursion_limit`, để checkpoint của một bước được ghi trước khi bước sau gây hiệu ứng.
- R6.14 KHI lượt chạy wf-lite bắt đầu, bộ khởi chạy PHẢI ghi sha256 của tài liệu vào cột mới `platform.worker_runs.definition_hash` của lượt (cột của run manifest, ADR-0109 (Accepted)), không vào `release_manifest_ref`, cột của release manifest nền tảng.
- R6.20 Mọi bàn giao tự động của wf-lite PHẢI có đủ bốn trường của digital-worker:R4.2: `problem` là mã và bước, `context` là các mục `trail` và đầu ra của bước khi có, `tried` là danh sách bước đã xong, `recommendation` là câu cố định theo mã trong `configs/copy/wflite_handoff.yaml`.
- R6.21 Cổng `human.approval` PHẢI ghi `proposal_schema` là schema đầu vào của công cụ của bước `tool.call` trong lane `approved` của nó (do trình biên dịch tính), không do tài liệu khai.
- R6.19 NẾU wrapper của một nút thấy sha256 của tài liệu đã biên dịch khác `definition_hash` của lượt, THÌ lượt chạy PHẢI bàn giao việc với `definition_changed` mà không chạy bước đó hay bước nào nữa.
- R6.15 TRONG KHI DW của việc không ở `operating`, lane `dw_timers` PHẢI để việc ở `waiting_timer` và không chạy tiếp lượt nào.
- R6.16 NẾU `ToolExecutor` từ chối lời gọi của một bước `tool.call` (digital-worker:R6.1, digital-worker:R6.2, R6.17), THÌ bước PHẢI bàn giao việc cho Validator với `problem` nêu mã từ chối và không chạy bước nào sau đó.
- R6.17 NẾU `ToolExecutor`, hỏi `DecisionAutonomy` (digital-worker:R2.3) cho `decision_class` mà bước khai, thấy chính sách tự chủ đòi người cho lời gọi mà lời gọi không mang id của một approval `dw.decision` đã duyệt của chính lượt chạy và bước cổng, hay băm JSON chuẩn (khóa xếp, không khoảng trắng) của bản đã duyệt khác băm của `input`, THÌ `ToolExecutor` PHẢI từ chối `approval_missing` hay `subject_changed` (ADR-0112 (Accepted) quyết 7) và không gọi công cụ.
- R6.18 NẾU một bước ném lỗi không phải lỗi chờ của LangGraph (`GraphInterrupt` đi qua nguyên vẹn), THÌ wrapper của nút PHẢI ghi mục `failed` vào `trail` và bàn giao việc cho Validator với gói của R6.20 mang bước và mã lỗi, thay vì để lỗi lên runner.

## Hành vi giữ nguyên

- G1 KHI một graph mã của context dừng ở interrupt không có `wait: timer`, runner PHẢI TIẾP TỤC mở approval như hôm nay (test: `packages/python/dw_agent_runtime/tests/unit/test_approval_flow.py`).

## Trong phạm vi

- Mô-đun `dw_agent_runtime.wflite` (tài liệu, sổ loại bước, bộ kiểm, trình biên dịch, nút), `PackCatalog` đọc `configs/packs/**`, lane `dw_timers` của worker, khóa `wait: timer` của interrupt trong runner, trường `trail` của `GET /v1/work-items/{id}`, cột `platform.worker_runs.definition_hash`, phép kiểm approval đã duyệt của R6.17 trong `ToolExecutor`, `configs/copy/wflite_handoff.yaml`.

## Ngoài phạm vi

| Việc                                                              | Vì sao                                                                  | Chủ                              |
| ----------------------------------------------------------------- | ----------------------------------------------------------------------- | -------------------------------- |
| Bản nháp, phiên bản do tenant dựng, cổng phát hành, mô phỏng      | D17: gói ship sẵn trước                                                 | workflow-engine, agent-lifecycle |
| CEL và 26 loại bước còn lại của ADR-0112 (Accepted)               | lát đầu chỉ cần sáu; CEL chờ ADR-0114 (Accepted)                        | workflow-nodes                   |
| Song song, vòng lặp, quy trình con, `on_error`, `retry` theo bước | bậc B và workflow-engine                                                | workflow-engine                  |
| `platform.run_steps` và màn Lịch sử chạy theo bước                | `trail` trong trạng thái lượt chạy đủ cho màn DW                        | telemetry-and-audit/03           |
| Gói Marketing, prompt, công cụ email                              | nội dung của DW đầu tiên                                                | `leadcare`                       |
| Hạn của approval `dw.decision` (`expired`) và hạn của lượt chạy   | ADR-0112 (Accepted) mục Open 2 và ADR-0113 (Accepted) quyết 3 chưa dựng | workflow-engine                  |
| Chờ sự kiện tương quan (thư trả lời đến thì chạy tiếp)            | W3; lát đầu hỏi hộp thư sau một bước hẹn giờ                            | đợt sau                          |

## Kiểm soát

| #     | Kiểm soát                                                                               | Yêu cầu          | Test âm                                                                                                                                                                                    |
| ----- | --------------------------------------------------------------------------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| WFL1  | tài liệu sai hình không được nạp                                                        | R1.2             | tệp có khóa lạ và tệp tên lệch phiên bản: `wf.schema_invalid`, catalog không có tài liệu đó                                                                                                |
| WFL2  | loại bước lạ hay config sai bị từ chối                                                  | R2.2             | bước `http.request@1` và `ai.llm@1` thiếu `prompt`: hai lỗi đúng mã                                                                                                                        |
| WFL3  | tham chiếu tới bước không đứng trước bị từ chối                                         | R3.2             | tham chiếu tới bước ở lane khác của switch: `wf.ref_not_dominating`                                                                                                                        |
| WFL4  | switch phải có lane mặc định                                                            | R3.3             | switch không `default`: `wf.router_not_total`                                                                                                                                              |
| WFL5  | công cụ và loại quyết định phải được khai                                               | R3.4             | công cụ không có spec, loại không khai: hai lỗi đúng mã                                                                                                                                    |
| WFL6  | tài liệu lỗi chặn khởi động                                                             | R3.5             | thêm một tệp lỗi vào thư mục gói tạm: dựng ứng dụng API và worker đều ném lỗi nêu tệp                                                                                                      |
| WFL7  | hiệu ứng ra ngoài chỉ nằm trong lane `approved` của cổng cùng loại                      | R4.1             | `tool.call` email không cổng, cổng ở lane khác, sau khối duyệt, và trong lane `rejected`: bốn lần `wf.hitl_gate_missing`; trong lane `approved`: hợp lệ                                    |
| WFL8  | công cụ không được vượt mức hiệu ứng của loại quyết định                                | R4.2             | công cụ `external` dưới loại `internal`: `wf.effect_above_class`                                                                                                                           |
| WFL9  | đầu ra model sai schema thì bàn giao, không chạy tiếp                                   | R5.2             | model giả trả JSON thiếu trường: việc `handed_off`, bước sau không có trong `trail`                                                                                                        |
| WFL10 | độ chắc chắn dưới ngưỡng thì bàn giao                                                   | R5.3             | `confidence` 0,4 với ngưỡng 0,7: việc `handed_off`, công cụ gửi không được gọi                                                                                                             |
| WFL11 | tham số sai hay thiếu loại quyết định thì không chạy bước nào                           | R6.2             | DW thiếu loại `email.send`: việc `failed` `decision_class_missing`, `trail` rỗng                                                                                                           |
| WFL12 | cổng đòi người thì không đi tiếp trước quyết định                                       | R6.3             | mức hiệu lực A2 với loại `external`: lượt chạy `waiting_approval`, công cụ gửi chưa được gọi                                                                                               |
| WFL13 | hiệu ứng đòi người chỉ chạy với quyết định đã duyệt khớp băm đầu vào                    | R6.17            | gọi `email.send` không id approval, với approval của lượt khác: `approval_missing`; với băm khác: `subject_changed`; công cụ không chạy                                                    |
| WFL14 | chờ hẹn giờ không mở approval, chạy tiếp một lần, có thuê                               | R6.5, R6.12      | interrupt `wait: timer`: không dòng approval; hai lane song song: một lần chạy tiếp; lane của tenant B không thấy việc của A; tiến trình chết sau khi nhận: việc được nhận lại sau 15 phút |
| WFL15 | `trail` không mang nội dung và không đọc chéo tenant                                    | R6.6, R6.13      | đầu ra model có email người: không chuỗi nào của nó trong `trail`; tenant B và workspace khác đọc việc của A: 404                                                                          |
| WFL16 | hiệu ứng không lặp lại khi chạy tiếp sau sự cố                                          | R6.4, R6.8       | dừng tiến trình sau bước gửi, chạy tiếp: `ToolExecutor` thấy khóa đã dùng, công cụ được gọi một lần                                                                                        |
| WFL18 | công cụ dùng bản đã duyệt, không bản nháp của model                                     | R6.10            | duyệt với tiêu đề đã sửa: thư gửi mang tiêu đề đã sửa, không tiêu đề của bản nháp                                                                                                          |
| WFL19 | hiệu ứng có cổng chỉ nhận đúng bản đã duyệt                                             | R4.3             | `input` là `{{ steps.draft.subject }}`, hay là bản đề xuất ghép thêm trường: `wf.unapproved_input`                                                                                         |
| WFL20 | tham chiếu và cấu hình sai bị bắt trước khi chạy                                        | R3.6, R3.7, R3.8 | `{{ params.khong_co }}`, `{{ work.khong_co }}`, `"Chào {{ work.name }}"`, `min_confidence` không có `confidence`: bốn lỗi đúng mã                                                          |
| WFL21 | lượt đang chờ không chạy tiếp trên tài liệu đã đổi                                      | R6.14, R6.19     | sửa tệp gói giữ `key@version` khi lượt `waiting_approval`, rồi duyệt: việc `handed_off` với `definition_changed`, công cụ không chạy                                                       |
| WFL22 | DW không `operating` không chạy tiếp hẹn giờ, và từ chối ở cửa công cụ dẫn tới bàn giao | R6.15, R6.16     | DW `paused` có việc quá hạn: lane không chạy tiếp; approval duyệt khi DW `paused`: `dw_not_operating`, việc `handed_off`, không thư                                                        |
| WFL23 | lỗi của bước không mất dấu vết                                                          | R6.18            | công cụ giả ném lỗi: `trail` có mục `failed`, việc `handed_off` với mã lỗi                                                                                                                 |
| WFL24 | tham chiếu tới trường không có trong đầu ra bị bắt                                      | R3.2             | `{{ steps.draft.khong_co }}`: `wf.ref_unknown`                                                                                                                                             |
| WFL25 | bàn giao tự động đủ bốn trường                                                          | R6.20            | `low_confidence`, `model_output_invalid`, lỗi bước: gói có đủ bốn trường không rỗng, `hand_off` nhận                                                                                       |
| WFL26 | lỗi chờ không bị nuốt                                                                   | R6.18            | wrapper bọc nút `human.approval`: lượt `waiting_approval`, không bàn giao                                                                                                                  |
| WFL17 | DW không nới loại quyết định của tài liệu                                               | R6.9             | DW khai `email.send` là `none` hay `reversible: true` trái tài liệu: việc `failed` `decision_class_mismatch`, `trail` rỗng                                                                 |

## Tiêu chí xong

- Mọi tiêu chí R và G có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (`scripts/mutate.py`).
- `make test-unit test-contract test-architecture` xanh và integration của `dw_agent_runtime`, `apps/worker`, `apps/api` xanh.

## Phụ thuộc

- ADR-0112 (Accepted) quyết 1-4, ADR-0128 (Proposed), ADR-0010 (Accepted) cho biến prompt không tin cậy.
- digital-worker:R3.3, digital-worker:R4.1, digital-worker:R5.1 (`WorkKindSchemas`, `WorkQueue.hand_off`, `DecisionGate`).
- `GraphRegistry`, `LangGraphWorkflowRunner`, `ModelGateway`, `PromptRegistry`, `ToolSpecRegistry`, `ToolExecutor`.
- Kiểm lại khi: workflow-engine thêm hạn của approval → ADR-0128 (Proposed) bước "approve" có hạn, R6.3; workflow-engine/01 dựng `WorkflowIR` → wf-lite chuyển sang IR đó; ADR-0114 (Accepted) có CEL → `logic.switch` nhận biểu thức; telemetry-and-audit/03 có `platform.run_steps` → R6.6 chuyển nguồn.

## Câu hỏi còn mở

## Quyết định

- 29/10/2026 (agent, tạm): Sổ có sáu loại, thêm `logic.switch@1` (chỉ so bằng một giá trị, lane mặc định bắt buộc) vào năm loại của hàng đợi, vì chăm sóc lead phải rẽ theo phân loại phản hồi và theo duyệt hay từ chối. Nếu sai thì: bỏ `logic.switch`, chăm sóc lead luôn nhắc rồi bàn giao, và nhánh theo phân loại chuyển vào gói bàn giao.
- 29/10/2026 (Đạt): D18: bước duyệt trả bản đã duyệt (có thể đã sửa) làm đầu ra. Sửa: R4.3, R6.10, WFL18, WFL19.
- 29/10/2026 (agent, tạm theo ủy quyền): Theo gate `checking-plan-readiness` lượt 1: hiệu ứng ra ngoài phải nằm trong lane `approved` (không chỉ đứng sau cổng) và nhận nguyên bản đã duyệt; `ToolExecutor` là cửa cuối, nhận lời gọi đòi người chỉ khi có approval đã duyệt khớp băm đầu vào, nên không có duyệt hai lần và không có đường vòng qua nút; lượt chạy ghim sha256 của tài liệu; DW dừng thì hẹn giờ không chạy tiếp và cửa công cụ từ chối; tham chiếu chỉ thay nguyên giá trị; lỗi của bước thành bàn giao có dấu vết; khóa chống lặp theo dạng của ADR-0112 (Accepted) quyết 5; `decision_class` của `ai.llm` và `initial_level` bỏ vì không ai đọc. Sửa: R1.1, R3.6-R3.8, R4.1, R4.3, R5.3, R6.4, R6.11, R6.12-R6.18, WFL7, WFL13-WFL15, WFL19-WFL23. Nếu sai thì: từng mục quay về bản trước gate trong lịch sử git của tệp này.
- 29/10/2026 (agent, tạm theo ủy quyền): Theo lượt xác nhận của gate: phép nhận theo cặp tenant và workspace (policy workspace của `work_items`); sha256 ghi vào `definition_hash`, không vào `release_manifest_ref` của nền tảng, và wrapper của mọi nút so nó (mọi đường chạy tiếp); `ToolExecutor` tự hỏi `DecisionAutonomy`, băm JSON chuẩn, `subject_changed` của ADR-0112 (Accepted) quyết 7; `GraphInterrupt` đi qua wrapper; bàn giao tự động đủ bốn trường, người nhận là Validator; `proposal_schema` do trình biên dịch tính; thuê 15 phút, chạy tiếp lần hai là no-op. Sửa: R3.2, R5.2, R5.3, R6.7, R6.12, R6.14, R6.17-R6.21, WFL13-WFL15, WFL24-WFL26. Nếu sai thì: từng mục quay về bản trước trong lịch sử git.
- 29/10/2026 (agent, tạm): `trail` trong trạng thái lượt chạy thay cho một bảng bước, vì `platform.run_steps` là của telemetry-and-audit/03 và hai bảng bước là hai câu trả lời. Nếu sai thì: wf-lite tạo `platform.run_steps` tối thiểu và telemetry-and-audit/03 mở rộng nó.
- 29/10/2026 (agent, tạm): "Chờ phản hồi" là `time.wait` rồi một công cụ đọc hộp thư, không là chờ sự kiện tương quan (W3). Nếu sai thì: thêm loại `event.wait@1` với khóa tương quan và cửa nhận thư trả lời.
- 29/10/2026 (agent, tạm theo ủy quyền): Duyệt cách chia ticket 01-02.

## Danh sách ticket

| #   | Ticket                                                                                  |
| --- | --------------------------------------------------------------------------------------- |
| 01  | [Tài liệu, sổ loại bước, bộ kiểm, luật sàn HITL](issues/01-tai-lieu-so-buoc-bo-kiem.md) |
| 02  | [Biên dịch, chạy, chờ và chạy tiếp](issues/02-bien-dich-va-chay.md)                     |
