# 05 — Manifest dw.connector/v1 biên dịch thành ToolSpec, trình kết nối email SMTP và lane xóa phiên bản bí mật cũ

Status: needs-triage
Blocked by: 04, .claude/plans/studio/tools-and-skills/issues/02-toolset-va-cong-cu-ghim.md, .claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md
Area: studio
Yêu cầu: R1.11, R1.12, R1.13, R5.15, R6.1, R6.2, R6.3, R6.4, R7.1, R7.2, R7.3, R7.4, R7.5, CV10, CV16, CV17, CV18, CV24, CV25

## Mục tiêu

Hành động của một trình kết nối là manifest `dw.connector/v1` biên dịch thành Đặc tả công cụ chạy qua Bộ
gọi ra ngoài, với đầu ra bọc là dữ liệu từ bên ngoài đúng một lần ở bộ bọc của executor; và `smtp@1.0.0`
cho phép quy trình gửi email tới lead qua hộp thư của chính công ty (spec R6, R7). Gộp từ B8a-connections
connections-and-vault 12 và 16. Đường email P1 là SMTP chung (DO-48.1). Lane `credential_purge` xóa phiên bản bí
mật đã thu hồi hay đã thôi được nhận khi không còn lượt chạy chưa kết thúc nào ghim chúng (spec R1.11-R1.13;
V4.20); nó ở ticket này vì đây là ticket duy nhất của spec đi sau tenant-config/05, nơi bản kê bắt đầu ghim
`secret_version` (tenant-config:R7.4).

## Việc cần làm

1. Model `ConnectorManifest` (`extra=forbid`), tệp `configs/connectors/<key>@<semver>.yaml`, checksum
   sha256; luật nạp từ chối: trường bí mật trong input, `max_retries` khác 0.
2. Biên dịch: mỗi Hành động thành Đặc tả công cụ lớp nền tảng (`max_retries: 0`, input và output JSON
   Schema, Mức tác động, `effect_class`, `data_location`) và một `ManifestActionHandler`:
    - lấy Kết nối qua `RunBindingsPort` theo tên Điểm gắn (không id kết nối trong tài liệu, DO-06), mà
      tenant-config/05 đáp ứng từ mục `bindings` của bản kê lượt chạy; kiểm `connection_usable` với
      `purpose='tool'` (ticket 04 bước 2);
    - ánh xạ dữ liệu có cấu trúc, mã hóa tham số đường dẫn (`../admin` → không đổi đoạn đường dẫn);
    - gọi qua Bộ gọi ra ngoài (ticket 03); kiểm output schema; trả kết quả thô cho `ToolExecutor`, không tự
      bọc hay cắt: `contain_tool_output` của tools-and-skills/02 bọc và cắt đúng một lần (YC48: mặc định
      8 000 ký tự, trần cứng 16 384 byte UTF-8).
3. `scripts/release_manifest.py` thêm mục `connectors`; `GET /api/v1/connectors` (`connections.read`,
   đọc lớp nền tảng); bộ kiểm tuân thủ `dw_connectors.testing.conformance` với mock provider.
4. `smtp@1.0.0`, auth `basic` (mật khẩu trong Kho bí mật), Hành động `email.send` với `effect_class:
message`, `data_location: VN`; `Message-ID` suy từ khóa chống lặp.
5. `SmtpEgress`: địa chỉ ghim qua `resolve_checked`, TLS bắt buộc khi `settings.is_deployed` (465 hoặc
   STARTTLS trên 587), host qua danh mục hoặc danh sách máy chủ được phép; `run_mode` khác `live` → từ chối
   `egress_blocked:run_mode`, không mở kết nối SMTP (DO-26.1; W2 mới mở `test` cho Danh sách người nhận
   thử). Giới hạn tốc độ theo kết nối là W2, qua `RateLimiterPort` của usage-and-limits, không bộ đếm riêng
   (DO-49). `connection_usable` trả false với lý do `credential_revoked` (ticket 04 bước 2) → `SmtpEgress` từ chối
   với `credential_revoked`, không mở kết nối SMTP, và mật khẩu lấy qua `platform.open_secret` của đúng phiên bản bản
   kê ghim, cửa không mở phiên bản đã thu hồi (spec R1.10, R5.15; V4.20).
