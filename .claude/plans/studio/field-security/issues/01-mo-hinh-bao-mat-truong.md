# 01 — Mô hình bảo mật trường và hàm quyết định duy nhất visible_fields

Status: needs-info (DO-34)
Blocked by: .claude/plans/studio/tenant-rbac/issues/04-quyen-doi-tuong-va-truong-co-do-sau.md, .claude/plans/studio/compliance-pdpl/issues/01-tu-vung-du-lieu-ca-nhan.md, .claude/plans/studio/custom-objects/issues/02-luoc-do-dinh-nghia-object.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R1.6, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, FS1, FS7, FS11, FS12

## Mục tiêu

Mỗi trường có `access_mode` (`open` hoặc `secured`), dữ liệu cá nhân `secured` mặc định và nhạy cảm luôn `secured`
(R1); một hàm thuần `resolve_field_access` là chủ duy nhất của quyết định "người gọi thấy hay sửa trường nào", cộng
dồn quyền trường qua mọi vai, giao với giới hạn dữ liệu, không ẩn được trường duy nhất với người ghi (R2). Đủ cho vai
Marketing và vai Sales trên `lead`: Sales chưa được cấp không đọc được `phone`, `email`. Quyết định owed DO-34 (luật sư
và người đặt yêu cầu xác nhận dữ liệu cá nhân cơ bản, kể cả họ tên, `secured` mặc định và admin mở được kèm audit).

## Việc cần làm

1. Một revision Alembic (id ngẫu nhiên do `alembic revision -m "..."` sinh) sửa `studio.field_defs` (custom-objects
   ticket 02 tạo), chép nguyên văn ràng buộc từ mục Dữ liệu của spec:
    - thêm `access_mode text NOT NULL DEFAULT 'open'` với `ck_fields_access_mode CHECK (access_mode IN ('open','secured'))`;
    - thêm `ck_fields_sensitive_is_secured CHECK (pd_category <> 'sensitive' OR access_mode = 'secured')`;
    - trigger `BEFORE INSERT` trên `studio.field_defs` đặt `access_mode = 'secured'` khi `pd_category <> 'none'` (trường
      dữ liệu cá nhân không tạo ra ở `open` được);
    - trigger `AFTER UPDATE OF access_mode` gọi `platform.bump_access_version()` của tenant-rbac ticket 02;
    - `dw_app` thêm `access_mode` vào tập cột định nghĩa được UPDATE; `dw_provisioner`, `dw_agent_ro` không gì mới.
    - Downgrade gỡ cột, hai CHECK và hai trigger, giữ `studio.field_defs`.
2. Cùng revision đăng ký khóa `studio.field_security.manage` (loại `tenant`, mức rủi ro `elevated`) vào danh mục quyền
   của tenant-rbac ticket 01 (ADR-0104 (Proposed)); vai nào giữ khóa là việc của tenant-rbac.
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
4. Route `PUT /api/v1/studio/objects/{api_name}/fields/{field}/security` trong nhóm `/api/v1/studio`,
   `Cache-Control: no-store`: khóa `studio.field_security.manage` mức `tenant`, `Idempotency-Key` (app-standards
   ticket 02), thân `{"access_mode": "open" | "secured"}`; trả 200 với `access_mode` và `fls_version`; 403
   `permission_denied`; 404 khi đối tượng hay trường không có trong tenant người gọi; 422 `sensitive_field_cannot_open`
   khi mở trường nhạy cảm (trước khi chạm DB); ghi audit và outbox `studio.field_security.changed` chỉ mang id đối
   tượng, id và khóa trường, `access_mode` trước và sau, người làm, trong một giao dịch.

## Tiêu chí chấp nhận

- [ ] R1.1: `studio.field_defs` có đúng một `access_mode` mỗi trường; giá trị ngoài `open`, `secured` bị từ chối theo
      tên `ck_fields_access_mode`.
- [ ] R1.2 (FS1): tạo trường `pd_category = 'basic'` → `access_mode = 'secured'`; đổi trigger để trường `pd` khác
      `none` giữ `open` → test đỏ.
- [ ] R1.3 (FS11): `UPDATE studio.field_defs SET access_mode = 'open'` cho trường `pd_category = 'sensitive'` → 23514
      `ck_fields_sensitive_is_secured`, không đổi dòng; gỡ CHECK → test đỏ.
- [ ] R1.4 (FS12): người giữ `studio.field_security.manage` mở một trường `basic` → `access_mode` đổi và đúng một
      audit `studio.field_security.changed` chỉ mang id và khóa trường trong một giao dịch; lỗi sau khi ghi audit →
      giao dịch lùi, 0 audit.
- [ ] R1.5 (FS12): người gọi thiếu `studio.field_security.manage` gọi `PUT .../security` → 403 `permission_denied`,
      `access_mode` không đổi, 0 audit.
- [ ] R1.6 (FS12): đổi `access_mode` commit ở giao dịch A → yêu cầu đầu tiên sau đó của người gọi dùng giá trị mới;
      gỡ trigger `platform.bump_access_version()` trên `studio.field_defs` → test đỏ.
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
- `docs/adr/0106-field-access-follows-personal-data-category.md:52-59`; spec: R1, R2.
- `.claude/plans/studio/custom-objects/issues/02-luoc-do-dinh-nghia-object.md:27`; spec: R1.2 (`pd_category` của `studio.field_defs`).
- `.claude/plans/studio/tenant-rbac/issues/04-quyen-doi-tuong-va-truong-co-do-sau.md:36-39`; spec: R2.4 (`fld.*` qua `platform.effective_grants`).
- `.claude/plans/studio/record-access/spec.md:356`; spec: R2.5 (`studio.actor_boundary_fields`).

## Comments

- 2026-10-23 (agent): `Blocked by` trỏ tới compliance-pdpl ticket 01 (từ vựng `dw_kernel.personal_data`) đang viết cùng đợt; tệp sẽ có khi đợt này xong.
