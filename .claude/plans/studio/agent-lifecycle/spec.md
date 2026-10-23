# Vòng đời agent và quy trình: giai đoạn, cổng chất lượng, tắt khẩn cấp và đóng băng

Status: needs-triage
Area: studio · Nhánh: `docs/studio-planning` · Viết: 23/10/2026
Duyệt: chưa
Sẵn sàng: chưa kiểm

Người dựng cần một lớp điều khiển vòng đời cho agent và quy trình: mỗi phiên bản đi qua Nháp, Đang
kiểm định, Chờ duyệt, Đang dùng, Đã gỡ trong một máy trạng thái do PostgreSQL canh; chỉ sang Đang dùng
khi Cổng chất lượng đạt trên đúng Mã băm định nghĩa của phiên bản (Bộ kiểm định an ninh nền tảng 100%)
và một người không phải Tác giả duyệt; Đóng băng và Tắt khẩn cấp được kiểm ở mọi cửa của runtime và
đóng khi lỗi. Lát này đứng trên vỏ phiên bản dùng chung của tenant-config (ADR-0109 (Accepted)) và cài
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
- R1.6 ĐỐI VỚI một loại thành phần mà sổ loại ghi là không có Cổng chất lượng (đối tượng `dw.object/v1`,
  công cụ), `studio.guard_version_stage()` PHẢI cho `draft → awaiting_approval` không qua Đang kiểm định và
  không đòi `gate_run_id`, và vẫn đòi `publish_approval_id` đã `approved` cho `awaiting_approval → live`.

### R2 — Gửi kiểm định niêm phong nội dung và ghi chỉ mục phụ thuộc

KHI gửi kiểm định, nội dung phiên bản bị niêm phong và bao đóng của nó băm thành Mã băm định nghĩa, để
"đã kiểm định" và Lệch cấu hình tính được (YC30; ADR-0109 (Accepted) quyết 4-5).

- R2.1 KHI người giữ `studio.versions.submit` gửi kiểm định một nháp hợp lệ qua
  `POST /api/v1/studio/{agents|workflows}/{artifact_id}/versions/{version_id}/submit`, dịch vụ gửi kiểm
  định PHẢI, trong một giao dịch, tính bao đóng bằng `ClosureExtractor` của loại, niêm phong nội dung
  qua bước niêm phong của tenant-config, ghi Mã băm định nghĩa, Nơi đang dùng và audit
  `studio.version.submitted`, rồi chuyển Nháp sang Đang kiểm định.
- R2.2 Mã băm định nghĩa của một phiên bản PHẢI là hàm của nội dung niêm phong và bao đóng ghim, nên
  hai phiên bản cùng nội dung và bao đóng cho cùng mã băm, còn một phần bao đóng ghim đổi thì cho mã
  băm khác.
- R2.3 NẾU giao dịch gửi kiểm định hỏng giữa chừng, THÌ dịch vụ gửi kiểm định PHẢI không để lại bản kê
  định nghĩa, dòng Nơi đang dùng hay audit nào của phiên bản đó.
- R2.4 KHI người giữ `studio.versions.submit` rút một Bản ứng viên chưa có quyết định qua
  `POST .../withdraw`, dịch vụ vòng đời PHẢI đưa phiên bản về Nháp và hủy yêu cầu phê duyệt phát hành
  đang treo trong một giao dịch, với audit `studio.version.returned_to_draft`.
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
  định an ninh nền tảng ở chế độ `simulate` (bộ đề của tenant là W2), chấm theo Chính sách cổng đã ghim, và
  chỉ cho qua khi bộ đó đạt 100%.
- R4.2 NẾU một Câu kiểm định của Bộ kiểm định an ninh nền tảng không đạt, hoặc một Câu kiểm định cho
  kết quả `unknown`, THÌ Cổng chất lượng PHẢI kết luận trượt và đưa phiên bản về Nháp.
- R4.3 TRONG KHI một Lượt kiểm định chạy, NẾU một công cụ có tác động được gọi, THÌ ToolExecutor PHẢI
  giả lập lời gọi và không để tác động nào rời nền tảng (tenant-config:R5.1).
- R4.4 NẾU chi phí xấu nhất của một Lượt kiểm định (số lần thử nhân trần chi phí mỗi lần thử, cộng lời
  gọi giám khảo) vượt trần mỗi lượt của Chính sách cổng, hoặc `LimitsPort` từ chối lease `eval_offline`
  của lượt, THÌ lane `studio_gate` PHẢI kết thúc Lượt kiểm định là `error` với `limit_exceeded` trước lời
  gọi model đầu tiên và không tạo lượt chạy nào.
