# 04 — Quyền theo đối tượng có độ sâu và quyền trường trong vai trò

Status: ready-for-agent
Blocked by: 02, 03, .claude/plans/studio/custom-objects/issues/02-luoc-do-dinh-nghia-object.md
Area: studio
Yêu cầu: R6.8, R9.1, R9.2, R9.3, R9.4, R9.5, R9.6, R9.7, R9.8, R9.9, R9.10, R9.11, R9.12, R9.13, R9.14, R9.15, RB28, RB29, RB30, RB31, RB33, RB35, RB44, RB45, RB46, RB47

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
   cả hai `ON DELETE CASCADE`; index `(tenant_id, role_id)`, `(tenant_id, object_id)` và `(action)` cho FK tới
   `platform.object_actions`; trigger `ck_role_object_privileges_action_enforced` (23514 khi `enforced = false`).
3. **Quyền trường.** `studio.field_permissions` theo ADR-0106 (Accepted) mục 3: `tenant_id`, `role_id`, `field_id`,
   `access text NOT NULL` với `ck_field_permissions_access CHECK (access IN ('read','edit'))`, `granted_by uuid NULL` FK
   `platform.users` `ON DELETE SET NULL`, `granted_at timestamptz NOT NULL DEFAULT now()`,
   `PRIMARY KEY (tenant_id, role_id, field_id)`; FK `(tenant_id, role_id)` tới `platform.tenant_roles (tenant_id, id)`
   và FK `(tenant_id, field_id)` tới `studio.field_defs (tenant_id, id)`, cả hai `ON DELETE CASCADE`; index
   `(tenant_id, field_id)` (khóa chính đã dẫn bằng `(tenant_id, role_id)`) và `granted_by`.
4. RLS ENABLE và FORCE, policy tenant cho hai bảng quyền; quyền vai như `platform.tenant_role_permissions`
   (`db/migrations/versions/b5677d345bc1_tenant_roles.py:1247`): `dw_app` SELECT, INSERT, UPDATE, DELETE, `dw_agent_ro`
   không gì; `dw_provisioner` SELECT trên hai bảng và trên `studio.object_defs`, `studio.field_defs`, vì
   `platform.effective_grants` (SECURITY INVOKER) đọc chúng khi chạy dưới vai đó, có một test gọi hàm dưới
   `dw_provisioner`; khẳng định trong
   `test_rls_coverage.py`, `test_privileges.py`; offboarding xuất và xóa. Hai bảng không có `workspace_id`: mỗi bảng một
   dòng trong danh sách bảng toàn tenant của `test_rls_coverage.py` với lý do "quyền của vai trò thuộc cả công ty; neo
   workspace nằm ở gán vai trò" (DO-01).
5. **Quyền hiệu lực.** `platform.effective_grants` trả thêm `obj.<api_name>.<action>` với mức và neo của gán vai trò, và
   `fld.<object api_name>.<field api_name>.read|edit` mang mức `tenant` (quyền trường không tự thu hẹp; tầm với do quyền
   đối tượng quyết định, ADR-0106 (Accepted) mục 3); quyền tính động của `tenant_owner` gồm mọi đối tượng sống và mọi hành
   động `enforced` ở mức `tenant`, và `fld.<object>.<field>.read`, `.edit` của mọi trường sống của các đối tượng đó, sinh
   từ `studio.field_defs`, không lưu dòng nào trong `studio.field_permissions` (R9.7, N1; ADR-0104 (Accepted) mục 2).
   Một dòng `access = 'edit'` trả cả `fld.<object>.<field>.read` và `.edit` (R9.15), nên field-security không tự suy
   "sửa thì đọc" và người giữ `.edit` cấp được `.read`. "Sống" là có dòng `studio.object_defs` hay `studio.field_defs`,
   tức đã qua lần phát hành đầu (`MetadataService.apply` của custom-objects/02); bản Nháp chưa sinh khóa nào, và
   `api_name` của đối tượng đã phát hành không đổi (custom-objects:R2.4).
   `platform.workspace_reach` trả rỗng cho mức `own`. `platform.scopes_in` có khóa `obj.*` ở mọi mức.
