# 05 — Manifest dw.connector/v1 với khối delivery, trình kết nối email SMTP và lane xóa phiên bản bí mật cũ

Status: needs-triage
Blocked by: 04, .claude/plans/studio/tools-and-skills/issues/02-toolset-va-cong-cu-ghim.md, .claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md
Area: studio
Yêu cầu: R1.11, R1.12, R1.13, R1.16, R5.16, R5.17, R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7, R6.8, R7.1, R7.2, R7.3, R7.4, R7.5, R7.6, R7.7, R7.8, CV10, CV16, CV17, CV18, CV24, CV25, CV26, CV27, CV28

## Mục tiêu

Hành động của một trình kết nối là manifest `dw.connector/v1` biên dịch thành Đặc tả công cụ chạy qua Bộ
gọi ra ngoài, với đầu ra bọc là dữ liệu từ bên ngoài đúng một lần ở bộ bọc của executor; và `smtp@1.0.0`
cho phép quy trình gửi email tới lead qua hộp thư của chính công ty ở mức không khóa: tự động tối đa một lần mỗi
khóa, lần không rõ kết quả thì một người quyết (spec R6, R7; V4.30). Mỗi Hành động có hiệu ứng khai khối `delivery`,
mà W1 chỉ nhận ở mức không khóa (spec R6.5-R6.7; H-5); mỗi lời gọi qua Kết nối ghi phiên bản bí mật đã dùng vào
`credential_version` (spec R6.8; V4.35; H-10). Gộp từ B8a-connections connections-and-vault 12 và 16. Đường email P1
là SMTP chung (DO-48.1). Lane `credential_purge` xóa phiên bản bị thay 24 giờ sau lần xoay và phiên bản bị thu hồi vì
lộ ngay, không đụng `compromised_at` (spec R1.11-R1.13, R1.16; H-10, H-28).

## Việc cần làm

