# 03 — Lớp lộ trình dữ liệu ở model gateway, mọi lời gọi qua cùng cổng

Status: ready-for-agent
Blocked by: .claude/plans/studio/model-connections/issues/02-model-resolver-theo-tenant.md, .claude/plans/studio/usage-and-limits/issues/02-bang-gia-so-su-dung-va-man-hinh.md, .claude/plans/studio/agent-lifecycle/issues/01-dong-bang-va-kiem-o-moi-cua.md
Area: studio
Yêu cầu: R2.1, R2.2, R2.3, R2.4, R2.7, R2.8, CP2, CP3, CP4, CP5

## Mục tiêu

Một `ResidencyGate` lấy Lộ trình dữ liệu chặt nhất của công ty, workspace và phiên bản, từ chối trước khi gửi
byte nào ra tuyến không hợp, và mọi adapter chạm model đi qua nó; ghi lộ trình trên mỗi lời gọi (spec R2;
ADR-0123 (Accepted)). Phần phiên bản agent của R2.4 (agent khai `route_class` lỏng hơn công ty) ở ticket 07, móc gửi
kiểm định của loại `agent`.

## Việc cần làm

1. Đọc `data_location` (`vn`, `foreign`), `processor`, `retention_days`, `no_training` trên `ModelRoute`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py:28-55`) do model-connections/02
   thêm, cùng luật "profile thiếu thì không nạp, bí danh không khai coi là `foreign`" của ticket đó; ticket
   này không khai lại trường hay luật. Ba đích không đi qua `ModelRoute` (rerank `cohere_compatible`, trích xuất tài
   liệu `GatewayFileParser`, chép lời `DeepgramTranscriptParser` với URL cố định
   `packages/python/dw_knowledge/src/dw_knowledge/adapters/api_parsers.py:28`) khai `data_location` và `processor`
   trong settings của tiến trình cạnh URL và khóa của chúng, không mặc định; thiếu thì cổng coi đích là `foreign`
   (cùng luật, áp ở cổng). Embedding, chat, gateway có cấu trúc và nén ngữ cảnh đọc `ModelRoute` của hồ sơ, không
   khai thêm. Hồ sơ mock của local, test và CI (`configs/models/*.yaml`, `provider: mock`) khai `data_location: vn`,
   `processor: mock`, vì adapter mock không gửi gì ra ngoài; tuyến tới gateway của người yêu cầu không khai tới khi
   FOG-18 trả lời, nên bị từ chối dưới `vn_only`, đúng như ADR-0123 (Accepted) Consequences; không ai khai `vn` cho
   một tuyến chưa định vị để test xanh.
2. Migration (id hex ngẫu nhiên): `platform.tenants` thêm `data_route_class text NOT NULL DEFAULT 'vn_only'`
   CHECK (`vn_only`, `cross_border_minimised`, `cross_border_full`), chỉ thêm cột, không thêm trigger nào
   trên `platform.tenants` (OPS-b); `platform.workspaces` thêm `data_route_class text NULL` cùng CHECK (NULL
   kế thừa, chỉ siết); `platform.worker_runs` thêm `data_route_class text NULL` cùng CHECK, ghi lúc nhận lượt.
   `platform.cross_border_attestations` không tạo ở ticket này: bên ghi và bên đọc duy nhất của nó là đường nới R2.5
   ở W2.
3. `effective_route_class(tenant_class, workspace_class, version_class)` một chủ, trả lộ trình chặt nhất; `None` ở
   workspace hay phiên bản là không siết thêm; một giá trị ngoài ba giá trị → lỗi, không bao giờ coi là lỏng.
   `RunContext` thêm `route_class` mặc định `vn_only` (hẹp nhất, như `clearance`); mỗi chỗ nhận lượt (nơi dựng
   `RunContext` cho một lượt mới) đặt nó bằng `effective_route_class` của dòng công ty, dòng workspace của lượt và
   `route_class` của phiên bản gốc (`dw.agent/v1` mục `route_class`, agent-builder:R1.6; `dw.workflow/v1` không có
   mục này ở W1 nên là `None`), và ghi nó lên `platform.worker_runs`; một lượt con lấy lớp chặt nhất của lớp lượt cha
   và phiên bản của nó; lần resume đọc lớp ở dòng lượt, không tính lại, và một dòng lượt mang NULL (nhận trước
   migration) đọc là `vn_only`. Siết lộ trình áp cho mọi lượt nhận sau khi
   thay đổi commit; ở W1 mọi công ty giữ `vn_only` (R2.7), nên lớp hiệu lực của mọi lượt là `vn_only` và lượt đang
   chạy không đổi gì.
4. `ResidencyGate.check(scope, destination)` lấy lớp từ `scope`, không bao giờ từ đối số của bên gọi hay từ thân
   request: `scope` là `RunContext` (đọc `route_class` đã ghim); hay, cho lời gọi đồng bộ của một request API ngoài
   lượt chạy (embedding câu hỏi và rerank khi tìm tri thức), công ty và workspace của `AccessContext` đã xác minh;
   hay, cho lời gọi của một job (nạp tài liệu, chép lời), phạm vi `(tenant_id, workspace_id)` của dòng job, ghi từ
   ngữ cảnh đã xác minh lúc tạo job (job toàn công ty có `workspace_id` NULL chỉ dùng lớp của công ty). Hai loại sau
   cổng giải qua một port hẹp đọc dòng công ty và workspace dưới RLS; không đọc được dòng hay gặp giá trị lạ → từ chối
   (`failure-modes.md` #7); eval của nền tảng (`tenant_id=None`) chạy với `vn_only`. Luật: `vn_only` chỉ nhận đích `vn`;
   `cross_border_minimised` nhận đích `vn` và từ chối đích `foreign` tới khi bộ giả danh có ở W2 (dòng Presidio của
   Ngoài phạm vi); `cross_border_full` nhận cả hai. Cổng kiểm từng tuyến trước khi gửi, không chỉ tuyến đầu: trong
   `RoutingModelGateway` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/gateway.py:120-155`, `_route`
   và `_attempts`) các tuyến bị cổng từ chối bị bỏ khỏi danh sách thử trước lần gửi đầu, nên lỗi 5xx của tuyến `vn`
   không bao giờ rơi sang một tuyến `foreign`; không còn tuyến nào → `ResidencyRefusedError`. Lỗi này không thử lại
   (middleware thử lại model coi nó là lỗi không thử lại), không ghi dòng `platform.usage_events` (không lời gọi nào
   xảy ra), và kết thúc lượt `failed` với `reason_code` `residency_refused` (spec mục API), thông điệp tiếng Việt.
   Cổng được tiêm qua constructor vào: `RoutingModelGateway`, sau cửa công tắc mà agent-lifecycle/01 đặt đầu gateway
   (ticket này chờ nó) và trước `LimitsMiddleware`; vòng agent, nơi ticket này cấp `ResidencyGateMiddleware` (cổng
   bọc thành middleware) mà agent-builder/03 đặt ngay sau `StudioModelSelection` và trước `LimitsMiddleware` theo
   thứ tự ngăn xếp ở bước 2 của ticket đó (ADR-0117 (Accepted) quyết 5; usage-and-limits:R6.5), không nằm trong
   factory chat model, và kiểm tuyến mà `StudioModelSelection` chọn cùng mọi tuyến dự phòng mà chat model có thể đổi
   sang, trước lần gửi đầu, như ở `RoutingModelGateway`; thử lại model chỉ thử lại tuyến đã qua cổng;
   agent-builder/03 giữ test thứ tự (agent-builder:R3.7); embedding
   (`dw_knowledge/adapters/embedding_factory.py`); rerank (`dw_knowledge/adapters/cohere_rerank.py`); trích xuất tài
   liệu và chép lời (`dw_knowledge/adapters/api_parsers.py`); nén ngữ cảnh (`PlatformSummarizationMiddleware` của
   `dw_agent_runtime/adapters/context_compaction.py`, gọi model thẳng, không qua node model của agent, nên middleware
   của vòng agent không thấy nó). Chấm eval: hôm nay `dw_evals` không có bộ chấm nào gọi model (bộ chấm LLM đứng sau
   một port, `packages/python/dw_evals/src/dw_evals/__init__.py:2`); adapter đầu tiên của port đó nhận cổng qua
   constructor.
5. `PATCH /api/v1/admin/tenant` thêm `data_route_class` (`platform.tenant.settings.write`) và
   `PATCH /api/v1/admin/workspaces/{workspace_id}` thêm `data_route_class` (cùng quyền
   `platform.tenant.settings.write` cho riêng trường này, vì lộ trình là quyết định của bên kiểm soát; trường `name`
   giữ quyền của nó): siết áp ngay với một người, audit `residency.class_changed` (giá trị trước và sau, công ty hay
   workspace) trong cùng giao dịch (spec R2.8); nới lớp của công ty về phía ra nước ngoài, nới lớp của workspace (về
   lớp lỏng hơn lớp đang có hay về NULL) → 409 `second_person_required`, lộ trình giữ nguyên, không audit (spec R2.7;
   D11; ADR-0123 (Accepted), Amendments 2026-10-24); workspace lỏng hơn công ty → 422 trước phép kiểm nới (spec R2.4);
   gửi đúng giá trị đang có → 200, không đổi, không audit. Workspace của công ty khác → 404 như không tồn tại (RLS
   không trả dòng). Đường nới hai người với Xác nhận chuyển dữ liệu ra nước ngoài còn hạn đi qua kind `policy` của
   tenant-config ở W2 (ADR-0110 (Accepted); spec R2.5). Quyền `platform.tenant.settings.write` xét ở độ sâu công ty
   cho cả hai route. Không route nào khác nhận `data_route_class`: route của người vận hành
   `PATCH /api/v1/platform/tenants/{tenant_id}` chỉ đổi tên (`apps/api/src/dw_api/routes/v1/platform.py:181`); một test
   hợp đồng đỏ khi thân của một route khác hai route này có trường `data_route_class` (`failure-modes.md` #5), vì bước
   2 không thêm trigger trên `platform.tenants`.
6. Ghi `data_route_class`, `data_location`, `processor` lên span (`dw.route_class`, ADR-0123 (Accepted) quyết 6) của
   mọi lời gọi, và lên cột của dòng `platform.usage_events` (usage-and-limits/02) mà adapter đó đã ghi; ticket này không
   thêm dòng Sổ sử dụng cho adapter nào chưa ghi; dòng lượt chạy chỉ mang
   `data_route_class` (bước 2, 3), vì một lượt có thể gọi nhiều tuyến khác nơi xử lý. `ResidencyGate` đứng trước
   `LimitsMiddleware` của usage-and-limits/03 (ticket đó chờ ticket này, OPS-b).
7. Kiểm R2.6 (trường dữ liệu cá nhân vào prompt trên tuyến ra nước ngoài) chạy lúc gửi kiểm định trong
   ticket 05, dùng `effective_route_class` của bước 3.

## Tiêu chí chấp nhận

- [ ] R2.1: một lời gọi model ghi `data_route_class`, `data_location` và `processor` lên span và Sổ sử dụng, và
      `data_route_class` lên dòng `platform.worker_runs` của lượt; lượt resume sau khi lớp của workspace bị siết vẫn
      đọc lớp ở dòng lượt, không tính lại.
- [ ] R2.2 (CP2): agent `vn_only` với tuyến `foreign` hay không khai → `ResidencyRefusedError` trước khi
      gửi, adapter giả ghi 0 lời gọi, lượt `failed` với `residency_refused`, không dòng `platform.usage_events`; gỡ
      cổng → test đỏ.
- [ ] R2.2 (CP2): hồ sơ có tuyến `vn` đầu và tuyến `foreign` dự phòng, tuyến `vn` trả 503 → adapter giả của tuyến
      `foreign` ghi 0 lời gọi, `ResidencyRefusedError`; cổng chỉ kiểm tuyến đầu → test đỏ. `cross_border_minimised`
      với tuyến `vn` → gửi; với tuyến `foreign` → từ chối.
- [ ] R2.2 (CP2): ở vòng agent, cùng hồ sơ `vn` đầu và `foreign` dự phòng, tuyến `vn` trả 503 → tuyến `foreign` 0
      lời gọi; `ResidencyGateMiddleware` chỉ kiểm tuyến được chọn → test đỏ.
- [ ] R2.2 (CP2): phạm vi job có `workspace_id` không đọc được dưới RLS, hay dòng công ty mang giá trị lạ (bảng thử
      bỏ CHECK) → từ chối, 0 lời gọi; một job truyền lớp `cross_border_full` vào adapter cho công ty `vn_only` → vẫn
      từ chối, vì cổng không nhận lớp từ bên gọi.
- [ ] R2.3 (CP3): chép lời khi `vn_only` tới URL `foreign` (settings không khai `data_location`) → job `failed` lý
      do `residency_refused`, 0 request. Mỗi adapter của bước 4 (gateway có cấu trúc, `ResidencyGateMiddleware`,
      embedding, rerank, trích xuất tài liệu, chép lời, nén ngữ cảnh) có một test riêng: đích `foreign` dưới `vn_only`
      → 0 request; gỡ cổng ở adapter đó → test của nó đỏ (ADR-0123 (Accepted) Consequences).
- [ ] R2.4 (CP4): đặt `cross_border_full` ở workspace khi công ty `vn_only` → 422, không đổi dòng.
- [ ] R2.7 (CP5): `PATCH` nới công ty từ `vn_only` sang `cross_border_full` → 409 `second_person_required`,
      lộ trình giữ nguyên, không audit; đưa workspace từ `vn_only` về NULL → 409, dòng giữ nguyên; gỡ chặn → test đỏ.
- [ ] R2.8: một người siết workspace từ NULL sang `vn_only` → áp ngay, audit `residency.class_changed` trong
      cùng giao dịch; gửi lại `vn_only` → 200, không audit thứ hai; lỗi ghi audit → không đổi dòng.
- [ ] CP4: người thiếu `platform.tenant.settings.write` đặt lớp cho công ty hay workspace → 403, dòng giữ nguyên;
      quản trị viên công ty B gửi `PATCH /api/v1/admin/workspaces/{id}` với id workspace của công ty A → 404, dòng
      của A giữ nguyên; thêm `data_route_class` vào thân `RenameTenantRequest` của route người vận hành → test hợp
      đồng đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py:28-55`; spec: R2.1 (ModelRoute
  không có `data_location`).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/gateway.py:100-155`; spec: R2.3 (cửa gateway
  chèn cổng, `_route` và `_attempts` chọn tuyến dự phòng).
- `packages/python/dw_knowledge/src/dw_knowledge/adapters/api_parsers.py:28`; spec: R2.3 (chép lời tới URL
  nước ngoài cố định).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/context_compaction.py:48`; spec: R2.3 (nén ngữ
  cảnh gọi model ngoài node model của agent).
- `apps/api/src/dw_api/routes/v1/admin_console.py:231`, `:314`; spec: R2.7, R2.8 (hai route quản trị).
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
- 2026-10-24 (agent): áp kiểm nhất quán vòng 3 (B:agent-builder/03\~compliance-pdpl/03): ở vòng agent, cổng không
  nằm trong factory chat model mà là một middleware ngay sau `StudioModelSelection`, trước `LimitsMiddleware`, theo
  thứ tự ngăn xếp của agent-builder/03 bước 2, để cổng chạy trước lease như usage-and-limits:R6.5 đòi (bước 4).
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (người dựng và ranh giới, vì ticket
  thêm migration và sửa hai route). CRITICAL 1: lớp của workspace là một lần ghi dữ liệu công ty mà không có test âm
  chéo tenant (`CLAUDE.md` mục 'Tenancy and authorization'); sửa: route workspace của bước 5, 404 khi id thuộc công ty
  khác, 403 khi thiếu quyền (tiêu chí CP4 thứ hai). Nếu sai thì: lớp workspace đi qua một route riêng
  `PUT /api/v1/admin/workspaces/{id}/data-route-class`, cùng hai test âm.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 1: chỉ embedding và chép lời có test gỡ cổng, trái
  ADR-0123 (Accepted) Consequences ("separately for every adapter"); sửa: mỗi adapter của bước 4 một test, gồm nén ngữ cảnh
  (gọi model ngoài node của agent, `context_compaction.py:48`). Nếu sai thì: một test tham số hóa qua danh sách
  adapter lấy từ composition root, đỏ khi một adapter thiếu cổng.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 2: tuyến dự phòng (`_attempts`, ADR-0118 (Accepted) quyết 6) có
  thể rơi từ tuyến `vn` sang tuyến `foreign` sau một 5xx; sửa: cổng kiểm từng tuyến trước lần gửi đầu, lỗi không thử
  lại, không dòng Sổ sử dụng, lượt `failed` với `residency_refused`. Nếu sai thì: cổng kiểm ngay trước mỗi lần gửi
  trong vòng thử, hành vi quan sát được như nhau.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 3: rerank, trích xuất và chép lời không có `ModelRoute` nên không
  có `data_location`; sửa: khai trong settings cạnh URL, không mặc định, thiếu là `foreign` (bước 1). Nếu sai thì: ba
  đích thành tuyến của hồ sơ model ở model-connections, ticket này chỉ đọc.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 4: lớp đến từ đâu và khi không đọc được thì sao; sửa: cổng lấy lớp
  từ `RunContext` hay từ phạm vi của job, không từ bên gọi, đóng khi không đọc được (bước 4). Nếu sai thì: bên gọi
  truyền lớp và một test kiến trúc cấm truyền lớp từ thân request.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 5: lớp của workspace không có route, quyền hay luật nới về NULL;
  sửa: bước 5 (route workspace, quyền của lộ trình, về NULL là nới → 409), spec R2.7 mở rộng sang workspace theo
  ADR-0123 (Accepted) Amendments 2026-10-24. Nếu sai thì: về NULL dưới công ty cùng lớp là không đổi gì và nhận.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 6: lớp tính mỗi lời gọi hay ghim lúc nhận lượt; sửa: ghim lúc
  nhận lượt vào `RunContext.route_class` và `platform.worker_runs`, như ADR-0123 (Accepted) quyết 3 và
  agent-builder/03 bước 4; siết áp cho lượt nhận sau đó, và ở W1 không lượt nào đổi lớp vì mọi công ty giữ `vn_only`
  (bước 3). Lớp không vào bản kê lượt chạy: dòng lượt là bản ghi duy nhất của nó, ghi ở ADR-0123 (Accepted)
  Amendments 2026-11-04. Nếu sai thì: khi đường nới W2 có, siết dừng lượt đang chạy ở lời gọi kế, như thu hồi bí mật.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 7: không ai kiểm phiên bản agent khai lỏng hơn công ty (R2.4,
  agent-builder:R1.6 trỏ về đây); sửa: phần đó vào móc gửi kiểm định của loại `agent` ở ticket 07, ticket này giữ
  phần workspace. Nếu sai thì: ticket này chờ agent-lifecycle/03 và đăng ký một kiểm riêng cho loại `agent`.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 8: "ghi lên dòng lượt chạy" không nêu bảng, cột, và
  `data_location`, `processor` không có nghĩa trên một lượt nhiều tuyến; sửa: cột `data_route_class` trên
  `platform.worker_runs` (bước 2), hai trường kia mỗi lời gọi trên span và Sổ sử dụng (bước 6). Nếu sai thì: thêm cột
  tập nơi xử lý của lượt khi có bên đọc.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận của gate (không CRITICAL mới, 5 HIGH, đã sửa): vòng
  agent cũng kiểm mọi tuyến dự phòng trước lần gửi đầu (bước 4, tiêu chí CP2 mới); lời gọi đồng bộ của API lấy lớp từ
  `AccessContext`, job toàn công ty chỉ dùng lớp công ty; hồ sơ mock khai `vn`, tuyến chưa định vị không được khai `vn`
  để test xanh (bước 1); R2.1 ghi lên dòng Sổ sử dụng mà adapter đã ghi, không thêm dòng mới (bước 6); không route nào
  khác nhận `data_route_class`, có test hợp đồng (bước 5). Nếu sai thì: mỗi mục quay về bản trước trong lịch sử git.
- 2026-11-04 (agent): MEDIUM, để người dựng: (a) `cross_border_minimised` từ chối đích `foreign`, nhận đích `vn` (bước
  4, "ticket 13" cũ không tồn tại); (b) eval của nền tảng chạy `vn_only` nên cần một tuyến `vn` hay bộ chấm giả; (c)
  `residency_refused` trong một Bước `ai.llm` hay `ai.agent` có cổng lỗi: đề xuất lượt `failed`, không đi cổng lỗi, vì
  đó là lời từ chối của chính sách chứ không phải lỗi của node; người dựng đối chiếu với luật cổng lỗi của
  workflow-nodes trước khi chọn; (d) chưa có test âm cho người giữ `platform.tenant.settings.write` neo ở một
  workspace khác (ở W1 chỉ siết được, tác hại thấp).
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
