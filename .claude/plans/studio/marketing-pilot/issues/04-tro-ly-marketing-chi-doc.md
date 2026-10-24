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
4. Bộ công cụ không chứa công cụ gửi tin hay công cụ ghi bản ghi: đó là thiết kế của gói (Luật Hai, ADR-0125 (Accepted) quyết 5), không phải sàn. Sàn của nền tảng chỉ từ chối lúc gửi kiểm định một trợ lý mang cả ba nhãn khai tự chủ trên A2 (compliance-pdpl:R4.3), nên test của R5.4 khai A3. Dùng `.claude/plans/studio/agent-lifecycle/issues/04-cong-kiem-dinh-va-duyet-hai-nguoi.md`.
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
