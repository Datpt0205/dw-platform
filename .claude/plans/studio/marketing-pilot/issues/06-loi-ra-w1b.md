# 06 — Lối ra W1b: uat với OpenBao, trợ lý và rà soát bảo mật của phần trợ lý

Status: needs-triage
Blocked by: 04, 05, .claude/plans/studio/connections-and-vault/issues/06-openbao-transit-va-sao-luu-kho-khoa.md, .claude/plans/studio/telemetry-and-audit/issues/02-cay-span-va-mot-trace-id.md, .claude/plans/studio/usage-and-limits/issues/06-gioi-han-vong-agent.md
Area: studio
Yêu cầu: R5.1, R5.2, R5.4, R6.1, R6.6, R6.9, MP2, MP4, MP5, MP6

## Mục tiêu

Lối ra W1b của W1 (V4.31): lát đã qua lối ra W1a (ticket 05) lên uat, môi trường triển khai đầu tiên, sau cổng E2 của
Phương án A trong requirements.md, với kết nối SMTP của công ty demo mã hóa bằng OpenBao Transit, tuyến model khai `vn`,
trợ lý Marketing chỉ đọc (ticket 04), cây span một `trace_id`, phần trợ lý của các kiểm soát MP và một lượt rà soát bảo
mật của phần trợ lý (marketing-pilot R6.9; R5.1, R5.2, R5.4, R6.1, R6.6 và MP2, MP4, MP5, MP6 phần trợ lý). Lát vẫn
chỉ chạy trên lead giả lập: dữ liệu cá nhân thật chỉ sau cổng E3 (YC99), ngoài ticket này.

## Việc cần làm

1. Bộ e2e `tests/e2e/marketing_pilot/test_pilot_uat.py` chạy trên uat (`settings.is_deployed` true, host uat có chứng
   chỉ hợp lệ và HSTS theo DO-57), với công ty A và B do script gieo của ticket 02 dựng qua API công khai của uat, SMTP
   giả ở phía nhà cung cấp và lead giả lập của ticket 01: kết nối SMTP của công ty demo dùng OpenBao Transit
   (`.claude/plans/studio/connections-and-vault/issues/06-openbao-transit-va-sao-luu-kho-khoa.md`), vì `LocalDevKms` bị
   từ chối ở môi trường triển khai; bước `ai.llm` dùng tuyến model khai `vn` (FOG-10, FOG-18; DO-54.1). Target `make e2e-uat-marketing-pilot` chạy bộ này
   cùng các đột biến của bước 4 trỏ vào host uat.
2. Trợ lý Marketing của ticket 04 trên uat, với giới hạn vòng của agent (`ModelCallLimitMiddleware`,
   `ToolCallLimitMiddleware`, `recursion_limit` của subagent) của
   `.claude/plans/studio/usage-and-limits/issues/06-gioi-han-vong-agent.md`.
3. Cây span của một lượt Tiếp nhận lead và của một lượt hỏi trợ lý mang một `trace_id` từ cửa nhận tới lời gọi model và
   công cụ, span không nội dung (`.claude/plans/studio/telemetry-and-audit/issues/02-cay-span-va-mot-trace-id.md`).
4. Thêm vào `tests/e2e/marketing_pilot/test_mutations.py` của ticket 05 đột biến phần trợ lý của MP2, MP4, MP5, MP6, mỗi
   đột biến một lần thấy đỏ ghi ở Comments, chạy trên cùng công ty A và B.
5. Chạy `reviewing-feature-security` và `reviewing-deployment-security` trên phần trợ lý và trên lần đưa lát lên uat
   (route, ảnh, host, OpenBao, danh sách máy chủ được phép) và ghi kết quả ở Comments; mọi phát hiện CRITICAL/HIGH đóng
   trước khi đóng ticket.

## Tiêu chí chấp nhận

- [ ] R6.9: bộ e2e của bước 1 chạy trên uat với `is_deployed` true → kết nối SMTP của công ty demo có khóa dữ liệu bọc bởi
      OpenBao Transit, một lead giả lập chạy tới đúng một email đã duyệt; đặt kho khóa cục bộ cho kết nối đó → kết nối bị
      từ chối khi lưu, 0 email, test đỏ nếu email vẫn gửi.
- [ ] R6.9: một lượt Tiếp nhận lead và một lượt hỏi trợ lý trên uat → mỗi lượt có đúng một `trace_id` cho cả cây span; một
      span con mang `trace_id` khác → test đỏ.
- [ ] R6.1: trên uat, công ty B đọc 0 dòng của công ty A qua API và qua trợ lý.
- [ ] R5.1 (MP5): trên uat, nhân viên Sales ở mức Của tôi hỏi trợ lý "lead nào đang Nóng" → chỉ lead người đó phụ trách;
      trưởng Marketing thấy mọi lead của workspace Marketing, không lead nào của workspace Sales; gỡ policy bản ghi ở
      đường agent → trợ lý trả lead ngoài tầm, đỏ.
- [ ] R5.2 (MP6): vai Cộng tác viên Marketing hỏi trợ lý về một lead → câu trả lời không có số hay email, hiện "Đã ẩn";
      gỡ áp quyền trường ở lược đồ công cụ → số điện thoại rò vào câu trả lời, đỏ.
