# 01 — Thử nghiệm xyflow và dagre rồi ngoại lệ antd-only có phụ thuộc chính xác

Status: needs-triage
Blocked by: .claude/plans/studio/studio-skeleton/issues/03-seam-web-va-allowlist-antd.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, BU1

## Mục tiêu

Đưa `@xyflow/react` và `@dagrejs/dagre` vào `apps/web` chỉ ở đường dẫn canvas của builder, như ngoại lệ
duy nhất của luật chỉ antd, với hai mục `EXCEPTIONS` có ADR trong allowlist của `antd-only.test.ts`
(workflow-builder-ui R1.1, R1.2, R1.3, BU1). Trước đó là một nhánh thử đo rằng hai gói chạy được dưới ngăn
xếp của repo (DO-42).

## Việc cần làm

1. Nhánh thử (số đo vào ADR-0101 (Accepted), không giữ mã thử; đây là phép đo FOG-51 của discovery/24,
   ticket khám phá đóng bằng một dòng trỏ tới số đo ở đây; bundle của route canvas đo riêng, ngoài ngân sách
   khoảng 250 kB của antd): CSP nonce ở `apps/web/lib/csp.ts:16-21`
   không vỡ (xyflow không chèn script nội tuyến không nonce); thứ tự `@layer theme, base, antd,
components, utilities`; bundle route builder (kB gzip); shim jsdom `ResizeObserver` có `contentRect`;
   dagre bố cục 100 Bước có thân map; Next 15.5, React 19. Lỗi CSP đếm phải bằng 0.
2. Ghim chính xác `@xyflow/react` 12.12.0 và `@dagrejs/dagre` 3.1.1 trong `apps/web/package.json`.
3. Import hai gói chỉ dưới `apps/web/app/studio/**/canvas/**`, kể cả hàm bố cục dagre; nạp bằng
   `next/dynamic` với `ssr: false`. antd vẽ mọi thân Bước, panel và thông báo; `--xy-*` ánh xạ sang
   `--ant-*`; giữ huy hiệu React Flow, không ẩn khi chưa mua Pro (DO-42.2).
4. Thêm hai mục `EXCEPTIONS` `{module, glob, adr}` (`@xyflow/react` và `@dagrejs/dagre`, glob
   `apps/web/app/studio/**/canvas/**`, ADR-0101 (Accepted)) vào allowlist mà studio-skeleton/03 dựng trong
   `apps/web/lib/__tests__/antd-only.test.ts`, cùng commit với import canvas đầu tiên; khẳng định chỉ
   `apps/web` khai báo hai gói và chỉ tệp dưới glob import. Thêm override ESLint tương ứng. `CLAUDE.md` "Web
   UI" đã sửa cùng lúc Đạt nhận ADR-0101 (Accepted); ticket này không sửa nó.

## Tiêu chí chấp nhận

- [ ] R1.1: `@xyflow/react` 12.12.0 và `@dagrejs/dagre` 3.1.1 ghim chính xác, chỉ import dưới
      `apps/web/app/studio/**/canvas/**`.
- [ ] R1.2 (BU1): import một trong hai gói từ `apps/web/app/approvals` → `antd-only.test.ts` đỏ; khai
      báo gói trong `@dw/ui` → `antd-only.test.ts` đỏ; gỡ mục allowlist có ADR → đường dẫn builder đỏ.
- [ ] R1.3: một node body render bằng antd; không có màu, kiểu chữ hay bo góc nào đặt ngoài theme antd
      (Tailwind chỉ bố cục).
- [ ] R1.1: số đo (kB gzip, ms bố cục, lỗi CSP = 0) ghi vào ADR-0101 (Accepted).
- [ ] Xong: `pnpm -C apps/web exec vitest run lib/__tests__/antd-only.test.ts` xanh.

## Nguồn

- `apps/web/package.json:20`; spec: R1.1 (chưa có gói đồ thị).
- `apps/web/lib/__tests__/antd-only.test.ts:14`; spec: R1.2 (đọc cả `@dw/ui`).
- `apps/web/lib/csp.ts:16-21`; spec: R1.1 (nonce, `strict-dynamic`).
- `CLAUDE.md:140`; spec: R1.2 (luật chỉ antd). ADR-0101 (Accepted).

## Comments

- 2026-10-23 (agent): DO-42 còn mở — Đạt sửa `CLAUDE.md` "Web UI" khi nhận ADR-0101 (Accepted); giữ needs-info đến
  lúc đó.
- 2026-10-23 (agent): DO-42 đã có lời đáp (Đạt 23/10/2026: `@xyflow/react` và `@dagrejs/dagre` cùng ngoại lệ, một glob canvas, allowlist `{module, glob, adr}`, giữ huy hiệu, không thư viện biểu đồ ở v1), nên ticket về `needs-triage`; việc đổi guard thành allowlist thuộc studio-skeleton/03, ticket này chỉ thêm mục `EXCEPTIONS`.