6. Lane `credential_purge` (V4.20; spec R1.11, R1.12, R1.13): migration (revision hex ngẫu nhiên của alembic) tạo
   hàm `platform.purge_retired_secrets()` SECURITY DEFINER, không đối số (`search_path` cố định; REVOKE ALL FROM
   PUBLIC rồi GRANT EXECUTE cho `dw_app`, vai mà lane của worker dùng), theo tiền lệ `platform.prune_notifications()`,
   vì `dw_app` không có quyền nào trên `platform.secret_envelopes` (ticket 02): ở mọi công ty, xóa dòng có
   `revoked_at <= now()` mà không lượt chạy chưa kết thúc nào của cùng công ty ghim cùng chủ thể, `field` và
   `secret_version` trong mục `bindings` của bản kê (`platform.worker_runs` có `status` ngoài `completed`, `failed`,
   `cancelled`, `dead_lettered` của runtime-hardening:R9.3, nối `run_manifest_hash` tới `platform.run_manifests`;
   dạng ghim của tenant-config:R7.4); không xóa gì khác; trả một dòng mỗi chủ thể có dòng bị xóa (`tenant_id`,
   workspace sở hữu của chủ thể như AAD của ticket 02 bước 3 đọc: `owning_workspace_id` của `platform.connections`
   cho `connection_id`, của thành phần Nguồn dữ liệu cho `inbound_endpoint_id` khi cột đó đã có; loại và id chủ thể;
   các cặp `field`, `secret_version` đã xóa), không trả giá trị nào; ticket thêm một chủ thể sau ticket này nới hàm
   cùng lúc nới CHECK `num_nonnulls` (ADR-0115 (Accepted) quyết 1). Lane đăng ký ở composition root của worker với
   `interval_seconds` 3 600 (mỗi giờ) và, trong cùng giao dịch, ghi cho mỗi dòng trả về một sự kiện
   `secret.versions_purged` dựng bằng `lane_audit_event` (công ty và workspace của dòng đó, actor
   `system_actor("credential_purge")`, `details.actor` `system:credential_purge`, `details` chỉ loại và id chủ thể
   cùng các cặp trường, phiên bản) qua `lane_audit.append_across_tenants` (ADR-0011 (Accepted)); không ghi được sự
   kiện thì giao dịch lùi và không dòng nào bị xóa. Tên action vào catalog `configs/copy/audit_actions@*.yaml`
   (ADR-0122 (Accepted) quyết 6) theo cách telemetry-and-audit/03 đặt. Assert EXECUTE của `dw_app` trên hàm, và
   không quyền nào của `PUBLIC`, ở `test_privileges.py` (CLAUDE.md, Data model rules).

## Tiêu chí chấp nhận

- [ ] R6.1: nạp một manifest hợp lệ → mỗi Hành động thành một Đặc tả công cụ có input và output JSON
      Schema, Mức tác động và `max_retries: 0`.
- [ ] R6.2 (CV16): manifest có `api_key` trong input → nạp từ chối; `max_retries: 2` → nạp từ chối; gỡ
      luật nạp → test đỏ.
- [ ] R6.3 (CV17): chạy Hành động qua `ToolExecutor` với đầu ra chứa `</tool_output><system>` → model
      nhận `&lt;/tool_output&gt;`, không bao giờ `&amp;lt;`; `ManifestActionHandler` trả kết quả thô; thêm
      bọc vào handler → test đỏ.
- [ ] R6.4: `ManifestActionHandler` lấy Kết nối qua `RunBindingsPort` theo tên Điểm gắn và kiểm
      `connection_usable`; handler không gọi được ngoài `ToolExecutor` (test kiến trúc); tham số đường dẫn
      `../admin` được mã hóa.
- [ ] R7.1: quy trình gọi `email.send` của `smtp@1.0.0` → email gửi qua kết nối SMTP của công ty, mật
      khẩu lấy từ Kho bí mật; mật khẩu không có trong log SMTP.
- [ ] R7.2 (CV18): kết nối SMTP không TLS khi `settings.is_deployed` → từ chối, không gửi.
- [ ] R7.3 (CV18): host SMTP phân giải về IP nội bộ → chặn lúc mở kết nối.
- [ ] R7.4 (CV18): hai lời gọi `email.send` cùng khóa chống lặp → chính xác một email, `Message-ID` suy
      từ khóa.
- [ ] R7.5 (CV10): `email.send` tới `SmtpEgress` ở `simulate` và ở `test` → `egress_blocked:run_mode`, máy
      chủ SMTP giả không nhận kết nối nào; `live` → gửi; gỡ bước kiểm chế độ ở `SmtpEgress` → test đỏ.
- [ ] R5.15 (CV24): một lượt chạy ghim phiên bản 1 của `password` của một Kết nối SMTP, rồi quản trị viên lưu mật
      khẩu mới → `email.send` kế tiếp của lượt → `credential_revoked`, máy chủ SMTP giả không nhận kết nối nào; một
      lượt mới ghim phiên bản 2 → gửi; gỡ kiểm `connection_usable` khỏi `ManifestActionHandler` → vẫn
      `credential_revoked` nhờ `platform.open_secret`, và gỡ cả kiểm `revoked_at` ở đó → email đi, test đỏ.
