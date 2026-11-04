# 02 — Cây span thật và một trace id từ trình duyệt đến worker

Status: ready-for-agent
Blocked by: 01, .claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md, .claude/plans/studio/app-standards/issues/03-quy-uoc-api-danh-sach-va-sua.md, .claude/plans/studio/usage-and-limits/issues/03-han-muc-giu-truoc-va-quyet-toan.md, .claude/plans/studio/workflow-engine/issues/05-cho-nguoi-va-ghim-phien-ban.md
Area: studio
Yêu cầu: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, R2.7, R2.8, R2.9, TA7, TA35, TA44

## Mục tiêu

Một cây span thật cho lượt chạy (workflow, node, agent, chat, tool, retrieval) và một trace id W3C 32 hex
đi từ trình duyệt qua API, outbox tới worker, thay các tiền tố giả hiện tại (spec R2).

## Việc cần làm

1. Middleware API đọc header `traceparent` bằng `TraceContextTextMapPropagator` (opentelemetry-api 1.44.0
   đã ghim) hoặc mở một trace mới; header sai định dạng W3C, version khác `00`, hay trace id hoặc parent id toàn số 0 thì bỏ
   header và mở trace mới, request vẫn chạy (spec R2.6); `X-Request-ID` khớp `^[A-Za-z0-9-]{1,64}$` thành `dw.request_id` trên span gốc, giá trị khác bị thay bằng id máy chủ sinh. Trace mới
   lấy id từ một bộ sinh ngẫu nhiên 128 bit khác toàn số 0 cả khi không exporter hay SDK nào bật, vì span không ghi của
   API OTel mang trace id toàn số 0 (spec R2.7); `tracestate` và `baggage` của trình duyệt bị bỏ, không vào outbox hay
   lời gọi ra ngoài. Mọi bên ghi `trace_id` ngoài request (lượt `schedule`, sự kiện vào, lane) lấy id từ cùng một bộ sinh
   `new_trace_id()` ở `dw_observability`, không tự chế cách thứ hai.
2. `RunContext.trace_id` thành 32 ký tự hex thay `api-<hex12>`
   (`apps/api/src/dw_api/bootstrap/container.py:227`), `resume-` và `lookup-`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:302`, `:394`); CHECK
   `trace_id ~ '^[0-9a-f]{32}$' AND trace_id <> repeat('0', 32)`: trên `platform.worker_runs` thêm `NOT VALID`, ghi lại mọi giá trị cũ không khớp thành
   `md5(trace_id)` với `updated_at = updated_at` (để mốc lưu giữ của ticket 03 không trôi, spec R5.16) rồi `VALIDATE` trong cùng revision (spec R2.5); trên `platform.audit_events` để `NOT VALID`, không sửa
   dòng audit nào, vì bảng chỉ thêm
   (migration trên bảng cha `audit_events` đứng sau migration index theo lượt chạy của app-standards/03; migration
   trên `platform.worker_runs` đứng sau trigger của workflow-engine/05, workflow-engine:R6.13).
3. `platform.outbox_events` thêm cột `trace_parent text` NULL có CHECK
   `trace_parent ~ '^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$'` và hai id không toàn số 0; NULL cho dòng outbox mà
   lane ghi ngoài mọi request. Dispatcher worker tiếp trace từ cột đó, cột NULL thì mở trace mới; lượt xếp hàng qua
   `platform.worker_runs` (không qua outbox) tiếp `trace_id` của dòng lượt làm ngữ cảnh cha từ xa, nên span worker cùng
   trace id với dòng lượt (spec R2.2).
4. Bộ bọc node của workflow-engine (ticket 03 của nó) là chỗ duy nhất mở `invoke_workflow`, `dw.node` (`dw.node_id`,
   `dw.node_type`, `dw.attempt`, `dw.error_policy`, `error.type`) và `invoke_agent`; ticket này đặt tên, thuộc tính và
   test cây trong mã của bộ bọc, không mở span thứ hai, và gỡ span khỏi adapter chỉ-phát-span của `StepRecorderPort` mà
   workflow-engine/03 nối tạm, nếu ticket này vào trước telemetry-and-audit/03. `error.type` là mã lỗi của bộ bọc khi mã
   đó thuộc tập lỗi đóng của nó (bảng mã `wf.*` và mã kết quả của các cửa, mọi mã đều có khóa trong catalog của ticket 03), còn lại `unknown_error`, cùng mã thay thế của R3.15 nên span, cột và nhãn metric một tập, không bao giờ chuỗi của
   công cụ hay nhà cung cấp (spec R2.9; TA44). Mỗi lời gọi model có đúng một span `chat {model}`: `LimitsMiddleware` mở
   nó trên vòng agent, gateway mở nó trên đường có cấu trúc, và lời gọi gateway nằm dưới `LimitsMiddleware` không mở
   span thứ hai. `retrieval` trong knowledge gateway không có câu hỏi; mỗi span mang `dw.run_mode`, id công ty và id
   workspace, và `dw.run_manifest_hash` khi lượt có bản kê (lượt Studio), vắng khóa đó ở lượt không có. Lượt agent
   không nằm trong quy trình có gốc `invoke_agent`.
5. Dừng chờ duyệt kết thúc span; request tiếp tục mang trace của chính nó (header, hay trace mới) cho span API, audit
   của quyết định, dòng outbox và span worker chạy tiếp, với span link tới trace gốc của lượt; `worker_runs.trace_id`
   giữ trace của request tạo lượt và không đổi, nên vế `platform.worker_runs` của R2.2 nói về request tạo lượt. Sửa nhánh stream thiếu version
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:350-352`).
6. Client web gửi `traceparent`; trường `trace_id` của vỏ lỗi do app-standards/01 dựng (app-standards:R1.2)
   nhận trace id 32 ký tự hex của request; ticket này không dựng lại vỏ (ADR-0108 (Accepted)).

