# 04 — Sàn gửi tin marketing: phần còn lại sau lõi (sổ bước ở hai composition root, nhãn audit)

Status: ready-for-agent
Blocked by: .claude/plans/studio/tools-and-skills/issues/01-executor-kiem-schema-va-nha-may.md, .claude/plans/studio/telemetry-and-audit/issues/01-otel-khong-noi-dung-va-metric.md
Area: studio
Yêu cầu: R3.12, CP25

## Mục tiêu

Lõi của Sàn gửi tin đã dựng ở ticket 08 (resolved): ba bảng, `MarketingSendPolicy` thỏa `SendAdmissionPort`, bước
`send_floor` trong sổ bước của `ToolExecutor`, route hủy nhận, hai mảnh retention, bước xóa offboarding
`platform.purge_tenant_marketing`, R3.1-R3.4, R3.6-R3.11, R5.6. Ticket này chứng minh bước sàn gửi tin có mặt ở sổ bước
của cả API và worker và test của nó đỏ được (spec R3.12, CP25; H-3), và thêm nhãn tiếng Việt cho các hành động audit mà
lát này ghi ở W1. Overlay công ty chỉ siết (R3.5, CP11) là W2 cùng kind `policy` của tenant-config, và đối tượng đọc
Bản ghi đồng ý của gói là W2 (hai dòng của Ngoài phạm vi của spec).

## Việc cần làm

1. Đọc ticket 08 trước. Không tạo lại bảng, policy, route, mảnh retention hay bước xóa nào của nó; ticket này không
   thêm migration, route hay màn hình.
2. Sổ bước (spec R3.12, CP25): bước `send_floor` đã đăng ký ở `build_tool_executor_steps()`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/wflite_host.py:121`) và không có trong
   `PENDING_STEPS` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:236`); test sổ có ở
   `packages/python/dw_agent_runtime/tests/unit/test_tool_steps.py:101`. Thêm một test cho mỗi composition root
   (`apps/api/src/dw_api/bootstrap/runtime.py:240`, `apps/worker/src/dw_worker/composition.py:347`): `ToolExecutor` mà
   root dựng có `send_floor` ở vị trí của tools-and-skills:R2.6 (thứ tự tương đối của `TOOL_STEP_ORDER`: sau
   `approval`, trước `claim`) và có `send_admission` là `MarketingSendPolicy` thật khi có `UNSUBSCRIBE_SIGNING_SECRET`;
   thiếu bí mật ở profile không triển khai thì `build_send_floor` trả `None`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/wflite_host.py:89-100`) và mọi tin bị từ chối
   `blocked:send_floor_unavailable` (`executor.py:739`), đóng khi thiếu như ADR-0124 (Accepted) đòi ở mọi profile;
   test integration trên PostgreSQL thật, lời gọi qua bước `tool.call`. Dấu gửi tin là một: khối `message` của `ToolSpec`
   (`sends_message`), mà `effect_class: message` của một Hành động dịch thành (tools-and-skills:R3.1), nên sàn chạy
   đúng một lần mỗi lời gọi; ticket này không thêm lời gọi sàn thứ hai.
3. Viết `mutations/04.yaml` (chạy ở lúc đóng hàng đợi, `.claude/rules/wave-close.md`): (a) gỡ dòng
   `steps.register("send_floor", ...)` → test sổ đỏ (`seal` từ chối một bước của R2.6 không đăng ký, không chờ); (b) gỡ
   dòng đó và trả `send_floor` về `PENDING_STEPS` → `email.send` thiếu đồng ý trả `blocked:send_floor_unavailable`
   thay vì `blocked:no_consent`, test sàn của R3.2 đỏ; (c) bỏ `send_admission` ở root của API → test root của API đỏ;
   (d) cùng đột biến ở root của worker → test root của worker đỏ; (e) gọi `admit` hai lần trong một lời gọi → test
   "đúng một lần" đỏ.
4. Nhãn audit: `configs/copy/audit_actions.d/compliance-pdpl.yaml` theo định dạng của
   `configs/copy/audit_actions.d/runtime-hardening.yaml` (`schema_version`, `copy_id`
   `platform.audit_actions.compliance_pdpl`, `version`, `actions`), mỗi hành động audit của lát ở W1 một nhãn tiếng
   Việt: `marketing.sent`, `marketing.send_refused` (ticket 08 đã ghi), `residency.class_changed` (ticket 03),
   `studio.conversation.expired` (ticket 06); một tệp, một chủ: ticket 03 và 06 không sửa tệp này. Bộ gộp danh mục là
   của telemetry-and-audit (telemetry-and-audit:R1.6; H-21), và test AST TA15 của telemetry-and-audit/03 đỏ khi một
   hành động ghi trong mã không có khóa trong mảnh nào, nên bước này không có test riêng. Ticket 03 không chờ được
   ticket này (phụ thuộc chỉ trỏ ngược), nên làm ticket này trước ticket 03: ticket này không chờ việc nào chưa xong.

## Tiêu chí chấp nhận

- [ ] R3.12 (CP25): test root của API và của worker: sổ bước có `send_floor` sau `approval`, trước `claim`, không
      trong `PENDING_STEPS`, và `send_admission` được đặt; `email.send` thiếu đồng ý qua executor của mỗi root →
      `blocked:no_consent`, không `blocked:send_floor_unavailable`, đúng một dòng nhật ký gửi `blocked` và đúng một
      `marketing.send_refused` (sàn chạy một lần); bỏ `send_admission` ở một root → test của root đó đỏ.
- [ ] R3.12 (CP25): root dựng không có `UNSUBSCRIBE_SIGNING_SECRET` ở profile `test` → `email.send` trả
      `blocked:send_floor_unavailable`, máy SMTP giả 0 lời gọi; một nhánh bỏ qua sàn khi thiếu nó → test đỏ.
- [ ] R3.12 (CP25): `mutations/04.yaml` có năm đột biến (a)-(e) của bước 3, mỗi đột biến nêu test mà nó làm đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/wflite_host.py:121`; spec: R3.12 (bước sàn gửi tin
  đã đăng ký).
