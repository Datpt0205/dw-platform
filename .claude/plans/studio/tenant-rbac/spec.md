# Phân quyền theo vai do tenant cấu hình

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Quản trị viên công ty cần tự dựng vai trò cho các workspace của mình (vai Marketing và vai Sales của lát Marketing, D4) với
quyền trên đối tượng do công ty định nghĩa (`obj.lead.read`, D3), điều mà danh mục vai toàn cục chỉ migration ghi không
làm được. Spec này đưa vai trò thành dữ liệu của tenant trên danh mục quyền do code sở hữu, mỗi quyền mang một mức truy
cập neo ở workspace được gán vai trò, một hàm PostgreSQL là chủ duy nhất của quyền hiệu lực, chống leo thang quyền ở
service và trigger, và hai người cho mọi thay đổi vai trò (D11), theo ADR-0104 (Accepted). Spec này sửa đổi
ADR-0012 (Accepted) và tiền đề của migration `648e2f7c3edb` ("the catalogue changes only in migrations") cho vai trò của
tenant; danh mục quyền và vai trò mẫu vẫn chỉ migration ghi.

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- Vai và bộ quyền là bảng toàn cục, không `tenant_id`, không RLS (`db/migrations/sql/0001_platform_baseline.sql:359-363`); seed bảy vai gồm `org_admin` và `platform_admin` (`db/migrations/sql/0001_platform_reference.sql:50-87`). Ràng buộc: chúng thành vai trò mẫu, vẫn chỉ migration ghi.
- Tiền đề "the catalogue changes only in migrations" (`db/migrations/versions/648e2f7c3edb_roles_and_permission_sets_read_only_to_.py:7-13`), giữ bằng test (`packages/python/dw_platform/tests/integration/test_privileges.py:131-149`). Ràng buộc: spec này sửa tiền đề cho vai trò của tenant và viết lại test trong cùng thay đổi.
- ADR-0012 (Accepted) dựa vào cùng tiền đề, "both tables change only in migrations" (`docs/adr/0012-a-sod-waiver-takes-two-people.md:38-46`); tách nhiệm xét trên một membership (`db/migrations/versions/b9862fa13a80_platform_separation_of_duty_rules_guard_.py:12-14`). Ràng buộc: được sửa đổi; hôm nay một người giữ hai vế một luật ở hai workspace vẫn qua kiểm.
- Membership mang `role_keys`, `permission_set_keys` jsonb không FK, một dòng mỗi workspace (`db/migrations/sql/0001_platform_baseline.sql:262-273`). Thiếu: khóa lạ không cấp gì mà không báo; không có gán vai trò nào vượt một workspace.
- `effective_scopes` hợp vai và bộ quyền và tự nhận là chủ (`packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:33-55`); người giữ quyền đọc nó (`packages/python/dw_platform/src/dw_platform/adapters/persistence/scope_holders.py:67-70`). Ràng buộc: thành adapter mỏng của hàm SQL.
- Bootstrap tự tính quyền chỉ từ vai, bỏ bộ quyền (`packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:252-269`), trả `roles`, `scopes` (`apps/api/src/dw_api/routes/v1/auth.py:21-30`) và web chặn theo đó (`apps/web/lib/auth/auth-context.tsx:83-93`). Thiếu: người có quyền chỉ qua bộ quyền bổ sung bị web báo thiếu.
- AccessContext chỉ đọc membership của workspace đang làm việc (`packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:80-106`). Thiếu: quyền không cộng dồn qua workspace như D1 cần.
- Chống leo thang quyền là luật tiền tố `platform.` (`packages/python/dw_platform/src/dw_platform/application/membership_admin.py:49-65`), chép lại ở `admin_console` (`packages/python/dw_platform/src/dw_platform/application/admin_console.py:295-304`). Thiếu: không xét mức truy cập, không chặn tự gán.
- `platform_admin` qua mọi kiểm quyền (`packages/python/dw_platform/src/dw_platform/application/authorization.py:68-71`), có bản sao ở web (`apps/web/lib/session.ts:177-181`). Ràng buộc: W1 giữ đường vượt này, W2 rút khỏi dữ liệu tenant.
- Cache AccessContext sống 30 giây (`packages/python/dw_platform/src/dw_platform/adapters/persistence/caching_lookup.py:27`), khóa không có phiên bản (`packages/python/dw_platform/src/dw_platform/application/cache.py:18-20`), route xóa cache sau khi ghi (`apps/api/src/dw_api/routes/v1/admin_members.py:80-84`). Thiếu: lane, nhập dữ liệu hay SQL để quyền cũ sống tới 30 giây.
- Không có danh mục khóa quyền: `runs.cancel` được kiểm (`apps/api/src/dw_api/routes/v1/runs.py:127`) mà không vai nào cấp. Thiếu: không gì bắt khóa không ai cấp hay không ai kiểm.
- `tenant_session` đặt `app.user_id` mỗi giao dịch từ AccessContext (`packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_session.py:23-27`). Ràng buộc: trigger biết người làm.
- Truy cập của người vận hành cấm theo tiền tố khóa (`packages/python/dw_platform/src/dw_platform/application/support_access.py:63-72`). Ràng buộc: thêm `studio.`, `obj.`, `fld.`.
- `dw_app` mặc định được ghi mọi bảng mới của schema `platform` (`db/migrations/sql/0001_platform_grants.sql:45-46`). Ràng buộc: quyền DB thu hẹp đi cùng migration (CLAUDE.md, "Data model rules").
- `test_rls_coverage.py` tìm bảng tenant theo cột `tenant_id` và không kiểm cột `workspace_id` (`packages/python/dw_platform/tests/integration/test_rls_coverage.py:44-59`). Ràng buộc: `platform.tenant_roles`, `platform.tenant_role_permissions`, `platform.tenant_access_versions`, `platform.role_change_requests`, `platform.tenant_role_object_privileges` và `studio.field_permissions` không có `workspace_id`; chúng vào lớp bảng toàn tenant mà CLAUDE.md mục Tenancy ghi (DO-01, ADR-0100 (Accepted)), mỗi bảng một dòng lý do trong danh sách của test đó; `platform.role_assignments` giữ `workspace_id` neo.

## Mục tiêu

### R1 — Danh mục quyền có một chủ

Mỗi khóa quyền nền tảng có đúng một dòng do migration ghi, với nhãn, loại và mức rủi ro.

