# Cấu hình của tenant có phiên bản, hai người duyệt, chạy mô phỏng an toàn, bản kê lượt chạy

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Mọi thứ công ty tự dựng trong Studio (đối tượng, quy trình, agent, công cụ, kỹ năng, bộ công cụ) cần
một vỏ phiên bản chung: đúng một nháp sửa được, phiên bản niêm phong bất biến có số và mã băm tái tạo
được, và Nơi đang dùng chặn xóa thứ đang được dùng. Mỗi lượt chạy ghim mọi thứ nó dùng vào một bản kê,
kể cả khi tiếp tục sau nhiều ngày chờ duyệt; chế độ chạy do máy chủ đặt và được kiểm ở executor, nên
người dựng chạy mô phỏng mà không tác động nào rời nền tảng; giá trị của điểm gắn chỉ có
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
  buộc: mỗi cạnh RESTRICT mới vào danh sách đó cùng migration của nó.
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

Người dựng của mọi loại thành phần có đúng một nháp sửa được và các phiên bản niêm phong không đổi,
đánh số không dùng lại (YC30; ADR-0109 (Accepted) quyết 1-2).

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
- R2.7 KHI niêm phong một nháp hợp lệ của loại có Cổng chất lượng, dịch vụ vỏ phiên bản PHẢI, trong một
  giao dịch, cấp `version_no` bằng `last_version_no` cộng 1, ghi `content_hash`, `definition_hash` và
  chuyển phiên bản từ `draft` sang `evaluating`.
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
- R2.13 ĐỐI VỚI loại thành phần không có Cổng chất lượng (`object` và `endpoint` ở W1, `tool` ở W2), khi lệnh gửi
  không đặt `tighten_only`, dịch vụ vỏ phiên bản PHẢI niêm phong như R2.7 nhưng chuyển phiên bản từ `draft` thẳng
  sang `awaiting_approval`, để bên gọi mở yêu cầu phê duyệt phát hành trong cùng giao dịch (ADR-0120 (Accepted)
  quyết 1-2).
- R2.14 NẾU một dòng đăng ký loại vào `studio.artifact_kinds` không nêu `has_quality_gate`, THÌ PostgreSQL PHẢI
  từ chối dòng đó, để không loại nào bỏ qua kiểm định chỉ vì thiếu khai báo.
- R2.15 Mỗi mục `ArtifactKindRegistry` PHẢI khai khóa đọc, khóa ghi và khóa gửi của loại, mỗi khóa có trong danh
  mục quyền một chủ của tenant-rbac, cùng móc phát hành mà spec của loại cấp, để R2.11, R2.12 và lệnh gửi của
  agent-lifecycle (agent-lifecycle:R2.1) kiểm đúng khóa của loại đó và giao dịch phát hành của agent-lifecycle chạy
  đúng móc của loại (agent-lifecycle:R2.9, agent-lifecycle:R5.5; ADR-0109 (Accepted) quyết 1).
- R2.16 ĐỐI VỚI phiên bản `dw.object/v1` mà lệnh gửi của agent-lifecycle đặt `tighten_only` (custom-objects:R1.7),
  dịch vụ vỏ phiên bản PHẢI niêm phong như R2.7 và chuyển phiên bản từ `draft` thẳng sang `live` trong giao dịch của
  bên gọi, không mở yêu cầu phê duyệt nào và không đổi Bản ứng viên đang chờ, để `compared_live_hash` cũ của nó, so
  với phiên bản Đang dùng mà lần phát hành của nó thay (gỡ trong cùng giao dịch), chặn nó thay bản vừa siết
  (agent-lifecycle:R1.8, agent-lifecycle:R5.9; ADR-0120 (Accepted) quyết 1).
- R2.17 NẾU `row_version` mà lệnh gửi của agent-lifecycle đưa cho bước niêm phong, tức giá trị `If-Match` của lệnh
  gửi, khác `row_version` hiện tại của nháp, THÌ dịch vụ vỏ phiên bản PHẢI từ chối với `details.reason_code`
  `stale_version` để lệnh gửi trả 412 `precondition_failed`, và không niêm phong gì (agent-lifecycle:R2.12;
  ADR-0108 (Accepted) quyết 3; ADR-0109 (Accepted) quyết 2).
- R2.18 NẾU một dòng trỏ tới một phiên bản của tenant khác qua `based_on_version_id`, Nơi đang dùng
  (`from_version_id`, `to_version_id`) hay khóa bản kê (`artifact_version_id`), THÌ PostgreSQL PHẢI từ chối dòng đó
  bằng FK ghép `(tenant_id, <cột>)` tới `uq_artifact_versions_tenant_id_id`, kể cả khi vai ghi bỏ qua RLS.

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

### R7 — Điểm gắn trong tài liệu

Tài liệu chỉ nêu tên những gì nó cần (kết nối, biến, người chạy), không bao giờ id kết nối; giá trị
nằm ở Bộ giá trị gắn đã duyệt và được ghim theo lượt chạy (YC35; ADR-0110 (Accepted) quyết 6-8).

- R7.1 NẾU tài liệu đem niêm phong chứa id kết nối ở chỗ phải là tên điểm gắn, THÌ dịch vụ vỏ phiên bản
  PHẢI trả 422 `validation_failed` có một lỗi cho mỗi đường dẫn đó và không niêm phong.
