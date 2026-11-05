# 08 — Offboarding ghi gói ra tệp, làm tiếp sau lần xóa, kho chưa tạo là rỗng, bảng chỉ có quyền theo cột chặn lượt

Status: resolved (2026-11-05, main)
Blocked by: 03, 07
Area: studio
Yêu cầu: R11.9, R11.10, R11.11, R11.12, R11.13, R11.14, R11.17, R11.18, R11.19, FH37, FH38, FH39, FH40, FH41, FH44

## Mục tiêu

Người vận hành offboard được một công ty lớn hơn bộ nhớ của worker: lane `offboarding` ghi gói xuất ra tệp tạm theo
từng lô và tải lên theo phần (R11.9), nên một công ty 10^6 bản ghi không còn làm worker 1 GiB bị OOM như discovery/09
đo; một yêu cầu đã tải gói được làm tiếp tới `completed` thay vì kẹt `failed` hay bị xuất lại (R11.10, R11.11); một
bucket hay collection chưa ai tạo là kho rỗng, không làm hỏng lượt (R11.12); và một bảng tenant mà `dw_app` chỉ đọc
được theo cột chặn cả lượt và làm test phủ đỏ ở mọi schema, thay vì bị bỏ qua (R11.13, R11.14). Lần nhận có đếm là
ticket 09, bảng có trước luật của test phủ là ticket 10.

## Việc cần làm

1. **Viết trước test phủ của FH41** trong `packages/python/dw_platform/tests/integration/test_offboarding_coverage.py`:
   `test_a_table_read_by_column_only_is_named_in_every_schema`, ba ca theo dạng thăm dò của discovery/09
   (`db/bench/offboarding/bench_offboarding.py` `probe`): bảng mới `studio.ob_cols` và `memory.ob_cols` có `tenant_id`,
   RLS ENABLE và FORCE, policy `tenant_isolation_*`, `REVOKE ALL` rồi `GRANT SELECT (id, body), DELETE` cho `dw_app`; và
   `platform.feedback` với `REVOKE SELECT` rồi `GRANT SELECT` mọi cột cho `dw_app`, cả ba trong giao dịch rollback của
   `_violations_after`. Mỗi ca khẳng định dòng `R11.14 <bảng> is read by column only`. Chạy trên mã hiện có: phải đỏ ở
   cả ba ca; ghi kết quả vào Comments.
2. **Test phủ đọc mọi schema** (R11.14): `_TENANT_TABLES` của test phủ lấy mọi bảng (`relkind` `r`, `p`, không phải
   partition) có cột `tenant_id` ở mọi schema trừ `information_schema` và schema bắt đầu bằng `pg_`. Một kiểm mới, không
   bỏ qua `_PLATFORM_PREDATING`: mỗi bảng như thế mà `has_any_column_privilege('dw_app', oid, 'SELECT')` đúng còn
   `has_table_privilege('dw_app', oid, 'SELECT')` sai thì thêm dòng `R11.14 <bảng> is read by column only`. Dòng R4.1
   giữ cho `studio`, R4.3 cho `platform`, schema khác dùng mã R11.14. Kiểm này là truy vấn riêng của test, không nhập
   truy vấn của adapter, để test và lane không mù cùng một chỗ.
3. **Lane từ chối bảng chỉ có quyền theo cột** (R11.13): trong
   `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py`, một truy vấn catalog
   `_CATALOG_COLUMN_ONLY` (bảng `r`, `p` không phải partition, mọi schema trừ `information_schema` và `^pg_`, cột
   `tenant_id` đọc từ `pg_attribute` chứ không từ `information_schema.columns`, quyền hỏi theo oid), và
   `_refuse_blocked` ném `OffboardingRefusedError` nêu `schema.table` của mọi bảng nó trả, trước mọi kiểm khác. Vì
   `export_rows` và `purge_rows` đều gọi `_refuse_blocked` đầu tiên, lượt từ chối trước lô xuất đầu và trước câu xóa đầu.
