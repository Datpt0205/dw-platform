# 02 — Hàng đợi việc chung, bàn giao có gói, cổng duyệt theo loại quyết định, ranh giới ở cửa công cụ

Status: resolved
Blocked by: 01, .claude/plans/studio/runtime-hardening/issues/01-toolexecutor-gianh-luot-khong-cua-sau.md
Area: studio
Yêu cầu: R1.4, R1.12, R1.14, R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R3.8, R3.9, R3.10, R3.11, R3.12, R3.13, R3.14, R3.15, R4.1, R4.2, R4.3, R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R6.1, R6.2, R6.3, DWK2, DWK3, DWK8, DWK9, DWK10, DWK11, DWK12, DWK13, DWK14, DWK15, DWK16, DWK22, DWK26, DWK27, DWK28, DWK29, DWK30, DWK31, DWK32, DWK34, DWK35, DWK37, DWK38, DWK39, DWK40

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
11. Theo gate lượt 2 và lượt xác nhận: lane sinh `run_id` trong giao dịch nhận, truyền vào `RunContext.run_id`,
    chỉ nhận việc của DW `operating` có Business Owner (R3.6); việc `in_progress` có `run_id` không dòng lượt chạy 15
    phút sau `updated_at` về `open` giữ `run_id` (R3.14); lỗi bắt đầu khác hạn mức → `failed`, lượt đã tồn tại thì
    không (R3.15); hàm `platform.retire_dw_principal(dw_id)` SECURITY DEFINER gỡ membership của principal khi
    `retired` (R1.14), với khẳng định quyền trong `test_privileges.py`; trigger giữ `payload` chỉ áp cho `dw_app`;
    bộ che `payload.proposal` và `edited_payload` của `dw.decision` theo loại approval, nối ở composition root (R5.6);
    bộ kiểm JSON Schema là mô-đun chung của `dw_kernel` (thay `jsonschema` gọi thẳng ở bước 2).

## Tiêu chí chấp nhận

