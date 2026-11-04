# 01 — Sổ kích hoạt, chạy tay và chạy mô phỏng, chạy dưới danh nghĩa tài khoản dịch vụ qua điểm gắn

Status: ready-for-agent
Blocked by: .claude/plans/studio/workflow-engine/issues/04-lan-studio-runs.md, .claude/plans/studio/org-and-principals/issues/03-tai-khoan-dich-vu-run-as.md, .claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md, .claude/plans/studio/agent-lifecycle/issues/05-tat-khan-cap-va-khoi-phuc.md, .claude/plans/studio/workflow-nodes/issues/03-pham-vi-bien-va-buoc-logic.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.4, R1.5, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.8, R2.9, R2.10, R3.1, R3.2, R3.3, R3.4, R3.5, R6.7, TR8, TR9, TR12, TR16, TR20, TR22

## Mục tiêu

Dựng sổ kích hoạt (đăng ký và lần kích hoạt) với bộ chuyển của đăng ký, loại bước `trigger.datahub@1`, chạy tay và chạy
mô phỏng qua `RunRequestService`, với một quyết định giả lập cho mỗi Bước phê duyệt của lượt mô phỏng, và danh tính chạy là
tài khoản dịch vụ ở điểm gắn `run_as` duyệt bởi người khác, không bao giờ người phát hành (R1, R2, R3, R6.7 của spec;
dòng 4/11/2026). Làn `studio_inbound` và cửa nhận gọi bộ chuyển này ở ticket 02.

## Việc cần làm

1. Migration (revision hex của alembic): `studio.trigger_subscriptions` và `studio.trigger_deliveries`, chép nguyên văn
   mục Dữ liệu của spec. `studio.trigger_subscriptions`: PK `(tenant_id, id)`; `artifact_id` FK `(tenant_id, artifact_id)`
   tới `studio.artifacts (tenant_id, id)` ON DELETE CASCADE, index `(tenant_id, artifact_id)`; `artifact_version_id` FK
   ghép `(tenant_id, artifact_version_id)` tới `studio.artifact_versions (tenant_id, id)` (`uq_artifact_versions_tenant_id_id`
   của tenant-config/02) ON DELETE CASCADE, index `(tenant_id, artifact_version_id)`; `endpoint_artifact_id` NULL, FK ghép
   `(tenant_id, endpoint_artifact_id)` tới `studio.artifacts (tenant_id, id)` ON DELETE CASCADE, CHECK
   `(trigger_kind = 'datahub') = (endpoint_artifact_id IS NOT NULL)`, index `(tenant_id, endpoint_artifact_id) WHERE status
= 'active'`; `trigger_kind text NOT NULL` CHECK (`datahub`, `provider_app`, `schedule`, `record_event`, `agent_tool`) theo
   ADR-0113 (Accepted) quyết 5; `status text NOT NULL` CHECK (`active`, `retired`), không DEFAULT; `created_at`; partial
   unique một `active` mỗi `(tenant_id, artifact_id, trigger_kind)`; không `workspace_id`, một dòng lý do trong danh sách
   bảng toàn tenant của `test_rls_coverage.py` (cấu hình của thành phần; DO-01); không cột danh tính chạy (R3.2).
   `studio.trigger_deliveries`: PK `(tenant_id, id, occurred_at)`; `subscription_id`, `inbound_event_id`, `run_id` NULL
   không FK (`subscription_id` NULL ở dòng của cửa nhận); `workspace_id uuid NOT NULL` (ảnh chụp workspace sở hữu của quy
   trình, hay của Nguồn dữ liệu ở dòng của cửa nhận, lúc ghi); `outcome text NOT NULL` CHECK (`run_requested`,
   `duplicate`, `held_frozen`, `refused_killed`, `quarantined`, `rejected`); `occurred_at timestamptz NOT NULL`; phân vùng
   tháng có DEFAULT, RLS chỉ theo tenant từng phân vùng, append-only, một dòng `platform.time_partitioned_tables`
   (studio-skeleton/01). Grant cùng migration; `test_privileges.py` khẳng định.
