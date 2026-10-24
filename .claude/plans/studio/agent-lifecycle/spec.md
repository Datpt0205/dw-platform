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
- R1.2 `studio.artifact_versions` PHẢI giữ tối đa một phiên bản Đang dùng cho mỗi thành phần bằng chỉ mục duy nhất
  từng phần, còn tối đa một phiên bản chưa phát hành (Nháp, Đang kiểm định hay Chờ duyệt) mỗi thành phần là chỉ mục
  duy nhất từng phần của tenant-config, phủ cả luật một Bản ứng viên (tenant-config:R2.20; ADR-0120 (Accepted)
  quyết 1).
- R1.3 NẾU hai lệnh Gửi kiểm định song song cùng gửi bản Nháp duy nhất của một thành phần, THÌ dịch vụ vòng đời PHẢI
  để một lệnh thành công và trả lệnh kia 409 `candidate_exists`, không mở Lượt kiểm định, yêu cầu phê duyệt hay audit
  thứ hai.
- R1.4 KHI một phiên bản sang Đang dùng, ở nhánh chỉ siết (R2.9) hay ở handler phát hành (R5.5), `LifecycleService`
  PHẢI đưa phiên bản Đang dùng trước đó sang Đã gỡ với lý do `superseded` trong cùng giao dịch, vì nó là bên duy nhất
  ghi `live` (ADR-0120 (Accepted) quyết 1).
- R1.5 Giai đoạn hiển thị của một thành phần PHẢI do một view SQL tính theo thứ tự Bị kill, Đang dùng,
  Chờ duyệt, Đang kiểm định, Nháp, Đã gỡ, và không bao giờ được lưu thành cột.
- R1.6 ĐỐI VỚI một loại thành phần mà `studio.artifact_kinds` ghi `has_quality_gate = false` (đối tượng
  `dw.object/v1` và Nguồn dữ liệu `dw.endpoint/v1` ở W1, công cụ ở W2), `studio.guard_version_stage()` PHẢI cho
  `draft → awaiting_approval` không qua Đang kiểm định và không đòi `gate_run_id`, và vẫn đòi `publish_approval_id`
  đã `approved` cho `awaiting_approval → live`.
- R1.7 ĐỐI VỚI một phiên bản `dw.object/v1` mà `LifecycleService` ghi lúc gửi `tighten_only = true` (bộ so
  sánh của loại báo mọi thay đổi chỉ siết, custom-objects:R1.8) cùng `compared_live_hash`,
  `studio.guard_version_stage()` PHẢI cho `draft → live` không cần phê duyệt khi `compared_live_hash` vẫn bằng
  `definition_hash` của phiên bản Đang dùng mà lần phát hành này thay, tức bản vừa gỡ `superseded` trong cùng giao
  dịch (R1.4; ADR-0120 (Accepted) quyết 1).
- R1.8 NẾU một lệnh ghi chuyển một phiên bản `awaiting_approval → live` mà `compared_live_hash` ghi lúc gửi (R2.10)
  khác, theo `IS DISTINCT FROM`, `definition_hash` của phiên bản Đang dùng mà lần phát hành này thay (gỡ
  `superseded` trong cùng giao dịch), hay khác NULL khi không có bản nào, THÌ PostgreSQL PHẢI từ chối với SQLSTATE
  23514 `ck_artifact_versions_stage_transition` và không đổi gì (ADR-0120 (Accepted) quyết 1).
- R1.9 NẾU một dòng `studio.artifact_versions` trỏ `gate_run_id` hay `publish_approval_id`, một dòng
  `studio.gate_case_results` trỏ `gate_run_id`, hay một dòng `studio.gate_runs` trỏ `artifact_id`, tới Lượt kiểm định,
  yêu cầu phê duyệt hay thành phần của công ty khác, THÌ PostgreSQL PHẢI từ chối dòng đó bằng FK ghép
  `(tenant_id, <cột>)` tới UNIQUE `(tenant_id, id)` của bảng đích, kể cả khi vai ghi bỏ qua RLS.

### R2 — Gửi kiểm định niêm phong nội dung và ghi chỉ mục phụ thuộc

KHI gửi kiểm định, nội dung phiên bản bị niêm phong và bao đóng của nó băm thành Mã băm định nghĩa, để
"đã kiểm định" và Lệch cấu hình tính được (YC30; ADR-0109 (Accepted) quyết 4-5).

- R2.1 KHI người giữ khóa gửi mà `ArtifactKindRegistry` khai cho loại (tenant-config:R2.15) gửi một nháp hợp
  lệ qua `POST /api/v1/studio/{agents|workflows|objects|data-sources}/{artifact_id}/versions/{version_id}/submit`,
  dịch vụ gửi kiểm định PHẢI, trong một giao dịch, tính bao đóng bằng `ClosureExtractor` của loại, niêm phong nội
  dung qua bước niêm phong của tenant-config, ghi Mã băm định nghĩa, Nơi đang dùng và audit
  `studio.version.submitted`, rồi qua `LifecycleService` chuyển phiên bản khỏi Nháp theo luật giai đoạn của loại (R1;
  ADR-0120 (Accepted) quyết 1).
- R2.2 Mã băm định nghĩa của một phiên bản PHẢI là hàm của nội dung niêm phong và bao đóng ghim, nên
  hai phiên bản cùng nội dung và bao đóng cho cùng mã băm, còn một phần bao đóng ghim đổi thì cho mã
  băm khác.
- R2.3 NẾU giao dịch gửi kiểm định hỏng giữa chừng, THÌ dịch vụ gửi kiểm định PHẢI không để lại bản kê
  định nghĩa, dòng Nơi đang dùng hay audit nào của phiên bản đó.
- R2.4 KHI người giữ khóa gửi của loại rút một Bản ứng viên chưa có quyết định qua `POST .../withdraw`, cách người dựng
  sửa tiếp một thành phần đang có Bản ứng viên vì route tạo nháp trả 409 `candidate_pending` (tenant-config:R2.22),
  dịch vụ vòng đời PHẢI đưa phiên bản về Nháp, thành bản chưa phát hành duy nhất của thành phần, và hủy yêu cầu phê
  duyệt phát hành đang treo trong một giao dịch, với audit `studio.version.returned_to_draft`.
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
  sánh của loại trong giao dịch gửi, rồi qua `LifecycleService` đưa phiên bản sang Đang dùng khi chỉ siết (R1.7,
  R2.9) hay sang Chờ duyệt cùng yêu cầu phê duyệt của R5.1 khi không chỉ siết hay chưa có phiên bản Đang dùng.
- R2.9 KHI một lần gửi đi nhánh chỉ siết (R1.7, R2.8), `LifecycleService` PHẢI, trong giao dịch của người gửi, đưa
  phiên bản Đang dùng cũ sang Đã gỡ (`superseded`) rồi đưa phiên bản sang Đang dùng, chạy móc phát hành mà mục
  `ArtifactKindRegistry` của loại mang (tenant-config:R2.15; ADR-0109 (Accepted) quyết 1), ghi đúng một audit
  `studio.version.published` với actor là người gửi và `details.path` `tighten_only`, và outbox
  `studio.version.live` (ADR-0120 (Accepted) quyết 2).
- R2.10 KHI người giữ khóa gửi của loại gửi một phiên bản của bất kỳ loại nào, dịch vụ gửi kiểm định PHẢI ghi
  trong giao dịch gửi `compared_live_hash` bằng `definition_hash` của phiên bản Đang dùng của thành phần lúc đó,
  NULL khi chưa có phiên bản Đang dùng (ADR-0120 (Accepted) quyết 1).
- R2.11 NẾU phiên bản được gửi khai một Điểm gắn bắt buộc chưa có giá trị trong Bộ giá trị gắn đã duyệt, THÌ
  dịch vụ gửi kiểm định PHẢI trả 409 `binding_unset` kèm tên Điểm gắn mà `PublishBindingsCheck` báo và không
  chuyển phiên bản khỏi Nháp (tenant-config:R7.2; ADR-0120 (Accepted) quyết 2).
- R2.12 NẾU lệnh gửi mang `If-Match` khác ETag hiện có của bản Nháp (`row_version` mà lần lưu nháp trả), THÌ dịch vụ
  gửi kiểm định PHẢI trả 412 `precondition_failed` với `details.reason_code` `stale_version`, không niêm phong gì
  và không chuyển phiên bản khỏi Nháp, ở mọi loại (tenant-config:R2.17; ADR-0108 (Accepted) quyết 3;
  ADR-0109 (Accepted) quyết 2).
- R2.13 NẾU lệnh gửi thiếu `If-Match`, THÌ route gửi kiểm định PHẢI trả 428 `precondition_required` và không đổi gì
  (app-standards:R3.3; ADR-0108 (Accepted) quyết 3).

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
- R4.8 KHI người giữ `studio.evals.run` xin Kiểm định thử qua `POST .../versions/{version_id}/dry-evaluations` cho một
  phiên bản `draft` của agent hay quy trình, lane `studio_gate` PHẢI chạy Kiểm định thử (dòng `studio.gate_runs` có
  `purpose` `dry`) trên Bộ kiểm định an ninh nền tảng dưới trần và lease `eval_offline` của R4.4, R4.5, mỗi lần thử là
  một lượt `simulate` có gốc là bản Nháp đó, ghim giai đoạn `draft` và mã băm tạm của nội dung nháp
  (tenant-config:R6.1, workflow-engine:R3.9; ADR-0109 (Accepted) quyết 6) và chạy graph biên dịch theo mã băm đã ghim
  (agent-builder:R3.1, agent-builder:R3.3 cho agent; workflow-engine:R4.2 cho quy trình), mà không niêm phong, không
  đổi giai đoạn của phiên bản và không mở yêu cầu phê duyệt nào.
- R4.9 NẾU `RunRequestService` từ chối một lần thử của Kiểm định thử vì nội dung nháp trượt bộ kiểm trả mọi lỗi của
  loại (workflow-engine:R3.11), THÌ lane `studio_gate` PHẢI kết thúc Kiểm định thử đó là `error` kèm mọi lỗi của lần
  từ chối và không xin thêm lần thử nào.
- R4.10 NẾU người giữ `studio.lifecycle.read` đọc qua `GET /api/v1/studio/gate-runs`, `/{id}` hay `/{id}/cases` một
  Lượt kiểm định, kể cả dòng `purpose` `dry` (R4.8), của thành phần mà khóa đó, ở độ sâu của người đọc, không chạm tới
  `owning_workspace_id` (ADR-0104 (Accepted) quyết 3), THÌ route PHẢI coi Lượt kiểm định đó như không tồn tại: bỏ khỏi
  danh sách và trả 404 khi đọc theo id.
- R4.11 KHI lane `studio_gate` xin một lần thử của Kiểm định thử, lane `studio_gate` PHẢI xin lượt `simulate` đó qua
  `RunRequestService` dưới danh nghĩa người xin Kiểm định thử, để lần thử đọc dưới giới hạn tạm mà cửa đó dẫn ra từ bao
  đóng của bản Nháp, giao với quyền của người xin (workflow-engine:R3.13, record-access:R6.12; ADR-0111 (Accepted)
  quyết 3).

### R5 — Phát hành cần một người không phải Tác giả duyệt

Một phiên bản sang Đang dùng chỉ qua một yêu cầu phê duyệt không lượt chạy mà người quyết định không
phải Tác giả, và PostgreSQL canh đúng điều kiện đó, trừ nhánh chỉ siết của R1.7 (YC70, YC60; D11;
ADR-0120 (Accepted) quyết 1-2).

- R5.1 KHI một phiên bản chuyển sang Chờ duyệt (lane `studio_gate` khi Cổng chất lượng đạt, hay dịch vụ gửi
  kiểm định với loại không có cổng), `LifecycleService` PHẢI, trong cùng giao dịch, mở một yêu cầu phê duyệt
  `studio.publish.<kind>` (`agent`, `workflow`, `object`, `endpoint`; `tool` ở W2, Ngoài phạm vi) có `requested_by`
  là `submitted_by` của dòng phiên bản, `required_scope` `studio.publish.approve`, và payload chỉ id và mã gồm
  `author_ids` dựng từ `contributor_ids` và `submitted_by` của chính dòng đó.
- R5.2 NẾU người quyết định một yêu cầu phê duyệt phát hành có trong `author_ids`, THÌ luồng phê duyệt PHẢI trả 409
  `conflict` và không đổi gì, với `details.reason_code` `second_person_required` khi người đó là người xin
  (`requested_by`, tức người gửi), vì kiểm tiền tố nghiêm `studio.publish.` chạy trước mọi guard
  (ADR-0104 (Accepted) quyết 11), và `author_cannot_approve` khi người đó là người đóng góp không phải người xin.
- R5.3 NẾU payload của một yêu cầu phê duyệt phát hành thiếu `author_ids`, THÌ luồng phê duyệt PHẢI từ
  chối quyết định và không đưa phiên bản sang Đang dùng.
- R5.4 NẾU người đọc hay quyết định một yêu cầu phê duyệt phát hành vừa không giữ tem
  `studio.publish.approve` vừa không phải người xin (`requested_by`), THÌ luồng phê duyệt PHẢI trả 404 khi đọc
  và khi quyết định, kể cả với `platform_admin` (ADR-0004 (Accepted), sửa đổi 07/10/2026).