- R7.2 NẾU phiên bản đem gửi hay phát hành có điểm gắn bắt buộc chưa có giá trị đã duyệt, THÌ kiểm điểm gắn
  (`PublishBindingsCheck`) PHẢI trả `binding_unset` kèm tên điểm gắn, để lệnh gửi trả 409 và handler `.decided`
  không đưa phiên bản sang `live` (agent-lifecycle:R2.11, agent-lifecycle:R5.10).
- R7.3 NẾU lúc nhận lượt chạy, kết nối được gắn đã bị thu hồi hoặc không còn dùng được cho người chạy,
  THÌ runtime PHẢI từ chối lượt chạy với `binding_degraded` trước node đầu tiên.
- R7.4 KHI một lượt chạy được nhận, runtime PHẢI ghim vào bản kê id phiên bản Bộ giá trị gắn, id và
  phiên bản credential của từng kết nối và mã băm của từng giá trị biến, không ghi giá trị bí mật nào.
- R7.5 KHI một Bộ giá trị gắn mới được duyệt trong lúc một lượt chạy đang chờ duyệt, runtime PHẢI tiếp
  tục lượt chạy đó với Bộ giá trị gắn đã ghim.

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
- R8.9 NẾU Phiên bản gốc của đề xuất đã đổi trước lúc quyết định, THÌ luồng phê duyệt PHẢI trả 409
  `conflict` với `details.reason_code` `decision_stale` và giữ yêu cầu phê duyệt ở `pending`.
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
  mỗi kind đăng ký kiểm lúc đề xuất và kiểm lúc nhận lượt chạy của nó; kiểm điểm gắn lúc gửi và lúc phát hành (đáp ứng
  `PublishBindingsCheck` mà agent-lifecycle khai) và lúc nhận lượt chạy; port async `ApprovalDecisionGuard` thay
  `DecisionGuard`; mã `second_person_required` của tiền tố nghiêm cho mọi loại phê duyệt; handler
  `config.version.decided` ở lane `outbox`; `RunBindingsPort` đáp ứng từ bản kê và `ConnectionDependentsPort` đáp ứng từ
  Nơi đang dùng (hai port do connections-and-vault khai).
- Audit: `studio.artifact.created`, `studio.artifact.updated`, `studio.artifact.draft_saved`,
  `studio.artifact.deleted`, `tool.simulated`, `config.version.proposed`, `config.version.approved`, `config.version.rejected`,
  `config.version.withdrawn`.

## Ngoài phạm vi

