# 01 — Mô hình bảo mật trường và hàm quyết định duy nhất visible_fields

Status: needs-triage
Blocked by: .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md, .claude/plans/studio/tenant-rbac/issues/04-quyen-doi-tuong-va-truong-co-do-sau.md, .claude/plans/studio/compliance-pdpl/issues/01-tu-vung-du-lieu-ca-nhan.md, .claude/plans/studio/custom-objects/issues/02-luoc-do-dinh-nghia-object.md, .claude/plans/studio/record-access/issues/04-ngu-canh-actor-o-moi-cua.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.6, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, FS1, FS7, FS11, FS12

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
    - thêm `ck_field_defs_sensitive_is_secured CHECK (pd_category <> 'sensitive' OR access_mode = 'secured')`;
    - trigger `BEFORE INSERT` trên `studio.field_defs` đặt `access_mode = 'secured'` khi `pd_category <> 'none'` (trường
      dữ liệu cá nhân không tạo ra ở `open` được);
    - trigger `AFTER UPDATE OF access_mode` gọi `platform.bump_access_version()` của tenant-rbac ticket 02;
    - `dw_app` thêm `access_mode` vào tập cột định nghĩa được UPDATE; `dw_provisioner`, `dw_agent_ro` không gì mới.
    - Downgrade gỡ cột, hai CHECK và hai trigger, giữ `studio.field_defs`.
    - `MetadataService.apply` của custom-objects/02 ghi cột `access_mode` từ thuộc tính `access_mode` của mỗi trường
      trong phiên bản `dw.object/v1` lên Đang dùng; đó là đường ghi duy nhất của cột.
2. (Bỏ 23/10/2026) Không đăng ký khóa `studio.field_security.manage`: không route nào đọc nó, vì `access_mode` đổi qua
   phát hành `dw.object/v1` (`D:field-security:R1.4~requirements.md:D11`).
3. Trong gói truy cập Studio (`dw_studio.field_security`):
    - kiểu `FieldAccess`: map `field_id` sang `hidden`, `read` hoặc `edit`, kèm `fls_version` (phiên bản metadata
      trường đã dùng);
    - hàm thuần `resolve_field_access(principal_grants, object_security, boundary) -> FieldAccess`: `principal_grants`
      là tập khóa `fld.<object>.<field>.read|edit` hiệu lực (tenant-rbac `platform.effective_grants`),
      `object_security` là `access_mode`, `pd_category`, `is_unique` và quyền `create`/`update` của người gọi trên đối
      tượng của mỗi trường, `boundary` là quyền trường của giới hạn dữ liệu đọc từ `studio.actor_boundary_fields`
      (record-access) hoặc `None` cho actor `user`;
    - quy tắc: trường `open` trả `read`/`edit` theo quyền bản ghi; trường `secured` trả `hidden` nếu không có khóa
      `fld.*`, `read` hoặc `edit` cộng dồn qua mọi vai (lấy mức cao hơn khi cả hai); với actor `agent`/`workflow`, giao
      với `boundary` (không bao giờ rộng hơn); trường duy nhất trả ít nhất `read` cho vai có `create` hoặc `update`;
    - helper `visible_fields(principal, object)` trả tập trường `read` trở lên để adapter chiếu cột;
    - test thuộc tính ≥ 1.000 trường hợp sinh ngẫu nhiên: cộng dồn, mặc định dữ liệu cá nhân, nhạy cảm không mở, giao
      với giới hạn, trường duy nhất đọc được.
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
      ngoại lệ trường duy nhất trong hàm → test đỏ.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:167`; spec: R2.1 (thay `data_classification`).
- `docs/adr/0106-field-access-follows-personal-data-category.md:52-61`; spec: R1, R2.
- `.claude/plans/studio/custom-objects/issues/02-luoc-do-dinh-nghia-object.md:29`; spec: R1.2 (`pd_category` của `studio.field_defs`).
- `.claude/plans/studio/tenant-rbac/issues/04-quyen-doi-tuong-va-truong-co-do-sau.md:39-44`; spec: R2.4 (`fld.*` qua `platform.effective_grants`).
- `.claude/plans/studio/record-access/spec.md:367-368`; spec: R2.5 (`studio.actor_boundary_fields`).

## Comments

- 2026-10-23 (agent): `Blocked by` trỏ tới compliance-pdpl ticket 01 (từ vựng `dw_kernel.personal_data`) đang viết cùng đợt; tệp sẽ có khi đợt này xong.
- 2026-10-23 (agent): DO-34.1 và `D:field-security:R1.4~requirements.md:D11` đã có lời đáp (Đạt và người đặt yêu cầu, 23/10/2026); Status về needs-triage. Bỏ R1.4, R1.5, khóa `studio.field_security.manage` và route; tên ràng buộc thành `ck_field_defs_*`; thêm record-access/04 vào Blocked by vì R2.5 đọc `studio.actor_boundary_fields`.
- 2026-10-24 (agent): vòng sửa 4: Blocked by thêm tenant-rbac/02 theo danh sách cạnh của vòng này, vì trigger của bước 1 gọi `platform.bump_access_version()` mà ticket đó tạo; cạnh này nói thẳng điều trước đây chỉ có qua tenant-rbac/04.
