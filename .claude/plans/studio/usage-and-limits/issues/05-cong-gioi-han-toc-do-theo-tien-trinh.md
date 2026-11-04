# 05 — Một RateLimiterPort và bộ đếm theo tiến trình cho giới hạn tốc độ W1

Status: resolved (2026-11-02, main)
Area: studio
Yêu cầu: R7.1, R7.2, R7.3, UL14

## Mục tiêu

Mọi giới hạn tốc độ theo công ty (60 sự kiện mỗi phút của một nguồn dữ liệu Data Hub, 20 lần 409 trùng mỗi
người mỗi đối tượng trong 10 phút trượt của custom-objects) hỏi một `RateLimiterPort` của usage-and-limits và
không tự viết bộ đếm; W1 đáp port bằng
bộ đếm theo tiến trình ở `giới hạn / số replica`, không cần Valkey (spec R7; DO-49). GCRA trên Valkey là
adapter thứ hai ở W2.

## Việc cần làm

1. Protocol `RateLimiterPort` trong `packages/python/dw_platform/src/dw_platform/application/rate_limit.py`, bất
   đồng bộ để adapter GCRA trên Valkey của W2 đáp cùng Protocol mà không sửa bên gọi:
   `async def acquire(key: RateLimitKey, limit: int, window: timedelta) -> RateDecision(allowed: bool, retry_at: datetime | None)`
   tính một lượt, và `async def peek(key, limit, window) -> RateDecision` hỏi mà không tính lượt (spec R7.3);
   `RateLimitKey` là hợp của hai dataclass đóng băng, `SourceKey(tenant_id: TenantId, source_id: UUID)` và
   `PrincipalObjectKey(tenant_id: TenantId, principal_id: UUID, object_id: UUID)` (`TenantId` của
   `packages/python/dw_kernel/src/dw_kernel/ids.py:32`, `UUID` của `uuid`), không nhận chuỗi tự do: `__post_init__`
   ném `TypeError` khi một trường không đúng kiểu, và adapter ném `TypeError` khi `key` không phải một trong hai kiểu,
   nên bên gọi không truyền được băm của bearer, kể cả khi bỏ qua mypy (spec R7.2).
2. Adapter `InProcessRateLimiter(replicas: int, clock: UtcClock)` trong
   `packages/python/dw_platform/src/dw_platform/adapters/rate_limit.py` (`UtcClock` của
   `packages/python/dw_kernel/src/dw_kernel/ports.py:17`): cửa sổ trượt mỗi khóa trong bộ nhớ tiến trình, khóa trong
   bảng là chính `RateLimitKey` (kiểu và mọi trường, `tenant_id` gồm cả), độ dài do bên gọi nêu (một phút cho Data
   Hub, mười phút cho kiểm trùng); phần của mỗi tiến trình bằng `floor(limit / replicas)`, nên khi một bản sao chết
   tổng giới hạn thấp đi chứ không cao lên; `retry_at` là lúc lượt cũ nhất ra khỏi cửa sổ; khóa không dùng quá độ
   dài cửa sổ của nó cộng một phút bị dọn để bộ nhớ không phình (`.claude/rules/failure-modes.md` mục 6).
3. `replicas` là số tiến trình API đang chạy (số container nhân số worker uvicorn; hôm nay một tiến trình mỗi container,
   `infra/docker/api.Dockerfile:92`): trường `api_replicas: int | None` (`ge=1`, env `DW_API_REPLICAS`, mặc định
   `None`) trong `apps/api/src/dw_api/settings.py`; `validate_for_profile` từ chối khởi động khi `is_deployed` mà
   trường trống, vì mặc định 1 ở N tiến trình nhân tổng giới hạn lên N lần (`failure-modes.md` mục 7); `local` và `test`
   hiểu trống là 1; `infra/compose/docker-compose.uat.yml` và `infra/compose/docker-compose.prod.yml` đặt
   `DW_API_REPLICAS: "1"` ở dịch vụ `api`.
4. Gắn đúng một instance ở composition root của API (`apps/api/src/dw_api/bootstrap/wiring.py`), giữ trên `Container`
   làm chỗ hai bên dùng của W1 nhận bằng injection (workflow-triggers/02 trả 429 ở endpoint Data Hub, kiểm trùng của
   custom-objects/03 ở record service, cả hai trong tiến trình API); không module nào giữ instance toàn cục. Worker
   không có instance ở W1 vì không bên dùng nào của W1 chạy trong worker (`failure-modes.md` mục 1); bên dùng đầu tiên
   trong worker gắn instance của nó ở `apps/worker/src/dw_worker/main.py` với số tiến trình worker của riêng nó.
