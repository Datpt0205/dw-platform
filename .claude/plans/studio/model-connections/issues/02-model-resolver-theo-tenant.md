# 02 — `ModelResolver` theo công ty, `ModelProfile` v2, `plan_model_profiles`

Status: resolved (2026-11-05, main)
Blocked by: .claude/plans/studio/tenant-config/issues/04-ban-ke-luot-chay.md, .claude/plans/studio/usage-and-limits/issues/02-bang-gia-so-su-dung-va-man-hinh.md, .claude/plans/studio/workflow-engine/issues/02-cot-run-va-cua-nhan-run.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R1.6, R2.1, R2.2, R2.3, R2.5, R2.6, R3.1, R3.2, MR1, MR2, MR3, MR4, MR5, MR6

## Mục tiêu

Thay ba chỗ đọc hồ sơ lệch nhau bằng một `ModelResolver` theo công ty trả lời mọi cửa model, lọc hồ sơ theo gói, ghim
route vào bản kê của lượt Studio và mang trường tuyến dữ liệu. Chứng minh R1, R2, R3 của spec và cài MR1–MR6. Nền móng
chạy được ngay, không chờ BYOM.

## Việc cần làm

1. `ModelResolver` ở `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/resolver.py`, cạnh
   `ModelProfileRegistry`, vì các cửa nó phục vụ ở `dw_agent_runtime` và gói này không import `dw_studio` hay
   `dw_platform`.
    - `resolve(run_context, profile_id, purpose) -> ResolvedRoute`. Công ty, gói (`run_context.plan_id`, như
      `RunAllowancePort`) và workspace lấy từ `RunContext`, không bao giờ từ request; không có tham số `tenant_id` rời
      (R1.1, R1.6). `profile_id` `None` là hồ sơ mặc định của deployment (`default_profile` từ `DW_API_MODEL_PROFILE`,
      truyền lúc dựng ở composition root, như `RoutingModelGateway.default_profile` hôm nay), cũng lọc theo gói;
      workflow-nodes/05 đọc model mặc định qua đường này. `purpose` là một trong `chat`, `structured_extraction`,
      `reasoning`, `deep_reasoning` (như `RouteKind` của `ports.py:23` cộng `chat`); không có embedding.
    - Thứ tự: lớp công ty của `ModelProfileRegistry` (`TenantOverlay`; ở W1 không mã sản xuất nào nạp lớp này, test đăng
      ký trực tiếp; nguồn thật là phiên bản cấu hình kind `model_profile` của tenant-config ở W2), không lọc theo gói
      (ADR-0118 (Accepted) quyết 1); rồi lớp nền tảng, chỉ khi gói liệt kê hồ sơ; không bao giờ công ty khác (mẫu
      `packages/python/dw_agent_runtime/tests/unit/test_tenant_overlay.py`). Không câu trả lời → `EntitlementDeniedError`
      với `details.reason_code` `model_profile_unavailable`, không gọi model.
    - `ResolvedRoute` (frozen): `profile_id`, `layer` (`platform` hay `tenant`), `version` (bước 2), `content_hash`
      (`dw_kernel.canonical.content_hash` của hồ sơ đã nạp), `purpose`, `route` (`ModelRoute` của mục đích đó, theo luật
      `_route` của `model/gateway.py:125` cho `deep_reasoning` không khai), và `fallbacks` (route `fallback` của hồ sơ
      khi khác model của `route`, như `_attempts` ở `model/gateway.py:135`). Không có `secret_version`
      (ADR-0118 (Accepted) quyết 1; V4.35). Danh sách thử của mọi cửa là `route` rồi `fallbacks`, đọc từ đây, để cổng
      lộ trình của compliance-pdpl/03 lọc một danh sách duy nhất trước lần gửi đầu (ADR-0123 (Accepted), Amendments
      2026-11-04, quyết 4); không cửa nào đọc `profile.fallback` ngoài bộ phân giải.
    - Gói: `PlanModelProfilesPort.allowed(plan_id) -> frozenset[str]` khai trong `dw_agent_runtime.ports`, đáp ứng bởi
      `SqlPlanModelProfiles` của `dw_platform` (cạnh `plan_catalog.py`) với cache theo `plan_id` và TTL 30 giây như
      `CachingPlanCatalog`, tiêm ở composition root của API và worker. Gói không có dòng → tập rỗng → từ chối (R2.2);
      đọc lỗi → ném, không bao giờ coi là mọi hồ sơ (R2.6). `scripts/run_evals.py`, các script eval và test tiêm một bản
      trong bộ nhớ liệt kê hồ sơ chúng dùng (`dw_evals/graders.py:163` dựng `RunContext` với gói `starter`, không có
      trong `platform.plans`).
    - `pin(tenant_id, plan_id, profile_ids, default_profile) -> dict`: chỉ cho `ModelRoutePinPort` của bước 5, gọi bởi
      cửa nhận lượt với công ty và gói từ ngữ cảnh đã xác minh mà nó giữ (R1.6), không từ thân request; cùng thứ tự lớp và
      cùng lọc gói như `resolve`.
    - `platform_profile(profile_id) -> ModelProfile`: lớp nền tảng, không lọc theo gói, chỉ cho composition root và
      script: độ rộng embedding (`apps/api/src/dw_api/bootstrap/knowledge.py:29`,
      `apps/worker/src/dw_worker/composition.py:156`), `default_profile` (`adapters/model_stack.py:175`), route biên
      dịch một lần của chat model cho agent của gói (`adapters/chat_model.py:39-49`, `:70`) và các script
      (`scripts/check_model_gateway.py:60`, `scripts/eval_leadcare.py:82`, `scripts/eval_wf_ai.py:59`).
