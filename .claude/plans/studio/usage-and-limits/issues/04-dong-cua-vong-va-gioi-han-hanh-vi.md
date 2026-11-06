# 04 — Đóng các cửa vòng qua hạn mức và giới hạn hành vi mỗi lượt chạy có trần của gói

Status: resolved
Blocked by: 03, .claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md
Area: studio
Yêu cầu: R6.1, R6.2, R6.3, R6.4, UL4

## Mục tiêu

Mọi cửa chạm model đi qua một kiểu có đo đòi lease, không cửa nào vòng qua hạn mức; giới hạn hành vi
(số bước, lời gọi model, lời gọi công cụ mỗi lượt chạy) là kẹp của giá trị trong phiên bản và Trần của
gói, và lượt quy trình chạm giới hạn số bước dừng sạch ở ranh giới kế tiếp với một dạng từ chối (spec R6). Đây là
phần của cổng E1 (V4.31); phần vòng agent của R6.3 (`ModelCallLimitMiddleware`, `ToolCallLimitMiddleware`,
`recursion_limit` của subagent) ở ticket 06, thuộc làn trợ lý và lối ra W1b. Giới hạn thời gian theo gói (`max_run_seconds`)
là W2 cùng bên đọc của nó: hạn chót `deadline_at` của W1 là của workflow-engine và dùng trần mặc định 30 ngày khi
`limits.max_run_seconds` chưa có ở W1, không đọc số nào của gói (workflow-engine:R5.22; V4.14; Ngoài phạm vi của
spec).

## Việc cần làm

1. `RuntimeSeam` không còn lộ gateway thô, chat model trần, adapter embedding hay rerank; chỉ
   `MeteredModelGateway`, `LimitedChatModelFactory`, `MeteredEmbeddingPort`, `MeteredRerankPort`;
   `metered_invoke` đòi lease; lane nạp tri thức đo embeddings với `purpose = 'ingestion'`, gắn
   workspace và người tải tài liệu. Lời gọi không thuộc lượt chạy nào mở một lease của thao tác qua
   `LimitsPort.admit_operation(tenant, workspace, purpose, actor, operation_id)` (`purpose` `ingestion`, `retrieval`,
   `builder_assist`, CHECK của ticket 03), tính vào trần tiền và token của chuỗi phạm vi, không tính `runs`, đóng khi thao
   tác xong; lease của thao tác chỉ bị kẹp bởi trần theo kỳ, không bởi trần mỗi lượt (của lượt chạy), và giữ nhịp bằng
   cùng tác vụ nhịp của ticket 03 ở tiến trình giữ thao tác; bị từ chối → `limit_exceeded`: việc nạp kết thúc thất bại với
   mã `limit_exceeded` và `resets_at` mà người dùng thấy, tài liệu không bị xóa và nạp lại được sau đó, không migration;
   route API không phải lượt chạy Studio (ADR-0121 (Accepted) quyết 6 chỉ cấm 429 cho lượt Studio) trả 429 problem+json
   `limit_exceeded` với `Retry-After` bằng `resets_at` (spec R6.2; gate 4/11/2026 (a)). Người
   dựng liệt kê mọi lối gọi model không thuộc lượt chạy mà mã có hôm nay (theo người dùng `RuntimeSeam` và adapter
   embedding, rerank) ở Comments, mỗi lối một ca âm của R6.2. Hợp đồng import-linter: chỉ composition root import
   `RoutingModelGateway`, adapter embedding, rerank cụ thể. Test liệt kê field của `RuntimeSeam`: mọi
   field chạm model là kiểu có đo.
