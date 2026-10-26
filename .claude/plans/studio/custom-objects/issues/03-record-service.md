# 03 — RecordService: tạo, đọc, sửa, xóa mềm, trường duy nhất, upsert và describe theo người gọi

Status: needs-triage
Blocked by: 02, .claude/plans/studio/telemetry-and-audit/issues/01-otel-khong-noi-dung-va-metric.md, .claude/plans/studio/record-access/issues/03-policy-ban-ghi-va-mac-dinh-truy-cap.md, .claude/plans/studio/field-security/issues/01-mo-hinh-bao-mat-truong.md, .claude/plans/studio/app-standards/issues/02-khoa-chong-lap-gan-nguoi-goi.md, .claude/plans/studio/app-standards/issues/03-quy-uoc-api-danh-sach-va-sua.md, .claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md, .claude/plans/studio/usage-and-limits/issues/05-cong-gioi-han-toc-do-theo-tien-trinh.md
Area: studio
Yêu cầu: R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R4.3, R4.4, R4.5, R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.7, R5.8, R5.9, R5.10, R5.11, R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7, R6.8, R7.1, R7.2, R7.3, R7.4, R7.5, R7.6, R7.7, R7.8, CO1, CO7, CO8, CO9, CO10, CO11, CO12, CO13, CO14, CO15, CO16, CO17, CO18, CO20, CO22, CO25, CO26

## Mục tiêu

Một đường ghi duy nhất cho bản ghi (R5), ép kiểu và chuẩn hóa một lần (R6), và trường duy nhất cùng Tạo hoặc cập
nhật để quy trình Tiếp nhận lead kiểm trùng theo số điện thoại rồi email mà không lộ bản ghi trùng (R7, YC95).
Route REST, bước quy trình (`RecordsPort` của workflow-nodes/04) và công cụ agent (`ObjectDataPort` của
tools-and-skills/03) gọi cùng một `RecordService`. Describe, danh mục đối tượng và bộ chiếu lược đồ theo quyền của
người gọi (R3) đến ở đây, sau khóa đọc đối tượng của tenant-rbac/04 và `resolve_field_access` của field-security/01.

## Việc cần làm

1. `RecordService` trong `dw_studio.records.application`, theo đúng thứ tự của ADR-0107 (Accepted) quyết định 3:
    - kiểm quyền hành động đối tượng `obj.<api_name>.create|read|update|delete` (tenant-rbac/04); thiếu → 403
      `permission_denied` trước khi đọc bản ghi nào;
    - `pg_advisory_xact_lock_shared` theo (công ty, đối tượng), rồi đọc `schema_version` và snapshot định nghĩa;
    - ép kiểu và chuẩn hóa: NFC cho chữ, email chữ thường, số điện thoại E.164, số `exact` và tiền thành bigint
      bằng giá trị nhân `10^scale` (số `exact` và tiền đến dưới dạng chuỗi JSON); port từ si-platform
      `si_metadata/values.py` theo DO-03.2 (a): thỏa thuận viết của PO và SA si-platform, ghim commit mỗi lần, dòng đầu
      `Ported from si-platform`, không đồng bộ, kèm test của nó; thỏa thuận chưa có trước P1 thì viết lại theo cùng bộ
      test vector;
    - kiểm bắt buộc, độ dài, danh sách chọn; gom mọi lỗi của một lần lưu vào `errors[]` với con trỏ
      `/fields/<api_name>`;
    - quyết định trường qua `resolve_field_access` (field-security/01): trường không tồn tại → 422 `validation_failed`
      với `errors[].code` `unknown_field`; trường Đã ẩn hay chỉ đọc → 403 `field_not_editable` có con trỏ (tên trường
      Đã ẩn là công khai, giá trị thì không; `B:custom-objects:R6.5~field-security:R3.3`);
    - quyền trên bản ghi do RLS của record-access/03 quyết, với `app.tenant_id`, `app.user_id`, `app.actor_kind` đặt
      đầu mỗi giao dịch (ADR-0105 (Accepted) quyết định 1, 6); mọi câu lệnh nêu `tenant_id = :tenant`;
    - ghi bản ghi; outbox; audit; `create_key`.
