# Sổ sử dụng, bảng giá và hạn mức

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Studio cần đo và chặn chi tiêu ở mức công ty, workspace, agent, quy trình và người dùng, việc mà một
tổng theo ngày của cả tenant không làm được. Lát này đưa lại Sổ sử dụng theo lượt gọi (D6) làm nguồn
cho hạn mức, sử dụng theo lượt chạy và màn Mức độ sử dụng, ba bên đọc ship cùng lát (đối soát cho người
vận hành là W2); đặt một Bảng giá theo ngày hiệu lực làm chủ duy nhất của "cái này tốn bao nhiêu"; biến
mọi Hạn mức cứng thành Khoản giữ trước bằng lease Postgres mở lúc nhận lượt chạy, kẹp `max_tokens` từng
lời gọi, quyết toán từng lượt gọi (ADR-0121 (Accepted)); và giữ một `RateLimiterPort` cho mọi giới hạn tốc
độ theo công ty. W1 phục vụ YC76, YC77, YC78, một chủ cho số của gói và giới hạn tốc độ của YC44 bằng bộ
đếm theo tiến trình (DO-49); GCRA trên Valkey và YC79 (hạn mức theo người và mục đích) thuộc W2.

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
  (`db/migrations/versions/2b5ff2bceb06_tenant_daily_spend_guard.py:15-18`). Ràng buộc: W1 đảo việc gỡ
  bằng một revision mới, kèm bên đọc từ ngày đầu (Đạt ký DO-21.1 ngày 23/10/2026).
- `platform.ensure_time_partitions` chỉ biết một parent `ARRAY['audit_events']`
  (`db/migrations/sql/0013_partition_maintenance.sql:123`). Ràng buộc: studio-skeleton viết lại hàm để đọc
  sổ `platform.time_partitioned_tables` (studio-skeleton:R3.1), nên Sổ sử dụng đăng ký bằng một dòng sổ,
  không sửa mảng của hàm.
- `platform.tenants.timezone` có nhưng không hàm cửa sổ nào đọc
  (`db/migrations/sql/0001_platform_baseline.sql:407`). Ràng buộc: một hàm `window_for` đọc nó cho kỳ
  tính (DO-50).
- Limiter API là cửa sổ cố định 60 giây theo băm của bearer chưa xác minh
  (`apps/api/src/dw_api/middleware/rate_limit.py:36-41`). Ràng buộc: middleware này chặn ở cửa API, không
  phải chủ giới hạn theo công ty; giới hạn theo nguồn dữ liệu đi qua `RateLimiterPort` (DO-49); Valkey chỉ
  giữ trạng thái tốc độ (W2); tiền và đồng thời ở Postgres.

## Mục tiêu

### R1 — Một chủ cho số của gói dịch vụ

Số giới hạn của một Gói dịch vụ nằm một chỗ trong database, không còn bản sao trong mã (YC77;
ADR-0121 (Accepted) quyết 6).

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
sử không bị định lại giá (YC76; ADR-0121 (Accepted) quyết 2).

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
mục đích và bên trả phí; màn Mức độ sử dụng đọc chính sổ này (YC76; ADR-0121 (Accepted) quyết 1).

- R3.1 KHI một lượt gọi model (chat, có cấu trúc, embedding) kết thúc, `UsageLedgerPort.settle` PHẢI ghi
  đúng một Bản ghi sử dụng mang `tenant_id`, `workspace_id`, `run_id`, `root_run_id`, `artifact_kind`,
  `artifact_id`, `artifact_version`, `purpose`, `payer`, `price_book_version` và lộ trình của lời gọi
  (`data_route_class`, `data_location`, `processor`; compliance-pdpl:R2.1).
- R3.2 KHI cùng một `(id, occurred_at)` được quyết toán lại, `platform.usage_events` PHẢI giữ đúng một
  dòng (`INSERT ... ON CONFLICT DO NOTHING`).
- R3.3 NẾU nhà cung cấp không trả số token dùng, THÌ `UsageLedgerPort.settle` PHẢI ghi `cost_source`
  `estimated` với chi phí ước tính, không ghi 0.
- R3.4 NẾU `dw_app` UPDATE hay DELETE trên `platform.usage_events` hay một phân vùng của nó, THÌ
  PostgreSQL PHẢI từ chối, vì sổ chỉ thêm.
- R3.5 KHI người giữ `platform.usage.read` mở `GET /api/v1/usage/summary`, màn Mức độ sử dụng PHẢI đọc
  tổng từ bảng cuộn của `platform.usage_events` trong tập workspace được phép, với tổng một ngày bằng đúng
  tổng `platform.usage_events` của ngày đó theo `window_for`.
- R3.6 NẾU công ty khác đọc Sổ sử dụng của công ty này qua bảng cha hay route, THÌ PostgreSQL và API PHẢI
  trả 0 dòng hoặc 404.
- R3.7 NẾU `dw_app` đọc hay ghi một phân vùng của `platform.usage_events` theo tên phân vùng, THÌ
  PostgreSQL PHẢI từ chối với `permission denied`, vì dòng chỉ đọc ghi qua bảng cha (DO-02.2).

