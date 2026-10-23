# 02 — Định nghĩa object và trường, bảng bản ghi, describe và chiếu JSON Schema

Status: needs-triage
Blocked by: 01, .claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md, .claude/plans/studio/tenant-config/issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md, .claude/plans/studio/org-and-principals/issues/01-khoa-don-vi-va-siet-realm.md, .claude/plans/studio/compliance-pdpl/issues/01-tu-vung-du-lieu-ca-nhan.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R1.6, R1.7, R2.1, R2.2, R2.3, R2.4, R2.5, R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R4.1, R4.2, R4.4, R9.2, R9.4, R9.5, CO1, CO2, CO3, CO4, CO5, CO6, CO7, CO8, CO21, CO23, CO24

## Mục tiêu

Lát nền của spec: định nghĩa đối tượng và trường của công ty thành dữ liệu (R1, R2), bảng bản ghi có người phụ
trách và workspace sở hữu với partition và slot theo số đo của ticket 01 (R4.1, R4.2, R9.2 tới R9.4), describe
theo người gọi và bộ chiếu lược đồ (R3). Sau ticket này tenant-rbac/04 sinh khóa `obj.<api_name>.<action>`,
field-security/01 thêm `access_mode`, record-access/03 thêm policy tầm, và marketing-pilot/02 tạo Lead, Campaign
qua API công khai.

## Việc cần làm

