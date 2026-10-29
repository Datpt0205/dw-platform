# 02 — Hàng đợi việc chung, bàn giao có gói, cổng duyệt theo loại quyết định, dừng ở cửa công cụ

Status: needs-triage
Blocked by: 01, .claude/plans/studio/runtime-hardening/issues/01-toolexecutor-gianh-luot-khong-cua-sau.md
Area: studio
Yêu cầu: R1.4, R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R3.8, R4.1, R4.2, R4.3, R5.1, R5.2, R5.3, R5.4, R5.5, R6.1, DWK2, DWK3, DWK8, DWK9, DWK10, DWK11, DWK12, DWK13, DWK14, DWK15, DWK16, DWK22

## Mục tiêu

Người và DW làm trên một hàng đợi; lane của worker nhận việc của DW đúng một lần và chạy nó dưới
danh nghĩa DW; DW bàn giao có gói; một đề xuất trên mức hiệu lực chờ Validator qua cửa phê duyệt có
sẵn; DW không `operating` không gây hiệu ứng (R1.4, R3-R6, ADR-0128 (Proposed) quyết 6-8, 10).

## Việc cần làm

1. Migration mới: `platform.work_items` đúng mục Dữ liệu của spec (gồm `wake_at` và CHECK của nó,
   index keyset dẫn bằng `tenant_id`, index một phần cho lane và cho `wake_at`), RLS một hình,
   quyền `dw_app` SELECT, INSERT, UPDATE.
2. `dw_platform/application/work_queue.py`: `WorkQueue` (`enqueue`, `hand_off`, `complete`,
   `list`, `get`, `claim_next_for_lane`) và Protocol `WorkKindSchemas` (do bên dùng khai; ticket này
   cấp một bản trong bộ nhớ cho test, wf-lite/01 cấp bản đọc gói), lỗi có mã
   `work_kind_outside_mandate`, `payload_invalid`, `handoff_packet_invalid`, `handoff_target_invalid`,
   `not_holder`; `enqueue` trùng `(tenant_id, kind, source_key)` trả việc đã có (`ON CONFLICT DO
NOTHING` rồi đọc lại); kiểm JSON Schema bằng `jsonschema` đã ghim.
3. `dw_platform/application/decision_gate.py`: `DecisionGate.check(dw_id, decision_class, proposal)`
   trả `auto` (và ghi audit `dw.decision.auto` đứng tên DW) hay lệnh mở approval `dw.decision` với
   payload `{approval_type, reason, required_scope: null, dw_id, decision_class, effective_level,
proposal, eligible_deciders}`, `eligible_deciders` đọc từ hồ sơ DW lúc gọi.
4. Guard `dw.decision` ở `apps/api/src/dw_api/bootstrap/runtime.py` (`decision_guards`): người quyết
   phải có trong `request.payload["eligible_deciders"]`, không thì `ConflictError` mã
   `not_eligible_decider`; mọi composition root dựng `ApproveAndResumeService` nhận cùng guard.
5. `dw_agent_runtime/digital_worker_context.py`: `run_context_for(dw, work_item, tools)` với `actor_id`
   là id DW, scope là hợp `required_scopes` của `allowed_tools` (R1.4).
6. Lane `dw_work` ở `apps/worker/src/dw_worker/consumers/dw_work.py`, đăng ký bằng
   `ConsumerRegistry.register` ở `apps/worker/src/dw_worker/main.py`: mỗi vòng `claim_next_for_lane`
   (`FOR UPDATE SKIP LOCKED`, chỉ việc `open` của DW `operating`), chuyển `in_progress`, ghi `run_id`,
   rồi gọi `DigitalWorkerRunStarter` (Protocol do lane khai; ticket này nối một bản ghi lời gọi, wf-lite/02
   nối bản chạy graph). Lane cắt ngang tenant theo `CLAUDE.md` "lane audit" và `tenant_wide_scope` không
   dùng: lane đọc qua hàm SECURITY DEFINER `platform.claim_dw_work(limit)` trả `(tenant_id, item_id)` rồi
   đặt ngữ cảnh từng tenant.
7. `ToolExecutor`: trước khi gọi công cụ, hỏi `PrincipalStatePort.is_operating(actor_id)` khi
   `actor_id` là id một DW; sai thì từ chối `dw_not_operating` và ghi lần từ chối vào
   `platform.tool_executions` (R6.1); port do runtime khai, platform cấp.
