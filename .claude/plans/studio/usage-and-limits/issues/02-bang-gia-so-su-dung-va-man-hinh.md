# 02 — Bảng giá theo ngày hiệu lực, sổ sử dụng theo lượt gọi và màn Mức độ sử dụng

Status: ready-for-agent
Blocked by: .claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md, .claude/plans/studio/tenant-rbac/issues/01-mot-chu-cho-quyen.md, .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md, .claude/plans/studio/telemetry-and-audit/issues/01-otel-khong-noi-dung-va-metric.md
Area: studio
Yêu cầu: R2.1, R2.2, R2.3, R2.4, R2.5, R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R3.8, R3.9, R3.10, R3.11, R3.12, UL5, UL7, UL12, UL16, UL18

## Mục tiêu

Một Bảng giá theo ngày hiệu lực là chủ duy nhất của giá; một Sổ sử dụng theo lượt gọi ghi mọi lượt gọi
model với đủ thuộc tính gán, chỉ thêm và idempotent; màn Mức độ sử dụng đọc chính sổ này (spec R2, R3).
Đảo việc gỡ `platform.model_usage_ledger` (DO-21.1, Đạt ký 23/10/2026), kèm bên đọc từ ngày đầu.

## Việc cần làm

1. Gói nền tảng mới `packages/python/dw_usage` (ADR-0121 (Accepted) quyết 1), dựng ở ticket này vì đây là ticket đầu
   của spec có mã của gói (ticket 01 và 05 đặt mã ở `dw_platform`): lớp `domain/ application/ adapters/ presentation/`,
   đăng ký ở mọi chỗ mà `CLAUDE.md` mục 'Adding a bounded context' bước 2, 7 và 8 nêu (`tool.uv.sources`, ruff
   `known-first-party`, mypy `files`/`mypy_path`, coverage `source`, import-linter `root_packages`, `IMPORT_TO_DIST` của
   `scripts/verify_architecture.py`, danh sách COPY của Dockerfile api và worker, `apps/api/pyproject.toml` và
   `apps/worker/pyproject.toml`), nên kiểm tra đăng ký của studio-skeleton:R1 xanh. Hợp đồng import-linter mới:
   `dw_agent_runtime` và `dw_platform` không import `dw_usage` (runtime khai port, `dw_usage` đáp); `dw_usage.domain`
   không import FastAPI hay SQLAlchemy.
