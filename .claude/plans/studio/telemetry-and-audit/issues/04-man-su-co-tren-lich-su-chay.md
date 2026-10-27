# 04 — Màn sự cố trên Lịch sử chạy: Chạy tiếp từ Bước lỗi và Kết thúc; màn giải outcome_review

Status: needs-triage
Blocked by: 03, .claude/plans/studio/workflow-engine/issues/07-chay-tiep-tu-buoc-loi.md, .claude/plans/studio/workflow-engine/issues/08-tac-dong-khong-ro-ket-qua.md
Area: studio
Yêu cầu: R4.6, R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R7.1, R7.2, R7.3, R7.4, R7.5, TA21, TA22, TA25, TA28, TA29

## Mục tiêu

Người dựng thấy một lượt quy trình đỗ ở một sự cố ngay trên `/runs/[id]` và giải nó bằng "Chạy tiếp từ Bước lỗi" hay
"Kết thúc", biết trước rằng lượt chạy lại với Bộ giá trị gắn đã ghim và phiên bản mới nhất chưa thu hồi của bí mật
(V4.35), và biết khi nào kết quả lần trước không rõ qua nhãn của catalog mã lý do (spec R6, R4.6; YC109; V4.26; H-12);
người giữ `runs.reconcile` thấy một lượt đỗ ở `outcome_review` và chọn "Đã nhận", "Chưa nhận, gửi lại cùng khóa" hay
"Bỏ" trên cùng màn (spec R7; V4.30). Route giải, dòng chờ `incident` và loại lỗi `outcome_unknown` là của
workflow-engine/07, route giải và dòng chờ `outcome_review` là của workflow-engine/08; lát này chỉ đọc dòng chờ và vẽ
màn, nên ticket 03 trên đường găng YC94 không chờ bậc B hay ticket 08.

## Việc cần làm

1. Route `GET /api/v1/runs/{run_id}/incidents` trong `apps/api/src/dw_api/routes/v1/runs.py` (`runs.read`, RLS của
   công ty và workspace theo độ sâu như `GET /api/v1/runs` của ticket 03): đọc dưới `dw_app` các dòng
   `platform.run_waits` có `kind = 'incident'` và `status = 'open'` của lượt, qua chỉ mục UNIQUE
   `(tenant_id, run_id, interrupt_id)` của bảng; mỗi dòng trả `wait_id` và `created_at` của dòng chờ, cùng `node_id`,
   `error_type` và `error_label` (nhãn của mã đó trong catalog mã lý do của ticket 03, NULL khi không có khóa; spec
   R4.6) của lần thử cuối của Bước lỗi, tức Bước chạy `kind` `node` có `seq` lớn nhất của lượt mang
   `error_type` trong `platform.run_steps` (chỉ mục `ix_run_steps_run (tenant_id, run_id, seq)` của ticket 03), không
   phải dòng `waiting` của Bước đó, vì lượt
   đỗ ngay sau lần thử đó và không Bước nào có `on_error` `incident` nằm trong làn song song (workflow-engine:R2.16);
   không nối Bước chạy theo `node_id` của dòng chờ, là node sự cố mà trình biên dịch của workflow-engine/07 dựng cho
   Bước lỗi, tên dẫn từ id Bước; lượt của công ty khác hay ngoài tầm theo độ sâu → 404 như id không tồn tại, không lộ
   dòng nào (spec R6.1, R6.2). Mô hình trả vào OpenAPI, và client sinh ra
   (`packages/typescript/api-client/src/generated/platform.d.ts`) mang phương thức mới.
