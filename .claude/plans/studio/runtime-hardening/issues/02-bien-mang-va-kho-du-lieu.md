# 02 — Biên mạng: rate limit theo địa chỉ, net_guard chỉ địa chỉ toàn cầu, Qdrant và Valkey có xác thực

Status: needs-triage
Blocked by: .claude/plans/studio/foundations-hardening/issues/01-test-khong-the-do.md
Area: studio
Yêu cầu: R7.1, R7.2, R8.1, R8.2, R8.3, R8.4, G7, RH20, RH21, RH22, RH23, RH24

## Mục tiêu

Một client không lách giới hạn tốc độ bằng bearer ngẫu nhiên; nền tảng có một chính sách địa chỉ ra
ngoài mà egress client của `connections-and-vault` dùng lại; Qdrant và Valkey đòi xác thực ở mọi
profile, profile triển khai không khởi động khi thiếu; ảnh bên thứ ba ghim digest (R7, R8, G7,
RH20-RH24; ADR-0115 (Accepted) quyết định 5). Triển khai cần người đặt bí mật mới trên host uat và
production.

## Việc cần làm

Giới hạn tốc độ (R7.1, G7):

1. `RateLimitMiddleware.dispatch`: mỗi request, trừ `/api/v1/health` và `/api/v1/ready`, đếm vào xô
   của địa chỉ client: request có header `Authorization` vào khóa `ip:` cộng địa chỉ với ngưỡng
   `10 × requests_per_minute` và thêm vào xô của bearer (khóa `tok:` cộng SHA-256) với ngưỡng
   `requests_per_minute`; request không có header vào khóa `anon:` cộng địa chỉ với ngưỡng
   `requests_per_minute` như hôm nay. Địa chỉ là `request.client.host` (uvicorn chỉ tin
   `X-Forwarded-For` từ `FORWARDED_ALLOW_IPS`); IPv6 lấy prefix `/64`. Trả 429 kèm `Retry-After` khi
   một xô vượt; request bị xô địa chỉ từ chối không tạo khóa `tok:`; đường quét 10.000 khóa giữ
   nguyên.
2. Docstring của middleware nói bearer chưa được xác minh ở tầng này và bộ đếm theo tiến trình;
   middleware này chỉ chặn ở cửa API, còn giới hạn theo tenant dùng chung giữa bản sao thuộc
   `RateLimiterPort` của `usage-and-limits` (DO-49).

Chính sách địa chỉ (R7.2):

3. `dw_kernel.net_guard` thêm `forbidden_address(ip)`: chuẩn hóa IPv4-mapped, 6to4 `2002::/16`,
   Teredo và NAT64 `64:ff9b::/96` về IPv4 nhúng, rồi từ chối trừ khi địa chỉ `is_global` và không
   `is_multicast`; và `resolve_checked(host, port)`: phân giải một lần, từ chối nếu một câu trả lời bị
   cấm, trả các địa chỉ đã kiểm để egress client ghim. `ensure_allowed_outbound_url` dùng
   `resolve_checked` và giữ chữ ký; host trong danh sách máy chủ được phép vẫn qua theo tên (khớp
   nguyên tên, không phân biệt hoa thường); host là IP literal đi qua `forbidden_address` không phân
   giải. `allow_private=True` chỉ nới `is_private` và `is_loopback`; link-local, multicast,
   unspecified, reserved và dạng nhúng vẫn bị từ chối.
4. Docstring của `net_guard` nói rõ: kiểm lúc xác thực URL gốc do người vận hành cấu hình, không ghim
   địa chỉ lúc kết nối; URL do tenant đưa đi qua egress client của `connections-and-vault`.
5. Compose truyền `DW_API_OUTBOUND_ALLOWED_HOSTS` cho dịch vụ `api` và
   `DW_WORKER_OUTBOUND_ALLOWED_HOSTS` cho dịch vụ `worker` từ `.env`; `.env.example` thay
   `DW_CHAT_OUTBOUND_ALLOWED_HOSTS` bằng hai biến này.

Kho dữ liệu (R8.1, R8.2, R8.4):

