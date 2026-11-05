# 08 — Chi phí quyền hiệu lực, access version và trigger chống leo thang quyền ở quy mô thật

Type: prototype
Status: resolved
Area: studio · Viết: 23/10/2026
FOG: FOG-38 `rbac-cost`

## Câu hỏi

1. `platform.effective_grants` và một lần đọc access version mỗi request tốn bao nhiêu, khi một người là thành viên 10
   workspace, giữ 30 vai trò, trên 200 đối tượng; `AccessContext` đã cache nặng bao nhiêu?
2. Trigger chống leo thang quyền và tách nhiệm chạy thế nào khi gán vai trò hàng loạt cho 1.000 người, và khi sửa một
   vai trò có 1.000 người giữ?
3. `FOR SHARE` trong trigger có chặn được cuộc đua thu hồi trong lúc gán trên PostgreSQL 16 không?
4. `session_user` có luôn là vai đăng nhập dưới các pool asyncpg không, để miễn trừ trong trigger là đúng?

## Vì sao

Quyết khóa cache mang access version hay xóa cache bằng NOTIFY, trigger theo dòng hay theo câu lệnh, và miễn trừ trong
trigger có an toàn không. `tenant-rbac/04` nằm trên đường găng và chờ `tenant-rbac/02`.

## Mở khóa

- Spec: `tenant-rbac` (02, 03; 04 trên đường găng).
- ADR: 0104 (Open 6; phương án dự phòng nếu đọc access version mỗi request quá đắt).
- DO: DO-09 (vai trò là dữ liệu), DO-10 (Đạt chốt 23/10/2026: tách nhiệm xét theo người trên cả công ty), DO-32.

## Dựng tối thiểu

Hàm `platform.effective_grants` nguyên mẫu và bảng gán vai trò trên một schema nháp, gieo một công ty theo D12 (5.000
người dùng, 200 workspace) với hồ sơ quyền như câu 1; trigger leo thang và tách nhiệm ở hai dạng (theo dòng, theo câu
lệnh); hai phiên song song cho cuộc đua thu hồi và gán; ứng dụng gọi qua pool asyncpg như API hiện có.

## Phép đo quyết định

| Đo                                                           | Ngưỡng hay so sánh                                         | Quyết định                          |
| ------------------------------------------------------------ | ---------------------------------------------------------- | ----------------------------------- |
| p95 của `effective_grants` và đọc access version mỗi request | Chưa có ngưỡng; ghi p95, so với ngân sách request của YC20 | Version trong khóa cache hay NOTIFY |
| Kích thước `AccessContext`                                   | Ghi byte mỗi người                                         | Cache ở đâu và cỡ bao nhiêu         |
| Gán 1.000 người; sửa vai trò có 1.000 người giữ              | Thời gian và khóa giữ                                      | Trigger theo dòng hay theo câu lệnh |
| Cuộc đua thu hồi và gán                                      | Không bản gán nào lọt sau thu hồi                          | `FOR SHARE` đủ hay cần khóa khác    |
| `session_user` qua pool                                      | Luôn là vai đăng nhập hay không                            | Giữ hay bỏ miễn trừ trong trigger   |

