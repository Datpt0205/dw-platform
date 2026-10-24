# Telemetry, lịch sử chạy và nhật ký kiểm toán

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Người dựng cần xem một lượt chạy đã làm gì theo từng bước (trạng thái, thời gian, lỗi, token, chi phí,
đầu vào và đầu ra), cổng kiểm định cần kết quả từng bước, nhưng chưa có kho nào cho công ty giữ việc đó
dưới RLS; telemetry hiện phát tên lệch spec GenAI và có thể mang nội dung. Lát này đưa một module ánh xạ
OTel GenAI ghim commit chỉ mang định danh, một trace id đi từ trình duyệt tới worker, và một kho Lịch sử
chạy theo bước che bí mật khi ghi và che theo quyền đọc trường của người xem khi đọc
(ADR-0122 (Accepted), ADR-0106 (Accepted)). W1 phục vụ YC23, YC80, YC81 và một phần YC82 (ghi `run.payload.viewed`)
và YC88; lọc và xuất Nhật ký kiểm toán (YC83), Langfuse cho Người vận hành và Ghi nội dung theo công ty
thuộc W2.

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

### R4 — Màn Lịch sử chạy đọc dưới `runs.read` theo độ sâu

Người giữ `runs.read` xem danh sách lượt chạy và chi tiết từng bước trong tập workspace được phép.

- R4.1 KHI người giữ `runs.read` gọi `GET /api/v1/runs`, API Lịch sử chạy PHẢI trả các lượt chạy trong tập
  workspace được phép theo độ sâu, phân trang keyset mà trang kế không trùng và không sót dòng.
- R4.2 KHI người giữ `runs.read` gọi `GET /api/v1/runs/{run_id}/steps`, API Lịch sử chạy PHẢI trả các Bước
  chạy của lượt đó theo thứ tự `seq`.
- R4.3 NẾU người gọi `GET /api/v1/runs/{run_id}/steps/{step_id}/payload` thiếu `runs.read_payloads`, THÌ
  API Lịch sử chạy PHẢI trả 403 và không trả payload.

### R5 — Lưu giữ có bộ xóa cho mỗi kho, không xóa lượt chạy còn sống

Mỗi kho lát này tạo, và các kho sự kiện vào mà lane lưu giữ của lát này đọc hạn, có một thời hạn và một bộ
xóa; lượt chạy chưa kết thúc hay còn được tham chiếu không bị xóa. Lát này là chủ định dạng của tệp chính sách
retention (một khóa `schema.table` mỗi kho) và các lane lưu giữ; mỗi ticket đăng ký một bảng `append_only` tự
thêm thời hạn của bảng mình vào một bản mới của tệp trong cùng thay đổi, nên studio-skeleton:R3.7 xanh ngay khi
đăng ký; thời hạn và bộ xóa của sự kiện vào, lần giao kích hoạt và khóa chống trùng do workflow-triggers/02 thêm,
lane của lát này thi hành (workflow-triggers:R6.3, workflow-triggers:R6.4, workflow-triggers:R6.7); mọi số là số
tạm UNVERIFIED tới khi luật sư xác nhận trước chạy bóng (ADR-0122 (Accepted) quyết 7; DO-52).

- R5.1 ĐỐI VỚI mỗi kho dữ liệu cá nhân mới (`platform.run_steps`, payload đối tượng, cột payload của lượt
  chạy, Sổ sử dụng, `studio.inbound_events`, `studio.trigger_deliveries`), tệp chính sách retention đang ghim
  PHẢI khai dưới khóa của kho một thời hạn và một bộ xóa đã đăng ký.
- R5.2 NẾU một kho dữ liệu cá nhân không có bộ xóa đăng ký, THÌ test tập bộ xóa PHẢI đỏ.
- R5.3 NẾU một lượt chạy chưa kết thúc hay còn được `memory.items` trỏ tới, THÌ lane lưu giữ PHẢI bỏ qua
  nó và vẫn đếm nó.
- R5.4 ĐỐI VỚI một Bước chạy quá 30 ngày (YC88), lane lưu giữ PHẢI xóa payload của bước (preview trong dòng
  và đối tượng theo tham chiếu) dù partition của tháng đó chưa tới lúc DROP.
- R5.5 NẾU một sự kiện vào quá 30 ngày còn được một lượt chạy `queued` trỏ tới, hay đang bị làn `studio_inbound`
  giữ vì Đóng băng (chưa xin lượt chạy), THÌ lane lưu giữ PHẢI bỏ qua nó và đếm nó trên metric của lane theo lý
  do, vì Đóng băng không có trần thời gian (agent-lifecycle:R7.2).
