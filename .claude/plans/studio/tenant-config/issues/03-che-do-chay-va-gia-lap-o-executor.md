# 03 — Chế độ chạy trên mỗi lượt chạy và executor giả lập ở chế độ Mô phỏng

Status: needs-triage
Blocked by: .claude/plans/studio/foundations-hardening/issues/04-toolexecutor-gianh-luot-khong-cua-sau.md
Area: studio
Yêu cầu: R4.1, R4.2, R4.3, R4.4, R4.5, R5.1, R5.2, R5.3, R5.4, R5.5, G1, TC9, TC10, TC11

## Mục tiêu

Mỗi lượt chạy mang một chế độ chạy do máy chủ đặt, cột không có giá trị mặc định, và chế độ giữ nguyên
khi tiếp tục; ToolExecutor giả lập mọi lệnh gọi không `simulate_safe` ở `simulate` và `test`, ngay tại
executor chứ không trong node (spec R4, R5). W1 chỉ mở `simulate` cho chạy thử: route chạy thử của
workflow-triggers từ chối `test` tới W2 (workflow-triggers:R2.6), và nếu một lượt `test` tới executor thì
bị giả lập như `simulate`. Lượt chạy của worker định nghĩa bằng code chạy `live` như hôm nay (G1).

## Việc cần làm

1. `packages/python/dw_kernel/src/dw_kernel/run_mode.py`: `RunMode = Literal["live", "test", "simulate"]`
   và `child_mode(parent, requested) -> RunMode` trả giá trị đứng trước theo thứ tự `simulate`, `test`,
   `live`. Thêm module vào `WATCHED_LITERALS` (`scripts/verify_invariants.py:109-112`); bên đọc trong
   cùng thay đổi: executor đọc `simulate` và `test`, runner ghi `live`.
2. `RunContext.run_mode: RunMode = "simulate"` trong
   `packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py`, chú thích như
   `autonomy_ceiling`: mặc định là giá trị đóng. Bốn chỗ dựng đặt giá trị tường minh:
   `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:269` và
   `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:382` đọc `run_mode` từ dòng
   lượt chạy; `apps/api/src/dw_api/bootstrap/container.py:211` và
   `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_usage.py:188` nhận từ bên
   gọi. Test hiện có dựng ngữ cảnh cho lượt chạy thật đặt `live`.
3. Revision Alembic mới (id hex ngẫu nhiên): thêm `platform.worker_runs.run_mode text`, backfill
   `live`, `SET NOT NULL`, `ck_worker_runs_run_mode CHECK (run_mode IN ('live', 'test', 'simulate'))`,
   không DEFAULT. Cập nhật `runtime_tables.py`; `SqlWorkerRunStore.create` nhận `run_mode` bắt buộc,
   không giá trị mặc định ở tham số.
4. Runner: mọi lần bắt đầu hiện có của worker định nghĩa bằng code ghi `live` (ADR-0111 (Accepted) quyết
   2); thêm thuộc tính `dw.run_mode` vào span bắt đầu và tiếp tục; thêm `details.run_mode` vào audit
   `run.started`.
5. `ToolDefinition.simulate_safe: bool = False`. Assembler của lớp nền tảng đặt `True` chỉ cho spec có
   `side_effect_level` là `none`; loại công cụ của tools-and-skills tự khai sau (ADR-0116 (Accepted)).
   `test_capable` không thêm ở ticket này: bên đọc của nó là chế độ `test` có Danh sách người nhận thử,
   thuộc W2.
6. Bước chế độ trong `ToolExecutor._execute`, sau kiểm quyền và phê duyệt, trước khi giành lượt và gọi
   handler. Khi `run_mode` là `simulate` hay `test` và công cụ không `simulate_safe`:
    - không gọi handler, không giành lượt; ghi dòng `platform.tool_executions` với `status` `simulated`;
    - audit `tool.simulated` với `details.run_mode` và `details.reason` (`not_simulate_safe`) trong cùng
      giao dịch với dòng đó;
    - trả đầu ra giả lập: giá trị nhỏ nhất sinh từ output schema, kiểm theo output schema như đầu ra thật,
      thêm `simulated: true`. Kết quả giả lập ghim theo Bước là W2 của workflow-nodes, không làm ở ticket
      này.
    - phê duyệt của công cụ `critical` vẫn hỏi người như cũ; chỉ hiệu ứng bị giả lập.
