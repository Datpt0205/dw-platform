# 04 — Agent Marketing chỉ đọc

Status: needs-triage
Blocked by: 02, .claude/plans/studio/agent-builder/issues/04-chat-va-man-chat.md, .claude/plans/studio/tools-and-skills/issues/03-cong-cu-du-lieu-doi-tuong.md, .claude/plans/studio/field-security/issues/02-ap-o-moi-duong.md, .claude/plans/studio/agent-lifecycle/issues/06-cong-chat-luong-va-ca-kich-ban.md, .claude/plans/studio/agent-builder/issues/05-gioi-han-du-lieu-cua-agent.md
Area: studio
Yêu cầu: R5.1, R5.2, R5.3, R5.4

## Mục tiêu

Người dùng Marketing có một trợ lý trả lời câu hỏi về lead và chiến dịch đúng theo quyền của mình bằng công cụ đọc, không bao giờ gửi tin hay sửa bản ghi (marketing-pilot R5.1, R5.2, R5.3, R5.4). Từ B12-product marketing-pilot 12 (phần không khởi động quy trình). Chứng minh MP5 và MP6 trên trợ lý.

## Việc cần làm

1. Agent `dw.agent/v1` "Trợ lý Marketing" dựng qua `POST /api/v1/studio/artifacts` (`kind: agent`) cùng `POST /api/v1/studio/agents/{id}/settings` của công ty demo (agent-builder:R1.1), với bộ công cụ chỉ chứa bốn công cụ đọc dữ liệu đối tượng, ghim theo tên mà tools-and-skills sinh từ đối tượng (tools-and-skills:R6.1; ADR-0116 (Accepted) quyết 5): `obj_mkt_lead__search`, `obj_mkt_lead__get`, `obj_mkt_campaign__search`, `obj_mkt_campaign__get`. Dùng `.claude/plans/studio/tools-and-skills/issues/03-cong-cu-du-lieu-doi-tuong.md`.
2. `Người được dùng` của agent gồm vai Marketing và Sales của công ty demo; mặc định đóng (không khớp thì không thấy agent), không fail-open (agent-builder:R5.1).
3. Phiên công cụ của lượt chạy agent chạy với quyền của người hỏi giao với giới hạn dữ liệu của phiên bản; quyền bản ghi và quyền trường áp ở đường agent và kết quả tìm kiếm (agent-builder:R3.4; record-access:R3.1). Giới hạn dữ liệu của phiên bản dẫn từ bộ công cụ lúc phát hành, và của lượt mô phỏng lúc nhận lượt. Dùng `.claude/plans/studio/field-security/issues/02-ap-o-moi-duong.md` và `.claude/plans/studio/agent-builder/issues/05-gioi-han-du-lieu-cua-agent.md`.
4. Bộ công cụ không chứa công cụ gửi tin hay công cụ ghi bản ghi: đó là thiết kế của gói (Luật Hai, ADR-0125 (Accepted) quyết 5), không phải sàn. Sàn của nền tảng chỉ từ chối lúc gửi kiểm định một trợ lý mang cả ba nhãn khai tự chủ trên A2 (compliance-pdpl:R4.3), nên test của R5.4 khai A3. Ca R5.4 tạo Nháp khi trợ lý không có Nháp hay Bản ứng viên nào (sau khi bản chỉ đọc lên Đang dùng), khai A3 rồi A2 trên chính bản Nháp đó, và sau lần khai A2 qua sàn thì Rút lại Bản ứng viên đó về Nháp bằng lệnh Rút lại của agent-lifecycle (agent-lifecycle:R2.4), để trợ lý không giữ một Bản ứng viên mang công cụ gửi; ca sau sửa tiếp bản Nháp đó thay vì tạo Nháp mới, vì tạo Nháp trả 409 `conflict` với `candidate_pending` khi có Bản ứng viên và `draft_exists` khi đã có Nháp (V4.17; tenant-config:R2.22, tenant-config:R2.23). Dùng `.claude/plans/studio/agent-lifecycle/issues/04-cong-kiem-dinh-va-duyet-hai-nguoi.md` cho lệnh Rút lại và phê duyệt phát hành.
5. Qua cổng an ninh nền tảng 100% (`.claude/plans/studio/agent-lifecycle/issues/06-cong-chat-luong-va-ca-kich-ban.md`) và một người không phải Tác giả duyệt mới lên Đang dùng; ticket này chạy trên profile `test` như lối ra W1a, còn trợ lý trên uat là của ticket 06; dùng màn chat của `.claude/plans/studio/agent-builder/issues/04-chat-va-man-chat.md`.