- `packages/python/dw_agent_runtime/tests/unit/test_tool_steps.py:101`; spec: CP25 (test sổ đã có).
- `apps/api/src/dw_api/bootstrap/runtime.py:240`, `apps/worker/src/dw_worker/composition.py:347`; spec: CP25 (hai root
  dựng sàn).
- ADR-0124 (Accepted) quyết 1, 2; ADR-0110 (Accepted) quyết 3 (kind `policy` ở W2).

## Comments

- 2026-10-23 (agent): gộp B11-security compliance-pdpl 04 và phần đồng ý của B12-product marketing-pilot 08. `needs-info` vì DO-55 (số chống spam, lời văn đồng ý người nhận thử) chờ luật sư; số giữ UNVERIFIED.
  Sổ đồng ý là của nền tảng; object Consent của gói Marketing là view đọc.
- 2026-10-23 (agent): DO-55 có lời đáp cho W1 (Đạt, 23/10/2026: số tạm UNVERIFIED), nên `needs-triage`. Áp
  E:CLAUDE.md#tenancy-and-authorization~compliance-pdpl:platform.consent_records (a) và ADR-0124 (Accepted):
  đồng ý và chặn gửi toàn tenant, nhật ký gửi hình workspace; DO-02.2 cho partition; từ khóa hủy Zalo sang W2.
  Số người nhận tối đa mỗi lượt mà ADR-0124 (Accepted) quyết 6 khai chưa có số tạm, nên bước 4 chưa đặt nó.
- 2026-10-24 (agent): áp quyết định của Đạt ngày 24/10/2026: DO-55 có số tạm (200 người nhận mỗi lượt ở thí điểm,
  công ty chỉ hạ), bước 4 đặt nó và bước 2 đọc nó (`blocked:recipient_cap`, spec R3.8), nên `needs-triage` giữ
  nguyên (H:ADR-0124 (Accepted)\~compliance-pdpl/04); mỗi lần chặn ghi một dòng nhật ký gửi `blocked` vì ở W1 Tương
  tác là dòng nhật ký gửi (N4); thêm thời hạn của hai bảng `append_only` trong cùng thay đổi đăng ký và chờ
  telemetry-and-audit/03 để các ticket sửa tệp retention có một thứ tự; dòng `STUDIO_EXCLUSIONS` cho offboarding.
