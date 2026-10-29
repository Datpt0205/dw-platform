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
- Không có tài khoản dịch vụ; org-and-principals/03 sẽ thêm `platform.service_principals` (`.claude/plans/studio/org-and-principals/spec.md:31`). Thiếu: định danh DW lát đầu là chủ thể tối thiểu (D17).
- `ApproveAndResumeService` nhận `decision_guards` theo loại approval và `strict_approval_prefixes` ở composition root (`apps/api/src/dw_api/bootstrap/runtime.py:238-240`), approval không gắn lượt chạy phát một sự kiện outbox `<type>.decided` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:304-305`). Ràng buộc: cổng DW và nâng tự chủ đi qua cửa này.
- Scope của membership là hợp scope của vai trong `platform.roles` (`packages/python/dw_platform/src/dw_platform/adapters/persistence/membership_lookup.py:34-48`). Ràng buộc: `dw.read`, `dw.manage` thêm vào vai bằng migration.
- Offboarding tìm bảng tenant qua catalog, không qua danh sách viết tay (`packages/python/dw_platform/src/dw_platform/adapters/persistence/offboarding.py:193-207`). Ràng buộc: bảng mới có `tenant_id` được xuất và xóa, thứ tự xóa theo khóa ngoại.
- Sổ sử dụng theo lượt gọi đã bị gỡ (`db/migrations/versions/0013_drop_model_usage_ledger.py:1`); chi phí chỉ còn ở telemetry (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/usage_recorders.py:1-8`). Thiếu: scorecard cần chi phí theo lượt chạy.

## Mục tiêu

### R1 — Hồ sơ Digital Worker

Business Owner và Technical Owner có một DW là dữ liệu của công ty, đứng tên chính nó.

- R1.1 KHI người giữ `dw.manage` gửi `POST /v1/digital-workers` hợp lệ, API PHẢI ghi một dòng `platform.digital_workers` trạng thái `draft` với id do server sinh, `tenant_id` và `workspace_id` từ access context, và trả 201 cùng hồ sơ.
- R1.2 NẾU một trong bốn người (`business_owner_id`, `technical_owner_id`, `work_assigner_id`, `validator_id`) không có membership trong workspace của DW, THÌ API PHẢI trả 422 `owner_not_member` và không ghi dòng nào.
- R1.3 NẾU `allowed_tools` nêu một công cụ không có trong sổ công cụ của nền tảng, hay `work_kinds` rỗng, THÌ API PHẢI trả 422 `tool_unknown` hay `work_kinds_empty` và không ghi dòng nào.
- R1.4 Bộ dựng ngữ cảnh lượt chạy DW PHẢI đặt `actor_id` và `requested_by` bằng id của DW và tập scope bằng hợp các `required_scopes` của công cụ trong `allowed_tools`, không bao giờ scope của người tạo hay người đưa việc vào.
- R1.5 NẾU người gọi không giữ `dw.read` trong workspace của DW hay DW thuộc tenant khác, THÌ `GET /v1/digital-workers/{id}` PHẢI trả 404 `not_found` như id không tồn tại.
- R1.6 NẾU người đổi trạng thái DW qua `POST /v1/digital-workers/{id}/state` không phải Business Owner hay Technical Owner của DW, THÌ API PHẢI trả 403 `not_dw_owner` và không đổi gì.
- R1.7 NẾU chuyển trạng thái không thuộc `draft→operating`, `operating→paused`, `paused→operating` hay `*→retired` (trừ `retired`), THÌ API PHẢI trả 409 `invalid_transition` và không đổi gì.
- R1.8 KHI trạng thái DW đổi, API PHẢI ghi một dòng `platform.audit_events` `dw.state_changed` đứng tên người đổi, cùng giao dịch.

### R2 — Loại quyết định và mức tự chủ có hiệu lực

Business Owner đặt trần và mức đã kiếm cho từng loại quyết định; runtime dùng mức thấp nhất (ADR-0128 (Proposed) quyết 3).

