# 03 — Lớp lộ trình dữ liệu ở model gateway, mọi lời gọi qua cùng cổng

Status: needs-info (DO-54)
Blocked by: .claude/plans/studio/model-connections/issues/02-model-resolver-theo-tenant.md
Area: studio
Yêu cầu: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, CP2, CP3, CP4, CP5, CP6

## Mục tiêu

Một `ResidencyGate` lấy Lộ trình dữ liệu chặt nhất của công ty, workspace và agent, từ chối trước khi gửi
byte nào ra tuyến không hợp, và mọi adapter chạm model đi qua nó; ghi lộ trình trên mỗi lời gọi (spec R2;
ADR-0123 (Proposed)).

## Việc cần làm

1. `ModelRoute` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py:28-55`) thêm bắt
   buộc `data_location` (`vn`, `foreign`), `processor`, `retention_days`, `no_training`; profile thiếu →
   không nạp; bí danh model không khai → coi là `foreign`.
2. Migration (id hex ngẫu nhiên): `platform.tenants` thêm `data_route_class text NOT NULL DEFAULT 'vn_only'`
   CHECK (`vn_only`, `cross_border_minimised`, `cross_border_full`); `platform.workspaces` thêm
   `data_route_class text NULL` cùng CHECK (NULL kế thừa, chỉ siết); `platform.cross_border_attestations`
   (RLS công ty; `processor`, `ctia_ref`, `attested_by`, `expires_at`, `revoked_at`).
3. `effective_route_class(tenant, workspace, agent)` một chủ, trả lộ trình chặt nhất.
4. `ResidencyGate.check(route_class, route)` gọi trong `RoutingModelGateway`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/gateway.py:85-124`) và factory chat model
   của agent (model-connections làm theo công ty); cho mọi adapter chạm model (embedding, rerank, trích
   xuất tài liệu, chép lời, tóm tắt, chấm eval) nhận cổng qua constructor; lỗi `ResidencyRefusedError` có
   thông điệp tiếng Việt; `cross_border_minimised` từ chối tới ticket 13 (W2).
5. `PATCH /api/v1/admin/tenant` thêm `data_route_class` (`platform.tenant.settings.write`); nới về phía ra
   nước ngoài cần người duyệt thứ hai (maker-checker, ADR-0110 (Proposed)) và Xác nhận chuyển dữ liệu ra nước ngoài
   còn hạn nêu `processor`; audit `residency.class_changed`, `residency.attested`.
6. Ghi `data_route_class`, `data_location`, `processor` lên span, dòng lượt chạy và Sổ sử dụng (usage-and-limits).
7. Kiểm phát hành: một phiên bản đưa giá trị trường dữ liệu cá nhân vào prompt trên tuyến ra nước ngoài →
   cổng phát hành từ chối (MP7).

## Tiêu chí chấp nhận

- [ ] R2.1: một lời gọi model ghi `data_route_class`, `data_location` và `processor` lên span, lượt chạy
      và Sổ sử dụng.
- [ ] R2.2 (CP2): agent `vn_only` với tuyến `foreign` hay không khai → `ResidencyRefusedError` trước khi
      gửi, adapter giả ghi 0 lời gọi; gỡ cổng → test đỏ.
- [ ] R2.3 (CP3): chép lời khi `vn_only` tới URL `foreign` → job `failed` lý do `residency_refused`, 0
      request; gỡ cổng ở embedding → test đỏ.
- [ ] R2.4 (CP4): đặt `cross_border_full` ở workspace khi công ty `vn_only` → 422, không đổi dòng.
- [ ] R2.5 (CP5): nới công ty sang ra nước ngoài bởi một người, không có Xác nhận còn hạn → từ chối, lộ
      trình giữ nguyên.
- [ ] R2.6 (CP6): gắn `full_name` vào prompt trên tuyến `cross_border_full` → phát hành từ chối; gỡ kiểm →
      test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py:28-55`; spec: R2.1 (ModelRoute
  không có `data_location`).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/gateway.py:85-124`; spec: R2.3 (cửa gateway
  chèn cổng).
- `packages/python/dw_knowledge/src/dw_knowledge/adapters/api_parsers.py:28`; spec: R2.3 (chép lời tới URL
  nước ngoài cố định).
- ADR-0123 (Proposed) quyết 3, 4, 5, 6.

## Comments

- 2026-10-23 (agent): gộp B11-security compliance-pdpl 02, 03. `needs-info` vì DO-54 (vai trò bên xử lý,
  pilot dùng model nào, đặt ở đâu) chờ luật sư và người yêu cầu. DO-19 đã quyết bằng D13 (lane LiteLLM
  riêng, `data_location` theo bí danh).