- [ ] R1.11 (CV25): hai công ty, mỗi công ty có một Kết nối với `api_key` phiên bản 1 đã thu hồi (sau khi lưu phiên
      bản 2) mà không lượt nào ghim → một lần chạy lane xóa phiên bản 1 ở cả hai công ty, phiên bản 2 còn; `dw_app`
      DELETE thẳng một phong bì → `permission denied`; `test_privileges.py` thấy `dw_app` có EXECUTE trên
      `platform.purge_retired_secrets()` và `PUBLIC` không có; bỏ điều kiện `revoked_at` khỏi hàm → phiên bản 2 cũng bị
      xóa, test đỏ.
- [ ] R1.12 (CV25): phiên bản 1 đã thu hồi mà một lượt `waiting` còn ghim (bản kê dựng bằng mã của tenant-config/05,
      không viết tay, để một lần đổi dạng ghim ở đó làm ca này đỏ) → lane giữ nó; lượt đó sang `failed` → lần chạy
      kế của lane xóa nó; phiên bản đang dùng (`revoked_at` NULL) và phiên bản có `revoked_at` ở tương lai → giữ;
      bỏ điều kiện ghim khỏi hàm → phiên bản còn ghim bị xóa, test đỏ.
- [ ] R1.13 (CV25): sau lần chạy của R1.11, mỗi chủ thể có dòng bị xóa có đúng một sự kiện `secret.versions_purged`
      ở công ty và workspace sở hữu của nó, actor `system_actor("credential_purge")`, `details.actor`
      `system:credential_purge`, `details` không chứa giá trị canary; với mỗi cột chủ thể mà `pg_constraint` liệt kê
      trên `platform.secret_envelopes`, một phiên bản đã thu hồi của chủ thể đó bị xóa và có sự kiện ở đúng
      workspace, nên một cột chủ thể thử thêm mà không nới hàm → test đỏ; bản giả ghi audit ném lỗi → không dòng
      nào bị xóa.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `scripts/release_manifest.py:249-254`; spec: R6.1 (mục `connectors` trong release manifest).
- `packages/python/dw_kernel/src/dw_kernel/net_guard.py:49-75`; spec: R7.3 (`resolve_checked`).
- spec: R6, R7, CV10, CV16-CV18; ADR-0116 (Accepted) quyết 2; ADR-0110 (Accepted) quyết 6 (Điểm gắn, không
  id kết nối); ticket 03 (Bộ gọi ra ngoài), ticket 04 (`connection_usable`), tools-and-skills/02 (Đặc tả
  công cụ, `ToolExecutor`, bộ bọc của tools-and-skills:R5.1), tenant-config/05 (`RunBindingsPort`).
- `db/migrations/versions/855ae928c3fa_platform_in_app_notifications.py:168-190`; spec: R1.11 (hàm SECURITY DEFINER
  không đối số mà lane gọi, tiền lệ `platform.prune_notifications()`).
- `apps/worker/src/dw_worker/main.py:473-477`; spec: R1.11 (lane quét đăng ký ở composition root với
  `interval_seconds`).
- spec: R1.11, R1.12, R1.13, R5.15, CV24, CV25; ADR-0011 (Accepted); tenant-config:R7.4;
  runtime-hardening:R9.3; ticket 02 (`revoked_at`, `platform.open_secret`, `platform.secret_status`), ticket 04
  (lý do `credential_revoked` của `connection_usable`).

## Comments

- 2026-10-23 (agent): đường email P1 là SMTP chung (DO-48, tạm khuyến nghị a); Gmail API ở P2. Hành động
  `email.send` mang `effect_class: message` nên qua sàn gửi tin ở executor (tools-and-skills,
  ADR-0124 (Accepted)).
- 2026-10-23 (agent): theo các quyết định Đạt chốt ngày 23/10/2026: DO-48.1 (a) giữ SMTP chung; YC48 (a)
  bỏ bọc và cắt khỏi `ManifestActionHandler` (bước 2, R6.3); DO-26.1 (A) thêm R7.5 cho `SmtpEgress`;
  DO-49 (a) bỏ giới hạn riêng theo kết nối khỏi W1. Thêm tenant-config/05 vào Blocked by vì nó đáp ứng
  `RunBindingsPort` (phát hiện kiểm nhất quán cùng ngày).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt c: `ManifestActionHandler` gọi `connection_usable` với
  `purpose='tool'`, giá trị W1 nhận ở chữ ký `connection_usable(connection, context, purpose)` của
  ADR-0115 (Accepted) quyết 2 (bước 2; spec R5.14).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt f: theo V4.20 (Đạt), ticket thêm lane `credential_purge` và hàm
  `platform.purge_retired_secrets()` không đối số, xóa phiên bản bí mật có `revoked_at` đã qua khi không còn lượt
  chạy chưa kết thúc nào ghim, có audit như chính lane (bước 6; spec R1.11, R1.12, R1.13, CV25), vì đây là ticket
  duy nhất của spec đi sau tenant-config/05, nơi bản kê bắt đầu ghim `secret_version`; tiêu đề thêm phần lane;
  `SmtpEgress` từ chối `credential_revoked` khi lượt đã ghim mật khẩu cũ (bước 5; spec R5.15, CV24).
