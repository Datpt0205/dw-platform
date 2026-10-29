# Digital Worker: hồ sơ, loại quyết định, hàng đợi chung, bàn giao, scorecard

Status: needs-triage
Area: studio · Nhánh: `main` · Viết: 29/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Khách mua một Digital Worker (DW) theo chuẩn CASANOS chứ không mua một trợ lý chat (D15): một tài sản của công ty giữ một việc lặp lại, có định danh, mandate, bốn người chịu trách nhiệm và mức tự chủ kiếm được theo từng loại quyết định, làm trên một hàng đợi chung với người. Spec này là lõi DW của nền tảng theo đường C của D17 (YC118-YC123) và ADR-0128 (Proposed); bộ máy chạy quy trình là spec `wf-lite`, DW đầu tiên là spec `leadcare`.

## Hiện trạng (đã kiểm ở `8508502` ngày 29/10/2026)

- Định nghĩa worker là tệp YAML của context, có `autonomy_level` A0-A4 (`packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:50-82`), và `configs/workers` rỗng vì worker là của context (`configs/workers/README.md:19-21`). Thiếu: DW là dữ liệu của tenant, có chủ và trạng thái.
- Năm mức tự chủ chỉ có một danh sách, trong kernel (`packages/python/dw_kernel/src/dw_kernel/autonomy.py:17`). Ràng buộc: không thêm A5 (ADR-0128 (Proposed) quyết 4).
- Thang quyết định cần người hay không theo mức và bậc hiệu ứng (`packages/python/dw_agent_runtime/src/dw_agent_runtime/autonomy.py:71-85`), hàm `requires_approval` nhận một `ToolDefinition` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/autonomy.py:123-133`). Ràng buộc: cổng theo loại quyết định dùng cùng thang này, không bảng thứ hai.
- Trần tự chủ của tenant là `platform.tenants.max_autonomy_level` (`db/migrations/versions/0006_autonomy.py:51`), đọc ở bảng điều khiển quản trị (`packages/python/dw_platform/src/dw_platform/adapters/persistence/admin_console_repo.py:252`). Ràng buộc: là một trong ba số của mức hiệu lực.
- Lượt chạy ghi `requested_by` không có khóa ngoại tới `platform.users` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/runtime_tables.py:38`), approval cũng vậy (`packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:224`). Ràng buộc: id của DW đứng tên được mà không cần dòng user.
- Không có tài khoản dịch vụ; ADR-0103 (Accepted) quyết 2 định hình service principal là một dòng `platform.users` `kind = 'service'` cộng `platform.service_principals`, quyết 4 cho lượt chạy không người đứng tên lane và chạy dưới principal đó (`docs/adr/0103-runs-act-as-a-principal-within-a-boundary.md:52-77`), và org-and-principals/03 sẽ dựng đầy đủ (`.claude/plans/studio/org-and-principals/spec.md:31`). Ràng buộc: định danh DW lát đầu là phần tối thiểu của hình đó (D17).
- `ApproveAndResumeService` nhận `decision_guards` theo loại approval và `strict_approval_prefixes` ở composition root (`apps/api/src/dw_api/bootstrap/runtime.py:238-240`), approval không gắn lượt chạy phát một sự kiện outbox `<type>.decided` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:304-305`). Ràng buộc: cổng DW và nâng tự chủ đi qua cửa này.
- Scope của membership là hợp scope của vai trong `platform.roles` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:34-48`). Ràng buộc: `dw.read`, `dw.manage` thêm vào vai bằng migration.
- Offboarding tìm bảng tenant qua catalog, không qua danh sách viết tay (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:193-207`). Ràng buộc: bảng mới có `tenant_id` được xuất và xóa, thứ tự xóa theo khóa ngoại.
- Sổ sử dụng theo lượt gọi đã bị gỡ (`db/migrations/versions/0013_drop_model_usage_ledger.py:1`); chi phí chỉ còn ở telemetry (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/usage_recorders.py:1-8`). Thiếu: scorecard cần chi phí theo lượt chạy.

## Mục tiêu

### R1 — Hồ sơ Digital Worker và chủ thể của nó

Business Owner và Technical Owner có một DW là dữ liệu của công ty; DW hành động dưới một service principal của chính nó theo ADR-0103 (Accepted) quyết 2 và 4, với tầm với là quyền của principal đó giao với ranh giới công cụ.

