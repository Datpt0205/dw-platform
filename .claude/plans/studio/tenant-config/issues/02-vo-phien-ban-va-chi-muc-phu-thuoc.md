# 02 — Vỏ phiên bản dùng chung và chỉ mục phụ thuộc ghi trong giao dịch gửi kiểm định

Status: resolved (2026-11-03, main)
Blocked by: 01, .claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md, .claude/plans/studio/org-and-principals/issues/01-khoa-don-vi-va-siet-realm.md, .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md, .claude/plans/studio/app-standards/issues/01-vo-loi-problem-json.md, .claude/plans/studio/app-standards/issues/03-quy-uoc-api-danh-sach-va-sua.md
Area: studio
Yêu cầu: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.8, R2.9, R2.10, R2.11, R2.12, R2.13, R2.14, R2.15, R2.16, R2.17, R2.18, R2.19, R2.20, R2.21, R2.22, R2.23, R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.8, TC1, TC2, TC3, TC4, TC5, TC6, TC7, TC21, TC24, TC27, TC29, TC30, TC31

## Mục tiêu

Mọi loại thành phần Studio có một vỏ phiên bản chung trong `dw_studio`: một nháp lưu bằng khóa lạc
quan, tối đa một phiên bản chưa phát hành mỗi thành phần (bản Nháp hay Bản ứng viên) cùng route tạo bản Nháp mới, bước
niêm phong cấp số không dùng lại và mã băm, như nhau cho mọi loại và không đổi giai đoạn, Nơi đang dùng ghi trong cùng
giao dịch niêm phong, chặn xóa thứ đang được dùng, và không lộ tên ngoài quyền (spec R2, R3). Route
gửi kiểm định của agent-lifecycle/03 gọi bước niêm phong này, rồi `LifecycleService` của agent-lifecycle chuyển giai
đoạn trong cùng giao dịch (`evaluating`, `awaiting_approval` với loại không có Cổng chất lượng, hay `live` ở nhánh
chỉ siết của `dw.object/v1`); ticket này không viết chuyển giai đoạn nào.

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên) trong schema `studio` của studio-skeleton/01, chép nguyên
   văn ràng buộc ở mục Dữ liệu của spec:
    - `studio.artifact_kinds`: danh mục loại của nền tảng, không có `tenant_id`; `kind text` là khóa
      chính; `has_quality_gate boolean NOT NULL`, không DEFAULT (R2.14); `dw_app` chỉ SELECT. Ticket này tạo
      bảng rỗng; mỗi spec đăng ký một loại INSERT một dòng nêu `has_quality_gate` bằng migration của nó, cùng lúc
      với mục registry (OPS-b). Test tích hợp của ticket này thêm dòng `fixture` (`has_quality_gate = true`) và
      `fixture_gateless` (`false`) bằng vai migrator qua bộ dựng của bước 8, theo module test, và gỡ khi module xong;
      migration không bao giờ chứa hai dòng đó.
    - `studio.artifacts`: `id` UUIDv7; `uq_artifacts_tenant_id_id UNIQUE (tenant_id, id)`, như
      `uq_workspaces_tenant_id_id`, đích của FK ghép `(tenant_id, <cột thành phần>)` trỏ tới thành phần: ở ticket này
      là `artifact_id` của `studio.artifact_versions`, `from_artifact_id` và `to_artifact_id` của
      `studio.dependencies` (R2.18); FK của spec khác, ví dụ `studio.agent_settings` của agent-builder hay
      `scope_artifact_id` của usage-and-limits, do spec tạo FK làm chủ cùng ca âm chéo tenant của nó; `kind` FK tới
      `studio.artifact_kinds (kind)` ON DELETE RESTRICT, có index `(kind)`; `api_name` `^[a-z][a-z0-9_]{1,39}$`, unique
      `(tenant_id, kind, api_name)` khi `deleted_at IS NULL`; FK ghép `(tenant_id, owning_workspace_id)` tới
      `platform.workspaces (tenant_id, id)` ON DELETE RESTRICT, có index `(tenant_id, owning_workspace_id)` (R2.18);
      `labels text[] NOT NULL DEFAULT '{}'` (bộ lọc `label` của danh sách đọc); `origin jsonb` NULL (domain-packs ghi
      và đọc nguồn gốc gói); `last_version_no integer NOT NULL DEFAULT 0`; `row_version integer NOT NULL`;
      `deleted_at timestamptz` NULL; `created_at`, `updated_at` `timestamptz NOT NULL`; index danh sách
      `(tenant_id, kind, updated_at DESC, id DESC)` khi lọc theo `kind`, và `(tenant_id, updated_at DESC, id DESC)`
      khi không lọc `kind` (trang `/studio`).
    - `studio.artifact_versions`: `stage` NOT NULL CHECK (`draft`, `evaluating`, `awaiting_approval`,
      `live`, `retired`), không DEFAULT; `version_no` NULL chỉ khi `stage = 'draft'`, unique
      `(artifact_id, version_no)`; một phiên bản chưa phát hành mỗi thành phần: chỉ mục duy nhất một phần trên
      `(artifact_id)` khi `stage IN ('draft', 'evaluating', 'awaiting_approval')` (R2.20), chỉ mục một Đang dùng là của
      agent-lifecycle/03 (agent-lifecycle:R1.2); `document_schema`
      `^dw\.[a-z_]+/v[0-9]+$`; `document` là jsonb object tối đa 1 MiB,
      `CHECK (document::text IS NFC NORMALIZED)`; `content_hash`, `definition_hash` khớp
      `^sha256:[0-9a-f]{64}$`, `definition_hash` NOT NULL ngoài `draft`; `row_version integer NOT NULL`;
      `artifact_id` FK ghép `(tenant_id, artifact_id)` tới `uq_artifacts_tenant_id_id` ON DELETE CASCADE, có index
      `(tenant_id, artifact_id)`; `uq_artifact_versions_tenant_id_id UNIQUE (tenant_id, id)`, đích của FK ghép
      `(tenant_id, <cột phiên bản>)` trỏ tới phiên bản: của spec này là `based_on_version_id`, `from_version_id`,
      `to_version_id` và `artifact_version_id` của ticket 04 (R2.18); FK của spec khác, ví dụ `version_id` của
      `studio.version_assessments` mà compliance-pdpl/05 đặt, do spec tạo FK làm chủ; `based_on_version_id` FK ghép
      `(tenant_id, based_on_version_id)` `ON DELETE SET NULL (based_on_version_id)` có index
      `(tenant_id, based_on_version_id)`, chỉ đặt NULL cột đó vì `tenant_id` NOT NULL; `change_note` NULL.
    - `studio.definition_manifests`: khóa chính `(tenant_id, hash)`, `body` jsonb NFC tối đa 1 MiB, ứng dụng chỉ
      INSERT, DELETE chỉ ở lượt xóa của offboarding (R3.8).
    - `studio.dependencies`: `from_version_id` FK ghép `(tenant_id, from_version_id)` và `from_artifact_id` FK ghép
      `(tenant_id, from_artifact_id)`, cả hai ON DELETE CASCADE; `to_kind` CHECK (`artifact`, `field`,
      `picklist_value`, `platform_artifact`, `connector`, `mcp_tool`, `binding`, `node_type`); `to_key`, `to_version`,
      `to_hash`; `to_artifact_id` FK ghép `(tenant_id, to_artifact_id)` và `to_version_id` FK ghép
      `(tenant_id, to_version_id)`, cả hai ON DELETE RESTRICT; mỗi FK ghép một index `(tenant_id, <cột>)`; `usage`
      CHECK (`read`, `write`, `compare`, `invoke`, `bind`, `display`); `path` con trỏ JSON; index
      `(tenant_id, to_kind, to_key)`; `ck_dependencies_artifact_target` CHECK
      `to_kind <> 'artifact' OR (to_artifact_id IS NOT NULL AND to_version_id IS NOT NULL AND to_key = to_artifact_id::text)`, vì trigger chặn xóa mềm tìm
      bên dùng qua `to_artifact_id` (failure-modes #7). `to_field_id` không có ở đây: custom-objects thêm cột và FK ghép
      `(tenant_id, to_field_id)` ON DELETE RESTRICT có index của nó cùng bảng field (ADR-0109 (Accepted) quyết 5).
    - FK ghép tới `platform.workspaces` dùng `uq_workspaces_tenant_id_id` do org-and-principals/01 tạo;
      ticket này không tạo ràng buộc đó (OPS-a.2).
2. Trigger trong cùng revision, tên ràng buộc theo `NAMING_CONVENTION`, ánh xạ ra lỗi API theo tên:
    - `studio.refuse_sealed_content_change()`: BEFORE UPDATE trên `studio.artifact_versions`, từ chối đổi
      `document`, `document_schema`, `content_hash`, `definition_hash`, `version_no`, `artifact_id` khi
      `OLD.stage <> 'draft'` (TC1).
    - `studio.refuse_api_name_change()`: BEFORE UPDATE OF `api_name` trên `studio.artifacts`, từ chối khi
      thành phần có phiên bản ở `live` hay `retired` (TC4; DO-08).
    - `studio.refuse_owning_workspace_change()`: BEFORE UPDATE OF `owning_workspace_id` trên `studio.artifacts`, từ
      chối khi `NEW.owning_workspace_id IS DISTINCT FROM OLD.owning_workspace_id`, vì AAD của phong bì bí mật của chủ
      thể thuộc thành phần gắn workspace sở hữu (TC30; R2.19; ADR-0115 (Accepted) quyết 1).
    - `studio.refuse_soft_delete_in_use()`: BEFORE UPDATE OF `deleted_at`, khi `deleted_at` chuyển từ
      NULL sang có giá trị mà một dòng `studio.dependencies` của thành phần khác trỏ tới nó từ một phiên
      bản `evaluating`, `awaiting_approval` hay `live`: `ERRCODE 23503`, ràng buộc
      `ck_artifacts_not_in_use` (TC5; DELETE cứng bị trigger dưới chặn ngoài offboarding, và bị FK chặn khi dòng phụ
      thuộc còn).
    - `platform.refuse_delete_outside_offboarding()`: BEFORE DELETE FOR EACH ROW trên `studio.artifacts`,
      `studio.artifact_versions` và `studio.definition_manifests`, `ERRCODE 23514` khi `platform.tenants.status` của
      công ty của `OLD.tenant_id` khác `offboarding` hay không đọc được (so bằng `IS DISTINCT FROM`; spec R3.8, TC31);
      ticket 04 và 05 gắn cùng hàm vào bảng của mình. Ứng dụng không xóa cứng dòng nào của ba bảng (xóa mềm, phiên bản
      bất biến, bản kê định nghĩa định danh theo nội dung), nên DELETE của `dw_app` ở bước 3 trên ba bảng đó chỉ để lane
      `offboarding` xóa được, cùng hình với trigger chặn xóa của compliance-pdpl:R5.6. `studio.dependencies` không có
      trigger này, vì `seal` của bước 6 xóa dòng của một phiên bản khi niêm phong lại phiên bản đó sau khi về `draft`.
    - `updated_at` do `platform.touch_updated_at()` giữ, nhường giá trị câu lệnh nêu (CLAUDE.md "Data
      model rules").
3. RLS ENABLE và FORCE, policy `tenant_isolation_<bảng>` chỉ theo `app.tenant_id` (định nghĩa toàn
   tenant, ADR-0100 (Accepted) quyết 5). Grant: `dw_app` SELECT, INSERT và DELETE trên `studio.artifacts`
   và `studio.artifact_versions`, cùng UPDATE theo cột, không bao giờ UPDATE cả bảng (studio-skeleton:R2.7, đã kiểm ở
   `packages/python/dw_platform/tests/integration/studio_catalog.py:164-188`): trên `studio.artifacts` chỉ `api_name`,
   `labels`, `last_version_no`, `row_version`, `deleted_at`, `updated_at`; trên `studio.artifact_versions` chỉ `stage`,
   `document_schema`, `document`, `version_no`, `content_hash`, `definition_hash`, `row_version`, `change_note` (`stage`
   cho `LifecycleService` của agent-lifecycle/03; cột mà spec khác thêm thì revision thêm nó cấp UPDATE theo cột; spec
   Dữ liệu); SELECT, INSERT và DELETE trên `studio.dependencies` và
   `studio.definition_manifests`; SELECT trên `studio.artifact_kinds`, có một dòng lý do trong
   `_PLATFORM_REFERENCE_TABLES` của `test_rls_coverage.py` (studio-skeleton:R2.8). Cả bốn bảng có DELETE vì lane `offboarding` xóa
   bằng `dw_app` và chỉ xóa bảng có trong `_CATALOG_PURGEABLE`; trên ba bảng của trigger ở bước 2, DELETE chỉ dùng được
   ở lượt xóa của offboarding. Khẳng định trong
   `test_privileges.py`; `test_rls_coverage.py` thấy cả bốn bảng có `tenant_id`, và mỗi bảng có một dòng lý
   do trong danh sách bảng toàn tenant của test đó (định nghĩa có `owning_workspace_id`, phiên bản và chỉ mục
   phụ thuộc là con của thành phần, bản kê định nghĩa định danh theo nội dung; DO-01).
4. Offboarding, trên `offboarding.py` và `test_offboarding.py` mà foundations-hardening/07 đã viết lại
   (`_CATALOG_COLUMNS`, `export_rows`) và sổ bước xóa của ticket đó (foundations-hardening:R11.4; H-2): bốn bảng dùng
   bước mặc định (câu `DELETE` chung) nhờ DELETE của bước 3, không đăng ký bước nào và không khai thứ tự; thứ tự đến từ
   khóa ngoại `RESTRICT` của chính các bảng này trong `pg_constraint` (studio-skeleton:R4.2; spec Dữ liệu):
   `studio.dependencies` trước hai bảng kia vì `to_version_id` và `to_artifact_id` giữ chúng (đã đo: xóa
   `studio.artifacts` trước khi gỡ cạnh phụ thuộc thì hỏng; CASCADE của `from_version_id` không cho nó đi sau);
   `studio.artifact_versions` trước `studio.artifacts`, với `studio.gate_runs` của agent-lifecycle ở giữa
   (`studio.artifact_versions.gate_run_id` và `studio.gate_runs.artifact_id` là FK RESTRICT, agent-lifecycle:R10.2);
   `studio.artifacts` trước `platform.workspaces` vì `owning_workspace_id` giữ nó; `studio.definition_manifests` không
   có FK RESTRICT nào nên không bị ràng thứ tự. Không bảng nào có dòng `STUDIO_EXCLUSIONS`; `test_offboarding.py` purge
   một tenant có hai thành phần phụ thuộc nhau ở hai workspace (TC21).
5. `ArtifactKindRegistry` trong lõi `dw_studio`, đăng ký ở `build_studio` (ADR-0100 (Accepted) quyết 6):
   mỗi mục có `kind`, `document_schema`, khóa đọc, khóa ghi và khóa gửi của loại, và `publish_hook`, không giá trị
   mặc định (R2.15; mỗi spec đăng ký khóa của mình theo quy ước `studio.<area>.<verb>` của tenant-rbac:R1.6),
   `validate(document)` trả mọi lỗi kèm con trỏ JSON, `extract(document)` thuần, không đọc cơ sở dữ liệu, trả danh sách
   tham chiếu `(to_kind, to_key, usage, path)`; với `to_kind` `artifact`, `to_key` là id của thành phần đích dạng chuỗi,
   id mà gói và bản sao mang (ADR-0109 (Accepted) quyết 1), còn phiên bản ghim do `seal` phân giải (bước 6). Bộ mục của
   registry chạy thật là một tuple hằng trong `dw_studio`, rỗng ở ticket này; `build_studio` của studio-skeleton/02 nhận
   thêm tham số từ khóa `kinds`, mặc định là tuple đó, không đọc từ settings hay biến môi trường, nên loại chỉ có trong
   test không vào được app chạy thật; `build_container` và `create_app` chuyển tiếp cùng một tham số từ khóa
   `studio_kinds` với cùng mặc định, và test dựng app với `studio_kinds=` gồm hai loại fixture của bước 8, không gán
   lại `container.studio` sau khi dựng. `publish_hook` là
   móc phát hành mà spec của loại cấp (dịch vụ metadata của custom-objects cho `object`, custom-objects:R1.1; móc của
   workflow-triggers cho `endpoint`; móc của workflow-engine cho `workflow`, workflow-engine:R1.4), là "publish hook"
   của ADR-0109 (Accepted) quyết 1: agent-lifecycle gọi nó trong giao dịch đưa phiên bản lên `live`, ở handler
   `.decided` và ở nhánh chỉ siết (agent-lifecycle:R2.9, agent-lifecycle:R5.5); móc không đổi giai đoạn, không ghi
   `studio.version.published`, và `seal` không gọi nó. Hai loại fixture khai một móc không làm gì. Mục không giữ cờ
   cổng: cờ chỉ ở cột `has_quality_gate` của `studio.artifact_kinds`. Test ở composition root: tập loại của registry
   chạy thật bằng tập dòng của `studio.artifact_kinds`, mỗi khóa của mỗi mục có trong danh mục quyền, và mỗi mục có
   `publish_hook`; vì cả hai tập rỗng ở ticket này, test mang hai ca trồng lỗi, một dòng vai migrator chèn mà registry
   không có và một mục registry mà bảng không có, mỗi ca đỏ (failure-modes #3).
6. `ArtifactService` (lõi `dw_studio`, constructor injection), mỗi thao tác một kiểm quyền: khóa đọc
   hay khóa ghi mà mục registry của loại khai, ở độ sâu chạm tới `owning_workspace_id`. "Chạm tới" do
   `platform.workspace_reach(tenant_id, user_id, <khóa>)` trả lời, hàm SQL cạnh `platform.effective_grants`
   (`db/migrations/versions/b5677d345bc1_tenant_roles.py:434`; tenant-rbac/02; ADR-0104 (Accepted) quyết 5), không tính
   lại độ sâu và neo từ `AccessContext.grants` trong Python (`CLAUDE.md` "Tenancy and authorization"); tenant khác,
   thành phần đã xóa mềm hay không đọc được → 404 ở mọi route `{id}`, đọc được mà không ghi được → 403
   `permission_denied` (TC24). Danh sách lọc trong SQL, không sau truy vấn: chỉ dòng có `(kind, owning_workspace_id)`
   nằm trong tầm khóa đọc của loại đó, `deleted_at IS NULL`, keyset trên index của bước 1, nên trang không bao giờ có
   thành phần ngoài tầm và không ngắn đi vì lọc. Test kiểm quyền tham số hóa theo mọi loại đã đăng ký và theo mọi route
   `{id}` của bước 7, để loại sau (như `workflow` của workflow-engine/01) chạy cùng test.
    - `create`: thành phần, nháp đầu và audit `studio.artifact.created` trong một giao dịch; `owning_workspace_id` là
      `AccessContext.workspace_id`, workspace hành động đã xác minh, không có trường body nào; khóa ghi của loại không
      chạm workspace đó → 403 `permission_denied`; `kind` không có trong registry → 422 `validation_failed` trước mọi
      lần ghi; Tên API sai mẫu → 422 `validation_failed`; vi phạm unique `(tenant_id, kind, api_name)` ánh xạ theo tên
      ràng buộc → 409 `conflict`, `details.reason_code` `api_name_taken`.
    - Một luật khóa: `save_draft`, `create_draft` và `seal` đều khóa dòng thành phần (`SELECT ... FOR UPDATE`) trước khi
      đọc phiên bản nào của nó, nên ba lệnh ghi phiên bản của một thành phần đi lần lượt và `content_hash` của một lần
      niêm phong luôn là mã băm của đúng `document` nó đọc. Tài nguyên thành phần và tài nguyên bản Nháp theo R3 của
      app-standards (ADR-0108 (Accepted) quyết 3): thân trả về mang `version` (số nguyên, là `row_version` của dòng),
      `ETag` là `version` đó, và mọi route ghi bật `RequireIfMatch`, gồm `DELETE .../{id}` và `POST .../draft` (giá trị
      là `version` của thành phần), không mục nào trong `EXEMPT_WRITES` của
      `apps/api/tests/unit/test_list_and_write_conventions.py`; lệnh ghi có điều kiện không khớp trả lời theo
      app-standards:R3.13.
    - `get_draft`: bản Nháp (`document_schema`, `document`, `version`, `based_on_version_id`) với ETag là `row_version`
      của nó, giá trị mà `save_draft` và lệnh gửi của agent-lifecycle/03 nhận trong `If-Match`; không có bản Nháp → 404
      `not_found` với `details.reason_code` `no_draft`.
    - `save_draft`: `to_nfc` ở biên, khóa dòng thành phần, `If-Match` so với `row_version`; khớp → thay tài liệu, đặt
      `version_no`, `content_hash` và `definition_hash` về NULL (bản Nháp từng niêm phong rồi về `draft` không còn mang
      số hay mã băm của nội dung cũ; R2.8 cấp số mới khi niêm phong lại), tăng `row_version`, trả ETag mới; lệch → 412
      `precondition_failed`, `details.reason_code` `stale_version`; thiếu → 428 (ADR-0108 (Accepted) quyết 3). Không có
      bản Nháp: có Bản ứng viên → 409 `conflict` `candidate_pending`, không có → 404 `no_draft`. Audit
      `studio.artifact.draft_saved` chỉ mang `row_version`.
    - `create_draft`: trong một giao dịch, khóa dòng thành phần (`SELECT ... FOR UPDATE`, như `seal`) rồi đọc phiên bản
      chưa phát hành của nó: Bản ứng viên ở `evaluating` hay `awaiting_approval` → 409 `conflict`, `details.reason_code`
      `candidate_pending` (R2.22; muốn sửa thì rút qua lệnh rút của agent-lifecycle/03, agent-lifecycle:R2.4); bản Nháp
      → 409 `conflict`, `details.reason_code` `draft_exists` (R2.23); không có → chèn một dòng `draft` (`version_no`
      NULL) chép `document_schema` và `document` của phiên bản `live`, hay của phiên bản có `version_no` lớn nhất khi
      không có bản `live`, `based_on_version_id` trỏ phiên bản đó, audit `studio.artifact.draft_created` mang
      `based_on_version_id`, rồi trả ETag (R2.21). Chỉ mục của bước 1 là hàng rào cuối cho lệnh ghi đi vòng qua service
      (R2.20); vi phạm của nó ánh xạ theo tên ra 409 `draft_exists`.
    - `update`: `api_name`, `labels` với `If-Match`; `api_name` khi đã có phiên bản từng `live` → 409
      `api_name_immutable` trước khi trigger phải chặn; audit `studio.artifact.updated` với tên trường. ETag của
      `GET .../{id}` và `If-Match` của `PATCH`, `DELETE` và `POST .../draft` là `studio.artifacts.row_version`, chỉ
      `update` tăng nó; `seal` (đổi `last_version_no`), `create_draft` và `soft_delete` không tăng nó.
    - `seal(uow, artifact_id, expected_row_version)`: trong giao dịch của bên gọi, khóa dòng thành phần
      (`SELECT ... FOR UPDATE`), so `expected_row_version` với `row_version` của nháp, lệch → từ chối với
      `details.reason_code` `stale_version` trước khi cấp số (R2.17; `expected_row_version` là giá trị `If-Match`, ETag
      của bản Nháp, mà lệnh gửi của agent-lifecycle nhận, trả 412 `precondition_failed` khi lệch và 428 khi thiếu,
      agent-lifecycle:R2.12, agent-lifecycle:R2.13; ADR-0109 (Accepted) quyết 2), `validate` (lỗi → 422
      `validation_failed` liệt kê mọi lỗi trong `errors[]`), `version_no = last_version_no + 1`, `content_hash` qua
      `dw_kernel.canonical`, bao đóng qua `closure_of(uow, kind, artifact_id, document)`, một hàm mà ticket 04 gọi lại
      cho bản Nháp của lượt `simulate`: chạy `extract`, phân giải mỗi tham chiếu `artifact` trong tenant, đọc dòng thành
      phần đích `FOR SHARE` (một lần xóa mềm đồng thời chờ, rồi trigger của nó thấy dòng phụ thuộc mới), đích phải tồn
      tại, chưa xóa mềm và có phiên bản `live`, không thì 422 `validation_failed` với một mục `errors[]` cho mỗi tham
      chiếu hỏng (`pointer` là `path`, `reason` `dependency_unresolved`, một lý do cho mọi trường hợp; phân giải không
      xét tầm đọc của người gửi, vì R3.4 cho bên dùng ở workspace khác, nên lần niêm phong chỉ xác nhận một id UUIDv7 mà
      người gửi đã biết); dòng ghi ra mang `to_artifact_id`, `to_version_id` của bản `live`, `to_version` là
      `version_no` của nó, `to_hash` là `content_hash` của nó; `to_kind` khác ghi đúng như `extract` trả, bên phân giải
      của chúng thuộc spec đăng ký loại đó. Mỗi mục bao đóng là `(kind, key, version, content_hash)` từ các dòng đó, gộp
      trùng, xếp theo `(kind, key)`; `definition_body(kind, artifact_id, content_hash, closure)` dựng thân
      `dw.definition_manifest/v1` của spec Dữ liệu, không mang `version_no`, và `definition_hash` là `content_hash` của
      thân, một hàm mà ticket 04 gọi lại cho mã băm tạm (TC28); ghi `studio.definition_manifests` `ON CONFLICT DO NOTHING`, thay các
      dòng `studio.dependencies` của phiên bản (xóa dòng mà lần niêm phong trước của một phiên bản đã về `draft` ghi,
      R2.8, rồi ghi bộ mới), tăng `row_version` của nháp (lần niêm phong thứ hai cùng `expected_row_version` nhận
      `stale_version`), rồi trả id phiên bản cùng hai mã băm. `seal` như nhau cho mọi loại: không đọc
      `has_quality_gate`, không đổi `stage` (phiên bản ra khỏi `seal` vẫn ở `draft`) và không đổi dòng phiên bản nào
      khác của thành phần (R2.13, R2.16); không Bản ứng viên nào chờ cạnh bản Nháp được niêm phong, vì chỉ mục một
      phiên bản chưa phát hành của bước 1 (R2.20). Chuyển giai
      đoạn sau `seal` là của `LifecycleService` của agent-lifecycle/03 và agent-lifecycle/04 trong cùng giao dịch
      (`draft → evaluating` khi `has_quality_gate` là true, `draft → awaiting_approval` khi false, `draft → live` ở
      nhánh chỉ siết sau khi gỡ bản `live` trước), với `studio.guard_version_stage()` là hàng rào cuối
      (agent-lifecycle:R1.4, agent-lifecycle:R1.6, agent-lifecycle:R2.8, agent-lifecycle:R2.9; ADR-0120 (Accepted)
      quyết 1); cột `tighten_only` và `compared_live_hash` do agent-lifecycle thêm và ghi ở mọi lần gửi
      (agent-lifecycle:R2.10), không do ticket này. Không audit: route gửi kiểm định của agent-lifecycle/03 audit trong
      cùng giao dịch, kể cả `studio.version.published` của nhánh chỉ siết.
    - `soft_delete`: đặt `deleted_at`; `ck_artifacts_not_in_use` → 409 `conflict`, `details.reason_code`
      `artifact_in_use`, `details` gồm số đếm theo giai đoạn; audit `studio.artifact.deleted`.
    - `versions` và `version`: chỉ phiên bản có `stage` khác `draft`; bản Nháp đọc qua `get_draft`.
    - `dependents`: nhóm theo giai đoạn (`live`, ứng viên); tên chỉ cho bên người gọi đọc được theo cùng
      kiểm quyền, còn lại chỉ đếm (TC7). `draft_dependencies`: chạy `extract` trên nháp, không ghi dòng
      nào.
7. Route trong nhóm `/api/v1/studio` của studio-skeleton/02, lỗi theo vỏ problem+json
   (ADR-0108 (Accepted)): `POST /api/v1/studio/artifacts`, `GET /api/v1/studio/artifacts` (keyset theo
   `updated_at DESC, id DESC`, lọc `kind`, `label`; index danh sách có `kind` khi lọc theo loại, index không `kind`
   khi không lọc), `GET /api/v1/studio/artifacts/{id}`,
   `PATCH /api/v1/studio/artifacts/{id}`, `GET /api/v1/studio/artifacts/{id}/draft` (`get_draft`),
   `PUT /api/v1/studio/artifacts/{id}/draft`,
   `POST /api/v1/studio/artifacts/{id}/draft` (`create_draft`),
   `GET /api/v1/studio/artifacts/{id}/versions`, `GET /api/v1/studio/artifacts/{id}/versions/{version_no}`,
   `DELETE /api/v1/studio/artifacts/{id}`, `GET /api/v1/studio/artifacts/{id}/dependents`,
   `GET /api/v1/studio/artifacts/{id}/draft/dependencies`. Mọi id là UUID. `POST /api/v1/studio/artifacts` và
   `POST .../draft` nhận `Idempotency-Key` tùy chọn qua `idempotent(...)` của
   `apps/api/src/dw_api/dependencies/idempotency.py:365`, với hàm kiểm của `ArtifactService` làm `check` (khóa theo
   loại), phát lại 201 kèm `ETag` và `Location` chỉ cho đúng người gọi (ADR-0108 (Accepted) quyết 4). Danh sách vào
   `REGISTERED` của `tests/support/plan_shape.py` (bảng `studio.artifacts`) và `EXPECTED` của
   `apps/api/tests/integration/test_plan_shape.py` với vị từ `()` và khóa sắp `("updated_at", "id")` khi không lọc,
   một mục thứ hai lọc `kind` với vị từ `("kind",)` nếu bộ kiểm cho hai dạng một route, không thì dạng lọc `kind`
   (app-standards R6; ADR-0108 (Accepted) quyết 2); lọc tầm, `deleted_at IS NULL` và `label` là `Filter` trên index
   dẫn bằng `tenant_id`. `make generate-contracts`.
8. Loại `fixture` chỉ trong test: tài liệu có trường `uses` trỏ tới thành phần khác, `extract` trả một
   phụ thuộc `artifact` cho mỗi phần tử; test fixture khẳng định đúng tập dòng ghi ra. Loại
   `fixture_gateless` chỉ trong test, cùng tài liệu, dòng `studio.artifact_kinds` của nó nêu
   `has_quality_gate = false`. Hai mục registry và bộ dựng dòng của chúng sống ở `dw_studio.testing` (gói con ra đời
   cùng ticket này, studio-skeleton/02 bước 1), vì workflow-engine/02, workflow-engine/03 và ticket 04 dùng lại loại
   fixture. Khóa đọc, ghi và gửi của hai loại là khóa chỉ trong test, không mang tiền tố `studio.` (test (d) của
   `packages/python/dw_platform/tests/integration/test_permission_catalogue.py` đòi khu vực có trong danh sách), chèn
   bằng `register_key` của `dw_platform.testing.rbac` (`scope_kind` `workspace`, mọi cột NOT NULL, gồm `risk` của
   tenant-rbac/01 và `tenant_grantable` của tenant-rbac/02; ADR-0104 (Accepted) quyết 1) và gỡ bằng `unregister_key`.
   Bộ dựng là một context manager async, dùng làm fixture pytest phạm vi module, không phạm vi session: khi thoát nó đưa
   các công ty thử của module sang `offboarding`, xóa dòng của chúng bằng vai migrator theo thứ tự khóa ngoại, gỡ hai
   dòng `studio.artifact_kinds` và các khóa, rồi khẳng định không còn dòng nào của hai loại; nhờ vậy test (c) của
   `test_permission_catalogue.py` (khóa `active` phải có chỗ kiểm trong mã) và test registry bằng bảng của bước 5, chạy
   trong cùng tiến trình pytest, không bao giờ thấy chúng. Ca cần một phiên bản ở giai đoạn khác `draft`
   (R2.8, R2.9, R2.10, R2.16, R2.20, R2.21, R2.22, R3.3, R3.4) đặt `stage` bằng vai migrator trong test, và vẫn chịu chỉ
   mục một phiên bản chưa phát hành của bước 1, vì bên chuyển giai đoạn là `LifecycleService` của agent-lifecycle/03,
   ticket chờ ticket này.

## Tiêu chí chấp nhận

- [ ] R2.1: `POST` tạo thành phần có id UUIDv7, một nháp và một audit `studio.artifact.created` trong một
      giao dịch; lỗi giữa chừng không để lại dòng nào.
- [ ] R2.2: Tên API 40 ký tự được nhận; 41 ký tự, 1 ký tự, `Lead` hay `1lead` → 422, không dòng nào.
- [ ] R2.3: Tên API trùng thành phần chưa xóa cùng loại → 409 `api_name_taken`; sau khi thành phần cũ bị
      xóa mềm, cùng tên tạo được; tenant khác dùng cùng tên được.
- [ ] R2.4: `PUT` nháp với `If-Match` đúng → tài liệu mới, `row_version` tăng 1, ETag mới.
- [ ] R2.5 (TC3): `PUT` nháp với `If-Match` cũ → 412 `stale_version`, nháp không đổi; INSERT nháp thứ hai
      cùng thành phần → lỗi partial unique; bỏ so `row_version` → test đỏ.
- [ ] R2.5 (TC3): `GET .../draft` trả tài liệu, `version` và ETag bằng `row_version`; `PUT` với ETag đó → 200; hai `PUT`
      đồng thời cùng `If-Match` → một 200, một 412 `stale_version`; thành phần không có bản Nháp → `GET` và `PUT` 404
      `no_draft`, có Bản ứng viên → `PUT` 409 `candidate_pending`, không dòng nào đổi; `PUT` lên bản Nháp từng niêm phong
      (v3 về `draft`) → `version_no`, `content_hash`, `definition_hash` NULL; `DELETE .../{id}` và `POST .../draft` thiếu
      `If-Match` → 428; test quy ước R3.12 của app-standards xanh với `EXEMPT_WRITES` rỗng.
- [ ] R2.7 (TC2): một giao dịch khác giữ khóa dòng thành phần (`SELECT ... FOR UPDATE`) → `PUT .../draft`,
      `POST .../draft` và `seal` của thành phần đó đều chờ tới khi nó kết thúc; bỏ khóa ở một trong ba → test đỏ, nêu thao
      tác đó. `definition_hash` bằng `content_hash(definition_body(...))` tính lại trong test, và hai nháp khác tài liệu
      cùng phụ thuộc có hai `definition_hash` khác nhau.
- [ ] R2.6: tài liệu `fixture` có ba lỗi → 422 với đủ ba mục `errors[]`, mỗi mục một con trỏ; không số
      phiên bản nào được cấp.
- [ ] R2.7 (TC2): niêm phong nháp hợp lệ cấp `last_version_no + 1`, ghi hai mã băm khớp
      `^sha256:[0-9a-f]{64}$` và để phiên bản ở `draft`; hai lần niêm phong đồng thời một nháp với cùng
      `expected_row_version` → một thành công, một `stale_version`; bỏ khóa dòng thành phần, hay bỏ bước tăng
      `row_version` của `seal` → test đồng thời đỏ.
- [ ] R2.8 (TC2): đưa phiên bản v3 về `draft` trong test rồi niêm phong lại → v4, không phiên bản nào
      mang lại số 3.
- [ ] R2.9 (TC1): `dw_app` UPDATE `document` của phiên bản `evaluating` hay `live` → trigger từ chối; gỡ
      trigger → test đỏ.
- [ ] R2.10 (TC4): `PATCH` `api_name` khi có phiên bản từng `live` → 409 `api_name_immutable`; khi chưa
      có → 200; UPDATE thẳng bằng `dw_app` → trigger từ chối.
- [ ] R2.11 (TC24): người chỉ đọc được ở ws1 `GET` thành phần của ws2 ngoài độ sâu → 404; tenant B `GET`
      thành phần của tenant A → 404; gỡ kiểm quyền ở service → test đỏ.
- [ ] R2.11 (TC24): người chỉ đọc được ở ws1 gọi `GET /api/v1/studio/artifacts`, không lọc và lọc `kind`, qua mọi trang
      → không thành phần nào của ws2 và không thành phần đã xóa mềm, mỗi trang đủ `limit` khi còn dòng trong tầm; bỏ phép
      lọc tầm → test đỏ; người giữ khóa đọc ở độ sâu `tenant` thấy cả hai workspace.
- [ ] R2.12 (TC24): test tham số hóa trên mọi route `{id}` của bước 7: tenant B, hay thành phần đã xóa mềm → 404,
      không ghi gì; đọc được mà không ghi được → 403 `permission_denied` ở `PATCH`, `PUT .../draft`, `POST .../draft` và
      `DELETE`, không ghi gì; `POST /api/v1/studio/artifacts` khi khóa ghi không chạm workspace hành động → 403, với
      `kind` chưa đăng ký → 422, không dòng nào.
- [ ] R2.12 (TC24): người đọc được mà không có quyền ghi `PUT` nháp → 403 `permission_denied`, nháp không
      đổi.
- [ ] R2.13 (TC27): niêm phong nháp hợp lệ của `fixture` (`true`) và của `fixture_gateless` (`false`) cấp số
      phiên bản và hai mã băm như R2.7 và để cả hai ở `draft`, không yêu cầu phê duyệt nào; để `seal` đổi `stage`
      theo `has_quality_gate` → test đỏ.
- [ ] R2.14 (TC27): INSERT dòng `studio.artifact_kinds` không nêu `has_quality_gate` bằng vai migrator → lỗi NOT
      NULL; thêm DEFAULT cho cột → test đỏ.
- [ ] R2.15 (TC24): mỗi mục registry khai đủ khóa đọc, ghi và gửi, mỗi khóa có trong danh mục quyền, và một
      `publish_hook`; gỡ khóa đọc hay móc của `fixture` → test registry đỏ; test kiểm quyền tham số hóa chạy cho mọi
      loại đã đăng ký; test registry bằng bảng đỏ ở cả hai ca trồng lỗi của bước 5; app dựng không `kinds=` không nhận
      `POST` loại `fixture` (422); sau một module dùng loại fixture không còn dòng `studio.artifact_kinds` hay
      `platform.permissions` nào của nó, và `test_permission_catalogue.py` chạy sau module đó trong cùng tiến trình xanh.
- [ ] R2.1: (ADR-0108 (Accepted) quyết 4) `POST /api/v1/studio/artifacts` gửi lại cùng `Idempotency-Key`, cùng người, cùng body → cùng
      201 kèm `ETag` và `Location`, một thành phần; người khác dùng key đó → 409 `idempotency_conflict`.
- [ ] R2.16 (TC27): `fixture_gateless` có một phiên bản `live`; niêm phong một nháp mới của cùng thành phần → bản mới ở
      `draft` có số và hai mã băm, dòng `live` giữ nguyên giai đoạn và mọi cột; để `seal` đổi dòng `live` → test đỏ.
      Nhánh chỉ siết `draft → live`, gồm bước gỡ bản `live` cũ, là của `LifecycleService` (agent-lifecycle:R2.9, AL4),
      và ca duyệt một Bản ứng viên có gốc đã đổi rồi về `draft` với `base_changed` là AL19, hai ca chạy ở
      agent-lifecycle/04.
- [ ] R2.17 (TC3): lưu nháp một lần rồi `seal` với `expected_row_version` cũ (lệnh gửi mang `If-Match` cũ) →
      `stale_version`, không số phiên bản, không dòng `studio.dependencies` hay `studio.definition_manifests`; bỏ so
      `expected_row_version` → test đỏ.
- [ ] R2.18 (TC29): bằng vai migrator, INSERT dòng `studio.dependencies` của tenant A có `to_version_id`, rồi
      `from_version_id`, là phiên bản của tenant B → lỗi FK ghép; UPDATE `based_on_version_id` của phiên bản tenant A
      sang phiên bản tenant B → lỗi FK; chuyển tenant A sang `offboarding` rồi xóa phiên bản gốc → `based_on_version_id`
      thành NULL, `tenant_id` giữ nguyên (ngoài `offboarding`, trigger của R3.8 từ chối lệnh xóa trước); đổi một FK ghép
      về FK một cột → test đỏ.
- [ ] R2.18 (TC29): bằng vai migrator, INSERT phiên bản của tenant A có `artifact_id` là thành phần của tenant B, rồi
      dòng `studio.dependencies` của tenant A có `from_artifact_id`, rồi `to_artifact_id`, là thành phần của tenant B →
      lỗi FK ghép; đổi một trong ba FK ghép về FK một cột → test đỏ.
- [ ] R2.18 (TC29): bằng vai migrator, INSERT thành phần của tenant A có `owning_workspace_id` là workspace của tenant B
      → lỗi FK ghép tới `uq_workspaces_tenant_id_id`; đổi FK đó về FK một cột tới `platform.workspaces (id)` → test đỏ.
- [ ] R2.19 (TC30): `dw_app` UPDATE `owning_workspace_id` của một thành phần sang workspace khác cùng tenant → từ chối
      vì không có quyền trên cột (42501), cột giữ nguyên; cùng lệnh bằng vai migrator → trigger từ chối; UPDATE `labels`
      của cùng dòng bằng `dw_app` → được; gỡ trigger → ca migrator đỏ; cấp `dw_app` UPDATE cả bảng → test quyền của
      studio-skeleton:R2.7 đỏ.
- [ ] R2.20 (TC27): bằng `dw_app`, INSERT một dòng `draft` cho thành phần đã có bản Nháp, rồi cho thành phần có Bản ứng
      viên ở `awaiting_approval` (đặt bằng vai migrator) → chỉ mục duy nhất một phần từ chối cả hai; thành phần chỉ có
      phiên bản `live` và `retired` nhận một dòng `draft`; thu chỉ mục về `stage = 'draft'` → ca Bản ứng viên đỏ.
- [ ] R2.21: thành phần có v1 `retired` và v2 `live` → `POST .../draft` trả 201 với ETag, bản Nháp mới chép
      `document_schema` và `document` của v2, `based_on_version_id` là v2, `version_no` NULL, một audit
      `studio.artifact.draft_created`; v1 và v2 đều `retired` → bản Nháp chép v2; người đọc được mà không có quyền ghi →
      403 `permission_denied`, tenant khác → 404, không dòng nào (R2.11, R2.12).
- [ ] R2.22 (TC27): `fixture_gateless` có Bản ứng viên ở `awaiting_approval`, và `fixture` có Bản ứng viên ở
      `evaluating` → `POST .../draft` trả 409 `conflict` với `details.reason_code` `candidate_pending` ở cả hai, không
      dòng nào, không audit; bỏ kiểm Bản ứng viên ở `create_draft` → test đỏ.
- [ ] R2.23 (TC27): thành phần đã có bản Nháp → `POST .../draft` trả 409 `conflict` với `details.reason_code`
      `draft_exists`, bản Nháp giữ `document` và `row_version`; hai lệnh `POST .../draft` đồng thời trên thành phần chỉ có
      bản `live` → một 201, một 409 `draft_exists`; khóa của `create_draft` có ca chờ của R2.7; `dw_app` INSERT thẳng
      bản Nháp thứ hai qua kho của service (bỏ qua khóa) → 409 `draft_exists` ánh xạ theo tên chỉ mục, không 500.
- [ ] R3.1 (TC6): lỗi chèn giữa giao dịch niêm phong → không số phiên bản, không dòng
      `studio.dependencies`, không dòng `studio.definition_manifests`; làm hỏng `extract` của `fixture`
      → test fixture đỏ.
- [ ] R3.1: đưa phiên bản v3 về `draft`, đổi tài liệu rồi niêm phong lại → dòng `studio.dependencies` của phiên bản là
      bộ của lần niêm phong sau, không còn dòng nào của lần trước; bỏ bước xóa của `seal` → test đỏ.
- [ ] R3.3 (TC5): niêm phong nháp `fixture` có `uses` trỏ một id không có, một thành phần đã xóa mềm và một
      thành phần chưa có bản `live` → 422 với ba mục `errors[]` `dependency_unresolved`, mỗi mục con trỏ của nó, không
      số phiên bản; `uses` trỏ thành phần có bản `live` → dòng `studio.dependencies` mang `to_artifact_id`, `to_version_id`
      của bản `live`, `to_key` là id của đích và `to_hash` là `content_hash` của bản đó; `dw_app` INSERT dòng `artifact`
      không có `to_artifact_id`, hay có `to_key` khác id đó → lỗi `ck_dependencies_artifact_target`; một giao dịch
      `dw_app` niêm phong bên dùng rồi, trong cùng giao dịch, đặt `stage = 'evaluating'` (đóng vai `LifecycleService`) mà
      chưa commit → xóa mềm đích ở kết nối khác chờ, rồi sau commit nhận 409 `artifact_in_use`; bỏ `FOR SHARE` → xóa mềm
      không chờ, thành công, và test đỏ.
- [ ] R3.2: xóa mềm thành phần không ai dùng → `deleted_at` có giá trị, audit `studio.artifact.deleted`,
      thành phần biến khỏi danh sách.
- [ ] R3.3 (TC5): xóa mềm thành phần A mà phiên bản `live` của thành phần B ở workspace khác dùng → 409
      `artifact_in_use` kèm số đếm; đưa phiên bản của B sang `retired` rồi xóa mềm → được; gỡ trigger → test xóa mềm
      đỏ; ở một công ty đã chuyển sang `offboarding`, DELETE cứng một thành phần mà dòng `studio.dependencies` còn trỏ
      tới → lỗi FK.
- [ ] R3.4 (TC7): người chỉ đọc được ở ws1 mở Nơi đang dùng thấy tên bên phụ thuộc ở ws1, bên ở ws2 chỉ
      là số đếm; tenant B → 404.
- [ ] R3.5: `GET .../draft/dependencies` trả phụ thuộc của nháp và số dòng `studio.dependencies` không
      đổi.
- [ ] R3.6 (TC21): `test_offboarding.py` purge tenant có hai thành phần phụ thuộc nhau, tenant khác giữ
      nguyên mọi dòng; thứ tự bước mà sổ bước xóa suy ra đặt `studio.dependencies` trước `studio.artifact_versions` và
      `studio.artifact_versions` trước `studio.artifacts`; đột biến phép suy để bỏ cạnh `to_version_id` → purge hỏng ở
      khóa ngoại đó và test phủ offboarding (studio-skeleton:R4.2) đỏ, nêu FK ghép của `to_version_id`; test phủ
      offboarding (studio-skeleton:R4.1, studio-skeleton:R4.2) xanh với bốn bảng không có trong `STUDIO_EXCLUSIONS`;
      thu DELETE của `dw_app` trên một trong bốn bảng → test phủ đỏ, nêu tên bảng.
- [ ] R3.8 (TC31): `dw_app` DELETE một dòng `studio.artifacts`, `studio.artifact_versions` hay
      `studio.definition_manifests` của công ty `active` → 23514, dòng còn; cùng lệnh khi công ty ở `offboarding` → xóa
      được; gỡ phép kiểm trạng thái khỏi `platform.refuse_delete_outside_offboarding()` → test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:46`; spec: Dữ liệu.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:108-114` (foundations-hardening/07 thay bằng sổ bước xóa); spec: R3.6,
  TC21.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:117-119`; spec: R3.8, TC31;
  `CLAUDE.md`, Data model rules.
- `db/migrations/sql/0001_platform_grants.sql:27`; spec: R2, R3; ADR-0109 (Accepted) quyết 1-2, 4-5;
  ADR-0120 (Accepted) quyết 1; ADR-0108 (Accepted) quyết 3 (R2.17); ADR-0115 (Accepted) quyết 1 (R2.19).

## Comments

- 2026-10-23 (agent): gộp từ B6 tenant-config 02 và 03. Không có con trỏ `active_version_id`
  (ADR-0109 (Accepted) quyết 2). Ticket dùng ETag, `If-Match`, 412 và 428 của app-standards/03 và
  `platform.effective_grants` của tenant-rbac/02, hai ticket chưa có ở Blocked by của gói nguồn.
- 2026-10-23 (agent): DO-05 đã có lời đáp (Đạt 23/10/2026, một vỏ chung), nên ticket về `needs-triage`.
  Theo phiếu cùng ngày: Tên API `{1,39}` (ADR-0107 (Accepted)), `studio.artifact_kinds` thay `ck_artifacts_kind`
  (OPS-b), `uq_workspaces_tenant_id_id` do org-and-principals/01 tạo (OPS-a.2), loại không có Cổng chất
  lượng sang `awaiting_approval` (R2.13), danh sách bảng toàn tenant (DO-01).
- 2026-10-24 (agent): theo quyết định của Đạt ngày 24/10/2026: cột `has_quality_gate` không DEFAULT là chỗ duy
  nhất của cờ cổng (R2.14); mục registry khai khóa đọc, ghi và gửi (R2.15); nhánh chỉ siết `draft` sang `live`
  của `dw.object/v1` (Q-R6, R2.16).
- 2026-10-24 (agent): vòng sửa thứ tư, theo Quyết định cùng ngày của spec: bản chỉ siết không đổi Bản ứng viên
  đang chờ, và lệnh duyệt Bản ứng viên có gốc đã đổi đưa nó về `draft` với `base_changed` (R2.16, TC27; quyết định
  của Đạt); thêm `uq_artifacts_tenant_id_id`; khóa của loại fixture chèn với mọi cột NOT NULL, nên ticket chờ
  tenant-rbac/02 (quyết định tạm của spec); chờ foundations-hardening/07, vì cùng sửa `offboarding.py` và
  `test_offboarding.py`; quy ước khóa của bước 5 dẫn tenant-rbac:R1.6 (quyết định tạm của spec).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt b, theo các quyết định tạm cùng ngày của spec: `seal` so
  `expected_row_version`, giá trị `If-Match` mà lệnh gửi của agent-lifecycle nhận (R2.17, TC3); mục registry mang
  `publish_hook` mà agent-lifecycle gọi trong giao dịch phát hành (R2.15); `uq_artifact_versions_tenant_id_id` và FK
  ghép cho mọi FK tới phiên bản (R2.18, TC29); Bản ứng viên bị bản chỉ siết chặn vì lần phát hành của nó so
  `compared_live_hash` với bản mà nó thay (R2.16); chờ app-standards/01 và app-standards/03. Đã đo trên
  `postgres:16-alpine` (PostgreSQL 16.15) ngày 24/10/2026: FK ghép `(tenant_id, based_on_version_id)` với
  `ON DELETE SET NULL (based_on_version_id)` đặt NULL đúng cột đó và từ chối dòng trỏ sang phiên bản của tenant khác;
  với `ON DELETE SET NULL` không danh sách cột, lần xóa hỏng vì PostgreSQL đặt NULL cả `tenant_id`.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt c, theo các quyết định tạm cùng ngày của spec: `artifact_id` của phiên bản,
  `from_artifact_id` và `to_artifact_id` là FK ghép tới `uq_artifacts_tenant_id_id` (R2.18, TC29); trigger
  `studio.refuse_owning_workspace_change()` giữ `owning_workspace_id` không đổi, vì AAD của phong bì bí mật gắn nó
  (R2.19, TC30); FK tới `platform.workspaces` có index; index danh sách phá hòa `id DESC` và route phân trang theo
  `updated_at DESC, id DESC`; móc phát hành của `workflow` do workflow-engine cấp; `to_field_id` mà custom-objects thêm
  là FK ghép ON DELETE RESTRICT có index (ADR-0109 (Accepted) quyết 5).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt d, theo các quyết định tạm cùng ngày của spec: `seal` như nhau cho mọi
  loại, không đổi `stage`, không nhận `tighten_only` và tăng `row_version`, còn `LifecycleService` của agent-lifecycle
  chuyển giai đoạn trong cùng giao dịch (R2.7, R2.13, R2.16, TC27; ADR-0120 (Accepted) quyết 1); FK ghép tới
  `platform.workspaces` có ca âm chéo tenant (R2.18, TC29); `kind` có index `(kind)`; index danh sách không `kind`
  cho trang `/studio`; FK của spec khác tới hai bảng của ticket này chỉ là ví dụ, chủ là spec tạo FK.
- 2026-10-24 (agent): vòng sửa thứ tư, theo quyết định tạm cùng ngày của spec về quyền xóa của lane `offboarding`:
  `dw_app` có DELETE trên bốn bảng của ticket này, vì lane chỉ xóa bảng có trong `_CATALOG_PURGEABLE` và bỏ qua mục
  `_ORDERED_FIRST` của bảng khác; trên `studio.artifacts`, `studio.artifact_versions` và `studio.definition_manifests`,
  DELETE chỉ dùng được ở lượt xóa của offboarding nhờ trigger `platform.refuse_delete_outside_offboarding()` (23514 khi
  công ty khác `offboarding`; R3.8, TC31), còn `studio.dependencies` có DELETE thường vì `seal` thay dòng của phiên bản
  niêm phong lại sau khi về `draft` (R2.8, R3.1); thứ tự `_ORDERED_FIRST` giữ theo ADR-0109 (Accepted) Consequences,
  kèm lý do của từng FK RESTRICT; ca xóa cứng để thấy lỗi FK (R2.18, R3.3) chạy khi công ty ở `offboarding`.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt f, theo quyết định V4.17 của Đạt và các quyết định tạm cùng ngày của spec:
  chỉ mục duy nhất một phần giữ một phiên bản chưa phát hành mỗi thành phần, thay chỉ mục một nháp (R2.20); route
  `POST /api/v1/studio/artifacts/{id}/draft` tạo bản Nháp từ bản `live` hay phiên bản có số lớn nhất, trả 409
  `candidate_pending` khi có Bản ứng viên và `draft_exists` khi đã có bản Nháp (R2.21, R2.22, R2.23); ca bản Nháp niêm
  phong cạnh một Bản ứng viên rời R2.16, vì không còn xảy ra được; `_ORDERED_FIRST` thành `studio.dependencies`,
  `studio.artifact_versions`, `studio.artifacts`, mỗi bảng sau mọi bảng giữ một FK RESTRICT tới nó, để agent-lifecycle/04
  chèn mục `studio.gate_runs` giữa hai mục sau (TC21). Không thêm cạnh Blocked by.
- 2026-10-25 (agent): lượt h, theo H-2 (quyết định tạm cùng ngày của spec): bước 4 thôi thêm mục `_ORDERED_FIRST`; bốn
  bảng dùng bước mặc định của sổ bước xóa của foundations-hardening/07, thứ tự suy từ khóa ngoại `RESTRICT` của
  `pg_constraint`, và ca âm của R3.6 thành đột biến phép suy; dòng Blocked by không đổi.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk trong
  một subagent, vì ticket thêm migration và route; đo trên `60ed145`, đối chiếu mã sau ticket 01 `66ad6e7` và 03
  `5246de9`): 0 CRITICAL, 6 HIGH, đã sửa ở bước 1, 3, 5-8 và tiêu chí, mỗi cái một dòng Quyết định 3/11/2026 của spec
  với Nếu sai thì: (1) UPDATE theo cột thay UPDATE cả bảng (studio-skeleton:R2.7), `studio.artifact_kinds` vào
  `_PLATFORM_REFERENCE_TABLES`; (2) tầm qua `platform.workspace_reach`, danh sách lọc trong SQL, workspace sở hữu là
  workspace hành động, xóa mềm là 404, test âm trên mọi route; (3) hợp đồng `extract`, phân giải `artifact` về bản
  `live` `FOR SHARE`, `ck_dependencies_artifact_target`, thân `dw.definition_manifest/v1` và hai hàm ticket 04 gọi lại;
  (4) `GET .../draft`, `no_draft`, chủ của hai ETag; (5) một luật khóa dòng thành phần cho `save_draft`, `create_draft`
  và `seal`; (6) loại fixture ở `dw_studio.testing`, vào app qua `studio_kinds=`, dựng và gỡ theo module. Kèm (MEDIUM,
  sửa luôn vì rẻ): `Idempotency-Key` tùy chọn ở hai `POST` (ADR-0108 (Accepted) quyết 4).
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (builder check mới trên bản đã sửa): 4 HIGH, đã sửa:
  ba tiêu chí khóa đồng thời không đỏ được vì bản sửa đầu chồng ba lớp rào (nay một luật khóa và một ca chờ cho mỗi
  thao tác); ca `FOR SHARE` đặt `evaluating` trong cùng giao dịch chưa commit; vi phạm chỉ mục ánh xạ ra `draft_exists`;
  danh sách vào `REGISTERED`/`EXPECTED` của kiểm dạng kế hoạch (app-standards R6); tài nguyên bật R3 của app-standards
  (`version`, `If-Match` ở `DELETE` và `POST .../draft`, `EXEMPT_WRITES` rỗng). Kèm: `save_draft` xóa số và mã băm cũ,
  `versions` chỉ trả phiên bản ngoài `draft`, `to_key = to_artifact_id::text` trong CHECK, TC30 của spec theo quyền cột,
  `studio_kinds` qua `create_app`, nguồn `offboarding.py:117-119`.
- 2026-11-03 (agent): đối chiếu studio-skeleton/02 (hợp đồng đã ĐẠT, chưa dựng): không mâu thuẫn về nội dung. Hai ticket
  dựng trong một lượt và vào `main` trong một lần push (Comments 28/10/2026 của ticket đó); cạnh Blocked by tới nó được
  thỏa trong cùng lượt, các bước của studio-skeleton/02 đi trước. Ticket này thêm tham số từ khóa `kinds` cho
  `build_studio(container, settings)` của bước 5 ticket đó (và `studio_kinds` cho `build_container`, `create_app`), và lấp `dw_studio.core` cùng gói con `dw_studio.testing`
  theo luật bước 1 ticket đó; bảng tenant đầu tiên của ticket này là lúc bước 10 ticket đó thêm `studio` vào
  `_PLATFORM_SCHEMAS`.
- 2026-11-03 (agent): MEDIUM và LOW của gate, chưa sửa, cho người dựng:
  (a) `save_draft` gọi `ensure_hashable` sau `to_nfc`, để bản Nháp có số thực hay số nguyên ngoài ±(2^53−1) bị 422 kèm
  con trỏ lúc lưu, không phải lúc niêm phong hay lúc ticket 04 tính mã băm tạm;
  (b) `seal` không nhận ngữ cảnh truy cập; lệnh gửi của agent-lifecycle/03 kiểm khóa gửi. Một bên gọi `seal` mới phải tự
  kiểm khóa gửi của loại (failure-modes #5); agent-lifecycle/03 thêm một ca âm gọi route gửi không có khóa gửi;
  (c) `labels` chưa có giới hạn: đề nghị tối đa 20 nhãn, mỗi nhãn `^[a-z0-9][a-z0-9_-]{0,39}$`, vượt → 422;
  (d) `change_note` chưa có bên ghi trong ticket này (failure-modes #1): lệnh gửi của agent-lifecycle/03 ghi nó, hoặc cột
  rời đi; `studio.artifact_versions` không có `created_at`, nên `GET .../versions` không có thời điểm niêm phong;
  (e) rollback của ADR-0120 (Accepted) quyết 1 ("một phiên bản mới chép từ phiên bản cũ") chưa có route: `POST
  .../draft` chỉ chép bản `live` hay bản số lớn nhất; chủ là agent-lifecycle hay một ticket sau, có thể thêm
  `from_version_no` tùy chọn;
  (f) `platform.refuse_delete_outside_offboarding()` là `SECURITY DEFINER` với `search_path` ghim và `REVOKE ... FROM
  PUBLIC`, như `platform.guard_contact_suppression()` (`db/migrations/versions/0c3e9392cc06_marketing_send_floor.py:146`),
  để đọc được `platform.tenants`; hai hàm cùng một luật, nên một ticket sau có thể gắn hàm mới lên
  `platform.contact_suppressions` và gỡ hàm cũ;
  (g) `platform.workspace_reach` bỏ workspace đã lưu trữ, nên thành phần của workspace đã lưu trữ thành 404 với mọi
  người, kể cả độ sâu `tenant`; đúng với ADR-0104 (Accepted), nhưng dọn những thành phần đó cần bỏ lưu trữ trước;
  (h) tham chiếu `artifact` trỏ chính thành phần đang niêm phong ghim bản `live` của nó; nên từ chối bằng
  `dependency_unresolved`;
  (i) niêm phong đồng thời hai thành phần trỏ nhau (A dùng B, B dùng A) có thể deadlock (40P01) giữa `FOR UPDATE` của
  mình và `FOR SHARE` của bên kia: ánh xạ 40P01 ra 409 `conflict` để bên gọi thử lại, không 500;
  (j) loại thật đăng ký khóa `active` mà kiểm qua `workspace_reach` trong SQL: khai mỗi khóa là hằng mô-đun tên
  `*_SCOPE`, để test (c) của `test_permission_catalogue.py` thấy chỗ kiểm;
  (k) Kiểm soát TC21 của spec còn "gỡ một mục thứ tự → test đỏ" và dẫn studio-skeleton:R4.3, cũ từ trước H-2; tiêu chí
  R3.6 của ticket này (đột biến phép suy, R4.2) là bản đúng;
  (l) LOW: trước agent-lifecycle/03, `stage` chỉ có CHECK, chưa có `studio.guard_version_stage()`, nên `dw_app` đổi được
  `live` về `draft` rồi sửa `document`; khoảng hở đóng khi agent-lifecycle/03 vào.
- 2026-11-03 (agent): bảng va chạm cho lịch hai lượt dựng. Lượt này là studio-skeleton/02 cộng ticket này.
  connections-and-vault/02 (`ready-for-agent`): cùng chuỗi revision Alembic, `test_rls_coverage.py` (danh sách bảng toàn
  tenant), `test_privileges.py`, `pyproject.toml` gốc và `uv.lock` (studio-skeleton/02 thêm `dw-studio`, ticket kia ghim
  `cryptography`), `scripts/verify_architecture.py` (`IMPORT_TO_DIST`); không chạy song song. usage-and-limits/02
  (`ready-for-agent`): cùng chuỗi revision, gói mới `dw_usage` đăng ký ở đúng các chỗ studio-skeleton/02 đăng ký
  `dw_studio` (`pyproject.toml` gốc, `uv.lock`, hợp đồng import-linter, `scripts/verify_architecture.py`, COPY của
  Dockerfile, `apps/api/pyproject.toml`), `wiring.py`, snapshot OpenAPI và kiểu TS (cả hai thêm route); không chạy song
  song. Ticket này không sửa `offboarding.py` (chỉ `test_offboarding.py`), nên không chung tệp đó với hai ticket kia.
- 2026-11-03 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-03 (agent): resolved, cùng lượt với studio-skeleton/02. Revision `67071483caa6` (sau `555dad01f629`).
    - Quyết định (agent, theo ủy quyền 31/10/2026): mọi FK ghép liệt kê cột của mình trước, `(<cột>, tenant_id) -> (id, tenant_id)`, nên `NAMING_CONVENTION` cho tên riêng từng khóa (`fk_dependencies_to_version_id_artifact_versions`, ...); PostgreSQL 16 khớp UNIQUE `(tenant_id, id)` theo tập cột (đã đo). Nếu sai thì: giữ thứ tự `(tenant_id, <cột>)` và đặt tên tay.
    - Quyết định (agent, theo ủy quyền 31/10/2026): chỉ mục một phiên bản chưa phát hành tên `uq_artifact_versions_unreleased` (tên theo quy ước sẽ trùng chỉ mục một Đang dùng của agent-lifecycle trên cùng cột); `ck_artifact_versions_sealed` đòi cả `content_hash` lẫn `definition_hash` ngoài `draft` (spec nêu `definition_hash`; đóng khi lỗi); `studio.dependencies` có `id` UUIDv7 làm khóa chính (keyset của bản xuất offboarding); `studio.definition_manifests` có FK `tenant_id` tới `platform.tenants` RESTRICT. Nếu sai thì: một revision sửa.
    - Quyết định (agent, theo ủy quyền 31/10/2026), các MEDIUM rẻ đã làm: `ensure_hashable` sau `to_nfc` ở lúc tạo và lúc lưu, 422 kèm con trỏ (a); nhãn tối đa 20, mỗi nhãn `^[a-z0-9][a-z0-9_-]{0,39}$`, không lặp (c); `platform.refuse_delete_outside_offboarding()` là SECURITY DEFINER, `search_path` ghim, REVOKE khỏi PUBLIC (f); tham chiếu tới chính thành phần đang niêm phong là `dependency_unresolved` (h); 40P01 ra 409 `concurrent_write` (i). Chưa làm: (b) `seal` không kiểm khóa gửi, agent-lifecycle/03 kiểm; (d) không thêm `created_at` cho phiên bản; (e) route rollback; (g) workspace lưu trữ; (j) hằng `*_SCOPE` khi có loại thật; (l) khoảng hở `stage` đến agent-lifecycle/03. Nếu sai thì: bỏ phần đã làm ở một ticket sau.
    - Quyết định (agent, theo ủy quyền 31/10/2026): tầm do `platform.workspace_reach` trả về tập workspace cho từng khóa, rồi vào câu SQL danh sách là `kind = :k AND owning_workspace_id = ANY(:ws)` cho mỗi loại, lọc trong câu lệnh trên index, không lọc sau; lọc `kind` chưa đăng ký trả trang rỗng, không 422; thứ tự kiểm 404 rồi 403 rồi 412; `GET .../versions` không phân trang; `PATCH` không nhận `Idempotency-Key` (ticket chỉ đòi hai `POST`); mục bao đóng lấy `kind` là `to_kind` của dòng phụ thuộc. Nếu sai thì: đổi ở `ArtifactService`, một chỗ.
    - Quyết định (agent, theo ủy quyền 31/10/2026): kiểm dạng kế hoạch đăng ký route ở dạng lọc `kind` (vị từ `("kind",)`), dạng không lọc có test riêng cùng ca gỡ index đỏ; bench gieo 120 thành phần, một loại hiếm, và `ANALYZE`, vì với vài dòng hai index cùng giá và bộ lập kế hoạch chọn index kia cho trang có con trỏ (đã đo). Nếu sai thì: cho bộ kiểm nhận hai dạng một route.
    - Đo khi viết test (failure-modes #3): bỏ `FOR SHARE` mà test xóa mềm chờ vẫn xanh, vì FK của dòng phụ thuộc mới cũng khóa KEY SHARE đích; test viết lại để xóa mềm bắt đầu giữa lúc đọc đích và lúc ghi dòng phụ thuộc, nay đỏ khi bỏ. Ba ca khóa dòng thành phần cũng xanh khi bỏ khóa (UPDATE và FK cũng chờ), nên viết lại: bên giữ khóa đổi phiên bản rồi commit, lệnh ghi phải trả lời theo trạng thái mới; bỏ khóa ở `save_draft`, `create_draft` hay `seal` thì đúng ca đó đỏ, nêu tên.
    - Test: `packages/python/dw_studio/tests/integration/test_artifact_envelope.py` 34 ca (TC1, TC2, TC3, TC4, TC5, TC6, TC27, TC29, TC30, TC31, R2.6-R2.8, R2.16, R2.17, R2.20, R2.23), `test_kind_registry.py` 3 ca (R2.15, hai ca trồng lỗi), `apps/api/tests/integration/test_studio_artifacts.py` 50 ca qua HTTP (R2.1-R2.5, R2.10-R2.12 tham số theo mọi route `{id}` và cả hai loại, R2.15, R2.21-R2.23, R3.2-R3.5, idempotency), `test_offboarding.py` TC21, `test_privileges.py` quyền theo cột, `test_rls_coverage.py` bốn bảng toàn tenant và bảng tham chiếu, `test_plan_shape.py`, unit `packages/python/dw_studio/tests/unit/test_artifact_domain.py`. 221 test tích hợp mà hai ticket thêm hay sửa xanh trong một tiến trình, `test_permission_catalogue.py` chạy sau module dùng loại fixture.
    - `mutations/02.yaml` 27 đột biến, chưa chạy (lượt kiểm tra cuối).
    - `reviewing-feature-security` (đọc): tenant: RLS ENABLE và FORCE theo tenant ở bốn bảng, phiên gắn tenant mỗi giao dịch, FK ghép chặn mọi dòng sang tenant khác kể cả vai bỏ qua RLS, tenant B nhận 404 ở mọi route; quyền: tầm từ `workspace_reach` ở chỗ ghi, người chỉ đọc nhận 403 ở cả bốn route ghi và ở `POST`, loại không đăng ký thì không ai đọc được (đóng khi lỗi); audit cùng giao dịch, lỗi giữa chừng không để dòng nào; provenance: `to_artifact_id`, `to_version_id` RESTRICT, xóa cứng khi offboarding còn dòng phụ thuộc thì lỗi FK; vòng đời: bộ dựng loại fixture gỡ dòng và khóa của nó và khẳng định không còn gì. Autonomy và nội dung không tin: không áp dụng (lỗi tài liệu chỉ mang con trỏ và mã, không mang giá trị).
    - Quyết định (agent, theo ủy quyền 31/10/2026): một commit cho cả studio-skeleton/02 và tenant-config/02, không hai: `build_studio` dựng `ArtifactService` và router của nó, nên commit chỉ có seam không import được và làm hỏng bisect, và seam không vào `main` khi rỗng (ADR-0100 (Accepted) điểm 6). Nếu sai thì: tách lại bằng một seam tạm có route thử.
