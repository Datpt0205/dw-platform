# 06 — tool.call qua ToolExecutor và human.approval với quyền bắt buộc, khóa tham số

Status: needs-triage
Blocked by: 03, .claude/plans/studio/workflow-engine/issues/05-cho-nguoi-va-ghim-phien-ban.md, .claude/plans/studio/tools-and-skills/issues/02-toolset-va-cong-cu-ghim.md, .claude/plans/studio/compliance-pdpl/issues/04-san-gui-tin-marketing.md, .claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md, .claude/plans/studio/agent-lifecycle/issues/03-hop-dong-vong-doi-va-niem-phong.md
Area: studio
Yêu cầu: R8.1, R8.2, R8.3, R8.4, R9.1, R9.2, R9.3, R9.5, R9.6, R9.7, R9.8, R9.9, R9.10, R9.11, R9.12, R9.13, R9.14, R9.15, R9.16, R9.17, WN6, WN7, WN8, WN9, WN11, WN17, WN18, WN20, WN21, WN27

## Mục tiêu

Bước `tool.call` đi qua `ToolExecutor` với khoá chống lặp; Bước phê duyệt là cổng do máy chủ thực thi,
với quyền bắt buộc, người duyệt khác người tạo lượt, tham số đã duyệt đúng là tham số được gửi, và trong lượt
mô phỏng thì đi theo quyết định giả lập mà không chờ người, còn dòng giao và dòng phê duyệt của Bước không trỏ được
tới lượt chạy hay yêu cầu của công ty khác; mỗi kết quả của phê duyệt là một làn Bước, làn `approved` chỉ chạy khi
quyết định là duyệt, và Bước phê duyệt không bao giờ đi tiếp qua lỗi như đã có quyết định
(workflow-nodes R8.1, R8.2, R8.3, R8.4, R9.1, R9.2, R9.3, R9.5, R9.6, R9.7, R9.8, R9.9, R9.10, R9.11, R9.12, R9.13,
R9.14, R9.15, R9.16, R9.17, WN6, WN7, WN8, WN9, WN11, WN17, WN18, WN20, WN21, WN27). Hết hạn riêng của Bước phê duyệt
(R9.4, WN10) ở W2; phê duyệt đang mở của một lượt bị hủy, kể cả lượt quá hạn chót của workflow-engine, bị hủy cùng
lượt (R9.15). Quy tắc `all` (mọi người được giao phải duyệt) là bậc B, ở ticket 07.

## Việc cần làm

1. `tool.call`: ghim phiên bản công cụ lúc gửi kiểm định; đối số qua đích `json` của bộ dựng mẫu; gọi
   `ToolExecutor.execute` với đúng khoá mà wrapper nút dẫn (workflow-engine:R4.5), không tự dựng khoá; nhận
   `subject` đã khoá sau phê duyệt.
   Thiếu quyền → `permission_denied` từ executor; sàn gửi tin ở đường messaging của executor
   (compliance-pdpl), không ở bước.
2. Bảng `studio.step_assignments` và `studio.step_approvals` (xem mục Dữ liệu của spec: `tenant_id`,
   `workspace_id`, `run_id`, `node_id`; `step_assignments.assignee_kind` CHECK (`user`) không DEFAULT ở W1;
   `step_assignments.run_id` FK ghép `(tenant_id, run_id)` tới `platform.worker_runs (tenant_id, id)`
   (`uq_worker_runs_tenant_id_id` của workflow-engine/02) `ON DELETE CASCADE`, chỉ mục `(tenant_id, run_id, node_id)`;
   `step_approvals` thêm `interrupt_id text NOT NULL`, `approval_request_id`, `subject_node_id`, `subject_hash`,
   CHECK `ck_step_approvals_subject_hash`; FK ghép `(tenant_id, workspace_id, approval_request_id)` tới
   `platform.approval_requests (tenant_id, workspace_id, id)` qua `uq_approval_requests_tenant_id_workspace_id_id`,
   ràng buộc đã có nên ticket này chỉ dùng và không sửa `platform.approval_requests`, và FK
   `(tenant_id, run_id, interrupt_id)` tới `platform.run_waits (tenant_id, run_id, interrupt_id)` của workflow-engine/05,
   cả hai `ON DELETE CASCADE`, với chỉ mục `(tenant_id, workspace_id, approval_request_id)` và
   `(tenant_id, run_id, interrupt_id)`; RLS bật và FORCE; `updated_at` do trigger giữ nhường giá trị câu lệnh nêu). Migration sinh bằng
   `alembic revision -m "..."` nối tiếp baseline `0001`, id hex ngẫu nhiên. Đáp ứng `StepWaitLookupPort` mà
   workflow-engine/05 khai: từ id yêu cầu trả `(run_id, interrupt_id)` của dòng `step_approvals`, nối ở composition
   root.
