# 06 — Cổng chất lượng mô phỏng với bộ an ninh nền tảng và ca kịch bản tất định của quy trình

Status: needs-triage
Blocked by: 02, 04, .claude/plans/studio/workflow-engine/issues/04-lan-studio-runs.md, .claude/plans/studio/compliance-pdpl/issues/05-phan-tich-bo-ba-khi-xuat-ban.md, .claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md, .claude/plans/studio/usage-and-limits/issues/03-han-muc-giu-truoc-va-quyet-toan.md, .claude/plans/studio/telemetry-and-audit/issues/01-otel-khong-noi-dung-va-metric.md
Area: studio
Yêu cầu: R1.9, R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, R4.7, R4.8, R4.9, R4.10, R4.11, R4.12, R4.13, R4.14, R4.15, R4.16, R4.17, R4.18, R4.19, R4.20, R5.1, R5.6, R5.7, R6.1, R6.2, R6.3, R10.2, R10.3, AL4, AL7, AL8, AL9, AL10, AL21, AL22, AL23, AL24, AL26, AL27, AL30, AL31, AL32, AL33

## Mục tiêu

Lượt kiểm định chạy ở chế độ Mô phỏng với Bộ kiểm định an ninh nền tảng (đạt 100%; bộ đề của tenant là W2) và, với một
quy trình, mọi ca kịch bản tất định của thành phần (đầu vào, quyết định giả lập, kết quả giả lập ghim theo Bước, kết quả
mong đợi, khẳng định CEL), chấm không gọi model, dưới trần chi phí giữ trước qua `LimitsPort`; mỗi lần thử đọc dưới giới
hạn tạm của Bản ứng viên, giao với quyền người gửi; Kiểm định thử bản Nháp đọc dưới giới hạn tạm của bản Nháp, giao với
quyền người xin; cổng không mở phê duyệt khi Phân tích năng lực thiếu hay chưa đạt; cổng đạt thì mở phê duyệt phát hành
qua `LifecycleService` của ticket 04; yêu cầu phê duyệt quá hạn bị hủy; Lượt kiểm định chỉ đọc được theo workspace sở hữu
của thành phần và chỉ lượt xóa của offboarding xóa được nó (spec R1.9, R4, R5.1, R5.6, R5.7, R6, R10; YC70, YC115;
V4.37). Phân tích năng lực do compliance-pdpl giữ và trả 422 lúc gửi kiểm định; lát này chỉ đọc kết quả đã ghi làm chốt
chặn. Phát hành hai người, handler `.decided` và route đọc Bản ứng viên là của ticket 04; màn duyệt là của ticket 07.

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên): `studio.gate_runs` (`status` CHECK `queued`, `running`, `passed`,
   `failed`, `error`, `cancelled`; `purpose` CHECK `gate`, `dry`; `artifact_id uuid NOT NULL`, thành phần được kiểm
   định, kể cả thành phần của bản Nháp ở dòng `dry`, FK ghép `(tenant_id, artifact_id)` tới `studio.artifacts
(tenant_id, id)` (`uq_artifacts_tenant_id_id` của tenant-config/02) ON DELETE RESTRICT, có index
   `(tenant_id, artifact_id)` (spec R1.9, R4.10); khóa bằng chứng `effective_hash`, `gate_policy_ref`,
   `security_suite_ref`, `scenario_set_hash text NOT NULL` (mã băm của tập ca kịch bản đã chạy, bước 7; mã băm của tập
   rỗng với agent), danh sách mã băm bộ đề của tenant (rỗng ở W1); `definition_hash` cho trigger giai đoạn;
   `spend_cap_usd`, `spent_usd`, `resolved_at_gate` jsonb, `verdict` jsonb; `created_at timestamptz NOT NULL`;
   `uq_gate_runs_tenant_id_id UNIQUE (tenant_id, id)`; index `(tenant_id, created_at DESC, id DESC)` cho keyset của
   `GET /api/v1/studio/gate-runs`); `dw_app` có DELETE trên `studio.gate_runs` chỉ dùng được ở lượt xóa của
   offboarding: trigger `studio.guard_gate_run_delete()` BEFORE DELETE từ chối với SQLSTATE 23514 mọi DELETE khi
   `platform.tenants.status` của công ty khác `offboarding` (spec R10.3), cùng hình với
   `platform.guard_control_switch()` của ticket 01; cùng revision thêm FK ghép `(tenant_id, gate_run_id)` của
   `studio.artifact_versions` (cột của ticket 03) tới `studio.gate_runs (tenant_id, id)` ON DELETE RESTRICT có index
   riêng (spec R1.9); `studio.gate_case_results` có `gate_run_id` FK ghép `(tenant_id, gate_run_id)` tới
   `studio.gate_runs (tenant_id, id)` ON DELETE RESTRICT, để một DELETE lên Lượt kiểm định không kéo theo xóa dòng chỉ
   thêm, `case_id text NOT NULL` (mã Câu kiểm định, hay id dòng của ca kịch bản), `category text NOT NULL`,
   `passed boolean NOT NULL`, `reason_code text NULL`, `cost_usd numeric(12,6) NOT NULL` (chi phí của câu, từ
   `Observation` của ticket 02, mà màn duyệt của ticket 07 đọc), và index `(tenant_id, gate_run_id, case_id)` trên bảng
   cha mang khóa ngoại đó và keyset của `GET .../{id}/cases` (CLAUDE.md, Data model rules), phân vùng theo tháng với
   DEFAULT, đăng ký bằng một dòng `platform.time_partitioned_tables` (`append_only = true`), không sửa thân hàm;
   ENABLE/FORCE RLS và policy tenant trên cha và DEFAULT cùng migration; `dw_app` không giữ quyền nào trên partition
   nào, kể cả DEFAULT (DO-02.2), chỉ SELECT, INSERT trên bảng cha. `studio.gate_run_datasets` là W2 cùng bộ đề của
   tenant. Policy drain `app.worker_drain` để lane nhận việc. Cùng thay đổi thêm mảnh
   `configs/policies/retention.d/studio.gate_case_results.yaml` (395 ngày, số tạm UNVERIFIED, bộ xóa DROP PARTITION qua
   `platform.drop_expired_partitions` của usage-and-limits/02, cổng `enforced`) theo định dạng mảnh của
   telemetry-and-audit/01 (telemetry-and-audit:R5.6; H-1), nên studio-skeleton:R3.7 xanh ngay khi đăng ký, không chờ
   ticket nào vì mảnh; một dòng `STUDIO_EXCLUSIONS` cho `studio.gate_case_results` với lý do "xóa khi offboarding bằng
   `platform.purge_tenant_append_only`" (usage-and-limits:R3.10), bước xóa mà usage-and-limits/02 đăng ký vào sổ bước
   xóa của lane `offboarding` và khai mọi bảng `append_only` của sổ phân vùng. Thứ tự xóa không có danh sách viết tay:
   sổ bước xóa ở composition root của worker (`.claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md`;
   foundations-hardening:R11.4) chạy mỗi bước sau mọi bước xóa bảng giữ một khóa ngoại `RESTRICT` hay `NO ACTION` tới bảng
   của nó, suy từ `pg_constraint` của cơ sở dữ liệu đang chạy, và từ chối lượt xóa trước câu xóa đầu khi hai bước khai
   cùng một bảng hay các cạnh tạo vòng (foundations-hardening:R11.5; H-2). `studio.gate_runs` và
   `studio.workflow_scenarios` chỉ cần câu `DELETE` chung, nên ticket này không đăng ký bước nào: bước mặc định nhận
   chúng từ danh mục xóa, và ba cạnh `RESTRICT` mới (`gate_run_id` của `studio.artifact_versions`, `gate_run_id` của
   `studio.gate_case_results`, `artifact_id` của chính `studio.gate_runs`) vào thứ tự từ `pg_constraint`, nên
   `studio.gate_case_results` và `studio.artifact_versions` đi trước `studio.gate_runs`, và `studio.gate_runs` đi trước
   `studio.artifacts`; `studio.workflow_scenarios` mất dòng qua `CASCADE` từ `studio.artifacts` hay bị bước mặc định
   xóa, như R11.4 cho phép; test phủ của studio-skeleton:R4.2 đọc sổ và các cạnh đó, đỏ khi một bước đi trái cạnh
   (spec R10.2). `studio.gate_runs`,
   `studio.gate_case_results` và `studio.workflow_scenarios` không có `workspace_id`: mỗi bảng một dòng trong danh sách
   bảng toàn tenant của `test_rls_coverage.py`, với lý do "Lượt kiểm định đi theo thành phần toàn tenant mà nó kiểm định,
   đọc theo `owning_workspace_id` của thành phần ở `artifact_id`", "kết quả từng câu là con của Lượt kiểm định
   (`gate_run_id`), đọc qua nó" và "ca kịch bản đi theo thành phần quy trình toàn tenant, đọc theo `owning_workspace_id`
   của thành phần ở `artifact_id`" (studio-skeleton:R9.1; CLAUDE.md, Tenancy and authorization).
