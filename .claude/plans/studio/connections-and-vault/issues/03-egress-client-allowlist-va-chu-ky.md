# 03 — Egress client ghim IP, danh sách máy chủ được phép và module chữ ký webhook

Status: needs-triage
Blocked by: .claude/plans/studio/foundations-hardening/issues/05-bien-mang-va-kho-du-lieu.md, .claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md
Area: studio
Yêu cầu: R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R3.8, R4.1, R4.2, R4.3, R4.4, CV7, CV8, CV9, CV10, CV11, CV19

## Mục tiêu

Mọi lời gọi ra ngoài của lưu lượng tới tenant đi qua một bộ gọi ghim địa chỉ đã kiểm, chỉ tới địa chỉ
Internet toàn cầu trong danh sách được phép, kể cả sau chuyển hướng hay đổi DNS; và một module thuần
kiểm chữ ký cho mọi cửa nhận sự kiện (spec R3, R4). W1 từ chối `simulate` ở egress làm lớp thứ hai sau
executor của tenant-config/03. Gộp từ B8a-connections connections-and-vault 02, 08 và 13 (phần module
chữ ký).

## Việc cần làm

1. Mở rộng `packages/python/dw_kernel/src/dw_kernel/net_guard.py` (chỉ stdlib, đúng hợp đồng "Kernel is
   pure"): `forbidden_address(ip) -> str | None` từ chối khi `not is_global or is_multicast or is_private
or is_loopback or is_link_local or is_reserved or is_unspecified`, đệ quy vào `ipv4_mapped`,
   `sixtofour`, `teredo` và NAT64 `64:ff9b::/96`; `resolve_checked(host, port)` phân giải và trả địa chỉ
   đã kiểm để ghim; giữ ngữ nghĩa `allow_private` và `allowed_hosts`.
2. Gói egress (`dw_connectors.egress`): `EgressRequest`, `EgressContext(tenant_id, workspace_id, run_id,
run_mode, purpose, connector_key, connection_id)`, `EgressResponse`, `EgressPort`, `EgressClient`;
   `PinnedNetworkBackend` trên `httpcore.AsyncNetworkBackend.connect_tcp` ghim địa chỉ, TLS SNI theo
   hostname; `httpx.AsyncClient(trust_env=False, follow_redirects=False)`.
3. Chuyển hướng theo manifest (`none` mặc định, `same_origin`, `revalidate`), tối đa 3 bước, mỗi bước
   `resolve_checked` lại và kiểm danh sách; bỏ `Authorization`, `Cookie` khi đổi origin; trần body 2 MiB
   đếm khi stream; tổng thời gian trong `timeout_seconds` của công cụ.
4. `run_mode == 'simulate'` → từ chối mọi purpose trừ `model` và hành động chỉ đọc đã phân loại, với mã
   `egress_blocked:run_mode`; `run_mode` đọc từ `EgressContext` (tenant-config/03 đặt trên ngữ cảnh lượt
   chạy).
5. Span `dw.egress.request`, metric `dw_egress_requests_total`, `dw_egress_blocked_total`; che bí mật
   theo giá trị (thô, mã hóa URL, base64) trong body, lỗi và log; filter logger `httpx` bỏ query string.
6. Test kiến trúc (AST): `httpx.AsyncClient(` và `httpx.Client(` chỉ ở các adapter vận hành liệt kê
   (`openai_compatible.py`, `openai_responses.py`, `zalo_bot.py`, `api_parsers.py`, `cohere_rerank.py`,
   `openai_embedding.py`) và gói egress.
7. Migration (revision hex): `platform.egress_allowed_hosts` theo mục Dữ liệu của spec, kiểm Public
   Suffix List (wildcard không đặt trên hậu tố công cộng, không IP literal); RLS ENABLE và FORCE theo
   tenant, grant cột; routes `GET`, `POST`, `DELETE /api/v1/egress/allowed-hosts` (`integrations.admin`),
   audit `egress.allowlist.added`, `egress.allowlist.removed`; Bộ gọi ra ngoài kiểm danh sách cho mọi
   purpose khác `connector` và `oauth`.
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
- [ ] R3.5 (CV10): gọi egress với `run_mode='simulate'`, purpose `connector` → `egress_blocked:run_mode`,
      không gọi nhà cung cấp; purpose `model` vẫn qua; gỡ bước kiểm chế độ → test đỏ.
- [ ] R3.6 (CV9): thêm `httpx.AsyncClient(` vào một module mới ngoài danh sách → test kiến trúc đỏ.
- [ ] R3.7 (CV19): đích host ngoài danh sách (purpose `http_tool`) → `egress_blocked:host_not_allowed`;
      gỡ kiểm danh sách → test đỏ.
- [ ] R3.8 (CV19): `*.com.vn` → 422; `203.0.113.5` → 422; công ty A không thấy và không dùng được danh
      sách của B.
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
- spec: R3, R4, CV7-CV11; ADR-0115 (Proposed) quyết 5, 6; si-platform `si_kernel/net_guard.py` có cùng
  lỗ (luồng ngược, ghi area file).

## Comments

- 2026-10-23 (agent): egress từ chối `simulate` là lớp thứ hai sau executor của tenant-config/03; ticket
  này chờ `run_mode` trên ngữ cảnh lượt chạy từ ticket đó.
