# 03 — RecordService: tạo, đọc, sửa, xóa mềm, trường duy nhất, upsert và describe theo người gọi

Status: resolved
Blocked by: 02, .claude/plans/studio/telemetry-and-audit/issues/01-otel-khong-noi-dung-va-metric.md, .claude/plans/studio/record-access/issues/03-policy-ban-ghi-va-mac-dinh-truy-cap.md, .claude/plans/studio/record-access/issues/04-ngu-canh-actor-o-moi-cua.md, .claude/plans/studio/field-security/issues/01-mo-hinh-bao-mat-truong.md, .claude/plans/studio/app-standards/issues/02-khoa-chong-lap-gan-nguoi-goi.md, .claude/plans/studio/app-standards/issues/03-quy-uoc-api-danh-sach-va-sua.md, .claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md, .claude/plans/studio/usage-and-limits/issues/05-cong-gioi-han-toc-do-theo-tien-trinh.md
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
      `/fields/<api_name>` và `errors[].code` `required`, `invalid_type`, `max_length`, `value_not_allowed` (danh sách
      chọn) hay `scale_exceeded` (R6.3), cùng `unknown_field` cho trường không tồn tại; còn lỗi nào thì trả 422
      `validation_failed` với mọi lỗi đó và chưa xét quyền trường, theo thứ tự của ADR-0107 (Accepted) quyết 3; thân lỗi
      không nhắc giá trị nào (gate 4/11/2026 (k));
    - quyết định trường qua `resolve_field_access` (field-security/01): trường Đã ẩn hay chỉ đọc → 403
      `field_not_editable` có con trỏ (tên trường Đã ẩn là công khai, giá trị thì không;
      `B:custom-objects:R6.5~field-security:R3.3`); `name` là trường mang `pd_category` của `name_field`, nên đi qua
      cùng quyết định như mọi trường: `name` Đã ẩn với người gọi thì `GET` và danh sách trả nó trong `hidden_fields`,
      không có giá trị, và ghi `name` khi nó chỉ đọc hay Đã ẩn → 403 `field_not_editable` con trỏ `/name` (gate (g));
    - quyền trên bản ghi do RLS của record-access/03 quyết (ADR-0105 (Accepted) quyết định 1, 6). RecordService không
      đặt setting `app.*` nào: nó chạy trong giao dịch mà cửa đã gắn, cửa API Studio qua `bind_actor` loại `user` và
      `studio.ensure_principal_scope()` của record-access/03, worker và công cụ qua `bind_actor` của record-access/04;
      test kiến trúc đỏ khi một mô-đun của `dw_studio.records` chứa `set_config('app.` (gate (c)); mọi câu lệnh nêu
      `tenant_id = :tenant`;
    - ghi bản ghi; outbox; audit; `create_key`.
2. Khi tạo: `owner_kind` `user`, `owner_id` là người gọi (hay principal của lượt chạy), `workspace_id` là workspace
   đang làm việc; policy chèn của record-access/03 đòi cả hai trong tầm tạo. `version` bắt đầu 1, mỗi lần sửa cộng 1.
   Route HTTP chống lặp bằng dependency `idempotent(<khóa hành động>, operation=...)` của app-standards/02
   (`apps/api/src/dw_api/dependencies/idempotency.py`): `idempotency.once(...)` với `PendingEffect` ghi dòng
   `platform.effect_keys` trong chính giao dịch ghi bản ghi, `reread` đọc lại bản ghi dưới quyền hiện tại của người gọi
   (app-standards:R2.16, R2.29; ADR-0108 (Accepted) quyết 4), nên hai người gọi cùng một `Idempotency-Key` và khóa gửi
   lại với thân khác theo app-standards:R2.20, R2.23, không luật riêng ở đây. Route không đặt `create_key`; chỉ
   `RecordsPort` đặt nó, bằng khóa `wf:{run_id}:{node_id}:{iteration_path}` của ADR-0108 (Accepted) quyết định 6, và
   trùng `create_key` trả bản ghi đã có khi `created_by` là cùng chủ thể, 409 `idempotency_conflict` khi khác. Thay
   cách ghép `http:` của H-34 (gate 4/11/2026 (a)): một khóa `wf:` gửi qua HTTP không bao giờ chạm `create_key`.

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
    tra khóa ở cả hai chỗ một khóa `wf:` có thể nằm, dòng `studio.record_write_keys` và `create_key` của bản ghi cùng đối
    tượng; có thì trả kết quả đã lưu mà không ghi: `{record_id, version, created, replayed: true}` cộng `record` đọc lại
    dưới quyền hiện tại của chủ thể (như app-standards:R2.29), nên một Bước `upsert` của workflow-nodes/04 bước 5 chạy lại
    sau sự cố, tìm thấy bản ghi mà lần đầu đã tạo và gọi `update` cùng khóa, nhận lần tạo đó với `created: true` và không
    sửa lần hai (gate (b)); không có thì ghi bản ghi, outbox, audit và dòng khóa (hay `create_key` khi tạo) trong một giao
    dịch; `upsert` gọi với khóa `wf:` ghi khóa ở nhánh nó đi (`create_key` khi tạo, dòng `op` `upsert` khi sửa); INSERT
    khóa vướng PK vì dòng của chủ thể khác (không thấy qua RLS) → 409 `idempotency_conflict`; vướng PK vì dòng của cùng
    chủ thể (hai lần thử chạy cùng lúc) → giao dịch lùi và trả kết quả của lần thắng với `replayed: true`. Ở `simulate`
    không ghi dòng khóa nào (R5.4). `replayed` là trường kết quả mà workflow-engine:R4.22 dựa vào; workflow-nodes/04 chạy
    bộ contract test của `RecordsPort` (H-30) trên service này.

    Lane lưu giữ không thấy dòng của chủ thể khác qua policy RESTRICTIVE, nên bộ xóa đăng ký vào
    `RetentionPurgerRegistry` là hàm SECURITY DEFINER `studio.purge_expired_record_write_keys()` thuộc `dw_migrator`,
    theo tiền lệ `platform.purge_expired_effect_keys()` (`effect_key_store.py`): `search_path` cố định, EXECUTE thu khỏi
    PUBLIC và cấp cho `dw_app`, đọc hạn từ `platform.retention_terms`, thiếu dòng hạn thì thất bại và không xóa gì
    (như app-standards:R2.15), xóa ở mọi tenant dòng có `created_at` cũ hơn hạn; dọn dẹp không ghi audit, chỉ log số
    dòng (CLAUDE.md, Agent and tool rules) (gate (p)).

