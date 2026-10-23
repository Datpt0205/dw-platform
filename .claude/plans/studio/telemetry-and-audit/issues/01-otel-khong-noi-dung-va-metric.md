# 01 — Module ánh xạ OTel GenAI ghim commit, không nội dung; metric phát hoặc xóa

Status: needs-triage
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, TA1, TA2, TA3, TA8, TA9

## Mục tiêu

Một chủ cho mọi tên span, khóa thuộc tính và tên metric GenAI, ghim theo một commit semconv, có test hợp
đồng; span, log, Nhật ký kiểm toán và lỗi chỉ mang định danh và tên trường; bảy metric khai mà không phát
được phát hoặc xóa (spec R1).

## Việc cần làm

1. `packages/python/dw_observability/src/dw_observability/semconv.py`: hằng `GENAI_SEMCONV_COMMIT` ghim một
   commit của `open-telemetry/semantic-conventions`; hàm dựng tên span (`invoke_workflow`, `dw.node`,
   `invoke_agent`, `chat`, `execute_tool`, `retrieval`), khóa thuộc tính `dw.*` và tên metric GenAI; ảnh
   chụp `contracts/telemetry/genai-semconv@<sha12>.json` sinh ra và `--check` trong CI.
2. Test hợp đồng: chạy gateway, middleware, executor và runner qua một `RecordingTelemetry`, đỏ nếu một tên
   phát ra nằm ngoài ảnh chụp đã ghim (TA2).
3. Thay `gen_ai.system` bằng `gen_ai.provider.name`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/telemetry_usage.py:60`);
   `gen_ai.response.model` lấy từ phản hồi; sửa docstring `dw_observability/__init__.py:1`.
4. `TelemetryPort.record_histogram` với bucket theo spec; `OtelTelemetry` dùng `create_histogram` và View;
   `RecordingTelemetry.histograms`; `NullTelemetry`.
5. Phát `dw_run_duration_seconds`, `dw_tool_call_total`, `dw_approval_wait_seconds`; hằng
   `dw_node_failure_total{error_type}` cho bộ bọc node của workflow-engine; xóa `dw_retrieval_hit_rate`,
   `dw_human_intervention_rate`, `dw_task_success_rate`; test AST: mọi tên trong `ALL_METRICS` là đối số
   đầu của `add_metric`, `set_gauge` hay `record_histogram` trong `src/` (TA3).
6. Formatter log JSON cho API và worker với danh sách trường định danh cho phép; giá trị dạng email, số
   điện thoại hay query string bị bỏ cả khi khóa được phép; `test_logs_carry_ids_only` (TA8).
7. Một span processor thêm khóa Langfuse khi Langfuse bật, bỏ `user.id` và mọi thuộc tính nội dung
   (`gen_ai.input.messages`, đầu ra) trước khi gửi (TA9).
8. Luật một chủ: một span, dòng log, sự kiện Nhật ký kiểm toán hay thông điệp lỗi chỉ mang định danh và
   tên trường (TA1).

## Tiêu chí chấp nhận

- [ ] R1.1 (TA2): đổi một tên span trong `semconv` → test hợp đồng đỏ; tên ngoài ảnh chụp không được nhận.
- [ ] R1.2 (TA1): input có một số điện thoại → không span, log hay sự kiện Nhật ký kiểm toán nào chứa giá
      trị đó.
- [ ] R1.3 (TA3): thêm một hằng vào `ALL_METRICS` không có lời gọi phát → test AST đỏ; ba metric tỷ lệ đã
      xóa.
- [ ] R1.4 (TA9): span processor bỏ `user.id` và `gen_ai.input.messages`; gỡ bỏ → test exporter đỏ.
- [ ] R1.5 (TA8): một dòng log mang giá trị dạng email → `test_logs_carry_ids_only` đỏ.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `packages/python/dw_observability/src/dw_observability/metrics.py:12-22`; spec: R1.3.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/telemetry_usage.py:60`; spec: R1.1.
- ADR-0122 (Accepted) quyết 1, 2, 3.

## Comments

- 2026-10-23 (agent): gộp B10b telemetry-and-audit 01, 04; B11 compliance-pdpl 06 (telemetry không nội
  dung) và B4 field-security 05 (log chỉ id) về đây làm một chủ.
