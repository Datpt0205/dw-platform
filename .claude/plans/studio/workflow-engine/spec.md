# Bộ máy quy trình: tài liệu, kiểm khi xuất bản, biên dịch, hàng đợi run, điểm chờ

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Người dựng cần một quy trình do công ty dựng chạy được như một tài liệu có phiên bản, chứ không phải một đồ thị viết bằng mã của nền tảng. Quy trình là tài liệu `dw.workflow/v1` niêm phong qua vỏ phiên bản chung, kiểm bằng một bộ kiểm trả mọi lỗi trên cùng một `WorkflowIR` mà trình biên dịch dùng, rồi biên dịch mỗi phiên bản phát hành thành một LangGraph `StateGraph`. Mọi lượt chạy Studio đi qua đúng một cửa `RunRequestService`, xếp vào hàng `platform.worker_runs` và chạy ở worker từ hàng đó, công bằng theo tenant; một wrapper nút của nền tảng làm chủ retry, timeout, `on_error` và đúng một hiệu ứng mỗi node; một lượt chạy chờ người tại chỗ nhiều ngày rồi tiếp tục ở tiến trình khác đúng từ bản kê đã ghim. Ý định: một bộ máy chạy quy trình bền vững, công bằng và ghim phiên bản, đặt trên runtime đang có chứ không thay nó. W1 phục vụ YC39, YC41 và YC81; chế độ chạy, bản kê và điểm gắn là của tenant-config, cổng phát hành, đóng băng và tắt khẩn là của agent-lifecycle (ADR-0112 (Proposed), ADR-0113 (Proposed), ADR-0109 (Proposed), ADR-0111 (Proposed)).

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- Runner chỉ dựng ở composition root của API (`apps/api/src/dw_api/bootstrap/runtime.py:209-226`); worker tự nói "hosts no graph, so it has no runner to resume a decided run on" (`apps/worker/src/dw_worker/main.py:203-205`). Thiếu: không có nơi chạy lượt chạy ở worker.
- `start()` biên dịch, chèn dòng run rồi `await graph.ainvoke(...)` ngay trong người gọi (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:294`); không gì xếp một lượt chạy cho tiến trình khác. Thiếu: hàng đợi run.
- Graph đã biên dịch được cache suốt đời tiến trình không trần (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:127`). Ràng buộc: cache của trình biên dịch Studio phải có trần (failure-modes #6).
- `resume()` từ chối trừ khi run ở `waiting_approval` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:501-509`): phê duyệt là loại chờ duy nhất. Thiếu: chờ nhiều loại và nhiều chờ mở.
- `platform.worker_runs` mở đầu `CREATE TABLE platform.worker_runs (` với `status` không CHECK (`db/migrations/sql/0001_platform_baseline.sql:447`), không có cột cha, trình kích hoạt, hàng đợi, lease hay hạn chót; foundations-hardening/06 thêm CHECK gồm `queued`, `waiting`, `blocked`. Thiếu: cột run Studio.
- `ConsumerRegistry.register(name, consumer, interval_seconds=...)` đăng ký làn chạy theo chu kỳ (`apps/worker/src/dw_worker/consumers/__init__.py:21-44`); tập làn bị ghim bởi `test_only_the_platform_lanes_are_wired` (`apps/worker/tests/unit/test_worker.py:103-104`). Ràng buộc: làn `studio_runs` vào qua seam này và sửa test tập làn.
- Giao hàng kênh lấy việc công bằng theo scope qua hàm SECURITY DEFINER `platform.channel_delivery_scopes_due` trả cặp định danh (`packages/python/dw_platform/src/dw_platform/adapters/persistence/channel_deliveries.py:47`). Ràng buộc: mẫu cho hàm lấy việc công bằng theo tenant.
- `platform.ensure_time_partitions` chỉ lặp một bảng cha `FOREACH parent IN ARRAY ARRAY['audit_events']` (`db/migrations/sql/0013_partition_maintenance.sql:123`); studio-skeleton/01 đổi nó thành đọc sổ. Ràng buộc: bảng append-only của spec này vào sổ đó.
- Executor hôm nay tìm lần thành công rồi mới chạy handler (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:202-214`); foundations-hardening/04 chuyển sang giành lượt trước. Ràng buộc: wrapper nút gọi hiệu ứng qua executor giành-lượt-trước đó.

## Mục tiêu

### R1 — Tài liệu `dw.workflow/v1` và loại `workflow`

Người dựng có một loại thành phần `workflow` với mô hình tài liệu kiểu hóa, và giá trị riêng của công ty chỉ vào qua tên điểm gắn (YC39; ADR-0112 (Proposed) quyết 1).

- R1.1 Tài liệu `dw.workflow/v1` PHẢI mang mỗi node một id duy nhất trong tài liệu, một `type@major` có trong `NodeTypeRegistry`, config kiểm theo schema của loại node đó, và chính sách `retry`, `timeout` cùng `on_error` của riêng node.
- R1.2 Mô hình tài liệu `dw.workflow/v1` PHẢI từ chối số thực và chỉ nhận số nguyên trong biên của dạng chuẩn, vì mã băm định nghĩa băm tài liệu qua `dw_kernel.canonical` (tenant-config:R1.2).
- R1.3 KHI một nháp `workflow` được niêm phong, bộ trích phụ thuộc của loại `workflow` PHẢI ghi vào `studio.dependencies` mỗi loại node (`node_type`), mỗi thành phần được gọi (`artifact`), và mỗi tên điểm gắn (`binding`) tài liệu khai, để Nơi đang dùng của tenant-config là nguồn duy nhất (tenant-config:R3.1).
- R1.4 KHI loại `workflow` được đăng ký, `kind` của `ArtifactKindRegistry` PHẢI gồm `workflow` với bộ kiểm trả mọi lỗi và bộ trích phụ thuộc thuần của nó (tenant-config:R2.6 gọi bộ kiểm này).

### R2 — Bộ kiểm xuất bản trả mọi lỗi trên một `WorkflowIR`

Việc niêm phong một quy trình chạy một bộ kiểm trả mọi lỗi đồ thị, biểu thức và điểm gắn cùng lúc, trên đúng cùng một `WorkflowIR` mà trình biên dịch dùng (YC40; ADR-0112 (Proposed) quyết 3; failure-modes #0).

Bộ kiểm xuất bản từ chối niêm phong và trả mỗi lỗi một con trỏ JSON khi tài liệu `dw.workflow/v1` có:

| Mã    | Điều kiện trong tài liệu                                              | Mã lỗi trả                   |
| ----- | --------------------------------------------------------------------- | ---------------------------- |
| R2.1  | một node không tới được từ node vào                                   | `wf.unreachable`             |
| R2.2  | một router không toàn phần (thiếu nhánh cho một giá trị)              | `wf.router_not_total`        |
| R2.3  | hai cạnh thường vào cùng một node không qua điểm nối                  | `wf.join_required`           |
| R2.4  | một chu trình không nằm trong vòng lặp có trần                        | `wf.unbounded_cycle`         |
| R2.5  | một tham chiếu `{{ }}` tới biến không bị mọi đường tới node thống trị | `wf.reference_not_dominated` |
| R2.6  | một biểu thức CEL sai kiểu                                            | `wf.cel_type_error`          |
| R2.7  | hai node ghi cùng một biến trong một superstep                        | `wf.variable_conflict`       |
| R2.8  | một bước chờ nằm trong thân map                                       | `wf.wait_in_map`             |
| R2.9  | một id kết nối hay id principal ở chỗ phải là tên điểm gắn            | `wf.inline_binding`          |
| R2.10 | vượt trần của gói (số node hay độ sâu lồng)                           | `wf.plan_limit`              |

- R2.11 KHI tài liệu có từ hai lỗi trở lên, bộ kiểm xuất bản PHẢI trả mọi lỗi trong `errors[]` trong một lần, không dừng ở lỗi đầu, và không niêm phong.
- R2.12 Bộ kiểm xuất bản và trình biên dịch PHẢI dựng từ cùng một `WorkflowIR`, để đồ thị bị kiểm là đúng đồ thị bị biên dịch.
- R2.13 KHI người dựng lưu nháp chưa niêm phong, bộ kiểm PHẢI chạy ở chế độ cảnh báo và không chặn việc lưu.

### R3 — Cột run Studio và cửa nhận lượt chạy duy nhất

Mọi lượt chạy Studio được tạo qua đúng một cửa `RunRequestService`, ghim mọi thứ nó dùng, và không bao giờ gọi runner ở tiến trình nhận yêu cầu (YC41; ADR-0113 (Proposed) quyết 1).

- R3.1 `platform.worker_runs` PHẢI mang `root_run_id`, `parent_run_id`, `chain_depth`, tham chiếu artifact (`artifact_kind`, `artifact_id`, `artifact_version_id`, `definition_hash`), `trigger_kind`, `run_as_principal_id`, `request_key`, `priority`, `available_at`, `lease_expires_at`, `attempts` và `dead_at` theo mục Dữ liệu.
- R3.2 NẾU một lệnh ghi đặt `status` của `worker_runs` ngoài tập trạng thái mà CHECK cho phép, THÌ PostgreSQL PHẢI từ chối lệnh đó, kể cả khi `dw_app` ghi thẳng bằng SQL (foundations-hardening:R9.3 là chủ của CHECK gồm `queued`, `waiting`, `blocked`).
- R3.3 KHI `RunRequestService` nhận một yêu cầu chạy, `RunRequestService` PHẢI tạo đúng một dòng `worker_runs` ở `queued` trong một giao dịch, mang `run_mode` do cửa quyết (tenant-config:R4), `run_manifest_hash` đã dựng (tenant-config:R6.1), `run_as_principal_id`, `trigger_kind` và `request_key`.
- R3.4 `RunRequestService` PHẢI không gọi runner hay `graph.ainvoke` ở tiến trình nhận yêu cầu.
- R3.5 NẾU một module ngoài `RunRequestService` chèn một dòng `worker_runs` `status = 'queued'` mang một `artifact_kind` của Studio, THÌ test kiến trúc PHẢI đỏ và nêu module đó.
- R3.6 KHI hai yêu cầu chạy mang cùng `request_key` tới song song, PostgreSQL PHẢI giữ đúng một dòng `worker_runs` cho khóa đó.
- R3.7 NẾU kết nối `dw_app` gắn tenant A đọc dòng `worker_runs` của tenant B, THÌ PostgreSQL PHẢI trả 0 dòng.

### R4 — Biên dịch sang `StateGraph` và wrapper nút

Mỗi phiên bản quy trình phát hành biên dịch thành một `StateGraph`, và một wrapper nút của nền tảng (không phải LangGraph) làm chủ retry, timeout, `on_error` và đúng một hiệu ứng mỗi node (YC41, YC81; ADR-0112 (Proposed) quyết 4-5).

- R4.1 KHI một phiên bản `workflow` được biên dịch, trình biên dịch PHẢI dựng `StateGraph` với một kênh cho mỗi đầu ra node, router bằng cạnh điều kiện, bước chờ là `interrupt()` đứng đầu node, và `recursion_limit` tính từ `max_steps` của tài liệu, không bao giờ để giá trị mặc định của thư viện.
- R4.2 Trình biên dịch PHẢI giữ graph đã biên dịch trong một cache LRU trần 256 theo tiến trình, khóa theo `(tenant_id, artifact_version_id, compiler_version)`.
- R4.3 KHI wrapper nút chạy một node, wrapper nút PHẢI áp `timeout` từng lần, `retry` có backoff và `on_error` (`fail` hoặc `continue`) của node, không để LangGraph định tuyến lỗi.
- R4.4 KHI một node có hiệu ứng ra ngoài, wrapper nút PHẢI cho đúng một hiệu ứng rời node qua đúng cửa của loại hiệu ứng (`ToolExecutor` cho công cụ và tin nhắn, `RecordsPort` cho bản ghi, `ModelResolver` cho model).
- R4.5 KHI wrapper nút gọi một hiệu ứng, wrapper nút PHẢI dẫn khóa chống lặp `wf:{run_id}:{node_id}:{iteration_path}` để hiệu ứng được nhà cung cấp nhận đúng một lần dù hai worker chạy cùng node vì lease giả hết hạn (qua executor giành-lượt-trước, foundations-hardening:R6.1).
- R4.6 NẾU đầu ra của một node vượt 64 KiB (65.536 byte thì nhận, 65.537 thì không), THÌ wrapper nút PHẢI cho node lỗi `output_too_large` và không ghi checkpoint lớn.
- R4.7 TRONG KHI lượt chạy ở chế độ `simulate`, wrapper nút PHẢI cho mọi hiệu ứng đi qua `ToolExecutor` không có đường vòng, để executor giả lập lệnh gọi tại điểm thực thi (tenant-config:R5.1).
- R4.8 KHI wrapper nút bắt đầu một node, wrapper nút PHẢI kiểm `RunControlPort` và dừng ở node kế tiếp trong ≤ 5 giây nếu phạm vi bị đóng băng hay tắt khẩn, không thực hiện hiệu ứng đang chờ nào (agent-lifecycle là chủ `RunControlPort`; YC72).
- R4.9 KHI wrapper nút kết thúc một node, wrapper nút PHẢI ghi một bước qua `StepRecorderPort` với đầu vào và đầu ra đã che theo quyền người xem, span `dw.node`, và gắn `app.actor_kind = 'workflow'` cùng `app.boundary_id` của phiên bản mỗi giao dịch (record-access:R6.4).
- R4.10 Node của quy trình PHẢI không chứa SQL hay SDK nhà cung cấp, nhận cổng nó cần bằng tiêm (studio-skeleton:R5.4).

### R5 — Làn `studio_runs`: lấy việc công bằng, nhận ở dispatch, lease, reaper, thư chết

Lượt chạy Studio chạy ở worker từ hàng đợi Postgres, công bằng theo tenant, với mỗi tác động tiếp tục đúng một lần sau khi một worker chết (YC41; ADR-0113 (Proposed) quyết 1-2).

- R5.1 Lượt chạy Studio PHẢI chỉ chạy trong worker, từ làn `studio_runs` mà `build_studio_lanes` đăng ký ở composition root, nên khi worker tắt dòng run giữ `queued` và tiến trình API không gọi `ainvoke`.
- R5.2 KHI làn `studio_runs` lấy việc, hàm SECURITY DEFINER lấy việc PHẢI trả id lượt chạy công bằng theo tenant, để sau 10.000 lượt đang xếp của một tenant, lượt của tenant khác nằm trong lô lấy đầu.
- R5.3 KHI hàm lấy việc chạy dưới ngữ cảnh tenant A, hàm lấy việc PHẢI chỉ trả id lượt chạy của tenant A và không bao giờ của tenant khác.
- R5.4 TRONG KHI làn `studio_runs` nhận một lượt chạy ở dispatch, NẾU `RunControlPort` báo đóng băng hay tắt khẩn, hoặc `LimitsPort.admit` báo phần còn lại của một hạn mức cứng không đủ, THÌ làn PHẢI giữ lượt chạy ở `queued` với `available_at` sau và không đặt `failed` (usage-and-limits là chủ `LimitsPort`; YC77).
- R5.5 NẾU một worker ghi checkpoint hay trạng thái cho một lượt chạy sau khi mất lease, THÌ lệnh ghi đó PHẢI bị từ chối và worker đó dừng chạy lượt chạy.
- R5.6 KHI một worker chết giữa một lượt chạy, làn reaper PHẢI cho một worker khác nhận lại lượt chạy đó đúng một lần trong ≤ 90 giây.
- R5.7 KHI một lượt chạy sập quá `attempts` cho phép, làn PHẢI đặt `dead_at`, phát outbox `studio.run.dead_lettered` và không nhận lại lượt chạy đó.
- R5.8 Làn `studio_runs` PHẢI cho lượt chạy `eval` ưu tiên thấp hơn lượt chạy tương tác và lượt chạy do trình kích hoạt xin.

### R6 — Chờ người bền vững, ghim phiên bản và kiểm khi tiếp tục

Một lượt chạy chờ người tại chỗ sau 3 ngày chờ duyệt hay lâu hơn, tiếp tục ở tiến trình khác đúng từ bản kê đã ghim, và từ chối tiếp tục khi topology đã đổi (YC32, YC41; ADR-0113 (Proposed) quyết 3; ADR-0109 (Proposed) quyết 8).

- R6.1 KHI một node chờ người chạy, runtime PHẢI ghi một `interrupt` cộng một dòng `platform.run_waits` bền vững, cho phép hơn một dòng chờ mở cùng lúc trên một lượt chạy.
- R6.2 KHI một bước chờ người mở, runtime PHẢI tạo một yêu cầu phê duyệt tiền tố nghiêm `studio.step.` với `required_scope` của node, qua bảng điều phối handler theo tiền tố ở composition root, không bằng một nhánh trong `decide` (ADR-0112 (Proposed) quyết 6: người tạo lượt chạy không duyệt được bước của chính mình).
- R6.3 KHI một yêu cầu phê duyệt `studio.step.` được quyết định, lane PHẢI đặt dòng chờ tương ứng sang `resolved` và lượt chạy sang `queued` trong cùng giao dịch của quyết định.
- R6.4 KHI một lượt chạy tiếp tục, runner PHẢI resume bằng map các dòng chờ đã `resolved` theo interrupt id.
- R6.5 NẾU không dòng chờ nào `resolved` khi một lượt chạy tiếp tục, THÌ runner PHẢI không gọi graph và ném lỗi.
- R6.6 NẾU một quyết định tới cho một interrupt id không còn mở, THÌ lane PHẢI từ chối quyết định đó và không tiếp tục lượt chạy.
- R6.7 KHI một lượt chạy Studio tiếp tục, runtime PHẢI chạy năm kiểm phiên bản — compiler, `type@major` của node, mã băm schema state, định dạng lưu, phiên bản LangGraph — đọc từ mục `engine` của bản kê, trước bước kế tiếp.
- R6.8 NẾU một trong năm kiểm phiên bản trượt khi tiếp tục, THÌ runtime PHẢI đặt lượt chạy `blocked`, ghi audit `run.blocked` và không chạy bước nào.
- R6.9 KHI một lượt chạy tiếp tục sau phê duyệt, runtime PHẢI giữ nguyên `run_mode` đã ghim của lượt chạy (tenant-config:R4.5).
- R6.10 Giá trị bí mật PHẢI không bao giờ xuất hiện trong dòng checkpoint hay `platform.run_waits`.

## Hành vi giữ nguyên

- G1 KHI một lượt chạy agent được duyệt rồi tiến trình khởi động lại, runner PHẢI TIẾP TỤC chạy tiếp lượt chạy đó từ checkpoint (test: `test_pause_restart_resume_approved`).

## Trong phạm vi

- Mã: mô hình tài liệu `dw.workflow/v1`, `WorkflowIR`, module đồ thị (`reachable`, `dominators`, `paths_to`, tập nhánh loại trừ), bộ kiểm xuất bản và bộ trích phụ thuộc của loại `workflow`; đăng ký `workflow` vào `ArtifactKindRegistry`; trình biên dịch phần P1 (tuần tự, router, chờ), cache LRU, wrapper nút; `RunRequestService`; `build_studio_lanes`, làn `studio_runs` và làn reaper; hàm lấy việc công bằng; `platform.run_waits` và resume theo interrupt id; năm kiểm khi tiếp tục.
- Bảng và cột ở mục Dữ liệu; route ở mục API.
- Audit: `run.started`, `run.blocked`, outbox `studio.run.dead_lettered`.

## Ngoài phạm vi

| Việc                                                                                                  | Vì sao                                                                              | Chủ                                   |
| ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------- |
| Loại node và form cấu hình, `NodeTypeRegistry`, thư viện CEL, mock ghim theo node                     | Loại bước có một chủ (ADR-0112 (Proposed) quyết 2)                                  | workflow-nodes                        |
| Canvas vẽ quy trình, vị trí node ngoài tài liệu                                                       | Canvas là ngoại lệ UI được duyệt (ADR-0101 (Proposed))                              | workflow-builder-ui                   |
| Vỏ phiên bản, bộ kiểm dạng chuẩn, bản kê lượt chạy, chế độ chạy, điểm gắn, binding set                | Một vỏ cho mọi loại (ADR-0109 (Proposed), ADR-0110 (Proposed), ADR-0111 (Proposed)) | tenant-config                         |
| Cổng phát hành, kiểm định, kill, freeze, `RunControlPort`, ưu tiên `eval`                             | Vòng đời có một chủ (ADR-0120 (Proposed))                                           | agent-lifecycle                       |
| `platform.run_steps`, API danh sách và lịch sử chạy, lease tiền, bộ đếm sử dụng                       | Sổ bước và sử dụng có chủ (ADR-0121 (Proposed), ADR-0122 (Proposed))                | usage-and-limits, telemetry-and-audit |
| Executor giành-lượt-trước, allowlist giải tuần tự, CHECK `worker_runs.status`                         | Lỗi nền P0 (ADR-0108 (Proposed))                                                    | foundations-hardening                 |
| Kích hoạt, chạy tay, chạy thử, danh tính chạy, Data Hub                                               | Trình kích hoạt chỉ xin run (ADR-0113 (Proposed) quyết 4)                           | workflow-triggers                     |
| W2: hủy xuyên tiến trình và hạn chót (route cancel, `dw_run_state`, `deadline_at`)                    | Hàng run W1 chỉ nhận lại lượt mồ côi; hủy chủ động là lớp sau                       | workflow-engine, đợt sau (W2)         |
| W2: map theo chunk, song song và join, vòng lặp, `on_error: route`, nhiều chờ mở                      | YC45; cần chunk `Send` và `defer=True` đo ở UAT                                     | workflow-engine, đợt sau (W2)         |
| W2: làn hẹn giờ `studio_timers` và timeout của chờ                                                    | Cần `zoneinfo` kiểm ở ảnh worker (FOG F1)                                           | workflow-engine, đợt sau (W2)         |
| W2: run con và `WorkflowStartPort.start_child`                                                        | Cần kind công cụ `workflow` của tools-and-skills                                    | workflow-engine, đợt sau (W2)         |
| W2: bộ lưu checkpoint Studio blob-per-channel; chạy lại và tách nhánh là run mới; cổng nâng LangGraph | Cần số đo UAT và saver mới (ADR-0112 (Proposed) quyết 10)                           | workflow-engine, đợt sau (W2)         |
| W2: đo dung lượng ở UAT và giá trị mặc định của gói (YC100)                                           | Tỷ số bền, trần tuyệt đối thì không; đo trước khi đặt hạn mức                       | workflow-engine, đợt sau (W2)         |
| W3: chuyển run đang chờ sang phiên bản mới                                                            | Cần ánh xạ node chờ và biến đổi state theo CEL                                      | workflow-engine, đợt sau (W3)         |

## Dữ liệu

Mọi bảng mới: `tenant_id`, RLS ENABLE và FORCE chỉ theo tenant, grant cùng migration, tên ràng buộc theo `NAMING_CONVENTION`, revision id hex ngẫu nhiên.

- `platform.worker_runs` (foundations-hardening/06 đặt CHECK `status`): thêm `root_run_id uuid NOT NULL`, `parent_run_id uuid` NULL, `chain_depth smallint NOT NULL DEFAULT 0`, `artifact_kind text` NULL, `artifact_id uuid` NULL, `artifact_version_id uuid` NULL, `definition_hash text` NULL khớp `^sha256:[0-9a-f]{64}$`, `trigger_kind text` NULL, `run_as_principal_id uuid` NULL, `request_key text` NULL, `priority smallint NOT NULL DEFAULT 100`, `available_at timestamptz NOT NULL DEFAULT now()`, `lease_expires_at timestamptz` NULL, `attempts smallint NOT NULL DEFAULT 0`, `dead_at timestamptz` NULL; `uq_worker_runs_tenant_id_id UNIQUE (tenant_id, id)`; partial unique `(tenant_id, request_key) WHERE request_key IS NOT NULL`; index `(tenant_id, priority, available_at) WHERE status = 'queued'`, `(tenant_id, artifact_id, created_at DESC, id DESC)`, `(tenant_id, root_run_id)`; FK `(tenant_id, run_manifest_hash)` là của tenant-config/04.
- `platform.run_waits`: PK `(tenant_id, id)`; `run_id` FK `(tenant_id, run_id)` tới `platform.worker_runs` ON DELETE CASCADE; `interrupt_id text NOT NULL`; `kind text NOT NULL` CHECK (`approval`); `status text NOT NULL` CHECK (`open`, `resolved`), không DEFAULT; `required_scope text` NULL; `approval_id uuid` NULL; `created_at`, `resolved_at timestamptz`; UNIQUE `(tenant_id, run_id, interrupt_id)`; RLS tenant ENABLE, FORCE; `dw_app` SELECT, INSERT, và UPDATE chỉ `status`, `resolved_at`.
- Hàm `platform.studio_run_scopes_due(...)` SECURITY DEFINER trả id lượt chạy công bằng theo tenant, theo quy tắc hàm definer (search_path cố định, thu EXECUTE khỏi PUBLIC), mẫu `platform.channel_delivery_scopes_due`.
- Cache LRU graph đã biên dịch nằm trong `dw_agent_runtime.adapters`, không phải bảng.

## API

- `POST /api/v1/runs/{run_id}/retry` (quyền `runs.retry`): chạy lại năm kiểm khi tiếp tục sau khi người dựng sửa phiên bản; 200 khi run rời `blocked`, 409 khi run không ở `blocked`.
- Lỗi theo vỏ problem+json của ADR-0108 (Proposed); `details.reason_code`: `output_too_large`, `run_blocked`, `stale_interrupt`, `empty_resume`.

## Kiểm soát

| #    | Kiểm soát                                                | Yêu cầu     | Test âm                                                                                                                                                                  |
| ---- | -------------------------------------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| WE1  | Đúng một cửa tạo lượt chạy Studio                        | R3.5        | Thêm một module ngoài `RunRequestService` chèn `worker_runs` `status='queued'` với `artifact_kind` Studio → test kiến trúc đỏ; gỡ khẳng định của test → ca trồng lỗi qua |
| WE2  | Lượt chạy Studio chỉ chạy trong worker                   | R5.1        | Tạo lượt chạy khi worker tắt → dòng giữ `queued`, tiến trình API không gọi `ainvoke`; dời việc chạy vào API → test đỏ                                                    |
| WE3  | Lấy việc không vượt tenant                               | R5.3        | Hàm definer dưới ngữ cảnh tenant A chỉ trả id của A; bỏ lọc tenant trong hàm → test đỏ                                                                                   |
| WE4  | Công bằng theo tenant                                    | R5.2        | Sau 10.000 lượt chờ của A, lượt của B nằm trong lô lấy đầu; đổi sang FIFO → test đỏ                                                                                      |
| WE5  | Kiểm đóng băng và tắt khẩn ở đầu mỗi node                | R4.8        | Tắt khẩn giữa lượt chạy → node kế tiếp không chạy trong ≤ 5 giây; bỏ kiểm `RunControlPort` ở wrapper → test đỏ                                                           |
| WE6  | Hạn mức ở lúc nhận (dispatch)                            | R5.4        | Vượt đồng thời → lượt chạy giữ `queued` với `available_at` sau, không `failed`; bỏ kiểm `LimitsPort.admit` → test đỏ                                                     |
| WE7  | Đúng một hiệu ứng mỗi node                               | R4.4, R4.5  | Hai worker chạy cùng node do lease giả hết hạn → nhà cung cấp giả nhận đúng một lần; bỏ khóa chống lặp → test đỏ                                                         |
| WE8  | Fencing lease                                            | R5.5        | Worker cũ ghi checkpoint hay trạng thái sau khi mất lease → bị từ chối, worker dừng; bỏ token rào → test đỏ                                                              |
| WE9  | Không resume với map rỗng                                | R6.5        | Gọi resume khi không dòng chờ nào `resolved` → runner không gọi graph, ném lỗi; cho qua map rỗng → test đỏ                                                               |
| WE10 | Năm kiểm khi tiếp tục                                    | R6.7, R6.8  | Bỏ từng kiểm (a) đến (e) → năm test đột biến tương ứng đỏ; xóa node đang chờ ở build mới → run `blocked`, không bước nào chạy                                            |
| WE11 | Interrupt cũ bị từ chối, bản ghim không lùi về hiện hành | R6.6, R6.9  | Quyết định cho interrupt id không còn mở → bị từ chối, lượt chạy không tiếp tục; niêm phong phiên bản mới khi lượt chờ → lượt tiếp tục với bản ghim                      |
| WE12 | Không bí mật trong state hay điểm chờ                    | R6.10       | Byte credential giả không xuất hiện trong dòng checkpoint hay `run_waits`; thêm nhánh ghi giá trị điểm gắn vào state → test đỏ                                           |
| WE13 | Trần đầu ra node                                         | R4.6        | Đầu ra 65.537 byte → node lỗi `output_too_large`, không ghi checkpoint lớn; bỏ trần → test đỏ                                                                            |
| WE14 | Một `WorkflowIR` cho kiểm và biên dịch                   | R2.3, R2.12 | Bỏ kiểm `wf.join_required` → test "hai cạnh vào một node chạy hai lần" đỏ; kiểm và biên dịch dùng hai mô hình đồ thị khác → fixture compile mọi ca kiểm đỏ               |

## Tiêu chí thành công

- YC94 (W1): một lead từ form chạy hết 15 bước của quy trình Tiếp nhận lead trong worker, qua một bước chờ duyệt, rồi gửi đúng một email.
- YC100 (W2): số đo ở UAT đặt giá trị mặc định của gói; không chốt hạn mức trước khi có số (ticket đợt sau).

## Tiêu chí xong

- Mọi tiêu chí R và G có test; mọi kiểm soát WE1-WE14 có test âm đã thấy đỏ khi gỡ kiểm soát, ghi ở Comments của ticket cài nó.
- `make ci && make test-integration` xanh; tắt API, giết worker giữa lượt chạy, deploy bản thiếu một node major đều có test.
- `reviewing-feature-security` đã chạy trên từng ticket; `.claude/plans/studio.md` ghi lát W1 đã xong.

## Phụ thuộc

- tenant-config: vỏ phiên bản và `ArtifactKindRegistry` (`.claude/plans/studio/tenant-config/issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md`), `RunMode` và `RunManifestPort` cùng `PinnedResolver` (tenant-config/03 và 04), binding set và `RunBindingsPort` (tenant-config/05); các mã tenant-config:R1.2, R2.6, R3.1, R4, R5.1, R6.1, R7.2.
- foundations-hardening: CHECK `worker_runs.status` gồm `queued`, `waiting`, `blocked` và outbox lùi thời gian (`.claude/plans/studio/foundations-hardening/issues/06-run-va-outbox-khong-ket.md`, foundations-hardening:R9.3, R10), executor giành-lượt-trước (`.claude/plans/studio/foundations-hardening/issues/04-toolexecutor-gianh-luot-khong-cua-sau.md`, foundations-hardening:R6.1).
- studio-skeleton: gói `dw_studio`, schema `studio`, seam worker `build_studio_lanes`, sổ `platform.time_partitioned_tables` và `ensure_time_partitions` (studio-skeleton/01, R3; studio-skeleton/04 giao seam worker ở Ngoài phạm vi của nó cho spec này).
- workflow-nodes: `NodeTypeRegistry`, loại node task, router, `human.approval@1`, thư viện CEL (`.claude/plans/studio/workflow-nodes/issues/02-so-dang-ky-buoc-va-mau-chuoi.md`).
- agent-lifecycle: `RunControlPort` ở nhận lượt chạy và đầu node, ưu tiên `eval` (`.claude/plans/studio/agent-lifecycle/issues/01-dong-bang-va-kiem-o-moi-cua.md`).
- record-access: actor kind `workflow` và `app.boundary_id` qua cùng helper mỗi bước (record-access:R6.4); usage-and-limits `LimitsPort.admit` và `StepRecorderPort`.
- Protocol do bên dùng khai: `RunManifestPort`, `RunBindingsPort`, `WorkflowRunnerPort`; `StepRecorderPort`, `LimitsPort`, `RunControlPort` do spec này gọi và bên kia đáp ứng.
- Kiểm lại khi: DO-05 chọn bảng phiên bản theo loại → R1, R2, ticket 01; DO-06 chọn id kết nối trong phiên bản → R1.3, R2.9; DO-41 chọn mô hình phân đoạn thay vì chờ tại chỗ → R6, ticket 05; CHECK `worker_runs.status` của foundations-hardening/06 đổi tập → R3.2.

## Câu hỏi còn mở

- Q1. Phiên bản của mọi loại nằm trong một vỏ `studio.artifact_versions`, không có `active_version_id` (DO-05, khuyến nghị a), hay trong bảng phiên bản riêng theo loại? Chủ: Đạt. Chặn: R1, R2, ticket 01.
- Q2. Tài liệu chỉ giữ tên điểm gắn còn giá trị nằm trong Bộ giá trị gắn được duyệt và ghim theo lượt chạy (DO-06, khuyến nghị a), hay id kết nối nằm thẳng trong phiên bản? Chủ: Đạt. Chặn: R1.3, R2.9, ticket 01.
- Q3. Một lượt chạy chờ nhiều ngày bằng chờ tại chỗ có nén checkpoint (DO-41, khuyến nghị a), hay bằng mô hình phân đoạn ngay bây giờ? Chủ: Đạt. Chặn: R6, ticket 05.

## Quyết định

- 22/10/2026 (người yêu cầu): D1: workspace là đơn vị sở hữu dữ liệu nên không bao giờ là môi trường; môi trường của v1 là phiên bản cộng chế độ chạy (ADR-0111 (Proposed)). Không đổi: spec này tiêu thụ `RunMode`, không định nghĩa.
- 23/10/2026 (người yêu cầu): D12: 10.000 lượt đang xếp của một tenant là ngưỡng công bằng đo (R5.2); số đo dung lượng ở UAT đặt hạn mức gói (YC100, W2).
- 23/10/2026 (agent, tạm): DO-05 theo khuyến nghị (a): phiên bản `workflow` sống trong vỏ `studio.artifact_versions` của tenant-config, không có `active_version_id`. Sửa: R1, R2. Nếu sai thì: R1, R2 trỏ sang bảng `studio.workflow_versions` riêng và ticket 01 chờ bảng đó.
- 23/10/2026 (agent, tạm): DO-06 theo khuyến nghị (a): tài liệu giữ tên điểm gắn, giá trị ghim theo lượt chạy; `wf.inline_binding` chặn id kết nối trong tài liệu. Sửa: R1.3, R2.9. Nếu sai thì: id kết nối nằm trong phiên bản và R2.9 rút.
- 23/10/2026 (agent, tạm): DO-41 theo khuyến nghị (a): chờ tại chỗ có nén checkpoint ở v1; mô hình phân đoạn là đường leo thang khi số đo UAT cho thấy chuỗi chờ vượt nén. Sửa: R6. Nếu sai thì: ticket 05 dựng mô hình phân đoạn và `run_waits` đổi hình.
- 23/10/2026 (agent, tạm): DO-28 theo khuyến nghị (a): đóng băng hủy lượt chạy đang chạy ở cửa kế tiếp, giữ lượt đang chờ, từ chối quyết định (ADR-0111 (Proposed)); wrapper nút kiểm ở đầu node (R4.8). Nếu sai thì: đóng băng park được lại thì R4.8 thêm nhánh park thay vì hủy.
- 23/10/2026 (agent, tạm): bước niêm phong của tenant-config/02 gọi bộ kiểm trả mọi lỗi của loại `workflow`, vì tenant-config:R2.6 là chủ bước niêm phong; spec này chỉ đăng ký bộ kiểm và bộ trích phụ thuộc. Sửa: R1.4, R2. Nếu sai thì: spec này mở route niêm phong riêng cho `workflow`.
- 23/10/2026 (agent, tạm): Mâu thuẫn nguồn: ADR-0112 (Proposed) nói wrapper nút của nền tảng làm chủ `on_error`, LangGraph có `error_handler`; theo wrapper nền tảng, vì đo cho thấy `error_handler` bị bỏ qua khi hai task cùng superstep (brief 1.10). Sửa: R4.3.

## Danh sách ticket

| #   | Ticket                                                                                                                                      |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| 01  | [Tài liệu dw.workflow/v1, loại workflow, bộ kiểm khi phát hành và WorkflowIR](issues/01-tai-lieu-workflow-va-kiem-xuat-ban.md)              |
| 02  | [Cột run Studio, CHECK trạng thái và cửa RunRequestService](issues/02-cot-run-va-cua-nhan-run.md)                                           |
| 03  | [Biên dịch sang StateGraph, cache LRU và wrapper nút](issues/03-bien-dich-va-wrapper-nut.md)                                                |
| 04  | [Làn studio_runs: lấy việc công bằng, lease, reaper, thư chết](issues/04-lan-studio-runs.md)                                                |
| 05  | [Bước chờ người: run_waits, quyết định trong giao dịch, resume theo interrupt id, ghim phiên bản](issues/05-cho-nguoi-va-ghim-phien-ban.md) |
