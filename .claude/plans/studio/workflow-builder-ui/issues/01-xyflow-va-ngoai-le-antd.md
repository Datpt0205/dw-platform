# 01 — Thử nghiệm Sơ đồ có cấu trúc, rồi ngoại lệ antd-only cho `@xyflow/react` và bộ từ vựng của Sơ đồ

Status: ready-for-agent
Blocked by: .claude/plans/studio/studio-skeleton/issues/03-seam-web-va-allowlist-antd.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.9, BU1, BU14

## Mục tiêu

Đo trên một bản nháp không commit rằng Sơ đồ có cấu trúc chạy được dưới ngăn xếp của repo (phép đo FOG-51 của
discovery/24, trừ hai phép đo cần người thật, ở lại discovery/24), rồi commit phần giữ lại: `@xyflow/react` vào
`apps/web` chỉ ở đường dẫn canvas của builder, như ngoại lệ có ADR của allowlist `antd-only.test.ts`, cùng thành phần
canvas đầu tiên import nó, không kèm thư viện bố cục nào; fixture F1-F9 là tài liệu `dw.workflow/v1` đúng hình của
wf-lite; và bộ từ vựng của Sơ đồ ghi một lần trong theme của `@dw/ui` để Đạt duyệt (workflow-builder-ui R1.1, R1.2,
R1.3, R1.9, BU1, BU14).

## Việc cần làm

1. Bản nháp đo, không commit: một trang thử `apps/web/app/studio/spike/canvas/page.tsx` sau CSP hiện có
   (`apps/web/lib/csp.ts:16-21`), với `@xyflow/react` 12.12.0 và không dagre: bản nháp của mô-đun thuần
   `apps/web/lib/workflow-layout.ts`; thẻ antd, làn, khung chứa, ô "+", làn lỗi, mũi tên quay lại; `Tree`; mô hình bàn
   phím của R2.5; kéo từ bảng bên và kéo một Bước có sẵn vào ô; thẻ Quy trình con (`flow.subworkflow@1`, bậc B của W1,
   V4.33) và các loại W2 (`logic.map@1`, làn "Hết hạn") chỉ để xem, trên cùng các khối. Trang thử, bản nháp
   `workflow-layout.ts`, `Tree`, bàn phím, kéo thả và kịch bản Playwright của phép đo bị xóa trước commit; số đo vào
   ADR-0101 (Accepted). `workflow-layout.ts` và các test của nó là của ticket 02, viết lại từ bài học ghi ở ADR.
2. Fixture, commit, ở `apps/web/lib/__fixtures__/workflows/`: F1 (15 Bước tiếp nhận lead), F2 (`logic.switch@1` 8 làn
   lồng 2 tầng), F3 (song song ×3 trong vòng lặp trong `logic.switch@1`), F4 (làn lỗi ở mọi Bước), F5 (vòng làm lại có
   phê duyệt, cùng một phê duyệt nhiều người bắt buộc), F6 và F7 (300 và 500 Bước, đúng trần nền tảng
   `MAX_TREE_STEPS`), F8 (tên tiếng Việt dài nhất), F9 (duyệt ba cấp mà từ chối quay về các Bước trước khác nhau theo lý
   do, bằng vòng lặp lồng nhau và Thoát vòng lặp, để thử giới hạn của cây). Mỗi fixture là một tài liệu `dw.workflow/v1`
   đúng hình wf-lite giữ, không một hình thứ hai (CLAUDE.md "Agent and tool rules"; ADR-0112 (Accepted) Amendments
   2026-11-03): Bước là `{id, type, config, description?}` cộng các khóa workflow-engine/01 thêm (`retry`, `timeout_s`,
   `on_error`, `error_lane`); `type` mang hậu tố phiên bản (`logic.switch@1`); làn nằm trong `config` dưới tên Nhánh
   ra (`approved`, `rejected` của `human.approval@1`; `cases` từng giá trị và `default` của `logic.switch@1`; `body` và
   `max_reached` của `logic.loop@1`, workflow-nodes:R11.2), làn lỗi là khóa `error_lane` của Bước khi `on_error` là
   `route`; cấu hình của các loại bậc B theo workflow-nodes:R10.1 (song song, mỗi làn một khóa
   `^[a-z][a-z0-9_]{0,39}$`; tạm đặt dưới `config.branches` như `cases` của `logic.switch@1`), R11.1 (`max_iterations`
   và điều kiện), R12.1 (`approval_rule` `all`) và R13.1 (`workflow` là `api_name`), và ticket workflow-nodes đăng ký
   một loại với hình khác sửa fixture cùng thay đổi đó; tên Bước người dựng đặt là `description`, trường mà Sơ đồ chỉ
   đọc của wf-lite hiện làm tên Bước. Fixture là tài liệu Studio: không `key`, không `version` (phong bì giữ chúng,
   ADR-0109 (Accepted) quyết 1), tệp JSON. Số Bước và độ sâu đếm như workflow-engine/01 bước 1: mọi Bước ở mọi làn, kể
   cả `error_lane`, không đếm `triggers[]`; Bước ở `steps[]` có độ sâu 1; F7 đúng 500, không fixture nào sâu quá 10.
   Một tệp danh mục giả `catalogue.json` cùng thư mục, theo hình `GET /api/v1/studio/node-types` (workflow-nodes:R1.2),
   nêu cho mỗi loại nguồn làn của nó như `NodeTypeSpec.lanes(config)` liệt kê (`registry.py:54-70`): danh sách Nhánh ra
   cố định (`approved`, `rejected`; `body`, `max_reached`), hay một khóa map mà mỗi khóa con là một làn (`cases`,
   `branches`) cùng làn `default` khi có; `error_lane` thuộc mọi Bước, không vào danh mục. Bản nháp bố cục đọc làn qua
   danh mục đó, không viết cứng tên làn nào. Ticket 02 thêm test nạp từng fixture bằng
   `WorkflowDocument.model_validate` khi workflow-engine/01 đã thêm các khóa đó.