| Việc                                                                                                                                                                                                                                                                                                                                               | Vì sao                                                                                                                                                                                                                                                                                                                       | Chủ                                                   |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| W2: người nhận thử và kiểm ở egress, mở chế độ `test` (kiểm soát TC12-TC14: egress, Danh sách người nhận thử, thông báo của lượt không `live` chỉ tới người chạy thử)                                                                                                                                                                              | YC36; cần `studio.test_recipients`, kết nối bật chế độ thử và lời đồng ý của DO-55                                                                                                                                                                                                                                           | tenant-config, đợt sau (W2); connections-and-vault    |
| W2: biểu mẫu sinh từ schema, so sánh từng trường, xem thay đổi ở hộp duyệt; màn hình thành phần, Nơi đang dùng và Bộ giá trị gắn                                                                                                                                                                                                                   | W1 chỉ mở API; độ vừa của biểu mẫu dw-proterial chờ FOG-53                                                                                                                                                                                                                                                                   | tenant-config, đợt sau (W2)                           |
| W2: lớp riêng của tenant cho prompt, tool spec, toolset, model profile, chính sách; `effective_hash`; gỡ `platform.policy_overrides`                                                                                                                                                                                                               | YC37; DO-27 (Đạt 23/10/2026): ghi đè prompt chỉ khi prompt có bên đọc theo công ty, không `raw_variables`, không prompt khung, và đổi Mã băm hiệu lực; gỡ `platform.policy_overrides` cùng lúc `platform.config_versions` nhận kind `policy`, sau khi đếm 0 dòng ở mọi môi trường; `ModelProfile` cần phiên bản và `Decimal` | tenant-config, đợt sau (W2)                           |
| W2: tín hiệu lệch cấu hình (gồm outbox `config.version.approved`); lưu giữ và dọn; CI chặn xóa artifact nền tảng đã phát hành                                                                                                                                                                                                                      | YC75; chưa có bên đọc ở W1; thời hạn lưu giữ là số tạm của DO-52 trong tệp `retention` do telemetry-and-audit/03 làm chủ                                                                                                                                                                                                     | tenant-config, đợt sau (W2); agent-lifecycle đọc lệch |
| W3: phụ thuộc quan sát được; đọc lại ghi giả lập trong cùng lượt chạy thử (v1.5)                                                                                                                                                                                                                                                                   | Cần records gateway và nguyên mẫu FOG-60                                                                                                                                                                                                                                                                                     | tenant-config, đợt sau (W3)                           |
| W3: công ty thử nghiệm (sandbox tenant), đưa phiên bản sang công ty chính bằng gói                                                                                                                                                                                                                                                                 | ADR-0111 (Accepted) quyết 7; DO-62 (Đạt 23/10/2026): chỉ người vận hành tạo, chỉ dữ liệu giả lập, hạn mức riêng                                                                                                                                                                                                              | tenant-config, đợt sau (W3)                           |
| Trigger chuyển giai đoạn (kể cả nhánh chỉ siết của `dw.object/v1`), cột `tighten_only` và `compared_live_hash`, cổng chất lượng, lệnh gửi kiểm định (nhận `If-Match` và đưa `row_version` đó cho bước niêm phong, R2.17) và phát hành (gọi móc phát hành của loại, R2.15), kể cả handler `.decided` trả Bản ứng viên về `draft` với `base_changed` | ADR-0120 (Accepted) quyết 1-2 giao cho vòng đời                                                                                                                                                                                                                                                                              | agent-lifecycle                                       |
| Cửa nhận lượt chạy, lượt con, sáu kiểm trước khi tiếp tục, trong đó kiểm thứ sáu đặt `blocked` với `incompatible_resume` khi nội dung bản Nháp mà lượt mô phỏng ghim đã đổi (R6.4; workflow-engine:R3.9, workflow-engine:R6.14)                                                                                                                    | ADR-0113 (Accepted); ADR-0109 (Accepted) quyết 8                                                                                                                                                                                                                                                                             | workflow-engine                                       |
| Route `.../test-runs` (chạy mô phỏng ở W1, nhận cả phiên bản `draft` khi bộ kiểm một lượt của lúc gửi kiểm định đạt trên nội dung nháp, không thì 422 với mã `wf.*`; 422 với `live`, và với `test` tới W2)                                                                                                                                         | Hợp đồng duy nhất của route này (DO-26.1; workflow-triggers:R2.3, workflow-triggers:R2.9; ADR-0112 (Accepted) quyết 3)                                                                                                                                                                                                       | workflow-triggers                                     |
| W2: Kết quả giả lập ghim theo Bước cho lệnh gọi giả lập                                                                                                                                                                                                                                                                                            | W1 dùng giá trị sinh từ output schema (R5.3); bảng thuật ngữ đặt chủ là workflow-nodes                                                                                                                                                                                                                                       | workflow-nodes, đợt sau (W2)                          |
| Egress client ở chế độ khác `live` từ chối mọi purpose trừ `model` và Hành động chỉ đọc hay `simulate_safe` (W2 mở ngoại lệ cho Danh sách người nhận thử); phân loại `simulate_safe` theo loại công cụ                                                                                                                                             | Lớp thứ hai sau executor (ADR-0111 (Accepted) quyết 3; ADR-0115 (Accepted) quyết 6; DO-26.1); ADR-0116 (Accepted)                                                                                                                                                                                                            | connections-and-vault; tools-and-skills               |
| W2: nhánh một người có audit cho thay đổi cấu hình chỉ siết: cột `tighten_only` do bộ so sánh của kind tính lúc đề xuất, kèm `document_hash` của bản đã duyệt được so, mà `ck_config_versions_checker_not_maker` và trigger `approved_by_approval` mở cho dòng đó                                                                                  | ADR-0110 (Accepted) quyết 2; `binding_set` ở W1 không đăng ký bộ so sánh nào, nên mọi đề xuất `binding_set` qua hai người (R8.8, R8.12); bộ so sánh đầu tiên ra cùng kind `policy`                                                                                                                                           | tenant-config, đợt sau (W2)                           |
| W2: route tạo thành phần từ chối Tiền tố dành riêng của gói nền tảng (domain-packs:R3.1)                                                                                                                                                                                                                                                           | Luật bật khi gói Marketing ra ở W2; `mkt_lead`, `mkt_campaign` mà marketing-pilot/02 đã gieo giữ tên, và gói gắn nguồn gốc cho chúng khi cài (domain-packs:R4.5)                                                                                                                                                             | tenant-config, đợt sau (W2); domain-packs             |
| Đưa `record_visibility`, `max_autonomy_level`, `timezone`, `locale` của `platform.tenants` vào phiên bản có duyệt                                                                                                                                                                                                                                  | Đổi hành vi ngoài Studio                                                                                                                                                                                                                                                                                                     | không làm                                             |
| Lớp cấu hình thứ ba theo workspace                                                                                                                                                                                                                                                                                                                 | `TenantOverlay` giữ hai lớp; thành phần của một workspace là thành phần Studio riêng (ADR-0110 (Accepted))                                                                                                                                                                                                                   | không làm                                             |

## Dữ liệu

Mọi bảng có `tenant_id`: RLS ENABLE và FORCE chỉ theo tenant (định nghĩa toàn tenant, ADR-0100 (Accepted)
quyết 5), grant cùng migration, tên ràng buộc theo `NAMING_CONVENTION`, revision id hex ngẫu nhiên. Mỗi bảng
không có `workspace_id` có một dòng lý do trong danh sách bảng toàn tenant của `test_rls_coverage.py`
(DO-01): `studio.artifacts`, `studio.artifact_versions`, `studio.definition_manifests`,
`studio.dependencies`, `platform.run_manifests`, `platform.run_manifest_keys`.

