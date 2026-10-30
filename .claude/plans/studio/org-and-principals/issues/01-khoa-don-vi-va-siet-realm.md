# 01 — Khóa tổng hợp cho workspace, gỡ enum khai báo suông, siết realm Keycloak

Status: needs-triage
Area: studio
Yêu cầu: R1.1, R2.1, R3.1, R3.2, R3.3, R3.4, R9.1, OP1, OP2, OP3

## Mục tiêu

Bốn sửa P0 làm được ngay: workspace có khóa `(tenant_id, id)` làm đích cho FK kép của mọi bảng Studio (R1), kiểu trạng thái
tenant không ai đọc biến mất (R2), realm Keycloak cấp token 300 giây, xoay refresh token, chống dò mật khẩu để thu hồi
không còn chờ 8 giờ (R3), và màn workspace bỏ chú thích "(phòng ban)" (R9, DO-04). Gộp từ brief B2 ticket 01, 02. Ticket
này là người tạo duy nhất của `uq_workspaces_tenant_id_id`; tenant-config/02 chờ nó (OPS-a.2).

## Việc cần làm

1. **Khóa tổng hợp.** Migration (id hex của `alembic revision`): `ALTER TABLE platform.workspaces ADD CONSTRAINT uq_workspaces_tenant_id_id UNIQUE (tenant_id, id)`
   (tên sinh từ `dw_kernel.naming.NAMING_CONVENTION`, `uq_%(table_name)s_%(column_0_N_name)s`). Không đổi dữ liệu. Không
   migration nào khác tạo ràng buộc này. Test integration: bảng thử có FK `(tenant_id, workspace_id)` tới khóa này; dòng
   trỏ `(tenant_B, ws_A)` → lỗi FK; test hỏi `pg_constraint` rằng ràng buộc tồn tại với đúng tên đó.
2. **Gỡ khai báo suông.** Xóa `TenantStatus`, `Tenant`, `Workspace` khỏi
   `packages/python/dw_platform/src/dw_platform/domain/entities.py` cùng test của chúng trong
   `packages/python/dw_platform/tests/unit/test_entities.py`; giữ `Plan` (đọc ở `application/entitlement.py`). Test quét mọi `StrEnum` của `dw_platform` có tên chứa `Tenant` hay mang giá trị chỉ trạng thái tenant có
   (`offboarding`, `offboarded`), và so với tập của `ck_tenants_status` mới nhất theo chuỗi `down_revision` của
   migration (không theo mtime), và chỉ trong SQL mà `upgrade()` của migration chạy (một `op` ghi lại lệnh; `downgrade()`
   không bao giờ được đọc), nên `setup` của tenant-rbac/02 tự vào tập; trạng thái thành viên của ticket 02
   (`suspended`) không bị bắt vì không mang tên hay giá trị riêng của tenant.
3. **Đo trước khi đổi realm.** Realm đủ giá trị bước 4 (xoay refresh token bật) trên một Keycloak tạm, web và API
   thật: hai tab đăng nhập một lần, mỗi tab mỗi phút sang trang khác qua menu (gọi API như người bấm), 20 phút;
   đếm mọi lần điều hướng tới endpoint auth của Keycloak sau đăng nhập (kể cả im lặng), mọi phản hồi token khác
   200, mọi 401 của API; ghi số đo vào Comments. Đo hỏng thì dừng và báo, không đổi realm.
4. **Realm** (`infra/keycloak/dw-realm.json`): `accessTokenLifespan` 300, `ssoSessionIdleTimeout` 1800,
   `ssoSessionMaxLifespan` 36000; `revokeRefreshToken` true, `refreshTokenMaxReuse` 0; `bruteForceProtected` true,
   `failureFactor` 10, `waitIncrementSeconds` 60, `maxFailureWaitSeconds` 900; mặc định của Keycloak ghi rõ:
   `permanentLockout` false, `maxDeltaTimeSeconds` 43200 ("liên tiếp" đếm trong 12 giờ),
   `quickLoginCheckMilliSeconds` 1000, `minimumQuickLoginWaitSeconds` 60. `--import-realm` chỉ ghi vào DB Keycloak rỗng
   (ADR-0009 (Accepted): realm đã có sửa tay), nên `scripts/keycloak_realm_settings.py` đọc đúng các khóa này từ tệp
   realm và ghi chúng vào realm đang chạy (`--check` chỉ báo lệch, thoát 1); uat, production chạy nó một lần khi triển khai ticket này, trên máy chủ, với `DW_KEYCLOAK_ADMIN_URL` là cổng loopback compose mở
   (hostname công khai không phục vụ `/admin`, ADR-0009).
