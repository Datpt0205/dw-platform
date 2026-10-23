# Sổ sử dụng, bảng giá và hạn mức

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Studio cần đo và chặn chi tiêu ở mức công ty, workspace, agent, quy trình và người dùng, việc mà một
tổng theo ngày của cả tenant không làm được. Lát này đưa lại Sổ sử dụng theo lượt gọi (D6) làm nguồn
cho hạn mức, màn Mức độ sử dụng và đối soát; đặt một Bảng giá theo ngày hiệu lực làm chủ duy nhất của
"cái này tốn bao nhiêu"; và biến mọi Hạn mức cứng thành Khoản giữ trước bằng lease Postgres mở lúc nhận
lượt chạy, kẹp `max_tokens` từng lời gọi, quyết toán từng lượt gọi (ADR-0121 (Proposed)). W1 phục vụ
YC76, YC77, YC78 và một chủ cho số của gói; YC44 (giới hạn tốc độ nguồn dữ liệu) và YC79 (hạn mức theo
người và mục đích) thuộc W2.

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- Danh mục gói là một dict trong mã: `DEFAULT_PLANS` với `runs_per_day` 20, 200, 2000
  (`packages/python/dw_platform/src/dw_platform/application/entitlement.py:13-36`), và một bản sao trong
  database `platform.plans (plan_id, name, features, quotas)`
  (`db/migrations/sql/0001_platform_baseline.sql:332-337`); `has_feature` đọc cả hai
  (`packages/python/dw_platform/src/dw_platform/application/entitlement.py:45-49`). Ràng buộc: đây là
  drift `failure-modes.md` #2; W1 dời số về một chủ.
- `RunAllowancePort` do runtime khai, platform đáp
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/ports.py:80-106`); `DailyAllowance` đếm run và
  chi theo ngày UTC, không giao dịch, chỉ ở `start` và `stream` chứ không ở `resume`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/allowance.py:10-15`,
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:246-264`). Thiếu:
  không giữ trước tiền; `resume` không kiểm.
- Cửa vòng: `RuntimeSeam.gateway` lộ `RoutingModelGateway` thô và `chat_models` là factory trần
  (`apps/api/src/dw_api/bootstrap/container.py:104`); `metered_invoke` không có trần và, không meter, thì
  không đo gì (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_usage.py:203-232`).
  Thiếu: mọi cửa chạm model phải là kiểu có đo.
- `RunBudgetLedger` là dict trong tiến trình, chỉ chặn input token và tiền, giải phóng chỉ ở trạng thái
  cuối, không ở lúc tạm dừng
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/budget.py:60-68`). Ràng buộc: thay bằng
  lease liên tiến trình trong cùng lát.
- Giá nằm trên route: `price_per_million_input/output` và `ModelBudgets(max_cost_usd_per_run=2.0)`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py:54-55`), không cache, reasoning,
  bậc hay ngày hiệu lực. Thiếu: một Bảng giá theo ngày hiệu lực.
- `platform.model_usage_ledger` đã bị gỡ ở revision `aefe7c1f5d9b`
  (`db/migrations/versions/0013_drop_model_usage_ledger.py:1-3`), thay bằng
  `platform.tenant_daily_spend_guard` "chỉ là cơ chế, không có bên đọc, không phải sổ theo lượt gọi"
  (`db/migrations/versions/2b5ff2bceb06_tenant_daily_spend_guard.py:15-18`). Ràng buộc: W1 đảo việc gỡ,
  kèm bên đọc từ ngày đầu (DO-21 cần Đạt ký).
- `platform.ensure_time_partitions` chỉ biết một parent `ARRAY['audit_events']`
  (`db/migrations/sql/0013_partition_maintenance.sql:123`). Ràng buộc: Sổ sử dụng phân vùng vào mảng đó
  cùng ENABLE/FORCE RLS và thu hồi ghi.
- `platform.tenants.timezone` có nhưng không hàm cửa sổ nào đọc
  (`db/migrations/sql/0001_platform_baseline.sql:407`). Ràng buộc: một hàm `window_for` đọc nó cho kỳ
  tính (DO-50).
- Limiter API là cửa sổ cố định 60 giây theo băm của bearer chưa xác minh
  (`apps/api/src/dw_api/middleware/rate_limit.py:36-41`). Ràng buộc: Valkey chỉ giữ trạng thái tốc độ
  (W2); tiền và đồng thời ở Postgres.