1. Một revision Alembic (id ngẫu nhiên do `alembic revision -m "..."` sinh) tạo bốn bảng, chép nguyên văn ràng buộc
   từ mục Dữ liệu của spec:
    - `studio.object_defs`: PK `(tenant_id, id)`; FK `(tenant_id, id)` tới `studio.artifacts` ON DELETE RESTRICT;
      `api_name` CHECK `^[a-z][a-z0-9_]{1,39}$`, UNIQUE `(tenant_id, api_name)`; `labels` jsonb có khóa `vi` khác
      rỗng; `default_access` NOT NULL DEFAULT `'private'` CHECK `private`, `public_read`, `public_read_write`;
      `schema_version` integer ≥ 1; `next_field_no` integer ≥ 1.
    - `studio.field_defs`: PK `(tenant_id, id)`, `id` là mã trường; FK `(tenant_id, object_id)` ON DELETE CASCADE;
      `api_name` như trên, UNIQUE `(tenant_id, object_id, api_name)`; `type` CHECK `text`, `number`, `currency`,
      `date`, `datetime`, `boolean`, `picklist`, `email`, `phone`, `url`, `owner`, `workspace`, `user` (bằng enum
      trong mã); `pd_category` NOT NULL CHECK `none`, `basic`, `sensitive`, cùng `sensitive_type` và
      `subject_identifier` theo `dw_kernel.personal_data`; `required`, `is_unique`, `indexed` boolean NOT NULL;
      `max_length` 1..255; `number_mode` `exact`, `float`; `scale` 0..6; `currency_code` `^[A-Z]{3}$`;
      `storage_kind` `system`, `slot`, `data`; `slot` `^(t|u|i|f|d|z|b)[0-9]{2}$` đúng họ của kiểu (`t`, `u`: chữ,
      email, điện thoại, url, `t` thêm danh sách chọn; `i`: số `exact`, tiền; `f`: số `float`; `d`: ngày; `z`:
      ngày giờ; `b`: đúng sai); `field_no` không dùng lại; UNIQUE
      `(tenant_id, object_id, slot) WHERE slot IS NOT NULL` và `(tenant_id, object_id, field_no)`.
    - `studio.picklist_options`: PK `(tenant_id, field_id, key)`; FK tới `studio.field_defs` ON DELETE CASCADE;
      `key` `^[a-z0-9_]{1,40}$`; `labels` có `vi`; `position`; `active` boolean NOT NULL.
    - `studio.records`: PK `(tenant_id, id)`; `object_id` FK tới `studio.object_defs` ON DELETE RESTRICT;
      `workspace_id` FK `(tenant_id, workspace_id)` tới `platform.workspaces` ON DELETE RESTRICT; `owner_kind` NOT
      NULL CHECK `user`, `team`; `owner_id` NOT NULL; `name` `COLLATE "vi-VN-x-icu"` NOT NULL, 1..255 ký tự;
      `version` ≥ 1; `create_key` ≤ 255 byte, UNIQUE
      `(tenant_id, object_id, create_key) WHERE create_key IS NOT NULL`; `data` jsonb object ≤ 32.768 byte; slot `t`
      (`COLLATE "vi-VN-x-icu"`) và `u` là text
      `octet_length ≤ 1024`, `i` bigint, `f` float8, `d` date, `z` timestamptz, `b` boolean; UNIQUE
      `(tenant_id, object_id, uNN) WHERE uNN IS NOT NULL AND deleted_at IS NULL`; `deleted_at`, `deleted_by`; chỉ
      mục `(tenant_id, object_id, created_at DESC, id DESC)`, `(tenant_id, object_id, updated_at DESC, id DESC)`,
      `(tenant_id, object_id, name, id)` và chỉ mục từng phần của mỗi slot. Tập slot là tập ticket 01 chốt;
      `PARTITION BY HASH (tenant_id)` modulus 8 với `studio.records_p0` tới `studio.records_p7`, hay modulus 4 với
      `studio.records_p0` tới `studio.records_p3` khi số đo của ticket 01 chọn đường lui (DO-15 (a)).
    - Mỗi bảng và mỗi partition: RLS ENABLE và FORCE; `tenant_isolation_object_defs`, `tenant_isolation_field_defs`,
      `tenant_isolation_picklist_options` FOR ALL dạng InitPlan; `tenant_isolation_records` AS RESTRICTIVE FOR ALL
      dạng InitPlan trên bảng cha và mỗi partition. Policy PERMISSIVE theo tầm là của record-access/03.
    - Trigger BEFORE UPDATE gọi `platform.touch_updated_at()` trên bốn bảng.
    - Quyền: `dw_app` có SELECT, INSERT, DELETE trên bốn bảng; UPDATE trên định nghĩa trừ cột khóa; UPDATE trên
      `studio.records` chỉ ở `name`, `data`, slot, `version`, `updated_*`, `deleted_*`; `REVOKE ALL` của `dw_app` trên
      từng partition, vì quyền mặc định của schema `studio` cấp SELECT cho mọi bảng mới (DO-02.2); không gì cho
      `dw_provisioner`, `dw_agent_ro`, `PUBLIC`. Downgrade xóa bốn bảng, giữ schema `studio`.
    - `studio.object_defs`, `studio.field_defs`, `studio.picklist_options` không có `workspace_id`: mỗi bảng một dòng
      trong danh sách bảng toàn tenant của `packages/python/dw_platform/tests/integration/test_rls_coverage.py` với lý
      do "định nghĩa đối tượng của cả công ty" (DO-01).
2. Cùng revision đăng ký khóa `studio.objects.manage` (chỉ mức `tenant`) trong danh mục quyền của tenant-rbac/01
   (ADR-0104 (Accepted)); vai nào giữ khóa là việc của tenant-rbac.
3. Thêm `("studio", "records")`, `("studio", "picklist_options")`, `("studio", "field_defs")`,
   `("studio", "object_defs")` theo thứ tự đó vào `_ORDERED_FIRST` của
   `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py`.
