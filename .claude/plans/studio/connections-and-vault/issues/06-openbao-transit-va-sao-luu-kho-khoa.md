# 06 — OpenBao Transit: khóa khi triển khai, xoay khóa, hủy khóa, sao lưu và diễn tập khôi phục

Status: ready-for-agent
Blocked by: 02, 05, .claude/plans/studio/studio-skeleton/issues/04-chinh-sach-compose-dich-vu-moi.md, .claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md
Area: studio
Yêu cầu: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.8, CV5, CV6, CV20

## Mục tiêu

Khóa của công ty nằm trong OpenBao Transit, tự mở niêm phong sau khởi động lại và xoay mỗi 90 ngày; offboarding hủy
khóa; kho khóa vào job sao lưu với thời hạn giữ không dài hơn bản sao lưu dữ liệu, và diễn tập khôi phục kiểm cả hai
(spec R2). Tách từ ticket 02 theo DO-47.1: OpenBao chỉ ship sau khi phép đo FOG-25 ở bước 1 đạt (ADR-0115 (Accepted));
`KmsPort`, `LocalDevKms` và cửa một chiều đi trước ở ticket 02. Ticket này dựng và chứng minh mọi thứ trên compose của
máy dev, với OpenBao thật trong container (lưu trữ tích hợp, có niêm phong), không bao giờ `bao server -dev`; việc trên
host triển khai thật (nâng host D14, khóa niêm phong và AppRole thật, đích off-box thật, đo trên host) là ticket 08
`ready-for-human` (spec, Quyết định 4/11/2026 của ticket 06, (j)).

## Việc cần làm

1. Đo FOG-25 trước trên compose của máy dev, đúng câu 1 của
   `.claude/plans/studio/discovery/issues/21-vault-and-egress.md`: OpenBao 2.7.x Transit với `datakey/plaintext`,
   `rewrap`, `deletion_allowed`, `auto_rotate_period` lúc tạo khóa. Đạt khi cả bốn: (a) bốn API trên trả đúng như Vault
   Transit (một test hợp đồng gọi chúng); (b) khởi động lại container thì tự mở niêm phong, không lệnh tay, với khóa
   niêm phong nằm ngoài tập tệp mà job sao lưu chép (static seal từ một tệp bí mật của host, không trong volume dữ
   liệu), nên một bản sao lưu không mang theo khóa mở nó; (c) p95 mỗi lời gọi `datakey/plaintext` và `decrypt` ≤ 50 ms ở
   10 lời gọi mỗi giây trong 5 phút; (d) bộ nhớ thường trú của container ≤ 512 MiB. Số (c), (d) tạm (agent, theo ủy
   quyền 31/10/2026), đo lại trên host thật ở ticket 08. Ghi kết quả vào `## Answer` của ticket khám phá 21 và mục Open
   5 của ADR-0115 (Accepted). Nếu (a) hay (b) không đạt: dừng bước 2 tới 7, ghi số đo, và đề xuất sửa
   ADR-0115 (Accepted) theo ủy quyền (đổi chỗ giữ khóa hay cách mở niêm phong) ở Comments.
