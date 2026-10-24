# Sổ sử dụng, bảng giá và hạn mức

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Studio cần đo và chặn chi tiêu ở mức công ty, workspace, agent và quy trình (theo người dùng từ W2), việc
mà một tổng theo ngày của cả tenant không làm được. Lát này đưa lại Sổ sử dụng theo lượt gọi (D6) làm nguồn
cho hạn mức, sử dụng theo lượt chạy và màn Mức độ sử dụng, ba bên đọc ship cùng lát (đối soát cho người
vận hành là W2); đặt một Bảng giá theo ngày hiệu lực làm chủ duy nhất của "cái này tốn bao nhiêu"; biến
mọi Hạn mức cứng thành Khoản giữ trước bằng lease Postgres mở lúc nhận lượt chạy, kẹp `max_tokens` từng
lời gọi, quyết toán từng lượt gọi (ADR-0121 (Accepted)); và giữ một `RateLimiterPort` cho mọi giới hạn tốc
độ theo công ty. W1 phục vụ YC76, YC77, YC78, một chủ cho số của gói và giới hạn tốc độ của YC44 bằng bộ
đếm theo tiến trình (DO-49); GCRA trên Valkey, trần đồng thời và YC79 (hạn mức theo người và mục đích)
thuộc W2.

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
- R3.8 KHI lane `offboarding` xóa dữ liệu của một công ty đang `offboarding`, lane `offboarding` PHẢI xuất rồi
  xóa mọi dòng của công ty đó trong `platform.usage_events` (qua `platform.purge_tenant_append_only`),
  `platform.usage_daily`, `platform.limit_policies`, `platform.budget_counters` và `platform.budget_leases`
  (YC6; ADR-0121 (Accepted)).
- R3.9 NẾU `platform.purge_tenant_append_only` được gọi cho một công ty có `platform.tenants.status` khác
  `offboarding`, THÌ PostgreSQL PHẢI từ chối với SQLSTATE 23514 và không xóa dòng nào.
- R3.10 `platform.purge_tenant_append_only` PHẢI chỉ xóa dòng của đúng công ty được gọi, ở mọi bảng có
  `append_only = true` trong `platform.time_partitioned_tables` trừ `platform.audit_events`, mà thời hạn của tệp
  chính sách retention giữ.
- R3.11 KHI lane `offboarding` xóa dữ liệu của một công ty đang `offboarding`, lane `offboarding` PHẢI gọi
  `platform.purge_tenant_append_only` trong giao dịch xóa trước khi DELETE dòng nào của một bảng thường, để dòng chỉ
  thêm có khóa ngoại `ON DELETE RESTRICT` tới một bảng thường, như tin nhắn tới hội thoại (agent-builder:R4.9), đi
  trước dòng cha của nó.

### R4 — Hạn mức là chính sách trên một chuỗi phạm vi, chặn ở cửa nhận lượt chạy

Cửa nhận lượt chạy là một chỗ: runner, do làn `studio_runs` gọi lúc dispatch (DO-21.3). Spec này là chủ câu
trả lời của `LimitsPort.admit`; cách làn xử lý từng `trigger_kind` khi bị từ chối là bảng của workflow-engine
(workflow-engine:R5.9, workflow-engine:R5.10, workflow-engine:R5.11): lượt tương tác kết
thúc, lượt do sự kiện vào chờ tới kỳ sau và không bao giờ bị bỏ, còn một lần kích hoạt của lịch khi đã hết hạn
mức ghi `limit_refused` rồi bỏ qua (W2), vì dồn mọi lần lỡ sẽ xả cả loạt khi kỳ mới bắt đầu (YC77; `CLAUDE.md`
mục 'Agent and tool rules'; ADR-0121 (Accepted) quyết 3). Lượt kiểm định xin lease qua lane `studio_gate`
(agent-lifecycle:R4.4).

- R4.1 KHI một lượt chạy xin bắt đầu, cửa nhận lượt chạy PHẢI kiểm mọi phạm vi có chính sách trong Chuỗi
  phạm vi hạn mức (gói, công ty, workspace và tổ tiên, agent hoặc quy trình, lượt chạy) và chỉ cho qua khi mọi
  phạm vi có chính sách đều còn đủ.
- R4.2 [Bỏ] 24/10/2026: hình từ chối lượt tương tác khi hết kỳ thuộc bảng của workflow-engine:R5.9; spec này
  trả câu trả lời của `LimitsPort.admit` (R4.10).
- R4.3 [Bỏ] 24/10/2026: giữ `queued` tới `resets_at` lượt do sự kiện vào khi hết kỳ thuộc workflow-engine:R5.10;
  spec này trả `resets_at` (R4.10).
- R4.4 NẾU một workspace con đặt trần cao hơn phần còn lại của cha, THÌ cửa nhận lượt chạy PHẢI vẫn áp
  trần của cha (phạm vi cha có chính sách thì phải qua).
- R4.5 NẾU người giữ `platform.limits.manage` đặt một Hạn mức cao hơn Trần của gói, THÌ API hạn mức PHẢI
  trả 422 `limit_above_plan` và không đổi dòng nào.
- R4.6 NẾU người gọi thiếu `platform.limits.manage`, hoặc nhắm workspace của công ty khác, THÌ API hạn mức
  PHẢI trả 403 hoặc 404 và không đổi gì.
- R4.7 [Bỏ] 24/10/2026: xếp lại lượt chạy khi thiếu chỗ đồng thời đến ở W2 cùng trần đồng thời (R4.11), ở dòng W2
  của bảng từ chối mà workflow-engine giữ (trước là workflow-engine:R5.4).
- R4.8 KHI người giữ `platform.limits.manage` hạ một Hạn mức hay đặt Hạn mức cho một phạm vi chưa có, API
  hạn mức PHẢI áp thay đổi với một người và ghi audit `limits.policy.set` trong cùng giao dịch (D11: siết
  một người).
- R4.9 NẾU một lệnh `PUT` hay `DELETE` làm một Hạn mức lỏng hơn chính sách đang có hiệu lực (giá trị cao
  hơn, gỡ chính sách, đổi `hard` sang `soft`), THÌ API hạn mức PHẢI trả 409 `second_person_required` và
  không đổi dòng nào, vì W1 chưa có đường hai người cho việc nới (D11: nới hai người).
- R4.10 NẾU phần còn lại của một Hạn mức cứng theo kỳ không đủ lúc nhận một lượt chạy, THÌ `LimitsPort.admit`
  PHẢI trả từ chối `limit_exceeded` kèm `metric`, `scope_type`, `window`, `limit`, `used` và `resets_at`, không mở
  lease và không đổi bộ đếm nào.
