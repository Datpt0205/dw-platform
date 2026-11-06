# Tài khoản của khách: từ lời mời tới lần đăng nhập đầu

Status: needs-triage
Area: go-live · Nhánh: `main` · Viết: 6/11/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Người được mời vào một công ty cần tự có mật khẩu và tự đăng nhập được, vì hôm nay chỉ người vận hành mở bảng quản trị Keycloak mới tạo được tài khoản, và không khách nào đi qua được đường đó.

## Hiện trạng (đã kiểm ở `6fe88f7b` ngày 6/11/2026)

- Realm tắt tự đăng ký (`infra/keycloak/dw-realm.json:5`) và tắt quên mật khẩu (`infra/keycloak/dw-realm.json:8`), trong khi bật xác minh email (`infra/keycloak/dw-realm.json:9`). Thiếu: realm không có `smtpServer`, nên thư xác minh cũng không đi được.
- Realm chỉ nạp lúc khởi động trên database rỗng (`infra/compose/docker-compose.yml:202`). Ràng buộc: đổi cấu hình realm trên cụm đang chạy đi qua `scripts/keycloak_realm_settings.py:35`, script đó chưa có `resetPasswordAllowed` và `smtpServer`.
- `RoleAssignmentService.invite` tạo người "no sign-in yet" và membership, không gửi gì (`packages/python/dw_platform/src/dw_platform/application/role_assignments.py:335`). Route ghi rõ không gửi thư (`apps/api/src/dw_api/routes/v1/admin_members.py:388`). Thiếu: người được mời không biết mình được mời.
- Danh tính mới đã xác thực có dòng người dùng, không membership nào (`packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:8`). Ràng buộc: phải giữ từ chối mặc định này.
- Tạo công ty là route của người vận hành, kèm hai chủ sở hữu (`apps/api/src/dw_api/routes/v1/platform.py:163`). Ràng buộc: lối tài khoản chạy cả cho hai chủ này.

## Mục tiêu

### R1 — Lời mời tới hộp thư

Người được mời nhận thư và tự đặt mật khẩu.

- R1.1 KHI một lời mời tạo một người chưa có tài khoản đăng nhập, nền tảng PHẢI tạo tài khoản đó ở nhà cung cấp danh tính.
- R1.2 KHI tài khoản được tạo, nhà cung cấp danh tính PHẢI gửi thư đặt mật khẩu tới đúng email của lời mời.
- R1.3 NẾU người được mời đã có tài khoản đăng nhập, THÌ nền tảng PHẢI gắn membership vào người hiện có và không tạo tài khoản thứ hai.
- R1.4 NẾU nhà cung cấp danh tính không trả lời, THÌ lời mời PHẢI vẫn ghi được và được gửi lại tự động, không mất.
- R1.5 Quản trị viên công ty PHẢI gửi lại được thư mời cho người còn ở trạng thái `invited` của công ty mình.
- R1.6 NẾU người gọi gửi lại thư cho người của công ty khác, THÌ nền tảng PHẢI trả 404 như người chưa từng tồn tại.

### R2 — Tự đặt lại mật khẩu

Người dùng không cần ai giúp khi quên mật khẩu.

- R2.1 KHI người dùng chọn quên mật khẩu, nhà cung cấp danh tính PHẢI gửi thư đặt lại tới email của họ.
- R2.2 NẾU email không có tài khoản, THÌ màn hình PHẢI trả cùng một câu như khi có tài khoản.

### R3 — Thư của nền tảng đi được

Thư hệ thống tới hộp thư thật.

- R3.1 Ở môi trường triển khai, nhà cung cấp danh tính PHẢI gửi thư qua máy chủ thư cấu hình từ biến môi trường.
- R3.2 NẾU thiếu cấu hình máy chủ thư ở môi trường triển khai, THÌ api PHẢI từ chối khởi động.
- R3.3 Tự đăng ký PHẢI tiếp tục tắt ở mọi môi trường.

### R4 — Không có đường vòng

Tài khoản không mở cửa vào công ty.

- R4.1 NẾU một người đăng nhập chưa có membership nào, THÌ api PHẢI trả trạng thái chưa được mời và 0 dữ liệu của công ty nào.
- R4.2 Khóa quản trị nhà cung cấp danh tính PHẢI chỉ có ở tiến trình api và chỉ mang quyền `manage-users` của realm `dw`.
- R4.3 NẾU người dùng bị vô hiệu ở mọi công ty do offboarding, THÌ tài khoản đăng nhập PHẢI bị tắt.

### R5 — Chấp nhận điều khoản

Chủ sở hữu thấy và chấp nhận điều khoản trước khi dùng.

- R5.1 KHI chủ sở hữu vào lần đầu mà chưa chấp nhận phiên bản điều khoản hiện hành, web PHẢI hiện điều khoản và DPA trước mọi màn hình khác của công ty.
- R5.2 KHI chủ sở hữu chấp nhận, nền tảng PHẢI ghi người, thời điểm và phiên bản vào audit.

## Hành vi giữ nguyên

- G1 KHI một danh tính mới đăng nhập mà không có lời mời, nền tảng PHẢI TIẾP TỤC tạo dòng người dùng không membership (test: `test_a_new_identity_gets_no_membership_by_default`).

## Trong phạm vi

