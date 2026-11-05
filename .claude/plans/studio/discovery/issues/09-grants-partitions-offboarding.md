# 09 — Quyền ghi tường minh, partition tạo sau và offboarding ở khối lượng Studio

Type: prototype
Status: resolved
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

## Answer

Đo ngày 5/11/2026 trên máy dev (không phải máy tham chiếu), PostgreSQL 16.15 của compose, database riêng
`dw_bench_offboarding_fog32` và mẫu `dw_bench_offboarding_seed_fog32` ở head `b0113f4` (alembic `902ac246a9dc`, đã xóa sau
khi đo); số, lệnh và cách chạy lại ở [`db/bench/offboarding/RESULTS.md`](../../../../../db/bench/offboarding/RESULTS.md),
harness `db/bench/offboarding/bench_offboarding.py` (`7782231`, `make bench-offboarding IMAGE=...`). Lane chạy trong tiến trình worker
thật (`python -m dw_worker.main`) của ảnh build tại chỗ từ head (`dw-worker:fog32-b0113f4`, không push, đã xóa), với
`--cpus 1.0 --memory 1g` của overlay prod và không swap; overlay không có giới hạn pids cho worker (`pids.peak` 14-35).
Seed dưới `dw_migrator` bằng `COPY`: bốn công ty (10^6, 250.000, 100.000 và 10.000 bản ghi `studio.records` đã phân vùng,
qua trigger chủ sở hữu, `access_key` sinh), mỗi công ty 200 thành viên có dòng `studio.principal_scopes`.

- **Câu 4: trượt ở head.** Công ty 10^6 bản ghi: worker bị giết vì bộ nhớ (`oom_kill` 1, `memory.peak` 1.074.491.392 B)
  34,5 giây sau khi nhận yêu cầu, không ra tệp, yêu cầu kẹt `exporting`. Đọc theo lô keyset (R11.2) không đủ: `_build_bundle`
  của lane worker giữ mọi dòng ndjson của bảng (1,88 KB một bản ghi), rồi bản nối và bản UTF-8, nên đỉnh là 9.143 byte mỗi
  bản ghi trên nền 204 MB (đo ở 100.000 và 250.000 bản ghi với 4 và 5 GiB: 1,12 và 2,49 GB, cả hai xuất đúng và md5 khớp).
  1 GiB chứa khoảng 95.000 bản ghi; 100.000 cũng bị giết. 10^6 cần khoảng 9,35 GB (ngoại suy). Nguyên mẫu ghi luồng ra
  tệp tạm (`worker_entry.py spool`, chỉ trong tiến trình đo): `memory.peak` 498.204.672 B (anon 349 MB, nền worker 174
  MB), xuất 153,7 giây, xóa 14,3 giây, tệp có **đúng 1.000.000 dòng bản ghi, 1.000.000 id khác nhau, md5 các id khớp seed, 0
  dòng của công ty khác**; ba công ty còn lại không bị chạm. Quyết định: xuất theo luồng (ghi tệp tạm, tải lên theo phần).
- **Câu 3, quyền SELECT theo cột: đạt trong `studio`, trượt ngoài nó.** `has_table_privilege('dw_app', oid, 'SELECT')` là
  false với bảng chỉ có `GRANT SELECT (cột)`, nên `_CATALOG_EXPORTABLE` và `_CATALOG_PURGEABLE` bỏ qua nó: `dw_app` đọc
  được dòng, `export_rows` thật xuất 0 dòng, lần xóa không chạm. `studio.fog32_probe` làm `offboarding_violations` đỏ
  (`R4.1 … is not exported`, `… is not purged`; test phủ ở head 14 passed). `memory.fog32_probe` và `platform.feedback`
  (có trước luật, cấp lại SELECT từng cột, đủ mọi cột) bị bỏ qua y như vậy mà test phủ vẫn `[]`: truy vấn của nó chỉ nhìn
  `studio` và `platform`, và bỏ qua `_PLATFORM_PREDATING`. Đó là failure-modes #0.