- R5.5 KHI một yêu cầu phê duyệt `studio.publish.<kind>` được duyệt, handler outbox
  `studio.publish.<kind>.decided` PHẢI, trong một giao dịch và đúng một lần dù sự kiện được giao lại, qua
  `LifecycleService`, bên duy nhất ghi `live` (ADR-0120 (Accepted) quyết 1), đưa phiên bản cũ sang Đã gỡ
  (`superseded`) rồi đưa phiên bản sang Đang dùng, gọi móc phát hành mà mục `ArtifactKindRegistry` của loại mang
  (tenant-config:R2.15; ADR-0109 (Accepted) quyết 1), ghi đúng một audit
  `studio.version.published` với actor là người quyết định, `details.lane` là tên lane và `details.path`
  `approved` (ADR-0011 (Accepted)), và outbox `studio.version.live`.
- R5.6 NẾU `dw_app` đưa một phiên bản sang Đang dùng khi yêu cầu phê duyệt phát hành liên kết chưa ở
  `approved`, khi `gate_run_id` không phải một Lượt kiểm định đạt trên đúng Mã băm định nghĩa của phiên bản
  (loại có Cổng chất lượng), hay khi đi thẳng từ Nháp mà phiên bản không phải `dw.object/v1`, `tighten_only`
  không là true hoặc `compared_live_hash` khác `definition_hash` của phiên bản Đang dùng mà lần phát hành này thay,
  THÌ PostgreSQL PHẢI từ chối với SQLSTATE 23514 và không đổi gì.
- R5.7 KHI một yêu cầu phê duyệt phát hành quá `publish_approval_ttl_days` của Chính sách cổng (14 ngày),
  lane hết hạn phê duyệt phát hành PHẢI hủy yêu cầu, đưa phiên bản về Nháp và ghi audit với actor
  `system:<lane>` trong một giao dịch.
- R5.8 KHI người xin (`requested_by`) mở yêu cầu phê duyệt phát hành của chính mình, luồng phê duyệt PHẢI trả
  yêu cầu đó với `can_decide` là false (ADR-0004 (Accepted), sửa đổi 07/10/2026).
- R5.9 NẾU handler `studio.publish.<kind>.decided` nhận một quyết định duyệt mà `compared_live_hash` của phiên bản
  khác `definition_hash` của phiên bản Đang dùng mà lần phát hành này sẽ thay, hay khác NULL khi không có bản nào
  (R1.8), THÌ handler PHẢI không đưa phiên bản sang Đang dùng, đưa nó về Nháp với `details.reason_code`
  `base_changed` và ghi audit `studio.version.returned_to_draft` (tên lần rút của R2.4 đã dùng) trong cùng giao
  dịch, actor là người quyết định và `details.lane` là tên lane (ADR-0120 (Accepted) quyết 2).
- R5.10 NẾU lúc handler `studio.publish.<kind>.decided` nhận một quyết định duyệt, `PublishBindingsCheck` trả
  `binding_unset` cho phiên bản, THÌ handler PHẢI không đưa phiên bản sang Đang dùng mà đưa nó về Nháp với
  `details.reason_code` `binding_unset` và ghi audit `studio.version.returned_to_draft` trong cùng giao dịch, actor là
  người quyết định và `details.lane` là tên lane (tenant-config:R7.2; ADR-0120 (Accepted) quyết 2).
- R5.11 KHI người được quyết định một yêu cầu phê duyệt `studio.publish.<kind>` còn `pending` (giữ `approvals.decide` và
  tem `studio.publish.approve`, ADR-0004 (Accepted) sửa đổi 07/10/2026) gọi
  `GET /api/v1/studio/publish-approvals/{approval_id}/candidate`, route PHẢI trả nội dung niêm phong của Bản ứng viên và
  phần khác với phiên bản Đang dùng của thành phần, kèm đúng một audit `studio.version.candidate_read` trong giao dịch
  đọc (ADR-0120 (Accepted) quyết 2).
- R5.12 NẾU người gọi `GET /api/v1/studio/publish-approvals/{approval_id}/candidate` không được quyết định yêu cầu đó
  (kể cả người xin không giữ tem, người chỉ giữ khóa tác giả của loại và `platform_admin` không giữ tem), hay yêu cầu đã
  quyết, không thuộc loại `studio.publish.*` hay thuộc công ty khác, THÌ route PHẢI trả 404 như yêu cầu không tồn tại,
  không trả nội dung nào và không ghi audit.

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
- R7.11 NẾU người quyết định gỡ Đóng băng là người xin gỡ, THÌ luồng phê duyệt PHẢI trả 409 `conflict` với
  `details.reason_code` `second_person_required` và không gỡ Đóng băng (ADR-0104 (Accepted) quyết 11).
- R7.12 TRONG KHI một Đóng băng của công ty hay nền tảng đang mở, KHI handler `studio.publish.<kind>.decided`
  nhận một quyết định duyệt, handler PHẢI không đưa phiên bản sang Đang dùng mà đưa nó về Nháp với `details.reason_code`
  `tenant_frozen` hay `platform_frozen` và ghi audit `studio.version.returned_to_draft` trong cùng giao dịch, actor là
  người quyết định và `details.lane` là tên lane (ADR-0120 (Accepted) quyết 2, quyết 7).
- R7.13 TRONG KHI Đóng băng của công ty đang mở và không có Đóng băng của nền tảng, KHI người giữ khóa gửi gửi một
  phiên bản `dw.object/v1` mà bộ so sánh của loại báo chỉ siết, dịch vụ gửi kiểm định PHẢI qua `LifecycleService` đưa
  phiên bản sang Đang dùng theo nhánh chỉ siết (R1.7, R2.9), vì nhánh đó chỉ bớt quyền (ADR-0120 (Accepted) quyết 7).

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
- R8.7 NẾU người quyết định bật lại là người xin bật lại, THÌ luồng phê duyệt PHẢI trả 409 `conflict` với
  `details.reason_code` `second_person_required` và không gỡ công tắc (ADR-0104 (Accepted) quyết 11).
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
  bảng từ chối ở dispatch: lượt `datahub`, `provider_app`, `record_event` đang `queued` ở lại `queued` tới khi tài
  khoản dịch vụ `active` lại (workflow-engine:R5.17, org-and-principals:R4.9), mọi lượt khác kết thúc `cancelled`
  (workflow-engine:R5.15 ở dispatch).
- R9.2 NẾU `platform.tenants.status` của công ty là `locked`, `offboarding` hay `offboarded` khi một lượt chạy
  của công ty đó tới cửa nhận hay cửa tiếp tục, THÌ `RunControlPort` PHẢI từ chối với `tenant_locked` (khi
  `locked`) hay `tenant_offboarding`, và lượt chạy kết thúc là `cancelled` mà không gọi model hay công cụ nào,
  theo hàng `tenant_locked`, `tenant_offboarding` của bảng từ chối ở dispatch (workflow-engine:R5.18;
  foundations-hardening:R3.3).

### R10 — Offboarding xóa công tắc và Lượt kiểm định của công ty

Lane offboarding xuất rồi xóa công tắc điều khiển và Lượt kiểm định của một công ty rời nền tảng như mọi dữ liệu
Studio của nó (YC6), mà không mở cho `dw_app` một đường xóa để gỡ Tắt khẩn cấp hay bỏ bằng chứng kiểm định.

- R10.1 KHI lane `offboarding` xóa dữ liệu của một công ty đang `offboarding`, lane `offboarding` PHẢI xuất rồi
  xóa mọi dòng `platform.control_switches` của công ty đó (studio-skeleton:R4.3).
- R10.2 KHI lane `offboarding` xóa dữ liệu của một công ty đang `offboarding`, lane `offboarding` PHẢI xuất rồi xóa mọi
  dòng `studio.gate_runs` của công ty đó, sau `studio.artifact_versions` và `studio.gate_case_results` trỏ tới chúng
  và trước `studio.artifacts` mà chúng trỏ tới (studio-skeleton:R4.1, studio-skeleton:R4.2).
- R10.3 NẾU `dw_app` DELETE một dòng `studio.gate_runs` khi `platform.tenants.status` của công ty của dòng khác
  `offboarding`, THÌ PostgreSQL PHẢI từ chối với SQLSTATE 23514 và không xóa gì.

## Hành vi giữ nguyên

- G1 KHI CI chạy `scripts/run_evals.py`, `dw_evals` PHẢI TIẾP TỤC chạy `run_dataset` trên dataset nền
  tảng với `SECURITY_CATEGORIES` không đổi (test: `apps/api/tests/unit/test_eval_datasets.py`).

## Trong phạm vi

- Bảng, cột và trigger ở mục Dữ liệu; route ở mục API.
- Mã: cột vòng đời và `studio.guard_version_stage()` trên `studio.artifact_versions`, với luật theo loại
  cho loại không có Cổng chất lượng và nhánh chỉ siết của `dw.object/v1` (cột `tighten_only`,
  `compared_live_hash`); `VersionStage` StrEnum với bảng chuyển đổi thuần và `LifecycleService`; view Giai
  đoạn hiển thị; dịch vụ gửi kiểm định cho mọi loại đã đăng ký (route `{agents|workflows|objects|data-sources}`,
  khóa gửi do `ArtifactKindRegistry` khai, `If-Match` bắt buộc) với bảng điều phối `ClosureExtractor` và bảng kiểm
  theo loại lúc gửi kiểm định (Protocol của spec này, compliance-pdpl và workflow-nodes đăng ký kiểm của mình);
  Protocol `PublishBindingsCheck` do spec này khai, hỏi ở lệnh gửi và ở handler phát hành (R2.11, R5.10;
  tenant-config/05 đáp ứng); mở rộng `dw_evals`
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
- Audit: `studio.version.submitted`, `.returned_to_draft`, `.retired`, `.published`, `.candidate_read` (người duyệt
  đọc Bản ứng viên, R5.11), `control.freeze.set`, `control.freeze.lifted`, `control.kill.set`, `control.kill.lifted`,
  `studio.gate_run.started`, `.completed`, `approval.cancelled` (lane `control_switch`), `tool.denied`
  (`policy_decision` `deny_frozen`); trong `platform.provisioning_audit`: `platform.freeze.set`,
  `platform.freeze.lifted`, `platform.tenant_freeze.set`, `platform.tenant_freeze.lifted`.

## Ngoài phạm vi