- R4.5 NẾU một lần thử chạm trần chi phí mỗi lần thử, THÌ lane `studio_gate` PHẢI dừng lần thử đó ở lời
  gọi kế tiếp, đánh Câu kiểm định đó trượt với lý do `cost_bound`, và vẫn chấm các câu còn lại.
- R4.6 KHI hai Lượt kiểm định có cùng khóa bằng chứng (Mã băm hiệu lực, Chính sách cổng, Bộ kiểm định
  an ninh nền tảng, danh sách mã băm bộ đề của tenant, rỗng ở W1), lane `studio_gate` PHẢI dùng lại kết
  quả Đạt và không tạo lượt chạy thứ hai.

### R5 — Phát hành cần một người không phải Tác giả duyệt

Một phiên bản sang Đang dùng chỉ qua một yêu cầu phê duyệt không lượt chạy mà người quyết định không
phải Tác giả, và PostgreSQL canh đúng điều kiện đó (YC70, YC60; D11; ADR-0120 (Accepted) quyết 2).

- R5.1 KHI Cổng chất lượng của một phiên bản đạt, lane `studio_gate` PHẢI, trong cùng giao dịch chuyển
  Đang kiểm định sang Chờ duyệt, mở một yêu cầu phê duyệt `studio.publish.agent` hoặc
  `studio.publish.workflow` có `required_scope` `studio.publish.approve` và payload chỉ id và mã gồm
  `author_ids` dựng từ `contributor_ids` và `submitted_by` của chính dòng phiên bản đó.
- R5.2 NẾU người quyết định một yêu cầu phê duyệt phát hành có trong `author_ids` (người gửi hoặc người
  đóng góp), THÌ luồng phê duyệt PHẢI trả 409 `author_cannot_approve` và không đổi gì.
- R5.3 NẾU payload của một yêu cầu phê duyệt phát hành thiếu `author_ids`, THÌ luồng phê duyệt PHẢI từ
  chối quyết định và không đưa phiên bản sang Đang dùng.
- R5.4 NẾU người quyết định không giữ tem `studio.publish.approve`, THÌ luồng phê duyệt PHẢI trả 404
  khi đọc và khi quyết định, kể cả với `platform_admin`.
- R5.5 KHI một yêu cầu phê duyệt phát hành được duyệt, handler outbox PHẢI, trong một giao dịch và đúng
  một lần dù sự kiện được giao lại, đưa phiên bản sang Đang dùng, phiên bản cũ sang Đã gỡ (`superseded`),
  ghi audit `studio.version.published` với actor là người quyết định và `details.lane` là tên lane
  (ADR-0011 (Accepted)), và outbox `studio.version.live`.
- R5.6 NẾU `dw_app` đưa một phiên bản sang Đang dùng khi yêu cầu phê duyệt phát hành liên kết chưa ở
  `approved`, hoặc khi `gate_run_id` không phải một Lượt kiểm định đạt trên đúng Mã băm định nghĩa của
  phiên bản, THÌ PostgreSQL PHẢI từ chối với SQLSTATE 23514 và không đổi gì.
- R5.7 KHI một yêu cầu phê duyệt phát hành quá `publish_approval_ttl_days` của Chính sách cổng (14 ngày),
  lane hết hạn phê duyệt phát hành PHẢI hủy yêu cầu, đưa phiên bản về Nháp và ghi audit với actor
  `system:<lane>` trong một giao dịch.

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
  `tenant_frozen` hay `platform_frozen`, để làn để nguyên sự kiện tới khi gỡ rồi xin lượt chạy theo
  `received_at` (workflow-triggers:R1.3).
- R7.3 NẾU `RunControlPort` không làm mới được trạng thái công tắc quá 30 giây, THÌ cửa runtime PHẢI từ
  chối lời gọi công cụ với `control_state_unavailable`.
- R7.4 NẾU quản trị viên công ty gỡ một Đóng băng có `origin` `platform` qua
  `POST /api/v1/admin/unfreeze`, THÌ API quản trị PHẢI trả 403 và không gỡ.
- R7.5 NẾU `dw_app` ghi thẳng để gỡ hay đổi một công tắc ngoài bước gỡ một lần hợp lệ, THÌ PostgreSQL
  PHẢI từ chối với SQLSTATE 23514 và không đổi gì.
- R7.6 KHI một Đóng băng được đặt hay gỡ, API hay handler tương ứng PHẢI ghi đúng một sự kiện audit trong
  cùng giao dịch, chỉ mang id và mã.
