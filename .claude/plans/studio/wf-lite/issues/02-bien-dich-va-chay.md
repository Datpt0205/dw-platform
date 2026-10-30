# 02 — Biên dịch sang StateGraph, chạy trên runner hiện có, chờ duyệt, hẹn giờ và chạy tiếp

Status: resolved
Blocked by: 01
Area: studio
Yêu cầu: R5.1, R5.2, R5.3, R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7, R6.8, R6.9, R6.10, R6.12, R6.13, R6.14, R6.15, R6.16, R6.17, R6.18, R6.19, R6.20, R6.21, G1, WFL9, WFL10, WFL11, WFL12, WFL13, WFL14, WFL15, WFL16, WFL17, WFL18, WFL21, WFL22, WFL23, WFL25, WFL26

## Mục tiêu

Mỗi tài liệu của gói biên dịch thành một StateGraph trên `LangGraphWorkflowRunner`; lane `dw_work`
chạy việc của DW qua nó; bước AI có đầu ra cấu trúc và bàn giao khi không chắc; cổng duyệt dừng lượt
chạy và chạy tiếp sau quyết định; `ToolExecutor` chỉ chạy hiệu ứng đòi người với đúng bản đã duyệt;
hẹn giờ dừng không mở approval; không hiệu ứng nào lặp lại khi chạy tiếp (R5, R6, G1).

## Việc cần làm

1. `dw_agent_runtime/wflite/compile.py`: `compile_workflow(doc, ports) -> StateGraph` theo R6.1; trạng
   thái có `work` (payload), `params`, `dw_id`, `work_item_id`, `out__<id>` mỗi bước, `trail` (reducer
   nối danh sách), `handed_off`; mỗi chờ là `interrupt()` dòng đầu nút; mỗi nút bọc trong một wrapper
   bắt lỗi của bước (R6.18); đăng ký mỗi tài liệu của `PackCatalog` vào `GraphRegistry` với `worker_id`
   `dw:<key>`, `graph_version` = `version`, và một `WorkerDefinition` sinh từ tài liệu (prompt bundle,
   toolset, policy theo phiên bản tài liệu).
2. Nút: `ai.llm@1` theo R5 (gateway, `PromptRegistry`, kiểm `output_schema` bằng `jsonschema`, bàn giao
   khi sai hay dưới `min_confidence` cho Validator); `tool.call@1` qua `ToolExecutor` với khóa
   `wf:<run_id>:<step_id>:`, đặt mức tự chủ của lời gọi là mức hiệu lực của `decision_class` của bước và
   mang id approval của cổng gác nó (R6.17), từ chối của executor thành bàn giao (R6.16);
   `human.approval@1` hỏi `DecisionGate`, `auto` thì lane `approved`, không thì interrupt với payload
   của cổng và đi lane theo quyết định khi chạy tiếp, đầu ra `proposal` là `edited_proposal` khi có
   (R6.10); `time.wait@1` interrupt `{wait: "timer", wake_at}`; `logic.switch@1` cạnh có điều kiện so bằng.
3. `ToolExecutor`: khi chính sách tự chủ đòi người cho lời gọi, chỉ nhận lời gọi mang id một approval
   `dw.decision` đã duyệt của cùng lượt chạy và bước cổng mà băm của bản đã duyệt (`edited_payload` hay
   `proposal`) bằng băm của `input`; không thì `approval_missing` (R6.17).
4. `LangGraphWorkflowRunner._handle_outcome`: interrupt có `wait: "timer"` → không approval, gọi
   `WaitRecorderPort.record_timer(run_context, run_id, wake_at)` (cấp bởi `WorkQueue`: việc
   `waiting_timer` với `wake_at`); approval → việc `waiting_approval`; mọi interrupt khác giữ như cũ (G1).