2. Lane `studio_gate` (tối đa một Lượt kiểm định mỗi tenant, một `ReapTarget` cho lượt treo): mỗi lần thử là một run
   `run_mode='simulate'` xin qua `RunRequestService` dưới danh nghĩa người gửi Bản ứng viên (`submitted_by`; ngữ cảnh
   truy cập đóng dấu của người đó, không của lane), để `RunRequestService` dẫn giới hạn tạm từ bao đóng niêm phong của
   Bản ứng viên, ghi dưới `(version_id, definition_hash)` cho riêng lượt đó, và lần thử đọc dưới giới hạn tạm giao với
   quyền của người gửi; việc dẫn, ghi, xóa giới hạn tạm và luật RLS chỉ nhận nó ở `simulate` là của workflow-engine và
   record-access (spec R4.12; workflow-engine:R3.15, workflow-engine:R3.14, record-access:R6.11, record-access:R6.12,
   record-access:R6.13); test danh nghĩa và phần đọc như ở bước 4, với một Bản ứng viên quy trình có Bước
   `data.object.*` giả của fixture; lane cấp cho mỗi Bước `human.approval` của lần thử quyết định `approved` hay
   `rejected` (từ vựng của workflow-nodes:R9.9, bước 3) mà Câu kiểm định hay ca kịch bản khai, Bước không chờ người
   thật, ghi `studio.step.approval.simulated` và không mở dòng `platform.approval_requests` nào (spec R4.7; hành vi của
   Bước là của workflow-nodes, ticket này thử hợp đồng với một Bước giả); ở ToolExecutor chế độ chạy đứng trước phê
   duyệt của công cụ (tools-and-skills:R2.6), nên công cụ `approval_policy: always` trong lần thử không mở yêu cầu phê
   duyệt thật (spec R4.3). Lượt kiểm định xin lease `purpose` `eval_offline` qua `LimitsPort` của usage-and-limits/03
   với trần mỗi lượt `max_gate_worst_case_usd`, mỗi lần thử, kể cả lần thử của ca kịch bản, dùng lease đó với trần
   `max_trial_cost_usd`; không đọc `profile.max_cost_usd_per_run` (DO-21.4). Trước lời gọi model đầu tiên: chi phí xấu
   nhất (mọi lần thử của Bộ an ninh và của ca kịch bản nhân trần mỗi lần thử) vượt trần mỗi lượt, hay `LimitsPort` từ
   chối lease → Lượt kiểm định `error` với `limit_exceeded`, không run nào (spec R4.4). Audit
   `studio.gate_run.started`, `studio.gate_run.completed` (actor `system:studio_gate`); thông báo người gửi. Cổng đạt
   (Bộ an ninh 100%, mọi ca kịch bản đạt, chốt chặn của bước 5 qua) → lane gọi `LifecycleService` của ticket 04 đưa
   phiên bản `evaluating → awaiting_approval` và mở yêu cầu phê duyệt `studio.publish.<kind>` trong cùng giao dịch, với
   cùng payload `author_ids` (spec R5.1); cổng trượt → phiên bản về `draft`.