- R1.1 KHI người giữ `dw.manage` gửi `POST /v1/digital-workers` hợp lệ, API PHẢI ghi trong một giao dịch một dòng `platform.digital_workers` trạng thái `draft` (id do server sinh, `tenant_id` và `workspace_id` từ access context), một service principal của DW (dòng `platform.users` `kind = 'service'` với `owner_tenant_id`, dòng `platform.service_principals` với `owner_user_id` là Business Owner) và membership của principal đó trong workspace của DW với `role_keys` của thân yêu cầu, và trả 201.
- R1.2 NẾU một trong bốn người (`business_owner_id`, `technical_owner_id`, `work_assigner_id`, `validator_id`) không có membership trong workspace của DW, hay Validator không giữ `approvals.decide` ở workspace đó, THÌ API PHẢI trả 422 `owner_not_member` hay `validator_cannot_decide` và không ghi dòng nào.
- R1.3 NẾU `allowed_tools` nêu một công cụ không có trong sổ công cụ của nền tảng, hay `work_kinds` rỗng, THÌ API PHẢI trả 422 `tool_unknown` hay `work_kinds_empty` và không ghi dòng nào.
- R1.4 Bộ dựng ngữ cảnh lượt chạy DW PHẢI đặt `requested_by` bằng `system_actor` của lane `dw_work`, `run_as_principal_id` và `actor_id` bằng service principal của DW, và tập scope bằng scope của membership của principal đó giao với hợp các `required_scopes` của công cụ trong `allowed_tools`.
- R1.5 NẾU người gọi không giữ `dw.read` trong workspace của DW hay DW thuộc tenant khác, THÌ `GET /v1/digital-workers/{id}` PHẢI trả 404 `not_found` như id không tồn tại.
- R1.6 NẾU người đổi trạng thái DW qua `POST /v1/digital-workers/{id}/state` không phải Business Owner hay Technical Owner của DW, THÌ API PHẢI trả 403 `not_dw_owner` và không đổi gì.
- R1.7 NẾU chuyển trạng thái không thuộc `draft→operating`, `operating→paused`, `paused→operating` hay `draft|operating|paused→retired`, THÌ API PHẢI trả 409 `invalid_transition` và không đổi gì.
- R1.8 KHI trạng thái DW đổi, API PHẢI ghi một dòng `platform.audit_events` `dw.state_changed` đứng tên người đổi, cùng giao dịch.
- R1.9 NẾU người gọi `draft→operating` là người đã tạo DW, hay không giữ mọi scope của vai của principal của DW, THÌ API PHẢI trả 409 `second_person_required` hay 403 `grants_not_covered` và không đổi gì (D11; ADR-0103 (Accepted) quyết 4).
- R1.10 NẾU người tạo DW không giữ mọi scope của `role_keys` gán cho principal của DW, THÌ API PHẢI trả 403 `grants_not_covered` và không ghi dòng nào (ADR-0103 (Accepted) quyết 4, luật phủ).
- R1.11 Service principal của DW PHẢI không có danh tính đăng nhập nào: trigger trên `platform.external_identities` từ chối dòng cho user `kind = 'service'`, và mọi danh sách của mặt danh tính (`/directory/candidates`, `/admin/members`) lọc `kind = 'human'`.
- R1.12 NẾU DW có việc ở `in_progress`, `waiting_approval` hay `waiting_timer` khi chuyển sang `retired`, THÌ API PHẢI trả 409 `dw_has_work_in_flight` và không đổi gì, kiểm trong giao dịch giữ khóa dòng DW (`FOR UPDATE`) mà phép nhận của lane cũng phải chờ (`FOR SHARE`).
- R1.14 KHI DW chuyển sang `retired`, API PHẢI đổi mọi việc `open` của DW sang `cancelled` cùng giao dịch.
- R1.15 NẾU một vai trong `role_keys` của principal là `tenant_owner`, `org_admin`, `platform_admin` hay mang một scope quản trị (`admin.*`), THÌ API PHẢI trả 422 `role_not_allowed_for_service` và không ghi dòng nào (ADR-0103 (Accepted) quyết 2: service principal không giữ vai có quyền tới hạn).
- R1.16 Trigger `platform.guard_accountable_owner()` PHẢI từ chối mọi `owner_user_id` của `platform.service_principals` không phải user `kind = 'human'` có membership trong tenant của principal (ADR-0103 (Accepted) quyết 3).
- R1.13 KHI Business Owner hay Technical Owner đổi một trong bốn người qua `PUT /v1/digital-workers/{id}/people`, API PHẢI kiểm như R1.2 và ghi audit `dw.people_changed`, cùng giao dịch, với Business Owner mới ghi vào `platform.service_principals.owner_user_id`, chỗ duy nhất giữ Business Owner.

### R2 — Loại quyết định và mức tự chủ có hiệu lực

Business Owner đặt trần và mức đã kiếm cho từng loại quyết định; runtime dùng mức thấp nhất (ADR-0128 (Proposed) quyết 3).

- R2.1 KHI một DW được tạo, API PHẢI ghi một dòng `platform.dw_decision_classes` cho mỗi loại quyết định trong thân yêu cầu, với `key`, `effect_level`, `reversible`, `ceiling` và `earned_level`.
- R2.2 NẾU `earned_level` của một loại cao hơn `ceiling` của nó, THÌ API PHẢI trả 422 `above_ceiling` và không ghi dòng nào.
- R2.3 `DecisionAutonomy.effective_level` PHẢI trả mức thấp nhất giữa `ceiling`, `earned_level` và `platform.tenants.max_autonomy_level`, đọc lúc được hỏi, và trả `A0` khi một trong ba không đọc được hay loại quyết định không tồn tại.
- R2.4 `DecisionAutonomy.requires_person` PHẢI quyết bằng cùng thang của `autonomy.py` (một hàm của `dw_kernel.autonomy`), với loại `external` có `reversible` xếp vào bậc ngoài có khóa chống lặp, và với loại `critical` luôn đòi người ở mọi mức.

### R3 — Hàng đợi việc chung

Người và DW làm trên một hàng đợi, mỗi việc có đúng một người giữ (ADR-0128 (Proposed) quyết 6).

- R3.1 KHI `WorkQueue.enqueue` nhận một việc cho một DW, cửa hàng đợi PHẢI ghi một dòng `platform.work_items` trạng thái `open`, `holder_kind = 'digital_worker'`, `holder_id` và `dw_id` là id DW, `payload_hash` là sha256 của payload chuẩn hóa.
- R3.2 NẾU `kind` của việc không có trong `work_kinds` của DW nhận, THÌ cửa hàng đợi PHẢI từ chối `work_kind_outside_mandate` và không ghi dòng nào.
- R3.3 NẾU payload không khớp JSON Schema khai cho `kind` đó qua `WorkKindSchemas`, hay không có schema cho `kind`, THÌ cửa hàng đợi PHẢI từ chối `payload_invalid` và không ghi dòng nào.
- R3.4 NẾU việc cùng `(tenant_id, dw_id, kind, source_key)` đã có, THÌ cửa hàng đợi PHẢI trả việc đã có khi `payload_hash` bằng nhau và từ chối `source_key_reused` khi khác, không ghi dòng thứ hai.
- R3.5 `GET /v1/work-items` PHẢI trả cho người giữ `dw.read` mọi việc của workspace (người và DW giữ) không kèm `payload` và `handoff`, lọc được theo `status` và `holder_kind`, phân trang keyset theo `(created_at, id)` qua một index dẫn bằng `tenant_id`.
- R3.6 Lane `dw_work` của worker PHẢI nhận mỗi việc `open` có `available_at <= now()` do một DW `operating` giữ đúng một lần, qua hàm SECURITY DEFINER `platform.dw_work_scopes_due(limit)` trả cặp `(tenant_id, workspace_id)` rồi một lần nhận `FOR UPDATE SKIP LOCKED` dưới `app.tenant_id` và `app.workspace_id` của cặp đó, chuyển việc sang `in_progress` và ghi `run_id` ngay khi runner trả id lượt chạy.
- R3.7 TRONG KHI DW giữ việc không ở trạng thái `operating`, lane `dw_work` PHẢI để việc ở `open` và không yêu cầu lượt chạy nào.
- R3.8 NẾU người gọi `POST /v1/work-items/{id}/complete` không phải người đang giữ việc, hay việc không ở `handed_off`, THÌ API PHẢI trả 403 `not_holder` hay 409 `invalid_transition` và không đổi gì.
- R3.13 KHI người đang giữ một việc `handed_off` gọi `POST /v1/work-items/{id}/complete`, API PHẢI chuyển việc sang `done` với `closed_at` và audit `work_item.completed` cùng giao dịch.
- R3.9 NẾU runner từ chối bắt đầu lượt chạy vì hạn mức của tenant, THÌ lane `dw_work` PHẢI trả việc về `open` với `available_at` sau 5 phút và không xóa việc (`CLAUDE.md` "Agent and tool rules": lượt do sự kiện vào chờ trong hàng, không bị bỏ).
- R3.10 NẾU người đưa việc qua `POST /v1/digital-workers/{id}/work-items` không phải Work Assigner của DW, THÌ API PHẢI trả 403 `not_work_assigner` và không ghi dòng nào.
- R3.11 `GET /v1/work-items/{id}` PHẢI trả `payload` và `handoff` chỉ cho người đang giữ việc và bốn người của DW, và trả việc không kèm hai trường đó cho người giữ `dw.read` khác.
- R3.14 NẾU một việc ở `in_progress` với `run_id` NULL quá 15 phút không cập nhật, THÌ lane `dw_work` PHẢI trả nó về `open` trước khi nhận việc mới, để việc mà tiến trình chết giữa lúc nhận và lúc bắt đầu lượt chạy không kẹt.
- R3.12 NẾU một thao tác đổi trạng thái việc theo cặp không có trong bảng chuyển của mục Dữ liệu, THÌ cửa hàng đợi PHẢI từ chối `invalid_transition` và không đổi gì.

