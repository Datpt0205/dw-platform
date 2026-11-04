# 02 — Thao tác cây, bố cục thuần và trang builder tự lưu bản nháp

Status: ready-for-agent
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
   Bước (workflow-engine:R1.1). Thao tác: chèn vào một ô (làn, chỉ số); dời một Bước sang ô khác, từ chối mọi ô trong
   cây con của chính Bước đó; xóa một Bước hay một khung chứa, trả tên mọi Bước bị xóa; thêm và bỏ một làn theo khóa
   (một mục `cases` của `logic.switch`, một mục `branches` của `logic.parallel`) và đặt `on_error` khác `route` khi làn
   lỗi còn Bước, mỗi lần bỏ Bước như vậy là một lần xóa theo R2.10, R2.11; sinh id cho Bước mới (phần tên của Loại bước
   sau dấu chấm và trước `@`, `_`, sáu ký tự `[a-z0-9]` ngẫu nhiên, sinh lại khi trùng trong tài liệu, không sửa được);
   ngăn xếp hoàn tác và làm lại của thao tác cây; duyệt theo thứ tự tài liệu cho bàn phím (Bước trước, sau, làn kế).
   Bước mới mang `config` gồm giá trị `default` mà `config_schema` khai, cộng mỗi làn mà danh mục nêu cho loại ở dạng
   rỗng (làn `default` của `logic.switch` là `[]`), không `description`; lưu Nháp không kiểm cấu hình đủ hay chưa, vì
   bộ kiểm chỉ cảnh báo lúc lưu (ADR-0112 (Accepted) quyết 3). Một Bước có Loại bước không có trong danh mục (chưa đăng
   ký, hay đã gỡ) vẽ thành thẻ "Loại bước không có trong danh mục", không làn nào, và không dời, không xóa được trên trang
   (menu chỉ có Sao chép tham chiếu), vì trang không biết làn nào trong `config` của nó chứa Bước; bộ kiểm của máy chủ báo
   `wf.unknown_type`. Thứ tự bàn phím là thứ tự trước của cây (Bước, rồi các Bước trong các làn của nó theo thứ tự làn,
   rồi Bước kế cùng cấp): ↑/↓ tới phần tử trước, sau trong thứ tự đó, ←/→ tới Bước đầu của làn kề cùng Bước cha, và ô
   "Thêm Bước" của một làn rỗng là một điểm dừng như một Bước.
   Không diff: lớp phần khác đọc `diff_steps` của wf-lite (ticket 03). Không tọa độ, không đường nối trong tài liệu:
   tài liệu → cây → tài liệu bằng sâu tài liệu đầu (cùng khóa, khóa vắng vẫn vắng, cùng thứ tự mảng); ticket không viết
   bộ chuẩn hóa hay hàm băm thứ hai trong TS, Mã băm nội dung là của máy chủ (`dw_kernel.canonical`).
2. `apps/web/lib/workflow-layout.ts` (thuần, không import gói nào, ngoài glob canvas, có property test): hai bước, đo từ
   dưới lên rồi đặt từ trên xuống theo một trục. Một Bước là thẻ W×H cố định; một chuỗi xếp dọc với ô "+" giữa hai
   Bước; một khối làn xếp các làn trái sang phải theo thứ tự tài liệu, cao bằng đầu khối cộng làn cao nhất cộng khoảng
   gộp; một khung chứa là thân cộng lề, đầu khung và một rãnh cho mũi tên quay lại; làn lỗi ở rãnh phải của Bước; O(n),
   khung thu gọn đo như một thẻ. Trả hình thuần (thẻ, đầu làn, ô "+" ở giữa đường nối, đường nối gấp khúc qua điểm neo)
   mà Sơ đồ dưới `apps/web/app/studio/**/canvas/**` đổi thành node và cạnh của React Flow. Property test theo R1.6 trên
   cây ngẫu nhiên và F1-F9 của ticket 01; ghi p95 ở 500 Bước theo ngưỡng của spike. Mô-đun trượt thì sửa mô-đun, không
   đưa dagre trở lại (V4.25).
   Một test pytest, `packages/python/dw_agent_runtime/tests/unit/test_builder_fixtures.py` (dấu `unit`), nạp mỗi
   fixture F1-F9 của ticket 01 (`apps/web/lib/__fixtures__/workflows/`) bằng
   `WorkflowDocument.model_validate` của wf-lite, đỏ khi một fixture lệch hình tài liệu, để fixture và mô hình không
   trôi (workflow-engine/01 thêm `error_lane`, `on_error` và các khóa khác vào mô hình); `workflow-layout.ts` đọc làn
   qua danh mục Loại bước, không viết cứng tên làn nào.
