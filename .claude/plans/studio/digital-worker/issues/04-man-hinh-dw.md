# 04 — Màn hình Digital Worker, hàng đợi việc và thẻ duyệt

Status: needs-triage
Blocked by: 03
Area: studio
Yêu cầu: R9.1, R9.2, R9.3, R9.4, R9.5, DWK21

## Mục tiêu

Business Owner, Validator và người làm việc thấy DW, hàng đợi chung, gói bàn giao và thẻ duyệt trên
web, bằng Ant Design v6 (R9).

## Việc cần làm

1. Client sinh từ OpenAPI cho các route của ticket 01-03 và `trail` của wf-lite/02
   (`apps/web/lib/api`), không gõ tay kiểu.
2. `apps/web/app/digital-workers/page.tsx`: bảng antd (tên, trạng thái `Tag`, mandate rút gọn, số việc
   đang mở).
3. `apps/web/app/digital-workers/[id]/page.tsx`: `Descriptions` hồ sơ và bốn người, bảng loại quyết
   định (trần, đã kiếm, hiệu lực hiện bằng `Tag` "Tự động", "Hỏi" hay "Chặn" kèm mức A0-A4), `Statistic` của scorecard 30 ngày, cây quy trình chỉ đọc vẽ bằng
   antd (`Steps` dọc, lane của `logic.switch` và `human.approval` lồng trong `Card`) từ tài liệu đã ghim.
4. `apps/web/app/work/page.tsx`: hàng đợi chung, lọc trạng thái và loại người giữ, `Drawer` của một
   việc với `trail` và gói bàn giao.
5. `apps/web/app/approvals`: thẻ cho `dw.decision` (tên DW, loại quyết định, mức hiệu lực, đề xuất:
   tiêu đề và thân thư), với ba nút Duyệt, "Sửa rồi duyệt" (form từ `proposal_schema`) và "Từ chối" bắt
   buộc lý do.
6. Mục "Digital Worker" và "Hàng đợi việc" trong thanh trên cùng của `@dw/ui`; ngày giờ qua `lib/dates.ts`.
7. Trạng thái 403 và 404 dùng chung của app (R9.5).
8. Test vitest cho mỗi trang (dữ liệu giả của API) và DWK21.

## Tiêu chí chấp nhận

- [ ] R9.1: trang liệt kê hiện đủ bốn cột với dữ liệu giả hai DW.
- [ ] R9.2: trang hồ sơ hiện bốn người, ba mức của mỗi loại quyết định với chữ Tự động/Hỏi/Chặn, bốn số scorecard và mọi bước của tài liệu.
- [ ] R9.3: lọc `handed_off` chỉ hiện việc đó; `Drawer` hiện bốn trường gói và `trail`.
- [ ] R9.4: approval `dw.decision` hiện tiêu đề thư đề xuất và mức hiệu lực.
- [ ] R9.5 (DWK21): API giả trả 403 → không có hàng dữ liệu nào, hiện trạng thái không có quyền.
- [ ] Xong: `pnpm --filter web test` xanh.

## Nguồn

- `apps/web/app/approvals`; `CLAUDE.md` mục Web UI; spec: R9, DWK21.

## Comments
