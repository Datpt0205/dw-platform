# Offboarding một công ty 10^6 bản ghi trong giới hạn worker, và bảng chỉ có quyền SELECT theo cột (discovery 09, FOG-32)

Ticket: [`.claude/plans/studio/discovery/issues/09-grants-partitions-offboarding.md`](../../../.claude/plans/studio/discovery/issues/09-grants-partitions-offboarding.md).
Harness: [`bench_offboarding.py`](bench_offboarding.py) và tiến trình trong container [`worker_entry.py`](worker_entry.py) (`7782231`). Mọi
số ở đây là _measured_ trên máy dev ngày 5/11/2026, trên schema ở head `b0113f4` (alembic `902ac246a9dc`: record-access/03
`c7d7112`, record-access/04, field-security/01, custom-objects/03), không phải máy tham chiếu.

## Cách chạy lại

```sh
docker build -f infra/docker/worker.Dockerfile -t dw-worker:<commit> .   # ảnh của chính commit đo, không push
make bench-offboarding IMAGE=dw-worker:<commit> OUT=<thư mục>
# hay từng bước:
export DW_TEST_DB_SUFFIX=_fog32
uv run python db/bench/offboarding/bench_offboarding.py setup              # seed: alembic upgrade head rồi gieo
uv run python db/bench/offboarding/bench_offboarding.py run --tenant big --image dw-worker:<commit> --out <thư mục>
uv run python db/bench/offboarding/bench_offboarding.py run --tenant big --variant spool --image ... --out ...
uv run python db/bench/offboarding/bench_offboarding.py probe --out <thư mục>
uv run python db/bench/offboarding/bench_offboarding.py drop               # xóa hai database và container còn sót
```

Không có trong `testpaths`, không chạy trong CI. Lần chạy ghi ở đây chạy từ một bản `git archive HEAD` sạch (cùng
`.venv` của repo), vì cây làm việc lúc đó có migration chưa commit của làn build 1; ảnh worker build từ chính bản ấy.

## Máy, ảnh và giới hạn

- Windows 11 (10.0.26300), 16 luồng; Docker Desktop 16 CPU, 7,9 GB; harness Python 3.12.10, SQLAlchemy 2.0.54, asyncpg
  0.31.0.
- PostgreSQL 16.15 (`postgres:16-alpine`) của compose `dwskel`, container không giới hạn, `shared_buffers` 128 MB,
  `work_mem` 4 MB. SeaweedFS 4.48 của compose làm kho S3.
- Ảnh `dw-worker:fog32-b0113f4`, build tại chỗ từ `infra/docker/worker.Dockerfile` (base
  `python:3.12-slim-bookworm@sha256:e697c818…`, uv 0.11.31), 2,72 GB, không push, đã xóa sau lần đo.
- Container: `--cpus 1.0 --memory 1g` như `infra/compose/docker-compose.prod.yml` (worker), thêm `--memory-swap 1g` (không
  swap; overlay để swap cho máy chủ quyết, nên đây là trường hợp chặt hơn). Overlay **không đặt giới hạn pids** cho worker
  (chỉ docgen có `pids_limit: 512`), nên không đặt; `pids.peak` đo được 14-35.
- Tiến trình đo là worker thật: `python -m dw_worker.main` (CMD của ảnh) qua `worker_entry.py head`, mọi lane đăng ký,
  profile `local`, `dw_app` trên database đo. Shell bọc ngoài chỉ để cgroup còn đọc được sau khi Python bị giết.
- Host đọc `memory.current`, `memory.stat` (anon, file), `memory.events` mỗi giây bằng `docker exec`, và
  `memory.peak`, `pids.peak`, `cpu.stat` khi xong; trạng thái lấy từ dòng `platform.tenant_offboarding_requests` (cột
  `updated_at` là đồng hồ của database).
- Hai chỗ khác cấu hình compose, cả hai vì kho dev chưa từng được ghi (đã đo trước, xem Phát hiện 2): bucket đính kèm
  phản hồi trỏ vào `dw-artifacts` (cùng tiền tố `feedback/<tenant>/`), và không đặt `QDRANT_URL` (chỉ mục tri thức trong
  bộ nhớ, không có collection bộ nhớ).

## Dữ liệu gieo