3. Trang `/studio/workflows/[id]/builder` (`[id]` là id thành phần của `studio.artifacts`): danh mục Loại bước từ
   `GET /api/v1/studio/node-types` (nhóm, tìm, lý do khóa; không loại `trigger.*` nào, vì `triggers[]` không sửa ở W1)
   trong một Popover có ô tìm mở từ mỗi ô "+" và mỗi ô "Thêm Bước", và trong một bảng bên từ `lg` kéo được vào ô
   (sự kiện con trỏ cùng `screenToFlowPosition` của React Flow, không thêm thư viện kéo thả; ô hợp lệ sáng lên khi
   kéo). Sơ đồ với `nodesDraggable={false}`, `nodesConnectable={false}`, handle ẩn chỉ làm neo cạnh, vẽ mọi thẻ Bước, ô
   "+" và đường nối ở đúng chỗ mô-đun bố cục trả, theo hàng Chuỗi của bảng ngữ pháp R1.5 (một chiều trên xuống dưới,
   ô "+" luôn hiện với vùng chạm ít nhất 24 px, làn trống có ô "Thêm Bước" nét đứt). Thẻ Bước theo R1.8. Cấu hình
   trong antd `Drawer` với `Form` sinh từ `config_schema`, bỏ các khóa làn mà danh mục nêu cho Loại bước (làn chỉ sửa
   trên Sơ đồ), không widget riêng nào (người duyệt nhập theo `config_schema`; bộ chọn người duyệt là W2, Ngoài phạm vi
   của spec), và tab "Khi lỗi". Menu "…" (`Dropdown`) có Thêm trước, Thêm sau, Di chuyển…, Xóa, Sao chép tham chiếu;
   với Loại bước có làn theo khóa (`logic.switch`, `logic.parallel`) menu có thêm "Thêm nhánh" (antd `Modal` hỏi khóa
   của mục `cases` hay tên của mục `branches`) và "Bỏ nhánh…" (chọn làn bằng `Select`), gọi thao tác làn của bước 1;
   đầu làn của ticket 04 gọi cùng hai thao tác đó. "Di chuyển…" mở antd `Modal` với `TreeSelect` các ô đích theo cây,
   không ô nào trong cây con của Bước. Từ `md` một antd `Segmented` "Sơ đồ | Danh sách" ở đầu trang chuyển giữa Sơ đồ
   và `Tree` của bước 6; dưới `md` chỉ có `Tree`. Tên của một Bước trên thẻ, ô "+", vùng `aria-live` và thông báo xóa là
   `description` của nó, hay nhãn tiếng Việt của Loại bước từ danh mục khi không có; trang không tự ghi `description`.
   Khi `GET .../draft` trả 404 (Quy trình chưa có bản Nháp), ticket này hiện antd `Result` "Quy trình chưa có bản Nháp"
   và không gọi route ghi nào; ticket 03 thay nó bằng trạng thái của R3.10 và R3.13.
