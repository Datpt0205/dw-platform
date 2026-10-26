# Kết nối và kho bí mật: vault, egress client, OAuth, trình kết nối

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Lát Marketing cần gửi email và sau này gửi Zalo tới lead, mà muốn vậy công ty phải lưu được token và
mật khẩu của nhà cung cấp, và nền tảng phải gọi ra Internet mà không bao giờ lộ bí mật hay bị lừa gọi
vào mạng nội bộ. Spec này sở hữu Kho bí mật mã hóa phong bì dưới Khóa của công ty, một Bộ gọi ra ngoài
ghim địa chỉ đã kiểm, Kết nối dùng chung theo workspace với một quy tắc `connection_usable`, và Bản mô
tả trình kết nối biên dịch thành công cụ; W1 ship kho bí mật, egress client, kết nối dùng chung và một
đường email SMTP, cùng hồ sơ duyệt ứng dụng nhà cung cấp bắt đầu từ tuần đầu (ADR-0115 (Accepted),
ADR-0110 (Accepted), ADR-0116 (Accepted)).

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- `_is_private_address` chỉ chặn `is_private`, `is_loopback`, `is_link_local`, `is_reserved`,
  `is_unspecified`, không dùng `is_global` hay `is_multicast` và không đệ quy vào dạng IPv4 nhúng
  (`packages/python/dw_kernel/src/dw_kernel/net_guard.py:38-45`). Thiếu: lỗ CGNAT (`100.64.0.0/10`),
  multicast và `::ffff:` mà bộ gọi ra ngoài phải đóng.
- `ensure_allowed_outbound_url` chỉ kiểm URL một lần lúc gọi, không phân giải và ghim IP, không theo
  chuyển hướng (`packages/python/dw_kernel/src/dw_kernel/net_guard.py:49-75`); `outbound_allowed_hosts`
  đã có ở settings (`apps/api/src/dw_api/settings.py:206`, `apps/worker/src/dw_worker/settings.py:179`).
  Thiếu: không có bộ gọi ra ngoài ghim địa chỉ lúc mở kết nối.