- 2026-10-24 (agent): áp quyết định của Đạt ngày 24/10/2026 cho kiểm nhất quán vòng 3: `recipient_cap` là lý do
  chặn của ADR-0124 (Accepted) quyết 1 và lần chặn ghi một dòng nhật ký gửi `blocked`
  (F:ADR-0124 (Accepted)\~compliance-pdpl:R3.8), nên bước 2 và R3.8 giữ nguyên tên. Theo các dòng tạm cùng ngày
  của spec: chờ workflow-triggers/02, ticket đứng trước trong chuỗi các ticket sửa tệp retention
  (C:configs:spec\~telemetry-and-audit/03); trigger `platform.guard_contact_suppression()` chỉ cho lượt xóa của
  offboarding xóa dòng chặn gửi (spec R5.6, CP19; D:agent-lifecycle:R7.5\~compliance-pdpl:R5.4).
- 2026-10-24 (agent): kiểm sau lượt sửa: tiêu chí R3.8 (CP18) nay khẳng định cả dòng nhật ký gửi `outcome` `blocked`
  với `blocked_reason` `recipient_cap` và tin tới người thứ 200 vẫn gửi, như CP18 của spec và ADR-0124 (Accepted)
  quyết 1 sau V4.11 (F:ADR-0124 (Accepted)\~compliance-pdpl:R3.8).
- 2026-10-25 (agent): lượt h, theo V4.30 của Đạt (mục 7): nhật ký gửi ghi một dòng `dispatching` trước khi gửi, commit
  riêng trước bước giành lượt, và trần tần suất đếm cả lần gửi còn dở hay chưa biết kết quả (bước 2; spec R3.9-R3.11,
  CP24); `outcome` CHECK thành (`dispatching`, `blocked`), vì bảng chỉ thêm và kết quả giao nhận nằm ở
  `platform.tool_executions`. Theo H-3: bước 3 đăng ký `MarketingSendPolicy` vào sổ bước của tools-and-skills/01 (spec
  R3.12, CP25). Theo H-1 và bảng cạnh của lượt: thời hạn của hai bảng là hai mảnh dưới `configs/policies/retention.d/`,
  nên gỡ Blocked by workflow-triggers/02 (chỉ vì chuỗi tệp) và telemetry-and-audit/03, thêm telemetry-and-audit/01
  (định dạng mảnh, bộ nạp, hàm đọc hạn). Theo H-29 (V4.39): `purpose` của Bản ghi đồng ý chỉ còn `marketing` ở W1.
