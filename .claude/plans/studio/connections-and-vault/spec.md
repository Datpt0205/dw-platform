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
đường email SMTP, cùng hồ sơ duyệt ứng dụng nhà cung cấp bắt đầu từ tuần đầu (ADR-0115 (Proposed),
ADR-0110 (Proposed), ADR-0116 (Proposed)).

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
bao giờ rời Kho bí mật ra một đường ra nào (YC61; ADR-0115 (Proposed) quyết 1).

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

### R2 — Khóa khi triển khai và xóa bằng hủy khóa

Khi triển khai, Khóa của công ty nằm trong OpenBao Transit; giải mã vẫn đóng khi dịch vụ khóa hỏng; và
offboarding hủy khóa để phong bì cũ không giải được (YC61; D14; DO-47; ADR-0115 (Proposed) quyết 1).

- R2.1 ĐỐI VỚI profile triển khai, `KmsPort` PHẢI bọc và mở khóa dữ liệu qua OpenBao Transit.
- R2.2 NẾU `settings.is_deployed` là đúng và `DW_KMS_PROVIDER` là `local`, THÌ api và worker PHẢI từ chối
  khởi động với `RuntimeError`.
- R2.3 KHI lane `offboarding` xóa một công ty, lane `offboarding` PHẢI gọi hủy Khóa của công ty ở bước
  cuối, để giải mã một phong bì của công ty đó sau đó trả `kms_key_destroyed`.
- R2.4 NẾU dịch vụ khóa không sẵn sàng, THÌ lời gọi giải mã PHẢI trả `kms_unavailable` và không ghi dòng
  rõ nào.

### R3 — Bộ gọi ra ngoài ghim địa chỉ, chặn địa chỉ không toàn cầu

Mọi lời gọi ra ngoài của lưu lượng tới tenant đi qua một bộ gọi ghim địa chỉ đã kiểm, chỉ tới địa chỉ
Internet toàn cầu trong danh sách được phép, kể cả sau chuyển hướng hay đổi DNS (YC63, YC34;
ADR-0115 (Proposed) quyết 5).

- R3.1 KHI mở một kết nối TCP ra ngoài, Bộ gọi ra ngoài PHẢI phân giải host một lần, ghim địa chỉ IP đã
  kiểm cho kết nối đó, và xác minh TLS theo hostname.
- R3.2 NẾU địa chỉ đích không phải địa chỉ Internet toàn cầu — gồm private, loopback, link-local, CGNAT
  `100.64.0.0/10`, multicast, và các dạng IPv4 nhúng `::ffff:`, 6to4, Teredo, NAT64 `64:ff9b::/96` —
  THÌ Bộ gọi ra ngoài PHẢI từ chối với `egress_blocked:address` và không gửi byte nào.
- R3.3 NẾU một chuyển hướng trỏ tới host ngoài danh sách được phép hoặc tới địa chỉ không toàn cầu, THÌ
  Bộ gọi ra ngoài PHẢI kiểm lại, từ chối và không gửi tiếp.
- R3.4 KHI một chuyển hướng đổi origin, Bộ gọi ra ngoài PHẢI bỏ header `Authorization` và `Cookie`
  trước khi gửi bước kế.
- R3.5 TRONG KHI lượt chạy ở chế độ `simulate`, NẾU một lời gọi mang purpose `connector`, `http_tool`
  hay `webhook`, THÌ Bộ gọi ra ngoài PHẢI từ chối với `egress_blocked:run_mode` và không gọi nhà cung
  cấp.
- R3.6 Test kiến trúc PHẢI đỏ khi một module ngoài danh sách adapter vận hành tạo `httpx.AsyncClient`
  trực tiếp.
- R3.7 NẾU đích của một purpose khác `connector` và `oauth` không nằm trong Máy chủ được phép của công
  ty, THÌ Bộ gọi ra ngoài PHẢI từ chối với `egress_blocked:host_not_allowed` và không gửi byte nào.
