# 01 — Một chủ cho quyền: bootstrap qua effective_scopes và danh mục platform.permissions

Status: resolved (2026-11-02, main)
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R1.6, R2.1, RB1, RB2, RB3, RB4

## Mục tiêu

Hai sửa P0 làm được ngay, không chờ quyết định nào: bootstrap hết lệch với AccessContext (R2.1), và mọi khóa quyền có
đúng một dòng trong danh mục quyền do migration ghi, có nhãn, loại và mức rủi ro (R1). Gộp từ brief B3 ticket 01, 02 và
phần bootstrap của foundations-hardening 05 (brief B11).

## Việc cần làm

1. **Bootstrap.** `SqlIdentityBootstrap._read_memberships` bỏ phần tự tính quyền từ `role_keys`
   (`identity_provisioning.py:252-269`) và gọi `effective_scopes(session, role_keys, permission_set_keys)`
   (`membership_lookup.py:33-55`) cho từng membership trong cùng phiên. Sửa docstring sai của route bootstrap
   (`apps/api/src/dw_api/routes/v1/auth.py:1-6` nói người mới thành member; mặc định là từ chối). Không đổi hợp đồng API,
   không đổi web (ticket 02 chuyển web sang `GET /api/v1/me`). Ticket này sở hữu cách bootstrap tính quyền;
   org-and-principals/02 chờ ticket này (OPS-b cạnh 10) và chỉ thêm điều kiện thành viên `active` vào cùng
   `_read_memberships`.
2. **Danh mục.** Migration (id hex của `alembic revision`, tên tệp mang số thứ tự): `platform.permissions`:
    - `key text PRIMARY KEY CHECK (key ~ '^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$')`;
    - `area text NOT NULL`, `label_vi text NOT NULL CHECK (btrim(label_vi) <> '')`, `description_vi text`;
    - `scope_kind text NOT NULL CHECK (scope_kind IN ('tenant','workspace','record'))`;
    - `risk text NOT NULL CHECK (risk IN ('standard','elevated','critical'))`;
    - `status text NOT NULL CHECK (status IN ('active','unassigned','retired'))`, `status_reason text`,
      `ck_permissions_status_reason CHECK (status = 'active' OR btrim(coalesce(status_reason, '')) <> '')`;
    - `owner_package text NOT NULL`, `created_at timestamptz NOT NULL DEFAULT now()`.
      Bảng toàn cục, không `tenant_id`, không RLS. REVOKE INSERT, UPDATE, DELETE, TRUNCATE khỏi `dw_app`, `dw_provisioner`,
      `dw_agent_ro` (mỗi câu trong khối DO kiểm vai tồn tại, như `648e2f7c3edb`); GRANT SELECT cho ba vai đó.
3. **Seed.** Mọi khóa đang dùng, kể cả bất thường, mỗi khóa có `scope_kind` và `risk` ghi trong migration:
    - trạng thái theo ba luật mà (a), (b), (c) của bước 5 giữ: khóa một vai trò mẫu hay bộ quyền cấp không bao giờ
      `unassigned`; khóa code kiểm không bao giờ `retired`; khóa `active` có chỗ kiểm hay nằm ở danh sách ngoại lệ.
      Bất thường mang trạng thái và lý do ở `status_reason`: `approvals.pending` (vai `approver`, `manager`,
      `director` và bộ `approver_boost` cấp; `approvals.py:162` chỉ dùng nó làm khóa con trỏ trang) và `feedback.inbox`
      (`org_admin` cấp; `feedback.py:201` là khóa con trỏ trang, route kiểm `platform.members.read`) là `retired`;
      `runs.cancel` (`runs.py:127`), `knowledge.publish_global` (`dw_knowledge/gateway.py:70`), `crm.records.all.read`
      (`membership_lookup.py:31`) và `platform.usage.read` (gỡ khỏi `org_admin` ở
      `0013_drop_model_usage_ledger.py:121-125`) là `unassigned`, vì không vai trò mẫu hay bộ quyền nào cấp;
      không đổi hành vi route nào, việc sửa từng bất thường ghi ở Comments thành đề xuất;
    - `platform.usage.read` là khóa đọc sử dụng duy nhất: ghi `unassigned` với lý do "usage-and-limits dùng lại và đưa
      về `active` trong migration của nó", không có khóa `usage.read` thứ hai (Quyết định 23/10/2026 của spec);
    - `risk = 'critical'` cho `platform.admin` và `platform.sod_waivers.write`, `elevated` cho các khóa `platform.*`
      khác, `standard` cho phần còn lại (spec, Quyết định 23/10/2026);
    - `scope_kind = 'tenant'` cho khóa route đọc toàn tenant (`platform.*`, `support.*`), `workspace` cho khóa còn lại;
      bảng phân loại nằm trong docstring của migration.
