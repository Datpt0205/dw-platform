# 03 — Hạn mức theo chuỗi phạm vi: giữ trước lúc nhận run, quyết toán từng lượt gọi, thu hồi lease mồ côi

Status: ready-for-agent
Blocked by: 01, 02, .claude/plans/studio/workflow-engine/issues/02-cot-run-va-cua-nhan-run.md, .claude/plans/studio/org-and-principals/issues/02-thanh-vien-cap-tenant.md, .claude/plans/studio/compliance-pdpl/issues/03-tuyen-du-lieu-o-model-gateway.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md
Area: studio
Yêu cầu: R3.8, R4.1, R4.4, R4.5, R4.6, R4.8, R4.9, R4.10, R4.12, R4.13, R4.14, R4.15, R4.16, R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.7, R5.8, R5.9, R5.10, R5.11, R6.5, UL2, UL3, UL6, UL8, UL9, UL10, UL11, UL13, UL15, UL17, UL19, UL20

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
   tenant-config/02), mỗi FK `ON DELETE CASCADE` và có index riêng, từ chối dòng trỏ sang công ty khác kể cả với vai
   bỏ qua RLS (spec R4.13); CHECK `num_nonnulls` của hai cột đó bằng 1 với
   đúng cột của `scope_type` khác `tenant` và bằng 0 khi `tenant` (spec R4.12; ADR-0121 (Accepted) quyết 4);
   `metric`, `window_kind` với CHECK trên cặp, bốn cặp của W1 (spec R4.14): (`cost_usd`, `day`), (`cost_usd`, `month`),
   (`tokens`, `month`), (`runs`, `day`), mỗi cặp ứng đúng một cột của `platform.plan_limits` (`cost_usd_per_day`,
   `cost_usd_per_month`, `tokens_per_month`, `runs_per_day`); `kind` CHECK `hard`, giá trị duy nhất ở W1; `limit_value numeric(20,8) CHECK (>= 0)`;
   `version`; `created_by`; UNIQUE NULLS NOT DISTINCT trên `tenant_id`, `scope_workspace_id`, `scope_artifact_id`,
   `metric`, `window_kind`; trigger `updated_at` nhường giá trị lệnh nêu; không có `scope_user_id`, `thresholds`,
   `purposes` và giá trị `soft` của `kind` ở W1, mỗi thứ vào ở W2 cùng bên đọc của nó, Ngoài phạm vi của spec);
   `platform.budget_counters` (khóa chính sáu cột đầu, `CHECK (used >= 0 AND reserved >= 0)`, RLS tenant và
   policy drain); `platform.budget_leases` (`UNIQUE (tenant_id, root_run_id) WHERE state='open'`, index từng phần
   `expires_at WHERE state='open'`, `purpose` CHECK (`run`, `eval_offline`, `ingestion`, `retrieval`, `builder_assist`;
   ba giá trị sau là lease của thao tác không thuộc lượt chạy mà ticket 04 mở, `root_run_id` khi đó là id của thao tác,
   cột không FK), RLS tenant và cùng policy drain, vì reaper và lane `retention_limits` quét mọi công
   ty dưới `app.worker_drain`). Cùng migration: `max_tokens_per_run` của `platform.plan_limits` là tổng token vào và ra
   của một lượt (ticket 01 M2), seed nâng từ 120000 lên 200000 bằng `UPDATE` cho mọi gói đang mang 120000, để profile
   `gateway` (`configs/models/gateway.yaml:75`) không bị siết ngầm. Ba bảng có policy `tenant_isolation_*` và DELETE cho `dw_app`, nên lane
   `offboarding` xuất rồi xóa chúng như bảng thường (spec R3.8; studio-skeleton:R4.3). Cùng migration: đăng ký
   khóa `platform.limits.manage` trong `platform.permissions` của tenant-rbac/01 (nhãn tiếng Việt, `scope_kind`
   `tenant`, `risk` `elevated` theo bảng phân loại của ticket đó); INSERT nêu mọi cột NOT NULL của bảng lúc đó, gồm
   `risk` của tenant-rbac/01 và `tenant_grantable` (`true`) của tenant-rbac/02, ticket này chờ ticket đó. Cùng thay
   đổi: thêm hai mảnh retention theo định dạng của telemetry-and-audit:R5.6,
   `configs/policies/retention.d/platform.budget_counters.yaml` (`days: 395` sau `window_end`, `purger: row_delete`) và
   `configs/policies/retention.d/platform.budget_leases.yaml` (`days: 30` sau khi đóng, `purger: row_delete`), số tạm
   UNVERIFIED; không ticket nào khác chờ hai mảnh này và ticket này không chờ ticket nào vì mảnh (H-1).