- R7.7 TRONG KHI một Đóng băng của phạm vi đang mở, KHI cửa nhận lượt chạy gặp một lượt chạy tương tác
  (`chat`, `manual`, `test`) hay một lần thử của Lượt kiểm định, cửa nhận PHẢI kết thúc lượt chạy là
  `cancelled` với `tenant_frozen` hay `platform_frozen` mà không gọi model nào.
- R7.8 TRONG KHI một Đóng băng của phạm vi đang mở, KHI cửa nhận lượt chạy gặp một lượt chạy do trình kích
  hoạt đã xếp hàng (`datahub`, `provider_app`, `schedule`, `record_event`), cửa nhận PHẢI giữ lượt chạy ở
  `queued` và cho nó chạy theo thứ tự xếp hàng sau khi gỡ Đóng băng.
- R7.9 NẾU người giữ `studio.versions.submit` gửi kiểm định trong khi Đóng băng của công ty hay nền tảng
  đang mở, THÌ dịch vụ gửi kiểm định PHẢI trả 409 `tenant_frozen` hay `platform_frozen` và không chuyển
  phiên bản khỏi Nháp.
- R7.10 KHI người giữ `studio.lifecycle.freeze` xin gỡ một Đóng băng có `origin` `tenant` qua
  `POST /api/v1/admin/unfreeze`, API quản trị PHẢI mở một yêu cầu phê duyệt `studio.lifecycle.unfreeze`
  nghiêm có tem `studio.lifecycle.freeze`, và chỉ gỡ Đóng băng khi một người khác người xin duyệt.
- R7.11 NẾU người quyết định gỡ Đóng băng là người xin gỡ, THÌ luồng phê duyệt PHẢI trả 409 và không gỡ
  Đóng băng.

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
  phần đó để gửi, lane gửi đi PHẢI không gọi nhà cung cấp.
- R8.5 KHI một agent bị Tắt khẩn cấp được dùng làm agent liên kết trong một agent khác, stack con PHẢI
  từ chối lời gọi của agent liên kết đó.
- R8.6 KHI người giữ `studio.lifecycle.kill` xin bật lại một thành phần, API PHẢI mở một yêu cầu phê
  duyệt `studio.lifecycle.revive` nghiêm có tem `studio.lifecycle.kill`, và chỉ gỡ công tắc khi một
  người khác người xin duyệt.
- R8.7 NẾU người quyết định bật lại là người xin bật lại, THÌ luồng phê duyệt PHẢI trả 409 và không gỡ
  công tắc.
- R8.8 KHI một thành phần bị Tắt khẩn cấp hay được bật lại, API hay handler tương ứng PHẢI ghi đúng một
  sự kiện audit trong cùng giao dịch, chỉ mang id và mã.

### R9 — Lượt chạy của chủ thể không còn active dừng ở cửa

Lượt chạy của một thành viên bị gỡ khỏi công ty hay bị tạm khóa không được nhận mới hay tiếp tục, qua cùng
`RunControlPort` mà mọi cửa đã hỏi, không thêm port nào (org-and-principals:R4.6).

- R9.1 NẾU chủ thể chạy của một lượt chạy (người kích hoạt hay tài khoản dịch vụ) không còn `active` trong
  công ty khi lượt chạy tới cửa nhận hay cửa tiếp tục, THÌ `RunControlPort` PHẢI từ chối với
  `principal_inactive` và lượt chạy kết thúc là `cancelled` mà không gọi model hay công cụ nào.

## Hành vi giữ nguyên

- G1 KHI CI chạy `scripts/run_evals.py`, `dw_evals` PHẢI TIẾP TỤC chạy `run_dataset` trên dataset nền
  tảng với `SECURITY_CATEGORIES` không đổi (test: `apps/api/tests/unit/test_eval_datasets.py`).

## Trong phạm vi

- Bảng, cột và trigger ở mục Dữ liệu; route ở mục API.
- Mã: cột vòng đời và `studio.guard_version_stage()` trên `studio.artifact_versions`, với luật theo loại
  cho loại không có Cổng chất lượng; `VersionStage` StrEnum với bảng chuyển đổi thuần và
  `LifecycleService`; view Giai đoạn hiển thị; dịch vụ gửi kiểm định với bảng điều phối `ClosureExtractor`
  và bảng kiểm theo loại lúc gửi kiểm định (Protocol của spec này, compliance-pdpl và workflow-nodes đăng
  ký kiểm của mình); mở rộng `dw_evals` (Observation, ObservationGrader, `JudgePort`, `EvalTargetPort`,
  `run_cases`, `gate.py`); lane `studio_gate`; `RunControlPort` (gồm lý do `principal_inactive`),
  `RunHaltedError` và adapter `SqlRunControl` với cache đóng khi lỗi; các cửa đóng băng và kill; prefix
  nghiêm `studio.publish.`, `studio.lifecycle.` và guard `require_not_author`; handler outbox phát hành,
  bật lại và gỡ Đóng băng; lane hết hạn phê duyệt phát hành; lane `control_switch` nghe outbox
  `control.switch.changed`.
