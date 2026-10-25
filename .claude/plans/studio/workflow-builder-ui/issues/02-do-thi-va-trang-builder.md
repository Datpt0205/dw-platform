# 02 — Thao tác cây, bố cục thuần và trang builder tự lưu bản nháp

Status: needs-triage
Blocked by: 01, .claude/plans/studio/workflow-engine/issues/01-tai-lieu-workflow-va-kiem-xuat-ban.md, .claude/plans/studio/workflow-nodes/issues/02-so-dang-ky-buoc-va-mau-chuoi.md
Area: studio
Yêu cầu: R1.4, R1.5, R1.6, R1.8, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.8, R2.9, R2.10, R2.11, BU4, BU7, BU8, BU10, BU11, BU12, BU13, BU14

## Mục tiêu

Hai mô-đun thuần, `workflow-graph.ts` làm mọi thao tác trên cây Bước của tài liệu `dw.workflow/v1` và
`workflow-layout.ts` tính vị trí từ cây cho cả năm khối, cùng trang builder đặt Bước vào ô, cấu hình trong Drawer, tự
lưu Nháp, dùng được chỉ bằng bàn phím, bằng trình đọc màn hình và ở 320 px (workflow-builder-ui R1.4, R1.5, R1.6,
R1.8, R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.8, R2.9, R2.10, R2.11, BU4, BU7, BU8, BU10, BU11, BU12, BU13, BU14).
Của R1.5, ticket này làm hàng Chuỗi; khung, đầu làn và nhãn của từng cấu trúc là ticket 04.

## Việc cần làm

1. `apps/web/lib/workflow-graph.ts` (thuần, không import gói nào, có test đơn vị): tài liệu `dw.workflow/v1` là cây
   Bước, mỗi Nhánh ra mà Loại bước khai (từ `GET /api/v1/studio/node-types`, workflow-nodes:R1.2) là một làn lồng trong
   Bước (workflow-engine:R1.1). Thao tác: chèn vào một ô (làn, chỉ số); dời một Bước sang ô khác; xóa một Bước hay một
   khung chứa, trả tên mọi Bước bị xóa; ngăn xếp hoàn tác và làm lại của thao tác cây; duyệt theo thứ tự tài liệu cho
   bàn phím (Bước trước, sau, làn kế); diff theo id Bước. Không tọa độ, không đường nối trong tài liệu: round-trip giữ
   nguyên Mã băm nội dung.
2. `apps/web/lib/workflow-layout.ts` (thuần, không import gói nào, ngoài glob canvas, có property test): hai bước, đo từ
   dưới lên rồi đặt từ trên xuống theo một trục. Một Bước là thẻ W×H cố định; một chuỗi xếp dọc với ô "+" giữa hai
   Bước; một khối làn xếp các làn trái sang phải theo thứ tự tài liệu, cao bằng đầu khối cộng làn cao nhất cộng khoảng
   gộp; một khung chứa là thân cộng lề, đầu khung và một rãnh cho mũi tên quay lại; làn lỗi ở rãnh phải của Bước; O(n),
   khung thu gọn đo như một thẻ. Trả hình thuần (thẻ, đầu làn, ô "+" ở giữa đường nối, đường nối gấp khúc qua điểm neo)
   mà Sơ đồ dưới `apps/web/app/studio/**/canvas/**` đổi thành node và cạnh của React Flow. Property test theo R1.6 trên
   cây ngẫu nhiên và F1-F9 của ticket 01; ghi p95 ở 500 Bước theo ngưỡng của spike. Mô-đun trượt thì sửa mô-đun, không
   đưa dagre trở lại (V4.25).
3. Trang `/studio/workflows/[id]/builder`: danh mục Loại bước từ `GET /api/v1/studio/node-types` (nhóm, tìm, lý do
   khóa) trong một Popover có ô tìm mở từ mỗi ô "+" và mỗi ô "Thêm Bước", và trong một bảng bên từ `lg` kéo được vào ô
   (sự kiện con trỏ cùng `screenToFlowPosition` của React Flow, không thêm thư viện kéo thả; ô hợp lệ sáng lên khi
   kéo). Sơ đồ với `nodesDraggable={false}`, `nodesConnectable={false}`, handle ẩn chỉ làm neo cạnh, vẽ mọi thẻ Bước, ô
   "+" và đường nối ở đúng chỗ mô-đun bố cục trả, theo hàng Chuỗi của bảng ngữ pháp R1.5 (một chiều trên xuống dưới,
   ô "+" luôn hiện với vùng chạm ít nhất 24 px, làn trống có ô "Thêm Bước" nét đứt). Thẻ Bước theo R1.8. Cấu hình
   trong antd `Drawer` với `Form` sinh từ `config_schema` cộng widget riêng (điểm gắn, người duyệt) và tab "Khi lỗi".
   Menu "…" (`Dropdown`) có Thêm sau, Di chuyển…, Xóa, Sao chép tham chiếu.
