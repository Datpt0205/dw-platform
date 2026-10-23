# 03 — RecordService: tạo, đọc, sửa, xóa mềm, trường duy nhất và upsert

Status: needs-info (DO-35)
Blocked by: 02, .claude/plans/studio/record-access/issues/03-policy-ban-ghi-va-mac-dinh-truy-cap.md, .claude/plans/studio/field-security/issues/01-mo-hinh-bao-mat-truong.md, .claude/plans/studio/app-standards/issues/02-khoa-chong-lap-gan-nguoi-goi.md, .claude/plans/studio/app-standards/issues/03-quy-uoc-api-danh-sach-va-sua.md, .claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md
Area: studio
Yêu cầu: R3.4, R4.3, R4.4, R4.5, R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.7, R5.8, R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7, R6.8, R7.1, R7.2, R7.3, R7.4, R7.5, R7.6, R7.7, CO1, CO7, CO8, CO9, CO10, CO11, CO12, CO13, CO14, CO15, CO16, CO17, CO18, CO20, CO22

## Mục tiêu

Một đường ghi duy nhất cho bản ghi (R5), ép kiểu và chuẩn hóa một lần (R6), và trường duy nhất cùng Tạo hoặc cập
nhật để quy trình Tiếp nhận lead kiểm trùng theo số điện thoại rồi email mà không lộ bản ghi trùng (R7, YC95).
Route REST, bước quy trình (`RecordsPort` của workflow-nodes/04) và công cụ agent (`ObjectDataPort` của
tools-and-skills/03) gọi cùng một `RecordService`.

## Việc cần làm

1. `RecordService` trong `dw_studio.records.application`, theo đúng thứ tự của ADR-0107 (Proposed) quyết định 3:
    - kiểm quyền hành động đối tượng `obj.<api_name>.create|read|update|delete` (tenant-rbac/04); thiếu → 403
      `permission_denied` trước khi đọc bản ghi nào;
    - `pg_advisory_xact_lock_shared` theo (công ty, đối tượng), rồi đọc `schema_version` và snapshot định nghĩa;
    - ép kiểu và chuẩn hóa: NFC cho chữ, email chữ thường, số điện thoại E.164, số `exact` và tiền thành bigint
      bằng giá trị nhân `10^scale` (số `exact` và tiền đến dưới dạng chuỗi JSON); port từ si-platform
      `si_metadata/values.py` ở commit ghim, có header nguồn gốc và test của nó, nếu DO-03 cho phép (Q6 của spec),
      không thì viết lại theo cùng bộ test vector;
    - kiểm bắt buộc, độ dài, danh sách chọn; gom mọi lỗi của một lần lưu vào `errors[]` với con trỏ
      `/fields/<api_name>`;
    - quyết định trường qua `resolve_field_access` (field-security/01): trường Đã ẩn hay không tồn tại → cùng 422,
      `errors[].code` `unknown_field`, cùng thông điệp; trường đọc được mà không sửa được → 403 `field_not_editable`;
    - quyền trên bản ghi do RLS của record-access/03 quyết, với `app.tenant_id`, `app.user_id`, `app.actor_kind` đặt
      đầu mỗi giao dịch (ADR-0105 (Proposed) quyết định 1, 6); mọi câu lệnh nêu `tenant_id = :tenant`;
    - ghi bản ghi; outbox; audit; `create_key`.
2. Khi tạo: `owner_kind` `user`, `owner_id` là người gọi (hay principal của lượt chạy), `workspace_id` là workspace
   đang làm việc; policy chèn của record-access/03 đòi cả hai trong tầm tạo. `version` bắt đầu 1, mỗi lần sửa cộng 1.
   `create_key` do đường gọi đặt: route lấy từ `Idempotency-Key` gắn người gọi (app-standards/02), bước quy trình
   dùng khóa `wf:{run_id}:{node_id}:{iteration_path}` của ADR-0108 (Proposed) quyết định 6; trùng `create_key`
   trả bản ghi đã có.
