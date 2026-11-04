# Đo hình dạng RLS bản ghi (record-access/01, ticket 06)

Mục smoke do `make bench-record-access SCALE=smoke MODULUS=8` sinh trên máy dev (record-access/01); mục "d12, máy tham chiếu" do ticket 06 thêm. Không số nào ở mục smoke là số D12, và không số nào ở đây vào ADR-0105 (Accepted) trước ticket 06.

## smoke, máy dev, không phải số D12

Modulus 8 (chưa chọn: luật quyết bước 7 của custom-objects/01 chưa chọn modulus ở scale này).
Mỗi độ trễ là thời gian cả giao dịch đo từ harness, gồm gắn setting và lời gọi
`studio.ensure_principal_scope()`; ngưỡng là của R9, xét lại ở D12 bởi ticket 06.
Ở smoke, kết quả chỉ chọn phương án cho ticket 02 và 03 đọc.

### Máy và cấu hình

- container dwbench-postgres, cổng 127.0.0.1:25442, volume dwbench-postgres-data
- /dev/shm: shm                      64.0M      1.0M     63.0M   2% /dev/shm (compose không đặt shm_size); mọi phiên của harness đặt max_parallel_maintenance_workers = 0, vì CREATE INDEX và VACUUM song song hỏi 64 MB bộ nhớ chia sẻ động và vỡ với 'could not resize shared memory segment' (autovacuum không bao giờ song song)
- image postgres:16.15-alpine@sha256:0cefaabd882e42bcb2a2f3dc56d3ce4770560ba62fd7f197f1a2e008fd5731ab
- giới hạn bộ nhớ 2.0 GiB (docker-compose.prod.yml)
- Docker: 16 CPU, 7905894400 byte RAM, Docker Desktop
- máy: Windows-11-10.0.26300-SP0, 16 luồng CPU (AMD64 Family 25 Model 68 Stepping 1, AuthenticAMD)
- PostgreSQL: PostgreSQL 16.15 on x86_64-pc-linux-musl, compiled by gcc (Alpine 15.2.0) 15.2.0, 64-bit
- shared_buffers 128MB, work_mem 4MB
- một vòng khứ hồi SELECT 1 từ harness: p50 0.81 ms, p95 1.04 ms; mọi độ trễ là thời gian giao dịch phía harness, gồm các vòng khứ hồi (GET và trang đầu 3, ghi 7-8)
- postgresql.conf khác mặc định: DateStyle=ISO, MDY (configuration file); TimeZone=UTC (configuration file); default_text_search_config=pg_catalog.english (configuration file); dynamic_shared_memory_type=posix (configuration file); lc_messages=en_US.utf8 (configuration file); lc_monetary=en_US.utf8 (configuration file); lc_numeric=en_US.utf8 (configuration file); lc_time=en_US.utf8 (configuration file); listen_addresses=* (configuration file); log_timezone=UTC (configuration file); max_connections=100 (configuration file); max_wal_size=1024MB (configuration file); min_wal_size=80MB (configuration file); shared_buffers=163848kB (configuration file); wal_level=logical (command line)
- chỗ trống trên ổ hệ thống trước lần chạy: 63 GiB
- chỉ ở --scale smoke: autovacuum_vacuum_scale_factor = 0.008 trên partition của T1 (soak rút ngắn, cùng hệ số)
- chỉ ở --scale smoke: autovacuum_vacuum_insert_scale_factor = 0.008 trên partition của T1 (soak rút ngắn, cùng hệ số)

### Biến thể chính sách: luật chọn (bước 2)

- trục K (khóa bigint): thắng P0; không phương án nào đạt, trượt; p95 tệ nhất P0 48253.2 ms, K inf ms
- trục L (sổ tầm một dòng mỗi hành động): thắng P0; không phương án nào đạt, trượt; p95 tệ nhất P0 48253.2 ms, L inf ms
- trục E (nhánh EXISTS thay mảng): thắng P0; không phương án nào đạt, trượt; p95 tệ nhất P0 48253.2 ms, E inf ms
- trục H (câu gợi ý cho planner): thắng H; không phương án nào đạt, trượt; p95 tệ nhất P0 48253.2 ms, H 39201.0 ms
- tổ hợp thắng W: {'key': 'uuid', 'ledger': 'row', 'arms': 'array', 'hint': True}

### Biến thể chính sách: trang đầu p95 (ms)

| Hồ sơ | P0 | K | L | E | H | W |
| --- | --- | --- | --- | --- | --- | --- |
| own | 286.0 | 158.3 | 178.7 | 172.9 | 1029.9 | 358.3 |
| own_sort_slot | 220.5 | 213.2 | 189.4 | 155.7 | 211.4 | 223.6 |
| team | 3659.8 | 1835.5 | 2117.0 | 6964.3 | 2720.1 | 1950.1 |
| team_sort_slot | 1982.7 | 1875.9 | 1905.2 | 7030.5 | 1525.8 | 2152.7 |
| workspace_1 | 5168.0 | 1688.7 | 3392.5 | 5892.9 | 3955.7 | 3244.1 |
| workspace_40 | 33754.9 | 36698.8 | 48436.7 | 44763.2 | 28922.3 | 38307.7 |
| company | 27683.1 | 23294.6 | 2370.9 | 31881.0 | 21168.7 | 28148.2 |
| company_updated | 29268.5 | 27487.0 | 2352.6 | 37983.7 | 27382.3 | 31244.9 |
| company_name | 29616.4 | 27915.1 | 2350.2 | 37102.1 | 27924.6 | 32441.3 |
| public_read | 7312.4 | inf | inf | 16654.7 | 7270.6 | 7483.1 |
| manager_50 | 2291.5 | 1782.4 | 2734.6 | 6650.7 | 1736.8 | 2515.0 |
| manager_500 | 33238.5 | 27777.8 | 32899.0 | 39303.2 | 27037.5 | 33567.0 |
| manager_5000 | 48253.2 | 33915.5 | 50840.2 | inf | 39201.0 | 49435.9 |
| share_recipient | 9897.3 | 8895.2 | 9297.9 | 11890.8 | 8222.3 | 10730.7 |
| agent_one_object | 30304.0 | 27748.1 | 2287.9 | 34947.8 | 25956.5 | 31601.6 |
| service_account | 26982.0 | 24808.0 | 2570.0 | 37021.9 | 21242.5 | 26229.9 |

Mỗi ô là p95 lớn nhất qua trang đầu trên hai object, có và không có bộ lọc,
nóng và nguội; số đủ ở Bảng số.

### Bảng số

