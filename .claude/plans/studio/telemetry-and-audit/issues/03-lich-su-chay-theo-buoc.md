# 03 — Lịch sử chạy theo bước: `run_steps` có che và lưu giữ, danh sách run, chi tiết bước

Status: needs-triage
Blocked by: .claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md, .claude/plans/studio/field-security/issues/01-mo-hinh-bao-mat-truong.md, .claude/plans/studio/usage-and-limits/issues/02-bang-gia-so-su-dung-va-man-hinh.md, .claude/plans/studio/usage-and-limits/issues/03-han-muc-giu-truoc-va-quyet-toan.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md
Area: studio
Yêu cầu: R1.6, R1.7, R1.8, R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R4.1, R4.2, R4.3, R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.7, R5.8, R5.9, R5.10, R5.11, R5.12, TA4, TA5, TA6, TA10, TA11, TA12, TA13, TA14, TA15, TA16, TA17, TA18, TA19, TA20

## Mục tiêu

Một kho `platform.run_steps` cho mỗi Bước chạy, che bí mật khi ghi và che theo quyền đọc trường của người xem khi đọc,
mỗi Bước chạy mang làn và lần lặp của lần chạy Bước (V4.26); màn Lịch sử chạy đọc dưới `runs.read` theo độ sâu; một
chính sách lưu giữ có bộ xóa cho mỗi kho mới, với bảng `platform.retention_terms` mà bộ nạp nạp từ bản tệp đang ghim lúc
triển khai và mọi hàm xóa hẹp không đối số đọc hạn (V4.21); một catalog hành động audit có test AST, chủ duy nhất của
nhãn action mà màn `/audit` đọc qua API (spec R1.6, R1.7, R1.8, R3, R4, R5).

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên): `platform.run_steps` phân vùng theo tháng trên `started_at`
   với DEFAULT, RLS ENABLE và FORCE trên cha và DEFAULT cùng migration; `PRIMARY KEY (id, started_at)`;
   cột `tenant_id`, `workspace_id`, `run_id`, `root_run_id`, `seq int`, `kind` CHECK (`node`, `model_call`,
   `tool_call`, `approval`, `sub_run`), `node_id`, `lane_path jsonb NOT NULL` CHECK
   `jsonb_typeof(lane_path) = 'array'` (mỗi phần tử
   `{"step": <id Bước chứa>, "port": <tên Nhánh ra mà loại của nó khai>}`, từ chuỗi gốc tới làn chứa Bước), `iteration_path text NOT NULL` (giá trị mà wrapper dẫn vào khóa chống lặp), cả hai
   không DEFAULT (spec R3.7), `status`, `started_at timestamptz`, `finished_at
timestamptz`, `duration_ms`, `error_type`, `input_preview` và `result_preview` (≤ 4 KB), `input_ref` và
   `result_ref` (đường dẫn đối tượng, NULL khi giữ trong dòng), token, `cost_usd numeric(18,8)`,
   `price_book_version`, `redaction_log jsonb NOT NULL DEFAULT '[]'`, `fls_version`; không cột nội dung
   thô; `dw_app` không UPDATE, DELETE trên cha và không giữ quyền nào trên phân vùng nào, kể cả DEFAULT
   (DO-02.2); index `ix_run_steps_run (tenant_id, run_id, seq)`.
2. Đăng ký `run_steps` bằng một dòng `platform.time_partitioned_tables` (`append_only = true`) trong cùng
   migration; không sửa thân `platform.ensure_time_partitions` (studio-skeleton/01 là chủ hàm, hàm tạo
   partition kèm ENABLE/FORCE RLS và policy công ty), cũng không sửa thân hai hàm của usage-and-limits/02. Cùng
   thay đổi: khóa `platform.run_steps` vào tệp chính sách retention (bước 7), nên studio-skeleton:R3.7 xanh ngay
   khi đăng ký; một dòng `STUDIO_EXCLUSIONS` cho `platform.run_steps` với lý do "`dw_app` không DELETE; xóa khi
   offboarding bằng `platform.purge_tenant_append_only`" (spec R5.8; studio-skeleton:R4.3).
