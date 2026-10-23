# 07 — Nền lưu trữ bản ghi: partition băm, ngân sách slot, collation tiếng Việt và tìm không dấu

Type: prototype
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-41 `records-storage-perf`, FOG-55 `unaccent`

## Câu hỏi

1. Thời gian lập kế hoạch và bộ nhớ relcache của `studio.records` với 8 partition băm nhân khoảng 80 index slot từng
   phần dưới RLS: custom plan và generic plan, có và không có vị từ `tenant_id` (FOG-41)?
2. Tỉ lệ HOT, WAL và khuếch đại ghi index cho một hỗn hợp cập nhật giống Lead (FOG-41)?
3. ORDER BY với collation `vi-VN-x-icu` còn dùng index sắp dưới RLS không (FOG-41)?
4. Hạn mức lưu trữ đếm bản ghi bằng dòng bộ đếm hay bằng ước lượng (FOG-41)?
5. `CREATE EXTENSION unaccent` có chạy dưới `dw_migrator` trong CI và compose không; cột STORED generated có nhận hàm
   bọc IMMUTABLE với `COLLATE "C"` không; PostgreSQL managed có `unaccent` không (FOG-55)?
6. Tìm theo tiền tố từ có đủ cho người dùng Marketing không; quy trình xử lý lệch collation ICU khi cập nhật
   `postgres:16-alpine` là gì (FOG-55)?

## Vì sao

Quyết partition, ngân sách slot và cách đếm hạn mức lưu trữ. Tìm tiếng Việt không dấu là điều thí điểm cần; lệch
collation làm hỏng index trong im lặng.

## Mở khóa

- Spec: `custom-objects` (01, 02; tìm không dấu ở W2), `record-access`.
- ADR: 0107 (Open 2: dạng không partition chỉ còn cho trường hợp phép đo trượt).
- DO: DO-15 (partition băm modulus 8 từ đầu, ở PostgreSQL 16), DO-14 (D12).
- Ticket W1: `custom-objects/01` (P0) là phép đo này.

## Dựng tối thiểu

Bảng `studio.records` partition băm theo `tenant_id` (modulus 8) với khoảng 80 index slot từng phần và policy RLS của
ticket 05, gieo tới 10^7 bản ghi; một script cập nhật kiểu Lead; image `postgres:16-alpine` của repo
(`infra/compose/docker-compose.yml:45`) chạy migration bằng `dw_migrator`; câu 6 hỏi thêm khách thí điểm (ticket 02).

## Phép đo quyết định

| Đo                                           | Ngưỡng hay so sánh                             | Quyết định                                        |
| -------------------------------------------- | ---------------------------------------------- | ------------------------------------------------- |
| Planning p95 và relcache theo kiểu plan      | Chưa có ngưỡng; so có và không partition       | Partition từ revision đầu (D12) hay dạng dự phòng |
| Danh sách sắp theo `vi-VN-x-icu` dưới RLS    | YC20; thứ tự "An, Ánh, Ân, Bình, Đạt" của YC27 | Index sắp và collation                            |
| HOT, WAL, khuếch đại ghi                     | So theo số slot                                | Ngân sách slot                                    |
| `unaccent` dưới `dw_migrator`; cột generated | Chạy được hay không, ở CI, compose và managed  | Tìm không dấu ở W2 dựng trên gì                   |
| Đếm bản ghi                                  | Sai số và chi phí mỗi lần ghi                  | Cách đếm hạn mức lưu trữ                          |

## Nguồn

- Brief B4, B5; `docs/adr/0107-custom-objects-over-fixed-tables-one-record-service.md` (Open 2).
- [research.md](../research.md) mục 1 (thời gian lập kế hoạch với 8 partition chưa kiểm), mục 15 (`unaccent` dưới
  `dw_migrator` chưa kiểm).

## Comments