2. Lưu giữ của `studio.trigger_deliveries` (R6.7; H-1): mảnh `configs/policies/retention.d/studio.trigger_deliveries.yaml`
   (`days: 90`, `purger: row_delete`, `enforced: true`, số tạm UNVERIFIED tới khi luật sư chốt, DO-52) trong cùng thay đổi
   tạo bảng; bộ xóa là một hàm SECURITY DEFINER hẹp không đối số (`search_path` cố định, REVOKE EXECUTE khỏi `PUBLIC`), đọc
   hạn qua `platform.retention_term_days('studio.trigger_deliveries')` (telemetry-and-audit:R5.12), không ghi cứng số, trả
   số dòng đã xóa; đăng ký vào `RetentionPurgerRegistry` ở composition root của worker (telemetry-and-audit:R5.1); test gọi
   thẳng hàm.
3. Adapter đáp ứng `TriggerActivationPort` mà workflow-engine/01 khai: móc phát hành của loại `workflow` gọi nó cho phiên
   bản vừa lên `live`, trên đúng giao dịch phát hành mà móc truyền (workflow-engine:R1.6, agent-lifecycle:R5.5), không mở
   giao dịch riêng; với mỗi mục `triggers[]` loại `trigger.datahub@1` ghi một đăng ký `active` mang `endpoint_artifact_id`,
   thu hồi (`retired`) đăng ký của phiên bản trước; thành phần nêu không phải kind `endpoint` → ném lỗi, giao dịch phát hành
   lùi; mục kind `call` (workflow-engine/09) không đăng ký gì; gọi lại cho cùng phiên bản không đổi gì. Composition root nối
   adapter ở `build_studio`. Không audit riêng (Trong phạm vi của spec, mục Audit).
4. Loại bước `trigger.datahub@1` trong `studio_node_types(ports)` của workflow-nodes/03
   (`packages/python/dw_studio/src/dw_studio/workflows/node_registry.py`): cấu hình `{endpoint: <id thành phần>}`;
   `dependencies(config)` trả `(artifact, <id>, read, /triggers/<i>/config/endpoint)`, nên bước niêm phong ghim phiên bản
   Nguồn dữ liệu và Nơi đang dùng của tenant-config thấy nó (R4.6); lược đồ `trigger.input` mà `expression_env` dẫn là lược
   đồ của phiên bản Nguồn dữ liệu đó trong bao đóng. Đầu vào của chạy tay và mô phỏng kiểm theo đúng lược đồ `trigger.input`
   đó, cùng hàm của `expression_env`, không bản sao; tài liệu không mục nào khai lược đồ đầu vào thì chỉ nhận `{}` (R2.4).
5. Bộ chuyển `TriggerDispatcher.dispatch(uow, subscription, event_id, input) -> outcome`, gọi trong giao dịch của bên gọi
   (làn của ticket 02): Tắt khẩn của quy trình qua `RunControlPort` (agent-lifecycle:R8.1) → lần kích hoạt `refused_killed`,
   không lượt (R1.4); đọc giá trị đã duyệt của điểm gắn `run_as` trong Bộ giá trị gắn của thành phần (tenant-config/05), cùng
   bộ mà `RunManifestBuilder` ghim trong giao dịch này; thiếu → lần kích hoạt `rejected` với lý do `binding_unset`, không
   lượt; có → `RunRequestService.request` với `LaneRequester(studio_inbound, tenant_id)`, chủ thể là tài khoản đó, khóa nguồn
   `<subscription_id>:<event_id>`, `inbound_event_id` là `event_id` (workflow-engine/02 bước 3 (c), (f); R1.5: `request_key`
   là của `RunRequestService`); `created = true` → `run_requested`, `false` → `duplicate`; một dòng `trigger_deliveries` mỗi
   kết quả, mang `subscription_id`, `inbound_event_id`, `run_id`. Composition root đăng ký `studio_inbound → {datahub}`
   vào sổ lane đóng băng của workflow-engine/02. Bộ chuyển không gọi runner.