## Tiêu chí chấp nhận

- [ ] R2.1: chạy 3 node → cây span đúng trên exporter bộ nhớ của OTel SDK; span `chat` có thời lượng lớn
      hơn 0; span `retrieval` không mang câu hỏi.
- [ ] R2.2 (TA7): request mang `traceparent` → cùng một trace id ở span API, span worker,
      `platform.worker_runs`, `platform.audit_events` và dòng outbox.
- [ ] R2.3 (TA7): ghi `trace_id` dạng `api-...` → CHECK từ chối; dạng 32 ký tự hex → nhận.
- [ ] R2.6 (TA7): `traceparent` sai định dạng, version `ff` hay trace id toàn số 0 → request 200 với trace id mới 32
      hex, không lệnh ghi nào lỗi; dùng nguyên header hỏng → CHECK làm request lỗi, test đỏ.
- [ ] R2.5 (TA35): dòng `platform.worker_runs` mang `api-<hex12>` trước revision → sau revision `trace_id` là `md5`
      của giá trị cũ, ràng buộc đã `VALIDATE`, UPDATE trạng thái của dòng đó nhận; bỏ bước ghi lại → `VALIDATE` lỗi,
      test đỏ.
- [ ] R2.4: một phản hồi 404 trả `application/problem+json` mang `trace_id` 32 ký tự hex của request.
- [ ] R2.7: không exporter, không SDK, request không header → `trace_id` 32 hex khác toàn số 0 ở vỏ lỗi và dòng lượt;
      ghi `trace_id` toàn số 0 → CHECK từ chối; dòng outbox mang `trace_parent` version `ff` hay parent id toàn số 0 →
      CHECK từ chối; dòng outbox của lane không có request → `trace_parent` NULL, worker mở trace mới.
- [ ] R2.8: lời gọi model qua `LimitsMiddleware` tới gateway → đúng một span `chat`; lời gọi chỉ qua gateway → một
      span; một lượt 3 node → đúng một span `dw.node` mỗi lần thử; mở span ở cả hai chỗ → test đỏ.
