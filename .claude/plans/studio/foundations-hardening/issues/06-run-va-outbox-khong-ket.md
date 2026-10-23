# 06 — Run không kẹt ở waiting_approval, CHECK trạng thái, outbox lùi thời gian và thư chết

Status: needs-info (DO-56)
Blocked by: 01
Area: studio
Yêu cầu: R9.1, R9.2, R9.3, R10.1, R10.2, R10.3, R10.4, G5, FH25, FH26, FH27, FH28, FH29

## Mục tiêu

Resume chết giữa chừng không còn làm thread kẹt mãi; PostgreSQL từ chối trạng thái lạ của run, yêu
cầu phê duyệt và quyết định, với các giá trị Studio sẽ ghi đã có sẵn; outbox lùi thời gian khi thử lại
và thư chết hiện trên số đo và cảnh báo (R9, R10, G5, FH25-FH29). Phần phát lại thư chết (R10.4,
FH29) chờ Q2 (DO-56); phần còn lại không phụ thuộc câu trả lời đó.

## Việc cần làm

Run không kẹt (R9.1, R9.2, G5):

1. `SqlWorkerRunStore.begin_resume(run_context, run_id)`: UPDATE `platform.worker_runs` đặt
   `status = 'running'` và `updated_at = now()` chỉ khi `status = 'waiting_approval'`, có
   `RETURNING id`; 0 dòng → `ConflictError` (409).
2. `LangGraphWorkflowRunner.resume` gọi `begin_resume` sau kiểm `hosts` và trước khi chạy graph; bắt
   `BaseException` quanh lần chạy graph, ghi `failed` (lỗi `ResumeInterrupted` khi bị hủy) rồi ném
   lại. Tiến trình bị giết hẳn để run ở `running`; reaper của đường claim thread dọn nó sau ngưỡng
   `stale_run_after_seconds` (3600 giây) như mọi run `running` khác.

CHECK trạng thái (R9.3):

3. Revision Alembic mới `db/migrations/versions/*_run_status_checks_and_outbox_backoff.py` (id ngẫu
   nhiên): `SELECT DISTINCT` trên dữ liệu hiện có (ghi Comments), rồi thêm
   `ck_worker_runs_status` cho `status IN ('pending', 'running', 'waiting_approval', 'completed', 'failed', 'cancelled', 'queued', 'waiting', 'blocked')`
   trên `platform.worker_runs`,
   `ck_approval_requests_status` cho `status IN ('pending', 'approved', 'rejected', 'cancelled', 'expired')`
   trên `platform.approval_requests`, và `ck_approval_decisions_outcome` cho
   `outcome IN ('approved', 'rejected')` trên `platform.approval_decisions`.
4. `RunStatus` thêm `QUEUED`, `WAITING`, `BLOCKED` (ADR-0113 (Proposed)) và `ApprovalStatus` thêm
   `EXPIRED` (ADR-0112 (Proposed)), mỗi giá trị kèm comment nói chưa có người ghi cho tới
   `workflow-engine`; test catalog so tập giá trị của mỗi CHECK với enum chủ của nó (`RunStatus`,
   `ApprovalStatus`, `DecisionOutcome`). Nếu enum lộ qua API, chạy `make generate-contracts`.

Outbox (R10.1, R10.2, R10.3):

5. Cùng revision: `platform.outbox_events` thêm `available_at timestamptz NOT NULL DEFAULT now()` và
   `dead_at timestamptz NULL`; thay `ix_outbox_events_unprocessed` bằng một index một phần cho dòng
   `processed_at IS NULL AND dead_at IS NULL` phục vụ truy vấn claim (thứ tự `occurred_at`, điều kiện
   `available_at`); chọn cột theo `EXPLAIN` của truy vấn claim và ghi plan vào Comments.
6. `SqlOutboxDrain.claim_batch` thêm `available_at <= now()` và `dead_at IS NULL`, giữ thứ tự
   `occurred_at`.
