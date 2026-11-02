# 04 — Màn hình trợ lý và thẻ duyệt

Status: resolved (2026-11-02, main)
Blocked by: 03
Area: studio
Yêu cầu: R7.1, R7.2

## Mục tiêu

Chủ DW trò chuyện với trợ lý, xem kế hoạch, diff và lỗi, lưu, chạy mô phỏng và gửi duyệt trên web; người duyệt thấy diff và kết quả mô phỏng trên thẻ approval (R7).

## Việc cần làm

1. Client sinh từ OpenAPI cho các route của ticket 01-03 trong `@dw/api-client`.
2. `apps/web/app/digital-workers/[id]/assistant/page.tsx`: các lượt (chữ của người và câu hỏi hay kế hoạch của trợ lý), diff theo bước thêm, bỏ, đổi, đổi chỗ, lỗi `wf.*` bằng chữ tiếng Việt, cây đề xuất bằng `WorkflowTree`; nút "Lưu bản nháp" (tắt kèm lý do khi `publishable` sai), "Chạy mô phỏng", "Gửi duyệt" (tắt kèm lý do khi chưa mô phỏng đúng bản này).
3. Thẻ `dw.workflow.publish` trong bảng `CARDS` của `/approvals`: tên DW, diff, kết quả mô phỏng và các công cụ đã ghi; Duyệt và Từ chối kèm lý do.
4. Test vitest mỗi trang với API giả; xem bằng Playwright sáng và tối, desktop và dưới 992px theo mục Ủy quyền của `studio.md`, ảnh trong Comments.

## Tiêu chí chấp nhận

- [x] R7.1: trang trợ lý với API giả hiện một kế hoạch, một bước thêm trong diff và một lỗi `wf.hitl_gate_missing` bằng chữ; "Lưu bản nháp" tắt khi `publishable` sai, có lý do.
- [x] R7.2: thẻ `dw.workflow.publish` hiện diff và `passed` của mô phỏng; nút tắt khi `can_decide` sai.
- [x] Xong: `pnpm --filter @dw/web test` xanh.

## Nguồn

- `apps/web/app/approvals/page.tsx:44`; `apps/web/components/digital-workers/workflow-tree.tsx:13`; spec: R7.1, R7.2.

## Comments

- 2026-10-31 (agent): viết cùng spec.
- 2026-11-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-02 (agent): resolved.
    - Khác ticket (agent, theo ủy quyền 31/10/2026): thẻ cần diff và mô phỏng mà payload approval chỉ có định danh và hash, còn `GET .../workflow-draft` chỉ cho chủ DW (Validator thì 403), nên thêm `GET .../workflow-draft/review` cho Validator, Business Owner, Technical Owner (403 `not_dw_person` cho người khác, 404 cho tenant khác); trợ lý trả thêm `outline` dựng phía server. Ghi ở spec, mục API và Quyết định. Thẻ so `approval_id` và `content_sha256` của review với payload, báo khi bản nháp hay quy trình đang chạy đã đổi từ khi gửi. Trang DW có link "Sửa với trợ lý".
    - Mỗi lần bấm một `Idempotency-Key` (`lib/idempotency.ts`), giữ khi thử lại cùng nội dung, bỏ sau khi thành công. Nút tắt có lý do trong Tooltip và bằng chữ bên cạnh.
    - Test: vitest `wf-ai-screens.test.tsx` 8 ca (cả web 138 passed, tsc và lint sạch; sửa hai lỗi kiểu có sẵn ở `dw-screens.test.tsx`); unit `test_wflite_assistant.py` thêm hai ca (`outline`); integration `test_wf_ai_publish.py` thêm ca review (14 passed).
    - `mutations/04.yaml` 2 đột biến phía server, cùng 4 đột biến web làm bằng tay; chưa chạy. Ảnh Playwright sáng/tối × desktop/dưới 992px và độ trễ để lượt kiểm tra cuối (`wave-close.md` 2/11/2026).
    - `reviewing-feature-security` (đọc): route review chỉ đọc, kiểm người của DW phía server dưới tenant của người gọi (tenant khác 404, thành viên không phải người của DW 403); `tool_calls` của mô phỏng chỉ tới người của DW; nút bị tắt không thay cho phân quyền: gửi, rút, duyệt vẫn do server quyết (test ở ticket 03).