- R5.6 Mỗi thời hạn trong tệp chính sách retention PHẢI nằm dưới khóa `schema.table` của bảng nó canh (kho không
  phải bảng dùng tên kho có tiền tố của nó), nên hai bảng cùng tên ở hai schema không đụng nhau và một khóa không
  khớp bảng nào làm test của tệp đỏ (ADR-0100 (Accepted) quyết 7).
- R5.7 KHI `output` của một dòng `platform.tool_executions` quá 30 ngày, lane lưu giữ PHẢI xóa trắng cột đó qua
  một hàm SECURITY DEFINER hẹp chỉ đặt NULL `output`, mà không trả UPDATE trên bảng cho `dw_app`
  (foundations-hardening:R6.3; ADR-0122 (Accepted) quyết 7).
- R5.8 KHI lane `offboarding` xóa dữ liệu của một công ty đang `offboarding`, lane `offboarding` PHẢI xuất rồi
  xóa mọi dòng `platform.run_steps` của công ty đó qua `platform.purge_tenant_append_only`
  (usage-and-limits:R3.8; YC6).

## Trong phạm vi

- Bảng, cột và phân vùng ở mục Dữ liệu; route ở mục API; màn ở mục Màn hình.
- Mã: `dw_observability.semconv` (tên span, khóa thuộc tính, tên metric GenAI, `GENAI_SEMCONV_COMMIT`);
  `TelemetryPort.record_histogram` với `OtelTelemetry`, `RecordingTelemetry`, `NullTelemetry`; span
  processor Langfuse; formatter log JSON có danh sách trường cho phép; `StepRecorderPort` và adapter ghi
  `platform.run_steps`; đọc Sổ sử dụng cho token và chi phí mỗi Bước chạy; định dạng tệp chính sách retention
  (khóa `schema.table`, R5.6) và các lane lưu giữ; dòng thời hạn của kho lát này tạo hay xóa mà không ticket
  đăng ký nào khác thêm (lớp run, bước, payload, `tool_executions.output`, `usage_daily`; DO-52); hàm SECURITY
  DEFINER hẹp xóa trắng `platform.tool_executions.output` (R5.7).
- Khóa quyền `runs.read_payloads` đăng ký ở ticket 03 theo quy ước của tenant-rbac/01.
- Thêm cột `trace_parent` cho `platform.outbox_events`; CHECK `trace_id` cho `platform.worker_runs` và
  `platform.audit_events`; đăng ký `run_steps` bằng một dòng `platform.time_partitioned_tables`.
- Audit: `run.payload.viewed`.

## Ngoài phạm vi

| Việc                                                                                                             | Vì sao                                                                              | Chủ                                           |
| ---------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | --------------------------------------------- |
| W2: Lọc Nhật ký kiểm toán phía máy chủ, danh mục hành động một chủ (YC83)                                        | cần bộ lọc; cơ chế của W1 không chặn                                                | telemetry-and-audit, đợt sau (W2)             |
| Index Nhật ký kiểm toán theo lượt chạy `platform.audit_events (tenant_id, run_id, occurred_at)` trên bảng cha    | một chủ (OPS-b); `ix_audit_events_run` của ADR-0122 (Accepted) bỏ; ticket 02 chờ nó | app-standards                                 |
| W2: Xuất Nhật ký kiểm toán qua tác vụ nền, link hết hạn 7 ngày (YC83)                                            | đọc tính năng `audit_export`; chờ danh mục hành động                                | telemetry-and-audit, đợt sau (W2)             |
| W2: Langfuse chỉ cho Người vận hành, ghim theo digest, lên v4                                                    | không gửi nội dung thì không cần bản Enterprise                                     | telemetry-and-audit, đợt sau (W2)             |
| W2: Ghi nội dung theo công ty qua chính sách `telemetry.content_capture` có audit, giữ ≤ 7 ngày, chỉ công ty đọc | DO-51.1; cần chính sách của tenant-config                                           | telemetry-and-audit, đợt sau (W2)             |
| W2: `traceparent` tới Cổng MCP (chặng nội bộ) nhưng không tới máy chủ MCP nào, không bao giờ `baggage`           | DO-46.3; mcp-client là W2; chỉ mở lại khi có nhà cung cấp trả span về nền tảng      | mcp-client; telemetry-and-audit, đợt sau (W2) |
| W3: Collector, lấy mẫu đuôi, bảng Grafana; chuỗi băm chống sửa, đẩy SIEM                                         | v1.5 trở đi                                                                         | telemetry-and-audit, đợt sau (W3)             |
| Bộ bọc node phát span và gọi `StepRecorderPort`                                                                  | lát này cấp `dw_observability.semconv` và `StepRecorderPort`                        | workflow-engine                               |
| Nhận diện dữ liệu cá nhân tiếng Việt ở exporter (Presidio)                                                       | bộ dò là kiểm soát phụ, có số đo trước khi dựa vào                                  | compliance-pdpl, đợt sau (W2)                 |
| Điểm đánh giá trực tuyến (`gen_ai.evaluation.result`)                                                            | dùng sự kiện GenAI nhưng thuộc cổng kiểm định                                       | agent-lifecycle                               |
| Sổ sử dụng theo lượt gọi và Bảng giá                                                                             | lát này đọc token và chi phí từ sổ, không tạo sổ                                    | usage-and-limits                              |
| Sổ `platform.time_partitioned_tables` và hàm tạo partition                                                       | lát này chỉ đăng ký `run_steps` bằng một dòng sổ (studio-skeleton:R3.1)             | studio-skeleton                               |
| Hàm quyết quyền đọc trường và dấu `Đã ẩn`                                                                        | lát này gọi hàm đó khi đọc payload                                                  | field-security                                |
| Trace thô cho công ty đọc                                                                                        | span ở backend không có RLS theo công ty; công ty đọc từ Postgres                   | không làm                                     |