4. Tự lưu Nháp qua route đã dựng của tenant-config/02: đọc `GET /api/v1/studio/artifacts/{id}/draft`, lưu
   `PUT /api/v1/studio/artifacts/{id}/draft` với `If-Match` là ETag (`version`) của bản đã đọc, ETag mới từ câu trả lời
   cho lần lưu sau (`apps/api/src/dw_api/routes/v1/studio_artifacts.py:285-307`); debounce; chỉ báo "Đang lưu… / Đã lưu
   / Lưu thất bại". Một 412 dừng tự lưu, giữ nguyên nội dung đang gõ và hiện một antd `Alert` "Bản nháp đã đổi ở nơi
   khác" với nút "Tải bản mới nhất", nút đó thay nội dung trên trang bằng bản của máy chủ và xóa ngăn hoàn tác.
5. Bàn phím: `nodesFocusable={false}` và `edgesFocusable={false}`, hay một node nhận focus một lúc; đích focus là antd
   `Button` trong thẻ (`.claude/rules/ui-quality.md` §3: không `onClick` trên `div` hay `Card`); roving focus một điểm
   dừng Tab theo thứ tự tài liệu với các phím của R2.5; `deleteKeyCode`, `panActivationKeyCode`, `selectionKeyCode` và
   `multiSelectionKeyCode` là `null`, ứng dụng tự xóa (mặc định của 12.12.0 là Backspace, Space và Shift, bắt trên cả
   trang, kể cả khi focus ở một nút, đo ngày 24/10/2026; trong ô nhập thư viện chỉ bỏ qua Space và Backspace, đọc ở
   `dist/esm/index.mjs` của gói ngày 25/10/2026); mọi bộ bắt phím bỏ qua `isComposing`; phím đơn chỉ khi Sơ đồ có
   focus (WCAG 2.1.4); Ctrl+Z và Ctrl+Shift+Z chỉ chạy khi focus ở Sơ đồ hay `Tree`, còn trong một ô nhập là hoàn tác
   của chính ô đó.
6. Trợ năng: `ariaLabelConfig` và `ariaLabel` của mỗi cạnh lấy từ khóa thông điệp tiếng Việt hay là `null` (mặc định
   của 12.12.0 là "Edge from … to …", đo ngày 24/10/2026; DO-57); mỗi ô "+" tên "Thêm Bước sau «tên»"; một vùng
   `aria-live` báo mỗi lần thêm, dời, xóa; xóa ngay với thông báo Hoàn tác qua `App.useApp()` nêu tên mọi Bước bị xóa
   (`.claude/rules/ui-quality.md` §10); thông báo đóng khi có thao tác cây mới, nên nút Hoàn tác của nó luôn là đỉnh
   ngăn hoàn tác, tức chính lần xóa đó. Dạng danh sách là antd `Tree` dựng từ cùng cây tài liệu: mỗi Bước một node, mỗi
   làn một node (nhãn của Nhánh ra từ danh mục) lồng dưới Bước của nó, các Bước của làn lồng dưới node làn, và một làn
   rỗng là node làn không con mà menu của nó có "Thêm Bước"; mỗi node của `treeData` truyền `aria-level`,
   `aria-posinset`, `aria-setsize` (antd 6.6.5 không tự phát, đo ngày 24/10/2026), cùng menu thao tác của Sơ đồ, là
   trình dựng chính dưới `md` và ở 320 px; ticket 04 dùng đúng hình này. Playwright ở 320 px và một dự án múi giờ khác.
   Phần của BU7 trên khung chứa và thân vòng lặp (dựng F5) là của ticket 04.

## Tiêu chí chấp nhận

- [ ] R1.4 (BU8): đặt một Bước vào mỗi loại ô (nút "+" trên đường nối, ô "Thêm Bước" của làn trống, kéo từ bảng bên,
      kéo một Bước có sẵn) → tài liệu khác bản trước đúng một thao tác chèn hay dời ở làn và chỉ số của ô, không tọa
      độ, không đường nối; kéo thẻ ra chỗ trống → tài liệu và Mã băm nội dung không đổi; kéo từ một Nhánh ra → không
      đường nối nào; bật `nodesDraggable` hay `nodesConnectable` → test thành phần đỏ; round-trip tài liệu → cây → tài
      liệu của F1-F9 bằng sâu tài liệu đầu, kể cả khóa tùy chọn vắng vẫn vắng; thêm một khóa vị trí khi round-trip → test
      đỏ.