## Mục tiêu

### R1 — Một chủ cho số của gói dịch vụ

Số giới hạn của một Gói dịch vụ nằm một chỗ trong database, không còn bản sao trong mã (YC77;
ADR-0121 (Proposed) quyết 6).

- R1.1 KHI một bên hỏi giới hạn của một Gói dịch vụ, `PlanCatalogPort` PHẢI đọc từ `platform.plan_limits`
  làm nguồn duy nhất, không từ một dict danh mục gói trong mã.
- R1.2 NẾU một Gói dịch vụ không có dòng `platform.plan_limits`, THÌ `PlanEntitlementService` PHẢI từ
  chối lượt chạy (đóng khi thiếu), không hiểu NULL-thiếu-dòng thành "không giới hạn".
- R1.3 NẾU `dw_app` ghi `platform.plan_limits`, THÌ PostgreSQL PHẢI từ chối, vì danh mục chỉ do migration
  ghi.
- R1.4 KHI một trần mỗi lượt chạy của gói được đọc, `platform.plan_limits` PHẢI trả một giá trị khác
  NULL (trần mỗi lượt là NOT NULL; `max_steps_per_run` trong 1..500, 1 thì nhận, 501 thì migration từ
  chối).

### R2 — Bảng giá theo ngày hiệu lực là chủ duy nhất của giá

Mọi Thao tác tính phí được định giá bởi một Bảng giá có phiên bản, ghim trong release manifest, và lịch
sử không bị định lại giá (YC76; ADR-0121 (Proposed) quyết 2).

- R2.1 KHI một Thao tác tính phí cần giá, `PriceBook.price` PHẢI trả chi phí `Decimal`, phiên bản Bảng
  giá và id mục giá từ mục có `effective_from` muộn nhất không muộn hơn thời điểm lời gọi.
- R2.2 NẾU bộ nạp Bảng giá gặp hai mục chồng thời gian cùng khóa, một loại sử dụng lạ hay một giá âm,
  THÌ bộ nạp PHẢI từ chối và không nạp Bảng giá.
- R2.3 NẾU ở profile đã triển khai (`settings.is_deployed`) một tuyến model nền tảng trả phí không có
  mục giá, THÌ dịch vụ khởi động PHẢI từ chối khởi động.
- R2.4 KHI Bảng giá đổi giá một model từ một ngày, một Bản ghi sử dụng đã quyết toán PHẢI giữ nguyên
  `price_book_version` và chi phí cũ của nó.

### R3 — Sổ sử dụng theo lượt gọi và màn Mức độ sử dụng

Mỗi lượt gọi model ghi đúng một Bản ghi sử dụng gắn công ty, workspace, lượt chạy, agent hoặc quy trình,
mục đích và bên trả phí; màn Mức độ sử dụng đọc chính sổ này (YC76; ADR-0121 (Proposed) quyết 1).

- R3.1 KHI một lượt gọi model (chat, có cấu trúc, embedding) kết thúc, `UsageLedgerPort.settle` PHẢI ghi
  đúng một Bản ghi sử dụng mang `tenant_id`, `workspace_id`, `run_id`, `root_run_id`, `artifact_kind`,
  `artifact_id`, `artifact_version`, `purpose`, `payer` và `price_book_version`.
- R3.2 KHI cùng một `(id, occurred_at)` được quyết toán lại, `platform.usage_events` PHẢI giữ đúng một
  dòng (`INSERT ... ON CONFLICT DO NOTHING`).
- R3.3 NẾU nhà cung cấp không trả số token dùng, THÌ `UsageLedgerPort.settle` PHẢI ghi `cost_source`
  `estimated` với chi phí ước tính, không ghi 0.
- R3.4 NẾU `dw_app` UPDATE hay DELETE trên `platform.usage_events` hay một phân vùng của nó, THÌ
  PostgreSQL PHẢI từ chối, vì sổ chỉ thêm.
- R3.5 KHI người giữ `usage.read` mở `GET /api/v1/usage/summary`, màn Mức độ sử dụng PHẢI đọc tổng từ
  bảng cuộn của `platform.usage_events` trong tập workspace được phép, với tổng một ngày bằng đúng tổng
  `platform.usage_events` của ngày đó theo `window_for`.