2. `OpenBaoTransitKms` sau `KmsPort`, năm phương thức của ADR-0115 (Accepted) quyết 1: ba của ticket 02 cộng
   `ensure_tenant_key` (tạo `tenant-<tenant_uuid>`, `aes256-gcm96`, `exportable=false`, `auto_rotate_period` 2160h, lười
   ở lần ghi bí mật đầu của công ty, chỉ tạo khi chưa có, "đã có" từ một lần tạo song song coi là thành công; không
   tạo cho công ty không ở `setup` hay `active`, trạng thái đọc trong giao dịch của lần ghi, để một lần ghi chen giữa bước
   hủy khóa và lúc đặt `offboarded` không tạo lại khóa) và `destroy_tenant_key` (đặt `deletion_allowed` rồi xóa; khóa
   không có → coi là đã hủy, idempotent). httpx async tới địa chỉ nội bộ của compose, không qua Bộ gọi ra ngoài (OpenBao
   là dịch vụ nội bộ, không phải đích ra Internet), đăng nhập AppRole, gia hạn token trước khi hết hạn.
   `DW_KMS_PROVIDER` thêm `openbao`; `validate_for_profile` của api và worker từ chối khi `settings.is_deployed` mà
   provider khác `openbao` (cả `none`, R2.1, R2.2), và overlay triển khai của compose đổi `${DW_KMS_PROVIDER:-none}`
   thành `${DW_KMS_PROVIDER:?}` (ticket 04 để lại). `GET /api/v1/ready` báo mục `kms` (`ok` | `unavailable`) trong
   thân; trạng thái HTTP vẫn 200 khi chỉ `kms` hỏng, vì mỗi lời gọi bí mật tự đóng khi lỗi (R2.4), api không rời định
   tuyến vì OpenBao.
3. Compose `openbao` theo chính sách dịch vụ mới của studio-skeleton/04 (ảnh ghim digest, chỉ mạng nội bộ, trivy).
   Chính sách, mỗi AppRole một tệp, quyền đúng đường dẫn: `infra/openbao/policies/dw-api.hcl` và `dw-worker.hcl`
   (`create` và `read` trên `transit/keys/tenant-*`, `update` trên `transit/datakey/plaintext/tenant-*`,
   `transit/decrypt/tenant-*`, `transit/rewrap/tenant-*`; không `transit/keys/*/config`, không `delete`);
   `dw-offboarding.hcl` (`update` trên `transit/keys/tenant-*/config`, `delete` trên `transit/keys/tenant-*`);
   `dw-backup.hcl` (`read` trên `sys/storage/raft/snapshot`). `role_id` và `secret_id` tới container qua docker secret
   (tệp dưới `/run/secrets/`), không qua biến môi trường; lane `offboarding` dựng client riêng với `dw-offboarding`,
   không lane nào khác cầm nó: `destroy_tenant_key` nhận một bằng chứng đọc trong giao dịch của lane rằng công ty đang
   `offboarding` và bước xóa dữ liệu cuối đã xong, từ chối khi thiếu, và một quét nguồn giữ chỗ gọi duy nhất của nó là
   module của lane `offboarding`, vì quyền của `dw-offboarding` hủy được khóa của mọi công ty và không đảo lại được. `scripts/openbao_bootstrap.py` tạo chính sách và AppRole, ghi thông tin xác thực vào
   tệp quyền 0600 dưới `infra/openbao/out/` (trong `.gitignore`), không in ra stdout, thu hồi root token sau bootstrap.
4. Lane `credential_rewrap` (hằng ngày, lô 500): migration (revision hex ngẫu nhiên) thêm ba hàm SECURITY DEFINER,
   `search_path` cố định, REVOKE PUBLIC, EXECUTE cho `dw_app`, `test_privileges.py` khẳng định:
   `platform.tenants_with_secrets()` trả id công ty có phong bì, không gì khác (như lane cuộn của usage-and-limits/02);
   `platform.secret_rewrap_candidates(p_below_kek_version int, p_limit int)`, hẹp theo `app.tenant_id` như các hàm cửa
   của ticket 02, trả `id`, `kek_version`, `wrapped_data_key` (không `ciphertext`, không `nonce`) của phong bì có
   `kek_version` nhỏ hơn; `platform.put_rewrapped_key(p_id uuid, p_from_kek_version int, p_wrapped_data_key bytea,
p_kek_version int)`, cùng hẹp, chỉ ghi `wrapped_data_key` và `kek_version` khi `kek_version` hiện bằng
   `p_from_kek_version`, `p_kek_version` lớn hơn nó và khối bắt đầu bằng `vault:v<p_kek_version>:` (so-và-đặt; sai → trả
   false, không ghi). Mỗi công ty một giao dịch đặt `app.tenant_id`; lane hỏi phiên bản mới nhất của khóa ở OpenBao,
   gọi `transit/rewrap`, ghi qua hàm; mỗi lô tối đa 500 phong bì của một công ty một giao dịch, phong bì không bọc lại được (khối hỏng, `kek_ref` của
   công ty khác thì audit `secret.key_mismatch` như CV3) bị bỏ qua, đếm và ghi log, không chặn lô; một
   `lane_audit_event` `secret.envelopes_rewrapped` trong cùng giao dịch của mỗi lô có dòng đổi, ở workspace sở hữu của
   chủ thể đầu tiên của lô (actor
   `system_actor("credential_rewrap")`, `details.actor` `system:credential_rewrap`, `details` chỉ số dòng và hai phiên
   bản khóa), nhãn vào mảnh `configs/copy/audit_actions.d/connections-and-vault.yaml`. Lane không nâng
   `min_decryption_version`, để bản sao lưu còn trong hạn giữ vẫn giải mã được (R2.7, R2.8). Lane không đổi `ciphertext`,
   `field`, `secret_version`, nên AAD của ticket 02 bước 3 không đổi.