3. Bảng đo (đo → ngưỡng → quyết định). Hàng CSP và lớp CSS và hàng React 19 là cổng: một trong hai trượt thì không
   thêm mục `EXCEPTIONS` và không ghim gói; ticket để mở, số đo và nguyên nhân ghi thành một Amendments của
   ADR-0101 (Accepted), và theo V4.25 cách sửa là sửa mã của ta hay bỏ một tính năng của thư viện, không thêm thư viện. Các hàng
   còn lại ghi số vào ADR-0101 (Accepted) và ra quyết định nêu ở hàng; không hàng nào trong chúng giữ ticket mở:
    - vi phạm CSP ở `next build && next start` và ở `next dev`, và CSS của `@xyflow/react` bị lớp antd đè → 0 → cấp
      ngoại lệ;
    - JS tải đầu của route canvas: tổng gzip của mọi chunk JS trình duyệt tải từ lúc điều hướng tới khi thẻ Bước đầu tiên
      (`.react-flow__node`) hiện, đo bằng Playwright trên `next build && next start`, tách phần chung, phần antd và phần
      `@xyflow/react` cùng phụ thuộc, so với cùng route không có canvas; không lấy cột "First Load JS" của `next build`,
      vì nó không đếm chunk của `next/dynamic` → ghi kB vào ADR-0101 (Accepted), ngoài ngân sách khoảng 250 kB của
      antd;
    - React 19, bản build Next 15.5, StrictMode của `next dev`, `next/dynamic` với `ssr: false`, lockfile có một
      `zustand` ≥4.5.6, không 5.x → 0 lỗi console và 0 `pageerror` lúc chạy → giữ bản ghim (CI của React Flow chỉ chạy
      React 18);
    - bố cục F1-F9 theo bất biến của R1.6 (snapshot, kiểm trên cây ngẫu nhiên sinh bằng hạt cố định, không hai thẻ chồng
      nhau), p95 của hàm bố cục ở F7 (500 Bước), 200 lần chạy ấm trong Node → ≤ 50 ms, thành ngưỡng của property test ở
      ticket 02; bản nháp trượt thì bài học ghi vào ADR-0101 (Accepted) và ticket 02 sửa mô-đun (tham khảo `flow-canvas-utils.ts`
      của Activepieces, MIT, có ghi công), không đưa dagre trở lại (V4.25);
    - F6 và F7 với thẻ antd: thời gian từ điều hướng tới thẻ đầu tiên, khung hình khi pan và zoom, bộ nhớ heap, có và
      không `onlyRenderVisibleElements`, khung thu gọn qua `hidden`, roving focus còn sống qua culling → so với ngân sách
      trang của `.claude/rules/latency.md` (P95 ≤ 1 s, P99 ≤ 2 s) và ≥ 30 fps khi pan và zoom; quyết định có bật
      `onlyRenderVisibleElements` không. Trần số Bước không do ticket này đặt: W1 giữ trần nền tảng 500 Bước và độ sâu
      10, như nhau cho mọi gói (workflow-engine:R2.10, mã `wf.limit_above_plan`; ADR-0112 (Accepted) Amendments
      2026-11-03); F7 trượt ngân sách cả khi bật culling thì ticket ghi số vào ADR-0101 (Accepted) và đề xuất hạ trần thành một dòng
      Quyết định của workflow-engine;
    - Playwright chỉ bàn phím trên bản nháp: dựng F5, dời một Bước, xóa rồi hoàn tác, mở và đóng cấu hình, vào và ra khung
      chứa, sang làn kế, Ctrl+K; phím mũi tên không bao giờ dời node → ghi được hay không cho R2.5, bài học cho ticket 02;
    - 320 px và cảm ứng (Playwright, viewport 320 px với `hasTouch`): `Tree` là trình dựng, không cuộn ngang, ô ≥ 24 px,
      kéo bằng tay vào ô chạy được hay có đường qua menu → YC39;
    - nhìn bằng mắt qua ảnh chụp Playwright: chế độ tối; tương phản ≥ 3:1 cho đường nối, ô "+" và vòng focus; màu không
      bao giờ một mình; giảm chuyển động tắt mọi chuyển tiếp; huy hiệu ghi công không bị Drawer che ở ≥ `lg`, ở `md` và ở
      320 px → bộ từ vựng của bước 4.
      Khi một hàng cổng trượt, phần không cần gói vẫn commit: fixture, danh mục giả, bộ từ vựng, `theme-contrast.test.ts`
      và `canvas-colours.test.ts`; ghim gói, `workflow-canvas.tsx`, CSS lớp và mục `EXCEPTIONS` thì không.
      Hai phép đo cần người thật không thuộc ticket này và ticket không chờ chúng: NVDA tiếng Việt trên `Tree`, và năm người
      dùng nghiệp vụ làm nhiệm vụ có kịch bản (người tham gia chờ DO-22, Chủ: Đạt). Chúng ở lại discovery/24, chạy trên
      builder thật sau ticket 04, và kết quả ghi vào ADR-0101 (Accepted).