3. Bộ sinh Bộ kiểm định an ninh nền tảng ở `configs/evals/studio_security_suite@1.0.0.yaml` và Chính sách cổng ở
   `configs/policies/studio_gate@1.0.0.yaml`, chỉ các trường có bên đọc ở W1 (DO-29.1): `security_pass_rate` cố định
   1.0, `scenario_pass_rate` cố định 1.0 (bên đọc: luật ca kịch bản của `evaluate_gate`, bước 7), `pass_k` = 3,
   `max_trial_cost_usd` = 0.10, `max_gate_worst_case_usd` = 10, `publish_approval_ttl_days` = 14; `min_cases_total`,
   `pass_rate_min`, `stale_draft_days` vào chính sách ở W2 cùng bên đọc. Cả hai ghim trong release manifest;
   `scripts/release_manifest.py` đã được usage-and-limits/02 sửa trước (nối qua usage-and-limits/03). Mỗi Câu kiểm định
   chạm một Bước `human.approval` khai quyết định giả lập trong `input` theo từ vựng `approved` hay `rejected` mà
   workflow-nodes:R9.9 làm chủ; câu thiếu khai báo đó bị bộ sinh từ chối. Bộ chấm `studio.*` hợp nhất bằng
   `merge_graders` ở composition root của worker; `dw_evals` không biết chúng. Lane hết hạn phê duyệt phát hành, bên đọc
   của `publish_approval_ttl_days`: hủy yêu cầu `studio.publish.*` quá hạn, đưa phiên bản về `draft` qua
   `LifecycleService`, audit qua `lane_audit_event` với actor `system:<lane>` vì lane tự làm (spec R5.7).
4. Route `POST /api/v1/studio/{agents|workflows}/{artifact_id}/versions/{version_id}/dry-evaluations`
   (`studio.evals.run`) nhận phiên bản `draft` (spec R4.8): lane chạy Kiểm định thử, dòng `studio.gate_runs` có
   `purpose` `dry`, với trần và lease `eval_offline` của bước 2, và với một bản Nháp quy trình cả ca kịch bản của thành
   phần như bước 7 (spec R4.20); mỗi lần thử là một run `run_mode='simulate'` có gốc là bản Nháp, xin qua
   `RunRequestService`, nơi bản kê ghim giai đoạn `draft` và mã băm tạm của nội dung nháp và bộ kiểm trả mọi lỗi của
   loại chạy trên nội dung đó (workflow-engine:R3.9, workflow-engine:R3.11; tenant-config:R6.1; ADR-0109 (Accepted)
   quyết 6); graph biên dịch theo mã băm ghim (workflow-engine:R4.2 cho quy trình; agent-builder:R3.1,
   agent-builder:R3.3 cho agent, ADR-0117 (Accepted) quyết 5). Lane xin mỗi lần thử dưới danh nghĩa người xin Kiểm định
   thử (ngữ cảnh truy cập đóng dấu của người đó, không của lane hay người gửi nào khác), để `RunRequestService` dẫn ra
   giới hạn tạm từ bao đóng của bản Nháp, ghi dưới `(version_id, pinned_hash)` cho riêng lượt đó, và lần thử đọc dưới
   giới hạn tạm giao với quyền của người xin; việc dẫn, ghi, xóa giới hạn tạm và luật RLS chỉ nhận nó ở `simulate` là
   của workflow-engine và record-access (spec R4.11; workflow-engine:R3.13, workflow-engine:R3.14,
   record-access:R6.12, record-access:R6.13; ADR-0111 (Accepted) quyết 3). Test danh nghĩa của lần thử với một cửa giả
   ghi danh nghĩa nó nhận, và phần đọc trên `RunRequestService` thật với một bản Nháp quy trình có Bước `data.object.*`
   (loại node giả của fixture, như workflow-engine/03 dùng, vì ticket này không chờ workflow-nodes/04, nơi đăng ký loại
   thật). `RunRequestService` từ chối lần thử → Kiểm định thử `error` kèm mọi lỗi, không xin thêm lần thử (spec R4.9).
   Kiểm định thử không niêm phong, không đổi giai đoạn, không mở phê duyệt. Test dùng bản Nháp quy trình thật và một
   nguồn graph agent giả theo khóa `(tenant_id, agent_version_id, mã băm ghim)`; đường thật của agent là
   agent-builder/03. `GET /api/v1/studio/gate-runs` (keyset `(created_at DESC, id DESC)`), `/{id}`, `/{id}/cases`
   (keyset `case_id`) (`studio.lifecycle.read`), mỗi thứ tự đi trên index của bước 1; cả ba chỉ trả Lượt kiểm định, kể
   cả dòng `dry`, của thành phần mà `studio.lifecycle.read` của người đọc chạm tới `owning_workspace_id` ở độ sâu của
   nó, đọc từ `platform.effective_grants` của tenant-rbac/02 (ADR-0104 (Accepted) quyết 3, quyết 5), còn ngoài độ sâu
   hay công ty khác → 404 như id không tồn tại (spec R4.10). Cùng migration của ticket: đăng ký khóa
   `studio.lifecycle.read`, `studio.evals.run` trong `platform.permissions` của tenant-rbac/01 (nhãn tiếng Việt,
   `scope_kind` `workspace`, `risk` `standard` theo bảng phân loại của ticket đó); INSERT nêu mọi cột NOT NULL của bảng
   lúc đó, gồm `risk` của tenant-rbac/01 và `tenant_grantable` (`true`) của tenant-rbac/02 (ticket này chờ ticket đó qua
   ticket 04).
