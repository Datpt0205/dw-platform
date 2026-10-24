# Vòng đời agent và quy trình: giai đoạn, cổng chất lượng, tắt khẩn cấp và đóng băng

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Người dựng cần một lớp điều khiển vòng đời cho agent và quy trình: mỗi phiên bản đi qua Nháp, Đang
kiểm định, Chờ duyệt, Đang dùng, Đã gỡ trong một máy trạng thái do PostgreSQL canh; chỉ sang Đang dùng
khi Cổng chất lượng đạt trên đúng Mã băm định nghĩa của phiên bản (Bộ kiểm định an ninh nền tảng 100%)
và một người không phải Tác giả duyệt, trừ nhánh chỉ siết một người của định nghĩa đối tượng (R1.7);
Đóng băng và Tắt khẩn cấp được kiểm ở mọi cửa của runtime và đóng khi lỗi. Lát này đứng trên vỏ phiên bản dùng chung của tenant-config (ADR-0109 (Accepted)) và cài
hợp đồng Giai đoạn, cổng và công tắc mà các spec dựng thành phần dùng (ADR-0120 (Accepted),
ADR-0125 (Accepted)). W1 phục vụ YC30, YC60, YC70, YC71, YC72, YC73, YC82; YC10, YC74, YC75 và YC93
thuộc W2.

## Hiện trạng (đã kiểm ở `ab33703` ngày 23/10/2026)

- `platform.worker_runs.status` là text không CHECK (`db/migrations/sql/0001_platform_baseline.sql:453`)
  và `RunStatus` có 6 giá trị, 3 terminal (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_store.py:34-43`).
  Thiếu: không có bảng phiên bản, giai đoạn, bộ đề, kết quả kiểm định, kill hay đóng băng; không có
  trạng thái `frozen`.
- Yêu cầu phê duyệt không lượt chạy phát `<type>.decided` qua outbox trong giao dịch quyết định
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:244-245`); prefix nghiêm hiện
  là `{"memory."}` (`apps/api/src/dw_api/bootstrap/runtime.py:237`). Ràng buộc: phát hành dùng lại cơ
  chế này và thêm prefix bằng `|=`.
- `DecisionGuard` đồng bộ chỉ thấy `(request, context)`
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:47`); loại nghiêm từ chối cả
  việc người gửi tự rút (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:115`).
  Ràng buộc: guard `require_not_author` đọc payload; phát hành cần route rút riêng.
- Các cửa model hôm nay: vòng agent (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_budget.py:53`),
  có cấu trúc (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/gateway.py:164`), tóm tắt
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/context_compaction.py:227`); cửa công
  cụ `ToolExecutor._execute` (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:160`).
  Ràng buộc: Đóng băng và Tắt khẩn cấp kiểm ở chính các cửa này.
- Dừng việc hôm nay chỉ có khóa tenant, cache 30 giây, không dừng lượt chạy đang chạy
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/caching_lookup.py:27`). Thiếu:
  không có đóng băng, kill, hay hủy liên tiến trình.
- `dw_evals`: `CaseCategory` 8 giá trị, `SECURITY_CATEGORIES` 3
  (`packages/python/dw_evals/src/dw_evals/dataset.py:14-31`); `Grader` đồng bộ, báo đạt hay trượt toàn
  bộ (`packages/python/dw_evals/src/dw_evals/graders.py:56`); docstring nói judge sau một port mà port
  không tồn tại (`packages/python/dw_evals/src/dw_evals/__init__.py:1-2`). Thiếu: quan sát có cấu trúc,
  `JudgePort`, pass^k, chính sách cổng thuần.
- `ToolDefinition.data_classification` không có bên đọc
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:167`). Thiếu: Phân tích năng lực
  là bên đọc đầu tiên (do compliance-pdpl giữ).
- Thang tự chủ: ở A2 công cụ `external` và `critical` luôn hỏi
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/autonomy.py:14-18`). Ràng buộc: Bộ ba nguy
  hiểm ép Mức tự chủ tối đa A2, thang vẫn là bên đọc runtime duy nhất.
- LISTEN/NOTIFY tái dùng được: kênh `dw_run_state` payload chỉ id
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_events.py:97-147`). Ràng buộc:
  Công tắc điều khiển dùng NOTIFY cùng kiểu, cache đóng khi lỗi.
- `platform.ensure_time_partitions` chỉ biết một parent `ARRAY['audit_events']`
  (`db/migrations/sql/0013_partition_maintenance.sql:123`). Ràng buộc: studio-skeleton viết lại hàm để đọc
  sổ `platform.time_partitioned_tables` (studio-skeleton:R3.1), nên bảng phân vùng mới của cổng đăng ký bằng
  một dòng sổ, không sửa mảng của hàm.