8. Route `apps/api/src/dw_api/routes/v1/work_items.py`: `GET /v1/work-items` (lọc `status`,
   `holder_kind`, keyset `(created_at, id)`), `GET /v1/work-items/{id}`,
   `POST /v1/work-items/{id}/complete`; kiểm hình kế hoạch của danh sách vào bộ kiểm của
   app-standards/03.
9. `POST /v1/approvals/{id}/decision` nhận `edited_proposal` tùy chọn cho loại `dw.decision`: kiểm theo `payload.proposal_schema` (cổng ghi schema đầu ra của bước đề xuất) trước khi gọi `decide`, sai thì 422 `proposal_invalid`; migration thêm `platform.approval_decisions.edited boolean NOT NULL DEFAULT false` và `edited_payload jsonb NULL`; `resume_payload` mang `edited_proposal` (R5.4, R5.5, D18).
10. Test âm DWK2, DWK3 (việc), DWK8-DWK16, DWK22.

## Tiêu chí chấp nhận

- [ ] R1.4 (DWK2): ngữ cảnh lượt chạy lane dựng có `actor_id` là id DW và đúng scope của công cụ, không scope của người tạo `admin.*`.
- [ ] R3.1: `enqueue` hợp lệ ghi việc `open`, `holder_kind = 'digital_worker'`, `holder_id` là id DW.
- [ ] R3.2 (DWK8): kind ngoài `work_kinds` → `work_kind_outside_mandate`, đếm việc không đổi.
- [ ] R3.3 (DWK9): payload thiếu trường bắt buộc, và kind không có schema → `payload_invalid`, không dòng nào.
- [ ] R3.4: cùng `source_key` hai lần → một dòng, lần hai trả cùng id.
- [ ] R3.5 (DWK3): danh sách có cả việc người và DW giữ của workspace, không việc của tenant B; kế hoạch dùng index dẫn bằng `tenant_id`.
- [ ] R3.6 (DWK10): hai lane song song trên một việc → đúng một lời gọi `DigitalWorkerRunStarter`, `run_id` một giá trị.
- [ ] R3.7 (DWK11): DW `paused` có việc `open` → sau một vòng lane việc vẫn `open`, không lời gọi nào.
- [ ] R3.8 (DWK12): người không giữ gọi `/complete` → 403 `not_holder`, trạng thái không đổi.
- [ ] R4.1: bàn giao đổi người giữ, trạng thái `handed_off`, gói lưu đủ, audit `work_item.handed_off` đứng tên DW, một giao dịch.
- [ ] R4.2 (DWK13): gói thiếu `recommendation` hay trường 4.001 ký tự → `handoff_packet_invalid`; 4.000 ký tự thì nhận.
- [ ] R4.3 (DWK14): người nhận của tenant B → `handoff_target_invalid`, người giữ không đổi.
- [ ] R5.1: loại `email.send` ở A2 → lệnh mở approval `dw.decision` có `eligible_deciders` là Validator và Business Owner.
- [ ] R5.2: loại `lead.score` ở A3 → `auto` và một dòng audit `dw.decision.auto`.
- [ ] R5.3 (DWK15): người giữ `approvals.decide` ngoài `eligible_deciders` quyết → 409 `not_eligible_decider`, không dòng `approval_decisions`.
- [ ] R5.4 (DWK22): `edited_proposal` thiếu `subject` → 422 `proposal_invalid`, không dòng quyết định, lượt chạy vẫn `waiting_approval`.
- [ ] R5.5: duyệt có sửa ghi `edited = true` và `edited_payload`; lượt chạy tiếp nhận `edited_proposal`; từ chối kèm lý do chạy tiếp với `comment`.
- [ ] R6.1 (DWK16): lượt chạy của DW `paused` gọi công cụ qua `ToolExecutor` → `dw_not_operating`, công cụ không chạy, một dòng từ chối trong `platform.tool_executions`.
- [ ] Xong: `make test-unit test-contract test-architecture` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:85-96`; `apps/api/src/dw_api/bootstrap/runtime.py:238-240`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:79`; `apps/worker/src/dw_worker/consumers/__init__.py:22`; spec: R1.4, R3-R6, DWK2, DWK3, DWK8-DWK16, DWK22.

## Comments
