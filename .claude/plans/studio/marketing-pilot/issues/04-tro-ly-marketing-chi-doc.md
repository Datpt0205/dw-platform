# 04 — Agent Marketing chỉ đọc

Status: needs-triage
Blocked by: 02, .claude/plans/studio/agent-builder/issues/04-chat-va-man-chat.md, .claude/plans/studio/tools-and-skills/issues/03-cong-cu-du-lieu-doi-tuong.md, .claude/plans/studio/field-security/issues/02-ap-o-moi-duong.md, .claude/plans/studio/agent-lifecycle/issues/04-cong-kiem-dinh-va-duyet-hai-nguoi.md
Area: studio
Yêu cầu: R5.1, R5.2, R5.3, R5.4

## Mục tiêu

Người dùng Marketing có một trợ lý trả lời câu hỏi về lead và chiến dịch đúng theo quyền của mình bằng công cụ đọc, không bao giờ gửi tin hay sửa bản ghi (marketing-pilot R5.1, R5.2, R5.3, R5.4). Từ B12-product marketing-pilot 12 (phần không khởi động quy trình). Chứng minh MP5 và MP6 trên trợ lý.

## Việc cần làm

1. Agent `dw.agent/v1` "Trợ lý Marketing" dựng qua `POST /api/v1/studio/agents` của công ty demo, với bộ công cụ chỉ chứa bốn công cụ đọc dữ liệu đối tượng, ghim theo tên mà tools-and-skills sinh từ đối tượng (tools-and-skills:R6.1; ADR-0116 (Accepted) quyết 5): `obj_mkt_lead__search`, `obj_mkt_lead__get`, `obj_mkt_campaign__search`, `obj_mkt_campaign__get`. Dùng `.claude/plans/studio/tools-and-skills/issues/03-cong-cu-du-lieu-doi-tuong.md`.
2. `Người được dùng` của agent gồm vai Marketing và Sales của công ty demo; mặc định đóng (không khớp thì không thấy agent), không fail-open (agent-builder:R5.1).
3. Phiên công cụ của lượt chạy agent chạy với quyền của người hỏi giao với giới hạn dữ liệu của phiên bản; quyền bản ghi và quyền trường áp ở đường agent và kết quả tìm kiếm (agent-builder:R3.4; record-access:R3.1). Dùng `.claude/plans/studio/field-security/issues/02-ap-o-moi-duong.md`.
4. Bộ công cụ không chứa công cụ gửi tin hay công cụ ghi bản ghi: đó là thiết kế của gói (Luật Hai, ADR-0125 (Accepted) quyết 5), không phải sàn. Sàn của nền tảng chỉ từ chối lúc gửi kiểm định một trợ lý mang cả ba nhãn khai tự chủ trên A2 (compliance-pdpl:R4.3), nên test của R5.4 khai A3. Ca R5.4 tạo Nháp khi trợ lý không có Nháp hay Bản ứng viên nào (sau khi bản chỉ đọc lên Đang dùng), khai A3 rồi A2 trên chính bản Nháp đó, và sau lần khai A2 qua sàn thì Rút lại Bản ứng viên đó về Nháp bằng lệnh Rút lại của agent-lifecycle (agent-lifecycle:R2.4), để trợ lý không giữ một Bản ứng viên mang công cụ gửi; ca sau sửa tiếp bản Nháp đó thay vì tạo Nháp mới, vì tạo Nháp trả 409 `conflict` với `candidate_pending` khi có Bản ứng viên và `draft_exists` khi đã có Nháp (V4.17; tenant-config:R2.22, tenant-config:R2.23). Dùng `.claude/plans/studio/agent-lifecycle/issues/04-cong-kiem-dinh-va-duyet-hai-nguoi.md`.
5. Qua cổng an ninh nền tảng 100% và một người không phải Tác giả duyệt mới lên Đang dùng; dùng màn chat của `.claude/plans/studio/agent-builder/issues/04-chat-va-man-chat.md`.

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
