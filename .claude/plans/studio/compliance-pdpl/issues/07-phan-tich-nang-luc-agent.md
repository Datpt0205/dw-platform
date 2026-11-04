# 07 — Phân tích năng lực của agent: luật tự chủ và móc của loại agent

Status: ready-for-agent
Blocked by: 05, .claude/plans/studio/agent-builder/issues/03-runtime-agent.md, .claude/plans/studio/agent-builder/issues/05-gioi-han-du-lieu-cua-agent.md
Area: studio
Yêu cầu: R2.4, R2.6, R4.3, R4.4, R4.5, R4.6, CP4, CP6, CP13, CP14, CP15

## Mục tiêu

Khi gửi kiểm định một phiên bản agent, cùng module `capability_analysis` của ticket 05 đọc nhãn năng lực của các công
cụ trong Bộ công cụ và giới hạn dữ liệu của agent; một agent mang cả ba nhãn phải tự chủ ≤ A2, công cụ thiếu phân loại
bị từ chối, và kết quả ghi vào `studio.version_assessments` như với quy trình (spec R4.3-R4.6; ADR-0125 (Accepted)).
Ticket thêm mục `autonomy` mà luật đó đọc vào `dw.agent/v1` và cho cửa nhận lượt của agent đọc nó, vì trước đó tài liệu
agent không khai Mức tự chủ nào (ADR-0117 (Accepted) Amendments 2026-11-04).
Ticket tách từ bước 3 của ticket 05 (V4.31), để phân tích của quy trình không chờ loại `agent`.

## Việc cần làm

1. Mức tự chủ khai của agent (spec R4.3; ADR-0125 (Accepted) quyết 3; ADR-0117 (Accepted) Amendments 2026-11-04):
   `dw.agent/v1` của agent-builder/02 không có mục nào mang Mức tự chủ, nên ticket này thêm mục `autonomy` (một giá
   trị của `dw_kernel.autonomy`, A0-A4, không mặc định, không bắt buộc) vào lược đồ `extra="forbid"` của tài liệu,
   và cửa nhận lượt của agent (agent-builder/03) đặt `RunContext.autonomy_level` bằng mức thấp hơn giữa `autonomy` của
   phiên bản đã ghim và `RunContext.autonomy_ceiling`, tức `platform.tenants.max_autonomy_level` mà `AccessContext` mang
   vào (`contracts.py:152-157`, một chủ), như runner làm với worker (`contracts.py:164-169`); vắng
   `autonomy` → `autonomy_level` để `None`, mà chính sách duyệt đọc là hỏi mọi thứ (`contracts.py:167-168`), nên
   một phiên bản niêm phong trước ticket này chạy đóng. Thang ở `autonomy.py:14-33` vẫn là bên đọc runtime duy nhất;
   không có kẹp ẩn nào.
2. Móc phân tích của loại `agent`: đăng ký `capability_analysis` vào bảng kiểm theo loại lúc gửi kiểm định của
   agent-lifecycle/03 cho loại `agent` (agent-lifecycle:R2.7), bên cạnh mục của loại `workflow` mà ticket 05 đăng ký;
   module đọc tài liệu agent và bao đóng ghim lúc gửi kiểm định. Nhãn ở W1:
    - mỗi công cụ của Bộ công cụ đã ghim theo luật `tool.call` của ticket 05 bước 1 (ba phân loại của phiên bản công
      cụ; thiếu một phân loại → 422 `tool_unclassified`; công cụ loại lạ mang cả ba nhãn, spec R4.1);
    - `private_data` khi giới hạn dữ liệu mà phép dẫn của agent-builder/05 trả với cùng phiên bản chạm một đối tượng có
      trường `pd_category` khác `none` mà `field_caps` còn để đọc được; `field_caps` che hết các trường đó → không B.
      Với công cụ dữ liệu đối tượng (những công cụ mà phép dẫn đọc), B chỉ đến từ luật giới hạn này, không từ
      `data_classification` của công cụ, vì giới hạn cộng `field_caps` là sự thật hẹp hơn mà runtime thi hành; mọi công
      cụ khác theo luật `tool.call`;
    - các mục `knowledge`, `links`, `sub_agents`, công cụ quy trình và kênh chat mở cho người ngoài là W2
      (agent-builder spec, Ngoài phạm vi), nên không mang nhãn ở W1; ticket thêm mục nào trong số đó thêm nhãn của nó
      (`knowledge` và kênh mở là A; agent liên kết và công cụ quy trình mang nhãn ở dòng đánh giá đã ghim của chúng, như
      ticket 05 bước 8). `audience` ở `studio.agent_settings` không tạo phiên bản, nên không là đầu vào của phân tích; ở
      W1 nó chỉ gồm thành viên.