3. Route trong nhóm `/api/v1/studio` (`dw_studio.records.presentation`), lỗi theo problem+json của app-standards:
    - `POST /api/v1/studio/objects/{api_name}/records` → 201, `ETag: "<version>"`, `Location`; `Idempotency-Key`
      không bắt buộc.
    - `GET /api/v1/studio/objects/{api_name}/records/{record_id}` → `id`, `object`, `version`, `etag`,
      `owner {kind, id}`, `workspace_id`, `created_*`, `updated_*`, `deleted_at`, `fields` (chỉ trường đọc được),
      `hidden_fields` (ADR-0106 (Accepted) quyết định 4), `permissions` (`update`, `delete`); `Cache-Control: no-store`.
      `permissions` tính trong cùng câu SELECT từ biểu thức tầm theo lệnh mà module mẫu policy của record-access/03 dựng
      (`reach_sql(<lệnh>)`, cùng văn bản mà policy `_update`, `_delete` dùng), giao với khóa hành động đối tượng; không
      vị từ tầm nào viết lại trong Python (gate (l); failure-modes #2).
    - `PATCH .../records/{record_id}`: JSON Merge Patch trên `name` và `fields` (`application/merge-patch+json` và
      `application/json`); `If-Match` so mạnh, lệch → 412 `precondition_failed`; `owner`, `workspace_id` → 422
      `validation_failed` với `errors[].code` `field_not_writable` và con trỏ `/owner` hay `/workspace_id`; thuộc tính
      chỉ để đọc bị bỏ qua.
    - `DELETE .../records/{record_id}`: xóa mềm (`deleted_at`, `deleted_by`), `If-Match` như trên, trả bản ghi có
      `deleted_at`. Xóa mềm là một câu UPDATE, nên tầm `delete` do WITH CHECK của policy `record_access_records_update`
      quyết: dòng mới có `deleted_at` khác NULL phải nằm trong tầm `delete` của người gọi (record-access/03 bước 4,
      record-access:R2.7); người đọc và sửa được mà không có tầm `delete` (kể cả qua `public_read_write`) → WITH CHECK
      từ chối, RecordService trả 403, `deleted_at` không đổi (gate (f)). `PATCH` hay `DELETE` một bản ghi đã xóa mềm →
      404 như không tồn tại.
    - `POST .../records/upsert`: thân `{match_field, name, fields}`, `match_field` là một trường `is_unique`;
      `Idempotency-Key` bắt buộc (thiếu → 422 với `details.reason_code` `idempotency_key_required` của
      app-standards/02); 201 `created: true` hay 200 `created: false`; `match_field` không phải trường `is_unique`, hay
      thân thiếu giá trị của nó hoặc giá trị là null → 422 có con trỏ, không ghi.
    - Số `exact` và tiền đến và đi dưới dạng chuỗi thập phân JSON ở mọi cửa; một số JSON vào trường đó → 422
      `invalid_type`. `ObjectSchemaProjector` của ticket 02 (`value_schema`) đổi theo: hai kiểu này chiếu thành
      `{"type": "string", "pattern": "^-?[0-9]+(\\.[0-9]+)?$"}`, không còn `{"type": "number"}` (gate (e)).
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
    - giới hạn áp cho lần ghi có loại actor `user` (route) và `agent` (`ObjectDataPort`), không cho `workflow`
      (`RecordsPort`): quy trình Tiếp nhận lead dò trùng như việc thường ngày dưới một tài khoản dịch vụ chung, nên đếm
      nó thì 20 biểu mẫu trùng chặn việc nhận lead thật của cả công ty, còn một quy trình là định nghĩa đã qua người thứ
      hai, không phải người dò; audit `studio.record.duplicate_refused` vẫn ghi ở mọi cửa (gate (d)). Lần 429 ở cửa
      `agent` là lỗi `duplicate_throttled` mà `ObjectDataPort` trả cho công cụ, route đổi nó ra 429 kèm `Retry-After`;
    - instance `RateLimiterPort`: API dùng instance có sẵn trên `ApiContainer`; ticket này là bên dùng đầu tiên trong
      worker (`ObjectDataPort` của công cụ agent chạy ở worker), nên gắn instance của worker ở
      `apps/worker/src/dw_worker/main.py` với số tiến trình worker `DW_WORKER_REPLICAS`, bắt buộc ở profile triển khai,
      theo bước 4 của usage-and-limits/05; không module nào giữ instance toàn cục (gate (d));
    - ở `simulate` (và `test`), RecordService không hỏi ràng buộc duy nhất: kiểm trùng chỉ so với bản ghi người gọi đọc
      được, bằng một SELECT dưới RLS trên slot `u`, nên lượt thử không thành chỗ dò giá trị trên bản ghi mình không đọc
      được, không giới hạn và không dấu vết; trùng với bản ghi không đọc được không báo ở `simulate`, và `upsert` giả lập
      trả `created: true` khi không bản ghi đọc được nào khớp (gate (h));
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
   `RecordService`; route `GET /api/v1/studio/objects` và describe của bước 9 đọc qua cùng service. RecordService
   không mở giao dịch tự do: nó nhận từ cửa một nhà máy giao dịch đã gắn (`bind_tenant`, `bind_actor` và
   `studio.ensure_principal_scope()` chạy ở mỗi giao dịch nhà máy mở), và mọi giao dịch riêng của nó (audit
   `duplicate_refused`, `duplicate_throttled`, đọc lại lần thắng sau khi vướng PK) mở qua cùng nhà máy, nên giao dịch
   thứ hai mang cùng ngữ cảnh actor (lượt xác nhận (q)).
   7a. Lượt xác nhận của gate 4/11/2026 (agent, theo ủy quyền 31/10/2026), bổ sung các bước trên:
    - (r) khi tạo, một trường ghi được khi người gọi giữ `obj.<api_name>.create` và quyết định trường của
      `resolve_field_access` với hành động `create` không là Đã ẩn hay chỉ đọc; tầm sửa trên bản ghi không áp vì bản ghi
      chưa có, nên vai chỉ tạo (nhập lead) tạo được bản ghi (ADR-0106 (Accepted) quyết 3 nói về sửa); field-security/01
      cung cấp nhánh `create` đó;
    - (s) nhánh sửa của `upsert` là Merge Patch như `PATCH`: chỉ đổi trường có trong thân, kiểm bắt buộc theo hình sửa;
      upsert khớp mà không đổi giá trị nào, hay `PATCH` không đổi gì, không ghi: không tăng `version`, không sự kiện,
      không audit, trả bản ghi hiện tại (200, `created: false`);
    - (t) upsert qua route: lần gửi lại sau khi tiến trình chết giữa commit và lưu phản hồi trả 200 với bản ghi đọc lại
      và `created: false`, vì `once` của app-standards/02 không giữ `created`; phản hồi đã lưu trả nguyên status của lần
      đầu;
    - (u) `create_key` vướng UNIQUE với bản ghi người gọi không đọc được, hay của chủ thể khác → 409
      `idempotency_conflict`, không trả bản ghi;
    - (v) khóa `RateLimiterPort` của lần ghi qua `ObjectDataPort` là (tenant, chủ thể của lượt
      `coalesce(run_as_principal_id, requested_by)`, đối tượng), cùng khóa với lần ghi của chính người đó qua route khi
      chủ thể là người đó;
    - (w) payload v1 của sự kiện: `operation_id` là khóa chống lặp của lần ghi (`Idempotency-Key` hay khóa `wf:`), NULL
      khi không có; `run_id` NULL ở kênh `api`;
    - (x) `GET /api/v1/studio/objects` trả mỗi đối tượng kèm các hành động người gọi giữ (`create`, `read`, `update`,
      `delete`, `assign`) theo khóa `obj.<api_name>.<action>`, để giao diện của ticket 05 khóa nút Tạo có lý do;
    - (y) describe trả mọi lựa chọn của danh sách chọn với cờ `active`, để một bản ghi giữ lựa chọn đã tắt vẫn hiện
      nhãn; ghi một lựa chọn đã tắt → 422 `value_not_allowed` (spec R3.1 sửa cùng).
8. Test kiến trúc: chuỗi SQL nhắc `studio.records` trong mã Python ngoài `dw_studio.records.adapters` → đỏ; hợp đồng
   import-linter: chỉ gốc ghép import adapter bản ghi.
9. Describe và bộ chiếu theo người gọi (R3.1 tới R3.7, chuyển từ ticket 02 theo Quyết định 24/10/2026 của spec), trong
   nhóm `/api/v1/studio`, `Cache-Control: no-store`:
    - `GET /api/v1/studio/objects` trả đúng các đối tượng người gọi giữ `obj.<api_name>.read` (tenant-rbac/04);
    - `GET /api/v1/studio/objects/{api_name}/describe`: thiếu `obj.<api_name>.read` → 403 `permission_denied` trước khi
      đọc gì, `api_name` của công ty khác → 404; quyền trường qua `resolve_field_access` (field-security/01); trả
      `ai_description` của đối tượng và của mỗi trường đọc được với nhãn `vi`, kiểu, `access`, các cờ và lựa chọn đang
      bật, và trường Đã ẩn chỉ với `api_name`, nhãn và `access: hidden`; với `?action=create` route kiểm
      `obj.<api_name>.create` thay `obj.<api_name>.read` (thiếu → cùng 403) và tính `access` bằng
      `resolve_field_access(..., action='create')` (field-security/01, R2.7), nên vai chỉ tạo nhận biểu mẫu tạo với
      trường nó ghi được là `edit`; `action` khác `read`, `create` → 422 `validation_failed`;
    - `ObjectSchemaProjector` của ticket 02 nhận quyết định trường của người gọi: lược đồ không có trường Đã ẩn, lược
      đồ tạo chỉ có trường mà quyết định với `action` `create` cho `edit`, lược đồ sửa chỉ có trường người gọi sửa được, và bảng `ai_description` tách riêng không có trường Đã ẩn (R3.6,
      R3.7). Bộ đệm của bộ chiếu giữ lược đồ đầy đủ theo `(tenant_id, object_id, schema_version)`; phép lọc theo quyết
      định trường của người gọi chạy sau bộ đệm ở mỗi lần gọi, không bao giờ nằm trong mục đệm, nên đổi quyền trường mà
      không đổi `schema_version` có hiệu lực ở lần gọi kế tiếp (gate, MEDIUM M5);
    - describe trả thêm, cho mỗi trường đọc được, `number_mode`, `scale`, `currency_code` và `max_length` khi trường có
      chúng, để biểu mẫu của ticket 05 dựng đúng control (spec R3.1; gate ticket 05 (a)); trường Đã ẩn vẫn chỉ có
      `api_name`, nhãn và `access: hidden` (R3.2).

## Tiêu chí chấp nhận

- [ ] R5.1: `POST` hợp lệ → 201, `ETag: "1"`, `owner` là người gọi, `workspace_id` là workspace đang làm việc.
- [ ] R5.2 (CO11): một lần ghi thành công có đúng một sự kiện và một audit, chuỗi giá trị đã ghi không có trong
      `details` của audit; ép lỗi khi chèn outbox → không bản ghi, không audit; tách outbox ra giao dịch khác → test
      đỏ.
- [ ] R5.3 (CO12): hai `RecordsPort.create` song song cùng khóa `wf:` → một dòng, hai kết quả cùng `id`; gỡ UNIQUE
      `create_key` → test đỏ; hai `POST` song song cùng `Idempotency-Key` của cùng người gọi → một dòng, một dòng
      `platform.effect_keys`; tiến trình chết sau commit của lần tạo và trước `record`, gửi lại → bản ghi đã có đọc lại,
      không dòng thứ hai; bỏ `PendingEffect` khỏi giao dịch ghi → test đỏ; khóa `wf:` gửi làm `Idempotency-Key` → bản
      ghi mới, `create_key` NULL.
- [ ] R5.10 (CO26): Bước `upsert` tạo bản ghi với khóa `wf:`, chết trước checkpoint, chạy lại thấy bản ghi đó và gọi
      `update` cùng khóa → kết quả của lần tạo với `created: true`, `replayed: true`, `version` 1, một sự kiện
      `studio.record.created`, không `.updated`; bỏ phép tra `create_key` khỏi `update` → lần chạy lại sửa, test đỏ;
      lệnh `create` của chủ thể khác với khóa `wf:` của lần tạo → 409 `idempotency_conflict`, không bản ghi nào trả về.
- [ ] R5.9: thêm `set_config('app.actor_kind', ...)` vào một mô-đun của `dw_studio.records` → test kiến trúc
      đỏ; RecordService gọi trong giao dịch không gắn loại actor → 404 như không tồn tại, không lỗi khác.
- [ ] R7.6 (CO18): lần ghi qua `ObjectDataPort` (`agent`) đếm vào cùng cửa sổ, lần thứ 21 trả
      `duplicate_throttled`; lần ghi qua `RecordsPort` (`workflow`) của tài khoản dịch vụ nhận 409 lần thứ 21 trở đi, không
      bao giờ `duplicate_throttled`, mỗi lần một audit `studio.record.duplicate_refused`; worker dựng không có
      `DW_WORKER_REPLICAS` ở profile triển khai → lỗi lúc khởi động.
- [ ] R6.4: `{"amount": 1000.5}` (số JSON) vào trường tiền → 422 `invalid_type`; lược đồ tạo của bộ chiếu
      cho trường tiền có `"type": "string"`; đổi lại `"type": "number"` → test đỏ.
- [ ] R5.8: người giữ `update` qua `public_read_write`, không có tầm `delete`, gọi `DELETE` → 403, `deleted_at`
      vẫn NULL; người có tầm `delete` → 200; `PATCH` một bản ghi đã xóa mềm → 404; gỡ nhánh `delete` khỏi WITH CHECK
      của `_update` → lần xóa đầu thành công, test đỏ.
- [ ] R6.6 (CO7): `name` Đã ẩn với người gọi → `GET` có `name` trong `hidden_fields`, không giá trị;
      `PATCH {"name": ...}` → 403 `field_not_editable` con trỏ `/name`; bỏ `name` khỏi quyết định trường → test đỏ.
- [ ] R5.4 (CO13): ở `simulate`, tạo Lead với số đã có ở một Lead người gọi không đọc được → bản ghi giả định,
      không 409, không đếm vào `RateLimiterPort`; cùng số ở Lead người gọi đọc được → 409 `duplicate_value`.
- [ ] R5.8: `permissions.delete` của `GET` sai với người có `update` mà không có tầm `delete`, đúng với người có;
      thay biểu thức của module bằng một điều kiện Python → test so với policy đỏ.
- [ ] R5.9: dòng `studio.record_write_keys` 32 ngày của hai công ty và hai chủ thể → bộ xóa xóa cả hai;
      dòng 30 ngày còn; không có dòng hạn trong `platform.retention_terms` → bộ xóa lỗi, không dòng nào bị xóa; chạy bộ
      xóa bằng `dw_app` thường thay hàm definer → 0 dòng bị xóa, test đỏ.
- [ ] R6.1: thân có lỗi kiểu ở trường Đã ẩn `phone` và một trường chỉ đọc hợp lệ → 422 với lỗi của `phone`,
      không 403; thân không lỗi kiểu mà ghi `phone` Đã ẩn → 403; không thân lỗi nào chứa giá trị đã gửi.
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
- [ ] R3.1: describe trả `scale` 2 và `currency_code` `VND` của trường tiền, `number_mode` của
      trường số, `max_length` của trường chữ; không thuộc tính nào trong bốn cho trường Đã ẩn.
- [ ] R5.5: `DELETE` đặt `deleted_at`, `deleted_by`, dòng còn; `GET` theo id trả `deleted_at`.
- [ ] R5.6 (CO10): thêm một mô-đun thử có chuỗi SQL `studio.records` ngoài `dw_studio.records.adapters` → test kiến
      trúc đỏ.
- [ ] R5.7 (CO9): `GET`, `PATCH`, `DELETE` với id không tồn tại và id có mà người gọi không đọc được → cùng 404, cùng
      thông điệp.
- [ ] R5.8: người có đọc mà không có sửa gọi thẳng `PATCH` (không qua giao diện) → 403, `version` không đổi.
- [ ] R3.1: describe cho người đọc được trả `ai_description` của đối tượng và mỗi trường với nhãn `vi`,
      `ai_description`, kiểu, `access`, các cờ và mọi lựa chọn với cờ `active`; lựa chọn đã tắt có `active: false`; ghi
      lựa chọn đã tắt → 422 `value_not_allowed`.
- [ ] R5.1: vai chỉ giữ `obj.mkt_lead.read` và `create` (không `update`) tạo Lead với `name` và `phone` → 201; trường
      chỉ đọc theo quyền trường với hành động `create` → 403 `field_not_editable`.
- [ ] R7.2: upsert khớp với thân chỉ có `score` → `name` và trường khác giữ nguyên; upsert khớp không đổi giá trị nào →
      200 `created: false`, `version` không đổi, không sự kiện; tiến trình chết sau commit của một lần tạo, gửi lại →
      200 với bản ghi, một dòng.
- [ ] R3.5: `GET /api/v1/studio/objects` trả `actions` của người gọi cho mỗi đối tượng; người chỉ giữ `read` có
      `create` sai.
- [ ] R3.2 (CO7): người gọi mà `phone` Đã ẩn gọi describe → `phone` chỉ có `api_name`, nhãn và `access: hidden`, không
      kiểu, cờ hay lựa chọn; lược đồ truy vấn của bộ chiếu không có `phone`.
- [ ] R3.3: người của công ty B gọi describe với `api_name` chỉ công ty A có → 404.
- [ ] R3.4 (CO8): người thiếu `obj.<api_name>.read` gọi describe, `GET` một id có và một id không có → cùng 403
      `permission_denied`.
- [ ] R3.1: vai chỉ giữ `obj.lead.create` (không `read`, không `update`) gọi `describe?action=create` → 200, trường
      `open` `access: edit`, trường duy nhất `secured` chưa cấp `access: read`; cùng vai gọi describe không `action` →
      403; người không giữ `obj.lead.create` gọi `describe?action=create` → 403; tính `access` của `action=create` bằng
      `action` `update` → vai giữ `create` mà không giữ `update` thấy mọi trường `read`, test đỏ.
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
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk, hai subagent, vì ticket thêm
  migration và route), đọc cùng mã của ticket 02 (`65bddef`, `b92f307`), `idempotency.py`, `rate_limit.py`,
  `effect_key_store.py`: `check_plans.py` không lỗi chặn ở thư mục; 0 CRITICAL, 10 HIGH, sửa theo khuyến nghị, mỗi quyết
  định cùng `Nếu sai thì:` ở Quyết định 4/11/2026 của spec, nhãn (a)-(p) ở bước và tiêu chí: chống lặp HTTP bằng
  `once` thay `create_key` ghép `http:`; khóa `wf:` tra ở cả `create_key`; RecordService không đặt setting, chờ thêm
  record-access/04; giới hạn dò trùng không đếm `workflow`, instance của worker; tiền là chuỗi; xóa mềm qua tầm `delete`
  (record-access:R2.7); `name` qua quyết định trường; `simulate` không hỏi ràng buộc duy nhất; `permissions` từ
  `reach_sql`; bộ xóa definer của `studio.record_write_keys`.
