# 05 — Bước chờ người: run_waits, quyết định trong giao dịch, resume theo interrupt id, ghim phiên bản

Status: needs-triage
Blocked by: 04, .claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md
Area: studio
Yêu cầu: R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7, R6.8, R6.9, R6.10, R6.11, R6.12, R6.13, R6.14, WE9, WE10, WE11, WE12, WE15, WE16, G1

## Mục tiêu

Cho một lượt chạy chờ người tại chỗ nhiều ngày rồi tiếp tục ở tiến trình khác đúng từ bản kê đã ghim, và từ chối tiếp tục khi topology hay phiên bản đã đổi (R6 của spec).

## Việc cần làm

1. Bảng `platform.run_waits` (PK `(tenant_id, id)`, `run_id` FK CASCADE, `interrupt_id`, `node_id text NOT NULL` là node đang đỗ mà kiểm (b) của R6.7 so, `kind` CHECK `approval`, `status` CHECK `open`, `resolved`, `cancelled` không DEFAULT, `required_scope`, `created_at`, `resolved_at`, UNIQUE `(tenant_id, run_id, interrupt_id)`; không cột id yêu cầu phê duyệt), RLS ENABLE và FORCE chỉ theo tenant, grant `dw_app` SELECT, INSERT, UPDATE chỉ `status`, `resolved_at`; vào thứ tự xóa offboarding và `test_rls_coverage.py`, với một dòng lý do trong danh sách bảng toàn tenant của test đó (bảng con của `platform.worker_runs`, FK CASCADE; DO-01).
2. Node chờ mở một `interrupt` cộng một dòng `run_waits`; nhiều dòng chờ mở cùng lúc được. Yêu cầu phê duyệt `studio.step.` do Bước phê duyệt của workflow-nodes mở (workflow-nodes:R9.1), kể cả tiền tố nghiêm và `decision_guards`; `studio.step_approvals` của workflow-nodes/06 giữ id yêu cầu và trỏ tới dòng chờ qua FK `(tenant_id, run_id, interrupt_id)`, nên ticket này chỉ ghi dòng chờ và đăng ký handler theo tiền tố `studio.step.` vào bảng điều phối của `ApproveAndResumeService` ở composition root (không nhánh trong `decide`); handler tìm `(run_id, interrupt_id)` từ id yêu cầu qua một Protocol `StepWaitLookupPort` mà ticket này khai trong `dw_agent_runtime.ports` và workflow-nodes/06 đáp ứng từ `studio.step_approvals`. Test của ticket này dùng một bước chờ giả và một bản giả của port theo đúng hợp đồng, cho tới khi `human.approval@1` của workflow-nodes/06 tới.
3. Quyết định đặt dòng chờ `resolved` và lượt chạy `queued` trong cùng giao dịch của quyết định; không tiếp tục trên request HTTP của người quyết. Runner resume bằng map các dòng chờ đã `resolved` theo interrupt id; không resume với map rỗng. Quyết định cho interrupt id không còn mở (kể cả dòng `cancelled`) bị từ chối. Trigger AFTER UPDATE OF `status` trên `platform.worker_runs`: lượt chạy sang `cancelled` thì mọi dòng `run_waits` `open` của nó sang `cancelled` trong cùng giao dịch, cho mọi đường hủy, kể cả lane `control_switch` của agent-lifecycle:R8.2 (R6.13).
4. Mục `engine` của bản kê (tenant-config/04) ghim compiler version, node `type@major`, mã băm schema state, định dạng lưu, phiên bản LangGraph. Trước mỗi lần tiếp tục và mỗi lần nhận lại của làn `studio_runs` (ticket 04), chạy năm kiểm của ADR-0109 (Accepted) quyết 8 mà mọi lượt chạy đều qua (R6.7): (a) compiler và mọi `type@major` đã ghim có đăng ký trong bản build; (b) node đang đỗ có trong đồ thị đã ghim và bằng `run_waits.node_id`; (c) mã băm schema state khớp; (d) định dạng lưu đọc được, phiên bản LangGraph kiểm cùng mục này; (e) giá trị resume là envelope khác rỗng. Một kiểm trượt → trạng thái `blocked` với `error.code` `incompatible_resume`, audit `run.blocked`, metric (R6.8). Lượt mô phỏng ghim mã băm tạm của bản Nháp (workflow-engine/02, R3.9) qua thêm kiểm thứ sáu của ADR-0109 (Accepted) quyết 8: `PinnedResolver` của tenant-config/04 là chỗ duy nhất băm lại nội dung nháp hiện tại và từ chối dựng lại khi mã băm khác mã băm tạm; trước khi tiếp tục hay nhận lại, runtime biến lần từ chối đó thành `blocked` với `incompatible_resume`, không bước nào chạy, và không băm lại lần thứ hai (R6.14). Giữ `run_mode` đã ghim. Khi lượt chạy chuyển sang `waiting`, saver xóa mọi checkpoint cũ của thread và chỉ giữ checkpoint mới nhất (R6.11, DO-41).
5. `POST /api/v1/runs/{run_id}/resume-check` (quyền `studio.workflows.resume_check`, đăng ký trong migration của ticket này theo quy ước khóa của tenant-rbac/01; câu INSERT vào `platform.permissions` nêu mọi cột NOT NULL không DEFAULT lúc đó, kể cả `risk` của tenant-rbac/01 và `tenant_grantable` của tenant-rbac/02, giá trị theo luật phân loại của hai ticket đó, V4.P2) chạy lại các kiểm khi tiếp tục sau khi người dựng sửa, tức năm kiểm của R6.7 và, khi gốc là bản Nháp, kiểm của R6.14: qua hết thì 200 và run rời `blocked`, một kiểm vẫn trượt thì 409 `incompatible_resume`. Giá trị bí mật không vào dòng checkpoint hay `run_waits`.
6. Quyền sống khi tiếp tục (R6.12): một port khai trong `dw_agent_runtime.ports` (như `RunAllowancePort`) trả scope hiện tại của chủ thể chạy trong workspace của lượt chạy; `dw_platform` đáp ứng bằng `platform.scopes_in` của tenant-rbac/02, nối ở composition root của worker. Lúc tiếp tục, runtime dựng lại `RunContext.scopes` từ port này, không từ scope đóng dấu lúc bắt đầu.

