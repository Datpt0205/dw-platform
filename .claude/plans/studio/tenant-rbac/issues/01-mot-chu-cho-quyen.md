# 01 — Một chủ cho quyền: bootstrap qua effective_scopes và danh mục platform.permissions

Status: needs-triage
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R2.1, RB1, RB2, RB3, RB4

## Mục tiêu

Hai sửa P0 làm được ngay, không chờ quyết định nào: bootstrap hết lệch với AccessContext (R2.1), và mọi khóa quyền có
đúng một dòng trong danh mục quyền do migration ghi, có nhãn, loại và mức rủi ro (R1). Gộp từ brief B3 ticket 01, 02 và
phần bootstrap của foundations-hardening 05 (brief B11).

## Việc cần làm

1. **Bootstrap.** `SqlIdentityBootstrap._read_memberships` bỏ phần tự tính quyền từ `role_keys`
   (`identity_provisioning.py:252-269`) và gọi `effective_scopes(session, role_keys, permission_set_keys)`
   (`membership_lookup.py:33-55`) cho từng membership trong cùng phiên. Sửa docstring sai của route bootstrap
   (`apps/api/src/dw_api/routes/v1/auth.py:1-6` nói người mới thành member; mặc định là từ chối). Không đổi hợp đồng API,
   không đổi web (ticket 02 chuyển web sang `GET /api/v1/me`). Ticket này sở hữu cách bootstrap tính quyền;
   org-and-principals/02 chờ ticket này (OPS-b cạnh 10) và chỉ thêm điều kiện thành viên `active` vào cùng
   `_read_memberships`.
2. **Danh mục.** Migration (id hex của `alembic revision`, tên tệp mang số thứ tự): `platform.permissions`:
    - `key text PRIMARY KEY CHECK (key ~ '^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$')`;
    - `area text NOT NULL`, `label_vi text NOT NULL CHECK (btrim(label_vi) <> '')`, `description_vi text`;
    - `scope_kind text NOT NULL CHECK (scope_kind IN ('tenant','workspace','record'))`;
    - `risk text NOT NULL CHECK (risk IN ('standard','elevated','critical'))`;
    - `status text NOT NULL CHECK (status IN ('active','unassigned','retired'))`, `status_reason text`,
      `ck_permissions_status_reason CHECK (status = 'active' OR btrim(coalesce(status_reason, '')) <> '')`;
    - `owner_package text NOT NULL`, `created_at timestamptz NOT NULL DEFAULT now()`.
      Bảng toàn cục, không `tenant_id`, không RLS. REVOKE INSERT, UPDATE, DELETE, TRUNCATE khỏi `dw_app`, `dw_provisioner`,
      `dw_agent_ro` (mỗi câu trong khối DO kiểm vai tồn tại, như `648e2f7c3edb`); GRANT SELECT cho ba vai đó.
3. **Seed.** Mọi khóa đang dùng, kể cả bất thường, mỗi khóa có `scope_kind` và `risk` ghi trong migration:
    - bất thường mang trạng thái và lý do: `runs.cancel`, `knowledge.publish_global` (`unassigned`), `approvals.pending`,
      `feedback.inbox`, `platform.usage.read`, `crm.records.all.read` (`retired` hoặc `unassigned`, ghi lý do);
      không đổi hành vi route nào, việc sửa từng bất thường ghi ở Comments thành đề xuất;
    - `platform.usage.read` là khóa đọc sử dụng duy nhất: ghi `unassigned` với lý do "usage-and-limits dùng lại và đưa
      về `active` trong migration của nó", không có khóa `usage.read` thứ hai (Quyết định 23/10/2026 của spec);
    - `risk = 'critical'` cho `platform.admin` và `platform.sod_waivers.write`, `elevated` cho các khóa `platform.*`
      khác, `standard` cho phần còn lại (spec, Quyết định 23/10/2026);
    - `scope_kind = 'tenant'` cho khóa route đọc toàn tenant (`platform.*`, `support.*`), `workspace` cho khóa còn lại;
      bảng phân loại nằm trong docstring của migration.
4. **Route.** `GET /api/v1/admin/permissions` (`platform.roles.read`, hằng `ROLES_READ` đã có): mảng `key`, `area`,
   `label_vi`, `scope_kind`, `risk`, `status`, sắp theo `area` rồi `key`; `make generate-contracts` và client trong
   `packages/typescript/api-client`.
5. **Test phủ** `packages/python/dw_platform/tests/integration/test_permission_catalogue.py`:
   (a) mọi khóa trong `platform.roles` và `platform.permission_sets` có dòng `active`;
   (b) mọi khóa mà code kiểm (`action="..."` trong route của `apps/api/src`, hằng `*_SCOPE`, `required_scopes` trong
   `configs/tools`, `scope` và `anyScope` trong `apps/web/lib/nav/registry.ts`) có trong danh mục;
   (c) mọi khóa `active` có ít nhất một chỗ kiểm, trừ danh sách ngoại lệ trong test, mỗi mục một lý do.
   Từ nay mỗi cụm Studio đăng ký khóa `studio.<area>.<verb>` của mình trong migration của chính nó, và test này giữ chúng.
6. **Người vận hành.** Thêm `studio.`, `obj.`, `fld.` vào `FORBIDDEN_SCOPE_PREFIXES` (`support_access.py:63-72`).
7. `test_privileges.py` khẳng định quyền DB của `platform.permissions` cho từng vai ứng dụng.

## Tiêu chí chấp nhận

- [ ] R2.1 (RB4): integration: thành viên có vai `member` và bộ quyền `approver_boost` → bootstrap trả `approvals.decide`, bằng đúng tập `GET /api/v1/me` trả ở cùng workspace; quay lại tính theo vai → test đỏ; người không có bộ quyền: kết quả không đổi.
- [ ] R1.3 (RB1): `dw_app`, `dw_provisioner`, `dw_agent_ro` INSERT, UPDATE, DELETE trên `platform.permissions` → `permission denied`; trả lại quyền ghi trong migration thử → test đỏ.
- [ ] R1.1 (RB2): thêm một route kiểm `x.y` không có dòng danh mục → (b) đỏ; xóa một dòng danh mục đang được kiểm → (b) đỏ.
- [ ] R1.2 (RB2): thêm khóa `active` không ai kiểm → (c) đỏ; khóa đó ở danh sách ngoại lệ có lý do → xanh.
- [ ] R1.4: `GET /api/v1/admin/permissions` trả đủ sáu trường cho mọi dòng; người không có `platform.roles.read` → 403.
- [ ] R1.5 (RB3): đăng ký `obj.lead.read` hay `studio.agents.publish` cho truy cập người vận hành → bị từ chối; gỡ tiền tố khỏi `FORBIDDEN_SCOPE_PREFIXES` → test đỏ.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:252-269`; spec: R2.1.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:33-55`; spec: R2.1.
- `apps/api/src/dw_api/routes/v1/auth.py:1-6`; spec: R2.1.
- `apps/api/src/dw_api/routes/v1/runs.py:127`; spec: R1.1, R1.2.
- `db/migrations/versions/648e2f7c3edb_roles_and_permission_sets_read_only_to_.py:51-57`; spec: R1.3.
- `packages/python/dw_platform/src/dw_platform/application/admin_console.py:32`; spec: R1.4.
- `packages/python/dw_platform/src/dw_platform/application/support_access.py:63-72`; spec: R1.5.
- ADR-0104 (Accepted) mục 1; brief B3 mục 1.10 và ticket 02.

## Comments
