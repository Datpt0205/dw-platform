# 02 — Kho bí mật: KmsPort, LocalDevKms, secret_envelopes và cửa một chiều

Status: resolved
Blocked by: .claude/plans/studio/foundations-hardening/issues/03-quyen-dw-app-va-rls-initplan.md, .claude/plans/studio/org-and-principals/issues/01-khoa-don-vi-va-siet-realm.md, .claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md, .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R1.6, R1.7, R1.8, R1.9, R1.10, R1.14, R2.2, CV1, CV2, CV3, CV4, CV5, CV23, CV24

## Mục tiêu

Mọi Thông tin bí mật của công ty nằm trong một phong bì AES-256-GCM dưới Khóa của công ty, chỉ bộ môi
giới bí mật mở được, và một cửa cơ sở dữ liệu một chiều chặn `dw_app` đọc thẳng (spec R1, R2.2). Phần này
không chờ spike 21 (ADR-0115 (Accepted)); OpenBao Transit, mở niêm phong, xoay khóa, hủy khóa và sao lưu
kho khóa ở ticket 06 (DO-47.1). Xoay một bí mật thay phiên bản cũ trong cùng giao dịch (bí mật ký sau 24 giờ chồng
lấn), cửa mở bí mật mở phiên bản mới nhất chưa thu hồi vì không lượt nào ghim phiên bản, và không mở phiên bản đã thu
hồi hay thiếu (spec R1.9, R1.10, R1.14; V4.20; V4.35). Gộp từ B8a-connections connections-and-vault 03 và 04.

## Việc cần làm

1. Một migration (revision hex ngẫu nhiên của alembic): `platform.secret_envelopes` và
   `platform.connections` theo mục Dữ liệu của spec:
    - `secret_envelopes`: `id` uuid, `tenant_id` NOT NULL FK `platform.tenants` ON DELETE CASCADE,
      `connection_id` uuid NULL với FK ghép `(tenant_id, connection_id)` tới `platform.connections (tenant_id, id)`
      ON DELETE CASCADE (phong bì là dòng con của chủ thể; R1.8), `field text NOT NULL`,
      `secret_version integer NOT NULL`, `alg text NOT NULL` CHECK (`aes-256-gcm`), `nonce bytea NOT NULL` CHECK
      độ dài 12, `kek_ref text NOT NULL`, `ciphertext bytea NOT NULL` CHECK độ dài ≤ 64 KiB,
      `wrapped_data_key bytea NOT NULL` (khóa dữ liệu bọc bởi Khóa của công ty, giữ cạnh `ciphertext`),
      `kek_version int NOT NULL`, `revoked_at timestamptz NULL` (thời điểm từ đó phiên bản bị từ chối, NULL ở phiên
      bản đang dùng, không vào AAD; V4.20), `replaced_at timestamptz NULL` (thời điểm của lần xoay đã thay phiên bản,
      chỉ `platform.put_secret` ghi, không vào AAD; H-10), `created_at`, `updated_at timestamptz NOT NULL`, không cột
      `aad_hint`;
      UNIQUE `(tenant_id, connection_id, field, secret_version)`, dạng của UNIQUE
      `(tenant_id, subject_kind, subject_id, field, secret_version)` cho cột chủ thể `connection_id`, dẫn đầu bằng
      hai cột của FK ghép nên cũng là chỉ mục của FK đó và của FK `tenant_id`; loại trừ chủ thể qua CHECK
      `num_nonnulls(connection_id) = 1`, mà mỗi chủ thể mới nới rộng bằng một cột NULL có FK ghép
      `(tenant_id, <cột chủ thể>)` tới UNIQUE `(tenant_id, id)` của bảng chủ thể ON DELETE CASCADE, cùng UNIQUE
      của cột đó, trong migration của ticket thêm nó (`inbound_endpoint_id` ở workflow-triggers/02,
      ADR-0115 (Accepted) quyết 1);
    - `connections`: toàn cột của spec trừ `compromised_at`, `name`, `disabled_at` và index `uq_connections_account_live`,
      mà ticket 04 thêm cùng bên đọc của chúng (bao gồm `share_scope` CHECK, `status` CHECK không DEFAULT,
      `owning_workspace_id` NOT NULL với FK ghép `(tenant_id, owning_workspace_id)` tới `platform.workspaces`
      ON DELETE RESTRICT trên `uq_workspaces_tenant_id_id` của org-and-principals/01, index danh sách), UNIQUE
      `(tenant_id, id)` (`uq_connections_tenant_id_id`) làm đích của FK ghép từ `secret_envelopes`, tạo trước FK
      đó trong cùng revision; trigger `platform.guard_connection_owning_workspace()` từ chối mọi UPDATE đổi
      `owning_workspace_id` (R1.7), vì AAD của bước 3 gắn cột đó; trigger `guard_connection_status` và
      `connection_usable` để ở ticket 04.