6. **Danh mục sinh.** `GET /api/v1/admin/permissions` liệt kê khóa sinh theo đối tượng sống và hành động `enforced`, nhãn
   "tên đối tượng — tên hành động", loại `record`; không lưu bản sao trong `platform.permissions`. Khóa `fld.*` không
   vào danh mục: chúng cấp theo `field_id` qua `field_permissions` và hiện ở `/me`. Thuộc tính của khóa sinh, một chỗ
   trong SQL mà `platform.rbac_refusals` và danh mục cùng đọc: `obj.*` cấp được trong tenant, mọi mức của
   `platform.object_actions`, `risk` `standard` cho `read` và `elevated` cho các hành động khác, không trọng yếu ở W1,
   `area` `records`; mỗi mục `obj.*` của danh mục mang `object_id` và `action` để client dựng thân `PUT`, và một khóa
   `obj.*` gửi trong mảng `permissions` → 422 `validation_failed` có con trỏ; `fld.*` trên trường `sensitive` làm vai trò trọng yếu qua
   `platform.role_is_critical` (bước 7). Một khóa sinh trỏ tới đối tượng hay trường không sống bị từ chối, không bao
   giờ coi "không có dòng danh mục" là cho qua. `fld.*` trên trường `open` nhận được, không có tác dụng tới khi trường
   `secured` (field-security:R2.2), và vẫn đi hai người như mọi lần nới.