| Mã | Chỉ số | Biến thể | Giá trị | Mẫu | Ngưỡng | Kết luận | Ghi chú |
| --- | --- | --- | --- | --- | --- | --- | --- |
| record-access:R9.1 | page_lead_cold:agent_one_object | E | 333.8 ms | 76 | <= 50 | trượt | p50 72.18 ms, p99 523.56 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:company | E | 151.1 ms | 147 | <= 50 | trượt | p50 41.32 ms, p99 1090.91 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:company_name | E | 506.9 ms | 51 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 169.15 ms, p99 1266.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:company_updated | E | 287.4 ms | 52 | <= 50 | trượt | trang mới cập nhật p50 135.49 ms, p99 338.75 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:manager_50 | E | 92.5 ms | 168 | <= 50 | trượt | 50 cấp dưới p50 39.04 ms, p99 141.09 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:manager_500 | E | 150.7 ms | 150 | <= 50 | trượt | 500 cấp dưới p50 38.18 ms, p99 301.07 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:manager_5000 | E | 196.2 ms | 79 | <= 50 | trượt | 4999 cấp dưới p50 59.92 ms, p99 308.58 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:own | E | 118.9 ms | 153 | <= 50 | trượt | p50 38.22 ms, p99 237.86 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:own_sort_slot | E | 129 ms | 147 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 35.25 ms, p99 366.58 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:public_read | E | 1270 ms | 79 | <= 50 | trượt | p50 80.15 ms, p99 1689.31 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:service_account | E | 156.8 ms | 157 | <= 50 | trượt | p50 37.30 ms, p99 481.28 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:share_recipient | E | 96.73 ms | 184 | <= 50 | trượt | p50 34.70 ms, p99 152.87 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:team | E | 95.66 ms | 176 | <= 50 | trượt | p50 36.37 ms, p99 136.01 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:team_sort_slot | E | 147.6 ms | 132 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 40.83 ms, p99 250.34 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:workspace_1 | E | 95.59 ms | 175 | <= 50 | trượt | p50 34.52 ms, p99 190.84 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:workspace_40 | E | 192.6 ms | 132 | <= 50 | trượt | 40 workspace p50 41.59 ms, p99 422.11 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:agent_one_object | E | 3.495e+04 ms | 67 | <= 50 | trượt | p50 14811.62 ms, p99 40383.23 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:company | E | 3.161e+04 ms | 52 | <= 50 | trượt | p50 3471.87 ms, p99 37040.87 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:company_name | E | 3.71e+04 ms | 78 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 25916.44 ms, p99 39762.24 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:company_updated | E | 3.798e+04 ms | 74 | <= 50 | trượt | trang mới cập nhật p50 26196.18 ms, p99 39984.29 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:manager_50 | E | 6651 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 1206.96 ms, p99 15614.49 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:manager_500 | E | 3.93e+04 ms | 52 | <= 50 | trượt | 500 cấp dưới p50 4590.88 ms, p99 40052.92 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:manager_5000 | E | inf ms | 54 | <= 50 | trượt | 4999 cấp dưới p50 15108.84 ms, p99 inf ms; 4 lỗi, đầu: QueryCanceledError: canceling statement due to statement timeout dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:own | E | 116.3 ms | 188 | <= 50 | trượt | p50 32.89 ms, p99 249.31 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:own_sort_slot | E | 116.3 ms | 196 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 35.41 ms, p99 1406.12 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:public_read | E | 1.665e+04 ms | 97 | <= 50 | trượt | p50 2474.43 ms, p99 17445.19 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:service_account | E | 3.702e+04 ms | 53 | <= 50 | trượt | p50 4049.99 ms, p99 39464.94 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:share_recipient | E | 1.189e+04 ms | 51 | <= 50 | trượt | p50 1229.72 ms, p99 16826.56 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:team | E | 1965 ms | 51 | <= 50 | trượt | p50 1266.48 ms, p99 3208.85 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:team_sort_slot | E | 7031 ms | 52 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 1200.76 ms, p99 15327.49 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:workspace_1 | E | 5893 ms | 51 | <= 50 | trượt | p50 1146.37 ms, p99 15898.90 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:workspace_40 | E | 4.476e+04 ms | 54 | <= 50 | trượt | 40 workspace p50 7319.03 ms, p99 46374.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:agent_one_object | E | 3.237e+04 ms | 92 | <= 50 | trượt | p50 18698.36 ms, p99 34204.35 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:company | E | 3.188e+04 ms | 55 | <= 50 | trượt | p50 4327.34 ms, p99 33373.36 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:company_name | E | 3.427e+04 ms | 62 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 31766.81 ms, p99 35203.79 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:company_updated | E | 3.368e+04 ms | 61 | <= 50 | trượt | trang mới cập nhật p50 30567.90 ms, p99 34668.28 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:manager_50 | E | 4613 ms | 52 | <= 50 | trượt | 50 cấp dưới p50 1043.01 ms, p99 7318.68 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:manager_500 | E | 3.456e+04 ms | 54 | <= 50 | trượt | 500 cấp dưới p50 4525.58 ms, p99 35010.68 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:manager_5000 | E | 5.025e+04 ms | 59 | <= 50 | trượt | 4999 cấp dưới p50 13114.46 ms, p99 54982.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:own | E | 134.9 ms | 158 | <= 50 | trượt | p50 35.16 ms, p99 213.80 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:own_sort_slot | E | 155.7 ms | 144 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 37.22 ms, p99 209.69 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:public_read | E | 4792 ms | 115 | <= 50 | trượt | p50 3223.74 ms, p99 4989.70 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:service_account | E | 3.172e+04 ms | 57 | <= 50 | trượt | p50 4013.53 ms, p99 33422.43 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:share_recipient | E | 2547 ms | 51 | <= 50 | trượt | p50 1030.72 ms, p99 5083.73 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:team | E | 6964 ms | 54 | <= 50 | trượt | p50 1154.79 ms, p99 7280.65 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:team_sort_slot | E | 3957 ms | 54 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 1364.48 ms, p99 5056.38 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:workspace_1 | E | 4167 ms | 58 | <= 50 | trượt | p50 1291.13 ms, p99 6783.90 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:workspace_40 | E | 3.468e+04 ms | 58 | <= 50 | trượt | 40 workspace p50 7330.48 ms, p99 37846.59 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:agent_one_object | E | 258.9 ms | 69 | <= 50 | trượt | p50 81.54 ms, p99 2167.04 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:company | E | 152.6 ms | 132 | <= 50 | trượt | p50 45.20 ms, p99 295.81 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:company_name | E | 378.3 ms | 52 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 133.14 ms, p99 1160.25 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:company_updated | E | 287 ms | 52 | <= 50 | trượt | trang mới cập nhật p50 136.17 ms, p99 738.00 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:manager_50 | E | 92.83 ms | 163 | <= 50 | trượt | 50 cấp dưới p50 38.40 ms, p99 209.10 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:manager_500 | E | 181.7 ms | 120 | <= 50 | trượt | 500 cấp dưới p50 45.04 ms, p99 372.38 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:manager_5000 | E | 330.5 ms | 60 | <= 50 | trượt | 4999 cấp dưới p50 82.65 ms, p99 853.94 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:own | E | 172.9 ms | 109 | <= 50 | trượt | p50 48.61 ms, p99 188.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:own_sort_slot | E | 149.4 ms | 122 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 42.85 ms, p99 205.71 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:public_read | E | 2429 ms | 110 | <= 50 | trượt | p50 88.96 ms, p99 3275.07 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:service_account | E | 190.6 ms | 148 | <= 50 | trượt | p50 43.04 ms, p99 413.19 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:share_recipient | E | 107.8 ms | 138 | <= 50 | trượt | p50 41.30 ms, p99 147.20 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:team | E | 99.59 ms | 171 | <= 50 | trượt | p50 38.97 ms, p99 137.29 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:team_sort_slot | E | 141.6 ms | 112 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 45.99 ms, p99 205.62 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:workspace_1 | E | 104.3 ms | 149 | <= 50 | trượt | p50 39.68 ms, p99 191.17 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:workspace_40 | E | 346.1 ms | 79 | <= 50 | trượt | 40 workspace p50 58.37 ms, p99 995.27 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:agent_one_object | E | 9088 ms | 51 | <= 50 | trượt | p50 448.41 ms, p99 12981.63 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:company | E | 148.1 ms | 151 | <= 50 | trượt | p50 37.41 ms, p99 973.76 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:company_name | E | 355.6 ms | 53 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 147.32 ms, p99 515.44 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:company_updated | E | 287.1 ms | 54 | <= 50 | trượt | trang mới cập nhật p50 113.95 ms, p99 539.46 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:manager_50 | E | 85.58 ms | 196 | <= 50 | trượt | 50 cấp dưới p50 33.36 ms, p99 136.91 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:manager_500 | E | 198 ms | 150 | <= 50 | trượt | 500 cấp dưới p50 39.41 ms, p99 440.33 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:manager_5000 | E | 475.5 ms | 58 | <= 50 | trượt | 4999 cấp dưới p50 79.93 ms, p99 1309.73 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:own | E | 137.8 ms | 177 | <= 50 | trượt | p50 27.80 ms, p99 182.59 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:own_sort_slot | E | 106.5 ms | 171 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 31.78 ms, p99 228.82 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:public_read | E | 1374 ms | 85 | <= 50 | trượt | p50 62.80 ms, p99 2157.41 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:service_account | E | 213.6 ms | 166 | <= 50 | trượt | p50 34.95 ms, p99 872.91 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:share_recipient | E | 92.46 ms | 187 | <= 50 | trượt | p50 35.68 ms, p99 253.12 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:team | E | 100.4 ms | 171 | <= 50 | trượt | p50 36.12 ms, p99 242.75 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:team_sort_slot | E | 109.1 ms | 136 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 41.11 ms, p99 148.33 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:workspace_1 | E | 103.1 ms | 185 | <= 50 | trượt | p50 38.29 ms, p99 1048.76 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:workspace_40 | E | 151.1 ms | 148 | <= 50 | trượt | 40 workspace p50 40.43 ms, p99 391.18 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:agent_one_object | E | 103.6 ms | 210 | <= 50 | trượt | p50 32.46 ms, p99 1394.68 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:company | E | 3638 ms | 51 | <= 50 | trượt | p50 453.55 ms, p99 3888.67 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:company_name | E | 3552 ms | 54 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 2601.05 ms, p99 4719.94 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:company_updated | E | 3375 ms | 53 | <= 50 | trượt | trang mới cập nhật p50 2691.99 ms, p99 3732.23 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:manager_50 | E | 1865 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 125.52 ms, p99 2819.80 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:manager_500 | E | 3044 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 315.23 ms, p99 3842.64 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:manager_5000 | E | 6203 ms | 52 | <= 50 | trượt | 4999 cấp dưới p50 1133.84 ms, p99 8494.97 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:own | E | 117.2 ms | 193 | <= 50 | trượt | p50 26.46 ms, p99 276.82 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:own_sort_slot | E | 109.4 ms | 229 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 29.06 ms, p99 296.38 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:public_read | E | 2826 ms | 63 | <= 50 | trượt | p50 255.62 ms, p99 2909.74 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:service_account | E | 3006 ms | 51 | <= 50 | trượt | p50 314.10 ms, p99 3606.34 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:share_recipient | E | 305.7 ms | 51 | <= 50 | trượt | p50 120.09 ms, p99 1278.07 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:team | E | 288.1 ms | 51 | <= 50 | trượt | p50 104.65 ms, p99 2772.85 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:team_sort_slot | E | 323.3 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 122.07 ms, p99 1881.60 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:workspace_1 | E | 609.4 ms | 51 | <= 50 | trượt | p50 141.71 ms, p99 2849.28 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:workspace_40 | E | 4780 ms | 51 | <= 50 | trượt | 40 workspace p50 724.57 ms, p99 5103.38 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:agent_one_object | E | 114.7 ms | 147 | <= 50 | trượt | p50 36.60 ms, p99 204.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:company | E | 2887 ms | 52 | <= 50 | trượt | p50 287.19 ms, p99 3495.02 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:company_name | E | 3488 ms | 52 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 2709.04 ms, p99 3658.30 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:company_updated | E | 3545 ms | 54 | <= 50 | trượt | trang mới cập nhật p50 2589.80 ms, p99 3752.44 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:manager_50 | E | 597.5 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 107.97 ms, p99 948.13 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:manager_500 | E | 2393 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 318.91 ms, p99 2710.82 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:manager_5000 | E | 4815 ms | 51 | <= 50 | trượt | 4999 cấp dưới p50 1024.05 ms, p99 4972.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:own | E | 142.7 ms | 169 | <= 50 | trượt | p50 31.92 ms, p99 351.50 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:own_sort_slot | E | 132.2 ms | 148 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 35.12 ms, p99 448.48 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:public_read | E | 1392 ms | 103 | <= 50 | trượt | p50 321.53 ms, p99 2838.71 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:service_account | E | 2898 ms | 52 | <= 50 | trượt | p50 245.36 ms, p99 3108.64 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:share_recipient | E | 570.4 ms | 51 | <= 50 | trượt | p50 106.61 ms, p99 1138.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:team | E | 377.3 ms | 53 | <= 50 | trượt | p50 112.94 ms, p99 1185.79 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:team_sort_slot | E | 307.9 ms | 53 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 119.20 ms, p99 526.18 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:workspace_1 | E | 888.9 ms | 53 | <= 50 | trượt | p50 97.42 ms, p99 1347.32 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:workspace_40 | E | 3517 ms | 51 | <= 50 | trượt | 40 workspace p50 658.77 ms, p99 4375.85 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:agent_one_object | E | 4369 ms | 52 | <= 50 | trượt | p50 536.00 ms, p99 6984.25 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:company | E | 153.7 ms | 134 | <= 50 | trượt | p50 43.44 ms, p99 251.15 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:company_name | E | 397.8 ms | 57 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 123.46 ms, p99 1173.48 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:company_updated | E | 344.6 ms | 56 | <= 50 | trượt | trang mới cập nhật p50 146.21 ms, p99 1184.19 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:manager_50 | E | 113.5 ms | 138 | <= 50 | trượt | 50 cấp dưới p50 40.61 ms, p99 240.17 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:manager_500 | E | 166.4 ms | 130 | <= 50 | trượt | 500 cấp dưới p50 44.30 ms, p99 333.57 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:manager_5000 | E | 175 ms | 75 | <= 50 | trượt | 4999 cấp dưới p50 61.93 ms, p99 265.37 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:own | E | 125.8 ms | 144 | <= 50 | trượt | p50 42.10 ms, p99 266.74 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:own_sort_slot | E | 118.3 ms | 158 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 41.19 ms, p99 382.05 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:public_read | E | 1011 ms | 118 | <= 50 | trượt | p50 80.16 ms, p99 2928.99 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:service_account | E | 189.5 ms | 130 | <= 50 | trượt | p50 42.64 ms, p99 296.18 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:share_recipient | E | 131.3 ms | 153 | <= 50 | trượt | p50 39.21 ms, p99 806.91 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:team | E | 122.5 ms | 157 | <= 50 | trượt | p50 35.24 ms, p99 239.93 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:team_sort_slot | E | 158.2 ms | 110 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 47.72 ms, p99 274.42 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:workspace_1 | E | 142 ms | 159 | <= 50 | trượt | p50 39.38 ms, p99 237.58 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:workspace_40 | E | 121 ms | 121 | <= 50 | trượt | 40 workspace p50 46.02 ms, p99 247.65 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:agent_one_object | E | 405.8 ms | 52 | <= 5 | trượt | p50 37.57 ms, p99 2377.03 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:company | E | 271.5 ms | 51 | <= 5 | trượt | p50 34.59 ms, p99 1398.91 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:company_name | E | 130.8 ms | 51 | <= 5 | trượt | ORDER BY name "vi-VN-x-icu" p50 36.40 ms, p99 1430.34 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:company_updated | E | 129.4 ms | 51 | <= 5 | trượt | trang mới cập nhật p50 30.72 ms, p99 183.76 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:manager_50 | E | 157.4 ms | 51 | <= 5 | trượt | 50 cấp dưới p50 34.36 ms, p99 991.23 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:manager_500 | E | 143.8 ms | 51 | <= 5 | trượt | 500 cấp dưới p50 33.52 ms, p99 214.30 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:manager_5000 | E | 141.9 ms | 51 | <= 5 | trượt | 4999 cấp dưới p50 29.13 ms, p99 900.26 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:own | E | 190.2 ms | 51 | <= 5 | trượt | p50 33.47 ms, p99 774.62 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:own_sort_slot | E | 754.6 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 40.26 ms, p99 1348.56 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:public_read | E | 1008 ms | 55 | <= 5 | trượt | p50 47.57 ms, p99 1521.83 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:service_account | E | 129 ms | 51 | <= 5 | trượt | p50 36.20 ms, p99 722.68 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:share_recipient | E | 134.5 ms | 51 | <= 5 | trượt | p50 33.26 ms, p99 147.80 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:team | E | 133.6 ms | 51 | <= 5 | trượt | p50 26.51 ms, p99 244.97 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:team_sort_slot | E | 235 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 30.96 ms, p99 1383.26 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:workspace_1 | E | 179.5 ms | 51 | <= 5 | trượt | p50 40.07 ms, p99 948.95 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:workspace_40 | E | 143.2 ms | 51 | <= 5 | trượt | 40 workspace p50 34.92 ms, p99 237.32 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:agent_one_object | E | 267.2 ms | 51 | <= 5 | trượt | p50 36.26 ms, p99 2332.98 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:company | E | 161.6 ms | 53 | <= 5 | trượt | p50 30.95 ms, p99 231.12 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:company_name | E | 163.2 ms | 52 | <= 5 | trượt | ORDER BY name "vi-VN-x-icu" p50 40.23 ms, p99 754.65 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:company_updated | E | 142.4 ms | 51 | <= 5 | trượt | trang mới cập nhật p50 30.36 ms, p99 1956.74 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:manager_50 | E | 303.8 ms | 51 | <= 5 | trượt | 50 cấp dưới p50 33.73 ms, p99 1370.51 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:manager_500 | E | 103.4 ms | 52 | <= 5 | trượt | 500 cấp dưới p50 27.51 ms, p99 191.47 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:manager_5000 | E | 155.6 ms | 51 | <= 5 | trượt | 4999 cấp dưới p50 26.97 ms, p99 295.20 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:own | E | 108.2 ms | 51 | <= 5 | trượt | p50 29.69 ms, p99 833.09 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:own_sort_slot | E | 159.9 ms | 53 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 37.71 ms, p99 1636.95 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:public_read | E | 648.2 ms | 103 | <= 5 | trượt | p50 55.70 ms, p99 949.15 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:service_account | E | 126.2 ms | 52 | <= 5 | trượt | p50 26.63 ms, p99 986.24 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:share_recipient | E | 151.4 ms | 51 | <= 5 | trượt | p50 32.59 ms, p99 578.08 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:team | E | 113 ms | 53 | <= 5 | trượt | p50 34.69 ms, p99 244.34 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:team_sort_slot | E | 107 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 32.15 ms, p99 164.74 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:workspace_1 | E | 188.1 ms | 52 | <= 5 | trượt | p50 35.42 ms, p99 279.01 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:workspace_40 | E | 134.1 ms | 53 | <= 5 | trượt | 40 workspace p50 33.18 ms, p99 201.66 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:agent_one_object | E | 435.7 ms | 59 | <= 50 | trượt | p50 101.41 ms, p99 476.59 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:company | E | 297.4 ms | 114 | <= 50 | trượt | p50 46.51 ms, p99 378.92 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:company_name | E | 333 ms | 119 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 43.06 ms, p99 435.38 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:company_updated | E | 269.7 ms | 122 | <= 50 | trượt | trang mới cập nhật p50 42.77 ms, p99 342.10 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:manager_50 | E | 116.9 ms | 136 | <= 50 | trượt | 50 cấp dưới p50 41.57 ms, p99 229.11 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:manager_500 | E | 180.6 ms | 132 | <= 50 | trượt | 500 cấp dưới p50 42.36 ms, p99 899.62 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:manager_5000 | E | 380.8 ms | 53 | <= 50 | trượt | 4999 cấp dưới p50 83.05 ms, p99 456.13 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:own | E | 116.9 ms | 156 | <= 50 | trượt | p50 40.16 ms, p99 152.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:own_sort_slot | E | 111 ms | 140 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 42.78 ms, p99 205.99 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:public_read | E | 1237 ms | 72 | <= 50 | trượt | p50 98.39 ms, p99 2265.35 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:service_account | E | 278.3 ms | 103 | <= 50 | trượt | p50 47.55 ms, p99 396.91 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:share_recipient | E | 141.7 ms | 146 | <= 50 | trượt | p50 37.62 ms, p99 239.89 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:team | E | 95.9 ms | 148 | <= 50 | trượt | p50 41.80 ms, p99 173.06 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:team_sort_slot | E | 120.1 ms | 143 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 38.25 ms, p99 243.15 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:workspace_1 | E | 117.3 ms | 153 | <= 50 | trượt | p50 40.50 ms, p99 278.58 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:workspace_40 | E | 347.6 ms | 53 | <= 50 | trượt | 40 workspace p50 100.88 ms, p99 2212.90 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:agent_one_object | E | 245.6 ms | 65 | <= 50 | trượt | p50 128.90 ms, p99 327.20 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:company | E | 279.8 ms | 70 | <= 50 | trượt | p50 75.50 ms, p99 706.34 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:company_name | E | 253.7 ms | 68 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 70.47 ms, p99 711.92 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:company_updated | E | 298.6 ms | 70 | <= 50 | trượt | trang mới cập nhật p50 64.54 ms, p99 1397.68 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:manager_50 | E | 159.9 ms | 83 | <= 50 | trượt | 50 cấp dưới p50 59.50 ms, p99 688.22 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:manager_500 | E | 294.9 ms | 67 | <= 50 | trượt | 500 cấp dưới p50 72.59 ms, p99 462.21 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:manager_5000 | E | 479.8 ms | 54 | <= 50 | trượt | 4999 cấp dưới p50 117.08 ms, p99 697.08 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:own | E | 98.95 ms | 141 | <= 50 | trượt | p50 39.53 ms, p99 138.17 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:own_sort_slot | E | 149.4 ms | 142 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 36.79 ms, p99 209.76 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:public_read | E | 649.3 ms | 96 | <= 50 | trượt | p50 124.09 ms, p99 1362.53 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:service_account | E | 240 ms | 68 | <= 50 | trượt | p50 75.91 ms, p99 403.76 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:share_recipient | E | 234.5 ms | 84 | <= 50 | trượt | p50 56.00 ms, p99 691.97 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:team | E | 203.7 ms | 81 | <= 50 | trượt | p50 58.60 ms, p99 1130.74 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:team_sort_slot | E | 183.5 ms | 92 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 54.80 ms, p99 336.32 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:workspace_1 | E | 144.3 ms | 88 | <= 50 | trượt | p50 56.60 ms, p99 1085.31 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:workspace_40 | E | 361.2 ms | 64 | <= 50 | trượt | 40 workspace p50 75.30 ms, p99 731.47 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:agent_one_object | E | 6802 ms | 61 | <= 300 | trượt | p50 1055.01 ms, p99 7303.92 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:company | E | 4681 ms | 225 | <= 300 | trượt | p50 188.68 ms, p99 7120.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:company_name | E | 4586 ms | 219 | <= 300 | trượt | ORDER BY name "vi-VN-x-icu" p50 191.69 ms, p99 6731.03 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:company_updated | E | 5190 ms | 235 | <= 300 | trượt | trang mới cập nhật p50 194.13 ms, p99 7119.59 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:manager_50 | E | 218.7 ms | 1000 | <= 300 | đạt | 50 cấp dưới p50 107.05 ms, p99 4174.02 ms |
| record-access:R9.4 | count_cold:manager_500 | E | 6613 ms | 165 | <= 300 | trượt | 500 cấp dưới p50 230.50 ms, p99 8955.56 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:manager_5000 | E | 8446 ms | 52 | <= 300 | trượt | 4999 cấp dưới p50 1514.93 ms, p99 9684.93 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:own | E | 223.4 ms | 1000 | <= 300 | đạt | p50 105.98 ms, p99 3723.85 ms |
| record-access:R9.4 | count_cold:own_sort_slot | E | 208.9 ms | 1000 | <= 300 | đạt | sắp theo slot t02, tầm hẹp p50 107.79 ms, p99 3148.17 ms |
| record-access:R9.4 | count_cold:public_read | E | 6927 ms | 54 | <= 300 | trượt | p50 4266.29 ms, p99 7587.44 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:service_account | E | 4202 ms | 219 | <= 300 | trượt | p50 199.81 ms, p99 7016.35 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:share_recipient | E | 211.7 ms | 1000 | <= 300 | đạt | p50 105.00 ms, p99 3652.47 ms |
| record-access:R9.4 | count_cold:team | E | 216.9 ms | 1000 | <= 300 | đạt | p50 105.64 ms, p99 3120.85 ms |
| record-access:R9.4 | count_cold:team_sort_slot | E | 217 ms | 1000 | <= 300 | đạt | sắp theo slot t02, tầm hẹp p50 107.86 ms, p99 3262.81 ms |
| record-access:R9.4 | count_cold:workspace_1 | E | 217.3 ms | 1000 | <= 300 | đạt | p50 110.89 ms, p99 3345.05 ms |
| record-access:R9.4 | count_cold:workspace_40 | E | 6476 ms | 54 | <= 300 | trượt | 40 workspace p50 603.57 ms, p99 10174.30 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:agent_one_object | E | 5788 ms | 64 | <= 300 | trượt | p50 1369.38 ms, p99 9795.79 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:company | E | 4461 ms | 210 | <= 300 | trượt | p50 215.33 ms, p99 7680.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:company_name | E | 4682 ms | 214 | <= 300 | trượt | ORDER BY name "vi-VN-x-icu" p50 199.24 ms, p99 8977.98 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:company_updated | E | 5209 ms | 205 | <= 300 | trượt | trang mới cập nhật p50 205.79 ms, p99 7428.98 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:manager_50 | E | 172.7 ms | 1010 | <= 300 | đạt | 50 cấp dưới p50 121.20 ms, p99 3322.05 ms |
| record-access:R9.4 | count_warm:manager_500 | E | 7123 ms | 127 | <= 300 | trượt | 500 cấp dưới p50 266.04 ms, p99 7824.84 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:manager_5000 | E | 9858 ms | 53 | <= 300 | trượt | 4999 cấp dưới p50 1258.98 ms, p99 12509.19 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:own | E | 169.9 ms | 1028 | <= 300 | đạt | p50 121.86 ms, p99 252.50 ms |
| record-access:R9.4 | count_warm:own_sort_slot | E | 168.1 ms | 1016 | <= 300 | đạt | sắp theo slot t02, tầm hẹp p50 120.89 ms, p99 3651.93 ms |
| record-access:R9.4 | count_warm:public_read | E | 1.251e+04 ms | 142 | <= 300 | trượt | p50 8615.93 ms, p99 13778.38 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:service_account | E | 4858 ms | 218 | <= 300 | trượt | p50 204.02 ms, p99 6862.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:share_recipient | E | 170.2 ms | 1005 | <= 300 | đạt | p50 119.29 ms, p99 2769.50 ms |
| record-access:R9.4 | count_warm:team | E | 170.2 ms | 1005 | <= 300 | đạt | p50 119.71 ms, p99 3318.12 ms |
| record-access:R9.4 | count_warm:team_sort_slot | E | 169.6 ms | 1010 | <= 300 | đạt | sắp theo slot t02, tầm hẹp p50 119.33 ms, p99 243.70 ms |
| record-access:R9.4 | count_warm:workspace_1 | E | 180 ms | 1010 | <= 300 | đạt | p50 123.05 ms, p99 3715.77 ms |
| record-access:R9.4 | count_warm:workspace_40 | E | 7082 ms | 57 | <= 300 | trượt | 40 workspace p50 727.90 ms, p99 11288.02 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.6 | assign_p95 | E | 354.2 ms | 58 | <= 20 | trượt | p50 26.90 ms, p99 369.80 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.6 | share_p95 | E | 32.43 ms | 1000 |  | — | p50 20.89 ms, p99 136.03 ms |
| record-access:R9.7 | scope_compute:company | E | 26.89 ms | 1000 | <= 50 | đạt | p50 21.56 ms, p99 32.42 ms |
| record-access:R9.7 | scope_compute:manager_50 | E | 30.84 ms | 1000 | <= 50 | đạt | p50 25.00 ms, p99 35.09 ms |
| record-access:R9.7 | scope_compute:manager_500 | E | 34.5 ms | 1000 | <= 50 | đạt | p50 27.11 ms, p99 40.32 ms |
| record-access:R9.7 | scope_compute:manager_5000 | E | 56.83 ms | 1000 | <= 50 | trượt | p50 30.83 ms, p99 63.70 ms |
| record-access:R9.7 | scope_compute:own | E | 25.51 ms | 1000 | <= 50 | đạt | p50 20.58 ms, p99 29.05 ms |
| record-access:R9.7 | scope_compute:public_read | E | 23.86 ms | 1000 | <= 50 | đạt | p50 19.14 ms, p99 28.54 ms |
| record-access:R9.7 | scope_compute:service_account | E | 27.52 ms | 1000 | <= 50 | đạt | p50 22.05 ms, p99 33.11 ms |
| record-access:R9.7 | scope_compute:share_recipient | E | 23.85 ms | 1000 | <= 50 | đạt | p50 19.18 ms, p99 28.41 ms |
| record-access:R9.7 | scope_compute:team | E | 25.98 ms | 1000 | <= 50 | đạt | p50 20.63 ms, p99 30.23 ms |
| record-access:R9.7 | scope_compute:workspace_1 | E | 25.34 ms | 1000 | <= 50 | đạt | p50 19.95 ms, p99 28.51 ms |
| record-access:R9.7 | scope_compute:workspace_40 | E | 42.45 ms | 1000 | <= 50 | đạt | p50 33.08 ms, p99 48.61 ms |
| record-access:R9.8 | door_valid_p95 | E | 1.028 ms | 1000 | <= 1 | trượt | p50 0.75 ms, p99 1.24 ms; một vòng khứ hồi, trong giao dịch đã gắn setting |
| record-access:R9.9 | recompute_total_1 | E | 401.6 s |  |  | — | 1 kết nối, 5000 chủ thể, 5000 dòng valid ở epoch mới, dưới tải hỗn hợp |
| record-access:R9.9 | recompute_total_4 | E | 106 s |  | <= 120 | đạt | 4 kết nối, 5000 chủ thể, 5000 dòng valid ở epoch mới, dưới tải hỗn hợp |
| record-access:R9.9 | stale_reads_after_revoke | E | 0 lần | 1000 | <= 0 | đạt | 1000 lần lặp trên hai kết nối; câu lệnh trước thu hồi thấy tầm 1000 lần |
| record-access:bước 5 | delete_p95 | E | 29.62 ms | 1000 |  | — | p50 23.40 ms, p99 105.27 ms |
| record-access:R9.1 | page_lead_cold:agent_one_object | H | 193 ms | 68 | <= 50 | trượt | p50 75.90 ms, p99 936.95 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:company | H | 144.8 ms | 117 | <= 50 | trượt | p50 45.41 ms, p99 740.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:company_name | H | 260.2 ms | 58 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 91.30 ms, p99 353.40 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:company_updated | H | 169.6 ms | 62 | <= 50 | trượt | trang mới cập nhật p50 101.10 ms, p99 1039.59 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:manager_50 | H | 968.5 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 331.82 ms, p99 3319.58 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:manager_500 | H | 2.17e+04 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 5285.86 ms, p99 25639.51 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:manager_5000 | H | 3.92e+04 ms | 58 | <= 50 | trượt | 4999 cấp dưới p50 19248.05 ms, p99 49530.51 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:own | H | 148.4 ms | 119 | <= 50 | trượt | p50 45.24 ms, p99 231.73 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:own_sort_slot | H | 128.6 ms | 95 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 51.37 ms, p99 195.85 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:public_read | H | 1029 ms | 100 | <= 50 | trượt | p50 60.05 ms, p99 1392.39 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:service_account | H | 111.7 ms | 102 | <= 50 | trượt | p50 48.40 ms, p99 180.51 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:share_recipient | H | 7508 ms | 54 | <= 50 | trượt | p50 3628.05 ms, p99 8055.61 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:team | H | 1157 ms | 51 | <= 50 | trượt | p50 444.60 ms, p99 3185.82 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:team_sort_slot | H | 796.6 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 316.49 ms, p99 2597.37 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:workspace_1 | H | 1260 ms | 51 | <= 50 | trượt | p50 471.78 ms, p99 1331.55 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:workspace_40 | H | 2.892e+04 ms | 58 | <= 50 | trượt | 40 workspace p50 8756.49 ms, p99 30263.79 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:agent_one_object | H | 2.315e+04 ms | 53 | <= 50 | trượt | p50 16521.79 ms, p99 24169.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:company | H | 2.117e+04 ms | 53 | <= 50 | trượt | p50 4986.21 ms, p99 22941.74 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:company_name | H | 2.243e+04 ms | 53 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 16472.65 ms, p99 22660.78 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:company_updated | H | 2.256e+04 ms | 52 | <= 50 | trượt | trang mới cập nhật p50 15166.74 ms, p99 23372.80 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:manager_50 | H | 1737 ms | 52 | <= 50 | trượt | 50 cấp dưới p50 966.37 ms, p99 4868.29 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:manager_500 | H | 2.153e+04 ms | 53 | <= 50 | trượt | 500 cấp dưới p50 4924.71 ms, p99 22987.72 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:manager_5000 | H | 3.264e+04 ms | 68 | <= 50 | trượt | 4999 cấp dưới p50 21469.36 ms, p99 40635.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:own | H | 162.8 ms | 137 | <= 50 | trượt | p50 37.66 ms, p99 240.89 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:own_sort_slot | H | 145.3 ms | 107 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 49.33 ms, p99 173.89 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:public_read | H | 7271 ms | 67 | <= 50 | trượt | p50 1034.21 ms, p99 7272.69 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:service_account | H | 2.124e+04 ms | 54 | <= 50 | trượt | p50 4846.39 ms, p99 21765.95 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:share_recipient | H | 1424 ms | 51 | <= 50 | trượt | p50 576.40 ms, p99 1554.75 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:team | H | 1581 ms | 51 | <= 50 | trượt | p50 706.75 ms, p99 4871.69 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:team_sort_slot | H | 1358 ms | 52 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 558.16 ms, p99 1634.49 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:workspace_1 | H | 3956 ms | 51 | <= 50 | trượt | p50 625.75 ms, p99 4866.14 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:workspace_40 | H | 2.658e+04 ms | 51 | <= 50 | trượt | 40 workspace p50 14851.84 ms, p99 27705.78 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:agent_one_object | H | 2.596e+04 ms | 57 | <= 50 | trượt | p50 16246.00 ms, p99 28659.46 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:company | H | 1.95e+04 ms | 53 | <= 50 | trượt | p50 4482.77 ms, p99 29043.74 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:company_name | H | 2.792e+04 ms | 53 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 19292.53 ms, p99 29544.34 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:company_updated | H | 2.738e+04 ms | 58 | <= 50 | trượt | trang mới cập nhật p50 18409.75 ms, p99 29574.95 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:manager_50 | H | 1390 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 393.46 ms, p99 1425.96 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:manager_500 | H | 2.388e+04 ms | 54 | <= 50 | trượt | 500 cấp dưới p50 5510.83 ms, p99 30970.70 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:manager_5000 | H | 3.432e+04 ms | 90 | <= 50 | trượt | 4999 cấp dưới p50 21013.55 ms, p99 42600.26 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:own | H | 146.2 ms | 137 | <= 50 | trượt | p50 42.98 ms, p99 216.41 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:own_sort_slot | H | 121.8 ms | 104 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 48.54 ms, p99 170.02 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:public_read | H | 3768 ms | 138 | <= 50 | trượt | p50 732.34 ms, p99 4430.62 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:service_account | H | 1.937e+04 ms | 53 | <= 50 | trượt | p50 5496.14 ms, p99 23648.84 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:share_recipient | H | 1934 ms | 51 | <= 50 | trượt | p50 295.94 ms, p99 2032.35 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:team | H | 1272 ms | 51 | <= 50 | trượt | p50 257.91 ms, p99 1325.29 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:team_sort_slot | H | 1526 ms | 52 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 384.32 ms, p99 2094.10 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:workspace_1 | H | 1672 ms | 51 | <= 50 | trượt | p50 475.86 ms, p99 2179.44 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:workspace_40 | H | 2.799e+04 ms | 55 | <= 50 | trượt | 40 workspace p50 10618.99 ms, p99 33236.01 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:agent_one_object | H | 174.5 ms | 64 | <= 50 | trượt | p50 66.22 ms, p99 250.65 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:company | H | 135.4 ms | 97 | <= 50 | trượt | p50 53.03 ms, p99 1412.11 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:company_name | H | 328.3 ms | 56 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 82.91 ms, p99 783.71 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:company_updated | H | 240.4 ms | 59 | <= 50 | trượt | trang mới cập nhật p50 86.18 ms, p99 1164.68 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:manager_50 | H | 924.5 ms | 52 | <= 50 | trượt | 50 cấp dưới p50 225.05 ms, p99 1313.99 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:manager_500 | H | 2.704e+04 ms | 55 | <= 50 | trượt | 500 cấp dưới p50 4240.97 ms, p99 30330.68 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:manager_5000 | H | 3.696e+04 ms | 60 | <= 50 | trượt | 4999 cấp dưới p50 21297.05 ms, p99 43165.48 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:own | H | 122.8 ms | 110 | <= 50 | trượt | p50 45.52 ms, p99 259.83 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:own_sort_slot | H | 159.4 ms | 112 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 47.48 ms, p99 283.10 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:public_read | H | 3415 ms | 144 | <= 50 | trượt | p50 56.92 ms, p99 4031.98 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:service_account | H | 162.7 ms | 105 | <= 50 | trượt | p50 48.64 ms, p99 887.49 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:share_recipient | H | 8222 ms | 53 | <= 50 | trượt | p50 1444.12 ms, p99 8480.91 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:team | H | 1036 ms | 51 | <= 50 | trượt | p50 255.94 ms, p99 1142.89 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:team_sort_slot | H | 992.8 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 236.33 ms, p99 1024.50 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:workspace_1 | H | 1264 ms | 51 | <= 50 | trượt | p50 361.12 ms, p99 1335.26 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:workspace_40 | H | 2.845e+04 ms | 57 | <= 50 | trượt | 40 workspace p50 8958.91 ms, p99 35565.90 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:agent_one_object | H | 1319 ms | 51 | <= 50 | trượt | p50 474.42 ms, p99 1627.13 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:company | H | 106.1 ms | 104 | <= 50 | trượt | p50 48.46 ms, p99 130.98 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:company_name | H | 220.7 ms | 62 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 85.59 ms, p99 1216.75 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:company_updated | H | 206.6 ms | 58 | <= 50 | trượt | trang mới cập nhật p50 80.15 ms, p99 211.25 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:manager_50 | H | 893.7 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 122.71 ms, p99 3153.43 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:manager_500 | H | 1302 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 201.52 ms, p99 1750.99 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:manager_5000 | H | 383.2 ms | 55 | <= 50 | trượt | 4999 cấp dưới p50 108.32 ms, p99 1615.01 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:own | H | 134.9 ms | 154 | <= 50 | trượt | p50 37.60 ms, p99 225.52 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:own_sort_slot | H | 211.4 ms | 128 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 45.80 ms, p99 316.00 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:public_read | H | 6213 ms | 62 | <= 50 | trượt | p50 677.80 ms, p99 6224.98 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:service_account | H | 110.2 ms | 131 | <= 50 | trượt | p50 41.93 ms, p99 870.38 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:share_recipient | H | 2389 ms | 52 | <= 50 | trượt | p50 685.72 ms, p99 4463.75 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:team | H | 2720 ms | 51 | <= 50 | trượt | p50 166.74 ms, p99 4370.96 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:team_sort_slot | H | 1408 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 593.39 ms, p99 1515.43 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:workspace_1 | H | 707.7 ms | 51 | <= 50 | trượt | p50 240.81 ms, p99 830.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:workspace_40 | H | 568.1 ms | 51 | <= 50 | trượt | 40 workspace p50 155.93 ms, p99 612.01 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:agent_one_object | H | 218 ms | 97 | <= 50 | trượt | p50 51.51 ms, p99 1995.86 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:company | H | 1843 ms | 51 | <= 50 | trượt | p50 426.03 ms, p99 2665.49 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:company_name | H | 2234 ms | 51 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 1561.45 ms, p99 3048.60 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:company_updated | H | 2241 ms | 51 | <= 50 | trượt | trang mới cập nhật p50 1450.49 ms, p99 2847.73 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:manager_50 | H | 169.5 ms | 80 | <= 50 | trượt | 50 cấp dưới p50 56.90 ms, p99 384.65 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:manager_500 | H | 1758 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 397.53 ms, p99 2195.51 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:manager_5000 | H | 2604 ms | 52 | <= 50 | trượt | 4999 cấp dưới p50 1455.92 ms, p99 3134.77 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:own | H | 1030 ms | 298 | <= 50 | trượt | p50 31.63 ms, p99 1060.34 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:own_sort_slot | H | 136.4 ms | 248 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 31.53 ms, p99 389.73 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:public_read | H | 1705 ms | 69 | <= 50 | trượt | p50 93.07 ms, p99 1710.42 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:service_account | H | 2392 ms | 51 | <= 50 | trượt | p50 431.56 ms, p99 3025.53 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:share_recipient | H | 324.8 ms | 78 | <= 50 | trượt | p50 82.65 ms, p99 1806.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:team | H | 199.9 ms | 71 | <= 50 | trượt | p50 70.88 ms, p99 762.70 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:team_sort_slot | H | 215.3 ms | 65 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 90.50 ms, p99 355.23 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:workspace_1 | H | 259.2 ms | 62 | <= 50 | trượt | p50 95.46 ms, p99 319.08 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:workspace_40 | H | 2009 ms | 51 | <= 50 | trượt | 40 workspace p50 735.97 ms, p99 2299.15 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:agent_one_object | H | 136.6 ms | 187 | <= 50 | trượt | p50 37.66 ms, p99 234.65 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:company | H | 2701 ms | 51 | <= 50 | trượt | p50 337.47 ms, p99 3174.05 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:company_name | H | 2384 ms | 51 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 1364.88 ms, p99 2752.57 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:company_updated | H | 2476 ms | 51 | <= 50 | trượt | trang mới cập nhật p50 1545.05 ms, p99 2996.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:manager_50 | H | 212.3 ms | 85 | <= 50 | trượt | 50 cấp dưới p50 67.51 ms, p99 962.19 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:manager_500 | H | 2213 ms | 52 | <= 50 | trượt | 500 cấp dưới p50 294.90 ms, p99 2600.84 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:manager_5000 | H | 2877 ms | 53 | <= 50 | trượt | 4999 cấp dưới p50 1210.79 ms, p99 4302.58 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:own | H | 95.83 ms | 317 | <= 50 | trượt | p50 29.63 ms, p99 230.63 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:own_sort_slot | H | 115 ms | 261 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 32.48 ms, p99 429.82 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:public_read | H | 3240 ms | 109 | <= 50 | trượt | p50 87.14 ms, p99 3761.62 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:service_account | H | 2011 ms | 52 | <= 50 | trượt | p50 247.64 ms, p99 2269.00 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:share_recipient | H | 185.8 ms | 83 | <= 50 | trượt | p50 68.63 ms, p99 792.26 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:team | H | 234 ms | 72 | <= 50 | trượt | p50 73.61 ms, p99 263.55 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:team_sort_slot | H | 230.3 ms | 65 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 80.98 ms, p99 370.18 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:workspace_1 | H | 234.4 ms | 79 | <= 50 | trượt | p50 63.74 ms, p99 732.27 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:workspace_40 | H | 3078 ms | 52 | <= 50 | trượt | 40 workspace p50 690.15 ms, p99 3487.08 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:agent_one_object | H | 1321 ms | 54 | <= 50 | trượt | p50 538.40 ms, p99 1954.95 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:company | H | 125.7 ms | 123 | <= 50 | trượt | p50 45.47 ms, p99 223.81 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:company_name | H | 242.2 ms | 68 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 70.50 ms, p99 841.10 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:company_updated | H | 270.9 ms | 70 | <= 50 | trượt | trang mới cập nhật p50 77.80 ms, p99 1247.53 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:manager_50 | H | 795.5 ms | 52 | <= 50 | trượt | 50 cấp dưới p50 185.07 ms, p99 2127.67 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:manager_500 | H | 719.8 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 230.94 ms, p99 1290.53 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:manager_5000 | H | 207.3 ms | 60 | <= 50 | trượt | 4999 cấp dưới p50 83.83 ms, p99 286.96 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:own | H | 163.8 ms | 117 | <= 50 | trượt | p50 45.94 ms, p99 327.77 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:own_sort_slot | H | 139.6 ms | 164 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 39.83 ms, p99 247.38 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:public_read | H | 4254 ms | 114 | <= 50 | trượt | p50 507.38 ms, p99 4495.29 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:service_account | H | 129 ms | 116 | <= 50 | trượt | p50 48.29 ms, p99 275.61 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:share_recipient | H | 1060 ms | 51 | <= 50 | trượt | p50 218.73 ms, p99 1297.19 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:team | H | 733.2 ms | 51 | <= 50 | trượt | p50 206.62 ms, p99 1174.36 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:team_sort_slot | H | 1170 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 258.96 ms, p99 1520.46 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:workspace_1 | H | 572.6 ms | 52 | <= 50 | trượt | p50 152.55 ms, p99 703.61 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:workspace_40 | H | 379.5 ms | 51 | <= 50 | trượt | 40 workspace p50 165.97 ms, p99 476.71 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:agent_one_object | H | 107.4 ms | 51 | <= 5 | trượt | p50 33.35 ms, p99 146.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:company | H | 205.2 ms | 51 | <= 5 | trượt | p50 32.53 ms, p99 836.06 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:company_name | H | 64.28 ms | 51 | <= 5 | trượt | ORDER BY name "vi-VN-x-icu" p50 30.88 ms, p99 91.64 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:company_updated | H | 102.2 ms | 51 | <= 5 | trượt | trang mới cập nhật p50 28.29 ms, p99 779.85 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:manager_50 | H | 162.1 ms | 51 | <= 5 | trượt | 50 cấp dưới p50 38.39 ms, p99 1059.47 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:manager_500 | H | 392 ms | 51 | <= 5 | trượt | 500 cấp dưới p50 41.27 ms, p99 970.35 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:manager_5000 | H | 196.8 ms | 51 | <= 5 | trượt | 4999 cấp dưới p50 47.25 ms, p99 849.96 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:own | H | 112.3 ms | 51 | <= 5 | trượt | p50 43.96 ms, p99 121.84 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:own_sort_slot | H | 108.8 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 35.80 ms, p99 208.08 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:public_read | H | 861.7 ms | 52 | <= 5 | trượt | p50 36.63 ms, p99 896.07 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:service_account | H | 137.1 ms | 51 | <= 5 | trượt | p50 30.86 ms, p99 170.95 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:share_recipient | H | 100.4 ms | 51 | <= 5 | trượt | p50 37.09 ms, p99 153.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:team | H | 115.9 ms | 51 | <= 5 | trượt | p50 35.43 ms, p99 819.69 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:team_sort_slot | H | 162.2 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 36.91 ms, p99 906.29 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:workspace_1 | H | 121 ms | 51 | <= 5 | trượt | p50 31.61 ms, p99 625.71 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:workspace_40 | H | 137.1 ms | 51 | <= 5 | trượt | 40 workspace p50 45.52 ms, p99 1070.93 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:agent_one_object | H | 125 ms | 51 | <= 5 | trượt | p50 22.13 ms, p99 887.91 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:company | H | 98.74 ms | 51 | <= 5 | trượt | p50 31.44 ms, p99 138.56 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:company_name | H | 122.2 ms | 51 | <= 5 | trượt | ORDER BY name "vi-VN-x-icu" p50 25.85 ms, p99 480.40 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:company_updated | H | 114.7 ms | 51 | <= 5 | trượt | trang mới cập nhật p50 30.23 ms, p99 586.53 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:manager_50 | H | 138.3 ms | 51 | <= 5 | trượt | 50 cấp dưới p50 37.41 ms, p99 1059.47 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:manager_500 | H | 143.9 ms | 51 | <= 5 | trượt | 500 cấp dưới p50 39.52 ms, p99 156.35 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:manager_5000 | H | 98.86 ms | 51 | <= 5 | trượt | 4999 cấp dưới p50 35.27 ms, p99 190.68 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:own | H | 120.6 ms | 51 | <= 5 | trượt | p50 33.29 ms, p99 824.66 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:own_sort_slot | H | 113.6 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 30.53 ms, p99 659.72 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:public_read | H | 1063 ms | 88 | <= 5 | trượt | p50 32.06 ms, p99 4366.36 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:service_account | H | 123.4 ms | 51 | <= 5 | trượt | p50 28.78 ms, p99 847.64 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:share_recipient | H | 164.4 ms | 51 | <= 5 | trượt | p50 35.47 ms, p99 662.20 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:team | H | 79.82 ms | 51 | <= 5 | trượt | p50 34.00 ms, p99 103.11 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:team_sort_slot | H | 90.82 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 37.82 ms, p99 111.87 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:workspace_1 | H | 130.1 ms | 51 | <= 5 | trượt | p50 29.74 ms, p99 224.63 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:workspace_40 | H | 104.5 ms | 51 | <= 5 | trượt | 40 workspace p50 26.32 ms, p99 207.41 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:agent_one_object | H | 198 ms | 68 | <= 50 | trượt | p50 74.25 ms, p99 341.58 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:company | H | 166.3 ms | 101 | <= 50 | trượt | p50 50.18 ms, p99 270.37 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:company_name | H | 192.7 ms | 97 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 51.95 ms, p99 758.83 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:company_updated | H | 145.5 ms | 99 | <= 50 | trượt | trang mới cập nhật p50 50.58 ms, p99 1276.72 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:manager_50 | H | 697.5 ms | 54 | <= 50 | trượt | 50 cấp dưới p50 179.05 ms, p99 915.48 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:manager_500 | H | 6345 ms | 53 | <= 50 | trượt | 500 cấp dưới p50 458.55 ms, p99 19006.20 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:manager_5000 | H | 1.338e+04 ms | 53 | <= 50 | trượt | 4999 cấp dưới p50 113.73 ms, p99 36289.10 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:own | H | 162.8 ms | 109 | <= 50 | trượt | p50 47.08 ms, p99 233.26 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:own_sort_slot | H | 173.7 ms | 99 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 52.61 ms, p99 253.11 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:public_read | H | 913.2 ms | 72 | <= 50 | trượt | p50 79.15 ms, p99 987.97 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:service_account | H | 168.1 ms | 66 | <= 50 | trượt | p50 68.04 ms, p99 942.48 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:share_recipient | H | 6454 ms | 53 | <= 50 | trượt | p50 3347.30 ms, p99 7068.62 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:team | H | 699 ms | 51 | <= 50 | trượt | p50 194.61 ms, p99 818.78 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:team_sort_slot | H | 862.9 ms | 53 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 231.02 ms, p99 1044.39 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:workspace_1 | H | 672.6 ms | 52 | <= 50 | trượt | p50 244.76 ms, p99 2388.08 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:workspace_40 | H | 8988 ms | 52 | <= 50 | trượt | 40 workspace p50 289.15 ms, p99 17799.47 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:agent_one_object | H | 178 ms | 61 | <= 50 | trượt | p50 89.20 ms, p99 275.68 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:company | H | 160.7 ms | 85 | <= 50 | trượt | p50 57.70 ms, p99 1166.90 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:company_name | H | 168.2 ms | 96 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 52.65 ms, p99 957.74 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:company_updated | H | 164.6 ms | 94 | <= 50 | trượt | trang mới cập nhật p50 54.20 ms, p99 829.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:manager_50 | H | 358.7 ms | 54 | <= 50 | trượt | 50 cấp dưới p50 91.73 ms, p99 738.30 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:manager_500 | H | 997.4 ms | 52 | <= 50 | trượt | 500 cấp dưới p50 241.15 ms, p99 1085.72 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:manager_5000 | H | 253.5 ms | 58 | <= 50 | trượt | 4999 cấp dưới p50 85.88 ms, p99 1773.33 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:own | H | 175.2 ms | 144 | <= 50 | trượt | p50 40.51 ms, p99 285.02 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:own_sort_slot | H | 135.2 ms | 131 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 42.35 ms, p99 195.24 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:public_read | H | 385 ms | 137 | <= 50 | trượt | p50 51.61 ms, p99 3456.98 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:service_account | H | 134.6 ms | 96 | <= 50 | trượt | p50 57.36 ms, p99 167.50 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:share_recipient | H | 2772 ms | 53 | <= 50 | trượt | p50 437.59 ms, p99 3893.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:team | H | 609.8 ms | 53 | <= 50 | trượt | p50 107.95 ms, p99 798.26 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:team_sort_slot | H | 558.3 ms | 56 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 163.51 ms, p99 628.49 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:workspace_1 | H | 634.2 ms | 52 | <= 50 | trượt | p50 108.67 ms, p99 1141.56 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:workspace_40 | H | 619.2 ms | 51 | <= 50 | trượt | 40 workspace p50 165.85 ms, p99 2027.50 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:agent_one_object | H | 1692 ms | 71 | <= 300 | trượt | p50 741.67 ms, p99 2081.82 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:company | H | 1094 ms | 168 | <= 300 | trượt | p50 245.76 ms, p99 1866.94 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:company_name | H | 1329 ms | 149 | <= 300 | trượt | ORDER BY name "vi-VN-x-icu" p50 261.53 ms, p99 1700.95 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:company_updated | H | 1305 ms | 131 | <= 300 | trượt | trang mới cập nhật p50 260.70 ms, p99 1390.44 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:manager_50 | H | 3762 ms | 51 | <= 300 | trượt | 50 cấp dưới p50 1496.73 ms, p99 5094.81 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:manager_500 | H | 3.284e+04 ms | 52 | <= 300 | trượt | 500 cấp dưới p50 8022.26 ms, p99 35426.46 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:manager_5000 | H | 3.198e+04 ms | 87 | <= 300 | trượt | 4999 cấp dưới p50 20134.48 ms, p99 36057.41 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:own | H | 7055 ms | 53 | <= 300 | trượt | p50 4149.03 ms, p99 8804.49 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:own_sort_slot | H | 7568 ms | 62 | <= 300 | trượt | sắp theo slot t02, tầm hẹp p50 5164.77 ms, p99 9922.37 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:public_read | H | 1272 ms | 109 | <= 300 | trượt | p50 479.91 ms, p99 1539.17 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:service_account | H | 1154 ms | 137 | <= 300 | trượt | p50 266.73 ms, p99 2068.80 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:share_recipient | H | 6356 ms | 54 | <= 300 | trượt | p50 3719.99 ms, p99 8480.26 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:team | H | 5794 ms | 55 | <= 300 | trượt | p50 3006.49 ms, p99 6536.14 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:team_sort_slot | H | 6742 ms | 57 | <= 300 | trượt | sắp theo slot t02, tầm hẹp p50 3764.89 ms, p99 9109.22 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:workspace_1 | H | 3845 ms | 52 | <= 300 | trượt | p50 1373.23 ms, p99 5033.96 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:workspace_40 | H | 1.557e+04 ms | 55 | <= 300 | trượt | 40 workspace p50 8346.00 ms, p99 32879.10 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:agent_one_object | H | 1728 ms | 79 | <= 300 | trượt | p50 387.26 ms, p99 1950.67 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:company | H | 1262 ms | 146 | <= 300 | trượt | p50 230.46 ms, p99 1782.85 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:company_name | H | 1356 ms | 128 | <= 300 | trượt | ORDER BY name "vi-VN-x-icu" p50 227.89 ms, p99 1745.82 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:company_updated | H | 1321 ms | 130 | <= 300 | trượt | trang mới cập nhật p50 257.82 ms, p99 1522.39 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:manager_50 | H | 3979 ms | 51 | <= 300 | trượt | 50 cấp dưới p50 1239.56 ms, p99 4783.79 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:manager_500 | H | 4.216e+04 ms | 53 | <= 300 | trượt | 500 cấp dưới p50 8988.16 ms, p99 45256.14 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:manager_5000 | H | 3.182e+04 ms | 64 | <= 300 | trượt | 4999 cấp dưới p50 15074.55 ms, p99 48271.89 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:own | H | 7546 ms | 64 | <= 300 | trượt | p50 5667.49 ms, p99 7941.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:own_sort_slot | H | 5763 ms | 51 | <= 300 | trượt | sắp theo slot t02, tầm hẹp p50 1734.89 ms, p99 6172.72 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:public_read | H | 940.6 ms | 102 | <= 300 | trượt | p50 426.26 ms, p99 1194.89 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:service_account | H | 1281 ms | 161 | <= 300 | trượt | p50 226.46 ms, p99 1582.18 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:share_recipient | H | 7107 ms | 52 | <= 300 | trượt | p50 2857.97 ms, p99 7664.69 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:team | H | 6856 ms | 54 | <= 300 | trượt | p50 1789.86 ms, p99 8397.65 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:team_sort_slot | H | 6655 ms | 52 | <= 300 | trượt | sắp theo slot t02, tầm hẹp p50 2240.28 ms, p99 9279.05 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:workspace_1 | H | 4354 ms | 52 | <= 300 | trượt | p50 1373.42 ms, p99 6061.86 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:workspace_40 | H | 4.061e+04 ms | 53 | <= 300 | trượt | 40 workspace p50 5213.24 ms, p99 42740.76 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.6 | assign_p95 | H | 310.7 ms | 58 | <= 20 | trượt | p50 29.57 ms, p99 340.31 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.6 | share_p95 | H | 35.56 ms | 1000 |  | — | p50 20.72 ms, p99 141.69 ms |
| record-access:R9.7 | scope_compute:company | H | 30.52 ms | 1000 | <= 50 | đạt | p50 22.52 ms, p99 39.14 ms |
| record-access:R9.7 | scope_compute:manager_50 | H | 34.91 ms | 1000 | <= 50 | đạt | p50 25.64 ms, p99 45.78 ms |
| record-access:R9.7 | scope_compute:manager_500 | H | 38.55 ms | 1000 | <= 50 | đạt | p50 27.97 ms, p99 46.92 ms |
| record-access:R9.7 | scope_compute:manager_5000 | H | 62.41 ms | 1000 | <= 50 | trượt | p50 32.74 ms, p99 74.47 ms |
| record-access:R9.7 | scope_compute:own | H | 29.73 ms | 1000 | <= 50 | đạt | p50 21.44 ms, p99 35.66 ms |
| record-access:R9.7 | scope_compute:public_read | H | 27.04 ms | 1000 | <= 50 | đạt | p50 20.05 ms, p99 35.46 ms |
| record-access:R9.7 | scope_compute:service_account | H | 30.8 ms | 1000 | <= 50 | đạt | p50 23.00 ms, p99 38.16 ms |
| record-access:R9.7 | scope_compute:share_recipient | H | 26.47 ms | 1000 | <= 50 | đạt | p50 20.28 ms, p99 36.13 ms |
| record-access:R9.7 | scope_compute:team | H | 29.72 ms | 1000 | <= 50 | đạt | p50 21.48 ms, p99 37.02 ms |
| record-access:R9.7 | scope_compute:workspace_1 | H | 28.02 ms | 1000 | <= 50 | đạt | p50 20.65 ms, p99 37.08 ms |
| record-access:R9.7 | scope_compute:workspace_40 | H | 46.54 ms | 1000 | <= 50 | đạt | p50 33.83 ms, p99 58.80 ms |
| record-access:R9.8 | door_valid_p95 | H | 1.202 ms | 1000 | <= 1 | trượt | p50 0.79 ms, p99 1.55 ms; một vòng khứ hồi, trong giao dịch đã gắn setting |
| record-access:R9.9 | recompute_total_1 | H | 423.4 s |  |  | — | 1 kết nối, 5000 chủ thể, 5000 dòng valid ở epoch mới, dưới tải hỗn hợp |
| record-access:R9.9 | recompute_total_4 | H | 120.9 s |  | <= 120 | trượt | 4 kết nối, 5000 chủ thể, 5000 dòng valid ở epoch mới, dưới tải hỗn hợp |
| record-access:R9.9 | stale_reads_after_revoke | H | 0 lần | 1000 | <= 0 | đạt | 1000 lần lặp trên hai kết nối; câu lệnh trước thu hồi thấy tầm 1000 lần |
| record-access:bước 5 | delete_p95 | H | 28.15 ms | 1000 |  | — | p50 21.20 ms, p99 127.85 ms |
| record-access:R9.1 | page_lead_cold:agent_one_object | K | 237.5 ms | 66 | <= 50 | trượt | p50 73.90 ms, p99 614.18 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:company | K | 106.7 ms | 116 | <= 50 | trượt | p50 44.79 ms, p99 358.79 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:company_name | K | 229.1 ms | 54 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 89.52 ms, p99 445.38 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:company_updated | K | 250.6 ms | 55 | <= 50 | trượt | trang mới cập nhật p50 83.00 ms, p99 341.32 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:manager_50 | K | 1782 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 200.76 ms, p99 3487.81 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:manager_500 | K | 2.539e+04 ms | 53 | <= 50 | trượt | 500 cấp dưới p50 2521.78 ms, p99 28073.90 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:manager_5000 | K | 3.31e+04 ms | 88 | <= 50 | trượt | 4999 cấp dưới p50 19257.10 ms, p99 46314.48 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:own | K | 125.9 ms | 105 | <= 50 | trượt | p50 49.25 ms, p99 254.62 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:own_sort_slot | K | 170.8 ms | 90 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 51.57 ms, p99 992.41 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:public_read | K | 997.6 ms | 115 | <= 50 | trượt | p50 61.49 ms, p99 1852.87 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:service_account | K | 131.8 ms | 107 | <= 50 | trượt | p50 48.78 ms, p99 188.43 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:share_recipient | K | 6440 ms | 54 | <= 50 | trượt | p50 1442.94 ms, p99 6936.43 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:team | K | 765.6 ms | 51 | <= 50 | trượt | p50 173.79 ms, p99 1094.01 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:team_sort_slot | K | 519.3 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 161.57 ms, p99 2828.32 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:workspace_1 | K | 1133 ms | 52 | <= 50 | trượt | p50 484.36 ms, p99 3525.82 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:workspace_40 | K | 3.67e+04 ms | 55 | <= 50 | trượt | 40 workspace p50 5623.71 ms, p99 38397.07 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:agent_one_object | K | 2.775e+04 ms | 58 | <= 50 | trượt | p50 19702.56 ms, p99 28389.00 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:company | K | 2.329e+04 ms | 56 | <= 50 | trượt | p50 5759.69 ms, p99 25235.70 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:company_name | K | 2.792e+04 ms | 54 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 22729.38 ms, p99 30030.07 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:company_updated | K | 2.749e+04 ms | 54 | <= 50 | trượt | trang mới cập nhật p50 20023.51 ms, p99 28755.20 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:manager_50 | K | 1363 ms | 53 | <= 50 | trượt | 50 cấp dưới p50 336.13 ms, p99 2452.87 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:manager_500 | K | 2.472e+04 ms | 55 | <= 50 | trượt | 500 cấp dưới p50 3685.31 ms, p99 28254.61 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:manager_5000 | K | 3.367e+04 ms | 62 | <= 50 | trượt | 4999 cấp dưới p50 19432.19 ms, p99 42910.93 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:own | K | 112.5 ms | 140 | <= 50 | trượt | p50 40.83 ms, p99 176.97 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:own_sort_slot | K | 153.4 ms | 171 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 37.71 ms, p99 226.66 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:public_read | K | 6318 ms | 72 | <= 50 | trượt | p50 914.73 ms, p99 6608.84 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:service_account | K | 2.481e+04 ms | 55 | <= 50 | trượt | p50 4117.20 ms, p99 26385.08 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:share_recipient | K | 1659 ms | 52 | <= 50 | trượt | p50 345.33 ms, p99 2660.33 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:team | K | 1835 ms | 51 | <= 50 | trượt | p50 373.19 ms, p99 2583.02 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:team_sort_slot | K | 1370 ms | 52 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 281.46 ms, p99 2136.34 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:workspace_1 | K | 810.3 ms | 51 | <= 50 | trượt | p50 235.94 ms, p99 3445.00 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:workspace_40 | K | 3.18e+04 ms | 56 | <= 50 | trượt | 40 workspace p50 11044.27 ms, p99 35746.52 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:agent_one_object | K | 2.57e+04 ms | 54 | <= 50 | trượt | p50 15721.32 ms, p99 26259.32 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:company | K | 2.069e+04 ms | 51 | <= 50 | trượt | p50 6852.04 ms, p99 26965.00 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:company_name | K | 2.673e+04 ms | 55 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 18423.62 ms, p99 28334.56 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:company_updated | K | 2.645e+04 ms | 54 | <= 50 | trượt | trang mới cập nhật p50 17854.24 ms, p99 26662.11 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:manager_50 | K | 1782 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 267.45 ms, p99 1995.42 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:manager_500 | K | 2.192e+04 ms | 56 | <= 50 | trượt | 500 cấp dưới p50 7066.58 ms, p99 28672.72 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:manager_5000 | K | 3.326e+04 ms | 67 | <= 50 | trượt | 4999 cấp dưới p50 22429.84 ms, p99 42678.94 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:own | K | 144.3 ms | 101 | <= 50 | trượt | p50 50.34 ms, p99 250.61 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:own_sort_slot | K | 150 ms | 99 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 50.39 ms, p99 229.14 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:public_read | K | inf ms | 143 | <= 50 | trượt | p50 750.84 ms, p99 inf ms; 18 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction. dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:service_account | K | 1.909e+04 ms | 58 | <= 50 | trượt | p50 5940.61 ms, p99 24526.71 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:share_recipient | K | 1875 ms | 51 | <= 50 | trượt | p50 265.37 ms, p99 1992.98 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:team | K | 1747 ms | 52 | <= 50 | trượt | p50 270.33 ms, p99 2105.24 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:team_sort_slot | K | 1876 ms | 54 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 405.40 ms, p99 1983.49 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:workspace_1 | K | 1689 ms | 51 | <= 50 | trượt | p50 349.74 ms, p99 2093.17 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:workspace_40 | K | 2.587e+04 ms | 68 | <= 50 | trượt | 40 workspace p50 12925.85 ms, p99 30966.97 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:agent_one_object | K | 167.7 ms | 75 | <= 50 | trượt | p50 61.48 ms, p99 226.01 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:company | K | 153.4 ms | 88 | <= 50 | trượt | p50 55.75 ms, p99 818.00 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:company_name | K | 212.9 ms | 59 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 88.76 ms, p99 1250.11 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:company_updated | K | 338.5 ms | 57 | <= 50 | trượt | trang mới cập nhật p50 96.13 ms, p99 1318.31 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:manager_50 | K | 1336 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 199.03 ms, p99 1459.13 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:manager_500 | K | 2.778e+04 ms | 54 | <= 50 | trượt | 500 cấp dưới p50 6356.94 ms, p99 30636.87 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:manager_5000 | K | 3.392e+04 ms | 72 | <= 50 | trượt | 4999 cấp dưới p50 20323.45 ms, p99 45573.47 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:own | K | 151.1 ms | 93 | <= 50 | trượt | p50 53.60 ms, p99 316.16 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:own_sort_slot | K | 213.2 ms | 93 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 52.93 ms, p99 796.79 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:public_read | K | inf ms | 167 | <= 50 | trượt | p50 56.21 ms, p99 inf ms; 21 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction. dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:service_account | K | 206.2 ms | 103 | <= 50 | trượt | p50 51.04 ms, p99 780.01 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:share_recipient | K | 8895 ms | 55 | <= 50 | trượt | p50 1223.92 ms, p99 9279.11 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:team | K | 1194 ms | 51 | <= 50 | trượt | p50 267.22 ms, p99 1284.68 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:team_sort_slot | K | 1008 ms | 52 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 263.32 ms, p99 1235.07 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:workspace_1 | K | 1217 ms | 51 | <= 50 | trượt | p50 242.34 ms, p99 1449.35 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:workspace_40 | K | 3.018e+04 ms | 57 | <= 50 | trượt | 40 workspace p50 11889.39 ms, p99 37144.13 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:agent_one_object | K | 1142 ms | 51 | <= 50 | trượt | p50 266.44 ms, p99 1242.27 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:company | K | 115.9 ms | 120 | <= 50 | trượt | p50 45.82 ms, p99 224.42 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:company_name | K | 250.7 ms | 63 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 74.45 ms, p99 855.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:company_updated | K | 241.6 ms | 61 | <= 50 | trượt | trang mới cập nhật p50 83.13 ms, p99 351.48 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:manager_50 | K | 407.4 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 114.55 ms, p99 2524.29 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:manager_500 | K | 1054 ms | 52 | <= 50 | trượt | 500 cấp dưới p50 212.10 ms, p99 1428.35 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:manager_5000 | K | 194.8 ms | 63 | <= 50 | trượt | 4999 cấp dưới p50 72.39 ms, p99 504.48 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:own | K | 122.4 ms | 157 | <= 50 | trượt | p50 38.31 ms, p99 305.76 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:own_sort_slot | K | 126 ms | 164 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 40.03 ms, p99 241.44 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:public_read | K | 5443 ms | 65 | <= 50 | trượt | p50 688.33 ms, p99 5450.12 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:service_account | K | 89.57 ms | 116 | <= 50 | trượt | p50 45.86 ms, p99 106.80 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:share_recipient | K | 1079 ms | 51 | <= 50 | trượt | p50 346.69 ms, p99 2139.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:team | K | 545.7 ms | 51 | <= 50 | trượt | p50 156.90 ms, p99 732.85 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:team_sort_slot | K | 1297 ms | 52 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 230.60 ms, p99 2930.77 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:workspace_1 | K | 416.5 ms | 52 | <= 50 | trượt | p50 126.25 ms, p99 682.95 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:workspace_40 | K | 470.7 ms | 51 | <= 50 | trượt | 40 workspace p50 134.69 ms, p99 808.11 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:agent_one_object | K | 69.7 ms | 359 | <= 50 | trượt | p50 35.82 ms, p99 172.23 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:company | K | 2139 ms | 51 | <= 50 | trượt | p50 414.28 ms, p99 2800.81 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:company_name | K | 2704 ms | 53 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 1573.08 ms, p99 2978.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:company_updated | K | 2495 ms | 51 | <= 50 | trượt | trang mới cập nhật p50 1618.11 ms, p99 3045.18 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:manager_50 | K | 175.3 ms | 89 | <= 50 | trượt | 50 cấp dưới p50 57.88 ms, p99 536.50 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:manager_500 | K | 2266 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 326.73 ms, p99 3751.71 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:manager_5000 | K | 3502 ms | 55 | <= 50 | trượt | 4999 cấp dưới p50 1622.54 ms, p99 4167.31 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:own | K | 68.29 ms | 514 | <= 50 | trượt | p50 25.55 ms, p99 148.85 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:own_sort_slot | K | 123.7 ms | 546 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 27.09 ms, p99 793.12 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:public_read | K | 1490 ms | 77 | <= 50 | trượt | p50 89.01 ms, p99 1777.52 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:service_account | K | 1859 ms | 51 | <= 50 | trượt | p50 272.10 ms, p99 2562.07 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:share_recipient | K | 141.3 ms | 104 | <= 50 | trượt | p50 49.80 ms, p99 218.24 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:team | K | 209.6 ms | 84 | <= 50 | trượt | p50 59.32 ms, p99 578.51 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:team_sort_slot | K | 266.9 ms | 69 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 75.59 ms, p99 308.35 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:workspace_1 | K | 241.1 ms | 75 | <= 50 | trượt | p50 67.05 ms, p99 742.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:workspace_40 | K | 2022 ms | 51 | <= 50 | trượt | 40 workspace p50 475.10 ms, p99 2827.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:agent_one_object | K | 141.8 ms | 157 | <= 50 | trượt | p50 38.47 ms, p99 178.44 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:company | K | 2497 ms | 51 | <= 50 | trượt | p50 600.94 ms, p99 2644.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:company_name | K | 2438 ms | 52 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 1087.43 ms, p99 2588.80 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:company_updated | K | 2379 ms | 53 | <= 50 | trượt | trang mới cập nhật p50 1362.18 ms, p99 2741.59 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:manager_50 | K | 251.4 ms | 83 | <= 50 | trượt | 50 cấp dưới p50 72.69 ms, p99 742.70 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:manager_500 | K | 2204 ms | 52 | <= 50 | trượt | 500 cấp dưới p50 287.33 ms, p99 2371.85 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:manager_5000 | K | 3202 ms | 52 | <= 50 | trượt | 4999 cấp dưới p50 1279.03 ms, p99 3700.41 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:own | K | 158.3 ms | 189 | <= 50 | trượt | p50 34.37 ms, p99 411.48 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:own_sort_slot | K | 140.6 ms | 238 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 34.14 ms, p99 257.31 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:public_read | K | inf ms | 122 | <= 50 | trượt | p50 97.66 ms, p99 inf ms; 13 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction. dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:service_account | K | 1800 ms | 52 | <= 50 | trượt | p50 262.47 ms, p99 2122.50 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:share_recipient | K | 254.6 ms | 85 | <= 50 | trượt | p50 64.97 ms, p99 681.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:team | K | 207.7 ms | 78 | <= 50 | trượt | p50 69.32 ms, p99 638.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:team_sort_slot | K | 282.1 ms | 74 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 80.18 ms, p99 479.94 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:workspace_1 | K | 222.2 ms | 84 | <= 50 | trượt | p50 58.44 ms, p99 1339.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:workspace_40 | K | 2761 ms | 51 | <= 50 | trượt | 40 workspace p50 1028.73 ms, p99 3188.27 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:agent_one_object | K | 1513 ms | 52 | <= 50 | trượt | p50 863.11 ms, p99 2280.76 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:company | K | 105.6 ms | 102 | <= 50 | trượt | p50 49.93 ms, p99 150.11 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:company_name | K | 189.4 ms | 65 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 82.03 ms, p99 749.94 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:company_updated | K | 249.4 ms | 59 | <= 50 | trượt | trang mới cập nhật p50 92.78 ms, p99 1187.84 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:manager_50 | K | 732.9 ms | 52 | <= 50 | trượt | 50 cấp dưới p50 223.05 ms, p99 768.75 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:manager_500 | K | 595.8 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 277.33 ms, p99 1161.96 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:manager_5000 | K | 237 ms | 61 | <= 50 | trượt | 4999 cấp dưới p50 93.10 ms, p99 456.27 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:own | K | 150.4 ms | 120 | <= 50 | trượt | p50 45.41 ms, p99 232.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:own_sort_slot | K | 122.9 ms | 127 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 42.62 ms, p99 213.95 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:public_read | K | inf ms | 129 | <= 50 | trượt | p50 571.04 ms, p99 inf ms; 14 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction. dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:service_account | K | 158.5 ms | 98 | <= 50 | trượt | p50 50.83 ms, p99 688.29 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:share_recipient | K | 1443 ms | 52 | <= 50 | trượt | p50 207.31 ms, p99 1632.30 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:team | K | 1063 ms | 51 | <= 50 | trượt | p50 169.21 ms, p99 1224.01 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:team_sort_slot | K | 1535 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 233.72 ms, p99 1773.91 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:workspace_1 | K | 828.7 ms | 52 | <= 50 | trượt | p50 130.36 ms, p99 1306.98 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:workspace_40 | K | 411.2 ms | 51 | <= 50 | trượt | 40 workspace p50 191.97 ms, p99 437.13 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:agent_one_object | K | 121.7 ms | 51 | <= 5 | trượt | p50 30.26 ms, p99 505.78 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:company | K | 138.2 ms | 51 | <= 5 | trượt | p50 28.06 ms, p99 147.49 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:company_name | K | 162.4 ms | 51 | <= 5 | trượt | ORDER BY name "vi-VN-x-icu" p50 26.43 ms, p99 220.57 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:company_updated | K | 103 ms | 51 | <= 5 | trượt | trang mới cập nhật p50 28.80 ms, p99 175.79 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:manager_50 | K | 148.1 ms | 51 | <= 5 | trượt | 50 cấp dưới p50 34.27 ms, p99 933.62 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:manager_500 | K | 103.8 ms | 51 | <= 5 | trượt | 500 cấp dưới p50 36.47 ms, p99 127.65 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:manager_5000 | K | 129.5 ms | 51 | <= 5 | trượt | 4999 cấp dưới p50 44.09 ms, p99 169.72 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:own | K | 150.7 ms | 51 | <= 5 | trượt | p50 31.85 ms, p99 658.94 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:own_sort_slot | K | 132.6 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 38.26 ms, p99 726.08 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:public_read | K | 797.9 ms | 52 | <= 5 | trượt | p50 25.55 ms, p99 1022.32 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:service_account | K | 545 ms | 51 | <= 5 | trượt | p50 33.42 ms, p99 912.97 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:share_recipient | K | 88.14 ms | 51 | <= 5 | trượt | p50 33.57 ms, p99 1055.15 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:team | K | 133.7 ms | 51 | <= 5 | trượt | p50 37.58 ms, p99 190.90 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:team_sort_slot | K | 116.1 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 35.08 ms, p99 1023.44 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:workspace_1 | K | 168.8 ms | 51 | <= 5 | trượt | p50 28.27 ms, p99 1021.70 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:workspace_40 | K | 109.9 ms | 51 | <= 5 | trượt | 40 workspace p50 24.32 ms, p99 113.87 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:agent_one_object | K | 97.97 ms | 51 | <= 5 | trượt | p50 28.28 ms, p99 572.63 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:company | K | 99.91 ms | 51 | <= 5 | trượt | p50 37.60 ms, p99 140.50 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:company_name | K | 125.2 ms | 51 | <= 5 | trượt | ORDER BY name "vi-VN-x-icu" p50 28.82 ms, p99 996.05 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:company_updated | K | 127.8 ms | 51 | <= 5 | trượt | trang mới cập nhật p50 29.62 ms, p99 534.01 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:manager_50 | K | 147.9 ms | 52 | <= 5 | trượt | 50 cấp dưới p50 45.11 ms, p99 643.82 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:manager_500 | K | 122.1 ms | 52 | <= 5 | trượt | 500 cấp dưới p50 36.51 ms, p99 146.37 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:manager_5000 | K | 104.9 ms | 51 | <= 5 | trượt | 4999 cấp dưới p50 46.38 ms, p99 115.65 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:own | K | 173.8 ms | 51 | <= 5 | trượt | p50 35.66 ms, p99 574.16 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:own_sort_slot | K | 124.5 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 36.83 ms, p99 627.30 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:public_read | K | 939.8 ms | 96 | <= 5 | trượt | p50 30.14 ms, p99 inf ms; 3 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction. dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:service_account | K | 123.4 ms | 52 | <= 5 | trượt | p50 31.85 ms, p99 681.40 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:share_recipient | K | 201.2 ms | 51 | <= 5 | trượt | p50 47.45 ms, p99 857.94 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:team | K | 95.35 ms | 51 | <= 5 | trượt | p50 34.72 ms, p99 115.11 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:team_sort_slot | K | 128.4 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 34.18 ms, p99 219.79 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:workspace_1 | K | 85.09 ms | 51 | <= 5 | trượt | p50 30.27 ms, p99 142.10 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:workspace_40 | K | 144.9 ms | 51 | <= 5 | trượt | 40 workspace p50 27.82 ms, p99 379.99 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:agent_one_object | K | 236.8 ms | 77 | <= 50 | trượt | p50 64.98 ms, p99 278.77 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:company | K | 111.3 ms | 95 | <= 50 | trượt | p50 51.25 ms, p99 998.55 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:company_name | K | 176.2 ms | 117 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 46.05 ms, p99 1019.74 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:company_updated | K | 119 ms | 100 | <= 50 | trượt | trang mới cập nhật p50 50.59 ms, p99 193.66 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:manager_50 | K | 569.3 ms | 52 | <= 50 | trượt | 50 cấp dưới p50 94.18 ms, p99 861.44 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:manager_500 | K | 4448 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 467.06 ms, p99 16960.90 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:manager_5000 | K | 2.165e+04 ms | 57 | <= 50 | trượt | 4999 cấp dưới p50 141.01 ms, p99 31448.75 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:own | K | 154.3 ms | 113 | <= 50 | trượt | p50 47.40 ms, p99 218.31 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:own_sort_slot | K | 137 ms | 113 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 45.27 ms, p99 195.96 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:public_read | K | 801 ms | 86 | <= 50 | trượt | p50 63.31 ms, p99 1588.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:service_account | K | 155.1 ms | 108 | <= 50 | trượt | p50 46.53 ms, p99 321.48 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:share_recipient | K | 2019 ms | 53 | <= 50 | trượt | p50 1154.15 ms, p99 4826.31 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:team | K | 321.9 ms | 51 | <= 50 | trượt | p50 110.94 ms, p99 2541.05 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:team_sort_slot | K | 315 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 106.04 ms, p99 491.74 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:workspace_1 | K | 623.7 ms | 52 | <= 50 | trượt | p50 105.58 ms, p99 928.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:workspace_40 | K | 2.393e+04 ms | 51 | <= 50 | trượt | 40 workspace p50 148.15 ms, p99 33538.40 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:agent_one_object | K | 206.3 ms | 63 | <= 50 | trượt | p50 75.02 ms, p99 332.78 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:company | K | 163.4 ms | 98 | <= 50 | trượt | p50 53.37 ms, p99 1269.50 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:company_name | K | 154.7 ms | 90 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 56.34 ms, p99 753.66 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:company_updated | K | 325.1 ms | 85 | <= 50 | trượt | trang mới cập nhật p50 56.72 ms, p99 1135.85 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:manager_50 | K | 555.4 ms | 58 | <= 50 | trượt | 50 cấp dưới p50 144.77 ms, p99 642.71 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:manager_500 | K | 919 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 293.94 ms, p99 1057.55 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:manager_5000 | K | 242.9 ms | 58 | <= 50 | trượt | 4999 cấp dưới p50 96.51 ms, p99 1286.52 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:own | K | 207.3 ms | 103 | <= 50 | trượt | p50 49.26 ms, p99 234.41 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:own_sort_slot | K | 117.3 ms | 108 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 47.48 ms, p99 178.81 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:public_read | K | inf ms | 138 | <= 50 | trượt | p50 48.57 ms, p99 inf ms; 9 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction. dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:service_account | K | 124.2 ms | 87 | <= 50 | trượt | p50 54.52 ms, p99 148.40 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:share_recipient | K | 3407 ms | 52 | <= 50 | trượt | p50 429.97 ms, p99 4973.60 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:team | K | 962.7 ms | 53 | <= 50 | trượt | p50 103.60 ms, p99 1537.05 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:team_sort_slot | K | 691.5 ms | 56 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 136.15 ms, p99 767.08 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:workspace_1 | K | 601.6 ms | 52 | <= 50 | trượt | p50 104.40 ms, p99 817.20 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:workspace_40 | K | 562 ms | 51 | <= 50 | trượt | 40 workspace p50 218.26 ms, p99 1136.70 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:agent_one_object | K | 1834 ms | 51 | <= 300 | trượt | p50 1235.70 ms, p99 1931.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:company | K | 1518 ms | 154 | <= 300 | trượt | p50 254.27 ms, p99 1915.58 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:company_name | K | 1001 ms | 223 | <= 300 | trượt | ORDER BY name "vi-VN-x-icu" p50 228.37 ms, p99 1447.28 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:company_updated | K | 1508 ms | 144 | <= 300 | trượt | trang mới cập nhật p50 245.78 ms, p99 1696.22 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:manager_50 | K | 3333 ms | 52 | <= 300 | trượt | 50 cấp dưới p50 1183.34 ms, p99 4263.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:manager_500 | K | 3.888e+04 ms | 54 | <= 300 | trượt | 500 cấp dưới p50 5104.76 ms, p99 43682.52 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:manager_5000 | K | 4.895e+04 ms | 55 | <= 300 | trượt | 4999 cấp dưới p50 11526.23 ms, p99 51368.56 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:own | K | 6417 ms | 52 | <= 300 | trượt | p50 2153.72 ms, p99 7140.02 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:own_sort_slot | K | 2930 ms | 51 | <= 300 | trượt | sắp theo slot t02, tầm hẹp p50 1654.67 ms, p99 3005.66 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:public_read | K | 1082 ms | 117 | <= 300 | trượt | p50 362.34 ms, p99 1294.67 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:service_account | K | 1601 ms | 148 | <= 300 | trượt | p50 243.51 ms, p99 2280.34 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:share_recipient | K | 6818 ms | 55 | <= 300 | trượt | p50 1759.48 ms, p99 7081.02 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:team | K | 3852 ms | 51 | <= 300 | trượt | p50 1274.13 ms, p99 6338.05 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:team_sort_slot | K | 5785 ms | 55 | <= 300 | trượt | sắp theo slot t02, tầm hẹp p50 1491.45 ms, p99 6704.92 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:workspace_1 | K | 5746 ms | 54 | <= 300 | trượt | p50 1409.37 ms, p99 5880.70 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:workspace_40 | K | 1.704e+04 ms | 60 | <= 300 | trượt | 40 workspace p50 7244.15 ms, p99 42811.85 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:agent_one_object | K | 1749 ms | 74 | <= 300 | trượt | p50 413.51 ms, p99 1846.94 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:company | K | 1208 ms | 151 | <= 300 | trượt | p50 246.89 ms, p99 1951.53 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:company_name | K | 1170 ms | 146 | <= 300 | trượt | ORDER BY name "vi-VN-x-icu" p50 271.55 ms, p99 1537.43 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:company_updated | K | 1104 ms | 153 | <= 300 | trượt | trang mới cập nhật p50 240.64 ms, p99 1422.71 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:manager_50 | K | 4546 ms | 51 | <= 300 | trượt | 50 cấp dưới p50 1079.78 ms, p99 5134.17 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:manager_500 | K | 4.174e+04 ms | 52 | <= 300 | trượt | 500 cấp dưới p50 8901.78 ms, p99 44683.22 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:manager_5000 | K | 3.675e+04 ms | 57 | <= 300 | trượt | 4999 cấp dưới p50 9839.79 ms, p99 42992.75 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:own | K | 8977 ms | 55 | <= 300 | trượt | p50 5777.98 ms, p99 10936.79 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:own_sort_slot | K | 7212 ms | 52 | <= 300 | trượt | sắp theo slot t02, tầm hẹp p50 1535.45 ms, p99 10755.51 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:public_read | K | 1094 ms | 127 | <= 300 | trượt | p50 334.60 ms, p99 inf ms; 2 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction. dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:service_account | K | 1260 ms | 147 | <= 300 | trượt | p50 260.03 ms, p99 1755.25 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:share_recipient | K | 9113 ms | 54 | <= 300 | trượt | p50 2622.18 ms, p99 10079.42 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:team | K | 8222 ms | 53 | <= 300 | trượt | p50 1740.99 ms, p99 8936.16 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:team_sort_slot | K | 7345 ms | 53 | <= 300 | trượt | sắp theo slot t02, tầm hẹp p50 2680.71 ms, p99 7603.81 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:workspace_1 | K | 5901 ms | 51 | <= 300 | trượt | p50 1094.16 ms, p99 6704.52 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:workspace_40 | K | 4.273e+04 ms | 52 | <= 300 | trượt | 40 workspace p50 5386.73 ms, p99 45022.87 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.6 | assign_p95 | K | 270.9 ms | 58 | <= 20 | trượt | p50 26.69 ms, p99 319.16 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.6 | share_p95 | K | 31.2 ms | 1000 |  | — | p50 19.49 ms, p99 124.48 ms |
| record-access:R9.7 | scope_compute:company | K | 26.74 ms | 1000 | <= 50 | đạt | p50 20.97 ms, p99 31.41 ms |
| record-access:R9.7 | scope_compute:manager_50 | K | 30.62 ms | 1000 | <= 50 | đạt | p50 24.12 ms, p99 36.25 ms |
| record-access:R9.7 | scope_compute:manager_500 | K | 33.89 ms | 1000 | <= 50 | đạt | p50 26.31 ms, p99 40.23 ms |
| record-access:R9.7 | scope_compute:manager_5000 | K | 55.78 ms | 1000 | <= 50 | trượt | p50 30.70 ms, p99 63.16 ms |
| record-access:R9.7 | scope_compute:own | K | 25.52 ms | 1000 | <= 50 | đạt | p50 20.21 ms, p99 31.14 ms |
| record-access:R9.7 | scope_compute:public_read | K | 24.03 ms | 1000 | <= 50 | đạt | p50 19.00 ms, p99 29.17 ms |
| record-access:R9.7 | scope_compute:service_account | K | 27.1 ms | 1000 | <= 50 | đạt | p50 21.42 ms, p99 31.82 ms |
| record-access:R9.7 | scope_compute:share_recipient | K | 24.62 ms | 1000 | <= 50 | đạt | p50 18.91 ms, p99 29.15 ms |
| record-access:R9.7 | scope_compute:team | K | 25.69 ms | 1000 | <= 50 | đạt | p50 20.14 ms, p99 31.26 ms |
| record-access:R9.7 | scope_compute:workspace_1 | K | 25.16 ms | 1000 | <= 50 | đạt | p50 19.60 ms, p99 30.64 ms |
| record-access:R9.7 | scope_compute:workspace_40 | K | 42.98 ms | 1000 | <= 50 | đạt | p50 32.46 ms, p99 48.40 ms |
| record-access:R9.8 | door_valid_p95 | K | 0.982 ms | 1000 | <= 1 | đạt | p50 0.74 ms, p99 1.16 ms; một vòng khứ hồi, trong giao dịch đã gắn setting |
| record-access:R9.9 | recompute_total_1 | K | 268.1 s |  |  | — | 1 kết nối, 5000 chủ thể, 5000 dòng valid ở epoch mới, dưới tải hỗn hợp; 2479 lời gọi cửa bị máy chủ từ chối dưới tải, gọi lại sau tải (đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction.) |
| record-access:R9.9 | recompute_total_4 | K | 93.78 s |  | <= 120 | đạt | 4 kết nối, 5000 chủ thể, 5000 dòng valid ở epoch mới, dưới tải hỗn hợp |
| record-access:R9.9 | stale_reads_after_revoke | K | 0 lần | 1000 | <= 0 | đạt | 1000 lần lặp trên hai kết nối; câu lệnh trước thu hồi thấy tầm 1000 lần |
| record-access:bước 5 | delete_p95 | K | 25.74 ms | 1000 |  | — | p50 20.47 ms, p99 99.26 ms |
| record-access:R9.1 | page_lead_cold:agent_one_object | L | 122.9 ms | 129 | <= 50 | trượt | p50 46.39 ms, p99 151.90 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:company | L | 106.5 ms | 145 | <= 50 | trượt | p50 44.32 ms, p99 966.14 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:company_name | L | 126.9 ms | 83 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 55.02 ms, p99 191.67 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:company_updated | L | 218.9 ms | 70 | <= 50 | trượt | trang mới cập nhật p50 67.16 ms, p99 894.66 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:manager_50 | L | 1182 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 555.99 ms, p99 3344.02 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:manager_500 | L | 3.29e+04 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 6048.10 ms, p99 34613.52 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:manager_5000 | L | 5.084e+04 ms | 58 | <= 50 | trượt | 4999 cấp dưới p50 21412.72 ms, p99 55213.30 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:own | L | 148.6 ms | 86 | <= 50 | trượt | p50 57.87 ms, p99 207.66 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:own_sort_slot | L | 149.1 ms | 92 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 55.37 ms, p99 240.10 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:public_read | L | 924.6 ms | 105 | <= 50 | trượt | p50 68.84 ms, p99 1150.04 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:service_account | L | 91.87 ms | 128 | <= 50 | trượt | p50 46.05 ms, p99 113.71 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:share_recipient | L | 8467 ms | 54 | <= 50 | trượt | p50 4992.46 ms, p99 8646.83 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:team | L | 981.8 ms | 51 | <= 50 | trượt | p50 586.39 ms, p99 3336.48 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:team_sort_slot | L | 955.2 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 478.04 ms, p99 2407.90 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:workspace_1 | L | 1634 ms | 51 | <= 50 | trượt | p50 737.35 ms, p99 2101.63 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:workspace_40 | L | 3.946e+04 ms | 58 | <= 50 | trượt | 40 workspace p50 11542.42 ms, p99 40615.68 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:agent_one_object | L | 2288 ms | 52 | <= 50 | trượt | p50 1164.23 ms, p99 2657.22 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:company | L | 2371 ms | 51 | <= 50 | trượt | p50 937.35 ms, p99 2508.48 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:company_name | L | 2269 ms | 52 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 1297.63 ms, p99 2805.83 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:company_updated | L | 2353 ms | 52 | <= 50 | trượt | trang mới cập nhật p50 1251.28 ms, p99 4280.79 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:manager_50 | L | 2735 ms | 52 | <= 50 | trượt | 50 cấp dưới p50 1215.87 ms, p99 4271.95 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:manager_500 | L | 2.991e+04 ms | 54 | <= 50 | trượt | 500 cấp dưới p50 6733.93 ms, p99 34126.94 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:manager_5000 | L | 4.411e+04 ms | 71 | <= 50 | trượt | 4999 cấp dưới p50 22834.43 ms, p99 49489.59 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:own | L | 152.4 ms | 128 | <= 50 | trượt | p50 42.35 ms, p99 196.87 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:own_sort_slot | L | 140.9 ms | 102 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 49.20 ms, p99 240.36 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:public_read | L | 6623 ms | 68 | <= 50 | trượt | p50 921.89 ms, p99 6636.61 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:service_account | L | 2570 ms | 53 | <= 50 | trượt | p50 1203.39 ms, p99 4276.95 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:share_recipient | L | 1476 ms | 51 | <= 50 | trượt | p50 957.58 ms, p99 1737.98 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:team | L | 1937 ms | 51 | <= 50 | trượt | p50 1065.90 ms, p99 4268.09 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:team_sort_slot | L | 1548 ms | 52 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 846.29 ms, p99 1852.27 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:workspace_1 | L | 3392 ms | 51 | <= 50 | trượt | p50 777.74 ms, p99 4269.81 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:workspace_40 | L | 3.635e+04 ms | 51 | <= 50 | trượt | 40 workspace p50 18905.56 ms, p99 38306.51 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:agent_one_object | L | 2267 ms | 52 | <= 50 | trượt | p50 1222.83 ms, p99 2576.91 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:company | L | 2341 ms | 51 | <= 50 | trượt | p50 1047.75 ms, p99 3392.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:company_name | L | 2350 ms | 51 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 805.35 ms, p99 2386.03 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:company_updated | L | 2152 ms | 52 | <= 50 | trượt | trang mới cập nhật p50 894.37 ms, p99 2284.87 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:manager_50 | L | 1827 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 942.05 ms, p99 1935.98 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:manager_500 | L | 3.175e+04 ms | 54 | <= 50 | trượt | 500 cấp dưới p50 6985.27 ms, p99 33510.39 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:manager_5000 | L | 4.81e+04 ms | 89 | <= 50 | trượt | 4999 cấp dưới p50 24107.97 ms, p99 59012.74 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:own | L | 135.3 ms | 113 | <= 50 | trượt | p50 47.77 ms, p99 197.80 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:own_sort_slot | L | 144.6 ms | 101 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 50.60 ms, p99 316.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:public_read | L | inf ms | 123 | <= 50 | trượt | p50 647.04 ms, p99 inf ms; 11 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction. dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:service_account | L | 2213 ms | 52 | <= 50 | trượt | p50 1236.63 ms, p99 2740.40 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:share_recipient | L | 1520 ms | 53 | <= 50 | trượt | p50 1031.36 ms, p99 1866.80 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:team | L | 1394 ms | 51 | <= 50 | trượt | p50 659.75 ms, p99 1620.48 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:team_sort_slot | L | 1905 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 927.10 ms, p99 2208.27 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:workspace_1 | L | 1615 ms | 51 | <= 50 | trượt | p50 1013.03 ms, p99 1843.39 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:workspace_40 | L | 4.198e+04 ms | 63 | <= 50 | trượt | 40 workspace p50 13250.26 ms, p99 45414.19 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:agent_one_object | L | 104.2 ms | 118 | <= 50 | trượt | p50 47.53 ms, p99 219.90 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:company | L | 129.5 ms | 116 | <= 50 | trượt | p50 44.92 ms, p99 323.43 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:company_name | L | 182 ms | 88 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 54.82 ms, p99 646.42 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:company_updated | L | 184.4 ms | 75 | <= 50 | trượt | trang mới cập nhật p50 63.86 ms, p99 985.17 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:manager_50 | L | 1017 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 617.49 ms, p99 1035.80 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:manager_500 | L | 2.906e+04 ms | 54 | <= 50 | trượt | 500 cấp dưới p50 6062.63 ms, p99 41020.81 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:manager_5000 | L | 4.923e+04 ms | 63 | <= 50 | trượt | 4999 cấp dưới p50 22197.48 ms, p99 inf ms; 2 lỗi, đầu: QueryCanceledError: canceling statement due to statement timeout dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:own | L | 178.7 ms | 92 | <= 50 | trượt | p50 56.12 ms, p99 207.94 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:own_sort_slot | L | 159.6 ms | 78 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 64.26 ms, p99 827.67 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:public_read | L | inf ms | 152 | <= 50 | trượt | p50 63.13 ms, p99 inf ms; 11 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction. dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:service_account | L | 127.7 ms | 135 | <= 50 | trượt | p50 45.59 ms, p99 915.08 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:share_recipient | L | 9298 ms | 54 | <= 50 | trượt | p50 3476.61 ms, p99 12570.90 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:team | L | 1207 ms | 51 | <= 50 | trượt | p50 648.86 ms, p99 1341.55 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:team_sort_slot | L | 1001 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 529.53 ms, p99 1122.36 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:workspace_1 | L | 1323 ms | 51 | <= 50 | trượt | p50 608.41 ms, p99 1368.26 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:workspace_40 | L | 4.844e+04 ms | 53 | <= 50 | trượt | 40 workspace p50 10869.07 ms, p99 49862.79 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:agent_one_object | L | 1579 ms | 51 | <= 50 | trượt | p50 775.14 ms, p99 3203.44 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:company | L | 95.04 ms | 136 | <= 50 | trượt | p50 45.09 ms, p99 132.05 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:company_name | L | 160.8 ms | 92 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 55.48 ms, p99 988.11 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:company_updated | L | 116 ms | 89 | <= 50 | trượt | trang mới cập nhật p50 54.29 ms, p99 221.56 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:manager_50 | L | 779 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 214.74 ms, p99 1389.85 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:manager_500 | L | 1143 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 226.79 ms, p99 1341.02 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:manager_5000 | L | 288.9 ms | 53 | <= 50 | trượt | 4999 cấp dưới p50 100.69 ms, p99 789.65 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:own | L | 102.7 ms | 115 | <= 50 | trượt | p50 46.89 ms, p99 165.27 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:own_sort_slot | L | 158.3 ms | 109 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 49.42 ms, p99 475.12 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:public_read | L | 5625 ms | 60 | <= 50 | trượt | p50 687.42 ms, p99 5631.95 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:service_account | L | 101.2 ms | 144 | <= 50 | trượt | p50 43.02 ms, p99 748.59 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:share_recipient | L | 1887 ms | 52 | <= 50 | trượt | p50 916.77 ms, p99 3755.52 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:team | L | 2117 ms | 51 | <= 50 | trượt | p50 449.70 ms, p99 3595.38 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:team_sort_slot | L | 1521 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 826.18 ms, p99 2273.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:workspace_1 | L | 878.3 ms | 51 | <= 50 | trượt | p50 300.99 ms, p99 919.35 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:workspace_40 | L | 699 ms | 51 | <= 50 | trượt | 40 workspace p50 194.96 ms, p99 1048.43 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:agent_one_object | L | 340.2 ms | 72 | <= 50 | trượt | p50 94.42 ms, p99 1796.36 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:company | L | 355.5 ms | 55 | <= 50 | trượt | p50 130.65 ms, p99 1803.70 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:company_name | L | 313.3 ms | 56 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 132.90 ms, p99 336.65 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:company_updated | L | 305.1 ms | 56 | <= 50 | trượt | trang mới cập nhật p50 116.76 ms, p99 360.14 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:manager_50 | L | 315.1 ms | 70 | <= 50 | trượt | 50 cấp dưới p50 91.65 ms, p99 2046.30 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:manager_500 | L | 2485 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 630.50 ms, p99 3011.57 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:manager_5000 | L | 2950 ms | 52 | <= 50 | trượt | 4999 cấp dưới p50 1645.47 ms, p99 3627.69 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:own | L | 135.2 ms | 236 | <= 50 | trượt | p50 25.46 ms, p99 212.68 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:own_sort_slot | L | 145.4 ms | 177 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 33.47 ms, p99 328.47 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:public_read | L | 1539 ms | 97 | <= 50 | trượt | p50 73.34 ms, p99 2028.81 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:service_account | L | 518.3 ms | 57 | <= 50 | trượt | p50 111.03 ms, p99 1222.61 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:share_recipient | L | 914.8 ms | 73 | <= 50 | trượt | p50 92.27 ms, p99 1796.72 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:team | L | 284 ms | 65 | <= 50 | trượt | p50 76.64 ms, p99 932.62 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:team_sort_slot | L | 298.1 ms | 57 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 104.86 ms, p99 361.17 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:workspace_1 | L | 282.8 ms | 62 | <= 50 | trượt | p50 129.20 ms, p99 493.37 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:workspace_40 | L | 2494 ms | 51 | <= 50 | trượt | 40 workspace p50 926.76 ms, p99 3864.97 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:agent_one_object | L | 179.1 ms | 91 | <= 50 | trượt | p50 61.06 ms, p99 468.01 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:company | L | 1113 ms | 56 | <= 50 | trượt | p50 117.59 ms, p99 1828.36 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:company_name | L | 405 ms | 54 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 140.89 ms, p99 947.08 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:company_updated | L | 297.5 ms | 57 | <= 50 | trượt | trang mới cập nhật p50 117.16 ms, p99 338.09 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:manager_50 | L | 209.5 ms | 64 | <= 50 | trượt | 50 cấp dưới p50 88.55 ms, p99 1697.59 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:manager_500 | L | 2525 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 516.38 ms, p99 3298.92 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:manager_5000 | L | 3366 ms | 51 | <= 50 | trượt | 4999 cấp dưới p50 1806.60 ms, p99 5413.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:own | L | 127.1 ms | 286 | <= 50 | trượt | p50 30.03 ms, p99 334.21 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:own_sort_slot | L | 189.4 ms | 232 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 30.77 ms, p99 277.74 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:public_read | L | inf ms | 130 | <= 50 | trượt | p50 87.06 ms, p99 inf ms; 12 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction. dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:service_account | L | 382.8 ms | 67 | <= 50 | trượt | p50 138.55 ms, p99 497.17 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:share_recipient | L | 261.3 ms | 68 | <= 50 | trượt | p50 100.97 ms, p99 905.24 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:team | L | 267.9 ms | 67 | <= 50 | trượt | p50 114.25 ms, p99 454.49 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:team_sort_slot | L | 303.5 ms | 61 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 114.23 ms, p99 445.49 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:workspace_1 | L | 306.6 ms | 62 | <= 50 | trượt | p50 87.46 ms, p99 914.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:workspace_40 | L | 3786 ms | 52 | <= 50 | trượt | 40 workspace p50 1008.96 ms, p99 4193.52 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:agent_one_object | L | 1505 ms | 52 | <= 50 | trượt | p50 978.73 ms, p99 1659.06 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:company | L | 102.6 ms | 119 | <= 50 | trượt | p50 45.46 ms, p99 166.11 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:company_name | L | 212.7 ms | 98 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 53.43 ms, p99 912.96 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:company_updated | L | 179.7 ms | 92 | <= 50 | trượt | trang mới cập nhật p50 54.99 ms, p99 756.64 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:manager_50 | L | 710.3 ms | 52 | <= 50 | trượt | 50 cấp dưới p50 369.44 ms, p99 814.36 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:manager_500 | L | 1035 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 257.54 ms, p99 1448.42 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:manager_5000 | L | 250.5 ms | 56 | <= 50 | trượt | 4999 cấp dưới p50 112.47 ms, p99 432.27 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:own | L | 155.7 ms | 112 | <= 50 | trượt | p50 46.66 ms, p99 206.32 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:own_sort_slot | L | 188.2 ms | 120 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 45.20 ms, p99 274.29 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:public_read | L | inf ms | 127 | <= 50 | trượt | p50 530.45 ms, p99 inf ms; 15 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction. dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:service_account | L | 131.9 ms | 120 | <= 50 | trượt | p50 43.64 ms, p99 224.58 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:share_recipient | L | 1608 ms | 51 | <= 50 | trượt | p50 633.75 ms, p99 2077.47 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:team | L | 1086 ms | 51 | <= 50 | trượt | p50 476.10 ms, p99 1244.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:team_sort_slot | L | 1382 ms | 53 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 854.72 ms, p99 1793.49 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:workspace_1 | L | 949.7 ms | 53 | <= 50 | trượt | p50 280.09 ms, p99 1328.23 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:workspace_40 | L | 460.5 ms | 53 | <= 50 | trượt | 40 workspace p50 190.78 ms, p99 859.64 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:agent_one_object | L | 104 ms | 51 | <= 5 | trượt | p50 36.71 ms, p99 306.10 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:company | L | 751 ms | 51 | <= 5 | trượt | p50 29.79 ms, p99 987.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:company_name | L | 188.9 ms | 51 | <= 5 | trượt | ORDER BY name "vi-VN-x-icu" p50 37.86 ms, p99 251.91 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:company_updated | L | 65.77 ms | 51 | <= 5 | trượt | trang mới cập nhật p50 28.61 ms, p99 1099.69 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:manager_50 | L | 312.9 ms | 51 | <= 5 | trượt | 50 cấp dưới p50 41.25 ms, p99 1207.06 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:manager_500 | L | 428.2 ms | 51 | <= 5 | trượt | 500 cấp dưới p50 48.71 ms, p99 910.04 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:manager_5000 | L | 333.4 ms | 51 | <= 5 | trượt | 4999 cấp dưới p50 55.17 ms, p99 941.12 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:own | L | 122.5 ms | 51 | <= 5 | trượt | p50 41.01 ms, p99 171.39 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:own_sort_slot | L | 163.3 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 41.71 ms, p99 1651.84 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:public_read | L | 814.7 ms | 53 | <= 5 | trượt | p50 28.14 ms, p99 830.72 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:service_account | L | 123.9 ms | 51 | <= 5 | trượt | p50 27.64 ms, p99 766.94 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:share_recipient | L | 135 ms | 51 | <= 5 | trượt | p50 39.95 ms, p99 394.56 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:team | L | 91.1 ms | 51 | <= 5 | trượt | p50 34.64 ms, p99 110.36 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:team_sort_slot | L | 103.4 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 41.18 ms, p99 1097.56 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:workspace_1 | L | 248 ms | 51 | <= 5 | trượt | p50 35.32 ms, p99 816.82 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:workspace_40 | L | 105.2 ms | 51 | <= 5 | trượt | 40 workspace p50 34.99 ms, p99 139.66 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:agent_one_object | L | 150.1 ms | 51 | <= 5 | trượt | p50 35.67 ms, p99 548.44 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:company | L | 187 ms | 52 | <= 5 | trượt | p50 35.63 ms, p99 247.23 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:company_name | L | 134 ms | 51 | <= 5 | trượt | ORDER BY name "vi-VN-x-icu" p50 32.43 ms, p99 834.29 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:company_updated | L | 197.4 ms | 51 | <= 5 | trượt | trang mới cập nhật p50 28.13 ms, p99 655.28 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:manager_50 | L | 210.9 ms | 52 | <= 5 | trượt | 50 cấp dưới p50 47.48 ms, p99 769.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:manager_500 | L | 119.6 ms | 51 | <= 5 | trượt | 500 cấp dưới p50 43.98 ms, p99 346.05 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:manager_5000 | L | 93.51 ms | 52 | <= 5 | trượt | 4999 cấp dưới p50 45.34 ms, p99 120.13 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:own | L | 100.3 ms | 52 | <= 5 | trượt | p50 33.48 ms, p99 1011.35 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:own_sort_slot | L | 170.1 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 39.92 ms, p99 936.04 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:public_read | L | 768.5 ms | 93 | <= 5 | trượt | p50 41.82 ms, p99 inf ms; 2 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction. dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:service_account | L | 376.5 ms | 54 | <= 5 | trượt | p50 36.05 ms, p99 778.98 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:share_recipient | L | 101.4 ms | 53 | <= 5 | trượt | p50 46.40 ms, p99 1086.28 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:team | L | 188 ms | 53 | <= 5 | trượt | p50 44.18 ms, p99 230.30 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:team_sort_slot | L | 181.3 ms | 52 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 39.37 ms, p99 360.66 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:workspace_1 | L | 102.8 ms | 51 | <= 5 | trượt | p50 35.70 ms, p99 153.75 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:workspace_40 | L | 209.1 ms | 51 | <= 5 | trượt | 40 workspace p50 43.18 ms, p99 330.19 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:agent_one_object | L | 137.7 ms | 113 | <= 50 | trượt | p50 49.05 ms, p99 247.37 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:company | L | 112.1 ms | 112 | <= 50 | trượt | p50 49.28 ms, p99 215.44 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:company_name | L | 111.5 ms | 117 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 45.90 ms, p99 309.33 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:company_updated | L | 103.1 ms | 120 | <= 50 | trượt | trang mới cập nhật p50 46.91 ms, p99 143.87 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:manager_50 | L | 615 ms | 52 | <= 50 | trượt | 50 cấp dưới p50 185.46 ms, p99 757.37 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:manager_500 | L | 1.792e+04 ms | 53 | <= 50 | trượt | 500 cấp dưới p50 457.75 ms, p99 32373.90 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:manager_5000 | L | 1.616e+04 ms | 53 | <= 50 | trượt | 4999 cấp dưới p50 114.95 ms, p99 21765.30 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:own | L | 143.7 ms | 109 | <= 50 | trượt | p50 51.68 ms, p99 164.50 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:own_sort_slot | L | 143.2 ms | 85 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 56.44 ms, p99 176.83 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:public_read | L | 955 ms | 83 | <= 50 | trượt | p50 63.63 ms, p99 1240.33 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:service_account | L | 107 ms | 127 | <= 50 | trượt | p50 45.99 ms, p99 833.16 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:share_recipient | L | 7559 ms | 54 | <= 50 | trượt | p50 4008.36 ms, p99 9770.30 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:team | L | 752.4 ms | 51 | <= 50 | trượt | p50 301.03 ms, p99 861.11 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:team_sort_slot | L | 779 ms | 52 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 303.84 ms, p99 839.51 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:workspace_1 | L | 818.5 ms | 52 | <= 50 | trượt | p50 279.41 ms, p99 2492.35 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:workspace_40 | L | 1.289e+04 ms | 52 | <= 50 | trượt | 40 workspace p50 272.88 ms, p99 29926.35 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:agent_one_object | L | 135.2 ms | 105 | <= 50 | trượt | p50 50.87 ms, p99 192.49 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:company | L | 101.6 ms | 121 | <= 50 | trượt | p50 44.89 ms, p99 199.64 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:company_name | L | 159.6 ms | 117 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 45.64 ms, p99 314.62 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:company_updated | L | 162.7 ms | 116 | <= 50 | trượt | trang mới cập nhật p50 45.44 ms, p99 1073.50 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:manager_50 | L | 574.9 ms | 52 | <= 50 | trượt | 50 cấp dưới p50 158.60 ms, p99 756.72 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:manager_500 | L | 1475 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 257.18 ms, p99 1611.81 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:manager_5000 | L | 359.6 ms | 54 | <= 50 | trượt | 4999 cấp dưới p50 95.51 ms, p99 966.11 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:own | L | 132.9 ms | 89 | <= 50 | trượt | p50 54.77 ms, p99 226.07 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:own_sort_slot | L | 131.4 ms | 114 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 45.75 ms, p99 294.80 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:public_read | L | 508.6 ms | 138 | <= 50 | trượt | p50 55.01 ms, p99 949.15 ms; 1 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction. dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:service_account | L | 111.3 ms | 110 | <= 50 | trượt | p50 46.75 ms, p99 188.86 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:share_recipient | L | 3677 ms | 52 | <= 50 | trượt | p50 724.26 ms, p99 5453.27 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:team | L | 701.1 ms | 51 | <= 50 | trượt | p50 190.84 ms, p99 1425.49 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:team_sort_slot | L | 665 ms | 55 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 292.21 ms, p99 840.46 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:workspace_1 | L | 767.7 ms | 52 | <= 50 | trượt | p50 205.84 ms, p99 1178.13 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:workspace_40 | L | 741.7 ms | 51 | <= 50 | trượt | 40 workspace p50 230.99 ms, p99 1818.22 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:agent_one_object | L | 104 ms | 1000 | <= 300 | đạt | p50 52.13 ms, p99 276.82 ms |
| record-access:R9.4 | count_cold:company | L | 105.7 ms | 1000 | <= 300 | đạt | p50 48.57 ms, p99 228.48 ms |
| record-access:R9.4 | count_cold:company_name | L | 114.5 ms | 1000 | <= 300 | đạt | ORDER BY name "vi-VN-x-icu" p50 49.56 ms, p99 321.72 ms |
| record-access:R9.4 | count_cold:company_updated | L | 104.3 ms | 1000 | <= 300 | đạt | trang mới cập nhật p50 48.43 ms, p99 287.32 ms |
| record-access:R9.4 | count_cold:manager_50 | L | 4771 ms | 51 | <= 300 | trượt | 50 cấp dưới p50 2839.24 ms, p99 5349.29 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:manager_500 | L | 1.746e+04 ms | 52 | <= 300 | trượt | 500 cấp dưới p50 9285.60 ms, p99 48226.63 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:manager_5000 | L | 3.117e+04 ms | 81 | <= 300 | trượt | 4999 cấp dưới p50 22288.75 ms, p99 49173.58 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:own | L | 9707 ms | 55 | <= 300 | trượt | p50 6158.83 ms, p99 9817.94 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:own_sort_slot | L | 9715 ms | 59 | <= 300 | trượt | sắp theo slot t02, tầm hẹp p50 5479.60 ms, p99 11172.81 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:public_read | L | 1152 ms | 113 | <= 300 | trượt | p50 406.55 ms, p99 1179.36 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:service_account | L | 109.4 ms | 1000 | <= 300 | đạt | p50 48.36 ms, p99 288.18 ms |
| record-access:R9.4 | count_cold:share_recipient | L | 8684 ms | 54 | <= 300 | trượt | p50 5330.77 ms, p99 10135.66 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:team | L | 7275 ms | 55 | <= 300 | trượt | p50 3845.95 ms, p99 8145.53 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:team_sort_slot | L | 8142 ms | 56 | <= 300 | trượt | sắp theo slot t02, tầm hẹp p50 5103.98 ms, p99 9502.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:workspace_1 | L | 7011 ms | 53 | <= 300 | trượt | p50 3087.71 ms, p99 7283.14 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:workspace_40 | L | 1.822e+04 ms | 56 | <= 300 | trượt | 40 workspace p50 11546.06 ms, p99 38896.22 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:agent_one_object | L | 104.7 ms | 1002 | <= 300 | đạt | p50 71.44 ms, p99 316.25 ms |
| record-access:R9.4 | count_warm:company | L | 109.4 ms | 1011 | <= 300 | đạt | p50 69.53 ms, p99 281.24 ms |
| record-access:R9.4 | count_warm:company_name | L | 110.6 ms | 1006 | <= 300 | đạt | ORDER BY name "vi-VN-x-icu" p50 69.81 ms, p99 275.47 ms |
| record-access:R9.4 | count_warm:company_updated | L | 105.5 ms | 1026 | <= 300 | đạt | trang mới cập nhật p50 69.12 ms, p99 275.59 ms |
| record-access:R9.4 | count_warm:manager_50 | L | 4607 ms | 52 | <= 300 | trượt | 50 cấp dưới p50 2598.15 ms, p99 5654.13 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:manager_500 | L | 2.447e+04 ms | 55 | <= 300 | trượt | 500 cấp dưới p50 11862.09 ms, p99 inf ms; 1 lỗi, đầu: QueryCanceledError: canceling statement due to statement timeout dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:manager_5000 | L | 2.857e+04 ms | 60 | <= 300 | trượt | 4999 cấp dưới p50 18450.06 ms, p99 56901.15 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:own | L | 9095 ms | 56 | <= 300 | trượt | p50 6408.96 ms, p99 12455.57 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:own_sort_slot | L | 8714 ms | 53 | <= 300 | trượt | sắp theo slot t02, tầm hẹp p50 3147.26 ms, p99 9336.65 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:public_read | L | 1058 ms | 118 | <= 300 | trượt | p50 347.79 ms, p99 inf ms; 2 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction. dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:service_account | L | 103.7 ms | 1013 | <= 300 | đạt | p50 69.50 ms, p99 196.03 ms |
| record-access:R9.4 | count_warm:share_recipient | L | 8329 ms | 55 | <= 300 | trượt | p50 5621.69 ms, p99 10760.38 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:team | L | 7658 ms | 55 | <= 300 | trượt | p50 4349.47 ms, p99 9867.49 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:team_sort_slot | L | 7977 ms | 54 | <= 300 | trượt | sắp theo slot t02, tầm hẹp p50 4772.85 ms, p99 9185.05 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:workspace_1 | L | 6346 ms | 53 | <= 300 | trượt | p50 2000.57 ms, p99 8231.91 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:workspace_40 | L | 4.836e+04 ms | 52 | <= 300 | trượt | 40 workspace p50 8523.24 ms, p99 55906.16 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.6 | assign_p95 | L | 309.7 ms | 58 | <= 20 | trượt | p50 29.71 ms, p99 351.48 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.6 | share_p95 | L | 33.75 ms | 1000 |  | — | p50 20.82 ms, p99 146.12 ms |
| record-access:R9.7 | scope_compute:company | L | 25.91 ms | 1000 | <= 50 | đạt | p50 20.71 ms, p99 31.01 ms |
| record-access:R9.7 | scope_compute:manager_50 | L | 31.31 ms | 1000 | <= 50 | đạt | p50 24.52 ms, p99 37.48 ms |
| record-access:R9.7 | scope_compute:manager_500 | L | 34.64 ms | 1000 | <= 50 | đạt | p50 27.05 ms, p99 40.23 ms |
| record-access:R9.7 | scope_compute:manager_5000 | L | 60.48 ms | 1000 | <= 50 | trượt | p50 38.65 ms, p99 77.10 ms |
| record-access:R9.7 | scope_compute:own | L | 25.71 ms | 1000 | <= 50 | đạt | p50 20.33 ms, p99 31.24 ms |
| record-access:R9.7 | scope_compute:public_read | L | 24 ms | 1000 | <= 50 | đạt | p50 19.00 ms, p99 30.45 ms |
| record-access:R9.7 | scope_compute:service_account | L | 27.08 ms | 1000 | <= 50 | đạt | p50 21.27 ms, p99 30.61 ms |
| record-access:R9.7 | scope_compute:share_recipient | L | 23.93 ms | 1000 | <= 50 | đạt | p50 18.96 ms, p99 29.13 ms |
| record-access:R9.7 | scope_compute:team | L | 25.73 ms | 1000 | <= 50 | đạt | p50 20.39 ms, p99 30.12 ms |
| record-access:R9.7 | scope_compute:workspace_1 | L | 24.45 ms | 1000 | <= 50 | đạt | p50 19.48 ms, p99 29.28 ms |
| record-access:R9.7 | scope_compute:workspace_40 | L | 43.9 ms | 1000 | <= 50 | đạt | p50 34.36 ms, p99 58.78 ms |
| record-access:R9.8 | door_valid_p95 | L | 1.304 ms | 1000 | <= 1 | trượt | p50 0.90 ms, p99 1.52 ms; một vòng khứ hồi, trong giao dịch đã gắn setting |
| record-access:R9.9 | recompute_total_1 | L | 377.8 s |  |  | — | 1 kết nối, 5000 chủ thể, 5000 dòng valid ở epoch mới, dưới tải hỗn hợp |
| record-access:R9.9 | recompute_total_4 | L | 90.64 s |  | <= 120 | đạt | 4 kết nối, 5000 chủ thể, 5000 dòng valid ở epoch mới, dưới tải hỗn hợp |
| record-access:R9.9 | stale_reads_after_revoke | L | 0 lần | 1000 | <= 0 | đạt | 1000 lần lặp trên hai kết nối; câu lệnh trước thu hồi thấy tầm 1000 lần |
| record-access:bước 5 | delete_p95 | L | 28.3 ms | 1000 |  | — | p50 21.10 ms, p99 131.66 ms |
| record-access:R9.1 | page_lead_cold:agent_one_object | P0 | 1918 ms | 60 | <= 50 | trượt | p50 102.25 ms, p99 2790.77 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:company | P0 | 308.4 ms | 85 | <= 50 | trượt | p50 63.18 ms, p99 1711.03 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:company_name | P0 | 233.9 ms | 55 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 92.79 ms, p99 566.82 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:company_updated | P0 | 331.5 ms | 52 | <= 50 | trượt | trang mới cập nhật p50 118.70 ms, p99 1306.41 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:manager_50 | P0 | 2291 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 433.11 ms, p99 4233.83 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:manager_500 | P0 | 2.973e+04 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 7309.02 ms, p99 31876.30 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:manager_5000 | P0 | 4.825e+04 ms | 58 | <= 50 | trượt | 4999 cấp dưới p50 24082.77 ms, p99 53115.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:own | P0 | 152.6 ms | 99 | <= 50 | trượt | p50 52.38 ms, p99 299.18 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:own_sort_slot | P0 | 152.4 ms | 89 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 55.11 ms, p99 292.48 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:public_read | P0 | 1104 ms | 123 | <= 50 | trượt | p50 86.52 ms, p99 1701.66 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:service_account | P0 | 269.8 ms | 76 | <= 50 | trượt | p50 66.75 ms, p99 1402.34 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:share_recipient | P0 | 9897 ms | 54 | <= 50 | trượt | p50 5029.74 ms, p99 10050.06 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:team | P0 | 1457 ms | 51 | <= 50 | trượt | p50 483.94 ms, p99 4060.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:team_sort_slot | P0 | 1414 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 343.56 ms, p99 3630.26 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:workspace_1 | P0 | 2298 ms | 51 | <= 50 | trượt | p50 661.89 ms, p99 4187.69 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:workspace_40 | P0 | 3.375e+04 ms | 58 | <= 50 | trượt | 40 workspace p50 12134.84 ms, p99 38136.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:agent_one_object | P0 | 2.954e+04 ms | 53 | <= 50 | trượt | p50 18698.55 ms, p99 30123.90 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:company | P0 | 2.768e+04 ms | 53 | <= 50 | trượt | p50 7914.89 ms, p99 28605.89 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:company_name | P0 | 2.895e+04 ms | 55 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 12734.82 ms, p99 30089.14 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:company_updated | P0 | 2.887e+04 ms | 52 | <= 50 | trượt | trang mới cập nhật p50 17723.64 ms, p99 29271.09 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:manager_50 | P0 | 2242 ms | 52 | <= 50 | trượt | 50 cấp dưới p50 1221.20 ms, p99 6218.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:manager_500 | P0 | 2.589e+04 ms | 54 | <= 50 | trượt | 500 cấp dưới p50 8813.34 ms, p99 30240.32 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:manager_5000 | P0 | 4.414e+04 ms | 66 | <= 50 | trượt | 4999 cấp dưới p50 23108.76 ms, p99 52547.57 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:own | P0 | 184.9 ms | 99 | <= 50 | trượt | p50 51.21 ms, p99 261.34 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:own_sort_slot | P0 | 127.7 ms | 167 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 37.81 ms, p99 237.74 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:public_read | P0 | 7312 ms | 71 | <= 50 | trượt | p50 999.96 ms, p99 7392.80 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:service_account | P0 | 2.698e+04 ms | 54 | <= 50 | trượt | p50 6945.93 ms, p99 30570.47 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:share_recipient | P0 | 2081 ms | 51 | <= 50 | trượt | p50 790.08 ms, p99 2150.91 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:team | P0 | 2199 ms | 51 | <= 50 | trượt | p50 944.42 ms, p99 6231.35 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:team_sort_slot | P0 | 1983 ms | 52 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 654.20 ms, p99 2354.95 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:workspace_1 | P0 | 5168 ms | 51 | <= 50 | trượt | p50 601.74 ms, p99 6236.06 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:workspace_40 | P0 | 3.23e+04 ms | 51 | <= 50 | trượt | 40 workspace p50 17996.69 ms, p99 35339.10 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:agent_one_object | P0 | 3.03e+04 ms | 53 | <= 50 | trượt | p50 18295.62 ms, p99 31415.41 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:company | P0 | 2.568e+04 ms | 53 | <= 50 | trượt | p50 6382.25 ms, p99 32279.12 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:company_name | P0 | 2.962e+04 ms | 52 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 21563.63 ms, p99 30635.02 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:company_updated | P0 | 2.927e+04 ms | 54 | <= 50 | trượt | trang mới cập nhật p50 20445.30 ms, p99 32116.55 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:manager_50 | P0 | 2134 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 440.41 ms, p99 2434.79 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:manager_500 | P0 | 2.561e+04 ms | 55 | <= 50 | trượt | 500 cấp dưới p50 8186.44 ms, p99 33496.20 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:manager_5000 | P0 | 3.996e+04 ms | 86 | <= 50 | trượt | 4999 cấp dưới p50 23506.62 ms, p99 51175.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:own | P0 | 271.4 ms | 96 | <= 50 | trượt | p50 51.63 ms, p99 922.10 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:own_sort_slot | P0 | 198.5 ms | 93 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 57.44 ms, p99 315.15 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:public_read | P0 | 3113 ms | 129 | <= 50 | trượt | p50 845.67 ms, p99 4742.85 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:service_account | P0 | 2.221e+04 ms | 54 | <= 50 | trượt | p50 7099.04 ms, p99 28578.68 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:share_recipient | P0 | 1766 ms | 52 | <= 50 | trượt | p50 671.99 ms, p99 2008.35 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:team | P0 | 1680 ms | 52 | <= 50 | trượt | p50 536.04 ms, p99 2804.38 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:team_sort_slot | P0 | 1747 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 613.69 ms, p99 2471.15 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:workspace_1 | P0 | 2019 ms | 51 | <= 50 | trượt | p50 764.15 ms, p99 2857.22 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:workspace_40 | P0 | 2.934e+04 ms | 64 | <= 50 | trượt | 40 workspace p50 15223.18 ms, p99 34490.04 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:agent_one_object | P0 | 219.4 ms | 57 | <= 50 | trượt | p50 86.96 ms, p99 301.81 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:company | P0 | 243.2 ms | 84 | <= 50 | trượt | p50 61.64 ms, p99 2073.18 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:company_name | P0 | 329.2 ms | 53 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 135.42 ms, p99 485.53 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:company_updated | P0 | 425.5 ms | 53 | <= 50 | trượt | trang mới cập nhật p50 116.80 ms, p99 1255.16 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:manager_50 | P0 | 1333 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 226.54 ms, p99 1521.31 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:manager_500 | P0 | 3.324e+04 ms | 55 | <= 50 | trượt | 500 cấp dưới p50 6770.16 ms, p99 33829.56 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:manager_5000 | P0 | 4.409e+04 ms | 58 | <= 50 | trượt | 4999 cấp dưới p50 23916.96 ms, p99 52121.09 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:own | P0 | 190.5 ms | 100 | <= 50 | trượt | p50 51.12 ms, p99 276.86 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:own_sort_slot | P0 | 220.5 ms | 83 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 55.41 ms, p99 1167.84 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:public_read | P0 | 4059 ms | 138 | <= 50 | trượt | p50 62.22 ms, p99 4563.23 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:service_account | P0 | 177 ms | 89 | <= 50 | trượt | p50 55.91 ms, p99 1976.71 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:share_recipient | P0 | 8775 ms | 56 | <= 50 | trượt | p50 1834.09 ms, p99 9624.35 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:team | P0 | 1478 ms | 51 | <= 50 | trượt | p50 418.71 ms, p99 1775.33 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:team_sort_slot | P0 | 1119 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 372.17 ms, p99 1459.03 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:workspace_1 | P0 | 1741 ms | 51 | <= 50 | trượt | p50 412.00 ms, p99 2263.57 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:workspace_40 | P0 | 3.138e+04 ms | 62 | <= 50 | trượt | 40 workspace p50 12100.82 ms, p99 42251.48 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:agent_one_object | P0 | 1607 ms | 51 | <= 50 | trượt | p50 681.65 ms, p99 1960.02 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:company | P0 | 176.2 ms | 88 | <= 50 | trượt | p50 56.81 ms, p99 335.04 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:company_name | P0 | 251.7 ms | 56 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 94.61 ms, p99 1372.46 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:company_updated | P0 | 239.2 ms | 61 | <= 50 | trượt | trang mới cập nhật p50 98.81 ms, p99 251.52 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:manager_50 | P0 | 1058 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 142.21 ms, p99 1500.27 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:manager_500 | P0 | 1450 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 303.78 ms, p99 1582.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:manager_5000 | P0 | 341.9 ms | 51 | <= 50 | trượt | 4999 cấp dưới p50 113.31 ms, p99 2296.62 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:own | P0 | 119.5 ms | 113 | <= 50 | trượt | p50 47.80 ms, p99 235.23 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:own_sort_slot | P0 | 131.4 ms | 148 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 40.72 ms, p99 239.90 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:public_read | P0 | 6075 ms | 70 | <= 50 | trượt | p50 569.41 ms, p99 6086.39 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:service_account | P0 | 291.2 ms | 84 | <= 50 | trượt | p50 59.82 ms, p99 1313.83 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:share_recipient | P0 | 3532 ms | 52 | <= 50 | trượt | p50 1115.59 ms, p99 5669.32 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:team | P0 | 3660 ms | 51 | <= 50 | trượt | p50 278.83 ms, p99 5817.27 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:team_sort_slot | P0 | 1709 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 886.97 ms, p99 1987.29 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:workspace_1 | P0 | 1001 ms | 51 | <= 50 | trượt | p50 307.80 ms, p99 1174.58 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:workspace_40 | P0 | 772.5 ms | 51 | <= 50 | trượt | 40 workspace p50 243.16 ms, p99 1027.63 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:agent_one_object | P0 | 294.8 ms | 75 | <= 50 | trượt | p50 74.73 ms, p99 3182.55 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:company | P0 | 3095 ms | 51 | <= 50 | trượt | p50 691.03 ms, p99 3140.81 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:company_name | P0 | 3061 ms | 51 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 1775.69 ms, p99 3368.03 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:company_updated | P0 | 2673 ms | 51 | <= 50 | trượt | trang mới cập nhật p50 1588.59 ms, p99 2801.77 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:manager_50 | P0 | 262.9 ms | 68 | <= 50 | trượt | 50 cấp dưới p50 92.77 ms, p99 295.00 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:manager_500 | P0 | 3704 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 866.32 ms, p99 4892.79 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:manager_5000 | P0 | 3712 ms | 55 | <= 50 | trượt | 4999 cấp dưới p50 1861.69 ms, p99 4516.02 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:own | P0 | 286 ms | 402 | <= 50 | trượt | p50 30.74 ms, p99 926.36 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:own_sort_slot | P0 | 180.6 ms | 371 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 30.29 ms, p99 930.26 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:public_read | P0 | 1665 ms | 65 | <= 50 | trượt | p50 80.83 ms, p99 1761.82 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:service_account | P0 | 1698 ms | 51 | <= 50 | trượt | p50 509.47 ms, p99 2278.41 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:share_recipient | P0 | 311.6 ms | 68 | <= 50 | trượt | p50 108.32 ms, p99 2389.90 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:team | P0 | 393.3 ms | 57 | <= 50 | trượt | p50 115.60 ms, p99 496.74 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:team_sort_slot | P0 | 356.3 ms | 58 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 98.52 ms, p99 493.50 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:workspace_1 | P0 | 290.7 ms | 63 | <= 50 | trượt | p50 88.64 ms, p99 343.62 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:workspace_40 | P0 | 3000 ms | 51 | <= 50 | trượt | 40 workspace p50 1110.78 ms, p99 5802.90 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:agent_one_object | P0 | 196.3 ms | 99 | <= 50 | trượt | p50 50.93 ms, p99 320.84 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:company | P0 | 3132 ms | 51 | <= 50 | trượt | p50 625.34 ms, p99 4326.79 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:company_name | P0 | 2623 ms | 51 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 1523.26 ms, p99 3251.19 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:company_updated | P0 | 2423 ms | 51 | <= 50 | trượt | trang mới cập nhật p50 1629.99 ms, p99 3263.70 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:manager_50 | P0 | 439 ms | 74 | <= 50 | trượt | 50 cấp dưới p50 83.74 ms, p99 1436.78 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:manager_500 | P0 | 2073 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 448.70 ms, p99 2727.26 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:manager_5000 | P0 | 3362 ms | 52 | <= 50 | trượt | 4999 cấp dưới p50 1536.33 ms, p99 3891.12 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:own | P0 | 172.8 ms | 220 | <= 50 | trượt | p50 30.69 ms, p99 416.56 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:own_sort_slot | P0 | 207.5 ms | 156 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 37.21 ms, p99 345.01 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:public_read | P0 | 3825 ms | 120 | <= 50 | trượt | p50 89.43 ms, p99 4248.58 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:service_account | P0 | 2355 ms | 51 | <= 50 | trượt | p50 407.20 ms, p99 3043.84 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:share_recipient | P0 | 279.8 ms | 72 | <= 50 | trượt | p50 72.67 ms, p99 1675.56 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:team | P0 | 315.7 ms | 72 | <= 50 | trượt | p50 114.16 ms, p99 390.12 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:team_sort_slot | P0 | 315.9 ms | 61 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 108.85 ms, p99 697.31 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:workspace_1 | P0 | 291.6 ms | 75 | <= 50 | trượt | p50 67.36 ms, p99 1306.98 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:workspace_40 | P0 | 3104 ms | 51 | <= 50 | trượt | 40 workspace p50 934.14 ms, p99 4016.50 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:agent_one_object | P0 | 1582 ms | 51 | <= 50 | trượt | p50 747.68 ms, p99 3931.95 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:company | P0 | 203.2 ms | 83 | <= 50 | trượt | p50 63.01 ms, p99 329.96 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:company_name | P0 | 419.5 ms | 57 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 91.13 ms, p99 1126.68 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:company_updated | P0 | 279 ms | 57 | <= 50 | trượt | trang mới cập nhật p50 103.54 ms, p99 530.56 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:manager_50 | P0 | 643.1 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 292.91 ms, p99 1493.33 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:manager_500 | P0 | 807.5 ms | 52 | <= 50 | trượt | 500 cấp dưới p50 299.79 ms, p99 1733.83 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:manager_5000 | P0 | 369.6 ms | 55 | <= 50 | trượt | 4999 cấp dưới p50 118.78 ms, p99 538.18 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:own | P0 | 158.9 ms | 105 | <= 50 | trượt | p50 48.72 ms, p99 330.50 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:own_sort_slot | P0 | 156.2 ms | 105 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 48.27 ms, p99 302.17 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:public_read | P0 | 3302 ms | 120 | <= 50 | trượt | p50 559.41 ms, p99 4585.06 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:service_account | P0 | 196.5 ms | 83 | <= 50 | trượt | p50 71.39 ms, p99 1181.59 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:share_recipient | P0 | 1790 ms | 51 | <= 50 | trượt | p50 261.16 ms, p99 2977.57 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:team | P0 | 1417 ms | 51 | <= 50 | trượt | p50 242.23 ms, p99 1629.29 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:team_sort_slot | P0 | 1496 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 318.67 ms, p99 1743.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:workspace_1 | P0 | 1015 ms | 51 | <= 50 | trượt | p50 237.21 ms, p99 1464.61 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:workspace_40 | P0 | 482.3 ms | 51 | <= 50 | trượt | 40 workspace p50 222.54 ms, p99 506.39 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:agent_one_object | P0 | 164.4 ms | 51 | <= 5 | trượt | p50 37.14 ms, p99 1882.39 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:company | P0 | 328 ms | 52 | <= 5 | trượt | p50 35.21 ms, p99 1155.10 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:company_name | P0 | 101 ms | 51 | <= 5 | trượt | ORDER BY name "vi-VN-x-icu" p50 45.10 ms, p99 177.87 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:company_updated | P0 | 165.7 ms | 51 | <= 5 | trượt | trang mới cập nhật p50 34.83 ms, p99 1726.57 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:manager_50 | P0 | 142.9 ms | 51 | <= 5 | trượt | 50 cấp dưới p50 44.54 ms, p99 1303.32 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:manager_500 | P0 | 929.3 ms | 51 | <= 5 | trượt | 500 cấp dưới p50 44.77 ms, p99 1793.30 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:manager_5000 | P0 | 183.5 ms | 51 | <= 5 | trượt | 4999 cấp dưới p50 55.62 ms, p99 1212.07 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:own | P0 | 107.3 ms | 51 | <= 5 | trượt | p50 39.82 ms, p99 181.06 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:own_sort_slot | P0 | 121.3 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 48.28 ms, p99 192.40 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:public_read | P0 | 937.4 ms | 55 | <= 5 | trượt | p50 32.37 ms, p99 983.49 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:service_account | P0 | 123.3 ms | 51 | <= 5 | trượt | p50 36.51 ms, p99 271.63 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:share_recipient | P0 | 175.7 ms | 51 | <= 5 | trượt | p50 55.58 ms, p99 737.99 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:team | P0 | 361.5 ms | 51 | <= 5 | trượt | p50 52.82 ms, p99 1431.27 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:team_sort_slot | P0 | 277.1 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 54.58 ms, p99 1023.31 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:workspace_1 | P0 | 170.7 ms | 51 | <= 5 | trượt | p50 42.41 ms, p99 1427.71 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:workspace_40 | P0 | 92.14 ms | 51 | <= 5 | trượt | 40 workspace p50 41.21 ms, p99 303.12 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:agent_one_object | P0 | 141.8 ms | 51 | <= 5 | trượt | p50 33.02 ms, p99 1387.37 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:company | P0 | 134.5 ms | 51 | <= 5 | trượt | p50 35.02 ms, p99 651.63 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:company_name | P0 | 120.3 ms | 51 | <= 5 | trượt | ORDER BY name "vi-VN-x-icu" p50 34.51 ms, p99 1276.85 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:company_updated | P0 | 242.7 ms | 51 | <= 5 | trượt | trang mới cập nhật p50 36.72 ms, p99 1065.57 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:manager_50 | P0 | 207.3 ms | 51 | <= 5 | trượt | 50 cấp dưới p50 41.73 ms, p99 1959.28 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:manager_500 | P0 | 135.2 ms | 52 | <= 5 | trượt | 500 cấp dưới p50 47.18 ms, p99 160.85 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:manager_5000 | P0 | 127.6 ms | 51 | <= 5 | trượt | 4999 cấp dưới p50 41.38 ms, p99 185.00 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:own | P0 | 166.4 ms | 51 | <= 5 | trượt | p50 41.40 ms, p99 1137.03 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:own_sort_slot | P0 | 340.6 ms | 52 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 42.76 ms, p99 1246.25 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:public_read | P0 | 878.5 ms | 91 | <= 5 | trượt | p50 32.25 ms, p99 4685.91 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:service_account | P0 | 406.3 ms | 52 | <= 5 | trượt | p50 33.00 ms, p99 737.87 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:share_recipient | P0 | 149.2 ms | 51 | <= 5 | trượt | p50 49.13 ms, p99 726.40 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:team | P0 | 146.3 ms | 51 | <= 5 | trượt | p50 45.01 ms, p99 238.58 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:team_sort_slot | P0 | 179.8 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 38.32 ms, p99 239.53 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:workspace_1 | P0 | 197.8 ms | 52 | <= 5 | trượt | p50 44.34 ms, p99 238.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:workspace_40 | P0 | 119.6 ms | 51 | <= 5 | trượt | 40 workspace p50 47.73 ms, p99 652.92 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:agent_one_object | P0 | 304.5 ms | 66 | <= 50 | trượt | p50 82.33 ms, p99 1418.17 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:company | P0 | 234 ms | 91 | <= 50 | trượt | p50 53.56 ms, p99 2216.96 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:company_name | P0 | 244.6 ms | 69 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 79.43 ms, p99 291.59 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:company_updated | P0 | 287.5 ms | 85 | <= 50 | trượt | trang mới cập nhật p50 60.66 ms, p99 2053.09 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:manager_50 | P0 | 814.3 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 196.01 ms, p99 1396.42 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:manager_500 | P0 | 8110 ms | 53 | <= 50 | trượt | 500 cấp dưới p50 559.81 ms, p99 27134.75 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:manager_5000 | P0 | 1.582e+04 ms | 53 | <= 50 | trượt | 4999 cấp dưới p50 134.02 ms, p99 27497.42 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:own | P0 | 164.1 ms | 110 | <= 50 | trượt | p50 47.69 ms, p99 247.32 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:own_sort_slot | P0 | 115.3 ms | 94 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 52.30 ms, p99 229.66 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:public_read | P0 | 913 ms | 70 | <= 50 | trượt | p50 80.87 ms, p99 1733.48 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:service_account | P0 | 213.4 ms | 69 | <= 50 | trượt | p50 69.73 ms, p99 1360.53 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:share_recipient | P0 | 8961 ms | 54 | <= 50 | trượt | p50 3436.13 ms, p99 11061.53 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:team | P0 | 847.6 ms | 51 | <= 50 | trượt | p50 318.62 ms, p99 1114.37 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:team_sort_slot | P0 | 1008 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 384.86 ms, p99 1330.67 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:workspace_1 | P0 | 782.9 ms | 52 | <= 50 | trượt | p50 299.43 ms, p99 3174.34 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:workspace_40 | P0 | 1.42e+04 ms | 52 | <= 50 | trượt | 40 workspace p50 275.09 ms, p99 25703.34 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:agent_one_object | P0 | 273.1 ms | 58 | <= 50 | trượt | p50 99.22 ms, p99 443.44 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:company | P0 | 204.3 ms | 73 | <= 50 | trượt | p50 66.23 ms, p99 1958.95 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:company_name | P0 | 361.4 ms | 72 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 75.72 ms, p99 1067.77 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:company_updated | P0 | 374.3 ms | 72 | <= 50 | trượt | trang mới cập nhật p50 74.24 ms, p99 1790.47 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:manager_50 | P0 | 546.5 ms | 57 | <= 50 | trượt | 50 cấp dưới p50 115.96 ms, p99 1583.85 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:manager_500 | P0 | 1098 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 343.35 ms, p99 1162.89 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:manager_5000 | P0 | 329.1 ms | 54 | <= 50 | trượt | 4999 cấp dưới p50 115.05 ms, p99 1449.34 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:own | P0 | 125.1 ms | 88 | <= 50 | trượt | p50 51.41 ms, p99 194.93 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:own_sort_slot | P0 | 240.8 ms | 89 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 62.86 ms, p99 885.23 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:public_read | P0 | 457.1 ms | 132 | <= 50 | trượt | p50 60.09 ms, p99 3636.10 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:service_account | P0 | 206.4 ms | 83 | <= 50 | trượt | p50 57.69 ms, p99 408.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:share_recipient | P0 | 4004 ms | 54 | <= 50 | trượt | p50 496.81 ms, p99 4395.99 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:team | P0 | 771.6 ms | 52 | <= 50 | trượt | p50 140.92 ms, p99 1530.23 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:team_sort_slot | P0 | 714.8 ms | 55 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 215.10 ms, p99 1059.40 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:workspace_1 | P0 | 549.8 ms | 52 | <= 50 | trượt | p50 183.81 ms, p99 883.60 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:workspace_40 | P0 | 839.3 ms | 51 | <= 50 | trượt | 40 workspace p50 242.98 ms, p99 2051.98 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:agent_one_object | P0 | 2051 ms | 59 | <= 300 | trượt | p50 1212.40 ms, p99 2306.56 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:company | P0 | 2110 ms | 105 | <= 300 | trượt | p50 341.85 ms, p99 2275.42 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:company_name | P0 | 2093 ms | 95 | <= 300 | trượt | ORDER BY name "vi-VN-x-icu" p50 492.44 ms, p99 3556.06 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:company_updated | P0 | 1782 ms | 191 | <= 300 | trượt | trang mới cập nhật p50 189.40 ms, p99 2077.86 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:manager_50 | P0 | 5684 ms | 51 | <= 300 | trượt | 50 cấp dưới p50 2010.79 ms, p99 6237.27 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:manager_500 | P0 | 3.685e+04 ms | 52 | <= 300 | trượt | 500 cấp dưới p50 11060.90 ms, p99 40514.73 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:manager_5000 | P0 | 4.919e+04 ms | 57 | <= 300 | trượt | 4999 cấp dưới p50 15477.65 ms, p99 56958.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:own | P0 | 1.092e+04 ms | 55 | <= 300 | trượt | p50 6642.33 ms, p99 12132.72 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:own_sort_slot | P0 | 1.151e+04 ms | 65 | <= 300 | trượt | sắp theo slot t02, tầm hẹp p50 5645.96 ms, p99 14109.50 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:public_read | P0 | 1273 ms | 92 | <= 300 | trượt | p50 439.01 ms, p99 1363.17 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:service_account | P0 | 1768 ms | 71 | <= 300 | trượt | p50 532.41 ms, p99 2691.22 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:share_recipient | P0 | 1.099e+04 ms | 54 | <= 300 | trượt | p50 4492.33 ms, p99 12755.58 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:team | P0 | 9729 ms | 55 | <= 300 | trượt | p50 3029.87 ms, p99 11540.27 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:team_sort_slot | P0 | 1.038e+04 ms | 58 | <= 300 | trượt | sắp theo slot t02, tầm hẹp p50 6659.95 ms, p99 10618.53 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:workspace_1 | P0 | 7260 ms | 53 | <= 300 | trượt | p50 1740.39 ms, p99 8465.73 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:workspace_40 | P0 | 2.166e+04 ms | 55 | <= 300 | trượt | 40 workspace p50 12222.22 ms, p99 40992.08 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:agent_one_object | P0 | 1706 ms | 62 | <= 300 | trượt | p50 763.80 ms, p99 2749.60 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:company | P0 | 1921 ms | 95 | <= 300 | trượt | p50 311.90 ms, p99 2771.83 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:company_name | P0 | 1674 ms | 101 | <= 300 | trượt | ORDER BY name "vi-VN-x-icu" p50 303.85 ms, p99 1957.04 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:company_updated | P0 | 1716 ms | 115 | <= 300 | trượt | trang mới cập nhật p50 284.66 ms, p99 2502.48 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:manager_50 | P0 | 5465 ms | 51 | <= 300 | trượt | 50 cấp dưới p50 1630.03 ms, p99 6052.63 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:manager_500 | P0 | 4.718e+04 ms | 53 | <= 300 | trượt | 500 cấp dưới p50 10806.34 ms, p99 49669.33 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:manager_5000 | P0 | 3.397e+04 ms | 60 | <= 300 | trượt | 4999 cấp dưới p50 14139.34 ms, p99 51551.91 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:own | P0 | 1.052e+04 ms | 56 | <= 300 | trượt | p50 6323.09 ms, p99 12138.29 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:own_sort_slot | P0 | 9039 ms | 53 | <= 300 | trượt | sắp theo slot t02, tầm hẹp p50 2412.32 ms, p99 11192.03 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:public_read | P0 | 1003 ms | 105 | <= 300 | trượt | p50 438.09 ms, p99 1742.83 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:service_account | P0 | 1563 ms | 108 | <= 300 | trượt | p50 298.82 ms, p99 1905.90 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:share_recipient | P0 | 9016 ms | 55 | <= 300 | trượt | p50 4943.30 ms, p99 10210.79 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:team | P0 | 8956 ms | 54 | <= 300 | trượt | p50 3117.32 ms, p99 10188.02 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:team_sort_slot | P0 | 9991 ms | 55 | <= 300 | trượt | sắp theo slot t02, tầm hẹp p50 3280.35 ms, p99 12042.53 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:workspace_1 | P0 | 7703 ms | 54 | <= 300 | trượt | p50 1490.54 ms, p99 11666.23 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:workspace_40 | P0 | 4.265e+04 ms | 53 | <= 300 | trượt | 40 workspace p50 6597.80 ms, p99 49159.19 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.5 | write_create_soak | P0 | 336.3 ms | 5667 | <= 10 | trượt | p50 238.87 ms, p99 889.73 ms; 4 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction.; soak 300 s, 75 lần ghi/s (mục tiêu 200) |
| record-access:R9.5 | write_update_slot_soak | P0 | 363.4 ms | 16960 | <= 10 | trượt | p50 246.82 ms, p99 1118.55 ms; 45 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction.; soak 300 s, 75 lần ghi/s (mục tiêu 200) |
| record-access:R9.6 | assign_p95 | P0 | 323.2 ms | 58 | <= 20 | trượt | p50 32.56 ms, p99 345.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.6 | share_p95 | P0 | 35.67 ms | 1000 |  | — | p50 22.96 ms, p99 142.97 ms |
| record-access:R9.7 | scope_compute:company | P0 | 32.27 ms | 1000 | <= 50 | đạt | p50 23.73 ms, p99 37.39 ms |
| record-access:R9.7 | scope_compute:manager_50 | P0 | 37.53 ms | 1000 | <= 50 | đạt | p50 27.35 ms, p99 43.90 ms |
| record-access:R9.7 | scope_compute:manager_500 | P0 | 40.98 ms | 1000 | <= 50 | đạt | p50 30.10 ms, p99 47.99 ms |
| record-access:R9.7 | scope_compute:manager_5000 | P0 | 68.39 ms | 1000 | <= 50 | trượt | p50 33.91 ms, p99 77.62 ms |
| record-access:R9.7 | scope_compute:own | P0 | 31.26 ms | 1000 | <= 50 | đạt | p50 22.90 ms, p99 36.94 ms |
| record-access:R9.7 | scope_compute:public_read | P0 | 28.33 ms | 1000 | <= 50 | đạt | p50 21.24 ms, p99 35.32 ms |
| record-access:R9.7 | scope_compute:service_account | P0 | 32.79 ms | 1000 | <= 50 | đạt | p50 24.23 ms, p99 38.39 ms |
| record-access:R9.7 | scope_compute:share_recipient | P0 | 28.97 ms | 1000 | <= 50 | đạt | p50 21.28 ms, p99 34.79 ms |
| record-access:R9.7 | scope_compute:team | P0 | 30.72 ms | 1000 | <= 50 | đạt | p50 22.72 ms, p99 37.49 ms |
| record-access:R9.7 | scope_compute:workspace_1 | P0 | 29.58 ms | 1000 | <= 50 | đạt | p50 22.26 ms, p99 35.45 ms |
| record-access:R9.7 | scope_compute:workspace_40 | P0 | 50.52 ms | 1000 | <= 50 | trượt | p50 36.18 ms, p99 55.98 ms |
| record-access:R9.8 | door_valid_p95 | P0 | 1.122 ms | 1000 | <= 1 | trượt | p50 0.86 ms, p99 1.39 ms; một vòng khứ hồi, trong giao dịch đã gắn setting |
| record-access:R9.9 | recompute_total_1 | P0 | 211 s |  |  | — | 1 kết nối, 5000 chủ thể, 5000 dòng valid ở epoch mới, dưới tải hỗn hợp; 3832 lời gọi cửa bị máy chủ từ chối dưới tải, gọi lại sau tải (đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction.) |
| record-access:R9.9 | recompute_total_4 | P0 | 106.9 s |  | <= 120 | đạt | 4 kết nối, 5000 chủ thể, 5000 dòng valid ở epoch mới, dưới tải hỗn hợp |
| record-access:R9.9 | stale_reads_after_revoke | P0 | 0 lần | 1000 | <= 0 | đạt | 1000 lần lặp trên hai kết nối; câu lệnh trước thu hồi thấy tầm 1000 lần |
| record-access:bước 5 | delete_p95 | P0 | 29.06 ms | 1000 |  | — | p50 23.18 ms, p99 116.85 ms |
| record-access:R9.1 | page_lead_cold:agent_one_object | W | 226.5 ms | 68 | <= 50 | trượt | p50 90.75 ms, p99 880.93 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:company | W | 171.2 ms | 87 | <= 50 | trượt | p50 57.45 ms, p99 1227.56 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:company_name | W | 210.7 ms | 58 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 88.33 ms, p99 277.06 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:company_updated | W | 266.9 ms | 56 | <= 50 | trượt | trang mới cập nhật p50 94.19 ms, p99 1050.89 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:manager_50 | W | 1025 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 222.07 ms, p99 3256.73 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:manager_500 | W | 3.181e+04 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 6905.14 ms, p99 34687.51 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:manager_5000 | W | 4.123e+04 ms | 58 | <= 50 | trượt | 4999 cấp dưới p50 23635.34 ms, p99 52760.55 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:own | W | 184.9 ms | 72 | <= 50 | trượt | p50 61.99 ms, p99 374.66 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:own_sort_slot | W | 155.1 ms | 97 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 54.56 ms, p99 271.74 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:public_read | W | 1896 ms | 85 | <= 50 | trượt | p50 76.82 ms, p99 2453.81 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:service_account | W | 191.1 ms | 80 | <= 50 | trượt | p50 65.36 ms, p99 954.37 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:share_recipient | W | 1.073e+04 ms | 54 | <= 50 | trượt | p50 3296.35 ms, p99 11107.14 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:team | W | 1184 ms | 51 | <= 50 | trượt | p50 382.66 ms, p99 3241.53 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:team_sort_slot | W | 870.1 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 270.32 ms, p99 2357.31 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:workspace_1 | W | 1564 ms | 51 | <= 50 | trượt | p50 400.66 ms, p99 1899.57 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_cold:workspace_40 | W | 3.831e+04 ms | 58 | <= 50 | trượt | 40 workspace p50 11492.45 ms, p99 42847.33 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:agent_one_object | W | 2.953e+04 ms | 54 | <= 50 | trượt | p50 19047.04 ms, p99 30935.47 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:company | W | 2.759e+04 ms | 53 | <= 50 | trượt | p50 6875.94 ms, p99 29314.93 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:company_name | W | 2.837e+04 ms | 56 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 16268.38 ms, p99 30139.21 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:company_updated | W | 2.861e+04 ms | 54 | <= 50 | trượt | trang mới cập nhật p50 16823.46 ms, p99 31189.47 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:manager_50 | W | 2515 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 1094.42 ms, p99 4058.37 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:manager_500 | W | 2.693e+04 ms | 54 | <= 50 | trượt | 500 cấp dưới p50 7264.21 ms, p99 27799.26 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:manager_5000 | W | 3.737e+04 ms | 71 | <= 50 | trượt | 4999 cấp dưới p50 25459.82 ms, p99 47507.76 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:own | W | 166.6 ms | 105 | <= 50 | trượt | p50 48.51 ms, p99 229.94 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:own_sort_slot | W | 173.8 ms | 83 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 58.67 ms, p99 214.35 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:public_read | W | 7483 ms | 70 | <= 50 | trượt | p50 1003.19 ms, p99 7529.16 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:service_account | W | 2.623e+04 ms | 54 | <= 50 | trượt | p50 6281.17 ms, p99 27692.96 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:share_recipient | W | 1839 ms | 51 | <= 50 | trượt | p50 401.42 ms, p99 2223.83 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:team | W | 1877 ms | 51 | <= 50 | trượt | p50 623.57 ms, p99 4065.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:team_sort_slot | W | 1653 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 359.23 ms, p99 1935.01 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:workspace_1 | W | 3244 ms | 51 | <= 50 | trượt | p50 382.71 ms, p99 4058.65 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_cold:workspace_40 | W | 2.782e+04 ms | 51 | <= 50 | trượt | 40 workspace p50 11217.79 ms, p99 30068.70 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:agent_one_object | W | 3.16e+04 ms | 55 | <= 50 | trượt | p50 20528.48 ms, p99 33422.43 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:company | W | 2.815e+04 ms | 52 | <= 50 | trượt | p50 6563.85 ms, p99 30842.75 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:company_name | W | 3.244e+04 ms | 55 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 22498.09 ms, p99 32959.06 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:company_updated | W | 3.124e+04 ms | 51 | <= 50 | trượt | trang mới cập nhật p50 22690.90 ms, p99 31913.80 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:manager_50 | W | 2069 ms | 53 | <= 50 | trượt | 50 cấp dưới p50 449.99 ms, p99 2363.96 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:manager_500 | W | 3.06e+04 ms | 56 | <= 50 | trượt | 500 cấp dưới p50 7386.29 ms, p99 33808.23 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:manager_5000 | W | 4.944e+04 ms | 70 | <= 50 | trượt | 4999 cấp dưới p50 22243.19 ms, p99 51710.29 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:own | W | 160.9 ms | 86 | <= 50 | trượt | p50 58.07 ms, p99 300.08 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:own_sort_slot | W | 223.6 ms | 107 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 49.41 ms, p99 267.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:public_read | W | 5970 ms | 121 | <= 50 | trượt | p50 790.33 ms, p99 inf ms; 4 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction. dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:service_account | W | 2.291e+04 ms | 57 | <= 50 | trượt | p50 6877.21 ms, p99 31777.19 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:share_recipient | W | 2256 ms | 53 | <= 50 | trượt | p50 428.91 ms, p99 2302.01 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:team | W | 1672 ms | 53 | <= 50 | trượt | p50 496.06 ms, p99 2482.37 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:team_sort_slot | W | 2153 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 584.63 ms, p99 2476.93 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:workspace_1 | W | 1862 ms | 52 | <= 50 | trượt | p50 743.21 ms, p99 2261.64 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_f_warm:workspace_40 | W | 3.158e+04 ms | 60 | <= 50 | trượt | 40 workspace p50 14134.24 ms, p99 36902.84 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:agent_one_object | W | 218 ms | 66 | <= 50 | trượt | p50 71.94 ms, p99 280.25 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:company | W | 235 ms | 89 | <= 50 | trượt | p50 57.43 ms, p99 2012.71 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:company_name | W | 412.4 ms | 55 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 110.00 ms, p99 1379.76 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:company_updated | W | 418.2 ms | 56 | <= 50 | trượt | trang mới cập nhật p50 92.74 ms, p99 1350.04 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:manager_50 | W | 1212 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 312.33 ms, p99 1411.09 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:manager_500 | W | 3.357e+04 ms | 55 | <= 50 | trượt | 500 cấp dưới p50 6474.61 ms, p99 38518.68 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:manager_5000 | W | 4.405e+04 ms | 67 | <= 50 | trượt | 4999 cấp dưới p50 22117.14 ms, p99 54207.40 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:own | W | 212.8 ms | 95 | <= 50 | trượt | p50 52.97 ms, p99 395.87 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:own_sort_slot | W | 213.5 ms | 82 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 58.37 ms, p99 1123.23 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:public_read | W | 6134 ms | 160 | <= 50 | trượt | p50 59.88 ms, p99 inf ms; 8 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction. dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:service_account | W | 236.1 ms | 85 | <= 50 | trượt | p50 60.81 ms, p99 1454.69 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:share_recipient | W | 8701 ms | 53 | <= 50 | trượt | p50 1771.90 ms, p99 10525.42 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:team | W | 1122 ms | 51 | <= 50 | trượt | p50 451.00 ms, p99 1172.34 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:team_sort_slot | W | 1206 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 422.15 ms, p99 1437.01 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:workspace_1 | W | 1606 ms | 53 | <= 50 | trượt | p50 520.55 ms, p99 1774.41 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_lead_warm:workspace_40 | W | 3.361e+04 ms | 55 | <= 50 | trượt | 40 workspace p50 11484.45 ms, p99 42457.89 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:agent_one_object | W | 1476 ms | 51 | <= 50 | trượt | p50 474.65 ms, p99 1695.76 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:company | W | 223.8 ms | 74 | <= 50 | trượt | p50 67.20 ms, p99 1614.81 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:company_name | W | 317.7 ms | 61 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 87.02 ms, p99 1110.64 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:company_updated | W | 231.5 ms | 57 | <= 50 | trượt | trang mới cập nhật p50 89.16 ms, p99 397.13 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:manager_50 | W | 561.9 ms | 51 | <= 50 | trượt | 50 cấp dưới p50 117.44 ms, p99 1031.73 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:manager_500 | W | 1079 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 177.47 ms, p99 1157.46 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:manager_5000 | W | 269.1 ms | 55 | <= 50 | trượt | 4999 cấp dưới p50 107.64 ms, p99 1221.56 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:own | W | 221.3 ms | 108 | <= 50 | trượt | p50 46.31 ms, p99 343.89 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:own_sort_slot | W | 210.7 ms | 120 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 46.56 ms, p99 382.67 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:public_read | W | 6044 ms | 61 | <= 50 | trượt | p50 715.92 ms, p99 6053.91 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:service_account | W | 184.5 ms | 92 | <= 50 | trượt | p50 54.13 ms, p99 816.12 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:share_recipient | W | 1991 ms | 52 | <= 50 | trượt | p50 606.10 ms, p99 3526.78 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:team | W | 1950 ms | 51 | <= 50 | trượt | p50 171.00 ms, p99 3436.71 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:team_sort_slot | W | 1316 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 587.27 ms, p99 1436.73 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:workspace_1 | W | 823.4 ms | 51 | <= 50 | trượt | p50 181.29 ms, p99 1028.47 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_cold:workspace_40 | W | 460.1 ms | 51 | <= 50 | trượt | 40 workspace p50 171.17 ms, p99 794.00 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:agent_one_object | W | 254.7 ms | 85 | <= 50 | trượt | p50 75.20 ms, p99 2234.78 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:company | W | 1824 ms | 51 | <= 50 | trượt | p50 497.36 ms, p99 2601.44 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:company_name | W | 2772 ms | 51 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 1788.57 ms, p99 2961.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:company_updated | W | 2846 ms | 51 | <= 50 | trượt | trang mới cập nhật p50 1743.99 ms, p99 3338.92 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:manager_50 | W | 258.6 ms | 81 | <= 50 | trượt | 50 cấp dưới p50 76.84 ms, p99 490.95 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:manager_500 | W | 2456 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 703.30 ms, p99 3094.34 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:manager_5000 | W | 3023 ms | 52 | <= 50 | trượt | 4999 cấp dưới p50 1782.12 ms, p99 4345.21 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:own | W | 358.3 ms | 245 | <= 50 | trượt | p50 29.59 ms, p99 1279.69 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:own_sort_slot | W | 166.8 ms | 207 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 32.22 ms, p99 361.07 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:public_read | W | 1623 ms | 80 | <= 50 | trượt | p50 89.90 ms, p99 1823.19 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:service_account | W | 2766 ms | 51 | <= 50 | trượt | p50 744.69 ms, p99 4290.68 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:share_recipient | W | 331.6 ms | 71 | <= 50 | trượt | p50 79.66 ms, p99 1666.40 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:team | W | 293.2 ms | 67 | <= 50 | trượt | p50 90.96 ms, p99 1391.95 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:team_sort_slot | W | 282.7 ms | 60 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 94.78 ms, p99 435.59 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:workspace_1 | W | 407.5 ms | 66 | <= 50 | trượt | p50 100.93 ms, p99 1963.36 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_cold:workspace_40 | W | 2155 ms | 51 | <= 50 | trượt | 40 workspace p50 986.95 ms, p99 3433.17 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:agent_one_object | W | 176.6 ms | 106 | <= 50 | trượt | p50 49.33 ms, p99 258.37 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:company | W | 2798 ms | 51 | <= 50 | trượt | p50 682.78 ms, p99 3123.29 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:company_name | W | 3109 ms | 52 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 1275.58 ms, p99 3645.34 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:company_updated | W | 2828 ms | 51 | <= 50 | trượt | trang mới cập nhật p50 1832.18 ms, p99 3277.45 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:manager_50 | W | 316.5 ms | 68 | <= 50 | trượt | 50 cấp dưới p50 84.67 ms, p99 1671.06 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:manager_500 | W | 2394 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 493.08 ms, p99 2653.30 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:manager_5000 | W | 3458 ms | 51 | <= 50 | trượt | 4999 cấp dưới p50 1592.75 ms, p99 4870.74 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:own | W | 178.1 ms | 193 | <= 50 | trượt | p50 31.16 ms, p99 414.19 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:own_sort_slot | W | 163.3 ms | 172 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 31.56 ms, p99 374.82 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:public_read | W | 5274 ms | 121 | <= 50 | trượt | p50 95.71 ms, p99 inf ms; 4 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction. dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:service_account | W | 2480 ms | 52 | <= 50 | trượt | p50 343.03 ms, p99 2847.85 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:share_recipient | W | 348.3 ms | 66 | <= 50 | trượt | p50 105.21 ms, p99 1511.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:team | W | 270.7 ms | 65 | <= 50 | trượt | p50 88.18 ms, p99 373.29 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:team_sort_slot | W | 360.2 ms | 60 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 103.92 ms, p99 514.99 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:workspace_1 | W | 303.1 ms | 64 | <= 50 | trượt | p50 100.64 ms, p99 1628.73 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_f_warm:workspace_40 | W | 3323 ms | 51 | <= 50 | trượt | 40 workspace p50 766.36 ms, p99 4233.59 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:agent_one_object | W | 2092 ms | 52 | <= 50 | trượt | p50 891.46 ms, p99 2303.98 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:company | W | 199.2 ms | 89 | <= 50 | trượt | p50 58.39 ms, p99 335.23 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:company_name | W | 257 ms | 57 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 103.22 ms, p99 1171.78 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:company_updated | W | 417.9 ms | 58 | <= 50 | trượt | trang mới cập nhật p50 99.34 ms, p99 1479.57 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:manager_50 | W | 829.3 ms | 54 | <= 50 | trượt | 50 cấp dưới p50 230.23 ms, p99 1156.39 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:manager_500 | W | 997.8 ms | 52 | <= 50 | trượt | 500 cấp dưới p50 269.09 ms, p99 1180.33 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:manager_5000 | W | 240.9 ms | 56 | <= 50 | trượt | 4999 cấp dưới p50 108.95 ms, p99 331.73 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:own | W | 197 ms | 106 | <= 50 | trượt | p50 49.88 ms, p99 310.66 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:own_sort_slot | W | 169.5 ms | 119 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 45.45 ms, p99 366.52 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:public_read | W | 5894 ms | 127 | <= 50 | trượt | p50 548.26 ms, p99 inf ms; 4 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction. dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:service_account | W | 192.8 ms | 87 | <= 50 | trượt | p50 60.82 ms, p99 1213.44 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:share_recipient | W | 1462 ms | 51 | <= 50 | trượt | p50 322.46 ms, p99 1909.37 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:team | W | 1343 ms | 52 | <= 50 | trượt | p50 251.34 ms, p99 1522.32 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:team_sort_slot | W | 1702 ms | 52 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 400.66 ms, p99 2225.55 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:workspace_1 | W | 885.4 ms | 52 | <= 50 | trượt | p50 201.68 ms, p99 2279.43 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.1 | page_other_warm:workspace_40 | W | 571.7 ms | 52 | <= 50 | trượt | 40 workspace p50 162.81 ms, p99 829.94 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:agent_one_object | W | 110 ms | 51 | <= 5 | trượt | p50 34.86 ms, p99 165.91 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:company | W | 731.3 ms | 51 | <= 5 | trượt | p50 35.90 ms, p99 1173.01 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:company_name | W | 91.07 ms | 51 | <= 5 | trượt | ORDER BY name "vi-VN-x-icu" p50 36.35 ms, p99 135.96 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:company_updated | W | 162.5 ms | 51 | <= 5 | trượt | trang mới cập nhật p50 37.82 ms, p99 1078.82 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:manager_50 | W | 182.2 ms | 51 | <= 5 | trượt | 50 cấp dưới p50 34.23 ms, p99 2186.02 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:manager_500 | W | 200.5 ms | 51 | <= 5 | trượt | 500 cấp dưới p50 52.57 ms, p99 827.71 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:manager_5000 | W | 159.5 ms | 51 | <= 5 | trượt | 4999 cấp dưới p50 53.32 ms, p99 749.41 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:own | W | 137.3 ms | 51 | <= 5 | trượt | p50 36.17 ms, p99 1385.39 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:own_sort_slot | W | 121.6 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 36.09 ms, p99 742.62 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:public_read | W | 810.3 ms | 57 | <= 5 | trượt | p50 40.88 ms, p99 949.93 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:service_account | W | 75.51 ms | 51 | <= 5 | trượt | p50 33.29 ms, p99 850.44 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:share_recipient | W | 162.9 ms | 51 | <= 5 | trượt | p50 45.94 ms, p99 1006.72 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:team | W | 131.6 ms | 51 | <= 5 | trượt | p50 35.88 ms, p99 955.93 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:team_sort_slot | W | 131.9 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 39.88 ms, p99 711.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:workspace_1 | W | 129.1 ms | 51 | <= 5 | trượt | p50 38.49 ms, p99 519.12 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_cold:workspace_40 | W | 159.5 ms | 51 | <= 5 | trượt | 40 workspace p50 31.78 ms, p99 167.95 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:agent_one_object | W | 206.9 ms | 51 | <= 5 | trượt | p50 35.77 ms, p99 1413.62 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:company | W | 127.7 ms | 51 | <= 5 | trượt | p50 35.80 ms, p99 144.63 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:company_name | W | 158 ms | 51 | <= 5 | trượt | ORDER BY name "vi-VN-x-icu" p50 33.33 ms, p99 1430.94 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:company_updated | W | 110.8 ms | 51 | <= 5 | trượt | trang mới cập nhật p50 36.50 ms, p99 1194.07 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:manager_50 | W | 144.5 ms | 51 | <= 5 | trượt | 50 cấp dưới p50 42.12 ms, p99 839.75 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:manager_500 | W | 138.8 ms | 51 | <= 5 | trượt | 500 cấp dưới p50 48.53 ms, p99 273.05 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:manager_5000 | W | 139 ms | 51 | <= 5 | trượt | 4999 cấp dưới p50 45.33 ms, p99 262.19 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:own | W | 194.5 ms | 51 | <= 5 | trượt | p50 45.40 ms, p99 837.32 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:own_sort_slot | W | 137.3 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 45.86 ms, p99 1530.57 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:public_read | W | 1134 ms | 88 | <= 5 | trượt | p50 40.48 ms, p99 inf ms; 2 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction. dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:service_account | W | 349.1 ms | 52 | <= 5 | trượt | p50 32.29 ms, p99 825.46 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:share_recipient | W | 132.6 ms | 51 | <= 5 | trượt | p50 47.93 ms, p99 1137.46 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:team | W | 110.1 ms | 51 | <= 5 | trượt | p50 54.38 ms, p99 151.00 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:team_sort_slot | W | 109.3 ms | 51 | <= 5 | trượt | sắp theo slot t02, tầm hẹp p50 51.76 ms, p99 211.82 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:workspace_1 | W | 134.3 ms | 51 | <= 5 | trượt | p50 45.02 ms, p99 254.47 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.2 | get_warm:workspace_40 | W | 177.1 ms | 51 | <= 5 | trượt | 40 workspace p50 33.49 ms, p99 496.25 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:agent_one_object | W | 277.5 ms | 64 | <= 50 | trượt | p50 93.95 ms, p99 1754.78 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:company | W | 208 ms | 89 | <= 50 | trượt | p50 59.83 ms, p99 1034.43 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:company_name | W | 230.7 ms | 75 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 71.04 ms, p99 310.56 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:company_updated | W | 154.8 ms | 74 | <= 50 | trượt | trang mới cập nhật p50 67.79 ms, p99 205.20 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:manager_50 | W | 694.4 ms | 52 | <= 50 | trượt | 50 cấp dưới p50 171.02 ms, p99 1212.65 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:manager_500 | W | 7837 ms | 53 | <= 50 | trượt | 500 cấp dưới p50 669.13 ms, p99 26156.03 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:manager_5000 | W | 1.704e+04 ms | 53 | <= 50 | trượt | 4999 cấp dưới p50 130.17 ms, p99 40288.08 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:own | W | 188.6 ms | 95 | <= 50 | trượt | p50 61.01 ms, p99 338.46 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:own_sort_slot | W | 226.6 ms | 78 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 62.66 ms, p99 355.49 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:public_read | W | 817.3 ms | 69 | <= 50 | trượt | p50 77.14 ms, p99 1011.17 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:service_account | W | 249.2 ms | 79 | <= 50 | trượt | p50 68.42 ms, p99 983.76 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:share_recipient | W | 7860 ms | 54 | <= 50 | trượt | p50 2142.53 ms, p99 10492.14 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:team | W | 1135 ms | 51 | <= 50 | trượt | p50 206.15 ms, p99 1972.01 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:team_sort_slot | W | 1397 ms | 51 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 243.43 ms, p99 1824.24 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:workspace_1 | W | 965.2 ms | 52 | <= 50 | trượt | p50 210.50 ms, p99 2334.33 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_cold:workspace_40 | W | 1.648e+04 ms | 51 | <= 50 | trượt | 40 workspace p50 257.26 ms, p99 22995.42 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:agent_one_object | W | 199 ms | 62 | <= 50 | trượt | p50 87.46 ms, p99 245.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:company | W | 221 ms | 78 | <= 50 | trượt | p50 66.45 ms, p99 1478.63 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:company_name | W | 276.9 ms | 81 | <= 50 | trượt | ORDER BY name "vi-VN-x-icu" p50 61.70 ms, p99 1393.54 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:company_updated | W | 484 ms | 77 | <= 50 | trượt | trang mới cập nhật p50 69.21 ms, p99 1547.89 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:manager_50 | W | 548.4 ms | 52 | <= 50 | trượt | 50 cấp dưới p50 106.99 ms, p99 1258.85 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:manager_500 | W | 1167 ms | 51 | <= 50 | trượt | 500 cấp dưới p50 238.00 ms, p99 1420.42 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:manager_5000 | W | 423.3 ms | 53 | <= 50 | trượt | 4999 cấp dưới p50 135.82 ms, p99 1377.12 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:own | W | 166.8 ms | 105 | <= 50 | trượt | p50 49.55 ms, p99 211.31 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:own_sort_slot | W | 151.5 ms | 103 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 48.27 ms, p99 184.93 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:public_read | W | 2211 ms | 138 | <= 50 | trượt | p50 66.20 ms, p99 inf ms; 4 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction. dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:service_account | W | 192.4 ms | 75 | <= 50 | trượt | p50 67.93 ms, p99 284.81 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:share_recipient | W | 3774 ms | 51 | <= 50 | trượt | p50 524.81 ms, p99 4585.61 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:team | W | 1143 ms | 52 | <= 50 | trượt | p50 144.03 ms, p99 2081.44 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:team_sort_slot | W | 710.4 ms | 55 | <= 50 | trượt | sắp theo slot t02, tầm hẹp p50 246.51 ms, p99 935.13 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:workspace_1 | W | 759.2 ms | 52 | <= 50 | trượt | p50 145.32 ms, p99 1636.95 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.3 | next_warm:workspace_40 | W | 710.7 ms | 51 | <= 50 | trượt | 40 workspace p50 216.98 ms, p99 2176.22 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:agent_one_object | W | 1786 ms | 59 | <= 300 | trượt | p50 1135.50 ms, p99 2305.56 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:company | W | 1749 ms | 113 | <= 300 | trượt | p50 320.28 ms, p99 2206.59 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:company_name | W | 1726 ms | 94 | <= 300 | trượt | ORDER BY name "vi-VN-x-icu" p50 347.76 ms, p99 2654.98 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:company_updated | W | 1866 ms | 86 | <= 300 | trượt | trang mới cập nhật p50 390.43 ms, p99 2475.64 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:manager_50 | W | 6130 ms | 51 | <= 300 | trượt | 50 cấp dưới p50 1878.49 ms, p99 8625.39 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:manager_500 | W | 1.688e+04 ms | 52 | <= 300 | trượt | 500 cấp dưới p50 10035.53 ms, p99 29855.34 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:manager_5000 | W | 3.779e+04 ms | 78 | <= 300 | trượt | 4999 cấp dưới p50 19421.30 ms, p99 59210.77 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:own | W | 1.099e+04 ms | 53 | <= 300 | trượt | p50 5557.94 ms, p99 13038.21 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:own_sort_slot | W | 1.191e+04 ms | 60 | <= 300 | trượt | sắp theo slot t02, tầm hẹp p50 3840.03 ms, p99 13795.84 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:public_read | W | 1155 ms | 108 | <= 300 | trượt | p50 431.55 ms, p99 1209.13 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:service_account | W | 2155 ms | 92 | <= 300 | trượt | p50 352.42 ms, p99 3275.76 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:share_recipient | W | 1.018e+04 ms | 54 | <= 300 | trượt | p50 2925.39 ms, p99 12240.21 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:team | W | 7708 ms | 55 | <= 300 | trượt | p50 2361.26 ms, p99 9578.20 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:team_sort_slot | W | 7442 ms | 56 | <= 300 | trượt | sắp theo slot t02, tầm hẹp p50 4393.91 ms, p99 8627.17 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:workspace_1 | W | 5309 ms | 53 | <= 300 | trượt | p50 1447.04 ms, p99 6189.66 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_cold:workspace_40 | W | 4.303e+04 ms | 56 | <= 300 | trượt | 40 workspace p50 11133.96 ms, p99 48296.38 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:agent_one_object | W | 1925 ms | 62 | <= 300 | trượt | p50 908.37 ms, p99 2690.42 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:company | W | 2256 ms | 110 | <= 300 | trượt | p50 315.91 ms, p99 2480.34 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:company_name | W | 1769 ms | 97 | <= 300 | trượt | ORDER BY name "vi-VN-x-icu" p50 341.47 ms, p99 2243.96 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:company_updated | W | 1854 ms | 102 | <= 300 | trượt | trang mới cập nhật p50 344.55 ms, p99 2168.85 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:manager_50 | W | 4862 ms | 54 | <= 300 | trượt | 50 cấp dưới p50 1889.87 ms, p99 5161.92 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:manager_500 | W | 4.847e+04 ms | 53 | <= 300 | trượt | 500 cấp dưới p50 12085.13 ms, p99 53283.77 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:manager_5000 | W | 3.056e+04 ms | 60 | <= 300 | trượt | 4999 cấp dưới p50 12202.18 ms, p99 59028.93 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:own | W | 9892 ms | 58 | <= 300 | trượt | p50 6785.32 ms, p99 12151.25 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:own_sort_slot | W | 8054 ms | 52 | <= 300 | trượt | sắp theo slot t02, tầm hẹp p50 2211.63 ms, p99 8192.77 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:public_read | W | 810.8 ms | 115 | <= 300 | trượt | p50 382.59 ms, p99 1174.03 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:service_account | W | 2035 ms | 111 | <= 300 | trượt | p50 298.44 ms, p99 2302.33 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:share_recipient | W | 9614 ms | 53 | <= 300 | trượt | p50 4520.08 ms, p99 10152.31 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:team | W | 8118 ms | 51 | <= 300 | trượt | p50 2490.74 ms, p99 9716.52 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:team_sort_slot | W | 8984 ms | 54 | <= 300 | trượt | sắp theo slot t02, tầm hẹp p50 2502.73 ms, p99 9328.88 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:workspace_1 | W | 5368 ms | 51 | <= 300 | trượt | p50 1616.03 ms, p99 8082.71 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.4 | count_warm:workspace_40 | W | 4.953e+04 ms | 54 | <= 300 | trượt | 40 workspace p50 7017.79 ms, p99 52955.35 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.5 | write_create_soak | W | 405 ms | 4428 | <= 10 | trượt | p50 306.04 ms, p99 473.44 ms; 5 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction.; soak 300 s, 59 lần ghi/s (mục tiêu 200) |
| record-access:R9.5 | write_update_slot_soak | W | 421.2 ms | 13285 | <= 10 | trượt | p50 315.49 ms, p99 497.44 ms; 51 lỗi, đầu: OutOfMemoryError: out of shared memory
HINT:  You might need to increase max_locks_per_transaction.; soak 300 s, 59 lần ghi/s (mục tiêu 200) |
| record-access:R9.6 | assign_p95 | W | 346.1 ms | 58 | <= 20 | trượt | p50 34.42 ms, p99 382.04 ms dừng sớm: hơn 5% của 1.000 mẫu đã trên ngưỡng |
| record-access:R9.6 | share_p95 | W | 39.49 ms | 1000 |  | — | p50 24.63 ms, p99 190.71 ms |
| record-access:R9.7 | scope_compute:company | W | 30.99 ms | 1000 | <= 50 | đạt | p50 23.38 ms, p99 36.84 ms |
| record-access:R9.7 | scope_compute:manager_50 | W | 35.44 ms | 1000 | <= 50 | đạt | p50 26.68 ms, p99 41.97 ms |
| record-access:R9.7 | scope_compute:manager_500 | W | 39.09 ms | 1000 | <= 50 | đạt | p50 29.29 ms, p99 46.84 ms |
| record-access:R9.7 | scope_compute:manager_5000 | W | 63.51 ms | 1000 | <= 50 | trượt | p50 35.50 ms, p99 76.48 ms |
| record-access:R9.7 | scope_compute:own | W | 29.62 ms | 1000 | <= 50 | đạt | p50 22.52 ms, p99 37.32 ms |
| record-access:R9.7 | scope_compute:public_read | W | 28.22 ms | 1000 | <= 50 | đạt | p50 20.90 ms, p99 36.05 ms |
| record-access:R9.7 | scope_compute:service_account | W | 32.03 ms | 1000 | <= 50 | đạt | p50 23.89 ms, p99 39.45 ms |
| record-access:R9.7 | scope_compute:share_recipient | W | 28.04 ms | 1000 | <= 50 | đạt | p50 21.21 ms, p99 35.35 ms |
| record-access:R9.7 | scope_compute:team | W | 30.21 ms | 1000 | <= 50 | đạt | p50 22.49 ms, p99 37.66 ms |
| record-access:R9.7 | scope_compute:workspace_1 | W | 29.23 ms | 1000 | <= 50 | đạt | p50 21.68 ms, p99 36.19 ms |
| record-access:R9.7 | scope_compute:workspace_40 | W | 48.66 ms | 1000 | <= 50 | đạt | p50 35.20 ms, p99 59.23 ms |
| record-access:R9.8 | door_valid_p95 | W | 1.169 ms | 1000 | <= 1 | trượt | p50 0.78 ms, p99 1.47 ms; một vòng khứ hồi, trong giao dịch đã gắn setting |
| record-access:R9.9 | recompute_total_1 | W | 509.4 s |  |  | — | 1 kết nối, 5000 chủ thể, 5000 dòng valid ở epoch mới, dưới tải hỗn hợp |
| record-access:R9.9 | recompute_total_4 | W | 97.56 s |  | <= 120 | đạt | 4 kết nối, 5000 chủ thể, 5000 dòng valid ở epoch mới, dưới tải hỗn hợp |
| record-access:R9.9 | stale_reads_after_revoke | W | 0 lần | 1000 | <= 0 | đạt | 1000 lần lặp trên hai kết nối; câu lệnh trước thu hồi thấy tầm 1000 lần |
| record-access:bước 5 | delete_p95 | W | 32.2 ms | 1000 |  | — | p50 23.43 ms, p99 109.20 ms |

