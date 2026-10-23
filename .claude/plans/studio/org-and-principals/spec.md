# Cơ cấu tổ chức và chủ thể: đơn vị, thành viên tenant, tài khoản dịch vụ

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Công ty cần một mô hình chủ thể đủ cho D1: vị thế của một người trong công ty là một dòng có trạng thái, không suy ra từ
membership, và lượt chạy không người kích hoạt (biểu mẫu, webhook, lịch, sự kiện bản ghi) chạy dưới danh nghĩa một tài
khoản dịch vụ của công ty, không bao giờ dưới danh nghĩa người phát hành. Chỉ người và tài khoản dịch vụ hành động; agent
và quy trình là giới hạn, không phải chủ thể (ADR-0103 (Proposed)); workspace là đơn vị sở hữu dữ liệu lồng nhau
(ADR-0102 (Proposed)). W1 dựng nền: khóa `(tenant_id, id)` cho workspace, realm Keycloak siết, thành viên công ty có trạng
thái và tài khoản dịch vụ; cây workspace, nhóm, quản lý trực tiếp, SSO theo tenant và khóa API ở W2.

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- `platform.workspaces` phẳng, không cột cha (`db/migrations/sql/0001_platform_baseline.sql:478-485`), chỉ có khóa duy nhất theo slug (`db/migrations/sql/0001_platform_baseline.sql:612`). Thiếu: không có `UNIQUE (tenant_id, id)` làm đích cho FK kép của Studio.
- Enum miền `TenantStatus` có `active`, `suspended` (`packages/python/dw_platform/src/dw_platform/domain/entities.py:25-27`) trong khi `ck_tenants_status` cho `active`, `locked`, `offboarding`, `offboarded` (`db/migrations/versions/5d9d89ffc716_tenant_offboarding_requests.py:79-80`). Thiếu: khai báo suông, không ai đọc (failure-modes #1).
- Access token, phiên SSO rảnh và phiên SSO tối đa đều 28.800 giây, không có chống dò mật khẩu (`infra/keycloak/dw-realm.json:12-14`). Thiếu: thu hồi chờ tới 8 giờ.
- Web làm mới token im lặng với `checkLoginIframe: false` (`apps/web/lib/auth/auth-context.tsx:199-211`). Ràng buộc: token 300 giây không được đẩy người dùng về trang đăng nhập.
- Danh sách thành viên toàn tenant suy ra từ membership (`packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_members.py:1-8`); `invited` suy ra từ việc chưa đăng nhập lần nào (`packages/python/dw_platform/src/dw_platform/adapters/persistence/directory.py:27-28`). Thiếu: "tạm khóa trong công ty" không có chỗ lưu.
- Lời mời tạo người dùng với `subject` dạng `invite:` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_members.py:164`). Ràng buộc: người được mời có dòng người dùng trước khi đăng nhập.
- Khóa tenant chỉ thực thi khi dựng AccessContext, nơi membership join đọc `tenants.status` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:105-106`). Ràng buộc: trạng thái thành viên công ty được đọc cùng chỗ đó.
- Năm đường ghi membership: `membership_admin` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_admin.py:109`), bộ nối danh tính (`packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:211`), provisioning (`packages/python/dw_platform/src/dw_platform/adapters/persistence/provisioning_repo.py:287`), seed (`packages/python/dw_platform/src/dw_platform/testing/seed_env.py:227`), script (`scripts/grant_platform_admin.py:74`). Ràng buộc: mọi đường phải có dòng thành viên công ty trước membership.
- Không có tài khoản dịch vụ; lượt chạy cần một người, `requested_by` NOT NULL (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/runtime_tables.py:38`). Thiếu: lượt chạy theo lịch hay webhook không có chủ thể để đứng tên.
- `platform.users` ở mặt danh tính, không RLS, không cột loại (`db/migrations/sql/0001_platform_baseline.sql:438-444`); tra cứu khớp `users.subject` bất kể issuer (`packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:200-202`). Ràng buộc: dòng loại `service` phải bị lọc ở mọi đường danh tính.
- `/directory/candidates` liệt kê mọi danh tính chưa có membership cho người giữ `platform.members.write` (`apps/api/src/dw_api/routes/v1/directory.py:65-78`). Ràng buộc: tài khoản dịch vụ không được lộ qua đây.
- Lane audit bằng `system_actor(<lane>)` (`packages/python/dw_platform/src/dw_platform/domain/audit.py:46-57`). Ràng buộc: lane không phải tài khoản dịch vụ và không giữ quyền trên bản ghi (ADR-0103 (Proposed)).
- Tenant mới có một workspace `main` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/provisioning_repo.py:163-164`). Ràng buộc: thành workspace gốc khi cây đến ở W2.

## Mục tiêu

### R1 — Khóa tổng hợp cho workspace

Mọi bảng Studio tham chiếu workspace bằng FK kép trong cùng tenant.

- R1.1 NẾU một FK tổng hợp `(tenant_id, workspace_id)` trỏ tới workspace của tenant khác, THÌ PostgreSQL PHẢI từ chối và không ghi dòng nào.

### R2 — Trạng thái tenant khai báo suông [Bỏ]

Lý do: `TenantStatus` và hai lớp `Tenant`, `Workspace` của miền không ai đọc và lệch `ck_tenants_status` (failure-modes #1).

Chuyển đổi: không dữ liệu nào đổi; không có người gọi; test của chúng bỏ cùng; `Plan` giữ nguyên.

- R2.1 Gói `dw_platform` PHẢI không còn kiểu nào khai báo trạng thái tenant ngoài `active`, `locked`, `offboarding`, `offboarded`.

### R3 — Realm Keycloak siết [Sửa]

Trước đây: access token và phiên SSO sống 28.800 giây (`infra/keycloak/dw-realm.json:12-14`).

- R3.1 Realm `dw` PHẢI cấp access token sống 300 giây, phiên SSO hết khi rảnh 1.800 giây và hết hẳn sau 36.000 giây.
- R3.2 NẾU một refresh token được dùng lần thứ hai, THÌ Keycloak PHẢI từ chối với 400 và không cấp token mới.
- R3.3 NẾU một tài khoản nhập sai mật khẩu lần thứ 10 liên tiếp, THÌ Keycloak PHẢI từ chối đăng nhập của tài khoản đó trong ít nhất 60 giây.
- R3.4 KHI access token của web còn 30 giây, web PHẢI làm mới token mà không đưa người dùng về trang đăng nhập, kể cả khi hai tab cùng mở.

### R4 — Thành viên công ty là một dòng có trạng thái

Quản trị viên công ty thấy và đổi vị thế của một người trong công ty, không phụ thuộc workspace nào (YC7).

- R4.1 Mỗi membership PHẢI thuộc đúng một thành viên công ty của cùng tenant, với trạng thái `invited`, `active` hay `suspended`.
- R4.2 KHI một thành viên công ty bị xóa, PostgreSQL PHẢI xóa mọi membership của người đó trong tenant trong cùng câu lệnh.
- R4.3 NẾU thành viên công ty không ở trạng thái `active`, THÌ API PHẢI trả 403 cho mọi route có kiểm quyền của người đó ở mọi workspace của tenant, và không đổi gì.
- R4.4 KHI quản trị viên công ty mời một người, API quản trị PHẢI ghi thành viên công ty trạng thái `invited` trong cùng giao dịch mời.
- R4.5 KHI người được mời đăng nhập lần đầu, bộ nối danh tính PHẢI đổi trạng thái của người đó sang `active` trong cùng giao dịch nối danh tính.
- R4.6 TRONG KHI thành viên công ty không ở trạng thái `active`, runner PHẢI từ chối nhận mới và tiếp tục lượt chạy dưới danh nghĩa người đó.
- R4.7 NẾU một kết nối đặt `app.tenant_id` của tenant A, hay không đặt tenant, đọc thành viên công ty của tenant B, THÌ PostgreSQL PHẢI trả 0 dòng.
- R4.8 KHI `GET /api/v1/auth/bootstrap` liệt kê workspace của một người, API xác thực PHẢI bỏ mọi workspace của tenant nơi người đó không ở trạng thái `active`.

### R5 — Trạng thái thành viên đọc từ một chỗ [Sửa]

Trước đây: `invited` hay `active` suy ra từ việc đã có danh tính đăng nhập (`packages/python/dw_platform/src/dw_platform/adapters/persistence/directory.py:27-28`).

- R5.1 KHI người giữ `platform.members.read` gọi `GET /api/v1/admin/members` hay người giữ `directory.read` gọi `GET /api/v1/directory/members`, API PHẢI trả `status` của mỗi người bằng đúng trạng thái thành viên công ty của người đó.

### R6 — Tài khoản dịch vụ làm chủ thể chạy

Lượt chạy không người kích hoạt có một chủ thể của công ty để đứng tên (YC8).

- R6.1 KHI người giữ `platform.service_principals.manage` gọi `POST /api/v1/admin/service-principals`, API quản trị PHẢI ghi trong một giao dịch một người dùng loại `service` thuộc tenant, thành viên công ty `active`, một membership ở workspace sở hữu và audit `platform.service_principal.created` [CAN LAM RO: Q2].
- R6.2 NẾU một token (Keycloak hay token dev) mang subject của một tài khoản dịch vụ, THÌ API PHẢI trả 403 và không dựng AccessContext.
- R6.3 NẾU một đường ghi thêm danh tính đăng nhập cho người dùng loại `service`, THÌ PostgreSQL PHẢI từ chối và không ghi gì.
- R6.4 NẾU một gán vai trò đưa `tenant_owner` hay vai trò có quyền trọng yếu cho tài khoản dịch vụ, hay một quyền trọng yếu được thêm vào vai trò đang gán cho tài khoản dịch vụ, THÌ PostgreSQL PHẢI từ chối với SQLSTATE 23514 và không đổi gì.
- R6.5 NẾU người đề xuất gắn một tài khoản dịch vụ làm chủ thể chạy không giữ mọi quyền của tài khoản đó ở mức bằng hoặc rộng hơn, hay thiếu `platform.service_principals.use` trên workspace sở hữu của nó, THÌ bộ kiểm gắn tài khoản dịch vụ PHẢI trả 403 `rbac_escalation` kèm danh sách quyền thiếu và không gắn gì [CAN LAM RO: Q1].
- R6.6 KHI quyền hiệu lực của một tài khoản dịch vụ tăng, PostgreSQL PHẢI ghi sự kiện outbox `platform.service_principal.grants_changed` trong cùng giao dịch.
- R6.7 ĐỐI VỚI lượt chạy không người kích hoạt (lịch, webhook, sự kiện bản ghi, Data Hub), runner PHẢI chạy dưới danh nghĩa tài khoản dịch vụ được gắn và duyệt bởi một người khác người gắn, không bao giờ dưới danh nghĩa người phát hành.

### R7 — Tài khoản dịch vụ không lộ ở mặt danh tính

Quản trị viên công ty và người vận hành không thấy tài khoản dịch vụ trong danh sách danh tính đăng nhập.

- R7.1 NẾU người giữ `platform.members.write` ở một tenant gọi `GET /api/v1/directory/candidates`, THÌ API danh bạ PHẢI không trả tài khoản dịch vụ nào, của tenant đó hay tenant khác.
- R7.2 KHI người vận hành gọi `GET /api/v1/platform/users`, API nền tảng PHẢI chỉ trả người dùng loại `human`.

## Hành vi giữ nguyên

- G1 KHI người được mời đăng nhập lần đầu, bộ nối danh tính PHẢI TIẾP TỤC nối vào người dùng đã mời để người đó thấy workspace của mình (test: `test_an_invited_person_signs_in_and_finds_their_workspace`).
- G2 KHI quản trị viên công ty gọi `DELETE /api/v1/admin/members/{user_id}` cho một workspace, API quản trị PHẢI TIẾP TỤC chỉ gỡ membership ở workspace đó (test: `test_revoke_removes_a_membership`).

## Trong phạm vi

- `uq_workspaces_tenant_id UNIQUE (tenant_id, id)` trên `platform.workspaces`; realm `dw` trong `infra/keycloak/dw-realm.json` và test cấu hình của nó.
- Bảng `platform.tenant_members` và FK từ `platform.memberships`; cột `platform.users.kind`, `owner_tenant_id`; bảng `platform.service_principals`.
- Route `/api/v1/admin/service-principals`; khóa `platform.service_principals.manage`, `.use` đăng ký trong danh mục quyền theo quy ước của tenant-rbac; bộ kiểm gắn tài khoản dịch vụ.
- Từ vựng chủ thể của ADR-0103 (Proposed) mục 1: `user`, `service_principal`, `system_lane`, `support_staff`; agent và quy trình là giới hạn, không có dòng người dùng, vai trò hay quyền.

## Ngoài phạm vi

| Việc                                                                                      | Vì sao                                                                                                                        | Chủ                                               |
| ----------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| R4.6: runner từ chối lượt chạy của người không `active`                                   | Cửa nhận và tiếp tục lượt chạy đọc `RunControlPort` (ADR-0120 (Proposed)), không thuộc spec này                               | agent-lifecycle, workflow-engine                  |
| R6.7: lượt chạy không người chạy dưới tài khoản dịch vụ được gắn                          | Binding `principal` trong bộ giá trị gắn hai người duyệt (ADR-0110 (Proposed)) và `run_as_principal_id` (ADR-0113 (Proposed)) | workflow-triggers, workflow-engine, tenant-config |
| Cây workspace: cha, gốc, độ sâu sáu, chống vòng, hàm đọc cây                              | ADR-0102 (Proposed) mục 1; D12 đặt độ sâu 6                                                                                   | org-and-principals, W2                            |
| Lưu trữ workspace có hiệu lực ở mọi cửa                                                   | Cần cây workspace và `RunControlPort`                                                                                         | org-and-principals, W2                            |
| Quan hệ quản lý cấp tenant                                                                | Tách khỏi ticket 02; `memberships.manager_user_id` giữ tới khi đó                                                             | org-and-principals, W2                            |
| Nhóm và thành viên nhóm                                                                   | Đi cùng mức `team` của tenant-rbac                                                                                            | org-and-principals, W2                            |
| Người chịu trách nhiệm bắt buộc và phản ứng khi người rời đi                              | Tài khoản dịch vụ W1 chưa có `owner_user_id`; guard và lane `principal_ownership` đến cùng                                    | org-and-principals, W2                            |
| Di chuyển workspace; tạm khóa, gỡ thành viên và SLO thu hồi                               | W1 có trạng thái và hiệu lực của nó (R4.3); route tạm khóa, mở lại và đo p99 60 giây ở W2                                     | org-and-principals, W2                            |
| Thuộc tính nhân sự, nhập danh bạ CSV, người được dùng `dw.audience/v1`                    | Định dạng chờ DO-40 (Q3)                                                                                                      | org-and-principals, W2                            |
| Keycloak Organizations, mã nhận lời mời, SSO theo tenant, MFA và step-up                  | Mô hình liên kết chờ DO-17 (Q2)                                                                                               | org-and-principals, W2                            |
| Khóa API cho tích hợp                                                                     | Cần tài khoản dịch vụ và kho khóa của connections-and-vault                                                                   | org-and-principals, W2                            |
| SCIM 2.0, client credentials `private_key_jwt`, tự cấu hình SSO, phân công theo thời hiệu | v2                                                                                                                            | org-and-principals, W3                            |
| Luật nối danh tính tạm thời qua email đã xác minh                                         | Đóng lỗ chiếm danh tính ở P0                                                                                                  | foundations-hardening                             |
| Vai trò, mức truy cập, quyền hiệu lực, chống leo thang quyền                              | Một chủ quyền hiệu lực (ADR-0104 (Proposed))                                                                                  | tenant-rbac                                       |
| `principal_kind` trên `RunContext`, audit và sổ usage                                     | Chủ các cột đó (ADR-0121 (Proposed))                                                                                          | telemetry-and-audit, usage-and-limits             |

## Kiểm soát

| #    | Kiểm soát                                      | Yêu cầu    | Test âm                                                                                                                                      |
| ---- | ---------------------------------------------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| OP1  | FK tổng hợp trong tenant                       | R1.1       | FK `(tenant_B, ws_A)` từ bảng thử → lỗi FK; test khẳng định `uq_workspaces_tenant_id` có trong `pg_constraint`; bỏ ràng buộc → đỏ            |
| OP2  | Refresh token dùng một lần                     | R3.2       | Probe trong compose: dùng lại refresh token → 400; đặt `refreshTokenMaxReuse` lớn hơn 0 → test cấu hình đỏ                                   |
| OP3  | Chống dò mật khẩu                              | R3.3       | Probe: lần sai thứ 10 → bị khóa; `bruteForceProtected` false → test cấu hình đỏ                                                              |
| OP4  | Mọi membership có thành viên công ty           | R4.1, R4.2 | INSERT membership không có dòng thành viên công ty → lỗi FK; DELETE thành viên công ty → 0 membership còn lại                                |
| OP5  | Không `active` thì không có quyền              | R4.3       | Đặt `suspended` bằng SQL → request kế tiếp 403 ở cả hai workspace; gỡ điều kiện `status = 'active'` → đỏ                                     |
| OP6  | Thành viên công ty thuộc một tenant            | R4.7       | Kết nối tenant A đọc thành viên tenant B → 0 dòng; không đặt tenant → 0 dòng; self-select chỉ trả dòng của chính mình                        |
| OP7  | Bootstrap bỏ công ty nơi người đó không active | R4.8       | Thành viên `suspended` ở A, `active` ở B → bootstrap chỉ có workspace của B; gỡ điều kiện → đỏ                                               |
| OP8  | Tài khoản dịch vụ không đăng nhập              | R6.2, R6.3 | Token dev mang subject của tài khoản dịch vụ → 403; INSERT `platform.external_identities` cho nó → trigger từ chối; gỡ nhánh `kind` → đỏ     |
| OP9  | Tài khoản dịch vụ không giữ quyền trọng yếu    | R6.4       | Dưới `dw_migrator` gán `tenant_owner` cho nó → 23514; thêm khóa `critical` vào vai trò đang gán cho nó → 23514; gỡ trigger → đỏ              |
| OP10 | Không leo thang quyền qua tài khoản dịch vụ    | R6.5       | Người thiếu một quyền của tài khoản → 403 `rbac_escalation`; thay `platform.grants_cover` bằng `true` → đỏ                                   |
| OP11 | Không lộ sang tenant khác                      | R7.1, R7.2 | Admin tenant B gọi `/directory/candidates` → không có tài khoản dịch vụ của A; `/platform/users` không có dòng `service`; gỡ lọc `kind` → đỏ |

## Tiêu chí xong

- Mọi tiêu chí R và G có test; mọi kiểm soát OP1-OP11 có test âm đã thấy đỏ khi gỡ kiểm soát, ghi ở Comments của ticket.
- `make ci` xanh; `test_rls_coverage.py`, `test_privileges.py`, `test_offboarding.py` có dòng cho `platform.tenant_members` và `platform.service_principals`.
- Số đo làm mới token im lặng với token 300 giây (hai tab, `checkLoginIframe: false`) ghi ở Comments của ticket 01 trước khi đổi realm; số đo dựng AccessContext với 5.000 thành viên công ty (D12) ghi ở Comments của ticket 02.

## Phụ thuộc

- tenant-rbac: `platform.effective_grants`, `platform.grants_cover` và gán vai trò (`.claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md`); ticket 03 ở đây chờ nó. Chiều ngược: tenant-rbac/02 chờ ticket 02 ở đây và gắn trigger phiên bản quyền lên `platform.tenant_members`.
- foundations-hardening: `platform.guard_privileged_login_identity()` và luật nối danh tính (`.claude/plans/studio/foundations-hardening/issues/02-hang-rao-du-lieu-va-danh-tinh.md`), quyền `dw_app` trên `platform.users` (`.claude/plans/studio/foundations-hardening/issues/03-quyen-dw-app-va-rls-initplan.md`); ticket 03 chờ cả hai.
- Bên gắn chủ thể chạy (workflow-triggers, tenant-config) khai Protocol của mình; composition root `apps/api/src/dw_api/bootstrap/wiring.py` đáp ứng bằng bộ kiểm gắn tài khoản dịch vụ (CLAUDE.md, "Non-negotiable architecture").
- Kiểm lại khi: DO-12 hay DO-17 được trả lời khác khuyến nghị → ticket 03; tenant-rbac đổi chữ ký `platform.grants_cover` → ticket 03; foundations-hardening đổi guard danh tính → ticket 03.

## Câu hỏi còn mở

- Q1. DO-12: lượt chạy không người kích hoạt (biểu mẫu, webhook, lịch, sự kiện vào) chạy dưới danh nghĩa ai: tài khoản dịch vụ gắn theo từng phiên bản qua binding đã duyệt (khuyến nghị), người phát hành, hay một chủ thể hệ thống toàn tenant? Chủ: Đạt và người yêu cầu. Chặn: R6.5, R6.7, ticket 03.
- Q2. DO-17: Keycloak Organizations trong một realm thay vì realm hay issuer riêng mỗi tenant, tài khoản dịch vụ là dòng `platform.users` loại `service` ở v1, và áp luật nối danh tính tạm thời ngay (sau khi hỏi dw-proterial có đường nhập nào dựa vào email chưa xác minh)? Chủ: Đạt. Chặn: R6.1, ticket 03.
- Q3. DO-40: người được dùng là danh sách điều kiện có kiểu hay CEL? Chủ: Đạt và người yêu cầu. Không đổi: W1 không có người được dùng.

## Quyết định

- 22/10/2026 (người yêu cầu): D1: workspace là đơn vị sở hữu dữ liệu và lồng nhau; với tới nhau qua quyền, không chép dữ liệu (ADR-0102 (Proposed)). Sửa: R1; cây ở W2.
- 23/10/2026 (người yêu cầu): D12 (DO-14): 5.000 người dùng, 200 workspace, cây sâu 6 mỗi tenant. Sửa: R4, Tiêu chí xong.
- 23/10/2026 (người yêu cầu): D11: hai người luôn luôn; binding `principal` do người giữ mọi quyền của tài khoản dịch vụ đề xuất và người khác duyệt (YC8, ADR-0110 (Proposed)); gán vai trò cho tài khoản dịch vụ đi qua hai người của tenant-rbac. Sửa: R6.5, R6.7.
- 23/10/2026 (agent, tạm): DO-04 theo khuyến nghị (a): giữ "workspace" làm thuật ngữ giao diện. Nếu sai thì: màn hình đổi sang thuật ngữ được chọn, code giữ `workspace`.
- 23/10/2026 (agent, tạm): DO-39 theo khuyến nghị (a): lời mời bằng liên kết do quản trị viên chép; MFA cho người vận hành, nhân viên hỗ trợ và người giữ quyền trọng yếu; tenant bị khóa trả 503 cho sự kiện vào và không lưu; người chịu trách nhiệm rời đi thì chặn phát hành, phiên bản đang dùng vẫn chạy. Cả bốn ở W2. Nếu sai thì: dòng W2 tương ứng đổi, W1 không đổi.
- 23/10/2026 (agent, tạm): Trigger tăng phiên bản quyền trên `platform.tenant_members` do tenant-rbac/02 gắn, vì `platform.bump_access_version()` ra đời ở đó và ticket ấy chờ ticket 02 này; ticket 02 làm trạng thái có hiệu lực ở chỗ dựng AccessContext. Nếu sai thì: hàm phiên bản chuyển sang ticket 02 này.
- 23/10/2026 (agent, tạm): Route tạm khóa và mở lại thành viên công ty ở W2 theo gói; W1 có trạng thái `suspended`, người đọc của nó (R4.3, R4.8) và người ghi `invited`, `active`. Nếu sai thì: ticket 02 thêm `POST /api/v1/admin/members/{user_id}/suspend` và `/reactivate`.
- 23/10/2026 (agent, tạm): Chặn tài khoản dịch vụ giữ quyền trọng yếu là trigger riêng ở ticket 03 này, không nằm trong `platform.rbac_refusals` của tenant-rbac/03, vì ticket 03 này không chờ tenant-rbac/03. Nếu sai thì: chuyển vào `platform.rbac_refusals` và thêm tenant-rbac/03 vào `Blocked by:`.

## Danh sách ticket

| #   | Ticket                                                                                                             |
| --- | ------------------------------------------------------------------------------------------------------------------ |
| 01  | [Khóa tổng hợp cho workspace, gỡ enum khai báo suông, siết realm Keycloak](issues/01-khoa-don-vi-va-siet-realm.md) |
| 02  | [Thành viên cấp tenant và trạng thái](issues/02-thanh-vien-cap-tenant.md)                                          |
| 03  | [Tài khoản dịch vụ làm chủ thể chạy](issues/03-tai-khoan-dich-vu-run-as.md)                                        |