- 2026-11-04 (agent): MEDIUM, đã sửa vì rẻ: (k) thứ tự lỗi và mã lỗi trường có tên; (M5) lọc theo người gọi sau bộ
  đệm của bộ chiếu; 422 cho `match_field` sai; 404 cho bản ghi đã xóa mềm. MEDIUM để lại: (M1) `PATCH` thiếu `If-Match`
  → 428 theo app-standards/03, không tiêu chí riêng ở đây; (M2) DO-03.2: thỏa thuận viết với si-platform chưa có, nên
  viết lại theo bộ test vector, luật cho "84901234567" và số nước ngoài theo bộ đó; (M3) audit `pd.read` khi trả giá trị
  trường `sensitive` (ADR-0106 (Accepted) quyết 5) là của field-security; (M4) `RecordsPort` có `upsert` hay không là
  của workflow-engine/03, ticket này phủ cả hai; (M6) vai chỉ có `create` mà không `read` nhận 403 theo R3.4; (M7) cặp
  không phụ thuộc với ticket 06 (`details.reason_code`) là cảnh báo giả của `check_plans.py`: một tên trường của vỏ lỗi,
  không phải tài nguyên chung.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (builder check mới trên bản đã sửa): 0 CRITICAL, 5 HIGH, sửa ở bước 7, 7a: (q) nhà máy
  giao dịch đã gắn từ cửa cho mọi giao dịch của service; (r) trường ghi được khi tạo theo `create` và quyền trường hành
  động `create`; (s) nhánh sửa của upsert là Merge Patch, lần ghi không đổi gì không ghi; (t) upsert gửi lại sau sự cố
  trả 200; (u) `create_key` của chủ thể khác → 409. Sửa luôn: (v) khóa giới hạn của cửa `agent`; (w) nghĩa của
  `operation_id`; (x) hành động của người gọi trong danh mục đối tượng (ticket 05); (y) lựa chọn đã tắt trong describe.
  Sửa của lượt này không có người đọc mới: nhận rủi ro (agent, theo ủy quyền 31/10/2026), mỗi sửa có tiêu chí đỏ được. Nếu sai thì: lỗi lộ ra khi
  dựng, ghi ở đây. Thứ tự dựng: sau 02 (đã xong), record-access/03, /04, field-security/01; trước 04, 05, 06,
  record-access/05.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): `checking-plan-consistency` của vùng studio (B:custom-objects/03~field-security/01, HIGH): (r) hứa vai chỉ tạo tạo được bản ghi, nhưng describe đòi `obj.read` và tính quyền trường như `update`, nên vai đó nhận 403 hay mọi control `disabled` ở biểu mẫu tạo của ticket 05; nay describe có biến thể `?action=create` dùng nhánh `create` của field-security/01, bộ chiếu lược đồ tạo cũng vậy, tiêu chí R3.1 mới. Nếu sai thì: một route `GET .../create-form` riêng thay tham số.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): quyết khi dựng. (D1) Tạo hoặc cập nhật là SELECT khớp dưới RLS, rồi
  `INSERT ... ON CONFLICT (tenant_id, object_id, uNN) WHERE uNN IS NOT NULL AND deleted_at IS NULL DO NOTHING`, rồi
  đọc lại và sửa có điều kiện theo phiên bản, thay một câu `DO UPDATE`: nhánh sửa là Merge Patch có quyết định trường
  hành động `update`, `changed_fields` và không ghi khi không đổi (s), mà một câu `DO UPDATE` không cho biết nhánh trước
  khi quyết; vẫn một dòng khi đua (R7.3 có test). Nếu sai thì: một câu `DO UPDATE ... WHERE` với quyết định trường tính
  trước cho cả hai nhánh. (D2) Lối vào upsert đòi `obj.<api_name>.create`; nhánh sửa đòi thêm `update`, thiếu thì 409
  `duplicate_value` như R7.4. Nếu sai thì: lối vào nhận `create` hay `update`. (D3) Ba cột của `assign` trong
  `studio.record_write_keys` là `owner_kind`, `owner_id`, `owner_workspace_id`, không `workspace_id`: một cột tên
  `workspace_id` làm bảng thành bảng hẹp theo workspace với `test_rls_coverage.py` (R9.2), trái dòng lý do bảng toàn
  tenant mà bước 2 đòi. Nếu sai thì: record-access/05 đổi tên trong revision của nó. (D4) Giá trị trường không slot nằm
  trong `data` theo khóa `field_no` (chuỗi), không theo `api_name`, vì `field_no` không dùng lại. Nếu sai thì: một
  revision chuyển khóa. (D5) Chế độ chạy là chặt hơn giữa `app.run_mode` mà `bind_actor` đọc từ dòng lượt (rỗng với
  người) và `RunMode` cửa truyền; giá trị lạ đọc là `simulate`. Người gọi, workspace của bản ghi mới và chế độ đều đọc
  từ giao dịch cửa đã gắn, không từ tham số. Nếu sai thì: chỉ tham số của cửa. (D6) Khóa hành động đối tượng đọc từ
  `platform.effective_grants` trong giao dịch, cùng lần đọc mà quyết định trường dùng (`FieldAccessService.caller()`,
  `for_actions()` mới), không từ `AccessContext.scopes`, nên cửa API, bước và công cụ hỏi cùng một câu. Nếu sai thì:
  đọc `AccessContext` ở route. (D7) Chuẩn hóa viết lại theo bộ vector (M2): chữ NFC, bỏ khoảng trắng hai đầu, rỗng là
  null; `"1.500"` vào `scale` 2 nhận (bỏ số 0 đuôi); điện thoại: `0` đầu là số trong nước, `00` và `+` là quốc tế, `84`
  trần với 9-10 số là Việt Nam, còn lại `invalid_type`. Nếu sai thì: sửa `values.py` và bộ vector. (D8) `RecordsPort`
  (workflow-nodes/04) và `ObjectDataPort` (tools-and-skills/03) chưa có ở mã: `RecordService` nhận `RecordDoor`
  (nhà máy giao dịch đã gắn), `write_key` và `run_mode`; hai ticket đó khai Protocol hẹp của mình và gốc ghép đáp
  bằng service này. Test qua cửa lượt chạy thật (`bind_actor` từ dòng `platform.worker_runs`). Nếu sai thì: service
  khai luôn hai Protocol. (D9) Lane offboarding xóa bảng khóa bằng bước mặc định (bảng có trong catalog, phạm vi
  `tenant` mở policy RESTRICTIVE, và CASCADE từ `studio.records`), không thêm bước vào sổ; test R4.4 xuất đúng một dòng
  khóa và còn 0 sau purge. Nếu sai thì: một bước riêng trong `build_purge_steps`. (D10) `GET /api/v1/studio/objects`
  trả `{items}` không phân trang (một công ty có vài đối tượng). (D11) Tạo không dùng `RETURNING` (đòi policy đọc của
  vai chỉ tạo); phản hồi là bản ghi đọc lại, hay khi người tạo không đọc được: mọi trường ẩn, không quyền. (D12) Upsert
  miễn `If-Match` (`EXEMPT_WRITES` của `test_list_and_write_conventions.py`), `Idempotency-Key` bắt buộc thay.
  (D13) `Retry-After` là số giây tới lúc lần 409 cũ nhất ra khỏi cửa sổ; port không cho thời điểm thì 600. (D14)
  Worker phụ thuộc `dw-studio` để đăng ký bộ xóa; `DW_WORKER_REPLICAS` vào hai overlay triển khai. (D15) Hạn chót 30
  ngày của lượt là `STUDIO_RUN_DEADLINE` ở `dw_kernel.run_mode`, workflow-engine:R5.22 đọc khi dựng. Nếu sai thì (D9-D15):
  sửa ở lần dựng ticket dùng nó.
