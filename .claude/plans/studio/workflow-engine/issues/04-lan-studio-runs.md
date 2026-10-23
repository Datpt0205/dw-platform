# 04 — Làn studio_runs: lấy việc công bằng, lease, reaper, thư chết

Status: needs-triage
Blocked by: 03
Area: studio
Yêu cầu: R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.7, R5.8, R5.9, R5.10, R5.11, R5.12, R5.13, R5.14, WE2, WE3, WE4, WE6, WE8, WE17

## Mục tiêu

Chạy lượt chạy Studio ở worker từ hàng `platform.worker_runs`, công bằng theo tenant, với lease có hàng rào, một reaper nhận lại lượt mồ côi và thư chết thấy được, để một tenant ồn không bỏ đói tenant khác và một worker chết không làm mất hay nhân đôi tác động (R5 của spec).

## Việc cần làm

1. `build_studio_lanes` ở composition root của worker dựng runner Studio và đăng ký làn `studio_runs` qua `ConsumerRegistry.register`; sửa `test_only_the_platform_lanes_are_wired` để thêm làn mới có tên.
2. Hàm SECURITY DEFINER `platform.studio_run_scopes_due(...)` trả id lượt chạy công bằng theo tenant (mẫu `platform.channel_delivery_scopes_due`), theo quy tắc hàm definer (search_path cố định, thu EXECUTE khỏi PUBLIC); lấy việc dưới RLS bằng `FOR UPDATE SKIP LOCKED`.
3. Ở dispatch, chỗ duy nhất nhận lượt chạy Studio cho mọi `trigger_kind` (DO-21.3): kiểm `RunControlPort` rồi `LimitsPort.admit`, xử lý từ chối theo bảng R5.4, R5.9-R5.14 của spec và không gọi model: thiếu đồng thời → `queued` với `available_at` sau; hết hạn mức của kỳ → `chat`, `manual`, `test` thành `failed` `limit_exceeded` kèm `resets_at`, `datahub`, `provider_app`, `record_event` giữ `queued` với `available_at` bằng `resets_at`, `eval` kết thúc lượt kiểm định `error` với `limit_exceeded`; Đóng băng → `chat`, `manual`, `test`, `eval` thành `cancelled` với `tenant_frozen` hay `platform_frozen`, lượt do trình kích hoạt giữ `queued` và nhận theo `available_at` sau khi gỡ; Tắt khẩn → `cancelled`, không giữ `queued` (DO-28 C).
4. Heartbeat gia hạn `lease_expires_at`; token rào (fencing) từ chối ghi checkpoint hay trạng thái của worker đã mất lease; làn `studio_run_reaper` nhận lại lượt mồ côi; backoff; `dead_at` và outbox `studio.run.dead_lettered` sau số lần thử; đánh thức bằng NOTIFY `dw_run_state`.
5. Ưu tiên `eval` thấp hơn tương tác và trình kích hoạt qua cột `priority`.

## Tiêu chí chấp nhận

- [ ] R5.1 (WE2): tạo lượt chạy khi worker tắt → dòng giữ `queued`, tiến trình API không gọi `ainvoke`; dời việc chạy vào API → test đỏ.
- [ ] R5.2 (WE4): sau 10.000 lượt chờ của tenant A, lượt của tenant B nằm trong lô lấy đầu; đổi hàm sang FIFO → test đỏ.
- [ ] R5.3 (WE3): hàm definer dưới ngữ cảnh tenant A chỉ trả id của A; bỏ lọc tenant trong hàm → test đỏ.
- [ ] R5.4 (WE6): vượt hạn mức đồng thời → lượt chạy giữ `queued` với `available_at` sau, không `failed`; bỏ kiểm `LimitsPort.admit` → test đỏ.
- [ ] R5.9 (WE6): hết hạn mức của kỳ với lượt `chat` → `failed` với `limit_exceeded` kèm `resets_at`, 0 lời gọi model.
- [ ] R5.10 (WE6): hết hạn mức của kỳ với lượt `datahub` → giữ `queued`, `available_at` bằng `resets_at`, sự kiện nhận còn nguyên, 0 lời gọi model.
- [ ] R5.11 (WE6): hết hạn mức của kỳ với lượt `eval` → lượt kiểm định kết thúc `error` với `limit_exceeded`, không có phản hồi HTTP nào.
- [ ] R5.12 (WE17): Đóng băng tenant khi lượt `chat` và lượt `manual` đang `queued` → cả hai `cancelled` với `tenant_frozen`; giữ `queued` cho lượt tương tác → test đỏ.
- [ ] R5.13 (WE17): Đóng băng tenant khi ba lượt `datahub` đang `queued` → cả ba giữ `queued`; gỡ Đóng băng → ba lượt chạy theo thứ tự `available_at`.
- [ ] R5.14 (WE17): Tắt khẩn quy trình khi một lượt `datahub` của nó đang `queued` → `cancelled`, không giữ `queued`.
- [ ] R5.5 (WE8): worker cũ ghi checkpoint sau khi mất lease → bị từ chối, worker dừng; bỏ token rào → test đỏ.
- [ ] R5.6: `kill -9` worker giữa lượt chạy → một worker khác nhận lại trong ≤ 90 giây, đúng một lần.
- [ ] R5.7: năm lần sập → `dead_at` đặt, outbox `studio.run.dead_lettered`, không nhận lại.
- [ ] R5.8: lượt `eval` và lượt tương tác cùng chờ → lượt tương tác lấy trước.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/channel_deliveries.py:47`; `apps/worker/tests/unit/test_worker.py:103-104`; spec: R5, WE2, WE3, WE4, WE6, WE8.
- usage-and-limits `LimitsPort.admit`; agent-lifecycle `RunControlPort` và ưu tiên `eval`; ADR-0113 (Accepted) quyết 1-2.

## Comments

- 2026-10-23 (agent): theo phiếu 23/10/2026: `LimitsPort.admit` chỉ gọi ở dispatch, hình từ chối theo `trigger_kind` (DO-21.3); Đóng băng ở dispatch hủy lượt tương tác và giữ lượt do trình kích hoạt (DO-28 C).