- Nhiều `httpx.AsyncClient` thô nằm trong adapter
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/openai_compatible.py:61`,
  `packages/python/dw_connectors/src/dw_connectors/adapters/zalo_bot.py:121`,
  `packages/python/dw_knowledge/src/dw_knowledge/adapters/openai_embedding.py:68`). Ràng buộc: lưu lượng
  tới tenant phải đi qua một bộ gọi ra ngoài; các adapter vận hành nền tảng là ngoại lệ liệt kê.
- `settings.is_deployed` là cổng cho hành vi không được tới môi trường triển khai
  (`apps/api/src/dw_api/settings.py:323-325`, `:338`). Ràng buộc: LocalDevKms và TLS bắt buộc của egress
  gác trên nó, không gác trên `profile == "production"`.
- Baseline nền tảng định nghĩa `platform.worker_runs` và các bảng khác nhưng không có
  `platform.secret_envelopes`, `platform.connections` hay `platform.oauth_flows`
  (`db/migrations/sql/0001_platform_baseline.sql:447`). Thiếu: kho bí mật và kết nối chưa tồn tại.
- `scripts/backup_postgres.sh` chỉ sao lưu Postgres và chép off-box qua S3
  (`scripts/backup_postgres.sh:2-3`). Thiếu: khi thêm OpenBao, sao lưu kho khóa và restore drill phải mở
  rộng để giải mã lại một bí mật sau khôi phục.

## Mục tiêu

### R1 — Kho bí mật mã hóa phong bì dưới khóa của công ty

Mọi Thông tin bí mật của một công ty nằm mã hóa dưới Khóa của công ty, không bao giờ ở dạng rõ và không
bao giờ rời Kho bí mật ra một đường ra nào; không lượt chạy nào ghim phiên bản bí mật, nên mỗi lời gọi mở phiên
bản mới nhất chưa thu hồi; xoay một bí mật thay phiên bản cũ, còn thu hồi vì lộ là một việc riêng dừng mọi lượt chưa
xong của Kết nối; phiên bản bị thay bị xóa 24 giờ sau lần xoay, phiên bản bị thu hồi vì lộ bị xóa ngay (YC61;
ADR-0115 (Accepted) quyết 1; V4.20; V4.35).

- R1.1 Kho bí mật PHẢI lưu mỗi Thông tin bí mật dưới dạng phong bì AES-256-GCM với một khóa dữ liệu
  riêng mỗi bí mật, bọc bởi Khóa của công ty qua `KmsPort`.
- R1.2 Thông tin bí mật PHẢI không xuất hiện trong phản hồi API, trạng thái lượt chạy, checkpoint, đối
  số công cụ, bản kê lượt chạy, trace, log hay Nhật ký kiểm toán.
- R1.3 NẾU `dw_app` đọc, sửa hay xóa thẳng `platform.secret_envelopes`, THÌ PostgreSQL PHẢI từ chối với
  `permission denied` và không trả dòng nào.
- R1.4 NẾU một phong bì được giải mã với công ty, workspace sở hữu, chủ thể, trường hay phiên bản bí mật
  (`secret_version`, không đổi khi bọc lại khóa dữ liệu) khác với lúc mã hóa, THÌ Kho bí mật PHẢI giải mã lỗi và
  không trả giá trị rõ.
- R1.5 NẾU một dòng mang `kek_ref` của công ty khác với công ty trong ngữ cảnh, THÌ Kho bí mật PHẢI từ
  chối và ghi audit `secret.key_mismatch`.
- R1.6 KHI lane `offboarding` xuất dữ liệu một công ty, danh sách bảng xuất PHẢI không gồm
  `platform.secret_envelopes`.
- R1.7 NẾU một lệnh UPDATE đổi `owning_workspace_id` của một Kết nối, THÌ PostgreSQL PHẢI từ chối lệnh đó và
  không đổi dòng nào, vì AAD của mọi phong bì của Kết nối gắn workspace sở hữu (R1.4).
- R1.8 NẾU một phong bì trỏ tới một chủ thể thuộc công ty khác với `tenant_id` của phong bì, THÌ PostgreSQL PHẢI
  từ chối lệnh ghi bằng khóa ngoại ghép và không ghi.
- R1.9 KHI một giá trị mới của một trường bí mật được lưu (xoay), Kho bí mật PHẢI ghi, trong cùng giao dịch, cho mọi
  phiên bản cũ có `revoked_at` NULL của cùng chủ thể và trường, `replaced_at` bằng thời điểm của giao dịch và
  `revoked_at` bằng thời điểm đó, hay bằng thời điểm đó cộng 24 giờ khi trường là `signing_secret` (V4.20; V4.35).
- R1.10 NẾU một lần mở bí mật nêu một `secret_version` đã thu hồi (`revoked_at` đã qua) hay không còn dòng nào, hay một
  trường không còn phiên bản nào chưa thu hồi, THÌ Kho bí mật PHẢI trả `credential_revoked` và không trả giá trị rõ
  (V4.20, V4.35: đóng khi thiếu).
- R1.11 KHI lane `credential_purge` chạy, lane `credential_purge` PHẢI xóa mọi phiên bản bí mật có `replaced_at` từ
  24 giờ trước trở về trước, và mọi phiên bản có `revoked_at` đã qua mà `replaced_at` NULL, tức bị thu hồi vì lộ
  (R1.15), vì không lượt chạy nào ghim phiên bản (V4.35; H-10).
- R1.12 NẾU một phiên bản bí mật chưa thu hồi (`revoked_at` NULL hay chưa tới), hay bị thay chưa đủ 24 giờ, THÌ lane
  `credential_purge` PHẢI giữ nguyên dòng đó.
- R1.13 KHI lane `credential_purge` xóa phiên bản bí mật của một chủ thể, lane `credential_purge` PHẢI ghi trong cùng
  giao dịch một sự kiện `secret.versions_purged` của chính lane ở công ty và workspace sở hữu của chủ thể, không
  mang giá trị bí mật nào (ADR-0011 (Accepted)).
- R1.14 KHI một lời gọi ra ngoài mở bí mật của một trường của Kết nối, Kho bí mật PHẢI mở phiên bản có `secret_version`
  lớn nhất mà chưa thu hồi và trả số phiên bản đó cùng giá trị, vì bản kê lượt chạy ghim id kết nối, không ghim phiên
  bản bí mật (ADR-0109 (Accepted) quyết 6; V4.35; H-10).
- R1.15 KHI một Kết nối bị thu hồi vì lộ (`POST /api/v1/connections/{id}/revoke-credentials`, do một người giữ
  `connections.manage` với tới workspace sở hữu của Kết nối; Đạt, Q-h3), Kho bí mật PHẢI ghi trong một giao dịch `revoked_at` bằng thời điểm của giao dịch cho mọi phiên
  bản của mọi trường của Kết nối có `revoked_at` NULL hay ở tương lai, và `platform.connections.compromised_at` bằng
  cùng thời điểm, cùng audit `connection.credentials_revoked` (V4.35; H-28).
- R1.16 KHI lane `credential_purge` xóa phiên bản bị thu hồi vì lộ của một Kết nối, lane `credential_purge` PHẢI giữ
  nguyên `compromised_at` của Kết nối đó, để lượt được xin trước lần thu hồi vẫn bị từ chối sau lần dọn (R5.16; H-28;
  failure-modes #7).

### R2 — Khóa khi triển khai, xoay khóa và xóa bằng hủy khóa

Khi triển khai, Khóa của công ty nằm trong OpenBao Transit, tự mở niêm phong và xoay mỗi 90 ngày; giải mã
vẫn đóng khi dịch vụ khóa hỏng; offboarding hủy khóa, và Xóa bằng hủy khóa có hiệu lực khi bản sao lưu kho
khóa cũ nhất còn giữ khóa đó hết hạn (YC61; D14; DO-47.1; ADR-0115 (Accepted) quyết 1).

- R2.1 ĐỐI VỚI profile triển khai, `KmsPort` PHẢI bọc và mở khóa dữ liệu qua OpenBao Transit.
- R2.2 NẾU `settings.is_deployed` là đúng và `DW_KMS_PROVIDER` là `local`, THÌ api và worker PHẢI từ chối
  khởi động với `RuntimeError`.
- R2.3 KHI lane `offboarding` xóa một công ty, lane `offboarding` PHẢI gọi hủy Khóa của công ty ở bước
  cuối, để giải mã một phong bì của công ty đó sau đó trả `kms_key_destroyed`.
- R2.4 NẾU dịch vụ khóa không sẵn sàng, THÌ lời gọi giải mã PHẢI trả `kms_unavailable` và không ghi dòng
  rõ nào.
- R2.5 KHI OpenBao khởi động lại ở profile triển khai, route `GET /api/v1/ready` PHẢI báo `kms` sẵn sàng mà
  không cần ai mở niêm phong bằng tay.
- R2.6 KHI một Khóa của công ty đủ 90 ngày (UTC) kể từ lần xoay trước, OpenBao Transit PHẢI xoay khóa đó
  sang phiên bản mới mà phong bì bọc bằng phiên bản cũ vẫn giải mã được.
- R2.7 Job sao lưu PHẢI giữ bản sao lưu kho khóa OpenBao, cả bản trên máy lẫn bản off-box, trong một thời
  hạn ghi trong cấu hình và không dài hơn thời hạn giữ bản sao lưu `dw`.
- R2.8 KHI diễn tập khôi phục chạy, diễn tập khôi phục PHẢI khôi phục cả cơ sở dữ liệu `dw` lẫn kho khóa
  OpenBao từ cùng một lượt sao lưu và giải mã được một bí mật canary.

### R3 — Bộ gọi ra ngoài ghim địa chỉ, chặn địa chỉ không toàn cầu

Mọi lời gọi ra ngoài của lưu lượng tới tenant đi qua một bộ gọi ghim địa chỉ đã kiểm, chỉ tới địa chỉ
Internet toàn cầu trong danh sách được phép, kể cả sau chuyển hướng hay đổi DNS; thêm một Máy chủ được phép cần
người thứ hai; và mỗi lời gọi kết thúc bằng một kết quả có kiểu mà ToolExecutor và wrapper nút đọc, không bao giờ tự
gửi lại một lời gọi không rõ kết quả (YC41, YC63, YC34; D11; ADR-0115 (Accepted) quyết 5, 6; ADR-0111 (Accepted) quyết
3; V4.30).

- R3.1 KHI mở một kết nối TCP ra ngoài, Bộ gọi ra ngoài PHẢI phân giải host một lần, ghim địa chỉ IP đã
  kiểm cho kết nối đó, và xác minh TLS theo hostname.
- R3.2 NẾU địa chỉ đích không phải địa chỉ Internet toàn cầu — gồm private, loopback, link-local, CGNAT
  `100.64.0.0/10`, multicast, và các dạng IPv4 nhúng `::ffff:`, 6to4, Teredo, NAT64 `64:ff9b::/96` —
  THÌ Bộ gọi ra ngoài PHẢI từ chối với `egress_blocked:address` và không gửi byte nào.
- R3.3 NẾU một chuyển hướng trỏ tới host ngoài danh sách được phép hoặc tới địa chỉ không toàn cầu, THÌ
  Bộ gọi ra ngoài PHẢI kiểm lại, từ chối và không gửi tiếp.
- R3.4 KHI một chuyển hướng đổi origin, Bộ gọi ra ngoài PHẢI bỏ header `Authorization` và `Cookie`
  trước khi gửi bước kế.
- R3.5 TRONG KHI lượt chạy ở chế độ khác `live` (`simulate`, hay `test` mà W1 chưa mở), NẾU một lời gọi
  mang purpose khác `model` và không đến từ một Hành động khai chỉ đọc hay `simulate_safe`, kể cả purpose
  `mcp` và `oauth`, THÌ Bộ gọi ra ngoài PHẢI từ chối với `egress_blocked:run_mode` và không gọi nhà cung cấp.
- R3.6 Test kiến trúc PHẢI đỏ khi một module ngoài danh sách adapter vận hành tạo `httpx.AsyncClient`
  trực tiếp.
- R3.7 NẾU đích của một purpose khác `connector` và `oauth` không nằm trong Máy chủ được phép của công
  ty, THÌ Bộ gọi ra ngoài PHẢI từ chối với `egress_blocked:host_not_allowed` và không gửi byte nào.
- R3.8 NẾU một mẫu Máy chủ được phép đặt wildcard trên một hậu tố công cộng, hoặc là một IP literal, THÌ
  API quản trị PHẢI trả 422 và không thêm dòng.
- R3.9 KHI người giữ `integrations.admin` gửi `POST /api/v1/egress/allowed-hosts` hợp lệ, API quản trị PHẢI
  trả 202 với một yêu cầu phê duyệt không lượt chạy loại `egress.allowed_host` có `required_scope`
  `integrations.admin`, mà chưa thêm dòng nào vào `platform.egress_allowed_hosts`.
- R3.10 NẾU người quyết một yêu cầu `egress.allowed_host` là người đã gửi nó, THÌ luồng phê duyệt PHẢI trả
  409 `conflict` với `details.reason_code` `second_person_required` và không thêm dòng nào.
- R3.11 KHI một yêu cầu `egress.allowed_host` được người thứ hai duyệt, handler `egress.allowed_host.decided`
  PHẢI thêm đúng một dòng `platform.egress_allowed_hosts` cùng audit `egress.allowlist.added` đứng tên người
  quyết, `details.lane` là `outbox`, trong một giao dịch.
- R3.12 NẾU một `POST /api/v1/egress/allowed-hosts` hợp lệ tới khi không có người `active` nào khác người gửi giữ
  `integrations.admin` với tới workspace đang làm việc của người gửi, THÌ API quản trị PHẢI trả 409 `conflict` với
  `details.reason_code` `no_checker_available` và không mở yêu cầu phê duyệt nào.
- R3.13 KHI một lời gọi qua Bộ gọi ra ngoài kết thúc, Bộ gọi ra ngoài PHẢI trả kết quả `succeeded`, hay ném đúng một
  trong ba lỗi có kiểu mà `dw_agent_runtime` khai (runtime-hardening/01): `NotDispatchedError`, `RejectedError` mang
  mã, `OutcomeUnknownError` (ADR-0115 (Accepted) quyết 6; V4.30).
- R3.14 NẾU một lời gọi dừng trước khi byte đầu tiên của yêu cầu được ghi ra socket (phân giải, kết nối, bắt tay TLS,
  mọi `egress_blocked`, `credential_revoked`), THÌ Bộ gọi ra ngoài PHẢI ném `NotDispatchedError` mang mã của lần dừng.
- R3.15 NẾU một lời gọi HTTP hết thời gian hay bị reset sau khi byte đầu tiên của yêu cầu đã được ghi, hay nhận một
  trạng thái 5xx, THÌ Bộ gọi ra ngoài PHẢI ném `OutcomeUnknownError` và không tự gửi lại lời gọi đó.
- R3.16 NẾU một lời gọi HTTP nhận một trạng thái 4xx, THÌ Bộ gọi ra ngoài PHẢI ném `RejectedError` mang trạng thái đó
  làm mã và không tự gửi lại.

### R4 — Bộ kiểm chữ ký webhook

Một module thuần kiểm chữ ký cho mọi cửa nhận sự kiện, từ chối sai chữ ký và lệch giờ (YC42;
ADR-0115 (Accepted) quyết 6).

- R4.1 KHI nhận một thông điệp có chữ ký Standard Webhooks 1.0 đúng và dấu thời gian trong cửa sổ ±5
  phút, Bộ kiểm chữ ký PHẢI trả `verified`.
- R4.2 NẾU chữ ký sai, dấu thời gian lệch quá ±5 phút, hay chữ ký thiếu, THÌ Bộ kiểm chữ ký PHẢI trả
  `rejected` kèm lý do và không lặp lại giá trị đã nhận.
- R4.3 ĐỐI VỚI nhà cung cấp dùng token tĩnh, Bộ kiểm chữ ký PHẢI so token theo thời gian hằng định và
  trả `rejected` khi token sai.
- R4.4 TRONG KHI khóa ký đang xoay, Bộ kiểm chữ ký PHẢI nhận chữ ký của cả khóa cũ còn hạn (tới `revoked_at` của
  nó, 24 giờ sau lần xoay; V4.20) lẫn khóa mới.

### R5 — Kết nối dùng chung theo workspace

Quản trị viên thêm, kiểm, tắt và thu hồi Kết nối dùng chung của một workspace, một quy tắc
`connection_usable` quyết mọi lượt dùng, tắt hay thu hồi có hiệu lực trước lần gọi ra ngoài kế tiếp, xoay bí mật
của Kết nối không dừng lượt nào mà lượt đang chờ gửi bằng phiên bản mới, thu hồi vì lộ dừng mọi lượt được xin lúc hay
trước lần thu hồi ở lời gọi ra ngoài kế tiếp, và bật lại cần người thứ hai (YC62; DO-48; D11; ADR-0115 (Accepted)
quyết 2; V4.20; V4.35).

- R5.1 KHI người giữ `connections.manage` ở workspace đang làm việc tạo một Kết nối, API kết nối PHẢI
  lưu bí mật vào Kho bí mật, tạo dòng Kết nối với Connection status `pending` hoặc `active`, và audit
  `connection.created`.
- R5.2 KHI người gọi đọc một Kết nối, API kết nối PHẢI không trả giá trị bí mật nào và hiện trường bí
  mật đã lưu là "Đã cấu hình".
- R5.3 NẾU người gọi ở công ty khác gọi một route kết nối với id của công ty này, THÌ API kết nối PHẢI
  trả 404 và không gọi nhà cung cấp.
- R5.4 NẾU một lượt chạy ở workspace khác dùng một Kết nối có Phạm vi dùng chung `workspace` của workspace
  không phải của nó, THÌ `connection_usable` PHẢI trả false và lời gọi bị từ chối ở phát hành và ở Bộ
  gọi ra ngoài.
- R5.5 KHI quản trị viên tắt hoặc thu hồi một Kết nối, `connection_usable` PHẢI trả false cho mọi lượt
  chạy trước lời gọi ra ngoài kế tiếp.
- R5.6 NẾU một lệnh đổi Connection status từ `revoked` sang `active`, THÌ PostgreSQL PHẢI từ chối lệnh
  đó.
- R5.7 KHI quản trị viên mở trang Kết nối, trang `/studio/connections` PHẢI hiện tên, trình kết nối, tài
  khoản ngoài, Phạm vi dùng chung, Connection status bằng chữ và "Được dùng bởi".
- R5.8 NẾU người gọi xóa một Kết nối còn thành phần đang dùng, THÌ API kết nối PHẢI trả 409
  `connection_in_use` và không xóa.
- R5.9 NẾU chủ thể của ngữ cảnh (chủ thể mà lượt chạy hành động thay, hay người đề xuất giá trị Điểm gắn)
  không giữ `connections.use` ở workspace của lượt chạy hay của giá trị đang duyệt, THÌ `connection_usable`
  PHẢI trả false, nên lời gọi bị từ chối lúc duyệt giá trị Điểm gắn, lúc nhận lượt chạy và ở Bộ gọi ra ngoài.
- R5.10 KHI người giữ `connections.manage` gửi `POST /api/v1/connections/{id}/enable` cho một Kết nối
  `disabled`, API kết nối PHẢI trả 202 với một yêu cầu phê duyệt không lượt chạy loại `connections.enable` có
  `required_scope` `connections.manage`, mà Connection status vẫn là `disabled`.
- R5.11 NẾU người quyết một yêu cầu `connections.enable` là người đã gửi nó, THÌ luồng phê duyệt PHẢI trả 409
  `conflict` với `details.reason_code` `second_person_required` và không đổi Connection status.
- R5.12 KHI một yêu cầu `connections.enable` được người thứ hai duyệt, handler `connections.enable.decided`
  PHẢI đổi Connection status từ `disabled` sang `active` cùng audit `connection.enabled` đứng tên người quyết,
  `details.lane` là `outbox`, trong một giao dịch.
- R5.13 NẾU một `POST /api/v1/connections/{id}/enable` tới khi không có người `active` nào khác người gửi giữ
  `connections.manage` với tới workspace sở hữu của Kết nối, THÌ API kết nối PHẢI trả 409 `conflict` với
  `details.reason_code` `no_checker_available`, không mở yêu cầu phê duyệt nào và giữ Connection status
  `disabled`.
- R5.14 NẾU `connection_usable` được hỏi với một `purpose` khác `tool`, THÌ `connection_usable` PHẢI trả false.
- R5.15 NẾU, trước lời gọi ra ngoài của một lượt chạy, một trường bí mật của Kết nối không còn phiên bản nào chưa thu
  hồi (`revoked_at` NULL hay ở tương lai), kể cả khi không còn dòng nào, THÌ `connection_usable` PHẢI trả false với lý
  do `credential_revoked`, nên Bộ gọi ra ngoài và `SmtpEgress` từ chối với `credential_revoked` và không gửi byte nào
  (V4.20; V4.35: đóng khi thiếu).
- R5.16 NẾU `compromised_at` của Kết nối khác NULL và lượt chạy được xin lúc hay trước thời điểm đó (`created_at` của
  dòng `platform.worker_runs` không sau `compromised_at`), THÌ `connection_usable` PHẢI trả false với lý do
  `credential_revoked` trước lời gọi ra ngoài kế tiếp của lượt, kể cả khi Kết nối đã có phiên bản mới chưa thu hồi
  (V4.35; H-28).
- R5.17 KHI một lượt chạy được xin trước một lần xoay bí mật của Kết nối gọi ra ngoài sau lần xoay đó, mà Kết nối chưa
  bị thu hồi vì lộ sau khi lượt được xin, `connection_usable` PHẢI trả true khi các điều kiện khác của R5 đạt, và lời
  gọi dùng phiên bản mới (R1.14; V4.35).

### R6 — Bản mô tả trình kết nối biên dịch thành công cụ

Hành động của một trình kết nối là manifest `dw.connector/v1` biên dịch thành Đặc tả công cụ chạy qua Bộ
gọi ra ngoài, với đầu ra bọc là dữ liệu từ bên ngoài, và mỗi Hành động có hiệu ứng khai trong khối `delivery` mức
bảo đảm mà nhà cung cấp cho phép: có khóa, có tra cứu hay không khóa (YC41, YC48, YC64; ADR-0116 (Accepted) quyết 1, 2;
V4.30).

- R6.1 KHI nạp một Bản mô tả trình kết nối `dw.connector/v1`, bộ nạp PHẢI biên dịch mỗi Hành động thành
  một Đặc tả công cụ lớp nền tảng có input và output JSON Schema, Mức tác động và `max_retries` là 0.
- R6.2 NẾU một Bản mô tả khai một trường bí mật trong input, hoặc `max_retries` khác 0, THÌ bộ nạp PHẢI
  từ chối và không đăng ký Hành động nào.
- R6.3 KHI một Hành động trả kết quả, `ManifestActionHandler` PHẢI trả kết quả đã kiểm output schema cho
  `ToolExecutor` mà không tự bọc hay cắt, vì chỉ bộ bọc của tools-and-skills:R5.1 bọc và cắt đầu ra công
  cụ (YC48).
- R6.4 KHI chạy một Hành động, `ManifestActionHandler` PHẢI lấy Kết nối qua `RunBindingsPort` theo tên
  Điểm gắn, kiểm `connection_usable`, rồi gọi qua Bộ gọi ra ngoài.
- R6.5 NẾU một Hành động có `side_effect_level` khác `none` thiếu khối `delivery`, THÌ bộ nạp PHẢI từ chối Bản mô tả và
  không đăng ký Hành động nào; khối có `idempotency` (`mode` `provider_key` | `natural_key` | `none`, `field`,
  `retention_hours`), `reconciliation` (`mode` `lookup` | `none`, `action`, `ref_field`) và `on_unknown` (`review` |
  `resend_same_key` | `lookup_then_resend`), không có giá trị "coi như thất bại" nào (V4.30; failure-modes #7).
- R6.6 NẾU một khối `delivery` khai `on_unknown: resend_same_key` mà `idempotency.mode` là `none`, hay
  `on_unknown: lookup_then_resend` mà `reconciliation.mode` khác `lookup`, hay ở W1 khai `idempotency.mode` khác
  `none`, `reconciliation.mode` khác `none` hay `on_unknown` khác `review`, THÌ bộ nạp PHẢI từ chối Bản mô tả và không
  đăng ký Hành động nào (V4.30; H-5).
- R6.7 KHI một khối `delivery` không khai `on_unknown`, bộ nạp PHẢI biên dịch Hành động với `on_unknown: review`
  (V4.30).
- R6.8 KHI một Hành động gọi ra ngoài qua một Kết nối, ToolExecutor PHẢI ghi phiên bản bí mật mà lời gọi đã mở (R1.14)
  vào cột `credential_version` của dòng kết thúc trong `platform.tool_executions` và vào audit của lời gọi, kể cả khi
  lời gọi kết thúc `outcome_unknown` (V4.35; H-10).

### R7 — Trình kết nối email SMTP

Quy trình gửi được email tới lead qua kết nối hộp thư SMTP của chính công ty, như một Hành động khai
trong Bản mô tả trình kết nối, ở mức không khóa: tự động tối đa một lần mỗi khóa, lần không rõ kết quả thì một người
quyết (YC41, YC64; DO-48; ADR-0116 (Accepted) quyết 2; V4.30).

- R7.1 KHI một quy trình gọi Hành động `email.send` của trình kết nối `smtp@1.0.0`, `SmtpEgress` PHẢI
  gửi email qua kết nối SMTP của công ty với mật khẩu lấy từ Kho bí mật.
- R7.2 NẾU `settings.is_deployed` là đúng và kết nối SMTP không bật TLS (465 hoặc STARTTLS trên 587), THÌ
  `SmtpEgress` PHẢI từ chối và không gửi.
- R7.3 NẾU host SMTP phân giải về một địa chỉ không toàn cầu, THÌ `SmtpEgress` PHẢI từ chối lúc mở kết
  nối.
- R7.4 KHI hai lời gọi `email.send` mang cùng khóa chống lặp đi qua ToolExecutor, kể cả khi lần đầu kết thúc
  `outcome_unknown` hay tiến trình chết sau khi máy chủ SMTP trả 250, trình kết nối `smtp@1.0.0` PHẢI tự động gửi
  tối đa một email cho khóa đó, còn lần gửi không rõ kết quả thì một người quyết (workflow-engine/08); `Message-ID`
  suy từ khóa chỉ là gợi ý cho phía hộp thư nhận (mức không khóa của YC41; V4.30; H-5).
- R7.5 TRONG KHI lượt chạy ở chế độ khác `live`, NẾU một lời gọi `email.send` tới `SmtpEgress`, THÌ
  `SmtpEgress` PHẢI từ chối với `egress_blocked:run_mode` và không mở kết nối SMTP.
- R7.6 NẾU `SmtpEgress` đã gửi dấu kết thúc dữ liệu của lệnh `DATA` mà chưa nhận trả lời 250 (hết thời gian, reset),
  THÌ `SmtpEgress` PHẢI ném `OutcomeUnknownError` và không gửi lại email đó (ADR-0115 (Accepted) quyết 6; V4.30).
- R7.7 NẾU một lời gọi `email.send` dừng trước khi dấu kết thúc dữ liệu của `DATA` được gửi, THÌ `SmtpEgress` PHẢI ném
  `NotDispatchedError` mang mã của lần dừng (V4.30).
- R7.8 NẾU máy chủ SMTP trả một mã 4yz hay 5yz cho một lệnh của lời gọi, kể cả trả lời sau dấu kết thúc dữ liệu, THÌ
  `SmtpEgress` PHẢI ném `RejectedError` mang mã SMTP đó và không gửi lại (RFC 5321 mục 4.2; V4.30).

## Trong phạm vi

- Bảng và cột ở mục Dữ liệu; route ở mục API; màn hình ở mục Màn hình.
- Mã: `KmsPort`, `LocalDevKms` (chỉ ngoài profile triển khai), `OpenBaoTransitKms`, `SecretStore` và kiểu
  `Secret`; `EgressPort`, `EgressClient`, `PinnedNetworkBackend`, mở rộng `net_guard` cho địa chỉ không
  toàn cầu; module thuần `dw_connectors.webhooks` với `SignatureVerifier`; `ConnectorManifest` và bộ biên
  dịch sang Đặc tả công cụ, `ManifestActionHandler`; khối `delivery` của `dw.connector/v1` với luật nạp của R6.5-R6.7,
  W1 chỉ nhận `none`, `none`, `review` (H-5); kết quả có kiểu của Bộ gọi ra ngoài và `SmtpEgress` qua ba lỗi có kiểu
  mà `dw_agent_runtime` khai ở runtime-hardening/01 (R3.13-R3.16, R7.6-R7.8); cột `credential_version` của
  `platform.tool_executions`, mà spec này là chủ vì Bộ gọi ra ngoài phân giải bí mật (R6.8; H-10); route thu hồi vì lộ
  cùng `compromised_at` của `platform.connections` (R1.15, R1.16, R5.16; H-28); `SmtpEgress`;
  `connection_usable(connection, context, purpose)`
  một hàm, mà W1 chỉ gọi với `purpose='tool'` (ADR-0115 (Accepted) quyết 2; R5.14);
  `ConnectionDependentsPort` (spec này khai; tenant-config đáp ứng, đọc `studio.dependencies` cộng giá trị
  Bộ giá trị gắn đã duyệt trong `platform.config_versions`; workflow-engine và agent-builder không cài);
  lane `credential_rewrap`; lane `credential_purge` (mỗi giờ) cùng hàm SECURITY DEFINER không đối số
  `platform.purge_retired_secrets()` mà lane gọi, xóa phiên bản bị thay 24 giờ sau lần xoay và phiên bản bị thu hồi vì
  lộ ngay, không đụng `compromised_at` (R1.11, R1.12, R1.13, R1.16; V4.35; H-10, H-28).
- Khóa quyền, đăng ký vào Danh mục quyền trong migration của ticket dùng nó (quy ước của tenant-rbac/01):
  `connections.read`, `connections.manage`, `connections.use` ở ticket 04; `integrations.admin` ở ticket 03.
  Câu INSERT nêu mọi cột NOT NULL có lúc đó, gồm `risk` của tenant-rbac/01 và `tenant_grantable` của
  tenant-rbac/02, nên cả hai ticket chờ tenant-rbac/02. Tên giữ như ADR-0115 (Accepted); tiền tố `connections.`
  và `integrations.` nằm trong `FORBIDDEN_SCOPE_PREFIXES` của truy cập người vận hành (tenant-rbac:R1.5).
- Phê duyệt không lượt chạy `egress.allowed_host` (ticket 03) và `connections.enable` (ticket 04): cả hai vào
  `strict_approval_prefixes` bằng `|=` ở API và worker, mỗi loại một handler `.decided` đăng ký ở composition
  root của worker; trước khi mở yêu cầu, API hỏi `platform.checker_candidates` của tenant-rbac/02 và từ chối
  `no_checker_available` khi không còn ai khác người gửi (R3.12, R5.13); tắt kết nối và xóa Máy chủ được phép
  vẫn một người cộng audit (D11).
- Audit: `connection.created`, `connection.updated`, `connection.disabled`, `connection.enabled`,
  `connection.revoked`, `connection.tested`, `connection.credentials_revoked` (R1.15), `secret.key_mismatch`,
  `secret.versions_purged` (của lane
  `credential_purge`), `egress.allowlist.added`, `egress.allowlist.removed`.
- Outbox: `connection.status_changed` v1.

## Ngoài phạm vi

| Việc                                                                                                                                                                                                                                                                                           | Vì sao                                                                                                                                                                                                                                                                                 | Chủ                                                   |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| R4: cửa nhận Data Hub, ép lược đồ, định danh nguồn ≥128 bit, chống trùng, không tạo lượt chạy khi từ chối                                                                                                                                                                                      | YC42 phần endpoint; module này chỉ cấp Bộ kiểm chữ ký                                                                                                                                                                                                                                  | workflow-triggers                                     |
| W2: giới hạn tốc độ, Retry-After, backoff, cầu dao, công tắc tắt egress                                                                                                                                                                                                                        | `from_briefs` B8a 06; qua `RateLimiterPort` của usage-and-limits, không bộ giới hạn riêng; mất Valkey thì xô mỗi tiến trình ở hạn mức chia số replica (DO-49)                                                                                                                          | usage-and-limits đợt sau (W2)                         |
| W2: smokescreen là lớp thứ hai trên mạng riêng, bắt buộc trước đích HTTP đầu tiên do công ty định nghĩa                                                                                                                                                                                        | DO-47.2: `validate_for_profile` từ chối profile triển khai bật đích HTTP của công ty khi thiếu `DW_EGRESS_PROXY_URL`; host SMTP của P1 chỉ ghim địa chỉ (R7.3); chỉ ship sau spike 21 (FOG-25, FOG-26) và khi host đã nâng (D14)                                                       | connections-and-vault đợt sau (W2)                    |
| W2: mức có khóa hay tra cứu của khối `delivery`: `idempotency.mode` `provider_key` và `natural_key` (khóa gửi nhà cung cấp là mã băm của khóa `wf:`, giống nhau ở mọi lần thử), `reconciliation.mode: lookup`, `on_unknown` `resend_same_key` và `lookup_then_resend`, lane `studio_reconcile` | H-5: tác động ra ngoài duy nhất của W1 là SMTP, không khóa và không tra cứu, nên R6.6 từ chối các giá trị này tới khi trình kết nối đầu tiên khai khóa hay tra cứu; mục `compensation` không vào v1 vì bù là một Bước tường minh trong làn lỗi, không có bên đọc (V4.30)               | connections-and-vault đợt sau (W2); workflow-engine   |
| W2: bộ điều phối OAuth và làm mới token một luồng                                                                                                                                                                                                                                              | YC65; `from_briefs` B8a 10, 11; P1 chỉ kết nối dùng chung, chưa có luồng cấp quyền                                                                                                                                                                                                     | connections-and-vault đợt sau (W2)                    |
| W2: định tuyến sự kiện ứng dụng nhà cung cấp theo tài khoản ngoài; cùng Page hay OA do hai công ty nối thì gửi tới cả hai                                                                                                                                                                      | YC97; `from_briefs` B8a 13 (phần định tuyến); cần cửa `provider_app` của workflow-triggers; DO-48.2: không bật trước ý kiến luật sư (compliance-pdpl/02, câu 3 của discovery/18)                                                                                                       | connections-and-vault đợt sau (W2); workflow-triggers |
| W2: trình kết nối Zalo OA và ZNS; Meta Lead Ads                                                                                                                                                                                                                                                | YC97; `from_briefs` B8a 14, 15; cần OAuth và duyệt ứng dụng                                                                                                                                                                                                                            | connections-and-vault đợt sau (W2)                    |
| W2: gửi email qua Gmail của công ty bằng ứng dụng Google nội bộ của khách, như một Hành động khai trong Bản mô tả trình kết nối                                                                                                                                                                | YC107; N8; DO-20 (c): nền tảng không giữ ứng dụng Google nào (ticket 01 bước 4); cần bộ điều phối OAuth (YC65); P1 gửi qua SMTP (R7)                                                                                                                                                   | connections-and-vault đợt sau (W2)                    |
| W2: lane gửi tin đã xếp hàng, hỏi công tắc Tắt khẩn cấp trước khi gọi nhà cung cấp (hợp đồng agent-lifecycle:R8.4)                                                                                                                                                                             | Đạt giao chủ lane cho spec này ngày 24/10/2026; tin chỉ được hoãn và xếp hàng từ W2, nên W1 chỉ có lane giả trong test của agent-lifecycle                                                                                                                                             | connections-and-vault đợt sau (W2)                    |
| W3: trình kết nối TikTok Lead Generation                                                                                                                                                                                                                                                       | N8: rút khỏi phần W2 của YC97; chỉ làm sau một ticket khám phá kiểm API (FOG-82)                                                                                                                                                                                                       | connections-and-vault đợt sau (W3); marketing-pilot   |
| Trình kết nối Google Sheets                                                                                                                                                                                                                                                                    | N8: không yêu cầu nào của thí điểm cần nó                                                                                                                                                                                                                                              | không làm ở v1; ứng viên W3                           |
| W2: kết nối cá nhân và Ủy quyền dùng kết nối; ứng dụng OAuth riêng của tổ chức                                                                                                                                                                                                                 | DO-48.1 chốt P1 chỉ dùng chung theo workspace; `from_briefs` B8a 17, 18                                                                                                                                                                                                                | connections-and-vault đợt sau (W2)                    |
| W2: webhook gửi đi theo Standard Webhooks; mở rộng danh mục trình kết nối                                                                                                                                                                                                                      | YC24; `from_briefs` B8a 19, 20; đọc từ outbox, cần endpoint đã đăng ký; DO-58: mặc định sự kiện mỏng, dữ liệu cá nhân chỉ khi bật cho từng endpoint, có audit, áp Đã ẩn và Lộ trình dữ liệu                                                                                            | connections-and-vault đợt sau (W2)                    |
| W2: chế độ `test` gửi thật tới Danh sách người nhận thử                                                                                                                                                                                                                                        | DO-26.1: W1 chỉ mở `simulate`; tới khi đó R3.5 và R7.5 từ chối ở mọi chế độ khác `live`, trừ purpose `model` và Hành động chỉ đọc (R3.5)                                                                                                                                               | tenant-config đợt sau (W2); connections-and-vault     |
| W3: giải mã chỉ trong dịch vụ `dw-egress`; manifest tầng tenant; BYOK (sau v1, DO-47.1) và HSM                                                                                                                                                                                                 | `from_briefs` B8a 21, 22, 23; cần tách dịch vụ egress và PKCS#11                                                                                                                                                                                                                       | connections-and-vault đợt sau (W3)                    |
| Sàn gửi tin kiểm đồng ý ở executor cho Hành động `effect_class: message`                                                                                                                                                                                                                       | ADR-0124 (Accepted); executor là một cửa, sổ đồng ý là của compliance-pdpl                                                                                                                                                                                                             | tools-and-skills; compliance-pdpl                     |
| Khung loại công cụ, kiểm JSON Schema trong executor, bọc đầu ra không tin cậy                                                                                                                                                                                                                  | ADR-0116 (Accepted); spec này cấp Bộ gọi ra ngoài và Kết nối cho loại `connector_action`                                                                                                                                                                                               | tools-and-skills                                      |
| Chế độ chạy do máy chủ đặt và `run_mode` trên ngữ cảnh lượt chạy                                                                                                                                                                                                                               | ADR-0111 (Accepted); Bộ gọi ra ngoài và `SmtpEgress` đọc `run_mode` để từ chối theo R3.5 và R7.5                                                                                                                                                                                       | tenant-config                                         |
| Cấu hình model của tenant (BYOM qua model proxy); khóa model là bí mật                                                                                                                                                                                                                         | ADR-0118 (Accepted); khóa model lưu trong Kho bí mật này; W2: kết nối model hỏi `connection_usable` với `purpose='model'` (ADR-0118 (Accepted) quyết 3), giá trị mà R5.14 từ chối tới đợt đó; lời gọi model của công ty ghi phiên bản khóa đã dùng trên `platform.usage_events` (H-25) | model-connections đợt sau (W2)                        |

## Dữ liệu

Mọi bảng: RLS ENABLE và FORCE theo tenant, grant cùng migration, tên ràng buộc theo `NAMING_CONVENTION`,
revision id hex ngẫu nhiên của alembic. Cả ba bảng là bảng toàn tenant (ADR-0100 (Accepted) quyết 5; DO-01):
không `workspace_id`, mỗi bảng một dòng có lý do trong `_TENANT_WIDE_ON_PURPOSE` của `test_rls_coverage.py`
(studio-skeleton:R9.1). Lý do: `secret_envelopes` là dòng con mà chủ thể của nó mang workspace;
`connections` và `egress_allowed_hosts` có tầm dùng vượt workspace theo thiết kế (D1). Workspace sở hữu nằm ở
`owning_workspace_id`, mà phân quyền đọc và RLS không đọc, với FK ghép `(tenant_id, owning_workspace_id)` tới
`platform.workspaces (tenant_id, id)` (`uq_workspaces_tenant_id_id` của org-and-principals/01).

- `platform.secret_envelopes`: `id` uuid; `tenant_id` NOT NULL FK `platform.tenants` ON DELETE CASCADE;
  `connection_id` uuid NULL với FK ghép `(tenant_id, connection_id)` tới `platform.connections (tenant_id, id)`
  ON DELETE CASCADE, vì phong bì là dòng con của chủ thể, loại trừ với chủ thể khác qua CHECK
  `num_nonnulls(...) = 1`; mỗi chủ thể mới (ADR-0115 (Accepted) quyết 1) là một cột NULL có FK ghép
  `(tenant_id, <cột chủ thể>)` tới UNIQUE `(tenant_id, id)` của bảng chủ thể, ON DELETE CASCADE, cộng CHECK đó nới
  rộng và một UNIQUE của cột đó (dưới đây), thêm trong migration của ticket thêm chủ thể: `inbound_endpoint_id`
  (FK ghép tới `studio.inbound_endpoints (tenant_id, id)` ON DELETE CASCADE) ở workflow-triggers/02; FK một cột thì
  không đủ, vì kiểm khóa ngoại không qua RLS nên một phong bì của công ty này trỏ được tới chủ thể của công ty
  khác (R1.8); `field text NOT NULL`, tên trường bí mật của chủ thể (`api_key`, `password`,
  `signing_secret`); `secret_version integer NOT NULL`, phiên bản của bí mật: `platform.put_secret` ghi giá trị
  mới của (chủ thể, trường) thành một dòng với số kế tiếp, không sửa bản mã của dòng cũ mà chỉ ghi `revoked_at` của
  nó, còn lane `credential_rewrap` không đổi `secret_version`; `revoked_at timestamptz NULL`, thời điểm từ đó phiên
  bản bị từ chối (V4.20), NULL ở phiên bản đang dùng, không vào AAD: `platform.put_secret` ghi nó cho mọi phiên bản
  cũ có `revoked_at` NULL của cùng (chủ thể, trường) trong giao dịch ghi phiên bản mới, bằng thời điểm của giao dịch
  (phiên bản bị thay không được lời gọi nào sau đó mở, như mọi trường của một Kết nối), hay bằng thời điểm đó cộng 24
  giờ khi trường là `signing_secret` (khoảng chồng của lần xoay, như bí mật ký của Nguồn dữ liệu ở
  workflow-triggers/02), và không dời `revoked_at` đã ghi, nên xoay hai lần trong 24 giờ không kéo dài hạn của phiên
  bản đầu; một quy tắc trong hàm cho mọi chủ thể (R1.9), nên ticket thêm chủ thể không sửa nó; lần thu hồi vì lộ
  (`platform.revoke_connection_secrets`, dưới đây) ghi nó bằng thời điểm của giao dịch cho mọi phiên bản của Kết nối có
  `revoked_at` NULL hay ở tương lai (R1.15); `replaced_at timestamptz NULL`, thời điểm của lần xoay đã thay phiên bản,
  do `platform.put_secret` ghi cùng `revoked_at` trên cùng các dòng và không hàm nào khác ghi, nên một phiên bản có
  `revoked_at` mà `replaced_at` NULL là phiên bản bị thu hồi vì lộ; lane `credential_purge` đọc nó để xóa phiên bản bị
  thay 24 giờ sau lần xoay và phiên bản bị thu hồi vì lộ ngay (R1.11; H-10); UNIQUE
  `(tenant_id, subject_kind, subject_id, field, secret_version)`, mà vì đúng một cột chủ thể khác NULL nên là một
  UNIQUE `(tenant_id, <cột chủ thể>, field, secret_version)` cho mỗi cột chủ thể,
  `(tenant_id, connection_id, field, secret_version)` ở ticket 02, dẫn đầu bằng hai cột của FK ghép nên cũng là
  chỉ mục của FK đó và của FK `tenant_id`; `alg text NOT NULL` CHECK (`aes-256-gcm`);
  `nonce bytea NOT NULL` CHECK độ dài 12; `kek_ref text NOT NULL`; `ciphertext bytea NOT NULL` CHECK độ dài
  ≤ 64 KiB;
  `wrapped_data_key bytea NOT NULL`, khóa dữ liệu riêng của phong bì bọc bởi Khóa của công ty, giữ cạnh
  `ciphertext` (ADR-0115 (Accepted) quyết 1), cột duy nhất lane `credential_rewrap` ghi lại;
  `kek_version int NOT NULL`, phiên bản Khóa của công ty đã bọc `wrapped_data_key`, lane `credential_rewrap` tăng
  nó và nó không vào AAD; `created_at`, `updated_at timestamptz NOT NULL`. AAD của phong bì dựng từ công ty của
  ngữ cảnh, workspace sở hữu của chủ thể, cột chủ thể, `field` và `secret_version` (ticket 02 bước 3), nên bảng
  không có cột gợi ý AAD nào. `REVOKE ALL FROM dw_app`; chỉ các hàm SECURITY DEFINER `platform.put_secret`,
  `platform.open_secret`, `platform.secret_status`, `platform.delete_secret`, `platform.revoke_connection_secrets`
  (lấy công ty từ `app.tenant_id`, không nhận tham số công ty; hàm thứ năm là của lần thu hồi vì lộ, ticket 04) và
  `platform.purge_retired_secrets()` không đối số của lane `credential_purge` (R1.11, ticket 05) có EXECUTE cho
  `dw_app`. Một phiên bản đã thu hồi là một dòng có `revoked_at` đã qua; một `secret_version` không còn dòng nào (xóa
  qua `platform.delete_secret` hay lane `credential_purge`) được coi như đã thu hồi (đóng khi thiếu):
  `platform.secret_status` trả `secret_version`, `revoked_at` và `replaced_at` của từng phiên bản còn dòng, không trả
  giá trị, `connection_usable` đọc chúng ở đó (R5.15, ticket 04 bước 2); `platform.open_secret` mở phiên bản bên gọi
  nêu (bộ kiểm chữ ký của workflow-triggers/02, trong khoảng chồng 24 giờ), hay khi không nêu thì phiên bản có
  `secret_version` lớn nhất chưa thu hồi, trả số phiên bản đã mở cùng giá trị (R1.14), và không mở phiên bản đã thu hồi
  hay thiếu (R1.10). Vì `dw_app` không có quyền nào trên bảng, lane `offboarding`
  không xuất (R1.6) và không xóa thẳng nó, và bảng được tạo sau khi studio-skeleton/01 đo `_PLATFORM_PREDATING`,
  nên bảng có một dòng `STUDIO_EXCLUSIONS` của test phủ offboarding (studio-skeleton:R4.3) với lý do "REVOKE ALL với
  `dw_app`; xóa theo FK CASCADE từ chủ thể (`platform.connections`, `studio.inbound_endpoints`) khi lane xóa chủ
  thể, và qua `platform.delete_secret` cho một bí mật lẻ" (ticket 02 bước 6).
- `platform.connections`: `id` uuid; `tenant_id` NOT NULL; UNIQUE `(tenant_id, id)` (`uq_connections_tenant_id_id`),
  đích của FK ghép từ `platform.secret_envelopes`; `owning_workspace_id` NOT NULL, FK ghép
  `(tenant_id, owning_workspace_id)` tới `platform.workspaces` ON DELETE RESTRICT, có index, và không đổi sau khi
  tạo: trigger `platform.guard_connection_owning_workspace()` từ chối mọi UPDATE đổi cột đó (R1.7), vì AAD của
  phong bì gắn nó (ADR-0115 (Accepted) quyết 1), nên đổi workspace sở hữu, nếu có, là mã hóa lại mọi phong bì của
  Kết nối dưới AAD mới chứ không phải UPDATE cột; `connector_key text NOT NULL`,
  `connector_major int NOT NULL`; `share_scope text NOT NULL` CHECK (`owner`, `workspace`,
  `workspace_subtree`); `external_account text`; `status text NOT NULL` CHECK (`pending`, `active`,
  `needs_reauth`, `disabled`, `revoked`), không DEFAULT; `scopes text[] NOT NULL DEFAULT '{}'`;
  `last_used_at timestamptz` NULL; `compromised_at timestamptz` NULL, không DEFAULT, thời điểm của lần thu hồi vì lộ
  gần nhất, chỉ `platform.revoke_connection_secrets` ghi (grant cột của `dw_app` không có UPDATE trên nó), trigger
  `platform.guard_connection_compromised_at()` từ chối mọi UPDATE đặt nó về NULL hay lùi nó về trước giá trị đã có,
  và lane `credential_purge` không đụng nó, nên dấu thu hồi không mất khi vật liệu bí mật bị xóa (R1.16, R5.16; H-28;
  failure-modes #7); `created_by`, `created_at`, `updated_at timestamptz NOT NULL`;
  trigger `platform.guard_connection_status()` cấm `revoked → active`; index danh sách
  `(tenant_id, created_at DESC, id DESC)`; partial unique một kết nối `active` cho mỗi
  `(tenant_id, connector_key, external_account)`. Trigger `touch_updated_at` nhường giá trị statement
  nêu (CLAUDE.md). `dw_app` có DELETE trên bảng, để route xóa (R5.8) và lane `offboarding` xóa Kết nối như bảng
  thường, và FK CASCADE xóa phong bì của nó (ticket 02 bước 2).
- `platform.egress_allowed_hosts`: `id`, `tenant_id`, `owning_workspace_id` (FK ghép
  `(tenant_id, owning_workspace_id)` tới `platform.workspaces` ON DELETE RESTRICT, có index, như
  `platform.connections`); `host_pattern text` CHECK
  (`^(\*\.)?[a-z0-9.-]+$`, ≤ 253 ký tự), kiểm Public Suffix List (wildcard không đặt trên hậu tố công
  cộng), không IP literal; `ports int[] NOT NULL DEFAULT '{443}'`; `purpose text` CHECK (`http_tool`,
  `mcp`, `webhook`, `model`, `any`); `note`, `created_by`, `created_at`; UNIQUE
  `(tenant_id, host_pattern, purpose)`. Dòng chỉ được thêm bởi handler `egress.allowed_host.decided` (R3.11).
- `platform.tool_executions` (bảng của baseline, chỉ thêm; runtime-hardening/01 đặt CHECK `status`): thêm
  `credential_version jsonb` NULL với CHECK `credential_version IS NULL OR jsonb_typeof(credential_version) = 'object'`,
  ánh xạ tên trường bí mật sang `secret_version` mà lời gọi đã mở (ví dụ `{"password": 2}`), NULL ở lời gọi không qua
  Kết nối; ghi một lần trên dòng kết thúc, nên bảng vẫn chỉ thêm và `dw_app` không nhận UPDATE (runtime-hardening:R6.3);
  không bao giờ mang giá trị bí mật (R1.2, R6.8; H-10; ticket 05).

## API

- `GET`, `POST /api/v1/connections`; `GET`, `PATCH`, `DELETE /api/v1/connections/{id}`;
  `POST /api/v1/connections/{id}/test`, `.../disable`, `.../enable`;
  `GET /api/v1/connections/{id}/dependents`. Quyền `connections.read`, `connections.manage` (ticket 04 đăng
  ký); trường bí mật `writeOnly`; `Idempotency-Key` cho `POST`; DELETE còn phụ thuộc → 409
  `connection_in_use`. `.../enable` trả 202 kèm id yêu cầu `connections.enable` (R5.10), hay 409
  `no_checker_available` khi không có người thứ hai (R5.13); `.../disable` có hiệu lực ngay;
  `POST /api/v1/connections/{id}/revoke-credentials` thu hồi vì lộ mọi phiên bản bí mật của Kết nối và ghi
  `compromised_at` (R1.15), có hiệu lực ngay, `connections.manage` với tới workspace sở hữu, một người (Q-h3); xoay một bí mật là `PATCH` với giá
  trị mới của trường (R1.9).
- `GET /api/v1/connectors` (`connections.read`), đọc lớp nền tảng.
- `GET`, `POST`, `DELETE /api/v1/egress/allowed-hosts` (`integrations.admin`, ticket 03 đăng ký): `POST` trả
  202 kèm id yêu cầu `egress.allowed_host` (R3.9), hay 409 `no_checker_available` khi không có người thứ hai
  (R3.12); `DELETE` có hiệu lực ngay.
- Lỗi theo vỏ problem+json của ADR-0108 (Accepted); `details.reason_code`: `connection_in_use`,
  `connection_disabled`, `credential_revoked` (R1.10, R5.15), `egress_blocked`, `kms_unavailable`,
  `kms_key_destroyed`, `secret_key_mismatch`, `no_checker_available`, `second_person_required`. Id của công ty khác
  ở mọi route → 404. Người quyết bị từ
  chối nhận mã theo ADR-0104 (Accepted) quyết 11: người gửi tự quyết → 409 `conflict` với `details.reason_code`
  `second_person_required`, không giữ `required_scope` → 404.

## Màn hình

- `/studio/connections`: antd `Table` (tên, trình kết nối, tài khoản ngoài, Phạm vi dùng chung,
  Connection status bằng chữ, lần dùng gần nhất); `Drawer` thêm kết nối (API key, basic); trang chi tiết
  (sức khỏe, mã lỗi gần nhất, phạm vi đã cấp, "Được dùng bởi"); xác nhận xóa nêu tên kết nối và danh
  sách phụ thuộc; người thiếu `connections.manage` thấy nút bị tắt kèm lý do, và API vẫn chặn; nút "Bật lại"
  gửi yêu cầu cho người thứ hai duyệt, và trang chi tiết hiện yêu cầu đang chờ; nút "Thu hồi vì lộ" gọi route của
  R1.15 sau một xác nhận nói rằng mọi lượt chưa xong của kết nối sẽ dừng ở lời gọi ra ngoài kế tiếp, và trang chi tiết
  hiện thời điểm thu hồi gần nhất (ticket 07).
- `/studio/egress-hosts`: màn quản trị Máy chủ được phép (`integrations.admin`); thêm một máy chủ tạo yêu cầu
  chờ người thứ hai duyệt, xóa có hiệu lực ngay.

## Kiểm soát

| #    | Kiểm soát                                                                                     | Yêu cầu                                      | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ---- | --------------------------------------------------------------------------------------------- | -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CV1  | Phong bì gắn danh tính bằng AAD                                                               | R1.4, R1.7                                   | Chép phong bì sang kết nối khác cùng công ty hay công ty khác, sang trường khác của cùng kết nối, sang `secret_version` khác, hay sang chủ thể `inbound_endpoint_id` (ca này chạy ở workflow-triggers/02, nơi thêm cột) → giải mã lỗi; bọc lại khóa dữ liệu (`kek_version` tăng) → vẫn giải mã; UPDATE `owning_workspace_id` của một Kết nối → trigger từ chối, dòng không đổi, phong bì vẫn giải mã; gỡ AAD khỏi `SecretStore`, đưa `kek_version` vào AAD, hay gỡ trigger `platform.guard_connection_owning_workspace()` → test đỏ                                                                                                                                                                                                                                                                                        |
| CV2  | Một cửa cơ sở dữ liệu, `dw_app` không đọc thẳng                                               | R1.3, R1.6                                   | `SELECT * FROM platform.secret_envelopes` bằng `dw_app` → permission denied; catalog export của offboarding không liệt kê `secret_envelopes`; offboarding một công ty có Kết nối → mọi phong bì của công ty đó bị xóa theo CASCADE, phong bì của công ty khác còn; bỏ dòng `STUDIO_EXCLUSIONS` của bảng → test phủ offboarding (studio-skeleton:R4.3) đỏ, nêu tên bảng                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| CV3  | Khóa suy từ công ty của ngữ cảnh                                                              | R1.5                                         | Dòng mang `kek_ref` của công ty khác → từ chối, audit `secret.key_mismatch`; bỏ kiểm `kek_ref` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| CV4  | Bí mật không rò ra response, trạng thái, trace, log, audit                                    | R1.2                                         | Mock nhà cung cấp vọng header và key trong body lỗi → 0 lần xuất hiện ở checkpoint, `tool_executions`, audit, span, log; tắt che → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| CV5  | LocalDevKms chỉ chạy ngoài profile triển khai                                                 | R2.2                                         | `DW_KMS_PROVIDER=local` với profile `uat` → `RuntimeError` lúc khởi động; gỡ `validate_for_profile` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| CV6  | Xóa bằng hủy khóa khi offboarding                                                             | R2.3                                         | Sau offboarding, giải mã một phong bì từ dump trước đó → `kms_key_destroyed`; bỏ bước hủy khóa → giải mã vẫn được, test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| CV7  | Egress chặn địa chỉ không toàn cầu lúc ghim                                                   | R3.1, R3.2                                   | Resolver giả trả IP công khai lần đầu, IP nội bộ lần sau → bị chặn lúc kết nối; `100.64.0.1`, `224.0.0.1`, `::ffff:169.254.169.254` → chặn; gỡ ghim → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| CV8  | Chuyển hướng kiểm lại, bỏ header xác thực khi đổi origin                                      | R3.3, R3.4                                   | Redirect tới `http://169.254.169.254/` hay host ngoài danh sách → chặn, không gửi; mock origin khác không thấy `Authorization`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| CV9  | Không có client HTTP thô                                                                      | R3.6                                         | Thêm `httpx.AsyncClient(` vào một module mới ngoài danh sách → test kiến trúc đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| CV10 | Chế độ khác `live` không gọi ra ngoài, trừ `model` và Hành động chỉ đọc                       | R3.5, R7.5                                   | Gọi egress với `run_mode` `simulate` và `test`, purpose `connector`, `http_tool`, `webhook`, `mcp` và `oauth` → `egress_blocked:run_mode`; lời gọi của một Hành động khai chỉ đọc ở `simulate` và purpose `model` → qua; `email.send` tới `SmtpEgress` ở `test` → từ chối, không mở kết nối SMTP; gỡ bước kiểm chế độ ở một trong hai lớp → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| CV11 | Bộ kiểm chữ ký từ chối sai chữ ký, lệch giờ, token sai                                        | R4.2, R4.3                                   | Vector Standard Webhooks qua; sửa một byte trượt; dấu thời gian lệch quá 5 phút trượt; token tĩnh sai trượt; gỡ kiểm dấu thời gian → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| CV12 | API kết nối không trả bí mật                                                                  | R5.2                                         | Duyệt mọi schema 2xx của router kết nối: không trường bí mật; `GET` sau khi tạo không chứa giá trị canary                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| CV13 | Cách ly tenant cho kết nối                                                                    | R5.3                                         | Công ty B gọi `GET`, `PATCH`, `DELETE`, `test` với id của công ty A → 404; mock nhà cung cấp không nhận gì                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| CV14 | Phạm vi workspace của kết nối, quyền dùng kết nối và mục đích dùng                            | R5.4, R5.9, R5.14                            | Lượt chạy ở một workspace dùng kết nối `workspace` của workspace khác → từ chối ở phát hành và ở Bộ gọi ra ngoài; chủ thể không giữ `connections.use` ở workspace của lượt chạy → từ chối lúc duyệt giá trị Điểm gắn, lúc nhận lượt và ở Bộ gọi ra ngoài; `purpose='model'` hay một giá trị lạ → false; gỡ kiểm workspace, kiểm `connections.use` hay kiểm `purpose` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| CV15 | Tắt hay thu hồi có hiệu lực trước lần gọi sau                                                 | R5.5, R5.6                                   | Kết nối `disabled` → `connection_disabled` ở egress; `revoked → active` bị trigger từ chối; gỡ kiểm trong `connection_usable` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| CV16 | Manifest không có input nhạy cảm, không tự thử lại                                            | R6.2                                         | Manifest có `api_key` trong input → nạp từ chối; `max_retries: 2` → nạp từ chối; gỡ luật nạp → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| CV17 | Đầu ra Hành động bọc và cắt đúng một lần, ở bộ bọc của executor                               | R6.3                                         | Chạy Hành động qua `ToolExecutor` với đầu ra chứa `</tool_output><system>` → model nhận `&lt;/tool_output&gt;`, không bao giờ `&amp;lt;`; `ManifestActionHandler` trả kết quả thô; thêm bọc vào handler → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| CV18 | SMTP ghim địa chỉ, TLS khi triển khai, tự động tối đa một email mỗi khóa                      | R7.2, R7.3, R7.4                             | Host SMTP phân giải về IP nội bộ → chặn; không TLS khi triển khai → từ chối; K4 trên PostgreSQL thật: máy chủ SMTP giả trả 250, tiến trình chết trước dòng kết thúc, lời gọi kế tiếp cùng khóa → `outcome_unknown`, máy chủ giả có đúng 1 email; T: máy chủ giả nhận dữ liệu rồi không trả 250 tới hết thời gian → `outcome_unknown`, không lần gửi thứ hai; gỡ ánh xạ của R7.6 để lần hết thời gian sau `DATA` thành `NotDispatchedError` → wrapper thử lại và máy chủ giả nhận 2 email, test đỏ                                                                                                                                                                                                                                                                                                                          |
| CV19 | Chỉ tới Máy chủ được phép, wildcard không trên hậu tố công cộng                               | R3.7, R3.8                                   | Host ngoài danh sách (purpose `http_tool`) → `egress_blocked:host_not_allowed`; `*.com.vn` → 422; `203.0.113.5` → 422; gỡ kiểm danh sách → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| CV20 | Diễn tập khôi phục thấy kho khóa; bản sao lưu kho khóa không sống lâu hơn bản sao lưu dữ liệu | R2.7, R2.8                                   | Diễn tập chỉ khôi phục `dw` → giải mã canary thất bại, test đỏ; hạn giữ bản sao lưu kho khóa dài hơn `BACKUP_KEEP_DAYS` của `dw` → kiểm cấu hình đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| CV21 | Bật lại một kết nối cần người thứ hai                                                         | R5.10, R5.11, R5.12, R5.13                   | `POST .../enable` → 202, Connection status vẫn `disabled`, egress vẫn `connection_disabled`; người gửi tự duyệt → 409 `second_person_required`, status không đổi; người không giữ `connections.manage` quyết → 404; người thứ hai giữ `connections.manage` duyệt → `active`, audit `connection.enabled` đứng tên người đó với `details.lane` `outbox`; `PATCH` mang `status: active` không đổi status; chỉ người gửi giữ `connections.manage` với tới workspace của Kết nối → 409 `no_checker_available`, không yêu cầu nào, status vẫn `disabled`; bỏ `connections.enable` khỏi tiền tố nghiêm hay gỡ kiểm người duyệt → test đỏ                                                                                                                                                                                          |
| CV22 | Thêm một Máy chủ được phép cần người thứ hai                                                  | R3.9, R3.10, R3.11, R3.12                    | `POST /api/v1/egress/allowed-hosts` → 202, không dòng nào, đích đó vẫn `egress_blocked:host_not_allowed`; người gửi tự duyệt → 409 `second_person_required`; người thứ hai giữ `integrations.admin` duyệt → đúng một dòng, audit `egress.allowlist.added` đứng tên người đó; handler chạy lại cùng quyết định → vẫn một dòng; chỉ người gửi giữ `integrations.admin` → 409 `no_checker_available`, không yêu cầu nào, không dòng nào; bỏ `egress.allowed_host` khỏi tiền tố nghiêm hay gỡ kiểm người duyệt → test đỏ                                                                                                                                                                                                                                                                                                       |
| CV23 | Phong bì chỉ trỏ tới chủ thể cùng công ty                                                     | R1.8                                         | `platform.put_secret` dưới `app.tenant_id` của công ty A với `connection_id` của công ty B → lỗi khóa ngoại (23503), không dòng nào; xóa một Kết nối → mọi phong bì của nó xóa theo (CASCADE); đổi FK ghép thành FK một cột `connection_id` trong migration thử → lần ghi chéo công ty thành công, test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| CV24 | Lời gọi dùng phiên bản mới nhất chưa thu hồi; xoay không dừng lượt đang chờ; đóng khi thiếu   | R1.9, R1.10, R1.14, R5.15, R5.17, R6.8       | Một lượt đang chờ duyệt, đổi mật khẩu SMTP sang phiên bản 2, duyệt → email gửi bằng phiên bản 2, dòng kết thúc của `platform.tool_executions` có `credential_version` `{"password": 2}` và audit của lời gọi ghi 2; `platform.open_secret` với phiên bản 1 → `credential_revoked`, không giá trị; xóa mọi dòng của trường rồi gọi → `credential_revoked`, máy chủ giả không nhận gì; xoay `signing_secret` lần nữa trước khi 24 giờ của lần đầu hết → phiên bản 1 giữ `revoked_at` của lần đầu; gỡ bước ghi `revoked_at` khỏi `platform.put_secret` (phiên bản 1 vẫn mở được), cho `platform.open_secret` mở phiên bản nhỏ nhất thay lớn nhất, gỡ nhánh "không còn phiên bản chưa thu hồi" khỏi `connection_usable` hay bỏ cột khỏi lần ghi dòng kết thúc → test của lớp đó đỏ, mỗi lớp hỏi thẳng chứ không qua lớp sau nó |
| CV25 | Lane xóa phiên bản bị thay sau 24 giờ và phiên bản bị thu hồi vì lộ ngay                      | R1.11, R1.12, R1.13                          | Phiên bản bị thay 25 giờ trước → lane xóa, một sự kiện `secret.versions_purged` đứng tên `system:credential_purge` ở workspace sở hữu của Kết nối; bị thay 23 giờ trước → giữ; bị thu hồi vì lộ một phút trước → xóa; phiên bản đang dùng và bí mật ký cũ chưa tới `revoked_at` → giữ; bỏ điều kiện 24 giờ khỏi `platform.purge_retired_secrets()` → phiên bản bị thay 23 giờ trước bị xóa, hay bỏ nhánh `replaced_at` NULL → phiên bản bị thu hồi vì lộ còn sau lần chạy, test đỏ                                                                                                                                                                                                                                                                                                                                         |
| CV26 | Egress trả kết quả có kiểu, không tự gửi lại lời gọi không rõ kết quả                         | R3.13, R3.14, R3.15, R3.16, R7.6, R7.7, R7.8 | Máy chủ HTTP giả: từ chối kết nối → `NotDispatchedError`; nhận yêu cầu rồi reset → `OutcomeUnknownError`, máy giả có đúng 1 yêu cầu; 503 → `OutcomeUnknownError`; 422 → `RejectedError` mang 422; `egress_blocked:address` → `NotDispatchedError`; máy chủ SMTP giả: ngắt trước dấu kết thúc dữ liệu → `NotDispatchedError`; trả 550 sau dữ liệu → `RejectedError` mang 550; gỡ phân loại theo byte đã ghi, để reset sau khi gửi thành `NotDispatchedError`, hay cho egress thử lại lần reset → máy giả nhận 2 yêu cầu, test đỏ                                                                                                                                                                                                                                                                                            |
| CV27 | Khối `delivery` bắt buộc, luật nạp, W1 chỉ không khóa                                         | R6.5, R6.6, R6.7                             | Hành động `side_effect_level` `low` không có `delivery` → nạp từ chối; `on_unknown: resend_same_key` với `idempotency.mode: none` → từ chối; `lookup_then_resend` với `reconciliation.mode: none` → từ chối; `on_unknown: treat_as_failed` → từ chối theo schema; ở W1 `idempotency.mode: provider_key` → từ chối; vắng `on_unknown` → Đặc tả công cụ mang `review`; `smtp@1.0.0` nạp với `none`, `none`, `review`; gỡ luật nạp nào → ca của nó qua, test đỏ                                                                                                                                                                                                                                                                                                                                                               |
| CV28 | Thu hồi vì lộ dừng mọi lượt được xin trước nó, dấu thu hồi không mất khi dọn                  | R1.15, R1.16, R5.16                          | Một lượt đang chờ, thu hồi vì lộ rồi lưu phiên bản 2 → lời gọi ra ngoài kế tiếp của lượt → `credential_revoked`, máy chủ giả không nhận gì; lượt xin sau lần thu hồi → gửi bằng phiên bản 2; lane `credential_purge` xóa phiên bản bị thu hồi rồi lượt cũ gọi tiếp → vẫn `credential_revoked`; `dw_app` UPDATE `compromised_at` về NULL hay lùi giá trị → bị từ chối; công ty B gọi route với id của công ty A → 404, không phiên bản nào đổi; người không giữ `connections.manage` với tới workspace sở hữu gọi route → 403, không phiên bản nào đổi; một người giữ khóa gọi → có hiệu lực ngay, không chờ người thứ hai; gỡ nhánh `compromised_at` khỏi `connection_usable`, hay gỡ trigger `platform.guard_connection_compromised_at()` rồi cho lane đặt `compromised_at` NULL → lượt cũ gửi bằng phiên bản 2, test đỏ  |

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (ghi ở Comments của
  ticket).
