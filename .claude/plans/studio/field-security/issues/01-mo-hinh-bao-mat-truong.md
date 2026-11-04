# 01 — Mô hình bảo mật trường và hàm quyết định duy nhất visible_fields

Status: ready-for-agent
Blocked by: .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md, .claude/plans/studio/tenant-rbac/issues/04-quyen-doi-tuong-va-truong-co-do-sau.md, .claude/plans/studio/compliance-pdpl/issues/01-tu-vung-du-lieu-ca-nhan.md, .claude/plans/studio/custom-objects/issues/02-luoc-do-dinh-nghia-object.md, .claude/plans/studio/record-access/issues/04-ngu-canh-actor-o-moi-cua.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.6, R1.7, R1.8, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.8, R2.9, R2.10, FS1, FS7, FS11, FS12, FS13, FS15

## Mục tiêu

Mỗi trường có `access_mode` (`open` hoặc `secured`), dữ liệu cá nhân `secured` mặc định và nhạy cảm luôn `secured`
(R1); một hàm thuần `resolve_field_access` là chủ duy nhất của quyết định "người gọi thấy hay sửa trường nào", cộng
dồn quyền trường qua mọi vai, giao với giới hạn dữ liệu, không ẩn được trường duy nhất với người ghi (R2). Đủ cho vai
Marketing và vai Sales trên `lead`: Sales chưa được cấp không đọc được `phone`, `email`. DO-34.1 đã quyết theo khuyến
nghị (a) (Đạt, 23/10/2026); `access_mode` đổi qua phát hành `dw.object/v1` của custom-objects, không có route riêng
(`D:field-security:R1.4~requirements.md:D11`).

## Việc cần làm

1. Một revision Alembic (id ngẫu nhiên do `alembic revision -m "..."` sinh) sửa `studio.field_defs` (custom-objects
   ticket 02 tạo), chép nguyên văn ràng buộc từ mục Dữ liệu của spec:
    - thêm `access_mode text NOT NULL DEFAULT 'open'` với `ck_field_defs_access_mode CHECK (access_mode IN ('open','secured'))`;
    - ngay sau đó, trước mọi CHECK mới, điền lại dòng đã có (R1.7):
      `UPDATE studio.field_defs SET access_mode = 'secured' WHERE pd_category <> 'none'`, vì `ADD COLUMN ... DEFAULT`
      không qua trigger INSERT và mọi trường dữ liệu cá nhân mà custom-objects/02 đã tạo sẽ thành `open`;
    - thêm `ck_field_defs_sensitive_is_secured CHECK (pd_category <> 'sensitive' OR access_mode = 'secured')`;
    - trigger `BEFORE INSERT` trên `studio.field_defs` đặt `access_mode = 'secured'` khi `pd_category <> 'none'` (trường
      dữ liệu cá nhân không tạo ra ở `open` được);
    - trigger `trg_z_bump_access_version_access_mode AFTER UPDATE OF access_mode ... FOR EACH ROW` gọi
      `platform.bump_access_version()` của tenant-rbac ticket 02 (hàm đọc `NEW.tenant_id`; tên `trg_z_` xếp cuối như mọi
      trigger cùng hàm, `db/migrations/versions/b5677d345bc1_tenant_roles.py:1153`, giữ một thứ tự khóa; tên riêng vì `trg_z_bump_access_version` AFTER INSERT OR DELETE trên cùng bảng là của tenant-rbac/04 cho quyền tính động của `tenant_owner`);
    - `dw_app` thêm `access_mode` vào tập cột định nghĩa được UPDATE
      (`db/migrations/versions/16357d3dbff8_studio_object_definitions_and_records.py:398`); `dw_provisioner`,
      `dw_agent_ro` không gì mới.
    - Downgrade gỡ cột, hai CHECK và hai trigger, giữ `studio.field_defs`.
    - Móc ghi cột (R1.8), sửa mã của custom-objects/02 đã dựng (`65bddef`): `FieldDefinition` thêm `access_mode`
      (`packages/python/dw_studio/src/dw_studio/records/domain/document.py:188`), `field_definition` lấy từ tài liệu đã
      parse (mặc định đã điền), `name_definition` suy ra `secured` khi `pd_category` của `name_field` khác `none` và
      `open` khi bằng `none`, `OWNER_ROW` và `WORKSPACE_ROW` là `open`; `_MUTABLE` của
      `packages/python/dw_studio/src/dw_studio/records/application/metadata.py:53` thêm `access_mode`, nên móc ghi nó ở
      trường mới và trường có sẵn; kho định nghĩa đọc cột ra, nên `definition_of` so cả `access_mode` (lời hứa ở
      `document.py:190`). `MetadataService.apply` là đường ghi duy nhất của cột.