5. `DigitalWorkerRunStarter` thật cho lane `dw_work` (digital-worker/02): kiểm `parameters` theo
   `variables[]` và loại quyết định trên DW (R6.2), loại trên DW không nới loại của tài liệu (R6.9),
   ghi `release_manifest_ref` `pack:<key>@<version>#<sha256>` (R6.14), dựng `RunContext` bằng
   `run_context_for`, gọi `runner.start`; kết thúc `completed` → việc `done`, `failed` → việc `failed`
   (R6.7); mỗi lần chạy tiếp so sha256 (R6.14).
6. Migration: hàm `platform.dw_timer_scopes_due(limit)` SECURITY DEFINER trả id tenant. Lane `dw_timers` ở
   `apps/worker/src/dw_worker/consumers/dw_timers.py`: theo từng tenant dưới `app.tenant_id`, nhận việc
   `waiting_timer` có `wake_at <= now()` của DW `operating` bằng `FOR UPDATE SKIP LOCKED`, dời `wake_at`
   thêm 5 phút trong giao dịch nhận (thuê), rồi gọi `runner.resume`; lượt chạy tiếp chuyển việc sang
   `in_progress` (R6.12, R6.15).
7. Approval `dw.decision` được quyết thì `ApproveAndResumeService` chạy tiếp như hôm nay; việc trở lại
   `in_progress` khi chạy tiếp.
8. `GET /v1/work-items/{id}` trả `trail` đọc từ trạng thái lượt chạy (checkpoint khi đang chạy,
   `worker_runs.result` khi đã kết thúc) dưới ngữ cảnh của người gọi, chỉ `{step_id, type, status, at}`.
9. Mọi `ainvoke` và `astream` của graph wf-lite truyền `durability="sync"` và `recursion_limit` (R6.8).
10. Test integration với PostgreSQL thật và model giả: lượt đi hết, lượt dừng ở duyệt rồi chạy tiếp,
    lượt hẹn giờ, lượt bàn giao; test âm WFL9-WFL18, WFL21-WFL23; WFL16 dừng tiến trình giữa bước gửi
    và bước sau rồi chạy tiếp.

## Tiêu chí chấp nhận