4. **Kho chưa tạo là rỗng** (R11.12): câu quy tắc viết một lần ở docstring của `ObjectStoragePort.list_objects` và
   `VectorIndexPort.delete_by_tenant` (`packages/python/dw_knowledge/src/dw_knowledge/ports.py`), docstring của
   `MemoryVectorPurgePort` (`packages/python/dw_memory/src/dw_memory/ranking.py`) trỏ về đó.
   `MinioObjectStorageAdapter._list_sync` trả `[]` khi `bucket_exists` sai; `QdrantVectorIndexAdapter.delete_by_tenant`
   trả về khi `collection_exists` sai, phép hỏi nằm trong khối `try` hiện có để một Qdrant không với tới được vẫn ném
   `InfrastructureError`. Một module `tests/support/absent_store.py` có hai hàm kiểm, `a_missing_bucket_lists_nothing`
   và `a_missing_collection_purge_is_done`, mà
   `packages/python/dw_knowledge/tests/integration/test_object_storage_contract.py`, một test Qdrant thật của chỉ mục tri
   thức trong `packages/python/dw_knowledge/tests/integration/` và
   `packages/python/dw_memory/tests/integration/test_qdrant_ranker.py` cùng gọi.
5. **Gói ghi ra tệp và tải theo phần** (R11.9): trong `apps/worker/src/dw_worker/consumers/offboarding.py`, thay
   `_build_bundle` bằng một hàm ghi vào một `tempfile.TemporaryFile()` (tệp không tên, mất khi đóng, cả khi tiến trình
   chết): mỗi bảng một mục `tables/<schema>.<table>.ndjson` mở bằng `ZipFile.open(name, "w", force_zip64=True)`, mỗi lô
   mã hóa và ghi trong `asyncio.to_thread` rồi bỏ; một bảng tới thành hai đợt không liền nhau thì ném lỗi thay vì ghi
   hai mục cùng tên; blob đọc và ghi từng cái một (`blobs/artifacts/<key>`, `blobs/attachments/<key>`), không gom vào
   dict. Lane khai `ExportSinkPort` với một phương thức `put_stream(key, data, length, content_type)`;
   `MinioObjectStorageAdapter.put_stream` tạo bucket khi chưa có như `_put_sync` rồi gọi
   `Minio.put_object(bucket, key, data, length, content_type=...)`, SDK tải theo phần 5 MiB khi tệp lớn hơn một phần;
   `build_export_bucket` (`apps/worker/src/dw_worker/composition.py`) trả kiểu adapter đó. Ràng buộc: worker của compose
   có hệ tệp gốc ghi được và không tmpfs (`infra/compose/docker-compose.yml:472-531`), nên tệp tạm nằm trên đĩa và chỉ
   cache trang của nó vào cgroup; gói nén cỡ 157 MB mỗi 10^6 bản ghi (`db/bench/offboarding/RESULTS.md`); đĩa đầy là một
   `OSError` trong lúc xuất, trước `purging`, nên `failed`. Mỗi blob nằm trọn trong bộ nhớ một lần, chặn bởi giới hạn tải
   lên 50 MiB (`apps/api/src/dw_api/routes/v1/knowledge.py:30`).
6. **Làm tiếp một yêu cầu đã tải gói** (R11.10, R11.11): `claim_requested` trả mỗi yêu cầu nhận được thành một
   `OffboardingClaim(tenant_id, resume_export_key)`; câu `UPDATE` đặt
   `status = CASE WHEN status = 'purging' AND export_key IS NOT NULL THEN 'purging' ELSE 'exporting' END` và trả
   `export_key` chỉ cho yêu cầu giữ `purging`. `TenantOffboardingLane.run` với khóa làm tiếp hỏi
   `ExportSinkPort.has_object(key)` (`stat_object`; `NoSuchKey` hay `NoSuchBucket` là `False`, lỗi khác ném) và hỏng khi
   gói không còn, rồi bỏ qua xuất và tải; từ lúc yêu cầu ở `purging` (sau `mark_status("purging")`, hay ngay từ đầu
   khi làm tiếp), mọi lỗi được ném lại thành `PurgeUnfinishedError` mang `export_key`, và
   `build_offboarding_consumer` ghi `mark_status(tenant, "purging", export_key=..., error=...)` cho lỗi đó, `failed` cho
   mọi lỗi khác như hôm nay. `mark_status("purging")` chỉ chạy sau khi `put_stream` trả về. Chỉ `Exception` được bắt:
   worker tắt giữa lượt (`CancelledError`) không đổi trạng thái, và lần nhận lại sau `_STALE_CLAIM_MINUTES` làm tiếp
   theo trạng thái đã ghi. Docstring đầu module của lane và của `claim_requested` nói lại chuyện làm tiếp theo cách mới.
   Lần làm tiếp sau khi lần xóa SQL đã commit không ghi audit thứ hai: `_record_purge_audit` bỏ qua khi công ty không còn
   workspace (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:701-713`). Các phép từ
   chối của R11.5 (kiểm vòng trong `order_purge_steps`), R11.7 và R11.13 chạy trong `_refuse_blocked`, mà `export_rows` gọi
   trước lô đầu (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:542-544`,
   `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:617-624`), trước khi yêu cầu sang
   `purging`, nên vẫn kết thúc `failed`;
   chỉ một thay đổi catalog giữa lúc xuất và lúc xóa rơi vào `purging` và được thử lại tới ticket 09.