2. (Bỏ 23/10/2026) Không đăng ký khóa `studio.field_security.manage`: không route nào đọc nó, vì `access_mode` đổi qua
   phát hành `dw.object/v1` (`D:field-security:R1.4~requirements.md:D11`).
3. Trong gói truy cập Studio (`dw_studio.field_security`, các lớp `domain/ application/ adapters/`):
    - kiểu `FieldAccess`: map `field_id` sang `hidden`, `read` hoặc `edit`, kèm `fls_version`, là `schema_version` của
      đối tượng (`version_no` của phiên bản đang áp, custom-objects/02), một số cho cả đối tượng (ADR-0106 (Accepted)
      quyết 4);
    - hàm thuần `resolve_field_access(principal_grants, object_security, boundary, action) -> FieldAccess`:
      `principal_grants` là tập khóa `obj.<object>.<action>` và `fld.<object>.<field>.read|edit` hiệu lực của chủ thể ở
      công ty đang gắn (tenant-rbac `platform.effective_grants`; `fld.*` luôn mức `tenant`, tenant-rbac/04 bước 5);
      `object_security` là `api_name`, `access_mode`, `pd_category`, `is_unique` của mỗi trường cùng `schema_version`;
      `boundary` là `None` chỉ khi actor là `user`, còn với `agent`/`workflow` là quyền trường của mọi mắt xích trong
      chuỗi `studio.boundary_chain` (có thể rỗng); `action` là `read`, `update` (mặc định) hay `create` (R2.7);
    - hàng `owner` và `workspace` của `studio.field_defs` nằm ngoài `FieldAccess`: chúng là cột hệ thống, hiện với ai
      tới được bản ghi (ADR-0105 (Accepted)); `name` và mọi trường công ty định nghĩa đi qua hàm;
    - với `action` `create`: trường `edit` khi chủ thể giữ `obj.<object>.create` và (trường `open`, hay trường `secured`
      với `fld.<object>.<field>.edit`), còn lại `hidden`, không cần `obj.<object>.read`, nên vai chỉ tạo (nhập lead) tạo
      được bản ghi; thân trả về sau khi tạo chiếu theo `action` `read` (R2.7);
    - quy tắc của `read` và `update`, theo thứ tự: không giữ `obj.<object>.read` → mọi trường `hidden`; trường `open` → `edit` khi giữ khóa
      của `action` ghi (`obj.<object>.update`, hay `.create` khi `action` là `create`), `read` khi không (R2.2); trường
      `secured` → `hidden` khi không có khóa `fld.*`, `read` hay `edit` cộng dồn qua mọi vai, `edit` chỉ khi cũng giữ
      khóa của `action` ghi (R2.3, R2.4); trường duy nhất → ít nhất `read` khi chủ thể giữ `obj.<object>.create` hay
      `.update` và giữ `obj.<object>.read` (R2.6); rồi với `agent`/`workflow` giao với từng mắt xích của `boundary`, trường không có dòng ở một mắt
      xích hay chuỗi rỗng → `hidden`, kể cả trường `open` và trường duy nhất (R2.5, R2.8);
    - helper `visible_fields(access)` trả tập trường `read` trở lên để adapter chiếu cột; helper thuần
      `reads_all(accesses, stamped_fields) -> bool`, `True` khi mọi `<object>.<field>` của `payload.stamped_fields`
      (workflow-nodes/06) là `read` hay `edit` trong `FieldAccess` của đối tượng đó, `False` khi một đối tượng hay
      trường không có trong `accesses` (luật của R4.5, R4.7, mà workflow-nodes/06 và ticket 02 gọi);
    - phần không thuần, một chỗ: `FieldAccessService.for_object(tx, object_id, action) -> FieldAccess` đọc trong giao
      dịch của bên gọi, qua một port `FieldSecurityInputsPort` với adapter SQL, các dòng `studio.field_defs` sống của đối
      tượng, khóa hiệu lực của chủ thể đọc từ `platform.effective_grants` trong chính giao dịch đó, hợp mọi gán ở mọi
      neo và mọi mức (người gọi với actor `user`; `coalesce(run_as_principal_id, requested_by)` của dòng lượt với
      `agent`/`workflow`), không từ phép chiếu theo workspace đang thao tác hay bộ đệm của `AccessContext`, vì tầm theo
      bản ghi là của RLS, dưới RLS của công ty đang gắn, và `studio.actor_boundary_fields` của mọi id trong `app.boundary_id` theo `app.actor_kind` mà
      `bind_actor` của record-access/04 đặt; `app.actor_kind` thiếu hay một lần đọc lỗi → ném lỗi, bên gọi từ chối,
      không bao giờ coi như `user`. Biến thể `FieldAccessService.for_person(tx, user_id, object_id)` tính cho một người
      khác bên gọi (ứng viên duyệt, người xem), luôn `boundary=None`, đọc quyền của người đó dưới RLS của công ty đang
      gắn. Không bộ đệm nào giữ `FieldAccess` quá giao dịch (R2.9); custom-objects/03,
      tools-and-skills/03, workflow-nodes/03, /06 và telemetry-and-audit/03 gọi service này, không tự đọc quyền;
    - test thuộc tính ≥ 1.000 trường hợp sinh ngẫu nhiên: cộng dồn, mặc định dữ liệu cá nhân, nhạy cảm không mở, giao
      với mọi mắt xích, chuỗi rỗng ẩn hết, trường duy nhất đọc được ở phía chủ thể mà giới hạn vẫn ẩn được, `edit` chỉ
      khi giữ khóa của `action`.