### R4 — Bàn giao với gói

DW dừng và trao việc cho một người kèm gói bàn giao (YC121, ADR-0128 (Proposed) quyết 7).

- R4.1 KHI `WorkQueue.hand_off` được gọi cho một việc DW đang giữ, cửa hàng đợi PHẢI chuyển việc sang `handed_off`, đổi người giữ sang người nhận (`holder_kind = 'person'`) và ghi gói `{problem, context, tried, recommendation}`, cùng một dòng audit `work_item.handed_off` đứng tên service principal của DW, trong một giao dịch.
- R4.2 NẾU gói thiếu một trong bốn trường, hay một trường rỗng hoặc dài quá 4.000 ký tự, THÌ cửa hàng đợi PHẢI từ chối `handoff_packet_invalid` và không đổi việc.
- R4.3 NẾU người nhận không có membership trong workspace của việc, THÌ cửa hàng đợi PHẢI từ chối `handoff_target_invalid` và không đổi việc.

### R5 — Cổng duyệt theo loại quyết định

Một đề xuất trên mức hiệu lực chờ đúng người duyệt, qua cửa phê duyệt có sẵn (ADR-0128 (Proposed) quyết 8).

- R5.1 KHI `DecisionGate.check` được gọi cho một loại quyết định mà `requires_person` đúng, cổng PHẢI trả lệnh mở approval loại `dw.decision` với payload gồm `dw_id`, `decision_class`, `effective_level`, `proposal`, `proposal_schema` và `locked_fields`.
- R5.2 KHI `requires_person` sai, cổng PHẢI trả `auto` và ghi một dòng audit `dw.decision.auto` với `decision_class` và `effective_level`, đứng tên service principal của DW.
- R5.3 NẾU người quyết một approval `dw.decision` không phải Validator hay Business Owner hiện tại của DW, đọc lúc quyết trong giao dịch của quyết định, THÌ `ApproveAndResumeService.decide` PHẢI trả 409 `not_eligible_decider` và không ghi quyết định nào.
- R5.4 NẾU người duyệt một approval `dw.decision` gửi `edited_proposal` không khớp `proposal_schema`, hay đổi một trường trong `locked_fields`, THÌ route quyết định PHẢI trả 422 `proposal_invalid` hay `locked_field_changed` và không ghi quyết định nào (D18).
- R5.5 KHI một approval `dw.decision` được quyết, `ApproveAndResumeService` PHẢI chạy tiếp lượt chạy với `approved`, `comment` và `edited_proposal` (khi có), và ghi `edited` đúng hay sai lên dòng quyết định để scorecard đọc (D18).

### R6 — Ranh giới ở cửa công cụ

Tạm dừng và mandate có hiệu lực ở cửa hiệu ứng, không chỉ ở lane (ADR-0128 (Proposed) quyết 10).

- R6.1 TRONG KHI DW ở trạng thái khác `operating`, hay trạng thái của nó không đọc được, `ToolExecutor` PHẢI từ chối mọi lời gọi công cụ của lượt chạy có `run_as_principal_id` là principal của DW đó với `dw_not_operating`, không gọi công cụ và ghi lần từ chối vào `platform.tool_executions`.
- R6.2 NẾU công cụ của một lời gọi không có trong `allowed_tools` của DW mà lượt chạy đứng tên, THÌ `ToolExecutor` PHẢI từ chối `tool_not_allowed`, không gọi công cụ và ghi lần từ chối.
- R6.3 NẾU scope mà công cụ đòi không nằm trong scope hiện tại của membership của principal của DW giao với `allowed_tools`, đọc lúc gọi chứ không từ ngữ cảnh dựng lúc lượt bắt đầu, THÌ `ToolExecutor` PHẢI từ chối `scope_lost` và không gọi công cụ (ADR-0103 (Accepted) quyết 5: tầm với đọc sống, lượt chạy tiếp hẹp lại khi mất quyền).

### R7 — Scorecard

Business Owner đọc DW làm được gì từ dữ liệu, không từ lời DW tự báo (YC122).

- R7.1 `GET /v1/digital-workers/{id}/scorecard?days=<n>` PHẢI trả, trong cửa sổ cuộn `now() - n × 24 giờ`, số việc của DW (`dw_id`) theo trạng thái và tỷ lệ `done`, `handed_off` theo `created_at` của việc, số approval `dw.decision` của DW được duyệt nguyên văn, duyệt có sửa và bị từ chối theo `decided_at`, và tổng `model_cost_usd` của lượt chạy có `run_as_principal_id` là principal của DW theo `created_at` của lượt.
- R7.2 NẾU `days` ngoài 1-90, THÌ API PHẢI trả 422 `days_out_of_range`; 1 và 90 thì nhận.
- R7.3 KHI một lời gọi model của lượt chạy DW xong, bộ ghi chi phí PHẢI cộng chi phí ước tính vào `platform.worker_runs.model_cost_usd` của lượt đó bằng một câu `UPDATE` cộng dồn.