2. Khi tạo: `owner_kind` `user`, `owner_id` là người gọi (hay principal của lượt chạy), `workspace_id` là workspace
   đang làm việc; policy chèn của record-access/03 đòi cả hai trong tầm tạo. `version` bắt đầu 1, mỗi lần sửa cộng 1.
   `create_key` do đường gọi đặt: route ghép `http:`, `caller_ref` của app-standards/02 và `Idempotency-Key`, nên khóa gửi qua HTTP không bao giờ
   trùng khóa `wf:` của một lượt chạy hay khóa của người gọi khác (H-34; ca: hai người gọi cùng `Idempotency-Key`
   → hai bản ghi, một khóa `wf:` của một lượt chạy gửi làm `Idempotency-Key` → bản ghi mới, không trả bản ghi của
   lượt đó; bỏ tiền tố → test đỏ), bước quy trình
   dùng khóa `wf:{run_id}:{node_id}:{iteration_path}` của ADR-0108 (Accepted) quyết định 6; trùng `create_key`
   trả bản ghi đã có.

    Khóa của lệnh sửa từ một Bước (R5.9 tới R5.11; V4.30): bảng `studio.record_write_keys` theo mục Dữ liệu của spec
    (PK `(tenant_id, write_key)`, `write_key` CHECK bắt đầu bằng `wf:`, FK ghép `(tenant_id, record_id)` tới
    `studio.records` ON DELETE CASCADE có index, `op` CHECK `update`, `upsert`, `assign`, `version`, `created`, ba cột
    người phụ trách cho `assign`, `actor_id`, `created_at`), RLS ENABLE và FORCE với policy tenant cộng policy RESTRICTIVE
    `tenant AND (actor_id = app.user_id OR scope)`, một dòng lý do trong danh sách bảng toàn tenant của
    `test_rls_coverage.py`, quyền `dw_app` SELECT, INSERT, DELETE và không UPDATE (assert ở
    `dw_platform/tests/integration/test_privileges.py`), một bước xóa trong sổ bước của lane `offboarding` (H-2) và mảnh
    `configs/policies/retention.d/studio.record_write_keys.yaml` 31 ngày (`purger: row_delete`, `enforced: true`) trong
    cùng revision, cùng bộ xóa theo dòng đăng ký vào sổ bộ xóa `RetentionPurgerRegistry` của telemetry-and-audit/01
    (H-35); khóa không phải dữ liệu cá nhân nên mảnh không chờ cổng E3. `RecordService.update` và
    nhánh sửa của `upsert` nhận `write_key` chỉ từ `RecordsPort` (không route nào nhận khóa `wf:`): trước khi ép kiểu,
    tra khóa; có dòng thì trả `{record_id, version, created, replayed: true}` mà không ghi; không có thì ghi bản ghi,
    outbox, audit và dòng khóa trong một giao dịch; INSERT khóa vướng PK vì dòng của chủ thể khác (không thấy qua RLS) →
    409 `idempotency_conflict`. Ở `simulate` không ghi dòng khóa nào (R5.4). `replayed` là trường kết quả mà
    workflow-engine:R4.22 dựa vào; workflow-nodes/04 chạy bộ contract test của `RecordsPort` (H-30) trên service này.