5. Lane `offboarding` gọi `destroy_tenant_key` ở bước cuối; lỗi (OpenBao không tới được) → bước đó lỗi, công ty ở lại
   `offboarding`, lane thử lại ở lượt sau, không bao giờ đặt `offboarded` khi khóa còn; khóa không có → coi như đã hủy.
   Audit `tenant.key_destroyed` đứng tên người đã quyết offboarding với `details.lane` `offboarding` (CLAUDE.md, Agent
   and tool rules), trong giao dịch đặt `offboarded`.
6. Sao lưu: snapshot của OpenBao (`bao operator raft snapshot save` bằng AppRole `dw-backup`) trong cùng job với
   `scripts/backup_postgres.sh`, cùng tên lượt; thời hạn giữ ở một tệp cấu hình `infra/backup/retention.env`
   (`BACKUP_KEEP_DAYS`, `KEYSTORE_KEEP_DAYS`, `OFFBOX_BACKUP_KEEP_DAYS`, `OFFBOX_KEYSTORE_KEEP_DAYS`), job tự xóa bản
   quá hạn ở cả hai nơi; một lượt chỉ có một nửa (`dw` mà không snapshot, hay ngược lại) làm job đỏ, không tính là lượt
   đủ, và lệnh xóa bản quá hạn không bao giờ xóa cặp đủ mới nhất; `scripts/check_backup_retention.py` chạy trong CI, đỏ khi một hạn của kho khóa dài hơn hạn
   tương ứng của `dw`. Đích off-box ở compose là một bucket của SeaweedFS; đích thật là ticket 08.
7. `test_restore_drill.py` mở rộng: khôi phục cả `dw` lẫn snapshot của OpenBao từ cùng một lượt sao lưu vào một OpenBao
   mới (mở niêm phong bằng cùng tệp khóa niêm phong của compose), rồi giải mã bí mật canary. Chạy trong
   `make test-integration` với dịch vụ `openbao` của compose, thêm vào các dịch vụ mà job integration của CI khởi động;
   thiếu dịch vụ thì test đỏ, không bỏ qua.

## Tiêu chí chấp nhận

- [ ] R2.5: bước 1, bốn mục (a)-(d) có số đo ở `## Answer` của discovery/21 và Open 5 của ADR-0115 (Accepted); một mục không
      có số → ticket chưa xong.
- [ ] R2.1: compose với `DW_KMS_PROVIDER=openbao`, `GET /api/v1/ready` báo `kms` `ok`; token của `dw-api` gọi xóa khóa hay
      sửa `transit/keys/tenant-*/config` → 403 từ OpenBao; token của `dw-offboarding` gọi `datakey` → 403.
- [ ] R2.2 (CV5): settings triển khai với `DW_KMS_PROVIDER=none` hay `local` → `RuntimeError` lúc khởi động ở api và
      worker; gỡ nhánh `none` → test đỏ.
