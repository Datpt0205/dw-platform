# 01 — Module ánh xạ OTel GenAI ghim commit, không nội dung; metric phát hoặc xóa; mảnh retention và bảng thời hạn

Status: resolved (2026-10-27, main)
Blocked by: .claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md
Area: studio
Yêu cầu: R1.1, R1.2, R1.3, R1.4, R1.5, R5.6, R5.9, R5.10, R5.11, R5.12, R5.13, R5.14, TA1, TA2, TA3, TA8, TA9, TA17, TA18, TA19, TA27

## Mục tiêu

Một chủ cho mọi tên span, khóa thuộc tính và tên metric GenAI, ghim theo một commit semconv, có test hợp
đồng; span, log, Nhật ký kiểm toán và lỗi chỉ mang định danh và tên trường; bảy metric khai mà không phát
được phát hoặc xóa (spec R1). Cùng ticket, vì đây là ticket sớm nhất của lát: chính sách lưu giữ một mảnh mỗi kho, bộ
đọc tập mảnh, mã băm của tập trong release manifest, bảng `platform.retention_terms` với bộ nạp, hàm đọc hạn và test
lệch bảng, và mảnh `platform.audit_events` thay ánh xạ tạm sang `retention@1.7.0` (spec R5.6, R5.9-R5.14; H-1; V4.21),
để ticket nào cần chúng chỉ chờ ticket này, không chờ ticket 03.

## Việc cần làm

1. `packages/python/dw_observability/src/dw_observability/semconv.py`: hằng `GENAI_SEMCONV_COMMIT` ghim một
   commit của `open-telemetry/semantic-conventions-genai` (ADR-0122 (Accepted) quyết 1); hàm dựng tên span
   (`invoke_workflow`, `dw.node`, `invoke_agent`, `chat`, `execute_tool`, `retrieval`), khóa thuộc tính `dw.*`, tên
   metric GenAI, và danh sách định danh cho phép mà test hợp đồng, formatter log và span processor Langfuse cùng đọc
   (spec R1.4, R1.5); ảnh chụp `contracts/telemetry/genai-semconv@<sha12>.json` sinh từ YAML thượng nguồn ở commit đó,
   không từ `semconv.py`, cộng các tên `semconv.py` khai: `dw.*`, tên span mà YAML không có và tên `dw_*` của
   `ALL_METRICS` (spec R1.1), và `--check` trong CI.
2. Test hợp đồng: chạy gateway, middleware, executor và runner qua một `RecordingTelemetry`, đỏ nếu một tên
   phát ra nằm ngoài ảnh chụp đã ghim (TA2).