- R3.8 NẾU một mẫu Máy chủ được phép đặt wildcard trên một hậu tố công cộng, hoặc là một IP literal, THÌ
  API quản trị PHẢI trả 422 và không thêm dòng.

### R4 — Bộ kiểm chữ ký webhook

Một module thuần kiểm chữ ký cho mọi cửa nhận sự kiện, từ chối sai chữ ký và lệch giờ (YC42;
ADR-0115 (Proposed) quyết 6).

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
(YC62; DO-48; ADR-0115 (Proposed) quyết 2).

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
gọi ra ngoài, với đầu ra bọc là dữ liệu từ bên ngoài (YC48, YC64; ADR-0116 (Proposed) quyết 2).

- R6.1 KHI nạp một Bản mô tả trình kết nối `dw.connector/v1`, bộ nạp PHẢI biên dịch mỗi Hành động thành
  một Đặc tả công cụ lớp nền tảng có input và output JSON Schema, Mức tác động và `max_retries` là 0.
- R6.2 NẾU một Bản mô tả khai một trường bí mật trong input, hoặc `max_retries` khác 0, THÌ bộ nạp PHẢI
  từ chối và không đăng ký Hành động nào.
- R6.3 KHI một Hành động trả kết quả cho model, `ManifestActionHandler` PHẢI bọc kết quả là dữ liệu từ
  bên ngoài theo ADR-0010 (Accepted) và cắt ở 16 KiB (16 384 ký tự thì giữ, byte thứ 16 385 thì cắt).
- R6.4 KHI chạy một Hành động, `ManifestActionHandler` PHẢI lấy Kết nối qua `RunBindingsPort` theo tên
  Điểm gắn, kiểm `connection_usable`, rồi gọi qua Bộ gọi ra ngoài.

### R7 — Trình kết nối email SMTP

Quy trình gửi được email tới lead qua kết nối hộp thư SMTP của chính công ty, như một Hành động khai
trong Bản mô tả trình kết nối (YC64; DO-48; ADR-0116 (Proposed) quyết 2).

- R7.1 KHI một quy trình gọi Hành động `email.send` của trình kết nối `smtp@1.0.0`, `SmtpEgress` PHẢI
  gửi email qua kết nối SMTP của công ty với mật khẩu lấy từ Kho bí mật.
- R7.2 NẾU `settings.is_deployed` là đúng và kết nối SMTP không bật TLS (465 hoặc STARTTLS trên 587), THÌ
  `SmtpEgress` PHẢI từ chối và không gửi.
- R7.3 NẾU host SMTP phân giải về một địa chỉ không toàn cầu, THÌ `SmtpEgress` PHẢI từ chối lúc mở kết
  nối.
- R7.4 KHI hai lời gọi `email.send` mang cùng khóa chống lặp, `SmtpEgress` PHẢI gửi chính xác một email,
  với `Message-ID` suy từ khóa chống lặp.

## Trong phạm vi

- Bảng và cột ở mục Dữ liệu; route ở mục API; màn hình ở mục Màn hình.
- Mã: `KmsPort`, `LocalDevKms` (chỉ ngoài profile triển khai), `OpenBaoTransitKms`, `SecretStore` và kiểu
  `Secret`; `EgressPort`, `EgressClient`, `PinnedNetworkBackend`, mở rộng `net_guard` cho địa chỉ không
  toàn cầu; module thuần `dw_connectors.webhooks` với `SignatureVerifier`; `ConnectorManifest` và bộ biên
  dịch sang Đặc tả công cụ, `ManifestActionHandler`; `SmtpEgress`; `connection_usable` một hàm;
  `ConnectionDependentsPort` (spec này khai, workflow-engine và agent-builder cài); lane
  `credential_rewrap`.