- R4.11 [Bỏ] 24/10/2026: câu trả lời thiếu chỗ đồng thời của `LimitsPort.admit` đến ở W2 cùng trần đồng thời
  (Ngoài phạm vi; YC79).
- R4.12 NẾU workspace hay thành phần mà một chính sách hạn mức nhắm tới bị xóa, THÌ PostgreSQL PHẢI xóa chính
  sách đó trong cùng lệnh xóa, nên không còn chính sách mồ côi (ADR-0121 (Accepted) quyết 4).

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
- R5.7 KHI lane `retention_limits` chạy, lane PHẢI xóa dòng `platform.budget_counters` có `window_end` cũ hơn
  thời hạn dưới khóa `platform.budget_counters` (395 ngày, 13 tháng, bằng Sổ sử dụng) và lease
  `platform.budget_leases` đã đóng quá thời hạn dưới khóa `platform.budget_leases` (30 ngày), đọc cả hai từ tệp
  chính sách retention (số tạm UNVERIFIED), không chạm dòng của kỳ hay lease còn mở.

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
- R7.2 Khóa của `RateLimiterPort` PHẢI là một khóa có kiểu đã xác minh, `(tenant_id, id nguồn dữ liệu)` hay
  `(tenant_id, principal_id, object_id)`, đi cùng giới hạn và độ dài cửa sổ trượt do bên gọi nêu, không bao giờ
  là chuỗi tự do hay băm của bearer chưa xác minh.
- R7.3 KHI bên gọi hỏi `RateLimiterPort` mà không tính lượt, adapter theo tiến trình PHẢI trả khóa đã đủ giới
  hạn hay chưa trong cửa sổ trượt cùng thời điểm lượt cũ nhất ra khỏi cửa sổ, và không đổi bộ đếm (khóa
  `(tenant_id, principal_id, object_id)`, 20 lượt trong 10 phút, 1 replica: sau lượt tính thứ 20 trong 10 phút
  thì trả đã đủ, khi lượt cũ nhất qua 10 phút thì trả chưa đủ; custom-objects:R7.6).

## Trong phạm vi

- Bảng, cột và phân vùng ở mục Dữ liệu; route ở mục API.
- Mã: gói nền tảng `dw_usage` (Bảng giá, Sổ sử dụng, chính sách, bộ đếm, lease, bảng cuộn);
  `PlanCatalogPort` và `PlanEntitlementService` đọc một chủ; `PriceBook` theo ngày hiệu lực;
  `UsageLedgerPort`; `EffectiveLimits.for_admission` trên Chuỗi phạm vi hạn mức; `LimitsPort` (runtime
  khai) với `admit`, `resume`, `RunLease`, `release`; `LimitsMiddleware` thay `RunBudgetMiddleware`;
  cửa có đo `MeteredModelGateway`, `LimitedChatModelFactory`, `MeteredEmbeddingPort`, `MeteredRerankPort`;
  `ReapTarget` cho lease mồ côi; lane `usage_rollup`; lane `retention_limits`; `RateLimiterPort` với hai khóa có
  kiểu, lần hỏi không tính lượt và adapter bộ đếm theo tiến trình trên cửa sổ trượt (W1).
- Hàm của sổ `platform.time_partitioned_tables`, chủ duy nhất ở W1:
  `platform.drop_expired_partitions(cutoffs jsonb)` (mỗi bảng cha một mốc đọc từ tệp chính sách retention) và
  `platform.purge_tenant_append_only(p_tenant uuid)` cho offboarding, gọi trước mọi bảng thường trong giao dịch xóa
  (R3.8, R3.10, R3.11); spec khác không viết lại thân hai hàm này.
- Dòng thời hạn của bảng spec này tạo trong tệp chính sách retention, theo định dạng khóa `schema.table` của
  telemetry-and-audit (telemetry-and-audit:R5.6): `platform.usage_events` (ticket 02, cùng thay đổi đăng ký),
  `platform.budget_counters`, `platform.budget_leases` (ticket 03).
- Khóa quyền: `platform.usage.read` đưa về `active` (ticket 02), `platform.limits.manage` đăng ký (ticket 03),
  theo quy ước của tenant-rbac/01.
- Gỡ trong cùng lát: `RunAllowancePort` và adapter của nền tảng đáp nó, `RunBudgetLedger`, `RunSpend`,
  `ModelBudgets`, `DailyAllowance`, `SqlSpendGuard*`, lane `spend_guard_retention`,
  `platform.tenant_daily_spend_guard` (và dòng của nó trong danh sách bảng toàn tenant của
  `test_rls_coverage.py`).
- Audit: `limits.policy.set`, `limits.policy.removed`, `limits.refused`, `limits.lease.expired`.

## Ngoài phạm vi