- `SqlScopeHolders.holding` liệt kê người giữ một quyền trong workspace
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/scope_holders.py:74-90`). Ràng
  buộc: thông báo người duyệt phát hành dùng nó.
- Vỏ phiên bản `studio.artifact_versions`, băm chuẩn hóa RFC 8785 (`dw_kernel.canonical`), bản kê định
  nghĩa và Nơi đang dùng đã thuộc tenant-config (`.claude/plans/studio/tenant-config/spec.md:74`). Ràng
  buộc: spec này thêm cột vòng đời, trigger và route trên vỏ đó, không tạo lại nó.

## Mục tiêu

### R1 — Máy trạng thái phiên bản do database canh

Người dựng đưa một phiên bản agent hay quy trình qua Giai đoạn Nháp, Đang kiểm định, Chờ duyệt, Đang
dùng, Đã gỡ, với PostgreSQL canh mọi chuyển tiếp (YC30, YC70; ADR-0120 (Accepted) quyết 1).

- R1.1 NẾU một lệnh ghi chuyển Giai đoạn của một phiên bản ra ngoài tập chuyển tiếp hợp lệ của
  `studio.guard_version_stage()`, THÌ PostgreSQL PHẢI từ chối với SQLSTATE 23514
  `ck_artifact_versions_stage_transition` và không đổi gì, kể cả khi `dw_app` ghi thẳng bằng SQL.
- R1.2 `studio.artifact_versions` PHẢI giữ tối đa một phiên bản Đang dùng và tối đa một Bản ứng viên
  cho mỗi thành phần, bằng chỉ mục duy nhất từng phần.
- R1.3 NẾU hai lệnh Gửi kiểm định song song tạo Bản ứng viên thứ hai cho cùng thành phần, THÌ dịch vụ
  vòng đời PHẢI để một lệnh thành công và trả lệnh kia 409 `candidate_exists`, không tạo Bản ứng viên
  thứ hai.
- R1.4 KHI một phiên bản sang Đang dùng, dịch vụ phát hành PHẢI đưa phiên bản Đang dùng trước đó sang
  Đã gỡ với lý do `superseded` trong cùng giao dịch.
- R1.5 Giai đoạn hiển thị của một thành phần PHẢI do một view SQL tính theo thứ tự Bị kill, Đang dùng,
  Chờ duyệt, Đang kiểm định, Nháp, Đã gỡ, và không bao giờ được lưu thành cột.
- R1.6 ĐỐI VỚI một loại thành phần mà `studio.artifact_kinds` ghi `has_quality_gate = false` (đối tượng
  `dw.object/v1`, công cụ), `studio.guard_version_stage()` PHẢI cho `draft → awaiting_approval` không qua Đang
  kiểm định và không đòi `gate_run_id`, và vẫn đòi `publish_approval_id` đã `approved` cho
  `awaiting_approval → live`.
- R1.7 ĐỐI VỚI một phiên bản `dw.object/v1` mà `LifecycleService` ghi lúc gửi `tighten_only = true` (bộ so
  sánh của loại báo mọi thay đổi chỉ siết, custom-objects:R1.8) cùng `compared_live_hash`,
  `studio.guard_version_stage()` PHẢI cho `draft → live` không cần phê duyệt khi `compared_live_hash` vẫn bằng
  `definition_hash` của phiên bản Đang dùng hiện tại (ADR-0120 (Accepted) quyết 1).
- R1.8 NẾU một lệnh ghi chuyển một phiên bản `awaiting_approval → live` khi `compared_live_hash` ghi lúc gửi (R2.10)
  không còn bằng `definition_hash` của phiên bản Đang dùng hiện tại của thành phần (so bằng `IS NOT DISTINCT FROM`,
  nên hai bên cùng NULL khi chưa có phiên bản Đang dùng là bằng), THÌ PostgreSQL PHẢI từ chối với SQLSTATE 23514
  `ck_artifact_versions_stage_transition` và không đổi gì (ADR-0120 (Accepted) quyết 1).

### R2 — Gửi kiểm định niêm phong nội dung và ghi chỉ mục phụ thuộc

KHI gửi kiểm định, nội dung phiên bản bị niêm phong và bao đóng của nó băm thành Mã băm định nghĩa, để
"đã kiểm định" và Lệch cấu hình tính được (YC30; ADR-0109 (Accepted) quyết 4-5).

- R2.1 KHI người giữ khóa gửi mà `ArtifactKindRegistry` khai cho loại (tenant-config:R2.15) gửi một nháp hợp
  lệ qua `POST /api/v1/studio/{agents|workflows|objects}/{artifact_id}/versions/{version_id}/submit`, dịch vụ
  gửi kiểm định PHẢI, trong một giao dịch, tính bao đóng bằng `ClosureExtractor` của loại, niêm phong nội dung
  qua bước niêm phong của tenant-config, ghi Mã băm định nghĩa, Nơi đang dùng và audit
  `studio.version.submitted`, rồi chuyển phiên bản khỏi Nháp theo luật giai đoạn của loại (R1).
- R2.2 Mã băm định nghĩa của một phiên bản PHẢI là hàm của nội dung niêm phong và bao đóng ghim, nên
  hai phiên bản cùng nội dung và bao đóng cho cùng mã băm, còn một phần bao đóng ghim đổi thì cho mã
  băm khác.
- R2.3 NẾU giao dịch gửi kiểm định hỏng giữa chừng, THÌ dịch vụ gửi kiểm định PHẢI không để lại bản kê
  định nghĩa, dòng Nơi đang dùng hay audit nào của phiên bản đó.
- R2.4 KHI người giữ khóa gửi của loại rút một Bản ứng viên chưa có quyết định qua `POST .../withdraw`, dịch vụ
  vòng đời PHẢI đưa phiên bản về Nháp và hủy yêu cầu phê duyệt phát hành đang treo trong một giao dịch, với audit
  `studio.version.returned_to_draft`.
- R2.5 KHI người giữ `studio.versions.retire` gỡ một phiên bản Đang dùng mà không phiên bản Đang dùng
  nào của thành phần khác phụ thuộc, dịch vụ vòng đời PHẢI chuyển phiên bản sang Đã gỡ với lý do
  `explicit` và audit `studio.version.retired`.
- R2.6 NẾU người gọi gỡ một phiên bản mà một phiên bản Đang dùng của thành phần khác đang phụ thuộc,
  THÌ dịch vụ vòng đời PHẢI trả 409 `artifact_in_use` kèm danh sách bên người gọi đọc được và không
  gỡ gì.
- R2.7 NẾU một kiểm mà bảng kiểm theo loại ở composition root đăng ký cho loại của nháp từ chối lúc gửi
  kiểm định (Phân tích năng lực, compliance-pdpl:R4.2; kiểm người duyệt của quy trình, workflow-nodes:R9.5),
  THÌ dịch vụ gửi kiểm định PHẢI trả 422 với `details.reason_code` của kiểm đó và không chuyển phiên bản
  khỏi Nháp.
- R2.8 ĐỐI VỚI một loại có `has_quality_gate = false`, dịch vụ gửi kiểm định PHẢI ghi `tighten_only` theo bộ so
  sánh của loại trong giao dịch gửi, rồi đưa phiên bản sang Đang dùng khi chỉ siết (R1.7) hay sang Chờ duyệt cùng
  yêu cầu phê duyệt của R5.1 khi không chỉ siết hay chưa có phiên bản Đang dùng.
- R2.9 KHI dịch vụ gửi kiểm định đưa một phiên bản lên Đang dùng theo nhánh chỉ siết, dịch vụ gửi kiểm định
  PHẢI, trong giao dịch của người gửi, đưa phiên bản Đang dùng cũ sang Đã gỡ (`superseded`), ghi đúng một audit
  `studio.version.published` với actor là người gửi và `details.path` `tighten_only`, và outbox
  `studio.version.live`.
- R2.10 KHI người giữ khóa gửi của loại gửi một phiên bản của bất kỳ loại nào, dịch vụ gửi kiểm định PHẢI ghi
  trong giao dịch gửi `compared_live_hash` bằng `definition_hash` của phiên bản Đang dùng của thành phần lúc đó,
  NULL khi chưa có phiên bản Đang dùng (ADR-0120 (Accepted) quyết 1).
- R2.11 NẾU phiên bản được gửi khai một Điểm gắn bắt buộc chưa có giá trị trong Bộ giá trị gắn đã duyệt, THÌ
  dịch vụ gửi kiểm định PHẢI trả 409 `binding_unset` kèm tên Điểm gắn mà `PublishBindingsCheck` báo và không
  chuyển phiên bản khỏi Nháp (tenant-config:R7.2; ADR-0120 (Accepted) quyết 2).

### R3 — Mở rộng dw_evals: quan sát, bộ chấm theo quan sát, JudgePort, pass^k, chính sách cổng thuần

Cổng chất lượng cần một bộ chạy kiểm định chấm theo quan sát, lặp k lần và kết luận bằng một hàm thuần
có test (ADR-0120 (Accepted) quyết 4; ADR-0109 (Accepted)).

- R3.1 KHI `run_cases` chạy một Câu kiểm định gắn `consistency` với `pass_k` lần thử, `dw_evals` PHẢI
  đánh câu đó Đạt cả k lần chỉ khi tất cả `pass_k` lần thử đều đạt.
- R3.2 NẾU một bộ chấm theo quan sát trả `unknown`, THÌ `evaluate_gate` PHẢI tính câu đó như trượt.
- R3.3 NẾU một Câu kiểm định khai cả tham chiếu tệp lẫn giá trị nội tuyến cho `input` hay `expected`,
  THÌ `dw_evals` PHẢI từ chối khi validate và không chạy câu đó.
- R3.4 `evaluate_gate` PHẢI quyết định Đạt hay trượt chỉ từ báo cáo kiểm định và Chính sách cổng, không
  đọc trạng thái ngoài hai đầu vào đó.
- R3.5 `dw_evals` PHẢI không import gói Studio nào.

### R4 — Cổng chất lượng: mô phỏng, bộ an ninh nền tảng 100%, trần chi phí

Ở W1 một Bản ứng viên chỉ qua cổng khi Bộ kiểm định an ninh nền tảng đạt 100% ở chế độ Mô phỏng dưới
trần chi phí giữ trước qua `LimitsPort`; bộ đề của tenant vào ở W2 (YC74); bằng chứng chỉ tính cho đúng
khóa của nó (YC70; ADR-0120 (Accepted) quyết 3; ADR-0109 (Accepted) quyết 4).

- R4.1 KHI một Bản ứng viên vào Đang kiểm định, lane `studio_gate` PHẢI chạy Lượt kiểm định trên Bộ kiểm
  định an ninh nền tảng ở chế độ `simulate` (bộ đề của tenant là W2; Bước `human.approval` nhận quyết định
  giả lập theo R4.7), chấm theo Chính sách cổng đã ghim, và chỉ cho qua khi bộ đó đạt 100%.
- R4.2 NẾU một Câu kiểm định của Bộ kiểm định an ninh nền tảng không đạt, hoặc một Câu kiểm định cho
  kết quả `unknown`, THÌ Cổng chất lượng PHẢI kết luận trượt và đưa phiên bản về Nháp.
- R4.3 TRONG KHI một Lượt kiểm định chạy, NẾU một công cụ có tác động được gọi, THÌ ToolExecutor PHẢI xét
  chế độ chạy trước phê duyệt của công cụ, giả lập lời gọi mà không mở yêu cầu phê duyệt nào, và không để tác
  động nào rời nền tảng (tenant-config:R5.1; tools-and-skills:R2.6).
- R4.4 NẾU chi phí xấu nhất của một Lượt kiểm định (số lần thử nhân trần chi phí mỗi lần thử, cộng lời
  gọi giám khảo) vượt trần mỗi lượt của Chính sách cổng, hoặc `LimitsPort` từ chối lease `eval_offline`
  của lượt, THÌ lane `studio_gate` PHẢI kết thúc Lượt kiểm định là `error` với `limit_exceeded` trước lời
  gọi model đầu tiên và không tạo lượt chạy nào.
- R4.5 NẾU một lần thử chạm trần chi phí mỗi lần thử, THÌ lane `studio_gate` PHẢI dừng lần thử đó ở lời
  gọi kế tiếp, đánh Câu kiểm định đó trượt với lý do `cost_bound`, và vẫn chấm các câu còn lại.
- R4.6 KHI hai Lượt kiểm định có cùng khóa bằng chứng (Mã băm hiệu lực, Chính sách cổng, Bộ kiểm định
  an ninh nền tảng, danh sách mã băm bộ đề của tenant, rỗng ở W1), lane `studio_gate` PHẢI dùng lại kết
  quả Đạt và không tạo lượt chạy thứ hai.
- R4.7 TRONG KHI một lần thử của Lượt kiểm định chạy, KHI lần thử tới một Bước `human.approval`, lane
  `studio_gate` PHẢI cấp cho Bước đó quyết định `approved` hay `rejected` (từ vựng của workflow-nodes:R9.9) mà Câu
  kiểm định khai, để Bước không chờ
  người thật, ghi audit `studio.step.approval.simulated` và không mở yêu cầu phê duyệt nào, nên không quyết
  định nào của lần thử thỏa một phê duyệt `live` (ADR-0111 (Accepted) quyết 5).

### R5 — Phát hành cần một người không phải Tác giả duyệt

Một phiên bản sang Đang dùng chỉ qua một yêu cầu phê duyệt không lượt chạy mà người quyết định không
phải Tác giả, và PostgreSQL canh đúng điều kiện đó, trừ nhánh chỉ siết của R1.7 (YC70, YC60; D11;
ADR-0120 (Accepted) quyết 1-2).

- R5.1 KHI một phiên bản chuyển sang Chờ duyệt (lane `studio_gate` khi Cổng chất lượng đạt, hay dịch vụ gửi
  kiểm định với loại không có cổng), `LifecycleService` PHẢI, trong cùng giao dịch, mở một yêu cầu phê duyệt
  `studio.publish.<kind>` (`agent`, `workflow`, `object`) có `requested_by` là `submitted_by` của dòng phiên
  bản, `required_scope` `studio.publish.approve`, và payload chỉ id và mã gồm `author_ids` dựng từ
  `contributor_ids` và `submitted_by` của chính dòng đó.
- R5.2 NẾU người quyết định một yêu cầu phê duyệt phát hành có trong `author_ids` (người gửi hoặc người
  đóng góp), THÌ luồng phê duyệt PHẢI trả 409 `author_cannot_approve` và không đổi gì.
- R5.3 NẾU payload của một yêu cầu phê duyệt phát hành thiếu `author_ids`, THÌ luồng phê duyệt PHẢI từ
  chối quyết định và không đưa phiên bản sang Đang dùng.
- R5.4 NẾU người đọc hay quyết định một yêu cầu phê duyệt phát hành vừa không giữ tem
  `studio.publish.approve` vừa không phải người xin (`requested_by`), THÌ luồng phê duyệt PHẢI trả 404 khi đọc
  và khi quyết định, kể cả với `platform_admin` (ADR-0004 (Accepted), sửa đổi 07/10/2026).
- R5.5 KHI một yêu cầu phê duyệt `studio.publish.<kind>` được duyệt, handler outbox
  `studio.publish.<kind>.decided` PHẢI, trong một giao dịch và đúng một lần dù sự kiện được giao lại, đưa
  phiên bản sang Đang dùng qua dịch vụ phát hành của tenant-config cùng móc phát hành của loại, phiên bản cũ
  sang Đã gỡ (`superseded`), ghi đúng một audit `studio.version.published` với actor là người quyết định,
  `details.lane` là tên lane và `details.path` `approved` (ADR-0011 (Accepted)), và outbox `studio.version.live`.
- R5.6 NẾU `dw_app` đưa một phiên bản sang Đang dùng khi yêu cầu phê duyệt phát hành liên kết chưa ở
  `approved`, khi `gate_run_id` không phải một Lượt kiểm định đạt trên đúng Mã băm định nghĩa của phiên bản
  (loại có Cổng chất lượng), hay khi đi thẳng từ Nháp mà phiên bản không phải `dw.object/v1`, `tighten_only`
  không là true hoặc `compared_live_hash` khác `definition_hash` của phiên bản Đang dùng hiện tại, THÌ
  PostgreSQL PHẢI từ chối với SQLSTATE 23514 và không đổi gì.
- R5.7 KHI một yêu cầu phê duyệt phát hành quá `publish_approval_ttl_days` của Chính sách cổng (14 ngày),
  lane hết hạn phê duyệt phát hành PHẢI hủy yêu cầu, đưa phiên bản về Nháp và ghi audit với actor
  `system:<lane>` trong một giao dịch.
- R5.8 KHI người xin (`requested_by`) mở yêu cầu phê duyệt phát hành của chính mình, luồng phê duyệt PHẢI trả
  yêu cầu đó với `can_decide` là false (ADR-0004 (Accepted), sửa đổi 07/10/2026).
- R5.9 NẾU handler `studio.publish.<kind>.decided` nhận một quyết định duyệt mà `compared_live_hash` của phiên bản
  không còn bằng `definition_hash` của phiên bản Đang dùng hiện tại (R1.8), THÌ handler PHẢI không đưa phiên bản sang
  Đang dùng, đưa nó về Nháp với `details.reason_code` `base_changed` và ghi audit `studio.version.returned_to_draft`
  trong cùng giao dịch, actor là người quyết định và `details.lane` là tên lane (ADR-0120 (Accepted) quyết 2).
- R5.10 NẾU lúc handler `studio.publish.<kind>.decided` nhận một quyết định duyệt, `PublishBindingsCheck` trả
  `binding_unset` cho phiên bản, THÌ handler PHẢI không đưa phiên bản sang Đang dùng và từ chối lần giao đó với
  `binding_unset` (tenant-config:R7.2).

### R6 — Cổng không mở phê duyệt khi Phân tích năng lực thiếu hay chưa đạt

Phân tích năng lực chạy lúc gửi kiểm định và trả 422 ở đó (compliance-pdpl:R4.2, R4.3, R4.4; R2.7);
lane `studio_gate` chỉ đọc kết quả đã ghi, làm chốt chặn cho đường `dw_app` ghi thẳng giai đoạn (YC71,
YC60; ADR-0125 (Accepted)).

- R6.1 NẾU kết quả Phân tích năng lực ghi cho Mã băm định nghĩa của một Bản ứng viên thiếu, hoặc ghi một
  đường từ đầu vào bên ngoài qua dữ liệu riêng tới tác động ra ngoài không có bước phê duyệt đứng trước,
  hay Mức tự chủ khai vượt mức cho phép, THÌ lane `studio_gate` PHẢI kết luận cổng trượt, không mở yêu cầu
  phê duyệt phát hành và đưa phiên bản về Nháp.
- R6.2 NẾU kết quả Phân tích năng lực của một Bản ứng viên ghi một công cụ thiếu phân loại mức tác động
  hay phân loại dữ liệu, THÌ lane `studio_gate` PHẢI kết luận cổng trượt và không mở yêu cầu phê duyệt
  phát hành.
- R6.3 Mức sàn duyệt của công cụ (trọng yếu, luôn duyệt, Bộ ba nguy hiểm) PHẢI không bị hạ bởi cấu hình
  công ty, người dựng hay Mức tự chủ; công ty chỉ siết thêm được.

### R7 — Đóng băng nền tảng và theo tenant, kiểm ở mọi cửa, đóng khi lỗi

KHI nhà vận hành hay quản trị viên công ty đóng băng một phạm vi, mọi lượt chạy của phạm vi đó dừng ở
cửa kế tiếp và không tác động đang chờ nào được thực hiện (YC72; ADR-0120 (Accepted) quyết 5).

- R7.1 TRONG KHI một Đóng băng của phạm vi đang mở, KHI một lượt chạy đang chạy trong phạm vi tới một cửa
  runtime (lời gọi model ở vòng agent, sub-agent, gateway có cấu trúc và tóm tắt, lời gọi công cụ, quyết
  định phê duyệt, đầu node), cửa runtime đó PHẢI từ chối lời gọi và kết thúc lượt chạy là `cancelled` với
  `reason_code` `tenant_frozen` hay `platform_frozen` trong ≤ 5 giây ở mọi tiến trình.
- R7.2 TRONG KHI một Đóng băng đang mở, KHI làn `studio_inbound` của workflow-triggers hỏi
  `RunControlPort.admission_state` cho một sự kiện trình kích hoạt đã lưu, `RunControlPort` PHẢI trả
  `tenant_frozen` hay `platform_frozen`, để làn để nguyên sự kiện tới khi gỡ, không có trần thời gian (lane lưu
  giữ bỏ qua và đếm sự kiện đang bị giữ, telemetry-and-audit:R5.5), rồi xin lượt chạy theo `received_at`
  (workflow-triggers:R1.3).
- R7.3 NẾU `RunControlPort` không làm mới được trạng thái công tắc quá 30 giây, THÌ cửa runtime PHẢI từ
  chối lời gọi công cụ với `control_state_unavailable`.
- R7.4 NẾU quản trị viên công ty gỡ một Đóng băng có `origin` `platform` qua
  `POST /api/v1/admin/unfreeze`, THÌ API quản trị PHẢI trả 403 và không gỡ.
- R7.5 NẾU `dw_app` ghi thẳng để gỡ, đổi hay xóa một công tắc ngoài bước gỡ một lần hợp lệ và ngoài lượt xóa
  của offboarding (R10.1), THÌ PostgreSQL PHẢI từ chối với SQLSTATE 23514 và không đổi gì.
- R7.6 KHI một Đóng băng được đặt hay gỡ, API hay handler tương ứng PHẢI ghi đúng một sự kiện audit trong
  cùng giao dịch, chỉ mang id và mã.
- R7.7 TRONG KHI một Đóng băng của phạm vi đang mở, KHI cửa nhận lượt chạy gặp một lượt chạy tương tác
  (`chat`, `manual`, `test`) hay một lần thử của Lượt kiểm định, cửa nhận PHẢI kết thúc lượt chạy là
  `cancelled` với `tenant_frozen` hay `platform_frozen` mà không gọi model nào.
- R7.8 TRONG KHI một Đóng băng của phạm vi đang mở, KHI cửa nhận lượt chạy gặp một lượt chạy do trình kích
  hoạt đã xếp hàng (`datahub`, `provider_app`, `schedule`, `record_event`), cửa nhận PHẢI giữ lượt chạy ở
  `queued` và cho nó chạy theo thứ tự xếp hàng sau khi gỡ Đóng băng.
- R7.9 NẾU người giữ khóa gửi của loại gửi một phiên bản trong khi Đóng băng của nền tảng đang mở, hay trong khi
  Đóng băng của công ty đang mở mà lần gửi không đi nhánh chỉ siết của R1.7, THÌ dịch vụ gửi kiểm định PHẢI trả
  409 `tenant_frozen` hay `platform_frozen` và không chuyển phiên bản khỏi Nháp.
- R7.10 KHI người giữ `studio.lifecycle.freeze` xin gỡ một Đóng băng có `origin` `tenant` qua
  `POST /api/v1/admin/unfreeze`, API quản trị PHẢI mở một yêu cầu phê duyệt `studio.lifecycle.unfreeze`
  nghiêm có tem `studio.lifecycle.freeze`, và chỉ gỡ Đóng băng khi một người khác người xin duyệt.
- R7.11 NẾU người quyết định gỡ Đóng băng là người xin gỡ, THÌ luồng phê duyệt PHẢI trả 409 và không gỡ
  Đóng băng.
- R7.12 TRONG KHI một Đóng băng của công ty hay nền tảng đang mở, KHI handler `studio.publish.<kind>.decided`
  nhận một quyết định duyệt, handler PHẢI không đưa phiên bản sang Đang dùng và từ chối lần giao đó với
  `tenant_frozen` hay `platform_frozen` (ADR-0120 (Accepted) quyết 7).
- R7.13 TRONG KHI Đóng băng của công ty đang mở và không có Đóng băng của nền tảng, KHI người giữ khóa gửi gửi một
  phiên bản `dw.object/v1` mà bộ so sánh của loại báo chỉ siết, dịch vụ gửi kiểm định PHẢI đưa phiên bản sang Đang
  dùng theo nhánh chỉ siết (R1.7, R2.9), vì nhánh đó chỉ bớt quyền (ADR-0120 (Accepted) quyết 7).

### R8 — Tắt khẩn cấp agent và quy trình, hủy việc đang chờ, bật lại hai người

KHI người có quyền Tắt khẩn cấp một agent hay quy trình, công tắc chặn lượt chạy mới, hủy việc đang
chờ và tắt trình kích hoạt, và bật lại cần một người thứ hai (YC73; D11; ADR-0120 (Accepted) quyết 5).

- R8.1 KHI người giữ `studio.lifecycle.kill` Tắt khẩn cấp một agent hay quy trình qua
  `POST /api/v1/studio/{agents|workflows}/{artifact_id}/kill`, cửa nhận lượt chạy PHẢI kết thúc là
  `cancelled` với `artifact_killed` mọi lượt chạy `live` và `test` của thành phần đó, kể cả lượt do trình
  kích hoạt đã xếp hàng, và vẫn cho lượt `simulate` chạy.
- R8.2 KHI một thành phần bị Tắt khẩn cấp, lane `control_switch` PHẢI hủy mọi lượt chạy `waiting_approval`
  của thành phần đó, hủy các yêu cầu phê duyệt của chúng và tắt trình kích hoạt của thành phần, trong
  một phản ứng.
- R8.3 NẾU một quyết định phê duyệt tới sau khi lượt chạy liên quan đã bị hủy do Tắt khẩn cấp, THÌ luồng
  phê duyệt PHẢI trả 409 và không tiếp tục lượt chạy.
- R8.4 TRONG KHI một thành phần bị Tắt khẩn cấp, KHI một lane gửi đi lấy một tin đã xếp hàng của thành
  phần đó để gửi, lane gửi đi PHẢI không gọi nhà cung cấp (hợp đồng, thử với lane giả ở W1; lane gửi tin đã
  xếp hàng thật là của connections-and-vault ở W2).
- R8.5 KHI một agent bị Tắt khẩn cấp được dùng làm agent liên kết trong một agent khác, stack con PHẢI
  từ chối lời gọi của agent liên kết đó.
- R8.6 KHI người giữ `studio.lifecycle.kill` xin bật lại một thành phần, API PHẢI mở một yêu cầu phê
  duyệt `studio.lifecycle.revive` nghiêm có tem `studio.lifecycle.kill`, và chỉ gỡ công tắc khi một
  người khác người xin duyệt.
- R8.7 NẾU người quyết định bật lại là người xin bật lại, THÌ luồng phê duyệt PHẢI trả 409 và không gỡ
  công tắc.
- R8.8 KHI một thành phần bị Tắt khẩn cấp hay được bật lại, API hay handler tương ứng PHẢI ghi đúng một
  sự kiện audit trong cùng giao dịch, chỉ mang id và mã.

### R9 — Lượt chạy của chủ thể hay công ty không còn active dừng ở cửa

Lượt chạy của một thành viên bị gỡ khỏi công ty hay bị tạm khóa, và lượt chạy của một công ty bị khóa hay
đang offboarding, không được chạy, qua cùng `RunControlPort` mà mọi cửa đã hỏi, không thêm port nào; lượt do
trình kích hoạt của một tài khoản dịch vụ không `active` chờ trong hàng đợi thay vì bị hủy
(org-and-principals:R4.6, org-and-principals:R4.9; ADR-0113 (Accepted) quyết 3; ADR-0120 (Accepted) quyết 6).

- R9.1 NẾU chủ thể chạy của một lượt chạy (người kích hoạt hay tài khoản dịch vụ) không còn `active` trong
  công ty khi lượt chạy tới cửa nhận hay cửa tiếp tục, THÌ `RunControlPort` PHẢI từ chối với
  `principal_inactive` trước mọi lời gọi model hay công cụ, và lượt chạy theo hai hàng `principal_inactive` của
  bảng từ chối ở dispatch (workflow-engine:R5.15, workflow-engine:R5.17): lượt `datahub`, `provider_app`,
  `record_event` đang `queued` ở lại `queued` tới khi tài khoản dịch vụ `active` lại (org-and-principals:R4.9), mọi
  lượt khác kết thúc `cancelled`.
- R9.2 NẾU `platform.tenants.status` của công ty là `locked`, `offboarding` hay `offboarded` khi một lượt chạy
  của công ty đó tới cửa nhận hay cửa tiếp tục, THÌ `RunControlPort` PHẢI từ chối với `tenant_locked` (khi
  `locked`) hay `tenant_offboarding`, và lượt chạy kết thúc là `cancelled` mà không gọi model hay công cụ nào,
  theo hàng `tenant_locked`, `tenant_offboarding` của bảng từ chối ở dispatch (workflow-engine:R5.18;
  foundations-hardening:R3.3).

### R10 — Offboarding xóa công tắc của công ty

Lane offboarding xuất rồi xóa công tắc điều khiển của một công ty rời nền tảng như mọi dữ liệu Studio của nó
(YC6), mà không mở cho `dw_app` một đường xóa để gỡ Tắt khẩn cấp.

- R10.1 KHI lane `offboarding` xóa dữ liệu của một công ty đang `offboarding`, lane `offboarding` PHẢI xuất rồi
  xóa mọi dòng `platform.control_switches` của công ty đó (studio-skeleton:R4.3).

## Hành vi giữ nguyên

- G1 KHI CI chạy `scripts/run_evals.py`, `dw_evals` PHẢI TIẾP TỤC chạy `run_dataset` trên dataset nền
  tảng với `SECURITY_CATEGORIES` không đổi (test: `apps/api/tests/unit/test_eval_datasets.py`).

## Trong phạm vi

- Bảng, cột và trigger ở mục Dữ liệu; route ở mục API.
- Mã: cột vòng đời và `studio.guard_version_stage()` trên `studio.artifact_versions`, với luật theo loại
  cho loại không có Cổng chất lượng và nhánh chỉ siết của `dw.object/v1` (cột `tighten_only`,
  `compared_live_hash`); `VersionStage` StrEnum với bảng chuyển đổi thuần và `LifecycleService`; view Giai
  đoạn hiển thị; dịch vụ gửi kiểm định cho mọi loại đã đăng ký (route `{agents|workflows|objects}`, khóa gửi
  do `ArtifactKindRegistry` khai) với bảng điều phối `ClosureExtractor` và bảng kiểm theo loại lúc gửi kiểm
  định (Protocol của spec này, compliance-pdpl và workflow-nodes đăng ký kiểm của mình); Protocol
  `PublishBindingsCheck` do spec này khai, hỏi ở lệnh gửi và ở handler phát hành (R2.11, R5.10; tenant-config/05
  đáp ứng); mở rộng `dw_evals`
  (Observation, ObservationGrader, `JudgePort`, `EvalTargetPort`, `run_cases`, `gate.py`); lane `studio_gate`;
  `RunControlPort` (gồm lý do `principal_inactive`, `tenant_locked`, `tenant_offboarding`), `RunHaltedError`
  và adapter `SqlRunControl` với cache đóng khi lỗi; các cửa đóng băng và kill; prefix nghiêm
  `studio.publish.`, `studio.lifecycle.` và guard `require_not_author`; handler outbox phát hành
  `studio.publish.<kind>.decided` cho mọi loại, bật lại và gỡ Đóng băng; lane hết hạn phê duyệt phát hành;
  lane `control_switch` nghe outbox `control.switch.changed`.
- Khóa quyền của spec, mỗi khóa đăng ký (nhãn, `scope_kind`, `risk`) trong danh mục quyền một chủ bằng
  migration của ticket dùng nó (quy ước của tenant-rbac/01): `studio.lifecycle.freeze` (ticket 01),
  `studio.versions.submit`, `studio.versions.retire` (ticket 03), `studio.publish.approve`,
  `studio.lifecycle.read`, `studio.evals.run` (ticket 04), `studio.lifecycle.kill`, `studio.lifecycle.revive`
  (ticket 05).
- Audit: `studio.version.submitted`, `.returned_to_draft`, `.retired`, `.published`,
  `control.freeze.set`, `control.freeze.lifted`, `control.kill.set`, `control.kill.lifted`,
  `studio.gate_run.started`, `.completed`, `approval.cancelled` (lane `control_switch`), `tool.denied`
  (`policy_decision` `deny_frozen`); trong `platform.provisioning_audit`: `platform.freeze.set`,
  `platform.freeze.lifted`, `platform.tenant_freeze.set`, `platform.tenant_freeze.lifted`.

## Ngoài phạm vi

| Việc                                                                                                                                                                  | Vì sao                                                                                                                                                             | Chủ                                                                                   |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------- |
| Phân tích năng lực Bộ ba nguy hiểm (tín hiệu A, B, C từ bao đóng, nút phê duyệt áp đảo C) lúc gửi kiểm định, 422 khi chưa đạt, kết quả ở `studio.version_assessments` | ADR-0125 (Accepted); R2.7 gọi nó qua bảng kiểm theo loại, R6 chỉ đọc kết quả đã ghi                                                                                | compliance-pdpl                                                                       |
| W2: bộ đề kiểm định của tenant (bảng, API, màn nhập câu không code, `studio.gate_run_datasets`), cùng `min_cases_total`, `pass_rate_min` của Chính sách cổng          | YC74; cần gói và điều hướng của studio-skeleton; trường chính sách vào cùng bên đọc của nó (DO-29.1)                                                               | agent-lifecycle, đợt sau (W2)                                                         |
| W2: Mức rủi ro AI trên `studio.version_assessments` (công ty tự phân hạng từ mặc định, không khai thấp hơn ở v1), tờ giải thích                                       | YC93; DO-60; bảng có từ W1 cho kết quả Phân tích năng lực (compliance-pdpl:R4.6)                                                                                   | compliance-pdpl; agent-lifecycle đọc (W2)                                             |
| W2: tổng quan đội ngũ, "đã kiểm định thật N/M", chip cảnh báo, cảnh báo nháp để lâu (`stale_draft_days`), trang phiên bản, so sánh từng trường                        | YC75; mẫu học từ phân tích đối thủ (config-chang.md mẫu 3); đọc theo quyền người xem, cổng chặn ở server; `stale_draft_days` vào chính sách cùng bên đọc (DO-29.1) | agent-lifecycle, đợt sau (W2)                                                         |
| W2: Đóng băng có thể tiếp tục cho lượt đang chạy (`RunStatus.FROZEN`, lane tiếp tục sau khi gỡ)                                                                       | W1 hủy lượt đang chạy ở cửa kế tiếp và chỉ giữ lượt do trình kích hoạt đã xếp hàng (DO-28 C); cần nguyên mẫu của ticket 01                                         | agent-lifecycle, đợt sau (W2)                                                         |
| W2: phát hiện Lệch cấu hình, giám khảo LLM hiệu chuẩn, kiểm định retrieval, so với bản đang chạy                                                                      | mẫu cảnh báo lệch học từ phân tích đối thủ (config-chang.md mẫu 3); cần `mcp-client`, `model-connections`                                                          | agent-lifecycle, đợt sau (W2)                                                         |
| W2: kiểm định trực tuyến lấy mẫu (tắt mặc định, model chấm cùng Lộ trình dữ liệu), phân tích năng lực theo đường đi, gói hồ sơ AI theo Luật AI                        | YC93; chờ `usage-and-limits`, `workflow-nodes` và luật sư (DO-60)                                                                                                  | agent-lifecycle; compliance-pdpl, đợt sau (W2)                                        |
| W2: kiểm định lại khi ghi đè của tenant đổi Mã băm hiệu lực, phần nền tảng trả có trần cho lượt do nền tảng kích                                                      | bằng chứng khóa theo Mã băm hiệu lực nên bằng chứng cũ tự hết giá trị (ADR-0109 (Accepted)); DO-29.2                                                               | agent-lifecycle; usage-and-limits, đợt sau (W2)                                       |
| W2: `scope_type` `tool` trên công tắc để ngưng công cụ MCP (`suspended`), gỡ bằng `studio.lifecycle.revive` nối với lần duyệt định nghĩa mới                          | công cụ MCP đi qua máy giai đoạn (D:mcp-client:R3.4, quyết 23/10/2026); mcp-client là W2                                                                           | agent-lifecycle; mcp-client, đợt sau (W2)                                             |
| W2: lý do dừng `workspace_archived` của `RunControlPort` (ADR-0120 (Accepted) quyết 6)                                                                                | lưu trữ workspace đến ở W2 cùng org-and-principals; W1 dừng lượt chạy của công ty bị khóa hay đang offboarding (R9.2)                                              | agent-lifecycle; org-and-principals, đợt sau (W2)                                     |
| W2: phát hành từ chối 409 `owner_missing` khi người chịu trách nhiệm rời công ty (YC10; ADR-0103 (Accepted) quyết 3)                                                  | ADR-0120 (Accepted) quyết 2 đòi người chịu trách nhiệm khi phát hành; người chịu trách nhiệm bắt buộc, guard và lane `principal_ownership` đến ở W2 (DO-39.2)      | agent-lifecycle; org-and-principals (guard, lane `principal_ownership`), đợt sau (W2) |
| W2: lane gửi tin đã xếp hàng thật thi hành hợp đồng R8.4                                                                                                              | tin chỉ được hoãn và xếp hàng từ W2; W1 thử R8.4 với lane giả (ADR-0120 (Accepted) quyết 6)                                                                        | connections-and-vault, đợt sau (W2)                                                   |
| W3: công tắc theo workspace, kết nối, tuyến model; nhà vận hành tắt một agent; mô phỏng nhiều lượt                                                                    | v1.5 trở đi                                                                                                                                                        | agent-lifecycle, đợt sau (W3)                                                         |
| Vỏ phiên bản, băm RFC 8785 (`dw_kernel.canonical`), bản kê định nghĩa và Nơi đang dùng                                                                                | ADR-0109 (Accepted); đã có                                                                                                                                         | tenant-config                                                                         |
| Bảng phiên bản agent và quy trình, trình soạn, canvas; chế độ chạy, hàng đợi, lịch, Data Hub                                                                          | spec này chỉ đặt hợp đồng cột vòng đời và hợp đồng cửa                                                                                                             | agent-builder, workflow-engine, workflow-triggers                                     |
| Sổ sử dụng, lease, hạn mức theo phạm vi                                                                                                                               | spec này xin lease `purpose` `eval_offline` qua `LimitsPort` cho Lượt kiểm định (DO-21.4)                                                                          | usage-and-limits                                                                      |
| Danh mục quyền, vai trò, độ sâu workspace; phân loại công cụ, ghim định nghĩa MCP                                                                                     | spec này chỉ đăng ký khóa của mình vào danh mục (quy ước của tenant-rbac/01) và đọc phân loại, sự kiện                                                             | tenant-rbac; tools-and-skills; mcp-client                                             |

## Dữ liệu

Mọi bảng mới: RLS ENABLE và FORCE theo tenant, grant cùng migration, tên ràng buộc theo
`NAMING_CONVENTION`, revision id hex ngẫu nhiên.

- Cột vòng đời thêm trên `studio.artifact_versions` (vỏ chung của tenant-config, ADR-0109 (Accepted)
  quyết 2; DO-05 chọn vỏ chung): `gate_run_id uuid` NULL, FK `studio.gate_runs` ON DELETE RESTRICT,
  bắt buộc khi `stage IN ('awaiting_approval','live','retired')` với loại có Cổng chất lượng, luôn NULL
  với loại mà `studio.artifact_kinds` ghi `has_quality_gate = false` (R1.6); `publish_approval_id uuid` NULL, FK
  `platform.approval_requests` ON DELETE RESTRICT, bắt buộc khi `stage IN ('awaiting_approval','live','retired')`
  trừ phiên bản lên Đang dùng theo nhánh chỉ siết (R1.7); `tighten_only boolean NOT NULL DEFAULT false`, do
  `LifecycleService` ghi lúc gửi theo bộ so sánh của loại, và `compared_live_hash text` NULL (`definition_hash` của
  phiên bản Đang dùng lúc gửi, NULL khi chưa có), do `LifecycleService` ghi ở mọi lần gửi (R2.10), CHECK
  `NOT tighten_only OR compared_live_hash IS NOT NULL`;
  `contributor_ids uuid[] NOT NULL CHECK (cardinality(contributor_ids) >= 1)`; `submitted_by`,
  `submitted_at`, `published_by`, `published_at`, `retired_by`, `retired_at`; `retire_reason_code`
  CHECK (`superseded`, `explicit`); `stage_changed_at timestamptz NOT NULL`. Trigger
  `studio.guard_version_stage()` (BEFORE INSERT OR UPDATE) cho đúng các chuyển tiếp của R1, cho mọi chuyển sang
  `live` chỉ khi `compared_live_hash` vẫn là mã băm của phiên bản Đang dùng mà lần phát hành thay (R1.7, R1.8), và
  chặn đổi nội dung ngoài `draft`; chỉ mục một Đang dùng (`WHERE stage='live'`), một Bản ứng viên
  (`WHERE stage IN ('evaluating','awaiting_approval')`), và `(tenant_id, stage, stage_changed_at DESC, id DESC)`.
  View `studio.artifact_display_stage` tính Giai đoạn hiển thị, không lưu.
- `platform.control_switches`: `tenant_id`, `id`; `scope_type` CHECK (`tenant`, `agent`, `workflow`);
  `workspace_id`, `target_id` NULL chỉ khi `scope_type='tenant'`; `action` CHECK (`freeze`, `kill`);
  `origin` CHECK (`tenant`, `platform`); `reason_code` CHECK (`incident`, `maintenance`, `abuse`,
  `test`, `other`); `reason` 1..500 ký tự; `set_by`, `set_at`; `lift_approval_id`, `lifted_by`,
  `lifted_at`, `lift_reason`; chỉ mục một công tắc mở
  `(tenant_id, scope_type, coalesce(target_id, '…nil…'::uuid)) WHERE lifted_at IS NULL`; FK
  `tenant_id → platform.tenants ON DELETE CASCADE`; trigger `platform.guard_control_switch()` (chèn chỉ
  mở; gỡ một lần; dòng `origin='platform'` chỉ `dw_provisioner` gỡ) và trigger
  `pg_notify('dw_control_switch', ...)` chỉ id; `dw_app` SELECT, INSERT, UPDATE
  (`lifted_by, lifted_at, lift_reason, lift_approval_id`) và DELETE chỉ cho lượt xóa của offboarding: trigger
  `platform.guard_control_switch()` từ chối mọi DELETE khi `platform.tenants.status` của công ty khác
  `offboarding` (R7.5, R10.1). Mỗi lần đặt hay gỡ một công tắc `kill` ghi outbox `control.switch.changed` v1
  chỉ id trong cùng giao dịch; lane `control_switch` nghe sự kiện đó.
- `platform.platform_freezes` (mặt danh tính, không tenant): tối đa một dòng mở; `dw_app` chỉ SELECT;
  do `dw_provisioner` ghi, audit trong `platform.provisioning_audit`.
- `studio.gate_runs`: `status` CHECK (`queued`, `running`, `passed`, `failed`, `error`, `cancelled`);
  `purpose` CHECK (`gate`, `dry`); khóa bằng chứng (`effective_hash`, `gate_policy_ref`,
  `security_suite_ref`, danh sách mã băm bộ đề của tenant, rỗng ở W1); `definition_hash` cho trigger giai
  đoạn; `spend_cap_usd`, `spent_usd`, `resolved_at_gate` jsonb,
  `verdict` jsonb; `created_at timestamptz NOT NULL`; index `(tenant_id, created_at DESC, id DESC)` mang thứ tự
  keyset của `GET /api/v1/studio/gate-runs` (CLAUDE.md, Data model rules). `studio.gate_run_datasets` là W2 cùng bộ
  đề của tenant. `studio.gate_case_results`: index `(tenant_id, gate_run_id, case_id)` trên bảng cha mang thứ tự
  keyset của `GET /api/v1/studio/gate-runs/{id}/cases`;
  phân vùng theo tháng với DEFAULT, đăng ký bằng một dòng `platform.time_partitioned_tables`
  (`append_only = true`, studio-skeleton:R3.1); ENABLE/FORCE RLS và policy tenant trên cha và DEFAULT cùng
  migration; `dw_app` không giữ quyền nào trên partition nào, kể cả DEFAULT, chỉ SELECT, INSERT trên bảng cha;
  thời hạn 395 ngày (13 tháng, số tạm UNVERIFIED) dưới khóa `studio.gate_case_results` của tệp chính sách
  retention, thêm trong cùng thay đổi đăng ký (telemetry-and-audit:R5.6, studio-skeleton:R3.7), xóa bằng DROP
  PARTITION qua `platform.drop_expired_partitions` của usage-and-limits/02; khi offboarding, dòng của công ty
  xóa qua `platform.purge_tenant_append_only` (usage-and-limits:R3.8), nên bảng có một dòng `STUDIO_EXCLUSIONS`
  nêu cách xóa đó (studio-skeleton:R4.1).

## API

- `POST /api/v1/studio/{agents|workflows|objects}/{artifact_id}/versions/{version_id}/submit` và
  `POST .../withdraw` (khóa gửi mà `ArtifactKindRegistry` khai cho loại, tenant-config:R2.15:
  `studio.versions.submit` cho agent và quy trình, `studio.objects.manage` cho đối tượng; `Idempotency-Key`);
  với đối tượng, lệnh gửi đưa phiên bản sang Chờ duyệt hay, theo nhánh chỉ siết, Đang dùng (R2.8).
  `POST /api/v1/studio/{agents|workflows}/{artifact_id}/versions/{version_id}/retire` (`studio.versions.retire`,
  `Idempotency-Key`).
- `POST /api/v1/studio/{agents|workflows}/{artifact_id}/versions/{version_id}/dry-evaluations` (`studio.evals.run`);
  `GET /api/v1/studio/gate-runs` (keyset theo `(created_at DESC, id DESC)`), `/{id}`, `/{id}/cases` (keyset theo
  `case_id`) (`studio.lifecycle.read`); mỗi thứ tự có index ở mục Dữ liệu.
- `POST /api/v1/admin/freeze` (`studio.lifecycle.freeze`; `Idempotency-Key`; body `reason_code`,
  `reason`; một người cộng audit), `POST /api/v1/admin/unfreeze` (`studio.lifecycle.freeze`; mở yêu cầu
  phê duyệt `studio.lifecycle.unfreeze`, gỡ khi người thứ hai duyệt); `GET /api/v1/control-state` (mọi
  thành viên; chỉ mã, không lý do chữ); nhà vận hành `POST /api/v1/platform/freeze`, `POST /api/v1/platform/unfreeze`,
  `POST /api/v1/platform/tenants/{tenant_id}/freeze`, `POST /api/v1/platform/tenants/{tenant_id}/unfreeze`
  (ngữ cảnh provisioning).
- `POST /api/v1/studio/{agents|workflows}/{artifact_id}/kill` (`studio.lifecycle.kill`, lý do);
  `POST /api/v1/studio/{agents|workflows}/{artifact_id}/revive-requests` (mở `studio.lifecycle.revive`).
- Phát hành đi qua inbox `/approvals` hiện có (nhãn loại và liên kết "Xem diff" ở điểm cắm
  `apps/web/components/tool-approval.tsx`).
- Lỗi theo vỏ problem+json của ADR-0108 (Accepted); `details.reason_code`: `candidate_exists`,
  `author_cannot_approve`, `tenant_frozen`, `platform_frozen`, `artifact_killed`,
  `control_state_unavailable`, `principal_inactive`, `tenant_locked`, `tenant_offboarding`, `cost_bound`,
  `limit_exceeded`, `artifact_in_use`, `binding_unset` (409 ở lệnh gửi, R2.11), `base_changed` (handler phát hành
  đưa phiên bản về Nháp, không mã HTTP, R5.9); route gửi kiểm định trả thêm mã 422 của kiểm theo loại do spec chủ kiểm
  quyết (`capability_trifecta_autonomy`, `tool_unclassified`, `trifecta_path_unapproved`, `residency_refused` của
  compliance-pdpl; mã của kiểm người duyệt của workflow-nodes:R9.5).

## Kiểm soát

| #    | Kiểm soát                                                                    | Yêu cầu                                    | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ---- | ---------------------------------------------------------------------------- | ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AL1  | Máy trạng thái thuộc database                                                | R1.1                                       | `dw_app` UPDATE `draft → live` trực tiếp → 23514 `ck_artifact_versions_stage_transition`; gỡ trigger → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| AL2  | Một Đang dùng, một Bản ứng viên                                              | R1.2, R1.3                                 | Hai lần gửi kiểm định song song → một 202, một 409 `candidate_exists`; INSERT bản `live` thứ hai → lỗi chỉ mục; gỡ chỉ mục từng phần → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| AL3  | Bao đóng và Nơi đang dùng ghi cùng giao dịch, khóa theo Mã băm định nghĩa    | R2.1, R2.2, R2.3                           | Rollback giữa giao dịch gửi kiểm định → không bản kê, phụ thuộc hay audit; đổi phiên bản một công cụ ghim → Mã băm định nghĩa khác; bỏ một loại khỏi bao đóng → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| AL4  | Đang dùng cần cổng đạt và approval đã duyệt; chỉ phiên bản chỉ siết đi thẳng | R1.7, R2.8, R5.6                           | Chuyển `live` với `gate_run_id` của mã băm khác, hoặc approval còn `pending` → 23514; `draft → live` với `tighten_only` false, với `compared_live_hash` cũ sau khi phiên bản Đang dùng đổi, hay với loại `agent` hoặc `tool` → 23514; phiên bản đối tượng vừa đóng một trường vừa thêm một trường → Chờ duyệt kèm phê duyệt; gỡ CHECK hay luật nhánh → test đỏ                                                                                                                                                                                                                                                                                                                                                                                 |
| AL5  | Người duyệt không phải Tác giả, không phải người gửi                         | R5.1, R5.2, R5.3                           | Người trong `contributor_ids` có scope duyệt → 409 `author_cannot_approve`; payload thiếu `author_ids` → từ chối; `author_ids` dựng thiếu một người trong `contributor_ids` hay `submitted_by` → test khớp đỏ; yêu cầu `studio.publish.object` mở lúc gửi cũng mang `author_ids`; gỡ guard → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| AL6  | Không vai nào thay tem `studio.publish.approve`; người xin chỉ đọc           | R5.4, R5.8                                 | `platform_admin` không giữ tem và không phải người xin → 404 khi đọc và khi quyết định; người gửi không giữ tem đọc yêu cầu của mình với `can_decide` false; gỡ luật người xin → người gửi nhận 404, test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| AL7  | Bộ kiểm định an ninh nền tảng 100%, `unknown` chặn như trượt, không sửa được | R4.1, R4.2                                 | Một Câu an ninh trượt hoặc `unknown` → cổng trượt; không route nào ghi Câu an ninh (không phải dữ liệu tenant); gỡ luật trong `evaluate_gate` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| AL8  | Kiểm định không gây tác động thật, không phê duyệt thật                      | R4.3, R4.7                                 | Lượt kiểm định agent có công cụ gửi Zalo → egress giả không nhận lời gọi nào, không yêu cầu phê duyệt nào mở; lần thử của quy trình có Bước `human.approval` mà Câu kiểm định khai `rejected` (từ vựng `approved`, `rejected` của workflow-nodes:R9.9) → nhánh từ chối chạy, 0 dòng `platform.approval_requests`, audit `studio.step.approval.simulated` mang `rejected`; gỡ chặn `simulate` ở executor hay đặt phê duyệt trước chế độ chạy → test đỏ                                                                                                                                                                                                                                                                                          |
| AL9  | Trần chi phí trước lời gọi đầu, trần riêng mỗi lần thử                       | R4.4, R4.5                                 | Chi phí xấu nhất vượt trần lượt, hoặc `LimitsPort` từ chối lease `eval_offline` → Lượt kiểm định `error` `limit_exceeded`, không `worker_runs` nào; một lần thử chạm trần → Câu trượt `cost_bound`, các câu khác vẫn chấm; gỡ trần lần thử → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| AL10 | Phiên bản chưa qua kiểm theo loại hay Phân tích năng lực không lên Chờ duyệt | R2.7, R6.1, R6.2, R6.3                     | Đăng ký một kiểm từ chối cho loại `workflow` → gửi kiểm định 422, phiên bản vẫn Nháp; `dw_app` ghi thẳng một Bản ứng viên không có kết quả Phân tích năng lực sang Đang kiểm định → cổng trượt, không yêu cầu phê duyệt nào; gỡ đọc kết quả ở lane → yêu cầu phê duyệt mở (đỏ)                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| AL11 | Đóng băng chặn ở mọi cửa, đóng khi lỗi                                       | R7.1, R7.3, R7.7, R7.8, R7.9, R7.12, R7.13 | Đặt đóng băng giữa run: mỗi cửa trong 6 cửa của R7.1 từ chối lời gọi kế tiếp, run `cancelled`; lượt `chat` tới cửa nhận → `cancelled` `tenant_frozen`, 0 lời gọi model; lượt `datahub` đã xếp hàng vẫn `queued` và chạy sau khi gỡ; gửi kiểm định → 409; phiên bản đối tượng chỉ siết gửi khi Đóng băng của công ty → Đang dùng, cùng phiên bản khi Đóng băng của nền tảng → 409 `platform_frozen`, phiên bản đối tượng không chỉ siết khi Đóng băng của công ty → 409 `tenant_frozen`; handler phát hành nhận quyết định duyệt khi đóng băng → phiên bản không lên Đang dùng, `tenant_frozen`; cache quá 30 giây không làm mới → lời gọi công cụ `control_state_unavailable`; gỡ kiểm ở một cửa hay gỡ ngoại lệ chỉ siết → test của chỗ đó đỏ |
| AL12 | Tenant không gỡ Đóng băng của nhà vận hành; không xóa công tắc để gỡ         | R7.4, R7.5                                 | `POST /api/v1/admin/unfreeze` khi `origin='platform'` → 403; `dw_app` UPDATE gỡ trực tiếp → 23514; `dw_app` DELETE một công tắc `kill` của công ty `active` → 23514, công tắc còn; gỡ phép kiểm DELETE khỏi trigger → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| AL13 | Tắt khẩn cấp hủy việc đang chờ                                               | R8.2, R8.3                                 | Run `waiting_approval` của thành phần → `cancelled`, approval `cancelled`; quyết định đến sau → 409, không resume; gỡ lane → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| AL14 | Bật lại cần người thứ hai                                                    | R8.6, R8.7                                 | Người xin bật lại tự duyệt `studio.lifecycle.revive` → 409, công tắc không gỡ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| AL15 | Tắt khẩn cấp chặn gửi đã xếp hàng và agent liên kết                          | R8.4, R8.5                                 | Tắt sau khi tin Zalo xếp hàng → lane gửi giả không gọi nhà cung cấp (lane thật là W2 của connections-and-vault; đường gửi W1 qua cửa công cụ: marketing-pilot:R6.4); agent liên kết bị tắt → stack con từ chối                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| AL16 | Cách ly tenant của công tắc                                                  | R7.1, R8.1                                 | Đóng băng, tắt của tenant A không chạm run của tenant B; đọc công tắc của B từ A → 404; gỡ FORCE RLS → `test_rls_coverage.py` đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| AL17 | Chủ thể hay công ty không active không chạy tiếp                             | R9.1, R9.2                                 | Gỡ thành viên khỏi công ty rồi tiếp tục lượt chạy chờ duyệt của người đó → `cancelled` `principal_inactive`, 0 lời gọi model; đặt `suspended` bằng SQL rồi nhận lượt mới → như trên; tài khoản dịch vụ `suspended` rồi lượt `datahub` của nó tới cửa nhận (làn giả) → giữ `queued` với `principal_inactive`, 0 lời gọi model, kích hoạt lại tài khoản → chạy theo thứ tự đến; khóa công ty rồi nhận lượt mới → `cancelled` `tenant_locked`; công ty `offboarding` → `tenant_offboarding`; gỡ kiểm ở `require_open` → test đỏ                                                                                                                                                                                                                   |
| AL18 | Gỡ Đóng băng của công ty cần người thứ hai                                   | R7.10, R7.11                               | Người xin gỡ tự duyệt `studio.lifecycle.unfreeze` → 409, Đóng băng còn; người khác duyệt → gỡ; gỡ luật nghiêm của `studio.lifecycle.` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| AL19 | Phát hành không đè phiên bản Đang dùng mới hơn bản đã so lúc gửi             | R1.8, R2.10, R5.9                          | Một phiên bản đối tượng chỉ siết lên `live` trong lúc một Bản ứng viên của cùng thành phần chờ duyệt, rồi duyệt Bản ứng viên → nó về `draft` với `base_changed` và audit, phiên bản `live` vẫn là bản chỉ siết; `dw_app` UPDATE `awaiting_approval → live` với `compared_live_hash` cũ → 23514; gỡ luật khỏi trigger hay kiểm khỏi handler → test đỏ                                                                                                                                                                                                                                                                                                                                                                                           |
| AL20 | Phát hành cần mọi Điểm gắn bắt buộc đã có giá trị duyệt                      | R2.11, R5.10                               | Phiên bản quy trình khai Điểm gắn `principal` bắt buộc chưa có giá trị đã duyệt → gửi kiểm định 409 `binding_unset` nêu `principal`, phiên bản vẫn Nháp; handler nhận quyết định duyệt khi `PublishBindingsCheck` trả `binding_unset` → phiên bản không lên Đang dùng; gỡ kiểm ở lệnh gửi hay ở handler → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                              |

## Tiêu chí xong

- Mọi tiêu chí R và G có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (ghi ở Comments của
  ticket).
- `make ci && make test-integration` xanh; `reviewing-feature-security` và `reviewing-deployment-security`
  đã chạy trên từng ticket có route, migration hay lane; `.claude/plans/studio.md` ghi lát W1 đã xong.

## Phụ thuộc

- tenant-config: vỏ `studio.artifact_versions` với cột `stage` (CHECK năm giai đoạn, không DEFAULT),
  bước niêm phong (gồm loại không cổng, tenant-config:R2.13, tenant-config:R2.16), sổ loại
  `studio.artifact_kinds` với cờ `has_quality_gate` cho luật theo loại của R1.6 (tenant-config:R2.14) và khóa
  đọc, ghi, gửi của loại trong `ArtifactKindRegistry` cho route gửi của R2.1 (tenant-config:R2.15)
  (`.claude/plans/studio/tenant-config/issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md`);
  băm `dw_kernel.canonical` (`.claude/plans/studio/tenant-config/issues/01-bam-chuan-hoa-jcs.md`); chế
  độ `simulate` chặn tác động ở executor (tenant-config:R5.1,
  `.claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md`); bản kê lượt chạy
  ghim phiên bản (`.claude/plans/studio/tenant-config/issues/04-ban-ke-luot-chay.md`); `BindingStatus.satisfied`
  đáp ứng `PublishBindingsCheck` của R2.11, R5.10 (tenant-config:R7.2), nên ticket 04 chờ
  `.claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md`.
- studio-skeleton: gói `dw_studio`, nhóm route `/api/v1/studio`, schema `studio`
  (`.claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md`,
  `.claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md`); ticket 01 chờ
  studio-skeleton/01 vì test phủ offboarding và `STUDIO_EXCLUSIONS` mà R10.1 dựa vào do ticket đó dựng
  (studio-skeleton:R4.3).
- tenant-rbac: danh mục quyền là một chủ (tenant-rbac:R1.1), bảng `platform.permissions` do
  `.claude/plans/studio/tenant-rbac/issues/01-mot-chu-cho-quyen.md` tạo; mỗi khóa của spec này (mục Trong phạm
  vi) đăng ký trong migration của ticket dùng nó, theo quy ước khu vực số nhiều của ticket đó; mọi ticket đăng ký
  khóa (01, 03, 04, 05) chờ `.claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md` và nêu trong
  INSERT mọi cột NOT NULL của bảng lúc đó, gồm `risk` của tenant-rbac/01 và `tenant_grantable` của tenant-rbac/02.
- custom-objects: bộ so sánh chỉ siết của loại `object` (custom-objects:R1.8) và móc phát hành của loại, móc chỉ
  áp định nghĩa và không ghi audit, vì spec này ghi `studio.version.published` đúng một lần (R2.9, R5.5); loại
  phê duyệt `studio.publish.object` là của custom-objects (custom-objects:R1.2), cơ chế mở, guard và handler là
  của spec này (R5.1, R5.5).
- workflow-nodes: Bước `human.approval` nhận quyết định giả lập ở `simulate` theo từ vựng `approved`, `rejected`
  (workflow-nodes:R9.9), ghi `studio.step.approval.simulated` (N2; R4.7), và kiểm người duyệt lúc gửi kiểm định
  (workflow-nodes:R9.5).
- foundations-hardening: compare-and-set trên đường resume
  (`.claude/plans/studio/foundations-hardening/issues/06-run-va-outbox-khong-ket.md`), nơi ticket 01 chèn phép
  kiểm công tắc nên ticket 01 chờ nó; trạng thái công ty cho R9.2 (foundations-hardening:R3.3); ticket 03 chờ
  `.claude/plans/studio/foundations-hardening/issues/07-offboarding-xuat-mot-lan-theo-lo.md` vì cùng sửa
  `_ORDERED_FIRST` của lane `offboarding` (studio-skeleton:R4.2).
- Thứ tự cửa trong gateway có cấu trúc: công tắc (ticket 01), Lộ trình dữ liệu
  (`.claude/plans/studio/compliance-pdpl/issues/03-tuyen-du-lieu-o-model-gateway.md`, chờ ticket 01), rồi hạn mức
  (`LimitsMiddleware` của usage-and-limits/03, chờ compliance-pdpl/03).
- Lưu giữ và offboarding: định dạng tệp chính sách retention (telemetry-and-audit:R5.6) và lane lưu giữ bỏ qua
  sự kiện bị giữ khi Đóng băng (telemetry-and-audit:R5.5); tệp retention đi theo một chuỗi ticket, mỗi ticket một
  phiên bản mới, trong đó ticket 04 đứng ngay sau
  `.claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md`; `platform.drop_expired_partitions` và
  `platform.purge_tenant_append_only` của usage-and-limits/02 (usage-and-limits:R3.8); `STUDIO_EXCLUSIONS` và
  test phủ offboarding (studio-skeleton:R4.1, studio-skeleton:R4.3).
- Protocol do bên dùng khai: `RunControlPort` và `RunHaltedError` (runtime khai, spec này đáp ứng bằng
  `SqlRunControl`, đọc trạng thái thành viên của org-and-principals cho `principal_inactive`); `ClosureExtractor`
  theo loại (agent-builder, workflow-engine cung cấp); bảng kiểm theo loại lúc gửi kiểm định (spec này khai;
  Phân tích năng lực của
  `.claude/plans/studio/compliance-pdpl/issues/05-phan-tich-bo-ba-khi-xuat-ban.md` và kiểm workflow-nodes:R9.5
  đăng ký vào); `PublishBindingsCheck` (spec này khai, tenant-config/05 đáp); `LimitsPort` cho lease
  `eval_offline` của Lượt kiểm định (runtime khai, `dw_usage` đáp;
  `.claude/plans/studio/usage-and-limits/issues/03-han-muc-giu-truoc-va-quyet-toan.md`); làn `studio_inbound`
  của workflow-triggers giữ và xin lại sự kiện đã giữ (workflow-triggers:R1.3); làn `studio_runs` thi hành
  cửa nhận theo `trigger_kind` theo bảng từ chối ở dispatch của workflow-engine, gồm hai hàng `principal_inactive`
  (workflow-engine:R5.15, workflow-engine:R5.17) và hàng `tenant_locked`, `tenant_offboarding`
  (workflow-engine:R5.18) (`.claude/plans/studio/workflow-engine/issues/04-lan-studio-runs.md`); việc giữ lượt của
  tài khoản dịch vụ không `active` là org-and-principals:R4.9, còn báo người chịu trách nhiệm và route hủy từng lượt
  đang giữ đến ở W2 của workflow-engine, nên ở W1 chỉ Tắt khẩn cấp hủy lượt đang giữ (R8.1); lane gửi tin đã xếp
  hàng kiểm công tắc trước khi gửi (R8.4), chủ là connections-and-vault ở W2.
- workflow-engine/01 chờ ticket 03, vì ticket 03 đăng ký khóa gửi `studio.versions.submit` mà mục
  `ArtifactKindRegistry` của loại `workflow` khai (cạnh nằm ở ticket đó).
- Hai ghim cho một lượt chạy Studio: release manifest ghim lớp nền tảng, Bản kê lượt chạy ghim phần Studio
  với Mã băm định nghĩa của gốc; ADR-0109 (Accepted) và ADR-0120 (Accepted) ghi điều đó, và `CLAUDE.md` mục
  'Non-negotiable architecture' sửa theo khi Đạt nhận hai ADR. Cache công tắc đóng khi lỗi, trái cache
  AccessContext mở khi lỗi (ADR-0024 (Proposed) quyết 4), có chủ ý.
- Kiểm lại khi: sổ loại của tenant-config đổi cờ có Cổng chất lượng hay khóa của loại → R1.6, R2.1, ticket 03;
  custom-objects đổi bộ so sánh chỉ siết → R1.7, R2.8, ticket 04; usage-and-limits đổi
  `platform.purge_tenant_append_only` hay telemetry-and-audit đổi định dạng tệp retention → Dữ liệu, ticket 04;
  danh mục quyền của
  tenant-rbac đổi tên → R5, R7, R8; phân loại công cụ của tools-and-skills đổi enum → R6; hợp đồng
  `RunControlPort` đổi hình → R7, R8, R9, ticket 01; hợp đồng `LimitsPort` đổi → R4.4, R4.5, ticket 04;
  workflow-triggers đổi làn `studio_inbound` → R7.2; compliance-pdpl đổi chỗ ghi kết quả Phân tích năng lực
  → R6, ticket 04; tenant-config đổi hình `BindingStatus` hay Điểm gắn bắt buộc → R2.11, R5.10, ticket 04;
  workflow-engine đổi bảng từ chối ở dispatch → R9.1, R9.2, ticket 01.

## Câu hỏi còn mở

- Q3. Theo Luật AI 134/2025/QH15: ai là "nhà cung cấp" của agent do tenant dựng, agent marketing có là
  rủi ro trung bình, và tin do AI soạn có người duyệt có buộc gắn nhãn? Chủ: luật sư. Không đổi: tới khi có
  lời đáp, công ty tự phân hạng từ mặc định, không khai thấp hơn ở v1, và nhãn "do AI soạn" bật mặc định
  (DO-60); câu trả lời chỉ chạm hồ sơ Mức rủi ro AI và gói hồ sơ AI ở W2.

## Quyết định

- 23/10/2026 (Đạt): DO-05 (O1): hợp đồng Giai đoạn nằm trên hàng của vỏ chung `studio.artifact_versions`,
  không có `active_version_id`. Hỏi: Q1. Sửa: R1, Dữ liệu. (Phần còn lại của DO-05 về bảng phiên bản
  theo loại vẫn mở.)
- 23/10/2026 (người yêu cầu): D11 (DO-07): phát hành và bật lại cần hai người; tenant chỉ một người giữ
  `studio.publish.approve` không phát hành được (hệ quả của R5.2). Sửa: R5.2, R8.6.
- 23/10/2026 (agent, tạm): DO-28 theo khuyến nghị (a): Đóng băng v1 hủy lượt chạy đang chạy ở cửa kế
  tiếp, giữ lượt chờ duyệt ở nguyên, từ chối quyết định. Sửa: R7.1. Nếu sai thì: đỗ lượt chạy (`frozen`)
  rồi tiếp tục sau khi gỡ ở v1.5, sau nguyên mẫu của ticket 01.
- 23/10/2026 (agent, tạm): DO-30 theo khuyến nghị (a): phiên bản quy trình con và agent liên kết ghim
  lúc gửi kiểm định. Sửa: R2.1. Nếu sai thì: theo bản đang chạy, và Lệch cấu hình đổi nghĩa.
- 23/10/2026 (agent, tạm): DO-39 theo khuyến nghị (a): người chịu trách nhiệm rời công ty chặn phát
  hành, phiên bản Đang dùng vẫn chạy (YC10, W2). Sửa: Ngoài phạm vi.
- 23/10/2026 (agent, tạm): số của Cổng chất lượng và ai trả chi phí kiểm định nằm ở
  `configs/policies/studio_gate@1.0.0.yaml` ghim trong release manifest; Bộ kiểm định an ninh nền tảng
  cố định 100%. Hỏi: Q2. Nếu sai thì: đổi dữ liệu chính sách, không sửa R4.
- 23/10/2026 (agent, tạm): mẫu control plane "đã kiểm định thật N/M" (chỉ đếm lượt có bộ đề và có chấm)
  và cảnh báo kiểu (kill, nháp để lâu, Lệch cấu hình, kiểm định dưới ngưỡng) lấy từ phân tích đối thủ
  (config-chang.md mẫu 3, YC75) — một mẫu học được, không phải mã của họ; đọc theo quyền người xem và
  chặn ở server; đưa vào W2. Sửa: Ngoài phạm vi.
- 23/10/2026 (Đạt): xác nhận nội dung dòng DO-05 (O1) ở trên, ghi ngày 23/10/2026; DO-05 theo (a) trọn
  vẹn: một vỏ chung `studio.artifact_versions` mang `stage` của ADR-0120 (Accepted) cho mọi loại, `live`
  lưu một lần, không `active_version_id`, phần bảng phiên bản theo loại đã đóng; trigger giai đoạn có luật
  theo loại cho loại không có Cổng chất lượng (cùng D:mcp-client:R3.4 và D:field-security:R1.4). Hỏi: Q1.
  Sửa: R1.6, Dữ liệu, Phụ thuộc, ticket 03.
- 23/10/2026 (Đạt): DO-29.1 theo (a), chỉ cho trường có bên đọc ở W1: `pass_k` = 3, USD 0,10 mỗi lần
  thử, USD 10 mỗi lượt, hạn duyệt phát hành 14 ngày, Bộ kiểm định an ninh nền tảng cố định 100%;
  `min_cases_total`, `pass_rate_min`, `stale_draft_days` vào `studio_gate` cùng bên đọc ở W2. DO-29.2 theo
  (a): công ty trả kiểm định của mình, nền tảng trả lượt kiểm định lại do nền tảng kích (W2). Hỏi: Q2.
  Sửa: R5.7, Ngoài phạm vi, ticket 04.
- 23/10/2026 (Đạt): H:agent-lifecycle:R4.1 theo (a): W1 chỉ chạy Bộ kiểm định an ninh nền tảng;
  `studio.gate_run_datasets` sang W2 cùng bộ đề của tenant. Sửa: R4, R4.1, R4.6, Dữ liệu, ticket 04.
- 23/10/2026 (Đạt): ADR-0109 (Accepted) và ADR-0120 (Accepted) nhận kèm sửa: hai ghim (release manifest
  cho lớp nền tảng, Bản kê lượt chạy cho Studio), bằng chứng kiểm định khóa theo Mã băm hiệu lực. Sửa:
  R4.6, Dữ liệu, Phụ thuộc, Ngoài phạm vi.
- 23/10/2026 (Đạt): DO-21.3 và DO-21.4 theo (a): Lượt kiểm định xin lease `eval_offline` qua `LimitsPort`,
  không đọc `profile.max_cost_usd_per_run`; từ chối là `error` với `limit_exceeded`, không mã HTTP vì lane
  không có người gọi. Sửa: R4, R4.4, AL9, Ngoài phạm vi, Phụ thuộc, ticket 04.
- 23/10/2026 (Đạt): B:agent-lifecycle:R6.1\~compliance-pdpl:R4.2 theo (a): Phân tích năng lực chạy lúc gửi
  kiểm định và trả 422 ở đó; compliance-pdpl giữ module và ghi kết quả; lane `studio_gate` chỉ đọc kết quả
  làm chốt chặn (cổng trượt, không 422). D:agent-lifecycle:R2.1\~workflow-nodes:R9.5 theo (a): một khóa phát
  hành chung `studio.publish.approve`, không khóa theo loại; điều kiện riêng của loại là một kiểm đăng ký ở
  bảng kiểm theo loại ở composition root. Sửa: R2.7, R6, AL10, API, Trong phạm vi, Ngoài phạm vi, ticket
  03, 04.
- 23/10/2026 (Đạt): DO-28 theo C, thay dòng DO-28 tạm ở trên: cửa nhận tách theo `trigger_kind`; lượt
  tương tác và lần thử của Lượt kiểm định nhận `tenant_frozen` ngay; lượt do trình kích hoạt đã xếp hàng
  giữ `queued` và chạy theo thứ tự sau khi gỡ; Tắt khẩn cấp vẫn hủy; đóng băng từ chối gửi kiểm định
  (ADR-0120 (Accepted) quyết 7 sửa theo). Sửa: R7.1, R7.7, R7.8, R7.9, R8.1, AL11, Ngoài phạm vi, ticket
  01, 03, 05.
- 23/10/2026 (Đạt): H:agent-lifecycle:R7.2~workflow-triggers:R1.3 theo (a): làn `studio_inbound` hỏi
  `RunControlPort` mỗi chu kỳ, để nguyên sự kiện khi đóng băng và xin lại theo `received_at` khi gỡ; spec này
  chỉ trả trạng thái. Sửa: R7.2, Phụ thuộc, ticket 01.
- 23/10/2026 (Đạt): H:org-and-principals:R4.6 theo (b): `RunControlPort` thêm lý do `principal_inactive`,
  kiểm ở cửa nhận và cửa tiếp tục; dựng lại scope sống khi tiếp tục là việc của workflow-engine. Sửa: R9,
  AL17, Trong phạm vi, API, ticket 01.
- 23/10/2026 (Đạt): OPS-a.1 theo "người": handler phát hành, handler bật lại, handler gỡ Đóng băng và lane
  `control_switch` thi hành quyết định của một người nên ghi actor là người đó cùng `details.lane`
  (ADR-0011 (Accepted)); lane hủy phê duyệt phát hành hết hạn tự làm nên ghi `system:<lane>`. Sửa: R5.5,
  R5.7, ticket 01, 04, 05.
- 23/10/2026 (người đặt yêu cầu và Đạt): D11 xác nhận 23/10/2026, phạm vi "đóng một người, mở hai người":
  Đóng băng và Tắt khẩn cấp một người cộng audit; gỡ Đóng băng của công ty và bật lại cần người thứ hai.
  Sửa: R7.10, R7.11, AL18, API, ticket 01.
- 23/10/2026 (Đạt): D:mcp-client:R3.4~tenant-config theo (a): công cụ MCP qua máy giai đoạn, `suspended` là
  công tắc với `scope_type` `tool` (W2), trigger giai đoạn có luật cho loại không cổng. Sửa: R1.6, Ngoài
  phạm vi.
- 23/10/2026 (Đạt): DO-30 theo (a) và DO-39.2 theo (a): xác nhận hai dòng tạm cùng tên ở trên. DO-60 theo
  (a) cho phân hạng: công ty tự phân hạng từ mặc định, không khai thấp hơn ở v1; nhãn "do AI soạn" bật mặc
  định tới khi luật sư trả lời; kiểm định trực tuyến tắt mặc định, model chấm cùng Lộ trình dữ liệu (W2).
  Sửa: Q3, Ngoài phạm vi.
- 23/10/2026 (Đạt): DO-02.2 theo (a): partition của mọi bảng trong sổ `platform.time_partitioned_tables`
  không cấp quyền nào cho `dw_app`; `studio.gate_case_results` đăng ký bằng một dòng sổ. Sửa: Hiện trạng,
  Dữ liệu, ticket 04.
- 23/10/2026 (agent, tạm): D:agent-lifecycle:R5.2~R5.6: `author_ids` dựng từ `contributor_ids` và
  `submitted_by` của dòng phiên bản trong giao dịch mở yêu cầu phê duyệt, có test khớp, vì `DecisionGuard`
  đồng bộ không đọc được cột phiên bản. Sửa: R5.1, AL5, ticket 04. Nếu sai thì: guard đọc cột phiên bản qua
  một port.
- 23/10/2026 (agent, tạm): B:agent-lifecycle/05~dữ-liệu: ghi công tắc `kill` phát outbox
  `control.switch.changed` v1 chỉ id trong cùng giao dịch cho lane `control_switch`. Sửa: Dữ liệu, Trong phạm
  vi, ticket 05. Nếu sai thì: lane đọc NOTIFY `dw_control_switch`.
- 23/10/2026 (agent, tạm): I:agent-lifecycle/05~workflow-triggers/01: đường gửi và trình kích hoạt thật được
  chứng minh ở marketing-pilot/05 (marketing-pilot:R6.4); ticket 05 giữ test hợp đồng với lane giả. Sửa:
  AL15, ticket 05. Nếu sai thì: ticket 05 chờ workflow-triggers/01 và ticket lane gửi của
  connections-and-vault.
- 24/10/2026 (Đạt): Q-R6, phát hành chỉ siết: phiên bản `dw.object/v1` mà bộ so sánh của loại báo chỉ siết đi
  `draft → live` bởi người gửi, có audit; mọi phiên bản có nới, và phiên bản đầu, vẫn qua Chờ duyệt và người thứ
  hai; trigger kiểm cột `tighten_only` và `compared_live_hash` do `LifecycleService` ghi lúc gửi
  (ADR-0120 (Accepted) quyết 1); `studio.version.published` ghi người duyệt và `details.path` `approved` khi qua phê
  duyệt, người gửi và `tighten_only` ở nhánh chỉ siết (B:agent-lifecycle:R1.6\~custom-objects:R1.7). Sửa: R1.6,
  thêm R1.7, R2.8, R2.9, R5.5, R5.6, AL4, Dữ liệu, Trong phạm vi, ticket 03, 04.
- 24/10/2026 (người đặt yêu cầu và Đạt): D11, thu hẹp `default_access` là một người cộng audit, qua nhánh chỉ
  siết của R1.7; gỡ Đóng băng của công ty cần người thứ hai qua `studio.lifecycle.unfreeze` như R7.10, R7.11 đã
  viết, và ADR-0120 (Accepted) quyết 7 ghi cơ chế này (D:ADR-0120 (Accepted)\~R7.10). Sửa: R1.7; R7.10, R7.11,
  AL18 giữ nguyên.
- 24/10/2026 (Đạt): ADR-0120 (Accepted) quyết 3 sửa theo spec: chi phí xấu nhất vượt trần thì Lượt kiểm định
  kết thúc `error` với `limit_exceeded`, không mã 422, vì lane không có người gọi HTTP
  (F:ADR-0120 (Accepted)\~R4.4). Sửa: không đổi R4.4, AL9.
- 24/10/2026 (Đạt): luật theo loại đọc cột `has_quality_gate` của `studio.artifact_kinds` (tenant-config:R2.14)
  (B:agent-lifecycle:R1.6\~tenant-config:dữ-liệu). Sửa: R1.6, Dữ liệu, Phụ thuộc, ticket 03.
- 24/10/2026 (Đạt): spec này là chủ route gửi của mọi loại, kể cả loại không có Cổng chất lượng
  (`POST /api/v1/studio/{agents|workflows|objects}/.../submit`, khóa gửi do `ArtifactKindRegistry` khai,
  tenant-config:R2.15), và của payload `author_ids`, guard `require_not_author` và handler
  `studio.publish.<kind>.decided` cho mọi loại theo ADR-0120 (Accepted) quyết 2; loại phê duyệt
  `studio.publish.object`, bộ so sánh và móc phát hành là của custom-objects (B:agent-lifecycle:api\~custom-objects:R1.2,
  B:agent-lifecycle:R5.1\~custom-objects/02). Sửa: R2.1, R2.4, R2.8, R5.1, R5.5, API, Trong phạm vi, Phụ thuộc, ticket
  03, 04.
- 24/10/2026 (Đạt): `requested_by` của yêu cầu phê duyệt phát hành là `submitted_by` của phiên bản, kể cả khi
  lane `studio_gate` mở yêu cầu; theo ADR-0004 (Accepted) sửa đổi 07/10/2026, người không giữ tem và không phải
  người xin nhận 404, người xin đọc được yêu cầu của mình mà không quyết định được (F:ADR-0004 (Accepted)\~R5.4).
  Sửa: R5.1, R5.4, thêm R5.8, AL6, ticket 04.
- 24/10/2026 (Đạt): N2: trong lượt `simulate`, Bước `human.approval` không chờ người thật mà nhận quyết định giả
  lập do Câu kiểm định khai (hay do người thử chọn trong biểu mẫu chạy mô phỏng), ghi audit
  `studio.step.approval.simulated` và không bao giờ thỏa một phê duyệt `live`; ở ToolExecutor chế độ chạy đứng
  trước phê duyệt khi chế độ khác `live` (tools-and-skills:R2.6; ADR-0111 (Accepted) quyết 5). Sửa: R4.1, R4.3,
  thêm R4.7, AL8, ticket 04.
- 24/10/2026 (Đạt): sự kiện bị giữ khi Đóng băng không bị lane lưu giữ xóa, lane đó bỏ qua và đếm chúng, và Đóng
  băng không có trần thời gian (B:agent-lifecycle:R7.2\~telemetry-and-audit:R5.5). Sửa: R7.2.
- 24/10/2026 (Đạt): handler `studio.publish.<kind>.decided` không đưa phiên bản sang Đang dùng khi Đóng băng của
  công ty hay nền tảng đang mở (F:ADR-0120 (Accepted)\~R7.9). Sửa: thêm R7.12, AL11, ticket 04.
- 24/10/2026 (Đạt): `RunControlPort` từ chối `tenant_locked` và `tenant_offboarding` ở W1, đọc trạng thái công ty
  mà foundations-hardening/02 canh; `workspace_archived` đến ở W2 cùng org-and-principals
  (F:ADR-0120 (Accepted)\~agent-lifecycle:api). Sửa: R9, thêm R9.2, AL17, API, Trong phạm vi, Ngoài phạm vi,
  ticket 01.
- 24/10/2026 (Đạt): lane gửi tin đã xếp hàng của R8.4 thuộc connections-and-vault, ở W2; W1 thử hợp đồng với lane
  giả, còn đường gửi W1 của lát đi qua cửa công cụ (I:agent-lifecycle:R8.4\~agent-lifecycle:phụ-thuộc). Sửa: R8.4,
  AL15, Ngoài phạm vi, Phụ thuộc, ticket 05.
- 24/10/2026 (Đạt): mỗi ticket dùng một khóa quyền đăng ký khóa đó (nhãn, `scope_kind`, `risk`) trong migration của
  mình theo quy ước của tenant-rbac/01 (B:agent-lifecycle:phụ-thuộc\~tenant-rbac/01); tên khóa theo khu vực số
  nhiều `studio.<areas>.<verb>`. Sửa: Trong phạm vi, Ngoài phạm vi, Phụ thuộc, ticket 01, 03, 04, 05.
- 24/10/2026 (agent, tạm): theo luật khu vực số nhiều, `studio.eval.run` đổi thành `studio.evals.run`;
  `studio.lifecycle.*`, `studio.publish.approve` và `studio.versions.*` giữ tên vì khu vực không đếm được hay đã
  số nhiều. Sửa: API, Trong phạm vi, ticket 04. Nếu sai thì: giữ `studio.eval.run` trong migration đăng ký.
- 24/10/2026 (Đạt): thứ tự cửa trong gateway có cấu trúc là công tắc, Lộ trình dữ liệu, rồi hạn mức;
  compliance-pdpl/03 chờ ticket 01, và ticket 01 chờ foundations-hardening/06 vì cùng sửa đường resume
  (C:agent-lifecycle/01\~compliance-pdpl/03). Sửa: Phụ thuộc, ticket 01.
- 24/10/2026 (agent, tạm): `strict_approval_prefixes` và `decision_guards` theo cách sửa thứ hai của
  C:agent-lifecycle:R7.10\~tenant-config:R8.8: ticket 01 và 04 mỗi ticket chỉ thêm một dòng `|=` cho tiền tố của
  mình và một khóa guard, kèm test khẳng định tập tiền tố đầy đủ, như tenant-config/05 đã làm, không thêm cạnh
  tới tenant-config/05 hay workflow-nodes/06, để ticket 01 và 04 không phải chờ hai ticket đó chỉ vì một dòng ở
  composition root. Sửa: ticket 01, 04. Nếu sai thì: ticket 01 chờ tenant-config/05 và ticket 04 chờ
  workflow-nodes/06.
- 24/10/2026 (Đạt): offboarding xuất rồi xóa `platform.control_switches` của công ty, và `studio.gate_case_results`
  có thời hạn trong tệp chính sách retention ngay khi đăng ký và một dòng `STUDIO_EXCLUSIONS` nêu cách xóa
  (H:ADR-0121 (Accepted)\~usage-and-limits:dữ-liệu theo cách sửa của studio-skeleton:R4.3;
  I:studio-skeleton:R3.7\~usage-and-limits/02). Sửa: R7.5, thêm R10, AL12, Dữ liệu, Phụ thuộc, ticket 01, 04.
- 24/10/2026 (agent, tạm): `dw_app` giữ DELETE trên `platform.control_switches` chỉ cho lượt xóa của offboarding,
  trigger `platform.guard_control_switch()` từ chối DELETE khi công ty không ở `offboarding`, để xóa không thành
  một cách gỡ Tắt khẩn cấp; thời hạn `studio.gate_case_results` là 395 ngày (13 tháng), số tạm UNVERIFIED bằng Sổ
  sử dụng, vì chưa nguồn nào đặt số. Sửa: R7.5, R10.1, Dữ liệu, ticket 01, 04. Nếu sai thì: xóa công tắc qua một
  hàm SECURITY DEFINER của offboarding; đổi số thời hạn trong bản kế tiếp của tệp.
- 24/10/2026 (Đạt): kiểm người duyệt của workflow-nodes đăng ký vào bảng kiểm theo loại lúc gửi kiểm định và trả
  422 với mã riêng (B:agent-lifecycle:R2.7\~workflow-nodes:R9.5). Sửa: API.
- 24/10/2026 (Đạt): mọi lần gửi, không chỉ nhánh chỉ siết, ghi `compared_live_hash` (mã băm của phiên bản Đang dùng
  lúc gửi, NULL khi chưa có); chuyển sang `live` chỉ được khi mã đó vẫn là của phiên bản Đang dùng mà lần phát hành
  thay, trigger canh như canh nhánh chỉ siết; handler `.decided` của phê duyệt đã duyệt mà gốc đã đổi không phát hành,
  đưa phiên bản về Nháp với `base_changed` và một audit, người dựng gửi lại để so với bản Đang dùng mới
  (D:ADR-0120 (Accepted)\~tenant-config:R2.16). Sửa: thêm R1.8, R2.10, R5.9, sửa R2.8, AL19, Dữ liệu, API, ticket 03, 04.
- 24/10/2026 (Đạt): nhánh chỉ siết của `dw.object/v1` đi qua được Đóng băng của công ty, vì nó chỉ bớt quyền; mọi lần
  gửi, Lượt kiểm định và phát hành khác vẫn bị từ chối `tenant_frozen`, và Đóng băng của nền tảng từ chối cả nhánh này
  (F:ADR-0120 (Accepted)\~custom-objects:R1.7). Sửa: R7.9, thêm R7.13, AL11, ticket 04.
- 24/10/2026 (Đạt): lượt `datahub`, `provider_app`, `record_event` mà tài khoản dịch vụ chạy dưới danh nghĩa không
  `active` ở lại `queued` với `principal_inactive`, như Đóng băng giữ lượt kích hoạt, và chạy theo thứ tự đến khi tài
  khoản `active` lại; lượt tương tác vẫn bị từ chối, lượt `schedule` giữ cách ADR-0113 (Accepted) quyết 3 ghi
  (F:ADR-0113 (Accepted)\~org-and-principals:R4.6). Sửa: R9, R9.1, AL17, Phụ thuộc, ticket 01.
- 24/10/2026 (agent, tạm): tệp chính sách retention giữ một tệp có phiên bản `configs/policies/retention@<semver>.yaml`;
  các ticket sửa tệp đi thành một chuỗi, mỗi ticket ra một phiên bản mới: studio-skeleton/01, usage-and-limits/02,
  usage-and-limits/03, telemetry-and-audit/03, ticket 04, workflow-triggers/02, compliance-pdpl/04, agent-builder/04,
  compliance-pdpl/06; ticket 04 chờ telemetry-and-audit/03 (C:configs:spec\~telemetry-and-audit/03). Sửa: Phụ thuộc,
  ticket 04. Nếu sai thì: tách tệp theo bảng, sửa telemetry-and-audit:R5.6 và ADR-0122 (Accepted) quyết 7.
- 24/10/2026 (agent, tạm): mọi ticket chèn dòng vào `platform.permissions` (01, 03, 04, 05) chờ tenant-rbac/02 và nêu
  trong INSERT mọi cột NOT NULL có lúc đó, gồm `tenant_grantable` của tenant-rbac/02 và `risk` của tenant-rbac/01,
  theo ADR-0104 (Accepted) quyết 1 (C:custom-objects/02\~tenant-rbac/02). Sửa: Phụ thuộc, ticket 01, 03, 04, 05. Nếu
  sai thì: tenant-rbac/01 tạo cột kèm sửa ADR-0104 (Accepted) quyết 1.
- 24/10/2026 (agent, tạm): workflow-engine/01 chờ ticket 03, ticket chủ đăng ký khóa gửi `studio.versions.submit`;
  bên dùng chờ, việc đăng ký không chuyển (I:agent-lifecycle/03\~workflow-engine/01). Sửa: Phụ thuộc, ticket 03. Nếu
  sai thì: workflow-engine/01 đăng ký khóa và ticket 03 chỉ dùng nó.

## Danh sách ticket

| #   | Ticket                                                                                                  |
| --- | ------------------------------------------------------------------------------------------------------- |
| 01  | [Đóng băng toàn nền tảng và theo tenant, kiểm ở mọi cửa](issues/01-dong-bang-va-kiem-o-moi-cua.md)      |
| 02  | [Mở rộng dw_evals: quan sát, bộ chấm, JudgePort, lặp, cổng thuần](issues/02-mo-rong-dw-evals.md)        |
| 03  | [Hợp đồng vòng đời phiên bản và gửi kiểm định niêm phong](issues/03-hop-dong-vong-doi-va-niem-phong.md) |
| 04  | [Cổng chất lượng mô phỏng và duyệt phát hành hai người](issues/04-cong-kiem-dinh-va-duyet-hai-nguoi.md) |
| 05  | [Tắt khẩn cấp agent và quy trình, bật lại hai người](issues/05-tat-khan-cap-va-khoi-phuc.md)            |
