# 03 — Egress client ghim IP, danh sách máy chủ được phép và module chữ ký webhook

Status: needs-triage
Blocked by: .claude/plans/studio/foundations-hardening/issues/05-bien-mang-va-kho-du-lieu.md, .claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md, .claude/plans/studio/tenant-rbac/issues/01-mot-chu-cho-quyen.md, .claude/plans/studio/org-and-principals/issues/01-khoa-don-vi-va-siet-realm.md, .claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md
Area: studio
Yêu cầu: R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R3.8, R3.9, R3.10, R3.11, R3.12, R4.1, R4.2, R4.3, R4.4, CV7, CV8, CV9, CV10, CV11, CV19, CV22

## Mục tiêu

Mọi lời gọi ra ngoài của lưu lượng tới tenant đi qua một bộ gọi ghim địa chỉ đã kiểm, chỉ tới địa chỉ
Internet toàn cầu trong danh sách được phép, kể cả sau chuyển hướng hay đổi DNS; và một module thuần
kiểm chữ ký cho mọi cửa nhận sự kiện (spec R3, R4). W1 từ chối mọi chế độ khác `live` ở egress làm lớp
thứ hai sau executor của tenant-config/03 (DO-26.1). Gộp từ B8a-connections connections-and-vault 02, 08 và
13 (phần module chữ ký).

## Việc cần làm

