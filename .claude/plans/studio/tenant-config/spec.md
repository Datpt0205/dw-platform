# Cấu hình của tenant có phiên bản, hai người duyệt, chạy thử an toàn, bản kê lượt chạy

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Mọi thứ công ty tự dựng trong Studio (đối tượng, quy trình, agent, công cụ, kỹ năng, bộ công cụ) cần
một vỏ phiên bản chung: đúng một nháp sửa được, phiên bản niêm phong bất biến có số và mã băm tái tạo
được, và Nơi đang dùng chặn xóa thứ đang được dùng. Mỗi lượt chạy ghim mọi thứ nó dùng vào một bản kê,
kể cả khi tiếp tục sau nhiều ngày chờ duyệt; chế độ chạy do máy chủ đặt và được kiểm ở executor, nên
người dựng chạy thử ở chế độ Mô phỏng mà không tác động nào rời nền tảng; giá trị của điểm gắn chỉ có
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
- R2.13 ĐỐI VỚI loại thành phần không có Cổng chất lượng (`object` ở W1, `tool` ở W2), dịch vụ vỏ phiên bản
  PHẢI niêm phong như R2.7 nhưng chuyển phiên bản từ `draft` thẳng sang `awaiting_approval`, để bên gọi mở
  yêu cầu phê duyệt phát hành trong cùng giao dịch (ADR-0120 (Accepted) quyết 2).
- R2.14 NẾU đăng ký của một loại thành phần không nêu loại đó có Cổng chất lượng hay không, THÌ dịch vụ vỏ
  phiên bản PHẢI coi loại đó là có Cổng chất lượng.

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