### R8 — Nâng và hạ mức đã kiếm

Business Owner đổi mức đã kiếm; nâng cần người thứ hai, hạ có hiệu lực ngay (YC123, ADR-0128 (Proposed) quyết 5).

- R8.1 KHI Business Owner hay Technical Owner hạ `earned_level` qua `POST /v1/digital-workers/{id}/decision-classes/{key}/autonomy`, API PHẢI ghi mức mới và dòng audit `dw.autonomy.lowered` trong một giao dịch, và cổng đọc mức mới ở lần hỏi kế tiếp.
- R8.2 KHI Business Owner nâng `earned_level`, API PHẢI mở một approval `dw.autonomy.raise` không gắn lượt chạy với `from_level` và `to_level` trong payload, và không đổi mức.
- R8.3 NẾU người quyết `dw.autonomy.raise` là người đề nghị, không phải Validator hay Technical Owner của DW, hay không ghi lý do, THÌ `ApproveAndResumeService.decide` PHẢI trả 409 và không ghi quyết định nào.
- R8.4 NẾU mức đề nghị cao hơn `ceiling` của loại quyết định, hay loại đó đã có một approval `dw.autonomy.raise` đang chờ, THÌ API PHẢI trả 422 `above_ceiling` hay 409 `raise_pending` và không mở approval.
- R8.5 NẾU người nâng không phải Business Owner, hay người hạ không phải Business Owner hay Technical Owner, THÌ API PHẢI trả 403 `not_dw_owner` và không đổi gì.
- R8.6 KHI sự kiện `dw.autonomy.raise.decided` tới, handler PHẢI ghi `to_level` chỉ khi quyết định là duyệt, `earned_level` hiện tại vẫn bằng `from_level` và DW chưa `retired`, và ghi audit `dw.autonomy.raise_stale` mà không đổi mức khi không.

### R9 — Màn hình

Business Owner, Validator và người làm việc thấy DW, hàng đợi và thẻ duyệt trên web (antd).

- R9.1 Trang `/digital-workers` PHẢI liệt kê DW của workspace với tên, trạng thái, mandate rút gọn và số việc đang mở.
- R9.2 Trang `/digital-workers/[id]` PHẢI hiện hồ sơ, bốn người, các loại quyết định với trần, mức đã kiếm và mức hiệu lực hiện bằng chữ "Tự động", "Hỏi" hay "Chặn" ("Chặn" là thao tác ngoài `allowed_tools`) kèm mức A0-A4 (D18), scorecard 30 ngày và cây quy trình chỉ đọc.
- R9.3 Trang `/work` PHẢI hiện hàng đợi chung lọc theo trạng thái và loại người giữ, cùng gói bàn giao của việc `handed_off`.
- R9.4 Trang `/approvals` PHẢI hiện approval `dw.decision` thành một thẻ có tên DW, loại quyết định, mức hiệu lực và đề xuất.
- R9.5 NẾU API trả 403 hay 404 cho một trang DW, THÌ trang PHẢI hiện trạng thái không có quyền hay không tìm thấy và không hiện dữ liệu nào.

## Trong phạm vi

- Bảng `platform.digital_workers`, `platform.dw_decision_classes`, `platform.work_items`, `platform.service_principals` tối thiểu; cột `platform.users.kind`, `platform.users.owner_tenant_id`, `platform.worker_runs.run_as_principal_id`, `platform.worker_runs.model_cost_usd`, `platform.approval_decisions.edited`, `platform.approval_decisions.edited_payload`; scope `dw.read`, `dw.manage`.
- Route `/v1/digital-workers` (tạo, danh sách, đọc, đổi trạng thái, đổi người, scorecard, đổi mức, đưa việc), `/v1/work-items` (danh sách, đọc, xong).
- Port `DecisionAutonomy`, `DecisionGate`, `WorkQueue`, `WorkKindSchemas` (do bên dùng khai), lane `dw_work`, kiểm `dw.decision` và `dw.autonomy.raise` lúc quyết, handler `dw.autonomy.raise.decided`, hai phép kiểm ở `ToolExecutor` (R6).
- Trang web `/digital-workers`, `/digital-workers/[id]`, `/work`, thẻ `dw.decision` trên `/approvals`.

## Ngoài phạm vi

| Việc                                                                                                | Vì sao                                                               | Chủ                      |
| --------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- | ------------------------ |
| Chạy tài liệu quy trình của DW                                                                      | bộ máy quy trình là một spec riêng                                   | `wf-lite`                |
| Gói Marketing, JSON Schema của lead, cửa nhận lead                                                  | nội dung của DW đầu tiên, không phải lõi                             | `leadcare`               |
| Khóa API của service principal, gắn principal qua binding của phiên bản, lane `principal_ownership` | ADR-0103 (Accepted) quyết 3, 4, 6 cho Studio; lát DW chỉ cần chủ thể | org-and-principals/03    |
| `RunRequestService`, `RunControlPort` (đóng băng) và `trigger_kind` của ADR-0113 (Accepted)         | lượt DW lát đầu chạy tài liệu gói, chưa là lượt Studio (D17)         | workflow-engine          |
| Sổ sử dụng theo lượt gọi làm nguồn chi phí của scorecard                                            | sổ chưa có; R7.3 ghi chi phí của chính lượt chạy                     | usage-and-limits/02      |
| Bảo mật trường trên payload việc                                                                    | chưa có field-security; R3.11 giới hạn người đọc payload             | field-security           |
| KPI có đích và mức dịch vụ của DW                                                                   | lát đầu chỉ đo; đích đặt sau khi có số                               | đợt sau                  |
| A5                                                                                                  | ADR-0128 (Proposed) quyết 4                                          | không làm                |
| Tenant tự dựng DW và quy trình trong Studio, cổng chất lượng trước `operating`                      | đường C đi trước Studio (D17)                                        | agent-lifecycle, đợt sau |
| Work Assigner giao việc ngoài mandate                                                               | ADR-0128 (Proposed) mục Open 2                                       | đợt sau                  |

## Dữ liệu