- R3.6 NẾU công ty khác đọc Sổ sử dụng của công ty này qua tên phân vùng hay route, THÌ PostgreSQL và
  API PHẢI trả 0 dòng hoặc 404.

### R4 — Hạn mức là chính sách trên một chuỗi phạm vi, chặn ở cửa nhận lượt chạy

KHI một lượt chạy xin bắt đầu mà phần còn lại của một Hạn mức cứng trong Chuỗi phạm vi hạn mức không đủ,
cửa nhận lượt chạy từ chối, không gọi model và giữ sự kiện đã nhận (YC77; ADR-0121 (Proposed) quyết 3).

- R4.1 KHI một lượt chạy xin bắt đầu, cửa nhận lượt chạy PHẢI kiểm mọi phạm vi có chính sách trong Chuỗi
  phạm vi hạn mức (gói, công ty, workspace và tổ tiên, agent hoặc quy trình, người dùng, lượt chạy) và
  chỉ cho qua khi mọi phạm vi có chính sách đều còn đủ.
- R4.2 NẾU phần còn lại của một Hạn mức cứng không đủ lúc nhận một lượt chạy tương tác, THÌ cửa nhận lượt
  chạy PHẢI từ chối với 429 `limit_exceeded` kèm `metric`, `scope_type`, `window`, `limit`, `used`,
  `resets_at`, không gọi model nào.
- R4.3 NẾU phần còn lại không đủ lúc nhận một lượt chạy do trình kích hoạt, THÌ cửa nhận lượt chạy PHẢI
  giữ lượt chạy ở hàng đợi tới khi kỳ tính đặt lại hay hạn mức được nâng, không bỏ sự kiện.
- R4.4 NẾU một workspace con đặt trần cao hơn phần còn lại của cha, THÌ cửa nhận lượt chạy PHẢI vẫn áp
  trần của cha (phạm vi cha có chính sách thì phải qua).
- R4.5 NẾU người giữ `limits.manage` đặt một Hạn mức cao hơn Trần của gói, THÌ API hạn mức PHẢI trả 422
  `limit_above_plan` và không đổi dòng nào.
- R4.6 NẾU người gọi thiếu `limits.manage`, hoặc nhắm workspace của công ty khác, THÌ API hạn mức PHẢI
  trả 403 hoặc 404 và không đổi gì.

### R5 — Hạn mức cứng giữ trước bằng lease, quyết toán từng lượt gọi, thu hồi lease mồ côi

Tiền và token được giữ trước bằng một lease mở lúc nhận lượt chạy, mỗi lời gọi kẹp `max_tokens` theo
phần lease còn lại và quyết toán idempotent, và lease của lượt chạy chết được thu hồi (YC77, YC78;
ADR-0121 (Proposed) quyết 4).

- R5.1 KHI nhận một lượt chạy, `LimitsPort.admit` PHẢI khóa các bộ đếm theo thứ tự chuẩn và mở đúng một
  lease mở cho mỗi lượt chạy gốc, trong một giao dịch.
- R5.2 KHI một lời gọi model sắp chạy, `RunLease.before_call` PHẢI đặt `max_tokens` của lời gọi không
  vượt phần lease còn lại cho phép.
- R5.3 KHI một lượt chạy tạm dừng chờ phê duyệt hay việc người rồi tiếp tục, `LimitsPort` PHẢI nhả phần
  `reserved` lúc dừng và lấy lại lease lúc tiếp tục sao cho số đã tiêu qua các lease được giữ nguyên.
- R5.4 NẾU một tiến trình chết giữa lời gọi, THÌ một `ReapTarget` PHẢI đóng lease quá `expires_at`, ghi
  một dòng `unsettled_estimate` cho phần đang bay, cuộn bộ đếm, và audit `limits.lease.expired` với actor
  `system:reaper`.
- R5.5 TRONG KHI một trần mỗi lượt chạy đã cạn giữa lượt chạy, lượt chạy PHẢI dừng ở ranh giới lời gọi
  kế tiếp với `limit_exceeded`, không hạ ngầm xuống model rẻ hơn.

### R6 — Mọi cửa chạm model đều có đo và hạn mức, giới hạn hành vi kẹp theo gói

