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
(ADR-0122 (Proposed), ADR-0106 (Proposed)). W1 phục vụ YC23, YC80, YC81 và một phần YC82 (ghi `run.payload.viewed`)
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
- R2.4 KHI một phản hồi lỗi `application/problem+json` trả về, API PHẢI đặt `trace_id` của request vào
  thân phản hồi.

### R3 — Kho Lịch sử chạy theo bước, che khi ghi và khi đọc

Người dựng có một kho `platform.run_steps` cho mỗi Bước chạy, che bí mật khi ghi và che theo quyền đọc
trường của người xem khi đọc.

- R3.1 KHI một node, lời gọi model, lời gọi công cụ, phê duyệt hay lượt chạy con kết thúc,
  `StepRecorderPort` PHẢI ghi đúng một Bước chạy mang trạng thái, thời điểm, thời lượng, loại lỗi, token và
  chi phí.
- R3.2 KHI ghi một Bước chạy, `StepRecorderPort` PHẢI bỏ trường bí mật và tham chiếu credential, che trường
  `Nhạy cảm`, và ghi lại từng quyết định che.
- R3.3 KHI một người đọc payload của một Bước chạy, Lịch sử chạy PHẢI che mỗi trường người đó không có
  quyền đọc và trả dấu `Đã ẩn` tại chỗ (ADR-0106 (Proposed) quyết 4).
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

Mỗi kho lát này tạo có một thời hạn và một bộ xóa, và lượt chạy chưa kết thúc hay còn được tham chiếu
không bị xóa (ADR-0122 (Proposed) quyết 7).

- R5.1 ĐỐI VỚI mỗi kho dữ liệu cá nhân mới (`platform.run_steps`, payload đối tượng, cột payload của lượt
  chạy, Sổ sử dụng), `configs/policies/retention@1.8.0.yaml` PHẢI khai một thời hạn và một bộ xóa đã đăng ký.
- R5.2 NẾU một kho dữ liệu cá nhân không có bộ xóa đăng ký, THÌ test tập bộ xóa PHẢI đỏ.
- R5.3 NẾU một lượt chạy chưa kết thúc hay còn được `memory.items` trỏ tới, THÌ lane lưu giữ PHẢI bỏ qua
  nó và vẫn đếm nó.

## Trong phạm vi

- Bảng, cột và phân vùng ở mục Dữ liệu; route ở mục API; màn ở mục Màn hình.
- Mã: `dw_observability.semconv` (tên span, khóa thuộc tính, tên metric GenAI, `GENAI_SEMCONV_COMMIT`);
  `TelemetryPort.record_histogram` với `OtelTelemetry`, `RecordingTelemetry`, `NullTelemetry`; span
  processor Langfuse; formatter log JSON có danh sách trường cho phép; `StepRecorderPort` và adapter ghi
  `platform.run_steps`; đọc Sổ sử dụng cho token và chi phí mỗi Bước chạy;
  `configs/policies/retention@1.8.0.yaml` (lớp run, bước, payload, Sổ sử dụng) và các lane xóa.
- Thêm cột `trace_parent` cho `platform.outbox_events`; CHECK `trace_id` cho `platform.worker_runs` và
  `platform.audit_events`; thêm `run_steps` vào `platform.ensure_time_partitions`.
- Audit: `run.payload.viewed`.

## Ngoài phạm vi

| Việc                                                                                      | Vì sao                                                            | Chủ                               |
| ----------------------------------------------------------------------------------------- | ----------------------------------------------------------------- | --------------------------------- |
| W2: Lọc Nhật ký kiểm toán phía máy chủ, index theo run, danh mục hành động một chủ (YC83) | cần bộ lọc và index; cơ chế của W1 không chặn                     | telemetry-and-audit, đợt sau (W2) |
| W2: Xuất Nhật ký kiểm toán qua tác vụ nền, link hết hạn 7 ngày (YC83)                     | đọc tính năng `audit_export`; chờ danh mục hành động              | telemetry-and-audit, đợt sau (W2) |
| W2: Langfuse chỉ cho Người vận hành, ghim theo digest, lên v4                             | không gửi nội dung thì không cần bản Enterprise                   | telemetry-and-audit, đợt sau (W2) |
| W2: Ghi nội dung theo công ty, giữ ≤ 7 ngày, chỉ công ty đọc                              | cần chính sách `telemetry.content_capture` của tenant-config      | telemetry-and-audit, đợt sau (W2) |
| W3: Collector, lấy mẫu đuôi, bảng Grafana; chuỗi băm chống sửa, đẩy SIEM                  | v1.5 trở đi                                                       | telemetry-and-audit, đợt sau (W3) |
| Bộ bọc node phát span và gọi `StepRecorderPort`                                           | lát này cấp `dw_observability.semconv` và `StepRecorderPort`      | workflow-engine                   |
| Nhận diện dữ liệu cá nhân tiếng Việt ở exporter (Presidio)                                | bộ dò là kiểm soát phụ, có số đo trước khi dựa vào                | compliance-pdpl, đợt sau (W2)     |
| Điểm đánh giá trực tuyến (`gen_ai.evaluation.result`)                                     | dùng sự kiện GenAI nhưng thuộc cổng kiểm định                     | agent-lifecycle                   |
| Sổ sử dụng theo lượt gọi, Bảng giá và hàm phân vùng                                       | lát này đọc token và chi phí từ sổ, không tạo sổ                  | usage-and-limits                  |
| Hàm quyết quyền đọc trường và dấu `Đã ẩn`                                                 | lát này gọi hàm đó khi đọc payload                                | field-security                    |
| Trace thô cho công ty đọc                                                                 | span ở backend không có RLS theo công ty; công ty đọc từ Postgres | không làm                         |

