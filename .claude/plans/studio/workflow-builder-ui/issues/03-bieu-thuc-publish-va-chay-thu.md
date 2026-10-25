# 03 — Ô biểu thức, lỗi tại chỗ, gửi kiểm định, chạy mô phỏng và màn lượt chạy

Status: needs-triage
Blocked by: 02, .claude/plans/studio/workflow-nodes/issues/03-pham-vi-bien-va-buoc-logic.md, .claude/plans/studio/workflow-triggers/issues/01-so-kich-hoat-chay-tay-va-danh-tinh.md, .claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md, .claude/plans/studio/agent-lifecycle/issues/03-hop-dong-vong-doi-va-niem-phong.md
Area: studio
Yêu cầu: R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R3.8, R3.9, R3.10, R3.11, R3.12, R3.13, R3.14, R3.15, BU2, BU3, BU5, BU6, BU9, BU15, BU16

## Mục tiêu

Ô Biểu thức có Chọn biến có kiểu kiểm ở máy chủ, lỗi kiểm gắn về đúng Bước, nút gửi kiểm định nêu lý do
khi khóa và không tự phát hành, trang chỉ đọc khi một Bản ứng viên còn chờ, bản Nháp mới chỉ mở khi người dựng bấm Tạo
bản Nháp, và chạy mô phỏng với một lựa chọn duyệt hay từ chối cho mỗi Bước phê duyệt, kết quả hiện trên cùng Sơ đồ theo
lần lặp và làn, che theo bảo mật trường (workflow-builder-ui R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R3.8, R3.9,
R3.10, R3.11, R3.12, R3.13, R3.14, R3.15, BU2, BU3, BU5, BU6, BU9, BU15, BU16).

## Việc cần làm

1. Ô Biểu thức: Chọn biến chèn đường dẫn có kiểu từ cây `GET /api/v1/studio/workflows/{id}/draft/scope?node=`
   (chỉ Bước trội); kiểm qua `POST /api/v1/studio/expressions/check` khi rời ô; hiện kiểu; bỏ qua phím
   khi `isComposing`. Không nhúng thư viện CEL vào bundle — mọi tính toán ở máy chủ.
2. Lỗi tại chỗ: huy hiệu lỗi trên Bước (chữ và màu, không chỉ màu); lỗi trường qua antd `Form.setFields`;
   ngăn kéo "Còn N lỗi" (`role="status"`); bấm một lỗi đưa focus tới Bước. Lỗi lấy từ 422 của máy chủ,
   mỗi lỗi mang mã Bước.
3. Nút Gửi kiểm định: gọi route gửi kiểm định của agent-lifecycle (agent-lifecycle:R2.1) với `If-Match` là ETag của
   Nháp đã đọc (R3.9; agent-lifecycle:R2.12, agent-lifecycle:R2.13), như tự lưu của ticket 02; 412 thì giữ nội dung
   đang gõ và mời tải lại; 409 `candidate_exists`, khi một tab khác đã gửi chính bản Nháp đó (agent-lifecycle:R1.3), thì
   đọc lại giai đoạn và vào trạng thái chỉ đọc của bước 6; khi bị khóa, nêu lý do; không có đường nào trong trang gọi
   phát hành. Giai đoạn vòng đời hiện ở đầu trang (đọc từ `agent-lifecycle`).
4. Chạy mô phỏng: biểu mẫu theo `input_schema` hoặc payload mẫu, cộng một lựa chọn bắt buộc "Duyệt" hay "Từ chối" (antd
   `Radio.Group`, nhãn từ khóa thông điệp) cho mỗi Bước phê duyệt của Nháp, gửi thành `simulated_decisions` theo id Bước
   (workflow-triggers:R2.7); trang chỉ gửi `simulate` ở W1, tới route `.../versions/{version_id}/test-runs` của
   workflow-triggers với id của phiên bản Nháp đang mở (route nhận bản `draft` ở chế độ `simulate`, bản kê ghim mã băm
   tạm của nội dung nháp, workflow-triggers:R2.3, tenant-config:R6.1; người gọi cần `studio.workflows.test`; route trả
   422 với `live`, với `test` tới W2, khi thiếu quyết định cho một Bước phê duyệt, và khi bộ kiểm khi gửi kiểm định báo
   lỗi `wf.*` trên nội dung nháp, ADR-0112 (Accepted) quyết 3, workflow-triggers:R2.2, workflow-triggers:R2.6,
   workflow-triggers:R2.8, workflow-triggers:R2.9). Mỗi lỗi `wf.*` của 422 đó gắn về đúng Bước như bước 2. Không Bước
   phê duyệt nào của lượt mô phỏng chờ người quyết (workflow-nodes:R9.9). Kết quả mở trên màn lượt chạy của bước 7.