1. Model `ConnectorManifest` (`extra=forbid`), tệp `configs/connectors/<key>@<semver>.yaml`, checksum
   sha256; luật nạp từ chối: trường bí mật trong input, `max_retries` khác 0. Khối `delivery` của mỗi Hành động
   (spec R6.5-R6.7; ADR-0116 (Accepted) quyết 1; V4.30), bắt buộc khi `side_effect_level` khác `none`:
   `idempotency` (`mode` `provider_key` | `natural_key` | `none`, `field`, `retention_hours`), `reconciliation` (`mode`
   `lookup` | `none`, `action`, `ref_field`), `on_unknown` (`review` | `resend_same_key` | `lookup_then_resend`; vắng là
   `review`), enum đóng, không giá trị "coi như thất bại"; luật nạp: `resend_same_key` cần `idempotency.mode` khác
   `none`, `lookup_then_resend` cần `reconciliation.mode: lookup`, và ở W1 mọi `idempotency.mode` khác `none`,
   `reconciliation.mode` khác `none` hay `on_unknown` khác `review` bị từ chối (H-5); Đặc tả công cụ biên dịch mang
   `on_unknown` đã giải, mà ToolExecutor trả cùng `outcome_unknown` (runtime-hardening:R6.9).
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
message`, `data_location: VN`, `delivery` khai `idempotency: {mode: none}`, `reconciliation: {mode: none}`,
   `on_unknown: review`; `Message-ID` suy từ khóa chống lặp chỉ là gợi ý cho phía hộp thư nhận (V4.30; H-5).
5. `SmtpEgress`: địa chỉ ghim qua `resolve_checked`, TLS bắt buộc khi `settings.is_deployed` (465 hoặc
   STARTTLS trên 587), host qua danh mục hoặc danh sách máy chủ được phép; `run_mode` khác `live` → từ chối
   `egress_blocked:run_mode`, không mở kết nối SMTP (DO-26.1; W2 mới mở `test` cho Danh sách người nhận
   thử). Giới hạn tốc độ theo kết nối là W2, qua `RateLimiterPort` của usage-and-limits, không bộ đếm riêng
   (DO-49). `connection_usable` trả false với lý do `credential_revoked` (ticket 04 bước 2) → `SmtpEgress` từ chối
   với `credential_revoked`, không mở kết nối SMTP; mật khẩu lấy qua `platform.open_secret` không nêu phiên bản, tức
   phiên bản mới nhất chưa thu hồi, cửa không mở phiên bản đã thu hồi (spec R1.10, R1.14; V4.35). Kết quả có kiểu theo
   bảng phân loại của ticket 03 bước 9 (spec R7.6-R7.8): dừng trước dấu kết thúc dữ liệu của `DATA` →
   `NotDispatchedError`; trả lời 4yz, 5yz → `RejectedError` mang mã SMTP; đã gửi dấu kết thúc dữ liệu mà chưa nhận 250
   → `OutcomeUnknownError`, không gửi lại; `SmtpEgress` ghi nhận lúc dấu kết thúc dữ liệu được ghi ra socket, không suy
   từ loại ngoại lệ của thư viện SMTP.
6. Lane `credential_purge` (V4.20, V4.35; spec R1.11, R1.12, R1.13, R1.16; H-10, H-28): migration (revision hex
   ngẫu nhiên của alembic) tạo hàm `platform.purge_retired_secrets()` SECURITY DEFINER, không đối số (`search_path` cố
   định; REVOKE ALL FROM PUBLIC rồi GRANT EXECUTE cho `dw_app`, vai mà lane của worker dùng), theo tiền lệ
   `platform.prune_notifications()`, vì `dw_app` không có quyền nào trên `platform.secret_envelopes` (ticket 02): ở mọi
   công ty, xóa dòng có `replaced_at <= now() - interval '24 hours'` (phiên bản bị thay) và dòng có
   `revoked_at <= now()` mà `replaced_at` NULL (phiên bản bị thu hồi vì lộ, ticket 04 bước 2a); không đọc bản kê nào,
   vì không lượt chạy nào ghim phiên bản (ADR-0109 (Accepted) quyết 6); không xóa gì khác và không đụng
   `platform.connections`, nên `compromised_at` còn nguyên; trả một dòng mỗi chủ thể có dòng bị xóa (`tenant_id`,
   workspace sở hữu của chủ thể như AAD của ticket 02 bước 3 đọc: `owning_workspace_id` của `platform.connections`
   cho `connection_id`, của thành phần Nguồn dữ liệu cho `inbound_endpoint_id` khi cột đó đã có; loại và id chủ thể;
   các cặp `field`, `secret_version` đã xóa), không trả giá trị nào; ticket thêm một chủ thể sau ticket này nới hàm
   cùng lúc nới CHECK `num_nonnulls` (ADR-0115 (Accepted) quyết 1). Lane đăng ký ở composition root của worker với
   `interval_seconds` 3 600 (mỗi giờ) và, trong cùng giao dịch, ghi cho mỗi dòng trả về một sự kiện
   `secret.versions_purged` dựng bằng `lane_audit_event` (công ty và workspace của dòng đó, actor
   `system_actor("credential_purge")`, `details.actor` `system:credential_purge`, `details` chỉ loại và id chủ thể
   cùng các cặp trường, phiên bản) qua `lane_audit.append_across_tenants` (ADR-0011 (Accepted)); không ghi được sự
   kiện thì giao dịch lùi và không dòng nào bị xóa. Nhãn của action vào mảnh
   `configs/copy/audit_actions.d/connections-and-vault.yaml` (H-21; ADR-0122 (Accepted) quyết 6). Assert EXECUTE của
   `dw_app` trên hàm, và không quyền nào của `PUBLIC`, ở `test_privileges.py` (CLAUDE.md, Data model rules).
7. `credential_version` (spec R6.8; V4.35; H-10): migration (revision hex) thêm vào `platform.tool_executions` cột
   `credential_version jsonb` NULL với CHECK `credential_version IS NULL OR jsonb_typeof(credential_version) =