6. Chuyển `QDRANT__SERVICE__API_KEY: ${QDRANT_API_KEY:?}` và `--requirepass ${REDIS_PASSWORD:?}` của
   Valkey từ `infra/compose/docker-compose.dev.yml` sang `infra/compose/docker-compose.yml`; client đọc
   cùng biến `QDRANT_API_KEY` và `REDIS_URL` dựng từ `REDIS_PASSWORD`; healthcheck của Qdrant và Valkey
   dùng thông tin xác thực; overlay dev bỏ phần trùng; `.env.example` mang giá trị chỉ dùng cho dev.
   Langfuse (profile `observability`) chuyển sang một dịch vụ Valkey riêng (`langfuse-valkey`, mật khẩu
   `LANGFUSE_REDIS_PASSWORD`), `REDIS_CONNECTION_STRING` của nó trỏ vào đó.
7. `ApiSettings.validate_for_profile` từ chối `qdrant_api_key` trống và `redis_url` không có mật khẩu
   khi `settings.is_deployed`; `WorkerSettings.validate_for_profile` từ chối `qdrant_api_key` trống
   (worker không dùng Valkey).
8. Vai `dw_monitor` (`LOGIN NOSUPERUSER NOBYPASSRLS`, chỉ được cấp `pg_monitor`) trong
   `infra/compose/init/init-databases.sh` cho cluster mới, và một script admin idempotent theo mẫu
   `scripts/create_agent_role.py` cho cluster có sẵn; `postgres-exporter` nối bằng `dw_monitor`, mật
   khẩu lấy từ `.env`.

Ảnh (R8.3):

9. Mọi `image:` của ảnh bên thứ ba trong `infra/compose/*.yml` mang tag phiên bản cụ thể và
   `@sha256:` của đúng tag đó (postgres, valkey, qdrant, seaweedfs, rclone, keycloak, clickhouse,
   langfuse, langfuse-worker, postgres-exporter, alpine, alertmanager, prometheus); ảnh `dw-*:local`
   do repo build được miễn.
10. `scripts/verify_invariants.py` (chạy trong `make ci` qua `make test-architecture`) thêm hai kiểm:
    một `image:` bên thứ ba thiếu `@sha256:` thì đỏ; `DATA_SOURCE_NAME` của `postgres-exporter` không
    dùng `dw_monitor` thì đỏ. Bước trivy ở `.github/workflows/ci.yml` quét cả ảnh bên thứ ba đã ghim.

## Tiêu chí chấp nhận

- [ ] R7.1 (RH20): `10 × L + 1` request từ một địa chỉ, mỗi request một bearer ngẫu nhiên → request
      cuối 429; bỏ xô địa chỉ → đỏ.
- [ ] R7.1: `L + 1` request không `Authorization` từ một địa chỉ → request cuối 429; mỗi request một
      `X-Forwarded-For` giả từ một địa chỉ ngoài `FORWARDED_ALLOW_IPS` → vẫn một xô.
- [ ] R7.1: một bearer vượt `L` request trong 60 giây → 429 dù địa chỉ còn dưới `10 × L`.
- [ ] R7.2 (RH21): resolver giả trả `100.64.0.1`, `100.100.100.200`, `224.0.0.1`, `ff02::1`,
      `::ffff:169.254.169.254`, `64:ff9b::a9fe:a9fe`, `2002:a9fe:a9fe::1` và một địa chỉ Teredo nhúng
      `169.254.169.254` → `OutboundUrlError`; `8.8.8.8` giả lập → nhận; khôi phục vị từ cũ → đỏ với
      `100.64.0.1`, `100.100.100.200`, `224.0.0.1`; `allow_private=True` với `169.254.169.254` → vẫn
      `OutboundUrlError`, với `10.0.0.5` → nhận.
- [ ] R7.2: host có tên trong danh sách máy chủ được phép qua theo đúng tên, không phân giải;
      `docker compose -f infra/compose/docker-compose.yml config` cho thấy hai biến danh sách ở `api`
      và `worker`.
