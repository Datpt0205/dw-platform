# 13 — Công cụ trên bản đã ghim: import-linter, uv, alembic, FastAPI và openapi-typescript

Type: prototype
Status: ready-for-agent
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

## Việc của agent (phân loại 4/11/2026)

- Câu hỏi: phần còn lại của câu 4: trên FastAPI 0.141.1, `POST .../records/query` đứng cạnh `GET`, `PATCH`,
  `DELETE .../records/{record_id}` mà mỗi request tới đúng handler không, ở cả hai thứ tự khai route?
- Cách làm: test đơn vị với app FastAPI tối thiểu theo đường dẫn của custom-objects/04, hoặc chính test route của
  custom-objects/04 khi ticket đó dựng; sinh lại OpenAPI và chạy typecheck của client như `make test-contract`.
- Đầu ra: `## Answer` ở đây; test được giữ nếu nằm trong custom-objects/04.
- Đạt khi: ở cả hai thứ tự, `POST .../records/query` tới handler truy vấn, `GET .../records/<uuid>` tới handler đọc,
  `GET .../records/query` không bao giờ thành đọc bản ghi có id `query` (405 hoặc 422), và client sinh ra biên
  dịch. Trượt thì đổi thứ tự khai hay đường dẫn trước khi custom-objects/04 dựng.

## Comments

- 2026-11-04 (agent, phân loại G12, theo ủy quyền 31/10/2026): `ready-for-agent`. Đã trả lời: câu 1, studio-skeleton/02 (`09c344d`, Comments): import-linter 2.15 nhận `*` và `**` trong `source_modules`, `forbidden_modules`, `ignore_imports`, mẫu không khớp module nào không lỗi. Câu 2 không còn quyết gì: `check_registration` đòi dòng COPY manifest ở cả ba Dockerfile, kể cả docgen (studio-skeleton/01, `b6d065d`; `scripts/verify_architecture.py:45`), nên hành vi của `uv sync` khi thiếu manifest không còn đổi thiết kế. Câu 3, studio-skeleton/02 R6.7 (`test_metadata_matches_catalog.py`, docstring): `compare_metadata` không thấy vị từ index một phần, CHECK, policy, quyền theo cột, trigger; thấy thứ tự và chiều index, `ON DELETE`. Câu 4 một phần: `application/merge-patch+json` đã chạy (app-standards/03, `a70fb37`; `apps/api/src/dw_api/dependencies/conditions.py`, `test_conditional_writes_and_queries.py`); openapi-typescript sinh `{[key: string]: unknown}` cho đối tượng mở và biên dịch được (`document` của phong bì trong `packages/typescript/api-client/src/generated/platform.d.ts`).
