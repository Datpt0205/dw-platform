# 02 — Kho bí mật: KmsPort, LocalDevKms, secret_envelopes và cửa một chiều

Status: needs-triage
Blocked by: .claude/plans/studio/foundations-hardening/issues/03-quyen-dw-app-va-rls-initplan.md, .claude/plans/studio/org-and-principals/issues/01-khoa-don-vi-va-siet-realm.md, .claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R1.6, R2.2, CV1, CV2, CV3, CV4, CV5

## Mục tiêu

Mọi Thông tin bí mật của công ty nằm trong một phong bì AES-256-GCM dưới Khóa của công ty, chỉ bộ môi
giới bí mật mở được, và một cửa cơ sở dữ liệu một chiều chặn `dw_app` đọc thẳng (spec R1, R2.2). Phần này
không chờ spike 21 (ADR-0115 (Accepted)); OpenBao Transit, mở niêm phong, xoay khóa, hủy khóa và sao lưu
kho khóa ở ticket 06 (DO-47.1). Gộp từ B8a-connections connections-and-vault 03 và 04.

## Việc cần làm

1. Một migration (revision hex ngẫu nhiên của alembic): `platform.secret_envelopes` và
   `platform.connections` theo mục Dữ liệu của spec:
    - `secret_envelopes`: `id` uuid, `tenant_id` FK `platform.tenants` ON DELETE CASCADE,
      `connection_id` uuid NULL, `alg text` CHECK (`aes-256-gcm`), `nonce bytea` CHECK độ dài 12,
      `kek_ref text`, `ciphertext bytea` CHECK độ dài ≤ 64 KiB, `aad_hint text` CHECK độ dài ≤ 64,
      `kek_version int`, timestamps; loại trừ chủ thể qua CHECK `num_nonnulls(connection_id) = 1`, mà mỗi
      chủ thể mới nới rộng bằng một cột FK NULL trong migration của ticket thêm nó (`inbound_endpoint_id` ở
      workflow-triggers/02, ADR-0115 (Accepted) quyết 1);
    - `connections`: toàn cột của spec (bao gồm `share_scope` CHECK, `status` CHECK không DEFAULT,
      `owning_workspace_id` NOT NULL với FK ghép `(tenant_id, owning_workspace_id)` tới `platform.workspaces`
      ON DELETE RESTRICT trên `uq_workspaces_tenant_id_id` của org-and-principals/01, index danh sách);
      trigger `guard_connection_status` và `connection_usable` để ở ticket 04.
2. RLS ENABLE và FORCE, policy tenant theo dạng `test_rls_coverage.py` đòi lúc merge trên cả hai bảng;
   `REVOKE ALL ON platform.secret_envelopes FROM dw_app`; hàm SECURITY DEFINER `platform.put_secret`,
   `platform.open_secret`, `platform.secret_status`, `platform.delete_secret` lấy công ty từ
   `app.tenant_id` (không nhận tham số công ty), EXECUTE cho `dw_app`; grant cột cho `platform.connections`.
3. `KmsPort`, `LocalDevKms` (HKDF-SHA256 từ `DW_LOCAL_KMS_MASTER_KEY`, AES key wrap); `SecretStore`
   (AES-256-GCM, AAD `dw.secret.v1|<tenant_id>|<connection_id>`); kiểu `Secret` (`repr` ẩn, `reveal()`
   chỉ ở module cho phép, có test kiến trúc).
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
      trị rõ.
- [ ] R1.2 (CV4): mock nhà cung cấp vọng header và key trong body lỗi → 0 lần xuất hiện ở checkpoint,
      `platform.tool_executions`, audit, span, log; tắt che → test đỏ.
- [ ] R1.3 (CV2): `SELECT * FROM platform.secret_envelopes` bằng `dw_app` → `permission denied`; khẳng
      định catalog trong `test_privileges.py`.
- [ ] R1.4 (CV1): chép một phong bì sang `connection_id` khác (cùng công ty và công ty khác) rồi giải mã
      → lỗi; gỡ AAD khỏi `SecretStore` → test đỏ.
- [ ] R1.5 (CV3): đặt công ty A, `open_secret` với chủ thể của công ty B → không dòng; một dòng mang
      `kek_ref` của công ty khác → từ chối, audit `secret.key_mismatch`; chưa đặt `app.tenant_id` → không
      dòng.
- [ ] R1.6 (CV2): truy vấn catalog export của offboarding (`_CATALOG_EXPORTABLE`) không liệt kê
      `secret_envelopes` (integration).
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