3. Route trong nhóm `/api/v1/studio` (`dw_studio.records.presentation`), lỗi theo problem+json của app-standards:
    - `POST /api/v1/studio/objects/{api_name}/records` → 201, `ETag: "<version>"`, `Location`; `Idempotency-Key`
      không bắt buộc.
    - `GET /api/v1/studio/objects/{api_name}/records/{record_id}` → `id`, `object`, `version`, `etag`,
      `owner {kind, id}`, `workspace_id`, `created_*`, `updated_*`, `deleted_at`, `fields` (chỉ trường đọc được),
      `hidden_fields` (ADR-0106 (Accepted) quyết định 4), `permissions` (`update`, `delete`); `Cache-Control: no-store`.
    - `PATCH .../records/{record_id}`: JSON Merge Patch trên `name` và `fields` (`application/merge-patch+json` và
      `application/json`); `If-Match` so mạnh, lệch → 412 `precondition_failed`; `owner`, `workspace_id` → 422
      `validation_failed` với `errors[].code` `field_not_writable` và con trỏ `/owner` hay `/workspace_id`; thuộc tính
      chỉ để đọc bị bỏ qua.
    - `DELETE .../records/{record_id}`: xóa mềm (`deleted_at`, `deleted_by`), `If-Match` như trên, trả bản ghi có
      `deleted_at`.
    - `POST .../records/upsert`: thân `{match_field, name, fields}`, `match_field` là một trường `is_unique`;
      `Idempotency-Key` bắt buộc (thiếu → 422 với `details.reason_code` `idempotency_key_required` của
      app-standards/02); 201 `created: true` hay 200 `created: false`.
    - Không tồn tại, công ty khác, không đọc được → cùng 404; đọc được mà không sửa, xóa được → 403.
    - Không route nào vào `SUPPORT_ALLOWED_ROUTES` (`apps/api/src/dw_api/bootstrap/wiring.py:110`).
4. Trường duy nhất và Tạo hoặc cập nhật:
    - giá trị `is_unique` lưu ở slot `u` đã chuẩn hóa; vi phạm UNIQUE từng phần của slot `u` (nhận theo tên ràng buộc)
      → 409 `duplicate_value`, con trỏ `/fields/<api_name>`, không id bản ghi, không giá trị (ADR-0105 (Accepted)
      quyết định 8);
    - Tạo hoặc cập nhật bằng
      `INSERT ... ON CONFLICT (tenant_id, object_id, uNN) WHERE uNN IS NOT NULL AND deleted_at IS NULL DO UPDATE`,
      theo số đo ON CONFLICT dưới policy theo lệnh của ticket 01; RLS từ chối dòng đang có → cùng 409
      `duplicate_value`;
    - audit `studio.record.duplicate_refused` (`object_id`, khóa trường, người gọi) ghi trong giao dịch riêng sau khi
      lần ghi bị hoàn tác;
    - giới hạn số lần 409 `duplicate_value` theo (tenant, người gọi, đối tượng) qua `RateLimiterPort` của
      usage-and-limits/05 (DO-49), không bộ đếm Valkey riêng; mất Valkey thì port giữ xô theo tiến trình; tối đa 20 lần
      409 trong cửa sổ trượt 10 phút (DO-35, Đạt 24/10/2026; số tạm, FOG-11 đo lại): mỗi lần 409 báo port một lần với
      khóa có kiểu (tenant, người gọi, đối tượng), và trước mỗi lần ghi lên đối tượng service hỏi port mà không tính
      lượt; đã đủ 20 → 429 kèm `Retry-After` là lúc lần 409 cũ nhất ra khỏi cửa sổ, cho mọi lần ghi của người đó lên đối
      tượng đó, trùng hay không, và audit `studio.record.duplicate_throttled` (`object_id`, người gọi; không giá trị,
      không id bản ghi) trong giao dịch riêng;
    - kiểm trùng của quy trình tiếp nhận chạy dưới tài khoản dịch vụ (ADR-0105 (Accepted) mục 8; DO-35).
5. Trong giao dịch của mỗi lần ghi: outbox `studio.record.created`, `studio.record.updated`, `studio.record.deleted`
   payload v1 (`object_id`, `record_id`, `version`, `workspace_id`, `owner_kind`, `owner_id`, `changed_fields` là khóa
   trường, `channel` là `api`, `workflow` hay `agent`, `run_id`, `operation_id`, `run_mode`), không giá trị trường;
   audit `studio.record.created`, `studio.record.updated`, `studio.record.deleted` với `details` chỉ gồm khóa trường
   và `version`.