2. Khối sự cố trên `/runs/[id]` (spec R6.3 tới R6.6): antd Alert nêu Bước lỗi và lỗi của lần thử cuối bằng
   `error_label`; câu "Chạy tiếp dùng lại Bộ giá trị gắn mà lượt đã ghim, với phiên bản mới nhất chưa thu hồi của mỗi bí
   mật; sửa Bộ giá trị gắn sau khi lượt bắt đầu không có tác dụng với lượt này" cạnh hai nút (V4.35); `error_label`
   "Không rõ nhà cung cấp đã nhận hay chưa" cạnh nút "Chạy tiếp từ Bước lỗi" khi `error_type` của lần thử cuối là
   `outcome_unknown`, chữ lấy từ API, màn không giữ bản chữ thứ hai (H-12); hai antd
   Button "Chạy tiếp từ Bước lỗi" và "Kết thúc" gọi `POST /api/v1/runs/{run_id}/incidents/{wait_id}/resume` và
   `.../end` của workflow-engine/07 qua `@dw/api-client`, mỗi lần bấm gửi đúng một yêu cầu với một `Idempotency-Key`
   mới, nút ở trạng thái đang tải tới khi có phản hồi; hai nút chỉ hiện khi `/me` báo người xem giữ
   `studio.workflows.resolve_incident` ở workspace của lượt (`hasScope`, `apps/web/lib/nav/visibility.ts`), còn route
   vẫn là chỗ kiểm (workflow-engine:R6.23). Phản hồi 403, 404 hay 409 → thông báo tiếng Việt theo `details.reason_code`
   qua `App.useApp()`, chữ đi qua khóa thông điệp, rồi đọc lại `.../incidents` và hiện đúng trạng thái máy chủ trả
   (spec R6.6); 200 → tải lại lượt, sự cố và Bước chạy.
3. Route `GET /api/v1/runs/{run_id}/outcome-reviews` cạnh route của bước 1, cùng kiểm (`runs.read`, RLS của công ty và
   workspace theo độ sâu): các dòng `platform.run_waits` có `kind = 'outcome_review'` và `status = 'open'` của lượt, mỗi
   dòng trả `wait_id` và `created_at` của dòng chờ cùng `node_id` của Bước đang chờ, đọc từ Bước chạy `waiting` có
   `reason_code` `outcome_unknown` và `seq` lớn nhất của lượt (spec R3.8), không nối theo `node_id` của dòng chờ, là node
   xác nhận mà trình biên dịch của workflow-engine/08 dựng cho Bước có hiệu ứng (workflow-engine:R6.30); lượt của công
   ty khác hay ngoài tầm → 404 như id không tồn tại (spec R7.1, R7.2). Mô hình trả vào OpenAPI và client sinh ra.
4. Khối giải `outcome_review` trên `/runs/[id]` (spec R7.3 tới R7.5): antd Alert ở Bước đang chờ với `reason_label`
   "Không rõ nhà cung cấp đã nhận hay chưa"; ba antd Button "Đã nhận", "Chưa nhận, gửi lại cùng khóa" và "Bỏ" gọi
   `POST /api/v1/runs/{run_id}/outcome-reviews/{wait_id}/resolve` của workflow-engine/08 qua `@dw/api-client` với
   `decision` `received`, `resend` hay `abandon`, mỗi lần bấm đúng một yêu cầu với một `Idempotency-Key` mới; "Đã nhận"
   mở antd Modal có ô bằng chứng bắt buộc và không gửi khi ô rỗng; ba nút chỉ hiện khi `/me` báo người xem giữ
   `runs.reconcile` ở workspace của lượt, còn route vẫn là chỗ kiểm, kể cả 409 `second_person_required` với tác động
   `critical` (workflow-engine:R6.35). Phản hồi 403, 404 hay 409 → thông báo tiếng Việt theo `details.reason_code` qua
   `App.useApp()`, rồi đọc lại `.../outcome-reviews` và hiện đúng trạng thái máy chủ trả (spec R7.5); 200 → tải lại lượt, dòng chờ và Bước chạy.
5. Test: hai route trên PostgreSQL thật (công ty khác, ngoài độ sâu, trong tầm, dòng `resolved` và `cancelled` không
   trả, dòng của lượt khác và dòng khác loại không trả); test màn với client giả (200, 409 `stale_interrupt`, 409
   `tenant_frozen`, 409 `second_person_required`, 403; `outcome_unknown` và một lỗi khác; "Đã nhận" với ô bằng chứng
   rỗng); Playwright mở `/runs/[id]` có sự cố và có `outcome_review` ở 320 px, không cuộn ngang.

## Tiêu chí chấp nhận

- [ ] R4.6 (TA25): đổi nhãn của `outcome_unknown` trong một catalog thử → `GET /api/v1/runs/{run_id}/incidents` trả nhãn
      mới trong `error_label` của sự cố có lần thử cuối mang mã đó; mã không có khóa → `error_label` NULL, sự cố vẫn trả.
