# 07 — Màn Kết nối /studio/connections

Status: ready-for-agent
Blocked by: 04, 05, .claude/plans/studio/studio-skeleton/issues/03-seam-web-va-allowlist-antd.md
Area: studio
Yêu cầu: R5.7, R1.15, R5.18

## Mục tiêu

Quản trị viên của một workspace thấy, thêm, kiểm, tắt, xin bật lại và thu hồi vì lộ Kết nối dùng chung trên trang
`/studio/connections`, trên các route mà ticket 04 đã ship; người thiếu quyền thấy nút bị tắt kèm lý do, còn API vẫn
chặn (spec R5.7, R1.15, mục Màn hình). Ticket tách từ bước 7 của ticket 04 (V4.31), để luật `connection_usable` và API
không chờ seam web của studio-skeleton/03.

## Việc cần làm

1. Trang `apps/web/app/studio/connections/page.tsx` dưới seam web và allowlist antd của studio-skeleton/03, chỉ dùng
   `antd` và `@ant-design/icons` (CLAUDE.md, mục Web UI; `apps/web/lib/__tests__/antd-only.test.ts`), gọi client sinh
   bởi `make generate-contracts` của ticket 04: `GET /api/v1/connections`, `GET /api/v1/connections/{id}`,
   `GET /api/v1/connections/{id}/dependents`, `GET /api/v1/connectors`.
2. antd `Table` với cột tên, trình kết nối, tài khoản ngoài, workspace sở hữu (tên lấy từ danh sách workspace của
   `/me`, ngoài danh sách thì id ngắn), Phạm vi dùng chung, Connection status bằng chữ (không chỉ màu) cộng một `Tag`
   "Đã thu hồi vì lộ" khi `compromised_at` có giá trị (Connection status vẫn `active` sau lần thu hồi), lần dùng gần
   nhất qua `lib/dates.ts` (ticket 05 ghi `last_used_at`); `Drawer` thêm kết nối dựng ô nhập từ mục của `GET
/api/v1/connectors` (ticket 05 bước 3: `auth.secret_fields`, `settings_schema`; W1 chỉ có `smtp`, auth `basic`), gửi
   `POST /api/v1/connections` kèm `Idempotency-Key`, trường bí mật là ô mật khẩu không bao giờ điền sẵn; bí mật đã lưu
   hiện "Đã cấu hình". Bộ dựng form phủ đúng phần `settings_schema` dùng: chuỗi có trần, số nguyên có khoảng, enum,
   `format: email`; `external_account` của `smtp` lấy từ `from_address`, không ô riêng; ô `data_location` cho chọn `vn`
   và `foreign`, chọn `foreign` hiện cảnh báo rằng ở W1 Kết nối đó không gửi được (ticket 05, R7.11). Bảng phân trang theo
   cursor `next` của `GET /api/v1/connections`, 50 dòng một trang. Người không giữ `connections.read` ở đâu cả không thấy
   mục điều hướng, mở thẳng trang thì thấy thông báo không có quyền.
