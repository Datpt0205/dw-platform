# 01 — Thử nghiệm Sơ đồ có cấu trúc, rồi ngoại lệ antd-only cho `@xyflow/react` và bộ từ vựng của Sơ đồ

Status: needs-triage
Blocked by: .claude/plans/studio/studio-skeleton/issues/03-seam-web-va-allowlist-antd.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.9, BU1, BU14

## Mục tiêu

Đo trên một nhánh thử rằng Sơ đồ có cấu trúc chạy được dưới ngăn xếp của repo (phép đo FOG-51 của discovery/24), rồi
đưa `@xyflow/react` vào `apps/web` chỉ ở đường dẫn canvas của builder, như ngoại lệ có ADR của allowlist
`antd-only.test.ts`, không kèm thư viện bố cục nào, và ghi bộ từ vựng của Sơ đồ một lần trong theme của `@dw/ui` để Đạt
duyệt (workflow-builder-ui R1.1, R1.2, R1.3, R1.9, BU1, BU14).

## Việc cần làm

1. Nhánh thử theo discovery/24 (`.claude/plans/studio/discovery/issues/24-workflow-canvas.md`): số đo vào
   ADR-0101 (Accepted), không giữ mã thử; ticket khám phá đóng bằng một dòng trỏ tới số đo ở đây; bundle của route
   canvas đo riêng, ngoài ngân sách khoảng 250 kB của antd. Dựng một trang nháp dưới `apps/web/app/studio/**/canvas/**`, sau CSP
   hiện có (`apps/web/lib/csp.ts:16-21`), với `@xyflow/react` 12.12.0 và không dagre: bản nháp của mô-đun thuần
   `apps/web/lib/workflow-layout.ts`; thẻ antd, làn, khung chứa, ô "+", làn lỗi, mũi tên quay lại; `Tree`; mô hình bàn
   phím của R2.5; kéo từ bảng bên và kéo một Bước có sẵn vào ô; thẻ Quy trình con (`flow.subworkflow`, bậc B của W1,
   V4.33) và các loại W2 (`logic.map`, làn "Hết hạn") chỉ để xem, trên cùng các khối. Fixture sinh dưới dạng cây Bước: F1 (15 Bước tiếp nhận lead), F2
   (`logic.switch` 8 làn lồng 2 tầng), F3 (song song ×3 trong vòng lặp trong `logic.switch`), F4 (làn lỗi ở mọi Bước),
   F5 (vòng làm lại có phê duyệt, cùng một phê duyệt nhiều người bắt buộc), F6 và F7 (300 và 500 Bước), F8 (tên tiếng
   Việt dài nhất), F9 (duyệt ba cấp mà từ chối quay về các Bước trước khác nhau theo lý do, bằng vòng lặp lồng nhau và
   Thoát vòng lặp, để thử giới hạn của cây trước khi khóa hình tài liệu).