- [ ] R6.1 (TA21): lượt có một sự cố `open` và một sự cố `resolved` → `GET /api/v1/runs/{run_id}/incidents` trả đúng
      sự cố `open` với `wait_id`, `node_id`, `created_at` và `error_type` của Bước chạy cuối của Bước lỗi; không trả sự
      cố `cancelled` hay sự cố của lượt khác; dòng chờ của fixture mang `node_id` của node sự cố, khác id Bước lỗi, như
      workflow-engine/07 ghi, và lần thử cuối mang `outcome_unknown` → sự cố trả id Bước lỗi và `outcome_unknown`; nối
      Bước chạy theo `node_id` của dòng chờ → `error_type` rỗng, test đỏ.
- [ ] R6.2 (TA21): người của công ty B gọi với `run_id` của công ty A → 404 giống hệt phản hồi cho một id ngẫu nhiên
      không tồn tại; người không có `runs.read` tới workspace của lượt → 404; chạy truy vấn bằng vai bỏ qua RLS, hay bỏ
      lọc độ sâu → test đỏ.
- [ ] R6.3: màn với client giả hiện Bước lỗi và hai nút cho người xem giữ `studio.workflows.resolve_incident`; bấm
      "Chạy tiếp từ Bước lỗi" gọi `POST .../incidents/{wait_id}/resume` đúng `wait_id` với một `Idempotency-Key`, bấm
      "Kết thúc" gọi `.../end`; người xem không giữ khóa không thấy hai nút; sai nếu gọi với `wait_id` khác hay thiếu
      khóa chống lặp.
- [ ] R6.4: khối sự cố hiện câu về Bộ giá trị gắn đã ghim và phiên bản mới nhất chưa thu hồi của bí mật cạnh hai nút;
      sai nếu câu vắng khi có sự cố, hay câu còn nói lượt dùng lại phiên bản bí mật đã ghim.
- [ ] R6.5 (TA22): `error_type` của lần thử cuối là `outcome_unknown` → `error_label` "Không rõ nhà cung cấp đã nhận hay
      chưa" mà client giả trả hiện cạnh nút "Chạy tiếp từ Bước lỗi"; một lỗi khác → không hiện; gỡ nhánh
      `outcome_unknown`, hay màn hiện một chữ tự giữ thay `error_label` → test màn đỏ.
- [ ] R6.6 (TA22): client giả trả 409 `tenant_frozen` hay 403 và lần đọc lại còn sự cố → thông báo tiếng Việt theo
      mã qua `App.useApp()`, sự cố còn hiện `open`; 409 `stale_interrupt` và lần đọc lại không còn sự cố → thông báo
      theo mã, khối sự cố thôi hiện; coi mọi phản hồi là thành công, hay giữ sự cố mà không đọc lại → test màn đỏ.
- [ ] R7.1 (TA28): lượt có một dòng `outcome_review` `open`, một dòng `outcome_review` `resolved` và một sự cố `open` →
      `GET /api/v1/runs/{run_id}/outcome-reviews` trả đúng dòng `outcome_review` `open` với `wait_id`, `created_at` và
      `node_id` của Bước đang chờ; dòng chờ của fixture mang `node_id` của node xác nhận, khác id Bước, như
      workflow-engine/08 ghi → dòng trả id Bước; nối Bước chạy theo `node_id` của dòng chờ → `node_id` rỗng, test đỏ.
- [ ] R7.2 (TA28): người của công ty B gọi với `run_id` của công ty A → 404 giống hệt phản hồi cho một id ngẫu nhiên;
      người không có `runs.read` tới workspace của lượt → 404; chạy truy vấn bằng vai bỏ qua RLS, hay bỏ lọc độ sâu →
      test đỏ.
- [ ] R7.3: màn với client giả hiện ba nút cho người xem giữ `runs.reconcile`; bấm từng nút gọi
      `POST .../outcome-reviews/{wait_id}/resolve` đúng `wait_id` với `decision` `received`, `resend`, `abandon` và một
      `Idempotency-Key`; người xem không giữ khóa không thấy ba nút; sai nếu gọi với `wait_id` khác hay thiếu khóa chống
      lặp.
- [ ] R7.4 (TA29): chọn "Đã nhận" với ô bằng chứng rỗng → client giả không nhận yêu cầu nào và màn nêu ô còn thiếu; có
      bằng chứng → đúng một yêu cầu `received` mang bằng chứng đó; gửi `received` không bằng chứng → test màn đỏ.