4. Trong `dw_studio.records` (gói của studio-skeleton/02):
    - `domain/field_types.py`: Literal `FieldType` với 13 giá trị của CHECK và bảng kiểu sang họ slot; thêm tệp vào
      `WATCHED_LITERALS` của `scripts/verify_invariants.py`.
    - Mô hình tài liệu `dw.object/v1` (Pydantic v2, `extra="forbid"`): `api_name`, `labels`, `default_access`,
      `name_field` (`labels`, `pd_category`), `fields[]` (`api_name`, `labels`, `type`, `number_mode`, `scale`,
      `currency_code`, `max_length`, `required`, `is_unique`, `indexed`, `pd_category`, `sensitive_type`,
      `subject_identifier`, `access_mode`, `options[]`); `access_mode` mặc định `secured` khi `pd_category` khác `none`,
      `open` khi `none`; field-security/01 thêm cột và để dịch vụ metadata ghi nó.
    - Trình kiểm trả mọi lỗi một lần (`{path, code, message}`): kiểu (R2.1), `pd_category` qua
      `dw_kernel.personal_data` (R2.2), `api_name` (R2.3), so với phiên bản Đang dùng (R2.4), `access_mode` của trường
      `sensitive` hay trường mới có dữ liệu cá nhân (R2.5), ngân sách slot (R1.6), nhãn `vi` khác rỗng.
    - Phân loại phát hành so với phiên bản Đang dùng: phiên bản chỉ siết (trường từ `open` sang `secured`;
      `default_access` hẹp hơn theo thứ tự `public_read_write`, `public_read`, `private`; mọi phần khác của tài liệu bằng
      nhau) lên Đang dùng trong giao dịch của người gửi, audit `studio.version.published` với người gửi là actor (R1.7);
      mọi phiên bản khác, kể cả phiên bản đầu, sang Chờ duyệt với phê duyệt `studio.publish.object` không qua Cổng chất
      lượng, theo máy giai đoạn của agent-lifecycle (R1.2; ADR-0120 (Accepted) mục 2).
    - Bộ trích phụ thuộc thuần, trả danh sách rỗng ở W1 (chưa có trường tham chiếu), có test fixture.
    - Móc phát hành `MetadataService.apply`, chạy trong giao dịch phát hành của tenant-config/02: tạo dòng
      `studio.object_defs` ở lần đầu; với mỗi trường mới lấy `pg_advisory_xact_lock` theo công ty rồi chọn slot trống
      nhỏ nhất của họ (trường lọc được) hoặc `next_field_no` (trường trong `data`); thêm lựa chọn; sửa nhãn;
      `schema_version` cộng 1; audit `studio.object.created`, `studio.object.updated`, `studio.field.created`,
      `studio.field.updated`, `studio.picklist.updated` chỉ mang khóa và phiên bản.
    - Đăng ký loại `object` vào `ArtifactKindRegistry` ở `build_studio`, nêu `studio.objects.manage` là khóa cho tạo,
      lưu nháp và phát hành; migration thêm dòng `object` vào `studio.artifact_kinds` (`ck_artifacts_kind` thành FK tới
      bảng này, OPS-b cạnh 4), và test ở composition root so registry với các dòng.
5. Route trong nhóm `/api/v1/studio`, `Cache-Control: no-store`: `GET /api/v1/studio/objects` và
   `GET /api/v1/studio/objects/{api_name}/describe`, đọc quyền đối tượng qua khóa `obj.<api_name>.read`
   (tenant-rbac/04) và quyền trường qua `resolve_field_access` (field-security/01); describe trả trường Đã ẩn chỉ với
   `api_name`, nhãn và `access: hidden`; `ObjectSchemaProjector` dựng JSON Schema 2020-12 cho tạo, sửa, truy vấn,
   khóa theo `(object_id, schema_version)` và quyết định trường của người gọi, không có trường Đã ẩn.

## Tiêu chí chấp nhận

- [ ] R1.1 (CO2): phát hành một `dw.object/v1` 20 trường áp định nghĩa trong cùng giao dịch, số quan hệ của schema
      `studio` trong `pg_class` không đổi; `dw_app` chạy `CREATE TABLE studio.x` hay `CREATE INDEX ON studio.records`
      → bị từ chối; cấp `CREATE` trên `studio` cho `dw_app` → test đỏ.
