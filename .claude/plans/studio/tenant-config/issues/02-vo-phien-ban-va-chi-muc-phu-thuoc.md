# 02 — Vỏ phiên bản dùng chung và chỉ mục phụ thuộc ghi trong giao dịch gửi kiểm định

Status: needs-triage
Blocked by: 01, .claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md, .claude/plans/studio/org-and-principals/issues/01-khoa-don-vi-va-siet-realm.md, .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md, .claude/plans/studio/app-standards/issues/01-vo-loi-problem-json.md, .claude/plans/studio/app-standards/issues/03-quy-uoc-api-danh-sach-va-sua.md
Area: studio
Yêu cầu: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.8, R2.9, R2.10, R2.11, R2.12, R2.13, R2.14, R2.15, R2.16, R2.17, R2.18, R2.19, R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.8, TC1, TC2, TC3, TC4, TC5, TC6, TC7, TC21, TC24, TC27, TC29, TC30, TC31

## Mục tiêu

Mọi loại thành phần Studio có một vỏ phiên bản chung trong `dw_studio`: một nháp lưu bằng khóa lạc
quan, bước niêm phong cấp số không dùng lại và mã băm, như nhau cho mọi loại và không đổi giai đoạn, Nơi đang dùng
ghi trong cùng giao dịch niêm phong, chặn xóa thứ đang được dùng, và không lộ tên ngoài quyền (spec R2, R3). Route
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
      `fixture_gateless` (`false`) bằng vai migrator trong một fixture pytest phạm vi session và gỡ khi xong;
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
      `(artifact_id, version_no)`; một dòng `draft` mỗi thành phần (partial unique); `document_schema`
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
      `(tenant_id, to_kind, to_key)`. `to_field_id` không có ở đây: custom-objects thêm cột và FK ghép
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
   tenant, ADR-0100 (Accepted) quyết 5). Grant: `dw_app` SELECT, INSERT, UPDATE và DELETE trên `studio.artifacts`
   và `studio.artifact_versions`; SELECT, INSERT và DELETE trên `studio.dependencies` và
   `studio.definition_manifests`; SELECT trên `studio.artifact_kinds`. Cả bốn bảng có DELETE vì lane `offboarding` xóa
   bằng `dw_app` và chỉ xóa bảng có trong `_CATALOG_PURGEABLE`; trên ba bảng của trigger ở bước 2, DELETE chỉ dùng được
   ở lượt xóa của offboarding. Khẳng định trong
   `test_privileges.py`; `test_rls_coverage.py` thấy cả bốn bảng có `tenant_id`, và mỗi bảng có một dòng lý
   do trong danh sách bảng toàn tenant của test đó (định nghĩa có `owning_workspace_id`, phiên bản và chỉ mục
   phụ thuộc là con của thành phần, bản kê định nghĩa định danh theo nội dung; DO-01).