## Dữ liệu

Mọi bảng gắn công ty: RLS ENABLE và FORCE theo công ty, grant cùng migration, tên ràng buộc theo
`NAMING_CONVENTION`, revision id hex ngẫu nhiên.

- `platform.run_steps`: phân vùng theo tháng trên `started_at` với DEFAULT; `PRIMARY KEY (id, started_at)`;
  `kind` CHECK (`node`, `model_call`, `tool_call`, `approval`, `sub_run`); gắn `tenant_id`, `workspace_id`,
  `run_id`, `root_run_id`, `seq int`, `node_id`, `status`, `started_at timestamptz`, `finished_at
timestamptz`, `duration_ms`, `error_type`; `input_preview` và `result_preview` (≤ 4 KB), `input_ref` và
  `result_ref` (đường dẫn đối tượng, NULL khi giữ trong dòng); token, `cost_usd numeric(18,8)`,
  `price_book_version`, `redaction_log jsonb NOT NULL DEFAULT '[]'`, `fls_version`; không cột nội dung thô;
  `dw_app` không UPDATE, DELETE trên cha và mọi phân vùng; vào mảng chỉ-thêm của
  `platform.ensure_time_partitions` cùng ENABLE/FORCE RLS và policy công ty trên cha và DEFAULT; giữ 90
  ngày; index `ix_run_steps_run (tenant_id, run_id, seq)`.
- `platform.outbox_events`: thêm `trace_parent text` CHECK định dạng W3C `traceparent`; dispatcher worker
  tiếp trace từ cột đó.
- `platform.worker_runs`, `platform.audit_events`: CHECK `trace_id ~ '^[0-9a-f]{32}$'` dạng `NOT VALID`.
- `configs/policies/retention@1.8.0.yaml` thay `1.7.0`: `run_steps` 90 ngày (DROP PARTITION), payload đối
  tượng 30 ngày (lane xóa đối tượng), cột payload lượt chạy 90 ngày sau kết thúc (lane xóa), lượt chạy 395
  ngày sau kết thúc bỏ qua dòng `memory.items` trỏ tới (lane xóa).

## API

- `GET /api/v1/runs?artifact_kind&artifact_id&status&trigger_kind&from&to&cursor&limit` (`runs.read`, RLS
  và workspace theo độ sâu): danh sách lượt chạy, phân trang keyset.
- `GET /api/v1/runs/{run_id}/steps` (`runs.read`): các Bước chạy theo `seq`.
- `GET /api/v1/runs/{run_id}/steps/{step_id}/payload?part=in|out` (`runs.read_payloads`): payload che theo
  quyền đọc trường của người xem; audit `run.payload.viewed` trong cùng giao dịch.
- Lỗi theo vỏ `application/problem+json` của ADR-0108 (Proposed), mang `trace_id`; `details.reason_code`
  cho 404 cách ly.

## Màn hình

- Màn `/runs` (antd Table: thời điểm, agent hoặc quy trình, trạng thái, nguồn kích hoạt, thời lượng, chi
  phí; bộ lọc theo `artifact`, trạng thái, nguồn kích hoạt, khoảng thời gian), đọc `GET /api/v1/runs`.
- Màn `/runs/[id]` (antd: Steps cho các Bước chạy, Descriptions, xem JSON có dấu `Đã ẩn`, token và chi phí
  mỗi Bước chạy, nút "Sao chép trace id").

## Kiểm soát

