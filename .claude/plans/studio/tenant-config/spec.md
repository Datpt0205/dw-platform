# Cấu hình của tenant có phiên bản, hai người duyệt, chạy mô phỏng an toàn, bản kê lượt chạy

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Mọi thứ công ty tự dựng trong Studio (đối tượng, quy trình, agent, công cụ, kỹ năng, bộ công cụ) cần
một vỏ phiên bản chung: tối đa một phiên bản chưa phát hành (một nháp sửa được hay một Bản ứng viên đang chờ),
phiên bản niêm phong bất biến có số và mã băm tái tạo được, và Nơi đang dùng chặn xóa thứ đang được dùng. Mỗi lượt
chạy ghim mọi thứ nó dùng vào một bản kê, kể cả khi tiếp tục sau nhiều ngày chờ duyệt; chế độ chạy do máy chủ đặt và
được kiểm ở executor, nên người dựng chạy mô phỏng mà không tác động nào rời nền tảng; giá trị của điểm gắn chỉ có
hiệu lực khi một người khác Người đề xuất duyệt. Đợt W1 phục vụ YC30-YC35; YC36, YC37 và YC75 thuộc
W2. Các spec dựng thành phần (custom-objects, workflow-engine, agent-builder, tools-and-skills) và
agent-lifecycle đứng trên vỏ này (ADR-0109 (Accepted), ADR-0110 (Accepted), ADR-0111 (Accepted)).

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- `TenantOverlay` giữ lớp nền tảng và lớp tenant trong bộ nhớ
  (`packages/python/dw_kernel/src/dw_kernel/overlay.py:29-70`); API nạp mọi registry mà không truyền
  tenant (`apps/api/src/dw_api/bootstrap/runtime.py:117`). Thiếu: không có kho lưu lớp riêng của tenant;
  câu "loaded from storage" (`packages/python/dw_kernel/src/dw_kernel/overlay.py:17-19`) chưa đúng.
- `platform.policy_overrides` một dòng mỗi `(tenant_id, policy_id)`
  (`db/migrations/versions/45dc1b5e0125_platform_policy_overrides.py:74`), ghi đè tại chỗ
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/policy_overrides.py:69-72`);
  `PolicyOverridePort` (`packages/python/dw_platform/src/dw_platform/application/ports.py:120`) không có
  bên đọc ngoài adapter và test. Ràng buộc: bảng còn tới khi W2 gỡ; W1 không ghi vào đó.
- Băm hôm nay là `json.dumps(sort_keys=True)` ở khóa chống lặp của executor
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:69-73`) và ở ref của release
  manifest (`scripts/release_manifest.py:249-254`). Thiếu: không có dạng chuẩn RFC 8785; hai hàm này
  giữ nguyên (G2, G3).
- Kernel chỉ dùng stdlib theo hợp đồng import-linter "Kernel is pure" (`pyproject.toml:252`). Ràng
  buộc: hàm dạng chuẩn không phụ thuộc gói ngoài; `rfc8785` chỉ ở nhóm dev.
- `platform.worker_runs` (`db/migrations/sql/0001_platform_baseline.sql:447`) chỉ có
  `release_manifest_ref` và bốn nhãn `varchar(16)`
  (`db/migrations/versions/0005_run_artifact_versions.py:41-51`). Thiếu: không có chế độ chạy, không
  ghim được phiên bản Studio.
- `RunContext` không có chế độ chạy (`packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:98`),
  còn `autonomy_ceiling` mặc định đóng (`packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:141`).
  Ràng buộc: bốn chỗ dựng ngữ cảnh phải đặt chế độ, gồm lần tiếp tục sau duyệt
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:269`),
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:382`,
  `apps/api/src/dw_api/bootstrap/container.py:211` và
  `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_usage.py:188`.
- ToolExecutor thực thi mọi lệnh gọi chính sách cho phép
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:135`); `tool_executions.status`
  chưa có CHECK (`db/migrations/sql/0001_platform_baseline.sql:423`) và index chống lặp chỉ trên
  `succeeded` (`db/migrations/sql/0001_platform_baseline.sql:698`). Thiếu: không có bước chế độ chạy.
- `WATCHED_LITERALS` bắt mỗi giá trị Literal mới phải có bên đọc (`scripts/verify_invariants.py:109-112`).
  Ràng buộc: module của `RunMode` vào danh sách này.
- Prefix nghiêm từ chối người yêu cầu ở cả duyệt lẫn từ chối
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:118-124`); guard theo loại
  là hàm đồng bộ không thấy quyết định (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:47`);
  yêu cầu không lượt chạy ghi sự kiện quyết định vào outbox
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:245`). Ràng buộc: rút đề xuất
  `config.` không đi được đường tự từ chối; guard `decision_stale` cần port async.
- API đặt prefix nghiêm `{"memory."}` (`apps/api/src/dw_api/bootstrap/runtime.py:237`), worker thêm
  bằng `|=` (`apps/worker/src/dw_worker/main.py:175`); `SqlScopeHolders.holding` liệt kê người giữ một
  quyền trong workspace (`packages/python/dw_platform/src/dw_platform/adapters/persistence/scope_holders.py:77`).
  Ràng buộc: `config.` vào cả hai chỗ; `no_checker_available` đọc từ `holding`.
- Grant chỉ phủ schema `platform`, `knowledge`, `memory` (`db/migrations/sql/0001_platform_grants.sql:27`);
  offboarding xóa theo thứ tự chữ cái cộng danh sách tay `_ORDERED_FIRST`
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:108-114`). Ràng
  buộc: foundations-hardening/07 thay danh sách đó bằng sổ bước xóa có thứ tự suy từ khóa ngoại `RESTRICT` và
  `NO ACTION` của `pg_constraint` (foundations-hardening:R11.4; H-2), nên một cạnh RESTRICT mới của spec này không sửa
  danh sách nào.
- `platform.workspaces` chỉ unique `(tenant_id, slug)`
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:46`). Thiếu: FK ghép
  `(tenant_id, owning_workspace_id)` cần `uq_workspaces_tenant_id_id`.