1. Mở rộng `packages/python/dw_kernel/src/dw_kernel/net_guard.py` (chỉ stdlib, đúng hợp đồng "Kernel is
   pure"): `forbidden_address(ip) -> str | None` từ chối khi `not is_global or is_multicast or is_private
or is_loopback or is_link_local or is_reserved or is_unspecified`, đệ quy vào `ipv4_mapped`,
   `sixtofour`, `teredo` và NAT64 `64:ff9b::/96`; `resolve_checked(host, port)` phân giải và trả địa chỉ
   đã kiểm để ghim; giữ ngữ nghĩa `allow_private` và `allowed_hosts`.
2. Gói egress (`dw_connectors.egress`): `EgressRequest`, `EgressContext(tenant_id, workspace_id, run_id,
run_mode, purpose, connector_key, connection_id, simulate_safe)` (`simulate_safe` mặc định false, như
   tenant-config:R5.5), `EgressResponse`, `EgressPort`, `EgressClient`;
   `PinnedNetworkBackend` trên `httpcore.AsyncNetworkBackend.connect_tcp` ghim địa chỉ, TLS SNI theo
   hostname; `httpx.AsyncClient(trust_env=False, follow_redirects=False)`.
3. Chuyển hướng theo manifest (`none` mặc định, `same_origin`, `revalidate`), tối đa 3 bước, mỗi bước
   `resolve_checked` lại và kiểm danh sách; bỏ `Authorization`, `Cookie` khi đổi origin; trần body 2 MiB
   đếm khi stream; tổng thời gian trong `timeout_seconds` của công cụ.
4. `run_mode` khác `live` (`simulate`, và `test` mà W1 chưa mở) → từ chối mọi purpose trừ `model` và lời gọi
   của Hành động khai chỉ đọc hay `simulate_safe` (tenant-config:R5.4), kể cả `mcp` và `oauth`, với mã
   `egress_blocked:run_mode`; `run_mode` và cờ `simulate_safe` lấy từ `EgressContext` (tenant-config/03 đặt
   trên ngữ cảnh lượt chạy); W2 mới mở `test` cho Danh sách người nhận thử (DO-26.1).
5. Span `dw.egress.request`, metric `dw_egress_requests_total`, `dw_egress_blocked_total`; che bí mật
   theo giá trị (thô, mã hóa URL, base64) trong body, lỗi và log; filter logger `httpx` bỏ query string.
6. Test kiến trúc (AST): `httpx.AsyncClient(` và `httpx.Client(` chỉ ở các adapter vận hành liệt kê
   (`openai_compatible.py`, `openai_responses.py`, `zalo_bot.py`, `api_parsers.py`, `cohere_rerank.py`,
   `openai_embedding.py`) và gói egress.
7. Migration (revision hex): `platform.egress_allowed_hosts` theo mục Dữ liệu của spec (`owning_workspace_id`
   với FK ghép `(tenant_id, owning_workspace_id)` tới `uq_workspaces_tenant_id_id` của org-and-principals/01,
   ON DELETE RESTRICT, có index), kiểm Public Suffix List
   (wildcard không đặt trên hậu tố công cộng, không IP literal); RLS ENABLE và FORCE theo tenant, grant
   cột; một dòng có lý do cho bảng trong `_TENANT_WIDE_ON_PURPOSE` của `test_rls_coverage.py` (studio-skeleton/01); đăng ký
   khóa `integrations.admin` vào Danh mục quyền trong cùng migration, câu INSERT nêu mọi cột NOT NULL có lúc đó,
   gồm nhãn, `scope_kind` và `risk` theo tenant-rbac/01 cùng `tenant_grantable` của tenant-rbac/02; routes `GET`,
   `POST`, `DELETE /api/v1/egress/allowed-hosts` (`integrations.admin`); Bộ gọi ra ngoài kiểm danh sách cho mọi
   purpose khác `connector` và `oauth`.
    - `POST` kiểm R3.8, rồi hỏi `platform.checker_candidates` của tenant-rbac/02 với khóa `integrations.admin`,
      người gửi và workspace đang làm việc: rỗng → 409 `conflict` với `details.reason_code`
      `no_checker_available`, không mở yêu cầu (R3.12); không thì trả 202 với một yêu cầu phê duyệt không lượt
      chạy `egress.allowed_host`, `required_scope` `integrations.admin`, payload chỉ mang mẫu máy chủ, cổng,
      purpose và ghi chú; chưa ghi dòng nào. `egress.allowed_host` vào `strict_approval_prefixes` bằng `|=` ở API
      và worker, nên người gửi tự quyết nhận 409 `conflict` với `details.reason_code` `second_person_required`
      của tiền tố nghiêm (R3.10; ADR-0104 (Accepted) quyết 11).
    - Handler `egress.allowed_host.decided` đăng ký ở composition root của worker, chạy lặp lại không đổi kết
      quả theo id phê duyệt: duyệt → thêm đúng một dòng cùng audit `egress.allowlist.added` đứng tên người quyết,
      `details.lane` `outbox`, trong một giao dịch; từ chối → không ghi gì.
    - `DELETE` một người, có hiệu lực ngay, audit `egress.allowlist.removed`.
8. Module thuần `dw_connectors.webhooks`: `InboundMessage`, `VerifierKey`, `Verdict`, `SignatureVerifier`,
   bảng `VERIFIERS` (`standard_webhooks_v1`, `static_header_token`, `meta_x_hub_signature_256`,
   `zalo_oa_zevent`), `sign_standard_webhook()`; cửa sổ dấu thời gian ±5 phút; so token theo thời gian
   hằng định.

## Tiêu chí chấp nhận

- [ ] R3.1 (CV7): listener `127.0.0.1` với resolver giả trả IP công khai lần đầu, IP nội bộ lần sau → bị
      chặn lúc kết nối; gỡ ghim → test đỏ.
- [ ] R3.2 (CV7): `100.64.0.1`, `169.254.169.254`, `224.0.0.1`, `::ffff:169.254.169.254`,
      `64:ff9b::a9fe:a9fe`, `2002:a9fe:a9fe::1` → chặn; `8.8.8.8`, `2606:4700:4700::1111` qua.
- [ ] R3.3 (CV8): redirect tới `http://169.254.169.254/` hay host ngoài danh sách → chặn, không gửi; gỡ
      kiểm lại chuyển hướng → test đỏ.
- [ ] R3.4 (CV8): redirect đổi origin → mock origin khác không thấy `Authorization` hay `Cookie`.
- [ ] R3.5 (CV10): gọi egress với `run_mode` `simulate` và `test`, purpose `connector`, `http_tool`,
      `webhook`, `mcp` và `oauth` → `egress_blocked:run_mode`, không gọi nhà cung cấp; purpose `model` và lời
      gọi của một Hành động khai chỉ đọc ở `simulate` vẫn qua; `live` → qua; gỡ bước kiểm chế độ → test đỏ.
- [ ] R3.6 (CV9): thêm `httpx.AsyncClient(` vào một module mới ngoài danh sách → test kiến trúc đỏ.
- [ ] R3.7 (CV19): đích host ngoài danh sách (purpose `http_tool`) → `egress_blocked:host_not_allowed`;
      gỡ kiểm danh sách → test đỏ.
- [ ] R3.8 (CV19): `*.com.vn` → 422; `203.0.113.5` → 422; công ty A không thấy và không dùng được danh
      sách của B.
- [ ] R3.9 (CV22): `POST /api/v1/egress/allowed-hosts` hợp lệ → 202 kèm id phê duyệt `egress.allowed_host`
      có `required_scope` `integrations.admin`, không dòng nào, đích đó vẫn `egress_blocked:host_not_allowed`;
      ghi dòng ngay ở `POST` → test đỏ.
- [ ] R3.10 (CV22): người gửi tự duyệt → 409 `conflict` với `details.reason_code` `second_person_required`, không
      dòng nào; người không giữ `integrations.admin` quyết → 404; bỏ `egress.allowed_host` khỏi tiền tố nghiêm →
      test đỏ.
- [ ] R3.11 (CV22): người thứ hai giữ `integrations.admin` duyệt → đúng một dòng, audit
      `egress.allowlist.added` đứng tên người đó với `details.lane` `outbox`; handler chạy lại cùng quyết định →
      vẫn một dòng; đích vừa thêm qua kiểm danh sách.
- [ ] R3.12 (CV22): công ty chỉ người gửi giữ `integrations.admin` với tới workspace đang làm việc → `POST` trả
      409 `conflict` với `details.reason_code` `no_checker_available`, không dòng `platform.approval_requests` nào,
      không dòng `platform.egress_allowed_hosts` nào; thêm người thứ hai giữ khóa → 202; gỡ kiểm người duyệt →
      test đỏ.
- [ ] R4.1: vector Standard Webhooks 1.0 đúng, dấu thời gian trong ±5 phút → `verified` (`standardwebhooks`
      làm oracle).
- [ ] R4.2 (CV11): sửa một byte trượt; dấu thời gian lệch quá ±5 phút trượt; chữ ký thiếu trượt; gỡ kiểm
      dấu thời gian → test đỏ.
- [ ] R4.3 (CV11): token tĩnh sai → `rejected`, so theo thời gian hằng định.
- [ ] R4.4: khi xoay khóa ký, chữ ký của cả khóa cũ còn hạn lẫn khóa mới đều `verified`.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_kernel/src/dw_kernel/net_guard.py:38-45`; spec: R3.1, R3.2.
- `packages/python/dw_kernel/src/dw_kernel/net_guard.py:49-75`; spec: R3.3, R3.4.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/openai_compatible.py:61`; spec: R3.6.
- `apps/api/src/dw_api/settings.py:206`; spec: R3.2 (danh sách máy chủ được phép).
- spec: R3, R4, CV7-CV11; ADR-0115 (Accepted) quyết 5, 6; si-platform `si_kernel/net_guard.py` có cùng
  lỗ (luồng ngược, ghi area file).

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