3. `StepRecorderPort.step_started`, `step_finished`; `step_started` nhận `lane_path` và `iteration_path` của lần chạy
   Bước từ bên gọi và ghi nguyên, không tự tính (wrapper nút của workflow-engine/03 cấp chúng từ `WorkflowIR` của lượt,
   `iteration_path` là giá trị nó dẫn vào khóa chống lặp, workflow-engine:R4.5; spec R3.7); đường che `redact_mapping`
   bỏ trường bí mật và tham chiếu credential, che trường `Nhạy cảm` bằng hàm quyết quyền đọc trường của field-security,
   preview ≤ 4 KB, payload lớn gzip ở đường dẫn `tenants/{tenant_id}/workspaces/{workspace_id}/run-steps/`, ghi đường
   dẫn và lý do che vào `redaction_log`.
4. Agent: Bước chạy `model_call` và `tool_call` ghi từ `LimitsMiddleware` (usage-and-limits/03) và
   ToolExecutor; đọc token và chi phí mỗi Bước chạy từ Sổ sử dụng của usage-and-limits; Bước chạy của lượt agent không
   nằm trong một Bước quy trình mang `lane_path` `[]` và `iteration_path` rỗng, còn Bước chạy con của một Bước quy trình
   mang `lane_path` và `iteration_path` của lần chạy Bước đó.
5. Route (`runs.read`, RLS và workspace theo độ sâu):
   `GET /api/v1/runs?artifact_kind&artifact_id&status&trigger_kind&from&to&cursor&limit` với index
   `ix_worker_runs_page (tenant_id, workspace_id, created_at DESC, id DESC)`; `GET /api/v1/runs/{run_id}/steps` (mỗi
   Bước chạy mang `lane_path` và `iteration_path`, spec R4.2);
   `GET /api/v1/runs/{run_id}/steps/{step_id}/payload?part=in|out` (`runs.read_payloads`, che theo quyền đọc trường của
   người xem, audit `run.payload.viewed` trong cùng giao dịch). Một lượt chạy chạm bản ghi người xem không thấy → 404.
   Migration của ticket đăng ký khóa `runs.read_payloads` trong `platform.permissions` của tenant-rbac/01, với INSERT
   nêu mọi cột NOT NULL có lúc đó: nhãn tiếng Việt, `scope_kind` `workspace`, `risk` `standard` theo bảng phân loại của
   tenant-rbac/01, và `tenant_grantable` `true` của tenant-rbac/02 (ticket này chờ tenant-rbac/02).
6. Màn `/runs` (antd Table: thời điểm, agent hoặc quy trình, trạng thái, nguồn kích hoạt, thời lượng, chi
   phí, bộ lọc) và `/runs/[id]` (Steps, Descriptions, xem JSON có dấu `Đã ẩn`, token và chi phí mỗi Bước
   chạy, nút "Sao chép trace id").