- [ ] R2.3 (CV6): hủy Khóa của công ty → `open_secret` của công ty đó trả `kms_key_destroyed`, công ty khác vẫn mở được;
      bỏ bước hủy khóa → giải mã vẫn được, test đỏ; OpenBao dừng lúc offboarding → công ty vẫn `offboarding`, không
      audit `tenant.key_destroyed`; chạy lại khi OpenBao lên → `offboarded`, đúng một audit.
- [ ] R2.4: OpenBao dừng → `open_secret` trả `kms_unavailable`, không dòng rõ nào được ghi; `GET /api/v1/ready` trả 200
      với `kms` `unavailable`.
- [ ] R2.5: `docker restart` container `openbao` → `GET /api/v1/ready` báo `kms` ok mà không có lệnh mở niêm phong tay;
      sai nếu cần thao tác tay.
- [ ] R2.6: chu kỳ xoay của khóa đọc lại từ OpenBao bằng 2160h; xoay khóa sang phiên bản mới → phong bì cũ vẫn giải mã
      được; sau lane `credential_rewrap`, plaintext giữ nguyên, `wrapped_data_key` đổi còn `ciphertext` và `nonce` giữ
      nguyên, `kek_version` tăng, `secret_version` không đổi, phong bì vẫn giải mã được với cùng AAD, log lane không
      chứa giá trị canary, đúng một `secret.envelopes_rewrapped` cho công ty đó; `put_rewrapped_key` với
      `p_from_kek_version` cũ, hay với khối không mang tiền tố `vault:v<n>:` → false, dòng không đổi; giao dịch của công
      ty B gọi với id của A → false, dòng của A không đổi; `secret_rewrap_candidates` trong giao dịch của B không trả phong
      bì nào của A; một phong bì hỏng trong lô → lô vẫn xong, phong bì đó đếm vào log; đưa `kek_version` vào AAD → giải mã sau lane thất bại, test
      đỏ.
- [ ] R2.7 (CV20): `KEYSTORE_KEEP_DAYS` hay `OFFBOX_KEYSTORE_KEEP_DAYS` dài hơn hạn tương ứng của `dw` → kiểm cấu hình
      đỏ; bằng hay ngắn hơn → xanh; job xóa snapshot quá hạn ở cả hai nơi.
- [ ] R2.8 (CV20): diễn tập khôi phục cả `dw` lẫn kho khóa từ cùng một lượt sao lưu giải mã được bí mật canary; diễn
      tập chỉ khôi phục `dw` → giải mã thất bại, test đỏ; snapshot của OpenBao lỗi trong một lượt → job đỏ, cặp đủ trước
      đó không bị xóa.
- [ ] R2.3 (CV6): gọi `destroy_tenant_key` cho công ty `active`, hay từ một module ngoài lane `offboarding` → từ chối,
      khóa còn; quét nguồn thấy một chỗ gọi mới → test đỏ; lần ghi bí mật của công ty `offboarding` → không khóa nào được
      tạo.
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
- 2026-10-24 (agent): theo kiểm nhất quán vòng 3 (vòng sửa thứ tư): thêm Blocked by foundations-hardening/07, vì
  bước 5 sửa lane `offboarding` (`offboarding.py` và `test_offboarding.py`) mà ticket đó viết lại.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt b: lane `credential_rewrap` chỉ bọc lại khóa dữ liệu
  (`wrapped_data_key` của ticket 02) và tăng `kek_version`, không đổi `ciphertext` hay `secret_version`, nên AAD
  của ticket 02 (vế phiên bản là `secret_version`, ADR-0115 (Accepted) quyết 1) không đổi và phong bì vẫn giải mã
  sau lane (bước 4, R2.6).
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check, rồi boundary walk vì bản
  sửa thêm một migration) trên `0baced0`: `check_plans.py` 24 Đạt; 0 CRITICAL, 9 HIGH, sửa
  theo khuyến nghị, mỗi quyết định cùng `Nếu sai thì:` ở mục Quyết định của spec, dòng 4/11/2026 của ticket 06,
  (a)-(j): lane bọc lại không có cửa đọc ghi phong bì (ba hàm definer, so-và-đặt); "đạt" của FOG-25 không có ngưỡng (bốn
  mục, số tạm); ai tạo khóa của công ty và chính sách nào sửa được cấu hình khóa; hủy khóa lỗi thì sao (ở lại
  `offboarding`, audit đứng tên người quyết); `/ready` khi `kms` hỏng và `none` ở profile triển khai; diễn tập trên
  OpenBao thật trong CI; hạn giữ off-box và danh tính chụp snapshot; đường của thông tin xác thực AppRole; lane không
  nâng `min_decryption_version`. Tách việc trên host thật sang ticket 08 `ready-for-human` (D14, Chờ Đạt 20): ticket
  này dựng được trên máy dev với OpenBao trong compose. Thêm Blocked by 05: hai ticket cùng sửa composition root của
  worker (`build_kms`) và `settings.py`, không có đường phụ thuộc giữa chúng (bảng va chạm của gate ticket 05).
