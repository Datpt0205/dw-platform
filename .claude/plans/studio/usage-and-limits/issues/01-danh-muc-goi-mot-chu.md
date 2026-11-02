# 01 — Một chủ cho danh mục gói dịch vụ: platform.plan_limits thay DEFAULT_PLANS

Status: ready-for-agent
Blocked by: .claude/plans/studio/foundations-hardening/issues/03-quyen-dw-app-va-rls-initplan.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, UL1

## Mục tiêu

Số giới hạn của một Gói dịch vụ về một chủ trong database, đóng drift `failure-modes.md` #2 giữa
`DEFAULT_PLANS` và `platform.plans` (spec R1). Mọi bên đọc giới hạn gói đọc từ `platform.plan_limits`.

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên) tạo `platform.plan_limits`: `plan_id text` khóa chính và FK
   `platform.plans ON DELETE CASCADE`; không `tenant_id`, không RLS; `dw_app` chỉ SELECT (grant trong
   migration, khẳng định ở `test_privileges.py`); cột `CHECK (>= 0)` `runs_per_day`, `cost_usd_per_day`,
   `cost_usd_per_month`, `tokens_per_month` (NULL = không giới hạn); trần mỗi lượt NOT NULL `max_cost_usd_per_run`,
   `max_tokens_per_run`, `max_steps_per_run` CHECK (BETWEEN 1 AND 500), `max_model_calls_per_run`,
   `max_tool_calls_per_run`. Không có cột `max_run_seconds`, `max_concurrent_runs`, `requests_per_minute` hay
   `tokens_per_minute` ở W1: mỗi cột vào ở W2 cùng bên đọc của nó, hai cột tốc độ cùng GCRA (Ngoài phạm vi của spec).
2. Seed giữ số hiện tại: `runs_per_day` 20, 200, 2000; tiền NULL (DO-59.1: số tiền của gói chỉ cần trước
   GA; trần của công ty thí điểm đặt qua `platform.limit_policies`, usage-and-limits/03); trần mỗi lượt như nhau
   ở ba gói: `max_cost_usd_per_run` 2.0 và `max_tokens_per_run` 120000 (mặc định `ModelBudgets`,
   `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py:61-62`), `max_steps_per_run` 50
   (mặc định `recursion_limit`, `packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:82`, `le=500`
   bằng CHECK 1..500), `max_model_calls_per_run` 50 và `max_tool_calls_per_run` 200 (Comments 2026-11-02, B3).
3. Migration mới chuyển dữ liệu `platform.plans.quotas` sang cột rồi bỏ cột `quotas` (không sửa
   baseline); tính năng đọc từ `platform.plans.features`.
