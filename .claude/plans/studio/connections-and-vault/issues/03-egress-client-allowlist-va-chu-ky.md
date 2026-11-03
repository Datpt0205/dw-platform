# 03 — Egress client ghim IP, kết quả có kiểu, danh sách máy chủ được phép và module chữ ký webhook

Status: ready-for-agent
Blocked by: 02, .claude/plans/studio/runtime-hardening/issues/02-bien-mang-va-kho-du-lieu.md, .claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md, .claude/plans/studio/tenant-rbac/issues/01-mot-chu-cho-quyen.md, .claude/plans/studio/org-and-principals/issues/01-khoa-don-vi-va-siet-realm.md, .claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md
Area: studio
Yêu cầu: R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R3.8, R3.9, R3.10, R3.11, R3.12, R3.13, R3.14, R3.15, R3.16, R3.17, R3.18, R3.19, R3.20, R3.21, R4.1, R4.2, R4.3, R4.4, CV7, CV8, CV9, CV10, CV11, CV19, CV22, CV26, CV29, CV30

## Mục tiêu

Mọi lời gọi ra ngoài của lưu lượng tới tenant đi qua một bộ gọi ghim địa chỉ đã kiểm, chỉ tới địa chỉ
Internet toàn cầu trong danh sách được phép, kể cả sau chuyển hướng hay đổi DNS; và một module thuần
kiểm chữ ký cho mọi cửa nhận sự kiện (spec R3, R4). W1 từ chối mọi chế độ khác `live` ở egress làm lớp
thứ hai sau executor của tenant-config/03 (DO-26.1). Mỗi lời gọi kết thúc bằng một kết quả có kiểu mà ToolExecutor
(runtime-hardening:R6.12) và wrapper nút (workflow-engine:R4.23) đọc, và egress không bao giờ tự gửi lại một lời gọi
không rõ kết quả (spec R3.13-R3.16; V4.30). Gộp từ B8a-connections connections-and-vault 02, 08 và 13 (phần module
chữ ký).

## Việc cần làm

