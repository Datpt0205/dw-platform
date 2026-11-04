# 25 — Presidio trên dữ liệu cá nhân tiếng Việt: họ tên, địa chỉ, CCCD, số điện thoại

Type: prototype
Status: ready-for-agent
Area: studio · Viết: 23/10/2026
FOG: FOG-77 `presidio`

## Câu hỏi

Presidio với bộ nhận dạng tiếng Việt đạt precision và recall bao nhiêu trên họ tên, địa chỉ, số CCCD và số điện thoại
trong văn bản tiếng Việt: lời nhắn tự do của lead, ghi chú, hội thoại?

## Vì sao

Quyết `cross_border_minimised` có bán được không: lộ trình này chỉ có nghĩa khi dữ liệu cá nhân được che trước khi ra
nước ngoài. Cũng quyết việc che trong telemetry dựa được vào phát hiện tới đâu. Presidio tốn CPU trên đường nóng và làm
image lớn thêm một model NLP (`docs/adr/0106-field-access-follows-personal-data-category.md:129`).

YC87 (W1) đã đòi che số điện thoại và email trong lời nhắn tự do trước bước chấm điểm; ticket này đo phần một biểu thức
chính quy không bắt được: họ tên và địa chỉ, và CCCD lẫn trong văn bản.

## Mở khóa

- Spec: `compliance-pdpl` (03, lộ trình dữ liệu), `telemetry-and-audit` (che dữ liệu), `field-security`.
- ADR: 0123, 0106 (Open 5), 0122.
- DO: DO-54 (`vn_only` mặc định; ra nước ngoài cần xác nhận có chữ ký nêu bên xử lý), DO-51.

## Dựng tối thiểu

Presidio với bộ nhận dạng tiếng Việt (mẫu cho số điện thoại `+84` và CCCD; NER cho họ tên và địa chỉ) chạy trên bộ lead
giả lập có nhãn của `marketing-pilot/01`, gồm văn bản không dấu, viết tắt và địa chỉ theo danh sách tỉnh sau sáp nhập
2025 (ticket 27).

## Phép đo quyết định

| Đo                                                      | Ngưỡng                                            | Quyết định                                        |
| ------------------------------------------------------- | ------------------------------------------------- | ------------------------------------------------- |
| Recall theo loại (họ tên, địa chỉ, CCCD, số điện thoại) | Chưa có ngưỡng; luật sư và Đạt chốt mức chấp nhận | Có `cross_border_minimised` ở v1 không (ADR 0123) |
| Precision theo loại                                     | Ghi số                                            | Che quá tay có làm hỏng câu trả lời không         |
| CPU mỗi 1.000 ký tự; cỡ image tăng thêm                 | Ghi số                                            | Chi phí ghi vào ADR 0106                          |

Bộ nhãn là dữ liệu giả lập; không đưa văn bản của người thật vào repo (DO-22, DO-54).

## Nguồn

- Brief B11; `docs/adr/0106-field-access-follows-personal-data-category.md` (Open 5).
- [research.md](../research.md) mục 12 (độ chính xác của Presidio với dữ liệu cá nhân tiếng Việt chưa kiểm).

## Việc của agent (phân loại 4/11/2026)

- Câu hỏi: precision và recall theo loại (họ tên, địa chỉ, CCCD, số điện thoại) của Presidio với bộ nhận dạng
  tiếng Việt trên lời nhắn lead giả lập; CPU mỗi 1.000 ký tự; cỡ image tăng thêm.
- Cách làm: spike dưới `tests/spike/presidio/`, venv tạm, `presidio-analyzer` và một mô hình NER tiếng Việt công
  khai ghim đúng phiên bản (ghi tên, giấy phép, cỡ); bộ nhận dạng mẫu cho số `+84` và số nội địa, CCCD 12 chữ số.
  Tập có nhãn: từ bộ sinh của marketing-pilot/01 (`tests/e2e/marketing_pilot/generator.py`, hạt giống cố định),
  mở rộng bằng nhãn span cho họ tên (danh sách tên của bộ sinh), địa chỉ (danh sách tỉnh sau sáp nhập 2025 của
  ticket 27 câu 1), CCCD giả lập, số trong dải thử `+84900000000`-`+84900009999`; có dấu và không dấu, viết tắt;
  ít nhất 500 lời nhắn; không văn bản của người thật.
- Đầu ra: `## Answer` (bảng theo loại kèm phiên bản và máy), một dòng vào Open 5 của ADR-0106 (Accepted).
- Đạt khi: bảng đủ ô; recall số điện thoại và CCCD bằng 1,0 trên tập (YC87 đã đòi che số điện thoại). Đề xuất,
  chưa chốt (Đạt và luật sư chốt mức chấp nhận): recall họ tên và địa chỉ ≥ 0,95 thì giữ `cross_border_minimised`
  cho W2, thấp hơn thì đề xuất bỏ khỏi v1 (ADR-0123).

## Comments

- 2026-11-04 (agent, phân loại G12, theo ủy quyền 31/10/2026): `ready-for-agent`. Chưa câu nào được đo, Presidio chưa có trong repo; spec `compliance-pdpl` để nó ở W2 và compliance-pdpl/03 từ chối đích `foreign` của `cross_border_minimised` tới lúc đó. Không cần người, khóa hay máy riêng: bộ nhãn là dữ liệu giả lập; chỉ mức chấp nhận là của Đạt và luật sư.