| #    | Kiểm soát                                           | Yêu cầu    | Test âm                                                                                                                                                           |
| ---- | --------------------------------------------------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TA1  | Span, log, audit không mang nội dung                | R1.2       | Input có số điện thoại → không span, log hay sự kiện Nhật ký kiểm toán nào chứa giá trị đó; bật Ghi nội dung cho công ty A không làm span công ty B mang nội dung |
| TA2  | Tên phát khớp ảnh đã ghim                           | R1.1       | Đổi một tên span trong `semconv` → test hợp đồng đỏ                                                                                                               |
| TA3  | Mỗi metric khai có nơi phát                         | R1.3       | Thêm một hằng vào `ALL_METRICS` không có lời gọi phát → test AST đỏ                                                                                               |
| TA4  | Lịch sử chạy cách ly công ty và bản ghi             | R3.6       | `GET` Bước chạy của lượt chạy công ty B từ A → 404; danh sách `GET /api/v1/runs` không có lượt chạy công ty khác                                                  |
| TA5  | Che theo quyền đọc trường khi đọc payload           | R3.3       | Người không có quyền đọc `phone` → payload trả dấu `Đã ẩn`; gỡ che → test đỏ                                                                                      |
| TA6  | Bí mật không vào Lịch sử chạy                       | R3.2       | Input mang một khóa bí mật → preview không có giá trị, `redaction_log` ghi lý do; gỡ bỏ bí mật → test đỏ                                                          |
| TA7  | Trace id 32 hex xuyên tiến trình                    | R2.2, R2.3 | Request mang `traceparent` → cùng trace id ở span API, span worker, `platform.worker_runs` và dòng outbox; ghi `trace_id` dạng `api-...` → CHECK từ chối          |
| TA8  | Log chỉ id                                          | R1.5       | Một dòng log mang giá trị dạng email hay query string → `test_logs_carry_ids_only` đỏ                                                                             |
| TA9  | Langfuse không nhận user id hay nội dung            | R1.4       | Span processor bỏ `user.id` và `gen_ai.input.messages`; gỡ bỏ → test exporter đỏ                                                                                  |
| TA10 | Mở payload có ghi Nhật ký kiểm toán                 | R3.5       | Mở payload → đúng một sự kiện `run.payload.viewed`; gỡ ghi audit → test đỏ                                                                                        |
| TA11 | Lưu giữ không xóa lượt chạy sống hay còn tham chiếu | R5.3       | Lượt chạy `waiting_approval` 400 ngày còn nguyên; lượt chạy được `memory.items` trỏ tới → bỏ qua, được đếm                                                        |
| TA12 | Payload cần `runs.read_payloads`                    | R4.3       | Thiếu `runs.read_payloads` gọi payload → 403, không trả payload; gỡ kiểm → test đỏ                                                                                |
| TA13 | Mỗi kho mới có bộ xóa đăng ký                       | R5.1, R5.2 | Một lớp retention thiếu bộ xóa → test tập bộ xóa đỏ                                                                                                               |

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (ghi ở Comments của ticket).
- `make ci && make test-integration` xanh; `reviewing-feature-security` và `reviewing-deployment-security`
  đã chạy trên từng ticket có route, migration hay lane; `.claude/plans/studio.md` ghi lát W1 đã xong.

## Phụ thuộc

- usage-and-limits: hàm phân vùng `platform.ensure_time_partitions` và Sổ sử dụng theo lượt gọi, định giá
  theo ADR-0121 (Proposed)
  (`.claude/plans/studio/usage-and-limits/issues/02-bang-gia-so-su-dung-va-man-hinh.md`).
- workflow-engine: bộ bọc node phát span và gọi `StepRecorderPort`, `root_run_id` và cửa nhận lượt chạy
  (`.claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md`).
- field-security: hàm quyết quyền đọc trường và dấu `Đã ẩn`, đang viết đợt này — dẫn theo đường dẫn
  (`.claude/plans/studio/field-security/issues/01-mo-hinh-bao-mat-truong.md`); ADR-0106 (Proposed).
- tenant-rbac: quyền `runs.read`, `runs.read_payloads` trong danh mục quyền một chủ
  (`.claude/plans/studio/tenant-rbac/issues/01-mot-chu-cho-quyen.md`).
- studio-skeleton: schema và điều hướng
  (`.claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md`).
- `configs/policies/retention@1.8.0.yaml` đồng sở hữu với compliance-pdpl: lát này giữ lớp run, Bước chạy,
  payload và Sổ sử dụng; compliance-pdpl thêm lớp Bản ghi đồng ý, nhật ký gửi và sự cố
  (`.claude/plans/studio/compliance-pdpl/issues/06-lop-luu-giu-du-lieu-ca-nhan.md`).
- Kiểm lại khi: hợp đồng `StepRecorderPort` hay bộ bọc node của workflow-engine đổi → R3; hàm quyền đọc
  trường của field-security đổi → R3.3; ADR-0122 (Proposed) bị Đạt bác → toàn lát.

## Câu hỏi còn mở

- Q1. Thời hạn lưu cho lượt chạy kết thúc, Bước chạy và payload là bao nhiêu, theo PDPL và Nghị định 356?
  Chủ: Đạt và luật sư. Chặn: R5.1, ticket 03 (DO-52).

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
  dung, không đọc từ trace (ADR-0122 (Proposed)) — quan sát học được, không phải mã của họ. Sửa: R1, R3.

## Danh sách ticket

| #   | Ticket                                                                                                                     |
| --- | -------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Module ánh xạ OTel GenAI ghim commit, không nội dung; metric phát hoặc xóa](issues/01-otel-khong-noi-dung-va-metric.md)   |
| 02  | [Cây span thật và một trace id từ trình duyệt đến worker](issues/02-cay-span-va-mot-trace-id.md)                           |
| 03  | [Lịch sử chạy theo bước: `run_steps` có che và lưu giữ, danh sách run, chi tiết bước](issues/03-lich-su-chay-theo-buoc.md) |