6. Chế độ chạy lấy từ `RunMode` của lượt chạy (tenant-config/03): ở `simulate` và `test`, service kiểm đủ và trả bản
   ghi giả định (id mới không lưu, `version` dự kiến), không dòng, không outbox, không audit (ADR-0111 (Accepted)).
   RecordService là chỗ giả lập duy nhất cho mọi đường ghi (API, agent, bước, lane); Bước bản ghi của workflow-nodes
   chỉ chuyển `RunMode` qua `RecordsPort` (`D:custom-objects:R5.4~workflow-nodes:R5.3`); W1 chỉ mở `simulate` ở cửa chạy
   thử, nhưng service vẫn giả lập `test` như `simulate` nếu một lượt `test` tới (DO-26.1 (A)).
7. Ở `build_studio`, gốc ghép đáp `RecordsPort` (workflow-nodes/04) và `ObjectDataPort` (tools-and-skills/03) bằng
   `RecordService`; route `GET /api/v1/studio/objects` và describe của bước 9 đọc qua cùng service.
8. Test kiến trúc: chuỗi SQL nhắc `studio.records` trong mã Python ngoài `dw_studio.records.adapters` → đỏ; hợp đồng
   import-linter: chỉ gốc ghép import adapter bản ghi.
9. Describe và bộ chiếu theo người gọi (R3.1 tới R3.7, chuyển từ ticket 02 theo Quyết định 24/10/2026 của spec), trong
   nhóm `/api/v1/studio`, `Cache-Control: no-store`:
    - `GET /api/v1/studio/objects` trả đúng các đối tượng người gọi giữ `obj.<api_name>.read` (tenant-rbac/04);
    - `GET /api/v1/studio/objects/{api_name}/describe`: thiếu `obj.<api_name>.read` → 403 `permission_denied` trước khi
      đọc gì, `api_name` của công ty khác → 404; quyền trường qua `resolve_field_access` (field-security/01); trả
      `ai_description` của đối tượng và của mỗi trường đọc được với nhãn `vi`, kiểu, `access`, các cờ và lựa chọn đang
      bật, và trường Đã ẩn chỉ với `api_name`, nhãn và `access: hidden`;
    - `ObjectSchemaProjector` của ticket 02 nhận quyết định trường của người gọi: lược đồ không có trường Đã ẩn, lược
      đồ tạo, sửa chỉ có trường người gọi sửa được, và bảng `ai_description` tách riêng không có trường Đã ẩn (R3.6,
      R3.7).

## Tiêu chí chấp nhận

- [ ] R5.1: `POST` hợp lệ → 201, `ETag: "1"`, `owner` là người gọi, `workspace_id` là workspace đang làm việc.
- [ ] R5.2 (CO11): một lần ghi thành công có đúng một sự kiện và một audit, chuỗi giá trị đã ghi không có trong
      `details` của audit; ép lỗi khi chèn outbox → không bản ghi, không audit; tách outbox ra giao dịch khác → test
      đỏ.
- [ ] R5.3 (CO12): hai `POST` song song cùng `create_key` → một dòng, hai phản hồi cùng `id`; gỡ UNIQUE `create_key`
      → test đỏ.
- [ ] R5.4 (CO13): service trong lượt `simulate` và lượt `test` trả bản ghi giả định; số dòng của `studio.records`,
      outbox và `platform.audit_events` không đổi; gỡ bước chế độ chạy → test đỏ.
- [ ] R5.9 (CO26): một Bước `update` qua `RecordsPort` với khóa `wf:` → một dòng `studio.record_write_keys` cùng
      giao dịch với bản ghi, outbox và audit; ép lỗi khi chèn audit → không bản ghi đổi và không dòng khóa; ghi dòng khóa
      trong giao dịch riêng → test đỏ.
