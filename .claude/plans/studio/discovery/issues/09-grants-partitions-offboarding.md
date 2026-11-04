# 09 — Quyền ghi tường minh, partition tạo sau và offboarding ở khối lượng Studio

Type: prototype
Status: ready-for-agent
Area: studio · Viết: 23/10/2026
FOG: FOG-31 `grants-assumption`, FOG-32 `partition-policy`, FOG-33 `purge-order`

## Câu hỏi

1. Bảng `studio` nào đã lên kế hoạch (bản ghi, vỏ phiên bản, lần kích hoạt) ngầm cần quyền ghi mặc định, khi default
   privileges của schema `studio` chỉ cho SELECT (FOG-31)?
2. `platform._ensure_one_partition` (`db/migrations/sql/0013_partition_maintenance.sql:21`), khi tên có schema, có
   chép được policy dạng InitPlan với sáu nhánh của quyền trên bản ghi, thay vì chỉ policy tenant, không (FOG-32)?
3. Partition băm của `studio.records` và quyền SELECT theo cột đi qua truy vấn catalog và bộ lọc
   `has_table_privilege` của offboarding thế nào (FOG-32)?
4. Offboarding có xuất được một công ty có một triệu bản ghi không, khi `export_rows` nạp cả bảng trong một giao dịch
   (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:162-181`) (FOG-32)?
5. Thứ tự xóa có suy được từ `pg_constraint` (thứ tự topo của cạnh RESTRICT) thay cho danh sách tay `_ORDERED_FIRST`
   (`offboarding.py:108`) không (FOG-33)?

## Vì sao

Bảng thiếu quyền tường minh lỗi ở truy vấn thật đầu tiên trong khi health check vẫn xanh. Partition tạo sau phải mang
đủ RLS và quyền. Studio thêm ít nhất năm cạnh RESTRICT, danh sách tay sẽ lệch (failure-modes #2). Offboarding phải còn
chạy ở khối lượng Studio.

## Mở khóa

- Spec: `studio-skeleton` (01, ticket đầu của đường găng), `custom-objects`, `tenant-config`, `workflow-triggers`,
  `foundations-hardening` (offboarding).
- ADR: 0100, 0105, 0107.
- DO: DO-02 (default privileges chỉ SELECT), DO-13 (lane bảo trì đọc bản ghi). Ticket W1: `studio-skeleton/01` (P0).

## Dựng tối thiểu

Một migration nháp: schema `studio` với default privileges chỉ SELECT cho `dw_app`, `studio.records` partition băm có
quyền theo cột, một partition tháng tạo sau qua `_ensure_one_partition`; gieo 10^6 bản ghi cho một công ty rồi chạy xuất
và xóa của offboarding; một hàm sắp topo trên `pg_constraint`, so với `_ORDERED_FIRST` trên schema hiện tại.

## Phép đo quyết định

| Đo                                                                  | Ngưỡng hay so sánh                                                        | Quyết định                                  |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------- | ------------------------------------------- |
| `test_rls_coverage.py`, `test_privileges.py` trên partition tạo sau | Xanh với đủ bộ policy; đỏ khi chỉ có policy tenant                        | Sửa `_ensure_one_partition` hay không       |
| Bộ nhớ và thời gian xuất 10^6 bản ghi                               | Vừa giới hạn 1 GB của worker (`infra/compose/docker-compose.prod.yml:41`) | Xuất theo luồng hay giữ nguyên              |
| Thứ tự topo so với `_ORDERED_FIRST`                                 | Bằng hoặc bao trùm danh sách tay                                          | Bỏ danh sách tay hay không                  |
| Bảng kế hoạch thiếu GRANT                                           | Danh sách tên bảng                                                        | GRANT đi cùng migration của ticket tạo bảng |

## Nguồn

- Brief B1, B5, B6 (F10); `docs/adr/0105-record-reach-is-decided-by-postgresql.md:130` (partition bản ghi cần đủ bộ
  policy).

## Việc của agent (phân loại 4/11/2026)

- Câu hỏi: câu 4, và phần quyền SELECT theo cột của câu 3: lane offboarding có xuất một công ty 10^6 bản ghi dưới
  giới hạn worker 1 CPU / 1 GB không, và một bảng mà `dw_app` chỉ có quyền SELECT theo cột có bị bộ lọc
  `has_table_privilege` bỏ qua không?
- Cách làm: database riêng trên compose (`DW_TEST_DB_SUFFIX=_fog32`), `alembic upgrade head`; gieo 10^6 dòng
  `studio.records` (bảng tạm của custom-objects/02, `65bddef`) cho một tenant bằng `COPY` dưới migrator; chạy lane
  `offboarding` (`apps/worker/src/dw_worker/consumers/offboarding.py`) trong container worker với giới hạn của
  `infra/compose/docker-compose.prod.yml` (1 CPU, 1 GB); đọc `memory.peak` của cgroup và thời gian. Thêm một bảng
  thử trong `studio` chỉ có `GRANT SELECT (cột)` cho `dw_app`, chạy truy vấn catalog của offboarding và
  `test_offboarding_coverage.py`.
- Đầu ra: `## Answer` ở đây và một dòng trong Comments của foundations-hardening/07.
- Đạt khi: xuất xong không bị OOM, `memory.peak` dưới 1 GiB, tệp xuất có đúng 10^6 dòng (mỗi dòng một lần); bảng
  chỉ có quyền theo cột hoặc được xuất, hoặc làm test phủ offboarding đỏ. Trượt khi bảng đó bị bỏ qua mà không test
  nào đỏ (failure-modes #0), hay khi worker bị giết vì bộ nhớ.

## Comments

- 2026-10-27 (agent): studio-skeleton/01 đo phần FOG-31 và phần của FOG-32, FOG-33 thuộc ticket đó; số đo ở Comments của `.claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md`. Còn mở: câu 2 (chép policy InitPlan sáu nhánh, foundations-hardening/03), câu 4 (xuất 10^6 bản ghi) và câu 5 (thứ tự topo), foundations-hardening/07.
- 2026-11-04 (agent, phân loại G12, theo ủy quyền 31/10/2026): `ready-for-agent`. Đã trả lời: câu 1 (FOG-31) ở studio-skeleton/01 (`b6d065d`, Comments 27/10/2026): bảng mới trong `studio` cho `dw_app` SELECT, còn INSERT, UPDATE, DELETE bị từ chối (`test_a_studio_table_is_readable_and_not_writable_by_default`). Câu 2: partition tháng tạo sau mang ENABLE, FORCE, policy tenant và không quyền nào của `dw_app` (studio-skeleton/01), và từ foundations-hardening/03 (`62d3b32`) `_ensure_one_partition` viết policy dạng sub-SELECT (InitPlan), có test trong `test_rls_coverage.py`; policy bản ghi sáu nhánh không đi qua hàm đó, vì partition băm của `studio.records` do migration tạo (custom-objects/02, `65bddef`) và record-access/03 chép mẫu vào revision (`1b864bb`). Câu 3, phần partition: `NOT c.relispartition` cho mỗi dòng một lần qua bảng cha (foundations-hardening/07, `8cee863`). Câu 5: thứ tự xóa suy từ cạnh RESTRICT và NO ACTION của `pg_constraint`, `_ORDERED_FIRST` đã gỡ (foundations-hardening/07, R11.4). Còn câu 4 (xuất theo lô keyset ≤ 1.000 dòng đã dựng, chưa đo ở 10^6) và phần quyền theo cột của câu 3.
