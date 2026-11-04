# 07 — Màn duyệt phát hành: Sơ đồ chỉ đọc với lớp phần khác, kết quả cổng và chi phí ước tính

Status: ready-for-agent
Blocked by: 06, .claude/plans/studio/workflow-builder-ui/issues/03-bieu-thuc-publish-va-chay-thu.md
Area: studio
Yêu cầu: R5.11, R5.12, R5.13, R5.14, R5.15, R5.16, AL25, AL34, AL35

## Mục tiêu

Người được quyết định một yêu cầu phê duyệt phát hành thấy, trước khi quyết ở inbox `/approvals`, một màn duyệt: với
quy trình là Sơ đồ chỉ đọc của Bản ứng viên với lớp phần khác so với bản Đang dùng của workflow-builder-ui
(workflow-builder-ui:R3.16-R3.20, BU17), với loại khác là bảng `changes[]`; kết quả Cổng chất lượng; chi phí ước tính; và
phần khác của bao đóng đã ghim, mà lớp phần khác của Sơ đồ không thấy (spec R5.13-R5.16; YC116; V4.37). Màn nằm dưới glob
canvas của ADR-0101 (Accepted) quyết 1, chỉ đọc, và đọc qua route Bản ứng viên của ticket 04, nên ai không được quyết
định yêu cầu thì không thấy gì (spec R5.12).

## Việc cần làm

1. Câu trả lời của `GET /api/v1/studio/publish-approvals/{approval_id}/candidate` (ticket 04, bước 5) thêm, dưới đúng
   các kiểm và ca 404 của route đó, không route mới và không audit thứ hai (spec R5.11, R5.12): `artifact` (`kind`,
   `api_name`), `requested_by` và `submitted_at` cho đầu trang, vì người duyệt có thể không giữ khóa đọc của loại để gọi
   route thành phần của tenant-config; `live_document`, tài liệu
   niêm phong của phiên bản mà Bản ứng viên đã so lúc gửi, tức phiên bản có `definition_hash` bằng `compared_live_hash`
   của Bản ứng viên (NULL khi `compared_live_hash` NULL), vì đó là bản mà handler phát hành sẽ so; `base_changed`
   (bool), true khi bản Đang dùng lúc đọc khác bản đó, để màn cảnh báo "Bản Đang dùng đã đổi từ lúc gửi; duyệt sẽ trả
   Bản ứng viên về Nháp" (spec R5.9); với loại `workflow`, `compare_status`, một trong ba giá trị mà workflow-builder-ui/03
   bước 9 đặt tên, do máy chủ quyết, không trang nào suy ra: `no_live` khi `compared_live_hash` NULL, `live` khi
   `live_document` đọc được và parse được thành `WorkflowDocument` (`dw_agent_runtime/wflite/document.py:63`) với mọi
   Loại bước có trong sổ loại Bước mà builder dùng (sổ hiện tại, gồm loại Bước Studio), `read_error` khi tài liệu vắng,
   không parse được hay có một Loại bước vắng sổ; và `step_changes[]`, `section_changes[]`, đầu ra của `diff_steps`
   (`wflite/outline.py:164`) trên `steps` của hai tài liệu với cùng sổ đó, và của `diff_sections` mà workflow-builder-ui/03
   thêm, chỉ khi `compare_status` là `live`, NULL ở hai giá trị kia, vì `diff_steps` bỏ qua im lặng Bước nó không đặt
   được (`outline.py:127-138`) và không bao giờ báo lỗi; `gate`, NULL với loại có
   `has_quality_gate = false`, còn lại là tóm tắt của Lượt kiểm định mà `gate_run_id` của Bản ứng viên trỏ tới, đọc từ
   `studio.gate_runs` và `studio.gate_case_results` của ticket 06, và khi Lượt đó dùng lại bằng chứng
   (`reused_from_gate_run_id`), kết quả từng câu và chi phí đọc từ Lượt nguồn, kèm `reused_from_gate_run_id` để màn ghi
   "Dùng lại kết quả của lần kiểm định trước"; `status`, số Câu an ninh đạt trên tổng (dòng có `category` khác
   `scenario`, một dòng mỗi câu, `cost_usd` là tổng mọi lần thử của câu), mỗi ca kịch bản
   `{case_id, name, passed, reason_code}` (`name` từ `studio.workflow_scenarios`, NULL khi ca đã bị xóa sau Lượt kiểm
   định), `spent_usd`, và `estimated_run_cost_usd` là trung bình `cost_usd` của các ca kịch bản của Lượt kiểm định kèm số
   ca tính, NULL khi không có ca nào; `closure_changes[]`, phần khác của bao đóng đã ghim giữa Bản ứng viên và bản Đang
   dùng, đọc từ chỉ mục phụ thuộc `studio.dependencies` của tenant-config/02 cho hai phiên bản
   (`db/migrations/versions/67071483caa6_studio_artifact_envelope.py:163-203`): chỉ dòng `to_kind` `artifact` (Quy trình
   con, đối tượng, và ở W2 công cụ, Bộ công cụ của tenant) và `platform_artifact` (công cụ, Bộ công cụ nền tảng của W1),
   gộp mọi dòng cùng đích (cùng `to_kind` và `to_artifact_id`, hay `to_key` với `platform_artifact`) bất kể `path` và
   `usage`; mỗi phần tử `{to_kind, kind, artifact_id, key, name, before_version, after_version}`: với `artifact`,
   `artifact_id` là `to_artifact_id`, `kind` và `name` (`api_name`) nối từ `studio.artifacts`, phiên bản là `version_no`
   nối từ `to_version_id`; với `platform_artifact`, bước niêm phong không ghi `to_version` (`service.py:605-607`) và
   khóa mang phiên bản (`studio.agent_frame@1.0.0`), nên route tách `to_key` ở dấu `@` cuối: `key` và `name` là phần
   trước, phiên bản là phần sau, và "cùng đích" là cùng `key`; `artifact_id` NULL, `kind` NULL; một phụ thuộc thêm (`before_version` NULL), bỏ (`after_version` NULL) hay đổi phiên bản ghim; mọi
   phụ thuộc là thêm khi chưa có bản Đang dùng; các `to_kind` khác (trường, kết nối, Điểm gắn, loại node) không có phiên
   bản ghim nên không vào khối này. Route không mở `GET /api/v1/studio/gate-runs` cho người duyệt: chỉ Lượt kiểm định của chính Bản ứng viên,
   chỉ khi yêu cầu còn `pending` (spec R4.10 không đổi).