### Tự kiểm (bước 7)

- đủ ô, mọi tự kiểm đạt

### Kế hoạch trang đầu trên mkt_lead (P0 và W)

#### page_lead public_read (P0): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8880.41 rows=50 width=1300) (actual time=1.323..1.480 rows=50 loops=1)
  Buffers: shared hit=130
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.008..0.008 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.116..0.116 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=1.160..1.160 rows=1 loops=1)
          Buffers: shared hit=79
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (never executed)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  ->  Result  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=1.322..1.472 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=130
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=1.307..1.445 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Buffers: shared hit=130
Planning:
  Buffers: shared hit=5127 read=10
Planning Time: 37.214 ms
Execution Time: 1.756 ms
```

#### page_lead own (P0): dùng chỉ mục records_p5_tenant_id_owner_id_object_id_created_at_id_idx

```
Limit  (cost=3.72..81.59 rows=1 width=1300) (actual time=5.462..9.825 rows=31 loops=1)
  Buffers: shared hit=114 read=30
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.012..0.013 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.002 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.005..0.006 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.180..0.181 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=1.664..1.665 rows=1 loops=1)
          Buffers: shared hit=79
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=1.461..1.462 rows=1 loops=1)
          Buffers: shared hit=26
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.100..0.100 rows=1 loops=1)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.892..0.892 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  ->  Result  (cost=0.55..78.42 rows=1 width=1300) (actual time=5.459..9.807 rows=31 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=114 read=30
        ->  Index Scan using records_p5_tenant_id_owner_id_object_id_created_at_id_idx on records_p5 records  (cost=0.55..78.42 rows=1 width=1300) (actual time=5.435..9.759 rows=31 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (owner_id = '00040000-0000-0000-0000-000000000309'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Buffers: shared hit=114 read=30
Planning:
  Buffers: shared hit=5136 read=1
Planning Time: 40.548 ms
Execution Time: 10.268 ms
```

#### page_lead own_sort_slot (P0): dùng chỉ mục records_p5_tenant_id_owner_id_object_id_created_at_id_idx

```
Limit  (cost=81.60..81.61 rows=1 width=1300) (actual time=22.452..22.462 rows=28 loops=1)
  Buffers: shared hit=18 read=39
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.011..0.012 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.002..0.002 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.002 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.171..0.172 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.646..0.646 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.680..0.680 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.045..0.045 rows=1 loops=1)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.547..0.547 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  ->  Sort  (cost=78.43..78.43 rows=1 width=1300) (actual time=22.450..22.453 rows=28 loops=1)
        Sort Key: records.t02 COLLATE "vi-VN-x-icu", records.id
        Sort Method: quicksort  Memory: 53kB
        Buffers: shared hit=18 read=39
        ->  Result  (cost=0.55..78.42 rows=1 width=1300) (actual time=2.189..2.463 rows=28 loops=1)
              One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
              Buffers: shared hit=15 read=32
              ->  Index Scan using records_p5_tenant_id_owner_id_object_id_created_at_id_idx on records_p5 records  (cost=0.55..78.42 rows=1 width=1300) (actual time=2.164..2.426 rows=28 loops=1)
                    Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (owner_id = '00040000-0000-0000-0000-000000000309'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
                    Filter: ((deleted_at IS NULL) AND (t02 IS NOT NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
                    Rows Removed by Filter: 3
                    Buffers: shared hit=15 read=32
Planning:
  Buffers: shared hit=1 read=41
Planning Time: 1.633 ms
Execution Time: 22.863 ms
```

#### page_lead team (P0): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8880.41 rows=50 width=1300) (actual time=2.601..27.486 rows=50 loops=1)
  Buffers: shared hit=8702 read=197
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.005..0.005 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.002 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.002 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.074..0.074 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.516..0.516 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.388..0.389 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.028..0.028 rows=1 loops=1)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.494..0.495 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.703..0.703 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.398..0.399 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.445..0.445 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.344..0.344 rows=1 loops=1)
          Buffers: shared hit=4
  ->  Result  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=2.600..27.468 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=8702 read=197
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=2.589..27.429 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Rows Removed by Filter: 20610
              Buffers: shared hit=8702 read=197
Planning:
  Buffers: shared read=37
Planning Time: 1.265 ms
Execution Time: 27.982 ms
```

#### page_lead team_sort_slot (P0): dùng chỉ mục records_p5_tenant_id_object_id_t02_id_idx

```
Limit  (cost=3.72..9698.72 rows=50 width=1300) (actual time=7.972..41.528 rows=50 loops=1)
  Buffers: shared hit=1381 read=5916
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.006..0.007 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.002 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.005..0.006 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.150..0.150 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.855..0.855 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.394..0.395 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.038..0.038 rows=1 loops=1)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.744..0.744 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.418..0.419 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.559..0.560 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.368..0.368 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.592..0.593 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.345..0.346 rows=1 loops=1)
          Buffers: shared hit=4
  ->  Result  (cost=0.55..189246.83 rows=976 width=1300) (actual time=7.971..41.501 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=1381 read=5916
        ->  Index Scan using records_p5_tenant_id_object_id_t02_id_idx on records_p5 records  (cost=0.55..189246.83 rows=976 width=1300) (actual time=7.958..41.454 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now()))))))
              Rows Removed by Filter: 7129
              Buffers: shared hit=1381 read=5916
Planning:
  Buffers: shared read=37
Planning Time: 1.336 ms
Execution Time: 42.125 ms
```

#### page_lead workspace_1 (P0): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8880.41 rows=50 width=1300) (actual time=51.987..69.556 rows=50 loops=1)
  Buffers: shared hit=113 read=11523
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.007..0.007 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.002 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.002..0.002 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.090..0.090 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.523..0.523 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.375..0.375 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.027..0.027 rows=1 loops=1)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.614..0.615 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.529..0.530 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.715..0.715 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.370..0.371 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.336..0.336 rows=1 loops=1)
          Buffers: shared hit=4
  ->  Result  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=51.985..69.536 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=113 read=11523
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=51.968..69.490 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Rows Removed by Filter: 27008
              Buffers: shared hit=113 read=11523
Planning:
  Buffers: shared read=37
Planning Time: 1.346 ms
Execution Time: 70.109 ms
```

#### page_lead workspace_40 (P0): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8880.41 rows=50 width=1300) (actual time=984.323..1197.337 rows=50 loops=1)
  Buffers: shared hit=142203 read=8673
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.006..0.006 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.002 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.002 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.135..0.136 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.639..0.639 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.398..0.398 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.036..0.036 rows=1 loops=1)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.430..0.430 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.633..0.633 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.386..0.387 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.355..0.355 rows=1 loops=1)
          Buffers: shared hit=4
  ->  Result  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=984.322..1197.314 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=142203 read=8673
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=984.307..1197.273 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Rows Removed by Filter: 20252
              Buffers: shared hit=142203 read=8673
Planning:
  Buffers: shared read=37
Planning Time: 1.363 ms
Execution Time: 1197.798 ms
```

#### page_lead company (P0): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8880.41 rows=50 width=1300) (actual time=0.834..1.972 rows=50 loops=1)
  Buffers: shared hit=126 read=29
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.007..0.007 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.002..0.002 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.002..0.002 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.096..0.096 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.607..0.608 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (never executed)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  ->  Result  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=0.833..1.960 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=126 read=29
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=0.818..1.929 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Buffers: shared hit=126 read=29
Planning:
  Buffers: shared hit=37
Planning Time: 1.419 ms
Execution Time: 2.245 ms
```

#### page_lead company_updated (P0): dùng chỉ mục records_p5_tenant_id_object_id_updated_at_id_idx

```
Limit  (cost=3.60..8882.25 rows=50 width=1300) (actual time=0.650..1.788 rows=50 loops=1)
  Buffers: shared hit=117 read=39
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.004..0.004 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.065..0.065 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.495..0.495 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (never executed)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  ->  Result  (cost=0.42..192667.25 rows=1085 width=1300) (actual time=0.649..1.779 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=117 read=39
        ->  Index Scan using records_p5_tenant_id_object_id_updated_at_id_idx on records_p5 records  (cost=0.42..192667.25 rows=1085 width=1300) (actual time=0.640..1.752 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Buffers: shared hit=117 read=39
Planning:
  Buffers: shared hit=37
Planning Time: 1.086 ms
Execution Time: 1.973 ms
```

#### page_lead company_name (P0): dùng chỉ mục records_p5_tenant_id_object_id_name_id_idx

```
Limit  (cost=3.72..8950.03 rows=50 width=1300) (actual time=2.379..3.775 rows=50 loops=1)
  Buffers: shared hit=116 read=42
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.006..0.006 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.004..0.004 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.137..0.137 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.879..0.879 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (never executed)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  ->  Result  (cost=0.55..194135.38 rows=1085 width=1300) (actual time=2.377..3.762 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=116 read=42
        ->  Index Scan using records_p5_tenant_id_object_id_name_id_idx on records_p5 records  (cost=0.55..194135.38 rows=1085 width=1300) (actual time=2.363..3.727 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Buffers: shared hit=116 read=42
Planning:
  Buffers: shared hit=37
Planning Time: 1.238 ms
Execution Time: 3.996 ms
```

#### page_lead manager_50 (P0): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8880.41 rows=50 width=1300) (actual time=3.177..48.003 rows=50 loops=1)
  Buffers: shared hit=1339 read=7988
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.004..0.004 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.002 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.063..0.063 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.523..0.523 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.521..0.521 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.035..0.035 rows=1 loops=1)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.469..0.469 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.386..0.386 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.760..0.760 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.344..0.344 rows=1 loops=1)
          Buffers: shared hit=4
  ->  Result  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=3.176..47.983 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=1339 read=7988
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=3.166..47.935 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Rows Removed by Filter: 21624
              Buffers: shared hit=1339 read=7988
Planning:
  Buffers: shared hit=37
Planning Time: 1.111 ms
Execution Time: 48.530 ms
```

#### page_lead manager_500 (P0): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8880.41 rows=50 width=1300) (actual time=4.591..511.492 rows=50 loops=1)
  Buffers: shared hit=40336 read=8582
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.004..0.005 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.067..0.067 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.494..0.494 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.386..0.386 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.026..0.026 rows=1 loops=1)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.376..0.377 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.363..0.364 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.622..0.622 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.337..0.338 rows=1 loops=1)
          Buffers: shared hit=4
  ->  Result  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=4.590..511.449 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=40336 read=8582
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=4.579..511.366 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Rows Removed by Filter: 20077
              Buffers: shared hit=40336 read=8582
Planning:
  Buffers: shared hit=37
Planning Time: 1.179 ms
Execution Time: 511.964 ms
```

#### page_lead manager_5000 (P0): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8880.41 rows=50 width=1300) (actual time=86.052..2879.275 rows=50 loops=1)
  Buffers: shared hit=81748 read=7268
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.003..0.004 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.059..0.059 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.423..0.424 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.340..0.340 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.024..0.024 rows=1 loops=1)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.463..0.463 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.375..0.375 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.678..0.679 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.347..0.348 rows=1 loops=1)
          Buffers: shared hit=4
  ->  Result  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=86.050..2879.209 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=81748 read=7268
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=86.040..2879.075 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Rows Removed by Filter: 20042
              Buffers: shared hit=81748 read=7268
Planning:
  Buffers: shared hit=37
Planning Time: 1.016 ms
Execution Time: 2879.707 ms
```

#### page_lead share_recipient (P0): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8880.41 rows=50 width=1300) (actual time=46.229..418.119 rows=50 loops=1)
  Buffers: shared hit=1705 read=82765 dirtied=19 written=2
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.005..0.005 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.065..0.065 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.690..0.691 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.579..0.579 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.031..0.032 rows=1 loops=1)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.993..0.993 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.466..0.467 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.448..0.448 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.381..0.381 rows=1 loops=1)
          Buffers: shared hit=4
  ->  Result  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=46.228..418.066 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=1705 read=82765 dirtied=19 written=2
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=46.217..417.916 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Rows Removed by Filter: 197538
              Buffers: shared hit=1705 read=82765 dirtied=19 written=2
Planning:
  Buffers: shared hit=37
Planning Time: 1.134 ms
Execution Time: 418.621 ms
```

#### page_lead agent_one_object (P0): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8880.41 rows=50 width=1300) (actual time=1.313..2.397 rows=50 loops=1)
  Buffers: shared hit=174 read=27
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.003..0.004 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.063..0.064 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.021..0.021 rows=1 loops=1)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.718..0.719 rows=1 loops=1)
          Buffers: shared hit=24 read=22
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.426..0.426 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (never executed)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  ->  Result  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=1.312..2.388 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=174 read=27
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=1.303..2.360 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Buffers: shared hit=174 read=27
Planning:
  Buffers: shared read=37
Planning Time: 1.206 ms
Execution Time: 2.597 ms
```

#### page_lead service_account (P0): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8880.41 rows=50 width=1300) (actual time=0.636..1.796 rows=50 loops=1)
  Buffers: shared hit=124 read=33 dirtied=2
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.005..0.005 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.068..0.069 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.485..0.485 rows=1 loops=1)
          Buffers: shared hit=5 read=1 dirtied=2
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (never executed)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  ->  Result  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=0.635..1.785 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=124 read=33 dirtied=2
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192627.25 rows=1085 width=1300) (actual time=0.624..1.754 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Buffers: shared hit=124 read=33 dirtied=2
Planning:
  Buffers: shared hit=37
Planning Time: 1.170 ms
Execution Time: 1.998 ms
```

#### page_lead public_read (W): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8825.42 rows=50 width=1300) (actual time=1.333..1.555 rows=50 loops=1)
  Buffers: shared hit=130
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.009..0.009 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.002..0.002 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.002 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.151..0.151 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=1.108..1.109 rows=1 loops=1)
          Buffers: shared hit=79
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (never executed)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  ->  Result  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=1.331..1.546 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=130
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=1.314..1.515 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Buffers: shared hit=130
Planning:
  Buffers: shared hit=5125 read=8
Planning Time: 37.115 ms
Execution Time: 1.910 ms
```

#### page_lead own (W): dùng chỉ mục records_p5_tenant_id_owner_id_object_id_created_at_id_idx

```
Limit  (cost=3.98..85.63 rows=1 width=1300) (actual time=4.123..8.707 rows=31 loops=1)
  Buffers: shared hit=114 read=30
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.107..0.107 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.008..0.009 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.002 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.004..0.004 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.153..0.153 rows=1 loops=1)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=1.286..1.287 rows=1 loops=1)
          Buffers: shared hit=79
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.671..0.671 rows=1 loops=1)
          Buffers: shared hit=26
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.044..0.044 rows=1 loops=1)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.473..0.473 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 16 (returns $15)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  ->  Result  (cost=0.55..82.20 rows=1 width=1300) (actual time=4.121..8.691 rows=31 loops=1)
        One-Time Filter: (($1 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($2 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=114 read=30
        ->  Index Scan using records_p5_tenant_id_owner_id_object_id_created_at_id_idx on records_p5 records  (cost=0.55..82.20 rows=1 width=1300) (actual time=4.106..8.626 rows=31 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (owner_id = $0) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($3 = 'tenant'::text) OR ((($4 = 'user'::text) OR (($5 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($6)))) AND ((object_id = ANY ($7)) OR (access_key = ANY ($8)) OR ((owner_id = $9) AND (object_id = ANY ($10))) OR ((owner_id = ANY ($11)) AND (object_id = ANY ($12))) OR ((owner_id = ANY ($13)) AND (object_id = ANY ($14))) OR ((read_grants && $15) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Buffers: shared hit=114 read=30
Planning:
  Buffers: shared hit=5128 read=2
Planning Time: 36.846 ms
Execution Time: 9.170 ms
```

#### page_lead own_sort_slot (W): dùng chỉ mục records_p5_tenant_id_owner_id_object_id_created_at_id_idx

```
Limit  (cost=85.64..85.65 rows=1 width=1300) (actual time=22.754..22.764 rows=28 loops=1)
  Buffers: shared hit=18 read=39
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.148..0.149 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.031..0.032 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.004..0.004 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.002..0.002 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.059..0.059 rows=1 loops=1)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.702..0.702 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.405..0.406 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.031..0.032 rows=1 loops=1)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.532..0.532 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 16 (returns $15)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  ->  Sort  (cost=82.21..82.21 rows=1 width=1300) (actual time=22.753..22.754 rows=28 loops=1)
        Sort Key: records.t02 COLLATE "vi-VN-x-icu", records.id
        Sort Method: quicksort  Memory: 53kB
        Buffers: shared hit=18 read=39
        ->  Result  (cost=0.55..82.20 rows=1 width=1300) (actual time=2.028..2.188 rows=28 loops=1)
              One-Time Filter: (($1 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($2 = '00010000-0000-0000-0000-000000000000'::uuid))
              Buffers: shared hit=15 read=32
              ->  Index Scan using records_p5_tenant_id_owner_id_object_id_created_at_id_idx on records_p5 records  (cost=0.55..82.20 rows=1 width=1300) (actual time=1.980..2.132 rows=28 loops=1)
                    Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (owner_id = $0) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
                    Filter: ((deleted_at IS NULL) AND (t02 IS NOT NULL) AND (($3 = 'tenant'::text) OR ((($4 = 'user'::text) OR (($5 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($6)))) AND ((object_id = ANY ($7)) OR (access_key = ANY ($8)) OR ((owner_id = $9) AND (object_id = ANY ($10))) OR ((owner_id = ANY ($11)) AND (object_id = ANY ($12))) OR ((owner_id = ANY ($13)) AND (object_id = ANY ($14))) OR ((read_grants && $15) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
                    Rows Removed by Filter: 3
                    Buffers: shared hit=15 read=32
Planning:
  Buffers: shared hit=1 read=41
Planning Time: 1.534 ms
Execution Time: 23.182 ms
```

#### page_lead team (W): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8825.42 rows=50 width=1300) (actual time=2.641..27.252 rows=50 loops=1)
  Buffers: shared hit=8711 read=197
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.006..0.007 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.002 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.002 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.075..0.076 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.562..0.563 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.447..0.447 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.031..0.031 rows=1 loops=1)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.396..0.397 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=1.189..1.190 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.419..0.420 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.706..0.706 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.335..0.336 rows=1 loops=1)
          Buffers: shared hit=4
  ->  Result  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=2.640..27.231 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=8711 read=197
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=2.627..27.189 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Rows Removed by Filter: 20620
              Buffers: shared hit=8711 read=197