5. Chốt chặn Phân tích năng lực: trước khi mở yêu cầu phê duyệt, lane đọc kết quả Phân tích năng lực mà compliance-pdpl/05
   ghi ở `studio.version_assessments` cho Mã băm định nghĩa của Bản ứng viên; thiếu kết quả, đường bộ ba chưa giải
   quyết, Mức tự chủ vượt mức hay công cụ chưa phân loại → cổng trượt, không mở yêu cầu phê duyệt, phiên bản về `draft`
   (spec R6.1, R6.2). Mã 422 lúc gửi kiểm định là của compliance-pdpl (compliance-pdpl:R4.2, R4.3, R4.4). Mức sàn duyệt
   của công cụ không bị hạ bởi cấu hình công ty, người dựng hay Mức tự chủ (ADR-0125 (Accepted)).
6. Kho ca kịch bản (spec R4.18, R4.19; H-23): cùng revision của bước 1 tạo `studio.workflow_scenarios`: `tenant_id`,
   `id`, `artifact_id uuid NOT NULL` với FK ghép `(tenant_id, artifact_id)` tới `studio.artifacts (tenant_id, id)` ON
   DELETE CASCADE, `name text NOT NULL` CHECK `char_length(name) BETWEEN 1 AND 80`, UNIQUE
   `(tenant_id, artifact_id, name)` (mang khóa ngoại và keyset của danh sách), `scenario jsonb NOT NULL` CHECK
   `octet_length(scenario::text) <= 262144`, `row_version bigint NOT NULL`, `created_by`, `updated_by`,
   `created_at timestamptz NOT NULL`, `updated_at timestamptz NOT NULL` (trigger `updated_at` nhường giá trị câu lệnh
   nêu); RLS ENABLE/FORCE chỉ theo tenant; `dw_app` SELECT, INSERT, UPDATE, DELETE; khẳng định ở `test_privileges.py`.
   Ca nằm ngoài tài liệu `dw.workflow/v1`, nên tạo, sửa hay xóa một ca không đổi `definition_hash` của phiên bản nào.
   `scenario` là mô hình `WorkflowScenario` (Pydantic, `extra="forbid"`), mỗi ca thành một `EvalCase` của ticket 02 với
   `category` `scenario`, `input` và `expected` nội tuyến, `trials` 1: `input` (đối tượng, đầu vào của lần thử),
   `approval_decisions` (map id Bước → `approved` hay `rejected`, từ vựng của workflow-nodes:R9.9), `pinned_results`
   (map id Bước → `{output}` hay `{error: {code}}`, hình mà `RunRequest.pinned_results` của workflow-engine/03 nhận),
   `expected_outcomes` (danh sách tên duy nhất, tối đa 20), `assertions` (tối đa 20 biểu thức CEL, mỗi biểu thức tối đa
   1.000 ký tự); id Bước theo dạng `^[a-z][a-z0-9_]{0,39}$` của workflow-engine. Route trong
   `dw_studio.lifecycle.presentation`: `GET /api/v1/studio/workflows/{artifact_id}/scenarios` (keyset theo `name`),
   `POST` (bắt buộc `Idempotency-Key`), `PUT .../scenarios/{scenario_id}` và `DELETE .../scenarios/{scenario_id}` (bắt
   buộc `If-Match` là `row_version`: lệch → 412 `precondition_failed` với `stale_version`, thiếu → 428
   `precondition_required`; app-standards:R3.2, app-standards:R3.3); khóa đọc `studio.workflows.read`, khóa ghi
   `studio.workflows.edit` ở độ sâu của `owning_workspace_id`, một người (spec R4.18; Đạt, Q-h9); thân sai dạng → 422 `validation_failed` với `errors[].pointer` (app-standards:R1.3), trùng `name`
   → 409 `conflict`; thành phần không phải `workflow`, ngoài độ sâu của khóa ở `owning_workspace_id` hay của công ty
   khác → 404 như không tồn tại, không ghi và không audit (spec R4.19). Audit `studio.scenario.created`,
   `studio.scenario.updated`, `studio.scenario.deleted` (actor là người gọi, `details` chỉ id thành phần và id ca) trong
   giao dịch ghi.