2. Tên `metric` của mọi `limit_exceeded`, một bảng ở `dw_usage` mà ticket 03, 04, 06 cùng dùng: trần theo kỳ và lease
   `cost_usd`, `tokens`, `runs`; trần hành vi `steps`, `model_calls`, `tool_calls`. Lượt con chạm trần hành vi của chính
   nó thì Bước cha phân biệt bằng `metric` (gate 4/11/2026 của ticket 06 (f)).
   `RunLimits = kẹp(giá trị của phiên bản, Trần của gói)` với năm trường `max_steps`, `max_model_calls`,
   `max_tool_calls`, `max_cost_usd`, `max_tokens`; phiên bản không khai một trường → Trần của gói của trường đó; tính ở
   mỗi `admit` và mỗi `resume` (ticket 03) từ giá trị của phiên bản đã ghim trong bản kê và Trần của gói hiện hành, nên
   gói đổi trong lúc lượt chờ người áp từ lần tiếp tục; lượt quy trình đọc `max_steps` (cùng `max_cost_usd`, `max_tokens`
   qua lease của ticket 03), vòng agent đọc `max_model_calls`, `max_tool_calls` (ticket 06), Bước `ai.*` chạy một vòng
   agent dùng giá trị của agent đó (gate 4/11/2026 (b)); kiểu mà cả quy trình lẫn vòng agent (ticket 06) đọc;
   quy trình: `RunLimits.max_steps` tới bộ đếm bước theo lượt của wrapper nút
   bằng tiêm (workflow-engine:R4.20, ở workflow-engine/06, ticket chờ ticket này), không tới
   `recursion_limit`, vì `recursion_limit` đặt lại mỗi lần tiếp tục (đo trên LangGraph 1.2.11,
   ADR-0112 (Accepted) Context). Mọi vi phạm → `LimitExceededError(metric)` → run `failed`,
   `error.code = limit_exceeded`, không áp chính sách lỗi của node, không thử lại (`retry` của Bước bị bỏ qua,
   ADR-0121 (Accepted) quyết 6) và không vào làn lỗi; trong `logic.parallel`, lane anh em chạy xong Bước đang chạy (không cắt
   giữa một Bước gửi, UL13) rồi không bắt đầu Bước mới, join và các Bước sau không chạy; lượt kiểm định kết thúc `error`
   với `limit_exceeded` (ADR-0113 (Accepted) quyết 3). Audit `run.limit_stopped` (`details.metric`, `details.scope_type`)
   bằng `lane_audit_event` của lane đang chạy lượt (`system:studio_runs` hay lane của worker); trên đường chạy inline cũ
   của api, audit đứng tên actor của lượt như audit kết thúc lượt hiện có của đường đó, với `details.reason_code`
   `limit_exceeded` (gate 4/11/2026 (c), (d)). Middleware giới hạn
   của vòng agent và `recursion_limit` của subagent là ticket 06.

## Tiêu chí chấp nhận

- [x] R6.1 (UL4): mọi field chạm model của `RuntimeSeam` là kiểu có đo; đặt một field thành gateway thô
      → test field đỏ.
- [x] R6.2 (UL4): lease cạn, gọi thẳng gateway có cấu trúc, `metered_invoke`, chat model, embeddings,
      rerank, lane nạp → mỗi cửa từ chối `limit_exceeded` (test âm gọi thẳng từng cửa, không qua lớp đã
      chặn).
- [x] R6.3: một Bước thử trong lượt quy trình, khai `on_error: continue`, gọi cửa có đo khi lease đã cạn và nhận
      `LimitExceededError` → run `failed` với `limit_exceeded`, Bước kế không chạy và chính sách lỗi của node không áp;
      bỏ phép bỏ qua chính sách lỗi cho `LimitExceededError` → lượt đi tiếp theo `continue`, test đỏ; giới hạn số bước
      theo lượt qua nhiều lần tiếp tục thử ở tiêu chí R4.20 của workflow-engine/06, trên `RunLimits` mà ticket này trả.
- [x] R6.4: giá trị hành vi trong phiên bản cao hơn Trần của gói → bị kẹp về Trần của gói lúc chạy; phiên bản không khai
      `max_steps` → `RunLimits.max_steps` bằng `max_steps_per_run` của gói; gói hạ trong lúc lượt chờ → lần tiếp tục dùng
      trần mới.