5. Che theo bảo mật trường: một trường người xem không đọc được hiện "Đã ẩn" ở cả kết quả Bước và màn lượt
   chạy, ở mọi lần lặp và mọi làn, không rò trong DOM hay payload mạng.
6. Bản ứng viên đang chờ: khi giai đoạn đọc từ agent-lifecycle ở bước 3 là `evaluating` hay `awaiting_approval`, Sơ đồ,
   biểu mẫu và ô Biểu thức chỉ đọc, tự lưu của ticket 02 tắt, và trang không gọi `PUT .../draft` hay `POST .../draft` của
   tenant-config, vì thành phần không có bản Nháp nào khi một Bản ứng viên còn chờ (tenant-config:R2.20,
   tenant-config:R2.22). Một thông báo (khóa thông điệp) nêu "rút bản đang chờ về Nháp để sửa" kèm nút Rút về Nháp gọi
   `POST .../withdraw` của agent-lifecycle (agent-lifecycle:R2.4) chỉ khi người dựng bấm; route đó kiểm khóa gửi của loại,
   nên 403 giữ trang chỉ đọc và nêu lý do; rút xong, trang đọc lại bản Nháp cùng ETag của nó.
7. Màn lượt chạy (R3.11, R3.12): cùng Sơ đồ của ticket 02 ở chế độ chỉ đọc, không bảng Loại bước, không ô "+", không
   menu sửa, không lưu Nháp và không thao tác cây. Mỗi thẻ Bước mang trạng thái, thời gian, token và chi phí của Bước chạy
   từ `run_steps` bằng chữ cùng biểu tượng; đường đã đi được tô, với Bước phê duyệt là làn của quyết định giả lập nó đã
   đi; Bước chưa chạy ghi "Chưa chạy". Một bộ chọn lần lặp (antd `Select`) cho mỗi Bước vòng lặp đọc `iteration_path` mà
   mỗi Bước chạy mang, mọi làn của một Bước song song vẽ cùng lúc, qua `GET /api/v1/runs/{run_id}/steps`
   (telemetry-and-audit:R3.7, telemetry-and-audit:R4.2;
   `.claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md`). Khung, đầu làn và nhãn của từng cấu
   trúc là ticket 04; màn này dùng chúng khi có, không chờ chúng.
8. Bản Nháp mới (R3.13, R3.14, R3.15): Quy trình không có bản Nháp hay Bản ứng viên mở phiên bản Đang dùng, hay phiên
   bản mới nhất khi không có bản Đang dùng, chỉ đọc kèm nút "Tạo bản Nháp"; trang không gọi route tạo bản Nháp khi mở.
   Bấm nút thì gọi `POST /api/v1/studio/artifacts/{id}/draft` của tenant-config đúng một lần (tenant-config:R2.21) rồi
   mở bản Nháp trả về cùng ETag của nó; 409 `candidate_pending` (tenant-config:R2.22) thì đọc lại giai đoạn và vào trạng
   thái chỉ đọc của bước 6; 409 `draft_exists` (tenant-config:R2.23) thì đọc và mở bản Nháp đang có; không lần nào gọi
   lại route.

## Tiêu chí chấp nhận

- [ ] R3.1: cây Chọn biến của một Bước chỉ liệt kê Bước trội; Bước phía sau không xuất hiện.
- [ ] R3.2 (BU2): bundle route builder không chứa thư viện CEL (test manifest); một Biểu thức sai kiểu
      báo lỗi từ `/expressions/check` của máy chủ, không từ trình duyệt.
- [ ] R3.3 (BU3): gửi kiểm định một Nháp lỗi qua API → 422 với mỗi lỗi mang mã Bước.
- [ ] R3.4: khi có 422, mỗi lỗi gắn về đúng Bước và nút gửi kiểm định nêu lý do bị khóa.
- [ ] R3.5 (BU3): không đường nào trong trang builder gọi phát hành; grep mã trang không thấy lời gọi
      phát hành.
