# 03 — Hạn mức theo chuỗi phạm vi: giữ trước lúc nhận run, quyết toán từng lượt gọi, thu hồi lease mồ côi

Status: needs-triage
Blocked by: 01, 02, .claude/plans/studio/workflow-engine/issues/02-cot-run-va-cua-nhan-run.md, .claude/plans/studio/org-and-principals/issues/02-thanh-vien-cap-tenant.md, .claude/plans/studio/compliance-pdpl/issues/03-tuyen-du-lieu-o-model-gateway.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md
Area: studio
Yêu cầu: R3.8, R4.1, R4.4, R4.5, R4.6, R4.8, R4.9, R4.10, R4.12, R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.7, R6.5, UL2, UL3, UL6, UL8, UL9, UL10, UL11, UL13, UL15

## Mục tiêu

Hạn mức là chính sách trên một Chuỗi phạm vi hạn mức; Hạn mức cứng giữ trước bằng lease Postgres mở lúc
nhận lượt chạy, mỗi lời gọi kẹp `max_tokens` theo phần còn lại và quyết toán idempotent, lease của lượt
chạy chết được thu hồi (spec R4, R5). Thay `RunBudgetLedger` và `tenant_daily_spend_guard`.

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên): `platform.limit_policies` (RLS tenant; `scope_type` CHECK
   `tenant`, `workspace`, `agent`, `workflow`; cột khóa ngoại có kiểu `scope_workspace_id` (FK ghép
   `(tenant_id, scope_workspace_id)` tới `platform.workspaces (tenant_id, id)`, đích là `uq_workspaces_tenant_id_id` của
   org-and-principals/01, ticket này chờ nó qua org-and-principals/02) và `scope_artifact_id` (FK ghép
   `(tenant_id, scope_artifact_id)` tới `studio.artifacts (tenant_id, id)`, đích là `uq_artifacts_tenant_id_id` của
   tenant-config/02), mỗi FK `ON DELETE CASCADE` và có index riêng; CHECK `num_nonnulls` của hai cột đó bằng 1 với
   đúng cột của `scope_type` khác `tenant` và bằng 0 khi `tenant` (spec R4.12; ADR-0121 (Accepted) quyết 4);
   `metric`, `window_kind`; `kind` CHECK `hard`, giá trị duy nhất ở W1; `limit_value numeric(20,8) CHECK (>= 0)`;
   `version`; `created_by`; UNIQUE NULLS NOT DISTINCT trên `tenant_id`, `scope_workspace_id`, `scope_artifact_id`,
   `metric`, `window_kind`; trigger `updated_at` nhường giá trị lệnh nêu; không có `scope_user_id`, `thresholds`,
   `purposes` và giá trị `soft` của `kind` ở W1, mỗi thứ vào ở W2 cùng bên đọc của nó, Ngoài phạm vi của spec);
   `platform.budget_counters` (khóa chính sáu cột đầu, `CHECK (used >= 0 AND reserved >= 0)`, RLS tenant và
   policy drain); `platform.budget_leases` (`UNIQUE (tenant_id, root_run_id) WHERE state='open'`, index từng phần
   `expires_at WHERE state='open'`). Ba bảng có policy `tenant_isolation_*` và DELETE cho `dw_app`, nên lane
   `offboarding` xuất rồi xóa chúng như bảng thường (spec R3.8; studio-skeleton:R4.3). Cùng migration: đăng ký
   khóa `platform.limits.manage` trong `platform.permissions` của tenant-rbac/01 (nhãn tiếng Việt, `scope_kind`
   `tenant`, `risk` `elevated` theo bảng phân loại của ticket đó); INSERT nêu mọi cột NOT NULL của bảng lúc đó, gồm
   `risk` của tenant-rbac/01 và `tenant_grantable` (`true`) của tenant-rbac/02, ticket này chờ ticket đó. Cùng thay
   đổi: thêm khóa `platform.budget_counters` (395 ngày sau `window_end`) và `platform.budget_leases` (30 ngày sau khi
   đóng), số tạm UNVERIFIED, vào bản kế tiếp của tệp chính sách retention theo định dạng của
   telemetry-and-audit:R5.6; trong chuỗi phiên bản của tệp, bản này đứng sau bản của ticket 02 và trước bản của
   telemetry-and-audit/03.
