# Trình dựng quy trình: sơ đồ, cấu hình bước, chạy mô phỏng, phiên bản

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Người dựng không viết mã dựng một Quy trình bằng cách đặt Bước vào ô của một Sơ đồ có cấu trúc, cấu hình mỗi Bước bằng
biểu mẫu antd sinh từ schema, viết Biểu thức với một bộ Chọn biến có kiểu, chạy mô phỏng và gửi kiểm định. Sơ đồ là
ngoại lệ đầu tiên của allowlist antd-only: antd không có canvas, nên `@xyflow/react` vào `apps/web` chỉ ở đường dẫn
canvas `apps/web/app/studio/**/canvas/**`, có test giữ ranh giới, còn vị trí do một mô-đun thuần của ứng dụng tính từ
cây Bước, không thư viện bố cục nào. Biểu thức tính ở máy chủ, lỗi kiểm về từ bộ kiểm của máy chủ; trang builder không
bao giờ tự phát hành. Lát W1 là Sơ đồ có cấu trúc với ngữ pháp cho mọi cấu trúc (nhánh, phê duyệt, song song, vòng lặp,
nhánh lỗi, quy trình con), đủ dựng, chạy mô phỏng và gửi kiểm định quy trình Tiếp nhận lead, cùng Sơ đồ chỉ đọc có lớp
phần khác so với bản Đang dùng mà màn duyệt phát hành dùng (V4.33, V4.37).

## Hiện trạng (đã kiểm ở `7539b4e` ngày 25/10/2026)

- `apps/web` dùng `antd` ^6.6.5 và không có thư viện sơ đồ hay bố cục nào (`apps/web/package.json:20`).
  Thiếu: một Sơ đồ quy trình.
