# Đo chi phí vai trò của tenant ở quy mô D12 (discovery 08, FOG-38)

Ticket: [`.claude/plans/studio/discovery/issues/08-rbac-cost.md`](../../../.claude/plans/studio/discovery/issues/08-rbac-cost.md).
Harness: [`bench_rbac.py`](bench_rbac.py) (`ad7d80c`). Mọi số ở đây là _measured_ trên máy dev ngày 5/11/2026, trên schema ở head
`044859c` (tenant-rbac/02 `b5677d345bc1`, /03 `d2b57239ef50`, /04 `ef68083f2905`), không phải máy tham chiếu.

## Cách chạy lại

```sh
make bench-rbac                                   # setup q1 q1gc q2 q3 q4 drop, JSON vào thư mục tạm của hệ thống
# hay từng bước, giữ database giữa các lần:
export DW_TEST_DB_SUFFIX=_fog38
uv run python db/bench/rbac/bench_rbac.py setup            # dw_bench_rbac_fog38: alembic upgrade head rồi gieo
uv run python db/bench/rbac/bench_rbac.py q1 q1gc q2 q3 q4 --out <thư mục>
uv run python db/bench/rbac/bench_rbac.py drop             # xóa dòng danh mục đã gieo, rồi drop database
```

`q2` chạy một lần trên một lần `setup` (vai trò gán hàng loạt và khóa đã thêm ở lại). Không có trong `testpaths`, không
chạy trong CI. Lần chạy ghi ở đây: `setup q1 q1gc q2 q3 q4` liền một mạch (gieo 66 giây, đo 19 phút), rồi `drop` (0 dòng
danh mục thử còn lại, database đã xóa).

## Máy và cấu hình

- Windows 11 (10.0.26300), 16 luồng, Python 3.12.10 (venv chung; CI dùng 3.12.15), SQLAlchemy 2.0.54, asyncpg 0.31.0,
  redis-py 5.3.1; Docker Desktop 16 CPU, 7,9 GB.
- PostgreSQL 16.15 (`postgres:16-alpine`) của compose `dwskel`, 127.0.0.1:25432, container không giới hạn CPU hay bộ
  nhớ, `shared_buffers` 128 MB, `work_mem` 4 MB, `synchronous_commit` on, READ COMMITTED; dùng chung với làn build 1,
  có thể chạy test cùng lúc. Một vòng `SELECT 1` từ harness: p50 1,29 ms, p95 1,67 ms. `track_functions = all` chỉ trên
  database đo, để chia thời gian một lần ghi cho từng trigger (`pg_stat_xact_user_functions`).
- Valkey 8.1.10 của compose (`redis://127.0.0.1:16379/7`) làm cache của `CachingMembershipLookup`, như wiring của API.
- App: `build_container(ApiSettings(profile="test", ...))` và `create_app` thật, gọi qua `httpx.ASGITransport` như
  `apps/api/tests/integration`; `rate_limit_per_minute=0` (240/phút mỗi người gọi từ chối chính lần đo; test cũng đặt 0).
  Hai bản app (có Valkey và không cache) và harness chạy chung **một tiến trình, một event loop**: `/me` của câu 2 (hai
  làn cạnh một lần ghi) vì thế chậm hơn ở một tiến trình API riêng, và lần gán "một mình" là số của riêng cơ sở dữ liệu.

## Dữ liệu gieo

Một công ty theo D12: 5.000 thành viên `active`, 200 workspace, mỗi người một membership và vai trò `member`; hai
`tenant_owner`. 200 khóa danh mục thử (`bench.k_000`..`bench.k_199`, `dw_migrator` chèn, `drop` xóa), 40 object × 5 hành
động = 200 khóa `obj.*` sinh từ định nghĩa sống (tenant-rbac/04), mỗi object 10 trường (800 khóa `fld.*` cho chủ sở
hữu). 30 vai trò, mỗi vai trò 20 khóa danh mục, 20 quyền object (độ sâu own/workspace/tenant xen kẽ) và 5 quyền trường.

- **Người nặng**: 10 membership ở 10 workspace, 3 vai trò mỗi workspace (30 vai trò khác nhau) cùng `member`:
  `effective_grants` trả 1.358 dòng, 458 khóa khác nhau (600 dòng `obj.*`, 150 dòng `fld.*`).
- **Chủ sở hữu**: `tenant_owner` (quyền tính động: mọi khóa danh mục cấp được, mọi `obj.*`, mọi `fld.*`), 1.255 dòng.
- **Người thường**: chỉ `member`, 8 dòng.
- `bench_held`: vai trò 1.000 người giữ (câu 2); sáu vai trò `bench_bulk_*` cho các lần gán 1.000 người.
- Một luật tách nhiệm miễn trừ được (`sod_bench_left_right`) và bốn luật trơ trên khóa không ai giữ.
- Câu 3 trên một công ty nhỏ riêng (5 người: hai chủ sở hữu, người gán, người của cuộc đua a, người nhận của cuộc đua b):
  cuộc đua không phụ thuộc cỡ công ty, còn mỗi lệnh trên bảng vai trò chạy `check_owner_coverage` của cả công ty.

## Bảng kết luận

| #   | Đạt khi (ticket)                                                                | Số đo                                                                                                                                                                                                                           | Kết quả                                                                            |
| --- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| 1   | `GET /api/v1/me` P95 ≤ 300 ms, P99 ≤ 1 s (`latency.md`)                         | Cache nóng P95/P99: người nặng 237,2/264,1 ms, chủ sở hữu 244,0/288,8, người thường 13,7/15,5. Ngay sau tăng version: 266,9/317,3; 275,9/306,7; 47,3/59,5                                                                       | **Đạt**; P95 sát ngưỡng vì GC của Python (Câu 1)                                   |
| 2   | Như dòng 1, kể cả lúc gán hàng loạt                                             | Trong lần gán 1.000 người: cache nóng P95 261,6 / P99 290,6 (n = 1.259); không cache 340,4 / 369,4 (n = 413). Cạnh lần sửa vai trò 1.000 người giữ: cache nóng P95 255,9-310,8. Với `gc.freeze()`: 50,9 / 62,7 và 142,9 / 166,4 | **Đạt** lúc gán hàng loạt có cache; **trượt P95** ở hai chỗ (Câu 2), P99 đạt mọi ô |
| 3   | 0 lần gán lọt sau thu hồi trên 200 lượt; bỏ `FOR SHARE` cho ít nhất một lần lọt | Head: 0/200 (miễn trừ tách nhiệm) và 0/200 (quyền của người gán). Bỏ `FOR SHARE`: 196/200 và 99/200 lần lọt                                                                                                                     | **Đạt**, hai test đỏ được                                                          |
| 4   | `session_user` là vai đăng nhập ở 1.000/1.000 lần                               | Pool `dw_app` của API 1.000/1.000, pool `dw_provisioner` 1.000/1.000, cả trong hàm SECURITY DEFINER; `SET ROLE`, `SET SESSION AUTHORIZATION` sang `dw_migrator` bị từ chối 200/200 mỗi loại                                     | **Đạt**                                                                            |