Mọi lời gọi model của một lượt chạy, qua bất kỳ đường nào, chịu trần chi phí và giới hạn hành vi hữu hạn
của lượt đó, và không cửa nào vòng qua hạn mức (YC78; ADR-0121 (Proposed) quyết 4, 9).

- R6.1 Mọi cửa chạm model (gateway có cấu trúc, chat, embedding, rerank, lane nạp tri thức) PHẢI là một
  kiểu có đo đòi lease, và `RuntimeSeam` không lộ gateway thô hay factory chat trần.
- R6.2 NẾU lease đã cạn, THÌ mỗi cửa chạm model PHẢI từ chối lời gọi với `limit_exceeded`, dù gọi thẳng
  cửa đó không qua lớp đã chặn.
- R6.3 KHI một lượt chạy chạm giới hạn số bước, số lời gọi model hay số lời gọi công cụ của lượt (kẹp bởi
  Trần của gói), lượt chạy PHẢI dừng ở ranh giới kế tiếp với một dạng từ chối `limit_exceeded` và không
  áp chính sách lỗi của node.
- R6.4 Giới hạn hành vi của một lượt chạy PHẢI là kẹp của giá trị trong phiên bản và Trần của gói, không
  vượt Trần của gói.

## Trong phạm vi

- Bảng, cột và phân vùng ở mục Dữ liệu; route ở mục API.
- Mã: gói nền tảng `dw_usage` (Bảng giá, Sổ sử dụng, chính sách, bộ đếm, lease, bảng cuộn);
  `PlanCatalogPort` và `PlanEntitlementService` đọc một chủ; `PriceBook` theo ngày hiệu lực;
  `UsageLedgerPort`; `EffectiveLimits.for_admission` trên Chuỗi phạm vi hạn mức; `LimitsPort` (runtime
  khai) với `admit`, `resume`, `RunLease`, `release`; `LimitsMiddleware` thay `RunBudgetMiddleware`;
  cửa có đo `MeteredModelGateway`, `LimitedChatModelFactory`, `MeteredEmbeddingPort`, `MeteredRerankPort`;
  `ReapTarget` cho lease mồ côi; lane `usage_rollup`.
- Gỡ trong cùng lát: `RunBudgetLedger`, `RunSpend`, `ModelBudgets`, `DailyAllowance`, `SqlSpendGuard*`,
  lane `spend_guard_retention`, `platform.tenant_daily_spend_guard`.
- Audit: `limits.policy.set`, `limits.policy.removed`, `limits.refused`, `limits.lease.expired`.

## Ngoài phạm vi

| Việc                                                                                                               | Vì sao                                                                                  | Chủ                                               |
| ------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------- | ------------------------------------------------- |
| Hóa đơn, tín dụng, bảng giá bán cho khách; hiển thị VND và tỷ giá                                                  | Sổ là đo lường, không phải hóa đơn (D6); đơn vị bán và tiền tệ hiển thị chờ DO-59       | không làm (v1); usage-and-limits, đợt sau         |
| W2: cảnh báo ngưỡng 80% và 100% mỗi chính sách và kỳ qua outbox (`usage.limit.threshold_crossed`)                  | YC79; cần bộ đếm và chính sách của W1 trước                                             | usage-and-limits, đợt sau (W2)                    |
| W2: giới hạn tốc độ GCRA trên Valkey và bộ điều tốc nhà cung cấp                                                   | YC44; Valkey chỉ giữ trạng thái tốc độ; mất Valkey lùi về bộ đệm mỗi tiến trình (DO-49) | usage-and-limits, đợt sau (W2)                    |
| W2: hạn mức theo người dùng, theo mục đích (dựng có AI, chạy thử, kiểm định), theo đồng thời                       | YC79; mẫu cấu hình limit theo agent học từ phân tích đối thủ (config-chang.md mẫu 4)    | usage-and-limits, đợt sau (W2)                    |
| W2: BYOM (bên trả phí, giá riêng tenant, hạn mức token); đo CPU-giây sandbox, rerank, trích xuất, chuyển giọng nói | YC79; chờ `model-connections` và `code-sandbox` (DO-43, DO-45)                          | usage-and-limits; model-connections; code-sandbox |
| W3: hạn mức kiểu xin nâng, dự báo tốc độ đốt, phát hiện bất thường                                                 | v1.5 trở đi                                                                             | usage-and-limits, đợt sau (W3)                    |
| Hàng đợi lượt chạy và điều phối công bằng; cổng đánh giá và ngưỡng chi phí phát hành                               | spec này cấp bộ đếm đồng thời và nhãn `purpose`; cổng đọc sổ                            | workflow-engine; agent-lifecycle                  |
| Kết nối BYOM và LiteLLM; runtime sandbox                                                                           | spec này định nghĩa cổng báo CPU-giây và bên trả phí                                    | model-connections; code-sandbox                   |
| Đóng băng, Tắt khẩn cấp                                                                                            | cùng middleware hỏi thêm câu của agent-lifecycle                                        | agent-lifecycle                                   |

