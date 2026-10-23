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
bao giờ rời Kho bí mật ra một đường ra nào (YC61; ADR-0115 (Accepted) quyết 1).

- R1.1 Kho bí mật PHẢI lưu mỗi Thông tin bí mật dưới dạng phong bì AES-256-GCM với một khóa dữ liệu
  riêng mỗi bí mật, bọc bởi Khóa của công ty qua `KmsPort`.
- R1.2 Thông tin bí mật PHẢI không xuất hiện trong phản hồi API, trạng thái lượt chạy, checkpoint, đối
  số công cụ, bản kê lượt chạy, trace, log hay Nhật ký kiểm toán.
- R1.3 NẾU `dw_app` đọc, sửa hay xóa thẳng `platform.secret_envelopes`, THÌ PostgreSQL PHẢI từ chối với
  `permission denied` và không trả dòng nào.
- R1.4 NẾU một phong bì được giải mã với danh tính chủ thể hoặc công ty khác với lúc mã hóa, THÌ Kho bí
  mật PHẢI giải mã lỗi và không trả giá trị rõ.
- R1.5 NẾU một dòng mang `kek_ref` của công ty khác với công ty trong ngữ cảnh, THÌ Kho bí mật PHẢI từ
  chối và ghi audit `secret.key_mismatch`.
- R1.6 KHI lane `offboarding` xuất dữ liệu một công ty, danh sách bảng xuất PHẢI không gồm
  `platform.secret_envelopes`.

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
Internet toàn cầu trong danh sách được phép, kể cả sau chuyển hướng hay đổi DNS (YC63, YC34;
ADR-0115 (Accepted) quyết 5).

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
  mang purpose `connector`, `http_tool` hay `webhook`, THÌ Bộ gọi ra ngoài PHẢI từ chối với
  `egress_blocked:run_mode` và không gọi nhà cung cấp.
- R3.6 Test kiến trúc PHẢI đỏ khi một module ngoài danh sách adapter vận hành tạo `httpx.AsyncClient`
  trực tiếp.
- R3.7 NẾU đích của một purpose khác `connector` và `oauth` không nằm trong Máy chủ được phép của công
  ty, THÌ Bộ gọi ra ngoài PHẢI từ chối với `egress_blocked:host_not_allowed` và không gửi byte nào.
- R3.8 NẾU một mẫu Máy chủ được phép đặt wildcard trên một hậu tố công cộng, hoặc là một IP literal, THÌ
  API quản trị PHẢI trả 422 và không thêm dòng.

### R4 — Bộ kiểm chữ ký webhook

Một module thuần kiểm chữ ký cho mọi cửa nhận sự kiện, từ chối sai chữ ký và lệch giờ (YC42;
ADR-0115 (Accepted) quyết 6).

- R4.1 KHI nhận một thông điệp có chữ ký Standard Webhooks 1.0 đúng và dấu thời gian trong cửa sổ ±5
  phút, Bộ kiểm chữ ký PHẢI trả `verified`.
- R4.2 NẾU chữ ký sai, dấu thời gian lệch quá ±5 phút, hay chữ ký thiếu, THÌ Bộ kiểm chữ ký PHẢI trả
  `rejected` kèm lý do và không lặp lại giá trị đã nhận.
- R4.3 ĐỐI VỚI nhà cung cấp dùng token tĩnh, Bộ kiểm chữ ký PHẢI so token theo thời gian hằng định và
  trả `rejected` khi token sai.
- R4.4 TRONG KHI khóa ký đang xoay, Bộ kiểm chữ ký PHẢI nhận chữ ký của cả khóa cũ còn hạn lẫn khóa mới.

### R5 — Kết nối dùng chung theo workspace

Quản trị viên thêm, kiểm, tắt và thu hồi Kết nối dùng chung của một workspace, một quy tắc
`connection_usable` quyết mọi lượt dùng, và tắt hay thu hồi có hiệu lực trước lần gọi ra ngoài kế tiếp
(YC62; DO-48; ADR-0115 (Accepted) quyết 2).

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

### R6 — Bản mô tả trình kết nối biên dịch thành công cụ