Planning:
  Buffers: shared read=37
Planning Time: 1.403 ms
Execution Time: 27.775 ms
```

#### page_lead team_sort_slot (W): dùng chỉ mục records_p5_tenant_id_object_id_t02_id_idx

```
Limit  (cost=3.72..9631.80 rows=50 width=1300) (actual time=3.695..41.278 rows=50 loops=1)
  Buffers: shared hit=1382 read=5918 dirtied=1
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.005..0.006 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.003..0.003 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.101..0.102 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.605..0.605 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.548..0.548 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.041..0.042 rows=1 loops=1)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.758..0.759 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.386..0.387 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.535..0.535 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.398..0.399 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.660..0.661 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.372..0.372 rows=1 loops=1)
          Buffers: shared hit=4
  ->  Result  (cost=0.55..189481.07 rows=984 width=1300) (actual time=3.693..41.224 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=1382 read=5918 dirtied=1
        ->  Index Scan using records_p5_tenant_id_object_id_t02_id_idx on records_p5 records  (cost=0.55..189481.07 rows=984 width=1300) (actual time=3.682..41.151 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now()))))))
              Rows Removed by Filter: 7130
              Buffers: shared hit=1382 read=5918 dirtied=1
Planning:
  Buffers: shared read=37
Planning Time: 1.244 ms
Execution Time: 41.994 ms
```

#### page_lead workspace_1 (W): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8825.42 rows=50 width=1300) (actual time=49.144..66.097 rows=50 loops=1)
  Buffers: shared hit=119 read=11526
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.002..0.003 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.054..0.055 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.427..0.427 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.314..0.315 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.023..0.023 rows=1 loops=1)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.381..0.382 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.317..0.317 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.645..0.646 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.390..0.390 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.335..0.335 rows=1 loops=1)
          Buffers: shared hit=4
  ->  Result  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=49.143..66.077 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=119 read=11526
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=49.131..66.039 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Rows Removed by Filter: 27018
              Buffers: shared hit=119 read=11526
Planning:
  Buffers: shared read=37
Planning Time: 1.038 ms
Execution Time: 66.584 ms
```

