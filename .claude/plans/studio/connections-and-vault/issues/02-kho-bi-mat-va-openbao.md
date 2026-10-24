# 02 — Kho bí mật: KmsPort, LocalDevKms, secret_envelopes và cửa một chiều

Status: needs-triage
Blocked by: .claude/plans/studio/foundations-hardening/issues/03-quyen-dw-app-va-rls-initplan.md, .claude/plans/studio/org-and-principals/issues/01-khoa-don-vi-va-siet-realm.md, .claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md, .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R1.6, R1.7, R1.8, R2.2, CV1, CV2, CV3, CV4, CV5, CV23

## Mục tiêu

Mọi Thông tin bí mật của công ty nằm trong một phong bì AES-256-GCM dưới Khóa của công ty, chỉ bộ môi
giới bí mật mở được, và một cửa cơ sở dữ liệu một chiều chặn `dw_app` đọc thẳng (spec R1, R2.2). Phần này
không chờ spike 21 (ADR-0115 (Accepted)); OpenBao Transit, mở niêm phong, xoay khóa, hủy khóa và sao lưu
kho khóa ở ticket 06 (DO-47.1). Gộp từ B8a-connections connections-and-vault 03 và 04.

## Việc cần làm

1. Một migration (revision hex ngẫu nhiên của alembic): `platform.secret_envelopes` và
   `platform.connections` theo mục Dữ liệu của spec:
    - `secret_envelopes`: `id` uuid, `tenant_id` FK `platform.tenants` ON DELETE CASCADE,
      `connection_id` uuid NULL với FK ghép `(tenant_id, connection_id)` tới `platform.connections (tenant_id, id)`
      ON DELETE CASCADE (phong bì là dòng con của chủ thể; R1.8), `field text NOT NULL`,
      `secret_version integer NOT NULL`, `alg text` CHECK
      (`aes-256-gcm`), `nonce bytea` CHECK độ dài 12, `kek_ref text`, `ciphertext bytea` CHECK độ dài ≤ 64 KiB,
      `wrapped_data_key bytea NOT NULL` (khóa dữ liệu bọc bởi Khóa của công ty, giữ cạnh `ciphertext`),
      `kek_version int`, timestamps, không cột `aad_hint`; UNIQUE
      `(tenant_id, connection_id, field, secret_version)`, dạng của UNIQUE
      `(tenant_id, subject_kind, subject_id, field, secret_version)` cho cột chủ thể `connection_id`, dẫn đầu bằng
      hai cột của FK ghép nên cũng là chỉ mục của FK đó; loại trừ chủ thể qua CHECK
      `num_nonnulls(connection_id) = 1`, mà mỗi chủ thể mới nới rộng bằng một cột NULL có FK ghép
      `(tenant_id, <cột chủ thể>)` tới UNIQUE `(tenant_id, id)` của bảng chủ thể ON DELETE CASCADE, cùng UNIQUE
      của cột đó, trong migration của ticket thêm nó (`inbound_endpoint_id` ở workflow-triggers/02,
      ADR-0115 (Accepted) quyết 1);
    - `connections`: toàn cột của spec (bao gồm `share_scope` CHECK, `status` CHECK không DEFAULT,
      `owning_workspace_id` NOT NULL với FK ghép `(tenant_id, owning_workspace_id)` tới `platform.workspaces`
      ON DELETE RESTRICT trên `uq_workspaces_tenant_id_id` của org-and-principals/01, index danh sách), UNIQUE
      `(tenant_id, id)` (`uq_connections_tenant_id_id`) làm đích của FK ghép từ `secret_envelopes`, tạo trước FK
      đó trong cùng revision; trigger `platform.guard_connection_owning_workspace()` từ chối mọi UPDATE đổi
      `owning_workspace_id` (R1.7), vì AAD của bước 3 gắn cột đó; trigger `guard_connection_status` và
      `connection_usable` để ở ticket 04.
2. RLS ENABLE và FORCE, policy tenant theo dạng `test_rls_coverage.py` đòi lúc merge trên cả hai bảng;
   `REVOKE ALL ON platform.secret_envelopes FROM dw_app`; hàm SECURITY DEFINER `platform.put_secret`,
   `platform.open_secret`, `platform.secret_status`, `platform.delete_secret` lấy công ty từ
   `app.tenant_id` (không nhận tham số công ty), EXECUTE cho `dw_app`; `platform.put_secret` ghi giá trị mới
   của (chủ thể, trường) thành một dòng mới và không sửa dòng cũ, với `secret_version` là số kế tiếp mà
   `SecretStore` đã đưa vào AAD trước khi mã hóa (bước 3), nên hai lần ghi đồng thời cùng số thì UNIQUE từ chối
   lần sau; `platform.open_secret` mở đúng (chủ thể, trường, `secret_version`) bên gọi nêu, tức phiên bản mà bản
   kê của lượt ghim (ticket 04 bước 2); `platform.secret_status` trả các `secret_version` còn dòng của (chủ thể,
   trường), không trả giá trị; grant cột cho `platform.connections`.
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
4. `DW_KMS_PROVIDER=none|local` (giá trị `openbao` thêm ở ticket 06, cùng thay đổi với bên đọc của nó);
   `validate_for_profile` của api và worker từ chối `local` khi `settings.is_deployed`.