4. Bộ từ vựng của Sơ đồ (V4.27): agent dựng bản nháp, gồm màu nhóm từ token của theme (trigger xanh dương, AI tím, dữ
   liệu cyan, logic vàng, con người hồng tím, công cụ xanh lá, lỗi đỏ), mỗi màu đạt 3:1 trên nền thẻ ở cả chế độ sáng và
   tối, không là sắc nhạt preset của antd (`.claude/rules/ui-quality.md` §12); một biểu tượng `@ant-design/icons` mỗi
   nhóm; cỡ thẻ; kiểu đường nối. Ghi một lần cạnh `buildTheme` của `@dw/ui` (`packages/typescript/ui/src/theme.ts`) để
   Đạt duyệt; `apps/web/lib/__tests__/theme-contrast.test.ts` đo mỗi màu nhóm ở hai chế độ. Ticket 04 đọc giá trị từ
   theme, nên Đạt đổi giá trị lúc duyệt mà không ticket nào đổi.
5. Ghim chính xác `@xyflow/react` 12.12.0 trong `apps/web/package.json`, không thư viện bố cục nào, không thêm
   devDependency nào; một test đọc `pnpm-lock.yaml` đỏ khi lockfile có hơn một `zustand`, một bản dưới 4.5.6 hay một bản
   5.x.