2. `EffectiveLimits.for_admission(run_context, artifact)` gộp gói, tenant, workspace và tổ tiên, agent
   hoặc quy trình (phạm vi người dùng ở W2), đọc trong chính giao dịch của `admit` và của lần nạp thêm, không cache
   trong tiến trình: `PUT` chạy ở api còn `admit` ở worker, nên một cache xóa khi ghi không thấy lần hạ trần ở tiến trình
   kia (spec R4.8 "áp ngay"; failure-modes #7). Ranh giới kỳ của bộ đếm lấy từ
   `window_for(tenant_id, window_kind, at)` mà ticket 02 dựng trong `dw_usage` (DO-50; ADR-0121 (Accepted) quyết 9), chủ
   duy nhất của ranh giới; ticket này không viết bản thứ hai.
3. `LimitsPort` (runtime khai, `dw_usage` đáp): `admit`, `resume`, `RunLease.before_call(estimate) -> CallPermit(max_output_tokens, call_id, occurred_at)`,
   `after_call`, `release(reason)`. Nhận run một giao dịch, khóa bộ đếm theo thứ tự chuẩn (scope rank
   rồi `scope_id`); "còn đủ" là còn lớn hơn 0 với tiền và token, còn ít nhất 1 với `runs`, phần còn lại của một phạm vi
   là `limit - used - reserved` của bộ đếm kỳ hiện tại; lease giữ `min` của phần còn lại qua mọi phạm vi có chính sách và
   trần mỗi lượt (`max_cost_usd_per_run`, `max_tokens_per_run` đã kẹp, ticket 04), cộng vào `reserved` của từng bộ đếm
   trong cùng giao dịch (spec R5.8; ADR-0121 (Accepted) quyết 5); hết kỳ → `QuotaExceededError` `limit_exceeded` kèm
   `metric`, `scope_type`, `window`, `limit`, `used`, `resets_at`, không mở lease và không đổi bộ đếm (spec R4.10); đọc
   chính sách hay bộ đếm lỗi → từ chối `limits_unavailable` (không bao giờ nhận lượt khi không biết hạn mức), mã mà bảng
   từ chối của workflow-engine xử như `control_state_unavailable`. `before_call(estimate)`: ước tính là token vào đếm được
   nhân giá vào cộng `max_tokens` yêu cầu nhân giá ra (Bảng giá của ticket 02); phần lease còn lại không đủ → nạp thêm
   trong một giao dịch khóa bộ đếm theo thứ tự chuẩn, tới `min` của phần còn lại qua các phạm vi và trần mỗi lượt còn
   lại; vẫn không đủ cho chi phí đầu vào → `limit_exceeded` trước lời gọi; đủ → `max_output_tokens` là phần còn lại sau
   chi phí đầu vào chia giá ra (spec R5.2, R5.8). Mỗi tiến trình đang chạy một lượt của cây gốc giữ một tác vụ nhịp 60 giây cho lease
   chung: ghi `heartbeat_at`, đặt `expires_at = now() + 300 giây`, cuộn `settled_* - rolled_*` vào `used` và hạ `reserved`
   tương ứng bằng một câu lệnh dưới khóa dòng lease, nên hai nhịp đồng thời không cuộn hai lần (spec R5.9; gate 4/11/2026
   (m)). Bộ đếm chỉ có ở phạm vi có chính sách hay Trần của gói; ở cấp công ty một dòng bộ đếm phục vụ cả Trần của gói lẫn
   chính sách công ty cùng cặp, giới hạn là số nhỏ hơn, câu trả lời từ chối nêu `scope_type` `tenant` và `limit_source`
   `plan` hay `policy`. Phần đã tiêu của một lượt qua các lần dừng là tổng `settled_*` của mọi lease của `root_run_id`; audit `limits.refused` một lần cho mỗi (lượt, kỳ), không mỗi lần nhận lại, đứng tên
   `system:<lane>` của lane nhận lượt, hay actor của lượt trên đường inline cũ; không đếm chỗ đồng thời ở W1
   (trần đồng thời là W2, spec R4.11 đã rút); audit `limits.refused`; metric `dw_limit_refusals_total`. Ticket này
   chỉ trả câu trả lời; hình từ chối theo `trigger_kind` (đặt `failed`, giữ `queued` tới `resets_at`) là của làn
   `studio_runs` trong workflow-engine/04 (workflow-engine:R5.9, workflow-engine:R5.10, workflow-engine:R5.11),
   ticket đó chờ ticket này; không 429 (429 chỉ còn ở đường chạy inline cũ `langgraph_runner.py:246-264`).
4. Runner, do làn `studio_runs` gọi lúc dispatch, là chỗ duy nhất gọi `admit`: `_require_allowance` →
   `limits.admit` cho mọi lượt gốc, kể cả đường chạy inline cũ và lane của worker đang gọi `_require_allowance` hôm
   nay, vì bước 7 gỡ `RunAllowancePort`. Theo các lời đáp đã xác nhận của ADR-0121 (Accepted) (DO-50 (a), DO-43,
   DO-29.2 (a)): chỉ lượt gốc `purpose` `run` tính vào `runs`; `test_run` (lượt ở `run_mode` `test` hay `simulate`),
   `builder_assist` và `eval_offline` tính vào trần tiền và token của công ty mà không tính `runs`; công ty trả Lượt kiểm
   định do mình xin, nền tảng trả lần kiểm định lại do nền tảng gây ra (lease đó không tính vào trần nào của công ty); token
   BYOM chỉ tính vào chính sách công ty đặt, không vào Trần của gói (ticket 02 M7; gate 4/11/2026 (h), sửa ở lượt xác
   nhận). `runs` tính đúng một lần mỗi `root_run_id`, ở lần `admit` mở lease đầu tiên của gốc: `admit` hay `resume` của
   một gốc đã có lease (tiến trình chết rồi lượt được nhận lại, hai lượt con tiếp tục cùng lúc) gắn vào lease đang mở nếu
   có, mở lease mới nếu không, không tính `runs` lần hai (gate 4/11/2026 (l)); lượt chạy con dùng lease của lượt gốc, lần thử của Lượt kiểm định hay của Kiểm định thử dùng lease
   của Lượt kiểm định hay Kiểm định thử chứa nó, không gọi `admit` (ADR-0113 (Accepted) quyết 9; spec R5.6); kết thúc
   → `release`; `release(paused)` chỉ khi không lượt nào của cây gốc đang chạy (lượt con chờ người trong khi lượt anh em
   hay lượt gốc còn chạy không nhả lease chung; lượt gốc chờ một `child_run` đang chạy cũng không nhả); `limits.resume`
   do runner gọi lúc nó tiếp tục chạy một lượt, không trong giao dịch của `ApproveAndResumeService`, vì quyết định chỉ đưa
   lượt về `queued` (ADR-0113 (Accepted) quyết 3, 4); `resume` mở lease mới không đếm `runs` lần hai, và từ chối bằng
   cùng câu trả lời của `admit`, mà bên gọi xử như lần nhận; trên đường inline cũ, runner gọi `release(paused)` lúc lượt
   dừng và `resume` khi `ApproveAndResumeService` tiếp tục nó, `resume` từ chối thì lượt `failed` `limit_exceeded` còn
   quyết định duyệt vẫn ghi, người quyết nhận câu trả lời thường và thấy lượt kết thúc qua trạng thái của lượt; bỏ `budget.forget`; số run mỗi ngày không tính lại khi resume (giữ quy tắc `langgraph_runner.py:255-257`).
   `LimitsMiddleware` thay `RunBudgetMiddleware`: permit mỗi lời gọi, đặt `max_tokens`, từ chối
   `LimitExceededError`; đứng sau `ResidencyGate` của compliance-pdpl/03, nên một lời gọi bị cổng lộ trình từ chối
   không giữ tiền và không ghi Bản ghi sử dụng (spec R6.5).
5. `ReapTarget(name="budget_leases")` trên lane `reaper` (hôm nay không đăng ký gì): quét lease mở có `expires_at` đã
   qua dưới `app.worker_drain`, đặt tenant theo từng sự kiện, đóng lease `expired`; mỗi lời gọi đang bay ghi ở lease lúc
   `before_call` (`call_id`, `occurred_at`) thành một dòng `unsettled_estimate` mang đúng `(id, occurred_at)` đó, nên
   `after_call` đến muộn của tiến trình còn sống gặp khóa của Sổ sử dụng, trả `False`, ghi log và metric
   `dw_limit_late_settlements_total`, không tính hai lần; `before_call` trên lease đã đóng → `limit_exceeded` với
   `details.reason` `lease_expired` (spec R5.9); cuộn bộ đếm; audit
   `limits.lease.expired` bằng `lane_audit_event` và `append_across_tenants`. Lane `retention_limits` đọc thời
   hạn của mảnh `platform.budget_counters` và mảnh `platform.budget_leases` trong tập mảnh retention đang ghim, qua bộ
   đọc tập mảnh của mô hình chính sách (telemetry-and-audit:R5.13, dựng ở telemetry-and-audit/01, mà ticket này chờ qua
   ticket 02) (bộ đếm quá `window_end` cộng 395 ngày, lease đóng quá 30 ngày, chỉ khi gốc của nó đã ở trạng thái cuối, để phần đã tiêu của một lượt còn chờ không bị xóa;
   spec R5.7), không ghi cứng số nào trong
   mã; thiếu mảnh thì không xóa gì và báo lỗi cấu hình. Sửa `test_only_the_platform_lanes_are_wired`.
6. Route `GET /api/v1/limits` (`platform.usage.read`): mỗi chính sách kèm Hạn mức hiệu lực, bộ đếm của kỳ
   hiện tại và giờ đặt lại (không route `/api/v1/usage/limits` riêng).
   `PUT /api/v1/limits/{scope_type}/{scope_id}/{metric}/{window_kind}` với thân `{limit_value, kind}`, một dòng chính sách
   mỗi đường dẫn, `If-Match` là `version` của đúng dòng đó (gate 4/11/2026 (n)); `PUT` tạo một chính sách mới giữa kỳ đặt
   `used` của bộ đếm kỳ hiện tại bằng tổng `platform.usage_events` của phạm vi đó trong kỳ, trong cùng giao dịch, nên một
   trần đặt giữa kỳ không đếm từ 0 (gate 4/11/2026 (o)); và `DELETE` cùng đường dẫn (`platform.limits.manage`, `Idempotency-Key`; `{scope_type}` nhận `tenant`, `workspace`, `agent`,
   `workflow`, còn `user` là W2): `{scope_id}` của `tenant` phải bằng công ty của ngữ cảnh truy cập (khác → 404, không
   bao giờ lấy công ty từ đường dẫn; CLAUDE.md, Per-tenant artifacts), của `agent` hay `workflow` phải là thành phần
   cùng loại (khác loại → 422 `scope_kind_mismatch`, công ty khác → 404); `PUT` lên chính sách đã có và `DELETE` đòi
   `If-Match` mang `version` của dòng (thiếu → 428, cũ → 412, app-standards/03), giao dịch khóa dòng `FOR UPDATE` rồi so
   lỏng hay chặt với giá trị đã khóa, `version` tăng mỗi lần đổi (spec R4.15); metric hay kỳ ngoài bốn cặp → 422
   `validation_failed` với con trỏ (spec R4.14); hạ hay đặt mới áp ngay với một người, audit
   `limits.policy.set` (`before`, `after`) trong cùng giao dịch; nâng hay gỡ → 409
   `second_person_required`, không đổi dòng nào (D11; nới qua tenant-config là W2); cao hơn Trần của gói →
   422 `limit_above_plan`; `kind` khác `hard` → 422 `validation_failed` với con trỏ tới `kind` (app-standards:R1.3),
   vì `soft` là W2. Màn Cấu hình hạn mức (antd Form, Table) ở cấp tenant và workspace, hiện Trần của
   gói và Hạn mức hiệu lực; W1 chỉ có thao tác siết. Màn `/usage` của ticket 02 thêm antd Progress cho mỗi hạn mức, đọc
   `GET /api/v1/limits` (spec, Màn hình).
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
- [ ] R4.13 (UL17): bằng vai migrator, INSERT dòng `platform.limit_policies` của tenant A có `scope_workspace_id` là
      workspace của tenant B, hay `scope_artifact_id` là thành phần của B → FK ghép từ chối, không ghi; cùng id của
      tenant A → nhận; đổi một FK ghép sang FK một cột → test đỏ.
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
- [ ] R5.7: với thời hạn 395 và 30 ngày trong hai mảnh retention, lane `retention_limits` xóa bộ đếm có
      `window_end` 396 ngày trước và lease đóng 31 ngày trước; giữ bộ đếm 394 ngày và lease còn mở; đổi số trong
      mảnh thử → lane theo số mới, không sửa mã; gỡ mảnh `platform.budget_leases` khỏi tập thử → lane không xóa lease
      nào và báo lỗi cấu hình.
- [ ] R6.5: `ResidencyGate` giả từ chối một lời gọi → `reserved` của lease không đổi, 0 dòng
      `usage_events` cho lời gọi đó.
- [ ] R4.14 (UL19): `PUT` với metric `cost_usd_per_week` hay cặp (`tokens`, `day`) → 422 `validation_failed`, không dòng
      nào; `dw_app` INSERT cặp ngoài bốn cặp → CHECK từ chối; `PUT` (`tokens`, `month`) cao hơn `tokens_per_month` của gói
      → 422 `limit_above_plan`; cột gói NULL → nhận.
- [ ] R4.16 (UL19): `dw_app` INSERT cặp (`tokens`, `day`) thẳng vào `platform.limit_policies` → CHECK từ chối; nới CHECK →
      test đỏ.
- [ ] R4.15 (UL20): hai `PUT` hạ cùng một trần từ 50, một về 30 một về 40, cùng `If-Match` của version 1 → một nhận, một
      412, trần cuối là giá trị của lần nhận; `PUT` không `If-Match` lên chính sách đã có → 428; gỡ khóa `FOR UPDATE` và
      kiểm `If-Match` → lần sau ghi 40 lên 30, test đỏ.
- [ ] R4.8: API hạ trần từ 50 xuống 10, rồi `admit` ở một tiến trình khác (subprocess, kết nối mới) → dùng 10; thêm cache
      trong tiến trình vào `EffectiveLimits` → test đỏ.
- [ ] R4.6: `PUT /api/v1/limits/tenant/{id công ty khác}` → 404, không dòng nào; `PUT /api/v1/limits/agent/{id quy trình}`
      → 422 `scope_kind_mismatch`.
- [ ] R5.8 (UL2): tháng còn USD 1, trần mỗi lượt USD 2 → nhận, lease giữ USD 1; còn USD 0 → `limit_exceeded`; 10 lượt
      gốc song song khi tháng còn USD 3 và trần mỗi lượt USD 1 → tổng `reserved` không vượt 3; lời gọi có chi phí đầu vào
      ước tính USD 0.4 khi lease còn 0.3 và kỳ còn → nạp thêm rồi chạy.
- [ ] R5.10 (UL3): lời gọi có chi phí đầu vào ước tính USD 0.4 khi lease còn 0.3 và kỳ đã cạn → `limit_exceeded` trước lời
      gọi, 0 dòng `usage_events`; gỡ kiểm chi phí đầu vào → lời gọi chạy, test đỏ.
- [ ] R5.9 (UL6): lease có nhịp → `expires_at` dời mỗi 60 giây, reaper không đóng nó dù lời gọi kéo 6 phút (đồng hồ
      giả); nhịp dừng 5 phút → reaper đóng `expired`, dòng `unsettled_estimate` mang `(id, occurred_at)` của lời gọi đang
      bay; lượt cũ gọi tiếp → `limit_exceeded` `lease_expired`.
- [ ] R5.11 (UL6): `after_call` muộn của lời gọi mà reaper đã ghi `unsettled_estimate` → `False`, metric
      `dw_limit_late_settlements_total` tăng, lời gọi đó có đúng một dòng trong `usage_events`; cho `after_call` ghi dòng
      thứ hai → test đỏ.
- [ ] R5.3: lượt con chờ người khi lượt anh em còn chạy → lease không nhả; cả cây chờ → nhả; người duyệt → runner gọi
      `resume` lúc nhận lại, không trong giao dịch quyết định; kỳ cạn lúc tiếp tục → cùng `limit_exceeded` như `admit`,
      `runs` không tăng.
- [ ] R4.10: đọc `platform.limit_policies` lỗi (bản giả ném) → `limits_unavailable`, không lease, bộ đếm không đổi.
- [ ] R5.1 (UL2): lượt gốc ở `run_mode` `test`, lease `builder_assist` hay `eval_offline` → `runs` không tăng, trần tiền
      tăng; lần kiểm định lại do nền tảng gây ra → không bộ đếm nào của công ty đổi; token BYOM → chỉ chính sách của công ty
      tính, Trần của gói không; tiến trình chết, lượt được nhận lại khi lease cũ còn mở → gắn vào lease đó, `runs` không
      tăng; đếm lượt `test` vào `runs` → test đỏ.
- [ ] R5.9: hai tiến trình của cùng một cây nhịp cùng lúc → `used` tăng đúng phần đã quyết toán một lần; lượt gốc chờ
      một `child_run` chạy ở worker khác hơn 5 phút → lease không bị reaper đóng.
- [ ] R4.8: tháng đã tiêu USD 40 ở workspace W, đặt chính sách USD 10 cho W → lượt kế tiếp ở W bị `limit_exceeded`; đặt
      `used` về 0 khi tạo → test đỏ.
- [ ] R5.4: reaper dưới `app.worker_drain` thấy lease quá hạn của hai công ty và đóng cả hai; gỡ policy drain của
      `platform.budget_leases` trong migration thử → reaper không thấy lease nào, test đỏ.
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
- 2026-10-24 (agent): vòng sửa thứ tư, lượt d, theo các Quyết định tạm cùng ngày của spec: hai FK ghép phạm vi có ca âm
  chéo công ty (spec R4.13, UL17; CLAUDE.md, Tenancy and authorization), bước 1 và tiêu chí R4.13; bước 4 nói lần thử
  của Kiểm định thử cũng dùng lease của Kiểm định thử chứa nó, không gọi `admit` (spec R5.6; agent-lifecycle:R4.8).
- 2026-10-26 (agent): vòng 4, lượt h, theo H-1: thời hạn của bộ đếm và lease là hai mảnh
  `configs/policies/retention.d/<schema>.<table>.yaml` thêm trong cùng thay đổi tạo bảng, thay bản tệp retention trong
  chuỗi ticket (bước 1); lane `retention_limits` đọc hai mảnh qua bộ đọc tập mảnh của telemetry-and-audit/01 (bước 5,
  tiêu chí R5.7 thêm ca thiếu mảnh). Không đổi cạnh: telemetry-and-audit/01 đã là tổ tiên qua ticket 02 (H-27).
- 2026-10-26 (agent): theo V4.31 và V4.37, Lượt kiểm định và lease `eval_offline` của nó nay ở agent-lifecycle/06, tách từ
  agent-lifecycle/04; ticket chờ ticket này là agent-lifecycle/06 (cạnh đã có ở ticket đó), thay vế "agent-lifecycle/04 chờ
  ticket này" của dòng 2026-10-23 ở trên.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): theo gate của ticket 02: `window_for` dời sang ticket 02 (lane cuộn
  của ticket đó là bên dùng đầu), ticket này dùng lại (bước 2); Progress cho hạn mức trên màn `/usage` dời từ ticket 02
  sang đây cùng `GET /api/v1/limits` (bước 6). Nếu sai thì: `window_for` về lại ticket này và lane cuộn của ticket 02
  cắt ngày theo UTC tới khi ticket này xong.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk, ba
  subagent, vì ticket thêm migration, route và màn) trên `0baced0`, đọc cùng mã của ticket 02 (`522bd4e`…`e6a7c6f`):
  `check_plans.py` 24 Đạt; 0 CRITICAL, 11 HIGH, sửa theo khuyến nghị; mỗi quyết định cùng `Nếu sai thì:` ở mục Quyết
  định của spec, dòng 4/11/2026 (a)-(k): cỡ lease, ngưỡng nhận, nạp thêm và nhịp (ADR-0121 (Accepted) quyết 5 đã nói,
  ticket chưa chép); chi phí đầu vào kiểm trước lời gọi; `resume` ở runner theo ADR-0113 (Accepted); lease chung không
  nhả khi còn nhánh chạy; bỏ cache trong tiến trình; `PUT` khóa dòng và đòi `If-Match`, `version` có bên đọc; bốn cặp
  metric và kỳ có CHECK; mọi lượt gốc tính, `payer` theo tuyến (ticket 02 M7); `max_tokens_per_run` là tổng, seed 200000
  (ticket 01 M2); policy drain trên `budget_leases`; `{scope_id}` của `tenant` từ ngữ cảnh, loại thành phần khớp. Lượt
  xác nhận chạy sau, ghi ở dòng kế.
