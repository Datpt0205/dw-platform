# 01 — Đóng băng toàn nền tảng và theo tenant, kiểm ở mọi cửa của runtime

Status: resolved (2026-11-04, main)
Blocked by: .claude/plans/studio/org-and-principals/issues/02-thanh-vien-cap-tenant.md, .claude/plans/studio/runtime-hardening/issues/03-run-va-outbox-khong-ket.md, .claude/plans/studio/studio-skeleton/issues/01-dang-ky-schema-studio-va-phan-vung.md, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md, .claude/plans/studio/tools-and-skills/issues/01-executor-kiem-schema-va-nha-may.md
Area: studio
Yêu cầu: R7.1, R7.2, R7.3, R7.4, R7.5, R7.6, R7.7, R7.8, R7.10, R7.11, R7.14, R9.1, R9.2, R10.1, AL11, AL12, AL16, AL17, AL18

## Mục tiêu

Đóng băng (nền tảng, tenant) là công tắc trong Postgres, đọc qua một cache đóng khi lỗi mà NOTIFY làm
mới, và mọi cửa của runtime hỏi một `RunControlPort` trước khi làm. Lát này dựng bảng công tắc, port,
adapter và các cửa; ticket 05 dùng chính bảng và các cửa này cho Tắt khẩn cấp (spec R7). Cửa nhận tách
theo `trigger_kind` (DO-28 C), gỡ Đóng băng của công ty cần người thứ hai (D11), và port từ chối chủ thể
không còn `active` (spec R9). Kèm một nguyên mẫu đo việc tiếp tục một lượt chạy sau khi bị chặn ở một
cửa, để quyết Đóng băng có thể tiếp tục cho lượt đang chạy ở W3.

## Việc cần làm

1. Revision Alembic mới (id hex ngẫu nhiên, owner `dw_platform`), chép nguyên văn mục Dữ liệu của spec:
    - `platform.control_switches` với CHECK `scope_type` (`tenant`, `agent`, `workflow`), `action`
      (`freeze`, `kill`), `origin` (`tenant`, `platform`), `reason_code` (`incident`, `maintenance`,
      `abuse`, `test`, `other`), `reason` 1..500 ký tự; `owning_workspace_id` (workspace sở hữu của thành phần đích, để hiển thị và
      xét độ sâu của khóa, RLS không bao giờ đọc; CLAUDE.md, Tenancy and authorization) và `target_id` NULL chỉ khi
      `scope_type='tenant'`; `scope_type` `tool` (ADR-0120 (Accepted) quyết 5) là W2 (spec, Ngoài phạm vi); chỉ mục một
      công tắc mở mỗi nguồn
      `(tenant_id, scope_type, origin, coalesce(target_id, '00000000-0000-0000-0000-000000000000'::uuid)) WHERE lifted_at IS NULL`
      (ADR-0120 (Accepted), sửa đổi 4/11/2026); CHECK `(scope_type = 'tenant') = (action = 'freeze')`, nên Đóng băng
      chỉ ở phạm vi công ty và Tắt khẩn cấp chỉ ở thành phần;
      nên Đóng băng do công ty đặt và do nhà vận hành đặt cho cùng công ty cùng mở được và mỗi bên chỉ gỡ dòng của mình;
      `lift_approval_id` FK ghép `(tenant_id, lift_approval_id)` tới `platform.approval_requests (tenant_id, id)` ON
      DELETE RESTRICT có index riêng, và cùng revision thêm `uq_approval_requests_tenant_id_id UNIQUE (tenant_id, id)`
      trên `platform.approval_requests` (ticket sớm nhất cần nó; ticket 03 dùng lại cho `publish_approval_id`);
      bảng là bảng toàn tenant, một dòng lý do trong danh sách của `test_rls_coverage.py` (công tắc của thành phần toàn
      tenant hay của cả công ty);
      FK `tenant_id → platform.tenants ON DELETE CASCADE` có index `(tenant_id)` riêng, vì chỉ mục một công tắc mở là
      từng phần và không phủ dòng đã gỡ (CLAUDE.md, Data model rules); RLS ENABLE và FORCE theo tenant.
    - Trigger `platform.guard_control_switch()` (chèn chỉ mở, và một dòng `origin='platform'` chỉ do `dw_provisioner`
      chèn; một dòng gỡ một lần, không đổi gì khác;
      dòng `origin='platform'` chỉ `dw_provisioner` gỡ, `lift_approval_id` NULL; dòng `origin='tenant'` chỉ gỡ được khi
      `lift_approval_id` trỏ một yêu cầu `approved` có `approval_type` `studio.lifecycle.unfreeze` (`action` `freeze`)
      hay `studio.lifecycle.revive` (`action` `kill`, ticket 05) và `payload->>'switch_id'` bằng id của chính dòng, nên
      `dw_app` không gỡ được bằng SQL thẳng mà bỏ qua người thứ hai, spec R7.5; DELETE chỉ khi
      `platform.tenants.status` của công ty là `offboarding`, mọi DELETE khác → 23514, spec R7.5, R10.1) và trigger
      `pg_notify('dw_control_switch', ...)` với payload chỉ id và mã, `{"tenant_id", "id"}`, như `run_events.py`
      mang tenant để bên nghe biết ảnh chụp nào phải bỏ (`run_events.py:63-69`); trigger trên
      `platform.platform_freezes` NOTIFY cùng kênh với payload `{"platform": true}`, làm mọi tiến trình bỏ mọi ảnh
      chụp.
        - `platform.platform_freezes` (mặt danh tính, không `tenant_id`): `id`, `reason_code`, `reason`, `set_by` (danh
          tính người vận hành của ngữ cảnh provisioning), `set_at`, `lifted_by`, `lifted_at`; `set_by` và `id` vào ảnh chụp
          của `SqlRunControl` cho `RunHaltedError` của ticket 05 (spec R8.11); tối đa một dòng mở; `dw_app` chỉ
          SELECT; do `dw_provisioner` ghi, audit trong `platform.provisioning_audit`.
    - Grant: `dw_app` SELECT, INSERT, UPDATE (`lifted_by, lifted_at, lift_reason, lift_approval_id`) và
      DELETE (chỉ dùng được qua lượt xóa của offboarding, nhờ trigger trên) trên `control_switches`, chỉ
      SELECT trên `platform_freezes`; `dw_provisioner` ghi cả hai; khẳng định ở `test_privileges.py`;
      `test_rls_coverage.py` thấy `control_switches`; policy `tenant_isolation_control_switches` để lane
      `offboarding` xuất và xóa bảng (studio-skeleton:R4.3). Đăng ký khóa `studio.lifecycle.freeze` trong
      `platform.permissions` của tenant-rbac/01 (nhãn "Đóng băng công ty", `scope_kind` `tenant`, `risk`
      `standard` theo bảng phân loại của ticket đó); INSERT nêu mọi cột NOT NULL của bảng lúc đó, gồm `risk` và `status`
      (`active`) của tenant-rbac/01 và `tenant_grantable` (`true`) của tenant-rbac/02, ticket này chờ ticket đó. Khóa đến
      `tenant_owner` theo quyền tính động của tenant-rbac (mọi khóa `active` có `tenant_grantable` ở mức `tenant`, kể cả
      khóa đăng ký sau lần gán vai trò: tenant-rbac:R2.7, dựng ở tenant-rbac/02 bước 7), không cần dòng quyền nào; cùng
      migration thêm khóa vào vai mẫu `org_admin` cho công ty
      nhân bản mẫu đó về sau, không chạm vai đã nhân bản (tenant-rbac:R3.2).
