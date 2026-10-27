# 02 — Cây span thật và một trace id từ trình duyệt đến worker

Status: needs-triage
Blocked by: 01, .claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md, .claude/plans/studio/app-standards/issues/03-quy-uoc-api-danh-sach-va-sua.md, .claude/plans/studio/usage-and-limits/issues/03-han-muc-giu-truoc-va-quyet-toan.md, .claude/plans/studio/workflow-engine/issues/05-cho-nguoi-va-ghim-phien-ban.md
Area: studio
Yêu cầu: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, TA7, TA35

## Mục tiêu

Một cây span thật cho lượt chạy (workflow, node, agent, chat, tool, retrieval) và một trace id W3C 32 hex
đi từ trình duyệt qua API, outbox tới worker, thay các tiền tố giả hiện tại (spec R2).

## Việc cần làm

1. Middleware API đọc header `traceparent` bằng `TraceContextTextMapPropagator` (opentelemetry-api 1.44.0
   đã ghim) hoặc mở một trace mới; header sai định dạng W3C, version khác `00`, hay trace id hoặc parent id toàn số 0 thì bỏ
   header và mở trace mới, request vẫn chạy (spec R2.6); `X-Request-ID` thành `dw.request_id` trên span gốc.
2. `RunContext.trace_id` thành 32 ký tự hex thay `api-<hex12>`
   (`apps/api/src/dw_api/bootstrap/container.py:227`), `resume-` và `lookup-`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:302`, `:394`); CHECK
   `trace_id ~ '^[0-9a-f]{32}$'`: trên `platform.worker_runs` thêm `NOT VALID`, ghi lại mọi giá trị cũ không khớp thành
   `md5(trace_id)` rồi `VALIDATE` trong cùng revision (spec R2.5); trên `platform.audit_events` để `NOT VALID`, không sửa
   dòng audit nào, vì bảng chỉ thêm
   (migration trên bảng cha `audit_events` đứng sau migration index theo lượt chạy của app-standards/03; migration
   trên `platform.worker_runs` đứng sau trigger của workflow-engine/05, workflow-engine:R6.13).
3. `platform.outbox_events` thêm cột `trace_parent text` có CHECK định dạng W3C `traceparent`; dispatcher
   worker tiếp trace từ cột đó.
4. Bộ bọc node của workflow-engine mở `invoke_workflow`, `dw.node` (`dw.node_id`, `dw.node_type`,
   `dw.attempt`, `dw.error_policy`, `error.type`) và `invoke_agent`; `chat {model}` mở trước lời gọi trong
   `LimitsMiddleware` và gateway; `retrieval` trong knowledge gateway không có câu hỏi; mỗi span mang
   `dw.run_mode`, `dw.run_manifest_hash`, id công ty và id workspace.
5. Dừng chờ duyệt kết thúc span; resume là một trace mới có span link. Sửa nhánh stream thiếu version
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