- Audit: `studio.version.submitted`, `.returned_to_draft`, `.retired`, `.published`,
  `control.freeze.set`, `control.freeze.lifted`, `control.kill.set`, `control.kill.lifted`,
  `studio.gate_run.started`, `.completed`, `approval.cancelled` (lane `control_switch`), `tool.denied`
  (`policy_decision` `deny_frozen`); trong `platform.provisioning_audit`: `platform.freeze.set`,
  `platform.freeze.lifted`, `platform.tenant_freeze.set`, `platform.tenant_freeze.lifted`.

## Ngoài phạm vi

| Việc                                                                                                                                                                  | Vì sao                                                                                                                                                             | Chủ                                               |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------- |
| Phân tích năng lực Bộ ba nguy hiểm (tín hiệu A, B, C từ bao đóng, nút phê duyệt áp đảo C) lúc gửi kiểm định, 422 khi chưa đạt, kết quả ở `studio.version_assessments` | ADR-0125 (Accepted); R2.7 gọi nó qua bảng kiểm theo loại, R6 chỉ đọc kết quả đã ghi                                                                                | compliance-pdpl                                   |
| W2: bộ đề kiểm định của tenant (bảng, API, màn nhập câu không code, `studio.gate_run_datasets`), cùng `min_cases_total`, `pass_rate_min` của Chính sách cổng          | YC74; cần gói và điều hướng của studio-skeleton; trường chính sách vào cùng bên đọc của nó (DO-29.1)                                                               | agent-lifecycle, đợt sau (W2)                     |
| W2: Mức rủi ro AI trên `studio.version_assessments` (công ty tự phân hạng từ mặc định, không khai thấp hơn ở v1), tờ giải thích                                       | YC93; DO-60; bảng có từ W1 cho kết quả Phân tích năng lực (compliance-pdpl:R4.6)                                                                                   | compliance-pdpl; agent-lifecycle đọc (W2)         |
| W2: tổng quan đội ngũ, "đã kiểm định thật N/M", chip cảnh báo, cảnh báo nháp để lâu (`stale_draft_days`), trang phiên bản, so sánh từng trường                        | YC75; mẫu học từ phân tích đối thủ (config-chang.md mẫu 3); đọc theo quyền người xem, cổng chặn ở server; `stale_draft_days` vào chính sách cùng bên đọc (DO-29.1) | agent-lifecycle, đợt sau (W2)                     |
| W2: Đóng băng có thể tiếp tục cho lượt đang chạy (`RunStatus.FROZEN`, lane tiếp tục sau khi gỡ)                                                                       | W1 hủy lượt đang chạy ở cửa kế tiếp và chỉ giữ lượt do trình kích hoạt đã xếp hàng (DO-28 C); cần nguyên mẫu của ticket 01                                         | agent-lifecycle, đợt sau (W2)                     |
| W2: phát hiện Lệch cấu hình, giám khảo LLM hiệu chuẩn, kiểm định retrieval, so với bản đang chạy                                                                      | mẫu cảnh báo lệch học từ phân tích đối thủ (config-chang.md mẫu 3); cần `mcp-client`, `model-connections`                                                          | agent-lifecycle, đợt sau (W2)                     |
| W2: kiểm định trực tuyến lấy mẫu (tắt mặc định, model chấm cùng Lộ trình dữ liệu), phân tích năng lực theo đường đi, gói hồ sơ AI theo Luật AI                        | YC93; chờ `usage-and-limits`, `workflow-nodes` và luật sư (DO-60)                                                                                                  | agent-lifecycle; compliance-pdpl, đợt sau (W2)    |
| W2: kiểm định lại khi ghi đè của tenant đổi Mã băm hiệu lực, phần nền tảng trả có trần cho lượt do nền tảng kích                                                      | bằng chứng khóa theo Mã băm hiệu lực nên bằng chứng cũ tự hết giá trị (ADR-0109 (Accepted)); DO-29.2                                                               | agent-lifecycle; usage-and-limits, đợt sau (W2)   |
| W2: `scope_type` `tool` trên công tắc để ngưng công cụ MCP (`suspended`), gỡ bằng `studio.lifecycle.revive` nối với lần duyệt định nghĩa mới                          | công cụ MCP đi qua máy giai đoạn (D:mcp-client:R3.4, quyết 23/10/2026); mcp-client là W2                                                                           | agent-lifecycle; mcp-client, đợt sau (W2)         |
| W3: công tắc theo workspace, kết nối, tuyến model; nhà vận hành tắt một agent; mô phỏng nhiều lượt                                                                    | v1.5 trở đi                                                                                                                                                        | agent-lifecycle, đợt sau (W3)                     |
| Vỏ phiên bản, băm RFC 8785 (`dw_kernel.canonical`), bản kê định nghĩa và Nơi đang dùng                                                                                | ADR-0109 (Accepted); đã có                                                                                                                                         | tenant-config                                     |
| Bảng phiên bản agent và quy trình, trình soạn, canvas; chế độ chạy, hàng đợi, lịch, Data Hub                                                                          | spec này chỉ đặt hợp đồng cột vòng đời và hợp đồng cửa                                                                                                             | agent-builder, workflow-engine, workflow-triggers |
| Sổ sử dụng, lease, hạn mức theo phạm vi                                                                                                                               | spec này xin lease `purpose` `eval_offline` qua `LimitsPort` cho Lượt kiểm định (DO-21.4)                                                                          | usage-and-limits                                  |
| Danh mục quyền, vai trò, độ sâu workspace; phân loại công cụ, ghim định nghĩa MCP                                                                                     | spec này chỉ đề xuất tên quyền và đọc phân loại, sự kiện                                                                                                           | tenant-rbac; tools-and-skills; mcp-client         |

