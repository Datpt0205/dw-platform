# 02 — Hàng đợi việc chung, bàn giao có gói, cổng duyệt theo loại quyết định, ranh giới ở cửa công cụ

Status: needs-triage
Blocked by: 01, .claude/plans/studio/runtime-hardening/issues/01-toolexecutor-gianh-luot-khong-cua-sau.md
Area: studio
Yêu cầu: R1.4, R1.12, R1.14, R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R3.8, R3.9, R3.10, R3.11, R3.12, R3.13, R3.14, R4.1, R4.2, R4.3, R5.1, R5.2, R5.3, R5.4, R5.5, R6.1, R6.2, R6.3, DWK2, DWK3, DWK8, DWK9, DWK10, DWK11, DWK12, DWK13, DWK14, DWK15, DWK16, DWK22, DWK26, DWK27, DWK28, DWK29, DWK30, DWK31, DWK32, DWK34, DWK35

## Mục tiêu

Người và DW làm trên một hàng đợi; lane của worker nhận việc của DW đúng một lần và chạy nó dưới service
principal của DW, đứng tên lane; DW bàn giao có gói; một đề xuất trên mức hiệu lực chờ Validator qua
cửa phê duyệt có sẵn; `ToolExecutor` giữ ranh giới của DW (R1.4, R1.12, R1.14, R3-R6, ADR-0128 (Proposed)
quyết 6-8, 10).

## Việc cần làm

1. Migration mới: `platform.work_items` đúng mục Dữ liệu của spec (gồm `payload_hash`, `available_at`,
   `wake_at` và CHECK của nó, trigger giữ `payload` không đổi, index keyset dẫn bằng `tenant_id`, index
   một phần cho lane và cho `wake_at`), RLS một hình, quyền `dw_app` SELECT, INSERT, UPDATE; hàm
   `platform.dw_work_scopes_due(limit)` SECURITY DEFINER trả id tenant, `EXECUTE` chỉ cho `dw_app`;
   `platform.worker_runs.run_as_principal_id`; `platform.approval_decisions.edited` và `edited_payload`.
2. `dw_platform/application/work_queue.py`: `WorkQueue` (`enqueue`, `hand_off`, `complete`, `list`,
   `get`, `claim_for_lane`, `release_for_limit`, `record_wait`, `resume_claimed`, `finish`) và Protocol
   `WorkKindSchemas` (do bên dùng khai; ticket này cấp một bản trong bộ nhớ cho test, wf-lite/01 cấp
   bản đọc gói); mọi đổi trạng thái đi qua một bảng chuyển (R3.12); lỗi có mã
   `work_kind_outside_mandate`, `payload_invalid`, `source_key_reused`, `handoff_packet_invalid`,
   `handoff_target_invalid`, `not_holder`, `invalid_transition`; kiểm JSON Schema bằng `jsonschema` đã ghim.
3. `dw_platform/application/decision_gate.py`: `DecisionGate.check(dw_id, decision_class, proposal,
proposal_schema, locked_fields)` trả `auto` (và audit `dw.decision.auto` đứng tên principal của DW)
   hay lệnh mở approval `dw.decision` với payload `{approval_type, reason, dw_id, decision_class,
effective_level, proposal, proposal_schema, locked_fields}`.
4. Kiểm `dw.decision` lúc quyết: một `DecisionAdmission` đọc Validator và Business Owner hiện tại của DW
   trong giao dịch của quyết định (R5.3), nối ở mọi composition root dựng `ApproveAndResumeService`;
   route `POST /v1/approvals/{id}/decision` nhận `edited_proposal` tùy chọn cho loại `dw.decision`, kiểm
   theo `payload.proposal_schema` và `locked_fields` trước khi gọi `decide` (R5.4); `resume_payload` mang
   `edited_proposal`; dòng quyết định ghi `edited` và `edited_payload` (R5.5).
5. `dw_agent_runtime/digital_worker_context.py`: `run_context_for(dw, work_item, membership_scopes,
tool_scopes)` theo R1.4 (`requested_by` là `system_actor('dw_work')`, `run_as_principal_id` và
   `actor_id` là principal của DW, scope là giao của hai tập).
