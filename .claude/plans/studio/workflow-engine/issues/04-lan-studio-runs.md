# 04 — Làn studio_runs: lấy việc công bằng, lease, reaper, thư chết

Status: needs-triage
Blocked by: 03, .claude/plans/studio/usage-and-limits/issues/03-han-muc-giu-truoc-va-quyet-toan.md, .claude/plans/studio/agent-lifecycle/issues/05-tat-khan-cap-va-khoi-phuc.md
Area: studio
Yêu cầu: R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.7, R5.8, R5.9, R5.10, R5.11, R5.12, R5.13, R5.14, R5.15, R5.16, R5.17, R5.18, WE2, WE3, WE4, WE6, WE8, WE17

## Mục tiêu

Chạy lượt chạy Studio ở worker từ hàng `platform.worker_runs`, công bằng theo tenant, với lease có hàng rào, một reaper nhận lại lượt mồ côi và thư chết thấy được, để một tenant ồn không bỏ đói tenant khác và một worker chết không làm mất hay nhân đôi tác động (R5 của spec).

## Việc cần làm

1. `build_studio_lanes` ở composition root của worker dựng runner Studio và đăng ký làn `studio_runs` qua `ConsumerRegistry.register`; sửa `test_only_the_platform_lanes_are_wired` để thêm làn mới có tên.
2. Hàm SECURITY DEFINER `platform.studio_run_scopes_due(...)` trả id lượt chạy công bằng theo tenant (mẫu `platform.channel_delivery_scopes_due`), theo quy tắc hàm definer (search_path cố định, thu EXECUTE khỏi PUBLIC); lấy việc dưới RLS bằng `FOR UPDATE SKIP LOCKED`.
3. Ở dispatch, chỗ duy nhất nhận lượt chạy Studio cho mọi `trigger_kind` (DO-21.3), và bảng R5 của spec là chủ duy nhất của hình từ chối: kiểm `RunControlPort` rồi `LimitsPort.admit` của usage-and-limits/03, vốn chỉ trả lý do, `resets_at` và `metric`; xử lý từ chối theo bảng R5.4, R5.9-R5.18 của spec và không gọi model: thiếu đồng thời → `queued` với `available_at` sau; hết hạn mức của kỳ → `chat`, `manual`, `test` thành `failed` `limit_exceeded` kèm `resets_at` và `metric`, `datahub`, `provider_app`, `record_event` giữ `queued` với `available_at` bằng `resets_at`, `eval` kết thúc lượt kiểm định `error` với `limit_exceeded`; Đóng băng → `chat`, `manual`, `test`, `eval` thành `cancelled` với `tenant_frozen` hay `platform_frozen`, lượt do trình kích hoạt giữ `queued` và nhận theo `available_at` sau khi gỡ; Tắt khẩn → `cancelled`, không giữ `queued` (DO-28 C); `principal_inactive` → `chat`, `manual`, `test`, `eval` thành `cancelled` với `principal_inactive`, còn `datahub`, `provider_app`, `record_event` giữ `queued` và nhận theo thứ tự `available_at` khi tài khoản dịch vụ `active` lại (D9 của Đạt ngày 24/10/2026; R5.15, R5.17); `tenant_locked`, `tenant_offboarding` → mọi loại thành `cancelled` với đúng lý do đó (R5.18); `control_state_unavailable` → giữ `queued` với `available_at` sau (ADR-0113 (Accepted) quyết 3). Báo người chịu trách nhiệm khi bắt đầu giữ là dòng W2 của spec.
4. Lease nhận việc 60 giây trên `lease_owner`, `lease_until`, heartbeat 15 giây gia hạn `lease_until`; mọi lệnh ghi trạng thái và checkpoint rào bằng `(lease_owner, attempt)`, nên worker đã mất lease bị từ chối; lane `studio_run_reaper` nhận lại lượt mồ côi với backoff `min(2^attempt * 5 s, 10 phút)` cộng jitter; sau 5 lần thử, trong một giao dịch, lane đặt `status = 'dead_lettered'`, ghi audit `run.dead_lettered` qua `lane_audit_event` với actor `system:studio_run_reaper` và outbox `studio.run.dead_lettered` (ADR-0113 (Accepted) quyết 3; CLAUDE.md, Agent and tool rules). Làn lấy việc bằng thăm dò theo chu kỳ của `ConsumerRegistry`; ticket này không dùng NOTIFY `dw_run_state`, kênh đó thuộc dòng W2 hủy xuyên tiến trình.
5. Ưu tiên qua cột `priority` (0 lượt tương tác, 1 lượt do trình kích hoạt, 2 lượt `eval`), lấy việc theo `(priority, available_at)`, nên `eval` đi sau tương tác và trình kích hoạt.

## Tiêu chí chấp nhận