- `studio.artifact_kinds`: danh mục loại của nền tảng, không có `tenant_id`; `kind text` là khóa chính;
  `has_quality_gate boolean NOT NULL`, không DEFAULT, mà bước niêm phong và `studio.guard_version_stage()` của
  agent-lifecycle cùng đọc (R2.13, R2.14); ticket đăng ký một loại INSERT một dòng nêu cờ đó trong migration của
  nó, cùng lúc với mục `ArtifactKindRegistry`; `dw_app` chỉ SELECT.
- `studio.artifacts`: `id` UUIDv7; `uq_artifacts_tenant_id_id UNIQUE (tenant_id, id)`, đích của FK ghép
  `(tenant_id, artifact_id)` mà bên dùng đặt (`studio.agent_settings` của agent-builder, `scope_artifact_id` của
  usage-and-limits), như `uq_workspaces_tenant_id_id`; `kind` FK tới `studio.artifact_kinds (kind)` ON DELETE
  RESTRICT, có index; `api_name` `^[a-z][a-z0-9_]{1,39}$`, unique `(tenant_id, kind, api_name)` khi
  `deleted_at IS NULL`; FK `(tenant_id, owning_workspace_id)` tới `platform.workspaces (tenant_id, id)` ON DELETE
  RESTRICT, qua `uq_workspaces_tenant_id_id` do org-and-principals/01 tạo;
  `labels text[] NOT NULL DEFAULT '{}'` (bộ lọc `label` của danh sách đọc); `origin jsonb` NULL
  (domain-packs ghi và đọc nguồn gốc gói); `last_version_no integer NOT NULL DEFAULT 0`;
  `row_version integer NOT NULL`; `deleted_at timestamptz` NULL; `created_at`, `updated_at`
  `timestamptz NOT NULL`; index danh sách `(tenant_id, kind, updated_at DESC, id)`.
- `studio.artifact_versions`: `stage` NOT NULL CHECK (`draft`, `evaluating`, `awaiting_approval`,
  `live`, `retired`), không DEFAULT; `version_no` NULL chỉ khi `stage = 'draft'`, unique
  `(artifact_id, version_no)`; một dòng `draft` mỗi thành phần (partial unique); `document_schema`
  `^dw\.[a-z_]+/v[0-9]+$`; `document` là jsonb object tối đa 1 MiB, `CHECK (document::text IS NFC NORMALIZED)`;
  `content_hash`, `definition_hash` khớp `^sha256:[0-9a-f]{64}$`, `definition_hash` NOT NULL ngoài
  `draft`; `row_version integer NOT NULL`; `artifact_id` FK CASCADE;
  `uq_artifact_versions_tenant_id_id UNIQUE (tenant_id, id)`, đích của mọi FK ghép `(tenant_id, <cột phiên bản>)` trỏ
  tới phiên bản (R2.18): `based_on_version_id` của chính bảng này, `studio.dependencies`, `platform.run_manifest_keys`
  và `version_id` của `studio.version_assessments` (compliance-pdpl); `based_on_version_id` FK ghép
  `(tenant_id, based_on_version_id)` `ON DELETE SET NULL (based_on_version_id)`, chỉ đặt NULL cột đó vì `tenant_id`
  NOT NULL; `change_note` NULL.
- `studio.definition_manifests`: khóa chính `(tenant_id, hash)`, `body` jsonb NFC tối đa 1 MiB, chỉ
  INSERT.
- `studio.dependencies`: `from_version_id` FK ghép `(tenant_id, from_version_id)` và `from_artifact_id` FK, cả hai
  CASCADE; `to_kind` CHECK (`artifact`, `field`, `picklist_value`, `platform_artifact`, `connector`, `mcp_tool`,
  `binding`, `node_type`); `to_key`, `to_version`, `to_hash`; `to_artifact_id` FK và `to_version_id` FK ghép
  `(tenant_id, to_version_id)`, cả hai RESTRICT; mỗi FK một index, FK ghép thì index `(tenant_id, <cột>)`;
  `usage` CHECK (`read`, `write`, `compare`, `invoke`, `bind`, `display`); `path` con trỏ JSON; index
  `(tenant_id, to_kind, to_key)`; `to_field_id` và FK của nó do custom-objects thêm cùng bảng field.
- `platform.worker_runs`: `run_mode text NOT NULL` CHECK (`live`, `test`, `simulate`), không DEFAULT,
  dòng cũ backfill `live`; `run_manifest_hash` NULL, khớp `^sha256:[0-9a-f]{64}$`, FK
  `(tenant_id, run_manifest_hash)` tới `platform.run_manifests` ON DELETE RESTRICT, có index.
- `platform.tool_executions.status`: CHECK của foundations-hardening/04 thêm `simulated`.
- `platform.run_manifests`: khóa chính `(tenant_id, hash)`, `body` jsonb NFC tối đa 1 MiB, ghi bằng
  `INSERT ... ON CONFLICT DO NOTHING`, `dw_app` chỉ SELECT và INSERT. `platform.run_manifest_keys`: FK
  tới bản kê ON DELETE CASCADE; `artifact_version_id` FK ghép `(tenant_id, artifact_version_id)` và
  `config_version_id` FK, cả hai RESTRICT, đúng một cột khác NULL.