7. **Chống leo thang quyền** trên hai bảng mới, cùng máy của ticket 03 chứ không bản thứ hai:
    - trigger `rbac_refusals_tenant_role_object_privileges` và `rbac_refusals_field_permissions` BEFORE INSERT, UPDATE,
      DELETE gọi `platform.rbac_refusals` của ticket 03 với mức của quyền đối tượng (DELETE áp luật giữ quyền khi gỡ,
      R6.1); quyền trường chỉ vào vai trò khi người làm giữ đúng khóa `fld.*` đó, nên chủ sở hữu công ty (giữ mọi
      `fld.*` qua quyền tính động) là người cấp được `fld.*` đầu tiên, và người xác nhận đề xuất cũng phải giữ khóa đó
      vì thay đổi áp trong giao dịch của người xác nhận;
    - cùng trigger giữ luật hai người của ticket 03 bước 4 (R7.5, R9.10): một lần ghi nới quyền (INSERT, UPDATE nâng
      `depth`, UPDATE `read` lên `edit`) của `dw_app` cần `app.role_change_id` trỏ tới đề xuất cùng tenant, của người
      khác, loại `role_permissions` hay `role_create` cho đúng `role_id`, đã xác nhận bởi `app.user_id` trong chính giao
      dịch này, như ticket 03 bước 4; ticket này mở rộng danh sách lần ghi của hai loại đó ở ticket 03 sang INSERT,
      UPDATE, DELETE hai bảng mới của vai trò đó, và phép so `payload` của ticket 03 sang hai mảng
      `object_privileges` (`object_id`, `action`, `depth`) và `field_permissions` (`field_id`, `access`) mà `payload`
      mang trọn lúc đề xuất. Lần ghi chỉ
      siết (DELETE, hạ `depth`, `edit` xuống `read`) chỉ cần `app.user_id`. Miễn trừ `dw_provisioner`, `dw_migrator`
      và lần ghi chỉ siết ở tenant `offboarding`/`offboarded` như ticket 03 bước 2 và 4 (lần cascade khi offboarding
      xóa định nghĩa; lần ghi nới quyền ở đó vẫn bị xét);
    - `platform.role_is_critical` của org-and-principals/03 (`CREATE OR REPLACE`, một chủ, ADR-0104 (Accepted) sửa
      3/11/2026) thêm nhánh: vai trò có dòng `studio.field_permissions` trên trường sống có `pd_category = 'sensitive'`;
      `platform.rbac_refusals` không giữ phép so riêng mà đọc hàm đó cho luật `platform.roles.bind` (R6.8, DO-32.1),
      cũng như `_check_roles` của DW; một vai trò trọng yếu ra khỏi phủ của `bind`, nên người làm phải giữ mọi quyền của
      nó theo luật giữ quyền (R6.1), R6.8 là một ca của luật đó;
    - `platform.guard_service_principal_grants()` (`CREATE OR REPLACE`) thêm hai nhánh, mỗi nhánh khóa dòng vai trò
      `FOR NO KEY UPDATE` trước khi đọc, như các nhánh có sẵn: INSERT hay UPDATE `studio.field_permissions` trên trường
      `sensitive` khi `platform.service_holders_of_role` của vai trò khác rỗng; UPDATE `pd_category` của
      `studio.field_defs` lên `sensitive` khi một vai trò mang `fld.*` của trường đó có người giữ là tài khoản dịch vụ
      (lần phát hành lùi, cùng 23514 `ck_role_assignments_service_not_critical` mà org-and-principals/03 đã dịch; lần
      phát hành đã duyệt mà không áp được về Nháp kèm lý do theo V4.18, người gửi thấy lý do đó).
      Trigger `guard_service_principal_grants` trên `studio.field_permissions` (BEFORE INSERT OR UPDATE) và trên
      `studio.field_defs` (BEFORE UPDATE OF pd_category) (R9.9);
    - API ghi hai loại quyền qua `PUT /api/v1/admin/roles/{role_id}/permissions` của ticket 03
      (`object_privileges: [{object_id, action, depth}]`, `field_permissions: [{field_id, access}]`): mảng vắng giữ
      nguyên, mảng có mặt thay toàn bộ loại đó (R9.14); thêm quyền hay nâng mức ở bất kỳ mảng nào đi qua đề xuất và xác
      nhận của hai người, chỉ bỏ quyền hay hạ mức là thay đổi chỉ siết, một người cộng audit (R7.6); một `object_id` hay
      `field_id` không thấy dưới RLS → 422 `validation_failed` với `errors[].pointer` tới phần tử, giống id không tồn
      tại, trước khi ghi đề xuất (R9.13); cũng 422 có con trỏ trước khi ghi đề xuất: `action` không có trong
      `platform.object_actions` hay chưa `enforced`, `depth` ngoài tập, `access` ngoài `read`, `edit`; 23514 lúc xác nhận
      dịch như ticket 03 bước 7, không bao giờ 500;
    - `POST /api/v1/admin/roles` với `clone_of` chép cả quyền đối tượng và quyền trường của vai trò nguồn; đó là
      `role_create`, nên người xác nhận phải giữ mọi khóa chép theo luật giữ quyền.
8. Trigger tăng `version` của vai trò cha (ticket 03 bước 5) AFTER INSERT, UPDATE, DELETE trên hai bảng mới, tên đứng
   trước `trg_z_` như ở ticket 03 (R9.11), nên ETag và `proposal_stale` thấy thay đổi quyền đối tượng và quyền trường;
   trigger `platform.bump_access_version()` (ticket 02) trên hai bảng mới, và `trg_z_bump_access_version` AFTER INSERT
   OR DELETE trên `studio.object_defs` và `studio.field_defs`, vì quyền tính động của `tenant_owner` đổi theo định nghĩa
   (R9.12); field-security/01 thêm trigger riêng `trg_z_bump_access_version_access_mode` cho `access_mode`. Hai trigger
   trên bảng định nghĩa là `CONSTRAINT TRIGGER ... DEFERRABLE INITIALLY DEFERRED`, nên dòng
   `platform.tenant_access_versions` bị khóa lúc commit, sau mọi dòng vai trò mà guard của bước 7 khóa trong
   `MetadataService.apply`: một thứ tự khóa (dòng vai trò trước dòng phiên bản, ticket 03 bước 2), không 40P01 giữa một
   lần phát hành và một lần xác nhận vai trò; một test chạy hai việc đó xen kẽ có điều khiển như R7.8.
   `platform.sod_violation` đọc khóa `obj.*` qua `platform.effective_grants` mà không đổi gì.

## Tiêu chí chấp nhận