| Việc                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | Vì sao                                                                                                                                                                                                                                                                | Chủ                                               |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| Hóa đơn, tín dụng, bảng giá bán cho khách; hiển thị VND và tỷ giá                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | Sổ là đo lường, không phải hóa đơn (D6); v1 bán phí gói cố định kèm trần chi phí AI mỗi tháng (`cost_usd_per_month`), không tín dụng (DO-59.2); VND với bảng tỷ giá có ngày ở v1.5                                                                                    | không làm (v1); usage-and-limits, đợt sau         |
| W2: nới Hạn mức (nâng, gỡ, đổi `hard` sang `soft`) và nâng giới hạn 60 sự kiện mỗi phút của một Nguồn dữ liệu (workflow-triggers:R5.9) qua đề xuất một người và duyệt của người thứ hai trong tenant-config                                                                                                                                                                                                                                                                                                                          | D11 (mở hai người); W1 chỉ siết, lệnh nới trả 409 (R4.9); W1 chưa có đường hai người để nâng một hạn mức (ADR-0110 (Accepted) quyết 2)                                                                                                                                | usage-and-limits; tenant-config, đợt sau (W2)     |
| W2: đối soát cho người vận hành và chi phí theo kết quả                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | không có bên đọc ở W1 (DO-21.1); chi phí mỗi lead (KQ12) cần sự kiện kết quả của marketing-pilot                                                                                                                                                                      | usage-and-limits; marketing-pilot, đợt sau (W2)   |
| W2: lượt `schedule` thiếu hạn mức ghi lần kích hoạt `limit_refused` rồi bỏ qua, không giữ tới `resets_at`                                                                                                                                                                                                                                                                                                                                                                                                                            | trình kích hoạt lịch là W2 (DO-21.3); dồn mọi lần lỡ sẽ xả cả loạt khi kỳ mới bắt đầu (`CLAUDE.md` mục 'Agent and tool rules'; ADR-0113 (Accepted))                                                                                                                   | workflow-triggers, đợt sau (W2)                   |
| W2: cột `max_run_seconds` của `platform.plan_limits` và giới hạn thời gian mỗi lượt chạy theo nó                                                                                                                                                                                                                                                                                                                                                                                                                                     | cột vào cùng bên đọc của nó (failure-modes #1); cần hạn chót bền và hủy xuyên tiến trình của workflow-engine, đều W2                                                                                                                                                  | usage-and-limits; workflow-engine, đợt sau (W2)   |
| W2: cảnh báo ngưỡng 80% và 100% mỗi chính sách và kỳ qua outbox (`usage.limit.threshold_crossed`), cùng cột `thresholds` của `platform.limit_policies`                                                                                                                                                                                                                                                                                                                                                                               | YC79; cột vào cùng bên đọc của nó (failure-modes #1); cần bộ đếm và chính sách của W1 trước                                                                                                                                                                           | usage-and-limits, đợt sau (W2)                    |
| W2: giới hạn tốc độ GCRA trên Valkey (adapter thứ hai của `RateLimiterPort`) và bộ điều tốc nhà cung cấp, cùng cột `requests_per_minute`, `tokens_per_minute` của `platform.plan_limits` mà chúng đọc                                                                                                                                                                                                                                                                                                                                | YC44; W1 đã có port và bộ đếm theo tiến trình (R7), nhận giới hạn do bên gọi nêu (R7.2), nên không bên nào ở W1 đọc hai cột tốc độ của gói (failure-modes #1); Valkey chỉ giữ trạng thái tốc độ; mất Valkey lùi về bộ đếm mỗi tiến trình (DO-49)                      | usage-and-limits, đợt sau (W2)                    |
| W2: hạn mức theo người dùng (giá trị `user` của `scope_type`, cột `scope_user_id` FK ghép `(tenant_id, scope_user_id)` tới `platform.tenant_members` `ON DELETE CASCADE`), theo mục đích (cột `purposes`; dựng có AI, chạy mô phỏng và chạy thử, kiểm định), theo đồng thời (cột `max_concurrent_runs` của `platform.plan_limits`, câu trả lời thiếu chỗ đồng thời của `LimitsPort.admit` kèm thời điểm thử lại, trước là R4.11); hiển thị sử dụng theo tên người; phần nền tảng trả có trần cho lượt kiểm định lại do nền tảng kích | YC79, và phần người dùng của chuỗi trong YC77; mỗi cột vào cùng bên đọc của nó (failure-modes #1); mẫu cấu hình limit theo agent học từ phân tích đối thủ (config-chang.md mẫu 4); theo tên người sau khi luật sư xác nhận thông báo cho nhân viên (DO-51.2); DO-29.2 | usage-and-limits, đợt sau (W2)                    |
| W2: BYOM (bên trả phí, giá riêng tenant, hạn mức token); đo bước mã theo vCPU và GB đặt trước nhân thời gian chạy, rerank, trích xuất, chuyển giọng nói                                                                                                                                                                                                                                                                                                                                                                              | YC79; chờ `model-connections` và `code-sandbox` (DO-43; DO-45.1 chọn đơn vị đặt trước)                                                                                                                                                                                | usage-and-limits; model-connections; code-sandbox |
| W3: hạn mức kiểu xin nâng, dự báo tốc độ đốt, phát hiện bất thường                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | v1.5 trở đi                                                                                                                                                                                                                                                           | usage-and-limits, đợt sau (W3)                    |
| Hàng đợi lượt chạy và điều phối công bằng; cổng đánh giá và ngưỡng chi phí phát hành                                                                                                                                                                                                                                                                                                                                                                                                                                                 | spec này cấp `LimitsPort` (bộ đếm đồng thời đến ở W2 cùng trần đồng thời); cổng xin lease `eval_offline` (DO-21.4)                                                                                                                                                    | workflow-engine; agent-lifecycle                  |
| Kết nối model của công ty và `model-proxy`; runtime sandbox                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | spec này định nghĩa cổng báo vCPU và GB đặt trước nhân thời gian chạy (DO-45.1) và bên trả phí                                                                                                                                                                        | model-connections; code-sandbox                   |
| Đóng băng, Tắt khẩn cấp                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | cùng middleware hỏi thêm câu của agent-lifecycle                                                                                                                                                                                                                      | agent-lifecycle                                   |

## Dữ liệu

Mọi bảng tenant: RLS ENABLE và FORCE theo tenant, grant cùng migration, tên ràng buộc theo
`NAMING_CONVENTION`, revision id hex ngẫu nhiên.

- `platform.plan_limits`: `plan_id text` khóa chính và FK `platform.plans ON DELETE CASCADE`; không
  `tenant_id`, không RLS; `dw_app` chỉ SELECT; cột `CHECK (>= 0)`: `runs_per_day`, `cost_usd_per_day`,
  `cost_usd_per_month`, `tokens_per_month` (NULL = không giới hạn); trần mỗi lượt NOT NULL:
  `max_cost_usd_per_run`, `max_tokens_per_run`, `max_steps_per_run` CHECK (1..500), `max_model_calls_per_run`,
  `max_tool_calls_per_run`; `max_run_seconds`, `max_concurrent_runs`, `requests_per_minute` và `tokens_per_minute`
  thêm ở W2, mỗi cột cùng bên đọc của nó (Ngoài phạm vi). `platform.plans.quotas`
  jsonb bị gỡ ở migration sau khi dời dữ liệu; tính năng đọc từ `platform.plans.features`.
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
  395 ngày (13 tháng, số tạm UNVERIFIED, DO-52) dưới khóa `platform.usage_events` mà ticket 02 thêm vào bản kế
  tiếp của tệp chính sách retention trong cùng thay đổi đăng ký (telemetry-and-audit:R5.6, studio-skeleton:R3.7),
  xóa bằng DROP PARTITION qua `platform.drop_expired_partitions`; vì `dw_app` không DELETE, bảng có một dòng
  `STUDIO_EXCLUSIONS` nêu cách xóa khi offboarding, `platform.purge_tenant_append_only` (R3.8;
  studio-skeleton:R4.3); index
  `(tenant_id, occurred_at)`, `(tenant_id, run_id) WHERE run_id IS NOT NULL`,
  `(lease_id) WHERE lease_id IS NOT NULL`.
- `platform.usage_daily`: RLS tenant; `UNIQUE NULLS NOT DISTINCT (tenant_id, workspace_id, day, artifact_kind, artifact_id, user_id, provider, model, operation, purpose, payer)`;
  index `(tenant_id, day)`, `(tenant_id, workspace_id, day)`; cuộn lại hôm nay và hôm qua cho tenant có
  hoạt động, ngày theo `window_for`.
- `platform.limit_policies`: RLS tenant; `scope_type` CHECK (`tenant`, `workspace`, `agent`, `workflow`) cho API
  và Chuỗi phạm vi hạn mức (`user` ở W2, Ngoài phạm vi); phạm vi cụ thể nằm ở cột khóa ngoại có kiểu
  `scope_workspace_id` (FK ghép `(tenant_id, scope_workspace_id)` tới `platform.workspaces`) và `scope_artifact_id`
  (FK ghép `(tenant_id, scope_artifact_id)` tới `studio.artifacts (tenant_id, id)`, đích là ràng buộc
  `uq_artifacts_tenant_id_id` của tenant-config, agent hay quy trình), mỗi FK `ON DELETE CASCADE` và có index
  riêng; CHECK `num_nonnulls(scope_workspace_id, scope_artifact_id) = 1` khi `scope_type` khác `tenant`, với đúng
  cột của `scope_type`, và `= 0` khi `tenant`, như chủ thể của Kho bí mật (ADR-0115 (Accepted); ADR-0121 (Accepted)
  quyết 4), để chính sách mồ côi tự gỡ (R4.12); `metric`, `window_kind`, `kind` CHECK (`hard`, `soft`);
  `limit_value numeric(20,8) CHECK (>= 0)`; `version`; `created_by`; UNIQUE NULLS NOT DISTINCT trên `tenant_id`,
  `scope_workspace_id`, `scope_artifact_id`, `metric`, `window_kind`; trigger `updated_at` nhường giá trị lệnh nêu;
  `scope_user_id`, `thresholds` và `purposes` đến ở W2 cùng bên đọc (Ngoài phạm vi). Bảng toàn tenant: không cột
  `workspace_id` (phạm vi nằm ở cột có kiểu, tên `scope_*` như ADR-0121 (Accepted) quyết 4), có tên và lý do trong
  danh sách bảng toàn tenant mà `test_rls_coverage.py` giữ (`CLAUDE.md` mục 'Tenancy and authorization',
  ngoại lệ của DO-01).
- `platform.budget_counters`: khóa chính `(tenant_id, scope_type, scope_id, metric, window_kind, window_start)`;
  `window_end`, `used`, `reserved`, `updated_at`; `CHECK (used >= 0 AND reserved >= 0)`; RLS tenant và
  policy drain; bảng toàn tenant, khóa `(scope_type, scope_id)` (ADR-0121 (Accepted)); lane `retention_limits`
  xóa dòng có `window_end` cũ hơn thời hạn dưới khóa `platform.budget_counters` của tệp chính sách retention
  (395 ngày, R5.7), do ticket 03 thêm vào tệp.
- `platform.budget_leases`: `id`, `tenant_id`, `workspace_id`, `run_id`, `root_run_id`, `purpose`,
  `counter_keys jsonb`, `reserved_usd`, `reserved_tokens`, `settled_*`, `rolled_*`, `in_flight_*`,
  `state`, `close_reason`, `opened_at`, `heartbeat_at`, `expires_at`, `closed_at`; `UNIQUE (tenant_id, root_run_id) WHERE state='open'`;
  index từng phần `expires_at WHERE state='open'`; lane `retention_limits` xóa lease đóng quá thời hạn dưới khóa
  `platform.budget_leases` của tệp chính sách retention (30 ngày, R5.7), do ticket 03 thêm vào tệp.

## API

- `GET /api/v1/runs/{run_id}/usage` (`runs.read`, RLS và workspace): tổng theo thao tác, model, nguồn
  chi phí.
- `GET /api/v1/usage/summary` (`platform.usage.read`, workspace trong tập được phép): gộp theo workspace,
  agent, quy trình và mục đích; W1 không có chiều gộp theo người (DO-51.2).
- `GET /api/v1/limits` (`platform.usage.read`): mỗi chính sách kèm Hạn mức hiệu lực, bộ đếm của kỳ hiện tại
  và giờ đặt lại; không có route `/api/v1/usage/limits` riêng. `PUT /api/v1/limits/{scope_type}/{scope_id}`
  và `DELETE` (`platform.limits.manage`, `Idempotency-Key`; `{scope_type}` là `tenant`, `workspace`, `agent` hay
  `workflow`, `user` đến ở W2): siết áp ngay với một người (R4.8); nới trả 409
  `second_person_required` ở W1 (R4.9); cao hơn Trần của gói → 422 `limit_above_plan`.
- Lỗi theo vỏ problem+json của ADR-0108 (Accepted); `details.reason_code`: `limit_exceeded`,
  `limit_above_plan`, `second_person_required`.

## Màn hình

- Màn Mức độ sử dụng `/usage` (antd Statistic cho chi phí, token, số run; Table nhóm theo workspace,
  agent, quy trình, mục đích, không theo người ở W1; Progress cho hạn mức; không thư viện biểu đồ ở v1,
  biểu đồ cần ADR ngoại lệ riêng khi có YC đòi, ADR-0101 (Accepted) quyết 6, DO-42.3), đọc
  `GET /api/v1/usage/summary`; nhúng tab ở trang agent
  và quy trình (mẫu cấu hình limit và usage theo agent, config-chang.md mẫu 4).
- Màn Cấu hình hạn mức (antd Form, Table) ở cấp tenant và workspace, hiện Trần của gói và Hạn mức hiệu
  lực; W1 chỉ cho hạ hay đặt mới, nới mở ở W2 cùng đề xuất hai người; cấp agent và quy trình nhúng sau
  (agent-builder, workflow-builder-ui).

## Kiểm soát

| #    | Kiểm soát                                            | Yêu cầu           | Test âm                                                                                                                                                                                                                                                                                                     |
| ---- | ---------------------------------------------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| UL1  | Số của gói có một chủ trong database                 | R1.1, R1.2        | Xóa dòng `platform.plan_limits` của một gói → nhận lượt chạy bị từ chối, không hiểu thành "không giới hạn"; khai lại dict gói trong mã → test kiến trúc đỏ                                                                                                                                                  |
| UL2  | Hạn mức cứng giữ trước khi chi                       | R5.1              | `runs_per_day` của tenant còn đúng 3 lượt: 10 lượt chạy gốc nhận song song → đúng 3 được nhận và mở lease, 7 lượt nhận `limit_exceeded`, bộ đếm không vượt trần; gỡ khóa bộ đếm theo thứ tự → test đỏ                                                                                                       |
| UL3  | `max_tokens` kẹp theo lease                          | R5.2              | Lease còn đủ cho 100 token output → lời gọi mang `max_tokens <= 100`; gỡ kẹp → test đỏ                                                                                                                                                                                                                      |
| UL4  | Không cửa nào vòng qua hạn mức                       | R6.1, R6.2        | Lease cạn: gọi thẳng gateway có cấu trúc, chat, embedding, rerank, lane nạp → mỗi cửa bị từ chối; `RuntimeSeam` lộ gateway thô → test field đỏ                                                                                                                                                              |
| UL5  | Thiếu số dùng không thành 0                          | R3.3              | Adapter không báo usage → dòng `estimated` bằng ước tính; gỡ → test đỏ                                                                                                                                                                                                                                      |
| UL6  | Lease mồ côi được thu hồi                            | R5.4              | Tiến trình chết giữa lời gọi → sau `expires_at` lease đóng, phần đang bay tính, audit `system:reaper`; gỡ `ReapTarget` → test đỏ                                                                                                                                                                            |
| UL7  | Cách ly tenant                                       | R3.6, R3.7        | Đọc, ghi `budget_counters`, `budget_leases`, `usage_events`, `limit_policies` của tenant B từ A → 0 dòng hoặc 404; kết nối không đặt tenant đọc 0 dòng; đọc một phân vùng của `usage_events` theo tên → `permission denied`                                                                                 |
| UL8  | Workspace con không vượt cha                         | R4.4              | Cha cap USD 10 đã dùng hết, con cap USD 50 → lượt chạy ở con bị chặn; gỡ vòng tổ tiên → test đỏ                                                                                                                                                                                                             |
| UL9  | Không đặt Hạn mức trên Trần của gói                  | R4.5              | `PUT` hạn mức tenant cao hơn gói → 422 `limit_above_plan`, không dòng nào đổi                                                                                                                                                                                                                               |
| UL10 | Chỉ người có quyền đặt Hạn mức                       | R4.6              | Thiếu `platform.limits.manage` → 403; workspace tenant khác → 404                                                                                                                                                                                                                                           |
| UL11 | Tạm dừng nhả tiền                                    | R5.3              | Lượt chạy chờ duyệt → `reserved` của lượt về 0; tiếp tục → giữ lại số đã tiêu; gỡ nhả → test đỏ                                                                                                                                                                                                             |
| UL12 | Giá không định lại lịch sử                           | R2.4              | Đổi Bảng giá → dòng cũ giữ `price_book_version` và chi phí cũ                                                                                                                                                                                                                                               |
| UL13 | Hạn mức giữa lượt chạy dừng sạch, không hạ ngầm      | R5.5, R6.3        | Trần cạn giữa lượt → dừng ở ranh giới kế tiếp `limit_exceeded`, không cắt giữa một bước gửi, không hạ model; gỡ kiểm ranh giới → test đỏ                                                                                                                                                                    |
| UL14 | Giới hạn tốc độ theo khóa có kiểu, không theo bearer | R7.1, R7.2, R7.3  | Giới hạn 60, 2 replica: lần thứ 31 trong một phút ở một tiến trình bị từ chối; hai bearer khác nhau gửi tới cùng nguồn chia chung một bộ đếm; khóa (tenant, người gọi, đối tượng) 20 trong 10 phút: lần hỏi không tính lượt không đổi bộ đếm, sau lượt thứ 20 trả đã đủ; đổi khóa sang băm bearer → test đỏ |
| UL15 | Không nới Hạn mức bằng một người                     | R4.9              | Một người `PUT` nâng trần tenant từ USD 10 lên USD 50 → 409 `second_person_required`, Hạn mức hiệu lực vẫn USD 10; `DELETE` chính sách → 409; đổi `hard` sang `soft` → 409; gỡ kiểm → test đỏ                                                                                                               |
| UL16 | Xóa sổ chỉ thêm chỉ khi công ty đang offboarding     | R3.8, R3.9, R3.10 | Gọi `platform.purge_tenant_append_only` cho công ty `active` → 23514, 0 dòng xóa; công ty `offboarding` → dòng của nó trong `usage_events` xóa hết, dòng của công ty khác và `audit_events` còn; gỡ kiểm trạng thái khỏi hàm → test đỏ                                                                      |

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (ghi ở Comments của
  ticket).
- `make ci && make test-integration` xanh; `reviewing-feature-security` và `reviewing-deployment-security`
  đã chạy trên từng ticket có route, migration hay lane; `.claude/plans/studio.md` ghi lát W1 đã xong.

## Phụ thuộc

- studio-skeleton: sổ `platform.time_partitioned_tables` và quyền partition (studio-skeleton:R3.1; DO-02.2)
  (`.claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md`), gói và điều
  hướng (`.claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md`).
- studio-skeleton: R3.7 đọc thời hạn của mỗi bảng `append_only` dưới khóa `schema.table` (studio-skeleton:R3.7);
  test phủ offboarding và `STUDIO_EXCLUSIONS` cho bảng tenant mới của `platform` (studio-skeleton:R4.3).
- tenant-rbac: danh mục quyền là một chủ (tenant-rbac:R1.1), bảng do
  `.claude/plans/studio/tenant-rbac/issues/01-mot-chu-cho-quyen.md` tạo; `platform.usage.read` đưa về `active` ở
  ticket 02 và `platform.limits.manage` đăng ký ở ticket 03, mỗi khóa trong migration của ticket dùng nó theo quy
  ước của ticket đó; độ sâu workspace qua `platform.effective_grants` (tenant-rbac:R2.1); ticket 02 và 03 chờ
  `.claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md`, và INSERT khóa của ticket 03 nêu mọi cột NOT
  NULL của bảng lúc đó, gồm `risk` của tenant-rbac/01 và `tenant_grantable` của tenant-rbac/02.
- tenant-config: `studio.artifacts` với `uq_artifacts_tenant_id_id UNIQUE (tenant_id, id)` làm đích của FK ghép
  `scope_artifact_id` (`.claude/plans/studio/tenant-config/issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md`); ticket
  03 nối tới ticket đó qua workflow-engine/02 và tenant-config/04.
- foundations-hardening: ticket 01 chờ
  `.claude/plans/studio/foundations-hardening/issues/03-quyen-dw-app-va-rls-initplan.md` để quyền ghi và cột của
  `platform.plans` đổi theo một thứ tự; ticket 02 chờ
  `.claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md` vì cùng sửa lane
  `offboarding` (gọi `platform.purge_tenant_append_only` trước vòng DELETE bảng thường, R3.11).
- org-and-principals: cây workspace và workspace gốc cho Chuỗi phạm vi hạn mức
  (`.claude/plans/studio/org-and-principals/issues/02-thanh-vien-cap-tenant.md`); hàm xóa người dùng `service` của
  `.claude/plans/studio/org-and-principals/issues/03-tai-khoan-dich-vu-run-as.md` chạy sau cùng trong cùng giao dịch
  xóa, sau mọi bảng của công ty, nên ticket đó chờ ticket 02 (cạnh nằm ở ticket đó).
- workflow-engine: làn `studio_runs` giao lượt chạy cho runner lúc dispatch, chỗ duy nhất gọi
  `LimitsPort.admit`, và là chủ bảng xử lý từ chối theo `trigger_kind` (workflow-engine:R5.9,
  workflow-engine:R5.10, workflow-engine:R5.11), nên workflow-engine/04 chờ ticket 03
  (DO-21.3; `.claude/plans/studio/workflow-engine/issues/04-lan-studio-runs.md`),
  `root_run_id` và ranh giới node (`.claude/plans/studio/workflow-engine/issues/02-cot-run-va-cua-nhan-run.md`,
  `.claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md`); agent-builder: giới hạn
  hành vi trong phiên bản (`.claude/plans/studio/agent-builder/issues/03-runtime-agent.md`), ticket đó chờ ticket
  03 vì `LimitsMiddleware` thay `RunBudgetMiddleware` trong ngăn xếp mà nó giữ thứ tự (ADR-0117 (Accepted) quyết 5).
- agent-lifecycle: cùng danh sách cửa hỏi thêm câu Đóng băng (agent-lifecycle:R7.1); Lượt kiểm định xin
  lease `purpose` `eval_offline` qua `LimitsPort` (agent-lifecycle:R4.4).
- compliance-pdpl: `ResidencyGate` đứng trước `LimitsMiddleware` ở mọi cửa chạm model (R6.5) và ghi lộ trình lên
  Bản ghi sử dụng (`.claude/plans/studio/compliance-pdpl/issues/03-tuyen-du-lieu-o-model-gateway.md`); ở cửa vòng
  agent, vị trí của nó trong ngăn xếp (ngay sau `StudioModelSelection`, trước `LimitsMiddleware`) do agent-builder/03
  giữ, vì ticket đó giữ thứ tự ngăn xếp (ADR-0117 (Accepted) quyết 5).
- telemetry-and-audit: chủ định dạng tệp chính sách retention (khóa `schema.table`, telemetry-and-audit:R5.6) và
  lane lưu giữ; spec này thêm thời hạn của `usage_events` (ticket 02) và của `budget_counters`, `budget_leases`
  (ticket 03) trong cùng thay đổi tạo bảng, còn thời hạn `usage_daily` (760 ngày) do telemetry-and-audit/03 khai
  (DO-52). Tệp đi theo một chuỗi ticket bắt đầu từ ticket 02, mỗi ticket một phiên bản mới: ticket 02 (bản đầu có mục
  khóa `schema.table`, kể cả `platform.audit_events`), ticket 03, rồi telemetry-and-audit/03 chờ ticket 03;
  studio-skeleton/01 không sửa tệp, nó đọc `retention@1.7.0` qua ánh xạ tạm mà ticket 02 bỏ (V4.P1).
- model-connections: `ModelProfile` v2 không mang giá, chỉ dẫn chiếu Bảng giá (DO-21.5); ticket 02 chờ
  `.claude/plans/studio/model-connections/issues/02-model-resolver-theo-tenant.md` vì cả hai sửa
  `model/profiles.py` và `configs/models/*.yaml`.
- Bên dùng `RateLimiterPort`: Data Hub (workflow-triggers:R5.9, khóa nguồn dữ liệu, 60 mỗi phút cố định ở W1, việc
  nâng là W2 qua đường hai người ở Ngoài phạm vi), kiểm trùng của custom-objects (custom-objects:R7.6, khóa người gọi
  và đối tượng, 20 trong 10 phút trượt, DO-35).
- Bảng toàn tenant `platform.limit_policies`, `platform.budget_counters` theo ngoại lệ DO-01 của `CLAUDE.md`
  mục 'Tenancy and authorization'; `LimitsPort` thay `RunAllowancePort` trong câu hạn mức của `CLAUDE.md`
  mục 'Agent and tool rules' (DO-21.2) khi Đạt nhận ADR-0121 (Accepted). `resume` nay kiểm lease tiền (chi
  sau khi tiếp tục là chi mới), nhưng số run mỗi ngày không tính lại (giữ quy tắc
  `langgraph_runner.py:255-257`).
- Kiểm lại khi: danh mục quyền của tenant-rbac đổi tên → R3.5, R4.5, R4.6; cây workspace của
  org-and-principals đổi hình → R4.1, R4.4; workflow-engine đổi chỗ gọi `admit` hay bảng từ chối → R4, R4.10,
  R5; telemetry-and-audit đổi định dạng tệp retention → R5.7, Dữ liệu; tenant-config mở
  đường đề xuất hai người cho Hạn mức → R4.9; tenant-config đổi khóa duy nhất của `studio.artifacts` → Dữ liệu,
  ticket 03; agent-builder/03 đổi thứ tự ngăn xếp agent → R6.5; `RateLimiterPort` có adapter Valkey → R7 và hai cột
  tốc độ của `platform.plan_limits`; foundations-hardening hay org-and-principals đổi thứ tự trong giao dịch xóa của
  offboarding → R3.11, ticket 02.

## Câu hỏi còn mở

## Quyết định

- 23/10/2026 (người yêu cầu): D6 (DO-21, chờ Đạt ký): đưa lại Sổ sử dụng theo lượt gọi làm nguồn cho
  hạn mức, màn Mức độ sử dụng và đối soát, kèm bên đọc từ ngày đầu. Hỏi: Q1. Sửa: R2, R3, R5.
- 23/10/2026 (người yêu cầu): D13 (DO-19): model của tenant (BYOM) đi qua `model-proxy` riêng (bản LiteLLM
  không trạng thái); nền tảng giữ khóa trong vault và tiêm theo lời gọi. Sửa: Ngoài phạm vi (BYOM W2).
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
- 24/10/2026 (Đạt): Q-R7: lượt do sự kiện vào thiếu hạn mức chờ ở hàng đợi, không bao giờ bị bỏ; một lần kích
  hoạt của lịch khi đã hết hạn mức ghi `limit_refused` rồi bỏ qua, vì dồn mọi lần lỡ sẽ xả cả loạt khi kỳ mới bắt
  đầu; câu hạn mức của `CLAUDE.md` mục 'Agent and tool rules' đã sửa theo, đúng DO-21.3 và ADR-0113 (Accepted)
  (E:CLAUDE.md#agent-and-tool-rules\~usage-and-limits:ngoài-phạm-vi). Sửa: R4, Ngoài phạm vi.
- 24/10/2026 (Đạt): một chủ cho bảng xử lý từ chối theo `trigger_kind` là workflow-engine (workflow-engine:R5.4,
  workflow-engine:R5.9, workflow-engine:R5.10, workflow-engine:R5.11); spec này chỉ trả câu trả lời của
  `LimitsPort.admit` với `metric` và `resets_at`, và workflow-engine/04 chờ ticket 03
  (A:usage-and-limits:R4.2\~workflow-engine:R5.9). Sửa: R4, R4.2, R4.3, R4.7 (rút), thêm R4.10, R4.11, Phụ
  thuộc, ticket 03.
- 24/10/2026 (Đạt): `platform.budget_counters` giữ 13 tháng (395 ngày), bằng Sổ sử dụng, và
  `platform.budget_leases` 30 ngày sau khi đóng; cả hai đọc từ tệp chính sách retention, số tạm UNVERIFIED, do
  ticket 03 thêm vào tệp (D:ADR-0121 (Accepted)\~usage-and-limits:R5.7). Sửa: R5.7, Dữ liệu, Trong phạm vi,
  ticket 03.
- 24/10/2026 (Đạt): `platform.limit_policies` thay `(scope_type, scope_id)` đa hình bằng cột khóa ngoại có kiểu
  theo phạm vi (workspace, người dùng, thành phần) với CHECK `num_nonnulls` và `ON DELETE CASCADE`, để hạn mức
  mồ côi tự gỡ (F:ADR-0121 (Accepted)\~usage-and-limits:dữ-liệu; ADR-0121 (Accepted) quyết 4). Sửa: thêm R4.12,
  Dữ liệu, ticket 03.
- 24/10/2026 (agent, tạm): `scope_type` ở lại trên `platform.limit_policies` cho API và Chuỗi phạm vi hạn mức,
  CHECK buộc đúng cột có kiểu của nó; người dùng nhắm qua `platform.tenant_members`, nên rời công ty thì hạn mức
  của người đó tự gỡ. Sửa: Dữ liệu, ticket 03. Nếu sai thì: bỏ `scope_type` và suy phạm vi từ cột khác NULL.
- 24/10/2026 (Đạt): DO-35, số tạm UNVERIFIED: tối đa 20 lần 409 `duplicate_value` mỗi người, mỗi đối tượng,
  trong cửa sổ trượt 10 phút; `RateLimiterPort` nhận khóa có kiểu (công ty, người gọi, đối tượng), độ dài cửa sổ
  do bên gọi nêu và một lần hỏi không tính lượt (B:custom-objects:R7.6\~usage-and-limits:R7.2). Sửa: R7.2, thêm
  R7.3, UL14, Phụ thuộc, ticket 05.
- 24/10/2026 (Đạt): cột `max_run_seconds` của `platform.plan_limits` vào W2 cùng bên đọc của nó
  (H:usage-and-limits:dữ-liệu\~usage-and-limits:ngoài-phạm-vi). Sửa: Dữ liệu, Ngoài phạm vi, ticket 01.
- 24/10/2026 (Đạt): `platform.drop_expired_partitions(cutoffs jsonb)` có một chủ là ticket 02 ở W1, mỗi bảng cha
  một mốc đọc từ tệp chính sách retention; spec khác không viết lại thân hàm
  (A:studio-skeleton:ngoài-phạm-vi\~usage-and-limits:spec). Sửa: Trong phạm vi, ticket 02.
- 24/10/2026 (Đạt): telemetry-and-audit sở hữu định dạng tệp chính sách retention (khóa `schema.table`) và lane;
  mỗi ticket đăng ký một bảng `append_only` tự thêm thời hạn của bảng mình trong cùng thay đổi, nên ticket 02 thêm
  `platform.usage_events` (I:studio-skeleton:R3.7\~usage-and-limits/02). Sửa: Dữ liệu, Trong phạm vi, Phụ thuộc,
  ticket 02.
- 24/10/2026 (Đạt): offboarding xuất rồi xóa mọi bảng tenant của spec này; bảng mà `dw_app` không có DELETE vào
  `STUDIO_EXCLUSIONS` kèm cách xóa, theo cách sửa thứ hai mà studio-skeleton:R4.3 nhận
  (H:ADR-0121 (Accepted)\~usage-and-limits:dữ-liệu). Sửa: thêm R3.8, Dữ liệu, ticket 02.
- 24/10/2026 (agent, tạm): cách xóa khi offboarding cho mọi bảng `append_only` của sổ là một hàm SECURITY DEFINER
  `platform.purge_tenant_append_only(p_tenant uuid)` do ticket 02 tạo cạnh `platform.drop_expired_partitions`:
  đọc sổ, bỏ qua `platform.audit_events` (thời hạn của nó là việc của tệp retention, không của offboarding), chỉ
  chạy cho công ty đang `offboarding`; lane `offboarding` gọi nó sau khi xuất. Sửa: thêm R3.9, R3.10, UL16,
  Trong phạm vi, ticket 02. Nếu sai thì: mỗi bảng một hàm xóa riêng, hay bảng chỉ thêm giữ tới hết thời hạn.
- 24/10/2026 (Đạt): ticket 01 chờ foundations-hardening/03 (C:foundations-hardening/03\~usage-and-limits/01);
  ticket 02 chờ model-connections/02 (C:model-connections/02\~usage-and-limits/02); agent-builder/03 chờ ticket
  03, cạnh nằm ở ticket đó (C:agent-builder/03\~usage-and-limits/03). Sửa: Phụ thuộc, ticket 01, 02, 03.
- 24/10/2026 (Đạt): mỗi ticket dùng một khóa quyền đăng ký khóa đó trong migration của mình theo quy ước của
  tenant-rbac/01: ticket 02 đưa `platform.usage.read` về `active`, ticket 03 đăng ký `platform.limits.manage`
  (B:agent-lifecycle:phụ-thuộc\~tenant-rbac/01). Sửa: Trong phạm vi, Phụ thuộc, ticket 02, 03.
- 24/10/2026 (người đặt yêu cầu và Đạt): D11, W1 chưa có đường hai người cho việc nâng Hạn mức, nên mọi lệnh nới
  bị khóa ở W1 (đóng khi thiếu, R4.9 như đã viết); trần của công ty thí điểm đặt đúng lúc gieo
  (marketing-pilot:R1.6). Sửa: không đổi R4.9.
- 24/10/2026 (Đạt): dịch vụ proxy model của tenant tên `model-proxy` ở mọi nơi; thư viện biểu đồ cần một ADR ngoại
  lệ riêng theo ADR-0101 (Accepted) quyết 6 (N10). Sửa: Ngoài phạm vi, dòng D13, Màn hình.
- 24/10/2026 (Đạt): tên cột phạm vi có kiểu của `platform.limit_policies` giữ như spec, `scope_workspace_id`,
  `scope_user_id`, `scope_artifact_id`, và ADR-0121 (Accepted) quyết 4 đổi theo, vì bảng toàn tenant không mang cột
  `workspace_id` (`CLAUDE.md` mục 'Tenancy and authorization'; F:ADR-0121 (Accepted)\~usage-and-limits:spec). Sửa:
  Dữ liệu.
- 24/10/2026 (agent, tạm): V4.P6: theo YC79 và ADR-0121 (Accepted), W1 bỏ phạm vi `user` (giá trị `user` của CHECK
  `scope_type`, R4.1, `PUT`) và trần đồng thời (rút R4.11, UL2 thử bằng `runs_per_day`); `purposes`, `thresholds`
  sang W2 cùng bên đọc, và cũng vậy cột `scope_user_id` (tên giữ theo dòng trên), `max_concurrent_runs` của
  `platform.plan_limits`, và `requests_per_minute`, `tokens_per_minute` của bảng đó cùng bên đọc GCRA, vì không bên
  đọc nào ở W1 (`RateLimiterPort` nhận giới hạn do bên gọi nêu, R7.2; failure-modes #1)
  (H:usage-and-limits:R4.1\~usage-and-limits:spec). Sửa: mở đầu, R4, R4.1, R4.7, R4.11, R4.12, Ngoài phạm vi, Dữ
  liệu, API, UL2, Phụ thuộc, ticket 01, 03. Nếu sai thì: W1 nhận phạm vi người dùng và trần đồng thời, khôi phục
  R4.11, cột `scope_user_id`, `max_concurrent_runs` và hai cột tốc độ cùng một bên đọc W1 của chúng, và ghi YC79 một
  phần ở W1.
- 24/10/2026 (agent, tạm): V4.P1: tệp chính sách retention giữ một tệp có phiên bản
  `configs/policies/retention@<semver>.yaml`; các ticket sửa tệp đi thành một chuỗi bắt đầu từ ticket 02, mỗi ticket
  ra một phiên bản mới: ticket 02, ticket 03, telemetry-and-audit/03, agent-lifecycle/04, workflow-triggers/02,
  compliance-pdpl/04, agent-builder/04, compliance-pdpl/06; ticket 02 là bản đầu có mục khóa `schema.table`, và
  studio-skeleton/01 không sửa tệp, nó đọc `retention@1.7.0` qua ánh xạ tạm (C:configs:spec\~telemetry-and-audit/03).
  Sửa: Phụ thuộc, ticket 02, 03. Nếu sai thì: tách tệp theo bảng, sửa telemetry-and-audit:R5.6 và ADR-0122 (Accepted)
  quyết 7.
- 24/10/2026 (agent, tạm): ticket 02 và 03 chờ tenant-rbac/02; INSERT khóa `platform.limits.manage` của ticket 03 nêu
  mọi cột NOT NULL có lúc đó, gồm `tenant_grantable` của tenant-rbac/02 và `risk` của tenant-rbac/01, theo
  ADR-0104 (Accepted) quyết 1 (C:custom-objects/02\~tenant-rbac/02). Sửa: Phụ thuộc, ticket 02, 03. Nếu sai thì:
  tenant-rbac/01 tạo cột kèm sửa ADR-0104 (Accepted) quyết 1.
- 24/10/2026 (agent, tạm): lane `offboarding` gọi `platform.purge_tenant_append_only` trong giao dịch xóa trước vòng
  DELETE bảng thường, vì một bảng chỉ thêm có thể mang khóa ngoại `ON DELETE RESTRICT` tới một bảng thường: khóa
  ngoại ghép của `studio.conversation_messages` tới `studio.conversations` là `ON DELETE RESTRICT`, để một DELETE của
  `dw_app` lên hội thoại không kéo theo xóa tin nhắn chỉ thêm (agent-builder:R4.9), nên tin nhắn đi trước hội thoại;
  hàm xóa người dùng `service` của org-and-principals/03 chạy sau cùng, sau mọi bảng của công ty. Sửa: thêm R3.11,
  Trong phạm vi, Phụ thuộc, ticket 02. Nếu sai thì: lời gọi hàm đứng sau vòng DELETE, và khóa ngoại của tin nhắn đổi
  sang `ON DELETE CASCADE`, mở cho `dw_app` một đường xóa tin nhắn chỉ thêm qua hội thoại.
- 24/10/2026 (agent, tạm): mục đích `test_run` ở dòng W2 của hạn mức theo mục đích gọi là "chạy mô phỏng và chạy
  thử", vì lượt qua cửa chạy thử ở W1 là lượt `simulate`, mà glossary gọi là chạy mô phỏng và dành "chạy thử" cho chế
  độ `test` (`docs/platform/CONTEXT.md`, Run mode); YC79 đổi cùng chữ. Sửa: Ngoài phạm vi. Nếu sai thì: hai chỗ cùng
  giữ "chạy thử" và glossary nới nghĩa của từ đó.

## Danh sách ticket

| #   | Ticket                                                                                                                       |
| --- | ---------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Một chủ cho danh mục gói: platform.plan_limits thay DEFAULT_PLANS](issues/01-danh-muc-goi-mot-chu.md)                       |
| 02  | [Bảng giá theo ngày hiệu lực, sổ sử dụng theo lượt gọi và màn Mức độ sử dụng](issues/02-bang-gia-so-su-dung-va-man-hinh.md)  |
| 03  | [Hạn mức theo chuỗi phạm vi: giữ trước lúc nhận run, quyết toán từng lượt gọi](issues/03-han-muc-giu-truoc-va-quyet-toan.md) |
| 04  | [Đóng các cửa vòng qua hạn mức và giới hạn hành vi mỗi lượt chạy](issues/04-dong-cua-vong-va-gioi-han-hanh-vi.md)            |
| 05  | [Một RateLimiterPort và bộ đếm theo tiến trình cho giới hạn tốc độ W1](issues/05-cong-gioi-han-toc-do-theo-tien-trinh.md)    |