4. `PlanCatalogPort` (dw_platform khai) có `async limits(plan_id) -> PlanLimits | None`; adapter đọc
   `platform.plan_limits` dưới `dw_app`, cache trong tiến trình theo `plan_id` (danh mục không phải dữ liệu tenant)
   với TTL 30 giây (như `DEFAULT_TTL_SECONDS`,
   `packages/python/dw_platform/src/dw_platform/adapters/persistence/caching_lookup.py:27`) và đồng hồ tiêm; gói
   thiếu dòng cũng được cache là thiếu. Lỗi đọc database lan ra cho bên gọi, không bao giờ trả số cũ trong cache
   hay "không giới hạn", nên lượt chạy không được nhận. `PlanEntitlementService` nhận `PlanCatalogPort` thay
   `Mapping[str, Plan]`; `runs_per_day` và `spend_usd_per_day` (cột `cost_usd_per_day`) thành `async`, và
   `RunAllowancePort` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/ports.py:95-107`) cùng hai chỗ gọi
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/allowance.py:65`, `allowance.py:86`) đổi theo (ticket 03
   gỡ port này). `has_feature` chỉ còn đọc `context.has_feature`, vì tính năng của gói đã vào `AccessContext` từ
   `platform.plans.features` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:125-141`
   ở `1aa6ea7`). Xóa `DEFAULT_PLANS` (`entitlement.py:13-36`) và nhánh đôi ở `has_feature`
   (`entitlement.py:45-49`); hai composition root (`apps/api/src/dw_api/bootstrap/wiring.py:181`,
   `apps/worker/src/dw_worker/composition.py:382`) dựng adapter; 28 tệp test đang dùng `DEFAULT_PLANS` chuyển sang
   một catalogue giả trong `dw_platform.testing` nhận số từ chính test, không tự khai số gói nào.
5. Test kiến trúc (quét `ast`, unit test của `dw_platform`) trên mọi cây `packages/python/*/src` và `apps/*/src`:
   đỏ khi có tên `DEFAULT_PLANS`, hay một lời gọi `Plan(` hoặc `PlanLimits(` ngoài module adapter đọc
   `platform.plan_limits`.

## Tiêu chí chấp nhận

- [ ] R1.1 (UL1): mọi bên đọc giới hạn gói đọc `platform.plan_limits`; test kiến trúc của bước 5 xanh trên cây
      nguồn; khai lại `DEFAULT_PLANS` trong `entitlement.py` → đỏ; thêm một lời gọi `Plan(...)` hay `PlanLimits(...)`
      trong `wiring.py` → đỏ.
- [ ] R1.2 (UL1): thiếu dòng gói → `QuotaExceededError` khi nhận lượt chạy, không hiểu thành "không giới
      hạn"; gỡ kiểm thiếu dòng → test đỏ.
- [ ] R1.3: `dw_app` ghi `platform.plan_limits` → bị từ chối (chỉ migration ghi).
- [ ] R1.1: bằng vai migrator đổi `runs_per_day` của một gói (đồng hồ giả) → lần nhận lượt chạy trong 30 giây
      sau lần đọc trước còn dùng số cũ, lần nhận sau khi qua 30 giây dùng số mới; gỡ hạn TTL → test đỏ.
- [ ] R1.2: adapter của `PlanCatalogPort` gặp lỗi đọc database (session giả ném lỗi) khi nhận lượt chạy → lượt chạy
      không được nhận và lỗi lan ra, kể cả khi cache còn một dòng đã hết hạn; nuốt lỗi và trả số cũ hay `None`
      → test đỏ.
- [ ] R1.4: `max_steps_per_run` 501 → migration từ chối, 1 → nhận; `max_tokens_per_run` NULL → từ chối.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/application/entitlement.py:13-36`; spec: R1.1 (DEFAULT_PLANS).
- `packages/python/dw_platform/src/dw_platform/application/entitlement.py:45-49`; spec: R1.1
  (`has_feature` đọc hai nguồn).
- `db/migrations/sql/0001_platform_baseline.sql:332-337`; spec: R1.1, R1.3 (`platform.plans`);
  ADR-0121 (Accepted) quyết 6.

## Comments

- 2026-10-23 (agent): từ B10b usage-and-limits 01. custom-objects thêm giới hạn metadata (object,
  trường, index) làm cột của cùng bảng — một danh mục gói cho nền tảng.
- 2026-10-23 (agent): DO-59.1 (Đạt, 23/10/2026): tiền NULL ở gói giữ như hôm nay; DO-59.2: v1 bán phí gói
  cố định kèm trần chi phí AI mỗi tháng (`cost_usd_per_month`), không tín dụng.
- 2026-10-24 (agent): áp quyết định của Đạt ngày 24/10/2026: chờ foundations-hardening/03 để quyền ghi và cột của
  `platform.plans` đổi theo một thứ tự (C:foundations-hardening/03\~usage-and-limits/01); bỏ `max_run_seconds`
  khỏi W1 vì chưa có bên đọc (H:usage-and-limits:dữ-liệu\~usage-and-limits:ngoài-phạm-vi).
- 2026-10-24 (agent): vòng sửa thứ tư: trần đồng thời sang W2 (Quyết định tạm của spec theo YC79), nên cột
  `max_concurrent_runs` cũng ra khỏi W1 cùng bên đọc của nó.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt b: `requests_per_minute`, `tokens_per_minute` cũng ra khỏi W1 và vào W2
  cùng bên đọc GCRA, vì `RateLimiterPort` của W1 nhận giới hạn do bên gọi nêu (V4.P6, Quyết định tạm của spec).
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH B1 (cách `PlanCatalogPort` đọc): bước 4 viết "cache tiến
  trình, TTL ngắn" không số, tiêu chí R1.4 cũ đòi "lần nhận sau dùng số mới" mà cache đó không cho, lỗi đọc database
  không được nói tới (danh mục không đọc được phải đóng, failure-modes #7), và `RunAllowancePort` đồng bộ
  (`ports.py:95-107`) không đáp được bằng một lần đọc database bất đồng bộ. Sửa: bước 4 nêu port `async`, TTL 30 giây
  như `caching_lookup.py:27`, khóa cache chỉ `plan_id`, dòng thiếu cũng cache, lỗi đọc lan ra không trả số cũ hay
  "không giới hạn", `RunAllowancePort` và `allowance.py:65`, `:86` thành `async`; tiêu chí R1.1 thêm ca TTL bằng đồng
  hồ giả, R1.2 thêm ca lỗi đọc. Nếu sai thì: giữ `RunAllowancePort` đồng bộ bằng một ảnh chụp danh mục nạp lúc khởi
  động và làm mới nền, và tiêu chí TTL đổi thành tiêu chí làm mới.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH B2 (test kiến trúc mơ hồ): tiêu chí R1.1 cũ "không còn dict
  danh mục gói trong mã" không nói test bắt gì, trong khi 28 tệp test dựng `PlanEntitlementService(DEFAULT_PLANS)`.
  Sửa: thêm bước 5 (quét `ast` trên `packages/python/*/src` và `apps/*/src`: tên `DEFAULT_PLANS`, lời gọi `Plan(` hay
  `PlanLimits(` ngoài adapter), test dùng catalogue giả của `dw_platform.testing` nhận số từ test; tiêu chí R1.1 nêu hai
  đột biến. Nếu sai thì: test chỉ bắt tên `DEFAULT_PLANS`, và Comments ghi rằng nó không thấy một dict đổi tên.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH B3 (số seed không có nguồn): bước 2 trỏ "số lời gọi theo đề
  xuất ghi ở Comments" nhưng Comments không có đề xuất nào, và spec, ADR-0117 (Accepted), ADR-0121 (Accepted),
  ticket 04, 06 không nêu số.
  Quyết: `max_model_calls_per_run` 50, vì mỗi lời gọi model là ít nhất một bước của đồ thị dưới `recursion_limit` 50
  (`contracts.py:82`), nên không lượt nào chạy được hôm nay bị chặn thêm; `max_tool_calls_per_run` 200, bốn lời gọi
  công cụ song song cho mỗi lời gọi model; như nhau ở ba gói; neo hai số còn lại vào `profiles.py:61-62` và
  `contracts.py:82`. Ticket 06 là bên đọc đầu tiên của hai cột. Nếu sai thì: một revision mới UPDATE hai số trước khi
  ticket 06 đóng.
- 2026-11-02 (agent): gate MEDIUM, chưa sửa, cho người dựng:
    - M1: Nguồn của ticket và spec R1 (`spec.md:65`) trích "ADR-0121 (Accepted) quyết 6"; danh mục gói là quyết 9
      (`docs/adr/0121-usage-ledger-returns-and-limits-are-postgres-leases.md:126-130`), quyết 6 là khi chạm hạn mức.
    - M2: seed `max_tokens_per_run` 120000 lấy từ `max_input_tokens_per_run` (chỉ input), mà
      `configs/models/gateway.yaml:75` có 200000 và `deepseek.yaml:25` có 100000; khi ticket 03, 04 kẹp theo Trần của
      gói, lượt của profile `gateway` bị siết. Ticket 03 nói cột là token vào hay tổng, và nâng seed nếu cần.
    - M3: ở ticket này chỉ `runs_per_day` và `cost_usd_per_day` có bên đọc; `cost_usd_per_month`, `tokens_per_month` và
      năm trần mỗi lượt được đọc từ ticket 03, 04, 06, còn `ModelBudgets` của `configs/models` vẫn là bên đọc trần mỗi
      lượt tới ticket 03 (hai bản tạm, failure-modes #1, #2); ticket 03 gỡ `ModelBudgets` như spec nói.
    - M4: spec và ticket không nêu kiểu cột; gợi ý `numeric(20,8)` cho USD như `limit_value` của
      `platform.limit_policies` (so sánh 422 `limit_above_plan` cùng kiểu), `bigint` cho token, `integer` cho số đếm.
    - M5: `ALTER DEFAULT PRIVILEGES` cấp `dw_app` SELECT, INSERT, UPDATE, DELETE trên bảng `platform` mới
      (`db/migrations/sql/0001_platform_grants.sql:45-46`), nên migration phải REVOKE ba quyền ghi, không chỉ GRANT
      SELECT; tiêu chí R1.3 hỏi bằng câu lệnh và bằng catalog (INSERT, UPDATE, DELETE, TRUNCATE) như
      `test_privileges.py:905-933` làm cho `platform.plans`.
    - M6: `wiring.py:181` dựng `PlanEntitlementService` trước cổng database (`wiring.py:216-218`), và `Container` đòi
      nó cả khi không có database (`wiring.py:212`, `apps/api/src/dw_api/bootstrap/container.py:149`); adapter đọc
      database dựng sau cổng đó, và khi không cấu hình database thì câu hỏi giới hạn gói từ chối, không mở.
    - M7 (LOW): docstring `entitlement.py:52-62` và chú thích `0001_platform_reference.sql:9-16` nói về
      `DEFAULT_PLANS`; sửa docstring, baseline giữ nguyên (bất biến). Dòng `Xong:` đọc theo `wave-close.md`.
- 2026-11-02 (agent): bảng cặp không có đường phụ thuộc: (01, 02) bảng `plan_limits`, `plans` với `usage_events`,
  `usage_daily`, mỗi bên một revision riêng, không route, config chung; (01, 05) 05 không migration, không bảng. Không
  va chạm. Ngoài spec: org-and-principals/02 đang sửa `tables.py`, `test_privileges.py`, `seed_env.py` trong cây làm
  việc; dựng ticket này sau khi ticket đó commit, và revision mới nối vào head lúc đó.
- 2026-11-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