- [ ] R9.1: tạo đối tượng `lead` → `GET /api/v1/admin/permissions` có năm khóa `obj.lead.*` loại `record`; không có `obj.lead.share`, `obj.lead.export`.
- [ ] R9.2 (RB28): cấp `share` trên `lead` khi `share` chưa `enforced` → 23514 `ck_role_object_privileges_action_enforced`; gỡ trigger → đỏ.
- [ ] R9.3 (RB31): xóa cứng định nghĩa `lead` hay một trường của nó (lượt xóa của offboarding, hay `dw_migrator` trong test, vì W1 không có xóa mềm định nghĩa) → không còn dòng quyền nào trỏ tới chúng; `/me` kế tiếp không có `obj.lead.*`.
- [ ] R9.8 (RB35): bằng `dw_migrator`, vai bỏ qua RLS và được trigger `rbac_refusals_*` miễn nên chỉ khóa ngoại chặn được, INSERT dòng của tenant A vào `platform.tenant_role_object_privileges` với `role_id` hay `object_id` của B và vào `studio.field_permissions` với `role_id` hay `field_id` của B → FK kép từ chối (23503), không dòng nào; migration thử đổi một FK ghép thành FK một cột → test đỏ.
- [ ] R9.4 (RB29): vai trò có `obj.lead.read` mức `own` → `platform.workspace_reach` rỗng cho người giữ; đổi hàm coi `own` như `workspace` → đỏ.
- [ ] R9.5 (RB30): người giữ `obj.lead.read` mức `workspace` đặt mức `tenant` → 23514; thêm `fld.lead.phone.edit` mình không giữ → 23514; `tenant_owner` đề xuất thêm `fld.lead.phone.read` vào vai Marketing → 202, quyền chưa đổi; một `tenant_owner` khác xác nhận → áp, `/me` của người giữ vai Marketing có `fld.lead.phone.read`; người xác nhận không giữ khóa đó → 403 `rbac_escalation`; gỡ trigger → test SQL thô đỏ.
- [ ] R9.6: vai trò A cho `fld.lead.phone.read`, vai trò B cho `fld.lead.phone.edit`, cùng một người → `/me` trả cả hai khóa.
- [ ] R9.7: tạo trường `phone` trên `lead` → `/me` của người giữ `tenant_owner` có `fld.lead.phone.read` và `fld.lead.phone.edit` mức `tenant`, `studio.field_permissions` không có dòng nào cho trường đó; xóa trường → hai khóa vắng ở `/me` kế tiếp; bỏ nhánh `fld.*` khỏi quyền tính động của `tenant_owner` → test đỏ.
- [ ] R6.8 (RB33): người chỉ giữ `platform.roles.bind` đề xuất gán vai trò có `fld.lead.cccd.read` trên trường `sensitive` mà mình không giữ → 403 `rbac_escalation`, không dòng đề xuất; cùng thao tác bằng SQL thô dưới `dw_app` → 23514; vai trò chỉ có `fld.*` trên trường `basic` → nhận; bỏ nhánh `sensitive` khỏi `platform.rbac_refusals` → test đỏ.
- [ ] R9.9 (RB44): vai trò R gán cho một tài khoản dịch vụ; đề xuất `role_permissions` thêm `fld.lead.cccd.read`
      (`cccd` `sensitive`) vào R, người thứ hai xác nhận → 23514 `ck_role_assignments_service_not_critical`, không dòng;
      R giữ `fld.lead.note.read` trên trường `basic` rồi một phiên bản nâng `note` lên `sensitive` → lần phát hành lùi;
      `platform.role_is_critical` trả true cho vai trò mang `fld.*` nhạy cảm; bỏ nhánh đó → test đỏ.
- [ ] R9.10 (RB45): `tenant_owner` INSERT `studio.field_permissions` bằng SQL thô dưới `dw_app` không có
      `app.role_change_id` → 23514; cùng lần INSERT `platform.tenant_role_object_privileges` → 23514; DELETE cùng dòng
      chỉ với `app.user_id` → nhận; lần xác nhận một đề xuất `role_permissions` có `field_permissions` → áp; gỡ nhánh
      hai người khỏi trigger của bảng mới → test đỏ.
