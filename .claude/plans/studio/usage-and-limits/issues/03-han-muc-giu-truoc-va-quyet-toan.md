# 03 — Hạn mức theo chuỗi phạm vi: giữ trước lúc nhận run, quyết toán từng lượt gọi, thu hồi lease mồ côi

Status: needs-info (DO-59)
Blocked by: 01, 02, .claude/plans/studio/workflow-engine/issues/02-cot-run-va-cua-nhan-run.md, .claude/plans/studio/org-and-principals/issues/02-thanh-vien-cap-tenant.md
Area: studio
Yêu cầu: R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, R5.1, R5.2, R5.3, R5.4, R5.5, UL2, UL3, UL6, UL8, UL9, UL10, UL11, UL13

## Mục tiêu

Hạn mức là chính sách trên một Chuỗi phạm vi hạn mức; Hạn mức cứng giữ trước bằng lease Postgres mở lúc
nhận lượt chạy, mỗi lời gọi kẹp `max_tokens` theo phần còn lại và quyết toán idempotent, lease của lượt
chạy chết được thu hồi (spec R4, R5). Thay `RunBudgetLedger` và `tenant_daily_spend_guard`.

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên): `platform.limit_policies` (RLS tenant; `scope_type` CHECK
   `tenant`, `workspace`, `agent`, `workflow`, `user`; `metric`, `window_kind`, `kind` CHECK `hard`,
   `soft`; `limit_value numeric(20,8) CHECK (>= 0)`; `thresholds smallint[]` CHECK con của {50, 80, 90,
   100}; `purposes text[]`; `version`; `created_by`; `UNIQUE (tenant_id, scope_type, scope_id, metric, window_kind)`;
   trigger `updated_at` nhường giá trị lệnh nêu); `platform.budget_counters` (khóa chính sáu cột đầu,
   `CHECK (used >= 0 AND reserved >= 0)`, RLS tenant và policy drain); `platform.budget_leases`
   (`UNIQUE (tenant_id, root_run_id) WHERE state='open'`, index từng phần `expires_at WHERE state='open'`).
2. `EffectiveLimits.for_admission(run_context, artifact)` gộp gói, tenant, workspace và tổ tiên, agent
   hoặc quy trình, người dùng; cache theo tenant, xóa khi ghi. Một hàm `window_for(tenant_id, window_kind, at)`
   đọc `platform.tenants.timezone` cho ranh giới (DO-50).
3. `LimitsPort` (runtime khai, `dw_usage` đáp): `admit`, `resume`, `RunLease.before_call(estimate) -> CallPermit(max_output_tokens, call_id, occurred_at)`,
   `after_call`, `release(reason)`. Nhận run một giao dịch, khóa bộ đếm theo thứ tự chuẩn (scope rank
   rồi `scope_id`); hụt → `QuotaExceededError` `limit_exceeded` (tương tác 429, do trình kích hoạt thì
   giữ ở hàng đợi); audit `limits.refused`; metric `dw_limit_refusals_total`.
4. Runner: `_require_allowance → limits.admit`; kết thúc → `release`; `waiting_approval → release(paused)`;
   `ApproveAndResumeService → limits.resume`; bỏ `budget.forget`; số run mỗi ngày không tính lại khi
   resume (giữ quy tắc `langgraph_runner.py:255-257`). `LimitsMiddleware` thay `RunBudgetMiddleware`:
   permit mỗi lời gọi, đặt `max_tokens`, từ chối `LimitExceededError`.
5. `ReapTarget(name="budget_leases")` trên lane `reaper` (hôm nay không đăng ký gì): quét dưới
   `app.worker_drain`, đặt tenant theo từng sự kiện; dòng `unsettled_estimate`; cuộn bộ đếm; audit
   `limits.lease.expired` bằng `lane_audit_event` và `append_across_tenants`. Lane `retention_limits`
   (lease đóng quá 30 ngày, bộ đếm quá `window_end` cộng 35 ngày). Sửa `test_only_the_platform_lanes_are_wired`.
