# 29 — Màn quản trị W2: ma trận vai trò, biểu mẫu theo lược đồ, diff phiên bản và tín hiệu lệch cấu hình

Type: prototype
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-39 `rbac-matrix-ui`, FOG-52 `diff-readability`, FOG-53 `schema-form`

## Câu hỏi

1. Một ma trận antd 200 đối tượng nhân 7 hành động, mỗi ô là một ô chọn mức truy cập, có nhanh, tiếp cận được và dùng
   được ở 320 px không (FOG-39)?
2. Diff phiên bản có cấu trúc (diff dòng của chỉ dẫn, đường dẫn JSON, bản ghim, chênh lệch của cổng) có đọc được với
   người dựng nghiệp vụ và người duyệt không; quản trị viên Marketing hành động theo cảnh báo lệch cấu hình nào (FOG-52)?
3. Biểu mẫu theo lược đồ của dw-proterial (8 dạng trong `rule-schema.ts`) hợp tới đâu với lược đồ của bộ giá trị gắn và
   của chính sách; port khoảng 2.300 dòng TypeScript tốn bao nhiêu; `@dw/ui` có giữ nó không (FOG-53)?

## Vì sao

Màn sửa vai trò là màn chính của quản trị viên công ty (YC16, W2). Người duyệt không đọc được diff thì duyệt mù; tín hiệu
lệch không ai đọc là failure-modes #1. Tránh dựng bộ sinh biểu mẫu thứ hai. W1 cấu hình vai trò, đối tượng và giá trị gắn
qua API công khai, nên ticket này đi sau đích.

## Mở khóa

- Spec: `tenant-rbac` (màn vai trò, W2), `agent-lifecycle` (giao diện duyệt phát hành), `tenant-config` (biểu mẫu, diff
  trong hộp duyệt, lệch cấu hình; W2).
- ADR: 0104, 0110, 0120.
- DO: DO-07 (D11: người duyệt khác người đề xuất, nên phải đọc được thứ mình duyệt).
- Không ticket W1 nào trùng: các màn này ở W2.

## Dựng tối thiểu

Một trang nháp trong `apps/web`: ma trận antd 200 x 7 với dữ liệu giả; hai phiên bản agent giả và màn diff giữa chúng;
bản port thử một dạng của biểu mẫu dw-proterial trên một lược đồ bộ giá trị gắn; thử với người dựng và người duyệt
nghiệp vụ thật.

## Phép đo quyết định

| Đo                                             | Ngưỡng                          | Quyết định                               |
| ---------------------------------------------- | ------------------------------- | ---------------------------------------- |
| Ma trận: thời gian render, bàn phím, 320 px    | YC16; dùng được ở 320 px        | Thiết kế màn vai trò                     |
| Người duyệt nói đúng thay đổi sau khi đọc diff | Chưa có ngưỡng; ghi tỉ lệ       | Hình của diff                            |
| Cảnh báo lệch được hành động theo              | Ghi loại nào được dùng          | Tín hiệu lệch nào giữ (failure-modes #1) |
| Port biểu mẫu                                  | Dạng nào hợp, số dòng phải port | Port vào `@dw/ui` hay không              |

## Nguồn

- Brief B3 (F7), B6 (F6, F7), B10a.

## Comments