Hành động của một trình kết nối là manifest `dw.connector/v1` biên dịch thành Đặc tả công cụ chạy qua Bộ
gọi ra ngoài, với đầu ra bọc là dữ liệu từ bên ngoài (YC48, YC64; ADR-0116 (Accepted) quyết 2).

- R6.1 KHI nạp một Bản mô tả trình kết nối `dw.connector/v1`, bộ nạp PHẢI biên dịch mỗi Hành động thành
  một Đặc tả công cụ lớp nền tảng có input và output JSON Schema, Mức tác động và `max_retries` là 0.
- R6.2 NẾU một Bản mô tả khai một trường bí mật trong input, hoặc `max_retries` khác 0, THÌ bộ nạp PHẢI
  từ chối và không đăng ký Hành động nào.
- R6.3 KHI một Hành động trả kết quả, `ManifestActionHandler` PHẢI trả kết quả đã kiểm output schema cho
  `ToolExecutor` mà không tự bọc hay cắt, vì chỉ bộ bọc của tools-and-skills:R5.1 bọc và cắt đầu ra công
  cụ (YC48).
- R6.4 KHI chạy một Hành động, `ManifestActionHandler` PHẢI lấy Kết nối qua `RunBindingsPort` theo tên
  Điểm gắn, kiểm `connection_usable`, rồi gọi qua Bộ gọi ra ngoài.

### R7 — Trình kết nối email SMTP

Quy trình gửi được email tới lead qua kết nối hộp thư SMTP của chính công ty, như một Hành động khai
trong Bản mô tả trình kết nối (YC64; DO-48; ADR-0116 (Accepted) quyết 2).

- R7.1 KHI một quy trình gọi Hành động `email.send` của trình kết nối `smtp@1.0.0`, `SmtpEgress` PHẢI
  gửi email qua kết nối SMTP của công ty với mật khẩu lấy từ Kho bí mật.
- R7.2 NẾU `settings.is_deployed` là đúng và kết nối SMTP không bật TLS (465 hoặc STARTTLS trên 587), THÌ
  `SmtpEgress` PHẢI từ chối và không gửi.
- R7.3 NẾU host SMTP phân giải về một địa chỉ không toàn cầu, THÌ `SmtpEgress` PHẢI từ chối lúc mở kết
  nối.
- R7.4 KHI hai lời gọi `email.send` mang cùng khóa chống lặp, `SmtpEgress` PHẢI gửi chính xác một email,
  với `Message-ID` suy từ khóa chống lặp.
- R7.5 TRONG KHI lượt chạy ở chế độ khác `live`, NẾU một lời gọi `email.send` tới `SmtpEgress`, THÌ
  `SmtpEgress` PHẢI từ chối với `egress_blocked:run_mode` và không mở kết nối SMTP.

## Trong phạm vi

- Bảng và cột ở mục Dữ liệu; route ở mục API; màn hình ở mục Màn hình.
- Mã: `KmsPort`, `LocalDevKms` (chỉ ngoài profile triển khai), `OpenBaoTransitKms`, `SecretStore` và kiểu
  `Secret`; `EgressPort`, `EgressClient`, `PinnedNetworkBackend`, mở rộng `net_guard` cho địa chỉ không
  toàn cầu; module thuần `dw_connectors.webhooks` với `SignatureVerifier`; `ConnectorManifest` và bộ biên
  dịch sang Đặc tả công cụ, `ManifestActionHandler`; `SmtpEgress`; `connection_usable` một hàm;
  `ConnectionDependentsPort` (spec này khai; tenant-config đáp ứng, đọc `studio.dependencies` cộng giá trị
  Bộ giá trị gắn đã duyệt trong `platform.config_versions`; workflow-engine và agent-builder không cài);
  lane `credential_rewrap`.
- Khóa quyền, đăng ký vào Danh mục quyền trong migration của ticket dùng nó (quy ước của tenant-rbac/01):
  `connections.read`, `connections.manage` ở ticket 04; `integrations.admin` ở ticket 03.
- Audit: `connection.created`, `connection.updated`, `connection.disabled`, `connection.revoked`,
  `connection.tested`, `secret.key_mismatch`, `egress.allowlist.added`, `egress.allowlist.removed`.
- Outbox: `connection.status_changed` v1.