## Dữ liệu

Mọi bảng mới: RLS ENABLE và FORCE theo tenant, grant cùng migration, tên ràng buộc theo
`NAMING_CONVENTION`, revision id hex ngẫu nhiên.

- Cột vòng đời thêm trên `studio.artifact_versions` (vỏ chung của tenant-config, ADR-0109 (Accepted)
  quyết 2; DO-05 chọn vỏ chung): `gate_run_id uuid` NULL, FK `studio.gate_runs` ON DELETE RESTRICT,
  bắt buộc khi `stage IN ('awaiting_approval','live','retired')` với loại có Cổng chất lượng, luôn NULL
  với loại mà sổ loại `studio.artifact_kinds` ghi là không có cổng (R1.6); `publish_approval_id uuid` NULL, FK
  `platform.approval_requests` ON DELETE RESTRICT, bắt buộc khi `stage IN ('awaiting_approval','live','retired')`;
  `contributor_ids uuid[] NOT NULL CHECK (cardinality(contributor_ids) >= 1)`; `submitted_by`,
  `submitted_at`, `published_by`, `published_at`, `retired_by`, `retired_at`; `retire_reason_code`
  CHECK (`superseded`, `explicit`); `stage_changed_at timestamptz NOT NULL`. Trigger
  `studio.guard_version_stage()` (BEFORE INSERT OR UPDATE) cho đúng các chuyển tiếp của R1 và chặn đổi
  nội dung ngoài `draft`; chỉ mục một Đang dùng (`WHERE stage='live'`), một Bản ứng viên
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
  (`lifted_by, lifted_at, lift_reason, lift_approval_id`). Mỗi lần đặt hay gỡ một công tắc `kill` ghi
  outbox `control.switch.changed` v1 chỉ id trong cùng giao dịch; lane `control_switch` nghe sự kiện đó.
- `platform.platform_freezes` (mặt danh tính, không tenant): tối đa một dòng mở; `dw_app` chỉ SELECT;
  do `dw_provisioner` ghi, audit trong `platform.provisioning_audit`.
- `studio.gate_runs`: `status` CHECK (`queued`, `running`, `passed`, `failed`, `error`, `cancelled`);
  `purpose` CHECK (`gate`, `dry`); khóa bằng chứng (`effective_hash`, `gate_policy_ref`,
  `security_suite_ref`, danh sách mã băm bộ đề của tenant, rỗng ở W1); `definition_hash` cho trigger giai
  đoạn; `spend_cap_usd`, `spent_usd`, `resolved_at_gate` jsonb,
  `verdict` jsonb. `studio.gate_run_datasets` là W2 cùng bộ đề của tenant. `studio.gate_case_results`:
  phân vùng theo tháng với DEFAULT, đăng ký bằng một dòng `platform.time_partitioned_tables`
  (`append_only = true`, studio-skeleton:R3.1); ENABLE/FORCE RLS và policy tenant trên cha và DEFAULT cùng
  migration; `dw_app` không giữ quyền nào trên partition nào, kể cả DEFAULT, và đọc ghi qua bảng cha.

