# 02 — Định nghĩa object và trường, bảng bản ghi và chiếu JSON Schema từ định nghĩa

Status: needs-triage
Blocked by: 01, .claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md, .claude/plans/studio/tenant-config/issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md, .claude/plans/studio/org-and-principals/issues/01-khoa-don-vi-va-siet-realm.md, .claude/plans/studio/compliance-pdpl/issues/01-tu-vung-du-lieu-ca-nhan.md, .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md, .claude/plans/studio/tenant-rbac/issues/01-mot-chu-cho-quyen.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md
Area: studio
Yêu cầu: R1.1, R1.3, R1.4, R1.5, R1.6, R1.8, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R3.7, R4.1, R4.2, R4.4, R4.6, R9.2, R9.4, R9.5, CO1, CO2, CO3, CO4, CO5, CO6, CO21, CO23, CO24, CO25

## Mục tiêu

Lát nền của spec: định nghĩa đối tượng và trường của công ty thành dữ liệu (R1, R2), bảng bản ghi có người phụ
trách và workspace sở hữu với partition và slot theo số đo của ticket 01 (R4.1, R4.2, R9.2 tới R9.4), khóa ngoại ghép
không trỏ sang công ty khác, kể cả `to_field_id` của `studio.dependencies` (R4.6), bộ chiếu lược
đồ dựng từ định nghĩa với `ai_description` tách khỏi lược đồ (R3.7). Sau ticket này tenant-rbac/04 sinh khóa
`obj.<api_name>.<action>`, field-security/01 thêm `access_mode`, record-access/03 thêm policy tầm, ticket 03 dựng
describe và bộ chiếu theo quyền của người gọi, và ticket 06 nối loại `object` vào đường phát hành của agent-lifecycle.

## Việc cần làm

