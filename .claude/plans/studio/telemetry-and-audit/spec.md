# Telemetry, lịch sử chạy và nhật ký kiểm toán

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Người dựng cần xem một lượt chạy đã làm gì theo từng bước (trạng thái, thời gian, lỗi, token, chi phí, đầu vào và đầu
ra), cổng kiểm định cần kết quả từng bước, nhưng chưa có kho nào cho công ty giữ việc đó dưới RLS; telemetry hiện phát
tên lệch spec GenAI và có thể mang nội dung. Lát này đưa một module ánh xạ OTel GenAI ghim commit chỉ mang định danh,
một trace id đi từ trình duyệt tới worker, một kho Lịch sử chạy theo bước che bí mật khi ghi và che theo quyền đọc
trường của người xem khi đọc, có dòng cho Bước đang chờ và đọc thành cây với lý do có nhãn tiếng Việt (V4.36), nhãn
một mảnh mỗi spec (H-21), và chính sách lưu giữ một mảnh mỗi kho (H-1) (ADR-0122 (Accepted), ADR-0106 (Accepted)). W1
phục vụ YC23, YC80, YC81 và một phần YC82 (ghi `run.payload.viewed`) và YC88, cùng màn sự cố của YC109 ở bậc B của
V4.26, và cho người dựng đọc lượt mô phỏng do chính mình xin (V4.41); lọc và xuất Nhật ký kiểm toán (YC83), Langfuse
cho Người vận hành và Ghi nội dung theo công ty thuộc W2.

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- Bảy metric `dw_*` khai mà không có nơi phát: `dw_run_duration_seconds`, `dw_node_failure_total`,
  `dw_tool_call_total`, `dw_approval_wait_seconds`, `dw_retrieval_hit_rate`, `dw_human_intervention_rate`,
  `dw_task_success_rate` (`packages/python/dw_observability/src/dw_observability/metrics.py:12-22`).
  Thiếu: một tên khai mà không phát là điều một lần grep tên không thấy (`failure-modes.md` #0, #1).
- Span lời gọi model đặt khóa đã bị bỏ `gen_ai.system`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/telemetry_usage.py:60`). Ràng buộc:
  GenAI semconv nay ở kho riêng và còn ở trạng thái Development, phải ghim một commit thay vì theo tên trôi.
- `RunContext.trace_id` là chuỗi `api-<hex12>` (`apps/api/src/dw_api/bootstrap/container.py:227`), và
  `resume-`, `lookup-` ở lối phê duyệt
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:302`, `:394`). Ràng buộc: không
  phải trace id W3C 32 hex, nên không nối được một trace xuyên trình duyệt, API và worker.
- `/runs` có `GET /{run_id}` và `GET /{run_id}/timeline` nhưng không kho bước, không danh sách, không xem
  payload (`apps/api/src/dw_api/routes/v1/runs.py:41-68`). Thiếu: một kho Lịch sử chạy theo bước cho công ty.
- Checkpoint là trạng thái LangGraph tuần tự hóa bằng `JsonPlusSerializer`, không che, xóa sau lượt chạy
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/checkpoint.py:56-60`). Ràng buộc: không
  dùng làm Lịch sử chạy cho công ty.
- Nhật ký kiểm toán `list_for_run` chặn cứng 100 dòng, không lọc phía máy chủ
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/repositories.py:234-244`); trang
  `/audit` lọc phía client (`apps/web/app/audit/page.tsx:40`). Ràng buộc: lọc và xuất là W2.