- 2026-11-04 (agent): MEDIUM, chưa sửa, cho người dựng: (M1) S3 của gate: bản sao lưu `dw` cũ cùng snapshot kho khóa còn
  hạn vẫn giải mã được bí mật của công ty đã offboard tới khi snapshot cuối giữ khóa đó hết hạn: đúng thiết kế
  (ADR-0115 (Accepted) quyết 1, R2.7), ghi ở trang vận hành; (M2) neo ở Nguồn đã trôi (ticket 02 M (a)): `settings.py:323-325` nay
  là `is_deployed` ở `apps/api/src/dw_api/settings.py:350-353`, `offboarding.py:108-114` nay là `_CATALOG_EXPORTABLE`;
  (M3) `scripts/openbao_bootstrap.py` chạy lại trên kho đã bootstrap: idempotent, không tạo AppRole thứ hai; (M4) dòng
  `Xong:` đọc theo `.claude/rules/wave-close.md`, cộng `test_privileges.py`, `test_rls_coverage.py` vì có migration.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): boundary walk (một subagent, sáu biên) trên bản đã sửa: 0 CRITICAL, 1
  HIGH, sửa: quyền của `dw-offboarding` hủy được khóa của mọi công ty mà bất kỳ mã nào trong worker cũng đọc được tệp
  của nó: `destroy_tenant_key` đòi bằng chứng `offboarding` đọc trong giao dịch và chỉ một chỗ gọi (quét nguồn). Bốn
  MEDIUM sửa luôn vì rẻ: không tạo lại khóa cho công ty không `setup`/`active`; lượt sao lưu một nửa làm job đỏ và không
  xóa cặp đủ cuối; lô bọc lại theo công ty, audit cùng giao dịch ở workspace sở hữu, phong bì hỏng bỏ qua; tạo khóa song
  song. Sửa của lượt này không có người đọc mới: nhận rủi ro (agent, theo ủy quyền 31/10/2026), mỗi sửa có tiêu chí đỏ
  được. Nếu sai thì: lỗi lộ ra khi dựng, ghi ở đây. MEDIUM để lại: (M5) không nâng `min_decryption_version`, nên một
  dump `dw` cũ quá hạn giữ vẫn mở được bằng kho khóa sống của công ty còn hoạt động: rủi ro nhận theo ủy quyền, tới khi
  một lane nâng nó sau khi bản sao lưu cuối giữ phiên bản cũ hết hạn (W2); (M6) `secret_id` của AppRole không có TTL hay
  giới hạn số lần dùng ở W1, xoay là việc của ticket 08; (M7) phong bì ghi bằng `LocalDevKms` trên một môi trường chuyển
  sang `openbao` không giải mã được: môi trường triển khai chưa bao giờ chạy `local` (R2.2), máy dev xóa dữ liệu khi đổi.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