## Câu 1: `effective_grants`, đọc access version, `AccessContext`

1.000 lần mỗi câu dưới `dw_app` (`app.tenant_id` đặt cho phiên), sau 20 lần làm nóng. "Thực thi" là `Execution Time` của
`EXPLAIN (ANALYZE)` (1.000 lần riêng), "khứ hồi" là thời gian harness qua SQLAlchemy và asyncpg như app.

| Câu lệnh                                   | Dòng  | Thực thi p50 / p95 / p99 (ms) | Khứ hồi p50 / p95 / p99 (ms) |
| ------------------------------------------ | ----- | ----------------------------- | ---------------------------- |
| Đọc `tenant_access_versions` (mỗi request) | 1     | 0,07 / 0,12 / 0,16            | 1,38 / 2,09 / 2,60           |
| `effective_grants`, người nặng             | 1.358 | 6,67 / 9,93 / 12,18           | 11,36 / 16,59 / 257,24       |
| `effective_grants`, chủ sở hữu             | 1.255 | 2,42 / 3,43 / 4,08            | 4,83 / 6,58 / 7,84           |
| `effective_grants`, người thường           | 8     | 0,92 / 1,30 / 1,66            | 1,93 / 2,66 / 3,28           |
| Câu dựng AccessContext (`_HELD`), nặng     | 1     | 28,10 / 38,83 / 46,44         | 33,12 / 44,60 / 56,78        |
| `_HELD`, chủ sở hữu                        | 1     | 21,19 / 28,00 / 32,80         | 25,80 / 36,49 / 43,88        |
| `_HELD`, người thường                      | 1     | 10,17 / 15,12 / 19,61         | 11,74 / 15,20 / 17,99        |

`GET /api/v1/me`, 300 request mỗi ô qua app thật (ms):

| Người      | Cache nóng (Valkey) p50 / p95 / p99 | Ngay sau tăng version p50 / p95 / p99 | Không cache p50 / p95 / p99 |
| ---------- | ----------------------------------- | ------------------------------------- | --------------------------- |
| Nặng       | 21,9 / 237,2 / 264,1                | 70,6 / 266,9 / 317,3                  | 69,6 / 296,5 / 334,5        |
| Chủ sở hữu | 22,5 / 244,0 / 288,8                | 66,6 / 275,9 / 306,7                  | 62,7 / 290,3 / 316,6        |
| Thường     | 10,6 / 13,7 / 15,5                  | 36,0 / 47,3 / 59,5                    | 33,1 / 40,6 / 45,8          |

"Ngay sau tăng version": trước mỗi request đo, `dw_migrator` tăng `tenant_access_versions.version` của công ty (điều mọi
trigger trên bảng quyền làm), nên mỗi request trượt cache: đọc version, đọc Valkey, dựng lại, ghi Valkey.

**Kích thước `AccessContext` đã tuần tự hóa** (`caching_lookup._serialize`, thứ Valkey giữ): người nặng 110.158 byte (1.358
grant, 318 scope), chủ sở hữu 130.928 byte (1.255 grant, 1.247 scope), người thường 1.127 byte. Thân `/me`: 154.563,
171.007 và 1.295 byte. Một mục cho mỗi (version, workspace, issuer, subject), TTL 30 giây: 5.000 người thường cùng đăng
nhập ở một version là khoảng 5,5 MB; mỗi người nặng hay chủ sở hữu thêm 110-131 KB; một lần tăng version bỏ cả tập (khóa
cũ hết hạn theo TTL). Valkey chứa được; không cần cache trong tiến trình.

**Đuôi P95 là GC của Python, không phải cơ sở dữ liệu** (`q1gc`). Cùng 300 request cache nóng của người nặng, mỗi lần GC
đo bằng `gc.callbacks`: 16 lần thu gom thế hệ 2, mỗi lần 241 ms p50 (264 ms tối đa), đúng cỡ đuôi; người thường không gây
lần nào. Sau `gc.collect(); gc.freeze()` khi app đã khởi động (heap lúc khởi động ra khỏi bộ thu gom): P95 238,96 → 29,52
ms, P99 276,43 → 33,10 ms, mỗi lần thế hệ 2 còn 0,74 ms p50. Khứ hồi của `effective_grants` nặng cũng thế (p99 257 ms khi
thực thi p99 12 ms): 1.358 dòng giải mã thành đối tượng Python là thứ kích hoạt thu gom.

**Câu dựng AccessContext đắt gấp 3-10 lần `effective_grants`** (`_HELD` 28 ms p50 so với 6,7 ms với người nặng; 10 ms so
với 0,9 ms với người thường): `platform.scopes_in` được gọi trong danh sách SELECT (`ARRAY(SELECT platform.scopes_in(...))`),
nên hàm SQL trả tập không được inline và chạy như một hàm riêng với kế hoạch chung (một `EXPLAIN` riêng: 30 ms với người
thường). Gọi nó trong FROM, hay chiếu scope từ chính các grant câu đã đọc, bỏ được phần này (đề xuất, chưa đo).

## Câu 2: gán 1.000 người, sửa vai trò 1.000 người giữ

Mỗi lần ghi là một giao dịch `dw_app` như service ghi: `app.tenant_id`, `app.user_id` = chủ sở hữu 1 (người xác nhận), và
mỗi thay đổi mở rộng đi qua đề xuất `platform.role_change_requests` của chủ sở hữu 2 (gieo sẵn), xác nhận trong chính giao
dịch (`UPDATE ... confirmed`, `app.role_change_id`) rồi mới ghi, như `SqlRoleAdminRepository.confirm` (không có lần hỏi
trước của service). Một đề xuất `assignment_grant` khớp đúng một membership, nên 1.000 người là 1.000 đề xuất, 1.000 cặp
`UPDATE` + `INSERT` trong một giao dịch. Thời gian từng trigger lấy từ `pg_stat_xact_user_functions` trước commit.

