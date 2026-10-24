# 03 — Biên dịch sang StateGraph, cache LRU và wrapper nút

Status: needs-triage
Blocked by: 01, 02, .claude/plans/studio/record-access/issues/04-ngu-canh-actor-o-moi-cua.md, .claude/plans/studio/custom-objects/issues/03-record-service.md
Area: studio
Yêu cầu: R1.7, R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, R4.7, R4.8, R4.9, R4.10, WE5, WE7, WE13

## Mục tiêu

Biên dịch phần P1 của một phiên bản quy trình (tuần tự, router, chờ) thành một `StateGraph`, và cho một wrapper nút của nền tảng làm chủ retry, timeout, `on_error`, đúng một hiệu ứng mỗi node và kiểm đóng băng ở đầu node (R4 của spec); móc phát hành của loại `workflow` ghi giới hạn dữ liệu của phiên bản, mà wrapper gắn vào `app.boundary_id` (R1.7).

## Việc cần làm

1. Trình biên dịch (`dw_studio.workflows.workflows.compiler`) dựng từ `WorkflowIR` của ticket 01: một kênh cho mỗi đầu ra node (không dùng một dict `vars` chung), router bằng cạnh điều kiện, node chờ là `interrupt()` đứng đầu, `recursion_limit` tính từ `limits.max_steps`, không bao giờ để mặc định thư viện. LangGraph chỉ ở module này và `dw_studio.agents.workflows` (studio-skeleton:R5.5).
2. Cache LRU trần 256 theo `(tenant_id, artifact_version_id, mã băm ghim, compiler_version)` trong `dw_agent_runtime.adapters`, mã băm ghim là `definition_hash` của bản đã niêm phong hay mã băm tạm của bản Nháp trong bản kê của lượt mô phỏng (workflow-engine/02, R3.9), vì bản Nháp đổi nội dung mà giữ id; hash schema state tính một lần.
3. Wrapper nút: `asyncio.timeout` từng lần, `retry` có backoff, `on_error` `fail` và `continue`; đúng một hiệu ứng mỗi node qua đúng cửa (`ToolExecutor`, `RecordsPort`, `ModelResolver`), chuyển `run_mode` của lượt chạy tới cửa đó để chính cửa giả lập ở `simulate`; khóa chống lặp `wf:{run_id}:{node_id}:{iteration_path}` (qua executor giành-lượt-trước của foundations-hardening/04); trần đầu ra 64 KiB; kiểm `RunControlPort` ở đầu node; span `dw.node`; gắn `app.actor_kind = 'workflow'` và `app.boundary_id` mỗi giao dịch (record-access/04).
4. Node không chứa SQL hay SDK nhà cung cấp; nhận cổng bằng tiêm (studio-skeleton:R5.4).
5. Giới hạn dữ liệu của phiên bản (R1.7; record-access:R6.7): thêm vào `publish_hook` của loại `workflow` (ticket 01) một lời gọi `ActorBoundaryPort.record` của record-access/04 với loại `workflow` và phiên bản vừa lên `live`, trên đúng giao dịch phát hành mà móc nhận, sau lời gọi `TriggerActivationPort`, không mở giao dịch riêng. Giới hạn dẫn từ các node `data.object.*` của tài liệu (ADR-0103 (Accepted) quyết 5): mỗi object mà một node nêu là một dòng, mang hợp cờ của mọi lệnh mà lời gọi `RecordsPort` của các node nêu object đó chạy dưới policy của `studio.records` (record-access/04, bước 5), và mỗi Trường mà cấu hình một node nêu là một dòng, `edit` khi một node ghi Trường đó, không thì `read`, vì khóa chính của `studio.actor_boundary_objects` và `studio.actor_boundary_fields` là một dòng mỗi object, mỗi Trường của giới hạn (record-access/04, bước 1); tài liệu không có node dữ liệu nào thì giới hạn rỗng. Wrapper nút của bước 3 gắn id của giới hạn đó vào `app.boundary_id` (R4.9).

## Tiêu chí chấp nhận