## Tiêu chí chấp nhận

- [ ] R6.1: một node chờ → một `interrupt` và một dòng `run_waits`; hai node chờ mở cùng lúc → hai dòng `open`.
- [ ] R6.2: một bước chờ giả mở yêu cầu `studio.step.` → một dòng `run_waits` `open`, mà liên kết theo `(run_id, interrupt_id)` nối với yêu cầu; quyết định đi tới handler đăng ký theo tiền tố ở composition root; `decide` không có nhánh nào cho `studio.step.`.
- [ ] R6.3: tắt API ngay sau quyết định → lượt chạy tiếp tục ở worker; gỡ handler trong giao dịch → test "đã duyệt mà run kẹt" đỏ.
- [ ] R6.4: một lượt chạy tiếp tục dùng map theo interrupt id của các dòng chờ `resolved`.
- [ ] R6.5 (WE9): gọi resume khi không dòng chờ nào `resolved` → runner không gọi graph, ném lỗi; cho qua map rỗng → test đỏ.
- [ ] R6.6 (WE11): quyết định cho interrupt id không còn mở → bị từ chối, lượt chạy không tiếp tục; dòng chờ `cancelled` vì lượt chạy bị hủy, rồi quyết định tới → bị từ chối, lượt chạy vẫn `cancelled`.
- [ ] R6.13 (WE11): đặt một lượt chạy có hai dòng chờ `open` sang `cancelled` → cả hai dòng `cancelled` trong cùng giao dịch; gỡ trigger hủy dòng chờ → dòng giữ `open`, test đỏ.
- [ ] R6.7 (WE10): tiếp tục và nhận lại chạy năm kiểm đọc từ mục `engine` của bản kê; mỗi kiểm (a) đến (e) có một test đột biến riêng, và bỏ đúng kiểm đó → test của nó đỏ.
- [ ] R6.8 (WE10): xóa node đang chờ ở build mới, hay `run_waits.node_id` khác node đang đỗ → run `blocked` với `error.code` `incompatible_resume`, audit `run.blocked`, không bước nào chạy; `resume-check` khi kiểm vẫn trượt → 409 `incompatible_resume`.
- [ ] R6.14 (WE10): worker chết giữa một lượt mô phỏng ghim bản Nháp, người dựng sửa bản Nháp, rồi lượt được nhận lại → `blocked` với `incompatible_resume`, không bước nào chạy; `resume-check` cho lượt đó khi nội dung nháp vẫn khác → 409 `incompatible_resume`; bản Nháp không đổi → lượt chạy tiếp; cho runtime chạy tiếp khi `PinnedResolver` từ chối → test đỏ.
- [ ] R6.9 (WE11): niêm phong phiên bản mới khi lượt chạy chờ duyệt → lượt tiếp tục với bản ghim và `run_mode` cũ.
- [ ] R6.10 (WE12): byte credential giả không xuất hiện trong dòng checkpoint hay `run_waits`; thêm nhánh ghi giá trị điểm gắn vào state → test đỏ.
- [ ] R6.11 (WE15): lượt chạy qua ba node rồi chờ → thread còn đúng một checkpoint; gỡ bước nén → số checkpoint lớn hơn một, test đỏ.
- [ ] R6.12 (WE16): thu hồi quyền công cụ của chủ thể chạy khi lượt chạy chờ duyệt, rồi duyệt → lời gọi công cụ bị executor từ chối `permission_denied`; dựng lại ngữ cảnh bằng scope đóng dấu → test đỏ.
- [ ] G1: `test_pause_restart_resume_approved` xanh trước và sau thay đổi.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:501-509`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:245`; spec: R6, WE9, WE10, WE11, WE12.
- tenant-config:R4.5, R6.4 (giữ chế độ, dựng lại từ bản kê); ADR-0113 (Accepted) quyết 3; ADR-0109 (Accepted) quyết 8.