## Ngoài phạm vi

| Việc                                                                                                                      | Vì sao                                                                                                                                                                                                                           | Chủ                                                   |
| ------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| R4: cửa nhận Data Hub, ép lược đồ, định danh nguồn ≥128 bit, chống trùng, không tạo lượt chạy khi từ chối                 | YC42 phần endpoint; module này chỉ cấp Bộ kiểm chữ ký                                                                                                                                                                            | workflow-triggers                                     |
| W2: giới hạn tốc độ, Retry-After, backoff, cầu dao, công tắc tắt egress                                                   | `from_briefs` B8a 06; qua `RateLimiterPort` của usage-and-limits, không bộ giới hạn riêng; mất Valkey thì xô mỗi tiến trình ở hạn mức chia số replica (DO-49)                                                                    | usage-and-limits đợt sau (W2)                         |
| W2: smokescreen là lớp thứ hai trên mạng riêng, bắt buộc trước đích HTTP đầu tiên do công ty định nghĩa                   | DO-47.2: `validate_for_profile` từ chối profile triển khai bật đích HTTP của công ty khi thiếu `DW_EGRESS_PROXY_URL`; host SMTP của P1 chỉ ghim địa chỉ (R7.3); chỉ ship sau spike 21 (FOG-25, FOG-26) và khi host đã nâng (D14) | connections-and-vault đợt sau (W2)                    |
| W2: bộ điều phối OAuth và làm mới token một luồng                                                                         | YC65; `from_briefs` B8a 10, 11; P1 chỉ kết nối dùng chung, chưa có luồng cấp quyền                                                                                                                                               | connections-and-vault đợt sau (W2)                    |
| W2: định tuyến sự kiện ứng dụng nhà cung cấp theo tài khoản ngoài; cùng Page hay OA do hai công ty nối thì gửi tới cả hai | YC97; `from_briefs` B8a 13 (phần định tuyến); cần cửa `provider_app` của workflow-triggers; DO-48.2: không bật trước ý kiến luật sư (compliance-pdpl/02, câu 3 của discovery/18)                                                 | connections-and-vault đợt sau (W2); workflow-triggers |
| W2: trình kết nối Zalo OA và ZNS; Meta Lead Ads                                                                           | YC97; `from_briefs` B8a 14, 15; cần OAuth và duyệt ứng dụng                                                                                                                                                                      | connections-and-vault đợt sau (W2)                    |
| W2: kết nối cá nhân và ủy quyền; ứng dụng OAuth riêng của tổ chức                                                         | DO-48.1 chốt P1 chỉ dùng chung theo workspace; `from_briefs` B8a 17, 18                                                                                                                                                          | connections-and-vault đợt sau (W2)                    |
| W2: webhook gửi đi theo Standard Webhooks; mở rộng danh mục trình kết nối                                                 | YC24; `from_briefs` B8a 19, 20; đọc từ outbox, cần endpoint đã đăng ký; DO-58: mặc định sự kiện mỏng, dữ liệu cá nhân chỉ khi bật cho từng endpoint, có audit, áp Đã ẩn và Lộ trình dữ liệu                                      | connections-and-vault đợt sau (W2)                    |
| W2: chế độ `test` gửi thật tới Danh sách người nhận thử                                                                   | DO-26.1: W1 chỉ mở `simulate`; tới khi đó R3.5 và R7.5 từ chối mọi chế độ khác `live`                                                                                                                                            | tenant-config đợt sau (W2); connections-and-vault     |
| W3: giải mã chỉ trong dịch vụ `dw-egress`; manifest tầng tenant; BYOK (sau v1, DO-47.1) và HSM                            | `from_briefs` B8a 21, 22, 23; cần tách dịch vụ egress và PKCS#11                                                                                                                                                                 | connections-and-vault đợt sau (W3)                    |
| Sàn gửi tin kiểm đồng ý ở executor cho Hành động `effect_class: message`                                                  | ADR-0124 (Accepted); executor là một cửa, sổ đồng ý là của compliance-pdpl                                                                                                                                                       | tools-and-skills; compliance-pdpl                     |
| Khung loại công cụ, kiểm JSON Schema trong executor, bọc đầu ra không tin cậy                                             | ADR-0116 (Accepted); spec này cấp Bộ gọi ra ngoài và Kết nối cho loại `connector_action`                                                                                                                                         | tools-and-skills                                      |
| Chế độ chạy do máy chủ đặt và `run_mode` trên ngữ cảnh lượt chạy                                                          | ADR-0111 (Accepted); Bộ gọi ra ngoài và `SmtpEgress` đọc `run_mode` để từ chối mọi chế độ khác `live`                                                                                                                            | tenant-config                                         |
| Cấu hình model của tenant (BYOM qua model proxy); khóa model là bí mật                                                    | ADR-0118 (Accepted); khóa model lưu trong Kho bí mật này                                                                                                                                                                         | model-connections                                     |