- [ ] R7.5 (TA29): client giả trả 409 `second_person_required`, 409 `stale_interrupt`, 409 `tenant_frozen` và 403 → mỗi
      ca một thông báo tiếng Việt theo mã qua `App.useApp()`, rồi đọc lại `.../outcome-reviews`: còn dòng chờ thì còn
      hiện `open`, `stale_interrupt` mà dòng đã giải thì khối giải thôi hiện; coi mọi phản hồi là thành công, hay giữ
      dòng chờ mà không đọc lại →
      test màn đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `apps/api/src/dw_api/routes/v1/runs.py:41-68`; spec: R6.1, R6.2 (`/runs` có đọc lượt và dòng thời gian, chưa đọc sự
  cố).
- `apps/web/lib/nav/visibility.ts:18-24`; spec: R6.3 (màn đọc khóa từ `/me` để ẩn nút, không thay chỗ kiểm).
- workflow-engine:R6.18, workflow-engine:R6.19, workflow-engine:R6.20, workflow-engine:R6.23, workflow-engine:R6.27,
  workflow-engine:R6.28; ADR-0122 (Accepted) quyết 4.
- workflow-engine:R6.30, workflow-engine:R6.31, workflow-engine:R6.32, workflow-engine:R6.35; spec: R7 (route giải
  `outcome_review` và node xác nhận của workflow-engine/08; V4.30).

## Comments

- 2026-10-24 (agent): ticket mới ở lượt g của vòng sửa 4, theo V4.26 của Đạt (Chạy tiếp từ Bước lỗi là một sự cố, màn
  của nó thuộc telemetry-and-audit) và dòng Quyết định tạm cùng ngày của spec: route đọc sự cố và khối sự cố trên
  `/runs/[id]`; Blocked by workflow-engine/07, nơi route giải, dòng chờ `incident` và loại lỗi `outcome_unknown` ra
  đời, cạnh đã kiểm không tạo vòng.
- 2026-10-24 (agent): kiểm lượt g của vòng sửa 4: bước 1 và tiêu chí R6.1 thôi nối Bước chạy theo `node_id` của dòng
  chờ, vì workflow-engine/07 ghi dòng chờ `incident` với `node_id` của node sự cố, không của Bước lỗi, nên phép nối đó
  không gặp lần thử nào và "Kết quả lần trước không rõ" không bao giờ hiện; route đọc lần thử cuối là Bước chạy `kind`
  `node` có `seq` lớn nhất của lượt mang `error_type` (spec R6.1, TA21, dòng Quyết định tạm cùng ngày). Không thêm cạnh.
- 2026-10-25 (agent): lượt h, theo V4.35 của Đạt và H-12 (các dòng cùng ngày của spec): câu cạnh hai nút thôi nói lượt
  dùng lại phiên bản bí mật đã ghim, vì bản kê không ghim phiên bản bí mật và chạy tiếp dùng phiên bản mới nhất chưa thu
  hồi (bước 2; R6.4); route sự cố mang `error_label` từ catalog mã lý do của ticket 03 và màn hiện nhãn đó thay câu
  "Kết quả lần trước không rõ" (bước 1, 2; R4.6, R6.5, TA22, TA25); route đọc lần thử cuối, không đọc dòng `waiting` của
  Bước (V4.36). Theo V4.30 và dòng tạm cùng ngày của spec, ticket này cũng giữ màn giải `outcome_review` và route đọc
  dòng chờ của nó (bước 3, 4, 5; R7.1-R7.5, TA28, TA29). Thêm Blocked by workflow-engine/08, nơi route giải và dòng chờ
  `outcome_review` ra đời, cạnh ngoài mục B của lượt h: đã chạy `g.py` trên cây hiện tại cộng các thao tác của mục B,
  không vòng, độ sâu `marketing-pilot/03` giữ 15, chuỗi dài nhất 18; ticket này đã chờ workflow-engine/07, sâu hơn
  ticket đó (cả hai chờ workflow-engine/05), và không ticket nào chờ ticket này, nên cạnh không làm ticket này sâu thêm.
- 2026-10-27 (agent): theo lời đáp của Đạt (câu 2 theo A): sau 403, 404 hay 409 màn đọc lại route đọc thay vì giữ
  `open`, nên sự cố hay dòng chờ người khác đã giải thôi hiện (spec R6.6, R7.5; TA22, TA29).