7. **Giữ lượt còn sống, một gói mỗi yêu cầu** (R11.17, R11.18, R11.19): `OffboardingClaim` mang thêm `request_id`;
   `export_key` là `<tenant_id>/offboarding-<request_id>.zip`, nên lần xuất lại của cùng yêu cầu ghi đè gói trước, và
   `clock` rời `TenantOffboardingLane` (dòng `clock=clock` của lane ở `apps/worker/src/dw_worker/main.py` bỏ theo). Store
   có `keep_claim(tenant_id)`: dưới `app.tenant_id`, `UPDATE ... SET updated_at = now()` chỉ cho yêu cầu của tenant đó
   đang `exporting` hay `purging`; mỗi tenant có nhiều nhất một yêu cầu đang chạy (chỉ mục
   `uq_tenant_offboarding_requests_active`, `db/migrations/versions/5d9d89ffc716_tenant_offboarding_requests.py:63-66`,
   cũng là thứ khiến người vận hành không mở được yêu cầu mới khi yêu cầu cũ còn `purging`), nên làm mới theo tenant là
   làm mới đúng yêu cầu đó. `run` chạy phần việc của lượt và một tác vụ nền gọi `keep_claim` mỗi `heartbeat_seconds`
   (mặc định 300, một phần sáu `_STALE_CLAIM_MINUTES`), hủy tác vụ nền khi lượt xong hay hỏng; một lần `keep_claim` hỏng
   được ghi log, hai lần liền thì tác vụ nền ném `ClaimLostError`, phần việc bị hủy và lượt hỏng với lỗi đó (R11.19).
8. **Đo lại** (R11.9): build ảnh worker từ commit tính năng (`infra/docker/worker.Dockerfile`, không push, xóa sau khi
   đo), `bench_offboarding.py setup` rồi `run --tenant big` dưới `--cpus 1.0 --memory 1g --memory-swap 1g`, với bucket
   đính kèm thật (`feedback`, chưa có) và Qdrant của compose với một collection tri thức chưa có, nên `_worker_env` của
   harness bỏ hai chỗ né của lần đo trước. Ghi anon lớn nhất (mẫu mỗi giây), `memory.peak` (gồm cache trang của tệp
   tạm), thời gian xuất và xóa, số dòng, số id khác
   nhau, md5 so với seed và số dòng của công ty khác vào `db/bench/offboarding/RESULTS.md` và Comments; xóa database,
   container và ảnh sau khi đo.
9. Test của từng tiêu chí dưới đây; `mutations/08.yaml` mỗi kiểm soát FH37-FH41 và FH44 một đột biến, không chạy
   `scripts/mutate.py` ở ticket này (`.claude/rules/wave-close.md`).

## Tiêu chí chấp nhận

- [x] R11.9 (FH37): `test_the_bundle_writer_holds_one_batch_not_the_table` dựng gói từ 10 lô 1.000 dòng tiếng Việt
      khoảng 2 KB mỗi dòng, sinh dần, dưới `tracemalloc`: đỉnh dưới 32 MB và mục ndjson có đúng 10.000 dòng theo thứ tự;
      sai nếu bản ghi vẫn gom dòng của cả bảng trước khi ghi (cách của `b0113f4` vượt ngưỡng, test đỏ).
- [x] R11.9 (FH37): gói dựng từ `export_rows` thật của tenant A khi tenant B có dòng ở cùng các bảng có mọi dòng của A
      đúng một lần và không dòng nào có `tenant_id` của B; sai nếu một dòng của B có trong gói.
- [x] R11.9: một bảng tới thành hai đợt không liền nhau → bản ghi ném lỗi, không có hai mục cùng tên; sai nếu gói có
      hai mục `tables/<bảng>.ndjson`.
- [x] R11.9: `put_stream` của tệp 11 MiB lên SeaweedFS thật đọc lại đúng từng byte, và ETag của đối tượng mang hậu tố
      `-<số phần>` của một lần tải theo phần; sai nếu tệp được tải bằng một `PUT` duy nhất.