7. `record_failure`: với n là `attempts` sau claim, đặt
   `available_at = now() + min(30 × 2^(n-1), 3600)` giây cộng jitter ngẫu nhiên từ 0 tới 20% khoảng
   đó; khi n bằng `outbox_max_attempts` thì đặt `dead_at = now()`; claim và `record_failure` cùng
   dùng `now()` của PostgreSQL, không dùng đồng hồ của tiến trình.
8. `_deliver`: `UndeliverableEventError` đặt `dead_at = now()` ngay, không dùng hết lượt.
9. Tên gauge `dw_outbox_dead_letters` khai cạnh `DW_OUTBOX_BACKLOG_SIZE` trong
   `dw_observability.metrics`; worker xuất nó trong cùng lượt đo backlog; `backlog()` chỉ đếm dòng
   chưa chết; luật `DwOutboxDeadLetters` khi `dw_outbox_dead_letters > 0` trong
   `infra/prometheus/alerts.yml`, cùng dạng `DwOutboxBacklogAboveThreshold`.

Phát lại thư chết (R10.4), làm sau khi Q2 có câu trả lời:

10. Công cụ phát lại một sự kiện chết theo `event_id`: xóa `dead_at`, đặt `attempts = 0` và
    `available_at = now()`, ghi một audit trong cùng giao dịch. Ai được chạy nó, qua đường nào và
    audit ghi actor nào theo câu trả lời Q2 (khuyến nghị: người vận hành qua một script trong
    `scripts/`).

## Tiêu chí chấp nhận

- [ ] R9.1 (FH25): integration giả lập chết sau `begin_resume` (run ở `running`, `updated_at` đặt lùi
      quá `stale_run_after_seconds`) → lượt mới của cùng thread được nhận, không còn báo chờ duyệt;
      bỏ compare-and-set (resume không đổi `status`) → lượt mới bị báo chờ duyệt, test đỏ.
- [ ] R9.1: `CancelledError` trong lần chạy graph → run `failed` với lỗi `ResumeInterrupted` và ngoại
      lệ được ném lại.
- [ ] R9.2 (FH25): hai resume đồng thời cùng một run → đúng một lần chạy graph, lần kia 409.
- [ ] R9.3 (FH26): ghi `status='bogus'` vào run và yêu cầu phê duyệt, `outcome='bogus'` vào quyết định
      → CHECK từ chối; thêm một giá trị vào `RunStatus` mà không vào CHECK → test catalog đỏ.
- [ ] R10.1 (FH27): lỗi lần một → sự kiện không được claim khi `available_at` còn ở tương lai; lùi
      `available_at` về quá khứ → được claim lại; khoảng lùi lần n nằm trong `[b, 1,2 × b]` với
      `b = min(30 × 2^(n-1), 3600)` giây; bỏ điều kiện `available_at` khỏi claim → đỏ.
- [ ] R10.2 (FH28): thất bại ở lượt `outbox_max_attempts` → `dead_at` được đặt và sự kiện không bị
      claim lại; `UndeliverableEventError` → `dead_at` ngay lần đầu; bỏ điều kiện `dead_at` khỏi claim
      → đỏ.
- [ ] R10.3 (FH28): một sự kiện chết → gauge `dw_outbox_dead_letters` bằng 1, không có → 0; `backlog`
      không đếm sự kiện chết.
- [ ] R10.4 (FH29): theo câu trả lời Q2, người được phép phát lại → sự kiện về hàng đợi và có đúng một
      audit; người không được phép → từ chối, sự kiện vẫn mang `dead_at`.
- [ ] G5: `test_pause_restart_resume_approved` xanh với compare-and-set.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:501-548`
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py:213-255`
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py:257-275`
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py:34-40`
- `packages/python/dw_platform/src/dw_platform/domain/approval.py:44-53`
- `configs/policies/worker_runs@1.0.0.yaml:28`
- `db/migrations/sql/0001_platform_baseline.sql:683`
- `apps/worker/src/dw_worker/consumers/outbox.py:48-62`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/outbox_drain.py:46-119`
- `packages/python/dw_observability/src/dw_observability/metrics.py:27-29`
- `infra/prometheus/alerts.yml:53-66`
- `docs/adr/0113-every-run-is-requested-and-queued-in-postgres.md:40-44`
- spec: R9, R10, G5, FH25-FH29.

## Comments
