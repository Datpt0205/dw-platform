# 01 — Đóng băng toàn nền tảng và theo tenant, kiểm ở mọi cửa của runtime

Status: needs-triage
Blocked by: .claude/plans/studio/org-and-principals/issues/02-thanh-vien-cap-tenant.md, .claude/plans/studio/foundations-hardening/issues/06-run-va-outbox-khong-ket.md
Area: studio
Yêu cầu: R7.1, R7.2, R7.3, R7.4, R7.5, R7.6, R7.7, R7.8, R7.10, R7.11, R9.1, R9.2, R10.1, AL11, AL12, AL16, AL17, AL18

## Mục tiêu

Đóng băng (nền tảng, tenant) là công tắc trong Postgres, đọc qua một cache đóng khi lỗi mà NOTIFY làm
mới, và mọi cửa của runtime hỏi một `RunControlPort` trước khi làm. Lát này dựng bảng công tắc, port,
adapter và các cửa; ticket 05 dùng chính bảng và các cửa này cho Tắt khẩn cấp (spec R7). Cửa nhận tách
theo `trigger_kind` (DO-28 C), gỡ Đóng băng của công ty cần người thứ hai (D11), và port từ chối chủ thể
không còn `active` (spec R9). Kèm một nguyên mẫu đo việc tiếp tục một lượt chạy sau khi bị chặn ở một
cửa, để quyết Đóng băng có thể tiếp tục cho lượt đang chạy ở W2.

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên, owner `dw_platform`), chép nguyên văn mục Dữ liệu của spec:
    - `platform.control_switches` với CHECK `scope_type` (`tenant`, `agent`, `workflow`), `action`
      (`freeze`, `kill`), `origin` (`tenant`, `platform`), `reason_code` (`incident`, `maintenance`,
      `abuse`, `test`, `other`), `reason` 1..500 ký tự; `workspace_id`, `target_id` NULL chỉ khi
      `scope_type='tenant'`; chỉ mục một công tắc mở
      `(tenant_id, scope_type, coalesce(target_id, '00000000-0000-0000-0000-000000000000'::uuid)) WHERE lifted_at IS NULL`;
      FK `tenant_id → platform.tenants ON DELETE CASCADE`; RLS ENABLE và FORCE theo tenant.
    - Trigger `platform.guard_control_switch()` (chèn chỉ mở; một dòng gỡ một lần, không đổi gì khác;
      dòng `origin='platform'` chỉ `dw_provisioner` gỡ; DELETE chỉ khi `platform.tenants.status` của công ty là
      `offboarding`, mọi DELETE khác → 23514, spec R7.5, R10.1) và trigger
      `pg_notify('dw_control_switch', ...)` payload chỉ id.
    - `platform.platform_freezes` (mặt danh tính, không `tenant_id`): tối đa một dòng mở; `dw_app` chỉ
      SELECT; do `dw_provisioner` ghi, audit trong `platform.provisioning_audit`.
    - Grant: `dw_app` SELECT, INSERT, UPDATE (`lifted_by, lifted_at, lift_reason, lift_approval_id`) và
      DELETE (chỉ dùng được qua lượt xóa của offboarding, nhờ trigger trên) trên `control_switches`, chỉ
      SELECT trên `platform_freezes`; `dw_provisioner` ghi cả hai; khẳng định ở `test_privileges.py`;
      `test_rls_coverage.py` thấy `control_switches`; policy `tenant_isolation_control_switches` để lane
      `offboarding` xuất và xóa bảng (studio-skeleton:R4.3). Đăng ký khóa `studio.lifecycle.freeze` trong
      `platform.permissions` của tenant-rbac/01 (nhãn "Đóng băng công ty", `scope_kind` `tenant`, `risk`
      `standard` theo bảng phân loại của ticket đó) và thêm khóa vào vai `org_admin` (vai còn do migration sở
      hữu).