### R4 — Hạn mức là chính sách trên một chuỗi phạm vi, chặn ở cửa nhận lượt chạy

Cửa nhận lượt chạy là một chỗ: runner, do làn `studio_runs` gọi lúc dispatch (DO-21.3). KHI phần còn lại
của một Hạn mức cứng trong Chuỗi phạm vi hạn mức không đủ, lượt tương tác kết thúc, lượt do trình kích
hoạt chờ tới kỳ sau, không gọi model và không mất sự kiện (YC77; ADR-0121 (Accepted) quyết 3). Lượt kiểm
định xin lease qua lane `studio_gate` (agent-lifecycle:R4.4).

- R4.1 KHI một lượt chạy xin bắt đầu, cửa nhận lượt chạy PHẢI kiểm mọi phạm vi có chính sách trong Chuỗi
  phạm vi hạn mức (gói, công ty, workspace và tổ tiên, agent hoặc quy trình, người dùng, lượt chạy) và
  chỉ cho qua khi mọi phạm vi có chính sách đều còn đủ.
- R4.2 NẾU phần còn lại của một Hạn mức cứng theo kỳ không đủ lúc nhận một lượt chạy tương tác (`chat`,
  `manual`, `test`), THÌ cửa nhận lượt chạy PHẢI kết thúc lượt chạy là `failed` với `limit_exceeded` kèm
  `metric`, `scope_type`, `window`, `limit`, `used`, `resets_at`, không gọi model nào.
- R4.3 NẾU phần còn lại của một Hạn mức cứng theo kỳ không đủ lúc nhận một lượt chạy do trình kích hoạt
  (`datahub`, `record_event`, `provider_app`), THÌ cửa nhận lượt chạy PHẢI giữ lượt chạy ở `queued` với
  `available_at` bằng `resets_at` và `limit_exceeded`, không gọi model và không bỏ sự kiện.
- R4.4 NẾU một workspace con đặt trần cao hơn phần còn lại của cha, THÌ cửa nhận lượt chạy PHẢI vẫn áp
  trần của cha (phạm vi cha có chính sách thì phải qua).
- R4.5 NẾU người giữ `platform.limits.manage` đặt một Hạn mức cao hơn Trần của gói, THÌ API hạn mức PHẢI
  trả 422 `limit_above_plan` và không đổi dòng nào.
- R4.6 NẾU người gọi thiếu `platform.limits.manage`, hoặc nhắm workspace của công ty khác, THÌ API hạn mức
  PHẢI trả 403 hoặc 404 và không đổi gì.
- R4.7 NẾU thiếu chỗ đồng thời lúc nhận một lượt chạy, THÌ cửa nhận lượt chạy PHẢI xếp lại lượt chạy ở
  `queued` với `available_at` sau, với mọi `trigger_kind`, không gọi model nào.
- R4.8 KHI người giữ `platform.limits.manage` hạ một Hạn mức hay đặt Hạn mức cho một phạm vi chưa có, API
  hạn mức PHẢI áp thay đổi với một người và ghi audit `limits.policy.set` trong cùng giao dịch (D11: siết
  một người).
- R4.9 NẾU một lệnh `PUT` hay `DELETE` làm một Hạn mức lỏng hơn chính sách đang có hiệu lực (giá trị cao
  hơn, gỡ chính sách, đổi `hard` sang `soft`), THÌ API hạn mức PHẢI trả 409 `second_person_required` và
  không đổi dòng nào, vì W1 chưa có đường hai người cho việc nới (D11: nới hai người).

### R5 — Hạn mức cứng giữ trước bằng lease, quyết toán từng lượt gọi, thu hồi lease mồ côi

Tiền và token được giữ trước bằng một lease mở lúc nhận lượt chạy, mỗi lời gọi kẹp `max_tokens` theo
phần lease còn lại và quyết toán idempotent, và lease của lượt chạy chết được thu hồi (YC77, YC78;
ADR-0121 (Accepted) quyết 4).

- R5.1 KHI runner nhận một lượt chạy gốc do làn `studio_runs` giao ở dispatch, `LimitsPort.admit` PHẢI
  khóa các bộ đếm theo thứ tự chuẩn và mở đúng một lease mở cho lượt chạy gốc đó, trong một giao dịch.
- R5.2 KHI một lời gọi model sắp chạy, `RunLease.before_call` PHẢI đặt `max_tokens` của lời gọi không
  vượt phần lease còn lại cho phép.
- R5.3 KHI một lượt chạy tạm dừng chờ phê duyệt hay việc người rồi tiếp tục, `LimitsPort` PHẢI nhả phần
  `reserved` lúc dừng và lấy lại lease lúc tiếp tục sao cho số đã tiêu qua các lease được giữ nguyên.
- R5.4 NẾU một tiến trình chết giữa lời gọi, THÌ một `ReapTarget` PHẢI đóng lease quá `expires_at`, ghi
  một dòng `unsettled_estimate` cho phần đang bay, cuộn bộ đếm, và audit `limits.lease.expired` với actor
  `system:reaper`.