- [ ] R4.1: config biên dịch không bao giờ thiếu `recursion_limit`; tài liệu lead mẫu của ticket 01 biên dịch và chạy với node giả.
- [ ] R4.2: 300 phiên bản biên dịch → cache ≤ 256; khóa gồm mã băm ghim và `compiler_version`; sửa một bản Nháp rồi xin lượt mô phỏng mới → graph biên dịch lại từ nội dung mới, không lấy graph của nội dung cũ trong cache.
- [ ] R4.3: node lỗi ba lần với `on_error: continue` → nhánh tiếp chạy; `on_error: fail` → lượt chạy `failed`, nhánh tiếp không chạy.
- [ ] R4.4: node gọi hai hiệu ứng ra ngoài → wrapper nút chặn hiệu ứng thứ hai; mỗi loại hiệu ứng đi qua đúng cửa của nó.
- [ ] R4.5 (WE7): hai worker chạy cùng node do lease giả hết hạn → nhà cung cấp giả nhận đúng một lần; bỏ khóa chống lặp → test đỏ.
- [ ] R4.6 (WE13): đầu ra 65.537 byte → node lỗi `output_too_large`, không ghi checkpoint lớn; 65.536 byte → nhận.
- [ ] R4.7: lượt chạy `simulate` gọi công cụ `external` → `ToolExecutor` giả lập, handler không chạy (tenant-config:R5.1); một bước bản ghi ở `simulate` → `RecordsPort` nhận `run_mode` `simulate` và RecordService không ghi dòng nào (custom-objects:R5.4); wrapper không có đường vòng.
- [ ] R4.8 (WE5): tắt khẩn giữa lượt chạy, hay chủ thể chạy bị tạm khóa giữa lượt chạy → node kế tiếp không chạy trong ≤ 5 giây; bỏ kiểm `RunControlPort` ở wrapper → test đỏ.
- [ ] R4.9: bước ghi qua `StepRecorderPort` có đầu vào và đầu ra đã che theo quyền người xem, span `dw.node`; `app.actor_kind = 'workflow'` gắn mỗi giao dịch.
- [ ] R4.10: thêm một module node có chuỗi SQL hay import SDK nhà cung cấp → test kiến trúc đỏ.
- [ ] R1.7: gọi `publish_hook` của `workflow` trong một giao dịch thử cho một phiên bản có một node `data.object.query` và một node `data.object.create` (loại node giả của fixture tới khi workflow-nodes/04 đăng ký loại thật) trên một object thử → `studio.actor_boundaries` có đúng một giới hạn `workflow` cho phiên bản đó, chỉ có object đó với cờ của hai node; giao dịch lùi → không giới hạn nào; một lượt chạy của phiên bản đọc được bản ghi của object đó dưới `app.boundary_id` của giới hạn, còn một lệnh sửa bản ghi đó dưới cùng giới hạn bị policy từ chối; gỡ lời gọi `ActorBoundaryPort` khỏi móc → lượt chạy đọc 0 bản ghi, test đỏ.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:127`; spec: R4, WE5, WE7, WE13.
- foundations-hardening:R6.1 (executor giành-lượt-trước); record-access:R6.4 (actor và biên dữ liệu), R6.7 (một giới hạn mỗi phiên bản đã phát hành, ghi trong giao dịch phát hành); tenant-config:R5.1 (giả lập); ADR-0112 (Accepted) quyết 4-5; ADR-0103 (Accepted) quyết 5 (giới hạn của quy trình dẫn từ các Bước dữ liệu).

## Comments

- 2026-10-23 (agent): theo phiếu 23/10/2026: giả lập ghi bản ghi ở RecordService, không trong Bước (D:custom-objects:R5.4~workflow-nodes:R5.3); `RunControlPort` có thêm lý do chủ thể chạy không `active` (H:org-and-principals:R4.6).
- 2026-10-24 (agent): theo quyết định của Đạt ngày 24/10/2026 (I:record-access:R6.4~workflow-engine:R4.9): ticket chờ record-access/04 (helper `app.actor_kind`, `app.boundary_id` của R4.9) và custom-objects/03 (RecordService giả lập ở `simulate` của R4.7), nên test R4.7 và R4.9 chạy với bản thật.
- 2026-10-24 (agent): lượt b của vòng 4: khóa cache mang mã băm mà lượt chạy ghim, vì từ V4.4 một bản Nháp chạy mô phỏng được mà giữ id khi sửa, nên khóa theo id phiên bản cho lượt mới graph của nội dung cũ (workflow-engine:R3.9, CLAUDE.md, Non-negotiable architecture: lượt chạy chỉ phân giải từ bản kê).
- 2026-10-24 (agent): lượt d của vòng 4: dòng Comments của lượt b thôi dẫn mã mục của lượt; ticket nhận R1.7: bước 5 thêm vào móc phát hành của loại `workflow` lời gọi `ActorBoundaryPort` ghi giới hạn dữ liệu của phiên bản, một dòng mỗi object và mỗi Trường của giới hạn (tiêu chí R1.7 thử hai node trên cùng một object), như record-access đòi (record-access:R6.7) và như móc của loại `agent` (ADR-0117 (Accepted) quyết 3), vì ticket này đã chờ record-access/04, nơi port ra đời; không thêm cạnh.
