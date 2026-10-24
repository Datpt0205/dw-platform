# 03 — Ô biểu thức, lỗi tại chỗ, gửi kiểm định và chạy mô phỏng từng bước

Status: needs-triage
Blocked by: 02, .claude/plans/studio/workflow-nodes/issues/03-pham-vi-bien-va-buoc-logic.md, .claude/plans/studio/workflow-triggers/issues/01-so-kich-hoat-chay-tay-va-danh-tinh.md, .claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md, .claude/plans/studio/agent-lifecycle/issues/03-hop-dong-vong-doi-va-niem-phong.md
Area: studio
Yêu cầu: R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R3.8, BU2, BU3, BU5, BU6

## Mục tiêu

Ô Biểu thức có Chọn biến có kiểu kiểm ở máy chủ, lỗi kiểm gắn về đúng Bước, nút gửi kiểm định nêu lý do
khi khóa và không tự phát hành, và chạy mô phỏng với một lựa chọn duyệt hay từ chối cho mỗi Bước phê duyệt, kết
quả từng Bước chạy che theo bảo mật trường
(workflow-builder-ui R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R3.8, BU2, BU3, BU5, BU6).

## Việc cần làm

1. Ô Biểu thức: Chọn biến chèn đường dẫn có kiểu từ cây `GET /api/v1/studio/workflows/{id}/draft/scope?node=`
   (chỉ Bước trội); kiểm qua `POST /api/v1/studio/expressions/check` khi rời ô; hiện kiểu; bỏ qua phím
   khi `isComposing`. Không nhúng thư viện CEL vào bundle — mọi tính toán ở máy chủ.
2. Lỗi tại chỗ: huy hiệu lỗi trên Bước (chữ và màu, không chỉ màu); lỗi trường qua antd `Form.setFields`;
   ngăn kéo "Còn N lỗi" (`role="status"`); bấm một lỗi đưa focus tới Bước. Lỗi lấy từ 422 của máy chủ,
   mỗi lỗi mang mã Bước.
3. Nút Gửi kiểm định: gọi route gửi kiểm định của agent-lifecycle (agent-lifecycle:R2.1); khi bị khóa, nêu lý do; không có
   đường nào trong trang gọi phát hành. Giai đoạn vòng đời hiện ở đầu trang (đọc từ `agent-lifecycle`).
4. Chạy mô phỏng: biểu mẫu theo `input_schema` hoặc payload mẫu, cộng một lựa chọn bắt buộc "Duyệt" hay "Từ chối"
   (antd `Radio.Group`, nhãn từ khóa thông điệp) cho mỗi Bước phê duyệt của Nháp, gửi thành `simulated_decisions`
   theo id Bước (workflow-triggers:R2.7); trang chỉ gửi `simulate` ở W1, tới route `.../test-runs` của
   workflow-triggers (người gọi cần `studio.workflows.test`; route trả 422 với `live`, với `test` tới W2, và khi thiếu
   quyết định cho một Bước phê duyệt, workflow-triggers:R2.2, workflow-triggers:R2.6, workflow-triggers:R2.8). Không
   Bước phê duyệt nào của lượt mô phỏng chờ người quyết (workflow-nodes:R9.9). Lớp phủ trạng thái, thời gian, token,
   chi phí theo từng Bước chạy từ `run_steps`, kể cả quyết định giả lập mà mỗi Bước phê duyệt đã đi theo.
5. Che theo bảo mật trường: một trường người xem không đọc được hiện "Đã ẩn" ở cả kết quả Bước và lớp
   phủ, không rò trong DOM hay payload mạng.

## Tiêu chí chấp nhận

- [ ] R3.1: cây Chọn biến của một Bước chỉ liệt kê Bước trội; Bước phía sau không xuất hiện.
- [ ] R3.2 (BU2): bundle route builder không chứa thư viện CEL (test manifest); một Biểu thức sai kiểu
      báo lỗi từ `/expressions/check` của máy chủ, không từ trình duyệt.
- [ ] R3.3 (BU3): gửi kiểm định một Nháp lỗi qua API → 422 với mỗi lỗi mang mã Bước.
- [ ] R3.4: khi có 422, mỗi lỗi gắn về đúng Bước và nút gửi kiểm định nêu lý do bị khóa.
- [ ] R3.5 (BU3): không đường nào trong trang builder gọi phát hành; grep mã trang không thấy lời gọi
      phát hành.
- [ ] R3.6 (BU5): trang builder chỉ gửi `simulate`; gọi thẳng route với `live` hay `test` → 422; bỏ giới
      hạn chế độ ở builder → test thành phần đỏ.
- [ ] R3.7 (BU6): người không đọc được `phone` thấy "Đã ẩn" ở kết quả Bước, và số không có trong DOM
      hay payload mạng; gỡ che → test đỏ.
- [ ] R3.8: Nháp có hai Bước phê duyệt → biểu mẫu chạy mô phỏng có hai lựa chọn bắt buộc; chưa chọn một Bước thì
      nút chạy khóa có lý do; chọn đủ → thân yêu cầu mang `simulated_decisions` đúng hai id và hai quyết định đã
      chọn (test thành phần).
- [ ] Xong: `pnpm -C apps/web test` xanh.

## Nguồn

- workflow-nodes:R3.2, workflow-nodes:R3.5;
  `.claude/plans/studio/workflow-nodes/issues/03-pham-vi-bien-va-buoc-logic.md`.
- workflow-triggers:R2.2, workflow-triggers:R2.3, workflow-triggers:R2.6, tenant-config:R5.1; spec: R3.6.
- ADR-0101 (Accepted), ADR-0114 (Accepted); spec: R3.2.

## Comments

- 2026-10-23 (agent): theo phiếu 23/10/2026: W1 chỉ chạy thử `simulate` và route chạy thử là của workflow-triggers (DO-26.1); route kiểm biểu thức theo dạng sub-resource của ADR-0108 (Accepted); nút là "Gửi kiểm định" và gọi route của agent-lifecycle.
- 2026-10-24 (agent): theo quyết định N2 của Đạt ngày 24/10/2026: biểu mẫu chạy mô phỏng đòi một lựa chọn duyệt hay từ chối cho mỗi Bước phê duyệt (R3.8), thay câu "người duyệt trong lượt chạy thử là chính người thử"; lượt `simulate` gọi là chạy mô phỏng.
