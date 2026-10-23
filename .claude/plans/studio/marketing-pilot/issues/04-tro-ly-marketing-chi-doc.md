# 04 — Agent Marketing chỉ đọc

Status: needs-triage
Blocked by: 02, .claude/plans/studio/agent-builder/issues/04-chat-va-man-chat.md, .claude/plans/studio/tools-and-skills/issues/03-cong-cu-du-lieu-doi-tuong.md, .claude/plans/studio/field-security/issues/02-ap-o-moi-duong.md, .claude/plans/studio/agent-lifecycle/issues/04-cong-kiem-dinh-va-duyet-hai-nguoi.md
Area: studio
Yêu cầu: R5.1, R5.2, R5.3, R5.4

## Mục tiêu

Người dùng Marketing có một trợ lý trả lời câu hỏi về lead, chiến dịch và tương tác đúng theo quyền của mình bằng công cụ đọc, không bao giờ gửi tin hay sửa bản ghi (marketing-pilot R5.1, R5.2, R5.3, R5.4). Từ B12-product marketing-pilot 12 (phần không khởi động quy trình). Chứng minh MP5 và MP6 trên trợ lý.

## Việc cần làm

1. Agent `dw.agent/v1` "Trợ lý Marketing" dựng qua `POST /api/v1/studio/agents` của công ty demo, với bộ công cụ chỉ chứa công cụ đọc dữ liệu đối tượng `obj.mkt_lead.search`, `obj.mkt_lead.get`, `obj.mkt_campaign.search`, `obj.mkt_campaign.get`. Dùng `.claude/plans/studio/tools-and-skills/issues/03-cong-cu-du-lieu-doi-tuong.md`.
2. `Người được dùng` của agent gồm vai Marketing và Sales của công ty demo; mặc định đóng (không khớp thì không thấy agent), không fail-open (agent-builder:R5.1).
3. Phiên công cụ của lượt chạy agent chạy với quyền của người hỏi giao với giới hạn dữ liệu của phiên bản; quyền bản ghi và quyền trường áp ở đường agent và kết quả tìm kiếm (agent-builder:R3.4; record-access:R3.1). Dùng `.claude/plans/studio/field-security/issues/02-ap-o-moi-duong.md`.
4. Bộ công cụ không chứa công cụ gửi tin hay công cụ ghi bản ghi; phân tích năng lực lúc phát hành từ chối phiên bản nếu có một công cụ như vậy (agent-lifecycle:R6.1, R6.2). Dùng `.claude/plans/studio/agent-lifecycle/issues/04-cong-kiem-dinh-va-duyet-hai-nguoi.md`.
5. Qua cổng an ninh nền tảng 100% và một người không phải Tác giả duyệt mới lên Đang dùng; dùng màn chat của `.claude/plans/studio/agent-builder/issues/04-chat-va-man-chat.md`.

## Tiêu chí chấp nhận

- [ ] R5.1: một nhân viên Sales hỏi "lead nào đang Nóng" → trợ lý trả lời chỉ gồm lead người đó được đọc; một lead ngoài tầm không xuất hiện; trưởng nhóm thấy cả cây; Marketing thấy lead của workspace Marketing.
- [ ] R5.2: một người giữ vai Cộng tác viên Marketing hỏi về một lead → câu trả lời hiện "Đã ẩn" thay cho `phone_e164` và `email`; API không trả hai trường đó; lọc theo `phone_e164` trả 422; xuất không có cột đó.
- [ ] R5.3: bộ công cụ của trợ lý chỉ gồm bốn công cụ đọc, không công cụ gửi tin hay công cụ ghi bản ghi nào.
- [ ] R5.4: thêm một công cụ gửi tin vào nháp agent rồi gửi kiểm định → bộ kiểm phát hành trả 409 và không phát hành (công cụ gửi trên agent có đầu vào ngoài và dữ liệu riêng là Bộ ba nguy hiểm).
- [ ] Xong: `uv run pytest tests/e2e/marketing_pilot/test_marketing_assistant.py` xanh.

## Nguồn

- spec: R5.1, R5.2, R5.3, R5.4.
- agent-builder:R3.4, R5.1; agent-lifecycle:R6.1, R6.2; record-access:R3.1; custom-objects:R3.2; field-security và tools-and-skills (đang viết đợt này); YC96; ADR-0125 (Proposed).

## Comments