6. Lane `dw_work` ở `apps/worker/src/dw_worker/consumers/dw_work.py`, đăng ký bằng
   `ConsumerRegistry.register` ở `apps/worker/src/dw_worker/main.py`: `dw_work_scopes_due` rồi nhận
   theo từng tenant dưới `app.tenant_id` (`FOR UPDATE SKIP LOCKED`, chỉ việc `open` có `available_at <=
now()` của DW `operating`), chuyển `in_progress`, rồi gọi `DigitalWorkerRunStarter` (Protocol do lane
   khai; ticket này nối một bản ghi lời gọi, wf-lite/02 nối bản chạy graph); runner từ chối vì hạn mức
   thì `release_for_limit` (R3.9).
7. `ToolExecutor`: khi `run_as_principal_id` là principal của một DW, hỏi `DigitalWorkerBoundaryPort`
   (runtime khai, platform cấp) trạng thái và `allowed_tools` của DW; không `operating`, đọc lỗi, hay
   công cụ ngoài `allowed_tools` thì từ chối `dw_not_operating` hay `tool_not_allowed` và ghi lần từ chối
   vào `platform.tool_executions` (R6).
8. Route `apps/api/src/dw_api/routes/v1/work_items.py`: `GET /v1/work-items` (lọc `status`,
   `holder_kind`, keyset `(created_at, id)`, không `payload`), `GET /v1/work-items/{id}` (payload theo
   R3.11), `POST /v1/work-items/{id}/complete`; `POST /v1/digital-workers/{id}/work-items` (Work
   Assigner); `retired` ở `/state` theo R1.12, R1.14; kiểm hình kế hoạch của danh sách vào bộ kiểm của
   app-standards/03.
9. Đo P50/P95/P99 của `GET /v1/work-items` và `POST .../work-items` (ticket đổi cách truy cập DB, `latency.md`).
10. Test âm DWK2, DWK3 (việc), DWK8-DWK16, DWK22, DWK26-DWK32.

## Tiêu chí chấp nhận

