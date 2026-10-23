# 20 — Đo trên host cỡ thí điểm: dung lượng, bộ nhớ dịch vụ mới, công tắc, khoản giữ trước, khối lượng audit

Type: prototype
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-13 `pilot-capacity`, FOG-23 `host-memory`, FOG-65 `switch-cache`, FOG-70 `lease-cost`, FOG-72 `audit-volume`

## Câu hỏi

1. Host 2 vCPU / 8 GB, worker giới hạn 1 CPU / 1 GB (`infra/compose/docker-compose.prod.yml:34-41`), có chạy được
   2.000 lead mỗi ngày không; cỡ UAT cho dung lượng tuyệt đối nào (worker, kết nối, lượt chạy đang chờ mỗi công ty)
   trước khi đặt hạn mức của gói dịch vụ (FOG-13)?
2. Bộ nhớ lúc rảnh và lúc tải P1 của OpenBao, smokescreen, `mcp-gateway` và `model-proxy` trên host đó, khi trần
   production đã cộng tới 7,0 GB (`infra/compose/docker-compose.prod.yml:27-71`) cộng 3 GB của docgen
   (`infra/compose/docker-compose.yml:369`) (FOG-23)?
3. Cache công tắc điều khiển: độ trễ NOTIFY, LISTEN rớt và nối lại, p99 của một lần kiểm; ngưỡng 30 giây rồi chuyển
   sang chặn (fail closed) có đúng không (FOG-65)?
4. Hai lần ghi khoản giữ trước mỗi lời gọi và khóa bộ đếm hạn mức khi chiến dịch dồn tải; cỡ mỗi khoản giữ trước; chi
   phí tính lại một ngày của công ty ở khối lượng thí điểm (chu kỳ lane, độ tươi của màn Mức độ sử dụng) (FOG-70)?
5. Khối lượng nhật ký kiểm toán khi ghi bản ghi và lệnh trong môi trường chạy mã đều được audit; độ trễ lọc mỗi
   partition với index mới (FOG-72)?

## Vì sao

D14 đòi đo trước khi chốt cỡ host, và hạn mức của gói dịch vụ cần một trần đo được. Công tắc tắt khẩn cấp không được thấy trong
nhiều phút thì không phải công tắc. Hạn mức cứng trong PostgreSQL không được thành nút thắt. Nhật ký kiểm toán chỉ thêm
và giữ 1095 ngày (`configs/policies/retention@1.7.0.yaml:120-121`).

## Mở khóa

- Spec: `usage-and-limits` (01, 03: số của gói dịch vụ, khoản giữ trước), `agent-lifecycle` (01, 05), `connections-and-vault`,
  `mcp-client`, `model-connections`, `telemetry-and-audit`, `marketing-pilot`.
- ADR: 0115 (Open 3), 0118, 0120, 0121, 0122.
- DO: DO-24 (D14), DO-50 (agent, tạm). Ticket W1: `agent-lifecycle/01` (NOTIFY cho cache công tắc),
  `usage-and-limits/03`.

## Dựng tối thiểu

Một VM cỡ host (2 vCPU / 8 GB, rồi 4 vCPU / 16 GB theo D14) chạy stack compose production cộng bốn dịch vụ mới; một
script tải đẩy lead giả lập qua đường tiếp nhận nguyên mẫu (ghi bản ghi, audit, run, hai lần ghi khoản giữ trước mỗi lời
gọi model giả); một bài cắt kết nối LISTEN cho cache công tắc.

## Phép đo quyết định

| Đo                                | Ngưỡng                                                | Quyết định                         |
| --------------------------------- | ----------------------------------------------------- | ---------------------------------- |
| 2.000 lead mỗi ngày               | YC100: bước AI p95 ≤ 20 giây, tiếp nhận p95 ≤ 60 giây | Cỡ host và hạn mức của gói dịch vụ |
| Bộ nhớ từng dịch vụ mới           | Tổng trần dưới RAM của host                           | Cỡ của D14 (ADR 0115 Open 3)       |
| Đóng băng tới mọi tiến trình      | KQ9 và YC72: ≤ 5 giây                                 | Giữ hay đổi ngưỡng 30 giây         |
| Ghi khoản giữ trước khi dồn tải   | Chưa có ngưỡng; ghi p95 và tranh khóa                 | Cỡ khoản giữ trước, chu kỳ lane    |
| Audit mỗi lead; lọc mỗi partition | Ghi số; ước dung lượng cho 1095 ngày                  | Index và partition của audit       |

## Nguồn

- Brief B1, B7a, B10a, B10b, B12.
- [research.md](../research.md) mục 5 và 11 (không số nào đo trên host 2 vCPU / 8 GB; chi phí khoản giữ trước chưa
  kiểm).

## Comments