## Dữ liệu

Mọi bảng tenant: RLS ENABLE và FORCE theo tenant, grant cùng migration, tên ràng buộc theo
`NAMING_CONVENTION`, revision id hex ngẫu nhiên.

- `platform.plan_limits`: `plan_id text` khóa chính và FK `platform.plans ON DELETE CASCADE`; không
  `tenant_id`, không RLS; `dw_app` chỉ SELECT; cột `CHECK (>= 0)`: `runs_per_day`, `cost_usd_per_day`,
  `cost_usd_per_month`, `tokens_per_month`, `max_concurrent_runs`, `requests_per_minute`,
  `tokens_per_minute` (NULL = không giới hạn); trần mỗi lượt NOT NULL: `max_cost_usd_per_run`,
  `max_tokens_per_run`, `max_steps_per_run` CHECK (1..500), `max_model_calls_per_run`,
  `max_tool_calls_per_run`, `max_run_seconds`. `platform.plans.quotas` jsonb bị gỡ ở migration sau khi
  dời dữ liệu; tính năng đọc từ `platform.plans.features`.
- `platform.usage_events`: phân vùng theo tháng trên `occurred_at` với DEFAULT; `PRIMARY KEY (id, occurred_at)`;
  `operation` CHECK (`chat`, `embeddings`, `rerank`, `extraction`, `transcription`, `sandbox_exec`,
  `server_tool`, `unsettled_estimate`); gắn `tenant_id`, `workspace_id`, `run_id`, `root_run_id`,
  `lease_id`, `node_id`, `artifact_kind`, `artifact_id`, `artifact_version`, `user_id`, `actor_kind`,
  `trigger_kind`, `purpose` CHECK (`run`, `test_run`, `builder_assist`, `eval_offline`, `eval_online`,
  `ingestion`, `retrieval`, `compaction`, `memory`); token và `units jsonb`; `payer` CHECK (`platform`,
  `tenant`), `cost_usd numeric(18,8)` NULL chỉ khi `cost_source='unpriced'`, `cost_source` CHECK
  (`computed`, `provider_reported`, `estimated`, `unpriced`), `price_book_version`, `price_entry_ids`;
  CHECK `cache_read_tokens + cache_write_tokens <= input_tokens`, `reasoning_tokens <= output_tokens`,
  không cột nội dung; `dw_app` không UPDATE, DELETE trên cha và mọi phân vùng; vào mảng chỉ-thêm của
  `platform.ensure_time_partitions` cùng ENABLE/FORCE RLS và policy tenant trên cha và DEFAULT; giữ 395
  ngày; index `(tenant_id, occurred_at)`, `(tenant_id, run_id) WHERE run_id IS NOT NULL`,
  `(lease_id) WHERE lease_id IS NOT NULL`.
- `platform.usage_daily`: RLS tenant; `UNIQUE NULLS NOT DISTINCT (tenant_id, workspace_id, day, artifact_kind, artifact_id, user_id, provider, model, operation, purpose, payer)`;
  index `(tenant_id, day)`, `(tenant_id, workspace_id, day)`; cuộn lại hôm nay và hôm qua cho tenant có
  hoạt động, ngày theo `window_for`.
- `platform.limit_policies`: RLS tenant; `scope_type` CHECK (`tenant`, `workspace`, `agent`, `workflow`,
  `user`); `metric`, `window_kind`, `kind` CHECK (`hard`, `soft`); `limit_value numeric(20,8) CHECK (>= 0)`;
  `thresholds smallint[]` CHECK con của {50, 80, 90, 100}; `purposes text[]`; `version`; `created_by`;
  `UNIQUE (tenant_id, scope_type, scope_id, metric, window_kind)`; trigger `updated_at` nhường giá trị
  lệnh nêu. Không `workspace_id` cột (khóa `(scope_type, scope_id)`), như `platform.policy_overrides`
  tiền lệ (ADR-0121 (Proposed) nêu ngoại lệ với `CLAUDE.md:163`).