- `platform.users`: thêm `kind text NOT NULL DEFAULT 'human'` CHECK trong `human, service`, `owner_tenant_id uuid NULL` FK `platform.tenants` `ON DELETE CASCADE`, index, CHECK `(kind = 'service') = (owner_tenant_id IS NOT NULL)` (ADR-0103 (Accepted) quyết 2).
- `platform.service_principals`: `user_id uuid PK` FK `platform.users` `ON DELETE CASCADE`; `tenant_id uuid NOT NULL`; `owning_workspace_id uuid NOT NULL` FK `platform.workspaces` `ON DELETE RESTRICT`, index; `name text NOT NULL` 1-120 ký tự; `owner_user_id uuid NULL` FK `platform.users` `ON DELETE SET NULL`, index, giữ bởi trigger `platform.guard_accountable_owner()` (R1.16), là Business Owner của DW; `created_at`. Bảng toàn tenant (RLS theo tenant, lý do ghi trong danh sách của `test_rls_coverage.py`).
- `platform.digital_workers`: `id uuid PK`; `tenant_id uuid NOT NULL` FK `platform.tenants` `ON DELETE RESTRICT`; `workspace_id uuid NOT NULL` FK `platform.workspaces` `ON DELETE RESTRICT`; `principal_user_id uuid NOT NULL UNIQUE` FK `platform.users` `ON DELETE RESTRICT`; không cột Business Owner riêng (đọc `platform.service_principals.owner_user_id`); `key text NOT NULL` CHECK `^[a-z][a-z0-9_]{1,39}$`, UNIQUE `(tenant_id, key)`; `name text NOT NULL` 1-120 ký tự; `mandate text NOT NULL` 1-2.000 ký tự; `work_kinds text[] NOT NULL` CHECK `cardinality >= 1`; `allowed_tools text[] NOT NULL`; `workflow_key text NOT NULL`; `workflow_version text NOT NULL` semver; `parameters jsonb NOT NULL DEFAULT '{}'`; `state text NOT NULL DEFAULT 'draft'` CHECK trong `draft, operating, paused, retired`; ba cột người `technical_owner_id`, `work_assigner_id`, `validator_id` `uuid NOT NULL` FK `platform.users` `ON DELETE RESTRICT`, mỗi cột một index; `created_by uuid NOT NULL`; `created_at`, `updated_at timestamptz NOT NULL`, trigger `updated_at` nhường giá trị câu lệnh nêu.
- `platform.dw_decision_classes`: PK `(dw_id, key)`; `tenant_id`, `workspace_id` NOT NULL; `dw_id` FK `platform.digital_workers` `ON DELETE CASCADE`; `key text` CHECK `^[a-z][a-z0-9_.]{1,63}$`; `effect_level text NOT NULL` CHECK trong `none, internal, external, critical`; `reversible boolean NOT NULL`; `ceiling`, `earned_level text NOT NULL` CHECK trong `A0..A4`, CHECK `earned_level <= ceiling` theo thứ tự mức; `updated_at`.
- `platform.work_items`: `id uuid PK`; `tenant_id`, `workspace_id` NOT NULL; `dw_id uuid NOT NULL` FK `platform.digital_workers` `ON DELETE RESTRICT`, index; `kind text NOT NULL`; `source_key text NOT NULL`; `payload jsonb NOT NULL`, không đổi sau khi ghi (trigger `BEFORE UPDATE` từ chối đổi `payload`, `payload_hash`, `kind`, `source_key`, `dw_id`); `payload_hash text NOT NULL`; UNIQUE `(tenant_id, dw_id, kind, source_key)`; `holder_kind text NOT NULL` CHECK trong `digital_worker, person`; `holder_id uuid NOT NULL`; `status text NOT NULL` CHECK trong `open, in_progress, waiting_approval, waiting_timer, handed_off, done, failed, cancelled`; `available_at timestamptz NOT NULL DEFAULT now()`; `run_id uuid NULL`, index; `wake_at timestamptz NULL`, CHECK `(status = 'waiting_timer') = (wake_at IS NOT NULL)`, index một phần `(wake_at) WHERE status = 'waiting_timer'`; `handoff jsonb NULL`; `error text NULL`; `created_at`, `updated_at`, `closed_at timestamptz`; index `(tenant_id, workspace_id, created_at DESC, id DESC)` và index một phần `(tenant_id, available_at) WHERE status = 'open'` cho lane.
- Bảng chuyển trạng thái của việc (R3.12), mỗi cặp với bên thực hiện: `open→in_progress` (lane `dw_work`); `in_progress→open` (hạn mức R3.9, việc kẹt R3.14); `in_progress→waiting_approval`, `in_progress→waiting_timer` (runner khi chờ); `waiting_approval→in_progress`, `waiting_timer→in_progress` (chạy tiếp); `in_progress→handed_off`, `waiting_approval→handed_off`, `waiting_timer→handed_off` (`hand_off`); `in_progress→done`, `in_progress→failed` (lượt chạy kết thúc); `handed_off→done` (người giữ, R3.13); `open→cancelled` (DW `retired`, R1.14). `done`, `failed`, `cancelled` là cuối.
- `platform.worker_runs`: thêm `run_as_principal_id uuid NULL`, index (cột của ADR-0113 (Accepted) quyết 1, có từ lát này); `model_cost_usd numeric(12,6) NOT NULL DEFAULT 0` CHECK `>= 0`.
- `platform.approval_decisions`: thêm `edited boolean NOT NULL DEFAULT false`, `edited_payload jsonb NULL`, CHECK `edited = (edited_payload IS NOT NULL)`.
- RLS: các bảng mới ENABLE và FORCE; `digital_workers`, `dw_decision_classes`, `work_items` dùng policy `tenant AND (workspace OR current_setting('app.workspace_scope') = 'tenant')` của `CLAUDE.md` "Tenancy and authorization"; quyền `dw_app` SELECT, INSERT, UPDATE; `DELETE` không cấp (offboarding xóa bằng vai của nó). Hàm `platform.dw_work_scopes_due(limit)` SECURITY DEFINER chỉ trả cặp `(tenant_id, workspace_id)` có việc đến hạn (mẫu của `platform.channel_delivery_scopes_due`, ADR-0113 (Accepted) quyết 2).

## API

