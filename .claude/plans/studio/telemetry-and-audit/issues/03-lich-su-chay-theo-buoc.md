# 03 — Lịch sử chạy theo bước: `run_steps` có che và lưu giữ, danh sách run, chi tiết bước

Status: needs-triage
Blocked by: .claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md, .claude/plans/studio/field-security/issues/01-mo-hinh-bao-mat-truong.md, .claude/plans/studio/usage-and-limits/issues/02-bang-gia-so-su-dung-va-man-hinh.md, .claude/plans/studio/usage-and-limits/issues/03-han-muc-giu-truoc-va-quyet-toan.md
Area: studio
Yêu cầu: R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R4.1, R4.2, R4.3, R5.1, R5.2, R5.3, R5.4, R5.5, TA4, TA5, TA6, TA10, TA11, TA12, TA13

## Mục tiêu

Một kho `platform.run_steps` cho mỗi Bước chạy, che bí mật khi ghi và che theo quyền đọc trường của người
xem khi đọc; màn Lịch sử chạy đọc dưới `runs.read` theo độ sâu; một chính sách lưu giữ có bộ xóa cho mỗi
kho mới (spec R3, R4, R5).

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên): `platform.run_steps` phân vùng theo tháng trên `started_at`
   với DEFAULT, RLS ENABLE và FORCE trên cha và DEFAULT cùng migration; `PRIMARY KEY (id, started_at)`;
   cột `tenant_id`, `workspace_id`, `run_id`, `root_run_id`, `seq int`, `kind` CHECK (`node`, `model_call`,
   `tool_call`, `approval`, `sub_run`), `node_id`, `status`, `started_at timestamptz`, `finished_at
timestamptz`, `duration_ms`, `error_type`, `input_preview` và `result_preview` (≤ 4 KB), `input_ref` và
   `result_ref` (đường dẫn đối tượng, NULL khi giữ trong dòng), token, `cost_usd numeric(18,8)`,
   `price_book_version`, `redaction_log jsonb NOT NULL DEFAULT '[]'`, `fls_version`; không cột nội dung
   thô; `dw_app` không UPDATE, DELETE trên cha và không giữ quyền nào trên phân vùng nào, kể cả DEFAULT
   (DO-02.2); index `ix_run_steps_run (tenant_id, run_id, seq)`.
2. Đăng ký `run_steps` bằng một dòng `platform.time_partitioned_tables` (`append_only = true`) trong cùng
   migration; không sửa thân `platform.ensure_time_partitions` (studio-skeleton/01 là chủ hàm, hàm tạo
   partition kèm ENABLE/FORCE RLS và policy công ty).
3. `StepRecorderPort.step_started`, `step_finished`; đường che `redact_mapping` bỏ trường bí mật và tham
   chiếu credential, che trường `Nhạy cảm` bằng hàm quyết quyền đọc trường của field-security, preview
   ≤ 4 KB, payload lớn gzip ở đường dẫn `tenants/{tenant_id}/workspaces/{workspace_id}/run-steps/`, ghi
   đường dẫn và lý do che vào `redaction_log`.
4. Agent: Bước chạy `model_call` và `tool_call` ghi từ `LimitsMiddleware` (usage-and-limits/03) và
   ToolExecutor; đọc token và chi phí mỗi Bước chạy từ Sổ sử dụng của usage-and-limits.
5. Route (`runs.read`, RLS và workspace theo độ sâu): `GET /api/v1/runs?artifact_kind&artifact_id&status&trigger_kind&from&to&cursor&limit`
   với index `ix_worker_runs_page (tenant_id, workspace_id, created_at DESC, id DESC)`;
   `GET /api/v1/runs/{run_id}/steps`; `GET /api/v1/runs/{run_id}/steps/{step_id}/payload?part=in|out`
   (`runs.read_payloads`, che theo quyền đọc trường của người xem, audit `run.payload.viewed` trong cùng
   giao dịch). Một lượt chạy chạm bản ghi người xem không thấy → 404.
6. Màn `/runs` (antd Table: thời điểm, agent hoặc quy trình, trạng thái, nguồn kích hoạt, thời lượng, chi
   phí, bộ lọc) và `/runs/[id]` (Steps, Descriptions, xem JSON có dấu `Đã ẩn`, token và chi phí mỗi Bước
   chạy, nút "Sao chép trace id").