7. Ca kịch bản trong Lượt kiểm định (spec R4.13-R4.17; V4.37; H-14, H-18, H-23, H-26): khi Lượt kiểm định của một Bản
   ứng viên quy trình bắt đầu, lane đọc mọi dòng `studio.workflow_scenarios` của thành phần, ghi `scenario_set_hash` là
   sha256 của dạng chuẩn `dw_kernel.canonical` của danh sách `{name, scenario}` theo `name`, và mã đó vào khóa bằng chứng
   (spec R4.6), nên sửa một ca sau đó không đổi kết quả đã ghi mà làm lần gửi sau không dùng lại bằng chứng cũ; thành
   phần không có ca nào thì Lượt kiểm định trượt với `scenario_missing`, không lần thử nào (spec R4.13; Đạt, Q-h8). Trước lần thử, lane kiểm ca với tài liệu đã ghim: id Bước của
   `approval_decisions` hay `pinned_results` không có trong cây, một Bước `human.approval` của cây (mọi độ sâu) không có
   quyết định, hay tên của `expected_outcomes` không có trong `outcomes[]` của tài liệu (workflow-engine:R1.9) → ca trượt
   với `scenario_invalid`, không lần thử nào (spec R4.16). Lần thử của ca: `RunRequest` `simulate` như bước 2, đầu vào là
   `input` của ca, quyết định giả lập theo id Bước, và `pinned_results` của ca chuyển nguyên vào trường
   `RunRequest.pinned_results` mà workflow-engine/03 thêm (workflow-engine:R3.16, workflow-engine:R4.27; H-18); lane
   không lọc kết quả ghim nào, nên kết quả ghim cho một Bước `human.approval` làm lần thử `failed` với
   `pinned_result_invalid` của wrapper (workflow-engine:R4.29; H-26) và ca trượt với mã đó, 0 yêu cầu phê duyệt (spec
   R4.17). `EvalTargetPort` của ticket 02, đáp ứng ở composition root, trả `Observation` mà ticket này thêm trường
   `state` (map JSON mà `dw_evals` không đọc): `run.status`, `run.outcomes` (cột `platform.worker_runs.outcomes` của
   workflow-engine/04, workflow-engine:R5.24), `run.result` và `run.error_code` của lần thử, và `tool_calls` (tên công
   cụ và trạng thái của mỗi dòng `platform.tool_executions` của lần thử), không payload nào khác. Bộ chấm
   `studio.scenario` (trong `dw_studio`, hợp nhất bằng `merge_graders` ở bước 3) đánh ca đạt chỉ khi tập
   `run.outcomes` bằng tập `expected_outcomes` và mỗi khẳng định, biên dịch và tính qua `ExpressionEngine` của
   workflow-nodes/01 trên `state`, trả `true`; lệch tập → `outcome_mismatch`, `false` → `assertion_failed`, lỗi biên dịch,
   lỗi khi tính hay kết quả không phải bool → `assertion_error` (spec R4.15, R4.16); bộ chấm không nhận `JudgePort`, nên
   không gọi model nào. `dw_evals/dataset.py` thêm `CaseCategory.SCENARIO`, không đổi `SECURITY_CATEGORIES` (G1);
   `evaluate_gate` thêm luật: một câu `scenario` trượt hay `unknown` làm `passed=False` kèm lý do, đọc
   `scenario_pass_rate` của Chính sách cổng (spec R4.13). Mỗi ca ghi một dòng `studio.gate_case_results` với `case_id`
   là id dòng của ca, `reason_code` và `cost_usd`.
8. Nhãn (H-21): mỗi hành động audit mới của ticket (`studio.gate_run.started`, `studio.gate_run.completed`,
   `studio.scenario.created`, `.updated`, `.deleted`) có nhãn tiếng Việt trong mảnh
   `configs/copy/audit_actions.d/agent-lifecycle.yaml`, và mỗi mã lý do mới mà lane `studio_gate` ghi (`cost_bound`,
   `scenario_missing`, `scenario_invalid`, `outcome_mismatch`, `assertion_failed`, `assertion_error`) có nhãn trong mảnh
   `configs/copy/run_reason_codes.d/agent-lifecycle.yaml`, trong cùng thay đổi; mã của spec khác (`limit_exceeded`,
   `pinned_result_invalid`) giữ nhãn ở mảnh của spec chủ, vì bộ nạp từ chối một khóa khai ở hai mảnh
   (telemetry-and-audit:R1.10); bộ nạp và test thiếu nhãn là của telemetry-and-audit.

## Tiêu chí chấp nhận

- [ ] R4.1 (AL7): một Câu an ninh trượt → cổng trượt, phiên bản về `draft`; tất cả đạt (agent, không ca kịch bản) →
      `awaiting_approval`; không route nào ghi Câu an ninh.