| Route                                                           | Scope và chức năng                     | Lỗi chính                                                                                                                        |
| --------------------------------------------------------------- | -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `POST /v1/digital-workers`                                      | `dw.manage`                            | 422 `owner_not_member`, `validator_cannot_decide`, `tool_unknown`, `work_kinds_empty`, `above_ceiling`; 403 `grants_not_covered` |
| `GET /v1/digital-workers`, `GET /v1/digital-workers/{id}`       | `dw.read`                              | 404 `not_found`                                                                                                                  |
| `POST /v1/digital-workers/{id}/state`                           | `dw.read` và BO hay TO của DW          | 403 `not_dw_owner`, 409 `invalid_transition`, `second_person_required`, `dw_has_work_in_flight`                                  |
| `PUT /v1/digital-workers/{id}/people`                           | `dw.read` và BO hay TO của DW          | 403 `not_dw_owner`, 422 như tạo                                                                                                  |
| `GET /v1/digital-workers/{id}/scorecard?days=`                  | `dw.read`                              | 422 `days_out_of_range`                                                                                                          |
| `POST /v1/digital-workers/{id}/decision-classes/{key}/autonomy` | `dw.read` và BO (nâng), BO hay TO (hạ) | 403 `not_dw_owner`, 422 `above_ceiling`, 409 `raise_pending`; 202 khi mở approval nâng                                           |
| `POST /v1/digital-workers/{id}/work-items`                      | `dw.read` và Work Assigner của DW      | 403 `not_work_assigner`, 422 `payload_invalid`, `work_kind_outside_mandate`, 409 `source_key_reused`                             |
| `GET /v1/work-items`, `GET /v1/work-items/{id}`                 | `dw.read`                              | 404 `not_found`                                                                                                                  |
| `POST /v1/work-items/{id}/complete`                             | `dw.read` và người giữ                 | 403 `not_holder`, 409 `invalid_transition`                                                                                       |

Mọi route theo app-standards (problem+json, `Idempotency-Key` ở route ghi, keyset có kiểu). Scope `dw.read` cấp cho mọi vai thành viên, `dw.manage` cho `org_admin`, bằng migration. Bốn người là chức năng kiểm ở chính thao tác (ADR-0128 (Proposed) quyết 2), không phải vai.

## Màn hình

R9. Ant Design v6, thanh trên cùng có mục "Digital Worker" và "Hàng đợi việc"; ngày giờ qua `lib/dates.ts`. Cây quy trình chỉ đọc vẽ bằng antd (không `@xyflow/react`, đường đó chỉ cho `apps/web/app/studio/**/canvas/**`). Một loại quyết định hiện "Chặn" khi mọi công cụ mà các bước `tool.call` của loại đó gọi trong tài liệu đã ghim đều ngoài `allowed_tools`, "Hỏi" khi `requires_person` đúng, "Tự động" khi sai.

## Kiểm soát