2. Bảng đo (đo → ngưỡng → quyết định):
    - vi phạm CSP ở bản build và ở `next dev`, và CSS của `@xyflow/react` bị lớp antd đè → 0 → cấp ngoại lệ;
    - JS tải đầu của route canvas (kB gzip), với `@xyflow/react/dist/base.css` trong `@layer components`, `--xy-*` ánh xạ
      sang `--ant-*`, và một test thứ tự lớp đỏ khi sai thứ tự → ghi kB, so ngân sách +250 kB → ADR-0101 (Accepted);
    - React 19, bản build Next 15.5, StrictMode, `next/dynamic` với `ssr: false`, lockfile có một `zustand` ≥4.5.6, không
      5.x → 0 lỗi lúc chạy → giữ bản ghim (CI của React Flow chỉ chạy React 18);
    - bố cục F1-F9 theo bất biến của R1.6 (snapshot, property test trên cây ngẫu nhiên, không hai thẻ chồng nhau), thời
      gian p95 ở 500 Bước → ghi ngưỡng; trượt thì sửa mô-đun (tham khảo `flow-canvas-utils.ts` của Activepieces, MIT, có
      ghi công), không đưa dagre trở lại (V4.25);
    - 300 và 500 thẻ antd: render đầu, khung hình khi pan và zoom, bộ nhớ, có và không `onlyRenderVisibleElements`, khung
      thu gọn qua `hidden`, roving focus còn sống qua culling → trần số Bước của gói (`wf.limit_above_plan`) và có dùng cờ
      đó hay không;
    - Playwright chỉ bàn phím: dựng F5, dời một Bước, xóa rồi hoàn tác, mở và đóng cấu hình, vào và ra khung chứa, sang
      làn kế, Ctrl+K; phím mũi tên không bao giờ dời node → R2.5;
    - 320 px và cảm ứng: `Tree` là trình dựng, không cuộn ngang, ô ≥ 24 px, kéo bằng tay vào ô chạy được hay có đường qua
      menu → YC39;
    - NVDA tiếng Việt trên `Tree`: đọc đúng thứ tự Bước, "nhánh 2 trên 3: …", cấp lồng và trạng thái, báo mỗi lần thêm,
      dời, xóa → `Tree` có đủ cho người dùng trình đọc màn hình không;
    - nhìn bằng mắt: chế độ tối; tương phản ≥ 3:1 cho đường nối, ô "+" và vòng focus; màu không bao giờ một mình; giảm
      chuyển động tắt mọi chuyển tiếp; huy hiệu ghi công không bị Drawer che ở ≥ `lg`, ở `md` và ở 320 px → bộ từ vựng của
      bước 3;
    - năm người dùng nghiệp vụ làm nhiệm vụ có kịch bản (dựng F5 từ một bản mô tả, sửa hai lỗi được báo, trả lời năm câu
      về một Quy trình 60-100 Bước, dựng lại F9), ghi tỷ lệ xong, thời gian, lỗi, Sơ đồ hay `Tree`, và node không kéo
      được hay thiếu minimap có làm họ vướng không; ai tuyển người chờ DO-22, Chủ: Đạt → giữ mô hình có cấu trúc hay mở
      lại.
3. Bộ từ vựng của Sơ đồ (V4.27): agent làm spike dựng bản nháp, gồm màu nhóm từ token của theme (trigger xanh dương, AI
   tím, dữ liệu cyan, logic vàng, con người hồng tím, công cụ xanh lá, lỗi đỏ), mỗi màu đạt 3:1 trên nền thẻ ở cả chế độ
   sáng và tối, không là sắc nhạt preset của antd (`.claude/rules/ui-quality.md` §12); một biểu tượng `@ant-design/icons`
   mỗi nhóm; cỡ thẻ; kiểu đường nối. Ghi một lần cạnh `buildTheme` của `@dw/ui` (`packages/typescript/ui/src/theme.ts`)
   để Đạt duyệt; `apps/web/lib/__tests__/theme-contrast.test.ts` đo mỗi màu nhóm ở hai chế độ. Ticket 04 đọc giá trị từ
   theme, nên Đạt đổi giá trị lúc duyệt mà không ticket nào đổi.
4. Ghim chính xác `@xyflow/react` 12.12.0 trong `apps/web/package.json`, không thư viện bố cục nào; một test đọc
   `pnpm-lock.yaml` đỏ khi lockfile có hơn một `zustand`, một bản dưới 4.5.6 hay một bản 5.x.
5. Import `@xyflow/react` chỉ dưới `apps/web/app/studio/**/canvas/**`; nạp bằng `next/dynamic` với `ssr: false`. antd
   vẽ mọi thân Bước, nhãn làn, đầu khung chứa, menu, Popover, biểu mẫu trong Drawer, thông báo và nút thu phóng (antd
   `Button` trong một `Panel` của React Flow); không dùng `MiniMap`, `Controls`, `NodeToolbar`;
   `@xyflow/react/dist/base.css` nạp một lần vào `@layer components`, `--xy-*` ánh xạ sang `--ant-*`; giữ huy hiệu React
   Flow ở góc dưới trái bằng `attributionPosition`, không ẩn khi chưa mua Pro (DO-42.2, V4.25).
6. Thêm một mục `EXCEPTIONS` `{module, glob, adr}` (`@xyflow/react`, glob `apps/web/app/studio/**/canvas/**`,
   ADR-0101 (Accepted)) vào allowlist mà studio-skeleton/03 dựng trong `apps/web/lib/__tests__/antd-only.test.ts`, cùng
   commit với import canvas đầu tiên; khẳng định chỉ `apps/web` khai báo gói và chỉ tệp dưới glob import nó; không mục
   nào cho `@dagrejs/dagre`. Thêm override ESLint tương ứng. `CLAUDE.md` mục Web UI đã chỉ nêu `@xyflow/react` (V4.25,
   V4.29); ticket này không sửa nó.