| Việc                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | Vì sao                                                                                                                                                                                                                                                            | Chủ                                                                                   |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Phân tích năng lực Bộ ba nguy hiểm (tín hiệu A, B, C từ bao đóng, nút phê duyệt áp đảo C) lúc gửi kiểm định, 422 khi chưa đạt, kết quả ở `studio.version_assessments`                                                                                                                                                                                                                                                                                                                                                                                                                      | ADR-0125 (Accepted); R2.7 gọi nó qua bảng kiểm theo loại, R6 chỉ đọc kết quả đã ghi                                                                                                                                                                               | compliance-pdpl                                                                       |
| W2: bộ đề kiểm định của tenant (bảng, API, màn nhập câu không code, `studio.gate_run_datasets`), cùng `min_cases_total`, `pass_rate_min` của Chính sách cổng                                                                                                                                                                                                                                                                                                                                                                                                                               | YC74; cần gói và điều hướng của studio-skeleton; trường chính sách vào cùng bên đọc của nó (DO-29.1)                                                                                                                                                              | agent-lifecycle, đợt sau (W2)                                                         |
| W2: Mức rủi ro AI trên `studio.version_assessments` (công ty tự phân hạng từ mặc định, không khai thấp hơn ở v1), tờ giải thích                                                                                                                                                                                                                                                                                                                                                                                                                                                            | YC93; DO-60; bảng có từ W1 cho kết quả Phân tích năng lực (compliance-pdpl:R4.6)                                                                                                                                                                                  | compliance-pdpl; agent-lifecycle đọc (W2)                                             |
| W2: tổng quan đội ngũ, "đã kiểm định thật N/M", chip cảnh báo, cảnh báo nháp để lâu (`stale_draft_days`), trang phiên bản, so sánh từng trường trên trang đó cho người dựng                                                                                                                                                                                                                                                                                                                                                                                                                | YC75; mẫu học từ phân tích đối thủ (config-chang.md mẫu 3); đọc theo quyền người xem, cổng chặn ở server; `stale_draft_days` vào chính sách cùng bên đọc (DO-29.1); người duyệt đọc Bản ứng viên và phần khác với bản Đang dùng từ W1 qua route của R5.11 (V4.23) | agent-lifecycle, đợt sau (W2)                                                         |
| W2: phát hiện Lệch cấu hình, giám khảo LLM hiệu chuẩn, kiểm định retrieval, so với bản đang chạy                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | mẫu cảnh báo lệch học từ phân tích đối thủ (config-chang.md mẫu 3); cần `mcp-client`, `model-connections`                                                                                                                                                         | agent-lifecycle, đợt sau (W2)                                                         |
| W2: kiểm định trực tuyến lấy mẫu (tắt mặc định, model chấm cùng Lộ trình dữ liệu), phân tích năng lực theo đường đi, gói hồ sơ AI theo Luật AI                                                                                                                                                                                                                                                                                                                                                                                                                                             | YC93; chờ `usage-and-limits`, `workflow-nodes` và luật sư (DO-60)                                                                                                                                                                                                 | agent-lifecycle; compliance-pdpl, đợt sau (W2)                                        |
| W2: kiểm định lại khi ghi đè của tenant đổi Mã băm hiệu lực, phần nền tảng trả có trần cho lượt do nền tảng kích                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | bằng chứng khóa theo Mã băm hiệu lực nên bằng chứng cũ tự hết giá trị (ADR-0109 (Accepted)); DO-29.2                                                                                                                                                              | agent-lifecycle; usage-and-limits, đợt sau (W2)                                       |
| W2: `scope_type` `tool` trên công tắc để ngưng công cụ MCP (`suspended`), gỡ bằng `studio.lifecycle.revive` nối với lần duyệt định nghĩa mới                                                                                                                                                                                                                                                                                                                                                                                                                                               | công cụ MCP đi qua máy giai đoạn (D:mcp-client:R3.4, quyết 23/10/2026); mcp-client là W2                                                                                                                                                                          | agent-lifecycle; mcp-client, đợt sau (W2)                                             |
| W2: loại `tool` qua lệnh gửi, máy giai đoạn và handler phát hành của spec này: không có Cổng chất lượng (R1.6), không nhánh chỉ siết, phê duyệt `studio.publish.tool` có tem `studio.publish.approve`, trừ công cụ MCP mở ngoại lệ có tên `studio.mcp.tool_approval` có tem `studio.mcp.approve` (mcp-client:R3.1); handler của R5.5, R5.9 nhận cả `studio.publish.tool.decided` lẫn `studio.mcp.tool_approval.decided` (mcp-client:R3.4); route gửi thêm đoạn của loại, và khóa gửi của loại `tool` do ticket W2 đăng ký loại khai trong mục `ArtifactKindRegistry` (tenant-config:R2.15) | công cụ do công ty viết đi qua vòng đời từ W2 (V4.3; ADR-0116 (Accepted) quyết 9; ADR-0120 (Accepted) quyết 2); W1 không có công cụ do công ty viết (tools-and-skills, Ngoài phạm vi)                                                                             | agent-lifecycle; tools-and-skills; mcp-client, đợt sau (W2)                           |
| W2: lý do dừng `workspace_archived` của `RunControlPort` (ADR-0120 (Accepted) quyết 6)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | lưu trữ workspace đến ở W2 cùng org-and-principals; W1 dừng lượt chạy của công ty bị khóa hay đang offboarding (R9.2)                                                                                                                                             | agent-lifecycle; org-and-principals, đợt sau (W2)                                     |
| W2: phát hành từ chối `owner_missing` khi người chịu trách nhiệm rời công ty, với 409 ở lệnh có người gọi và, ở handler `studio.publish.<kind>.decided`, phiên bản về Nháp với mã đó và audit `studio.version.returned_to_draft` như R5.10 (V4.18; YC10; ADR-0103 (Accepted) quyết 3)                                                                                                                                                                                                                                                                                                      | ADR-0120 (Accepted) quyết 2 đòi người chịu trách nhiệm khi phát hành; người chịu trách nhiệm bắt buộc, guard và lane `principal_ownership` đến ở W2 (DO-39.2)                                                                                                     | agent-lifecycle; org-and-principals (guard, lane `principal_ownership`), đợt sau (W2) |
| W2: lane gửi tin đã xếp hàng thật thi hành hợp đồng R8.4                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | tin chỉ được hoãn và xếp hàng từ W2; W1 thử R8.4 với lane giả (ADR-0120 (Accepted) quyết 6)                                                                                                                                                                       | connections-and-vault, đợt sau (W2)                                                   |
| W3: Đóng băng có thể tiếp tục cho lượt đang chạy (`RunStatus.FROZEN`, lane tiếp tục sau khi gỡ)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | W1 hủy lượt đang chạy ở cửa kế tiếp và chỉ giữ lượt do trình kích hoạt đã xếp hàng (DO-28 C); v1.5 trở đi (ADR-0120 (Accepted), mục Open, DO-28); cần nguyên mẫu của ticket 01                                                                                    | agent-lifecycle, đợt sau (W3)                                                         |
| W3: công tắc theo workspace, kết nối, tuyến model; nhà vận hành tắt một agent; mô phỏng nhiều lượt                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | v1.5 trở đi                                                                                                                                                                                                                                                       | agent-lifecycle, đợt sau (W3)                                                         |
| Vỏ phiên bản, băm RFC 8785 (`dw_kernel.canonical`), bản kê định nghĩa và Nơi đang dùng                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | ADR-0109 (Accepted); đã có                                                                                                                                                                                                                                        | tenant-config                                                                         |
| Bảng phiên bản agent và quy trình, trình soạn, canvas; chế độ chạy, hàng đợi, lịch, Data Hub                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | spec này chỉ đặt hợp đồng cột vòng đời và hợp đồng cửa                                                                                                                                                                                                            | agent-builder, workflow-engine, workflow-triggers                                     |
| Sổ sử dụng, lease, hạn mức theo phạm vi                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | spec này xin lease `purpose` `eval_offline` qua `LimitsPort` cho Lượt kiểm định (DO-21.4)                                                                                                                                                                         | usage-and-limits                                                                      |
| Danh mục quyền, vai trò, độ sâu workspace; phân loại công cụ, ghim định nghĩa MCP                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | spec này chỉ đăng ký khóa của mình vào danh mục (quy ước của tenant-rbac/01) và đọc phân loại, sự kiện                                                                                                                                                            | tenant-rbac; tools-and-skills; mcp-client                                             |

## Dữ liệu

Mọi bảng mới: RLS ENABLE và FORCE theo tenant, grant cùng migration, tên ràng buộc theo
`NAMING_CONVENTION`, revision id hex ngẫu nhiên.