2. `RunControlPort` (bên dùng khai trong `dw_agent_runtime.ports`): `require_open(run_context, *, artifacts=())`
   ném `RunHaltedError` (một `ConflictError`, HTTP 409, `details.reason_code` trong `platform_frozen`,
   `tenant_frozen`, `artifact_killed`, `control_state_unavailable`, `principal_inactive`, `tenant_locked`,
   `tenant_offboarding`), và
   `admission_state(tenant_id, artifacts)` cho làn nhận. `SqlRunControl` giữ ảnh chụp theo tenant TTL 5 giây,
   nghe `dw_control_switch` (dựng như listener của `run_events.py`), và quá 30 giây không làm mới thì từ chối
   (đóng khi lỗi; trái cache AccessContext mở khi lỗi, ADR-0024 (Proposed) quyết 4). `principal_inactive`:
   `SqlRunControl` đọc `platform.tenant_members.status` của chủ thể chạy (người kích hoạt hay tài khoản dịch
   vụ) ở cửa nhận và cửa tiếp tục; không `active` thì từ chối (spec R9.1). Cùng chỗ, `SqlRunControl` đọc
   `platform.tenants.status` của công ty: `locked` → `tenant_locked`, `offboarding` hay `offboarded` →
   `tenant_offboarding` (spec R9.2; trạng thái do foundations-hardening/02 canh). `RuntimeSeam.run_control` một
   instance.
3. Gắn cửa (mỗi cửa nhận port bằng injection, không mặc định): runner `start`, `stream`, `resume`;
   `ApproveAndResumeService.decide` trước khi quyết; `RunControlMiddleware` trong `platform_middleware`
   và stack con `sub_agent_spec` (thứ tự ngăn xếp middleware do agent-builder/03 giữ; ticket này cấp
   middleware); gateway có cấu trúc trước `budget.check`, và là cửa đầu tiên của gateway: sau nó là
   `ResidencyGate` của compliance-pdpl/03 (ticket đó chờ ticket này), rồi `LimitsMiddleware` của
   usage-and-limits/03; middleware tóm tắt trước `budget.check`; cửa `resume` chèn trên compare-and-set của
   foundations-hardening/06, ticket này chờ nó;
   `ToolExecutor._execute` trước kiểm quyền (audit `tool.denied`, `policy_decision` `deny_frozen`). Runner
   map `RunHaltedError` sang `_fail(status=CANCELLED, event="run.cancelled")`; middleware lỗi công cụ ném lại
   `RunHaltedError` thay vì báo model. Cửa nhận theo `trigger_kind` (spec R7.7, R7.8): lượt `chat`,
   `manual`, `test` và lần thử của Lượt kiểm định kết thúc `cancelled`; lượt `datahub`, `provider_app`,
   `schedule`, `record_event` đã xếp hàng giữ `queued` và chạy theo thứ tự xếp hàng sau khi gỡ. Làn
   `studio_runs` của workflow-engine/04 thi hành hợp đồng này; ticket này giao hợp đồng kèm test với làn giả.
4. Route `POST /api/v1/admin/freeze` (`studio.lifecycle.freeze`, `Idempotency-Key`, body `reason_code`,
   `reason`; một người cộng audit) và `POST /api/v1/admin/unfreeze` (`studio.lifecycle.freeze`): mở một yêu
   cầu phê duyệt không lượt chạy `studio.lifecycle.unfreeze` nghiêm, tem `studio.lifecycle.freeze`; handler
   `studio.lifecycle.unfreeze.decided` gỡ Đóng băng khi một người khác người xin duyệt (D11; spec R7.10,
   R7.11). Thêm `studio.lifecycle.` vào `strict_approval_prefixes` bằng đúng một dòng `|=` ở composition root
   của API và worker (kèm chú thích), không sửa dòng của ticket khác (tenant-config/05 thêm `config.`, ticket 04
   thêm `studio.publish.` cũng ở đó), và test khẳng định tập tiền tố nghiêm ở cả hai chỗ chứa
   `studio.lifecycle.`; ticket 05 dùng lại tiền tố này cho `studio.lifecycle.revive`.
   `GET /api/v1/control-state` (mọi thành viên; chỉ mã, không lý do chữ); nhà vận hành
   `POST /api/v1/platform/freeze`, `POST /api/v1/platform/unfreeze`,
   `POST /api/v1/platform/tenants/{tenant_id}/freeze`, `POST /api/v1/platform/tenants/{tenant_id}/unfreeze`
   (ngữ cảnh provisioning).