- [x] R11.9: `bench_offboarding.py run --tenant big` trên ảnh của commit tính năng, 1 CPU / 1 GiB, không swap: không
      `oom_kill`, anon lớn nhất dưới 512 MiB, gói có đúng 1.000.000 dòng `studio.records`, 1.000.000 id khác nhau, md5 khớp
      seed, 0 dòng của công ty khác; sai nếu worker bị giết hay một trong các số đó lệch (đo, không có trong CI).
- [x] R11.10 (FH38): một yêu cầu `purging` có `export_key`, quá `_STALE_CLAIM_MINUTES` → `claim_requested` trả nó với
      `resume_export_key` bằng `export_key` đó và trạng thái giữ `purging`; một yêu cầu `exporting` quá hạn → khóa rỗng,
      trạng thái `exporting`; sai nếu lần nhận đặt lại `exporting` cho yêu cầu `purging`.
- [x] R11.10 (FH38): lane chạy với `resume_export_key` không gọi `export_rows`, không gọi `put_stream`, gọi `purge_rows`
      và xóa blob, vector, rồi ghi `completed` với chính khóa đó; sai nếu có một gói mới hay `export_key` đổi.
- [x] R11.10 (FH38): lane làm tiếp khi `has_object` trả `False` → không gọi `purge_rows`, không xóa blob hay vector,
      trạng thái cuối `purging` có `error`; sai nếu lần xóa chạy khi gói không còn.
- [x] R11.11 (FH38): kho vector bộ nhớ hỏng sau khi yêu cầu sang `purging` → trạng thái cuối `purging`, `error` nêu
      lỗi, `export_key` giữ, không có `completed` và không có `failed`; `export_rows` hỏng → `failed` như hôm nay; sai
      nếu lỗi sau `purging` chuyển `failed`.
- [x] R11.10 (FH38): `purge_rows` gọi hai lần cho cùng tenant (lần thứ hai như lượt làm tiếp sau lần xóa đã commit)
      → đúng một audit `tenant.offboarding.purged` cho tenant đó; sai nếu lượt làm tiếp ghi audit thứ hai hay hỏng ở audit.
- [x] R11.17 (FH44): lane có `export_rows` chậm hơn `heartbeat_seconds` (rút còn 0,05 giây trong test) gọi `keep_claim`
      ít nhất hai lần trong lượt và không gọi nữa sau khi lượt xong hay hỏng; sai nếu gỡ vòng làm mới (0 lần gọi).
- [x] R11.19 (FH44): `keep_claim` ném hai lần liền khi `export_rows` còn đang chạy → lượt dừng với `ClaimLostError`,
      `put_stream` không được gọi; sai nếu lượt chạy tiếp tới tải gói.
- [x] R11.17 (FH44): `keep_claim(A)` đổi `updated_at` của yêu cầu `exporting` của A, không đổi yêu cầu `completed` của A
      hay yêu cầu `exporting` của B; sai nếu một trong hai đổi.
- [x] R11.18 (FH44): hai lượt của cùng `OffboardingClaim` (lần đầu chết trước `purging`) gọi `put_stream` với cùng
      khóa `<tenant_id>/offboarding-<request_id>.zip`; sai nếu khóa sinh theo đồng hồ hay khác nhau giữa hai lần.
- [x] R11.12 (FH39): SeaweedFS thật: `list_objects` trên bucket chưa có trả `[]`; Qdrant thật: `delete_by_tenant` của
      chỉ mục tri thức và của bộ xếp hạng bộ nhớ trên collection chưa có trả về không lỗi; một Qdrant ở cổng không có
      gì → chỉ mục tri thức vẫn ném `InfrastructureError`; sai nếu bỏ phép kiểm tồn tại ở một adapter (test của adapter
      đó đỏ).
- [x] R11.12 (FH39): lane với bucket đính kèm thật chưa có và chỉ mục tri thức Qdrant thật trên collection chưa có, các
      cổng khác giả → trạng thái cuối `completed`; sai nếu lượt dừng ở `list_objects` hay `delete_by_tenant`.
- [x] R11.13 (FH40): bảng thử `memory.ob_cols` (dạng của bước 1, có một dòng của tenant) → `export_rows` ném
      `OffboardingRefusedError` nêu `memory.ob_cols` trước lô đầu, `purge_rows` ném cùng lỗi, 0 dòng bị xóa ở bảng thử
      và ở `platform.workspaces`; sai nếu `export_rows` trả lô nào hay lượt xóa chạy.
