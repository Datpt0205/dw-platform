# 03 — Lịch sử chạy theo bước: `run_steps` có che và lưu giữ, danh sách run, chi tiết bước

Status: needs-triage
Blocked by: 01, .claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md, .claude/plans/studio/field-security/issues/01-mo-hinh-bao-mat-truong.md, .claude/plans/studio/usage-and-limits/issues/02-bang-gia-so-su-dung-va-man-hinh.md, .claude/plans/studio/usage-and-limits/issues/03-han-muc-giu-truoc-va-quyet-toan.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md
Area: studio
Yêu cầu: R1.6, R1.7, R1.8, R1.9, R1.10, R1.11, R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R3.8, R3.9, R3.10, R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, R4.7, R4.8, R4.9, R4.10, R5.1, R5.2, R5.3, R5.4, R5.5, R5.7, R5.8, R5.12, G1, TA4, TA5, TA6, TA10, TA11, TA12, TA13, TA14, TA15, TA16, TA19, TA20, TA23, TA24, TA25, TA26, TA30

## Mục tiêu

Một kho `platform.run_steps` cho mỗi Bước chạy, che bí mật khi ghi và che theo quyền đọc trường của người xem khi đọc,
mỗi Bước chạy mang làn, lần lặp, lần thử, Nhánh ra và lượt con của lần chạy Bước, và một Bước đang chờ có dòng của nó
từ lúc đỗ (V4.26, V4.36); màn Lịch sử chạy đọc dưới `runs.read` theo độ sâu thành một cây có chỗ đang chờ và lý do bị
giữ, và người dựng đọc lượt mô phỏng do chính mình xin (V4.41); mảnh retention, lane lưu giữ và các hàm xóa hẹp của
các kho lát này tạo, trên định dạng mảnh, bộ nạp và hàm đọc hạn của ticket 01 (H-1); một catalog hành động audit và
một catalog mã lý do, mỗi catalog một mảnh mỗi spec, gộp bởi một bộ nạp từ chối khóa trùng, ghim trong release
manifest, có test AST và là chủ duy nhất của nhãn mà màn đọc qua API (spec R1.6-R1.11, R3, R4, R5; H-12, H-21).

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên): `platform.run_steps` phân vùng theo tháng trên `started_at`
   với DEFAULT, RLS ENABLE và FORCE trên cha và DEFAULT cùng migration; `PRIMARY KEY (id, started_at)`;
   cột `tenant_id`, `workspace_id`, `run_id`, `root_run_id`, `seq int`, `kind` CHECK (`node`, `model_call`,
   `tool_call`, `approval`, `sub_run`), `node_id`, `lane_path jsonb NOT NULL` CHECK
   `jsonb_typeof(lane_path) = 'array'` (mỗi phần tử
   `{"step": <id Bước chứa>, "port": <tên Nhánh ra mà loại của nó khai>}`, từ chuỗi gốc tới làn chứa Bước),
   `iteration_path text NOT NULL` (giá trị mà wrapper dẫn vào khóa chống lặp), cả hai không DEFAULT (spec R3.7); ba cột
   của V4.36 ngay trong revision này (spec R3.9, R3.10): `attempt smallint NOT NULL` CHECK `attempt >= 1`, không
   DEFAULT; `port text` NULL CHECK `port <> ''`; `child_run_id uuid` NULL với FK ghép `(tenant_id, child_run_id)` tới
   `platform.worker_runs (tenant_id, id)` qua `uq_worker_runs_tenant_id_id` ON DELETE RESTRICT và index
   `ix_run_steps_child_run (tenant_id, child_run_id) WHERE child_run_id IS NOT NULL`; không cột `branch_key` (H-11);
   `status text NOT NULL` CHECK (`waiting`, `succeeded`, `failed`, `cancelled`), `reason_code text` NULL với CHECK
   `(status = 'waiting') = (reason_code IS NOT NULL)` (spec R3.8), `started_at timestamptz`, `finished_at
timestamptz` (NULL ở dòng `waiting`), `duration_ms`, `error_type`, `input_preview` và `result_preview` (≤ 4 KB),
   `input_ref` và `result_ref` (đường dẫn đối tượng, NULL khi giữ trong dòng), token, `cost_usd numeric(18,8)`,
   `price_book_version`, `redaction_log jsonb NOT NULL DEFAULT '[]'`, `fls_version`; không cột nội dung
   thô; `dw_app` không UPDATE, DELETE trên cha và không giữ quyền nào trên phân vùng nào, kể cả DEFAULT
   (DO-02.2); index `ix_run_steps_run (tenant_id, run_id, seq)`.