- Audit: `connection.created`, `connection.updated`, `connection.disabled`, `connection.revoked`,
  `connection.tested`, `secret.key_mismatch`, `egress.allowlist.added`, `egress.allowlist.removed`.
- Outbox: `connection.status_changed` v1.

## Ngoài phạm vi

| Việc                                                                                                      | Vì sao                                                                                     | Chủ                                                   |
| --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ | ----------------------------------------------------- |
| R4: cửa nhận Data Hub, ép lược đồ, định danh nguồn ≥128 bit, chống trùng, không tạo lượt chạy khi từ chối | YC42 phần endpoint; module này chỉ cấp Bộ kiểm chữ ký                                      | workflow-triggers                                     |
| W2: giới hạn tốc độ, Retry-After, backoff, cầu dao, công tắc tắt egress                                   | `from_briefs` B8a 06; cần `RateLimiterPort` của usage-and-limits (DO-49)                   | usage-and-limits đợt sau (W2)                         |
| W2: smokescreen là lớp thứ hai trên mạng riêng                                                            | `from_briefs` B8a 09; cần host đã resize (D14) và đo topology (DO-47)                      | connections-and-vault đợt sau (W2)                    |
| W2: bộ điều phối OAuth và làm mới token một luồng                                                         | YC65; `from_briefs` B8a 10, 11; P1 chỉ kết nối dùng chung, chưa có luồng cấp quyền         | connections-and-vault đợt sau (W2)                    |
| W2: định tuyến sự kiện ứng dụng nhà cung cấp theo tài khoản ngoài                                         | YC97; `from_briefs` B8a 13 (phần định tuyến); cần cửa `provider_app` của workflow-triggers | connections-and-vault đợt sau (W2); workflow-triggers |
| W2: trình kết nối Zalo OA và ZNS; Meta Lead Ads                                                           | YC97; `from_briefs` B8a 14, 15; cần OAuth và duyệt ứng dụng                                | connections-and-vault đợt sau (W2)                    |
| W2: kết nối cá nhân và ủy quyền; ứng dụng OAuth riêng của tổ chức                                         | DO-48 chốt P1 chỉ dùng chung theo workspace; `from_briefs` B8a 17, 18                      | connections-and-vault đợt sau (W2)                    |
| W2: webhook gửi đi theo Standard Webhooks; mở rộng danh mục trình kết nối                                 | YC24; `from_briefs` B8a 19, 20; đọc từ outbox, cần endpoint đã đăng ký                     | connections-and-vault đợt sau (W2)                    |
| W3: giải mã chỉ trong dịch vụ `dw-egress`; manifest tầng tenant; BYOK và HSM                              | `from_briefs` B8a 21, 22, 23; cần tách dịch vụ egress và PKCS#11                           | connections-and-vault đợt sau (W3)                    |
| Sàn gửi tin kiểm đồng ý ở executor cho Hành động `effect_class: message`                                  | ADR-0124 (Proposed); executor là một cửa, sổ đồng ý là của compliance-pdpl                 | tools-and-skills; compliance-pdpl                     |
| Khung loại công cụ, kiểm JSON Schema trong executor, bọc đầu ra không tin cậy                             | ADR-0116 (Proposed); spec này cấp Bộ gọi ra ngoài và Kết nối cho loại `connector_action`   | tools-and-skills                                      |
| Chế độ chạy do máy chủ đặt và `run_mode` trên ngữ cảnh lượt chạy                                          | ADR-0111 (Proposed); Bộ gọi ra ngoài đọc `run_mode` để từ chối `simulate`                  | tenant-config                                         |
| Cấu hình model của tenant (BYOM qua LiteLLM); khóa model là bí mật                                        | ADR-0118 (Proposed); khóa model lưu trong Kho bí mật này                                   | model-connections                                     |

## Dữ liệu

Mọi bảng: RLS ENABLE và FORCE theo tenant, grant cùng migration, tên ràng buộc theo `NAMING_CONVENTION`,
revision id hex ngẫu nhiên của alembic.

