# 05 — Biên mạng: rate limit theo địa chỉ, net_guard chỉ địa chỉ toàn cầu, Qdrant và Valkey có xác thực

Status: needs-triage
Blocked by: 01
Area: studio
Yêu cầu: R7.1, R7.2, R8.1, R8.2, R8.3, R8.4, G7, FH20, FH21, FH22, FH23, FH24

## Mục tiêu

Một client không lách giới hạn tốc độ bằng bearer ngẫu nhiên; nền tảng có một chính sách địa chỉ ra
ngoài mà egress client của `connections-and-vault` dùng lại; Qdrant và Valkey đòi xác thực ở mọi
profile, profile triển khai không khởi động khi thiếu; ảnh bên thứ ba ghim digest (R7, R8, G7,
FH20-FH24; ADR-0115 (Accepted) quyết định 5). Triển khai cần người đặt bí mật mới trên host uat và
production.

## Việc cần làm

Giới hạn tốc độ (R7.1, G7):

1. `RateLimitMiddleware.dispatch`: mỗi request, trừ `/api/v1/health` và `/api/v1/ready`, đếm vào xô
   của địa chỉ client (khóa `ip:` cộng địa chỉ) với ngưỡng `10 × requests_per_minute`, và khi có
   header `Authorization` đếm thêm vào xô của bearer (khóa `tok:` cộng SHA-256) với ngưỡng
   `requests_per_minute`; trả 429 kèm `Retry-After` khi một trong hai xô vượt; đường quét 10.000 khóa
   giữ nguyên.
2. Docstring của middleware nói bearer chưa được xác minh ở tầng này và bộ đếm theo tiến trình;
   middleware này chỉ chặn ở cửa API, còn giới hạn theo tenant dùng chung giữa bản sao thuộc
   `RateLimiterPort` của `usage-and-limits` (DO-49).

Chính sách địa chỉ (R7.2):

3. `dw_kernel.net_guard` thêm `forbidden_address(ip)`: chuẩn hóa IPv4-mapped, 6to4 `2002::/16`,
   Teredo và NAT64 `64:ff9b::/96` về IPv4 nhúng, rồi từ chối trừ khi địa chỉ `is_global` và không
   `is_multicast`; và `resolve_checked(host, port)`: phân giải một lần, từ chối nếu một câu trả lời bị
   cấm, trả các địa chỉ đã kiểm để egress client ghim. `ensure_allowed_outbound_url` dùng
   `resolve_checked` và giữ chữ ký; host trong danh sách máy chủ được phép vẫn qua theo tên.
4. Docstring của `net_guard` nói rõ: kiểm lúc xác thực URL gốc do người vận hành cấu hình, không ghim
   địa chỉ lúc kết nối; URL do tenant đưa đi qua egress client của `connections-and-vault`.
5. Compose truyền `DW_API_OUTBOUND_ALLOWED_HOSTS` cho dịch vụ `api` và
   `DW_WORKER_OUTBOUND_ALLOWED_HOSTS` cho dịch vụ `worker` từ `.env`; `.env.example` thay
   `DW_CHAT_OUTBOUND_ALLOWED_HOSTS` bằng hai biến này.

Kho dữ liệu (R8.1, R8.2, R8.4):

6. Chuyển `QDRANT__SERVICE__API_KEY` và `--requirepass` của Valkey từ
   `infra/compose/docker-compose.dev.yml` sang `infra/compose/docker-compose.yml`; client đọc
   `QDRANT_API_KEY` và `REDIS_URL` có mật khẩu; healthcheck của Qdrant và Valkey dùng thông tin xác
   thực; overlay dev bỏ phần trùng.
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

- [ ] R7.1 (FH20): `10 × L + 1` request từ một địa chỉ, mỗi request một bearer ngẫu nhiên → request
      cuối 429; bỏ xô địa chỉ → đỏ.
- [ ] R7.1: một bearer vượt `L` request trong 60 giây → 429 dù địa chỉ còn dưới `10 × L`.
- [ ] R7.2 (FH21): resolver giả trả `100.64.0.1`, `100.100.100.200`, `224.0.0.1`, `ff02::1`,
      `::ffff:169.254.169.254`, `64:ff9b::a9fe:a9fe`, `2002:a9fe:a9fe::1` và một địa chỉ Teredo nhúng
      `169.254.169.254` → `OutboundUrlError`; `8.8.8.8` giả lập → nhận; khôi phục vị từ cũ → đỏ với
      `100.64.0.1`, `100.100.100.200`, `224.0.0.1`.
- [ ] R7.2: host có tên trong danh sách máy chủ được phép qua theo đúng tên, không phân giải;
      `docker compose -f infra/compose/docker-compose.yml config` cho thấy hai biến danh sách ở `api`
      và `worker`.
- [ ] R8.1 (FH22): compose smoke: gọi Qdrant không kèm API key → 401; `redis-cli PING` không mật khẩu
      → `NOAUTH`; API và worker vẫn khỏe với thông tin xác thực.
- [ ] R8.2 (FH22): settings profile `uat` thiếu `qdrant_api_key` → `validate_for_profile` ném lỗi ở
      API và worker; `redis_url` của API không mật khẩu → ném lỗi; profile `local` không đòi.
- [ ] R8.3 (FH23): gỡ `@sha256:` khỏi một `image:` → `scripts/verify_invariants.py` đỏ.
- [ ] R8.4 (FH24): `DATA_SOURCE_NAME` dùng `dw_app` → kiểm ở bước 10 đỏ; `dw_monitor` SELECT một bảng
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
- spec: R7, R8, G7, FH20-FH24; si-platform `packages/python/hosts/si_api/src/si_api/http/rate_limit.py`
  (xô địa chỉ `10 × L`).

## Comments

- 2026-10-24 (agent): kiểm vòng sửa 4, lượt ba: neo ADR-0115 (Accepted) ở Nguồn trỏ lại quyết định 5 (một chính
  sách địa chỉ), vì các lần sửa ADR đó đã dời quyết định 5 khỏi các dòng neo cũ.
