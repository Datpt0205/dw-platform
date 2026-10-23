# 03 — Tình trạng pháp lý tháng 10/2026: chứng nhận dịch vụ xử lý dữ liệu cá nhân và văn bản hướng dẫn Luật AI

Type: research
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-73 `pdpl-certificate`, FOG-74 `vn-law-status`

## Câu hỏi

1. Giấy chứng nhận dịch vụ xử lý dữ liệu cá nhân (Nghị định 356/2025/NĐ-CP Điều 21-27, theo brief B11, chưa kiểm): có
   áp cho Studio không, có thời gian chuyển tiếp không, pháp nhân nào đứng tên, cần hồ sơ gì và bao lâu (FOG-73)?
2. Tình trạng tháng 10/2026 của các nghị định hướng dẫn Luật Trí tuệ nhân tạo 134/2025/QH15: tiêu chí rủi ro, danh mục
   rủi ro cao, định dạng gắn nhãn nội dung do AI tạo, thông báo lên cổng, ngưỡng sự cố, lưu nhật ký vận hành quá 13
   tháng (FOG-74)?
3. Nghị định xử phạt về dữ liệu cá nhân; Luật An ninh mạng 2025 và văn bản thay Nghị định 53 (lưu trữ trong nước, thời
   hạn lưu nhật ký) (FOG-74)?
4. Nghị định 356 Điều 4.2 (ghi lại việc đọc dữ liệu nhạy cảm, hạn chế dữ liệu cơ bản); trường lead-ad, UTM và hồ sơ
   mạng xã hội có là dữ liệu nhạy cảm "theo dõi hành vi" theo Điều 4.1(l) không (FOG-74)?

## Vì sao

Giấy chứng nhận có thể chặn việc bán, và điều kiện của nó mất nhiều tháng. Quy tắc mức rủi ro, hạn báo sự cố, lớp lưu
giữ và phân loại trường có thể đổi cổng phát hành và mặc định bảo mật trường của thí điểm.

## Mở khóa

- Spec: `compliance-pdpl` (02, 06), `agent-lifecycle` (mức rủi ro AI), `telemetry-and-audit` (lưu giữ),
  `field-security` (mặc định), `marketing-pilot` (trước khi chạy trên dữ liệu thật).
- ADR: 0106 (Open 6), 0122, 0123, 0125.
- DO: DO-53, DO-52, DO-60, DO-34. Ticket W1: `compliance-pdpl/02` (ready-for-human, tuần một).

## Đầu ra

- Một bảng văn bản: số hiệu, ngày ban hành, ngày hiệu lực, điều khoản liên quan, loại nguồn (văn bản gốc, bản dịch,
  bài thứ cấp), ngày đọc. Điều chưa tìm được văn bản ghi "chưa kiểm".
- Danh sách câu hỏi gửi luật sư cho `compliance-pdpl/02`. Ticket này tìm dữ kiện, không thay ý kiến luật sư: DO-53 và
  DO-60 do luật sư trả lời.
- Câu trả lời đổi mặc định bảo mật trường hay mức rủi ro AI thì ghi vào mục Open của ADR 0106 và ADR 0125.

## Nguồn

- Brief B4, B10a, B10b, B11, B12.
- [research.md](../research.md) mục 12 (Luật 91/2025/QH15, Nghị định 356/2025/NĐ-CP, Luật 134/2025/QH15; chưa có ý
  kiến luật sư; văn bản hướng dẫn chưa kiểm).

## Comments