7. Tệp chính sách retention `configs/policies/retention@<semver>.yaml`, một bản mới theo định dạng của spec R5.6
   (mỗi kho một khóa `schema.table` với thời hạn, bộ xóa và `enforced`; khóa của bảng mà spec khác tạo do ticket tạo
   bảng thêm, ticket này không khai lại), là bản kế tiếp sau bản của usage-and-limits/03 trong chuỗi các ticket sửa
   tệp ở mục Phụ thuộc của spec, mọi số ghi UNVERIFIED tới khi luật sư xác nhận trước chạy bóng (DO-52). Ticket này
   thêm khóa và bộ xóa cho
   `platform.run_steps` (30 ngày; lane xóa payload trong dòng và đối tượng của bước quá 30 ngày qua một hàm SECURITY
   DEFINER hẹp không đối số của lane, đọc hạn dưới khóa `platform.run_steps` qua `platform.retention_term_days` của
   bước 10, vì `dw_app` không UPDATE bảng; DROP PARTITION khi cả tháng quá 30 ngày), payload đối tượng (30 ngày,
   lane xóa đối tượng), cột payload lượt chạy (90 ngày sau kết thúc, lane xóa), lượt chạy (395 ngày sau kết
   thúc, lane xóa, bỏ qua dòng `memory.items` trỏ tới theo `db/migrations/versions/0007_evidence.py:113-115`),
   `platform.tool_executions.output` (30 ngày dưới khóa `platform.tool_executions`, xóa trắng qua hàm SECURITY
   DEFINER hẹp không đối số chỉ đặt NULL `output` của dòng quá hạn, đọc hạn qua `platform.retention_term_days` của
   bước 10, `dw_app` không nhận UPDATE; spec R5.7), `usage_daily` (760 ngày, lane xóa); lane đếm mỗi dòng quá
   hạn mà một bộ xóa đăng ký bỏ qua trên `dw_retention_skipped_total{store, reason}` theo lý do bộ xóa trả (spec
   R5.3, R5.5); bỏ chú thích "model_usage_ledger đã bị bỏ" của bản 1.7.0
   (`configs/policies/retention@1.7.0.yaml:72`); test tập bộ xóa, test khóa của tệp (mỗi khóa khớp một bảng có thật
   hay một kho có tên; spec R5.6) và `test_the_pinned_retention_policy_promises_only_classes_code_can_assign`.
   Khóa, bộ xóa và test xóa của `studio.inbound_events`, `studio.trigger_deliveries` và `studio.inbound_dedupe` ở
   workflow-triggers/02, nơi tạo bảng; ticket này không thêm khóa nào cho bảng chưa có.
8. Catalog hành động audit `configs/copy/audit_actions@1.0.0.yaml` (ADR-0122 (Accepted) quyết 6): một khóa cho mỗi
   `action` mà mã trong `src/` ghi lúc ticket này vào, gồm `run.payload.viewed` của bước 5, mỗi khóa mang một nhãn
   tiếng Việt; test AST đọc mọi lời ghi sự kiện Nhật ký kiểm toán trong `src/` và đỏ khi một `action` không có khóa
   trong catalog (spec R1.6). Cách các ticket sau thêm tên action là Q2 của spec; ticket này không thêm tên cho action
   chưa có mã ghi.
