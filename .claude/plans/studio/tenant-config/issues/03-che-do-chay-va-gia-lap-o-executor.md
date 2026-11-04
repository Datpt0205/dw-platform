# 03 — Chế độ chạy trên mỗi lượt chạy và executor giả lập ở chế độ Mô phỏng

Status: resolved (2026-11-02, main)
Blocked by: .claude/plans/studio/runtime-hardening/issues/01-toolexecutor-gianh-luot-khong-cua-sau.md
Area: studio
Yêu cầu: R4.1, R4.2, R4.3, R4.4, R4.5, R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, G1, TC9, TC10, TC11

## Mục tiêu

Mỗi lượt chạy mang một chế độ chạy do máy chủ đặt, cột không có giá trị mặc định, và chế độ giữ nguyên
khi tiếp tục; ToolExecutor giả lập mọi lệnh gọi không `simulate_safe` ở `simulate` và `test`, ngay tại
executor chứ không trong node, và trước bước phê duyệt, nên lượt không `live` không mở yêu cầu phê duyệt nào cho
lệnh gọi bị giả lập (spec R4, R5). W1 chỉ mở chạy mô phỏng (`simulate`): route `.../test-runs` của
workflow-triggers từ chối `test` tới W2 (workflow-triggers:R2.6), và nếu một lượt `test` tới executor thì
bị giả lập như `simulate`. Lượt chạy của worker định nghĩa bằng code chạy `live` như hôm nay (G1).

## Việc cần làm

1. `packages/python/dw_kernel/src/dw_kernel/run_mode.py`: `RunMode = Literal["live", "test", "simulate"]`
   và `child_mode(parent, requested) -> RunMode` trả giá trị đứng trước theo thứ tự `simulate`, `test`,
   `live`. Thêm module vào `WATCHED_LITERALS` (`scripts/verify_invariants.py:109-112`); bên đọc trong
   cùng thay đổi: `ToolDefinition.intercepted_in` (bước 5) và chỗ dựng DW (bước 2) đọc `"live"`, mặc định của
   `RunContext` là `"simulate"`; `"test"` không có nhánh riêng ở W1 (bị giả lập qua `run_mode != "live"`, DO-26.1), nên
   nó vào `UNREAD_EXEMPT` (`scripts/verify_invariants.py:122`) với lý do đó và tên bên đọc của W2 (Danh sách người nhận
   thử), không bằng một câu nhắc tới giá trị chỉ để qua phép kiểm.