- `platform.config_versions`: `kind` CHECK (`binding_set`); `key` là id thành phần; `action` CHECK
  (`set`); `version_no` tăng theo khóa, không dùng lại; `base_version`; `document` jsonb object tối đa
  256 KiB, NFC; `document_hash`; `status` CHECK (`proposed`, `approved`, `rejected`, `withdrawn`,
  `superseded`); partial unique một `approved` và một `proposed` mỗi khóa; `workspace_id` là nơi đề
  xuất; FK `(tenant_id, workspace_id, approval_id)` tới `platform.approval_requests`;
  `ck_config_versions_checker_not_maker`; trigger `approved_by_approval`; `dw_app` chỉ UPDATE `status`,
  `decided_by`, `decided_at`, `decision_comment`, `superseded_at`.

## API

- `POST /api/v1/studio/artifacts` (tạo kèm nháp), `GET /api/v1/studio/artifacts` (keyset, lọc `kind`,
  `label`), `GET /api/v1/studio/artifacts/{id}`, `PATCH /api/v1/studio/artifacts/{id}` (`api_name`,
  `labels`; `If-Match`), `PUT /api/v1/studio/artifacts/{id}/draft` (`If-Match`; thiếu thì 428),
  `GET /api/v1/studio/artifacts/{id}/versions`, `GET /api/v1/studio/artifacts/{id}/versions/{version_no}`,
  `DELETE /api/v1/studio/artifacts/{id}` (xóa mềm), `GET /api/v1/studio/artifacts/{id}/dependents`,
  `GET /api/v1/studio/artifacts/{id}/draft/dependencies`.
- `GET /api/v1/studio/artifacts/{id}/bindings`, `POST /api/v1/studio/artifacts/{id}/bindings/proposals`,
  `POST /api/v1/studio/artifacts/{id}/bindings/proposals/{config_version_id}/withdraw`.
- Lỗi theo vỏ problem+json của ADR-0108 (Accepted); `details.reason_code`: `stale_version`,
  `api_name_taken`, `api_name_immutable`, `artifact_in_use`, `no_checker_available`, `second_person_required`,
  `proposal_open`, `decision_stale`, `binding_unset`, `binding_degraded`. `Idempotency-Key` theo ADR-0108 (Accepted)
  quyết 4.

## Kiểm soát