- `platform.budget_counters`: khóa chính `(tenant_id, scope_type, scope_id, metric, window_kind, window_start)`;
  `window_end`, `used`, `reserved`, `updated_at`; `CHECK (used >= 0 AND reserved >= 0)`; RLS tenant và
  policy drain.
- `platform.budget_leases`: `id`, `tenant_id`, `workspace_id`, `run_id`, `root_run_id`, `purpose`,
  `counter_keys jsonb`, `reserved_usd`, `reserved_tokens`, `settled_*`, `rolled_*`, `in_flight_*`,
  `state`, `close_reason`, `opened_at`, `heartbeat_at`, `expires_at`, `closed_at`; `UNIQUE (tenant_id, root_run_id) WHERE state='open'`;
  index từng phần `expires_at WHERE state='open'`.

## API

- `GET /api/v1/runs/{run_id}/usage` (`runs.read`, RLS và workspace): tổng theo thao tác, model, nguồn
  chi phí.
- `GET /api/v1/usage/summary` (`usage.read`, workspace trong tập được phép);
  `GET /api/v1/usage/limits` (bộ đếm so Hạn mức hiệu lực, giờ đặt lại).
- `GET /api/v1/limits` (`usage.read`); `PUT /api/v1/limits/{scope_type}/{scope_id}` và `DELETE`
  (`limits.manage`, `Idempotency-Key`); cao hơn Trần của gói → 422 `limit_above_plan`.
- Lỗi theo vỏ problem+json của ADR-0108 (Proposed); `details.reason_code`: `limit_exceeded`,
  `limit_above_plan`.

## Màn hình

- Màn Mức độ sử dụng `/usage` (antd Statistic cho chi phí, token, số run; Table nhóm theo; Progress cho
  hạn mức; không thư viện biểu đồ tới khi có quyết định), đọc `GET /api/v1/usage/summary`; nhúng tab ở
  trang agent và quy trình (mẫu cấu hình limit và usage theo agent, config-chang.md mẫu 4).
- Màn Cấu hình hạn mức (antd Form, Table) ở cấp tenant và workspace, hiện Trần của gói và Hạn mức hiệu
  lực; cấp agent và quy trình nhúng sau (agent-builder, workflow-builder-ui).

## Kiểm soát

| #    | Kiểm soát                                       | Yêu cầu    | Test âm                                                                                                                                                    |
| ---- | ----------------------------------------------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| UL1  | Số của gói có một chủ trong database            | R1.1, R1.2 | Xóa dòng `platform.plan_limits` của một gói → nhận lượt chạy bị từ chối, không hiểu thành "không giới hạn"; khai lại dict gói trong mã → test kiến trúc đỏ |
| UL2  | Hạn mức cứng giữ trước khi chi                  | R5.1       | 10 lượt chạy đồng thời, chỗ cho 3 → đúng 3 được nhận; gỡ khóa bộ đếm theo thứ tự → test đỏ                                                                 |
| UL3  | `max_tokens` kẹp theo lease                     | R5.2       | Lease còn đủ cho 100 token output → lời gọi mang `max_tokens <= 100`; gỡ kẹp → test đỏ                                                                     |
| UL4  | Không cửa nào vòng qua hạn mức                  | R6.1, R6.2 | Lease cạn: gọi thẳng gateway có cấu trúc, chat, embedding, rerank, lane nạp → mỗi cửa bị từ chối; `RuntimeSeam` lộ gateway thô → test field đỏ             |
| UL5  | Thiếu số dùng không thành 0                     | R3.3       | Adapter không báo usage → dòng `estimated` bằng ước tính; gỡ → test đỏ                                                                                     |
| UL6  | Lease mồ côi được thu hồi                       | R5.4       | Tiến trình chết giữa lời gọi → sau `expires_at` lease đóng, phần đang bay tính, audit `system:reaper`; gỡ `ReapTarget` → test đỏ                           |
| UL7  | Cách ly tenant                                  | R3.6       | Đọc, ghi `budget_counters`, `budget_leases`, `usage_events`, `limit_policies` của tenant B từ A → 0 dòng hoặc 404; kết nối không đặt tenant đọc 0 dòng     |
| UL8  | Workspace con không vượt cha                    | R4.4       | Cha cap USD 10 đã dùng hết, con cap USD 50 → lượt chạy ở con bị chặn; gỡ vòng tổ tiên → test đỏ                                                            |
| UL9  | Không đặt Hạn mức trên Trần của gói             | R4.5       | `PUT` hạn mức tenant cao hơn gói → 422 `limit_above_plan`, không dòng nào đổi                                                                              |
| UL10 | Chỉ người có quyền đặt Hạn mức                  | R4.6       | Thiếu `limits.manage` → 403; workspace tenant khác → 404                                                                                                   |
| UL11 | Tạm dừng nhả tiền                               | R5.3       | Lượt chạy chờ duyệt → `reserved` của lượt về 0; tiếp tục → giữ lại số đã tiêu; gỡ nhả → test đỏ                                                            |
| UL12 | Giá không định lại lịch sử                      | R2.4       | Đổi Bảng giá → dòng cũ giữ `price_book_version` và chi phí cũ                                                                                              |
| UL13 | Hạn mức giữa lượt chạy dừng sạch, không hạ ngầm | R5.5, R6.3 | Trần cạn giữa lượt → dừng ở ranh giới kế tiếp `limit_exceeded`, không cắt giữa một bước gửi, không hạ model; gỡ kiểm ranh giới → test đỏ                   |

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (ghi ở Comments của
  ticket).