- [x] R11.14 (FH41): test của bước 1 xanh sau bản vá ở cả ba ca; trả `_TENANT_TABLES` về `studio` với `platform` → ca
      `memory` đỏ; bỏ kiểm theo cột → ca `platform.feedback` đỏ; `test_offboarding_covers_every_table_it_has_to` vẫn
      `[]` trên checkout đã migrate; sai nếu một trong ba ca không nêu tên bảng.
- [x] Xong: `uv run pytest -m "unit or integration" apps/worker/tests packages/python/dw_platform/tests/integration/test_offboarding.py packages/python/dw_platform/tests/integration/test_offboarding_registry.py packages/python/dw_platform/tests/integration/test_offboarding_coverage.py packages/python/dw_knowledge/tests/integration packages/python/dw_memory/tests/integration/test_qdrant_ranker.py`
      xanh.

## Nguồn

- `apps/worker/src/dw_worker/consumers/offboarding.py:141-172`
- `apps/worker/src/dw_worker/consumers/offboarding.py:175-196`
- `apps/worker/src/dw_worker/consumers/offboarding.py:199-222`
- `apps/worker/src/dw_worker/composition.py:130-137`
- `apps/worker/src/dw_worker/main.py:880-883`
- `infra/compose/docker-compose.yml:472-531`
- `apps/api/src/dw_api/routes/v1/knowledge.py:30`
- `db/migrations/versions/5d9d89ffc716_tenant_offboarding_requests.py:63-66`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:80`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:88-111`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:617-654`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:701-713`
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:736-767`
- `packages/python/dw_knowledge/src/dw_knowledge/adapters/minio_storage.py:23-33`
- `packages/python/dw_knowledge/src/dw_knowledge/adapters/minio_storage.py:57-69`
- `packages/python/dw_knowledge/src/dw_knowledge/adapters/qdrant_index.py:224-234`
- `packages/python/dw_memory/src/dw_memory/adapters/qdrant_ranker.py:199-206`
- `packages/python/dw_knowledge/src/dw_knowledge/ports.py:147`
- `packages/python/dw_knowledge/src/dw_knowledge/ports.py:189`
- `packages/python/dw_platform/tests/integration/test_offboarding_coverage.py:82-91`
- `packages/python/dw_platform/tests/integration/test_offboarding_coverage.py:147-149`
- `db/bench/offboarding/worker_entry.py:30-67`
- `db/bench/offboarding/bench_offboarding.py:421-447`
- `db/bench/offboarding/RESULTS.md`; `.claude/plans/studio/discovery/issues/09-grants-partitions-offboarding.md`
  (`## Answer`).
- spec: R11.9-R11.14, R11.17-R11.19, FH37-FH41, FH44; Quyết định 5/11/2026.

## Comments

- 2026-11-05 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (người dựng; không migration, không route):
  lượt 1 có ba HIGH (lượt dài bị nhận lại, khóa theo đồng hồ để lại gói mồ côi, audit khi làm tiếp), lượt xác nhận ba
  HIGH (vòng làm mới chỉ ghi log, làm tiếp không kiểm gói, `memory.peak` gồm cache trang); đã sửa theo khuyến nghị, ghi ở
  Quyết định 5/11/2026 của spec. MEDIUM để lại: (1) một công ty không có workspace nào được purge mà không có audit
  (`_record_purge_audit` bỏ qua, có từ trước; ticket 09 chạm audit của lane, xem lại ở đó); (2) worker chết giữa một lần
  tải theo phần để lại các phần dở trong bucket xuất (SDK chỉ hủy khi có ngoại lệ): cần quy tắc vòng đời
  `AbortIncompleteMultipartUpload` của bucket `dw-exports` ở triển khai, chưa đo SeaweedFS có hỗ trợ không; (3) bảng
  chỉ có quyền theo cột chặn cả lượt kể cả khi công ty không có dòng nào ở đó (quyết định, R11.13).
