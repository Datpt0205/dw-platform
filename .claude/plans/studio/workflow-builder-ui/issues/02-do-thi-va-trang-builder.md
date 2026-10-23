# 02 — Mô-đun đồ thị thuần và trang builder ba cột tự lưu bản nháp

Status: needs-triage
Blocked by: 01, .claude/plans/studio/workflow-engine/issues/01-tai-lieu-workflow-va-kiem-xuat-ban.md, .claude/plans/studio/workflow-nodes/issues/02-so-dang-ky-buoc-va-mau-chuoi.md
Area: studio
Yêu cầu: R1.4, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, BU4, BU7, BU8

## Mục tiêu

Một mô-đun đồ thị thuần chuyển tài liệu `dw.workflow/v1` thành Bước và Đường nối (và ngược lại), và trang
builder ba cột tự lưu Nháp, dùng được bằng bàn phím và ở 320 px (workflow-builder-ui R1.4, R2.1, R2.2,
R2.3, R2.4, R2.5, R2.6, BU4, BU7, BU8).

## Việc cần làm

1. `apps/web/lib/workflow-graph.ts` (thuần, có test đơn vị): tài liệu ↔ Bước và Đường nối; bố cục dagre;
   chèn giữa; nối Nhánh ra; xóa; thứ tự phím theo đồ thị; diff theo id Bước. Không lưu vị trí: round-trip
   giữ nguyên Mã băm nội dung.
2. Trang `/studio/workflows/[id]/builder`: cột bảng Loại bước (từ `GET /api/v1/studio/node-types`: nhóm,
   tìm, lý do khóa); cột Sơ đồ; cột biểu mẫu antd `Form` sinh từ `config_schema` cộng widget riêng (điểm
   gắn, người duyệt). Dưới `lg`: cột cấu hình thành Drawer.
3. Tự lưu Nháp: debounce; gửi `If-Match` phiên bản đã đọc; chỉ báo "Đang lưu… / Đã lưu / Lưu thất bại".
   Một 412 giữ nguyên nội dung đang gõ và mời tải lại.
4. Bàn phím và trình đọc màn hình: Dạng danh sách antd `Tree` đồng bộ với Sơ đồ; mũi tên theo thứ tự đồ
   thị, Enter mở cấu hình; phím tắt chỉ khi Sơ đồ có focus (WCAG 2.1.4); xóa có xác nhận nêu Bước và
   Đường nối sẽ mất; `ariaLabelConfig` tiếng Việt. Playwright ở 320 px và một dự án múi giờ khác.

## Tiêu chí chấp nhận

- [ ] R1.4 (BU8): kéo một Bước không đổi tài liệu và không đổi Mã băm nội dung; round-trip tài liệu →
      đồ thị → tài liệu giữ nguyên Mã băm.
- [ ] R2.1: trang hiện ba cột bảng Loại bước, Sơ đồ, cấu hình; dưới `lg` cột cấu hình thành Drawer.
- [ ] R2.2: ở 320 px không có cuộn ngang.
- [ ] R2.3: tự lưu gửi `If-Match` với phiên bản Nháp đã đọc.
- [ ] R2.4 (BU4): hai tab lưu cùng Nháp → tab sau nhận 412 và nội dung đang gõ giữ nguyên.
- [ ] R2.5 (BU7): Playwright thêm, nối và xóa Bước chỉ bằng bàn phím, không chuột.
- [ ] R2.6: Dạng danh sách đồng bộ với Sơ đồ; một bước thêm trên Sơ đồ xuất hiện trong `Tree` với nhãn
      tiếng Việt.
- [ ] Xong: `pnpm -C apps/web test` xanh.

## Nguồn

- workflow-nodes:R1.2; `.claude/plans/studio/workflow-nodes/issues/02-so-dang-ky-buoc-va-mau-chuoi.md`.
- `apps/web/app/layout.tsx:1`; spec: R2.1 (chưa có route `studio`).
- ADR-0101 (Proposed); spec: R1.4 (vị trí không lưu).

## Comments