1. Một revision Alembic (id ngẫu nhiên do `alembic revision -m "..."` sinh) tạo bốn bảng và cột `to_field_id` của
   `studio.dependencies`, chép nguyên văn ràng buộc từ mục Dữ liệu của spec:
    - `studio.object_defs`: PK `(tenant_id, id)`; FK `(tenant_id, id)` tới `studio.artifacts (tenant_id, id)`
      (`uq_artifacts_tenant_id_id` của tenant-config/02) ON DELETE RESTRICT;
      `api_name` CHECK `^[a-z][a-z0-9_]{1,39}$`, UNIQUE `(tenant_id, api_name)`; `labels` jsonb có khóa `vi` khác
      rỗng; `default_access` NOT NULL DEFAULT `'private'` CHECK `private`, `public_read`, `public_read_write`;
      `ai_description` text NULL CHECK `char_length(ai_description) <= 500`; `schema_version` integer ≥ 1;
      `next_field_no` integer ≥ 1.
    - `studio.field_defs`: PK `(tenant_id, id)`, `id` là mã trường; FK `(tenant_id, object_id)` tới
      `studio.object_defs (tenant_id, id)` ON DELETE CASCADE;
      `api_name` như trên, UNIQUE `(tenant_id, object_id, api_name)`; `ai_description` text NULL CHECK
      `char_length(ai_description) <= 500`; `type` CHECK `text`, `number`, `currency`,
      `date`, `datetime`, `boolean`, `picklist`, `email`, `phone`, `url`, `owner`, `workspace`, `user` (bằng enum
      trong mã); `pd_category` NOT NULL CHECK `none`, `basic`, `sensitive`, cùng `sensitive_type` và
      `subject_identifier` theo `dw_kernel.personal_data`; `required`, `is_unique`, `indexed` boolean NOT NULL;
      `max_length` 1..255; `number_mode` `exact`, `float`; `scale` 0..6; `currency_code` `^[A-Z]{3}$`;
      `storage_kind` `system`, `slot`, `data`; `slot` `^(t|u|i|f|d|z|b)[0-9]{2}$` đúng họ của kiểu (`t`, `u`: chữ,
      email, điện thoại, url, `t` thêm danh sách chọn; `i`: số `exact`, tiền; `f`: số `float`; `d`: ngày; `z`:
      ngày giờ; `b`: đúng sai); `field_no` không dùng lại; UNIQUE
      `(tenant_id, object_id, slot) WHERE slot IS NOT NULL` và `(tenant_id, object_id, field_no)`.
    - `studio.picklist_options`: PK `(tenant_id, field_id, key)`; FK `(tenant_id, field_id)` tới
      `studio.field_defs (tenant_id, id)` ON DELETE CASCADE;
      `key` `^[a-z0-9_]{1,40}$`; `labels` có `vi`; `position`; `active` boolean NOT NULL.
    - `studio.records`: PK `(tenant_id, id)`; `object_id` FK `(tenant_id, object_id)` tới
      `studio.object_defs (tenant_id, id)` ON DELETE RESTRICT; `workspace_id` FK `(tenant_id, workspace_id)` tới
      `platform.workspaces (tenant_id, id)` ON DELETE RESTRICT; `owner_kind` NOT
      NULL CHECK `user`, `team`; `owner_id` NOT NULL; `name` `COLLATE "vi-VN-x-icu"` NOT NULL, 1..255 ký tự;
      `version` ≥ 1; `create_key` ≤ 255 byte, UNIQUE
      `(tenant_id, object_id, create_key) WHERE create_key IS NOT NULL`; `data` jsonb object ≤ 32.768 byte; slot `t`
      (`COLLATE "vi-VN-x-icu"`) và `u` là text
      `octet_length ≤ 1024`, `i` bigint, `f` float8, `d` date, `z` timestamptz, `b` boolean; UNIQUE
      `(tenant_id, object_id, uNN) WHERE uNN IS NOT NULL AND deleted_at IS NULL`; `deleted_at`, `deleted_by`; chỉ
      mục `(tenant_id, object_id, created_at DESC, id DESC)`, `(tenant_id, object_id, updated_at DESC, id DESC)`,
      `(tenant_id, object_id, name, id)`, `(tenant_id, workspace_id)` cho FK tới workspace sở hữu, và chỉ mục từng
      phần của mỗi slot. Tập slot là tập ticket 01 chốt;
      `PARTITION BY HASH (tenant_id)` modulus 8 với `studio.records_p0` tới `studio.records_p7`, hay modulus 4 với
      `studio.records_p0` tới `studio.records_p3` khi số đo của ticket 01 chọn đường lui (DO-15 (a)).
    - `studio.dependencies` (bảng của tenant-config/02): `ALTER TABLE` thêm `to_field_id uuid` NULL, FK ghép
      `(tenant_id, to_field_id)` tới `studio.field_defs (tenant_id, id)` ON DELETE RESTRICT, index
      `(tenant_id, to_field_id)` (ADR-0109 (Accepted) quyết 5); quyền của `dw_app` trên bảng giữ như
      tenant-config/02 cấp.
    - Mỗi bảng và mỗi partition: RLS ENABLE và FORCE; `tenant_isolation_object_defs`, `tenant_isolation_field_defs`,
      `tenant_isolation_picklist_options` FOR ALL dạng InitPlan; `tenant_isolation_records` AS RESTRICTIVE FOR ALL
      dạng InitPlan trên bảng cha và mỗi partition. Policy PERMISSIVE theo tầm là của record-access/03.
    - Trigger BEFORE UPDATE gọi `platform.touch_updated_at()` trên bốn bảng.
    - Quyền: `dw_app` có SELECT, INSERT, DELETE trên bốn bảng; UPDATE trên định nghĩa trừ cột khóa; UPDATE trên
      `studio.records` chỉ ở `name`, `data`, slot, `version`, `updated_*`, `deleted_*`; `REVOKE ALL` của `dw_app` trên
      từng partition, vì quyền mặc định của schema `studio` cấp SELECT cho mọi bảng mới (DO-02.2); không gì cho
      `dw_provisioner`, `dw_agent_ro`, `PUBLIC`. Downgrade gỡ cột `to_field_id` rồi xóa bốn bảng, giữ schema `studio`.
    - `studio.object_defs`, `studio.field_defs`, `studio.picklist_options` không có `workspace_id`: mỗi bảng một dòng
      trong danh sách bảng toàn tenant của `packages/python/dw_platform/tests/integration/test_rls_coverage.py` với lý
      do "định nghĩa đối tượng của cả công ty" (DO-01).
2. Cùng revision đăng ký khóa `studio.objects.manage` trong `platform.permissions` của tenant-rbac/01
   (ADR-0104 (Accepted)): câu INSERT nêu mọi cột NOT NULL của danh mục lúc đó, gồm `label_vi`, `area`,
   `scope_kind` `tenant` (chỉ mức `tenant`), `risk` `standard` theo bảng phân loại của tenant-rbac/01, `status`
   `active`, `owner_package` và `tenant_grantable` `true` của tenant-rbac/02 (Quyết định 24/10/2026 của spec); vai
   nào giữ khóa là việc của tenant-rbac.