- R5.5 TRONG KHI một trần mỗi lượt chạy đã cạn giữa lượt chạy, lượt chạy PHẢI dừng ở ranh giới lời gọi
  kế tiếp với `limit_exceeded`, không hạ ngầm xuống model rẻ hơn.
- R5.6 KHI một lượt chạy con hay một lần thử của Lượt kiểm định bắt đầu, runner PHẢI dùng lease của lượt
  chạy gốc hay của Lượt kiểm định, không gọi `LimitsPort.admit` và không mở lease thứ hai
  (ADR-0113 (Accepted) quyết 9).
- R5.7 KHI lane `retention_limits` chạy, lane PHẢI xóa dòng `platform.budget_counters` có `window_end` cũ
  hơn 35 ngày và lease `platform.budget_leases` đã đóng quá 30 ngày, không chạm dòng của kỳ hay lease còn mở.

### R6 — Mọi cửa chạm model đều có đo và hạn mức, giới hạn hành vi kẹp theo gói

Mọi lời gọi model của một lượt chạy, qua bất kỳ đường nào, chịu trần chi phí và giới hạn hành vi hữu hạn
của lượt đó, và không cửa nào vòng qua hạn mức (YC78; ADR-0121 (Accepted) quyết 4, 9).

- R6.1 Mọi cửa chạm model (gateway có cấu trúc, chat, embedding, rerank, lane nạp tri thức) PHẢI là một
  kiểu có đo đòi lease, và `RuntimeSeam` không lộ gateway thô hay factory chat trần.
- R6.2 NẾU lease đã cạn, THÌ mỗi cửa chạm model PHẢI từ chối lời gọi với `limit_exceeded`, dù gọi thẳng
  cửa đó không qua lớp đã chặn.
- R6.3 KHI một lượt chạy chạm giới hạn số bước, số lời gọi model hay số lời gọi công cụ của lượt (kẹp bởi
  Trần của gói), lượt chạy PHẢI dừng ở ranh giới kế tiếp với một dạng từ chối `limit_exceeded` và không
  áp chính sách lỗi của node.
- R6.4 Giới hạn hành vi của một lượt chạy PHẢI là kẹp của giá trị trong phiên bản và Trần của gói, không
  vượt Trần của gói.
- R6.5 NẾU `ResidencyGate` từ chối một lời gọi model (compliance-pdpl:R2.2), THÌ `LimitsMiddleware` PHẢI
  không giữ trước tiền và không ghi Bản ghi sử dụng nào cho lời gọi đó, vì cổng lộ trình đứng trước lease.

### R7 — Một `RateLimiterPort` cho mọi giới hạn tốc độ theo công ty

Nguồn dữ liệu và các bên giới hạn tốc độ theo công ty hỏi một port của spec này, không tự viết bộ đếm;
W1 dùng bộ đếm theo tiến trình, GCRA trên Valkey vào ở W2 (YC44; DO-49).

- R7.1 KHI một bên gọi `RateLimiterPort` với khóa của một nguồn dữ liệu, adapter theo tiến trình PHẢI cho
  qua tối đa `giới hạn / số replica` lần mỗi phút cho khóa đó ở mỗi tiến trình (giới hạn 60, 2 replica: lần
  thứ 30 trong một phút ở một tiến trình thì nhận, lần thứ 31 thì từ chối kèm thời điểm thử lại).
- R7.2 Khóa của `RateLimiterPort` PHẢI là `(tenant_id, id nguồn dữ liệu)` đã xác minh, không bao giờ là
  băm của bearer chưa xác minh.

## Trong phạm vi

- Bảng, cột và phân vùng ở mục Dữ liệu; route ở mục API.
- Mã: gói nền tảng `dw_usage` (Bảng giá, Sổ sử dụng, chính sách, bộ đếm, lease, bảng cuộn);
  `PlanCatalogPort` và `PlanEntitlementService` đọc một chủ; `PriceBook` theo ngày hiệu lực;
  `UsageLedgerPort`; `EffectiveLimits.for_admission` trên Chuỗi phạm vi hạn mức; `LimitsPort` (runtime
  khai) với `admit`, `resume`, `RunLease`, `release`; `LimitsMiddleware` thay `RunBudgetMiddleware`;
  cửa có đo `MeteredModelGateway`, `LimitedChatModelFactory`, `MeteredEmbeddingPort`, `MeteredRerankPort`;
  `ReapTarget` cho lease mồ côi; lane `usage_rollup`; lane `retention_limits`; `RateLimiterPort` và adapter
  bộ đếm theo tiến trình (W1).
- Gỡ trong cùng lát: `RunAllowancePort` và adapter của nền tảng đáp nó, `RunBudgetLedger`, `RunSpend`,
  `ModelBudgets`, `DailyAllowance`, `SqlSpendGuard*`, lane `spend_guard_retention`,
  `platform.tenant_daily_spend_guard` (và dòng của nó trong danh sách bảng toàn tenant của
  `test_rls_coverage.py`).
- Audit: `limits.policy.set`, `limits.policy.removed`, `limits.refused`, `limits.lease.expired`.

## Ngoài phạm vi