- 2026-10-29 (agent, tạm theo ủy quyền): lõi sàn (ba bảng, `MarketingSendPolicy`, `SendAdmissionPort` trong executor, route hủy nhận, R3.1-R3.4, R3.6-R3.11, R5.6) tách sang ticket 08, làm trước theo hàng đợi phiên không người trực; ticket này còn R3.5, R3.12, đối tượng Đồng ý và mảnh copy, và mở rộng bảng của ticket 08 chứ không tạo lại. Không thêm 08 vào Blocked by vì phụ thuộc chỉ trỏ ngược; cảnh báo collision giữa 04 và 08 là có chủ ý.
- 2026-10-29 (agent, tạm theo ủy quyền): sau khi tách ticket 08, phần còn làm ở ticket này là R3.5 (overlay chỉ siết), R3.12 (bước trong sổ bước của tools-and-skills/01), R5.1 và R5.5 cho phần nó chạm; các tiêu chí R3 khác đã được ticket 08 chứng minh và ở đây chỉ chạy lại khi phần mở rộng chạm chúng; đối tượng Đồng ý của gói và mảnh copy; bước 1, 2, 5, 6 ở trên đã thay bằng quyết định của ticket 08 (khung giờ cố định `Asia/Ho_Chi_Minh`, phát lại vẫn kiểm chặn gửi và đồng ý, `GET` trang và `POST` hành động, xóa qua `platform.purge_tenant_marketing`, ghi trong giao dịch của policy) và không được làm theo chữ cũ; đọc ticket 08 trước.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (người dựng và ranh giới). CRITICAL 1:
  R3.5 đòi một overlay công ty cho Sàn gửi tin ở W1, mà ADR-0110 (Accepted) quyết 3 chỉ cho kind `binding_set` ở W1,
  kind `policy` ở W2, và bác `platform.policy_overrides` (hai chủ một sự thật); ticket không có kho, route, quyền, audit
  hay test âm chéo tenant cho overlay. Sửa: R3.5 và CP11 sang W2 cùng kind `policy` (dòng mới của Ngoài phạm vi của
  spec, mang luật so theo từng trường, giá trị chặt nhất đọc ở mỗi lần nhận, gỡ overlay là nới); ở W1 sàn là số của
  nền tảng, công ty không đổi được, nên không có đường nới nào. Nếu sai thì: một kind `policy` chỉ siết, một người
  duyệt kèm audit, thêm vào ADR-0110 (Accepted) trước, rồi R3.5 về W1 ở ticket này.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 1: "đối tượng Đồng ý của gói qua RecordService" không có bước,
  tiêu chí, kiểm soát hay bên đọc (marketing-pilot ghi đồng ý ở cửa nhận Data Hub, workflow-triggers:R5.14, và không đọc
  object nào); sửa: sang W2 với bảo mật trường (Ngoài phạm vi của spec), gỡ Blocked by custom-objects/03. Nếu sai thì:
  một view đọc toàn tenant qua RecordService với bảo mật trường và test âm chéo tenant, ticket chờ custom-objects/03.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 2: tiêu chí R5.1 (`enforced: true`) và R5.5 (hai dòng
  `STUDIO_EXCLUSIONS` qua `platform.purge_tenant_append_only`) trái với cái ticket 08 đã dựng (bước
  `platform.purge_tenant_marketing`, studio-skeleton:R4.5 cấm dòng ngoại lệ cho bảng đã có bước; hai mảnh
  `enforced: false`); sửa: bỏ khỏi ticket này, spec R5.5 và mục Dữ liệu dẫn bước đã dựng, việc bật hai mảnh ở ticket 06.
  Nếu sai thì: không có, đây là chép lại cái đã dựng.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 3: R3.12 (đăng ký bước) đã dựng ở ticket 08, và ticket không nói
  có gỡ lời gọi sàn trực tiếp của ticket 08 hay không (sàn chạy hai lần); đã có câu trả lời: chỉ có một bước
  `send_floor` trong sổ (`wflite_host.py:121`), dấu gửi tin là khối `message` (tools-and-skills:R3.1); sửa: ticket
  chứng minh sổ ở cả hai root và viết đột biến (bước 2, 3). Nếu sai thì: không có.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 4: luật so "lỏng hơn" của overlay (cặp tần suất, khung giờ, giá trị
  hiệu lực khi sàn nền tảng siết sau) không định nghĩa; sửa: ghi trong dòng W2 của Ngoài phạm vi cùng R3.5. Nếu sai
  thì: đổi luật so ở dòng đó trước khi W2 cắt ticket.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận của gate (không CRITICAL mới, 1 HIGH, đã sửa): khi root
  thiếu bí mật ký ở profile không triển khai, sàn là `None` và mọi tin bị từ chối `blocked:send_floor_unavailable`, đã
  có ở `wflite_host.py:89-100` và `executor.py:739`; ticket thêm tiêu chí giữ điều đó, test root chạy với
  `MarketingSendPolicy` thật trên PostgreSQL, khẳng định sàn chạy một lần, và đột biến cho cả root của worker. Nếu sai
  thì: không có, đây là chép lại hành vi đã dựng.
- 2026-11-04 (agent): MEDIUM, để người dựng và `checking-plan-consistency`: (a) cảnh báo va chạm 04 với 08 của
  `check_plans` là có chủ ý (04 xây trên 08 đã resolved); đánh số lại khi cắt lại lượt ticket; (b) bộ gộp danh mục
  nhãn audit của telemetry-and-audit:R1.6 chưa có trong mã (không bộ nạp nào đọc `configs/copy/audit_actions.d/`),
  nên nhãn của bước 4 có bên đọc khi bộ gộp có; (c) hai lời gọi đồng thời tới người nhận thứ 200 và 201 của cùng lượt
  gốc chưa có test (khóa tư vấn theo `root_run_id` của ticket 08 bước 4).
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
