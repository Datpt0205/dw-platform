# 02 — Định nghĩa object và trường, bảng bản ghi và chiếu JSON Schema từ định nghĩa

Status: resolved (2026-11-04, main)
Blocked by: .claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md, .claude/plans/studio/tenant-config/issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md, .claude/plans/studio/org-and-principals/issues/01-khoa-don-vi-va-siet-realm.md, .claude/plans/studio/compliance-pdpl/issues/01-tu-vung-du-lieu-ca-nhan.md, .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md, .claude/plans/studio/tenant-rbac/issues/01-mot-chu-cho-quyen.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md
Area: studio
Yêu cầu: R1.1, R1.3, R1.4, R1.5, R1.6, R1.8, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R3.7, R4.1, R4.2, R4.4, R4.6, R9.4, R9.5, CO1, CO2, CO3, CO4, CO5, CO6, CO21, CO23, CO24, CO25

## Mục tiêu

Lát nền của spec: định nghĩa đối tượng và trường của công ty thành dữ liệu (R1, R2), bảng bản ghi có người phụ
trách và workspace sở hữu (R4.1, R4.2) trên DDL tạm của mục Dữ liệu (modulus 4, tập slot đề xuất A0 của ticket 01,
R9.4, R9.5) mà ticket 07 đưa về kết luận của lần đo `--scale d12` khi máy tham chiếu có (Chờ Đạt 23), khóa ngoại ghép
không trỏ sang công ty khác, kể cả `to_field_id` của `studio.dependencies` (R4.6), bộ chiếu lược đồ dựng từ định
nghĩa với `ai_description` tách khỏi lược đồ (R3.7). Sau ticket này tenant-rbac/04 sinh khóa `obj.<api_name>.<action>`,
field-security/01 thêm `access_mode`, record-access/03 thêm policy tầm, ticket 03 dựng describe và bộ chiếu theo quyền
của người gọi, và ticket 06 nối loại `object` vào đường phát hành của agent-lifecycle.

## Việc cần làm

1. Một revision Alembic (id ngẫu nhiên do `alembic revision -m "..."` sinh) tạo bốn bảng và cột `to_field_id` của
   `studio.dependencies`, chép nguyên văn ràng buộc từ mục Dữ liệu của spec. Khi Comments của ticket 01 đã có kết quả
   `--scale smoke` (UNIQUE từng phần trên `u01` của bảng partition, `ON CONFLICT` dưới policy theo lệnh, trigger
   `updated_at` trên partition), đọc trước khi viết: một mục ghi "không chạy được" thì dừng và ghi vào Comments ở đây.
   Chưa có thì không chờ: migration và test tích hợp của ticket này chạy chính ba mục đó (tiêu chí R1.5, R4.2, R9.4).
    - `studio.object_defs`: PK `(tenant_id, id)`; FK `(tenant_id, id)` tới `studio.artifacts (tenant_id, id)`
      (`uq_artifacts_tenant_id_id` của tenant-config/02) ON DELETE RESTRICT;
      `api_name` CHECK `^[a-z][a-z0-9_]{1,39}$`, UNIQUE `(tenant_id, api_name)`, chép từ `studio.artifacts.api_name`
      ở lần áp đầu, không từ tài liệu; `labels` jsonb có khóa `vi` khác rỗng; `default_access` NOT NULL DEFAULT
      `'private'` CHECK `private`, `public_read`, `public_read_write`; `ai_description` text NULL CHECK
      `char_length(ai_description) <= 500`; `applied_version_id` NOT NULL, FK ghép `(tenant_id, applied_version_id)` tới
      `studio.artifact_versions (tenant_id, id)` (`uq_artifact_versions_tenant_id_id`) ON DELETE RESTRICT, index
      `(tenant_id, applied_version_id)`; `schema_version` integer ≥ 1, bằng `version_no` của phiên bản đó;
      `next_field_no` integer ≥ 1.
    - `studio.field_defs`: PK `(tenant_id, id)`, `id` là mã trường; FK `(tenant_id, object_id)` tới
      `studio.object_defs (tenant_id, id)` ON DELETE CASCADE;
      `api_name` như trên, UNIQUE `(tenant_id, object_id, api_name)`; `ai_description` text NULL CHECK
      `char_length(ai_description) <= 500`; `type` CHECK `text`, `number`, `currency`, `date`, `datetime`, `boolean`,
      `picklist`, `email`, `phone`, `url`, `owner`, `workspace` (bằng enum trong mã); `pd_category` NOT NULL CHECK
      `none`, `basic`, `sensitive`, cùng `sensitive_type` và `subject_identifier` theo `dw_kernel.personal_data`;
      `required`, `is_unique`, `indexed` boolean NOT NULL; `max_length` 1..255; `number_mode` `exact`, `float`;
      `scale` 0..6; `currency_code` `^[A-Z]{3}$`; `storage_kind` `system`, `slot`, `data`; `slot`
      `^(t|u|i|f|d|z|b)[0-9]{2}$` đúng họ của kiểu (`t`, `u`: chữ, email, điện thoại, url, `t` thêm danh sách chọn;
      `i`: số `exact`, tiền; `f`: số `float`; `d`: ngày; `z`: ngày giờ; `b`: đúng sai); `field_no` không dùng lại;
      UNIQUE `(tenant_id, object_id, slot) WHERE slot IS NOT NULL` và `(tenant_id, object_id, field_no)`. Luật kho,
      mỗi luật một CHECK: `(storage_kind = 'slot') = (slot IS NOT NULL)`; `(storage_kind = 'data') =
(field_no IS NOT NULL)`; `storage_kind = 'system'` đúng ba dòng hệ thống `name` (`text`), `owner` (`owner`),
      `workspace` (`workspace`), và kiểu `owner`, `workspace` chỉ ở dòng `system`; `is_unique` chỉ với `text`,
      `email`, `phone`, `url`, và trường `is_unique` ở slot họ `u`; trường không hệ thống có `indexed` hay `is_unique`
      ở `slot`, còn lại ở `data`.
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
      mục `(tenant_id, object_id, created_at DESC, id DESC)`, `(tenant_id, object_id, updated_at DESC, id DESC)`
      (btree), `(tenant_id, object_id, name, id)`, `(tenant_id, workspace_id)` cho FK tới workspace sở hữu, và chỉ
      mục từng phần `(tenant_id, object_id, <slot>, id) WHERE <slot> IS NOT NULL AND deleted_at IS NULL` của mỗi slot.
      DDL tạm của mục Dữ liệu tới khi có số đo D12 (V4.32; ADR-0107 (Accepted) quyết 2): tập slot đề xuất A0 của ticket
      01 bước 2, `t01`-`t24`, `i01`-`i12`, `f01`-`f08`, `d01`-`d08`, `z01`-`z08`, `b01`-`b08`, `u01`-`u04`, chỉ mục
      họ `b` giữ, và `PARTITION BY HASH (tenant_id)` modulus 4 với `studio.records_p0` tới `studio.records_p3`
      (R9.5). Ticket 07 đưa DDL về kết luận của luật quyết (modulus 8, A2, A3 hay ít slot hơn) bằng một revision sau.
    - `studio.dependencies` (bảng của tenant-config/02): `ALTER TABLE` thêm `to_field_id uuid` NULL, FK ghép
      `(tenant_id, to_field_id)` tới `studio.field_defs (tenant_id, id)` ON DELETE RESTRICT, index
      `(tenant_id, to_field_id)` (ADR-0109 (Accepted) quyết 5); quyền của `dw_app` trên bảng giữ như
      tenant-config/02 cấp.
    - Trigger `studio.refuse_object_artifact_delete()` BEFORE UPDATE OF `deleted_at` trên `studio.artifacts`: khi
      `deleted_at` chuyển từ NULL sang có giá trị ở một thành phần `kind = 'object'` đã có dòng `studio.object_defs`,
      hay có một phiên bản ở giai đoạn khác `draft` (Bản ứng viên chờ duyệt cũng giữ tên) → `ERRCODE 23503`, ràng buộc
      `ck_artifacts_not_in_use`, nên `soft_delete` của tenant-config/02 trả 409 `conflict` `artifact_in_use` theo tên
      ràng buộc đã ánh xạ, với số đếm của bên dùng mà nó tính (có thể 0); xóa đối tượng là việc của W2 (Ngoài phạm vi
      "Tiến hóa lược đồ").
    - Mỗi bảng và mỗi partition: RLS ENABLE và FORCE; `tenant_isolation_object_defs`, `tenant_isolation_field_defs`,
      `tenant_isolation_picklist_options` FOR ALL dạng InitPlan; `tenant_isolation_records` AS RESTRICTIVE FOR ALL
      dạng InitPlan trên bảng cha và mỗi partition. Policy PERMISSIVE theo tầm là của record-access/03.
    - Trigger BEFORE UPDATE gọi `platform.touch_updated_at()` trên bốn bảng.
    - Quyền: `dw_app` có SELECT, INSERT, DELETE trên bốn bảng; UPDATE trên định nghĩa trừ cột khóa; UPDATE trên
      `studio.records` chỉ ở `name`, `data`, slot, `version`, `updated_*`, `deleted_*`; `REVOKE ALL` của `dw_app` trên
      từng partition, vì quyền mặc định của schema `studio` cấp SELECT cho mọi bảng mới (DO-02.2); không gì cho
      `dw_provisioner`, `dw_agent_ro`, `PUBLIC`. Downgrade gỡ trigger và cột `to_field_id` rồi xóa bốn bảng, giữ
      schema `studio`.
    - `studio.object_defs`, `studio.field_defs`, `studio.picklist_options` không có `workspace_id`: mỗi bảng một dòng
      trong `_TENANT_WIDE_ON_PURPOSE` của `packages/python/dw_platform/tests/integration/test_rls_coverage.py` với lý
      do "định nghĩa đối tượng của cả công ty" (DO-01).
    - Mô tả SQLAlchemy của bốn bảng trong tầng `adapters` của `dw_studio.records`, trên cùng `metadata` của
      `dw_studio.core.adapters.tables`, và cột `to_field_id` trên bảng `dependencies` của lõi với FK nêu đích bằng
      chuỗi `studio.field_defs`, vì lõi không nhập `dw_studio.records`; `test_metadata_matches_catalog.py` của
      studio-skeleton/02 vẫn xanh.