| Việc                                                                                                                                                                                             | Vì sao                                                                                                                                                                             | Chủ                                               |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| Hóa đơn, tín dụng, bảng giá bán cho khách; hiển thị VND và tỷ giá                                                                                                                                | Sổ là đo lường, không phải hóa đơn (D6); v1 bán phí gói cố định kèm trần chi phí AI mỗi tháng (`cost_usd_per_month`), không tín dụng (DO-59.2); VND với bảng tỷ giá có ngày ở v1.5 | không làm (v1); usage-and-limits, đợt sau         |
| W2: nới Hạn mức (nâng, gỡ, đổi `hard` sang `soft`) qua đề xuất một người và duyệt của người thứ hai trong tenant-config                                                                          | D11 (mở hai người); W1 chỉ siết, lệnh nới trả 409 (R4.9)                                                                                                                           | usage-and-limits; tenant-config, đợt sau (W2)     |
| W2: đối soát cho người vận hành và chi phí theo kết quả                                                                                                                                          | không có bên đọc ở W1 (DO-21.1); chi phí mỗi lead (KQ12) cần sự kiện kết quả của marketing-pilot                                                                                   | usage-and-limits; marketing-pilot, đợt sau (W2)   |
| W2: lượt `schedule` thiếu hạn mức ghi lần kích hoạt `limit_refused`, không giữ tới `resets_at`                                                                                                   | trình kích hoạt lịch là W2 (DO-21.3)                                                                                                                                               | workflow-triggers, đợt sau (W2)                   |
| W2: giới hạn thời gian mỗi lượt chạy theo `max_run_seconds`                                                                                                                                      | cần hạn chót bền và hủy xuyên tiến trình của workflow-engine, đều W2                                                                                                               | usage-and-limits; workflow-engine, đợt sau (W2)   |
| W2: cảnh báo ngưỡng 80% và 100% mỗi chính sách và kỳ qua outbox (`usage.limit.threshold_crossed`)                                                                                                | YC79; cần bộ đếm và chính sách của W1 trước                                                                                                                                        | usage-and-limits, đợt sau (W2)                    |
| W2: giới hạn tốc độ GCRA trên Valkey (adapter thứ hai của `RateLimiterPort`) và bộ điều tốc nhà cung cấp                                                                                         | YC44; W1 đã có port và bộ đếm theo tiến trình (R7); Valkey chỉ giữ trạng thái tốc độ; mất Valkey lùi về bộ đếm mỗi tiến trình (DO-49)                                              | usage-and-limits, đợt sau (W2)                    |
| W2: hạn mức theo người dùng, theo mục đích (dựng có AI, chạy thử, kiểm định), theo đồng thời; hiển thị sử dụng theo tên người; phần nền tảng trả có trần cho lượt kiểm định lại do nền tảng kích | YC79; mẫu cấu hình limit theo agent học từ phân tích đối thủ (config-chang.md mẫu 4); theo tên người sau khi luật sư xác nhận thông báo cho nhân viên (DO-51.2); DO-29.2           | usage-and-limits, đợt sau (W2)                    |
| W2: BYOM (bên trả phí, giá riêng tenant, hạn mức token); đo bước mã theo vCPU và GB đặt trước nhân thời gian chạy, rerank, trích xuất, chuyển giọng nói                                          | YC79; chờ `model-connections` và `code-sandbox` (DO-43; DO-45.1 chọn đơn vị đặt trước)                                                                                             | usage-and-limits; model-connections; code-sandbox |
| W3: hạn mức kiểu xin nâng, dự báo tốc độ đốt, phát hiện bất thường                                                                                                                               | v1.5 trở đi                                                                                                                                                                        | usage-and-limits, đợt sau (W3)                    |
| Hàng đợi lượt chạy và điều phối công bằng; cổng đánh giá và ngưỡng chi phí phát hành                                                                                                             | spec này cấp bộ đếm đồng thời và `LimitsPort`; cổng xin lease `eval_offline` (DO-21.4)                                                                                             | workflow-engine; agent-lifecycle                  |
| Kết nối BYOM và LiteLLM; runtime sandbox                                                                                                                                                         | spec này định nghĩa cổng báo vCPU và GB đặt trước nhân thời gian chạy (DO-45.1) và bên trả phí                                                                                     | model-connections; code-sandbox                   |
| Đóng băng, Tắt khẩn cấp                                                                                                                                                                          | cùng middleware hỏi thêm câu của agent-lifecycle                                                                                                                                   | agent-lifecycle                                   |

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
  `data_route_class` CHECK (`vn_only`, `cross_border_minimised`, `cross_border_full`), `data_location`
  CHECK (`vn`, `foreign`), `processor` (ADR-0123 (Accepted) quyết 6);
  CHECK `cache_read_tokens + cache_write_tokens <= input_tokens`, `reasoning_tokens <= output_tokens`,
  không cột nội dung; `dw_app` không UPDATE, DELETE trên cha và không giữ quyền nào trên phân vùng nào,
  kể cả DEFAULT, nên đọc ghi qua bảng cha (DO-02.2); đăng ký bằng một dòng `platform.time_partitioned_tables`
  (`append_only = true`, studio-skeleton:R3.1), ENABLE/FORCE RLS và policy tenant trên cha và DEFAULT; giữ
  395 ngày (13 tháng), thời hạn khai trong `retention@1.8.0` của telemetry-and-audit (DO-52); index
  `(tenant_id, occurred_at)`, `(tenant_id, run_id) WHERE run_id IS NOT NULL`,
  `(lease_id) WHERE lease_id IS NOT NULL`.