5. `apps/api/src/dw_api/middleware/rate_limit.py` giữ nguyên vai chặn ở cửa API; nó không phải chủ giới hạn
   theo công ty và không ai gọi nó thay port này.

## Tiêu chí chấp nhận

- [x] R7.1 (UL14): giới hạn 60 với `replicas` = 2: lần thứ 30 trong một phút ở một tiến trình được nhận,
      lần thứ 31 bị từ chối kèm `retry_at`; phút sau nhận lại; với `replicas` = 1 thì lần 60 nhận, lần 61 từ
      chối.
- [x] R7.1: settings của profile `uat` đủ mọi trường bắt buộc khác nhưng không có `DW_API_REPLICAS` →
      `validate_for_profile` ném `RuntimeError` nêu `DW_API_REPLICAS`; profile `local` không có nó → adapter dựng với
      `replicas` = 1; bỏ phép kiểm ở profile triển khai → test đỏ.
- [x] R7.2 (UL14): hai `SourceKey` dựng riêng từ cùng `(tenant_id, source_id)`, như hai yêu cầu mang hai bearer khác
      nhau sẽ dựng, chia chung một bộ đếm; `SourceKey(tenant_id, "băm-bearer")` và `acquire("chuỗi", 60, ...)` (kèm
      `# type: ignore`) ném `TypeError`; thêm `str` vào hợp `RateLimitKey` hay bỏ phép kiểm kiểu → test đỏ; hai
      `PrincipalObjectKey` khác người gọi hay khác đối tượng có bộ đếm riêng. Test HTTP hai bearer tới một Nguồn dữ
      liệu thuộc bên dùng (workflow-triggers:R5.9, ticket 02 của nó).
- [x] R7.2 (UL14): chéo tenant, công ty A dùng hết giới hạn của `SourceKey(A, s)` và của `PrincipalObjectKey(A, p, o)`
      → `SourceKey(B, s)` và `PrincipalObjectKey(B, p, o)` cùng `s`, `p`, `o` vẫn được nhận và `peek` của B trả cho
      qua; bỏ `tenant_id` khỏi khóa của bảng đếm → test đỏ.
- [x] R7.3 (UL14): `PrincipalObjectKey`, giới hạn 20, cửa sổ 10 phút, `replicas` = 1: `peek` sau 19 lượt tính trả
      cho qua và bộ đếm vẫn 19; sau lượt tính thứ 20 `peek` trả đã đủ kèm `retry_at` bằng lúc lượt đầu ra khỏi cửa
      sổ; tới lúc đó `peek` trả cho qua; `peek` tính lượt → test đỏ.
- [x] Xong: `cổng nhanh của ticket theo wave-close.md; tích hợp đầy đủ, mutate.py và đo trễ lúc đóng hàng đợi` xanh.

## Nguồn

- `apps/api/src/dw_api/middleware/rate_limit.py:36-41`, hôm nay `apps/api/src/dw_api/middleware/rate_limit.py:79-92`;
  spec: R7.2 (limiter hôm nay khóa theo băm bearer chưa xác minh).
- spec: R7.1; workflow-triggers:R5.9; custom-objects:R7.6; DO-49.
- `apps/api/src/dw_api/settings.py:366` (`validate_for_profile`); `infra/docker/api.Dockerfile:92`;
  `packages/python/dw_kernel/src/dw_kernel/ports.py:17`; `packages/python/dw_kernel/src/dw_kernel/ids.py:32`.

## Comments

- 2026-10-23 (agent): ticket mới theo DO-49 và câu Q3 của requirements.md (Đạt, 23/10/2026). Bên dùng là
  workflow-triggers/02 (Data Hub) và kiểm trùng của custom-objects; hai ticket đó nên chờ ticket này.