- Màn `/audit` giữ bảng nhãn và màu riêng `ACTIONS` cho sáu action, action ngoài bảng hiện `Hoạt động hệ thống`
  (`apps/web/app/audit/page.tsx:15-25`), còn `GET /api/v1/audit/events` chỉ trả mã `action`
  (`apps/api/src/dw_api/routes/v1/audit.py:27`). Thiếu: một chủ cho nhãn action; khi có catalog hành động của
  ADR-0122 (Accepted) quyết 6, bảng đó là bản sao thứ hai (`failure-modes.md` #2).
- Tính năng `audit_export` khai trong gói nhưng không mã sản xuất nào đọc
  (`packages/python/dw_platform/src/dw_platform/application/entitlement.py:33`). Thiếu: bên đọc
  (`failure-modes.md` #1); xuất là W2.
- Thời hạn Nhật ký kiểm toán dẫn Nghị định 13/2023 đã hết hiệu lực
  (`configs/policies/retention@1.7.0.yaml:118-120`). Ràng buộc: dẫn lại theo PDPL và Nghị định 356
  (compliance-pdpl).

## Mục tiêu

### R1 — Telemetry chỉ mang định danh, không nội dung

Người vận hành và hệ thống quan sát nhận span, log và metric chỉ có định danh và tên trường.

- R1.1 NẾU một thành phần phát một tên span, khóa thuộc tính hay tên metric GenAI không có trong ảnh chụp
  đã ghim của `dw_observability.semconv`, THÌ test hợp đồng PHẢI đỏ và không nhận tên đó.
- R1.2 Một span, một dòng log, một sự kiện Nhật ký kiểm toán hay một thông điệp lỗi PHẢI chỉ chứa định
  danh và tên trường, không chứa giá trị trường, nội dung prompt hay đầu ra.
- R1.3 NẾU một tên metric khai trong `ALL_METRICS` không có lời gọi phát nào trong `src/`, THÌ test AST
  PHẢI đỏ.
- R1.4 KHI Langfuse được bật, span processor PHẢI bỏ `user.id` và mọi thuộc tính nội dung trước khi gửi
  sang Langfuse.
- R1.5 Một dòng log JSON của API hay worker PHẢI chỉ mang các trường trong danh sách định danh cho phép.
- R1.6 NẾU mã trong `src/` ghi một sự kiện Nhật ký kiểm toán với một `action` không có khóa mang nhãn tiếng Việt khác
  rỗng trong catalog hành động, hợp của các mảnh `configs/copy/audit_actions.d/<spec>.yaml` đang ghim, THÌ test AST
  PHẢI đỏ và nêu `action` đó (ADR-0122 (Accepted) quyết 6; H-21).
- R1.7 KHI `GET /api/v1/audit/events` trả một trang sự kiện, API Nhật ký kiểm toán PHẢI mang trên mỗi sự kiện
  `action_label`, nhãn tiếng Việt của `action` đó trong catalog hành động gộp từ tập mảnh đang ghim, hay NULL khi
  catalog không có khóa của `action` đó (ADR-0122 (Accepted) quyết 6; H-21).
- R1.8 KHI màn `/audit` hiện một sự kiện Nhật ký kiểm toán, màn `/audit` PHẢI hiện ở cột Thao tác đúng
  `action_label` mà API trả cho sự kiện đó, hay `Hoạt động hệ thống` khi trường đó NULL, vì catalog là chủ duy nhất
  của nhãn action (`failure-modes.md` #2).
- R1.9 NẾU mã trong `src/` ghi lên một lượt chạy hay một Bước chạy một `reason_code` hay `error.code` không có khóa mang
  nhãn tiếng Việt khác rỗng trong catalog mã lý do, hợp của các mảnh `configs/copy/run_reason_codes.d/<spec>.yaml` đang
  ghim, kể cả mã mà một loại Bước trả về để wrapper ghi chứ không chỉ chuỗi ở chỗ ghi, THÌ test AST PHẢI đỏ và nêu
  mã đó (H-12; H-21; `failure-modes.md` #0).
- R1.10 NẾU hai mảnh của cùng một catalog nhãn, `configs/copy/audit_actions.d/` hay `configs/copy/run_reason_codes.d/`,
  cùng khai một khóa, THÌ bộ nạp catalog PHẢI từ chối nạp catalog đó và nêu khóa cùng hai mảnh, kể cả khi hai nhãn giống
  nhau, vì mỗi nhãn có đúng một mảnh là chủ (H-21; `failure-modes.md` #2).
- R1.11 KHI release manifest được dựng, release manifest PHẢI ghim mã băm sha256 của tập mảnh
  `configs/copy/audit_actions.d/` và của tập mảnh `configs/copy/run_reason_codes.d/`, mỗi tập một mục, nên sửa một mảnh
  mà không dựng lại manifest làm kiểm manifest của CI đỏ (H-21).

### R2 — Một trace id từ trình duyệt tới worker, cây span thật

Người vận hành truy được một lượt chạy qua một trace id duy nhất từ trình duyệt tới worker.

- R2.1 KHI một lượt chạy thực thi, runner PHẢI mở cây span `invoke_workflow`, `dw.node`, `invoke_agent`,
  `chat`, `execute_tool` và `retrieval`, mỗi span mang `dw.run_mode`, `dw.run_manifest_hash`, id công ty
  và id workspace, không mang câu hỏi truy xuất.
- R2.2 KHI một request mang header `traceparent`, API và worker PHẢI dùng chung một trace id 32 ký tự hex
  trên span, `platform.worker_runs`, `platform.audit_events` và dòng `platform.outbox_events`.
- R2.3 `RunContext.trace_id` PHẢI khớp `^[0-9a-f]{32}$`, thay cho tiền tố `api-`, `resume-` và `lookup-`
  hiện tại.
- R2.4 KHI một phản hồi lỗi `application/problem+json` trả về, API PHẢI đặt vào trường `trace_id` của vỏ
  lỗi (app-standards:R1.2) đúng trace id 32 ký tự hex của request.

### R3 — Kho Lịch sử chạy theo bước, che khi ghi và khi đọc

Người dựng có một kho `platform.run_steps` cho mỗi Bước chạy, che bí mật khi ghi và che theo quyền đọc
trường của người xem khi đọc.

- R3.1 KHI một node, lời gọi model, lời gọi công cụ, phê duyệt hay lượt chạy con kết thúc,
  `StepRecorderPort` PHẢI ghi đúng một Bước chạy mang trạng thái, thời điểm, thời lượng, loại lỗi, token và
  chi phí.
- R3.2 KHI ghi một Bước chạy, `StepRecorderPort` PHẢI bỏ trường bí mật và tham chiếu credential, che trường
  `Nhạy cảm`, và ghi lại từng quyết định che.
- R3.3 KHI một người đọc payload của một Bước chạy, Lịch sử chạy PHẢI che mỗi trường người đó không có
  quyền đọc và trả dấu `Đã ẩn` tại chỗ (ADR-0106 (Accepted) quyết 4).
- R3.4 ĐỐI VỚI một payload trên 4 KB, `StepRecorderPort` PHẢI lưu phần thân theo tham chiếu dưới đường dẫn
  đối tượng gắn công ty và workspace (4 KB thì giữ trong dòng, 4 KB cộng một byte thì theo tham chiếu).
- R3.5 KHI một người mở payload của một Bước chạy, API Lịch sử chạy PHẢI ghi đúng một sự kiện
  `run.payload.viewed` trong cùng giao dịch.
- R3.6 NẾU một người đọc Bước chạy hay lượt chạy của công ty khác, hay một lượt chạy chạm tới bản ghi người
  đó không thấy, THÌ API Lịch sử chạy PHẢI trả 404 và không lộ dòng nào.
- R3.7 KHI `StepRecorderPort` ghi một Bước chạy thuộc một lần chạy Bước của lượt quy trình, `StepRecorderPort` PHẢI
  ghi trên Bước chạy đó đường làn (`lane_path`) và `iteration_path` mà wrapper nút cấp cho lần chạy Bước ấy, với
  `iteration_path` bằng đúng giá trị trong khóa chống lặp `wf:{run_id}:{node_id}:{iteration_path}` của lần chạy đó
  (workflow-engine:R4.5; V4.26).
- R3.8 KHI wrapper nút báo qua `StepRecorderPort` rằng một Bước đỗ ở một điểm chờ, `StepRecorderPort` PHẢI ghi trong
  giao dịch của bên gọi một Bước chạy `status` `waiting` mang `reason_code` của điểm chờ cùng `attempt`, `lane_path` và
  `iteration_path` của lần chạy Bước, nên Bước đang chờ có dòng từ lúc đỗ, trước dòng kết thúc của R3.1 (V4.36).
- R3.9 KHI `StepRecorderPort` ghi một Bước chạy thuộc một lần chạy Bước, `StepRecorderPort` PHẢI ghi trên Bước chạy đó
  `attempt` (lần thử, từ 1) mà wrapper nút cấp, `port` là Nhánh ra mà Bước đã đi khi nó chọn một Nhánh ra (khóa nhánh
  của `switch`, làn quyết định của phê duyệt, làn lỗi), và `child_run_id` khi nó mở một lượt con, không tự tính giá trị
  nào (V4.36; H-11).
- R3.10 NẾU một lệnh ghi của `dw_app` gắn công ty A đặt `child_run_id` của một Bước chạy bằng id một lượt chạy của công
  ty B, THÌ PostgreSQL PHẢI từ chối lệnh đó bằng FK ghép `(tenant_id, child_run_id)` và không ghi dòng nào (CLAUDE.md,
  mục Tenancy and authorization).

### R4 — Màn Lịch sử chạy đọc dưới `runs.read` theo độ sâu, thành cây, và lượt mô phỏng của chính người dựng [Sửa]

Người giữ `runs.read` xem danh sách lượt chạy và chi tiết từng bước trong tập workspace được phép, thành một cây có chỗ
đang chờ và lý do bị giữ; người giữ `studio.workflows.test` đọc Bước chạy và chi tiết của lượt mô phỏng do chính mình
xin (V4.36, V4.41).
Trước đây: `GET /api/v1/runs/{run_id}` và `.../timeline` chỉ kiểm `runs.read` và trả 403 khi thiếu, không có danh sách hay Bước chạy (`apps/api/src/dw_api/routes/v1/runs.py:47-52`).

- R4.1 KHI người giữ `runs.read` gọi `GET /api/v1/runs`, API Lịch sử chạy PHẢI trả các lượt chạy trong tập
  workspace được phép theo độ sâu, phân trang keyset mà trang kế không trùng và không sót dòng.
- R4.2 KHI người giữ `runs.read` gọi `GET /api/v1/runs/{run_id}/steps`, API Lịch sử chạy PHẢI trả các Bước
  chạy của lượt đó theo thứ tự `seq`, mỗi Bước chạy mang `status`, `lane_path`, `iteration_path`, `attempt`, `port`,
  `child_run_id` và `reason_code` đã ghi (R3.7, R3.8, R3.9).
- R4.3 NẾU người gọi `GET /api/v1/runs/{run_id}/steps/{step_id}/payload` thiếu `runs.read_payloads`, THÌ
  API Lịch sử chạy PHẢI trả 403 và không trả payload.
- R4.4 KHI người giữ `studio.workflows.test` tới workspace của lượt theo độ sâu (ADR-0104 (Accepted) quyết 3) gọi
  `GET /api/v1/runs/{run_id}/steps` hay `GET /api/v1/runs/{run_id}` cho một lượt `simulate` có `requested_by` là chính
  người đó, API Lịch sử chạy PHẢI trả các Bước chạy hay chi tiết của lượt đó dù người đó không giữ `runs.read`, mỗi giá
  trị trường mà người đó không có quyền đọc thay bằng dấu `Đã ẩn` như R3.3 (V4.41); payload của các Bước chạy đó vẫn
  theo R4.3: thiếu `runs.read_payloads` thì 403 (Đạt, Q-h4).
- R4.5 NẾU người gọi `GET /api/v1/runs/{run_id}/steps` hay `GET /api/v1/runs/{run_id}` không giữ `runs.read` tới
  workspace của lượt, và lượt đó không phải lượt `simulate` mà chính người gọi xin trong khi giữ `studio.workflows.test`
  tới workspace đó (R4.4), THÌ API Lịch sử chạy PHẢI trả 404 giống hệt phản hồi cho một id không tồn tại và không lộ
  dòng nào (V4.41).
- R4.6 KHI API Lịch sử chạy trả `reason_code` hay `error_type` của một Bước chạy, ở `GET /api/v1/runs/{run_id}/steps`
  hay `GET /api/v1/runs/{run_id}/incidents`, API Lịch sử chạy PHẢI mang cạnh mỗi mã nhãn tiếng Việt của nó trong
  catalog mã lý do gộp từ tập mảnh đang ghim (`reason_label`, `error_label`), hay NULL khi mã NULL hay catalog không có
  khóa, vì catalog là chủ duy nhất của nhãn (H-12; H-21; `failure-modes.md` #2).
- R4.7 KHI màn `/runs/[id]` hiện một lượt, màn `/runs/[id]` PHẢI vẽ các Bước chạy thành cây antd `Tree` theo
  `lane_path`, mỗi lần lặp (`iteration_path`) và mỗi lần thử (`attempt`) một nút con, Bước mang `port` hiện tên Nhánh
  ra đã đi, và Bước có `child_run_id` mang liên kết tới `/runs/[child_run_id]` (V4.36).
- R4.8 TRONG KHI một lượt chưa kết thúc có một Bước mà dòng mới nhất là `waiting`, màn `/runs/[id]` PHẢI đánh dấu
  Bước đó "Đang chờ ở đây" trên cây kèm `reason_label` của nó, với `outcome_unknown` là "Không rõ nhà cung cấp đã nhận
  hay chưa" (V4.36; V4.30).
- R4.9 TRONG KHI một lượt đã kết thúc mà dòng mới nhất của một Bước vẫn là `waiting` với `reason_code`
  `outcome_unknown`, màn `/runs/[id]` PHẢI hiện ở Bước đó `effect_unresolved_label` mà API trả (R4.10), nhãn "Không rõ
  nhà cung cấp đã nhận hay chưa, chưa ai xác nhận" của khóa `effect_unresolved`, dù lượt kết thúc vì `deadline_at` hay
  bị hủy khi Tắt khẩn hay Đóng băng (H-6; H-22).
- R4.10 KHI `GET /api/v1/runs/{run_id}/steps` trả một lượt đã kết thúc mà dòng mới nhất của một Bước là dòng `waiting`
  mang `reason_code` `outcome_unknown`, API Lịch sử chạy PHẢI mang trên dòng đó `effect_unresolved_label`, nhãn của khóa
  `effect_unresolved` trong catalog mã lý do, và NULL trên mọi dòng khác, vì màn không giữ bảng nhãn nào (H-6; H-12).

### R5 — Lưu giữ có bộ xóa cho mỗi kho, không xóa lượt chạy còn sống

Mỗi kho lát này tạo, và các kho sự kiện vào mà lane lưu giữ của lát này đọc hạn, có một thời hạn và một bộ
xóa; lượt chạy chưa kết thúc hay còn được tham chiếu không bị xóa. Lát này là chủ định dạng của chính sách retention,
một mảnh `configs/policies/retention.d/<schema>.<table>.yaml` cho mỗi kho, và các lane lưu giữ (H-1); ticket nào tạo
hay đăng ký một kho thì thêm mảnh của kho đó trong cùng thay đổi, không chờ ticket nào vì mảnh, nên
studio-skeleton:R3.7 xanh ngay khi đăng ký, và release manifest ghim mã băm của tập mảnh; thời hạn và bộ xóa của sự
kiện vào, lần giao kích hoạt và khóa chống trùng do workflow-triggers/02 thêm, lane của lát này thi hành
(workflow-triggers:R6.3, workflow-triggers:R6.4, workflow-triggers:R6.7); mọi số là số tạm UNVERIFIED tới khi luật sư
xác nhận trước chạy bóng (ADR-0122 (Accepted) quyết 7; DO-52). Lát này cũng là chủ của `platform.retention_terms`, bản
ở runtime của các thời hạn trong tập mảnh đang ghim, mà bộ nạp của lát nạp lúc triển khai và mỗi hàm xóa hẹp không đối
số đọc hạn của mình ở đó, nên luật sư đổi số bằng một lần sửa mảnh của kho đó, không bằng code hay migration (V4.21).

- R5.1 ĐỐI VỚI mỗi kho dữ liệu cá nhân mới (`platform.run_steps`, payload đối tượng, cột payload của lượt
  chạy, Sổ sử dụng, `studio.inbound_events`, `studio.trigger_deliveries`), tập mảnh retention đang ghim PHẢI có mảnh
  của kho đó mang một thời hạn và một bộ xóa đã đăng ký.
- R5.2 NẾU một kho dữ liệu cá nhân không có bộ xóa đăng ký, THÌ test tập bộ xóa PHẢI đỏ.
- R5.3 NẾU một lượt chạy chưa kết thúc hay còn được `memory.items` trỏ tới, THÌ lane lưu giữ PHẢI bỏ qua
  nó và vẫn đếm nó.
- R5.4 ĐỐI VỚI một Bước chạy quá 30 ngày (YC88), lane lưu giữ PHẢI xóa payload của bước (preview trong dòng
  và đối tượng theo tham chiếu) dù partition của tháng đó chưa tới lúc DROP.
- R5.5 NẾU một sự kiện vào quá 30 ngày còn được một lượt chạy `queued` trỏ tới, hay đang bị làn `studio_inbound`
  giữ vì Đóng băng (chưa xin lượt chạy), THÌ lane lưu giữ PHẢI bỏ qua nó và đếm nó trên metric của lane theo lý
  do, vì Đóng băng không có trần thời gian (agent-lifecycle:R7.2).
- R5.6 NẾU tên một mảnh trong `configs/policies/retention.d/` không phải `<schema>.<table>` của một bảng có thật hay tên
  có tiền tố của một kho có tên (như `objects.run_step_payloads`), THÌ test tập mảnh PHẢI đỏ và nêu mảnh đó, nên hai
  bảng cùng tên ở hai schema không đụng nhau và một thời hạn không treo dưới một tên không canh gì
  (ADR-0100 (Accepted) quyết 7; H-1).
- R5.7 KHI `output` của một dòng `platform.tool_executions` quá thời hạn dưới khóa `platform.tool_executions` của
  `platform.retention_terms` (30 ngày), lane lưu giữ PHẢI xóa trắng cột đó qua một hàm SECURITY DEFINER hẹp không
  nhận đối số, chỉ đặt NULL `output` và đọc thời hạn ở bảng đó, mà không trả UPDATE trên bảng cho `dw_app`
  (runtime-hardening:R6.3; ADR-0122 (Accepted) quyết 7; V4.21).
- R5.8 KHI lane `offboarding` xóa dữ liệu của một công ty đang `offboarding`, lane `offboarding` PHẢI xuất rồi
  xóa mọi dòng `platform.run_steps` của công ty đó qua `platform.purge_tenant_append_only`
  (usage-and-limits:R3.10; YC6).
- R5.9 KHI một lần triển khai chạy migration, bộ nạp thời hạn PHẢI làm `platform.retention_terms` đúng bằng tập mảnh
  retention đang ghim trước khi `api` và `worker` khởi động: một dòng cho mỗi mảnh có thời hạn theo ngày và
  `enforced`, mang đúng thời hạn đó, không dòng nào khác (V4.21; H-1).
- R5.10 NẾU `platform.retention_terms` thiếu một khóa, thừa một khóa hay mang một thời hạn khác tập mảnh retention
  đang ghim, THÌ test lệch bảng PHẢI đỏ và nêu khóa đó (`failure-modes.md` #2).
- R5.11 NẾU `dw_app` chèn, sửa hay xóa một dòng `platform.retention_terms`, THÌ PostgreSQL PHẢI từ chối với
  `permission denied` và không đổi dòng nào (V4.21).
- R5.12 NẾU `platform.retention_terms` không có dòng của khóa mà một hàm xóa hẹp không đối số hỏi qua
  `platform.retention_term_days`, THÌ `platform.retention_term_days` PHẢI báo lỗi SQLSTATE `P0002` nêu khóa đó và
  không trả hạn nào, nên hàm xóa hẹp gọi nó dừng mà không xóa hay xóa trắng dòng nào (`failure-modes.md` #7).
- R5.13 Mô hình chính sách retention PHẢI đọc thời hạn của mỗi kho chỉ từ mảnh của kho đó trong tập mảnh đang ghim,
  nên một kho không có mảnh không có thời hạn nào, kể cả `platform.audit_events` mà ánh xạ tạm sang `retention@1.7.0`
  từng trả (H-1).
- R5.14 KHI release manifest được dựng, release manifest PHẢI ghim mã băm sha256 của tập mảnh trong
  `configs/policies/retention.d/` thay cho semver của một tệp, nên sửa một mảnh mà không dựng lại manifest làm kiểm
  manifest của CI đỏ (H-1).

### R6 — Màn sự cố trên Lịch sử chạy

Người dựng thấy một lượt quy trình đỗ ở một sự cố ngay trên Lịch sử chạy và giải nó bằng Chạy tiếp từ Bước lỗi hay Kết
thúc, biết trước rằng lượt chạy lại với Bộ giá trị gắn nó đã ghim (V4.35); route giải và trạng thái sự cố là của workflow-engine
(YC109; workflow-engine:R6.18 tới workflow-engine:R6.28; V4.26), màn và phần đọc là của lát này.

- R6.1 KHI người giữ `runs.read` gọi `GET /api/v1/runs/{run_id}/incidents` cho một lượt trong tầm của mình, API Lịch
  sử chạy PHẢI trả mọi sự cố `open` của lượt đó, mỗi sự cố mang `wait_id`, thời điểm mở, và `node_id` cùng loại lỗi
  của lần thử cuối của Bước lỗi, đọc từ Bước chạy `kind` `node` có `seq` lớn nhất mang `error_type` của lần thử đó,
  không từ `node_id` của dòng chờ, là node sự cố mà trình biên dịch dựng cho Bước lỗi (`platform.run_waits` ở mục Dữ
  liệu của workflow-engine), và không từ dòng `waiting` của Bước đó (R3.8).
- R6.2 NẾU lượt chạy của `GET /api/v1/runs/{run_id}/incidents` thuộc công ty khác hay ngoài tầm `runs.read` của người
  gọi theo độ sâu, THÌ API Lịch sử chạy PHẢI trả 404 và không lộ dòng nào.
- R6.3 KHI màn `/runs/[id]` hiện một lượt có sự cố `open`, màn `/runs/[id]` PHẢI hiện Bước lỗi cùng nút "Chạy tiếp từ
  Bước lỗi" gọi `POST /api/v1/runs/{run_id}/incidents/{wait_id}/resume` và nút "Kết thúc" gọi `.../end`, mỗi lần bấm
  mang một `Idempotency-Key` sinh cho lần bấm đó (workflow-engine:R6.19, workflow-engine:R6.20).
- R6.4 KHI màn `/runs/[id]` hiện một sự cố, màn `/runs/[id]` PHẢI hiện cạnh hai nút câu "Chạy tiếp dùng lại Bộ giá
  trị gắn mà lượt đã ghim, với phiên bản mới nhất chưa thu hồi của mỗi bí mật; sửa Bộ giá trị gắn sau khi lượt bắt đầu
  không có tác dụng với lượt này" (workflow-engine:R6.27; V4.35).
- R6.5 KHI lần thử cuối của Bước lỗi mang loại lỗi `outcome_unknown` (workflow-engine:R6.28), màn `/runs/[id]` PHẢI
  hiện cạnh nút "Chạy tiếp từ Bước lỗi", trước lần bấm, `error_label` mà API trả cho mã đó, "Không rõ nhà cung cấp đã
  nhận hay chưa" của catalog mã lý do (R4.6; H-12).
- R6.6 NẾU route giải sự cố trả 403, 404 hay 409, THÌ màn `/runs/[id]` PHẢI hiện thông báo tiếng Việt theo
  `details.reason_code` qua `App.useApp()` và giữ sự cố ở trạng thái `open` trên màn.

### R7 — Màn giải `outcome_review` trên Lịch sử chạy

Người giữ `runs.reconcile` thấy một lượt đỗ vì không rõ nhà cung cấp đã nhận hay chưa ngay trên Lịch sử chạy và chọn
"Đã nhận", "Chưa nhận, gửi lại cùng khóa" hay "Bỏ"; route giải, dòng chờ `outcome_review`, khóa `runs.reconcile` và
luật người giải là của workflow-engine (V4.30; H-8; workflow-engine:R6.30 tới workflow-engine:R6.36), màn và phần đọc là
của lát này, vì màn Lịch sử chạy có một chủ (V4.26).

- R7.1 KHI người giữ `runs.read` gọi `GET /api/v1/runs/{run_id}/outcome-reviews` cho một lượt trong tầm của mình, API
  Lịch sử chạy PHẢI trả mọi dòng chờ `outcome_review` `open` của lượt đó, mỗi dòng mang `wait_id`, thời điểm mở và
  `node_id` của Bước đang chờ, đọc từ Bước chạy `waiting` có `reason_code` `outcome_unknown` và `seq` lớn nhất của lượt
  (R3.8), không từ `node_id` của dòng chờ, là node xác nhận mà trình biên dịch dựng cho Bước đó (workflow-engine:R6.30).
- R7.2 NẾU lượt chạy của `GET /api/v1/runs/{run_id}/outcome-reviews` thuộc công ty khác hay ngoài tầm `runs.read` của
  người gọi theo độ sâu, THÌ API Lịch sử chạy PHẢI trả 404 và không lộ dòng nào.
- R7.3 KHI màn `/runs/[id]` hiện một lượt có dòng chờ `outcome_review` `open`, màn `/runs/[id]` PHẢI hiện ở Bước đó ba
  nút "Đã nhận", "Chưa nhận, gửi lại cùng khóa" và "Bỏ", mỗi nút gọi
  `POST /api/v1/runs/{run_id}/outcome-reviews/{wait_id}/resolve` với `decision` `received`, `resend` hay `abandon` và
  một `Idempotency-Key` sinh cho lần bấm đó (workflow-engine:R6.31).
- R7.4 NẾU người dùng chọn "Đã nhận" mà ô bằng chứng rỗng, THÌ màn `/runs/[id]` PHẢI không gửi yêu cầu nào và nêu ô
  bằng chứng còn thiếu, vì lần giải `received` mang bằng chứng (workflow-engine:R6.32).
- R7.5 NẾU route giải `outcome_review` trả 403, 404 hay 409, kể cả `second_person_required` của tác động `critical`,
  THÌ màn `/runs/[id]` PHẢI hiện thông báo tiếng Việt theo `details.reason_code` qua `App.useApp()` và giữ dòng chờ ở
  trạng thái `open` trên màn (workflow-engine:R6.35).

## Hành vi giữ nguyên

- G1 KHI người giữ `runs.read` gọi `GET /api/v1/runs/{run_id}` cho một lượt trong workspace của mình, API Lịch sử chạy
  PHẢI TIẾP TỤC trả lượt đó (test:
  `apps/api/tests/unit/test_run_and_audit_reads.py::test_the_callers_own_run_is_read`).

## Trong phạm vi

- Bảng, cột và phân vùng ở mục Dữ liệu; route ở mục API; màn ở mục Màn hình.
- Mã: `dw_observability.semconv` (tên span, khóa thuộc tính, tên metric GenAI, `GENAI_SEMCONV_COMMIT`);
  `TelemetryPort.record_histogram` với `OtelTelemetry`, `RecordingTelemetry`, `NullTelemetry`; span
  processor Langfuse; formatter log JSON có danh sách trường cho phép; `StepRecorderPort` và adapter ghi
  `platform.run_steps`; đọc Sổ sử dụng cho token và chi phí mỗi Bước chạy; định dạng mảnh retention (R5.6), bộ đọc
  tập mảnh của mô hình chính sách (R5.13), mã băm của tập trong release manifest (R5.14) và mảnh
  `platform.audit_events`, ở ticket 01 (H-1); các lane lưu giữ; mảnh của kho lát này tạo hay xóa mà không ticket đăng
  ký nào khác thêm (lớp run, bước, payload, `tool_executions.output`, `usage_daily`; DO-52); hàm SECURITY DEFINER hẹp
  không đối số xóa trắng `platform.tool_executions.output` (R5.7) và hàm SECURITY DEFINER hẹp không đối số xóa payload
  của Bước chạy quá hạn (R5.4), cả hai đọc hạn ở `platform.retention_terms`, ở ticket 03.
- Bảng `platform.retention_terms`, bộ nạp của nó chạy lúc triển khai dưới vai `dw_provisioner`, hàm đọc hạn
  `platform.retention_term_days(text)` mà mọi hàm xóa hẹp không đối số gọi, và test lệch bảng (R5.9, R5.10, R5.11,
  R5.12; V4.21), ở ticket 01, ticket sớm nhất của lát, để ticket nào cần hàm đọc hạn hay bộ nạp chỉ chờ ticket đó (H-1).
- Cột `attempt`, `port`, `child_run_id`, `reason_code` và dòng `waiting` của `platform.run_steps` (R3.8, R3.9, R3.10;
  V4.36), cây Bước chạy của `/runs/[id]` (R4.7-R4.9), nhãn trên API (R4.6, R4.10), và đường đọc của người dựng cho lượt
  mô phỏng do chính mình xin (R4.4, R4.5), ở ticket 03 (H-12; V4.41).
- Khóa quyền `runs.read_payloads` đăng ký ở ticket 03 theo quy ước của tenant-rbac/01.
- Route đọc `GET /api/v1/runs/{run_id}/incidents` và khối sự cố của màn `/runs/[id]` (R6), ở ticket 04; route giải sự
  cố là của workflow-engine.
- Route đọc `GET /api/v1/runs/{run_id}/outcome-reviews` và khối giải `outcome_review` của màn `/runs/[id]` (R7; V4.30),
  ở ticket 04; route giải, dòng chờ và khóa `runs.reconcile` là của workflow-engine/08.
- Thêm cột `trace_parent` cho `platform.outbox_events`; CHECK `trace_id` cho `platform.worker_runs` và
  `platform.audit_events`; đăng ký `run_steps` bằng một dòng `platform.time_partitioned_tables`.
- Audit: `run.payload.viewed`.
- Hai catalog nhãn theo mảnh, tạo ở ticket 03 (H-21): catalog hành động audit, các mảnh
  `configs/copy/audit_actions.d/<spec>.yaml` (ADR-0122 (Accepted) quyết 6), và catalog mã lý do, các mảnh
  `configs/copy/run_reason_codes.d/<spec>.yaml` (H-12); một bộ nạp catalog gộp mỗi tập và từ chối khóa trùng giữa hai
  mảnh (R1.10), release manifest ghim mã băm của mỗi tập (R1.11), và test AST của R1.6, R1.9. Mảnh
  `telemetry-and-audit.yaml` của mỗi catalog mang nhãn của lời ghi mà lát này đưa vào, của lời ghi có trước các spec
  Studio và của khóa `effect_unresolved` (R4.10). Catalog là chủ duy nhất của nhãn: `action_label` của
  `GET /api/v1/audit/events` (R1.7) và `reason_label`, `error_label`, `effect_unresolved_label` của Lịch sử chạy (R4.6,
  R4.10) đọc từ nó, và màn `/audit` hiện `action_label` thay bảng nhãn riêng của màn (R1.8).

## Ngoài phạm vi

| Việc                                                                                                                                                                                  | Vì sao                                                                                                                                                                                   | Chủ                                           |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| W2: Lọc Nhật ký kiểm toán phía máy chủ (YC83)                                                                                                                                         | cần bộ lọc; cơ chế của W1 không chặn; catalog hành động có từ ticket 03 (R1.6)                                                                                                           | telemetry-and-audit, đợt sau (W2)             |
| Index Nhật ký kiểm toán theo lượt chạy `platform.audit_events (tenant_id, run_id, workspace_id, occurred_at)` trên bảng cha                                                           | một chủ (OPS-b); `ix_audit_events_run` của ADR-0122 (Accepted) bỏ; ticket 02 chờ nó                                                                                                      | app-standards                                 |
| W2: Xuất Nhật ký kiểm toán qua tác vụ nền, link hết hạn 7 ngày (YC83)                                                                                                                 | YC83 ở W2; bên đọc đầu tiên của tính năng `audit_export` (ADR-0122 (Accepted) quyết 6)                                                                                                   | telemetry-and-audit, đợt sau (W2)             |
| W2: Langfuse chỉ cho Người vận hành, ghim theo digest, lên v4                                                                                                                         | không gửi nội dung thì không cần bản Enterprise                                                                                                                                          | telemetry-and-audit, đợt sau (W2)             |
| W2: Ghi nội dung theo công ty qua chính sách `telemetry.content_capture` có audit, giữ ≤ 7 ngày, chỉ công ty đọc                                                                      | DO-51.1; cần chính sách của tenant-config                                                                                                                                                | telemetry-and-audit, đợt sau (W2)             |
| W2: `traceparent` tới Cổng MCP (chặng nội bộ) nhưng không tới máy chủ MCP nào, không bao giờ `baggage`                                                                                | DO-46.3; mcp-client là W2; chỉ mở lại khi có nhà cung cấp trả span về nền tảng                                                                                                           | mcp-client; telemetry-and-audit, đợt sau (W2) |
| W3: Collector, lấy mẫu đuôi, bảng Grafana; chuỗi băm chống sửa, đẩy SIEM                                                                                                              | v1.5 trở đi                                                                                                                                                                              | telemetry-and-audit, đợt sau (W3)             |
| Bộ bọc node phát span và gọi `StepRecorderPort`                                                                                                                                       | lát này cấp `dw_observability.semconv` và `StepRecorderPort`                                                                                                                             | workflow-engine                               |
| Route giải sự cố (`.../incidents/{wait_id}/resume`, `.../end`), khóa `studio.workflows.resolve_incident`, dòng chờ `incident` và loại lỗi `outcome_unknown`                           | lát này chỉ đọc sự cố và vẽ màn (R6); trạng thái, quyền và chạy lại là của động cơ (workflow-engine:R6.18 tới workflow-engine:R6.28)                                                     | workflow-engine                               |
| Điểm chờ `outcome_review`, route giải dưới `runs.reconcile` ("Đã nhận", "Chưa nhận, gửi lại cùng khóa", "Bỏ"), luật người giải với tác động `critical`, audit `run.effect_unresolved` | lát này ghi dòng `waiting` của Bước đó, hiện chỗ chờ cùng nhãn lý do (R3.8, R4.8, R4.9) và vẽ ba nút gọi route giải (R7); trạng thái, quyền và lần giải là của động cơ (V4.30, H-6, H-8) | workflow-engine (ticket 08)                   |
| Nhận diện dữ liệu cá nhân tiếng Việt ở exporter (Presidio)                                                                                                                            | bộ dò là kiểm soát phụ, có số đo trước khi dựa vào                                                                                                                                       | compliance-pdpl, đợt sau (W2)                 |
| Điểm đánh giá trực tuyến (`gen_ai.evaluation.result`)                                                                                                                                 | dùng sự kiện GenAI nhưng thuộc cổng kiểm định                                                                                                                                            | agent-lifecycle                               |
| Sổ sử dụng theo lượt gọi và Bảng giá                                                                                                                                                  | lát này đọc token và chi phí từ sổ, không tạo sổ                                                                                                                                         | usage-and-limits                              |
| Sổ `platform.time_partitioned_tables` và hàm tạo partition                                                                                                                            | lát này chỉ đăng ký `run_steps` bằng một dòng sổ (studio-skeleton:R3.1)                                                                                                                  | studio-skeleton                               |
| Hàm quyết quyền đọc trường và dấu `Đã ẩn`                                                                                                                                             | lát này gọi hàm đó khi đọc payload                                                                                                                                                       | field-security                                |
| Trace thô cho công ty đọc                                                                                                                                                             | span ở backend không có RLS theo công ty; công ty đọc từ Postgres                                                                                                                        | không làm                                     |

## Dữ liệu

Mọi bảng gắn công ty: RLS ENABLE và FORCE theo công ty, grant cùng migration, tên ràng buộc theo
`NAMING_CONVENTION`, revision id hex ngẫu nhiên.

- `platform.run_steps`: phân vùng theo tháng trên `started_at` với DEFAULT; `PRIMARY KEY (id, started_at)`;
  `kind` CHECK (`node`, `model_call`, `tool_call`, `approval`, `sub_run`); gắn `tenant_id`, `workspace_id`,
  `run_id`, `root_run_id`, `seq int`, `node_id`, `lane_path jsonb NOT NULL` (CHECK mảng; mỗi phần tử là cặp id Bước
  chứa và tên Nhánh ra mà loại của Bước đó khai, từ chuỗi gốc của tài liệu tới làn chứa Bước, mảng rỗng ở chuỗi gốc
  và ở Bước chạy của lượt agent không nằm trong một Bước quy trình; không DEFAULT, để bên ghi quên cột thì bị từ chối,
  `failure-modes.md` #7), `iteration_path text NOT NULL` (giá trị của khóa chống lặp, chuỗi rỗng ngoài thân vòng lặp
  và thân map; không DEFAULT), cùng ba cột của V4.36 có ngay từ migration tạo bảng: `attempt smallint NOT NULL` CHECK
  `attempt >= 1` (lần thử của lần chạy Bước do wrapper cấp, 1 ở Bước chạy không thuộc lần chạy Bước nào; không
  DEFAULT, như hai cột trên), `port text` NULL CHECK `port <> ''` (Nhánh ra mà Bước đã đi: khóa nhánh của `switch`, làn
  quyết định của phê duyệt, làn lỗi; NULL khi Bước không chọn Nhánh ra) và `child_run_id uuid` NULL với FK ghép
  `(tenant_id, child_run_id)` tới `platform.worker_runs (tenant_id, id)` (`uq_worker_runs_tenant_id_id` của
  workflow-engine/02) ON DELETE RESTRICT và index `ix_run_steps_child_run (tenant_id, child_run_id) WHERE child_run_id
IS NOT NULL` (R3.10; RESTRICT không chặn lane xóa lượt chạy, vì dòng Bước chạy sống tối đa 61 ngày còn lượt chạy 395
  ngày, và offboarding xóa `platform.run_steps` trước `platform.worker_runs` theo thứ tự suy từ cạnh RESTRICT, H-2);
  không cột `branch_key`, vì nhánh của làn song song đã ở `lane_path` và nhánh của `switch` cùng quyết định của phê
  duyệt ở `port` (H-11); `status text NOT NULL` CHECK (`waiting`, `succeeded`, `failed`, `cancelled`) và `reason_code
text` NULL với CHECK `(status = 'waiting') = (reason_code IS NOT NULL)` (dòng `waiting` của R3.8 mang lý do chờ, dòng
  khác không mang); `started_at timestamptz` (dòng kết thúc của một Bước đã chờ mang cùng `started_at` với dòng
  `waiting` của nó, nên hai dòng ở cùng partition), `finished_at timestamptz` (NULL ở dòng `waiting`), `duration_ms`,
  `error_type`; `input_preview` và `result_preview` (≤ 4 KB), `input_ref` và
  `result_ref` (đường dẫn đối tượng, NULL khi giữ trong dòng); token, `cost_usd numeric(18,8)`,
  `price_book_version`, `redaction_log jsonb NOT NULL DEFAULT '[]'`, `fls_version`; không cột nội dung thô;
  `dw_app` không UPDATE, DELETE trên cha và không giữ quyền nào trên phân vùng nào, kể cả DEFAULT, nên đọc
  ghi qua bảng cha (DO-02.2), và một Bước đã chờ có hai dòng, `waiting` lúc đỗ rồi dòng kết thúc, nối với nhau bằng
  (`run_id`, `kind`, `node_id`, `iteration_path`, `attempt`), còn Bước chạy `model_call` và `tool_call` không bao giờ có
  dòng `waiting`; đăng ký bằng một dòng `platform.time_partitioned_tables`
  (`append_only = true`, studio-skeleton:R3.1), ENABLE/FORCE RLS và policy công ty trên cha và DEFAULT; giữ 30 ngày
  (YC88) dưới mảnh `platform.run_steps` mà ticket 03 thêm cùng thay đổi đăng ký: lane lưu giữ xóa payload của bước quá
  30 ngày qua một hàm SECURITY DEFINER hẹp không đối số đọc hạn dưới khóa đó ở `platform.retention_terms`, vì `dw_app`
  không UPDATE (R5.4, R5.12), DROP PARTITION khi cả tháng quá 30 ngày (thực tế 30-61 ngày); vì `dw_app` không DELETE,
  bảng có một dòng `STUDIO_EXCLUSIONS` nêu cách xóa khi offboarding, `platform.purge_tenant_append_only` (R5.8;
  studio-skeleton:R4.3); index `ix_run_steps_run (tenant_id, run_id, seq)`.
- `platform.outbox_events`: thêm `trace_parent text` CHECK định dạng W3C `traceparent`; dispatcher worker
  tiếp trace từ cột đó.
- `platform.worker_runs`, `platform.audit_events`: CHECK `trace_id ~ '^[0-9a-f]{32}$'` dạng `NOT VALID`.
- Mảnh retention (lát này là chủ định dạng, ADR-0100 (Accepted) quyết 7, ADR-0122 (Accepted) quyết 7; H-1): một tệp
  `configs/policies/retention.d/<schema>.<table>.yaml` cho mỗi kho, tên tệp là khóa của kho (R5.6), kho không phải bảng
  dùng tên có tiền tố có trong danh sách kho có tên của mô hình chính sách (`objects.run_step_payloads`,
  `platform.worker_runs.payload`); mỗi mảnh mang `days` (số nguyên dương; `indefinite` khi kho không hết hạn theo thời gian, chỉ đi với `purger: none`
  và `description` nêu lượt xóa thật của kho; hay `null` khi chưa ai quyết), `purger`
  (`drop_partition` qua `platform.drop_expired_partitions`, `row_delete`, `object_delete`, `column_clear`, mỗi giá
  trị một bộ xóa đã đăng ký, hay `none` chỉ khi `days: indefinite`), `enforced` và `description`, không khóa nào khác; mọi số UNVERIFIED tới khi luật sư xác
  nhận trước chạy bóng. Release manifest ghim mã băm sha256 của cả tập (R5.14), bộ nạp của R5.9 nạp tập vào
  `platform.retention_terms` lúc triển khai, và mô hình chính sách `dw_platform.retention_policy` đọc thời hạn của mỗi
  kho chỉ từ mảnh của nó (R5.13). Ticket nào tạo hay đăng ký một kho thêm mảnh của kho đó trong cùng thay đổi; không
  ticket nào chờ ticket khác vì mảnh, chỉ ticket cần bộ đọc tập mảnh, bộ nạp hay `platform.retention_term_days` chờ
  ticket 01. Ticket 01 thêm mảnh `platform.audit_events` (1095 ngày, `drop_partition`, `enforced: true`, chuyển từ
  `audit.tables.audit_events` của `retention@1.7.0`) và thay `retention@1.7.0` bằng `retention@1.8.0` bỏ mục đó, cổng
  `audit.enforced` của nó và chú thích "model_usage_ledger đã bị bỏ"; các lớp không theo kho (`classes`, `knowledge`,
  `checkpoints`, `channel_deliveries`, `audit.months_ahead`, `batch_limit`) giữ ở tệp có phiên bản đó, và không ticket
  nào khác sửa tệp đó. Ticket 03 thêm mảnh: `platform.run_steps` 30 ngày (lane xóa payload ở ngày 30, DROP PARTITION khi
  cả tháng quá hạn), `objects.run_step_payloads` 30 ngày (lane xóa đối tượng), `platform.worker_runs.payload` 90 ngày
  sau kết thúc (lane xóa trắng cột payload của lượt chạy), `platform.worker_runs` 395 ngày sau kết thúc bỏ qua dòng
  `memory.items` trỏ tới (lane xóa), `platform.tool_executions` 30 ngày (xóa trắng `output` qua hàm của R5.7),
  `platform.usage_daily` 760 ngày (lane xóa). Mảnh của bảng mà spec khác tạo do ticket tạo bảng thêm
  (usage-and-limits/02, usage-and-limits/03, agent-lifecycle/06, workflow-triggers/02 với `studio.inbound_events`,
  `studio.trigger_deliveries` và `studio.inbound_dedupe`, compliance-pdpl/04, agent-builder/04, compliance-pdpl/06, custom-objects/03 với `studio.record_write_keys` 31
  ngày);
  lát này không khai lại số đó.
- `platform.retention_terms` (V4.21; ADR-0122 (Accepted) quyết 7): bản ở runtime của các thời hạn trong tập mảnh
  retention đang ghim; bảng của lớp nền tảng, không `tenant_id` nên không RLS, như
  `platform.time_partitioned_tables` (studio-skeleton:R3.1); `store_key text PRIMARY KEY` (khóa của R5.6),
  `term_days integer NOT NULL` CHECK `term_days > 0`; một dòng cho mỗi mảnh có thời hạn theo ngày và
  `enforced: true`, nên kho chưa `enforced` hay kho không có hạn theo thời gian (`platform.contact_suppressions`)
  không có dòng. Bộ nạp của ticket 01 ghi bảng lúc triển khai dưới vai `dw_provisioner` (SELECT, INSERT, UPDATE,
  DELETE), trong một giao dịch thêm, sửa và xóa dòng tới khi bảng đúng bằng tập mảnh đang ghim (R5.9); `dw_app` chỉ
  SELECT, thu lại INSERT, UPDATE và DELETE mà quyền mặc định của schema `platform` cấp (R5.11); không vai nào khác có
  quyền. `platform.retention_term_days(p_store_key text)` trả `term_days` của khóa và báo lỗi `P0002` khi không
  có dòng (R5.12), REVOKE ALL FROM PUBLIC; mọi hàm xóa hẹp không đối số, của lát này (R5.4, R5.7) và của
  compliance-pdpl/06, gọi nó và đặt mốc bằng `now()` trừ hạn đó. Test lệch bảng so bảng với tập mảnh đang ghim
  (R5.10), nên bản ở runtime không lệch mảnh lặng lẽ (`failure-modes.md` #2).

## API

- `GET /api/v1/runs?artifact_kind&artifact_id&status&trigger_kind&from&to&cursor&limit` (`runs.read`, RLS
  và workspace theo độ sâu): danh sách lượt chạy, phân trang keyset trên `ix_worker_runs_page` của workflow-engine/02
  (H-20).
- `GET /api/v1/runs/{run_id}/steps` (`runs.read`, hay `studio.workflows.test` cho lượt `simulate` mà `requested_by` là
  người gọi, R4.4): các Bước chạy theo `seq`, mỗi Bước mang `status`, `lane_path`, `iteration_path`, `attempt`, `port`,
  `child_run_id`, `reason_code` cùng `reason_label`, `error_type` cùng `error_label`, và `effect_unresolved_label`
  (R3.7-R3.9, R4.2, R4.6, R4.10), để màn lượt chạy của workflow-builder-ui chọn làn và lần lặp; một Bước đã chờ có dòng
  `waiting` rồi dòng kết thúc, cả hai trả theo `seq`, và bên đọc lấy dòng mới nhất của mỗi (`kind`, `node_id`,
  `iteration_path`, `attempt`).
- `GET /api/v1/runs/{run_id}` (route có sẵn, `runs.read`, hay `studio.workflows.test` cho lượt `simulate` mà
  `requested_by` là người gọi): chi tiết lượt, giá trị trường mà người xem không được đọc thay bằng `Đã ẩn` (R4.4);
  người gọi không giữ `runs.read` tới workspace của lượt và không qua nhánh đó → 404 như id không tồn tại, thay 403 của
  hôm nay (R4.5).
- `GET /api/v1/runs/{run_id}/steps/{step_id}/payload?part=in|out` (`runs.read_payloads`): payload che theo
  quyền đọc trường của người xem; audit `run.payload.viewed` trong cùng giao dịch.
- `GET /api/v1/runs/{run_id}/incidents` (`runs.read`, RLS và workspace theo độ sâu, ticket 04): các sự cố `open` của
  lượt (dòng `platform.run_waits` `kind` `incident` của workflow-engine), mỗi sự cố mang `wait_id` và `created_at`
  của dòng chờ, cùng `node_id`, `error_type` và `error_label` (R4.6) của Bước chạy cuối của Bước lỗi: Bước chạy `kind` `node` có `seq` lớn
  nhất của lượt mang `error_type`, vì lượt đỗ ngay sau lần thử đó và không Bước nào có `on_error` `incident` nằm trong
  làn song song (workflow-engine:R2.16), nên một lượt có nhiều nhất một sự cố `open`; lượt của công ty khác hay ngoài
  tầm → 404 (R6.1, R6.2).
- `GET /api/v1/runs/{run_id}/outcome-reviews` (`runs.read`, RLS và workspace theo độ sâu, ticket 04): các dòng chờ
  `outcome_review` `open` của lượt, mỗi dòng mang `wait_id` và `created_at` của dòng chờ cùng `node_id` của Bước đang chờ,
  đọc từ Bước chạy `waiting` có `reason_code` `outcome_unknown` và `seq` lớn nhất, vì dòng chờ mang `node_id` của node
  xác nhận (workflow-engine:R6.30); lượt của công ty khác hay ngoài tầm → 404 (R7.1, R7.2).
- `GET /api/v1/audit/events` (route có sẵn, kiểm quyền và phân trang giữ nguyên): mỗi sự kiện thêm `action_label`,
  nhãn của catalog hành động gộp từ tập mảnh đang ghim cho `action` đó, NULL khi catalog không có khóa (R1.7).
- Lỗi theo vỏ `application/problem+json` của ADR-0108 (Accepted), mang `trace_id`; `details.reason_code`
  cho 404 cách ly.

## Màn hình

- Màn `/runs` (antd Table: thời điểm, agent hoặc quy trình, trạng thái, nguồn kích hoạt, thời lượng, chi
  phí; bộ lọc theo `artifact`, trạng thái, nguồn kích hoạt, khoảng thời gian), đọc `GET /api/v1/runs`.
- Màn `/runs/[id]` (antd: `Tree` cho các Bước chạy theo `lane_path`, lần lặp và lần thử, Descriptions, xem JSON có dấu
  `Đã ẩn`, token và chi phí mỗi Bước chạy, nút "Sao chép trace id"; V4.36): nút cây hiện trạng thái của dòng mới nhất
  của Bước, tên Nhánh ra đã đi khi có `port`, liên kết tới lượt con khi có `child_run_id`; Bước đang chờ của một lượt
  chưa kết thúc mang tag "Đang chờ ở đây" và `reason_label` (R4.8), và Bước còn `waiting` với `outcome_unknown` khi lượt
  đã kết thúc mang `effect_unresolved_label` (R4.9, R4.10); nhãn của mọi mã lý do và mã lỗi lấy từ `reason_label`,
  `error_label` và `effect_unresolved_label` của API, màn không giữ bảng nhãn nào (R4.6). Người giữ
  `studio.workflows.test` mở màn này cho lượt mô phỏng của chính mình bằng id lượt mà route `test-runs` trả (R4.4;
  H-17).
- Khối sự cố của `/runs/[id]` (ticket 04): antd Alert nêu Bước lỗi và lỗi của lần thử cuối, câu "Chạy tiếp dùng lại Bộ
  giá trị gắn mà lượt đã ghim, với phiên bản mới nhất chưa thu hồi của mỗi bí mật; sửa Bộ giá trị gắn sau khi lượt bắt
  đầu không có tác dụng với lượt này" (V4.35), `error_label` "Không rõ nhà cung cấp đã nhận hay chưa" khi lần thử cuối
  mang `outcome_unknown`, và hai antd Button "Chạy tiếp từ Bước lỗi", "Kết thúc"; hai nút chỉ hiện cho người
  mà `/me` báo giữ `studio.workflows.resolve_incident` ở workspace của lượt, còn route vẫn là chỗ kiểm
  (workflow-engine:R6.23; CLAUDE.md mục Tenancy and authorization); thông báo qua `App.useApp()` (R6.3 tới R6.6).
- Khối giải `outcome_review` của `/runs/[id]` (ticket 04; R7): antd Alert ở Bước đang chờ nêu `reason_label` "Không rõ
  nhà cung cấp đã nhận hay chưa", ba antd Button "Đã nhận" (mở antd Modal với ô bằng chứng bắt buộc), "Chưa nhận, gửi
  lại cùng khóa" và "Bỏ"; ba nút chỉ hiện cho người mà `/me` báo giữ `runs.reconcile` ở workspace của lượt, còn route
  vẫn là chỗ kiểm, kể cả luật người giải khác người xin lượt với tác động `critical` (workflow-engine:R6.35; CLAUDE.md
  mục Tenancy and authorization); thông báo qua `App.useApp()` (R7.3 tới R7.5).
- Màn `/audit` (có sẵn): cột Thao tác hiện `action_label` của `GET /api/v1/audit/events` trong một antd Tag chung cho
  mọi action, `Hoạt động hệ thống` khi trường đó NULL, dòng vẫn hiện; màn bỏ bảng nhãn và màu theo từng action của nó
  (R1.8).

## Kiểm soát

| #    | Kiểm soát                                                                     | Yêu cầu            | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ---- | ----------------------------------------------------------------------------- | ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TA1  | Span, log, audit không mang nội dung                                          | R1.2               | Input có số điện thoại → không span, log hay sự kiện Nhật ký kiểm toán nào chứa giá trị đó; bật Ghi nội dung cho công ty A không làm span công ty B mang nội dung                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| TA2  | Tên phát khớp ảnh đã ghim                                                     | R1.1               | Đổi một tên span trong `semconv` → test hợp đồng đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| TA3  | Mỗi metric khai có nơi phát                                                   | R1.3               | Thêm một hằng vào `ALL_METRICS` không có lời gọi phát → test AST đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| TA4  | Lịch sử chạy cách ly công ty và bản ghi                                       | R3.6               | `GET` Bước chạy của lượt chạy công ty B từ A → 404; danh sách `GET /api/v1/runs` không có lượt chạy công ty khác                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| TA5  | Che theo quyền đọc trường khi đọc payload                                     | R3.3               | Người không có quyền đọc `phone` → payload trả dấu `Đã ẩn`; gỡ che → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| TA6  | Bí mật không vào Lịch sử chạy                                                 | R3.2               | Input mang một khóa bí mật → preview không có giá trị, `redaction_log` ghi lý do; gỡ bỏ bí mật → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| TA7  | Trace id 32 hex xuyên tiến trình                                              | R2.2, R2.3         | Request mang `traceparent` → cùng trace id ở span API, span worker, `platform.worker_runs` và dòng outbox; ghi `trace_id` dạng `api-...` → CHECK từ chối                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| TA8  | Log chỉ id                                                                    | R1.5               | Một dòng log mang giá trị dạng email hay query string → `test_logs_carry_ids_only` đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| TA9  | Langfuse không nhận user id hay nội dung                                      | R1.4               | Span processor bỏ `user.id` và `gen_ai.input.messages`; gỡ bỏ → test exporter đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| TA10 | Mở payload có ghi Nhật ký kiểm toán                                           | R3.5               | Mở payload → đúng một sự kiện `run.payload.viewed`; gỡ ghi audit → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| TA11 | Lưu giữ không xóa lượt chạy sống hay còn tham chiếu                           | R5.3, R5.5         | Lượt chạy `waiting_approval` 400 ngày còn nguyên; lượt chạy được `memory.items` trỏ tới → bỏ qua, được đếm; sự kiện vào 31 ngày mà một lượt `queued` còn trỏ tới → bỏ qua, được đếm; sự kiện vào 45 ngày đang bị giữ khi Đóng băng → bỏ qua, metric bỏ qua tăng; gỡ điều kiện → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                           |
| TA12 | Payload cần `runs.read_payloads`                                              | R4.3               | Thiếu `runs.read_payloads` gọi payload → 403, không trả payload; gỡ kiểm → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| TA13 | Mỗi kho mới có bộ xóa đăng ký                                                 | R5.1, R5.2         | Một lớp retention thiếu bộ xóa → test tập bộ xóa đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| TA14 | Xóa output công cụ không trả UPDATE cho `dw_app`                              | R5.7               | Lane chạy qua dòng `tool_executions` 31 ngày → `output` NULL, cột khác giữ nguyên; dòng 29 ngày giữ `output`; `dw_app` UPDATE thẳng → `permission denied`; hàm đặt NULL thêm một cột khác → test đỏ; hạ dòng `platform.tool_executions` của `platform.retention_terms` còn 20 ngày trong bảng thử → dòng 21 ngày bị xóa trắng; hàm giữ hằng 30 ngày hay nhận mốc làm đối số → test đỏ                                                                                                                                                                                                                                                                                                                             |
| TA15 | Mỗi action audit có trong catalog                                             | R1.6               | Thêm một lời ghi audit với `action` không có khóa trong mảnh nào của `configs/copy/audit_actions.d/` → test AST đỏ, nêu tên action; một khóa của một mảnh có nhãn tiếng Việt rỗng → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| TA16 | Nhãn action có một chủ                                                        | R1.7, R1.8         | Đổi nhãn của `run.started` trong một catalog thử → `GET /api/v1/audit/events` trả nhãn mới trong `action_label` và màn `/audit` hiện nhãn đó; `action` không có khóa trong catalog → `action_label` NULL, màn hiện `Hoạt động hệ thống`, dòng vẫn hiện; giữ lại bảng `ACTIONS` của màn → nhãn mới không hiện, test màn đỏ; bỏ `action_label` khỏi bản zod của `@dw/contracts` → `client.ts` không biên dịch                                                                                                                                                                                                                                                                                                       |
| TA17 | Bảng thời hạn khớp tập mảnh đã ghim                                           | R5.9, R5.10        | Bộ nạp chạy trên tập mảnh thử A rồi tập mảnh thử B (một hạn đổi, một mảnh bỏ, một mảnh thêm, một mảnh `enforced: false`) → bảng đúng bằng B, không dòng của khóa bỏ hay khóa chưa `enforced`; bộ nạp bỏ bước xóa dòng → test đỏ; sửa tay hạn một dòng, chèn một khóa thừa hay xóa một dòng → test lệch bảng đỏ, nêu khóa; bỏ bộ nạp khỏi job `migrate`, hay `api`, `worker` không chờ job đó → kiểm compose đỏ                                                                                                                                                                                                                                                                                                    |
| TA18 | `dw_app` không ghi bảng thời hạn                                              | R5.11              | `dw_app` INSERT, UPDATE, DELETE trên `platform.retention_terms` → `permission denied`, bảng không đổi; `test_privileges.py` khẳng định `dw_app` chỉ SELECT, `dw_provisioner` SELECT, INSERT, UPDATE, DELETE; để lại quyền mặc định của schema cho `dw_app` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| TA19 | Thiếu hạn thì hàm xóa hẹp không xóa                                           | R5.12              | `platform.retention_term_days` hỏi một khóa không có dòng → lỗi `P0002` nêu khóa; xóa dòng `platform.tool_executions` khỏi bảng thử → hàm xóa trắng `output` báo lỗi, không dòng nào đổi; xóa dòng `platform.run_steps` → hàm xóa payload bước báo lỗi, không payload nào mất; `platform.retention_term_days` trả hạn mặc định hay NULL khi thiếu dòng → test đỏ                                                                                                                                                                                                                                                                                                                                                  |
| TA20 | Bước chạy mang làn và lần lặp của wrapper                                     | R3.7, R4.2         | Hai lần chạy cùng một Bước ở hai lần lặp, ghi qua `StepRecorderPort` với giá trị của wrapper → hai Bước chạy có `iteration_path` khác nhau, bằng đúng giá trị trong hai khóa chống lặp; một Bước ở làn `rejected` của một Bước phê duyệt → `lane_path` nêu Bước phê duyệt và Nhánh ra `rejected`, và `GET /api/v1/runs/{run_id}/steps` trả nguyên hai trường; INSERT thiếu `lane_path` hay `iteration_path` → NOT NULL từ chối; bên ghi thay `iteration_path` của wrapper bằng chuỗi rỗng → hai Bước chạy không còn phân biệt được, test đỏ; thêm DEFAULT `'[]'` cho `lane_path` → INSERT thiếu cột qua, test đỏ                                                                                                  |
| TA21 | Đọc sự cố cách ly công ty và theo độ sâu                                      | R6.1, R6.2         | `GET /api/v1/runs/{run_id}/incidents` cho lượt của công ty B từ A → 404, không dòng nào; người không có `runs.read` tới workspace của lượt → 404; người trong tầm → đúng các sự cố `open` của lượt, không sự cố `resolved` hay `cancelled`, không sự cố của lượt khác; dòng chờ mang `node_id` của node sự cố, khác id Bước lỗi → sự cố trả `node_id` và `error_type` của lần thử cuối của Bước lỗi; nối Bước chạy theo `node_id` của dòng chờ → `error_type` rỗng, test đỏ; chạy truy vấn bằng vai bỏ qua RLS hay bỏ lọc độ sâu → test đỏ                                                                                                                                                                        |
| TA22 | Màn không coi lần từ chối là đã giải, và báo kết quả không rõ                 | R6.5, R6.6         | Route giả trả 409 `stale_interrupt` → thông báo theo mã, sự cố còn hiện `open`; trả 403 hay 409 `tenant_frozen` → như trên; lần thử cuối mang `outcome_unknown` → `error_label` "Không rõ nhà cung cấp đã nhận hay chưa" mà API trả hiện cạnh nút, mang lỗi khác → không hiện; coi mọi phản hồi là thành công, gỡ nhánh `outcome_unknown`, hay màn tự giữ chữ của nhãn thay vì đọc `error_label` → test màn đỏ                                                                                                                                                                                                                                                                                                    |
| TA23 | Bước chạy mang lần thử, Nhánh ra và lượt con, không trỏ sang công ty khác     | R3.9, R3.10        | Hai lần thử của cùng một Bước ở cùng `iteration_path` → hai Bước chạy `attempt` 1 và 2; Bước `switch` đi nhánh `hot` → `port` `hot`; Bước phê duyệt bị từ chối → `port` `rejected`; Bước mở lượt con → `child_run_id` của lượt đó; INSERT `attempt` 0 hay thiếu `attempt` → CHECK hay NOT NULL từ chối; `port` rỗng → CHECK từ chối; `dw_app` gắn công ty A chèn Bước chạy mang `child_run_id` của một lượt công ty B → lỗi FK 23503, không dòng nào; đổi FK ghép thành FK một cột `child_run_id` → ca đó qua, test đỏ; bên ghi tự tính `attempt` thay giá trị của wrapper → test đỏ                                                                                                                              |
| TA24 | Bước đang chờ có dòng từ lúc đỗ, và màn nói đang chờ ở đâu                    | R3.8, R4.8, R4.9   | Bước phê duyệt đỗ → có ngay một Bước chạy `waiting` mang `reason_code` của điểm chờ, cùng giao dịch với dòng `platform.run_waits`, trước mọi quyết định; quyết định tới → thêm dòng kết thúc cùng `started_at`, dòng `waiting` còn nguyên; INSERT dòng `waiting` thiếu `reason_code`, hay dòng `succeeded` mang `reason_code` → CHECK từ chối; lượt chờ ở `outcome_review` → Bước đó trên cây mang "Đang chờ ở đây" và "Không rõ nhà cung cấp đã nhận hay chưa"; lượt đó kết thúc vì `deadline_at`, hay bị hủy khi Tắt khẩn → Bước mang "Không rõ nhà cung cấp đã nhận hay chưa, chưa ai xác nhận" và không mang "Đang chờ ở đây"; gỡ lời ghi lúc đỗ → lượt chờ duyệt không có Bước nào "Đang chờ ở đây", test đỏ |
| TA25 | Mỗi mã lý do có nhãn, và nhãn có một chủ                                      | R1.9, R4.6, R4.10  | Thêm một lời ghi `reason_code` hay `error.code` lên lượt chạy với mã không có khóa trong mảnh nào của `configs/copy/run_reason_codes.d/` → test AST đỏ, nêu mã; một khóa có nhãn rỗng → test đỏ; đổi nhãn của `outcome_unknown` trong một catalog thử → `GET .../steps` và `GET .../incidents` trả nhãn mới trong `reason_label`, `error_label`, và màn hiện nhãn đó; đổi nhãn của `effect_unresolved` → `effect_unresolved_label` của Bước còn `waiting` với `outcome_unknown` ở lượt đã kết thúc mang nhãn mới, cùng dòng ở lượt chưa kết thúc mang NULL; mã không có khóa → nhãn NULL, Bước vẫn hiện mã; màn giữ một bảng nhãn riêng → nhãn mới không hiện, test màn đỏ                                        |
| TA26 | Người dựng chỉ đọc lượt mô phỏng của chính mình                               | R4.4, R4.5         | Người chỉ giữ `studio.workflows.test` gọi `GET .../steps` và `GET /api/v1/runs/{run_id}` cho lượt `simulate` mình xin → 200, giá trị `phone` mà người đó không được đọc là `Đã ẩn`; lượt `simulate` của người khác → 404 giống hệt id ngẫu nhiên; lượt `live` → 404; lượt `simulate` mình xin ở công ty A, gọi bằng ngữ cảnh công ty B → 404; `GET /api/v1/runs` của người đó không trả lượt mô phỏng nào (H-17); payload thiếu `runs.read_payloads` → 403 (R4.3); bỏ điều kiện `requested_by`, bỏ điều kiện `run_mode`, hay chạy truy vấn bằng vai bỏ qua RLS → test đỏ                                                                                                                                          |
| TA27 | Mỗi thời hạn có một mảnh là chủ, tập mảnh ghim trong manifest                 | R5.6, R5.13, R5.14 | Mảnh tên `platform.no_such_table.yaml` hay `audit_events.yaml` thiếu schema → test tập mảnh đỏ, nêu mảnh; gỡ mảnh `platform.audit_events` → mô hình chính sách không trả hạn nào cho bảng đó và test catalog của studio-skeleton:R3.7 đỏ, nêu bảng; giữ lại ánh xạ tạm sang `retention@1.7.0` → ca gỡ mảnh vẫn xanh, test đỏ; sửa một mảnh mà không dựng lại manifest → kiểm manifest đỏ                                                                                                                                                                                                                                                                                                                          |
| TA28 | Đọc `outcome_review` cách ly công ty và theo độ sâu                           | R7.1, R7.2         | `GET /api/v1/runs/{run_id}/outcome-reviews` cho lượt của công ty B từ A → 404, không dòng nào; người không có `runs.read` tới workspace của lượt → 404; người trong tầm → đúng các dòng `outcome_review` `open` của lượt, không dòng `resolved`, `cancelled`, không dòng `incident` hay `approval`; dòng chờ mang `node_id` của node xác nhận → dòng trả `node_id` của Bước đang chờ; nối Bước chạy theo `node_id` của dòng chờ → `node_id` rỗng, test đỏ; chạy truy vấn bằng vai bỏ qua RLS hay bỏ lọc độ sâu → test đỏ                                                                                                                                                                                          |
| TA29 | Màn không gửi "Đã nhận" thiếu bằng chứng, và không coi lần từ chối là đã giải | R7.4, R7.5         | Chọn "Đã nhận" với ô bằng chứng rỗng → client giả không nhận yêu cầu nào; route giả trả 409 `second_person_required`, 409 `stale_interrupt`, 409 `tenant_frozen` hay 403 → thông báo theo mã, dòng chờ còn hiện `open`; coi mọi phản hồi là thành công, hay gửi `received` không bằng chứng → test màn đỏ                                                                                                                                                                                                                                                                                                                                                                                                         |
| TA30 | Mỗi nhãn có một mảnh là chủ, tập mảnh ghim trong manifest                     | R1.10, R1.11       | Hai mảnh thử của `configs/copy/audit_actions.d/` cùng khai `run.started`, với hai nhãn khác nhau hay giống nhau → bộ nạp từ chối, nêu khóa và hai mảnh; cùng ca ở `configs/copy/run_reason_codes.d/` → như trên; gỡ kiểm trùng → bộ nạp nhận, test đỏ; sửa một mảnh mà không dựng lại manifest → `make release-manifest-check` đỏ; một mảnh không mang `copy_id` → `make release-manifest` vẫn chạy và manifest có một mục cho mỗi tập; đổi thứ tự đọc tệp → mã băm không đổi                                                                                                                                                                                                                                     |

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (ghi ở Comments của ticket).
- `make ci && make test-integration` xanh; `reviewing-feature-security` và `reviewing-deployment-security`
  đã chạy trên từng ticket có route, migration hay lane; `.claude/plans/studio.md` ghi lát W1 đã xong.

## Phụ thuộc

- usage-and-limits: Sổ sử dụng theo lượt gọi, định giá theo ADR-0121 (Accepted)
  (`.claude/plans/studio/usage-and-limits/issues/02-bang-gia-so-su-dung-va-man-hinh.md`), và `LimitsMiddleware`
  nơi mở span `chat` và ghi Bước chạy `model_call`
  (`.claude/plans/studio/usage-and-limits/issues/03-han-muc-giu-truoc-va-quyet-toan.md`).
- app-standards: trường `trace_id` của vỏ lỗi (app-standards:R1.2) và index audit theo lượt chạy
  (`.claude/plans/studio/app-standards/issues/03-quy-uoc-api-danh-sach-va-sua.md`).
- workflow-triggers: bảng `studio.inbound_events`, `studio.trigger_deliveries`, `studio.inbound_dedupe`, mảnh retention
  của chúng và bộ xóa mà chúng đăng ký vào sổ bộ xóa của ticket 01 (H-35) để lane lưu giữ của lát này chạy, cùng tín hiệu sự kiện đang
  bị giữ khi Đóng băng cho R5.5, đều do
  `.claude/plans/studio/workflow-triggers/issues/02-data-hub-endpoint-va-ingress.md` thêm (workflow-triggers:R6.3,
  workflow-triggers:R6.4, workflow-triggers:R6.7); test của R5.5 trên các bảng đó chạy ở ticket đó, gọi thẳng bộ xóa, không qua lane
  (workflow-triggers:R1.7, workflow-triggers:R6.8).
- workflow-engine, cho màn sự cố (R6): dòng `platform.run_waits` `kind` `incident`, route giải
  `POST /api/v1/runs/{run_id}/incidents/{wait_id}/resume` và `.../end` với khóa `studio.workflows.resolve_incident`, và
  loại lỗi `outcome_unknown` mà bộ bọc ghi qua `StepRecorderPort` (workflow-engine:R6.18 tới workflow-engine:R6.28), ở
  `.claude/plans/studio/workflow-engine/issues/07-chay-tiep-tu-buoc-loi.md`, mà ticket 04 chờ; ticket 03 không chờ
  ticket nào của bậc B (V4.26).
- workflow-engine, cho màn giải `outcome_review` (R7): dòng `platform.run_waits` `kind` `outcome_review`, route
  `POST /api/v1/runs/{run_id}/outcome-reviews/{wait_id}/resolve` dưới `runs.reconcile` với ba `decision`, luật người giải
  khác người xin lượt với tác động `critical` và mã trả của route (workflow-engine:R6.30 tới workflow-engine:R6.36), ở
  `.claude/plans/studio/workflow-engine/issues/08-tac-dong-khong-ro-ket-qua.md`, mà ticket 04 chờ.
- workflow-engine: bộ bọc node phát span và gọi `StepRecorderPort`, `root_run_id` và cửa nhận lượt chạy
  (`.claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md`), cùng `lane_path` và `iteration_path`
  của mỗi lần chạy Bước mà bộ bọc cấp từ `WorkflowIR` của lượt, `iteration_path` là giá trị nó dẫn vào khóa chống lặp
  (workflow-engine:R4.5; R3.7); trigger trên
  `platform.worker_runs` của workflow-engine:R6.13
  (`.claude/plans/studio/workflow-engine/issues/05-cho-nguoi-va-ghim-phien-ban.md`), mà ticket 02 chờ vì CHECK
  `trace_id` cũng đặt trên bảng đó.
- workflow-engine, cho V4.36: bộ bọc cấp `attempt`, `port` và `child_run_id` cho mỗi Bước chạy (R3.9), báo qua
  `StepRecorderPort` lúc một Bước đỗ ở một điểm chờ, trong giao dịch ghi dòng `platform.run_waits`, với `reason_code`
  của điểm chờ (R3.8), kể cả điểm chờ `outcome_review` với `outcome_unknown` của
  `.claude/plans/studio/workflow-engine/issues/08-tac-dong-khong-ro-ket-qua.md` và điểm chờ `child_run` của
  `.claude/plans/studio/workflow-engine/issues/09-quy-trinh-con.md`; mọi `reason_code` và `error.code` mà động cơ, các
  lane và cửa nhận lượt ghi có nhãn trong catalog của R1.9 (H-12), mỗi nhãn ở mảnh `workflow-engine.yaml` mà ticket ghi
  mã đó thêm trong cùng thay đổi, trừ mã đã có nhãn ở một mảnh khác (R1.10), và nhãn của audit `run.effect_unresolved` ở
  mảnh cùng tên của catalog hành động (H-21). Ticket 03 thử các cột bằng giá trị mà bên gọi đưa, nên không chờ ticket 08
  hay 09.
- tenant-config: cột `run_mode` của `platform.worker_runs` (tenant-config:R4.1), mà R4.4 đọc để biết một lượt là
  `simulate`; ticket 03 đã chờ ticket đặt cột qua workflow-engine/03.
- workflow-engine: khóa `studio.workflows.test`, mà
  `.claude/plans/studio/workflow-engine/issues/01-tai-lieu-workflow-va-kiem-xuat-ban.md` đăng ký vào danh mục quyền
  cùng các khóa khác của loại `workflow` (workflow-engine:R1.5; H-19); ticket 03 kiểm khóa đó cho R4.4 và đã chờ ticket
  đó qua workflow-engine/03, nên không thêm cạnh.
- workflow-engine/02: `ix_worker_runs_page (tenant_id, workspace_id, created_at DESC, id DESC)`, mà danh sách của R4.1
  phân trang trên đó (`.claude/plans/studio/workflow-engine/issues/02-cot-run-va-cua-nhan-run.md`; H-20); ticket 03 đã
  chờ ticket đó qua workflow-engine/03, và lát này không đặt chỉ mục hay ràng buộc nào trên bảng lượt chạy ngoài CHECK
  `trace_id` của ticket 02.
- workflow-triggers: route `.../test-runs` trả id lượt mô phỏng
  (`.claude/plans/studio/workflow-triggers/issues/01-so-kich-hoat-chay-tay-va-danh-tinh.md`), mà người dựng dùng để mở
  lượt của mình (R4.4; H-17); ticket 03 không chờ ticket đó, vì test của R4.4 dựng lượt `simulate` mà không qua route
  đó.
- field-security: hàm quyết quyền đọc trường và dấu `Đã ẩn`, đang viết đợt này — dẫn theo đường dẫn
  (`.claude/plans/studio/field-security/issues/01-mo-hinh-bao-mat-truong.md`); ADR-0106 (Accepted).
- tenant-rbac: quyền `runs.read` trong danh mục quyền một chủ; `runs.read_payloads` đăng ký ở ticket 03 theo quy
  ước của `.claude/plans/studio/tenant-rbac/issues/01-mot-chu-cho-quyen.md`, với cột `tenant_grantable` của
  `.claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md` trong cùng INSERT, nên ticket 03 chờ
  tenant-rbac/02.
- studio-skeleton: schema, điều hướng và sổ `platform.time_partitioned_tables` (studio-skeleton:R3.1)
  (`.claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md`); R3.7 đọc tập mảnh qua mô
  hình chính sách của R5.13 (studio-skeleton:R3.7); test phủ offboarding và `STUDIO_EXCLUSIONS`
  (studio-skeleton:R4.3). Ticket 01 chờ studio-skeleton/01, vì nó gỡ ánh xạ tạm sang `retention@1.7.0` mà ticket đó
  dựng và test phủ của nó đọc sổ của ticket đó (H-1).
- usage-and-limits/02: `platform.drop_expired_partitions(cutoffs jsonb)` cho mọi kho DROP PARTITION, với mốc đọc từ tập
  mảnh (H-1), và `platform.purge_tenant_append_only` cho R5.8 (usage-and-limits:R3.10); ticket 03 chờ nó, còn nó chờ
  ticket 01, vì mốc của hàm đọc qua bộ đọc tập mảnh (R5.13) và test của studio-skeleton:R3.7 cho
  `platform.usage_events` mà nó đăng ký chỉ xanh khi bộ đọc đó đã có (H-27).
- runtime-hardening: `dw_app` không có UPDATE trên `platform.tool_executions` (runtime-hardening:R6.3),
  nên R5.7 đi qua hàm riêng của lane.
- Mảnh retention (H-1): không có chuỗi ticket sửa tệp; ticket nào tạo hay đăng ký một kho thêm mảnh của kho đó trong
  cùng thay đổi, và ticket cần bộ đọc tập mảnh, bộ nạp hay `platform.retention_term_days` chờ ticket 01 ở dòng Blocked
  by của chính nó (compliance-pdpl/04, compliance-pdpl/06, agent-builder/04, workflow-triggers/02, agent-lifecycle/06;
  mục B của lượt h; usage-and-limits/02, H-27), không chờ ticket 03.
- Mảnh nhãn (H-21): không có chuỗi ticket sửa tệp; ticket nào của spec khác ghi một `action` audit mới, hay một
  `reason_code` hay `error.code` mới lên lượt chạy hay Bước chạy, thêm nhãn của nó vào mảnh của spec mình,
  `configs/copy/audit_actions.d/<spec>.yaml` hay `configs/copy/run_reason_codes.d/<spec>.yaml`, trong cùng thay đổi, kể
  cả khi ticket đó đi trước ticket 03 (runtime-hardening/03 với `platform.outbox.replayed`), và không ticket nào chờ
  ticket 03 vì mảnh; một mã đã có nhãn ở một mảnh không được khai lại ở mảnh khác (R1.10).
- Bộ nạp của R5.9: vai `dw_provisioner` (`scripts/create_provisioner_role.py`), cấp quyền theo từng bảng, và job một
  lần `migrate` của compose mà `api` và `worker` chờ với `service_completed_successfully`; bộ nạp chạy trong job đó
  ngay sau `alembic upgrade head` và đọc tập mảnh đang ghim qua mô hình `dw_platform.retention_policy` (V4.21; H-1).
- Kiểm lại khi: hợp đồng `StepRecorderPort` hay bộ bọc node của workflow-engine đổi, hay workflow-engine đổi cách
  gọi tên làn hay `iteration_path` → R3, R3.7, R4.2, ticket 03; workflow-engine đổi route giải sự cố, mã trả của nó,
  dòng chờ `incident`, loại lỗi `outcome_unknown`, hay cho một Bước có `on_error` `incident` vào làn song song
  (workflow-engine:R2.16) → R6, ticket 04; hàm quyền đọc trường của field-security đổi → R3.3; ADR-0122 (Accepted) bị Đạt bác → toàn lát; workflow-triggers đổi bảng
  sự kiện vào hay cách giữ sự kiện khi Đóng băng → R5.1, R5.5; luật sư đổi số thời hạn → một lần sửa mảnh của kho
  đó mà bộ nạp nạp lúc triển khai, không đổi tiêu chí, không migration (V4.21; H-1); usage-and-limits
  đổi hai hàm của sổ → R5.8, ticket 03; một ticket mới thêm mảnh, hay cần bộ đọc tập mảnh, bộ nạp hay hàm đọc hạn →
  mục Phụ thuộc, ticket 01; workflow-engine bỏ hay dời trigger trên `platform.worker_runs` → ticket 02; một
  ticket khác sửa `GET /api/v1/audit/events` hay màn `/audit` → R1.7, R1.8, ticket 03; một spec thêm một hàm xóa
  hẹp không đối số → R5.12, và hàm đó đọc hạn qua `platform.retention_term_days`; lát này đổi hình
  `platform.retention_terms`, hàm đọc hạn, bộ nạp hay định dạng mảnh → compliance-pdpl:R5.9, compliance-pdpl:R5.10,
  ticket 01 và `.claude/plans/studio/compliance-pdpl/issues/06-lop-luu-giu-du-lieu-ca-nhan.md`; vai `dw_provisioner`
  hay job `migrate` đổi → R5.9, ticket 01; workflow-engine đổi cách báo một Bước đỗ, hay cách cấp `attempt`, `port`,
  `child_run_id` → R3.8, R3.9, ticket 03; workflow-engine đổi mã `outcome_unknown` hay cách kết thúc một lượt còn tác
  động chưa giải (H-6, H-22) → R4.8, R4.9, R4.10, R6.5, ticket 03, 04; một ticket ghi một mã lý do hay một `action`
  audit mới → mảnh của spec đó, R1.6, R1.9, R1.10 (H-21); `scripts/release_manifest.py` đổi cách đọc `configs/copy/` →
  R1.11, ticket 03; workflow-engine đổi `ix_worker_runs_page` hay thứ tự phân trang của nó → R4.1, ticket 03 (H-20);
  workflow-engine đổi khóa `studio.workflows.test` (H-19), hay workflow-triggers đổi cách route `test-runs` trả id lượt →
  R4.4, ticket 03;
  tenant-config đổi cột `run_mode` → R4.4, R4.5; workflow-engine đổi chạy tiếp từ Bước lỗi về Bộ giá trị gắn hay phiên
  bản bí mật (V4.35) → R6.4, ticket 04; workflow-engine đổi route giải `outcome_review`, `decision` của nó, mã trả, hay
  `node_id` của dòng chờ `outcome_review` → R7, ticket 04.

## Câu hỏi còn mở

Không còn câu hỏi mở.

## Quyết định

- 23/10/2026 (người yêu cầu): D6 (DO-21): đưa lại Sổ sử dụng theo lượt gọi làm nguồn; lát này đọc sổ cho
  token và chi phí mỗi Bước chạy. Sửa: R3.1.
- 23/10/2026 (agent, tạm): DO-52 theo khuyến nghị (a): thời hạn vào `retention@1.8.0` (I/O bước 90 ngày,
  payload đối tượng 30 ngày, lượt chạy kết thúc 395 ngày), luật sư xác nhận theo PDPL. Hỏi: Q1. Sửa: R5.1.
  Nếu sai thì: đổi số trong `retention@1.8.0`, không đổi cơ chế.
- 23/10/2026 (agent, tạm): DO-51 theo khuyến nghị (a): Ghi nội dung chỉ công ty đọc, giữ ≤ 7 ngày, Người
  vận hành không đọc — W2. Sửa: Ngoài phạm vi. Nếu sai thì: bỏ Ghi nội dung khỏi lộ trình.
- 23/10/2026 (agent, tạm): config-chang.md ghi đối thủ phơi "Nhật ký audit" và "Lịch sử" làm bề mặt quan
  sát (mục 7); Studio cải tiến là công ty đọc Lịch sử chạy từ `platform.run_steps` dưới RLS, span không nội
  dung, không đọc từ trace (ADR-0122 (Accepted)) — quan sát học được, không phải mã của họ. Sửa: R1, R3.
- 23/10/2026 (Đạt): DO-21.1 ký: Sổ sử dụng theo lượt gọi quay lại; dòng D6 ở trên không còn chờ chữ ký.
  Sửa: Phụ thuộc, ticket 03.
- 23/10/2026 (Đạt): DO-52 theo (a) cộng hai dòng, thay dòng DO-52 tạm ở trên: bảng tạm UNVERIFIED theo
  ADR-0122 (Accepted) quyết 7; Bước chạy và sự kiện vào 30 ngày (YC88 thắng 90 ngày của ADR); lát này là chủ
  duy nhất của `retention@1.8.0` và lane lưu giữ của nó đọc hạn `studio.inbound_events`,
  `studio.trigger_deliveries`; lane không xóa sự kiện vào mà lượt `queued` còn trỏ tới; luật sư xác nhận số
  trước chạy bóng (compliance-pdpl/02). Hỏi: Q1. Sửa: R5, R5.1, R5.4, R5.5, TA11, Dữ liệu, Trong phạm vi,
  Phụ thuộc, ticket 03.
- 23/10/2026 (Đạt): DO-51.1 theo (a) và DO-51.2 theo (c), thay dòng DO-51 tạm ở trên: Ghi nội dung ở W2 qua
  chính sách có audit, ≤ 7 ngày, chỉ công ty đọc; sử dụng theo tên người là W2. DO-46.3 theo (b): không gửi
  `traceparent` tới máy chủ MCP nào, không bao giờ `baggage`. Sửa: Ngoài phạm vi.
- 23/10/2026 (Đạt): OPS-b và ADR-0122 (Accepted) nhận kèm sửa: index audit theo lượt chạy có một chủ là
  app-standards/03, ticket 02 chờ nó; ticket 02 và 03 chờ usage-and-limits/03 vì `LimitsMiddleware` ghi span
  `chat` và Bước chạy `model_call`. DO-02.2 theo (a): partition của `run_steps` không cấp quyền nào cho
  `dw_app`, bảng đăng ký bằng một dòng sổ. Sửa: Ngoài phạm vi, Dữ liệu, Trong phạm vi, Phụ thuộc, ticket 02, 03.
- 23/10/2026 (agent, tạm): A:app-standards:R1.2~telemetry-and-audit:R2.4: lát này chỉ bảo đảm `trace_id`
  32 hex trong vỏ lỗi của app-standards, không dựng vỏ. Sửa: R2.4, ticket 02. Nếu sai thì: lát này giữ cả
  việc dựng trường `trace_id`.
- 24/10/2026 (Đạt): lát này sở hữu định dạng tệp chính sách retention (khóa `schema.table`) và các lane lưu giữ,
  không còn là chủ duy nhất của mọi dòng trong tệp; mỗi ticket đăng ký một bảng `append_only` tự thêm thời hạn
  của bảng mình vào một bản mới của tệp trong cùng thay đổi, nên studio-skeleton:R3.7 xanh ngay khi đăng ký
  (F:ADR-0100 (Accepted)\~studio-skeleton:R3.7, I:studio-skeleton:R3.7\~usage-and-limits/02). Sửa: R5, R5.1,
  thêm R5.6, Trong phạm vi, Dữ liệu, Phụ thuộc, ticket 03.
- 24/10/2026 (Đạt): lane lưu giữ bỏ qua và đếm sự kiện vào đang bị giữ khi Đóng băng; Đóng băng không có trần thời
  gian (B:agent-lifecycle:R7.2\~telemetry-and-audit:R5.5). Sửa: R5.5, TA11, Dữ liệu, ticket 03.
- 24/10/2026 (Đạt): xóa `platform.tool_executions.output` sau 30 ngày (ADR-0122 (Accepted) quyết 7) là việc của
  lane lưu giữ của lát này, qua một hàm SECURITY DEFINER hẹp chỉ đặt NULL cột đó; `dw_app` không nhận lại UPDATE
  (runtime-hardening:R6.3; H:ADR-0122 (Accepted)\~runtime-hardening:R6.3). Sửa: thêm R5.7, TA14, Trong
  phạm vi, Dữ liệu, Phụ thuộc, ticket 03.
- 24/10/2026 (Đạt): offboarding xuất rồi xóa `platform.run_steps`; vì `dw_app` không DELETE, bảng có một dòng
  `STUDIO_EXCLUSIONS` nêu cách xóa, `platform.purge_tenant_append_only` của usage-and-limits/02, theo cách sửa mà
  studio-skeleton:R4.3 nhận (H:ADR-0121 (Accepted)\~usage-and-limits:dữ-liệu). Sửa: thêm R5.8, Dữ liệu, Phụ thuộc,
  ticket 03.
- 24/10/2026 (Đạt): `runs.read_payloads` đăng ký ở ticket 03 theo quy ước của tenant-rbac/01
  (B:agent-lifecycle:phụ-thuộc\~tenant-rbac/01). Sửa: Trong phạm vi, Phụ thuộc, ticket 03.
- 24/10/2026 (agent, tạm): V4.P1: tệp chính sách retention giữ là một tệp có phiên bản
  `configs/policies/retention@<semver>.yaml`, một câu trả lời có số hiệu cho câu hỏi tuân thủ; các ticket sửa tệp đi
  thành một chuỗi theo `Blocked by`, mỗi ticket ra một bản mới, theo thứ tự ở mục Phụ thuộc, bắt đầu từ
  usage-and-limits/02; studio-skeleton/01 không thuộc chuỗi vì nó không sửa tệp, chỉ đọc `retention@1.7.0` qua ánh
  xạ tạm (C:configs:spec\~telemetry-and-audit/03; ADR-0122 (Accepted) quyết 7). Sửa: Dữ liệu, Phụ thuộc, ticket 03.
  Nếu sai thì: tách tệp thành một tệp mỗi bảng, sửa R5.6 và ADR-0122 (Accepted) quyết 7.
- 24/10/2026 (agent, tạm): ticket 02 chờ workflow-engine/05, theo chiều của lộ trình (lát này đi sau
  workflow-engine), vì cả hai đặt DDL trên `platform.worker_runs` (trigger của workflow-engine:R6.13 và CHECK
  `trace_id`); qua workflow-engine/05, ticket 02 cũng chờ workflow-engine/04
  (C:telemetry-and-audit/02\~workflow-engine/05). Sửa: Phụ thuộc, ticket 02. Nếu sai thì: workflow-engine/05 chờ
  ticket 02 và cạnh này bỏ.
- 24/10/2026 (agent, tạm): mọi ticket chèn dòng vào `platform.permissions` chờ tenant-rbac/02 và nêu trong INSERT mọi
  cột NOT NULL có lúc đó, nên ticket 03 chờ tenant-rbac/02 và dòng `runs.read_payloads` mang cả `tenant_grantable`
  (C:custom-objects/02\~tenant-rbac/02; ADR-0104 (Accepted) quyết 1). Sửa: Phụ thuộc, ticket 03. Nếu sai thì:
  tenant-rbac/01 tạo cột `tenant_grantable` kèm sửa ADR-0104 (Accepted) quyết 1, và ticket 03 chỉ chờ
  tenant-rbac/01.
- 24/10/2026 (agent, tạm): R5.8 và mục Phụ thuộc dẫn usage-and-limits:R3.10, hợp đồng của
  `platform.purge_tenant_append_only` trên mọi bảng `append_only` của sổ, thay usage-and-limits:R3.8, tiêu chí
  offboarding của chính các bảng usage-and-limits. Sửa: R5.8, Phụ thuộc. Nếu sai thì: R5.8 dẫn lại số tiêu chí mà
  usage-and-limits đặt cho hàm.
- 24/10/2026 (agent, tạm): catalog hành động audit `configs/copy/audit_actions@1.0.0.yaml` của ADR-0122 (Accepted)
  quyết 6 chưa có chủ, trong khi spec khác dẫn nó như đã có ở W1 (agent-lifecycle, mục Quyết định), nên ticket 03 tạo
  nó cùng test AST đỏ khi mã ghi một `action` mà catalog thiếu; catalog rời dòng W2 của bộ lọc, vì YC83 chỉ đòi lọc
  và xuất. Cách các ticket sau thêm tên action quyết ở lượt `checking-plan-readiness` của spec này, cùng dạng chuỗi
  của tệp chính sách retention (V4.P1), ghi ở Q2. Sửa: thêm R1.6, TA15, Trong phạm vi, Ngoài phạm vi, Q2, ticket 03.
  Nếu sai thì: catalog về W2 cùng bộ lọc của YC83, R1.6 và TA15 sang dòng W2 đó, và các spec dẫn catalog ở W1 đổi
  theo.
- 24/10/2026 (agent, tạm): catalog hành động audit là chủ duy nhất của nhãn action: `GET /api/v1/audit/events` trả mỗi
  sự kiện kèm `action_label` đọc từ catalog đang ghim (NULL khi catalog không có khóa), và màn `/audit` hiện trường đó
  và bỏ bảng `ACTIONS` riêng của nó (nhãn và màu theo từng action, `apps/web/app/audit/page.tsx:15-25`), vì hai bản
  nhãn của một action lệch nhau mà không ai thấy (`failure-modes.md` #2) và ADR-0122 (Accepted) quyết 6 giao nhãn
  tiếng Việt của mọi action cho catalog; nhãn đi qua một trường của route có sẵn thay một route riêng, nên màn chỉ gọi
  một route; bản zod viết tay của sự kiện ở `@dw/contracts` mang trường đó cùng một dòng `SameType` so với route, vì
  zod bỏ khóa nó không khai (`packages/typescript/api-client/src/client.ts:200-205`), nên thiếu bản zod thì nhãn không
  tới màn. Sửa: Hiện trạng, thêm R1.7, R1.8, TA16, Trong phạm vi, API, Màn hình, Phụ thuộc, ticket 03. Nếu sai thì:
  màn đọc catalog qua một route riêng (ví dụ `GET /api/v1/audit/actions`) và ghép nhãn theo `action`, R1.7, R1.8 và
  TA16 đổi theo route đó; catalog vẫn là chủ duy nhất của nhãn.
- 24/10/2026 (Đạt): V4.21: các thời hạn do luật sư quyết nằm trong bảng `platform.retention_terms` (khóa
  `schema.table`, hạn), do provisioner nạp từ bản tệp chính sách retention đã ghim lúc triển khai, `dw_app` chỉ đọc;
  mỗi hàm xóa hẹp (hội thoại của compliance-pdpl/06, xóa `output` công cụ) không nhận đối số và đọc hạn của mình ở
  bảng đó; một test đỏ khi bảng lệch tệp đã ghim; luật sư vẫn đổi số bằng một bản mới của tệp, không bằng code
  (ADR-0122 (Accepted) quyết 7; DO-52 (a)); lát này làm chủ bảng, bộ nạp và test. Sửa: R5, R5.7, thêm R5.9, R5.10,
  R5.11, R5.12, TA14, thêm TA17, TA18, TA19, Trong phạm vi, Dữ liệu, Phụ thuộc, ticket 03.
- 24/10/2026 (agent, tạm): V4.21 ở lát này: bảng mang một dòng cho mỗi khóa của bản tệp đang ghim có thời hạn theo
  ngày và `enforced: true`, nên hàm xóa hẹp của một khóa chưa `enforced` báo lỗi thay vì xóa trước khi cổng mở; mọi
  hàm xóa hẹp không đối số, kể cả hàm xóa payload của Bước chạy (R5.4), đọc hạn qua một hàm
  `platform.retention_term_days(text)` báo lỗi khi thiếu dòng, một chủ cho cách đọc (`failure-modes.md` #7); bộ nạp
  chạy dưới vai `dw_provisioner` trong job `migrate` của compose ngay sau `alembic upgrade head`, nên `api` và
  `worker`, vốn chờ job đó, khởi động sau khi bảng khớp tệp; bộ nạp và worker đọc cùng một hằng ghim bản tệp
  (`failure-modes.md` #2). Sửa: R5.9, R5.12, TA17, TA19, Dữ liệu, Phụ thuộc, ticket 03. Nếu sai thì: bảng mang mọi
  khóa có hạn kèm cột `enforced` mà hàm xóa hẹp tự kiểm, mỗi hàm tự đọc dòng của mình, hay bộ nạp chạy ở một job
  compose riêng theo luật dịch vụ mới của studio-skeleton (studio-skeleton:R8.2 tới studio-skeleton:R8.7).
- 24/10/2026 (Đạt): V4.26: W1 kéo dài khoảng 2-3 tuần để chứa làn song song gộp kiểu all, vòng lặp có trần cho phép chờ
  trong thân cùng Bước Thoát vòng lặp, Chạy tiếp từ Bước lỗi như một sự cố, và phê duyệt mà mọi người được giao phải
  duyệt, sau đường găng YC94; mở rộng ticket 03 để Bước chạy mang làn và `iteration_path`, và màn sự cố của Chạy tiếp từ
  Bước lỗi thuộc lát này. Sửa: R3.7, R4.2, thêm R6, TA20, TA21, TA22, Dữ liệu, API, Màn hình, Trong phạm vi, Ngoài phạm
  vi, Phụ thuộc, ticket 03, thêm ticket 04.
- 24/10/2026 (agent, tạm): cách áp V4.26 ở lát này: `lane_path` là mảng jsonb các cặp (id Bước chứa, tên Nhánh ra mà
  loại của Bước đó khai) từ chuỗi gốc tới làn chứa Bước, và `iteration_path` là đúng giá trị mà wrapper nút dẫn vào khóa
  chống lặp (ADR-0108 (Accepted) quyết 6), cả hai do wrapper cấp từ `WorkflowIR` của lượt, NOT NULL không DEFAULT, nên
  một bên ghi quên chúng bị từ chối thay vì ghi rỗng lặng lẽ (`failure-modes.md` #7) và lần lặp thứ hai của một Bước
  không trộn vào lần thứ nhất; ticket 03 thử cột bằng giá trị mà bên gọi đưa, còn vòng lặp và làn song song thật ghi qua
  wrapper ở ticket của workflow-engine, nên ticket 03 không chờ ticket nào của bậc B và không chặn đường găng YC94. Sửa:
  R3.7, Dữ liệu, ticket 03. Nếu sai thì: Bước chạy chỉ mang `node_id` và `iteration_path`, làn được dẫn từ tài liệu đã
  ghim theo `node_id` lúc đọc, và `lane_path` cùng ca của nó rời R3.7, TA20.
- 24/10/2026 (agent, tạm): màn sự cố của V4.26 nằm trên `/runs/[id]` của lát này, chủ của màn Lịch sử chạy, và đọc sự cố
  qua một route đọc riêng `GET /api/v1/runs/{run_id}/incidents` dưới `runs.read` theo độ sâu, vì route giải của
  workflow-engine nhận `wait_id` trong đường dẫn và trả 409 `stale_interrupt` cho một sự cố không còn `open`, nên màn
  cần biết đúng `wait_id` đang mở, mà danh sách Bước chạy không mang; route đọc có ca âm chéo công ty và ngoài độ sâu
  như R3.6 (CLAUDE.md mục Tenancy and authorization); màn và route vào ticket 04, chờ ticket 03 và workflow-engine/07,
  để ticket 03 trên đường găng YC94 không chờ bậc B. Sửa: thêm R6, TA21, TA22, API, Màn hình, Trong phạm vi, Ngoài phạm
  vi, Phụ thuộc, thêm ticket 04. Nếu sai thì: `GET /api/v1/runs/{run_id}` trả kèm sự cố `open` của lượt, R6.1, R6.2 và
  TA21 chuyển sang route đó, và ticket 04 chỉ còn màn.
- 24/10/2026 (agent, tạm): route đọc sự cố lấy `node_id` và `error_type` của lần thử cuối của Bước lỗi từ Bước chạy
  `kind` `node` có `seq` lớn nhất của lượt mang `error_type`, không nối Bước chạy theo `node_id` của dòng chờ, vì dòng
  chờ `incident` mang `node_id` của node sự cố mà trình biên dịch dựng cho Bước lỗi, tên dẫn từ id Bước (mục Dữ liệu và
  ticket 07 của workflow-engine), nên phép nối đó không gặp lần thử nào và câu "Kết quả lần trước không rõ" không bao giờ
  hiện; lượt đỗ ngay sau lần thử cuối, và không Bước nào có `on_error` `incident` nằm trong làn song song
  (workflow-engine:R2.16), nên một lượt có nhiều nhất một sự cố `open` và Bước chạy đó là của đúng Bước lỗi. Sửa: R6.1,
  API, TA21, Phụ thuộc (Kiểm lại khi), ticket 04. Nếu sai thì: dòng chờ `incident` của workflow-engine mang thêm id Bước lỗi, và route đọc lần
  thử cuối theo id đó.
- 25/10/2026 (Đạt): V4.30: lời hứa "đúng một lần" thành các mức bảo đảm cùng điểm chờ `outcome_review`; khi không rõ
  kết quả, lượt sang `waiting` trên một dòng chờ `outcome_review` và Lịch sử chạy hiện "Không rõ nhà cung cấp đã nhận
  hay chưa" với `reason_code` `outcome_unknown`. Sửa: R4.8, R6.5, TA22, TA24, Màn hình, ticket 03, 04.
- 25/10/2026 (Đạt): V4.31: gỡ cạnh giả trước khi ticket nào lên `ready-for-agent`; ở lát này, chuỗi các ticket sửa tệp
  retention bỏ (H-1): ticket 03 chờ ticket 01; compliance-pdpl/04, agent-builder/04 và workflow-triggers/02 thôi chờ
  ticket 03 (và thôi chờ nhau vì tệp), rồi cùng compliance-pdpl/06 và agent-lifecycle/06 chờ ticket 01, ở dòng Blocked
  by của chính chúng. Sửa: R5, Dữ liệu, Phụ thuộc, ticket 01, 03.
- 25/10/2026 (Đạt): V4.35: bản kê lượt chạy ghim id kết nối và phiên bản Bộ giá trị gắn, không ghim phiên bản bí mật;
  chạy tiếp từ Bước lỗi dùng Bộ giá trị gắn đã ghim và phiên bản mới nhất chưa thu hồi của bí mật, nên câu cạnh nút
  của màn sự cố thôi nói lượt dùng lại phiên bản bí mật đã ghim. Sửa: R6.4, Màn hình, ticket 04.
- 25/10/2026 (Đạt): V4.36: `platform.run_steps` có `attempt`, `port` và `child_run_id` ngay từ migration tạo bảng, không
  `branch_key` (H-11); một Bước đang chờ có dòng của nó từ lúc đỗ; màn `/runs/[id]` là cây antd `Tree` có "đang chờ ở
  đâu" và lý do bị giữ; catalog mã lý do có nhãn tiếng Việt với một chủ (H-12). Sửa: R1.9, R3.8, R3.9, R3.10, R4.2,
  R4.6-R4.9, TA23-TA25, Dữ liệu, API, Màn hình, Trong phạm vi, Phụ thuộc, ticket 03.
- 25/10/2026 (Đạt): V4.41: người giữ `studio.workflows.test` đọc Bước chạy và chi tiết của lượt `simulate` mà
  `requested_by` là chính mình; lượt `live` vẫn đòi `runs.read`; bảo mật trường áp như mọi nơi; lượt của người khác,
  lượt `live` khi không giữ `runs.read` và lượt của công ty khác trả như không tồn tại (404); danh sách `/runs` không
  đổi ở W1 (H-17). Sửa: R4, R4.4, R4.5, G1, TA26, API, Màn hình, Phụ thuộc, ticket 03.
- 25/10/2026 (agent, tạm): H-1: chính sách lưu giữ là một mảnh mỗi kho, `configs/policies/retention.d/<schema>.<table>.yaml`
  (kho không phải bảng dùng tên có tiền tố), cùng các trường của mục khóa trước đây (thời hạn, bộ xóa, cổng `enforced`);
  release manifest ghim mã băm của tập mảnh thay cho semver của tệp; ticket nào đăng ký kho thì thêm mảnh của nó trong
  cùng thay đổi, không có chuỗi ticket; lát này vẫn là chủ định dạng và lane (Đạt 24/10/2026; V4.21): định dạng mảnh,
  bộ đọc tập mảnh, bộ nạp `platform.retention_terms`, `platform.retention_term_days(text)`, test lệch bảng (R5.9-R5.12)
  và test phủ dời từ ticket 03 về ticket 01, ticket sớm nhất của lát, cùng việc gỡ ánh xạ tạm `retention@1.7.0` của
  studio-skeleton/01 và mảnh `platform.audit_events`; lane lưu giữ và các hàm xóa của lát ở ticket 03; studio-skeleton:R3.7
  đọc tập mảnh, và `platform.drop_expired_partitions` của usage-and-limits/02 đọc mốc từ tập mảnh. Sửa: R5, R5.1, R5.6,
  R5.9, R5.10, R5.12, thêm R5.13, R5.14, TA17, TA19, thêm TA27, Trong phạm vi, Dữ liệu, Phụ thuộc, Danh sách ticket,
  ticket 01, 03. Nếu sai thì: một tệp có phiên bản với chuỗi ticket như V4.P1.
- 25/10/2026 (agent, tạm): cách áp H-1 ở lát này: tên tệp là khóa của mảnh, nên không có trường `store` thứ hai lệch được
  tên; kho có tên có trong danh sách của mô hình chính sách (`objects.run_step_payloads`, `platform.worker_runs.payload`
  cho cột payload của lượt chạy, vì một bảng có hai thời hạn); test phủ của mảnh là test catalog của studio-skeleton:R3.7
  chạy trên bộ đọc tập mảnh (R5.13), không phải một test thứ hai cho cùng sự thật; ticket 01 thay `retention@1.7.0` bằng
  `retention@1.8.0` chỉ bỏ thời hạn `audit_events` đã sang mảnh (một chủ) và chú thích "model_usage_ledger đã bị bỏ", nên
  chỉ ticket 01 sửa tệp có phiên bản đó; R5.12 nêu `platform.retention_term_days` làm chủ thể, vì hàm đó ra đời ở ticket
  01 còn hàm xóa hẹp ở ticket 03 và compliance-pdpl/06; ticket 01 chờ studio-skeleton/01, cạnh ngoài mục B, đã mô phỏng
  không đổi độ sâu `marketing-pilot/03` (15). Sửa: R5.6, R5.12, R5.13, TA27, Dữ liệu, Phụ thuộc, ticket 01, 03. Nếu sai
  thì: mảnh mang trường `store` riêng, test phủ là test riêng của lát này, `audit.tables` giữ ở tệp có phiên bản cạnh
  mảnh với một test bắt hai bản khớp nhau, và ticket 01 không chờ studio-skeleton/01 vì studio-skeleton/01 đọc mảnh
  `platform.audit_events` thay ánh xạ tạm.
- 25/10/2026 (agent, tạm): H-11: không có `branch_key`; nhánh của làn song song là `lane_path` đã có, nhánh của `switch`
  và quyết định của phê duyệt là `port`, vì thêm `branch_key` là hai bản của một sự thật (`failure-modes.md` #2). Sửa:
  R3.9, Dữ liệu. Nếu sai thì: thêm `branch_key` bằng phần tử cuối của `lane_path`.
- 25/10/2026 (agent, tạm): H-12: lát này là chủ `configs/copy/run_reason_codes@1.0.0.yaml` (mã → nhãn tiếng Việt, cạnh
  catalog audit của ADR-0122 (Accepted) quyết 6), tạo ở ticket 03; mọi `reason_code` và `error.code` mà workflow-engine,
  các lane và cửa nhận lượt ghi phải có nhãn, test đỏ khi một mã thiếu nhãn; API trả nhãn cạnh mã như `action_label`
  của R1.7, nên màn không giữ bảng nhãn nào. Sửa: R1.9, R4.6, R6.5, TA22, TA25, Trong phạm vi, Phụ thuộc, Q2, ticket 03, 04. Nếu sai thì: nhãn nằm ở bảng mã `wf.*` của workflow-engine.
- 25/10/2026 (agent, tạm): H-17: W1 không đổi `/runs` (vẫn `runs.read`); người dựng tới lượt mô phỏng của mình từ trang
  builder qua id lượt mà route `test-runs` trả. Sửa: Màn hình, TA26. Nếu sai thì: `/runs` cho người giữ
  `studio.workflows.test` thấy lượt mô phỏng của chính mình.
- 25/10/2026 (agent, tạm): cách áp V4.36 ở lát này: `run_steps` vẫn chỉ thêm (DO-02.2), nên một Bước đã chờ có hai dòng,
  `waiting` ghi lúc đỗ trong giao dịch ghi dòng chờ rồi dòng kết thúc cùng `started_at`, nối bằng (`run_id`, `kind`,
  `node_id`, `iteration_path`, `attempt`); lý do chờ ở cột `reason_code` riêng với CHECK `(status = 'waiting') =
(reason_code IS NOT NULL)` và `status` có CHECK (`waiting`, `succeeded`, `failed`, `cancelled`), vì để lý do chờ vào
  `error_type` sẽ làm route sự cố đọc nhầm dòng `waiting` là lần thử lỗi, và một trạng thái không CHECK mở cửa cho giá
  trị lạ mà màn đọc sai lặng lẽ (`failure-modes.md` #7); `attempt` không DEFAULT; `child_run_id` FK ghép ON DELETE RESTRICT
  như `parent_run_id` của workflow-engine, vì dòng Bước chạy sống ngắn hơn lượt chạy; lượt đã kết thúc mà Bước còn
  `waiting` với `outcome_unknown` hiện nhãn của khóa `effect_unresolved` trong catalog (H-6); màn sự cố đọc nhãn
  `outcome_unknown` từ catalog thay câu "Kết quả lần trước không rõ", để một sự thật có một chữ. Sửa: R3.8, R3.9, R3.10,
  R4.8, R4.9, R6.5, TA23, TA24, Dữ liệu, Màn hình, ticket 03, 04. Nếu sai thì: dòng `waiting` được sửa thành dòng kết thúc
  qua một hàm SECURITY DEFINER hẹp, lý do chờ đọc từ `platform.run_waits.kind` của dòng chờ `open`, CHECK `status` thêm
  giá trị mà wrapper ghi, `child_run_id` ON DELETE SET NULL, và màn sự cố giữ câu riêng của nó.
- 25/10/2026 (agent, tạm): cách áp V4.41 ở lát này: người dựng phải giữ `studio.workflows.test` tới workspace của lượt
  theo độ sâu, như mọi khóa (ADR-0104 (Accepted) quyết 3); người không giữ `runs.read` tới workspace của lượt nhận 404
  cho `GET /api/v1/runs/{run_id}` thay 403 của hôm nay, vì quyết định gọi lượt `live` khi không giữ `runs.read` là không
  tồn tại, và `test_reading_a_run_needs_runs_read` đổi theo; payload của lượt mô phỏng là Q7, vì V4.41 chỉ nói Bước
  chạy và chi tiết. Sửa: R4, R4.4, R4.5, G1, TA26, API, Phụ thuộc, Q7, ticket 03. Nếu sai thì: người gọi thiếu cả hai
  khóa vẫn nhận 403 như hôm nay và chỉ lượt của người khác hay lượt `live` của người dựng là 404.
- 25/10/2026 (agent, tạm): màn giải `outcome_review` của V4.30 ("Đã nhận", "Chưa nhận, gửi lại cùng khóa", "Bỏ") thuộc
  lát này, vì màn Lịch sử chạy có một chủ (V4.26) và workflow-engine giao màn đó cho lát này ở mục Ngoài phạm vi của nó;
  màn đọc dòng chờ qua một route đọc riêng `GET /api/v1/runs/{run_id}/outcome-reviews` như route sự cố của R6, vì route
  giải nhận `wait_id` trong đường dẫn, và đọc Bước đang chờ từ dòng `waiting` của nó, không từ `node_id` của dòng chờ, là
  node xác nhận mà trình biên dịch dựng; màn và route vào ticket 04 cạnh khối sự cố, vì ticket 04 đã chờ
  workflow-engine/07, ticket sâu hơn workflow-engine/08 (cả hai chờ workflow-engine/05), và không ticket nào chờ ticket
  04, nên cạnh trực tiếp tới workflow-engine/08 không làm ticket 04 sâu thêm và không đổi độ sâu `marketing-pilot/03`
  (đã mô phỏng: 15), còn ticket 03 chờ workflow-engine/08 thì `marketing-pilot/03` sâu 17; lối ra W1a không chờ màn này,
  vì ca K4 của marketing-pilot/03 chỉ đếm email và dòng `outcome_review`. Sửa: thêm R7, TA28, TA29, Trong phạm vi, Ngoài
  phạm vi, API, Màn hình, Phụ thuộc, Danh sách ticket, ticket 04. Nếu sai thì: màn ở một ticket mới của lát này chờ
  ticket 03 và workflow-engine/08, hay ở workflow-engine/08, và R7 dời theo.
- 25/10/2026 (agent, tạm): H-19: workflow-engine/01 đăng ký `studio.workflows.test` vào danh mục quyền cùng các khóa
  khác của loại `workflow` (workflow-engine:R1.5), dời từ workflow-triggers/01; workflow-triggers/01 (route `test-runs`)
  và ticket 03 (R4.4) kiểm khóa đó, và workflow-engine/01 đã là tổ tiên của cả hai nên không thêm cạnh. Hỏi: Q4. Sửa:
  Phụ thuộc, Câu hỏi còn mở, ticket 03. Nếu sai thì: ticket 03 đăng ký khóa và workflow-triggers/01 chờ ticket 03.
- 25/10/2026 (agent, tạm): H-20: `ix_worker_runs_page` dời từ ticket 03 sang workflow-engine/02, ticket thêm cột và chỉ
  mục của `platform.worker_runs`; route danh sách của R4.1 dẫn chỉ mục đó, và ticket 02 (CHECK `trace_id`) cùng ticket
  03 thôi cùng sửa bảng đó, nên ticket 03 không chờ ticket 02. Hỏi: Q6. Sửa: API, Phụ thuộc, Câu hỏi còn mở, ticket 03.
  Nếu sai thì: ticket 03 giữ chỉ mục và chờ ticket 02.
- 25/10/2026 (agent, tạm): H-21: nhãn hành động audit và nhãn mã lý do là mảnh theo spec,
  `configs/copy/audit_actions.d/<spec>.yaml` và `configs/copy/run_reason_codes.d/<spec>.yaml`, do bộ nạp của lát này,
  chủ cả hai catalog, gộp; tập mảnh ghim bằng mã băm trong release manifest; ticket nào ghi một hành động hay mã mới
  thêm nhãn vào mảnh của spec mình trong cùng thay đổi; test đỏ khi một hành động hay mã thiếu nhãn; mảnh thay tệp có
  phiên bản của dòng 24/10/2026 về catalog hành động và của dòng H-12. Hỏi: Q2. Sửa: R1.6, R1.7, R1.9, R4.6, thêm
  R1.10, R1.11, TA15, TA25, thêm TA30, Trong phạm vi, API, Phụ thuộc, Câu hỏi còn mở, ticket 03. Nếu sai thì: mỗi
  catalog một tệp có phiên bản với chuỗi ticket.
- 25/10/2026 (agent, tạm): cách áp H-21 ở lát này: một khóa khai ở hai mảnh làm bộ nạp từ chối cả catalog, kể cả khi hai
  nhãn giống nhau, vì hai bản của một nhãn lệch nhau lặng lẽ (R1.10; `failure-modes.md` #2), nên một mã mà hai spec cùng
  ghi, như `outcome_unknown`, có nhãn ở mảnh của ticket ghi nó trước; mảnh `telemetry-and-audit.yaml` của mỗi catalog
  mang nhãn của lời ghi có trước các spec Studio (kể cả sáu nhãn của bảng `ACTIONS` cũ), của lời ghi mà lát này đưa vào
  và của khóa `effect_unresolved`, thay một mảnh không thuộc spec nào; một ticket đi trước ticket 03 vẫn thêm mảnh của
  mình, và ticket 03 thêm vào đúng mảnh đó nhãn còn thiếu mà test AST của nó thấy; hai tập mảnh nằm dưới
  `configs/copy/`, mà `_copy_bundles` của `scripts/release_manifest.py` đọc đệ quy và đòi `copy_id` ở mỗi tệp, nên
  ticket 03 cho hàm đó bỏ qua hai thư mục `.d` và thêm một mục mã băm cho mỗi tập, dùng lại hàm băm tập mảnh của ticket
  01 (R1.11). Sửa: R1.10, R1.11, TA30, Trong phạm vi, Phụ thuộc, ticket 03. Nếu sai thì: khóa trùng chỉ bị từ chối khi
  hai nhãn khác nhau, nhãn có trước Studio nằm ở một mảnh `platform.yaml` riêng, hay mỗi mảnh mang `copy_id` và
  `version` để `_copy_bundles` ghim từng tệp.
- 25/10/2026 (agent, tạm): nhãn của tác động chưa giải (H-6) tới màn qua API như mọi nhãn: `GET .../steps` mang
  `effect_unresolved_label` trên dòng `waiting` `outcome_unknown` mới nhất của một Bước ở lượt đã kết thúc (R4.10), vì
  màn không giữ bảng nhãn nào (H-12) mà R4.9 cần chữ của khóa `effect_unresolved`, khóa không lời ghi nào đặt lên Bước
  chạy; R4.9 phủ mọi lượt đã kết thúc, kể cả lượt bị hủy khi Tắt khẩn hay Đóng băng (H-22). Sửa: R4.9, thêm R4.10, TA24,
  TA25, Trong phạm vi, API, Màn hình, ticket 03. Nếu sai thì: `reason_label` của dòng đó mang nhãn của
  `effect_unresolved` thay một trường riêng, hay `GET /api/v1/runs/{run_id}` trả danh sách Bước còn tác động chưa giải
  kèm nhãn.
- 26/10/2026 (agent, tạm): H-35, sổ bộ xóa: `RetentionPurgerRegistry` khai ở ticket 01 cùng bộ đọc tập mảnh, không ở
  ticket 03, vì workflow-triggers/02, custom-objects/03 và usage-and-limits/02 tạo kho và bộ xóa của nó mà chỉ chờ
  ticket 01; thêm cạnh tới ticket 03 đẩy độ sâu `marketing-pilot/03` lên 17. Lane lưu giữ của ticket 03 chạy mọi bộ
  xóa trong sổ, và test của R5.2 so sổ với tập mảnh. Sửa: Phụ thuộc, ticket 01, 03; workflow-triggers/02. Nếu sai thì:
  workflow-triggers/02 chờ ticket 03 và độ sâu đó lên 17.
- 26/10/2026 (agent, tạm): H-36, `enforced` của mảnh có số Đạt đã đáp (DO-52: `studio.inbound_events`,
  `studio.trigger_deliveries`, `studio.inbound_dedupe`, `studio.conversations`, `studio.conversation_messages` sau
  compliance-pdpl/06) là `true`, vì lời đáp là số tạm có chủ và bộ xóa theo dòng chỉ xóa phần đã quá hạn; mảnh có số
  còn chờ một câu hỏi mở giữ `false` tới khi câu đó được đáp (usage-and-limits Q3). Sửa: workflow-triggers/02. Nếu
  sai thì: mọi mảnh `false` tới cổng E3 và `make retention-unenforced` liệt kê cả năm.
- 26/10/2026 (agent, tạm): H-33, mảnh `enforced: false` chưa có bộ xóa: một kho có thể có mảnh trước bộ xóa của nó (như
  `studio.conversation_messages` của agent-builder/04, bộ xóa ở compliance-pdpl/06) hay chờ luật sư xác nhận hạn
  (usage-and-limits Q), nên test tập bộ xóa của R5.2 đòi bộ xóa đã đăng ký cho mọi mảnh `enforced: true` và cho mảnh
  `enforced: false` chỉ đòi `description` nêu ticket hay câu hỏi còn nợ; `make retention-unenforced` liệt kê các mảnh
  đó, vì cổng E3 đòi hạn lưu dữ liệu cá nhân đã được thực thi (requirements.md:YC99), nên danh sách rỗng ở mọi kho dữ
  liệu cá nhân là bằng chứng của E3, không phải một cờ ai cũng quên. Sửa: ticket 03. Nếu sai thì: test đỏ với mọi mảnh
  thiếu bộ xóa, và agent-builder/04 đăng ký bộ xóa hội thoại thay compliance-pdpl/06.
- 25/10/2026 (agent, tạm): H-31, kho không hết hạn theo thời gian (Danh sách chặn gửi của compliance-pdpl/06): mảnh
  mang `days: indefinite` với `purger: none`, vì `days: null` nghĩa là chưa ai quyết và một kho đã quyết là giữ mãi
  không được đọc như kho còn chờ quyết; bộ nạp không ghi dòng cho nó, như kho chưa `enforced`, và mô hình mảnh từ chối
  `purger: none` đi với `days` khác `indefinite`. Sửa: Dữ liệu, ticket 01; compliance-pdpl/06. Nếu sai thì: mảnh mang
  thêm khóa `term: indefinite`, `days` bỏ trống, và mô hình mảnh nhận năm khóa.
- 25/10/2026 (agent, tạm): H-27: usage-and-limits/02 chờ ticket 01, vì mốc của `platform.drop_expired_partitions` đọc
  qua bộ đọc tập mảnh (R5.13) và test của studio-skeleton:R3.7 cho `platform.usage_events` mà ticket đó đăng ký cần bộ
  đọc đó; đã mô phỏng: độ sâu `marketing-pilot/03` 15, chuỗi dài nhất 18; cạnh nằm ở dòng Blocked by của
  usage-and-limits/02. Hỏi: Q5. Sửa: Phụ thuộc, Câu hỏi còn mở. Nếu sai thì: cạnh đó bỏ, và ticket 01 mang mảnh và test
  phủ của `platform.usage_events` thay usage-and-limits/02.
- 26/10/2026 (Đạt): Q-h4 theo khuyến nghị ("theo khuyến nghị hết cho tôi"): ở W1 người dựng không xem payload của
  lượt mô phỏng do chính mình xin khi thiếu `runs.read_payloads`; R4.3 giữ 403 theo ADR-0122 (Accepted) quyết 4,
  không thêm nhánh. Hỏi: Q7. Sửa: R4.4. Không đổi TA26 và ticket 03, vốn đã thử 403 đó.
- 27/10/2026 (Đạt): Index Nhật ký kiểm toán theo lượt chạy mang `workspace_id` sau `run_id`, `platform.audit_events (tenant_id, run_id, workspace_id, occurred_at)`, vì danh sách theo lượt chạy lọc theo workspace và app-standards:R6.1 đòi mọi cột vị từ nằm trong `Index Cond` (ADR-0122 (Accepted), sửa 27/10/2026). Sửa: Ngoài phạm vi.

## Danh sách ticket

| #   | Ticket                                                                                                                                                    |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Module ánh xạ OTel GenAI ghim commit, không nội dung; metric phát hoặc xóa; mảnh retention và bảng thời hạn](issues/01-otel-khong-noi-dung-va-metric.md) |
| 02  | [Cây span thật và một trace id từ trình duyệt đến worker](issues/02-cay-span-va-mot-trace-id.md)                                                          |
| 03  | [Lịch sử chạy theo bước: `run_steps` có che và lưu giữ, danh sách run, chi tiết bước](issues/03-lich-su-chay-theo-buoc.md)                                |
| 04  | [Màn sự cố trên Lịch sử chạy: Chạy tiếp từ Bước lỗi và Kết thúc; màn giải outcome_review](issues/04-man-su-co-tren-lich-su-chay.md)                       |
