# 04 — Màn sự cố trên Lịch sử chạy: Chạy tiếp từ Bước lỗi và Kết thúc

Status: needs-triage
Blocked by: 03, .claude/plans/studio/workflow-engine/issues/07-chay-tiep-tu-buoc-loi.md
Area: studio
Yêu cầu: R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, TA21, TA22

## Mục tiêu

Người dựng thấy một lượt quy trình đỗ ở một sự cố ngay trên `/runs/[id]` và giải nó bằng "Chạy tiếp từ Bước lỗi" hay
"Kết thúc", biết trước rằng lượt chạy lại với Bộ giá trị gắn và phiên bản bí mật đã ghim, và biết khi nào kết quả lần
trước không rõ (spec R6; YC109; V4.26). Route giải, dòng chờ `incident` và loại lỗi `outcome_unknown` là của
workflow-engine/07; lát này chỉ đọc sự cố và vẽ màn, nên ticket 03 trên đường găng YC94 không chờ bậc B.

## Việc cần làm

1. Route `GET /api/v1/runs/{run_id}/incidents` trong `apps/api/src/dw_api/routes/v1/runs.py` (`runs.read`, RLS của
   công ty và workspace theo độ sâu như `GET /api/v1/runs` của ticket 03): đọc dưới `dw_app` các dòng
   `platform.run_waits` có `kind = 'incident'` và `status = 'open'` của lượt, qua chỉ mục UNIQUE
   `(tenant_id, run_id, interrupt_id)` của bảng; mỗi dòng trả `wait_id` và `created_at` của dòng chờ, cùng `node_id`
   và `error_type` của lần thử cuối của Bước lỗi, tức Bước chạy `kind` `node` có `seq` lớn nhất của lượt mang
   `error_type` trong `platform.run_steps` (chỉ mục `ix_run_steps_run (tenant_id, run_id, seq)` của ticket 03), vì lượt
   đỗ ngay sau lần thử đó và không Bước nào có `on_error` `incident` nằm trong làn song song (workflow-engine:R2.16);
   không nối Bước chạy theo `node_id` của dòng chờ, là node sự cố mà trình biên dịch của workflow-engine/07 dựng cho
   Bước lỗi, tên dẫn từ id Bước; lượt của công ty khác hay ngoài tầm theo độ sâu → 404 như id không tồn tại, không lộ
   dòng nào (spec R6.1, R6.2). Mô hình trả vào OpenAPI, và client sinh ra
   (`packages/typescript/api-client/src/generated/platform.d.ts`) mang phương thức mới.
2. Khối sự cố trên `/runs/[id]` (spec R6.3 tới R6.6): antd Alert nêu Bước lỗi và lỗi của lần thử cuối; câu "Chạy tiếp
   dùng lại Bộ giá trị gắn và phiên bản bí mật mà lượt đã ghim, nên chỉ cứu được lỗi tạm thời" cạnh hai nút; "Kết quả
   lần trước không rõ" cạnh nút "Chạy tiếp từ Bước lỗi" khi `error_type` của lần thử cuối là `outcome_unknown`; hai antd
   Button "Chạy tiếp từ Bước lỗi" và "Kết thúc" gọi `POST /api/v1/runs/{run_id}/incidents/{wait_id}/resume` và
   `.../end` của workflow-engine/07 qua `@dw/api-client`, mỗi lần bấm gửi đúng một yêu cầu với một `Idempotency-Key`
   mới, nút ở trạng thái đang tải tới khi có phản hồi; hai nút chỉ hiện khi `/me` báo người xem giữ
   `studio.workflows.resolve_incident` ở workspace của lượt (`hasScope`, `apps/web/lib/nav/visibility.ts`), còn route
   vẫn là chỗ kiểm (workflow-engine:R6.23). Phản hồi 403, 404 hay 409 → thông báo tiếng Việt theo `details.reason_code`
   qua `App.useApp()`, chữ đi qua khóa thông điệp, sự cố vẫn hiện `open`; 200 → tải lại lượt, sự cố và Bước chạy.
3. Test: route trên PostgreSQL thật (công ty khác, ngoài độ sâu, trong tầm, sự cố `resolved` và `cancelled` không
   trả, sự cố của lượt khác không trả); test màn với client giả (200, 409 `stale_interrupt`, 409 `tenant_frozen`, 403;
   `outcome_unknown` và một lỗi khác); Playwright mở `/runs/[id]` có sự cố ở 320 px, không cuộn ngang.

## Tiêu chí chấp nhận

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
- [ ] R6.4: khối sự cố hiện câu về Bộ giá trị gắn và phiên bản bí mật đã ghim cạnh hai nút; sai nếu câu vắng khi có
      sự cố.
- [ ] R6.5 (TA22): `error_type` của lần thử cuối là `outcome_unknown` → "Kết quả lần trước không rõ" hiện cạnh nút
      "Chạy tiếp từ Bước lỗi"; một lỗi khác → không hiện; gỡ nhánh `outcome_unknown` → test màn đỏ.
- [ ] R6.6 (TA22): client giả trả 409 `stale_interrupt`, 409 `tenant_frozen` và 403 → mỗi ca một thông báo tiếng Việt
      theo mã qua `App.useApp()`, sự cố còn hiện `open`; coi mọi phản hồi là thành công → test màn đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `apps/api/src/dw_api/routes/v1/runs.py:41-68`; spec: R6.1, R6.2 (`/runs` có đọc lượt và dòng thời gian, chưa đọc sự
  cố).
- `apps/web/lib/nav/visibility.ts:18-24`; spec: R6.3 (màn đọc khóa từ `/me` để ẩn nút, không thay chỗ kiểm).
- workflow-engine:R6.18, workflow-engine:R6.19, workflow-engine:R6.20, workflow-engine:R6.23, workflow-engine:R6.27,
  workflow-engine:R6.28; ADR-0122 (Accepted) quyết 4.

## Comments

- 2026-10-24 (agent): ticket mới ở lượt g của vòng sửa 4, theo V4.26 của Đạt (Chạy tiếp từ Bước lỗi là một sự cố, màn
  của nó thuộc telemetry-and-audit) và dòng Quyết định tạm cùng ngày của spec: route đọc sự cố và khối sự cố trên
  `/runs/[id]`; Blocked by workflow-engine/07, nơi route giải, dòng chờ `incident` và loại lỗi `outcome_unknown` ra
  đời, cạnh đã kiểm không tạo vòng.
- 2026-10-24 (agent): kiểm lượt g của vòng sửa 4: bước 1 và tiêu chí R6.1 thôi nối Bước chạy theo `node_id` của dòng
  chờ, vì workflow-engine/07 ghi dòng chờ `incident` với `node_id` của node sự cố, không của Bước lỗi, nên phép nối đó
  không gặp lần thử nào và "Kết quả lần trước không rõ" không bao giờ hiện; route đọc lần thử cuối là Bước chạy `kind`
  `node` có `seq` lớn nhất của lượt mang `error_type` (spec R6.1, TA21, dòng Quyết định tạm cùng ngày). Không thêm cạnh.