- [ ] R9.11 (RB45): một người bỏ `fld.lead.phone.read` khỏi R (200) giữa lúc một đề xuất giữ khóa đó và lúc xác nhận →
      409 `proposal_stale`, khóa không trở lại; `If-Match` cũ sau khi thêm một quyền đối tượng → 412; gỡ trigger
      `version` trên bảng mới → test đỏ.
- [ ] R9.12 (RB46): ngữ cảnh truy cập của `tenant_owner` đã nằm trong bộ đệm; phát hành phiên bản thêm trường `email`
      vào `lead` → `platform.tenant_access_versions.version` tăng, `/me` kế tiếp có `fld.lead.email.read`; gỡ trigger
      trên `studio.field_defs` → test đỏ.
- [ ] R9.13 (RB47): người của A gửi `PUT .../permissions` với `field_id` của B, hay `object_id` của B → 422
      `validation_failed` với con trỏ tới phần tử, thân giống id ngẫu nhiên, không dòng `platform.role_change_requests`;
      để lỗi khóa ngoại tới lúc xác nhận → test đỏ.
- [ ] R9.14: `PUT .../permissions` chỉ có `permissions` → quyền đối tượng và quyền trường của vai trò không đổi; thân có
      `field_permissions: []` mà không thêm gì → chỉ siết, 200, bỏ mọi quyền trường; coi mảng vắng là rỗng → test đỏ.
- [ ] R9.15: vai trò có `access = 'edit'` trên `phone` → `/me` có cả `fld.lead.phone.read` và `.edit`; người chỉ giữ vai
      trò đó cấp được `fld.lead.phone.read` cho vai trò khác (qua đề xuất); bỏ khóa `.read` sinh từ `edit` → test đỏ.
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
- 2026-10-24 (agent): vòng sửa 4, lượt ba: bước 3 nêu hai FK ghép của `studio.field_permissions`, tới `platform.tenant_roles (tenant_id, id)` và `studio.field_defs (tenant_id, id)`, cùng chỉ mục `(tenant_id, field_id)`, thay cho "FK tới vai trò" không nêu cột; tiêu chí R9.3 (RB31) thêm ca `field_id`, `role_id` của tenant khác (Quyết định 24/10/2026 của spec).
- 2026-10-24 (agent): vòng sửa 4, lượt bốn: ca `object_id`, `field_id`, `role_id` của tenant khác rời tiêu chí R9.3 (RB31), vì RB31 của spec chỉ thử việc xóa định nghĩa, sang tiêu chí R9.8 với kiểm soát RB35; bước 2 thêm index `(action)` cho FK tới `platform.object_actions` và bước 3 thêm index `granted_by`, để mỗi khóa ngoại có index dẫn bằng cột của nó (CLAUDE.md, Data model rules; hai dòng Quyết định 24/10/2026 của spec).
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness, builder check và boundary walk (ba subagent:
  builder, ranh giới 1-3, ranh giới 4-6) vì ticket thêm một revision và đổi route; đọc trên code đã dựng của ticket 02
  (`bd8c607`), org-and-principals/03 (`14a19ed`, `platform.role_is_critical`, `guard_service_principal_grants`) và
  custom-objects/02 (`65bddef`). Script 24 Đạt. Một CRITICAL (luật trọng yếu ở `rbac_refusals` thay vì
  `platform.role_is_critical`, không guard tài khoản dịch vụ trên bảng mới; M13 của ticket 03) và chín HIGH, sửa ở spec
  (Quyết định 4/11/2026, R9.9 tới R9.15, RB44 tới RB47) và bước 5 tới 8. Nếu sai thì: ghi ở đây khi dựng và sửa spec.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (builder check mới trên bản đã sửa) tìm 7 HIGH, đã sửa
  ở bước 4, 6, 7, 8: quyền vai DB của hai bảng mới và SELECT cho `dw_provisioner` vì `platform.effective_grants` chạy
  dưới nó; 422 có con trỏ cho `action`, `depth`, `access` sai trước khi ghi đề xuất; `clone_of` chép hai loại quyền
  mới; mục `obj.*` của danh mục mang `object_id`, `action`, `risk`, `area`; vai trò trọng yếu ra khỏi phủ của `bind`;
  lần phát hành bị guard từ chối về Nháp theo V4.18; trigger phiên bản trên bảng định nghĩa hoãn tới commit để giữ một
  thứ tự khóa. Sửa của lượt này không có người đọc mới: nhận rủi ro (agent, theo ủy quyền 31/10/2026), mỗi sửa có tiêu
  chí hay test đỏ được. Nếu sai thì: lỗi lộ ra khi dựng, ghi ở đây.