| #    | Kiểm soát                                                                                                                                           | Yêu cầu                      | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TC1  | Nội dung phiên bản chỉ đổi khi ở `draft`                                                                                                            | R2.9                         | `dw_app` UPDATE `document` của phiên bản `live` → trigger từ chối; gỡ trigger → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| TC2  | Số phiên bản cấp tuần tự, không cấp lại                                                                                                             | R2.7, R2.8                   | Hai lần niêm phong đồng thời một nháp → một thành công, không số nào cấp hai lần; phiên bản quay về `draft` rồi niêm phong lại → số mới; bỏ khóa dòng `last_version_no` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| TC3  | Một nháp mỗi thành phần, khóa lạc quan                                                                                                              | R2.5, R2.17                  | `PUT` nháp với `If-Match` cũ → 412 `stale_version`, nháp không đổi; INSERT nháp thứ hai → lỗi partial unique; niêm phong với `row_version` cũ, tức lệnh gửi mang `If-Match` cũ → `stale_version`, không số phiên bản nào; bỏ so `row_version` ở `PUT` hay ở `seal` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| TC4  | Tên API bất biến sau lần phát hành đầu                                                                                                              | R2.10                        | `PATCH` `api_name` khi đã có phiên bản từng `live` → 409 `api_name_immutable`; UPDATE thẳng bằng `dw_app` → trigger từ chối                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| TC5  | Không xóa thành phần đang được dùng                                                                                                                 | R3.3                         | Xóa mềm đối tượng mà phiên bản `live` của một quy trình ở workspace khác dùng → 409 `artifact_in_use`; DELETE cứng → lỗi FK; gỡ trigger → test xóa mềm đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| TC6  | Nơi đang dùng ghi cùng giao dịch niêm phong                                                                                                         | R3.1                         | Lỗi chèn giữa giao dịch niêm phong → không số phiên bản, không dòng phụ thuộc; làm hỏng bộ trích xuất của loại fixture → test fixture đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| TC7  | Nơi đang dùng không lộ tên ngoài quyền                                                                                                              | R3.4                         | Người chỉ đọc được ở ws1 thấy tên bên phụ thuộc ở ws1, phần ở ws2 chỉ là số đếm; tenant B → 404                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| TC8  | Một hàm dạng chuẩn, đóng khi lỗi                                                                                                                    | R1.1, R1.2, R1.3, R1.4, R1.5 | `{"a": 1.0}`, `2**53`, chuỗi NFD → đúng mã lỗi, không mã băm; đổi thứ tự sắp khóa sang code point → test vi sai đỏ trên khóa ngoài BMP                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| TC9  | Chế độ chạy do máy chủ đặt, cột không mặc định, lượt con không nới                                                                                  | R4.1, R4.2, R4.4             | INSERT `worker_runs` thiếu `run_mode` → lỗi NOT NULL; `RunContext` dựng không chế độ gọi công cụ `external` → bị giả lập; cha `simulate`, con xin `live` → `simulate`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| TC10 | Tiếp tục lượt chạy giữ chế độ                                                                                                                       | R4.5                         | Lượt `simulate` chờ duyệt một công cụ `simulate_safe` đòi phê duyệt rồi tiếp tục → công cụ `external` gọi sau đó vẫn giả lập; bỏ `run_mode` khỏi chỗ dựng lại ngữ cảnh khi tiếp tục → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| TC11 | Executor giả lập ở `simulate` và `test`, trước bước phê duyệt                                                                                       | R5.1, R5.2, R5.3, R5.5, R5.6 | Gọi thẳng ToolExecutor, không qua node, với công cụ `external` ở `simulate` → handler không chạy, `status` `simulated`, audit `tool.simulated`; công cụ `critical` đòi phê duyệt ở `simulate` → giả lập, không yêu cầu phê duyệt nào; gỡ bước chế độ, hay đặt nó sau bước phê duyệt → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| TC15 | Bản kê ghim, không lùi về bản hiện hành, không bị dọn, không bí mật                                                                                 | R6.3, R6.4, R6.5, R7.4, R7.5 | Niêm phong phiên bản mới khi lượt chạy chờ duyệt → lượt tiếp tục với bản ghim; khóa không ghim → bị từ chối; DELETE phiên bản được ghim → lỗi FK; token mẫu không có trong `body`; lượt `simulate` trên bản Nháp, lưu nháp rồi tiếp tục → phân giải gốc bị từ chối, nội dung mới không chạy                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| TC16 | Người đề xuất không tự duyệt                                                                                                                        | R8.8                         | Người đề xuất quyết → 409 `conflict` với `second_person_required`; người yêu cầu tự quyết một yêu cầu `memory.review` → cùng mã, vì tiền tố nghiêm đặt mã một lần cho mọi loại; UPDATE `decided_by = proposed_by` → CHECK từ chối; bỏ `config.` khỏi prefix nghiêm → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| TC17 | Có hiệu lực chỉ qua yêu cầu phê duyệt đã duyệt, quyết toán một lần, audit đứng tên người quyết                                                      | R8.10, R8.11, R8.12, R8.15   | UPDATE `status = 'approved'` khi yêu cầu còn `pending` → trigger từ chối; `dw_app` UPDATE `document` → permission denied; giao lại sự kiện → không dòng, không audit mới; audit `config.version.approved` và `config.version.rejected` mang actor là `decided_by` và `details.lane` `outbox`, ghi actor `system:outbox` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| TC18 | Một đề xuất mở, luôn có người duyệt khác                                                                                                            | R8.5, R8.6                   | Đề xuất thứ hai cùng khóa → 409 `proposal_open`; workspace chỉ Người đề xuất giữ quyền duyệt → 409 `no_checker_available`; không dòng nào được ghi                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| TC19 | Chỉ loại đã đăng ký, không sang tenant khác                                                                                                         | R8.3, R8.7                   | Đề xuất loại `prompt` → 422, ghi thẳng → CHECK `kind` từ chối; tenant B đọc hay đề xuất trên thành phần của tenant A → 404                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| TC20 | Quyết định cũ bị từ chối, quyết toán không ghi đè                                                                                                   | R8.9, R8.11                  | Niêm phong phiên bản đổi khai báo điểm gắn giữa đề xuất và quyết định → 409 `decision_stale`, yêu cầu vẫn `pending`; gỡ guard → test đỏ; quyết toán gặp bản khác đã duyệt → `rejected`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| TC21 | Offboarding xóa hết dữ liệu Studio của tenant                                                                                                       | R3.6                         | Tenant có hai thành phần phụ thuộc nhau, bản kê và phiên bản cấu hình riêng → purge xong, tenant khác nguyên; gỡ một mục thứ tự → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| TC22 | Không gửi hay phát hành, không nhận lượt chạy khi điểm gắn thiếu hay hỏng                                                                           | R7.2, R7.3                   | Phiên bản thiếu giá trị `zalo_oa` → `PublishBindingsCheck` trả `binding_unset` nêu `zalo_oa`; gỡ kiểm `required` → test đỏ; kết nối bị thu hồi → nhận lượt chạy bị từ chối `binding_degraded`, không node nào chạy                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| TC23 | Tài liệu không chứa id kết nối                                                                                                                      | R7.1                         | Niêm phong tài liệu có UUID của một kết nối ở chỗ tên điểm gắn → 422 có con trỏ; gỡ kiểm → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| TC24 | Mỗi route thành phần kiểm tenant và quyền theo độ sâu, bằng khóa của loại                                                                           | R2.11, R2.12, R2.15          | Người chỉ đọc được ở ws1 GET thành phần của ws2 ngoài độ sâu → 404; `PUT` nháp không có quyền ghi → 403; tenant B → 404; test tham số hóa theo mọi loại đã đăng ký, gồm `workflow` khi workflow-engine:R1.5 đăng ký nó: thiếu `studio.workflows.read` → 404, có khóa đọc mà thiếu `studio.workflows.edit` → `PUT` nháp 403; mục registry thiếu một trong ba khóa hay móc phát hành, hay khai khóa không có trong danh mục quyền → test registry đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| TC25 | Chỉ người có quyền đề xuất và dùng được kết nối mới đề xuất được                                                                                    | R8.2, R8.4                   | Thiếu `studio.bindings.propose` → 403; kết nối Người đề xuất không dùng được → 422; không dòng nào được ghi                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| TC26 | Chỉ Người đề xuất rút được đề xuất                                                                                                                  | R8.14                        | Người khác gọi `withdraw` → 403, đề xuất và yêu cầu phê duyệt không đổi; bỏ so `proposed_by` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| TC27 | Chỉ loại khai không có Cổng chất lượng mới bỏ qua `evaluating`; chỉ nhánh chỉ siết bỏ qua người thứ hai, và Bản ứng viên cũ không thay bản vừa siết | R2.13, R2.14, R2.16          | INSERT dòng `studio.artifact_kinds` không nêu `has_quality_gate` → lỗi NOT NULL; `fixture` (`true`) → niêm phong sang `evaluating`; `fixture_gateless` (`false`) không `tighten_only` → `awaiting_approval`; `fixture_gateless` với `tighten_only` → `live`, không yêu cầu phê duyệt nào; `fixture` với `tighten_only` → từ chối, không niêm phong; thêm DEFAULT cho cột → test đỏ; một bản chỉ siết lên `live` trong lúc Bản ứng viên chờ → Bản ứng viên không đổi, rồi duyệt nó → về `draft` với `base_changed`, vì `compared_live_hash` của nó khác mã băm của bản chỉ siết mà lần phát hành này thay, và bản `live` vẫn là bản chỉ siết; duyệt một Bản ứng viên có gốc không đổi → lên `live` dù lần phát hành gỡ bản `live` cũ trước trong cùng giao dịch, và so với bản Đang dùng còn lại sau khi gỡ thay vì bản lần phát hành thay → test đỏ (ca duyệt chạy ở agent-lifecycle/04, nơi có handler `.decided`: AL19 và agent-lifecycle:R5.5) |
| TC28 | Chỉ lượt `simulate` chạy bản Nháp; lượt khác không dùng mã băm tạm                                                                                  | R6.1, R6.7                   | Nhận lượt `live` hay `test` có gốc `draft` → từ chối, không dòng `platform.run_manifests`, không node nào chạy; lượt `simulate` trên bản Nháp → bản kê ghim giai đoạn `draft` và mã băm tạm bằng mã băm mà bước niêm phong cho cùng nội dung; bỏ kiểm chế độ → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| TC29 | Không dòng nào trỏ tới phiên bản của tenant khác                                                                                                    | R2.18                        | Bằng vai migrator, INSERT dòng `studio.dependencies` của tenant A có `to_version_id` là phiên bản của tenant B → lỗi FK; cùng ca với `from_version_id`, `based_on_version_id` và `platform.run_manifest_keys.artifact_version_id`; đổi một FK ghép về FK một cột → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |

