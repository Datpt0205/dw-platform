# 04 — Làn studio_runs: lấy việc công bằng, lease, reaper, thư chết

Status: needs-triage
Blocked by: 03
Area: studio
Yêu cầu: R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.7, R5.8, WE2, WE3, WE4, WE6, WE8

## Mục tiêu

Chạy lượt chạy Studio ở worker từ hàng `platform.worker_runs`, công bằng theo tenant, với lease có hàng rào, một reaper nhận lại lượt mồ côi và thư chết thấy được, để một tenant ồn không bỏ đói tenant khác và một worker chết không làm mất hay nhân đôi tác động (R5 của spec).

## Việc cần làm

1. `build_studio_lanes` ở composition root của worker dựng runner Studio và đăng ký làn `studio_runs` qua `ConsumerRegistry.register`; sửa `test_only_the_platform_lanes_are_wired` để thêm làn mới có tên.
2. Hàm SECURITY DEFINER `platform.studio_run_scopes_due(...)` trả id lượt chạy công bằng theo tenant (mẫu `platform.channel_delivery_scopes_due`), theo quy tắc hàm definer (search_path cố định, thu EXECUTE khỏi PUBLIC); lấy việc dưới RLS bằng `FOR UPDATE SKIP LOCKED`.
3. Ở dispatch: kiểm `RunControlPort` rồi `LimitsPort.admit`; thiếu hạn mức → giữ `queued` với `available_at` sau, không `failed`.
4. Heartbeat gia hạn `lease_expires_at`; token rào (fencing) từ chối ghi checkpoint hay trạng thái của worker đã mất lease; làn `studio_run_reaper` nhận lại lượt mồ côi; backoff; `dead_at` và outbox `studio.run.dead_lettered` sau số lần thử; đánh thức bằng NOTIFY `dw_run_state`.
5. Ưu tiên `eval` thấp hơn tương tác và trình kích hoạt qua cột `priority`.

## Tiêu chí chấp nhận

- [ ] R5.1 (WE2): tạo lượt chạy khi worker tắt → dòng giữ `queued`, tiến trình API không gọi `ainvoke`; dời việc chạy vào API → test đỏ.
- [ ] R5.2 (WE4): sau 10.000 lượt chờ của tenant A, lượt của tenant B nằm trong lô lấy đầu; đổi hàm sang FIFO → test đỏ.
- [ ] R5.3 (WE3): hàm definer dưới ngữ cảnh tenant A chỉ trả id của A; bỏ lọc tenant trong hàm → test đỏ.
- [ ] R5.4 (WE6): vượt hạn mức đồng thời → lượt chạy giữ `queued` với `available_at` sau, không `failed`; bỏ kiểm `LimitsPort.admit` → test đỏ.
- [ ] R5.5 (WE8): worker cũ ghi checkpoint sau khi mất lease → bị từ chối, worker dừng; bỏ token rào → test đỏ.
- [ ] R5.6: `kill -9` worker giữa lượt chạy → một worker khác nhận lại trong ≤ 90 giây, đúng một lần.
- [ ] R5.7: năm lần sập → `dead_at` đặt, outbox `studio.run.dead_lettered`, không nhận lại.
- [ ] R5.8: lượt `eval` và lượt tương tác cùng chờ → lượt tương tác lấy trước.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/channel_deliveries.py:47`; `apps/worker/tests/unit/test_worker.py:103-104`; spec: R5, WE2, WE3, WE4, WE6, WE8.
- usage-and-limits `LimitsPort.admit`; agent-lifecycle `RunControlPort` và ưu tiên `eval`; ADR-0113 (Proposed) quyết 1-2.

## Comments
