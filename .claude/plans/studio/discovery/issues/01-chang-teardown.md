# 01 — Quan sát chang.fpt.net bằng tài khoản thử theo danh sách kiểm của teardown

Type: research
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-01 `chang`

## Câu hỏi

Dùng tài khoản thử trên https://chang.fpt.net (D10), chỉ quan sát như một người dùng thường, trả lời danh sách kiểm
A-J ở mục "Danh sách kiểm khi có tài khoản thử" của [teardown-chang.md](../teardown-chang.md):

1. Danh mục bước của quy trình: mọi loại bước, cấu hình và đầu ra, cú pháp biểu thức, vòng lặp, song song, chính sách
   lỗi, quy trình con, chạy thử và lịch sử từng bước (mục B).
2. Data Hub: endpoint xác thực thế nào, có chữ ký không, schema có được ép không, chống trùng, phát lại, lịch sử sự kiện
   giữ bao lâu (mục C).
3. Agent: "Brain (Beta)" là gì, "Liên kết Agent" nghĩa là gì, luồng "Ủy quyền hành động", danh sách người được dùng (chi
   nhánh, mã chức danh, văn phòng) lấy từ đâu, phiên bản và diff, chiều của "Cấu hình limit" (phạm vi, cứng hay mềm),
   các số trên màn "Mức độ sử dụng" (mục D).
4. Kiểm định: định dạng bộ đề và ngân hàng câu hỏi, kiểm định retrieval, kiểm định đầy đủ và nhẹ, ngưỡng cổng, trượt
   cổng có chặn Publish không (mục E).
5. Skills, Plugin, MCP, Credentials: mô hình dữ liệu và phạm vi, ai tạo được, bí mật có hiện lại sau khi lưu không,
   OAuth có tự làm mới không, webhook gửi đi có ký không (mục F).
6. Control plane: "lệch cấu hình" và "Component chờ xử lý" định nghĩa thế nào, đóng băng có dừng lượt đang chạy không
   (mục G).
7. Bảo mật quan sát được: có những vai quản trị nào, ai tạo được agent, quy trình, kết nối; có quyền theo đối tượng, bản
   ghi hay trường không; kiểu id trên URL của đối tượng do chính mình tạo (chỉ nhìn, không dò); TLS; nhật ký audit ghi
   gì (mục A và H).
8. DataTable: kiểu trường, giới hạn, định dạng nhập, "Mô tả ngữ nghĩa AI" dùng vào đâu; ZNS có chế độ thử không (mục I).

## Vì sao

Khách sẽ so Studio với sản phẩm này. Khóa quyền và mức rủi ro, ngữ nghĩa cổng chất lượng, chiều hạn mức và tín hiệu lệch
cấu hình trong các brief hiện được chỉnh theo phỏng đoán từ tám ảnh chụp.

## Mở khóa

- Spec: `tenant-rbac` (khóa quyền, mức rủi ro), `agent-lifecycle` (cổng, đóng băng), `usage-and-limits` (chiều hạn
  mức), `workflow-nodes` (danh mục bước), `connections-and-vault` (phạm vi), `tenant-config` (tín hiệu lệch cấu hình).
- ADR: 0104, 0110, 0112, 0115, 0120, 0121. Tài liệu: [teardown-chang.md](../teardown-chang.md), phần so sánh đối thủ
  của `requirements.md`.
- DO: DO-23 (luật dùng tài khoản; khuyến nghị (a), Đạt chốt 23/10/2026).

## Quy tắc và đầu ra

- Theo mục "Quy tắc khi dùng tài khoản thử" của teardown (DO-23): không quét, không tạo tải, không dò; chỉ thao tác
  trên đối tượng mình tạo, với dữ liệu giả lập; không chép tên người, email, prompt hay dữ liệu nghiệp vụ của họ vào
  repo.
- Mỗi mục ghi một dòng `Quan sát | Màn | Hệ quả cho Studio | Độ chắc` vào teardown, kèm ngày và trình duyệt; rồi cập
  nhật bảng "So sánh với Studio" và mở câu hỏi mới trong spec liên quan.
- Chờ: tài khoản thử do bên yêu cầu cấp (D10). Trước khi có tài khoản, ticket không làm được và không đoán thay.

## Nguồn

- Brief B3, B4, B5, B8a, B8b, B9, B10a, B10b, B12; tám ảnh chụp ngày 22/10/2026 tóm trong teardown.
- [research.md](../research.md) mục 16 (chang.fpt.net là sản phẩm nào và "Brain (Beta)" làm gì: chưa kiểm).

## Comments