## Dữ liệu

Mọi bảng gắn công ty: RLS ENABLE và FORCE theo công ty, grant cùng migration, tên ràng buộc theo
`NAMING_CONVENTION`, revision id hex ngẫu nhiên.

- `platform.run_steps`: phân vùng theo tháng trên `started_at` với DEFAULT; `PRIMARY KEY (id, started_at)`;
  `kind` CHECK (`node`, `model_call`, `tool_call`, `approval`, `sub_run`); gắn `tenant_id`, `workspace_id`,
  `run_id`, `root_run_id`, `seq int`, `node_id`, `status`, `started_at timestamptz`, `finished_at
timestamptz`, `duration_ms`, `error_type`; `input_preview` và `result_preview` (≤ 4 KB), `input_ref` và
  `result_ref` (đường dẫn đối tượng, NULL khi giữ trong dòng); token, `cost_usd numeric(18,8)`,
  `price_book_version`, `redaction_log jsonb NOT NULL DEFAULT '[]'`, `fls_version`; không cột nội dung thô;
  `dw_app` không UPDATE, DELETE trên cha và không giữ quyền nào trên phân vùng nào, kể cả DEFAULT, nên đọc
  ghi qua bảng cha (DO-02.2); đăng ký bằng một dòng `platform.time_partitioned_tables` (`append_only = true`,
  studio-skeleton:R3.1), ENABLE/FORCE RLS và policy công ty trên cha và DEFAULT; giữ 30 ngày (YC88) dưới khóa
  `platform.run_steps` mà ticket 03 thêm cùng thay đổi đăng ký: lane lưu giữ xóa payload của bước quá 30 ngày
  (R5.4), DROP PARTITION khi cả tháng quá 30 ngày (thực tế 30-61 ngày); vì `dw_app` không DELETE, bảng có một
  dòng `STUDIO_EXCLUSIONS` nêu cách xóa khi offboarding, `platform.purge_tenant_append_only` (R5.8;
  studio-skeleton:R4.3); index `ix_run_steps_run (tenant_id, run_id, seq)`.
- `platform.outbox_events`: thêm `trace_parent text` CHECK định dạng W3C `traceparent`; dispatcher worker
  tiếp trace từ cột đó.