#### page_lead workspace_40 (W): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8825.42 rows=50 width=1300) (actual time=899.688..1091.497 rows=50 loops=1)
  Buffers: shared hit=142280 read=8675
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.003..0.003 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.054..0.055 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.506..0.506 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.314..0.315 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.027..0.027 rows=1 loops=1)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.357..0.357 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.687..0.687 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.318..0.319 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.289..0.290 rows=1 loops=1)
          Buffers: shared hit=4
  ->  Result  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=899.687..1091.478 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=142280 read=8675
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=899.677..1091.440 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Rows Removed by Filter: 20262
              Buffers: shared hit=142280 read=8675
Planning:
  Buffers: shared read=37
Planning Time: 1.119 ms
Execution Time: 1091.907 ms
```

#### page_lead company (W): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8825.42 rows=50 width=1300) (actual time=0.866..2.062 rows=50 loops=1)
  Buffers: shared hit=124 read=31
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.004..0.005 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.002 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.002 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.257..0.258 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.523..0.523 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (never executed)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  ->  Result  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=0.865..2.050 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=124 read=31
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=0.855..2.012 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Buffers: shared hit=124 read=31
Planning:
  Buffers: shared hit=37
Planning Time: 1.205 ms
Execution Time: 2.289 ms
```

#### page_lead company_updated (W): dùng chỉ mục records_p5_tenant_id_object_id_updated_at_id_idx