## Dữ liệu

Mọi bảng: RLS ENABLE và FORCE theo tenant, grant cùng migration, tên ràng buộc theo `NAMING_CONVENTION`,
revision id hex ngẫu nhiên của alembic. Cả ba bảng là bảng toàn tenant (ADR-0100 (Accepted) quyết 5; DO-01):
không `workspace_id`, mỗi bảng một dòng có lý do trong `_TENANT_WIDE_ON_PURPOSE` của `test_rls_coverage.py`
(studio-skeleton:R9.1). Lý do: `secret_envelopes` là dòng con mà chủ thể của nó mang workspace;
`connections` và `egress_allowed_hosts` có tầm dùng vượt workspace theo thiết kế (D1). Workspace sở hữu nằm ở
`owning_workspace_id`, mà phân quyền đọc và RLS không đọc, với FK ghép `(tenant_id, owning_workspace_id)` tới
`platform.workspaces (tenant_id, id)` (`uq_workspaces_tenant_id_id` của org-and-principals/01).

- `platform.secret_envelopes`: `id` uuid; `tenant_id` NOT NULL FK `platform.tenants` ON DELETE CASCADE;
  `connection_id` uuid NULL (cung loại trừ với chủ thể khác qua CHECK); `alg text NOT NULL` CHECK
  (`aes-256-gcm`); `nonce bytea` CHECK độ dài 12; `kek_ref text NOT NULL`; `ciphertext bytea` CHECK độ
  dài ≤ 64 KiB; `aad_hint text` CHECK độ dài ≤ 64; `kek_version int NOT NULL`; `created_at`,
  `updated_at timestamptz NOT NULL`. `REVOKE ALL FROM dw_app`; chỉ các hàm SECURITY DEFINER
  `platform.put_secret`, `platform.open_secret`, `platform.secret_status`, `platform.delete_secret` (lấy
  công ty từ `app.tenant_id`, không nhận tham số công ty) có EXECUTE cho `dw_app`.
- `platform.connections`: `id` uuid; `tenant_id` NOT NULL; `owning_workspace_id` NOT NULL, FK ghép
  `(tenant_id, owning_workspace_id)` tới `platform.workspaces` ON DELETE RESTRICT, có index; `connector_key text NOT NULL`,
  `connector_major int NOT NULL`; `share_scope text NOT NULL` CHECK (`owner`, `workspace`,
  `workspace_subtree`); `external_account text`; `status text NOT NULL` CHECK (`pending`, `active`,
  `needs_reauth`, `disabled`, `revoked`), không DEFAULT; `scopes text[] NOT NULL DEFAULT '{}'`;
  `last_used_at timestamptz` NULL; `created_by`, `created_at`, `updated_at timestamptz NOT NULL`;
  trigger `platform.guard_connection_status()` cấm `revoked → active`; index danh sách
  `(tenant_id, created_at DESC, id DESC)`; partial unique một kết nối `active` cho mỗi
  `(tenant_id, connector_key, external_account)`. Trigger `touch_updated_at` nhường giá trị statement
  nêu (CLAUDE.md).
- `platform.egress_allowed_hosts`: `id`, `tenant_id`, `owning_workspace_id` (FK ghép như
  `platform.connections`); `host_pattern text` CHECK
  (`^(\*\.)?[a-z0-9.-]+$`, ≤ 253 ký tự), kiểm Public Suffix List (wildcard không đặt trên hậu tố công
  cộng), không IP literal; `ports int[] NOT NULL DEFAULT '{443}'`; `purpose text` CHECK (`http_tool`,
  `mcp`, `webhook`, `model`, `any`); `note`, `created_by`, `created_at`; UNIQUE
  `(tenant_id, host_pattern, purpose)`.

