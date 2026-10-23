# 02 — Vỏ phiên bản dùng chung và chỉ mục phụ thuộc ghi trong giao dịch gửi kiểm định

Status: needs-info (DO-05)
Blocked by: 01, .claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md
Area: studio
Yêu cầu: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.8, R2.9, R2.10, R2.11, R2.12, R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, TC1, TC2, TC3, TC4, TC5, TC6, TC7, TC21, TC24

## Mục tiêu

Mọi loại thành phần Studio có một vỏ phiên bản chung trong `dw_studio`: một nháp lưu bằng khóa lạc
quan, bước niêm phong cấp số không dùng lại và mã băm rồi đưa phiên bản sang `evaluating`, Nơi đang
dùng ghi trong cùng giao dịch niêm phong, chặn xóa thứ đang được dùng, và không lộ tên ngoài quyền
(spec R2, R3). Route gửi kiểm định của agent-lifecycle/03 gọi bước niêm phong này; ticket này không
viết chuyển giai đoạn nào khác.

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên) trong schema `studio` của studio-skeleton/01, chép nguyên
   văn ràng buộc ở mục Dữ liệu của spec:
    - `studio.artifacts`: `id` UUIDv7; `kind` CHECK đúng các loại của `ArtifactKindRegistry`;
      `api_name` `^[a-z][a-z0-9_]{1,62}$`, unique `(tenant_id, kind, api_name)` khi
      `deleted_at IS NULL`; FK `(tenant_id, owning_workspace_id)` tới `platform.workspaces (tenant_id, id)`
      ON DELETE RESTRICT; `labels text[] NOT NULL DEFAULT '{}'` (bộ lọc `label` của danh sách đọc);
      `origin jsonb` NULL (domain-packs ghi và đọc nguồn gốc gói); `last_version_no integer NOT NULL DEFAULT 0`; `row_version integer NOT NULL`;
      `deleted_at timestamptz` NULL; `created_at`, `updated_at` `timestamptz NOT NULL`; index danh sách
      `(tenant_id, kind, updated_at DESC, id)`.
    - `studio.artifact_versions`: `stage` NOT NULL CHECK (`draft`, `evaluating`, `awaiting_approval`,
      `live`, `retired`), không DEFAULT; `version_no` NULL chỉ khi `stage = 'draft'`, unique
      `(artifact_id, version_no)`; một dòng `draft` mỗi thành phần (partial unique); `document_schema`
      `^dw\.[a-z_]+/v[0-9]+$`; `document` là jsonb object tối đa 1 MiB,
      `CHECK (document::text IS NFC NORMALIZED)`; `content_hash`, `definition_hash` khớp
      `^sha256:[0-9a-f]{64}$`, `definition_hash` NOT NULL ngoài `draft`; `row_version integer NOT NULL`;
      `artifact_id` FK CASCADE; `based_on_version_id` FK ON DELETE SET NULL; `change_note` NULL.
    - `studio.definition_manifests`: khóa chính `(tenant_id, hash)`, `body` jsonb NFC tối đa 1 MiB, chỉ
      INSERT.
    - `studio.dependencies`: `from_version_id`, `from_artifact_id` FK CASCADE; `to_kind` CHECK
      (`artifact`, `field`, `picklist_value`, `platform_artifact`, `connector`, `mcp_tool`, `binding`,
      `node_type`); `to_key`, `to_version`, `to_hash`; `to_artifact_id`, `to_version_id` FK RESTRICT, mỗi
      FK một index; `usage` CHECK (`read`, `write`, `compare`, `invoke`, `bind`, `display`); `path` con
      trỏ JSON; index `(tenant_id, to_kind, to_key)`. `to_field_id` không có ở đây: custom-objects thêm
      cột và FK cùng bảng field của nó.
    - `uq_workspaces_tenant_id_id` trên `platform.workspaces (tenant_id, id)` cho FK ghép.
    - Ticket này chưa có loại thật: `ck_artifacts_kind` tạo với tập rỗng
      (`kind = ANY ('{}'::text[])`); mỗi spec đăng ký loại thêm giá trị của nó bằng migration riêng, cùng
      lúc với mục registry. Test tích hợp của ticket này thêm giá trị `fixture` bằng vai migrator trong
      một fixture pytest phạm vi session và gỡ khi xong; migration không bao giờ chứa `fixture`.