- 2026-11-04 (agent): MEDIUM, chưa sửa: (M1) W1 không có đường nới, nên gõ nhầm trần về 0 chặn công ty tới W2: khôi phục
  là việc của người vận hành bằng một lệnh trên database, có audit tay, ghi ở trang vận hành; (M2) phát lại
  `Idempotency-Key` của `PUT` sau một lần hạ khác trả câu trả lời đã lưu theo app-standards/02, `If-Match` mới là chỗ
  chặn ghi đè; (M3) lượt kéo qua ranh giới kỳ quyết toán vào `counter_keys` ghi trên lease lúc mở, đổi múi giờ giữa kỳ
  không cuộn lại (ticket 02 M1); (M4) `budget_leases` có `workspace_id` mà policy chỉ theo công ty: đúng, vì reaper và
  quyết toán đọc theo công ty, `test_rls_coverage.py` không đòi bảng có `workspace_id` phải hẹp theo workspace; (M5)
  `code-quality.md` dùng `RunAllowancePort` làm ví dụ, bước 7 gỡ port đó: sửa ví dụ sang `LimitsPort` cùng commit
  (`.claude/rules`, không thuộc khu này); (M6) ticket 02 M1 vẫn đứng: dòng `unsettled_estimate` qua nửa đêm hôm sau nằm
  ngoài hai ngày lane cuộn tính lại.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (builder check mới trên bản đã sửa): 1 CRITICAL do chính
  bản sửa (h) gây ra, trái các lời đáp đã xác nhận của ADR-0121 (Accepted) (lượt thử, dựng có AI và kiểm định không tính
  `runs`; công ty trả kiểm định của mình, nền tảng trả lần kiểm định lại; BYOM chỉ tính chính sách công ty đặt): sửa (h)
  theo ADR. Cùng 5 HIGH, sửa: (l) `runs` tính một lần mỗi gốc, lượt nhận lại hay hai lượt con tiếp tục gắn vào lease đang
  mở; (m) ai giữ nhịp khi gốc chờ lượt con ở worker khác: mọi tiến trình của cây, cuộn bằng một câu lệnh dưới khóa dòng;
  (n) đường dẫn `PUT`/`DELETE` thiếu `metric`, `window_kind`; (o) chính sách đặt giữa kỳ đếm từ 0; (p) Trần của gói và
  chính sách công ty dùng chung dòng bộ đếm. Sửa luôn vì rẻ: lease đóng của lượt còn chờ không bị lane retention xóa;
  đường inline của `resume`; `limits.refused` một lần mỗi (lượt, kỳ). Sửa của lượt này không có người đọc mới: nhận rủi
  ro (agent, theo ủy quyền 31/10/2026), mỗi sửa có tiêu chí đỏ được. Nếu sai thì: lỗi lộ ra khi dựng, ghi ở đây. MEDIUM để
  lại: (M7) chính sách phạm vi `agent` chỉ kiểm khi agent đó là gốc; một Bước `ai.agent` của quy trình chạy agent X trên
  lease của quy trình, nên trần riêng của X không chặn nó ở W1 (ADR-0121 (Accepted) quyết 4: lượt con dùng lease của
  gốc); (M8) `payer` `tenant` của kiểm định trên model nền tảng mang nghĩa rộng hơn glossary (BYOM): cờ cho
  `mattpocock-skills:domain-modeling`, không sửa `docs/platform/CONTEXT.md` ở lượt này.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