- `platform.usage_daily`: RLS tenant; `UNIQUE NULLS NOT DISTINCT (tenant_id, workspace_id, day, artifact_kind, artifact_id, user_id, provider, model, operation, purpose, payer)`;
  index `(tenant_id, day)`, `(tenant_id, workspace_id, day)`; cuộn lại hôm nay và hôm qua cho tenant có
  hoạt động, ngày theo `window_for`.
- `platform.limit_policies`: RLS tenant; `scope_type` CHECK (`tenant`, `workspace`, `agent`, `workflow`,
  `user`); `metric`, `window_kind`, `kind` CHECK (`hard`, `soft`); `limit_value numeric(20,8) CHECK (>= 0)`;
  `thresholds smallint[]` CHECK con của {50, 80, 90, 100}; `purposes text[]`; `version`; `created_by`;
  `UNIQUE (tenant_id, scope_type, scope_id, metric, window_kind)`; trigger `updated_at` nhường giá trị
  lệnh nêu. Bảng toàn tenant: không cột `workspace_id` (khóa `(scope_type, scope_id)`, tiền lệ
  `platform.policy_overrides`), có tên và lý do trong danh sách bảng toàn tenant mà `test_rls_coverage.py`
  giữ (`CLAUDE.md` mục 'Tenancy and authorization', ngoại lệ của DO-01).
- `platform.budget_counters`: khóa chính `(tenant_id, scope_type, scope_id, metric, window_kind, window_start)`;
  `window_end`, `used`, `reserved`, `updated_at`; `CHECK (used >= 0 AND reserved >= 0)`; RLS tenant và
  policy drain; bảng toàn tenant như `platform.limit_policies`; lane `retention_limits` xóa dòng có
  `window_end` cũ hơn 35 ngày (R5.7).
- `platform.budget_leases`: `id`, `tenant_id`, `workspace_id`, `run_id`, `root_run_id`, `purpose`,
  `counter_keys jsonb`, `reserved_usd`, `reserved_tokens`, `settled_*`, `rolled_*`, `in_flight_*`,
  `state`, `close_reason`, `opened_at`, `heartbeat_at`, `expires_at`, `closed_at`; `UNIQUE (tenant_id, root_run_id) WHERE state='open'`;
  index từng phần `expires_at WHERE state='open'`; lane `retention_limits` xóa lease đóng quá 30 ngày (R5.7).

## API

- `GET /api/v1/runs/{run_id}/usage` (`runs.read`, RLS và workspace): tổng theo thao tác, model, nguồn
  chi phí.
- `GET /api/v1/usage/summary` (`platform.usage.read`, workspace trong tập được phép): gộp theo workspace,
  agent, quy trình và mục đích; W1 không có chiều gộp theo người (DO-51.2).
- `GET /api/v1/limits` (`platform.usage.read`): mỗi chính sách kèm Hạn mức hiệu lực, bộ đếm của kỳ hiện tại
  và giờ đặt lại; không có route `/api/v1/usage/limits` riêng. `PUT /api/v1/limits/{scope_type}/{scope_id}`
  và `DELETE` (`platform.limits.manage`, `Idempotency-Key`): siết áp ngay với một người (R4.8); nới trả 409
  `second_person_required` ở W1 (R4.9); cao hơn Trần của gói → 422 `limit_above_plan`.
- Lỗi theo vỏ problem+json của ADR-0108 (Accepted); `details.reason_code`: `limit_exceeded`,
  `limit_above_plan`, `second_person_required`.

## Màn hình

- Màn Mức độ sử dụng `/usage` (antd Statistic cho chi phí, token, số run; Table nhóm theo workspace,
  agent, quy trình, mục đích, không theo người ở W1; Progress cho hạn mức; không thư viện biểu đồ ở v1,
  biểu đồ cần ADR riêng khi có YC đòi, DO-42.3), đọc `GET /api/v1/usage/summary`; nhúng tab ở trang agent
  và quy trình (mẫu cấu hình limit và usage theo agent, config-chang.md mẫu 4).
- Màn Cấu hình hạn mức (antd Form, Table) ở cấp tenant và workspace, hiện Trần của gói và Hạn mức hiệu
  lực; W1 chỉ cho hạ hay đặt mới, nới mở ở W2 cùng đề xuất hai người; cấp agent và quy trình nhúng sau
  (agent-builder, workflow-builder-ui).

## Kiểm soát