5. **Test cấu hình** `packages/python/dw_platform/tests/unit/test_keycloak_realm.py` đọc tệp realm và khẳng định từng giá
   trị ở bước 4, khẳng định không client nào trong tệp bật `directAccessGrantsEnabled` (direct grant bỏ qua luồng
   "dw browser" và OTP bắt buộc của nhân viên hỗ trợ, ADR-0024), và khẳng định script bước 4 ghi đúng tập khóa đó.
   **Probe sống** `packages/python/dw_platform/tests/integration/test_keycloak_realm_live.py`: tạo client công khai có
   direct grant và người dùng thử qua admin API, xóa cả hai sau; token mới có `exp - iat` = 300; dùng lại refresh
   token → 400 `invalid_grant`; 9 lần sai rồi đúng → vào được, 10 lần sai (cách nhau quá 1 giây) rồi đúng → 400. Chạy
   trong job integration của CI, nơi Keycloak của compose đã bật; vắng Keycloak thì bỏ qua ở máy dev, hỏng ở CI.
6. **Thuật ngữ** (DO-04): bỏ "(phòng ban)" khỏi tiêu đề phụ của `apps/web/app/admin/workspaces/page.tsx` và khỏi `hint` của
   mục `/admin/workspaces` trong `apps/web/lib/nav/registry.ts`, giữ "workspace" như glossary; một test web khẳng định
   trang và mục điều hướng không chứa chuỗi "phòng ban".

## Tiêu chí chấp nhận

- [ ] R1.1 (OP1): FK thử trỏ `(tenant_B, ws_A)` → lỗi FK, không dòng nào ghi; bỏ `uq_workspaces_tenant_id_id` trong migration thử → test `pg_constraint` đỏ.
- [ ] R2.1: grep không còn `TenantStatus` trong `packages/python/dw_platform/src`; test quét `StrEnum` đỏ khi thêm lại `class TenantStatus(StrEnum)` có `suspended`; một `StrEnum` trạng thái thành viên có `suspended` không làm nó đỏ.
- [ ] R3.1: test cấu hình đọc 300, 1800, 36000; probe lấy token mới từ realm → `exp - iat` bằng 300; đặt lại 28800 → test cấu hình đỏ; realm đang chạy còn 28800 → probe đỏ, `scripts/keycloak_realm_settings.py` → probe xanh.
- [ ] R3.2 (OP2): probe dùng lại refresh token → 400; đặt `refreshTokenMaxReuse` 1 → test cấu hình đỏ.
- [ ] R3.3 (OP3): probe 9 lần sai rồi đúng → vào được; 10 lần sai liên tiếp → lần đúng kế tiếp bị từ chối; đặt `bruteForceProtected` false → test cấu hình đỏ.
- [ ] F1: thêm `directAccessGrantsEnabled: true` cho một client trong `dw-realm.json` → test cấu hình đỏ.
- [ ] R3.4: số đo bước 3 ghi ở Comments: 20 phút, hai tab, 0 lần điều hướng tới endpoint auth của Keycloak (kể cả im lặng), 0 phản hồi token khác 200, 0 lần 401 của API; một con số khác 0 là đo hỏng.
- [ ] R9.1: test web của trang `/admin/workspaces` và của `NAV_ITEMS` không tìm thấy "phòng ban"; thêm lại chú thích thì test đỏ.
- [ ] Xong: ruff, format, mypy, `make test-unit`, `make test-contract`, `make test-architecture` và integration của
      `dw_platform` (probe sống chạy trên một Keycloak có realm này) xanh (`.claude/rules/wave-close.md`).

## Nguồn