- `platform.worker_runs`, `platform.audit_events`: CHECK `trace_id ~ '^[0-9a-f]{32}$'` dạng `NOT VALID`.
- Tệp chính sách retention (lát này là chủ định dạng, ADR-0100 (Accepted) quyết 7, ADR-0122 (Accepted) quyết 7):
  một tệp có phiên bản `configs/policies/retention@<semver>.yaml`; mỗi kho một khóa `schema.table` (kho không phải
  bảng dùng tên có tiền tố, như `objects.run_step_payloads`), mỗi khóa mang thời hạn, bộ xóa (DROP PARTITION qua
  `platform.drop_expired_partitions`, lane xóa dòng, lane xóa đối tượng, xóa trắng cột) và cổng `enforced`; mỗi lần
  thêm hay đổi một khóa là một bản mới của tệp, ghim trong release manifest, và các ticket sửa tệp đi thành một
  chuỗi theo `Blocked by`, mỗi ticket ra một bản (mục Phụ thuộc); mọi số UNVERIFIED tới khi luật sư xác nhận trước
  chạy bóng. Ticket 03 thêm: `run_steps` 30 ngày (lane xóa payload ở ngày 30, DROP PARTITION khi cả tháng quá hạn),
  payload đối tượng 30 ngày (lane xóa đối tượng), cột payload lượt chạy 90 ngày sau kết thúc (lane xóa), lượt chạy
  395 ngày sau kết thúc bỏ qua dòng `memory.items` trỏ tới (lane xóa), `platform.tool_executions.output` 30 ngày
  (xóa trắng qua hàm của R5.7), `usage_daily` 760 ngày (lane xóa); bỏ chú thích "model_usage_ledger đã bị bỏ" của
  bản 1.7.0. Thời hạn của bảng mà spec khác tạo do ticket tạo bảng thêm (usage-and-limits/02, usage-and-limits/03,
  agent-lifecycle/04, workflow-triggers/02 với `studio.inbound_events`, `studio.trigger_deliveries` và
  `studio.inbound_dedupe`, compliance-pdpl/04, agent-builder/04), và compliance-pdpl/06 thêm lớp của nó; lát này
  không khai lại số đó.

## API

- `GET /api/v1/runs?artifact_kind&artifact_id&status&trigger_kind&from&to&cursor&limit` (`runs.read`, RLS
  và workspace theo độ sâu): danh sách lượt chạy, phân trang keyset.
- `GET /api/v1/runs/{run_id}/steps` (`runs.read`): các Bước chạy theo `seq`.
- `GET /api/v1/runs/{run_id}/steps/{step_id}/payload?part=in|out` (`runs.read_payloads`): payload che theo
  quyền đọc trường của người xem; audit `run.payload.viewed` trong cùng giao dịch.
- Lỗi theo vỏ `application/problem+json` của ADR-0108 (Accepted), mang `trace_id`; `details.reason_code`
  cho 404 cách ly.

## Màn hình

- Màn `/runs` (antd Table: thời điểm, agent hoặc quy trình, trạng thái, nguồn kích hoạt, thời lượng, chi
  phí; bộ lọc theo `artifact`, trạng thái, nguồn kích hoạt, khoảng thời gian), đọc `GET /api/v1/runs`.
- Màn `/runs/[id]` (antd: Steps cho các Bước chạy, Descriptions, xem JSON có dấu `Đã ẩn`, token và chi phí
  mỗi Bước chạy, nút "Sao chép trace id").

## Kiểm soát

