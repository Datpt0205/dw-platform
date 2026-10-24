# 02 — Khách thí điểm: số liệu, nguồn lead, người duyệt và file mẫu

Type: grilling
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-02 `pilot-customer`, FOG-06 `email-path`, FOG-14 `vn-encodings`, FOG-15 `hr-exports`, FOG-68 `polling-ok`

## Câu hỏi

Hỏi khách thí điểm (một đội marketing thật, DO-22) cùng bên yêu cầu, trong một buổi:

1. Khách là ai; người tài trợ và người duyệt tin là ai; nguồn lead và số lead mỗi tháng theo nguồn; thời gian phản hồi
   lead hiện nay; CRM đang dùng; tiêu chí chấm điểm lead (FOG-02).
2. Danh sách trường của Lead: kiểu, trường nào được lọc, trường nào là dữ liệu cá nhân; tìm theo vài số cuối của số
   điện thoại có quan trọng không (FOG-02)?
3. Hộp thư gửi đi: SMTP cho phép mật khẩu ứng dụng, một nhà cung cấp gửi thư qua HTTP, hay Google Workspace (FOG-06)?
4. File nhập của khách dùng UTF-8, Windows-1258, hay VNI và TCVN3 (Python không có codec VNI, TCVN3), và bao nhiêu phần
   (FOG-14)?
5. File xuất nhân sự (MISA AMIS HRM, Base, 1Office) có những cột và mã nào cho thành viên, quản lý trực tiếp và thuộc
   tính nhân sự (FOG-15)?
6. Người dùng thí điểm chấp nhận polling cho chat, hay token streaming là bắt buộc ở P1 (FOG-68)?
7. Khách có xác nhận đích của các kết quả đo được (KQ) trong `requirements.md` không, như DO-22 đòi trước chạy bóng?

## Vì sao

Mọi con số của thí điểm (khối lượng, ngân sách slot, đích thành công, bằng chứng đồng ý) là phỏng đoán tới khi có tên
khách. Đường email P1, bộ giải mã khi nhập, ánh xạ CSV nhân sự và việc relay qua Valkey và SSE có vào P1 hay không cùng
chờ câu trả lời này.

## Mở khóa

- Spec: `marketing-pilot` (02, 03), `custom-objects` (ngân sách slot, nhập), `usage-and-limits` (trần của thí điểm),
  `connections-and-vault` (05, email), `org-and-principals` (nhập CSV, W2), `agent-builder` (04, chat).
- ADR: 0107, 0117, 0121.
- DO: DO-22 (Đạt chốt 23/10/2026: một đội marketing thật, dữ liệu giả lập tới khi ký DPA), DO-48 (Đạt chốt
  23/10/2026: SMTP chung là đường email P1), DO-44 (polling hay streaming ở P1), DO-59 (đơn vị chi phí mỗi lead).

## Đầu ra

- Câu trả lời ghi ở `## Answer`, mỗi số kèm nguồn ("khách nói", "khách đo", "ước"); đích đã xác nhận chép vào
  `requirements.md`.
- Chỉ lấy dòng tiêu đề và bảng mã của file nhập và file xuất nhân sự; không đưa dòng dữ liệu người thật vào repo
  (DO-22, DO-54).
- Chưa có tên khách thì ghi đúng vậy: các đích giữ là đề xuất của brief B12, ngân sách slot chưa chốt.

## Nguồn

- Brief B2, B5, B8a, B9, B12.
- [research.md](../research.md) mục 13 (cột file nhân sự chưa kiểm), mục 15 (tần suất VNI, TCVN3 chưa kiểm).

## Comments