## Tiêu chí chấp nhận

- [ ] R5.1: một nhân viên Sales ở mức Của tôi hỏi "lead nào đang Nóng" → trợ lý trả lời chỉ gồm lead người đó phụ trách; một lead ngoài tầm không xuất hiện; trưởng Marketing ở mức Workspace của tôi thấy mọi lead của workspace Marketing và không lead nào của workspace Sales.
- [ ] R5.2: một người giữ vai Cộng tác viên Marketing hỏi về một lead → câu trả lời hiện "Đã ẩn" thay cho `phone_e164` và `email`; API không trả hai trường đó; lọc theo `phone_e164` trả 422.
- [ ] R5.3: bộ công cụ của trợ lý chỉ gồm `obj_mkt_lead__search`, `obj_mkt_lead__get`, `obj_mkt_campaign__search`, `obj_mkt_campaign__get`, mỗi tên khớp một công cụ mà tools-and-skills đã sinh từ đối tượng, không công cụ gửi tin hay công cụ ghi bản ghi nào.
- [ ] R5.4: thêm một công cụ gửi tin vào nháp trợ lý, khai Mức tự chủ A3, rồi gửi kiểm định → 422 `capability_trifecta_autonomy`, phiên bản vẫn Nháp (công cụ gửi trên agent có đầu vào ngoài và dữ liệu riêng là Bộ ba nguy hiểm); khai A2 → qua sàn.
- [ ] Xong: `uv run pytest tests/e2e/marketing_pilot/test_marketing_assistant.py` xanh.

## Nguồn

- spec: R5.1, R5.2, R5.3, R5.4.
- agent-builder:R3.4, R5.1; compliance-pdpl:R4.3; record-access:R3.1; custom-objects:R3.2; field-security và tools-and-skills (đang viết đợt này); YC96; ADR-0125 (Accepted).

## Comments