- 2026-11-04 (agent): MEDIUM của gate, chưa sửa. (M1) Audit `platform.role.permissions_set` của ticket 03 chỉ mang id
  vai trò: nên thêm `object_id` hay `field_id`, `action` hay `access`, `depth` trước và sau, để đi ngược được "ai cấp
  đọc `cccd` cho vai trò X" (ADR-0106 (Accepted) mục 5). (M2) `granted_by` không có người ghi định nghĩa: nên là
  `app.user_id` của giao dịch áp (người xác nhận), đặt bằng trigger; `tenant_role_object_privileges` không có cột tương
  đương. (M3) `object_actions.enforced` đổi trong migration của record-access hay custom-objects không tăng phiên bản
  quyền: migration đó tự gọi `platform.bump_access_version` cho mọi tenant hay chấp nhận TTL. (M4) `platform.scopes_in`
  với `obj.*` mức `own` neo ở workspace khác: tầm theo bản ghi là của RLS (record-access), field-security đọc
  `platform.effective_grants` hợp mọi neo. (M5) Một phiên bản nâng `pd_category` lên `sensitive` làm vai trò thành trọng
  yếu với gán đã có của người: gán cũ đứng, chỉ gán mới qua `bind` bị chặn; ghi ở đây cho lượt kiểm nhất quán.
- 2026-11-04 (agent): bảng cặp. Ticket không có đường phụ thuộc với ticket này và đang dựng hay `ready-for-agent`:
  usage-and-limits/03 và connections-and-vault đang dựng: chung đầu chuỗi Alembic và `test_privileges.py`, nên
  revision đổi `down_revision` về head lúc commit; field-security/01 chờ ticket này (có đường) và thêm trigger tên khác
  trên `studio.field_defs`. Ticket chờ ticket 03, mà ticket 03 chờ ticket 05 `ready-for-human` (FOG-49): ticket này và
  mọi ticket chờ nó (record-access/02, field-security/01, custom-objects/03) đứng sau câu trả lời của người giữ
  dw-proterial. Thứ tự dựng: ngay sau ticket 03.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): khóa cột cũ tách từ ticket 03 sang ticket 06 (Quyết định 4/11/2026
  của spec); ticket này chỉ cần phần không khóa của ticket 03 (`platform.rbac_refusals`, đề xuất, trigger `version`),
  nên `Blocked by` giữ nguyên và câu "đứng sau câu trả lời của người giữ dw-proterial" ở dòng bảng cặp trên hết đúng:
  ticket này và chuỗi chờ nó chỉ chờ ticket 03 dựng xong. Bảng cặp thêm 04~06: không đường phụ thuộc, chung đầu chuỗi
  Alembic (ticket xong sau trỏ lại `down_revision`); 06 chỉ đổi `platform.memberships`, không bảng hay trigger của ticket
  này. Nếu sai thì: như dòng của ticket 03 cùng ngày.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate lại ticket 03 cùng ngày (boundary walk, HIGH): ticket 03 bước 4
  nay đòi đề xuất được xác nhận bởi `app.user_id` trong chính giao dịch ghi và lần ghi khớp `payload`, không chỉ khớp
  `role_id`; bước 7 ở trên đổi theo cho hai bảng mới, không phạm vi mới. Nếu sai thì: như ticket 03 cùng ngày.