- R1.1 Mỗi khóa quyền mà một route, một vai trò mẫu, một đặc tả trong `configs/tools` hay điều hướng của web kiểm hoặc cấp PHẢI có đúng một dòng trong danh mục quyền, với nhãn tiếng Việt, loại quyền (`tenant`, `workspace`, `record`) và mức rủi ro (`standard`, `elevated`, `critical`).
- R1.2 Mỗi khóa `active` của danh mục quyền PHẢI có ít nhất một chỗ kiểm trong code, trừ khóa thuộc danh sách ngoại lệ ghi kèm lý do.
- R1.3 NẾU `dw_app`, `dw_provisioner` hay `dw_agent_ro` ghi vào danh mục quyền hay bảng vai trò mẫu, THÌ PostgreSQL PHẢI từ chối với `permission denied` và không đổi dòng nào.
- R1.4 KHI người giữ `platform.roles.read` gọi `GET /api/v1/admin/permissions`, API quản trị PHẢI trả mỗi khóa của danh mục với `key`, `area`, `label_vi`, `scope_kind`, `risk` và `status`.
- R1.5 NẾU một khóa bắt đầu bằng `studio.`, `obj.` hay `fld.` được đăng ký cho truy cập của người vận hành (ADR-0024 (Proposed)), THÌ danh mục quyền của người vận hành PHẢI từ chối khóa đó và không đổi gì.

### R2 — Một chủ cho quyền hiệu lực [Sửa]

Trước đây: bootstrap tự tính quyền chỉ từ vai (`packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:252-269`); AccessContext đọc một membership (`packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:80-106`).

Mọi đường đọc trả cùng một câu trả lời cho "người này giữ gì": hợp mọi gán vai trò của người đó trong tenant.

- R2.1 TRONG KHI `GET /api/v1/auth/bootstrap` còn trả `scopes`, API xác thực PHẢI trả cho mỗi membership đúng tập quyền mà `GET /api/v1/me` trả cho cùng người ở cùng workspace, gồm quyền chỉ đến từ bộ quyền bổ sung.
- R2.2 Với cùng một người và cùng workspace đang làm việc, AccessContext, `GET /api/v1/me`, danh sách người giữ quyền dùng để chọn người duyệt và luật tách nhiệm PHẢI dùng cùng một tập quyền hiệu lực (ADR-0104 (Accepted) mục 5).
- R2.3 KHI một người giữ một khóa ở mức `tenant` từ gán vai trò ở workspace A và làm việc ở workspace B, `GET /api/v1/me` ở B PHẢI trả khóa đó.
- R2.4 KHI một người giữ một khóa ở mức `workspace` chỉ từ gán vai trò ở workspace A và làm việc ở workspace B, `GET /api/v1/me` ở B PHẢI không trả khóa đó.
- R2.5 NẾU tenant hay thành viên công ty không ở trạng thái `active`, vai trò đã xóa mềm hay gán vai trò đã quá `expires_at`, THÌ quyền hiệu lực của người đó PHẢI không gồm quyền nào từ nguồn ấy.
- R2.6 KHI web quyết định ẩn hay khóa một điều khiển, web PHẢI đọc quyền từ `GET /api/v1/me` của workspace đang làm việc, không từ `GET /api/v1/auth/bootstrap` hay từ khóa vai trò.

### R3 — Vai trò là dữ liệu của tenant

Công ty có vai trò của riêng mình, nhân bản từ vai trò mẫu, không bao giờ rơi về mẫu khi đọc.

- R3.1 KHI người vận hành tạo tenant qua `POST /api/v1/platform/tenants`, API nền tảng PHẢI cài hai vai trò hệ thống `tenant_owner` và `member` trong cùng giao dịch tạo tenant.
- R3.2 KHI một migration sửa một vai trò mẫu, vai trò của tenant đã nhân bản từ mẫu đó PHẢI giữ nguyên quyền và mức truy cập.
- R3.3 NẾU một kết nối đặt `app.tenant_id` của tenant A, hay không đặt tenant, đọc hoặc ghi vai trò, quyền của vai trò hay gán vai trò của tenant B, THÌ PostgreSQL PHẢI trả 0 dòng hoặc từ chối ghi, và không đổi gì.
- R3.4 NẾU một quyền của vai trò mang mức không khớp loại quyền (W1: khóa `tenant` chỉ nhận `tenant`; khóa `workspace` nhận `workspace`, `tenant`; khóa `record` nhận `own`, `workspace`, `tenant`), THÌ PostgreSQL PHẢI từ chối với SQLSTATE 23514 và không đổi gì.
- R3.5 KHI migration chuyển dữ liệu hiện có xong, `GET /api/v1/me` PHẢI trả cho mọi membership đúng tập khóa nó trả trước migration.
- R3.6 KHI migration chuyển dữ liệu hiện có, migration PHẢI gán `tenant_owner` cho người giữ `org_admin` ở workspace `main` của mỗi tenant, với audit `platform.role_assignment.grant` của `system:rbac_migration`.
- R3.7 NẾU một tenant đã có 200 vai trò chưa xóa (tính cả bộ quyền bổ sung), THÌ PostgreSQL PHẢI từ chối vai trò thứ 201 với `role_limit_reached` và không đổi gì.
- R3.8 KHI người vận hành gọi `POST /api/v1/platform/tenants/{tenant_id}/org-admins`, API nền tảng PHẢI gán vai trò `tenant_owner` cho người đó thay cho khóa `org_admin`.

### R4 — Thay đổi quyền có hiệu lực từ request đầu tiên

Một quyền bị thu hồi thôi tác dụng ở request đầu tiên sau commit, ai ghi cũng vậy (YC14).

- R4.1 KHI một thay đổi ở vai trò, quyền của vai trò, gán vai trò, membership, thành viên công ty, trạng thái tenant hay gói được commit bởi API, lane, nhập dữ liệu hay SQL thô, API PHẢI quyết định request đầu tiên sau commit theo quyền mới, không chờ 30 giây của cache.
- R4.2 NẾU một bản ghi cache AccessContext thiếu một trường hay mang phiên bản quyền khác phiên bản hiện tại của tenant, THÌ bộ đọc AccessContext PHẢI coi là trượt cache và dựng lại từ PostgreSQL.

### R5 — Tách nhiệm trên quyền hiệu lực [Sửa]

Trước đây: luật xét trên một membership với vai toàn cục (`db/migrations/versions/b9862fa13a80_platform_separation_of_duty_rules_guard_.py:12-14`).

- R5.1 NẾU một gán vai trò hay một thay đổi quyền của vai trò làm một người giữ khóa của cả hai vế một luật tách nhiệm chưa có miễn trừ đã xác nhận, kể cả khi hai vế đến từ hai workspace, THÌ PostgreSQL PHẢI từ chối với SQLSTATE 23514, ràng buộc `ck_roles_sod_memberships`, nêu tối đa 20 người giữ, và không đổi gì.
- R5.2 KHI một quyền chỉ đến từ `tenant_owner`, luật tách nhiệm PHẢI không tính quyền đó.
- R5.3 KHI PostgreSQL từ chối một thay đổi vai trò vì tách nhiệm, API quản trị vai trò PHẢI trả 409 nêu luật và tối đa 20 người giữ.

