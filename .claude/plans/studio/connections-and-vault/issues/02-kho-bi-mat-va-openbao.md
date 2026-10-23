# 02 — Kho bí mật: KmsPort, LocalDevKms, secret_envelopes và OpenBao Transit

Status: needs-info (DO-47)
Blocked by: .claude/plans/studio/studio-skeleton/issues/04-chinh-sach-compose-dich-vu-moi.md, .claude/plans/studio/foundations-hardening/issues/03-quyen-dw-app-va-rls-initplan.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R1.6, R2.1, R2.2, R2.3, R2.4, CV1, CV2, CV3, CV4, CV5, CV6

## Mục tiêu

Mọi Thông tin bí mật của công ty nằm trong một phong bì AES-256-GCM dưới Khóa của công ty, chỉ bộ môi
giới bí mật mở được, và một cửa cơ sở dữ liệu một chiều chặn `dw_app` đọc thẳng (spec R1, R2). Phần
`KmsPort` và `LocalDevKms` không chờ DO-47; OpenBao Transit, cách unseal và kho lưu chờ Đạt (O2, DO-47).
Gộp từ B8a-connections connections-and-vault 03 và 04.

## Việc cần làm

1. Một migration (revision hex ngẫu nhiên của alembic): `platform.secret_envelopes` và
   `platform.connections` theo mục Dữ liệu của spec:
    - `secret_envelopes`: `id` uuid, `tenant_id` FK `platform.tenants` ON DELETE CASCADE,
      `connection_id` uuid NULL, `alg text` CHECK (`aes-256-gcm`), `nonce bytea` CHECK độ dài 12,
      `kek_ref text`, `ciphertext bytea` CHECK độ dài ≤ 64 KiB, `aad_hint text` CHECK độ dài ≤ 64,
      `kek_version int`, timestamps; cung loại trừ chủ thể qua CHECK;
    - `connections`: toàn cột của spec (bao gồm `share_scope` CHECK, `status` CHECK không DEFAULT,
      `owner_workspace_id` FK `(tenant_id, id)` ON DELETE RESTRICT, index danh sách); trigger
      `guard_connection_status` và `connection_usable` để ở ticket 04.
2. RLS ENABLE và FORCE, policy tenant theo dạng `test_rls_coverage.py` đòi lúc merge trên cả hai bảng;
   `REVOKE ALL ON platform.secret_envelopes FROM dw_app`; hàm SECURITY DEFINER `platform.put_secret`,
   `platform.open_secret`, `platform.secret_status`, `platform.delete_secret` lấy công ty từ
   `app.tenant_id` (không nhận tham số công ty), EXECUTE cho `dw_app`; grant cột cho `platform.connections`.
3. `KmsPort`, `LocalDevKms` (HKDF-SHA256 từ `DW_LOCAL_KMS_MASTER_KEY`, AES key wrap); `SecretStore`
   (AES-256-GCM, AAD `dw.secret.v1|<tenant_id>|<connection_id>`); kiểu `Secret` (`repr` ẩn, `reveal()`
   chỉ ở module cho phép, có test kiến trúc).
4. `DW_KMS_PROVIDER=none|local|openbao`; `validate_for_profile` của api và worker từ chối `local` khi
   `settings.is_deployed`.
5. `kek_ref` suy từ công ty của ngữ cảnh; một dòng mang `kek_ref` của công ty khác → từ chối, audit
   `secret.key_mismatch`.
6. Khi triển khai (DO-47): `OpenBaoTransitKms` (httpx async qua Bộ gọi ra ngoài nội bộ, đăng nhập
   AppRole, gia hạn token); `GET /api/v1/ready` báo `kms`; compose `openbao` (ảnh ghim digest, chỉ mạng
   nội bộ, trivy); chính sách `infra/openbao/policies/dw-api.hcl`, `dw-worker.hcl`, `dw-offboarding.hcl`;
   `scripts/openbao_bootstrap.py` (không in secret ra stdout, thu hồi root token sau bootstrap);
   sao lưu kho OpenBao trong cùng job off-box với `scripts/backup_postgres.sh`, mở rộng restore drill.
7. Lane `credential_rewrap` (hằng ngày, lô 500, `transit/rewrap`), actor `system:credential_rewrap`;
   lane `offboarding` gọi hủy Khóa của công ty ở bước cuối với AppRole `dw-offboarding`.
8. Assert ở `test_privileges.py`; `test_rls_coverage.py` tự thấy hai bảng; catalog export của offboarding
   (`_CATALOG_EXPORTABLE`) không liệt kê `secret_envelopes`.

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
- [ ] R2.1: ở profile `uat` với `DW_KMS_PROVIDER=openbao`, `GET /api/v1/ready` báo `kms` ok; token của
      chính sách `dw-api` gọi xóa khóa → 403 từ OpenBao.
- [ ] R2.2 (CV5): `DW_KMS_PROVIDER=local` với profile `uat` → `RuntimeError` lúc khởi động; gỡ
      `validate_for_profile` → test đỏ.
- [ ] R2.3 (CV6): hủy Khóa của công ty → `open_secret` của công ty đó trả `kms_key_destroyed`; rewrap
      giữ nguyên plaintext, `kek_version` tăng, log lane không chứa giá trị canary.
- [ ] R2.4: OpenBao dừng → `open_secret` trả `kms_unavailable`, không dòng rõ nào được ghi; restore drill
      giải mã được bí mật canary sau khi khôi phục cả `dw` lẫn kho OpenBao.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `apps/api/src/dw_api/settings.py:323-325`; spec: R2.2.
- `scripts/backup_postgres.sh:2-3`; spec: R2.4.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:108-114`; spec: R1.6,
  R2.3.
- spec: R1, R2, CV1-CV6; ADR-0115 (Proposed) quyết 1; si-platform `db/si` không có bảng này (tự dẫn).

## Comments

- 2026-10-23 (agent): `needs-info` vì DO-47 (vận hành OpenBao: unseal, kho lưu, xoay khóa) chờ Đạt; phần
  `KmsPort`, `LocalDevKms`, `secret_envelopes` và cửa một chiều không chờ. D14 (DO-24) đã chốt resize host
  trước khi OpenBao ship.