- `WorkflowRunnerPort.hosts` đòi đúng các phiên bản lượt chạy bắt đầu
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/ports.py:132`). Ràng buộc: bản kê mở rộng
  điều này cho phiên bản nằm trong database (ADR-0109 (Accepted) quyết 7).

## Mục tiêu

### R1 — Dạng chuẩn và mã băm một chủ

Mọi mã băm của Studio do một hàm dạng chuẩn trong kernel sinh ra, tái tạo được ở ngôn ngữ khác.

- R1.1 KHI một tài liệu hợp lệ được băm, hàm dạng chuẩn của kernel PHẢI trả `sha256:` cùng 64 chữ số
  hex trên bytes JCS theo RFC 8785, trùng các vector không số thực của RFC đó.
- R1.2 NẾU tài liệu chứa số thực, NaN hoặc Infinity, THÌ hàm dạng chuẩn PHẢI từ chối với mã
  `float_forbidden` và không trả mã băm nào.
- R1.3 NẾU tài liệu chứa số nguyên có trị tuyệt đối vượt 2^53−1, THÌ hàm dạng chuẩn PHẢI từ chối với mã
  `integer_out_of_range` (2^53−1 thì nhận, 2^53 thì từ chối) và không trả mã băm nào.
- R1.4 NẾU một chuỗi hay một khóa của tài liệu không ở dạng NFC, THÌ hàm dạng chuẩn PHẢI từ chối với mã
  `not_nfc` và không trả mã băm nào.
- R1.5 KHI băm release manifest đã commit (bỏ `git_sha`), hàm dạng chuẩn PHẢI cho đúng bytes mà ref của
  release manifest đang băm.

### R2 — Vỏ phiên bản: một nháp, phiên bản niêm phong bất biến

Người dựng của mọi loại thành phần có tối đa một phiên bản chưa phát hành, một nháp sửa được hay một Bản ứng viên
đang chờ, và các phiên bản niêm phong không đổi, đánh số không dùng lại (YC30; ADR-0109 (Accepted) quyết 1-2;
ADR-0120 (Accepted) quyết 1).

- R2.1 KHI người giữ quyền ghi của loại thành phần tạo một thành phần, API Studio PHẢI tạo trong một
  giao dịch thành phần có id UUIDv7, Tên API, workspace sở hữu và đúng một nháp, kèm audit
  `studio.artifact.created`.
- R2.2 NẾU Tên API không khớp `^[a-z][a-z0-9_]{1,39}$` (2 tới 40 ký tự), THÌ API Studio PHẢI trả 422
  `validation_failed` và không tạo gì.
- R2.3 NẾU Tên API trùng một thành phần chưa xóa cùng loại trong tenant, THÌ API Studio PHẢI trả 409
  `conflict` với `details.reason_code` `api_name_taken` và không tạo gì.
- R2.4 KHI người giữ quyền ghi lưu nháp với `If-Match` bằng `row_version` hiện tại, API Studio PHẢI thay
  tài liệu nháp, tăng `row_version` và trả ETag mới.
- R2.5 NẾU người gọi lưu nháp với `If-Match` khác `row_version` hiện tại, THÌ API Studio PHẢI trả 412
  `precondition_failed` với `details.reason_code` `stale_version` và không đổi nháp.
- R2.6 NẾU tài liệu đem niêm phong có lỗi, THÌ dịch vụ vỏ phiên bản PHẢI trả 422 `validation_failed`
  liệt kê mọi lỗi trong `errors[]` bằng con trỏ JSON và không niêm phong gì.
- R2.7 KHI niêm phong một nháp hợp lệ, dịch vụ vỏ phiên bản PHẢI, trong giao dịch của bên gọi, cấp `version_no`
  bằng `last_version_no` cộng 1, ghi `content_hash`, `definition_hash` và để phiên bản ở `draft`, vì bước chuyển
  giai đoạn theo loại trong cùng giao dịch là của `LifecycleService` của agent-lifecycle, với
  `studio.guard_version_stage()` là hàng rào cuối (agent-lifecycle:R2.1, agent-lifecycle:R2.8; ADR-0120 (Accepted)
  quyết 1).
- R2.8 Dịch vụ vỏ phiên bản PHẢI không bao giờ cấp lại một `version_no` đã cấp cho cùng thành phần, kể
  cả khi phiên bản mang số đó quay về `draft`.
- R2.9 NẾU một lệnh ghi đổi `document`, `document_schema`, `content_hash`, `definition_hash` hay
  `version_no` của phiên bản không ở giai đoạn `draft`, THÌ PostgreSQL PHẢI từ chối lệnh đó, kể cả khi
  `dw_app` ghi thẳng bằng SQL.
- R2.10 NẾU người gọi đổi Tên API của thành phần đã có phiên bản từng ở giai đoạn `live`, THÌ API Studio
  PHẢI trả 409 `conflict` với `details.reason_code` `api_name_immutable` và không đổi tên.
- R2.11 NẾU thành phần thuộc tenant khác, hoặc người gọi không giữ quyền đọc của loại ở độ sâu chạm tới
  workspace sở hữu, THÌ API Studio PHẢI trả 404 và không lộ thành phần đó.
- R2.12 NẾU người gọi đọc được thành phần nhưng không giữ quyền ghi của loại ở độ sâu đó, THÌ API Studio
  PHẢI trả 403 `permission_denied` và không đổi gì.
- R2.13 ĐỐI VỚI loại thành phần không có Cổng chất lượng (`object` và `endpoint` ở W1, `tool` ở W2), dịch vụ vỏ phiên
  bản PHẢI niêm phong đúng như R2.7, không đọc `has_quality_gate` và không đổi `stage`, để `LifecycleService` đưa
  phiên bản từ `draft` thẳng sang `awaiting_approval`, ngoài nhánh chỉ siết của R2.16, và mở yêu cầu phê duyệt phát
  hành trong cùng giao dịch (agent-lifecycle:R1.6, agent-lifecycle:R2.8, agent-lifecycle:R5.1; ADR-0120 (Accepted)
  quyết 1-2).
- R2.14 NẾU một dòng đăng ký loại vào `studio.artifact_kinds` không nêu `has_quality_gate`, THÌ PostgreSQL PHẢI
  từ chối dòng đó, để không loại nào bỏ qua kiểm định chỉ vì thiếu khai báo.
- R2.15 Mỗi mục `ArtifactKindRegistry` PHẢI khai khóa đọc, khóa ghi và khóa gửi của loại, mỗi khóa có trong danh
  mục quyền một chủ của tenant-rbac, cùng móc phát hành mà spec của loại cấp, để R2.11, R2.12 và lệnh gửi của
  agent-lifecycle (agent-lifecycle:R2.1) kiểm đúng khóa của loại đó và giao dịch phát hành của agent-lifecycle chạy
  đúng móc của loại (agent-lifecycle:R2.9, agent-lifecycle:R5.5; ADR-0109 (Accepted) quyết 1).
- R2.16 ĐỐI VỚI phiên bản `dw.object/v1` mà lệnh gửi của agent-lifecycle đưa vào nhánh chỉ siết (custom-objects:R1.7),
  dịch vụ vỏ phiên bản PHẢI niêm phong đúng như R2.7 và không đổi dòng phiên bản nào khác của thành phần, để
  `LifecycleService` đưa phiên bản từ `draft` sang `live` trong giao dịch của người gửi (agent-lifecycle:R2.9); không
  Bản ứng viên nào chờ cạnh bản Nháp đó, vì R2.20 giữ một phiên bản chưa phát hành mỗi thành phần, còn kiểm
  `compared_live_hash` của agent-lifecycle:R1.8 vẫn là hàng rào (ADR-0120 (Accepted) quyết 1).
- R2.17 NẾU `row_version` mà lệnh gửi của agent-lifecycle đưa cho bước niêm phong, tức giá trị `If-Match` của lệnh
  gửi, khác `row_version` hiện tại của nháp, THÌ dịch vụ vỏ phiên bản PHẢI từ chối với `details.reason_code`
  `stale_version` để lệnh gửi trả 412 `precondition_failed`, và không niêm phong gì (agent-lifecycle:R2.12;
  ADR-0108 (Accepted) quyết 3; ADR-0109 (Accepted) quyết 2).
- R2.18 NẾU một dòng trỏ tới một thành phần, một phiên bản, một phiên bản cấu hình hay một workspace của tenant khác,
  qua `artifact_id` hay `based_on_version_id` của phiên bản, Nơi đang dùng (`from_artifact_id`, `from_version_id`,
  `to_artifact_id`, `to_version_id`), khóa bản kê (`artifact_version_id`, `config_version_id`) hay
  `owning_workspace_id` của thành phần, THÌ PostgreSQL PHẢI từ chối dòng đó bằng FK ghép `(tenant_id, <cột>)` tới
  UNIQUE `(tenant_id, id)` của bảng đích (`uq_artifacts_tenant_id_id`, `uq_artifact_versions_tenant_id_id`,
  `uq_config_versions_tenant_id_id`, `uq_workspaces_tenant_id_id`), kể cả khi vai ghi bỏ qua RLS.
- R2.19 NẾU một lệnh ghi đổi `owning_workspace_id` của một thành phần, THÌ PostgreSQL PHẢI từ chối lệnh đó, kể cả khi
  `dw_app` ghi thẳng bằng SQL, vì AAD của phong bì bí mật của chủ thể thuộc thành phần (như bí mật ký của một Nguồn dữ
  liệu) gắn workspace sở hữu (ADR-0115 (Accepted) quyết 1).
- R2.20 NẾU một lệnh ghi đặt một phiên bản thứ hai của cùng thành phần vào `draft`, `evaluating` hay
  `awaiting_approval`, THÌ PostgreSQL PHẢI từ chối lệnh đó, kể cả khi `dw_app` ghi thẳng bằng SQL, để mỗi thành phần có
  tối đa một bản Nháp hay Bản ứng viên bên cạnh tối đa một phiên bản Đang dùng (ADR-0120 (Accepted) quyết 1).
- R2.21 KHI người giữ quyền ghi của loại tạo bản Nháp cho một thành phần không có phiên bản nào ở `draft`,
  `evaluating` hay `awaiting_approval`, API Studio PHẢI tạo trong một giao dịch một bản Nháp chép `document_schema` và
  `document` của phiên bản Đang dùng, hay của phiên bản có `version_no` lớn nhất khi thành phần không có bản Đang dùng,
  với `based_on_version_id` trỏ phiên bản đó và audit `studio.artifact.draft_created`, rồi trả ETag của bản Nháp.
- R2.22 NẾU người gọi tạo bản Nháp cho một thành phần có Bản ứng viên ở `evaluating` hay `awaiting_approval`, THÌ API
  Studio PHẢI trả 409 `conflict` với `details.reason_code` `candidate_pending` và không tạo gì, vì muốn sửa thì người
  giữ khóa gửi của loại rút Bản ứng viên về Nháp (agent-lifecycle:R2.4).
- R2.23 NẾU người gọi tạo bản Nháp cho một thành phần đã có bản Nháp, THÌ API Studio PHẢI trả 409 `conflict` với
  `details.reason_code` `draft_exists` và không đổi bản Nháp đó.

### R3 — Nơi đang dùng và chặn xóa

Người dựng thấy cái gì đang dùng một thành phần, và không xóa được thứ một phiên bản khác đang dùng
(YC31; ADR-0109 (Accepted) quyết 5).

- R3.1 KHI một nháp được niêm phong, dịch vụ vỏ phiên bản PHẢI ghi Nơi đang dùng của phiên bản đó trong
  cùng giao dịch niêm phong, để giao dịch hỏng không để lại số phiên bản lẫn dòng phụ thuộc nào.
- R3.2 KHI người giữ quyền ghi xóa mềm một thành phần mà không phiên bản `evaluating`,
  `awaiting_approval` hay `live` nào của thành phần khác dùng, API Studio PHẢI đặt `deleted_at` và ghi
  audit `studio.artifact.deleted` trong một giao dịch.
- R3.3 NẾU người gọi xóa mềm một thành phần mà một phiên bản `evaluating`, `awaiting_approval` hoặc
  `live` của thành phần khác đang dùng, THÌ API Studio PHẢI trả 409 `conflict` với
  `details.reason_code` `artifact_in_use` kèm số đếm và không xóa gì.
- R3.4 KHI người gọi mở Nơi đang dùng của một thành phần, API Studio PHẢI nhóm bên phụ thuộc theo giai
  đoạn, chỉ nêu tên bên người gọi đọc được và chỉ đếm phần còn lại.
- R3.5 KHI người gọi xem phụ thuộc của một nháp, API Studio PHẢI tính chúng bằng cùng bộ trích xuất của
  loại và không ghi dòng nào vào Nơi đang dùng.
- R3.6 KHI lane offboarding xóa một tenant có thành phần phụ thuộc nhau, bản kê lượt chạy và phiên bản
  cấu hình riêng, lane offboarding PHẢI xóa hết các dòng đó của tenant và không đổi dòng nào của tenant
  khác.
- R3.7 KHI connections-and-vault hỏi một Kết nối có thành phần nào đang dùng không
  (connections-and-vault:R5.8), dịch vụ Nơi đang dùng PHẢI trả lời từ các Bộ giá trị gắn đã duyệt có giá
  trị là Kết nối đó cộng `studio.dependencies`, không từ nguồn thứ hai.
- R3.8 NẾU một lệnh xóa chạm một dòng `studio.artifacts`, `studio.artifact_versions`, `studio.definition_manifests`,
  `platform.run_manifests`, `platform.run_manifest_keys` hay `platform.config_versions` của một công ty có
  `platform.tenants.status` khác `offboarding`, THÌ PostgreSQL PHẢI từ chối lệnh đó với SQLSTATE 23514 và không xóa
  dòng nào, kể cả khi `dw_app` xóa thẳng bằng SQL, vì chỉ lượt xóa của lane `offboarding` (R3.6) xóa cứng các dòng
  đó.

### R4 — Chế độ chạy do máy chủ đặt

Mỗi lượt chạy mang một chế độ chạy do máy chủ đặt lúc nhận, không bao giờ nới ra (YC33;
ADR-0111 (Accepted) quyết 1-2).

- R4.1 NẾU một lệnh ghi tạo lượt chạy không nêu `run_mode` hoặc nêu giá trị ngoài `live`, `test`,
  `simulate`, THÌ PostgreSQL PHẢI từ chối lệnh đó.
- R4.2 NẾU một chỗ dựng ngữ cảnh lượt chạy không đặt chế độ, THÌ ngữ cảnh lượt chạy PHẢI mang
  `simulate`.
- R4.3 KHI runner bắt đầu một lượt chạy của worker định nghĩa bằng code, runner PHẢI ghi `run_mode`
  `live` lên dòng lượt chạy, span `dw.run_mode` và `details.run_mode` của audit `run.started`.
- R4.4 KHI một lượt con được yêu cầu, luật chế độ lượt con PHẢI trả chế độ đứng trước trong cặp (chế độ
  của cha, chế độ yêu cầu) theo thứ tự `simulate`, `test`, `live`.
- R4.5 KHI một lượt chạy tiếp tục sau phê duyệt ở bất kỳ tiến trình nào, runtime PHẢI dựng lại ngữ cảnh
  lượt chạy với `run_mode` đọc từ dòng lượt chạy.

### R5 — Mô phỏng chặn tác động tại executor

Người dựng chạy mô phỏng mà không lệnh gọi có tác động nào rời nền tảng (YC34;
ADR-0111 (Accepted) quyết 3).

- R5.1 TRONG KHI lượt chạy ở chế độ `simulate` hoặc `test`, NẾU công cụ được gọi không khai
  `simulate_safe`, THÌ ToolExecutor PHẢI không gọi handler và ghi lệnh gọi với `status` `simulated`.
- R5.2 KHI ToolExecutor giả lập một lệnh gọi, ToolExecutor PHẢI ghi audit `tool.simulated` có
  `details.run_mode` và `details.reason` trong cùng giao dịch với dòng lệnh gọi.
- R5.3 KHI ToolExecutor giả lập một lệnh gọi, ToolExecutor PHẢI trả đầu ra giả lập sinh từ output schema
  của công cụ, đã kiểm theo schema đó và đánh dấu `simulated: true`.
- R5.4 KHI lượt chạy ở chế độ `simulate` gọi công cụ khai `simulate_safe`, ToolExecutor PHẢI thực thi
  công cụ như ở chế độ `live`.
- R5.5 NẾU định nghĩa công cụ không nêu `simulate_safe`, THÌ ToolExecutor PHẢI coi giá trị đó là
  `false`.
- R5.6 TRONG KHI lượt chạy ở chế độ `simulate` hoặc `test`, NẾU công cụ không khai `simulate_safe` có chính sách
  đòi phê duyệt, THÌ ToolExecutor PHẢI giả lập lệnh gọi trước bước phê duyệt và không mở yêu cầu phê duyệt nào,
  theo thứ tự bước của tools-and-skills:R2.6 (ADR-0111 (Accepted) quyết 5).

### R6 — Bản kê lượt chạy

Mỗi lượt chạy Studio ghim mọi thứ nó dùng và chỉ đọc từ bản kê đó, kể cả khi tiếp tục sau 3 ngày chờ
duyệt hay lâu hơn (YC32; ADR-0109 (Accepted) quyết 6-7).

- R6.1 KHI một lượt chạy có gốc là thành phần Studio được nhận, runtime PHẢI ghi lên dòng lượt chạy
  `run_manifest_hash` của bản kê `dw.run_manifest/v1` gồm release ref, chế độ chạy, phiên bản gốc với
  `definition_hash` và bao đóng, trước node đầu tiên; lượt `simulate` trên bản Nháp ghim giai đoạn `draft` và mã
  băm tạm của nội dung nháp lúc nhận, tính bằng cùng bước băm của niêm phong (ADR-0109 (Accepted) quyết 4 và 6).
- R6.2 KHI hai lượt chạy ghim cùng nội dung, PostgreSQL PHẢI giữ đúng một dòng bản kê cho mã băm đó.
- R6.3 TRONG KHI một lượt chạy Studio chạy hay tiếp tục, NẾU nó hỏi một khóa không có trong bản kê, THÌ
  runtime PHẢI từ chối lần phân giải đó và không đọc phiên bản hiện hành.
- R6.4 KHI một lượt chạy Studio tiếp tục ở tiến trình khác sau khi chờ duyệt, runtime PHẢI dựng lại mọi
  phân giải từ bản kê đã ghim, kể cả khi thành phần đã có phiên bản mới hơn.
- R6.5 NẾU một lệnh xóa chạm tới bản kê, hay tới phiên bản mà bản kê ghim, trong khi lượt chạy còn trỏ
  tới bản kê đó, THÌ PostgreSQL PHẢI từ chối lệnh xóa.
- R6.6 Việc dựng và ghi bản kê NÊN thêm không quá 20 ms p95 vào lúc nhận lượt chạy (bao đóng 50 thành
  phần, đo trên compose), trừ khi số đo ghi ở ticket 04 cho thấy không đạt và Đạt chấp nhận số mới.
- R6.7 NẾU một lượt chạy có gốc là phiên bản `draft` được nhận ở chế độ khác `simulate`, THÌ runtime PHẢI từ chối
  nhận lượt chạy đó trước node đầu tiên và không ghi bản kê nào, để không lượt `live` hay `test` nào dùng mã băm
  tạm của một bản Nháp (ADR-0109 (Accepted) quyết 6).
- R6.8 KHI runtime ghi bản kê của một lượt chạy Studio, runtime PHẢI ghim `durability` bằng `sync` trong mục `engine`
  của bản kê, giá trị duy nhất mà mô hình `dw.run_manifest/v1` nhận, để mọi lần chạy và tiếp tục của lượt truyền cùng độ
  bền checkpoint (ADR-0109 (Accepted) quyết 8; V4.34; workflow-engine:R4.25).

### R7 — Điểm gắn trong tài liệu

Tài liệu chỉ nêu tên những gì nó cần (kết nối, biến, người chạy), không bao giờ id kết nối; giá trị
nằm ở Bộ giá trị gắn đã duyệt và được ghim theo lượt chạy (YC35; ADR-0110 (Accepted) quyết 6-8). Bản kê ghim kết
nối, không ghim phiên bản bí mật của nó: lúc gọi, lời gọi dùng phiên bản mới nhất chưa bị thu hồi của kết nối, nên
một bí mật được xoay trong lúc lượt chờ tới được lượt đó, còn một bí mật bị thu hồi vì lộ dừng lượt ở lời gọi egress
kế tiếp (V4.35; ADR-0109 (Accepted) quyết 6; ADR-0115 (Accepted) quyết 1).

- R7.1 NẾU tài liệu đem niêm phong chứa id kết nối ở chỗ phải là tên điểm gắn, THÌ dịch vụ vỏ phiên bản
  PHẢI trả 422 `validation_failed` có một lỗi cho mỗi đường dẫn đó và không niêm phong.
- R7.2 NẾU phiên bản đem gửi hay phát hành có điểm gắn bắt buộc chưa có giá trị đã duyệt, THÌ kiểm điểm gắn
  (`PublishBindingsCheck`) PHẢI trả `binding_unset` kèm tên điểm gắn, để lệnh gửi trả 409 và handler `.decided`
  không đưa phiên bản sang `live` (agent-lifecycle:R2.11, agent-lifecycle:R5.10).
- R7.3 NẾU lúc nhận lượt chạy, kết nối được gắn đã bị thu hồi hoặc không còn dùng được cho người chạy,
  THÌ runtime PHẢI từ chối lượt chạy với `binding_degraded` trước node đầu tiên.
- R7.4 KHI một lượt chạy được nhận, runtime PHẢI ghim vào bản kê id phiên bản Bộ giá trị gắn, id của từng kết nối
  và mã băm của từng giá trị biến, không ghi phiên bản bí mật hay giá trị bí mật nào, vì lời gọi phân giải bí mật của
  kết nối lúc gọi và ghi phiên bản đã dùng vào `platform.tool_executions.credential_version` cùng audit của nó
  (connections-and-vault; ADR-0109 (Accepted) quyết 6; ADR-0115 (Accepted) quyết 1; V4.35, H-10).
- R7.5 KHI một Bộ giá trị gắn mới được duyệt, hay bí mật của một kết nối đã ghim được xoay, trong lúc một lượt chạy
  đang chờ duyệt, runtime PHẢI tiếp tục lượt chạy đó với Bộ giá trị gắn đã ghim, còn lời gọi của nó dùng phiên bản bí
  mật mới nhất chưa bị thu hồi của kết nối lúc gọi (V4.35; connections-and-vault là chủ phép phân giải và luật thu hồi
  vì lộ).

### R8 — Bộ giá trị gắn: một người đề xuất, một người khác duyệt

Giá trị điểm gắn chỉ có hiệu lực sau khi một người khác Người đề xuất duyệt (YC35; D11;
ADR-0110 (Accepted) quyết 1-2, 7).

- R8.1 KHI người giữ `studio.bindings.propose` ở workspace đang làm việc đề xuất Bộ giá trị gắn cho một
  thành phần, API Studio PHẢI ghi trong một giao dịch phiên bản cấu hình riêng `binding_set` ở
  `proposed`, yêu cầu phê duyệt `config.version` có `required_scope` `studio.bindings.approve` và audit
  `config.version.proposed`.

Đề xuất bị từ chối, không ghi dòng nào, khi:

| Mã   | Điều kiện                                                                                                                                       | API Studio trả                                               |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| R8.2 | người gọi thiếu `studio.bindings.propose` ở workspace đang làm việc                                                                             | 403 `permission_denied`                                      |
| R8.3 | thành phần hay kết nối thuộc tenant khác                                                                                                        | 404                                                          |
| R8.4 | giá trị sai kiểu khai báo; kết nối khác trình kết nối hay phiên bản chính khai báo, thiếu quyền khai báo, hoặc Người đề xuất không dùng được nó | 422 `validation_failed`, mỗi lỗi một con trỏ                 |
| R8.5 | không ai khác Người đề xuất giữ `studio.bindings.approve` ở workspace của đề xuất                                                               | 409 `conflict`, `details.reason_code` `no_checker_available` |
| R8.6 | khóa đã có một đề xuất mở                                                                                                                       | 409 `conflict`, `details.reason_code` `proposal_open`        |
| R8.7 | loại cấu hình chưa đăng ký                                                                                                                      | 422 `validation_failed`                                      |

- R8.8 NẾU người quyết định là Người đề xuất, THÌ luồng phê duyệt PHẢI trả 409 `conflict` với
  `details.reason_code` `second_person_required` và không ghi quyết định nào (ADR-0104 (Accepted) quyết 11).
- R8.9 NẾU Phiên bản gốc của đề xuất đã đổi trước lúc quyết định, hay lúc duyệt một kết nối của đề xuất không còn
  dùng được cho Người đề xuất ở workspace của đề xuất (connections-and-vault:R5.9; ADR-0110 (Accepted) quyết 7), THÌ
  luồng phê duyệt PHẢI trả 409 `conflict` với `details.reason_code` `decision_stale` và giữ yêu cầu phê duyệt ở
  `pending`.
- R8.10 KHI yêu cầu phê duyệt `config.version` được duyệt, lane `outbox` PHẢI đặt phiên bản sang
  `approved` và bản đã duyệt trước của cùng khóa sang `superseded` trong một giao dịch có audit
  `config.version.approved` đứng tên người quyết (`decided_by`) với `details.lane` `outbox` (ADR-0011 (Accepted)).
- R8.11 KHI yêu cầu phê duyệt bị từ chối, hoặc lúc quyết toán đã có bản khác được duyệt cho cùng khóa,
  lane `outbox` PHẢI đặt phiên bản sang `rejected` (lý do `settlement_conflict` ở trường hợp sau) trong
  một giao dịch có audit `config.version.rejected` đứng tên người quyết với `details.lane` `outbox`.
- R8.12 NẾU một lệnh ghi đặt `approved` khi yêu cầu phê duyệt liên kết chưa duyệt, đổi `document` của
  phiên bản cấu hình riêng, hoặc đổi `status` ngoài các bước `proposed` sang `approved`, `rejected`,
  `withdrawn` và `approved` sang `superseded`, THÌ PostgreSQL PHẢI từ chối lệnh đó.
- R8.13 KHI Người đề xuất rút đề xuất còn mở của mình, API Studio PHẢI đặt nó sang `withdrawn` và hủy
  yêu cầu phê duyệt liên kết trong một giao dịch có audit `config.version.withdrawn`.
- R8.14 NẾU người rút đề xuất không phải Người đề xuất, THÌ API Studio PHẢI trả 403 `permission_denied`
  và không đổi gì.
- R8.15 KHI outbox giao lại một sự kiện quyết định đã được quyết toán, lane `outbox` PHẢI không đổi dòng
  nào và không ghi audit thứ hai.
- R8.16 NẾU một phiên bản cấu hình riêng trỏ `approval_id` tới một yêu cầu phê duyệt của tenant khác, hay của một
  workspace khác workspace của đề xuất, THÌ PostgreSQL PHẢI từ chối dòng đó bằng FK ghép
  `(tenant_id, workspace_id, approval_id)` tới `uq_approval_requests_tenant_id_workspace_id_id`, kể cả khi vai ghi bỏ
  qua RLS.

## Hành vi giữ nguyên

- G1 KHI một lượt chạy của worker định nghĩa bằng code gọi công cụ mà chính sách cho phép, ToolExecutor
  PHẢI TIẾP TỤC thực thi công cụ và ghi `succeeded` (test:
  `packages/python/dw_agent_runtime/tests/unit/test_executor.py::test_happy_path_returns_typed_output_and_audits`).
- G2 KHI ToolExecutor dẫn khóa chống lặp cho một lệnh gọi, ToolExecutor PHẢI TIẾP TỤC dùng hàm băm hiện
  có, để lượt chạy đang dở phát lại đúng kết quả đã lưu (test:
  `packages/python/dw_agent_runtime/tests/unit/test_executor.py::test_replay_returns_cached_output_without_reexecution`).
- G3 KHI release manifest được dựng lại từ cùng tập artifact, script release manifest PHẢI TIẾP TỤC cho
  cùng ref và bỏ qua `git_sha` (test:
  `apps/api/tests/unit/test_release_manifest.py::test_manifest_ref_is_stable_and_ignores_git_sha`).
- G4 KHI một yêu cầu `memory.review` được quyết định, luồng phê duyệt PHẢI TIẾP TỤC quyết theo prefix
  nghiêm và guard độ mật (test:
  `apps/api/tests/unit/test_memory_review_wiring.py::test_the_api_decides_memory_reviews_strictly_and_only_with_clearance`).

## Trong phạm vi

- Bảng và cột ở mục Dữ liệu; route ở mục API.
- Mã: `dw_kernel.canonical`; `RunMode` và luật chế độ lượt con trong kernel; `ArtifactKindRegistry` (mô hình tài liệu,
  bộ kiểm trả mọi lỗi, bộ trích xuất phụ thuộc thuần, khóa đọc, ghi và gửi của loại, móc phát hành của loại) và bước
  niêm phong của vỏ phiên bản, so `row_version` mà lệnh gửi đưa; bước chế độ chạy trong ToolExecutor; `RunManifestPort`
  (runtime khai, Studio đáp ứng) và `PinnedResolver`; `ConfigKindRegistry` với loại `binding_set`; bộ kiểu Điểm gắn, nơi
  mỗi kind đăng ký kiểm lúc đề xuất của nó; kiểm điểm gắn lúc gửi và lúc phát hành (đáp ứng `PublishBindingsCheck` mà
  agent-lifecycle khai) và lúc nhận lượt chạy (`binding_degraded`, R7.3); port async `ApprovalDecisionGuard` thay
  `DecisionGuard`; mã `second_person_required` của tiền tố nghiêm cho mọi loại phê duyệt; handler
  `config.version.decided` ở lane `outbox`; `RunBindingsPort` đáp ứng từ bản kê và `ConnectionDependentsPort` đáp ứng từ
  Nơi đang dùng (hai port do connections-and-vault khai).
- Audit: `studio.artifact.created`, `studio.artifact.updated`, `studio.artifact.draft_saved`,
  `studio.artifact.draft_created`, `studio.artifact.deleted`, `tool.simulated`, `config.version.proposed`,
  `config.version.approved`, `config.version.rejected`, `config.version.withdrawn`.

## Ngoài phạm vi

| Việc                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | Vì sao                                                                                                                                                                                                                                                                                                                       | Chủ                                                   |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| W2: người nhận thử và kiểm ở egress, mở chế độ `test` (kiểm soát TC12-TC14: egress, Danh sách người nhận thử, thông báo của lượt không `live` chỉ tới người chạy thử)                                                                                                                                                                                                                                                                                                                                                                                              | YC36; cần `studio.test_recipients`, kết nối bật chế độ thử và lời đồng ý của DO-55                                                                                                                                                                                                                                           | tenant-config, đợt sau (W2); connections-and-vault    |
| W2: biểu mẫu sinh từ schema, so sánh từng trường, xem thay đổi ở hộp duyệt; màn hình thành phần, Nơi đang dùng và Bộ giá trị gắn                                                                                                                                                                                                                                                                                                                                                                                                                                   | W1 chỉ mở API; độ vừa của biểu mẫu dw-proterial chờ FOG-53                                                                                                                                                                                                                                                                   | tenant-config, đợt sau (W2)                           |
| W2: lớp riêng của tenant cho prompt, tool spec, toolset, model profile, chính sách; `effective_hash`; gỡ `platform.policy_overrides`                                                                                                                                                                                                                                                                                                                                                                                                                               | YC37; DO-27 (Đạt 23/10/2026): ghi đè prompt chỉ khi prompt có bên đọc theo công ty, không `raw_variables`, không prompt khung, và đổi Mã băm hiệu lực; gỡ `platform.policy_overrides` cùng lúc `platform.config_versions` nhận kind `policy`, sau khi đếm 0 dòng ở mọi môi trường; `ModelProfile` cần phiên bản và `Decimal` | tenant-config, đợt sau (W2)                           |
| W2: tín hiệu lệch cấu hình (gồm outbox `config.version.approved`); lưu giữ và dọn; CI chặn xóa artifact nền tảng đã phát hành                                                                                                                                                                                                                                                                                                                                                                                                                                      | YC75; chưa có bên đọc ở W1; thời hạn lưu giữ là số tạm của DO-52 trong tệp `retention` do telemetry-and-audit/03 làm chủ                                                                                                                                                                                                     | tenant-config, đợt sau (W2); agent-lifecycle đọc lệch |
| W3: phụ thuộc quan sát được; đọc lại ghi giả lập trong cùng lượt chạy thử (v1.5)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | Cần records gateway và nguyên mẫu FOG-60                                                                                                                                                                                                                                                                                     | tenant-config, đợt sau (W3)                           |
| W3: công ty thử nghiệm (sandbox tenant), đưa phiên bản sang công ty chính bằng gói                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | ADR-0111 (Accepted) quyết 7; DO-62 (Đạt 23/10/2026): chỉ người vận hành tạo, chỉ dữ liệu giả lập, hạn mức riêng                                                                                                                                                                                                              | tenant-config, đợt sau (W3)                           |
| `LifecycleService` và trigger chuyển giai đoạn sau bước niêm phong (`draft → evaluating`, `draft → awaiting_approval`, và `draft → live` ở nhánh chỉ siết của `dw.object/v1`), cột `tighten_only` và `compared_live_hash`, cổng chất lượng, lệnh gửi kiểm định (nhận `If-Match` và đưa `row_version` đó cho bước niêm phong, R2.17) và phát hành (gọi móc phát hành của loại, R2.15), lệnh rút Bản ứng viên về Nháp (đường để sửa khi Bản ứng viên còn chờ, R2.22), chỉ mục một Đang dùng, kể cả handler `.decided` trả Bản ứng viên về `draft` với `base_changed` | ADR-0120 (Accepted) quyết 1-2 giao cho vòng đời                                                                                                                                                                                                                                                                              | agent-lifecycle                                       |
| Cửa nhận lượt chạy, kể cả bộ kiểm một lượt của lúc gửi kiểm định mà cửa tự chạy trên nội dung nháp khi gốc là bản Nháp ở `simulate`, bên gọi nào xin cũng vậy; lượt con; sáu kiểm trước khi tiếp tục, trong đó kiểm thứ sáu đặt `blocked` với `incompatible_resume` khi nội dung bản Nháp mà lượt mô phỏng ghim đã đổi (R6.4; workflow-engine:R3.9, workflow-engine:R6.14)                                                                                                                                                                                         | ADR-0113 (Accepted); ADR-0109 (Accepted) quyết 6 và 8; một cửa cho mọi bên gọi, không chỉ route `.../test-runs` (failure-modes #5)                                                                                                                                                                                           | workflow-engine                                       |
| Route `.../test-runs` (chạy mô phỏng ở W1, nhận cả phiên bản `draft` khi bộ kiểm một lượt của lúc gửi kiểm định đạt trên nội dung nháp, không thì 422 với mã `wf.*`; 422 với `live`, và với `test` tới W2)                                                                                                                                                                                                                                                                                                                                                         | Hợp đồng duy nhất của route này (DO-26.1; workflow-triggers:R2.3, workflow-triggers:R2.9; ADR-0112 (Accepted) quyết 3)                                                                                                                                                                                                       | workflow-triggers                                     |
| W2: nhập Kết quả giả lập ghim theo Bước qua route `.../test-runs`; ở W1 kết quả ghim chỉ đến từ ca kịch bản của Cổng chất lượng và wrapper nút áp nó cho Bước ở `simulate`, sau khi kiểm với schema đầu ra của Bước, không gọi ToolExecutor                                                                                                                                                                                                                                                                                                                        | Executor không đọc kết quả ghim; lệnh gọi tới executor ở `simulate` vẫn nhận giá trị sinh từ output schema (R5.3; workflow-engine:R4.27; V4.37, H-18)                                                                                                                                                                        | workflow-triggers, W2 (phần W1: workflow-engine)      |
| Egress client ở chế độ khác `live` từ chối mọi purpose trừ `model` và Hành động chỉ đọc hay `simulate_safe` (W2 mở ngoại lệ cho Danh sách người nhận thử); phân loại `simulate_safe` theo loại công cụ                                                                                                                                                                                                                                                                                                                                                             | Lớp thứ hai sau executor (ADR-0111 (Accepted) quyết 3; ADR-0115 (Accepted) quyết 6; DO-26.1); ADR-0116 (Accepted)                                                                                                                                                                                                            | connections-and-vault; tools-and-skills               |
| W2: nhánh một người có audit cho thay đổi cấu hình chỉ siết: cột `tighten_only` do bộ so sánh của kind tính lúc đề xuất, kèm `document_hash` của bản đã duyệt được so, mà `ck_config_versions_checker_not_maker` và trigger `approved_by_approval` mở cho dòng đó                                                                                                                                                                                                                                                                                                  | ADR-0110 (Accepted) quyết 2; `binding_set` ở W1 không đăng ký bộ so sánh nào, nên mọi đề xuất `binding_set` qua hai người (R8.8, R8.12); bộ so sánh đầu tiên ra cùng kind `policy`                                                                                                                                           | tenant-config, đợt sau (W2)                           |
| W2: route tạo thành phần từ chối Tiền tố dành riêng của gói nền tảng (domain-packs:R3.1)                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | Luật bật khi gói Marketing ra ở W2; `mkt_lead`, `mkt_campaign` mà marketing-pilot/02 đã gieo giữ tên, và gói gắn nguồn gốc cho chúng khi cài (domain-packs:R4.5)                                                                                                                                                             | tenant-config, đợt sau (W2); domain-packs             |
| Đưa `record_visibility`, `max_autonomy_level`, `timezone`, `locale` của `platform.tenants` vào phiên bản có duyệt                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Đổi hành vi ngoài Studio                                                                                                                                                                                                                                                                                                     | không làm                                             |
| Lớp cấu hình thứ ba theo workspace                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | `TenantOverlay` giữ hai lớp; thành phần của một workspace là thành phần Studio riêng (ADR-0110 (Accepted))                                                                                                                                                                                                                   | không làm                                             |

## Dữ liệu

Mọi bảng có `tenant_id`: RLS ENABLE và FORCE chỉ theo tenant (định nghĩa toàn tenant, ADR-0100 (Accepted)
quyết 5), grant cùng migration, tên ràng buộc theo `NAMING_CONVENTION`, revision id hex ngẫu nhiên. Mỗi bảng
không có `workspace_id` có một dòng lý do trong danh sách bảng toàn tenant của `test_rls_coverage.py`
(DO-01): `studio.artifacts`, `studio.artifact_versions`, `studio.definition_manifests`,
`studio.dependencies`, `platform.run_manifests`, `platform.run_manifest_keys`.

Lane `offboarding` xóa bằng `dw_app` và chỉ xóa bảng mà `dw_app` có DELETE
(`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:98-101`), nên `dw_app` có DELETE trên
sáu bảng của R3.8, quyền mà ứng dụng không dùng: trigger BEFORE DELETE `platform.refuse_delete_outside_offboarding()`
từ chối với SQLSTATE 23514 khi `platform.tenants.status` của công ty của dòng khác `offboarding` hay không đọc được
(R3.8), cùng hình với trigger chặn xóa của compliance-pdpl:R5.6. `dw_app` có DELETE thường, không trigger đó, trên
`studio.dependencies`, vì bước niêm phong thay Nơi đang dùng của một phiên bản được niêm phong lại sau khi về `draft`
(R2.8, R3.1). Thứ tự xóa đến từ sổ bước xóa của foundations-hardening/07, suy từ khóa ngoại `RESTRICT` và
`NO ACTION` của `pg_constraint`: bước xóa bảng tham chiếu chạy trước bước xóa bảng được tham chiếu, không danh sách
viết tay nào (foundations-hardening:R11.4; H-2), và test phủ của studio-skeleton:R4.2 đỏ khi một bước đi trái một cạnh
đó. Bảy bảng của spec này dùng bước mặc định (câu `DELETE` chung), không đăng ký bước nào; các khóa ngoại của chúng
cho thứ tự: `studio.dependencies` cùng các bảng trỏ tới phiên bản (`platform.worker_runs`,
`platform.run_manifest_keys`, bảng của spec khác) trước `studio.artifact_versions`, rồi các bảng kiểm định của
agent-lifecycle (agent-lifecycle:R10.2), rồi `studio.artifacts`; `platform.run_manifest_keys` trước
`platform.config_versions`; `platform.worker_runs` trước `platform.run_manifests`.

- `studio.artifact_kinds`: danh mục loại của nền tảng, không có `tenant_id`; `kind text` là khóa chính;
  `has_quality_gate boolean NOT NULL`, không DEFAULT, mà dịch vụ gửi kiểm định (qua `LifecycleService`) và
  `studio.guard_version_stage()` của agent-lifecycle cùng đọc, còn bước niêm phong không đọc (R2.13, R2.14;
  agent-lifecycle:R1.6, agent-lifecycle:R2.8); ticket đăng ký một loại INSERT một dòng nêu cờ đó trong migration của
  nó, cùng lúc với mục `ArtifactKindRegistry`; `dw_app` chỉ SELECT.
- `studio.artifacts`: `id` UUIDv7; `uq_artifacts_tenant_id_id UNIQUE (tenant_id, id)`, như `uq_workspaces_tenant_id_id`,
  đích của FK ghép `(tenant_id, <cột thành phần>)` trỏ tới thành phần: của spec này là `artifact_id` của
  `studio.artifact_versions`, `from_artifact_id` và `to_artifact_id` của `studio.dependencies` (R2.18); FK của spec
  khác, ví dụ `studio.agent_settings` của agent-builder hay `scope_artifact_id` của usage-and-limits, do spec tạo FK
  làm chủ cùng ca âm chéo tenant của nó; `kind` FK tới `studio.artifact_kinds (kind)` ON DELETE RESTRICT, có index
  `(kind)`, vì index danh sách dẫn bằng `tenant_id`; `api_name` `^[a-z][a-z0-9_]{1,39}$`, unique
  `(tenant_id, kind, api_name)` khi `deleted_at IS NULL`; FK ghép `(tenant_id, owning_workspace_id)` tới
  `platform.workspaces (tenant_id, id)` ON DELETE RESTRICT, qua `uq_workspaces_tenant_id_id` do org-and-principals/01
  tạo, có index `(tenant_id, owning_workspace_id)` (R2.18); trigger `studio.refuse_owning_workspace_change()` từ chối
  mọi lệnh đổi `owning_workspace_id` (R2.19); `labels text[] NOT NULL DEFAULT '{}'` (bộ lọc `label` của danh sách
  đọc); `origin jsonb` NULL (domain-packs ghi và đọc nguồn gốc gói); `last_version_no integer NOT NULL DEFAULT 0`;
  `row_version integer NOT NULL`; `deleted_at timestamptz` NULL; `created_at`, `updated_at` `timestamptz NOT NULL`;
  hai index danh sách mang trọn thứ tự trang `updated_at DESC, id DESC` của `GET /api/v1/studio/artifacts`:
  `(tenant_id, kind, updated_at DESC, id DESC)` khi lọc theo `kind`, và `(tenant_id, updated_at DESC, id DESC)` khi
  không lọc `kind` (trang `/studio`).
- `studio.artifact_versions`: `stage` NOT NULL CHECK (`draft`, `evaluating`, `awaiting_approval`,
  `live`, `retired`), không DEFAULT; `version_no` NULL chỉ khi `stage = 'draft'`, unique
  `(artifact_id, version_no)`; một phiên bản chưa phát hành mỗi thành phần: chỉ mục duy nhất một phần trên
  `(artifact_id)` khi `stage IN ('draft', 'evaluating', 'awaiting_approval')` (R2.20), còn chỉ mục một Đang dùng
  (`WHERE stage = 'live'`) là của agent-lifecycle (agent-lifecycle:R1.2); `document_schema`
  `^dw\.[a-z_]+/v[0-9]+$`; `document` là jsonb object tối đa 1 MiB, `CHECK (document::text IS NFC NORMALIZED)`;
  `content_hash`, `definition_hash` khớp `^sha256:[0-9a-f]{64}$`, `definition_hash` NOT NULL ngoài
  `draft`; `row_version integer NOT NULL`; `artifact_id` FK ghép `(tenant_id, artifact_id)` tới
  `uq_artifacts_tenant_id_id` ON DELETE CASCADE, có index `(tenant_id, artifact_id)`;
  `uq_artifact_versions_tenant_id_id UNIQUE (tenant_id, id)`, đích của FK ghép `(tenant_id, <cột phiên bản>)` trỏ tới
  phiên bản: của spec này là `based_on_version_id` của chính bảng này, `from_version_id` và `to_version_id` của
  `studio.dependencies`, `artifact_version_id` của `platform.run_manifest_keys` (R2.18); FK của spec khác, ví dụ
  `version_id` của `studio.version_assessments` (compliance-pdpl), do spec tạo FK làm chủ cùng ca âm chéo tenant của
  nó; `based_on_version_id` FK ghép `(tenant_id, based_on_version_id)` `ON DELETE SET NULL (based_on_version_id)`, chỉ
  đặt NULL cột đó vì `tenant_id` NOT NULL, có index `(tenant_id, based_on_version_id)`; `change_note` NULL.
- `studio.definition_manifests`: khóa chính `(tenant_id, hash)`, `body` jsonb NFC tối đa 1 MiB, ứng dụng chỉ
  INSERT, DELETE chỉ ở lượt xóa của offboarding (R3.8).
- `studio.dependencies`: `from_version_id` FK ghép `(tenant_id, from_version_id)` và `from_artifact_id` FK ghép
  `(tenant_id, from_artifact_id)`, cả hai ON DELETE CASCADE; `to_kind` CHECK (`artifact`, `field`, `picklist_value`,
  `platform_artifact`, `connector`, `mcp_tool`, `binding`, `node_type`); `to_key`, `to_version`, `to_hash`;
  `to_artifact_id` FK ghép `(tenant_id, to_artifact_id)` và `to_version_id` FK ghép `(tenant_id, to_version_id)`, cả
  hai ON DELETE RESTRICT; mỗi FK ghép một index `(tenant_id, <cột>)`; `usage` CHECK (`read`, `write`, `compare`,
  `invoke`, `bind`, `display`); `path` con trỏ JSON; index `(tenant_id, to_kind, to_key)`; `to_field_id` và FK ghép
  `(tenant_id, to_field_id)` của nó, ON DELETE RESTRICT, có index `(tenant_id, to_field_id)` (ADR-0109 (Accepted)
  quyết 5), do custom-objects thêm cùng bảng field.
- `platform.worker_runs`: `run_mode text NOT NULL` CHECK (`live`, `test`, `simulate`), không DEFAULT,
  dòng cũ backfill `live`; `run_manifest_hash` NULL, khớp `^sha256:[0-9a-f]{64}$`, FK
  `(tenant_id, run_manifest_hash)` tới `platform.run_manifests` ON DELETE RESTRICT, có index
  `(tenant_id, run_manifest_hash)`.
- `platform.tool_executions.status`: CHECK `ck_tool_executions_status` của runtime-hardening/01 (`succeeded`, `failed`,
  `dispatched`, `outcome_unknown`; runtime-hardening:R6.3) thêm `simulated`, giữ đủ bốn giá trị đó.
- `platform.run_manifests`: khóa chính `(tenant_id, hash)`, `body` jsonb NFC tối đa 1 MiB, ghi bằng
  `INSERT ... ON CONFLICT DO NOTHING`; trên bảng này và `platform.run_manifest_keys`, `dw_app` SELECT, INSERT, và
  DELETE chỉ ở lượt xóa của offboarding (R3.8). `platform.run_manifest_keys`: FK ghép
  `(tenant_id, manifest_hash)` tới bản kê ON DELETE CASCADE, có index dẫn bằng hai cột đó qua unique
  `(tenant_id, manifest_hash, artifact_version_id)` bên dưới; `artifact_version_id` FK ghép
  `(tenant_id, artifact_version_id)` tới `uq_artifact_versions_tenant_id_id` và `config_version_id` FK ghép
  `(tenant_id, config_version_id)` tới `uq_config_versions_tenant_id_id`, cả hai ON DELETE RESTRICT, mỗi FK ghép một
  index; CHECK `num_nonnulls(artifact_version_id, config_version_id) = 1`, nên `artifact_version_id`, NOT NULL ở
  ticket 04, bỏ NOT NULL ở ticket 05 cùng bước thêm `config_version_id`; unique
  `(tenant_id, manifest_hash, artifact_version_id)` và `(tenant_id, manifest_hash, config_version_id)`.
- `platform.config_versions`: `uq_config_versions_tenant_id_id UNIQUE (tenant_id, id)`, đích của FK ghép
  `config_version_id` của `platform.run_manifest_keys` (R2.18); `kind` CHECK (`binding_set`); `key` là id thành phần;
  `action` CHECK (`set`); `version_no` tăng theo khóa, không dùng lại; `base_version`; `document` jsonb object tối đa
  256 KiB, NFC; `document_hash`; `status` CHECK (`proposed`, `approved`, `rejected`, `withdrawn`, `superseded`);
  partial unique một `approved` và một `proposed` mỗi khóa; `workspace_id` là nơi đề xuất; FK ghép
  `(tenant_id, workspace_id, approval_id)` tới `platform.approval_requests` ON DELETE RESTRICT, qua
  `uq_approval_requests_tenant_id_workspace_id_id`, có index `(tenant_id, workspace_id, approval_id)` (R8.16);
  `ck_config_versions_checker_not_maker`; trigger `approved_by_approval`; `dw_app` chỉ UPDATE `status`, `decided_by`,
  `decided_at`, `decision_comment`, `superseded_at`, và DELETE chỉ ở lượt xóa của offboarding (R3.8).

## API

- `POST /api/v1/studio/artifacts` (tạo kèm nháp), `GET /api/v1/studio/artifacts` (keyset theo
  `updated_at DESC, id DESC`, lọc `kind`, `label`), `GET /api/v1/studio/artifacts/{id}`,
  `PATCH /api/v1/studio/artifacts/{id}` (`api_name`, `labels`; `If-Match`), `PUT /api/v1/studio/artifacts/{id}/draft`
  (`If-Match`; thiếu thì 428), `POST /api/v1/studio/artifacts/{id}/draft` (tạo bản Nháp từ phiên bản Đang dùng, hay
  phiên bản có `version_no` lớn nhất khi không có bản Đang dùng; R2.21, R2.22, R2.23),
  `GET /api/v1/studio/artifacts/{id}/versions`, `GET /api/v1/studio/artifacts/{id}/versions/{version_no}`,
  `DELETE /api/v1/studio/artifacts/{id}` (xóa mềm), `GET /api/v1/studio/artifacts/{id}/dependents`,
  `GET /api/v1/studio/artifacts/{id}/draft/dependencies`.
- `GET /api/v1/studio/artifacts/{id}/bindings`, `POST /api/v1/studio/artifacts/{id}/bindings/proposals`,
  `POST /api/v1/studio/artifacts/{id}/bindings/proposals/{config_version_id}/withdraw`.
- Lỗi theo vỏ problem+json của ADR-0108 (Accepted); `details.reason_code`: `stale_version`,
  `api_name_taken`, `api_name_immutable`, `candidate_pending`, `draft_exists`, `artifact_in_use`, `no_checker_available`,
  `second_person_required`, `proposal_open`, `decision_stale`, `binding_unset`, `binding_degraded`. `Idempotency-Key`
  theo ADR-0108 (Accepted) quyết 4.

## Kiểm soát

| #    | Kiểm soát                                                                                                                                                          | Yêu cầu                                        | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| TC1  | Nội dung phiên bản chỉ đổi khi ở `draft`                                                                                                                           | R2.9                                           | `dw_app` UPDATE `document` của phiên bản `live` → trigger từ chối; gỡ trigger → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| TC2  | Số phiên bản cấp tuần tự, không cấp lại                                                                                                                            | R2.7, R2.8                                     | Hai lần niêm phong đồng thời một nháp → một thành công, không số nào cấp hai lần; phiên bản quay về `draft` rồi niêm phong lại → số mới; bỏ khóa dòng `last_version_no` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| TC3  | Một nháp mỗi thành phần, khóa lạc quan                                                                                                                             | R2.5, R2.17                                    | `PUT` nháp với `If-Match` cũ → 412 `stale_version`, nháp không đổi; INSERT nháp thứ hai → lỗi partial unique; niêm phong với `row_version` cũ, tức lệnh gửi mang `If-Match` cũ → `stale_version`, không số phiên bản nào; bỏ so `row_version` ở `PUT` hay ở `seal` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| TC4  | Tên API bất biến sau lần phát hành đầu                                                                                                                             | R2.10                                          | `PATCH` `api_name` khi đã có phiên bản từng `live` → 409 `api_name_immutable`; UPDATE thẳng bằng `dw_app` → trigger từ chối                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| TC5  | Không xóa thành phần đang được dùng                                                                                                                                | R3.3                                           | Xóa mềm đối tượng mà phiên bản `live` của một quy trình ở workspace khác dùng → 409 `artifact_in_use`; DELETE cứng khi công ty ở `offboarding` mà dòng phụ thuộc còn → lỗi FK; gỡ trigger → test xóa mềm đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| TC6  | Nơi đang dùng ghi cùng giao dịch niêm phong                                                                                                                        | R3.1                                           | Lỗi chèn giữa giao dịch niêm phong → không số phiên bản, không dòng phụ thuộc; làm hỏng bộ trích xuất của loại fixture → test fixture đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| TC7  | Nơi đang dùng không lộ tên ngoài quyền                                                                                                                             | R3.4                                           | Người chỉ đọc được ở ws1 thấy tên bên phụ thuộc ở ws1, phần ở ws2 chỉ là số đếm; tenant B → 404                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| TC8  | Một hàm dạng chuẩn, đóng khi lỗi                                                                                                                                   | R1.1, R1.2, R1.3, R1.4, R1.5                   | `{"a": 1.0}`, `2**53`, chuỗi NFD → đúng mã lỗi, không mã băm; đổi thứ tự sắp khóa sang code point → test vi sai đỏ trên khóa ngoài BMP                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| TC9  | Chế độ chạy do máy chủ đặt, cột không mặc định, lượt con không nới                                                                                                 | R4.1, R4.2, R4.4                               | INSERT `worker_runs` thiếu `run_mode` → lỗi NOT NULL; `RunContext` dựng không chế độ gọi công cụ `external` → bị giả lập; cha `simulate`, con xin `live` → `simulate`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| TC10 | Tiếp tục lượt chạy giữ chế độ                                                                                                                                      | R4.5                                           | Lượt `simulate` chờ duyệt một công cụ `simulate_safe` đòi phê duyệt rồi tiếp tục → công cụ `external` gọi sau đó vẫn giả lập; bỏ `run_mode` khỏi chỗ dựng lại ngữ cảnh khi tiếp tục → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| TC11 | Executor giả lập ở `simulate` và `test`, trước bước phê duyệt                                                                                                      | R5.1, R5.2, R5.3, R5.5, R5.6                   | Gọi thẳng ToolExecutor, không qua node, với công cụ `external` ở `simulate` → handler không chạy, `status` `simulated`, audit `tool.simulated`; công cụ `critical` đòi phê duyệt ở `simulate` → giả lập, không yêu cầu phê duyệt nào; gỡ bước chế độ, hay đặt nó sau bước phê duyệt → test đỏ; sau revision của ticket 03, INSERT `dispatched` và `outcome_unknown` vẫn được nhận, tập mới thiếu một trong hai → ca nhận đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| TC15 | Bản kê ghim, không lùi về bản hiện hành, không bị dọn, không bí mật                                                                                                | R6.3, R6.4, R6.5, R7.4, R7.5                   | Niêm phong phiên bản mới khi lượt chạy chờ duyệt → lượt tiếp tục với bản ghim; khóa không ghim → bị từ chối; công ty ở `offboarding`, DELETE phiên bản được ghim → lỗi FK; token mẫu và khóa `secret_version` không có trong `body`, mô hình bản kê với một mục `secret_version` → lỗi kiểm `extra="forbid"`; lượt `simulate` trên bản Nháp, lưu nháp rồi tiếp tục → phân giải gốc bị từ chối, nội dung mới không chạy                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| TC16 | Người đề xuất không tự duyệt                                                                                                                                       | R8.8                                           | Người đề xuất quyết → 409 `conflict` với `second_person_required`; người yêu cầu tự quyết một yêu cầu `memory.review` → cùng mã, vì tiền tố nghiêm đặt mã một lần cho mọi loại; UPDATE `decided_by = proposed_by` → CHECK từ chối; bỏ `config.` khỏi prefix nghiêm → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| TC17 | Có hiệu lực chỉ qua yêu cầu phê duyệt đã duyệt, quyết toán một lần, audit đứng tên người quyết                                                                     | R8.10, R8.11, R8.12, R8.15                     | UPDATE `status = 'approved'` khi yêu cầu còn `pending` → trigger từ chối; `dw_app` UPDATE `document` → permission denied; giao lại sự kiện → không dòng, không audit mới; audit `config.version.approved` và `config.version.rejected` mang actor là `decided_by` và `details.lane` `outbox`, ghi actor `system:outbox` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| TC18 | Một đề xuất mở, luôn có người duyệt khác                                                                                                                           | R8.5, R8.6                                     | Đề xuất thứ hai cùng khóa → 409 `proposal_open`; workspace chỉ Người đề xuất giữ quyền duyệt → 409 `no_checker_available`; không dòng nào được ghi                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| TC19 | Chỉ loại đã đăng ký, không sang tenant khác                                                                                                                        | R8.3, R8.7                                     | Đề xuất loại `prompt` → 422, ghi thẳng → CHECK `kind` từ chối; tenant B đọc hay đề xuất trên thành phần của tenant A → 404                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| TC20 | Quyết định cũ bị từ chối, quyết toán không ghi đè                                                                                                                  | R8.9, R8.11                                    | Niêm phong phiên bản đổi khai báo điểm gắn giữa đề xuất và quyết định → 409 `decision_stale`, yêu cầu vẫn `pending`; gỡ guard → test đỏ; tắt kết nối của đề xuất, hay thu hồi `connections.use` của Người đề xuất ở workspace của đề xuất, giữa đề xuất và lúc duyệt → duyệt nhận 409 `decision_stale`, yêu cầu vẫn `pending`; bỏ lần hỏi lại lúc duyệt → test đỏ; quyết toán gặp bản khác đã duyệt → `rejected`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| TC21 | Offboarding xóa hết dữ liệu Studio của tenant                                                                                                                      | R3.6                                           | Tenant có hai thành phần phụ thuộc nhau, bản kê và phiên bản cấu hình riêng → purge xong, tenant khác nguyên; gỡ một mục thứ tự → test đỏ; đặt `studio.dependencies` sau `studio.artifact_versions` → test phủ offboarding đỏ, nêu FK ghép của `to_version_id` (studio-skeleton:R4.2); thu DELETE của `dw_app` trên một bảng của R3.8 → test phủ offboarding đỏ, nêu tên bảng (studio-skeleton:R4.1, studio-skeleton:R4.3)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| TC22 | Không gửi hay phát hành, không nhận lượt chạy khi điểm gắn thiếu hay hỏng                                                                                          | R7.2, R7.3                                     | Phiên bản thiếu giá trị `zalo_oa` → `PublishBindingsCheck` trả `binding_unset` nêu `zalo_oa`; gỡ kiểm `required` → test đỏ; kết nối bị thu hồi → nhận lượt chạy bị từ chối `binding_degraded`, không node nào chạy                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| TC23 | Tài liệu không chứa id kết nối                                                                                                                                     | R7.1                                           | Niêm phong tài liệu có UUID của một kết nối ở chỗ tên điểm gắn → 422 có con trỏ; gỡ kiểm → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| TC24 | Mỗi route thành phần kiểm tenant và quyền theo độ sâu, bằng khóa của loại                                                                                          | R2.11, R2.12, R2.15                            | Người chỉ đọc được ở ws1 GET thành phần của ws2 ngoài độ sâu → 404; `PUT` nháp không có quyền ghi → 403; tenant B → 404; test tham số hóa theo mọi loại đã đăng ký, gồm `workflow` khi workflow-engine:R1.5 đăng ký nó: thiếu `studio.workflows.read` → 404, có khóa đọc mà thiếu `studio.workflows.edit` → `PUT` nháp 403; mục registry thiếu một trong ba khóa hay móc phát hành, hay khai khóa không có trong danh mục quyền → test registry đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| TC25 | Chỉ người có quyền đề xuất và dùng được kết nối mới đề xuất được                                                                                                   | R8.2, R8.4                                     | Thiếu `studio.bindings.propose` → 403; kết nối Người đề xuất không dùng được → 422; không dòng nào được ghi                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| TC26 | Chỉ Người đề xuất rút được đề xuất                                                                                                                                 | R8.14                                          | Người khác gọi `withdraw` → 403, đề xuất và yêu cầu phê duyệt không đổi; bỏ so `proposed_by` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| TC27 | Cờ cổng ở một cột không DEFAULT; niêm phong như nhau cho mọi loại, không chuyển giai đoạn và không đổi phiên bản khác; một phiên bản chưa phát hành mỗi thành phần | R2.7, R2.13, R2.14, R2.16, R2.20, R2.22, R2.23 | INSERT dòng `studio.artifact_kinds` không nêu `has_quality_gate` → lỗi NOT NULL; thêm DEFAULT cho cột → test đỏ; niêm phong nháp `fixture` (`true`) và nháp `fixture_gateless` (`false`) → cả hai có số phiên bản và hai mã băm, `stage` vẫn `draft`, không yêu cầu phê duyệt nào; để `seal` đổi `stage` theo `has_quality_gate` → test đỏ; `fixture_gateless` có một phiên bản `live`, niêm phong một nháp mới của cùng thành phần → dòng `live` giữ nguyên giai đoạn và mọi cột; để `seal` đổi dòng đó → test đỏ; `fixture_gateless` có một Bản ứng viên ở `awaiting_approval`, tạo bản Nháp → 409 `candidate_pending`, không dòng nào; `dw_app` INSERT thẳng một dòng `draft` cạnh Bản ứng viên đó → chỉ mục duy nhất một phần từ chối; tạo bản Nháp khi đã có bản Nháp → 409 `draft_exists`, bản Nháp không đổi; hai lệnh tạo bản Nháp đồng thời → một 201, một 409 `draft_exists`; bỏ kiểm Bản ứng viên ở route, bỏ khóa dòng thành phần, hay thu chỉ mục về `stage = 'draft'` → test đỏ (bước chuyển giai đoạn theo loại, nhánh chỉ siết `draft → live` và ca duyệt Bản ứng viên rồi về `draft` với `base_changed` là của `LifecycleService` và handler `.decided`, thử ở agent-lifecycle/03 và agent-lifecycle/04: AL4, AL19) |
| TC28 | Chỉ lượt `simulate` chạy bản Nháp; lượt khác không dùng mã băm tạm                                                                                                 | R6.1, R6.7                                     | Nhận lượt `live` hay `test` có gốc `draft` → từ chối, không dòng `platform.run_manifests`, không node nào chạy; lượt `simulate` trên bản Nháp → bản kê ghim giai đoạn `draft` và mã băm tạm bằng mã băm mà bước niêm phong cho cùng nội dung; bỏ kiểm chế độ → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| TC29 | Không dòng nào trỏ tới thành phần, phiên bản, phiên bản cấu hình, workspace hay yêu cầu phê duyệt của tenant khác                                                  | R2.18, R8.16                                   | Bằng vai migrator, INSERT dòng `studio.dependencies` của tenant A có `to_version_id` là phiên bản của tenant B → lỗi FK; cùng ca với `from_version_id`, `based_on_version_id` và `platform.run_manifest_keys.artifact_version_id`; cùng ca với thành phần của tenant B qua `artifact_id` của `studio.artifact_versions`, `from_artifact_id` và `to_artifact_id`, và với phiên bản cấu hình của tenant B qua `platform.run_manifest_keys.config_version_id`; INSERT `studio.artifacts` của tenant A có `owning_workspace_id` là workspace của tenant B → lỗi FK; INSERT `platform.config_versions` của tenant A có `approval_id` là yêu cầu phê duyệt của tenant B → lỗi FK; đổi một FK ghép về FK một cột → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| TC30 | Workspace sở hữu của thành phần không đổi                                                                                                                          | R2.19                                          | `dw_app` UPDATE `owning_workspace_id` của một thành phần sang workspace khác cùng tenant → trigger từ chối; cùng lệnh bằng vai migrator → trigger từ chối; UPDATE `labels` của cùng dòng → được; gỡ trigger → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| TC31 | Chỉ lượt xóa của offboarding xóa cứng định nghĩa, bản kê và phiên bản cấu hình                                                                                     | R3.8                                           | `dw_app` DELETE một dòng của mỗi bảng của R3.8 thuộc công ty `active` → 23514, dòng còn; cùng lệnh khi công ty ở `offboarding` → xóa được; gỡ phép kiểm trạng thái khỏi trigger → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| TC32 | Bản kê ghim độ bền checkpoint `sync`                                                                                                                               | R6.8                                           | Bản kê của một lượt gốc `fixture` có `engine.durability` `sync`; dựng mô hình bản kê với `async`, hay thiếu `durability` → lỗi kiểm, không dòng `platform.run_manifests`; đổi kiểu của trường thành chuỗi tự do → ca `async` được nhận, test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |

## Tiêu chí xong

- Mọi tiêu chí R và G có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (ghi ở Comments
  của ticket).
- `make ci && make test-integration` xanh; `reviewing-feature-security` đã chạy trên từng ticket;
  `.claude/plans/studio.md` ghi lát W1 đã xong.

## Phụ thuộc

- `.claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md`: gói `dw_studio`, nhóm
  route `/api/v1/studio`, schema `studio` có USAGE và default privileges (studio-skeleton/01).
- `.claude/plans/studio/runtime-hardening/issues/01-toolexecutor-gianh-luot-khong-cua-sau.md`:
  executor giành lượt trước và CHECK `tool_executions.status` mà ticket 03 mở rộng.
- `.claude/plans/studio/connections-and-vault/issues/04-ket-noi-dung-chung-theo-workspace.md`:
  `platform.connections` và `connection_usable` cho ticket 05, hàm này kiểm cả `connections.use` ở workspace của
  lượt chạy và nhận `purpose` ngay từ W1, ticket 05 gọi với `tool` lúc đề xuất, lúc duyệt và lúc nhận lượt chạy (R8.4,
  R8.9, R7.3; connections-and-vault:R5.9; ADR-0115 (Accepted) quyết 2); bản kê không ghim `secret_version`: lời gọi
  egress phân giải phiên bản mới nhất chưa bị thu hồi của kết nối lúc gọi và ghi nó vào
  `platform.tool_executions.credential_version`, cột mà connections-and-vault làm chủ, cùng luật thu hồi vì lộ dừng lượt
  với `credential_revoked` (R7.4, R7.5; ADR-0109 (Accepted) quyết 6; ADR-0115 (Accepted) quyết 1; V4.35, H-10, H-28);
  connections-and-vault/03 cho egress client ở chế độ khác `live`, từ chối mọi purpose trừ `model` và Hành động chỉ
  đọc hay `simulate_safe` (ADR-0115 (Accepted) quyết 6), nên R5.4 không đổi.
- `.claude/plans/studio/org-and-principals/issues/01-khoa-don-vi-va-siet-realm.md`: tạo
  `uq_workspaces_tenant_id_id` cho FK ghép của `studio.artifacts`; ticket 02 không tạo ràng buộc đó (OPS-a.2).
- `.claude/plans/studio/runtime-hardening/issues/03-run-va-outbox-khong-ket.md`: CHECK `status` của yêu
  cầu phê duyệt và đường tiếp tục ở `approval_flow.py` mà ticket 05 đổi sau (OPS-b), và `ck_worker_runs_status`
  trên `platform.worker_runs` có trước cột `run_manifest_hash` của ticket 04 (C:runtime-hardening/03~tenant-config/04).
- `.claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md`: viết lại
  `_CATALOG_COLUMNS`, `export_rows` và `test_offboarding.py`, nơi ticket 02, 04 và 05 thêm ca purge của mình, và dựng sổ
  bước xóa có thứ tự suy từ `pg_constraint` (foundations-hardening:R11.4), nên ba ticket không đăng ký bước nào và không
  khai thứ tự (C:foundations-hardening/07~tenant-rbac/02; H-2).
- studio-skeleton: test phủ offboarding (studio-skeleton:R4.1, studio-skeleton:R4.2, studio-skeleton:R4.3), mà sáu bảng
  của R3.8 và `studio.dependencies` qua bằng DELETE của `dw_app` và thứ tự mà sổ bước xóa suy từ các cạnh RESTRICT của
  `pg_constraint` (studio-skeleton:R4.2; foundations-hardening:R11.4), không bằng dòng `STUDIO_EXCLUSIONS` nào; trigger của
  R3.8 đọc trạng thái `offboarding`, mà không câu lệnh nào đưa công ty về `active` hay `locked`
  (foundations-hardening:R3.2).
- tenant-rbac: khóa `studio.<area>.<verb>` theo luật đặt tên của tenant-rbac:R1.6, đăng ký trong migration của cụm
  (tenant-rbac/01), độ sâu qua `platform.effective_grants` (tenant-rbac/02, ADR-0104 (Accepted) quyết 5), và hàm SQL chung
  `platform.checker_candidates` của tenant-rbac/02 trả người `active` giữ một quyền mà khác Người đề xuất, dùng
  cho `no_checker_available` của cả R8.5 lẫn tenant-rbac:R7.3 (D:tenant-config/05~tenant-rbac:R7.1); hai mã
  `no_checker_available` và `second_person_required` cùng hình 409 `conflict` với tenant-rbac:R7.2 và
  tenant-rbac:R7.3 (ADR-0104 (Accepted) quyết 10-11); ticket chèn dòng vào `platform.permissions` (khóa
  `studio.bindings.*` của ticket 05, khóa của hai loại fixture trong test của ticket 02) chờ tenant-rbac/02 và nêu
  trong INSERT mọi cột NOT NULL có lúc đó, gồm `risk` của tenant-rbac/01 và `tenant_grantable` của tenant-rbac/02
  (ADR-0104 (Accepted) quyết 1).
- app-standards: vỏ problem+json của mọi lỗi (`.claude/plans/studio/app-standards/issues/01-vo-loi-problem-json.md`;
  app-standards:R1.3 cho 422 có `errors[]`) và ETag, `If-Match`, 412, 428
  (`.claude/plans/studio/app-standards/issues/03-quy-uoc-api-danh-sach-va-sua.md`; app-standards:R3.2,
  app-standards:R3.3), hai ticket mà ticket 02 chờ; `Idempotency-Key` gắn người gọi
  (`.claude/plans/studio/app-standards/issues/02-khoa-chong-lap-gan-nguoi-goi.md`; app-standards:R2.1), ticket mà
  ticket 05 chờ (ADR-0108 (Accepted) quyết 3-4).
- agent-lifecycle: `LifecycleService`, bên chuyển giai đoạn trong giao dịch gửi sau bước niêm phong của R2.7
  (`draft → evaluating`, `draft → awaiting_approval`, `draft → live`; agent-lifecycle:R2.1, agent-lifecycle:R2.8,
  agent-lifecycle:R2.9), và `studio.guard_version_stage()`, hàng rào cuối, với luật theo loại: `draft` sang
  `awaiting_approval` cho loại không có Cổng chất lượng (agent-lifecycle:R1.6), và nhánh chỉ siết `draft` sang `live`
  với cột `tighten_only` cùng `compared_live_hash` mà lệnh gửi tính bằng bộ so sánh của loại (agent-lifecycle:R1.7,
  agent-lifecycle:R2.8, agent-lifecycle:R2.9; custom-objects:R1.7, custom-objects:R1.8; R2.16); mọi lệnh gửi ghi
  `compared_live_hash`, `definition_hash` của bản `live` lúc so (agent-lifecycle:R2.10), `awaiting_approval → live`
  chỉ khi nó vẫn là mã băm của phiên bản Đang dùng mà lần phát hành thay (gỡ trong cùng giao dịch), hay cùng NULL khi
  không có bản nào (agent-lifecycle:R1.8), và handler `.decided` đưa Bản ứng viên có gốc đã đổi về `draft` với
  `details.reason_code` `base_changed` (agent-lifecycle:R5.9; ADR-0120 (Accepted) quyết 1-2); lệnh gửi `POST .../submit`
  (agent-lifecycle:R2.1) kiểm khóa gửi mà R2.15 khai và nhận `If-Match` là ETag của bản Nháp, giá trị nó đưa cho bước
  niêm phong làm `row_version` mong đợi (412 `stale_version` khi lệch, 428 khi thiếu; agent-lifecycle:R2.12,
  agent-lifecycle:R2.13; R2.17); giao dịch phát hành của handler `.decided` và của nhánh chỉ siết gọi móc phát hành mà
  R2.15 khai (agent-lifecycle:R2.9, agent-lifecycle:R5.5); lệnh rút `POST .../withdraw` đưa Bản ứng viên về Nháp
  (agent-lifecycle:R2.4), đường người dựng tự gọi để sửa khi một Bản ứng viên còn chờ (R2.22); chỉ mục một Đang dùng
  (agent-lifecycle:R1.2) bên cạnh chỉ mục một phiên bản chưa phát hành của R2.20; mục `studio.gate_runs` mà
  agent-lifecycle tạo đứng giữa `studio.artifact_versions` và `studio.artifacts` trong thứ tự xóa mà sổ bước xóa suy
  ra, vì `studio.artifact_versions.gate_run_id` và `studio.gate_runs.artifact_id` là FK RESTRICT (agent-lifecycle:R10.2;
  foundations-hardening:R11.4).
- custom-objects: loại phê duyệt `studio.publish.object` là của custom-objects (custom-objects:R1.2;
  ADR-0120 (Accepted) quyết 2; R2.13), và móc phát hành của loại `object` là dịch vụ metadata (custom-objects:R1.1;
  R2.15).
- workflow-triggers: loại `endpoint` (Nguồn dữ liệu) là loại không có Cổng chất lượng, với phê duyệt
  `studio.publish.endpoint` đóng dấu `studio.publish.approve` và không bộ so sánh chỉ siết nào (ADR-0120 (Accepted)
  quyết 1-2; R2.13); workflow-triggers cấp móc phát hành của loại `endpoint` (R2.15).
- workflow-engine: loại `workflow` khai khóa của loại và cấp móc phát hành của loại đó (workflow-engine:R1.4,
  workflow-engine:R1.5; R2.15); `binding_needs_review` của kind `principal`, do `BindingReviewPort` hỏi ở dispatch và
  đọc `decided_at` của các Bộ giá trị gắn đã duyệt (workflow-triggers:R3.7), không từ chối lượt mà giữ nó ở `queued`
  tới khi Bộ giá trị gắn được duyệt lại, theo hàng của mã đó ở bảng từ chối của workflow-engine (workflow-engine:R5.19),
  và lần giữ báo người giữ `studio.bindings.approve`, khóa duyệt Bộ giá trị gắn của R8.1 (workflow-engine:R5.21; V4.16).
- Protocol do bên dùng khai: `RunManifestPort` (runtime khai, Studio đáp ứng); `PublishBindingsCheck`
  (agent-lifecycle khai, lệnh gửi và handler `.decided` gọi, ticket 05 đáp ứng; R7.2); `RunBindingsPort` (connections-and-vault và handler
  của lượt chạy khai, ticket 05 đáp ứng từ bản kê, ADR-0110 (Accepted)); `ConnectionDependentsPort`
  (connections-and-vault khai, ticket 05 đáp ứng, R3.7); lệnh gửi kiểm định của agent-lifecycle/03 gọi bước
  niêm phong của ticket 02.
- Bảng toàn tenant theo `CLAUDE.md` "Tenancy and authorization", sửa cùng lúc Đạt nhận ADR-0100 (Accepted)
  và DO-01 ngày 23/10/2026: bảng không có `workspace_id` có lý do trong `test_rls_coverage.py` (mục Dữ
  liệu). Hai ghim theo `CLAUDE.md` "Non-negotiable architecture" và "Per-tenant artifacts", sửa cùng lúc Đạt
  nhận ADR-0109 (Accepted) và ADR-0120 (Accepted): release manifest ghim lớp nền tảng, bản kê ghim lượt
  chạy Studio, và thành phần Studio phân giải qua bản kê chứ không qua `TenantOverlay`. Giá trị `test` của
  chế độ chạy không bao giờ được so với profile `test` (`CLAUDE.md` "Environments"); cổng triển khai vẫn đọc
  `settings.is_deployed`.
- Giá trị biến của Bộ giá trị gắn là chữ do tenant viết: prompt nào nội suy nó thì `PromptRegistry` bọc
  như mọi biến (ADR-0010 (Accepted)); spec này chỉ kiểm kiểu và chỉ ghim mã băm của nó.
- Kiểm lại khi: tenant-rbac đổi cách tính quyền (DO-09) hay đổi hàm tìm người duyệt chung → ticket 02, 04, 05;
  agent-lifecycle/03 đổi hợp đồng niêm phong, bên chuyển giai đoạn sau bước niêm phong, cột `stage`, cột `tighten_only`
  hay luật chuyển giai đoạn của loại không có Cổng chất lượng → R2.7, R2.13, R2.16, TC27, ticket 02; agent-lifecycle
  đổi luật `compared_live_hash`, cách đưa Bản ứng viên về `draft` (lệnh rút, `base_changed`) hay chỉ mục một Đang dùng
  → R2.16, R2.20, R2.22, TC27; agent-lifecycle hay một spec khác thêm hay bỏ một FK RESTRICT tới thành phần hay phiên
  bản → thứ tự xóa ở Dữ liệu, TC21, ticket 02; workflow-triggers hay workflow-engine đổi cách giữ lượt
  `binding_needs_review` → Phụ thuộc, ticket 05; agent-lifecycle đổi điều kiện ghi của lệnh gửi hay chỗ gọi móc phát
  hành → R2.15, R2.17, ticket 02; app-standards
  đổi vỏ lỗi, ETag hay `Idempotency-Key` → ticket 02, 05; một bảng mới của spec này trỏ tới một bảng theo tenant → FK
  ghép và ca âm chéo tenant như R2.18, R8.16, TC29 (FK của spec khác tới bảng của spec này do spec tạo FK làm chủ);
  ADR-0115 (Accepted) quyết 1 thôi gắn `owning_workspace_id` vào AAD → R2.19, TC30; workflow-triggers đổi vòng đời
  của loại `endpoint` → R2.13; custom-objects đổi bộ so sánh chỉ siết → R2.16; workflow-triggers hay workflow-engine
  đổi việc nhận phiên bản `draft` ở chế độ `simulate` hay kiểm khi tiếp tục lượt đó → R6.1, R6.7, TC28, ticket 04;
  tenant-rbac đổi cột NOT NULL của `platform.permissions` → ticket 02, 05; foundations-hardening/07 đổi
  `test_offboarding.py` hay danh mục xuất → ticket 02, 04, 05; studio-skeleton đổi test phủ offboarding hay cách nó
  đọc thứ tự xóa → R3.8, TC21, TC31, ticket 02, 04, 05; một lane của W2 xóa phiên bản, bản kê hay đề xuất theo lưu
  giữ → R3.8, TC31, trigger của ticket 02; tools-and-skills đổi thứ tự bước của `ToolExecutor`
  → R5.6, ticket 03; `connection_usable` đổi hình, hay connections-and-vault đổi cách lời gọi phân giải phiên bản bí
  mật lúc gọi → R7.4, R7.5, R8.9, ticket 05; workflow-engine đổi cách truyền `durability` hay ADR-0109 (Accepted)
  quyết 8 đổi mục `engine` → R6.8, TC32, ticket 04; runtime-hardening đổi tập của `ck_tool_executions_status` → ticket 03;
  foundations-hardening/07 đổi cách suy thứ tự xóa → Dữ liệu, TC21, ticket 02, 04, 05; một node W1 gửi thông báo qua kênh chat từ lượt không `live` → TC12-TC14 kéo về W1.

## Câu hỏi còn mở

## Quyết định

- 22/10/2026 (người yêu cầu): D1: workspace là đơn vị sở hữu dữ liệu nên không bao giờ là môi trường;
  môi trường của v1 là phiên bản cộng chế độ chạy (ADR-0111 (Accepted) quyết 6). Sửa: R4, R5.
- 23/10/2026 (người yêu cầu): D11 (DO-07): mọi thay đổi cấu hình của tenant cần Người đề xuất và một
  Người duyệt khác; tenant không có người duyệt thứ hai thì không đề xuất được. Sửa: R8.5, R8.8.
- 23/10/2026 (agent, tạm): DO-08 theo khuyến nghị (a): Tên API bất biến sau lần phát hành đầu; đổi tên
  là thành phần mới cộng migration. Sửa: R2.10. Nếu sai thì: một bảng bí danh cho một thành phần hai tên
  trong gói và trong Nơi đang dùng (ADR-0109 (Accepted) Open 2).
- 23/10/2026 (agent, tạm): DO-26 theo khuyến nghị (a): giữ giá trị `test` với `RunMode` có kiểu và
  bảng thuật ngữ; ở W1 executor giả lập lượt `test` như `simulate`, ghi bản ghi trong `test` bị giả lập,
  vùng nháp theo lượt chạy ở v1.5. Sửa: R5.1. Nếu sai thì: (b) bản ghi thật gắn nhãn `test` cần lane
  dọn và bộ lọc ở mọi danh sách; (c) dựng ngay vùng nháp theo lượt chạy và đổi giá trị thành `trial`.
- 23/10/2026 (agent, tạm): cột `stage` được tạo ở migration vỏ phiên bản của ticket 02 (CHECK năm giai
  đoạn của ADR-0120 (Accepted), không DEFAULT) vì trigger bất biến và chỉ mục một nháp đọc nó, và bước
  niêm phong của ticket 02 chuyển nháp sang `evaluating`; trigger chuyển giai đoạn, cột cổng và route
  gửi kiểm định thuộc agent-lifecycle/03, route này gọi bước niêm phong. Sửa: R2.7, R2.9. Nếu sai thì:
  agent-lifecycle/03 tạo cột và bước chuyển, ticket 02 chờ nó.
- 23/10/2026 (agent, tạm): Người đề xuất rút đề xuất qua route riêng, hủy yêu cầu phê duyệt bằng
  `ApprovalRequest.cancel()`, vì prefix nghiêm chặn cả lệnh từ chối của chính người yêu cầu. Sửa:
  R8.13, R8.14. Nếu sai thì: bỏ route; `withdrawn` chỉ do lane hết hạn của W2 ghi.
- 23/10/2026 (agent, tạm): khóa quyền `studio.bindings.propose` và `studio.bindings.approve` theo dạng
  `studio.<area>.<verb>` của tenant-rbac/01. Sửa: R8.1, R8.2, R8.5. Nếu sai thì: đổi tên ở R8 và ticket
  05 theo danh mục của tenant-rbac.
- 23/10/2026 (agent, tạm): với `binding_set`, Phiên bản gốc là `version_no` của phiên bản niêm phong mới
  nhất mà đề xuất được kiểm theo, vì ADR-0110 (Accepted) quyết 7 kiểm theo khai báo đã phát hành mà
  việc phát hành lại cần giá trị đã duyệt trước. Sửa: R8.9. Nếu sai thì: Phiên bản gốc là phiên bản
  `live`, và phiên bản đầu tiên không có khai báo nào để kiểm.
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: ADR-0110 (Accepted) nói phát hành từ chối tài liệu chứa id
  kết nối, ADR-0109 (Accepted) đặt bộ kiểm trả mọi lỗi ở lúc gửi kiểm định; theo lúc niêm phong, vì
  phiên bản đã niêm phong không đổi được nên cũng không phát hành được. Sửa: R7.1.
- 23/10/2026 (Đạt): DO-05 (a): phiên bản của mọi loại nằm trong một vỏ `studio.artifact_versions` với cột
  `stage` của ADR-0120 (Accepted), `live` lưu một lần, không `active_version_id`. Hỏi: Q1. Sửa: ticket 02.
- 23/10/2026 (Đạt): DO-06 (a): tài liệu chỉ giữ tên điểm gắn; giá trị nằm ở Bộ giá trị gắn đã duyệt và
  được ghim theo lượt chạy; giờ của lịch là điểm gắn kind `schedule` khi lịch ra ở W2. Hỏi: Q2. Sửa:
  ticket 05.
- 23/10/2026 (Đạt): DO-01 (a) và ADR-0100 (Accepted): bảng toàn tenant hợp lệ khi có một dòng lý do trong
  `test_rls_coverage.py`, cột chủ sở hữu tên `owning_workspace_id`; `CLAUDE.md` sửa cùng lúc. Sửa: Dữ liệu,
  Phụ thuộc, ticket 02, 04.
- 23/10/2026 (Đạt): ADR-0109 (Accepted) và ADR-0120 (Accepted): hai ghim, release manifest cho lớp nền tảng
  và bản kê cho lượt chạy Studio; bằng chứng kiểm định khóa theo Mã băm hiệu lực. Sửa: Phụ thuộc.
- 23/10/2026 (Đạt): ADR-0107 (Accepted) và DO-08 (a): một luật Tên API cho mọi loại,
  `^[a-z][a-z0-9_]{1,39}$`, bất biến sau lần phát hành đầu, để tên công cụ `ask__<api_name>` và
  `obj_<api_name>__search` không vượt 64 ký tự (ADR-0116 (Accepted)). Sửa: R2.2, Dữ liệu, ticket 02.
- 23/10/2026 (Đạt): OPS-a.2: `uq_workspaces_tenant_id_id` chỉ do org-and-principals/01 tạo; ticket 02 bỏ
  dòng tạo ràng buộc và chờ ticket đó. Sửa: Dữ liệu, Phụ thuộc, ticket 02.
- 23/10/2026 (Đạt): OPS-b: `ck_artifacts_kind` thành FK tới bảng danh mục `studio.artifact_kinds`, mỗi
  ticket đăng ký loại INSERT một dòng; ticket 05 chờ runtime-hardening/03. Sửa: Dữ liệu, ticket 02, 05.
- 23/10/2026 (Đạt): DO-26.1 (A), DO-26.2 (a) và ADR-0111 (Accepted) nguyên văn: W1 chỉ mở `simulate` cho
  chạy thử, route chạy thử của workflow-triggers trả 422 với `test` tới W2; executor vẫn giả lập lượt `test`
  như `simulate` nếu một lượt như vậy tới; giữ tên `test` với `RunMode` có kiểu. Sửa: Ngoài phạm vi, ticket 03.
- 23/10/2026 (người đặt yêu cầu và Đạt): D11 phủ định nghĩa đối tượng, `default_access` và mở trường:
  phiên bản `dw.object/v1` phát hành qua người thứ hai (D:field-security:R1.4~requirements.md:D11), nên
  loại không có Cổng chất lượng đi từ `draft` sang `awaiting_approval`, không qua `evaluating`. Sửa: R2.7,
  R2.13, ticket 02.
- 23/10/2026 (Đạt): công cụ MCP đi qua máy giai đoạn như mọi loại; `tool` là loại không có Cổng chất lượng
  ở W2 (D:mcp-client:R3.4~tenant-config:studio.artifact_versions). Sửa: R2.13.
- 23/10/2026 (Đạt): hai cơ chế hai người có lý do: vai trò theo mẫu ADR-0012 (Accepted) ở tenant-rbac, mọi
  cấu hình khác qua spec này; hai bên dùng chung một hàm SQL tìm người duyệt trên `platform.effective_grants`
  (D:tenant-config/05~tenant-rbac:R7.1). Sửa: Phụ thuộc, ticket 05.
- 23/10/2026 (Đạt): DO-27.1 (a) và DO-27.2 (a): ở W2 công ty ghi đè được prompt nền tảng chỉ khi prompt có
  bên đọc theo công ty, không `raw_variables`, không prompt khung, và ghi đè đổi Mã băm hiệu lực; gỡ
  `platform.policy_overrides` ở W2 cùng lúc kind `policy` ra đời, sau khi đếm 0 dòng ở mọi môi trường. Sửa:
  Ngoài phạm vi.
- 23/10/2026 (Đạt): DO-62 (a): công ty thử nghiệm ở v2 chỉ do người vận hành tạo, chỉ chứa dữ liệu giả lập,
  có hạn mức riêng. Sửa: Ngoài phạm vi.
- 23/10/2026 (Đạt): DO-52 (a): thời hạn lưu giữ là số tạm trong tệp `retention` do telemetry-and-audit/03
  làm chủ; luật sư chốt số trước chạy bóng. Sửa: Ngoài phạm vi.
- 23/10/2026 (Đạt): Kết quả giả lập ghim theo Bước do workflow-nodes làm ở W2; W1 chỉ dùng giá trị sinh từ
  output schema (H:CONTEXT.md#mock-output~workflow-engine:ngoài-phạm-vi). Sửa: R5.3, Ngoài phạm vi, ticket 03.
- 23/10/2026 (agent, tạm): hàm SQL chung tìm người duyệt là `platform.checker_candidates` của tenant-rbac/02,
  nơi tạo `platform.effective_grants`; ticket 05 chờ ticket đó. Sửa: Phụ thuộc, ticket 05. Nếu sai thì: ticket 05
  tạo hàm và tenant-rbac/03 chờ ticket 05.
- 23/10/2026 (agent, tạm): sửa phát hiện `A:connections-and-vault:R5.8~tenant-config:R3.3` và
  `I:connections-and-vault:R6.4~workflow-engine:phụ-thuộc`: spec này đáp ứng `ConnectionDependentsPort` từ Nơi
  đang dùng và `RunBindingsPort` từ bản kê; workflow-engine và agent-builder không cài hai port đó. Sửa:
  R3.7, Trong phạm vi, Phụ thuộc, ticket 05. Nếu sai thì: hai port có chủ khác và R3.7 rút.
- 23/10/2026 (agent, tạm): mục `ArtifactKindRegistry` không nêu Cổng chất lượng thì coi là có cổng, để một
  loại không bỏ qua kiểm định chỉ vì thiếu khai báo (failure-modes #7). Sửa: R2.14, TC27. Nếu sai thì: cờ
  thành bắt buộc và registry từ chối mục thiếu cờ.
- 24/10/2026 (người đặt yêu cầu và Đạt): Q-R6: phiên bản `dw.object/v1` mà bộ so sánh của loại báo chỉ siết (đóng
  trường, thu hẹp `default_access`, bỏ quyền) đi `draft` sang `live` bởi một người có audit, mọi phiên bản có nới
  quyền vẫn qua `awaiting_approval` và người thứ hai; đây là một nhánh của cùng máy giai đoạn ở ADR-0120 (Accepted)
  quyết 1, với cột `tighten_only` và mã băm phiên bản `live` đã so do lệnh gửi của agent-lifecycle tính. Dòng này
  thay phần "loại không có Cổng chất lượng đi từ `draft` sang `awaiting_approval`" của dòng D11 ngày 23/10/2026 cho
  nhánh chỉ siết. Sửa: R2.13, R2.16, TC27, Ngoài phạm vi, Phụ thuộc, ticket 02.
- 24/10/2026 (người đặt yêu cầu và Đạt): D11 cho cấu hình theo ADR-0110 (Accepted) quyết 2: thay đổi nới quyền cần
  Người đề xuất và một Người duyệt khác, thay đổi chỉ siết đi một người có audit; `binding_set` ở W1 không đăng ký
  bộ so sánh nào nên mọi đề xuất `binding_set` qua hai người như R8.8 và R8.12, và nhánh một người ra ở W2 cùng kind
  `policy` với chốt DB riêng (phát hiện F về ADR-0110 (Accepted) và R8.12). Dòng này thay dòng D11 ngày 23/10/2026 "mọi thay đổi
  cấu hình của tenant cần Người đề xuất và một Người duyệt khác". Sửa: Ngoài phạm vi.
- 24/10/2026 (Đạt): `config.version.approved` và `config.version.rejected` audit đứng tên người quyết
  (`decided_by`) với `details.lane` `outbox`, vì lane thi hành quyết định đã ghi của một người (ADR-0011 (Accepted);
  E:CLAUDE.md#agent-and-tool-rules~tenant-config:R8.10). Sửa: R8.10, R8.11, TC17, ticket 05.
- 24/10/2026 (Đạt): cột `has_quality_gate boolean NOT NULL`, không DEFAULT, trên `studio.artifact_kinds`; mỗi ticket
  đăng ký loại nêu cờ trong migration của nó; bước niêm phong và `studio.guard_version_stage()` cùng đọc cột đó, nên
  `ArtifactKindRegistry` không giữ bản sao thứ hai của cờ (B:agent-lifecycle:R1.6~tenant-config:dữ-liệu). Dòng này
  thay dòng tạm ngày 23/10/2026 về mục không nêu cờ. Sửa: R2.14, TC27, Dữ liệu, ticket 02.
- 24/10/2026 (Đạt): mỗi mục `ArtifactKindRegistry` khai khóa đọc, khóa ghi và khóa gửi của loại; R2.11, R2.12 và lệnh
  gửi của agent-lifecycle kiểm đúng các khóa đó; loại `workflow` khai `studio.workflows.read` ở workflow-engine/01
  (`B:tenant-config:R2.11~workflow-engine:trong-phạm-vi`; `B:agent-lifecycle:api~custom-objects:R1.2`). Sửa: R2.15, TC24,
  Trong phạm vi, Phụ thuộc, ticket 02.
- 24/10/2026 (Đạt): người quyết là Người đề xuất nhận 409 `conflict` với `details.reason_code`
  `second_person_required`, cùng hình với `no_checker_available` và với tenant-rbac (ADR-0104 (Accepted) quyết 11;
  B:tenant-config:R8.8~tenant-rbac:R7.2). Sửa: R8.5, R8.6, R8.8, TC16, API, Phụ thuộc, ticket 05.
- 24/10/2026 (Đạt): loại phê duyệt `studio.publish.object` là của custom-objects (custom-objects:R1.2);
  agent-lifecycle giữ `studio.guard_version_stage()` và luật theo loại (A:custom-objects:R1.2~tenant-config:phụ-thuộc).
  Sửa: Phụ thuộc.
- 24/10/2026 (Đạt): N2: ở chế độ `simulate` (và `test` từ W2) bước chế độ chạy của ToolExecutor đứng trước bước phê
  duyệt, nên công cụ không `simulate_safe` bị giả lập mà không mở yêu cầu phê duyệt nào; thứ tự bước do
  tools-and-skills:R2.6 làm chủ (D:workflow-nodes:R9.6~workflow-triggers:R3.3). Sửa: R5.6, TC10, TC11, ticket 03.
- 24/10/2026 (Đạt): egress ở chế độ khác `live` theo ADR-0115 (Accepted) quyết 6: từ chối mọi purpose trừ `model` và
  Hành động chỉ đọc hay `simulate_safe`, nên R5.4 đứng nguyên; `connection_usable` kiểm cả `connections.use` ở
  workspace của lượt chạy (B:connections-and-vault:R3.5~tenant-config:R5.4). Sửa: Ngoài phạm vi, Phụ thuộc.
- 24/10/2026 (Đạt): lượt chạy ở chế độ `simulate` gọi là chạy mô phỏng; "Chạy thử" chỉ gọi chế độ `test`
  (G:CONTEXT.md#run-mode~workflow-triggers:R2.3). Sửa: đoạn mở đầu, R5, Ngoài phạm vi.
- 24/10/2026 (Đạt): khóa quyền theo luật đặt tên mà tenant-rbac làm chủ (tenant-rbac:R1.6); khóa của spec này đã
  theo luật đó. Sửa: Phụ thuộc.
- 24/10/2026 (agent, tạm): kiểm Tiền tố dành riêng ở route tạo thành phần thành một dòng W2 của Ngoài phạm vi
  (H:domain-packs:R3.1~tenant-config:R2.2). Sửa: Ngoài phạm vi. Nếu sai thì: trình cài gói tự kiểm tiền tố và route
  không đổi.
- 24/10/2026 (Đạt): Q2 của domain-packs: cài gói Marketing 1.0 ở W2 vào công ty đã có `mkt_lead`, `mkt_campaign` do
  marketing-pilot/02 gieo thì gắn nguồn gốc gói cho thành phần đang có, chỗ khác phiên bản của gói thành Đề xuất cập
  nhật gói vào bản Nháp, như mọi bản cập nhật gói (H:domain-packs:spec~tenant-config:spec). Sửa: Ngoài phạm vi.
- 24/10/2026 (Đạt): `endpoint` (Nguồn dữ liệu của workflow-triggers) là loại không có Cổng chất lượng như `object` và
  `tool`: phiên bản đi `draft → awaiting_approval → live`, lên `live` khi người thứ hai duyệt phê duyệt
  `studio.publish.endpoint` đóng dấu `studio.publish.approve`; loại này không đăng ký bộ so sánh chỉ siết
  (D:ADR-0120 (Accepted)\~workflow-triggers:spec). Sửa: R2.13, Phụ thuộc.
- 24/10/2026 (Đạt): mọi lần gửi ghi `compared_live_hash`, `definition_hash` của bản `live` lúc so (NULL khi chưa có bản
  `live`); `awaiting_approval → live` chỉ khi nó vẫn là mã băm của phiên bản Đang dùng mà lần phát hành thay (gỡ trong
  cùng giao dịch), hay cùng NULL khi không có bản nào, do `studio.guard_version_stage()` canh; handler `.decided` của
  một phê duyệt đã duyệt mà gốc đã đổi đưa Bản ứng viên về `draft` với `details.reason_code` `base_changed` và một sự
  kiện audit, nên bản chỉ siết lên `live` trong lúc Bản ứng viên chờ không bị thay
  (D:ADR-0120 (Accepted)\~tenant-config:R2.16). Sửa: R2.16, TC27, Ngoài phạm vi, Phụ thuộc, ticket 02.
- 24/10/2026 (Đạt): route `.../versions/{version_id}/test-runs` ở chế độ `simulate` nhận cả phiên bản `draft`; bản
  kê ghim giai đoạn `draft` và mã băm tạm của nội dung nháp lúc nhận yêu cầu, tính bằng cùng bước băm của niêm phong
  (ADR-0109 (Accepted)); lượt chạy chỉ phân giải từ bản kê, nên nháp đổi trước khi lượt mô phỏng xong thì lần tiếp
  tục bị từ chối `incompatible_resume` (ADR-0109 (Accepted) quyết 8); lượt `live` không bao giờ dùng mã băm tạm
  (B:workflow-builder-ui:R3.6~workflow-triggers:R2.8). Sửa: R6.1, R6.7, TC15, TC28, Ngoài phạm vi, Phụ thuộc, ticket 04.
- 24/10/2026 (Đạt): lưu nháp cũ trả 412 `precondition_failed` theo ADR-0108 (Accepted) quyết 3, với
  `details.reason_code` `stale_version`; ADR-0109 (Accepted) quyết 2 bỏ 409 (F:ADR-0109 (Accepted)\~tenant-config:R2.5).
  Sửa: R2.5.
- 24/10/2026 (agent, tạm): ticket chèn dòng vào `platform.permissions` chờ tenant-rbac/02 và nêu trong INSERT mọi cột
  NOT NULL có lúc đó (`risk` của tenant-rbac/01, `tenant_grantable` của tenant-rbac/02): ticket 05 với hai khóa
  `studio.bindings.*`, ticket 02 với khóa của hai loại fixture trong test, nên ticket 02 chờ tenant-rbac/02; không
  chuyển cột sang tenant-rbac/01 (ADR-0104 (Accepted) quyết 1; C:custom-objects/02~tenant-rbac/02). Sửa: Phụ thuộc,
  ticket 02, 05. Nếu sai thì: tenant-rbac/01 tạo `tenant_grantable` kèm sửa ADR-0104 (Accepted) quyết 1, và ticket 02
  chỉ chờ tenant-rbac/02 vì `platform.effective_grants`.
- 24/10/2026 (agent, tạm): lần từ chối của tiền tố nghiêm (người yêu cầu hay chủ thể chạy tự quyết) mang
  `details.reason_code` `second_person_required` cho mọi loại phê duyệt, đặt một lần ở `_enforce_strict_rules` của
  ticket 05, không nhánh theo loại trong `decide`; `author_cannot_approve` vẫn là mã của guard tác giả dưới
  `studio.publish.` (ADR-0104 (Accepted) quyết 11; B:packages:spec~tenant-config/05). Sửa: Trong phạm vi, TC16,
  ticket 05. Nếu sai thì: mỗi loại tự đặt mã qua guard của nó trong `decision_guards`, và TC16 chỉ phủ `config.`.
- 24/10/2026 (agent, tạm): ticket 04 chờ runtime-hardening/03, vì `ck_worker_runs_status` có trước cột
  `run_manifest_hash` trên cùng `platform.worker_runs` (C:runtime-hardening/03~tenant-config/04). Sửa: Phụ thuộc,
  ticket 04. Nếu sai thì: runtime-hardening/03 chờ ticket 04, và dòng Phụ thuộc đổi chiều.
- 24/10/2026 (agent, tạm): sửa các phát hiện có nguồn đã chấp nhận: kiểm điểm gắn đáp ứng Protocol
  `PublishBindingsCheck` mà agent-lifecycle khai cho lệnh gửi và handler `.decided`
  (`B:agent-lifecycle:api~tenant-config:R7.2`; ADR-0120 (Accepted) quyết 2, ADR-0103 (Accepted) quyết 4);
  `uq_artifacts_tenant_id_id` làm đích FK ghép của agent-builder và usage-and-limits
  (`B:agent-builder:spec~tenant-config:spec`); ticket 02, 04, 05 chờ foundations-hardening/07 vì cùng sửa
  `offboarding.py` và `test_offboarding.py` (`C:foundations-hardening/07~tenant-rbac/02`).
  Sửa: R7.2, Trong phạm vi, Dữ liệu, TC22, Phụ thuộc, ticket 02, 04, 05. Nếu sai thì: tên Protocol đổi theo
  agent-lifecycle, và bên dùng tự thêm ràng buộc đích trong migration của mình.
- 24/10/2026 (agent, tạm): quy ước khóa quyền do tenant-rbac làm chủ ở tenant-rbac:R1.6 (V4.P10), nên Phụ thuộc,
  ticket 02 và dòng Đạt cùng ngày về dạng khóa dẫn luật đó thay vì chép lại nó, vì luật có khu vực số ít mà spec này
  dùng (`studio.publish.approve`); khóa `studio.bindings.*` không đổi
  (G:ADR-0117 (Accepted)\~tenant-rbac:trong-phạm-vi). Sửa: Phụ thuộc, Quyết định, ticket 02. Nếu sai thì:
  `studio.publish.approve` mà spec này dẫn đổi tên theo luật của tenant-rbac.
- 24/10/2026 (agent, tạm): luật so `compared_live_hash` viết "so với phiên bản Đang dùng mà lần phát hành này thay
  (gỡ trong cùng giao dịch), hay không có bản nào" thay cho "bản Đang dùng hiện tại", vì lần phát hành gỡ bản `live`
  cũ trước khi đặt bản mới (chỉ mục một Đang dùng, agent-lifecycle:R1.4), nên so với bản còn lại sau khi gỡ thì mọi
  lần phát hành có bản `live` trước đều bị từ chối; dòng Đạt cùng ngày về `compared_live_hash` (V4.2) đọc theo câu
  này (ADR-0120 (Accepted) quyết 1). Sửa: R2.16, TC27, Phụ thuộc, Quyết định. Nếu sai thì: ADR-0120 (Accepted)
  quyết 1 giữ "bản Đang dùng hiện tại" với một thứ tự gỡ khác, và R2.16, TC27, Phụ thuộc đổi theo câu của ADR.
- 24/10/2026 (agent, tạm): hoàn tất V4.4: gốc bản kê là bản Nháp với mã băm tạm chỉ ở chế độ `simulate`
  (ADR-0109 (Accepted) quyết 6), và kiểm thứ sáu của quyết 8 so mã băm hiện tại của nội dung nháp với mã băm đã ghim,
  lệch thì `incompatible_resume`; route chạy mô phỏng chạy bộ kiểm một lượt của lúc gửi kiểm định trên nội dung nháp
  trước khi xin lượt, có lỗi thì 422 với mã `wf.*` (ADR-0112 (Accepted) quyết 3; workflow-triggers:R2.9). Sửa: R6.1,
  R6.7, Ngoài phạm vi, ticket 04. Nếu sai thì: R6.1, R6.7 dẫn quyết định của ADR-0109 (Accepted) mà ADR ghi cho gốc bản
  Nháp, và route chạy mô phỏng không kiểm nội dung nháp trước khi xin lượt, nên lỗi `wf.*` chỉ hiện lúc gửi kiểm định.
- 24/10/2026 (agent, tạm): lệnh gửi kiểm định của agent-lifecycle nhận `If-Match` là ETag của bản Nháp (lệch → 412
  `precondition_failed` với `stale_version`, V4.6; thiếu → 428 `precondition_required`; agent-lifecycle:R2.12,
  agent-lifecycle:R2.13; app-standards:R3.2, app-standards:R3.3; ADR-0108 (Accepted) quyết 3; ADR-0109 (Accepted)
  quyết 2), và `seal(..., expected_row_version)` của ticket 02 dùng đúng giá trị đó. Sửa: R2.17, Trong phạm vi,
  Ngoài phạm vi, TC3, Phụ thuộc, ticket 02. Nếu sai thì: lệnh gửi không mang điều kiện ghi, `seal` chỉ khóa dòng và đọc
  `row_version` hiện tại, và R2.17 rút.
- 24/10/2026 (agent, tạm): mục `ArtifactKindRegistry` mang móc phát hành của loại theo ADR-0109 (Accepted) quyết 1
  ("publish hook"); spec của từng loại cấp móc (dịch vụ metadata của custom-objects cho `object`, workflow-triggers
  cho `endpoint`), agent-lifecycle gọi nó trong giao dịch phát hành, và spec này không có dịch vụ phát hành riêng.
  Sửa: R2.15, Trong phạm vi, Ngoài phạm vi, TC24, Phụ thuộc, ticket 02. Nếu sai thì: tenant-config có một dịch vụ
  phát hành gọi móc, agent-lifecycle gọi dịch vụ đó, và Ngoài phạm vi đổi chủ của bước phát hành.
- 24/10/2026 (agent, tạm): `uq_artifact_versions_tenant_id_id UNIQUE (tenant_id, id)` và FK ghép cho mọi FK tới
  `studio.artifact_versions` mà spec này nêu (`based_on_version_id`, `from_version_id`, `to_version_id`,
  `artifact_version_id`), để FK chặn tham chiếu chéo tenant mà RLS không canh (`CLAUDE.md` "Tenancy and
  authorization"); `based_on_version_id` dùng `ON DELETE SET NULL (based_on_version_id)`, vì SET NULL không danh sách
  cột đặt NULL cả `tenant_id` (đo trên PostgreSQL 16.15, ghi ở ticket 02). Sửa: R2.18, Dữ liệu, TC29, Phụ thuộc,
  ticket 02, 04. Nếu sai thì: FK một cột giữ nguyên, và một trigger so `tenant_id` hai phía thay FK ghép.
- 24/10/2026 (agent, tạm): ticket 02 chờ app-standards/01 (vỏ problem+json) và app-standards/03 (ETag, `If-Match`,
  412, 428), ticket 05 chờ app-standards/02 (`Idempotency-Key` gắn người gọi), vì hai ticket dùng các hợp đồng đó; đã
  kiểm không tạo vòng. Sửa: Phụ thuộc, ticket 02, 05. Nếu sai thì: hai ticket chỉ dựa trên phần hợp đồng đã có ở
  `main`, và ba cạnh rút.
- 24/10/2026 (agent, tạm): mọi khóa ngoại của spec này nêu `ON DELETE` và có index ở phía mình (`CLAUDE.md` "Data model
  rules"): FK `(tenant_id, workspace_id, approval_id)` của `platform.config_versions` là ON DELETE RESTRICT có index,
  như ticket 05 đã viết, và FK `(tenant_id, owning_workspace_id)` của `studio.artifacts` có index
  `(tenant_id, owning_workspace_id)`; FK của `artifact_version_id` ở ticket 04 viết `ON DELETE RESTRICT` tường minh;
  `to_field_id` mà custom-objects thêm vào `studio.dependencies` là FK ghép `(tenant_id, to_field_id)` ON DELETE
  RESTRICT có index, như ADR-0109 (Accepted) quyết 5 viết, vì câu cũ "FK của nó" không nêu hành động.
  Sửa: Dữ liệu, ticket 02, 04, 05. Nếu sai thì: FK tới yêu cầu phê duyệt là ON DELETE CASCADE, và
  `platform.config_versions` không cần đứng trước `platform.approval_requests` trong `_ORDERED_FIRST` của ticket 05.
- 24/10/2026 (agent, tạm): FK giữa hai bảng của tenant là FK ghép `(tenant_id, <cột>)` tới UNIQUE `(tenant_id, id)` của
  bảng đích, vì kiểm khóa ngoại không qua RLS nên một FK một cột để một công ty trỏ tới dòng của công ty khác
  (`CLAUDE.md` "Tenancy and authorization"), như dòng tạm cùng ngày về `uq_artifact_versions_tenant_id_id`:
  `artifact_id` của `studio.artifact_versions`, `from_artifact_id` và `to_artifact_id` của `studio.dependencies` tới
  `uq_artifacts_tenant_id_id`, và `config_version_id` của `platform.run_manifest_keys` tới
  `uq_config_versions_tenant_id_id`, mà ticket 05 tạo trong revision tạo `platform.config_versions`; FK tới bảng không
  theo tenant (`studio.artifact_kinds`) giữ một cột; R2.18 và TC29 phủ mọi cột đó. Sửa: R2.18, Dữ liệu, TC29, Phụ
  thuộc, ticket 02, 05. Nếu sai thì: các cột đó giữ FK một cột, và một trigger so `tenant_id` hai phía thay FK ghép.
- 24/10/2026 (agent, tạm): ticket 05 thêm `config_version_id` vào `platform.run_manifest_keys` cùng CHECK
  `num_nonnulls(artifact_version_id, config_version_id) = 1`, và trong cùng bước bỏ NOT NULL của `artifact_version_id`
  mà ticket 04 tạo, vì dòng khóa của một phiên bản cấu hình có `artifact_version_id` NULL (ADR-0109 (Accepted) quyết 6:
  khóa bản kê RESTRICT tới cả `studio.artifact_versions` lẫn `platform.config_versions`); unique
  `(tenant_id, manifest_hash, config_version_id)` giữ một dòng khóa cho mỗi phiên bản cấu hình của một bản kê như unique
  của `artifact_version_id` ở ticket 04, vì unique đó không phủ dòng có `artifact_version_id` NULL. Sửa: Dữ liệu, ticket
  04, 05. Nếu sai thì: khóa của phiên bản cấu hình nằm ở một bảng riêng có `config_version_id` NOT NULL, và
  `artifact_version_id` giữ NOT NULL.
- 24/10/2026 (agent, tạm): bản kê ghim một `secret_version` cho mỗi (kết nối, trường bí mật), không một phiên bản
  credential cho mỗi kết nối, vì `secret_version` đánh số theo chủ thể và trường và là phiên bản credential mà bản kê
  ghim (ADR-0115 (Accepted) quyết 1; ADR-0109 (Accepted) quyết 6). Sửa: R7.4, Phụ thuộc, ticket 05. Nếu sai thì: một
  kết nối có một phiên bản credential chung cho mọi trường, ADR-0115 (Accepted) quyết 1 đổi khóa unique của
  `platform.secret_envelopes`, và R7.4 ghim một phiên bản cho mỗi kết nối.
- 24/10/2026 (agent, tạm): index danh sách lọc `kind` của `studio.artifacts` là
  `(tenant_id, kind, updated_at DESC, id DESC)` và `GET /api/v1/studio/artifacts` phân trang theo
  `updated_at DESC, id DESC`, cùng chiều phá hòa `id DESC` của các danh sách khác trong area, để index mang trọn thứ tự
  trang (`CLAUDE.md` "Data model rules"). Sửa: Dữ liệu, API, ticket 02. Nếu sai thì: area phá hòa theo `id` tăng, và
  index cùng thứ tự của route đổi theo.
- 24/10/2026 (agent, tạm): `connection_usable(connection, context, purpose)` nhận `purpose` từ W1, như
  ADR-0115 (Accepted) quyết 2 viết và ADR-0118 (Accepted) gọi với `model`, để W2 không phải sửa mọi chỗ gọi
  (`CLAUDE.md` "Per-tenant artifacts": thêm đối số về sau là sửa mọi chỗ gọi); ticket 05 gọi với `purpose` `tool` lúc
  đề xuất, lúc duyệt và lúc nhận lượt chạy, vì kết nối của W1 chỉ dùng cho công cụ. Sửa: Phụ thuộc, ticket 05. Nếu sai
  thì: hàm không có `purpose` ở W1, và W2 thêm đối số ở mọi chỗ gọi, kể cả ba chỗ của ticket 05.
- 24/10/2026 (agent, tạm): `owning_workspace_id` của thành phần không đổi: trigger
  `studio.refuse_owning_workspace_change()` từ chối lệnh đổi cột đó, vì AAD của phong bì bí mật gắn workspace sở hữu
  của chủ thể, workspace sở hữu của một chủ thể thuộc thành phần (như dòng `studio.inbound_endpoints` của một Nguồn dữ
  liệu, chủ thể của phong bì bí mật ký, workflow-triggers Dữ liệu) là của thành phần, nên đổi cột thì các phong bì đó
  không mở được nữa (ADR-0115 (Accepted) quyết 1); `PATCH` vốn không nhận cột này. Sửa: R2.19, Dữ liệu, TC30, Phụ
  thuộc, ticket 02. Nếu sai thì: đổi workspace sở hữu là một thao tác riêng mã hóa lại mọi phong bì của chủ thể thuộc
  thành phần trong cùng giao dịch, và trigger nhường cho thao tác đó.
- 24/10/2026 (agent, tạm): `RunRequestService` của workflow-engine tự chạy bộ kiểm một lượt của lúc gửi kiểm định trên
  nội dung nháp khi gốc là bản Nháp ở `simulate`, bên gọi nào xin cũng vậy, và có lỗi thì từ chối yêu cầu
  (workflow-engine:R3.11), vì mọi bên gọi đều tới cửa đó (failure-modes #5; ADR-0109 (Accepted) quyết 6); route
  `.../test-runs` không chạy bộ kiểm lần thứ hai mà trả lần từ chối đó thành 422 với mã `wf.*` (workflow-triggers:R2.9).
  Dòng này thay phần "route chạy mô phỏng chạy bộ kiểm một lượt của lúc gửi kiểm định trên nội dung nháp trước khi xin
  lượt" của dòng hoàn tất V4.4 cùng ngày. Sửa: Ngoài phạm vi. Nếu sai thì: cửa từ chối gốc bản Nháp khi yêu cầu không
  mang kết quả kiểm đạt, thay vì tự chạy bộ kiểm.
- 24/10/2026 (agent, tạm): workflow-engine cấp móc phát hành của loại `workflow`, như custom-objects cho `object` và
  workflow-triggers cho `endpoint`, vì móc do chủ của loại cấp (ADR-0109 (Accepted) quyết 1). Sửa: Phụ thuộc, ticket 02.
  Nếu sai thì: một spec khác cấp móc của loại `workflow`, và dòng Phụ thuộc của workflow-engine đổi chủ.
- 24/10/2026 (agent, tạm): bước niêm phong của vỏ phiên bản (`seal`: so và tăng `row_version`, cấp `version_no`, hai
  mã băm, bản kê định nghĩa, Nơi đang dùng) như nhau cho mọi loại và không đổi `stage`; `LifecycleService` của
  agent-lifecycle chuyển giai đoạn trong cùng giao dịch gửi (`draft → evaluating`, `draft → awaiting_approval`, và
  `draft → live` ở nhánh chỉ siết sau khi gỡ bản `live` trước), và `studio.guard_version_stage()` là hàng rào cuối, vì
  ADR-0120 (Accepted) quyết 1 viết "`LifecycleService` writes; the trigger is the backstop"; nên `seal` không còn tham
  số `tighten_only`, không đọc `has_quality_gate` (bên đọc cờ là dịch vụ gửi kiểm định và trigger của agent-lifecycle),
  và tăng `row_version` để lần niêm phong thứ hai cùng `expected_row_version` nhận `stale_version`. Dòng này thay phần
  "bước niêm phong của ticket 02 chuyển nháp sang `evaluating`" của dòng tạm 23/10/2026 về cột `stage`, và dòng Đạt
  24/10/2026 về `has_quality_gate` đọc theo câu này (cột vẫn là chỗ duy nhất của cờ). Sửa: R2.7, R2.13, R2.16, Ngoài
  phạm vi, Dữ liệu, TC27, Phụ thuộc, ticket 02. Nếu sai thì: `seal` chuyển giai đoạn theo `has_quality_gate` và nhận
  lại `tighten_only`, ADR-0120 (Accepted) quyết 1 đổi bên ghi giai đoạn, và agent-lifecycle/03, agent-lifecycle/04 chỉ
  gọi `seal`.
- 24/10/2026 (agent, tạm): hai FK ghép của spec này chưa có ca âm chéo tenant nay có, như các FK ghép khác của spec tới
  một UNIQUE có `id` (R2.18): `(tenant_id, owning_workspace_id)` của `studio.artifacts` tới
  `uq_workspaces_tenant_id_id` (thành phần của tenant A có `owning_workspace_id` là workspace của tenant B → lỗi FK;
  ADR-0109 (Accepted) quyết 1), và `(tenant_id, workspace_id, approval_id)` của `platform.config_versions` tới
  `uq_approval_requests_tenant_id_workspace_id_id` (phiên bản cấu hình của tenant A trỏ yêu cầu phê duyệt của tenant
  B → lỗi FK; R8.16, tiêu chí mới), vì test âm cho ghi chéo tenant là bắt buộc (`CLAUDE.md` "Tenancy and
  authorization"; failure-modes #3) và một FK một cột ở đó để trigger `approved_by_approval` nhận phê duyệt của công ty
  khác. Sửa: R2.18, R8.16, Dữ liệu, TC29, Phụ thuộc, ticket 02, 05. Nếu sai thì: hai ca rời R2.18, TC29 và R8.16 rút,
  và hai cột chỉ được canh bằng kiểm quyền của route ghi.
- 24/10/2026 (agent, tạm): mọi khóa ngoại của spec này có index dẫn bằng cột của nó (`CLAUDE.md` "Data model rules"):
  `kind` của `studio.artifacts` có index `(kind)` riêng, vì index danh sách và unique Tên API dẫn bằng `tenant_id`;
  Dữ liệu nêu index `(tenant_id, run_manifest_hash)` của FK trên `platform.worker_runs` như ticket 04 đã viết; FK
  `(tenant_id, manifest_hash)` của `platform.run_manifest_keys` dùng unique
  `(tenant_id, manifest_hash, artifact_version_id)`, dẫn bằng hai cột đó. Sửa: Dữ liệu, ticket 02, 04. Nếu sai thì: FK
  tới bảng danh mục `studio.artifact_kinds` không cần index phía mình vì dòng danh mục không bị xóa, và `CLAUDE.md`
  "Data model rules" ghi ngoại lệ đó.
- 24/10/2026 (agent, tạm): thêm index `(tenant_id, updated_at DESC, id DESC)` cho `GET /api/v1/studio/artifacts` không
  lọc `kind` (trang `/studio`), bên cạnh index lọc `kind` của dòng tạm cùng ngày về index danh sách, vì index dẫn bằng
  `(tenant_id, kind)` không mang thứ tự trang khi không có `kind`, nên trang nào cũng sắp cả tập khớp (`CLAUDE.md`
  "Data model rules"). Sửa: Dữ liệu, Quyết định, ticket 02. Nếu sai thì: route bắt buộc lọc `kind`, trang `/studio`
  gọi một lần cho mỗi loại, và index thứ hai rút.
- 24/10/2026 (agent, tạm): lúc duyệt một Bộ giá trị gắn, guard quyết định của ticket 05 hỏi lại `connection_usable`
  với `purpose` `tool` cho Người đề xuất ở workspace của đề xuất, với mọi kết nối của đề xuất, như ADR-0110 (Accepted)
  quyết 7 ("asked again at approval") và ADR-0115 (Accepted) quyết 2 viết (connections-and-vault:R5.9); trả false →
  409 `conflict` với `decision_stale` và yêu cầu giữ `pending`, cùng mã với Phiên bản gốc đã đổi vì cả hai là quyết
  định trên một đề xuất mà điều kiện đã đổi từ lúc đề xuất; lệnh từ chối không hỏi lại. Dòng tạm cùng ngày về
  `connection_usable` thêm chỗ gọi lúc duyệt. Sửa: R8.9, TC20, Phụ thuộc, Quyết định, ticket 05. Nếu sai thì: lần hỏi
  lại trả một mã riêng (`binding_degraded`) ở một tiêu chí mới của R8, và TC20 tách ca đó.
- 24/10/2026 (agent, tạm): Dữ liệu không liệt kê "mọi FK ghép" tới `uq_artifacts_tenant_id_id` hay
  `uq_artifact_versions_tenant_id_id` như một danh sách đủ: nó nêu FK của spec này (R2.18) và gọi FK của spec khác là
  ví dụ, vì chủ của từng FK, cùng ca âm chéo tenant của nó, là spec tạo FK (failure-modes #2: danh sách thứ hai lệch im
  lặng khi một spec thêm FK). Sửa: Dữ liệu, Phụ thuộc, ticket 02. Nếu sai thì: spec này giữ danh sách đủ mọi FK tới
  vỏ, và spec nào thêm FK sửa danh sách đó cùng lúc.
- 24/10/2026 (agent, tạm): `dw_app` có DELETE trên `studio.artifacts`, `studio.artifact_versions`,
  `studio.definition_manifests`, `platform.run_manifests`, `platform.run_manifest_keys` và `platform.config_versions`,
  quyền chỉ dùng được ở lượt xóa của offboarding: trigger BEFORE DELETE `platform.refuse_delete_outside_offboarding()`
  từ chối với SQLSTATE 23514 khi công ty của dòng khác `offboarding` (R3.8, TC31), cùng hình với agent-lifecycle:R7.5 và
  compliance-pdpl:R5.6, vì lane `offboarding` xóa bằng `dw_app` và chỉ xóa bảng mà `dw_app` có DELETE
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:98-101`; mục `_ORDERED_FIRST` của bảng
  khác bị bỏ qua, `offboarding.py:187-188`), nên thiếu DELETE thì test phủ offboarding đỏ và dữ liệu ở lại (`CLAUDE.md`
  "Data model rules": quyền là một phần của schema; studio-skeleton:R4.1, studio-skeleton:R4.3), còn ứng dụng không xóa
  cứng dòng nào của sáu bảng (xóa mềm, phiên bản bất biến, bản kê định danh theo nội dung, phiên bản cấu hình là hồ sơ
  quyết định). `studio.dependencies` có DELETE thường, không trigger đó, vì ứng dụng tự xóa dòng của nó: niêm phong lại
  một phiên bản đã về `draft` (R2.8) thay Nơi đang dùng của phiên bản đó (R3.1; ADR-0109 (Accepted) quyết 5). Mỗi FK ON
  DELETE RESTRICT chạm bảy bảng này có thứ tự trong `_ORDERED_FIRST`, bảng tham chiếu trước (studio-skeleton:R4.2):
  `studio.dependencies`, `studio.artifacts`, `studio.artifact_versions` theo ADR-0109 (Accepted) Consequences;
  `platform.run_manifest_keys` sau `platform.worker_runs` và trước `platform.config_versions` cùng các mục `studio`, vì
  test phủ đọc thứ tự các bước xóa mà `offboarding.py` khai, không theo CASCADE của `platform.run_manifests`, nên
  `platform.run_manifests` về phần xóa theo chữ cái, vẫn sau `platform.worker_runs`. Ca xóa cứng để thấy lỗi FK (R2.18,
  R3.3, R6.5) chạy khi công ty ở `offboarding`. Sửa: thêm R3.8, TC31, Dữ liệu, TC5, TC15, TC21, Phụ thuộc, ticket 02,
  04, 05. Nếu sai thì: `dw_app` không có DELETE trên sáu bảng đó, lane `offboarding` xóa chúng bằng một hàm SECURITY
  DEFINER hẹp, một bước xóa mà test phủ đọc, và mỗi bảng có một dòng `STUDIO_EXCLUSIONS` nêu hàm đó; nếu niêm phong lại
  không thay Nơi đang dùng của phiên bản, `studio.dependencies` nhận cùng trigger.