- `db/migrations/sql/0001_platform_baseline.sql:478-485`; spec: R1.1.
- `db/migrations/sql/0001_platform_baseline.sql:612`; spec: R1.1.
- `packages/python/dw_kernel/src/dw_kernel/naming.py:25-27`; spec: R1.1.
- `packages/python/dw_platform/src/dw_platform/domain/entities.py:25-55`; spec: R2.1.
- `packages/python/dw_platform/src/dw_platform/application/entitlement.py:11`; spec: R2.1.
- `db/migrations/versions/5d9d89ffc716_tenant_offboarding_requests.py:79-80`; spec: R2.1.
- `infra/keycloak/dw-realm.json:12-14`; spec: R3.1.
- `apps/web/lib/auth/auth-context.tsx:199-211`; spec: R3.4.
- `apps/web/app/admin/workspaces/page.tsx:65`, `apps/web/lib/nav/registry.ts:80`; spec: R9.1.
- ADR-0103 (Accepted) mục 9; ADR-0102 (Accepted) mục 1; brief B2 mục 1.1, 1.3.

## Comments

- 2026-10-29 (agent, tạm theo ủy quyền): theo gate (5 HIGH, không CRITICAL): đo bước 3 trên realm đủ bước 4 và đếm cả lần chuyển im lặng (B1); script đồng bộ cho realm đã import (B2); probe là test integration tự tạo client và người dùng thử, xóa sau (B3, B4); test quét enum nhận diện theo tên `Tenant` hay giá trị riêng của tenant, tập đọc theo chuỗi `down_revision` (B5, B6); test cấu hình cấm client direct grant (F1); bốn mặc định chống dò ghi rõ (B8). Để lại MEDIUM/LOW: B7 ("rảnh" đo theo token: `onTokenExpired` chỉ hẹn giờ từ lần làm mới đầu, xem dòng đo), F2 (khóa do dò mật khẩu không ai mở và không audit; ai cũng khóa được chủ sở hữu biết email, tối đa 15 phút mỗi 10 lần), F3 (`offline_access` của `dw-web` sống quá 10 giờ), F5 (FK ghép MATCH SIMPLE bỏ qua `workspace_id` NULL: bảng Studio nào dùng khóa này khai NOT NULL hay MATCH FULL), X1-X5 (tiêu chí yếu, đã sửa ở trên trừ X5: số đo R3.4 là đo tay, không test nào chạy lại).
- 2026-10-29 (agent): lượt xác nhận của gate: không CRITICAL mới; B3, B4, B5, F1 đóng; B1, B2, B6 đóng một phần và đã sửa: R3.4 có ngưỡng 0 cho cả ba số đếm, script chạy qua `DW_KEYCLOAK_ADMIN_URL` loopback, tập trạng thái đọc từ SQL của `upgrade()`. Gate ĐẠT dựa trên lượt gate và lượt xác nhận.
- 2026-10-30 (agent): dở dang, commit để không mất việc. Xong: bước 1, 2, 4, 5, 6; gate và xác nhận; đột biến 8/8 (7 qua `scripts/mutate.py` và tại chỗ, R9.1 bằng tay); ruff, format, mypy, test-unit, test-contract, kiến trúc, integration `test_workspace_composite_key`, `test_privileges`, `test_rls_coverage` xanh; probe sống 3/3 xanh trên Keycloak 26.7.2 tạm. Đo bước 3 (realm đủ bước 4, web và API thật, hai tab, mỗi phút một lần bấm menu): 610 giây đầu, mỗi tab 1 lần làm mới token 200, 25 lời gọi API 200, 0 lần tới endpoint auth, 0 lần 401; phiên dừng trước 20 phút, nên R3.4 CHƯA đạt. Đo thêm: hai tab cùng phiên không làm hỏng refresh token của nhau; dùng lại token cũ → 400 `Stale token` và client session bị gỡ (tab kia cũng phải đăng nhập lại). Phát hiện: `auth-context.tsx` gán `onTokenExpired` sau `kc.init()`, keycloak-js chỉ hẹn giờ khi đặt token, nên token đầu không tự làm mới; web làm mới khi gọi API (`session.ts` `updateToken(30)`), và từ lần làm mới đầu thì hẹn giờ mỗi 5 phút (B7). Còn: đo đủ 20 phút; realm tạm về 28800 → probe đỏ, script → xanh; đóng ticket.