- `platform.secret_envelopes`: `id` uuid; `tenant_id` NOT NULL FK `platform.tenants` ON DELETE CASCADE;
  `connection_id` uuid NULL (cung loại trừ với chủ thể khác qua CHECK); `alg text NOT NULL` CHECK
  (`aes-256-gcm`); `nonce bytea` CHECK độ dài 12; `kek_ref text NOT NULL`; `ciphertext bytea` CHECK độ
  dài ≤ 64 KiB; `aad_hint text` CHECK độ dài ≤ 64; `kek_version int NOT NULL`; `created_at`,
  `updated_at timestamptz NOT NULL`. `REVOKE ALL FROM dw_app`; chỉ các hàm SECURITY DEFINER
  `platform.put_secret`, `platform.open_secret`, `platform.secret_status`, `platform.delete_secret` (lấy
  công ty từ `app.tenant_id`, không nhận tham số công ty) có EXECUTE cho `dw_app`.
- `platform.connections`: `id` uuid; `tenant_id` NOT NULL; `owner_workspace_id` NOT NULL FK
  `(tenant_id, id)` tới `platform.workspaces` ON DELETE RESTRICT; `connector_key text NOT NULL`,
  `connector_major int NOT NULL`; `share_scope text NOT NULL` CHECK (`owner`, `workspace`,
  `workspace_subtree`); `external_account text`; `status text NOT NULL` CHECK (`pending`, `active`,
  `needs_reauth`, `disabled`, `revoked`), không DEFAULT; `scopes text[] NOT NULL DEFAULT '{}'`;
  `last_used_at timestamptz` NULL; `created_by`, `created_at`, `updated_at timestamptz NOT NULL`;
  trigger `platform.guard_connection_status()` cấm `revoked → active`; index danh sách
  `(tenant_id, created_at DESC, id DESC)`; partial unique một kết nối `active` cho mỗi
  `(tenant_id, connector_key, external_account)`. Trigger `touch_updated_at` nhường giá trị statement
  nêu (CLAUDE.md).
- `platform.egress_allowed_hosts`: `id`, `tenant_id`, `owner_workspace_id`; `host_pattern text` CHECK
  (`^(\*\.)?[a-z0-9.-]+$`, ≤ 253 ký tự), kiểm Public Suffix List (wildcard không đặt trên hậu tố công
  cộng), không IP literal; `ports int[] NOT NULL DEFAULT '{443}'`; `purpose text` CHECK (`http_tool`,
  `mcp`, `webhook`, `model`, `any`); `note`, `created_by`, `created_at`; UNIQUE
  `(tenant_id, host_pattern, purpose)`.

## API

- `GET`, `POST /api/v1/connections`; `GET`, `PATCH`, `DELETE /api/v1/connections/{id}`;
  `POST /api/v1/connections/{id}/test`, `.../disable`, `.../enable`;
  `GET /api/v1/connections/{id}/dependents`. Quyền `connections.read`, `connections.manage`; trường bí
  mật `writeOnly`; `Idempotency-Key` cho `POST`; DELETE còn phụ thuộc → 409 `connection_in_use`.
- `GET /api/v1/connectors` (`connections.read`), đọc lớp nền tảng.
- `GET`, `POST`, `DELETE /api/v1/egress/allowed-hosts` (`integrations.admin`).
- Lỗi theo vỏ problem+json của ADR-0108 (Proposed); `details.reason_code`: `connection_in_use`,
  `connection_disabled`, `egress_blocked`, `kms_unavailable`, `kms_key_destroyed`, `secret_key_mismatch`.
  Id của công ty khác ở mọi route → 404.

## Màn hình