2. `EffectiveLimits.for_admission(run_context, artifact)` gộp gói, tenant, workspace và tổ tiên, agent
   hoặc quy trình (phạm vi người dùng ở W2); cache theo tenant, xóa khi ghi. Một hàm `window_for(tenant_id, window_kind, at)`
   đọc `platform.tenants.timezone` cho ranh giới, NULL thì Asia/Ho_Chi_Minh (DO-50; ADR-0121 (Accepted)
   quyết 9); ảnh worker mang dữ liệu múi giờ (tzdata).
3. `LimitsPort` (runtime khai, `dw_usage` đáp): `admit`, `resume`, `RunLease.before_call(estimate) -> CallPermit(max_output_tokens, call_id, occurred_at)`,
   `after_call`, `release(reason)`. Nhận run một giao dịch, khóa bộ đếm theo thứ tự chuẩn (scope rank
   rồi `scope_id`); hết kỳ → `QuotaExceededError` `limit_exceeded` kèm `metric`, `scope_type`, `window`,
   `limit`, `used`, `resets_at`, không mở lease và không đổi bộ đếm (spec R4.10); không đếm chỗ đồng thời ở W1
   (trần đồng thời là W2, spec R4.11 đã rút); audit `limits.refused`; metric `dw_limit_refusals_total`. Ticket này
   chỉ trả câu trả lời; hình từ chối theo `trigger_kind` (đặt `failed`, giữ `queued` tới `resets_at`) là của làn
   `studio_runs` trong workflow-engine/04 (workflow-engine:R5.9, workflow-engine:R5.10, workflow-engine:R5.11),
   ticket đó chờ ticket này; không 429 (429 chỉ còn ở đường chạy inline cũ `langgraph_runner.py:246-264`).
4. Runner, do làn `studio_runs` gọi lúc dispatch, là chỗ duy nhất gọi `admit`: `_require_allowance` →
   `limits.admit`; lượt chạy con và lần thử của Lượt kiểm định dùng lease của lượt gốc hay của Lượt kiểm
   định, không gọi `admit` (ADR-0113 (Accepted) quyết 9); kết thúc → `release`; `waiting_approval` →
   `release(paused)`; `ApproveAndResumeService` → `limits.resume`; bỏ `budget.forget`; số run mỗi ngày không
   tính lại khi resume (giữ quy tắc `langgraph_runner.py:255-257`). `LimitsMiddleware` thay
   `RunBudgetMiddleware`: permit mỗi lời gọi, đặt `max_tokens`, từ chối `LimitExceededError`; đứng sau
   `ResidencyGate` của compliance-pdpl/03, nên một lời gọi bị cổng lộ trình từ chối không giữ tiền và không
   ghi Bản ghi sử dụng (spec R6.5).
5. `ReapTarget(name="budget_leases")` trên lane `reaper` (hôm nay không đăng ký gì): quét dưới
   `app.worker_drain`, đặt tenant theo từng sự kiện; dòng `unsettled_estimate`; cuộn bộ đếm; audit
   `limits.lease.expired` bằng `lane_audit_event` và `append_across_tenants`. Lane `retention_limits` đọc thời
   hạn dưới khóa `platform.budget_counters` và `platform.budget_leases` của tệp chính sách retention mà lane
   `partitions` nạp (bộ đếm quá `window_end` cộng 395 ngày, lease đóng quá 30 ngày; spec R5.7), không ghi cứng số
   nào trong mã; thiếu khóa thì không xóa gì và báo lỗi cấu hình. Sửa `test_only_the_platform_lanes_are_wired`.
6. Route `GET /api/v1/limits` (`platform.usage.read`): mỗi chính sách kèm Hạn mức hiệu lực, bộ đếm của kỳ
   hiện tại và giờ đặt lại (không route `/api/v1/usage/limits` riêng). `PUT /api/v1/limits/{scope_type}/{scope_id}`
   và `DELETE` (`platform.limits.manage`, `Idempotency-Key`; `{scope_type}` nhận `tenant`, `workspace`, `agent`,
   `workflow`, còn `user` là W2): hạ hay đặt mới áp ngay với một người, audit
   `limits.policy.set` (`before`, `after`) trong cùng giao dịch; nâng hay gỡ → 409
   `second_person_required`, không đổi dòng nào (D11; nới qua tenant-config là W2); cao hơn Trần của gói →
   422 `limit_above_plan`; `kind` khác `hard` → 422 `validation_failed` với con trỏ tới `kind` (app-standards:R1.3),
   vì `soft` là W2. Màn Cấu hình hạn mức (antd Form, Table) ở cấp tenant và workspace, hiện Trần của
   gói và Hạn mức hiệu lực; W1 chỉ có thao tác siết.