3. `human.approval` ở chế độ `live`: mở yêu cầu phê duyệt có `approval_type` dưới tiền tố nghiêm `studio.step.`,
   thêm vào `strict_approval_prefixes` bằng đúng một dòng `|=` ở composition root của API và worker, không sửa dòng
   của ticket khác (agent-lifecycle/04 thêm `studio.publish.` ở cùng chỗ); workflow-engine/05 giữ dòng chờ và handler
   theo tiền tố; `required_scope` bắt buộc, thu hẹp theo người hoặc Biểu thức (nhóm ở W2); đóng dấu vào yêu cầu tên
   mọi Trường trang duyệt hiển thị (R9.7). Một mục `decision_guards['studio.step.approval']` qua guard async
   `ApprovalDecisionGuard` của tenant-config/05 trả 403 `permission_denied` cho người giữ `required_scope` mà không
   được giao và người không đọc được một Trường đã đóng dấu (R9.8, luật của field-security:R4.5); người tạo lượt
   chạy thiếu `required_scope` nhận 403 ở kiểm tem, mọi người khác không giữ tem nhận 404 vì không thấy yêu cầu; người
   tạo lượt chạy giữ scope nhận 409 `conflict` với `details.reason_code` `second_person_required` ở luật tiền tố
   nghiêm, mã mà `_enforce_strict_rules` của tenant-config/05 đặt cho mọi loại phê duyệt, nên ticket này không đặt mã
   riêng (V4.P9; ADR-0104 (Accepted) quyết 11; ADR-0004 (Accepted)). Mã băm chủ thể khoá ở `subject_node`. Trước khi mở
   yêu cầu, Bước tính ứng viên từ `effective_grants` của tenant-rbac: người giữ `required_scope`, thu hẹp theo người
   được giao hay Biểu thức, bỏ người tạo lượt chạy và chủ thể chạy; không còn ai thì Bước kết thúc với
   `no_approver`, đi làn lỗi khi Khi lỗi là `route` và làm lượt chạy `failed` khi là `fail`, và không yêu cầu nào mở
   (R9.13; ADR-0112 (Accepted) quyết 7). Schema của `human.approval@1` chỉ nhận Khi lỗi `fail` hay `route` (R9.17).
   Theo ba tính chất vị trí bắt buộc của ticket 02, `human.approval@1` khai `opens_wait` đúng, `ends_run` và
   `exits_loop` sai, và `tool.call@1` khai cả ba sai.
   Bước khai hai Nhánh ra `approved` ("Duyệt") và `rejected` ("Từ chối"), mỗi Nhánh ra một làn Bước của tài liệu dạng
   cây (V4.24); lúc lượt `live` tiếp tục sau quyết định, Bước chạy làn của quyết định đó và không chạy làn kia
   (R9.16).
4. Kiểm khi gửi kiểm định: chen bước sau phê duyệt làm đổi mã băm chủ thể → từ chối. Kiểm theo loại `workflow`
   (R9.5): ngoài người chạy của lượt không ai giữ `required_scope` → lệnh gửi kiểm định trả 422 với
   `details.reason_code` `no_second_approver` và phiên bản ở Nháp; đăng ký vào bảng kiểm theo loại mà
   agent-lifecycle/03 khai (agent-lifecycle:R2.7), ở composition root; không có khóa `studio.workflows.publish`.
5. `human.approval` ở chế độ `simulate` (N2): đọc quyết định giả lập của chính Bước từ đầu vào của lượt mô phỏng
   (`simulated_decisions[node_id]`, workflow-triggers:R2.7) hay từ Câu kiểm định của Cổng chất lượng
   (agent-lifecycle:R4.7); đi Nhánh ra của quyết định đó; không mở yêu cầu phê duyệt, không ghi dòng chờ; audit
   `studio.step.approval.simulated` với `details.run_mode`, `details.decision` và nguồn, trong cùng giao dịch ghi kết
   quả của Bước (R9.9, R9.10); không có quyết định cho Bước → lượt chạy `failed` với `simulated_decision_missing`
   (R9.12). Ở `live`, Bước bỏ qua mọi quyết định giả lập trong đầu vào và mở yêu cầu thật (R9.11).