7. Revision Alembic mới: thay `ck_tool_executions_status` (foundations-hardening/04 tạo) bằng cùng tập
   giá trị cộng `simulated`; migration dừng với lỗi nếu có dòng mang giá trị ngoài tập mới. Index chống
   lặp giữ điều kiện `succeeded`.
8. Test gọi thẳng executor, không qua graph node (failure-modes #5), và test tiếp tục sau duyệt ở một
   runner khác với runner đã bắt đầu lượt chạy.

## Tiêu chí chấp nhận

- [ ] R4.1 (TC9): INSERT `platform.worker_runs` thiếu `run_mode` → lỗi NOT NULL; `run_mode = 'dry'` →
      CHECK từ chối; sau migration mọi dòng cũ là `live`.
- [ ] R4.2 (TC9): `RunContext` dựng không nêu chế độ mang `simulate`, và lệnh gọi công cụ `external` của
      nó bị giả lập; đổi giá trị mặc định thành `live` → test đỏ.
- [ ] R4.3: lượt chạy mới của worker định nghĩa bằng code có `run_mode = 'live'` trên dòng, `dw.run_mode`
      trên span và `details.run_mode` trong audit `run.started`.
- [ ] R4.4 (TC9): `child_mode` đúng cho cả 9 cặp; cha `simulate` xin con `live` → `simulate`.
- [ ] R4.5 (TC10): lượt `simulate` chờ duyệt rồi tiếp tục ở runner khác → công cụ vẫn bị giả lập; lượt
      `live` → công cụ thực thi; bỏ `run_mode` khỏi chỗ dựng lại ngữ cảnh ở `approval_flow.py` → test đỏ.
- [ ] R5.1 (TC11): gọi thẳng ToolExecutor với công cụ `external` ở `simulate` và ở `test` → handler (spy)
      không chạy, dòng có `status` `simulated`; gỡ bước chế độ → test đỏ.
- [ ] R5.2 (TC11): audit `tool.simulated` có `details.run_mode` và `details.reason`; rollback giao dịch
      thì cả dòng lệnh gọi lẫn audit đều không còn.
- [ ] R5.3 (TC11): đầu ra giả lập sinh từ output schema, qua kiểm output schema và mang `simulated: true`;
      làm hỏng bộ sinh để trả giá trị sai schema → `validation_failed` như đầu ra thật.
- [ ] R5.4: công cụ `simulate_safe` ở `simulate` chạy handler và ghi `succeeded`.
- [ ] R5.5 (TC11): `ToolDefinition` không nêu `simulate_safe` → bị giả lập ở `simulate`.
- [ ] G1: `test_happy_path_returns_typed_output_and_audits` xanh với `run_mode = 'live'`; mọi test
      executor hiện có xanh.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:141`; spec: R4.2.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:269`; spec: R4.5, TC10.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:135`; spec: R5, TC11.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:283`; spec: R4.3.
- `db/migrations/sql/0001_platform_baseline.sql:423`; spec: R5.1; ADR-0111 (Accepted) quyết 1-3.

## Comments

- 2026-10-23 (agent): gộp từ B6 tenant-config 04 và 06. Ở W1 executor giả lập `test` như `simulate`
  (DO-26, tạm theo khuyến nghị a); egress client từ chối `simulate` là lớp thứ hai của
  connections-and-vault/03, ticket đó chờ ticket này.
- 2026-10-23 (agent): DO-26.1 (A) và DO-26.2 (a) đã có lời đáp (Đạt 23/10/2026): route chạy thử là của
  workflow-triggers và trả 422 với `test` tới W2; egress client từ chối mọi chế độ khác `live`. Kết quả giả
  lập ghim theo Bước dời sang W2 của workflow-nodes, nên ticket này chỉ sinh đầu ra từ output schema.