| Lần ghi (một giao dịch)                                      | Thời gian (ms) | Trigger tốn nhất (tổng ms trong giao dịch)                                                                                                   |
| ------------------------------------------------------------ | -------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Gán 1.000 người, không gì chạy cạnh                          | 30.246         | `check_owner_coverage` 17.936 (1.000 lần), `rbac_guard` 4.061, `role_is_critical` 1.594, tách nhiệm 1.205, `guard_role_change_request` 1.064 |
| Gán 1.000 người, hai làn `/me` cạnh                          | 58.594         | như trên (18.867, 4.406, ...); phần thêm là event loop chung với hai làn `/me`                                                               |
| Gán 1.000 người, hai làn `/me`, `gc.freeze()`                | 44.867         | như trên                                                                                                                                     |
| Thêm 1 khóa vào vai trò 1.000 người giữ                      | 1.966          | tách nhiệm 993 (1.000 × `sod_violation`), `rbac_guard` 627 (1.000 × `holder_covers_grant`)                                                   |
| Thêm 10 khóa, 10 lệnh (như `_set_privileges`)                | 15.059         | tách nhiệm 7.411 (10.000 × `sod_violation`), `rbac_guard` 6.483 (10.000 × `holder_covers_grant`)                                             |
| Thêm 10 khóa, 1 lệnh, trigger theo dòng (head)               | 16.088         | tách nhiệm 8.314, `rbac_guard` 7.181                                                                                                         |
| Thêm 10 khóa, 1 lệnh, tách nhiệm theo câu lệnh (nguyên mẫu)  | 8.301          | `rbac_guard` 6.903, tách nhiệm 734 (1.000 × `sod_violation`)                                                                                 |
| Thêm 10 khóa, 10 lệnh, tách nhiệm theo câu lệnh (nguyên mẫu) | 16.830         | tách nhiệm 7.986, `rbac_guard` 7.865                                                                                                         |
| Bỏ 10 khóa (thu hẹp, không đề xuất; bốn lần)                 | 6.963-9.486    | `rbac_guard` 6.598-9.033 (10.000 × `holder_covers_grant`)                                                                                    |
| Thêm 5 quyền object                                          | 5.118          | `rbac_guard` 4.511 (5.000 × `holder_covers_grant`)                                                                                           |

Mỗi lần gán trong bulk một mình: p50 27,9 ms, p95 40,7 ms, p99 61,5 ms; commit 3-17 ms. Nguyên mẫu "theo câu lệnh" thay
trigger tách nhiệm trên `tenant_role_permissions` bằng một trigger `FOR EACH STATEMENT` có bảng chuyển tiếp, xét mỗi người
giữ một lần cho cả lệnh, trong database đo, rồi dựng lại trigger của head.

**Ai trả giá.** Một lần sửa vai trò trả theo (số dòng quyền × số lần gán của vai trò): `rbac_refusals` (op `add`,
`remove`) xét luật giữ quyền với từng lần gán của vai trò (1.000 lần `holder_covers_grant`, 0,65 ms mỗi lần, trong khi
1.000 lần gán ấy chỉ ở 200 workspace và người làm giữ khóa ở mức `tenant`), và trigger tách nhiệm xét lại cả 1.000 người
giữ cho mỗi dòng (1.000 lần `sod_held_keys`, kể cả khi khóa thêm vào không thuộc luật nào). Một lần gán trả
`check_owner_coverage` (18 ms mỗi lệnh ở 5.000 thành viên: `checker_candidates` dựng `effective_grants` của mọi thành
viên cho hai khóa) ở mỗi lệnh trên `role_assignments`, `tenant_role_permissions`, `tenant_roles`, `tenant_members`: 59%
thời gian của lần gán 1.000 người.

**Khóa giữ.** `pg_locks` của giao dịch ghi, đọc 0,5 giây sau lệnh ghi đầu: 95-137 khóa, đều `granted`: `RowExclusiveLock`
trên các bảng nó ghi (`role_assignments` hay `tenant_role_permissions`, `role_change_requests`, `tenant_access_versions`,
`tenants`, `studio.principal_scopes` hay `studio.access_epochs`, `outbox_events`), `AccessShareLock`/`RowShareLock` trên
bảng và index nó đọc, một khóa tư vấn theo người (M4 của tenant-rbac/02) với lần gán. Không khóa bảng nào chặn `/me` (đọc
MVCC). Khóa dòng thì có: lệnh ghi đầu khóa dòng `tenant_access_versions` của công ty (trigger tăng version, chạy cuối
chuỗi trigger của dòng) tới commit; thử `FOR UPDATE NOWAIT` trên dòng đó bị từ chối, trên dòng `tenants` và
`studio.access_epochs` thì không. Một phiên khác ghi một bảng tăng version của **cùng công ty** (ở đây
`UPDATE platform.tenants SET name = name`) chờ cả giao dịch: 30.141 ms sau lần gán một mình, 58.213 ms sau lần gán có
làn `/me`, 13.311 ms sau "thêm 10 khóa, 10 lệnh"; `pg_locks` thấy nó chờ `transactionid ShareLock`. Cùng lệnh trên **công
ty khác** xong trong 107-201 ms. Một lần gán hàng loạt hay sửa vai trò lớn vì thế chặn mọi lần ghi quyền khác của công ty
đó (mời, gán, sửa vai trò, đổi trạng thái thành viên, khóa công ty) tới commit, không chặn công ty khác, không chặn đọc.

`/me` của người nặng chạy liên tục cạnh mỗi lần ghi, một làn qua app có Valkey, một làn qua app không cache (ms):

| Lần ghi                        | Nóng: n, p50 / p95 / p99     | Không cache: n, p50 / p95 / p99 |
| ------------------------------ | ---------------------------- | ------------------------------- |
| Gán 1.000 người                | 1.259, 29,2 / 261,6 / 290,6  | 413, 94,0 / 340,4 / 369,4       |
| Gán 1.000 người, `gc.freeze()` | 1.290, 33,3 / 50,9 / 62,7    | 407, 106,2 / 142,9 / 166,4      |
| Thêm 1 khóa                    | 60, 26,8 / 271,8 / 306,6     | 18, 92,8 / 365,8 / 365,8        |
| Thêm 10 khóa, 10 lệnh          | 333, 28,0 / 260,7 / 286,4    | 109, 90,6 / 328,0 / 383,5       |
| Thêm 10 khóa, 1 lệnh           | 315, 35,2 / 290,8 / 343,9    | 102, 116,5 / 389,2 / 425,4      |
| Bỏ 10 khóa (bốn lần)           | 162-179, p95 255,9-298,8     | 51-57, p95 357,6-412,0          |
| Thêm 5 quyền object            | 91, 35,7 / **310,8** / 327,3 | 28, 124,7 / 432,9 / 461,6       |