7. `configs/policies/retention@1.8.0.yaml` thay `1.7.0`; ticket này là chủ duy nhất của bản 1.8.0
   (compliance-pdpl/06 nâng lên 1.9.0 sau), mọi số ghi UNVERIFIED tới khi luật sư xác nhận trước chạy bóng
   (DO-52): lớp và bộ xóa cho `run_steps` (30 ngày; lane xóa payload trong dòng và đối tượng của bước quá 30
   ngày qua một hàm riêng của lane vì `dw_app` không UPDATE bảng, DROP PARTITION khi cả tháng quá 30 ngày),
   payload đối tượng (30 ngày, lane xóa đối tượng), cột payload lượt chạy (90 ngày sau kết thúc, lane xóa),
   lượt chạy (395 ngày sau kết thúc, lane xóa, bỏ qua dòng `memory.items` trỏ tới theo
   `db/migrations/versions/0007_evidence.py:113-115`), `usage_events` (395 ngày, DROP PARTITION bằng
   `drop_expired_partitions` của usage-and-limits/02), `usage_daily` (760 ngày, lane xóa),
   `studio.inbound_events` (30 ngày, lane xóa, bỏ qua sự kiện mà lượt `queued` còn trỏ tới),
   `studio.trigger_deliveries` (90 ngày, lane xóa), khóa chống trùng của sự kiện vào (72 giờ, lane xóa); bỏ
   chú thích "model_usage_ledger đã bị bỏ" của bản 1.7.0 (`configs/policies/retention@1.7.0.yaml:72`); test
   tập bộ xóa và `test_the_pinned_retention_policy_promises_only_classes_code_can_assign`. Test xóa trên bảng
   sự kiện vào chạy ở workflow-triggers/02, nơi tạo bảng.

## Tiêu chí chấp nhận

- [ ] R3.1: một node kết thúc → đúng một Bước chạy mang trạng thái, thời điểm, thời lượng, token, chi phí.
- [ ] R3.2 (TA6): input mang một khóa bí mật → preview không có giá trị, `redaction_log` ghi lý do; gỡ bỏ
      bí mật → test đỏ.
- [ ] R3.3 (TA5): người không có quyền đọc `phone` → payload trả dấu `Đã ẩn`; gỡ che → test đỏ.
- [ ] R3.4: payload 4 KB giữ trong dòng; 4 KB cộng một byte → lưu theo tham chiếu, dòng giữ `input_ref`.
- [ ] R3.5 (TA10): mở payload → đúng một sự kiện `run.payload.viewed`; gỡ ghi audit → test đỏ.
- [ ] R3.6 (TA4): `GET /api/v1/runs/{run_id}/steps` của lượt chạy công ty B từ A → 404; danh sách
      `GET /api/v1/runs` không có lượt chạy công ty khác.
- [ ] R4.1: người giữ `runs.read` gọi `GET /api/v1/runs` → chỉ lượt chạy trong tập workspace được phép;
      trang 2 không trùng và không sót dòng so với trang 1.
- [ ] R4.2: `GET /api/v1/runs/{run_id}/steps` → các Bước chạy theo thứ tự `seq`.
- [ ] R4.3 (TA12): thiếu `runs.read_payloads` gọi payload → 403, không trả payload; gỡ kiểm → test đỏ.
- [ ] R5.1 (TA13): mỗi kho (`run_steps`, payload đối tượng, cột payload, `usage_events`, `usage_daily`,
      `studio.inbound_events`, `studio.trigger_deliveries`, khóa chống trùng) có một thời hạn trong
      `retention@1.8.0` và một bộ xóa đã đăng ký.
- [ ] R5.2 (TA13): một lớp retention thiếu bộ xóa → test tập bộ xóa đỏ.
- [ ] R5.3 (TA11): lượt chạy `waiting_approval` 400 ngày còn nguyên; lượt chạy được `memory.items` trỏ tới
      → bỏ qua, được đếm.
- [ ] R5.4: Bước chạy 31 ngày tuổi trong tháng chưa tới lúc DROP → lane xóa preview và đối tượng của nó, dòng
      bước còn trạng thái và chi phí; bước 29 ngày còn nguyên payload.
- [ ] R5.5 (TA11): sự kiện vào 31 ngày mà một lượt `queued` còn trỏ tới → lane bỏ qua, được đếm; sự kiện 31
      ngày không còn ai trỏ tới → bị xóa.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `apps/api/src/dw_api/routes/v1/runs.py:41-68`; spec: R4.1 (có `get_run` và `timeline`; thêm danh sách,
  bước, payload).
- `configs/policies/retention@1.7.0.yaml:118-120`; spec: R5.3 (dẫn Nghị định 13 cần bỏ, chuyển compliance-pdpl).
- ADR-0122 (Accepted) quyết 4, 7; ADR-0106 (Accepted) quyết 4.

## Comments

- 2026-10-23 (agent): gộp B10b telemetry-and-audit 05, 06, 07. `needs-info` vì DO-52 (thời hạn lưu) chờ
  counsel và Đạt. Cột `redaction_log` giữ quyết định che để kiểm; payload lớn theo tham chiếu để xóa theo
  yêu cầu chủ thể (compliance-pdpl ticket 14, W2).
- 2026-10-23 (agent): DO-52 có lời đáp cho W1 (Đạt, 23/10/2026), nên `needs-triage`. Ticket này là chủ
  duy nhất của `retention@1.8.0`; chờ usage-and-limits/03 vì Bước chạy `model_call` ghi từ
  `LimitsMiddleware`; compliance-pdpl/06 chờ ticket này.