3. Thêm `("studio", "records")`, `("studio", "picklist_options")`, `("studio", "field_defs")`,
   `("studio", "object_defs")` theo thứ tự đó vào `_ORDERED_FIRST` của
   `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py`, giữa `studio.dependencies` và
   `studio.artifacts` mà tenant-config/02 thêm: sau `studio.dependencies` vì `to_field_id` giữ `studio.field_defs` bằng
   FK RESTRICT, trước `studio.artifacts` vì FK của `studio.object_defs` tới thành phần là RESTRICT
   (studio-skeleton:R4.2); trên phần đọc catalog và `export_rows` mà foundations-hardening/07 đã viết lại.
4. Trong `dw_studio.records` (gói của studio-skeleton/02):
    - `domain/field_types.py`: Literal `FieldType` với 13 giá trị của CHECK và bảng kiểu sang họ slot; thêm tệp vào
      `WATCHED_LITERALS` của `scripts/verify_invariants.py`.
    - Mô hình tài liệu `dw.object/v1` (Pydantic v2, `extra="forbid"`): `api_name`, `labels`, `ai_description`,
      `default_access`, `name_field` (`labels`, `pd_category`), `fields[]` (`api_name`, `labels`, `ai_description`,
      `type`, `number_mode`, `scale`, `currency_code`, `max_length`, `required`, `is_unique`, `indexed`, `pd_category`,
      `sensitive_type`, `subject_identifier`, `access_mode`, `options[]`); `ai_description` không bắt buộc, tối đa 500
      ký tự tính trên chuỗi NFC; `access_mode` mặc định `secured` khi `pd_category` khác `none`, `open` khi `none`;
      field-security/01 thêm cột và để dịch vụ metadata ghi nó.
    - Trình kiểm trả mọi lỗi một lần (`{path, code, message}`): kiểu (R2.1), `pd_category` qua
      `dw_kernel.personal_data` (R2.2), `api_name` (R2.3), so với phiên bản Đang dùng (R2.4), `access_mode` của trường
      `sensitive` hay trường mới có dữ liệu cá nhân (R2.5), `ai_description` của đối tượng và mỗi trường (R2.6), ngân
      sách slot (R1.6), nhãn `vi` khác rỗng.
    - Bộ so sánh chỉ siết của loại `object` (R1.8), hàm thuần: báo chỉ siết khi và chỉ khi đối tượng có phiên bản Đang
      dùng và mọi khác biệt là một trường từ `open` sang `secured` hay `default_access` hẹp hơn theo thứ tự
      `public_read_write`, `public_read`, `private`; mọi khác biệt khác, kể cả `ai_description` hay nhãn, là không chỉ
      siết. Ticket 06 nối nó vào lệnh Gửi kiểm định của agent-lifecycle, nơi `LifecycleService` ghi `tighten_only` và
      `compared_live_hash` theo kết quả của nó (R1.2, R1.7; `agent-lifecycle:R2.8`).
    - Bộ trích phụ thuộc thuần, trả danh sách rỗng ở W1 (chưa có trường tham chiếu), có test fixture.
    - Móc phát hành `MetadataService.apply`, khai ở mục `ArtifactKindRegistry` của loại (trường móc phát hành mà
      tenant-config/02 thêm; ADR-0109 (Accepted) quyết 1), và agent-lifecycle gọi nó trong giao dịch đưa phiên bản lên
      Đang dùng, ở handler `studio.publish.object.decided` và ở nhánh chỉ siết (`agent-lifecycle:R5.5`,
      `agent-lifecycle:R2.9`; ticket 06 kiểm hai đường đó đầu-cuối): tạo dòng `studio.object_defs` ở lần đầu; với
      mỗi trường mới lấy `pg_advisory_xact_lock` theo công ty rồi chọn slot trống
      nhỏ nhất của họ (trường lọc được) hoặc `next_field_no` (trường trong `data`); thêm lựa chọn; sửa nhãn và
      `ai_description`; `schema_version` cộng 1; audit `studio.object.created`, `studio.object.updated`,
      `studio.field.created`, `studio.field.updated`, `studio.picklist.updated` chỉ mang khóa và phiên bản. Móc chỉ áp
      định nghĩa: nó không đổi giai đoạn phiên bản và không ghi `studio.version.published`, sự kiện mà agent-lifecycle
      ghi đúng một lần mỗi lần phát hành (`agent-lifecycle:R2.9`, `agent-lifecycle:R5.5`).
    - Đăng ký loại `object` vào `ArtifactKindRegistry` ở `build_studio`: `studio.objects.manage` (mức `tenant`) là khóa
      đọc, khóa ghi và khóa gửi của loại cho đọc, tạo, lưu nháp và Gửi kiểm định (`tenant-config:R2.11`,
      `tenant-config:R2.12`, `tenant-config:R2.15`), không có Cổng chất lượng, bộ so sánh chỉ siết và móc phát hành ở
      trên; migration thêm dòng `object` với
      `has_quality_gate = false` vào `studio.artifact_kinds` (`ck_artifacts_kind` thành FK tới bảng này, OPS-b cạnh 4,
      `tenant-config:R2.14`), và test ở composition root so registry với các dòng.