- [x] R6.2 (UL4): lane nạp tri thức khi tháng đã cạn → không lời gọi embedding nào tới nhà cung cấp, tài liệu ở trạng
      thái chờ với `resets_at`, không bị xóa; route truy vấn tri thức khi cạn → problem+json `limit_exceeded`; một lease
      `ingestion` không tăng bộ đếm `runs`; gỡ `admit_operation` khỏi lane nạp → embedding chạy, test đỏ.
- [x] R6.3: Bước khai `retry: {max_attempts: 3}` nhận `LimitExceededError` → không lần thử thứ hai; trong
      wrapper nút của workflow-engine/03 nhận `LimitExceededError` → lượt `failed`, audit `run.limit_stopped` đứng tên
      `system:<lane>` của lane gọi (test với lane giả tên `studio_runs`). Ca `logic.parallel` hai lane (lane anh em chạy xong
      Bước đang chạy, join không chạy) thử ở ticket dựng `logic.parallel` (workflow-engine/06, ticket đó chờ ticket này),
      vì ticket này không thể chờ nó; hành vi đã viết ở bước 2.
- [x] Xong: `cổng nhanh của ticket theo wave-close.md; tích hợp đầy đủ, mutate.py và đo trễ lúc đóng hàng đợi` xanh.

## Nguồn