- [ ] R1.4 (BU8): thao tác cây (test đơn vị của `workflow-graph.ts`): dời một `logic.switch` vào một làn của chính nó → bị từ chối,
      tài liệu không đổi; bỏ một mục `cases` còn hai Bước → trả tên cả hai Bước như một lần xóa, Hoàn tác trả đúng tài
      liệu cũ; đặt `on_error` của F4 khác `route` → làn lỗi bị bỏ như một lần xóa; 1 000 Bước mới chèn liên tiếp vào F1 →
      1 000 id khác nhau khớp `^[a-z][a-z0-9_]{0,39}$`, không id nào trùng id đã có; bỏ kiểm cây con khi dời → test đỏ.
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
- [ ] R2.1: bấm một ô "+" → Popover bảng chọn có ô tìm, nhóm theo nhóm, nêu lý do khóa, không loại `trigger.*` nào;
      chọn một Loại bước → Bước vào đúng ô đó; từ `lg` bảng bên kéo được vào ô, dưới `lg` không có bảng bên; mở một
      `logic.switch` → Drawer với Form sinh từ `config_schema`, không ô nào cho `cases` hay `default`; cho Form hiện khóa
      làn → test thành phần đỏ.
- [ ] R2.2: ở 320 px không có cuộn ngang.
- [ ] R2.3: tự lưu gửi `PUT /api/v1/studio/artifacts/{id}/draft` với `If-Match` là ETag của bản Nháp đã đọc, và lần
      lưu sau mang ETag mà câu trả lời trước trả; bỏ header → test thành phần đỏ.
- [ ] R2.4 (BU4): hai tab lưu cùng Nháp → tab sau nhận 412, nội dung đang gõ giữ nguyên, tự lưu dừng (không lời gọi
      `PUT` nào nữa tới khi bấm "Tải bản mới nhất"); bấm nút → trang mang bản của máy chủ và ETag mới.
- [ ] R2.5 (BU7): Playwright dựng F1 chỉ bằng bàn phím, không chuột: đặt Bước qua menu "…" (cả "Thêm trước" ở Bước
      đầu của một làn không rỗng, vào chỉ số 0) và ô "Thêm Bước", dời một Bước qua "Di chuyển…", xóa rồi hoàn tác bằng
      Ctrl+Z và làm lại bằng Ctrl+Shift+Z, mở và đóng cấu hình, Ctrl+K "Đi tới Bước"; Ctrl+Z khi focus trong một ô nhập
      của Drawer không đổi cây; phím mũi tên không bao giờ dời node; bỏ đường bàn phím của một ô → test đỏ.
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
- [ ] R2.9 (BU12): Bước lạ và Bước mới (test thành phần): F1 thêm một Bước `x.unknown@1` có `config` chứa một mảng Bước → thẻ "Loại
      bước không có trong danh mục", menu chỉ có Sao chép tham chiếu, Xóa và dời không có ở đâu; cho xóa Bước lạ → test
      đỏ; chèn một `logic.switch` → `config` có `default: []` và giá trị `default` của schema, không `description`, làn
      "Khác" có ô "Thêm Bước"; ô "+" sau Bước đó tên "Thêm Bước sau «nhãn Loại bước»".