## Tiêu chí xong

- Mọi tiêu chí R và G có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (ghi ở Comments
  của ticket).
- `make ci && make test-integration` xanh; `reviewing-feature-security` đã chạy trên từng ticket;
  `.claude/plans/studio.md` ghi lát W1 đã xong.

## Phụ thuộc

- `.claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md`: gói `dw_studio`, nhóm
  route `/api/v1/studio`, schema `studio` có USAGE và default privileges (studio-skeleton/01).
- `.claude/plans/studio/foundations-hardening/issues/04-toolexecutor-gianh-luot-khong-cua-sau.md`:
  executor giành lượt trước và CHECK `tool_executions.status` mà ticket 03 mở rộng.
- `.claude/plans/studio/connections-and-vault/issues/04-ket-noi-dung-chung-theo-workspace.md`:
  `platform.connections` và `connection_usable` cho ticket 05, hàm này kiểm cả `connections.use` ở workspace của
  lượt chạy (ADR-0115 (Accepted) quyết 2); connections-and-vault/03 cho egress client ở chế độ khác `live`, từ chối
  mọi purpose trừ `model` và Hành động chỉ đọc hay `simulate_safe` (ADR-0115 (Accepted) quyết 6), nên R5.4 không đổi.
- `.claude/plans/studio/org-and-principals/issues/01-khoa-don-vi-va-siet-realm.md`: tạo
  `uq_workspaces_tenant_id_id` cho FK ghép của `studio.artifacts`; ticket 02 không tạo ràng buộc đó (OPS-a.2).
- `.claude/plans/studio/foundations-hardening/issues/06-run-va-outbox-khong-ket.md`: CHECK `status` của yêu
  cầu phê duyệt và đường tiếp tục ở `approval_flow.py` mà ticket 05 đổi sau (OPS-b), và `ck_worker_runs_status`
  trên `platform.worker_runs` có trước cột `run_manifest_hash` của ticket 04 (C:foundations-hardening/06~tenant-config/04).