P99 dưới 1 s ở mọi ô (lớn nhất 640 ms, không cache, cạnh một lần bỏ 10 khóa). P95 ≤ 300 ms đạt ở cấu hình có cache lúc
gán hàng loạt (261,6) và **trượt** ở hai chỗ: cạnh lần thêm 5 quyền object, cache nóng P95 310,8 ms (n = 91); và mọi ô
không cache (328-433 ms; cấu hình không triển khai, compose đặt `REDIS_URL`). Nguyên nhân đo được ở cả hai là GC thế hệ 2
(khoảng 240 ms mỗi lần, Câu 1) trong một tiến trình chung với harness, app thứ hai và lần ghi: với `gc.freeze()`, cùng lần
gán 1.000 người cho P95 50,9 ms (cache) và 142,9 ms (không cache). Phần cơ sở dữ liệu: đọc version 0,12 ms p95; dựng lại
khi trượt cache 21-28 ms p50 với hai người lớn.

## Câu 3: `FOR SHARE` và cuộc đua thu hồi trong lúc gán

Hai phiên `dw_app`, mỗi phiên một kết nối giữ suốt 200 lượt; mỗi lượt theo một lịch: lượt chẵn để bên gán lấy khóa trước
và giữ giao dịch mở 150-300 ms trong khi bên thu hồi tới sau 80-200 ms; lượt lẻ ngược lại (bên thu hồi giữ 100-250 ms,
bên gán tới sau 20-60 ms); trong mỗi khoảng thời điểm là ngẫu nhiên (seed cố định).

- **a. Miễn trừ tách nhiệm** (`platform.sod_violation`, khóa `FOR SHARE` miễn trừ đang mở; cuộc đua của `f381f1694395`).
  Người giữ vế trái của luật miễn trừ được; bên gán xác nhận đề xuất gán vế phải (trigger AFTER xét tách nhiệm), bên thu
  hồi `UPDATE platform.sod_waivers SET revoked_at` (trigger `refuse_revoking_a_waiver_in_use` đếm người đang dựa vào).
  Lọt: sau lượt, người đó giữ cả hai vế mà không có miễn trừ mở nào.
- **b. Quyền của người gán** (`platform.rbac_refusals`, khóa `FOR SHARE OF a` các lần gán của người làm; tenant-rbac/03).
  Người gán giữ `platform.roles.bind` qua đúng một lần gán; bên gán xác nhận đề xuất gán một vai trò không trọng yếu cho
  người khác, bên thu hồi (chủ sở hữu) xóa lần gán cho quyền `bind` đó. Lọt: cả hai commit và lần thu hồi commit xong
  trước khi bên gán gửi COMMIT, tức lần gán được xét theo một quyền đã bị thu hồi lúc nó có hiệu lực.

| Cuộc đua               | Head (200 lượt)                                                                                                                                    | Bỏ `FOR SHARE` (200 lượt)                                      |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| a. Miễn trừ tách nhiệm | **0 lọt**. Gán trước: 100/100 thu hồi bị từ chối (`ck_sod_waivers_not_in_use`). Thu hồi trước: 100/100 gán bị từ chối (`ck_roles_sod_memberships`) | **196 lọt**: 96/100 lượt gán trước, 100/100 lượt thu hồi trước |
| b. Quyền của người gán | **0 lọt**. Gán trước: 100/100 cả hai commit, gán trước thu hồi. Thu hồi trước: 100/100 gán bị từ chối (`rbac_escalation`)                          | **99 lọt**: 99/100 lượt thu hồi trước; 0/100 lượt gán trước    |

Phép đột biến làm **trong database đo, không trong tệp nào của repo**: lấy `pg_get_functiondef` của hàm, thay đúng một lần
`FOR SHARE;` (a) hay `FOR SHARE OF a;` (b) bằng `;` (đếm đúng một lần trước khi thay), `CREATE OR REPLACE` dưới
`dw_migrator`, kiểm `md5(prosrc)` đã đổi (a: `57ac3bd9…` → `48feda15…`; b: `166f4cb2…` → `b72c6f9f…`), chạy 200 lượt,
rồi tạo lại định nghĩa đã lưu và kiểm `md5` trùng bản gốc (failure-modes #3: phép đột biến không đổi gì thì không chứng
minh gì). Hai test đỏ được.

Vì sao b không lọt ở lượt "gán trước" ngay cả khi bỏ `FOR SHARE`: lệnh gán, ở trigger cuối của dòng, khóa dòng version
của công ty tới commit, nên lệnh xóa của bên thu hồi chờ ở đó và commit sau. Khóa ấy chỉ đến **sau** các trigger BEFORE đã
xét, nên ở lượt "thu hồi trước" nó không cứu gì (99/100 lọt): `FOR SHARE` là thứ duy nhất làm bên gán đọc lại sau khi bên
thu hồi commit. Cuộc đua a đi qua `sod_waivers`, không tăng version, nên lọt ở cả hai lịch.

## Câu 4: `session_user` qua pool asyncpg của API

1.000 lần mượn kết nối từ `container.engine` (pool `dw_app` 10 + 20 của API) và 1.000 lần từ
`container.provisioner_engine` (pool `dw_provisioner`), 25 lần song song mỗi đợt. Mỗi lần thứ năm làm một việc: không gì;
`SET LOCAL ROLE <vai đăng nhập>` trong giao dịch; `SET LOCAL ROLE dw_migrator`; `SET SESSION AUTHORIZATION dw_migrator`;
`SET ROLE <vai đăng nhập>` ở mức phiên rồi trả kết nối về pool (để lại cho người mượn sau). Rồi đọc `session_user`,
`current_user` và `fog38.whoami()`, một hàm SECURITY DEFINER của `dw_migrator` trả `session_user`, `current_user` như một
trigger SECURITY DEFINER thấy.

| Pool             | `session_user` = vai đăng nhập | Trong hàm SECURITY DEFINER                                                    | Bị từ chối                                                                                                  |
| ---------------- | ------------------------------ | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `dw_app`         | 1.000/1.000                    | `session_user` = `dw_app` 1.000/1.000; `current_user` = `dw_migrator`         | `SET LOCAL ROLE dw_migrator` 200/200 ("permission denied to set role"), `SET SESSION AUTHORIZATION` 200/200 |
| `dw_provisioner` | 1.000/1.000                    | `session_user` = `dw_provisioner` 1.000/1.000; `current_user` = `dw_migrator` | như trên, 200/200 mỗi loại                                                                                  |

`dw_app` không là thành viên vai nào (`pg_auth_members` chỉ có `dw_monitor`), nên `SET ROLE` chỉ đặt được chính nó; và
`SET ROLE` chỉ đổi `current_user`: một phiên siêu người dùng `dw_admin` đặt `SET ROLE dw_migrator` rồi ghi
`tenant_role_object_privileges` vẫn bị `rbac_guard` từ chối (`rbac_actor_missing`), vì `session_user` vẫn là `dw_admin`.
Trong hàm SECURITY DEFINER `current_user` là chủ hàm (`dw_migrator`), nên phép miễn trừ đọc `current_user` sẽ miễn trừ mọi
người gọi; trigger đọc `session_user`, đúng chỗ.