6. Bộ trả phiên bản chủ thể cho mã quyết định Zalo (W2 nối thêm nhắc, chuyển cấp và hết hạn; ở W1 Bước phê duyệt
   không có hạn riêng, DO-31, còn lượt chạy có hạn chót `deadline_at` của workflow-engine, V4.14). Huỷ lượt chạy theo
   bất kỳ đường nào, kể cả Tắt khẩn và quá hạn chót (`deadline_exceeded`, workflow-engine:R5.23), huỷ phê duyệt đang mở
   trong cùng giao dịch (R9.15): một trigger AFTER UPDATE OF `status` trên `platform.run_waits` nghe dòng chờ sang
   `cancelled`, việc mà trigger của workflow-engine/05 làm khi lượt chạy sang `cancelled` (workflow-engine:R6.13), và
   đặt yêu cầu `pending` nối qua `studio.step_approvals` sang `cancelled`.

## Tiêu chí chấp nhận

- [ ] R8.1: `tool.call` gọi `ToolExecutor.execute` với đúng khoá mà wrapper nút dẫn (workflow-engine:R4.5) và
      phiên bản công cụ đã ghim lúc gửi kiểm định.
- [ ] R8.2 (WN6): hai lần chạy song song cùng khoá do wrapper nút dẫn → tác động ngoài xảy ra đúng một lần; cho Bước
      tự dựng khoá khác → test đỏ.
- [ ] R8.3 (WN7): người chạy thiếu quyền công cụ → `permission_denied` từ executor, không từ bước.
- [ ] R8.4 (WN7): `tool.call` `email.send` của `smtp@1.0.0` tới địa chỉ chưa đồng ý → `blocked:no_consent`;
      gọi thẳng công cụ (bỏ qua bước) cũng bị chặn; gỡ sàn gửi khỏi executor → test đỏ.
- [ ] R9.1: Bước phê duyệt ở `live` mở `approval_type` dưới `studio.step.` với `required_scope` bắt buộc; cấu hình
      thu hẹp theo nhóm → schema từ chối; INSERT `assignee_kind = 'team'` → CHECK từ chối.
- [ ] R9.2 (WN8): người giữ `required_scope` mà không được giao → 403 qua `decision_guards`; người tạo lượt chạy
      thiếu `required_scope` → 403; một người khác không giữ tem quyết hay đọc yêu cầu → 404; gỡ guard → test đỏ.
- [ ] R9.6 (WN8): nhân viên Sales tạo lượt chạy và giữ `required_scope` tự duyệt → 409 `conflict` với
      `details.reason_code` `second_person_required`; bỏ `studio.step.` khỏi tiền tố nghiêm → test đỏ.
- [ ] R9.13 (WN8): người được giao duy nhất giữ `required_scope` rời công ty sau khi phát hành, rồi một lượt `live`
      tới Bước phê duyệt khai Khi lỗi `route` → làn lỗi chạy với `no_approver`, không dòng `platform.approval_requests`
      nào; cùng tài liệu với Khi lỗi `fail` → lượt chạy `failed` với `no_approver`; gỡ kiểm ứng viên lúc mở → yêu cầu
      mở mà không ai duyệt được và lượt chờ tới hạn chót, test đỏ.
- [ ] R9.16 (WN27): lượt `live`, quyết định `rejected` → làn `rejected` chạy, `tool.call` trong làn `approved` có 0
      lời gọi; quyết định `approved` → làn `approved` chạy, làn `rejected` không chạy; đảo ánh xạ từ quyết định sang
      làn → test đỏ.
- [ ] R9.17 (WN11): cấu hình Bước phê duyệt khai Khi lỗi `continue` hay `incident` → schema từ chối; `fail` và
      `route` → nhận; gỡ danh sách Khi lỗi cho phép khỏi mục `human.approval@1` → `continue` qua, test đỏ.