```
Limit  (cost=3.60..8827.25 rows=50 width=1300) (actual time=0.601..1.688 rows=50 loops=1)
  Buffers: shared hit=127 read=30
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.004..0.005 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.056..0.056 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.467..0.467 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (never executed)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  ->  Result  (cost=0.42..192885.47 rows=1093 width=1300) (actual time=0.601..1.678 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=127 read=30
        ->  Index Scan using records_p5_tenant_id_object_id_updated_at_id_idx on records_p5 records  (cost=0.42..192885.47 rows=1093 width=1300) (actual time=0.591..1.653 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Buffers: shared hit=127 read=30
Planning:
  Buffers: shared hit=37
Planning Time: 1.167 ms
Execution Time: 1.858 ms
```

#### page_lead company_name (W): dùng chỉ mục records_p5_tenant_id_object_id_name_id_idx

```
Limit  (cost=3.72..8895.08 rows=50 width=1300) (actual time=1.646..2.783 rows=50 loops=1)
  Buffers: shared hit=116 read=42
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.003..0.003 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.002..0.002 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.068..0.068 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.448..0.448 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (never executed)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  ->  Result  (cost=0.55..194365.59 rows=1093 width=1300) (actual time=1.645..2.775 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=116 read=42
        ->  Index Scan using records_p5_tenant_id_object_id_name_id_idx on records_p5 records  (cost=0.55..194365.59 rows=1093 width=1300) (actual time=1.636..2.751 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Buffers: shared hit=116 read=42
Planning:
  Buffers: shared hit=37
Planning Time: 1.277 ms
Execution Time: 2.956 ms
```