## API

- `POST /api/v1/studio/{agents|workflows}/{artifact_id}/versions/{version_id}/submit`,
  `POST .../withdraw`, `POST .../retire` (`studio.versions.submit`, `studio.versions.retire`;
  `Idempotency-Key`).
- `POST .../versions/{version_id}/dry-evaluations` (`studio.eval.run`);
  `GET /api/v1/studio/gate-runs`, `/{id}`, `/{id}/cases` (`studio.lifecycle.read`).
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
  `control_state_unavailable`, `principal_inactive`, `cost_bound`, `limit_exceeded`, `artifact_in_use`;
  route gửi kiểm định trả thêm mã 422 của kiểm theo loại do spec chủ kiểm quyết (`capability_trifecta_autonomy`,
  `tool_unclassified`, `trifecta_path_unapproved`, `residency_refused` của compliance-pdpl).

## Kiểm soát

| #    | Kiểm soát                                                                    | Yêu cầu                      | Test âm                                                                                                                                                                                                                                                                                                                                                                    |
| ---- | ---------------------------------------------------------------------------- | ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AL1  | Máy trạng thái thuộc database                                                | R1.1                         | `dw_app` UPDATE `draft → live` trực tiếp → 23514 `ck_artifact_versions_stage_transition`; gỡ trigger → test đỏ                                                                                                                                                                                                                                                             |
| AL2  | Một Đang dùng, một Bản ứng viên                                              | R1.2, R1.3                   | Hai lần gửi kiểm định song song → một 202, một 409 `candidate_exists`; INSERT bản `live` thứ hai → lỗi chỉ mục; gỡ chỉ mục từng phần → test đỏ                                                                                                                                                                                                                             |
| AL3  | Bao đóng và Nơi đang dùng ghi cùng giao dịch, khóa theo Mã băm định nghĩa    | R2.1, R2.2, R2.3             | Rollback giữa giao dịch gửi kiểm định → không bản kê, phụ thuộc hay audit; đổi phiên bản một công cụ ghim → Mã băm định nghĩa khác; bỏ một loại khỏi bao đóng → test đỏ                                                                                                                                                                                                    |
| AL4  | Đang dùng cần cổng đạt trên đúng Mã băm định nghĩa và approval đã duyệt      | R5.6                         | Chuyển `live` với `gate_run_id` của mã băm khác, hoặc approval còn `pending` → 23514; gỡ CHECK → test đỏ                                                                                                                                                                                                                                                                   |
| AL5  | Người duyệt không phải Tác giả, không phải người gửi                         | R5.1, R5.2, R5.3             | Người trong `contributor_ids` có scope duyệt → 409 `author_cannot_approve`; payload thiếu `author_ids` → từ chối; `author_ids` dựng thiếu một người trong `contributor_ids` hay `submitted_by` → test khớp đỏ; gỡ guard → test đỏ                                                                                                                                          |
| AL6  | Không vai nào thay tem `studio.publish.approve`                              | R5.4                         | `platform_admin` không giữ tem → 404 khi đọc và khi quyết định                                                                                                                                                                                                                                                                                                             |
| AL7  | Bộ kiểm định an ninh nền tảng 100%, `unknown` chặn như trượt, không sửa được | R4.1, R4.2                   | Một Câu an ninh trượt hoặc `unknown` → cổng trượt; không route nào ghi Câu an ninh (không phải dữ liệu tenant); gỡ luật trong `evaluate_gate` → test đỏ                                                                                                                                                                                                                    |
| AL8  | Kiểm định không gây tác động thật                                            | R4.3                         | Lượt kiểm định agent có công cụ gửi Zalo → egress giả không nhận lời gọi nào; gỡ chặn `simulate` ở executor → test đỏ                                                                                                                                                                                                                                                      |
| AL9  | Trần chi phí trước lời gọi đầu, trần riêng mỗi lần thử                       | R4.4, R4.5                   | Chi phí xấu nhất vượt trần lượt, hoặc `LimitsPort` từ chối lease `eval_offline` → Lượt kiểm định `error` `limit_exceeded`, không `worker_runs` nào; một lần thử chạm trần → Câu trượt `cost_bound`, các câu khác vẫn chấm; gỡ trần lần thử → test đỏ                                                                                                                       |
| AL10 | Phiên bản chưa qua kiểm theo loại hay Phân tích năng lực không lên Chờ duyệt | R2.7, R6.1, R6.2, R6.3       | Đăng ký một kiểm từ chối cho loại `workflow` → gửi kiểm định 422, phiên bản vẫn Nháp; `dw_app` ghi thẳng một Bản ứng viên không có kết quả Phân tích năng lực sang Đang kiểm định → cổng trượt, không yêu cầu phê duyệt nào; gỡ đọc kết quả ở lane → yêu cầu phê duyệt mở (đỏ)                                                                                             |
| AL11 | Đóng băng chặn ở mọi cửa, đóng khi lỗi                                       | R7.1, R7.3, R7.7, R7.8, R7.9 | Đặt đóng băng giữa run: mỗi cửa trong 6 cửa của R7.1 từ chối lời gọi kế tiếp, run `cancelled`; lượt `chat` tới cửa nhận → `cancelled` `tenant_frozen`, 0 lời gọi model; lượt `datahub` đã xếp hàng vẫn `queued` và chạy sau khi gỡ; gửi kiểm định → 409; cache quá 30 giây không làm mới → lời gọi công cụ `control_state_unavailable`; gỡ kiểm ở một cửa → test cửa đó đỏ |
| AL12 | Tenant không gỡ Đóng băng của nhà vận hành                                   | R7.4, R7.5                   | `POST /api/v1/admin/unfreeze` khi `origin='platform'` → 403; `dw_app` UPDATE gỡ trực tiếp → 23514                                                                                                                                                                                                                                                                          |
| AL13 | Tắt khẩn cấp hủy việc đang chờ                                               | R8.2, R8.3                   | Run `waiting_approval` của thành phần → `cancelled`, approval `cancelled`; quyết định đến sau → 409, không resume; gỡ lane → test đỏ                                                                                                                                                                                                                                       |
| AL14 | Bật lại cần người thứ hai                                                    | R8.6, R8.7                   | Người xin bật lại tự duyệt `studio.lifecycle.revive` → 409, công tắc không gỡ                                                                                                                                                                                                                                                                                              |
| AL15 | Tắt khẩn cấp chặn gửi đã xếp hàng và agent liên kết                          | R8.4, R8.5                   | Tắt sau khi tin Zalo xếp hàng → lane gửi giả không gọi nhà cung cấp (đường gửi thật: marketing-pilot:R6.4); agent liên kết bị tắt → stack con từ chối                                                                                                                                                                                                                      |
| AL16 | Cách ly tenant của công tắc                                                  | R7.1, R8.1                   | Đóng băng, tắt của tenant A không chạm run của tenant B; đọc công tắc của B từ A → 404; gỡ FORCE RLS → `test_rls_coverage.py` đỏ                                                                                                                                                                                                                                           |
| AL17 | Chủ thể không active không chạy tiếp                                         | R9.1                         | Gỡ thành viên khỏi công ty rồi tiếp tục lượt chạy chờ duyệt của người đó → `cancelled` `principal_inactive`, 0 lời gọi model; đặt `suspended` bằng SQL rồi nhận lượt mới → như trên; gỡ kiểm ở `require_open` → test đỏ                                                                                                                                                    |
| AL18 | Gỡ Đóng băng của công ty cần người thứ hai                                   | R7.10, R7.11                 | Người xin gỡ tự duyệt `studio.lifecycle.unfreeze` → 409, Đóng băng còn; người khác duyệt → gỡ; gỡ luật nghiêm của `studio.lifecycle.` → test đỏ                                                                                                                                                                                                                            |