4. **Route.** `GET /api/v1/admin/permissions` (`platform.roles.read`, hằng `ROLES_READ` đã có): mảng `key`, `area`,
   `label_vi`, `scope_kind`, `risk`, `status`, sắp theo `area` rồi `key`; `make generate-contracts` và client trong
   `packages/typescript/api-client`.
5. **Test phủ** `packages/python/dw_platform/tests/integration/test_permission_catalogue.py`:
   (a) mọi khóa trong `platform.roles` và `platform.permission_sets` có dòng `active` hay `retired`, không `unassigned`;
   (b) mọi khóa mà code kiểm có dòng `active` hay `unassigned`, không `retired`. Khóa code kiểm đọc bằng `ast` trên
   `apps/*/src` và `packages/python/*/src`: đối số `action` của mọi lời gọi `.require(` có đối số đó, đối số đầu của
   `idempotent(`, đối số của `has_scope(`, vế trái của `in`/`not in` khi vế phải là tên hay thuộc tính `scopes`, và mọi
   hằng chuỗi cấp module tên `*_SCOPE`; mỗi cái là chuỗi viết thẳng hay tên hằng cấp module, kể cả hằng nhập từ module
   khác (`MEMBERS_WRITE`, `ROLES_READ`, `DW_MANAGE`, `APPROVALS_DECIDE`). Đối số là hàm kiểm (`_may_decide`,
   `_owner_of_path`, `check_request` của `support.py`) thì bỏ qua, vì hàm đó gọi `.require(` mà (b) đã đọc; một chỗ khác
   mà test không giải ra chuỗi làm (b) đỏ, trừ danh sách cửa chuyển tiếp trong test, mỗi mục một lý do, ở 2/11/2026 đúng
   bốn chỗ: `authorization.py:28` và `:71` (cửa phân quyền nhận khóa từ nơi gọi), `has_scope` của `access_context.py:71`,
   `_authorize` của `idempotency.py:337-340` (khóa đến từ `idempotent(`). Cộng `required_scopes` trong `configs/tools`,
   `scope` và `anyScope` trong `apps/web/lib/nav/registry.ts`;
   (c) mọi khóa `active` có ít nhất một chỗ kiểm, trừ danh sách ngoại lệ trong test, mỗi mục một lý do;
   (d) mọi khóa `studio.*` của danh mục và mọi khóa `studio.*` mà code kiểm có đúng ba đoạn `studio.<area>.<verb>`
   (R1.6), với khu vực nằm trong danh sách khu vực của test: dạng số nhiều của danh từ đếm được (`agents`, `workflows`,
   `objects`, `versions`, `bindings`, `tools`, `packs`, `evals`; khu vực mới vào danh sách ở dạng số nhiều cùng khóa
   đầu tiên của nó) và năm khu vực số ít, mỗi mục một lý do: `publish` (một hành động), `lifecycle` (một quá trình),
   `datahub` (tên sản phẩm), `code` (danh từ không đếm), `mcp` (tên giao thức). (d) chỉ đọc khóa quyền, không đọc loại
   phê duyệt hay tên sự kiện audit.
   Từ nay mỗi cụm Studio đăng ký mọi khóa nó kiểm trong migration của chính nó, và test này giữ chúng, kể cả khóa ngoài
   tiền tố `studio.` mà cụm đó kiểm (`platform.limits.manage` của usage-and-limits, `runs.read_payloads` của
   telemetry-and-audit, `runs.reconcile` của workflow-engine/08, mức rủi ro cao, `tenant_grantable` đúng, H-8); ticket đăng ký chờ ticket 02 (cột `tenant_grantable`) và câu INSERT nêu mọi cột NOT NULL
   của danh mục lúc đó (Quyết định 24/10/2026 của spec); ticket này không đăng ký khóa của cụm khác.
