# Quyền trên bản ghi: người phụ trách, mặc định truy cập, quản lý, chia sẻ

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Ai thấy bản ghi nào được quyết định trong PostgreSQL bằng RLS trên một sổ tầm truy cập, không ở ứng dụng, nên API,
agent, quy trình, xuất, lane và dịch vụ viết bằng ngôn ngữ khác nhận cùng một câu trả lời (ADR-0105 (Accepted),
ADR-0103 (Accepted)). Chủ thể là người dùng hay tài khoản dịch vụ; agent và quy trình chỉ là giới hạn dữ liệu. W1 làm
lớp (a) của D3: người phụ trách và workspace sở hữu trên mọi bản ghi, mặc định truy cập theo object, mức truy cập Của
tôi, Workspace của tôi và Toàn công ty, giao một lead của Marketing cho Sales, ngữ cảnh actor ở mọi cửa. Ba lớp còn lại
(quản lý thấy bản ghi của cấp dưới, chia sẻ thủ công có hạn, quy tắc chia sẻ) là dòng W2 ở Ngoài phạm vi; bảo mật
trường là spec `field-security`.

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- `bind_tenant` gắn `app.tenant_id`, `app.workspace_id`, `app.user_id` cho giao dịch đang mở bằng
  `set_config(..., true)`, chuỗi rỗng khi thiếu
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/tenant_session.py:47-65`); không cửa nào gắn loại
  actor hay giới hạn dữ liệu. Thiếu: `app.actor_kind`, `app.boundary_id` và cửa sổ tầm.
- Policy tenant hiện có đọc setting ngay trong biểu thức, không ở dạng InitPlan, và mọi policy là PERMISSIVE
  (`db/migrations/sql/0001_platform_baseline.sql:770`). Ràng buộc: foundations-hardening ticket 03 đo dạng InitPlan;
  policy bản ghi dùng dạng đó.
- Chỉ lane offboarding đặt `app.workspace_scope = 'tenant'`
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:51-54`), đúng quy tắc của CLAUDE.md
  mục Tenancy and authorization. Ràng buộc: theo DO-13.1 (Đạt, 23/10/2026), chỉ helper `tenant_wide_scope` đặt setting
  này, cho lane có tên trong danh sách đăng ký đóng băng ở composition root (W1: offboarding); CLAUDE.md mục Tenancy ghi
  luật đó.
- Offboarding tìm bảng để xuất theo policy tên `tenant_isolation_%` và quyền SELECT của `dw_app`
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:68-86`). Ràng buộc: bảng bản ghi
  giữ tên policy đó và SELECT của `dw_app` ở bảng cha, không ở partition, để mỗi dòng được xuất một lần.
- RLS thu hẹp theo người nhận làm lane offboarding không thấy thông báo của người khác
  (`db/migrations/versions/855ae928c3fa_platform_in_app_notifications.py:44-47`). Ràng buộc: mọi policy thu hẹp theo
  chủ thể phải đọc phạm vi toàn tenant.
- Partition tạo lúc chạy nhận policy chỉ theo tenant và giữ quyền mặc định của `dw_app`; chỉ partition của
  `audit_events` bị thu quyền (`db/migrations/sql/0013_partition_maintenance.sql:63-83`). Ràng buộc: partition của bảng
  bản ghi không được tạo qua hàm này nguyên trạng.
- `test_rls_coverage.py` tìm bảng tenant từ catalog kể cả partition
  (`packages/python/dw_platform/tests/integration/test_rls_coverage.py:44-58`), chỉ tin ba setting
  (`packages/python/dw_platform/tests/integration/test_rls_coverage.py:95-99`) và chỉ nhận `app.workspace_scope` đứng
  cạnh một mệnh đề tenant thuần (`packages/python/dw_platform/tests/integration/test_rls_coverage.py:395-411`).
  Ràng buộc: test đọc văn bản policy nên không thấy thu hẹp nằm trong một hàm (failure-modes #0).
- Cùng test chỉ dò cột `tenant_id`, không kiểm cột `workspace_id`
  (`packages/python/dw_platform/tests/integration/test_rls_coverage.py:44-59`). Ràng buộc: `studio.access_epochs`,
  `studio.principal_scopes`, `studio.actor_boundaries`, `studio.actor_boundary_objects` và
  `studio.actor_boundary_fields` không có `workspace_id`; chúng vào lớp bảng toàn tenant mà CLAUDE.md mục Tenancy ghi
  (DO-01, ADR-0100 (Accepted)), mỗi bảng một dòng lý do trong danh sách của test đó.
- `tenants.record_visibility` mặc định `'open'`, không CHECK (`db/migrations/sql/0001_platform_baseline.sql:409`);
  `visible_owners` đi theo `AccessContext`
  (`packages/python/dw_platform/src/dw_platform/application/access_context.py:43-50`), vào lượt chạy
  (`apps/api/src/dw_api/bootstrap/container.py:223-226`) và được phát lại khi tiếp tục
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:289-294`); không đường nào lọc bản ghi theo
  chúng. Ràng buộc: W1 không đọc chúng; gỡ ở W2.
- Vai trò `platform_admin` qua mọi kiểm quyền
  (`packages/python/dw_platform/src/dw_platform/application/authorization.py:68-71`). Ràng buộc: không vai trò nào
  thay quyền trên bản ghi (ADR-0105 (Accepted) mục 2).
- Cổng công cụ chỉ so tập scope (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:160-174`) và
  `RunContext` không mang giới hạn dữ liệu (`packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:106-128`).
  Thiếu: giới hạn dữ liệu của agent và quy trình.
- Kết quả tra thành viên dựng `AccessContext` được cache 30 giây
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/caching_lookup.py:27`). Ràng buộc: tầm trên bản
  ghi không đi qua cache này, nếu không một thu hồi trễ tới 30 giây.
- Hàm SECURITY DEFINER theo một quy tắc viết sẵn: `search_path` cố định, thu EXECUTE khỏi PUBLIC, không chuỗi nào của
  người gọi đặt tên bảng (`db/migrations/sql/0012_partition_maintenance.sql:45-48`). Ràng buộc:
  `studio.ensure_principal_scope()` và `studio.assign_record` theo quy tắc này.
- Số đo lúc lập kế hoạch dừng ở 2 triệu bản ghi trên một laptop, chưa đo đường ghi dưới WITH CHECK hay đồng thời
  (`docs/adr/0105-record-reach-is-decided-by-postgresql.md:31-33`). Chưa rõ: hình dạng policy có giữ ở quy mô D12
  không; ticket 01 đo.

## Mục tiêu

### R1 — Người phụ trách và workspace sở hữu trên mọi bản ghi

Mọi đường đọc biết ai phụ trách một bản ghi và workspace nào sở hữu nó (YC17).

- R1.1 [Bỏ] 23/10/2026: cột `owner_id`, `owner_kind`, `workspace_id`, `object_id` và NOT NULL có một người tạo là
  custom-objects/02 (`custom-objects:R4.1`); spec này chỉ đọc chúng.
- R1.2 NẾU một lần ghi đặt người phụ trách không phải thành viên công ty đang hoạt động của tenant đang gắn, THÌ
  `studio.records` PHẢI từ chối với SQLSTATE 23514 `ck_records_owner_in_tenant` và không ghi gì.
- R1.3 NẾU kết nối `dw_app` cập nhật thẳng `owner_id`, `owner_kind`, `workspace_id` hay `object_id`, THÌ PostgreSQL
  PHẢI từ chối với `permission denied` và không đổi dòng nào.