- 2026-11-05 (agent): MEDIUM, chưa sửa. (M8) Instance `RateLimiterPort` của worker (`build_rate_limiter`) và
  `RecordService.schemas` chưa có người gọi sản xuất tới tools-and-skills/03 và workflow-nodes/04; failure-modes #1
  đứng mở tới đó. (M9) Một lần ghi là khoảng 12-15 câu (gắn, cài đặt, đối tượng, khóa, định nghĩa ba câu, quyết định
  trường hai câu, ghi, outbox, audit, đọc lại); đo ở lúc đóng hàng. (M10) Image worker nay cài `cel-expr-python` và
  `protobuf` (đã có ở image API): trivy image worker ở lúc đóng hàng. (M11) Thiếu `obj.<api_name>.read` trả 403 nên lộ
  rằng đối tượng có (R3.4 muốn vậy). (M12) Describe đánh dấu `name` sắp được, không lọc được; ngữ pháp lọc là của
  ticket 04.
- 2026-11-05 (agent): resolved. Revision `902ac246a9dc` (`studio.record_write_keys`, policy tenant và RESTRICTIVE
  theo chủ thể, `dw_app` SELECT/INSERT/DELETE, hàm definer `studio.purge_expired_record_write_keys()`, mảnh lưu giữ 31
  ngày đăng ký ở worker). Test: `tests/integration/test_record_service.py` 22 ca (R5.2/CO11 với outbox và audit hỏng,
  R5.3/CO12 song song, R5.9-R5.11/CO26 qua cửa lượt `workflow` thật, gate (b), (u), purge (p) hai công ty, R5.9 giao
  dịch không actor, R5.4/CO13 `simulate` và `test`, R7.2-R7.4/CO17, R7.6/CO18 `agent` đếm và `workflow` không, cửa sổ
  trượt, R5.8 (f) và (l) so với policy, R6.6 `name`, tài khoản dịch vụ và trường nhạy cảm duy nhất, R3.6, khóa chia
  sẻ, R4.4/CO20 offboarding); `apps/api/tests/integration/test_studio_records.py` 20 ca (R5.1, (r), R5.5, R4.3/R5.7
  CO1/CO9, R3.3, R3.4/CO8, R4.5/CO22, R6.1 và (k), R6.2-R6.5, R6.7/CO14, R6.8/CO15, R5.8, R5.3 khóa HTTP và gửi lại
  sau sự cố, R7.1/CO16, R7.2 (t), R7.7, R7.6/R7.8, R3.1, R3.2, R3.7/CO25, R3.5 (x)); đơn vị: giá trị (40), quét nguồn
  CO10 và (c) có mô-đun cài (3), chế độ chạy (7), hạn khóa so với hạn chót lượt (1), bộ chiếu (+2), `caller()` (+1),
  worker (4). `test_rls_coverage.py`, `test_privileges.py` (bảng, hàm definer), `test_metadata_matches_catalog.py` (bỏ
  khóa ngoại PostgreSQL tự tạo tới từng partition). `mutations/03.yaml` 31 mục; phá tay 9 (khóa đối tượng, trường chỉ
  đọc, outbox giao dịch riêng, `If-Match`, `RateLimiterPort`, `workflow` bị đếm, tra khóa ghi, `permissions.delete`,
  lược đồ tiền), cả 9 đỏ. Cổng: ruff, format, mypy 871 tệp (Windows và Linux trên bản xuất sạch), unit toàn repo phủ
  76,33%, unit Studio cũng trên Python 3.12.16 sạch; tích hợp studio cả gói cùng API studio 485 qua, platform
  (`rls_coverage`, `privileges`, `offboarding_coverage`) xanh; lint-imports 16 hợp đồng (thêm "Only a composition root
  imports the records adapter"), verify_invariants, verify_architecture, check_hygiene, `release_manifest --check`,
  `check_plans.py` vùng (23 Đạt, một Không đạt là cảnh báo va chạm có sẵn, M7); OpenAPI và kiểu TS sinh lại,
  `pnpm run typecheck` xanh. `reviewing-feature-security`: sáu ranh giới, (3) không công cụ mới, (4) `ai_description`
  chỉ là dữ liệu; `reviewing-deployment-security`: route mới sau cổng Studio, không URL ra ngoài, không bí mật,
  `DW_WORKER_REPLICAS` bắt buộc ở profile triển khai; image worker thêm gói (M10).
- 2026-11-05 (agent): nợ lúc đóng hàng: `scripts/mutate.py` cho `mutations/03.yaml` (31); `make test-integration` đầy
  đủ; P50/P95/P99 so với `37dab0b` của bảy route mới (`GET /objects`, describe, tạo, đọc, `PATCH`, `DELETE`, upsert)
  và đường ghi qua cửa lượt (`RecordService` cùng `FieldAccessService`, M9); trivy image worker (M10); `/code-review`.
- 2026-11-05 (agent, lane 2, discovery/10 (b), theo ủy quyền 31/10/2026): upsert dưới bộ policy bản ghi đầy đủ. Đã có: R7.1 `test_r7_1_co16_a_duplicate_names_the_field_and_nothing_else` (API, lối tạo, dòng ở workspace khác: 409 không id, không số), R7.4 `test_r7_4_co16_a_match_the_caller_cannot_change_is_a_plain_duplicate` (dòng đọc được, thiếu khóa `update`: phép kiểm của service, không phải policy), R7.3 đua. Thiếu: upsert trúng dòng người gọi không đọc được, và test nào đỏ khi gỡ policy. Thêm hai test vào `packages/python/dw_studio/tests/integration/test_record_service.py` (`a021a667`): (1) `test_r7_4_co16_an_upsert_onto_a_record_the_caller_cannot_read_reveals_nothing`: người giữ mọi hành động ở tầm workspace, dòng ở workspace kia; ba thân (giá trị khác, đúng giá trị đang có, số viết `+84`) → 409 `duplicate_value` chỉ con trỏ `/fields/phone`, không id, không số trong lỗi, số dòng không đổi, bản ghi `version` 1, không sự kiện mới, một audit chỉ khóa; thân không `name` → 422 `required` ở `/name` như với số không ai giữ, nên không phân biệt được. (2) `test_r7_4_co16_a_readable_match_out_of_update_reach_is_a_plain_duplicate`: đọc toàn công ty, sửa trong workspace mình → 409, bản ghi không đổi. Phá trên bản xuất sạch, revision `996c234cfde3` sửa tại chỗ, bản gốc giữ trong scratchpad, sha256 so lại sau khi trả: tầm đọc của `record_access_records_select` thành `true` → (1) đỏ (thân đúng giá trị và thân `+84` trả 200 `created: false` kèm bản ghi, thân không `name` thôi 422; thân giá trị khác vẫn 409 nhờ policy UPDATE), (2) xanh; tầm sửa của `record_access_records_update` (USING và WITH CHECK) thành `true` → (2) đỏ (bản ghi bị sửa), (1) xanh nhờ policy SELECT; chỉ USING → (2) đỏ với 403. Hai lớp giữ một luật, mỗi lớp một test (failure-modes #3); hai mục thêm vào `mutations/03.yaml` (33). Trên HEAD: 24/24 của tệp xanh. Lệch (MEDIUM, không lộ gì): upsert đúng giá trị đang có lên dòng đọc được mà ngoài tầm sửa, người gọi giữ khóa `update` → 200 `created: false`, `permissions.update` sai, không ghi, thay 409 của R7.4 (đo bằng test tạm, không giữ); với khóa `wf:` còn ghi một dòng khóa cho bản ghi không sửa được (đọc mã, `record_service.py:674`, chưa chạy). Đề xuất ở custom-objects/11 (`needs-triage`).