6. **Người vận hành.** Thêm `studio.`, `obj.`, `fld.`, `connections.`, `integrations.` vào `FORBIDDEN_SCOPE_PREFIXES`
   (`support_access.py:63-72`), để người vận hành không được cấp `connections.manage` hay `integrations.admin` của
   tenant.
7. `test_privileges.py` khẳng định quyền DB của `platform.permissions` cho từng vai ứng dụng.

## Tiêu chí chấp nhận

- [x] R2.1 (RB4): integration: thành viên có vai `member` và bộ quyền `approver_boost` → bootstrap trả `approvals.decide`, bằng đúng tập `GET /api/v1/me` trả ở cùng workspace; quay lại tính theo vai → test đỏ; người không có bộ quyền: kết quả không đổi.
- [x] R1.3 (RB1): `dw_app`, `dw_provisioner`, `dw_agent_ro` INSERT, UPDATE, DELETE trên `platform.permissions` → `permission denied`; trả lại quyền ghi trong migration thử → test đỏ.
- [x] R1.1 (RB2): thêm một route kiểm `x.y` không có dòng danh mục → (b) đỏ; thêm `authz.require(action=X_Y)` với hằng `X_Y = "x.y"` trong một service của `packages/python` → (b) đỏ; một `.require(action=...)` mà test không giải ra chuỗi, ngoài danh sách chỗ gọi → (b) đỏ; xóa một dòng danh mục đang được kiểm → (b) đỏ; ghi `retired` cho `runs.cancel` → (b) đỏ; ghi `unassigned` cho `approvals.decide` → (a) đỏ.
- [x] R1.2 (RB2): thêm khóa `active` không ai kiểm → (c) đỏ; khóa đó ở danh sách ngoại lệ có lý do → xanh.
- [x] R1.4: `GET /api/v1/admin/permissions` trả đủ sáu trường cho mọi dòng; người không có `platform.roles.read` → 403.
- [x] R1.5 (RB3): đăng ký `obj.lead.read`, `studio.agents.publish`, `connections.manage` hay `integrations.admin` cho truy cập người vận hành → bị từ chối; gỡ từng tiền tố khỏi `FORBIDDEN_SCOPE_PREFIXES` → test của tiền tố đó đỏ.
- [x] R1.6: dòng danh mục thử `studio.agents.settings.manage` (bốn đoạn) hay `studio.agent.read` (khu vực số ít ngoài năm ngoại lệ) → (d) đỏ và nêu khóa; `studio.agents.manage_settings`, `studio.publish.approve`, `studio.datahub.manage` → xanh; loại phê duyệt `studio.publish.object` và tên audit `studio.version.published` không nằm trong tập (d) đọc.
- [x] Xong: `make ci` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/identity_provisioning.py:252-269`; spec: R2.1.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:33-55`; spec: R2.1.
- `apps/api/src/dw_api/routes/v1/auth.py:1-6`; spec: R2.1.
- `apps/api/src/dw_api/routes/v1/runs.py:127`; spec: R1.1, R1.2.
- `db/migrations/versions/648e2f7c3edb_roles_and_permission_sets_read_only_to_.py:51-57`; spec: R1.3.
- `packages/python/dw_platform/src/dw_platform/application/admin_console.py:32`; spec: R1.4.
- `packages/python/dw_platform/src/dw_platform/application/support_access.py:63-72`; spec: R1.5.
- ADR-0104 (Accepted) mục 1; brief B3 mục 1.10 và ticket 02.