- **Cần ticket theo dõi** (RESULTS.md, Phát hiện): (1) gói xuất ghi luồng ra tệp và tải lên theo phần, có test bộ nhớ, và
  một yêu cầu bị OOM không được nhận lại vô hạn mỗi 30 phút (`_STALE_CLAIM_MINUTES`; suy từ mã); (2) lane coi bucket
  `feedback` hay collection Qdrant chưa từng tạo là rỗng: đo được yêu cầu `failed` ở `list_objects` (`NoSuchBucket`), và ở
  `delete_by_tenant` của chỉ mục tri thức **sau khi lần xóa SQL đã commit**; bộ xếp hạng bộ nhớ đã làm đúng; (3) test phủ
  offboarding đọc mọi schema có bảng tenant, và lane từ chối trước lần xuất khi một bảng tenant có quyền theo cột mà không
  có quyền bảng.

## Comments

- 2026-10-27 (agent): studio-skeleton/01 đo phần FOG-31 và phần của FOG-32, FOG-33 thuộc ticket đó; số đo ở Comments của `.claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md`. Còn mở: câu 2 (chép policy InitPlan sáu nhánh, foundations-hardening/03), câu 4 (xuất 10^6 bản ghi) và câu 5 (thứ tự topo), foundations-hardening/07.
- 2026-11-04 (agent, phân loại G12, theo ủy quyền 31/10/2026): `ready-for-agent`. Đã trả lời: câu 1 (FOG-31) ở studio-skeleton/01 (`b6d065d`, Comments 27/10/2026): bảng mới trong `studio` cho `dw_app` SELECT, còn INSERT, UPDATE, DELETE bị từ chối (`test_a_studio_table_is_readable_and_not_writable_by_default`). Câu 2: partition tháng tạo sau mang ENABLE, FORCE, policy tenant và không quyền nào của `dw_app` (studio-skeleton/01), và từ foundations-hardening/03 (`62d3b32`) `_ensure_one_partition` viết policy dạng sub-SELECT (InitPlan), có test trong `test_rls_coverage.py`; policy bản ghi sáu nhánh không đi qua hàm đó, vì partition băm của `studio.records` do migration tạo (custom-objects/02, `65bddef`) và record-access/03 chép mẫu vào revision (`1b864bb`). Câu 3, phần partition: `NOT c.relispartition` cho mỗi dòng một lần qua bảng cha (foundations-hardening/07, `8cee863`). Câu 5: thứ tự xóa suy từ cạnh RESTRICT và NO ACTION của `pg_constraint`, `_ORDERED_FIRST` đã gỡ (foundations-hardening/07, R11.4). Còn câu 4 (xuất theo lô keyset ≤ 1.000 dòng đã dựng, chưa đo ở 10^6) và phần quyền theo cột của câu 3.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): đo xong, `resolved`. Làm khác "Việc của agent" ở năm chỗ: (1) đo cả 100.000
  và 250.000 bản ghi với 4 và 5 GiB để có chi phí mỗi bản ghi, vì head đã OOM ở 1 GiB từ 100.000; (2) thêm một nguyên mẫu
  ghi luồng chạy trong cùng ảnh, thay `_build_bundle` trong tiến trình đo, để quyết định "xuất theo luồng" có số, không sửa
  mã repo; (3) bucket đính kèm trỏ vào `dw-artifacts` và không đặt Qdrant, vì kho dev chưa có bucket `feedback` và
  collection `dw_knowledge` và lane thất bại ở cả hai (Phát hiện 2, đo trước khi đổi); (4) ngoài bảng thử trong `studio`,
  thêm một bảng thử trong `memory` và cấp lại `platform.feedback` theo cột trong database đo, để hỏi test phủ không nhìn
  thấy gì; (5) chạy từ một bản `git archive HEAD` sạch vì migration chưa commit của làn 1 nằm trong cây làm việc.
  Nếu sai thì: ngưỡng 1 GiB tính trên tiến trình worker có mọi lane, không swap; overlay để swap cho máy chủ, nên máy có
  swap có thể sống lâu hơn một chút ở head, không đổi kết luận vì đỉnh cần khoảng 9,35 GB.