2. Đăng ký `run_steps` bằng một dòng `platform.time_partitioned_tables` (`append_only = true`) trong cùng
   migration; không sửa thân `platform.ensure_time_partitions` (studio-skeleton/01 là chủ hàm, hàm tạo
   partition kèm ENABLE/FORCE RLS và policy công ty), cũng không sửa thân hai hàm của usage-and-limits/02. Cùng
   thay đổi: mảnh `configs/policies/retention.d/platform.run_steps.yaml` (bước 7), nên studio-skeleton:R3.7 xanh ngay
   khi đăng ký; một dòng `STUDIO_EXCLUSIONS` cho `platform.run_steps` với lý do "`dw_app` không DELETE; xóa khi
   offboarding bằng `platform.purge_tenant_append_only`" (spec R5.8; studio-skeleton:R4.3). FK RESTRICT của
   `child_run_id` là một cạnh mà thứ tự xóa của offboarding suy ra (H-2), nên offboarding xóa `platform.run_steps`
   trước bảng lượt chạy mà FK đó trỏ tới; ticket này không đặt chỉ mục hay ràng buộc nào trên bảng lượt chạy (H-20).
3. `StepRecorderPort.step_started`, `step_waiting`, `step_finished`; mỗi lời gọi nhận `lane_path`, `iteration_path`,
   `attempt`, `port` và `child_run_id` của lần chạy Bước từ bên gọi và ghi nguyên, không tự tính (wrapper nút của
   workflow-engine cấp chúng từ `WorkflowIR` của lượt, `iteration_path` là giá trị nó dẫn vào khóa chống lặp,
   workflow-engine:R4.5; spec R3.7, R3.9); `step_waiting` nhận thêm `reason_code` của điểm chờ, ghi trong giao dịch của
   bên gọi, là giao dịch ghi dòng `platform.run_waits`, một Bước chạy `status` `waiting` không `finished_at`, và dòng
   kết thúc sau đó của cùng (`kind`, `node_id`, `iteration_path`, `attempt`) mang cùng `started_at` (spec R3.8); Bước
   chạy `model_call` và `tool_call` không có dòng `waiting`. Đường che `redact_mapping`
   bỏ trường bí mật và tham chiếu credential, che trường `Nhạy cảm` bằng hàm quyết quyền đọc trường của field-security,
   preview ≤ 4 KB, payload lớn gzip ở đường dẫn `tenants/{tenant_id}/workspaces/{workspace_id}/run-steps/`, ghi đường
   dẫn và lý do che vào `redaction_log`.
4. Agent: Bước chạy `model_call` và `tool_call` ghi từ `LimitsMiddleware` (usage-and-limits/03) và
   ToolExecutor; đọc token và chi phí mỗi Bước chạy từ Sổ sử dụng của usage-and-limits; Bước chạy của lượt agent không
   nằm trong một Bước quy trình mang `lane_path` `[]`, `iteration_path` rỗng và `attempt` 1, còn Bước chạy con của một
   Bước quy trình mang `lane_path`, `iteration_path` và `attempt` của lần chạy Bước đó.
5. Route (RLS và workspace theo độ sâu):
   `GET /api/v1/runs?artifact_kind&artifact_id&status&trigger_kind&from&to&cursor&limit` (`runs.read`), phân trang
   keyset trên `ix_worker_runs_page` mà workflow-engine/02 dựng (H-20), không đổi cho người dựng (H-17);
   `GET /api/v1/runs/{run_id}/steps` (mỗi Bước chạy mang `status`, `lane_path`, `iteration_path`, `attempt`, `port`,
   `child_run_id`, `reason_code` cùng `reason_label`, `error_type` cùng `error_label`, spec R4.2, R4.6, và
   `effect_unresolved_label`, nhãn của khóa `effect_unresolved` trên dòng mới nhất `waiting` mang `outcome_unknown` của
   một Bước khi lượt đã kết thúc, NULL trên mọi dòng khác, spec R4.10);
   `GET /api/v1/runs/{run_id}/steps/{step_id}/payload?part=in|out` (`runs.read_payloads`, che theo quyền đọc trường của
   người xem, audit `run.payload.viewed` trong cùng giao dịch). Một lượt chạy chạm bản ghi người xem không thấy → 404.
   Đường đọc của người dựng (spec R4.4, R4.5; V4.41): `GET .../steps` và `GET /api/v1/runs/{run_id}`
   (`apps/api/src/dw_api/routes/v1/runs.py:41-64`) trả lượt khi người gọi giữ `runs.read` tới workspace của lượt, hay
   khi lượt có `run_mode` `simulate`, `requested_by` là người gọi và người gọi giữ `studio.workflows.test` tới workspace
   đó theo độ sâu; chi tiết lượt trên nhánh người dựng đi qua cùng hàm che của R3.3 cho giá trị trường của `result` và
   `error`; mọi ca khác → 404 giống hệt id không tồn tại, kể cả người gọi không giữ khóa nào (thay 403 của hôm nay,
   nên `test_reading_a_run_needs_runs_read` đổi sang 404 và vẫn khẳng định không đọc lượt nào), và lượt của công ty khác
   không đọc được qua RLS. Migration của ticket đăng ký khóa `runs.read_payloads` trong `platform.permissions` của
   tenant-rbac/01, với INSERT nêu mọi cột NOT NULL có lúc đó: nhãn tiếng Việt, `scope_kind` `workspace`, `risk`
   `standard` theo bảng phân loại của tenant-rbac/01, và `tenant_grantable` `true` của tenant-rbac/02 (ticket này chờ
   tenant-rbac/02). Khóa `studio.workflows.test` do workflow-engine/01 đăng ký cùng các khóa của loại `workflow`
   (workflow-engine:R1.5; H-19); ticket này đã chờ ticket đó qua workflow-engine/03.
