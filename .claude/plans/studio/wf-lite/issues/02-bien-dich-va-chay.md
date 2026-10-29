# 02 — Biên dịch sang StateGraph, chạy trên runner hiện có, chờ duyệt, hẹn giờ và chạy tiếp

Status: needs-triage
Blocked by: 01
Area: studio
Yêu cầu: R5.1, R5.2, R5.3, R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7, R6.8, R6.9, G1, WFL9, WFL10, WFL11, WFL12, WFL13, WFL14, WFL15, WFL16, WFL17

## Mục tiêu

Mỗi tài liệu của gói biên dịch thành một StateGraph trên `LangGraphWorkflowRunner`; lane `dw_work`
chạy việc của DW qua nó; bước AI có đầu ra cấu trúc và bàn giao khi không chắc; cổng duyệt dừng lượt
chạy và chạy tiếp sau quyết định; hẹn giờ dừng không mở approval; không hiệu ứng nào lặp lại khi chạy
tiếp (R5, R6, G1).

## Việc cần làm

1. `dw_agent_runtime/wflite/compile.py`: `compile_workflow(doc, ports) -> StateGraph` theo R6.1; trạng
   thái có `work` (payload), `params`, `dw_id`, `work_item_id`, `out__<id>` mỗi bước, `trail` (reducer
   nối danh sách), `handed_off`; mỗi chờ là `interrupt()` dòng đầu nút; đăng ký mỗi tài liệu của
   `PackCatalog` vào `GraphRegistry` với `worker_id` `dw:<key>`, `graph_version` = `version`, và một
   `WorkerDefinition` sinh từ tài liệu (prompt bundle, toolset, policy theo phiên bản tài liệu).
2. Nút: `ai.llm@1` theo R5 (gateway, `PromptRegistry`, kiểm `output_schema` bằng `jsonschema`, bàn giao
   khi sai hay dưới `min_confidence`); `tool.call@1` qua `ToolExecutor` với khóa `<run_id>:<step_id>`,
   từ chối `tool_not_allowed` trước khi gọi; `human.approval@1` hỏi `DecisionGate`, `auto` thì lane
   `approved`, không thì interrupt với payload của cổng và lane theo `approved` khi chạy tiếp;
   `time.wait@1` interrupt `{wait: "timer", wake_at}`; `logic.switch@1` cạnh có điều kiện so bằng.
3. `LangGraphWorkflowRunner._handle_outcome`: interrupt có `wait: "timer"` → không approval, gọi
   `WaitRecorderPort.record_timer(run_context, run_id, wake_at)` (cấp bởi `WorkQueue`: việc
   `waiting_timer` với `wake_at`); approval → việc `waiting_approval`; mọi interrupt khác giữ như cũ (G1).
4. `DigitalWorkerRunStarter` thật cho lane `dw_work` (digital-worker/02): kiểm `parameters` theo
   `variables[]` và loại quyết định trên DW (R6.2), loại trên DW không nới loại của tài liệu (R6.9), dựng `RunContext` bằng `run_context_for`, gọi
   `runner.start`; kết thúc `completed` → việc `done`, `failed` → việc `failed` (R6.7).
5. Lane `dw_timers` ở `apps/worker/src/dw_worker/consumers/dw_timers.py`: nhận việc `waiting_timer` có
   `wake_at <= now()` bằng `FOR UPDATE SKIP LOCKED`, chuyển `in_progress`, gọi `runner.resume`.
6. Approval `dw.decision` được quyết thì `ApproveAndResumeService` chạy tiếp như hôm nay; việc trở lại
   `in_progress` khi chạy tiếp.
7. `GET /v1/work-items/{id}` trả `trail` đọc từ trạng thái lượt chạy (checkpoint khi đang chạy,
   `worker_runs.result` khi đã kết thúc), chỉ `{step_id, type, status, at}`.
8. Mọi `ainvoke` và `astream` của graph wf-lite truyền `durability="sync"` và `recursion_limit` (R6.8).
9. Test integration với PostgreSQL thật và model giả: lượt đi hết, lượt dừng ở duyệt rồi chạy tiếp,
   lượt hẹn giờ, lượt bàn giao; test âm WFL9-WFL16; WFL16 dừng tiến trình giữa bước gửi và bước sau rồi
   chạy tiếp.

## Tiêu chí chấp nhận

- [ ] R5.1: bước `ai.llm` gọi gateway với prompt `id@version`, biến bọc `<input>`, đầu ra trong `out__<id>`.
- [ ] R5.2 (WFL9): model giả trả JSON thiếu trường → việc `handed_off` với `problem` nêu `model_output_invalid`, bước sau không trong `trail`.
- [ ] R5.3 (WFL10): `confidence` 0,4 với ngưỡng 0,7 → `handed_off`, công cụ gửi không được gọi.
- [ ] R6.1: tài liệu mẫu biên dịch, đăng ký `dw:<key>@<version>`, `runner.hosts` đúng.
- [ ] R6.2 (WFL11): DW thiếu loại `email.send` → việc `failed` `decision_class_missing`, `trail` rỗng; tham số sai kiểu → `parameter_invalid`.
- [ ] R6.9 (WFL17): DW khai `email.send` là `none`, và `reversible: true` trái tài liệu → việc `failed` `decision_class_mismatch`, `trail` rỗng.
- [ ] R6.3 (WFL12): mức A2 cho loại `external` → lượt chạy `waiting_approval`, việc `waiting_approval`, công cụ chưa gọi; duyệt → chạy tiếp lane `approved`; từ chối → lane `rejected`.
- [ ] R6.4 (WFL13): công cụ ngoài `allowed_tools` → `tool_not_allowed`, `ToolExecutor` không được gọi.
- [ ] R6.5 (WFL14): `time.wait` → không dòng approval, việc `waiting_timer`; hai lane `dw_timers` song song → một lần chạy tiếp.
- [ ] R6.6 (WFL15): `trail` không chứa chuỗi nào của đầu ra model hay payload.
- [ ] R6.7: lượt đi hết → việc `done` có `closed_at`; lượt lỗi → việc `failed`.
- [ ] R6.8 (WFL16): dừng sau bước gửi rồi chạy tiếp → công cụ gửi được gọi đúng một lần; gỡ `durability="sync"` thì test đỏ.
- [ ] G1: `test_approval_flow.py` xanh không sửa.
- [ ] Xong: `make test-unit test-contract test-architecture` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:609-673`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/registry.py:29-47`; `docs/adr/0112-workflows-compile-to-langgraph-one-effect-per-node.md:117-135`; spec: R5, R6, G1, WFL9-WFL17.

## Comments