2. Trang `apps/web/app/studio/publish-approvals/[approvalId]/page.tsx` (antd, `vi_VN`, thông báo qua `App.useApp()`, ngày
   qua `lib/dates.ts`, Tailwind chỉ cho bố cục): đầu trang (loại, tên, `version_no`, người xin, lúc gửi); khối "Kết quả
   Cổng chất lượng" (antd `Descriptions` và `Table`: Câu an ninh đạt trên tổng, mỗi ca kịch bản với `Tag` có chữ cùng biểu
   tượng và nhãn của `reason_code` từ catalog của telemetry-and-audit; "Loại này không qua Cổng chất lượng" khi `gate`
   NULL); khối "Chi phí ước tính" (antd `Statistic`: chi phí của Lượt kiểm định, chi phí ước tính mỗi lượt chạy kèm câu
   "ước tính từ N lần thử mô phỏng, không gồm Bước có kết quả ghim", "Chưa ước tính được" khi NULL); khối "Phần khác của
   bao đóng" (antd `Table` của `closure_changes[]`, câu "Không phiên bản ghim nào đổi" khi rỗng); và phần nội dung: với
   loại `workflow` là Sơ đồ chỉ đọc của bước 3, với loại khác là antd `Table` của `changes[]` (`path`, trước, sau). Câu
   trả lời 404 → antd `Result` "Không tìm thấy yêu cầu" như mọi id không tồn tại; lỗi khác (mạng, 5xx) → `Result` lỗi
   với nút thử lại, không Sơ đồ, không khối nào nói "không có phần khác". Trang không có nút quyết định: người duyệt quyết
   ở inbox `/approvals`. Liên kết "Xem diff" đi qua cửa theo loại có sẵn, `CARDS` của
   `apps/web/app/approvals/page.tsx:40-51` ("one entry per type"): bốn mục `studio.publish.agent`, `.workflow`, `.object`,
   `.endpoint` trỏ một thành phần `PublishApprovalCard`, vẽ như thẻ chung cộng liên kết; không phép thử tiền tố thứ hai
   và không sửa `ToolApprovalPayload` (nó trả `null` khi payload không có hàng nào, `tool-approval.tsx:113`). Liên kết
   chỉ hiện khi `approval.status` là `pending`, `approval.can_decide` của chính mục là true (không `hasScope` của cả
   trang) và người xem không nằm trong `payload.author_ids` (route loại người xin và Tác giả dù `may_decide` không xét
   họ, `approval_flow.py:128-137`); ẩn liên kết chỉ là tiện dụng, route vẫn là bên chặn.