5. `ObjectSchemaProjector` trong `dw_studio.records`: dựng JSON Schema 2020-12 cho tạo, sửa, truy vấn từ định nghĩa,
   khóa theo `(object_id, schema_version)`, và trả `ai_description` của đối tượng và mỗi trường trong một bảng tách khỏi
   lược đồ, không đặt vào `title`, `description` hay nhãn (R3.7, YC48). Route `GET /api/v1/studio/objects`, describe và
   phần lọc theo khóa đọc đối tượng và quyết định trường của người gọi (R3.1 tới R3.6, phần trường Đã ẩn của R3.7)
   thuộc ticket 03, vì chúng cần tenant-rbac/04 và field-security/01, mà cả hai chờ ticket này (Quyết định 24/10/2026
   của spec).

## Tiêu chí chấp nhận

- [ ] R1.1 (CO2): móc phát hành, gọi qua mục `ArtifactKindRegistry` của loại `object` cho một `dw.object/v1` 20
      trường trong giao dịch đưa phiên bản lên Đang dùng mà fixture mở thay agent-lifecycle (phê duyệt `approved` dựng
      bằng fixture; đường thật kiểm ở ticket 06), áp định nghĩa trong cùng giao dịch, số quan hệ của schema `studio`
      trong `pg_class` không đổi; `dw_app` chạy `CREATE TABLE studio.x` hay
      `CREATE INDEX ON studio.records` → bị từ chối; cấp `CREATE` trên `studio` cho `dw_app` → test đỏ.
- [ ] R1.8 (CO23): test thuộc tính trên cặp tài liệu sinh ngẫu nhiên: bộ so sánh báo chỉ siết đúng khi mọi khác biệt
      là đóng trường hay hạ `default_access`; phiên bản đầu (chưa có Đang dùng) → không chỉ siết; nâng `default_access`,
      mở một trường, đổi nhãn hay `ai_description` → không chỉ siết; vừa đóng `phone` vừa đổi nhãn → không chỉ siết, và
      coi thay đổi trộn đó là chỉ siết → test đỏ.
- [ ] R1.3 (CO3): người thiếu `studio.objects.manage` tạo hay lưu nháp thành phần loại `object` → 403
      `permission_denied`, không dòng mới trong `studio.artifact_versions`; gỡ kiểm khóa ở mục đăng ký của loại → test
      đỏ (lệnh Gửi kiểm định kiểm ở ticket 06).
- [ ] R1.4: tài liệu không nêu `default_access` → dòng có `private`; giá trị ngoài CHECK bị từ chối theo tên ràng
      buộc.
- [ ] R1.5 (CO4): hai phát hành song song cùng thêm trường lọc được họ `t` vào một đối tượng → hai slot khác nhau;
      gỡ UNIQUE `(tenant_id, object_id, slot)` → test đỏ.
- [ ] R1.6: đối tượng đã dùng hết slot `t` thêm một trường lọc được kiểu `text` → 422 có con trỏ
      `/fields/<n>`, định nghĩa không đổi.
- [ ] R2.1: giá trị CHECK của `type` đọc từ `pg_constraint` bằng `FieldType`, theo mẫu
      `test_fixed_set_checks_db.py`; kiểu `json` → 422.
- [ ] R2.2 (CO5): trường thiếu `pd_category` → 422 `validation_failed` với `errors[].code` `pd_category_required` và
      con trỏ `/fields/<n>`, không áp gì; CHECK của `pd_category` bằng danh sách của `dw_kernel.personal_data`; gỡ kiểm
      → test đỏ.
