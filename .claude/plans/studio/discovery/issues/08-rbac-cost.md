# 08 — Chi phí quyền hiệu lực, access version và trigger chống leo thang quyền ở quy mô thật

Type: prototype
Status: needs-triage
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
- DO: DO-09 (vai trò là dữ liệu), DO-10 (agent, tạm: tách nhiệm xét theo người trên cả công ty), DO-32.

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

## Comments
