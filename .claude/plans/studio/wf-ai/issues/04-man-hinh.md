# 04 — Màn hình trợ lý và thẻ duyệt

Status: needs-triage
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

- [ ] R7.1: trang trợ lý với API giả hiện một kế hoạch, một bước thêm trong diff và một lỗi `wf.hitl_gate_missing` bằng chữ; "Lưu bản nháp" tắt khi `publishable` sai, có lý do.
- [ ] R7.2: thẻ `dw.workflow.publish` hiện diff và `passed` của mô phỏng; nút tắt khi `can_decide` sai.
- [ ] Xong: `pnpm --filter @dw/web test` xanh.

## Nguồn

- `apps/web/app/approvals/page.tsx:44`; `apps/web/components/digital-workers/workflow-tree.tsx:13`; spec: R7.1, R7.2.

## Comments

- 2026-10-31 (agent): viết cùng spec.