4. Tự lưu Nháp: debounce; gửi `If-Match` phiên bản đã đọc; chỉ báo "Đang lưu… / Đã lưu / Lưu thất bại".
   Một 412 giữ nguyên nội dung đang gõ và mời tải lại.
5. Bàn phím: `nodesFocusable={false}` và `edgesFocusable={false}`, hay một node nhận focus một lúc; đích focus là antd
   `Button` trong thẻ (`.claude/rules/ui-quality.md` §3: không `onClick` trên `div` hay `Card`); roving focus một điểm
   dừng Tab theo thứ tự tài liệu với các phím của R2.5; `deleteKeyCode`, `panActivationKeyCode`, `selectionKeyCode` và
   `multiSelectionKeyCode` là `null`, ứng dụng tự xóa (mặc định của 12.12.0 là Backspace, Space và Shift, bắt trên cả
   trang, kể cả khi focus ở một nút, đo ngày 24/10/2026; trong ô nhập thư viện chỉ bỏ qua Space và Backspace, đọc ở
   `dist/esm/index.mjs` của gói ngày 25/10/2026); mọi bộ bắt phím bỏ qua `isComposing`; phím đơn chỉ khi Sơ đồ có
   focus (WCAG 2.1.4).
6. Trợ năng: `ariaLabelConfig` và `ariaLabel` của mỗi cạnh lấy từ khóa thông điệp tiếng Việt hay là `null` (mặc định
   của 12.12.0 là "Edge from … to …", đo ngày 24/10/2026; DO-57); mỗi ô "+" tên "Thêm Bước sau «tên»"; một vùng
   `aria-live` báo mỗi lần thêm, dời, xóa; xóa ngay với thông báo Hoàn tác qua `App.useApp()` nêu tên mọi Bước bị xóa
   (`.claude/rules/ui-quality.md` §10). Dạng danh sách là antd `Tree` dựng từ cùng cây tài liệu, mỗi node của
   `treeData` truyền `aria-level`, `aria-posinset`, `aria-setsize` (antd 6.6.5 không tự phát, đo ngày 24/10/2026), cùng
   menu thao tác của Sơ đồ, là trình dựng chính dưới `md` và ở 320 px. Playwright ở 320 px và một dự án múi giờ khác.

## Tiêu chí chấp nhận

- [ ] R1.4 (BU8): đặt một Bước vào mỗi loại ô (nút "+" trên đường nối, ô "Thêm Bước" của làn trống, kéo từ bảng bên,
      kéo một Bước có sẵn) → tài liệu khác bản trước đúng một thao tác chèn hay dời ở làn và chỉ số của ô, không tọa
      độ, không đường nối; kéo thẻ ra chỗ trống → tài liệu và Mã băm nội dung không đổi; kéo từ một Nhánh ra → không
      đường nối nào; bật `nodesDraggable` hay `nodesConnectable` → test thành phần đỏ; round-trip tài liệu → cây → tài
      liệu giữ nguyên Mã băm nội dung.
- [ ] R1.5: F1 vẽ một chiều trên xuống dưới, mỗi đường nối có ô "+" hiện cả khi không rê chuột với vùng chạm ít nhất
      24 px; một làn trống, như làn "Khác" chưa có Bước nào, có ô "Thêm Bước" nét đứt; ô "+" chỉ hiện khi rê chuột, hay
      vùng chạm dưới 24 px → test đỏ.
- [ ] R1.6 (BU13): property test của `workflow-layout.ts` trên cây ngẫu nhiên và F1-F9: cùng tài liệu → cùng tọa độ;
      chèn một Bước → chỉ các Bước đi sau chỗ chèn trong làn đó và trong các chuỗi bao ngoài đổi tọa độ, và chỉ theo
      chiều dọc; chèn một Bước có làn → không Bước nào đứng trước chỗ chèn đổi tọa độ dọc; mọi lần chèn giữ thứ tự dọc
      và thứ tự làn, không hai thẻ chồng nhau; đổi mô-đun để xếp làn theo độ rộng → test đỏ; `workflow-layout.ts`
      import một gói → test đỏ.
- [ ] R1.8 (BU14): thẻ Bước của F8 cắt tên bằng dấu … và đủ chữ qua Tooltip; huy hiệu "Thử lại ×3", "Hết giờ 30 s",
      "Khi lỗi: …" có chữ cùng biểu tượng; một màu literal trong thành phần thẻ → test đỏ.
