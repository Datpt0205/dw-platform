# 19 — Chất lượng model trên tiếng Việt: chấm điểm lead, model trong nước, cổng chất lượng, chọn công cụ

Type: prototype
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-09 `scoring-quality`, FOG-10 `vn-models`, FOG-64 `gate-flakiness`, FOG-67 `tool-selection`

## Câu hỏi

1. Chấm điểm lead tiếng Việt theo từng hồ sơ model ứng viên: token mỗi lead, tỉ lệ đầu ra có cấu trúc hợp lệ sau một lần
   sửa, độ trễ, nhất quán pass^3, chi phí mỗi lead; số ký tự tiếng Việt mỗi token theo model để ước lượng trước lời gọi
   (FOG-09)?
2. Model trong nước nào (FPT AI Factory, Viettel MaaS, VNPT, vLLM tự host) đạt chất lượng và chi phí của thí điểm dưới
   `vn_only`, và có chấm được đầu ra tiếng Việt đủ để hiệu chỉnh cổng không (FOG-10)? Phần "gateway của bên yêu cầu đi ra
   đâu" thuộc ticket 18.
3. k và ngưỡng nào tránh trượt giả với chi phí chấp nhận được; chi phí cổng xấu nhất (số câu nhân số lần nhân trần) so
   với ngân sách kiểm định tháng thực tế; bộ kiểm định an ninh nền tảng tất định và chung có ý nghĩa với agent no-code
   không; promptfoo có dùng được làm bộ sinh offline không (FOG-64)?
4. Mô tả công cụ tiếng Việt và số công cụ ảnh hưởng độ chính xác chọn công cụ thế nào trên model mục tiêu (để đặt
   `max_visible_tools`); lịch sử theo ngân sách token và chất lượng tóm tắt trên hội thoại tiếng Việt ra sao (FOG-67)?

## Vì sao

Đặt model của thí điểm, k của cổng và các ước lượng hạn mức. Không có lộ trình trong Việt Nam thì công ty `vn_only` (mặc
định) không có AI. Số của cổng là phỏng đoán tới khi đo.

## Mở khóa

- Spec: `marketing-pilot` (03, bước chấm điểm), `agent-lifecycle` (02, 04: số của cổng), `usage-and-limits` (ước
  lượng), `model-connections` (danh mục), `compliance-pdpl` (03, lộ trình dữ liệu), `tools-and-skills`,
  `agent-builder`.
- ADR: 0120, 0123, 0118, 0116, 0117.
- DO: DO-29 (số của cổng, ai trả chi phí kiểm định), DO-50 (Đạt chốt 23/10/2026: kiểm định trả từ ngân sách công
  ty), DO-54, DO-59. Ticket W1: `agent-lifecycle/02` (P0) dựng khung chạy lặp k lần dùng ở đây.

## Dựng tối thiểu

Khung `dw_evals` chạy lặp k lần với `JudgePort` (như `agent-lifecycle/02`), trên bộ lead giả lập tiếng Việt của
`marketing-pilot/01` cộng nhãn hạng do khách thí điểm chấm (ticket 02); các hồ sơ model ứng viên, có model trong nước
nếu câu 2 tìm được; một agent chỉ đọc với số công cụ tăng dần, mô tả bằng tiếng Việt.

## Phép đo quyết định

| Đo                                            | Ngưỡng                         | Quyết định                                  |
| --------------------------------------------- | ------------------------------ | ------------------------------------------- |
| Khớp hạng với người; pass^3                   | KQ4: ≥ 80%; ≥ 95%              | Model của thí điểm                          |
| Bước AI p95                                   | YC100: ≤ 20 giây               | Model và cách gọi                           |
| Chi phí mỗi lead                              | KQ12, đơn vị theo DO-59        | Ước lượng hạn mức                           |
| Model trong nước đạt hai dòng trên            | Có hay không                   | `vn_only` có AI ở thí điểm không (ADR 0123) |
| Tỉ lệ trượt giả theo k; chi phí cổng xấu nhất | Chưa có ngưỡng; DO-29 chốt     | k, ngưỡng, ai trả                           |
| Độ chính xác chọn công cụ theo số công cụ     | Chưa có ngưỡng; ghi đường cong | `max_visible_tools`                         |

## Nguồn

- Brief B7b, B8b, B9, B10a, B10b, B11, B12.
- [research.md](../research.md) mục 6 (chọn công cụ với mô tả tiếng Việt chưa kiểm), mục 11 (số token của văn bản tiếng
  Việt chưa kiểm).

## Comments
