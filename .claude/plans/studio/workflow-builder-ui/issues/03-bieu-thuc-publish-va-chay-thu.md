# 03 — Ô biểu thức, lỗi tại chỗ, gửi kiểm định và chạy mô phỏng từng bước

Status: needs-triage
Blocked by: 02, .claude/plans/studio/workflow-nodes/issues/03-pham-vi-bien-va-buoc-logic.md, .claude/plans/studio/workflow-triggers/issues/01-so-kich-hoat-chay-tay-va-danh-tinh.md, .claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md, .claude/plans/studio/agent-lifecycle/issues/03-hop-dong-vong-doi-va-niem-phong.md
Area: studio
Yêu cầu: R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, BU2, BU3, BU5, BU6

## Mục tiêu

Ô Biểu thức có Chọn biến có kiểu kiểm ở máy chủ, lỗi kiểm gắn về đúng Bước, nút gửi kiểm định nêu lý do
khi khóa và không tự phát hành, và chạy thử Mô phỏng với kết quả từng Bước chạy che theo bảo mật trường
(workflow-builder-ui R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, BU2, BU3, BU5, BU6).

## Việc cần làm

1. Ô Biểu thức: Chọn biến chèn đường dẫn có kiểu từ cây `GET /api/v1/studio/workflows/{id}/draft/scope?node=`
   (chỉ Bước trội); kiểm qua `POST /api/v1/studio/expressions:check` khi rời ô; hiện kiểu; bỏ qua phím
   khi `isComposing`. Không nhúng thư viện CEL vào bundle — mọi tính toán ở máy chủ.
2. Lỗi tại chỗ: huy hiệu lỗi trên Bước (chữ và màu, không chỉ màu); lỗi trường qua antd `Form.setFields`;
   ngăn kéo "Còn N lỗi" (`role="status"`); bấm một lỗi đưa focus tới Bước. Lỗi lấy từ 422 của máy chủ,
   mỗi lỗi mang mã Bước.
3. Nút gửi kiểm định: gọi API gửi kiểm định của `workflow-engine`; khi bị khóa, nêu lý do; không có
   đường nào trong trang gọi phát hành. Giai đoạn vòng đời hiện ở đầu trang (đọc từ `agent-lifecycle`).
4. Chạy thử: biểu mẫu theo `input_schema` hoặc payload mẫu; `simulate` mặc định, `test` khi người đó
   giữ `runs.test`; `mode=live` ở cửa chạy thử → 422. Lớp phủ trạng thái, thời gian, token, chi phí theo
   từng Bước chạy từ `run_steps`; người duyệt trong lượt chạy thử là chính người thử.
5. Che theo bảo mật trường: một trường người xem không đọc được hiện "Đã ẩn" ở cả kết quả Bước và lớp
   phủ, không rò trong DOM hay payload mạng.

## Tiêu chí chấp nhận

- [ ] R3.1: cây Chọn biến của một Bước chỉ liệt kê Bước trội; Bước phía sau không xuất hiện.
- [ ] R3.2 (BU2): bundle route builder không chứa thư viện CEL (test manifest); một Biểu thức sai kiểu
      báo lỗi từ `expressions:check` của máy chủ, không từ trình duyệt.
- [ ] R3.3 (BU3): gửi kiểm định một Nháp lỗi qua API → 422 với mỗi lỗi mang mã Bước.
- [ ] R3.4: khi có 422, mỗi lỗi gắn về đúng Bước và nút gửi kiểm định nêu lý do bị khóa.
- [ ] R3.5 (BU3): không đường nào trong trang builder gọi phát hành; grep mã trang không thấy lời gọi
      phát hành.
- [ ] R3.6 (BU5): chạy thử với `mode=live` → 422; `simulate` chạy được; `test` chỉ khi có `runs.test`.
- [ ] R3.7 (BU6): người không đọc được `phone` thấy "Đã ẩn" ở kết quả Bước, và số không có trong DOM
      hay payload mạng; gỡ che → test đỏ.
- [ ] Xong: `pnpm -C apps/web test` xanh.

## Nguồn

- workflow-nodes:R3.2, workflow-nodes:R3.5;
  `.claude/plans/studio/workflow-nodes/issues/03-pham-vi-bien-va-buoc-logic.md`.
- tenant-config:R4.1, tenant-config:R5.1; spec: R3.6.
- ADR-0101 (Proposed), ADR-0114 (Proposed); spec: R3.2.

## Comments