- [x] R5.1: bước `ai.llm` gọi gateway với prompt `id@version`, biến bọc `<input>`, đầu ra trong `out__<id>`.
- [x] R5.2 (WFL9): model giả trả JSON thiếu trường → việc `handed_off` với `problem` nêu `model_output_invalid`, bước sau không trong `trail`.
- [x] R5.3 (WFL10): `confidence` 0,4 với ngưỡng 0,7 → `handed_off` cho Validator, công cụ gửi không được gọi.
- [x] R6.1: tài liệu mẫu biên dịch, đăng ký `dw:<key>@<version>`, `runner.hosts` đúng.
- [x] R6.2 (WFL11): DW thiếu loại `email.send` → việc `failed` `decision_class_missing`, `trail` rỗng; tham số sai kiểu → `parameter_invalid`.
- [x] R6.9 (WFL17): DW khai `email.send` là `none`, và `reversible: true` trái tài liệu → việc `failed` `decision_class_mismatch`, `trail` rỗng.
- [x] R6.3 (WFL12): mức A2 cho loại `external` → lượt chạy `waiting_approval`, việc `waiting_approval`, công cụ chưa gọi; duyệt → chạy tiếp lane `approved`; từ chối → lane `rejected`.
- [x] R6.4: bước `tool.call` gọi `ToolExecutor` với khóa `wf:<run_id>:<step_id>:`.
- [x] R6.17 (WFL13): gọi `email.send` không id approval, với approval của lượt khác, hay với băm khác → `approval_missing`, công cụ không chạy; approval đã duyệt khớp băm → chạy một lần.
- [x] R6.5 (WFL14): `time.wait` → không dòng approval, việc `waiting_timer` với `wake_at`.
- [x] R6.12 (WFL14): hai lane `dw_timers` song song trên một việc quá hạn → một lần chạy tiếp; việc chưa tới hạn không được chạy tiếp; tiến trình chết sau khi nhận → việc được nhận lại sau 5 phút.
- [x] R6.13 (WFL15): `GET /v1/work-items/{id}` trả `trail` khi lượt đang chờ và khi đã kết thúc; tenant B đọc việc của A → 404.
- [x] R6.6 (WFL15): `trail` có một mục mỗi nút đã chạy và không chứa chuỗi nào của đầu ra model hay payload.
- [x] R6.7: lượt đi hết → việc `done` có `closed_at`; lượt lỗi → việc `failed`.
- [x] R6.8 (WFL16): dừng sau bước gửi rồi chạy tiếp → công cụ gửi được gọi đúng một lần; gỡ `durability="sync"` thì test đỏ.
- [x] R6.10 (WFL18): duyệt với tiêu đề đã sửa → thư gửi mang tiêu đề đã sửa.
- [x] R6.14: lượt chạy mới có `release_manifest_ref` `pack:lead_care@1.0.0#<sha256 của tệp>`.
- [x] R6.19 (WFL21): sửa tệp gói giữ `key@version` khi lượt `waiting_approval`, rồi duyệt → việc `handed_off` với `definition_changed`, công cụ không chạy.
- [x] R6.15 (WFL22): DW `paused` có việc `waiting_timer` quá hạn → lane không chạy tiếp, việc giữ nguyên.
- [x] R6.16 (WFL22): approval duyệt khi DW `paused` → `dw_not_operating` ở cửa công cụ, việc `handed_off` cho Validator, không thư.
- [x] R6.18 (WFL23): công cụ giả ném lỗi → `trail` có mục `failed`, việc `handed_off` với mã lỗi.
- [x] R6.20 (WFL25): `low_confidence`, `model_output_invalid` và lỗi bước → gói đủ bốn trường không rỗng, `hand_off` nhận, người nhận là Validator.
- [x] R6.21: `proposal_schema` của cổng `approve_send` là schema đầu vào của `email.send`.
- [x] R6.18 (WFL26): nút `human.approval` bọc wrapper → lượt `waiting_approval`, không bàn giao.
- [x] G1: `test_approval_flow.py` xanh không sửa.
- [x] Xong: `make test-unit test-contract test-architecture && uv run pytest -m integration packages/python/dw_agent_runtime apps/worker apps/api` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:609-673`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/registry.py:29-47`; `docs/adr/0112-workflows-compile-to-langgraph-one-effect-per-node.md:117-135`; spec: R5, R6, G1, WFL9-WFL18, WFL21-WFL23.

## Comments

