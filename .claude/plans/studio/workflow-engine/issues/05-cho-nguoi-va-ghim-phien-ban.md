# 05 — Bước chờ người: run_waits, quyết định trong giao dịch, resume theo interrupt id, ghim phiên bản

Status: needs-triage
Blocked by: 04, .claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md
Area: studio
Yêu cầu: R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7, R6.8, R6.9, R6.10, R6.11, R6.12, WE9, WE10, WE11, WE12, WE15, WE16, G1

## Mục tiêu

Cho một lượt chạy chờ người tại chỗ nhiều ngày rồi tiếp tục ở tiến trình khác đúng từ bản kê đã ghim, và từ chối tiếp tục khi topology hay phiên bản đã đổi (R6 của spec).

## Việc cần làm

1. Bảng `platform.run_waits` (PK `(tenant_id, id)`, `run_id` FK CASCADE, `interrupt_id`, `kind` CHECK `approval`, `status` CHECK `open`, `resolved` không DEFAULT, `required_scope`, `approval_id`, `created_at`, `resolved_at`, UNIQUE `(tenant_id, run_id, interrupt_id)`), RLS ENABLE và FORCE chỉ theo tenant, grant `dw_app` SELECT, INSERT, UPDATE chỉ `status`, `resolved_at`; vào thứ tự xóa offboarding và `test_rls_coverage.py`, với một dòng lý do trong danh sách bảng toàn tenant của test đó (bảng con của `platform.worker_runs`, FK CASCADE; DO-01).
2. Node chờ mở một `interrupt` cộng một dòng `run_waits`; nhiều dòng chờ mở cùng lúc được. Yêu cầu phê duyệt `studio.step.` do Bước phê duyệt của workflow-nodes mở (workflow-nodes:R9.1), kể cả tiền tố nghiêm và `decision_guards`; ticket này ghi dòng chờ trỏ tới yêu cầu đó và đăng ký handler theo tiền tố `studio.step.` vào bảng điều phối của `ApproveAndResumeService` ở composition root (không nhánh trong `decide`). Test của ticket này dùng một bước chờ giả cho tới khi `human.approval@1` của workflow-nodes/06 tới.
3. Quyết định đặt dòng chờ `resolved` và lượt chạy `queued` trong cùng giao dịch của quyết định; không tiếp tục trên request HTTP của người quyết. Runner resume bằng map các dòng chờ đã `resolved` theo interrupt id; không resume với map rỗng. Quyết định cho interrupt id không còn mở bị từ chối.
4. Mục `engine` của bản kê (tenant-config/04) ghim compiler version, node `type@major`, mã băm schema state, định dạng lưu, phiên bản LangGraph; năm kiểm khi tiếp tục; trạng thái `blocked`, audit `run.blocked`, metric; giữ `run_mode` đã ghim. Khi lượt chạy chuyển sang `waiting`, saver xóa mọi checkpoint cũ của thread và chỉ giữ checkpoint mới nhất (R6.11, DO-41).
5. `POST /api/v1/runs/{run_id}/resume-check` (quyền `studio.workflows.resume_check`, đăng ký trong migration của ticket này theo quy ước của tenant-rbac/01) chạy lại năm kiểm sau khi người dựng sửa. Giá trị bí mật không vào dòng checkpoint hay `run_waits`.
6. Quyền sống khi tiếp tục (R6.12): một port khai trong `dw_agent_runtime.ports` (như `RunAllowancePort`) trả scope hiện tại của chủ thể chạy trong workspace của lượt chạy; `dw_platform` đáp ứng bằng `platform.scopes_in` của tenant-rbac/02, nối ở composition root của worker. Lúc tiếp tục, runtime dựng lại `RunContext.scopes` từ port này, không từ scope đóng dấu lúc bắt đầu.

## Tiêu chí chấp nhận

- [ ] R6.1: một node chờ → một `interrupt` và một dòng `run_waits`; hai node chờ mở cùng lúc → hai dòng `open`.
- [ ] R6.2: một bước chờ giả mở yêu cầu `studio.step.` → một dòng `run_waits` `open` trỏ tới yêu cầu; quyết định đi tới handler đăng ký theo tiền tố ở composition root; `decide` không có nhánh nào cho `studio.step.`.
- [ ] R6.3: tắt API ngay sau quyết định → lượt chạy tiếp tục ở worker; gỡ handler trong giao dịch → test "đã duyệt mà run kẹt" đỏ.
- [ ] R6.4: một lượt chạy tiếp tục dùng map theo interrupt id của các dòng chờ `resolved`.
- [ ] R6.5 (WE9): gọi resume khi không dòng chờ nào `resolved` → runner không gọi graph, ném lỗi; cho qua map rỗng → test đỏ.
- [ ] R6.6 (WE11): quyết định cho interrupt id không còn mở → bị từ chối, lượt chạy không tiếp tục.
- [ ] R6.7 (WE10): tiếp tục chạy năm kiểm đọc từ mục `engine` của bản kê; bỏ từng kiểm (a) đến (e) → năm test đột biến tương ứng đỏ.
- [ ] R6.8 (WE10): xóa node đang chờ ở build mới → run `blocked`, audit `run.blocked`, không bước nào chạy.
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