- Kết quả FOG-25 (tương đương Transit, mở niêm phong không người) có ở `## Answer` của discovery/21 và mục
  Open của ADR-0115 (Accepted) trước khi OpenBao ship (ticket 06).
- `make ci && make test-integration` xanh; `reviewing-feature-security` và `reviewing-deployment-security`
  đã chạy cho từng ticket có route, image hay URL ra ngoài; `.claude/plans/studio.md` ghi lát W1 đã xong
  và bảng trạng thái duyệt ứng dụng nhà cung cấp.

## Phụ thuộc

- `.claude/plans/studio/studio-skeleton/issues/04-chinh-sach-compose-dich-vu-moi.md`: chính sách thêm
  dịch vụ compose mới (OpenBao ở ticket 06, sau là smokescreen) và trivy; `studio-skeleton/03`: seam web và
  allowlist antd cho `/studio/connections` (ticket 07; V4.31).
- `.claude/plans/studio/runtime-hardening/issues/01-toolexecutor-gianh-luot-khong-cua-sau.md`: ba lỗi có kiểu
  `NotDispatchedError`, `RejectedError`, `OutcomeUnknownError` khai ở `dw_agent_runtime`, mà Bộ gọi ra ngoài (ticket 03) và `SmtpEgress` (ticket 05) ném, và nhật ký lần gửi `dispatched` cùng cách ToolExecutor ghi dòng kết thúc theo
  kết quả có kiểu, lỗi không có kiểu sau `dispatched` thành `outcome_unknown` (runtime-hardening:R6.9,
  runtime-hardening:R6.11, runtime-hardening:R6.12); ticket 03 đi sau ticket đó qua tenant-config/03. Bên đọc kết quả
  có kiểu ở phía quy trình là wrapper nút (workflow-engine:R4.23) và điểm chờ `outcome_review` của
  `.claude/plans/studio/workflow-engine/issues/08-tac-dong-khong-ro-ket-qua.md`, ticket chờ ticket 03.
