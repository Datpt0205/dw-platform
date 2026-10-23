# 11 — Đồng ý lúc tiếp nhận lead và giới hạn chống tin rác cho sàn gửi tin

Type: research
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-03 `consent-intake`, FOG-75 `anti-spam`

## Câu hỏi

1. Ở mỗi nguồn lead của thí điểm (form website, Meta Lead Ads, Zalo), đồng ý được lấy thế nào, và nguồn đó đưa được
   bằng chứng gì: văn bản đã hiện, thời điểm, định danh form (FOG-03)?
2. Một ô đánh dấu đồng ý trên form có đủ theo Luật 91/2025/QH15 Điều 28.3 và Nghị định 356/2025/NĐ-CP Điều 6 không
   (điều khoản theo brief B11, chưa kiểm) (FOG-03)?
3. Giới hạn chống tin rác hiện hành (Nghị định 91/2020/NĐ-CP hoặc văn bản thay thế): tần suất, khung giờ gửi, danh sách
   Do Not Call quốc gia (FOG-75)?

## Vì sao

Thiếu bằng chứng đồng ý lúc tiếp nhận thì sàn gửi tin từ chối mọi lead và thí điểm không gửi được gì. Các số của sàn
gửi tin hiện là giữ chỗ ghi UNVERIFIED tới khi có câu trả lời.

## Mở khóa

- Spec: `compliance-pdpl` (02; 04: bản ghi đồng ý và sàn gửi tin), `marketing-pilot` (03, tiếp nhận),
  `workflow-triggers` (ánh xạ đồng ý từ sự kiện nhận).
- ADR: 0124.
- DO: DO-55 (số của sàn gửi tin và bằng chứng đồng ý; giữ chỗ 1 tin mỗi địa chỉ mỗi kênh mỗi 24 giờ, 08:00-20:00 giờ
  địa phương), DO-53.
- Ticket W1: `compliance-pdpl/02` (ready-for-human, ý kiến luật sư), `compliance-pdpl/04` (sàn gửi tin).

## Đầu ra

- Bảng theo nguồn: cách lấy đồng ý, bằng chứng có được, trường nào map vào bản ghi đồng ý; tài liệu kèm URL, ngày đọc
  và loại. Phần Meta và Zalo dùng kết quả của ticket 04 nếu đã có.
- Văn bản chống tin rác: số hiệu, hiệu lực, con số; điều chưa tìm được ghi "chưa kiểm". Số đã kiểm thay giữ chỗ trong
  `compliance-pdpl/04` và bỏ nhãn UNVERIFIED.
- Câu 2 và mọi câu cần diễn giải đi vào danh sách gửi luật sư của `compliance-pdpl/02`; ticket này không thay ý kiến
  luật sư.

## Nguồn

- Brief B11, B12.
- [research.md](../research.md) mục 12 (giới hạn của Nghị định 91/2020/NĐ-CP chưa kiểm; chưa có ý kiến luật sư).

## Comments
