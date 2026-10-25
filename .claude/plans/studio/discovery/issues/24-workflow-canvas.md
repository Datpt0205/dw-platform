# 24 — Sơ đồ quy trình: `@xyflow/react` với bố cục cấu trúc dưới CSP nonce, lớp antd, Next 15.5 và React 19

Type: prototype
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-51 `canvas`

## Câu hỏi

1. `@xyflow/react` 12.12.0, ghim chính xác, không dagre và không thư viện bố cục nào (V4.25), có chạy dưới CSP nonce
   theo từng request, thứ tự lớp CSS của antd, Next 15.5 và React 19 (`apps/web/package.json:23-24`) với đúng một
   `zustand` ≥ 4.5.6 trong lockfile không, và trang sơ đồ tốn bao nhiêu JS tải đầu?
2. Module bố cục thuần TypeScript `apps/web/lib/workflow-layout.ts` (đo từ dưới lên, đặt từ trên xuống, O(n), khung thu
   gọn đo như một thẻ) có giữ các bất biến bố cục của V4.24 trên F1-F9 không, và p95 của nó ở 500 Bước là bao nhiêu?
3. Ngữ pháp sơ đồ của V4.24 (thẻ antd, nhánh, khung, ô "+", nhánh lỗi, mũi tên quay lại, `Điểm nối`) có vẽ được mọi
   cấu trúc mà người dựng nghiệp vụ đọc và sửa được không, kể cả một quy trình làm lại quay về nhiều Bước trước (F9),
   trước khi hình tài liệu cây Bước bị khóa (ADR 0112 quyết định 1)?
4. 300 và 500 thẻ antd có render đầu, pan và zoom dùng được không, có và không `onlyRenderVisibleElements`, và roving
   focus có còn sau khi node bị cull không?
5. Chỉ bằng bàn phím, ở 320 px và cảm ứng, và với NVDA đọc tiếng Việt trên Dạng danh sách, người dựng có làm được mọi
   thao tác không?

## Vì sao