3. Quy tắc agent (spec R4.3, R4.5): mang cả ba nhãn và `autonomy` khai trên A2 → 422 `capability_trifecta_autonomy`
   kèm hai cách sửa (hạ tự chủ, hoặc tách phần đọc nội dung không tin cậy khỏi phần giữ tác động), kể cả khi mọi công cụ
   `external` đều `approval_policy: always`, vì luật của ADR-0125 (Accepted) quyết 3 là Mức tự chủ khai; vắng `autonomy`
   → qua (chạy hỏi mọi thứ). "Overlay công ty" của R4.5 ở W1 là bản của chính công ty cho một agent của gói, đi qua cùng
   cửa gửi kiểm định; `max_autonomy_level` của công ty chỉ hạ được.
4. Lộ trình (spec R2.4, phần agent, và R2.6 cho loại `agent`; ticket 03 giữ phần workspace, ticket 05 phần quy trình):
   lớp lúc gửi kiểm định như ticket 05 bước 5; lớp khác `vn_only`, agent mang B và một tuyến bất kỳ của hồ sơ model
   (`model.profile`, tuyến chính hay dự phòng) khai `data_location` khác `vn` hay không khai → 422 `residency_refused`
   (MP7; ADR-0123 (Accepted) Consequences). trong cùng móc, `route_class` mà
   `dw.agent/v1` khai (agent-builder:R1.6) lỏng hơn `platform.tenants.data_route_class` của công ty lúc gửi kiểm định,
   theo thứ tự của `effective_route_class` của ticket 03 → 422 `validation_failed` với `errors[].code`
   `route_class_looser_than_tenant`, con trỏ `/route_class`, phiên bản vẫn Nháp; vắng `route_class` hay bằng hay chặt
   hơn công ty → qua; lưu bản Nháp không kiểm điều này (bản Nháp không đổi lộ trình của lượt nào). Thân 422: một lỗi mỗi
   lần gửi, theo thứ tự `validation_failed`, `tool_unclassified`, `residency_refused`, `capability_trifecta_autonomy`;
   `capability_trifecta_autonomy` mang `details.remedies` (`lower_autonomy`, `split_untrusted_reader`) và
   `details.tools` (công cụ sinh mỗi nhãn).
5. Kết quả ghi một dòng `studio.version_assessments` (bảng của ticket 05) cho Mã băm định nghĩa của phiên bản agent
   trong giao dịch gửi kiểm định, cùng cột như dòng của quy trình (spec R4.6): tín hiệu là nhãn của từng công cụ và của
   giới hạn dữ liệu, kết luận, phiên bản bộ phân tích; lần gửi bị 422 không để lại dòng. Dòng có hai tầng: nhãn từng
   công cụ ở chi tiết của tín hiệu, và tập nhãn của cả dòng, tầng duy nhất mà `VersionAssessmentLookup` của ticket 05 đọc
   và lấy hợp cho Bước `ai.agent`. Tập nhãn của dòng mang `external_effect` chỉ khi có một công cụ `external` hay
   `critical` mà chính sách duyệt có một chủ (`AutonomyApprovalPolicy.requires_approval` của
   `packages/python/dw_agent_runtime/src/dw_agent_runtime/autonomy.py`, với `autonomy` đã khai) trả "không hỏi", vì một
   Bước `ai.agent` mang nhãn của agent và tác động của nó chỉ tính là đã gác khi luôn hỏi (ADR-0125 (Accepted) quyết 2);
   không viết lại luật thang ở đây. Phiên bản bộ phân tích tính theo loại (`workflow`, `agent`), nên ticket này không
   làm cũ dòng của quy trình.