| #     | Kiểm soát                                                                         | Yêu cầu      | Test âm                                                                                                                                                                                                       |
| ----- | --------------------------------------------------------------------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| DWK1  | bốn người phải là thành viên, Validator phải duyệt được                           | R1.2, R1.13  | Validator là user của tenant B, và Validator không giữ `approvals.decide`: 422, đếm `digital_workers` không đổi                                                                                               |
| DWK2  | lượt chạy DW đứng tên lane, tầm với là quyền của principal giao ranh giới công cụ | R1.4         | người tạo giữ `admin.*`, principal giữ `email.send` và `records.read`, `allowed_tools` chỉ cần `email.send`: scope của ngữ cảnh chỉ `email.send`, `requested_by` là actor của lane                            |
| DWK3  | DW, loại quyết định, việc của tenant khác hay workspace khác không đọc được       | R1.5, R3.5   | tenant B đọc id DW và id việc của tenant A: 404; danh sách của B không có dòng của A; đọc thẳng bảng không scope: 0 dòng                                                                                      |
| DWK4  | chỉ Business Owner hay Technical Owner đổi trạng thái và người                    | R1.6, R1.13  | người giữ `dw.manage` không là chủ gọi `/state` và `/people`: 403, không đổi gì                                                                                                                               |
| DWK5  | chuyển trạng thái ngoài bảng bị từ chối                                           | R1.7         | `retired→operating`: 409, trạng thái không đổi                                                                                                                                                                |
| DWK6  | mức hiệu lực là mức thấp nhất của ba, thiếu thì `A0`                              | R2.3         | trần tenant A1, đã kiếm A3: `A1`; loại không tồn tại: `A0`                                                                                                                                                    |
| DWK7  | `critical` luôn đòi người, ngoài đảo được xếp bậc có khóa                         | R2.4         | loại `critical` ở A4: đòi người; `external` không đảo được ở A3: đòi; đảo được ở A3: không đòi                                                                                                                |
| DWK8  | việc ngoài mandate bị từ chối                                                     | R3.2         | `enqueue` kind không thuộc `work_kinds`: từ chối, đếm `work_items` không đổi                                                                                                                                  |
| DWK9  | payload sai schema hay không có schema bị từ chối                                 | R3.3         | payload thiếu trường bắt buộc, và kind không có schema: từ chối, không dòng nào                                                                                                                               |
| DWK10 | mỗi việc được nhận đúng một lần                                                   | R3.6         | hai lane chạy song song trên một việc: đúng một lượt chạy được yêu cầu                                                                                                                                        |
| DWK11 | DW không `operating` không nhận việc                                              | R3.7         | DW `paused` với việc `open`: lane chạy xong, việc vẫn `open`, không lượt chạy nào                                                                                                                             |
| DWK12 | chỉ người giữ đánh dấu xong, chỉ từ `handed_off`                                  | R3.8         | người khác gọi `/complete`: 403; người giữ gọi trên việc `in_progress`: 409; trạng thái không đổi                                                                                                             |
| DWK13 | gói bàn giao đủ bốn trường                                                        | R4.2         | thiếu `recommendation`: từ chối, việc vẫn `in_progress`                                                                                                                                                       |
| DWK14 | người nhận bàn giao phải là thành viên workspace                                  | R4.3         | người nhận của tenant B: từ chối, người giữ không đổi                                                                                                                                                         |
| DWK15 | chỉ Validator hay Business Owner hiện tại quyết `dw.decision`                     | R5.3         | người giữ `approvals.decide` không là Validator hay BO, và Validator cũ sau khi đổi người: 409, không dòng quyết định                                                                                         |
| DWK16 | DW không `operating` hay trạng thái không đọc được thì không gây hiệu ứng         | R6.1         | lượt chạy của DW `paused` gọi công cụ, và lần đọc trạng thái lỗi: từ chối `dw_not_operating`, công cụ không chạy                                                                                              |
| DWK17 | nâng mức không đổi gì trước khi người thứ hai duyệt, không ghi đè lần hạ          | R8.2, R8.6   | nâng: mức vẫn cũ; từ chối: vẫn cũ; hạ khẩn rồi duyệt đề nghị cũ: mức giữ mức đã hạ, có `dw.autonomy.raise_stale`                                                                                              |
| DWK18 | người duyệt nâng là Validator hay TO khác người đề nghị                           | R8.3         | BO duyệt đề nghị của mình, và người ngoài DW giữ `approvals.decide` duyệt: 409, mức không đổi                                                                                                                 |
| DWK19 | mức đề nghị không vượt trần, không hai đề nghị song song                          | R8.4         | đề nghị A4 với trần A3: 422; đề nghị thứ hai khi một đang chờ: 409; không approval mới                                                                                                                        |
| DWK20 | chỉ chủ DW nâng hay hạ                                                            | R8.5         | Validator hạ mức: 403, mức không đổi                                                                                                                                                                          |
| DWK21 | trang DW không hiện dữ liệu khi API từ chối                                       | R9.5         | API mock trả 403: trang không có hàng dữ liệu nào                                                                                                                                                             |
| DWK22 | bản sửa sai schema hay đổi trường khóa không thành quyết định                     | R5.4         | `edited_proposal` thiếu `subject`, và đổi `to`: 422, không dòng quyết định, lượt chạy vẫn chờ                                                                                                                 |
| DWK23 | cấu hình mới vào chạy cần người thứ hai                                           | R1.9         | người tạo tự gọi `draft→operating`: 409 `second_person_required`; TO không giữ scope của vai của principal: 403 `grants_not_covered`; DW vẫn `draft`                                                          |
| DWK24 | người tạo không trao cho DW quyền mình không có                                   | R1.10        | người tạo không giữ `email.send` gán vai có `email.send` cho principal: 403 `grants_not_covered`, không dòng nào                                                                                              |
| DWK25 | service principal không đăng nhập được và không hiện ở mặt danh tính              | R1.11        | chèn `external_identities` cho user `kind = 'service'`: lỗi trigger; `/directory/candidates` không có principal của DW                                                                                        |
| DWK26 | công cụ ngoài `allowed_tools` không chạy ở cửa công cụ                            | R6.2         | lượt chạy DW gọi công cụ cùng scope nhưng ngoài `allowed_tools`: `tool_not_allowed`, công cụ không chạy                                                                                                       |
| DWK27 | việc không bị bỏ khi hạn mức hết                                                  | R3.9         | runner giả từ chối vì hạn mức: việc về `open` với `available_at` sau 5 phút, không dòng nào bị xóa                                                                                                            |
| DWK28 | khóa chống lặp gồm DW, khác payload thì từ chối                                   | R3.4         | hai DW cùng tenant cùng `source_key`: hai việc; cùng DW khác payload: `source_key_reused`                                                                                                                     |
| DWK29 | payload chỉ người giữ và bốn người đọc được                                       | R3.11, R3.5  | thành viên giữ `dw.read` không là người của DW đọc việc: không có `payload` và `handoff`                                                                                                                      |
| DWK30 | chỉ Work Assigner đưa việc tay                                                    | R3.10        | Validator gọi `POST .../work-items`: 403 `not_work_assigner`, không dòng nào                                                                                                                                  |
| DWK31 | việc chỉ đổi trạng thái theo bảng chuyển, payload không đổi                       | R3.12        | `done→in_progress`: `invalid_transition`; `UPDATE` `payload` của việc: lỗi trigger                                                                                                                            |
| DWK33 | principal không giữ vai tới hạn, chủ chịu trách nhiệm là người thật của tenant    | R1.15, R1.16 | gán `org_admin` cho principal: 422 `role_not_allowed_for_service`; `owner_user_id` là user của tenant B hay user `kind = 'service'`: lỗi trigger                                                              |
| DWK34 | tầm với đọc sống ở cửa công cụ                                                    | R6.3         | thu vai của principal sau khi lượt chờ duyệt, rồi duyệt: `scope_lost`, công cụ không chạy                                                                                                                     |
| DWK35 | việc kẹt giữa lúc nhận và lúc bắt đầu lượt được trả về                            | R3.14        | việc `in_progress` `run_id` NULL 16 phút: lane trả về `open`; 14 phút: giữ nguyên                                                                                                                             |
| DWK32 | DW `retired` không để việc mồ côi và không bỏ việc đang chạy                      | R1.12, R1.14 | có việc `waiting_approval`: 409 `dw_has_work_in_flight`; chỉ có việc `open`: việc thành `cancelled`; lane nhận song song với `retired`: một trong hai chờ khóa, không việc `in_progress` nào của DW `retired` |

## Tiêu chí thành công

- Góp vào KQ15: Business Owner thấy DW chăm sóc lead làm việc trên màn hình, với scorecard tính từ lịch sử.

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (`scripts/mutate.py`).
- `make test-unit test-contract test-architecture` xanh và integration của `dw_platform`, `dw_agent_runtime`, `apps/api`, `apps/worker` xanh.

## Phụ thuộc

- ADR-0128 (Proposed), ADR-0103 (Accepted) quyết 1, 2, 4, 5, ADR-0113 (Accepted) quyết 1-2 cho hình hàng đợi Postgres và phép nhận công bằng không `BYPASSRLS`; `RunAllowancePort` của runner cho hạn mức (`CLAUDE.md` "Agent and tool rules").
- `ApproveAndResumeService` với `decision_guards` và `strict_approval_prefixes`, `ToolExecutor`, `platform.tenants.max_autonomy_level`, `autonomy.py`.
- `wf-lite` gọi `DecisionGate`, `WorkQueue.hand_off` và khai `WorkKindSchemas` qua tài liệu của gói; `leadcare` gọi `WorkQueue.enqueue`.
- Hai lớp quyết "cần người" khớp nhau nhờ chuỗi wf-lite:R4.2 (công cụ không vượt loại quyết định của tài liệu) và wf-lite:R6.9 (DW không nới loại của tài liệu); cửa cuối là wf-lite:R6.17 ở `ToolExecutor`. `RunAllowancePort` là cổng hạn mức hiện có mà `CLAUDE.md` gọi là `LimitsPort` (usage-and-limits đổi tên).
- Kiểm lại khi: org-and-principals/02 có `platform.tenant_members` → FK của `owner_user_id`; org-and-principals/03 mở rộng `platform.service_principals` (khóa API, binding, lane chủ sở hữu) → R1.1, R1.11; workflow-engine dựng `RunRequestService` → R3.6, R3.9; usage-and-limits/02 có sổ → R7.3 chuyển nguồn; ADR-0128 (Proposed) đổi trạng thái → cả spec.