6. Route `GET /api/v1/limits` (`usage.read`), `PUT /api/v1/limits/{scope_type}/{scope_id}` và `DELETE`
   (`limits.manage`, `Idempotency-Key`); cao hơn Trần của gói → 422 `limit_above_plan`; audit
   `limits.policy.set`, `limits.policy.removed` (`before`, `after`). Màn Cấu hình hạn mức (antd Form,
   Table) ở cấp tenant và workspace, hiện Trần của gói và Hạn mức hiệu lực.
7. Xóa `RunBudgetLedger`, `RunSpend`, `ModelBudgets`, `DailyAllowance`, `SqlSpendGuard*`, lane
   `spend_guard_retention`; migration bỏ `platform.tenant_daily_spend_guard` (downgrade tạo lại). Copy
   tiếng Việt cho từ chối trong `configs/copy/runtime@x.y.z.yaml`.

## Tiêu chí chấp nhận

- [ ] R4.1: một lượt chạy có chính sách ở gói, tenant và workspace cha → qua chỉ khi cả ba còn đủ.
- [ ] R4.2: trần tenant nhỏ, lượt chạy tương tác → 429 `limit_exceeded` kèm `metric`, `scope_type`,
      `window`, `resets_at`, 0 lời gọi model (MP13).
- [ ] R4.3: trần cạn, lượt chạy do trình kích hoạt → giữ ở hàng đợi, không bỏ sự kiện.
- [ ] R4.4 (UL8): cha cap USD 10 đã hết, con cap USD 50 → lượt chạy ở con bị chặn; gỡ vòng tổ tiên → test đỏ.
- [ ] R4.5 (UL9): `PUT` hạn mức tenant cao hơn gói → 422 `limit_above_plan`, không dòng nào đổi.
- [ ] R4.6 (UL10): thiếu `limits.manage` → 403; workspace tenant khác → 404.
- [ ] R5.1 (UL2): 10 lượt chạy đồng thời, chỗ cho 3 → đúng 3 được nhận; gỡ khóa bộ đếm theo thứ tự → test đỏ.
- [ ] R5.2 (UL3): lease còn đủ cho 100 token output → lời gọi mang `max_tokens <= 100`; gỡ kẹp → test đỏ.
- [ ] R5.3 (UL11): lượt chạy chờ duyệt → `reserved` của lượt về 0; resume → giữ lại số đã tiêu qua các
      lease; gỡ nhả → test đỏ.
- [ ] R5.4 (UL6): tiến trình chết giữa lời gọi → sau `expires_at` lease đóng, phần đang bay tính, audit
      `system:reaper`; gỡ `ReapTarget` → test đỏ.
- [ ] R5.5 (UL13): trần mỗi lượt cạn giữa lượt chạy → dừng ở ranh giới lời gọi kế tiếp `limit_exceeded`,
      không hạ ngầm xuống model rẻ hơn; gỡ kiểm ranh giới → test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/ports.py:80-106`; spec: R4.1 (`RunAllowancePort`
  tiền lệ hình port).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/budget.py:60-68`; spec: R5.3 (RunBudgetLedger
  trong tiến trình, thay bằng lease).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:246-264`; spec:
  R5.1 (nhận run ở start và stream, nay thêm lease); ADR-0121 (Proposed) quyết 3-4.

## Comments

- 2026-10-23 (agent): gộp B10b usage-and-limits 04, 05, 06. `needs-info` vì DO-59 (số mặc định gói, đơn
  vị bán) còn mở; người đặt yêu cầu đặt trần riêng cho tenant thí điểm ngay, số của gói quyết trước GA.
  DO-50 quyết tạm theo khuyến nghị (a): kỳ theo múi giờ công ty, chạm trần giữa lượt dừng lượt chạy,
  chỉ run gốc tính vào số run mỗi ngày.