- `.claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md`: viết lại
  `_CATALOG_COLUMNS`, `export_rows` và `test_offboarding.py`, nơi ticket 02, 04 và 05 thêm mục `_ORDERED_FIRST` và ca
  purge của mình (C:foundations-hardening/07~tenant-rbac/02).
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
- agent-lifecycle: `studio.guard_version_stage()` và luật theo loại: `draft` sang `awaiting_approval` cho loại không
  có Cổng chất lượng (agent-lifecycle:R1.6), và nhánh chỉ siết `draft` sang `live` với cột `tighten_only` cùng
  `compared_live_hash` mà lệnh gửi tính bằng bộ so sánh của loại (agent-lifecycle:R1.7, agent-lifecycle:R2.8,
  agent-lifecycle:R2.9; custom-objects:R1.7, custom-objects:R1.8; R2.16); mọi lệnh gửi ghi `compared_live_hash`,
  `definition_hash` của bản `live` lúc so (agent-lifecycle:R2.10), `awaiting_approval → live` chỉ khi nó vẫn là mã
  băm của phiên bản Đang dùng mà lần phát hành thay (gỡ trong cùng giao dịch), hay cùng NULL khi không có bản nào
  (agent-lifecycle:R1.8), và handler `.decided` đưa Bản ứng viên có gốc đã đổi về `draft` với `details.reason_code`
  `base_changed` (agent-lifecycle:R5.9; ADR-0120 (Accepted) quyết 1-2); lệnh gửi `POST .../submit`
  (agent-lifecycle:R2.1) kiểm khóa gửi mà R2.15 khai và nhận `If-Match` là ETag của bản Nháp, giá trị nó đưa cho bước
  niêm phong làm `row_version` mong đợi (412 `stale_version` khi lệch, 428 khi thiếu; agent-lifecycle:R2.12,
  agent-lifecycle:R2.13; R2.17); giao dịch phát hành của handler `.decided` và của nhánh chỉ siết gọi móc phát hành mà
  R2.15 khai (agent-lifecycle:R2.9, agent-lifecycle:R5.5).
- custom-objects: loại phê duyệt `studio.publish.object` là của custom-objects (custom-objects:R1.2;
  ADR-0120 (Accepted) quyết 2; R2.13), và móc phát hành của loại `object` là dịch vụ metadata (custom-objects:R1.1;
  R2.15).
- workflow-triggers: loại `endpoint` (Nguồn dữ liệu) là loại không có Cổng chất lượng, với phê duyệt
  `studio.publish.endpoint` đóng dấu `studio.publish.approve` và không bộ so sánh chỉ siết nào (ADR-0120 (Accepted)
  quyết 1-2; R2.13); workflow-triggers cấp móc phát hành của loại `endpoint` (R2.15).
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
  agent-lifecycle/03 đổi hợp đồng niêm phong, cột `stage`, cột `tighten_only` hay luật chuyển giai đoạn của loại không
  có Cổng chất lượng → R2.13, R2.16, ticket 02; agent-lifecycle đổi luật `compared_live_hash` hay cách đưa Bản ứng viên
  về `draft` với `base_changed` → R2.16, TC27; agent-lifecycle đổi điều kiện ghi của lệnh gửi hay chỗ gọi móc phát hành
  → R2.15, R2.17, ticket 02; app-standards đổi vỏ lỗi, ETag hay `Idempotency-Key` → ticket 02, 05; một bảng mới trỏ tới
  `studio.artifact_versions` → FK ghép của R2.18, TC29; workflow-triggers đổi vòng đời của loại `endpoint` → R2.13;
  custom-objects đổi bộ so sánh chỉ siết → R2.16; workflow-triggers hay workflow-engine đổi việc nhận phiên bản `draft`
  ở chế độ `simulate` hay kiểm khi tiếp tục lượt đó → R6.1, R6.7, TC28, ticket 04; tenant-rbac đổi cột NOT NULL của
  `platform.permissions` → ticket 02, 05; foundations-hardening/07 đổi `test_offboarding.py` hay danh mục xuất →
  ticket 02, 04, 05; tools-and-skills đổi thứ tự bước của `ToolExecutor` → R5.6, ticket 03; `connection_usable` đổi hình
  → ticket 05; một node W1 gửi thông báo qua kênh chat từ lượt không `live` → TC12-TC14 kéo về W1.

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
  ticket đăng ký loại INSERT một dòng; ticket 05 chờ foundations-hardening/06. Sửa: Dữ liệu, ticket 02, 05.
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
- 24/10/2026 (agent, tạm): ticket 04 chờ foundations-hardening/06, vì `ck_worker_runs_status` có trước cột
  `run_manifest_hash` trên cùng `platform.worker_runs` (C:foundations-hardening/06~tenant-config/04). Sửa: Phụ thuộc,
  ticket 04. Nếu sai thì: foundations-hardening/06 chờ ticket 04, và dòng Phụ thuộc đổi chiều.
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

## Danh sách ticket

| #   | Ticket                                                                                                                           |
| --- | -------------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Băm chuẩn hóa JCS (RFC 8785) một chủ trong dw_kernel](issues/01-bam-chuan-hoa-jcs.md)                                           |
| 02  | [Vỏ phiên bản dùng chung và chỉ mục phụ thuộc ghi trong giao dịch gửi kiểm định](issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md) |
| 03  | [Chế độ chạy trên mỗi lượt chạy và executor giả lập ở chế độ Mô phỏng](issues/03-che-do-chay-va-gia-lap-o-executor.md)           |
| 04  | [Bản kê lượt chạy: ghim mọi thứ lượt chạy dùng, phân giải theo bản kê](issues/04-ban-ke-luot-chay.md)                            |
| 05  | [Điểm gắn: giá trị là phiên bản cấu hình có người đề xuất và người duyệt khác nhau](issues/05-lien-ket-va-phien-ban-cau-hinh.md) |
