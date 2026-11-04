# 06 — Khóa `memberships.role_keys` và `permission_set_keys` sau FOG-49

Status: ready-for-agent
Blocked by: 03, 05
Area: studio
Yêu cầu: R8.6, G2, RB27

## Mục tiêu

Hai cột cũ của membership hết đường ghi (R8.6): mọi lần ghi `permission_set_keys` khác rỗng hay `role_keys` khác rỗng
và khác `["platform_admin"]` bị PostgreSQL từ chối, từ mọi vai cơ sở dữ liệu. Ticket 03 đã chuyển mọi người ghi và
người đọc trong repo sang gán vai trò và để trigger hai người của nó xét lần ghi mà trigger chép làm; ticket 05 (FOG-49,
Đạt 24/10/2026) là lời xác nhận của người giữ dw-proterial rằng dw-proterial thôi ghi hai cột. Tách từ bước 9 của
ticket 03 ngày 4/11/2026; đường vượt `platform_admin` giữ nguyên tới dòng W2 (G2).

## Việc cần làm

1. **Một revision** (id hex của `alembic revision`), theo đúng thứ tự:
    - bỏ trigger `trg_memberships_legacy_role_columns` và hàm `platform.sync_legacy_role_columns()` của ticket 02
      (`b5677d345bc1_tenant_roles.py:663-720`, `:1158-1160`);
    - xóa trắng hai cột: `permission_set_keys` thành `'[]'::jsonb`, `role_keys` thành `'["platform_admin"]'::jsonb` khi nó
      chứa `platform_admin`, `'[]'::jsonb` khi không, chỉ trên dòng có giá trị khác. Xóa khi trigger chép còn thì nó gỡ
      mọi gán vai trò đến từ hai cột (Comments của ticket 02, HIGH 12), nên bỏ trigger đứng trước;
    - thêm `ck_memberships_legacy_role_columns`:
      `CHECK (permission_set_keys = '[]'::jsonb AND role_keys IN ('[]'::jsonb, '["platform_admin"]'::jsonb))`, tên theo
      `dw_kernel.naming.NAMING_CONVENTION` cho ra đúng tên đó. CHECK áp cho mọi vai, kể cả `dw_migrator`;
      `guard_legacy_role_columns` của ticket 03 vẫn giữ ai được thêm `platform_admin`.
    - Downgrade: bỏ CHECK, dựng lại hàm và trigger như `b5677d345bc1`; giá trị đã xóa trắng không dựng lại, vì quyền nằm ở
      gán vai trò.
2. **Người ghi còn lại.** Sau ticket 03, chỉ `scripts/grant_platform_admin.py` (dưới `dw_migrator`, `["platform_admin"]`)
   và `seed_env` (cùng giá trị) còn ghi `role_keys`. Hàm thử `dw_platform.testing.rbac` gỡ khóa khỏi hai cột trước khi
   xóa vai mẫu (`packages/python/dw_platform/src/dw_platform/testing/rbac.py:205-216`) bỏ, cùng chỗ gọi nó. Test của
   RB48 (ticket 03: lần ghi cột cũ đi qua trigger chép tới trigger hai người) đổi theo: ca thêm khóa nay mong
   `ck_memberships_legacy_role_columns`, ca `dw_migrator` thêm khóa thành bị từ chối, ca bỏ khóa thành không còn gán
   nào để gỡ; RB48 thôi áp từ ticket này vì cột không còn tới gán vai trò, RB27 thay nó. Test RB49, RB50 giữ nguyên tên
   ràng buộc, vì `guard_legacy_role_columns` là trigger BEFORE, bắn trước CHECK; ca `scripts/grant_platform_admin.py`
   của RB49 đổi thành: `role_keys` `[]` cộng gán `member` → `["platform_admin"]`, gán `member` còn nguyên, vì CHECK
   không cho dựng `["member"]` nữa. Không bảng,
   route, quyền vai hay bước offboarding mới, nên `test_rls_coverage.py`, `test_privileges.py`,
   `test_offboarding_coverage.py` không đổi.
