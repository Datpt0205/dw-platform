# 30 — Truy vấn tổng hợp dưới RLS ở quy mô D12: đếm, tổng, nhóm theo trường và theo ngày qua RecordService

Type: prototype
Status: needs-triage
Area: studio · Viết: 24/10/2026
FOG: FOG-81 `aggregate-rls`

## Câu hỏi

1. Một truy vấn tổng hợp đi qua `RecordService` dưới RLS (đếm, tổng một trường số, nhóm theo một trường lọc được, và
   nhóm theo ngày, theo tháng trong múi giờ của công ty) tốn bao lâu ở quy mô D12 (10^7 bản ghi một đối tượng,
   5 × 10^7 bản ghi một tenant), với một người đọc ở mức Toàn công ty và một người ở mức Của tôi giữ 10^6 bản ghi?
2. Dưới policy bản ghi của ADR 0105, kế hoạch truy vấn có giữ partition pruning, chỉ mục slot và InitPlan khi có
   `GROUP BY` và hàm cắt ngày theo múi giờ không, hay rơi về quét cả tenant như các toán tử không leakproof
   ([research.md](../research.md) mục 2)?
3. Chỉ mục nào, dẫn đầu bằng `tenant_id` như mục "Data model rules" của `CLAUDE.md` đòi, giữ cho phép nhóm theo trường
   và theo ngày không phải sắp cả tập khớp, và mỗi chỉ mục thêm tốn bao nhiêu ở mỗi lần ghi?
4. Số đếm trả cho người ở mức Của tôi có bằng đúng số bản ghi người đó lật trang được qua API danh sách không, kể cả khi
   chia sẻ tay và cấp trên có mặt (ADR 0127 quyết định 1)?
5. Khi ngưỡng trượt, hai đường lui của ADR 0127 mục Open 1 (báo cáo nền có giới hạn qua tác vụ chạy nền, hay bảng gộp
   sẵn theo tenant cho người đọc mức Toàn công ty) cho số đo nào?

## Vì sao

ADR 0127 cho báo cáo đi qua API tổng hợp trên `RecordService`, vì quyền trên bản ghi và bảo mật trường giữ nguyên theo
cấu trúc; rủi ro của đường này là hiệu năng ở D12, chưa ai đo. Hôm nay đếm chính xác dừng ở 10.000 (custom-objects:R8.8)
và record-access đo một số đếm có trần 1.001 trong 300 ms (record-access:R9.4); một tổng không trần nhóm theo ngày trên
10^7 bản ghi dưới RLS là một phép đo khác. Số đo này quyết đường tổng hợp có đủ không hay phải mở kho phân tích theo
tenant (ADR 0127 quyết định 7), nên nó phải có trước khi spec W3 được viết.

## Mở khóa

- Spec: `custom-objects` (truy vấn tổng hợp trong `RecordService`, W3), `field-security` (quyết định áp lên số đo,
  chiều và bộ lọc), `record-access` (policy bản ghi dưới `GROUP BY`).
- ADR: 0127 (quyết định 2, Open 1), 0105, 0107.
- DO: D12 (DO-14). Đạt đặt ngưỡng của báo cáo trực tuyến bằng số đo của ticket này (ADR 0127 mục Open 1).
- Không ticket W1 nào trùng: báo cáo ở W3 (v1.5).

## Dựng tối thiểu

Dùng lại bộ dữ liệu gieo D12 và bộ policy của ticket 05 (10^7 bản ghi một đối tượng, 5.000 người dùng, 200 workspace
sâu 6), thêm một trường số và một trường ngày giờ trong slot có chỉ mục, rải ngày theo 24 tháng. Một hàm tổng hợp nguyên
mẫu dựng câu `SELECT` có `GROUP BY` qua cùng đường của `RecordService`, chạy trong giao dịch của người gọi với setting
và sổ tầm của người đó. Đo cả hai hồ sơ: mức Toàn công ty, và mức Của tôi giữ 10^6 bản ghi.

## Phép đo quyết định

| Đo                                                            | Ngưỡng hay so sánh                                            | Quyết định                                       |
| ------------------------------------------------------------- | ------------------------------------------------------------- | ------------------------------------------------ |
| Đếm, tổng; nhóm theo một trường; nhóm theo ngày và theo tháng | Chưa có ngưỡng; ghi p95 cho mỗi hồ sơ quyền                   | Ngưỡng của báo cáo trực tuyến (ADR 0127, Open 1) |
| Kế hoạch truy vấn dưới policy bản ghi khi có `GROUP BY`       | Không Seq Scan trên `studio.records`, như record-access:R9.10 | Chỉ mục nào phải có trước spec W3                |
| Chi phí ghi của mỗi chỉ mục thêm                              | So với record-access:R9.5 (10 ms)                             | Giữ hay bỏ chỉ mục đó                            |
| Số đếm mức Của tôi so với số bản ghi lật trang được           | Bằng nhau                                                     | Đường tổng hợp có giữ quyền trên bản ghi không   |
| Báo cáo nền có giới hạn; bảng gộp sẵn theo tenant             | Ghi p95 và độ trễ dữ liệu của mỗi đường                       | Đường lui khi ngưỡng trượt (ADR 0127, Open 1)    |

Số đo ghi phiên bản PostgreSQL, máy đo (máy tham chiếu của YC20 nếu có, máy dev thì nói rõ) và kế hoạch truy vấn vào
ADR 0127.

## Nguồn

- `docs/adr/0127-reports-through-the-platform-aggregate-api-and-a-per-tenant-analytics-store.md`, quyết định 1, 2, 7 và
  mục Open 1; Quyết định ngày 24/10/2026 (N10) trong [requirements.md](../../requirements.md).
- [research.md](../research.md) mục 1 và 2 (toán tử không leakproof dưới RLS rơi về quét cả tenant, đo ở 1-2 triệu bản
  ghi trên máy dev, chưa đo ở D12).

## Comments