- R2.1 KHI một DW được tạo, API PHẢI ghi một dòng `platform.dw_decision_classes` cho mỗi loại quyết định trong thân yêu cầu, với `key`, `effect_level`, `reversible`, `ceiling` và `earned_level`.
- R2.2 NẾU `earned_level` của một loại cao hơn `ceiling` của nó, THÌ API PHẢI trả 422 `above_ceiling` và không ghi dòng nào.
- R2.3 `DecisionAutonomy.effective_level` PHẢI trả mức thấp nhất giữa `ceiling`, `earned_level` và `platform.tenants.max_autonomy_level`, đọc lúc được hỏi, và trả `A0` khi một trong ba không đọc được hay loại quyết định không tồn tại.
- R2.4 `DecisionAutonomy.requires_person` PHẢI quyết bằng cùng thang của `autonomy.py`, với loại `external` có `reversible` xếp vào bậc ngoài có khóa chống lặp, và với loại `critical` luôn đòi người ở mọi mức.

### R3 — Hàng đợi việc chung

Người và DW làm trên một hàng đợi, mỗi việc có đúng một người giữ (ADR-0128 (Proposed) quyết 6).

- R3.1 KHI `WorkQueue.enqueue` nhận một việc cho một DW, cửa hàng đợi PHẢI ghi một dòng `platform.work_items` trạng thái `open`, `holder_kind = 'digital_worker'`, `holder_id` là id DW.
- R3.2 NẾU `kind` của việc không có trong `work_kinds` của DW nhận, THÌ cửa hàng đợi PHẢI từ chối `work_kind_outside_mandate` và không ghi dòng nào.
- R3.3 NẾU payload không khớp JSON Schema khai cho `kind` đó qua `WorkKindSchemas`, hay không có schema cho `kind`, THÌ cửa hàng đợi PHẢI từ chối `payload_invalid` và không ghi dòng nào.
- R3.4 NẾU việc cùng `(tenant_id, kind, source_key)` đã có, THÌ cửa hàng đợi PHẢI trả việc đã có và không ghi dòng thứ hai.
- R3.5 `GET /v1/work-items` PHẢI trả cho người giữ `dw.read` mọi việc của workspace (người và DW giữ), lọc được theo `status` và `holder_kind`, phân trang keyset theo `(created_at, id)` qua một index dẫn bằng `tenant_id`.
- R3.6 Lane `dw_work` của worker PHẢI nhận mỗi việc `open` do một DW `operating` giữ đúng một lần (`FOR UPDATE SKIP LOCKED`), chuyển nó sang `in_progress` và ghi `run_id` của lượt chạy mà nó yêu cầu, trong một giao dịch.
- R3.7 TRONG KHI DW giữ việc không ở trạng thái `operating`, lane `dw_work` PHẢI để việc ở `open` và không yêu cầu lượt chạy nào.
- R3.8 NẾU người gọi `POST /v1/work-items/{id}/complete` không phải người đang giữ việc, THÌ API PHẢI trả 403 `not_holder` và không đổi gì.

### R4 — Bàn giao với gói

DW dừng và trao việc cho một người kèm gói bàn giao (YC121, ADR-0128 (Proposed) quyết 7).

- R4.1 KHI `WorkQueue.hand_off` được gọi cho một việc DW đang giữ, cửa hàng đợi PHẢI chuyển việc sang `handed_off`, đổi người giữ sang người nhận (`holder_kind = 'person'`) và ghi gói `{problem, context, tried, recommendation}`, cùng một dòng audit `work_item.handed_off` đứng tên DW, trong một giao dịch.
- R4.2 NẾU gói thiếu một trong bốn trường, hay một trường rỗng hoặc dài quá 4.000 ký tự, THÌ cửa hàng đợi PHẢI từ chối `handoff_packet_invalid` và không đổi việc.
- R4.3 NẾU người nhận không có membership trong workspace của việc, THÌ cửa hàng đợi PHẢI từ chối `handoff_target_invalid` và không đổi việc.

### R5 — Cổng duyệt theo loại quyết định

Một đề xuất trên mức hiệu lực chờ đúng người duyệt, qua cửa phê duyệt có sẵn (ADR-0128 (Proposed) quyết 8).