4. (Bỏ 23/10/2026) Không route `PUT .../fields/{field}/security`: mở một trường `basic` là phiên bản `dw.object/v1` mới
   qua người thứ hai, đóng một trường là phiên bản chỉ siết một người cộng audit (`custom-objects:R1.2`,
   `custom-objects:R1.7`); trình kiểm của loại `object` từ chối mở trường nhạy cảm (`custom-objects:R2.5`).

## Tiêu chí chấp nhận

- [ ] R1.1: `studio.field_defs` có đúng một `access_mode` mỗi trường; giá trị ngoài `open`, `secured` bị từ chối theo
      tên `ck_field_defs_access_mode`; phát hành một phiên bản đặt `access_mode` → cột bằng giá trị của tài liệu.
- [ ] R1.2 (FS1): tạo trường `pd_category = 'basic'` → `access_mode = 'secured'`; đổi trigger để trường `pd` khác
      `none` giữ `open` → test đỏ.
- [ ] R1.3 (FS11): `UPDATE studio.field_defs SET access_mode = 'open'` cho trường `pd_category = 'sensitive'` → 23514
      `ck_field_defs_sensitive_is_secured`, không đổi dòng; gỡ CHECK → test đỏ.
- [ ] R1.6 (FS12): phiên bản đóng `phone` lên Đang dùng ở giao dịch A → yêu cầu đầu tiên sau đó của người gọi thấy
      `phone` là `hidden`; gỡ trigger `platform.bump_access_version()` trên `studio.field_defs` → test đỏ.