### R6 — Chống leo thang quyền

Không ai trao quyền mình không giữ, không ai tự trao quyền, mỗi tenant luôn còn chủ sở hữu công ty (YC13).

- R6.1 NẾU người làm đưa vào vai trò, gán hay gỡ một quyền mà chính họ không giữ ở mức bằng hoặc rộng hơn trên workspace được gán vai trò của người nhận, THÌ API quản trị vai trò PHẢI trả 403 `rbac_escalation` kèm danh sách quyền thiếu và không đổi gì.
- R6.2 NẾU một thay đổi mà R6.1, R6.4, R6.5 hay R6.6 cấm đi bằng SQL thô dưới `dw_app`, hay thiếu `app.user_id`, THÌ PostgreSQL PHẢI từ chối với SQLSTATE 23514 và không đổi gì.
- R6.3 ĐỐI VỚI người giữ `platform.roles.bind`, API quản trị vai trò CÓ THỂ gán hay gỡ một vai trò không có quyền trọng yếu dù người làm không giữ đủ quyền của vai trò đó.
- R6.4 NẾU người làm gán hay thêm vai trò cho membership của chính mình, kể cả với tư cách người duyệt, THÌ API quản trị vai trò PHẢI trả 403 `rbac_self_assignment` và không đổi gì.
- R6.5 NẾU một thay đổi đưa khóa không cấp được cho tenant (`platform.admin`) vào vai trò của tenant, hay gán `platform_admin`, THÌ API quản trị vai trò PHẢI trả 422 `rbac_not_grantable` và không đổi gì.
- R6.6 NẾU một thay đổi xóa hay đổi khóa một vai trò hệ thống, hay sửa quyền của `tenant_owner`, THÌ API quản trị vai trò PHẢI trả 409 `role_is_system` và không đổi gì.
- R6.7 NẾU một thay đổi (gỡ gán vai trò, xóa membership, xóa thành viên công ty hay người dùng, đổi trạng thái thành viên) làm một tenant `active` không còn chủ sở hữu công ty `active` nào, THÌ PostgreSQL PHẢI từ chối với ràng buộc `ck_role_assignments_last_owner` và không đổi gì.
- R6.8 NẾU người làm gán hay gỡ một vai trò mang `fld.*` trên một trường có `pd_category` là `sensitive` mà chính họ không giữ khóa `fld.*` đó, THÌ API quản trị vai trò PHẢI trả 403 `rbac_escalation` và không đổi gì, kể cả khi họ giữ `platform.roles.bind`.

### R7 — Hai người khi nới quyền, một người khi chỉ siết

Theo D11, một người đề xuất, một người khác giữ cùng quyền xác nhận, rồi thay đổi mới có hiệu lực; thay đổi chỉ siết quyền
cần một người cộng audit ("đóng một người, mở hai người").

- R7.1 KHI quản trị viên công ty gửi một thay đổi vai trò không chỉ siết quyền (tạo, đổi tên, đổi mô tả hay xóa mềm vai trò; thêm quyền hay nâng mức trong vai trò; gán vai trò, kể cả gán `member` khi mời), API quản trị vai trò PHẢI ghi một đề xuất chưa có hiệu lực và chỉ áp thay đổi khi một người khác giữ cùng quyền xác nhận.
- R7.2 NẾU người duyệt là người đề xuất, THÌ API quản trị vai trò PHẢI trả 409 `second_person_required` và không đổi gì.
- R7.3 NẾU một thay đổi cần người thứ hai mà trong tenant không có người thứ hai `active` nào giữ quyền cần để xác nhận, THÌ API quản trị vai trò PHẢI trả 409 `no_checker_available` và không ghi đề xuất.
- R7.4 NẾU lời xác nhận đến sau `expires_at` của đề xuất (đúng 7 ngày sau lúc đề xuất, so bằng `timestamptz`), THÌ API quản trị vai trò PHẢI trả 409 `proposal_expired` và không đổi gì.
- R7.5 NẾU `dw_app` ghi một thay đổi không chỉ siết quyền vào vai trò, quyền của vai trò hay gán vai trò trong giao dịch không mang một đề xuất còn hạn do người khác `app.user_id` đề xuất, THÌ PostgreSQL PHẢI từ chối với SQLSTATE 23514 và không đổi gì.
- R7.6 KHI quản trị viên công ty gửi một thay đổi chỉ siết quyền (gỡ gán vai trò; bỏ quyền hay hạ mức trong vai trò mà không thêm quyền hay nâng mức nào), API quản trị vai trò PHẢI áp thay đổi trong giao dịch của người gửi cùng đúng một sự kiện audit, không ghi đề xuất.

### R8 — API quản trị vai trò, audit và cột cũ [Sửa]

Trước đây: `GET /api/v1/admin/roles` trả vai toàn cục, chỉ để xem (`apps/api/src/dw_api/routes/v1/admin_console.py:242`).

- R8.1 KHI người giữ `platform.roles.read` gọi `GET /api/v1/admin/roles`, API quản trị vai trò PHẢI trả mọi vai trò chưa xóa của tenant với `id`, `key`, `name`, `kind`, `is_system`, `holder_count`, `version` và `assignable_by_me`.
- R8.2 NẾU người gọi không giữ `platform.roles.write` hay `platform.roles.bind` mà một mutation quản trị vai trò cần, THÌ API quản trị vai trò PHẢI trả 403 và không đổi gì, dù giao diện có ẩn điều khiển hay không.
- R8.3 KHI một đề xuất được ghi, xác nhận hay rút, API quản trị vai trò PHẢI ghi đúng một sự kiện audit trong cùng giao dịch, chỉ mang id và mã, không email, không tên.
- R8.4 KHI một mutation quản trị vai trò được gửi lại với cùng `Idempotency-Key` và cùng thân, API quản trị vai trò PHẢI trả cùng kết quả và không ghi audit thứ hai.
- R8.5 NẾU `If-Match` của một mutation trên vai trò đã có khác ETag hiện tại của vai trò đó, THÌ API quản trị vai trò PHẢI trả 412 `precondition_failed` và không ghi đề xuất hay thay đổi nào.
- R8.6 NẾU một đường ghi đặt `memberships.permission_set_keys` khác rỗng, hay đặt `memberships.role_keys` chứa khóa khác `platform_admin`, THÌ PostgreSQL PHẢI từ chối với `ck_memberships_legacy_role_columns` và không đổi gì.
- R8.7 NẾU vai trò đổi `version` giữa lúc đề xuất và lúc xác nhận, THÌ API quản trị vai trò PHẢI trả 409 `stale_version` và không đổi gì.
- R8.8 NẾU một mutation trên vai trò đã có thiếu `If-Match`, THÌ API quản trị vai trò PHẢI trả 428 `precondition_required` và không ghi gì.