6. Thành phần canvas, commit: `apps/web/app/studio/workflows/[id]/builder/canvas/workflow-canvas.tsx`, tệp đầu tiên
   import `@xyflow/react`, trong một thư mục không có `page.tsx` nên không thành route; ticket 02 dựng trang builder trên
   nó. Nó nhận node và cạnh dạng hình thuần qua props, không tự tính vị trí, và vẽ mỗi thân Bước bằng antd `Card` với
   `description` của Bước; được nạp bằng `next/dynamic` với `ssr: false` từ một thành phần client ngoài thư mục canvas
   (ticket 02). Kiểu props là `CanvasShapes` (thẻ `{id, x, y, description}`, đường nối `{id, from, to}`) khai trong
   `apps/web/lib/workflow-shapes.ts`, ngoài glob canvas, không import gì; `workflow-layout.ts` của ticket 02 trả đúng
   kiểu đó và mở rộng nó tại chỗ. Thành phần tự đổi `CanvasShapes` sang `Node` và `Edge` của React Flow, và thẻ có
   `Handle` ẩn với `isConnectable={false}` chỉ làm neo cạnh. Cấu hình React Flow theo ADR-0101 (Accepted) quyết 3: `nodesDraggable`, `nodesConnectable`,
   `nodesFocusable`, `edgesFocusable` là `false`; `deleteKeyCode`, `panActivationKeyCode`, `selectionKeyCode`,
   `multiSelectionKeyCode` là `null`. antd vẽ mọi thân Bước, nhãn làn, đầu khung chứa, menu, Popover, biểu mẫu trong
   Drawer, thông báo và nút thu phóng (antd `Button` trong một `Panel` của React Flow); không dùng `MiniMap`, `Controls`,
   `NodeToolbar`. `@xyflow/react/dist/base.css` vào `@layer components` bằng `@import "@xyflow/react/dist/base.css"
layer(components);` trong một tệp `.css` cạnh thành phần, dưới glob canvas, cùng ánh xạ `--xy-*` sang `--ant-*` trong
   cùng lớp, không giá trị dự phòng literal; không import `base.css` từ tệp `.ts`/`.tsx`, vì CSS nạp như thế không ở lớp
   nào và thắng cả lớp antd lẫn utilities. Giữ huy hiệu React Flow ở góc dưới trái bằng `attributionPosition`, không ẩn
   khi chưa mua Pro (DO-42.2, V4.25).
7. Thêm một mục `EXCEPTIONS` `{module, glob, adr}` (`@xyflow/react`, glob `app/studio/**/canvas/**` tính từ `apps/web`,
   ADR-0101 (Accepted)) vào allowlist mà studio-skeleton/03 dựng trong `apps/web/lib/__tests__/antd-only.test.ts`, cùng
   commit với `workflow-canvas.tsx`; khẳng định chỉ `apps/web` khai báo gói và chỉ tệp dưới glob import nó; không mục nào
   cho `@dagrejs/dagre`. Thêm override ESLint tương ứng. `CLAUDE.md` mục Web UI đã chỉ nêu `@xyflow/react` (V4.25,
   V4.29); ticket này không sửa nó.
8. Test màu literal, `apps/web/lib/__tests__/canvas-colours.test.ts`: quét mọi tệp `.ts`, `.tsx`, `.css` dưới
   `app/studio/**/canvas/**` cùng `lib/workflow-layout.ts` và `lib/workflow-graph.ts` khi có; đỏ khi gặp một màu hex
   (`#rgb`, `#rrggbb`, `#rrggbbaa`), một hàm màu (`rgb(`, `rgba(`, `hsl(`, `hsla(`, `hwb(`, `lab(`, `lch(`, `oklab(`,
   `oklch(`, `color(`) ở bất cứ đâu ngoài chú thích, hay một tên màu CSS (trừ `transparent`, `currentColor`, `inherit`)
   làm giá trị của một khai báo màu hay một biến tùy biến (`--*`, kể cả `--xy-*`) trong tệp `.css`, hay của `style`,
   `stroke`, `fill`, `color` trong tệp `.tsx` (`<Tag color="magenta">` cũng đỏ: sắc preset, `ui-quality.md` §12); gốc
   quét là tham số để ca âm dùng một cây thử.

## Tiêu chí chấp nhận

- [ ] R1.1: `@xyflow/react` 12.12.0 ghim chính xác trong `apps/web/package.json`; `apps/web/package.json` và
      `packages/typescript/ui/package.json`, hai manifest mà allowlist đọc, không khai thư viện bố cục nào, vì allowlist
      không có mục cho nó; chỉ tệp dưới glob canvas import gói (allowlist, không đếm tệp); lockfile có đúng một `zustand`
      ≥4.5.6, thêm một bản 5.x hay hạ về dưới 4.5.6 → test lockfile đỏ.
- [ ] R1.2 (BU1): với mục `EXCEPTIONS` thật, một cây thử có `app/approvals/a.tsx` import `@xyflow/react` →
      `antd-only.test.ts` đỏ; khai báo gói trong `@dw/ui` → đỏ; `apps/web` khai `@dagrejs/dagre` → đỏ; gỡ mục allowlist
      có ADR → test đỏ, nêu `workflow-canvas.tsx`.