- [ ] R4.2 (AL7): một bộ chấm trả `unknown` chặn như trượt; gỡ luật `unknown` trong `evaluate_gate` → test đỏ.
- [ ] R4.3 (AL8): agent có công cụ gửi Zalo `approval_policy: always` trong Lượt kiểm định → egress giả không nhận lời
      gọi, 0 dòng `platform.approval_requests` mới; gỡ chặn `simulate` ở executor hay đặt phê duyệt trước chế độ chạy →
      test đỏ.
- [ ] R4.7 (AL8): lần thử của quy trình có một Bước `human.approval` (Bước giả theo hợp đồng của workflow-nodes) với Câu
      kiểm định khai `rejected` → nhánh từ chối chạy, audit `studio.step.approval.simulated` mang `rejected`, 0 dòng
      `platform.approval_requests`; Câu khai `approved` → nhánh duyệt chạy; Câu thiếu khai báo → bộ sinh từ chối câu đó.
- [ ] R4.4 (AL9): chi phí xấu nhất, tính cả lần thử của ca kịch bản, vượt trần mỗi lượt → Lượt kiểm định `error`
      `limit_exceeded` trước mọi `worker_runs`; `LimitsPort` giả từ chối lease `eval_offline` → như trên, 0 lời gọi
      model; bỏ lần thử của ca kịch bản khỏi phép tính chi phí xấu nhất → ca vượt trần chỉ vì ca kịch bản không bị chặn,
      test đỏ.
- [ ] R4.5 (AL9): một lần thử chạm trần mỗi lần thử → Câu đó trượt với `cost_bound`, các câu khác vẫn chấm; gỡ trần mỗi
      lần thử → test đỏ.
- [ ] R4.6 (AL32): hai Lượt kiểm định cùng khóa bằng chứng → lượt sau dùng lại, không tạo run; sửa một ca kịch bản giữa
      hai lần gửi cùng nội dung → `scenario_set_hash` khác, lượt sau chạy lại; bỏ `scenario_set_hash` khỏi khóa → lượt
      sau dùng lại bằng chứng của tập ca cũ, test đỏ.
- [ ] R4.8 (AL22): Kiểm định thử một bản Nháp quy trình → mỗi lần thử là run `simulate` mà bản kê ghim giai đoạn `draft`
      và mã băm tạm, phiên bản vẫn `draft`, `gate_run_id` NULL, 0 dòng `platform.approval_requests`; sửa nháp rồi Kiểm
      định thử lại → lần thử ghim mã băm tạm mới và chạy nội dung mới; cùng hai ca với một bản Nháp agent qua nguồn graph
      giả theo khóa có mã băm ghim; bỏ mã băm ghim khỏi khóa cache graph → lần sau chạy nội dung cũ, test đỏ.
- [ ] R4.9 (AL22): `RunRequestService` từ chối lần thử vì nội dung nháp trượt bộ kiểm của loại → Kiểm định thử `error`
      kèm mọi lỗi, 0 `worker_runs`, không lần thử nào được xin thêm; nuốt lần từ chối rồi xin lần thử kế → test đỏ.
- [ ] R4.11 (AL26): với cửa giả ghi danh nghĩa, mỗi lần thử của Kiểm định thử được xin dưới danh nghĩa người xin; xin
      dưới danh nghĩa lane hay người gửi khác người xin → test khớp đỏ; trên `RunRequestService` thật, Kiểm định thử bản
      Nháp quy trình có Bước `data.object.*` đọc đối tượng X mà người xin đọc được bản ghi x1, không đọc được x2 → lần thử
      thấy x1, không thấy x2, và đọc đối tượng Y ngoài bao đóng → 0 bản ghi; bỏ giới hạn tạm khỏi lần thử → x1 cũng
      không thấy, test đỏ.
- [ ] R4.12 (AL27): với cửa giả ghi danh nghĩa, mỗi lần thử của Lượt kiểm định, kể cả lần thử của ca kịch bản, được xin
      dưới danh nghĩa người gửi Bản ứng viên; xin dưới danh nghĩa lane (`system:studio_gate`) hay một người khác người
      gửi → test khớp đỏ; trên `RunRequestService` thật, Lượt kiểm định một Bản ứng viên quy trình có Bước
      `data.object.*` đọc đối tượng X mà người gửi đọc được bản ghi x1, không đọc được x2 → lần thử thấy x1, không thấy x2,
      và đọc đối tượng Y ngoài bao đóng → 0 bản ghi; bỏ giới hạn tạm khỏi lần thử → x1 cũng không thấy
      (record-access:R6.5), test đỏ.
- [ ] R4.10 (AL23): người giữ `studio.lifecycle.read` ở độ sâu `workspace` của ws1 gọi `GET /api/v1/studio/gate-runs` →
      chỉ Lượt kiểm định của thành phần có `owning_workspace_id` là ws1, không dòng nào của thành phần thuộc ws2, kể cả
      dòng `dry`; `GET .../gate-runs/{id}` và `/{id}/cases` của Lượt kiểm định thuộc ws2 → 404; người của tenant B dùng
      id của tenant A → 404; bỏ lọc theo `owning_workspace_id` của thành phần → test đỏ.
- [ ] R4.13 (AL30): quy trình fixture có `outcomes[]` `lead_new`, `lead_duplicate` và ba ca kịch bản đúng → Lượt kiểm
      định `passed`, ba dòng `studio.gate_case_results` `scenario` đạt; một ca mong `lead_new` mà lần thử ra
      `lead_duplicate` → cổng trượt, phiên bản về `draft`, 0 yêu cầu phê duyệt; gỡ luật `scenario` khỏi `evaluate_gate` →
      cổng đạt dù ca trượt, test đỏ.