### R9 — Quyền trên đối tượng và trường trong vai trò

Vai trò mang quyền `obj.<api_name>.<action>` có mức truy cập và quyền trường `fld.*` cộng dồn qua mọi vai trò (YC12, YC22).

- R9.1 KHI một định nghĩa đối tượng có `api_name` X còn sống, `GET /api/v1/admin/permissions` PHẢI liệt kê `obj.X.read`, `obj.X.create`, `obj.X.update`, `obj.X.delete` và `obj.X.assign`, loại `record`.
- R9.2 NẾU một vai trò nhận quyền đối tượng cho hành động chưa `enforced` (W1: `share`, `export`), THÌ PostgreSQL PHẢI từ chối với ràng buộc `ck_role_object_privileges_action_enforced` và không đổi gì.
- R9.3 KHI một định nghĩa đối tượng hay trường bị xóa, PostgreSQL PHẢI xóa quyền đối tượng và quyền trường của nó khỏi mọi vai trò trong cùng giao dịch.
- R9.4 KHI một người chỉ giữ `obj.X.read` ở mức `own`, tầm với workspace của khóa đó cho người này PHẢI rỗng.
- R9.5 NẾU người làm đưa vào vai trò một quyền đối tượng ở mức rộng hơn mức chính họ giữ, hay một quyền trường họ không giữ, THÌ PostgreSQL PHẢI từ chối với SQLSTATE 23514 và không đổi gì.
- R9.6 KHI một người giữ `fld.X.Y.read` từ một vai trò và `fld.X.Y.edit` từ vai trò khác, `GET /api/v1/me` PHẢI trả cả hai khóa.

## Hành vi giữ nguyên

- G1 KHI người đã đề xuất một miễn trừ tách nhiệm tự xác nhận miễn trừ đó, API tách nhiệm PHẢI TIẾP TỤC trả 409 và không mở luật (test: `test_the_admin_who_proposed_a_waiver_cannot_confirm_it`).
- G2 KHI người có `platform_admin` trong `memberships.role_keys` gọi một route kiểm quyền không có dấu duyệt, API PHẢI TIẾP TỤC cho qua cho tới dòng W2 rút `platform_admin` (test: `test_platform_admin_bypasses_scopes`).

## Trong phạm vi

- Bảng `platform.permissions`, `platform.tenant_roles`, `platform.tenant_role_permissions`, `platform.role_assignments`, `platform.tenant_access_versions`, `platform.role_change_requests`, `platform.object_actions`, `platform.tenant_role_object_privileges`, `studio.field_permissions` (tên theo ADR-0106 (Accepted)).
- Hàm `platform.effective_grants`, `platform.scopes_in`, `platform.workspace_reach`, `platform.grants_cover`, `platform.checker_candidates` (người `active` giữ một khóa, khác người đề xuất; dùng chung với `tenant-config:R8.5`), `platform.rbac_refusals`, `platform.bump_access_version`, `platform.install_system_roles`, `platform.install_role_template`; `platform.sod_violation` viết lại trên quyền hiệu lực.
- Route `GET /api/v1/admin/permissions`, `/api/v1/admin/roles` và con của nó, `/api/v1/admin/role-changes`; `GET /api/v1/me` thêm `grants`, `access_version`, `platform_bypass`; `GET /api/v1/auth/bootstrap` bỏ `roles`, `scopes`.
- Audit `platform.role.create`, `.update`, `.permissions_set`, `.delete`, `platform.role_assignment.grant`, `.revoke`, `platform.role_change.proposed`, `.confirmed`, `.withdrawn`.
- Quy ước: mỗi cụm Studio đăng ký khóa `studio.<area>.<verb>` của mình trong migration của chính nó, có nhãn, loại và mức rủi ro, giữ bằng test phủ của ticket 01.

## Ngoài phạm vi

| Việc                                                                                                                    | Vì sao                                                                                                                                                                                                                                              | Chủ                                                 |
| ----------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| `platform_admin` ra khỏi dữ liệu tenant, quyền vượt có hạn                                                              | DO-33 (a): quyền vượt tối đa 8 giờ trong `platform.platform_admin_grants`, script ghi kèm lý do, rút khi support-access 03 xong; W1 chỉ chặn tenant gán nó (R6.5) và giữ đường vượt cũ (G2)                                                         | tenant-rbac, W2                                     |
| Màn hình quản trị vai bằng antd                                                                                         | W1 giao API; ma trận đối tượng × hành động × mức cần đo hiệu năng ở 320 px trước (YC16)                                                                                                                                                             | tenant-rbac, W2                                     |
| Quản trị theo workspace; nhóm giữ vai trò                                                                               | Cần cây workspace và nhóm của org-and-principals; mức `team`, `workspace_subtree` vào cùng                                                                                                                                                          | tenant-rbac, W2                                     |
| Gán vai có hạn, lane hết hạn, xuất rà soát quyền                                                                        | API W1 không đặt `expires_at`; rà quyền đặc quyền theo quý, bản rà lưu theo hạn audit 1095 ngày (DO-61)                                                                                                                                             | tenant-rbac, W2                                     |
| Hai người cho thay đổi quyền trọng yếu                                                                                  | D11 đưa hai người vào mọi thay đổi nới quyền từ W1 (R7, ticket 03); W2 còn màn hàng đợi xác nhận trong giao diện quản trị                                                                                                                           | tenant-rbac, W2                                     |
| Giải thích quyền hiệu lực, nhật ký từ chối; luật tách nhiệm của tenant                                                  | W1 chỉ dùng luật toàn cục có sẵn và lỗi có `reason_code`                                                                                                                                                                                            | tenant-rbac, W2                                     |
| Điều kiện thuộc tính trên quyền của vai                                                                                 | Cần CEL (ADR-0114 (Accepted)) và predicate của record-access; đo trước khi cam kết                                                                                                                                                                  | tenant-rbac, W3                                     |
| Thực thi mức truy cập trên bản ghi                                                                                      | record-access đọc quyền hiệu lực và tầm với của spec này                                                                                                                                                                                            | record-access                                       |
| Ngữ nghĩa, mặc định và cửa phụ của quyền trường; luật người duyệt phải đọc được trường mà phê duyệt đóng dấu            | Spec này chỉ lưu quyền trường trong vai trò (ADR-0106 (Accepted)); R2.2 chỉ trỏ tới `field-security:R4.5` (DO-36)                                                                                                                                   | field-security                                      |
| Thành viên công ty, cây workspace, nhóm, tài khoản dịch vụ                                                              | Chủ thể và cơ cấu (ADR-0102 (Accepted), ADR-0103 (Accepted))                                                                                                                                                                                        | org-and-principals                                  |
| Quyền của lượt chạy không người; kiểm lại quyền khi tiếp tục lượt chạy; từ chối lượt chạy của thành viên không `active` | Run-as là tài khoản dịch vụ gắn theo phiên bản (DO-12); workflow-engine dựng lại scope sống qua một port runtime khai đọc `platform.scopes_in`, như `RunAllowancePort`; lý do `principal_inactive` của `RunControlPort` (H:org-and-principals:R4.6) | workflow-triggers, workflow-engine, agent-lifecycle |
| Hạn mức số vai trò theo gói                                                                                             | W1 dùng hằng 200 (R3.7)                                                                                                                                                                                                                             | usage-and-limits                                    |
| Quyền phủ định (deny)                                                                                                   | v1 chỉ cộng dồn (ADR-0104 (Accepted))                                                                                                                                                                                                               | không làm                                           |