5. Audit `control.freeze.set`, `control.freeze.lifted` (tenant; khi gỡ qua phê duyệt, actor là người quyết
   định và `details.lane` là tên lane, ADR-0011 (Accepted)), `platform.freeze.set`, `platform.freeze.lifted`,
   `platform.tenant_freeze.set`, `platform.tenant_freeze.lifted` (provisioning), mỗi sự kiện trong giao dịch
   của thay đổi; metric `dw_control_refusals_total{door, reason_code}` không nhãn tenant. Hợp đồng
   `admission_state` cho làn `studio_inbound` của workflow-triggers (spec R7.2) và làn `studio_runs` của
   workflow-engine (spec R7.7, R7.8), kèm test hợp đồng với làn giả; làn thật là việc của hai spec đó.
6. Nguyên mẫu (nghiên cứu) trên `langgraph==1.2.11`, `langchain==1.4.1`, `SqlAlchemyCheckpointSaver`:
   một graph `create_agent` được runner chứa, ném `RunHaltedError` ở middleware model và ở executor;
   gọi lại với `None` trên cùng thread có tiếp tục từ checkpoint cuối không, công cụ đã chạy có chạy lại
   không, khóa chống lặp có giữ không, có cần trạng thái `frozen` riêng không. Ghi kết quả vào Comments;
   kết quả quyết Đóng băng có thể tiếp tục cho lượt đang chạy ở W2.

## Tiêu chí chấp nhận

- [ ] R7.1 (AL11): đặt đóng băng giữa một run, lời gọi kế tiếp qua mỗi cửa trong 6 cửa của R7.1 bị từ
      chối, run kết thúc `cancelled` với `reason_code`; tiến trình B thấy công tắc do tiến trình A đặt trong
      5 giây (NOTIFY), và trong TTL khi NOTIFY mất; gỡ kiểm ở một cửa → test của cửa đó đỏ.
- [ ] R7.3 (AL11): database ngắt quá 30 giây → lời gọi công cụ bị từ chối `control_state_unavailable`.
- [ ] R7.2: test hợp đồng với làn `studio_inbound` giả: khi đóng băng `admission_state` trả `tenant_frozen`
      và làn để nguyên sự kiện; sau khi gỡ trả mở và làn xin lượt chạy theo `received_at`.
- [ ] R7.7 (AL11): với làn giả, lượt `chat` và lần thử của Lượt kiểm định tới cửa nhận khi đóng băng →
      `cancelled` `tenant_frozen`, 0 lời gọi model; gỡ nhánh tương tác → test đỏ.
- [ ] R7.8 (AL11): với làn giả, lượt `datahub` đã xếp hàng khi đóng băng giữ `queued`, không `cancelled`;
      sau khi gỡ chạy theo thứ tự xếp hàng.
- [ ] R7.4 (AL12): `org_admin` gỡ đóng băng nguồn `platform` qua `POST /api/v1/admin/unfreeze` → 403.
- [ ] R7.10 (AL18): `POST /api/v1/admin/unfreeze` mở yêu cầu `studio.lifecycle.unfreeze`, Đóng băng còn;
      người khác người xin duyệt → Đóng băng gỡ, audit `control.freeze.lifted` với actor là người duyệt.
- [ ] R7.11 (AL18): người xin gỡ tự duyệt → 409, Đóng băng còn; gỡ `studio.lifecycle.` khỏi tiền tố nghiêm →
      test đỏ.