2. `RunControlPort` (bên dùng khai trong `dw_agent_runtime.ports`): `require_open(run_context, *, door,
artifacts=())`, `door` một StrEnum (`admission`, `start`, `resume`, `node`, `decide`, `model`, `compaction`,
   `tool`, `send`), nhãn `door` của metric ở bước 5 đọc từ đó, ném `RunHaltedError` (một `ConflictError`, HTTP 409, `details.reason_code` trong `platform_frozen`,
   `tenant_frozen`, `artifact_killed`, `control_state_unavailable`, `principal_inactive`, `tenant_locked`,
   `tenant_offboarding`), và
   `admission_state(tenant_id, artifacts)` chỉ cho sự kiện trình kích hoạt chưa có lượt (làn `studio_inbound` của
   workflow-triggers), trả mã từ chối (Đóng băng, Tắt khẩn, `control_state_unavailable`, `tenant_locked`,
   `tenant_offboarding`) hay `None`; mọi lượt đã có, ở cửa nhận của làn `studio_runs`, gọi
   `require_open(run_context, door=admission)`, nơi có chủ thể để kiểm `principal_inactive`. `SqlRunControl` giữ ảnh chụp theo tenant TTL 5 giây,
   nghe `dw_control_switch` (dựng như listener của `run_events.py`), và quá 30 giây không làm mới thì từ chối
   (đóng khi lỗi; trái cache AccessContext mở khi lỗi, ADR-0024 (Proposed) quyết 4). `principal_inactive`:
   `SqlRunControl` đọc `platform.tenant_members.status` của chủ thể chạy (người kích hoạt hay tài khoản dịch
   vụ) chỉ ở `door` `admission`, `start` và `resume`, một truy vấn mỗi lần, ngoài ảnh chụp; không `active` thì từ
   chối (spec R9.1); actor là `system_actor(<lane>)` (id cố định suy từ tên lane trong sổ lane, ADR-0011 (Accepted))
   bỏ qua phép kiểm này, mọi id khác không có dòng `platform.tenant_members` là không `active`, đóng khi thiếu. Cùng chỗ, `SqlRunControl` đọc
   `platform.tenants.status` của công ty: `locked` → `tenant_locked`, `offboarding` hay `offboarded` →
   `tenant_offboarding` (spec R9.2; trạng thái do foundations-hardening/02 canh). `RuntimeSeam.run_control` một
   instance.