7. Xóa `RunAllowancePort` và adapter của nền tảng đáp nó, `RunBudgetLedger`, `RunSpend`, `ModelBudgets`,
   `DailyAllowance`, `SqlSpendGuard*`, lane `spend_guard_retention`; sửa wiring ở composition root và test
   lane; migration bỏ `platform.tenant_daily_spend_guard` (downgrade tạo lại) và bỏ dòng của bảng đó khỏi
   danh sách bảng toàn tenant của `test_rls_coverage.py`; `platform.limit_policies`,
   `platform.budget_counters` vào danh sách đó kèm lý do. Copy tiếng Việt cho từ chối trong
   `configs/copy/runtime@x.y.z.yaml`.

## Tiêu chí chấp nhận

- [ ] R4.1: một lượt chạy có chính sách ở gói, tenant và workspace cha → qua chỉ khi cả ba còn đủ.
- [ ] R4.10: trần kỳ của tenant cạn → `LimitsPort.admit` trả `limit_exceeded` kèm `metric`, `scope_type`,
      `window`, `limit`, `used`, `resets_at`, không dòng `budget_leases` mới, `budget_counters` không đổi, không
      phản hồi 429 nào.
- [ ] R4.12: xóa workspace mà một chính sách hạn mức nhắm tới → chính sách đó biến mất cùng lệnh xóa; xóa thành phần
      agent mà một chính sách nhắm tới → như trên; dòng đặt cả hai cột phạm vi, `scope_type` `workspace` mà cột
      workspace NULL, hay `scope_type` `user` → CHECK từ chối.
- [ ] R3.8: công ty `offboarding` có dòng trong `limit_policies`, `budget_counters`, `budget_leases` → lane
      `offboarding` xuất mỗi dòng một lần rồi xóa hết; test phủ offboarding (studio-skeleton:R4.3) xanh không cần
      dòng `STUDIO_EXCLUSIONS` cho ba bảng.
- [ ] R4.4 (UL8): cha cap USD 10 đã hết, con cap USD 50 → lượt chạy ở con bị chặn; gỡ vòng tổ tiên → test đỏ.
- [ ] R4.5 (UL9): `PUT` hạn mức tenant cao hơn gói → 422 `limit_above_plan`, không dòng nào đổi.
- [ ] R4.6 (UL10): thiếu `platform.limits.manage` → 403; workspace tenant khác → 404.
- [ ] R4.8: một người hạ trần tenant từ USD 50 xuống USD 10 → áp ngay, audit `limits.policy.set` có `before`,
      `after` trong cùng giao dịch; `PUT` mang `kind` `soft` → 422 `validation_failed`, không dòng nào đổi; `dw_app`
      INSERT một chính sách `kind` `soft` → CHECK từ chối; nới CHECK thành (`hard`, `soft`) → test đỏ.
- [ ] R4.9 (UL15): một người nâng trần từ USD 10 lên USD 50 → 409 `second_person_required`, Hạn mức hiệu lực
      vẫn USD 10; `DELETE` chính sách → 409; gỡ kiểm → test đỏ.
- [ ] R5.1 (UL2): `runs_per_day` của tenant còn đúng 3 lượt, 10 lượt chạy gốc nhận song song → đúng 3 được nhận và
      mở lease, 7 lượt nhận `limit_exceeded`, bộ đếm không vượt trần; gỡ khóa bộ đếm theo thứ tự → test đỏ.
- [ ] R5.2 (UL3): lease còn đủ cho 100 token output → lời gọi mang `max_tokens <= 100`; gỡ kẹp → test đỏ.
- [ ] R5.3 (UL11): lượt chạy chờ duyệt → `reserved` của lượt về 0; resume → giữ lại số đã tiêu qua các
      lease; gỡ nhả → test đỏ.
- [ ] R5.4 (UL6): tiến trình chết giữa lời gọi → sau `expires_at` lease đóng, phần đang bay tính, audit
      `system:reaper`; gỡ `ReapTarget` → test đỏ.
- [ ] R5.5 (UL13): trần mỗi lượt cạn giữa lượt chạy → dừng ở ranh giới lời gọi kế tiếp `limit_exceeded`,
      không hạ ngầm xuống model rẻ hơn; gỡ kiểm ranh giới → test đỏ.
