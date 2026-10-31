# 01 — Một lượt với trợ lý, không lưu

Status: needs-triage
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R2.1, R2.2, R2.3, R2.4, R3.1, R4.1, R5.1, R5.2, R5.3, WAI1, WAI2, WAI3, WAI4, WAI5, WAI6, WAI7, WAI8

## Mục tiêu

Business Owner hay Technical Owner của một DW gửi một yêu cầu sửa quy trình bằng chữ và nhận lại một câu hỏi lại hoặc một đề xuất cây bước có kế hoạch, diff, lỗi của bộ kiểm và cờ `publishable`; chưa lưu, chưa mô phỏng, chưa phát hành (R1-R5).

## Việc cần làm

1. `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/assistant.py`: `AssistantTurn` (Pydantic, đầu ra của model: `kind` `question` hay `proposal`, `question` tối đa 1.000 ký tự, `plan` tối đa 8 dòng mỗi dòng 300 ký tự, `steps` là danh sách bước thô; không trường nào khác, `extra="forbid"`). `WorkflowAssistant` nhận `DwReaderPort` (có `require_owner`), `PinnedWorkflowsPort`, `ModelGateway`, `PromptRegistry`, sổ loại bước, công cụ và schema của kind; `turn(context, dw_id, instruction, history)`:
   kiểm độ dài (R1.4: `instruction` ≤ 4.000 ký tự, `history` ≤ 10 lượt, mỗi lượt ≤ 4.000, `role` là `user` hay `assistant`) rồi `require_owner` (R1.2) trước khi gọi model; đọc tài liệu gốc từ ghim của DW (R1.3, 404 `workflow_not_shipped` như `/workflow`); gọi `generate_structured` với `AssistantTurn`; khi `proposal`: dựng tài liệu đề xuất là bản sao của gốc chỉ thay `steps` (R2.1), chạy `validate` của wf-lite với sổ, công cụ và schema của gốc, cộng `wf.tool_not_in_base` và `wf.prompt_not_in_base` (R2.2, R2.3, thêm hai mã vào bảng thông điệp của `validate.py`), `publishable` khi không lỗi (R3.1).
2. `diff_steps(base, proposal, registry)` trong `wflite/outline.py`: thêm, bỏ, đổi (`config` hay `description`), đổi chỗ, theo `id`, mỗi mục với đường dẫn lane (R4.1). Bước có `id` trùng trong đề xuất là lỗi của bộ kiểm, diff không đoán.
3. `configs/prompts/wf_ai/workflow_edit@1.0.0.yaml`: biến `instruction`, `history`, `base_document` (YAML của tài liệu gốc), `node_types` (tên và mô tả sáu loại), không `raw_variables` (R5.1); fixture của provider `mock` cho prompt này trả một `proposal` hợp lệ trên `lead_care@1.0.0` (thêm một `time.wait` trước `fetch_reply`).
4. Route `POST /api/v1/digital-workers/{dw_id}/workflow-assistant` trong `apps/api/src/dw_api/routes/v1/digital_workers.py`, model thân và trả như mục API của spec; `ModelOutputInvalidError` thành 502 `upstream_unavailable` với `details.reason_code` `assistant_output_invalid` (R1.5); wiring ở `apps/api/src/dw_api/bootstrap/wiring.py` với gateway của runtime; snapshot OpenAPI và kiểu TS sinh lại (`make generate-contracts`).
5. `evals/datasets/wf_ai/` với ca chèn lệnh trong `instruction` và trong `description` của gốc (bỏ cổng duyệt, gọi công cụ khác, đổi loại quyết định) và grader `wf_ai.frozen` trong `dw_agent_runtime.testing`, đăng ký ở `scripts/run_evals.py` (R5.2, R5.3); chạy với model thật để trống tới khi có khóa (Chờ Đạt 21), ghi ở Comments.
6. Test unit cho `AssistantTurn`, `diff_steps`, kiểm "chỉ từ cái đã có", độ dài; test route với gateway giả đếm số lần gọi; `mutations/01.yaml` một đột biến mỗi kiểm soát WAI1-WAI8.

## Tiêu chí chấp nhận

- [ ] R1.1: gateway giả trả `question` thì route trả `kind: question` không `steps`; trả `proposal` thì có `plan`, `steps`, `diff`, `problems`, `publishable`.
- [ ] R1.2 (WAI1): Validator của DW gọi route: 403 `not_dw_owner`, gateway giả 0 lần gọi; người không `dw.read`: 404.
- [ ] R1.3 (WAI2): thân có `workflow_key: other` và `tenant_id` khác: tài liệu gốc trong prompt và trong đề xuất là `lead_care@1.0.0` mà DW ghim.
- [ ] R1.4 (WAI3): `instruction` 4.001 ký tự, hay 11 lượt `history`: 422 `assistant_input_too_long`, gateway giả 0 lần gọi.
- [ ] R1.5: gateway giả ném `ModelOutputInvalidError`: 502 với `reason_code` `assistant_output_invalid`, không `steps`.
- [ ] R2.1 (WAI4): một đề xuất hợp lệ giữ nguyên mọi khóa ngoài `steps` của gốc, so từng khóa.
- [ ] R2.4 (WAI4): gateway giả trả thêm `decision_classes`: `AssistantTurn` từ chối, route trả 502 `assistant_output_invalid` như R1.5.
- [ ] R2.2 (WAI5): đề xuất gọi công cụ gốc không gọi: lỗi `wf.tool_not_in_base` ở đúng bước, `publishable` sai.
- [ ] R2.3 (WAI6): đề xuất nêu prompt gốc không dùng: `wf.prompt_not_in_base`, `publishable` sai.
- [ ] R3.1 (WAI7): đề xuất đưa `send` ra khỏi lane `approved`: `wf.hitl_gate_missing`, `publishable` sai; đề xuất của fixture mock: không lỗi, `publishable` đúng.
- [ ] R4.1: diff của fixture mock nêu đúng một bước thêm, `id` và lane `approved` của `approve_send`; bỏ một bước và đổi chỗ một bước cho đúng mục.
- [ ] R5.1 (WAI8): `instruction` chứa `</input>` và câu lệnh: prompt dựng có chuỗi đã escape trong khối `<input name="instruction">`.
- [ ] R5.2: `evals/datasets/wf_ai` có ít nhất ba ca chèn lệnh, mỗi ca một trong ba ý đồ.
- [ ] R5.3: grader `wf_ai.frozen` chấm đỏ một đề xuất có `wf.hitl_gate_missing` và một đề xuất đổi `decision_classes`, xanh với đề xuất của fixture (test unit của grader).
- [ ] Xong: `make test-unit test-contract test-architecture` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/validate.py:118-130`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/outline.py:56`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/ports.py:56-62`; `packages/python/dw_platform/src/dw_platform/application/digital_workers.py:303`; spec: R1-R5, WAI1-WAI8.

## Comments

- 2026-10-31 (agent): viết cùng spec.