Ngoại lệ của sơ đồ với quy tắc chỉ dùng antd (`CLAUDE.md`, mục "Web UI") phải được đo trước khi cấp: ADR 0101 biến
guard antd-only thành allowlist, mỗi ngoại lệ có ADR riêng. Hình tài liệu cây Bước (V4.24) là thứ đắt nhất để sửa về
sau, nên phép đo này thử giới hạn của cây (F9) và ngữ pháp sơ đồ với người dùng thật trước khi `workflow-engine/01`
dựng trên nó. CI của `@xyflow/react` chỉ thử React 18, và ứng dụng trộn `zustand` 4 với 5 đã vỡ trên React 19
(issue #5229, #5095 của xyflow), nên đây là phép thử React 19 duy nhất của ta (`.claude/rules/failure-modes.md` mục 4).

## Mở khóa

- Spec: `workflow-builder-ui` (01 là phép đo này; 02 thao tác cây và `workflow-layout.ts`; 03; 04 ngữ pháp sơ đồ cho
  nhánh, song song, vòng lặp và nhánh lỗi), `studio-skeleton` (03, seam web và allowlist), `workflow-engine` (01, tài
  liệu cây Bước, qua F9).
- ADR: 0101 (quyết định 1, 3, 4, 5 sửa ngày 24/10/2026), 0112 (quyết định 1, tài liệu là cây Bước).
- DO: DO-42 theo V4.25 (chỉ `@xyflow/react` trong ngoại lệ, `antd-only.test.ts` là allowlist `{module, glob, adr}`,
  giữ huy hiệu ghi công của React Flow ở góc dưới trái để Drawer không che); V4.27 (bộ từ vựng hình ảnh, Đạt duyệt).
- Ticket W1: `workflow-builder-ui/01` (P0) là phép đo này; xong thì FOG-51 đóng bằng một dòng trỏ tới số đo ở đó.

## Dựng tối thiểu

Một trang nháp dưới `apps/web/app/studio/**/canvas/**`, sau CSP nonce hiện có, với `@xyflow/react` 12.12.0 ghim chính
xác và không dagre:

- Module bố cục `apps/web/lib/workflow-layout.ts`: thuần TypeScript, ngoài glob canvas, không import gì, trả hình
  thuần mà sơ đồ đổi thành node và cạnh của React Flow.
- Thẻ Bước là antd Card cỡ cố định; nhánh, khung thu gọn được, ô "+" trên đường nối và ô "Thêm Bước" trong nhánh trống,
  nhánh lỗi nét đứt bên phải Bước, mũi tên quay lại của vòng lặp, thanh `Chờ tất cả nhánh xong` của Bước song song;
  Dạng danh sách là antd Tree của chính cây đó.
- Mô hình bàn phím của V4.24; kéo từ bảng bên vào ô và kéo một Bước sang ô khác, không thêm thư viện kéo thả nào.
- Cấu hình React Flow: `nodesDraggable`, `nodesConnectable`, `nodesFocusable` và `edgesFocusable` là `false` (hay một
  node nhận focus một lúc cho roving focus), đích focus là antd Button trong thẻ, không `onClick` trên `div` hay Card
  (`.claude/rules/ui-quality.md` §3); `deleteKeyCode`, `panActivationKeyCode`, `selectionKeyCode` và
  `multiSelectionKeyCode` là `null`; mọi cạnh có `ariaLabel` tiếng Việt hay `null`; `attributionPosition` ở góc dưới
  trái.
- Các loại W2 (lặp qua danh sách, quy trình con, nhánh `Hết hạn`) chỉ hiển thị, trên cùng các phần dựng chung.
- Một agent dựng bản nháp bộ từ vựng hình ảnh để Đạt duyệt (V4.27): màu nhóm lấy từ token của theme (ví dụ trigger
  xanh dương, AI tím, dữ liệu cyan, logic vàng, con người hồng tím, công cụ xanh lá, lỗi đỏ), mỗi màu kiểm tương phản
  3:1, biểu tượng `@ant-design/icons`, cỡ thẻ và kiểu cạnh; không dùng sắc nhạt preset của antd cho ô nhóm
  (`.claude/rules/ui-quality.md` §12).
- Bố cục và cách tương tác học từ các tham chiếu Đạt gửi; không chép giao diện của Dify, không chép mã của Windmill
  (AGPLv3) hay n8n (Sustainable Use License) (V4.24, V4.29).

Fixture, sinh dưới dạng cây Bước:

- F1: quy trình Tiếp nhận lead 15 Bước (YC94).
- F2: một Bước rẽ nhánh 8 nhánh, lồng 2 tầng.
- F3: Bước song song 3 nhánh trong một Bước vòng lặp trong một Bước rẽ nhánh (3 tầng).
- F4: nhánh lỗi ở mọi Bước.
- F5: vòng làm lại có phê duyệt (`Lặp lại khi …` quanh soạn lại rồi phê duyệt), cùng một Bước phê duyệt cần mọi người
  được giao duyệt (YC110).
- F6 và F7: 300 và 500 Bước trộn mọi loại.
- F8: các tên Bước tiếng Việt thật dài nhất.
- F9: duyệt ba cấp mà từ chối quay về các Bước trước khác nhau theo lý do (vòng lặp lồng nhau và `Thoát vòng lặp`),
  để thử giới hạn của cây trước khi khóa hình tài liệu.

## Phép đo quyết định

| Đo                                                                                                                                                                                                                            | Ngưỡng                                                                                                                                                                                                                                                                                                                                                               | Quyết định                                                                                                                             |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| Vi phạm CSP ở production và dev; CSS của `@xyflow/react` bị lớp antd đè                                                                                                                                                       | 0                                                                                                                                                                                                                                                                                                                                                                    | Cấp ngoại lệ hay không (ADR 0101, DO-42, V4.25)                                                                                        |
| JS tải đầu (gzip) của trang sơ đồ, với `base.css` trong `@layer components`, `--xy-*` ánh xạ sang `--ant-*` và một test thứ tự lớp đỏ khi sai thứ tự                                                                          | Ghi kB, so với +250 kB mà `CLAUDE.md` chấp nhận cho antd; thư viện khoảng 60 kB gzip theo bundlephobia, mã của ta chưa đo                                                                                                                                                                                                                                            | Ghi vào ADR 0101                                                                                                                       |
| React 19 với build production của Next 15.5, StrictMode, `next/dynamic` với `ssr: false`; lockfile có đúng một `zustand` ≥ 4.5.6, không bản 5.x                                                                               | 0 lỗi lúc chạy                                                                                                                                                                                                                                                                                                                                                       | Giữ bản ghim (CI của thư viện chỉ thử React 18)                                                                                        |
| Bố cục F1-F9                                                                                                                                                                                                                  | Cùng tài liệu ra cùng tọa độ (snapshot); chèn một Bước chỉ dời những gì đi sau nó trong nhánh của nó và trong các chuỗi bao ngoài; chèn một Bước có nhánh có thể đẩy các nhánh anh em sang ngang nhưng không đổi thứ tự dọc hay thứ tự nhánh; không chồng lấn (property test trên cây ngẫu nhiên); p95 ở 500 Bước ghi số, đích đặt khi đo (ví dụ ≤ 50 ms, chưa kiểm) | Bỏ dagre hẳn; module lỗi thì sửa module (tham khảo `flow-canvas-utils.ts` của Activepieces, MIT, có ghi công), không đưa dagre trở lại |
| 300 và 500 thẻ antd: render đầu, khung hình khi pan và zoom, bộ nhớ, có và không `onlyRenderVisibleElements`, khung thu gọn qua `hidden`                                                                                      | Ghi số; focus không mất khi node đang giữ nó bị cull                                                                                                                                                                                                                                                                                                                 | Trần số Bước của gói (`wf.limit_above_plan`) và có dùng `onlyRenderVisibleElements` không                                              |
| Playwright chỉ bằng bàn phím: dựng F5, dời một Bước, xóa rồi hoàn tác, mở và đóng cấu hình, vào ra khung và qua nhánh, Ctrl+K "Đi tới Bước"                                                                                   | Mọi thao tác làm được; phím mũi tên không bao giờ dời node; xóa do ứng dụng làm (`deleteKeyCode` là `null`); bộ bắt phím bỏ qua `isComposing` (gõ Telex); phím đơn chỉ chạy khi sơ đồ có focus (WCAG 2.1.4); `aria-live` báo mỗi lần thêm, dời, xóa                                                                                                                  | R2.5 và BU7 của `workflow-builder-ui` đạt hay không                                                                                    |
| 320 px và cảm ứng                                                                                                                                                                                                             | Dạng danh sách là trình dựng; trang không cuộn ngang; ô "+" ít nhất 24 px; kéo bằng cảm ứng vào ô chạy được hay có đường qua menu                                                                                                                                                                                                                                    | YC39 đạt hay không                                                                                                                     |
| NVDA đọc tiếng Việt trên Dạng danh sách, sau một test đỏ khi node của Tree thiếu `aria-level`, `aria-posinset` hay `aria-setsize` (antd 6.6.5 không tự phát)                                                                  | Đọc đúng thứ tự Bước, "nhánh 2 trên 3: …", tầng lồng và trạng thái; báo thêm, dời, xóa                                                                                                                                                                                                                                                                               | Dạng danh sách đủ cho người dùng trình đọc màn hình không (R2.6 của `workflow-builder-ui`)                                             |
| Trực quan: dark mode; tương phản ≥ 3:1 cho cạnh, ô "+" và vòng focus; màu không bao giờ là thứ duy nhất mang nghĩa; chuyển động giảm tắt mọi chuyển tiếp; huy hiệu ghi công không bị che khi Drawer mở ở `lg`, `md` và 320 px | Qua cả năm điểm                                                                                                                                                                                                                                                                                                                                                      | Bộ từ vựng hình ảnh ghi một lần trong theme của `@dw/ui`, Đạt duyệt (V4.27)                                                            |
| Năm quản trị viên nghiệp vụ thật làm nhiệm vụ có kịch bản: dựng F5 từ một mô tả viết, sửa hai lỗi được đánh dấu, trả lời năm câu về một quy trình 60-100 Bước, dựng F9                                                        | Ghi tỷ lệ xong, thời gian, lỗi, chọn Sơ đồ hay Dạng danh sách, và node không kéo được hay thiếu minimap có làm họ vướng không                                                                                                                                                                                                                                        | Giữ mô hình có cấu trúc hay mở lại; người tham gia chờ đội thí điểm của DO-22. Chủ: Đạt                                                |

Không thuộc ticket này: hành vi của bộ máy chạy ở bậc B của V4.26 (`Điểm nối` trên nhánh biên dịch thành subgraph,
vòng lặp có chờ, `Sự cố`) đo ở [14](14-workflow-runtime.md), trên PostgreSQL với hai worker.

## Nguồn

- Brief B7b; `apps/web/lib/__tests__/antd-only.test.ts` (guard hiện tại); `apps/web/lib/csp.ts` (nonce,
  `strict-dynamic`, `style-src 'unsafe-inline'`).
- [research.md](../research.md) mục 3 (`@xyflow/react` dưới CSP nonce và React 19 chưa kiểm).
- Nghiên cứu sơ đồ và phản biện của nó ngày 24/10/2026, mà Đạt nhận mọi khuyến nghị (V4.24-V4.29 ở mục State của
  [studio.md](../../../studio.md)); số đo LangGraph ghi ở Context của ADR 0112, các thư viện bị loại ở Alternatives của
  ADR 0101. Trong đó:
    - `@xyflow/react` 12.12.0 (24/09/2026) là bản ổn định mới nhất, 13.0.0-next.0 (11/10/2026) là bản thử:
      <https://registry.npmjs.org/@xyflow/react>; _documented_, đọc 24/10/2026.
    - Ở 12.12.0, phím mũi tên chỉ dời node khi node kéo được và đang chọn; mặc định `deleteKeyCode` là `Backspace`,
      `selectionKeyCode` là `Shift`, `panActivationKeyCode` là `Space`; nhãn cạnh mặc định là "Edge from … to …" tiếng
      Anh: `dist/esm/index.mjs` trong <https://registry.npmjs.org/@xyflow/react/-/react-12.12.0.tgz>; _measured_
      24/10/2026.
    - Khoảng 60 kB gzip cho `@xyflow/react` cùng phụ thuộc:
      <https://bundlephobia.com/api/size?package=@xyflow/react@12.12.0>; _documented_, số đo của bên thứ ba, đọc 24/10/2026.
    - Tree của antd 6.6.5 (`@rc-component/tree` 1.4.0) không phát `aria-level`, `aria-posinset`, `aria-setsize`;
      _measured_ 24/10/2026 trên `node_modules` của repo.
    - Activepieces tắt kéo, nối và focus node trên sơ đồ, và tính vị trí từ cây không cần thư viện bố cục
      (`flow-canvas-utils.ts`, MIT):
      <https://github.com/activepieces/activepieces/blob/6f4be340d7c4bef9fb6ff874ca72224e4933d3d2/packages/web/src/app/builder/flow-canvas/index.tsx#L228-L240>;
      _documented_, đọc 24/10/2026.
    - Giấy phép của Dify nói thiết kế tương tác của họ được bảo hộ kiểu dáng:
      <https://raw.githubusercontent.com/langgenius/dify/main/LICENSE>; _documented_, đọc 24/10/2026.

## Comments

- 2026-10-24 (agent): viết lại theo V4.24-V4.29 của Đạt: tiêu đề mới, bỏ dagre và phép đo bố cục dagre, thêm fixture
  F1-F9 và bảng đo của nghiên cứu sơ đồ đã gộp phản biện (bất biến bố cục hẹp hơn, roving focus qua culling, test
  `aria-*` trước NVDA, F9); hành vi bộ máy của bậc B chuyển sang ticket 14.