2. `RunContext.run_mode: RunMode = "simulate"` trong
   `packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py`, cạnh `autonomy_ceiling`
   (`contracts.py:156`) và chú thích như nó: mặc định là giá trị đóng. Chỗ dựng ngữ cảnh cho một lượt chạy
   bắt đầu hay tiếp tục đặt giá trị tường minh (neo kiểm ở `9fbc933`):
    - `resume_context` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py:124`), lối
      tiếp tục duy nhất, mà cả `ApproveAndResumeService` (`approval_flow.py:372`) lẫn lane `dw_timers`
      (`apps/worker/src/dw_worker/consumers/dw_timers.py:84`) gọi, đọc `run_mode` từ dòng lượt chạy:
      `RunRecord.run_mode`, đọc ở chỗ dựng `RunRecord` của store (`run_store.py:515`);
    - `run_context_for` của Digital Worker
      (`packages/python/dw_agent_runtime/src/dw_agent_runtime/digital_worker_context.py:32`), lối mà
      `wflite/starter.py:146` dùng để bắt đầu mọi lượt chạy DW của phiên bản quy trình đã phát hành, đặt `live`
      (ADR-0111 (Accepted) quyết 2: trigger và lượt chạy tay của phiên bản đang dùng là `live`).

    Chỗ dựng ngữ cảnh chỉ để tra cứu hay chỉ để gọi model, không bắt đầu lượt chạy nào, giữ mặc định `simulate`
    và chú thích lý do: `ApiContainer.run_context_for` (`apps/api/src/dw_api/bootstrap/container.py:256`: tra lượt
    chạy, trợ lý và mô phỏng nháp của wf-ai), `_run_context_for` (`approval_flow.py:484`: chỉ đọc dòng lượt chạy),
    `usage_run_context` (`adapters/langchain_usage.py:177`: không có dòng `worker_runs`, không gọi ToolExecutor) và
    ba script (`scripts/eval_leadcare.py:60`, `scripts/eval_wf_ai.py:133`, `scripts/check_model_gateway.py:81`;
    đánh giá là `simulate` theo quyết 2). Test hiện có dựng ngữ cảnh cho lượt chạy thật đặt `live`.

3. Revision Alembic mới (id hex ngẫu nhiên): thêm `platform.worker_runs.run_mode text`, backfill
   `live`, `SET NOT NULL`, `ck_worker_runs_run_mode CHECK (run_mode IN ('live', 'test', 'simulate'))`,
   không DEFAULT. Cập nhật `runtime_tables.py`; `SqlWorkerRunStore.create` (`adapters/run_store.py:204`, câu
   INSERT ở `:422`) ghi `run_context.run_mode`, không thêm tham số nào: dòng, span và audit đọc cùng một giá trị,
   như `create` đã nhận cả `WorkerDefinition` thay vì từng nhãn.
4. Runner (`adapters/langgraph_runner.py:307` `start` và `:358` `stream`) không tự quyết chế độ: dòng lượt
   chạy, thuộc tính `dw.run_mode` của span bắt đầu và tiếp tục, và `details.run_mode` của audit `run.started`
   (`:330`, `:386`) đều đọc `run_context.run_mode`. Lượt chạy của worker định nghĩa bằng code và lượt chạy DW nhận
   `live` từ chỗ dựng ở bước 2 (ADR-0111 (Accepted) quyết 2), nên dòng của chúng mang `live` (R4.3); không nhánh
   nào ghi hằng `live` bất kể ngữ cảnh, vì runner ghi `live` cho ngữ cảnh `simulate` sẽ làm lượt chạy thành `live`
   khi tiếp tục (R4.5 đọc từ dòng), tức nới ra.
5. `ToolDefinition.simulate_safe: bool = False`, và một hàm trả lời "lệnh gọi này có bị giả lập không":
   `ToolDefinition.intercepted_in(run_mode) -> bool`, đúng khi `run_mode` khác `live` và công cụ không
   `simulate_safe`; executor, tool wrapper của agent và middleware phê duyệt ở bước 6 cùng đọc hàm này. Assembler của
   lớp nền tảng (`ToolSpec.to_definition`, `packages/python/dw_agent_runtime/src/dw_agent_runtime/tool_specs.py:107`)
   đặt `True` chỉ cho spec có `side_effect_level` là `none`; loại công cụ của tools-and-skills tự khai sau
   (ADR-0116 (Accepted)). `test_capable` không thêm ở ticket này: bên đọc của nó là chế độ `test` có Danh sách người
   nhận thử, thuộc W2.
6. Bước chế độ trong `ToolExecutor._execute`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:283`), đúng chỗ thứ tự bước của
   tools-and-skills:R2.6 đặt: sau biên DW (2b), lệnh gọi quyết định (2c) và kiểm quyền (3), trước kiểm phê duyệt
   (`executor.py:339`), nên cũng trước yêu cầu khóa chống lặp, trước sàn gửi (4b, `executor.py:366`, nên
   `send_admission.admit` không chạy cho lệnh gọi bị giả lập), trước khi giành lượt (`executor.py:402`) và gọi handler
   (N2, R5.6); tools-and-skills/01, ticket sau, đưa bước này vào sổ guard `build_tool_executor_steps` của
   ToolExecutor (tools-and-skills:R2.6; H-3), nên ticket này đặt nó thẳng vào `_execute`. Khi
   `definition.intercepted_in(run_context.run_mode)`:
    - không gọi handler, không giành lượt, không qua sàn gửi; ghi dòng `platform.tool_executions` với `status`
      `simulated`;
    - audit `tool.simulated` với `details.run_mode` và `details.reason` (`not_simulate_safe`) trong cùng giao dịch
      với dòng đó: `ExecutionStorePort.record` nhận thêm `audit: AuditEvent | None = None`, và
      `SqlToolExecutionStore` (`adapters/tool_execution_store.py:90`) ghi nó bằng `SqlAuditRepository(session).append`
      trong chính phiên ghi dòng, như `adapters/wf_drafts.py:158`; fake của port làm đúng như vậy;
    - trả đầu ra giả lập: `sample_of(tool.output_model.model_json_schema())`, kiểm bằng
      `tool.output_model.model_validate` như đầu ra thật (`executor.py:584`), lỗi kiểm thành `DomainError`
      (`validation_failed`) như đầu ra thật; giá trị trả về là
      `SampleOutput.model_validate({**validated.model_dump(mode="json"), "simulated": True})` và cột `output` của dòng
      giữ đúng payload đó, `output_hash` băm trên nó. `sample_of` và model `extra="allow"` của nó (`_Sample`, đổi tên
      `SampleOutput`) chuyển từ `wflite/simulate.py:53-108` sang module mới
      `packages/python/dw_agent_runtime/src/dw_agent_runtime/samples.py`, và `wflite/simulate.py` nhập từ đó: một hàm
      sinh mẫu cho cả hai, còn executor không nhập được `wflite` vì `wflite/simulate.py` nhập executor. Executor không
      đọc kết quả giả lập ghim nào: ở W1 wrapper nút của workflow-engine/03 áp kết quả ghim ở mức Bước, sau khi kiểm
      với schema đầu ra của Bước, và không gọi ToolExecutor cho Bước đó (workflow-engine:R4.27; V4.37, H-18); kết quả
      ghim qua route `.../test-runs` là W2 của workflow-triggers.
    - không mở yêu cầu phê duyệt nào, kể cả với công cụ `critical`: bước phê duyệt chỉ chạy cho lệnh gọi đi qua
      bước chế độ, tức công cụ `simulate_safe` ở chế độ khác `live` và mọi công cụ ở `live`. Tool wrapper của agent
      hỏi người trước khi gọi executor (`adapters/langchain_tools.py:494`), và lần ngắt của nó mở yêu cầu phê duyệt
      qua runner (`adapters/langgraph_runner.py:774`), nên wrapper và `OneApprovalPerStepMiddleware`
      (`adapters/langchain_tools.py:272`) chỉ coi một lệnh gọi là cần duyệt khi `approval_policy.decide(...)` đúng và
      `definition.intercepted_in(run_context.run_mode)` sai (failure-modes #5).

    Mô phỏng nháp của wf-ai (`wflite/simulate.py`) không phải một chế độ chạy và không đổi hành vi: nó không có dòng
    `worker_runs`, không gọi ToolExecutor và trả mẫu cho mọi công cụ; chung với ticket này chỉ có `sample_of`.

7. Revision Alembic mới: thay `ck_tool_executions_status`, nay là tập của `f051d26f0610_tool_executions_refused.py:31`
   (runtime-hardening:R6.3 cộng `refused` của digital-worker/02), bằng tập đó cộng `simulated`, tức
   `CHECK (status IN ('succeeded', 'failed', 'dispatched', 'outcome_unknown', 'refused', 'simulated'))`, giữ
   `dispatched` và `outcome_unknown` mà nhật ký lần gửi ghi (V4.30) và `refused` mà biên DW ghi
   (`executor.py:818`); `ck_tool_executions_refused_unkeyed` và `ck_tool_executions_dispatch_id` giữ nguyên;
   downgrade xóa dòng `simulated` rồi trả tập cũ, như `f051d26f0610` làm với `refused`; migration dừng với lỗi nếu
   có dòng mang giá trị ngoài tập mới. Index chống lặp `uq_tool_executions_idempotency` giữ điều kiện `succeeded`.
8. Test gọi thẳng executor, không qua graph node (failure-modes #5); test riêng cho tool wrapper của agent ở
   `simulate` (một quy tắc giữ ở hai tầng cần một test mỗi tầng, failure-modes #3); và test tiếp tục sau duyệt ở
   một runner khác với runner đã bắt đầu lượt chạy.

## Tiêu chí chấp nhận

- [x] R4.1 (TC9): INSERT `platform.worker_runs` thiếu `run_mode` → lỗi NOT NULL; `run_mode = 'dry'` →
      CHECK từ chối; sau migration mọi dòng cũ là `live`.
- [x] R4.2 (TC9): `RunContext` dựng không nêu chế độ mang `simulate`, và lệnh gọi công cụ `external` của
      nó bị giả lập; đổi giá trị mặc định thành `live` → test đỏ.
- [x] R4.3: lượt chạy mới của worker định nghĩa bằng code có `run_mode = 'live'` trên dòng, `dw.run_mode`
      trên span và `details.run_mode` trong audit `run.started`; runner nhận ngữ cảnh `simulate` → dòng, span và
      audit đều `simulate`; thay `run_context.run_mode` bằng hằng `live` trong runner hay store → test đỏ.
- [x] R4.3: lượt chạy DW bắt đầu qua `wflite/starter.py` có `run_mode = 'live'` trên dòng và công cụ của nó
      thực thi, ghi `succeeded`; bỏ `run_mode="live"` khỏi `run_context_for` của `digital_worker_context.py` → test đỏ.
- [x] R4.4 (TC9): `child_mode` đúng cho cả 9 cặp; cha `simulate` xin con `live` → `simulate`.
- [x] R4.5 (TC10): lượt `simulate` chờ duyệt một công cụ `simulate_safe` có chính sách duyệt luôn hỏi, rồi tiếp
      tục ở runner khác → công cụ `external` gọi sau đó vẫn bị giả lập; lượt `live` → công cụ thực thi; bỏ
      `run_mode` khỏi `resume_context` (`adapters/run_store.py:124`) → test đỏ.
- [x] R5.1 (TC11): gọi thẳng ToolExecutor với công cụ `external` ở `simulate` và ở `test` → handler (spy)
      không chạy, dòng có `status` `simulated`; gỡ bước chế độ → test đỏ.
- [x] R5.1 (TC11): sau revision của bước 7, INSERT dòng `simulated`, `dispatched`, `outcome_unknown` và `refused`
      (không khóa) → nhận; `bogus` → CHECK từ chối; tập mới thiếu `dispatched`, `outcome_unknown` hay `refused` → ca
      nhận đỏ.
- [x] R5.2 (TC11): audit `tool.simulated` có `details.run_mode` và `details.reason`; trên PostgreSQL thật, lần ghi
      audit trong `record` thất bại thì dòng `simulated` cũng không còn; ghi audit bằng `_audit` ở giao dịch riêng như
      hôm nay → test đỏ.
- [x] R5.3 (TC11): đầu ra giả lập là `sample_of` của output schema của công cụ (một hàm ở `samples.py`, mà
      `wflite/simulate.py` cũng nhập), qua `tool.output_model.model_validate`, và cả giá trị trả về lẫn cột `output`
      mang `simulated: true`; làm hỏng bộ sinh để trả giá trị sai schema → `validation_failed` như đầu ra thật; test
      của wf-ai cho `simulate` xanh không sửa.
- [x] R5.4: công cụ `simulate_safe` ở `simulate` chạy handler và ghi `succeeded`.
- [x] R5.5 (TC11): `ToolDefinition` không nêu `simulate_safe` → bị giả lập ở `simulate`.
- [x] R5.6 (TC11): công cụ `critical` không `simulate_safe` có chính sách duyệt luôn hỏi, gọi thẳng ToolExecutor
      ở `simulate` → `status` `simulated`, không dòng `platform.approval_requests` nào; cùng lệnh gọi ở `live` →
      `approval_required`; đặt bước chế độ sau bước phê duyệt → ca `simulate` trả `approval_required`, test đỏ.
- [x] R5.6 (TC11): cùng công cụ gọi qua tool wrapper của agent (`_build_tool` ở `adapters/langchain_tools.py:482`)
      ở `simulate` → không ngắt, không dòng `platform.approval_requests` nào, dòng `simulated`; bỏ điều kiện
      `intercepted_in` khỏi wrapper → test đỏ.
- [x] G1: `test_happy_path_returns_typed_output_and_audits` xanh với `run_mode = 'live'`; mọi test
      executor hiện có xanh.
- [x] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:156`; spec: R4.2.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py:124`; spec: R4.5, TC10.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/digital_worker_context.py:32`; spec: R4.3, G1; ADR-0111 (Accepted)
  quyết 2.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:283`; spec: R5, TC11.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_tools.py:494`; spec: R5.6; ADR-0111 (Accepted)
  quyết 5.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/simulate.py:53`; spec: R5.3; ADR-0111 (Accepted) quyết 3.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:307`; spec: R4.3.
- `db/migrations/sql/0001_platform_baseline.sql:423`; spec: R5.1; ADR-0111 (Accepted) quyết 1-3.
- `db/migrations/versions/f051d26f0610_tool_executions_refused.py:31`; spec: Dữ liệu.
- `.claude/plans/studio/runtime-hardening/spec.md` R6.3 (tập của `ck_tool_executions_status`); spec: Dữ liệu.

## Comments

- 2026-10-23 (agent): gộp từ B6 tenant-config 04 và 06. Ở W1 executor giả lập `test` như `simulate`
  (DO-26, tạm theo khuyến nghị a); egress client từ chối `simulate` là lớp thứ hai của
  connections-and-vault/03, ticket đó chờ ticket này.
- 2026-10-23 (agent): DO-26.1 (A) và DO-26.2 (a) đã có lời đáp (Đạt 23/10/2026): route chạy thử là của
  workflow-triggers và trả 422 với `test` tới W2; egress client từ chối mọi chế độ khác `live`. Kết quả giả
  lập ghim theo Bước dời sang W2 của workflow-nodes, nên ticket này chỉ sinh đầu ra từ output schema.
- 2026-10-24 (agent): theo quyết định N2 của Đạt ngày 24/10/2026: ở chế độ khác `live` bước chế độ đứng trước bước
  phê duyệt (R5.6, thứ tự của tools-and-skills:R2.6), nên lệnh gọi bị giả lập không mở yêu cầu phê duyệt; egress
  ở chế độ khác `live` theo ADR-0115 (Accepted) quyết 6 (chừa `model` và Hành động chỉ đọc).
- 2026-10-25 (agent): lượt h, theo V4.37, H-18 và V4.30 (quyết định cùng ngày của spec): kết quả giả lập ghim theo Bước
  vào W1 nhưng thuộc wrapper nút của workflow-engine/03, không thuộc executor, nên bước 6 chỉ dẫn chiếu và R5.3 không
  đổi; câu Comments ngày 23/10/2026 "Kết quả giả lập ghim theo Bước dời sang W2 của workflow-nodes" không còn áp. Bước 7
  nêu tập đủ của CHECK, giữ `dispatched` và `outcome_unknown` của runtime-hardening:R6.3; bước 6 ghi rằng
  tools-and-skills/01 đưa bước chế độ vào sổ guard (H-3). Dòng Blocked by không đổi.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH B1: bước 7 chép tập bốn giá trị của runtime-hardening:R6.3,
  trong khi `f051d26f0610` (digital-worker/02) đã thêm `refused` mà biên DW ghi (`executor.py:818`); revision như viết
  sẽ dừng trên dòng `refused` có sẵn, hay làm mọi lần từ chối ở biên DW lỗi CHECK (failure-modes #2). Sửa: bước 7 lấy
  tập hiện có cộng `simulated`, giữ `ck_tool_executions_refused_unkeyed`, tiêu chí CHECK có `refused`; spec: Dữ liệu,
  TC11 và một dòng Quyết định. Nếu sai thì: digital-worker/02 gỡ `refused` trước, và bước 7 trở lại tập bốn giá trị cộng
  `simulated`.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH B2: R5.2 đòi dòng và audit trong một giao dịch, còn hôm nay
  `SqlToolExecutionStore.record` và `ToolExecutor._audit` mở hai giao dịch riêng; người dựng phải tự chế cách. Sửa: bước
  6 cho `ExecutionStorePort.record` tham số `audit`, ghi bằng `SqlAuditRepository(session).append` trong phiên ghi dòng
  như `adapters/wf_drafts.py:158`; tiêu chí R5.2 thành ca PostgreSQL thật đỏ khi audit ghi riêng. Nếu sai thì: một
  method `record_simulated` riêng trên port, cùng một giao dịch.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH B3: "bốn chỗ dựng" đã trôi: lối tiếp tục nay là
  `resume_context` (`adapters/run_store.py:124`, cho cả lần duyệt lẫn lane `dw_timers`), và
  `digital_worker_context.run_context_for`, lối duy nhất mà production bắt đầu lượt chạy hôm nay (`wflite/starter.py:146`),
  không có trong danh sách, nên mọi lượt chạy DW sẽ mang mặc định `simulate` và không còn gửi gì. Sửa: bước 2 nêu từng
  chỗ và giá trị của nó (DW `live` theo ADR-0111 (Accepted) quyết 2; chỗ tra cứu, chỗ chỉ gọi model và script eval giữ
  mặc định, có lý do), thêm tiêu chí R4.3/G1 cho lượt chạy DW, tiêu chí R4.5 trỏ `resume_context`. Nếu sai thì: lượt chạy
  DW là lượt chạy Studio phải qua cửa yêu cầu lượt chạy của workflow-engine (ADR-0113 (Accepted)), và chỗ dựng của nó đọc chế độ từ
  đó thay vì đặt `live`.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH B4: bước 4 "runner ghi `live`" và bước 3 "`create` nhận
  `run_mode` bắt buộc" để ngỏ việc dòng có thể nói `live` khi ngữ cảnh nói `simulate`; R4.5 đọc chế độ từ dòng, nên
  lượt chạy nới thành `live` khi tiếp tục, trái ADR-0111 (Accepted) quyết 2 ("only gets safer"). Sửa: runner và store đọc
  `run_context.run_mode` cho dòng, span và audit, không tham số thứ hai, không hằng `live`; tiêu chí R4.3 có ca
  `simulate` và đỏ khi thay bằng hằng. Nếu sai thì: `create` nhận `run_mode` riêng và một assert ở runner đòi nó bằng
  `run_context.run_mode`.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH B5: "giá trị nhỏ nhất sinh từ output schema ... thêm
  `simulated: true`" là bộ sinh mẫu thứ hai bên cạnh `sample_of` của wf-ai/02 (`wflite/simulate.py:53`; failure-modes
  #2), và không nói `simulated: true` nằm đâu khi output model của mỗi công cụ là class Pydantic bỏ khóa lạ. Sửa: bước
  6 chuyển `sample_of` và `_Sample` (thành `SampleOutput`, `extra="allow"`) sang `dw_agent_runtime/samples.py`, cho
  executor và wf-ai cùng dùng, kiểm bằng `tool.output_model`, trả `SampleOutput` mang `simulated: true` và lưu đúng
  payload đó; mô phỏng nháp của wf-ai giữ nguyên, vì nó không phải chế độ chạy (không dòng `worker_runs`, không gọi
  ToolExecutor). Nếu sai thì: executor trả đúng class output của công cụ và `simulated: true` chỉ ở cột `output` và audit.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH S1 (đi qua biên phê duyệt): tool wrapper của agent hỏi
  `approval_policy.decide` trước khi gọi executor (`adapters/langchain_tools.py:494`) và lần ngắt mở yêu cầu phê duyệt
  qua runner, nên một agent ở `simulate` gọi công cụ `critical` vẫn mở yêu cầu phê duyệt dù executor sẽ giả lập nó,
  trái R5.6 và ADR-0111 (Accepted) quyết 5 (failure-modes #5). Sửa: bước 5 thêm `ToolDefinition.intercepted_in`, bước 6
  cho wrapper và `OneApprovalPerStepMiddleware` đọc nó, bước 8 và một tiêu chí R5.6 thêm test tầng wrapper; spec: TC11 và
  một dòng Quyết định. Nếu sai thì: `AutonomyApprovalPolicy.decide` trả sai cho lệnh gọi bị giả lập, và phép đảo bước của
  TC11 (và tools-and-skills:TS10) đổi thành phép gỡ mệnh đề đó.
- 2026-11-02 (agent): ghi chú MEDIUM của gate cho người dựng, chưa sửa: (M1) neo đã trôi chưa sửa: `WATCHED_LITERALS`
  nay ở `scripts/verify_invariants.py:117-120` (bước 1); Hiện trạng của spec giữ neo của `ab33703` (`executor.py:135`,
  `contracts.py:98`, `:141`, `approval_flow.py:269`, `:382`, `container.py:211`); tìm theo tên. (M2) `child_mode` chưa có
  bên đọc production nào ở ticket này, chỉ test (failure-modes #1); bên đọc đầu tiên là lượt con của workflow-engine, nêu
  tên ticket đó khi viết. (M3) chưa có test rằng `send_admission.admit` không chạy cho một công cụ `message` bị giả lập;
  vị trí của bước chế độ đảm bảo điều đó, nhưng cần ca đỏ khi dời bước chế độ xuống dưới sàn gửi. (M4) metric
  `DW_TOOL_CALL_TOTAL` sẽ đếm lệnh gọi bị giả lập là `ok`; ADR-0111 (Accepted) quyết 5 bỏ lượt không `live` khỏi số liệu nghiệp vụ,
  nên nhãn `simulated` là cách rẻ nhất. (M5) ca R4.5 là đường đầu tiên một lượt `simulate` mở yêu cầu phê duyệt thật
  (công cụ `simulate_safe` luôn hỏi); ADR-0111 (Accepted) quyết 5 đòi yêu cầu đó chỉ tới người chạy thử, trong ứng dụng, không qua
  kênh chat, và chưa ticket nào nói ai định tuyến nó. (M6) LangGraph chạy lại node sau checkpoint khi tiếp tục, nên lệnh
  gọi bị giả lập có khóa sẽ ghi thêm dòng `simulated` và audit `tool.simulated` mỗi lần chạy lại; vô hại cho tác động,
  nhưng vết đếm đôi. (M7) biên DW (2b) và lệnh gọi quyết định (2c) đứng trước bước chế độ, nên ở `simulate` một quyết
  định cần người bị từ chối `approval_missing` (quyết định giả lập không thỏa phê duyệt thật, ADR-0111 (Accepted) quyết 5): đúng
  hướng đóng, nhưng không ai được dời bước chế độ lên trên chúng. (M8) "mô phỏng" của wf-ai (trả mẫu cho mọi công cụ) và
  chế độ `simulate` (chạy thật công cụ `simulate_safe`) là hai nghĩa của một từ; `CONTEXT.md` nên tách tên. LOW: dòng
  Quyết định 2/11/2026 về `workflow_sha256` của spec có một dòng lặp (bắt đầu bằng "vào vỏ"); bước 3 và bước 7 có thể
  là một revision.
- 2026-11-02 (agent): lượt xác nhận của gate, chỉ đọc sáu chỗ sửa B1-B5 và S1: không CRITICAL mới; B1-B5 và S1 đóng
  (bước 2-8, tiêu chí, Nguồn, Dữ liệu và TC11 của spec cùng nói một điều). Một hệ quả của B4 và S1 sửa ngay: bước 1
  từng nói "runner ghi `live`" và "executor đọc `test`", nay sai, nên bước 1 nêu bên đọc thật và đưa `RunMode:test`
  vào `UNREAD_EXEMPT` có lý do (W1 giả lập `test` qua `run_mode != "live"`), thay vì để `verify_invariants.py` đỏ và
  người dựng thêm một câu nhắc giá trị chỉ để qua phép kiểm (agent, theo ủy quyền 31/10/2026; Nếu sai thì: executor
  so khớp tường minh `("simulate", "test")` và không cần dòng miễn).
- 2026-11-02 (agent): ticket này thêm hai revision Alembic (cột `worker_runs.run_mode`, CHECK của
  `tool_executions.status`) và đổi đường ghi của executor ở chế độ khác `live` (dòng và audit trong một giao dịch),
  nên thuộc diện đo độ trễ của `latency.md` ("When"); theo lệ từ 2/11/2026, đo một lần sau khi hết ticket của đợt.
- 2026-11-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-02 (agent): resolved.
    - Khác ticket (agent, theo ủy quyền 31/10/2026): bước 3 và 7 là một revision (`c478ca7b6ed1`, LOW của gate). `dw.run_mode` vào danh sách thuộc tính được phép của `dw_observability.semconv` và ảnh chụp `genai-semconv@e19717d65f89.json` (một giá trị trong tập ba, là định danh), nếu không test "chỉ định danh" của span từ chối nó. Chín fixture test chèn `platform.worker_runs` bằng SQL thô nay nêu `run_mode = 'live'`: cột NOT NULL không DEFAULT làm đúng việc của nó. Test dựng ngữ cảnh cho lượt chạy thật đặt `live` (chín bộ dựng). Nếu sai thì: tách revision theo bước.
    - R4.5 đo trên graph demo (không công cụ) qua hai runner thật: `resume_context` đọc `simulate` từ dòng và lượt tiếp tục ở runner khác nhận `simulate`; việc executor đọc chế độ của ngữ cảnh có test riêng ở unit. Ca CHECK của R5.1 ghi được `simulated`, `refused`, `outcome_unknown`, từ chối `bogus`, và đọc định nghĩa CHECK cho đủ sáu giá trị (`dispatched` cần `dispatch_id`, đã có ở test của runtime-hardening).
    - Test: unit `test_run_mode.py` 17 ca (mặc định đóng, 9 cặp `child_mode`, giả lập ở `simulate` và `test`, `live` chạy thật, mẫu sai schema là `validation_failed`, `simulate_safe` chạy, công cụ `critical` không mở phê duyệt ngoài `live`), `test_agent_factory.py` thêm ca wrapper ở `simulate`, `test_tool_specs.py` thêm ca assembler; integration `test_run_mode_db.py` 6 ca (NOT NULL, CHECK, không DEFAULT; runner ghi chế độ của ngữ cảnh lên dòng và audit; tiếp tục ở runner khác vẫn `simulate`; tập trạng thái; audit cùng giao dịch với dòng, lỗi audit thì không còn dòng), `test_wflite_runs_db.py` khẳng định lượt DW mang `live`. Integration của runtime, worker và các tệp có fixture sửa: xanh.
    - `mutations/03.yaml` 10 đột biến, chưa chạy. Độ trễ (cột mới trên INSERT lượt chạy, đọc khi tiếp tục) đo ở lượt cuối.
    - MEDIUM chưa làm, cho ticket sau: M3 (test sàn gửi không chạy cho công cụ tin nhắn bị giả lập; theo thứ tự bước nó đứng sau bước chế độ), M4 (metric gọi công cụ đếm `simulated` là `ok`), M5, M6 (dòng `simulated` lặp khi graph phát lại nút lúc tiếp tục), M8 (hai nghĩa của "mô phỏng" trong `CONTEXT.md`).
    - `reviewing-feature-security` (đọc): chế độ đặt phía server, mặc định đóng, đọc lại từ dòng khi tiếp tục, không bao giờ nới (`child_mode`); bước chế độ ở executor sau biên DW, lệnh gọi quyết định và kiểm quyền, trước phê duyệt, khóa, sàn gửi, giành lượt và handler; wrapper và middleware của agent đọc cùng hàm `intercepted_in`; dòng `simulated` và audit cùng giao dịch.