## Kiểm soát

| #    | Kiểm soát                                  | Yêu cầu          | Test âm                                                                                                                                                                                                                                        |
| ---- | ------------------------------------------ | ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| RB1  | Danh mục và vai trò mẫu chỉ migration ghi  | R1.3             | `dw_app`, `dw_provisioner`, `dw_agent_ro` INSERT, UPDATE, DELETE `platform.permissions` và `platform.roles` → `permission denied`; trả quyền ghi → đỏ                                                                                          |
| RB2  | Danh mục phủ đúng mọi khóa được kiểm       | R1.1, R1.2       | Thêm route kiểm `x.y` không có dòng danh mục → test phủ đỏ; thêm khóa `active` không ai kiểm → đỏ                                                                                                                                              |
| RB3  | Người vận hành không mang khóa Studio      | R1.5             | Đăng ký `obj.lead.read` cho truy cập người vận hành → từ chối; gỡ tiền tố `obj.` → đỏ                                                                                                                                                          |
| RB4  | Bootstrap không lệch `/me`                 | R2.1             | Người chỉ có `approvals.decide` qua `approver_boost` → bootstrap và `/me` cùng trả khóa; quay lại tính theo vai → đỏ                                                                                                                           |
| RB5  | Một chủ quyền hiệu lực                     | R2.2             | Cùng người qua bộ quyền bổ sung: AccessContext, `/me`, người giữ quyền, tách nhiệm cùng thấy khóa; đổi hàm bỏ bộ quyền → mọi test đó đỏ                                                                                                        |
| RB6  | Mức `workspace` neo ở workspace được gán   | R2.4             | Khóa mức `workspace` từ A vắng ở `/me` của B; bỏ điều kiện neo trong hàm → đỏ                                                                                                                                                                  |
| RB7  | Nguồn không hiệu lực không cấp quyền       | R2.5             | Qua đường SQL: `platform.effective_grants` cho thành viên `suspended`, tenant `locked`, vai trò xóa mềm, gán quá hạn → khóa vắng; gỡ từng điều kiện trong hàm → đỏ                                                                             |
| RB8  | Vai trò và gán vai trò thuộc một tenant    | R3.3             | `GET /api/v1/admin/roles/{role_id}` của tenant B từ A → 404; INSERT gán với `role_id` của B dưới `app.tenant_id` A → FK kép từ chối; kết nối không đặt tenant → 0 dòng                                                                         |
| RB9  | Mức khớp loại quyền                        | R3.4             | `platform.roles.write` mức `workspace` → 23514; gỡ trigger → đỏ                                                                                                                                                                                |
| RB10 | Vai trò mẫu không lan sang bản nhân bản    | R3.2             | Migration thử đổi mẫu `approver` → vai trò `approver` của tenant giữ nguyên; đọc rơi về mẫu → đỏ                                                                                                                                               |
| RB11 | Tối đa 200 vai trò mỗi tenant              | R3.7             | Vai trò thứ 201 → `role_limit_reached`; hai giao dịch đồng thời ở vai trò thứ 200 → đúng một thành công; gỡ khóa tư vấn → đỏ                                                                                                                   |
| RB12 | Hiệu lực từ request đầu tiên               | R4.1             | Gỡ gán vai trò bằng SQL thô khi cache còn → request kế tiếp 403; khóa tenant qua route khóa đã gỡ `delete_pattern` → request kế tiếp 403; gỡ trigger tăng phiên bản → đỏ                                                                       |
| RB13 | Cache cũ là trượt                          | R4.2             | Bản ghi cache thiếu `grants` hay mang phiên bản cũ → dựng lại; đọc trường thiếu bằng mặc định → đỏ                                                                                                                                             |
| RB14 | Tách nhiệm qua mọi workspace               | R5.1, R5.3       | Hai vế một luật ở hai workspace → 23514, API 409 kèm id; gỡ trigger AFTER → đỏ                                                                                                                                                                 |
| RB15 | Chỉ trao quyền mình giữ                    | R6.1, R6.2       | Người giữ `approvals.decide` mức `workspace` đặt mức `tenant` → 403; cùng thao tác bằng SQL thô `dw_app` → 23514; gỡ lời gọi trong trigger → test SQL đỏ                                                                                       |
| RB16 | `bind` chỉ phủ vai trò không trọng yếu     | R6.3             | Người giữ `bind` gán vai trò có `platform.roles.write` mà mình không giữ → 403 `rbac_escalation`                                                                                                                                               |
| RB17 | Không tự gán                               | R6.4             | Tự gán, kể cả khi xác nhận đề xuất của người khác → 403; SQL thô với `app.user_id` là người nhận → 23514                                                                                                                                       |
| RB18 | Khóa không cấp cho tenant                  | R6.5             | Thêm `platform.admin` vào vai trò hay gán `platform_admin` → 422; SQL thô → 23514                                                                                                                                                              |
| RB19 | Vai trò hệ thống bất biến                  | R6.6             | Xóa, đổi khóa vai trò hệ thống, sửa quyền `tenant_owner` → 409 qua API, 23514 qua SQL thô                                                                                                                                                      |
| RB20 | Luôn còn chủ sở hữu công ty                | R6.7             | Gỡ gán `tenant_owner` cuối, xóa membership hay người dùng của chủ sở hữu công ty cuối cùng → `last_owner`; đặt `expires_at` cho gán `tenant_owner` → từ chối                                                                                   |
| RB21 | Hai người                                  | R7.1, R7.2, R7.5 | Người đề xuất tự xác nhận → 409; SQL thô `dw_app` ghi gán vai trò không mang đề xuất → 23514; bỏ kiểm người thứ hai → đỏ                                                                                                                       |
| RB22 | Không người duyệt thì không đề xuất        | R7.3             | Tenant chỉ một người giữ `platform.roles.write` → 409 `no_checker_available`, không có dòng đề xuất                                                                                                                                            |
| RB23 | Đề xuất hết hạn                            | R7.4             | Xác nhận ở 7 ngày cộng 1 giây → 409 `proposal_expired`; ở 7 ngày trừ 1 giây → nhận                                                                                                                                                             |
| RB24 | Ẩn không phải phân quyền                   | R8.2             | Người không có `platform.roles.write` gọi thẳng `PUT /api/v1/admin/roles/{role_id}/permissions` → 403                                                                                                                                          |
| RB25 | Một audit mỗi thay đổi, cùng giao dịch     | R8.3, R8.4       | Giao dịch lùi do 409 → không audit; gửi lại `Idempotency-Key` → không audit thứ hai; `details` có email → test đỏ                                                                                                                              |
| RB26 | Khóa lạc quan theo ETag                    | R8.5, R8.7, R8.8 | `If-Match` cũ → 412 `precondition_failed`, không đề xuất; thiếu `If-Match` → 428; vai trò đổi `version` giữa đề xuất và xác nhận → 409 `stale_version`, quyền không đổi                                                                        |
| RB27 | Cột cũ hết đường ghi                       | R8.6             | Ghi `permission_set_keys` khác rỗng hay `role_keys` có `member` → 23514 `ck_memberships_legacy_role_columns`                                                                                                                                   |
| RB28 | Hành động chưa thực thi không cấp được     | R9.2             | Cấp `share` trên `lead` khi `share` chưa `enforced` → 23514                                                                                                                                                                                    |
| RB29 | Mức `own` không mở workspace               | R9.4             | `obj.lead.read` mức `own` → tầm với workspace rỗng; hàm coi `own` như `workspace` → đỏ                                                                                                                                                         |
| RB30 | Leo thang quyền trên đối tượng và trường   | R9.5             | Người giữ `obj.lead.read` mức `workspace` đặt mức `tenant` → 23514; thêm `fld.lead.phone.edit` mình không giữ → 23514                                                                                                                          |
| RB31 | Xóa định nghĩa thì xóa quyền               | R9.3             | Xóa đối tượng `lead` → không còn dòng quyền nào của nó; `/me` kế tiếp không có `obj.lead.*`                                                                                                                                                    |
| RB32 | Chỉ thay đổi chỉ siết đi một người         | R7.1, R7.6       | `PUT .../permissions` vừa bỏ vừa thêm một khóa → 202 đề xuất, quyền chưa đổi; nâng mức `workspace` lên `tenant` → 202; xóa mềm vai trò → 202; gỡ gán vai trò → 200, áp ngay, một audit, không dòng đề xuất; coi thay đổi trộn là chỉ siết → đỏ |
| RB33 | `bind` không phủ quyền đọc trường nhạy cảm | R6.8             | Người chỉ giữ `bind` gán vai trò có `fld.lead.cccd.read` trên trường `sensitive` → 403 `rbac_escalation`; cùng thao tác bằng SQL thô → 23514; coi `fld.*` nhạy cảm là không trọng yếu → đỏ                                                     |