## Tiêu chí xong

- Mọi tiêu chí R và G có test; mọi kiểm soát có test âm đã thấy đỏ khi gỡ kiểm soát (ghi ở Comments của
  ticket).
- `make ci && make test-integration` xanh; `reviewing-feature-security` và `reviewing-deployment-security`
  đã chạy trên từng ticket có route, migration hay lane; `.claude/plans/studio.md` ghi lát W1 đã xong.

## Phụ thuộc

- tenant-config: vỏ `studio.artifact_versions` với cột `stage` (CHECK năm giai đoạn, không DEFAULT),
  bước niêm phong và sổ loại `studio.artifact_kinds` cho luật theo loại của R1.6
  (`.claude/plans/studio/tenant-config/issues/02-vo-phien-ban-va-chi-muc-phu-thuoc.md`);
  băm `dw_kernel.canonical` (`.claude/plans/studio/tenant-config/issues/01-bam-chuan-hoa-jcs.md`); chế
  độ `simulate` chặn tác động ở executor (tenant-config:R5.1,
  `.claude/plans/studio/tenant-config/issues/03-che-do-chay-va-gia-lap-o-executor.md`); bản kê lượt chạy
  ghim phiên bản (`.claude/plans/studio/tenant-config/issues/04-ban-ke-luot-chay.md`).
