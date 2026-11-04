# 08 — Chi phí quyền hiệu lực, access version và trigger chống leo thang quyền ở quy mô thật

Type: prototype
Status: ready-for-agent
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

## Comments

- 2026-11-04 (agent, phân loại G12, theo ủy quyền 31/10/2026): `ready-for-agent`. Chưa câu nào được đo: tenant-rbac/02 (`bd8c607`) dựng hàm và khóa cache, rồi dời số đo FOG-38 trên công ty 5.000 người sang lúc đóng hàng đợi (Comments M11 của ticket đó), và chưa đóng hàng nào đo nó. Không cần người hay máy riêng: đo trên compose của máy này, ghi rõ máy dev.