- Port `IdentityProviderPort` do `dw_platform` khai, adapter Keycloak, lane gửi lại, route gửi lại thư mời, bảng chấp nhận điều khoản, trạng thái chưa được mời trên web, cấu hình `dw-realm.json`, thêm khóa vào `scripts/keycloak_realm_settings.py`.

## Ngoài phạm vi

| Việc                     | Vì sao                           | Chủ                         |
| ------------------------ | -------------------------------- | --------------------------- |
| SSO theo công ty, SCIM   | Khách đầu không cần              | `studio/org-and-principals` |
| Hai yếu tố bắt buộc      | YC11 của Studio, W2              | `studio/org-and-principals` |
| Nội dung điều khoản, DPA | Luật sư viết                     | `go-live/operator-tasks`    |
| Tự đăng ký công ty mới   | Quyết định của `requirements.md` | đợt sau                     |

## API

- `POST /api/v1/admin/members/{user_id}/resend-invitation`: scope `platform.members.write`; 404 khi không phải người của công ty người gọi; 409 `member_not_invited` khi người đó không còn `invited`.
- `POST /api/v1/me/terms-acceptance`: thân `{"version": "<phiên bản>"}`; 409 `terms_version_outdated` khi không phải bản hiện hành.

## Kiểm soát

| #    | Kiểm soát                                           | Yêu cầu | Test âm                                                                                                 |
| ---- | --------------------------------------------------- | ------- | ------------------------------------------------------------------------------------------------------- |
| CA1  | Không tạo tài khoản thứ hai cho một email           | R1.3    | Mời email đã có tài khoản; adapter giả ghi 0 lần tạo; gỡ kiểm thì ghi 1, đỏ                             |
| CA2  | Lời mời không mất khi nhà cung cấp danh tính hỏng   | R1.4    | Adapter giả ném lỗi; lời mời trả thành công, lane gửi lại đúng một lần; gỡ kiểm thì mất, đỏ             |
| CA3  | Gửi lại chéo công ty trả như chưa tồn tại           | R1.6    | Quản trị công ty B gọi với người của A; 404 và 0 lần gửi; gỡ kiểm thì 202, đỏ                           |
| CA4  | Quên mật khẩu không lộ email có tồn tại không       | R2.2    | Live trên Keycloak: hai email cho cùng câu trả lời; bật lại khác biệt thì đỏ                            |
| CA5  | Thiếu máy chủ thư thì không khởi động               | R3.2    | `validate_for_profile` với production không có cấu hình; `RuntimeError`; gỡ kiểm thì chạy, đỏ           |
| CA6  | Tự đăng ký tắt                                      | R3.3    | Đọc realm đang chạy; `registrationAllowed` false; đổi tệp thành true thì test live đỏ                   |
| CA7  | Người chưa mời không thấy gì                        | R4.1    | Token người mới gọi route công ty; 0 dòng; gỡ kiểm thì thấy, đỏ                                         |
| CA8  | Khóa quản trị chỉ ở api, chỉ quyền `manage-users`   | R4.2    | Soi biến môi trường của worker, web; có khóa thì đỏ; khóa thử gọi quản trị client trả 403, đổi quyền đỏ |
| CA9  | Tài khoản bị tắt khi offboarding hết công ty        | R4.3    | Offboard người chỉ thuộc một công ty; adapter giả ghi tắt; còn công ty khác thì không; gỡ kiểm thì đỏ   |
| CA10 | Chưa chấp nhận điều khoản thì không vào màn công ty | R5.1    | Chủ chưa chấp nhận gọi route công ty; 403 `terms_not_accepted`; gỡ kiểm thì 200, đỏ                     |

## Tiêu chí thành công

- Góp vào KQ2 của `requirements.md`.

## Tiêu chí xong

- Mọi tiêu chí R và G có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát.
- `make ci` xanh và test live trên Keycloak của stack xanh.

## Phụ thuộc

- ADR-0103 (Accepted): danh tính và liên kết.
- tenant-rbac/16 và /17 ở `studio`: membership không vai và lời mời.
- `operator-tasks/05`: máy chủ thư của nền tảng.
- Kiểm lại khi: đổi nhà cung cấp danh tính → R1, R2.

## Câu hỏi còn mở

## Quyết định

- 6/11/2026 (agent, tạm): Dùng thư hành động của Keycloak thay vì thư tự viết, để liên kết đặt mật khẩu do nhà cung cấp danh tính ký và hết hạn. Nếu sai thì: một lane gửi thư riêng.
- 6/11/2026 (agent, tạm): Khóa quản trị là tài khoản dịch vụ của một client riêng với đúng quyền `manage-users` của realm `dw`; đây là biên tin cậy mới, ghi ở ADR-0200 (Proposed) trước khi dựng. Nếu sai thì: người vận hành tạo tài khoản bằng script.
- 6/11/2026 (agent, tạm): Lần chấp nhận điều khoản chỉ đòi chủ sở hữu, không đòi mọi thành viên. Nếu sai thì: mở rộng R5.1 cho mọi thành viên.
- 6/11/2026 (agent, tạm): Mã lỗi quên mật khẩu theo mặc định của Keycloak, chỉ cấu hình để không phân biệt email. Nếu sai thì: một màn riêng ở web.

## Danh sách ticket