'object'`, chép nguyên văn mục Dữ liệu của spec; bảng vẫn chỉ thêm, `dw_app` không nhận UPDATE
   (runtime-hardening:R6.3). `ManifestActionHandler` đặt ánh xạ trường → `secret_version` mà `platform.open_secret` trả
   vào ngữ cảnh lời gọi ngay khi mở bí mật, trước lời gọi ra ngoài; ToolExecutor chép nó vào dòng kết thúc mà nó ghi
   theo kết quả có kiểu (runtime-hardening:R6.12), kể cả dòng `outcome_unknown` của một lỗi không có kiểu, và vào audit
   của lời gọi; lời gọi không qua Kết nối để NULL. Không giá trị bí mật nào vào cột hay audit (spec R1.2).

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
- [ ] R7.4 (CV18): K4 trên PostgreSQL thật: máy chủ SMTP giả trả 250, tiến trình chết trước dòng kết thúc, lời gọi
      `email.send` kế tiếp cùng khóa qua ToolExecutor → `outcome_unknown`, handler không chạy, máy chủ giả có đúng 1
      email; hai lời gọi cùng khóa nối tiếp, lần đầu `succeeded` → lần sau phát lại, vẫn 1 email; `Message-ID` suy từ
      khóa; gỡ ánh xạ của R7.6 để lần hết thời gian sau dữ liệu thành `NotDispatchedError` → wrapper thử lại và máy chủ
      giả nhận 2 email, test đỏ.
- [ ] R7.6 (CV18): máy chủ SMTP giả nhận dấu kết thúc dữ liệu rồi không trả lời tới hết thời gian → `SmtpEgress` ném
      `OutcomeUnknownError`, dòng kết thúc `outcome_unknown`, không lần gửi thứ hai; reset ngay sau dấu kết thúc dữ liệu
      → như trên.
- [ ] R7.7 (CV26): máy chủ giả ngắt sau `RCPT TO`, trước `DATA` → `NotDispatchedError`, không email nào; TLS bắt
      tay lỗi → `NotDispatchedError`.
- [ ] R7.8 (CV26): máy chủ giả trả 550 cho `RCPT TO` → `RejectedError` mang 550; trả 451 sau dấu kết thúc dữ liệu →
      `RejectedError` mang 451, không gửi lại; đổi ánh xạ 5yz thành `NotDispatchedError` → test bảng đỏ.
- [ ] R6.5 (CV27): Hành động `side_effect_level` khác `none` không có `delivery` → nạp từ chối, không Hành động nào
      đăng ký; `on_unknown: treat_as_failed` → schema từ chối; gỡ luật bắt buộc → test đỏ.
- [ ] R6.6 (CV27): `on_unknown: resend_same_key` với `idempotency.mode: none` → từ chối; `lookup_then_resend` với
      `reconciliation.mode: none` → từ chối; ở W1 `idempotency.mode: provider_key`, `reconciliation.mode: lookup` hay
      `on_unknown: resend_same_key` dù hợp lệ → từ chối; gỡ từng luật → ca của nó qua, test đỏ.
- [ ] R6.7 (CV27): khối `delivery` không có `on_unknown` → Đặc tả công cụ mang `review`; `smtp@1.0.0` nạp được với
      `none`, `none`, `review`; cho mặc định thành giá trị khác → test đỏ.
- [ ] R6.8 (CV24): lời gọi `email.send` gửi được → dòng kết thúc của `platform.tool_executions` có `credential_version`
      `{"password": 1}` và audit của lời gọi ghi 1; lời gọi kết thúc `outcome_unknown` → dòng đó cũng có
      `credential_version`; không giá trị canary nào trong cột hay audit; INSERT `credential_version` là một mảng → CHECK
      từ chối; bỏ bước chép cột ở ToolExecutor → test đỏ.
- [ ] R7.5 (CV10): `email.send` tới `SmtpEgress` ở `simulate` và ở `test` → `egress_blocked:run_mode`, máy
      chủ SMTP giả không nhận kết nối nào; `live` → gửi; gỡ bước kiểm chế độ ở `SmtpEgress` → test đỏ.
- [ ] R5.17 (CV24): thí nghiệm của V4.35: một lượt `live` đang chờ duyệt trước Bước `email.send`, đổi mật khẩu SMTP
      sang phiên bản 2, duyệt → email gửi bằng phiên bản 2 (máy chủ SMTP giả nhận lần xác thực bằng mật khẩu mới), dòng
      kết thúc và audit ghi `{"password": 2}`; cho `ManifestActionHandler` mở phiên bản nhỏ nhất còn dòng → lần xác thực
      bằng mật khẩu cũ, test đỏ.
- [ ] R5.16 (CV28): ba lượt `live` đang chờ duyệt trên cùng Kết nối SMTP, thu hồi vì lộ rồi lưu mật khẩu phiên bản 2,
      duyệt cả ba → mỗi lượt dừng ở lời gọi `email.send` kế tiếp với `credential_revoked`, máy chủ SMTP giả không nhận
      kết nối nào; một lượt xin sau lần thu hồi → gửi bằng phiên bản 2; gỡ kiểm `connection_usable` khỏi
      `ManifestActionHandler` → lượt cũ gửi bằng phiên bản 2, test đỏ.
- [ ] R1.11 (CV25): hai công ty, mỗi công ty có một Kết nối với `api_key` phiên bản 1 bị thay 25 giờ trước và một Kết
      nối có phiên bản bị thu hồi vì lộ một phút trước → một lần chạy lane xóa cả hai loại ở cả hai công ty, phiên bản
      đang dùng còn; `dw_app` DELETE thẳng một phong bì → `permission denied`; `test_privileges.py` thấy `dw_app` có
      EXECUTE trên `platform.purge_retired_secrets()` và `PUBLIC` không có; bỏ nhánh `replaced_at` NULL → phiên bản bị
      thu hồi vì lộ còn, test đỏ.
- [ ] R1.12 (CV25): phiên bản bị thay 23 giờ trước → giữ, lần chạy sau mốc 24 giờ → xóa; phiên bản đang dùng
      (`revoked_at` NULL) và bí mật ký cũ có `revoked_at` ở tương lai → giữ; bỏ điều kiện 24 giờ khỏi hàm → phiên bản bị
      thay 23 giờ trước bị xóa, test đỏ.
- [ ] R1.16 (CV28): Kết nối bị thu hồi vì lộ, lane xóa phiên bản bị thu hồi → `compromised_at` của Kết nối không đổi,
      và `connection_usable` của một lượt xin trước lần thu hồi vẫn trả `credential_revoked`; cho hàm đặt
      `compromised_at` NULL khi xóa phiên bản cuối (trigger của ticket 04 gỡ trong migration thử) → lượt cũ qua, test
      đỏ.
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
- spec: R1.11, R1.12, R1.13, R1.16, R5.16, R5.17, R6.5-R6.8, R7.4, R7.6-R7.8, CV18, CV24-CV28; ADR-0011 (Accepted);
  ADR-0109 (Accepted) quyết 6; ADR-0116 (Accepted) quyết 1; runtime-hardening:R6.3, runtime-hardening:R6.9,
  runtime-hardening:R6.12; ticket 02 (`revoked_at`, `replaced_at`, `platform.open_secret`, `platform.secret_status`),
  ticket 03 (bảng phân loại kết quả có kiểu), ticket 04 (lý do `credential_revoked` của `connection_usable`,
  `compromised_at`).
- `db/migrations/sql/0001_platform_baseline.sql:416-432`; spec: R6.8 (`platform.tool_executions` chưa có
  `credential_version`).

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
- 2026-10-25 (agent): lượt h, theo V4.30 của Đạt (mục 1, 2, 8) và H-5: bước 1 thêm khối `delivery` với luật nạp và
  phạm vi W1 (spec R6.5-R6.7, CV27); bước 4 cho `smtp@1.0.0` khai `none`, `none`, `review`; bước 5 cho `SmtpEgress` ném
  ba lỗi có kiểu theo bảng của ticket 03, đã gửi dấu kết thúc dữ liệu mà chưa nhận 250 là `outcome_unknown` (R7.6-R7.8);
  R7.4 thôi hứa "chính xác một email" mà hứa mức không khóa, thử bằng ca K4 và T. Theo V4.35, H-10, H-28: mật khẩu là
  phiên bản mới nhất chưa thu hồi, bước 7 thêm cột `credential_version` (R6.8), lane `credential_purge` thôi đọc bản kê,
  xóa phiên bản bị thay sau 24 giờ và phiên bản bị thu hồi vì lộ ngay, không đụng `compromised_at` (bước 6; R1.11,
  R1.12, R1.16); R5.15 của ticket này (lượt ghim phiên bản 1) thay bằng thí nghiệm của V4.35 (R5.17, R5.16). Không đổi
  cạnh: ticket đã đi sau runtime-hardening/01 qua tools-and-skills/02.