### R2 — Mặc định truy cập theo object

Quản trị viên công ty mở một object cho cả công ty xem hoặc sửa mà không phải cấp thêm vai trò (YC17); mặc định truy
cập chỉ đổi qua phiên bản `dw.object/v1` của custom-objects (`custom-objects:R1.4`).

- R2.1 [Bỏ] 23/10/2026: cột `default_access` và `ck_object_defs_default_access` có một người tạo là custom-objects/02
  (`custom-objects:R1.4`); spec này chỉ đọc và gắn trigger tăng epoch.
- R2.2 TRONG KHI object ở `public_read`, policy đọc của `studio.records` PHẢI cho người giữ quyền `read` object ở bất
  kỳ mức truy cập nào đọc mọi bản ghi của object đó trong tenant.
- R2.3 TRONG KHI object ở `public_read_write`, policy sửa của `studio.records` PHẢI cho người giữ quyền `update`
  object ở bất kỳ mức truy cập nào sửa mọi bản ghi của object đó trong tenant.
- R2.4 NẾU người dùng chỉ với tới một bản ghi qua mặc định truy cập, THÌ policy xóa của `studio.records` PHẢI không
  xóa bản ghi đó (0 dòng bị ảnh hưởng).
- R2.5 [Bỏ] 23/10/2026: route `PATCH /api/v1/studio/objects/{api_name}/access` bỏ; mặc định truy cập chỉ đổi qua
  phát hành `dw.object/v1`, mở cần người thứ hai, siết một người (`custom-objects:R1.2`, `custom-objects:R1.7`).
- R2.6 [Bỏ] 23/10/2026: cùng lý do với R2.5; khóa `studio.sharing.manage` không có người đọc ở W1 nên không đăng ký.

### R3 — Mức truy cập Của tôi, Workspace của tôi, Toàn công ty

Người dùng đọc, sửa và xóa đúng những bản ghi mà các lần gán vai trò của mình cho phép, cộng dồn trong tenant (YC12,
YC18).

- R3.1 ĐỐI VỚI một lần gán vai trò cho quyền `read`, `update` hay `delete` của object ở mức Của tôi, policy cùng lệnh
  của `studio.records` PHẢI cho tới đúng các bản ghi của object đó mà người được gán là người phụ trách.
- R3.2 ĐỐI VỚI cùng các quyền ở mức Workspace của tôi, policy cùng lệnh của `studio.records` PHẢI cho tới đúng các bản
  ghi của object đó có workspace sở hữu là workspace được gán vai trò.
- R3.3 ĐỐI VỚI cùng các quyền ở mức Toàn công ty, policy cùng lệnh của `studio.records` PHẢI cho tới mọi bản ghi của
  object đó trong tenant.
- R3.4 KHI một người giữ từ hai lần gán vai trò trở lên trong tenant, policy của `studio.records` PHẢI cho họ hợp tầm
  của mọi lần gán, như nhau ở mọi workspace đang làm việc.
- R3.5 NẾU một lần tạo đặt workspace sở hữu hay người phụ trách ngoài tầm `create` của người gọi, THÌ policy thêm của
  `studio.records` PHẢI từ chối với SQLSTATE 42501 và không ghi gì.

### R4 — PostgreSQL quyết định ở một chỗ cho mọi đường

Mọi đường đọc và ghi nhận cùng một câu trả lời về bản ghi, và không vai trò nào vượt qua (YC3, YC18).

- R4.1 Bảng `studio.records` và mỗi partition của nó PHẢI mang đúng một policy RESTRICTIVE
  `tenant_isolation_records` và bốn policy PERMISSIVE `record_access_records_select`, `_insert`, `_update`,
  `_delete` theo mẫu của ADR-0105 (Accepted) mục 1, và không policy nào khác.
- R4.2 NẾU kết nối `dw_app` gắn tenant A đọc hay ghi bản ghi của tenant B, THÌ `studio.records` PHẢI trả 0 dòng khi
  đọc và lỗi WITH CHECK khi ghi, không đổi dòng nào.
- R4.3 NẾU kết nối `dw_app` đọc hay ghi một partition của bảng bản ghi theo tên partition, THÌ PostgreSQL PHẢI từ
  chối với `permission denied`.
- R4.4 NẾU chủ thể của giao dịch chỉ có Quyền vượt của nền tảng (`platform_admin`) hay là `support_staff`
  (ADR-0024 (Proposed)), không có lần gán vai trò nào trên object, THÌ policy của `studio.records` PHẢI cho 0 bản ghi.
- R4.5 `dw_provisioner` PHẢI không giữ quyền nào trên `studio.records`, `studio.principal_scopes` và
  `studio.access_epochs`.
- R4.6 NẾU kết nối không gắn `app.tenant_id`, THÌ `studio.records` PHẢI trả 0 dòng.

### R5 — Sổ tầm truy cập và thu hồi từ câu lệnh kế tiếp

Một thay đổi quyền có hiệu lực ở câu lệnh đầu tiên sau commit, kể cả khi nó đến từ lane nền hay nhập dữ liệu (YC14).

- R5.1 Sổ tầm của mỗi chủ thể PHẢI do đúng một hàm SQL tính từ `platform.effective_grants` (ADR-0104 (Accepted)
  mục 5) và mặc định truy cập của object, lấy tenant và chủ thể từ setting của giao dịch, không từ tham số.
- R5.2 KHI một giao dịch commit việc gỡ hay tạm khóa thành viên công ty, gỡ thành viên workspace, gỡ lần gán vai trò,
  hạ mức truy cập trong vai trò hay đổi mặc định truy cập, sổ tầm PHẢI cho tầm mới từ câu lệnh đầu tiên của mọi giao
  dịch bắt đầu sau commit đó.
- R5.3 NẾU dòng sổ tầm của chủ thể thiếu, ở trạng thái `stale` hay mang epoch khác epoch của tenant, THÌ sổ tầm PHẢI
  cho tầm rỗng, không bao giờ tầm cũ.
- R5.4 NẾU một lần tính sổ tầm bắt đầu trước một thu hồi và ghi kết quả sau khi thu hồi commit, THÌ
  `studio.principal_scopes` PHẢI giữ dòng đó ở trạng thái khác `valid`.
- R5.5 NẾU kết nối `dw_app` INSERT, UPDATE hay DELETE `studio.principal_scopes` hay `studio.access_epochs`, THÌ
  PostgreSQL PHẢI từ chối với `permission denied`.
- R5.6 KHI thành viên công ty của một chủ thể bị xóa khỏi tenant, `studio.principal_scopes` PHẢI xóa dòng sổ tầm của
  chủ thể đó trong cùng giao dịch.
- R5.7 NẾU một lần ghi sổ tầm của tenant A nêu một chủ thể không phải thành viên công ty của tenant A, THÌ PostgreSQL
  PHẢI từ chối lần ghi đó và không ghi dòng nào.

### R6 — Ngữ cảnh actor ở mọi cửa; agent và quy trình trong giới hạn dữ liệu

Agent và quy trình đọc, ghi bản ghi bằng quyền của người kích hoạt hay tài khoản dịch vụ chạy dưới danh nghĩa, giao
với giới hạn dữ liệu của phiên bản đã phát hành, đánh giá lại ở từng câu lệnh (YC18, YC19).