- `apps/api/src/dw_api/bootstrap/container.py:104`; spec: R6.1 (`RuntimeSeam.gateway` lộ gateway thô).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_usage.py:203`; spec: R6.2
  (`metered_invoke` không trần hôm nay); ADR-0121 (Accepted) quyết 4, 9.

## Comments

- 2026-10-23 (agent): gộp B10b usage-and-limits 07, 10, cộng phần hạn mức ở executor của B8b
  tools-and-skills 08. Cùng helper kiểm soát rồi hạn mức với cửa đóng băng của agent-lifecycle.
- 2026-10-23 (agent): bỏ `max_run_seconds` khỏi W1 (phát hiện H:usage-and-limits/04~workflow-engine, ghi ở
  Ngoài phạm vi của spec).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt f, theo V4.14 của Đạt: `deadline_at` có từ W1 ở workflow-engine, với trần
  mặc định 30 ngày khi `limits.max_run_seconds` chưa có ở W1, nên Mục tiêu đổi lý do: giới hạn thời gian theo gói vẫn
  là W2 vì không bên nào ở W1 đọc nó, không phải vì hạn chót là W2. Ticket này không đổi việc cần làm và không thêm
  cạnh.
- 2026-10-25 (agent): bước 2 thôi nối số bước của quy trình vào `recursion_limit`: theo V4.26, trần của lượt
  quy trình là bộ đếm bước theo lượt của workflow-engine:R4.20, mà workflow-engine/06 dựng và nhận
  `RunLimits.max_steps` của ticket này bằng tiêm, vì `recursion_limit` đặt lại mỗi lần tiếp tục;
  `recursion_limit` vẫn là trần của vòng agent. Không thêm cạnh: workflow-engine/06 đã chờ ticket này.
- 2026-10-26 (agent): vòng 4, lượt h, theo V4.31: tách ticket. Ticket này giữ số và giữ R6.1, R6.2, phần quy trình
  của R6.3, R6.4 và UL4 (cổng E1); phần agent của bước 2 (`ModelCallLimitMiddleware`, `ToolCallLimitMiddleware`,
  `recursion_limit` của subagent) và các ca agent của tiêu chí R6.3 dời sang ticket 06, nên gỡ cạnh
  04 <- agent-builder/03 (cạnh đó nằm ở ticket 06).
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check; không migration, không
  route: CHECK `purpose` của lease thao tác nằm ở migration của ticket 03) trên `0baced0`: `check_plans.py` 24 Đạt; 0
  CRITICAL, 5 HIGH, sửa theo khuyến nghị; mỗi quyết định cùng `Nếu sai thì:` ở mục Quyết định của spec, dòng 4/11/2026
  của ticket 04, (a)-(e): lối gọi model không thuộc lượt chạy (lane nạp, truy vấn tri thức, dựng có AI) không có nguồn
  lease: lease của thao tác qua `admit_operation`; `RunLimits` có trường nào, khai thiếu thì sao, tính lúc nào; thử lại
  của Bước và làn lỗi không áp cho `LimitExceededError`, `logic.parallel` dừng thế nào; actor của `run.limit_stopped`;
  lượt kiểm định kết thúc `error`.
- 2026-11-04 (agent): MEDIUM, chưa sửa: (M1) trần tĩnh 500 Bước và độ sâu 10 của bộ kiểm wf-lite (ADR-0112 (Accepted)
  sửa đổi 3/11/2026) là cỡ cây tài liệu, không phải bộ đếm Bước theo lượt, nên không hai chủ với `max_steps_per_run`;
  cảnh báo `wf.steps_may_exceed_limit` vẫn so với `limits.max_steps` của tài liệu chưa kẹp, chủ là workflow-engine;
  (M2) lượt `datahub` chạm trần giữa lượt kết thúc `failed`, sự kiện không vào hàng lại: đúng ADR-0121 (Accepted) quyết 6
  (dừng giữa lượt), khác lúc nhận (giữ `queued`), ghi ở trang vận hành; (M3) dòng `Xong:` đọc theo
  `.claude/rules/wave-close.md`.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (builder check mới trên 04 và 06 cùng lúc): 0 CRITICAL, 4
  HIGH cho ticket này, sửa: tên `metric` chung một bảng; lease của thao tác không kẹp bởi trần mỗi lượt và có nhịp; mã HTTP
  của route không phải lượt chạy (429 với `Retry-After`) và việc nạp thất bại thấy được thay vì trạng thái chờ cần cột
  mới; ca `logic.parallel` và lane `studio_runs` không có trong Blocked by: ca song song thử ở workflow-engine/06, lane
  thử bằng lane giả. Sửa của lượt này không có người đọc mới: nhận rủi ro (agent, theo ủy quyền 31/10/2026). Nếu sai
  thì: lỗi lộ ra khi dựng, ghi ở đây. Việc cho gate của workflow-engine/06 (khu khác): tiêu chí `logic.parallel` gặp
  `LimitExceededError` ở một lane.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-06 (agent): lối gọi model không thuộc lượt chạy mà mã có hôm nay (theo người dùng `RuntimeSeam` và adapter
  embedding, rerank), mỗi lối một ca âm của R6.2: (1) lane nạp tri thức của worker (`dw_worker.consumers.ingest`),
  lease `ingestion` của workspace và người tải: `test_ingest_consumer.py::test_a_spent_month_ends_the_job_unsent_with_when_it_resets`,
  trên PostgreSQL `test_operation_leases_db.py`; (2) chỉ mục vector của ký ức ở lane outbox (`LeasedMemoryIndex`), lease
  `ingestion`, actor `system`: `test_leased_memory_index.py::test_a_spent_period_keeps_the_memory_unranked_without_raising`;
  (3) trợ lý quy trình (`ModelStack.one_call`, `POST /digital-workers/{id}/workflow-assistant`), lease `builder_assist`:
  `test_single_call_gateway.py`, và 429 `limit_exceeded` với `Retry-After` ở `test_limit_exceeded_route.py`; (4)
  `scripts/knowledge_reindex.py`, lease `ingestion` theo từng tài liệu, công ty cạn thì bỏ qua và thoát mã 1: cửa nhúng
  từ chối khi không lease nào có hiệu lực (`test_metering.py::test_an_embedding_with_no_lease_in_force_is_refused_unsent`).
  Truy vấn tri thức và gọi lại ký ức hôm nay chỉ chạy trong lượt chạy, dưới lease của lượt mà runner đặt có hiệu lực
  (`spending_under(run_holder)`); route truy vấn tri thức ngoài lượt chạy chưa có (router `knowledge` chỉ liệt kê, tải
  lên, xóa), nên `retrieval` chưa có người gọi và dạng 429 thử trên route trợ lý. Đầu dò của nhà phát triển
  (`check_model_gateway.py`, `eval_leadcare.py`, `eval_wf_ai.py` với `OpenLimits`; `check_rerank.py` gọi adapter bên trong
  cửa) không chi của công ty nào và nằm ngoài phạm vi import-linter.
- 2026-11-06 (agent): làm khác ticket. `metered_invoke` không còn trong mã (Nguồn trỏ dòng đã đổi): cửa chat tương đương
  là `LimitedChatModelFactory`, callback `PermitRequired` từ chối ở `on_chat_model_start` khi không permit nào có hiệu lực
  (permit chỉ do `LimitsMiddleware` và tóm tắt ngữ cảnh đặt, quanh đúng lời gọi). Cổng embedding và rerank không mang
  `RunContext`, nên đọc lease có hiệu lực từ ContextVar `dw_kernel.limits.LeaseInForce` (runner đặt cho lượt,
  `held_operation` cho thao tác); lease của công ty khác bị từ chối. `RoutingModelGateway` dời sang `model/routing.py`
  để hợp đồng import-linter cấm được nó. Bảng giá lên 1.1.0 (thêm `mock hash-embedding` giá 0). `RunContext.declared_limits`
  rỗng ở W1 (chưa phiên bản nào khai giới hạn; workflow-engine/06 nhận `RunLimits.max_steps` bằng tiêm). Lượt Studio
  dừng vì hạn mức ghi `error.code = limit_exceeded` như từ chối ở hàng đợi (`studio_dispatch`). Không migration: các cột
  `max_*_per_run` của gói đã có. Lượt kiểm định chưa có lane chạy (không ai gọi `admit_gate`), nên kết thúc `error` của
  ADR-0113 quyết 3 thuộc ticket dựng lane đó. Sửa thêm các mutation cũ đã lệch từ ticket 03 và model-connections/02
  (usage-and-limits/02 R2.5, R3.1, R3.2; agent-lifecycle/01 AL11 sub-agent; model-connections/02 MR1 cửa ngân sách).
- 2026-11-06 (agent, theo ủy quyền 31/10/2026): quyết định. (a) Chỉ mục ký ức chi bằng lease `ingestion` của công ty,
  actor `system`; bị từ chối thì ký ức vẫn gọi lại được, chưa xếp hạng, không vòng thử lại. Nếu sai thì: thêm purpose
  riêng ở migration sau. (b) Dựng lại chỉ mục tính vào hạn mức của công ty sở hữu tài liệu. Nếu sai thì: lease do nền
  tảng trả (`payer = platform`) như cổng kiểm định. (c) Rerank được đo theo `rerank_search_unit` và bảng giá W1 chưa có
  giá nào cho nó: một bản ghi `unpriced` dừng lượt ở lời gọi kế (R2.5), nên api đã triển khai bật rerank chưa có giá thì
  không khởi động (`require_rerank_priced`, cùng luật R2.3). Nếu sai thì: thêm giá rerank vào bảng giá trước khi bật.
- 2026-11-06 (agent): ticket `resolved`. Cổng: ruff, ruff format, mypy (Windows và Linux 3.12.15), `lint-imports` 17
  hợp đồng giữ (hợp đồng mới tự thử bằng `test_model_door_import_contract.py`), unit cả repo, contract 30, tích hợp
  `dw_usage` cùng `test_wf_ai_wiring.py` 87 xanh. Nợ lúc đóng hàng: `mutate.py` của `mutations/04.yaml` (23 mutation) và
  các tệp mutation đã sửa, tích hợp đầy đủ, P50/P95/P99 của ingest, trợ lý quy trình và một bước model của lượt Studio.