Test cuộc đua phải đỏ khi bỏ `FOR SHARE` (failure-modes #3).

## Nguồn

- Brief B3 (F1-F4); `docs/adr/0104-tenant-roles-with-depth-and-one-effective-grants-owner.md:114` và Open 6.
- [research.md](../research.md) mục 2 (chi phí `platform.effective_grants` mỗi request chưa kiểm).

## Việc của agent (phân loại 4/11/2026)

- Câu hỏi: câu 1-4 trên schema ở head, nơi tenant-rbac/02 (`bd8c607`) đã dựng `platform.effective_grants` và đặt
  access version trong khóa cache; `FOR SHARE` đã dựng là lần khóa miễn trừ tách nhiệm trong
  `platform.sod_violation` (revision `b5677d345bc1`, cuộc đua của `f381f1694395`), còn trigger chống leo thang là
  tenant-rbac/03 (`needs-triage`): câu 3 đo trên chỗ đã dựng và đo lại khi tenant-rbac/03 dựng.
- Cách làm: database riêng trên PostgreSQL 16.15 của compose (`DW_TEST_DB_SUFFIX=_fog38`), `alembic upgrade head`;
  gieo một công ty 5.000 thành viên, 200 workspace, người đo giữ 30 vai trò trên 10 workspace với quyền trên 200 khóa
  đối tượng (dòng `platform.permissions` thử do migrator chèn, xóa khi xong). (1) 1.000 lần `effective_grants` dưới
  `dw_app` (p50/p95/p99, Execution Time); 200 request `GET /api/v1/me` qua app ASGI thật như
  `.claude/rules/latency.md`, cache nóng và ngay sau khi tăng version; byte của `AccessContext` đã tuần tự hóa. (2)
  Gán vai trò cho 1.000 người trong một giao dịch, rồi sửa một vai trò 1.000 người giữ: thời gian, khóa giữ
  (`pg_locks`), và P99 của `GET /api/v1/me` chạy song song. (3) Hai phiên đua thu hồi miễn trừ và gán vai trò, 200
  lượt; rồi đột biến bỏ `FOR SHARE` tại chỗ (sao lưu tệp trước, không `git checkout`). (4) 1.000 lần mượn kết nối từ engine asyncpg
  của API, kể cả sau `SET LOCAL ROLE`, đọc `session_user` và `current_user`.
- Đầu ra: `db/bench/rbac/RESULTS.md` (cùng dạng `db/bench/record-access/RESULTS.md`), tóm vào `## Answer` ở đây,
  Comments của tenant-rbac/02 (mục M11) và mục Open 6 của ADR-0104 (Accepted).
- Đạt khi: 0 lần gán lọt sau thu hồi trên 200 lượt, và đột biến bỏ `FOR SHARE` cho ít nhất một lần lọt (test đỏ
  được); `session_user` là vai đăng nhập ở 1.000/1.000 lần; `GET /api/v1/me` P95 ≤ 300 ms và P99 ≤ 1 s (ngân sách
  tạm của `latency.md`), kể cả lúc gán hàng loạt. Trượt một dòng thì ghi số và nguyên nhân, và đề xuất phương án dự
  phòng của ADR-0104 Open 6; ngưỡng riêng cho `effective_grants` do Đạt chốt, ticket chỉ ghi số.

## Answer

Đo ngày 5/11/2026 trên máy dev (không phải máy tham chiếu), PostgreSQL 16.15 của compose, database riêng
`dw_bench_rbac_fog38` ở head `044859c` (đã xóa sau khi đo, cùng các dòng danh mục thử); số, lệnh và cách chạy lại ở
[`db/bench/rbac/RESULTS.md`](../../../../../db/bench/rbac/RESULTS.md), harness `db/bench/rbac/bench_rbac.py`
(`make bench-rbac`).

- **Câu 1.** `effective_grants` thực thi p50/p95/p99 6,67/9,93/12,18 ms với người 10 workspace, 30 vai trò (1.358 dòng,
  458 khóa, 600 dòng `obj.*`), 2,42/3,43/4,08 với chủ sở hữu (1.255 dòng), 0,92/1,30/1,66 với người thường; đọc access
  version 0,07/0,12/0,16 ms (khứ hồi 2,1 ms p95). `AccessContext` tuần tự hóa: 110 KB người nặng, 131 KB chủ sở hữu, 1,1 KB
  người thường. `GET /api/v1/me` (300 request mỗi ô, app thật, Valkey): cache nóng P95/P99 237,2/264,1 ms (nặng),
  244,0/288,8 (chủ sở hữu), 13,7/15,5 (thường); ngay sau tăng version 266,9/317,3, 275,9/306,7, 47,3/59,5. **Đạt**, P95
  sát ngưỡng: đuôi là GC thế hệ 2 của Python (16 lần, 241 ms mỗi lần); `gc.freeze()` sau khởi động đưa P95 về 29,5 ms.
- **Câu 2.** Gán 1.000 người trong một giao dịch (1.000 đề xuất xác nhận): 30,2 giây một mình (27,9 ms p50 mỗi lần gán),
  59% là `check_owner_coverage` chạy ở mỗi lệnh. Sửa vai trò 1.000 người giữ: thêm 1 khóa 2,0 giây, 10 khóa 15,1 giây, bỏ
  10 khóa 7,0-9,5 giây, 5 quyền object 5,1 giây (luật giữ quyền xét từng lần gán của vai trò, tách nhiệm xét lại từng người
  giữ cho mỗi dòng). Khóa: dòng version của công ty từ lệnh ghi đầu tới commit, nên lần ghi quyền khác của cùng công ty
  chờ cả giao dịch (30,1 giây); công ty khác 0,1-0,2 giây; đọc không chờ. `/me` cạnh lần gán: cache nóng P95/P99
  261,6/290,6 ms **đạt**; **trượt P95** cạnh lần thêm 5 quyền object (310,8 ms, n = 91) và ở mọi ô không cache (328-433
  ms); P99 dưới 1 s mọi ô. Nguyên nhân cả hai là GC (cùng tiến trình với harness): với `gc.freeze()` cùng lần gán cho P95
  50,9 ms (cache) và 142,9 ms (không cache). Phương án dự phòng của Open 6 (NOTIFY thay đọc version) chỉ bỏ được 0,12 ms
  máy chủ, 2,1 ms khứ hồi mỗi request, không chạm nguyên nhân; đề xuất `gc.freeze()` thay nó.
- **Câu 3.** `FOR SHARE` đủ trên PostgreSQL 16: 0/200 lần lọt ở cuộc đua thu hồi miễn trừ với gán (`sod_violation`) và
  0/200 ở cuộc đua thu hồi quyền `bind` của người gán với lần gán (`rbac_refusals`), mỗi cuộc 100 lượt mỗi thứ tự; bỏ
  `FOR SHARE` trong database đo (hàm thay bằng `pg_get_functiondef` sửa đúng một chỗ, `md5` kiểm đổi rồi khôi phục): 196/200
  và 99/200 lần lọt. Test đỏ được.
- **Câu 4.** `session_user` là vai đăng nhập ở 1.000/1.000 lần mượn từ pool `dw_app` của API và 1.000/1.000 từ pool
  `dw_provisioner`, kể cả sau `SET LOCAL ROLE` và trong hàm SECURITY DEFINER (nơi `current_user` là `dw_migrator`);
  `SET ROLE`, `SET SESSION AUTHORIZATION` sang `dw_migrator` bị từ chối 200/200 mỗi loại. Giữ miễn trừ.
- **Quyết định:** version trong khóa cache, không NOTIFY; trigger theo dòng giữ nguyên (tách nhiệm theo câu lệnh chỉ nhanh
  hơn với một lệnh nhiều dòng, 16,1 → 8,3 giây, mà service ghi mỗi khóa một lệnh); `FOR SHARE` đủ; giữ miễn trừ theo
  `session_user`. Ngưỡng riêng cho `effective_grants` vẫn của Đạt.
- **Cần ticket theo dõi** (RESULTS.md, Phát hiện): `gc.freeze()` khi API khởi động; `check_owner_coverage` một lần mỗi
  giao dịch; luật giữ quyền theo neo thay vì theo lần gán; tách nhiệm bỏ qua khóa không thuộc luật nào; `_HELD` gọi
  `scopes_in` trong FROM.

## Comments

- 2026-11-04 (agent, phân loại G12, theo ủy quyền 31/10/2026): `ready-for-agent`. Chưa câu nào được đo: tenant-rbac/02 (`bd8c607`) dựng hàm và khóa cache, rồi dời số đo FOG-38 trên công ty 5.000 người sang lúc đóng hàng đợi (Comments M11 của ticket đó), và chưa đóng hàng nào đo nó. Không cần người hay máy riêng: đo trên compose của máy này, ghi rõ máy dev.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): đo xong, `resolved`. Làm khác "Việc của agent" ở bốn chỗ: (1) `/me` 300
  request mỗi ô thay vì 200, thêm ô "không cache" và `q1gc` (GC đo bằng `gc.callbacks`, rồi `gc.freeze()`), vì đuôi P95
  không đến từ cơ sở dữ liệu; (2) lần gán 1.000 người và lần sửa vai trò ghi thẳng vào bảng dưới `dw_app` với đề xuất xác
  nhận trong chính giao dịch, như lệnh ghi cuối của `SqlRoleAdminRepository.confirm`, không qua lần hỏi trước và audit
  của service; (3) câu 3 đo hai cuộc đua (miễn trừ của `sod_violation` và quyền của người gán trong `rbac_refusals` của
  tenant-rbac/03) trên một công ty 5 người, vì cuộc đua không phụ thuộc cỡ công ty còn mỗi lệnh trên bảng vai trò chạy
  `check_owner_coverage` của cả công ty; (4) phép đột biến bỏ `FOR SHARE` làm trên hàm trong database đo
  (`CREATE OR REPLACE` từ `pg_get_functiondef`, `md5` kiểm đổi rồi khôi phục), không sửa tệp migration nào. Nếu sai thì: chạy lại
  `make bench-rbac` sau khi đổi harness; mọi lựa chọn nằm trong `db/bench/rbac/bench_rbac.py`.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): bốn quyết định ADR-0104 Open 6 chờ, chốt theo số: version trong khóa cache
  (không NOTIFY), trigger theo dòng (không theo câu lệnh), `FOR SHARE` đủ, giữ miễn trừ theo `session_user`. Hai dòng P95
  trượt (cạnh lần thêm 5 quyền object 310,8 ms; mọi ô không cache) ghi đúng số; nguyên nhân đo được là GC của Python, nên
  phương án dự phòng của Open 6 được xét và không chọn (bỏ được 2,1 ms khứ hồi mỗi request, không chạm 240 ms một lần GC);
  đề xuất `gc.freeze()` khi API khởi động. Nếu sai thì: NOTIFY xóa mục cache theo tenant thay cho đọc version, với số đo
  lại sau `gc.freeze()` làm mốc; tách nhiệm theo câu lệnh cùng `_set_privileges` ghi một lệnh nhiều dòng; khóa tư vấn
  theo tenant thay `FOR SHARE`; miễn trừ theo một vai riêng thay `session_user`.