- [ ] R1.2 (CO23): người giữ `studio.objects.manage` gửi phát hành bản nháp hợp lệ thêm một trường → phiên bản Chờ duyệt
      với phê duyệt `studio.publish.object`, định nghĩa chưa đổi; một người khác giữ `studio.publish.approve` duyệt →
      Đang dùng và định nghĩa đã áp; phiên bản mở một trường `basic` → Chờ duyệt.
- [ ] R1.7 (CO23): phiên bản chỉ đóng `phone` (hay chỉ hạ `default_access` từ `public_read` về `private`) → Đang dùng
      ngay trong giao dịch của người gửi, có audit `studio.version.published` với người gửi là actor, không phê duyệt;
      phiên bản vừa đóng `phone` vừa đổi nhãn → Chờ duyệt; coi thay đổi trộn là chỉ siết → test đỏ.
- [ ] R1.3 (CO3): người thiếu `studio.objects.manage` tạo, lưu nháp, phát hành → 403 `permission_denied`, không
      dòng mới trong `studio.artifact_versions`; gỡ kiểm khóa ở mục đăng ký của loại → test đỏ.
- [ ] R1.4: tài liệu không nêu `default_access` → dòng có `private`; giá trị ngoài CHECK bị từ chối theo tên ràng
      buộc.
- [ ] R1.5 (CO4): hai phát hành song song cùng thêm trường lọc được họ `t` vào một đối tượng → hai slot khác nhau;
      gỡ UNIQUE `(tenant_id, object_id, slot)` → test đỏ.
- [ ] R1.6: đối tượng đã dùng hết slot `t` thêm một trường lọc được kiểu `text` → 422 có con trỏ
      `/fields/<n>`, định nghĩa không đổi.
- [ ] R2.1: giá trị CHECK của `type` đọc từ `pg_constraint` bằng `FieldType`, theo mẫu
      `test_fixed_set_checks_db.py`; kiểu `json` → 422.
- [ ] R2.2 (CO5): trường thiếu `pd_category` → 422 `pd_category_required`, không áp gì; CHECK của `pd_category`
      bằng danh sách của `dw_kernel.personal_data`; gỡ kiểm → test đỏ.
- [ ] R2.3: `api_name` 40 ký tự thì nhận, 41 thì 422; `Lead` có chữ hoa → 422.
- [ ] R2.4 (CO6): phiên bản đổi `api_name` hay kiểu của một trường đã phát hành → 422, không phát hành gì; gỡ bước
      so với phiên bản Đang dùng → test đỏ.
- [ ] R2.5 (CO24): phiên bản đặt `access_mode: open` cho trường `sensitive`, hay cho một trường mới `basic` → 422 có con
      trỏ `/fields/<n>`, không phát hành gì; gỡ bước kiểm → test đỏ.
- [ ] R3.1: describe cho người đọc được trả mỗi trường với nhãn `vi`, kiểu, `access`, các cờ và lựa chọn đang bật;
      lựa chọn đã tắt không có.
- [ ] R3.2 (CO7): người gọi mà `phone` Đã ẩn gọi describe → `phone` chỉ có `api_name`, nhãn và `access: hidden`, không
      kiểu, cờ hay lựa chọn; lược đồ truy vấn của bộ chiếu không có `phone`.
- [ ] R3.3: người của công ty B gọi describe với `api_name` chỉ công ty A có → 404.
- [ ] R3.4 (CO8): người thiếu `obj.<api_name>.read` gọi describe → 403 `permission_denied`.
- [ ] R3.5: `GET /api/v1/studio/objects` trả đúng các đối tượng người gọi giữ khóa đọc, không thừa không thiếu.
- [ ] R3.6: lược đồ tạo của bộ chiếu không có trường người gọi không sửa được; lược đồ truy vấn không có trường Đã
      ẩn; `schema_version` tăng → lược đồ mới.