| #    | Kiểm soát                                             | Yêu cầu    | Test âm                                                                                                                                                                                                                     |
| ---- | ----------------------------------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| UL1  | Số của gói có một chủ trong database                  | R1.1, R1.2 | Xóa dòng `platform.plan_limits` của một gói → nhận lượt chạy bị từ chối, không hiểu thành "không giới hạn"; khai lại dict gói trong mã → test kiến trúc đỏ                                                                  |
| UL2  | Hạn mức cứng giữ trước khi chi                        | R5.1       | 10 lượt chạy đồng thời, chỗ cho 3 → đúng 3 được nhận; gỡ khóa bộ đếm theo thứ tự → test đỏ                                                                                                                                  |
| UL3  | `max_tokens` kẹp theo lease                           | R5.2       | Lease còn đủ cho 100 token output → lời gọi mang `max_tokens <= 100`; gỡ kẹp → test đỏ                                                                                                                                      |
| UL4  | Không cửa nào vòng qua hạn mức                        | R6.1, R6.2 | Lease cạn: gọi thẳng gateway có cấu trúc, chat, embedding, rerank, lane nạp → mỗi cửa bị từ chối; `RuntimeSeam` lộ gateway thô → test field đỏ                                                                              |
| UL5  | Thiếu số dùng không thành 0                           | R3.3       | Adapter không báo usage → dòng `estimated` bằng ước tính; gỡ → test đỏ                                                                                                                                                      |
| UL6  | Lease mồ côi được thu hồi                             | R5.4       | Tiến trình chết giữa lời gọi → sau `expires_at` lease đóng, phần đang bay tính, audit `system:reaper`; gỡ `ReapTarget` → test đỏ                                                                                            |
| UL7  | Cách ly tenant                                        | R3.6, R3.7 | Đọc, ghi `budget_counters`, `budget_leases`, `usage_events`, `limit_policies` của tenant B từ A → 0 dòng hoặc 404; kết nối không đặt tenant đọc 0 dòng; đọc một phân vùng của `usage_events` theo tên → `permission denied` |
| UL8  | Workspace con không vượt cha                          | R4.4       | Cha cap USD 10 đã dùng hết, con cap USD 50 → lượt chạy ở con bị chặn; gỡ vòng tổ tiên → test đỏ                                                                                                                             |
| UL9  | Không đặt Hạn mức trên Trần của gói                   | R4.5       | `PUT` hạn mức tenant cao hơn gói → 422 `limit_above_plan`, không dòng nào đổi                                                                                                                                               |
| UL10 | Chỉ người có quyền đặt Hạn mức                        | R4.6       | Thiếu `platform.limits.manage` → 403; workspace tenant khác → 404                                                                                                                                                           |
| UL11 | Tạm dừng nhả tiền                                     | R5.3       | Lượt chạy chờ duyệt → `reserved` của lượt về 0; tiếp tục → giữ lại số đã tiêu; gỡ nhả → test đỏ                                                                                                                             |
| UL12 | Giá không định lại lịch sử                            | R2.4       | Đổi Bảng giá → dòng cũ giữ `price_book_version` và chi phí cũ                                                                                                                                                               |
| UL13 | Hạn mức giữa lượt chạy dừng sạch, không hạ ngầm       | R5.5, R6.3 | Trần cạn giữa lượt → dừng ở ranh giới kế tiếp `limit_exceeded`, không cắt giữa một bước gửi, không hạ model; gỡ kiểm ranh giới → test đỏ                                                                                    |
| UL14 | Giới hạn tốc độ theo nguồn dữ liệu, không theo bearer | R7.1, R7.2 | Giới hạn 60, 2 replica: lần thứ 31 trong một phút ở một tiến trình bị từ chối; hai bearer khác nhau gửi tới cùng nguồn chia chung một bộ đếm; đổi khóa sang băm bearer → test đỏ                                            |
| UL15 | Không nới Hạn mức bằng một người                      | R4.9       | Một người `PUT` nâng trần tenant từ USD 10 lên USD 50 → 409 `second_person_required`, Hạn mức hiệu lực vẫn USD 10; `DELETE` chính sách → 409; đổi `hard` sang `soft` → 409; gỡ kiểm → test đỏ                               |

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (ghi ở Comments của
  ticket).
- `make ci && make test-integration` xanh; `reviewing-feature-security` và `reviewing-deployment-security`
  đã chạy trên từng ticket có route, migration hay lane; `.claude/plans/studio.md` ghi lát W1 đã xong.

## Phụ thuộc

- studio-skeleton: sổ `platform.time_partitioned_tables` và quyền partition (studio-skeleton:R3.1; DO-02.2)
  (`.claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md`), gói và điều
  hướng (`.claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md`).
- tenant-rbac: danh mục quyền là một chủ (tenant-rbac:R1.1) — `platform.usage.read` (đưa về `active`) và
  `platform.limits.manage` đăng ký ở `.claude/plans/studio/tenant-rbac/issues/01-mot-chu-cho-quyen.md`; độ
  sâu workspace qua `platform.effective_grants` (tenant-rbac:R2.1).
- org-and-principals: cây workspace và workspace gốc cho Chuỗi phạm vi hạn mức
  (`.claude/plans/studio/org-and-principals/issues/02-thanh-vien-cap-tenant.md`).
