# 02 — Ý kiến luật sư Việt Nam cho PDPL và Luật AI

Status: ready-for-human
Area: studio
Yêu cầu: không (ticket pháp lý; thu thập ý kiến luật sư, không chứng minh mã của spec)

## Mục tiêu

Gửi luật sư Việt Nam danh sách câu hỏi PDPL và Luật AI, kèm sơ đồ luồng dữ liệu của lát Marketing, và ghi
câu trả lời có ngày vào Comments rồi chuyển vào ADR liên quan. Ý kiến này gỡ chặn số liệu và vai trò bên
xử lý mà ticket 03, 04, 06 chờ, và trả lời Q1, Q2 của spec.

## Việc cần làm

1. Soạn danh sách câu hỏi cho luật sư, mỗi câu một DO:
    - DO-53: Studio có phải "dịch vụ xử lý dữ liệu cá nhân" cần giấy chứng nhận Bộ Công an trước tenant trả
      phí đầu tiên (Nghị định 356 Điều 21-27), và bên nào giữ?
    - DO-54: nền tảng là bên xử lý, công ty khách là bên kiểm soát, DPA ký trước khi chạy ngầm, mặc định
      `vn_only`, ai nộp DPIA và CTIA?
    - DO-55: số chống spam (tần suất, khung giờ, số người nhận mỗi lượt), lời văn đồng ý của người nhận
      thử, thời hạn hiệu lực và ai được thêm?
    - DO-60: ai là nhà cung cấp một agent do công ty khách dựng theo Luật AI, agent marketing có phải rủi
      ro trung bình, công ty được khai tầng dưới đề xuất không, tin AI soạn có người duyệt có phải gắn
      nhãn?
2. Đính kèm sơ đồ luồng dữ liệu lát Marketing (nguồn lead, chấm điểm, tạo bản ghi, gửi tin).
3. Nhận ý kiến bằng văn bản; ghi từng câu trả lời và ngày vào Comments.
4. Chuyển mỗi câu trả lời vào ADR liên quan (ADR-0123 (Proposed), ADR-0124 (Proposed), ADR-0106 (Proposed),
   ADR-0125 (Proposed)) hoặc dòng Quyết định của spec, qua writing-plan-specs, kèm ngày.

## Tiêu chí chấp nhận

- [ ] Mỗi câu (DO-53, DO-54, DO-55, DO-60) có câu trả lời bằng văn bản hoặc "chưa có hướng dẫn" kèm ngày,
      ghi ở Comments.
- [ ] Mỗi câu trả lời được chuyển vào ADR liên quan hoặc dòng Quyết định của spec, kèm ngày.
- [ ] Xong: `python -I scripts/check_plans.py --advisory --path .claude/plans/studio/compliance-pdpl` xanh.

## Nguồn

- Research mục 11 (PDPL 91/2025/QH15, Nghị định 356/2025/ND-CP, Luật AI 134/2025/QH15); DO-53, DO-54,
  DO-55, DO-60.

## Comments

- 2026-10-23 (agent): B11-security compliance-pdpl 11. Bắt đầu tuần đầu W1 cùng hồ sơ nhà cung cấp. Số Sàn
  gửi tin, thời hạn lưu và vai trò bên xử lý chờ câu trả lời; tới khi có, lát Marketing chỉ chạy lead giả
  lập (YC89).