- [ ] R1.3: test thành phần render `workflow-canvas.tsx` với hai node và một cạnh (shim `ResizeObserver` và
      `DOMMatrixReadOnly` trong vitest): mỗi thân Bước là một antd `Card` mang `description`; không phần tử nào có lớp
      `react-flow__minimap`, `react-flow__controls` hay `react-flow__node-toolbar`; huy hiệu có lớp `bottom` và `left`;
      không `.react-flow__node` nào có lớp `draggable` hay `tabindex`, không handle nào có lớp `connectable`;
      `nodesDraggable`, `nodesConnectable` hay `nodesFocusable` thành `true` → test đỏ (phím mặc định của thư viện là
      R2.7, kiểm ở ticket 02 bằng Playwright).
- [ ] R1.9 (BU14): bộ từ vựng nằm một lần trong theme của `@dw/ui`; `theme-contrast.test.ts` đọc mỗi màu nhóm và
      khẳng định ≥ 3:1 trên nền thẻ ở hai chế độ; hạ một màu dưới 3:1 → test đỏ; trong cây thử của
      `canvas-colours.test.ts`, mỗi ca `#1677ff`, `rgba(0,0,0,.45)`, `hsla(0,0%,0%,.5)` và `background: white` trong một
      tệp dưới glob canvas → đỏ, nêu tệp; `var(--ant-color-border)` → qua.
- [ ] R1.1: số đo của bước 3 (kB gzip theo cách đo ở đó, p95 bố cục ở F7, thời gian tới thẻ đầu, khung hình và bộ nhớ ở
      F6 và F7, lỗi CSP = 0, lỗi lúc chạy = 0) ghi vào ADR-0101 (Accepted); F1-F9 và danh mục giả có trong
      `apps/web/lib/__fixtures__/workflows/`.
- [ ] Xong: `pnpm -C apps/web test` xanh.

## Nguồn

- `apps/web/package.json:20`; spec: R1.1 (chưa có gói sơ đồ).
- `apps/web/lib/__tests__/antd-only.test.ts:14`; spec: R1.2 (đọc cả `@dw/ui`).
- `apps/web/lib/csp.ts:16-21`; spec: R1.1 (nonce, `strict-dynamic`).
- `CLAUDE.md:140-153`; spec: R1.2 (allowlist, chỉ `@xyflow/react` dưới glob canvas). ADR-0101 (Accepted).
- `packages/typescript/ui/src/theme.ts:3-6`, `apps/web/lib/__tests__/theme-contrast.test.ts:8-11`; spec: R1.9 (một chủ
  của màu, tương phản đo từ theme).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/document.py:32-36`,
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/registry.py:54-70`; ADR-0112 (Accepted) Amendments
  2026-11-03 (một hình `dw.workflow/v1`, làn trong `config`, `error_lane`, trần 500 và độ sâu 10).
- `.claude/plans/studio/discovery/issues/24-workflow-canvas.md`; FOG-51.

## Comments

- 2026-10-23 (agent): DO-42 còn mở — Đạt sửa `CLAUDE.md` "Web UI" khi nhận ADR-0101 (Accepted); giữ needs-info đến
  lúc đó.