- R5.1 KHI `DecisionGate.check` được gọi cho một loại quyết định mà `requires_person` đúng, cổng PHẢI trả lệnh mở approval loại `dw.decision` với payload gồm `dw_id`, `decision_class`, `effective_level`, `proposal` và `eligible_deciders` (Validator, Business Owner) đọc từ hồ sơ DW lúc đó.
- R5.2 KHI `requires_person` sai, cổng PHẢI trả `auto` và ghi một dòng audit `dw.decision.auto` với `decision_class` và `effective_level`, đứng tên DW.
- R5.3 NẾU người quyết một approval `dw.decision` không có trong `eligible_deciders` của nó, THÌ `ApproveAndResumeService.decide` PHẢI trả 409 `not_eligible_decider` và không ghi quyết định nào.

### R6 — Dừng một Digital Worker

Tạm dừng có hiệu lực ở cửa hiệu ứng, không chỉ ở lane (ADR-0128 (Proposed) quyết 10).

- R6.1 TRONG KHI DW ở trạng thái khác `operating`, `ToolExecutor` PHẢI từ chối mọi lời gọi công cụ của lượt chạy có `actor_id` là id DW đó với `dw_not_operating`, không gọi công cụ và ghi lần từ chối vào `platform.tool_executions`.

### R7 — Scorecard

Business Owner đọc DW làm được gì từ dữ liệu, không từ lời DW tự báo (YC122).

- R7.1 `GET /v1/digital-workers/{id}/scorecard?days=<n>` PHẢI trả, cho các việc tạo trong `n` ngày gần nhất (Asia/Ho_Chi_Minh), số việc theo trạng thái, tỷ lệ `done`, tỷ lệ `handed_off`, số approval `dw.decision` được duyệt và bị từ chối, và tổng `model_cost_usd` của lượt chạy, tính bằng truy vấn trên `platform.work_items`, `platform.approval_requests`, `platform.approval_decisions` và `platform.worker_runs`.
- R7.2 NẾU `days` ngoài 1-90, THÌ API PHẢI trả 422 `days_out_of_range`; 1 và 90 thì nhận.
- R7.3 KHI một lời gọi model của lượt chạy DW xong, bộ ghi chi phí PHẢI cộng chi phí ước tính vào `platform.worker_runs.model_cost_usd` của lượt đó bằng một câu `UPDATE` cộng dồn.

### R8 — Nâng và hạ mức đã kiếm

Business Owner đổi mức đã kiếm; nâng cần người thứ hai, hạ có hiệu lực ngay (YC123, ADR-0128 (Proposed) quyết 5).

- R8.1 KHI Business Owner hay Technical Owner hạ `earned_level` qua `POST /v1/digital-workers/{id}/decision-classes/{key}/autonomy`, API PHẢI ghi mức mới và dòng audit `dw.autonomy.lowered` trong một giao dịch, và cổng đọc mức mới ở lần hỏi kế tiếp.
- R8.2 KHI Business Owner nâng `earned_level`, API PHẢI mở một approval `dw.autonomy.raise` không gắn lượt chạy và không đổi mức; handler của `dw.autonomy.raise.decided` PHẢI ghi mức mới chỉ khi quyết định là duyệt.
- R8.3 NẾU người quyết `dw.autonomy.raise` là người đề nghị hay không ghi lý do, THÌ `ApproveAndResumeService.decide` PHẢI trả 409 và không ghi quyết định nào.
- R8.4 NẾU mức đề nghị cao hơn `ceiling` của loại quyết định, THÌ API PHẢI trả 422 `above_ceiling` và không mở approval.
- R8.5 NẾU người nâng không phải Business Owner, hay người hạ không phải Business Owner hay Technical Owner, THÌ API PHẢI trả 403 `not_dw_owner` và không đổi gì.

### R9 — Màn hình

Business Owner, Validator và người làm việc thấy DW, hàng đợi và thẻ duyệt trên web (antd).