2. Trigger trong cùng revision, tên ràng buộc theo `NAMING_CONVENTION`, ánh xạ ra lỗi API theo tên:
    - `studio.refuse_sealed_content_change()`: BEFORE UPDATE trên `studio.artifact_versions`, từ chối đổi
      `document`, `document_schema`, `content_hash`, `definition_hash`, `version_no`, `artifact_id` khi
      `OLD.stage <> 'draft'` (TC1).
    - `studio.refuse_api_name_change()`: BEFORE UPDATE OF `api_name` trên `studio.artifacts`, từ chối khi
      thành phần có phiên bản ở `live` hay `retired` (TC4; DO-08, tạm).
    - `studio.refuse_soft_delete_in_use()`: BEFORE UPDATE OF `deleted_at`, khi `deleted_at` chuyển từ
      NULL sang có giá trị mà một dòng `studio.dependencies` của thành phần khác trỏ tới nó từ một phiên
      bản `evaluating`, `awaiting_approval` hay `live`: `ERRCODE 23503`, ràng buộc
      `ck_artifacts_not_in_use` (TC5; FK chặn DELETE cứng).
    - `updated_at` do `platform.touch_updated_at()` giữ, nhường giá trị câu lệnh nêu (CLAUDE.md "Data
      model rules").
3. RLS ENABLE và FORCE, policy `tenant_isolation_<bảng>` chỉ theo `app.tenant_id` (định nghĩa toàn
   tenant, ADR-0100 (Proposed) quyết 5). Grant: `dw_app` SELECT, INSERT, UPDATE trên `studio.artifacts`
   và `studio.artifact_versions` (không DELETE); SELECT, INSERT trên `studio.dependencies` và
   `studio.definition_manifests`. Khẳng định trong `test_privileges.py`; `test_rls_coverage.py` thấy cả
   bốn bảng.
4. Offboarding: `_ORDERED_FIRST` thêm theo thứ tự `studio.dependencies`, `studio.artifacts`,
   `studio.artifact_versions` (đã đo: xóa `studio.artifacts` trước khi gỡ cạnh phụ thuộc thì hỏng);
   `test_offboarding.py` purge một tenant có hai thành phần phụ thuộc nhau ở hai workspace (TC21).
5. `ArtifactKindRegistry` trong lõi `dw_studio`, đăng ký ở `build_studio` (ADR-0100 (Proposed) quyết 6):
   mỗi mục có `kind`, `document_schema`, khóa quyền đọc và ghi của loại (tenant-rbac/01 đăng ký khóa),
   `validate(document)` trả mọi lỗi kèm con trỏ JSON, `extract(document)` thuần trả các phụ thuộc. Test
   ở composition root: tập loại của registry bằng tập giá trị của `ck_artifacts_kind` đọc từ
   `pg_constraint`.
6. `ArtifactService` (lõi `dw_studio`, constructor injection), mỗi thao tác một kiểm quyền: quyền đọc
   hay ghi của loại ở độ sâu chạm tới `owning_workspace_id`, đọc từ `platform.effective_grants`
   (tenant-rbac/02, ADR-0104 (Proposed) quyết 5); tenant khác hay không đọc được → 404, đọc được mà
   không ghi được → 403 `permission_denied` (TC24).
    - `create`: thành phần, nháp đầu và audit `studio.artifact.created` trong một giao dịch; Tên API sai
      mẫu → 422 `validation_failed`; vi phạm unique `(tenant_id, kind, api_name)` ánh xạ theo tên ràng
      buộc → 409 `conflict`, `details.reason_code` `api_name_taken`.
    - `save_draft`: `to_nfc` ở biên, `If-Match` so với `row_version`; khớp → thay tài liệu, tăng
      `row_version`, trả ETag mới; lệch → 412 `precondition_failed`, `details.reason_code`
      `stale_version`; thiếu → 428 (ADR-0108 (Proposed) quyết 3). Audit `studio.artifact.draft_saved`
      chỉ mang `row_version`.
    - `update`: `api_name`, `labels` với `If-Match`; `api_name` khi đã có phiên bản từng `live` → 409
      `api_name_immutable` trước khi trigger phải chặn; audit `studio.artifact.updated` với tên trường.
    - `seal(uow, artifact_id, expected_row_version)`: trong giao dịch của bên gọi, khóa dòng thành phần
      (`SELECT ... FOR UPDATE`), kiểm `row_version` của nháp, `validate` (lỗi → 422 `validation_failed`
      liệt kê mọi lỗi trong `errors[]`), `version_no = last_version_no + 1`, `content_hash` qua
      `dw_kernel.canonical`, bao đóng qua `extract` (mỗi thành phần ghim
      `(kind, key, version, content_hash)`), `definition_hash` là mã băm của bao đóng, ghi `studio.definition_manifests`
      `ON CONFLICT DO NOTHING`, ghi các dòng `studio.dependencies`, rồi chuyển `stage` sang `evaluating`.
      Không audit: route gửi kiểm định của agent-lifecycle/03 audit trong cùng giao dịch.
    - `soft_delete`: đặt `deleted_at`; `ck_artifacts_not_in_use` → 409 `conflict`, `details.reason_code`
      `artifact_in_use`, `details` gồm số đếm theo giai đoạn; audit `studio.artifact.deleted`.
    - `dependents`: nhóm theo giai đoạn (`live`, ứng viên); tên chỉ cho bên người gọi đọc được theo cùng
      kiểm quyền, còn lại chỉ đếm (TC7). `draft_dependencies`: chạy `extract` trên nháp, không ghi dòng
      nào.
7. Route trong nhóm `/api/v1/studio` của studio-skeleton/02, lỗi theo vỏ problem+json
   (ADR-0108 (Proposed)): `POST /api/v1/studio/artifacts`, `GET /api/v1/studio/artifacts` (keyset trên index danh
   sách, lọc `kind`, `label`), `GET /api/v1/studio/artifacts/{id}`, `PATCH /api/v1/studio/artifacts/{id}`,
   `PUT /api/v1/studio/artifacts/{id}/draft`, `GET /api/v1/studio/artifacts/{id}/versions`,
   `GET /api/v1/studio/artifacts/{id}/versions/{version_no}`, `DELETE /api/v1/studio/artifacts/{id}`,
   `GET /api/v1/studio/artifacts/{id}/dependents`, `GET /api/v1/studio/artifacts/{id}/draft/dependencies`.
   Mọi id là UUID. `make generate-contracts`.
8. Loại `fixture` chỉ trong test: tài liệu có trường `uses` trỏ tới thành phần khác, `extract` trả một
   phụ thuộc `artifact` cho mỗi phần tử; test fixture khẳng định đúng tập dòng ghi ra.

## Tiêu chí chấp nhận

- [ ] R2.1: `POST` tạo thành phần có id UUIDv7, một nháp và một audit `studio.artifact.created` trong một
      giao dịch; lỗi giữa chừng không để lại dòng nào.
- [ ] R2.2: Tên API 63 ký tự được nhận; 64 ký tự, 1 ký tự, `Lead` hay `1lead` → 422, không dòng nào.
- [ ] R2.3: Tên API trùng thành phần chưa xóa cùng loại → 409 `api_name_taken`; sau khi thành phần cũ bị
      xóa mềm, cùng tên tạo được; tenant khác dùng cùng tên được.
- [ ] R2.4: `PUT` nháp với `If-Match` đúng → tài liệu mới, `row_version` tăng 1, ETag mới.
- [ ] R2.5 (TC3): `PUT` nháp với `If-Match` cũ → 412 `stale_version`, nháp không đổi; INSERT nháp thứ hai
      cùng thành phần → lỗi partial unique; bỏ so `row_version` → test đỏ.
- [ ] R2.6: tài liệu `fixture` có ba lỗi → 422 với đủ ba mục `errors[]`, mỗi mục một con trỏ; không số
      phiên bản nào được cấp.
- [ ] R2.7 (TC2): niêm phong nháp hợp lệ cấp `last_version_no + 1`, ghi hai mã băm khớp
      `^sha256:[0-9a-f]{64}$` và để phiên bản ở `evaluating`; hai lần niêm phong đồng thời một nháp → một
      thành công, một `stale_version`; bỏ khóa dòng thành phần → test đồng thời đỏ.
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
- [ ] R3.1 (TC6): lỗi chèn giữa giao dịch niêm phong → không số phiên bản, không dòng
      `studio.dependencies`, không dòng `studio.definition_manifests`; làm hỏng `extract` của `fixture`
      → test fixture đỏ.
- [ ] R3.2: xóa mềm thành phần không ai dùng → `deleted_at` có giá trị, audit `studio.artifact.deleted`,
      thành phần biến khỏi danh sách.
- [ ] R3.3 (TC5): xóa mềm thành phần A mà phiên bản `live` của thành phần B ở workspace khác dùng → 409
      `artifact_in_use` kèm số đếm; DELETE cứng → lỗi FK; đưa phiên bản của B sang `retired` rồi xóa mềm
      → được; gỡ trigger → test xóa mềm đỏ.
- [ ] R3.4 (TC7): người chỉ đọc được ở ws1 mở Nơi đang dùng thấy tên bên phụ thuộc ở ws1, bên ở ws2 chỉ
      là số đếm; tenant B → 404.
- [ ] R3.5: `GET .../draft/dependencies` trả phụ thuộc của nháp và số dòng `studio.dependencies` không
      đổi.
- [ ] R3.6 (TC21): `test_offboarding.py` purge tenant có hai thành phần phụ thuộc nhau, tenant khác giữ
      nguyên mọi dòng; gỡ mục `studio.dependencies` khỏi `_ORDERED_FIRST` → test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:46`; spec: Dữ liệu.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:108-114`; spec: R3.6,
  TC21.
- `db/migrations/sql/0001_platform_grants.sql:27`; spec: R2, R3; ADR-0109 (Proposed) quyết 1-2, 4-5;
  ADR-0120 (Proposed) quyết 1.

## Comments

- 2026-10-23 (agent): gộp từ B6 tenant-config 02 và 03. Không có con trỏ `active_version_id`
  (ADR-0109 (Proposed) quyết 2). Ticket dùng ETag, `If-Match`, 412 và 428 của app-standards/03 và
  `platform.effective_grants` của tenant-rbac/02, hai ticket chưa có ở Blocked by của gói nguồn.