## Câu hỏi còn mở

- Q1. A5 có nghĩa gì khác A4 trên nền tảng này? Chủ: Đạt. Không đổi: năm mức A0-A4 của kernel trong lát này.

## Quyết định

- 29/10/2026 (agent, tạm theo ủy quyền): Theo gate `checking-plan-readiness` (lượt 1): định danh DW là service principal tối thiểu theo ADR-0103 (Accepted) quyết 2 (dòng `platform.users` `kind = 'service'`, `platform.service_principals`, membership có vai), không phải id của dòng DW như bản nháp, vì ADR-0103 (Accepted) quyết 1 bác "agent là chủ thể có quyền riêng"; lượt chạy đứng tên lane `dw_work`, chạy dưới principal đó, tầm với là quyền của principal giao ranh giới công cụ (quyết 4, 5); org-and-principals/03 chờ digital-worker/01 và mở rộng bảng đó. Sửa: R1.1, R1.4, R1.10, R1.11, Dữ liệu, DWK2, DWK24, DWK25. Nếu sai thì: lát DW chờ org-and-principals/03.
- 29/10/2026 (agent, tạm theo ủy quyền): Cũng theo gate lượt 1: `draft→operating` cần người khác người tạo (R1.9), nên cấu hình ban đầu và mức đã kiếm lúc tạo không đi vòng luật hai người; chức năng (BO, TO, Work Assigner, Validator) kiểm ở thao tác, không cần `dw.manage`; người duyệt `dw.decision` đọc lúc quyết; payload việc không đổi sau khi ghi và chỉ người giữ và bốn người đọc được; hàng đợi có bảng chuyển trạng thái, `available_at` cho hạn mức, khóa chống lặp gồm DW; `ToolExecutor` từ chối công cụ ngoài `allowed_tools` và đóng khi không đọc được trạng thái DW. Sửa: R1.2, R1.9, R1.12-R1.14, R3.1-R3.13, R5.1, R5.3, R5.4, R6, R7.1, R8.2-R8.6, Dữ liệu, API, DWK1-DWK32. Nếu sai thì: từng mục quay về bản trước gate trong lịch sử git của tệp này.
- 29/10/2026 (agent, tạm theo ủy quyền): Theo lượt xác nhận của gate (hai CRITICAL mới từ ADR-0103 (Accepted)): Business Owner chỉ nằm ở `platform.service_principals.owner_user_id` (chủ chịu trách nhiệm của quyết 3), giữ bởi trigger, `ON DELETE SET NULL`, FK tới `platform.users` cho tới khi org-and-principals/02 có `platform.tenant_members` thì chuyển FK theo quyết 3; principal không giữ `tenant_owner`, `org_admin`, `platform_admin` hay vai mang scope `admin.*` (quyết 2, khi chưa có danh mục quyền `critical` của ADR-0104 (Accepted)); tầm với đọc sống ở cửa công cụ (quyết 5); người đưa DW vào chạy phải phủ quyền của principal (quyết 4); phép nhận theo cặp tenant và workspace; khóa dòng DW giữa `retired` và lane; việc kẹt trả về `open`. Đúng về `dw.manage` thay `platform.service_principals.manage` (quyết 2): tới khi tenant-rbac có danh mục quyền, `dw.manage` là quyền tạo principal của DW. Sửa: R1.1, R1.9, R1.12, R1.13, R1.15, R1.16, R3.6, R3.14, R6.3, Dữ liệu, DWK23, DWK32-DWK35. Nếu sai thì: từng mục quay về bản trước trong lịch sử git.
- 29/10/2026 (agent, tạm theo ủy quyền): Lượt DW lát đầu không đi qua `RunRequestService` của ADR-0113 (Accepted), vì chưa có và lượt chạy tài liệu gói chưa là lượt Studio (D17); lane `dw_work` là cửa duy nhất, nhận theo mẫu công bằng của ADR-0113 (Accepted) quyết 2, hạn mức qua `RunAllowancePort` của runner, việc bị từ chối vì hạn mức chờ trong hàng. Nếu sai thì: lát DW chờ workflow-engine dựng `RunRequestService`.
- 29/10/2026 (agent, tạm): Loại quyết định của DW nêu trong thân yêu cầu tạo; wf-lite kiểm lúc chạy rằng mọi loại mà tài liệu quy trình dùng đều có trên DW, vì dw/01 đi trước wf-lite/01 theo hàng đợi. Nếu sai thì: API tạo DW đọc loại quyết định từ tài liệu đã ghim và thân yêu cầu chỉ nêu mức.
- 29/10/2026 (agent, tạm): Mức hiệu lực đọc ở lúc cổng hỏi, không đóng dấu lúc lượt chạy bắt đầu, nên hạ mức có hiệu lực cả với lượt đang chạy ở cổng kế tiếp. Nếu sai thì: đóng dấu mức lên lượt chạy và R8.1 chỉ áp lượt mới.
- 29/10/2026 (agent, tạm): Chi phí của scorecard là cột `model_cost_usd` của lượt chạy cho tới khi sổ sử dụng có; khi đó sổ là chủ và cột thành dẫn xuất hay bị bỏ. Nếu sai thì: scorecard không có cột chi phí cho tới usage-and-limits/02.
- 29/10/2026 (Đạt): D18 theo khuyến nghị sau khi đối chiếu FPT AI EOS: chữ "Tự động / Hỏi / Chặn", "Sửa rồi duyệt" và "Từ chối kèm lý do". Sửa: R5.4, R5.5, R7.1, R9.2, DWK22.
- 29/10/2026 (agent, tạm): Cây quy trình chỉ đọc vẽ bằng antd, không `@xyflow/react`. Nếu sai thì: trang chuyển dưới `apps/web/app/studio/**/canvas/**` và dùng canvas của ADR-0101 (Accepted).

## Danh sách ticket

| #   | Ticket                                                                            |
| --- | --------------------------------------------------------------------------------- |
| 01  | [Hồ sơ DW và loại quyết định](issues/01-ho-so-dw-va-loai-quyet-dinh.md)           |
| 02  | [Hàng đợi chung, bàn giao, cổng duyệt](issues/02-hang-doi-ban-giao-cong-duyet.md) |
| 03  | [Scorecard và nâng hạ tự chủ](issues/03-scorecard-va-nang-ha-tu-chu.md)           |
| 04  | [Màn hình DW](issues/04-man-hinh-dw.md)                                           |
