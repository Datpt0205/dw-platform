# 03 — Biên dịch sang StateGraph, cache LRU và wrapper nút

Status: needs-triage
Blocked by: 01, 02
Area: studio
Yêu cầu: R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, R4.7, R4.8, R4.9, R4.10, WE5, WE7, WE13

## Mục tiêu

Biên dịch phần P1 của một phiên bản quy trình (tuần tự, router, chờ) thành một `StateGraph`, và cho một wrapper nút của nền tảng làm chủ retry, timeout, `on_error`, đúng một hiệu ứng mỗi node và kiểm đóng băng ở đầu node (R4 của spec).

## Việc cần làm

1. Trình biên dịch (`dw_studio.workflows.workflows.compiler`) dựng từ `WorkflowIR` của ticket 01: một kênh cho mỗi đầu ra node (không dùng một dict `vars` chung), router bằng cạnh điều kiện, node chờ là `interrupt()` đứng đầu, `recursion_limit` tính từ `limits.max_steps`, không bao giờ để mặc định thư viện. LangGraph chỉ ở module này và `dw_studio.agents.workflows` (studio-skeleton:R5.5).
2. Cache LRU trần 256 theo `(tenant_id, artifact_version_id, compiler_version)` trong `dw_agent_runtime.adapters`; hash schema state tính một lần.
3. Wrapper nút: `asyncio.timeout` từng lần, `retry` có backoff, `on_error` `fail` và `continue`; đúng một hiệu ứng mỗi node qua đúng cửa (`ToolExecutor`, `RecordsPort`, `ModelResolver`); khóa chống lặp `wf:{run_id}:{node_id}:{iteration_path}` (qua executor giành-lượt-trước của foundations-hardening/04); trần đầu ra 64 KiB; kiểm `RunControlPort` ở đầu node; span `dw.node`; gắn `app.actor_kind = 'workflow'` và `app.boundary_id` mỗi giao dịch (record-access/04).
4. Node không chứa SQL hay SDK nhà cung cấp; nhận cổng bằng tiêm (studio-skeleton:R5.4).

## Tiêu chí chấp nhận

- [ ] R4.1: config biên dịch không bao giờ thiếu `recursion_limit`; tài liệu lead mẫu của ticket 01 biên dịch và chạy với node giả.
- [ ] R4.2: 300 phiên bản biên dịch → cache ≤ 256; khóa gồm `compiler_version`.
- [ ] R4.3: node lỗi ba lần với `on_error: continue` → nhánh tiếp chạy; `on_error: fail` → lượt chạy `failed`, nhánh tiếp không chạy.
- [ ] R4.4: node gọi hai hiệu ứng ra ngoài → wrapper nút chặn hiệu ứng thứ hai; mỗi loại hiệu ứng đi qua đúng cửa của nó.
- [ ] R4.5 (WE7): hai worker chạy cùng node do lease giả hết hạn → nhà cung cấp giả nhận đúng một lần; bỏ khóa chống lặp → test đỏ.
- [ ] R4.6 (WE13): đầu ra 65.537 byte → node lỗi `output_too_large`, không ghi checkpoint lớn; 65.536 byte → nhận.
- [ ] R4.7: lượt chạy `simulate` gọi công cụ `external` → `ToolExecutor` giả lập, handler không chạy (tenant-config:R5.1); wrapper không có đường vòng.
- [ ] R4.8 (WE5): tắt khẩn giữa lượt chạy → node kế tiếp không chạy trong ≤ 5 giây; bỏ kiểm `RunControlPort` ở wrapper → test đỏ.
- [ ] R4.9: bước ghi qua `StepRecorderPort` có đầu vào và đầu ra đã che theo quyền người xem, span `dw.node`; `app.actor_kind = 'workflow'` gắn mỗi giao dịch.
- [ ] R4.10: thêm một module node có chuỗi SQL hay import SDK nhà cung cấp → test kiến trúc đỏ.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:127`; spec: R4, WE5, WE7, WE13.
- foundations-hardening:R6.1 (executor giành-lượt-trước); record-access:R6.4 (actor và biên dữ liệu); tenant-config:R5.1 (giả lập); ADR-0112 (Proposed) quyết 4-5.

## Comments