| #    | Kiểm soát                                           | Yêu cầu    | Test âm                                                                                                                                                                                                                                                                                 |
| ---- | --------------------------------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TA1  | Span, log, audit không mang nội dung                | R1.2       | Input có số điện thoại → không span, log hay sự kiện Nhật ký kiểm toán nào chứa giá trị đó; bật Ghi nội dung cho công ty A không làm span công ty B mang nội dung                                                                                                                       |
| TA2  | Tên phát khớp ảnh đã ghim                           | R1.1       | Đổi một tên span trong `semconv` → test hợp đồng đỏ                                                                                                                                                                                                                                     |
| TA3  | Mỗi metric khai có nơi phát                         | R1.3       | Thêm một hằng vào `ALL_METRICS` không có lời gọi phát → test AST đỏ                                                                                                                                                                                                                     |
| TA4  | Lịch sử chạy cách ly công ty và bản ghi             | R3.6       | `GET` Bước chạy của lượt chạy công ty B từ A → 404; danh sách `GET /api/v1/runs` không có lượt chạy công ty khác                                                                                                                                                                        |
| TA5  | Che theo quyền đọc trường khi đọc payload           | R3.3       | Người không có quyền đọc `phone` → payload trả dấu `Đã ẩn`; gỡ che → test đỏ                                                                                                                                                                                                            |
| TA6  | Bí mật không vào Lịch sử chạy                       | R3.2       | Input mang một khóa bí mật → preview không có giá trị, `redaction_log` ghi lý do; gỡ bỏ bí mật → test đỏ                                                                                                                                                                                |
| TA7  | Trace id 32 hex xuyên tiến trình                    | R2.2, R2.3 | Request mang `traceparent` → cùng trace id ở span API, span worker, `platform.worker_runs` và dòng outbox; ghi `trace_id` dạng `api-...` → CHECK từ chối                                                                                                                                |
| TA8  | Log chỉ id                                          | R1.5       | Một dòng log mang giá trị dạng email hay query string → `test_logs_carry_ids_only` đỏ                                                                                                                                                                                                   |
| TA9  | Langfuse không nhận user id hay nội dung            | R1.4       | Span processor bỏ `user.id` và `gen_ai.input.messages`; gỡ bỏ → test exporter đỏ                                                                                                                                                                                                        |
| TA10 | Mở payload có ghi Nhật ký kiểm toán                 | R3.5       | Mở payload → đúng một sự kiện `run.payload.viewed`; gỡ ghi audit → test đỏ                                                                                                                                                                                                              |
| TA11 | Lưu giữ không xóa lượt chạy sống hay còn tham chiếu | R5.3, R5.5 | Lượt chạy `waiting_approval` 400 ngày còn nguyên; lượt chạy được `memory.items` trỏ tới → bỏ qua, được đếm; sự kiện vào 31 ngày mà một lượt `queued` còn trỏ tới → bỏ qua, được đếm; sự kiện vào 45 ngày đang bị giữ khi Đóng băng → bỏ qua, metric bỏ qua tăng; gỡ điều kiện → test đỏ |
| TA12 | Payload cần `runs.read_payloads`                    | R4.3       | Thiếu `runs.read_payloads` gọi payload → 403, không trả payload; gỡ kiểm → test đỏ                                                                                                                                                                                                      |
| TA13 | Mỗi kho mới có bộ xóa đăng ký                       | R5.1, R5.2 | Một lớp retention thiếu bộ xóa → test tập bộ xóa đỏ                                                                                                                                                                                                                                     |
| TA14 | Xóa output công cụ không trả UPDATE cho `dw_app`    | R5.7       | Lane chạy qua dòng `tool_executions` 31 ngày → `output` NULL, cột khác giữ nguyên; dòng 29 ngày giữ `output`; `dw_app` UPDATE thẳng → `permission denied`; hàm đặt NULL thêm một cột khác → test đỏ                                                                                     |

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
- workflow-triggers: bảng `studio.inbound_events`, `studio.trigger_deliveries`, `studio.inbound_dedupe`, thời hạn
  của chúng trong tệp chính sách retention và bộ xóa mà lane lưu giữ của lát này chạy, cùng tín hiệu sự kiện đang
  bị giữ khi Đóng băng cho R5.5, đều do
  `.claude/plans/studio/workflow-triggers/issues/02-data-hub-endpoint-va-ingress.md` thêm (workflow-triggers:R6.3,
  workflow-triggers:R6.4, workflow-triggers:R6.7); test của R5.5 trên các bảng đó chạy ở ticket đó
  (workflow-triggers:R1.7, workflow-triggers:R6.8).
- workflow-engine: bộ bọc node phát span và gọi `StepRecorderPort`, `root_run_id` và cửa nhận lượt chạy
  (`.claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md`); trigger trên
  `platform.worker_runs` của workflow-engine:R6.13
  (`.claude/plans/studio/workflow-engine/issues/05-cho-nguoi-va-ghim-phien-ban.md`), mà ticket 02 chờ vì CHECK
  `trace_id` cũng đặt trên bảng đó.
- field-security: hàm quyết quyền đọc trường và dấu `Đã ẩn`, đang viết đợt này — dẫn theo đường dẫn
  (`.claude/plans/studio/field-security/issues/01-mo-hinh-bao-mat-truong.md`); ADR-0106 (Accepted).
- tenant-rbac: quyền `runs.read` trong danh mục quyền một chủ; `runs.read_payloads` đăng ký ở ticket 03 theo quy
  ước của `.claude/plans/studio/tenant-rbac/issues/01-mot-chu-cho-quyen.md`, với cột `tenant_grantable` của
  `.claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md` trong cùng INSERT, nên ticket 03 chờ
  tenant-rbac/02.
- studio-skeleton: schema, điều hướng và sổ `platform.time_partitioned_tables` (studio-skeleton:R3.1)
  (`.claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md`); R3.7 đọc thời hạn
  theo định dạng của R5.6 (studio-skeleton:R3.7); test phủ offboarding và `STUDIO_EXCLUSIONS`
  (studio-skeleton:R4.3).
