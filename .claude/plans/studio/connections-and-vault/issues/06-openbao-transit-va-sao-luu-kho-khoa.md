# 06 — OpenBao Transit: khóa khi triển khai, xoay khóa, hủy khóa, sao lưu và diễn tập khôi phục

Status: needs-triage
Blocked by: 02, .claude/plans/studio/studio-skeleton/issues/04-chinh-sach-compose-dich-vu-moi.md
Area: studio
Yêu cầu: R2.1, R2.3, R2.4, R2.5, R2.6, R2.7, R2.8, CV6, CV20

## Mục tiêu

Khi triển khai, Khóa của công ty nằm trong OpenBao Transit, tự mở niêm phong sau khởi động lại và xoay mỗi
90 ngày; offboarding hủy khóa; kho khóa vào job sao lưu với thời hạn giữ không dài hơn bản sao lưu dữ liệu,
và diễn tập khôi phục kiểm cả hai (spec R2). Tách từ ticket 02 theo DO-47.1: OpenBao chỉ ship sau khi phép đo
FOG-25 ở bước 1 đạt (ADR-0115 (Accepted)); `KmsPort`, `LocalDevKms` và cửa một chiều đi trước ở ticket 02.

## Việc cần làm

1. Đo FOG-25 trước, đúng câu 1 của `.claude/plans/studio/discovery/issues/21-vault-and-egress.md`: OpenBao
   2.7.x Transit với `datakey/plaintext`, `rewrap`, `deletion_allowed`; mở niêm phong không người (lưu trữ
   tích hợp hay database riêng); độ trễ p95 mỗi lời gọi ở tốc độ thí điểm và bộ nhớ trên host. Ghi kết quả
   vào `## Answer` của ticket khám phá 21 và mục Open 5 của ADR-0115 (Accepted). Nếu tương đương API hay mở niêm phong
   không người không đạt, dừng và báo Đạt; không làm bước 2 tới 6.
2. `OpenBaoTransitKms` sau `KmsPort` (httpx async qua Bộ gọi ra ngoài nội bộ, đăng nhập AppRole, gia hạn
   token); `DW_KMS_PROVIDER` thêm giá trị `openbao`; `GET /api/v1/ready` báo `kms`.
3. Compose `openbao` theo chính sách dịch vụ mới của studio-skeleton/04 (ảnh ghim digest, chỉ mạng nội bộ,
   trivy); chính sách `infra/openbao/policies/dw-api.hcl`, `dw-worker.hcl`, `dw-offboarding.hcl`;
   `scripts/openbao_bootstrap.py` (không in secret ra stdout, thu hồi root token sau bootstrap); đường mở
   niêm phong không người theo kết quả bước 1.
4. Khóa `tenant-<tenant_uuid>` (`aes256-gcm96`, không xuất được) xoay mỗi 90 ngày; lane
   `credential_rewrap` (hằng ngày, lô 500, `transit/rewrap`), actor `system:credential_rewrap`.
5. Lane `offboarding` gọi hủy Khóa của công ty ở bước cuối với AppRole `dw-offboarding`.
6. Sao lưu kho OpenBao trong cùng job off-box với `scripts/backup_postgres.sh`; thời hạn giữ cả bản trên
   máy lẫn bản off-box ghi trong cấu hình và không dài hơn `BACKUP_KEEP_DAYS` của `dw`, có một kiểm cấu
   hình chạy trong CI; mở rộng `test_restore_drill.py` để khôi phục cả `dw` lẫn kho khóa từ cùng một lượt
   sao lưu.

## Tiêu chí chấp nhận

- [ ] R2.1: ở profile `uat` với `DW_KMS_PROVIDER=openbao`, `GET /api/v1/ready` báo `kms` ok; token của
      chính sách `dw-api` gọi xóa khóa → 403 từ OpenBao.
- [ ] R2.3 (CV6): hủy Khóa của công ty → `open_secret` của công ty đó trả `kms_key_destroyed`; bỏ bước
      hủy khóa → giải mã vẫn được, test đỏ.
- [ ] R2.4: OpenBao dừng → `open_secret` trả `kms_unavailable`, không dòng rõ nào được ghi.
- [ ] R2.5: khởi động lại container `openbao` ở profile `uat` → `GET /api/v1/ready` báo `kms` ok mà không
      có lệnh mở niêm phong tay; sai nếu cần thao tác tay.
- [ ] R2.6: chu kỳ xoay của khóa đọc lại từ OpenBao bằng 90 ngày; xoay khóa sang phiên bản mới → phong bì
      cũ vẫn giải mã được; sau lane `credential_rewrap`, plaintext giữ nguyên, `kek_version` tăng, log lane
      không chứa giá trị canary.
- [ ] R2.7 (CV20): thời hạn giữ bản sao lưu kho khóa dài hơn `BACKUP_KEEP_DAYS` của `dw` → kiểm cấu hình
      đỏ; bằng hay ngắn hơn → xanh.
- [ ] R2.8 (CV20): diễn tập khôi phục cả `dw` lẫn kho khóa từ cùng một lượt sao lưu giải mã được bí mật
      canary; diễn tập chỉ khôi phục `dw` → giải mã thất bại, test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `apps/api/src/dw_api/settings.py:323-325`; spec: R2.1, R2.5.
- `scripts/backup_postgres.sh:29`; spec: R2.7.
- `packages/python/dw_platform/tests/integration/test_restore_drill.py:57`; spec: R2.8.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:108-114`; spec: R2.3.
- spec: R2, CV6, CV20; ADR-0115 (Accepted) quyết 1, 7; DO-47.1, DO-47.2; discovery/21.

## Comments

- 2026-10-23 (agent): tách từ ticket 02 theo DO-47.1 (Đạt chốt 23/10/2026). ADR-0115 (Accepted) được chấp nhận với
  điều kiện OpenBao chỉ ship sau khi FOG-25 đo mở niêm phong không người và tương đương Transit, nên bước 1
  là phép đo; ticket khám phá 21 đóng bằng một dòng trỏ tới kết quả ghi ở đây. D14: host chính lên ít nhất
  4 vCPU / 16 GB trước khi OpenBao ship.
