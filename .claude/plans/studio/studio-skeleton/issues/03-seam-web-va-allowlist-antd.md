# 03 — Seam web Studio và guard antd-only thành allowlist

Status: needs-triage
Blocked by: 02
Area: studio
Yêu cầu: R7.1, R7.2, R7.3, R7.4, R7.5, R7.6, R7.7, G3, SKEL15

## Mục tiêu

Lát này cho người dùng đúng một mục "Studio" trên thanh điều hướng và một trang `/studio` có nội dung thật (R7.1 đến R7.4, YC1), và biến guard antd-only thành allowlist mà không nới: thư viện UI nào chưa có ADR vẫn đỏ, và một ngoại lệ chỉ hợp lệ trong glob của nó (R7.5 đến R7.7, ADR-0101 (Accepted) điểm 4). Ticket này chưa thêm ngoại lệ nào; ngoại lệ canvas vào cùng import canvas đầu tiên ở workflow-builder-ui.

## Việc cần làm

1. `apps/web/app/studio/_meta/sections.ts`: danh sách `STUDIO_SECTIONS` gồm `{ key, href, label, readKey }`; mục đầu là khu vực cấu hình, `readKey` là khóa đọc mà `GET /api/v1/studio/artifacts` đòi; spec chủ của mỗi khu vực sau thêm mục của nó.
2. `apps/web/app/studio/_meta/nav.ts`: `studioNav: NavItem[]` đúng một mục `{ href: "/studio", label: "Studio", hint: "Đối tượng, quy trình, agent và kết nối của công ty", icon: AppstoreOutlined, anyScope: STUDIO_SECTIONS.map((s) => s.readKey) }`; một dòng import và một spread trong `NAV_ITEMS` của `apps/web/lib/nav/registry.ts`, trước `...platformNav`.
3. `apps/web/app/studio/layout.tsx`: antd `Layout` với `Menu` riêng của Studio dựng từ `STUDIO_SECTIONS`; chữ đi qua khóa thông điệp tiếng Việt (DO-57).
4. `apps/web/app/studio/page.tsx`: `Table` của antd liệt kê artifact từ `GET /api/v1/studio/artifacts` qua `@dw/api-client`; ngày giờ qua `apps/web/lib/dates.ts` (Asia/Ho_Chi_Minh); trạng thái rỗng, lỗi và đang tải theo `ERROR_STATE` và `.claude/rules/ui-quality.md`.
5. `apps/web/lib/__tests__/antd-only.test.ts` thành allowlist: `ALLOWED` gồm `antd`, `@ant-design/icons`, `@ant-design/nextjs-registry`, `dayjs`, `keycloak-js`, `next`, `react`, `react-dom` và `@dw/*`, kể cả đường con như `dayjs/locale/vi`, `next/navigation`; `DEV_ONLY` gồm các devDependencies hiện có (`vitest`, `@testing-library/react`, `@playwright/test`, `jsdom`, `@vitejs/plugin-react`, `tailwindcss`, `@tailwindcss/postcss`, `eslint`, `eslint-config-next`, `typescript`, `@types/*`), chỉ được import từ tệp test, tệp cấu hình và tệp `.css`; `EXCEPTIONS` là danh sách `{ module, glob, adr }`, rỗng ở ticket này; mục của `@xyflow/react` và `@dagrejs/dagre` (Đạt cho phép ngày 23/10/2026, DO-42) vào ở workflow-builder-ui ticket 01, cùng glob `app/studio/**/canvas/**`. Kiểm manifest đọc `dependencies`, `peerDependencies`, `devDependencies` của `apps/web/package.json` và `packages/typescript/ui/package.json`. Kiểm import đọc mọi specifier trần trong mã nguồn của hai gói, bỏ qua `node:`, đường tương đối và alias `@/`. Giữ nguyên kiểm `REMOVED_PRIMITIVES` và kiểm tệp shadcn còn sót.
6. `apps/web/.eslintrc.json`: `no-restricted-imports` thành allowlist bằng `patterns` có phủ định, `message` nêu ADR-0101 (Accepted); `overrides` cho tệp test và tệp cấu hình nhận `DEV_ONLY`; giữ luật cấm `message`, `notification` tĩnh của antd. Đo trên ESLint đang ghim rằng mẫu phủ định chặn đúng một import lạ và để yên một import trong allowlist trước khi dựa vào nó (failure-modes #4).
7. Test: `apps/web/lib/nav/__tests__/studio-nav.test.ts` (đúng một mục `/studio` trong `NAV_ITEMS`; `isNavItemVisible` trả sai khi người xem không giữ khóa nào trong `STUDIO_SECTIONS`, đúng khi giữ một); test trang `/studio` với client giả; các ca allowlist trong `antd-only.test.ts`; `apps/web/e2e/studio.spec.ts` mở `/studio` ở 320 px.

## Tiêu chí chấp nhận

- [ ] R7.1: `NAV_ITEMS` có đúng một mục `href` `/studio`, nhãn "Studio"; thêm mục thứ hai trỏ `/studio` thì test đỏ.
- [ ] R7.2: người xem không giữ khóa nào trong `STUDIO_SECTIONS` không thấy mục; giữ một khóa thì thấy; `STUDIO_SECTIONS` rỗng thì mục ẩn.
- [ ] R7.3: trang `/studio` với client giả hiện tên artifact và giờ theo Asia/Ho_Chi_Minh; client trả `permission_denied` thì trang hiện vùng lỗi, không hiện bảng rỗng.
- [ ] R7.4: Playwright mở `/studio` ở 320 px và `scrollWidth` của tài liệu không quá 320.
- [ ] R7.5 (SKEL15): manifest thử khai `@chakra-ui/react` trong `dependencies` làm test đỏ, nêu tên; khai nó trong `devDependencies` cũng đỏ.
- [ ] R7.6 (SKEL15): `import { ReactFlow } from "@xyflow/react"` trong một tệp của `apps/web/app` làm test đỏ; với ngoại lệ thử `{ module: "@xyflow/react", glob: "app/studio/**/canvas/**" }`, cùng import trong `app/studio/w/canvas/a.tsx` qua còn trong `app/studio/w/a.tsx` đỏ; `vitest` import từ một tệp không phải test thì đỏ.
- [ ] R7.7: `pnpm --filter @dw/web lint` báo lỗi ở một tệp thử import `@chakra-ui/react` và không báo ở tệp import `antd`.
- [ ] G3: ca "catches each way the old system could come back" vẫn xanh; `sonner` và `Button from @dw/ui` vẫn bị bắt.
- [ ] Xong: `pnpm --filter @dw/web test && make test-web` xanh.

## Nguồn

- `apps/web/lib/nav/registry.ts:121-137`, `apps/web/lib/nav/types.ts:3-28`, `apps/web/lib/nav/visibility.ts:18-24`; spec: R7.1, R7.2.
- `apps/web/lib/__tests__/antd-only.test.ts:16-18`, `apps/web/lib/__tests__/antd-only.test.ts:95-151`; spec: R7.5, R7.6, G3.
- `apps/web/.eslintrc.json:4-37`; spec: R7.7.
- `apps/web/package.json:14-26`; spec: R7.5.
- ADR-0101 (Accepted) điểm 4.

## Comments
