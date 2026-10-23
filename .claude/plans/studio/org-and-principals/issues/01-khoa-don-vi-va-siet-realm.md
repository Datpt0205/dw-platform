# 01 — Khóa tổng hợp cho workspace, gỡ enum khai báo suông, siết realm Keycloak

Status: needs-triage
Area: studio
Yêu cầu: R1.1, R2.1, R3.1, R3.2, R3.3, R3.4, OP1, OP2, OP3

## Mục tiêu

Ba sửa P0 làm được ngay: workspace có khóa `(tenant_id, id)` làm đích cho FK kép của mọi bảng Studio (R1), kiểu trạng thái
tenant không ai đọc biến mất (R2), và realm Keycloak cấp token 300 giây, xoay refresh token, chống dò mật khẩu để thu hồi
không còn chờ 8 giờ (R3). Gộp từ brief B2 ticket 01, 02.

## Việc cần làm

1. **Khóa tổng hợp.** Migration (id hex của `alembic revision`): `ALTER TABLE platform.workspaces ADD CONSTRAINT uq_workspaces_tenant_id UNIQUE (tenant_id, id)`
   (tên theo `dw_kernel.naming.NAMING_CONVENTION`). Không đổi dữ liệu. Test integration: bảng thử có FK
   `(tenant_id, workspace_id)` tới khóa này; dòng trỏ `(tenant_B, ws_A)` → lỗi FK; test hỏi `pg_constraint` rằng ràng buộc
   tồn tại.
2. **Gỡ khai báo suông.** Xóa `TenantStatus`, `Tenant`, `Workspace` khỏi
   `packages/python/dw_platform/src/dw_platform/domain/entities.py` cùng test của chúng trong
   `packages/python/dw_platform/tests/unit/test_entities.py`; giữ `Plan` (đọc ở `application/entitlement.py`). Test kiến
   trúc quét mọi `StrEnum` của `dw_platform` mang giá trị trạng thái tenant và so với `ck_tenants_status`.
3. **Đo trước khi đổi realm.** Với token 300 giây trên compose: web làm mới im lặng (`checkLoginIframe: false`,
   `onTokenExpired` gọi `updateToken(30)`) qua 20 phút, hai tab cùng mở, không lần nào về trang đăng nhập; ghi số đo vào
   Comments. Đo hỏng thì dừng và báo, không đổi realm.
4. **Realm** (`infra/keycloak/dw-realm.json`): `accessTokenLifespan` 300, `ssoSessionIdleTimeout` 1800,
   `ssoSessionMaxLifespan` 36000; `revokeRefreshToken` true, `refreshTokenMaxReuse` 0; `bruteForceProtected` true,
   `failureFactor` 10, `waitIncrementSeconds` 60, `maxFailureWaitSeconds` 900.
5. **Test cấu hình** `packages/python/dw_platform/tests/unit/test_keycloak_realm.py` đọc tệp realm và khẳng định từng giá
   trị ở bước 4; probe trong compose smoke: dùng lại refresh token → 400; 10 lần sai mật khẩu liên tiếp → lần đăng nhập
   đúng ngay sau đó bị từ chối.

## Tiêu chí chấp nhận

- [ ] R1.1 (OP1): FK thử trỏ `(tenant_B, ws_A)` → lỗi FK, không dòng nào ghi; bỏ `uq_workspaces_tenant_id` trong migration thử → test `pg_constraint` đỏ.
- [ ] R2.1: grep không còn `TenantStatus`, `SUSPENDED` trong `packages/python/dw_platform/src`; test quét `StrEnum` đỏ khi thêm lại một enum trạng thái tenant có `suspended`.
- [ ] R3.1: test cấu hình đọc 300, 1800, 36000; probe lấy token mới từ realm → `exp - iat` bằng 300; đặt lại 28800 → test cấu hình đỏ.
- [ ] R3.2 (OP2): probe dùng lại refresh token → 400; đặt `refreshTokenMaxReuse` 1 → test cấu hình đỏ.
- [ ] R3.3 (OP3): probe 10 lần sai liên tiếp → lần đúng kế tiếp bị từ chối; đặt `bruteForceProtected` false → test cấu hình đỏ.
- [ ] R3.4: số đo bước 3 ghi ở Comments: 20 phút, hai tab, 0 lần về trang đăng nhập.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `db/migrations/sql/0001_platform_baseline.sql:478-485`; spec: R1.1.
- `db/migrations/sql/0001_platform_baseline.sql:612`; spec: R1.1.
- `packages/python/dw_platform/src/dw_platform/domain/entities.py:25-55`; spec: R2.1.
- `packages/python/dw_platform/src/dw_platform/application/entitlement.py:11`; spec: R2.1.
- `db/migrations/versions/5d9d89ffc716_tenant_offboarding_requests.py:79-80`; spec: R2.1.
- `infra/keycloak/dw-realm.json:12-14`; spec: R3.1.
- `apps/web/lib/auth/auth-context.tsx:199-211`; spec: R3.4.
- ADR-0103 (Proposed) mục 9; ADR-0102 (Proposed) mục 1; brief B2 mục 1.1, 1.3.

## Comments