1. Dùng lại chính sách địa chỉ đã có một chủ, không viết lại (runtime-hardening/02, `34768e7`; failure-modes #2):
   `forbidden_address(ip, *, allow_private=False) -> bool` và `resolve_checked(host, port, *, allow_private=False)
-> list[str]` của `packages/python/dw_kernel/src/dw_kernel/net_guard.py` đã chuẩn hóa IPv4-mapped, 6to4, Teredo,
   NAT64, đã từ chối khi một câu trả lời bất kỳ bị cấm, và `allow_private` không bao giờ mở link-local. Không đổi chữ
   ký của hai hàm. Egress không đọc `outbound_allowed_hosts` của settings: danh sách đó cho host qua theo tên mà không
   phân giải và chỉ dành cho URL gốc người vận hành cấu hình; lưu lượng tới tenant chỉ theo Máy chủ được phép (R3.7,
   R3.21) và `egress_hosts` (R3.17).
2. Gói egress (`dw_connectors.egress`): `EgressRequest` (mang thêm `secret_values`, các giá trị bên gọi đã đặt vào
   header hay body, để che; không bao giờ ghi log), `EgressContext(tenant_id, workspace_id, run_id,
run_mode, purpose, connector_key, connection_id, simulate_safe)` (`run_mode` và `purpose` bắt buộc, không mặc định;
   `simulate_safe` mặc định false, như tenant-config:R5.5), `EgressResponse`, `EgressPort`, `EgressClient`;
   `PinnedNetworkBackend` trên `httpcore.AsyncNetworkBackend.connect_tcp` ghim địa chỉ, TLS SNI theo
   hostname; `httpx.AsyncClient(trust_env=False, follow_redirects=False)`. `EgressClient` nhận `allow_private` qua
   constructor; chỉ composition root của api và worker đặt nó, bằng `not settings.is_deployed`, không có biến môi trường
   riêng. Egress khai `CatalogueHostsPort.egress_hosts(connector_key) -> frozenset[str]` (bên dùng khai); W1 gắn một
   cài đặt trả tập rỗng cho mọi khóa, nên R3.17 từ chối mọi lời gọi `connector` và `oauth` tới khi trình kết nối HTTP
   đầu tiên (W2, spec "Ngoài phạm vi") gắn `egress_hosts` của Bản mô tả. Ticket này không mở bí mật và không gọi
   `connection_usable`: bên gọi (ticket 04, 05) làm việc đó trước khi gọi egress.
3. Chuyển hướng theo manifest (`none` mặc định, `same_origin`, `revalidate`), tối đa 3 bước, mỗi bước
   `resolve_checked` lại, kiểm `https` khi `settings.is_deployed` (R3.20) và kiểm danh sách; bỏ `Authorization`,
   `Cookie` khi đổi origin; trần body 2 MiB đếm khi stream trên byte đã giải nén; tổng thời gian trong
   `timeout_seconds` của công cụ.
4. `run_mode` khác `live` (`simulate`, và `test` mà W1 chưa mở) → từ chối mọi purpose trừ `model` và lời gọi purpose
   `connector` hay `http_tool` mang `simulate_safe` đúng (tenant-config:R5.4; Hành động chỉ đọc là `simulate_safe`,
   `packages/python/dw_agent_runtime/src/dw_agent_runtime/tool_specs.py:126`, không có cờ chỉ đọc riêng); mọi lời gọi `mcp`,
   `oauth` và `webhook` bị từ chối dù cờ ra sao; mã `egress_blocked:run_mode`; `run_mode` và cờ `simulate_safe` lấy từ
   `EgressContext` (tenant-config/03 đặt trên ngữ cảnh lượt chạy); W2 mới mở `test` cho Danh sách người nhận thử
   (DO-26.1).
5. Span `dw.egress.request`, metric `dw_egress_requests_total`, `dw_egress_blocked_total`; che `secret_values` của
   lời gọi theo giá trị (thô, mã hóa URL, base64) trong body, lỗi và log; filter logger `httpx` bỏ query string.
6. Test kiến trúc (AST) trên `packages/python/*/src` và `apps/*/src`: `httpx.AsyncClient(` và `httpx.Client(` chỉ ở
   các adapter vận hành liệt kê (`openai_compatible.py`, `openai_responses.py`, `zalo_bot.py`, `api_parsers.py`,
   `cohere_rerank.py`, `openai_embedding.py`, và `mailpit_mailbox.py`, hộp thư giả của dev) và gói egress; `scripts/`
   (công cụ người vận hành chạy tay, như `keycloak_dev_users.py`) ngoài phạm vi quét.
7. Migration (revision hex): `platform.egress_allowed_hosts` theo mục Dữ liệu của spec, nguyên văn: `id` bằng id yêu
   cầu phê duyệt; `owning_workspace_id` NOT NULL, workspace của yêu cầu phê duyệt, với FK ghép
   `(tenant_id, owning_workspace_id)` tới `uq_workspaces_tenant_id_id` của org-and-principals/01, ON DELETE RESTRICT,
   có index; `host_pattern text` NOT NULL CHECK (`^(\*\.)?[a-z0-9.-]+$`, ≤ 253 ký tự, và `!~ '^[0-9.]+$'` để chặn IP
   literal cả với lần ghi thẳng), kiểm Public Suffix List ở API (wildcard không đặt trên hậu tố công cộng, kể cả phần
   PRIVATE như `github.io`; bản danh sách ghim trong gói, không tải lúc chạy), sau khi `POST` chuẩn hóa mẫu như R3.21
   (chữ thường, bỏ dấu chấm cuối, IDN sang A-label), và payload phê duyệt mang dạng đã chuẩn hóa; `created_by` là
   người gửi, người duyệt nằm ở audit `egress.allowlist.added`; `ports int[] NOT NULL DEFAULT '{443}'`; `purpose`
   NOT NULL CHECK (`http_tool`, `mcp`, `webhook`, `model`, `any`); `removed_at`, `removed_by` cùng NULL hay cùng có;
   UNIQUE từng phần `(tenant_id, host_pattern, purpose) WHERE removed_at IS NULL`; RLS ENABLE và FORCE theo tenant;
   grant `dw_app` SELECT, INSERT, UPDATE cột `removed_at`, `removed_by`, DELETE (chỉ lane `offboarding` dùng, nên
   `test_offboarding_coverage.py` thấy bảng được xuất và xóa như bảng thường, không cần dòng loại trừ); một dòng có lý
   do cho bảng trong `_TENANT_WIDE_ON_PURPOSE` của `test_rls_coverage.py` (studio-skeleton/01); đăng ký
   khóa `integrations.admin` vào Danh mục quyền trong cùng migration, câu INSERT nêu mọi cột NOT NULL có lúc đó:
   `area` `integrations`, nhãn tiếng Việt, `scope_kind` `tenant` (một dòng mở egress cho mọi workspace của công ty),
   `risk` `elevated`, `status` `active`, `tenant_grantable` đúng (tenant-rbac/01, tenant-rbac/02); routes `GET`,
   `POST /api/v1/egress/allowed-hosts`, `DELETE /api/v1/egress/allowed-hosts/{id}` (`integrations.admin`); Bộ gọi ra
   ngoài kiểm danh sách cho mọi purpose khác `connector` và `oauth`, đọc bảng ở mỗi lời gọi (không bộ đệm trong tiến
   trình), khớp theo R3.21: host chuẩn hóa (chữ thường, bỏ dấu chấm cuối, IDN sang A-label) bằng mẫu, hay mẫu
   `*.<miền>` với đúng một nhãn trước `<miền>` (không khớp chính `<miền>`), cổng trong `ports`, `purpose` trùng hay
   `any`, `removed_at` NULL.
    - `POST` kiểm R3.8, rồi hỏi `platform.checker_candidates` của tenant-rbac/02 với khóa `integrations.admin`,
      người gửi và workspace đang làm việc: rỗng → 409 `conflict` với `details.reason_code`
      `no_checker_available`, không mở yêu cầu (R3.12); không thì trả 202 với một yêu cầu phê duyệt không lượt
      chạy `egress.allowed_host`, `required_scope` `integrations.admin`, payload chỉ mang mẫu máy chủ, cổng,
      purpose và ghi chú; chưa ghi dòng nào. `egress.allowed_host` vào `strict_approval_prefixes` bằng `|=` ở API
      và worker, nên người gửi tự quyết nhận 409 `conflict` với `details.reason_code` `second_person_required`
      của tiền tố nghiêm (R3.10; ADR-0104 (Accepted) quyết 11).
    - Handler `egress.allowed_host.decided` đăng ký ở composition root của worker, chạy lặp lại không đổi kết
      quả theo id phê duyệt: duyệt → `INSERT ... ON CONFLICT DO NOTHING` một dòng có `id` là id phê duyệt, và chỉ khi
      có dòng mới thì audit `egress.allowlist.added` đứng tên người quyết, `details.lane` `outbox`, trong cùng giao
      dịch; xung đột (phát lại, kể cả sau khi dòng đã gỡ; hay mẫu đó đã có dòng sống từ yêu cầu khác) → không ghi gì,
      kết thúc không lỗi để outbox không thử lại; từ chối → không ghi gì.
    - `DELETE /api/v1/egress/allowed-hosts/{id}` một người, có hiệu lực ngay: đặt `removed_at`, `removed_by` cùng audit
      `egress.allowlist.removed` trong một giao dịch (R3.18); id của công ty khác → 404, người không giữ
      `integrations.admin` → 403 (R3.19); dòng đã gỡ → 404. `GET` chỉ trả dòng có `removed_at` NULL.
8. Module thuần `dw_connectors.webhooks`: `InboundMessage`, `VerifierKey(secret, version, not_after)` (`not_after`
   là `revoked_at` của phiên bản, NULL khi chưa thu hồi), `Verdict`, `SignatureVerifier`, bảng `VERIFIERS` của W1
   (`standard_webhooks_v1`, `static_header_token`, hai lược đồ mà workflow-triggers:R5.2 dùng; `standard_webhooks_v1a`,
   `meta_x_hub_signature_256`, `zalo_oa_zevent` vào cùng bên dùng đầu tiên ở W2, spec "Ngoài phạm vi"),
   `sign_standard_webhook()`; cửa sổ dấu thời gian ±5 phút theo đồng hồ tiêm vào; khóa có `not_after` đã qua bị bỏ
   trong bộ kiểm, không ở bên gọi (một chủ cho hạn 24 giờ); so token theo thời gian hằng định; lược đồ không có trong
   `VERIFIERS` → `rejected`.
9. Kết quả có kiểu (spec R3.13-R3.16; ADR-0115 (Accepted) quyết 6; V4.30): `EgressClient` trả `EgressResponse` cho
   `succeeded`, hay ném một trong ba lỗi của runtime-hardening/01 bước 3 (`NotDispatchedError`, `RejectedError` mang
   mã, `OutcomeUnknownError`), không lớp lỗi riêng nào khác:
    - chuyển định nghĩa ba lớp từ `packages/python/dw_agent_runtime/src/dw_agent_runtime/dispatch.py` sang một module
      của `dw_kernel` (chỉ stdlib, cạnh `DWError`), và `dw_agent_runtime.dispatch` xuất lại đúng các lớp đó (cùng đối
      tượng, nên ToolExecutor và test của runtime-hardening/01 không đổi): `dw_agent_runtime` đã phụ thuộc
      `dw_connectors`, nên egress nhập từ `dw_agent_runtime` là một vòng phụ thuộc gói (spec R3.13);
    - module thuần `dw_connectors.egress.outcome` giữ một bảng phân loại theo pha của lời gọi, một chủ cho cả HTTP và
      SMTP (ticket 05 dùng lại cho `SmtpEgress`): dừng trước byte đầu tiên của yêu cầu đầu tiên (phân giải, kết nối,
      bắt tay TLS, `egress_blocked:*` trước byte đó, `credential_revoked` do bên gọi ném qua module này) →
      `NotDispatchedError` mang mã đó; HTTP dừng sau byte đó mà không nhận trọn 2xx hay 4xx trong trần 2 MiB (hết thời
      gian, reset, 5xx, 3xx không theo, chuyển hướng bị chặn ở bước sau, body vượt trần) → `OutcomeUnknownError` mang mã
      của lần dừng; HTTP 4xx → `RejectedError` mang trạng thái; SMTP dừng
      trước dấu kết thúc dữ liệu của `DATA` → `NotDispatchedError`; trả lời 4yz, 5yz → `RejectedError` mang mã SMTP;
      đã gửi dấu kết thúc dữ liệu mà chưa nhận 250 → `OutcomeUnknownError`;
    - `PinnedNetworkBackend` ghi nhận byte đầu tiên đã ghi ra socket, để pha "đã gửi" là sự thật đo được, không suy từ
      loại ngoại lệ của `httpx`;
    - egress chỉ tự thử lại ở pha trước byte đầu tiên (thử lại kết nối), không bao giờ sau đó; lỗi khác ném ra từ
      egress không được nuốt, để ToolExecutor ghi nó `outcome_unknown` theo runtime-hardening:R6.12.

## Tiêu chí chấp nhận

- [ ] R3.1 (CV7): resolver giả trả IP công khai lần đầu, IP nội bộ từ lần sau; tầng mạng giả dưới
      `PinnedNetworkBackend` ghi địa chỉ được mở → `EgressClient` mở đúng IP công khai đã kiểm, không bao giờ IP nội
      bộ, và SNI là hostname; gỡ ghim để `httpcore` tự phân giải lại → tầng giả ghi IP nội bộ, test đỏ.
- [ ] R3.2 (CV7): `EgressClient` gọi một host mà resolver giả trả `100.64.0.1`, `169.254.169.254`, `224.0.0.1`,
      `::ffff:169.254.169.254`, `64:ff9b::a9fe:a9fe`, `2002:a9fe:a9fe::1` → `egress_blocked:address`, tầng mạng giả
      không mở kết nối nào; `8.8.8.8`, `2606:4700:4700::1111` qua; `EgressClient` dựng với settings triển khai có
      `allow_private` sai, và một host trả `10.0.0.5` bị chặn ở đó; bỏ lời gọi `resolve_checked` khỏi egress → test đỏ.
- [ ] R3.3 (CV8): redirect tới `http://169.254.169.254/` hay host ngoài danh sách → chặn, không gửi; gỡ
      kiểm lại chuyển hướng → test đỏ.
- [ ] R3.4 (CV8): redirect đổi origin → mock origin khác không thấy `Authorization` hay `Cookie`.
- [ ] R3.5 (CV10): gọi egress với `run_mode` `simulate` và `test`, purpose `connector`, `http_tool`,
      `webhook`, `mcp` và `oauth` → `egress_blocked:run_mode`, không gọi nhà cung cấp; purpose `model` và lời
      gọi `http_tool` của một Hành động khai chỉ đọc ở `simulate` vẫn qua; lời gọi `oauth` hay `mcp` mang
      `simulate_safe` đúng ở `simulate` → vẫn `egress_blocked:run_mode`; `live` → qua; gỡ bước kiểm chế độ, hay cho
      `simulate_safe` miễn mọi purpose → test đỏ.
- [ ] R3.6 (CV9): thêm `httpx.AsyncClient(` vào một module mới ngoài danh sách → test kiến trúc đỏ.
- [ ] R3.7 (CV19): đích host ngoài danh sách (purpose `http_tool`) → `egress_blocked:host_not_allowed`;
      host có trong `outbound_allowed_hosts` của settings mà không trong danh sách của công ty → vẫn
      `host_not_allowed`; gỡ kiểm danh sách → test đỏ.
- [ ] R3.21 (CV19): dòng `*.acme.vn` cổng `{443}` purpose `http_tool` → `api.acme.vn:443` và `API.Acme.vn.` qua;
      `acme.vn`, `a.b.acme.vn`, `api.acme.vn:8443`, purpose `mcp`, và dòng đã có `removed_at` →
      `host_not_allowed`; gỡ kiểm cổng hay khớp một nhãn → test đỏ.
- [ ] R3.17 (CV29): purpose `connector` không `connector_key` → `egress_blocked:host_not_allowed`;
      `CatalogueHostsPort` giả trả `{api.example.vn}` cho một khóa, gọi `other.example.vn` với khóa đó, purpose
      `connector` rồi `oauth` → `host_not_allowed`, máy giả không nhận gì; `api.example.vn` → qua; cài đặt W1 của cổng
      → mọi lời gọi `connector` bị chặn; gỡ kiểm `egress_hosts` → test đỏ.
- [ ] R3.20 (CV29): với settings triển khai, `http://` tới host được phép, và một bước chuyển hướng từ `https` về
      `http://` → `egress_blocked:scheme`, máy giả không nhận `Authorization` nào; ngoài profile triển khai `http://`
      qua; gỡ kiểm `https` → test đỏ.
- [ ] R3.8 (CV19): `*.com.vn` → 422; `*.github.io` → 422; `203.0.113.5` → 422, và INSERT thẳng `203.0.113.5` bằng
      `dw_app` → vi phạm CHECK; công ty A không thấy và không dùng được danh sách của B.
- [ ] R3.9 (CV22): `POST /api/v1/egress/allowed-hosts` hợp lệ → 202 kèm id phê duyệt `egress.allowed_host`
      có `required_scope` `integrations.admin`, không dòng nào, đích đó vẫn `egress_blocked:host_not_allowed`;
      ghi dòng ngay ở `POST` → test đỏ.
- [ ] R3.10 (CV22): người gửi tự duyệt → 409 `conflict` với `details.reason_code` `second_person_required`, không
      dòng nào; người không giữ `integrations.admin` quyết → 404; bỏ `egress.allowed_host` khỏi tiền tố nghiêm →
      test đỏ.
- [ ] R3.11 (CV22): người thứ hai giữ `integrations.admin` duyệt → đúng một dòng, audit
      `egress.allowlist.added` đứng tên người đó với `details.lane` `outbox`, `id` dòng là id phê duyệt; handler chạy
      lại cùng quyết định → vẫn một dòng, một audit; gỡ dòng rồi phát lại quyết định → dòng vẫn gỡ, đích vẫn
      `host_not_allowed`; hai yêu cầu cùng mẫu cùng purpose cùng được duyệt → một dòng, handler thứ hai kết thúc không
      lỗi và không audit; đích vừa thêm qua kiểm danh sách; đổi `ON CONFLICT DO NOTHING` thành chèn thẳng → test đỏ.
- [ ] R3.18 (CV30): `DELETE /api/v1/egress/allowed-hosts/{id}` của người giữ `integrations.admin` → `removed_at`,
      `removed_by` có giá trị, audit `egress.allowlist.removed` trong cùng giao dịch, `GET` không còn dòng, lời gọi kế
      tiếp tới đích đó → `host_not_allowed`; gỡ lọc `removed_at` khỏi kiểm danh sách → test đỏ.
- [ ] R3.19 (CV30): công ty B `DELETE` id của công ty A → 404, dòng của A còn hiệu lực; người không giữ
      `integrations.admin` → 403, dòng còn; gỡ kiểm quyền ở route → test đỏ.
- [ ] R3.12 (CV22): công ty chỉ người gửi giữ `integrations.admin` với tới workspace đang làm việc → `POST` trả
      409 `conflict` với `details.reason_code` `no_checker_available`, không dòng `platform.approval_requests` nào,
      không dòng `platform.egress_allowed_hosts` nào; thêm người thứ hai giữ khóa → 202; gỡ kiểm người duyệt →
      test đỏ.
- [ ] R4.1: vector Standard Webhooks 1.0 đúng, dấu thời gian trong ±5 phút → `verified` (`standardwebhooks`
      làm oracle).
- [ ] R4.2 (CV11): sửa một byte trượt; dấu thời gian lệch quá ±5 phút trượt; chữ ký thiếu trượt; gỡ kiểm
      dấu thời gian → test đỏ.
- [ ] R4.3 (CV11): token tĩnh sai → `rejected`, so theo thời gian hằng định.
- [ ] R4.4: khi xoay khóa ký, chữ ký của cả khóa cũ còn hạn lẫn khóa mới đều `verified`; chữ ký chỉ khớp khóa cũ có
      `not_after` đã qua theo đồng hồ tiêm vào → `rejected`; lược đồ không có trong `VERIFIERS` → `rejected`; gỡ kiểm
      `not_after` → test đỏ.
- [ ] R3.13 (CV26): mỗi ca của bảng phân loại kết thúc bằng đúng một `EgressResponse` hay một trong ba lỗi;
      `dw_agent_runtime.dispatch.NotDispatchedError is` lớp của `dw_kernel` (cùng cho hai lớp kia); một test kiến trúc
      thấy egress không khai lớp lỗi kết quả nào khác và `dw_connectors` không nhập `dw_agent_runtime`; thêm một nhánh
      trả `None` hay ném `RuntimeError` cho một pha → test bảng đỏ.
- [ ] R3.14 (CV26): máy chủ HTTP giả từ chối kết nối → `NotDispatchedError`, máy giả không nhận byte nào; đích bị
      `egress_blocked:address` → `NotDispatchedError` mang mã đó; gỡ phân loại theo byte đã ghi để mọi lỗi kết nối
      thành `OutcomeUnknownError` → ca này đỏ.
- [ ] R3.15 (CV26): máy chủ giả đọc yêu cầu rồi reset → `OutcomeUnknownError`, máy giả có đúng 1 yêu cầu; máy giả trả
      503 → `OutcomeUnknownError`; POST nhận 307 tới host ngoài danh sách → `OutcomeUnknownError` mang
      `egress_blocked:host_not_allowed`, máy giả có đúng 1 yêu cầu; body 2xx vượt 2 MiB (kể cả gzip nở ra quá trần) →
      `OutcomeUnknownError`; cho egress thử lại sau reset, hay phân loại reset hoặc chuyển hướng bị chặn sau khi gửi
      thành `NotDispatchedError` → máy giả nhận 2 yêu cầu hay ca đó đỏ.
- [ ] R3.16 (CV26): máy giả trả 422 → `RejectedError` mang 422, máy giả có đúng 1 yêu cầu; bảng của SMTP: ngắt trước dấu
      kết thúc dữ liệu → `NotDispatchedError`, 550 sau dữ liệu → `RejectedError` mang 550, hết thời gian sau dấu kết
      thúc dữ liệu → `OutcomeUnknownError`; đổi 4xx thành `OutcomeUnknownError` hay 550 thành `NotDispatchedError` →
      test bảng đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_kernel/src/dw_kernel/net_guard.py:58`; spec: R3.2 (`forbidden_address`, đã dựng ở `34768e7`).
- `packages/python/dw_kernel/src/dw_kernel/net_guard.py:69`; spec: R3.1, R3.3 (`resolve_checked`, địa chỉ để ghim).
- `packages/python/dw_kernel/src/dw_kernel/net_guard.py:105`; spec: R3.7, R3.21 (`ensure_allowed_outbound_url` cho
  host trong danh sách của người vận hành qua theo tên, nên egress không dùng nó).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/openai_compatible.py:61`; spec: R3.6.
- `packages/python/dw_connectors/src/dw_connectors/adapters/mailpit_mailbox.py:36`; spec: R3.6 (client thô thứ bảy).
- `apps/api/src/dw_api/settings.py:215`; spec: R3.7 (`outbound_allowed_hosts` của người vận hành, egress không đọc).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/dispatch.py:38`; spec: R3.13 (ba lỗi có kiểu hôm nay).
- `packages/python/dw_agent_runtime/pyproject.toml:12`; spec: R3.13 (`dw-agent-runtime` phụ thuộc `dw-connectors`).
- spec: R3, R4, CV7-CV11; ADR-0115 (Accepted) quyết 5, 6; si-platform `si_kernel/net_guard.py` có cùng
  lỗ (luồng ngược, ghi area file).
- spec: R3.13-R3.16, CV26; runtime-hardening/01 bước 3 (ba lỗi có kiểu), runtime-hardening:R6.12 (lỗi không có kiểu sau
  `dispatched` là `outcome_unknown`); workflow-engine:R4.23 (wrapper chỉ thử lại `not_dispatched` và `rejected` khai
  thử lại được).

## Comments

- 2026-10-23 (agent): egress từ chối `simulate` là lớp thứ hai sau executor của tenant-config/03; ticket
  này chờ `run_mode` trên ngữ cảnh lượt chạy từ ticket đó.
- 2026-10-23 (agent): Đạt chốt DO-26.1 (A) ngày 23/10/2026: egress từ chối mọi chế độ khác `live` từ W1
  (bước 4, R3.5). Theo DO-01, bảng dùng `owning_workspace_id` với FK ghép nên chờ org-and-principals/01; khóa
  `integrations.admin` đăng ký trong migration của ticket này nên chờ Danh mục quyền của tenant-rbac/01; bảng
  ghi một dòng vào danh sách bảng toàn tenant nên chờ studio-skeleton/01.
- 2026-10-24 (agent): theo quyết định Đạt ngày 24/10/2026: bước 4 và R3.5 theo ADR-0115 (Accepted) quyết 6,
  từ chối ở chế độ khác `live` mọi purpose trừ `model` và Hành động chỉ đọc, nêu rõ `mcp` và `oauth`; phạm vi
  D11 (người đặt yêu cầu và Đạt): thêm một Máy chủ được phép cần người thứ hai qua phê duyệt nghiêm
  `egress.allowed_host`, xóa vẫn một người (bước 7; R3.9, R3.10, R3.11, CV22).
- 2026-10-24 (agent): theo kiểm nhất quán vòng 3 (vòng sửa thứ tư): `POST` hỏi `platform.checker_candidates` và
  trả 409 `no_checker_available` khi không còn người duyệt khác người gửi (R3.12, CV22); người gửi tự quyết nhận
  `second_person_required` (V4.P9, R3.10); câu INSERT đăng ký khóa nêu `tenant_grantable` (V4.P2); thêm Blocked
  by tenant-rbac/02, chủ của `platform.checker_candidates` và cột `tenant_grantable` (bước 7). Khóa duyệt
  `integrations.admin` của `egress.allowed_host` nay là quyết định của Đạt (V4.5), ADR-0115 (Accepted) quyết 6 ghi.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt c: FK ghép `(tenant_id, owning_workspace_id)` của
  `platform.egress_allowed_hosts` nêu `ON DELETE RESTRICT` và chỉ mục như spec ghi cho `platform.connections`
  (CLAUDE.md, Data model rules: khóa ngoại nào cũng nêu `ON DELETE` và có chỉ mục ở phía của nó) (bước 7).
- 2026-10-25 (agent): lượt h, theo V4.30 của Đạt (mục 2): egress trả kết quả có kiểu, `succeeded` hay ba lỗi có kiểu
  mà runtime-hardening/01 khai ở `dw_agent_runtime` (bước 9; spec R3.13-R3.16, CV26), với bảng phân loại một chủ cho
  HTTP và SMTP mà `SmtpEgress` của ticket 05 dùng lại (SMTP đã gửi dấu kết thúc dữ liệu của `DATA` mà chưa nhận 250 là
  `outcome_unknown`); lỗi khác không bị nuốt, để ToolExecutor ghi nó `outcome_unknown` (runtime-hardening:R6.12).
  Không thêm cạnh: ticket này đã đi sau runtime-hardening/01 qua tenant-config/03.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness (builder check và boundary walk, bốn subagent,
  rồi một builder check kiểm lại) CHƯA ĐẠT lượt đầu, 2 CRITICAL, 12 HIGH, sửa theo khuyến nghị; mỗi quyết định cùng
  `Nếu sai thì:` ở mục Quyết định của spec, dòng 3/11/2026 (a)-(n). CRITICAL: (a) `connector` và `oauth` chỉ tới
  `egress_hosts` của Bản mô tả qua `CatalogueHostsPort` (R3.17, CV29); (b) `DELETE .../{id}` có R và test âm chéo công
  ty (R3.18, R3.19, CV30). HIGH: (c) bước 1 dùng lại `net_guard` của `34768e7`, không đọc `outbound_allowed_hosts`,
  `allow_private` chỉ từ composition root; (d) ba lỗi có kiểu chuyển về `dw_kernel` vì `dw_agent_runtime` đã phụ thuộc
  `dw_connectors`; (e) dừng sau byte đầu tiên là `OutcomeUnknownError`; (f) chỉ `https` khi triển khai (R3.20);
  (g) id dòng là id phê duyệt, gỡ bằng `removed_at`, handler `ON CONFLICT DO NOTHING`; (h) cách khớp mẫu và `ports`
  (R3.21); (i) miễn trừ ở `simulate` chỉ cho `connector`, `http_tool`; (j) `integrations.admin` là khóa `tenant`,
  `elevated`, `tenant_grantable`; (k) `VERIFIERS` W1 chỉ hai lược đồ có bên dùng, `not_after` trong bộ kiểm;
  (l) không mở bí mật, bên gọi truyền giá trị cần che; Blocked by 02 vì cùng chuỗi migration, `_TENANT_WIDE_ON_PURPOSE`
  và `test_privileges.py`, không vì chức năng; (m) `mailpit_mailbox.py` vào danh sách client thô; (n) Public Suffix
  List gồm phần PRIVATE, CHECK chặn IP literal. Không tách ticket: không bước nào cần host triển khai hay bí mật thật
  (`zalo_oa_zevent` đo trên OA thật thuộc W2, dòng Ngoài phạm vi; smokescreen thuộc ADR-0115 (Accepted) quyết 7, không ở đây).
- 2026-11-03 (agent): MEDIUM, chưa sửa: (M1) CONTEXT.md nói egress thực thi Lộ trình dữ liệu, còn ADR-0123 (Accepted)
  quyết 5 đặt kiểm ở ToolExecutor trước khi egress gửi (compliance-pdpl): ticket này không kiểm Lộ trình; sửa thuật ngữ
  qua domain-modeling. (M2) `POST` cho mẫu và purpose đã có dòng sống, hay đang có yêu cầu chờ, vẫn mở phê duyệt mà
  handler bỏ qua: đề xuất 409 `conflict` với `details.reason_code` `allowed_host_exists` ở `POST`; đổi `ports` là gỡ
  rồi thêm. (M3) `Idempotency-Key` không bắt buộc ở `POST` (ADR-0108 (Accepted) quyết 4), nên bấm hai lần mở hai yêu
  cầu; 202 mang `Location` tới yêu cầu phê duyệt, không tới `/api/v1/operations`. (M4) `EgressRequest.redirect` mặc
  định `none`, chỉ lời gọi `connector` lấy giá trị khác từ Bản mô tả; một GET nhận 301 thành `OutcomeUnknownError`.
  (M5) người giữ `integrations.admin` ở workspace khác có thấy yêu cầu không (ADR-0104 (Accepted) quyết 11): khóa
  `tenant` nên phải thấy; test R3.11 đặt người duyệt ở workspace khác người gửi. (M6) tên header của
  `static_header_token` mang trên `VerifierKey`, theo cách workflow-triggers/02 gửi. (M7) index cho `ORDER BY` của
  `GET` dẫn đầu bằng `tenant_id`; lỗi đọc danh sách trước byte đầu tiên là `NotDispatchedError`. (M8) R3.13 ("đúng
  một trong ba lỗi") và runtime-hardening:R6.12 (lỗi lạ không bị nuốt) là hai lớp: bảng phủ mọi pha đã biết, lỗi lập
  trình vẫn nổi lên.
- 2026-11-03 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