`dw_migrator` gieo một lần vào database mẫu, mỗi lần đo bắt đầu từ một bản `CREATE DATABASE … TEMPLATE` mới (lần xóa ăn
mất dữ liệu nó đo). Bốn công ty, mỗi công ty 20 workspace, 200 thành viên `active` (mỗi người một membership, vai trò
`member`, một dòng `studio.principal_scopes` từ `studio.ensure_principal_scope()`), 5 object, mỗi object 5 trường lưu
trong `data` (email, địa chỉ, ghi chú, nguồn, công ty) và 3 trường lọc ở slot (`t01` điện thoại, `i01` tiền VND, `d01`
ngày). Bản ghi gieo bằng `COPY` (`copy_records_to_table`), 100.000 dòng mỗi giao dịch dưới `app.tenant_id`, qua trigger
chủ sở hữu (`ck_records_owner_in_tenant`); tên và giá trị tiếng Việt có dấu.

| Công ty | Bản ghi   | Vai trò trong lần đo                                     |
| ------- | --------- | -------------------------------------------------------- |
| `big`   | 1.000.000 | câu hỏi của ticket                                       |
| `mid`   | 250.000   | chi phí mỗi bản ghi (điểm thứ hai)                       |
| `small` | 100.000   | chi phí mỗi bản ghi (điểm thứ nhất)                      |
| `other` | 10.000    | không bao giờ offboard: gói không được có, xóa phải chừa |

Gieo 1.360.000 bản ghi: 341 giây, database 2.090 MB. Mỗi bản ghi `SELECT *` có 89 cột (72 slot, đa số null, và cột sinh
`access_key`) nên một dòng ndjson là 1,88 KB (tệp `studio.records.ndjson` của `big`: 1.881.445.037 byte). Dấu vân tay
của mỗi công ty là `count(*)` và md5 của các id sắp xếp nối bằng dấu phẩy, đọc dưới `dw_migrator` trước lần đo.

## Bảng kết luận

