# 03 — Run không kẹt ở waiting_approval, CHECK trạng thái, outbox lùi thời gian và thư chết

Status: ready-for-agent
Blocked by: .claude/plans/studio/foundations-hardening/issues/01-test-khong-the-do.md, .claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md
Area: studio
Yêu cầu: R9.1, R9.2, R9.3, R10.1, R10.2, R10.3, R10.4, R10.5, G5, RH25, RH26, RH27, RH28, RH29

## Mục tiêu

Resume chết giữa chừng không còn làm thread kẹt mãi; PostgreSQL từ chối trạng thái lạ của run, yêu
cầu phê duyệt và quyết định, với các giá trị Studio sẽ ghi đã có sẵn; outbox lùi thời gian khi thử lại
và thư chết hiện trên số đo và cảnh báo (R9, R10, G5, RH25-RH29). Người vận hành phát lại thư chết
bằng một script có audit đứng tên mình; công ty thấy lượt chạy lỗi của mình trong Lịch sử chạy, không
có route mới (DO-56.1). Ticket này chờ tenant-config/03, cùng ALTER `platform.worker_runs` và cùng sửa
đường resume, và tenant-config/05 chờ ticket này (OPS-b); agent-lifecycle/01 chờ ticket này, vì nó chèn phép
kiểm công tắc vào cùng đường resume; tenant-config/04 chờ ticket này, vì cùng ALTER `platform.worker_runs` và CHECK
`ck_worker_runs_status` có trước cột `run_manifest_hash` của nó.

## Việc cần làm

Run không kẹt (R9.1, R9.2, G5):

1. `SqlWorkerRunStore.begin_resume(run_context, run_id, *, waiting: RunStatus)`: UPDATE
   `platform.worker_runs` đặt `status = 'running'` và `updated_at = now()` chỉ khi `status` bằng `waiting`
   (`waiting_approval` hay `waiting_timer`, trạng thái `resume` vừa đọc), có `RETURNING id`, cùng giao dịch và
   cùng NOTIFY như `set_status`; 0 dòng → `ConflictError` (409).