- [ ] R3.6 (BU5): trang builder chỉ gửi `simulate`, tới `.../versions/{version_id}/test-runs` với id của phiên bản
      Nháp đang mở; gọi thẳng route với `live` hay `test` → 422; bỏ giới hạn chế độ ở builder → test thành phần đỏ.
- [ ] R3.6: route trả 422 với một lỗi `wf.unreachable_node` có `path` của một Bước → lỗi gắn về đúng Bước đó và ngăn
      kéo "Còn N lỗi" đếm nó (test thành phần với route giả).
- [ ] R3.9: nút Gửi kiểm định gửi `If-Match` bằng ETag của Nháp đã đọc; route trả 412 vì một tab khác đã lưu → nội
      dung đang gõ giữ nguyên và trang mời tải lại; bỏ header → test thành phần đỏ.
- [ ] R3.7 (BU6): người không đọc được `phone` thấy "Đã ẩn" ở kết quả Bước và trên màn lượt chạy, kể cả ở lần lặp thứ
      hai của một khung vòng lặp và ở một làn song song, và số không có trong DOM hay payload mạng; gỡ che → test đỏ.
- [ ] R3.8: Nháp có hai Bước phê duyệt → biểu mẫu chạy mô phỏng có hai lựa chọn bắt buộc; chưa chọn một Bước thì
      nút chạy khóa có lý do; chọn đủ → thân yêu cầu mang `simulated_decisions` đúng hai id và hai quyết định đã
      chọn (test thành phần).
- [ ] R3.10 (BU9): Quy trình có Bản ứng viên ở `awaiting_approval` → Sơ đồ và biểu mẫu chỉ đọc, trang nêu "rút bản đang
      chờ về Nháp để sửa", không lời gọi `PUT .../draft` hay `POST .../draft`, không lời gọi `withdraw` khi chưa bấm Rút
      về Nháp; bấm → đúng một lời gọi `POST .../withdraw`, rồi trang mở bản Nháp với ETag mới; route gửi kiểm định giả
      trả 409 `candidate_exists` → trang vào cùng trạng thái chỉ đọc; bỏ trạng thái chỉ đọc → test thành phần đỏ.
- [ ] R3.11 (BU16): lượt mô phỏng của F5 (test thành phần với `GET /api/v1/runs/{run_id}/steps` giả) → Sơ đồ chỉ
      đọc, mỗi thẻ có trạng thái, thời gian, token và chi phí bằng chữ cùng biểu tượng; làn của quyết định giả lập được
      tô, làn kia ghi "Chưa chạy"; màn lượt chạy không gọi lưu Nháp hay thao tác cây nào; cho sửa trên màn lượt chạy →
      test thành phần đỏ.
- [ ] R3.12 (BU16): lượt mô phỏng của F3 (test thành phần với `GET /api/v1/runs/{run_id}/steps` giả) → chọn lần lặp
      2 → mỗi Bước của thân vòng lặp, ở mọi làn của một Bước song song trong thân, hiện Bước chạy có `iteration_path`
      của lần 2; bỏ lọc theo `iteration_path` → test đỏ.
- [ ] R3.13 (BU15): Quy trình chỉ có bản Đang dùng → trang chỉ đọc kèm "Tạo bản Nháp", không lời gọi
      `POST .../draft` khi chưa bấm; bấm → đúng một lời gọi, rồi trang mở bản Nháp với ETag route trả; gọi route lúc mở
      trang → test thành phần đỏ.
- [ ] R3.14 (BU15): route giả trả 409 `conflict` với `candidate_pending` → trang vào trạng thái chỉ đọc của R3.10, nêu
      "rút bản đang chờ về Nháp để sửa", không lời gọi thứ hai; gọi lại route sau 409 → test đỏ.
- [ ] R3.15 (BU15): route giả trả 409 `conflict` với `draft_exists` → trang đọc và mở bản Nháp đang có với ETag của nó,
      không lời gọi thứ hai; hiện lỗi thay vì mở bản Nháp → test đỏ.
- [ ] Xong: `pnpm -C apps/web test` xanh.

