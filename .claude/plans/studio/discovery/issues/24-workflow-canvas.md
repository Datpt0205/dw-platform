# 24 — Sơ đồ quy trình: `@xyflow/react` và dagre dưới CSP nonce, lớp antd, Next 15.5 và React 19

Type: prototype
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-51 `canvas`

## Câu hỏi

1. `@xyflow/react` 12.12.0 và dagre 3.1.1 có chạy dưới CSP nonce theo từng request, thứ tự lớp CSS của antd, Next 15.5 và
   React 19 (`apps/web/package.json:23-24`) không, và tốn bao nhiêu bundle?
2. Bố cục dagre có đọc được ở 60-100 bước, có thân của bước map và nhánh ra lỗi, khi không lưu vị trí không?
3. Dạng danh sách (outline view) có dùng được với NVDA đọc tiếng Việt không?

## Vì sao

Ngoại lệ của sơ đồ với quy tắc chỉ dùng antd (CLAUDE.md "Web UI") phải được đo trước khi cấp. ADR 0101 biến guard
antd-only thành allowlist, mỗi ngoại lệ có ADR riêng.

## Mở khóa

- Spec: `workflow-builder-ui` (01, 02), `studio-skeleton` (03, seam web và allowlist).
- ADR: 0101.
- DO: DO-42 (sửa CLAUDE.md "Web UI" cho sơ đồ, `antd-only.test.ts` thành kiểm allowlist, giữ huy hiệu ghi công của
  React Flow).
- Ticket W1: `workflow-builder-ui/01` (P0) là phép đo này.

## Dựng tối thiểu

Một trang nháp trong `apps/web`, sau CSP nonce hiện có: `@xyflow/react` và `@dagrejs/dagre` ghim chính xác; một quy trình
100 bước sinh ngẫu nhiên có map và nhánh lỗi, bố cục chỉ bằng dagre; dạng danh sách song song dựng bằng antd.

## Phép đo quyết định

| Đo                                 | Ngưỡng                                              | Quyết định                                                |
| ---------------------------------- | --------------------------------------------------- | --------------------------------------------------------- |
| Vi phạm CSP; CSS bị lớp antd đè    | 0                                                   | Cấp ngoại lệ hay không (ADR 0101, DO-42)                  |
| Bundle tải đầu của trang builder   | Ghi kB; so với +250 kB CLAUDE.md chấp nhận cho antd | Ghi vào ADR 0101                                          |
| Dùng ở 320 px và chỉ bằng bàn phím | YC39                                                | YC39 đạt hay không                                        |
| NVDA đọc dạng danh sách tiếng Việt | Đọc đúng thứ tự bước và nhánh                       | Dạng danh sách đủ cho người dùng trình đọc màn hình không |
| 60-100 bước không lưu vị trí       | Người dựng đọc được, thử với người dùng thật        | Giữ "không lưu vị trí" của ADR 0101 hay không             |

## Nguồn

- Brief B7b; `apps/web/lib/__tests__/antd-only.test.ts` (guard hiện tại).
- [research.md](../research.md) mục 3 (`@xyflow/react` dưới CSP nonce và React 19 chưa kiểm).

## Comments