- [ ] R5.1 (WE2): tạo lượt chạy khi worker tắt → dòng giữ `queued`, tiến trình API không gọi `ainvoke`; dời việc chạy vào API → test đỏ.
- [ ] R5.2 (WE4): sau 10.000 lượt chờ của tenant A, lượt của tenant B nằm trong lô lấy đầu; đổi hàm sang FIFO → test đỏ.
- [ ] R5.3 (WE3): hàm definer dưới ngữ cảnh tenant A chỉ trả id của A; bỏ lọc tenant trong hàm → test đỏ.
- [ ] R5.4 (WE6): vượt hạn mức đồng thời → lượt chạy giữ `queued` với `available_at` sau, không `failed`; bỏ kiểm `LimitsPort.admit` → test đỏ.
- [ ] R5.9 (WE6): hết hạn mức của kỳ với lượt `chat` → `failed` với `limit_exceeded` kèm `resets_at` và `metric` lấy từ câu trả lời của `LimitsPort.admit`, 0 lời gọi model.
- [ ] R5.10 (WE6): hết hạn mức của kỳ với lượt `datahub` → giữ `queued`, `available_at` bằng `resets_at`, sự kiện nhận còn nguyên, 0 lời gọi model.
- [ ] R5.11 (WE6): hết hạn mức của kỳ với lượt `eval` → lượt kiểm định kết thúc `error` với `limit_exceeded`, không có phản hồi HTTP nào.
- [ ] R5.12 (WE17): Đóng băng tenant khi lượt `chat` và lượt `manual` đang `queued` → cả hai `cancelled` với `tenant_frozen`; giữ `queued` cho lượt tương tác → test đỏ.
- [ ] R5.13 (WE17): Đóng băng tenant khi ba lượt `datahub` đang `queued` → cả ba giữ `queued`; gỡ Đóng băng → ba lượt chạy theo thứ tự `available_at`.
- [ ] R5.14 (WE17): Tắt khẩn quy trình khi một lượt `datahub` của nó đang `queued` → `cancelled`, không giữ `queued`.
- [ ] R5.15 (WE17): người chạy của một lượt `manual` bị tạm khóa khi lượt đang `queued` → `cancelled` với `principal_inactive`, 0 lời gọi model.
- [ ] R5.16 (WE17): `RunControlPort` báo `control_state_unavailable` → lượt giữ `queued` với `available_at` sau, không `cancelled`, 0 lời gọi model; cho lượt qua khi port báo lý do đó → test đỏ.
- [ ] R5.17 (WE17): tài khoản dịch vụ chạy của ba lượt `datahub` bị tạm khóa khi chúng đang `queued` → cả ba giữ `queued`, 0 lời gọi model; kích hoạt lại tài khoản → ba lượt chạy theo thứ tự `available_at`; hủy lượt `datahub` vì `principal_inactive` → test đỏ.
- [ ] R5.18 (WE17): công ty `locked` khi một lượt `chat` và một lượt `datahub` đang `queued` → cả hai `cancelled` với `tenant_locked`; công ty `offboarding` → `cancelled` với `tenant_offboarding`; 0 lời gọi model.
- [ ] R5.5 (WE8): worker cũ ghi checkpoint sau khi mất lease → bị từ chối, worker dừng; bỏ token rào → test đỏ.
- [ ] R5.6: `kill -9` worker giữa lượt chạy → một worker khác nhận lại trong ≤ 90 giây, đúng một lần.
- [ ] R5.7: năm lần sập → `status = 'dead_lettered'`, đúng một audit `run.dead_lettered` với actor `system:studio_run_reaper` và một outbox `studio.run.dead_lettered` trong cùng giao dịch, không nhận lại.
- [ ] R5.8: lượt `eval` (`priority` 2) và lượt tương tác (`priority` 0) cùng chờ → lượt tương tác lấy trước.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/channel_deliveries.py:47`; `apps/worker/tests/unit/test_worker.py:103-104`; spec: R5, WE2, WE3, WE4, WE6, WE8.
- usage-and-limits `LimitsPort.admit`; agent-lifecycle `RunControlPort` và ưu tiên `eval`; ADR-0113 (Accepted) quyết 1-2.

## Comments

- 2026-10-23 (agent): theo phiếu 23/10/2026: `LimitsPort.admit` chỉ gọi ở dispatch, hình từ chối theo `trigger_kind` (DO-21.3); Đóng băng ở dispatch hủy lượt tương tác và giữ lượt do trình kích hoạt (DO-28 C).
- 2026-10-24 (agent): theo quyết định của Đạt ngày 24/10/2026: ticket chờ usage-and-limits/03 (`LimitsPort.admit` trả lý do, `resets_at`, `metric`; bảng từ chối là của spec này) và agent-lifecycle/05 (Tắt khẩn cho R5.14); thêm R5.15, R5.16; bỏ NOTIFY `dw_run_state` khỏi W1; lane tên `studio_run_reaper`.
- 2026-10-24 (agent): vòng sửa thứ tư: theo D9 của Đạt, lượt do trình kích hoạt mà tài khoản dịch vụ không `active` ở lại `queued` (R5.17), lượt khác vẫn `cancelled` (R5.15); bảng từ chối thêm `tenant_locked`, `tenant_offboarding` (R5.18, B:agent-lifecycle:R9.2~workflow-engine:R5); lease, rào và thư chết theo tên của ADR-0113 (Accepted) quyết 3 (phát hiện F về ADR-0113 (Accepted) và R3.1).
- 2026-10-24 (agent): kiểm sau vòng sửa thứ tư: bước 3 dẫn bảng R5.4, R5.9-R5.18, vì R5.17 và R5.18 đã vào bảng, và ghi rõ D9 của Đạt ngày 24/10/2026, vì D9 của requirements là một hướng khác.