- workflow-engine: làn `studio_runs` giao lượt chạy cho runner lúc dispatch, chỗ duy nhất gọi
  `LimitsPort.admit` (DO-21.3; `.claude/plans/studio/workflow-engine/issues/04-lan-studio-runs.md`),
  `root_run_id` và ranh giới node (`.claude/plans/studio/workflow-engine/issues/02-cot-run-va-cua-nhan-run.md`,
  `.claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md`); agent-builder: giới hạn
  hành vi trong phiên bản (`.claude/plans/studio/agent-builder/issues/03-runtime-agent.md`).
- agent-lifecycle: cùng danh sách cửa hỏi thêm câu Đóng băng (agent-lifecycle:R7.1); Lượt kiểm định xin
  lease `purpose` `eval_offline` qua `LimitsPort` (agent-lifecycle:R4.4).
- compliance-pdpl: `ResidencyGate` đứng trước `LimitsMiddleware` (R6.5) và ghi lộ trình lên Bản ghi sử dụng
  (`.claude/plans/studio/compliance-pdpl/issues/03-tuyen-du-lieu-o-model-gateway.md`).
- telemetry-and-audit: chủ tệp `retention@1.8.0` khai thời hạn `usage_events`, `usage_daily` (DO-52).
- model-connections: `ModelProfile` v2 không mang giá, chỉ dẫn chiếu Bảng giá (DO-21.5).
- Bên dùng `RateLimiterPort`: Data Hub (workflow-triggers:R5.9), kiểm trùng của custom-objects
  (custom-objects:R7.6).
- Bảng toàn tenant `platform.limit_policies`, `platform.budget_counters` theo ngoại lệ DO-01 của `CLAUDE.md`
  mục 'Tenancy and authorization'; `LimitsPort` thay `RunAllowancePort` trong câu hạn mức của `CLAUDE.md`
  mục 'Agent and tool rules' (DO-21.2) khi Đạt nhận ADR-0121 (Accepted). `resume` nay kiểm lease tiền (chi
  sau khi tiếp tục là chi mới), nhưng số run mỗi ngày không tính lại (giữ quy tắc
  `langgraph_runner.py:255-257`).
- Kiểm lại khi: danh mục quyền của tenant-rbac đổi tên → R3.5, R4.5, R4.6; cây workspace của
  org-and-principals đổi hình → R4.1, R4.4; workflow-engine đổi chỗ gọi `admit` → R4, R5; tenant-config mở
  đường đề xuất hai người cho Hạn mức → R4.9; `RateLimiterPort` có adapter Valkey → R7.

## Câu hỏi còn mở

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
- 23/10/2026 (Đạt): DO-21.1 ký: Sổ sử dụng theo lượt gọi quay lại bằng một revision mới (không downgrade
  `aefe7c1f5d9b`), giữ 13 tháng, là đo lường chứ không phải chứng từ hóa đơn; ba bên đọc ship cùng lát (lease,
  sử dụng theo lượt chạy, màn Mức độ sử dụng); đối soát cho người vận hành và chi phí theo kết quả sang W2.
  Hỏi: Q1. Sửa: mở đầu, Hiện trạng, Ngoài phạm vi, Tiêu chí xong, Phụ thuộc, ticket 02.
- 23/10/2026 (Đạt): DO-21.2: câu hạn mức của `CLAUDE.md` đổi sang `LimitsPort`; gỡ `RunAllowancePort`,
  `DailyAllowance` trong cùng lát. DO-21.5: Bảng giá là chủ duy nhất của giá, `ModelProfile` v2 chỉ dẫn
  chiếu. Sửa: Trong phạm vi, Phụ thuộc, ticket 03.
- 23/10/2026 (Đạt): DO-21.3 theo (a): một chỗ nhận là runner do làn `studio_runs` gọi lúc dispatch; hết kỳ
  thì `chat`, `manual`, `test` thành `failed` `limit_exceeded` kèm `resets_at`, `datahub`, `record_event`,
  `provider_app` giữ `queued` tới `resets_at`, `schedule` (W2) ghi `limit_refused`; thiếu đồng thời thì mọi
  loại xếp lại; lượt con và lần thử của Lượt kiểm định dùng lease của lượt gốc; 429 chỉ còn ở đường chạy
  inline cũ. DO-21.4: Lượt kiểm định xin lease `eval_offline`, agent-lifecycle/04 chờ ticket 03. Sửa: R4,
  R4.2, R4.3, R4.7, R5.1, R5.6, Ngoài phạm vi, Phụ thuộc, ticket 03.
- 23/10/2026 (Đạt): E:CLAUDE.md#tenancy-and-authorization~usage-and-limits:platform.limit_policies theo
  (a): `platform.limit_policies`, `platform.budget_counters` vào lớp bảng toàn tenant, khóa
  `(scope_type, scope_id)`, tiền lệ `platform.policy_overrides`; thêm lane dọn kỳ cũ;
  `platform.tenant_daily_spend_guard` ra khỏi danh sách bảng toàn tenant khi lát này gỡ nó. Sửa: Dữ liệu,
  R5.7, Trong phạm vi, Phụ thuộc, ticket 03.