- [ ] R2.1: `resolve_field_access` trả đúng một trong `hidden`, `read`, `edit` cho mỗi trường của đối tượng, kèm
      `fls_version` nó đã dùng; test thuộc tính sinh ≥ 1.000 trường hợp cho R2.1 tới R2.6 xanh.
- [ ] R2.2: trường `open` → `read` cho người đọc được bản ghi, `edit` cho người sửa được bản ghi.
- [ ] R2.3 (FS1): trường `secured` chưa cấp cho vai người gọi → `hidden`; lược đồ `visible_fields` không có trường đó.
- [ ] R2.4: vai A cho `fld.lead.phone.read`, vai B cho `fld.lead.phone.edit`, cùng một người → `resolve_field_access`
      trả `edit` cho `phone`.
- [ ] R2.5: lượt chạy actor `agent` với giới hạn dữ liệu chỉ có `fld.lead.name.read` → một trường chủ thể được cấp
      nhưng ngoài giới hạn trả `hidden`; mở rộng giới hạn → trường đó lên `read`.
- [ ] R2.6 (FS7): ẩn trường duy nhất `phone` với vai có quyền `create` trên `lead` → `resolve_field_access` trả `read`,
      không `hidden`; lỗi trùng của custom-objects (`custom-objects:R7.1`) không có giá trị, không id bản ghi kia; gỡ
      ngoại lệ trường duy nhất trong hàm → test đỏ; cùng chủ thể dưới giới hạn bỏ `phone` → `hidden`.
- [ ] R2.2: người giữ `fld.lead.phone.edit` mà không giữ `obj.lead.update` → `read`; trường `open` với người chỉ
      giữ `obj.lead.read` → `read`; người không giữ `obj.lead.read` → mọi trường `hidden`; bỏ điều kiện khóa của
      `action` khỏi nhánh `edit` → test đỏ.
- [ ] R2.7: người giữ `obj.lead.create` mà không giữ `obj.lead.update`, với `fld.lead.phone.edit` → `action` `create`
      trả `edit` cho `phone`, `action` `update` trả `read`; trường `open` với `action` `create` → `edit`; vai chỉ giữ
      `obj.lead.create` (không `read`) → `action` `create` trả `edit` cho trường `open`, `hidden` cho trường `secured`
      chưa cấp, kể cả trường duy nhất; gỡ nhánh `create` → test đỏ.
- [ ] R2.4: người giữ `obj.lead.read` mức `own` neo ở workspace A, gọi từ workspace B → `FieldAccessService` vẫn tính
      `phone` theo `fld.lead.phone.read` của người đó (tầm tới bản ghi để RLS quyết); đọc khóa từ phép chiếu theo
      workspace đang thao tác → test đỏ.
- [ ] R2.8: `FieldAccessService` cho lượt `agent` có `app.boundary_id` rỗng → mọi trường `hidden`, kể
      cả trường `open`; `app.actor_kind` không đặt → lỗi, không `FieldAccess`; coi chuỗi rỗng như `boundary=None` →
      test đỏ.
- [ ] R2.9 (FS12): hai giao dịch nối nhau của cùng một lượt, giữa chúng thu `fld.lead.phone.read` của chủ thể → giao
      dịch thứ hai trả `hidden` cho `phone`; giữ `FieldAccess` trong một bộ đệm theo lượt → test đỏ.
- [ ] R2.10 (FS13): tích hợp trên PostgreSQL, hai công ty cùng có đối tượng `lead`, một người là thành viên cả hai, giữ
      `fld.lead.phone.read` chỉ ở A → `FieldAccessService` gắn B trả `hidden` cho `phone` của B; adapter đọc quyền
      không qua RLS của công ty đang gắn → test đỏ.