## Comments

- 2026-10-23 (agent): ticket còn needs-info vì DO-41 (chờ tại chỗ có nén hay mô hình phân đoạn) chưa được Đạt chốt; thiết kế theo khuyến nghị (a).
- 2026-10-23 (agent): DO-41 đã có lời đáp (Đạt 23/10/2026, chờ tại chỗ có nén), nên ticket về `needs-triage`. Theo phiếu cùng ngày: chờ tenant-config/05 (OPS-b) và tenant-rbac/02 (`platform.scopes_in`); workflow-nodes mở phê duyệt bước, ticket này giữ điểm chờ và handler (B:workflow-engine:R6.2~workflow-nodes:R9.2); `run_waits` vào lớp bảng toàn tenant (DO-01); route `/retry` thành `/resume-check`.
- 2026-10-24 (agent): theo quyết định của Đạt ngày 24/10/2026: `run_waits` thêm trạng thái `cancelled` và hủy theo lượt chạy (R6.13); `approval_id` bỏ, liên kết tới yêu cầu là `studio.step_approvals` của workflow-nodes/06 qua `(run_id, interrupt_id)`.
- 2026-10-24 (agent): vòng sửa thứ tư: năm kiểm đúng ADR-0109 (Accepted) quyết 8, `run_waits.node_id`, lỗi `incompatible_resume` (phát hiện F về ADR-0109 (Accepted) và R6.7); theo V4.4, lượt mô phỏng bản Nháp đã đổi thì không tiếp tục (R6.14); câu INSERT khóa nêu `tenant_grantable` (V4.P2) và dẫn quy ước khóa của tenant-rbac/01 (V4.P10).
- 2026-10-24 (agent): lượt b của vòng 4: R6.14 là kiểm thứ sáu của ADR-0109 (Accepted) quyết 8 cho gốc là bản Nháp, và `resume-check` chạy cả kiểm đó (B6); nhãn vòng 4 đổi thành `V4.<n>`, `V4.P<n>`.