6. Màn `/runs` (antd Table: thời điểm, agent hoặc quy trình, trạng thái, nguồn kích hoạt, thời lượng, chi
   phí, bộ lọc) và `/runs/[id]` (spec R4.7, R4.8, R4.9; V4.36): antd `Tree` cho các Bước chạy theo `lane_path`, mỗi lần
   lặp và mỗi lần thử một nút con, mỗi nút hiện trạng thái của dòng mới nhất của (`kind`, `node_id`, `iteration_path`,
   `attempt`), tên Nhánh ra khi có `port` và liên kết tới `/runs/[child_run_id]` khi có lượt con; Bước có dòng mới nhất
   `waiting` của một lượt chưa kết thúc mang tag "Đang chờ ở đây" kèm `reason_label`; Bước còn `waiting` với
   `outcome_unknown` của một lượt đã kết thúc, vì `deadline_at` hay bị hủy khi Tắt khẩn hay Đóng băng, mang
   `effect_unresolved_label` và không mang tag "Đang chờ ở đây" (H-6, H-22); Descriptions, xem JSON có dấu `Đã ẩn`, token
   và chi phí mỗi Bước chạy, nút "Sao chép trace id"; màn không giữ bảng nhãn nào, mọi nhãn mã lấy từ `reason_label`,
   `error_label` và `effect_unresolved_label` của API.
7. Mảnh retention của các kho lát này tạo hay xóa (spec R5.1, R5.6; H-1), theo định dạng và bộ đọc của ticket 01, mọi
   số ghi UNVERIFIED tới khi luật sư xác nhận trước chạy bóng (DO-52); mảnh của bảng mà spec khác tạo do ticket tạo bảng
   thêm, ticket này không khai lại. Ticket này thêm vào `configs/policies/retention.d/`:
   `platform.run_steps.yaml` (30 ngày, `drop_partition` khi cả tháng quá 30 ngày; lane xóa payload trong dòng và đối
   tượng của bước quá 30 ngày qua một hàm SECURITY DEFINER hẹp không đối số của lane, đọc hạn dưới khóa
   `platform.run_steps` qua `platform.retention_term_days` của ticket 01, vì `dw_app` không UPDATE bảng),
   `objects.run_step_payloads.yaml` (30 ngày, `object_delete`), `platform.worker_runs.payload.yaml` (90 ngày sau kết
   thúc, lane xóa trắng cột payload của lượt chạy), `platform.worker_runs.yaml` (395 ngày sau kết thúc, `row_delete`, bỏ
   qua dòng `memory.items` trỏ tới theo `db/migrations/versions/0007_evidence.py:113-115`),
   `platform.tool_executions.yaml` (30 ngày, `column_clear`: hàm SECURITY DEFINER hẹp không đối số chỉ đặt NULL
   `output` của dòng quá hạn, đọc hạn qua `platform.retention_term_days`, `dw_app` không nhận UPDATE; spec R5.7) và
   `platform.usage_daily.yaml` (760 ngày, `row_delete`); thêm `objects.run_step_payloads` và
   `platform.worker_runs.payload` vào danh sách kho có tên của `dw_platform.retention_policy`. Lane đếm mỗi dòng quá
   hạn mà một bộ xóa đăng ký bỏ qua trên `dw_retention_skipped_total{store, reason}` theo lý do bộ xóa trả (spec R5.3,
   R5.5); test tập bộ xóa. Mảnh, bộ xóa và test xóa của `studio.inbound_events`, `studio.trigger_deliveries` và
   `studio.inbound_dedupe` ở workflow-triggers/02, nơi tạo bảng; ticket này không thêm mảnh nào cho bảng chưa có.