## Tiêu chí xong

- Mọi tiêu chí R và G có test; mọi kiểm soát RB1-RB33 có test âm đã thấy đỏ khi gỡ kiểm soát, ghi ở Comments của ticket.
- `make ci` xanh, gồm integration của `dw_platform` và `apps/api`; `test_rls_coverage.py`, `test_privileges.py`, `test_offboarding.py` có dòng cho mọi bảng mới.
- Số đo `platform.effective_grants` và một lần đọc phiên bản mỗi request ở cỡ D12 (5.000 người dùng, 200 workspace mỗi tenant) ghi ở Comments của ticket 02.

## Phụ thuộc

- org-and-principals: bảng thành viên công ty và trạng thái (`.claude/plans/studio/org-and-principals/issues/02-thanh-vien-cap-tenant.md`); ticket 02 ở đây chờ nó. Chiều ngược: org-and-principals/03 chờ ticket 02 ở đây (`platform.grants_cover`, gán vai trò cho tài khoản dịch vụ). AccessContext từ chối người không `active` là cửa của `org-and-principals:R4.3`; `platform.effective_grants` là chủ của câu "giữ quyền gì" (R2.5).
- foundations-hardening/02: xóa cache theo mẫu ở route khóa, mở khóa, offboard (`foundations-hardening:R3.3`) là tạm; ticket 02 ở đây gỡ nó và chờ ticket đó.
- custom-objects: `studio.object_defs`, `studio.field_defs` với `api_name` bất biến và khóa `(tenant_id, id)` (ADR-0107 (Accepted)); ticket 04 chờ `.claude/plans/studio/custom-objects/issues/02-luoc-do-dinh-nghia-object.md`.
- record-access và field-security đọc `platform.effective_grants` và `platform.workspace_reach`, không tính lại (ADR-0105 (Accepted), ADR-0106 (Accepted)); record-access bật `share`, custom-objects bật `export` trong migration giao đường đọc của chúng.
- field-security là chủ luật người duyệt phải đọc được mọi trường mà bước phê duyệt đóng dấu (`field-security:R4.5`); R2.2 chỉ trỏ tới.
- tenant-config: cơ chế hai người của cấu hình (`tenant-config:R8.5`) dùng chung `platform.checker_candidates` của ticket 02 và `details.reason_code` `no_checker_available`, `second_person_required` (ADR-0104 (Accepted), ADR-0110 (Accepted)).
- app-standards: problem+json, `Idempotency-Key` gắn người gọi, ETag và `If-Match` (ADR-0108 (Accepted)); ticket 03 chờ app-standards/01, /02, /03.
- Seam: `authz.require(action)` giữ nghĩa vì `AccessContext.scopes` vẫn là phép chiếu cho workspace đang làm việc (ADR-0104 (Accepted) mục 3).
- Kiểm lại khi: org-and-principals thêm cây workspace hay nhóm (W2) → ticket 02 (`platform.workspace_reach`, mức `team`, `workspace_subtree`); custom-objects đổi khóa định nghĩa → ticket 04; số đo FOG-38 của `platform.effective_grants` ở cỡ D12 trượt ngân sách → ticket 02; tenant-config đổi cơ chế hai người hay mã lỗi chung → ticket 02, 03.

## Câu hỏi còn mở

## Quyết định