## Quyết định các phép đo này chốt

1. **Version trong khóa cache, không NOTIFY.** Đọc version mỗi request tốn 0,12 ms p95 phía máy chủ, 2,1 ms p95 khứ hồi;
   một lần trượt cache dựng lại 21-28 ms p50 với người lớn. Phương án dự phòng của ADR-0104 Open 6 (xóa cache bằng
   NOTIFY thay vì đọc version) tiết kiệm nhiều nhất một vòng khứ hồi mỗi request và thêm một kênh có thể mất tin; không
   dùng. Cache ở Valkey như hiện có: 1,1 KB mỗi người thường, 110-131 KB mỗi người nặng hay chủ sở hữu.
2. **Trigger theo dòng giữ nguyên.** Tách nhiệm theo câu lệnh chỉ nhanh hơn (16,1 → 8,3 giây cho 10 khóa) khi cả lần sửa
   là một lệnh nhiều dòng, mà `_set_privileges` ghi mỗi khóa một lệnh (16,8 giây, không lợi gì); nửa còn lại là luật giữ
   quyền theo dòng của `rbac_guard`, không đổi theo dạng trigger. Thứ đáng sửa là việc mỗi dòng làm (mục Phát hiện).
3. **`FOR SHARE` đủ trên PostgreSQL 16**, ở cả hai chỗ: 0/400 lần lọt ở head, 196/200 và 99/200 khi bỏ nó. Không cần
   khóa khác (khóa tư vấn, SERIALIZABLE).
4. **Giữ miễn trừ theo `session_user`** trong `rbac_guard` và `guard_role_change_request`: 2.000/2.000 lần qua hai pool
   asyncpg của API là vai đăng nhập. Điều kiện để nó còn đúng: không ứng dụng nào đăng nhập bằng `dw_migrator` hay
   `dw_provisioner`, không vai ứng dụng nào là thành viên của hai vai đó, và một bộ gộp kết nối (PgBouncer) nếu có thì
   đăng nhập phía máy chủ bằng đúng vai của pool phía khách (`session_user` là vai đăng nhập của kết nối máy chủ).

## Phát hiện cho các ticket đã dựng

Mỗi mục là đề xuất, chưa đo sau khi sửa; người điều phối mở ticket theo dõi. Ngày 5/11/2026: mục 1 và 5 đã sửa và đo lại
ở tenant-rbac/07 (mục ngay dưới); mục 2-4 là tenant-rbac/08 (`needs-triage`), cần migration.

1. **`gc.freeze()` khi API khởi động** (apps/api `main.py` lifespan): đuôi P95 của `/me` với người nặng 237 → 30 ms, lần gán
   1.000 người 261,6 → 50,9 ms. Là nguyên nhân của mọi lần trượt P95 ở đây.
2. **`check_owner_coverage` một lần mỗi giao dịch, không mỗi lệnh** (tenant-rbac/02 bước 17): 18 ms mỗi lệnh ở 5.000
   thành viên, 59% của lần gán 1.000 người; một trigger ràng buộc hoãn tới commit (như `trg_z_bump_access_version_access_mode`
   của field-security/01) chạy nó một lần.
3. **Luật giữ quyền theo neo, không theo lần gán** (`platform.rbac_refusals`, op `add`/`remove`/`role_delete`): xét
   `DISTINCT a.workspace_id` của vai trò (≤ 200) thay vì từng lần gán (1.000), và một lần khi người làm giữ khóa ở mức
   `tenant`. Hiện 0,65 ms × 1.000 cho mỗi dòng quyền.
4. **Tách nhiệm bỏ qua khóa không thuộc luật nào** (`platform.enforce_role_separation_of_duties` trên
   `tenant_role_permissions`): hiện xét lại 1.000 người giữ cho mỗi khóa thêm vào (993 ms), kể cả khi khóa ấy không ở
   `left_scopes`/`right_scopes` của luật nào.
5. **`_HELD` gọi `scopes_in` trong FROM** (`membership_lookup.py`): hàm trả tập trong danh sách SELECT không được inline;
   câu dựng AccessContext 28 ms p50 với người nặng so với 6,7 ms của `effective_grants`.
6. Một lần ghi quyền lớn khóa dòng version của công ty tới commit: mọi lần ghi quyền khác của công ty đó chờ (30 giây với
   lần gán 1.000 người một mình). Không chặn đọc, không chặn công ty khác. Ghi lại, không sửa: là giá của việc version do
   cơ sở dữ liệu tăng trong cùng giao dịch (ADR-0104 quyết định 7).

## Đo lại sau tenant-rbac/07: `gc.freeze()` khi API khởi động, `scopes_in` trong FROM

Ticket: [`tenant-rbac/07`](../../../.claude/plans/studio/tenant-rbac/issues/07-gc-freeze-va-scopes-in-trong-from.md). Đo
ngày 5/11/2026, cùng máy và cấu hình như trên, `setup q1 q1gc q2` rồi `drop` (`DW_TEST_DB_SUFFIX=_fog38`, 0 dòng danh mục
thử còn lại, database đã xóa sau mỗi lần). **Trước** là `git archive` của `125f2fe` (commit gốc của ticket), **sau** là
`git archive` của `953d072` cộng các tệp của ticket, cả hai chạy từ bản xuất sạch, không từ cây làm việc chung với làn
build 1. Lần "trước" chạy cùng lúc với việc khác của làn này (gate, `check_plans.py`), lần "sau" thì không, nên phần cơ sở
dữ liệu chênh theo máy: `effective_grants` của người nặng, không đổi ở ticket này, thực thi p50 7,7 ms ở lần trước và 5,6
ms ở lần sau. Phép so sánh hai dạng câu dựng AccessContext vì thế đo riêng, cùng một lần, trên cùng database (dưới).

**Câu dựng AccessContext, hai dạng cùng một lần** (500 lần `EXPLAIN (ANALYZE)` mỗi dạng sau 20 lần làm nóng, `dw_app`,
database của lần "trước" sau `q2`): cả 5.009 membership của công ty cho cùng `scopes`, `role_keys` và `grants` ở hai dạng,
và `scopes` bằng đúng `platform.scopes_in` (0 lệch).