- [ ] R5.10 (CO26): giết worker sau commit của lần sửa và trước checkpoint, chạy lại Bước cùng khóa với đầu vào đã đổi
      → kết quả của lần đầu với `replayed: true`, `version` tăng một lần, một sự kiện `studio.record.updated`, một audit,
      giá trị của lần đầu giữ nguyên; gỡ bước tra khóa → lần chạy lại sửa lần hai, test đỏ.
- [ ] R5.11 (CO26): cùng khóa `wf:` từ một chủ thể khác → 409 `idempotency_conflict`, không dòng nào đổi; chủ thể khác
      SELECT `studio.record_write_keys` → 0 dòng; gỡ policy RESTRICTIVE theo chủ thể → chủ thể khác đọc được dòng, test
      đỏ.
- [ ] R5.9: mảnh lưu giữ của `studio.record_write_keys` đặt 30 ngày, bằng hạn chót của lượt chạy → test so hai số đỏ.
- [ ] R5.5: `DELETE` đặt `deleted_at`, `deleted_by`, dòng còn; `GET` theo id trả `deleted_at`.
- [ ] R5.6 (CO10): thêm một mô-đun thử có chuỗi SQL `studio.records` ngoài `dw_studio.records.adapters` → test kiến
      trúc đỏ.
- [ ] R5.7 (CO9): `GET`, `PATCH`, `DELETE` với id không tồn tại và id có mà người gọi không đọc được → cùng 404, cùng
      thông điệp.
- [ ] R5.8: người có đọc mà không có sửa gọi thẳng `PATCH` (không qua giao diện) → 403, `version` không đổi.
- [ ] R3.1: describe cho người đọc được trả `ai_description` của đối tượng và mỗi trường với nhãn `vi`,
      `ai_description`, kiểu, `access`, các cờ và lựa chọn đang bật; lựa chọn đã tắt không có.
- [ ] R3.2 (CO7): người gọi mà `phone` Đã ẩn gọi describe → `phone` chỉ có `api_name`, nhãn và `access: hidden`, không
      kiểu, cờ hay lựa chọn; lược đồ truy vấn của bộ chiếu không có `phone`.
- [ ] R3.3: người của công ty B gọi describe với `api_name` chỉ công ty A có → 404.
- [ ] R3.4 (CO8): người thiếu `obj.<api_name>.read` gọi describe, `GET` một id có và một id không có → cùng 403
      `permission_denied`.
- [ ] R3.5: `GET /api/v1/studio/objects` trả đúng các đối tượng người gọi giữ khóa đọc, không thừa không thiếu.
- [ ] R3.6: lược đồ tạo của bộ chiếu không có trường người gọi không sửa được; lược đồ truy vấn không có trường Đã
      ẩn; `schema_version` tăng → lược đồ mới.
- [ ] R3.7 (CO25): trường Đã ẩn với người gọi không có `ai_description` ở describe lẫn bảng `ai_description` của bộ
      chiếu; trả `ai_description` của trường Đã ẩn → test đỏ.
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
- [ ] R6.5: ghi trường lạ `khong_co` → 422 `validation_failed` với `errors[].code` `unknown_field` và con trỏ
      `/fields/khong_co`, không ghi.
- [ ] R6.6 (CO7): ghi trường chỉ đọc hay trường Đã ẩn `phone` với người gọi → 403 `field_not_editable` có con trỏ, không
      ghi; giá trị của `phone` không có trong thân lỗi.
- [ ] R6.7 (CO14): `PATCH` có `owner` → 422 `validation_failed` với `errors[].code` `field_not_writable` và con trỏ
      `/owner`, không ghi; `dw_app` chạy `UPDATE studio.records SET owner_id` → permission denied.
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
- [ ] R7.6 (CO18): một người gọi nhận 20 lần 409 `duplicate_value` trên `mkt_lead` trong 10 phút → lần thứ 20 vẫn là
      409; lần ghi kế tiếp, trùng hay không, → 429 có `Retry-After`, không ghi; sau khi lần 409 cũ nhất ra khỏi cửa sổ
      10 phút → ghi lại được; người gọi khác, hay cùng người trên đối tượng khác, không bị chặn; gỡ lời gọi
      `RateLimiterPort` → test đỏ.