- 23/10/2026 (Đạt): DO-49 và câu Q3 của requirements.md theo (a), thay dòng DO-49 tạm ở trên:
  `RateLimiterPort` của spec này có ở W1 với bộ đếm theo tiến trình ở `giới hạn / số replica`, khóa theo
  nguồn dữ liệu; GCRA trên Valkey là W2; không spec nào tự viết bộ giới hạn. Sửa: mở đầu, Hiện trạng, R7,
  UL14, Trong phạm vi, Ngoài phạm vi, ticket 05.
- 23/10/2026 (Đạt): DO-50 theo (a), xác nhận dòng tạm ở trên; `window_for` lấy Asia/Ho_Chi_Minh khi
  `platform.tenants.timezone` NULL (ADR-0121 (Accepted) quyết 9). DO-59.1 theo (a): W1 tính USD ước tính;
  seed gói giữ số hiện có, tiền NULL; trần của công ty thí điểm đặt qua `platform.limit_policies` trước lượt
  chạy Thật đầu tiên, số do người đặt yêu cầu nêu trước demo. DO-59.2 theo (a): phí gói cố định kèm trần
  chi phí AI mỗi tháng, không tín dụng ở v1. Hỏi: Q2. Sửa: Ngoài phạm vi, ticket 01, 03.
- 23/10/2026 (người đặt yêu cầu và Đạt): D11 phạm vi "đóng một người, mở hai người": hạ hay đặt Hạn mức một
  người cộng audit; nâng, gỡ hay đổi `hard` sang `soft` cần hai người; W1 chưa có đường đề xuất nên lệnh nới
  trả 409 `second_person_required`, nới qua tenant-config ở W2. Sửa: R4.8, R4.9, UL15, API, Màn hình, Ngoài
  phạm vi, ticket 03.
- 23/10/2026 (Đạt): DO-29.2 theo (a): công ty trả kiểm định của mình (`payer` `tenant`, `purpose`
  `eval_offline`), phần nền tảng trả có trần là W2. DO-42.3 theo (a): không thư viện biểu đồ ở v1. DO-45.1
  theo (a): bước mã tính vCPU và GB đặt trước nhân thời gian chạy. DO-51.2 theo (c): W1 gộp theo workspace,
  agent, quy trình, mục đích; theo tên người là W2. Sửa: API, Màn hình, Ngoài phạm vi, ticket 02.
- 23/10/2026 (Đạt): DO-02.2 theo (a) và OPS-b: phân vùng của `usage_events` không cấp quyền nào cho
  `dw_app`, bảng đăng ký bằng một dòng sổ; ticket 03 chờ compliance-pdpl/03 và `ResidencyGate` đứng trước
  `LimitsMiddleware`. Sửa: Hiện trạng, Dữ liệu, R3.7, R6.5, UL7, Phụ thuộc, ticket 02, 03.
- 23/10/2026 (agent, tạm): A:usage-and-limits:api: gộp `GET /api/v1/usage/limits` vào `GET /api/v1/limits`.
  Sửa: API, ticket 03. Nếu sai thì: tách lại và giao route thứ hai cho ticket 02.
- 23/10/2026 (agent, tạm): G:tenant-rbac/01~usage-and-limits:api: dùng lại `platform.usage.read` (đưa về
  `active`) thay `usage.read`, và đặt `platform.limits.manage` thay `limits.manage`. Sửa: R3.5, R4.5, R4.6,
  R4.8, API, UL10, Phụ thuộc, ticket 02, 03. Nếu sai thì: đổi tên khóa trong migration đăng ký.
- 23/10/2026 (agent, tạm): B:compliance-pdpl/03~usage-and-limits: `data_route_class`, `data_location`,
  `processor` là cột của `platform.usage_events`; compliance-pdpl/03 chờ ticket 02 để ghi chúng. Sửa: R3.1,
  Dữ liệu, ticket 02. Nếu sai thì: bỏ phần ghi lên sổ khỏi compliance-pdpl:R2.1.
- 23/10/2026 (agent, tạm): H:usage-and-limits/04~workflow-engine: `max_run_seconds` ra khỏi phạm vi W1 của
  R6.3 vì hạn chót bền của workflow-engine là W2. Sửa: Ngoài phạm vi, ticket 04. Nếu sai thì: cần cơ chế hạn
  thời gian W1 và ticket chủ.

## Danh sách ticket

| #   | Ticket                                                                                                                       |
| --- | ---------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Một chủ cho danh mục gói: platform.plan_limits thay DEFAULT_PLANS](issues/01-danh-muc-goi-mot-chu.md)                       |
| 02  | [Bảng giá theo ngày hiệu lực, sổ sử dụng theo lượt gọi và màn Mức độ sử dụng](issues/02-bang-gia-so-su-dung-va-man-hinh.md)  |
| 03  | [Hạn mức theo chuỗi phạm vi: giữ trước lúc nhận run, quyết toán từng lượt gọi](issues/03-han-muc-giu-truoc-va-quyet-toan.md) |
| 04  | [Đóng các cửa vòng qua hạn mức và giới hạn hành vi mỗi lượt chạy](issues/04-dong-cua-vong-va-gioi-han-hanh-vi.md)            |
| 05  | [Một RateLimiterPort và bộ đếm theo tiến trình cho giới hạn tốc độ W1](issues/05-cong-gioi-han-toc-do-theo-tien-trinh.md)    |
