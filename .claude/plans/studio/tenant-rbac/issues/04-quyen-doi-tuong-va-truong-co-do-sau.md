# 04 — Quyền theo đối tượng có độ sâu và quyền trường trong vai trò

Status: needs-triage
Blocked by: 02, 03, .claude/plans/studio/custom-objects/issues/02-luoc-do-dinh-nghia-object.md
Area: studio
Yêu cầu: R6.8, R9.1, R9.2, R9.3, R9.4, R9.5, R9.6, R9.7, RB28, RB29, RB30, RB31, RB33

## Mục tiêu

Vai trò của tenant mang quyền trên đối tượng do công ty định nghĩa, `obj.<api_name>.<action>` với một mức truy cập mỗi
quyền, và quyền trường `fld.<object>.<field>.read|edit` cộng dồn qua mọi vai trò (R9), đủ cho vai Marketing và vai Sales
của lát Marketing trên `lead`. Quyền hiệu lực trả các khóa này để record-access và field-security đọc. Gộp từ brief B3
ticket 09, 14; ngữ nghĩa quyền trường thuộc field-security (ADR-0106 (Accepted)). DO-09.1 đã quyết theo khuyến nghị (a)
(Đạt, 23/10/2026); DO-32.1 thêm luật `bind` không phủ vai trò mang `fld.*` trên trường nhạy cảm (R6.8).

## Việc cần làm

1. **Hành động.** `platform.object_actions`:
   `action text PRIMARY KEY CHECK (action IN ('read','create','update','delete','assign','share','export'))`,
   `label_vi text NOT NULL`, `enforced boolean NOT NULL`, `sort_order integer NOT NULL`; seed `read`, `create`, `update`,
   `delete`, `assign` với `enforced = true`, `share` và `export` với `enforced = false` (record-access bật `share`,
   custom-objects bật `export`, mỗi bên trong migration giao đường đọc của mình). `dw_app`, `dw_provisioner`,
   `dw_agent_ro` chỉ SELECT.
2. **Quyền đối tượng.** `platform.tenant_role_object_privileges`: `tenant_id uuid NOT NULL`, `role_id uuid NOT NULL`,
   `object_id uuid NOT NULL`, `action text NOT NULL` FK `platform.object_actions` `ON DELETE RESTRICT`,
   `depth text NOT NULL CHECK (depth IN ('own','workspace','tenant'))`, `PRIMARY KEY (role_id, object_id, action)`; FK
   `(tenant_id, role_id)` tới `platform.tenant_roles` và FK `(tenant_id, object_id)` tới `studio.object_defs (tenant_id, id)`,
   cả hai `ON DELETE CASCADE`; index `(tenant_id, role_id)`, `(tenant_id, object_id)`; trigger
   `ck_role_object_privileges_action_enforced` (23514 khi `enforced = false`).
3. **Quyền trường.** `studio.field_permissions` theo ADR-0106 (Accepted) mục 3: `tenant_id`, `role_id`, `field_id`,
   `access text NOT NULL` với `ck_field_permissions_access CHECK (access IN ('read','edit'))`, `granted_by uuid NULL` FK
   `platform.users` `ON DELETE SET NULL`, `granted_at timestamptz NOT NULL DEFAULT now()`,
   `PRIMARY KEY (tenant_id, role_id, field_id)`; FK tới vai trò và tới `studio.field_defs (tenant_id, id)`
   `ON DELETE CASCADE`; index phía FK.
4. RLS ENABLE và FORCE, policy tenant cho hai bảng quyền; `dw_app` SELECT, INSERT, UPDATE, DELETE; khẳng định trong
   `test_rls_coverage.py`, `test_privileges.py`; offboarding xuất và xóa. Hai bảng không có `workspace_id`: mỗi bảng một
   dòng trong danh sách bảng toàn tenant của `test_rls_coverage.py` với lý do "quyền của vai trò thuộc cả công ty; neo
   workspace nằm ở gán vai trò" (DO-01).
5. **Quyền hiệu lực.** `platform.effective_grants` trả thêm `obj.<api_name>.<action>` với mức và neo của gán vai trò, và
   `fld.<object api_name>.<field api_name>.read|edit` mang mức `tenant` (quyền trường không tự thu hẹp; tầm với do quyền
   đối tượng quyết định, ADR-0106 (Accepted) mục 3); quyền tính động của `tenant_owner` gồm mọi đối tượng sống và mọi hành
   động `enforced` ở mức `tenant`, và `fld.<object>.<field>.read`, `.edit` của mọi trường sống của các đối tượng đó, sinh
   từ `studio.field_defs`, không lưu dòng nào trong `studio.field_permissions` (R9.7, N1; ADR-0104 (Accepted) mục 2).
   `platform.workspace_reach` trả rỗng cho mức `own`. `platform.scopes_in` có khóa `obj.*` ở mọi mức.
6. **Danh mục sinh.** `GET /api/v1/admin/permissions` liệt kê khóa sinh theo đối tượng sống và hành động `enforced`, nhãn
   "tên đối tượng — tên hành động", loại `record`; không lưu bản sao trong `platform.permissions`.