2. RLS ENABLE và FORCE, policy tenant theo dạng `test_rls_coverage.py` đòi lúc merge trên cả hai bảng;
   `REVOKE ALL ON platform.secret_envelopes FROM dw_app`; hàm SECURITY DEFINER `platform.put_secret`,
   `platform.open_secret`, `platform.secret_status`, `platform.delete_secret` lấy công ty từ
   `app.tenant_id` (không nhận tham số công ty), mỗi hàm `SET search_path = pg_catalog, platform`, rồi
   `REVOKE ALL ON FUNCTION ... FROM PUBLIC` và EXECUTE chỉ cho `dw_app` (như
   `db/migrations/versions/349080a62e41_tenant_members.py:162`, `:179`), vì một hàm mới mặc định cho PUBLIC
   EXECUTE, nên `dw_provisioner` và mọi vai có USAGE trên schema `platform` gọi được cửa nếu thiếu câu REVOKE (CV2); `platform.put_secret` ghi giá trị mới
   của (chủ thể, trường) thành một dòng mới, không sửa bản mã của dòng cũ, với `secret_version` là số kế tiếp mà
   `SecretStore` đã đưa vào AAD trước khi mã hóa (bước 3), nên hai lần ghi đồng thời cùng số thì UNIQUE từ chối
   lần sau, và trong cùng giao dịch, bằng một câu UPDATE, ghi cho mọi dòng cũ có `revoked_at` NULL của cùng (chủ thể,
   trường) `replaced_at = now()` và `revoked_at` bằng `now()`, hay `now() + interval '24 hours'` khi
   `field = 'signing_secret'` (khoảng chồng của lần xoay, như bí mật ký của workflow-triggers/02), một quy tắc trong hàm
   cho mọi chủ thể, nên ticket thêm chủ thể không sửa nó (spec R1.9; V4.20; V4.35);
   `platform.open_secret(subject, field, secret_version)` với `secret_version` NULL mở phiên bản có `secret_version`
   lớn nhất của (chủ thể, trường) mà `revoked_at` NULL hay ở tương lai, và với `secret_version` nêu (bộ kiểm chữ ký
   của workflow-triggers/02 trong khoảng chồng 24 giờ) mở đúng phiên bản đó; trả số phiên bản đã mở cùng bản mã; không
   trả dòng nào khi phiên bản được chọn có `revoked_at <= now()` hay không còn phiên bản chưa thu hồi nào, như khi không
   còn dòng, nên `SecretStore` trả `credential_revoked` khi không có dòng (spec R1.10, R1.14; đóng khi thiếu); không lượt
   chạy nào ghim phiên bản (ADR-0109 (Accepted) quyết 6; V4.35);
   `platform.secret_status` trả `secret_version`, `revoked_at` và `replaced_at` của từng phiên bản còn dòng của (chủ
   thể, trường), không trả giá trị; trên `platform.connections`, `dw_app` giữ SELECT, INSERT và DELETE ở mức bảng,
   vì catalog của offboarding hỏi `has_table_privilege` SELECT và DELETE
   (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:81-119`), nên SELECT theo cột
   làm lane bỏ qua bảng, và UPDATE chỉ theo cột: `REVOKE UPDATE` rồi
   `GRANT UPDATE (share_scope, external_account, status, scopes, last_used_at, updated_at)`, không UPDATE trên `id`,
   `tenant_id`, `owning_workspace_id`, `connector_key`, `connector_major`, `created_by`, `created_at`, nên cột ticket
   sau thêm (`compromised_at` của ticket 04) không có UPDATE của `dw_app` khi không migration nào cấp (spec Dữ liệu);
   DELETE để route xóa của ticket 04 và lane `offboarding` xóa Kết nối như bảng thường và FK CASCADE xóa phong bì
   của nó (bước 6).
3. `KmsPort`, `LocalDevKms` (HKDF-SHA256 từ `DW_LOCAL_KMS_MASTER_KEY`, AES key wrap); `SecretStore`
   (AES-256-GCM) với AAD
   `dw.secret.v1|<tenant_id>|<owning_workspace_id>|<subject_kind>:<subject_id>|<field>|<secret_version>` theo
   ADR-0115 (Accepted) quyết 1: công ty lấy từ `app.tenant_id` của ngữ cảnh, không từ dòng; workspace sở hữu
   của chủ thể; `<subject_kind>` là tên cột chủ thể bỏ `_id` (`connection`, và `inbound_endpoint` từ
   workflow-triggers/02) với id trong cột đó; `<field>` và `<secret_version>` là cột `field`, `secret_version`
   của dòng, tức tên trường bí mật bên gọi nêu và phiên bản của bí mật. `kek_version` không vào AAD: bọc lại
   khóa dữ liệu (`KmsPort.rewrap`, lane `credential_rewrap` của ticket 06) chỉ đổi `wrapped_data_key` và
   `kek_version`, nên AAD không đổi và phong bì vẫn giải mã. Kiểu `Secret` (`repr` ẩn, `reveal()` chỉ ở module
   cho phép, có test kiến trúc).
4. `DW_KMS_PROVIDER=none|local`, mặc định `none` (giá trị `openbao` thêm ở ticket 06, cùng thay đổi với bên đọc
   của nó); `none` dựng một `KmsPort` từ chối mọi lời gọi với `kms_unavailable` (spec R2.4), không rơi về
   `LocalDevKms` hay giá trị rõ; `local` cần `DW_LOCAL_KMS_MASTER_KEY` (base64 của ít nhất 32 byte), thiếu hay ngắn
   hơn → `RuntimeError` lúc khởi động ở mọi profile; `validate_for_profile` của api và worker từ chối `local` khi
   `settings.is_deployed`; composition root của api và worker dựng `KmsPort` và `SecretStore` lúc khởi động, nên cấu
   hình sai hỏng ngay, và ticket 04 là bên dùng đầu tiên. Khóa chủ của `LocalDevKms` sinh tại máy dev
   (`.env.example` để trống kèm lệnh sinh, fixture test một hằng), không phải bí mật của Đạt.
5. `kek_ref` là `tenant-<tenant_uuid>` (ADR-0115 (Accepted) quyết 1), suy từ công ty của ngữ cảnh; `SecretStore` so
   `kek_ref` của dòng `open_secret` trả với giá trị đó trước khi gọi `KmsPort`; lệch → lỗi `secret_key_mismatch`,
   không giải mã, và audit `secret.key_mismatch` ghi qua `ScopedAuditPort` (`SqlScopedAudit`,
   `packages/python/dw_platform/src/dw_platform/adapters/persistence/digital_workers_repo.py:548`) trong giao dịch
   riêng trước khi ném lỗi, nên dòng còn khi giao dịch của bên gọi lùi; đứng tên tác nhân của ngữ cảnh gọi (người,
   hay `system_actor(<lane>)` khi một lane gọi, ADR-0011 (Accepted)), ở công ty của ngữ cảnh và workspace sở hữu của
   chủ thể, `details` chỉ `subject_kind`, `subject_id`, `field`, `secret_version`, không giá trị và không `kek_ref`
   của dòng, vì nó mang id của công ty khác.
6. Assert ở `test_privileges.py`; `test_rls_coverage.py` tự thấy hai bảng; thêm hai dòng có lý do vào
   `_TENANT_WIDE_ON_PURPOSE` (danh sách của studio-skeleton/01, studio-skeleton:R9.1) (`secret_envelopes`: dòng con mà chủ thể mang workspace; `connections`: tầm dùng
   vượt workspace theo thiết kế); catalog export của offboarding (`_CATALOG_EXPORTABLE`) không liệt kê
   `secret_envelopes`; vì bảng được tạo sau khi studio-skeleton/01 đo `_PLATFORM_PREDATING`, và lane `offboarding`
   không xuất và không xóa thẳng nó, test phủ offboarding (studio-skeleton:R4.3) đòi hai dòng
   (`packages/python/dw_platform/tests/integration/test_offboarding_coverage.py`, `offboarding_violations`): một dòng
   `EXPORT_EXCLUSIONS["platform.secret_envelopes"]` với lý do "bí mật không rời Kho bí mật qua đường ra nào, gói xuất
   cũng vậy (R1.2, R1.6); `dw_app` không SELECT", và một dòng `STUDIO_EXCLUSIONS["platform.secret_envelopes"]` là
   `OffboardingExclusion(reason="REVOKE ALL với dw_app; xóa theo FK CASCADE khi lane xóa platform.connections",
cascade_from="platform.connections")`, đúng một cách xóa như `OffboardingExclusion` đòi (`offboarding.py:163-189`);
   workflow-triggers/02 sửa lý do khi thêm chủ thể `studio.inbound_endpoints`, và `platform.delete_secret` không phải
   bước của lane.

## Tiêu chí chấp nhận

- [x] R1.1: ghi một bí mật rồi `open_secret` trả đúng giá trị; phong bì trong database không chứa giá
      trị rõ; ghi giá trị mới cho cùng (chủ thể, trường) → một dòng mới với `secret_version` kế tiếp, bản mã của dòng
      cũ không đổi (phiên bản cũ ở R1.10, phiên bản mới ở R1.14); chèn trùng
      (chủ thể, `field`, `secret_version`) → UNIQUE từ chối; `platform.put_secret` với `nonce` hay `ciphertext`
      NULL → lỗi NOT NULL (23502), không dòng nào; gỡ NOT NULL của hai cột trong migration thử → phong bì thiếu bản
      mã được ghi, test đỏ.
- [x] R1.2 (CV4): lớp Kho bí mật: một giá trị canary ghi qua `SecretStore` rồi mở → canary không có trong `repr`,
      `str`, `format`, JSON hay `model_dump` của `Secret`, trong log bắt được của lần ghi và lần mở, trong thông điệp
      lỗi `credential_revoked`, `kms_unavailable`, `secret_key_mismatch` và trong dòng audit `secret.key_mismatch`;
      `reveal()` gọi từ một module ngoài danh sách cho phép → test kiến trúc đỏ; cho `__repr__` trả giá trị → test
      đỏ. Ca mock nhà cung cấp vọng header và key (checkpoint, `platform.tool_executions`, span) chạy ở ticket 05, lời
      gọi ra ngoài đầu tiên qua một Kết nối.
- [x] R1.3 (CV2): `SELECT * FROM platform.secret_envelopes` bằng `dw_app` → `permission denied`; khẳng
      định catalog trong `test_privileges.py`; `has_function_privilege` trên bốn hàm đúng với `dw_app`, sai với
      `dw_provisioner` và `dw_agent_ro`, `proacl` không cấp PUBLIC, mỗi hàm `prosecdef` với `search_path` ghim;
      `dw_provisioner` (có USAGE trên `platform`) gọi `platform.put_secret` → `permission denied for function`;
      `dw_app` giữ SELECT, INSERT, DELETE trên `platform.connections` ở mức bảng, UPDATE ở đúng các cột của bước 2 và
      không UPDATE ở `owning_workspace_id`, `tenant_id`; gỡ `REVOKE ... FROM PUBLIC` trong migration thử →
      `dw_provisioner` ghi được phong bì, test đỏ.
- [x] R1.4 (CV1): chép một phong bì sang `connection_id` khác (cùng công ty và công ty khác), sang trường khác
      của cùng kết nối, hay sang dòng có `secret_version` khác rồi giải mã → lỗi; bọc lại khóa dữ liệu qua
      `KmsPort.rewrap` của `LocalDevKms` (`kek_version` tăng) → vẫn giải mã; gỡ AAD khỏi `SecretStore`, hay đưa
      `kek_version` vào AAD → test đỏ. Ca chủ thể `inbound_endpoint_id` chạy ở workflow-triggers/02, nơi thêm cột
      đó.
- [x] R1.5 (CV3): đặt công ty A, `open_secret` với chủ thể của công ty B → không dòng; một dòng mang
      `kek_ref` của công ty khác → từ chối với `secret_key_mismatch`, `KmsPort` không được gọi, audit
      `secret.key_mismatch` đứng tên tác nhân của ngữ cảnh, còn sau khi giao dịch của bên gọi lùi, `details` không chứa
      `kek_ref` của dòng; gỡ phép so `kek_ref` → giải mã được gọi, test đỏ; chưa đặt `app.tenant_id` → không
      dòng.
- [x] R1.6 (CV2): truy vấn catalog export của offboarding (`_CATALOG_EXPORTABLE`) không liệt kê
      `secret_envelopes` (integration); test phủ offboarding (studio-skeleton:R4.3) xanh với dòng `EXPORT_EXCLUSIONS` và
      dòng `STUDIO_EXCLUSIONS` của `platform.secret_envelopes`, bỏ một trong hai → test phủ đỏ và nêu tên bảng;
      `platform.connections` có trong `_CATALOG_PURGEABLE`; offboarding một công ty có Kết nối →
      mọi phong bì của công ty đó bị xóa theo CASCADE khi lane xóa `platform.connections`, phong bì của công ty khác
      còn nguyên.
- [x] R1.7 (CV1): `UPDATE platform.connections SET owning_workspace_id = <workspace khác cùng công ty>` → trigger
      từ chối, dòng không đổi, phong bì của Kết nối vẫn giải mã; UPDATE cột khác của cùng dòng → nhận; gỡ trigger
      `platform.guard_connection_owning_workspace()` → UPDATE thành công và phong bì giải mã lỗi, test đỏ.
- [x] R1.8 (CV23): đặt `app.tenant_id` của công ty A, `platform.put_secret` với `connection_id` của công ty B → lỗi
      khóa ngoại (23503), không dòng nào; xóa một Kết nối → mọi phong bì của nó xóa theo; đổi FK ghép thành FK một
      cột `connection_id` trong migration thử → lần ghi chéo công ty thành công, test đỏ.
- [x] R1.9 (CV24): lưu giá trị mới cho `api_key` của một Kết nối → dòng cũ có `revoked_at` và `replaced_at` bằng
      `now()` của giao dịch ghi, dòng mới có cả hai NULL; lưu giá trị mới cho trường `signing_secret` → dòng cũ có
      `replaced_at` bằng `now()` và `revoked_at` bằng `now()` cộng 24 giờ; giao dịch ghi lùi → dòng cũ vẫn `revoked_at` NULL và không dòng mới nào; trường `password`
      của cùng Kết nối và Kết nối khác không đổi; xoay `signing_secret` lần nữa trước khi 24 giờ của lần đầu hết →
      phiên bản 1 giữ `revoked_at` và `replaced_at` của lần đầu, phiên bản 2 nhận `now()` cộng 24 giờ; gỡ bước ghi
      `revoked_at` khỏi `platform.put_secret` → phiên bản cũ vẫn mở được bằng số của nó, bỏ điều kiện `revoked_at` NULL
      khỏi câu ghi → phiên bản 1 bị dời hạn, hay gỡ vế `replaced_at` → dòng cũ có `replaced_at` NULL, test đỏ.
- [x] R1.10 (CV24): `open_secret` với phiên bản đã thu hồi của ca R1.9 → không dòng, `SecretStore` trả
      `credential_revoked`, không giá trị rõ; với một `secret_version` chưa từng có → `credential_revoked`; mọi phiên
      bản của một trường đã thu hồi hay đã xóa, `open_secret` không nêu phiên bản → `credential_revoked`; phiên bản
      cũ của `signing_secret` ở ca R1.9 (`revoked_at` ở tương lai) → mở được tới thời điểm đó và `credential_revoked`
      sau đó; `platform.secret_status` trả `revoked_at` và `replaced_at` của cả hai phiên bản, không giá trị; gỡ kiểm
      `revoked_at` khỏi `platform.open_secret` → phiên bản đã thu hồi mở được, test đỏ.
- [x] R1.14 (CV24): ba phiên bản của `password` một Kết nối, phiên bản 3 vừa lưu → `open_secret` không nêu phiên bản
      trả giá trị của phiên bản 3 cùng số 3; đặt `revoked_at` của phiên bản 3 về quá khứ bằng vai migrator trong test
      (thu hồi vì lộ của ticket 04 chưa có) → `credential_revoked`, không lùi về phiên bản 2 đã bị thay; cho hàm chọn
      `secret_version` nhỏ nhất, hay bỏ điều kiện `revoked_at` khỏi phép chọn → giá trị của phiên bản 1 hay của phiên
      bản 3 đã thu hồi được trả, test đỏ.
- [x] R2.2 (CV5): `DW_KMS_PROVIDER=local` với profile `uat` → `RuntimeError` lúc khởi động, ở api và ở worker; gỡ
      `validate_for_profile` → test đỏ; không đặt `DW_KMS_PROVIDER` → `none`, và `put` hay `open` qua `SecretStore` →
      `kms_unavailable`, không dòng nào được ghi; `local` với `DW_LOCAL_KMS_MASTER_KEY` trống hay dưới 32 byte →
      `RuntimeError` lúc khởi động ở profile `local`; cho `none` rơi về `LocalDevKms` → test đỏ.
- [x] Xong: các cổng nhanh của ticket xanh (wave-close.md); `make test-integration` đầy đủ, mutate.py và đo trễ ở
      lúc đóng hàng đợi.

## Nguồn

- `apps/api/src/dw_api/settings.py:323-325`; spec: R2.2.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:108-114`; spec: R1.6.
- `packages/python/dw_platform/tests/integration/test_rls_coverage.py:108`; spec: Dữ liệu
  (`_TENANT_WIDE_ON_PURPOSE` theo mẫu `_PRINCIPAL_ONLY_ON_PURPOSE`, DO-01).
- spec: R1, R2.2, CV1-CV5, CV23, CV24; ADR-0115 (Accepted) quyết 1; ADR-0109 (Accepted) quyết 6 (bản kê không ghim
  phiên bản bí mật); si-platform `db/si` không có bảng này (tự dẫn).
- spec: R1.6, Dữ liệu (dòng `STUDIO_EXCLUSIONS` của `platform.secret_envelopes`); studio-skeleton:R4.3.

## Comments

- 2026-10-23 (agent): `needs-info` vì DO-47 (vận hành OpenBao: unseal, kho lưu, xoay khóa) chờ Đạt; phần
  `KmsPort`, `LocalDevKms`, `secret_envelopes` và cửa một chiều không chờ. D14 (DO-24) đã chốt resize host
  trước khi OpenBao ship.
- 2026-10-23 (agent): Đạt chốt DO-47.1 (a) và DO-47.2 (a) ngày 23/10/2026, nên ticket về `needs-triage`.
  Theo DO-47.1, phần OpenBao (R2.1, R2.3, R2.4, R2.5-R2.8, CV6, CV20, compose `openbao`, lane
  `credential_rewrap`, hủy khóa ở offboarding, sao lưu và diễn tập) tách sang ticket 06, vì ADR-0115 (Accepted) được
  chấp nhận với điều kiện OpenBao chỉ ship sau spike 21; studio-skeleton/04 chuyển sang Blocked by của
  ticket 06. Thêm org-and-principals/01: FK ghép `(tenant_id, owning_workspace_id)` cần
  `uq_workspaces_tenant_id_id`, mà org-and-principals/01 là chủ duy nhất (DO-01); thêm studio-skeleton/01 vì
  hai bảng ghi dòng vào danh sách bảng toàn tenant mà ticket đó dựng.
- 2026-10-24 (agent): theo quyết định Đạt ngày 24/10/2026 (ADR-0115 (Accepted) quyết 1): CHECK
  `num_nonnulls` của bước 1 là chỗ mỗi chủ thể mới nới rộng; cột `inbound_endpoint_id` và CHECK nới rộng thuộc
  migration của workflow-triggers/02, ticket đó chờ ticket này.
- 2026-10-24 (agent): theo kiểm nhất quán vòng 3 (vòng sửa thứ tư): AAD của bước 3 gắn công ty, workspace sở
  hữu, chủ thể, trường và phiên bản như ADR-0115 (Accepted) quyết 1, và CV1 thêm ca chép sang trường khác, phiên
  bản khác (R1.4); thêm Blocked by foundations-hardening/07, vì ticket đó viết lại `_CATALOG_COLUMNS` và
  `export_rows` của `offboarding.py`, mà bước 6 cùng sửa (catalog xuất không liệt kê `secret_envelopes`).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt b: vế phiên bản của AAD là `secret_version` của bí mật thay
  `kek_version`, vì lane `credential_rewrap` (ticket 06 bước 4) chỉ bọc lại khóa dữ liệu và tăng `kek_version`,
  nên AAD mang `kek_version` làm hỏng mọi phong bì sau lần bọc lại đầu tiên (ADR-0115 (Accepted) quyết 1, phiên
  bản của bí mật); bước 1 thêm `field`, `secret_version` và UNIQUE theo chủ thể, trường, phiên bản, thêm
  `wrapped_data_key`, khóa dữ liệu đã bọc mà ADR-0115 (Accepted) quyết 1 giữ cạnh `ciphertext` và lane bọc lại
  ghi lại, bỏ `aad_hint` không bên đọc; bước 2 nêu `secret_version` của `platform.put_secret`, số mà
  `SecretStore` đã đưa vào AAD trước khi mã hóa, của `platform.open_secret`, phiên bản bản kê ghim, và của
  `platform.secret_status`, mà `connection_usable` của ticket 04 đọc; R1.1 thêm ca mở phiên bản cũ, R1.4 thêm
  ca bọc lại vẫn giải mã (bước 3, CV1).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt c: `connection_id` có FK ghép `(tenant_id, connection_id)` tới
  `platform.connections (tenant_id, id)` ON DELETE CASCADE, chỉ mục là UNIQUE theo chủ thể, trường, phiên bản, và
  `platform.connections` thêm UNIQUE `(tenant_id, id)` làm đích (CLAUDE.md, Data model rules); mọi cột chủ thể thêm
  sau dùng cùng FK ghép, vì kiểm khóa ngoại không qua RLS (R1.8, CV23); `owning_workspace_id` của Kết nối không đổi
  sau khi tạo, vì AAD của bước 3 gắn nó (trigger `platform.guard_connection_owning_workspace()`, R1.7, CV1;
  ADR-0115 (Accepted) quyết 1) (bước 1).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt d: `nonce` và `ciphertext` NOT NULL, vì CHECK độ dài nhận NULL
  (failure-modes #7), và bước 1 chép nguyên văn ràng buộc của mục Dữ liệu cho `tenant_id`, `alg`, `kek_ref`,
  `kek_version` và hai cột thời gian (failure-modes #2); UNIQUE theo chủ thể, trường, phiên bản cũng là chỉ mục của
  FK `tenant_id` (CLAUDE.md, Data model rules); R1.1 thêm ca phong bì thiếu `nonce` hay `ciphertext` (bước 1).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt f: theo V4.20 (Đạt), bước 1 thêm `revoked_at timestamptz NULL`;
  `platform.put_secret` ghi `revoked_at` cho phiên bản cũ trong giao dịch ghi phiên bản mới, ngay, hay sau 24 giờ khi
  trường là `signing_secret`, `platform.open_secret` không mở phiên bản đã thu hồi hay thiếu (`credential_revoked`), và
  `platform.secret_status` trả `revoked_at` (bước 2; spec R1.9, R1.10, CV24), nên R1.1 thôi hứa mở được phiên bản
  cũ; bước 6 thêm dòng `STUDIO_EXCLUSIONS` của `platform.secret_envelopes` với lý do xóa theo FK CASCADE từ chủ
  thể, vì bảng có sau lần đo `_PLATFORM_PREDATING` của studio-skeleton/01 (studio-skeleton:R4.3), và bước 2 cấp
  DELETE trên `platform.connections` cho `dw_app`, đường xóa mà lý do đó dựa vào (R1.6, CV2).
- 2026-10-24 (agent): kiểm lượt f của vòng 4: spec R1.9 và mục Dữ liệu nói như bước 2, chỉ dòng có `revoked_at` NULL
  được ghi `revoked_at`, vì "chưa thu hồi" của spec R1.12 gồm cả hạn ở tương lai, nên một lần xoay thứ hai trong 24
  giờ đã dời hạn của bí mật ký cũ nhất quá 24 giờ sau lần xoay của nó (V4.20); tiêu chí R1.9 và CV24 thêm ca xoay hai
  lần và ca bỏ điều kiện đó.
- 2026-10-25 (agent): lượt h, theo V4.35 của Đạt và H-10: bản kê lượt chạy thôi ghim `secret_version`, nên bước 2
  cho `platform.open_secret` mở phiên bản lớn nhất chưa thu hồi khi bên gọi không nêu phiên bản và trả số đã mở (spec
  R1.14), bộ kiểm chữ ký vẫn nêu phiên bản trong khoảng chồng 24 giờ; bước 1 thêm `replaced_at`, mà
  `platform.put_secret` ghi cùng `revoked_at`, để lane `credential_purge` của ticket 05 xóa phiên bản bị thay 24 giờ sau
  lần xoay và phiên bản bị thu hồi vì lộ ngay; R1.1 thôi nói `open_secret` với phiên bản mới, R1.9, R1.10 thêm
  `replaced_at` và ca không còn phiên bản chưa thu hồi, thêm R1.14. Thu hồi vì lộ (`compromised_at`,
  `platform.revoke_connection_secrets`) ở ticket 04. Không đổi cạnh.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` ở `f95a89f`, kiểm người dựng và đi
  ranh giới trong một lượt (ticket thêm migration, không route), trong ngữ cảnh của agent gate, không subagent.
  `check_plans`: 24 Đạt, 0 cảnh báo. Mọi Blocked by đã `resolved`. CRITICAL 1: bốn hàm SECURITY DEFINER không nói
  `REVOKE ... FROM PUBLIC` hay `search_path`, mà một hàm mới mặc định cho PUBLIC EXECUTE, nên mọi vai có USAGE trên
  `platform` (`dw_provisioner`) ghi, mở hay xóa được phong bì, không kiểm soát và không test âm; sửa: bước 2 theo tiền
  lệ `349080a62e41_tenant_members.py:162`, `:179`, R1.3 thêm phép kiểm catalog và lời gọi của `dw_provisioner` (không
  phải `dw_agent_ro`, vai không có USAGE trên `platform`, nên đột biến sẽ không đỏ), spec Dữ liệu và CV2. Nếu sai thì:
  không có cách sai an toàn hơn; chỉ có thể đổi vai dùng cho test.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 1: bước 6 chỉ nêu `STUDIO_EXCLUSIONS` với lý do nêu hai cách xóa
  và một bảng chưa có, trong khi `OffboardingExclusion` đòi đúng một cách (`offboarding.py:163-189`) và test phủ đòi
  thêm một dòng `EXPORT_EXCLUSIONS` cho bảng không xuất (`test_offboarding_coverage.py`, `offboarding_violations`,
  R4.3); sửa: bước 6, R1.6, spec Dữ liệu và CV2. Nếu sai thì: test phủ tự nêu dòng thiếu, sửa lý do theo nó.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 2: "grant cột cho `platform.connections`" không nói đặc quyền
  nào theo cột; SELECT theo cột làm `has_table_privilege` của catalog offboarding (`offboarding.py:81-119`) bỏ qua
  bảng, nên Kết nối và phong bì sống qua offboarding; sửa: SELECT, INSERT, DELETE ở mức bảng, UPDATE theo sáu cột
  nêu tên (bước 2, R1.3, R1.6). Nếu sai thì: ticket 04 cấp thêm cột cho PATCH trong migration của nó.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 3: tiêu chí R1.2 (CV4) đòi mock nhà cung cấp và checkpoint,
  `platform.tool_executions`, span, trong khi ticket không có lời gọi ra ngoài nào (mục 29: chỉ ticket khác làm nó
  đúng được); tách, không thu nhỏ: ticket này giữ lớp `Secret` và Kho bí mật, ca vọng bí mật đầu-cuối sang ticket 05
  (Yêu cầu thêm R1.2, CV4 và một tiêu chí). Nếu sai thì: ca đó về ticket 03 với máy chủ HTTP giả của nó.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 4: `DW_KMS_PROVIDER` không có mặc định, `none` không có hành vi
  và khóa chủ trống của `local` không bị từ chối, một mặc định có thể mở (failure-modes #7, như HIGH "bí mật kho trống
  dựng kho mở" của runtime-hardening/02); sửa: mặc định `none`, `none` từ chối mọi lời gọi với `kms_unavailable`, khóa
  chủ thiếu hay dưới 32 byte → `RuntimeError`, composition root dựng `KmsPort` lúc khởi động (bước 4, R2.2). Nếu sai
  thì: thiếu `DW_KMS_PROVIDER` → `RuntimeError` lúc khởi động thay vì `none`.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): HIGH 5: audit `secret.key_mismatch` không nói giao dịch, tác nhân,
  workspace hay `details`; ghi trong giao dịch của bên gọi thì mất khi lỗi làm nó lùi, và `kek_ref` của dòng mang id
  công ty khác vào audit của công ty này; sửa: `ScopedAuditPort` (`digital_workers_repo.py:548`) trong giao dịch riêng
  trước khi ném lỗi, tác nhân của ngữ cảnh hay `system_actor(<lane>)`, `details` không `kek_ref` (bước 5, R1.5). Nếu
  sai thì: audit ghi cùng giao dịch và bên gọi commit trước khi ném lỗi.
- 2026-11-02 (agent): lượt xác nhận chỉ đọc sáu bản sửa: cả sáu đóng; một chỗ của chính bản sửa CRITICAL đã sửa
  ngay (`dw_agent_ro` không có USAGE trên `platform`, nên đột biến gỡ REVOKE không đỏ được; đổi sang `dw_provisioner`
  và `has_function_privilege`); không CRITICAL hay HIGH mới.
- 2026-11-02 (agent): MEDIUM, chưa sửa, cho người dựng: (a) neo ở Nguồn đã trôi: `settings.py:323-325` nay là
  `is_deployed` ở `apps/api/src/dw_api/settings.py:350-353` và `validate_for_profile` ở `:366`, của worker
  `apps/worker/src/dw_worker/settings.py:337-344`; `offboarding.py:108-114` nay là `_CATALOG_EXPORTABLE` ở `:107`
  (`_CATALOG_COLUMNS` `:81-105`); `test_rls_coverage.py:108` nay là `_PRINCIPAL_ONLY_ON_PURPOSE` ở `:112`,
  `_TENANT_WIDE_ON_PURPOSE` ở `:604`; (b) trigger `touch_updated_at` của `secret_envelopes` không được nêu (CLAUDE.md,
  Data model rules), `put_secret` và lane bọc lại sửa dòng; (c) `field` không CHECK dạng, đề xuất
  `^[a-z][a-z0-9_]{0,62}$`, cũng giữ `|` khỏi AAD; (d) `open_secret` trả những cột nào (`alg`, `nonce`, `kek_ref`,
  `kek_version`, `wrapped_data_key`, `ciphertext`, `secret_version`) và `SecretStore` lấy `owning_workspace_id` từ
  `platform.connections` (dw_app SELECT được); (e) `KmsPort` của ticket này chỉ cần `generate_data_key`,
  `decrypt_data_key`, `rewrap` (ADR-0115 (Accepted) quyết 1 nêu năm; `ensure_tenant_key`, `destroy_tenant_key` cùng ticket 06);
  `LocalDevKms` dẫn KEK phiên bản v bằng HKDF với info `<kek_ref>|<v>`, phiên bản hiện hành là tham số dựng;
  (f) `cryptography` chỉ là phụ thuộc bắc cầu (`uv.lock`: 50.0.1), phải khai ghim trong `pyproject.toml` của gói
  chủ, `scripts/verify_architecture.py` `IMPORT_TO_DIST` thêm `cryptography`; (g) gói chủ của `KmsPort`, `SecretStore`
  và danh sách module được gọi `Secret.reveal()` (lúc đầu chỉ `SecretStore`, ticket 03, 05 thêm module của chúng)
  chưa nêu; (h) hai lần `put_secret` đồng thời: lần sau nhận 23505, `SecretStore` trả `ConflictError` và không tự thử
  lại (AAD mang số phiên bản); (i) `platform.delete_secret` xóa mọi phiên bản của (chủ thể, trường) hay một phiên bản,
  và chưa có bên gọi sản xuất ở W1 (ticket 04 chỉ dùng trong test); (j) `created_by` của `platform.connections` chưa
  nói FK và ON DELETE, và bảng không có cột tên mà màn của spec liệt kê (ticket 04, 07); (k) policy đặt tên
  `tenant_isolation_<bảng>`, vì catalog offboarding lọc theo tiền tố đó; theo tiền lệ, `REVOKE ALL ... FROM dw_agent_ro`
  trên hai bảng; (l) `Xong:` đọc theo `.claude/rules/wave-close.md`: cổng nhanh cộng integration của `dw_platform`,
  `apps/api`, `apps/worker`. LOW: partial unique `active` theo `external_account` NULL không chặn hai kết nối trùng.
- 2026-11-02 (agent): xây được trên máy này không cần bí mật thật của Đạt: `LocalDevKms` với khóa chủ sinh tại chỗ,
  PostgreSQL của compose; OpenBao, khóa triển khai và bí mật host thuộc ticket 06 (Chờ Đạt 20, 21 không chặn ticket này).
- 2026-11-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): gate của ticket 04 (spec Quyết định 3/11/2026, (s)): bước 1 ghi rõ
  `name`, `disabled_at` và `uq_connections_account_live` là của ticket 04, như `compromised_at`, để hai migration không
  tạo trùng; không đổi gì ticket này dựng, nên verdict ĐẠT của nó đứng.
- 2026-11-04 (agent): dựng xong (lane 1). Bước 1-6 như ticket; MEDIUM của gate đã theo: (b) `touch_updated_at` trên
  cả hai bảng; (c) CHECK `field ~ '^[a-z][a-z0-9_]{0,62}$'`, `SecretStore` giữ cùng dạng; (d) `open_secret` trả
  `secret_version, alg, nonce, kek_ref, kek_version, wrapped_data_key, ciphertext`, `SecretStore` đọc
  `owning_workspace_id` từ `platform.connections` dưới RLS của bên gọi; (e) `KmsPort` ba phương thức, `LocalDevKms`
  dẫn KEK bằng HKDF với info `dw.kms.local.v1|<kek_ref>|<v>`; (f) `cryptography==50.0.1` khai ở `dw_platform`,
  `IMPORT_TO_DIST` thêm nó; (g) `Secret` ở `dw_kernel.secret`, `KmsPort`/`SecretStore` ở
  `dw_platform.application.secrets`, danh sách gọi `reveal()` chỉ `secrets.py`
  (`dw_kernel/tests/unit/test_secret_reveal_scan.py`); (h) hai lần ghi cùng số → `ConflictError`
  `secret_version_taken`, không tự thử lại; (i) `platform.delete_secret` xóa mọi phiên bản của (chủ thể, trường),
  chưa bên gọi sản xuất; (j) `created_by` FK `platform.users` ON DELETE SET NULL; (k) policy
  `tenant_isolation_<bảng>`, `REVOKE ALL ... FROM dw_agent_ro` trên hai bảng. Thêm CHECK
  `ck_secret_envelopes_replaced_revoked` (`replaced_at` chỉ đi cùng `revoked_at`) và hàm nội bộ
  `platform.secret_subject_column(kind)`, đọc cột chủ thể từ catalog (FK ghép hai cột với `tenant_id`), nên chủ thể
  sau (workflow-triggers/02) không sửa bốn hàm cửa; hàm đó REVOKE khỏi PUBLIC, không vai nào gọi thẳng.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): UNIQUE theo chủ thể đặt tên
  `uq_secret_envelopes_tenant_id_connection_id_field_version`, không theo đủ quy ước: tên đủ dài 64 ký tự, Postgres
  cắt về 63 chỉ kèm NOTICE, nên adapter đổi vi phạm thành `ConflictError` theo tên không bao giờ khớp (test tích hợp
  `test_a_version_already_taken_is_refused_by_the_unique` tìm ra; failure-modes #4 thêm ca này). Chủ thể sau theo cùng
  dạng (`..._inbound_endpoint_id_field_version`: 63 ký tự). Nếu sai thì: đổi tên bằng một revision mới và sửa
  `_VERSION_TAKEN` của `secret_envelopes.py`.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): worker chưa dựng `KmsPort` và `SecretStore`: worker chưa có bên dùng
  nào (ticket 05 `credential_purge`, ticket 06 `credential_rewrap`), một đối tượng dựng mà không ai đọc là
  failure-modes #1; cấu hình sai vẫn hỏng lúc khởi động vì `main` gọi `validate_for_profile` trước mọi lane, và
  `check_kms_settings` giải mã khóa chủ ở đó. Api dựng cả hai trước cổng database (`wiring.py`), `ApiContainer.secret_store`
  cho ticket 04. Nếu sai thì: `build_kms(...)` ở đầu `build_registry` của worker.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): `.env.example` có `DW_KMS_PROVIDER=none` và
  `DW_LOCAL_KMS_MASTER_KEY=` kèm lệnh sinh; compose chưa chuyển hai biến cho api và worker, việc của ticket 04, bên
  dùng đầu tiên. Nếu sai thì: hai dòng `${DW_KMS_PROVIDER:-none}`, `${DW_LOCAL_KMS_MASTER_KEY:-}` ở
  `infra/compose/docker-compose.yml`, và `reviewing-deployment-security` cho chúng.
- 2026-11-04 (agent): khác ticket: R1.7 giữ hai lớp, mỗi lớp một test: `dw_app` không có UPDATE trên
  `owning_workspace_id` (permission denied trước trigger), trigger từ chối cả chủ bảng. `GRANT SELECT, INSERT, DELETE`
  trên `platform.connections` trùng với default privileges của `0001_platform_grants.sql`; kiểm soát thật là câu
  `REVOKE UPDATE`, nên đột biến R1.6 thu hồi DELETE. Chủ thể của công ty khác (không thấy dưới RLS) trả
  `credential_revoked` như khi thiếu, không lộ sự tồn tại. `test_restore_drill.py` theo `DW_TEST_DB_SUFFIX` (tên
  database của `pg_dump`/`pg_restore`), import bí danh `lane_db_name` vì pytest thu `test_db_name` như một test;
  `_violations_after` của `test_offboarding_coverage.py` gộp dòng thật với dòng thử, vì catalog đã cần dòng của
  `platform.secret_envelopes`.
- 2026-11-04 (agent): cổng của ticket: ruff, ruff format, mypy (633 tệp), lint-imports (11 hợp đồng),
  `verify_architecture.py`, `verify_invariants.py` sạch; unit `dw_kernel`, `dw_platform`, `dw_api`, `dw_worker` (1054
  xanh); tích hợp (`DW_TEST_DB_SUFFIX=_lane1`) `test_secret_vault.py` (21), `test_privileges.py`,
  `test_rls_coverage.py`, `test_offboarding_coverage.py`, `test_offboarding.py`, `test_restore_drill.py`: 137 xanh.
  Không route nào đổi, nên không sinh lại OpenAPI. `mutations/02.yaml` 23 đột biến, chạy lúc đóng hàng đợi; danh
  sách cho phép `reveal()` (quét nguồn) đã thử đỏ bằng tay tại chỗ ngày 4/11/2026. Lúc đóng hàng đợi không có thao tác
  API nào để đo trễ (ticket không thêm route).
- 2026-11-04 (agent): MEDIUM để lại: (a) `ApiContainer.secret_store` chưa ai đọc tới ticket 04 (ticket đòi dựng lúc
  khởi động); (b) `platform.delete_secret` chỉ hẹp theo công ty, ai được xóa trường nào là việc của route ticket 04;
  (c) `SecretKeyMismatchError` và `SecretUnreadableError` mang `ErrorCode.INTERNAL`, ticket 04 quyết response của
  chúng (problem+json 500, không chi tiết); (d) ca canary đầu-cuối của R1.2 (checkpoint, `tool_executions`, span) ở
  ticket 05 như gate đã tách.
