# 01 — Đóng băng toàn nền tảng và theo tenant, kiểm ở mọi cửa của runtime

Status: needs-triage
Area: studio
Yêu cầu: R7.1, R7.2, R7.3, R7.4, R7.5, R7.6, AL11, AL12, AL16

## Mục tiêu

Đóng băng (nền tảng, tenant) là công tắc trong Postgres, đọc qua một cache đóng khi lỗi mà NOTIFY làm
mới, và mọi cửa của runtime hỏi một `RunControlPort` trước khi làm. Lát này dựng bảng công tắc, port,
adapter và các cửa; ticket 05 dùng chính bảng và các cửa này cho Tắt khẩn cấp (spec R7). Kèm một
nguyên mẫu đo việc tiếp tục một lượt chạy sau khi bị chặn ở một cửa, để quyết Đóng băng có thể tiếp
tục ở W2 (DO-28).

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên, owner `dw_platform`), chép nguyên văn mục Dữ liệu của spec:
    - `platform.control_switches` với CHECK `scope_type` (`tenant`, `agent`, `workflow`), `action`
      (`freeze`, `kill`), `origin` (`tenant`, `platform`), `reason_code` (`incident`, `maintenance`,
      `abuse`, `test`, `other`), `reason` 1..500 ký tự; `workspace_id`, `target_id` NULL chỉ khi
      `scope_type='tenant'`; chỉ mục một công tắc mở
      `(tenant_id, scope_type, coalesce(target_id, '00000000-0000-0000-0000-000000000000'::uuid)) WHERE lifted_at IS NULL`;
      FK `tenant_id → platform.tenants ON DELETE CASCADE`; RLS ENABLE và FORCE theo tenant.
    - Trigger `platform.guard_control_switch()` (chèn chỉ mở; một dòng gỡ một lần, không đổi gì khác;
      dòng `origin='platform'` chỉ `dw_provisioner` gỡ) và trigger `pg_notify('dw_control_switch', ...)`
      payload chỉ id.
    - `platform.platform_freezes` (mặt danh tính, không `tenant_id`): tối đa một dòng mở; `dw_app` chỉ
      SELECT; do `dw_provisioner` ghi, audit trong `platform.provisioning_audit`.
    - Grant: `dw_app` SELECT, INSERT, UPDATE (`lifted_by, lifted_at, lift_reason, lift_approval_id`) trên
      `control_switches`, chỉ SELECT trên `platform_freezes`; `dw_provisioner` ghi cả hai; khẳng định ở
      `test_privileges.py`; `test_rls_coverage.py` thấy `control_switches`. Thêm `studio.lifecycle.freeze`
      vào vai `org_admin` (vai còn do migration sở hữu).
2. `RunControlPort` (bên dùng khai trong `dw_agent_runtime.ports`): `require_open(run_context, *, artifacts=())`
   ném `RunHaltedError` (một `ConflictError`, HTTP 409, `details.reason_code` trong `platform_frozen`,
   `tenant_frozen`, `artifact_killed`, `control_state_unavailable`), và `admission_state(tenant_id, artifacts)`
   cho ingress. `SqlRunControl` giữ ảnh chụp theo tenant TTL 5 giây, nghe `dw_control_switch` (dựng như
   listener của `run_events.py`), và quá 30 giây không làm mới thì từ chối (đóng khi lỗi; trái cache
   AccessContext mở khi lỗi, ADR-0024 (Proposed) quyết 4). `RuntimeSeam.run_control` một instance.
3. Gắn cửa (mỗi cửa nhận port bằng injection, không mặc định): runner `start`, `stream`, `resume`;
   `ApproveAndResumeService.decide` trước khi quyết; `RunControlMiddleware` trong `platform_middleware`
   và stack con `sub_agent_spec`; gateway có cấu trúc trước `budget.check`; middleware tóm tắt trước
   `budget.check`; `ToolExecutor._execute` trước kiểm quyền (audit `tool.denied`, `policy_decision`
   `deny_frozen`). Runner map `RunHaltedError` sang `_fail(status=CANCELLED, event="run.cancelled")`;
   middleware lỗi công cụ ném lại `RunHaltedError` thay vì báo model.