6. Case trong bộ eval bảo mật: agent Marketing có công cụ gửi tin, đọc lead và nhận nội dung từ web ở A3.

## Tiêu chí chấp nhận

- [ ] R4.3 (CP13): agent có cả ba nhãn ở A3 → 422 `capability_trifecta_autonomy` kèm hai cách sửa; cùng agent ở A2 →
      gửi kiểm định được; cùng agent không khai `autonomy` → gửi kiểm định được và lượt của nó chạy với
      `autonomy_level` `None`, công cụ gửi tin hỏi người; gỡ kiểm → test đỏ.
- [ ] R4.3 (CP13): agent khai A3, công ty `max_autonomy_level` A1 → lượt chạy với `autonomy_level` A1; cửa nhận lượt bỏ
      qua `autonomy` của phiên bản → test đỏ.
- [ ] R4.3 (CP13): giới hạn dữ liệu chạm đối tượng có trường `basic` mà `field_caps` để đọc → B; `field_caps` che trường
      đó → không B, agent A3 với công cụ đọc web và gửi tin qua được.
- [ ] R4.4 (CP14): Bộ công cụ của agent có một công cụ thiếu một trong ba phân loại → 422 `tool_unclassified`; gỡ kiểm
      → test đỏ.
- [ ] R4.5 (CP15): bản của công ty cho một agent bộ ba của gói nâng `autonomy` lên A3 → gửi kiểm định 422
      `capability_trifecta_autonomy`, phiên bản vẫn Nháp.
- [ ] R4.6: gửi kiểm định một agent hợp lệ → đúng một dòng `studio.version_assessments` cho Mã băm định nghĩa của
      phiên bản, ghi trong cùng giao dịch; rollback giao dịch gửi kiểm định → không dòng nào; bỏ mục `agent` khỏi bảng
      kiểm theo loại → gửi kiểm định agent A3 bộ ba qua được, test đỏ; agent có một công cụ `external` mà chính sách duyệt
      ở mức đã khai trả "không hỏi" → tập nhãn của dòng mang `external_effect`; cùng công cụ ở mức mà chính sách trả
      "hỏi" → không mang; luật C viết lại thay cho lời gọi chính sách → ca thứ hai đỏ.
- [ ] R2.4 (CP4): công ty `vn_only`, agent khai `route_class: cross_border_full` → gửi kiểm định 422
      `route_class_looser_than_tenant` ở `/route_class`, phiên bản vẫn Nháp; khai `vn_only` hay không khai → qua; gỡ
      kiểm → test đỏ.
- [ ] R2.6 (CP6): công ty `cross_border_full`, agent mang B, hồ sơ model có tuyến dự phòng `foreign` → gửi kiểm định
      422 `residency_refused`; hồ sơ chỉ có tuyến `vn` → qua; gỡ kiểm → test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/autonomy.py:14-33`; spec: R4.3 (thang tự chủ, hai sàn
  `critical` và `approval_policy: always`).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:152-169`; spec: R4.3 (trần của công ty, mức của
  lượt, `None` là hỏi mọi thứ).
- `docs/adr/0117-agents-are-form-configured-documents.md:56-61`; spec: R4.3 (các mục của `dw.agent/v1`, không có mục tự
  chủ trước Amendments 2026-11-04).
- ADR-0125 (Accepted) quyết 1, 2, 3, 5; agent-lifecycle:R2.7; spec: R4.3-R4.6.

## Comments