- [ ] R1.4 (DWK2): người tạo giữ `admin.*`, principal giữ `email.send` và `records.read`, `allowed_tools` chỉ cần `email.send` → scope của ngữ cảnh chỉ `email.send`, `requested_by` là actor của lane, `run_as_principal_id` là principal của DW.
- [ ] R1.12 (DWK32): DW có việc `waiting_approval` chuyển `retired` → 409 `dw_has_work_in_flight`, trạng thái không đổi.
- [ ] R1.14 (DWK32): DW chỉ có việc `open` chuyển `retired` → mọi việc đó `cancelled` cùng giao dịch.
- [ ] R3.1: `enqueue` hợp lệ ghi việc `open`, `holder_kind = 'digital_worker'`, `holder_id` và `dw_id` là id DW, `payload_hash` đúng.
- [ ] R3.2 (DWK8): kind ngoài `work_kinds` → `work_kind_outside_mandate`, đếm việc không đổi.
- [ ] R3.3 (DWK9): payload thiếu trường bắt buộc, và kind không có schema → `payload_invalid`, không dòng nào.
- [ ] R3.4 (DWK28): cùng DW cùng `source_key` cùng payload → một dòng, lần hai trả cùng id; khác payload → `source_key_reused`; hai DW cùng `source_key` → hai việc.
- [ ] R3.5 (DWK3): danh sách có cả việc người và DW giữ của workspace, không `payload`, không việc của tenant B; kế hoạch dùng index dẫn bằng `tenant_id`.
- [ ] R3.6 (DWK10): hai lane song song trên một việc → đúng một lời gọi `DigitalWorkerRunStarter`.
- [ ] R3.7 (DWK11): DW `paused` có việc `open` → sau một vòng lane việc vẫn `open`, không lời gọi nào.
- [ ] R3.8 (DWK12): người không giữ gọi `/complete` → 403 `not_holder`; người giữ gọi trên việc `in_progress` → 409; trạng thái không đổi.
- [ ] R3.9 (DWK27): runner giả từ chối vì hạn mức → việc về `open`, `available_at` sau 5 phút, không dòng nào bị xóa; lane không nhận lại trước `available_at`.
- [ ] R3.10 (DWK30): Validator gọi `POST /v1/digital-workers/{id}/work-items` → 403 `not_work_assigner`; Work Assigner → 201.
- [ ] R3.11 (DWK29): thành viên giữ `dw.read` không là người của DW đọc việc → không `payload`, không `handoff`; Validator đọc → có.
- [ ] R3.12 (DWK31): `done→in_progress` → `invalid_transition`; `UPDATE` `payload` của việc dưới `dw_app` → lỗi trigger.
- [ ] R3.13: người giữ việc `handed_off` gọi `/complete` → `done`, `closed_at`, audit `work_item.completed`.
- [ ] R4.1: bàn giao đổi người giữ, trạng thái `handed_off`, gói lưu đủ, audit `work_item.handed_off` đứng tên principal của DW, một giao dịch.
- [ ] R4.2 (DWK13): gói thiếu `recommendation` hay trường 4.001 ký tự → `handoff_packet_invalid`; 4.000 ký tự thì nhận.
- [ ] R4.3 (DWK14): người nhận của tenant B → `handoff_target_invalid`, người giữ không đổi.
- [ ] R5.1: loại `email.send` ở A2 → lệnh mở approval `dw.decision` với `proposal`, `proposal_schema`, `locked_fields`.
- [ ] R5.2: loại `lead.score` ở A3 → `auto` và một dòng audit `dw.decision.auto`.
- [ ] R5.3 (DWK15): người giữ `approvals.decide` ngoài Validator và BO quyết → 409 `not_eligible_decider`; đổi Validator rồi Validator cũ quyết → 409; không dòng `approval_decisions`.
- [ ] R5.4 (DWK22): `edited_proposal` thiếu `subject` → 422 `proposal_invalid`; đổi `to` khi `to` trong `locked_fields` → 422 `locked_field_changed`; lượt chạy vẫn `waiting_approval`.
- [ ] R5.5: duyệt có sửa ghi `edited = true` và `edited_payload`; lượt chạy tiếp nhận `edited_proposal`; từ chối kèm lý do chạy tiếp với `comment`.
- [ ] R6.1 (DWK16): lượt chạy của DW `paused` gọi công cụ, và cổng giả của trạng thái ném lỗi → `dw_not_operating`, công cụ không chạy, một dòng từ chối trong `platform.tool_executions`.
- [ ] R6.3 (DWK34): thu vai của principal khi lượt đang chờ duyệt, rồi duyệt → `scope_lost`, công cụ không chạy.
- [ ] R3.14 (DWK35): việc `in_progress` `run_id` NULL 16 phút → lane trả về `open`; 14 phút → giữ.
- [ ] R6.2 (DWK26): lượt chạy DW gọi công cụ cùng scope nhưng ngoài `allowed_tools` → `tool_not_allowed`, công cụ không chạy.
- [ ] Xong: `make test-unit test-contract test-architecture` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:85-96`; `apps/api/src/dw_api/bootstrap/runtime.py:238-240`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:79`; `apps/worker/src/dw_worker/consumers/__init__.py:22`; `packages/python/dw_platform/src/dw_platform/adapters/persistence/channel_deliveries.py:47`; spec: R1.4, R1.12, R1.14, R3-R6, DWK2, DWK3, DWK8-DWK16, DWK22, DWK26-DWK32.

## Comments

- 2026-10-29 (agent): viết lại theo gate `checking-plan-readiness` lượt 1.
- 2026-10-29 (agent): theo lượt xác nhận của gate: `dw_work_scopes_due` trả cặp `(tenant_id, workspace_id)` và phép nhận đặt cả `app.workspace_id`; `retired` khóa dòng DW `FOR UPDATE`, phép nhận `FOR SHARE`; `ToolExecutor` đọc scope sống (R6.3); lane trả việc kẹt về `open` (R3.14); `run_id` ghi ngay khi runner trả id. MEDIUM để người làm: payload `proposal` của approval `dw.decision` đọc được bởi người xem hộp duyệt của workspace, rộng hơn R3.11; đặt `required_scope` của approval theo quyền duyệt của DW khi làm.