- R9.1 Trang `/digital-workers` PHẢI liệt kê DW của workspace với tên, trạng thái, mandate rút gọn và số việc đang mở.
- R9.2 Trang `/digital-workers/[id]` PHẢI hiện hồ sơ, bốn người, các loại quyết định với trần, mức đã kiếm và mức hiệu lực, scorecard 30 ngày và cây quy trình chỉ đọc.
- R9.3 Trang `/work` PHẢI hiện hàng đợi chung lọc theo trạng thái và loại người giữ, cùng gói bàn giao của việc `handed_off`.
- R9.4 Trang `/approvals` PHẢI hiện approval `dw.decision` thành một thẻ có tên DW, loại quyết định, mức hiệu lực và đề xuất.
- R9.5 NẾU API trả 403 hay 404 cho một trang DW, THÌ trang PHẢI hiện trạng thái không có quyền hay không tìm thấy và không hiện dữ liệu nào.

## Trong phạm vi

- Bảng `platform.digital_workers`, `platform.dw_decision_classes`, `platform.work_items`; cột `platform.worker_runs.model_cost_usd`; scope `dw.read`, `dw.manage`.
- Route `/v1/digital-workers` (tạo, danh sách, đọc, đổi trạng thái, scorecard, đổi mức), `/v1/work-items` (danh sách, đọc, xong).
- Port `DecisionAutonomy`, `DecisionGate`, `WorkQueue`, `WorkKindSchemas` (do bên dùng khai), lane `dw_work`, guard `dw.decision`, handler `dw.autonomy.raise.decided`.
- Trang web `/digital-workers`, `/digital-workers/[id]`, `/work`, thẻ `dw.decision` trên `/approvals`.

## Ngoài phạm vi

| Việc                                                                           | Vì sao                                           | Chủ                      |
| ------------------------------------------------------------------------------ | ------------------------------------------------ | ------------------------ |
| Chạy tài liệu quy trình của DW                                                 | bộ máy quy trình là một spec riêng               | `wf-lite`                |
| Gói Marketing, JSON Schema của lead, cửa nhận lead                             | nội dung của DW đầu tiên, không phải lõi         | `leadcare`               |
| `platform.service_principals` sau id DW                                        | D17: chủ thể tối thiểu trước, chuẩn hóa sau      | org-and-principals/03    |
| Sổ sử dụng theo lượt gọi làm nguồn chi phí của scorecard                       | sổ chưa có; R7.3 ghi chi phí của chính lượt chạy | usage-and-limits/02      |
| KPI có đích và mức dịch vụ của DW                                              | lát đầu chỉ đo; đích đặt sau khi có số           | đợt sau                  |
| A5                                                                             | ADR-0128 (Proposed) quyết 4                      | không làm                |
| Tenant tự dựng DW và quy trình trong Studio, cổng chất lượng trước `operating` | đường C đi trước Studio (D17)                    | agent-lifecycle, đợt sau |
| Work Assigner giao việc ngoài mandate                                          | ADR-0128 (Proposed) mục Open 2                   | đợt sau                  |

## Dữ liệu