2. `LangGraphWorkflowRunner.resume` gọi `begin_resume` sau kiểm `hosts`, `_graph` và `worker_registry.resolve`, và
   trước audit `run.resumed` và `waits.resumed`, để lần thua 409 không ghi audit hay đổi việc; câu
   `set_status(RUNNING)` không điều kiện của đường `waiting_timer` bị bỏ, vì `begin_resume` thay nó. Từ ngay sau
   `begin_resume` tới hết lần chạy graph, bắt `BaseException`: gọi `uncancel()` trước khi ghi như `_drive` làm,
   ghi `failed` (lỗi `ResumeInterrupted` khi bị hủy) rồi ném lại. Tiến trình bị giết hẳn để run ở `running`;
   reaper của đường claim thread dọn nó sau ngưỡng `stale_run_after_seconds` (3600 giây) như mọi run `running`
   khác. Lane `dw_timers` đã bắt `ConflictError` (`apps/worker/src/dw_worker/consumers/dw_timers.py:88`), nên lần
   thua của nó chỉ ghi log. Đường resume dựng trên bản của tenant-config/03, nơi chế độ chạy được dựng lại trong
   `resume_context`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py:130-180`); giữ nguyên chỗ dựng lại đó, và giữ `_ensure_graph` (wf-ai R6.5)
   trước kiểm `hosts`.

CHECK trạng thái (R9.3):

3. Revision Alembic mới `db/migrations/versions/*_run_status_checks_and_outbox_backoff.py` (id ngẫu
   nhiên): `SELECT DISTINCT` trên dữ liệu hiện có (ghi Comments), rồi thêm
   `ck_worker_runs_status` cho `status IN ('pending', 'running', 'waiting_approval', 'waiting_timer', 'completed', 'failed', 'cancelled', 'queued', 'waiting', 'blocked', 'dead_lettered')`
   trên `platform.worker_runs`,
   `ck_approval_requests_status` cho `status IN ('pending', 'approved', 'rejected', 'cancelled', 'expired')`
   trên `platform.approval_requests`, và `ck_approval_decisions_outcome` cho
   `outcome IN ('approved', 'rejected')` trên `platform.approval_decisions`.
4. `RunStatus` thêm `QUEUED`, `WAITING`, `BLOCKED`, `DEAD_LETTERED` (ADR-0113 (Accepted) quyết 1, 3) và `ApprovalStatus` thêm
   `EXPIRED` (ADR-0112 (Accepted)), mỗi giá trị kèm comment nói chưa có người ghi cho tới
   `workflow-engine`; người ghi `EXPIRED` là workflow-engine ở W2, và ở W1 phê duyệt chờ không hạn
   (DO-31). Test catalog so tập giá trị của mỗi CHECK với enum chủ của nó (`RunStatus`,
   `ApprovalStatus`, `DecisionOutcome`). Nếu enum lộ qua API, chạy `make generate-contracts`.

Outbox (R10.1, R10.2, R10.3):

5. Cùng revision: `platform.outbox_events` thêm `available_at timestamptz NOT NULL DEFAULT now()` và
   `dead_at timestamptz NULL`; thay `ix_outbox_events_unprocessed` bằng một index một phần cho dòng
   `processed_at IS NULL AND dead_at IS NULL` phục vụ truy vấn claim (thứ tự `occurred_at`, điều kiện
   `available_at`); chọn cột theo `EXPLAIN` của truy vấn claim và ghi plan vào Comments.
6. `SqlOutboxDrain.claim_batch` thêm `available_at <= now()` và `dead_at IS NULL`, giữ thứ tự
   `occurred_at`, và bỏ điều kiện `attempts < max_attempts`: trong cùng câu UPDATE của claim, dòng đã có
   `attempts >= max_attempts` (tiến trình chết giữa lần giao cuối, hay dòng hết lượt từ trước migration) được đặt
   `dead_at = now()` và không được trả về để giao. `backlog()` cũng thôi lọc theo `attempts`; `dead_at` là chủ duy
   nhất của "đã chết".
7. `record_failure`: với n là `attempts` sau claim, đặt
   `available_at = now() + min(30 × 2^(n-1), 3600)` giây cộng jitter ngẫu nhiên từ 0 tới 20% khoảng
   đó; khi n bằng `outbox_max_attempts` thì đặt `dead_at = now()`; claim và `record_failure` cùng
   dùng `now()` của PostgreSQL, không dùng đồng hồ của tiến trình.
8. `_deliver`: `UndeliverableEventError` đặt `dead_at = now()` ngay, không dùng hết lượt.
9. Tên gauge `dw_outbox_dead_letters` khai cạnh `DW_OUTBOX_BACKLOG_SIZE` trong
   `dw_observability.metrics`; worker xuất nó trong cùng lượt đo backlog; `backlog()` chỉ đếm dòng
   chưa chết; luật `DwOutboxDeadLetters` khi `dw_outbox_dead_letters > 0` trong
   `infra/prometheus/alerts.yml`, cùng dạng `DwOutboxBacklogAboveThreshold`.

Phát lại thư chết (R10.4, R10.5), theo DO-56.1:

10. `scripts/replay_dead_outbox.py --operator <email> <event_id>...`, người vận hành chạy bằng thông tin
    của `dw_app`: tìm user của `--operator` trong bảng người vận hành của nền tảng, không có thì thoát 1
    và không đổi gì; đọc `id`, `tenant_id`, `workspace_id` của từng sự kiện chết dưới
    `set_config('app.worker_drain', 'on', true)`, không đọc `payload`; mỗi sự kiện một giao dịch đặt
    tenant bằng `set_config('app.tenant_id', <tenant của sự kiện>, true)`, xóa `dead_at`, đặt
    `attempts = 0` và `available_at = now()`, rồi ghi audit `platform.outbox.replayed` (actor là người
    vận hành, `resource_id` là id sự kiện) trong cùng giao dịch. Không có route cho công ty: công ty thấy
    lượt chạy lỗi của mình trong Lịch sử chạy. Cùng thay đổi: mảnh `configs/copy/audit_actions.d/runtime-hardening.yaml`
    mang nhãn tiếng Việt của `platform.outbox.replayed`, mảnh của spec này trong catalog hành động mà
    telemetry-and-audit gộp (telemetry-and-audit:R1.6; H-21); ticket này không chờ ticket nào vì mảnh.

## Tiêu chí chấp nhận

- [ ] R9.1 (RH25): integration giả lập chết sau `begin_resume` (run ở `running`, `updated_at` đặt lùi
      quá `stale_run_after_seconds`) → lượt mới của cùng thread được nhận, không còn báo chờ duyệt;
      bỏ compare-and-set (resume không đổi `status`) → lượt mới bị báo chờ duyệt, test đỏ.
- [ ] R9.1: `CancelledError` trong lần chạy graph → run `failed` với lỗi `ResumeInterrupted` và ngoại
      lệ được ném lại.
- [ ] R9.2 (RH25): hai resume đồng thời cùng một run → đúng một lần chạy graph, lần kia 409 và không ghi
      audit `run.resumed`; cùng ca cho một run `waiting_timer` → một chạy, một 409; các test hẹn giờ của
      `apps/worker/tests/integration/test_wflite_runs_db.py` (lane `dw_timers` chạy tiếp từ `waiting_timer`)
      xanh với compare-and-set.
- [ ] R9.3 (RH26): ghi `status='bogus'` vào run và yêu cầu phê duyệt, `outcome='bogus'` vào quyết định
      → CHECK từ chối; thêm một giá trị vào `RunStatus` mà không vào CHECK → test catalog đỏ.
- [ ] R10.1 (RH27): lỗi lần một → sự kiện không được claim khi `available_at` còn ở tương lai; lùi
      `available_at` về quá khứ → được claim lại; khoảng lùi lần n nằm trong `[b, 1,2 × b]` với
      `b = min(30 × 2^(n-1), 3600)` giây; bỏ điều kiện `available_at` khỏi claim → đỏ.
- [ ] R10.2 (RH28): thất bại ở lượt `outbox_max_attempts` → `dead_at` được đặt và sự kiện không bị
      claim lại; `UndeliverableEventError` → `dead_at` ngay lần đầu; sự kiện có `attempts` bằng
      `outbox_max_attempts`, `processed_at` và `dead_at` rỗng (chết giữa lần giao cuối) → lượt claim kế đặt
      `dead_at`, handler không chạy, gauge bằng 1; bỏ điều kiện `dead_at` khỏi claim, hay bỏ nhánh hết lượt
      của claim → đỏ.
- [ ] R10.3 (RH28): một sự kiện chết → gauge `dw_outbox_dead_letters` bằng 1, không có → 0; `backlog`
      không đếm sự kiện chết.
- [ ] R10.4 (RH29): người vận hành chạy script cho một sự kiện chết → sự kiện về hàng đợi (`dead_at`
      rỗng, `attempts` 0) và có đúng một audit `platform.outbox.replayed` đứng tên người đó, trong cùng
      giao dịch; audit ném lỗi → sự kiện vẫn mang `dead_at`.
- [ ] R10.5 (RH29): `--operator` không có trong `platform.platform_operators` → script thoát 1, sự kiện
      vẫn mang `dead_at`, không có audit; gỡ kiểm người vận hành → test đỏ.
- [ ] G5: `test_pause_restart_resume_approved` xanh với compare-and-set.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

Đo lại ở `ceec634` (2/11/2026):

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:561-619` (`resume`, nhận
  `waiting_approval` và `waiting_timer` ở dòng 569, `set_status(RUNNING)` của hẹn giờ ở dòng 595-598)
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:492-513` (`_drive` bắt
  `CancelledError`, `uncancel()` trước khi ghi)
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py:239-270` (đụng
  `uq_worker_runs_active_thread`: hỏi chờ duyệt trước, rồi reaper)
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py:272-314` (reaper)
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py:316-334` (`waiting_approval_for_thread`)
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py:35-47` (`RunStatus`, `TERMINAL_STATUSES`)
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py:474-495` (`set_status`)
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:156-194` (`_resumable_run` chỉ nhận
  `waiting_approval`)
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:371-375` (gọi `runner.resume`)
- `apps/worker/src/dw_worker/consumers/dw_timers.py:83-89` (lane hẹn giờ gọi `resume`, bắt `ConflictError`)
- `packages/python/dw_platform/src/dw_platform/domain/approval.py:44-53`
- `configs/policies/worker_runs@1.0.0.yaml:28`
- `db/migrations/sql/0001_platform_baseline.sql:683`, `db/migrations/sql/0001_platform_baseline.sql:701`
  (`uq_worker_runs_active_thread`)
- `apps/worker/src/dw_worker/consumers/outbox.py:48-61`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/outbox_drain.py:46-119`
- `packages/python/dw_observability/src/dw_observability/metrics.py:33-50` (hai gauge outbox và `ALL_METRICS`)
- `infra/prometheus/alerts.yml:53-65`
- `docs/adr/0113-every-run-is-requested-and-queued-in-postgres.md:40-47`
- spec: R9, R10, G5, RH25-RH29; telemetry-and-audit:R1.6 (mảnh nhãn audit; H-21).

## Comments

- 2026-10-24 (agent): tenant-config/04 chờ ticket này (cạnh ở dòng Blocked by của tenant-config/04), vì hai
  ticket cùng ALTER `platform.worker_runs` và CHECK `ck_worker_runs_status` có trước cột `run_manifest_hash`; migration
  của tenant-config/04 nối tiếp revision của ticket này, nên cây Alembic chỉ có một head
  (C:runtime-hardening/03~tenant-config/04).
- 2026-10-24 (agent): `ck_worker_runs_status` và `RunStatus` nhận thêm `dead_lettered` (bước 3, 4; spec R9.3), trạng thái
  thư chết mà lane `studio_run_reaper` của workflow-engine/04 ghi (ADR-0113 (Accepted) quyết 3; workflow-engine:R3.2,
  workflow-engine:R5.7); workflow-engine/02 đã chờ ticket này.
- 2026-10-25 (agent): ticket chuyển từ foundations-hardening/06 sang đây thành ticket 03 khi spec tách (hai dòng Quyết định cuối của spec); kiểm soát FH25-FH29 thành RH25-RH29, cùng số, và cạnh tới ticket 01 cùng thư mục cũ thành đường dẫn tới foundations-hardening/01. Không đổi việc cần làm, không thêm cạnh.
- 2026-10-26 (agent): lượt h, đợt 2, theo H-21 (dòng tạm 25/10/2026 của telemetry-and-audit): nhãn của audit
  `platform.outbox.replayed` vào mảnh `configs/copy/audit_actions.d/runtime-hardening.yaml` trong cùng thay đổi (bước
  10); test AST của telemetry-and-audit:R1.6 đọc mảnh đó khi telemetry-and-audit/03, đi sau ticket này, vào. Không thêm
  cạnh.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` HIGH 1: CHECK `ck_worker_runs_status` thiếu
  `waiting_timer`, trạng thái wf-lite/02 đã ghi (`run_store.py:39-41`, `langgraph_runner.py:764`), nên migration hay
  lần đỗ hẹn giờ đầu tiên sẽ bị chính CHECK từ chối; bước 3 và spec R9.3 thêm `waiting_timer`. Nếu sai thì: bỏ
  `waiting_timer` khỏi CHECK cùng lúc wf-lite đổi trạng thái chờ hẹn giờ của run sang `waiting` của ADR-0113 (Accepted).
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH 2: `resume` nay chạy tiếp từ cả `waiting_approval` lẫn
  `waiting_timer` (`langgraph_runner.py:569`, lane `dw_timers`), nên compare-and-set chỉ từ `waiting_approval` làm mọi
  lần chạy tiếp hẹn giờ thành 409; bước 1, 2 cho `begin_resume` nhận trạng thái chờ vừa đọc, thay câu
  `set_status(RUNNING)` không điều kiện của đường hẹn giờ, đặt nó trước audit `run.resumed` và `waits.resumed`, và
  gọi `uncancel()` như `_drive`; tiêu chí R9.2 thêm ca hẹn giờ và test lane `dw_timers`; spec R9.1, RH25 theo. Neo Nguồn
  đo lại ở `ceec634`. Nếu sai thì: đường hẹn giờ giữ câu `set_status` cũ và R9.2 chỉ hứa cho `waiting_approval`.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH 3: claim lọc `attempts < max_attempts`, nên sự kiện mà tiến
  trình chết giữa lần giao cuối (lượt đã đếm lúc claim, `record_failure` chưa chạy) có `dead_at` rỗng và vô hình với
  claim, `backlog` lẫn gauge, mất lặng lẽ đúng chỗ R10.3 hứa thấy được; bước 6 cho claim đặt `dead_at` cho dòng đã hết
  lượt và bỏ lọc theo `attempts`, `dead_at` là chủ duy nhất; tiêu chí R10.2 và spec R10.2, RH28 thêm ca đó. Nếu sai
  thì: `backlog` và gauge đếm `attempts >= outbox_max_attempts` thay vì `dead_at`.
- 2026-11-02 (agent): gate MEDIUM, chưa sửa, cho người dựng: (1) resume bị hủy ghi `failed`/`ResumeInterrupted` còn
  `_drive` ghi `cancelled`/`run.cancelled` cho cùng sự kiện, hai câu trả lời; theo `_drive` hoặc ghi lý do khác ở đây.
  (2) script đặt `app.worker_drain` từ `scripts/`, nơi phép quét của foundations-hardening:R2.6
  (`test_drain_setting_scan.py`) không nhìn tới (`failure-modes.md` #0); nên đọc phạm vi sự kiện chết qua một phương
  thức của `SqlOutboxDrain`, module đã được miễn, để hằng drain giữ một chủ. (3) id không chết (đã phát lại, chạy hai lần
  cùng lúc, id lạ): UPDATE có `dead_at IS NOT NULL`, 0 dòng thì không audit, nêu id và thoát khác 0. (4)
  `DW_OUTBOX_DEAD_LETTERS` vào cả `ALL_METRICS` (`metrics.py:39-50`). (5) `QUEUED`, `WAITING`, `BLOCKED`,
  `DEAD_LETTERED` thêm vào `RunStatus` nhưng `TERMINAL_STATUSES` và `uq_worker_runs_active_thread` giữ nguyên ở đây;
  workflow-engine quyết `dead_lettered` có là cuối; `waiting` (ADR-0113 (Accepted)) và `waiting_timer` (wf-lite) là hai tên của run
  chờ, cho `checking-plan-consistency`. (6) run chạy tiếp từ hẹn giờ mà chết: reaper chỉ dọn khi có lượt mới cùng
  thread, việc của DW ở `in_progress` do lane của digital-worker (R3.14, R3.15) xử; và `_fail` trước `waits.resumed`
  gọi `waits.finished` trên việc còn `waiting_timer`, chuyển mà bảng của digital-worker không có. (7) dòng chết không
  có ai xóa ngoài phát lại; hàng "Xóa dòng outbox đã xử lý" của Ngoài phạm vi chỉ nói dòng đã xử lý
  (`failure-modes.md` #6). (8) tham số `max_attempts` của `backlog()` thôi có người đọc sau bước 6; bỏ khỏi
  `OutboxDrainPort`. (9) ticket thêm migration, index và đổi câu claim, `record_failure`, thêm một câu trên đường
  resume: đo độ trễ theo `latency.md`, ở lần đóng đợt (2/11/2026). LOW: enum không lộ qua `apps/api` (grep), nên
  `make generate-contracts` không cần; dòng Xong đọc theo `wave-close.md`.
- 2026-11-02 (agent): bảng cặp: telemetry-and-audit/02 (cột `trace_parent` của `platform.outbox_events`, dispatcher) có
  đường qua workflow-engine/03 → workflow-engine/02 → ticket này; usage-and-limits/03 (đường resume) qua
  workflow-engine/02; agent-lifecycle/01, tenant-config/04, tenant-config/05 chờ ticket này; record-access/05 chỉ chèn
  dòng outbox, cột mới có mặc định, không đụng. Không cặp nào đụng mà thiếu đường. Duyệt cách chia: dòng 30/10/2026
  (agent, tạm theo ủy quyền) "Duyệt cách chia ticket 01-03" của spec.
- 2026-11-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-02 (agent): code và test riêng xong, đã commit; chờ integration liên quan trước khi resolved.
