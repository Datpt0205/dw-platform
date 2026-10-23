# Trình dựng quy trình: sơ đồ, cấu hình bước, chạy thử, phiên bản

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Người dựng không viết mã vẽ một Quy trình trên một Sơ đồ, cấu hình mỗi Bước bằng biểu mẫu antd sinh từ
schema, viết Biểu thức với một bộ Chọn biến có kiểu, chạy thử ở chế độ Mô phỏng và gửi kiểm định. Sơ đồ
là ngoại lệ duy nhất của luật "chỉ antd": antd không có canvas đồ thị, nên `@xyflow/react` cùng dagre
vào `apps/web` chỉ ở đường dẫn canvas `apps/web/app/studio/**/canvas/**`, có test giữ ranh giới. Biểu thức tính ở máy chủ, lỗi kiểm về từ
bộ kiểm của máy chủ; trang builder không bao giờ tự phát hành. Lát W1 là canvas tối thiểu đủ dựng, chạy
thử và gửi kiểm định quy trình Tiếp nhận lead.

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- `apps/web` dùng `antd` ^6.6.5 và không có thư viện đồ thị hay layout nào (`apps/web/package.json:20`).
  Thiếu: một Sơ đồ đồ thị.
- `CLAUDE.md:137` bắt UI dùng `antd` và không gì khác; guard là một denylist của hệ đã gỡ
  (`apps/web/lib/__tests__/antd-only.test.ts:20`) cộng ESLint `no-restricted-imports`. Một thư viện
  canvas sẽ qua cả hai mà vẫn trái `CLAUDE.md` — một check không thấy được phần nó phủ
  (`failure-modes.md` #0). Ràng buộc: ngoại lệ phải đổi test, không chỉ đổi chữ.
- `antd-only.test.ts` đọc cả `apps/web` lẫn gói `@dw/ui` ở `packages/typescript/ui`
  (`apps/web/lib/__tests__/antd-only.test.ts:14`), kể cả một phụ thuộc quay lại qua manifest mà không
  có import. Ràng buộc: test ngoại lệ khẳng định app nào khai và tệp nào import.
- CSP đặt `script-src` một nonce theo request với `strict-dynamic`, và `style-src 'unsafe-inline'` vì
  CSS-in-JS của antd viết thẻ `<style>` lúc chạy (`apps/web/lib/csp.ts:16-21`). Ràng buộc: gói canvas
  phải chạy dưới CSP này mà không chèn script nội tuyến không nonce.
- Các route dưới `apps/web/app/` là `admin`, `approvals`, `audit`, `integrations`, `knowledge`,
  `memory`, `platform`, `dev-login`; chưa có `studio` (`apps/web/app/layout.tsx:1`). Thiếu: điều hướng
  `/studio/*` do `studio-skeleton` dựng.

## Mục tiêu

### R1 — Sơ đồ là ngoại lệ antd-only, vị trí không lưu

Người dựng vẽ Quy trình trên một Sơ đồ, antd vẽ mọi thân Bước, vị trí tính lúc render (YC39; BUI-01;
ADR-0101 (Accepted)).

- R1.1 `@xyflow/react` 12.12.0 và `@dagrejs/dagre` 3.1.1, ghim đúng hai phiên bản đó, PHẢI chỉ được
  import dưới `apps/web/app/studio/**/canvas/**`.
- R1.2 NẾU một tệp ngoài đường dẫn canvas của builder, hoặc gói `@dw/ui`, import hay khai báo hai gói
  đó, THÌ `antd-only.test.ts` PHẢI đỏ.
- R1.3 Sơ đồ PHẢI để antd vẽ mọi thân Bước, bảng, biểu mẫu và thông báo, với màu, kiểu chữ và bo góc
  lấy từ theme antd, còn Tailwind chỉ lo bố cục.
- R1.4 KHI người dựng kéo một Bước trên Sơ đồ, hàm bố cục dưới đường dẫn canvas PHẢI tính lại vị trí bằng
  dagre mà không ghi vị trí vào tài liệu và không đổi Mã băm nội dung.

### R2 — Trang builder ba cột, tự lưu, dùng được bằng bàn phím

Người dựng cấu hình Bước bằng biểu mẫu, ở màn hẹp và chỉ bằng bàn phím (YC39; BUI-02, BUI-05, BUI-07).

- R2.1 KHI người dựng mở `/studio/workflows/[id]/builder`, trang builder PHẢI hiện ba cột bảng Loại
  bước, Sơ đồ và biểu mẫu cấu hình antd sinh từ `config_schema`, với cột cấu hình thành Drawer dưới
  breakpoint `lg`.
- R2.2 Ở màn rộng 320 px, trang builder PHẢI không cuộn ngang.
- R2.3 KHI trang builder tự lưu Nháp, trang builder PHẢI gửi `If-Match` với phiên bản Nháp đã đọc.
- R2.4 NẾU hai tab lưu cùng một Nháp, THÌ trang builder PHẢI nhận 412 và giữ nguyên nội dung đang gõ.
- R2.5 Mỗi thao tác chuột trên Sơ đồ PHẢI có một đường bàn phím tương đương, kể cả thêm, nối và xóa Bước.
- R2.6 Dạng danh sách PHẢI đồng bộ với Sơ đồ và dùng được với trình đọc màn hình tiếng Việt.

### R3 — Ô biểu thức, lỗi tại chỗ, gửi kiểm định, chạy thử Mô phỏng

Biểu thức kiểm ở máy chủ, lỗi về đúng Bước, chạy thử không rời chế độ an toàn, và trang builder không
tự phát hành (YC33, YC40; BUI-03, BUI-04, BUI-06).

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
- R3.6 KHI người dựng chạy thử, trang builder PHẢI gửi chế độ `simulate` tới route chạy thử và hiện lỗi 422
  của route nếu có; quyền và chế độ được nhận là của workflow-triggers:R2.2, workflow-triggers:R2.3 và
  workflow-triggers:R2.6.
- R3.7 KHI chạy thử trả kết quả từng Bước chạy, trang builder PHẢI hiện "Đã ẩn" cho mỗi trường người
  xem không đọc được, không rò giá trị trong DOM hay payload mạng.

## Trong phạm vi

- Route `/studio/workflows/[id]/builder` và các thành phần của nó.
- `apps/web/lib/workflow-graph.ts`: mô-đun thuần, không import gói nào: tài liệu `dw.workflow/v1` ↔ Bước và
  Đường nối, chèn giữa, nối Nhánh ra, xóa, thứ tự phím theo đồ thị, diff theo id Bước. Hàm bố cục dagre nằm
  dưới `apps/web/app/studio/**/canvas/**`.
- Ô Biểu thức với Chọn biến có kiểu; huy hiệu lỗi trên Bước; nút gửi kiểm định; bảng chạy thử.
- Dạng danh sách (antd `Tree`) đồng bộ với Sơ đồ.
- Ngoại lệ antd-only: hai mục `EXCEPTIONS` `{module, glob, adr}` trong allowlist của `antd-only.test.ts`
  (studio-skeleton/03 đổi guard thành allowlist) và override ESLint.

## Ngoài phạm vi

| Việc                                                                                           | Vì sao                                                        | Chủ                                 |
| ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------- | ----------------------------------- |
| Danh sách Quy trình và điều hướng `/studio/*`                                                  | Khung và điều hướng Studio                                    | `studio-skeleton`                   |
| Sổ đăng ký loại bước, API `node-types`, `/expressions/check`, `draft/scope`, bộ dựng mẫu       | Loại bước là mã nền tảng (ADR-0112 (Accepted))                | `workflow-nodes`                    |
| Tài liệu `dw.workflow/v1`, bộ kiểm khi gửi kiểm định và bảng mã `wf.*`, máy chạy của Quy trình | Hợp đồng và máy chạy của Quy trình                            | `workflow-engine`                   |
| Route chạy thử, quyền và chế độ chạy thử                                                       | Hợp đồng duy nhất của route (workflow-triggers:R2.3; DO-26.1) | `workflow-triggers`                 |
| Thư viện biểu đồ cho dashboard                                                                 | Đạt 23/10/2026: không thư viện biểu đồ nào ở v1 (DO-42)       | không làm ở v1                      |
| Màn "Lịch sử chạy" và `run_steps`                                                              | Đọc từ Postgres dưới RLS (ADR-0122 (Accepted))                | `telemetry-and-audit`               |
| Vòng đời và màn duyệt phát hành                                                                | Giai đoạn và cổng phát hành (ADR-0120 (Accepted))             | `agent-lifecycle`                   |
| Biểu mẫu bản ghi                                                                               | Thuộc trình bày của đối tượng                                 | `custom-objects`                    |
| Lịch sử chạy trên Sơ đồ                                                                        | B7b-nodes workflow-builder-ui 09                              | đợt sau (W2, `workflow-builder-ui`) |
| Phiên bản và so sánh từng Bước, khôi phục thành Nháp                                           | B7b-nodes workflow-builder-ui 10                              | đợt sau (W2, `workflow-builder-ui`) |
| Trình soạn schema không cần code, chọn người duyệt                                             | B7b-nodes workflow-builder-ui 11                              | đợt sau (W2, `workflow-builder-ui`) |
| Trợ lý dựng Quy trình bằng AI                                                                  | B7b-nodes workflow-builder-ui 12                              | đợt sau (W3, `workflow-builder-ui`) |

## Màn hình

- `/studio/workflows/[id]/builder` (người giữ `studio.workflows.edit`): ba cột bảng Loại bước, Sơ đồ,
  cấu hình. Trạng thái: xem và sửa Nháp, tự lưu ("Đang lưu… / Đã lưu / Lưu thất bại"), huy hiệu lỗi
  trên Bước, chạy thử `simulate` với kết quả từng Bước chạy, nút Gửi kiểm định (khóa có lý do). Dưới `lg`: cột cấu
  hình thành Drawer. Ở 320 px: không cuộn ngang. Dạng danh sách là đường cho trình đọc màn hình, đồng
  bộ với Sơ đồ. Giai đoạn vòng đời hiện ở đầu trang (đọc từ `agent-lifecycle`); trang không tự phát
  hành.

## Kiểm soát

| #   | Kiểm soát                                                                                                                   | Yêu cầu    | Test âm                                                                                                                                            |
| --- | --------------------------------------------------------------------------------------------------------------------------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| BU1 | Hai gói đồ thị chỉ ở `apps/web`, chỉ tệp builder import                                                                     | R1.2       | Import từ `app/approvals` → `antd-only.test.ts` đỏ; `@dw/ui` khai báo gói → đỏ                                                                     |
| BU2 | Không tính Biểu thức trong trình duyệt                                                                                      | R3.2       | Thư viện CEL có mặt trong bundle route builder → test manifest đỏ                                                                                  |
| BU3 | Nút Gửi kiểm định khóa có lý do; máy chủ vẫn từ chối; builder không tự phát hành                                            | R3.3, R3.5 | Gửi kiểm định một Nháp lỗi qua API → 422; không đường nào trong builder gọi phát hành                                                              |
| BU4 | Tự lưu dùng `If-Match`                                                                                                      | R2.4       | Hai tab → 412, nội dung đang gõ giữ nguyên                                                                                                         |
| BU5 | Chạy thử từ builder chỉ gửi `simulate`; route vẫn từ chối `live` và `test` (workflow-triggers:R2.2, workflow-triggers:R2.6) | R3.6       | Test thành phần: builder không gửi chế độ nào khác `simulate`; gọi thẳng route với `live` → 422; bỏ giới hạn chế độ ở builder → test thành phần đỏ |
| BU6 | Kết quả Bước chạy che theo bảo mật trường                                                                                   | R3.7       | Người không đọc được `phone` không thấy số trong DOM và trong mạng; gỡ che → test đỏ                                                               |
| BU7 | Mọi thao tác chuột có đường bàn phím; Dạng danh sách cho trình đọc màn hình                                                 | R2.5, R2.6 | Playwright dựng một Quy trình chỉ bằng bàn phím                                                                                                    |
| BU8 | Không lưu vị trí Bước                                                                                                       | R1.4       | Kéo một Bước không đổi tài liệu, Mã băm nội dung không đổi                                                                                         |

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát.
- Playwright chạy ở 320 px và ở một dự án múi giờ khác.
- `pnpm -C apps/web test` và `pnpm -C apps/web build` xanh; `antd-only.test.ts` xanh với hai mục
  `EXCEPTIONS` có ADR.

## Phụ thuộc

- `studio-skeleton`: seam web, guard antd-only thành allowlist `{module, glob, adr}` mà spec này chỉ thêm hai
  mục `EXCEPTIONS`, điều hướng `/studio/*`, khóa thông điệp tiếng Việt
  (`.claude/plans/studio/studio-skeleton/issues/03-seam-web-va-allowlist-antd.md`).
- `workflow-nodes`: tính Biểu thức chỉ ở máy chủ (workflow-nodes:R3.5), danh mục Loại bước với lý do
  khóa (workflow-nodes:R1.2), phạm vi biến trội và `draft/scope` (workflow-nodes:R3.2);
  `.claude/plans/studio/workflow-nodes/issues/02-so-dang-ky-buoc-va-mau-chuoi.md`,
  `.claude/plans/studio/workflow-nodes/issues/03-pham-vi-bien-va-buoc-logic.md`.
- `workflow-engine` (batch 2, đang viết song song): tài liệu `dw.workflow/v1` và bảng mã `wf.*` mà trang
  builder gắn lỗi về Bước (workflow-engine:R2.11).
- `workflow-triggers`: route chạy thử, quyền `studio.workflows.test` và chế độ được nhận (workflow-triggers:R2.2,
  workflow-triggers:R2.3, workflow-triggers:R2.6;
  `.claude/plans/studio/workflow-triggers/issues/01-so-kich-hoat-chay-tay-va-danh-tinh.md`).
- `tenant-config`: Chế độ chạy do máy chủ đặt (tenant-config:R4.1), Mô phỏng chặn tác động
  (tenant-config:R5.1); Nháp với ETag.
- `telemetry-and-audit` (batch 2): `run_steps` cho bảng chạy thử và lớp phủ.
- `agent-lifecycle` (batch 2): giai đoạn vòng đời và cổng phát hành mà builder không tự gọi.
- Kiểm lại khi: `workflow-nodes` đổi hình API `node-types`/`/expressions/check`/`draft/scope`;
  `workflow-engine` đổi hợp đồng `dw.workflow/v1` hay `workflow-triggers` đổi route chạy thử → kiểm lại
  01-03; W2 mở chế độ `test` → R3.6, BU5, ticket 03.

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

## Danh sách ticket

| #   | Ticket                                                                             |
| --- | ---------------------------------------------------------------------------------- |
| 01  | [xyflow và ngoại lệ antd-only](issues/01-xyflow-va-ngoai-le-antd.md)               |
| 02  | [Đồ thị thuần và trang builder](issues/02-do-thi-va-trang-builder.md)              |
| 03  | [Biểu thức, gửi kiểm định và chạy thử](issues/03-bieu-thuc-publish-va-chay-thu.md) |