6. `POST /api/v1/studio/workflows/{artifact_id}/runs` (bản đang dùng, chế độ `live`) và
   `POST .../versions/{version_id}/test-runs` (W1 chỉ `simulate`; `test`, `live` → 422), cả hai `Idempotency-Key` bắt buộc
   (app-standards/02), khóa nguồn của `RunRequestService` cho `manual`, `test`. Composition root thêm mục
   (`workflow`, `manual`) → `studio.workflows.run` vào bảng khóa chạy của `RunRequestService` (workflow-engine:R3.17); cửa
   đó là chỗ thi hành khóa và độ sâu ở workspace sở hữu (`platform.workspace_reach`), route chỉ trả lời sớm; người không đọc
   được quy trình nhận 404, đọc được mà thiếu khóa chạy nhận 403 (ADR-0104 (Accepted) quyết 11). `version_id` không thuộc
   `artifact_id` → 404 (R2.5). Thân `/runs` mang khóa `simulated_decisions` → 422 (R2.10). `test-runs`: mở giao dịch, đọc
   nội dung phiên bản dưới `FOR SHARE` như `RunRequestService` (workflow-engine/02 bước 3 (b)), kiểm `simulated_decisions`
   với tập id Bước phê duyệt (`human.approval@2`, tên loại do workflow-nodes/06 làm chủ và đọc từ sổ loại, không viết cứng; `STUDIO_RULES` từ chối `@1` trên đường Studio) của đúng nội dung đó (thiếu hay thừa → 422 mỗi id một lỗi, R2.8), rồi gọi
   `RunRequestService.request` trong cùng giao dịch và đưa quyết định vào đầu vào của lượt (R2.7, workflow-nodes:R9.9);
   lần từ chối vì bản Nháp trượt bộ kiểm → 422 `validation_failed` với mọi lỗi `wf.*` (R2.9), route không chạy bộ kiểm thứ
   hai. Test dùng một loại bước giả `human.approval@2` trong fixture tới khi workflow-nodes/06 đăng ký loại thật. Migration
   của ticket này đăng ký `studio.workflows.run` vào danh mục quyền theo quy ước khóa của tenant-rbac/01, câu INSERT nêu mọi
   cột NOT NULL không DEFAULT lúc đó, kể cả `risk` và `tenant_grantable` (V4.P2); `studio.workflows.test` là của
   workflow-engine/01 (H-19).
7. Điểm gắn `run_as` (R3.1-R3.4): kiểm của nó đăng ký vào bộ kiểu Điểm gắn của `binding_set` (tenant-config/05), chạy ở
   mỗi lần đề xuất mang `run_as`, kể cả khi giá trị không đổi: giá trị phải là tài khoản dịch vụ (`kind = service`) của
   chính công ty (một thành viên là người → 422 `validation_failed`), và kiểm gắn run-as của org-and-principals/03 (org-and-principals:R6.5, R6.7; `grants_cover` và mọi điều kiện của nó, không bản thứ hai) cho Người
   đề xuất (thiếu → 403 `rbac_escalation`). Thiếu giá trị thì `PublishBindingsCheck` làm lệnh gửi trả 409 `binding_unset`
   và handler `.decided` không đưa phiên bản lên Đang dùng (agent-lifecycle:R2.11, agent-lifecycle:R5.10;
   tenant-config:R7.2). R3.5: kiểm lúc kích hoạt rằng tài khoản `run_as` đọc được mọi trường mà điều kiện của trình kích
   hoạt dùng; ở W1 `trigger.datahub@1` không có điều kiện, nên kiểm này là hàm có bảng ca và không chặn gì tới khi một loại
   trình kích hoạt có điều kiện ra đời (W2).

## Tiêu chí chấp nhận

- [ ] R1.1: móc phát hành của `workflow` gọi `TriggerActivationPort` cho phiên bản mới có một `trigger.datahub@1` trong
      một giao dịch thử → đăng ký cũ `retired`, mới `active` mang `endpoint_artifact_id`, cùng giao dịch; giao dịch đó lùi →
      đăng ký cũ vẫn `active`, không dòng mới; adapter mở giao dịch riêng → test lùi thấy dòng mới còn lại, test đỏ;
      `endpoint` trỏ tới một thành phần kind `workflow` → lỗi, phát hành lùi; `dw_app` gắn tenant A chèn đăng ký mang
      `artifact_id`, `artifact_version_id` hay `endpoint_artifact_id` của tenant B, mỗi lần đúng một cột → lỗi FK, không dòng
      nào được ghi; đổi một trong ba FK ghép về FK một cột → ca của nó qua, test đỏ; `test_offboarding.py` purge một tenant
      có đăng ký → xong, tenant khác nguyên.