- `.claude/plans/studio/foundations-hardening/issues/03-quyen-dw-app-va-rls-initplan.md`: hình policy RLS
  và grant của `dw_app`; `runtime-hardening/02`: biến mạng và kho dữ liệu;
  `.claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md`: viết lại
  `_CATALOG_COLUMNS` và `export_rows` của `offboarding.py`, mà ticket 02 (catalog xuất không liệt kê
  `secret_envelopes`) và ticket 06 (hủy khóa ở bước cuối của offboarding) cùng sửa, nên hai ticket chờ nó.
- `.claude/plans/studio/org-and-principals/issues/01-khoa-don-vi-va-siet-realm.md`: `uq_workspaces_tenant_id_id`
  làm đích cho FK ghép `(tenant_id, owning_workspace_id)` của ticket 02 và 03.
- `.claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md`: danh sách bảng toàn
  tenant của test phủ RLS (studio-skeleton:R9.1, studio-skeleton:R9.4) mà ticket 02 và 03 thêm dòng vào.
- `.claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md`: `run_mode` trên
  ngữ cảnh lượt chạy và cờ `simulate_safe` mà Bộ gọi ra ngoài và `SmtpEgress` đọc để từ chối theo R3.5, R7.5
  (tenant-config:R4.1, tenant-config:R5.1, tenant-config:R5.4).