4. Offboarding, trên `offboarding.py` và `test_offboarding.py` mà foundations-hardening/07 đã viết lại
   (`_CATALOG_COLUMNS`, `export_rows`): `_ORDERED_FIRST` thêm theo thứ tự `studio.dependencies`, `studio.artifacts`,
   `studio.artifact_versions` (ADR-0109 (Accepted) Consequences), bảng tham chiếu trước bảng mà FK ON DELETE RESTRICT
   của nó giữ (studio-skeleton:R4.2): `studio.dependencies` trước vì `to_artifact_id` và `to_version_id` giữ hai bảng
   kia (đã đo: xóa `studio.artifacts` trước khi gỡ cạnh phụ thuộc thì hỏng), `studio.artifacts` trước phần xóa theo chữ
   cái vì `owning_workspace_id` giữ `platform.workspaces`; `studio.definition_manifests` không có FK RESTRICT nào nên ở
   phần xóa theo chữ cái. `purge_rows` bỏ qua mục `_ORDERED_FIRST` của bảng không có trong `_CATALOG_PURGEABLE`
   (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:187-188`), nên bốn bảng xóa được
   nhờ DELETE của bước 3, không bảng nào có dòng `STUDIO_EXCLUSIONS`; `test_offboarding.py` purge một tenant có hai
   thành phần phụ thuộc nhau ở hai workspace (TC21).
5. `ArtifactKindRegistry` trong lõi `dw_studio`, đăng ký ở `build_studio` (ADR-0100 (Accepted) quyết 6):
   mỗi mục có `kind`, `document_schema`, khóa đọc, khóa ghi và khóa gửi của loại, và `publish_hook`, không giá trị
   mặc định (R2.15; mỗi spec đăng ký khóa của mình theo quy ước `studio.<area>.<verb>` của tenant-rbac:R1.6),
   `validate(document)` trả mọi lỗi kèm con trỏ JSON, `extract(document)` thuần trả các phụ thuộc. `publish_hook` là
   móc phát hành mà spec của loại cấp (dịch vụ metadata của custom-objects cho `object`, custom-objects:R1.1; móc của
   workflow-triggers cho `endpoint`; móc của workflow-engine cho `workflow`, workflow-engine:R1.4), là "publish hook"
   của ADR-0109 (Accepted) quyết 1: agent-lifecycle gọi nó trong giao dịch đưa phiên bản lên `live`, ở handler
   `.decided` và ở nhánh chỉ siết (agent-lifecycle:R2.9, agent-lifecycle:R5.5); móc không đổi giai đoạn, không ghi
   `studio.version.published`, và `seal` không gọi nó. Hai loại fixture khai một móc không làm gì. Mục không giữ cờ
   cổng: cờ chỉ ở cột `has_quality_gate` của `studio.artifact_kinds`. Test ở composition root: tập loại của registry
   bằng tập dòng của `studio.artifact_kinds`, mỗi khóa của mỗi mục có trong danh mục quyền, và mỗi mục có
   `publish_hook`.
6. `ArtifactService` (lõi `dw_studio`, constructor injection), mỗi thao tác một kiểm quyền: khóa đọc
   hay khóa ghi mà mục registry của loại khai, ở độ sâu chạm tới `owning_workspace_id`, đọc từ
   `platform.effective_grants` (tenant-rbac/02, ADR-0104 (Accepted) quyết 5); tenant khác hay không đọc được →
   404, đọc được mà không ghi được → 403 `permission_denied` (TC24). Test kiểm quyền tham số hóa theo mọi loại
   đã đăng ký, để loại sau (như `workflow` của workflow-engine/01) chạy cùng test.
    - `create`: thành phần, nháp đầu và audit `studio.artifact.created` trong một giao dịch; Tên API sai
      mẫu → 422 `validation_failed`; vi phạm unique `(tenant_id, kind, api_name)` ánh xạ theo tên ràng
      buộc → 409 `conflict`, `details.reason_code` `api_name_taken`.
    - `save_draft`: `to_nfc` ở biên, `If-Match` so với `row_version`; khớp → thay tài liệu, tăng
      `row_version`, trả ETag mới; lệch → 412 `precondition_failed`, `details.reason_code`
      `stale_version`; thiếu → 428 (ADR-0108 (Accepted) quyết 3). Audit `studio.artifact.draft_saved`
      chỉ mang `row_version`.
    - `update`: `api_name`, `labels` với `If-Match`; `api_name` khi đã có phiên bản từng `live` → 409
      `api_name_immutable` trước khi trigger phải chặn; audit `studio.artifact.updated` với tên trường.
    - `seal(uow, artifact_id, expected_row_version)`: trong giao dịch của bên gọi, khóa dòng thành phần
      (`SELECT ... FOR UPDATE`), so `expected_row_version` với `row_version` của nháp, lệch → từ chối với
      `details.reason_code` `stale_version` trước khi cấp số (R2.17; `expected_row_version` là giá trị `If-Match`, ETag
      của bản Nháp, mà lệnh gửi của agent-lifecycle nhận, trả 412 `precondition_failed` khi lệch và 428 khi thiếu,
      agent-lifecycle:R2.12, agent-lifecycle:R2.13; ADR-0109 (Accepted) quyết 2), `validate` (lỗi → 422
      `validation_failed` liệt kê mọi lỗi trong `errors[]`), `version_no = last_version_no + 1`, `content_hash` qua
      `dw_kernel.canonical`, bao đóng qua `extract` (mỗi thành phần ghim `(kind, key, version, content_hash)`),
      `definition_hash` là mã băm của bao đóng, ghi `studio.definition_manifests` `ON CONFLICT DO NOTHING`, thay các
      dòng `studio.dependencies` của phiên bản (xóa dòng mà lần niêm phong trước của một phiên bản đã về `draft` ghi,
      R2.8, rồi ghi bộ mới), tăng `row_version` của nháp (lần niêm phong thứ hai cùng `expected_row_version` nhận
      `stale_version`), rồi trả id phiên bản cùng hai mã băm. `seal` như nhau cho mọi loại: không đọc
      `has_quality_gate`, không đổi `stage` (phiên bản ra khỏi `seal` vẫn ở `draft`) và không đổi dòng phiên bản nào
      khác của thành phần, kể cả Bản ứng viên đang chờ ở `awaiting_approval`, mà `compared_live_hash` cũ của nó chặn nó
      thay một bản chỉ siết lên `live` sau nó (R2.13, R2.16; agent-lifecycle:R1.8, agent-lifecycle:R5.9). Chuyển giai
      đoạn sau `seal` là của `LifecycleService` của agent-lifecycle/03 và agent-lifecycle/04 trong cùng giao dịch
      (`draft → evaluating` khi `has_quality_gate` là true, `draft → awaiting_approval` khi false, `draft → live` ở
      nhánh chỉ siết sau khi gỡ bản `live` trước), với `studio.guard_version_stage()` là hàng rào cuối
      (agent-lifecycle:R1.4, agent-lifecycle:R1.6, agent-lifecycle:R2.8, agent-lifecycle:R2.9; ADR-0120 (Accepted)
      quyết 1); cột `tighten_only` và `compared_live_hash` do agent-lifecycle thêm và ghi ở mọi lần gửi
      (agent-lifecycle:R2.10), không do ticket này. Không audit: route gửi kiểm định của agent-lifecycle/03 audit trong
      cùng giao dịch, kể cả `studio.version.published` của nhánh chỉ siết.
    - `soft_delete`: đặt `deleted_at`; `ck_artifacts_not_in_use` → 409 `conflict`, `details.reason_code`
      `artifact_in_use`, `details` gồm số đếm theo giai đoạn; audit `studio.artifact.deleted`.
    - `dependents`: nhóm theo giai đoạn (`live`, ứng viên); tên chỉ cho bên người gọi đọc được theo cùng
      kiểm quyền, còn lại chỉ đếm (TC7). `draft_dependencies`: chạy `extract` trên nháp, không ghi dòng
      nào.
7. Route trong nhóm `/api/v1/studio` của studio-skeleton/02, lỗi theo vỏ problem+json
   (ADR-0108 (Accepted)): `POST /api/v1/studio/artifacts`, `GET /api/v1/studio/artifacts` (keyset theo
   `updated_at DESC, id DESC`, lọc `kind`, `label`; index danh sách có `kind` khi lọc theo loại, index không `kind`
   khi không lọc), `GET /api/v1/studio/artifacts/{id}`,
   `PATCH /api/v1/studio/artifacts/{id}`, `PUT /api/v1/studio/artifacts/{id}/draft`,
   `GET /api/v1/studio/artifacts/{id}/versions`, `GET /api/v1/studio/artifacts/{id}/versions/{version_no}`,
   `DELETE /api/v1/studio/artifacts/{id}`, `GET /api/v1/studio/artifacts/{id}/dependents`,
   `GET /api/v1/studio/artifacts/{id}/draft/dependencies`. Mọi id là UUID. `make generate-contracts`.
8. Loại `fixture` chỉ trong test: tài liệu có trường `uses` trỏ tới thành phần khác, `extract` trả một
   phụ thuộc `artifact` cho mỗi phần tử; test fixture khẳng định đúng tập dòng ghi ra. Loại
   `fixture_gateless` chỉ trong test, cùng tài liệu, dòng `studio.artifact_kinds` của nó nêu
   `has_quality_gate = false`. Khóa đọc, ghi và gửi của hai loại là khóa chỉ trong test, chèn vào
   `platform.permissions` bằng vai migrator trong cùng fixture pytest phạm vi session và gỡ khi xong; câu INSERT nêu mọi
   cột NOT NULL có lúc đó, gồm `risk` của tenant-rbac/01 và `tenant_grantable` của tenant-rbac/02
   (ADR-0104 (Accepted) quyết 1), nên ticket này chờ tenant-rbac/02. Ca cần một phiên bản ở giai đoạn khác `draft`
   (R2.8, R2.9, R2.10, R2.16, R3.3, R3.4) đặt `stage` bằng vai migrator trong test, vì bên chuyển giai đoạn là
   `LifecycleService` của agent-lifecycle/03, ticket chờ ticket này.

## Tiêu chí chấp nhận

- [ ] R2.1: `POST` tạo thành phần có id UUIDv7, một nháp và một audit `studio.artifact.created` trong một
      giao dịch; lỗi giữa chừng không để lại dòng nào.
- [ ] R2.2: Tên API 40 ký tự được nhận; 41 ký tự, 1 ký tự, `Lead` hay `1lead` → 422, không dòng nào.
- [ ] R2.3: Tên API trùng thành phần chưa xóa cùng loại → 409 `api_name_taken`; sau khi thành phần cũ bị
      xóa mềm, cùng tên tạo được; tenant khác dùng cùng tên được.
- [ ] R2.4: `PUT` nháp với `If-Match` đúng → tài liệu mới, `row_version` tăng 1, ETag mới.
- [ ] R2.5 (TC3): `PUT` nháp với `If-Match` cũ → 412 `stale_version`, nháp không đổi; INSERT nháp thứ hai
      cùng thành phần → lỗi partial unique; bỏ so `row_version` → test đỏ.
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
- [ ] R2.12 (TC24): người đọc được mà không có quyền ghi `PUT` nháp → 403 `permission_denied`, nháp không
      đổi.
- [ ] R2.13 (TC27): niêm phong nháp hợp lệ của `fixture` (`true`) và của `fixture_gateless` (`false`) cấp số
      phiên bản và hai mã băm như R2.7 và để cả hai ở `draft`, không yêu cầu phê duyệt nào; để `seal` đổi `stage`
      theo `has_quality_gate` → test đỏ.
- [ ] R2.14 (TC27): INSERT dòng `studio.artifact_kinds` không nêu `has_quality_gate` bằng vai migrator → lỗi NOT
      NULL; thêm DEFAULT cho cột → test đỏ.
- [ ] R2.15 (TC24): mỗi mục registry khai đủ khóa đọc, ghi và gửi, mỗi khóa có trong danh mục quyền, và một
      `publish_hook`; gỡ khóa đọc hay móc của `fixture` → test registry đỏ; test kiểm quyền tham số hóa chạy cho mọi
      loại đã đăng ký.
- [ ] R2.16 (TC27): `fixture_gateless` có một Bản ứng viên ở `awaiting_approval`; niêm phong một nháp mới của cùng
      thành phần → bản mới ở `draft` có số và hai mã băm, dòng Bản ứng viên giữ nguyên giai đoạn và mọi cột; để `seal`
      đổi Bản ứng viên → test đỏ. Nhánh chỉ siết `draft → live` là của `LifecycleService` (agent-lifecycle:R2.9, AL4),
      và ca duyệt Bản ứng viên đó rồi về `draft` với `base_changed` là AL19, hai ca chạy ở agent-lifecycle/04.
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
- [ ] R2.19 (TC30): `dw_app` UPDATE `owning_workspace_id` của một thành phần sang workspace khác cùng tenant → trigger
      từ chối, cột giữ nguyên; cùng lệnh bằng vai migrator → từ chối; UPDATE `labels` của cùng dòng → được; gỡ trigger
      → test đỏ.
- [ ] R3.1 (TC6): lỗi chèn giữa giao dịch niêm phong → không số phiên bản, không dòng
      `studio.dependencies`, không dòng `studio.definition_manifests`; làm hỏng `extract` của `fixture`
      → test fixture đỏ.
- [ ] R3.1: đưa phiên bản v3 về `draft`, đổi tài liệu rồi niêm phong lại → dòng `studio.dependencies` của phiên bản là
      bộ của lần niêm phong sau, không còn dòng nào của lần trước; bỏ bước xóa của `seal` → test đỏ.
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
      nguyên mọi dòng; gỡ mục `studio.dependencies` khỏi `_ORDERED_FIRST` → test đỏ; test phủ offboarding
      (studio-skeleton:R4.1, studio-skeleton:R4.2) xanh với bốn bảng không có trong `STUDIO_EXCLUSIONS`; thu DELETE của
      `dw_app` trên một trong bốn bảng → test phủ đỏ, nêu tên bảng.
- [ ] R3.8 (TC31): `dw_app` DELETE một dòng `studio.artifacts`, `studio.artifact_versions` hay
      `studio.definition_manifests` của công ty `active` → 23514, dòng còn; cùng lệnh khi công ty ở `offboarding` → xóa
      được; gỡ phép kiểm trạng thái khỏi `platform.refuse_delete_outside_offboarding()` → test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:46`; spec: Dữ liệu.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:108-114`; spec: R3.6,
  TC21.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:98-101`; spec: R3.8, TC31;
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