- 2026-11-05 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-05 (agent): test đỏ trước: `test_a_table_read_by_column_only_is_named_in_every_schema` trên mã cũ đỏ cả ba ca
  (`studio`: chỉ có hai dòng R4.1, không có R11.14; `memory` và `platform.feedback`: `[]`), xanh sau bản vá.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): làm xong (`3d4be83`). Làm khác chữ của ticket ở bảy chỗ: (1)
  `mark_status` chỉ ghi yêu cầu đang `exporting` hay `purging`, như `keep_claim`: đọc ra lúc dựng rằng nó ghi mọi dòng của
  tenant, nên một công ty nộp lại sau khi hỏng bị ghi đè cả yêu cầu cũ, kể cả `export_key` của gói thật; có test. Nếu sai
  thì: `mark_status` nhận `request_id`; (2) `BucketPort` của lane bỏ `put_object`, vì bucket tri thức và đính kèm chỉ được
  đọc và xóa; (3) lượt mất lượt nhận (`ClaimLostError`) không ghi trạng thái nào, vì worker khác có thể đã giữ dòng; (4)
  dạng bảng thử "lane không đọc, không xóa" của test phủ đổi từ `GRANT SELECT (id)` sang `REVOKE ALL`, vì bảng chỉ có quyền
  theo cột nay bị nêu tên dù có dòng loại trừ (R11.14), và test đổi tên thành
  `test_a_table_the_lane_neither_reads_nor_deletes_is_named_until_listed`; (5) phép đo dùng một tên bucket đính kèm và một
  tên collection ngẫu nhiên chưa có thay cho `feedback`, để chắc chắn kho chưa từng được tạo và không chạm dữ liệu dev; (6)
  commit tính năng mang luôn test để mỗi commit trên `main` xanh; (7) một dòng `clock=clock` ở
  `apps/worker/src/dw_worker/main.py` vào cùng commit, khi `main.py` trong cây không còn thay đổi chưa commit của lane 1.
- 2026-11-05 (agent): đo (RESULTS.md, "Sau foundations-hardening 08"): 10^6 bản ghi, worker thật 1 CPU / 1 GiB không swap,
  Qdrant với collection chưa có và bucket đính kèm chưa có: `completed`, `oom_kill` 0, anon lớn nhất 263.041.024 B (head:
  `oom_kill` sau 34,5 giây ở 1.074.491.392 B), `memory.peak` 499.367.936 B gồm cache trang của tệp tạm, xuất 163,3 s, xóa
  14,3 s; gói 156,4 MB có đúng 1.000.000 dòng, 1.000.000 id khác nhau, md5 khớp seed, 0 dòng công ty khác; ba công ty kia
  còn nguyên. Test rẻ: đỉnh `tracemalloc` 17,3 MB với bản ghi luồng, 134,3 MB với `_build_bundle` cũ, ngưỡng 32 MB.
- 2026-11-05 (agent): cổng: `uv run pytest -m unit --cov` trên bản xuất sạch của `3d4be83` 3694 passed, 9 skipped; mypy
  trong `python:3.12-slim-bookworm` không lỗi (897 tệp); integration (`DW_TEST_DB_SUFFIX=_lane2`): offboarding,
  registry, coverage của `dw_platform` 57 passed, contract object storage 7 passed, Qdrant tri thức, bộ xếp hạng bộ nhớ và
  hai tệp offboarding của worker 23 passed; lint-imports 16 kept, `verify_invariants`, `verify_architecture`,
  `check_hygiene` (0), `release_manifest --check`, gitleaks (không lộ), Prettier xanh. Ruff toàn repo trong cây làm việc đỏ
  ở tệp chưa commit của lane 1 (`dw_agent_runtime/ports.py`, `langgraph_runner.py`), xanh trên bản xuất sạch.
  `reviewing-feature-security` (đọc): biên 1, 5, 6 áp dụng, có test âm; 2, 3 không (không route, không đường agent); 4:
  tên mục zip lấy từ khóa đối tượng của chính tenant, như trước (LOW, có từ trước). `mutations/08.yaml` 15 đột biến cho
  FH37-FH41 và FH44, chưa chạy `scripts/mutate.py`; bẻ tay bảy cái, mỗi kiểm soát ít nhất một: cả bảy đỏ.
- 2026-11-05 (agent): để lại cho lúc đóng hàng đợi: `scripts/mutate.py` trên `mutations/08.yaml`; toàn bộ
  `make test-integration`; độ trễ: ticket không đổi route nào, chỉ lane `offboarding` (`claim_requested`, `mark_status`,
  `keep_claim`), nên `.claude/rules/latency.md` không có thao tác API nào để đo; dòng "Tiếp theo" của area file cho spec
  này (gate không ghi vào `.claude/plans/studio.md` theo phân lane).