3. Trang chi tiết: sức khỏe là một nhãn suy từ dữ liệu đã có, không cột mới, theo thứ tự ưu tiên: `disabled` →
   "Đã tắt"; `compromised_at` có giá trị và một `secret_fields[].configured` false → "Đã thu hồi vì lộ, cần bí mật mới";
   một `configured` false → "Thiếu bí mật"; còn lại → "Hoạt động" (`compromised_at` chỉ tiến, nên sau "Đổi bí mật" nhãn
   về "Hoạt động" và lần thu hồi hiện như một mốc lịch sử; ở danh sách, không có `secret_fields`, `Tag` ghi "Thu hồi vì
   lộ lúc <thời điểm>" là mốc, không là trạng thái), thiết
   lập không bí mật (`settings`, ticket 05), "Được dùng bởi" (`.../dependents`: liệt kê `visible`, cộng dòng "và N
   thành phần bạn không xem được" khi `total` lớn hơn), yêu cầu bật lại đang chờ (`pending_enable_approval_id`: "Đang chờ người thứ hai duyệt", nút "Bật lại" tắt khi có yêu cầu chờ), thời
   điểm thu
   hồi vì lộ gần nhất (`compromised_at`); W1 không hiện mã lỗi gần nhất hay phạm vi đã cấp, vì không bên nào ghi chúng ở
   P1 (failure-modes #1; spec, Màn hình). Nút "Đổi bí mật" mở `Drawer` gửi `PATCH /api/v1/connections/{id}` với giá trị
   mới cho mọi trường của `auth.secret_fields`, kèm thiết lập đã sửa nếu có (`from_address` không sửa được; R5.22), để
   Kết nối dùng lại được sau lần thu hồi vì lộ; "Đổi tên" sửa `name` qua `PATCH`. Nút bật theo trạng thái cộng
   `can_manage`: "Tắt" và "Kiểm" chỉ khi `active`, "Bật lại" chỉ khi `disabled` và không có yêu cầu chờ, "Thu hồi vì lộ"
   ở mọi trạng thái khác `revoked`, mỗi nút tắt kèm lý do bằng chữ; nút "Kiểm" (`.../test`),
   "Tắt" (`.../disable`), "Bật lại" (`.../enable`, hiện 202 là "Đã gửi yêu cầu cho người thứ hai duyệt" và 409
   `no_checker_available` là lý do bằng chữ); xác nhận xóa nêu tên kết nối và danh sách phụ thuộc, 409
   `connection_in_use` hiện danh sách đó.
4. Nút "Thu hồi vì lộ" gọi `POST /api/v1/connections/{id}/revoke-credentials` (spec R1.15) sau một `Modal` xác nhận nói
   rằng mọi lượt chưa xong của kết nối sẽ dừng ở lời gọi ra ngoài kế tiếp, kể cả khi đã lưu mật khẩu mới; nút bật cho người giữ
   `connections.manage` (spec R1.15; Đạt, Q-h3).
5. Nút ghi của một Kết nối bật theo trường `can_manage` mà ticket này thêm vào câu trả lời danh sách và theo id của
   `GET /api/v1/connections`: server tính nó bằng đúng luật `platform.workspace_reach` với `connections.manage` mà
   `ConnectionService` dùng ở route ghi (R5.18; ADR-0104 (Accepted) quyết 5), web không tự tính tầm với; OpenAPI và kiểu
   TS sinh lại. Nút "Thêm kết nối" bật theo `connections.manage` ở workspace đang làm việc của `/me`. Người thiếu khóa
   thấy nút bị tắt kèm lý do; ẩn hay tắt nút không phải phân quyền, API của ticket 04 vẫn chặn (CLAUDE.md, Tenancy and
   authorization). Thông báo qua `App.useApp()`.

## Tiêu chí chấp nhận

- [ ] R5.7: Playwright mở `/studio/connections` với một Kết nối của fixture → thấy tên, trình kết nối, tài khoản
      ngoài, phạm vi, trạng thái bằng chữ và "Được dùng bởi"; trường bí mật hiện "Đã cấu hình", HTML của trang không
      chứa giá trị canary; người thiếu `connections.manage` thấy nút bị tắt kèm lý do và `POST /api/v1/connections` của
      người đó vẫn trả 403; bỏ cột trạng thái bằng chữ hay điền sẵn ô bí mật → test đỏ.
- [ ] R1.15: Playwright bấm "Thu hồi vì lộ" rồi hủy xác nhận → route không được gọi; xác nhận → route được gọi đúng một
      lần và trang chi tiết hiện thời điểm thu hồi cùng nhãn "Đã thu hồi vì lộ, cần bí mật mới"; "Đổi bí mật" với mật
      khẩu mới → `PATCH` một lần, nhãn đổi về "Hoạt động", mốc thu hồi vẫn hiện; bỏ bước xác nhận → ca hủy gọi route,
      test đỏ.
- [ ] R5.7: Kết nối `disabled` có yêu cầu bật lại đang chờ → nút "Bật lại" tắt kèm lý do, "Tắt" và "Kiểm" tắt; 51 Kết nối
      của fixture → trang hai có dòng thứ 51; `Drawer` thêm `smtp` không có ô `external_account`, thân `POST` mang nó bằng
      `from_address`.
- [ ] R5.18: người giữ `connections.manage` chỉ ở W1 và `connections.read` ở cả công ty: test API thấy `can_manage` true
      với Kết nối của W1 và false với Kết nối của W2; Playwright thấy nút ghi của dòng W2 bị tắt kèm lý do, `PATCH` của
      người đó lên Kết nối W2 vẫn 403; cho `can_manage` luôn true → test API đỏ.
- [ ] Xong: `make ci && make test-web` xanh.

## Nguồn

- spec: R5.7, R1.15, mục Màn hình, mục API; ticket 04 (route, `compromised_at`, `make generate-contracts`);
  studio-skeleton/03 (seam web và allowlist antd).
- `apps/web/lib/__tests__/antd-only.test.ts`; CLAUDE.md, mục Web UI (antd v6, `App.useApp()`, `lib/dates.ts`).

## Comments

- 2026-10-25 (agent): ticket mới theo V4.31 của Đạt (lượt h), số và đường dẫn theo bảng ticket mới của lượt: bước 7 cũ
  của ticket 04 (màn `/studio/connections`) cùng R5.7 dời về đây; Blocked by 04 và studio-skeleton/03 theo bảng cạnh
  của lượt, cộng Blocked by 05 (ngoài bảng, đã chạy mô phỏng đồ thị của lượt: không vòng, độ sâu của
  marketing-pilot/03 không đổi) vì `Drawer` thêm kết nối đọc danh mục trình kết nối `GET /api/v1/connectors` mà ticket
  05 ship. Thêm nút "Thu hồi vì lộ" của V4.35 (R1.15), khóa của nút chờ Q3.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check; ticket không thêm route
  hay migration, chỉ thêm trường `can_manage` vào câu trả lời của route có sẵn) trên `0baced0`: `check_plans.py` 24
  Đạt; 0 CRITICAL, 3 HIGH, sửa theo khuyến nghị: (a) "sức khỏe" và "mã lỗi gần nhất" không có nguồn (không cột, `GET`
  của ticket 04 không trả): sức khỏe là nhãn suy từ trạng thái, `compromised_at` và `secret_fields`, mã lỗi gần nhất và
  phạm vi đã cấp không hiện ở W1 (spec, Màn hình sửa cùng lượt); (b) nút ghi tắt theo gì: `can_manage` do server tính
  bằng luật tầm với của route ghi, web không tính lại (ADR-0104 (Accepted) quyết 5); (c) sau lần thu hồi vì lộ màn không
  có đường lưu bí mật mới: nút "Đổi bí mật" gửi `PATCH` (R5.22 của ticket 05). Nếu sai thì: (a) một cột
  `last_error_code` do ticket 05 ghi; (b) `/me` trả tầm với theo khóa và web đọc nó; (c) không đường an toàn hơn. Câu
  "khóa của nút chờ Q3" ở dòng 2026-10-25 đã cũ: Đạt trả lời Q-h3 (một người giữ `connections.manage`), spec R1.15.
- 2026-11-04 (agent): MEDIUM, chưa sửa: (M1) nhãn workspace lấy từ `/me`, nên người đọc được Kết nối của workspace mình
  không là thành viên thấy id ngắn; (M2) hộp duyệt chung hiện yêu cầu `connections.enable` theo nhãn loại của mảnh copy
  phê duyệt, payload chỉ id Kết nối: nhãn và liên kết tới trang chi tiết là việc của chủ hộp duyệt; (M3) màn `/studio/egress-hosts` của spec, Màn hình không có ticket:
  route của ticket 03 đã ship, màn đi cùng đợt màn quản trị sau, cần một ticket mới khi Đạt xếp nó (thêm vào Comments
  của spec ở lượt kiểm nhất quán); (M4) dòng `Xong:` đọc theo `.claude/rules/wave-close.md`, cộng ảnh Playwright sáng,
  tối, desktop và dưới 992px lúc đóng hàng đợi.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (builder check mới trên bản đã sửa): 0 CRITICAL, 3 HIGH,
  sửa: nhãn sức khỏe trái tiêu chí R1.15 vì `compromised_at` chỉ tiến (thứ tự ưu tiên, mốc lịch sử); nút theo trạng thái
  (`Tắt`, `Kiểm` chỉ khi `active`, `Bật lại` khi `disabled` không yêu cầu chờ); danh sách chỉ trang đầu (phân trang theo
  cursor). Sửa luôn vì rẻ: `external_account` từ `from_address`, `data_location` có cảnh báo, "Đổi tên", trang khi không
  có quyền đọc. Sửa của lượt này không có người đọc mới: nhận rủi ro (agent, theo ủy quyền 31/10/2026), mỗi sửa có tiêu
  chí đỏ được. Nếu sai thì: lỗi lộ ra khi dựng, ghi ở đây.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