- [ ] R4.13 (AL30): đột biến gỡ nhánh trùng của quy trình fixture rồi gửi lại → ca "lead trùng" trượt với
      `outcome_mismatch`, cổng trượt; cùng sáu ca lặp 20 lượt cổng trên cùng Bản ứng viên (đồng hồ và nguồn ngẫu nhiên
      giả) → cùng một `verdict` mỗi lượt.
- [ ] R4.13 (AL30): thành phần quy trình không có ca nào → Lượt kiểm định trượt với `scenario_missing`, 0 lần thử,
      phiên bản về Nháp; gỡ kiểm → cổng đạt trên tập rỗng, test đỏ.
- [ ] R4.14 (AL31): ca ghim kết quả `{output: {sent: true}}` cho Bước gửi email → lần thử nhận kết quả đó, 0 lời gọi
      `ToolExecutor` cho Bước đó, `pinned_results` của dòng `worker_runs` bằng đúng map của ca; lane không chuyển
      `pinned_results` → lần thử gọi cửa của Bước, test đỏ.
- [ ] R4.15 (AL30): ca có khẳng định `run.status == 'completed' && size(tool_calls) == 1` đúng → ca đạt; khẳng định trả
      `false` → `assertion_failed`; một `JudgePort` giả nối vào composition root nhận 0 lời gọi trong cả Lượt kiểm định;
      cho bộ chấm gọi `JudgePort` → test đếm lời gọi đỏ.
- [ ] R4.16 (AL30): khẳng định không biên dịch, ném lỗi khi tính hay trả chuỗi → `assertion_error`, ca trượt;
      `expected_outcomes` nêu tên không có trong `outcomes[]` của tài liệu ghim, id Bước của `pinned_results` không có
      trong cây, hay một Bước `human.approval` của cây không có quyết định → `scenario_invalid`, 0 lần thử của ca đó; cho
      lỗi khi tính thành đạt → test đỏ.
- [ ] R4.17 (AL31): ca ghim kết quả cho một Bước `human.approval` → lần thử `failed` `pinned_result_invalid`, ca trượt
      với mã đó, nhánh của quyết định giả lập không chạy, 0 dòng `platform.approval_requests`; lane lọc kết quả ghim của
      Bước phê duyệt khỏi `RunRequest` → ca đạt, test đỏ.
- [ ] R4.18 (AL33): người chỉ giữ `studio.workflows.read` → `GET` danh sách được, `POST` → 403; người giữ
      `studio.workflows.edit` ở độ sâu của `owning_workspace_id` `POST` một ca hợp lệ → 201 với `row_version`, đúng một audit
      `studio.scenario.created`, `definition_hash` của mọi phiên bản thành phần không đổi; `PUT` với `If-Match` cũ → 412
      `stale_version`, ca không đổi; thiếu `If-Match` → 428; khóa lạ trong `scenario` → 422 với con trỏ; trùng `name` →
      409; `DELETE` với `If-Match` đúng → ca mất khỏi danh sách, audit `studio.scenario.deleted`.
- [ ] R4.19 (AL33): người của tenant B gọi `GET`, `PUT`, `DELETE` với id thành phần hay id ca của tenant A → 404 giống
      hệt id ngẫu nhiên, không ghi và không audit ở A; người giữ khóa ở độ sâu `workspace` của ws1 gọi route của thành
      phần thuộc ws2 → 404; `artifact_id` của một agent → 404; chạy truy vấn của route bằng vai bỏ qua RLS hay bỏ lọc
      `owning_workspace_id` → test đỏ.
- [ ] R4.20: Kiểm định thử một bản Nháp quy trình có hai ca kịch bản → hai dòng `studio.gate_case_results` `scenario`
      trong Lượt kiểm định `dry`, phiên bản vẫn `draft`; bỏ ca kịch bản khỏi Kiểm định thử → test đỏ.
- [ ] R1.9 (AL21): bằng vai migrator, dòng phiên bản của tenant A đặt `gate_run_id` là id một Lượt kiểm định của tenant
      B, một dòng `studio.gate_case_results` của A trỏ tới Lượt kiểm định đó, một dòng `studio.gate_runs` của A đặt
      `artifact_id` là id một thành phần của tenant B, và một dòng `studio.workflow_scenarios` của A đặt `artifact_id`
      của tenant B → FK ghép từ chối cả bốn, không ghi; cùng id của tenant A → nhận; đổi một FK sang một cột → test đỏ.
- [ ] R5.1: khi gate đạt, yêu cầu phê duyệt mở trong cùng giao dịch `evaluating → awaiting_approval` qua
      `LifecycleService`, payload chỉ id và mã với `author_ids` bằng `contributor_ids` cộng `submitted_by`,
      `requested_by` bằng `submitted_by`; lane ghi `awaiting_approval` thẳng không qua `LifecycleService` → không yêu
      cầu phê duyệt nào mở, test đỏ.
- [ ] R5.6 (AL4): chuyển `live` với `gate_run_id` của một Lượt kiểm định `passed` trên mã băm khác, hay của một Lượt
      kiểm định `failed` → 23514; gỡ kiểm cổng khỏi trigger → test đỏ.