- [ ] R4.1: INSERT vào `studio.records` thiếu `owner_kind`, `owner_id` hay `workspace_id` → vi phạm NOT NULL.
- [ ] R4.2 (CO1): kết nối không đặt `app.tenant_id` đọc 0 dòng ở bốn bảng; INSERT với `tenant_id` của công ty khác
      → RLS từ chối; `dw_app` đọc thẳng `studio.records_p3` → permission denied; một vai thử NOBYPASSRLS có SELECT
      trên `studio.records_p3`, không đặt tenant → 0 dòng; `test_rls_coverage.py` thấy mọi partition và so policy
      của mỗi partition với bảng cha.
- [ ] R4.2 (CO21): thêm policy PERMISSIVE `USING (true)` lên `studio.records` → test catalog đỏ.
- [ ] R4.4: offboarding một công ty có hai đối tượng xuất mỗi dòng định nghĩa đúng một lần, sau purge còn 0 dòng ở
      bốn bảng; bỏ một bảng `studio` khỏi `_ORDERED_FIRST` → test walk `pg_class` của studio-skeleton/01 đỏ.
- [ ] R9.2: khi ticket 01 chọn modulus 8, test catalog thấy `studio.records` là `PARTITION BY HASH (tenant_id)` với 8
      partition, mỗi partition ENABLE và FORCE RLS, không quyền nào của `dw_app`.
- [ ] R9.5: khi ticket 01 chọn đường lui modulus 4, test catalog thấy 4 partition `studio.records_p0` tới
      `studio.records_p3`, mỗi partition ENABLE và FORCE RLS, không quyền nào của `dw_app`.
- [ ] R9.4: test catalog đọc `pg_index` thấy đúng tập slot của ticket 01, mỗi slot một chỉ mục từng phần đúng vị từ.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `db/migrations/sql/0001_platform_grants.sql:27-46`; `db/migrations/sql/0001_platform_baseline.sql:478-485`;
  spec: R1.1, R4.1.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:108-114`; spec: R4.4.
- `packages/python/dw_platform/tests/integration/test_rls_coverage.py:50-55`; spec: R4.2.
- `packages/python/dw_memory/tests/integration/test_fixed_set_checks_db.py:135`; `scripts/verify_invariants.py:109-112`;
  spec: R2.1.
- `db/migrations/versions/0004_touch_updated_at_yields.py:44`; spec: Dữ liệu.
- ADR-0107 (Accepted) quyết định 1, 2, 5; ADR-0109 (Accepted) quyết định 1; ADR-0106 (Accepted) quyết định 1.
- `docs/adr/0120-publish-gate-and-run-control-switches.md:39-72`; spec: R1.2, R1.7.

## Comments

- 2026-10-23 (agent): Đề xuất đổi R3.1 tới R3.6 sang ticket 03: describe theo người gọi và bộ chiếu lược đồ cần
  `resolve_field_access` (field-security/01) và khóa `obj.<api_name>.read` (tenant-rbac/04), mà cả hai ticket đó bị
  chặn bởi ticket này; ticket 03 đứng sau cả hai.
- 2026-10-23 (agent): Đề xuất thêm tenant-rbac/01 vào Blocked by: bước 2 đăng ký khóa vào danh mục quyền mà
  tenant-rbac/01 tạo.
- 2026-10-23 (agent): DO-15 (a) và Q1 của spec (phạm vi D11 cho định nghĩa đối tượng) đã có lời đáp (Đạt và người đặt
  yêu cầu, 23/10/2026); Status về needs-triage. Thêm R1.7, R2.5, R9.5, CO23, CO24; bỏ R9.3. Phát hành qua
  `studio.publish.object` cần máy giai đoạn và phê duyệt phát hành của agent-lifecycle, mà Blocked by chưa có cạnh tới.