- R6.1 NẾU một giao dịch gắn tenant mà không gắn `app.actor_kind`, hay gắn giá trị ngoài `user`, `agent`, `workflow`,
  THÌ policy của `studio.records` PHẢI cho 0 bản ghi khi đọc và từ chối mọi lệnh ghi.
- R6.2 KHI cửa API Studio mở giao dịch cho một yêu cầu đã xác thực, cửa API Studio PHẢI gắn loại actor `user` với
  người gọi làm chủ thể và gọi cửa sổ tầm trước câu lệnh đầu tiên.
- R6.3 KHI runtime mở phiên công cụ cho một lượt chạy agent, phiên công cụ PHẢI gắn loại actor `agent`, chủ thể của
  lượt chạy và `app.boundary_id` của phiên bản agent.
- R6.4 TRONG KHI loại actor là `agent` hay `workflow`, policy của `studio.records` PHẢI chỉ cho tới bản ghi của object
  và lệnh có trong giới hạn dữ liệu, giao với tầm của chủ thể.
- R6.5 NẾU loại actor là `agent` hay `workflow` mà `app.boundary_id` thiếu hay không trỏ tới một giới hạn dữ liệu của
  tenant đang gắn, THÌ policy của `studio.records` PHẢI cho 0 bản ghi.
- R6.6 KHI một lượt chạy tiếp tục sau phê duyệt, policy của `studio.records` PHẢI áp tầm hiện tại của chủ thể ở câu
  lệnh kế tiếp, không áp tầm đóng dấu lúc lượt chạy bắt đầu.
- R6.7 `studio.actor_boundaries` PHẢI giữ đúng một giới hạn dữ liệu cho mỗi phiên bản agent hay quy trình đã phát
  hành, ghi trong giao dịch phát hành.
- R6.8 NẾU một lệnh UPDATE, hay một lệnh DELETE ngoài phạm vi toàn tenant của lane offboarding, chạm giới hạn dữ liệu
  của phiên bản đã phát hành, THÌ `studio.actor_boundaries` PHẢI từ chối với SQLSTATE 23514
  `ck_actor_boundaries_frozen` và không đổi gì.
- R6.9 ĐỐI VỚI lượt chạy quy trình không người kích hoạt, policy của `studio.records` PHẢI áp tầm của tài khoản dịch
  vụ chạy dưới danh nghĩa của phiên bản, giao với giới hạn dữ liệu, như cho một người giữ cùng vai trò.

### R7 — Phạm vi toàn tenant cho offboarding và lane đã đăng ký [Sửa]