2. `configs/pricing/price_book@1.0.0.yaml` và `dw_usage.domain.pricing.PriceBook.price(tenant_id, quantities, provider,
model, at)` trả chi phí `Decimal`, phiên bản, id mục giá. `tenant_id` lấy từ `RunContext` của lời gọi, không bao giờ từ
   request; ở W1 mọi tenant nhận lớp nền tảng, vì mục giá riêng tenant (`platform.tenant_price_entries`, giải như
   `TenantOverlay`) là BYOM W2 (ADR-0121 (Accepted) quyết 3), và chữ ký mang `tenant_id` từ đầu (`CLAUDE.md` mục
   'Per-tenant artifacts'). Loại sử dụng là tập đóng (`input_uncached`, `cache_read`, `cache_write_5m`,
   `cache_write_1h`, `output`, `image_input`, `audio_input`, `embedding_input`, `rerank_search_unit`, `extraction_page`,
   `transcription_second`, `sandbox_vcpu_second`, `sandbox_gb_second`, `server_tool_call`; bước mã tính vCPU và GB đặt
   trước nhân thời gian chạy, DO-45.1); `input_uncached = input_tokens − cache_read − cache_write`. Bậc giá theo số token
   input của lời gọi áp cho cả lời gọi, và bậc là một phần của khóa khi kiểm chồng thời gian. Bộ nạp từ chối mục chồng
   thời gian cùng khóa, loại sử dụng lạ, giá âm. Không mục nào có `effective_from` không muộn hơn `at` cho một
   (provider, model, loại sử dụng) của lời gọi → `PriceNotFoundError`, không bao giờ chi phí 0 (spec R2.5).
   Tuyến nền tảng trả phí là mọi route có provider khác `mock` trong `configs/models/*.yaml` (W1 chưa có BYOM); route
   `mock` có mục giá 0 trong Bảng giá, nên không có nhánh riêng cho nó. Khi `settings.is_deployed`, khởi động đòi mỗi tuyến
   trả phí có mục phủ thời điểm khởi động cho mọi loại sử dụng mà adapter của loại route báo được (chat:
   `input_uncached`, `cache_read`, `cache_write_5m`, `cache_write_1h`, `output`; embedding: `embedding_input`; rerank:
   `rerank_search_unit`), thiếu → từ chối khởi động (spec R2.3).
   `route_cost` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/budget.py:46`, bên đọc duy nhất hôm nay của
   `price_per_million_input` và `price_per_million_output`) đọc giá qua `PricingPort`, một Protocol `dw_agent_runtime`
   khai và `PriceBook` đáp, mà composition root của api và worker tiêm vào bốn bên gọi hôm nay (`model/gateway.py`,
   `adapters/langchain_usage.py`, `adapters/run_budget.py`, `adapters/context_compaction.py`), thay cho hai trường đó;
   `route_cost` để `PriceNotFoundError` lan ra, không đổi nó thành 0; bốn bên gọi bắt nó sau lời gọi model, trả kết quả
   của lời gọi, ghi dòng `unpriced` (bước 6) và đánh dấu lượt chạy đã chạm trần chi phí trong `RunBudgetLedger`, nên lời
   gọi kế tiếp của lượt đó bị từ chối `BudgetExceededError` (đóng khi thiếu giá; ticket 03 thay `RunBudgetLedger` bằng
   lease, cùng quy tắc). Vì kiểm khởi động phủ mọi loại sử dụng adapter báo được, ở profile triển khai lỗi này chỉ còn
   với loại sử dụng adapter W1 chưa báo. Ticket này không sửa `model/profiles.py` hay
   `configs/models/*.yaml`: hai trường giá của `ModelRoute` ở lại không bên đọc tới khi model-connections/02, chờ ticket
   này, bỏ chúng lúc dựng `ModelProfile` v2, mỗi tệp một ticket sửa (H-4); test AST: không mã nào trong `src/` đọc
   `price_per_million_input` hay `price_per_million_output` ngoài khai báo của `ModelRoute`, nên hai bản của giá không
   trôi lặng lẽ. `scripts/release_manifest.py` ghim Bảng giá (id, version, sha256). Số giá trong `price_book@1.0.0.yaml`
   là giá niêm yết công khai có ngày, ghi UNVERIFIED trong tệp; Chờ Đạt: giá thật của các route sau gateway của người
   đặt yêu cầu (DO-19) trước lượt chạy tốn tiền thật đầu tiên, không chặn việc dựng.
3. Revision Alembic mới (id hex ngẫu nhiên; không downgrade `aefe7c1f5d9b`): `platform.usage_events` như
   mục Dữ liệu của spec, gồm `data_route_class`, `data_location`, `processor` có CHECK; phân vùng theo tháng
   với DEFAULT, RLS ở cha và DEFAULT cùng migration; index `(tenant_id, occurred_at)`,
   `(tenant_id, run_id) WHERE run_id IS NOT NULL`, `(lease_id) WHERE lease_id IS NOT NULL`; `dw_app` không UPDATE,
   DELETE trên cha và không giữ quyền nào trên partition nào, kể cả DEFAULT (DO-02.2). Cột NOT NULL: `id`,
   `occurred_at`, `tenant_id`, `operation`, `purpose`, `payer`, `provider`, `model`, `cost_source`, `price_book_version`,
   các cột token (CHECK `>= 0`). Cột được NULL, mỗi cột vì một bên ghi chưa có ở W1 hay một lời gọi không có giá trị đó:
   `workspace_id` (việc cấp công ty: `ingestion`, `builder_assist` trên thành phần toàn tenant), `run_id`,
   `root_run_id`, `node_id`, `artifact_kind`, `artifact_id`, `artifact_version` (lời gọi của worker hiện có, không thuộc
   thành phần Studio), `lease_id` (ticket 03 ghi), `user_id`, `trigger_kind`, và `data_route_class`, `data_location`,
   `processor` (compliance-pdpl/03 ghi từ `ResidencyGate`, ticket đó chờ ticket này; NULL nghĩa là lời gọi chưa qua cổng
   lộ trình, không bao giờ được đọc như `vn_only`). `cost_usd` NULL chỉ khi `cost_source = 'unpriced'`, CHECK
   `cost_usd >= 0`. Policy drain `worker_drain_usage_events` trên cha chỉ cho SELECT
   (`current_setting('app.worker_drain', true) = 'on'`, cùng hình `db/migrations/versions/0010_memory_retention_drain.py`);
   bên đặt `app.worker_drain` ở ticket này chỉ là lane `usage_rollup`.
4. Đăng ký `usage_events` bằng một dòng `platform.time_partitioned_tables` (`append_only = true`) trong
   migration này; không sửa thân `platform.ensure_time_partitions` (studio-skeleton/01 là chủ hàm). Ticket này là
   chủ duy nhất ở W1 của `platform.drop_expired_partitions(cutoffs jsonb)`: viết lại thân hàm, mỗi bảng cha một
   mốc (NULL = không xóa). Lane `partitions` dựng mốc của mỗi bảng cha trong sổ từ mảnh của bảng đó trong tập mảnh
   retention đang ghim, qua bộ đọc tập mảnh của mô hình chính sách (`RetentionPolicy.store_cutoff`,
   telemetry-and-audit:R5.13, dựng ở telemetry-and-audit/01; H-1, H-27): chỉ mảnh có `days`, `purger: drop_partition` và
   `enforced: true` cho một mốc, mọi bảng cha khác nhận NULL, nên bảng không có mảnh hay chưa `enforced` không mất tháng
   nào. `test_a_term_drops_only_the_months_entirely_behind_it` (G1 của studio-skeleton, mốc của `platform.audit_events`
   đọc từ mảnh của nó) và `test_a_partition_made_at_runtime_keeps_the_audit_log_append_only` (G2) xanh qua bản viết lại.
   Cùng thay đổi đăng ký, thêm mảnh `configs/policies/retention.d/platform.usage_events.yaml` theo định dạng của
   telemetry-and-audit:R5.6 (`days: 395`, số tạm UNVERIFIED, `purger: drop_partition`, `enforced: false` và `description`
   nêu rằng thời hạn chờ luật sư xác nhận trước chạy bóng; Đạt, Q-h11; telemetry-and-audit H-33), nên studio-skeleton:R3.7
   xanh ngay khi đăng ký. Không có chuỗi tệp retention và không có ánh xạ tạm nào ở ticket này: mảnh
   `platform.audit_events` và việc gỡ ánh xạ tạm của studio-skeleton/01 là của telemetry-and-audit/01 (H-1).
5. Hai hàm SECURITY DEFINER (search_path cố định, thu EXECUTE khỏi `PUBLIC`, cấp EXECUTE cho `dw_app`), cùng hình
   `platform.purge_tenant_marketing` (`db/migrations/versions/0c3e9392cc06_marketing_send_floor.py`) và
   `platform.purge_tenant_access_version` (`db/migrations/versions/b5677d345bc1_tenant_roles.py`):
   `platform.append_only_tables()` trả `schema.table` của mọi dòng `append_only = true` của
   `platform.time_partitioned_tables` trừ `platform.audit_events` (`dw_app` không đọc sổ trực tiếp, `a77c5408a1f4`);
   `platform.purge_tenant_append_only(p_tenant uuid, p_tables text[])` từ chối với SQLSTATE 23514 khi `p_tenant` khác
   `app.tenant_id` của giao dịch, khi `platform.tenants.status` của `p_tenant` khác `offboarding` (spec R3.9), hay khi một
   phần tử của `p_tables` không thuộc `platform.append_only_tables()`; không thì xóa dòng `tenant_id = p_tenant` ở đúng các
   bảng của `p_tables` và trả số dòng theo bảng (spec R3.10). Bước `platform.purge_tenant_append_only` đăng ký trong
   `OffboardingPurgeSteps.platform()` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py`),
   không ở `dw_usage`, vì hàm phủ mọi bảng chỉ thêm của sổ chứ không riêng Sổ sử dụng, và test phủ đọc chính tập bước đó.
   Các bảng của bước giải ở mỗi lượt, trong `SqlTenantOffboarding._steps_for`: `platform.append_only_tables()` trừ mọi
   bảng một bước khác khai (hôm nay `platform.consent_records`, `platform.marketing_send_log` của
   `platform.purge_tenant_marketing`), và bước truyền đúng tập đó làm `p_tables`; nên không có danh sách viết tay, và hai
   bước không bao giờ cùng khai một bảng (foundations-hardening:R11.8). Hình của chỗ nối cho một bước có bảng giải theo
   lượt là của người dựng, trong `offboarding.py`. Bước chạy sau khi xuất, trong giao dịch xóa của lane, và hàm không được
   gọi từ chỗ nào khác (foundations-hardening:R11.4, foundations-hardening:R11.5; H-2). Ticket này không ghi thứ tự của
   bước: sổ suy thứ tự từ cạnh khóa ngoại `RESTRICT` và `NO ACTION` trong `pg_constraint`, nên một bảng chỉ thêm có khóa
   ngoại `ON DELETE RESTRICT` tới một bảng thường, như `studio.conversation_messages` tới `studio.conversations` của
   agent-builder, bị xóa trước bảng thường đó (spec R3.11), và test phủ của studio-skeleton:R4.2 đỏ khi một bước đăng
   ký đi trái một cạnh như vậy. org-and-principals/03 đăng ký bước xóa người dùng `service` của nó vào cùng sổ; hai
   ticket không chờ nhau. `STUDIO_EXCLUSIONS` thêm `platform.usage_events` với `function` là
   `platform.purge_tenant_append_only` và lý do "`dw_app` không DELETE; xóa khi offboarding bằng
   `platform.purge_tenant_append_only`" (studio-skeleton:R4.3); `platform.usage_daily` có policy
   `tenant_isolation_usage_daily` và DELETE cho `dw_app` để lane `offboarding` xóa như bảng thường (spec R3.8).
6. `UsageLedgerPort.settle(event) -> bool` (`INSERT ... ON CONFLICT DO NOTHING`); `id`, `occurred_at` cấp trước khi ghi;
   thiếu số dùng của nhà cung cấp → `cost_source = 'estimated'` bằng ước tính, không 0; `PriceNotFoundError` → dòng vẫn
   ghi với `cost_source = 'unpriced'`, `cost_usd` NULL, một log lỗi và metric `dw_usage_unpriced_total` (spec R2.5). Bên
   ghi ở ticket này: `LedgerUsageRecorder` của `dw_usage` đáp `UsageRecorderPort`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/gateway.py:61`) và vào `CompositeUsageRecorder` ở
   composition root của api và worker, nên mọi lời gọi qua gateway, `LangchainUsageMeter` hay context compaction ghi một
   Bản ghi sử dụng từ ngày đầu. Lời gọi chưa có lease hay thành phần Studio ghi `purpose` `run`, `payer` `platform`,
   `root_run_id = run_id`, `actor_kind` từ `RunContext`, và NULL ở các cột thành phần, `lease_id`, `node_id` và ba cột lộ
   trình. Ticket 03 dời lời gọi `settle` vào `RunLease.after_call` của `LimitsMiddleware`, ticket 04 vào các cửa có đo.
7. Bên đọc từ ngày đầu:
    - `window_for(tenant_id, window_kind, at)` trong `dw_usage` (dời từ ticket 03 sang đây, vì lane cuộn là bên dùng
      đầu): ranh giới kỳ theo `platform.tenants.timezone`, NULL thì Asia/Ho_Chi_Minh (DO-50; ADR-0121 (Accepted) quyết 9);
      ảnh worker mang dữ liệu múi giờ (tzdata). Đây là chủ duy nhất của ranh giới ngày: lane cuộn truyền cho SQL khoảng
      `[start, end)` hàm trả, không đổi múi giờ trong SQL; bộ đếm của ticket 03 dùng lại hàm này.
    - `GET /api/v1/runs/{run_id}/usage` (`runs.read`): trước hết đọc lượt chạy qua `run_store.get` trong workspace của
      người gọi, như `GET /api/v1/runs/{run_id}` (`apps/api/src/dw_api/routes/v1/runs.py:41-55`), nên run của công ty
      khác, của workspace khác hay không có → 404; run thấy được → 200 với tổng theo thao tác, model, nguồn chi phí của các
      dòng có `run_id` đó, tổng 0 khi run chưa gọi model nào.
    - `platform.usage_daily` cuộn ngày và lane `usage_rollup` (5 phút, tính lại hôm nay và hôm qua theo `window_for` cho
      tenant có dòng `usage_events` trong hai ngày đó, đọc dưới `app.worker_drain`, ghi từng tenant với tenant của nó).
    - `GET /api/v1/usage/summary` (`platform.usage.read`, đưa về `active` trong `platform.permissions` bằng migration của
      ticket này theo quy ước của tenant-rbac/01, sau tenant-rbac/02 mà ticket này chờ; `tenant_owner` nhận nó qua quyền
      tính sẵn của `platform.assigned_grants`): khóa có `scope_kind` `tenant`, nên người giữ đọc cả công ty, kể cả dòng
      `workspace_id` NULL, hiện thành nhóm "Cấp công ty"; gộp theo workspace, agent, quy trình, mục đích, không theo người ở
      W1 (DO-51.2); thiếu khóa → 403 (spec R3.12).
    - Màn `/usage` antd (Statistic, Table; lọc theo workspace, agent, quy trình bằng tham số URL; không thư viện biểu đồ ở
      v1, DO-42.3); mục điều hướng hiện theo `platform.usage.read` của `/me`, và route vẫn trả 403 khi thiếu khóa. Progress
      cho hạn mức trên màn này thuộc ticket 03, cùng `GET /api/v1/limits`; tab ở trang agent và quy trình thuộc
      agent-builder và workflow-builder-ui khi hai trang đó có (spec, Ngoài phạm vi).

## Tiêu chí chấp nhận

- [ ] R2.1: giá một model đổi ngày 2027-01-01 cho hai chi phí khác nhau; 1000 input có 800 cache_read →
      200 `input_uncached`; bậc trên 200k token áp cho cả lời gọi; `route_cost` cho cùng lời gọi trả đúng chi phí của
      `PriceBook.price`; `PriceBook.price` của hai tenant khác nhau cho cùng lời gọi trả giá lớp nền tảng; thêm một lời đọc
      `price_per_million_input` trong `src/` ngoài `ModelRoute` → test AST đỏ, nêu tệp; một import `dw_usage` trong
      `dw_agent_runtime` → import-linter đỏ.
- [ ] R2.2: mục giá chồng thời gian cùng khóa, loại sử dụng lạ, hay giá âm → bộ nạp từ chối.
- [ ] R2.3: tuyến nền tảng trả phí thiếu giá `output` ở profile `uat` → khởi động lỗi, nêu route; route `mock` vẫn khởi
      động với mục giá 0; gỡ kiểm → test đỏ.
- [ ] R2.4 (UL12): đổi Bảng giá → dòng sử dụng cũ giữ `price_book_version` và chi phí cũ.
- [ ] R2.5: lời gọi ngày 2026-06-01 với mục giá sớm nhất từ 2026-07-01, hay với loại sử dụng `image_input` không có mục →
      `PriceNotFoundError`, lời gọi đó vẫn trả kết quả, dòng sổ ghi `unpriced` với `cost_usd` NULL,
      `dw_usage_unpriced_total` tăng và lời gọi kế tiếp của cùng lượt chạy bị từ chối `BudgetExceededError`; đổi lỗi thành
      chi phí 0 → test đỏ.
- [ ] R3.1: một lượt gọi chat qua `RoutingModelGateway` hôm nay ghi đúng một Bản ghi sử dụng qua `LedgerUsageRecorder`,
      mang `tenant_id`, `workspace_id`, `run_id`, `root_run_id`, `purpose`, `payer` và `price_book_version`; `settle` một
      sự kiện có `data_route_class`, `data_location`, `processor` → ba cột lưu đúng, giá trị ngoài CHECK → từ chối; gỡ
      `LedgerUsageRecorder` khỏi `CompositeUsageRecorder` → test đỏ. Ghi lộ trình cho mọi lời gọi là tiêu chí R2.1 của
      compliance-pdpl/03.
- [ ] R3.2: quyết toán hai lần cùng `(id, occurred_at)` → một dòng, lần thứ hai trả `False`.
- [ ] R3.3 (UL5): adapter không báo usage → dòng `estimated` bằng ước tính, không 0; gỡ → test đỏ.
- [ ] R3.4: `dw_app` UPDATE hay DELETE trên cha và partition mới → bị từ chối.
- [ ] R3.5: tổng `usage_daily` một ngày bằng tổng `usage_events` ngày đó theo `window_for`; dòng lúc 2026-11-03T17:30Z của
      tenant có `timezone` NULL rơi vào ngày 2026-11-04 còn dòng lúc 2026-11-03T16:30Z rơi vào 2026-11-03, và tenant
      `Asia/Tokyo` cắt ngày lúc 15:00Z; cuộn hai lần cùng kết quả; dòng quyết toán trễ hiện sau lượt cuộn kế;
      `GET /api/v1/usage/summary` có nhóm "Cấp công ty" cho dòng `workspace_id` NULL.
- [ ] R3.6 (UL7): tenant A đọc bảng cha `usage_events` hay `usage_daily` khi có dòng của B → 0 dòng của B;
      `GET /api/v1/runs/{run_id}/usage` của run tenant B từ A → 404; người giữ `runs.read` ở workspace W1 mở run của W2
      cùng công ty → 404; run của chính workspace chưa gọi model nào → 200 với tổng 0; `GET /api/v1/usage/summary` từ A không có số nào của B; kết nối `dw_app` không đặt
      `app.worker_drain` không đọc được dòng của tenant khác qua policy drain.
- [ ] R3.7 (UL7): `dw_app` đọc hay ghi một partition của `usage_events` theo tên → `permission denied`, cả
      partition do lane tạo lẫn DEFAULT; cấp lại SELECT trên partition → test đỏ.
- [ ] R3.8: công ty `offboarding` có dòng trong `usage_events`, `usage_daily` → lane `offboarding` xuất mỗi dòng
      một lần rồi xóa hết; test phủ offboarding (studio-skeleton:R4.3) xanh với dòng `STUDIO_EXCLUSIONS` của
      `platform.usage_events`; gỡ bước của hàm khỏi sổ bước xóa → dòng `usage_events` còn, test đỏ.
- [ ] R3.9 (UL16): gọi `platform.purge_tenant_append_only` cho công ty `active` → 23514, 0 dòng xóa; giao dịch đặt tenant A
      gọi hàm cho công ty B đang `offboarding` → 23514, 0 dòng của B xóa; gỡ kiểm trạng thái hay kiểm tenant → test đỏ.
- [ ] R3.10 (UL16): với công ty `offboarding`, hàm xóa dòng của nó ở mọi bảng của `p_tables`, kể cả một bảng thử đăng ký
      `append_only` trong test, còn dòng của công ty khác và mọi dòng `platform.audit_events` giữ nguyên; `p_tables` có
      `platform.audit_events` hay một bảng thường → 23514, 0 dòng xóa; bước không khai `platform.consent_records`,
      `platform.marketing_send_log`, và worker dựng sổ bước xóa có cả bước này lẫn `platform.purge_tenant_marketing`.
- [ ] R3.11: một bảng `append_only` thử đăng ký trong test có khóa ngoại `ON DELETE RESTRICT` tới một bảng thường
      thử, công ty `offboarding` có dòng ở cả hai → sổ bước xóa xếp bước của hàm trước bước của bảng thường và lane
      `offboarding` xóa hết cả hai trong một giao dịch; đổi phần nêu bảng của bước sang một danh sách viết tay không có
      bảng thử → sổ không xếp bước trước bảng thường, lỗi khóa ngoại, giao dịch xóa lùi, và test phủ của
      studio-skeleton:R4.2 đỏ, nêu tên khóa ngoại thử.
- [ ] R3.12 (UL18): người không giữ `platform.usage.read` gọi `GET /api/v1/usage/summary` → 403, không truy vấn nào tới
      `usage_daily`; `tenant_owner` gọi → 200; gỡ kiểm quyền → test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py:54-55`; spec: R2.1 (giá trên route).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/budget.py:46-56`; spec: R2.1 (`route_cost`, bên đọc
  duy nhất của giá trên route).
- `db/migrations/versions/0013_drop_model_usage_ledger.py:1-3`; spec: R3.1 (sổ đã bị gỡ, nay đảo lại).
- `db/migrations/sql/0013_partition_maintenance.sql:123`; spec: R3.4 (mảng một cha hôm nay);
  ADR-0121 (Accepted) quyết 1-2.

## Comments

- 2026-10-23 (agent): gộp B10b usage-and-limits 02, 03, 09. `needs-info` vì DO-21 (đưa lại sổ) chờ Đạt
  ký — chính Đạt yêu cầu gỡ. Offboarding xuất sổ và không purge (cạnh chỉ-thêm); cột `user_id` là dữ
  liệu cá nhân, xóa theo yêu cầu chủ thể chờ compliance-pdpl.
- 2026-10-23 (agent): Đạt ký DO-21.1 ngày 23/10/2026, nên `needs-triage`. Áp thêm DO-02.2 (partition không
  quyền `dw_app`, R3.7), DO-52 (thời hạn ở tệp của telemetry-and-audit/03), DO-45.1 (đơn vị bước mã), DO-42.3,
  DO-51.2 và cột lộ trình của ADR-0123 (Accepted) cho compliance-pdpl/03. Xóa `user_id` theo yêu cầu chủ thể
  vẫn mở (ADR-0122 (Accepted) Open 1).
- 2026-10-24 (agent): áp quyết định của Đạt ngày 24/10/2026: ticket này là chủ duy nhất của
  `platform.drop_expired_partitions(cutoffs jsonb)` ở W1; thêm thời hạn của `platform.usage_events` vào tệp
  retention trong cùng thay đổi đăng ký, theo định dạng khóa `schema.table` của telemetry-and-audit (bản tệp đầu
  có mục đó nếu chưa có); hàm `platform.purge_tenant_append_only` và dòng `STUDIO_EXCLUSIONS` cho offboarding
  (H:ADR-0121 (Accepted)\~usage-and-limits:dữ-liệu); chờ model-connections/02 (cùng sửa `model/profiles.py`,
  `configs/models/*.yaml`: hồ sơ v2 trước, rồi dời giá) và foundations-hardening/07 (cùng sửa lane `offboarding`).
  Ticket này là ticket đầu sau studio-skeleton/01 thêm khóa vào tệp retention; các ticket sau (ticket 03,
  agent-lifecycle/04, telemetry-and-audit/03, compliance-pdpl/04, compliance-pdpl/06) mỗi ticket thêm một bản mới.
- 2026-10-24 (agent): vòng sửa thứ tư: thứ tự của chuỗi tệp retention theo Quyết định tạm của spec, thay danh sách ở
  dòng trên: studio-skeleton/01, ticket này, ticket 03, telemetry-and-audit/03, agent-lifecycle/04,
  workflow-triggers/02, compliance-pdpl/04, agent-builder/04, compliance-pdpl/06; bản của ticket này chắc chắn là bản
  đầu có mục khóa `schema.table` (kể cả `platform.audit_events`). Chờ tenant-rbac/02 (Quyết định tạm của spec về
  đăng ký khóa).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt b, theo các Quyết định tạm cùng ngày của spec: chuỗi tệp retention bắt
  đầu từ ticket này, studio-skeleton/01 không sửa tệp mà đọc `retention@1.7.0` qua ánh xạ tạm (V4.P1), thay danh
  sách của hai dòng trên; lời gọi `platform.purge_tenant_append_only` đứng trước vòng DELETE bảng thường trong giao
  dịch xóa (spec R3.11), và org-and-principals/03 chờ ticket này vì hàm xóa người dùng `service` của nó chạy sau cùng.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt c, theo Quyết định tạm cùng ngày của spec: lời gọi
  `platform.purge_tenant_append_only` là một bước trong thứ tự các bước xóa của `purge_rows` mà studio-skeleton/01
  khai ở một chỗ trong `offboarding.py`, ticket này thêm bước đó vào chỗ ấy và test phủ của studio-skeleton:R4.2 đọc
  nó (bước 4, tiêu chí R3.11).
- 2026-10-26 (agent): vòng 4, lượt h. H-4: ticket này dựng Bảng giá và chuyển `route_cost` sang đọc nó, không sửa
  `model/profiles.py` hay `configs/models/*.yaml`; model-connections/02 nay chờ ticket này và bỏ hai trường giá, nên
  gỡ cạnh 02 <- model-connections/02 (bước 1, tiêu chí R2.1 thêm test AST). H-1: lane `partitions` dựng mốc của
  `platform.drop_expired_partitions` từ tập mảnh retention, ticket này thêm mảnh `platform.usage_events`; chuỗi tệp
  retention và ánh xạ tạm bỏ khỏi ticket này (bước 3); `enforced` của mảnh chờ Q3 của spec. H-27: thêm cạnh
  02 <- telemetry-and-audit/01 (bộ đọc tập mảnh). H-2: bước `platform.purge_tenant_append_only` đăng ký vào sổ bước
  xóa của foundations-hardening/07, thứ tự suy từ cạnh RESTRICT, không còn ở ticket này; org-and-principals/03 thôi
  chờ ticket này (bước 4, tiêu chí R3.8, R3.11). Các dòng Comments trước về chuỗi tệp retention và thứ tự các bước xóa
  là lịch sử, đã bị thay.
- 2026-10-26 (agent): áp Q-h11 của Đạt (theo khuyến nghị): mảnh `platform.usage_events` mang `enforced: false`, lane `partitions` không DROP tháng nào của bảng tới khi luật sư xác nhận thời hạn. Không thêm cạnh.
- 2026-10-29 (agent): `platform.purge_tenant_append_only` phải bỏ qua bảng đã có bước khác khai trong sổ bước xóa (`platform.consent_records`, `platform.marketing_send_log` do `platform.purge_tenant_marketing` của compliance-pdpl/08 xóa), vì foundations-hardening R11.8 làm worker không khởi động khi hai bước cùng khai một bảng.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk, vì
  ticket thêm migration, route và màn), đo trên `992bf74`; `check_plans.py` 23 Đạt, 1 Không đạt (`acceptance`, ở ticket 01
  và 05 đã dựng, không ở ticket này). 2 CRITICAL, 7 HIGH, đã sửa ở ticket, spec và ticket 03:
    - CRITICAL (mục 11; `CLAUDE.md` mục 'Tenancy and authorization', test âm chéo tenant cho ghi là bắt buộc):
      `platform.purge_tenant_append_only` SECURITY DEFINER, EXECUTE cho `dw_app`, chỉ kiểm trạng thái, nên một giao dịch
      của tenant A xóa được sổ chỉ thêm của tenant B đang `offboarding`. Hai hàm xóa cùng loại đã có đều buộc `p_tenant` bằng
      `app.tenant_id` (`0c3e9392cc06`, `b5677d345bc1`). Sửa: bước 5, R3.9, UL16 của spec, tiêu chí R3.9. Nếu sai thì:
      không đường nào được chấp nhận; CRITICAL chỉ được sửa.
    - CRITICAL (mục 23; `CLAUDE.md` mục 'Per-tenant artifacts': "New registries take `tenant_id` from the start"):
      `PriceBook.price` không nhận `tenant_id`, trong khi ADR-0121 (Accepted) quyết 3 giải mục giá BYOM theo tenant như
      `TenantOverlay`. Sửa: bước 2, R2.1 của spec, tiêu chí R2.1 (W1 trả lớp nền tảng cho mọi tenant). Nếu sai thì: không
      đường nào được chấp nhận; CRITICAL chỉ được sửa.
    - HIGH (mục 29, 17): không bên nào gọi `settle` ở ticket này (`LimitsMiddleware` là ticket 03, cửa có đo là ticket 04),
      nên R3.1 chỉ ticket khác làm đúng và màn `/usage` đọc một sổ rỗng; ba cột lộ trình và cột thành phần không nói NULL
      hay không, khi `ResidencyGate` (compliance-pdpl/03) chờ ticket này. Sửa: bước 3 (cột NOT NULL và cột NULL, mỗi cột
      một lý do; NULL lộ trình không đọc như `vn_only`), bước 6 (`LedgerUsageRecorder` vào `CompositeUsageRecorder`), tiêu
      chí R3.1. Nếu sai thì: ba cột lộ trình NOT NULL và compliance-pdpl/03 đi trước ticket này, gỡ cạnh của nó tới ticket
      này và ghi cột ở một migration riêng.
    - HIGH (mục 32; foundations-hardening:R11.8): R3.10 đòi hàm xóa mọi bảng `append_only` trừ audit, Comments 2026-10-29
      đòi bỏ qua bảng của `platform.purge_tenant_marketing`, hàm SQL không đọc được sổ bước xóa ở Python, và
      `OffboardingPurgeStep.tables` là tập cố định lúc dựng nên không đọc sổ ở database được. Sửa: bước 5
      (`platform.append_only_tables()`, `p_tables text[]` chỉ thu hẹp, bước trong `OffboardingPurgeSteps.platform()` giải
      bảng mỗi lượt trừ bảng của bước khác), R3.10 của spec, tiêu chí R3.10. Nếu sai thì: mỗi bảng chỉ thêm một hàm xóa
      riêng và một dòng bước viết tay, kèm test so tập bước với sổ, và R3.11 bỏ vế "danh sách viết tay".
    - HIGH (mục 11, 12): giới hạn theo workspace của hai route đọc chỉ ở tầng ứng dụng, không tiêu chí và không test âm
      cùng công ty khác workspace; summary không có test âm 403; dòng `workspace_id` NULL không nói ai thấy. Sửa: bước 7
      (`platform.usage.read` là khóa `scope_kind` `tenant` trong catalogue `ebb17244abc6`, nên summary là cả công ty kèm
      nhóm "Cấp công ty"; route run theo workspace của người gọi như `runs.py:41-55`), thêm R3.12 và UL18, sửa R3.5, R3.6,
      UL7 của spec, tiêu chí R3.5, R3.6, R3.12. Nếu sai thì: khóa đổi sang `scope_kind` `workspace` ở migration của ticket
      này, summary lọc theo tập workspace của `platform.effective_grants`, và dòng `workspace_id` NULL chỉ người giữ ở độ
      sâu công ty thấy.
    - HIGH (mục 16, 7; `failure-modes.md` #7): không nói khi không mục giá nào phủ `at` hay thiếu một loại sử dụng thì trả
      gì; trả 0 làm trần tiền không thấy chi; "tuyến nền tảng trả phí" không định nghĩa. Sửa: bước 2 (`PriceNotFoundError`;
      tuyến trả phí là route provider khác `mock`; kiểm khởi động theo loại sử dụng của loại route), bước 6 (dòng `unpriced`
      kèm metric), thêm R2.5 của spec, tiêu chí R2.3, R2.5. Nếu sai thì: lời gọi thiếu giá bị từ chối trước khi gửi ở profile
      triển khai, và R2.5 đổi sang từ chối lời gọi.
    - HIGH (mục 32): `window_for` dựng ở ticket 03, mà lane cuộn của ticket này dùng và ticket 03 chờ ticket này (phụ thuộc
      trỏ tới trước). Sửa: bước 7 dời `window_for` sang đây, ticket 03 bước 2 dùng lại; tiêu chí R3.5 thêm ca múi giờ. Nếu
      sai thì: lane cuộn dùng UTC tới ticket 03 và R3.5 đổi chữ "theo `window_for`".
    - HIGH (mục 32, 31): Progress cho hạn mức trên `/usage` cần `GET /api/v1/limits` của ticket 03 (sau ticket này); tab ở
      trang agent và quy trình nhúng vào trang chưa có (`apps/web/app` không có trang Studio nào) và không ticket nào nhận.
      Sửa: bước 7; Progress sang ticket 03 bước 6; tab vào một dòng Ngoài phạm vi của spec, chủ agent-builder và
      workflow-builder-ui. Nếu sai thì: ticket 02 dựng Progress theo Trần của gói (`plan_limits`, ticket 01) và ticket 03
      đổi nguồn.
    - HIGH (mục 3, 23; `CLAUDE.md` mục 'Adding a bounded context' bước 2, 7, 8): gói `dw_usage` chưa có
      (`packages/python/` không có nó), ticket không nói ai dựng và đăng ký nó, và `route_cost` ở `dw_agent_runtime` đọc
      `PriceBook` của `dw_usage` qua đâu. Sửa: bước 1 (dựng và đăng ký gói, hợp đồng import-linter), bước 2 (`PricingPort`
      runtime khai), tiêu chí R2.1. Nếu sai thì: Bảng giá và Sổ sử dụng ở `dw_platform` như ticket 01 và 05, và
      ADR-0121 (Accepted) quyết 1 ghi lại chỗ của gói.
- 2026-11-03 (agent): MEDIUM và LOW của gate, chưa sửa, cho người dựng:
    - M1: lane `usage_rollup` chỉ tính lại hôm nay và hôm qua, nên dòng đến trễ hơn (dòng `unsettled_estimate` của
      `ReapTarget` ticket 03 khi lease hết hạn qua nửa đêm hôm sau) hay đổi `platform.tenants.timezone` làm R3.5 sai cho
      ngày cũ. Khuyến nghị: lane tính lại mọi ngày có dòng `usage_events` mới hơn lượt cuộn trước (theo `occurred_at` và
      thời điểm ghi), và đổi múi giờ không cuộn lại lịch sử, ghi ở docstring.
    - M2: `settle` cùng `id` khác `occurred_at` (lần thử lại rơi sang tháng mới) thành hai dòng; `id` và `occurred_at` cấp
      một lần và đi cùng nhau ở mọi lần thử lại. Cùng khóa khác nội dung trả `False` và log cảnh báo, không lỗi.
    - M3: `usage_daily` có `user_id` trong UNIQUE dù W1 không bên nào gộp theo người (DO-51.2; `failure-modes.md` #1).
      Khuyến nghị: giữ cột như spec (ADR-0122 (Accepted) Open 1 còn mở) nhưng ghi NULL ở W1, cột có giá trị khi màn theo
      người đến ở W2.
    - M4: `usage_daily` chưa có mảnh retention tới telemetry-and-audit/03 (760 ngày, DO-52); bảng nhỏ (một dòng mỗi nhóm
      mỗi ngày) nên tăng chậm, nhưng không ai xóa trước ticket đó.
    - M5: access context cache trước migration đưa `platform.usage.read` về `active` thiếu khóa tới khi hết hạn (đóng khi
      thiếu, chỉ chậm); migration không cần bump `platform.tenant_access_versions`.
    - M6: "hàm không được gọi từ chỗ nào khác" không có quét mã giữ; kiểm tenant và trạng thái trong hàm là phần chặn thật.
      Khuyến nghị: một quét `ast` nhỏ như test của ticket 01 nếu rẻ.
    - M7: `payer` của lượt `eval_offline` trên model nền tảng là `tenant` theo DO-29.2, trong khi glossary nói `tenant` là
      BYOM; ticket 03 quyết khi mở lease `eval_offline`, ticket này chỉ lưu giá trị bên gọi nêu.
    - M8: `GET /api/v1/runs/{run_id}/usage` chỉ cộng dòng có đúng `run_id`, không gộp lượt con theo `root_run_id`; tổng
      theo cây là W2 cùng run con của workflow-engine.
- 2026-11-03 (agent): bảng va chạm với ticket không có đường phụ thuộc tới ticket này. Trong spec: 01 (dựng xong; bảng
  `platform.plan_limits`, `platform.plans`, không chung), 05 (dựng xong; không bảng), 03, 04, 06 chờ ticket này. Ngoài
  spec: connections-and-vault/02 (`ready-for-agent`) cùng sửa `offboarding.py` (`STUDIO_EXCLUSIONS`, và ticket này sửa
  `OffboardingPurgeSteps.platform()` với `_steps_for`): mã, không phải tài nguyên của danh sách va chạm, nhưng không dựng
  song song; tenant-rbac/03 (`needs-triage`) cùng ghi dòng `platform.permissions` (khóa khác nhau, theo quy ước của
  tenant-rbac/01): không dựng song song; org-and-principals/04 (resolved) chung `wiring.py`. Mọi ticket có migration nối
  `down_revision` vào head lúc commit (`wave-close.md`).
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): lượt xác nhận của gate (builder check mới trên bản đã sửa): 2 HIGH, đã sửa.
    - HIGH (mục 16): bốn bên gọi `route_cost` làm gì với `PriceNotFoundError` không nói; hỏng lời gọi hay bỏ qua trần
      tiền đều sai. Sửa: bước 2 (bắt sau lời gọi, trả kết quả, ghi `unpriced`, lượt chạy chạm trần chi phí; kiểm khởi động
      phủ mọi loại sử dụng adapter báo được), tiêu chí R2.5. Nếu sai thì: lời gọi thiếu giá chỉ ghi `unpriced` và metric,
      lượt chạy đi tiếp, và R2.5 bỏ vế từ chối lời gọi kế tiếp.
    - HIGH (mục 3, `[Mâu thuẫn]`): mục API của spec còn ghi summary "workspace trong tập được phép" sau khi R3.5 nói cả công
      ty. Sửa: mục API. Khóa `scope_kind` `tenant` chỉ được giữ ở độ sâu công ty (`ck_tenant_role_permissions_depth_kind`,
      `b5677d345bc1`), nên người giữ nó luôn thấy cả công ty. Nếu sai thì: như dòng `Nếu sai thì` về giới hạn theo workspace
      ở trên.
    - Cùng lượt, MEDIUM đã sửa vì rẻ: route usage theo run đọc lượt chạy qua `run_store.get` trước, run thấy được mà chưa
      gọi model nào trả 200 với tổng 0, không 404 (bước 7, tiêu chí R3.6).
- 2026-11-03 (agent): MEDIUM của lượt xác nhận, chưa sửa, cho người dựng:
    - M9: R3.3 không nói ước tính thế nào. Khuyến nghị: cột token ghi số ước tính, không 0; đầu vào bằng bộ đếm token sẵn có
      của context compaction nếu có, không thì số ký tự chia 4; đầu ra bằng `max_tokens` của lời gọi; tiêu chí R3.3 kiểm cả
      cột token, không chỉ `cost_usd`.
    - M10: `purpose` của lời gọi compaction và nạp tri thức là `compaction` và `ingestion` theo tác vụ của `ModelRequest`,
      không gộp vào `run`; lời gọi embedding vào sổ khi ticket 04 dựng `MeteredEmbeddingPort`, R3.1 của ticket này kiểm
      đường chat.
    - M11: hợp đồng của summary chưa nêu tham số. Khuyến nghị: `from`, `to` là ngày theo `window_for`, mặc định tháng hiện
      tại, tối đa 400 ngày (422 khi quá); `group_by` một trong `workspace`, `artifact`, `purpose`; tên agent và quy trình
      đọc từ `studio.artifacts` khi có, không thì id.
    - M12: Statistic "số run" của Màn hình không đọc được từ `usage_daily` mà không đếm lặp (một run nhiều dòng). Khuyến
      nghị: thay bằng "số lượt gọi" từ cột `calls` của `usage_daily`, hoặc thêm `runs` đếm `root_run_id` khác nhau theo ngày
      và nhóm, ghi rằng tổng nhiều nhóm có thể đếm lặp.
    - M13: dòng `unpriced` có `cost_usd` NULL nên SUM bỏ qua; `usage_daily` thêm `unpriced_calls` và `estimated_calls`, màn
      hiện cảnh báo khi khác 0, để tổng thiếu không lặng lẽ.
    - M14: `effective_from` là `timestamptz` so với `at` theo UTC; ngày trong tệp viết kèm múi giờ.
    - M15: sổ có một cột `cache_write_tokens` mà Bảng giá có `cache_write_5m` và `cache_write_1h`; số theo loại ghi trong
      `units`, cột giữ tổng; ngưỡng bậc 200k đếm `input_tokens` gồm cả token cache, như nhà cung cấp tính.
- 2026-11-03 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