3. Route trong nhóm `/api/v1/studio` (`dw_studio.records.presentation`), lỗi theo problem+json của app-standards:
    - `POST /api/v1/studio/objects/{api_name}/records` → 201, `ETag: "<version>"`, `Location`; `Idempotency-Key`
      không bắt buộc.
    - `GET /api/v1/studio/objects/{api_name}/records/{record_id}` → `id`, `object`, `version`, `etag`,
      `owner {kind, id}`, `workspace_id`, `created_*`, `updated_*`, `deleted_at`, `fields` (chỉ trường đọc được),
      `hidden_fields` (ADR-0106 (Proposed) quyết định 4), `permissions` (`update`, `delete`); `Cache-Control: no-store`.
    - `PATCH .../records/{record_id}`: JSON Merge Patch trên `name` và `fields` (`application/merge-patch+json` và
      `application/json`); `If-Match` so mạnh, lệch → 412 `precondition_failed`; `owner`, `workspace_id` → 422
      `field_not_writable`; thuộc tính chỉ để đọc bị bỏ qua.
    - `DELETE .../records/{record_id}`: xóa mềm (`deleted_at`, `deleted_by`), `If-Match` như trên, trả bản ghi có
      `deleted_at`.
    - `POST .../records/upsert`: thân `{match_field, name, fields}`, `match_field` là một trường `is_unique`;
      `Idempotency-Key` bắt buộc (thiếu → 422 `idempotency_key_required`); 201 `created: true` hay 200
      `created: false`.
    - Không tồn tại, công ty khác, không đọc được → cùng 404; đọc được mà không sửa, xóa được → 403.
    - Không route nào vào `SUPPORT_ALLOWED_ROUTES` (`apps/api/src/dw_api/bootstrap/wiring.py:110`).
4. Trường duy nhất và Tạo hoặc cập nhật:
    - giá trị `is_unique` lưu ở slot `u` đã chuẩn hóa; vi phạm UNIQUE từng phần của slot `u` (nhận theo tên ràng buộc)
      → 409 `duplicate_value`, con trỏ `/fields/<api_name>`, không id bản ghi, không giá trị (ADR-0105 (Proposed)
      quyết định 8);
    - Tạo hoặc cập nhật bằng
      `INSERT ... ON CONFLICT (tenant_id, object_id, uNN) WHERE uNN IS NOT NULL AND deleted_at IS NULL DO UPDATE`,
      theo số đo ON CONFLICT dưới policy theo lệnh của ticket 01; RLS từ chối dòng đang có → cùng 409
      `duplicate_value`;
    - audit `studio.record.duplicate_refused` (`object_id`, khóa trường, người gọi) ghi trong giao dịch riêng sau khi
      lần ghi bị hoàn tác;
    - giới hạn số lần 409 `duplicate_value` theo (người gọi, đối tượng) trong Valkey, khóa
      `ratelimit:dup:<tenant_id>:<user_id>:<object_id>`, ngưỡng và cửa sổ theo trả lời Q3 (DO-35); vượt → 429 kèm
      `Retry-After`.
5. Trong giao dịch của mỗi lần ghi: outbox `studio.record.created`, `studio.record.updated`, `studio.record.deleted`
   payload v1 (`object_id`, `record_id`, `version`, `workspace_id`, `owner_kind`, `owner_id`, `changed_fields` là khóa
   trường, `channel` là `api`, `workflow` hay `agent`, `run_id`, `operation_id`, `run_mode`), không giá trị trường;
   audit `studio.record.created`, `studio.record.updated`, `studio.record.deleted` với `details` chỉ gồm khóa trường
   và `version`.
6. Chế độ chạy lấy từ `RunMode` của lượt chạy (tenant-config/03): ở `simulate` và `test`, service kiểm đủ và trả bản
   ghi giả định (id mới không lưu, `version` dự kiến), không dòng, không outbox, không audit (ADR-0111 (Proposed);
   DO-26 tạm theo khuyến nghị).
7. Ở `build_studio`, gốc ghép đáp `RecordsPort` (workflow-nodes/04) và `ObjectDataPort` (tools-and-skills/03) bằng
   `RecordService`; chuyển `GET /api/v1/studio/objects` và describe của ticket 02 sang đọc qua cùng service.
8. Test kiến trúc: chuỗi SQL nhắc `studio.records` trong mã Python ngoài `dw_studio.records.adapters` → đỏ; hợp đồng
   import-linter: chỉ gốc ghép import adapter bản ghi.

## Tiêu chí chấp nhận

- [ ] R5.1: `POST` hợp lệ → 201, `ETag: "1"`, `owner` là người gọi, `workspace_id` là workspace đang làm việc.
- [ ] R5.2 (CO11): một lần ghi thành công có đúng một sự kiện và một audit, chuỗi giá trị đã ghi không có trong
      `details` của audit; ép lỗi khi chèn outbox → không bản ghi, không audit; tách outbox ra giao dịch khác → test
      đỏ.
- [ ] R5.3 (CO12): hai `POST` song song cùng `create_key` → một dòng, hai phản hồi cùng `id`; gỡ UNIQUE `create_key`
      → test đỏ.
- [ ] R5.4 (CO13): service trong lượt `simulate` và lượt `test` trả bản ghi giả định; số dòng của `studio.records`,
      outbox và `platform.audit_events` không đổi; gỡ bước chế độ chạy → test đỏ.