- `CLAUDE.md:140-153` chỉ cho `@xyflow/react`, ghim chính xác, dưới `apps/web/app/studio/**/canvas/**`, bố cục do mô-đun
  của ứng dụng tính từ cây Bước, và gọi `antd-only.test.ts` là allowlist `{module, glob, adr}`; nhưng test vẫn là
  denylist của hệ đã gỡ (`apps/web/lib/__tests__/antd-only.test.ts:16-18`) cộng ESLint `no-restricted-imports`, nên một
  thư viện canvas qua cả hai ở mọi đường dẫn — một check không thấy được phần nó phủ (`failure-modes.md` #0). Ràng buộc:
  ngoại lệ phải đổi test, không chỉ đổi chữ.
- `antd-only.test.ts` đọc cả `apps/web` lẫn gói `@dw/ui` ở `packages/typescript/ui`
  (`apps/web/lib/__tests__/antd-only.test.ts:14`), kể cả một phụ thuộc quay lại qua manifest mà không
  có import. Ràng buộc: test ngoại lệ khẳng định app nào khai và tệp nào import.
- Theme của `@dw/ui` là chủ duy nhất của màu, kiểu chữ và bo góc (`packages/typescript/ui/src/theme.ts:3-6`), và
  `apps/web/lib/__tests__/theme-contrast.test.ts:8-11` đo tương phản từ chính theme đó ở cả chế độ sáng và tối.
  Ràng buộc: bộ từ vựng của Sơ đồ vào theme đó và được đo ở đó, không định nghĩa lần thứ hai.
- CSP đặt `script-src` một nonce theo request với `strict-dynamic`, và `style-src 'unsafe-inline'` vì
  CSS-in-JS của antd viết thẻ `<style>` lúc chạy (`apps/web/lib/csp.ts:16-21`). Ràng buộc: gói canvas
  phải chạy dưới CSP này mà không chèn script nội tuyến không nonce.
- Các route dưới `apps/web/app/` là `admin`, `approvals`, `audit`, `integrations`, `knowledge`,
  `memory`, `platform`, `dev-login`; chưa có `studio` (`apps/web/app/layout.tsx:1`). Thiếu: điều hướng
  `/studio/*` do `studio-skeleton` dựng.

## Mục tiêu

### R1 — Sơ đồ có cấu trúc: một thư viện, vị trí tính từ cây Bước, ngữ pháp cho mọi cấu trúc

Người dựng đặt Bước vào ô của một Sơ đồ có cấu trúc, không kéo vị trí hay nối dây; antd vẽ mọi thân Bước, và vị trí
tính từ cây Bước lúc vẽ, không lưu (YC39; ngữ pháp cho các cấu trúc của YC105, YC108, YC110, YC117; BUI-01;
ADR-0101 (Accepted); ADR-0112 (Accepted) quyết 1).

- R1.1 `@xyflow/react` 12.12.0, ghim đúng phiên bản đó, PHẢI là thư viện sơ đồ duy nhất của `apps/web`, không kèm thư
  viện bố cục nào, chỉ được import dưới `apps/web/app/studio/**/canvas/**`, với đúng một `zustand` ≥4.5.6 và không bản
  5.x nào trong lockfile.
- R1.2 NẾU một tệp ngoài `apps/web/app/studio/**/canvas/**`, hay gói `@dw/ui`, import hay khai báo `@xyflow/react`,
  hoặc một manifest của `apps/web` hay `@dw/ui` khai `@dagrejs/dagre`, THÌ `antd-only.test.ts` PHẢI đỏ.
- R1.3 Sơ đồ PHẢI để antd vẽ mọi thân Bước, đầu khung chứa, nhãn làn, ô "+", menu, Popover, biểu mẫu, nút thu phóng
  và thông báo, với màu, kiểu chữ và bo góc lấy từ theme antd, còn Tailwind chỉ lo bố cục.
- R1.4 KHI người dựng đặt một Bước vào một ô (nút "+" trên một đường nối, ô "Thêm Bước" của một làn trống, hay kéo từ
  bảng Loại bước hoặc kéo một Bước có sẵn vào ô), trang builder PHẢI đổi tài liệu bằng đúng một thao tác chèn hay dời
  trên cây ở làn và vị trí của ô đó, không ghi vị trí hay đường nối nào, vì thẻ Bước không kéo tự do và không nối dây
  được.
- R1.5 Sơ đồ PHẢI vẽ mỗi cấu trúc của cây Bước theo ngữ pháp ở bảng dưới, từ năm khối chung (chuỗi, làn, khung chứa,
  mũi tên quay lại, làn lỗi) mà các Loại bước W2 dùng lại, với màu nhóm, biểu tượng, cỡ thẻ và kiểu đường nối chỉ lấy
  từ bộ từ vựng của Sơ đồ trong theme của `@dw/ui`.

| Cấu trúc                           | Ngữ pháp trên Sơ đồ                                                                                                                                                                                                          |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Chuỗi                              | Thẻ Bước xếp một chiều, trên xuống dưới; một ô "+" trên mỗi đường nối, luôn hiện, không chỉ khi rê chuột, vùng chạm ít nhất 24 px; làn trống có ô "Thêm Bước" nét đứt                                                        |
| `logic.switch`                     | Thẻ điều kiện; dưới nó các làn cạnh nhau theo thứ tự tài liệu, mỗi làn dưới một Tag điều kiện ("Điểm ≥ 70"); làn "Khác" luôn có; các làn gộp ở một điểm dưới các làn, không phải Điểm nối                                    |
| Bước phê duyệt (`human.approval`)  | Thẻ người duyệt (người được giao, phạm vi; "Cần cả N người duyệt" khi Bước đòi N người duyệt bắt buộc); làn "Duyệt" và "Từ chối" treo dưới thẻ, gộp ở một điểm dưới các làn                                                  |
| Bước song song (`logic.parallel`)  | Khung "Song song" N làn cạnh nhau; đáy khung là Điểm nối, một thanh "Chờ tất cả nhánh xong"                                                                                                                                  |
| Bước vòng lặp (`logic.loop`)       | Khung "Lặp lại khi … (tối đa N lần)" quanh thân; mũi tên "Lặp lại" dọc bên trái; làn "Đã đủ N lần" cho Nhánh ra `max_reached` khi Bước có làn đó; Bước "Thoát vòng lặp" (`logic.break`) vẽ mũi tên tới lối ra dưới khung     |
| Làn lỗi (Khi lỗi là `route`)       | Làn nét đứt bên phải Bước, nhãn "Khi lỗi" theo token lỗi của theme, gộp lại dưới Bước, trừ khi làn kết thúc bằng `flow.stop`; trong một làn song song chỉ gộp lại (bộ kiểm từ chối làn kết thúc ở đó, workflow-engine:R2.15) |
| Quy trình con (`flow.subworkflow`) | Thẻ Bước mang dấu "Quy trình con" (biểu tượng cùng chữ), `api_name` của Quy trình được gọi và dòng "Chờ Quy trình con xong"; không Bước nào của Quy trình con được vẽ trong Sơ đồ cha                                        |

- R1.6 Sơ đồ PHẢI đặt cùng một tài liệu ở cùng tọa độ mỗi lần vẽ, sao cho chèn một Bước chỉ dời xuống các Bước đi sau
  chỗ chèn trong làn đó và trong các chuỗi bao ngoài, chèn một Bước có làn còn có thể đẩy các làn anh em sang ngang,
  và không lần chèn nào đổi thứ tự dọc hay thứ tự làn.
- R1.7 KHI người dựng thu gọn hay mở một khung chứa, Sơ đồ PHẢI vẽ khung thu gọn như một thẻ, nhớ trạng thái đó theo
  người xem trên trình duyệt, và không đổi tài liệu hay Mã băm nội dung.
- R1.8 Sơ đồ PHẢI vẽ mỗi Bước bằng một antd Card cỡ cố định gồm ô biểu tượng theo nhóm, tên người dựng đặt (cắt bằng
  dấu …, đủ chữ qua Tooltip), Loại bước với tóm tắt cấu hình, và huy hiệu cho thử lại, hết giờ và Khi lỗi của Bước
  ("Thử lại ×3", "Hết giờ 30 s", "Khi lỗi: …"), luôn có chữ cùng biểu tượng, không chỉ màu.
- R1.9 Bộ từ vựng của Sơ đồ PHẢI nằm đúng một lần trong theme của `@dw/ui`, cho mỗi nhóm Loại bước một màu từ token
  của theme đạt tương phản 3:1 trên nền thẻ ở cả chế độ sáng và tối, không là sắc nhạt preset của antd, cùng một biểu
  tượng `@ant-design/icons`, cỡ thẻ và kiểu đường nối.

### R2 — Trang builder: bảng chọn, cấu hình trong Drawer, tự lưu, dùng được bằng bàn phím

Người dựng đặt và cấu hình Bước ở màn hẹp, chỉ bằng bàn phím và bằng trình đọc màn hình (YC39; BUI-02, BUI-05,
BUI-07).

- R2.1 KHI người dựng mở `/studio/workflows/[id]/builder`, trang builder PHẢI đưa danh mục Loại bước của
  `GET /api/v1/studio/node-types` (nhóm, tìm, lý do khóa) qua hai đường, một Popover có ô tìm mở từ mỗi ô "+" hay ô
  "Thêm Bước" và một bảng bên kéo được vào ô từ breakpoint `lg`, và mở cấu hình của Bước trong một Drawer với antd Form
  sinh từ `config_schema`.
- R2.2 Ở màn rộng 320 px, trang builder PHẢI không cuộn ngang.
- R2.3 KHI trang builder tự lưu Nháp, trang builder PHẢI gửi `If-Match` với phiên bản Nháp đã đọc.
- R2.4 NẾU hai tab lưu cùng một Nháp, THÌ trang builder PHẢI nhận 412 và giữ nguyên nội dung đang gõ.
- R2.5 Mỗi thao tác chuột trên Sơ đồ PHẢI có một đường bàn phím tương đương, kể cả đặt Bước vào ô, dời, xóa, hoàn tác
  và mở cấu hình, theo roving focus một điểm dừng Tab trong thứ tự tài liệu: ↑/↓ tới Bước trước, sau, ←/→ tới làn kế,
  Enter mở cấu hình, Esc về Bước, Shift+F10 mở menu "…", Ctrl+Z và Ctrl+Shift+Z hoàn tác, làm lại, Ctrl+K mở "Đi tới
  Bước".
- R2.6 Dạng danh sách PHẢI là chính cây tài liệu mà Sơ đồ vẽ, mỗi node mang `aria-level`, `aria-posinset` và
  `aria-setsize` theo cấp và vị trí của nó, và là trình dựng chính dưới breakpoint `md` và ở 320 px, với cùng các thao
  tác thêm, dời, xóa và mở cấu hình như Sơ đồ.
- R2.7 TRONG KHI Sơ đồ không có focus, trang builder PHẢI không để phím nào, kể cả phím đơn, Space, Shift và Backspace,
  kéo, chọn hay xóa gì trên Sơ đồ (WCAG 2.1.4).
- R2.8 KHI một sự kiện phím có `isComposing` đúng, mọi bộ bắt phím của trang builder PHẢI bỏ qua sự kiện đó, để gõ
  Telex không chạy phím tắt nào (ui-quality.md §3).
- R2.9 Mỗi điều khiển trên Sơ đồ PHẢI mang tên truy cập tiếng Việt từ khóa thông điệp (ô "+" tên là "Thêm Bước sau
  «tên»"), mỗi đường nối mang tên tiếng Việt hay không tên nào, và không phần tử nào giữ chuỗi tiếng Anh mặc định của
  thư viện sơ đồ (ui-quality.md §12; DO-57).
- R2.10 KHI người dựng thêm, dời hay xóa một Bước, trang builder PHẢI báo thao tác đó qua một vùng `aria-live`, nêu tên
  Bước và làn của nó.
- R2.11 KHI người dựng xóa một Bước hay một khung chứa, trang builder PHẢI xóa ngay, không hộp xác nhận, và hiện qua
  `App.useApp()` một thông báo có nút Hoàn tác nêu tên mọi Bước bị xóa, mà Hoàn tác trả tài liệu về đúng nội dung trước
  lần xóa (ui-quality.md §10).

### R3 — Ô biểu thức, lỗi tại chỗ, gửi kiểm định, chạy mô phỏng, màn lượt chạy, lớp phần khác

Biểu thức kiểm ở máy chủ, lỗi về đúng Bước, chạy mô phỏng không rời chế độ an toàn và hiện kết quả trên cùng Sơ đồ theo
làn và lần lặp, bản Nháp mới chỉ mở khi người dựng chọn, trang builder không tự phát hành, và Sơ đồ chỉ đọc so một phiên
bản với bản Đang dùng theo id Bước cho màn duyệt phát hành (YC33, YC40, YC116; V4.37; BUI-03, BUI-04, BUI-06).

- R3.1 KHI người dựng gõ trong ô Biểu thức, Chọn biến PHẢI chỉ hiện biến có kiểu của Bước trội tại vị
  trí đó, lấy từ `draft/scope` của máy chủ.
- R3.2 Ô Biểu thức PHẢI kiểm qua `POST /api/v1/studio/expressions/check` ở máy chủ và không bao giờ tính
  Biểu thức trong trình duyệt.
- R3.3 NẾU một Nháp đem gửi kiểm định có lỗi kiểm, THÌ máy chủ PHẢI trả 422 với mỗi lỗi mang mã Bước
  của nó.
- R3.4 KHI máy chủ trả 422, trang builder PHẢI gắn mỗi lỗi về đúng Bước và nêu lý do nút gửi kiểm định
  bị khóa.
- R3.5 Trang builder PHẢI không bao giờ tự phát hành; nó chỉ gửi kiểm định, còn vòng đời quyết định việc
  phát hành.
- R3.6 KHI người dựng chạy mô phỏng, trang builder PHẢI gửi chế độ `simulate` tới route
  `.../versions/{version_id}/test-runs` với id của phiên bản Nháp đang mở và hiện lỗi 422 của route, gắn về đúng Bước
  như R3.4 mỗi lỗi `wf.*` mà bộ kiểm khi gửi kiểm định báo trên nội dung nháp (ADR-0112 (Accepted) quyết 3); quyền,
  chế độ được nhận, việc nhận bản Nháp và 422 đó là của workflow-triggers:R2.2, workflow-triggers:R2.3,
  workflow-triggers:R2.6 và workflow-triggers:R2.9, còn lần kiểm là của `RunRequestService` (workflow-engine:R3.11).
- R3.7 KHI lượt mô phỏng trả kết quả từng Bước chạy, trang builder PHẢI hiện "Đã ẩn" cho mỗi trường người
  xem không đọc được, không rò giá trị trong DOM hay payload mạng.
- R3.8 KHI người dựng chạy mô phỏng một Quy trình có Bước phê duyệt, biểu mẫu chạy mô phỏng PHẢI đòi một lựa chọn
  duyệt hay từ chối cho mỗi Bước phê duyệt của Nháp và gửi các lựa chọn đó trong thân yêu cầu, để không Bước phê
  duyệt nào chờ người quyết (workflow-triggers:R2.7, workflow-triggers:R2.8, workflow-nodes:R9.9).
- R3.9 KHI người dựng gửi kiểm định, trang builder PHẢI gửi `If-Match` bằng ETag của Nháp đã đọc tới route gửi kiểm
  định, như khi tự lưu (R2.3), để lệnh gửi một Nháp đã đổi ở tab khác nhận 412 thay vì niêm phong nội dung người dựng
  chưa thấy (agent-lifecycle:R2.12, agent-lifecycle:R2.13; ADR-0108 (Accepted) quyết 3).
- R3.10 TRONG KHI Quy trình có Bản ứng viên ở `evaluating` hay `awaiting_approval`, trang builder PHẢI hiện Bản ứng viên
  chỉ đọc, không gọi lưu nháp hay route tạo bản Nháp, nêu rằng muốn sửa thì rút bản đang chờ về Nháp, và chỉ gọi lệnh
  rút của agent-lifecycle khi người dựng chọn rút (agent-lifecycle:R2.4; tenant-config:R2.20, tenant-config:R2.22).
- R3.11 KHI người dựng mở kết quả một lượt mô phỏng do chính mình xin, qua id lượt mà route `test-runs` trả, trang
  builder PHẢI vẽ lượt đó trên cùng Sơ đồ ở chế độ chỉ đọc, mỗi Bước mang trạng thái, thời gian, token và chi phí của
  Bước chạy của nó, đường lượt đã đi được tô và Bước chưa chạy ghi "Chưa chạy", luôn có chữ cùng biểu tượng, không chỉ
  màu (quyền đọc Bước chạy của lượt đó là của người giữ `studio.workflows.test` đã xin nó, telemetry-and-audit:R4.4,
  telemetry-and-audit:R4.5; V4.41, H-17).
- R3.12 KHI người xem chọn một lần lặp của một Bước vòng lặp trên màn lượt chạy, màn lượt chạy PHẢI hiện cho mỗi Bước
  trong thân đó, ở mọi làn, đúng Bước chạy có `iteration_path` khớp lựa chọn.
- R3.13 TRONG KHI một Quy trình không có bản Nháp hay Bản ứng viên, KHI người dựng bấm "Tạo bản Nháp", trang builder
  PHẢI gọi `POST /api/v1/studio/artifacts/{id}/draft` đúng một lần và mở bản Nháp route trả cùng ETag của bản đó
  (tenant-config:R2.21).
- R3.14 NẾU route tạo bản Nháp trả 409 `conflict` với `details.reason_code` `candidate_pending`, THÌ trang builder
  PHẢI đọc lại giai đoạn và vào trạng thái chỉ đọc của R3.10, nêu "rút bản đang chờ về Nháp để sửa", và không gọi lại
  route (tenant-config:R2.22).
- R3.15 NẾU route tạo bản Nháp trả 409 `conflict` với `details.reason_code` `draft_exists`, THÌ trang builder PHẢI mở
  bản Nháp đang có cùng ETag của nó và không gọi lại route (tenant-config:R2.23).
- R3.16 KHI một màn mở Sơ đồ chỉ đọc của một phiên bản kèm bản Đang dùng của cùng Quy trình để so, hay kèm lời nêu rằng
  Quy trình chưa có bản Đang dùng, Sơ đồ chỉ đọc PHẢI gắn nhãn "Mới" cho mỗi Bước có id chỉ ở phiên bản đang xem, là
  mọi Bước khi chưa có bản Đang dùng, nhãn "Đã sửa" cho mỗi Bước có id ở cả hai bản mà nội dung, làn chứa hay thứ tự
  giữa các Bước chung của làn khác, và không nhãn nào cho Bước giống hệt, luôn có chữ cùng biểu tượng.
- R3.17 KHI một id Bước chỉ có ở bản Đang dùng, Sơ đồ chỉ đọc PHẢI liệt kê Bước đó trong danh sách "Bước đã xóa" cạnh Sơ
  đồ, với tên, Loại bước và làn cũ của nó, vì phiên bản đang xem không có chỗ cho thẻ của nó.
- R3.18 KHI người xem chọn một Bước mang nhãn "Đã sửa", Sơ đồ chỉ đọc PHẢI mở một Drawer chỉ đọc nêu từng trường của
  Bước đã khác, với giá trị ở bản Đang dùng và ở phiên bản đang xem.
- R3.19 NẾU màn mở Sơ đồ chỉ đọc không đưa được bản Đang dùng để so, vì đọc lỗi hay chưa rõ Quy trình có bản Đang dùng
  hay không, THÌ Sơ đồ chỉ đọc PHẢI nêu "Không so được với bản Đang dùng" và không gắn nhãn phần khác nào, không bao giờ
  vẽ như không có phần khác.
- R3.20 KHI phần ngoài cây Bước của tài liệu (`triggers`, `variables`, `inputs`, `outputs`, `bindings`, `limits`,
  `outcomes`) khác bản Đang dùng, Sơ đồ chỉ đọc PHẢI nêu tên mỗi phần đã khác ở đầu Sơ đồ, vì không thẻ Bước nào mang
  chúng.

## Trong phạm vi

- Route `/studio/workflows/[id]/builder` và các thành phần của nó, kể cả màn lượt chạy của lượt mô phỏng trên cùng Sơ
  đồ.
- Sơ đồ chỉ đọc với lớp phần khác so với bản Đang dùng, tính theo id Bước bằng diff của `workflow-graph.ts`: nhãn "Mới",
  "Đã sửa", danh sách "Bước đã xóa", Drawer chỉ đọc nêu trường đã khác, tên các phần ngoài cây Bước đã khác, và thông
  báo khi không so được (R3.16-R3.20); thành phần dưới glob canvas mà màn duyệt của agent-lifecycle/07 dùng, còn route,
  quyền và hai phiên bản đưa vào là của màn đó.
- `apps/web/lib/workflow-graph.ts`: mô-đun thuần, không import gói nào: tài liệu `dw.workflow/v1` là cây Bước, mỗi
  Nhánh ra của Bước là một làn; chèn vào ô, dời sang ô khác, xóa Bước hay khung chứa, hoàn tác và làm lại, thứ tự phím
  theo tài liệu, diff theo id Bước.
- `apps/web/lib/workflow-layout.ts`: mô-đun thuần, không import gói nào, ngoài glob canvas: vị trí của năm khối tính từ
  cây theo hai bước (đo từ dưới lên, đặt từ trên xuống), O(n), trả hình thuần mà Sơ đồ dưới glob canvas đổi thành node
  và cạnh của React Flow.
- Ngữ pháp Sơ đồ cho mọi cấu trúc và thẻ Bước; bộ từ vựng của Sơ đồ trong theme của `@dw/ui`.
- Ô Biểu thức với Chọn biến có kiểu; huy hiệu lỗi trên Bước; nút gửi kiểm định; biểu mẫu chạy mô phỏng, với một lựa
  chọn duyệt hay từ chối cho mỗi Bước phê duyệt; trạng thái chỉ đọc khi Quy trình có Bản ứng viên đang chờ, với lời mời
  rút bản đang chờ về Nháp để sửa; nút Tạo bản Nháp gọi route tạo bản Nháp của tenant-config.
- Dạng danh sách (antd `Tree`): chính cây tài liệu, mang `aria-level`, `aria-posinset`, `aria-setsize`, là trình dựng
  chính dưới `md`.
- Ngoại lệ antd-only: một mục `EXCEPTIONS` `{module, glob, adr}` cho `@xyflow/react` trong allowlist của
  `antd-only.test.ts` (studio-skeleton/03 đổi guard thành allowlist) và override ESLint.

## Ngoài phạm vi

| Việc                                                                                                                                                                                            | Vì sao                                                                                                                                                                                                                                                                                              | Chủ                                                                      |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Danh sách Quy trình và điều hướng `/studio/*`                                                                                                                                                   | Khung và điều hướng Studio                                                                                                                                                                                                                                                                          | `studio-skeleton`                                                        |
| Sổ đăng ký loại bước, API `node-types`, `/expressions/check`, `draft/scope`, bộ dựng mẫu                                                                                                        | Loại bước là mã nền tảng (ADR-0112 (Accepted))                                                                                                                                                                                                                                                      | `workflow-nodes`                                                         |
| Tài liệu `dw.workflow/v1` (cây Bước), bộ kiểm khi gửi kiểm định và bảng mã `wf.*`, máy chạy của Quy trình                                                                                       | Hợp đồng và máy chạy của Quy trình                                                                                                                                                                                                                                                                  | `workflow-engine`                                                        |
| Route `.../test-runs`, quyền và chế độ của chạy mô phỏng                                                                                                                                        | Hợp đồng duy nhất của route (workflow-triggers:R2.3; DO-26.1)                                                                                                                                                                                                                                       | `workflow-triggers`                                                      |
| Route tạo bản Nháp `POST /api/v1/studio/artifacts/{id}/draft` và mã 409 của nó                                                                                                                  | Một phiên bản chưa phát hành mỗi thành phần (tenant-config:R2.20, tenant-config:R2.21)                                                                                                                                                                                                              | `tenant-config`                                                          |
| Thư viện biểu đồ cho dashboard và báo cáo                                                                                                                                                       | Đạt 23/10/2026: không thư viện biểu đồ nào ở v1 (DO-42); báo cáo đi qua API tổng hợp của nền tảng ở W3 (ADR-0127 (Accepted)), và một thư viện biểu đồ cần ADR ngoại lệ riêng theo ADR-0101 (Accepted) quyết 6                                                                                       | không làm ở v1                                                           |
| W2: nhãn Chặng trên Bước, một thuộc tính của Bước trong `dw.workflow/v1` phủ các Bước liền nhau của một chuỗi, mà Sơ đồ và Dạng danh sách đọc để nhóm và thu gọn, không mang nghĩa chạy (YC102) | ADR-0126 (Accepted); trình biên dịch không đọc nhãn, nên hai tài liệu chỉ khác nhãn biên dịch ra cùng đồ thị                                                                                                                                                                                        | đợt sau (W2, `workflow-builder-ui`); `workflow-engine`                   |
| W2: ngữ pháp của `logic.map` (khung "Lặp qua danh sách") và làn "Hết hạn" của Bước phê duyệt, trên cùng năm khối của R1.5; Tag phiên bản ghim, báo lệch và nút Mở của thẻ Quy trình con         | Bậc C của V4.26 (Đạt, 24/10/2026): các Loại bước và làn đó đến ở W2; thẻ Quy trình con vào ngữ pháp W1 (R1.5; V4.33), còn phiên bản ghim của nó nằm trong closure của phiên bản, chưa route nào của W1 đưa cho Sơ đồ, và lệch là của agent-lifecycle                                                | đợt sau (W2, `workflow-builder-ui`); `workflow-nodes`, `agent-lifecycle` |
| Màn "Lịch sử chạy" và `run_steps`                                                                                                                                                               | Đọc từ Postgres dưới RLS (ADR-0122 (Accepted))                                                                                                                                                                                                                                                      | `telemetry-and-audit`                                                    |
| Vòng đời và màn duyệt phát hành: route, quyền, kết quả cổng, chi phí ước tính và hai phiên bản đưa vào để so; màn đó dùng Sơ đồ chỉ đọc và lớp phần khác của spec này (R3.16-R3.20)             | Giai đoạn và cổng phát hành (ADR-0120 (Accepted)); màn duyệt W1 là `.claude/plans/studio/agent-lifecycle/issues/07-man-duyet-phat-hanh.md` (V4.37)                                                                                                                                                  | `agent-lifecycle`                                                        |
| Biểu mẫu bản ghi                                                                                                                                                                                | Thuộc trình bày của đối tượng                                                                                                                                                                                                                                                                       | `custom-objects`                                                         |
| Mở một lượt chạy bất kỳ từ Lịch sử chạy trên Sơ đồ (lượt `live`, lượt của Trình kích hoạt); W1 vẽ trên Sơ đồ lượt mô phỏng chạy từ builder (R3.11, R3.12)                                       | B7b-nodes workflow-builder-ui 09; màn Lịch sử chạy của W1 là của telemetry-and-audit                                                                                                                                                                                                                | đợt sau (W2, `workflow-builder-ui`); `telemetry-and-audit`               |
| Trang Phiên bản: so sánh hai phiên bản bất kỳ, khôi phục một phiên bản thành Nháp                                                                                                               | B7b-nodes workflow-builder-ui 10; W1 chỉ so một phiên bản với bản Đang dùng, cho màn duyệt phát hành (R3.16-R3.20; V4.37)                                                                                                                                                                           | đợt sau (W2, `workflow-builder-ui`)                                      |
| Trình soạn schema không cần code, chọn người duyệt                                                                                                                                              | B7b-nodes workflow-builder-ui 11                                                                                                                                                                                                                                                                    | đợt sau (W2, `workflow-builder-ui`)                                      |
| Trợ lý dựng Quy trình bằng AI                                                                                                                                                                   | B7b-nodes workflow-builder-ui 12                                                                                                                                                                                                                                                                    | đợt sau (W3, `workflow-builder-ui`)                                      |
| Chuyển động ngoài antd                                                                                                                                                                          | Quyết định sau, một ADR thư viện và bộ từ vựng chuyển động ghi cùng theme (Đạt, V4.29); tới lúc đó Sơ đồ chỉ dùng chuyển động antd có sẵn theo token `motion*` của theme, tắt khi giảm chuyển động (ui-quality.md §12)                                                                              | đợt sau (chưa xếp đợt, Đạt quyết), `workflow-builder-ui`                 |
| Chép giao diện Dify, mã Windmill hay n8n, hay mẫu Workflow Editor của React Flow Pro                                                                                                            | Giấy phép của Dify nói thiết kế tương tác có bằng sáng chế kiểu dáng; frontend của Windmill là AGPLv3, n8n là Sustainable Use License; giấy phép Pro cấm phân phối lại mẫu (V4.24, V4.25); đặc tả OpenFlow của Windmill (Apache-2.0) và luồng của Power Automate chỉ là danh sách kiểm cho ngữ pháp | không làm                                                                |

## Màn hình

- `/studio/workflows/[id]/builder` (người giữ `studio.workflows.edit`): bảng Loại bước bên trái từ `lg`, kéo vào ô;
  Sơ đồ có cấu trúc trên xuống dưới, mỗi đường nối có ô "+" và mỗi làn trống có ô "Thêm Bước", mỗi ô mở Popover bảng
  chọn; cấu hình của Bước trong Drawer (Form sinh từ `config_schema`, tab "Khi lỗi"); menu "…" của Bước có Thêm sau, Di
  chuyển…, Xóa, Sao chép tham chiếu; Ctrl+K "Đi tới Bước"; khung chứa thu gọn được; nút thu phóng là antd Button; huy
  hiệu ghi công React Flow ở góc dưới trái để Drawer không che. Trạng thái: xem và sửa Nháp, tự lưu ("Đang lưu… / Đã
  lưu / Lưu thất bại"), huy hiệu lỗi trên Bước, xóa có thông báo Hoàn tác, chạy mô phỏng (`simulate`) với một lựa chọn
  duyệt hay từ chối cho mỗi Bước phê duyệt, nút Gửi kiểm định (khóa có lý do). Dưới `md` và ở 320 px: Dạng danh sách là
  trình dựng chính, không cuộn ngang; ở mọi độ rộng nó là đường cho trình đọc màn hình, đồng bộ với Sơ đồ vì là cùng cây
  tài liệu. Giai đoạn vòng đời hiện ở đầu trang (đọc từ `agent-lifecycle`); trang không tự phát hành. Khi Quy trình không
  có bản Nháp hay Bản ứng viên: phiên bản Đang dùng, hay phiên bản mới nhất khi không có bản Đang dùng, chỉ đọc kèm nút
  Tạo bản Nháp. Khi Quy trình có Bản ứng viên đang chờ: Sơ đồ và cấu hình chỉ đọc, tự lưu tắt, một thông báo nêu "rút
  bản đang chờ về Nháp để sửa" kèm nút Rút về Nháp; trang chỉ gọi lệnh rút khi người dựng bấm nút đó.
- Màn lượt chạy của một lượt mô phỏng (người giữ `studio.workflows.test` đã xin lượt đó, mở từ id lượt mà route
  `test-runs` trả; V4.41): cùng Sơ đồ, chỉ đọc; trạng thái, thời gian, token và chi phí từng Bước bằng chữ cùng biểu
  tượng; đường đã đi được tô, Bước chưa chạy ghi "Chưa chạy"; chọn lần lặp của mỗi Bước vòng lặp, mọi làn của một Bước
  song song vẽ cùng lúc; trường người xem không đọc được hiện "Đã ẩn".
- Sơ đồ chỉ đọc có lớp phần khác (trong màn duyệt phát hành của agent-lifecycle/07): cùng Sơ đồ, chỉ đọc; thẻ "Mới" và
  "Đã sửa" bằng chữ cùng biểu tượng; danh sách "Bước đã xóa" cạnh Sơ đồ; chọn một thẻ "Đã sửa" mở Drawer chỉ đọc nêu
  trường đã khác, trước và sau; đầu Sơ đồ nêu các phần ngoài cây Bước đã khác; chưa có bản Đang dùng thì mọi thẻ mang
  "Mới"; không so được thì một thông báo "Không so được với bản Đang dùng" thay mọi nhãn.

## Kiểm soát

| #    | Kiểm soát                                                                                                                            | Yêu cầu                    | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------ | -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BU1  | `@xyflow/react` chỉ ở `apps/web`, chỉ tệp dưới glob canvas import, không thư viện bố cục nào                                         | R1.1, R1.2                 | Import `@xyflow/react` từ `app/approvals` → `antd-only.test.ts` đỏ; `@dw/ui` khai báo gói → đỏ; `apps/web` khai `@dagrejs/dagre` → đỏ, vì không mục `EXCEPTIONS` nào nhận nó; lockfile có thêm một `zustand` 5.x → test lockfile đỏ                                                                                                                                                                                                                                                                                                           |
| BU2  | Không tính Biểu thức trong trình duyệt                                                                                               | R3.2                       | Thư viện CEL có mặt trong bundle route builder → test manifest đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| BU3  | Nút Gửi kiểm định khóa có lý do; máy chủ vẫn từ chối; builder không tự phát hành                                                     | R3.3, R3.5                 | Gửi kiểm định một Nháp lỗi qua API → 422; không đường nào trong builder gọi phát hành                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| BU4  | Tự lưu dùng `If-Match`                                                                                                               | R2.4                       | Hai tab → 412, nội dung đang gõ giữ nguyên                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| BU5  | Chạy mô phỏng từ builder chỉ gửi `simulate`; route vẫn từ chối `live` và `test` (workflow-triggers:R2.2, workflow-triggers:R2.6)     | R3.6                       | Test thành phần: builder không gửi chế độ nào khác `simulate`; gọi thẳng route với `live` → 422; bỏ giới hạn chế độ ở builder → test thành phần đỏ                                                                                                                                                                                                                                                                                                                                                                                            |
| BU6  | Kết quả Bước chạy che theo bảo mật trường, ở mọi lần lặp và mọi làn                                                                  | R3.7                       | Người không đọc được `phone` không thấy số trong DOM và trong mạng, kể cả ở lần lặp thứ hai của một khung vòng lặp và ở một làn song song; gỡ che → test đỏ                                                                                                                                                                                                                                                                                                                                                                                   |
| BU7  | Mọi thao tác chuột có đường bàn phím theo thứ tự tài liệu; xóa có Hoàn tác                                                           | R2.5, R2.11                | Playwright dựng F5 chỉ bằng bàn phím: đặt Bước vào ô của chuỗi, của làn và của thân vòng lặp, dời một Bước sang làn khác, xóa một khung chứa rồi hoàn tác, mở và đóng cấu hình, Ctrl+K; phím mũi tên không bao giờ dời node; thông báo xóa nêu tên mọi Bước bị xóa và Hoàn tác trả đúng tài liệu cũ; bỏ đường bàn phím của một ô hay bỏ Hoàn tác → test đỏ                                                                                                                                                                                    |
| BU8  | Không trạng thái hiển thị nào vào tài liệu (vị trí, đường nối, thu gọn); đặt vào ô là một thao tác cây                               | R1.4, R1.7                 | Kéo một thẻ Bước ra chỗ trống → tài liệu và Mã băm nội dung không đổi, thẻ về chỗ cũ; kéo từ một Nhánh ra → không đường nối nào; thu gọn một khung → tài liệu và Mã băm nội dung không đổi; bật kéo hay nối node, hay ghi trạng thái thu gọn vào tài liệu → test thành phần đỏ                                                                                                                                                                                                                                                                |
| BU9  | Bản ứng viên đang chờ thì builder chỉ đọc, chỉ rút về Nháp khi người dựng chọn                                                       | R3.10                      | Test thành phần: Quy trình có Bản ứng viên ở `awaiting_approval` → Sơ đồ và biểu mẫu chỉ đọc, trang nêu "rút bản đang chờ về Nháp để sửa", không lời gọi `PUT .../draft` hay `POST .../draft`, không lời gọi `withdraw` khi chưa bấm Rút về Nháp; bấm → đúng một lời gọi `withdraw`; bỏ trạng thái chỉ đọc → test đỏ                                                                                                                                                                                                                          |
| BU10 | Phím chỉ tác động lên Sơ đồ khi Sơ đồ có focus; không phím mặc định nào của thư viện; bỏ qua `isComposing`                           | R2.7, R2.8                 | Chọn một Bước, rồi nhấn Space, Shift hay Backspace khi focus ở một nút ngoài Sơ đồ (nơi phím mặc định của thư viện vẫn chạy; trong ô nhập thư viện chỉ bỏ qua Space và Backspace) và trong một ô nhập ngoài Sơ đồ → Sơ đồ không kéo, chọn hay xóa gì, tài liệu không đổi; gõ Telex trong ô tìm của Ctrl+K → không phím tắt nào chạy; đặt lại `deleteKeyCode` mặc định hay bỏ kiểm `isComposing` → test đỏ                                                                                                                                     |
| BU11 | Dạng danh sách là cây tài liệu, mang cấp và vị trí cho trình đọc màn hình                                                            | R2.6                       | Test thành phần trên F2: mỗi node của `Tree` có `aria-level`, `aria-posinset`, `aria-setsize` đúng cây; một Bước thêm trên Sơ đồ có mặt trong `Tree` ở đúng cấp và vị trí; bỏ một thuộc tính hay dựng `Tree` từ một bản sao khác của tài liệu → test đỏ                                                                                                                                                                                                                                                                                       |
| BU12 | Tên truy cập tiếng Việt cho mọi điều khiển, không chuỗi mặc định tiếng Anh; báo mỗi thao tác                                         | R2.9, R2.10                | Test thành phần: không phần tử nào của Sơ đồ có `aria-label` bắt đầu bằng `Edge from`; ô "+" có tên "Thêm Bước sau «tên»" với tên của Bước đứng trước; thêm, dời, xóa một Bước → vùng `aria-live` nêu tên Bước; bỏ `ariaLabel` của một đường nối hay bỏ lời báo → test đỏ                                                                                                                                                                                                                                                                     |
| BU13 | Bố cục tất định; chèn không dời phần đứng trước và không đổi thứ tự                                                                  | R1.6                       | Property test trên cây ngẫu nhiên và F1-F9: cùng tài liệu → cùng tọa độ; chèn một Bước → chỉ các Bước đi sau chỗ chèn trong làn đó và trong các chuỗi bao ngoài đổi tọa độ, và chỉ theo chiều dọc; chèn một Bước có làn → không Bước nào đứng trước chỗ chèn đổi tọa độ dọc; mọi lần chèn giữ thứ tự dọc và thứ tự làn, không hai thẻ chồng nhau; đổi bố cục để xếp làn theo độ rộng hay theo thứ hạng, hay cho `workflow-layout.ts` import một gói → test đỏ                                                                                 |
| BU14 | Màu, biểu tượng, cỡ thẻ và kiểu đường nối chỉ từ bộ từ vựng của theme; không bao giờ chỉ màu                                         | R1.5, R1.8, R1.9           | Một màu literal (`#…`, `rgb(`, `hsl(`) dưới glob canvas, trong `workflow-layout.ts` hay thành phần builder → test đỏ; một màu nhóm dưới 3:1 trên nền thẻ ở chế độ sáng hay tối → `theme-contrast.test.ts` đỏ; một huy hiệu hay nhãn làn chỉ có màu, không chữ → test đỏ                                                                                                                                                                                                                                                                       |
| BU15 | Bản Nháp mới chỉ khi người dựng bấm "Tạo bản Nháp"; một 409 không bao giờ thành lời gọi thứ hai                                      | R3.13, R3.14, R3.15        | Test thành phần: mở builder của Quy trình chỉ có bản Đang dùng → không lời gọi `POST .../draft`; bấm → đúng một lời gọi, rồi trang mở bản Nháp với ETag của nó; route giả trả 409 `candidate_pending` → trạng thái chỉ đọc của R3.10, không lời gọi thứ hai; 409 `draft_exists` → mở bản Nháp đang có, không lời gọi thứ hai; tạo bản Nháp lúc mở trang → test đỏ                                                                                                                                                                             |
| BU16 | Màn lượt chạy chỉ đọc, gắn Bước chạy theo lần lặp                                                                                    | R3.11, R3.12               | Test thành phần trên lượt mô phỏng của F3: màn lượt chạy không gọi lưu Nháp hay thao tác cây nào; chọn lần lặp 2 → mỗi Bước của thân hiện Bước chạy có `iteration_path` của lần 2; bỏ lọc theo `iteration_path`, hay cho sửa trên màn lượt chạy → test đỏ (bỏ lọc theo `lane_path` không làm test nào đỏ được, vì id Bước là duy nhất trong cây, workflow-engine:R1.1)                                                                                                                                                                        |
| BU17 | Lớp phần khác không bao giờ im lặng: mọi phần khác đều có nhãn, kể cả đổi chỗ, dời làn và phần ngoài cây Bước; không so được thì nói | R3.16, R3.17, R3.19, R3.20 | Test thành phần trên F1 và một bản sửa của nó (thêm một Bước, xóa một Bước, đổi ngưỡng của một `logic.switch`, đổi chỗ hai Bước trong một làn, dời một Bước sang làn khác, đổi `limits.max_steps`) → đúng một thẻ "Mới", "Đã sửa" ở Bước đổi ngưỡng, ở cả hai Bước đổi chỗ và ở Bước dời, một mục "Bước đã xóa", và `limits` ở đầu Sơ đồ; bản Đang dùng đọc lỗi → "Không so được với bản Đang dùng", không nhãn nào; bỏ so thứ tự trong làn, bỏ so phần ngoài cây Bước, hay cho lỗi đọc thành "không phần khác" hoặc thành cây rỗng → test đỏ |

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát.
- Playwright chạy ở 320 px và ở một dự án múi giờ khác, kể cả lượt dựng F5 chỉ bằng bàn phím.
- `pnpm -C apps/web test` và `pnpm -C apps/web build` xanh; `antd-only.test.ts` xanh với một mục `EXCEPTIONS` có ADR.
- Số đo của spike (ticket 01) ghi ở ADR-0101 (Accepted); property test bố cục xanh trên F1-F9.

## Phụ thuộc

- `studio-skeleton`: seam web, guard antd-only thành allowlist `{module, glob, adr}` mà spec này chỉ thêm một mục
  `EXCEPTIONS` cho `@xyflow/react`, điều hướng `/studio/*`, khóa thông điệp tiếng Việt
  (`.claude/plans/studio/studio-skeleton/issues/03-seam-web-va-allowlist-antd.md`).
- `workflow-nodes`: tính Biểu thức chỉ ở máy chủ (workflow-nodes:R3.5), danh mục Loại bước với Nhánh ra, nhãn tiếng
  Việt và lý do khóa, từ đó Sơ đồ biết mỗi Bước mang những làn nào (workflow-nodes:R1.2), phạm vi biến trội và
  `draft/scope` (workflow-nodes:R3.2); `.claude/plans/studio/workflow-nodes/issues/02-so-dang-ky-buoc-va-mau-chuoi.md`,
  `.claude/plans/studio/workflow-nodes/issues/03-pham-vi-bien-va-buoc-logic.md`. Các Loại bước của bậc B (Bước song
  song, Bước vòng lặp có trần, Thoát vòng lặp, phê duyệt với nhiều người duyệt bắt buộc; workflow-nodes:R10.1,
  workflow-nodes:R11.2, workflow-nodes:R12.1) và Bước Quy trình con (`flow.subworkflow@1`, cấu hình mang `api_name` của
  Quy trình được gọi; workflow-nodes:R13.1, workflow-nodes:R13.2; V4.33) do workflow-nodes đăng ký sau đường găng YC94
  (V4.26): ngữ pháp của R1.5 không chờ chúng, bảng Loại bước chỉ đưa chúng khi danh mục có.
- `workflow-engine` (batch 2, đang viết song song): tài liệu `dw.workflow/v1` là cây Bước, mỗi Nhánh ra một làn lồng
  (workflow-engine:R1.1; ADR-0112 (Accepted) quyết 1), và mô hình tài liệu từ chối `edges[]` hay mọi trường vị trí, nên
  một vị trí lọt khỏi trang builder vẫn không vào được tài liệu (workflow-engine:R1.8); bảng mã `wf.*` mà trang builder
  gắn lỗi về Bước (workflow-engine:R2.11), kể cả mã từ chối `flow.stop` và làn lỗi kết thúc trong một làn song song
  (workflow-engine:R2.15), mà Sơ đồ chỉ hiện; `RunRequestService`, cửa của mọi lượt chạy, chạy bộ kiểm khi gửi kiểm
  định trên nội dung nháp của một yêu cầu `simulate` và từ chối khi nội dung trượt (workflow-engine:R3.11); id của một
  Bước giữ nguyên qua các phiên bản (ADR-0112 (Accepted) quyết 1), nên lớp phần khác so được theo id (R3.16).
- `workflow-triggers`: route `.../test-runs` và lần kiểm quyền `studio.workflows.test` của nó (khóa do workflow-engine/01
  đăng ký vào danh mục quyền, H-19), chế độ được nhận, việc nhận phiên bản
  `draft` ở chế độ `simulate` sau khi bộ kiểm khi gửi kiểm định đạt trên nội dung nháp (422 với mã `wf.*` khi không
  đạt, ADR-0112 (Accepted) quyết 3), và quyết định giả lập cho mỗi Bước phê duyệt của chính nội dung đó trong thân
  (workflow-triggers:R2.2, workflow-triggers:R2.3, workflow-triggers:R2.6, workflow-triggers:R2.7,
  workflow-triggers:R2.8, workflow-triggers:R2.9;
  `.claude/plans/studio/workflow-triggers/issues/01-so-kich-hoat-chay-tay-va-danh-tinh.md`).
- `workflow-nodes`: Bước phê duyệt của lượt mô phỏng đi theo quyết định giả lập, không chờ người
  (workflow-nodes:R9.9).
- `tenant-config`: Chế độ chạy do máy chủ đặt (tenant-config:R4.1), Mô phỏng chặn tác động
  (tenant-config:R5.1), bản kê của lượt mô phỏng trên bản Nháp ghim mã băm tạm của nội dung nháp
  (tenant-config:R6.1); Nháp với ETag; một phiên bản chưa phát hành mỗi thành phần, nên không có bản Nháp nào khi một
  Bản ứng viên còn chờ (tenant-config:R2.20, tenant-config:R2.22); route tạo bản Nháp
  `POST /api/v1/studio/artifacts/{id}/draft` với 409 `candidate_pending` và `draft_exists` (tenant-config:R2.21,
  tenant-config:R2.22, tenant-config:R2.23).
- `telemetry-and-audit` (batch 2): `run_steps` cho kết quả Bước và màn lượt chạy của lượt mô phỏng, đọc qua
  `GET /api/v1/runs/{run_id}/steps` (telemetry-and-audit:R4.2), mỗi Bước chạy mang `lane_path` và `iteration_path`
  (telemetry-and-audit:R3.7; `.claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md`) và `port`,
  Nhánh ra mà Bước đã đi (V4.36); người giữ `studio.workflows.test` đọc được Bước chạy và chi tiết của lượt `simulate`
  mà chính mình xin, lượt `live` vẫn đòi `runs.read`, còn lượt của người khác, lượt `live` khi không giữ `runs.read` và
  lượt của công ty khác đều trả 404 (telemetry-and-audit:R4.4, telemetry-and-audit:R4.5; V4.41); `/runs` không đổi ở
  W1, nên người dựng tới lượt của mình qua id mà route `test-runs` trả (H-17).
- `agent-lifecycle` (batch 2): giai đoạn vòng đời và cổng phát hành mà builder không tự gọi; route gửi kiểm định
  nhận `If-Match` là ETag của Nháp, 412 khi lệch và 428 khi thiếu (agent-lifecycle:R2.12, agent-lifecycle:R2.13); lệnh
  rút Bản ứng viên về Nháp `POST .../withdraw` (agent-lifecycle:R2.4), mà trang chỉ gọi khi người dựng chọn rút (R3.10),
  và 409 `candidate_exists` cho lần gửi thua khi hai tab cùng gửi bản Nháp duy nhất (agent-lifecycle:R1.3), sau đó trang
  vào trạng thái của R3.10.
- Kiểm lại khi: `workflow-nodes` đổi hình API `node-types`/`/expressions/check`/`draft/scope`, hay đổi Nhánh ra hoặc
  nhãn của một Loại bước → kiểm lại 01-04; `workflow-engine` đổi hợp đồng `dw.workflow/v1`, nhất là hình cây (làn theo
  Nhánh ra, làn lỗi, thân vòng lặp), → R1.4-R1.7, R2.5, R2.6, ticket 02, 04; `workflow-triggers` đổi route
  `.../test-runs` hay hình của quyết định giả lập → kiểm lại 03; `workflow-triggers` hay `tenant-config` thôi nhận bản
  Nháp ở chế độ `simulate`, hay `RunRequestService` thôi kiểm nội dung nháp trước khi xin lượt (workflow-engine:R3.11) →
  R3.6, R3.8, ticket 03; `agent-lifecycle` đổi điều kiện ghi của route gửi kiểm định → R3.9, ticket 03;
  `agent-lifecycle` đổi lệnh rút hay mã của lần gửi song song, hay `tenant-config` thôi giữ một phiên bản chưa phát hành
  mỗi thành phần → R3.10, BU9, ticket 03; `tenant-config` đổi route tạo bản Nháp hay mã 409 của nó → R3.13, R3.14,
  R3.15, BU15, ticket 03; `telemetry-and-audit` đổi cách Bước chạy mang `lane_path` hay `iteration_path` → R3.12, BU16,
  ticket 03; `telemetry-and-audit` đổi quyền đọc Bước chạy của lượt mô phỏng (V4.41) hay cột `port` → R3.11, ticket 03;
  agent-lifecycle/07 đổi cách đưa hai phiên bản để so, hay đổi bản để so khác bản Đang dùng → R3.16-R3.20, BU17, ticket
  03; `workflow-nodes` đổi cấu hình hay đầu ra của `flow.subworkflow@1` → R1.5, ticket 04; spike của ticket 01 thấy mô-đun bố cục trượt F1-F9 → sửa mô-đun, R1.6 và BU13 giữ nguyên, không đưa dagre trở lại
  (V4.25); Đạt đổi bộ từ vựng khi duyệt → chỉ theme đổi, R1.9 và BU14 giữ nguyên; W2 mở chế độ `test` → R3.6, R3.8, BU5,
  ticket 03.

## Câu hỏi còn mở

## Quyết định

- 23/10/2026 (agent, tạm theo khuyến nghị (a)): DO-42 — nhận ADR-0101 (Accepted); Sơ đồ `@xyflow/react`
  cùng dagre là ngoại lệ, vị trí không lưu; `antd-only.test.ts` thành allowlist; giữ huy hiệu React
  Flow; ngoại lệ thư viện biểu đồ xét trước v1 GA. Hỏi: DO-42. Sửa: R1. Nếu sai thì: dựng canvas SVG
  riêng hoặc một trình dựng biểu mẫu tuyến tính.
- 23/10/2026 (agent, tạm theo khuyến nghị (a)): DO-03 — khối số ADR 0100-0199 do một lượt gán với kiểm
  trùng CI; mã si-platform port theo thỏa thuận viết tay, ghim commit, header xuất xứ, không đồng bộ.
  Hỏi: DO-03. Sửa: Phụ thuộc. Nếu sai thì: re-derive mọi mô-đun định port thay vì port.
- 23/10/2026 (agent, tạm theo khuyến nghị (a)): DO-26 — chế độ `test` chặn ghi như `simulate` trong P1;
  scratch theo lượt chạy ở v1.5. Hỏi: DO-26. Sửa: R3.6. Nếu sai thì: `test` ghi vào scratch theo lượt
  chạy ngay ở P1.
- 23/10/2026 (agent, tạm): Học theo bố cục ba cột cấu hình Bước của phân tích chang.fpt.net
  (config-chang.md màn 4, Input/Setup/Output và chèn `{{ nodeId.var }}`): trang builder dùng ba cột
  bảng Loại bước / Sơ đồ / cấu hình và một Chọn biến chèn đường dẫn có kiểu (YC39), nhưng khác họ ở chỗ
  Biểu thức là CEL kiểm kiểu khi phát hành (ADR-0114 (Accepted)), không phải chuỗi mẫu không kiểm. Đây
  là mẫu học được, không phải mã của họ. Sửa: R2.1, R3.1.
- 23/10/2026 (Đạt): DO-42 (a), DO-42.1 (a) và ADR-0101 (Accepted): cho phép `@xyflow/react` 12.12.0 và
  `@dagrejs/dagre` 3.1.1 trong cùng một ngoại lệ, ghim chính xác, một glob canvas
  `apps/web/app/studio/**/canvas/**`; hàm bố cục dời vào thư mục canvas để `workflow-graph.ts` không import
  gói nào; `antd-only.test.ts` thành allowlist `{module, glob, adr}` ở studio-skeleton/03, spec này chỉ thêm
  hai mục `EXCEPTIONS`; `CLAUDE.md` "Web UI" sửa cùng lúc; không thư viện biểu đồ nào ở v1. Hỏi: Q1. Sửa: R1.1,
  R1.4, Trong phạm vi, Ngoài phạm vi, ticket 01, 02.
- 23/10/2026 (Đạt): DO-42.2 (a): giữ huy hiệu ghi công React Flow, không mua React Flow Pro, không ẩn huy
  hiệu. Hỏi: Q1. Sửa: ticket 01.
- 23/10/2026 (Đạt): DO-03.1 (a): giữ khối số ADR 0100-0199 và cách gán, luật `adr` của `scripts/check_plans.py`
  chạy ở một bước CI chặn. Hỏi: Q2.
- 23/10/2026 (Đạt): DO-03.2 (a): mã si-platform port theo thỏa thuận viết với chủ mã: ghim commit mỗi lần,
  dòng đầu `Ported from si-platform`, không đồng bộ; chưa có thỏa thuận trước P1 thì viết lại theo cùng
  vector. Hỏi: Q2.
- 23/10/2026 (Đạt): DO-26.1 (A): W1 chỉ chạy thử `simulate`; route chạy thử của workflow-triggers trả 422
  với `live` và với `test` tới W2, và là hợp đồng duy nhất của quyền chạy thử; R3.6 và BU5 dẫn chiếu nó
  (B:workflow-builder-ui:R3.6~workflow-triggers:R2.3). Sửa: R3.6, BU5, Phụ thuộc, ticket 03.
- 23/10/2026 (Đạt): DO-57 (a): giao diện chỉ tiếng Việt qua khóa thông điệp; `ariaLabelConfig` của Sơ đồ
  lấy từ khóa thông điệp. Sửa: ticket 02.
- 23/10/2026 (Đạt): ADR-0108 (Accepted): route kiểm biểu thức theo dạng sub-resource
  `/api/v1/studio/expressions/check`. Sửa: R3.2, Ngoài phạm vi, Phụ thuộc, ticket 03.
- 23/10/2026 (agent, tạm): sửa phát hiện G:CONTEXT.md#submit~workflow-builder-ui:BU3: "nút phát hành" và
  "bộ kiểm phát hành" thành "nút Gửi kiểm định" và "bộ kiểm khi gửi kiểm định". Sửa: BU3, Ngoài phạm vi,
  Danh sách ticket.
- 23/10/2026 (agent, tạm): sửa phát hiện I:workflow-builder-ui:phụ-thuộc~workflow-triggers:R2.2: cửa chạy
  thử dẫn workflow-triggers:R2.2, workflow-triggers:R2.3, workflow-triggers:R2.6 thay tenant-config:R4.1, và
  Phụ thuộc nêu workflow-triggers.
  Sửa: Phụ thuộc, ticket 03.
- 24/10/2026 (Đạt): N2: biểu mẫu chạy mô phỏng đòi người thử chọn duyệt hay từ chối cho mỗi Bước phê duyệt và gửi
  các lựa chọn đó trong thân yêu cầu, nên không Bước phê duyệt nào của lượt mô phỏng chờ người quyết; dòng này thay
  câu "người duyệt trong lượt chạy thử là chính người thử" của ticket 03. Sửa: R3.8, Trong phạm vi, Màn hình, Phụ
  thuộc, ticket 03.
- 24/10/2026 (Đạt): lượt chế độ `simulate` gọi là chạy mô phỏng, "Chạy thử" chỉ gọi chế độ `test`
  (G:CONTEXT.md#run-mode~workflow-triggers:R2.3). Sửa: đoạn mở đầu, R3, R3.6, R3.7, Ngoài phạm vi, Màn hình, BU5.
- 24/10/2026 (Đạt): Biểu thức được kiểm kiểu lúc gửi kiểm định, không "khi phát hành"; dòng này thay cách gọi của
  dòng 23/10/2026 về bố cục ba cột (G:requirements.md:YC40~workflow-builder-ui:quyết-định). Sửa: Quyết định.
- 24/10/2026 (Đạt): N5 và ADR-0126 (Accepted): nhãn Chặng trên Bước, chỉ để nhóm và thu gọn Sơ đồ, là W2 của spec
  này (YC102). N10: báo cáo đi qua API tổng hợp của nền tảng ở W3 (ADR-0127 (Accepted)), và một thư viện biểu đồ cần
  ADR ngoại lệ riêng theo ADR-0101 (Accepted) quyết 6. Sửa: Ngoài phạm vi.
- 24/10/2026 (Đạt): route `.../versions/{version_id}/test-runs` ở chế độ `simulate` nhận cả phiên bản `draft`, bản kê
  ghim mã băm tạm của nội dung nháp lúc nhận và tập Bước phê duyệt đọc từ đúng nội dung đó, nên builder chạy mô phỏng
  chính bản Nháp đang mở và đòi lựa chọn cho mỗi Bước phê duyệt của Nháp; nháp đổi trước khi lượt mô phỏng xong thì
  lần tiếp tục bị từ chối `incompatible_resume` (ADR-0109 (Accepted) quyết 8)
  (B:workflow-builder-ui:R3.6~workflow-triggers:R2.8). Sửa: R3.6, R3.8, Phụ thuộc, ticket 03.
- 24/10/2026 (agent, tạm): hoàn tất V4.4: route chạy mô phỏng chạy bộ kiểm một lượt của lúc gửi kiểm định trên nội
  dung nháp trước khi xin lượt và trả 422 với mã `wf.*` khi có lỗi (workflow-triggers:R2.9; ADR-0112 (Accepted)
  quyết 3; YC40), nên trang builder gắn các lỗi đó về Bước như R3.4. Sửa: R3.6, Phụ thuộc, ticket 03. Nếu sai thì:
  route nhận nội dung nháp có lỗi và lượt mô phỏng hỏng khi chạy, trang chỉ hiện lỗi của lượt chạy.
- 24/10/2026 (agent, tạm): route gửi kiểm định của agent-lifecycle nhận `If-Match` là ETag của Nháp, 412
  `precondition_failed` với `stale_version` khi lệch (V4.6) và 428 khi thiếu (agent-lifecycle:R2.12,
  agent-lifecycle:R2.13; ADR-0108 (Accepted) quyết 3; ADR-0109 (Accepted) quyết 2; app-standards:R3.2,
  app-standards:R3.3), nên nút Gửi kiểm định gửi ETag của Nháp đã đọc như tự lưu. Sửa: R3.9, Phụ thuộc, ticket 03.
  Nếu sai thì: route không mang điều kiện ghi, và R3.9 rút.
- 24/10/2026 (agent, tạm): bộ kiểm khi gửi kiểm định trên bản Nháp chạy ở `RunRequestService`, cửa duy nhất của mọi
  lượt chạy, bên gọi nào xin cũng vậy (workflow-engine:R3.11; ADR-0109 (Accepted) quyết 6; ADR-0113 (Accepted)
  quyết 1; failure-modes #5), không ở route `.../test-runs`; route trả lần từ chối đó thành 422 với các mã `wf.*`
  (workflow-triggers:R2.9), nên trang builder vẫn nhận đúng 422 đó và gắn lỗi về Bước như R3.4. Dòng này thay phần
  "route chạy mô phỏng chạy bộ kiểm một lượt của lúc gửi kiểm định trên nội dung nháp trước khi xin lượt" của dòng
  hoàn tất V4.4 cùng ngày. Sửa: R3.6, Phụ thuộc. Nếu sai thì: route nộp kết quả kiểm kèm mã băm của nội dung đã kiểm
  cho `RunRequestService`, và R3.6 dẫn lại workflow-triggers:R2.9 cho lần kiểm.
- 24/10/2026 (Đạt): V4.17: mỗi thành phần có tối đa một phiên bản chưa phát hành (bản Nháp hay Bản ứng viên); tạo bản
  Nháp mới khi đang có Bản ứng viên → 409 `conflict` với `details.reason_code` `candidate_pending`, muốn sửa thì rút Bản
  ứng viên về Nháp, nên trang builder hiện Bản ứng viên chỉ đọc, nêu "rút bản đang chờ về Nháp để sửa" và chỉ rút khi
  người dựng chọn. Sửa: R3.10, Trong phạm vi, Màn hình, BU9, Phụ thuộc, ticket 03.
- 24/10/2026 (Đạt): V4.24: tài liệu `dw.workflow/v1` là một cây Bước vẽ thành Sơ đồ có cấu trúc: đặt một Bước vào một
  ô ("+" trên đường nối, ô "Thêm Bước" trong làn trống, hay kéo từ bảng bên vào ô) là đã nối, thẻ Bước không kéo tự do,
  không nối dây, dời Bước là thao tác trên cây, một chiều trên xuống dưới; ngữ pháp cho mọi cấu trúc trên năm khối chung
  (chuỗi, làn, khung chứa, mũi tên quay lại, làn lỗi); thẻ Bước là antd Card cỡ cố định, luôn có chữ cùng biểu tượng;
  cấu hình trong Drawer, menu "…", Ctrl+K "Đi tới Bước", khung chứa thu gọn theo người xem, hoàn tác và làm lại, xóa có
  thông báo Hoàn tác; màn lượt chạy là cùng Sơ đồ chỉ đọc với làn và lần lặp; mô hình bàn phím và trợ năng như phản
  biện sửa (roving focus, phím mặc định của thư viện tắt, `isComposing`, tên tiếng Việt, `aria-live`, Dạng danh sách là
  cây tài liệu mang `aria-level`, `aria-posinset`, `aria-setsize` và là trình dựng chính dưới `md`); bất biến bố cục như
  phản biện sửa; học mẫu, không chép giao diện hay mã; dòng này thay phần "ba cột bảng Loại bước / Sơ đồ / cấu hình"
  của dòng 23/10/2026 học theo chang.fpt.net. Sửa: đoạn mở đầu, R1, R1.3, R1.4, R1.5, R1.6, R1.7, R1.8, R2, R2.1,
  R2.5, R2.6, R2.7, R2.8, R2.9, R2.10, R2.11, R3, R3.11, R3.12, Trong phạm vi, Ngoài phạm vi, Màn hình, BU6, BU7, BU8,
  BU10, BU11, BU12, BU13, BU16, Tiêu chí xong, Phụ thuộc, ticket 02, 03, 04.
- 24/10/2026 (Đạt): V4.25: Sơ đồ chỉ dùng `@xyflow/react` 12.12.0, ghim chính xác (13.0.0-next.0 là bản thử, không
  dùng), với đúng một `zustand` ≥4.5.6 trong lockfile, không 5.x; không mua React Flow Pro, huy hiệu ghi công ở góc
  dưới trái (`attributionPosition`) để Drawer không che; bỏ `@dagrejs/dagre`: vị trí do mô-đun thuần
  `apps/web/lib/workflow-layout.ts` (ngoài glob canvas, không import gì) tính từ cây theo hai bước, O(n), khung thu gọn
  đo như một thẻ, và mô-đun lỗi thì sửa mô-đun (tham khảo `flow-canvas-utils.ts` của Activepieces, MIT, có ghi công),
  không đưa dagre trở lại; AntV X6, Rete.js, bpmn-js, mẫu Workflow Editor của React Flow Pro, elkjs và FlowGram.ai bị
  loại với lý do có nguồn (ADR-0101 (Accepted)); dòng này thay phần `@dagrejs/dagre`, hàm bố cục dưới thư mục canvas và
  "hai mục `EXCEPTIONS`" của các dòng 23/10/2026 về DO-42 và DO-42.1. Sửa: đoạn mở đầu, Hiện trạng, R1.1, R1.2, Trong
  phạm vi, BU1, Tiêu chí xong, Phụ thuộc, ticket 01, 02.
- 24/10/2026 (Đạt): V4.26: W1 dài thêm khoảng 2-3 tuần để chứa bậc B (Bước song song gộp kiểu all, Bước vòng lặp có
  trần với Thoát vòng lặp, Chạy tiếp từ Bước lỗi, phê duyệt cần mọi người được giao), đi sau đường găng YC94 và không
  chặn ticket thí điểm nào; với spec này, ngữ pháp sơ đồ cho mọi cấu trúc thuộc bậc A, lõi W1, nên ticket 04 mới không
  chờ Loại bước nào của bậc B và bảng Loại bước chỉ đưa chúng khi workflow-nodes đăng ký, còn ticket 02 (thao tác cây,
  `workflow-layout.ts`) và 03 (màn lượt chạy theo làn và lần lặp) mở rộng. Sửa: đoạn mở đầu, R1, Ngoài phạm vi, Phụ
  thuộc, ticket 02, 03, 04.
- 24/10/2026 (Đạt): V4.27: bộ từ vựng hình ảnh của Sơ đồ (màu nhóm từ token của theme, ví dụ trigger xanh dương, AI
  tím, dữ liệu cyan, logic vàng, con người hồng tím, công cụ xanh lá, lỗi đỏ, mỗi màu kiểm tương phản 3:1; biểu tượng
  `@ant-design/icons`; cỡ thẻ; kiểu đường nối) do một agent dựng nháp trong spike, ghi một lần trong theme của `@dw/ui`
  để Đạt duyệt; ô nhóm không dùng sắc nhạt preset của antd (ui-quality.md §12). Sửa: Hiện trạng, R1.5, R1.9, BU14,
  ticket 01, 04.
- 24/10/2026 (Đạt): V4.29: antd vẫn là hệ component duy nhất; Studio học bố cục và cách tương tác từ các tham chiếu Đạt
  gửi (chang.fpt.net; Dify, Windmill, Activepieces và Camunda cho Sơ đồ) và đẹp hơn bằng theme antd (token màu, khoảng
  cách, bo góc, đổ bóng, trạng thái hover, skeleton), không chép nhận diện, giao diện hay mã của sản phẩm nào; một thư
  viện hỗ trợ antd mà không mang hệ component riêng vào qua ADR của nó và một mục allowlist `{module, glob, adr}`
  (CLAUDE.md, mục Web UI); chuyển động ngoài antd là quyết định sau. Sửa: đoạn mở đầu, Ngoài phạm vi, ticket 01, 04.
- 24/10/2026 (agent, tạm): áp V4.24 vào spec: bảng bên kéo vào ô có từ breakpoint `lg`, Popover của ô "+" có ở mọi độ
  rộng, cấu hình là Drawer ở mọi độ rộng, và dưới `md` Dạng danh sách là trình dựng chính; bất biến bố cục là R1.6, tách
  khỏi R1.4 để mỗi tiêu chí một phản hồi; ticket 02 dựng thao tác cây, mô-đun bố cục cho cả năm khối và mọi thẻ Bước, ô
  "+" và đường nối ở chỗ mô-đun trả, ticket 04 vẽ khung, đầu làn và nhãn của từng cấu trúc, còn màn lượt chạy ở ticket 03
  đọc `lane_path` và `iteration_path` của Bước chạy trên thẻ của ticket 02 mà không chờ ticket 04, vì một ticket chỉ bị
  chặn bởi ticket số nhỏ hơn. Sửa: R1.4, R1.6, R2.1, Màn hình, ticket 02, 03, 04. Nếu sai thì: bảng kéo có ở mọi độ rộng từ
  `md`, hay ticket 04 chờ ticket 03 và giữ phần làn và lần lặp của màn lượt chạy.
- 24/10/2026 (agent, tạm): màn lượt chạy của V4.24 ở W1 vẽ lượt mô phỏng chạy từ builder; mở một lượt bất kỳ từ Lịch
  sử chạy trên Sơ đồ (lượt `live`, lượt của Trình kích hoạt) vẫn là W2, vì màn Lịch sử chạy của W1 là của
  telemetry-and-audit. Sửa: R3.11, R3.12, Ngoài phạm vi. Nếu sai thì: R3.11 phủ mọi lượt chạy của Quy trình, mở cả từ
  màn Lịch sử chạy, và dòng W2 rút.
- 24/10/2026 (agent, tạm): G-5: sửa một Quy trình không có bản Nháp hay Bản ứng viên mở bản Nháp mới chỉ khi người dựng
  bấm "Tạo bản Nháp", qua `POST /api/v1/studio/artifacts/{id}/draft` (tenant-config:R2.21), không lúc mở trang, vì tạo
  bản Nháp ghi audit `studio.artifact.draft_created` và chiếm chỗ phiên bản chưa phát hành duy nhất của thành phần; 409
  `candidate_pending` đưa trang vào trạng thái chỉ đọc của R3.10, nêu "rút bản đang chờ về Nháp để sửa" (V4.17;
  tenant-config:R2.22), còn 409 `draft_exists` mở bản Nháp đang có (tenant-config:R2.23). Sửa: R3, R3.13, R3.14,
  R3.15, Trong phạm vi, Ngoài phạm vi, Màn hình, BU15, Phụ thuộc, ticket 03. Nếu sai thì: trang builder tạo bản Nháp
  ngay khi mở một Quy trình không có bản Nháp hay Bản ứng viên, R3.13 đổi theo và BU15 bỏ ca "không lời gọi khi chưa
  bấm".
- 25/10/2026 (agent, tạm): R3.12 thôi có bộ chọn làn: id Bước là duy nhất trong cây (workflow-engine:R1.1) và mọi làn
  của một Bước song song vẽ cùng lúc trên Sơ đồ, nên làn không phân biệt Bước chạy nào mà id chưa phân biệt; màn lượt
  chạy chọn lần lặp theo `iteration_path`, còn bộ chọn chỉ số của `logic.map` đến ở W2. Sửa: R3.12, BU16, ticket 03.
  Nếu sai thì: R3.12 giữ bộ chọn làn và nêu Bước chạy mà nó phân biệt.
- 25/10/2026 (Đạt): V4.33: `flow.subworkflow@1` vào bậc B của W1, lồng tối đa 3 cấp, và ngữ pháp Sơ đồ có khối quy
  trình con ở bậc A (ticket 04), nên Sơ đồ vẽ nó trước khi workflow-nodes đăng ký loại, còn bảng Loại bước chỉ đưa nó
  khi danh mục có. Sửa: đoạn mở đầu, R1, R1.5, Ngoài phạm vi, Phụ thuộc, ticket 01, 04.
- 25/10/2026 (Đạt): V4.37: màn duyệt W1 gồm Sơ đồ chỉ đọc, lớp phần khác so với bản Đang dùng, kết quả cổng và chi
  phí ước tính (agent-lifecycle/07); spec này làm Sơ đồ chỉ đọc và lớp phần khác, màn đó lo route, quyền, kết quả
  cổng, chi phí và hai phiên bản đưa vào. Sửa: đoạn mở đầu, R3, thêm R3.16-R3.20, Trong phạm vi, Ngoài phạm vi, Màn
  hình, thêm BU17, Phụ thuộc, ticket 03.
- 25/10/2026 (Đạt): V4.41: người giữ `studio.workflows.test` đọc Bước chạy và chi tiết của lượt `simulate` do chính
  mình xin, lượt `live` vẫn đòi `runs.read`, lượt của người khác hay của công ty khác trả 404, và `/runs` không đổi ở
  W1 (H-17), nên màn lượt chạy của R3.11 mở từ id lượt mà route `test-runs` trả, dưới quyền đó của telemetry-and-audit.
  Sửa: R3.11, Màn hình, Phụ thuộc, ticket 03.
- 25/10/2026 (agent, tạm): lớp phần khác so theo id Bước: một Bước "Đã sửa" khi `type`, `config`, `retry`,
  `timeout_s`, `on_error` hay `description` của nó khác, khi làn chứa nó (id Bước chứa và Nhánh ra) khác, hay khi chỉ
  số của nó trong dãy các Bước có ở cả hai bản của cùng làn khác, nên đổi chỗ hai Bước gắn nhãn cả hai, còn chèn một
  Bước mới trước một Bước không gắn nhãn Bước đó; Bước đã xóa vào một danh sách cạnh Sơ đồ thay vì thẻ ma trong cây,
  để bố cục giữ bất biến của R1.6; phần ngoài cây Bước được nêu tên, vì một thay đổi ở `limits` hay `triggers` không
  thẻ nào mang và một lớp phần khác chỉ nhìn thẻ sẽ báo "không đổi" cho nó (failure-modes #0); không so được thì nói,
  và màn phải nói rõ khi Quy trình chưa có bản Đang dùng, lúc đó mọi Bước "Mới", vì một lỗi đọc vẽ thành "không phần
  khác" là mặc định mở cho người duyệt (failure-modes #7). Sửa: R3.16-R3.20, BU17, ticket 03. Nếu sai thì: so thứ tự
  bằng dãy con chung dài nhất, chỉ Bước bị dời mang nhãn, Bước đã xóa vẽ thành thẻ mờ ở chỗ cũ, và phần ngoài cây
  Bước là việc của màn duyệt.
- 25/10/2026 (agent, tạm): thẻ Quy trình con ở W1 là một thẻ Bước mang dấu "Quy trình con", `api_name` của Quy trình
  được gọi và dòng "Chờ Quy trình con xong", không vẽ Bước nào của Quy trình con; Tag phiên bản ghim, báo lệch và nút
  Mở ở W2, vì phiên bản ghim nằm trong closure của phiên bản mà chưa route W1 nào đưa cho Sơ đồ, lệch là của
  agent-lifecycle, và Mở cần tra id từ `api_name`. Sửa: R1.5, Ngoài phạm vi, ticket 04. Nếu sai thì: thẻ ở W1 mang
  Tag phiên bản ghim và nút Mở, và ticket 04 chờ một route của tenant-config đưa phụ thuộc của phiên bản.
- 25/10/2026 (agent, tạm): màn lượt chạy tô làn đã đi của mỗi Bước rẽ nhánh, Bước phê duyệt và làn lỗi theo `port` của
  Bước chạy (V4.36), không suy từ Bước nào đã chạy, vì một làn rỗng không có Bước chạy nào để suy, và `port` là chủ duy
  nhất của sự thật đó (failure-modes #2). Sửa: ticket 03. Nếu sai thì: màn suy làn từ Bước chạy, và một làn rỗng đã đi
  ghi "Chưa chạy".

## Danh sách ticket

| #   | Ticket                                                                                                 |
| --- | ------------------------------------------------------------------------------------------------------ |
| 01  | [Thử nghiệm Sơ đồ có cấu trúc và ngoại lệ antd-only](issues/01-xyflow-va-ngoai-le-antd.md)             |
| 02  | [Thao tác cây, bố cục thuần và trang builder](issues/02-do-thi-va-trang-builder.md)                    |
| 03  | [Biểu thức, gửi kiểm định, chạy mô phỏng và màn lượt chạy](issues/03-bieu-thuc-publish-va-chay-thu.md) |
| 04  | [Ngữ pháp sơ đồ: nhánh, song song, vòng lặp, nhánh lỗi, quy trình con](issues/04-ngu-phap-so-do.md)    |