| Câu                               | Người      | `scopes_in` trong SELECT p50 / p95 / p99 (ms) | `scopes_in` trong FROM p50 / p95 / p99 (ms) |
| --------------------------------- | ---------- | --------------------------------------------- | ------------------------------------------- |
| `_HELD` (dựng AccessContext)      | Nặng       | 25,16 / 33,91 / 44,97                         | 19,34 / 27,65 / 39,09                       |
| `_HELD`                           | Chủ sở hữu | 21,55 / 29,74 / 41,46                         | 12,36 / 17,95 / 21,77                       |
| `_HELD`                           | Thường     | 10,36 / 14,39 / 17,64                         | 3,04 / 4,31 / 5,57                          |
| `_SCOPES_IN` (`effective_scopes`) | Nặng       | 14,07 / 20,09 / 25,09                         | 7,56 / 12,19 / 14,68                        |
| `_SCOPES_IN`                      | Chủ sở hữu | 12,50 / 16,71 / 21,77                         | 3,68 / 5,03 / 6,22                          |
| `_SCOPES_IN`                      | Thường     | 8,34 / 10,80 / 12,96                          | 1,65 / 2,59 / 3,17                          |

Kế hoạch (`EXPLAIN (ANALYZE, VERBOSE)`, người nặng): dạng cũ có `InitPlan 1 -> ProjectSet` với
`Output: platform.scopes_in(...)`, một lời gọi hàm kín 23,8-26,0 ms cho 318 dòng; dạng mới không còn nút nào gọi
`platform.scopes_in`, hàm được inline thành `Unique` trên các grant đã khai triển (5,2-5,3 ms). Thực thi 47,5 → 17,8 ms ở
lần chụp đó, lập kế hoạch 8,3 → 10,6 ms (kế hoạch inline dài hơn: 280 → 529 dòng). Phần còn lại của người nặng là hai lần
`effective_grants` (một trong phép chiếu, một cho cột `grants`); gộp hai lần đó là một bản thứ hai của luật chiếu nên không
làm (ticket 07, bước 3).

**`GET /api/v1/me`, 300 request mỗi ô** (ms; app thật, Valkey; "sau" có `gc.freeze()` trong lifespan):

| Người      | Ô                     | Trước p50 / p95 / p99    | Sau p50 / p95 / p99 |
| ---------- | --------------------- | ------------------------ | ------------------- |
| Nặng       | Cache nóng            | 23,5 / 249,6 / 272,0     | 18,3 / 28,5 / 34,5  |
| Nặng       | Ngay sau tăng version | 82,2 / **314,8** / 346,6 | 54,5 / 74,7 / 88,0  |
| Nặng       | Không cache           | 82,2 / **318,8** / 384,3 | 50,3 / 65,8 / 78,2  |
| Chủ sở hữu | Cache nóng            | 25,6 / 63,5 / 304,2      | 20,3 / 30,4 / 40,9  |
| Chủ sở hữu | Ngay sau tăng version | 92,4 / **331,2** / 411,0 | 50,1 / 66,6 / 84,3  |
| Chủ sở hữu | Không cache           | 71,4 / 154,7 / 350,9     | 44,3 / 57,9 / 72,2  |
| Thường     | Cache nóng            | 13,0 / 16,0 / 18,3       | 9,1 / 11,8 / 13,3   |
| Thường     | Ngay sau tăng version | 49,2 / 78,0 / 124,3      | 25,5 / 36,5 / 48,1  |
| Thường     | Không cache           | 38,4 / 49,6 / 67,1       | 21,8 / 29,5 / 33,7  |

`q1gc` sau: pha "default" giờ đã đóng băng bởi lifespan (không còn là heap mặc định của Python), người nặng P95 26,2 ms với
29 lần thu gom thế hệ 2, mỗi lần 6,93 ms p50 (trước: 16 lần, 257,2 ms mỗi lần, P95 265,7); pha "frozen" của harness thêm
`gc.collect(); gc.freeze()` trên cả heap của harness: P95 22,8 ms, 0,64 ms mỗi lần.

**`/me` của người nặng cạnh mỗi lần ghi của `q2`** (ms, p50 / p95 / p99; n trước → sau):

| Lần ghi                                | Nóng trước               | Nóng sau           | Không cache trước         | Không cache sau      |
| -------------------------------------- | ------------------------ | ------------------ | ------------------------- | -------------------- |
| Gán 1.000 người (n 1.351 → 1.317)      | 39,5 / **314,4** / 360,6 | 27,3 / 52,7 / 69,4 | 130,8 / **420,5** / 457,6 | 83,4 / 119,0 / 140,1 |
| Thêm 1 khóa                            | 38,2 / **331,4** / 346,8 | 28,7 / 60,5 / 74,3 | 124,4 / **431,6** / 431,6 | 89,0 / 127,3 / 142,2 |
| Thêm 10 khóa, 10 lệnh                  | 40,4 / **315,8** / 359,4 | 27,0 / 51,6 / 68,9 | 129,3 / **460,8** / 485,7 | 82,3 / 117,5 / 145,7 |
| Thêm 10 khóa, 1 lệnh                   | 40,7 / **337,8** / 365,3 | 27,6 / 55,4 / 68,4 | 133,4 / **447,4** / 462,2 | 83,8 / 121,5 / 168,2 |
| Bỏ 10 khóa (bốn lần)                   | p95 293,7-**336,4**      | p95 53,0-67,2      | p95 **434,2-455,5**       | p95 111,2-135,2      |
| Thêm 10 khóa, tách nhiệm theo câu lệnh | p95 **307,6-342,1**      | p95 55,9-58,2      | p95 **411,6-491,9**       | p95 117,4-121,4      |
| Thêm 5 quyền object                    | 37,9 / **303,7** / 468,6 | 27,4 / 53,2 / 79,3 | 123,6 / **471,6** / 517,5 | 83,0 / 122,6 / 140,1 |
| Gán 1.000 người, harness `gc.freeze()` | 44,7 / 70,0 / 101,0      | 25,9 / 40,9 / 50,1 | 145,6 / 213,4 / 266,9     | 77,0 / 97,7 / 126,0  |

Sau ticket, mọi ô `/me` của `q1` và `q2` đạt P95 ≤ 300 ms và P99 ≤ 1 s (lớn nhất P95 135,2 ms, P99 283,9 ms, không cache
cạnh một lần bỏ 10 khóa); trước ticket, trong lần đo này, 23 trên 33 ô trượt P95 (in đậm; P99 dưới 1 s ở cả hai lần). Lần ghi cũng ngắn lại, vì `/me` chạy
chung event loop với lần ghi: gán 1.000 người cạnh `/me` 80,9 → 40,5 giây, một mình 34,0 → 26,1 giây (phần một mình là cơ
sở dữ liệu và độ nhiễu của máy; ticket 08 nhắm vào nó).