2. Cùng revision đăng ký khóa `studio.objects.manage` trong `platform.permissions` của tenant-rbac/01
   (ADR-0104 (Accepted)): câu INSERT nêu mọi cột NOT NULL của danh mục lúc đó, gồm `label_vi`, `area`,
   `scope_kind` `tenant` (chỉ mức `tenant`), `risk` `standard` theo bảng phân loại của tenant-rbac/01, `status`
   `active`, `owner_package` và `tenant_grantable` `true` của tenant-rbac/02 (Quyết định 24/10/2026 của spec); vai
   nào giữ khóa là việc của tenant-rbac.
3. Offboarding: bốn bảng không đăng ký bước nào vào sổ bước xóa của foundations-hardening/07; `dw_app` có DELETE trên
   cả bốn nên mỗi bảng nhận bước mặc định (câu `DELETE` chung, `_default_step` của
   `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py`), và thứ tự suy từ khóa ngoại
   RESTRICT và NO ACTION của `pg_constraint` (foundations-hardening:R11.4; "một bảng mới chỉ cần câu `DELETE` chung thì
   không đăng ký gì", Phụ thuộc của foundations-hardening): `studio.dependencies` trước `studio.field_defs` vì
   `to_field_id` giữ nó bằng FK RESTRICT, `studio.records` trước `studio.object_defs`, `studio.object_defs` trước
   `studio.artifact_versions` và `studio.artifacts` (studio-skeleton:R4.2). Không dòng nào trong `STUDIO_EXCLUSIONS`.
4. Trong `dw_studio.records`, gói con năng lực đầu tiên của `dw_studio` (studio-skeleton/02 bước 1, 4: tầng của nó vào
   các hợp đồng import mà `check_registration()` đọc):
    - `domain/field_types.py`: Literal `FieldType` với 12 giá trị của CHECK, bảng kiểu sang họ slot và bảng họ sang tập
      slot của DDL tạm (một chủ trong mã cho tập slot, test so nó với cột của `studio.records` trong `pg_attribute`);
      thêm tệp vào `WATCHED_LITERALS` của `scripts/verify_invariants.py`.
    - Mô hình tài liệu `dw.object/v1` (Pydantic v2, `extra="forbid"`): `labels`, `ai_description`, `default_access`,
      `name_field` bắt buộc (`labels`, `pd_category` bắt buộc không mặc định, `sensitive_type`, `subject_identifier`),
      `fields[]` (`api_name`, `labels`, `ai_description`, `type` chỉ mười kiểu công ty định nghĩa của R2.1, không
      `owner` hay `workspace`, `number_mode`, `scale`, `currency_code`, `max_length`, `required`,
      `is_unique`, `indexed`, `pd_category`, `sensitive_type`, `subject_identifier`, `access_mode`, `options[]` mỗi
      mục `key`, `labels`, `position`, `active` mặc định true). Không có `api_name` ở gốc: tên API của đối tượng là
      `studio.artifacts.api_name` của vỏ (tenant-config:R2.2, tenant-config:R2.10). `ai_description` không bắt buộc,
      tối đa 500 ký tự tính trên chuỗi NFC; `access_mode` mặc định `secured` khi `pd_category` khác `none`, `open` khi
      `none`; field-security/01 thêm cột `access_mode` và để móc ghi nó. Trình kiểm, bộ so sánh và móc đọc tài liệu
      qua một hàm parse của mô hình này, mặc định đã điền; giữa hai phiên bản, trường ghép theo `api_name`, lựa chọn
      theo `key`, thứ tự không tính.
    - `validate_object(document)`, mục `validate` của registry, thuần: `seal` của tenant-config/02 gọi nó, nên lỗi
      thành 422 `validation_failed` với mọi lỗi trong `errors[]` (`{path, code, message}`): kiểu (R2.1),
      `pd_category` qua `classification_problems` của `dw_kernel.personal_data` (R2.2), `api_name` trường và trùng
      tên, tên dành cho dòng hệ thống `name`, `owner`, `workspace` → `reserved_api_name` (R2.3), `access_mode` `open`
      của trường `sensitive` (R2.5), `ai_description` của đối tượng và mỗi trường (R2.6), luật kho của bước 1
      (`is_unique` ngoài bốn kiểu chữ → `unique_not_supported`), ngân sách slot đếm trên tài liệu (R1.6; ở W1 không
      bỏ được trường nên tài liệu chứa mọi trường đã áp), nhãn `vi` khác rỗng.
    - `check_against_live(live_document | None, document)`, thuần, mọi lỗi một lần: trường hay lựa chọn của bản Đang
      dùng vắng ở bản mới → `field_removed`, `option_removed` (tắt lựa chọn bằng `active: false`); đổi `type`,
      `number_mode`, `scale`, `currency_code`, `is_unique` hay `indexed` của trường đã phát hành → `field_immutable`
      (R2.4, CO6); hạ `pd_category` của trường đã phát hành hay của `name_field` → `pd_category_lowered` (đổi
      `sensitive_type` giữa các loại nhạy cảm, hay `subject_identifier`, thì được, qua người thứ hai); trường mới có
      `pd_category` khác `none` mà `open` → lỗi của R2.5 (CO24); `live_document` None thì mọi trường là mới. Lỗi là
      danh sách `{path, code, message}` như của `validate_object`; móc ném nó trong `ObjectVersionRejected`, ngoại lệ
      có kiểu của `dw_studio.records`. Móc gọi nó làm hàng rào cuối;
      ticket 06 đăng ký nó vào bảng kiểm theo loại lúc Gửi kiểm định (`agent-lifecycle:R2.7`), để người gửi nhận 422
      trước khi có phê duyệt.
    - Bộ so sánh chỉ siết của loại `object` (R1.8), hàm thuần: báo chỉ siết khi và chỉ khi đối tượng có phiên bản Đang
      dùng và mọi khác biệt là một trường từ `open` sang `secured` hay `default_access` hẹp hơn theo thứ tự
      `public_read_write`, `public_read`, `private`; mọi khác biệt khác, kể cả `ai_description` hay nhãn, là không chỉ
      siết. Ticket 06 nối nó vào lệnh Gửi kiểm định của agent-lifecycle, nơi `LifecycleService` ghi `tighten_only` và
      `compared_live_hash` theo kết quả của nó (R1.2, R1.7; `agent-lifecycle:R2.8`).
    - Bộ trích phụ thuộc thuần, trả danh sách rỗng ở W1 (chưa có trường tham chiếu), có test fixture.
    - Móc phát hành `MetadataService.apply(tx, version_id)`, khai ở mục `ArtifactKindRegistry` của loại (trường
      `publish_hook` mà tenant-config/02 thêm; ADR-0109 (Accepted) quyết 1), mà agent-lifecycle gọi trong giao dịch đưa
      phiên bản lên Đang dùng, ở handler `studio.publish.object.decided` và ở nhánh chỉ siết (`agent-lifecycle:R5.5`,
      `agent-lifecycle:R2.9`; ticket 06 kiểm hai đường đó đầu-cuối). Theo thứ tự, trong giao dịch của bên gọi:
      lấy `pg_advisory_xact_lock` loại trừ trên `object_lock_key(tenant_id, object_id)`, hàm duy nhất của
      `dw_studio.records` mà RecordService của ticket 03 dùng lại cho khóa chia sẻ (ADR-0107 (Accepted) quyết 3, 5);
      `applied_version_id` đã là phiên bản này → không làm gì, không audit; `check_against_live` với tài liệu của
      `applied_version_id` → lỗi thì ném ngoại lệ có kiểu, giao dịch phát hành cuộn lại và định nghĩa không đổi; lần
      đầu tạo `studio.object_defs` (`api_name` chép từ vỏ) và ba dòng `system`: `name` (`text`, nhãn và loại dữ liệu cá
      nhân của `name_field`), `owner` (`owner`, `pd_category` `none`), `workspace` (`workspace`, `none`), không slot,
      không `field_no`; mỗi trường mới nhận slot trống nhỏ nhất của họ (trường `indexed` hay `is_unique`) hoặc
      `next_field_no` (trường trong `data`); mọi thuộc tính khác mà tài liệu mang được ghi cho đối tượng (`labels`,
      `ai_description`, `default_access`), cho trường có sẵn (nhãn, `ai_description`, `required`, `max_length`,
      `pd_category`, `sensitive_type`, `subject_identifier`) và cho lựa chọn (thêm mới; sửa `labels`, `position`,
      `active`); `applied_version_id` là phiên bản này và `schema_version` là `version_no` của nó (số của vỏ, không
      bộ đếm thứ hai; một quan hệ hai bảng nên móc giữ nó và test R1.1 kiểm, không CHECK); audit `studio.object.created`,
      `studio.object.updated`, `studio.field.created`, `studio.field.updated`, `studio.picklist.updated` chỉ mang khóa
      và phiên bản. Sau móc, định nghĩa đọc lại bằng `definition_of(document)` của phiên bản đó: hàm thuần trong
      `dw_studio.records.domain`, chiếu tài liệu đã parse thành những gì tài liệu quyết (của đối tượng: `labels`,
      `ai_description`, `default_access`; mỗi trường theo `api_name`, kể cả `name`: mọi thuộc tính tài liệu mang có cột
      trong `studio.field_defs`, nên `access_mode` vào phép so khi field-security/01 thêm cột của nó; mỗi lựa chọn theo
      `key`: `labels`, `position`, `active`), không gồm id, `slot`, `field_no`, `next_field_no` hay thời điểm, mà kho
      định nghĩa đọc ra cùng hình để so; hai dòng `owner`, `workspace` không do tài liệu quyết nên nằm ngoài phép so và có
      khẳng định riêng. Móc chỉ áp định nghĩa: nó không đổi giai đoạn phiên bản và không ghi
      `studio.version.published`, sự kiện mà agent-lifecycle ghi đúng một lần mỗi lần phát hành
      (`agent-lifecycle:R2.9`, `agent-lifecycle:R5.5`).
    - Mục `ArtifactKindRegistry` của loại `object`: `studio.objects.manage` (mức `tenant`) là khóa đọc, khóa ghi và
      khóa gửi của loại cho đọc, tạo, lưu nháp và Gửi kiểm định (`tenant-config:R2.11`, `tenant-config:R2.12`,
      `tenant-config:R2.15`), `validate_object`, bộ trích, móc phát hành ở trên; migration thêm dòng `object` với
      `has_quality_gate = false` vào `studio.artifact_kinds` (`ck_artifacts_kind` thành FK tới bảng này, OPS-b cạnh 4,
      `tenant-config:R2.14`). Bộ loại của app chạy thật thay hằng `PLATFORM_KINDS` của
      `dw_studio.core.application.registry` (tenant-config/02), vì hợp đồng "Studio core imports no capability" cấm lõi
      nhập `dw_studio.records`: hàm `platform_kinds(...)` trong `dw_studio/kinds.py`, một module chứ không phải gói con,
      nên `check_registration()` của studio-skeleton/02 không coi nó là năng lực và hợp đồng `independence` không áp; nó
      nhận qua tham số một nhà máy `Callable[[ArtifactTx], ObjectDefinitionStore]`, Protocol mà
      `dw_studio.records.application` khai, và không nhập adapter nào; composition root dựng nhà máy đó từ adapter SQL
      của lõi và của `dw_studio.records`, dùng chung phiên của giao dịch (`CLAUDE.md`: chỉ composition root nhập adapter
      cụ thể), không client cấp module. `build_studio(..., kinds=None)` và
      `create_app(studio_kinds=None)` dùng `platform_kinds(...)` khi không có `kinds=`, nên loại chỉ có trong test vẫn
      chỉ vào app qua `studio_kinds=` (ý của tenant-config:R2.15 giữ nguyên); móc chạy trong giao dịch của `ArtifactTx`
      nó nhận. Composition root nào gọi móc ngoài API (handler `.decided` của ticket 06 nếu chạy ở worker) dựng
      registry bằng cùng `platform_kinds(...)`, và ticket 06 khai `dw-studio` cho app đó. Test ở composition root so
      registry với các dòng `studio.artifact_kinds`.
5. `ObjectSchemaProjector` trong `dw_studio.records`: dựng JSON Schema 2020-12 cho tạo, sửa, truy vấn từ định nghĩa,
   đọc định nghĩa qua Protocol `ObjectDefinitionReader` của `dw_studio.records.application`, với `tenant_id` của khóa lấy
   từ ngữ cảnh truy cập hay lượt chạy của bên gọi, không từ yêu cầu (`CLAUDE.md`, Per-tenant artifacts), khóa theo
   `(tenant_id, object_id, schema_version)`, vì id của thành phần đi theo gói sang công ty khác
   (ADR-0109 (Accepted) quyết 1) và khóa đệm mang tenant (`CLAUDE.md`, Tenancy and authorization); bộ đệm nếu có là LRU có trần
   số mục trong tiến trình, không trong Valkey. Nó trả `ai_description` của đối tượng và mỗi trường trong một bảng tách
   khỏi lược đồ, không đặt vào `title`, `description` hay nhãn (R3.7, YC48). Lược đồ truy vấn ở đây chỉ nêu trường lọc
   được, sắp được và kiểu giá trị của chúng; ngữ pháp cây lọc là của ticket 04 và app-standards/03. Route
   `GET /api/v1/studio/objects`, describe và phần lọc theo khóa đọc đối tượng và quyết định trường của người gọi (R3.1
   tới R3.6, phần trường Đã ẩn của R3.7) thuộc ticket 03, vì chúng cần tenant-rbac/04 và field-security/01, mà cả hai
   chờ ticket này (Quyết định 24/10/2026 của spec).

## Tiêu chí chấp nhận

- [x] R1.1 (CO2): móc phát hành, gọi qua mục `ArtifactKindRegistry` của loại `object` cho một `dw.object/v1` 20
      trường trong giao dịch đưa phiên bản lên Đang dùng mà fixture mở thay agent-lifecycle (phê duyệt `approved` dựng
      bằng fixture; đường thật kiểm ở ticket 06), áp định nghĩa trong cùng giao dịch, số quan hệ của schema `studio`
      trong `pg_class` không đổi; `dw_app` chạy `CREATE TABLE studio.x` hay
      `CREATE INDEX ON studio.records` → bị từ chối; cấp `CREATE` trên `studio` cho `dw_app` → test đỏ.
- [x] R1.1: sau mỗi lần áp, định nghĩa đọc lại bằng `definition_of(document)` của phiên bản đó, `applied_version_id` là
      phiên bản đó và `schema_version` là `version_no` của nó; lần đầu có ba dòng `system` (`name` mang `pd_category`
      của `name_field`); phiên bản sau chỉ hạ `default_access` từ `public_read_write` xuống `private` → cột đổi theo,
      gỡ bước ghi `default_access` → test đỏ; gọi móc lần hai cho cùng phiên bản → không dòng nào đổi, không audit mới;
      `studio.object_defs.api_name` bằng `studio.artifacts.api_name`.
- [x] R1.1: xóa mềm thành phần `object` đã có định nghĩa, hay có Bản ứng viên ở `awaiting_approval` (đặt bằng vai
      migrator) → 409 `artifact_in_use`, `deleted_at` giữ NULL; thành phần `object` chỉ có bản Nháp xóa mềm được; thành
      phần `fixture` có bản `live` mà không ai dùng xóa mềm được (R3.3 của tenant-config/02 giữ xanh); gỡ trigger, hay
      bỏ điều kiện `kind`, → test đỏ.
- [x] R1.8 (CO23): test thuộc tính trên cặp tài liệu sinh ngẫu nhiên: bộ so sánh báo chỉ siết đúng khi mọi khác biệt
      là đóng trường hay hạ `default_access`; phiên bản đầu (chưa có Đang dùng) → không chỉ siết; nâng `default_access`,
      mở một trường, đổi nhãn hay `ai_description` → không chỉ siết; vừa đóng `phone` vừa đổi nhãn → không chỉ siết; chỉ
      đổi thứ tự `fields[]`, hay ghi tường minh một giá trị mặc định → không khác biệt; coi thay đổi trộn đó là chỉ siết
      → test đỏ.
- [x] R1.3 (CO3): trên app dựng không `studio_kinds=`, người thiếu `studio.objects.manage` tạo thành phần loại `object`
      qua `POST /api/v1/studio/artifacts` → 403 `permission_denied`, và `PUT .../draft` một thành phần `object` có sẵn →
      404 như thành phần không tồn tại, vì khóa đó cũng là khóa đọc (`tenant-config:R2.11`, TC24); không dòng mới trong
      `studio.artifact_versions`; người giữ khóa → 201; đổi khóa ghi của mục sang một khóa người thiếu kia giữ → test
      đỏ (lệnh Gửi kiểm định kiểm ở ticket 06).
- [x] R1.4: tài liệu không nêu `default_access` → dòng có `private`; giá trị ngoài CHECK bị từ chối theo tên ràng
      buộc.
- [x] R1.5 (CO4): hai giao dịch song song, mỗi giao dịch lấy khóa của móc rồi chạy bước cấp slot của móc cho một trường
      lọc được họ `t` mới (hai `api_name` khác nhau) của cùng một đối tượng → hai slot khác nhau; gỡ khóa advisory và
      UNIQUE `(tenant_id, object_id, slot)` → hai trường cùng slot, test đỏ; một giao dịch giữ
      `pg_advisory_xact_lock_shared` trên `object_lock_key` của đối tượng → móc chờ tới khi giao dịch đó kết thúc.
- [x] R1.6: đối tượng đã dùng hết slot `t` thêm một trường lọc được kiểu `text` → 422 có con trỏ
      `/fields/<n>`, định nghĩa không đổi; `is_unique` trên trường `number` → `unique_not_supported`; dòng
      `storage_kind = 'slot'` không slot, hay `data` không `field_no`, ghi thẳng bằng SQL → CHECK từ chối.
- [x] R2.1: giá trị CHECK của `type` đọc từ `pg_constraint` bằng `FieldType`, theo mẫu
      `test_fixed_set_checks_db.py`; trường công ty kiểu `json`, `user` hay `owner` → 422 qua `seal`.
- [x] R2.2 (CO5): trường thiếu `pd_category` → 422 `validation_failed` qua `seal` với `errors[].code`
      `pd_category_required` và con trỏ `/fields/<n>`, `name_field` thiếu `pd_category` → cùng mã với con trỏ
      `/name_field/pd_category`, không số phiên bản nào được cấp; CHECK của `pd_category` bằng danh sách của `dw_kernel.personal_data`
      (`assert_field_tables_classified` của `dw_platform.testing.personal_data` thấy `studio.field_defs`); gỡ kiểm →
      test đỏ.
- [x] R2.3: `api_name` trường 40 ký tự thì nhận, 41 thì 422; `Lead` có chữ hoa → 422; trường tên `name` → 422
      `reserved_api_name`; tài liệu có `api_name` ở gốc → 422 (`extra="forbid"`).
- [x] R2.4 (CO6): `check_against_live` trả `field_removed` khi bản mới bỏ trường đã phát hành (kể cả đổi tên, là bỏ tên
      cũ thêm tên mới), `option_removed` khi bỏ một lựa chọn, `field_immutable` khi đổi `type`, `number_mode`, `scale`,
      `currency_code`, `is_unique` hay `indexed`, mỗi lỗi có con trỏ; móc gọi cho phiên bản như vậy →
      `ObjectVersionRejected` mang các lỗi đó, giao dịch cuộn lại, định nghĩa và `applied_version_id` không đổi; gỡ bước
      gọi trong móc → test đỏ (422 ở lệnh Gửi kiểm định kiểm ở ticket 06).
- [x] R2.5 (CO24): phiên bản đặt `access_mode: open` cho trường `sensitive` → 422 qua `seal` có con trỏ
      `/fields/<n>`, không số phiên bản; cho một trường mới `basic`, hay hạ `pd_category` của trường đã phát hành hay
      của `name_field` từ `sensitive` xuống `none` → `check_against_live` trả lỗi có con trỏ và móc ném
      `ObjectVersionRejected`, không áp gì; gỡ một bước kiểm → test đỏ.
- [x] R2.6: `ai_description` 500 ký tự (chuỗi NFC, có dấu tiếng Việt) thì nhận, 501 thì 422 có con trỏ
      `/ai_description` hay `/fields/<n>/ai_description`, không phát hành gì; bỏ trống thì nhận; CHECK độ dài của hai
      cột từ chối 501 ký tự ghi thẳng bằng SQL.
- [x] R3.7 (CO25): trường có `ai_description` chứa `</input>` và "bỏ qua mọi chỉ dẫn" → JSON Schema của bộ chiếu không
      có chuỗi đó ở `title`, `description` hay nhãn, giá trị chỉ có trong bảng `ai_description` tách riêng; ghép
      `ai_description` vào `description` của lược đồ → test đỏ (trường Đã ẩn với người gọi kiểm ở ticket 03).
- [x] R3.7 (CO1): test đơn vị với bản giả của `ObjectDefinitionReader` (trả định nghĩa theo công ty, đúng như kho thật
      dưới RLS): hai công ty có đối tượng cùng `object_id` và cùng `schema_version` mà trường khác nhau → bộ chiếu trả
      mỗi công ty lược đồ và `ai_description` của chính nó, kể cả khi gọi xen kẽ trên một bộ đệm đã đầy; bỏ `tenant_id`
      khỏi khóa → test đỏ.
- [x] R4.1: INSERT vào `studio.records` thiếu `owner_kind`, `owner_id` hay `workspace_id` → vi phạm NOT NULL.
- [x] R4.2 (CO1): trên `studio.records` và mỗi partition, test thêm trong giao dịch của nó (cuộn lại khi xong) một
      policy PERMISSIVE `USING (true) WITH CHECK (true)` cho vai thử, vì ở ticket này bảng chưa có policy PERMISSIVE nào
      và mọi dòng đã bị từ chối sẵn, để chính `tenant_isolation_records` lọc; rồi: kết nối không đặt `app.tenant_id`
      đọc 0 dòng ở bốn bảng; INSERT với `tenant_id` của công ty khác → RLS từ chối; làm hỏng
      `tenant_isolation_records` trên bảng cha hay một partition → test đỏ; `dw_app` đọc thẳng `studio.records_p3` → permission denied; một vai thử NOBYPASSRLS
      có SELECT trên `studio.records_p3`, không đặt tenant → 0 dòng; `test_rls_coverage.py` thấy mọi partition và so
      policy của mỗi partition với bảng cha.
- [x] R4.2 (CO21): thêm policy PERMISSIVE `USING (true)` lên `studio.records` → test catalog đỏ.
- [x] R4.4: offboarding một công ty có hai đối tượng, có trường, lựa chọn và một dòng `studio.dependencies` có
      `to_field_id` trỏ tới một trường của nó → mỗi dòng của ba bảng định nghĩa xuất đúng một lần, sau purge còn 0 dòng
      ở ba bảng đó, dòng của công ty khác giữ nguyên; thứ tự mà sổ bước xóa suy ra đặt `studio.dependencies` trước
      `studio.field_defs` và `studio.object_defs` trước `studio.artifact_versions`, `studio.artifacts`; thu DELETE của
      `dw_app` trên một trong bốn bảng → test phủ offboarding của studio-skeleton/01 đỏ, nêu tên bảng
      (studio-skeleton:R4.1, studio-skeleton:R4.2). Dòng `studio.records` của R4.4 kiểm ở ticket 03 (CO20), vì `dw_app`
      chưa có policy PERMISSIVE nào trên bảng đó tới record-access/03.
- [x] R4.6 (CO1): bằng `dw_migrator`, vai bỏ qua RLS nên chỉ khóa ngoại chặn được (ở ticket này `studio.records` chưa
      có policy PERMISSIVE nào cho `dw_app` ghi), INSERT dòng của công ty A vào `studio.records` hay `studio.field_defs`
      với `object_id` của công ty B, vào `studio.picklist_options` với `field_id` của B, vào `studio.object_defs` với
      `id` của một thành phần của B hay `applied_version_id` của một phiên bản của B, vào `studio.records` với
      `workspace_id` của B, và vào `studio.dependencies` với `to_field_id` của một trường của B → lỗi FK ghép (23503),
      không dòng nào; migration thử đổi một FK ghép thành FK một cột → test đỏ.
- [x] R9.5: test catalog thấy `studio.records` là `PARTITION BY HASH (tenant_id)` với 4 partition `studio.records_p0`
      tới `studio.records_p3`, mỗi partition ENABLE và FORCE RLS, không quyền nào của `dw_app` (DDL tạm; ticket 07 giữ
      hay đổi theo số đo D12).
- [x] R9.4: test catalog đọc `pg_index` thấy đúng tập slot của DDL tạm, mỗi slot một chỉ mục từng phần đúng vị từ, và
      tập cột slot trong `pg_attribute` bằng bảng họ sang tập slot của `field_types.py`; thêm một cột slot ở migration
      mà không thêm vào bảng đó → test đỏ.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `db/migrations/sql/0001_platform_grants.sql:27-46`; `db/migrations/sql/0001_platform_baseline.sql:478-485`;
  spec: R1.1, R4.1.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:303-310`;
  `.claude/plans/studio/foundations-hardening/spec.md:412-415`; spec: R4.4.
- `packages/python/dw_platform/tests/integration/test_rls_coverage.py:604`; spec: R4.2.
- `packages/python/dw_memory/tests/integration/test_fixed_set_checks_db.py:135`; `scripts/verify_invariants.py:117-121`;
  spec: R2.1.
- `db/migrations/versions/0004_touch_updated_at_yields.py:44`; spec: Dữ liệu.
- ADR-0107 (Accepted) quyết định 1, 2, 3, 5; ADR-0109 (Accepted) quyết định 1, 5 (`to_field_id`); ADR-0106 (Accepted)
  quyết định 1, 2.
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
- 2026-10-24 (agent): vòng sửa 4, lượt sáu: tiêu chí R4.4 nêu test phủ offboarding của studio-skeleton/01, nay đọc khóa
  ngoại `RESTRICT` từ `pg_constraint` và đòi thứ tự xóa duy nhất liệt kê mỗi bảng sau mọi bảng giữ khóa tới nó
  (studio-skeleton:R4.2), thay cho "test walk `pg_class`"; bước 3 đã đúng luật đó.
- 2026-10-25 (agent): lượt h, theo V4.32 của Đạt: modulus và DDL của `studio.records` theo luật quyết của ticket 01 (modulus 8 chỉ khi A1 đạt ngưỡng và cho lợi ích bảo trì đo được, không thì 4; chỉ mục `updated_at` và họ `b` theo biến thể được chọn), thay cho "đường lui" của DO-15; ticket này vẫn chờ ticket 01. Tiêu chí không đổi ngoài chữ "đường lui" của R9.5.
- 2026-10-26 (agent): lượt h, theo H-2 (foundations-hardening/07, R11.4, R11.5, FH33): `_ORDERED_FIRST` đã bỏ, nên bước 3 đăng ký một bước xóa cho bốn bảng vào sổ bước xóa ở composition root của worker, thứ tự suy từ khóa ngoại RESTRICT và NO ACTION của `pg_constraint`, thay cho bốn mục chèn tay; tiêu chí R4.4 thêm ca khai trùng bảng. Ticket đã chờ foundations-hardening/07; không thêm cạnh.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk, vì ticket có migration; route là của tenant-config/02), ở `4891310`, đối chiếu hai hợp đồng đang dựng (studio-skeleton/02, tenant-config/02: ticket, và mã chưa commit trong cây chỉ làm gợi ý). `check_plans.py` 23 Đạt, 1 cảnh báo collision của ticket 06 với 03, không của ticket này. 1 CRITICAL, 12 HIGH, đã sửa ở ticket, spec, ticket 06, ticket 07 mới và ADR-0107 (Accepted), như dưới.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): CRITICAL: bộ chiếu khóa theo `(object_id, schema_version)`, không có tenant, trong khi id của thành phần đi theo gói sang công ty khác (ADR-0109 (Accepted) quyết 1) và `CLAUDE.md` đòi khóa đệm mang tenant. Sửa: khóa `(tenant_id, object_id, schema_version)`, bộ đệm LRU có trần trong tiến trình, tiêu chí R3.7 (CO1) hai công ty cùng id; CO1 của spec thêm ca đó. Nếu sai thì: không có; CRITICAL không nhận rủi ro.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 1: DDL của `studio.records` (modulus, tập slot, BRIN, họ `b`) là "những gì luật quyết của ticket 01 chốt", mà lần đo `--scale d12` chờ máy tham chiếu (Chờ Đạt 23), nên ticket không dựng được và Blocked by 01 không bao giờ hết (Xong của ticket 01 là lần chạy d12). Sửa: DDL tạm (modulus 4 theo nhánh "không thì 4" của luật quyết, tập slot A0 của ticket 01 bước 2, btree `updated_at`, giữ chỉ mục họ `b`); bỏ 01 khỏi Blocked by, đọc kết quả smoke của ticket 01 trước khi viết revision; R9.2 sang ticket 07 mới (`ready-for-human`, Chờ Đạt 23), ticket đưa DDL về kết luận D12 bằng một revision sau; ADR-0107 (Accepted) thêm mục sửa đổi. Thay phần thứ tự của DO-15 và V4.32 ("số đo trước khi ticket 02 lên ready-for-agent", "ticket 02 vẫn chờ ticket 01"). Nếu sai thì: ticket 02 trở lại Blocked by 01 và chờ máy tham chiếu, ticket 07 rút, DDL lấy thẳng kết luận D12.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 2: tài liệu không mang mã trường, ticket không nói trường hay lựa chọn vắng ở bản mới thì sao, nên "đổi `api_name` của trường" không kiểm được và móc có thể xóa dòng `field_defs` (slot về trống trong khi bản ghi còn giá trị). Sửa: ghép theo `api_name` và `key`; vắng → `field_removed`, `option_removed`; tắt lựa chọn bằng `active: false`. Nếu sai thì: móc giữ dòng và chỉ ẩn trường, R2.4 nói lại cách nhận ra đổi tên.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 3: R2.4 chỉ cấm đổi `api_name` và kiểu, nên đổi `scale` (nghĩa của số nguyên đã nhân 10^scale), `number_mode`, `currency_code`, `is_unique` (họ `t` sang `u`) hay `indexed` (từ `data` lên slot, việc promote của W2) áp vào metadata trong khi dữ liệu đã lưu đổi nghĩa. Sửa: R2.4 của spec và CO6 cấm các thuộc tính đó → `field_immutable`. Nếu sai thì: tiến hóa lược đồ của W2 làm chúng đổi được qua expand, migrate, contract.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 4: hạ `pd_category` của trường đã phát hành từ `sensitive` rồi đặt `open` đi vòng R2.5, trái ADR-0106 (Accepted) quyết 2 ("never be opened"). Sửa: R2.5 của spec và CO24 cấm hạ → `pd_category_lowered`. Nếu sai thì: hạ được qua người thứ hai, và field-security đặt lại `access_mode` về `secured` khi hạ.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 5: móc chỉ kể tạo, thêm trường, thêm lựa chọn, sửa nhãn; một bản chỉ siết hạ `default_access` lên Đang dùng mà cột record-access đọc không đổi (failure-modes #1, #2), móc chạy lại thì `schema_version` tăng lần hai, và `schema_version` là bộ đếm thứ hai cạnh `version_no` của vỏ. Sửa: móc ghi mọi thuộc tính, định nghĩa đọc lại bằng `definition_of(document)`; `applied_version_id` (FK ghép tới phiên bản) làm móc lũy đẳng; `schema_version` là `version_no` của phiên bản đã áp. Nếu sai thì: `schema_version` trở lại bộ đếm riêng cộng 1 mỗi lần áp, và móc kiểm lũy đẳng bằng `content_hash`.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 6: `name_field.pd_category` không có chỗ lưu, kiểu `owner`, `workspace`, `user` và `storage_kind` `system` không có người ghi. Sửa: lần áp đầu tạo ba dòng `system` (`name`, `owner`, `workspace`), tên dành riêng → `reserved_api_name`; bỏ `user` khỏi CHECK và `FieldType` (không ai ghi, `WATCHED_LITERALS` sẽ đỏ). Nếu sai thì: `name_labels`, `name_pd_category` thành cột của `studio.object_defs`, và `user` trở lại cùng trường tham chiếu người dùng của W2.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 7: `validate(document)` của registry là hàm thuần trên một tài liệu (tenant-config/02 bước 5, `registry.py` đang dựng), nên phép so với bản Đang dùng (R2.4, phần trường mới của R2.5) không có chỗ chạy. Sửa: `validate_object` thuần chạy trong `seal`; `check_against_live` thuần, móc gọi làm hàng rào cuối, ticket 06 đăng ký vào bảng kiểm lúc gửi (`agent-lifecycle:R2.7`). Nếu sai thì: tenant-config đổi chữ ký thành `validate(document, live)` và `seal` đọc bản Đang dùng.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 8: `api_name` của đối tượng có ba bản (`studio.artifacts`, tài liệu, `studio.object_defs`), và xóa mềm thành phần rồi tạo lại cùng tên làm UNIQUE của `studio.object_defs` hỏng ở giao dịch phát hành sau khi người thứ hai đã duyệt. Sửa: tài liệu không mang `api_name`, móc chép từ vỏ; trigger từ chối xóa mềm thành phần `object` đã có định nghĩa (409 `artifact_in_use`; xóa đối tượng là W2). Nếu sai thì: xóa mềm được, định nghĩa và bản ghi theo sau bằng lane purge của W2.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 9: bước 3 đăng ký một bước xóa cho bốn bảng mà không nói bước làm gì, trái Phụ thuộc của foundations-hardening ("một bảng mới chỉ cần câu `DELETE` chung thì không đăng ký gì") và cách tenant-config/02 làm. Sửa: bước mặc định, không đăng ký; tiêu chí R4.4 thay ca khai trùng (FH33 của foundations-hardening) bằng ca thu DELETE; spec sửa cùng. Nếu sai thì: bước đăng ký có `run` nêu rõ, cùng lý do bước chung không đủ.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 10: luật chọn kho chưa nói "lọc được" là gì, `is_unique` trên kiểu không có họ `u` thì sao, dòng nào ở `system`. Sửa: luật kho ở bước 1 thành CHECK, `unique_not_supported`. Nếu sai thì: `is_unique` mở cho kiểu khác cùng họ slot mới của W2.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 11: `PLATFORM_KINDS` nằm ở `dw_studio.core.application.registry` (mã đang dựng của tenant-config/02), mà hợp đồng "Studio core imports no capability" cấm lõi nhập `dw_studio.records`, nên mục `object` không vào được app chạy thật như bước 4 cũ nói. Sửa: bộ loại rời lõi sang module ngoài `dw_studio.core`, mọi composition root đọc cùng chỗ; tiêu chí R1.3 chạy trên app dựng không `studio_kinds=`. Nếu sai thì: `build_studio` ghép mục `object` vào sau `PLATFORM_KINDS`, và worker làm như vậy ở composition root của nó.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): HIGH 12: móc lấy khóa advisory "theo công ty" còn RecordService lấy khóa chia sẻ trên (công ty, đối tượng) (ADR-0107 (Accepted) quyết 3), hai khóa không loại trừ nhau, nên một lần ghi bản ghi chụp định nghĩa cũ ngay lúc móc đổi nó. Sửa: móc lấy khóa loại trừ trên `object_lock_key(tenant_id, object_id)`, một hàm ticket 03 dùng lại; ADR-0107 (Accepted) quyết 5 sửa cùng. Nếu sai thì: hai khóa, theo công ty cho slot và (công ty, đối tượng) cho định nghĩa.
- 2026-11-03 (agent): MEDIUM, chưa sửa, cho người dựng: (a) nhãn `vi` của đối tượng, trường, lựa chọn cũng là chữ của công ty: bộ chiếu không đặt chúng vào `title`, `description` hay mô tả `enum` dưới dạng chỉ dẫn, như `ai_description`; ca eval tiêm lệnh qua nhãn là của tools-and-skills/03. (b) `owner_id` không có FK: người phụ trách thuộc công ty khác hay không tồn tại là việc RecordService (ticket 03) và lần giao của record-access/05 chặn. (c) Audit của móc ở handler `.decided` theo luật lane của `CLAUDE.md`: người đã quyết (người duyệt) là actor, `details.lane` là tên lane; ở nhánh chỉ siết là người gửi; ticket 06 kiểm. (d) Một DW principal giữ `studio.objects.manage` (`standard`, `tenant_grantable`) phát hành một mình bản chỉ siết đóng mọi trường: vai nào giữ khóa là của tenant-rbac và org-and-principals/03. (e) Giảm `max_length` hay bật `required` trên trường đã có bản ghi: bản ghi cũ vẫn đọc được, RecordService (ticket 03) chỉ kiểm giá trị trong thân lần ghi. (f) Móc lỗi sau khi phê duyệt đã `approved`: giao dịch cuộn lại, phiên bản về Nháp với mã lý do là việc của handler (agent-lifecycle:R5.5, ticket 06). (g) Test đặt `stage` bằng vai migrator có thể vướng `studio.guard_version_stage()` khi agent-lifecycle/03 vào trước; khi đó dựng phiên bản `live` qua fixture của agent-lifecycle.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): lượt xác nhận thứ nhất (người đọc mới): CRITICAL, HIGH 2, 3, 6, 9, 10, 12 đóng; HIGH 1, 4, 5, 7, 8, 11 chưa đóng và ba câu mới (`name_field` không bắt buộc nên tên người có thể ở `none` và `open`; R1.3 403 trái TC24 của tenant-config/02 khi người gọi không đọc được; kiểu `owner` qua được `seal` rồi vỡ CHECK sau khi duyệt), đã sửa: kết quả smoke của ticket 01 không còn là điều kiện, hạ `pd_category` của `name_field` bị từ chối, `name_field` và `pd_category` của nó bắt buộc, `definition_of` có định nghĩa, lỗi của `check_against_live` quan sát qua `ObjectVersionRejected` (422 ở ticket 06), trigger chặn cả thành phần có Bản ứng viên, `platform_kinds(...)` ở `dw_studio/kinds.py`, R1.3 thành 404 cho lưu nháp và gửi (spec R1.3, CO3, ticket 06 sửa cùng), `type` của tài liệu chỉ mười kiểu.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): lượt xác nhận thứ hai (người đọc mới): C1-C4, C6, C8, C10, C11 đóng; còn `definition_of` với `access_mode` chưa có cột và hai dòng `owner`, `workspace`; trigger chưa giới hạn `kind = 'object'` (trái R3.3 của tenant-config/02); phụ thuộc của `platform_kinds(...)` chưa nêu; và ba HIGH mới: test R1.5 không dựng được qua hai phiên bản (chỉ mục một bản chưa phát hành, `field_removed`), ca hai công ty cùng `object_id` không gieo được trong DB vì PK của `studio.artifacts` là `id` trong mã đang dựng, các ca âm R4.2 trên `studio.records` không đỏ được khi chưa có policy PERMISSIVE nào (failure-modes #3). Đã sửa cả sáu: `access_mode` vào phép so cùng cột của field-security/01, hai dòng hệ thống khẳng định riêng; `kind = 'object'` và ca `fixture` xanh; nhà máy `ObjectDefinitionStore` do composition root dựng; R1.5 kiểm ở bước cấp slot; bộ chiếu đọc qua `ObjectDefinitionReader`, ca hai công ty là test đơn vị với bản giả; R4.2 thêm policy PERMISSIVE thử trong giao dịch test để chính policy tenant lọc. Sáu bản sửa này không qua người đọc mới (gate chỉ cho hai lượt chạy lại): nhận rủi ro theo ủy quyền, vì ticket chưa dựng và mọi chỗ sửa nằm trong tiêu chí có test. Nếu sai thì: lỗi lộ ra lúc dựng, ghi ở đây và sửa ticket.
- 2026-11-03 (agent): MEDIUM thêm, chưa sửa: (h) từ ticket này tới record-access/03, `studio.records` chỉ có policy RESTRICTIVE (đóng: `dw_app` không đọc ghi dòng nào), khuôn RESTRICTIVE cộng `record_access_*` của `CLAUDE.md` và phép kiểm khuôn trong `test_rls_coverage.py` đến cùng record-access/03 (bước 7 của nó); không nới phép kiểm nào ở đây. (i) Chữ ký móc `(tx, version_id)` không mang actor: móc lấy actor của audit từ ngữ cảnh mà bên gọi đặt trên giao dịch (người duyệt và `details.lane` ở handler `.decided`, người gửi ở nhánh chỉ siết), ticket 06 kiểm. (j) field-security/01 neo `02-luoc-do-dinh-nghia-object.md:32` cho `pd_category`, nay ở dòng 38 sau lần viết lại; gate của field-security/01 sửa neo.
- 2026-11-03 (agent): bảng cặp: 02~~01, `check_plans.py` báo chung tên `studio.object_defs`, `studio.field_defs`, `studio.records`, `studio.records_p0`, nhưng ticket 01 tạo chúng trong DDL của harness trên database `dw_bench` riêng, không trong chuỗi migration, nên không chung bảng, route, migration, config hay prompt; không đặt cạnh, vì Xong của ticket 01 chờ máy tham chiếu. 07~~03: chung `studio.records`, `studio.record_write_keys`, đã đặt ticket 07 chờ ticket 03. 06~03 (`details.reason_code`): không thuộc ticket này. Tệp chung với ticket đang mở ngoài area: chuỗi migration, `dw_studio/core/application/registry.py`, `dw_studio/core/adapters/tables.py`, `apps/api/src/dw_api/bootstrap/studio.py`, `apps/api/src/dw_api/main.py` (tenant-config/02, lane 1), `test_rls_coverage.py`, `test_privileges.py`, `scripts/verify_invariants.py`, dòng `platform.permissions` (tenant-rbac/03, usage-and-limits/02), hợp đồng import trong `pyproject.toml`.
- 2026-11-03 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): quyết định khi dựng, mỗi cái kèm Nếu sai thì:
    - (1) Bộ so sánh: phiên bản không khác gì bản Đang dùng thì không chỉ siết (`Comparison.tighten_only` cần ít nhất
      một khác biệt), nên vẫn qua người thứ hai. Nếu sai thì: đổi điều kiện thành "mọi khác biệt", phiên bản giống hệt
      được phát hành một mình ở ticket 06.
    - (2) `pd_category` của mô hình là `PdCategory | None`, None là "thiếu" và `classification_problems` báo
      `pd_category_required`, để mọi lỗi về cùng một lần (cùng hình `ClassifiedField` của kernel). Nếu sai thì: khóa
      bắt buộc ở pydantic, lỗi thiếu là `required` của bước parse và các lỗi ngữ nghĩa chỉ chạy khi parse qua.
    - (3) Hàm parse điền `max_length` 255 cho bốn kiểu chữ và `scale` 0 cho số `exact` và tiền; CHECK đòi đúng cặp đó
      (`ck_field_defs_max_length_type`, `ck_field_defs_scale_type`), nên ghi tường minh mặc định không là khác biệt và mọi
      tài liệu `seal` nhận không vỡ CHECK sau phê duyệt. Nếu sai thì: cột NULL nghĩa là mặc định, CHECK nới về "chỉ cho kiểu
      đó".
    - (4) "UPDATE trừ cột khóa" đọc là chỉ các cột móc ghi (`studio.object_defs`: nhãn, mô tả, truy cập mặc định, phiên bản
      đã áp, `schema_version`, `next_field_no`, `updated_*`; `studio.field_defs`: bảy thuộc tính đổi được; lựa chọn: nhãn,
      vị trí, bật), vì kiểu, kho, slot, `field_no` và `api_name` bất biến (R2.4). Nếu sai thì: một revision cấp thêm cột khi
      W2 cần.
    - (5) `ObjectVersionRejected` là lớp con của `DocumentInvalidError`, nên đi qua handler 422 `validation_failed` sẵn có.
      Nếu sai thì: ticket 06 thêm handler riêng.
    - (6) `next_field_no` lấy theo từng trường bằng `UPDATE ... RETURNING` trong giao dịch của móc, dưới khóa đối tượng.
      Nếu sai thì: móc đếm trong bộ nhớ và ghi một lần ở cuối.
    - (7) Actor của audit là `AccessContext` của giao dịch, qua `ObjectDefinitionStore.context` (MEDIUM (i)); nhà máy
      `object_store_of` ở `dw_studio.records.adapters` nhận `SqlArtifactTx` và từ chối loại khác; `build_studio` truyền nó
      vào `platform_kinds(...)`. Nếu sai thì: `ArtifactTx` khai `context` và nhà máy đọc qua Protocol.
    - (8) `OBJECTS_MANAGE_SCOPE` là hằng module thường (không `Final`): phép quét `*_SCOPE` của
      `test_permission_catalogue.py` chỉ đọc phép gán thường. Nếu sai thì: phép quét đọc thêm `AnnAssign`.
    - (9) Phép so policy partition với bảng cha trong `test_rls_coverage.py` chỉ cho partition của schema `studio`: partition
      thời gian của `platform` cố ý chỉ có policy tenant (`ensure_time_partitions`), `dw_app` không có quyền nào trên chúng.
      Nếu sai thì: mở rộng phép so và đổi hàm tạo partition.
    - (10) Khóa bộ đệm của bộ chiếu là một hàm `cache_key`: đột biến bỏ tenant ở một trong hai chỗ dựng khóa cũ chỉ làm mất
      lần trúng, không làm lộ, nên test xanh; nay một chỗ, đột biến đỏ. Nếu sai thì: không có.
    - (11) `SqlObjectDefinitionReader` và `ObjectSchemaProjector` dựng và có test (reader dưới RLS, bộ chiếu với bản giả),
      chưa nối ở composition root: route describe và bộ chiếu theo người gọi là của ticket 03. Nếu sai thì: nối vào
      `StudioContainer` ngay.
- 2026-11-04 (agent): resolved. Commit `65bddef` (mã, revision `16357d3dbff8`), commit đóng ticket này (test, spec đột biến).
    - Khác ticket: mô hình `dw.object/v1` có kiểm từng thuộc tính theo kiểu (`number_mode`, `scale`, `currency_code`,
      `max_length`, lựa chọn chỉ cho danh sách chọn, khóa lựa chọn) để không tài liệu nào qua `seal` rồi vỡ CHECK; slot của
      kiểu `currency` và số `exact` ở họ `i`; `refuse_object_artifact_delete` không gửi DETAIL nên `in_use` là `{}`. Kết quả
      smoke của ticket 01 không có mục "không chạy được"; ba mục của nó chạy chính ở test ở đây (UNIQUE từng phần trên `u`,
      trigger `updated_at` trên bảng cha, policy theo partition). `fixture_kinds._remove_rows` xóa thêm `studio.records`,
      `studio.object_defs` của công ty thử.
    - Test: unit `test_object_rules.py` (R1.6, R1.8 thuộc tính trên 600 cặp sinh ngẫu nhiên, R2.1-R2.6, `definition_of`,
      khóa), `test_schema_projector.py` (CO25, CO1 hai công ty cùng `object_id` trên bộ đệm đầy); integration
      `test_object_definitions.py` (catalog R2.1, R2.2, R9.4, R9.5; R4.1; R4.2 với vai thử NOBYPASSRLS và policy PERMISSIVE
      thử; R4.6 bảy khóa ghép; CO2; móc R1.1 20 trường, phiên bản sau, lũy đẳng; R1.4; R1.5 hai giao dịch và khóa chia sẻ;
      CO4 UNIQUE riêng; R2.4, R2.5 qua móc; `seal` R1.6, R2.1, R2.2, R2.6; xóa mềm; R4.4 qua lane thật);
      `apps/api/.../test_studio_objects.py` (R1.3 403/404/201, registry so `studio.artifact_kinds`); `test_rls_coverage.py`
      (ba bảng toàn tenant, CO21, partition so bảng cha), `test_privileges.py`, `test_offboarding_coverage.py` (thu DELETE).
    - `mutations/02.yaml` 27 đột biến, chưa chạy bằng `mutate.py`; cả 27 chạy tay khi viết test (mọi bộ mới xanh lần đầu),
      mỗi cái đỏ ở ca của nó.
    - `reviewing-feature-security` (đọc): ranh giới 1, 2, 4, 5, 6 áp dụng, có ca âm; 3 không (không công cụ, không lượt chạy).
    - MEDIUM để lại: (k) `order_purge_steps` không mang cạnh CASCADE của bảng có bước riêng: `studio.object_defs` CASCADE
      sang `studio.field_defs`, mà `studio.dependencies` RESTRICT tới nó; hôm nay thứ tự đúng nhờ cạnh
      `dependencies → field_defs` cộng thứ tự tên (`dependencies` < `object_defs`), đổi tên bảng có thể làm lượt xóa vấp FK
      giữa chừng; chủ là foundations-hardening. (l) Bốn bảng không có trigger `refuse_delete_outside_offboarding` như vỏ:
      `dw_app` xóa được định nghĩa ngoài offboarding; W1 không gì xóa, xóa đối tượng là W2. (m) Kiểu trường ngoài mười kiểu
      trả mã chung `value_not_allowed`, chưa có mã riêng. MEDIUM (a)-(j) của gate giữ nguyên chủ.
    - Owed lúc đóng hàng đợi: `mutate.py` cho `mutations/02.yaml`; `make test-integration` toàn bộ; P50/P95/P99 của
      `POST /api/v1/studio/artifacts` và `PUT .../draft` loại `object` và của `seal` với `validate_object` (không route mới);
      `/code-review` trên diff.