8. Catalog hành động audit theo mảnh (spec R1.6, R1.10; ADR-0122 (Accepted) quyết 6; H-21): thư mục
   `configs/copy/audit_actions.d/`, một mảnh `<spec>.yaml` cho mỗi spec ghi audit, mỗi khóa là một `action` mang một
   nhãn tiếng Việt. Bộ nạp catalog trong `dw_platform`, cạnh `dw_platform.retention_policy`, gộp mọi mảnh của thư mục và
   từ chối nạp, nêu khóa và hai mảnh, khi hai mảnh khai cùng một khóa, kể cả khi hai nhãn giống nhau; composition root
   của API nạp catalog một lần lúc khởi động và truyền nó vào route qua constructor. Ticket này thêm mảnh
   `telemetry-and-audit.yaml` mang nhãn của `run.payload.viewed` (bước 5) và của mỗi `action` mà mã có trước các spec
   Studio ghi; một `action` mà ticket của spec khác đưa vào trước ticket này có nhãn ở mảnh của spec đó, do ticket đó
   thêm trong cùng thay đổi (runtime-hardening/03 với `platform.outbox.replayed`), và ticket này thêm vào đúng mảnh đó
   nhãn còn thiếu mà test AST thấy; không thêm nhãn cho action chưa có mã ghi. Test AST đọc mọi lời ghi sự kiện Nhật ký
   kiểm toán trong `src/` và đỏ, nêu `action`, khi một `action` không có khóa trong catalog gộp hay khóa có nhãn rỗng.