- studio-skeleton: gói `dw_studio`, nhóm route `/api/v1/studio`, schema `studio`
  (`.claude/plans/studio/studio-skeleton/issues/02-goi-dw-studio-va-seam-api.md`,
  `.claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md`).
- tenant-rbac: danh mục quyền là một chủ (tenant-rbac:R1.1) — các tên quyền `studio.versions.submit`,
  `studio.versions.retire`, `studio.publish.approve`, `studio.lifecycle.read`, `studio.lifecycle.freeze`,
  `studio.lifecycle.kill`, `studio.lifecycle.revive`, `studio.eval.run` đăng ký ở
  `.claude/plans/studio/tenant-rbac/issues/01-mot-chu-cho-quyen.md`.
- Protocol do bên dùng khai: `RunControlPort` và `RunHaltedError` (runtime khai, spec này đáp ứng bằng
  `SqlRunControl`, đọc trạng thái thành viên của org-and-principals cho `principal_inactive`); `ClosureExtractor`
  theo loại (agent-builder, workflow-engine cung cấp); bảng kiểm theo loại lúc gửi kiểm định (spec này khai;
  Phân tích năng lực của
  `.claude/plans/studio/compliance-pdpl/issues/05-phan-tich-bo-ba-khi-xuat-ban.md` và kiểm workflow-nodes:R9.5
  đăng ký vào); `LimitsPort` cho lease `eval_offline` của Lượt kiểm định (runtime khai, `dw_usage` đáp;
  `.claude/plans/studio/usage-and-limits/issues/03-han-muc-giu-truoc-va-quyet-toan.md`); làn `studio_inbound`
  của workflow-triggers giữ và xin lại sự kiện đã giữ (workflow-triggers:R1.3); làn `studio_runs` thi hành
  cửa nhận theo `trigger_kind` (`.claude/plans/studio/workflow-engine/issues/04-lan-studio-runs.md`); lane gửi
  đi kiểm công tắc trước khi gửi (`.claude/plans/studio/connections-and-vault`).
- Hai ghim cho một lượt chạy Studio: release manifest ghim lớp nền tảng, Bản kê lượt chạy ghim phần Studio
  với Mã băm định nghĩa của gốc; ADR-0109 (Accepted) và ADR-0120 (Accepted) ghi điều đó, và `CLAUDE.md` mục
  'Non-negotiable architecture' sửa theo khi Đạt nhận hai ADR. Cache công tắc đóng khi lỗi, trái cache
  AccessContext mở khi lỗi (ADR-0024 (Proposed) quyết 4), có chủ ý.
- Kiểm lại khi: sổ loại của tenant-config đổi cờ có Cổng chất lượng → R1.6, ticket 03; danh mục quyền của
  tenant-rbac đổi tên → R5, R7, R8; phân loại công cụ của tools-and-skills đổi enum → R6; hợp đồng
  `RunControlPort` đổi hình → R7, R8, R9, ticket 01; hợp đồng `LimitsPort` đổi → R4.4, R4.5, ticket 04;
  workflow-triggers đổi làn `studio_inbound` → R7.2; compliance-pdpl đổi chỗ ghi kết quả Phân tích năng lực
  → R6, ticket 04.

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

## Danh sách ticket

| #   | Ticket                                                                                                  |
| --- | ------------------------------------------------------------------------------------------------------- |
| 01  | [Đóng băng toàn nền tảng và theo tenant, kiểm ở mọi cửa](issues/01-dong-bang-va-kiem-o-moi-cua.md)      |
| 02  | [Mở rộng dw_evals: quan sát, bộ chấm, JudgePort, lặp, cổng thuần](issues/02-mo-rong-dw-evals.md)        |
| 03  | [Hợp đồng vòng đời phiên bản và gửi kiểm định niêm phong](issues/03-hop-dong-vong-doi-va-niem-phong.md) |
| 04  | [Cổng chất lượng mô phỏng và duyệt phát hành hai người](issues/04-cong-kiem-dinh-va-duyet-hai-nguoi.md) |
| 05  | [Tắt khẩn cấp agent và quy trình, bật lại hai người](issues/05-tat-khan-cap-va-khoi-phuc.md)            |