Người dựng chạy thử ở chế độ Mô phỏng mà không lệnh gọi có tác động nào rời nền tảng (YC34;
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

### R6 — Bản kê lượt chạy

Mỗi lượt chạy Studio ghim mọi thứ nó dùng và chỉ đọc từ bản kê đó, kể cả khi tiếp tục sau 3 ngày chờ
duyệt hay lâu hơn (YC32; ADR-0109 (Accepted) quyết 6-7).

- R6.1 KHI một lượt chạy có gốc là thành phần Studio được nhận, runtime PHẢI ghi lên dòng lượt chạy
  `run_manifest_hash` của bản kê `dw.run_manifest/v1` gồm release ref, chế độ chạy, phiên bản gốc với
  `definition_hash` và bao đóng, trước node đầu tiên.
- R6.2 KHI hai lượt chạy ghim cùng nội dung, PostgreSQL PHẢI giữ đúng một dòng bản kê cho mã băm đó.
- R6.3 TRONG KHI một lượt chạy Studio chạy hay tiếp tục, NẾU nó hỏi một khóa không có trong bản kê, THÌ
  runtime PHẢI từ chối lần phân giải đó và không đọc phiên bản hiện hành.
- R6.4 KHI một lượt chạy Studio tiếp tục ở tiến trình khác sau khi chờ duyệt, runtime PHẢI dựng lại mọi
  phân giải từ bản kê đã ghim, kể cả khi thành phần đã có phiên bản mới hơn.
- R6.5 NẾU một lệnh xóa chạm tới bản kê, hay tới phiên bản mà bản kê ghim, trong khi lượt chạy còn trỏ
  tới bản kê đó, THÌ PostgreSQL PHẢI từ chối lệnh xóa.
- R6.6 Việc dựng và ghi bản kê NÊN thêm không quá 20 ms p95 vào lúc nhận lượt chạy (bao đóng 50 thành
  phần, đo trên compose), trừ khi số đo ghi ở ticket 04 cho thấy không đạt và Đạt chấp nhận số mới.

### R7 — Điểm gắn trong tài liệu

Tài liệu chỉ nêu tên những gì nó cần (kết nối, biến, người chạy), không bao giờ id kết nối; giá trị
nằm ở Bộ giá trị gắn đã duyệt và được ghim theo lượt chạy (YC35; ADR-0110 (Accepted) quyết 6-8).

- R7.1 NẾU tài liệu đem niêm phong chứa id kết nối ở chỗ phải là tên điểm gắn, THÌ dịch vụ vỏ phiên bản
  PHẢI trả 422 `validation_failed` có một lỗi cho mỗi đường dẫn đó và không niêm phong.
- R7.2 NẾU phiên bản đem phát hành có điểm gắn bắt buộc chưa có giá trị đã duyệt, THÌ kiểm điểm gắn PHẢI
  trả `binding_unset` để việc phát hành trả 409 và phiên bản không sang `live`.
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

| Mã   | Điều kiện                                                                                                                                       | API Studio trả                               |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| R8.2 | người gọi thiếu `studio.bindings.propose` ở workspace đang làm việc                                                                             | 403 `permission_denied`                      |
| R8.3 | thành phần hay kết nối thuộc tenant khác                                                                                                        | 404                                          |
| R8.4 | giá trị sai kiểu khai báo; kết nối khác trình kết nối hay phiên bản chính khai báo, thiếu quyền khai báo, hoặc Người đề xuất không dùng được nó | 422 `validation_failed`, mỗi lỗi một con trỏ |
| R8.5 | không ai khác Người đề xuất giữ `studio.bindings.approve` ở workspace của đề xuất                                                               | 409 `conflict`, `no_checker_available`       |
| R8.6 | khóa đã có một đề xuất mở                                                                                                                       | 409 `conflict`, `proposal_open`              |
| R8.7 | loại cấu hình chưa đăng ký                                                                                                                      | 422 `validation_failed`                      |

- R8.8 NẾU người quyết định là Người đề xuất, THÌ luồng phê duyệt PHẢI trả 409 và không ghi quyết định
  nào.
- R8.9 NẾU Phiên bản gốc của đề xuất đã đổi trước lúc quyết định, THÌ luồng phê duyệt PHẢI trả 409
  `conflict` với `details.reason_code` `decision_stale` và giữ yêu cầu phê duyệt ở `pending`.
- R8.10 KHI yêu cầu phê duyệt `config.version` được duyệt, lane `outbox` PHẢI đặt phiên bản sang
  `approved` và bản đã duyệt trước của cùng khóa sang `superseded` trong một giao dịch có audit
  `config.version.approved` với actor `system:outbox`.
- R8.11 KHI yêu cầu phê duyệt bị từ chối, hoặc lúc quyết toán đã có bản khác được duyệt cho cùng khóa,
  lane `outbox` PHẢI đặt phiên bản sang `rejected` (lý do `settlement_conflict` ở trường hợp sau) trong
  một giao dịch có audit `config.version.rejected`.
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
- Mã: `dw_kernel.canonical`; `RunMode` và luật chế độ lượt con trong kernel; `ArtifactKindRegistry`
  (mô hình tài liệu, bộ kiểm trả mọi lỗi, bộ trích xuất phụ thuộc thuần) và bước niêm phong của vỏ phiên
  bản; bước chế độ chạy trong ToolExecutor; `RunManifestPort` (runtime khai, Studio đáp ứng) và
  `PinnedResolver`; `ConfigKindRegistry` với loại `binding_set`; kiểm điểm gắn cho việc phát hành và
  lúc nhận lượt chạy; port async `ApprovalDecisionGuard` thay `DecisionGuard`; handler
  `config.version.decided` ở lane `outbox`; `RunBindingsPort` đáp ứng từ bản kê và
  `ConnectionDependentsPort` đáp ứng từ Nơi đang dùng (hai port do connections-and-vault khai).
- Audit: `studio.artifact.created`, `studio.artifact.updated`, `studio.artifact.draft_saved`,
  `studio.artifact.deleted`, `tool.simulated`, `config.version.proposed`, `config.version.approved`, `config.version.rejected`,
  `config.version.withdrawn`.

## Ngoài phạm vi

| Việc                                                                                                                                                                  | Vì sao                                                                                                                                                                                                                                                                                                                       | Chủ                                                   |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| W2: người nhận thử và kiểm ở egress, mở chế độ `test` (kiểm soát TC12-TC14: egress, Danh sách người nhận thử, thông báo của lượt không `live` chỉ tới người chạy thử) | YC36; cần `studio.test_recipients`, kết nối bật chế độ thử và lời đồng ý của DO-55                                                                                                                                                                                                                                           | tenant-config, đợt sau (W2); connections-and-vault    |
| W2: biểu mẫu sinh từ schema, so sánh từng trường, xem thay đổi ở hộp duyệt; màn hình thành phần, Nơi đang dùng và Bộ giá trị gắn                                      | W1 chỉ mở API; độ vừa của biểu mẫu dw-proterial chờ FOG-53                                                                                                                                                                                                                                                                   | tenant-config, đợt sau (W2)                           |
| W2: lớp riêng của tenant cho prompt, tool spec, toolset, model profile, chính sách; `effective_hash`; gỡ `platform.policy_overrides`                                  | YC37; DO-27 (Đạt 23/10/2026): ghi đè prompt chỉ khi prompt có bên đọc theo công ty, không `raw_variables`, không prompt khung, và đổi Mã băm hiệu lực; gỡ `platform.policy_overrides` cùng lúc `platform.config_versions` nhận kind `policy`, sau khi đếm 0 dòng ở mọi môi trường; `ModelProfile` cần phiên bản và `Decimal` | tenant-config, đợt sau (W2)                           |
| W2: tín hiệu lệch cấu hình (gồm outbox `config.version.approved`); lưu giữ và dọn; CI chặn xóa artifact nền tảng đã phát hành                                         | YC75; chưa có bên đọc ở W1; thời hạn lưu giữ là số tạm của DO-52 trong tệp `retention` do telemetry-and-audit/03 làm chủ                                                                                                                                                                                                     | tenant-config, đợt sau (W2); agent-lifecycle đọc lệch |
| W3: phụ thuộc quan sát được; đọc lại ghi giả lập trong cùng lượt chạy thử (v1.5)                                                                                      | Cần records gateway và nguyên mẫu FOG-60                                                                                                                                                                                                                                                                                     | tenant-config, đợt sau (W3)                           |
| W3: công ty thử nghiệm (sandbox tenant), đưa phiên bản sang công ty chính bằng gói                                                                                    | ADR-0111 (Accepted) quyết 7; DO-62 (Đạt 23/10/2026): chỉ người vận hành tạo, chỉ dữ liệu giả lập, hạn mức riêng                                                                                                                                                                                                              | tenant-config, đợt sau (W3)                           |
| Trigger chuyển giai đoạn, cổng chất lượng, lệnh gửi kiểm định và phát hành                                                                                            | ADR-0120 (Accepted) quyết 1-2 giao cho vòng đời                                                                                                                                                                                                                                                                              | agent-lifecycle                                       |
| Cửa nhận lượt chạy, lượt con, năm kiểm trước khi tiếp tục                                                                                                             | ADR-0113 (Accepted); ADR-0109 (Accepted) quyết 8                                                                                                                                                                                                                                                                             | workflow-engine                                       |
| Route chạy thử (422 với `live`, và với `test` tới W2)                                                                                                                 | Hợp đồng duy nhất của route chạy thử (DO-26.1; workflow-triggers:R2.3)                                                                                                                                                                                                                                                       | workflow-triggers                                     |
| W2: Kết quả giả lập ghim theo Bước cho lệnh gọi giả lập                                                                                                               | W1 dùng giá trị sinh từ output schema (R5.3); bảng thuật ngữ đặt chủ là workflow-nodes                                                                                                                                                                                                                                       | workflow-nodes, đợt sau (W2)                          |
| Egress client từ chối mọi chế độ khác `live` (W2 mở ngoại lệ cho Danh sách người nhận thử); phân loại `simulate_safe` theo loại công cụ                               | Lớp thứ hai sau executor (ADR-0111 (Accepted) quyết 3; DO-26.1); ADR-0116 (Accepted)                                                                                                                                                                                                                                         | connections-and-vault; tools-and-skills               |
| Đưa `record_visibility`, `max_autonomy_level`, `timezone`, `locale` của `platform.tenants` vào phiên bản có duyệt                                                     | Đổi hành vi ngoài Studio                                                                                                                                                                                                                                                                                                     | không làm                                             |
| Lớp cấu hình thứ ba theo workspace                                                                                                                                    | `TenantOverlay` giữ hai lớp; thành phần của một workspace là thành phần Studio riêng (ADR-0110 (Accepted))                                                                                                                                                                                                                   | không làm                                             |

## Dữ liệu

Mọi bảng có `tenant_id`: RLS ENABLE và FORCE chỉ theo tenant (định nghĩa toàn tenant, ADR-0100 (Accepted)
quyết 5), grant cùng migration, tên ràng buộc theo `NAMING_CONVENTION`, revision id hex ngẫu nhiên. Mỗi bảng
không có `workspace_id` có một dòng lý do trong danh sách bảng toàn tenant của `test_rls_coverage.py`
(DO-01): `studio.artifacts`, `studio.artifact_versions`, `studio.definition_manifests`,
`studio.dependencies`, `platform.run_manifests`, `platform.run_manifest_keys`.

- `studio.artifact_kinds`: danh mục loại của nền tảng, không có `tenant_id`; `kind text` là khóa chính;
  ticket đăng ký một loại INSERT một dòng trong migration của nó, cùng lúc với mục `ArtifactKindRegistry`;
  `dw_app` chỉ SELECT.
- `studio.artifacts`: `id` UUIDv7; `kind` FK tới `studio.artifact_kinds (kind)` ON DELETE RESTRICT, có
  index; `api_name` `^[a-z][a-z0-9_]{1,39}$`, unique `(tenant_id, kind, api_name)` khi `deleted_at IS NULL`;
  FK `(tenant_id, owning_workspace_id)` tới `platform.workspaces (tenant_id, id)` ON DELETE RESTRICT, qua
  `uq_workspaces_tenant_id_id` do org-and-principals/01 tạo;
  `labels text[] NOT NULL DEFAULT '{}'` (bộ lọc `label` của danh sách đọc); `origin jsonb` NULL
  (domain-packs ghi và đọc nguồn gốc gói); `last_version_no integer NOT NULL DEFAULT 0`;
  `row_version integer NOT NULL`; `deleted_at timestamptz` NULL; `created_at`, `updated_at`
  `timestamptz NOT NULL`; index danh sách `(tenant_id, kind, updated_at DESC, id)`.
- `studio.artifact_versions`: `stage` NOT NULL CHECK (`draft`, `evaluating`, `awaiting_approval`,
  `live`, `retired`), không DEFAULT; `version_no` NULL chỉ khi `stage = 'draft'`, unique
  `(artifact_id, version_no)`; một dòng `draft` mỗi thành phần (partial unique); `document_schema`
  `^dw\.[a-z_]+/v[0-9]+$`; `document` là jsonb object tối đa 1 MiB, `CHECK (document::text IS NFC NORMALIZED)`;
  `content_hash`, `definition_hash` khớp `^sha256:[0-9a-f]{64}$`, `definition_hash` NOT NULL ngoài
  `draft`; `row_version integer NOT NULL`; `artifact_id` FK CASCADE; `based_on_version_id` FK
  ON DELETE SET NULL; `change_note` NULL.
- `studio.definition_manifests`: khóa chính `(tenant_id, hash)`, `body` jsonb NFC tối đa 1 MiB, chỉ
  INSERT.
- `studio.dependencies`: `from_version_id`, `from_artifact_id` FK CASCADE; `to_kind` CHECK (`artifact`,
  `field`, `picklist_value`, `platform_artifact`, `connector`, `mcp_tool`, `binding`, `node_type`);
  `to_key`, `to_version`, `to_hash`; `to_artifact_id`, `to_version_id` FK RESTRICT, mỗi FK một index;
  `usage` CHECK (`read`, `write`, `compare`, `invoke`, `bind`, `display`); `path` con trỏ JSON; index
  `(tenant_id, to_kind, to_key)`; `to_field_id` và FK của nó do custom-objects thêm cùng bảng field.
- `platform.worker_runs`: `run_mode text NOT NULL` CHECK (`live`, `test`, `simulate`), không DEFAULT,
  dòng cũ backfill `live`; `run_manifest_hash` NULL, khớp `^sha256:[0-9a-f]{64}$`, FK
  `(tenant_id, run_manifest_hash)` tới `platform.run_manifests` ON DELETE RESTRICT, có index.
- `platform.tool_executions.status`: CHECK của foundations-hardening/04 thêm `simulated`.
- `platform.run_manifests`: khóa chính `(tenant_id, hash)`, `body` jsonb NFC tối đa 1 MiB, ghi bằng
  `INSERT ... ON CONFLICT DO NOTHING`, `dw_app` chỉ SELECT và INSERT. `platform.run_manifest_keys`: FK
  tới bản kê ON DELETE CASCADE; `artifact_version_id` và `config_version_id` FK RESTRICT, đúng một cột
  khác NULL.
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
  `api_name_taken`, `api_name_immutable`, `artifact_in_use`, `no_checker_available`, `proposal_open`, `decision_stale`,
  `binding_unset`, `binding_degraded`. `Idempotency-Key` theo ADR-0108 (Accepted) quyết 4.

## Kiểm soát

| #    | Kiểm soát                                                           | Yêu cầu                      | Test âm                                                                                                                                                                                |
| ---- | ------------------------------------------------------------------- | ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TC1  | Nội dung phiên bản chỉ đổi khi ở `draft`                            | R2.9                         | `dw_app` UPDATE `document` của phiên bản `live` → trigger từ chối; gỡ trigger → test đỏ                                                                                                |
| TC2  | Số phiên bản cấp tuần tự, không cấp lại                             | R2.7, R2.8                   | Hai lần niêm phong đồng thời một nháp → một thành công, không số nào cấp hai lần; phiên bản quay về `draft` rồi niêm phong lại → số mới; bỏ khóa dòng `last_version_no` → test đỏ      |
| TC3  | Một nháp mỗi thành phần, khóa lạc quan                              | R2.5                         | `PUT` nháp với `If-Match` cũ → 412 `stale_version`, nháp không đổi; INSERT nháp thứ hai → lỗi partial unique; bỏ so `row_version` → test đỏ                                            |
| TC4  | Tên API bất biến sau lần phát hành đầu                              | R2.10                        | `PATCH` `api_name` khi đã có phiên bản từng `live` → 409 `api_name_immutable`; UPDATE thẳng bằng `dw_app` → trigger từ chối                                                            |
| TC5  | Không xóa thành phần đang được dùng                                 | R3.3                         | Xóa mềm đối tượng mà phiên bản `live` của một quy trình ở workspace khác dùng → 409 `artifact_in_use`; DELETE cứng → lỗi FK; gỡ trigger → test xóa mềm đỏ                              |
| TC6  | Nơi đang dùng ghi cùng giao dịch niêm phong                         | R3.1                         | Lỗi chèn giữa giao dịch niêm phong → không số phiên bản, không dòng phụ thuộc; làm hỏng bộ trích xuất của loại fixture → test fixture đỏ                                               |
| TC7  | Nơi đang dùng không lộ tên ngoài quyền                              | R3.4                         | Người chỉ đọc được ở ws1 thấy tên bên phụ thuộc ở ws1, phần ở ws2 chỉ là số đếm; tenant B → 404                                                                                        |
| TC8  | Một hàm dạng chuẩn, đóng khi lỗi                                    | R1.1, R1.2, R1.3, R1.4, R1.5 | `{"a": 1.0}`, `2**53`, chuỗi NFD → đúng mã lỗi, không mã băm; đổi thứ tự sắp khóa sang code point → test vi sai đỏ trên khóa ngoài BMP                                                 |
| TC9  | Chế độ chạy do máy chủ đặt, cột không mặc định, lượt con không nới  | R4.1, R4.2, R4.4             | INSERT `worker_runs` thiếu `run_mode` → lỗi NOT NULL; `RunContext` dựng không chế độ gọi công cụ `external` → bị giả lập; cha `simulate`, con xin `live` → `simulate`                  |
| TC10 | Tiếp tục lượt chạy giữ chế độ                                       | R4.5                         | Lượt `simulate` chờ duyệt rồi tiếp tục → công cụ vẫn giả lập; bỏ `run_mode` khỏi chỗ dựng lại ngữ cảnh khi tiếp tục → test đỏ                                                          |
| TC11 | Executor giả lập ở `simulate` và `test`                             | R5.1, R5.2, R5.3, R5.5       | Gọi thẳng ToolExecutor, không qua node, với công cụ `external` ở `simulate` → handler không chạy, `status` `simulated`, audit `tool.simulated`; gỡ bước chế độ → test đỏ               |
| TC15 | Bản kê ghim, không lùi về bản hiện hành, không bị dọn, không bí mật | R6.3, R6.4, R6.5, R7.4, R7.5 | Niêm phong phiên bản mới khi lượt chạy chờ duyệt → lượt tiếp tục với bản ghim; khóa không ghim → bị từ chối; DELETE phiên bản được ghim → lỗi FK; token mẫu không có trong `body`      |
| TC16 | Người đề xuất không tự duyệt                                        | R8.8                         | Người đề xuất quyết → 409; UPDATE `decided_by = proposed_by` → CHECK từ chối; bỏ `config.` khỏi prefix nghiêm → test đỏ                                                                |
| TC17 | Có hiệu lực chỉ qua yêu cầu phê duyệt đã duyệt, quyết toán một lần  | R8.10, R8.12, R8.15          | UPDATE `status = 'approved'` khi yêu cầu còn `pending` → trigger từ chối; `dw_app` UPDATE `document` → permission denied; giao lại sự kiện → không dòng, không audit mới               |
| TC18 | Một đề xuất mở, luôn có người duyệt khác                            | R8.5, R8.6                   | Đề xuất thứ hai cùng khóa → 409 `proposal_open`; workspace chỉ Người đề xuất giữ quyền duyệt → 409 `no_checker_available`; không dòng nào được ghi                                     |
| TC19 | Chỉ loại đã đăng ký, không sang tenant khác                         | R8.3, R8.7                   | Đề xuất loại `prompt` → 422, ghi thẳng → CHECK `kind` từ chối; tenant B đọc hay đề xuất trên thành phần của tenant A → 404                                                             |
| TC20 | Quyết định cũ bị từ chối, quyết toán không ghi đè                   | R8.9, R8.11                  | Niêm phong phiên bản đổi khai báo điểm gắn giữa đề xuất và quyết định → 409 `decision_stale`, yêu cầu vẫn `pending`; gỡ guard → test đỏ; quyết toán gặp bản khác đã duyệt → `rejected` |
| TC21 | Offboarding xóa hết dữ liệu Studio của tenant                       | R3.6                         | Tenant có hai thành phần phụ thuộc nhau, bản kê và phiên bản cấu hình riêng → purge xong, tenant khác nguyên; gỡ một mục thứ tự → test đỏ                                              |
| TC22 | Không phát hành, không nhận lượt chạy khi điểm gắn thiếu hay hỏng   | R7.2, R7.3                   | Phiên bản thiếu giá trị `zalo_oa` → `binding_unset`; kết nối bị thu hồi → nhận lượt chạy bị từ chối `binding_degraded`, không node nào chạy                                            |
| TC23 | Tài liệu không chứa id kết nối                                      | R7.1                         | Niêm phong tài liệu có UUID của một kết nối ở chỗ tên điểm gắn → 422 có con trỏ; gỡ kiểm → test đỏ                                                                                     |
| TC24 | Mỗi route thành phần kiểm tenant và quyền theo độ sâu               | R2.11, R2.12                 | Người chỉ đọc được ở ws1 GET thành phần của ws2 ngoài độ sâu → 404; `PUT` nháp không có quyền ghi → 403; tenant B → 404                                                                |
| TC25 | Chỉ người có quyền đề xuất và dùng được kết nối mới đề xuất được    | R8.2, R8.4                   | Thiếu `studio.bindings.propose` → 403; kết nối Người đề xuất không dùng được → 422; không dòng nào được ghi                                                                            |
| TC26 | Chỉ Người đề xuất rút được đề xuất                                  | R8.14                        | Người khác gọi `withdraw` → 403, đề xuất và yêu cầu phê duyệt không đổi; bỏ so `proposed_by` → test đỏ                                                                                 |
| TC27 | Chỉ loại khai không có Cổng chất lượng mới bỏ qua `evaluating`      | R2.13, R2.14                 | Mục `fixture` không nêu cờ cổng → niêm phong sang `evaluating`; mục `fixture_gateless` khai không cổng → `awaiting_approval`; đổi giá trị mặc định của cờ sang không cổng → test đỏ    |

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
  `platform.connections` và `connection_usable` (ADR-0115 (Accepted)) cho ticket 05;
  connections-and-vault/03 cho egress client từ chối mọi chế độ khác `live`.
- `.claude/plans/studio/org-and-principals/issues/01-khoa-don-vi-va-siet-realm.md`: tạo
  `uq_workspaces_tenant_id_id` cho FK ghép của `studio.artifacts`; ticket 02 không tạo ràng buộc đó (OPS-a.2).
- `.claude/plans/studio/foundations-hardening/issues/06-run-va-outbox-khong-ket.md`: CHECK `status` của yêu
  cầu phê duyệt và đường tiếp tục ở `approval_flow.py` mà ticket 05 đổi sau (OPS-b).
- tenant-rbac: khóa `studio.<area>.<verb>` đăng ký trong migration của cụm (tenant-rbac/01), độ sâu qua
  `platform.effective_grants` (tenant-rbac/02, ADR-0104 (Accepted) quyết 5), và hàm SQL chung
  `platform.checker_candidates` của tenant-rbac/02 trả người `active` giữ một quyền mà khác Người đề xuất, dùng
  cho `no_checker_available` của cả R8.5 lẫn tenant-rbac:R7.3 (D:tenant-config/05~tenant-rbac:R7.1); app-standards/03: ETag, `If-Match`, 412 và 428
  (ADR-0108 (Accepted) quyết 3).
- agent-lifecycle: `studio.guard_version_stage()` cho phép `draft` sang `awaiting_approval` với loại không có
  Cổng chất lượng (agent-lifecycle:R1.6), và loại phê duyệt `studio.publish.object` (ADR-0120 (Accepted)
  quyết 2; R2.13).
- Protocol do bên dùng khai: `RunManifestPort` (runtime khai, Studio đáp ứng); kiểm điểm gắn cho việc
  phát hành (agent-lifecycle khai, ticket 05 đáp ứng); `RunBindingsPort` (connections-and-vault và handler
  của lượt chạy khai, ticket 05 đáp ứng từ bản kê, ADR-0110 (Accepted)); `ConnectionDependentsPort`
  (connections-and-vault khai, ticket 05 đáp ứng, R3.7); lệnh gửi kiểm định của agent-lifecycle/03 gọi bước
  niêm phong của ticket 02.
- Bảng toàn tenant theo `CLAUDE.md` "Tenancy and authorization", sửa cùng lúc Đạt nhận ADR-0100 (Accepted)
  và DO-01 ngày 23/10/2026: bảng không có `workspace_id` có lý do trong `test_rls_coverage.py` (mục Dữ
  liệu). Hai ghim theo `CLAUDE.md` "Non-negotiable architecture" và "Per-tenant artifacts", sửa cùng lúc Đạt
  nhận ADR-0109 (Accepted) và ADR-0120 (Accepted): release manifest ghim lớp nền tảng, bản kê ghim lượt
  chạy Studio, và thành phần Studio phân giải qua bản kê chứ không qua `TenantOverlay`. Giá trị `test` của
  chế độ chạy không bao giờ được so với profile `test` (`CLAUDE.md:319`); cổng triển khai vẫn đọc
  `settings.is_deployed`.
- Giá trị biến của Bộ giá trị gắn là chữ do tenant viết: prompt nào nội suy nó thì `PromptRegistry` bọc
  như mọi biến (ADR-0010 (Accepted)); spec này chỉ kiểm kiểu và chỉ ghim mã băm của nó.
- Kiểm lại khi: tenant-rbac đổi cách tính quyền (DO-09) hay đổi hàm tìm người duyệt chung → ticket 02, 04,
  05; agent-lifecycle/03 đổi hợp đồng niêm phong, cột `stage` hay luật chuyển giai đoạn của loại không có
  Cổng chất lượng → R2.13, ticket 02; `connection_usable` đổi hình → ticket 05; một node W1 gửi thông báo
  qua kênh chat từ lượt không `live` → TC12-TC14 kéo về W1.

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
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: ADR-0109 (Accepted) nói lưu nháp cũ trả 409
  `stale_version`, ADR-0108 (Accepted) nói `If-Match` lệch trả 412; theo ADR-0108 (Accepted) cho mã
  HTTP, giữ `stale_version` làm `details.reason_code`. Sửa: R2.5.
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

## Danh sách ticket

| #   | Ticket                                                                                                                           |
| --- | -------------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Băm chuẩn hóa JCS (RFC 8785) một chủ trong dw_kernel](issues/01-bam-chuan-hoa-jcs.md)                                           |
| 02  | [Vỏ phiên bản dùng chung và chỉ mục phụ thuộc ghi trong giao dịch gửi kiểm định](issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md) |
| 03  | [Chế độ chạy trên mỗi lượt chạy và executor giả lập ở chế độ Mô phỏng](issues/03-che-do-chay-va-gia-lap-o-executor.md)           |
| 04  | [Bản kê lượt chạy: ghim mọi thứ lượt chạy dùng, phân giải theo bản kê](issues/04-ban-ke-luot-chay.md)                            |
| 05  | [Điểm gắn: giá trị là phiên bản cấu hình có người đề xuất và người duyệt khác nhau](issues/05-lien-ket-va-phien-ban-cau-hinh.md) |