- [ ] R5.7: yêu cầu phê duyệt phát hành quá 14 ngày → lane hủy nó, phiên bản về `draft`, audit với actor
      `system:<lane>`; yêu cầu 13 ngày tuổi còn nguyên.
- [ ] R6.1 (AL10): `dw_app` ghi thẳng một Bản ứng viên không có dòng `studio.version_assessments` sang `evaluating` →
      cổng trượt, không yêu cầu phê duyệt nào, phiên bản về `draft`; dòng ghi đường bộ ba chưa giải quyết → như trên; gỡ
      đọc kết quả ở lane → yêu cầu phê duyệt mở (đỏ).
- [ ] R6.2 (AL10): kết quả ghi một công cụ thiếu phân loại → cổng trượt, không yêu cầu phê duyệt nào.
- [ ] R6.3 (AL10): cấu hình công ty không hạ được mức sàn duyệt của công cụ trọng yếu; chỉ siết thêm được.
- [ ] R10.2: `test_offboarding.py` purge một tenant có một Lượt kiểm định `gate` mà một phiên bản trỏ tới, kèm kết quả
      từng câu, một Lượt kiểm định `dry` và hai ca kịch bản → mọi dòng `studio.gate_runs` và `studio.workflow_scenarios`
      của tenant đó bị xóa, tenant khác giữ nguyên, không bước nào của ticket này trong sổ bước xóa; đăng ký thử một bước
      thứ hai khai `studio.gate_runs` → lane từ chối trước câu xóa đầu, tenant giữ `offboarding`
      (foundations-hardening:R11.5); cho sổ bỏ qua cạnh `gate_run_id` khi suy thứ tự → test phủ của studio-skeleton:R4.2 đỏ
      nêu khóa ngoại đó, và lần purge gặp lỗi khóa ngoại.
- [ ] R10.3 (AL24): `dw_app` DELETE một Lượt kiểm định của công ty `active` → 23514, dòng còn; cùng lệnh khi công ty
      `offboarding`, trên Lượt kiểm định không còn dòng nào trỏ tới → xóa được; gỡ kiểm khỏi trigger → test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_evals/src/dw_evals/dataset.py:14-31`; spec: R4.13 (`CaseCategory` thêm `scenario`,
  `SECURITY_CATEGORIES` không đổi, G1).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:167`; spec: R6.2 (phân loại công cụ là bên đọc
  đầu tiên); ADR-0120 (Accepted) quyết 2-3, ADR-0125 (Accepted).
- `db/migrations/sql/0001_platform_baseline.sql:447`; spec: R4.15 (`result`, `error` của `platform.worker_runs` mà
  `Observation.state` đọc).
- spec: R1.9, R4, R5.1, R5.6, R5.7, R6, R10.2, R10.3; workflow-engine:R1.9, workflow-engine:R3.16,
  workflow-engine:R4.27, workflow-engine:R4.29, workflow-engine:R5.24; workflow-nodes:R9.9; telemetry-and-audit:R5.6;
  YC115; V4.37; H-1, H-14, H-18, H-21, H-23, H-26.

## Comments

- 2026-10-26 (agent): lượt h, đợt 2, tách từ ticket 04 theo V4.31 của Đạt và bảng ticket của lượt h: ticket này nhận bước
  1-4 và 6 cũ của ticket 04 (`studio.gate_runs`, lane `studio_gate`, bộ an ninh nền tảng, `dry-evaluations`, chốt chặn
  Phân tích năng lực), cùng lane hết hạn phê duyệt phát hành, bên đọc của `publish_approval_ttl_days` trong tệp Chính sách
  cổng mà ticket này tạo, và nhận thêm ca kịch bản tất định của quy trình (V4.37; bước 6, 7). Ticket 04 giữ phát hành
  hai người cho mọi loại. Blocked by theo bảng của lượt h: cạnh tới telemetry-and-audit/03 của ticket 04 cũ thành
  telemetry-and-audit/01 (H-1: mảnh retention của `studio.gate_case_results` thêm trong cùng thay đổi, không chuỗi
  ticket). Không thêm cạnh ngoài bảng: `pinned_results` (workflow-engine/03), cột `outcomes` (workflow-engine/04) và
  `ExpressionEngine` (workflow-nodes/01) đều đứng trước workflow-engine/04, mà ticket này chờ.
- 2026-10-26 (agent): lượt h, đợt 2, theo H-2 (báo của nhóm TC-TR-OP-FH): `_ORDERED_FIRST` và thứ tự xóa viết tay đã bỏ;
  bước 1 và tiêu chí R10.2 theo sổ bước xóa của foundations-hardening/07 (foundations-hardening:R11.4, R11.5, FH33):
  thứ tự suy từ khóa ngoại `RESTRICT` và `NO ACTION` trong `pg_constraint`, ticket này không đăng ký bước nào vì hai bảng
  của nó chỉ cần câu `DELETE` chung. Không thêm cạnh: ticket này chờ ticket 04 → ticket 03, mà chờ foundations-hardening/07.
- 2026-10-26 (agent): áp Q-h8, Q-h9 của Đạt (theo khuyến nghị): bước 6 nêu khóa của route ca kịch bản, bước 7 cho cổng trượt
  `scenario_missing` khi không có ca, bước 8 thêm nhãn của mã đó; thêm hai tiêu chí. Không thêm cạnh.