- `/studio/connections`: antd `Table` (tên, trình kết nối, tài khoản ngoài, Phạm vi dùng chung,
  Connection status bằng chữ, lần dùng gần nhất); `Drawer` thêm kết nối (API key, basic); trang chi tiết
  (sức khỏe, mã lỗi gần nhất, phạm vi đã cấp, "Được dùng bởi"); xác nhận xóa nêu tên kết nối và danh
  sách phụ thuộc; người thiếu `connections.manage` thấy nút bị tắt kèm lý do, và API vẫn chặn.
- `/studio/egress-hosts`: màn quản trị Máy chủ được phép (`integrations.admin`).

## Kiểm soát

| #    | Kiểm soát                                                       | Yêu cầu          | Test âm                                                                                                                                                       |
| ---- | --------------------------------------------------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CV1  | Phong bì gắn danh tính bằng AAD                                 | R1.4             | Chép phong bì sang kết nối khác cùng công ty hay công ty khác → giải mã lỗi; gỡ AAD khỏi `SecretStore` → test đỏ                                              |
| CV2  | Một cửa cơ sở dữ liệu, `dw_app` không đọc thẳng                 | R1.3, R1.6       | `SELECT * FROM platform.secret_envelopes` bằng `dw_app` → permission denied; catalog export của offboarding không liệt kê `secret_envelopes`                  |
| CV3  | Khóa suy từ công ty của ngữ cảnh                                | R1.5             | Dòng mang `kek_ref` của công ty khác → từ chối, audit `secret.key_mismatch`; bỏ kiểm `kek_ref` → test đỏ                                                      |
| CV4  | Bí mật không rò ra response, trạng thái, trace, log, audit      | R1.2             | Mock nhà cung cấp vọng header và key trong body lỗi → 0 lần xuất hiện ở checkpoint, `tool_executions`, audit, span, log; tắt che → test đỏ                    |
| CV5  | LocalDevKms chỉ chạy ngoài profile triển khai                   | R2.2             | `DW_KMS_PROVIDER=local` với profile `uat` → `RuntimeError` lúc khởi động; gỡ `validate_for_profile` → test đỏ                                                 |
| CV6  | Xóa bằng hủy khóa khi offboarding                               | R2.3             | Sau offboarding, giải mã một phong bì từ dump trước đó → `kms_key_destroyed`; bỏ bước hủy khóa → giải mã vẫn được, test đỏ                                    |
| CV7  | Egress chặn địa chỉ không toàn cầu lúc ghim                     | R3.1, R3.2       | Resolver giả trả IP công khai lần đầu, IP nội bộ lần sau → bị chặn lúc kết nối; `100.64.0.1`, `224.0.0.1`, `::ffff:169.254.169.254` → chặn; gỡ ghim → test đỏ |
| CV8  | Chuyển hướng kiểm lại, bỏ header xác thực khi đổi origin        | R3.3, R3.4       | Redirect tới `http://169.254.169.254/` hay host ngoài danh sách → chặn, không gửi; mock origin khác không thấy `Authorization`                                |
| CV9  | Không có client HTTP thô                                        | R3.6             | Thêm `httpx.AsyncClient(` vào một module mới ngoài danh sách → test kiến trúc đỏ                                                                              |
| CV10 | `simulate` không gọi ra ngoài                                   | R3.5             | Gọi egress với `run_mode='simulate'`, purpose `connector` → `egress_blocked:run_mode`; gỡ bước kiểm chế độ → test đỏ                                          |
| CV11 | Bộ kiểm chữ ký từ chối sai chữ ký, lệch giờ, token sai          | R4.2, R4.3       | Vector Standard Webhooks qua; sửa một byte trượt; dấu thời gian lệch quá 5 phút trượt; token tĩnh sai trượt; gỡ kiểm dấu thời gian → test đỏ                  |
| CV12 | API kết nối không trả bí mật                                    | R5.2             | Duyệt mọi schema 2xx của router kết nối: không trường bí mật; `GET` sau khi tạo không chứa giá trị canary                                                     |
| CV13 | Cách ly tenant cho kết nối                                      | R5.3             | Công ty B gọi `GET`, `PATCH`, `DELETE`, `test` với id của công ty A → 404; mock nhà cung cấp không nhận gì                                                    |
| CV14 | Phạm vi workspace của kết nối                                   | R5.4             | Lượt chạy ở một workspace dùng kết nối `workspace` của workspace khác → từ chối ở phát hành và ở Bộ gọi ra ngoài; gỡ kiểm workspace → test đỏ                 |
| CV15 | Tắt hay thu hồi có hiệu lực trước lần gọi sau                   | R5.5, R5.6       | Kết nối `disabled` → `connection_disabled` ở egress; `revoked → active` bị trigger từ chối; gỡ kiểm trong `connection_usable` → test đỏ                       |
| CV16 | Manifest không có input nhạy cảm, không tự thử lại              | R6.2             | Manifest có `api_key` trong input → nạp từ chối; `max_retries: 2` → nạp từ chối; gỡ luật nạp → test đỏ                                                        |
| CV17 | Đầu ra Hành động bọc là dữ liệu từ bên ngoài, cắt 16 KiB        | R6.3             | Đầu ra chứa `</tool_output><system>` → model nhận `&lt;/tool_output&gt;`; 16 385 ký tự → cắt; gỡ bọc → test đỏ                                                |
| CV18 | SMTP ghim địa chỉ, TLS khi triển khai, một email mỗi khóa       | R7.2, R7.3, R7.4 | Host SMTP phân giải về IP nội bộ → chặn; không TLS khi triển khai → từ chối; cùng khóa chống lặp hai lần → một email                                          |
| CV19 | Chỉ tới Máy chủ được phép, wildcard không trên hậu tố công cộng | R3.7, R3.8       | Host ngoài danh sách (purpose `http_tool`) → `egress_blocked:host_not_allowed`; `*.com.vn` → 422; `203.0.113.5` → 422; gỡ kiểm danh sách → test đỏ            |

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (ghi ở Comments của
  ticket).