- [ ] R2.9 (TA44): lỗi của nhà cung cấp mang `ECONNRESET at 0912345678` → `error.type` của `dw.node` là `unknown_error`; mã
      `wf.*` của bộ bọc → giữ nguyên; đặt nguyên chuỗi lỗi → test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `apps/api/src/dw_api/bootstrap/container.py:227`; spec: R2.3 (trace id `api-` hiện tại).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:302`, `:394`; spec: R2.3.
- ADR-0122 (Accepted) quyết 1.

## Comments

- 2026-10-23 (agent): gộp B10b telemetry-and-audit 02, 03. Chờ bộ bọc node của workflow-engine để đặt span
  `dw.node` và `invoke_agent`.
- 2026-10-23 (agent): theo OPS-b (Đạt, 23/10/2026) chờ app-standards/03 vì cùng sửa `platform.audit_events`;
  chờ usage-and-limits/03 vì span `chat` mở trong `LimitsMiddleware`; trường `trace_id` của vỏ lỗi thuộc
  app-standards/01.
- 2026-10-24 (agent): theo dòng tạm cùng ngày của spec (C:telemetry-and-audit/02\~workflow-engine/05), chờ
  workflow-engine/05 vì ticket đó đặt trigger của workflow-engine:R6.13 trên `platform.worker_runs`, bảng mà bước 2
  thêm CHECK `trace_id`; qua ticket đó, ticket này cũng chờ workflow-engine/04.
- 2026-10-27 (agent): theo lượt `checking-plan-readiness` trên `2c63e01`: CHECK `NOT VALID` vẫn áp lên mọi UPDATE, nên
  `platform.worker_runs` ghi lại `trace_id` cũ rồi `VALIDATE` (spec R2.5, TA35); `platform.audit_events` giữ `NOT VALID`.
- 2026-10-27 (agent): theo lời đáp của Đạt (câu 2 theo A): `traceparent` hỏng thì mở trace mới (spec R2.6; TA7).
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness, builder check và boundary walk (ticket thêm
  revision CHECK và cột outbox); sửa ở spec (Quyết định 4/11/2026, R2.7 tới R2.9, TA44) và bước 1 tới 5: trace id
  ngẫu nhiên khác toàn số 0 cả khi không SDK, một bộ sinh `new_trace_id()` cho mọi bên ghi ngoài request; CHECK
  `trace_parent` chặn version khác `00` và id toàn số 0, NULL cho dòng của lane; lượt xếp hàng tiếp `trace_id` của dòng
  lượt; bộ bọc là chỗ duy nhất mở `dw.node`; một span `chat` mỗi lời gọi; `error.type` thuộc tập đóng hay
  `unknown_error`, cùng mã của R3.15; resume mang trace của request, link tới trace gốc; `X-Request-ID` có định dạng;
  `tracestate`, `baggage` bị bỏ; lần ghi lại `md5` giữ `updated_at`. Lượt xác nhận tìm thêm 4 HIGH (`_OTHER` với
  `unknown_error`, `updated_at`, bộ sinh ngoài request, `X-Request-ID`), đã sửa; không người đọc mới: nhận rủi ro
  (agent, theo ủy quyền 31/10/2026). Nếu sai thì: ghi ở đây khi dựng và sửa spec.
- 2026-11-04 (agent): MEDIUM của gate, chưa sửa. (M1) CHECK `NOT VALID` trên bảng cha phân vùng `platform.audit_events`:
  đo trên PostgreSQL đã ghim trước khi dựa vào (`failure-modes.md` #4); dòng `api-` nằm ở DEFAULT có thể chặn
  `platform.ensure_time_partitions` dời dòng, nên thử một dòng như vậy. (M2) `trace_id` hai bảng vẫn nhận NULL; thêm NOT
  NULL khi mọi bên ghi đã qua `new_trace_id()`. (M3) Trace id do trình duyệt chọn trộn trace giữa công ty ở backend:
  rủi ro Đạt nhận 27/10/2026. (M4) Lời gọi phía máy chủ của Next.js (SSR, server action) gửi `traceparent` hay không: chọn
  khi dựng bước 6. (M5) Nhãn metric `dw_node_failure_total{error_type}` của workflow-engine/03 cần cùng phép thay
  `unknown_error`: cho `checking-plan-consistency`.
- 2026-11-04 (agent): bảng cặp. Ticket 03 không có đường phụ thuộc với ticket này: cùng chạm `platform.worker_runs` (ticket
  này thêm CHECK `trace_id`, ticket 03 thêm hàm xóa và đặt `updated_at` khi xóa trắng) và span `dw.node` (ticket này mở
  trong bộ bọc, ticket 03 thay adapter chỉ-phát-span bằng adapter không mở span); hai revision nối chuỗi Alembic, nên
  không dựng song song, revision sau đổi `down_revision`. Thứ tự dựng: sau workflow-engine/05, usage-and-limits/03 và
  app-standards/03, trước hay sau ticket 03 đều được nếu không cùng lúc.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