- `platform.digital_workers`: `id uuid PK`; `tenant_id uuid NOT NULL` FK `platform.tenants` `ON DELETE RESTRICT`; `workspace_id uuid NOT NULL` FK `platform.workspaces` `ON DELETE RESTRICT`; `key text NOT NULL` CHECK `^[a-z][a-z0-9_]{1,39}$`, UNIQUE `(tenant_id, key)`; `name text NOT NULL` 1-120 ký tự; `mandate text NOT NULL` 1-2.000 ký tự; `work_kinds text[] NOT NULL` CHECK `cardinality >= 1`; `allowed_tools text[] NOT NULL`; `workflow_key text NOT NULL`; `workflow_version text NOT NULL` semver; `parameters jsonb NOT NULL DEFAULT '{}'`; `state text NOT NULL DEFAULT 'draft'` CHECK trong `draft, operating, paused, retired`; bốn cột người `uuid NOT NULL` FK `platform.users` `ON DELETE RESTRICT`, mỗi cột một index; `created_by uuid NOT NULL`; `created_at`, `updated_at timestamptz NOT NULL`, trigger `updated_at` nhường giá trị câu lệnh nêu.
- `platform.dw_decision_classes`: PK `(dw_id, key)`; `tenant_id`, `workspace_id` NOT NULL; `dw_id` FK `platform.digital_workers` `ON DELETE CASCADE`; `key text` CHECK `^[a-z][a-z0-9_.]{1,63}$`; `effect_level text NOT NULL` CHECK trong `none, internal, external, critical`; `reversible boolean NOT NULL`; `ceiling`, `earned_level text NOT NULL` CHECK trong `A0..A4`, CHECK `earned_level <= ceiling` theo thứ tự mức; `updated_at`.
- `platform.work_items`: `id uuid PK`; `tenant_id`, `workspace_id` NOT NULL; `kind text NOT NULL`; `source_key text NOT NULL`, UNIQUE `(tenant_id, kind, source_key)`; `payload jsonb NOT NULL`; `holder_kind text NOT NULL` CHECK trong `digital_worker, person`; `holder_id uuid NOT NULL`; `dw_id uuid NULL` FK `platform.digital_workers` `ON DELETE RESTRICT`, index; `status text NOT NULL` CHECK trong `open, in_progress, waiting_approval, waiting_timer, handed_off, done, failed, cancelled`; `run_id uuid NULL`, index; `wake_at timestamptz NULL`, CHECK `(status = 'waiting_timer') = (wake_at IS NOT NULL)`, index một phần `(wake_at) WHERE status = 'waiting_timer'`; `handoff jsonb NULL`; `created_at`, `updated_at`, `closed_at timestamptz`; index `(tenant_id, workspace_id, created_at DESC, id DESC)` và index một phần `(dw_id, created_at) WHERE status = 'open'` cho lane.
- `platform.worker_runs.model_cost_usd numeric(12,6) NOT NULL DEFAULT 0` CHECK `>= 0`.
- RLS: ba bảng ENABLE và FORCE, policy `tenant AND (workspace OR current_setting('app.workspace_scope') = 'tenant')` của `CLAUDE.md` "Tenancy and authorization"; quyền `dw_app` SELECT, INSERT, UPDATE; `DELETE` không cấp (offboarding xóa bằng vai của nó).

## API

| Route                                                           | Scope                  | Lỗi chính                                                                   |
| --------------------------------------------------------------- | ---------------------- | --------------------------------------------------------------------------- |
| `POST /v1/digital-workers`                                      | `dw.manage`            | 422 `owner_not_member`, `tool_unknown`, `work_kinds_empty`, `above_ceiling` |
| `GET /v1/digital-workers`, `GET /v1/digital-workers/{id}`       | `dw.read`              | 404 `not_found`                                                             |
| `POST /v1/digital-workers/{id}/state`                           | `dw.manage` và chủ DW  | 403 `not_dw_owner`, 409 `invalid_transition`                                |
| `GET /v1/digital-workers/{id}/scorecard?days=`                  | `dw.read`              | 422 `days_out_of_range`                                                     |
| `POST /v1/digital-workers/{id}/decision-classes/{key}/autonomy` | `dw.manage` và chủ DW  | 403 `not_dw_owner`, 422 `above_ceiling`; 202 khi mở approval nâng           |
| `GET /v1/work-items`, `GET /v1/work-items/{id}`                 | `dw.read`              | 404 `not_found`                                                             |
| `POST /v1/work-items/{id}/complete`                             | `dw.read` và người giữ | 403 `not_holder`, 409 `invalid_transition`                                  |

Mọi route theo app-standards (problem+json, `Idempotency-Key` ở route ghi, keyset có kiểu). Scope `dw.read` cấp cho mọi vai thành viên, `dw.manage` cho `org_admin`, bằng migration.

## Màn hình

R9. Ant Design v6, thanh trên cùng có mục "Digital Worker" và "Hàng đợi việc"; ngày giờ qua `lib/dates.ts`. Cây quy trình chỉ đọc vẽ bằng antd (không `@xyflow/react`, đường đó chỉ cho `apps/web/app/studio/**/canvas/**`).

