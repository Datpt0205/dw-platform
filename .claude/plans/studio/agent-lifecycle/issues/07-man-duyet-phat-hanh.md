# 07 — Màn duyệt phát hành: Sơ đồ chỉ đọc với lớp phần khác, kết quả cổng và chi phí ước tính

Status: needs-triage
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
   các kiểm và ca 404 của route đó, không route mới và không audit thứ hai (spec R5.11, R5.12): `live_document`, tài liệu
   niêm phong của phiên bản Đang dùng mà Bản ứng viên sẽ thay (NULL khi `live_version_id` NULL); `gate`, NULL với loại có
   `has_quality_gate = false`, còn lại là tóm tắt của Lượt kiểm định mà `gate_run_id` của Bản ứng viên trỏ tới, đọc từ
   `studio.gate_runs` và `studio.gate_case_results` của ticket 06: `status`, số Câu an ninh đạt trên tổng, mỗi ca kịch bản
   `{case_id, name, passed, reason_code}` (`name` từ `studio.workflow_scenarios`, NULL khi ca đã bị xóa sau Lượt kiểm
   định), `spent_usd`, và `estimated_run_cost_usd` là trung bình `cost_usd` của các ca kịch bản của Lượt kiểm định kèm số
   ca tính, NULL khi không có ca nào; `closure_changes[]`, phần khác của bao đóng đã ghim giữa Bản ứng viên và bản Đang
   dùng, đọc từ chỉ mục phụ thuộc `studio.dependencies` của tenant-config/02 cho hai phiên bản: mỗi phần tử
   `{kind, artifact_id, name, before_version_no, after_version_no}` cho một phụ thuộc thêm (`before` NULL), bỏ (`after`
   NULL) hay đổi phiên bản ghim (Quy trình con, công cụ, Bộ công cụ, đối tượng), mọi phụ thuộc là thêm khi chưa có bản
   Đang dùng. Route không mở `GET /api/v1/studio/gate-runs` cho người duyệt: chỉ Lượt kiểm định của chính Bản ứng viên,
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
   ở inbox `/approvals`, và điểm cắm `apps/web/components/tool-approval.tsx` có liên kết "Xem diff" mở trang này cho mọi
   yêu cầu `studio.publish.*` (thay câu "mở route của bước 9" cũ của ticket 04).
3. Sơ đồ chỉ đọc (spec R5.14, R5.16; workflow-builder-ui:R3.16-R3.20): một thành phần client
   `apps/web/app/studio/publish-approvals/[approvalId]/canvas/review-diagram.tsx`, dưới glob
   `apps/web/app/studio/**/canvas/**` của ADR-0101 (Accepted) quyết 1, nạp bằng `next/dynamic` với `ssr: false`, dựng Sơ
   đồ chỉ đọc và lớp phần khác của workflow-builder-ui/03 (bước 7, 9 của ticket đó) với tài liệu của Bản ứng viên và đúng
   một trong ba giá trị so mà trang tính, không giá trị nào suy từ giá trị khác: tài liệu `live_document` khi nó qua mô
   hình `dw.workflow/v1`; "chưa có bản Đang dùng" khi `live_version_id` NULL; "đọc lỗi" khi `live_version_id` khác NULL mà
   `live_document` vắng hay không qua mô hình. Trang không bao giờ đưa một cây rỗng hay "chưa có bản Đang dùng" thay cho
   "đọc lỗi". Sơ đồ của màn không có ô chèn, kéo, nối, phím sửa hay gọi API ghi nào; mọi thao tác vốn sửa ở builder (thả
   một Bước, phím xóa, dán) không gửi lệnh lưu Nháp nào (ADR-0101 (Accepted) Consequences).
4. Phần khác của bao đóng (spec R5.15): khối của bước 2 nêu mỗi phần tử `closure_changes[]`, vì lớp phần khác của Sơ đồ
   chỉ so tài liệu theo id Bước và khóa cấp đầu (workflow-builder-ui:R3.20), nên một Quy trình con hay công cụ đã ghim mà
   đổi phiên bản trong khi tài liệu giữ nguyên `ref` không hiện thẻ nào trên Sơ đồ.
