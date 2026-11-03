# 07 — Áp kết luận đo D12 vào DDL của studio.records

Status: ready-for-human (Chờ Đạt 23: máy tham chiếu của YC20)
Blocked by: 01, 02, 03
Area: studio
Yêu cầu: R9.2, R9.4, R9.5

## Mục tiêu

Ticket 02 dựng `studio.records` trên DDL tạm (modulus 4, tập slot đề xuất A0 của ticket 01, btree `updated_at`, chỉ
mục họ `b` giữ), vì lần đo `--scale d12` của ticket 01 chờ máy tham chiếu mà YC20 định nghĩa. Ticket này đọc kết luận
của luật quyết của ticket 01 ở quy mô D12 và đưa DDL về đúng kết luận đó (R9.2, R9.4, R9.5; ADR-0107 (Accepted) quyết 2,
sửa đổi 2026-11-03), để tập slot và modulus mà RecordService dựa vào là tập đã đo, không phải tập đề xuất.

## Việc cần làm

1. Đọc bảng số và kết luận của bước 7 ticket 01 ở lần chạy `--scale d12` (Comments của ticket 01). Kết luận là A1,
   modulus 4 và tập slot A0: ghi vào Comments ở đây, không revision, ticket xong. A1 trượt ngưỡng đọc ở cả hai modulus:
   quay lại người đặt yêu cầu (DO-15), ticket giữ `ready-for-human`.
2. Kết luận khác: một revision Alembic (id ngẫu nhiên do `alembic revision -m "..."` sinh), một thay đổi mỗi phần:
    - modulus 8: tạo bảng mới `PARTITION BY HASH (tenant_id)` modulus 8 (`studio.records_p0` tới `studio.records_p7`),
      chép mọi dòng qua bảng cha bằng `dw_migrator` trong một giao dịch, đổi tên, dựng lại mọi chỉ mục, UNIQUE, FK ghép
      ở cả hai chiều (kể cả FK từ bảng khác tới `studio.records`, như `studio.record_write_keys` của ticket 03 nếu đã
      có, ticket 03), policy RESTRICTIVE `tenant_isolation_records` trên bảng cha và mỗi partition, policy PERMISSIVE của
      record-access/03 nếu đã có, trigger `platform.touch_updated_at()`, quyền của mục Dữ liệu và `REVOKE ALL` của
      `dw_app` trên từng partition;
    - A2: chỉ mục `updated_at` thành BRIN;
    - A3 hay ít slot hơn mỗi họ: bỏ chỉ mục, hay cột và chỉ mục, của slot thừa; revision từ chối, trước câu đổi đầu,
      khi một slot bị bỏ đang được một dòng `studio.field_defs` giữ; bảng họ sang tập slot của
      `dw_studio/records/domain/field_types.py` đổi trong cùng commit, và ngân sách slot của R1.6 theo nó.
3. Ticket này chờ ticket 03, vì cả hai chạm `studio.records` và `studio.record_write_keys`: revision dựng lại FK của
   `studio.record_write_keys` và policy của record-access/03 mà ticket 03 đã có. RecordService chỉ ghi được bản ghi
   sau record-access/03, mà record-access/03 chờ lần đo D12 của record-access/06 trên cùng máy, nên bảng thường còn ít
   dòng; revision chép mọi dòng như bước 2.

## Tiêu chí chấp nhận

- [ ] R9.2: khi kết luận là modulus 8, test catalog thấy `studio.records` là `PARTITION BY HASH (tenant_id)` với 8
      partition, mỗi partition ENABLE và FORCE RLS với policy của bảng cha, không quyền nào của `dw_app`; dòng có trước
      revision còn đủ (cùng số dòng và cùng id theo tenant) sau revision.
- [ ] R9.5: khi kết luận là modulus 4, test catalog của ticket 02 xanh không đổi và Comments ở đây dẫn dòng kết luận
      của ticket 01.
- [ ] R9.4: test catalog đọc `pg_index` thấy đúng tập slot của kết luận, mỗi slot một chỉ mục từng phần đúng vị từ
      (trừ họ mà A3 bỏ chỉ mục), và tập cột slot trong `pg_attribute` bằng bảng họ sang tập slot của `field_types.py`;
      revision bỏ một slot đang được trường giữ → từ chối, 0 dòng đổi.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `.claude/plans/studio/custom-objects/issues/01-do-nen-luu-tru-ban-ghi.md:101-107`; spec: R9.2, R9.5.
- `.claude/plans/studio/record-access/issues/06-do-rls-ban-ghi-o-quy-mo-d12.md:3`; spec: R9.1.
- ADR-0107 (Accepted) quyết định 1, 2.

## Comments

- 2026-11-03 (agent, theo ủy quyền 31/10/2026): tách từ ticket 02 ở gate của nó (HIGH 1): ticket 02 dựng trên DDL tạm,
  ticket này áp kết luận D12. `ready-for-human` vì cần máy tham chiếu (Chờ Đạt 23); một agent dựng được revision khi số
  đo đã có trong Comments của ticket 01.