- `make ci && make test-integration` xanh; `reviewing-feature-security` và `reviewing-deployment-security`
  đã chạy cho từng ticket có route, image hay URL ra ngoài; `.claude/plans/studio.md` ghi lát W1 đã xong
  và bảng trạng thái duyệt ứng dụng nhà cung cấp.

## Phụ thuộc

- `.claude/plans/studio/studio-skeleton/issues/04-chinh-sach-compose-dich-vu-moi.md`: chính sách thêm
  dịch vụ compose mới (OpenBao, sau là smokescreen) và trivy; `studio-skeleton/03`: seam web và allowlist
  antd cho `/studio/connections`.
- `.claude/plans/studio/foundations-hardening/issues/03-quyen-dw-app-va-rls-initplan.md`: hình policy RLS
  và grant của `dw_app`; `foundations-hardening/05`: biến mạng và kho dữ liệu.
- `.claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md`: `run_mode` trên
  ngữ cảnh lượt chạy mà Bộ gọi ra ngoài đọc để từ chối `simulate` (tenant-config:R4.1, tenant-config:R5.1).
- `.claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md`: ánh xạ `connections.read`,
  `connections.manage`, `connections.use`, `integrations.admin` vào vai và độ sâu
  (`platform.effective_grants`).
- `.claude/plans/studio/tools-and-skills/issues/02-toolset-va-cong-cu-ghim.md`: Đặc tả công cụ và
  `ToolExecutor` mà Hành động `connector_action` của ticket 05 chạy qua (tools-and-skills:R2.1).
- Protocol do bên dùng khai: `RunBindingsPort` (workflow-engine và agent-builder đáp ứng từ bản kê,
  ADR-0110 (Proposed)); `ConnectionDependentsPort` (spec này khai, hai spec đó cài).