- [ ] R2.3: `api_name` 40 ký tự thì nhận, 41 thì 422; `Lead` có chữ hoa → 422.
- [ ] R2.4 (CO6): phiên bản đổi `api_name` hay kiểu của một trường đã phát hành → 422, không phát hành gì; gỡ bước
      so với phiên bản Đang dùng → test đỏ.
- [ ] R2.5 (CO24): phiên bản đặt `access_mode: open` cho trường `sensitive`, hay cho một trường mới `basic` → 422 có con
      trỏ `/fields/<n>`, không phát hành gì; gỡ bước kiểm → test đỏ.
- [ ] R2.6: `ai_description` 500 ký tự (chuỗi NFC, có dấu tiếng Việt) thì nhận, 501 thì 422 có con trỏ
      `/ai_description` hay `/fields/<n>/ai_description`, không phát hành gì; bỏ trống thì nhận; CHECK độ dài của hai
      cột từ chối 501 ký tự ghi thẳng bằng SQL.
- [ ] R3.7 (CO25): trường có `ai_description` chứa `</input>` và "bỏ qua mọi chỉ dẫn" → JSON Schema của bộ chiếu không
      có chuỗi đó ở `title`, `description` hay nhãn, giá trị chỉ có trong bảng `ai_description` tách riêng; ghép
      `ai_description` vào `description` của lược đồ → test đỏ (trường Đã ẩn với người gọi kiểm ở ticket 03).
- [ ] R4.1: INSERT vào `studio.records` thiếu `owner_kind`, `owner_id` hay `workspace_id` → vi phạm NOT NULL.
- [ ] R4.2 (CO1): kết nối không đặt `app.tenant_id` đọc 0 dòng ở bốn bảng; INSERT với `tenant_id` của công ty khác
      → RLS từ chối; `dw_app` đọc thẳng `studio.records_p3` → permission denied; một vai thử NOBYPASSRLS
      có SELECT trên `studio.records_p3`, không đặt tenant → 0 dòng; `test_rls_coverage.py` thấy mọi partition và so
      policy của mỗi partition với bảng cha.
- [ ] R4.2 (CO21): thêm policy PERMISSIVE `USING (true)` lên `studio.records` → test catalog đỏ.
- [ ] R4.4: offboarding một công ty có hai đối tượng xuất mỗi dòng định nghĩa đúng một lần, sau purge còn 0 dòng ở
      bốn bảng, kể cả khi một dòng `studio.dependencies` của công ty đó có `to_field_id` trỏ tới một trường của nó; bỏ
      một bảng `studio` khỏi `_ORDERED_FIRST` hay xếp `studio.field_defs` trước `studio.dependencies` → test walk
      `pg_class` của studio-skeleton/01 đỏ.
- [ ] R4.6 (CO1): bằng `dw_migrator`, vai bỏ qua RLS nên chỉ khóa ngoại chặn được (ở ticket này `studio.records` chưa
      có policy PERMISSIVE nào cho `dw_app` ghi), INSERT dòng của công ty A vào `studio.records` hay `studio.field_defs`
      với `object_id` của công ty B, vào `studio.picklist_options` với `field_id` của B, vào `studio.object_defs` với
      `id` của một thành phần của B, vào `studio.records` với `workspace_id` của B, và vào `studio.dependencies` với
      `to_field_id` của một trường của B → lỗi FK ghép (23503), không dòng nào; migration thử đổi một FK ghép thành FK
      một cột → test đỏ.
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
- ADR-0107 (Accepted) quyết định 1, 2, 5; ADR-0109 (Accepted) quyết định 1, 5 (`to_field_id`); ADR-0106 (Accepted)
  quyết định 1.
- `docs/adr/0120-publish-gate-and-run-control-switches.md:39-84`; spec: R1.8 (quyết 1, nhánh chỉ siết).

## Comments

- 2026-10-23 (agent): Đề xuất đổi R3.1 tới R3.6 sang ticket 03: describe theo người gọi và bộ chiếu lược đồ cần
  `resolve_field_access` (field-security/01) và khóa `obj.<api_name>.read` (tenant-rbac/04), mà cả hai ticket đó bị
  chặn bởi ticket này; ticket 03 đứng sau cả hai.
- 2026-10-23 (agent): Đề xuất thêm tenant-rbac/01 vào Blocked by: bước 2 đăng ký khóa vào danh mục quyền mà
  tenant-rbac/01 tạo.