- 2026-10-29 (agent): viết lại theo gate `checking-plan-readiness` lượt 1.
- 2026-10-29 (agent): theo lượt xác nhận của gate: migration thêm `platform.worker_runs.definition_hash` và `platform.dw_timer_scopes_due` trả cặp `(tenant_id, workspace_id)`; wrapper của nút so `definition_hash` (R6.19), để `GraphInterrupt` đi qua (R6.18) và dựng gói bốn trường (R6.20); `ToolExecutor` tự hỏi `DecisionAutonomy` (R6.17); thuê 15 phút. Ca chéo tenant của lane `dw_timers` và chéo workspace của `trail` thêm vào WFL14, WFL15.
- 2026-10-29 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-10-30 (agent): đang làm, dừng ở cuối pha B (tiếp ở phiên sau, theo thứ tự này):
  - Xong: pha A `a170793` (migration `16ac88642439`: `worker_runs.definition_hash`, `dw_timer_scopes_due`;
    `RunStatus.waiting_timer`; runner đỗ lượt ở `{wait: timer}` không approval, chạy tiếp từ cả hai chờ, `RunWaitsPort`;
    `durability="sync"` cho lượt có `definition_hash`; R6.17 ở `ToolExecutor` qua `DecisionCall`) và pha B `6976baf`
    (`wflite.compile` với sáu nút và wrapper, `wflite.waits`, `wflite.starter`, `run_store.resume_context`,
    `approval_id` trong payload chạy tiếp; 11 test biên dịch trong bộ nhớ xanh).
  - Còn (pha C): một hàm dựng chung đăng ký đồ thị và `WorkerDefinition` của mọi tài liệu trong `PackCatalog` vào
    `GraphRegistry`/`WorkerRegistry`, gọi ở `build_runtime` của API và ở một runtime wf-lite mới của worker (worker
    nền tảng chưa có runner: cần checkpointer, run store, `build_model_stack`, prompt, `ToolRegistry`, `ToolExecutor` với
    `SqlDwBoundary`, `DecisionAutonomy(SqlDecisionLevels)`, `SqlApprovedDecisions`, `DecisionGate`, `WorkQueue`,
    `WorkQueueRunWaits` gắn vào runner); `WorkflowRunStarter` thay `RecordingRunStarter`; lane `dw_timers`
    (`apps/worker/src/dw_worker/consumers/dw_timers.py`: `due_timer_scopes` → `claim_timers` thuê 15 phút →
    `run_store.get` + `resume_context` + `runner.resume`, `ConflictError` là no-op); `configs/copy/wflite_handoff.yaml`
    (câu khuyến nghị theo mã) nạp vào `WfPorts.recommendations`; `trail` ở `GET /v1/work-items/{id}` (R6.13: từ
    checkpoint khi lượt đang chờ, từ `worker_runs.result` khi đã xong, dưới ngữ cảnh người gọi).
  - Còn (pha D): test integration PostgreSQL thật với model giả (lượt đi hết, dừng ở duyệt rồi chạy tiếp, hẹn giờ, bàn
    giao, WFL11, WFL14 hai lane song song và tiến trình chết sau khi nhận, WFL16 dừng giữa bước gửi rồi chạy tiếp và đỏ
    khi gỡ `durability="sync"`, WFL17, WFL21, WFL22); `mutations/02.yaml`; `reviewing-feature-security`; độ trễ (ticket
    đổi truy cập database); cổng nhanh và integration của `dw_agent_runtime`, `apps/worker`, `apps/api`.
- 2026-10-30 (agent): đang làm, pha C xong `7197171`, test pha D xong `c98c422`:
  - Pha C: `adapters/wflite_host.py` là bộ dựng chung của API và worker (executor luôn có ranh giới DW và phép kiểm
    R6.17, cổng `DecisionGate`, đăng ký `dw:<key>@<version>`, starter, `RunTrailReader`); worker dựng runtime wf-lite
    và lane `dw_timers`; `trail` ở `GET /v1/work-items/{id}`; `checkpoint_serde` và bộ đọc release manifest chuyển
    vào `dw_agent_runtime` (image worker ship `contracts/release`).
  - Pha D: `apps/worker/tests/integration/test_wflite_runs_db.py` 14 ca xanh. WFL16 đo được: lỗi giả trong tiến trình
    không phân biệt `sync` với mặc định (LangGraph ghi nốt checkpoint khi lỗi lan ra), nên test giết tiến trình con
    bằng `os._exit` sau bước gửi; gỡ `durability="sync"` thì đỏ 3/3 (dấu hiệu: `tool.replayed`). Đo thêm: một
    `Command(resume=…)` không có interrupt đang chờ được interrupt kế tiếp nhận.
  - Còn: kết quả `mutations/02.yaml` (đang chạy); sửa rò rỉ do `reviewing-feature-security` tìm ra (lượt wf-lite dừng
    ở một tiến trình rồi kết thúc ở tiến trình kia để lại mục trong `RunBudgetLedger` của tiến trình dừng); độ trễ
    của `GET /v1/work-items/{id}` so với `d565566`; cổng nhanh, integration của ba gói; đóng ticket.