- `.claude/plans/studio/tenant-rbac/issues/01-mot-chu-cho-quyen.md`: Danh mục quyền mà ticket 03 và 04 đăng ký
  khóa vào, và tiền tố `connections.`, `integrations.` trong `FORBIDDEN_SCOPE_PREFIXES` của truy cập người vận
  hành (tenant-rbac:R1.5); `.claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md`: quyền hiệu
  lực theo độ sâu (`platform.effective_grants`) mà `connections.read`, `connections.manage`, `connections.use` và
  `integrations.admin` được kiểm qua, `platform.checker_candidates` cho `no_checker_available` của R3.12 và
  R5.13, và cột `tenant_grantable` mà câu INSERT đăng ký khóa nêu; ticket 03 và 04 chờ ticket đó.
- Seam nền tảng: phê duyệt không lượt chạy công bố `<approval_type>.decided` trong giao dịch của quyết định,
  tiền tố nghiêm từ chối người gửi và dấu `required_scope` (`CLAUDE.md`, mục "Agent and tool rules";
  ADR-0004 (Accepted)), mà `connections.enable` và `egress.allowed_host` dùng; mã từ chối người quyết theo
  ADR-0104 (Accepted) quyết 11, với `second_person_required` là mã chung của lần từ chối theo tiền tố nghiêm
  cho mọi loại phê duyệt.