5. `kek_ref` suy từ công ty của ngữ cảnh; một dòng mang `kek_ref` của công ty khác → từ chối, audit
   `secret.key_mismatch`.
6. Assert ở `test_privileges.py`; `test_rls_coverage.py` tự thấy hai bảng; thêm hai dòng có lý do vào
   `_TENANT_WIDE_ON_PURPOSE` (danh sách của studio-skeleton/01, studio-skeleton:R9.1) (`secret_envelopes`: dòng con mà chủ thể mang workspace; `connections`: tầm dùng
   vượt workspace theo thiết kế); catalog export của offboarding (`_CATALOG_EXPORTABLE`) không liệt kê
   `secret_envelopes`.

## Tiêu chí chấp nhận

- [ ] R1.1: ghi một bí mật rồi `open_secret` trả đúng giá trị; phong bì trong database không chứa giá
      trị rõ; ghi giá trị mới cho cùng (chủ thể, trường) → một dòng mới với `secret_version` kế tiếp, dòng cũ không
      đổi, `open_secret` với phiên bản cũ vẫn trả giá trị cũ và với phiên bản mới trả giá trị mới; chèn trùng
      (chủ thể, `field`, `secret_version`) → UNIQUE từ chối.
- [ ] R1.2 (CV4): mock nhà cung cấp vọng header và key trong body lỗi → 0 lần xuất hiện ở checkpoint,
      `platform.tool_executions`, audit, span, log; tắt che → test đỏ.
- [ ] R1.3 (CV2): `SELECT * FROM platform.secret_envelopes` bằng `dw_app` → `permission denied`; khẳng
      định catalog trong `test_privileges.py`.
- [ ] R1.4 (CV1): chép một phong bì sang `connection_id` khác (cùng công ty và công ty khác), sang trường khác
      của cùng kết nối, hay sang dòng có `secret_version` khác rồi giải mã → lỗi; bọc lại khóa dữ liệu qua
      `KmsPort.rewrap` của `LocalDevKms` (`kek_version` tăng) → vẫn giải mã; gỡ AAD khỏi `SecretStore`, hay đưa
      `kek_version` vào AAD → test đỏ. Ca chủ thể `inbound_endpoint_id` chạy ở workflow-triggers/02, nơi thêm cột
      đó.
- [ ] R1.5 (CV3): đặt công ty A, `open_secret` với chủ thể của công ty B → không dòng; một dòng mang
      `kek_ref` của công ty khác → từ chối, audit `secret.key_mismatch`; chưa đặt `app.tenant_id` → không
      dòng.
- [ ] R1.6 (CV2): truy vấn catalog export của offboarding (`_CATALOG_EXPORTABLE`) không liệt kê
      `secret_envelopes` (integration).
- [ ] R1.7 (CV1): `UPDATE platform.connections SET owning_workspace_id = <workspace khác cùng công ty>` → trigger
      từ chối, dòng không đổi, phong bì của Kết nối vẫn giải mã; UPDATE cột khác của cùng dòng → nhận; gỡ trigger
      `platform.guard_connection_owning_workspace()` → UPDATE thành công và phong bì giải mã lỗi, test đỏ.
- [ ] R1.8 (CV23): đặt `app.tenant_id` của công ty A, `platform.put_secret` với `connection_id` của công ty B → lỗi
      khóa ngoại (23503), không dòng nào; xóa một Kết nối → mọi phong bì của nó xóa theo; đổi FK ghép thành FK một
      cột `connection_id` trong migration thử → lần ghi chéo công ty thành công, test đỏ.
- [ ] R2.2 (CV5): `DW_KMS_PROVIDER=local` với profile `uat` → `RuntimeError` lúc khởi động; gỡ
      `validate_for_profile` → test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `apps/api/src/dw_api/settings.py:323-325`; spec: R2.2.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:108-114`; spec: R1.6.
- `packages/python/dw_platform/tests/integration/test_rls_coverage.py:108`; spec: Dữ liệu
  (`_TENANT_WIDE_ON_PURPOSE` theo mẫu `_PRINCIPAL_ONLY_ON_PURPOSE`, DO-01).
- spec: R1, R2.2, CV1-CV5; ADR-0115 (Accepted) quyết 1; si-platform `db/si` không có bảng này (tự dẫn).

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