- [ ] R7.7: Tạo hoặc cập nhật thiếu `Idempotency-Key` → 422 với `details.reason_code` `idempotency_key_required`,
      không dòng nào.
- [ ] R7.8 (CO18): mỗi lần 429 vì giới hạn dò trùng → đúng một audit `studio.record.duplicate_throttled` chỉ có
      `object_id` và người gọi, không giá trị, không id bản ghi; gỡ ghi audit → test đỏ.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/domain/outbox.py:33-35`; spec: R5.2.
- `packages/python/dw_kernel/src/dw_kernel/errors.py:20`; spec: R3.4.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:68-86`; spec: R4.4.
- `apps/api/src/dw_api/dependencies/auth.py:101`; `apps/api/src/dw_api/bootstrap/wiring.py:110`; spec: R4.5.
- `.claude/plans/studio/discovery/issues/10-dedupe-and-upsert.md:10-15`; spec: R7.
- ADR-0107 (Accepted) quyết định 3, 8; ADR-0105 (Accepted) quyết định 3, 8; ADR-0106 (Accepted) quyết định 4;
  ADR-0108 (Accepted) quyết định 3, 4, 6; ADR-0111 (Accepted).
- spec: R5.9, R5.10, R5.11, CO26 (V4.30 mục 10); workflow-engine:R4.22, R5.22; workflow-nodes:R5.1.

## Comments

- 2026-10-23 (agent): DO-35 (a), DO-49 (a), DO-03.2 (a), DO-26.1 (A) và `B:custom-objects:R6.5~field-security:R3.3` (a) đã có lời đáp (Đạt, 23/10/2026). Còn needs-info vì ngưỡng và cửa sổ của R7.6 chưa có số (Q3 của spec). Thêm usage-and-limits/05 (`RateLimiterPort` W1) vào Blocked by theo DO-49.
- 2026-10-24 (agent): Q3 (DO-35) có số (Đạt, 24/10/2026; tạm, UNVERIFIED, chờ luật sư khi có dữ liệu thật): tối đa 20 lần 409 `duplicate_value` mỗi người, mỗi đối tượng, trong cửa sổ trượt 10 phút; vượt thì 429 và audit. Status về needs-triage; thêm R7.8. Cạnh tới usage-and-limits/05 giữ nguyên; port cần khóa có kiểu (tenant, người gọi, đối tượng), cửa sổ 10 phút (`usage-and-limits:R7.2`) và lần hỏi không tính lượt (`usage-and-limits:R7.3`).
- 2026-10-24 (agent): vòng sửa 4: nhận R3.1 tới R3.6, phần trường Đã ẩn của R3.7 và CO25 từ ticket 02 (bước 9; Quyết định 24/10/2026 của spec, `I:custom-objects/02~tenant-rbac/01`), vì ticket này đã chờ field-security/01 và qua đó tenant-rbac/04; Blocked by không đổi. R6.7 thành 422 `validation_failed` với `errors[].code` `field_not_writable`, R7.7 mang `details.reason_code` `idempotency_key_required` (`B:app-standards:R1.3~custom-objects:R6.7`).
- 2026-10-25 (agent): lượt h, theo V4.30 của Đạt (mục 10): nhận R5.9 tới R5.11 và CO26, khóa `wf:` của lệnh sửa từ một Bước ghi cùng giao dịch với lần sửa và phát lại khi gặp lại (đoạn hai của bước 2); lệnh `create` đã có hành vi này qua `create_key` (bước 2), nên không đổi. Blocked by thêm telemetry-and-audit/01 vì mảnh lưu giữ của `studio.record_write_keys` theo định dạng và test phủ của ticket đó (H-1); cạnh ngoài bảng mục B, đã chạy g.py: `marketing-pilot/03` vẫn ở độ sâu 15, chuỗi dài nhất 18.