- 2026-10-23 (agent): DO-42 đã có lời đáp (Đạt 23/10/2026: `@xyflow/react` và `@dagrejs/dagre` cùng ngoại lệ, một glob canvas, allowlist `{module, glob, adr}`, giữ huy hiệu, không thư viện biểu đồ ở v1), nên ticket về `needs-triage`; việc đổi guard thành allowlist thuộc studio-skeleton/03, ticket này chỉ thêm mục `EXCEPTIONS`.
- 2026-10-25 (agent): lượt g, theo V4.25, V4.27 và V4.29 của Đạt ngày 24/10/2026: ticket là spike của discovery/24 cho Sơ đồ có cấu trúc (fixture F1-F9, bảng đo không còn mục dagre), `@dagrejs/dagre` rời ngoại lệ nên chỉ một mục `EXCEPTIONS`, huy hiệu ở góc dưới trái, một `zustand`, và bộ từ vựng nháp vào theme của `@dw/ui` để Đạt duyệt (R1.9, BU14). Không thêm cạnh.
- 2026-10-25 (agent): lượt h, theo V4.33 của Đạt: `flow.subworkflow` vào bậc B của W1 và thẻ Quy trình con vào ngữ pháp W1 (R1.5, ticket 04), nên bước 1 thôi gọi nó là loại W2; spike vẫn chỉ vẽ nó để xem. Không thêm cạnh.
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness trên `9f9b0a9` (builder check trong một subagent; không migration, không route API, không màn đọc dữ liệu tenant: trang thử chỉ đọc fixture), 1 CRITICAL và 6 HIGH đã sửa: (1) CRITICAL: hàng 300/500 thẻ quyết "trần số Bước của gói", trái ADR-0112 (Accepted) Amendments 2026-11-03 và workflow-engine:R2.10 (trần nền tảng 500 Bước, độ sâu 10, như nhau mọi gói); giờ ticket đo F6, F7 ở trần đó và chỉ đề xuất hạ qua workflow-engine. Nếu sai thì: usage-and-limits có cột trần theo gói trước W1 và ticket này đề xuất giá trị cho cột đó. (2) fixture chưa có hình nên dễ thành một cây thứ hai bên cạnh `dw.workflow/v1` của wf-lite (CLAUDE.md "Agent and tool rules", một hiện thực): giờ F1-F9 là tài liệu đúng hình wf-lite (làn trong `config` dưới tên Nhánh ra, `error_lane`, `type` có `@1`, tên ở `description`), làn đọc qua danh mục giả theo `node-types`, ticket 02 thêm test `model_validate`. Nếu sai thì: bố cục nhận `OutlineStepView` (`lanes: [{port, steps}]`) mà máy chủ chiếu từ `iter_lanes`, và fixture là dạng chiếu đó. (3) "không giữ mã thử" mâu thuẫn với "mục `EXCEPTIONS` cùng import canvas đầu tiên", với R1.2 "gỡ mục → đỏ" (không còn tệp nào import) và với ticket 02 dùng F1-F9: giờ trang thử, bản nháp bố cục, `Tree`, bàn phím và kéo thả bị xóa, còn fixture, `workflow-canvas.tsx`, CSS lớp, theme và test ở lại. Nếu sai thì: ghim gói và mục `EXCEPTIONS` dời sang ticket 02 cùng trang builder, ticket này chỉ đo. (4) NVDA bằng tai và năm người dùng (chờ DO-22) không agent nào làm xong, nên ticket không đóng được: hai phép đo ở lại discovery/24, chạy trên builder thật sau ticket 04. Nếu sai thì: ticket tách thêm một ticket `ready-for-human` trong khu này. (5) "JS tải đầu của route canvas" không nói cách đo, mà cột "First Load JS" của `next build` không đếm chunk `next/dynamic` (đo: 104 kB cho route có canvas, bằng `/_not-found`): giờ là gzip mọi chunk tới thẻ đầu, đo bằng Playwright. Nếu sai thì: đo bằng `@next/bundle-analyzer`, một devDependency cần mục `DEV_ONLY`. (6) ngưỡng và đường trượt: p95 bố cục ≤ 50 ms ở F7, ngân sách trang của `latency.md`, ≥ 30 fps; chỉ hàng CSP và lớp CSS và hàng React 19 chặn ngoại lệ. Nếu sai thì: mọi hàng là cổng, và ticket chờ đến khi bố cục và hiệu năng đạt. (7) test màu literal của R1.9 và BU14 chỉ nêu `#`, `rgb(`, `hsl(`, nên `rgba(`, `hsla(` và `white` lọt (failure-modes #0): giờ `canvas-colours.test.ts` có danh sách hàm màu và tên màu; spec BU14 sửa theo. Nếu sai thì: test chỉ bắt hex và hàm màu, tên màu để review.
- 2026-11-03 (agent): đo trong một thư mục nháp ngoài repo, theo failure-modes #4 (Next 15.5.25, React 19.2.8, antd 6.6.5, `@ant-design/nextjs-registry` 1.3.0 với `layer`, Tailwind 4.3.3, `@xyflow/react` 12.12.0; CSP nonce cùng `strict-dynamic` như `lib/csp.ts`; mỗi node một antd `Card` và `Button`; Playwright Chromium headless trên Windows): pnpm giải đúng một `zustand@4.5.7`; build production và `next dev` (StrictMode) 0 lỗi console, 0 `pageerror`, 0 vi phạm CSP; `@import "@xyflow/react/dist/base.css" layer(components);` trong một tệp `.css` dưới thư mục canvas được Tailwind 4.3.3 gộp vào `@layer components` (0 luật `react-flow__node` ngoài lớp); "First Load JS" của route 104 kB; JS gzip thật tới thẻ đầu 259 kB: 103 kB chung của Next và React, khoảng 53 kB thư viện (`@xyflow/react` 21 kB; `@xyflow/system`, d3 và `zustand` 32 kB), khoảng 95 kB antd mà app thật đã nạp ở layout; 500 thẻ: thẻ đầu sau khoảng 1,6 s từ lúc điều hướng, khoảng 1,0 s với `onlyRenderVisibleElements` (8 node trong DOM), heap khoảng 40 MB, pan và zoom 60 fps headless (không thay máy thật); huy hiệu có lớp `bottom left` ở góc dưới trái. `next/dynamic` với `ssr: false` phải gọi trong một tệp `"use client"`. Bước 3 vẫn đo lại trên app thật, với theme, `AppFrame` và layout.
- 2026-11-03 (agent): MEDIUM để lại cho người dựng: (a) bộ từ vựng: khuyến nghị một export riêng cạnh `buildTheme` trong `theme.ts`, mỗi màu nhóm một giá trị cho mỗi chế độ, "nền thẻ" là `colorBgContainer` của chế độ đó (nền của antd `Card`); (b) `@xyflow/react` 12.12.1 ra ngày 2/11/2026; ghim vẫn 12.12.0 theo V4.25, nâng là một thay đổi có chủ đích với phép đo mới (ADR-0101 (Accepted) Consequences); (c) test lockfile đọc cả workspace, nên một gói ngoài `apps/web` cần `zustand` 5 cũng bị chặn; đó là lời Đạt (V4.25), sửa thì sửa lời đó; (d) jsdom không có `ResizeObserver` và `DOMMatrixReadOnly`; shim chỉ ở `vitest.setup.ts` hay ngay trong test, không thêm gói; (e) `workflow-canvas.tsx` chưa có trang nào nạp tới ticket 02; đó là thành phần có test, không phải mô-đun giữ chỗ (CLAUDE.md "Work style" 6).
- 2026-11-03 (agent, theo ủy quyền 31/10/2026): lượt xác nhận ngữ cảnh mới sau các sửa trên, 3 HIGH đã sửa: (1) cấu hình các loại bậc B và chỗ đặt làn của chúng trong fixture theo workflow-nodes:R10.1, R11.1, R11.2, R12.1, R13.1, làn song song tạm dưới `config.branches`, và ticket workflow-nodes đăng ký loại sửa fixture cùng thay đổi (spec "Kiểm lại khi"); (2) danh mục giả nêu nguồn làn của mỗi loại (Nhánh ra cố định, hay khóa map như `cases`, `branches` cùng `default`), `error_lane` ngoài danh mục; (3) props của `workflow-canvas.tsx` là `CanvasShapes` trong `apps/web/lib/workflow-shapes.ts` mà `workflow-layout.ts` của ticket 02 trả, thẻ có `Handle` ẩn làm neo cạnh. Cùng lượt, sửa tại chỗ: fixture không `key`, `version`, tệp JSON; cách đếm 500 Bước và độ sâu 10 như workflow-engine/01; khi hàng cổng trượt thì phần không cần gói vẫn commit; test màu thấy biến `--*` và prop `color`; R1.1 nói allowlist theo glob, không đếm tệp. Nếu sai thì: làn song song nằm ở khóa cấp `config` theo tên làn, và fixture đổi khi workflow-nodes/R10.1 quyết; canvas nhận `Node` và `Edge` của React Flow dựng sẵn, và kiểu đó sống dưới glob canvas.
- 2026-11-03 (agent): MEDIUM thêm từ lượt xác nhận: (f) màu nhóm khóa theo mã nhóm mà danh mục `node-types` trả (R2.1), không theo tiền tố của `type`; "lỗi" là màu của làn lỗi và huy hiệu "Khi lỗi", không là một nhóm Loại bước; (g) màu đường nối đi tới SVG của React Flow qua `--xy-edge-stroke`, nên bộ từ vựng cần cả giá trị TS cho `theme-contrast.test.ts` lẫn biến CSS cho tệp `.css` của canvas; khuyến nghị theme phát chúng thành biến trên lớp `THEME_CSS_VAR_CLASS` như token antd, một chủ, hai cách đọc.
- 2026-11-03 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