- [ ] R1.1: tài liệu có `trigger.datahub@1` nêu một Nguồn dữ liệu → bước niêm phong ghi một dòng `studio.dependencies`
      `artifact` `read` tới nó; Nguồn dữ liệu chưa `live` → `dependency_unresolved` tại con trỏ của mục.
- [ ] R1.2: bộ chuyển với một đăng ký và một id sự kiện → một lượt chạy qua `RunRequestService` và một dòng
      `trigger_deliveries` `run_requested` mang `subscription_id`, `inbound_event_id`, `run_id`; gọi lại cùng cặp → một lượt,
      dòng thứ hai `duplicate`; bộ chuyển không gọi runner; `POST .../runs` và `test-runs` không ghi dòng nào.
- [ ] R1.4 (TR9): quy trình bị Tắt khẩn → bộ chuyển ghi `refused_killed`, không lượt chạy; bỏ kiểm Tắt khẩn → test đỏ.
- [ ] R1.5: hai lần gọi bộ chuyển cùng đăng ký và sự kiện → một dòng lượt chạy, `request_key` do `RunRequestService` dựng.
- [ ] R2.1 (TR20): `POST .../runs` của người giữ `studio.workflows.run` ở workspace sở hữu → một lượt chạy bản đang dùng
      ở `live`; thiếu `Idempotency-Key` → 422; người không giữ khóa → 403, không lượt; giữ khóa chỉ ở ws1 với quy trình ws2
      sở hữu → 403, không lượt; gỡ mục (`workflow`, `manual`) khỏi bảng khóa chạy → mọi người nhận `permission_denied`,
      test đỏ ở ca đúng; quy trình chưa có bản Đang dùng → 409 `conflict`, không lượt.
- [ ] R2.10 (TR22): `POST .../runs` với thân mang `simulated_decisions` → 422, không lượt; gỡ kiểm → test đỏ.
- [ ] R2.2 (TR12): `test-runs` với chế độ `live` → 422, không lượt chạy; bỏ kiểm chế độ → test đỏ.
- [ ] R2.3: `test-runs` với `simulate` của người không giữ `studio.workflows.test` → 403, không lượt chạy, và kiểm khóa ở
      cửa bị gỡ → test đỏ; của người giữ khóa → một lượt chạy ở `simulate`; cho một bản Nháp → lượt chạy có bản kê ghi giai
      đoạn `draft` và mã băm tạm của nội dung nháp lúc nhận; thiếu `Idempotency-Key` → 422.
- [ ] R2.9: `test-runs` với `simulate` cho một bản Nháp có một node không tới được và một biểu thức sai kiểu → 422
      `validation_failed` với hai lỗi `wf.unreachable_node`, `wf.type_mismatch` có con trỏ, 0 dòng `worker_runs`, 0 bản kê;
      bộ kiểm chạy đúng một lần, trong `RunRequestService` (spy); trả lần từ chối đó thành mã khác 422 hay bỏ lỗi nào khỏi
      `errors[]` → test đỏ.
- [ ] R2.6: `test-runs` với `test` → 422, không lượt chạy.
- [ ] R2.7: `test-runs` với `simulate` cho phiên bản có hai Bước phê duyệt, thân nêu `approved` và `rejected` → lượt mô
      phỏng mang đúng hai quyết định đó trong đầu vào, theo id Bước.
- [ ] R2.8 (TR16): thân thiếu quyết định cho một Bước phê duyệt → 422 có lỗi nêu id đó, không lượt chạy; thân nêu quyết
      định cho id của một Bước khác loại → 422 nêu id đó; một lần lưu nháp thêm Bước phê duyệt chờ sau khóa `FOR SHARE` của
      yêu cầu → lượt mô phỏng mang đúng tập của nội dung đã đọc; bỏ kiểm → test đỏ.
- [ ] R2.4: đầu vào sai lược đồ `trigger.input` của nội dung ghim → 422 theo trường, không lượt chạy; tài liệu không mục
      nào khai lược đồ và đầu vào `{"a": 1}` → 422; `{}` → nhận.