## Kiểm soát

| #     | Kiểm soát                                                                   | Yêu cầu    | Test âm                                                                                                                  |
| ----- | --------------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------ |
| DWK1  | bốn người của DW phải có membership trong workspace của DW                  | R1.2       | tạo DW với Validator là user của tenant B: 422 `owner_not_member`, đếm `digital_workers` không đổi                       |
| DWK2  | scope của lượt chạy DW tính từ công cụ, actor là id DW                      | R1.4       | người tạo giữ `admin.*`: ngữ cảnh lượt chạy chỉ có scope của công cụ, `actor_id` là id DW                                |
| DWK3  | DW, loại quyết định, việc của tenant khác hay workspace khác không đọc được | R1.5, R3.5 | tenant B đọc id DW và id việc của tenant A: 404; danh sách của B không có dòng của A; đọc thẳng bảng không scope: 0 dòng |
| DWK4  | chỉ Business Owner hay Technical Owner đổi trạng thái                       | R1.6       | người giữ `dw.manage` không là chủ gọi `/state`: 403, trạng thái không đổi                                               |
| DWK5  | chuyển trạng thái ngoài bảng bị từ chối                                     | R1.7       | `retired→operating`: 409, trạng thái không đổi                                                                           |
| DWK6  | mức hiệu lực là mức thấp nhất của ba, thiếu thì `A0`                        | R2.3       | trần tenant A1, đã kiếm A3: `A1`; loại không tồn tại: `A0`                                                               |
| DWK7  | `critical` luôn đòi người, ngoài đảo được xếp bậc có khóa                   | R2.4       | loại `critical` ở A4: `requires_person` đúng; `external` không đảo được ở A3: đúng; đảo được ở A3: sai                   |
| DWK8  | việc ngoài mandate bị từ chối                                               | R3.2       | `enqueue` kind không thuộc `work_kinds`: từ chối, đếm `work_items` không đổi                                             |
| DWK9  | payload sai schema hay không có schema bị từ chối                           | R3.3       | payload thiếu trường bắt buộc, và kind không có schema: từ chối, không dòng nào                                          |
| DWK10 | mỗi việc được nhận đúng một lần                                             | R3.6       | hai lane chạy song song trên một việc: đúng một lượt chạy được yêu cầu, `run_id` một giá trị                             |
| DWK11 | DW không `operating` không nhận việc                                        | R3.7       | DW `paused` với việc `open`: lane chạy xong, việc vẫn `open`, không lượt chạy nào                                        |
| DWK12 | chỉ người giữ đánh dấu xong                                                 | R3.8       | người khác gọi `/complete`: 403, trạng thái không đổi                                                                    |
| DWK13 | gói bàn giao đủ bốn trường                                                  | R4.2       | thiếu `recommendation`: từ chối, việc vẫn `in_progress`                                                                  |
| DWK14 | người nhận bàn giao phải là thành viên workspace                            | R4.3       | người nhận của tenant B: từ chối, người giữ không đổi                                                                    |
| DWK15 | chỉ người trong `eligible_deciders` quyết `dw.decision`                     | R5.3       | người giữ `approvals.decide` không là Validator hay Business Owner: 409, không dòng quyết định                           |
| DWK16 | DW không `operating` không gây hiệu ứng ở cửa công cụ                       | R6.1       | lượt chạy của DW `paused` gọi công cụ qua `ToolExecutor`: từ chối `dw_not_operating`, công cụ không chạy                 |
| DWK17 | nâng mức không đổi gì trước khi người thứ hai duyệt                         | R8.2       | nâng: mức vẫn cũ, có một approval; từ chối approval: mức vẫn cũ                                                          |
| DWK18 | người đề nghị nâng không tự duyệt                                           | R8.3       | Business Owner duyệt approval nâng của chính mình: 409, mức không đổi                                                    |
| DWK19 | mức đề nghị không vượt trần                                                 | R8.4       | đề nghị A4 với trần A3: 422, không approval                                                                              |
| DWK20 | chỉ chủ DW nâng hay hạ                                                      | R8.5       | Validator hạ mức: 403, mức không đổi                                                                                     |
| DWK21 | trang DW không hiện dữ liệu khi API từ chối                                 | R9.5       | API mock trả 403: trang không có hàng dữ liệu nào                                                                        |