## API

- `GET`, `POST /api/v1/connections`; `GET`, `PATCH`, `DELETE /api/v1/connections/{id}`;
  `POST /api/v1/connections/{id}/test`, `.../disable`, `.../enable`;
  `GET /api/v1/connections/{id}/dependents`. Quyền `connections.read`, `connections.manage` (ticket 04 đăng
  ký); trường bí mật `writeOnly`; `Idempotency-Key` cho `POST`; DELETE còn phụ thuộc → 409
  `connection_in_use`.
- `GET /api/v1/connectors` (`connections.read`), đọc lớp nền tảng.
- `GET`, `POST`, `DELETE /api/v1/egress/allowed-hosts` (`integrations.admin`, ticket 03 đăng ký).
- Lỗi theo vỏ problem+json của ADR-0108 (Accepted); `details.reason_code`: `connection_in_use`,
  `connection_disabled`, `egress_blocked`, `kms_unavailable`, `kms_key_destroyed`, `secret_key_mismatch`.
  Id của công ty khác ở mọi route → 404.

## Màn hình

- `/studio/connections`: antd `Table` (tên, trình kết nối, tài khoản ngoài, Phạm vi dùng chung,
  Connection status bằng chữ, lần dùng gần nhất); `Drawer` thêm kết nối (API key, basic); trang chi tiết
  (sức khỏe, mã lỗi gần nhất, phạm vi đã cấp, "Được dùng bởi"); xác nhận xóa nêu tên kết nối và danh
  sách phụ thuộc; người thiếu `connections.manage` thấy nút bị tắt kèm lý do, và API vẫn chặn.
- `/studio/egress-hosts`: màn quản trị Máy chủ được phép (`integrations.admin`).

## Kiểm soát