- `make ci && make test-integration` xanh; `reviewing-feature-security` và `reviewing-deployment-security`
  đã chạy trên từng ticket có route, migration hay lane; ADR-0121 (Proposed) được Đạt ký (DO-21);
  `.claude/plans/studio.md` ghi lát W1 đã xong.

## Phụ thuộc

- studio-skeleton: schema và phân vùng
  (`.claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md`), gói và điều
  hướng (`.claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md`).
- tenant-rbac: danh mục quyền là một chủ (tenant-rbac:R1.1) — tên quyền `usage.read`, `limits.manage`
  đăng ký ở `.claude/plans/studio/tenant-rbac/issues/01-mot-chu-cho-quyen.md`; độ sâu workspace qua
  `platform.effective_grants` (tenant-rbac:R2.1).
- org-and-principals: cây workspace và workspace gốc cho Chuỗi phạm vi hạn mức
  (`.claude/plans/studio/org-and-principals/issues/02-thanh-vien-cap-tenant.md`).
- workflow-engine: `root_run_id`, cửa nhận lượt chạy và ranh giới node
  (`.claude/plans/studio/workflow-engine/issues/02-cot-run-va-cua-nhan-run.md`,
  `.claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md`); agent-builder: giới hạn
  hành vi trong phiên bản (`.claude/plans/studio/agent-builder/issues/03-runtime-agent.md`).
- agent-lifecycle: cùng danh sách cửa hỏi thêm câu Đóng băng (agent-lifecycle:R7.1); spec này gắn nhãn
  `purpose` `eval_offline`, `eval_online` cho cổng đọc.
- Mâu thuẫn `CLAUDE.md:163` ("Mọi bảng gắn tenant có `tenant_id` và `workspace_id`"):
  `platform.limit_policies` và `platform.budget_counters` khóa theo `(scope_type, scope_id)` không có
  cột `workspace_id`, như tiền lệ `platform.policy_overrides`; ADR-0121 (Proposed) ghi ngoại lệ, nợ khi
  được chấp nhận. `resume` nay kiểm lease tiền (chi sau khi tiếp tục là chi mới), nhưng số run mỗi ngày
  không tính lại (giữ quy tắc `langgraph_runner.py:255-257`).
- Kiểm lại khi: DO-21 bị Đạt từ chối → R2, R3, R5 (toàn lát sổ); danh mục quyền của tenant-rbac đổi tên
  → R4.5, R4.6; cây workspace của org-and-principals đổi hình → R4.1, R4.4; cửa nhận lượt chạy của
  workflow-engine đổi hợp đồng → R4, R5.

## Câu hỏi còn mở

