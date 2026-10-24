# 23 — Keycloak 26.8: Organizations, brokering, `email_verified` và lời mời khi tắt đăng ký

Type: prototype
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-78 `keycloak`

## Câu hỏi

Trên Keycloak 26.8 (repo đang ghim 26.7.2 ở `infra/compose/docker-compose.yml:172`):

1. Organizations với mapper session note `identity_provider` và brokering SAML: MFA của Entra hay Google có tới được
   claim `amr` không?
2. Token của realm `dw` có mang `email_verified` không, và IdP được broker có đặt nó không?
3. Người được mời không có IdP công ty lấy tài khoản thế nào khi đăng ký tự do đang tắt và realm không có SMTP?
4. Làm mới ngầm với token 300 giây và xoay vòng refresh token giữa nhiều tab có chạy đúng không?
5. Quyền quản trị chi tiết có đăng xuất được một người dùng mà không cần quyền `manage-users` toàn realm không?

## Vì sao

Bản sửa nối danh tính (chỉ nối qua email đã xác minh, subject theo issuer) không được khóa ngoài mọi người được mời.
Chính sách MFA cần `amr`. research.md mục 13 ghi một đường chiếm tài khoản khi tenant tự mang IdP gắn vào Organization.

## Mở khóa

- Spec: `foundations-hardening` (02, nối danh tính), `org-and-principals` (01, 02, 03).
- ADR: 0102, 0103.
- DO: DO-17 (Organizations trong một realm; tài khoản dịch vụ là một dòng `platform.users`), DO-39 (Đạt chốt 23/10/2026:
  link nhận lời mời do quản trị viên chép; MFA cho người vận hành, nhân viên hỗ trợ và người giữ quyền trọng yếu).
- Ticket W1: `foundations-hardening/02`, `org-and-principals/01` (P0).

## Dựng tối thiểu

Keycloak 26.8.x trong compose dev, realm `dw` nhập từ `infra/keycloak` với Organizations bật; một IdP Google và một IdP
SAML thử, dùng tài khoản thử, không người thật; một người được mời không có IdP; ứng dụng web mở trên hai tab.

## Phép đo quyết định

| Đo                                  | Kết quả cần biết                      | Quyết định                        |
| ----------------------------------- | ------------------------------------- | --------------------------------- |
| `amr` sau MFA qua broker            | Có hay không, theo từng IdP           | MFA kiểm ở đâu (DO-39)            |
| `email_verified` theo IdP           | Có, đúng hay thiếu                    | Điều kiện nối danh tính           |
| Người được mời không có IdP         | Có đường lấy tài khoản không cần SMTP | Link nhận lời mời đủ hay cần SMTP |
| Hai tab với xoay vòng refresh token | Không tab nào bị đăng xuất sai        | Cấu hình token                    |
| Đăng xuất bằng quyền chi tiết       | Được hay không                        | Credential của API quản trị       |

Nâng từ 26.7.2 lên 26.8 chưa có ticket W1 nào nhận; kết quả ở đây quyết có cần nâng không.

## Nguồn

- Brief B2, B11; [research.md](../research.md) mục 13 (đo trên 26.7.2 và 26.8.1; MFA qua brokering chưa kiểm).
- Keycloak 26.8.0 ngày 01/10/2026 đổi cách kiểm domain của Organization:
  <https://www.keycloak.org/2026/10/keycloak-2680-released> (_documented_, theo research).

## Comments