- [ ] R5.4 (MP2): trợ lý có công cụ gửi trực tiếp khai A3 → gửi kiểm định 422 `capability_trifecta_autonomy`; gỡ phân tích
      năng lực của loại `agent` → phiên bản lọt sang Đang kiểm định, đỏ.
- [ ] R6.1 (MP4): trợ lý của công ty B hỏi tên một lead của công ty A → không có; gỡ policy RLS tenant ở đường công cụ →
      tên lead của A xuất hiện, đỏ.
- [ ] R6.6: phiên bản trợ lý Marketing chỉ lên Đang dùng sau khi cổng chất lượng đạt bộ an ninh nền tảng 100% và một
      người không phải Tác giả duyệt; người gửi tự duyệt → 409 `conflict` với `second_person_required`, không lên Đang dùng.
- [ ] Xong: `make e2e-uat-marketing-pilot` xanh.

## Nguồn

- spec: R5.1, R5.2, R5.4, R6.1, R6.6, R6.9, MP2, MP4, MP5, MP6; requirements.md, Phương án A (lối ra W1b, cổng E2).
- connections-and-vault/06 (OpenBao Transit); telemetry-and-audit/02 (một `trace_id`); usage-and-limits/06 (giới hạn
  vòng của agent); agent-builder:R3.4, R5.1; compliance-pdpl:R4.3; YC61, YC80, YC96; ADR-0115 (Accepted),
  ADR-0123 (Accepted), ADR-0125 (Accepted); DO-57.

## Comments

- 2026-10-25 (agent): ticket mới của lượt h, theo V4.31 của Đạt (mục C của bảng ticket): lối ra W1b, nhận từ ticket 05
  phần trợ lý của MP2, MP4, MP5, MP6, cây span (telemetry-and-audit/02) và rà soát bảo mật của trợ lý, và từ ticket 03
  phần uat với OpenBao (connections-and-vault/06). Blocked by đúng dòng của mục C: 04, 05, connections-and-vault/06,
  telemetry-and-audit/02, usage-and-limits/06.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness (builder check; không route, không migration):
  CẦN XEM, ticket ở lại `needs-triage`. Trường hợp: nửa dựng trên trợ lý chat riêng đã bỏ (R5.1, R5.2, R5.4 và phần trợ
  lý của MP2, MP4, MP5, MP6 chờ bản viết lại của ticket 04 theo D15 và D17), nửa còn lại cần người: host uat có chứng
  chỉ, OpenBao Transit triển khai và một tuyến model thật khai `vn` là giá trị thật chỉ Đạt có (studio.md, Ủy quyền). Khuyến
  nghị theo ủy quyền: khi viết lại ticket 04, tách ticket này làm hai: lối ra W1b không trợ lý (uat, OpenBao, tuyến `vn`,
  cây span, các MP không phải trợ lý chạy lại trên uat), `ready-for-human` cho phần dựng môi trường; và phần kênh chat
  của Digital Worker trên uat, đi sau ticket 04 mới. Bản viết lại phải mang các HIGH sau:
    - (1) SMTP giả "ở phía nhà cung cấp" trên uat: một host công khai có tên vào `platform.egress_allowed_hosts` qua phê
      duyệt hai người `egress.allowed_host`, vì chính sách địa chỉ từ chối địa chỉ riêng ở môi trường triển khai, theo
      ADR-0115 (Accepted); script gieo cần bước đó.
    - (2) Bước `ai.llm` trên uat dùng model thật khai `data_location: vn` (chờ FOG-10) hay model giả: mock ở profile triển
      khai không chứng minh gì về lưu trú dữ liệu; model thật làm các khẳng định không còn tất định.
    - (3) "Đột biến trỏ vào host uat" không được nghĩa là triển khai bản gỡ RLS lên uat: mutation chạy cục bộ, uat chỉ chạy
      bộ xanh.
    - (4) Tiêu chí "đặt kho khóa cục bộ cho kết nối đó → bị từ chối khi lưu" không xảy ra được: kho khóa chọn theo bản
      triển khai và `validate_for_profile` từ chối `LocalDevKms` lúc khởi động; đổi thành test khởi động.
    - (5) Danh tính trên uat: không có bộ cấp token dev, nên script gieo của ticket 02 (token tự ký) không chạy được; cần
      người dùng thật của IdP uat. Mỗi lần chạy gieo công ty mới thì công ty rác dồn lại (failure-modes #6): nói ai dọn,
      bằng offboarding của người vận hành; Hạn mức không nâng được nên không dùng lại công ty cũ mãi.
    - (6) Một `trace_id` cho cả lượt có Bước phê duyệt: phần sau duyệt chạy từ request của người duyệt; giữ trace của cửa
      nhận hay nối bằng span link, và test đọc span trên uat từ đâu.
    - (7) R6.9 dẫn R5.1 tới R5.4 mà ticket không có tiêu chí cho R5.3 trên uat.
      Nếu sai thì: Đạt giữ trợ lý riêng và ticket qua gate sau khi sửa (1)-(7), không tách.