2. Nối bốn cửa đang có vào `resolve`, mỗi lời gọi một lần trước khi gửi:
    - `RunBudgetMiddleware` (`adapters/run_budget.py:72`, `:76`): cửa ngân sách mà `LimitsMiddleware` của
      usage-and-limits/03 thay sau ticket này, đọc cùng bộ phân giải (ADR-0118 (Accepted) quyết 1);
    - `LangchainUsageMeter._record` (`adapters/langchain_usage.py:145`, hôm nay không có công ty): định giá theo
      `route` của lời gọi;
    - `RoutingModelGateway` (`model/gateway.py:181`, `_route`, `_attempts`): danh sách thử là `route` rồi `fallbacks`;
    - nén ngữ cảnh (`adapters/context_compaction.py:190-191` mỗi lời gọi; `:146` lúc dựng đọc `platform_profile` để
      kiểm `max_input_tokens`).

    Chat model của agent của gói biên dịch một lần từ `platform_profile` (một model cho mọi công ty); vì lớp công ty
    không có nguồn sản xuất ở W1, hai cửa mỗi lời gọi ở trên trả cùng route đó cho mọi công ty, còn gói không cho phép
    thì cửa ngân sách từ chối trước lời gọi. Chọn model theo công ty cho agent là `StudioModelSelection` của
    agent-builder/03, nhận `ModelResolver` qua constructor; bộ chấm LLM đầu tiên của `dw_evals` cũng vậy. Một test quét
    mã (MR1) đỏ khi có lời gọi `ModelProfileRegistry.resolve` hay `chat_route` ngoài `model/resolver.py` và các chỗ
    `platform_profile` liệt kê ở bước 1.

3. `ModelProfile` v2 (`model/profiles.py`), mọi `configs/models/*.yaml` đổi cùng thay đổi:
    - `schema_version` `"2.0"` (bộ nạp từ chối `"1.0"`); số phiên bản của hồ sơ là `routing_policy_version` sẵn có
      (semver), không thêm trường thứ hai; bản kê ghim nó cùng `content_hash` (bước 5).
    - Mỗi `ModelRoute` (gồm `fallback`, `embedding`) mang, không mặc định: `data_location` `Literal["vn", "foreign"]`,
      `processor` (chuỗi khác rỗng), `retention_days` (số nguyên ≥ 0, hay `null` khai rõ là chưa biết), `no_training`
      (bool). Mục `capabilities` của route mang tập đóng mười hai cờ của ADR-0118 (Accepted) quyết 2 (`tool_calling`,
      `parallel_tool_calls`, `strict_tools`, `max_strict_tools`, `numeric_bounds`, `structured_output`,
      `reasoning_effort`, `usage_reporting`, `stream_usage`, `provider_tool_search`, `max_input_tokens`, `vision`), mỗi
      cờ tùy chọn: không khai là không hỗ trợ, tên ngoài tập là lỗi nạp (`extra="forbid"`). `max_input_tokens` của
      `ModelRoute` hôm nay chuyển vào đây, đọc bởi nén ngữ cảnh như trước. Bên đọc ở W1: tools-and-skills/04
      (`strict_tools`, `max_strict_tools`, `numeric_bounds`) và nén ngữ cảnh (`max_input_tokens`); các cờ khác có bên
      đọc ở W2 (lane `model_probe`, kiểm lúc gửi của ADR-0118 (Accepted) quyết 4).
    - Dẫn chiếu giá (ADR-0118 (Accepted) quyết 1, "a price reference") là cặp (`provider`, `model`) của route, đúng khóa
      mà `PricingPort.price` (`model/pricing.py`) đã dùng; không thêm trường.
    - `scripts/release_manifest.py` thêm mục `model_profiles` (`profile_id`, `version` là `routing_policy_version`,
      `checksum`) cho mỗi tệp của `configs/models`, như mục `prompt_bundles`, và `contracts/release/manifest.json` sinh lại;
      `release-manifest-check` của `make ci` đỏ khi tệp hồ sơ đổi mà manifest không sinh lại.
    - Giá trị trong YAML: route `provider: mock` (`balanced`, `low_cost` và mọi route mock) khai `data_location: vn`,
      `processor: mock`, `retention_days: 0`, `no_training: true`, vì adapter mock không gửi gì ra ngoài; route thật
      (`gateway`, `luna`, `deepseek`, `openai`) khai `data_location: foreign` tới khi FOG-18 định vị alias đó, `processor`
      là nhà vận hành endpoint nêu ở chú thích của tệp hay `.env.example` (`fpt_ai_gateway`, `deepseek`, `openai`),
      `retention_days: null`, `no_training: false`. Không ai khai `vn` cho một route chưa định vị để test xanh.
    - Bỏ `price_per_million_input`, `price_per_million_output` khỏi `ModelRoute` (`model/profiles.py:54-55`) và khỏi
      YAML: usage-and-limits/02 đã chuyển `route_cost` sang Bảng giá, và hai trường không còn ai đọc
      (`model/pricing.py:1-9`; H-4); bộ nạp từ chối YAML còn khóa giá (`extra="forbid"`).
    - `temperature` (`model/profiles.py:40`) và `max_cost_usd_per_run` (`model/profiles.py:62`) sang `Decimal`, đọc từ
      văn bản YAML của giá trị (chuỗi trong YAML, hay bộ nạp đổi qua `str`), không qua số thực, để hồ sơ băm được
      ổn định (ADR-0109 (Accepted) Consequences).