- 22/10/2026 (người yêu cầu): D1 và D3: workspace sở hữu dữ liệu, vai trò cấp quyền có mức truy cập, quyền trường theo vai trò; W1 có mức `own`, `workspace`, `tenant`, còn `team` và `workspace_subtree` vào W2 cùng nhóm và cây (ADR-0104 (Accepted)). Sửa: R2, R3, R9.
- 23/10/2026 (người yêu cầu): Theo ADR-0104 (Accepted), vai trò của tenant là dữ liệu trên danh mục quyền do code sở hữu. Spec này sửa đổi ADR-0012 (Accepted) (tiền đề "both tables change only in migrations" và tách nhiệm theo từng membership) và tiền đề "the catalogue changes only in migrations" của migration `648e2f7c3edb`; danh mục quyền và vai trò mẫu vẫn chỉ migration ghi. Đạt chưa ký (Q1). Sửa: R1, R3, R5.
- 23/10/2026 (người yêu cầu): D11: hai người luôn luôn, áp cho mọi thay đổi vai trò và gán vai trò, gồm gán `member` khi mời; công ty chỉ có một người giữ quyền xác nhận thì không đổi được vai trò cho tới khi người vận hành cài chủ sở hữu công ty thứ hai qua `POST /api/v1/platform/tenants/{tenant_id}/org-admins`. Sửa: R7, ticket 03.
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: ADR-0104 (Accepted) mục Open 3 và ADR-0110 (Accepted) mục Open 1 nói D11 là cấu hình theo ADR-0110 (Accepted), chưa gồm gán vai trò, chờ người yêu cầu xác nhận; chỉ đạo viết spec ngày 23/10/2026 nói D11 áp cho thay đổi vai trò; theo chỉ đạo. Nếu sai thì: bỏ R7, ticket 03 trở lại một người.
- 23/10/2026 (agent, tạm): Hai người theo mẫu ADR-0012 (Accepted) (đề xuất, người khác giữ cùng quyền xác nhận, ràng buộc người thứ hai) với hạn 7 ngày của brief B3, không theo phê duyệt nghiêm `config.` của ADR-0110 (Accepted): thay đổi áp trong giao dịch của người duyệt nên trigger chống leo thang quyền thấy đúng người làm. Nếu sai thì: ticket 03 chuyển sang phê duyệt không lượt chạy với handler trong worker.
- 23/10/2026 (agent, tạm): DO-10 theo khuyến nghị (a): bộ quyền bổ sung là vai trò loại `permission_set`; mức `team` chỉ gồm bản ghi của tôi và của nhóm tôi; tách nhiệm xét theo người trên cả tenant. Sửa: R5.1. Nếu sai thì: tách nhiệm theo membership mở lại kẽ hở hai workspace; `team` rộng hơn thêm một nhánh closure, đo trước.
- 23/10/2026 (agent, tạm): DO-36 theo khuyến nghị (a): người duyệt phải giữ quyền đọc các trường mà phê duyệt hiện; ứng viên duyệt tìm theo mức truy cập qua quyền hiệu lực. Sửa: R2.2. Nếu sai thì: luật chọn người duyệt đổi, hàm quyền hiệu lực không đổi.
- 23/10/2026 (agent, tạm): W1 giữ `platform_admin` là giá trị cũ duy nhất được phép trong `memberships.role_keys`, do script nền tảng ghi, không thành vai trò của tenant. Sửa: R6.5, R8.6, G2. Nếu sai thì: DO-33 chọn rút ngay thì ticket 03 xóa giá trị này và G2 thành test âm.
- 23/10/2026 (agent, tạm): `platform.grants_cover` và cột `tenant_grantable` ra đời ở ticket 02 cùng hàm quyền hiệu lực, vì org-and-principals/03 chỉ chờ ticket 02 và quyền tính động của `tenant_owner` đọc `tenant_grantable`; `platform.rbac_refusals` của ticket 03 dùng `grants_cover`. Nếu sai thì: org-and-principals/03 phải chờ ticket 03.
- 23/10/2026 (agent, tạm): Mức `critical` cho `platform.admin`, `platform.roles.write`, `platform.roles.bind`, `platform.sod_waivers.write`; `elevated` cho các khóa `platform.*` khác; còn lại `standard`. Sửa: R1.1, R6.3. Nếu sai thì: đổi dòng danh mục trong migration, `bind` phủ hay không phủ vai trò tương ứng.
- 23/10/2026 (người yêu cầu): D12: 5.000 người dùng và 200 workspace mỗi tenant là cỡ đo của hàm quyền hiệu lực, trigger và cache. Sửa: Tiêu chí xong.
- 23/10/2026 (Đạt): DO-09.1 (a): chấp nhận ADR-0104 (Accepted): vai trò là dữ liệu tenant, quyền hiệu lực là hợp mọi gán vai trò trong tenant, mỗi mức neo ở workspace được gán; ADR-0104 (Accepted) ghi dòng sửa đổi ADR-0012 (Accepted); `test_privileges.py` viết lại trong cùng thay đổi. Còn nợ: FOG-38 (giá `platform.effective_grants` và một lần đọc phiên bản mỗi request ở cỡ D12, đo ở ticket 02) và FOG-49 (ai chuyển dw-proterial khỏi `memberships.role_keys` trước khi ticket 03 khóa cột). Hỏi: Q1. Sửa: R2.3, ticket 02, 04.
- 23/10/2026 (Đạt): DO-10.1 (a) và DO-10.2 (a): xác nhận quyết tạm DO-10: bộ quyền bổ sung là vai trò loại `permission_set`; mức `team` (W2) là của tôi và nhóm tôi; tách nhiệm xét theo người trên cả tenant, ADR-0104 (Accepted) sửa đổi ADR-0012 (Accepted). Sửa: R5.1.
- 23/10/2026 (người đặt yêu cầu và Đạt): Phạm vi D11 (DO-09.2): mọi thay đổi và gán vai trò từ W1 cần hai người, kể cả gán `member` khi mời; công ty một chủ sở hữu không đổi được vai trò tới khi có người thứ hai; thay đổi chỉ siết quyền (gỡ gán vai trò, bỏ quyền hay hạ mức trong vai trò) một người cộng audit, nới quyền luôn hai người ("đóng một người, mở hai người"; ADR-0104 (Accepted) mục 10). Đóng mâu thuẫn nguồn ghi cùng ngày về mục Open 3 của ADR-0104 (Accepted). Sửa: R7.1, R7.3, R7.5, R7.6, RB32, ticket 03.
- 23/10/2026 (Đạt): DO-32.1 (a): luật giữ quyền (YC13); quản trị viên tạo được quản trị viên; `platform.roles.bind` gán, gỡ vai trò không trọng yếu; một vai trò mang `fld.*` trên trường `pd_category = 'sensitive'` tính là trọng yếu với `bind`; người xác nhận một lần gán qua `bind` cũng phải giữ `bind` (R7.1). Hỏi: Q2. Sửa: R6.3, R6.8, RB33, ticket 03, 04.
- 23/10/2026 (Đạt): DO-32.2 (a): `tenant_owner` đầu tiên của tenant đã có là người giữ `org_admin` ở workspace `main`, audit `system:rbac_migration`; tenant không có ai thì người vận hành gán qua `POST /api/v1/platform/tenants/{tenant_id}/org-admins`; migration in danh sách tenant còn dưới hai chủ sở hữu và tenant không có `org_admin` ở `main`. Hỏi: Q2. Sửa: R3.6, ticket 02.
- 23/10/2026 (Đạt): DO-33 (a): `platform_admin` thành quyền vượt có hạn tối đa 8 giờ trong `platform.platform_admin_grants`, script ghi kèm lý do, rút khi support-access 03 xong; nó không vượt dấu duyệt, truy cập hỗ trợ, tách nhiệm hay quyền bản ghi (ADR-0104 (Accepted) mục 8); việc nằm ở dòng W2 của Ngoài phạm vi, quyết trước GA. Hỏi: Q3. Sửa: Ngoài phạm vi.
- 23/10/2026 (Đạt): DO-61 (a): xuất dữ liệu cá nhân cần quyền xuất riêng có audit; trường Bảo vệ chỉ xuất cho người đọc được không che; rà quyền đặc quyền theo quý, bản rà lưu theo hạn audit 1095 ngày; trước GA. Hỏi: Q4. Sửa: Ngoài phạm vi.
- 23/10/2026 (Đạt): `D:tenant-config/05~tenant-rbac:R7.1` (b): vai trò giữ mẫu ADR-0012 (Accepted), áp trong giao dịch người xác nhận để `platform.rbac_refusals` đọc đúng `app.user_id`; ngoại lệ ghi ở ADR-0104 (Accepted) và ADR-0110 (Accepted); cấu hình khác đi qua tenant-config. Hai cơ chế dùng chung một hàm SQL tìm người xác nhận trên `platform.effective_grants` (`platform.checker_candidates`, ticket 02) và cùng `details.reason_code` `no_checker_available`, `second_person_required`, cùng luật hạn đề xuất; hạn 7 ngày của brief B3 (R7.4) là hằng của nền tảng cho đề xuất, khác hạn duyệt phát hành vì hạn đó là số trong chính sách cổng mà công ty siết được (ADR-0120 (Accepted) mục 3). Sửa: R7.3, Trong phạm vi, Phụ thuộc, ticket 02, 03.
- 23/10/2026 (Đạt): `A:org-and-principals:R4.3~tenant-rbac:R2.5` (b): hai cửa hai câu: AccessContext từ chối người không `active` (`org-and-principals:R4.3`), `platform.effective_grants` lọc quyền (R2.5); ticket 02 gỡ bộ lọc riêng của `scope_holders.py`; RB7 thử qua đường SQL với phép đột biến gỡ điều kiện trong hàm. Sửa: RB7, Phụ thuộc, ticket 02.
- 23/10/2026 (Đạt): `A:foundations-hardening:R3.3~tenant-rbac:R4.1` (a): xóa cache theo mẫu ở route khóa, mở khóa, offboard của foundations-hardening/02 là tạm; ticket 02 gỡ nó cùng mọi `delete_pattern` khác và chờ ticket đó; phiên bản quyền trong khóa cache là cơ chế duy nhất; FH8 giữ hành vi, phép đột biến của nó thành gỡ trigger `bump_access_version` trên `platform.tenants`. Sửa: RB12, Phụ thuộc, ticket 02.
- 23/10/2026 (Đạt): DO-36 (a): field-security là chủ luật người duyệt phải giữ quyền đọc mọi trường mà bước phê duyệt đóng dấu (`field-security:R4.5`); workflow-nodes/06 áp bằng `decision_guards` của `studio.step.approval`; R2.2 chỉ trỏ tới. Sửa: Ngoài phạm vi, Phụ thuộc.
- 23/10/2026 (Đạt): DO-01 (a) và `E:CLAUDE.md#tenancy-and-authorization~tenant-rbac:platform.tenant_roles` (a): `platform.tenant_roles`, `platform.tenant_role_permissions`, `platform.tenant_access_versions`, `platform.role_change_requests`, `platform.tenant_role_object_privileges`, `studio.field_permissions` vào lớp bảng toàn tenant; ticket tạo bảng ghi một dòng lý do vào danh sách của `test_rls_coverage.py`. Sửa: Hiện trạng, ticket 02, 03, 04.
- 23/10/2026 (Đạt): Chấp nhận rủi ro: trigger `rbac_refusals_*` của ticket 03 và trigger tài khoản dịch vụ của org-and-principals/03 cùng nằm trên `platform.role_assignments` và `platform.tenant_role_permissions` mà hai ticket không chờ nhau (OPS-b cạnh 11); trigger tài khoản dịch vụ áp cả `dw_provisioner`, `dw_migrator` còn `platform.rbac_refusals` miễn hai vai này, nên giữ hai trigger, thứ tự bắn theo bảng chữ cái của tên là chủ ý và test catalog mỗi bên chỉ khẳng định trigger của mình.
- 23/10/2026 (agent, tạm): theo ADR-0108 (Accepted) mục 3, mutation trên vai trò dùng ETag và `If-Match` (412 khi lệch, 428 khi thiếu); `stale_version` chỉ còn cho vai trò đổi `version` giữa lúc đề xuất và lúc xác nhận (`B:app-standards:R3.2~tenant-rbac:R8.5`). Sửa: R8.5, R8.7, R8.8, RB26, Phụ thuộc, ticket 03. Nếu sai thì: quay lại `version` trong thân với 409, kèm ngoại lệ ghi ở app-standards.
- 23/10/2026 (agent, tạm): ticket 03 chờ app-standards/01, /02, /03 vì route của nó dùng problem+json, `Idempotency-Key` gắn người gọi và `If-Match` (`I:app-standards/02~tenant-rbac/03`); R6.8 nằm ở ticket 04, nơi `fld.*` vào vai trò, và mở rộng `platform.rbac_refusals` của ticket 03 mà ticket 04 đã chờ. Sửa: R6.8, ticket 03, 04. Nếu sai thì: bỏ cạnh tới app-standards khi route không còn dùng ba quy ước đó.
- 23/10/2026 (agent, tạm): `platform.usage.read` của danh mục là khóa đọc sử dụng duy nhất, usage-and-limits dùng lại nó thay cho `usage.read` (`G:tenant-rbac/01~usage-and-limits:api`). Sửa: ticket 01. Nếu sai thì: danh mục thêm một khóa và ghi `retired` cho khóa cũ.

## Danh sách ticket

| #   | Ticket                                                                                                                               |
| --- | ------------------------------------------------------------------------------------------------------------------------------------ |
| 01  | [Một chủ cho quyền: bootstrap qua effective_scopes và danh mục platform.permissions](issues/01-mot-chu-cho-quyen.md)                 |
| 02  | [Vai trò của tenant là dữ liệu: gán vai trò, vai trò mẫu, hàm quyền hiệu lực và phiên bản quyền](issues/02-vai-la-du-lieu-tenant.md) |
| 03  | [Chống leo thang quyền và API quản trị vai trò, gán vai trò, audit](issues/03-chong-leo-thang-va-api-quan-tri-vai.md)                |
| 04  | [Quyền theo đối tượng có độ sâu và quyền trường trong vai trò](issues/04-quyen-doi-tuong-va-truong-co-do-sau.md)                     |