## Tiêu chí thành công

- Góp vào KQ15: Business Owner thấy DW chăm sóc lead làm việc trên màn hình, với scorecard tính từ lịch sử.

## Tiêu chí xong

- Mọi tiêu chí R có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (`scripts/mutate.py`).
- `make test-unit test-contract test-architecture` xanh và integration của `dw_platform`, `dw_agent_runtime`, `apps/api`, `apps/worker` xanh.

## Phụ thuộc

- ADR-0128 (Proposed), ADR-0103 (Accepted), ADR-0113 (Accepted) cho hàng đợi Postgres là chính dòng việc.
- `ApproveAndResumeService` với `decision_guards` và `strict_approval_prefixes`, `ToolExecutor`, `platform.tenants.max_autonomy_level`, `autonomy.py`.
- `wf-lite` gọi `DecisionGate`, `WorkQueue.hand_off` và khai `WorkKindSchemas` qua tài liệu của gói; `leadcare` gọi `WorkQueue.enqueue`.
- Kiểm lại khi: org-and-principals/03 thêm `platform.service_principals` → R1.4 và cột `requested_by`; usage-and-limits/02 có sổ → R7.3 chuyển nguồn; ADR-0128 (Proposed) đổi trạng thái → cả spec.

## Câu hỏi còn mở

- Q1. A5 có nghĩa gì khác A4 trên nền tảng này? Chủ: Đạt. Không đổi: năm mức A0-A4 của kernel trong lát này.

## Quyết định

- 29/10/2026 (agent, tạm): Id của DW là định danh của nó (chủ thể tối thiểu của D17), không tạo dòng `platform.users`, vì một dòng user là một danh tính đăng nhập được. Nếu sai thì: tạo `platform.service_principals` tối thiểu ở dw/01 và org-and-principals/03 mở rộng bảng đó.
- 29/10/2026 (agent, tạm): Loại quyết định của DW nêu trong thân yêu cầu tạo; wf-lite kiểm lúc chạy rằng mọi loại mà tài liệu quy trình dùng đều có trên DW, vì dw/01 đi trước wf-lite/01 theo hàng đợi. Nếu sai thì: API tạo DW đọc loại quyết định từ tài liệu đã ghim và thân yêu cầu chỉ nêu mức.
- 29/10/2026 (agent, tạm): Mức hiệu lực đọc ở lúc cổng hỏi, không đóng dấu lúc lượt chạy bắt đầu, nên hạ mức có hiệu lực cả với lượt đang chạy ở cổng kế tiếp. Nếu sai thì: đóng dấu mức lên lượt chạy và R8.1 chỉ áp lượt mới.
- 29/10/2026 (agent, tạm): Chi phí của scorecard là cột `model_cost_usd` của lượt chạy cho tới khi sổ sử dụng có; khi đó sổ là chủ và cột thành dẫn xuất hay bị bỏ. Nếu sai thì: scorecard không có cột chi phí cho tới usage-and-limits/02.
- 29/10/2026 (agent, tạm): Cây quy trình chỉ đọc vẽ bằng antd, không `@xyflow/react`. Nếu sai thì: trang chuyển dưới `apps/web/app/studio/**/canvas/**` và dùng canvas của ADR-0101 (Accepted).

## Danh sách ticket

| #   | Ticket                                                                            |
| --- | --------------------------------------------------------------------------------- |
| 01  | [Hồ sơ DW và loại quyết định](issues/01-ho-so-dw-va-loai-quyet-dinh.md)           |
| 02  | [Hàng đợi chung, bàn giao, cổng duyệt](issues/02-hang-doi-ban-giao-cong-duyet.md) |
| 03  | [Scorecard và nâng hạ tự chủ](issues/03-scorecard-va-nang-ha-tu-chu.md)           |
| 04  | [Màn hình DW](issues/04-man-hinh-dw.md)                                           |