- `.claude/plans/studio/workflow-triggers/issues/02-data-hub-endpoint-va-ingress.md`: thêm chủ thể
  `inbound_endpoint_id` vào `platform.secret_envelopes` với FK ghép tới `studio.inbound_endpoints (tenant_id, id)`
  ON DELETE CASCADE, nới CHECK `num_nonnulls` và thêm UNIQUE `(tenant_id, inbound_endpoint_id, field, secret_version)`
  trong migration của nó, sau ticket 02 của spec này;
  bí mật ký của Nguồn dữ liệu dùng AAD của ticket 02 với `subject_kind` `inbound_endpoint` và `field`
  `signing_secret`, và hai bí mật chồng 24 giờ là hai `secret_version`; bí mật ký cũ mang `revoked_at` bằng lúc xoay
  cộng 24 giờ, do `platform.put_secret` của ticket 02 ghi (R1.9), cột mà bộ kiểm chữ ký của ticket đó đọc qua
  `platform.secret_status` để từ chối bí mật cũ sau 24 giờ và lane `credential_purge` đọc để xóa nó (V4.20).
- agent-lifecycle:R8.4: hợp đồng lane gửi đi hỏi công tắc trước khi gửi, mà lane gửi tin đã xếp hàng W2 của
  spec này đáp ứng.
- `.claude/plans/studio/tools-and-skills/issues/02-toolset-va-cong-cu-ghim.md`: Đặc tả công cụ, `ToolExecutor`
  và bộ bọc đầu ra mà Hành động `connector_action` của ticket 05 chạy qua (tools-and-skills:R2.1,
  tools-and-skills:R5.1).
- `.claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md`: `RunBindingsPort` đáp ứng
  từ mục `bindings` của bản kê lượt chạy, mà ticket 05 dùng; mục đó ghim id kết nối và phiên bản Bộ giá trị gắn, không
  ghim `secret_version` nào (ADR-0109 (Accepted) quyết 6; V4.35), nên lane `credential_purge` không đọc bản kê.
- Protocol do bên dùng khai: `RunBindingsPort` (tenant-config/05 đáp ứng từ bản kê, ADR-0110 (Accepted));
  `ConnectionDependentsPort` (spec này khai, tenant-config/05 đáp ứng theo tenant-config:R3.7).
- Kiểm lại khi: kết quả FOG-25 (Transit, mở niêm phong không người) → R2, ticket 06; kết quả FOG-26 → dòng
  smokescreen ở Ngoài phạm vi; luật sư bác gửi tới cả hai công ty (DO-48.2) → dòng định tuyến W2;
  `connection_usable` đổi hình hợp đồng → ticket 04, 05; `run_mode` đổi giá trị hay chỗ đọc → R3.5, R7.5,
  ticket 03, 05; `RunBindingsPort` đổi hình → ticket 05; ADR-0115 (Accepted) quyết 2, 6 đổi `required_scope`
  của `connections.enable` hay `egress.allowed_host` → R3.9, R5.10, ticket 03, 04; tenant-rbac/02 đổi hình
  `platform.checker_candidates` hay ADR-0104 (Accepted) quyết 11 đổi mã từ chối → R3.10, R3.12, R5.11, R5.13,
  ticket 03, 04; tenant-config lại ghim một phiên bản bí mật trong bản kê → R1.14, R5.15-R5.17, ticket 02, 04, 05;
  model-connections (W2) gọi `connection_usable` với `purpose='model'` (ADR-0118 (Accepted) quyết 3)
  → R5.14, ticket 04 bước 2; workflow-triggers/02 đổi khoảng chồng của bí mật ký hay cách nó đọc `revoked_at` → R1.9,
  R4.4, Dữ liệu, ticket 02; runtime-hardening/01 đổi tên hay tập lỗi có kiểu, hay cách ghi dòng kết thúc → R3.13-R3.16,
  R6.8, R7.6-R7.8, ticket 03, 05; workflow-engine đổi cách wrapper đọc kết quả có kiểu (workflow-engine:R4.23) →
  R3.13, R6.5-R6.7; trình kết nối đầu tiên khai khóa hay tra cứu (W2, H-5) → R6.6, dòng W2 của khối `delivery`;
  Đạt trả lời Q3 → R1.15, API, ticket 04, 07.

## Câu hỏi còn mở

- Q2. Thời hạn lưu giữ cho các kho mới (phong bì bí mật của kết nối đã thu hồi, kết nối đã thu hồi 90 ngày; phiên
  bản bí mật bị thay thì lane `credential_purge` xóa 24 giờ sau lần xoay, phiên bản bị thu hồi vì lộ thì xóa ngay,
  theo V4.35 và H-10) có theo artifact lưu giữ của DO-52 không? Chủ: counsel và Đạt. Không đổi: hình bảng W1; thời hạn
  vào lane lưu giữ ở W2.

## Quyết định

- 22/10/2026 (người yêu cầu): S10: kho bí mật mã hóa phong bì dưới Khóa của công ty trong OpenBao Transit
  sau `KmsPort`, một Bộ gọi ra ngoài ghim IP cộng smokescreen làm lớp thứ hai (ADR-0115 (Accepted) quyết
  1, 5). Sửa: R1, R3.
- 23/10/2026 (người yêu cầu): D14 (DO-24): resize host chính lên ít nhất 4 vCPU / 16 GB trước khi OpenBao
  và egress proxy triển khai; đo trước khi cố định kích thước. Sửa: R2.
- 23/10/2026 (agent, tạm): DO-20 theo khuyến nghị (c): nền tảng sở hữu ứng dụng Meta và Zalo (một ứng
  dụng mỗi môi trường), khách dùng Page và OA của họ qua OAuth, ứng dụng Google nội bộ của khách; duyệt
  bắt đầu tuần đầu. Sửa: ticket 01. Nếu sai thì: đổi chủ ứng dụng và callback trong ticket 01, 14, 15.
- 23/10/2026 (agent, tạm): DO-48 theo khuyến nghị (a): SMTP chung là đường email P1 (Gmail API ở P2); chỉ
  kết nối dùng chung theo workspace (không kết nối cá nhân hay ủy quyền ở P1); cùng một Page hay OA do hai
  công ty kết nối thì fan-out tới cả hai, counsel xác nhận. Sửa: R5, R7, Ngoài phạm vi. Nếu sai thì:
  thêm kết nối cá nhân và `connection_delegations` vào P1 (B8a ticket 17).
- 23/10/2026 (agent, tạm): khóa quyền `connections.read`, `connections.manage`, `connections.use`,
  `integrations.admin` theo dạng của tenant-rbac/01. Sửa: R5, mục API. Nếu sai thì: đổi tên khóa ở R5 và
  ticket 04 theo danh mục của tenant-rbac.
- 23/10/2026 (Đạt): DO-47.1 theo (a): OpenBao Transit từ P1, mở niêm phong không người theo số đo FOG-25,
  sao lưu kho khóa với thời hạn giữ không dài hơn bản sao lưu dữ liệu, xoay Khóa của công ty mỗi 90 ngày,
  BYOK sau v1; Xóa bằng hủy khóa có hiệu lực khi bản sao lưu kho khóa cũ nhất còn giữ khóa hết hạn, và
  diễn tập khôi phục kiểm cả `dw` lẫn kho khóa. Hỏi: Q1. Sửa: R2 (R2.5, R2.6, R2.7, R2.8), CV20, Ngoài
  phạm vi (BYOK), ticket 02 (phần OpenBao tách sang ticket 06).
- 23/10/2026 (Đạt): DO-47.2 theo (a): smokescreen bắt buộc trước đích HTTP đầu tiên do công ty định nghĩa
  (W2); host SMTP của P1 chỉ ghim địa chỉ (R7.3). Hỏi: Q1. Sửa: Ngoài phạm vi (dòng smokescreen).
- 23/10/2026 (Đạt): ADR-0115 (Accepted) được chấp nhận với điều kiện OpenBao và smokescreen chỉ ship sau
  khi spike 21 (FOG-25) đo mở niêm phong không người và tương đương Transit; `KmsPort`, `LocalDevKms`,
  `platform.secret_envelopes` và chính sách địa chỉ của R3.2 đi ngay. Sửa: ticket 02, ticket 06 (bước 1 là
  phép đo FOG-25), Tiêu chí xong.
- 23/10/2026 (Đạt): DO-01 theo (a): ba bảng của spec này là bảng toàn tenant, mỗi bảng một dòng có lý do
  trong `_TENANT_WIDE_ON_PURPOSE`; một tên cột `owning_workspace_id` với FK ghép tới `platform.workspaces`.
  Sửa: Dữ liệu (đổi `owner_workspace_id`), Phụ thuộc, ticket 02, 03 (chờ org-and-principals/01 và
  studio-skeleton/01).
- 23/10/2026 (Đạt): DO-06 theo (a): tài liệu giữ tên Điểm gắn; giá trị nằm ở Bộ giá trị gắn đã duyệt và
  ghim theo lượt chạy. R6.4 đã viết theo cách này.
- 23/10/2026 (Đạt): DO-20 theo (c): ứng dụng nền tảng cho Meta và Zalo, Page và OA của khách nối qua
  OAuth, nền tảng không giữ ứng dụng Google nào (ứng dụng nội bộ của khách là W2); pháp nhân vận hành nộp
  App Review và Business Verification từ tuần một. Sửa: ticket 01 (bỏ bước nền tảng xác minh Google), nhãn
  của dòng tạm DO-20 cùng ngày sửa từ (a) thành (c).
- 23/10/2026 (Đạt): DO-26.1 theo (A): W1 chỉ mở `simulate`, `test` trả 422 tới W2; mọi lớp egress từ chối
  chế độ khác `live`. Sửa: R3.5, R7.5, CV10, Ngoài phạm vi, ticket 03, 05.
- 23/10/2026 (Đạt): DO-48.1 theo (a): SMTP chung, chỉ kết nối dùng chung theo workspace; luồng OAuth và
  kết nối cá nhân ở W2. R5, R7 và ticket 04, 05 giữ như đang viết.
- 23/10/2026 (Đạt): DO-48.2 theo (a), tạm tới khi luật sư trả lời: cùng Page hay OA do hai công ty nối thì
  gửi tới cả hai; không bật định tuyến W2 trước ý kiến của compliance-pdpl/02 và câu 3 của discovery/18;
  luật sư bác thì thiết kế lại theo ràng buộc không lộ của ADR-0113 (Accepted), không từ chối lúc nối.
  Sửa: Ngoài phạm vi (dòng định tuyến W2), Phụ thuộc.
- 23/10/2026 (Đạt): DO-49 theo (a): mọi giới hạn tốc độ qua một `RateLimiterPort` của usage-and-limits;
  mất Valkey thì xô mỗi tiến trình ở hạn mức chia số replica. Sửa: Ngoài phạm vi, ticket 05 (bỏ giới hạn
  riêng theo kết nối khỏi W1).
- 23/10/2026 (Đạt): DO-58 theo (b): webhook gửi đi mặc định mỏng; dữ liệu cá nhân bật theo từng endpoint,
  có audit, áp Đã ẩn và Lộ trình dữ liệu. Sửa: Ngoài phạm vi (dòng webhook W2).
- 23/10/2026 (Đạt): mục trần đầu ra công cụ (YC48 so với ADR-0116 (Accepted)) theo (a): trần cứng 16 KiB theo byte, mặc định 8 000 ký tự, chỉ bộ bọc
  của tools-and-skills bọc và cắt. Sửa: R6.3, CV17, Phụ thuộc, ticket 05.
- 23/10/2026 (agent, tạm): `ConnectionDependentsPort` do tenant-config đáp ứng (đọc `studio.dependencies`
  cộng giá trị Bộ giá trị gắn đã duyệt), `RunBindingsPort` do tenant-config/05 đáp ứng từ mục `bindings`
  của bản kê; ticket 05 chờ tenant-config/05, ticket 04 kiểm R5.8 qua một bản giả theo đúng hợp đồng port
  vì tenant-config/05 chờ ticket 04 (phát hiện kiểm nhất quán 23/10/2026). Sửa: Trong phạm vi, Phụ thuộc,
  ticket 04, 05. Nếu sai thì: đổi bên đáp ứng và cạnh Blocked by của ticket 05.
- 23/10/2026 (agent, tạm): khóa `connections.read`, `connections.manage` đăng ký ở migration của ticket
  04, `integrations.admin` ở ticket 03 (quy ước của tenant-rbac/01); tên giữ như ADR-0115 (Accepted) viết,
  chưa theo dạng `studio.<area>.<verb>`. Sửa: Trong phạm vi, API, Phụ thuộc, ticket 03, 04. Nếu sai thì:
  đổi tên khóa cùng lúc ở ADR-0115 (Accepted) và mọi route.