3. Sơ đồ chỉ đọc (spec R5.14, R5.16; workflow-builder-ui:R3.16-R3.20): một thành phần client
   `apps/web/app/studio/publish-approvals/[approvalId]/canvas/review-diagram.tsx`, dưới glob
   `apps/web/app/studio/**/canvas/**` của ADR-0101 (Accepted) quyết 1, nạp bằng `next/dynamic` với `ssr: false`, dựng Sơ
   đồ chỉ đọc và lớp phần khác của workflow-builder-ui/03 (bước 7, 9 của ticket đó) với tài liệu của Bản ứng viên,
   `step_changes[]` và `section_changes[]` của bước 1, và đúng một trong ba giá trị so mà trang tính, không giá trị nào
   suy từ giá trị khác: `compare_status` của bước 1 chuyển nguyên (`live` cùng `live_document`, `no_live` "chưa có bản
   Đang dùng", `read_error` "đọc lỗi"); trang không tự kiểm tài liệu hay đoán trạng thái từ một trường NULL. Trang không bao giờ đưa một cây rỗng hay "chưa có bản Đang dùng" thay cho
   "đọc lỗi". Sơ đồ của màn không có ô chèn, kéo, nối, phím sửa hay gọi API ghi nào; mọi thao tác vốn sửa ở builder (thả
   một Bước, phím xóa, dán) không gửi lệnh lưu Nháp nào (ADR-0101 (Accepted) Consequences).
4. Phần khác của bao đóng (spec R5.15): khối của bước 2 nêu mỗi phần tử `closure_changes[]`, vì lớp phần khác của Sơ đồ
   chỉ so tài liệu theo id Bước và khóa cấp đầu (workflow-builder-ui:R3.20), nên một Quy trình con hay công cụ đã ghim mà
   đổi phiên bản trong khi tài liệu giữ nguyên `ref` không hiện thẻ nào trên Sơ đồ.
5. Đo first-load JS của route `/studio/publish-approvals/[approvalId]` riêng, như của builder, theo cách mà
   ADR-0101 (Accepted), sửa đổi 2026-11-03 (`docs/adr/0101-studio-canvas-is-an-allowlisted-ui-exception.md:307-309`)
   đặt: gzip của mọi chunk nạp tới khi thẻ đầu tiên của Sơ đồ vẽ xong, đo trong trình duyệt, vì cột "First Load JS" của
   `next build` không đếm chunk `next/dynamic`; ghi số vào mục Quyết định của spec này và vào ADR-0101 (Accepted); ngân
   sách khoảng 250 kB của antd (`CLAUDE.md`, Web UI) không phủ nó.

## Tiêu chí chấp nhận

- [ ] R5.13: người được quyết định một yêu cầu `studio.publish.workflow` còn `pending` mở trang → Sơ đồ chỉ đọc có thẻ
      "Mới" ở Bước thêm và "Đã sửa" ở Bước đổi ngưỡng, khối kết quả cổng nêu Câu an ninh đạt trên tổng và sáu ca kịch bản
      đạt, chi phí ước tính bằng trung bình `cost_usd` của sáu ca; với một yêu cầu `studio.publish.object` → bảng
      `changes[]` và câu "Loại này không qua Cổng chất lượng", không Sơ đồ; HTML do server trả cho trang không chứa mã của
      `@xyflow/react` (nạp `ssr: false`), và số first-load JS của route có ở mục Quyết định của spec.
- [ ] R5.14 (AL34): bản đã so có một Bước của Loại bước vắng sổ, hay tài liệu không parse được → route trả
      `compare_status` `read_error`, `step_changes` NULL, Sơ đồ nêu "Không so được với bản Đang dùng", không thẻ phần
      khác nào; `compared_live_hash` NULL → `no_live`, mọi Bước "Mới"; bản Đang dùng bị gỡ sau lúc gửi → `live_document`
      vẫn là bản đã so và `base_changed` true, màn hiện cảnh báo; trang tự suy trạng thái từ `live_document` NULL → test
      đỏ; câu trả lời
      lỗi 500 → `Result` lỗi, không Sơ đồ, không thẻ, không câu "không có phần khác"; đưa cây rỗng hay "chưa có bản Đang
      dùng" khi đọc lỗi → test đỏ.
- [ ] R5.15 (AL34): Bản ứng viên ghim công cụ X phiên bản 3 và một Quy trình con mới, bản Đang dùng ghim X phiên bản 2,
      tài liệu giống hệt ngoài phiên bản ghim → Sơ đồ không thẻ nào, `closure_changes[]` và khối bao đóng nêu X 2 → 3 và
      Quy trình con thêm; một công cụ nền tảng (`platform_artifact`) đổi phiên bản → nêu với `key`; một Quy trình con dùng
      ở hai Bước → một phần tử; một Bản ứng viên dùng lại bằng chứng → khối cổng nêu kết quả của Lượt nguồn và dòng "Dùng
      lại"; liên kết "Xem diff" vắng ở mục đã quyết và ở mục của người xin; chưa có bản Đang dùng → mọi phụ thuộc là thêm; bỏ `closure_changes[]` khỏi route hay khối khỏi
      trang → test đỏ.
- [ ] R5.16 (AL35): trên Sơ đồ của màn (không có bảng Loại bước), kéo một Bước, nhấn phím xóa trên một Bước đã chọn và dán → 0 yêu cầu
      tới mọi route ghi (bộ chặn mạng của test đếm), tài liệu hiển thị không đổi; bật bộ xử lý sửa của builder cho Sơ đồ
      của màn → test đếm đỏ.
- [ ] R5.11 (AL25): người được quyết định gọi route khi yêu cầu `pending` → 200 với `live_document`, `gate`,
      `closure_changes[]` thêm vào câu trả lời cũ, đúng một audit `studio.version.candidate_read`; ghi audit thứ hai cho
      phần thêm → test đếm audit đỏ.
- [ ] R5.12 (AL25): người xin không giữ tem, người chỉ giữ `studio.lifecycle.read`, và người giữ tem sau khi yêu cầu đã
      quyết → 404, thân không chứa `gate`, `live_document` hay `closure_changes`; trang của họ hiện "Không tìm thấy yêu
      cầu"; người của tenant B dùng id của tenant A → 404; đọc phần thêm trước kiểm `pending` và kiểm tem → test đỏ.
- [ ] Xong: `uv run python -m pytest apps/api/tests -k "candidate" && pnpm --filter web test:e2e -- publish-review` xanh.

## Nguồn

- `apps/web/components/tool-approval.tsx:107-128`, `apps/web/app/approvals/page.tsx:196`; spec: R5.13 (thẻ của
  inbox `/approvals` nhận liên kết tới màn qua prop mới).
- `docs/adr/0101-studio-canvas-is-an-allowlisted-ui-exception.md:64-72`; spec: R5.14, R5.16 (route thứ hai của canvas,
  `next/dynamic` với `ssr: false`, Sơ đồ chỉ đọc không gửi lệnh lưu).
- spec: R5.11-R5.16; workflow-builder-ui:R3.16-R3.20, BU17; ADR-0101 (Accepted) quyết 1; ADR-0120 (Accepted) quyết 2;
  YC116; V4.37.

## Comments

- 2026-10-26 (agent): lượt h, đợt 2, ticket mới theo V4.37 của Đạt và bảng ticket của lượt h: màn duyệt W1 có Sơ đồ chỉ
  đọc với lớp phần khác của workflow-builder-ui/03, kết quả cổng của ticket 06 và chi phí ước tính, dưới glob canvas của
  ADR-0101 (Accepted) quyết 1; route đọc là route của ticket 04 (V4.23), ticket này thêm phần mà màn đọc vào câu trả lời,
  nên không có cửa đọc thứ hai. Phần khác của bao đóng đã ghim do ticket này tự nêu, vì lớp phần khác của
  workflow-builder-ui chỉ so tài liệu theo id Bước và khóa cấp đầu (workflow-builder-ui:R3.20).
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness trên `72fd22a` (builder check trong một subagent, không boundary walk: ticket không thêm migration hay route mới, chỉ thêm trường vào câu trả lời của route của ticket 04 dưới đúng các kiểm của nó; đối chiếu `wflite/outline.py`, `wflite/document.py`, `tool-approval.tsx`, migration của vỏ, ADR-0101 (Accepted) và workflow-builder-ui/03; lượt xác nhận ngữ cảnh mới sau các sửa), 0 CRITICAL và 7 HIGH đã sửa theo khuyến nghị; giữ `step_changes[]`, `section_changes[]` của `baa6f48`. HIGH: (1) "qua mô hình" do máy chủ quyết bằng `compare_status` ba giá trị của workflow-builder-ui/03, parse thành `WorkflowDocument` với sổ loại Bước hiện tại, vì `diff_steps` không bao giờ báo lỗi; (2) `closure_changes[]` chỉ từ dòng `artifact` và `platform_artifact`, gộp theo đích, tên và phiên bản nối từ bảng, công cụ nền tảng có `key`; (3) bản để so là bản có `compared_live_hash`, kèm `base_changed`; (4) Lượt dùng lại bằng chứng đọc kết quả từ Lượt nguồn; (5) Câu an ninh là dòng khác `scenario`, một dòng mỗi câu; (6) "Xem diff" qua prop mới, chỉ khi `pending` và `canDecide`; (7) đo bundle theo sửa đổi 2026-11-03 của ADR-0101 (Accepted). Nếu sai thì: (1) trang tự parse tài liệu; (3) so với bản Đang dùng lúc đọc; (6) liên kết hiện cho mọi yêu cầu phát hành.
- 2026-11-04 (agent): MEDIUM để lại: agent không có ca kịch bản nên không bao giờ có chi phí ước tính ("Chưa ước tính được") ở W1.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (một subagent ngữ cảnh mới, mở đúng các tệp đã dẫn), 5 HIGH và 4 dẫn sai, đã sửa: (8) mọi khối so với cùng một bản, bản đã so lúc gửi (ticket 04 bước 5 và spec, API sửa theo); (9) hình `closure_changes[]` và `live_document` của spec theo ticket này; (10) công cụ nền tảng: `to_version` không được ghi, nên tách phiên bản khỏi `to_key`; (11) đầu trang lấy từ câu trả lời của route, không từ route thành phần; (12) liên kết qua `CARDS`, `can_decide` của mục và `author_ids`. Dẫn sai: `to_version` của `platform_artifact`; `can_decide` không xét người xin và Tác giả; `ToolApprovalPayload` trả `null`; phép thử tiền tố thứ hai thay cho `CARDS`. Một dòng kết quả mỗi câu sửa ở ticket 06. Nếu sai thì: (8) `changes[]` so với bản Đang dùng lúc đọc; (10) bước niêm phong ghi `to_version` cho `platform_artifact`.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