5. Đo first-load JS của route `/studio/publish-approvals/[approvalId]` riêng, như của builder (ADR-0101 (Accepted)
   Consequences): `next build` in số của route, ghi vào mục Quyết định của spec này và vào ADR-0101 (Accepted); ngân sách
   khoảng 250 kB của antd (`CLAUDE.md`, Web UI) không phủ nó.

## Tiêu chí chấp nhận

- [ ] R5.13: người được quyết định một yêu cầu `studio.publish.workflow` còn `pending` mở trang → Sơ đồ chỉ đọc có thẻ
      "Mới" ở Bước thêm và "Đã sửa" ở Bước đổi ngưỡng, khối kết quả cổng nêu Câu an ninh đạt trên tổng và sáu ca kịch bản
      đạt, chi phí ước tính bằng trung bình `cost_usd` của sáu ca; với một yêu cầu `studio.publish.object` → bảng
      `changes[]` và câu "Loại này không qua Cổng chất lượng", không Sơ đồ; HTML do server trả cho trang không chứa mã của
      `@xyflow/react` (nạp `ssr: false`), và số first-load JS của route có ở mục Quyết định của spec.
- [ ] R5.14 (AL34): câu trả lời có `live_version_id` mà `live_document` không qua mô hình `dw.workflow/v1` → Sơ đồ nêu
      "Không so được với bản Đang dùng", không thẻ phần khác nào; `live_version_id` NULL → mọi Bước "Mới"; câu trả lời
      lỗi 500 → `Result` lỗi, không Sơ đồ, không thẻ, không câu "không có phần khác"; đưa cây rỗng hay "chưa có bản Đang
      dùng" khi đọc lỗi → test đỏ.
- [ ] R5.15 (AL34): Bản ứng viên ghim công cụ X phiên bản 3 và một Quy trình con mới, bản Đang dùng ghim X phiên bản 2,
      tài liệu giống hệt ngoài phiên bản ghim → Sơ đồ không thẻ nào, `closure_changes[]` và khối bao đóng nêu X 2 → 3 và
      Quy trình con thêm; chưa có bản Đang dùng → mọi phụ thuộc là thêm; bỏ `closure_changes[]` khỏi route hay khối khỏi
      trang → test đỏ.
- [ ] R5.16 (AL35): trên Sơ đồ của màn, thả một Bước từ bảng loại, nhấn phím xóa trên một Bước đã chọn và dán → 0 yêu cầu
      tới mọi route ghi (bộ chặn mạng của test đếm), tài liệu hiển thị không đổi; bật bộ xử lý sửa của builder cho Sơ đồ
      của màn → test đếm đỏ.
- [ ] R5.11 (AL25): người được quyết định gọi route khi yêu cầu `pending` → 200 với `live_document`, `gate`,
      `closure_changes[]` thêm vào câu trả lời cũ, đúng một audit `studio.version.candidate_read`; ghi audit thứ hai cho
      phần thêm → test đếm audit đỏ.
- [ ] R5.12 (AL25): người xin không giữ tem, người chỉ giữ `studio.lifecycle.read`, và người giữ tem sau khi yêu cầu đã
      quyết → 404, thân không chứa `gate`, `live_document` hay `closure_changes`; trang của họ hiện "Không tìm thấy yêu
      cầu"; người của tenant B dùng id của tenant A → 404; đọc phần thêm trước kiểm `pending` và kiểm tem → test đỏ.
- [ ] Xong: `make ci && make test-integration && pnpm --filter web test:e2e -- publish-review` xanh.

## Nguồn

- `apps/web/components/tool-approval.tsx:107`; spec: R5.13 (điểm cắm của inbox `/approvals` nhận liên kết tới màn).
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