- [x] R1.4 (DWK2): người tạo giữ `admin.*`, principal giữ `email.send` và `records.read`, `allowed_tools` chỉ cần `email.send` → scope của ngữ cảnh chỉ `email.send`, `requested_by` là actor của lane, `run_as_principal_id` là principal của DW.
- [x] R1.12 (DWK32): DW có việc `waiting_approval` chuyển `retired` → 409 `dw_has_work_in_flight`, trạng thái không đổi.
- [x] R1.14 (DWK32): DW chỉ có việc `open` chuyển `retired` → mọi việc đó `cancelled` cùng giao dịch.
- [x] R3.1: `enqueue` hợp lệ ghi việc `open`, `holder_kind = 'digital_worker'`, `holder_id` và `dw_id` là id DW, `payload_hash` đúng.
- [x] R3.2 (DWK8): kind ngoài `work_kinds` → `work_kind_outside_mandate`, đếm việc không đổi.
- [x] R3.3 (DWK9): payload thiếu trường bắt buộc, và kind không có schema → `payload_invalid`, không dòng nào.
- [x] R3.4 (DWK28): cùng DW cùng `source_key` cùng payload → một dòng, lần hai trả cùng id; khác payload → `source_key_reused`; hai DW cùng `source_key` → hai việc.
- [x] R3.5 (DWK3): danh sách có cả việc người và DW giữ của workspace, không `payload`, không việc của tenant B; kế hoạch dùng index dẫn bằng `tenant_id`.
- [x] R3.6 (DWK10): hai lane song song trên một việc → đúng một lời gọi `DigitalWorkerRunStarter`.
- [x] R3.7 (DWK11): DW `paused` có việc `open` → sau một vòng lane việc vẫn `open`, không lời gọi nào.
- [x] R3.15: runner giả từ chối vì tài liệu không nạp được → việc `failed` với mã, lane không nhận lại.
- [x] R3.8 (DWK12): người không giữ gọi `/complete` → 403 `not_holder`; người giữ gọi trên việc `in_progress` → 409; trạng thái không đổi.
- [x] R3.9 (DWK27): runner giả từ chối vì hạn mức → việc về `open`, `available_at` sau 5 phút, không dòng nào bị xóa; lane không nhận lại trước `available_at`.
- [x] R3.10 (DWK30): Validator gọi `POST /v1/digital-workers/{id}/work-items` → 403 `not_work_assigner`; Work Assigner → 201.
- [x] R3.11 (DWK29): thành viên giữ `dw.read` không là người của DW đọc việc → không `payload`, không `handoff`; Validator đọc → có.
- [x] R3.12 (DWK31): `done→in_progress` → `invalid_transition`; `UPDATE` `payload` của việc dưới `dw_app` → lỗi trigger.
- [x] R3.13: người giữ việc `handed_off` gọi `/complete` → `done`, `closed_at`, audit `work_item.completed`.
- [x] R4.1: bàn giao đổi người giữ, trạng thái `handed_off`, gói lưu đủ, audit `work_item.handed_off` đứng tên principal của DW, một giao dịch.
- [x] R4.2 (DWK13): gói thiếu `recommendation` hay trường 4.001 ký tự → `handoff_packet_invalid`; 4.000 ký tự thì nhận.
- [x] R4.3 (DWK14): người nhận của tenant B → `handoff_target_invalid`, người giữ không đổi.
- [x] R5.1: loại `email.send` ở A2 → lệnh mở approval `dw.decision` với `proposal`, `proposal_schema`, `locked_fields`.
- [x] R5.2: loại `lead.score` ở A3 → `auto` và một dòng audit `dw.decision.auto`.
- [x] R5.3 (DWK15): người giữ `approvals.decide` ngoài Validator và BO quyết → 409 `not_eligible_decider`; đổi Validator rồi Validator cũ quyết → 409; không dòng `approval_decisions`.
- [x] R5.4 (DWK22): `edited_proposal` thiếu `subject` → 422 `proposal_invalid`; đổi `to` khi `to` trong `locked_fields` → 422 `locked_field_changed`; lượt chạy vẫn `waiting_approval`.
- [x] R5.5: duyệt có sửa ghi `edited = true` và `edited_payload`; lượt chạy tiếp nhận `edited_proposal`; từ chối kèm lý do chạy tiếp với `comment`.
- [x] R6.1 (DWK16): lượt chạy của DW `paused` gọi công cụ, và cổng giả của trạng thái ném lỗi → `dw_not_operating`, công cụ không chạy, một dòng từ chối trong `platform.tool_executions`.
- [x] R6.3 (DWK34): thu vai của principal khi lượt đang chờ duyệt, rồi duyệt → `scope_lost`, công cụ không chạy.
- [x] R3.14 (DWK35): việc `in_progress` `run_id` NULL 16 phút → lane trả về `open`; 14 phút → giữ.
- [x] R6.2 (DWK26): lượt chạy DW gọi công cụ cùng scope nhưng ngoài `allowed_tools` → `tool_not_allowed`, công cụ không chạy.
- [x] R1.14 (DWK32): `retired` gỡ membership của principal của DW đó, không chạm membership khác.
- [x] R3.14 (DWK37): việc `in_progress` có `run_id` không dòng lượt chạy 16 phút sau `updated_at` → `open` giữ `run_id`; lần bắt đầu sau cùng `run_id`, `email.send` của lượt đầu đã ghi khóa thì không gửi lần hai.
- [x] R5.6 (DWK38): thành viên giữ `approvals.read` không là người của DW đọc approval `dw.decision` → không `payload.proposal`, không `edited_payload`; Validator đọc → có.
- [x] R4.3 (DWK39): Validator là principal của DW khác → 422; người nhận bàn giao `kind = 'service'` → `handoff_target_invalid`.
- [x] R3.2 (DWK40): `enqueue` cho DW `retired` → `dw_not_accepting_work`, không dòng nào.
- [x] Xong: `make test-unit test-contract test-architecture` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:85-96`; `apps/api/src/dw_api/bootstrap/runtime.py:238-240`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:79`; `apps/worker/src/dw_worker/consumers/__init__.py:22`; `packages/python/dw_platform/src/dw_platform/adapters/persistence/channel_deliveries.py:47`; spec: R1.4, R1.12, R1.14, R3-R6, DWK2, DWK3, DWK8-DWK16, DWK22, DWK26-DWK32.

## Comments