- [ ] R2.5 (TR20): tenant B gọi `artifact_id` của tenant A ở `/runs` và `test-runs` → 404, không lượt chạy; `version_id`
      của một quy trình khác cùng tenant → 404.
- [ ] R3.1: đề xuất `run_as` cho một tài khoản dịch vụ mà Người đề xuất không giữ đủ quyền → 403 `rbac_escalation`; đề
      xuất `run_as` là một thành viên người → 422; đề xuất lại Bộ giá trị gắn chỉ đổi một kết nối, giữ nguyên `run_as`, bởi
      người không phủ quyền của tài khoản → 403; bỏ kiểm khi giá trị không đổi → test đỏ.
- [ ] R3.2 (TR8): người phát hành rời tenant → lượt chạy vẫn chạy bằng tài khoản `run_as`; Bộ giá trị gắn duyệt lại với
      tài khoản B → sự kiện kế tiếp chạy dưới B mà không phát hành lại; gắn người phát hành làm chủ thể → test đỏ.
- [ ] R3.3: lượt mô phỏng → runner chạy dưới danh nghĩa người thử.
- [ ] R3.4 (TR8): gửi một phiên bản thiếu giá trị `run_as` → 409 `binding_unset` ở lệnh gửi, phiên bản ở Nháp, không tạo
      đăng ký; bộ chuyển gặp Bộ giá trị gắn không có `run_as` → `rejected`, không lượt; kiểm điểm gắn của kind `principal`
      trả là đã có giá trị khi chưa có → test đỏ.
- [ ] R3.5: hàm kiểm trường của điều kiện, bảng ca với một điều kiện giả nêu trường mà tài khoản không đọc được → từ chối
      tạo đăng ký; `trigger.datahub@1` (không điều kiện) → không chặn.
- [ ] R6.7: lần kích hoạt quá 90 ngày bị bộ xóa của `studio.trigger_deliveries` xóa, 89 ngày còn nguyên; hạ hạn thử còn
      20 ngày → dòng 21 ngày bị xóa; xóa dòng hạn → hàm báo lỗi `P0002`, không dòng nào mất; tập mảnh có mảnh
      `studio.trigger_deliveries`.