- Q1. Có đưa lại Sổ sử dụng theo lượt gọi (D6), đảo migration `aefe7c1f5d9b`, đóng khung là đo lường với
  bên đọc có tên trong cùng lát? Chủ: Đạt. Chặn: R2, R3, R5, ticket 02, 03 (Đạt ký vì chính Đạt yêu cầu
  gỡ — DO-21).
- Q2. Đóng gói và giá: phí gói mỗi công ty cộng tín dụng AI gộp theo tháng, đơn vị công ty thấy, tiền tệ
  hiển thị (USD ở v1, VND với bảng tỷ giá có ngày ở v1.5), và các số mặc định của gói? Chủ: Đạt. Không
  đổi: USD nội bộ `numeric(18,8)`, số mặc định nằm ở `platform.plan_limits` seed; đổi là đổi dữ liệu,
  không sửa R1 (DO-59).

## Quyết định

- 23/10/2026 (người yêu cầu): D6 (DO-21, chờ Đạt ký): đưa lại Sổ sử dụng theo lượt gọi làm nguồn cho
  hạn mức, màn Mức độ sử dụng và đối soát, kèm bên đọc từ ngày đầu. Hỏi: Q1. Sửa: R2, R3, R5.
- 23/10/2026 (người yêu cầu): D13 (DO-19): model của tenant (BYOM) đi qua một lane LiteLLM riêng, không
  trạng thái; nền tảng giữ khóa trong vault và tiêm theo lời gọi. Sửa: Ngoài phạm vi (BYOM W2).
- 23/10/2026 (agent, tạm): DO-50 theo khuyến nghị (a): kỳ tính theo múi giờ của công ty qua một hàm
  `window_for`; Hạn mức cứng chạm giữa lượt dừng lượt chạy (xin nâng ở v1.5, không hạ ngầm); dựng có AI,
  chạy thử và kiểm định trả từ ngân sách công ty với trần mục đích riêng, không tính vào số run mỗi
  ngày; chỉ run gốc tính vào số run mỗi ngày. Sửa: R5.5, R3.5. Nếu sai thì: kỳ theo UTC và đổi
  `window_for`; đổi cách tính run mỗi ngày.
- 23/10/2026 (agent, tạm): DO-43 theo khuyến nghị (a): không fallback từ model tenant sang model nền
  tảng trả phí; token BYOM chỉ tính vào trần tenant đặt, không vào hạn mức tiền của nền tảng. Sửa: Ngoài
  phạm vi (BYOM W2). Nếu sai thì: thêm luật fallback và nhãn bên trả phí ở sổ.
- 23/10/2026 (agent, tạm): DO-49 theo khuyến nghị (a): usage-and-limits giữ `RateLimiterPort`; khi Valkey
  mất, lùi về bộ đệm mỗi tiến trình ở mức `limit / số replica`, tiền và đồng thời không ảnh hưởng (ở
  Postgres). Sửa: Ngoài phạm vi (GCRA W2). Nếu sai thì: đóng khi mất Valkey, không mở.
- 23/10/2026 (agent, tạm): mẫu cấu hình limit theo agent và màn Mức độ sử dụng đặt ngay trong cài đặt
  agent lấy từ phân tích đối thủ (config-chang.md mẫu 4, YC76, YC77) — một mẫu học được, không phải mã
  của họ; Studio mở rộng thành một Chuỗi phạm vi hạn mức giữ trước bằng lease. Sửa: R4, Màn hình.

## Danh sách ticket

| #   | Ticket                                                                                                                       |
| --- | ---------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Một chủ cho danh mục gói: platform.plan_limits thay DEFAULT_PLANS](issues/01-danh-muc-goi-mot-chu.md)                       |
| 02  | [Bảng giá theo ngày hiệu lực, sổ sử dụng theo lượt gọi và màn Mức độ sử dụng](issues/02-bang-gia-so-su-dung-va-man-hinh.md)  |
| 03  | [Hạn mức theo chuỗi phạm vi: giữ trước lúc nhận run, quyết toán từng lượt gọi](issues/03-han-muc-giu-truoc-va-quyet-toan.md) |
| 04  | [Đóng các cửa vòng qua hạn mức và giới hạn hành vi mỗi lượt chạy](issues/04-dong-cua-vong-va-gioi-han-hanh-vi.md)            |