9. Nhãn action có một chủ, catalog của bước 8 (spec R1.7, R1.8; `failure-modes.md` #2): `AuditEventView` của
   `GET /api/v1/audit/events` (`apps/api/src/dw_api/routes/v1/audit.py:17`) thêm `action_label: str | None`, nhãn
   của `action` trong catalog gộp của bước 8, NULL khi catalog không có khóa; kiểm quyền và phân trang của route giữ
   nguyên, và client sinh ra (`packages/typescript/api-client/src/generated/platform.d.ts`) mang trường mới. Màn đọc
   trang qua `listAuditEvents`, nơi bản zod viết tay `auditEventSchema` của `@dw/contracts`
   (`packages/typescript/contracts/src/audit.ts:3-12`) parse phản hồi, và zod bỏ mọi khóa bản zod không khai, nên
   `auditEventSchema` thêm `action_label: z.string().nullable()` và `packages/typescript/api-client/src/client.ts`
   thêm một dòng `SameType` so `AuditEvent` với `Generated["AuditEventView"]` theo kiểu và theo tập khóa, như các
   dòng ở `client.ts:200-244`: bản zod thiếu trường thì biên dịch đỏ, thay vì mọi dòng lặng lẽ hiện
   `Hoạt động hệ thống`. Màn `/audit` hiện `action_label` ở cột Thao tác trong một antd Tag chung cho mọi action,
   `Hoạt động hệ thống` khi trường đó NULL, dòng vẫn hiện; bỏ bảng `ACTIONS` (nhãn và màu theo từng action) cùng chú
   thích PLUG-IN POINT của nó ở `apps/web/app/audit/page.tsx:15-25`. Bước 8 chép nguyên chữ sáu nhãn của bảng đó vào
   mảnh `telemetry-and-audit.yaml`, nên chữ của sáu action đó trên màn không đổi; một action mới thêm nhãn vào mảnh của
   spec ghi nó (H-21), không vào mã web.
10. Catalog mã lý do theo mảnh (spec R1.9, R1.10, R4.6, R4.10; H-12; H-21): thư mục `configs/copy/run_reason_codes.d/`,
    cùng định dạng và cùng bộ nạp với bước 8. Mảnh `telemetry-and-audit.yaml` của ticket này mang nhãn tiếng Việt cho
    mỗi `reason_code` và `error.code` chưa có khóa ở mảnh nào mà mã có trước các spec Studio, hay lời ghi của chính
    ticket này (mã kết quả của ToolExecutor và `LimitsMiddleware` mà bước 4 bắt đầu ghi lên Bước chạy), ghi lên lượt
    chạy hay Bước chạy lúc ticket này vào, cộng khóa `effect_unresolved` ("Không rõ nhà cung cấp đã nhận hay chưa, chưa
    ai xác nhận", H-6) của bước 5 và 6. Mã mà ticket của spec khác ghi (literal ở lời ghi, hay thành viên của bảng mã
    `wf.*` của workflow-engine) có nhãn ở mảnh của spec đó, do ticket ghi mã thêm trong cùng thay đổi, và ticket này
    thêm vào đúng mảnh đó nhãn còn thiếu mà test AST thấy; `outcome_unknown` mang nhãn "Không rõ nhà cung cấp đã nhận hay
    chưa" (V4.30) ở mảnh của ticket ghi nó trước, và không mảnh nào khai lại nó (spec R1.10). Test AST đỏ và nêu mã khi
    một mã ghi không có khóa trong catalog gộp hay khóa có nhãn rỗng. Route của
    bước 5 và route sự cố của ticket 04 mang `reason_label`, `error_label`, `effect_unresolved_label` đọc từ catalog gộp,
    NULL khi không có khóa, và các bản zod của `@dw/contracts` cho Bước chạy mang các trường đó cùng một dòng `SameType`
    như bước 9.
11. Release manifest ghim hai tập mảnh (spec R1.11; H-21): `_copy_bundles` của `scripts/release_manifest.py` đọc đệ
    quy `configs/copy/` và đòi `copy_id`, `version` ở mỗi tệp (`scripts/release_manifest.py:103-120`), nên hàm đó bỏ qua
    hai thư mục `audit_actions.d/` và `run_reason_codes.d/` và thêm cho mỗi tập một mục, `copy_id` là tên thư mục và
    `checksum` là sha256 trên các cặp (tên tệp, nội dung) xếp theo tên tệp, dùng lại hàm băm tập mảnh mà ticket 01 dựng
    cho `retention.d`; `make release-manifest` sinh lại manifest, và `make release-manifest-check` đỏ khi một mảnh đổi mà
    manifest không đổi.

## Tiêu chí chấp nhận

- [ ] R1.6 (TA15): thêm một lời ghi audit với `action` không có khóa trong mảnh nào của `configs/copy/audit_actions.d/`
      → test AST đỏ, nêu tên action; một khóa của một mảnh có nhãn tiếng Việt rỗng → test đỏ; `run.payload.viewed` có
      khóa và nhãn ở mảnh `telemetry-and-audit.yaml`.
- [ ] R1.10 (TA30): hai mảnh thử của `configs/copy/audit_actions.d/` cùng khai `run.started`, với hai nhãn khác nhau hay
      giống nhau → bộ nạp từ chối, nêu khóa và hai mảnh; cùng ca ở `configs/copy/run_reason_codes.d/` → như trên; hai
      mảnh khác khóa → catalog gộp có mọi khóa của cả hai; gỡ kiểm trùng → bộ nạp nhận hai mảnh cùng khóa, test đỏ.
- [ ] R1.11 (TA30): sửa một mảnh mà không chạy `make release-manifest` → `make release-manifest-check` đỏ; manifest
      mang một mục mã băm cho `audit_actions.d` và một cho `run_reason_codes.d`; một mảnh không mang `copy_id` →
      `make release-manifest` vẫn chạy; đổi thứ tự đọc tệp → mã băm không đổi.
- [ ] R1.7 (TA16): đổi nhãn của `run.started` trong một catalog thử → `GET /api/v1/audit/events` trả nhãn mới trong
      `action_label` của sự kiện `run.started`; sự kiện có `action` không có khóa trong catalog → `action_label` NULL,
      dòng vẫn trả.
- [ ] R1.8 (TA16): màn `/audit` nhận qua `listAuditEvents` (phản hồi HTTP giả, parse bằng `auditEventSchema`) một
      trang có sự kiện `run.started` với `action_label` khác nhãn mà bảng `ACTIONS` cũ ghi → cột Thao tác hiện đúng
      `action_label`; `action_label` NULL → hiện `Hoạt động hệ thống`, dòng vẫn hiện; giữ lại bảng `ACTIONS` → test
      màn đỏ; bỏ `action_label` khỏi `auditEventSchema` → dòng `SameType` của `client.ts` không biên dịch.
- [ ] R1.9 (TA25): thêm một lời ghi `reason_code` lên lượt chạy với mã không có khóa trong mảnh nào của
      `configs/copy/run_reason_codes.d/` → test AST đỏ, nêu mã; một khóa có nhãn rỗng → test đỏ; khóa `effect_unresolved`
      có nhãn ở mảnh `telemetry-and-audit.yaml`.
- [ ] R3.1: một node kết thúc → đúng một Bước chạy mang trạng thái, thời điểm, thời lượng, token, chi phí.
- [ ] R3.2 (TA6): input mang một khóa bí mật → preview không có giá trị, `redaction_log` ghi lý do; gỡ bỏ
      bí mật → test đỏ.
- [ ] R3.3 (TA5): người không có quyền đọc `phone` → payload trả dấu `Đã ẩn`; gỡ che → test đỏ.
- [ ] R3.4: payload 4 KB giữ trong dòng; 4 KB cộng một byte → lưu theo tham chiếu, dòng giữ `input_ref`.
- [ ] R3.5 (TA10): mở payload → đúng một sự kiện `run.payload.viewed`; gỡ ghi audit → test đỏ.
- [ ] R3.6 (TA4): `GET /api/v1/runs/{run_id}/steps` của lượt chạy công ty B từ A → 404; danh sách
      `GET /api/v1/runs` không có lượt chạy công ty khác.
- [ ] R3.7 (TA20): hai lần chạy cùng một Bước ở hai lần lặp, ghi qua `StepRecorderPort` với giá trị mà bên gọi đưa như
      wrapper đưa → hai Bước chạy có `iteration_path` khác nhau, bằng đúng giá trị trong hai khóa chống lặp
      `wf:{run_id}:{node_id}:{iteration_path}` mà bên gọi dựng; một Bước ở làn `rejected` của một Bước phê duyệt →
      `lane_path` nêu Bước phê duyệt và Nhánh ra `rejected`; INSERT thiếu `lane_path` hay `iteration_path` → NOT NULL
      từ chối; bên ghi thay `iteration_path` của bên gọi bằng chuỗi rỗng → hai Bước chạy không phân biệt được, test đỏ;
      thêm DEFAULT `'[]'` cho `lane_path` trong migration thử → INSERT thiếu cột qua, test đỏ.
- [ ] R3.8 (TA24): bên gọi báo một Bước phê duyệt đỗ trong giao dịch ghi dòng `platform.run_waits` → cùng giao dịch có
      một Bước chạy `waiting` mang `reason_code` của điểm chờ, trước mọi quyết định; rollback giao dịch đó → không dòng
      nào; quyết định tới → thêm dòng kết thúc cùng `started_at`, dòng `waiting` còn nguyên; INSERT dòng `waiting`
      thiếu `reason_code`, hay dòng `succeeded` mang `reason_code` → CHECK từ chối; gỡ lời ghi lúc đỗ → lượt chờ duyệt
      không có dòng nào của Bước đang chờ, test đỏ.
- [ ] R3.9 (TA23): hai lần thử của cùng một Bước ở cùng `iteration_path` → hai Bước chạy `attempt` 1 và 2; Bước
      `switch` đi nhánh `hot` → `port` `hot`; Bước phê duyệt bị từ chối → `port` `rejected`; Bước mở lượt con →
      `child_run_id` của lượt đó; INSERT `attempt` 0 hay thiếu `attempt` → CHECK hay NOT NULL từ chối; `port` rỗng →
      CHECK từ chối; bên ghi tự tính `attempt` thay giá trị của bên gọi → test đỏ.
- [ ] R3.10 (TA23): `dw_app` gắn công ty A chèn Bước chạy mang `child_run_id` của một lượt công ty B → lỗi FK 23503,
      không dòng nào; migration thử đổi FK ghép thành FK một cột `child_run_id` → ca đó qua, test đỏ.
- [ ] R4.1: người giữ `runs.read` gọi `GET /api/v1/runs` → chỉ lượt chạy trong tập workspace được phép;
      trang 2 không trùng và không sót dòng so với trang 1.
- [ ] R4.2 (TA20): `GET /api/v1/runs/{run_id}/steps` → các Bước chạy theo thứ tự `seq`, mỗi Bước mang `status`,
      `lane_path`, `iteration_path`, `attempt`, `port`, `child_run_id` và `reason_code` đúng như đã ghi, một Bước đã chờ
      trả cả dòng `waiting` lẫn dòng kết thúc; bỏ một trường khỏi mô hình trả → test đỏ.
- [ ] R4.3 (TA12): thiếu `runs.read_payloads` gọi payload → 403, không trả payload; gỡ kiểm → test đỏ.
- [ ] R4.4 (TA26): người chỉ giữ `studio.workflows.test` tới workspace của lượt gọi `GET .../steps` và
      `GET /api/v1/runs/{run_id}` cho lượt `simulate` mình xin → 200, giá trị `phone` mà người đó không được đọc là
      `Đã ẩn` trong chi tiết lượt; người đó mất `studio.workflows.test` ở workspace đó → 404; bỏ điều kiện `run_mode`
      → lượt `live` của chính người đó đọc được, test đỏ.
- [ ] R4.5 (TA26): lượt `simulate` của người khác → 404 giống hệt phản hồi cho một id ngẫu nhiên; lượt `live` mà người
      gọi không giữ `runs.read` → 404; người gọi không giữ khóa nào → 404 mà route không đọc lượt nào; lượt `simulate`
      mình xin ở công ty A, gọi bằng ngữ cảnh công ty B → 404; `GET /api/v1/runs` của người chỉ giữ
      `studio.workflows.test` không trả lượt mô phỏng nào (H-17); bỏ điều kiện `requested_by`, hay chạy truy vấn bằng
      vai bỏ qua RLS → test đỏ.
- [ ] R4.6 (TA25): đổi nhãn của `outcome_unknown` trong một catalog thử → `GET .../steps` trả nhãn mới trong
      `reason_label` của dòng `waiting` mang mã đó; mã không có khóa → `reason_label` NULL, dòng vẫn trả; `error_type`
      của một lần thử lỗi → `error_label` đúng nhãn của catalog; bỏ một trường nhãn khỏi bản zod → dòng `SameType` không
      biên dịch.
- [ ] R4.7: màn `/runs/[id]` với client giả vẽ một lượt có làn song song, vòng lặp hai lần lặp, một Bước hai lần thử và
      một lượt con → cây antd `Tree` có đúng các nút làn, lần lặp và lần thử, tên Nhánh ra của Bước rẽ nhánh và liên kết
      tới `/runs/[child_run_id]`; sai nếu hai lần thử gộp thành một nút; Playwright mở màn ở 320 px, không cuộn ngang.
- [ ] R4.8 (TA24): lượt `waiting` có một Bước mà dòng mới nhất `waiting` với `outcome_unknown` → Bước đó mang "Đang chờ
      ở đây" và "Không rõ nhà cung cấp đã nhận hay chưa" từ `reason_label`; lượt chờ duyệt → Bước phê duyệt mang "Đang
      chờ ở đây" và nhãn của mã chờ duyệt; màn giữ một bảng nhãn riêng → nhãn đổi ở catalog thử không hiện, test màn đỏ.
- [ ] R4.9 (TA24): lượt đã `cancelled` vì `deadline_at`, hay bị hủy khi Tắt khẩn, mà một Bước còn dòng mới nhất
      `waiting` với `outcome_unknown` → Bước đó mang "Không rõ nhà cung cấp đã nhận hay chưa, chưa ai xác nhận" từ
      `effect_unresolved_label` và không mang "Đang chờ ở đây"; Bước còn `waiting` với mã khác ở lượt đã kết thúc → không
      mang nhãn đó.
- [ ] R4.10 (TA25): `GET .../steps` của một lượt đã kết thúc mà một Bước còn dòng mới nhất `waiting` với
      `outcome_unknown` → dòng đó mang `effect_unresolved_label` đúng nhãn của khóa `effect_unresolved` trong catalog
      thử, mọi dòng khác NULL; cùng Bước ở một lượt còn `waiting` → NULL; đổi nhãn của khóa đó trong catalog thử → nhãn
      mới; bỏ trường khỏi bản zod → dòng `SameType` không biên dịch.
- [ ] R5.1 (TA13): mỗi kho (`run_steps`, payload đối tượng, cột payload, `usage_events`, `usage_daily`) có mảnh của nó
      trong tập mảnh đang ghim, mang một thời hạn và một bộ xóa đã đăng ký; test tập bộ xóa này cũng phủ
      `studio.inbound_events`, `studio.trigger_deliveries` khi workflow-triggers/02 thêm mảnh và bộ xóa của chúng
      (workflow-triggers:R6.3, workflow-triggers:R6.7).
- [ ] R5.7 (TA14): dòng `tool_executions` 31 ngày tuổi → sau một lượt lane, `output` NULL, cột khác giữ nguyên;
      dòng 29 ngày giữ `output`; `dw_app` UPDATE thẳng → `permission denied`; hàm đặt NULL thêm một cột → test đỏ;
      hạ dòng `platform.tool_executions` của `platform.retention_terms` còn 20 ngày → dòng 21 ngày bị xóa trắng; hàm
      giữ hằng 30 ngày hay nhận mốc làm đối số → test đỏ.
- [ ] R5.12 (TA19): xóa dòng `platform.tool_executions` khỏi bảng thử → hàm xóa trắng `output` báo lỗi `P0002`,
      không dòng nào đổi; xóa dòng `platform.run_steps` → hàm xóa payload bước báo lỗi, không payload nào mất; hàm xóa
      hẹp tự giữ một hạn dự phòng khi `platform.retention_term_days` báo lỗi → test đỏ.
- [ ] R5.8: công ty `offboarding` có dòng `run_steps` → lane `offboarding` xuất mỗi dòng một lần rồi xóa hết qua
      `platform.purge_tenant_append_only`; test phủ offboarding (studio-skeleton:R4.3) xanh với dòng
      `STUDIO_EXCLUSIONS` của `platform.run_steps`.
- [ ] R5.2 (TA13): một lớp retention thiếu bộ xóa → test tập bộ xóa đỏ; một mảnh `enforced: true` có `purger` mà không bộ
      xóa nào đăng ký cho kho của nó → đỏ, nêu tệp; một mảnh `enforced: false` không có bộ xóa → xanh khi `description`
      nêu ticket hay câu hỏi còn nợ bộ xóa, đỏ khi không nêu; `make retention-unenforced` in mọi mảnh `enforced: false`
      cùng lý do, bằng chứng cho cổng E3 (YC99) (H-33).
- [ ] R5.3 (TA11): lượt chạy `waiting_approval` 400 ngày còn nguyên; lượt chạy được `memory.items` trỏ tới
      → bỏ qua, được đếm.
- [ ] R5.4: Bước chạy 31 ngày tuổi trong tháng chưa tới lúc DROP → lane xóa preview và đối tượng của nó, dòng
      bước còn trạng thái và chi phí; bước 29 ngày còn nguyên payload.
- [ ] R5.5 (TA11): một bộ xóa đăng ký trả một dòng quá hạn kèm lý do bỏ qua → lane không xóa dòng đó và
      `dw_retention_skipped_total{store, reason}` tăng đúng lý do; lane vẫn xóa dòng bị bỏ qua → test đỏ. Ca trên
      bảng sự kiện vào thật (31 ngày có lượt `queued` trỏ tới, 45 ngày bị giữ khi Đóng băng, 31 ngày không ai trỏ
      tới bị xóa) chạy ở workflow-triggers/02 (workflow-triggers:R1.7, workflow-triggers:R6.8).
- [ ] G1: `test_the_callers_own_run_is_read` xanh với route mới; người giữ `runs.read` đọc lượt `live` trong workspace
      của mình → 200 như trước.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `apps/api/src/dw_api/routes/v1/runs.py:41-68`; spec: R4.1 (có `get_run` và `timeline`; thêm danh sách,
  bước, payload).
- `apps/api/src/dw_api/routes/v1/runs.py:47-52`, `apps/api/tests/unit/test_run_and_audit_reads.py:225-234`,
  `apps/api/tests/unit/test_run_and_audit_reads.py:250-259`; spec: R4.4, R4.5, G1 (route kiểm `runs.read` và trả 403
  trước khi đọc lượt; test 403 đổi sang 404, test của G1 giữ nguyên).
- `configs/policies/retention@1.7.0.yaml:118-120`; spec: R5.3 (dẫn Nghị định 13 cần bỏ, chuyển compliance-pdpl).
- `apps/web/app/audit/page.tsx:15-25`, `apps/api/src/dw_api/routes/v1/audit.py:27`; spec: R1.7, R1.8 (màn giữ bảng
  nhãn action riêng, route chỉ trả mã `action`).
- `packages/typescript/contracts/src/audit.ts:3-12`, `packages/typescript/api-client/src/client.ts:200-244`; spec:
  R1.8 (bản zod của sự kiện audit chưa có dòng `SameType` nào so với route, và zod bỏ khóa nó không khai).
- `db/migrations/versions/0007_evidence.py:113-115`; spec: R5.3 (`memory.items` trỏ tới lượt chạy).
- `scripts/release_manifest.py:103-120`; spec: R1.11 (`_copy_bundles` đọc đệ quy `configs/copy/` và đòi `copy_id`,
  `version` ở mỗi tệp).
- ADR-0122 (Accepted) quyết 4, 6, 7; ADR-0106 (Accepted) quyết 4; ADR-0104 (Accepted) quyết 3; V4.36, V4.41; H-11,
  H-12, H-17, H-19, H-20, H-21, H-22.

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
  của lane (H:ADR-0122 (Accepted)\~runtime-hardening:R6.3); dòng `STUDIO_EXCLUSIONS` của `run_steps`; đăng ký
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
- 2026-10-25 (agent): lượt h, theo V4.30, V4.31, V4.36, V4.41 của Đạt và H-1, H-11, H-12, H-17 (các dòng cùng ngày của
  spec): định dạng của chính sách retention, bộ nạp, `platform.retention_terms`, `platform.retention_term_days`, test
  lệch bảng và test phủ dời về ticket 01 (R5.6, R5.9-R5.11 và TA17, TA18 rời dòng Yêu cầu; R5.12 và TA19 ở cả hai
  ticket: hàm đọc hạn ở ticket 01, hàm xóa hẹp ở đây), bước 7 thành các mảnh của kho lát này, và ticket này chờ ticket
  01 (mục B của lượt h); `run_steps` có `attempt`, `port`, `child_run_id`, `reason_code` và dòng `waiting` ngay từ
  revision tạo bảng (bước 1, 3; R3.8-R3.10, TA23, TA24); màn `/runs/[id]` là cây có chỗ đang chờ và lý do (bước 6;
  R4.7-R4.9); catalog mã lý do với test AST và nhãn trên API (bước 10; R1.9, R4.6, TA25); người dựng đọc lượt mô phỏng
  của chính mình, mọi ca khác 404 (bước 5; R4.4, R4.5, G1, TA26). Thứ tự với workflow-triggers/01, nơi khóa
  `studio.workflows.test` ra đời, là Q4 của spec: cạnh ticket này chờ ticket đó làm `marketing-pilot/03` sâu 16 (đã chạy
  `g.py`), nên chưa thêm.
- 2026-10-26 (agent): lượt h, đợt 2, theo H-19, H-20, H-21, H-22 (các dòng tạm 25/10/2026 của spec): khóa
  `studio.workflows.test` do workflow-engine/01 đăng ký, ticket mà ticket này đã chờ qua workflow-engine/03, nên câu hỏi
  về cạnh với workflow-triggers/01 ở dòng trên khép lại, không thêm cạnh (bước 5); `ix_worker_runs_page` dời sang
  workflow-engine/02, ticket này chỉ phân trang trên nó và không đặt chỉ mục hay ràng buộc nào trên bảng lượt chạy, nên
  không chờ ticket 02 (bước 2, 5); hai catalog nhãn thành mảnh mỗi spec dưới `configs/copy/audit_actions.d/` và
  `configs/copy/run_reason_codes.d/`, bộ nạp từ chối khóa trùng và release manifest ghim mã băm mỗi tập (bước 8-11;
  R1.10, R1.11, TA30); route Bước chạy mang `effect_unresolved_label` để màn không giữ chữ của tác động chưa giải, kể
  cả ở lượt bị hủy khi Tắt khẩn (bước 5, 6; R4.9, R4.10). Payload của lượt mô phỏng mà người dựng tự xin là Q7 của
  spec (Đạt đáp 26/10: không, Q-h4); R4.3 vẫn trả 403 khi thiếu `runs.read_payloads`. Không đổi dòng Blocked by.