Trước đây: chỉ lane offboarding đặt phạm vi toàn tenant (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:51-54`).

- R7.1 TRONG KHI một giao dịch ở phạm vi toàn tenant của tenant đang gắn, policy của `studio.records` PHẢI cho đọc và
  ghi mọi bản ghi của tenant đó và 0 bản ghi của tenant khác.
- R7.2 NẾU một lane không có trong danh sách đăng ký đóng băng ở composition root xin phạm vi toàn tenant, THÌ helper
  phạm vi toàn tenant PHẢI từ chối trước khi đặt `app.workspace_scope`.
- R7.3 KHI lane offboarding xuất một tenant, lane offboarding PHẢI xuất mỗi bản ghi của tenant đúng một lần, kể cả bản
  ghi của người đã rời tenant.

### R8 — Giao người phụ trách và đổi workspace sở hữu

Trưởng kinh doanh giao một lead của Marketing cho một nhân viên Sales và chọn có chuyển workspace sở hữu sang Sales
hay không (YC50, YC82).

- R8.1 KHI người có tầm `assign` trên bản ghi gửi `POST /api/v1/studio/objects/{api_name}/records/{record_id}/assign`
  với người nhận đủ điều kiện, API giao PHẢI đổi người phụ trách và tăng phiên bản bản ghi trong một giao dịch rồi trả
  200, kể cả khi người giao không còn thấy bản ghi sau đó.
- R8.2 KHI thân yêu cầu không có `workspace_id`, API giao PHẢI giữ nguyên workspace sở hữu của bản ghi.
- R8.3 KHI thân yêu cầu có `workspace_id` nằm trong tầm `create` của người giao trên object và người nhận là thành
  viên workspace đó, API giao PHẢI đặt workspace sở hữu mới trong cùng giao dịch.
- R8.4 NẾU người gọi thấy bản ghi mà không có tầm `assign` trên nó, THÌ API giao PHẢI trả 403 `assign_not_permitted`
  và không đổi gì.
- R8.5 NẾU người nhận không phải thành viên công ty đang hoạt động có quyền `read` object, hay `workspace_id` ngoài
  tầm `create` của người giao, hay người nhận không là thành viên workspace đó, THÌ API giao PHẢI trả 403
  `assign_target_out_of_reach` và không đổi gì.
- R8.6 NẾU bản ghi không thấy được với người gọi, hay người nhận hoặc bản ghi thuộc tenant khác, THÌ API giao PHẢI trả
  404 như với id không tồn tại và không đổi gì.
- R8.7 KHI một lần giao commit, API giao PHẢI ghi trong cùng giao dịch đúng một sự kiện audit `studio.record.assigned`
  chỉ mang id object, bản ghi, người phụ trách và workspace sở hữu trước và sau.
- R8.8 KHI một lần giao commit, API giao PHẢI ghi trong cùng giao dịch đúng một sự kiện outbox `studio.record.assigned`
  chỉ mang id.
- R8.9 KHI người phụ trách cũ chỉ với tới bản ghi qua mức Của tôi, policy của `studio.records` PHẢI cho người đó 0
  dòng của bản ghi đó từ câu lệnh đầu tiên sau commit của lần giao.
- R8.10 KHI cùng người gọi gửi lại cùng `Idempotency-Key`, API giao PHẢI trả kết quả lần đầu và không giao lần hai.

### R9 — Ngân sách thời gian ở quy mô D12

Danh sách và bản ghi giữ ngân sách thời gian với mọi hồ sơ quyền ở quy mô D12: 10 triệu bản ghi mỗi object, 50 triệu
mỗi tenant, 5.000 người, 200 workspace, cây workspace sâu 6 (YC20). Mỗi dòng là p95 của 20 lần, đo phía máy chủ trên
máy tham chiếu mà YC20 định nghĩa (host chính sau D14), với mọi hồ sơ quyền của ticket 01.

| Mã   | Thao tác dưới policy bản ghi                                   | p95 tối đa |
| ---- | -------------------------------------------------------------- | ---------- |
| R9.1 | Trang đầu 50 dòng, có và không có bộ lọc trên trường lọc được  | 50 ms      |
| R9.2 | Tra một bản ghi theo id                                        | 5 ms       |
| R9.3 | Trang kế tiếp theo keyset                                      | 50 ms      |
| R9.4 | Đếm có trần 1.001                                              | 300 ms     |
| R9.5 | Tạo một bản ghi, hay sửa một trường của nó                     | 10 ms      |
| R9.6 | Giao một bản ghi                                               | 20 ms      |
| R9.7 | Tính sổ tầm cho một chủ thể                                    | 50 ms      |
| R9.8 | Cửa sổ tầm khi dòng sổ tầm còn hiệu lực                        | 1 ms       |
| R9.9 | Tính lại sổ tầm của 5.000 chủ thể sau một lần tăng epoch, tổng | 120 s      |

- R9.10 Ở 10^5 bản ghi trong CI, kế hoạch của mọi truy vấn trang dưới policy bản ghi PHẢI không có Seq Scan trên
  `studio.records` hay partition của nó, với mọi hồ sơ quyền của ticket 01.

## Hành vi giữ nguyên

- G1 KHI lane offboarding xuất và xóa một tenant, lane offboarding PHẢI TIẾP TỤC chỉ xuất và xóa dòng của tenant đó,
  để nguyên dòng của tenant khác (test: `test_export_rows_returns_only_this_tenants_data`,
  `test_purge_rows_respects_fk_order_and_leaves_the_other_tenant_alone`).

## Trong phạm vi

- Policy `tenant_isolation_records` và bốn policy `record_access_records_<lệnh>` trên `studio.records` và mọi
  partition, dựng từ một module mẫu; quy tắc mới trong `test_rls_coverage.py`.
- Cột sinh `access_key`, index tầm, trigger `ck_records_owner_in_tenant` và quyền theo cột trên `studio.records`.
- Trigger AFTER UPDATE OF `default_access` trên `studio.object_defs` tăng epoch; cột và CHECK của nó thuộc custom-objects.
- Sổ tầm: `studio.access_epochs`, `studio.principal_scopes`, `studio.compute_principal_scope()`,
  `studio.ensure_principal_scope()`, các hàm `studio.acl_*` và trigger vô hiệu hóa.
- Setting `app.actor_kind`, `app.boundary_id`; helper gắn ngữ cảnh actor và helper phạm vi toàn tenant trong
  `tenant_session.py`; danh sách lane đăng ký.
- `studio.actor_boundaries`, `studio.actor_boundary_objects`, `studio.actor_boundary_fields` và port
  `ActorBoundaryPort`.
- `studio.assign_record`; route `POST /api/v1/studio/objects/{api_name}/records/{record_id}/assign`; audit và outbox
  `studio.record.assigned`.
- Bộ đo `db/bench/record-access/` với `make bench-record-access`.

## Ngoài phạm vi

| Việc                                                                                    | Vì sao                                                                                                                                      | Chủ                                       |
| --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| Quản lý thấy và sửa bản ghi cấp dưới (phân cấp)                                         | lớp (b) của D3; cần quan hệ quản lý toàn tenant của org-and-principals                                                                      | W2, record-access                         |
| Chia sẻ thủ công một bản ghi, có hạn                                                    | lớp (c); cột `read_grants`, `edit_grants`, `grants_valid_until` đến cùng người ghi và người đọc của chúng                                   | W2, record-access                         |
| Mẫu policy cho bảng con của bản ghi                                                     | lịch sử, liên kết và chia sẻ chưa có ở W1                                                                                                   | W2, record-access                         |
| Bản ghi trong knowledge giữ quyền                                                       | chờ foundations-hardening sửa xóa mềm không theo tenant; ADR-0105 (Accepted) mục 7                                                          | W2, record-access                         |
| Gỡ `record_visibility` và `visible_owners`                                              | khai báo mà không đường nào đọc; gỡ cùng mọi nơi mang chúng                                                                                 | W2, record-access                         |
| Quy tắc chia sẻ theo tiêu chí, có phiên bản; ai thấy bản ghi này và vì sao              | lớp (c), cần CEL của ADR-0114 (Accepted)                                                                                                    | W2, record-access                         |
| Chuyển hàng loạt người phụ trách; lane làm ấm sổ tầm và quét dòng không dùng 30 ngày    | W1 tính lại ở cửa và xóa dòng cùng thành viên công ty; lane chỉ làm ấm                                                                      | W2, record-access                         |
| Biên agent theo phạm vi; hỗ trợ theo một bản ghi; kênh chat đọc bản ghi                 | v2 trong ADR-0105 (Accepted) và ADR-0024 (Proposed)                                                                                         | W3, record-access                         |
| Nhóm làm người phụ trách; mức Của nhóm tôi và Workspace của tôi và cấp dưới             | nhóm và cây workspace đến ở W2 (ADR-0104 (Accepted))                                                                                        | W2, record-access cùng org-and-principals |
| Tab "Quyền truy cập" trong thiết lập object                                             | màn thiết lập object chưa có ở W1; một tab cho mặc định truy cập và quản lý thấy cấp dưới                                                   | W2, record-access                         |
| Hộp thoại "Giao cho" trên trang bản ghi                                                 | trang bản ghi thuộc custom-objects; hộp thoại gọi route giao của spec này                                                                   | custom-objects                            |
| Xoay vòng người nhận và người dự phòng khi giao (YC50)                                  | quy tắc giao là của bước giao; người dự phòng là một điểm gắn `principal` kiểm bằng `platform.effective_grants`, nhóm ở W2 (Q6)             | workflow-nodes                            |
| RA3: chỉ người giữ quyền đổi mặc định truy cập, có audit                                | mặc định truy cập chỉ đổi qua phát hành `dw.object/v1`; quyền phát hành, người thứ hai và audit là kiểm soát của custom-objects (CO3, CO23) | custom-objects                            |
| Đổi kết quả RLS thành 404 và 403 ở API bản ghi; tham chiếu tới bản ghi không thấy       | RecordService là cửa duy nhất của bản ghi (ADR-0107 (Accepted))                                                                             | custom-objects                            |
| Chọn tài khoản dịch vụ cho lượt chạy không người kích hoạt; từ chối phát hành khi thiếu | điểm gắn `principal` của ADR-0110 (Accepted)                                                                                                | workflow-triggers                         |
| Bảo mật trường                                                                          | một hàm ứng dụng (ADR-0106 (Accepted))                                                                                                      | field-security                            |
| Từ chối (deny), quy tắc hạn chế; chia sẻ ra ngoài tenant                                | v1 chỉ cộng dồn, như ADR-0105 (Accepted) mục 2                                                                                              | không làm                                 |

## Dữ liệu

- `studio.records` (custom-objects ticket 02 tạo, kể cả `owner_kind` với CHECK `user`, `team` và NOT NULL,
  `custom-objects:R4.1`): spec này thêm cột sinh `access_key` kiểu `uuid` từ
  `md5(object_id::text || '/' || workspace_id::text)` (hay biến thể `bigint` nếu ticket 01 chọn), index
  `(tenant_id, access_key, created_at DESC, id DESC)` và `(tenant_id, owner_id, object_id, created_at DESC, id DESC)`,
  trigger `ck_records_owner_in_tenant`; `dw_app` không UPDATE `owner_id`, `owner_kind`, `workspace_id`, `object_id` và
  không có quyền nào trên partition (DO-02.2).
- `studio.object_defs.default_access` với `ck_object_defs_default_access` (custom-objects ticket 02 tạo,
  `custom-objects:R1.4`); spec này chỉ đọc nó trong hàm tính sổ tầm và gắn trigger tăng epoch.
- `studio.access_epochs` (`tenant_id` PK, FK `platform.tenants` `ON DELETE CASCADE`, `epoch bigint`,
  `changed_at timestamptz`) và `studio.principal_scopes` (PK `(tenant_id, principal_id)`, FK ghép
  `(tenant_id, principal_id)` tới `platform.tenant_members (tenant_id, user_id)` `ON DELETE CASCADE`, `epoch`,
  `version`, `state` với `ck_principal_scopes_state` (`valid`,
  `stale`), `computed_at`, `workspace_ids` và một `uuid[]` cho mỗi cặp hành động `read`, `create`, `update`, `delete`,
  `assign` và nhánh `own`, `keys`, `tenant`); `dw_app` chỉ SELECT. Hai bảng là dữ liệu dẫn xuất, không có
  `workspace_id` (lớp bảng toàn tenant, DO-01), và offboarding không xóa chúng bằng `dw_app`: `studio.principal_scopes`
  đi theo cascade khi offboarding xóa `platform.tenant_members`; `studio.access_epochs` giữ có chủ ý một dòng đếm mỗi
  tenant, kể cả tenant đã offboard, vì offboarding giữ dòng `platform.tenants` ở `offboarded` (`foundations-hardening:R3.2`)
  và dòng đếm không mang dữ liệu nào của tenant. Mỗi bảng nằm trong `STUDIO_EXCLUSIONS` của test phủ offboarding kèm
  đúng lý do của nó.
- `studio.actor_boundaries` (`kind` `agent` hay `workflow`, `source_id`, `source_version`),
  `studio.actor_boundary_objects` (`can_read`, `can_create`, `can_update`, `can_delete`, `can_assign`),
  `studio.actor_boundary_fields` (`access` là `read` hay `edit`); RLS tenant; trigger `ck_actor_boundaries_frozen`; ba
  bảng thuộc phiên bản đã phát hành, không có `workspace_id` (lớp bảng toàn tenant, DO-01).
- Setting mỗi giao dịch: `app.actor_kind` (`user`, `agent`, `workflow`) và `app.boundary_id`, cạnh `app.tenant_id`,
  `app.user_id`, `app.workspace_scope` đã có.

## API

- `POST /api/v1/studio/objects/{api_name}/records/{record_id}/assign`: `Idempotency-Key`, thân
  `{"owner_id": "...", "workspace_id": "..."}` với `workspace_id` tùy chọn; 200 với `record_id`, `version`,
  `owner_id`, `workspace_id`; 403 `assign_not_permitted`, 403 `assign_target_out_of_reach`, 404.
- Mã RecordService của custom-objects trả từ kết quả RLS, do custom-objects đặt: 404 như id không tồn tại
  (`custom-objects:R5.7`), 403 `permission_denied` khi thiếu quyền đối tượng (`custom-objects:R3.4`), 403 khi đọc được
  mà không sửa hay xóa được (`custom-objects:R5.8`).

## Kiểm soát

| #    | Kiểm soát                                                                              | Yêu cầu           | Test âm                                                                                                                                                                                                                                                                                                                                                                                     |
| ---- | -------------------------------------------------------------------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| RA1  | Người phụ trách thuộc tenant                                                           | R1.2              | INSERT với `owner_id` là người của tenant B, hay thành viên bị tạm khóa → 23514 `ck_records_owner_in_tenant`; gỡ trigger → test đỏ                                                                                                                                                                                                                                                          |
| RA2  | Chỉ hàm định nghĩa đổi người phụ trách và workspace sở hữu                             | R1.3              | `dw_app` UPDATE thẳng `owner_id` hay `workspace_id` → permission denied; cấp lại UPDATE trên cột → test đỏ                                                                                                                                                                                                                                                                                  |
| RA3  | [Bỏ] 23/10/2026: chỉ người giữ `studio.sharing.manage` đổi mặc định truy cập, có audit | R2.5, R2.6        | Không còn route để thử: mặc định truy cập chỉ đổi qua phát hành `dw.object/v1`, kiểm soát ở custom-objects (CO3, CO23)                                                                                                                                                                                                                                                                      |
| RA4  | Mặc định truy cập                                                                      | R2.2, R2.3, R2.4  | object `private`: bản ghi của người khác → 0 dòng; `public_read`: SELECT 1 dòng, UPDATE 0 dòng; `public_read_write`: UPDATE 1 dòng, DELETE 0 dòng                                                                                                                                                                                                                                           |
| RA5  | Mức Của tôi                                                                            | R3.1              | vai trò `read` mức Của tôi: SELECT bản ghi của đồng nghiệp cùng workspace → 0 dòng, bản ghi của mình → 1 dòng                                                                                                                                                                                                                                                                               |
| RA6  | Mức Workspace của tôi và Toàn công ty, hợp các lần gán                                 | R3.2, R3.3, R3.4  | mức Workspace ở Marketing: bản ghi của Sales → 0 dòng; thêm lần gán Toàn công ty → cả hai; đổi workspace đang làm việc → cùng kết quả                                                                                                                                                                                                                                                       |
| RA7  | Tạo trong tầm `create`                                                                 | R3.5              | INSERT với workspace sở hữu ngoài tầm `create` → 42501, 0 dòng mới                                                                                                                                                                                                                                                                                                                          |
| RA8  | Bộ policy cố định, hàm policy kiểm được                                                | R4.1              | thêm một policy PERMISSIVE trên `studio.records` → test catalog đỏ; văn bản lệch mẫu → đỏ; một hàm `studio.acl_*` mất STABLE hay `search_path` cố định → đỏ; bảng thử mang hình sai (thêm PERMISSIVE chỉ theo tenant, `tenant_isolation` thành PERMISSIVE, `studio.acl_*` VOLATILE hay SECURITY DEFINER), dựng rồi lùi → test catalog bắt từng hình                                         |
| RA9  | Cách ly tenant trên bản ghi                                                            | R4.2, R4.6        | `dw_app` gắn tenant A: SELECT theo id bản ghi của B → 0 dòng; INSERT với `tenant_id` của B → lỗi WITH CHECK; không gắn tenant → 0 dòng; bỏ mệnh đề tenant khỏi policy RESTRICTIVE → đỏ                                                                                                                                                                                                      |
| RA10 | Partition không mở đường vòng                                                          | R4.3              | `dw_app` SELECT `studio.records_p0` theo tên → permission denied; cấp lại SELECT trên partition → test đỏ                                                                                                                                                                                                                                                                                   |
| RA11 | Không vai trò nào thay quyền                                                           | R4.4, R4.5        | chủ thể chỉ có `platform_admin` → 0 bản ghi; `support_staff` → 0 bản ghi; `has_table_privilege('dw_provisioner', 'studio.records', 'SELECT')` → false                                                                                                                                                                                                                                       |
| RA12 | Một hàm tính sổ tầm, không lẫn tenant                                                  | R5.1, R5.7        | hai tenant có cấu trúc giống hệt → mảng không lẫn id của nhau; bỏ lọc tenant trong hàm tính → đỏ; test vi sai với oracle trên ≥ 500 tổ chức ngẫu nhiên; `app.tenant_id` A với `app.user_id` của người chỉ là thành viên công ty B gọi `studio.ensure_principal_scope()` → lỗi khóa ngoại ghép, không dòng sổ tầm nào; đổi FK ghép thành FK một cột `principal_id` tới `platform.users` → đỏ |
| RA13 | Thu hồi từ câu lệnh kế tiếp                                                            | R5.2              | mỗi loại thay đổi commit ở giao dịch A → câu lệnh đầu của giao dịch B → 0 dòng; gỡ trigger vô hiệu hóa trên một bảng → test của loại đó và test catalog đỏ                                                                                                                                                                                                                                  |
| RA14 | Sổ tầm thiếu hay cũ thì tầm rỗng                                                       | R5.3              | xóa dòng sổ tầm rồi đọc không qua cửa → 0 dòng; tăng epoch mà không tính lại → 0 dòng                                                                                                                                                                                                                                                                                                       |
| RA15 | Lần tính cũ không ghi đè thu hồi                                                       | R5.4              | hai kết nối: lần tính bắt đầu, thu hồi commit, lần tính ghi → dòng khác `valid`; bỏ compare-and-set → đỏ                                                                                                                                                                                                                                                                                    |
| RA16 | Chỉ hàm định nghĩa ghi sổ tầm                                                          | R5.5              | `dw_app` INSERT hay UPDATE `studio.principal_scopes` → permission denied                                                                                                                                                                                                                                                                                                                    |
| RA17 | Thiếu ngữ cảnh actor thì không thấy gì                                                 | R6.1              | gắn tenant và chủ thể đúng, không gắn `app.actor_kind` → 0 dòng, INSERT bị từ chối; `app.actor_kind = 'admin'` → 0 dòng                                                                                                                                                                                                                                                                     |
| RA18 | Chỉ cửa được phép gắn loại actor                                                       | R6.2, R6.3        | test kiến trúc: module ngoài danh sách gọi helper với `agent` → đỏ; cửa API bỏ gắn `user` → yêu cầu Studio đọc 0 bản ghi                                                                                                                                                                                                                                                                    |
| RA19 | Agent và quy trình trong giới hạn dữ liệu, tầm sống                                    | R6.4, R6.5, R6.6  | giới hạn chỉ có `mkt_lead` → object khác 0 dòng dù chủ thể thấy; `agent` thiếu `app.boundary_id` → 0 dòng; chủ thể mất quyền trước khi lượt chạy tiếp tục → 0 dòng; gỡ nhánh giới hạn → đỏ                                                                                                                                                                                                  |
| RA20 | Giới hạn dữ liệu bất biến                                                              | R6.8              | UPDATE `studio.actor_boundary_objects` của phiên bản đã phát hành → 23514 `ck_actor_boundaries_frozen`; DELETE ngoài phạm vi toàn tenant → 23514                                                                                                                                                                                                                                            |
| RA21 | Lượt chạy không người kích hoạt dùng tầm của tài khoản dịch vụ                         | R6.9              | tài khoản dịch vụ chỉ có `read` mức Của tôi: lượt chạy thấy 0 bản ghi của người phát hành; gắn người phát hành làm chủ thể → test đỏ                                                                                                                                                                                                                                                        |
| RA22 | Phạm vi toàn tenant chỉ qua một helper                                                 | R7.1, R7.2        | thêm `set_config('app.workspace_scope', ...)` ngoài helper → test quét mã đỏ; lane ngoài danh sách → lỗi, setting không đổi; một dòng danh sách thiếu lý do hay thiếu ghi lane có đọc bảng riêng tư theo chủ không → test đỏ; phạm vi toàn tenant đọc 0 bản ghi của tenant khác                                                                                                             |
| RA23 | Offboarding xuất mỗi bản ghi một lần                                                   | R7.3, G1          | tenant có bản ghi của ba người phụ trách trên partition hash → bản xuất đủ, mỗi bản ghi đúng một lần; sau purge còn 0; tenant khác không đổi                                                                                                                                                                                                                                                |
| RA24 | Giao chỉ trong tầm                                                                     | R8.4, R8.5, R8.6  | không có tầm `assign`, kể cả khi chỉ với tới qua `public_read_write` → 403 `assign_not_permitted`; người nhận không đọc được object → 403; người nhận của tenant khác → 404; 0 dòng đổi                                                                                                                                                                                                     |
| RA25 | Giao có audit và outbox cùng giao dịch, chống lặp                                      | R8.7, R8.8, R8.10 | lỗi sau khi ghi audit → giao dịch lùi, 0 audit, 0 outbox; gửi lại cùng `Idempotency-Key` → một audit, một outbox                                                                                                                                                                                                                                                                            |
| RA26 | Người phụ trách cũ mất quyền theo Của tôi; giao không lùi vì đọc lại                   | R8.1, R8.9        | giao xong, người phụ trách cũ chỉ có mức Của tôi SELECT → 0 dòng; người giao mất quyền thấy sau lần giao → API vẫn 200                                                                                                                                                                                                                                                                      |

## Tiêu chí xong

- Mọi tiêu chí R và G có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát, ghi ở Comments của ticket cài nó.
- `make ci test-integration` xanh; `make bench-record-access` đạt mọi dòng R9 hay ghi phương án đã đo đạt ngưỡng.
- ADR-0105 (Accepted) ghi số đo của ticket 01; test catalog giữ hình policy thứ hai và người được đặt
  `app.workspace_scope` mà CLAUDE.md mục Tenancy ghi (DO-13.1, DO-13.2).

## Phụ thuộc

- tenant-rbac ticket 04: khóa `obj.<api_name>.<action>` có mức truy cập qua `platform.effective_grants`
  (ADR-0104 (Accepted) mục 4 và 5); các bảng mang trigger của `platform.bump_access_version()` (mục 7) là danh sách
  bảng đầu vào mà trigger sổ tầm theo.
- org-and-principals ticket 02 (`platform.tenant_members` có trạng thái) và ticket 03 (tài khoản dịch vụ có thành
  viên và vai trò như người, ADR-0103 (Accepted) mục 2).
- custom-objects ticket 02 (`studio.object_defs` với `default_access` và `ck_object_defs_default_access`,
  `studio.records` phân vùng hash theo tenant với cột hệ thống `owner_id`, `owner_kind`, `workspace_id`, `object_id`
  NOT NULL; `custom-objects:R1.4`, `custom-objects:R4.1`); RecordService của ticket 03 của họ trả các mã ở mục API.
- foundations-hardening ticket 03 (dạng InitPlan, quyền thừa của `dw_app`) và ticket 07 (offboarding đọc theo lô; ticket
  03 ở đây chờ nó để `offboarding.py` có một thứ tự sửa); studio-skeleton (schema `studio`, USAGE và quyền mặc định chỉ
  cho `dw_app`, test phủ offboarding đọc `STUDIO_EXCLUSIONS`).
- agent-builder ticket 03 dùng cửa gắn actor cho agent Studio; workflow-engine gắn `workflow` qua cùng helper ở mỗi
  bước; móc phát hành của loại `agent` (agent-builder) và của loại `workflow` (workflow-engine), mà agent-lifecycle gọi
  trong giao dịch phát hành (ADR-0109 (Accepted) quyết 1), ghi giới hạn dữ liệu qua `ActorBoundaryPort`; field-security
  đọc `studio.actor_boundary_fields`.
- app-standards: problem+json và `Idempotency-Key` gắn người gọi cho route giao (ticket 05 chờ app-standards/01, /02).
- Kiểm lại khi: `platform.effective_grants` đổi hình → ticket 02 tới 05; custom-objects đổi số partition (đường lui
  modulus 4, `custom-objects:R9.5`) → ticket 01, 03; số đo của ticket 01 trượt ngưỡng R9 → mẫu policy của ticket 03 và
  ADR-0105 (Accepted); foundations-hardening/03 rút `foundations-hardening:R5.3` (dạng InitPlan) → ticket 02, 03.

## Câu hỏi còn mở

## Quyết định

- 22/10/2026 (người yêu cầu): D1: workspace là đơn vị sở hữu dữ liệu, vai trò cấp quyền kèm mức truy cập, Marketing
  với tới Sales bằng quyền, không bằng bản sao.
- 22/10/2026 (người yêu cầu): D3: quyền trên bản ghi ở v1 cần đủ bốn lớp; W1 làm lớp (a), quản lý và hai kiểu chia
  sẻ là dòng W2, bảo mật trường là spec `field-security`.
- 23/10/2026 (người yêu cầu): D12: 10 triệu bản ghi mỗi object, 50 triệu mỗi tenant, 5.000 người, 200 workspace, cây
  sâu 6, bản ghi phân vùng hash theo tenant; trả lời DO-14 và đặt cỡ ticket 01. Sửa: R9.
- 23/10/2026 (agent, tạm): theo khuyến nghị (a) của DO-11, mặc định công khai là toàn tenant, lần giao giữ workspace
  sở hữu trừ khi người giao chọn khác, quan hệ quản lý bắc cầu cho đọc và sửa, chia sẻ tay sống qua lần đổi người
  phụ trách (hai ý sau ở W2). Sửa: R2.2, R2.3, R8.2, R8.3. Nếu sai thì: nhánh Toàn công ty của mặc định thêm điều
  kiện cây workspace sở hữu, và lần giao luôn chuyển workspace thì R8.2 đổi.
- 23/10/2026 (agent, tạm): máy tham chiếu của YC20 là hình dạng host hiện tại, 2 vCPU, 8 GB RAM, SSD, PostgreSQL 16.
  Sửa: R9. Nếu sai thì: ticket 01 đo lại trên host 4 vCPU, 16 GB của D14 với cùng ngưỡng.
- 23/10/2026 (agent, tạm): cột `read_grants`, `edit_grants`, `grants_valid_until` và nhánh chia sẻ của policy đến ở
  W2 cùng người ghi và người đọc của chúng (failure-modes #1); ticket 01 vẫn đo đủ sáu nhánh để mẫu policy không đổi
  hình. Nếu sai thì: ticket 03 thêm ba cột và một nhánh đọc mảng rỗng.
- 23/10/2026 (agent, tạm): `owner_kind = 'team'` bị trigger người phụ trách từ chối cho tới khi nhóm có ở W2, vì W1
  chỉ có mức `own`, `workspace`, `tenant` (ADR-0104 (Accepted)). Nếu sai thì: ticket 03 nhận nhóm của
  org-and-principals và thêm nhánh `team`.
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: YC20 nói 10 triệu bản ghi mỗi tenant, D12 nói 10 triệu mỗi object và 50
  triệu mỗi tenant; theo D12.
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: glossary Studio ghi lệnh giao là `:assign`, ADR-0108 (Accepted) mục 3
  nói phương thức tùy biến là sub-resource `POST`; theo ADR-0108 (Accepted).
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: ADR-0105 (Accepted) mục 2 nói `ck_objects_default_access`,
  ADR-0107 (Accepted) mục 1 đặt tên bảng `studio.object_defs` và `NAMING_CONVENTION` sinh
  `ck_object_defs_default_access`; theo quy ước tên của CLAUDE.md "Data model rules".
- 23/10/2026 (Đạt): DO-13.1 (a): chỉ `tenant_wide_scope()` trong `tenant_session.py` đặt `app.workspace_scope`, cho lane
  có tên trong danh sách đóng băng ở composition root của worker (W1: offboarding), audit là `system:<lane>`; mỗi dòng
  danh sách có lý do và nêu lane có cần đọc bảng riêng tư theo chủ không, vì lane trong danh sách thấy cả các bảng đó
  (ADR-0105 (Accepted) mục 5); test quét mã chặn mọi chỗ đặt khác. Hỏi: Q1. Sửa: Hiện trạng, R7.2, RA22, ticket 03.
- 23/10/2026 (Đạt): DO-13.2 (a): bảng bản ghi mang một policy RESTRICTIVE theo tenant cộng bốn PERMISSIVE
  `record_access_*` dựng từ một module mẫu, hình thứ hai mà CLAUDE.md mục Tenancy ghi; test so đúng tập policy, bắt bảng
  thử mang hình sai, kiểm hàm qua `pg_depend` và chạy dưới `dw_app` cùng test vi sai với oracle; mẫu chỉ chốt sau số
  đo của ticket 01. Hỏi: Q1. Sửa: RA8, Tiêu chí xong, ticket 03.
- 23/10/2026 (Đạt): DO-13.3 (a): dịch vụ viết bằng ngôn ngữ khác chỉ đọc giá trị bản ghi Studio qua API của nền tảng;
  nhân viên hỗ trợ đọc 0 bản ghi Studio ở v1 (R4.4 giữ nguyên). Hỏi: Q1.
- 23/10/2026 (Đạt): DO-12 (a): lượt chạy không người kích hoạt chạy dưới tài khoản dịch vụ gắn theo phiên bản qua điểm
  gắn `principal` đã duyệt, không rộng hơn người đề xuất; chưa gắn thì không phát hành (`binding_unset`); tầm sống giao
  giới hạn dữ liệu ở mỗi câu lệnh. Hỏi: Q2. Sửa: R6.9, ticket 04.
- 23/10/2026 (Đạt): `A:custom-objects:R1.4~record-access:R2.5` (a): `default_access` chỉ ghi qua tài liệu
  `dw.object/v1`; route `PATCH .../access` bỏ; custom-objects/02 là người tạo duy nhất cột và
  `ck_object_defs_default_access`, spec này chỉ đọc và gắn trigger tăng epoch; khóa `studio.sharing.manage` không đăng ký
  vì không có người đọc ở W1. Sửa: R2.1, R2.5, R2.6, RA3, Trong phạm vi, Ngoài phạm vi, Dữ liệu, API, ticket 03.
- 23/10/2026 (người đặt yêu cầu và Đạt): Phạm vi D11: đổi `default_access` là thay đổi cấu hình cần người thứ hai khi
  nới, một người cộng audit khi chỉ siết, qua phát hành `dw.object/v1` (`custom-objects:R1.2`, `custom-objects:R1.7`).
  Hỏi: Q3.
- 23/10/2026 (Đạt): DO-11 (a): xác nhận quyết tạm DO-11 cả bốn ý; R2.2, R2.3, R8.2, R8.3 giữ nguyên ở W1, cấp trên bắc
  cầu và chia sẻ sống qua đổi người phụ trách vào W2.
- 23/10/2026 (Đạt): Q6 (a): người dự phòng khi giao là một điểm gắn `principal` trong bộ giá trị gắn hai người duyệt,
  kiểm bằng `platform.effective_grants` như mọi ứng viên, không hợp lệ thì bước đi Nhánh ra lỗi; nhóm ở W2; chủ của quy
  tắc giao là workflow-nodes. Sửa: Ngoài phạm vi.
- 23/10/2026 (Đạt): DO-01 (a) và `E:CLAUDE.md#tenancy-and-authorization~tenant-rbac:platform.tenant_roles` (a):
  `studio.access_epochs`, `studio.principal_scopes` và ba bảng giới hạn dữ liệu vào lớp bảng toàn tenant, mỗi bảng một
  dòng lý do trong danh sách của `test_rls_coverage.py`. Sửa: Hiện trạng, Dữ liệu, ticket 02, 04.
- 23/10/2026 (agent, tạm): `owner_kind` có một người tạo là custom-objects/02 với CHECK `user`, `team`, không default;
  ticket 03 ở đây chỉ thêm trigger `ck_records_owner_in_tenant`, `access_key`, index và quyền cột
  (`A:custom-objects:R4.1~record-access:R1.1`, cùng nguyên tắc một người tạo cột của quyết định về `default_access`). Sửa:
  R1.1, Trong phạm vi, Dữ liệu, ticket 03. Nếu sai thì: ticket 03 thêm lại cột và custom-objects/02 bỏ nó.
- 23/10/2026 (agent, tạm): mục API trích mã RecordService từ custom-objects (`permission_denied`, 404 chung, 403 của
  R5.8) thay vì tự đặt; `unknown_reference` bỏ khỏi W1 vì tham chiếu bản ghi ở W2 (`B:custom-objects:R3.4~record-access:spec`).
  Sửa: API. Nếu sai thì: custom-objects đặt mã riêng và mục API trích lại.
- 23/10/2026 (agent, tạm): `studio.access_epochs`, `studio.principal_scopes` vào `STUDIO_EXCLUSIONS` của test phủ
  offboarding với lý do "dữ liệu dẫn xuất, xóa theo cascade" (`B:record-access:R5.5~studio-skeleton:R4.1`). Sửa: Dữ liệu,
  ticket 02. Nếu sai thì: lane offboarding có một hàm SECURITY DEFINER xóa hai bảng.
- 23/10/2026 (agent, tạm): dạng InitPlan của policy bản ghi đi theo ADR-0105 (Accepted) mục 1; foundations-hardening/03
  rút `foundations-hardening:R5.3` thì kiểm lại ticket 02, 03 (`F:custom-objects:spec~foundations-hardening:R5.3`). Sửa:
  Phụ thuộc.
- 23/10/2026 (agent, tạm): ticket 05 chờ app-standards/01, /02 vì route giao dùng problem+json và `Idempotency-Key` gắn
  người gọi (`I:app-standards/02~tenant-rbac/03`). Sửa: Phụ thuộc, ticket 05. Nếu sai thì: bỏ cạnh.
- 24/10/2026 (Đạt): sửa câu audit của dòng DO-13.1 ngày 23/10/2026: lane trong danh sách phạm vi toàn tenant chạy việc
  của chính nó thì audit `system:<lane>`; lane thi hành quyết định đã ghi của một người, như lần purge của offboarding,
  audit đứng tên người vận hành đã yêu cầu offboarding và ghi `details.lane` là `offboarding` (CLAUDE.md, Agent and tool
  rules; ADR-0011 (Accepted)); ADR-0105 (Accepted) mục 5 sửa cùng (`E:CLAUDE.md#agent-and-tool-rules~record-access:DO-13`).
  RA22 và ticket 03 không đổi. Sửa: Quyết định (dòng DO-13.1).
- 24/10/2026 (Đạt): máy tham chiếu có một chủ là YC20 của requirements.md, theo D14 (host chính sau khi nâng lên ít nhất 4
  vCPU, 16 GB); R9 và ticket 01 trích YC20, bỏ quyết tạm 2 vCPU, 8 GB ngày 23/10/2026
  (`A:custom-objects:quyết-định~record-access:quyết-định`). Sửa: R9, ticket 01.
- 24/10/2026 (Đạt): lý do loại trừ của `studio.access_epochs` khỏi test phủ offboarding là một dòng đếm mỗi tenant được
  giữ có chủ ý, vì dòng `platform.tenants` của tenant đã offboard còn ở `offboarded` nên không cascade nào xóa nó; bỏ lý do
  "xóa theo cascade" cho bảng này (`B:foundations-hardening:R3.2~record-access:dữ-liệu`). Sửa: Dữ liệu, ticket 02.
- 24/10/2026 (Đạt): ticket 03 chờ foundations-hardening/07, vì cả hai sửa `offboarding.py` (`SqlTenantOffboarding`, đọc
  catalog, `export_rows`) và cần một thứ tự sửa (`C:foundations-hardening/07~record-access/03`). Sửa: Phụ thuộc, ticket 03.
- 24/10/2026 (Đạt): Hiện trạng trích CLAUDE.md theo tên mục thay vì số dòng, vì số dòng đã dời khi CLAUDE.md sửa
  (`G:CLAUDE.md#tenancy-and-authorization~record-access:spec`). Sửa: Hiện trạng.
- 24/10/2026 (agent, tạm): không có dịch vụ phát hành nào: giới hạn dữ liệu của một phiên bản agent hay quy trình ghi qua
  `ActorBoundaryPort` trong móc phát hành của loại `agent` (agent-builder) và của loại `workflow` (workflow-engine), mà
  agent-lifecycle gọi trong giao dịch phát hành, vì mục `ArtifactKindRegistry` của loại mang móc do chủ loại cấp
  (ADR-0109 (Accepted) quyết 1) và `LifecycleService` là bên duy nhất ghi `live` (ADR-0120 (Accepted) quyết 1). Sửa:
  Phụ thuộc, ticket 04. Nếu sai thì: agent-lifecycle gọi `ActorBoundaryPort` sau móc của loại, và Phụ thuộc cùng ticket
  04 nêu agent-lifecycle thay hai móc.
- 24/10/2026 (agent, tạm): mục Dữ liệu nêu khóa ngoại của `studio.principal_scopes` là FK ghép
  `(tenant_id, principal_id)` tới `platform.tenant_members (tenant_id, user_id)`, như bước 1 của ticket 02, vì kiểm khóa
  ngoại không đi qua RLS nên khóa ngoại giữa hai bảng của tenant mang `tenant_id` (CLAUDE.md, Tenancy and
  authorization). Sửa: Dữ liệu. Nếu sai thì: Dữ liệu và ticket 02 đổi theo khóa mà org-and-principals/02 chốt cho
  `platform.tenant_members`.
- 24/10/2026 (agent, tạm): FK ghép `(tenant_id, principal_id)` của `studio.principal_scopes` có ca âm chéo tenant ở R5.7
  dưới kiểm soát RA12: `studio.ensure_principal_scope()` gọi với `app.tenant_id` của A và `app.user_id` của người chỉ là
  thành viên công ty B bị PostgreSQL từ chối, và đổi FK ghép thành FK một cột làm test đỏ, vì test âm cho ghi chéo tenant
  là bắt buộc (CLAUDE.md, Tenancy and authorization) và `dw_app` không ghi bảng này nên chỉ hàm SECURITY DEFINER đi tới
  khóa ngoại đó (failure-modes #3). Sửa: R5.7, RA12, ticket 02. Nếu sai thì: R5.7 rút bằng `[Bỏ]` và ca âm thành một
  dòng của RA16.

## Danh sách ticket

| #   | Ticket                                                                                                                                                       |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 01  | [Đo hình dạng RLS cho quyền trên bản ghi trước khi khóa thiết kế](issues/01-do-hinh-dang-rls-ban-ghi.md)                                                     |
| 02  | [Sổ tầm truy cập trong PostgreSQL: tính, lưu, đọc, vô hiệu hóa đồng bộ](issues/02-so-tam-truy-cap.md)                                                        |
| 03  | [Cột truy cập, bộ policy trên bảng bản ghi, mặc định truy cập theo object và phạm vi toàn tenant cho lane](issues/03-policy-ban-ghi-va-mac-dinh-truy-cap.md) |
| 04  | [Ngữ cảnh actor ở mọi cửa và biên dữ liệu của agent và workflow](issues/04-ngu-canh-actor-o-moi-cua.md)                                                      |
| 05  | [Giao người phụ trách và đổi workspace sở hữu](issues/05-giao-nguoi-phu-trach.md)                                                                            |