| #   | Đạt khi (ticket)                                                            | Số đo                                                                                                                                                                                                              | Kết quả                                         |
| --- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------- |
| 1   | Xuất xong không bị OOM, `memory.peak` dưới 1 GiB                            | Head: worker bị giết vì bộ nhớ (`oom_kill` 1) 34,5 giây sau khi nhận yêu cầu, `memory.peak` 1.074.491.392 B (chạm trần). Ngưỡng thật ở head khoảng 95.000 bản ghi: 100.000 bản ghi cũng bị giết ở 1 GiB            | **Trượt**                                       |
| 2   | Tệp xuất có đúng 10^6 dòng, mỗi dòng một lần                                | Head không ra tệp. Nguyên mẫu ghi luồng (`--variant spool`, chỉ trong tiến trình đo): 1.000.000 dòng, 1.000.000 id khác nhau, md5 khớp seed, 0 dòng của công ty khác; `memory.peak` 498.204.672 B, xuất 153,7 giây | **Trượt ở head**; đạt với nguyên mẫu            |
| 3   | Bảng chỉ có quyền theo cột hoặc được xuất, hoặc làm test phủ offboarding đỏ | `studio.fog32_probe`: không xuất, không xóa, test phủ đỏ (`R4.1 … is not exported`, `… is not purged`)                                                                                                             | **Đạt** trong `studio`                          |
| 3b  | Trượt khi bảng đó bị bỏ qua mà không test nào đỏ (failure-modes #0)         | `memory.fog32_probe` và `platform.feedback` cấp lại theo từng cột: `dw_app` đọc được dòng, `export_rows` bỏ qua, lần xóa bỏ qua, test phủ vẫn xanh (`[]`)                                                          | **Trượt** ngoài `studio` và bảng `platform` mới |

## Câu 4: xuất 10^6 bản ghi dưới 1 CPU / 1 GiB

Một lần đo là một tiến trình worker mới trên một bản database mới; "xuất" và "xóa" là khoảng giữa các `updated_at` của
dòng yêu cầu (nhận → `purging` → `completed`), gồm cả tải gói lên S3.

| Lần chạy                   | Bản ghi   | Giới hạn | `memory.peak` (B) | anon lớn nhất (mẫu mỗi giây) | Kết cục                                                           | Xuất    | Xóa    | Gói zip / ndjson bản ghi |
| -------------------------- | --------- | -------- | ----------------- | ---------------------------- | ----------------------------------------------------------------- | ------- | ------ | ------------------------ |
| Worker không việc, 60 giây | 0         | 1 GiB    | 233.140.224       | 174.297.088                  | —                                                                 | —       | —      | —                        |
| Head                       | 100.000   | 1 GiB    | 1.073.741.824     | 598.933.504                  | `oom_kill` 1, 13,6 giây sau khi nhận                              | —       | —      | —                        |
| Head                       | 100.000   | 4 GiB    | 1.118.789.632     | 873.893.888                  | `completed`, 100.000 dòng, md5 khớp                               | 17,9 s  | 1,6 s  | 15,4 MB / 188,0 MB       |
| Head                       | 250.000   | 5 GiB    | 2.490.269.696     | 2.349.678.592                | `completed`, 250.000 dòng, md5 khớp                               | 43,6 s  | 4,1 s  | 38,7 MB / 470,3 MB       |
| **Head**                   | 1.000.000 | 1 GiB    | 1.074.491.392     | 1.063.600.128                | **`oom_kill` 1**, 34,5 giây sau khi nhận, yêu cầu kẹt `exporting` | —       | —      | —                        |
| Nguyên mẫu `spool`         | 1.000.000 | 1 GiB    | 498.204.672       | 348.737.536                  | `completed`, 1.000.000 dòng, md5 khớp, 0 dòng lạ                  | 153,7 s | 14,3 s | 156,6 MB / 1.881,4 MB    |

Sau lần `spool`: `big` còn 0 bản ghi, `mid` 250.000, `small` 100.000, `other` 10.000 (lần xóa chỉ chạm công ty của nó).
Gói có 16 mục, `studio.principal_scopes` trong đó (200 dòng, D6). Container từ lúc chạy tới `completed`: 178,4 giây, CPU
141,0 giây, bị bóp CPU 516 lần (41,1 giây).

**Chi phí của head theo cỡ.** Hai điểm đo cho 9.143 byte đỉnh mỗi bản ghi trên nền 204 MB: 10^6 bản ghi cần khoảng
9,35 GB (ngoại suy, không đo được trên máy 7,9 GB), và 1 GiB chứa khoảng 95.000 bản ghi, khớp với lần 100.000 bị giết.
Một bản ghi tốn gấp 4,9 lần dòng ndjson 1,88 KB của nó vì `_build_bundle` giữ cả bảng ba lần cùng lúc (suy từ mã, khớp
với số): danh sách chuỗi dòng (chữ tiếng Việt ngoài Latin-1 làm cả chuỗi 2 byte một ký tự trong CPython), chuỗi
`"\n".join` thứ hai cỡ bằng thế, rồi bản UTF-8 `writestr` mã hóa, cộng gói nén và bản `getvalue()`. Đọc theo lô keyset
(R11.2) đã làm phần cơ sở dữ liệu nhỏ; phần còn lại nằm ở lane worker.

**Nguyên mẫu `spool`** (`worker_entry.py`, chỉ thay `_build_bundle` trong tiến trình đo, không sửa mã repo): mỗi bảng ghi
thẳng vào một mục zip trên tệp tạm theo từng lô, rồi đọc gói nén (156,6 MB) một lần để đưa cho `put_object` như cũ. Đỉnh
498 MB gồm cache trang của tệp tạm; anon lớn nhất 349 MB, nền worker 174 MB. Gói nén vẫn nằm trọn trong bộ nhớ một
lần, nên đỉnh còn tăng theo cỡ gói (khoảng 0,16 GB mỗi 10^6 bản ghi của dạng này); tải lên theo phần từ tệp
(`put_object` với luồng và `length=-1`) bỏ nốt phần đó. Tốc độ: 0,154 ms một bản ghi so với 0,175-0,179 ms của head.

## Câu 3, phần quyền SELECT theo cột

`probe` trên một bản database mới, với `dw_migrator` trong database đo (không migration nào trong repo), mỗi bảng một
dòng của công ty `other`:

- `studio.fog32_probe`, `memory.fog32_probe`: bảng mới có `tenant_id`, RLS ENABLE và FORCE, policy
  `tenant_isolation_*`, `REVOKE ALL` rồi `GRANT SELECT (id, tenant_id, body), DELETE` cho `dw_app`.
- `platform.feedback` (có trước luật, trong `_PLATFORM_PREDATING`): `REVOKE SELECT`, rồi `GRANT SELECT` **mọi cột** cho
  `dw_app`: ứng dụng đọc bảng y như trước.

| Bảng                 | `has_table_privilege` SELECT | `has_any_column_privilege` SELECT | DELETE | Trong `_CATALOG_EXPORTABLE` / `_PURGEABLE` | `dw_app` đọc được (dòng) | Dòng trong `export_rows` thật |
| -------------------- | ---------------------------- | --------------------------------- | ------ | ------------------------------------------ | ------------------------ | ----------------------------- |
| `studio.fog32_probe` | false                        | true                              | true   | không / không                              | 1                        | 0                             |
| `memory.fog32_probe` | false                        | true                              | true   | không / không                              | 1                        | 0                             |
| `platform.feedback`  | false                        | true                              | true   | không / không                              | 1                        | 0                             |

`offboarding_violations` của `test_offboarding_coverage.py` (chính hàm test chạy) trên catalog đó:

- trước probe: `[]`;
- sau probe: `['R4.1 studio.fog32_probe is not exported and has no export exclusion', 'R4.1 studio.fog32_probe is not
purged and has no purge exclusion']`. Không dòng nào cho `memory.fog32_probe` hay `platform.feedback`.

`pytest packages/python/dw_platform/tests/integration/test_offboarding_coverage.py` ở head: 14 passed (trong đó
`test_a_table_read_by_column_and_not_deleted_is_named_until_listed` cho `studio` và một bảng `platform` mới).

Vậy bộ lọc `has_table_privilege` **mù** với quyền theo cột, đúng như ticket hỏi, và test phủ bắt được điều đó **chỉ**
cho bảng `studio` và bảng `platform` tạo sau luật. Truy vấn của test giới hạn `n.nspname IN ('studio', 'platform')` và
bỏ qua mọi bảng trong `_PLATFORM_PREDATING`; database hôm nay có bảng tenant ở `knowledge` (4) và `memory` (3), và mỗi
context sản phẩm sau này thêm schema của nó. Một bảng ở đó chỉ còn quyền theo cột thì dòng của công ty không vào gói xuất,
không bị xóa (lane chỉ xóa bảng nó SELECT được), và không test nào đỏ: failure-modes #0, một check không thấy thứ nó
check.

## Phát hiện

1. **Gói xuất dựng trong bộ nhớ không qua nổi 1 GiB từ khoảng 95.000 bản ghi** (Câu 4). Hơn nữa, worker chết thì yêu cầu
   kẹt ở `exporting`; `claim_requested` nhận lại một yêu cầu cũ hơn 30 phút (`_STALE_CLAIM_MINUTES`), nên lane sẽ OOM lại
   mỗi 30 phút và mỗi lần kéo mọi lane khác của worker chết theo (suy từ mã, chưa đo vòng lặp). Đề xuất: ghi gói ra tệp
   tạm theo luồng như nguyên mẫu và tải lên theo phần, kèm một test đo bộ nhớ (đây là mục "Gói xuất offboarding ghi ra
   đĩa và tải lên theo phần" ở phần Ngoài phạm vi của spec `foundations-hardening`, nay có số).
2. **Lane thất bại trên một kho chưa từng được ghi.** Bucket `feedback` chỉ có sau lần tải đính kèm đầu tiên (API tạo khi
   `put`), và `list_objects` của bucket thiếu làm cả yêu cầu `failed` (`NoSuchBucket` → `InfrastructureError: object
storage list failed`, 12,4 giây sau khi nhận). Collection `dw_knowledge` chưa tạo làm
   `QdrantVectorIndexAdapter.delete_by_tenant` lỗi (`failed to delete tenant vectors`) **sau khi lần xóa SQL đã commit**:
   dữ liệu đã xóa, gói đã tải, yêu cầu `failed`, công ty kẹt ở `offboarding` (đo, 100.000 bản ghi). Bộ xếp hạng bộ nhớ
   coi collection chưa có là đã xóa xong; chỉ mục tri thức thì không: hai câu trả lời cho một câu hỏi (failure-modes #2).
3. **Bộ lọc `has_table_privilege` mù với quyền theo cột, và test phủ chỉ nhìn `studio` với bảng `platform` mới** (Câu 3).
   Đề xuất: test phủ đọc mọi schema có bảng mang `tenant_id` (hay policy `tenant_isolation_*`), không chỉ hai schema, và
   lane từ chối trước lần xuất đầu (R11.7) khi một bảng tenant có `has_any_column_privilege` mà không có
   `has_table_privilege`, thay vì lặng lẽ bỏ qua; bảng `_PLATFORM_PREDATING` ít nhất phải được xuất hoặc nêu tên.