## Comments

- 2026-10-24 (agent): Đạt nhận các khuyến nghị vòng 2 (24/10/2026): thêm `connections.`, `integrations.` vào `FORBIDDEN_SCOPE_PREFIXES` (`D:connections-and-vault:trong-phạm-vi~tenant-rbac:R1.5`); quy ước đăng ký khóa ghi rõ khu vực số nhiều và phủ cả khóa ngoài tiền tố `studio.` (`B:agent-lifecycle:phụ-thuộc~tenant-rbac/01`).
- 2026-10-24 (agent): vòng sửa 4: thêm R1.6 và kiểm (d) của bước 5 cho quy ước ba đoạn `studio.<area>.<verb>` mà spec là chủ (Quyết định 24/10/2026 của spec, khóa bốn đoạn của ADR-0117 (Accepted) đổi tên); ticket đăng ký khóa của cụm khác chờ tenant-rbac/02 và nêu mọi cột NOT NULL trong INSERT (`C:custom-objects/02~tenant-rbac/02`), nên cột `tenant_grantable` vẫn ra đời ở ticket 02, không ở đây.
- 2026-10-25 (agent): lượt h, theo H-8: bước 5 nêu `runs.reconcile` (workflow-engine/08) trong các ví dụ khóa ngoài
  tiền tố `studio.` mà cụm chủ đăng ký; mặc định chỉ `tenant_owner` có nó (R2.7). Không đổi phạm vi ticket này.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH B1: kiểm (b) chỉ đọc `action="..."` viết thẳng trong
  `apps/api/src` và hằng `*_SCOPE`, nên mù với phần lớn chỗ kiểm hôm nay: `authz.require(action=HẰNG)` trong service
  (`admin_console.py:193-336`, `digital_workers.py:248-305`, `separation_of_duties.py:120-150`), `APPROVALS_DECIDE` ở
  `approval_flow.py:263-266`, `idempotent(MEMBERS_WRITE, ...)`, `idempotent(DW_MANAGE, ...)`, `_RECORDS_ALL_READ in
scopes` (failure-modes #0); khóa mới kiểm qua hằng qua được (b) không dòng danh mục, còn (c) báo
  `platform.roles.read`, `dw.manage`, `approvals.decide` là không ai kiểm. Sửa: bước 5 (b) định nghĩa chỗ kiểm đọc bằng
  `ast` (đối số `action` của `.require(`, đối số đầu của `idempotent(`, `has_scope(`, `in ... scopes`, hằng
  `*_SCOPE`, giải hằng nhập từ module khác), chỗ không giải ra chuỗi làm (b) đỏ trừ danh sách có lý do; tiêu chí R1.1
  thêm ca hằng trong service và ca không giải được. Nếu sai thì: (b) quay về danh sách nguồn cũ và mọi khóa kiểm qua
  hằng vào danh sách ngoại lệ của (c), mỗi mục một lý do, và RB2 ghi rằng nó không thấy chỗ kiểm qua hằng.
- 2026-11-02 (agent, theo ủy quyền 31/10/2026): gate HIGH B2: (a) đòi dòng `active` cho mọi khóa mà vai trò mẫu
  cấp, trong khi bước 3 cho `approvals.pending` (vai `approver`, `manager`, `director`, bộ `approver_boost` cấp,
  `0001_platform_reference.sql:55-96`) và `feedback.inbox` (`org_admin` cấp) là `retired` hay `unassigned`, và để
  người dựng chọn giữa hai trạng thái. Sửa: ba luật trạng thái (khóa vai trò mẫu cấp không `unassigned`, khóa code kiểm
  không `retired`, khóa `active` có chỗ kiểm hay ở ngoại lệ) ở bước 3 và (a), (b); sáu bất thường mang trạng thái đã
  định (hai `retired`, bốn `unassigned`, `platform.usage.read` không còn được cấp từ `0013_drop_model_usage_ledger.py:121-125`);
  tiêu chí R1.1 thêm ca `retired` trên khóa được kiểm và `unassigned` trên khóa được cấp; spec thêm dòng Quyết định
  2/11/2026. Nếu sai thì: `approvals.pending` và `feedback.inbox` ghi `active` và vào danh sách ngoại lệ của (c) với lý
  do "khóa cũ được cấp, không ai kiểm", và luật thứ hai rút.
- 2026-11-02 (agent): ghi chú MEDIUM và LOW của gate cho người dựng, chưa sửa: (M1) neo đã trôi từ 23/10/2026:
  `_read_memberships` nay ở `identity_provisioning.py:261-320`, phần tự tính quyền từ vai ở `290-307` (neo `252-269`
  của bước 1 và Nguồn nay trỏ vào cuối `_provision_default_membership`); `effective_scopes` ở `membership_lookup.py:34-56`;
  `FORBIDDEN_SCOPE_PREFIXES` ở `support_access.py:64-73`; neo spec: lời gọi `effective_scopes` của `scope_holders.py` ở
  `74-77`, test catalogue của `test_privileges.py` ở `131-181`; tìm theo tên. (M2) `make ci` (`Makefile:170`) không
  chạy integration, nên dòng `Xong:` xanh mà không chạy test nào của R2.1, R1.1-R1.3, R1.6; theo `wave-close.md` đọc là
  cổng nhanh cộng `uv run python -m pytest packages/python/dw_platform/tests/integration apps/api/tests/integration`
  cho các test ticket thêm. (M3) bước 1 gọi `effective_scopes` cho từng membership: hai câu SQL mỗi membership ở
  bootstrap (như `scope_holders._scopes_of`); ticket đổi cách request tới DB nên `latency.md` áp, đo ở cuối wave; một
  biến thể đọc theo lô trong `membership_lookup.py` mà cả hai bên gọi là lựa chọn nếu số đo trượt. (M4) tiêu chí R2.1
  chỉ có một membership; thêm ca hai membership ở hai tenant, `approver_boost` chỉ ở A, để bắt lỗi gộp
  `permission_set_keys` qua các dòng như phần gộp `role_keys` hiện có (`identity_provisioning.py:290-292`). (M5)
  khóa ra đời sau ticket: `dw.read`, `dw.manage` (`be93e0c26a4c`, bảng DW toàn tenant với `owning_workspace_id`) rơi
  vào `scope_kind = 'workspace'` theo luật bước 3, nên ticket 02 neo chúng ở workspace được gán (R2.4); ghi lý do
  trong docstring migration, hay đổi sang `tenant` kèm lý do. (M6) ràng buộc theo `NAMING_CONVENTION`: `pk_permissions`
  và `ck_permissions_<tên>` cho mọi CHECK; PRIMARY KEY và CHECK không tên trong SQL thô nhận tên mặc định của
  PostgreSQL. (M7) `hasScope("...")` ở trang web (`apps/web/app/approvals/page.tsx:58`, `admin/*`) ngoài (b); hôm nay
  mọi khóa đó cũng được API kiểm, R1.1 chỉ nêu điều hướng. LOW: "mức rủi ro cao" của `runs.reconcile` ở bước 5 không
  là giá trị của `risk` (`elevated` hay `critical`, việc của workflow-engine/08); docstring `auth.py:1-6` sai vì mặc
  định người mới không có membership nào (danh sách rỗng), không phải bị từ chối; bước 6 nói "người vận hành" cho nhân
  viên hỗ trợ của ADR-0024 (Proposed).
- 2026-11-02 (agent): lượt xác nhận của gate, chỉ đọc hai chỗ sửa B1 và B2: không CRITICAL mới. B1 đóng, đo bằng một
  bản quét `ast` dùng một lần theo đúng chữ của (b): nó giải 22 khóa, trong đó `approvals.decide`, `dw.read`,
  `dw.manage`, `platform.roles.read`, `platform.sod_waivers.write`, `crm.records.all.read` mà danh sách nguồn cũ không
  thấy; chỗ không giải được đúng là bốn cửa chuyển tiếp của danh sách; lời gọi `.require(run_context)` của
  `langgraph_runner.py:305` và `single_call.py:49` không có `action`, nên ngoài (b); bản sửa đầu nêu `approval_flow.py`
  ở danh sách, sai vì `holds_stamped_scope` không phải dạng (b) đọc, đã thay bằng bốn chỗ đo được. B2 đóng:
  ba luật cho mỗi khóa đang có đúng một trạng thái hợp lệ với sáu bất thường (khóa được cấp và được kiểm chỉ `active`),
  khóa của cụm khác đăng ký kèm chỗ kiểm là `active`, nên quyền tính động của `tenant_owner` (R2.7) không đổi.
- 2026-11-02 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-02 (agent): resolved.
    - Khác ticket (agent, theo ủy quyền 31/10/2026): `dw_provisioner` không được `GRANT SELECT` trên `platform.permissions` (bước 2 nói ba vai), vì `test_the_provisioner_holds_exactly_what_its_code_runs` (FH13) giữ vai đó đúng bằng những gì code của nó chạy, và không code nào của nó đọc danh mục; đăng nhập đọc quyền dưới `dw_app`. Ghi quyền vẫn bị thu của cả ba vai. Nếu sai thì: thêm `platform.permissions` SELECT vào `PROVISIONER` của `0fdd32a39d87` và `scripts/create_provisioner_role.py` cùng lúc. `support.grant` (code kiểm, không vai trò mẫu nào cấp) ghi `active` vì có chỗ kiểm. Ngoại lệ (c) duy nhất: `platform.admin`, giữ bằng vai `platform_admin` mà cửa phân quyền đọc. Ràng buộc đặt tên theo `NAMING_CONVENTION` (M6). Lý do `scope_kind` của `dw.read`, `dw.manage` ghi trong docstring migration (M5). Test R2.1 có hai membership ở hai tenant (M4), so với `SqlMembershipLookup.find_access`, nguồn của `GET /api/v1/me`.
    - Bốn kiểm (a)-(d) là hàm trên dữ liệu trong chính test, nên ca tổng hợp (tạo cây nguồn tạm) chứng minh mỗi luật đỏ được; ca tích hợp chạy chúng trên danh mục đã migrate và cây nguồn thật: 22 khóa đọc được qua `ast`, 0 chỗ không giải được ngoài bốn cửa chuyển tiếp (khớp theo tệp và hàm bao, không theo dòng).
    - Test: `test_permission_catalogue.py` 9 ca; `test_identity_provisioning.py` thêm một ca; `test_privileges.py` thêm một ca; `test_admin_console.py` thêm một ca (R1.4, 403); `test_support_access.py` thêm năm ca (R1.5); `test_rls_coverage.py`, `test_offboarding_coverage.py` xanh. Snapshot OpenAPI và kiểu TS sinh lại; `listPermissions()` trong `@dw/api-client`.
    - `mutations/01.yaml` 8 đột biến, chưa chạy. Độ trễ của bootstrap (hai câu SQL mỗi membership, M3) đo ở lượt cuối.
    - `reviewing-feature-security` (đọc): đăng nhập nay ra đúng tập quyền của AccessContext (một hàm `effective_scopes`); danh mục toàn cục chỉ migration ghi; route chỉ đọc, kiểm `platform.roles.read` ở service; hỗ trợ không giữ được quyền Studio, object, field, kết nối, tích hợp của tenant.