3. **Không đổi**: `platform_admin` trong `role_keys` vẫn là đường vượt của G2, `membership_lookup.py:125`, `:171-172`
   vẫn đọc nó; bỏ hẳn hai cột là một revision sau (ADR-0104 (Accepted), Consequences), ngoài ticket này.

## Tiêu chí chấp nhận

- [ ] R8.6 (RB27): sau migration, dưới `dw_app` (có `app.user_id`) và `dw_migrator`: INSERT membership hay UPDATE
      với `permission_set_keys` `["approver_boost"]` hay `role_keys` `["member"]` → 23514
      `ck_memberships_legacy_role_columns`, không dòng đổi; dưới `dw_migrator`, `role_keys` `["platform_admin", "member"]`
      → 23514 cùng tên, `["platform_admin"]` → nhận; gỡ CHECK → các ca đó nhận, test đỏ. Dưới `dw_provisioner` mọi lần
      thêm khóa, và dưới `dw_app` mọi giá trị có `platform_admin`, vẫn bị `guard_legacy_role_columns` (BEFORE, bắn trước
      CHECK) từ chối với `ck_memberships_legacy_role_writer`, nên không tính vào phép gỡ CHECK.
- [ ] R8.6: migration chạy trên một tenant có membership `role_keys` `["member", "approver"]`, `permission_set_keys`
      `["approver_boost"]` (gán vai trò do trigger chép tạo) và một membership `["platform_admin", "member"]` → sau
      migration dòng thứ nhất có hai cột `[]`, dòng thứ hai `role_keys` `["platform_admin"]`; tập dòng
      `platform.role_assignments` của tenant và `grants` của `GET /api/v1/me` từng người không đổi; đặt câu xóa trắng
      trước câu bỏ trigger → gán vai trò mất, test đỏ.
- [ ] G2: membership còn `["platform_admin"]` sau migration → AccessContext dựng từ `membership_lookup.py` có
      `platform_admin` trong `roles` và `GET /api/v1/me` trả `platform_bypass` đúng; xóa trắng cả `platform_admin` →
      test đỏ; `test_platform_admin_bypasses_scopes` xanh.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `db/migrations/versions/b5677d345bc1_tenant_roles.py:663-720`, `db/migrations/versions/b5677d345bc1_tenant_roles.py:1158-1160`; spec: R8.6.
- `db/migrations/sql/0001_platform_baseline.sql:267-272`; spec: R8.6.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:171-172`; spec: G2.
- `packages/python/dw_platform/src/dw_platform/testing/rbac.py:205-216`; spec: R8.6.
- ADR-0104 (Accepted), Consequences và Open 5 (FOG-49); Comments của ticket 02 (HIGH 12) và ticket 03 (2026-11-04).

## Comments

- 2026-11-04 (agent, theo ủy quyền 31/10/2026): tách từ bước 9 của ticket 03 (Quyết định 4/11/2026 của spec): phần
  duy nhất của ticket 03 làm lần ghi hai cột cũ thất bại mà không có lý do quyền (bỏ trigger chép, xóa trắng, CHECK).
  Không có người đọc hai cột nào quyết quyền ngoài `platform_admin`, mà CHECK vẫn cho, nên tách không mở đường vòng.
  Nếu sai thì: gộp lại vào bước 9 của ticket 03, và ticket 03 chờ ticket 05 như trước.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness cùng lượt với ticket 03 (builder check,
  boundary walk, hai lượt xác nhận): tiêu chí RB27 nêu tên ràng buộc theo thứ tự trigger BEFORE trước CHECK, test RB48
  đổi ở đây, ca `grant_platform_admin.py` của RB49 dựng lại được sau xóa trắng. Dựng sau ticket 03 và khi ticket 05
  `resolved`; không đường phụ thuộc với ticket 04, chung đầu chuỗi Alembic (ticket xong sau trỏ lại `down_revision`).
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
