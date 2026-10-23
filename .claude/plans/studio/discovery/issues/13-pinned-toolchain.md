# 13 — Công cụ trên bản đã ghim: import-linter, uv, alembic, FastAPI và openapi-typescript

Type: prototype
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-28 `import-linter`, FOG-29 `uv-docgen`, FOG-30 `alembic-compare`, FOG-54 `merge-merge-api`

## Câu hỏi

1. import-linter 2.15 (`uv.lock:1786`) có nhận wildcard `**` trong `ignore_imports` của hợp đồng independence và trong
   `source_modules` không (FOG-28)?
2. `uv sync --frozen --no-install-workspace --no-dev --package dw-docgen` (`infra/docker/docgen.Dockerfile:34`) có
   thành công khi manifest của một thành viên mới không được COPY vào Dockerfile (dòng 20-31) không (FOG-29)?
3. `compare_metadata` của alembic 1.20.0 (`uv.lock:60`) báo gì cho policy RLS, quyền theo cột, index từng phần và cột
   generated trong schema `studio` (FOG-30)?
4. FastAPI 0.141.1 (`uv.lock:1284`) xử lý `application/merge-patch+json` thế nào; `/records/query` có đứng được cạnh
   `/records/{record_id}` không; openapi-typescript sinh gì cho một bản ghi có `fields` chung (FOG-54)?

## Vì sao

Câu 1 quyết hợp đồng Studio là mẫu hay danh sách mà mỗi capability mới phải sửa. Câu 2 quyết `check_registration` có
đòi dòng COPY của docgen không. Câu 3: ticket kiểm lệch migration không được luôn đạt hay luôn trượt (failure-modes #3).
Câu 4: client sinh ra phải biên dịch được cho đối tượng động.

## Mở khóa

- Spec: `studio-skeleton` (01, 02: hợp đồng import, kiểm đăng ký, kiểm lệch migration), `app-standards` (01, 03),
  `custom-objects` (04, 05: API bản ghi).
- ADR: 0100, 0108.
- DO: DO-02 (một phân phối `dw_studio`, hợp đồng theo capability), DO-16 (quy ước API).
- Ticket W1: `studio-skeleton/01`, `studio-skeleton/02`, `app-standards/01` (P0).

## Dựng tối thiểu

Một nhánh nháp: phân phối `dw_studio` rỗng với hai capability giả và hợp đồng dùng `**`; một thành viên workspace uv mới không
có trong `docgen.Dockerfile`; một migration nháp có policy, GRANT theo cột, index từng phần và cột generated, rồi gọi
`compare_metadata`; một app FastAPI với hai route, chạy openapi-typescript rồi `tsc --noEmit`.

## Phép đo quyết định

| Đo                                         | Kết quả cần biết                      | Quyết định                                          |
| ------------------------------------------ | ------------------------------------- | --------------------------------------------------- |
| `lint-imports` với `**`                    | Nhận và áp đúng, hay báo lỗi cấu hình | Hợp đồng theo mẫu hay liệt kê                       |
| `uv sync` khi thiếu manifest               | Thành công hay lỗi                    | `check_registration` có đòi COPY không              |
| `compare_metadata` trên bốn loại đối tượng | Báo đúng, bỏ qua hay báo sai          | Thiết kế kiểm lệch; test phải đỏ khi xóa một policy |
| Route và client sinh ra                    | Thứ tự route đúng; `tsc` qua          | Hình API bản ghi (DO-16)                            |

## Nguồn

- Brief B1, B5.
- [research.md](../research.md) mục 15 (`application/merge-patch+json` trên FastAPI 0.141.1 chưa kiểm).

## Comments