- [ ] R9.7: yêu cầu phê duyệt bước mang danh sách tên Trường mà trang duyệt hiển thị.
- [ ] R9.8 (WN17): người được giao không đọc được `phone` đã đóng dấu quyết → 403, yêu cầu vẫn `pending`;
      gỡ điều kiện đọc trường khỏi guard → test đỏ.
- [ ] R9.3 (WN9): chen một bước sau khi duyệt → gửi kiểm định từ chối; mã băm chủ thể khác lúc thực thi →
      `subject_changed`.
- [ ] R9.5 (WN8): chỉ người chạy giữ `required_scope` → lệnh gửi kiểm định của agent-lifecycle trả 422
      `no_second_approver`, phiên bản ở Nháp; gỡ đăng ký kiểm → test đỏ.
- [ ] R9.15 (WN21): Tắt khẩn một lượt đang chờ ở Bước phê duyệt → yêu cầu `studio.step.` của nó `cancelled` trong cùng
      giao dịch; lượt chờ bị reaper kết thúc vì `deadline_exceeded` → như vậy, người được giao quyết sau đó bị từ chối,
      yêu cầu vẫn `cancelled`; gỡ trigger hủy yêu cầu → yêu cầu còn `pending`, test đỏ.
- [ ] R9.9: lượt `simulate` với quyết định giả lập `rejected` cho Bước phê duyệt → Nhánh ra từ chối chạy, không dòng
      `platform.approval_requests` hay `platform.run_waits` nào, lượt chạy không chờ; quyết định `approved` → Nhánh ra
      duyệt chạy.
- [ ] R9.10: mỗi quyết định giả lập dùng → đúng một audit `studio.step.approval.simulated` có `details.run_mode`,
      `details.decision` và nguồn.
- [ ] R9.11 (WN18): lượt `live` có `simulated_decisions` mang `approved` trong đầu vào → một yêu cầu phê duyệt
      `studio.step.` thật được mở và lượt chạy chờ; cho Bước đọc quyết định giả lập ở `live` → test đỏ.
- [ ] R9.12 (WN18): lượt `simulate` thiếu quyết định cho một Bước phê duyệt → lượt chạy `failed` với
      `simulated_decision_missing`, Nhánh ra duyệt không chạy; coi thiếu là đã duyệt → test đỏ.
- [ ] R9.1: `StepWaitLookupPort` trả đúng `(run_id, interrupt_id)` cho id yêu cầu; dòng chờ của workflow-engine bị xóa
      theo lượt chạy thì dòng `step_approvals` đi theo CASCADE.