- usage-and-limits/02: `platform.drop_expired_partitions(cutoffs jsonb)` cho mọi khóa DROP PARTITION và
  `platform.purge_tenant_append_only` cho R5.8 (usage-and-limits:R3.8); ticket 03 chờ nó. Bản tệp retention đầu có
  mục khóa `schema.table` là của ticket đăng ký đầu tiên sau studio-skeleton/01 (usage-and-limits/02), viết theo
  định dạng của R5.6.
- foundations-hardening: `dw_app` không có UPDATE trên `platform.tool_executions` (foundations-hardening:R6.3),
  nên R5.7 đi qua hàm riêng của lane.
- Tệp chính sách retention: các ticket sửa tệp đi thành một chuỗi, mỗi ticket chờ ticket đứng trước:
  studio-skeleton/01 → usage-and-limits/02 → usage-and-limits/03 → ticket 03 của lát này → agent-lifecycle/04 →
  workflow-triggers/02 → compliance-pdpl/04 → agent-builder/04 →
  `.claude/plans/studio/compliance-pdpl/issues/06-lop-luu-giu-du-lieu-ca-nhan.md` với hội thoại và Danh sách chặn
  gửi (DO-52). studio-skeleton/01 đứng đầu chuỗi mà không ra bản nào (dựng hàm tra theo khóa `schema.table`, đọc
  `retention@1.7.0` qua ánh xạ tạm); mỗi ticket sau nó ra đúng một bản mới.
- Kiểm lại khi: hợp đồng `StepRecorderPort` hay bộ bọc node của workflow-engine đổi → R3; hàm quyền đọc
  trường của field-security đổi → R3.3; ADR-0122 (Accepted) bị Đạt bác → toàn lát; workflow-triggers đổi bảng
  sự kiện vào hay cách giữ sự kiện khi Đóng băng → R5.1, R5.5; luật sư đổi số thời hạn → một bản mới của tệp
  chính sách retention, không đổi tiêu chí; usage-and-limits đổi hai hàm của sổ → R5.8, ticket 03; một ticket mới
  sửa tệp chính sách retention, hay chuỗi các ticket sửa tệp đổi thứ tự → mục Phụ thuộc, ticket 03; workflow-engine
  bỏ hay dời trigger trên `platform.worker_runs` → ticket 02.

## Câu hỏi còn mở

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
  (foundations-hardening:R6.3; H:ADR-0122 (Accepted)\~foundations-hardening:R6.3). Sửa: thêm R5.7, TA14, Trong
  phạm vi, Dữ liệu, Phụ thuộc, ticket 03.
- 24/10/2026 (Đạt): offboarding xuất rồi xóa `platform.run_steps`; vì `dw_app` không DELETE, bảng có một dòng
  `STUDIO_EXCLUSIONS` nêu cách xóa, `platform.purge_tenant_append_only` của usage-and-limits/02, theo cách sửa mà
  studio-skeleton:R4.3 nhận (H:ADR-0121 (Accepted)\~usage-and-limits:dữ-liệu). Sửa: thêm R5.8, Dữ liệu, Phụ thuộc,
  ticket 03.
- 24/10/2026 (Đạt): `runs.read_payloads` đăng ký ở ticket 03 theo quy ước của tenant-rbac/01
  (B:agent-lifecycle:phụ-thuộc\~tenant-rbac/01). Sửa: Trong phạm vi, Phụ thuộc, ticket 03.
- 24/10/2026 (agent, tạm): tệp chính sách retention giữ là một tệp có phiên bản
  `configs/policies/retention@<semver>.yaml`, một câu trả lời có số hiệu cho câu hỏi tuân thủ; các ticket sửa tệp đi
  thành một chuỗi theo `Blocked by`, mỗi ticket ra một bản mới, theo thứ tự ở mục Phụ thuộc
  (C:configs:spec\~telemetry-and-audit/03). Sửa: Dữ liệu, Phụ thuộc, ticket 03. Nếu sai thì: tách tệp thành một tệp
  mỗi bảng, sửa R5.6 và ADR-0122 (Accepted) quyết 7.
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

## Danh sách ticket

| #   | Ticket                                                                                                                     |
| --- | -------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Module ánh xạ OTel GenAI ghim commit, không nội dung; metric phát hoặc xóa](issues/01-otel-khong-noi-dung-va-metric.md)   |
| 02  | [Cây span thật và một trace id từ trình duyệt đến worker](issues/02-cay-span-va-mot-trace-id.md)                           |
| 03  | [Lịch sử chạy theo bước: `run_steps` có che và lưu giữ, danh sách run, chi tiết bước](issues/03-lich-su-chay-theo-buoc.md) |