- 2026-10-25 (agent): ticket mới theo V4.31 của Đạt (lượt h), số và đường dẫn theo bảng ticket mới của lượt: luật agent
  (bước 3 cũ của ticket 05) và móc phân tích của loại `agent`; Blocked by 05 và agent-builder/05 theo bảng cạnh của
  lượt, thay cạnh 05 <- agent-builder/02.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (chỉ người dựng: ticket không thêm
  migration hay route; mục mới của lược đồ là JSON trong vỏ phiên bản). CRITICAL 1: R4.3 đọc "Mức tự chủ khai" của
  agent, mà `dw.agent/v1` (ADR-0117 (Accepted) quyết 2, agent-builder/02) không có mục nào như vậy, và lượt của agent
  Studio không có mức khai nào (`contracts.py:164-169`): luật đọc một trường không ai khai (`failure-modes.md` #1), trái
  ADR-0125 (Accepted) quyết 3. Sửa: mục `autonomy` không bắt buộc trong `dw.agent/v1`, cửa nhận lượt đặt mức thấp hơn
  giữa nó và trần của công ty, vắng thì hỏi mọi thứ (bước 1), ghi ở ADR-0117 (Accepted) Amendments 2026-11-04 và một
  dòng Quyết định của spec agent-builder; ticket chờ agent-builder/03 vì sửa cửa nhận lượt của nó. Nếu sai thì:
  agent-builder giữ mục và cửa (một ticket của nó), ticket này chỉ đọc; hay agent Studio ở W1 luôn chạy `None` và R4.3
  sang W2 cùng mục tự chủ.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 1: tín hiệu của agent ngoài công cụ (`knowledge`, kênh mở, trí
  nhớ, agent liên kết, công cụ quy trình) không nói; sửa: ở W1 các mục đó là W2 nên không mang nhãn, `audience` ở cài
  đặt không là đầu vào (bước 2). Nếu sai thì: đọc `audience` lúc gửi kiểm định và phân tích lại khi nó đổi.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 2: nhãn công cụ theo loại hay theo phân loại; sửa: theo luật
  `tool.call` của ticket 05 bước 1 (ba phân loại của phiên bản đã ghim). Nếu sai thì: theo bảng loại công cụ.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 3: `private_data` từ giới hạn dữ liệu bật khi nào; sửa: khi giới
  hạn chạm trường `pd_category` khác `none` mà `field_caps` để đọc (bước 2). Nếu sai thì: mọi đối tượng có trường cá
  nhân trong giới hạn, dù `field_caps` che.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): HIGH 4: agent A3 mà mọi công cụ `external` đều `approval_policy:
always` có bị chặn không, và dòng của agent ghi C ra sao cho Bước `ai.agent` của ticket 05; sửa: vẫn 422 theo Mức tự
  chủ khai (ADR-0125 (Accepted) quyết 3); dòng chỉ ghi C khi có tác động có thể chạy không hỏi (quyết 2), bước 3, 5.
  Nếu sai thì: miễn luật cho agent mà mọi tác động luôn hỏi, và dòng ghi C như hợp nhãn.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận của gate (không CRITICAL mới, 4 HIGH, đã sửa): nhãn C của
  dòng gọi chính sách duyệt có một chủ, không viết lại thang; B của công cụ dữ liệu đối tượng chỉ từ giới hạn và
  `field_caps`; R2.6 cho loại `agent` (MP7), thêm R2.6, CP6 vào Yêu cầu; tập nhãn của dòng là tầng duy nhất mà lookup
  đọc. Thêm: trần là `RunContext.autonomy_ceiling`, phiên bản bộ phân tích theo loại, thân 422 có `remedies` và
  `tools`. Nếu sai thì: từng mục quay về bản trước trong lịch sử git.
- 2026-11-04 (agent): MEDIUM, để người dựng: (a) case eval của bước 6 chưa có grader riêng, chạy ở eval smoke; (b) một
  phiên bản niêm phong trước ticket này không có `autonomy` và chạy hỏi mọi thứ, đúng ý; (c) khi `knowledge`,
  `links`, `sub_agents` vào ở W2, ticket thêm chúng phải thêm nhãn và test như bước 2; (d) công cụ MCP mang A theo
  ADR-0125 (Accepted) quyết 1 khi nó có ở W2; (e) `delegation.ask_before` là W2, khi có thì tính là "luôn hỏi" ở bước 5;
  (f) agent bộ ba khai A3 ở công ty có trần A1 vẫn 422, vì luật đọc mức khai, không mức chạy thật.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