**Worker** (cùng cách: một tiến trình dựng `build_registry`, rồi bảy lần `gc.collect()`, trung vị): API sau khi dựng
container và app giữ 419.529 đối tượng được theo dõi, một lần thu gom đầy đủ 213,1 ms (tối đa 315,1), 0,0 ms sau
`gc.freeze()`; worker 209.435 đối tượng, 101,4 ms (tối đa 106,0), 0,0 ms sau `gc.freeze()`. Worker không phục vụ request
nào có ngân sách độ trễ, nên ticket này không sửa nó (lý do ở Comments của ticket 07).

## Đo `_STANDING` và `_HOLDERS` (tenant-rbac/10): `scopes_in` trong FROM

Ticket: [`tenant-rbac/10`](../../../.claude/plans/studio/tenant-rbac/issues/10-scopes-in-cua-standing-va-holders.md). Đo
ngày 5/11/2026, cùng máy và cấu hình như trên (Python 3.12.15 của venv bản xuất; `SELECT 1` p50 0,94 ms), câu hỏi mới
`q5` của harness: `setup` một lần, `q5` trước, `q5` sau, rồi `drop` (`DW_TEST_DB_SUFFIX=_fog38`, 0 dòng danh mục thử còn
lại, database đã xóa). **Trước** chạy từ `git archive` của `d0faf4c` cộng harness mới, **sau** từ `git archive` của
`87996f5` (commit sửa) cộng harness, cả hai trên cùng database gieo một lần. Mỗi lần ba dạng mỗi câu, xen kẽ trong cùng
vòng lặp: mốc danh sách SELECT (câu ở `657ef4c6` chép nguyên văn vào harness, cố định), dạng FROM viết trong harness
(`ARRAY(SELECT s.key FROM platform.scopes_in(...) AS s(key))`, cùng ba tham số) và câu nhập từ module. Đo dưới `dw_app`
gắn `app.tenant_id` và `app.workspace_id` như `tenant_session`; mỗi dạng 20 lần làm nóng rồi 200 vòng đi về và 200 lần
`EXPLAIN (ANALYZE)`. Vòng đi về là đường của app (asyncpg qua SQLAlchemy, cùng cache câu lệnh chuẩn bị mặc định);
`EXPLAIN` lập kế hoạch lại mỗi lần, nên cột lập kế hoạch là chi phí của lần chạy đầu trên một kết nối, không phải của
mỗi request. Ô một thành viên: người nặng, chủ sở hữu, người thường ở workspace của membership đầu (`people` sai, như
`scopes_of`); ô cả workspace (`people_only` đúng, như `holding`): workspace của người nặng (25 thành viên) và workspace
`q5` gieo dưới `dw_migrator` cho đúng lần đo, 5.000 membership, mỗi membership một lần gán `member`, xóa trong `finally`.

Bằng nhau, cả hai lần: 10.009 membership của công ty (5.009 cùng 5.000 của workspace `q5`), `_STANDING` hai dạng 0 lệch;
201 workspace, `_HOLDERS` cả workspace (người và không) hai dạng 0 lệch.

**Lần trước** (câu của module bằng mốc danh sách SELECT), vòng đi về, ms:

| Câu                       | Ô                    | Dòng  | SELECT p50 / p95 / p99         | FROM p50 / p95 / p99         | Module p50 / p95 / p99         |
| ------------------------- | -------------------- | ----- | ------------------------------ | ---------------------------- | ------------------------------ |
| `_STANDING`               | Nặng                 | 1     | 16,87 / 24,92 / 27,70          | 8,30 / 12,24 / 14,60         | 16,90 / 25,47 / 30,48          |
| `_STANDING`               | Chủ sở hữu           | 1     | 15,75 / 20,31 / 26,23          | 5,83 / 7,72 / 9,11           | 15,58 / 21,13 / 25,66          |
| `_STANDING`               | Thường               | 1     | 10,81 / 14,20 / 19,39          | 3,00 / 4,13 / 5,40           | 10,69 / 14,19 / 22,08          |
| `_HOLDERS` một thành viên | Nặng                 | 1     | 16,61 / 22,96 / 30,64          | 8,09 / 11,77 / 15,11         | 16,54 / 22,43 / 30,17          |
| `_HOLDERS` một thành viên | Chủ sở hữu           | 1     | 15,85 / 22,39 / 27,03          | 5,80 / 8,47 / 10,80          | 15,62 / 20,60 / 24,57          |
| `_HOLDERS` một thành viên | Thường               | 1     | 11,09 / 15,18 / 17,12          | 3,06 / 4,08 / 4,99           | 11,08 / 14,61 / 19,93          |
| `_HOLDERS` cả workspace   | Workspace người nặng | 25    | 47,07 / 81,95 / 96,16          | 13,14 / 21,75 / 27,96        | 46,80 / 79,60 / 94,39          |
| `_HOLDERS` cả workspace   | Workspace `q5`       | 5.000 | 5.048,70 / 6.397,25 / 6.989,83 | 741,73 / 1.100,08 / 1.426,35 | 5.008,03 / 6.358,04 / 6.932,35 |

Thời gian thực thi (`EXPLAIN (ANALYZE)`), ms, cùng lần; lập kế hoạch p50 của dạng SELECT 0,22-0,56 ms, của dạng FROM
5,64-7,09 ms:

| Câu                       | Ô                    | SELECT p50 / p95 / p99         | FROM p50 / p95 / p99         | Module p50 / p95 / p99         |
| ------------------------- | -------------------- | ------------------------------ | ---------------------------- | ------------------------------ |
| `_STANDING`               | Nặng                 | 14,61 / 20,87 / 26,66          | 7,83 / 11,75 / 13,57         | 14,63 / 21,45 / 23,64          |
| `_STANDING`               | Chủ sở hữu           | 12,98 / 18,51 / 21,58          | 4,28 / 6,66 / 8,30           | 13,06 / 19,24 / 22,62          |
| `_STANDING`               | Thường               | 10,33 / 14,89 / 16,70          | 1,76 / 2,81 / 3,25           | 10,53 / 15,97 / 18,20          |
| `_HOLDERS` một thành viên | Nặng                 | 14,70 / 20,86 / 24,96          | 7,63 / 11,16 / 12,89         | 14,73 / 20,24 / 21,23          |
| `_HOLDERS` một thành viên | Chủ sở hữu           | 13,44 / 19,88 / 22,93          | 4,23 / 6,67 / 8,32           | 13,68 / 21,22 / 25,46          |
| `_HOLDERS` một thành viên | Thường               | 9,48 / 14,09 / 16,11           | 1,52 / 2,17 / 3,14           | 9,60 / 14,63 / 18,00           |
| `_HOLDERS` cả workspace   | Workspace người nặng | 50,55 / 134,97 / 157,53        | 14,96 / 41,68 / 56,54        | 49,43 / 119,07 / 145,30        |
| `_HOLDERS` cả workspace   | Workspace `q5`       | 4.939,51 / 6.070,29 / 7.150,27 | 981,48 / 1.212,37 / 1.409,37 | 4.978,82 / 6.379,53 / 6.612,90 |