7. **Chống leo thang quyền** trên hai bảng mới: trigger BEFORE INSERT, UPDATE gọi `platform.rbac_refusals` của ticket 03 với
   mức của quyền đối tượng; quyền trường chỉ vào vai trò khi người làm giữ đúng khóa `fld.*` đó, nên chủ sở hữu công ty
   (giữ mọi `fld.*` qua quyền tính động) là người cấp được `fld.*` đầu tiên, và người xác nhận đề xuất cũng phải giữ khóa
   đó vì thay đổi áp trong giao dịch của người xác nhận. `platform.rbac_refusals`
   coi vai trò mang `fld.*` trên một trường có `pd_category = 'sensitive'` là có quyền trọng yếu, nên
   `platform.roles.bind` không gán hay gỡ được vai trò đó khi người làm không giữ khóa `fld.*` ấy (R6.8, DO-32.1). API ghi
   hai loại quyền qua `PUT /api/v1/admin/roles/{role_id}/permissions` của ticket 03
   (`object_privileges: [{object_id, action, depth}]`, `field_permissions: [{field_id, access}]`): thêm quyền hay nâng
   mức đi qua đề xuất và xác nhận của hai người, bỏ quyền hay hạ mức là thay đổi chỉ siết, một người cộng audit (R7.6).
8. Trigger `platform.bump_access_version()` (ticket 02) trên hai bảng mới; `platform.sod_violation` đọc khóa `obj.*` qua
   `platform.effective_grants` mà không đổi gì.

## Tiêu chí chấp nhận

- [ ] R9.1: tạo đối tượng `lead` → `GET /api/v1/admin/permissions` có năm khóa `obj.lead.*` loại `record`; không có `obj.lead.share`, `obj.lead.export`.
- [ ] R9.2 (RB28): cấp `share` trên `lead` khi `share` chưa `enforced` → 23514 `ck_role_object_privileges_action_enforced`; gỡ trigger → đỏ.
- [ ] R9.3 (RB31): xóa định nghĩa `lead` hay một trường của nó → không còn dòng quyền nào trỏ tới chúng; `/me` kế tiếp không có `obj.lead.*`; `object_id` của tenant khác → FK kép từ chối.
- [ ] R9.4 (RB29): vai trò có `obj.lead.read` mức `own` → `platform.workspace_reach` rỗng cho người giữ; đổi hàm coi `own` như `workspace` → đỏ.
- [ ] R9.5 (RB30): người giữ `obj.lead.read` mức `workspace` đặt mức `tenant` → 23514; thêm `fld.lead.phone.edit` mình không giữ → 23514; `tenant_owner` đề xuất thêm `fld.lead.phone.read` vào vai Marketing → 202, quyền chưa đổi; một `tenant_owner` khác xác nhận → áp, `/me` của người giữ vai Marketing có `fld.lead.phone.read`; người xác nhận không giữ khóa đó → 403 `rbac_escalation`; gỡ trigger → test SQL thô đỏ.
- [ ] R9.6: vai trò A cho `fld.lead.phone.read`, vai trò B cho `fld.lead.phone.edit`, cùng một người → `/me` trả cả hai khóa.
- [ ] R9.7: tạo trường `phone` trên `lead` → `/me` của người giữ `tenant_owner` có `fld.lead.phone.read` và `fld.lead.phone.edit` mức `tenant`, `studio.field_permissions` không có dòng nào cho trường đó; xóa trường → hai khóa vắng ở `/me` kế tiếp; bỏ nhánh `fld.*` khỏi quyền tính động của `tenant_owner` → test đỏ.
- [ ] R6.8 (RB33): người chỉ giữ `platform.roles.bind` đề xuất gán vai trò có `fld.lead.cccd.read` trên trường `sensitive` mà mình không giữ → 403 `rbac_escalation`, không dòng đề xuất; cùng thao tác bằng SQL thô dưới `dw_app` → 23514; vai trò chỉ có `fld.*` trên trường `basic` → nhận; bỏ nhánh `sensitive` khỏi `platform.rbac_refusals` → test đỏ.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `db/migrations/sql/0001_platform_baseline.sql:262-273`; spec: R9.
- `packages/python/dw_platform/src/dw_platform/application/membership_admin.py:49-53`; spec: R9.5.
- `docs/adr/0106-field-access-follows-personal-data-category.md:57-61`; spec: R9.3, R9.6.
- `docs/adr/0107-custom-objects-over-fixed-tables-one-record-service.md:40-45`; spec: R9.1.
- ADR-0104 (Accepted) mục 4; ADR-0106 (Accepted) mục 3; ADR-0107 (Accepted) mục 1; brief B3 ticket 09, 14.

## Comments

- 2026-10-23 (agent): Bước 7 mở rộng `platform.rbac_refusals` và route của ticket 03 trong khi `Blocked by:` chép đúng gói (02 và custom-objects/02); đề xuất thêm 03 vào `Blocked by:`.
- 2026-10-23 (agent): DO-09.1 và DO-32.1 đã có lời đáp (Đạt, 23/10/2026); Status về needs-triage; thêm R6.8 (RB33) và luật siết một người của R7.6 vào bước 7.
- 2026-10-24 (agent): N1 (Đạt, 24/10/2026): quyền tính động của `tenant_owner` gồm mọi `fld.*` trên mọi trường sống, nên `fld.*` đầu tiên trên một trường `secured` cấp được; đưa `fld.*` vào vai khác vẫn đi đề xuất hai người. Thêm R9.7 vào bước 5 và tiêu chí; RB30 thêm đường của `tenant_owner`.