4. Route `POST /api/v1/admin/freeze`, `POST /api/v1/admin/unfreeze` (`studio.lifecycle.freeze`,
   `Idempotency-Key`, body `reason_code`, `reason`); `GET /api/v1/control-state` (mọi thành viên; chỉ
   mã, không lý do chữ); nhà vận hành `POST /api/v1/platform/freeze`, `POST /api/v1/platform/unfreeze`,
   `POST /api/v1/platform/tenants/{tenant_id}/freeze`, `POST /api/v1/platform/tenants/{tenant_id}/unfreeze`
   (ngữ cảnh provisioning).
5. Audit `control.freeze.set`, `control.freeze.lifted` (tenant), `platform.freeze.set`,
   `platform.freeze.lifted`, `platform.tenant_freeze.set`, `platform.tenant_freeze.lifted` (provisioning),
   mỗi sự kiện trong giao dịch của thay đổi; metric `dw_control_refusals_total{door, reason_code}` không
   nhãn tenant. Hợp đồng `admission_state` cho ingress của workflow-engine (giữ sự kiện khi đóng băng),
   kèm test hợp đồng với ingress giả.
6. Nguyên mẫu (nghiên cứu) trên `langgraph==1.2.11`, `langchain==1.4.1`, `SqlAlchemyCheckpointSaver`:
   một graph `create_agent` được runner chứa, ném `RunHaltedError` ở middleware model và ở executor;
   gọi lại với `None` trên cùng thread có tiếp tục từ checkpoint cuối không, công cụ đã chạy có chạy lại
   không, khóa chống lặp có giữ không, có cần trạng thái `frozen` riêng không. Ghi kết quả vào Comments;
   kết quả quyết Đóng băng có thể tiếp tục ở W2 (DO-28).

## Tiêu chí chấp nhận

- [ ] R7.1 (AL11): đặt đóng băng giữa một run, lời gọi kế tiếp qua mỗi cửa trong 7 cửa bị từ chối, run
      kết thúc `cancelled` với `reason_code`; tiến trình B thấy công tắc do tiến trình A đặt trong 5 giây
      (NOTIFY), và trong TTL khi NOTIFY mất; gỡ kiểm ở một cửa → test của cửa đó đỏ.
- [ ] R7.3 (AL11): database ngắt quá 30 giây → lời gọi công cụ bị từ chối `control_state_unavailable`.
- [ ] R7.2: với ingress giả, một sự kiện trình kích hoạt khi đóng băng bị giữ, không bắt đầu run, và
      chạy theo thứ tự đến sau khi gỡ.
- [ ] R7.4 (AL12): `org_admin` gỡ đóng băng nguồn `platform` qua `POST /api/v1/admin/unfreeze` → 403.
- [ ] R7.5 (AL12): `dw_app` UPDATE trực tiếp để gỡ hay đổi một công tắc ngoài bước gỡ hợp lệ → 23514; gỡ
      trigger → test đỏ.
- [ ] R7.6: đặt và gỡ đóng băng ghi đúng một audit trong cùng giao dịch; rollback thì audit không còn.
- [ ] R7.1 (AL16): đóng băng tenant A không chạm run tenant B; đọc công tắc của B từ A → 404; gỡ FORCE
      RLS khỏi `control_switches` → `test_rls_coverage.py` đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_events.py:97`; spec: R7.1 (mẫu NOTIFY).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:160`; spec: R7.1 (cửa công cụ).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/gateway.py:164`; spec: R7.1 (cửa có cấu trúc).
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/caching_lookup.py:27`; spec: R7.3
  (cache đóng khi lỗi, trái cache khóa tenant mở khi lỗi); ADR-0120 (Proposed) quyết 5.

## Comments

- 2026-10-23 (agent): gộp B10a agent-lifecycle 01 và 12 (nguyên mẫu), cộng phần đóng băng ở executor của
  B8b tools-and-skills 08. DO-28 đã quyết tạm theo khuyến nghị (a): đóng băng hủy run đang chạy ở cửa kế
  tiếp, giữ run chờ duyệt ở nguyên.
