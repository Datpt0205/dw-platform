# 03 — Lớp lộ trình dữ liệu ở model gateway, mọi lời gọi qua cùng cổng

Status: needs-triage
Blocked by: .claude/plans/studio/model-connections/issues/02-model-resolver-theo-tenant.md, .claude/plans/studio/usage-and-limits/issues/02-bang-gia-so-su-dung-va-man-hinh.md, .claude/plans/studio/agent-lifecycle/issues/01-dong-bang-va-kiem-o-moi-cua.md
Area: studio
Yêu cầu: R2.1, R2.2, R2.3, R2.4, R2.7, R2.8, CP2, CP3, CP4, CP5

## Mục tiêu

Một `ResidencyGate` lấy Lộ trình dữ liệu chặt nhất của công ty, workspace và agent, từ chối trước khi gửi
byte nào ra tuyến không hợp, và mọi adapter chạm model đi qua nó; ghi lộ trình trên mỗi lời gọi (spec R2;
ADR-0123 (Accepted)).

## Việc cần làm

1. Đọc `data_location` (`vn`, `foreign`), `processor`, `retention_days`, `no_training` trên `ModelRoute`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py:28-55`) do model-connections/02
   thêm, cùng luật "profile thiếu thì không nạp, bí danh không khai coi là `foreign`" của ticket đó; ticket
   này không khai lại trường hay luật.
2. Migration (id hex ngẫu nhiên): `platform.tenants` thêm `data_route_class text NOT NULL DEFAULT 'vn_only'`
   CHECK (`vn_only`, `cross_border_minimised`, `cross_border_full`), chỉ thêm cột, không thêm trigger nào
   trên `platform.tenants` (OPS-b); `platform.workspaces` thêm `data_route_class text NULL` cùng CHECK (NULL
   kế thừa, chỉ siết). `platform.cross_border_attestations` không tạo ở ticket này: bên ghi và bên đọc duy nhất
   của nó là đường nới R2.5 ở W2.
3. `effective_route_class(tenant, workspace, agent)` một chủ, trả lộ trình chặt nhất.
4. `ResidencyGate.check(route_class, route)` gọi trong `RoutingModelGateway`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/gateway.py:85-124`), sau cửa công tắc mà
   agent-lifecycle/01 đặt đầu gateway (ticket này chờ nó) và trước `LimitsMiddleware`, và factory chat model
   của agent (model-connections làm theo công ty); cho mọi adapter chạm model (embedding, rerank, trích
   xuất tài liệu, chép lời, tóm tắt, chấm eval) nhận cổng qua constructor; lỗi `ResidencyRefusedError` có
   thông điệp tiếng Việt; `cross_border_minimised` từ chối tới ticket 13 (W2).
5. `PATCH /api/v1/admin/tenant` thêm `data_route_class` (`platform.tenant.settings.write`): siết áp ngay với
   một người, audit `residency.class_changed` trong cùng giao dịch (spec R2.8); nới về phía ra nước ngoài →
   409 `second_person_required`, lộ trình giữ nguyên (spec R2.7; D11). Đường nới hai người với Xác nhận chuyển
   dữ liệu ra nước ngoài còn hạn đi qua kind `policy` của tenant-config ở W2 (ADR-0110 (Accepted); spec R2.5).
6. Ghi `data_route_class`, `data_location`, `processor` lên span, dòng lượt chạy và cột của
   `platform.usage_events` do usage-and-limits/02 tạo. `ResidencyGate` đứng trước `LimitsMiddleware` của
   usage-and-limits/03 (ticket đó chờ ticket này, OPS-b).
7. Kiểm R2.6 (trường dữ liệu cá nhân vào prompt trên tuyến ra nước ngoài) chạy lúc gửi kiểm định trong
   ticket 05, dùng `effective_route_class` của bước 3.

## Tiêu chí chấp nhận

- [ ] R2.1: một lời gọi model ghi `data_route_class`, `data_location` và `processor` lên span, lượt chạy
      và Sổ sử dụng.
- [ ] R2.2 (CP2): agent `vn_only` với tuyến `foreign` hay không khai → `ResidencyRefusedError` trước khi
      gửi, adapter giả ghi 0 lời gọi; gỡ cổng → test đỏ.
- [ ] R2.3 (CP3): chép lời khi `vn_only` tới URL `foreign` → job `failed` lý do `residency_refused`, 0
      request; gỡ cổng ở embedding → test đỏ.
- [ ] R2.4 (CP4): đặt `cross_border_full` ở workspace khi công ty `vn_only` → 422, không đổi dòng.
- [ ] R2.7 (CP5): `PATCH` nới công ty từ `vn_only` sang `cross_border_full` → 409 `second_person_required`,
      lộ trình giữ nguyên, không audit; gỡ chặn → test đỏ.
- [ ] R2.8: một người siết workspace từ NULL sang `vn_only` → áp ngay, audit `residency.class_changed` trong
      cùng giao dịch.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py:28-55`; spec: R2.1 (ModelRoute
  không có `data_location`).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/gateway.py:85-124`; spec: R2.3 (cửa gateway
  chèn cổng).
- `packages/python/dw_knowledge/src/dw_knowledge/adapters/api_parsers.py:28`; spec: R2.3 (chép lời tới URL
  nước ngoài cố định).
- ADR-0123 (Accepted) quyết 3, 4, 5, 6.

## Comments

- 2026-10-23 (agent): gộp B11-security compliance-pdpl 02, 03. `needs-info` vì DO-54 (vai trò bên xử lý,
  pilot dùng model nào, đặt ở đâu) chờ luật sư và người yêu cầu. DO-19 đã quyết bằng D13 (`model-proxy`
  riêng, `data_location` theo bí danh).
- 2026-10-23 (agent): DO-54.1 có lời đáp cho W1 (Đạt, 23/10/2026), nên `needs-triage`; demo trên uat cần một
  tuyến khai `vn` (FOG-10, FOG-18). W1 bỏ đường nới (D:tenant-config/05~tenant-rbac:R7.1), R2.5 sang W2; R2.6
  chuyển sang ticket 05; trường lộ trình của model-connections/02 chỉ đọc; ghi lộ trình lên Sổ sử dụng nên chờ
  usage-and-limits/02.
- 2026-10-24 (agent): áp quyết định của Đạt ngày 24/10/2026: chờ agent-lifecycle/01 vì cùng sửa
  `model/gateway.py`, thứ tự cửa là công tắc, Lộ trình dữ liệu, rồi hạn mức (C:agent-lifecycle/01\~compliance-pdpl/03);
  `platform.cross_border_attestations` sang W2 cùng R2.5
  (H:compliance-pdpl:dữ-liệu\~compliance-pdpl:ngoài-phạm-vi).