- 2026-10-23 (agent): DO-15 (a) và Q1 của spec (phạm vi D11 cho định nghĩa đối tượng) đã có lời đáp (Đạt và người đặt
  yêu cầu, 23/10/2026); Status về needs-triage. Thêm R1.7, R2.5, R9.5, CO23, CO24; bỏ R9.3. Phát hành qua
  `studio.publish.object` cần máy giai đoạn và phê duyệt phát hành của agent-lifecycle, mà Blocked by chưa có cạnh tới.
- 2026-10-24 (agent): Đạt nhận các khuyến nghị ngày 24/10/2026: Blocked by thêm foundations-hardening/07 (cùng sửa
  `offboarding.py`); thêm R1.8 (bộ so sánh chỉ siết), R2.6, R3.7 và CO25 (`ai_description`, YC101); mục đăng ký của
  loại khai khóa đọc, khóa ghi, khóa gửi và `has_quality_gate = false`. Đường phát hành qua agent-lifecycle (R1.2, R1.7,
  phần gửi của R1.3) chuyển sang ticket 06, nơi có cạnh tới agent-lifecycle/03, /04: đặt cạnh tới agent-lifecycle/04 ở
  đây khép vòng qua workflow-engine/03 và record-access/04. Hai đề xuất ngày 23/10/2026 ở trên chưa nằm trong quyết
  định của vòng này nên giữ nguyên.
- 2026-10-24 (agent): vòng sửa 4 áp hai đề xuất ngày 23/10/2026 (Quyết định 24/10/2026 của spec): R3.1 tới R3.6, phần
  trường Đã ẩn của R3.7, CO7, CO8 và route describe, `GET /api/v1/studio/objects` chuyển sang ticket 03; bộ chiếu dựng
  từ định nghĩa và phần tách `ai_description` của R3.7 ở lại đây (`I:custom-objects/02~tenant-rbac/01`); Blocked by
  thêm tenant-rbac/01, /02 và bước 2 nêu mọi cột NOT NULL của danh mục trong INSERT (`C:custom-objects/02~tenant-rbac/02`).
  Cùng vòng: R2.2 thành 422 `validation_failed` với `errors[].code` `pd_category_required`
  (`B:app-standards:R1.3~custom-objects:R6.7`); móc phát hành không ghi `studio.version.published`
  (`B:agent-lifecycle:R2.9~custom-objects:R1.7`); "gửi phát hành" thành "Gửi kiểm định" (`G:CONTEXT.md#submit~custom-objects:R1.2`).
- 2026-10-24 (agent): vòng sửa 4, lượt hai: móc phát hành khai ở mục `ArtifactKindRegistry` của loại (trường mà
  tenant-config/02 thêm) và agent-lifecycle gọi nó trong giao dịch phát hành, nên bước 4 thôi nói ticket 06 nối móc vào
  handler; R2.2 của spec dẫn compliance-pdpl:R1.1 (chủ mã) và app-standards:R1.3 (hình lỗi), tiêu chí R2.2 ở đây không
  đổi (Quyết định 24/10/2026 của spec).
- 2026-10-24 (agent): vòng sửa 4, lượt ba: tiêu chí R1.1 thôi nói "dịch vụ phát hành": móc gọi qua mục
  `ArtifactKindRegistry` của loại trong giao dịch do fixture mở thay agent-lifecycle (ADR-0109 (Accepted) quyết 1); bước
  1 nêu mọi khóa ngoại giữa hai bảng của tenant là FK ghép tới `(tenant_id, id)` của bảng đích, kể cả `object_id` của
  `studio.records` và `field_id` của `studio.picklist_options`, và tiêu chí R4.2 (CO1) thêm ca `object_id` của công ty
  khác (hai dòng Quyết định 24/10/2026 của spec).
- 2026-10-24 (agent): vòng sửa 4, lượt bốn: bước 1 thêm cột `to_field_id` của `studio.dependencies` với FK ghép ON
  DELETE RESTRICT tới `studio.field_defs` và index `(tenant_id, to_field_id)`, như tenant-config giao
  (ADR-0109 (Accepted) quyết 5), cùng index `(tenant_id, workspace_id)` của `studio.records` cho FK tới workspace; bước
  3 đặt bốn bảng giữa `studio.dependencies` và `studio.artifacts`; ca FK ghép của công ty khác rời tiêu chí R4.2 sang
  tiêu chí mới R4.6 (CO1), thêm ca `field_id` của lựa chọn, `id` của định nghĩa đối tượng, `workspace_id` của bản ghi và
  `to_field_id`; tiêu chí R4.4 thêm dòng phụ thuộc trỏ tới trường (ba dòng Quyết định 24/10/2026 của spec).