- 2026-10-24 (agent): áp DO-35 (Đạt, 24/10/2026; số tạm UNVERIFIED): khóa có kiểu thứ hai (công ty, người gọi,
  đối tượng), độ dài cửa sổ trượt do bên gọi nêu và `peek` không tính lượt cho giới hạn dò trùng của
  custom-objects/03 (B:custom-objects:R7.6\~usage-and-limits:R7.2); Data Hub đổi lời gọi sang
  `acquire(SourceKey(...), 60, timedelta(minutes=1))`.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (chỉ builder check: ticket không có
  migration hay route mới; chạy trong ngữ cảnh chính, không subagent, theo lời giao việc), đo trên `f95a89f`: 1 CRITICAL,
  3 HIGH, đã sửa theo khuyến nghị.
    - CRITICAL (mục 11): bộ đếm khóa theo `tenant_id` mà không có test âm chéo tenant. Sửa: tiêu chí "chéo tenant" của
      R7.2 và bước 2 (khóa của bảng đếm là chính `RateLimitKey`). Nếu sai thì: không có đường sai nào được chấp nhận;
      CRITICAL không nhận như rủi ro.
    - HIGH (mục 16, 7): `replicas` "đọc từ `settings` (tối thiểu 1)" không nói settings nào, đếm gì, và mặc định 1 ở N
      tiến trình nhân giới hạn lên N lần. Sửa: bước 3 (`DW_API_REPLICAS` đếm tiến trình API, bắt buộc ở profile triển
      khai, overlay uat/prod đặt 1) và tiêu chí R7.1 thứ hai; worker không có instance ở W1 (bước 4). Nếu sai thì: bên
      dùng nào chạy trong worker (vd. làn `studio_inbound` của workflow-triggers/02) gắn instance ở
      `apps/worker/src/dw_worker/main.py` với `DW_WORKER_REPLICAS` bắt buộc ở profile triển khai, cùng hình.
    - HIGH (mục 23 qua `code-quality.md` Liskov; cùng hình ticket 01): Protocol đồng bộ thì adapter Valkey W2 (I/O mạng)
      không đáp được mà không sửa mọi bên gọi. Sửa: bước 1, `async def acquire`, `async def peek`. Nếu sai thì: giữ đồng
      bộ và W2 đổi chữ ký ở workflow-triggers/02 và custom-objects/03.
    - HIGH (mục 29): tiêu chí R7.2 không thể đỏ trong ticket này: không đường request nào mang bearer, "mypy báo lỗi"
      không là test chạy được, không mã nào ở đây dựng khóa từ bearer. Sửa: bước 1 (kiểu trường `TenantId`, `UUID`;
      `TypeError` ở `__post_init__` và ở adapter) và tiêu chí R7.2 viết lại ở mức port; test HTTP hai bearer thuộc
      workflow-triggers/02 (R5.9 của nó đã nói "không theo bearer"). Nếu sai thì: ticket này thêm một test mypy chạy
      `mypy.api.run` trên một đoạn mã gọi sai.
- 2026-11-02 (agent): MEDIUM và LOW của gate, chưa sửa, cho người dựng:
    - M1: neo `apps/api/src/dw_api/middleware/rate_limit.py:36-41` ở Hiện trạng của spec (đọc ở `ab33703`) đã trôi:
      hôm nay dòng 36-41 là hằng số; xô bearer ở dòng 79-92 (Nguồn của ticket đã thêm neo này), và
      runtime-hardening/02 (resolved) thêm xô theo địa chỉ `10 × L`. Middleware vẫn băm bearer chưa xác minh, nên R7.2
      vẫn đúng; Hiện trạng của spec chưa sửa.
    - M2: lượt bị từ chối của `acquire` có tính vào cửa sổ không? Khuyến nghị: không, nên mỗi khóa giữ tối đa
      `floor(limit / replicas)` mốc thời gian và người gõ liên tục vẫn được nhận lại khi lượt cũ nhất ra (khớp `retry_at`
      của R7.3).
    - M3: `limit < replicas` cho phần mỗi tiến trình 0, mọi lượt bị từ chối (đóng khi thiếu); ghi rõ trong docstring,
      không nâng lên 1.
    - M4: lúc dọn khóa hết hạn không nêu (mỗi `acquire` khi bảng quá một ngưỡng như `_MAX_KEYS` của middleware, hay
      định kỳ); không có trần số khóa khi nhiều khóa khác nhau tới trong một cửa sổ.
    - M5: đồng hồ: `UtcClock` tiêm vào; đồng hồ tường nhảy lùi làm cửa sổ dài ra; test dùng đồng hồ giả.
    - M6: tên trường `source_id` ở đây, `endpoint_id` ở workflow-triggers/02 (khóa `(tenant_id, endpoint_id)`); cùng
      một id Nguồn dữ liệu.
    - M7: instance trên `Container` chưa có bên đọc trong ticket này; bên đọc đã nêu tên (workflow-triggers/02,
      custom-objects/03) và cả hai chờ ticket này (`failure-modes.md` mục 1).
    - M8: khóa không mang mục đích; hai bên gọi cùng kiểu khóa với giới hạn khác nhau sẽ chung bộ đếm. W1 mỗi kiểu khóa
      một bên gọi.
    - L1: bước 5 chỉ nói điều không đổi.