- [ ] R1.7 (FS15): migration chạy trên CSDL có dòng `pd_category = 'basic'` và `'sensitive'` tạo trước nó → cả hai là
      `secured` và CHECK thêm được; bỏ bước điền lại → test đỏ.
- [ ] R1.8 (FS15): phát hành `lead` với `name_field` `pd_category = 'none'` → `name` `open`; phiên bản nâng lên
      `basic` → `name` `secured`; phiên bản đặt `access_mode: open` cho trường `none` → cột `open`, `definition_of`
      bằng bản đọc từ kho; bỏ `access_mode` khỏi `_MUTABLE` → test đỏ.
- [ ] R2.1: helper `reads_all`, `stamped_fields` `["lead.phone"]` với `phone` `hidden` → `False`; với `read` → `True`; một đối tượng
      không có trong `accesses` → `False`; trả `True` khi thiếu → test đỏ.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:167`; spec: R2.1 (thay `data_classification`).
- `docs/adr/0106-field-access-follows-personal-data-category.md:52-61`; spec: R1, R2.
- `.claude/plans/studio/custom-objects/issues/02-luoc-do-dinh-nghia-object.md:32`; spec: R1.2 (`pd_category` của `studio.field_defs`).
- `.claude/plans/studio/tenant-rbac/issues/04-quyen-doi-tuong-va-truong-co-do-sau.md:40-45`; spec: R2.4 (`fld.*` qua `platform.effective_grants`).
- `.claude/plans/studio/record-access/spec.md:379-380`; spec: R2.5 (`studio.actor_boundary_fields`).

## Comments

- 2026-10-23 (agent): `Blocked by` trỏ tới compliance-pdpl ticket 01 (từ vựng `dw_kernel.personal_data`) đang viết cùng đợt; tệp sẽ có khi đợt này xong.
- 2026-10-23 (agent): DO-34.1 và `D:field-security:R1.4~requirements.md:D11` đã có lời đáp (Đạt và người đặt yêu cầu, 23/10/2026); Status về needs-triage. Bỏ R1.4, R1.5, khóa `studio.field_security.manage` và route; tên ràng buộc thành `ck_field_defs_*`; thêm record-access/04 vào Blocked by vì R2.5 đọc `studio.actor_boundary_fields`.
- 2026-10-24 (agent): vòng sửa 4: Blocked by thêm tenant-rbac/02 theo danh sách cạnh của vòng này, vì trigger của bước 1 gọi `platform.bump_access_version()` mà ticket đó tạo; cạnh này nói thẳng điều trước đây chỉ có qua tenant-rbac/04.
- 2026-10-24 (agent): kiểm vòng sửa 4, lượt ba: ba neo ở Nguồn trỏ lại đúng dòng, vì lượt ba thêm dòng vào ticket 02 của custom-objects, ticket 04 của tenant-rbac và spec của record-access; nội dung được neo không đổi, và Hiện trạng của spec sửa hai neo cùng lý do.
- 2026-10-24 (agent): vòng sửa 4, lượt bốn: neo tới ticket 02 của custom-objects và tới spec của record-access ở Nguồn trỏ lại đúng dòng, vì lượt bốn thêm dòng vào hai tệp đó; nội dung được neo không đổi, neo tới ticket 04 của tenant-rbac vẫn đúng, và Hiện trạng của spec sửa hai neo cùng lý do.
- 2026-10-24 (agent): neo tới spec của record-access ở Nguồn trỏ lại đúng dòng, vì spec đó thêm tiêu chí R6.10 và câu quyền xóa của ba bảng giới hạn dữ liệu ở mục Dữ liệu; nội dung được neo không đổi, và Hiện trạng của spec sửa neo cùng lý do.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness, builder check và boundary walk (ba subagent:
  builder, ranh giới 1-3, ranh giới 4-6) vì ticket có migration; script 24 Đạt. Sửa ở spec (Quyết định 4/11/2026) và
  bước 1, 3 ở trên: (a) nhánh `create` của `resolve_field_access` mà custom-objects/03 bước 7a (r) cần, qua tham số
  `action` (R2.7); (b) `edit` chỉ khi giữ khóa `obj.*` của hành động, `read` chỉ khi giữ `obj.<object>.read` (ADR-0106 (Accepted)
  quyết 3; R2.2, R2.4); (c) `boundary=None` mở khi chuỗi giới hạn rỗng: nay giao mọi mắt xích của
  `studio.boundary_chain`, rỗng hay thiếu dòng → `hidden` (R2.5, R2.8); (d) `ADD COLUMN ... DEFAULT 'open'` mở mọi
  trường dữ liệu cá nhân mà custom-objects/02 đã tạo: điền lại (R1.7); (e) `name` không mang `access_mode` trong tài
  liệu: suy từ `pd_category` ở mỗi lần áp (R1.8); (f) một chỗ không thuần đọc đầu vào, không bộ đệm quá giao dịch,
  quyền sống chứ không theo bản kê lượt (R2.9); (g) test âm chéo công ty (R2.10, FS13); (h) `reads_all` trên
  `payload.stamped_fields` là luật mà workflow-nodes/06 gọi ở guard; (i) `fls_version` là `schema_version`. Nếu sai
  thì: ghi ở đây khi dựng và sửa spec.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (builder check mới trên bản đã sửa) tìm 4 HIGH, đã sửa ở
  bước 3: (j) vai chỉ tạo không giữ `obj.<object>.read` nên mọi trường thành `hidden` và không tạo được: nhánh
  `create` không đòi `read`; (k) khóa của người gọi đọc từ `platform.effective_grants` trong giao dịch, hợp mọi neo,
  không từ phép chiếu theo workspace hay bộ đệm của `AccessContext`; (l) `for_person` cho ứng viên duyệt và người xem
  khác bên gọi; (m) `owner`, `workspace` ngoài `FieldAccess`. Sửa của lượt này không có người đọc mới: nhận rủi ro
  (agent, theo ủy quyền 31/10/2026), mỗi sửa có tiêu chí đỏ được. Nếu sai thì: lỗi lộ ra khi dựng, ghi ở đây.
- 2026-11-04 (agent): MEDIUM của gate, chưa sửa. (M1) `ToolDefinition.data_classification` vẫn khai mà không ai đọc
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:201`, `tool_specs.py:55`, ba YAML dưới
  `configs/tools/`); compliance-pdpl/01 Comments nói gỡ là của ticket này, nhưng thay nó bằng `pd_category` theo thuộc
  tính lược đồ công cụ là của tools-and-skills; cho `checking-plan-consistency` chọn một chủ, gỡ cùng lúc thay.
  (M2) R2.6 cho vai có `create` đọc trường duy nhất `sensitive` (ví dụ `national_id`) mà không qua lần cấp hai người;
  ADR-0106 (Accepted) quyết 4 đã quyết như vậy, nên giữ. (M3) Trigger tăng phiên bản khóa dòng
  `platform.tenant_access_versions` trong giao dịch phát hành, sau khóa advisory của đối tượng; đo ở lúc đóng hàng.
- 2026-11-04 (agent): bảng cặp. Ticket không có đường phụ thuộc với ticket này và đang dựng hay `ready-for-agent`:
  custom-objects/03 đến 06 đều chờ ticket này (có đường); tenant-rbac/03 (chuỗi Alembic, không đụng `studio.field_defs`)
  và connections-and-vault, usage-and-limits đang dựng: chung đầu chuỗi Alembic, nên revision của ticket này đổi
  `down_revision` về head lúc commit (`wave-close.md`, hai lane); không chung bảng hay tệp nào khác. Thứ tự dựng: sau
  tenant-rbac/04 (khóa `fld.*`) và record-access/04 (`bind_actor`, `studio.boundary_chain`); trước custom-objects/03,
  /06, workflow-nodes/03, tools-and-skills/03, telemetry-and-audit/03 và ticket 02.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