- 24/10/2026 (Đạt): V4.16: lần kích hoạt gặp `binding_needs_review` không còn bị từ chối: lượt chạy ở lại `queued` như
  V4.9 tới khi Bộ giá trị gắn được duyệt lại, rồi chạy theo thứ tự đến, và lần giữ báo người duyệt được Bộ giá trị gắn,
  tức người giữ `studio.bindings.approve`, khóa duyệt của R8.1. Sửa: Phụ thuộc, ticket 05.
- 24/10/2026 (agent, tạm): theo V4.16, kiểm `binding_needs_review` rời bộ kiểu Điểm gắn sang `BindingReviewPort` mà làn
  `studio_runs` hỏi ở dispatch (workflow-engine:R5.19; workflow-triggers:R3.7), vì lượt đang giữ phải được nhả khi Bộ
  giá trị gắn được duyệt lại, còn bước 9 của ticket 05 chạy một lần lúc ghim; nên bộ kiểu Điểm gắn ở W1 chỉ nhận kiểm
  lúc đề xuất và không giữ chỗ cho một kiểm lúc nhận lượt chạy mà không kind nào của W1 đăng ký (failure-modes #1), còn
  kiểm ở dispatch đọc `decided_at` của các Bộ giá trị gắn đã duyệt. Sửa: Trong phạm vi, Phụ thuộc, ticket 05. Nếu sai
  thì: kind `principal` đăng ký lại kiểm lúc nhận lượt chạy vào bộ kiểu Điểm gắn, `RunRequestService` tạo lượt đã giữ
  khi kiểm đó trả `binding_needs_review`, và một handler của lần duyệt Bộ giá trị gắn nhả các lượt đó.
- 24/10/2026 (Đạt): V4.17: mỗi thành phần có tối đa một phiên bản ở `draft`, `evaluating` hay `awaiting_approval` (chỉ
  mục duy nhất một phần) cùng tối đa một bản `live`; tạo bản Nháp mới khi đang có Bản ứng viên → 409 `conflict` với
  `details.reason_code` `candidate_pending`, muốn sửa thì rút Bản ứng viên về Nháp; ca bản chỉ siết lên `live` trong lúc
  một bản nới chờ không còn xảy ra được, nên rời TC27, thay bằng ca 409 `candidate_pending`, còn kiểm `compared_live_hash`
  vẫn là hàng rào; dòng này thay vế "nên bản chỉ siết lên `live` trong lúc Bản ứng viên chờ không bị thay" của dòng Đạt
  cùng ngày về `compared_live_hash`. Sửa: đoạn mở đầu, R2, R2.16, thêm R2.20, R2.22, Dữ liệu, API, Ngoài phạm vi, TC27,
  Phụ thuộc, ticket 02.
- 24/10/2026 (agent, tạm): route tạo bản Nháp mà V4.17 nêu là `POST /api/v1/studio/artifacts/{id}/draft`, vì spec chưa có
  route nào tạo bản Nháp sau bản đầu (R2.1 tạo bản đầu cùng thành phần, `PUT .../draft` chỉ lưu bản đang có): bản Nháp
  chép `document_schema` và `document` của phiên bản Đang dùng, hay của phiên bản có `version_no` lớn nhất khi không có
  bản Đang dùng, `based_on_version_id` trỏ phiên bản đó, audit `studio.artifact.draft_created`; thành phần đã có bản Nháp
  → 409 `conflict` với `draft_exists`, để mọi nhánh từ chối của route có mã riêng như `proposal_open` của R8.6. Sửa: thêm
  R2.21, R2.23, Trong phạm vi, API, TC27, ticket 02. Nếu sai thì: bản Nháp chép phiên bản người gọi chọn (khôi phục),
  hay route trả bản Nháp đang có thay vì 409 `draft_exists`, và R2.21, R2.23 đổi theo.
- 24/10/2026 (agent, tạm): thứ tự xóa duy nhất trong `offboarding.py` liệt kê mỗi bảng sau mọi bảng giữ một FK RESTRICT
  tới nó và không dựa vào CASCADE, vì `studio.gate_runs.artifact_id` (RESTRICT tới thành phần) và
  `studio.artifact_versions.gate_run_id` (RESTRICT tới Lượt kiểm định) của agent-lifecycle làm vỡ thứ tự thành phần trước
  phiên bản của ADR-0109 (Accepted) Consequences, thứ tự chỉ chạy được nhờ CASCADE từ thành phần xuống phiên bản:
  `studio.dependencies` cùng các bảng trỏ tới phiên bản (`platform.worker_runs`, `platform.run_manifest_keys`, bảng của
  spec khác) → `studio.artifact_versions` → các bảng kiểm định của agent-lifecycle → `studio.artifacts`.
  `studio.dependencies` đứng trước phiên bản chứ không sau Lượt kiểm định, vì `to_version_id` của nó là FK RESTRICT tới
  phiên bản (ADR-0109 (Accepted) quyết 5), nên luật trên đặt nó trước `studio.artifact_versions`, và CASCADE của
  `from_version_id` không cho nó đi sau: xóa phiên bản trước hỏng ở `to_version_id` mỗi khi phiên bản được phụ thuộc tới
  trước phiên bản phụ thuộc nó (đo trên PostgreSQL 16.15, ghi ở ADR-0109 (Accepted) Consequences); test phủ của
  studio-skeleton:R4.2 đọc các cạnh RESTRICT từ `pg_constraint` và đỏ khi thứ tự khai trái chúng (failure-modes #0). Dòng
  này thay phần "`studio.dependencies`, `studio.artifacts`, `studio.artifact_versions` theo ADR-0109 (Accepted)
  Consequences" của dòng tạm cùng ngày về quyền xóa của lane `offboarding`. Sửa: Dữ liệu, TC21, Phụ thuộc, ticket 02. Nếu
  sai thì: các khóa đó thành `NO ACTION DEFERRABLE INITIALLY DEFERRED`, kiểm lúc commit, để giao dịch xóa duy nhất xóa cả
  nhóm theo thứ tự nào cũng được (khóa không deferrable hỏng như RESTRICT, cùng số đo đó), và ticket 02 về thứ tự
  `studio.dependencies`, `studio.artifacts`, `studio.artifact_versions`.
- 25/10/2026 (Đạt): V4.34: `durability="sync"` ghim ở mục `engine` của bản kê lượt chạy (ADR-0109 (Accepted) quyết 8),
  ticket 04 là chủ nội dung bản kê, workflow-engine/03 truyền nó cho mọi lần chạy và tiếp tục. Sửa: thêm R6.8, TC32,
  Phụ thuộc, ticket 04.
- 25/10/2026 (Đạt): V4.35: bản kê lượt chạy ghim id kết nối và phiên bản Bộ giá trị gắn, không ghim `secret_version`;
  lúc gọi, lời gọi dùng phiên bản mới nhất chưa bị thu hồi của kết nối và ghi phiên bản đã dùng vào
  `platform.tool_executions` và audit; xoay tách khỏi thu hồi vì lộ, và thu hồi vì lộ dừng mọi lượt chưa xong của kết
  nối ở lời gọi egress kế tiếp với `credential_revoked` (connections-and-vault); dòng này thay dòng tạm 24/10/2026 "bản
  kê ghim một `secret_version` cho mỗi (kết nối, trường bí mật)". Sửa: R7, R7.4, R7.5, TC15, Phụ thuộc, ticket 05.
- 25/10/2026 (Đạt): V4.37: ca kịch bản tất định ở Cổng chất lượng của quy trình ở W1; "Kết quả giả lập ghim theo Bước"
  kéo từ W2 về W1, nơi wrapper nút áp nó ở mức Bước, không gọi ToolExecutor (workflow-engine:R4.27); dòng này thay dòng
  ngày 23/10/2026 "Kết quả giả lập ghim theo Bước do workflow-nodes làm ở W2". Sửa: Ngoài phạm vi, ticket 03.
- 25/10/2026 (agent, tạm): H-18: kết quả giả lập ghim thuộc wrapper nút của workflow-engine/03, không thuộc executor của
  ticket 03: wrapper áp kết quả ghim cho Bước ở `simulate` thay cho phần giả lập của loại, sau khi kiểm với schema đầu
  ra của Bước, ca kịch bản mang các kết quả ghim và lane `studio_gate` (agent-lifecycle/06) chuyển chúng vào lần thử;
  route `test-runs` giữ W2 cho kết quả ghim; ToolExecutor không đọc kết quả ghim nào và R5.3 không đổi. Sửa: Ngoài phạm
  vi, ticket 03. Nếu sai thì: mỗi loại Bước tự đọc kết quả ghim của mình, và bước chế độ của ticket 03 trả kết quả ghim
  thay cho giá trị sinh từ output schema.
- 25/10/2026 (agent, tạm): H-2 áp cho spec này: bảy bảng của spec dùng bước mặc định của sổ bước xóa của
  foundations-hardening/07, thứ tự suy từ khóa ngoại `RESTRICT` và `NO ACTION` của `pg_constraint`, nên ticket 02, 04, 05
  không thêm mục `_ORDERED_FIRST` nào, và ca âm của R3.6 thành ca trên thứ tự suy ra; dòng này thay phần thứ tự
  `_ORDERED_FIRST` của hai dòng tạm 24/10/2026 về quyền xóa của lane `offboarding` và về thứ tự xóa duy nhất, còn thứ tự
  các bảng mà hai dòng đó nêu nay là thứ tự mà catalog cho. Sửa: Hiện trạng, Dữ liệu, Phụ thuộc, ticket 02, 04, 05. Nếu
  sai thì: thứ tự viết tay trong `offboarding.py`, và ba ticket thêm mục của mình vào đó như trước.
- 25/10/2026 (agent, tạm): ticket 03 thay `ck_tool_executions_status` bằng tập của runtime-hardening:R6.3 (`succeeded`,
  `failed`, `dispatched`, `outcome_unknown`) cộng `simulated`, vì `dispatched` và `outcome_unknown` có từ lần tạo
  (V4.30) và một tập chép lại thiếu chúng sẽ từ chối nhật ký lần gửi; tools-and-skills/01 đưa bước chế độ chạy của ticket
  03 vào sổ guard của ToolExecutor (H-3). Sửa: Dữ liệu, TC11, ticket 03. Nếu sai thì: revision đọc tập hiện có từ
  catalog và thêm `simulated` vào đó.

## Danh sách ticket

| #   | Ticket                                                                                                                           |
| --- | -------------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Băm chuẩn hóa JCS (RFC 8785) một chủ trong dw_kernel](issues/01-bam-chuan-hoa-jcs.md)                                           |
| 02  | [Vỏ phiên bản dùng chung và chỉ mục phụ thuộc ghi trong giao dịch gửi kiểm định](issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md) |
| 03  | [Chế độ chạy trên mỗi lượt chạy và executor giả lập ở chế độ Mô phỏng](issues/03-che-do-chay-va-gia-lap-o-executor.md)           |
| 04  | [Bản kê lượt chạy: ghim mọi thứ lượt chạy dùng, phân giải theo bản kê](issues/04-ban-ke-luot-chay.md)                            |
| 05  | [Điểm gắn: giá trị là phiên bản cấu hình có người đề xuất và người duyệt khác nhau](issues/05-lien-ket-va-phien-ban-cau-hinh.md) |
