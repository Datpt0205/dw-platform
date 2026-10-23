# 05 — Bước chờ người: run_waits, quyết định trong giao dịch, resume theo interrupt id, ghim phiên bản

Status: needs-info (DO-41)
Blocked by: 04
Area: studio
Yêu cầu: R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.7, R6.8, R6.9, R6.10, WE9, WE10, WE11, WE12, G1

## Mục tiêu

Cho một lượt chạy chờ người tại chỗ nhiều ngày rồi tiếp tục ở tiến trình khác đúng từ bản kê đã ghim, và từ chối tiếp tục khi topology hay phiên bản đã đổi (R6 của spec).

## Việc cần làm

1. Bảng `platform.run_waits` (PK `(tenant_id, id)`, `run_id` FK CASCADE, `interrupt_id`, `kind` CHECK `approval`, `status` CHECK `open`, `resolved` không DEFAULT, `required_scope`, `approval_id`, `created_at`, `resolved_at`, UNIQUE `(tenant_id, run_id, interrupt_id)`), RLS ENABLE và FORCE, grant `dw_app` SELECT, INSERT, UPDATE chỉ `status`, `resolved_at`; vào thứ tự xóa offboarding và `test_rls_coverage.py`.
2. Node chờ mở một `interrupt` cộng một dòng `run_waits`; nhiều dòng chờ mở cùng lúc được. Interrupt thành yêu cầu phê duyệt tiền tố nghiêm `studio.step.` với `required_scope` của node; đăng ký handler theo tiền tố vào bảng điều phối của `ApproveAndResumeService` ở composition root (không nhánh trong `decide`).
3. Quyết định đặt dòng chờ `resolved` và lượt chạy `queued` trong cùng giao dịch của quyết định; không tiếp tục trên request HTTP của người quyết. Runner resume bằng map các dòng chờ đã `resolved` theo interrupt id; không resume với map rỗng. Quyết định cho interrupt id không còn mở bị từ chối.
4. Mục `engine` của bản kê (tenant-config/04) ghim compiler version, node `type@major`, mã băm schema state, định dạng lưu, phiên bản LangGraph; năm kiểm khi tiếp tục; trạng thái `blocked`, audit `run.blocked`, metric; giữ `run_mode` đã ghim.
5. `POST /api/v1/runs/{run_id}/retry` (quyền `runs.retry`) chạy lại năm kiểm sau khi người dựng sửa. Giá trị bí mật không vào dòng checkpoint hay `run_waits`.

## Tiêu chí chấp nhận

- [ ] R6.1: một node chờ → một `interrupt` và một dòng `run_waits`; hai node chờ mở cùng lúc → hai dòng `open`.
- [ ] R6.2: bước chờ mở yêu cầu phê duyệt `studio.step.`; người tạo lượt chạy quyết bước của chính mình → 409 (tiền tố nghiêm).
- [ ] R6.3: tắt API ngay sau quyết định → lượt chạy tiếp tục ở worker; gỡ handler trong giao dịch → test "đã duyệt mà run kẹt" đỏ.
- [ ] R6.4: một lượt chạy tiếp tục dùng map theo interrupt id của các dòng chờ `resolved`.
- [ ] R6.5 (WE9): gọi resume khi không dòng chờ nào `resolved` → runner không gọi graph, ném lỗi; cho qua map rỗng → test đỏ.
- [ ] R6.6 (WE11): quyết định cho interrupt id không còn mở → bị từ chối, lượt chạy không tiếp tục.
- [ ] R6.7 (WE10): tiếp tục chạy năm kiểm đọc từ mục `engine` của bản kê; bỏ từng kiểm (a) đến (e) → năm test đột biến tương ứng đỏ.
- [ ] R6.8 (WE10): xóa node đang chờ ở build mới → run `blocked`, audit `run.blocked`, không bước nào chạy.
- [ ] R6.9 (WE11): niêm phong phiên bản mới khi lượt chạy chờ duyệt → lượt tiếp tục với bản ghim và `run_mode` cũ.
- [ ] R6.10 (WE12): byte credential giả không xuất hiện trong dòng checkpoint hay `run_waits`; thêm nhánh ghi giá trị điểm gắn vào state → test đỏ.
- [ ] G1: `test_pause_restart_resume_approved` xanh trước và sau thay đổi.
- [ ] Xong: `make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langgraph_runner.py:501-509`; `packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:245`; spec: R6, WE9, WE10, WE11, WE12.
- tenant-config:R4.5, R6.4 (giữ chế độ, dựng lại từ bản kê); ADR-0113 (Proposed) quyết 3; ADR-0109 (Proposed) quyết 8.

## Comments

- 2026-10-23 (agent): ticket còn needs-info vì DO-41 (chờ tại chỗ có nén hay mô hình phân đoạn) chưa được Đạt chốt; thiết kế theo khuyến nghị (a).