- [ ] R9.14 (WN20): `dw_app` gắn tenant A chèn dòng `step_approvals` mang `approval_request_id` của một yêu cầu tenant
      B, hay dòng `step_assignments` mang `run_id` của một lượt chạy tenant B → lỗi FK, không dòng nào được ghi; đổi
      một trong hai FK về FK một cột → ca của nó qua, test đỏ.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/workflows/test_tool_call_node.py packages/python/dw_studio/tests/workflows/test_human_approval_node.py && make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:217-235`; spec: R9.1
  (`approval_requests` thiếu cột giao, hạn, chuyển cấp).
- `db/migrations/versions/e399be8c0a2d_platform_approval_view_receipts_and_.py:127-129`; spec: Dữ liệu
  (`uq_approval_requests_tenant_id_workspace_id_id`, đích của FK ghép của `step_approvals`).
- `apps/api/src/dw_api/bootstrap/runtime.py:237-239`; spec: R9.2 (`strict_approval_prefixes`,
  `decision_guards`).
- `apps/api/src/dw_api/bootstrap/wiring.py:314`; spec: R9.4 (mã Zalo chỉ cho loại có người trả lời).
- ADR-0112 (Accepted) quyết 7; spec: R9.

## Comments

- 2026-10-23 (agent): theo phiếu 23/10/2026: hết hạn phê duyệt sang W2 (DO-31); bảng mã từ chối người quyết ở ADR-0004 (Accepted) tách R9.2 (403) và R9.6 (409); người duyệt phải đọc được Trường đóng dấu qua guard async (DO-36), nên ticket chờ tenant-config/05; khóa phát hành chung, R9.5 là kiểm đăng ký qua Protocol; chờ compliance-pdpl/04 và test WN7 dùng `email.send` của `smtp@1.0.0` (DO-48.1).
- 2026-10-24 (agent): theo quyết định của Đạt ngày 24/10/2026: bảng ba mã ở ADR-0104 (Accepted) quyết 11, người khác không giữ tem nhận 404 (R9.2); R9.5 là kiểm lúc gửi kiểm định trả 422 `no_second_approver`, ticket chờ agent-lifecycle/03; khoá chống lặp của workflow-engine:R4.5; W1 không giao theo nhóm; `step_approvals` là chủ liên kết tới yêu cầu và đáp ứng `StepWaitLookupPort`; Bước phê duyệt ở `simulate` theo quyết định giả lập (N2: R9.9-R9.12, WN18).
- 2026-10-24 (agent): vòng sửa thứ tư: luật tiền tố nghiêm trả 409 với `second_person_required` do tenant-config/05 đặt (V4.P9, agent tạm); lúc mở phê duyệt không còn ứng viên thì `no_approver` (R9.13, phát hiện F về ADR-0112 (Accepted) và R9.5); từ vựng `approved`, `rejected` của R9.9 là chủ cho route `test-runs` và Câu kiểm định.
- 2026-10-24 (agent): lượt c của vòng 4: `step_assignments.run_id` thành FK ghép tới `uq_worker_runs_tenant_id_id`, và `step_approvals.approval_request_id` thành FK ghép `(tenant_id, workspace_id, approval_request_id)` qua `uq_approval_requests_tenant_id_workspace_id_id` đã có, nên ticket này không thêm UNIQUE nào lên `platform.approval_requests`; R9.1 thêm ca chéo tenant (CLAUDE.md, Tenancy and authorization).
- 2026-10-24 (agent): kiểm lượt c của vòng 4: dòng `Xong:` thêm `make test-integration`, vì ca chéo tenant và ca CASCADE của R9.1 cần PostgreSQL thật, mà hai tệp test bước không chạy (failure-modes #1: ai chạy test này).
- 2026-10-24 (agent): lượt d của vòng 4: dòng Comments của lượt c thôi dẫn mã mục của lượt; ca chéo tenant của hai FK ghép rời tiêu chí R9.1 sang R9.14 (WN20), kèm test đột biến đổi mỗi FK về một cột (CLAUDE.md, Tenancy and authorization; failure-modes #3), vẫn chạy trong `make test-integration` của dòng `Xong:`, và Mục tiêu nêu R9.14, WN20 cạnh các mã khác; bước 2 nêu chỉ mục của hai FK (CLAUDE.md, Data model rules). Không thêm cạnh.
- 2026-10-24 (agent): theo V4.14 của Đạt: lượt chạy có hạn chót ở W1, nên bước 6 thôi ghi "W1 phê duyệt chờ không hạn" và
  việc huỷ phê duyệt đang mở cùng lượt thành tiêu chí R9.15 (WN21), có ca quá hạn chót, thay dòng tiêu chí cũ mang mã R9.2;
  tiêu chí R9.13 thôi nói "lượt chờ mãi". Không thêm cạnh: ticket này đã chờ workflow-engine/05, nơi trigger hủy dòng chờ
  ra đời, và workflow-engine/04, nơi reaper kết thúc lượt quá hạn, qua ticket đó.
- 2026-10-24 (agent): theo V4.24 của Đạt: hai kết quả của phê duyệt là hai làn Bước, nên tiêu chí R9.16 (WN27) thử
  làn `approved` chỉ chạy khi quyết định là duyệt; làn lỗi chỉ có khi Khi lỗi là `route`, nên R9.13 nói `no_approver`
  đi làn lỗi với `route` và làm lượt `failed` với `fail` thay "không nối Nhánh ra đó", và schema chỉ nhận `fail` hay
  `route` (R9.17, WN11; agent, tạm). Quy tắc `all` của V4.26 ở ticket 07, chờ ticket này, nên đường găng YC94 không
  chờ bậc B. Không thêm cạnh.
- 2026-10-25 (agent): `human.approval@1` khai `opens_wait` đúng và `tool.call@1` khai cả ba tính chất vị trí sai, theo
  trường bắt buộc của ticket 02 (dòng Quyết định 25/10/2026 của spec), để `wf.wait_in_parallel` của workflow-engine/06
  nhận ra Bước phê duyệt mà không đọc tên loại. Không thêm cạnh.