- [ ] Xong: `pnpm -C apps/web test && pnpm -C apps/web e2e -- workflow-builder && uv run python -m pytest packages/python/dw_agent_runtime/tests/unit/test_builder_fixtures.py` xanh.

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
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): từ gate ticket 01: bước 2 thêm test `model_validate` cho F1-F9 và việc đọc làn qua danh mục, vì fixture của ticket 01 là tài liệu `dw.workflow/v1` đúng hình wf-lite và ticket 01 không chờ workflow-engine/01; `workflow-layout.ts` viết ở đây, bản nháp của spike bị xóa; trang builder dựng trên `apps/web/app/studio/workflows/[id]/builder/canvas/workflow-canvas.tsx` của ticket 01. Nếu sai thì: test fixture dời về ticket 01, và ticket 01 chờ workflow-engine/01.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness trên `0baced0` (builder check trong một subagent, không boundary walk: ticket không thêm migration hay route; lượt xác nhận ngữ cảnh mới sau các sửa), 0 CRITICAL, 19 HIGH đã sửa theo khuyến nghị, mỗi quyết định ở dòng 4/11/2026 của spec hay ngay dưới đây. Lượt đầu: (1) diff theo id Bước là của `diff_steps` của wf-lite, `workflow-graph.ts` không viết diff thứ hai (failure-modes #2); (2) Form bỏ khóa làn, thêm và bỏ làn là thao tác cây, bỏ làn còn Bước là một lần xóa có Hoàn tác; (3) "widget riêng (điểm gắn, người duyệt)" trái dòng W2 "chọn người duyệt" của spec: bỏ; (4) id Bước mới sinh ngẫu nhiên theo regex của ADR-0112 (Accepted), không dùng lại; (5) Ctrl+Z chỉ ở Sơ đồ và `Tree`; (6) "Thêm trước" cho chỉ số 0 bằng bàn phím; (7) "Di chuyển…" từ chối đích trong cây con; (8) `Segmented` "Sơ đồ | Danh sách" từ `md`; (9) không loại `trigger.*` trong bảng chọn, sửa `triggers[]` là W2 (Ngoài phạm vi); (10) round-trip so sâu tài liệu, không hàm băm TS; (11) dòng Xong chạy cả Playwright. Lượt xác nhận: (12) `Tree` có node làn; (13) `config` ban đầu theo `default` của schema và làn rỗng; (14) "Thêm nhánh", "Bỏ nhánh…" ở menu "…"; (15) thứ tự bàn phím là thứ tự trước, ô "Thêm Bước" của làn rỗng là điểm dừng; (16) thông báo xóa đóng khi có thao tác mới; (17) Bước của Loại bước lạ không xóa, không dời được, vì trang không biết làn của nó; (18) 404 của `GET .../draft` hiện `Result`, không gọi ghi; (19) test fixture pytest có tên tệp và vào dòng Xong. Nếu sai thì: xem `Nếu sai thì:` của dòng 4/11/2026 trong spec; với (12)-(19): `Tree` lồng Bước thẳng dưới Bước cha, Bước mới mang `config` rỗng, thêm làn ở đầu làn của ticket 04, thứ tự bàn phím theo làn trước Bước kế, Hoàn tác của thông báo chỉ đảo riêng lần xóa, Bước lạ xóa được kèm cảnh báo, ticket 02 tự tạo Nháp, test fixture viết trong Vitest.
- 2026-11-04 (agent): MEDIUM để lại cho người dựng: (a) `PUT .../draft` chuẩn hóa tài liệu bằng `canonical_document`, từ chối số thực và chuỗi không NFC (ADR-0112 (Accepted) Amendments 2026-11-03), nên Form gửi số theo kiểu mà `config_schema` khai và hiện 422 của lần lưu đó dưới "Lưu thất bại" với `pointer` của máy chủ; (b) mỗi lần lưu ghi một audit `studio.artifact.draft_saved` (`packages/python/dw_studio/src/dw_studio/core/application/service.py:439-446`), nên debounce ít nhất 2 s và không lưu khi tài liệu không đổi; (c) sau 412, "Tải bản mới nhất" thay nội dung trên trang mà không hỏi, vì nội dung đang gõ còn nhìn thấy tới khi bấm; (d) route builder chỉ có ý nghĩa với kind `workflow`: một `[id]` của kind khác hiện `Result` 404 như id không tồn tại; (e) tên tệp Playwright là `apps/web/e2e/workflow-builder.spec.ts`, mà dòng Xong lọc theo `workflow-builder`; (f) "nhãn của Nhánh ra" và "nhãn Loại bước" là nhãn tiếng Việt mà `node-types` trả (workflow-nodes:R1.2), không dịch ở trang.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