- 2026-11-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): M2 theo khuyến nghị: lượt bị từ chối không tính, mỗi khóa giữ tối
  đa `floor(limit / replicas)` mốc thời gian. M3: phần 0 từ chối mọi lượt với `retry_at` None (không lượt chờ nào
  giúp), ghi ở docstring của `RateDecision` và adapter. M4: dọn từ `acquire`, tối đa mỗi phút một lần, khóa có
  `last_used + window + 1 phút < now`; không trần số khóa (khóa là id đã xác minh). M5 theo khuyến nghị: `UtcClock`
  tiêm vào, đồng hồ lùi làm cửa sổ dài ra (nghiêng về từ chối), test dùng `FixedClock`. M8 theo khuyến nghị: docstring
  của `application/rate_limit.py` ghi W1 mỗi kiểu khóa một bên gọi, bên gọi thứ hai thêm kiểu khóa riêng. Nếu sai
  thì: M2 tính lượt bị từ chối là thêm một `append` ở nhánh từ chối; M3 `retry_at = now + window` là một dòng.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): `ApiContainer.rate_limiter` là `RateLimiterPort | None = None`, không
  bắt buộc, để hơn hai mươi container dựng tay trong test không phải sửa; `build_container` luôn đặt nó, trước cổng
  database vì bộ đếm không cần Postgres. `replicas = settings.api_replicas or 1` ở wiring là chỗ duy nhất đọc trống là
    1. Thêm `api_replicas=1` vào hai bộ settings triển khai của test (`test_dev_endpoints.deployed_settings`,
       `test_zalo_webhook_endpoint.deployed`) và một dòng chú thích `DW_API_REPLICAS` trong `.env.example`. `__len__` và
       `replicas` trên adapter để test đọc bảng và số tiến trình. Nếu sai thì: trường bắt buộc nghĩa là sửa mọi fixture
       dựng `ApiContainer`.
- 2026-11-02 (agent): resolved. `RateLimiterPort`, `SourceKey`, `PrincipalObjectKey`, `RateDecision` ở
  `dw_platform/application/rate_limit.py`; `InProcessRateLimiter` ở `dw_platform/adapters/rate_limit.py`;
  `DW_API_REPLICAS` bắt buộc khi `is_deployed`, overlay uat/prod đặt `"1"` (`docker compose ... config` hợp lệ);
  một instance trên `ApiContainer`, worker không có. Test: `test_rate_limiter.py` 27 (R7.1, M2, M3, R7.2 kiểu khóa,
  chéo tenant, R7.3, dọn khóa), `test_rate_limiter_replicas.py` 6 (R7.1 profile, env, wiring); unit dw_platform 237,
  unit api 349, contract api 28 xanh trên HEAD cộng thay đổi của ticket (cây làm việc có việc dở của ticket 01).
  Một mutation thử tay (bỏ `tenant_id` khỏi so sánh của `SourceKey`) làm test chéo tenant đỏ; 12 mutation trong
  `mutations/05.yaml` đã viết, chưa chạy (lúc đóng đợt). `reviewing-feature-security`: ranh giới 1 (bộ đếm khóa theo
  tenant, test âm chéo tenant) và 6 (dọn khóa, phần 0 đóng khi thiếu, thiếu `DW_API_REPLICAS` không khởi động) áp
  dụng; 2-5 không (không quyết định quyền, không chạm agent, nội dung, audit; khóa do bên dùng dựng từ ngữ cảnh đã
  xác minh). `reviewing-deployment-security`: §1 áp dụng (trường mới chặn bằng `is_deployed`, test uat/production);
  §2-§6 không (không route, không bí mật, không CORS, không URL ra ngoài, không image mới).