3. Gắn cửa (mỗi cửa nhận port bằng injection, không mặc định): runner `start`, `stream`, `resume`;
   `ApproveAndResumeService.decide` trước khi quyết, chỉ với yêu cầu có `run_id`: Đóng băng hay công tắc mở → 409
   với mã đó, yêu cầu giữ `pending` và lượt giữ `waiting_approval`, không hủy (ADR-0120 (Accepted) quyết 7: "keep paused
   runs paused and refuse decisions on them"; spec R7.14), còn `principal_inactive`, `tenant_locked`,
   `tenant_offboarding` ở cửa `resume` hủy lượt như R9; yêu cầu không lượt chạy (`studio.lifecycle.unfreeze`,
   `studio.lifecycle.revive`, `studio.publish.*`) không qua cửa này, vì gỡ Đóng băng phải quyết được trong lúc Đóng
   băng và handler phát hành tự đưa phiên bản về Nháp (spec R7.12); `RunControlMiddleware` trong `platform_middleware`
   và stack con `sub_agent_spec` (thứ tự ngăn xếp middleware do agent-builder/03 giữ; ticket này cấp
   middleware); gateway có cấu trúc ở câu đầu của lời gọi, trước `prompts.render` (`gateway.py:165`), nên là cửa
   đầu tiên của gateway: sau nó là
   `ResidencyGate` của compliance-pdpl/03 (ticket đó chờ ticket này), rồi `LimitsMiddleware` của
   usage-and-limits/03; middleware tóm tắt trước `budget.check`; cửa `resume` chèn trên compare-and-set của
   runtime-hardening/03 đã dựng (`langgraph_runner.py:601`, `begin_resume`), và nhánh `except BaseException` của
   `resume` (`langgraph_runner.py:620-628`), hôm nay ghi mọi lỗi là `failed`, thêm việc map `RunHaltedError` như `stream`;
   ở cửa `resume`, `tenant_frozen`, `platform_frozen` và `control_state_unavailable` để lượt ở trạng thái chờ của nó
   (`waiting_approval`, `waiting_timer`), không đổi gì, lane hẹn giờ thử lại ở nhịp kế tiếp (ADR-0120 (Accepted) quyết
   7: "keep paused runs paused"), còn `artifact_killed`, `principal_inactive`, `tenant_locked`, `tenant_offboarding`
   hủy lượt; runner ghi `reason_code` vào `error` jsonb của lượt (`{"type", "message", "reason_code"}`) và vào
   `details` của audit `run.cancelled`, nơi làn `studio_runs` và màn lượt chạy đọc nó; cửa đầu node là của wrapper nút của workflow-engine/03
   (workflow-engine:R4.8), gọi cùng port với `door` `node`;
   cửa công cụ là bước "công tắc điều khiển" (`control_switch`, chỗ đầu của `TOOL_STEP_ORDER` và mục duy nhất của
   `PENDING_STEPS`, `executor.py:213-242`) của sổ bước; sổ không nhận phụ thuộc (`wflite_host.py:105-116`), nên
   `RunControlPort` thành một trường bắt buộc của `ToolExecutor` và một tham số bắt buộc của `build_tool_executor`, truyền ở
   `apps/api/src/dw_api/bootstrap/runtime.py:232` và `apps/worker/src/dw_worker/composition.py:339`, không mặc định; bước
   không ghi dòng thực thi nào (chưa phân giải gì), và `_audit_event` nhận tên công cụ mà lời gọi xin để audit không thành
   `unknown@unknown` (`executor.py:1171-1172`); mục `build_tool_executor_steps(deps)` mà tools-and-skills/01 dựng ở
   composition root (tools-and-skills:R2.6, tools-and-skills:R2.7; H-3): ticket này đăng ký đúng một bước đó vào sổ, ở
   chỗ đầu mà thứ tự R2.6 của tools-and-skills dành cho nó, trước `resolve` và kiểm quyền: ghi audit `tool.denied`
   (`policy_decision` `deny_frozen` hay `deny_killed`, tên công cụ mà lời gọi xin, chưa phân giải) rồi ném
   `RunHaltedError`, không `PermissionDeniedError` của `_refuse` (`executor.py:1117`), để runner hủy lượt; và gỡ nó khỏi danh sách bước chờ đăng ký của sổ, không viết lại chuỗi bước của
   `ToolExecutor._execute` và không gọi bước nào ngoài sổ. Runner
   map `RunHaltedError` sang `_fail(status=CANCELLED, event="run.cancelled")`; middleware lỗi công cụ ném lại
   `RunHaltedError` thay vì báo model. Cửa nhận theo `trigger_kind` (spec R7.7, R7.8): lượt `chat`,
   `manual`, `test`, `replay` (ADR-0120 (Accepted) quyết 7) và lần thử của Lượt kiểm định kết thúc `cancelled`; lượt `datahub`, `provider_app`,
   `schedule`, `record_event` đã xếp hàng giữ `queued` và chạy theo thứ tự xếp hàng sau khi gỡ. Với
   `principal_inactive` (spec R9.1): lượt `datahub`, `provider_app`, `record_event` đang `queued` của tài khoản dịch vụ
   không `active` giữ `queued` và chạy theo thứ tự đến khi tài khoản `active` lại (workflow-engine:R5.17,
   org-and-principals:R4.9), mọi lượt khác kết thúc `cancelled` (workflow-engine:R5.15); `tenant_locked`,
   `tenant_offboarding` kết thúc mọi loại `cancelled` (spec R9.2; workflow-engine:R5.18); `control_state_unavailable`
   giữ lượt do trình kích hoạt ở `queued` (workflow-engine:R5.16), còn lượt tương tác kết thúc `cancelled`. Làn `studio_runs` của
   workflow-engine/04 thi hành hợp đồng này; ticket này giao hợp đồng kèm test với làn giả.
4. Route `POST /api/v1/admin/freeze` (`studio.lifecycle.freeze`, `Idempotency-Key`, body `reason_code`,
   `reason`; một người cộng audit; trả 201 với `{switch_id}`; đã có Đóng băng `origin` `tenant` mở → 409 `conflict` với `details.reason_code`
   `already_frozen`, 0 audit) và `POST /api/v1/admin/unfreeze` (`studio.lifecycle.freeze`, `Idempotency-Key`): mở
   một yêu cầu phê duyệt không lượt chạy `studio.lifecycle.unfreeze` nghiêm, tem `studio.lifecycle.freeze`, payload
   chỉ `{switch_id}` của dòng `origin` `tenant` đang mở, trả 202 với `{approval_id}` (không dòng nào → 409 `not_frozen`; một yêu cầu gỡ còn `pending`
   cho dòng đó → 409 `lift_pending`, không mở yêu cầu thứ hai, giữ bằng chỉ mục duy nhất từng phần
   `uq_approval_requests_control_lift_pending` trên `platform.approval_requests` `(tenant_id, (payload->>'switch_id'))
WHERE approval_type IN ('studio.lifecycle.unfreeze', 'studio.lifecycle.revive') AND status = 'pending'`, cùng tiền lệ
   `uq_approval_requests_dw_autonomy_raise_pending` (`db/migrations/versions/92abd4932780_dw_autonomy_raise_pending_unique.py`),
   nên hai lời gọi song song cho một 409 thay vì hai yêu cầu; mã `second_person_required` và lời bình bắt buộc của loại
   nghiêm đã có ở `approval_flow.py:139-157`, nên test gửi `comment`); handler `studio.lifecycle.unfreeze.decided` gỡ đúng dòng
   `switch_id` khi một người khác người xin duyệt, ghi `lift_approval_id` (D11; spec R7.10, R7.11), và dòng đã gỡ thì
   kết thúc không đổi gì, không audit, không lỗi, để lần giao lại không lặp 23514. Thêm `studio.lifecycle.` vào `strict_approval_prefixes` bằng đúng một dòng `|=` ở composition root
   của API và worker (kèm chú thích), không sửa dòng của ticket khác (tenant-config/05 thêm `config.`, ticket 04
   thêm `studio.publish.` cũng ở đó), và test khẳng định tập tiền tố nghiêm ở cả hai chỗ chứa
   `studio.lifecycle.`; ticket 05 dùng lại tiền tố này cho `studio.lifecycle.revive`.
   `GET /api/v1/control-state` (mọi thành viên; chỉ mã, không lý do chữ); nhà vận hành
   `POST /api/v1/platform/freeze`, `POST /api/v1/platform/unfreeze`,
   `POST /api/v1/platform/tenants/{tenant_id}/freeze`, `POST /api/v1/platform/tenants/{tenant_id}/unfreeze`
   (ngữ cảnh provisioning); route của nhà vận hành chỉ đặt và gỡ dòng `origin` `platform`, không bao giờ gỡ Đóng băng do
   công ty đặt (D11).
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
   kết quả quyết Đóng băng có thể tiếp tục cho lượt đang chạy ở W3.

## Tiêu chí chấp nhận

- [x] R7.1 (AL11): đặt đóng băng giữa một run, lời gọi kế tiếp qua mỗi cửa mà ticket này gắn (model ở vòng
      agent, sub-agent, gateway có cấu trúc, tóm tắt, công cụ) bị từ chối, run kết thúc `cancelled` với `reason_code`
      (cửa đầu node thử ở workflow-engine/03); tiến trình B thấy công tắc do tiến trình A đặt trong 5 giây (NOTIFY mang
      `tenant_id`), và trong TTL khi NOTIFY mất; Đóng băng của nền tảng → mọi tiến trình thấy trong 5 giây; metric
      `dw_control_refusals_total` mang `door` của cửa; gỡ kiểm ở một cửa → test của cửa đó đỏ.
- [x] R7.14 (AL11): Đóng băng đặt khi một lượt đang `waiting_approval`; người được quyết định duyệt → 409
      `tenant_frozen`, yêu cầu vẫn `pending`, lượt vẫn `waiting_approval`; gỡ Đóng băng rồi duyệt → lượt tiếp tục; lượt
      `waiting_timer` tới giờ trong lúc Đóng băng → vẫn `waiting_timer`, chạy tiếp sau khi gỡ; yêu cầu
      `studio.lifecycle.unfreeze` vẫn quyết được trong lúc Đóng băng; lượt bị hủy ở cửa khác mang `reason_code` trong
      `error` và trong audit `run.cancelled`; cho cửa `decide` hay `resume` hủy lượt khi Đóng băng → test đỏ.
- [x] R7.1 (AL11): sổ bước của API và của worker có bước "công tắc điều khiển" của ticket này ở chỗ đầu của thứ tự
      R2.6, danh sách bước chờ đăng ký không còn nó, và lời gọi công cụ khi Đóng băng → `tool.denied` với `deny_frozen`
      trước kiểm quyền; gỡ dòng đăng ký của ticket này mà không đưa bước lại vào danh sách chờ → test sổ của
      tools-and-skills:R2.7 đỏ, nêu bước; đăng ký bước sau kiểm quyền → test sổ đỏ.
- [x] R7.3 (AL11): database ngắt quá 30 giây → lời gọi công cụ bị từ chối `control_state_unavailable`.
- [x] R7.2: test hợp đồng với làn `studio_inbound` giả: khi đóng băng `admission_state` trả `tenant_frozen`
      và làn để nguyên sự kiện; sau khi gỡ trả mở và làn xin lượt chạy theo `received_at`.
- [x] R7.7 (AL11): với làn giả, lượt `chat`, `replay` và lần thử của Lượt kiểm định tới cửa nhận khi đóng băng →
      `cancelled` `tenant_frozen`, 0 lời gọi model; gỡ nhánh tương tác → test đỏ.
- [x] R7.8 (AL11): với làn giả, lượt `datahub` đã xếp hàng khi đóng băng giữ `queued`, không `cancelled`;
      sau khi gỡ chạy theo thứ tự xếp hàng.
- [x] R7.4 (AL12): `org_admin` gỡ đóng băng nguồn `platform` qua `POST /api/v1/admin/unfreeze` → 403.
- [x] R7.10 (AL18): `POST /api/v1/admin/unfreeze` mở yêu cầu `studio.lifecycle.unfreeze` với `switch_id`, Đóng
      băng còn; người khác người xin duyệt → Đóng băng gỡ, `lift_approval_id` ghi, audit `control.freeze.lifted` với actor
      là người duyệt; xin gỡ lần hai khi yêu cầu đầu còn `pending` → 409 `lift_pending`; sự kiện `.decided` giao lại sau
      khi đã gỡ → không đổi gì, không audit; đặt Đóng băng khi đã có một Đóng băng của công ty mở → 409
      `already_frozen`; `dw_app` INSERT một dòng `origin='platform'`, hay một dòng `tenant` với `action` `kill` → 23514;
      hai `POST /admin/unfreeze` song song khác `Idempotency-Key` → một yêu cầu, một 409 `lift_pending`; nhà vận hành đặt Đóng băng cho công ty đang có Đóng băng của chính công ty → hai dòng mở, công ty
      gỡ dòng của mình thì Đóng băng của nhà vận hành vẫn chặn.
- [x] R7.11 (AL18): người xin gỡ tự duyệt → 409 `conflict` với `details.reason_code` `second_person_required` (mã mà
      `_enforce_strict_rules` đã đặt cho mọi loại dưới tiền tố nghiêm, `approval_flow.py:139-152`), Đóng băng còn; gỡ
      `studio.lifecycle.` khỏi tiền tố nghiêm → test đỏ.
- [x] R9.1 (AL17): gỡ thành viên khỏi công ty rồi tiếp tục lượt chạy chờ duyệt của người đó → `cancelled`
      `principal_inactive`, 0 lời gọi model; đặt `suspended` bằng SQL rồi nhận lượt mới của người đó → như
      trên; gỡ kiểm trong `require_open` → test đỏ.
- [x] R9.1 (AL17): lượt của `system_actor(<lane>)` qua cửa nhận khi không có dòng `tenant_members` → chạy; một id
      người không có dòng → `principal_inactive`.
- [x] R9.1 (AL17): với làn giả gọi `require_open(..., door=admission)`, tài khoản dịch vụ `suspended` rồi lượt `datahub` của nó tới cửa nhận → giữ `queued`
      với `principal_inactive`, không `cancelled`, 0 lời gọi model; kích hoạt lại tài khoản → lượt chạy theo thứ tự
      đến; đặt nhánh `cancelled` cho lượt `datahub` → test đỏ.
- [x] R9.2 (AL17): khóa công ty rồi nhận một lượt chạy mới của nó → `cancelled` `tenant_locked`, 0 lời gọi
      model; công ty `offboarding` rồi tiếp tục một lượt chạy chờ duyệt → `cancelled` `tenant_offboarding`; gỡ
      phép đọc trạng thái công ty khỏi `require_open` → test đỏ.
- [x] R7.5 (AL12): `dw_app` UPDATE trực tiếp để gỡ một Đóng băng `origin` `tenant` không `lift_approval_id`, với
      `lift_approval_id` của một yêu cầu `pending`, khác loại hay của công tắc khác, hay để đổi một cột khác → 23514;
      `dw_app`
      DELETE một công tắc `kill` mở của công ty `active` → 23514, công tắc còn; gỡ trigger → test đỏ.
- [x] R10.1: công ty có một công tắc `kill` mở và một Đóng băng đã gỡ chuyển sang `offboarding` → lane
      `offboarding` xuất cả hai dòng một lần rồi xóa chúng; test phủ offboarding (studio-skeleton:R4.3) xanh với
      `platform.control_switches` không có trong `STUDIO_EXCLUSIONS`.
- [x] R7.6: đặt và gỡ đóng băng ghi đúng một audit trong cùng giao dịch; rollback thì audit không còn.
- [x] R7.1 (AL16): đóng băng tenant A không chạm run tenant B; `GET /api/v1/control-state` của người tenant A khi B
      đóng băng → mở; `dw_app` với `app.tenant_id` của A đọc `platform.control_switches` → 0 dòng của B; lệnh gỡ `POST /api/v1/admin/unfreeze` của người tenant A không chạm dòng của B; gỡ FORCE RLS khỏi `control_switches` hay bỏ dòng
      lý do bảng toàn tenant → `test_rls_coverage.py` đỏ.
- [x] Xong: `uv run python -m pytest packages/python/dw_agent_runtime/tests packages/python/dw_platform/tests apps/api/tests -k "control or freeze or run_control"` xanh.

## Nguồn

- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_events.py:97`; spec: R7.1 (mẫu NOTIFY).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:213-242`; spec: R7.1 (cửa công cụ, bước
  `control_switch` của sổ bước của tools-and-skills/01, đang ở `PENDING_STEPS`; tools-and-skills:R2.7; H-3).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/model/gateway.py:165`; spec: R7.1 (cửa có cấu trúc, trước
  `prompts.render`).
- ADR-0120 (Accepted) quyết 6 (cache đóng khi lỗi), trái cache AccessContext mở khi lỗi (ADR-0024 (Proposed) quyết 4);
  spec: R7.3.

## Comments

- 2026-10-23 (agent): gộp B10a agent-lifecycle 01 và 12 (nguyên mẫu), cộng phần đóng băng ở executor của
  B8b tools-and-skills 08. DO-28 đã quyết tạm theo khuyến nghị (a): đóng băng hủy run đang chạy ở cửa kế
  tiếp, giữ run chờ duyệt ở nguyên.
- 2026-10-23 (agent): áp quyết định của Đạt ngày 23/10/2026: DO-28 theo C (cửa nhận tách theo
  `trigger_kind`), R7.2 thành hợp đồng với làn `studio_inbound` của workflow-triggers, `principal_inactive`
  (H:org-and-principals:R4.6, chờ org-and-principals/02 cho `platform.tenant_members`), gỡ Đóng băng hai
  người (D11), tiền tố nghiêm `studio.lifecycle.` thêm ở ticket này.
- 2026-10-24 (agent): áp quyết định của Đạt ngày 24/10/2026: chờ runtime-hardening/03 vì cùng sửa đường
  resume, và compliance-pdpl/03 chờ ticket này (thứ tự cửa gateway: công tắc, Lộ trình dữ liệu, hạn mức); đăng
  ký khóa `studio.lifecycle.freeze` ở đây theo quy ước của tenant-rbac/01; `tenant_locked`, `tenant_offboarding`
  (spec R9.2); DELETE trên `control_switches` chỉ cho offboarding (spec R7.5, R10.1); một dòng `|=` cho tiền tố
  của ticket này kèm test tập tiền tố, không thêm cạnh tới tenant-config/05. tools-and-skills/01 chờ ticket này
  để chuỗi bước của `ToolExecutor._execute` có một thứ tự viết (cạnh nằm ở ticket đó).
- 2026-10-24 (agent): vòng sửa thứ tư: lượt `datahub`, `provider_app`, `record_event` của tài khoản dịch vụ không
  `active` giữ `queued` thay vì `cancelled` (quyết định của Đạt ngày 24/10/2026, spec R9.1); chờ studio-skeleton/01
  (test phủ offboarding mà spec R10.1 dựa vào) và tenant-rbac/02 (INSERT khóa nêu `tenant_grantable`, Quyết định tạm
  của spec).
- 2026-10-24 (agent): kiểm vòng sửa thứ tư: bước 3 và spec R9.1 nêu rõ lượt được giữ là lượt `datahub`,
  `provider_app`, `record_event` đang `queued`, khớp org-and-principals:R4.6, R4.9; lượt tới cửa tiếp tục kết thúc
  `cancelled` như lượt khác.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt b, theo các Quyết định tạm cùng ngày của spec: người xin tự quyết
  `studio.lifecycle.unfreeze` nhận 409 `second_person_required` (V4.P9; spec R7.11, AL18); bước 3 dẫn
  workflow-engine:R5.17 cho lượt được giữ `queued` và workflow-engine:R5.15 cho lượt bị hủy; bước 1 nói khóa
  `studio.lifecycle.freeze` đến `tenant_owner` theo quyền tính động của tenant-rbac và vai mẫu nhận nó qua migration
  sửa mẫu, thay câu "vai còn do migration sở hữu".
- 2026-10-24 (agent): kiểm lượt b: INSERT của bước 1 nêu `status` `active`, vì quyền tính động của `tenant_owner` chỉ
  tính khóa `active` (tenant-rbac/02 bước 7). Tiêu chí R7.11 khẳng định mã `second_person_required` mà tenant-config/05
  đặt, trong khi ticket này không chờ ticket đó (Quyết định tạm của spec về tiền tố nghiêm); cạnh hay cách khác do
  người lập kế hoạch quyết, chưa thêm ở đây.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt c, theo các Quyết định tạm cùng ngày của spec: chờ tenant-config/05, vì
  tiêu chí R7.11 khẳng định mã `second_person_required` mà ticket đó đặt ở `_enforce_strict_rules`; cạnh này thay câu
  "không thêm cạnh tới tenant-config/05" và câu "chưa thêm ở đây" của các dòng trên, còn dòng `|=` của ticket này
  vẫn không là lý do cho cạnh nào. Đóng băng có thể tiếp tục cho lượt đang chạy là W3 (Mục tiêu, bước 6), khớp
  requirements.md và ADR-0120 (Accepted). Bước 1 dẫn tenant-rbac:R2.7 cho luật động của `tenant_owner`.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt d, theo Quyết định tạm cùng ngày của spec: bước 1 thêm index `(tenant_id)`
  cho FK `tenant_id` của `platform.control_switches`, vì chỉ mục một công tắc mở là từng phần (CLAUDE.md, Data model
  rules: mọi khóa ngoại có chỉ mục ở phía mình).
- 2026-10-26 (agent): lượt h, đợt 2, theo V4.31 của Đạt và H-3: chiều cạnh với tools-and-skills/01 đảo, ticket này chờ
  ticket đó (bảng cạnh của lượt h), vì ticket đó dựng sổ bước có thứ tự của `ToolExecutor` ở composition root và ghi bước
  công tắc điều khiển vào danh sách chờ đăng ký; ticket này chỉ đăng ký bước của mình vào sổ (bước 3, tiêu chí R7.1),
  không viết lại chuỗi bước. Câu "tools-and-skills/01 chờ ticket này" của dòng 2026-10-24 không còn áp.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness trên `7818f7b` (builder check và boundary walk trong một subagent, vì ticket có migration và route; đối chiếu `executor.py`, `gateway.py`, `run_events.py`, `approval_flow.py` và workflow-engine/03, /04; lượt xác nhận ngữ cảnh mới sau các sửa), 1 CRITICAL và 10 HIGH đã sửa theo khuyến nghị. CRITICAL: (1) R7.1 hủy lượt ở cửa quyết định phê duyệt, trái ADR-0120 (Accepted) quyết 7 ("keep paused runs paused and refuse decisions on them"): cửa `decide` trả 409, lượt giữ `waiting_approval`, thêm R7.14 ở spec. HIGH: (2) cửa `decide` chỉ cho yêu cầu có `run_id`, nên gỡ Đóng băng và bật lại quyết được; (3) Đóng băng của công ty và của nhà vận hành chung một chỗ mở: chỉ mục theo `origin`, route của nhà vận hành chỉ gỡ dòng của mình; (4) gỡ một lần không buộc phê duyệt: trigger đòi `lift_approval_id` của yêu cầu `approved` đúng loại với `switch_id` của dòng, FK ghép, và `uq_approval_requests_tenant_id_id` dời về ticket này (ticket sớm nhất cần nó); (5) yêu cầu gỡ ghim `switch_id`, `lift_pending`, handler giao lại không lỗi; (6) `already_frozen`, `not_frozen`; (7) AL16 "đọc công tắc của B → 404" không route nào thử được: thay bằng `control-state`, đọc thẳng bằng `dw_app` và lý do bảng toàn tenant, cột `owning_workspace_id` thay `workspace_id` mà RLS không đọc; (8) NOTIFY chỉ id không cho biết tenant: payload `{tenant_id, id}`, Đóng băng của nền tảng NOTIFY bỏ mọi ảnh chụp; (9) `door` là tham số của `require_open`, nguồn của nhãn metric, kiểm chủ thể và công ty chỉ ở cửa nhận, bắt đầu, tiếp tục; (10) cửa đầu node là của workflow-engine/03, `control_state_unavailable` ở cửa nhận theo workflow-engine:R5.16, `replay` là tương tác; (11) dẫn sai mã đã dựng: `executor.py:160` thành `:213-242` với `RunHaltedError` thay `_refuse`, gateway đặt trước `prompts.render`, `caching_lookup.py:27` không phải mẫu mở khi lỗi. Nếu sai thì: (1) Đạt đổi ADR-0120 (Accepted) quyết 7 trước; (3) một chỗ mở mỗi công ty và Đóng băng của nhà vận hành nâng `origin`; (4) luật người thứ hai chỉ ở handler; (8) payload chỉ id và mọi NOTIFY bỏ mọi ảnh chụp.
- 2026-11-04 (agent): MEDIUM để lại: (a) phát lại `Idempotency-Key` của `POST /admin/freeze` sau khi đã gỡ trả lại câu trả lời cũ (ADR-0108 (Accepted) quyết 4); (b) lượt `schedule` giữ `queued` suốt Đóng băng dài bung ra sau khi gỡ: ADR-0120 (Accepted) quyết 7 giữ chúng, số lượt do lịch của workflow-triggers giới hạn; (c) `scope_type` `tool` và `workspace_archived` là W2 (spec, Ngoài phạm vi); (d) cảnh báo collision của script giữa 04 và 05 không chạm ticket này.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (một subagent ngữ cảnh mới, mở đúng các tệp đã dẫn), 8 HIGH và 3 dẫn sai, đã sửa: (12) lượt `waiting_timer` đánh thức trong lúc Đóng băng giữ chờ, không hủy; (13) actor `system_actor(<lane>)` bỏ qua kiểm chủ thể, id khác không có dòng là không `active`; (14) `admission_state` chỉ cho sự kiện chưa có lượt, lượt đã có qua `require_open(door=admission)`; (15) ADR-0120 (Accepted) quyết 5, 6 nay có sửa đổi 4/11/2026 ghi một chỗ mở mỗi nguồn và tham số `door` (`9a6a4b9`); (16) CHECK `scope_type` đi với `action`, `dw_app` không chèn dòng `origin='platform'`; (17) `lift_pending` giữ bằng chỉ mục duy nhất từng phần; (18) `reason_code` của lượt bị hủy ghi ở `error` và audit; (19) bước công tắc của executor không dòng thực thi, audit mang tên công cụ xin. Dẫn sai: sổ bước không nhận `deps`, `RunControlPort` là trường bắt buộc của `ToolExecutor`; `second_person_required` đã có ở `approval_flow.py:139-152`, nên bỏ cạnh tới tenant-config/05; compare-and-set của runtime-hardening/03 đã dựng, map `RunHaltedError` thêm ở nhánh lỗi của `resume`. Nếu sai thì: (12) hủy lượt chờ hẹn giờ như lượt đang chạy; (13) lượt nền cũng cần dòng thành viên; (17) kiểm `lift_pending` ở ứng dụng dưới khóa dòng công tắc.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-04 (agent): resolved.
    - Khác ticket (agent, theo ủy quyền 31/10/2026): (1) Một chỉ mục `(tenant_id, lift_approval_id)` phục vụ cả FK ghép của
      `lift_approval_id` lẫn FK `tenant_id` (dẫn đầu bằng `tenant_id`), không thêm chỉ mục `(tenant_id)` riêng. Nếu sai thì: thêm
      `ix_control_switches_tenant_id` ở revision mới. (2) `owning_workspace_id` có FK ghép `(owning_workspace_id, tenant_id)` tới
      `platform.workspaces` ON DELETE RESTRICT kèm chỉ mục, vì `test_rls_coverage.py` (R9.4) đòi ở mọi bảng có cột này, và CHECK
      `ck_control_switches_owning_workspace` (NULL đúng khi `scope_type='tenant'`). Nếu sai thì: bỏ FK và dòng R9.4 cho bảng này.
      (3) Trigger gỡ dòng `origin='tenant'` còn đòi một dòng `platform.approval_decisions` `approved` do người khác người xin, để
      một lệnh UPDATE trạng thái yêu cầu không thay được người thứ hai (D11). Nếu sai thì: chỉ đọc `status`. (4) DELETE qua được khi
      dòng công ty không còn (CASCADE từ chính `platform.tenants`), ngoài ra chỉ khi `offboarding`. Nếu sai thì: FK RESTRICT. (5) Actor
      của lane nhận ra qua `RUN_REQUESTING_LANES` (`dw_work`) trong `dw_agent_runtime.run_control`, `lane_actors()` đọc ở cả hai
      composition root; không theo phiên bản UUID vì `seed_env` cấp UUID v5 cho người dùng mẫu. Nếu sai thì: tiêm tên lane từ sổ
      lane của mỗi tiến trình. (6) `RunControlMiddleware` (agent, sub-agent) và tóm tắt lấy port từ `spec.executor.run_control`
      (trường bắt buộc của `ToolExecutor`), không thêm trường vào `AgentSpec`. Nếu sai thì: thêm `AgentSpec.run_control`. (7) Cửa
      `start` của runner hỏi sau khi ghi dòng lượt (sau kiểm hạn mức), nên lượt bị từ chối có dòng `cancelled` mang `reason_code`;
      `stream` từ chối trước khi tạo task, trả 409. Nếu sai thì: từ chối trước khi ghi, không dòng. (8) Wrapper Bước của wf-lite
      (`compile.py`) ném lại `RunHaltedError` thay vì bàn giao Bước, nếu không cửa công cụ và gateway của lượt DW thành bàn giao
      chứ không hủy (failure-modes #5). (9) `GET /control-state` trả `{state, platform_freeze, freezes[{origin, reason_code,
set_at}]}`, không chữ lý do, không id. (10) `Idempotency-Key` không bắt buộc ở hai route `/admin`; route gỡ của nhà vận hành
      cho một công ty nhận `{reason}` tùy chọn vào `lift_reason`, route nền tảng không thân. (11) Bước công tắc ghi
      `policy_decision` `deny_control_state` cho `control_state_unavailable`. (12) Lane `dw_timers` ghi log lượt bị giữ và để lease
      giữ mục, nên thử lại sau lease (15 phút) chứ không ở nhịp kế. (13) `RunHaltedError` mang `set_by`, `switch_id` (ảnh chụp
      giữ `id`, `set_by`) cho ticket 05; thứ tự lý do: nền tảng, Đóng băng của nhà vận hành, của công ty, rồi Tắt khẩn; ở
      `admission` Tắt khẩn đứng trước.
    - Nguyên mẫu (bước 6, đo trên langgraph 1.2.11, langchain 1.4.1, langchain-core 1.6.3, cả `InMemorySaver` lẫn
      `SqlAlchemyCheckpointSaver`, `durability="sync"`; script ở scratchpad của phiên, không vào repo): `RunHaltedError` ra khỏi
      `ainvoke` để checkpoint ở đúng bước lỗi (`aget_state().next` là `model` hay `tools`, lỗi lưu dạng chuỗi repr);
      `ainvoke(None)` trên cùng thread tiếp tục từ đó: lời gọi model bị chặn được gọi lại, công cụ đã chạy không chạy lại; công cụ
      bị chặn chạy lại với cùng AIMessage và cùng `tool_call_id`, không lời gọi model mới; công cụ song song đã xong không chạy
      lại. Kết luận: Đóng băng có thể tiếp tục lượt đang chạy ở W3 mà LangGraph không cần trạng thái `frozen` (trạng thái của nền
      tảng chỉ để runner không kết thúc lượt). Rủi ro: công cụ ném sau tác động thì chạy lại tác động, nên kiểm phải trước handler
      (bước công tắc là bước đầu) và khóa chống lặp phải gồm `tool_call_id` (ổn định qua lần tiếp tục); tiếp tục bằng đầu vào mới
      thay vì `None` bỏ dở lời gọi công cụ và đổi id; lý do dừng phải ở dòng lượt, không ở checkpoint.
    - Test: unit `test_run_control.py` 35 ca (bước công tắc với bốn lý do, cửa gateway trước `prompts.render`, middleware agent và
      sub-agent, middleware lỗi công cụ ném lại, ảnh chụp: TTL, NOTIFY, NOTIFY nền tảng, 30 giây, thứ tự lý do, Tắt khẩn, chủ thể,
      actor của lane, trạng thái công ty, metric không nhãn tenant, dọn ảnh chụp cũ); `test_tool_steps.py` (sổ đủ R2.6, bỏ hay
      đặt sau `scopes` → `ConfigError` nêu `control_switch`, ca dừng ở bước công tắc); `test_approval_flow.py` (cửa `decide` ×3 lý
      do, yêu cầu không lượt quyết được khi Đóng băng); `test_context_compaction.py`; `test_agent_factory.py` (thuộc tính thứ tám
      "frozen run refused"); `test_channel_commands.py` (tiền tố nghiêm ở worker). Integration `test_run_control_db.py` 20 ca
      (NOTIFY qua tiến trình, TTL khi mất NOTIFY, Đóng băng nền tảng ≤ 5 giây, AL16, hủy giữa lượt với lý do ở `error` và audit,
      R7.14 duyệt và hẹn giờ, R9.1 ×3, R9.2 ×2, làn giả R7.2, R7.7 ×3, R7.8, R9.1 `datahub`, actor của lane);
      `test_control_switches_db.py` 13 ca (23514 từng luật của trigger, hai nguồn cùng mở, gỡ của nhà vận hành, FK ghép chéo
      tenant, xóa ngoài offboarding, RLS, chỉ mục chờ gỡ, payload NOTIFY); `test_freeze_api.py` 10 ca (R7.4, R7.6, R7.10, R7.11,
      AL16, hai yêu cầu song song, route nhà vận hành); `test_offboarding.py` (R10.1); `test_privileges.py` (grant theo cột,
      provisioner); `test_rls_coverage.py`; `test_offboarding_coverage.py` và `test_permission_catalogue.py` xanh.
    - `mutations/01.yaml` 29 đột biến, chưa chạy bằng `mutate.py`; bộ test mới xanh ngay lần đầu nên chạy tay 10 đột biến (bước
      công tắc, cửa gateway, cửa `decide`, giữ ở `resume`, kiểm chủ thể, kiểm công ty, ánh xạ hủy của runner, middleware lỗi công
      cụ, cửa sub-agent, 30 giây), mỗi cái đỏ.
    - `reviewing-feature-security` (đọc): tenant chỉ từ access context hay sự kiện outbox; route nhà vận hành sau
      `RequireProvisioningContext`; RLS FORCE và đọc thẳng chéo tenant 0 dòng; người không giữ khóa 403; người xin tự quyết 409;
      `dw_app` không gỡ, không chèn dòng nhà vận hành, không xóa ngoài offboarding (DB tự chặn); metric không nhãn tenant; NOTIFY chỉ
      id và mã; ảnh chụp đóng khi lỗi.
    - MEDIUM: (a) bước 3 nói `control_state_unavailable` hủy lượt tương tác ở cửa nhận, workflow-engine:R5.16 nói giữ `queued`
      mọi loại; chủ bảng là workflow-engine/04, làn giả theo R5.16. (b) Đóng băng đặt giữa cửa `decide` và cửa `resume` (cùng ảnh
      chụp trong một tiến trình, cửa sổ nhỏ) để lại quyết định đã duyệt và lượt `waiting_approval` mà không lane nào thử lại;
      ticket 05 hay workflow-engine/08. (c) Lane hẹn giờ thử lại sau lease 15 phút. (d) Hai `POST /admin/freeze` song song khác
      khóa: một 201, một 409 nhờ chỉ mục, chưa có test riêng.
    - Còn ở lúc đóng hàng đợi: `mutate.py` cho `mutations/01.yaml`; `make test-integration` toàn bộ; P50/P95/P99 của
      `POST /api/v1/admin/freeze`, `POST /api/v1/admin/unfreeze`, `GET /api/v1/control-state`, bốn route `/platform`, và chi phí
      `require_open` ở `start`, `decide`, `tool`, `model` (một truy vấn ảnh chụp mỗi 5 giây mỗi công ty; một truy vấn trạng thái ở
      `start`/`resume`) so với commit đầu hàng đợi; `/code-review`; `reviewing-deployment-security` (route mới).