- 2026-10-30 (agent): resolved ở `3c85dbd` (pha A `a170793`, B `6976baf`, C `7197171`, test `c98c422`, sửa `d209fb9`,
  `3c85dbd`). Khác với ticket và spec, ngoài hai chỗ đã ghi (sha256 vào `definition_hash`, thuê 15 phút):
  - Test integration ở `apps/worker/tests/integration/test_wflite_runs_db.py` (lane thật của worker) và test route ở
    `apps/api/tests/unit/test_work_items_endpoint.py`; gói mẫu `tests/fixtures/packs/sample`, không `lead_care`.
  - WFL16 giết tiến trình con bằng `os._exit`: lỗi giả trong tiến trình không đỏ khi gỡ `sync` (đo, ghi ở
    `failure-modes.md` #4). Lượt chết khi `running` không có đường tự chạy tiếp (reaper đánh `failed`); test tái
    kích hoạt bằng tay để hỏi đúng câu của R6.8.
  - `RunTrailReader` đọc một nguồn theo trạng thái của việc (checkpoint khi việc đang chạy/chờ, `result` khi đã đóng).
  - `reviewing-feature-security` tìm hai lỗi, đã sửa: (1) lượt wf-lite dừng ở một tiến trình rồi kết thúc ở tiến trình
    kia để lại mục `RunBudgetLedger` mãi mãi, nay giải phóng lúc dừng (chỉ cho lượt wf-lite); (2) `run_checkpoints`
    chỉ hẹp theo tenant ở RLS và saver không lọc workspace, nên người ở workspace khác cùng tenant đọc được checkpoint,
    nay `aget_tuple`/`alist` lọc workspace của config. RLS của `run_checkpoints` vẫn chỉ theo tenant (ngoài ticket này).
  - Sáu ranh giới: tenant (lane nhận dưới RLS của phạm vi, trail dưới phạm vi người gọi, test âm hai nguồn); phân quyền
    (`trail` sau `WorkQueue.get`, 404 như không tồn tại); tự chủ (mọi `tool.call` mang `DecisionCall`, cửa công cụ là
    chốt cuối, mức không đọc được là A0, trần tenant lạ là `FAIL_CLOSED_LEVEL`); nội dung không tin cậy (đầu ra model
    kiểm JSON Schema, sai thì bàn giao; tham chiếu thay nguyên giá trị; ca prompt injection của eval thuộc gói
    `lead_care` ở leadcare/01, gói mẫu là fixture); audit (`dw.decision.auto`, `run.*`, bàn giao của hàng đợi; run ghi
    release manifest cả ở worker); vòng đời (thuê 15 phút, sổ chi tiêu giải phóng lúc dừng và lúc kết thúc).
  - Mutation `mutations/02.yaml`: 30/30 đỏ, đối chứng xanh (25 lượt đầu bắt 23; hai bộ lọc hẹn giờ có hai tầng nên
    thêm test từng tầng và đột biến hàm SQL; thêm ba đột biến cho các bản sửa).
  - Độ trễ `GET /v1/work-items/{id}`, 200 request ấm, so `d565566`: lượt đang chờ P50/P95/P99 44,8/52,9/62,0 →
    54,0/67,9/82,4 ms (lần đo thứ hai 53,9/64,1/84,7); lượt đã xong 44,9/53,8/58,6 → 52,9/63,9/77,2 ms. Trong ngân sách
    (P95 ≤ 300 ms) nhưng P95 xấu hơn 21-28%: lý do là chính vòng đọc mà R6.13 đòi (một giao dịch, khoảng 10 ms trên
    máy này); bản đầu đọc hai vòng (P95 +57%) đã bỏ một.
  - Cổng: ruff, format, mypy, `make test-unit` (1708), `test-contract`, `test-architecture`, integration của
    `dw_agent_runtime`, `apps/worker`, `apps/api` (297) xanh; G1: `test_approval_flow.py` không đổi, xanh.
  - Để cho wave close: trivy image worker (chỉ thêm `COPY contracts/release`), `/code-review` của wave.