- 2026-10-23 (agent): áp B:agent-lifecycle:R6.1~compliance-pdpl:R4.2 (a) (Đạt, 23/10/2026): từ chối lúc gửi kiểm định với 422 thay 409; R5.4 chỉ đỏ khi trợ lý khai tự chủ trên A2, vì bộ công cụ chỉ đọc là Luật Hai của gói.
- 2026-10-24 (agent): áp quyết định của Đạt ngày 24/10/2026: tên công cụ theo tools-and-skills:R6.1 (B:marketing-pilot/04\~tools-and-skills:R6.1); R5.1 ở mức W1, "cả cây" sang W2 (H:marketing-pilot:R5.1\~record-access:ngoài-phạm-vi); bỏ vế xuất khỏi R5.2 vì xuất CSV là W2 (H:custom-objects:ngoài-phạm-vi\~marketing-pilot:R5.2); câu hỏi về Tương tác là W2 cùng `mkt_touchpoint` (N4).
- 2026-10-24 (agent): lượt f của vòng 4, theo V4.17 của Đạt (dòng cùng ngày của spec): mỗi thành phần có tối đa một bản chưa phát hành, nên bước 4 dựng Nháp của R5.4 khi trợ lý không có Bản ứng viên đang chờ và Rút lại bản khai A2 sau khi nó qua sàn; tiêu chí không đổi.
- 2026-10-24 (agent): kiểm lượt f của vòng 4: bước 4 tạo Nháp của R5.4 chỉ khi trợ lý không có Nháp hay Bản ứng viên, và ca sau sửa tiếp bản Nháp mà lệnh Rút lại để lại, vì tạo Nháp lúc đã có Nháp trả 409 `draft_exists` (tenant-config:R2.23), nên câu "lần dựng Nháp sau không gặp 409" bỏ; tiêu chí không đổi.
- 2026-10-25 (agent): lượt h, theo V4.31 của Đạt: Blocked by gỡ agent-lifecycle/04, thêm agent-lifecycle/06 (Cổng chất lượng, nay tách khỏi phát hành hai người) và agent-builder/05 (giới hạn dữ liệu của agent, tách khỏi agent-builder/02) theo bảng cạnh của lượt h; agent-lifecycle/04 vẫn là tổ tiên qua agent-lifecycle/06. Ticket này thuộc lối ra W1b: ticket 05 (W1a) không chờ nó, ticket 06 chờ nó. Tiêu chí không đổi.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness trên `cb5e9a4` (builder check; không route, không
  migration): CẦN XEM, ticket ở lại `needs-triage`. Trường hợp: dựng trên trợ lý chat riêng đã bỏ. Ticket này là một
  trợ lý hỏi đáp có `Người được dùng` và màn chat của agent-builder/04, tức "trợ lý chat hỏi đáp như một sản phẩm" mà
  D15 của Đạt không làm (`requirements.md`, 29/10/2026, Không làm); D17 đọc YC96 lại là kênh chat vào Digital Worker
  chăm sóc lead (studio.md, Chờ Đạt 12), và agent-builder/04, chỗ dựa của bước 5, cũng CẦN XEM vì cùng lý do
  (`e35a917`). Khuyến nghị theo ủy quyền: viết lại R5 của spec và ticket này qua `writing-plan-specs` cùng lần viết lại
  agent-builder/04, khi `requirements.md` sửa theo D15: trợ lý là kênh chat của Digital Worker chăm sóc lead (hỏi về
  lead, việc trong hàng đợi và scorecard của DW đó, theo quyền người hỏi), không agent riêng. Giữ bước 1 của `cb5e9a4`
  (agent dựng qua `POST /api/v1/studio/artifacts` và route cài đặt) nếu kênh vẫn là một agent Studio. Bản viết lại phải
  mang các HIGH sau, mỗi dòng một khuyến nghị:
    - (1) Tín hiệu A của R5.4 chỉ có thể đến từ `output_trust` của công cụ đối tượng, vì `message` do người ngoài viết:
      công cụ `object_crud` khai `untrusted` cho trường đó, nếu không ca A3 không bao giờ thành Bộ ba và test không đỏ
      (ADR-0125 (Accepted) quyết 1); nói rõ hệ quả cho mọi agent dùng công cụ đối tượng.
    - (2) Ca R5.4 nêu công cụ gửi nào ghim được vào agent ở W1 (công cụ tenant là W2, `email.send` của lát là một Bước
      `tool.call`; công cụ gói `email.send@1.0.0` của leadcare là ứng viên).
    - (3) Cộng tác viên Marketing nằm ngoài `Người được dùng` (chỉ Marketing và Sales), nên vế trợ lý của R5.2 thành
      "không thấy agent": thêm vai đó vào audience, hay đổi người hỏi của ca.
    - (4) Cổng an ninh 100% cho một agent trên profile `test` với model giả: ca nào, chấm không gọi model ra sao, ai là
      người không phải Tác giả duyệt.
    - (5) R5.1, R5.2 khẳng định trên kết quả công cụ (`hidden_fields`, các dòng trả về), không trên văn bản của model;
      nói chữ "Đã ẩn" do màn chat dựng hay do model viết.
    - (6) Định danh trực tiếp (`name`, `phone_e164`, `email`, `message`) có vào ngữ cảnh model của trợ lý không khi
      người hỏi có quyền trường: R3.4 chỉ phủ `ai.llm`, và luật không ghi xuống của YC113 là W2.
    - (7) "Khai A2 → qua sàn" khẳng định gì (2xx của route gửi hay kết quả phân tích đã lưu), và Rút lại khi Bản ứng viên
      còn `evaluating` hay khi cổng tự trả về Nháp.
    - (8) Các HIGH của agent-builder/04 trong Comments của nó (`e35a917`): nội dung chat không vào hàng lượt chạy, khóa
      và audience ở cả hai route `POST`, workspace của hội thoại, `active_run_id`, `Idempotency-Key`, eval cho bề mặt chat.
      Đã trả lời ở lần gate ticket 03 (không còn là câu hỏi): Lead đã giao giữ workspace Marketing (record-access:R8.2), mức
      Của tôi của Sales với tới Lead mình phụ trách ở mọi workspace (record-access:R3.1). Nếu sai thì: Đạt giữ trợ lý riêng
      (YC96 nguyên nghĩa cũ), và ticket qua gate sau khi sửa (1)-(8).