- [ ] R3.1: đề xuất `run_as` là id tài khoản dịch vụ của công ty khác → 404 của kiểm kind `principal` (tenant-config/05),
      không dòng nào được ghi; cho kiểm đó nhận id ngoài công ty → test đỏ.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/runtime_tables.py:38`; `apps/api/src/dw_api/routes/v1/zalo.py:212-213`; spec: R1, R2, R3, R6.7, TR8, TR9, TR12, TR16, TR20, TR22.
- workflow-engine:R1.6 (móc phát hành gọi `TriggerActivationPort`), R3.3, R3.6, R3.11, R3.17 (bảng khóa chạy), workflow-engine/02 bước 3 (sổ lane, khóa nguồn); workflow-nodes/03 (`studio_node_types`, `expression_env`); org-and-principals:R6.5, R6.7; tenant-config:R7.2; ADR-0103 (Accepted) quyết 4, ADR-0113 (Accepted) quyết 4, 5.

## Comments

- 2026-10-23 (agent): ticket còn needs-info vì DO-12 (chủ thể của lượt chạy không người) và DO-06 (tên điểm gắn so với id trong phiên bản) chưa được Đạt chốt; thiết kế theo khuyến nghị (a) của cả hai.
- 2026-10-23 (agent): DO-06 và DO-12 (cùng DO-17.2) đã có lời đáp (Đạt 23/10/2026), nên ticket về `needs-triage`. Theo phiếu cùng ngày: W1 chỉ chạy thử `simulate` (DO-26.1), khóa đổi theo dạng `studio.<area>.<verb>`, kiểm `principal` đăng ký vào bộ kiểu Điểm gắn của `binding_set`, `trigger_kind` theo ADR-0113 (Accepted), `workspace_id` trên `studio.trigger_deliveries` (DO-01).
- 2026-10-24 (agent): theo quyết định của Đạt ngày 24/10/2026: ticket chờ agent-lifecycle/05 (Tắt khẩn của R1.4, TR9); lượt `simulate` gọi là chạy mô phỏng và mang một quyết định giả lập cho mỗi Bước phê duyệt (N2: R2.7, R2.8, TR16); khóa theo dạng `studio.<areas>.<verb>`.
- 2026-10-24 (agent): vòng sửa thứ tư: theo V4.4, `test-runs` nhận bản Nháp và đọc tập Bước phê duyệt từ nội dung lượt chạy ghim (R2.3, R2.8); `binding_unset` ở lệnh gửi và handler `.decided` qua `PublishBindingsCheck` (R3.4, TR8); khóa ngoại của hai bảng nêu ON DELETE, khóa chính của bảng phân vùng mang cột phân vùng, `studio.trigger_subscriptions` vào `_ORDERED_FIRST` (phát hiện E về CLAUDE.md, Data model rules); câu INSERT khóa nêu `tenant_grantable` (V4.P2) và dẫn quy ước khóa của tenant-rbac/01 (V4.P10). Ticket chờ tenant-rbac/02 qua workflow-engine/04, không thêm cạnh.
- 2026-10-24 (agent): lượt b của vòng 4: route `test-runs` chạy bộ kiểm khi gửi kiểm định trên bản Nháp trước khi xin lượt (R2.9; ADR-0112 (Accepted) quyết 3, ADR-0109 (Accepted) quyết 6); `artifact_version_id` và `run_as_principal_id` thành FK ghép, để cơ sở dữ liệu chặn tham chiếu chéo tenant; nhãn vòng 4 đổi thành `V4.<n>`, `V4.P<n>`.
- 2026-10-24 (agent): lượt c của vòng 4: đăng ký kích hoạt ghi qua adapter của `TriggerActivationPort`, mà móc phát hành của loại `workflow` gọi trong giao dịch phát hành (R1.1, workflow-engine:R1.6); bộ kiểm trên bản Nháp chạy ở `RunRequestService`, route chỉ trả lần từ chối thành 422 (R2.9, workflow-engine:R3.11), thay câu của lượt b ở bước 3. Không thêm cạnh: ticket này đã chờ workflow-engine/01 và /02 qua workflow-engine/04, và test R1.1 gọi móc trong giao dịch thử, không qua agent-lifecycle/04.
- 2026-10-24 (agent): lượt d của vòng 4: dòng Comments của lượt b, c thôi dẫn mã mục của lượt, nội dung giữ nguyên; bước 1 nêu tên index của từng FK, vì mọi khóa ngoại có index dẫn bằng cột của nó (CLAUDE.md, Data model rules). Không thêm cạnh.
- 2026-10-24 (agent): ca chéo tenant của tiêu chí R1.1 thêm FK ghép `artifact_id` cạnh `artifact_version_id` và `run_as_principal_id`, mỗi FK một ca và một test đột biến đổi nó về FK một cột, vì mọi FK ghép của spec có ca "dòng của công ty A trỏ tới dòng của công ty B → lỗi FK" ở ticket tạo nó (CLAUDE.md, Tenancy and authorization; failure-modes #3). Không thêm cạnh.
- 2026-10-26 (agent): vòng 4, lượt h, theo H-19: khóa `studio.workflows.test` nay do workflow-engine/01 đăng ký (workflow-engine:R1.5), ticket này chỉ kiểm nó ở route `test-runs` (bước 3, tiêu chí R2.3 thêm ca 403); workflow-engine/01 đã là tổ tiên qua workflow-engine/04, nên không thêm cạnh. Thân `test-runs` không đổi ở W1: kết quả giả lập ghim theo Bước của ca kịch bản đi qua lane `studio_gate` (agent-lifecycle/06) và wrapper của workflow-engine/03, còn route `test-runs` nhận kết quả ghim ở W2 (H-18).
- 2026-10-26 (agent): vòng 4, lượt h, theo H-2: `studio.trigger_subscriptions` thôi vào `_ORDERED_FIRST`; thứ tự xóa của nó trước `platform.tenant_members` do sổ bước xóa của foundations-hardening/07 suy từ cạnh RESTRICT (bước 1, tiêu chí R1.1). Không đổi cạnh: foundations-hardening/07 đã là tổ tiên qua workflow-engine/04.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness (builder check và boundary walk trong một subagent,
  vì ticket có migration và route; lượt xác nhận ngữ cảnh mới sau các sửa): 0 CRITICAL, 13 HIGH đã sửa theo khuyến nghị
  (dòng 4/11/2026 của spec): `trigger.datahub@1` và `endpoint_artifact_id` (đăng ký nêu Nguồn dữ liệu, loại bước có chủ);
  cột `run_as_principal_id` bỏ, `run_as` đọc từ Bộ giá trị gắn đã duyệt lúc xin lượt, kiểm ở mọi lần đề xuất, thành viên
  người bị từ chối; bộ chuyển `TriggerDispatcher` với mục sổ lane `studio_inbound` và mục bảng khóa chạy
  (`workflow`, `manual`) mà workflow-engine/02 giao; R1.3 sang ticket 02 (Đóng băng là của làn); mảnh lưu giữ và bộ xóa
  của `studio.trigger_deliveries` về ticket tạo bảng (R6.7, H-1); TR20 cho route chạy Thật; R2.10 và TR22 chặn quyết định
  giả lập ở lượt `live`; `Idempotency-Key` bắt buộc ở `test-runs`; tập Bước phê duyệt kiểm trong giao dịch của yêu cầu;
  đầu vào theo `trigger.input` của `expression_env`; hai audit kích hoạt không ai ghi bỏ; lượt xác nhận: `run_as` của công ty khác → 404 có tiêu chí, kiểm gắn run-as là của
  org-and-principals/03, không bản thứ hai. Quy trình chưa có bản Đang dùng
  → 409 `conflict` ở `/runs` (agent, theo ủy quyền 31/10/2026; Nếu sai thì: 404 như id không tồn tại). Nếu sai thì: như
  `Nếu sai thì:` của các dòng 4/11/2026 trong spec.
- 2026-11-04 (agent): MEDIUM của gate, chưa sửa: (M1) payload của sự kiện kiểm theo bản `live` của Nguồn dữ liệu lúc nhận,
  còn `trigger.input` của quy trình theo bản mà bao đóng ghim; một Nguồn dữ liệu phát hành bản mới sau quy trình làm trường
  mới vắng trong kiểu của quy trình, trường bỏ đọc ra `null` lúc chạy. (M2) Đăng ký `retired` không ai xóa ngoài cascade
  của thành phần; số dòng tăng theo số lần phát hành, không theo sự kiện. (M3) Ai cũng giữ `studio.workflows.run` thì chạy
  tay được một quy trình chỉ dành cho Nguồn dữ liệu với đầu vào tự gõ ở `live`; lượt đứng tên người đó và có audit
  `run.started`. (M4) Bước phê duyệt trong quy trình con của `flow.subworkflow` không nhận quyết định giả lập từ thân
  `test-runs` ở W1. (M5) Tắt khẩn hay Đóng băng lúc chạy tay do dispatch của workflow-engine/04 quyết (R5.12, R5.14), route
  không kiểm lần hai.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): `checking-plan-consistency` của vùng studio (B:workflow-nodes/06~workflow-triggers/01, HIGH): `test-runs` lọc `simulated_decisions` theo tên `human.approval@1` trong khi workflow-nodes/06 đăng ký `human.approval@2` và từ chối `@1` trên đường Studio, nên tập lọc luôn rỗng và mọi quyết định giả lập bị 422; nay lọc theo loại phê duyệt đọc từ sổ, fixture dùng `@2`. Nếu sai thì: workflow-nodes/06 giữ tên `@1` cho Studio và ADR-0112 (Accepted) bỏ dòng `@2` của nó.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): workflow-engine/01 đã dựng: `TriggerActivationPort` (`activate(tx, version_id)`) ở `dw_studio/workflows/application/ports.py`; `build_studio` nối tạm `NoTriggerSubscriptions` (`dw_studio/workflows/adapters/triggers.py`), không làm gì vì chưa có `studio.trigger_subscriptions`. Ticket này thay nó ở `build_studio` bằng adapter ghi đăng ký trên giao dịch phát hành, và thêm mục (`workflow`, `manual`) vào `_RUN_KEYS`, cạnh mục (`workflow`, `test`) → `WORKFLOWS_TEST_SCOPE` đã có. Nếu sai thì: `build_studio` không đăng ký loại `workflow` tới khi có adapter thật.