- [ ] R9.1 (AL17): gỡ thành viên khỏi công ty rồi tiếp tục lượt chạy chờ duyệt của người đó → `cancelled`
      `principal_inactive`, 0 lời gọi model; đặt `suspended` bằng SQL rồi nhận lượt mới của người đó → như
      trên; gỡ kiểm trong `require_open` → test đỏ.
- [ ] R9.2 (AL17): khóa công ty rồi nhận một lượt chạy mới của nó → `cancelled` `tenant_locked`, 0 lời gọi
      model; công ty `offboarding` rồi tiếp tục một lượt chạy chờ duyệt → `cancelled` `tenant_offboarding`; gỡ
      phép đọc trạng thái công ty khỏi `require_open` → test đỏ.
- [ ] R7.5 (AL12): `dw_app` UPDATE trực tiếp để gỡ hay đổi một công tắc ngoài bước gỡ hợp lệ → 23514; `dw_app`
      DELETE một công tắc `kill` mở của công ty `active` → 23514, công tắc còn; gỡ trigger → test đỏ.
- [ ] R10.1: công ty có một công tắc `kill` mở và một Đóng băng đã gỡ chuyển sang `offboarding` → lane
      `offboarding` xuất cả hai dòng một lần rồi xóa chúng; test phủ offboarding (studio-skeleton:R4.3) xanh với
      `platform.control_switches` không có trong `STUDIO_EXCLUSIONS`.
- [ ] R7.6: đặt và gỡ đóng băng ghi đúng một audit trong cùng giao dịch; rollback thì audit không còn.
- [ ] R7.1 (AL16): đóng băng tenant A không chạm run tenant B; đọc công tắc của B từ A → 404; gỡ FORCE
      RLS khỏi `control_switches` → `test_rls_coverage.py` đỏ.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_events.py:97`; spec: R7.1 (mẫu NOTIFY).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:160`; spec: R7.1 (cửa công cụ).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/gateway.py:164`; spec: R7.1 (cửa có cấu trúc).
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/caching_lookup.py:27`; spec: R7.3
  (cache đóng khi lỗi, trái cache khóa tenant mở khi lỗi); ADR-0120 (Accepted) quyết 5.

## Comments

- 2026-10-23 (agent): gộp B10a agent-lifecycle 01 và 12 (nguyên mẫu), cộng phần đóng băng ở executor của
  B8b tools-and-skills 08. DO-28 đã quyết tạm theo khuyến nghị (a): đóng băng hủy run đang chạy ở cửa kế
  tiếp, giữ run chờ duyệt ở nguyên.
- 2026-10-23 (agent): áp quyết định của Đạt ngày 23/10/2026: DO-28 theo C (cửa nhận tách theo
  `trigger_kind`), R7.2 thành hợp đồng với làn `studio_inbound` của workflow-triggers, `principal_inactive`
  (H:org-and-principals:R4.6, chờ org-and-principals/02 cho `platform.tenant_members`), gỡ Đóng băng hai
  người (D11), tiền tố nghiêm `studio.lifecycle.` thêm ở ticket này.
- 2026-10-24 (agent): áp quyết định của Đạt ngày 24/10/2026: chờ foundations-hardening/06 vì cùng sửa đường
  resume, và compliance-pdpl/03 chờ ticket này (thứ tự cửa gateway: công tắc, Lộ trình dữ liệu, hạn mức); đăng
  ký khóa `studio.lifecycle.freeze` ở đây theo quy ước của tenant-rbac/01; `tenant_locked`, `tenant_offboarding`
  (spec R9.2); DELETE trên `control_switches` chỉ cho offboarding (spec R7.5, R10.1); một dòng `|=` cho tiền tố
  của ticket này kèm test tập tiền tố, không thêm cạnh tới tenant-config/05. tools-and-skills/01 chờ ticket này
  để chuỗi bước của `ToolExecutor._execute` có một thứ tự viết (cạnh nằm ở ticket đó).