- [ ] R8.1 (RH22): compose smoke: gọi Qdrant không kèm API key → 401; `redis-cli PING` không mật khẩu
      → `NOAUTH`; API và worker vẫn khỏe với thông tin xác thực; `GET /collections` là endpoint thử 401;
      `docker compose -f infra/compose/docker-compose.yml config` với `QDRANT_API_KEY` trống → lỗi;
      profile `observability` khỏe với Valkey riêng của Langfuse.
- [ ] R8.2 (RH22): settings profile `uat` thiếu `qdrant_api_key` → `validate_for_profile` ném lỗi ở
      API và worker; `redis_url` của API không mật khẩu → ném lỗi; profile `local` không đòi.
- [ ] R8.3 (RH23): gỡ `@sha256:` khỏi một `image:` → `scripts/verify_invariants.py` đỏ.
- [ ] R8.4 (RH24): `DATA_SOURCE_NAME` dùng `dw_app` → kiểm ở bước 10 đỏ; `dw_monitor` SELECT một bảng
      tenant → `permission denied`; exporter vẫn xuất số đo.
- [ ] G7: `test_health_is_exempt_and_zero_disables` xanh.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `apps/api/src/dw_api/middleware/rate_limit.py:36-41`
- `apps/api/src/dw_api/middleware/rate_limit.py:34`
- `infra/compose/docker-compose.host.yml:94-97`
- `packages/python/dw_kernel/src/dw_kernel/net_guard.py:36-45`
- `packages/python/dw_kernel/src/dw_kernel/net_guard.py:49-75`
- `apps/api/src/dw_api/settings.py:208`
- `apps/worker/src/dw_worker/settings.py:182`
- `.env.example:254`
- `infra/compose/docker-compose.yml:19-25`
- `infra/compose/docker-compose.dev.yml:33`
- `infra/compose/docker-compose.yml:281`
- `infra/compose/docker-compose.yml:599`
- `apps/api/src/dw_api/settings.py:362-366`
- `apps/worker/src/dw_worker/settings.py:330`
- `infra/compose/docker-compose.host.yml:48`
- `docs/adr/0115-tenant-credentials-vault-and-one-egress-client.md:96-99`
- spec: R7, R8, G7, RH20-RH24; si-platform `packages/python/hosts/si_api/src/si_api/http/rate_limit.py`
  (xô địa chỉ `10 × L`).

## Comments

- 2026-10-24 (agent): kiểm vòng sửa 4, lượt ba: neo ADR-0115 (Accepted) ở Nguồn trỏ lại quyết định 5 (một chính
  sách địa chỉ), vì các lần sửa ADR đó đã dời quyết định 5 khỏi các dòng neo cũ.
- 2026-10-25 (agent): ticket chuyển từ foundations-hardening/05 sang đây thành ticket 02 khi spec tách (hai dòng Quyết định cuối của spec); kiểm soát FH20-FH24 thành RH20-RH24, cùng số, và cạnh tới ticket 01 cùng thư mục cũ thành đường dẫn tới foundations-hardening/01. Không đổi việc cần làm, không thêm cạnh.
- 2026-10-30 (agent): gate `checking-plan-readiness` lượt 1: CẦN XEM (0 CRITICAL, 5 HIGH), đã sửa theo khuyến nghị và
  ủy quyền (Quyết định 30/10 của spec): địa chỉ client và `X-Forwarded-For`; request không bearer giữ ngưỡng `L`;
  `allow_private` không nới link-local; bí mật kho bắt buộc trong compose; Langfuse có Valkey riêng. MEDIUM cho người
  làm: trivy chặn ở HIGH, CRITICAL với `--ignore-unfixed`; webhook nhà cung cấp chịu xô địa chỉ theo bước 1; khi bảng
  khóa chạm 10.000 chỉ quét cửa sổ đã hết, không xóa xô `ip:`; test `dw_monitor` tạo vai bằng chính script admin trên
  cluster test và vào `test_privileges.py`; RH21 có một đột biến cho mỗi bước chuẩn hóa dạng nhúng; mật khẩu
  `dw_monitor` trống bị từ chối như bí mật kho; `FROM` của Dockerfile repo không ghim digest (ngoài R8.3, ghi lại);
  nhiều người sau một NAT chung xô `10 × L` (đánh đổi đã biết).