- Kiểm lại khi: DO-47 chốt cách vận hành OpenBao → ticket 02; DO-48 đổi phạm vi kết nối P1 → R5, ticket
  04; `connection_usable` đổi hình hợp đồng → ticket 04, 05; `run_mode` đổi giá trị hay chỗ đọc → R3.5,
  ticket 03; `RunBindingsPort` đổi hình → ticket 05.

## Câu hỏi còn mở

- Q1. OpenBao có được nhận là dịch vụ tier-0 với đường unseal không người (lưu trữ tích hợp hay database
  riêng), mạng `dw-egress` với smokescreen ghim bản, xoay Khóa của công ty mỗi 90 ngày và BYOK ở v2
  không? Chủ: Đạt. Chặn: R2, ticket 02.
- Q2. Thời hạn lưu giữ cho các kho mới (phong bì bí mật, kết nối đã thu hồi 90 ngày) có theo artifact lưu
  giữ của DO-52 không? Chủ: counsel và Đạt. Không đổi: hình bảng W1; thời hạn vào lane lưu giữ ở W2.

## Quyết định

- 22/10/2026 (người yêu cầu): S10: kho bí mật mã hóa phong bì dưới Khóa của công ty trong OpenBao Transit
  sau `KmsPort`, một Bộ gọi ra ngoài ghim IP cộng smokescreen làm lớp thứ hai (ADR-0115 (Proposed) quyết
  1, 5). Sửa: R1, R3.
- 23/10/2026 (người yêu cầu): D14 (DO-24): resize host chính lên ít nhất 4 vCPU / 16 GB trước khi OpenBao
  và egress proxy triển khai; đo trước khi cố định kích thước. Sửa: R2.
- 23/10/2026 (agent, tạm): DO-20 theo khuyến nghị (a): nền tảng sở hữu ứng dụng Meta và Zalo (một ứng
  dụng mỗi môi trường), khách dùng Page và OA của họ qua OAuth, ứng dụng Google nội bộ của khách; duyệt
  bắt đầu tuần đầu. Sửa: ticket 01. Nếu sai thì: đổi chủ ứng dụng và callback trong ticket 01, 14, 15.
- 23/10/2026 (agent, tạm): DO-48 theo khuyến nghị (a): SMTP chung là đường email P1 (Gmail API ở P2); chỉ
  kết nối dùng chung theo workspace (không kết nối cá nhân hay ủy quyền ở P1); cùng một Page hay OA do hai
  công ty kết nối thì fan-out tới cả hai, counsel xác nhận. Sửa: R5, R7, Ngoài phạm vi. Nếu sai thì:
  thêm kết nối cá nhân và `connection_delegations` vào P1 (B8a ticket 17).
- 23/10/2026 (agent, tạm): khóa quyền `connections.read`, `connections.manage`, `connections.use`,
  `integrations.admin` theo dạng của tenant-rbac/01. Sửa: R5, mục API. Nếu sai thì: đổi tên khóa ở R5 và
  ticket 04 theo danh mục của tenant-rbac.

## Danh sách ticket

| #   | Ticket                                                                                                                          |
| --- | ------------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Hồ sơ ứng dụng và duyệt của nhà cung cấp: Meta, Zalo OA và ZNS, Google](issues/01-ho-so-ung-dung-nha-cung-cap.md)              |
| 02  | [Kho bí mật: KmsPort, LocalDevKms, secret_envelopes và OpenBao Transit](issues/02-kho-bi-mat-va-openbao.md)                     |
| 03  | [Egress client ghim IP, danh sách máy chủ được phép và module chữ ký webhook](issues/03-egress-client-allowlist-va-chu-ky.md)   |
| 04  | [Kết nối dùng chung theo workspace: quy tắc dùng được, API, màn Kết nối, audit](issues/04-ket-noi-dung-chung-theo-workspace.md) |
| 05  | [Manifest dw.connector/v1 biên dịch thành ToolSpec và trình kết nối email SMTP](issues/05-manifest-va-ket-noi-email.md)         |