- [ ] R5.6: lượt chạy con của một lượt gốc chạy trên lease của lượt gốc, không có dòng `budget_leases` thứ
      hai và không gọi `admit`.
- [ ] R5.7: với thời hạn 395 và 30 ngày trong tệp chính sách retention, lane `retention_limits` xóa bộ đếm có
      `window_end` 396 ngày trước và lease đóng 31 ngày trước; giữ bộ đếm 394 ngày và lease còn mở; đổi số trong
      tệp thử → lane theo số mới, không sửa mã.
- [ ] R6.5: `ResidencyGate` giả từ chối một lời gọi → `reserved` của lease không đổi, 0 dòng
      `usage_events` cho lời gọi đó.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/ports.py:80-106`; spec: R4.1 (`RunAllowancePort`
  tiền lệ hình port).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/budget.py:60-68`; spec: R5.3 (RunBudgetLedger
  trong tiến trình, thay bằng lease).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:246-264`; spec:
  R5.1 (nhận run ở start và stream, nay thêm lease); ADR-0121 (Accepted) quyết 3-4.

## Comments

- 2026-10-23 (agent): gộp B10b usage-and-limits 04, 05, 06. `needs-info` vì DO-59 (số mặc định gói, đơn
  vị bán) còn mở; người đặt yêu cầu đặt trần riêng cho tenant thí điểm ngay, số của gói quyết trước GA.
  DO-50 quyết tạm theo khuyến nghị (a): kỳ theo múi giờ công ty, chạm trần giữa lượt dừng lượt chạy,
  chỉ run gốc tính vào số run mỗi ngày.
- 2026-10-23 (agent): DO-59.1 có lời đáp cho W1 (Đạt, 23/10/2026), nên `needs-triage`. Áp DO-21.2, DO-21.3,
  D11 phạm vi (siết một người, nới hai người), bảng toàn tenant cho hạn mức và bộ đếm, và cạnh OPS-b chờ
  compliance-pdpl/03 (thứ tự cửa `ResidencyGate` trước `LimitsMiddleware`). agent-lifecycle/04 chờ ticket
  này (DO-21.4).
- 2026-10-24 (agent): áp quyết định của Đạt ngày 24/10/2026: ticket này chỉ trả câu trả lời của
  `LimitsPort.admit` (spec R4.10, R4.11), hình từ chối theo `trigger_kind` là của workflow-engine/04 và ticket đó
  chờ ticket này (A:usage-and-limits:R4.2\~workflow-engine:R5.9); cột khóa ngoại có kiểu cho phạm vi của hạn mức
  (spec R4.12); thời hạn của bộ đếm (13 tháng) và lease (30 ngày) đọc từ tệp retention mà ticket này thêm khóa;
  đăng ký `platform.limits.manage` ở đây theo quy ước của tenant-rbac/01; ba bảng xóa được khi offboarding.
  agent-builder/03 chờ ticket này vì `LimitsMiddleware` thay `RunBudgetMiddleware` trong ngăn xếp mà agent-builder/03
  giữ thứ tự (ADR-0117 (Accepted) quyết 5; cạnh nằm ở ticket đó).
- 2026-10-24 (agent): vòng sửa thứ tư, theo các Quyết định ngày 24/10/2026 của spec: W1 bỏ phạm vi `user` và trần
  đồng thời (rút spec R4.11, UL2 thử bằng `runs_per_day`), `scope_user_id`, `thresholds`, `purposes` sang W2 cùng bên
  đọc; tên cột `scope_*` giữ theo quyết định của Đạt; FK `scope_artifact_id` trỏ `uq_artifacts_tenant_id_id` của
  tenant-config/02; chờ tenant-rbac/02 vì INSERT `platform.limits.manage` nêu `tenant_grantable`; bản tệp retention
  của ticket này đứng giữa ticket 02 và telemetry-and-audit/03.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt c, theo các Quyết định tạm cùng ngày của spec: `kind` chỉ nhận `hard` ở W1,
  `soft` sang W2 cùng cảnh báo ngưỡng, nên lệnh nới ở W1 chỉ còn nâng và gỡ (bước 1, bước 6, tiêu chí R4.8, R4.9); FK
  ghép `scope_workspace_id` nêu đích `uq_workspaces_tenant_id_id` của org-and-principals/01.