## Nguồn

- workflow-nodes:R3.2, workflow-nodes:R3.5;
  `.claude/plans/studio/workflow-nodes/issues/03-pham-vi-bien-va-buoc-logic.md`.
- workflow-triggers:R2.2, workflow-triggers:R2.3, workflow-triggers:R2.6, workflow-triggers:R2.9, tenant-config:R5.1,
  tenant-config:R6.1; ADR-0112 (Accepted) quyết 3; spec: R3.6.
- agent-lifecycle:R2.1, agent-lifecycle:R2.12, agent-lifecycle:R2.13; ADR-0108 (Accepted) quyết 3; spec: R3.9.
- agent-lifecycle:R1.3, agent-lifecycle:R2.4; tenant-config:R2.20, tenant-config:R2.22; spec: R3.10.
- tenant-config:R2.21, tenant-config:R2.22, tenant-config:R2.23; spec: R3.13, R3.14, R3.15.
- telemetry-and-audit:R3.7, telemetry-and-audit:R4.2;
  `.claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md`; spec: R3.11, R3.12 (Bước chạy mang
  `lane_path` và `iteration_path`).
- ADR-0101 (Accepted), ADR-0114 (Accepted); spec: R3.2.

## Comments

- 2026-10-23 (agent): theo phiếu 23/10/2026: W1 chỉ chạy thử `simulate` và route chạy thử là của workflow-triggers (DO-26.1); route kiểm biểu thức theo dạng sub-resource của ADR-0108 (Accepted); nút là "Gửi kiểm định" và gọi route của agent-lifecycle.
- 2026-10-24 (agent): theo quyết định N2 của Đạt ngày 24/10/2026: biểu mẫu chạy mô phỏng đòi một lựa chọn duyệt hay từ chối cho mỗi Bước phê duyệt (R3.8), thay câu "người duyệt trong lượt chạy thử là chính người thử"; lượt `simulate` gọi là chạy mô phỏng.
- 2026-10-24 (agent): vòng sửa thứ tư, theo quyết định của Đạt cùng ngày: route `.../test-runs` nhận bản Nháp ở chế độ `simulate`, nên trang chạy mô phỏng chính phiên bản Nháp đang mở và giữ lựa chọn cho mỗi Bước phê duyệt của Nháp (R3.6, R3.8).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt b, theo các quyết định tạm cùng ngày của spec: lỗi `wf.*` mà route chạy mô phỏng trả khi nội dung nháp trượt bộ kiểm khi gửi kiểm định gắn về Bước (R3.6); nút Gửi kiểm định gửi `If-Match` là ETag của Nháp (R3.9).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt f, theo quyết định V4.17 của Đạt cùng ngày: Quy trình có Bản ứng viên đang chờ thì trang chỉ đọc, nêu "rút bản đang chờ về Nháp để sửa" và chỉ gọi lệnh rút của agent-lifecycle khi người dựng bấm (R3.10, BU9). Không thêm cạnh: ticket đã chờ agent-lifecycle/03, nơi có lệnh rút.
- 2026-10-25 (agent): lượt g, theo V4.24 của Đạt và G-5 ngày 24/10/2026: kết quả lượt mô phỏng mở trên màn lượt chạy cùng Sơ đồ, chỉ đọc, chọn lần lặp và làn (R3.11, R3.12, BU16), thay lớp phủ trước đây; Quy trình không có bản Nháp hay Bản ứng viên mở bản Nháp mới chỉ khi người dựng bấm Tạo bản Nháp (R3.13, R3.14, R3.15, BU15). Không thêm cạnh: ticket đã chờ telemetry-and-audit/03 (làn và `iteration_path` của Bước chạy), và tenant-config/02 (route tạo bản Nháp) đã đứng trước nó qua ticket 02.
- 2026-10-25 (agent): màn lượt chạy thôi có bộ chọn làn (R3.12, BU16): id Bước là duy nhất trong cây (workflow-engine:R1.1) và mọi làn của một Bước song song vẽ cùng lúc, nên làn không phân biệt Bước chạy nào mà id chưa phân biệt, và ca âm của nó không đỏ được; bộ chọn chỉ số của `logic.map` đến ở W2 (dòng Quyết định 25/10/2026 của spec).