3. Thay `gen_ai.system` bằng `gen_ai.provider.name`
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/telemetry_usage.py:60`);
   `gen_ai.response.model` lấy từ phản hồi; sửa docstring `dw_observability/__init__.py:1`.
4. `TelemetryPort.record_histogram` với ranh giới bucket của spec, mục Trong phạm vi; `OtelTelemetry` dùng `create_histogram` và View;
   `RecordingTelemetry.histograms`; `NullTelemetry`.
5. Phát `dw_run_duration_seconds`, `dw_tool_call_total`, `dw_approval_wait_seconds`; gỡ `DW_NODE_FAILURE_TOTAL` khỏi
   `dw_observability/metrics.py` và `ALL_METRICS`, vì chưa có nơi phát: workflow-engine/03 khai lại hằng
   `dw_node_failure_total{error_type}` cùng lời gọi phát ở bộ bọc node (`failure-modes.md` #1; Đạt, 27/10/2026);
   xóa `dw_retrieval_hit_rate`, `dw_human_intervention_rate`, `dw_task_success_rate`; test AST: mọi tên trong
   `ALL_METRICS` là đối số đầu của `add_metric`, `set_gauge` hay `record_histogram` trong `src/` (TA3).
6. Formatter log JSON cho API và worker chỉ giữ các khóa trong danh sách định danh cho phép của bước 1, bỏ mọi khóa
   khác; `message` là tên sự kiện hằng, không phải chuỗi định dạng mang giá trị; giá trị dạng email, số điện thoại hay
   query string bị bỏ cả khi khóa được phép; `test_logs_carry_ids_only` (spec R1.5; TA8).
7. Một span processor lắp trên mọi exporter, OTLP và Langfuse khi bật, chỉ chuyển các khóa trong danh sách định danh cho phép của bước 1, bỏ mọi khóa
   khác, kể cả `user.id`, `gen_ai.input.messages`, đầu ra, `exception.message`, `exception.stacktrace`, mô tả status và khóa
   nội dung mà thượng nguồn thêm sau (spec R1.4; TA9).
8. Một chủ cho định danh (spec R1.2; TA1): span, dòng log, sự kiện Nhật ký kiểm toán và thông điệp lỗi chỉ mang định
   danh và tên trường, vì span và log đi qua danh sách cho phép của bước 1, còn `details` của sự kiện audit và thông
   điệp lỗi do mã dựng chỉ nhận định danh và tên trường, không nhận giá trị của input.

Chính sách lưu giữ theo mảnh (spec R5.6, R5.9-R5.14; H-1; dời từ ticket 03, bước 7 phần định dạng và bước 10):

9. Định dạng mảnh và bộ đọc tập mảnh: thư mục `configs/policies/retention.d/`, một tệp `<schema>.<table>.yaml` cho mỗi
   kho, tên tệp là khóa của kho; kho không phải bảng dùng tên có tiền tố có trong danh sách kho có tên của
   `dw_platform.retention_policy`, mà ticket tạo kho thêm vào (ticket 03 thêm `objects.run_step_payloads` và
   `platform.worker_runs.payload`). Mỗi mảnh mang đúng bốn khóa: `days` (số nguyên dương; `indefinite` khi kho không hết hạn theo thời gian; hay `null` khi chưa ai
   quyết), `purger` (`drop_partition` qua `platform.drop_expired_partitions`, `row_delete`, `object_delete`,
   `column_clear`, hay `none` chỉ khi `days: indefinite`), `enforced` (bool) và `description`; mô hình Pydantic của mảnh
   từ chối khóa lạ, `purger: none` với `days` khác `indefinite` và `days: indefinite` với `purger` khác `none` (H-31). Cùng bộ đọc, ticket này khai sổ bộ xóa
   `RetentionPurgerRegistry` (khóa của kho → một bộ xóa không đối số, đóng băng ở composition root của worker, trùng khóa
   → lỗi lúc dựng), để ticket tạo kho đăng ký bộ xóa của nó mà không chờ lane lưu giữ của ticket 03, và ticket 03 chạy
   mọi bộ xóa trong sổ (H-35). Mô hình chính sách
   `dw_platform.retention_policy` đọc tập mảnh và trả thời hạn của mỗi kho chỉ từ mảnh của nó (spec R5.13); gỡ ánh xạ
   tạm `audit.tables.audit_events` → `platform.audit_events` mà studio-skeleton/01 dựng. Test tập mảnh: mỗi tên tệp
   khớp `<schema>.<table>` của một bảng có thật trong `pg_class` hay một kho có tên, mỗi tệp đúng mô hình (spec R5.6).
10. Mảnh `configs/policies/retention.d/platform.audit_events.yaml` (`days: 1095`, `purger: drop_partition`,
    `enforced: true`, `description` chép từ `audit.tables.audit_events` của `retention@1.7.0`); chú thích căn cứ pháp lý
    của thời hạn đó do compliance-pdpl/06 viết vào mảnh, bỏ dẫn Nghị định 13/2023. Thay
    `configs/policies/retention@1.7.0.yaml` bằng `configs/policies/retention@1.8.0.yaml`: bỏ `audit.enforced` và
    `audit.tables` (đã sang mảnh) cùng chú thích "model_usage_ledger đã bị bỏ", giữ mọi mục khác (`classes`,
    `knowledge`, `audit.months_ahead`, `checkpoints`, `channel_deliveries`, `batch_limit`); không ticket nào khác sửa tệp
    có phiên bản đó. Hằng `RETENTION_POLICY_PATH` (`apps/worker/src/dw_worker/main.py:114`) chuyển vào
    `dw_platform.retention_policy`, trỏ 1.8.0, cạnh hằng đường dẫn thư mục mảnh, nên worker, bộ nạp và
    `test_the_pinned_retention_policy_promises_only_classes_code_can_assign` đọc cùng một chỗ ghim. Lane `partitions`
    đọc thời hạn `platform.audit_events` từ mảnh.
11. `scripts/release_manifest.py`: `_policies` thêm một mục cho tập mảnh, `policy_id` `retention.d` và `checksum` là
    sha256 trên các cặp (tên tệp, nội dung) xếp theo tên tệp; `make release-manifest` sinh lại manifest, và
    `make release-manifest-check` đỏ khi một mảnh đổi mà manifest không đổi (spec R5.14).
12. Bảng thời hạn ở runtime (spec R5.9, R5.10, R5.11, R5.12; V4.21):
    - Revision Alembic mới (id hex ngẫu nhiên): `platform.retention_terms` (`store_key text PRIMARY KEY`,
      `term_days integer NOT NULL` CHECK `term_days > 0`, tên ràng buộc theo `NAMING_CONVENTION`), không
      `tenant_id`, không RLS; `REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON platform.retention_terms FROM dw_app` như
      migration `648e2f7c3edb`, vì quyền mặc định của schema cấp INSERT, UPDATE, DELETE, và `dw_app` giữ SELECT;
      `GRANT SELECT, INSERT, UPDATE, DELETE` cho `dw_provisioner` theo bảng, bọc trong kiểm vai tồn tại như các
      migration cấp quyền cho vai đó; dòng của bảng trong
      `packages/python/dw_platform/tests/integration/test_privileges.py`. Cùng revision: hàm
      `platform.retention_term_days(p_store_key text) RETURNS integer` STABLE, `search_path` cố định, trả
      `term_days` của khóa và RAISE với SQLSTATE `P0002` nêu khóa khi không có dòng; REVOKE ALL FROM PUBLIC, không vai
      nào nhận EXECUTE, vì chỉ các hàm xóa hẹp SECURITY DEFINER gọi nó (của ticket 03 và của compliance-pdpl/06).
    - Bộ nạp trong `dw_platform`, cạnh `dw_platform.retention_policy`: đọc tập mảnh đang ghim qua mô hình chính sách,
      lấy mỗi mảnh có `days` và `enforced: true`, rồi trong một giao dịch dưới vai `dw_provisioner` thêm, sửa và xóa
      dòng tới khi bảng đúng bằng tập đó; đọc mảnh hay nối CSDL hỏng thì thoát mã khác 0 và không đổi dòng nào.
    - Job `migrate` của `infra/compose/docker-compose.yml` chạy bộ nạp ngay sau `alembic upgrade head`, với
      `DW_PROVISIONER_DATABASE_URL`; `api` và `worker` đã chờ job đó với `service_completed_successfully`, nên khởi
      động sau khi bảng khớp tập mảnh. Fixture tích hợp chạy bộ nạp ngay sau `alembic upgrade head`. Bộ nạp cần vai
      `dw_provisioner`, mà mọi cụm compose tạo lúc khởi tạo và một cụm cũ hơn nhận qua
      `scripts/create_provisioner_role.py`; script đó thêm SELECT, INSERT, UPDATE, DELETE trên
      `platform.retention_terms` vào các quyền nó cấp lại, vì revision bỏ qua lệnh GRANT khi vai chưa có lúc migration
      chạy, mà script hứa chạy được trước hay sau migration (`scripts/create_provisioner_role.py:1-18`); thiếu vai thì
      bộ nạp không nối được và job `migrate` thoát mã khác 0, nên lần triển khai dừng thay vì chạy với một bảng thời
      hạn rỗng.
    - Test lệch bảng so `platform.retention_terms` với tập mảnh có `days` và `enforced: true` đang ghim, đỏ và nêu
      khóa khi một khóa thiếu, thừa hay khác hạn; một test đọc tệp compose đỏ khi lệnh của `migrate` không chạy bộ nạp
      sau migration, hay `api`, `worker` không chờ `migrate`.
13. Test phủ: test catalog của studio-skeleton:R3.7 chạy trên bộ đọc tập mảnh, nên mỗi bảng `append_only = true` của
    `platform.time_partitioned_tables` cần mảnh của nó (spec R5.13).

## Tiêu chí chấp nhận

- [ ] R1.1 (TA2): đổi một tên span trong `semconv` → test hợp đồng đỏ; tên ngoài ảnh chụp không được nhận; đổi một tên
      `gen_ai.*` sang tên không có ở YAML thượng nguồn rồi sinh lại ảnh chụp → test vẫn đỏ; sinh ảnh chụp từ
      `semconv.py` → ca đó xanh, test đỏ.
- [ ] R1.2 (TA1): input có một số điện thoại → không span, log hay sự kiện Nhật ký kiểm toán nào chứa giá
      trị đó.
- [ ] R1.3 (TA3): thêm một hằng vào `ALL_METRICS` không có lời gọi phát → test AST đỏ; ba metric tỷ lệ và
      `dw_node_failure_total` không còn trong `ALL_METRICS`; `make ci` xanh ở ticket này.
- [ ] R1.4 (TA9): span processor bỏ `user.id` và `gen_ai.input.messages`; gỡ bỏ → test exporter đỏ; một khóa nội
      dung mới không có trong danh sách cho phép (`gen_ai.system_instructions`) → không tới Langfuse; đổi processor
      sang danh sách cấm → test đỏ; span xuất qua OTLP mang `exception.message` có số điện thoại → exporter bộ nhớ không
      thấy khóa đó; processor chỉ lắp cho Langfuse → ca OTLP thấy giá trị, test đỏ; span của `dw_run_duration_seconds`
      và ba metric `dw_*` được phát không làm test hợp đồng đỏ.
- [ ] R1.5 (TA8): một dòng log mang giá trị dạng email → `test_logs_carry_ids_only` đỏ; `message` mang giá trị nội suy
      → đỏ; một khóa ngoài danh sách cho phép → bị bỏ khỏi dòng.
- [ ] R5.6 (TA27): mảnh tên `platform.no_such_table.yaml`, hay `audit_events.yaml` thiếu schema → test tập mảnh đỏ, nêu
      mảnh; kho có tên của fixture → nhận; hai bảng thử cùng tên ở `platform` và `studio` mang hai thời hạn khác nhau →
      mỗi bảng đọc đúng thời hạn của mình; mảnh có khóa ngoài bốn khóa → lỗi mô hình, nêu khóa.
- [ ] R5.13 (TA27): gỡ mảnh `platform.audit_events` → mô hình chính sách không trả hạn nào cho bảng đó và test catalog
      của studio-skeleton:R3.7 đỏ, nêu bảng; giữ lại ánh xạ tạm sang `retention@1.7.0` → ca gỡ mảnh vẫn trả hạn, test
      đỏ; với mảnh, lane `partitions` vẫn chỉ xóa những tháng `audit_events` nằm trọn sau 1095 ngày
      (`test_a_term_drops_only_the_months_entirely_behind_it` xanh).
- [ ] R5.14 (TA27): sửa một mảnh mà không chạy `make release-manifest` → `make release-manifest-check` đỏ; manifest
      mang mục `retention.d` với mã băm của tập; đổi thứ tự đọc tệp → mã băm không đổi.
- [ ] R5.9 (TA17): bộ nạp chạy trên tập mảnh thử A rồi tập mảnh thử B (một hạn đổi, một mảnh bỏ, một mảnh thêm, một
      mảnh `enforced: false`, một mảnh `days: indefinite`) → `platform.retention_terms` đúng bằng tập mảnh có `days` là số
      và `enforced: true` của B, không dòng của mảnh `indefinite`; mảnh `days: indefinite` với `purger: row_delete` hay
      `days: null` với `purger: none` → mô hình mảnh từ chối, nêu tệp; bộ
      nạp bỏ bước xóa dòng → dòng của mảnh bỏ còn, test đỏ; lệnh của job `migrate` không chạy bộ nạp sau
      `alembic upgrade head`, hay `api`, `worker` không chờ `migrate` → test tệp compose đỏ.
- [ ] R5.10 (TA17): sửa tay hạn một dòng, chèn một khóa thừa hay xóa một dòng → test lệch bảng đỏ, nêu khóa; bảng
      vừa nạp từ tập mảnh đang ghim → xanh.
- [ ] R5.11 (TA18): `dw_app` INSERT, UPDATE, DELETE trên `platform.retention_terms` → `permission denied`, bảng
      không đổi; `test_privileges.py` khẳng định `dw_app` chỉ SELECT, `dw_provisioner` SELECT, INSERT, UPDATE,
      DELETE; bỏ lệnh REVOKE của revision → test đỏ.
- [ ] R5.12 (TA19): `platform.retention_term_days` hỏi một khóa không có dòng → lỗi `P0002` nêu khóa, không trả hạn;
      hàm trả hạn mặc định hay NULL khi thiếu dòng → test đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_observability/src/dw_observability/metrics.py:12-22`; spec: R1.3.
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/telemetry_usage.py:60`; spec: R1.1.
- `configs/policies/retention.d/platform.audit_events.yaml:1-16`, `configs/policies/retention@1.8.0.yaml:69-81`; spec:
  R5.13 (thời hạn `audit_events` và chú thích về `model_usage_ledger`, dòng 111-122 và 72 của `retention@1.7.0.yaml` ở
  `ab33703`, nay là mảnh và tệp thay nó).
- `apps/worker/src/dw_worker/main.py:114`, `packages/python/dw_platform/src/dw_platform/retention_policy.py:191-192`,
  `apps/worker/tests/unit/test_worker.py:176`; spec: R5.9 (worker ghim bản tệp bằng một hằng đường dẫn và đọc nó qua
  mô hình chính sách).
- `scripts/release_manifest.py:89-100`; spec: R5.14 (manifest ghim mỗi tệp `configs/policies/*.yaml`, không đọc thư mục
  con).
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
- ADR-0122 (Accepted) quyết 1, 2, 3, 7; ADR-0100 (Accepted) quyết 7; studio-skeleton:R3.7.
- `packages/python/dw_observability/src/dw_observability/metrics.py:13`; spec: R1.3 (`DW_NODE_FAILURE_TOTAL` khai mà
  không có nơi phát trong `src/`).

## Comments

- 2026-10-23 (agent): gộp B10b telemetry-and-audit 01, 04; B11 compliance-pdpl 06 (telemetry không nội
  dung) và B4 field-security 05 (log chỉ id) về đây làm một chủ.
- 2026-10-25 (agent): lượt h, theo V4.31 của Đạt và H-1 (dòng tạm cùng ngày của spec): ticket này, ticket sớm nhất của
  lát, nhận từ ticket 03 định dạng của chính sách retention, nay là một mảnh mỗi kho, bộ đọc tập mảnh, bảng
  `platform.retention_terms` với bộ nạp, `platform.retention_term_days` và test lệch bảng (bước 9-13; spec R5.6,
  R5.9-R5.14, TA17-TA19, TA27), gỡ ánh xạ tạm sang `retention@1.7.0` của studio-skeleton/01 và thêm mảnh
  `platform.audit_events`; lane lưu giữ và các hàm xóa của lát vẫn ở ticket 03. Thêm Blocked by studio-skeleton/01,
  cạnh ngoài mục B của lượt h, vì ticket này gỡ ánh xạ tạm mà ticket đó dựng và test phủ đọc sổ của ticket đó; đã chạy
  `g.py` trên cây hiện tại cộng các thao tác của mục B: không vòng, độ sâu `marketing-pilot/03` giữ 15, chuỗi dài nhất 18. Dòng Xong thêm `make test-integration`, vì bảng và bộ nạp cần PostgreSQL thật.
- 2026-10-27 (agent): áp câu trả lời của Đạt cho lượt `checking-plan-readiness` trên `2c63e01` (câu 3 theo A, câu 4
  theo B) và các sửa có căn cứ: kho `semantic-conventions-genai`, ảnh chụp sinh từ YAML thượng nguồn, một danh sách định
  danh cho phép cho span, log và Langfuse, `dw_node_failure_total` sang workflow-engine/03 (bước 1, 5-8; R1.1, R1.3-R1.5).
- 2026-10-27 (agent): theo lượt kiểm lại trên `e4070f4` và lời đáp của Đạt: ảnh chụp mang tên `dw_*` của `ALL_METRICS`
  và tên span thượng nguồn không có; processor lọc trên mọi exporter và bỏ khóa ngoại lệ; bucket ghi ở spec (bước 1, 4,
  7; R1.1, R1.4).
- 2026-10-27 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-10-27 (agent): phát hiện lúc build. (1) Thượng nguồn không có tag: `GENAI_SEMCONV_COMMIT` ghim `e19717d` (main
  27/10/2026); YAML ở commit đó đã bỏ `gen_ai.system` và có cả `invoke_workflow` lẫn `retrieval` là operation, nên ảnh
  chụp lấy operation từ enum `gen_ai.operation.name`, khóa từ `key:` và `ref:` của `model/**/*.yaml`, metric từ
  `metrics:`; tên ta khai là của thượng nguồn (`GENAI_OPERATIONS`, `GENAI_ATTRIBUTES`) không bao giờ được thêm vào ảnh chụp
  từ `semconv.py`. (2) Bước 1 khai builder `chat`, `execute_tool`, `invoke_workflow` cùng nơi phát (span lời gọi model,
  span công cụ, và `dw.run.start`/`dw.run.resume` đổi thành `invoke_workflow <worker>`); `dw.node`, `invoke_agent`,
  `retrieval` chưa khai vì ticket này không có nơi phát chúng: ticket 02 (R2.1) khai cùng nơi phát, như
  `dw_node_failure_total` (`failure-modes.md` #1). Span rerank giữ `dw.knowledge.rerank`, khóa đổi thành
  `dw.rerank.candidates`, `dw.rerank.top_k`. (3) `gen_ai.response.model` lấy từ `model` của thân phản hồi
  (`ModelUsage.response_model`), vắng khi phản hồi không nói. (4) Ba metric có nơi phát: `dw_run_duration_seconds` mỗi lượt
  qua đồ thị ở runner (nhãn `worker`, `status` ok/error), `dw_tool_call_total` ở `ToolExecutor` (`status` ok, error,
  approval_required, denied), `dw_approval_wait_seconds` ở `ApproveAndResumeService.decide` sau commit (runner không biết lúc
  mở phê duyệt). Test hợp đồng chạy gateway, executor, rerank và runner cùng luồng phê duyệt (tích hợp) qua
  `RecordingTelemetry`; không middleware nào phát telemetry. (5) Log: formatter giữ mẫu của lời gọi, không giữ đối số, nên
  dòng access của uvicorn chỉ còn mẫu (mất method, path, status); đó là hệ quả của R1.5 đã đo
  (`configs/logging/uvicorn.json`, `--log-config` ở `api.Dockerfile`). Ngoại lệ ghi `exception.type` và
  `exception.frames` (file:dòng:hàm), không ghi thông điệp. (6) Ánh xạ tạm nằm ở
  `partition_maintenance.retention_term`, không ở `retention_policy.py`; đã gỡ, `RetentionTerm` sang
  `dw_platform.retention_policy`, `policy.term()` và `policy.store_cutoff()` đọc mảnh. (7) `RetentionPurgerRegistry` dựng và
  đóng băng ở `build_retention_purgers()` của worker, rỗng hôm nay; `test_every_purged_fragment_has_its_purger` đọc nó tới
  khi lane của ticket 03 chạy nó. (8) Bộ nạp: `python -m dw_platform.adapters.persistence.retention_terms`. Test bắt được
  một lỗi thật: biến PL/pgSQL tên `found` che `FOUND`, `IF NOT FOUND` so số nguyên. (9) Fixture tích hợp
  (`tests/support/pg_test_db.run_migrations`) đặt mật khẩu `dw_provisioner` của cụm test bằng hằng
  `PROVISIONER_TEST_PASSWORD`, như `test_provisioning.py` đã làm, rồi migration rồi bộ nạp.
- 2026-10-27 (agent): mutation check: 31 kiểm soát, mỗi cái gỡ đi làm đúng test của nó đỏ (lọc span theo danh sách cho
  phép, danh sách cấm, exporter không qua bộ lọc, mô tả status, giá trị log dưới khóa được phép, mẫu log nội suy, khóa log
  lạ, thông điệp ngoại lệ, đổi `chat` trong semconv, bộ sinh đọc semconv, khóa nội dung trong danh sách cho phép, metric
  khai không phát, `gen_ai.system`, response model chép từ request, ba metric không phát, giá trị input vào audit, thời
  hạn khi mất mảnh, `indefinite` với bộ xóa, khóa mảnh lạ, tên mảnh thiếu schema, mã băm bỏ tên tệp, bộ nạp không xóa dòng,
  nạp hạn chưa `enforced`, bộ nạp nuốt lỗi, hàm đọc hạn trả mặc định, REVOKE của `dw_app`, EXECUTE cho `dw_app`, job
  `migrate` không chạy bộ nạp, lane `partitions` xóa không theo mảnh).
- 2026-10-27 (agent): đóng. CI trên `63755ce` (cùng mã với `ee3420c`): unit, kiến trúc, contract cùng bước
  `genai_semconv_snapshot.py --check`, frontend, bộ tích hợp đầy đủ và compose smoke (job `migrate` chạy bộ nạp) xanh; hai
  bước đỏ (gitleaks, trivy) đỏ từ trước ticket này, từ `85aee2a`. Unit đỏ một lần trên `fc3fbda` rồi xanh lại trên
  `63755ce` mà không đổi mã: một test chập chờn, chưa biết tên vì log của CI cần đăng nhập.