| #    | Kiểm soát                                                                                     | Yêu cầu          | Test âm                                                                                                                                                                                                                     |
| ---- | --------------------------------------------------------------------------------------------- | ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CV1  | Phong bì gắn danh tính bằng AAD                                                               | R1.4             | Chép phong bì sang kết nối khác cùng công ty hay công ty khác → giải mã lỗi; gỡ AAD khỏi `SecretStore` → test đỏ                                                                                                            |
| CV2  | Một cửa cơ sở dữ liệu, `dw_app` không đọc thẳng                                               | R1.3, R1.6       | `SELECT * FROM platform.secret_envelopes` bằng `dw_app` → permission denied; catalog export của offboarding không liệt kê `secret_envelopes`                                                                                |
| CV3  | Khóa suy từ công ty của ngữ cảnh                                                              | R1.5             | Dòng mang `kek_ref` của công ty khác → từ chối, audit `secret.key_mismatch`; bỏ kiểm `kek_ref` → test đỏ                                                                                                                    |
| CV4  | Bí mật không rò ra response, trạng thái, trace, log, audit                                    | R1.2             | Mock nhà cung cấp vọng header và key trong body lỗi → 0 lần xuất hiện ở checkpoint, `tool_executions`, audit, span, log; tắt che → test đỏ                                                                                  |
| CV5  | LocalDevKms chỉ chạy ngoài profile triển khai                                                 | R2.2             | `DW_KMS_PROVIDER=local` với profile `uat` → `RuntimeError` lúc khởi động; gỡ `validate_for_profile` → test đỏ                                                                                                               |
| CV6  | Xóa bằng hủy khóa khi offboarding                                                             | R2.3             | Sau offboarding, giải mã một phong bì từ dump trước đó → `kms_key_destroyed`; bỏ bước hủy khóa → giải mã vẫn được, test đỏ                                                                                                  |
| CV7  | Egress chặn địa chỉ không toàn cầu lúc ghim                                                   | R3.1, R3.2       | Resolver giả trả IP công khai lần đầu, IP nội bộ lần sau → bị chặn lúc kết nối; `100.64.0.1`, `224.0.0.1`, `::ffff:169.254.169.254` → chặn; gỡ ghim → test đỏ                                                               |
| CV8  | Chuyển hướng kiểm lại, bỏ header xác thực khi đổi origin                                      | R3.3, R3.4       | Redirect tới `http://169.254.169.254/` hay host ngoài danh sách → chặn, không gửi; mock origin khác không thấy `Authorization`                                                                                              |
| CV9  | Không có client HTTP thô                                                                      | R3.6             | Thêm `httpx.AsyncClient(` vào một module mới ngoài danh sách → test kiến trúc đỏ                                                                                                                                            |
| CV10 | Chế độ khác `live` không gọi ra ngoài                                                         | R3.5, R7.5       | Gọi egress với `run_mode` `simulate` và `test`, purpose `connector` → `egress_blocked:run_mode`; `email.send` tới `SmtpEgress` ở `test` → từ chối, không mở kết nối SMTP; gỡ bước kiểm chế độ ở một trong hai lớp → test đỏ |
| CV11 | Bộ kiểm chữ ký từ chối sai chữ ký, lệch giờ, token sai                                        | R4.2, R4.3       | Vector Standard Webhooks qua; sửa một byte trượt; dấu thời gian lệch quá 5 phút trượt; token tĩnh sai trượt; gỡ kiểm dấu thời gian → test đỏ                                                                                |
| CV12 | API kết nối không trả bí mật                                                                  | R5.2             | Duyệt mọi schema 2xx của router kết nối: không trường bí mật; `GET` sau khi tạo không chứa giá trị canary                                                                                                                   |
| CV13 | Cách ly tenant cho kết nối                                                                    | R5.3             | Công ty B gọi `GET`, `PATCH`, `DELETE`, `test` với id của công ty A → 404; mock nhà cung cấp không nhận gì                                                                                                                  |
| CV14 | Phạm vi workspace của kết nối                                                                 | R5.4             | Lượt chạy ở một workspace dùng kết nối `workspace` của workspace khác → từ chối ở phát hành và ở Bộ gọi ra ngoài; gỡ kiểm workspace → test đỏ                                                                               |
| CV15 | Tắt hay thu hồi có hiệu lực trước lần gọi sau                                                 | R5.5, R5.6       | Kết nối `disabled` → `connection_disabled` ở egress; `revoked → active` bị trigger từ chối; gỡ kiểm trong `connection_usable` → test đỏ                                                                                     |
| CV16 | Manifest không có input nhạy cảm, không tự thử lại                                            | R6.2             | Manifest có `api_key` trong input → nạp từ chối; `max_retries: 2` → nạp từ chối; gỡ luật nạp → test đỏ                                                                                                                      |
| CV17 | Đầu ra Hành động bọc và cắt đúng một lần, ở bộ bọc của executor                               | R6.3             | Chạy Hành động qua `ToolExecutor` với đầu ra chứa `</tool_output><system>` → model nhận `&lt;/tool_output&gt;`, không bao giờ `&amp;lt;`; `ManifestActionHandler` trả kết quả thô; thêm bọc vào handler → test đỏ           |
| CV18 | SMTP ghim địa chỉ, TLS khi triển khai, một email mỗi khóa                                     | R7.2, R7.3, R7.4 | Host SMTP phân giải về IP nội bộ → chặn; không TLS khi triển khai → từ chối; cùng khóa chống lặp hai lần → một email                                                                                                        |
| CV19 | Chỉ tới Máy chủ được phép, wildcard không trên hậu tố công cộng                               | R3.7, R3.8       | Host ngoài danh sách (purpose `http_tool`) → `egress_blocked:host_not_allowed`; `*.com.vn` → 422; `203.0.113.5` → 422; gỡ kiểm danh sách → test đỏ                                                                          |
| CV20 | Diễn tập khôi phục thấy kho khóa; bản sao lưu kho khóa không sống lâu hơn bản sao lưu dữ liệu | R2.7, R2.8       | Diễn tập chỉ khôi phục `dw` → giải mã canary thất bại, test đỏ; hạn giữ bản sao lưu kho khóa dài hơn `BACKUP_KEEP_DAYS` của `dw` → kiểm cấu hình đỏ                                                                         |

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
  allowlist antd cho `/studio/connections`.
