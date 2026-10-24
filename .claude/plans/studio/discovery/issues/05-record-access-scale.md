# 05 — Quyền trên bản ghi ở quy mô D12: policy sáu nhánh, principal scope và cây workspace

Type: prototype
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-40 `record-access-perf`, FOG-44 `tree-scale`, FOG-43 `search-tenant-filter`

## Câu hỏi

1. Policy sáu nhánh (mặc định toàn công ty, khóa workspace, của tôi, nhóm, cấp dưới, chia sẻ) với khóa tổng hợp theo
   đối tượng có đạt ngân sách ở 10^7 bản ghi, khi một người phụ trách giữ 10^6 bản ghi và mảng cấp dưới dài 5.000
   (FOG-40)?
2. `compute_principal_scope()` tốn bao nhiêu trên công ty 5.000 người dùng và sau khi tăng access epoch; P1 có cần lane
   làm ấm không; compare-and-set của closure có đúng dưới READ COMMITTED không (FOG-40)?
3. Partition pruning và InitPlan có giữ được với partition băm dưới RESTRICTIVE cộng PERMISSIVE không; lợi ích InitPlan
   đã đo ở si-platform `db/si/migrations/0057_record_tenant_policies_initplan.sql` có lặp lại trên PostgreSQL 16 ở đây
   không (FOG-40)?
4. Hàm cây đệ quy và bước dựng closure tốn bao nhiêu ở 1.000 workspace; có bao giờ cần bảng closure không; khách thí
   điểm và khách mục tiêu có bao nhiêu workspace (FOG-44)?
5. Bộ lọc should của Qdrant với hàng trăm tới hàng nghìn giá trị MatchAny ở 10^6 điểm chạy ra sao, và bao lâu một lần
   bước kiểm lại bản ghi để lại ít hơn `top_k` kết quả (FOG-43, phục vụ W2)?

## Vì sao

Quyền trên bản ghi là cược hiệu năng rủi ro nhất của Studio: policy chậm là tính năng không ai dùng được. ADR 0105 chỉ
đóng băng mẫu policy sau khi có số đo. Agent tìm bản ghi phải tôn trọng quyền mà không bị thiếu kết quả.

## Mở khóa

- Spec: `record-access` (01, 02, 03), `foundations-hardening` (03, RLS đọc setting dạng InitPlan),
  `org-and-principals` (hàm cây), `agent-builder` (truy hồi, W2).
- ADR: 0105 (Consequences, Open 6), 0102.
- DO: DO-14 (D12), DO-15, DO-11 (Đạt chốt 23/10/2026). Ticket W1: `record-access/01` (P0) là phép đo này.

## Dựng tối thiểu

Một schema nháp với `studio.records` partition băm theo `tenant_id` (modulus 8), gieo theo D12: 10^7 bản ghi một đối
tượng, 5.000 người dùng, 200 workspace sâu 6 (thêm một lần ở 1.000 workspace cho câu 4); bộ policy RESTRICTIVE tenant
cộng PERMISSIVE sáu nhánh dạng InitPlan; `compute_principal_scope()` nguyên mẫu. Câu 5 dùng một collection Qdrant 10^6
điểm với payload quyền giả lập.

## Phép đo quyết định

| Đo                                                 | Ngưỡng hay so sánh                             | Quyết định                          |
| -------------------------------------------------- | ---------------------------------------------- | ----------------------------------- |
| Trang đầu 50 dòng; một bản ghi; mọi hồ sơ quyền    | YC20: p95 ≤ 50 ms; p95 ≤ 5 ms, đo phía máy chủ | Giữ hay đổi mẫu policy của ADR 0105 |
| Như trên ở 10^6 bản ghi một đối tượng              | p95 ≤ 100 ms (brief B5)                        | Ngưỡng nào vào YC20                 |
| `compute_principal_scope()` lúc nguội và sau epoch | Chưa có ngưỡng; ghi p95 và thời gian dựng lại  | Có lane làm ấm ở P1 không           |
| Hàm cây ở 1.000 workspace                          | So với closure dựng sẵn                        | Có bảng closure không (ADR 0102)    |
| MatchAny ở 10^6 điểm; tỉ lệ thiếu `top_k`          | Ghi p95 và tỉ lệ                               | Cách lọc tìm kiếm ở W2              |

Số đo ghi phiên bản PostgreSQL, máy đo và kế hoạch truy vấn vào ADR 0105.

## Nguồn

- Brief B2, B4, B11; `docs/adr/0105-record-reach-is-decided-by-postgresql.md:118-121` (đo trước khi đóng băng).
- [research.md](../research.md) mục 1 và 2 (khóa tổng hợp ở 10^7 bản ghi chưa kiểm).

## Comments