4. Migration `platform.plan_model_profiles` (revision hex sinh bằng `alembic revision`), theo mẫu
   `db/migrations/versions/764b0e239f95_plan_limits.py`: `plan_id text NOT NULL` FK tới `platform.plans (plan_id)`
   ON DELETE CASCADE; `profile_id text NOT NULL`, không FK; khóa chính `(plan_id, profile_id)`, cũng là chỉ mục của FK;
   không `tenant_id`, không RLS; chỉ `dw_app` có SELECT, mọi vai ứng dụng bị thu hồi INSERT, UPDATE, DELETE, TRUNCATE;
   tên ràng buộc theo `NAMING_CONVENTION`. Dữ liệu gieo: mọi gói của `platform.plans` (`basic`, `professional`,
   `enterprise` hôm nay) nhân mọi `profile_id` của `configs/models` ở commit này (`balanced`, `deepseek`, `gateway`,
   `low_cost`, `luna`, `openai`), để không công ty nào mất model khi bảng ra đời. `tables.py` của `dw_platform` thêm bảng.
   Một test đọc bảng đỏ khi một `profile_id` không có trong `configs/models` (failure-modes #2), và `test_privileges.py`
   thêm ca INSERT của `dw_app` bị từ chối như ca của `platform.plan_limits` (`test_privileges.py:1646`).
5. Ghim vào bản kê lượt chạy, chỉ cho lượt có gốc Studio (R1.4; ADR-0109 (Accepted) quyết 6, 8):
    - `EngineSection` (`packages/python/dw_studio/src/dw_studio/core/domain/run_manifest.py`) thêm `model_routes`: ánh
      xạ `profile_id` tới `{layer, version, content_hash, routes}`, `routes` là mọi route của hồ sơ trừ `embedding`,
      theo giá trị (`model_dump(mode="json")`, `Decimal` thành chuỗi), không khóa bí mật nào, và `content_hash` tính trên
      đúng `routes` đó (không gồm `embedding` hay `budgets`); cùng `default_model_profile`, id của hồ sơ mặc định lúc
      nhận lượt, hay `null` khi gói không cho phép nó; `extra="forbid"` giữ.
    - `RunManifestBuilder.build` (`dw_studio/core/application/run_manifests.py`) nhận thêm `plan_id` của lượt (gói trong
      ngữ cảnh đã xác minh mà `RunRequestService` của workflow-engine/02 nhận cho lượt, cũng là gói mà `RunContext` của
      lượt mang) và một `ModelRoutePinPort` khai trong
      `dw_studio.core.application.ports`, đáp ứng ở composition root bởi `ModelResolver`. Hồ sơ được ghim: hồ sơ mặc định
      của deployment, cộng mọi hồ sơ mà mục `ArtifactKindRegistry` của loại gốc trả qua một hàm tùy chọn
      `model_profiles(definition) -> frozenset[str]` (mặc định rỗng; loại `agent` đăng ký hàm đọc `model.profile` ở
      agent-builder/03; Bước AI của workflow ở W1 chỉ dùng hồ sơ mặc định, workflow-nodes/05). Một hồ sơ mà định nghĩa
      khai mà gói không cho phép → `build` từ chối với `model_profile_unavailable`, không ghi bản kê hay dòng lượt; hồ sơ
      mặc định ngoài gói không được ghim (`default_model_profile` `null`) và không chặn việc nhận lượt, nên một lượt không
      gọi model vẫn chạy.
    - Trong lượt Studio, `resolve` đọc từ `engine.model_routes` của `PinnedResolver` (tenant-config/04), không từ
      registry; `profile_id` `None` đọc `default_model_profile` đã ghim, không đọc `DW_API_MODEL_PROFILE` hiện hành, và
      `null` ở đó là hồ sơ không ghim: hồ sơ không ghim → `ConfigError` `key_not_pinned` như R6.3 của tenant-config; `content_hash` hiện hành
      của hồ sơ cùng tầng khác bản ghim, hay gói không còn liệt kê hồ sơ nền tảng → `model_profile_unavailable`
      (`details.reason` `pinned_profile_changed` hay `plan`), lời gọi không gửi và lượt kết thúc `failed` với
      `reason_code` `model_profile_unavailable` (R1.5; ADR-0118 (Accepted), Amendments 2026-11-04). Bản kê dựng trước ticket này
      không có `model_routes`, nên lời gọi model của lượt đó bị từ chối như hồ sơ không ghim (đóng khi thiếu).
    - Lượt không có gốc Studio phân giải mỗi lời gọi (dòng Ngoài phạm vi của spec).
6. `make check-model` (`scripts/check_model_gateway.py`): thăm dò mỗi route không phải mock của hồ sơ
   `DW_API_MODEL_PROFILE`, hay hồ sơ nêu bằng `make check-model PROFILE=<id>`, như hôm nay, rồi thăm dò cờ: `strict_tools`
   bằng một lời gọi có một công cụ `strict: true` (hỗ trợ khi 2xx và đối số trả về khớp lược đồ), `numeric_bounds` bằng
   cùng lời gọi với lược đồ có `minimum` (hỗ trợ khi 2xx). `max_strict_tools` không thăm dò; báo cáo in "không thăm dò".
   Phép so là một hàm thuần `compare_capabilities(declared, probed) -> list[str]` có test đơn vị với bản thăm dò giả; cờ
   khai khác kết quả → in route, cờ, giá trị khai và giá trị đo, thoát khác 0 (R2.5). Lệnh gọi gateway thật bằng khóa trong
   `.env` nên không chạy trong CI; ghi đầu ra một lần chạy vào Comments, hay "chưa đo: thiếu khóa gateway trong `.env`
   (Chờ Đạt 20)" mà không giữ ticket mở.

## Tiêu chí chấp nhận

- [x] R1.1 (MR1): bốn cửa (ngân sách, đo, gateway, nén) trả cùng `ResolvedRoute` cho một công ty có hồ sơ riêng; một cửa
      bỏ `run_context` (đọc lớp nền tảng) → test đỏ; thêm một lời gọi `ModelProfileRegistry.resolve` vào một tệp ngoài
      danh sách của bước 1 (`resolve`, `pin`, `platform_profile` ở các chỗ đã nêu) → test quét mã đỏ.
- [x] R1.2: hai cửa bất kỳ trong bốn trả cùng `content_hash` và `route` cho công ty có hồ sơ riêng; sai nếu hai cửa trả
      khác nhau.
- [x] R1.3 (MR2): công ty A hỏi hồ sơ mà chỉ công ty B có bản riêng nhận bản nền tảng khi gói của A liệt kê nó, và
      `model_profile_unavailable` khi không; không bao giờ bản của B; gỡ bước rơi về nền tảng → test đỏ.
- [x] R1.4 (MR4): lượt Studio nhận qua `RunRequestService` có `engine.model_routes` với hồ sơ mặc định và mọi route của
      nó kể cả `fallback`, và `default_model_profile` là id đó; đổi `DW_API_MODEL_PROFILE` sau khi nhận, gọi model với
      `profile_id` `None` → vẫn hồ sơ đã ghim; gói không cho phép hồ sơ mặc định → lượt vẫn nhận, `default_model_profile`
      `null`; thêm `secret_version` vào `ResolvedRoute` hay vào mục đã ghim → test hình bản kê đỏ
      (`extra="forbid"`); hồ sơ ngoài gói lúc nhận → 0 dòng lượt, 0 bản kê.
- [x] R1.5 (MR4): đổi YAML của hồ sơ đã ghim (chẳng hạn `data_location`) rồi gọi model trong lượt → từ chối, 0 lời gọi
      tới adapter giả, không theo route mới; bỏ hồ sơ khỏi gói rồi gọi → từ chối; hỏi hồ sơ không ghim → `key_not_pinned`;
      gỡ so `content_hash`, hay đọc registry thay bản kê → test đỏ.
- [x] R1.6 (MR6): gọi `resolve` không có `RunContext` (kiểu không cho, và một ca gọi với `None`) → từ chối; một cửa đổi
      sang `platform_profile` → test quét mã của R1.1 đỏ.
- [x] R2.1: bộ phân giải chỉ trả hồ sơ nền tảng mà gói liệt kê; một dòng `platform.plan_model_profiles` có `profile_id`
      không có trong `configs/models` → test đọc bảng đỏ; sai nếu trả hồ sơ ngoài gói.
- [x] R2.2 (MR3): lượt chạy xin hồ sơ ngoài gói, hay có gói không có dòng nào (`background`), nhận
      `model_profile_unavailable` và 0 lời gọi model; gỡ lọc gói → test đỏ.
- [x] R2.6 (MR3): `PlanModelProfilesPort` ném → lượt bị từ chối, 0 lời gọi; đổi nhánh lỗi thành "mọi hồ sơ" → test đỏ.
- [x] R2.3: `ModelProfile` v2 mang `schema_version` `"2.0"`, `routing_policy_version`, `strict_tools`, `numeric_bounds`,
      `data_location`, `processor` và `capabilities` trên mỗi route, không còn khóa giá, `temperature` và
      `max_cost_usd_per_run` là `Decimal`; YAML `"1.0"`, YAML còn khóa giá, YAML có cờ ngoài tập mười hai → bộ nạp từ
      chối; một route không khai `strict_tools` đọc là không hỗ trợ; `contracts/release/manifest.json` có mục
      `model_profiles` cho sáu hồ sơ; sai nếu một tệp sai vẫn nạp.
- [x] R2.5: `compare_capabilities` trả một dòng chênh cho mỗi cờ khai khác bản thăm dò giả, và rỗng khi khớp; sai nếu
      chênh mà rỗng. Đầu ra `make check-model` một lần, hay dòng "chưa đo", ở Comments.
- [x] R3.1 (MR5): YAML có một route thiếu `data_location`, một route thiếu `processor`, một route `data_location: VN` →
      bộ nạp từ chối từng ca và test nạp `configs/models` của CI đỏ; gỡ kiểm → test đỏ.
- [x] R3.2 (MR5): `ModelRoute` dựng bằng mã không có `data_location` → lỗi kiểm, không có giá trị mặc định nào; mọi route
      không phải mock trong `configs/models` khai `foreign`; sai nếu một route thật khai `vn` mà không có câu trả lời
      FOG-18 dẫn ở chú thích của tệp.
- [x] Xong: `uv run python -m pytest packages/python/dw_agent_runtime/tests packages/python/dw_studio/tests packages/python/dw_platform/tests/integration -k "model_resolver or model_profile or tenant_overlay or run_manifest or plan_model_profiles or privileges"` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_budget.py:72`;
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_usage.py:145`;
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/gateway.py:125-140`;
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/context_compaction.py:146`;
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py:113`;
  `packages/python/dw_studio/src/dw_studio/core/application/run_manifests.py:37`;
  `db/migrations/versions/764b0e239f95_plan_limits.py:1`; spec: R1.1, R1.2, R1.3, R1.4, R1.5, R1.6, R2.1, R2.2, R2.3,
  R2.4, R2.5, R2.6, R3.1, R3.2, MR1, MR2, MR3, MR4, MR5, MR6.

## Comments

- 2026-10-23 (agent): Đạt chốt DO-21.5 (a) ngày 23/10/2026: R2.4 rút, ticket không đổi giá trên hồ sơ (bước 2). Theo phát hiện kiểm nhất quán cùng ngày: thêm Blocked by tenant-config/04 vì bước 5 ghim route vào bản kê lượt chạy; trường tuyến dữ liệu chỉ thêm ở đây, compliance-pdpl/03 chỉ đọc.
- 2026-10-24 (agent): thứ tự với usage-and-limits/02 theo quyết định Đạt ngày 24/10/2026: cả hai ticket sửa `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py` và `configs/models/*.yaml`, nên ticket này đi trước và dựng `ModelProfile` v2 (bước 2); usage-and-limits/02 ghi Blocked by ticket này rồi dời giá sang Bảng giá trên bản v2. Ticket này không chờ usage-and-limits/02.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt c: `plan_id` có FK tới `platform.plans` ON DELETE CASCADE như `platform.plan_limits`, `profile_id` là khóa văn bản kiểm theo `configs/models` bằng test, không FK (bước 3, R2.1; CLAUDE.md, Data model rules); cửa ngân sách là `RunBudgetMiddleware` lúc ticket này dựng, rồi `LimitsMiddleware` của usage-and-limits/03 thay nó như ADR-0118 (Accepted) quyết 1 nêu (bước 1).
- 2026-10-26 (agent): vòng 4, lượt h. H-4: đảo chiều với usage-and-limits/02: ticket này nay chờ ticket đó, vì Bảng giá
  và `route_cost` đọc nó ra đời ở đó, và ticket này bỏ hai trường giá đã không còn ai đọc khi dựng `ModelProfile` v2
  (bước 2, tiêu chí R2.3); `temperature`, `max_cost_usd_per_run` vẫn sang `Decimal`; thay dòng 2026-10-24 ở trên về thứ
  tự. V4.35: `ResolvedRoute` không mang `secret_version` (bước 5, tiêu chí R1.4; ADR-0118 (Accepted) quyết 1).
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): sửa theo gate `checking-plan-readiness`, builder check và boundary walk
  vì ticket có migration (đo trên `c8dab56`; hai chặn cũ tenant-config/04 và usage-and-limits/02 đã `resolved`). 0
  CRITICAL; 16 HIGH, đã sửa hết như khuyến nghị (spec, mục Quyết định ngày 4/11/2026):
    - (1) giá trị tuyến dữ liệu của sáu YAML hiện có: mock `vn`/`mock`, route thật `foreign` tới FOG-18 (bước 3; R3.2);
    - (2) bộ nạp từ chối thiếu `processor` và giá trị ngoài `vn`, `foreign` (R3.1, ADR-0123 (Accepted) quyết 5);
    - (3) dữ liệu gieo của `platform.plan_model_profiles` và quyền chỉ SELECT, bảng toàn cục như `platform.plan_limits`,
      thay "RLS lớp nền tảng" (bước 4);
    - (4) gói không có dòng, gói giả, danh mục không đọc được đều từ chối (R2.2, R2.6);
    - (5) lớp công ty ở W1 chỉ là lớp trong bộ nhớ do test đăng ký, không lọc theo gói (ADR-0118 (Accepted) quyết 1);
    - (6) bản kê ghim gì: hồ sơ mặc định cộng hồ sơ do loại gốc khai, theo giá trị, ở `engine.model_routes`; lượt không
      gốc Studio không ghim (bước 5; R1.4);
    - (7) hồ sơ đã ghim mà đổi hay ra khỏi gói giữa lượt → từ chối lời gọi, không gửi theo khai báo cũ (R1.5);
    - (8) bản kê cũ không có `model_routes` → đóng khi thiếu;
    - (9) không có `tenant_id=None`: công ty và gói từ `RunContext`, lớp nền tảng chưa lọc chỉ qua `platform_profile`
      (R1.6);
    - (10) `ModelResolver` ở `dw_agent_runtime`, và `Xong:` không còn trỏ `packages/python/dw_studio/tests` cho mã của
      `dw_agent_runtime`;
    - (11) `make check-model` cần khóa gateway nên không vào CI; phép so cờ là hàm thuần có test, cách thăm dò từng cờ
      được nêu (bước 6; R2.5);
    - (12) "số phiên bản" là `routing_policy_version` sẵn có, `schema_version` lên `"2.0"`;
    - (13) `StudioModelSelection` và cửa giám khảo chưa có trong mã: nhận bộ phân giải ở ticket dựng chúng; chat model
      của agent của gói biên dịch từ lớp nền tảng (bước 2);
    - (14) `ResolvedRoute.fallbacks`: mọi cửa thử từ một danh sách mà cổng của compliance-pdpl/03 lọc (ADR-0123 (Accepted),
      Amendments 2026-11-04);
    - (15) hồ sơ `None` là hồ sơ mặc định của deployment, đọc bởi workflow-nodes/05;
    - (16) ghim lúc nhận lượt cần `RunRequestService` và cùng sửa `apps/api/src/dw_api/bootstrap/studio.py` với
      workflow-engine/02, nên thêm Blocked by workflow-engine/02.

    Lượt xác nhận cùng ngày tìm thêm 5 HIGH, đã sửa: `pin` nhận ngữ cảnh đã xác minh của cửa nhận lượt (bước 1, R1.6);
    lớp công ty không lọc gói (R2.1); lời gọi bị từ chối kết thúc lượt `failed`, `content_hash` không gồm `embedding`
    (bước 5, R1.5); `default_model_profile` ghim trong bản kê (bước 5); tập cờ đóng của ADR, dẫn chiếu giá và release
    manifest (bước 3).

    Nếu sai thì: như dòng `Nếu sai thì` của từng ý ở mục Quyết định của spec ngày 4/11/2026.

- 2026-11-04 (agent): MEDIUM để lại, chưa sửa:
    - Hiện trạng của spec dẫn `run_budget.py:62`, `langchain_usage.py:138`; hôm nay là `:72` và `:145` (ticket dẫn số mới).
    - Glossary `docs/platform/CONTEXT.md:350` viết `data_location: VN, foreign`; ADR-0118 (Accepted), ADR-0123 (Accepted) và ticket này dùng
      `vn`, `foreign`. Sửa glossary là việc của `domain-modeling`.
    - `retention_days` và `no_training` chưa có bên đọc ở W1 ngoài bộ nạp; bên đọc là form và sổ xử lý của W2
      (ADR-0118 (Accepted) quyết 3).
    - `model_connection_model_id` của route công ty (ADR-0118 (Accepted) quyết 2) thêm ở W2 cùng bảng kết nối model, vì
      W1 không có route công ty nào để mang nó.
    - Một hồ sơ thêm vào gói mà chưa có mục Bảng giá chạy lời gọi đầu rồi dừng ở lời gọi sau (usage-and-limits R2.5),
      không bị chặn trước lời gọi đầu.
    - workflow-engine/05 cũng thêm trường vào `EngineSection`; nó chờ ticket này qua workflow-engine/04,
      usage-and-limits/03 và compliance-pdpl/03, nên không chạy song song.
    - compliance-pdpl/03 bước 1 tự ghi giá trị cho hồ sơ mock; ticket này đã ghi đúng các giá trị đó, nên ticket kia chỉ
      còn kiểm.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): dựng xong trên `main` (lane 1). Khác ticket hay quyết khi dựng:
    - (1) Lượt Studio đọc `engine` của bản kê qua cổng `PinnedEnginePort.engine(tenant_id, run_manifest_hash)` khai trong
      `dw_agent_runtime.ports`, đáp ứng bởi `SqlRunManifestEngines` của `dw_studio` (một giao dịch riêng dưới RLS của công
      ty lượt), không qua `PinnedResolver.load` mỗi lời gọi: thân bản kê đánh địa chỉ theo nội dung nên đọc một lần, giữ
      trong bộ nhớ đệm LRU 256 mục theo (công ty, băm). Cửa không giữ `PinnedResolver`; nó chỉ có `RunContext`. Worker chưa
      nhận lượt Studio và chưa phụ thuộc `dw_studio`, nên bộ phân giải của worker không có cổng này: mọi lời gọi của lượt
      Studio ở đó bị từ chối (`manifest_not_found`) tới khi workflow-engine/04 nối nó. Nếu sai thì: runner của
      workflow-engine/04 trao `PinnedResolver` của lượt cho bộ phân giải và cổng này bỏ đi.
    - (2) `pin(tenant_id, plan_id, profile_ids)`: bỏ tham số thứ tư `default_profile`; hồ sơ mặc định là của bộ phân giải
      (một chủ, failure-modes #2). Gói lúc nhận lượt đọc bằng `RunIntakeTx.tenant_plan()` (`platform.entitlements` dưới RLS
      trong giao dịch của cửa), cho người và lane như nhau, vì `LaneRequester` không mang gói; không có dòng → chỉ lớp công
      ty được ghim. Nếu sai thì: lượt của người lấy `AccessContext.plan_id`, chỉ lane đọc bảng.
    - (3) `ResolvedRoute` thêm `budgets` (trần của hồ sơ như đang nạp, không ghim), vì cửa ngân sách, gateway và nén cần
      trần mà không được đọc registry. `content_hash` là một hàm duy nhất, `profile_hash` = băm `pinned_routes()` (mọi
      route trừ `embedding`), nên băm của câu trả lời và băm trong bản kê là một. Nếu sai thì: băm cả hồ sơ ở
      `ResolvedRoute`, băm route ở bản kê, và R1.5 so cái thứ hai.
    - (4) Bộ đo khi bộ phân giải từ chối vẫn ghi dòng, định giá theo model nhà cung cấp trả về (token đã tiêu); cửa từ chối
      trước lời gọi là cửa ngân sách. `route_cost` nhận `PriceKey` (`provider`, `model`) thay vì `ModelRoute`.
      Nếu sai thì: bộ đo bỏ dòng và ghi log.
    - (5) Cờ năng lực: bool mặc định `false`, `max_strict_tools` và `max_input_tokens` mặc định null. `make check-model`
      đo ngày 5/11/2026 trên gateway thật: `strict_tools` và `numeric_bounds` đều có ở `gpt-5.6-luna` (Responses),
      `gpt-4.1` và `gpt-4o-mini`, nên `luna.yaml` và `gateway.yaml` khai hai cờ đó; `deepseek`, `openai` không đo được (endpoint
      và khóa khác), để không khai (đọc là không hỗ trợ). `routing_policy_version` của sáu tệp lên một bậc minor vì nội
      dung đổi. Migration thêm `ck_plan_model_profiles_profile_id` (khác rỗng).
    - (6) `ArtifactKindEntry.model_profiles` là trường duy nhất có mặc định (`no_model_profiles`); docstring nói vì sao.
      `TenantOverlay.existing` không còn tạo lớp rỗng khi đọc (bộ phân giải hỏi theo từng công ty mỗi lời gọi; failure-modes
      #6). `openai_chat_model` tách khỏi factory để `check-model` dựng model từng route như agent. `RuntimeSeam.profiles`
      thành `RuntimeSeam.models` (`ModelResolver`); `AgentSpec.profiles` thành `models`.
    - (7) "Lượt kết thúc `failed`" (R1.5): bộ phân giải ném `EntitlementDeniedError` `model_profile_unavailable` trước khi
      gửi, đã test 0 lời gọi tới adapter; đặt lượt `failed` là việc của runner lượt Studio (workflow-engine/04), chưa có.
    - Đầu ra `make check-model` (5/11/2026, `DW_MODEL_PROVIDER=openai`):

        ```
        provider=openai profile=luna endpoint=portal.dxrank.vn
        ok   structured_extraction  openai_responses/gpt-5.6-luna answered by gpt-5.6-luna: in=80 out=43 cost=$0.00007 3698ms
        ok   reasoning              openai_responses/gpt-5.6-luna answered by gpt-5.6-luna: in=81 out=72 cost=$0.00010 2666ms
        ok   structured_extraction  openai_responses/gpt-5.6-luna strict_tools=True, numeric_bounds=True
             structured_extraction  openai_responses/gpt-5.6-luna max_strict_tools: not probed
        ok   fallback               openai_compatible/gpt-4o-mini strict_tools=True, numeric_bounds=True
             fallback               openai_compatible/gpt-4o-mini max_strict_tools: not probed
        provider=openai profile=gateway endpoint=portal.dxrank.vn
        ok   structured_extraction  openai_responses/gpt-5.6-luna answered by gpt-5.6-luna: in=81 out=39 cost=$0.00006 2433ms
        ok   reasoning              openai_compatible/gpt-4.1 answered by gpt-4.1: in=85 out=8 cost=$0.00023 1727ms
        ok   structured_extraction  openai_responses/gpt-5.6-luna strict_tools=True, numeric_bounds=True
             structured_extraction  openai_responses/gpt-5.6-luna max_strict_tools: not probed
        ok   reasoning              openai_compatible/gpt-4.1 strict_tools=True, numeric_bounds=True
             reasoning              openai_compatible/gpt-4.1 max_strict_tools: not probed
        ok   fallback               openai_compatible/gpt-4o-mini strict_tools=True, numeric_bounds=True
             fallback               openai_compatible/gpt-4o-mini max_strict_tools: not probed
        ```

        Lần chạy đầu (trước khi khai) in `FAIL ... strict_tools: declared False, measured True` cho mỗi route thật và thoát
        khác 0: phép so nhìn thấy chênh lệch.

    - Test: `test_model_resolver.py` (bốn cửa chạy thật cho một công ty có hồ sơ riêng, cùng `content_hash` và route; lọc
      gói, gói không dòng, `background`, danh mục không đọc được, lớp công ty không lọc; không `RunContext`; bản kê: đọc route
      đã ghim, nội dung đổi, gói bỏ hồ sơ, không ghim, bản kê cũ, không có cổng; bộ đệm có giới hạn; quét mã MR1/MR6 kèm ca
      trồng lỗi), `test_tenant_overlay.py` (MR2), `test_model_profile_v2.py` (R2.3, R3.1, R3.2 trên sáu tệp thật và các tệp
      hỏng), `test_run_manifest_model.py` (hình bản kê, `secret_version` ở bốn mức, băm khác route, `embedding`),
      `test_run_request.py` (R1.4-R1.6 qua `RunRequestService` thật: ghim theo giá trị, đổi hồ sơ mặc định sau khi nhận,
      mặc định ngoài gói, hồ sơ khai ngoài gói → 0 dòng lượt và 0 bản kê, công ty khác), `test_plan_model_profiles.py` và
      `test_privileges.py` (bảng, gieo, mọi `profile_id` có trong `configs/models` kèm ca trồng lỗi, chỉ SELECT),
      `test_plan_model_profiles_cache.py`, `test_check_model_capabilities.py`, `test_release_manifest.py`.
    - `mutations/02.yaml` 21 đột biến, chưa chạy bằng `mutate.py`; các bộ mới xanh ngay lần đầu nên chạy tay 12 (MR1 ở cửa
      ngân sách, gateway, nén; MR2 ×2; MR3 lọc gói, lỗi đọc; MR4 so băm, đọc registry thay bản kê; MR5 mặc định `vn`, `VN`;
      MR6), mỗi cái đỏ, cây khôi phục bằng bản sao.
    - `reviewing-feature-security` (đọc): công ty, gói, workspace của lời gọi từ `RunContext`; lúc ghim từ giao dịch của cửa
      nhận lượt, không từ thân yêu cầu; lớp nền tảng chưa lọc chỉ qua `platform_profile` ở composition root và script (test
      quét); bảng gói toàn cục, chỉ migration ghi; bản kê không mang khóa bí mật; bản kê của công ty khác đọc là không có.
    - MEDIUM để lại: (a) lane `studio_runs` (workflow-engine/04) phải dựng `RunContext.plan_id` từ gói hiện hành của công ty
      (dòng lượt Studio ghi `actor_plan_id` rỗng) và nối `SqlRunManifestEngines` ở worker, không thì mọi lời gọi của lượt
      Studio bị từ chối (đóng khi thiếu); (b) quét MR1 mù với registry giữ dưới tên không có `profile`; (c) `check-model`
      chỉ thăm dò route đầu tiên của mỗi cặp (`provider`, `model`); (d) mỗi lời gọi model thêm một lần đọc danh mục gói
      (bộ đệm 30 giây) và một lần băm hồ sơ.
    - Còn ở lúc đóng hàng đợi: `mutate.py` cho `mutations/02.yaml`; `make test-integration` toàn bộ; P50/P95/P99 của cửa
      nhận lượt Studio (thêm một câu đọc `platform.entitlements` và phần ghim) và của một lời gọi model qua gateway và agent
      (thêm lần hỏi bộ phân giải) so với commit đầu hàng đợi; `/code-review`. Không route mới, không image, không URL ra
      ngoài mới, nên không `reviewing-deployment-security`.