- 24/10/2026 (Đạt): `connection_usable` kiểm thêm `connections.use` ở workspace của lượt chạy, đúng
  ADR-0115 (Accepted) quyết 2; ticket 04 đăng ký khóa trong migration của nó, test âm ở CV14. Sửa: R5.9, Trong
  phạm vi, CV14, Phụ thuộc, ticket 04.
- 24/10/2026 (người đặt yêu cầu và Đạt): Phạm vi D11: bật lại một kết nối và thêm một Máy chủ được phép cần
  hai người, mỗi việc mở một phê duyệt nghiêm không lượt chạy (`connections.enable`, `egress.allowed_host`) mà
  handler `.decided` áp thay đổi; tắt kết nối và xóa Máy chủ được phép vẫn một người cộng audit
  (ADR-0115 (Accepted), sửa ngày 24/10/2026). Sửa: R3, R3.9, R3.10, R3.11, R5, R5.10, R5.11, R5.12, Trong phạm
  vi, Dữ liệu, API, Màn hình, CV21, CV22, Phụ thuộc, ticket 03, 04.
- 24/10/2026 (Đạt): V4.5: yêu cầu `connections.enable` đóng dấu `required_scope` `connections.manage`, yêu cầu
  `egress.allowed_host` đóng dấu `integrations.admin`, tức khóa quản lý chính việc đó, theo cách
  ADR-0110 (Accepted) quyết 2 đóng dấu khóa duyệt của loại (ADR-0004 (Accepted)); ADR-0115 (Accepted) quyết 2
  và 6 ghi hai khóa duyệt này; handler audit đứng tên người quyết với `details.lane` `outbox`
  (ADR-0011 (Accepted)). Sửa: R3.9, R3.11, R5.10, R5.12, Phụ thuộc (Kiểm lại khi).
- 24/10/2026 (Đạt): ở chế độ khác `live`, Bộ gọi ra ngoài từ chối mọi purpose trừ `model` và Hành động khai
  chỉ đọc hay `simulate_safe`, nêu rõ `mcp` và `oauth` (ADR-0115 (Accepted) quyết 6; ADR-0111 (Accepted) quyết
  3; tenant-config:R5.4). Sửa: R3.5, CV10, Ngoài phạm vi, Phụ thuộc, ticket 03.
- 24/10/2026 (Đạt): mỗi chủ thể mới của Kho bí mật là một cột FK NULL cộng CHECK `num_nonnulls` nới rộng trong
  migration của ticket thêm chủ thể; `inbound_endpoint_id` thuộc workflow-triggers/02, ticket đó chờ ticket
  02 (ADR-0115 (Accepted) quyết 1). Sửa: Dữ liệu, Phụ thuộc, ticket 02.
- 24/10/2026 (Đạt): khóa `connections.*` và `integrations.admin` giữ tên của ADR-0115 (Accepted); tiền tố
  `connections.` và `integrations.` vào `FORBIDDEN_SCOPE_PREFIXES` của tenant-rbac/01, nên người vận hành không
  được cấp quyền tạo kết nối hay thêm Máy chủ được phép. Sửa: Trong phạm vi, Phụ thuộc.
- 24/10/2026 (Đạt): lane gửi tin đã xếp hàng (agent-lifecycle:R8.4) thuộc spec này, ở W2, khi tin được hoãn và
  xếp hàng. Sửa: Ngoài phạm vi, Phụ thuộc.
- 24/10/2026 (Đạt): N8: gửi email qua Gmail của công ty bằng ứng dụng Google nội bộ của khách (DO-20 (c)) ở W2
  (YC107); TikTok Lead Generation sang W3 sau ticket khám phá FOG-82; Google Sheets không ở v1, ứng viên W3.
  Sửa: Ngoài phạm vi.
- 24/10/2026 (agent, tạm): V4.P2: ticket đăng ký khóa vào `platform.permissions` chờ tenant-rbac/02 và nêu trong câu
  INSERT mọi cột NOT NULL có lúc đó, gồm `risk` của tenant-rbac/01 và `tenant_grantable` của tenant-rbac/02
  (ADR-0104 (Accepted) quyết 1). Sửa: Trong phạm vi, Phụ thuộc, ticket 03, 04. Nếu sai thì: tenant-rbac/01 tạo
  cột `tenant_grantable` kèm sửa ADR-0104 (Accepted) quyết 1; ticket 03 vẫn chờ tenant-rbac/02 vì
  `platform.checker_candidates` (R3.12).
- 24/10/2026 (agent, tạm): V4.P9: người gửi tự quyết `egress.allowed_host` hay `connections.enable` bị tiền tố nghiêm
  từ chối với `details.reason_code` `second_person_required`, một mã cho mọi loại phê duyệt mà
  ADR-0104 (Accepted) quyết 11 ghi tên. Sửa: R3.10, R5.11, API, Phụ thuộc, CV21, CV22, ticket 03, 04. Nếu sai
  thì: đổi mã ở R3.10, R5.11, API và test CV21, CV22 theo tên ADR-0104 (Accepted) ghi.
- 24/10/2026 (agent, tạm): hai phê duyệt nghiêm hỏi `platform.checker_candidates` của tenant-rbac/02 trước khi
  mở và trả 409 `no_checker_available` khi không còn người duyệt nào khác người gửi, như mọi cơ chế hai người
  của ADR-0110 (Accepted) quyết 2 và ADR-0104 (Accepted) quyết 10 (kiểm nhất quán vòng 3). Sửa: thêm R3.12,
  R5.13, Trong phạm vi, API, CV21, CV22, Phụ thuộc, ticket 03, 04. Nếu sai thì: bỏ R3.12, R5.13 và hai ca âm đó
  của CV21, CV22.