- 2026-10-29 (agent): viết lại theo gate `checking-plan-readiness` lượt 1.
- 2026-10-29 (agent): theo lượt xác nhận của gate: `dw_work_scopes_due` trả cặp `(tenant_id, workspace_id)` và phép nhận đặt cả `app.workspace_id`; `retired` khóa dòng DW `FOR UPDATE`, phép nhận `FOR SHARE`; `ToolExecutor` đọc scope sống (R6.3); lane trả việc kẹt về `open` (R3.14); `run_id` ghi ngay khi runner trả id. MEDIUM để người làm: payload `proposal` của approval `dw.decision` đọc được bởi người xem hộp duyệt của workspace, rộng hơn R3.11; đặt `required_scope` của approval theo quyền duyệt của DW khi làm.
- 2026-10-29 (agent): theo gate lượt 2: lane sinh `run_id` trong giao dịch nhận và truyền vào `RunContext.run_id`; việc kẹt về `open` giữ `run_id` (R3.14, DWK37); lỗi bắt đầu khác hạn mức → `failed` (R3.15); bộ che `payload.proposal` của approval `dw.decision` theo loại, nối ở composition root (R5.6, DWK38); người nhận bàn giao `kind = 'human'` (DWK39); DW `draft` hay `retired` từ chối việc (DWK40); bộ kiểm JSON Schema dùng chung ở `dw_kernel`.
- 2026-10-29 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-10-30 (agent): làm theo bốn pha, mỗi pha một commit: hàng đợi (`6fa3116`), lane `dw_work` (`cb95e1f`), cổng
  duyệt (`0e108d6`), ranh giới ở `ToolExecutor` (`857b317`). Làm khác ticket, có lý do:
  - Bộ kiểm JSON Schema ở `dw_platform.application.json_schema` (`jsonschema==4.26.0` ghim ở `dw_platform`), không ở
    `dw_kernel`: kernel khai `dependencies = []` và hợp đồng import "Kernel is pure (stdlib only)"; runtime (wf-lite)
    đã phụ thuộc platform nên vẫn một chủ. Đo trước khi dùng: 27 µs một lần kiểm, `format: email` có hiệu lực với
    `FORMAT_CHECKER`.
  - R5.3 không đi bằng `admission` truyền theo lời gọi mà bằng sổ `type_admissions` theo loại ở composition root
    (cùng hình `decision_guards`, nhưng async và trong giao dịch của quyết định); `proposal_editors` theo loại giữ
    R5.4. `decide` không có nhánh nào cho `dw.decision`. Nối ở API và ở worker (lệnh duyệt qua chat; không có
    editor ở đó nên bản sửa bị từ chối).
  - R6.1 ghi lần từ chối vào `platform.tool_executions` với trạng thái mới `refused` (migration `f051d26f0610`), không
    khóa chống lặp, không `dispatch_id` (CHECK), cộng một dòng audit `tool.denied`. Lượt chạy có
    `run_as_principal_id` mà executor không có cổng ranh giới, hay cổng không thấy DW, bị từ chối (đóng khi thiếu).
  - `RunContext` thêm `requested_by` và `run_as_principal_id`; dòng lượt chạy ghi cả hai; lượt chạy tiếp hành động
    lại dưới principal (test mới trong `test_approval_flow.py`).
  - `dw_app` giữ DELETE trên `work_items` cho offboarding, cùng lý do ticket 01.
  - Bộ che R5.6 hỏi một lần mỗi trang (`readable(context, requests)`): bản đầu hỏi từng dòng và P95 của
    `GET /approvals` lên 480 ms (đo), sửa còn 54 ms.
  - `approval_decisions.edited_payload` là `JSONB(none_as_null=True)`: JSONB mặc định ghi JSON `null` cho None, CHECK
    mới từ chối mọi quyết định thường (tìm bằng test tích hợp).
  - `RecordingRunStarter` đứng chỗ bộ chạy tới wf-lite/02; chưa việc nào vào được vì chưa gói nào khai schema.
  - Tìm thấy ngoài ticket: `ApproveAndResumeService` của worker (lệnh duyệt qua chat) không nhận `decision_guards`
    của `memory.review` như API; chat chỉ quyết loại có cổng phiên bản chủ thể đăng ký, nên hôm nay không với tới,
    nhưng là cùng hình failure-modes #5. Ghi ở `platform-runtime.md`.
- 2026-10-30 (agent): `reviewing-feature-security`: (1) tenant: `work_items` RLS FORCE một hình workspace, hàm quét
  chỉ trả id, lane đặt tenant và workspace mỗi giao dịch, cổng ranh giới đọc dưới phạm vi của lượt; (2) quyền: người
  giữ, Work Assigner, chủ DW, người quyết đọc trong giao dịch, payload và đề xuất che, test âm mỗi cửa; (3) tự chủ:
  không tầm với mới (bộ chạy chưa chạy gì), cổng về A0 khi thiếu, executor từ chối ngoài ranh giới trước mọi bước;
  (4) nội dung không tin: payload kiểm schema, bản sửa kiểm schema và trường khóa, người nhận bàn giao do mã chọn
  (cổng nhận `to_user` từ bên gọi; wf-lite không được lấy từ đầu ra model); (5) audit: bàn giao, đóng, nhận việc,
  hoãn, lỗi bắt đầu cùng giao dịch với thay đổi, `dw.decision.auto` dưới principal; (6) vòng đời: việc kẹt trả về sau
  15 phút, cache validator giới hạn 256, việc chỉ xóa qua offboarding.
- 2026-10-30 (agent): mutation check `mutations/02.yaml`: 32/32 đỏ, đối chứng xanh. DWK10 có hai rào (SKIP LOCKED và
  UPDATE có điều kiện), mỗi rào một mình đủ nên đột biến phá cả hai.
- 2026-10-30 (agent): độ trễ, app ASGI thật trên PostgreSQL compose, ấm, 200 lần mỗi operation, một tenant 200 thành
  viên, P50/P95/P99 ms: `GET /work-items` (500 việc) 34,1/44,3/56,0; `POST /digital-workers/{id}/work-items`
  63,0/79,9/87,3 (mới, không đối chứng); `GET /approvals` so với `d757245` trên cùng dữ liệu (200 approval thường)
  32,0/43,2/50,1 → 31,5/40,5/46,1; với nửa trang là `dw.decision` 43,6/54,0/60,4: một lần đọc người của DW mỗi trang,
  R5.6 đòi đọc lúc hỏi. Trong ngân sách.
- 2026-10-30 (agent): cổng nhanh xanh: ruff, format, mypy (483 tệp), `make test-unit`, `make test-contract`,
  `make test-architecture`; integration của `dw_platform`, `dw_agent_runtime`, `apps/api`, `apps/worker` xanh.
  `make test-integration` đầy đủ và `/code-review` chờ lúc đóng đợt. Ticket resolved.