9. Nhãn action có một chủ, catalog của bước 8 (spec R1.7, R1.8; `failure-modes.md` #2): `AuditEventView` của
   `GET /api/v1/audit/events` (`apps/api/src/dw_api/routes/v1/audit.py:17`) thêm `action_label: str | None`, nhãn
   của `action` trong bản catalog đang ghim, NULL khi catalog không có khóa; kiểm quyền và phân trang của route giữ
   nguyên, và client sinh ra (`packages/typescript/api-client/src/generated/platform.d.ts`) mang trường mới. Màn đọc
   trang qua `listAuditEvents`, nơi bản zod viết tay `auditEventSchema` của `@dw/contracts`
   (`packages/typescript/contracts/src/audit.ts:3-12`) parse phản hồi, và zod bỏ mọi khóa bản zod không khai, nên
   `auditEventSchema` thêm `action_label: z.string().nullable()` và `packages/typescript/api-client/src/client.ts`
   thêm một dòng `SameType` so `AuditEvent` với `Generated["AuditEventView"]` theo kiểu và theo tập khóa, như các
   dòng ở `client.ts:200-244`: bản zod thiếu trường thì biên dịch đỏ, thay vì mọi dòng lặng lẽ hiện
   `Hoạt động hệ thống`. Màn `/audit` hiện `action_label` ở cột Thao tác trong một antd Tag chung cho mọi action,
   `Hoạt động hệ thống` khi trường đó NULL, dòng vẫn hiện; bỏ bảng `ACTIONS` (nhãn và màu theo từng action) cùng chú
   thích PLUG-IN POINT của nó ở `apps/web/app/audit/page.tsx:15-25`. Bước 8 chép nguyên chữ sáu nhãn của bảng đó vào
   catalog, nên chữ của sáu action đó trên màn không đổi; một action mới thêm nhãn vào catalog (Q2 của spec), không
   vào mã web.
10. Bảng thời hạn ở runtime (spec R5.9, R5.10, R5.11, R5.12; V4.21):
    - Revision Alembic mới (id hex ngẫu nhiên): `platform.retention_terms` (`store_key text PRIMARY KEY`,
      `term_days integer NOT NULL` CHECK `term_days > 0`, tên ràng buộc theo `NAMING_CONVENTION`), không
      `tenant_id`, không RLS; `REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON platform.retention_terms FROM dw_app` như
      migration `648e2f7c3edb`, vì quyền mặc định của schema cấp INSERT, UPDATE, DELETE, và `dw_app` giữ SELECT;
      `GRANT SELECT, INSERT, UPDATE, DELETE` cho `dw_provisioner` theo bảng, bọc trong kiểm vai tồn tại như các
      migration cấp quyền cho vai đó; dòng của bảng trong
      `packages/python/dw_platform/tests/integration/test_privileges.py`. Cùng revision: hàm
      `platform.retention_term_days(p_store_key text) RETURNS integer` STABLE, `search_path` cố định, trả
      `term_days` của khóa và RAISE với SQLSTATE `P0002` khi không có dòng; REVOKE ALL FROM PUBLIC, không vai nào
      nhận EXECUTE, vì chỉ các hàm xóa hẹp SECURITY DEFINER gọi nó.
    - Bộ nạp trong `dw_platform`, cạnh `dw_platform.retention_policy`: đọc bản tệp đang ghim qua mô hình chính
      sách, lấy mỗi khóa có `days` và `enforced: true`, rồi trong một giao dịch dưới vai `dw_provisioner` thêm, sửa
      và xóa dòng tới khi bảng đúng bằng tập đó; đọc tệp hay nối CSDL hỏng thì thoát mã khác 0 và không đổi dòng
      nào. Hằng `RETENTION_POLICY_PATH` ở `apps/worker/src/dw_worker/main.py:114` chuyển vào
      `dw_platform.retention_policy`, nên worker và bộ nạp đọc cùng một chỗ ghim bản tệp.
    - Job `migrate` của `infra/compose/docker-compose.yml` chạy bộ nạp ngay sau `alembic upgrade head`, với
      `DW_PROVISIONER_DATABASE_URL`; `api` và `worker` đã chờ job đó với `service_completed_successfully`, nên khởi
      động sau khi bảng khớp tệp. Fixture tích hợp chạy bộ nạp ngay sau `alembic upgrade head`. Bộ nạp cần vai
      `dw_provisioner`, mà mọi cụm compose tạo lúc khởi tạo và một cụm cũ hơn nhận qua
      `scripts/create_provisioner_role.py`; script đó thêm SELECT, INSERT, UPDATE, DELETE trên
      `platform.retention_terms` vào các quyền nó cấp lại, vì revision bỏ qua lệnh GRANT khi vai chưa có lúc migration
      chạy, mà script hứa chạy được trước hay sau migration (`scripts/create_provisioner_role.py:1-18`); thiếu vai thì
      bộ nạp không nối được và job `migrate` thoát mã khác 0, nên lần triển khai dừng thay vì chạy với một bảng thời
      hạn rỗng.
    - Test lệch bảng so `platform.retention_terms` với tập khóa có `days` và `enforced: true` của bản tệp đang ghim,
      đỏ và nêu khóa khi một khóa thiếu, thừa hay khác hạn; một test đọc tệp compose đỏ khi lệnh của `migrate` không
      chạy bộ nạp sau migration, hay `api`, `worker` không chờ `migrate`.

## Tiêu chí chấp nhận

- [ ] R1.6 (TA15): thêm một lời ghi audit với `action` không có khóa trong `configs/copy/audit_actions@1.0.0.yaml` →
      test AST đỏ, nêu tên action; một khóa của catalog có nhãn tiếng Việt rỗng → test đỏ; `run.payload.viewed` có
      khóa và nhãn.
- [ ] R1.7 (TA16): đổi nhãn của `run.started` trong một catalog thử → `GET /api/v1/audit/events` trả nhãn mới trong
      `action_label` của sự kiện `run.started`; sự kiện có `action` không có khóa trong catalog → `action_label` NULL,
      dòng vẫn trả.
- [ ] R1.8 (TA16): màn `/audit` nhận qua `listAuditEvents` (phản hồi HTTP giả, parse bằng `auditEventSchema`) một
      trang có sự kiện `run.started` với `action_label` khác nhãn mà bảng `ACTIONS` cũ ghi → cột Thao tác hiện đúng
      `action_label`; `action_label` NULL → hiện `Hoạt động hệ thống`, dòng vẫn hiện; giữ lại bảng `ACTIONS` → test
      màn đỏ; bỏ `action_label` khỏi `auditEventSchema` → dòng `SameType` của `client.ts` không biên dịch.
- [ ] R3.1: một node kết thúc → đúng một Bước chạy mang trạng thái, thời điểm, thời lượng, token, chi phí.
- [ ] R3.2 (TA6): input mang một khóa bí mật → preview không có giá trị, `redaction_log` ghi lý do; gỡ bỏ
      bí mật → test đỏ.
- [ ] R3.3 (TA5): người không có quyền đọc `phone` → payload trả dấu `Đã ẩn`; gỡ che → test đỏ.
- [ ] R3.4: payload 4 KB giữ trong dòng; 4 KB cộng một byte → lưu theo tham chiếu, dòng giữ `input_ref`.
- [ ] R3.5 (TA10): mở payload → đúng một sự kiện `run.payload.viewed`; gỡ ghi audit → test đỏ.
- [ ] R3.6 (TA4): `GET /api/v1/runs/{run_id}/steps` của lượt chạy công ty B từ A → 404; danh sách
      `GET /api/v1/runs` không có lượt chạy công ty khác.
- [ ] R4.1: người giữ `runs.read` gọi `GET /api/v1/runs` → chỉ lượt chạy trong tập workspace được phép;
      trang 2 không trùng và không sót dòng so với trang 1.
- [ ] R4.2 (TA20): `GET /api/v1/runs/{run_id}/steps` → các Bước chạy theo thứ tự `seq`, mỗi Bước mang `lane_path` và
      `iteration_path` đúng như đã ghi; bỏ hai trường khỏi mô hình trả → test đỏ.
- [ ] R3.7 (TA20): hai lần chạy cùng một Bước ở hai lần lặp, ghi qua `StepRecorderPort` với giá trị mà bên gọi đưa như
      wrapper đưa → hai Bước chạy có `iteration_path` khác nhau, bằng đúng giá trị trong hai khóa chống lặp
      `wf:{run_id}:{node_id}:{iteration_path}` mà bên gọi dựng; một Bước ở làn `rejected` của một Bước phê duyệt →
      `lane_path` nêu Bước phê duyệt và Nhánh ra `rejected`; INSERT thiếu `lane_path` hay `iteration_path` → NOT NULL
      từ chối; bên ghi thay `iteration_path` của bên gọi bằng chuỗi rỗng → hai Bước chạy không phân biệt được, test đỏ;
      thêm DEFAULT `'[]'` cho `lane_path` trong migration thử → INSERT thiếu cột qua, test đỏ.
- [ ] R4.3 (TA12): thiếu `runs.read_payloads` gọi payload → 403, không trả payload; gỡ kiểm → test đỏ.
- [ ] R5.1 (TA13): mỗi kho (`run_steps`, payload đối tượng, cột payload, `usage_events`, `usage_daily`) có một
      thời hạn dưới khóa của nó trong tệp chính sách retention đang ghim và một bộ xóa đã đăng ký; test tập bộ xóa
      này cũng phủ `studio.inbound_events`, `studio.trigger_deliveries` khi workflow-triggers/02 thêm khóa và bộ xóa
      của chúng (workflow-triggers:R6.3, workflow-triggers:R6.7).
- [ ] R5.6: tệp có một khóa không khớp bảng hay kho có tên nào, hay một thời hạn đặt dưới tên bảng thiếu schema →
      test khóa của tệp đỏ; hai bảng thử cùng tên ở `platform` và `studio` mang hai thời hạn khác nhau, mỗi bảng
      đọc đúng thời hạn của mình.
- [ ] R5.7 (TA14): dòng `tool_executions` 31 ngày tuổi → sau một lượt lane, `output` NULL, cột khác giữ nguyên;
      dòng 29 ngày giữ `output`; `dw_app` UPDATE thẳng → `permission denied`; hàm đặt NULL thêm một cột → test đỏ;
      hạ dòng `platform.tool_executions` của `platform.retention_terms` còn 20 ngày → dòng 21 ngày bị xóa trắng; hàm
      giữ hằng 30 ngày hay nhận mốc làm đối số → test đỏ.
- [ ] R5.9 (TA17): bộ nạp chạy trên tệp thử A rồi tệp thử B (một hạn đổi, một khóa bỏ, một khóa thêm, một khóa
      `enforced: false`) → `platform.retention_terms` đúng bằng tập khóa có `days` và `enforced: true` của B; bộ nạp
      bỏ bước xóa dòng → dòng của khóa bỏ còn, test đỏ; lệnh của job `migrate` không chạy bộ nạp sau
      `alembic upgrade head`, hay `api`, `worker` không chờ `migrate` → test tệp compose đỏ.
- [ ] R5.10 (TA17): sửa tay hạn một dòng, chèn một khóa thừa hay xóa một dòng → test lệch bảng đỏ, nêu khóa; bảng
      vừa nạp từ bản tệp đang ghim → xanh.
- [ ] R5.11 (TA18): `dw_app` INSERT, UPDATE, DELETE trên `platform.retention_terms` → `permission denied`, bảng
      không đổi; `test_privileges.py` khẳng định `dw_app` chỉ SELECT, `dw_provisioner` SELECT, INSERT, UPDATE,
      DELETE; bỏ lệnh REVOKE của revision → test đỏ.
- [ ] R5.12 (TA19): xóa dòng `platform.tool_executions` khỏi bảng thử → hàm xóa trắng `output` báo lỗi `P0002`,
      không dòng nào đổi; xóa dòng `platform.run_steps` → hàm xóa payload bước báo lỗi, không payload nào mất;
      `platform.retention_term_days` trả hạn mặc định hay NULL khi thiếu dòng → test đỏ.
- [ ] R5.8: công ty `offboarding` có dòng `run_steps` → lane `offboarding` xuất mỗi dòng một lần rồi xóa hết qua
      `platform.purge_tenant_append_only`; test phủ offboarding (studio-skeleton:R4.3) xanh với dòng
      `STUDIO_EXCLUSIONS` của `platform.run_steps`.
- [ ] R5.2 (TA13): một lớp retention thiếu bộ xóa → test tập bộ xóa đỏ.
- [ ] R5.3 (TA11): lượt chạy `waiting_approval` 400 ngày còn nguyên; lượt chạy được `memory.items` trỏ tới
      → bỏ qua, được đếm.
- [ ] R5.4: Bước chạy 31 ngày tuổi trong tháng chưa tới lúc DROP → lane xóa preview và đối tượng của nó, dòng
      bước còn trạng thái và chi phí; bước 29 ngày còn nguyên payload.
- [ ] R5.5 (TA11): một bộ xóa đăng ký trả một dòng quá hạn kèm lý do bỏ qua → lane không xóa dòng đó và
      `dw_retention_skipped_total{store, reason}` tăng đúng lý do; lane vẫn xóa dòng bị bỏ qua → test đỏ. Ca trên
      bảng sự kiện vào thật (31 ngày có lượt `queued` trỏ tới, 45 ngày bị giữ khi Đóng băng, 31 ngày không ai trỏ
      tới bị xóa) chạy ở workflow-triggers/02 (workflow-triggers:R1.7, workflow-triggers:R6.8).
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `apps/api/src/dw_api/routes/v1/runs.py:41-68`; spec: R4.1 (có `get_run` và `timeline`; thêm danh sách,
  bước, payload).
- `configs/policies/retention@1.7.0.yaml:118-120`; spec: R5.3 (dẫn Nghị định 13 cần bỏ, chuyển compliance-pdpl).
- `apps/web/app/audit/page.tsx:15-25`, `apps/api/src/dw_api/routes/v1/audit.py:27`; spec: R1.7, R1.8 (màn giữ bảng
  nhãn action riêng, route chỉ trả mã `action`).
- `packages/typescript/contracts/src/audit.ts:3-12`, `packages/typescript/api-client/src/client.ts:200-244`; spec:
  R1.8 (bản zod của sự kiện audit chưa có dòng `SameType` nào so với route, và zod bỏ khóa nó không khai).
- `apps/worker/src/dw_worker/main.py:114`, `packages/python/dw_platform/src/dw_platform/retention_policy.py:191-192`;
  spec: R5.9 (worker ghim bản tệp bằng một hằng đường dẫn và đọc nó qua mô hình chính sách).
- `infra/compose/docker-compose.yml:229-245`, `infra/compose/docker-compose.yml:311-312`,
  `infra/compose/docker-compose.yml:469-470`; spec: R5.9 (job một lần `migrate` chạy `alembic upgrade head` dưới
  `dw_migrator`; `api` và `worker` chờ nó với `service_completed_successfully`).
- `packages/python/dw_platform/tests/integration/conftest.py:25`; spec: R5.9 (fixture tích hợp chạy migration, nơi bộ
  nạp chạy tiếp).
- `infra/compose/init/init-databases.sh:23`, `scripts/create_provisioner_role.py:1-18`,
  `db/migrations/sql/0001_platform_grants.sql:52-55`; spec: R5.9 (cụm compose tạo `dw_provisioner` lúc khởi tạo,
  cụm cũ nhận vai qua script, và 0001 coi vai là tùy chọn, nên bộ nạp phải đỏ khi thiếu vai).
- `db/migrations/sql/0001_platform_grants.sql:45-46`,
  `db/migrations/versions/5d9d89ffc716_tenant_offboarding_requests.py:71-78`,
  `db/migrations/versions/648e2f7c3edb_roles_and_permission_sets_read_only_to_.py:39-48`; spec: R5.11 (quyền mặc
  định của schema cho `dw_app` phải thu hẹp theo bảng; `dw_provisioner` nhận quyền theo từng bảng, bọc kiểm vai tồn
  tại).
- ADR-0122 (Accepted) quyết 4, 6, 7; ADR-0106 (Accepted) quyết 4.

## Comments

- 2026-10-23 (agent): gộp B10b telemetry-and-audit 05, 06, 07. `needs-info` vì DO-52 (thời hạn lưu) chờ
  counsel và Đạt. Cột `redaction_log` giữ quyết định che để kiểm; payload lớn theo tham chiếu để xóa theo
  yêu cầu chủ thể (compliance-pdpl ticket 14, W2).
- 2026-10-23 (agent): DO-52 có lời đáp cho W1 (Đạt, 23/10/2026), nên `needs-triage`. Ticket này là chủ
  duy nhất của `retention@1.8.0`; chờ usage-and-limits/03 vì Bước chạy `model_call` ghi từ
  `LimitsMiddleware`; compliance-pdpl/06 chờ ticket này.
- 2026-10-24 (agent): áp quyết định của Đạt ngày 24/10/2026: ticket này là chủ định dạng tệp retention (khóa
  `schema.table`) và các lane, không còn là chủ duy nhất của mọi dòng; thời hạn `usage_events` do
  usage-and-limits/02 thêm, của `budget_counters`, `budget_leases` do usage-and-limits/03, của
  `studio.gate_case_results` do agent-lifecycle/04, của Bản ghi đồng ý và nhật ký gửi do compliance-pdpl/04 (chờ
  ticket này); lane bỏ qua và đếm sự kiện bị giữ khi Đóng băng; xóa trắng `tool_executions.output` qua hàm riêng
  của lane (H:ADR-0122 (Accepted)\~foundations-hardening:R6.3); dòng `STUDIO_EXCLUSIONS` của `run_steps`; đăng ký
  `runs.read_payloads` ở đây.
- 2026-10-24 (agent): áp kiểm nhất quán vòng 3 và các dòng tạm cùng ngày của spec: bỏ khóa của
  `studio.inbound_events`, `studio.trigger_deliveries` và khóa chống trùng khỏi bước 7, vì workflow-triggers/02 tạo
  ba bảng và thêm khóa, bộ xóa và test xóa của chúng (A:telemetry-and-audit:spec\~workflow-triggers/02), nên R5.1 và
  R5.5 ở đây thử phần lane, ca trên bảng thật chạy ở ticket đó; tệp retention là một tệp có phiên bản, ticket này
  đứng sau usage-and-limits/03 trong chuỗi các ticket sửa tệp (C:configs:spec\~telemetry-and-audit/03); chờ
  tenant-rbac/02 vì dòng `runs.read_payloads` nêu cả `tenant_grantable` (C:custom-objects/02\~tenant-rbac/02).
- 2026-10-24 (agent): lượt sửa thứ ba của vòng 4, theo dòng tạm cùng ngày của spec: ticket này tạo catalog hành động
  audit `configs/copy/audit_actions@1.0.0.yaml` của ADR-0122 (Accepted) quyết 6 cùng test AST (bước 8; spec R1.6,
  TA15), vì catalog chưa có chủ; cách các ticket sau thêm tên action chờ lượt `checking-plan-readiness` của spec (Q2).
- 2026-10-24 (agent): lượt sửa thứ tư của vòng 4, theo dòng tạm cùng ngày của spec: catalog hành động là chủ duy nhất
  của nhãn action, nên `GET /api/v1/audit/events` trả `action_label` từ catalog và màn `/audit` bỏ bảng `ACTIONS` riêng
  (bước 9; spec R1.7, R1.8, TA16; `failure-modes.md` #2); bản zod `auditEventSchema` của `@dw/contracts` mang trường
  đó cùng một dòng `SameType` so với route, vì zod bỏ khóa nó không khai, nên thiếu bản zod thì nhãn không tới màn.
- 2026-10-24 (agent): lượt f của vòng 4, theo V4.21 của Đạt và dòng tạm cùng ngày của spec: ticket này tạo bảng
  `platform.retention_terms`, bộ nạp chạy trong job `migrate` dưới vai `dw_provisioner`, hàm đọc hạn
  `platform.retention_term_days` và test lệch bảng (bước 10; spec R5.9-R5.12, TA17-TA19); hàm xóa trắng `output`
  công cụ và hàm xóa payload của Bước chạy không nhận đối số và đọc hạn ở bảng đó (bước 7); compliance-pdpl/06, đã
  chờ ticket này, gọi cùng hàm đọc hạn, nên không cần cạnh mới.
- 2026-10-24 (agent): kiểm lượt f của vòng 4: bước 10 thêm quyền trên `platform.retention_terms` vào các quyền mà
  `scripts/create_provisioner_role.py` cấp lại cho `dw_provisioner`, vì revision chỉ cấp quyền cho vai khi vai đã có,
  nên một cụm nhận vai qua script sau migration sẽ có vai mà bộ nạp vẫn không ghi được bảng; tiêu chí không đổi.
- 2026-10-24 (agent): lượt g của vòng sửa 4, theo V4.26 của Đạt và dòng tạm cùng ngày của spec: Bước chạy mang
  `lane_path` và `iteration_path` do wrapper nút cấp, NOT NULL không DEFAULT (bước 1, 3, 4, 5; spec R3.7, R4.2, TA20);
  ticket này thử hai cột bằng giá trị mà bên gọi đưa, còn vòng lặp và làn song song thật ghi qua wrapper ở ticket của
  workflow-engine, nên ticket này không chờ ticket nào của bậc B và không chặn đường găng YC94. Không thêm cạnh: ticket
  này đã chờ workflow-engine/03, nơi wrapper ra đời.
- 2026-10-24 (agent): kiểm lượt g của vòng sửa 4: bước 1 và tiêu chí R3.7 gọi phần tử `port` của `lane_path` là Nhánh
  ra, như glossary (`docs/platform/CONTEXT.md`, Port), không phải Cổng, chữ glossary dành cho Cổng chất lượng. Không
  thêm cạnh.