## Tiêu chí chấp nhận

- [ ] R1.1: `@xyflow/react` 12.12.0 ghim chính xác trong `apps/web/package.json`, không thư viện bố cục nào trong
      manifest nào, chỉ import dưới `apps/web/app/studio/**/canvas/**`; lockfile có đúng một `zustand` ≥4.5.6, thêm
      một bản 5.x hay hạ về dưới 4.5.6 → test lockfile đỏ.
- [ ] R1.2 (BU1): import `@xyflow/react` từ `apps/web/app/approvals` → `antd-only.test.ts` đỏ; khai báo gói trong
      `@dw/ui` → `antd-only.test.ts` đỏ; `apps/web` khai `@dagrejs/dagre` → `antd-only.test.ts` đỏ; gỡ mục allowlist
      có ADR → đường dẫn builder đỏ.
- [ ] R1.3: một thân Bước render bằng antd; không có màu, kiểu chữ hay bo góc nào đặt ngoài theme antd
      (Tailwind chỉ bố cục).
- [ ] R1.9 (BU14): bộ từ vựng nằm một lần trong theme của `@dw/ui`; `theme-contrast.test.ts` đọc mỗi màu nhóm và
      khẳng định ≥ 3:1 trên nền thẻ ở hai chế độ; hạ một màu dưới 3:1 → test đỏ; một màu literal dưới glob canvas →
      test đỏ.
- [ ] R1.1: số đo (kB gzip, p95 bố cục ở 500 Bước, khung hình và bộ nhớ ở 300 và 500 thẻ, lỗi CSP = 0) ghi vào
      ADR-0101 (Accepted).
- [ ] Xong: `pnpm -C apps/web test` xanh.

## Nguồn

- `apps/web/package.json:20`; spec: R1.1 (chưa có gói sơ đồ).
- `apps/web/lib/__tests__/antd-only.test.ts:14`; spec: R1.2 (đọc cả `@dw/ui`).
- `apps/web/lib/csp.ts:16-21`; spec: R1.1 (nonce, `strict-dynamic`).
- `CLAUDE.md:140-153`; spec: R1.2 (allowlist, chỉ `@xyflow/react` dưới glob canvas). ADR-0101 (Accepted).
- `packages/typescript/ui/src/theme.ts:3-6`, `apps/web/lib/__tests__/theme-contrast.test.ts:8-11`; spec: R1.9 (một chủ
  của màu, tương phản đo từ theme).
- `.claude/plans/studio/discovery/issues/24-workflow-canvas.md`; FOG-51.

## Comments

- 2026-10-23 (agent): DO-42 còn mở — Đạt sửa `CLAUDE.md` "Web UI" khi nhận ADR-0101 (Accepted); giữ needs-info đến
  lúc đó.
- 2026-10-23 (agent): DO-42 đã có lời đáp (Đạt 23/10/2026: `@xyflow/react` và `@dagrejs/dagre` cùng ngoại lệ, một glob canvas, allowlist `{module, glob, adr}`, giữ huy hiệu, không thư viện biểu đồ ở v1), nên ticket về `needs-triage`; việc đổi guard thành allowlist thuộc studio-skeleton/03, ticket này chỉ thêm mục `EXCEPTIONS`.
- 2026-10-25 (agent): lượt g, theo V4.25, V4.27 và V4.29 của Đạt ngày 24/10/2026: ticket là spike của discovery/24 cho Sơ đồ có cấu trúc (fixture F1-F9, bảng đo không còn mục dagre), `@dagrejs/dagre` rời ngoại lệ nên chỉ một mục `EXCEPTIONS`, huy hiệu ở góc dưới trái, một `zustand`, và bộ từ vựng nháp vào theme của `@dw/ui` để Đạt duyệt (R1.9, BU14). Không thêm cạnh.
- 2026-10-25 (agent): lượt h, theo V4.33 của Đạt: `flow.subworkflow` vào bậc B của W1 và thẻ Quy trình con vào ngữ pháp W1 (R1.5, ticket 04), nên bước 1 thôi gọi nó là loại W2; spike vẫn chỉ vẽ nó để xem. Không thêm cạnh.