- `.claude/plans/studio/foundations-hardening/issues/03-quyen-dw-app-va-rls-initplan.md`: hình policy RLS
  và grant của `dw_app`; `foundations-hardening/05`: biến mạng và kho dữ liệu.
- `.claude/plans/studio/org-and-principals/issues/01-khoa-don-vi-va-siet-realm.md`: `uq_workspaces_tenant_id_id`
  làm đích cho FK ghép `(tenant_id, owning_workspace_id)` của ticket 02 và 03.
- `.claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md`: danh sách bảng toàn
  tenant của test phủ RLS (studio-skeleton:R9.1, studio-skeleton:R9.4) mà ticket 02 và 03 thêm dòng vào.
- `.claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md`: `run_mode` trên
  ngữ cảnh lượt chạy mà Bộ gọi ra ngoài và `SmtpEgress` đọc để từ chối mọi chế độ khác `live`
  (tenant-config:R4.1, tenant-config:R5.1).
- `.claude/plans/studio/tenant-rbac/issues/01-mot-chu-cho-quyen.md`: Danh mục quyền mà ticket 03 và 04 đăng ký
  khóa vào; `tenant-rbac/02`: quyền hiệu lực theo độ sâu (`platform.effective_grants`) mà `connections.read`,
  `connections.manage` và `integrations.admin` được kiểm qua.
- `.claude/plans/studio/tools-and-skills/issues/02-toolset-va-cong-cu-ghim.md`: Đặc tả công cụ, `ToolExecutor`
  và bộ bọc đầu ra mà Hành động `connector_action` của ticket 05 chạy qua (tools-and-skills:R2.1,
  tools-and-skills:R5.1).
- `.claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md`: `RunBindingsPort` đáp ứng
  từ mục `bindings` của bản kê lượt chạy, mà ticket 05 dùng.
- Protocol do bên dùng khai: `RunBindingsPort` (tenant-config/05 đáp ứng từ bản kê, ADR-0110 (Accepted));
  `ConnectionDependentsPort` (spec này khai, tenant-config/05 đáp ứng theo tenant-config:R3.7).
- Kiểm lại khi: kết quả FOG-25 (Transit, mở niêm phong không người) → R2, ticket 06; kết quả FOG-26 → dòng
  smokescreen ở Ngoài phạm vi; luật sư bác gửi tới cả hai công ty (DO-48.2) → dòng định tuyến W2;
  `connection_usable` đổi hình hợp đồng → ticket 04, 05; `run_mode` đổi giá trị hay chỗ đọc → R3.5, R7.5,
  ticket 03, 05; `RunBindingsPort` đổi hình → ticket 05.

## Câu hỏi còn mở

- Q2. Thời hạn lưu giữ cho các kho mới (phong bì bí mật, kết nối đã thu hồi 90 ngày) có theo artifact lưu
  giữ của DO-52 không? Chủ: counsel và Đạt. Không đổi: hình bảng W1; thời hạn vào lane lưu giữ ở W2.

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

## Danh sách ticket

| #   | Ticket                                                                                                                                       |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Hồ sơ ứng dụng và duyệt của nhà cung cấp: Meta, Zalo OA và ZNS](issues/01-ho-so-ung-dung-nha-cung-cap.md)                                   |
| 02  | [Kho bí mật: KmsPort, LocalDevKms, secret_envelopes và cửa một chiều](issues/02-kho-bi-mat-va-openbao.md)                                    |
| 03  | [Egress client ghim IP, danh sách máy chủ được phép và module chữ ký webhook](issues/03-egress-client-allowlist-va-chu-ky.md)                |
| 04  | [Kết nối dùng chung theo workspace: quy tắc dùng được, API, màn Kết nối, audit](issues/04-ket-noi-dung-chung-theo-workspace.md)              |
| 05  | [Manifest dw.connector/v1 biên dịch thành ToolSpec và trình kết nối email SMTP](issues/05-manifest-va-ket-noi-email.md)                      |
| 06  | [OpenBao Transit: khóa khi triển khai, xoay khóa, hủy khóa, sao lưu và diễn tập khôi phục](issues/06-openbao-transit-va-sao-luu-kho-khoa.md) |