Kế hoạch (`EXPLAIN (ANALYZE, VERBOSE)`, người nặng): dạng SELECT của cả hai câu có `ProjectSet` với
`Output: platform.scopes_in(...)`, một lời gọi hàm kín 13,9-14,7 ms cho 318 dòng (`_STANDING` thực thi 15,5 ms, lập kế
hoạch 0,37 ms, 35 dòng kế hoạch); dạng FROM không còn nút `ProjectSet` hay `Function Scan` nào gọi `platform.scopes_in`,
hàm được inline (`_STANDING` 7,1 ms, lập kế hoạch 5,5 ms, 284 dòng; `_HOLDERS` một thành viên 13,2 → 7,0 ms, 23 → 272
dòng; cả workspace người nặng 34,8 → 12,0 ms).

**Quyết định** (ngưỡng của ticket: (a) P50 vòng đi về của FROM thấp hơn SELECT ít nhất 20% và 1 ms ở ít nhất một ô một
thành viên; (b) không ô nào của câu có P95 vòng đi về của FROM tệ hơn quá 20%): **chuyển cả hai câu**. `_STANDING` giảm
50,8-72,2% và 7,81-9,92 ms P50 ở cả ba ô; `_HOLDERS` một thành viên 51,3-72,4% và 8,03-10,05 ms; P95 của FROM bằng
0,27-0,51 lần mốc ở mọi ô, cả workspace 0,27 (25 người) và 0,17 (5.000 người).

**Lần sau** (câu của module nay là dạng FROM), vòng đi về, ms:

| Câu                       | Ô                    | Dòng  | SELECT p50 / p95 / p99         | FROM p50 / p95 / p99       | Module p50 / p95 / p99     |
| ------------------------- | -------------------- | ----- | ------------------------------ | -------------------------- | -------------------------- |
| `_STANDING`               | Nặng                 | 1     | 14,77 / 18,75 / 26,86          | 7,06 / 9,26 / 11,09        | 6,96 / 10,05 / 11,00       |
| `_STANDING`               | Chủ sở hữu           | 1     | 14,56 / 19,11 / 25,00          | 5,26 / 7,05 / 9,31         | 5,25 / 7,05 / 7,84         |
| `_STANDING`               | Thường               | 1     | 9,13 / 11,60 / 15,42           | 2,33 / 3,28 / 4,56         | 2,28 / 3,08 / 4,05         |
| `_HOLDERS` một thành viên | Nặng                 | 1     | 14,95 / 19,16 / 21,13          | 6,98 / 9,23 / 10,67        | 6,92 / 9,48 / 11,09        |
| `_HOLDERS` một thành viên | Chủ sở hữu           | 1     | 14,72 / 20,34 / 26,30          | 5,12 / 7,32 / 9,50         | 5,10 / 7,24 / 7,99         |
| `_HOLDERS` một thành viên | Thường               | 1     | 9,38 / 13,12 / 18,99           | 2,32 / 3,62 / 5,49         | 2,30 / 3,20 / 4,17         |
| `_HOLDERS` cả workspace   | Workspace người nặng | 25    | 35,16 / 50,28 / 59,85          | 9,95 / 15,08 / 17,84       | 9,94 / 14,16 / 16,12       |
| `_HOLDERS` cả workspace   | Workspace `q5`       | 5.000 | 4.771,98 / 5.419,64 / 6.027,04 | 679,59 / 958,69 / 1.022,43 | 677,52 / 965,97 / 1.098,29 |

Thời gian thực thi của câu module sau sửa, p50 / p95 / p99 (ms): `_STANDING` nặng 6,83 / 8,76 / 13,21, chủ sở hữu 3,77 /
5,46 / 6,93, thường 1,36 / 1,91 / 2,17; `_HOLDERS` một thành viên 7,30 / 11,51 / 14,53, 3,83 / 5,51 / 6,33, 1,20 / 1,60 /
1,77; cả workspace 25 người 10,37 / 14,36 / 18,32, 5.000 người 2.059,79 / 2.404,11 / 2.700,10 (dưới `EXPLAIN (ANALYZE)`
dạng inline đắt hơn chính nó ở vòng đi về, 677,5 ms: đồng hồ của 5.000 lần chạy một kế hoạch con nhiều nút; vòng đi về
mới là số của người gọi). Mốc SELECT cùng lần: 13,06, 11,72, 8,38; 13,66, 12,16, 8,30; 34,26, 4.861,72 ms p50. Kế hoạch
của câu module sau sửa, người nặng: không `ProjectSet`, không `Function Scan` gọi `platform.scopes_in`, ở cả `_STANDING`
(284 dòng) và `_HOLDERS` (272 và 273 dòng). Mọi ô: P95 vòng đi về của câu module bằng 0,18-0,54 lần mốc cùng lần, không ô
nào tệ hơn.

Còn lại: `_HOLDERS` cả workspace 5.000 người P95 966 ms sau sửa (6.358 ms trước), trên 300 ms của `latency.md`. Người gọi
duy nhất của `holding` là một lane của worker (`SqlHeldRunAlerts.binding_needs_review` của workflow-engine/04, `c0eca510`),
không phải route; ghi ở đây và ở Comments của ticket 10, không mở ticket (lý do ở đó).

## Chưa đo, và vì sao

- **Máy tham chiếu.** Mọi số là của máy dev ở trên, PostgreSQL của compose không giới hạn và dùng chung với một làn khác.
  Kết quả đúng/sai (câu 3, câu 4) không phụ thuộc máy; số tuyệt đối của câu 1, 2 phải đo lại ở máy pilot (discovery/20).
- **Một tiến trình API riêng.** `/me` đo trong cùng tiến trình với harness; số của một tiến trình uvicorn riêng sẽ thấp hơn,
  không đo.
- **Ngưỡng riêng cho `effective_grants`** do Đạt chốt; ở đây chỉ ghi số.
- **Lần hỏi trước của service** (`rbac_refusals` với `p_lock = false`, `_check_still_true`) và audit của mỗi lần xác nhận
  không nằm trong lần gán đo ở đây: lần gán đi thẳng vào bảng như lệnh ghi cuối của service.
- **Bản sửa của phát hiện 2-4** chưa có (tenant-rbac/08); phát hiện 1 và 5 đo lại ở mục trên.