- [ ] R5.5: `DELETE` đặt `deleted_at`, `deleted_by`, dòng còn; `GET` theo id trả `deleted_at`.
- [ ] R5.6 (CO10): thêm một mô-đun thử có chuỗi SQL `studio.records` ngoài `dw_studio.records.adapters` → test kiến
      trúc đỏ.
- [ ] R5.7 (CO9): `GET`, `PATCH`, `DELETE` với id không tồn tại và id có mà người gọi không đọc được → cùng 404, cùng
      thông điệp.
- [ ] R5.8: người có đọc mà không có sửa gọi thẳng `PATCH` (không qua giao diện) → 403, `version` không đổi.
- [ ] R3.4 (CO8): người thiếu `obj.<api_name>.read` gọi `GET` một id có và một id không có → cùng 403
      `permission_denied`.
- [ ] R4.3 (CO1): người của công ty A `GET`, `PATCH`, `DELETE` một bản ghi của công ty B → 404, dòng của B không đổi.
- [ ] R4.4 (CO20): công ty có bản ghi ở hai workspace → offboarding xuất số dòng bằng số dòng đã tạo, sau purge còn 0;
      cấp SELECT trên `studio.records_p0` cho `dw_app` → test thấy đếm đôi, đỏ.
- [ ] R4.5 (CO22): yêu cầu có header `X-DW-Support-Grant` hợp lệ gọi `GET .../records/{record_id}` → 403
      `support_context_not_allowed`; thêm route đó vào `SUPPORT_ALLOWED_ROUTES` → test đỏ.
- [ ] R6.1: thân có ba lỗi (kiểu, bắt buộc, danh sách chọn) → 422 với đúng ba phần tử `errors[]`, mỗi phần tử một con
      trỏ `/fields/<api_name>`.
- [ ] R6.2: "0901 234 567" lưu "+84901234567"; `A@X.VN` lưu `a@x.vn`; chuỗi NFD lưu đúng byte của NFC.
- [ ] R6.3: `"1000.5"` vào trường VND `scale` 0 → 422 có con trỏ, không ghi.
- [ ] R6.4: `"0.1"` vào trường `scale` 2 đọc lại là `"0.10"`.
- [ ] R6.5 (CO7): ghi trường lạ `khong_co` và trường Đã ẩn `phone` → cùng 422 `unknown_field`, cùng thông điệp.
- [ ] R6.6: ghi trường chỉ đọc với người gọi → 403 `field_not_editable` có con trỏ, không ghi.
- [ ] R6.7 (CO14): `PATCH` có `owner` → 422 `field_not_writable`; `dw_app` chạy `UPDATE studio.records SET owner_id`
      → permission denied.
- [ ] R6.8 (CO15): hai `PATCH` cùng `If-Match: "3"` → một 200, một 412, `version` tăng đúng 1; bỏ bước so phiên bản
      → test đỏ.
- [ ] R7.1 (CO16): tạo Lead có số đã có ở một Lead người gọi không đọc được → 409 `duplicate_value`, thân không có id
      hay số; trả id trong thân → test đỏ.
- [ ] R7.2: Tạo hoặc cập nhật lần đầu → 201 `created: true`; lần hai cùng số → 200 `created: false`, vẫn một dòng.
- [ ] R7.3 (CO17): hai lần Tạo hoặc cập nhật song song với "0901 234 567" và "+84901234567" → một dòng; cùng tên khác
      số → hai dòng; bỏ UNIQUE của slot `u` → test đỏ.
- [ ] R7.4 (CO16): Tạo hoặc cập nhật trúng bản ghi người gọi không sửa được → 409 `duplicate_value`, bản ghi không đổi.
- [ ] R7.5: audit `studio.record.duplicate_refused` chỉ có `object_id`, khóa trường và người gọi; không giá trị, không
      id bản ghi.
- [ ] R7.6 (CO18): vượt ngưỡng của Q3 → 429 có `Retry-After`, không ghi; gỡ bộ giới hạn → test đỏ.
- [ ] R7.7: Tạo hoặc cập nhật thiếu `Idempotency-Key` → 422 `idempotency_key_required`, không dòng nào.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/domain/outbox.py:33-35`; spec: R5.2.
- `packages/python/dw_kernel/src/dw_kernel/errors.py:20`; spec: R3.4.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:68-86`; spec: R4.4.
- `apps/api/src/dw_api/dependencies/auth.py:101`; `apps/api/src/dw_api/bootstrap/wiring.py:110`; spec: R4.5.
- `.claude/plans/studio/discovery/issues/10-dedupe-and-upsert.md:10-15`; spec: R7.
- ADR-0107 (Proposed) quyết định 3, 8; ADR-0105 (Proposed) quyết định 3, 8; ADR-0106 (Proposed) quyết định 4;
  ADR-0108 (Proposed) quyết định 3, 4, 6; ADR-0111 (Proposed).

## Comments