- Cột vòng đời thêm trên `studio.artifact_versions` (vỏ chung của tenant-config, ADR-0109 (Accepted)
  quyết 2; DO-05 chọn vỏ chung): `gate_run_id uuid` NULL, FK ghép `(tenant_id, gate_run_id)` tới
  `studio.gate_runs (tenant_id, id)` ON DELETE RESTRICT có index riêng, bắt buộc khi
  `stage IN ('awaiting_approval','live','retired')` với loại có Cổng chất lượng, luôn NULL
  với loại mà `studio.artifact_kinds` ghi `has_quality_gate = false` (R1.6); `publish_approval_id uuid` NULL, FK ghép
  `(tenant_id, publish_approval_id)` tới `platform.approval_requests (tenant_id, id)` ON DELETE RESTRICT có index
  riêng, bắt buộc khi `stage IN ('awaiting_approval','live','retired')` trừ phiên bản lên Đang dùng theo nhánh chỉ
  siết (R1.7); hai FK ghép vì kiểm khóa ngoại không đi qua RLS, nên FK một cột để một công ty trỏ tới dòng của công ty
  khác (R1.9), và đích của chúng là `uq_gate_runs_tenant_id_id` của `studio.gate_runs` (ticket 04) và
  `uq_approval_requests_tenant_id_id UNIQUE (tenant_id, id)` mà revision tạo FK thêm trên `platform.approval_requests`
  (ticket 03), vì UNIQUE đã có của bảng đó, `uq_approval_requests_tenant_id_workspace_id_id`, mang `workspace_id` mà
  vỏ phiên bản toàn tenant không có; `tighten_only boolean NOT NULL DEFAULT false`, do
  `LifecycleService` ghi lúc gửi theo bộ so sánh của loại, và `compared_live_hash text` NULL (`definition_hash` của
  phiên bản Đang dùng lúc gửi, NULL khi chưa có), do `LifecycleService` ghi ở mọi lần gửi (R2.10), CHECK
  `NOT tighten_only OR compared_live_hash IS NOT NULL`;
  `contributor_ids uuid[] NOT NULL CHECK (cardinality(contributor_ids) >= 1)`; `submitted_by`,
  `submitted_at`, `published_by`, `published_at`, `retired_by`, `retired_at`; `retire_reason_code`
  CHECK (`superseded`, `explicit`); `stage_changed_at timestamptz NOT NULL`. Trigger
  `studio.guard_version_stage()` (BEFORE INSERT OR UPDATE) cho đúng các chuyển tiếp của R1, cho mọi chuyển sang
  `live` chỉ khi `compared_live_hash` vẫn là mã băm của phiên bản Đang dùng mà lần phát hành thay (bản vừa gỡ
  `superseded` trong cùng giao dịch, vì chỉ mục một Đang dùng buộc gỡ bản cũ trước), với vế cùng NULL khi không có
  bản nào chỉ ở `awaiting_approval → live` (R1.8), còn nhánh chỉ siết `draft → live` luôn có mã băm, vì nó cần một
  bản Đang dùng để so (R2.8) và CHECK trên buộc `compared_live_hash` khác NULL khi `tighten_only` (R1.7), và chặn
  đổi nội dung ngoài `draft`; chỉ mục một Đang dùng (`WHERE stage='live'`) và
  `(tenant_id, stage, stage_changed_at DESC, id DESC)`. Một phiên bản chưa phát hành mỗi thành phần
  (`WHERE stage IN ('draft','evaluating','awaiting_approval')`) là chỉ mục duy nhất từng phần của tenant-config
  (tenant-config:R2.20), nên spec này không tạo chỉ mục một Bản ứng viên riêng, bản sao thứ hai của cùng luật (R1.2;
  failure-modes #2). View
  `studio.artifact_display_stage` tính Giai đoạn hiển thị, không lưu.
- `platform.control_switches`: `tenant_id`, `id`; `scope_type` CHECK (`tenant`, `agent`, `workflow`);
  `workspace_id`, `target_id` NULL chỉ khi `scope_type='tenant'`; `action` CHECK (`freeze`, `kill`);
  `origin` CHECK (`tenant`, `platform`); `reason_code` CHECK (`incident`, `maintenance`, `abuse`,
  `test`, `other`); `reason` 1..500 ký tự; `set_by`, `set_at`; `lift_approval_id`, `lifted_by`,
  `lifted_at`, `lift_reason`; chỉ mục một công tắc mở
  `(tenant_id, scope_type, coalesce(target_id, '…nil…'::uuid)) WHERE lifted_at IS NULL`; FK
  `tenant_id → platform.tenants ON DELETE CASCADE` có index `(tenant_id)` riêng, vì chỉ mục một công tắc mở là từng
  phần và không phủ dòng đã gỡ (CLAUDE.md, Data model rules); trigger `platform.guard_control_switch()` (chèn chỉ
  mở; gỡ một lần; dòng `origin='platform'` chỉ `dw_provisioner` gỡ) và trigger
  `pg_notify('dw_control_switch', ...)` chỉ id; `dw_app` SELECT, INSERT, UPDATE
  (`lifted_by, lifted_at, lift_reason, lift_approval_id`) và DELETE chỉ cho lượt xóa của offboarding: trigger
  `platform.guard_control_switch()` từ chối mọi DELETE khi `platform.tenants.status` của công ty khác
  `offboarding` (R7.5, R10.1). Mỗi lần đặt hay gỡ một công tắc `kill` ghi outbox `control.switch.changed` v1
  chỉ id trong cùng giao dịch; lane `control_switch` nghe sự kiện đó.
- `platform.platform_freezes` (mặt danh tính, không tenant): tối đa một dòng mở; `dw_app` chỉ SELECT;
  do `dw_provisioner` ghi, audit trong `platform.provisioning_audit`.
- `studio.gate_runs`: `status` CHECK (`queued`, `running`, `passed`, `failed`, `error`, `cancelled`);
  `purpose` CHECK (`gate`, `dry`); `artifact_id uuid NOT NULL`, thành phần được kiểm định, kể cả thành phần của bản
  Nháp ở dòng `dry` (R4.8), FK ghép `(tenant_id, artifact_id)` tới `studio.artifacts (tenant_id, id)`
  (`uq_artifacts_tenant_id_id` của tenant-config/02) ON DELETE RESTRICT, có index `(tenant_id, artifact_id)`, để ba
  route đọc lọc theo độ sâu ở `owning_workspace_id` của thành phần (R4.10); khóa bằng chứng (`effective_hash`,
  `gate_policy_ref`, `security_suite_ref`, danh sách mã băm bộ đề của tenant, rỗng ở W1); `definition_hash` cho
  trigger giai đoạn; `spend_cap_usd`, `spent_usd`, `resolved_at_gate` jsonb,
  `verdict` jsonb; `created_at timestamptz NOT NULL`; `uq_gate_runs_tenant_id_id UNIQUE (tenant_id, id)`, đích của
  FK ghép từ `studio.artifact_versions` và `studio.gate_case_results`; index `(tenant_id, created_at DESC, id DESC)`
  mang thứ tự keyset của `GET /api/v1/studio/gate-runs` (CLAUDE.md, Data model rules). `dw_app` có DELETE trên
  `studio.gate_runs` chỉ dùng được ở lượt xóa của offboarding: trigger `studio.guard_gate_run_delete()` BEFORE DELETE
  từ chối với SQLSTATE 23514 mọi DELETE khi `platform.tenants.status` của công ty khác `offboarding` (R10.3), cùng
  hình với `platform.guard_control_switch()`. Thứ tự xóa duy nhất của `offboarding.py` liệt kê mỗi bảng sau mọi bảng
  giữ một khóa ngoại RESTRICT tới nó (studio-skeleton:R4.2; ADR-0109 (Accepted) Consequences), với nhóm định nghĩa là:
  các bảng trỏ tới phiên bản (như `platform.worker_runs`, `studio.trigger_subscriptions`, `platform.run_manifest_keys`
  và `studio.dependencies`, mà `to_version_id` là khóa RESTRICT tới phiên bản), `studio.artifact_versions`,
  `studio.gate_case_results`, `studio.gate_runs`, rồi `studio.artifacts`; `studio.gate_runs` đứng sau
  `studio.artifact_versions` và `studio.gate_case_results` vì khóa ngoại `gate_run_id` (RESTRICT) của hai bảng đó, và
  trước `studio.artifacts` vì khóa ngoại `artifact_id` (RESTRICT) của chính nó (R10.2). `studio.gate_run_datasets` là
  W2 cùng bộ đề của tenant. `studio.gate_case_results`: `gate_run_id` FK ghép `(tenant_id, gate_run_id)` tới
  `studio.gate_runs (tenant_id, id)` ON DELETE RESTRICT, để một DELETE lên Lượt kiểm định không kéo theo xóa dòng
  chỉ thêm; index `(tenant_id, gate_run_id, case_id)` trên bảng cha mang khóa ngoại đó và thứ tự keyset của
  `GET /api/v1/studio/gate-runs/{id}/cases`;
  phân vùng theo tháng với DEFAULT, đăng ký bằng một dòng `platform.time_partitioned_tables`
  (`append_only = true`, studio-skeleton:R3.1); ENABLE/FORCE RLS và policy tenant trên cha và DEFAULT cùng
  migration; `dw_app` không giữ quyền nào trên partition nào, kể cả DEFAULT, chỉ SELECT, INSERT trên bảng cha;
  thời hạn 395 ngày (13 tháng, số tạm UNVERIFIED) dưới khóa `studio.gate_case_results` của tệp chính sách
  retention, thêm trong cùng thay đổi đăng ký (telemetry-and-audit:R5.6, studio-skeleton:R3.7), xóa bằng DROP
  PARTITION qua `platform.drop_expired_partitions` của usage-and-limits/02; khi offboarding, dòng của công ty
  xóa qua `platform.purge_tenant_append_only` (usage-and-limits:R3.10), bước chạy trước mọi bảng thường trong cùng thứ
  tự duy nhất (usage-and-limits:R3.11), nên bảng đứng trước `studio.gate_runs` và khóa ngoại `RESTRICT` tới nó được
  thỏa, và bảng có một dòng `STUDIO_EXCLUSIONS` nêu cách xóa đó (studio-skeleton:R4.1).
- `studio.gate_runs` và `studio.gate_case_results` là bảng toàn tenant như vỏ phiên bản (RLS chỉ theo công ty, không
  cột `workspace_id`), mỗi bảng một dòng lý do trong danh sách bảng toàn tenant của `test_rls_coverage.py`
  (CLAUDE.md, Tenancy and authorization; studio-skeleton:R9.1): Lượt kiểm định đi theo thành phần toàn tenant mà nó
  kiểm định, kết quả từng câu là con của Lượt kiểm định, và quyền đọc cả hai theo `owning_workspace_id` của thành
  phần ở `artifact_id` (R4.10).

## API

- `POST /api/v1/studio/{agents|workflows|objects|data-sources}/{artifact_id}/versions/{version_id}/submit` và
  `POST .../withdraw` (khóa gửi mà `ArtifactKindRegistry` khai cho loại, tenant-config:R2.15:
  `studio.versions.submit` cho agent và quy trình, `studio.objects.manage` cho đối tượng, `studio.datahub.manage`
  cho Nguồn dữ liệu, workflow-triggers:R4.7; `Idempotency-Key`); lệnh gửi nhận `If-Match` là ETag của bản Nháp:
  lệch → 412 `precondition_failed` với `stale_version` (R2.12), thiếu → 428 `precondition_required` (R2.13); với
  đối tượng, lệnh gửi đưa phiên bản sang Chờ duyệt hay, theo nhánh chỉ siết, Đang dùng (R2.8); với Nguồn dữ liệu,
  luôn sang Chờ duyệt.
  `POST /api/v1/studio/{agents|workflows}/{artifact_id}/versions/{version_id}/retire` (`studio.versions.retire`,
  `Idempotency-Key`).
- `POST /api/v1/studio/{agents|workflows}/{artifact_id}/versions/{version_id}/dry-evaluations` (`studio.evals.run`;
  Kiểm định thử của phiên bản `draft`, R4.8, R4.9; mỗi lần thử xin qua `RunRequestService` dưới danh nghĩa người xin,
  đọc dưới giới hạn tạm của bản Nháp giao với quyền của người đó, R4.11); `GET /api/v1/studio/gate-runs` (keyset theo
  `(created_at DESC, id DESC)`), `/{id}`, `/{id}/cases` (keyset theo `case_id`) (`studio.lifecycle.read`); mỗi thứ
  tự có index ở mục Dữ liệu; ba route chỉ trả Lượt kiểm định, kể cả dòng `dry`, của thành phần mà
  `studio.lifecycle.read` của người đọc chạm tới `owning_workspace_id` ở độ sâu của nó, đọc từ
  `platform.effective_grants` (ADR-0104 (Accepted) quyết 3, quyết 5), còn ngoài độ sâu hay công ty khác → 404 (R4.10).
- `POST /api/v1/admin/freeze` (`studio.lifecycle.freeze`; `Idempotency-Key`; body `reason_code`,
  `reason`; một người cộng audit), `POST /api/v1/admin/unfreeze` (`studio.lifecycle.freeze`; mở yêu cầu
  phê duyệt `studio.lifecycle.unfreeze`, gỡ khi người thứ hai duyệt); `GET /api/v1/control-state` (mọi
  thành viên; chỉ mã, không lý do chữ); nhà vận hành `POST /api/v1/platform/freeze`, `POST /api/v1/platform/unfreeze`,
  `POST /api/v1/platform/tenants/{tenant_id}/freeze`, `POST /api/v1/platform/tenants/{tenant_id}/unfreeze`
  (ngữ cảnh provisioning).
- `POST /api/v1/studio/{agents|workflows}/{artifact_id}/kill` (`studio.lifecycle.kill`, lý do);
  `POST /api/v1/studio/{agents|workflows}/{artifact_id}/revive-requests` (mở `studio.lifecycle.revive`).
- Phát hành đi qua inbox `/approvals` hiện có (nhãn loại và liên kết "Xem diff" ở điểm cắm
  `apps/web/components/tool-approval.tsx`, mở route dưới đây).
- `GET /api/v1/studio/publish-approvals/{approval_id}/candidate` (người được quyết định yêu cầu `studio.publish.<kind>`
  còn `pending`, tức giữ `approvals.decide` và tem `studio.publish.approve`, ADR-0004 (Accepted) sửa đổi 07/10/2026;
  đọc, không `Idempotency-Key`): `version_id`, `version_no`, Mã băm định nghĩa và nội dung niêm phong của Bản ứng viên,
  `live_version_id` của phiên bản Đang dùng mà nó sẽ thay (NULL khi chưa có), và `changes[]` là phần khác giữa hai tài
  liệu chuẩn hóa RFC 8785 theo con trỏ JSON (`path`, `before`, `after`; mọi trường là thêm khi chưa có bản Đang dùng),
  kèm audit `studio.version.candidate_read` (R5.11); người không được quyết định yêu cầu, yêu cầu đã quyết, loại khác
  `studio.publish.*` hay công ty khác → 404 như không tồn tại, không audit (R5.12). Ngoài lúc yêu cầu còn chờ, đọc định
  nghĩa vẫn cần khóa đọc của loại trên route của tenant-config (tenant-config:R2.11).
- Lỗi theo vỏ problem+json của ADR-0108 (Accepted); `details.reason_code`: `candidate_exists`,
  `second_person_required` (409 khi người xin tự quyết phê duyệt phát hành, gỡ Đóng băng hay bật lại: R5.2, R7.11,
  R8.7), `author_cannot_approve` (409, người đóng góp không phải người xin, R5.2), `stale_version` (412 ở lệnh gửi,
  R2.12), `tenant_frozen`, `platform_frozen`, `artifact_killed`,
  `control_state_unavailable`, `principal_inactive`, `tenant_locked`, `tenant_offboarding`, `cost_bound`,
  `limit_exceeded`, `artifact_in_use`, `binding_unset` (409 ở lệnh gửi, R2.11), `base_changed`; handler phát hành không
  áp được một phê duyệt đã duyệt thì đưa phiên bản về Nháp với `base_changed`, `binding_unset`, `tenant_frozen` hay
  `platform_frozen`, không mã HTTP (R5.9, R5.10, R7.12); route gửi kiểm định trả thêm mã 422 của kiểm theo loại do spec
  chủ kiểm quyết (`capability_trifecta_autonomy`, `tool_unclassified`, `trifecta_path_unapproved`, `residency_refused`
  của compliance-pdpl; mã của kiểm người duyệt của workflow-nodes:R9.5).

## Kiểm soát

| #    | Kiểm soát                                                                                | Yêu cầu                                    | Test âm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ---- | ---------------------------------------------------------------------------------------- | ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AL1  | Máy trạng thái thuộc database                                                            | R1.1                                       | `dw_app` UPDATE `draft → live` trực tiếp → 23514 `ck_artifact_versions_stage_transition`; gỡ trigger → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| AL2  | Một Đang dùng; hai lần gửi song song bản Nháp duy nhất thành một lần gửi                 | R1.2, R1.3                                 | Hai lần gửi kiểm định song song bản Nháp duy nhất của một thành phần → một 202, một 409 `candidate_exists`, đúng một audit `studio.version.submitted`, không yêu cầu phê duyệt hay Lượt kiểm định thứ hai; gỡ kiểm giai đoạn `draft` của lệnh gửi → lần thứ hai không nhận 409, test đỏ; INSERT bản `live` thứ hai → lỗi chỉ mục; gỡ chỉ mục một Đang dùng → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| AL3  | Bao đóng và Nơi đang dùng ghi cùng giao dịch, khóa theo Mã băm định nghĩa                | R2.1, R2.2, R2.3                           | Rollback giữa giao dịch gửi kiểm định → không bản kê, phụ thuộc hay audit; đổi phiên bản một công cụ ghim → Mã băm định nghĩa khác; bỏ một loại khỏi bao đóng → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| AL4  | Đang dùng cần cổng đạt và approval đã duyệt; chỉ phiên bản chỉ siết đi thẳng             | R1.7, R2.8, R5.6                           | Chuyển `live` với `gate_run_id` của mã băm khác, hoặc approval còn `pending` → 23514; `draft → live` với `tighten_only` false, với `compared_live_hash` cũ sau khi phiên bản Đang dùng đổi, hay với loại `agent` hoặc một loại không cổng khác `object` (như `endpoint`) → 23514; phiên bản đối tượng vừa đóng một trường vừa thêm một trường → Chờ duyệt kèm phê duyệt; gỡ CHECK hay luật nhánh → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| AL5  | Người duyệt không phải Tác giả, không phải người gửi                                     | R5.1, R5.2, R5.3                           | Người trong `contributor_ids` không phải người xin, có scope duyệt → 409 `author_cannot_approve`; người gửi tự duyệt → 409 `second_person_required` vì kiểm tiền tố nghiêm chạy trước guard; payload thiếu `author_ids` → từ chối; `author_ids` dựng thiếu một người trong `contributor_ids` hay `submitted_by` → test khớp đỏ; yêu cầu `studio.publish.object` mở lúc gửi cũng mang `author_ids`; gỡ guard → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| AL6  | Không vai nào thay tem `studio.publish.approve`; người xin chỉ đọc                       | R5.4, R5.8                                 | `platform_admin` không giữ tem và không phải người xin → 404 khi đọc và khi quyết định; người gửi không giữ tem đọc yêu cầu của mình với `can_decide` false; gỡ luật người xin → người gửi nhận 404, test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| AL7  | Bộ kiểm định an ninh nền tảng 100%, `unknown` chặn như trượt, không sửa được             | R4.1, R4.2                                 | Một Câu an ninh trượt hoặc `unknown` → cổng trượt; không route nào ghi Câu an ninh (không phải dữ liệu tenant); gỡ luật trong `evaluate_gate` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| AL8  | Kiểm định không gây tác động thật, không phê duyệt thật                                  | R4.3, R4.7                                 | Lượt kiểm định agent có công cụ gửi Zalo → egress giả không nhận lời gọi nào, không yêu cầu phê duyệt nào mở; lần thử của quy trình có Bước `human.approval` mà Câu kiểm định khai `rejected` (từ vựng `approved`, `rejected` của workflow-nodes:R9.9) → nhánh từ chối chạy, 0 dòng `platform.approval_requests`, audit `studio.step.approval.simulated` mang `rejected`; gỡ chặn `simulate` ở executor hay đặt phê duyệt trước chế độ chạy → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| AL9  | Trần chi phí trước lời gọi đầu, trần riêng mỗi lần thử                                   | R4.4, R4.5                                 | Chi phí xấu nhất vượt trần lượt, hoặc `LimitsPort` từ chối lease `eval_offline` → Lượt kiểm định `error` `limit_exceeded`, không `worker_runs` nào; một lần thử chạm trần → Câu trượt `cost_bound`, các câu khác vẫn chấm; gỡ trần lần thử → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| AL10 | Phiên bản chưa qua kiểm theo loại hay Phân tích năng lực không lên Chờ duyệt             | R2.7, R6.1, R6.2, R6.3                     | Đăng ký một kiểm từ chối cho loại `workflow` → gửi kiểm định 422, phiên bản vẫn Nháp; `dw_app` ghi thẳng một Bản ứng viên không có kết quả Phân tích năng lực sang Đang kiểm định → cổng trượt, không yêu cầu phê duyệt nào; gỡ đọc kết quả ở lane → yêu cầu phê duyệt mở (đỏ)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| AL11 | Đóng băng chặn ở mọi cửa, đóng khi lỗi                                                   | R7.1, R7.3, R7.7, R7.8, R7.9, R7.12, R7.13 | Đặt đóng băng giữa run: mỗi cửa trong 6 cửa của R7.1 từ chối lời gọi kế tiếp, run `cancelled`; lượt `chat` tới cửa nhận → `cancelled` `tenant_frozen`, 0 lời gọi model; lượt `datahub` đã xếp hàng vẫn `queued` và chạy sau khi gỡ; gửi kiểm định → 409; phiên bản đối tượng chỉ siết gửi khi Đóng băng của công ty → Đang dùng, cùng phiên bản khi Đóng băng của nền tảng → 409 `platform_frozen`, phiên bản đối tượng không chỉ siết khi Đóng băng của công ty → 409 `tenant_frozen`; handler phát hành nhận quyết định duyệt khi Đóng băng của công ty → phiên bản về `draft` với `tenant_frozen` và audit `studio.version.returned_to_draft`, không lên Đang dùng và không còn ở `awaiting_approval`, khi Đóng băng của nền tảng → như trên với `platform_frozen`; cache quá 30 giây không làm mới → lời gọi công cụ `control_state_unavailable`; gỡ kiểm ở một cửa hay gỡ ngoại lệ chỉ siết → test của chỗ đó đỏ |
| AL12 | Tenant không gỡ Đóng băng của nhà vận hành; không xóa công tắc để gỡ                     | R7.4, R7.5                                 | `POST /api/v1/admin/unfreeze` khi `origin='platform'` → 403; `dw_app` UPDATE gỡ trực tiếp → 23514; `dw_app` DELETE một công tắc `kill` của công ty `active` → 23514, công tắc còn; gỡ phép kiểm DELETE khỏi trigger → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| AL13 | Tắt khẩn cấp hủy việc đang chờ                                                           | R8.2, R8.3                                 | Run `waiting_approval` của thành phần → `cancelled`, approval `cancelled`; quyết định đến sau → 409, không resume; gỡ lane → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| AL14 | Bật lại cần người thứ hai                                                                | R8.6, R8.7                                 | Người xin bật lại tự duyệt `studio.lifecycle.revive` → 409 `second_person_required`, công tắc không gỡ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| AL15 | Tắt khẩn cấp chặn gửi đã xếp hàng và agent liên kết                                      | R8.4, R8.5                                 | Tắt sau khi tin Zalo xếp hàng → lane gửi giả không gọi nhà cung cấp (lane thật là W2 của connections-and-vault; đường gửi W1 qua cửa công cụ: marketing-pilot:R6.4); agent liên kết bị tắt → stack con từ chối                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| AL16 | Cách ly tenant của công tắc                                                              | R7.1, R8.1                                 | Đóng băng, tắt của tenant A không chạm run của tenant B; đọc công tắc của B từ A → 404; gỡ FORCE RLS → `test_rls_coverage.py` đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| AL17 | Chủ thể hay công ty không active không chạy tiếp                                         | R9.1, R9.2                                 | Gỡ thành viên khỏi công ty rồi tiếp tục lượt chạy chờ duyệt của người đó → `cancelled` `principal_inactive`, 0 lời gọi model; đặt `suspended` bằng SQL rồi nhận lượt mới → như trên; tài khoản dịch vụ `suspended` rồi lượt `datahub` của nó tới cửa nhận (làn giả) → giữ `queued` với `principal_inactive`, 0 lời gọi model, kích hoạt lại tài khoản → chạy theo thứ tự đến; khóa công ty rồi nhận lượt mới → `cancelled` `tenant_locked`; công ty `offboarding` → `tenant_offboarding`; gỡ kiểm ở `require_open` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                          |
| AL18 | Gỡ Đóng băng của công ty cần người thứ hai                                               | R7.10, R7.11                               | Người xin gỡ tự duyệt `studio.lifecycle.unfreeze` → 409 `second_person_required`, Đóng băng còn; người khác duyệt → gỡ; gỡ luật nghiêm của `studio.lifecycle.` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| AL19 | Phát hành chỉ thay đúng phiên bản Đang dùng đã so lúc gửi                                | R1.8, R2.10, R5.9                          | Gỡ (`explicit`) phiên bản Đang dùng của một agent trong lúc một Bản ứng viên của cùng thành phần chờ duyệt, rồi duyệt Bản ứng viên → nó về `draft` với `base_changed` và audit đứng tên người quyết định, không phiên bản nào lên `live`; `dw_app` UPDATE `awaiting_approval → live` với `compared_live_hash` cũ → 23514; gỡ luật khỏi trigger hay kiểm khỏi handler → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| AL20 | Phát hành cần mọi Điểm gắn bắt buộc đã có giá trị duyệt                                  | R2.11, R5.10                               | Phiên bản quy trình khai Điểm gắn `principal` bắt buộc chưa có giá trị đã duyệt → gửi kiểm định 409 `binding_unset` nêu `principal`, phiên bản vẫn Nháp; handler nhận quyết định duyệt khi `PublishBindingsCheck` trả `binding_unset` → phiên bản về `draft` với `binding_unset` và audit `studio.version.returned_to_draft`, không lên Đang dùng và không còn ở `awaiting_approval`; gỡ kiểm ở lệnh gửi hay ở handler → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| AL21 | Khóa ngoại của vòng đời không trỏ sang công ty khác                                      | R1.9                                       | Bằng vai migrator, dòng phiên bản của tenant A trỏ `publish_approval_id` tới yêu cầu phê duyệt của tenant B, hay `gate_run_id` tới Lượt kiểm định của B, dòng `studio.gate_case_results` của A trỏ tới Lượt kiểm định của B, và dòng `studio.gate_runs` của A trỏ `artifact_id` tới thành phần của B → FK từ chối, không ghi; đổi một FK sang một cột → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| AL22 | Kiểm định thử chạy đúng nội dung nháp và không dẫn tới phát hành                         | R4.8, R4.9                                 | Kiểm định thử một bản Nháp → mỗi lần thử là lượt `simulate` ghim giai đoạn `draft` và mã băm tạm, phiên bản vẫn `draft`, không `gate_run_id`, 0 dòng `platform.approval_requests`; sửa nháp rồi Kiểm định thử lại → lần thử ghim mã băm tạm mới và chạy nội dung mới; nội dung nháp trượt bộ kiểm của loại → Kiểm định thử `error` kèm các lỗi, 0 `worker_runs`; bỏ mã băm ghim khỏi khóa cache graph → lần sau chạy nội dung cũ, test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| AL23 | Lượt kiểm định chỉ đọc được theo độ sâu ở workspace sở hữu của thành phần                | R4.10                                      | Người giữ `studio.lifecycle.read` ở độ sâu `workspace` của ws1 gọi `GET /api/v1/studio/gate-runs` → không Lượt kiểm định nào, kể cả dòng `dry`, của thành phần có `owning_workspace_id` là ws2; `GET .../gate-runs/{id}` và `/{id}/cases` của Lượt kiểm định đó → 404; người của tenant B dùng id của tenant A → 404; bỏ lọc theo `owning_workspace_id` của thành phần → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| AL24 | Chỉ lượt xóa của offboarding xóa được Lượt kiểm định                                     | R10.3                                      | `dw_app` DELETE một Lượt kiểm định của công ty `active` → 23514, dòng còn; cùng lệnh khi công ty `offboarding`, trên Lượt kiểm định không còn dòng nào trỏ tới → xóa được; gỡ kiểm khỏi trigger `studio.guard_gate_run_delete()` → test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| AL25 | Người duyệt đọc Bản ứng viên chỉ khi yêu cầu còn chờ và mình được quyết định nó          | R5.11, R5.12                               | Người giữ `approvals.decide` và tem `studio.publish.approve`, không giữ khóa tác giả của loại, gọi `GET .../publish-approvals/{approval_id}/candidate` khi yêu cầu `pending` → 200 với nội dung niêm phong và `changes[]` so với bản Đang dùng, đúng một audit `studio.version.candidate_read`; người xin không giữ tem, người chỉ giữ khóa tác giả và `platform_admin` không giữ tem → 404, không audit; cùng người giữ tem sau khi yêu cầu đã duyệt hay bị từ chối → 404; id của một yêu cầu `studio.lifecycle.unfreeze` còn `pending`, gọi bởi người được quyết định nó (`approvals.decide` cùng tem `studio.lifecycle.freeze`) → 404; người của tenant B dùng id của tenant A → 404; gỡ kiểm `pending` hay kiểm tem khỏi route → test đỏ                                                                                                                                                                          |
| AL26 | Lần thử của Kiểm định thử đọc trong giới hạn tạm của bản Nháp, dưới danh nghĩa người xin | R4.11                                      | Kiểm định thử một bản Nháp quy trình có Bước `data.object.*` đọc đối tượng X, người xin đọc được bản ghi x1 mà không đọc được x2 của X → lần thử thấy x1, không thấy x2, và đọc đối tượng Y ngoài bao đóng → 0 bản ghi; lane xin lần thử dưới danh nghĩa lane hay người gửi khác người xin → test khớp đỏ; bỏ giới hạn tạm khỏi lần thử → x1 cũng không thấy (record-access:R6.5), test đỏ                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |

## Tiêu chí xong

- Mọi tiêu chí R và G có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (ghi ở Comments của
  ticket).
- `make ci && make test-integration` xanh; `reviewing-feature-security` và `reviewing-deployment-security`
  đã chạy trên từng ticket có route, migration hay lane; `.claude/plans/studio.md` ghi lát W1 đã xong.

## Phụ thuộc

- tenant-config: vỏ `studio.artifact_versions` với cột `stage` (CHECK năm giai đoạn, không DEFAULT),
  bước niêm phong cho mọi loại, cấp `version_no` và ghi mã băm mà không đổi giai đoạn (tenant-config:R2.7), vì mọi
  chuyển giai đoạn là của `LifecycleService` của spec này, với trigger là chốt chặn (R1, R2.1, R2.8, R2.9;
  ADR-0120 (Accepted) quyết 1), sổ loại
  `studio.artifact_kinds` với cờ `has_quality_gate` cho luật theo loại của R1.6 (tenant-config:R2.14), khóa
  đọc, ghi, gửi của loại trong `ArtifactKindRegistry` cho route gửi của R2.1 (tenant-config:R2.15), móc phát hành
  của loại trên cùng mục mà R2.9 và R5.5 gọi trong giao dịch phát hành (tenant-config:R2.15; ADR-0109 (Accepted)
  quyết 1), và
  `seal(..., expected_row_version)` nhận `row_version` từ `If-Match` của lệnh gửi (tenant-config:R2.17; R2.12),
  `uq_artifacts_tenant_id_id` làm đích FK `artifact_id` của `studio.gate_runs` (R1.9; tenant-config:R2.18),
  `owning_workspace_id` không đổi của thành phần mà R4.10 đọc độ sâu (tenant-config:R2.19), chỉ mục duy nhất từng phần
  một phiên bản chưa phát hành mỗi thành phần mà R1.2, R1.3 dựa vào (tenant-config:R2.20), và route tạo nháp trả 409
  `conflict` với `candidate_pending` khi thành phần có Bản ứng viên, nên lệnh rút của R2.4 là cách sửa tiếp
  (tenant-config:R2.22; ADR-0120 (Accepted) quyết 1), cùng nội dung niêm phong của phiên bản mà route của R5.11 đọc và
  so với bản Đang dùng
  (`.claude/plans/studio/tenant-config/issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md`);
  băm `dw_kernel.canonical` (`.claude/plans/studio/tenant-config/issues/01-bam-chuan-hoa-jcs.md`); chế
  độ `simulate` chặn tác động ở executor (tenant-config:R5.1,
  `.claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md`); bản kê lượt chạy
  ghim phiên bản (`.claude/plans/studio/tenant-config/issues/04-ban-ke-luot-chay.md`); `BindingStatus.satisfied`
  đáp ứng `PublishBindingsCheck` của R2.11, R5.10 (tenant-config:R7.2), nên ticket 04 chờ
  `.claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md`; ticket đó cũng đặt
  `details.reason_code` `second_person_required` ở `_enforce_strict_rules` một lần cho mọi loại dưới tiền tố
  nghiêm, mã mà R5.2, R7.11, R8.7 khẳng định (V4.P9; ADR-0104 (Accepted) quyết 11), nên ticket 01 (R7.11) và ticket
  05 (R8.7) cũng chờ nó.
- app-standards: ETag, `If-Match`, 412 và 428 cho lệnh gửi (app-standards:R3.2, app-standards:R3.3;
  `.claude/plans/studio/app-standards/issues/03-quy-uoc-api-danh-sach-va-sua.md`), mà ticket 03 nhận qua
  tenant-config/04 và tenant-config/02.
- workflow-triggers: loại `endpoint` (`dw.endpoint/v1`) với mục `ArtifactKindRegistry` khai khóa gửi
  `studio.datahub.manage`, `has_quality_gate = false`, không bộ so sánh, và móc phát hành của loại
  (workflow-triggers:R4.7, workflow-triggers:R4.8); workflow-triggers/02 đăng ký loại đó và chờ ticket 04.
- studio-skeleton: gói `dw_studio`, nhóm route `/api/v1/studio`, schema `studio`
  (`.claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md`,
  `.claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md`); ticket 01 chờ
  studio-skeleton/01 vì test phủ offboarding và `STUDIO_EXCLUSIONS` mà R10.1 dựa vào do ticket đó dựng
  (studio-skeleton:R4.3).
- tenant-rbac: danh mục quyền là một chủ (tenant-rbac:R1.1), bảng `platform.permissions` do
  `.claude/plans/studio/tenant-rbac/issues/01-mot-chu-cho-quyen.md` tạo; mỗi khóa của spec này (mục Trong phạm
  vi) đăng ký trong migration của ticket dùng nó, theo quy ước khu vực số nhiều của ticket đó; mọi ticket đăng ký
  khóa (01, 03, 04, 05) chờ `.claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md` và nêu trong
  INSERT mọi cột NOT NULL của bảng lúc đó, gồm `risk` của tenant-rbac/01 và `tenant_grantable` của tenant-rbac/02;
  R4.10 đọc độ sâu của `studio.lifecycle.read` từ `platform.effective_grants` mà tenant-rbac/02 dựng
  (ADR-0104 (Accepted) quyết 5).
- custom-objects: bộ so sánh chỉ siết của loại `object` (custom-objects:R1.8) và móc phát hành của loại, móc chỉ
  áp định nghĩa và không ghi audit, vì spec này ghi `studio.version.published` đúng một lần (R2.9, R5.5); loại
  phê duyệt `studio.publish.object` là của custom-objects (custom-objects:R1.2), cơ chế mở, guard và handler là
  của spec này (R5.1, R5.5).
- workflow-nodes: Bước `human.approval` nhận quyết định giả lập ở `simulate` theo từ vựng `approved`, `rejected`
  (workflow-nodes:R9.9), ghi `studio.step.approval.simulated` (N2; R4.7), và kiểm người duyệt lúc gửi kiểm định
  (workflow-nodes:R9.5).
- Kiểm định thử của bản Nháp (R4.8, R4.9): `RunRequestService` ghim giai đoạn `draft` và mã băm tạm của nội dung
  nháp, và chạy bộ kiểm trả mọi lỗi của loại trên nội dung đó trước khi tạo lượt chạy (workflow-engine:R3.9,
  workflow-engine:R3.11); bản kê từ chối gốc là bản Nháp ở chế độ khác `simulate` (tenant-config:R6.7); graph quy
  trình biên dịch theo mã băm ghim (workflow-engine:R4.2), graph agent theo khóa
  `(tenant_id, agent_version_id, mã băm ghim)` (agent-builder:R3.1, agent-builder:R3.3; ADR-0117 (Accepted) quyết 5),
  với đường thật của agent ở `.claude/plans/studio/agent-builder/issues/03-runtime-agent.md`, nên ticket 04 thử phần
  agent của hợp đồng bằng một nguồn graph giả và không chờ ticket đó. Giới hạn tạm của lần thử (R4.11) là của
  `RunRequestService` (workflow-engine), dẫn từ bao đóng của bản Nháp bằng đúng phép dẫn của móc phát hành, ghi dưới
  `(version_id, pinned_hash)` cho riêng lượt đó và xóa khi lượt kết thúc (workflow-engine:R3.13,
  workflow-engine:R3.14), và của RLS của record-access, chỉ nhận giới hạn tạm ở `simulate`, giao với tầm của người thử
  (record-access:R6.11, record-access:R6.12, record-access:R6.13; ADR-0111 (Accepted) quyết 3; ADR-0109 (Accepted)
  quyết 6); spec này chỉ xin lần thử dưới danh nghĩa người xin.
- agent-builder, workflow-engine: móc phát hành của loại `agent` và của loại `workflow` ghi giới hạn dữ liệu của phiên
  bản vào `studio.actor_boundaries` qua `ActorBoundaryPort` của record-access trong giao dịch phát hành của R5.5, vì
  ranh giới dẫn ra lúc phát hành (agent-builder:R1.9,
  `.claude/plans/studio/agent-builder/issues/02-loai-agent-va-khung-prompt.md`; workflow-engine:R1.7;
  ADR-0117 (Accepted) quyết 3); móc không ghi audit, như mọi móc của loại.
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
  `platform.purge_tenant_append_only` của usage-and-limits/02 (hợp đồng xóa usage-and-limits:R3.10, thứ tự trước mọi
  bảng thường usage-and-limits:R3.11); `STUDIO_EXCLUSIONS` và
  test phủ offboarding (studio-skeleton:R4.1, studio-skeleton:R4.3); thứ tự xóa duy nhất của `offboarding.py`, liệt
  kê mỗi bảng sau mọi bảng giữ một khóa ngoại RESTRICT tới nó, mà test phủ của studio-skeleton:R4.2 kiểm bằng các cạnh
  RESTRICT đọc từ `pg_constraint`, với nhóm định nghĩa do tenant-config/02 khai (`studio.dependencies`,
  `studio.artifact_versions`, `studio.artifacts`), nơi ticket 04 chèn `studio.gate_runs` sau `studio.artifact_versions`
  và trước `studio.artifacts` (R10.2).
- Protocol do bên dùng khai: `RunControlPort` và `RunHaltedError` (runtime khai, spec này đáp ứng bằng
  `SqlRunControl`, đọc trạng thái thành viên của org-and-principals cho `principal_inactive`); `ClosureExtractor`
  theo loại (agent-builder, workflow-engine cung cấp); bảng kiểm theo loại lúc gửi kiểm định (spec này khai;
  Phân tích năng lực của
  `.claude/plans/studio/compliance-pdpl/issues/05-phan-tich-bo-ba-khi-xuat-ban.md` và kiểm workflow-nodes:R9.5
  đăng ký vào); `PublishBindingsCheck` (spec này khai, tenant-config/05 đáp); `LimitsPort` cho lease
  `eval_offline` của Lượt kiểm định và của Kiểm định thử, mà mọi lần thử dùng (runtime khai, `dw_usage` đáp;
  usage-and-limits:R5.6;
  `.claude/plans/studio/usage-and-limits/issues/03-han-muc-giu-truoc-va-quyet-toan.md`); làn `studio_inbound`
  của workflow-triggers giữ và xin lại sự kiện đã giữ (workflow-triggers:R1.3); làn `studio_runs` thi hành
  cửa nhận theo `trigger_kind` theo bảng từ chối ở dispatch của workflow-engine, gồm hàng hủy `principal_inactive`
  (workflow-engine:R5.15), hàng giữ `queued` lượt của tài khoản dịch vụ không `active` (workflow-engine:R5.17) và
  hàng `tenant_locked`, `tenant_offboarding`
  (workflow-engine:R5.18) (`.claude/plans/studio/workflow-engine/issues/04-lan-studio-runs.md`); việc giữ lượt của
  tài khoản dịch vụ không `active` là org-and-principals:R4.9, thông báo ở W1 tới người giữ `platform.members.write` ở
  độ sâu công ty là của lane giữ lượt của workflow-engine (workflow-engine:R5.20; V4.15), còn route hủy từng lượt đang
  giữ đến ở W2 của workflow-engine, nên ở W1 chỉ Tắt khẩn cấp hủy lượt đang giữ (R8.1); lane gửi tin đã xếp hàng kiểm
  công tắc trước khi gửi (R8.4), chủ là connections-and-vault ở W2.
- workflow-engine/01 và agent-builder/02 chờ ticket 03, vì ticket 03 đăng ký khóa gửi `studio.versions.submit` mà
  mục `ArtifactKindRegistry` của loại `workflow` và của loại `agent` khai (cạnh nằm ở hai ticket đó).
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
  workflow-engine đổi bảng từ chối ở dispatch → R9.1, R9.2, ticket 01; tenant-config đổi móc phát hành trên mục
  `ArtifactKindRegistry` hay tham số của `seal` → R2.9, R2.12, R5.5, ticket 03, 04; workflow-triggers đổi mục registry
  của `endpoint` → R1.6, R2.1, R5.1, ticket 03, 04; tenant-config/05 đổi mã của `_enforce_strict_rules` → R5.2,
  R7.11, R8.7, ticket 01, 04, 05; agent-builder đổi khóa cache graph hay kiểm mã băm lúc nạp, hay workflow-engine đổi
  cách `RunRequestService` ghim và kiểm bản Nháp → R4.8, R4.9, ticket 04; agent-builder hay workflow-engine đổi việc
  móc của loại ghi giới hạn dữ liệu của phiên bản → Phụ thuộc, ticket 04; tenant-config đổi `uq_artifacts_tenant_id_id`,
  `owning_workspace_id` của thành phần hay thứ tự xóa của nhóm định nghĩa, hay studio-skeleton đổi luật thứ tự hay
  test phủ của studio-skeleton:R4.2 → R1.9, R4.10, R10.2, ticket 04; tenant-rbac đổi hình `platform.effective_grants` →
  R4.10, ticket 04; tenant-config đổi chỉ mục một phiên bản chưa phát hành hay mã của route tạo nháp
  (tenant-config:R2.20, tenant-config:R2.22) → R1.2, R1.3, R2.4, ticket 03; workflow-engine hay record-access đổi cách dẫn, ghi hay nhận giới hạn tạm của bản Nháp → R4.11,
  ticket 04; ADR-0004 (Accepted) đổi ai được quyết định một yêu cầu có tem → R5.11, R5.12, ticket 04.

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
  mình và một khóa guard, kèm test khẳng định tập tiền tố đầy đủ, như tenant-config/05 đã làm, và dòng `|=` không là
  lý do cho cạnh nào: ticket 04 không chờ workflow-nodes/06 chỉ vì một dòng ở composition root, còn cạnh của ticket
  01, 04 và 05 tới tenant-config/05 có lý do riêng (mã `second_person_required`, `PublishBindingsCheck`). Sửa: ticket
  01, 04. Nếu sai thì: ticket 04 chờ workflow-nodes/06.
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
- 24/10/2026 (agent, tạm): V4.P1: tệp chính sách retention giữ một tệp có phiên bản
  `configs/policies/retention@<semver>.yaml`; các ticket sửa tệp đi thành một chuỗi bắt đầu từ usage-and-limits/02, mỗi
  ticket ra một phiên bản mới: usage-and-limits/02, usage-and-limits/03, telemetry-and-audit/03, ticket 04,
  workflow-triggers/02, compliance-pdpl/04, agent-builder/04, compliance-pdpl/06; studio-skeleton/01 không sửa tệp, nó
  đọc `retention@1.7.0` qua ánh xạ tạm; ticket 04 chờ telemetry-and-audit/03 (C:configs:spec\~telemetry-and-audit/03).
  Sửa: Phụ thuộc, ticket 04. Nếu sai thì: tách tệp theo bảng, sửa telemetry-and-audit:R5.6 và ADR-0122 (Accepted)
  quyết 7.
- 24/10/2026 (agent, tạm): mọi ticket chèn dòng vào `platform.permissions` (01, 03, 04, 05) chờ tenant-rbac/02 và nêu
  trong INSERT mọi cột NOT NULL có lúc đó, gồm `tenant_grantable` của tenant-rbac/02 và `risk` của tenant-rbac/01,
  theo ADR-0104 (Accepted) quyết 1 (C:custom-objects/02\~tenant-rbac/02). Sửa: Phụ thuộc, ticket 01, 03, 04, 05. Nếu
  sai thì: tenant-rbac/01 tạo cột kèm sửa ADR-0104 (Accepted) quyết 1.
- 24/10/2026 (agent, tạm): workflow-engine/01 chờ ticket 03, ticket chủ đăng ký khóa gửi `studio.versions.submit`;
  bên dùng chờ, việc đăng ký không chuyển (I:agent-lifecycle/03\~workflow-engine/01). Sửa: Phụ thuộc, ticket 03. Nếu
  sai thì: workflow-engine/01 đăng ký khóa và ticket 03 chỉ dùng nó.
- 24/10/2026 (agent, tạm): luật so `compared_live_hash` viết "so với phiên bản Đang dùng mà lần phát hành này thay
  (gỡ `superseded` trong cùng giao dịch), hay với NULL khi không có bản nào" thay cho "phiên bản Đang dùng hiện tại",
  vế NULL chỉ ở nhánh qua phê duyệt (R1.8) vì nhánh chỉ siết luôn thay một bản (R1.7), và lần phát hành gỡ bản cũ
  trước khi đặt bản mới theo chỉ mục một Đang dùng (R1.4; ADR-0120 (Accepted) quyết 1). Sửa:
  R1.7, R1.8, R5.6, R5.9, Dữ liệu, ticket 03, 04. Nếu sai thì: câu so ở R1.7, R1.8 và trigger đổi theo thứ tự gỡ và
  đặt mà `LifecycleService` dùng.
- 24/10/2026 (agent, tạm): lệnh gửi nhận `If-Match` là ETag của bản Nháp và chuyển giá trị đó cho
  `seal(..., expected_row_version)` của tenant-config/02: lệch → 412 `precondition_failed` với `stale_version` (V4.6),
  thiếu → 428 `precondition_required` (app-standards:R3.3; ADR-0108 (Accepted) quyết 3), để người gửi niêm phong đúng
  nội dung mình đã xem, ở nhánh có cổng (ticket 03) lẫn nhánh không cổng (ticket 04). Sửa: thêm R2.12, R2.13, Trong
  phạm vi, API, Phụ thuộc, ticket 03, 04. Nếu sai thì: lệnh gửi niêm phong nháp mới nhất không điều kiện và `seal` bỏ
  tham số `expected_row_version`.
- 24/10/2026 (agent, tạm): móc phát hành của loại nằm trên mục `ArtifactKindRegistry`, do tenant-config làm chủ
  registry và tenant-config/02 thêm trường `publish_hook` (tenant-config:R2.15; ADR-0109 (Accepted) quyết 1); spec
  của từng loại cấp móc (custom-objects cho `object`, workflow-triggers cho `endpoint`), và spec này gọi móc trong
  giao dịch phát hành, ở nhánh chỉ siết lẫn ở handler `.decided`. Sửa: R2.9, R5.5, Phụ thuộc, ticket 04. Nếu sai
  thì: móc ở một bảng điều phối riêng tại composition root, và R2.9, R5.5 dẫn bảng đó.
- 24/10/2026 (agent, tạm): V4.P9 lan đủ: người gửi là `requested_by` của phê duyệt phát hành, và kiểm tiền tố nghiêm
  chạy trước mọi guard (ADR-0104 (Accepted) quyết 11), nên người gửi tự duyệt nhận 409 `conflict` với
  `second_person_required`, chỉ người đóng góp không phải người xin nhận `author_cannot_approve`; người xin tự quyết
  `studio.lifecycle.unfreeze` hay `studio.lifecycle.revive` cũng nhận `second_person_required`, mã mà tenant-config/05
  đặt ở `_enforce_strict_rules`. Sửa: R5.2, R7.11, R8.7, AL5, AL14, AL18, API, Phụ thuộc, ticket 01, 04, 05. Nếu sai
  thì: guard `require_not_author` chạy trước kiểm tiền tố nghiêm và người gửi nhận `author_cannot_approve`, trái
  ADR-0104 (Accepted) quyết 11.
- 24/10/2026 (agent, tạm): V4.1 và V4.3 lan đủ, vì spec này là chủ route gửi và handler của mọi loại: R1.6 thêm Nguồn
  dữ liệu (`endpoint`) vào loại không có Cổng chất lượng ở W1, công cụ ở W2; R5.1 mở `studio.publish.endpoint`; route
  gửi thêm đoạn `data-sources` với khóa gửi `studio.datahub.manage` (workflow-triggers:R4.7); loại `tool`
  (`studio.publish.tool`, trừ ngoại lệ có tên `studio.mcp.tool_approval` của công cụ MCP, cả hai do handler của R5.5,
  R5.9 xử lý, như mcp-client:R3.4 dẫn) vào một dòng W2, khóa gửi do ticket W2 đăng ký loại khai; lần về Nháp vì
  `base_changed` dùng tên audit đã có `studio.version.returned_to_draft`, nên catalog
  `configs/copy/audit_actions@*.yaml` không cần tên mới (ADR-0120 (Accepted) quyết 1-2; ADR-0116 (Accepted) quyết 9;
  ADR-0122 (Accepted) quyết 6). Sửa: R1.6, R2.1, R5.1, R5.9, AL4, Trong phạm vi, Ngoài phạm vi, API, Phụ thuộc, ticket
  03, 04. Nếu sai thì: workflow-triggers giữ route gửi của `endpoint`, và R1.6, R5.1 chỉ nêu ba loại.
- 24/10/2026 (agent, tạm): R9.1 dẫn workflow-engine:R5.17 cho lượt `datahub`, `provider_app`, `record_event` được giữ
  `queued` và workflow-engine:R5.15 cho lượt bị hủy, đúng hai hàng của bảng từ chối ở dispatch. Sửa: R9.1, Phụ thuộc,
  ticket 01. Nếu sai thì: workflow-engine đánh số lại bảng đó và R9.1 dẫn số mới.
- 24/10/2026 (agent, tạm): khóa `studio.lifecycle.freeze` đến `tenant_owner` theo quyền tính động của tenant-rbac (mọi
  khóa `active` có `tenant_grantable` ở mức `tenant`, tenant-rbac:R2.7), còn vai mẫu cho công ty tạo về sau nhận
  khóa qua migration sửa mẫu, không chạm vai đã nhân bản (tenant-rbac:R3.2), vì vai là dữ liệu của công ty từ
  tenant-rbac/02 mà ticket 01 chờ (ADR-0104 (Accepted)). Sửa: ticket 01. Nếu sai thì: ticket 01 cấp khóa cho vai của
  từng công ty đã có bằng một migration dữ liệu có audit.
- 24/10/2026 (agent, tạm): spec này không còn nói "dịch vụ phát hành" của tenant-config: `LifecycleService` là bên duy
  nhất ghi `live`, gỡ bản Đang dùng cũ rồi đặt bản mới trong giao dịch phát hành, ở nhánh chỉ siết lẫn ở handler
  `.decided`, và gọi móc phát hành mà mục `ArtifactKindRegistry` của loại mang, do chủ loại cấp; trigger giai đoạn là
  chốt chặn sau nó (ADR-0109 (Accepted) quyết 1; ADR-0120 (Accepted) quyết 1-2). Sửa: R1.4, R2.8, R2.9, R5.5,
  R7.13, dòng Quyết định về câu so `compared_live_hash` ở trên, ticket 03, 04. Nếu sai thì: tenant-config giữ một
  dịch vụ phát hành mà `LifecycleService` gọi, R1.4, R2.9 và R5.5 nêu nó, và ADR-0120 (Accepted) quyết 1 ghi bên ghi
  thứ hai.
- 24/10/2026 (agent, tạm): đoạn route của Nguồn dữ liệu ở lệnh gửi là `data-sources`, tức
  `POST /api/v1/studio/data-sources/{artifact_id}/versions/{version_id}/submit`, cùng đoạn mà workflow-triggers dùng cho
  mọi route của Nguồn dữ liệu (`{id}` ở đó là `artifact_id` của thành phần) và marketing-pilot dùng khi gửi, thay
  `endpoints`, để một loại có một đoạn route. Sửa: R2.1, Trong phạm vi, API, dòng Quyết định về V4.1 và V4.3 ở trên,
  ticket 03. Nếu sai thì: mọi route của Nguồn dữ liệu đổi sang `endpoints`, và workflow-triggers, marketing-pilot sửa
  theo.
- 24/10/2026 (agent, tạm): ticket 01 và 05 chờ tenant-config/05, vì tiêu chí R7.11 và R8.7 khẳng định
  `details.reason_code` `second_person_required` mà ticket đó đặt ở `_enforce_strict_rules` một lần cho mọi loại dưới
  tiền tố nghiêm (V4.P9; ADR-0104 (Accepted) quyết 11), và một ticket không khẳng định mã do ticket nó không chờ đặt;
  đồ thị ticket không có vòng với hai cạnh mới; agent-builder/02 chờ ticket 03 cho khóa gửi `studio.versions.submit`
  của loại `agent`, cạnh nằm ở ticket đó. Sửa: Phụ thuộc, dòng Quyết định về `strict_approval_prefixes` ở trên, ticket
  01, 03, 05. Nếu sai thì: R7.11 và R8.7 ở hai ticket chỉ khẳng định 409 `conflict`, mã để test của tenant-config/05,
  và hai cạnh bỏ.
- 24/10/2026 (agent, tạm): dẫn đúng tiêu chí của usage-and-limits: hợp đồng xóa của `platform.purge_tenant_append_only`
  là usage-and-limits:R3.10 và thứ tự chạy trước mọi bảng thường là usage-and-limits:R3.11, còn usage-and-limits:R3.8
  nói các bảng của chính spec đó. Sửa: Dữ liệu, Phụ thuộc, ticket 04. Nếu sai thì: các chỗ dẫn theo số mà
  usage-and-limits đặt lại.
- 24/10/2026 (agent, tạm): `studio.gate_case_results.gate_run_id` là FK ghép `(tenant_id, gate_run_id)` tới
  `studio.gate_runs (tenant_id, id)` ON DELETE RESTRICT, vì mọi khóa ngoại nêu `ON DELETE` tường minh và có index ở
  phía mình (CLAUDE.md, Data model rules), và một DELETE lên Lượt kiểm định không được kéo theo xóa dòng chỉ thêm;
  offboarding thỏa khóa ngoại vì `platform.purge_tenant_append_only` chạy trước mọi bảng thường
  (usage-and-limits:R3.11), và index `(tenant_id, gate_run_id, case_id)` đã có mang khóa ngoại. Sửa: Dữ liệu,
  ticket 04. Nếu sai thì: ON DELETE CASCADE từ `studio.gate_runs`, mở cho `dw_app` một đường xóa dòng chỉ thêm qua
  bảng cha.
- 24/10/2026 (agent, tạm): `gate_run_id` và `publish_approval_id` của `studio.artifact_versions` là FK ghép
  `(tenant_id, <cột>)` tới UNIQUE `(tenant_id, id)` của bảng đích, vì kiểm khóa ngoại không đi qua RLS nên FK một cột
  để một công ty trỏ tới dòng của công ty khác (ADR-0109 (Accepted) quyết 1; ADR-0120 (Accepted) quyết 1, nêu đúng
  hai cột này; cùng luật với tenant-config:R2.18), và revision thêm FK thêm UNIQUE đó khi bảng đích chưa có;
  `uq_gate_runs_tenant_id_id` do ticket 04 tạo cùng `studio.gate_runs` và FK của `gate_run_id`;
  `uq_approval_requests_tenant_id_id` do revision của ticket 03 thêm cùng FK của `publish_approval_id`, vì UNIQUE đã
  có của bảng đó (`uq_approval_requests_tenant_id_workspace_id_id`, mà bảng có `workspace_id` như
  `studio.step_approvals` của workflow-nodes dùng) mang `workspace_id` mà vỏ phiên bản toàn tenant không có; R1.9 và
  AL21 thử cả ba FK, như tenant-config:R2.18 và TC29. Sửa: thêm R1.9, AL21, Dữ liệu, ticket 03, 04. Nếu sai thì: FK
  của `publish_approval_id` đi qua `uq_approval_requests_tenant_id_workspace_id_id`, và vỏ phiên bản mang
  `workspace_id` của phê duyệt.
- 24/10/2026 (agent, tạm): ở mục Dữ liệu, vế "cùng NULL khi không có bản nào" của luật trigger chỉ áp cho
  `awaiting_approval → live` (R1.8); nhánh chỉ siết `draft → live` luôn có mã băm, vì nó cần một bản Đang dùng để so
  (R2.8) và CHECK `NOT tighten_only OR compared_live_hash IS NOT NULL` buộc vậy (R1.7; ADR-0120 (Accepted) quyết 1).
  Sửa: Dữ liệu, dòng Quyết định về câu so `compared_live_hash` ở trên. Nếu sai thì: nhánh chỉ siết nhận cả phiên bản
  đầu, và R1.7, R2.8 cùng CHECK đổi theo.
- 24/10/2026 (agent, tạm): Đóng băng có thể tiếp tục cho lượt đang chạy là W3, không W2, như dòng của agent-lifecycle ở
  mục Không làm của requirements.md và mục Open của ADR-0120 (Accepted), DO-28 (v1.5); nguyên mẫu của ticket 01 là số
  đo cho quyết định đó. Sửa: Ngoài phạm vi, ticket 01. Nếu sai thì: dòng về W2, và requirements.md cùng
  ADR-0120 (Accepted) đổi theo.
- 24/10/2026 (agent, tạm): ticket 01 bước 1 dẫn tenant-rbac:R2.7 cho luật động của `tenant_owner` (mọi khóa `active` có
  `tenant_grantable` ở mức `tenant`, kể cả khóa đăng ký sau lần gán vai trò), tiêu chí mà tenant-rbac đặt cho luật đã
  dựng ở tenant-rbac/02 bước 7, để `studio.lifecycle.freeze` đến chủ sở hữu công ty theo một tiêu chí có kiểm soát
  (RB34) chứ không theo một bước của ticket khác. Sửa: ticket 01, dòng Quyết định về `studio.lifecycle.freeze` ở trên.
  Nếu sai thì: bước 1 dẫn lại tenant-rbac/02 bước 7 và tenant-rbac giữ luật ở ticket.
- 24/10/2026 (agent, tạm): FK `tenant_id` của `platform.control_switches` tới `platform.tenants` có index `(tenant_id)`
  riêng, vì mọi khóa ngoại có chỉ mục ở phía mình (CLAUDE.md, Data model rules) mà chỉ mục một công tắc mở là từng phần
  (`WHERE lifted_at IS NULL`), không phủ dòng đã gỡ mà lần xóa theo khóa ngoại và lượt xuất của offboarding chạm tới;
  mọi FK khác của spec đã có index dẫn bằng cột của nó. Sửa: Dữ liệu, ticket 01. Nếu sai thì: khóa chính
  `(tenant_id, id)` của bảng mang FK đó và index riêng bỏ.
- 24/10/2026 (agent, tạm): tenant-config niêm phong (bước `seal` cấp `version_no`, ghi `content_hash`, `definition_hash`
  và so `row_version`; tenant-config:R2.7, tenant-config:R2.17) mà không đổi giai đoạn, còn `LifecycleService` của spec
  này chuyển mọi giai đoạn (`draft → evaluating`, sang `awaiting_approval`, sang `live`) với trigger là chốt chặn, như
  ADR-0120 (Accepted) quyết 1 ghi (`LifecycleService` ghi, trigger là chốt chặn), nên spec này không dẫn tenant-config
  cho việc chuyển giai đoạn. Sửa: R2.1, Phụ thuộc, dòng Quyết định về câu so `compared_live_hash` ở trên, ticket 03
  bước 5, ticket 04 bước 7. Nếu sai thì: bước niêm phong của tenant-config chuyển giai đoạn, R2.1, Phụ thuộc và ticket
  03, 04 dẫn lại tenant-config:R2.7, tenant-config:R2.13, tenant-config:R2.16, và ADR-0120 (Accepted) quyết 1 ghi bên
  ghi thứ hai.
- 24/10/2026 (agent, tạm): route `dry-evaluations` nhận phiên bản `draft` của agent, như V4.4 cho bản Nháp của quy
  trình: Kiểm định thử (dòng `studio.gate_runs` có `purpose` `dry`) chạy dưới trần và lease của R4.4, R4.5, mỗi lần
  thử là một lượt `simulate` có gốc là bản Nháp, ghim giai đoạn `draft` và mã băm tạm của nội dung nháp
  (ADR-0109 (Accepted) quyết 6), và graph agent biên dịch theo khóa `(tenant_id, agent_version_id, pinned_hash)`, với
  bản Nháp chỉ cho lượt `simulate` (ADR-0117 (Accepted) quyết 5; agent-builder:R3.1, agent-builder:R3.3), như graph
  quy trình theo workflow-engine:R4.2; Kiểm định thử không niêm phong, không đổi giai đoạn và không mở phê duyệt, vì nó
  không dẫn tới phát hành (mục Dry evaluation của `docs/platform/CONTEXT.md`); lần thử mà `RunRequestService` từ chối
  vì nội dung nháp trượt bộ kiểm của loại (workflow-engine:R3.11) kết thúc Kiểm định thử là `error` kèm các lỗi, như
  lần từ chối lease ở R4.4. Sửa: thêm R4.8, R4.9, AL22, API, Phụ thuộc, ticket 04. Nếu sai thì: Kiểm định thử chỉ nhận
  Bản ứng viên hay bản Nháp của quy trình, glossary thu hẹp nghĩa của từ, R4.8 nêu giai đoạn đó, và lần trượt bộ kiểm
  trả 422 `validation_failed` ở route thay R4.9.
- 24/10/2026 (agent, tạm): móc phát hành của loại `agent` ghi các dòng `studio.actor_boundaries` của agent qua
  `ActorBoundaryPort` của record-access trong giao dịch phát hành, vì agent-builder làm chủ các dòng đó và chúng dẫn ra
  lúc phát hành (ADR-0117 (Accepted) quyết 3; agent-builder:R1.9), và móc của loại `workflow` làm cùng việc cho quy
  trình (workflow-engine:R1.7), nên ticket 04 không còn nói móc của loại chỉ áp định nghĩa: móc làm phần việc của loại
  và không ghi audit. Sửa: Phụ thuộc, ticket 04 bước 5. Nếu sai thì: ranh giới của phiên bản được ghi ngoài móc phát
  hành, Phụ thuộc bỏ dòng agent-builder, workflow-engine và bước 5 không nêu ranh giới.
- 24/10/2026 (agent, tạm): `dw_app` giữ DELETE trên `studio.gate_runs` chỉ cho lượt xóa của offboarding: trigger
  `studio.guard_gate_run_delete()` BEFORE DELETE từ chối với SQLSTATE 23514 khi `platform.tenants.status` của công ty
  của dòng khác `offboarding`, vì lane `offboarding` xóa bằng `dw_app` và chỉ thấy bảng mà `dw_app` có DELETE
  (`_CATALOG_PURGEABLE` của `offboarding.py`), còn ứng dụng không bao giờ xóa một Lượt kiểm định, bằng chứng mà phát
  hành dựa vào (CLAUDE.md, Data model rules: quyền là một phần của lược đồ; cùng hình với
  `platform.guard_control_switch()` của R7.5 và `platform.guard_contact_suppression()` của compliance-pdpl:R5.6).
  Sửa: R10, thêm R10.2, R10.3, AL24, Dữ liệu, ticket 04. Nếu sai thì: `dw_app` không có DELETE trên bảng, offboarding
  xóa Lượt kiểm định qua một hàm SECURITY DEFINER hẹp và bảng có một dòng `STUDIO_EXCLUSIONS` nêu hàm đó.
- 24/10/2026 (agent, tạm): `studio.gate_runs` và `studio.gate_case_results`, không cột `workspace_id`, mỗi bảng có một
  dòng lý do trong danh sách bảng toàn tenant của `test_rls_coverage.py` (CLAUDE.md, Tenancy and authorization;
  studio-skeleton:R9.1); `studio.gate_runs` thêm `artifact_id` NOT NULL, FK ghép `(tenant_id, artifact_id)` tới
  `studio.artifacts` ON DELETE RESTRICT có index `(tenant_id, artifact_id)`, để ba route đọc Lượt kiểm định, kể cả dòng
  `dry` của R4.8 mà không phiên bản nào trỏ tới, lọc theo độ sâu của người đọc ở workspace sở hữu của thành phần
  (ADR-0104 (Accepted) quyết 3), và R1.9, AL21 thêm ca âm chéo tenant của FK đó (CLAUDE.md, Tenancy and
  authorization). Khóa ngoại đó cùng khóa ngoại `gate_run_id` (RESTRICT) của phiên bản buộc `_ORDERED_FIRST` xóa
  `studio.artifact_versions` rồi `studio.gate_runs` trước `studio.artifacts`, ngược thứ tự thành phần trước phiên bản
  mà ADR-0109 (Accepted) Consequences ghi; thứ tự đó không khóa ngoại nào đòi, nó chạy được chỉ nhờ phiên bản xóa theo
  CASCADE từ thành phần. Sửa: R1.9, thêm R4.10, AL21, thêm AL23, R10.2, Dữ liệu, API, Phụ thuộc, ticket 04. Nếu sai
  thì: hai bảng mang `workspace_id` của thành phần với policy hình workspace của CLAUDE.md thay hai dòng danh sách và
  R4.10 lọc bằng RLS; nếu ADR-0109 (Accepted) giữ thứ tự thành phần trước phiên bản, ON DELETE của `artifact_id` đổi và
  R10.2, ticket 04 đổi theo.
- 24/10/2026 (Đạt): V4.15: lượt `datahub`, `provider_app`, `record_event` bị giữ vì `principal_inactive` khiến lane giữ
  lượt của workflow-engine gửi ở W1 một thông báo tới người giữ `platform.members.write` ở độ sâu công ty, một lần cho
  mỗi lần tài khoản rời `active` (workflow-engine:R5.20), thay câu "báo người chịu trách nhiệm ở W2"; hủy từng lượt
  đang giữ vẫn là W2, và Tắt khẩn cấp vẫn dọn được hàng chờ (R8.1). Sửa: Phụ thuộc.
- 24/10/2026 (Đạt): V4.17: mỗi thành phần có tối đa một phiên bản chưa phát hành (`draft`, `evaluating` hay
  `awaiting_approval`), bằng chỉ mục duy nhất từng phần của tenant-config thay chỉ mục một Bản ứng viên của spec này,
  cùng tối đa một bản `live`; tạo bản Nháp mới khi đang có Bản ứng viên trả 409 `conflict` với `candidate_pending` ở
  route tạo nháp của tenant-config, và người dựng muốn sửa thì rút Bản ứng viên về Nháp bằng lệnh rút của R2.4; ca tranh
  chấp của V4.2 (một bản chỉ siết lên `live` trong lúc Bản ứng viên chờ) không còn dựng được, nên AL19 thử gốc đổi bằng
  lần gỡ bản `live` trong lúc Bản ứng viên chờ, và kiểm gốc `compared_live_hash` vẫn là hàng rào (ADR-0120 (Accepted)
  quyết 1). Sửa: R1.2, R1.3, R2.4, AL2, AL19, Dữ liệu, Phụ thuộc, ticket 03, 04.
- 24/10/2026 (Đạt): V4.18: handler `studio.publish.<kind>.decided` của một phê duyệt đã `approved` mà không áp được đưa
  phiên bản về Nháp với `details.reason_code` của lý do (`tenant_frozen` khi công ty đang Đóng băng, `binding_unset` khi
  Điểm gắn bắt buộc chưa duyệt, `owner_missing` khi thiếu người chịu trách nhiệm, phần này từ W2) và audit
  `studio.version.returned_to_draft` đứng tên người quyết định, như `base_changed` của R5.9, thay việc từ chối lần giao,
  để không phiên bản nào ở `awaiting_approval` với một phê duyệt đã quyết (ADR-0120 (Accepted) quyết 2). Sửa: R5.10,
  R7.12, AL11, AL20, API, Ngoài phạm vi, ticket 04.
- 24/10/2026 (agent, tạm): Đóng băng của nền tảng ở handler phát hành đi cùng luật của V4.18 với `platform_frozen`, vì
  R7.12 xử lý cả hai Đóng băng và V4.18 không để phiên bản nào ở `awaiting_approval` với một phê duyệt đã quyết. Sửa:
  R7.12, AL11, ticket 04. Nếu sai thì: lần giao khi Đóng băng của nền tảng giữ phiên bản ở `awaiting_approval` tới khi
  gỡ, R7.12 tách hai nhánh và ADR-0120 (Accepted) quyết 2 ghi nhánh đó.
- 24/10/2026 (Đạt): V4.22: lần thử của Kiểm định thử một bản Nháp, lượt `simulate` có gốc là bản Nháp, đọc dưới giới
  hạn tạm mà `RunRequestService` của workflow-engine dẫn ra từ bao đóng của bản Nháp bằng đúng phép dẫn của móc phát
  hành, ghi dưới `(version_id, pinned_hash)` cho riêng lượt đó và xóa khi lượt kết thúc; tầm đọc là phần giao với quyền
  của người thử, tức người xin Kiểm định thử, nên lane `studio_gate` xin lần thử dưới danh nghĩa người đó; không lượt
  `live` nào dùng giới hạn tạm, và RLS của record-access chỉ nhận nó ở `simulate` (workflow-engine:R3.13,
  record-access:R6.13; ADR-0111 (Accepted) quyết 3; ADR-0103 (Accepted) quyết 5; ADR-0109 (Accepted) quyết 6). Sửa:
  thêm R4.11, AL26, API, Phụ thuộc, ticket 04.
- 24/10/2026 (Đạt): V4.23: trong lúc một phê duyệt `studio.publish.*` còn `pending`, người được quyết định nó (giữ tem
  `studio.publish.approve`, và được giao nếu loại giao người) đọc Bản ứng viên và phần khác với bản `live` qua route
  phê duyệt của spec này, có audit; ngoài lúc đó, đọc định nghĩa cần khóa tác giả của loại (tenant-config:R2.11); người
  không giữ tem, hay phê duyệt đã quyết → 404 như không tồn tại (ADR-0120 (Accepted) quyết 2; ADR-0004 (Accepted) sửa
  đổi 07/10/2026). Sửa: thêm R5.11, R5.12, AL25, API, Trong phạm vi, Ngoài phạm vi, Phụ thuộc, ticket 04.
- 24/10/2026 (agent, tạm): route của V4.23 là `GET /api/v1/studio/publish-approvals/{approval_id}/candidate`, khóa theo
  id của yêu cầu phê duyệt vì quyền đọc đi theo yêu cầu đang chờ, không theo thành phần; người được quyết định là người
  mà ADR-0004 (Accepted) sửa đổi 07/10/2026 cho quyết định (`approvals.decide` cùng tem), như inbox `/approvals` đã lọc;
  mỗi lần đọc ghi một audit `studio.version.candidate_read`, tên đăng ký vào catalog `configs/copy/audit_actions@*.yaml`
  (ADR-0122 (Accepted) quyết 6) theo cách telemetry-and-audit đặt cho các ticket sau nó; phần khác là `changes[]` theo
  con trỏ JSON với giá trị trước và sau trên hai tài liệu chuẩn hóa RFC 8785, cả tài liệu là thêm khi chưa có bản Đang
  dùng. Sửa: R5.11, R5.12, API, ticket 04. Nếu sai thì: route nằm dưới `/api/v1/approvals/{approval_id}` của nền tảng
  với cùng kiểm và cùng ca âm, tên audit theo catalog, và hình của phần khác do màn "Xem diff" quyết.
- 24/10/2026 (agent, tạm): thứ tự xóa khi offboarding theo khóa ngoại: thứ tự duy nhất trong `offboarding.py` liệt kê
  mỗi bảng sau mọi bảng giữ một khóa ngoại RESTRICT tới nó, thay thứ tự "dependencies, artifacts, artifact_versions" của
  ADR-0109 (Accepted) Consequences, vốn dựa vào CASCADE từ thành phần xuống phiên bản mà khóa ngoại `artifact_id`
  (RESTRICT) của `studio.gate_runs` và `gate_run_id` (RESTRICT) của phiên bản làm vỡ. Với nhóm định nghĩa, luật đó cho:
  các bảng trỏ tới phiên bản (như `platform.worker_runs`, `studio.trigger_subscriptions`, `platform.run_manifest_keys`
  và `studio.dependencies`), `studio.artifact_versions`, `studio.gate_case_results`, `studio.gate_runs`, rồi
  `studio.artifacts`; `studio.dependencies` đứng trước phiên bản, không sau Lượt kiểm định, vì `to_version_id` của nó
  là khóa RESTRICT tới phiên bản (ADR-0109 (Accepted) quyết 5), như tenant-config và ADR-0109 (Accepted) Consequences
  cùng ghi; `studio.gate_case_results` đi ở bước `platform.purge_tenant_append_only`, đứng trước mọi bảng thường
  (usage-and-limits:R3.11); test phủ của studio-skeleton:R4.2 đọc các cạnh RESTRICT từ `pg_constraint` và đỏ khi thứ
  tự khai trái chúng (failure-modes #0).
  Sửa: Dữ liệu, Phụ thuộc, ticket 04 bước 1 và tiêu chí R10.2. Nếu sai thì: các khóa RESTRICT đó thành
  `NO ACTION DEFERRABLE INITIALLY DEFERRED`, kiểm lúc commit, để giao dịch xóa duy nhất xóa cả nhóm theo thứ tự nào cũng
  được, và ticket 04 bỏ vị trí riêng của `studio.gate_runs` trong thứ tự.

## Danh sách ticket

| #   | Ticket                                                                                                  |
| --- | ------------------------------------------------------------------------------------------------------- |
| 01  | [Đóng băng toàn nền tảng và theo tenant, kiểm ở mọi cửa](issues/01-dong-bang-va-kiem-o-moi-cua.md)      |
| 02  | [Mở rộng dw_evals: quan sát, bộ chấm, JudgePort, lặp, cổng thuần](issues/02-mo-rong-dw-evals.md)        |
| 03  | [Hợp đồng vòng đời phiên bản và gửi kiểm định niêm phong](issues/03-hop-dong-vong-doi-va-niem-phong.md) |
| 04  | [Cổng chất lượng mô phỏng và duyệt phát hành hai người](issues/04-cong-kiem-dinh-va-duyet-hai-nguoi.md) |
| 05  | [Tắt khẩn cấp agent và quy trình, bật lại hai người](issues/05-tat-khan-cap-va-khoi-phuc.md)            |