#### page_lead manager_50 (W): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8825.42 rows=50 width=1300) (actual time=3.761..47.742 rows=50 loops=1)
  Buffers: shared hit=1356 read=7982 dirtied=1
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.007..0.008 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.002 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.002..0.002 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.168..0.169 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.613..0.613 rows=1 loops=1)
          Buffers: shared hit=6 dirtied=1
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.474..0.474 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.034..0.034 rows=1 loops=1)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.540..0.540 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.512..0.512 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.703..0.703 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.436..0.436 rows=1 loops=1)
          Buffers: shared hit=4
  ->  Result  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=3.759..47.717 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=1356 read=7982 dirtied=1
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=3.742..47.656 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Rows Removed by Filter: 21634
              Buffers: shared hit=1356 read=7982 dirtied=1
Planning:
  Buffers: shared hit=37
Planning Time: 1.315 ms
Execution Time: 48.184 ms
```

#### page_lead manager_500 (W): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8825.42 rows=50 width=1300) (actual time=4.385..481.950 rows=50 loops=1)
  Buffers: shared hit=40362 read=8585
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.003..0.004 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.054..0.054 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.444..0.445 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.341..0.341 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.024..0.024 rows=1 loops=1)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.346..0.346 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.329..0.330 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.592..0.592 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.307..0.307 rows=1 loops=1)
          Buffers: shared hit=4
  ->  Result  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=4.384..481.905 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=40362 read=8585
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=4.370..481.818 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Rows Removed by Filter: 20087
              Buffers: shared hit=40362 read=8585
Planning:
  Buffers: shared hit=37
Planning Time: 1.080 ms
Execution Time: 482.387 ms
```