- 24/10/2026 (agent, tạm): AAD của phong bì là
  `dw.secret.v1|<tenant_id>|<owning_workspace_id>|<subject_kind>:<subject_id>|<field>|<secret_version>`, gắn công
  ty, workspace sở hữu, chủ thể, trường và phiên bản như ADR-0115 (Accepted) quyết 1 đòi, mà phiên bản ở đó là
  của bí mật, không đổi khi bọc lại: `secret_version` tăng khi giá trị bí mật đổi, còn lane `credential_rewrap`
  chỉ bọc lại khóa dữ liệu (`transit/rewrap`, ticket 06 bước 4) và tăng `kek_version`, nên AAD mang `kek_version`
  làm hỏng mọi phong bì sau lần bọc lại đầu tiên (kiểm nhất quán vòng 3, lỗi của bản sửa vòng 3). Bảng có cột
  `field`, `secret_version` và UNIQUE `(tenant_id, subject_kind, subject_id, field, secret_version)`, cùng cột
  `wrapped_data_key`, khóa dữ liệu đã bọc mà ADR-0115 (Accepted) quyết 1 giữ cạnh `ciphertext` và lane
  `credential_rewrap` bọc lại, và bỏ `aad_hint` không bên đọc (failure-modes #1); `connection_usable` đọc phiên
  bản bí mật đã thu hồi từ `secret_version`; bí mật ký của workflow-triggers/02 dùng cùng dạng với `subject_kind`
  `inbound_endpoint`, `field` `signing_secret`. Sửa: R1.4, Dữ liệu, CV1, Phụ thuộc, ticket 02, 04, 06. Nếu sai
  thì: lane `credential_rewrap` mã hóa lại mọi phong bì dưới một khóa dữ liệu mới thay vì bọc lại, nhánh mà phần
  sửa đổi vòng 4 của ADR-0115 (Accepted) ghi cho trường hợp sai, và khi đó AAD có thể mang phiên bản khóa;
  ticket 06 bước 4, R2.6 và ca bọc lại của CV1 đổi theo, còn `secret_version` vẫn là phiên bản credential mà bản
  kê lượt chạy ghim (ADR-0110 (Accepted) quyết 8).
- 24/10/2026 (agent, tạm): `platform.secret_envelopes.connection_id` có FK ghép `(tenant_id, connection_id)` tới
  `platform.connections (tenant_id, id)` ON DELETE CASCADE, vì phong bì là dòng con của chủ thể như
  `inbound_endpoint_id` của workflow-triggers/02; chỉ mục của FK là UNIQUE
  `(tenant_id, connection_id, field, secret_version)`, và `platform.connections` thêm UNIQUE `(tenant_id, id)` làm
  đích (CLAUDE.md, Data model rules: khóa ngoại nào cũng nêu `ON DELETE` và có chỉ mục ở phía của nó); FK workspace
  sở hữu của `platform.egress_allowed_hosts` cũng nêu rõ `ON DELETE RESTRICT` và chỉ mục, không chỉ dẫn "như
  `platform.connections`". Sửa: Dữ liệu, ticket 02, 03. Nếu sai thì: FK của phong bì là `ON DELETE RESTRICT`, và
  lần xóa một Kết nối (R5.8, ticket 04) gọi `platform.delete_secret` cho mọi phong bì của nó trước, trong cùng giao
  dịch.
- 24/10/2026 (agent, tạm): mọi khóa ngoại từ một bảng của spec này tới một bảng theo tenant là FK ghép
  `(tenant_id, <cột>)` tới UNIQUE `(tenant_id, id)` của bảng đích, vì kiểm khóa ngoại không qua RLS nên một FK một
  cột để phong bì của công ty này trỏ tới chủ thể của công ty khác; cột chủ thể nào thêm sau (`inbound_endpoint_id`
  của workflow-triggers/02) theo cùng dạng, và R1.8 cùng CV23 là test âm (CLAUDE.md, Tenancy and authorization: test
  âm cho đọc và ghi chéo tenant là bắt buộc). Sửa: thêm R1.8, Dữ liệu, Kiểm soát (CV23), Phụ thuộc (dòng
  workflow-triggers/02), ticket 02. Nếu sai thì: cột chủ thể giữ FK một cột và `platform.put_secret` tự kiểm chủ thể
  thuộc công ty của ngữ cảnh trước khi ghi, còn R1.8 và CV23 kiểm hàm đó thay khóa ngoại.
- 24/10/2026 (agent, tạm): bản kê lượt chạy ghim một `secret_version` cho mỗi (kết nối, trường), vì `secret_version`
  đếm theo (chủ thể, trường) (ADR-0115 (Accepted) quyết 1; tenant-config:R7.4), nên `pinned_secret_versions` mà
  `connection_usable` nhận là một `secret_version` cho mỗi trường bí mật của kết nối. Sửa: Phụ thuộc (Kiểm lại
  khi), ticket 04 bước 2. Nếu sai thì: bản kê ghim một phiên bản cho cả kết nối, `secret_version` thành phiên bản
  của kết nối thay vì của trường, và Dữ liệu, UNIQUE cùng AAD của ticket 02 đổi theo.
- 24/10/2026 (agent, tạm): `connection_usable(connection, context, purpose)` mang `purpose` từ W1, như
  ADR-0115 (Accepted) quyết 2 và ADR-0118 (Accepted) quyết 3 gọi (`purpose='model'`), để W2 chỉ thêm một giá trị
  mà không sửa chỗ gọi nào (CLAUDE.md, Per-tenant artifacts: registry mới nhận đối số từ đầu); W1 chỉ nhận
  `purpose='tool'` và mọi giá trị khác làm hàm trả false (R5.14), để đối số có bên đọc ngay từ W1 (failure-modes
  #1). Sửa: Trong phạm vi, thêm R5.14, Ngoài phạm vi (dòng BYOM), CV14, Phụ thuộc (Kiểm lại khi), ticket 04 bước 2,
  ticket 05 bước 2. Nếu sai thì: hàm bỏ `purpose`, R5.14 rút, và W2 thêm đối số ở mọi chỗ gọi cùng lúc với kết nối
  model.
- 24/10/2026 (agent, tạm): `owning_workspace_id` của `platform.connections` không đổi sau khi tạo: trigger
  `platform.guard_connection_owning_workspace()` từ chối mọi UPDATE đổi cột đó (R1.7), vì AAD của phong bì gắn
  workspace sở hữu (ADR-0115 (Accepted) quyết 1), nên đổi workspace sở hữu là mã hóa lại mọi phong bì của Kết nối
  dưới AAD mới, và `PATCH /api/v1/connections/{id}` không nhận cột đó. Sửa: thêm R1.7, Dữ liệu, CV1, ticket 02, 04.
  Nếu sai thì: UPDATE cột đó được phép trong một giao dịch mã hóa lại mọi phong bì của Kết nối, và R1.7 đổi thành
  kiểm giao dịch đó.
- 24/10/2026 (agent, tạm): `nonce` và `ciphertext` của `platform.secret_envelopes` là NOT NULL, vì CHECK độ dài nhận
  NULL, nên thiếu NOT NULL thì một phong bì không có nonce hay bản mã qua được mọi ràng buộc của bảng
  (failure-modes #7: giá trị thiếu không được mở cửa); ticket 02 bước 1 chép nguyên văn ràng buộc của mục Dữ liệu cho
  các cột của bảng, gồm `tenant_id`, `alg`, `kek_ref`, `kek_version` NOT NULL, để hai bản không lệch nhau
  (failure-modes #2), và R1.1 có ca phong bì thiếu `nonce` hay `ciphertext` bị từ chối. Sửa: Dữ liệu, ticket 02. Nếu
  sai thì: một trong hai cột được NULL có chủ ý (ví dụ một phong bì giữ chỗ trước khi có giá trị), Dữ liệu nêu
  trường hợp đó và CHECK độ dài viết rõ vế `IS NULL` kèm lý do.
- 24/10/2026 (agent, tạm): khóa ngoại `tenant_id` của `platform.secret_envelopes` tới `platform.tenants` nêu chỉ mục
  của nó, UNIQUE `(tenant_id, connection_id, field, secret_version)` dẫn đầu bằng `tenant_id`, vì mọi khóa ngoại có
  chỉ mục ở phía của nó (CLAUDE.md, Data model rules); các khóa ngoại khác của spec này đã nêu chỉ mục của mình. Sửa:
  Dữ liệu, ticket 02. Nếu sai thì: FK đó có chỉ mục riêng dẫn bằng `tenant_id`, và Dữ liệu cùng ticket 02 nêu chỉ
  mục đó.
- 24/10/2026 (Đạt): V4.20: bí mật ký cũ của Nguồn dữ liệu được nhận 24 giờ sau lần xoay rồi bị từ chối; thay bí mật
  của một kết nối thu hồi phiên bản cũ ngay (`revoked_at`), và một lượt đã ghim phiên bản đó dừng ở lần dùng kế tiếp
  với `credential_revoked` (đóng khi thiếu); một lane xóa các phiên bản bị từ chối hay thu hồi khi không còn lượt dở
  dang nào ghim chúng; nhánh "phiên bản đã thu hồi" của `connection_usable` nay có nguồn. Sửa: R1, thêm R1.9, R1.10,
  R1.11, R1.12, R1.13, R4.4, R5, thêm R5.15, Trong phạm vi, Dữ liệu, API, Kiểm soát (CV24, CV25), Phụ thuộc, Câu hỏi
  còn mở (Q2), ticket 02, 04, 05.
- 24/10/2026 (agent, tạm): cách áp V4.20: `revoked_at timestamptz NULL` là thời điểm từ đó một phiên bản bị từ chối,
  một cột cho cả hai trường hợp: `platform.put_secret` ghi nó cho phiên bản cũ có `revoked_at` NULL trong giao dịch ghi
  phiên bản mới, bằng thời điểm của giao dịch, hay bằng thời điểm đó cộng 24 giờ khi trường là `signing_secret`, và
  không dời hạn đã ghi, một quy tắc trong hàm cho mọi chủ thể, nên bộ kiểm chữ ký của workflow-triggers/02, `connection_usable`, `platform.open_secret` và lane
  đọc một sự thật thay vì mỗi bên tự tính hạn 24 giờ (failure-modes #2); `platform.open_secret` không mở phiên bản
  đã thu hồi hay thiếu, vì mọi lần dùng bí mật đi qua cửa đó, kể cả mật khẩu mà `SmtpEgress` lấy (failure-modes #5);
  `credential_revoked` là lý do của `connection_usable` và mã mà Bộ gọi ra ngoài trả mà không thử lại; lane
  `credential_purge` chạy mỗi giờ và gọi hàm SECURITY DEFINER không đối số `platform.purge_retired_secrets()`, vì
  `dw_app` không có quyền nào trên bảng, theo tiền lệ `platform.prune_notifications()` (không đối số nên không bên gọi
  nào nới được điều kiện xóa), và ghi audit như chính lane qua `lane_audit.append_across_tenants`
  (ADR-0011 (Accepted)); lane ở ticket 05, ticket duy nhất của spec đi sau tenant-config/05, nơi bản kê bắt đầu ghim
  `secret_version`. Sửa: R1.9, R1.10, R1.11, R1.12, R1.13, R4.4, R5.15, Trong phạm vi, Dữ liệu, Kiểm soát (CV24,
  CV25), Phụ thuộc, ticket 02, 04, 05. Nếu sai thì: bí mật ký giữ `revoked_at` NULL và hạn 24 giờ tính từ
  `created_at` của phiên bản mới trong một hàm mà bộ kiểm chữ ký và lane cùng gọi; hay lane đi qua
  `platform.delete_secret` theo từng công ty thay hàm thứ năm, và ADR-0115 (Accepted) quyết 1 bỏ hàm đó khỏi cửa của
  bảng.
- 24/10/2026 (agent, tạm): `platform.secret_envelopes` có một dòng `STUDIO_EXCLUSIONS` của test phủ offboarding
  (studio-skeleton:R4.3) với lý do "REVOKE ALL với `dw_app`; xóa theo FK CASCADE từ chủ thể (`platform.connections`,
  `studio.inbound_endpoints`) khi lane xóa chủ thể, và qua `platform.delete_secret` cho một bí mật lẻ", vì bảng được
  tạo sau khi studio-skeleton/01 đo `_PLATFORM_PREDATING`, và lane `offboarding` không xuất (R1.6) và không xóa thẳng
  nó, nên thiếu dòng đó thì test phủ đỏ; CV2 thêm ca bỏ dòng và ca phong bì bị xóa theo CASCADE khi offboarding, để lý
  do không là lời khai không ai kiểm (failure-modes #1). Sửa: Dữ liệu, Kiểm soát (CV2), ticket 02. Nếu sai thì: lane
  `offboarding` xóa bảng qua một hàm SECURITY DEFINER hẹp như `platform.purge_tenant_append_only`, và lý do của dòng
  nêu hàm đó thay FK CASCADE.
- 25/10/2026 (Đạt): V4.30: lời hứa "đúng một lần" thành bốn mức bảo đảm gọi bằng tên (nội bộ, có khóa hay tra cứu,
  không khóa, đồng thời); khối `delivery` của `dw.connector/v1` bắt buộc khi `side_effect_level` khác `none`, với
  `idempotency`, `reconciliation`, `on_unknown` (vắng là `review`), luật nạp `resend_same_key` cần khóa,
  `lookup_then_resend` cần tra cứu, không giá trị "coi như thất bại", không `effect_risk`; `smtp@1.0.0` khai
  `idempotency: none`, `reconciliation: none`, `on_unknown: review`, `Message-ID` suy từ khóa chỉ là gợi ý phía hộp thư
  nhận; Bộ gọi ra ngoài trả kết quả có kiểu `not_dispatched`, `rejected`, `outcome_unknown`, `succeeded` mà ToolExecutor
  và wrapper nút đọc, với SMTP đã gửi `DATA` mà chưa nhận 250 là `outcome_unknown`; R7.4 thôi hứa "gửi chính xác một
  email" mà hứa mức không khóa. Sửa: R3, thêm R3.13-R3.16, R6, thêm R6.5-R6.7, R7, R7.4, thêm R7.6-R7.8, Trong phạm
  vi, Ngoài phạm vi (dòng W2 của khối `delivery`), Kiểm soát (CV18, CV26, CV27), Phụ thuộc, ticket 03, 05.
- 25/10/2026 (Đạt): V4.31: màn `/studio/connections` (bước 7 của ticket 04) tách thành ticket 07, nên ticket 04 thôi
  chờ studio-skeleton/03 và ticket 07 chờ ticket 04 cùng studio-skeleton/03. Sửa: Màn hình, Phụ thuộc, Danh sách
  ticket, ticket 04, 07.
- 25/10/2026 (Đạt): V4.35: bản kê lượt chạy ghim id kết nối và phiên bản Bộ giá trị gắn, không ghim `secret_version`;
  lúc gọi thì dùng phiên bản mới nhất chưa thu hồi của kết nối và ghi phiên bản đã dùng vào `platform.tool_executions`
  và audit; xoay tách khỏi thu hồi vì lộ: thu hồi vì lộ làm mọi lượt chưa xong của kết nối dừng ở lời gọi egress kế
  tiếp với `credential_revoked`, kể cả khi đã có phiên bản mới; bí mật ký của Nguồn dữ liệu giữ luật 24 giờ của V4.20.
  Dòng này thay dòng 24/10/2026 (agent, tạm) "bản kê lượt chạy ghim một `secret_version` cho mỗi (kết nối, trường)",
  phần "một lượt đã ghim phiên bản đó dừng ở lần dùng kế tiếp" và "khi không còn lượt dở dang nào ghim chúng" của
  V4.20 cùng dòng cách áp V4.20 ngày 24/10/2026. Sửa: R1, R1.9-R1.12, thêm R1.14-R1.16, R5, R5.15, thêm R5.16, R5.17,
  thêm R6.8, Trong phạm vi, Dữ liệu, API, Màn hình, Kiểm soát (CV24, CV25, CV28), Phụ thuộc, Câu hỏi còn mở (Q2, Q3),
  ticket 02, 04, 05, 07.
- 25/10/2026 (agent, tạm): H-5, phạm vi W1 của mức có khóa hay tra cứu (V4.30): tác động ra ngoài duy nhất của W1 là
  email SMTP, không khóa và không tra cứu, nên W1 làm mức nội bộ, không khóa và đồng thời; khối `delivery` có đủ trường
  trong schema nhưng bộ nạp từ chối mọi `idempotency.mode` khác `none`, `reconciliation.mode` khác `none` và
  `on_unknown` khác `review` (R6.6) tới khi trình kết nối đầu tiên khai khóa hay tra cứu (W2), cùng lúc với
  `resend_same_key`, `lookup_then_resend` và lane `studio_reconcile`; `compensation` không vào v1 vì không có bên đọc.
  Sửa: R6.6, Trong phạm vi, Ngoài phạm vi, CV27, ticket 05. Nếu sai thì: mức có khóa vào W1 với một trình kết nối thử
  có khóa và lane `studio_reconcile`, R6.6 bỏ vế W1.
- 25/10/2026 (agent, tạm): H-10, vòng đời phiên bản bí mật khi không còn ghim (V4.35): một lời gọi dùng phiên bản mới
  nhất chưa thu hồi của kết nối và ghi `credential_version` đã dùng, cột mới của `platform.tool_executions` mà spec này
  là chủ vì Bộ gọi ra ngoài phân giải bí mật (runtime-hardening/01 không đổi); lane `credential_purge` xóa phiên bản bị
  thay 24 giờ sau lần xoay và phiên bản bị thu hồi ngay, vì không lượt nào ghim phiên bản nữa. Sửa: R1.11, R1.12,
  R1.14, R6.8, Dữ liệu, CV24, CV25, ticket 02, 05. Nếu sai thì: giữ phiên bản bị thay tới khi không còn lượt chưa xong
  nào của kết nối.
- 25/10/2026 (agent, tạm): H-28, dấu thu hồi vì lộ không mất khi xóa: lần thu hồi vì lộ ghi
  `platform.connections.compromised_at` trong cùng giao dịch với `revoked_at` của phiên bản; `connection_usable` từ chối
  với `credential_revoked` một lượt được xin lúc hay trước `compromised_at`, kể cả khi đã có phiên bản mới; lane
  `credential_purge` xóa vật liệu của phiên bản bị thu hồi ngay nhưng không xóa dấu đó (failure-modes #7). Sửa: R1.15,
  R1.16, R5.16, Dữ liệu, CV28, ticket 04, 05. Nếu sai thì: giữ dòng phiên bản bị thu hồi tới khi không còn lượt chưa
  xong nào của kết nối được xin trước nó, và bỏ `compromised_at`.
- 25/10/2026 (agent, tạm): cách áp V4.35, H-10 và H-28 ở lát này: cột `replaced_at timestamptz NULL` của
  `platform.secret_envelopes`, do `platform.put_secret` ghi cùng `revoked_at`, phân biệt phiên bản bị thay (xóa 24 giờ
  sau `replaced_at`) với phiên bản bị thu hồi vì lộ (`replaced_at` NULL, xóa ngay), vì hai thời hạn của H-10 không suy
  được từ `revoked_at` khi trường của Kết nối bị thay có `revoked_at` bằng lúc xoay còn bí mật ký có `revoked_at` bằng
  lúc xoay cộng 24 giờ; `platform.open_secret` không nêu phiên bản thì mở phiên bản lớn nhất chưa thu hồi và trả số đó
  (bộ kiểm chữ ký vẫn nêu phiên bản trong khoảng chồng); lần thu hồi vì lộ là hàm SECURITY DEFINER thứ năm
  `platform.revoke_connection_secrets(p_connection_id)`, vì `dw_app` không có quyền nào trên bảng phong bì;
  `compromised_at` chỉ tiến lên, có trigger; "được xin lúc hay trước" so `created_at` của dòng `platform.worker_runs`;
  `credential_version` là `jsonb` ánh xạ trường sang phiên bản, vì một Kết nối có thể có nhiều trường bí mật, và
  ToolExecutor ghi nó trên dòng kết thúc từ phiên bản mà `ManifestActionHandler` đặt vào ngữ cảnh lời gọi trước lần
  gọi ra ngoài, nên ca `outcome_unknown` vẫn có nó. Sửa: R1.9, R1.10, R1.14, R1.15, R5.16, R6.8, Dữ liệu, API, ticket
  02, 04, 05. Nếu sai thì: `credential_version` là một số nguyên và bộ nạp từ chối Hành động có hơn một trường bí mật;
  hay lần thu hồi vì lộ đi qua `platform.delete_secret` (xóa ngay thay vì đánh dấu), và ADR-0115 (Accepted) quyết 1 giữ
  bốn hàm.
- 25/10/2026 (agent, tạm): cách áp V4.30 ở lát này: Bộ gọi ra ngoài phân loại theo byte đã ghi ra socket, dừng trước
  byte đầu là `NotDispatchedError`, hết thời gian hay reset sau đó và mọi 5xx là `OutcomeUnknownError`, mọi 4xx là
  `RejectedError` mang trạng thái (ADR-0115 (Accepted) quyết 6: "a 4xx that the provider commits it did not apply"),
  vì wrapper chỉ thử lại mã `rejected` mà Hành động khai thử lại được (workflow-engine:R4.23), nên một 4xx đã áp dụng
  không tự gửi lại khi Hành động không khai nó; `SmtpEgress` ném `RejectedError` cho mọi trả lời 4yz, 5yz (RFC 5321
  mục 4.2: máy chủ không nhận trách nhiệm với thư), `NotDispatchedError` trước dấu kết thúc dữ liệu,
  `OutcomeUnknownError` sau nó mà chưa có 250; bảng phân loại là một module dùng chung ở ticket 03 mà `SmtpEgress` của
  ticket 05 dùng lại. Sửa: R3.13-R3.16, R7.6-R7.8, CV26, ticket 03, 05. Nếu sai thì: một 4xx chỉ là `rejected` khi
  Bản mô tả khai nó cam kết không áp dụng, các 4xx khác là `outcome_unknown`, và R6.5 thêm trường đó vào khối
  `delivery`.
- 26/10/2026 (Đạt): Q-h3 theo khuyến nghị ("theo khuyến nghị hết cho tôi"): người giữ `connections.manage` với tới
  workspace sở hữu của Kết nối thu hồi vì lộ một mình, có audit `connection.credentials_revoked`, vì việc này đóng quyền
  truy cập như tắt kết nối (D11). Hỏi: Q3. Sửa: R1.15, API, CV28, ticket 04, 07.

## Danh sách ticket

| #   | Ticket                                                                                                                                               |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Hồ sơ ứng dụng và duyệt của nhà cung cấp: Meta, Zalo OA và ZNS](issues/01-ho-so-ung-dung-nha-cung-cap.md)                                           |
| 02  | [Kho bí mật: KmsPort, LocalDevKms, secret_envelopes và cửa một chiều](issues/02-kho-bi-mat-va-openbao.md)                                            |
| 03  | [Egress client ghim IP, kết quả có kiểu, danh sách máy chủ được phép và module chữ ký webhook](issues/03-egress-client-allowlist-va-chu-ky.md)       |
| 04  | [Kết nối dùng chung theo workspace: quy tắc dùng được, API, thu hồi vì lộ, bật lại hai người, audit](issues/04-ket-noi-dung-chung-theo-workspace.md) |
| 05  | [Manifest dw.connector/v1 với khối delivery, trình kết nối email SMTP và lane xóa phiên bản bí mật cũ](issues/05-manifest-va-ket-noi-email.md)       |
| 06  | [OpenBao Transit: khóa khi triển khai, xoay khóa, hủy khóa, sao lưu và diễn tập khôi phục](issues/06-openbao-transit-va-sao-luu-kho-khoa.md)         |
| 07  | [Màn Kết nối /studio/connections](issues/07-man-ket-noi.md)                                                                                          |