- [ ] R2.1: bấm một ô "+" → Popover bảng chọn có ô tìm, nhóm theo nhóm, nêu lý do khóa; chọn một Loại bước → Bước vào
      đúng ô đó; từ `lg` bảng bên kéo được vào ô, dưới `lg` không có bảng bên; mở một Bước → Drawer với Form sinh từ
      `config_schema`.
- [ ] R2.2: ở 320 px không có cuộn ngang.
- [ ] R2.3: tự lưu gửi `If-Match` với phiên bản Nháp đã đọc.
- [ ] R2.4 (BU4): hai tab lưu cùng Nháp → tab sau nhận 412 và nội dung đang gõ giữ nguyên.
- [ ] R2.5 (BU7): Playwright dựng F1 chỉ bằng bàn phím, không chuột: đặt Bước qua menu "…" và ô "Thêm Bước", dời một
      Bước, xóa rồi hoàn tác bằng Ctrl+Z và làm lại bằng Ctrl+Shift+Z, mở và đóng cấu hình, Ctrl+K "Đi tới Bước"; phím
      mũi tên không bao giờ dời node; bỏ đường bàn phím của một ô → test đỏ.
- [ ] R2.6 (BU11): `Tree` dựng từ cùng cây tài liệu, mỗi node có `aria-level`, `aria-posinset`, `aria-setsize` đúng
      cây; một Bước thêm trên Sơ đồ có mặt trong `Tree` với nhãn tiếng Việt ở đúng cấp và vị trí; ở 320 px Playwright
      dựng F1 qua `Tree`; bỏ một thuộc tính → test đỏ.
- [ ] R2.7 (BU10): chọn một Bước, rồi nhấn Space, Shift hay Backspace khi focus ở một nút ngoài Sơ đồ và trong một ô
      nhập ngoài Sơ đồ → Sơ đồ không kéo, chọn hay xóa gì, tài liệu không đổi; đặt lại `deleteKeyCode` mặc định → ca
      focus ở nút đỏ.
- [ ] R2.8 (BU10): gõ Telex trong ô tìm của Ctrl+K → không phím tắt nào chạy; bỏ kiểm `isComposing` → test đỏ.
- [ ] R2.9 (BU12): không phần tử nào của Sơ đồ có `aria-label` bắt đầu bằng `Edge from`; ô "+" có tên "Thêm Bước sau
      «tên»" với tên của Bước đứng trước; bỏ `ariaLabel` của một đường nối → test đỏ.
- [ ] R2.10 (BU12): thêm, dời, xóa một Bước → vùng `aria-live` nêu tên Bước và làn; bỏ lời báo → test đỏ.
- [ ] R2.11 (BU7): xóa một Bước có làn → thông báo có nút Hoàn tác nêu tên mọi Bước bị xóa, không hộp xác nhận; Hoàn
      tác → tài liệu bằng đúng trước lần xóa; bỏ Hoàn tác → test đỏ.
- [ ] Xong: `pnpm -C apps/web test` xanh.

## Nguồn

- workflow-nodes:R1.2; `.claude/plans/studio/workflow-nodes/issues/02-so-dang-ky-buoc-va-mau-chuoi.md`.
- workflow-engine:R1.1; `.claude/plans/studio/workflow-engine/issues/01-tai-lieu-workflow-va-kiem-xuat-ban.md`.
- `apps/web/app/layout.tsx:1`; spec: R2.1 (chưa có route `studio`).
- ADR-0101 (Accepted) quyết 3; spec: R1.4, R1.6 (vị trí tính từ cây, không lưu).
- `.claude/rules/ui-quality.md:92-95`; spec: R2.7, R2.8 (phím đơn khi có focus, `isComposing`).
- `.claude/rules/ui-quality.md:312-315`; spec: R2.11 (hoàn tác trong thông báo, không hộp thoại).
- `.claude/rules/ui-quality.md:377-380`; spec: R2.9, R2.10 (tên truy cập, lời báo).

## Comments

- 2026-10-23 (agent): theo phiếu 23/10/2026: hàm bố cục dời vào thư mục canvas để `workflow-graph.ts` không import gói nào (DO-42.1); nhãn aria của Sơ đồ đi qua khóa thông điệp tiếng Việt (DO-57).
- 2026-10-25 (agent): lượt g, theo V4.24 và V4.25 của Đạt ngày 24/10/2026: `workflow-graph.ts` thành thao tác trên cây Bước, hàm bố cục dagre dưới thư mục canvas thành `apps/web/lib/workflow-layout.ts` thuần ngoài glob canvas (R1.6, BU13); đặt vào ô thay nối dây (R1.4, BU8); bảng chọn là Popover của ô "+" cùng bảng kéo, cấu hình trong Drawer (R2.1); xóa có thông báo Hoàn tác thay hộp xác nhận (R2.11); mô hình bàn phím và trợ năng theo phản biện (R2.5-R2.10, BU10-BU12). Không thêm cạnh.