#### page_lead manager_5000 (W): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8825.42 rows=50 width=1300) (actual time=88.193..2633.494 rows=50 loops=1)
  Buffers: shared hit=81791 read=7274
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.005..0.005 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.073..0.073 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.487..0.487 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.385..0.385 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.026..0.027 rows=1 loops=1)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.357..0.357 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.388..0.388 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.596..0.596 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.340..0.340 rows=1 loops=1)
          Buffers: shared hit=4
  ->  Result  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=88.192..2633.430 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=81791 read=7274
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=88.179..2633.297 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Rows Removed by Filter: 20052
              Buffers: shared hit=81791 read=7274
Planning:
  Buffers: shared hit=37
Planning Time: 1.356 ms
Execution Time: 2633.950 ms
```

#### page_lead share_recipient (W): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8825.42 rows=50 width=1300) (actual time=48.223..375.180 rows=50 loops=1)
  Buffers: shared hit=1722 read=82766 dirtied=20 written=2
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.008..0.008 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.002..0.003 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.113..0.113 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.571..0.571 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.387..0.387 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (actual time=0.026..0.026 rows=1 loops=1)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.678..0.679 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.386..0.386 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.355..0.355 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.328..0.328 rows=1 loops=1)
          Buffers: shared hit=4
  ->  Result  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=48.221..375.125 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=1722 read=82766 dirtied=20 written=2
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=48.207..374.988 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Rows Removed by Filter: 197548
              Buffers: shared hit=1722 read=82766 dirtied=20 written=2
Planning:
  Buffers: shared hit=37
Planning Time: 1.207 ms
Execution Time: 375.712 ms
```

#### page_lead agent_one_object (W): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8825.42 rows=50 width=1300) (actual time=1.372..2.544 rows=50 loops=1)
  Buffers: shared hit=173 read=27
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.003..0.003 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.050..0.050 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.021..0.021 rows=1 loops=1)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.709..0.709 rows=1 loops=1)
          Buffers: shared hit=23 read=22
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.505..0.505 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (never executed)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  ->  Result  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=1.371..2.536 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=173 read=27
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=1.363..2.510 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Buffers: shared hit=173 read=27
Planning:
  Buffers: shared read=37
Planning Time: 1.069 ms
Execution Time: 2.725 ms
```

#### page_lead service_account (W): dùng chỉ mục records_p5_tenant_id_object_id_created_at_id_idx

```
Limit  (cost=3.60..8825.42 rows=50 width=1300) (actual time=0.755..1.903 rows=50 loops=1)
  Buffers: shared hit=119 read=36
  InitPlan 1 (returns $0)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.003..0.004 rows=1 loops=1)
  InitPlan 2 (returns $1)
    ->  Result  (cost=0.00..0.02 rows=1 width=16) (actual time=0.001..0.001 rows=1 loops=1)
  InitPlan 3 (returns $2)
    ->  Result  (cost=0.00..0.01 rows=1 width=32) (actual time=0.001..0.002 rows=1 loops=1)
  InitPlan 4 (returns $3)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.064..0.064 rows=1 loops=1)
  InitPlan 5 (returns $4)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 6 (returns $5)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 7 (returns $6)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (actual time=0.569..0.570 rows=1 loops=1)
          Buffers: shared hit=4
  InitPlan 8 (returns $7)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 9 (returns $8)
    ->  Result  (cost=0.00..0.26 rows=1 width=16) (never executed)
  InitPlan 10 (returns $9)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 11 (returns $10)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 12 (returns $11)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 13 (returns $12)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 14 (returns $13)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  InitPlan 15 (returns $14)
    ->  Result  (cost=0.00..0.26 rows=1 width=32) (never executed)
  ->  Result  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=0.754..1.895 rows=50 loops=1)
        One-Time Filter: (($0 = '00010000-0000-0000-0000-000000000000'::uuid) AND ($1 = '00010000-0000-0000-0000-000000000000'::uuid))
        Buffers: shared hit=119 read=36
        ->  Index Scan using records_p5_tenant_id_object_id_created_at_id_idx on records_p5 records  (cost=0.42..192845.47 rows=1093 width=1300) (actual time=0.745..1.847 rows=50 loops=1)
              Index Cond: ((tenant_id = '00010000-0000-0000-0000-000000000000'::uuid) AND (object_id = '00030000-0000-0000-0000-000000000000'::uuid))
              Filter: ((deleted_at IS NULL) AND (($2 = 'tenant'::text) OR ((($3 = 'user'::text) OR (($4 = ANY ('{agent,workflow}'::text[])) AND (object_id = ANY ($5)))) AND ((object_id = ANY ($6)) OR (access_key = ANY ($7)) OR ((owner_id = $8) AND (object_id = ANY ($9))) OR ((owner_id = ANY ($10)) AND (object_id = ANY ($11))) OR ((owner_id = ANY ($12)) AND (object_id = ANY ($13))) OR ((read_grants && $14) AND ((grants_valid_until IS NULL) OR (grants_valid_until > now())))))))
              Buffers: shared hit=119 read=36
Planning:
  Buffers: shared hit=37
Planning Time: 1.080 ms
Execution Time: 2.098 ms
```

