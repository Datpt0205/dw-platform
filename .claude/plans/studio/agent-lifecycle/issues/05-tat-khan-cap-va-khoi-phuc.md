# 05 — Tắt khẩn cấp agent và quy trình, bật lại cần hai người, hủy việc đang chờ

Status: resolved (2026-11-05, main)
Blocked by: 01, 03, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md
Area: studio
Yêu cầu: R8.1, R8.2, R8.3, R8.4, R8.5, R8.6, R8.7, R8.8, R8.9, R8.10, R8.11, AL13, AL14, AL15, AL16, AL28, AL29

## Mục tiêu

Người có quyền Tắt khẩn cấp một agent hay quy trình: cửa chặn lượt chạy `live` và `test` mới, lane hủy
lượt chạy và phê duyệt đang chờ cùng trình kích hoạt, và bật lại cần một người thứ hai; lượt `simulate`
vẫn chạy để người dựng sửa (spec R8). Lời gọi nhà cung cấp đang bay khi Tắt khẩn hay Đóng băng được ghi theo kết quả
có kiểu của egress (ADR-0120 (Accepted) quyết 7; V4.30), và lượt bị hủy còn tác động chưa ai giải để lại audit đứng
tên người đặt công tắc (H-22). Dùng công tắc và các cửa của ticket 01, hợp đồng Giai đoạn của ticket 03.

## Việc cần làm

1. Route `POST /api/v1/studio/{agents|workflows}/{artifact_id}/kill` (`studio.lifecycle.kill` ở độ sâu tới
   `owning_workspace_id` của thành phần, ADR-0120 (Accepted) quyết 7 "in the artifact's workspace"; `Idempotency-Key`;
   thân `reason_code` theo CHECK của bảng và `reason` 1..500 ký tự như Đóng băng; một người cộng audit). Cùng ánh xạ đoạn,
   404 và 403 của ticket 03 bước 6: công ty khác, id không có, loại lưu khác đoạn hay ngoài độ sâu → 404; đọc được mà
   thiếu khóa → 403. Ghi một dòng `platform.control_switches` `action='kill'`, `origin='tenant'`, `owning_workspace_id`
   của thành phần, audit `control.kill.set` và outbox `control.switch.changed` v1 với payload chỉ id `{tenant_id,
switch_id}` trong cùng giao dịch; trả 201 với `{switch_id}`;
   thành phần đã có một công tắc `kill` mở → 409 `conflict` với `details.reason_code` `already_killed`, 0 audit, không
   500 từ chỉ mục một công tắc mở.
   `POST /api/v1/studio/{agents|workflows}/{artifact_id}/revive-requests` (`studio.lifecycle.kill`, cùng độ sâu, 404 và
   403; `Idempotency-Key`): mở một yêu cầu phê duyệt `studio.lifecycle.revive` nghiêm (tem `studio.lifecycle.kill`;
   tiền tố `studio.lifecycle.` của ticket 01), `workspace_id` là `owning_workspace_id`, payload chỉ `{switch_id}` của
   công tắc `kill` đang mở, trả 202 với `{approval_id}`; không công tắc nào mở → 409 `not_killed`; một yêu cầu bật lại còn `pending` cho công tắc đó →
   409 `lift_pending` (chỉ mục duy nhất từng phần `uq_approval_requests_control_lift_pending` của ticket 01); yêu cầu
   không lượt chạy nên không qua cửa `decide` của ticket 01 và quyết được dưới chính công tắc đó hay dưới Đóng băng.
   Handler `studio.lifecycle.revive.decided` gỡ đúng dòng `switch_id`, ghi `lift_approval_id` (trigger của ticket 01 đòi
   nó), và kết thúc không đổi gì, không audit khi dòng đã gỡ hay khi quyết định là `rejected` (công tắc giữ mở; luồng phê
   duyệt đã audit quyết định đó); ghi outbox `control.switch.changed` và audit `control.kill.lifted`
   với actor là người quyết định, `details` có khóa `lane` là tên lane (ADR-0011 (Accepted)). Migration của
   ticket đăng ký khóa `studio.lifecycle.kill` (không đăng ký `studio.lifecycle.revive`: là loại phê duyệt, không khóa,
   vì route bật lại và tem của người quyết đều là `studio.lifecycle.kill`, như `studio.lifecycle.unfreeze` của ticket 01;
   một khóa không bên đọc là failure-modes #1) trong `platform.permissions` của
   tenant-rbac/01 (nhãn tiếng Việt, `scope_kind` `workspace`, `risk` `standard` theo bảng phân loại của ticket
   đó); INSERT nêu mọi cột NOT NULL của bảng lúc đó, gồm `risk` và `status` (`active`) của tenant-rbac/01 và
   `tenant_grantable` (`true`) của tenant-rbac/02, ticket này chờ ticket đó; cùng migration thêm khóa vào vai mẫu
   `org_admin` như ticket 01 làm với `studio.lifecycle.freeze` (tenant-rbac:R3.2), để công ty thường có hơn một người
   giữ tem duyệt bật lại.
2. Kiểm `artifact_killed` ở mọi cửa của ticket 01 với thành phần của run và thành phần sau công cụ dùng
   quy trình hay agent liên kết; ở cửa nhận, lượt `live` và `test` của thành phần kết thúc `cancelled` kể cả
   lượt do trình kích hoạt đã xếp hàng (Tắt khẩn cấp không giữ `queued`, DO-28 C); lượt `simulate` không bị
   chặn bởi kill (ADR-0120 (Accepted) quyết 7: "still allows `simulate` runs so a fix can be evaluated"). Khi nhiều công
   tắc cùng mở, `RunHaltedError` mang một lý do theo thứ tự `platform_frozen`, `tenant_frozen` (nguồn `platform` trước
   `tenant`), `artifact_killed` (thành phần gốc trước agent liên kết), và `set_by` của đúng công tắc đó; riêng ở `door`
   `admission`, `artifact_killed` của thành phần đứng trước Đóng băng, để lượt đã xếp hàng của thành phần bị tắt bị hủy
   (spec R8.1) chứ không được Đóng băng giữ `queued`. Agent liên kết và Quy trình con: stack con của agent liên kết
   (`sub_agents.py:95-120`) gọi `RunControlMiddleware` với `artifacts` là id thành phần của agent liên kết, lấy từ bao
   đóng đã ghim của lượt (bản kê của tenant-config/04), và cửa đầu node của workflow-engine/03 làm vậy với Quy trình con;
   bước công tắc của executor (trước `resolve`, ticket 01) chỉ kiểm thành phần gốc. Lời gọi bị từ chối ném
   `RunHaltedError`, nên lượt cha kết thúc `cancelled` `artifact_killed` như ở mọi cửa; lane không quét lượt cha đang
   đỗ dùng agent bị tắt: cửa `resume` của lượt đó từ chối khi nó chạy tiếp.
3. Lane `control_switch` nghe outbox `control.switch.changed`: đọc dòng công tắc theo id; dòng đã gỡ, đã xóa hay không
   phải `kill` → kết thúc không đổi gì; còn mở → hủy mọi lượt chạy `live` và `test` đang đỗ của thành phần, tức
   `status` trong `waiting_approval`, `waiting_timer`, `waiting` và `queued` (`RunStatus`, `run_store.py:35-51`; chờ
   `outcome_review` và chờ sự cố là `waiting` của workflow-engine) (`cancelled`, sự kiện `run.cancelled`), không chạm lượt `simulate`
   (spec R8.1), hủy các yêu cầu phê duyệt của
   chúng bằng `ApprovalRequest.cancel()` (một yêu cầu đã không còn `pending`, vì `decide` commit quyết định trước khi
   `resume`, thì lane bỏ qua nó mà vẫn hủy lượt, và quyết định đó tới `resume` nhận 409, spec R8.3) (audit `approval.cancelled` với actor là người tắt và khóa `lane` của
   `details` là `control_switch`, vì lane thi hành quyết định của người đó). "Tắt trình kích hoạt" không ghi trạng thái
   thứ hai: trình kích hoạt của workflow-triggers hỏi `admission_state` và ghi lần kích hoạt `refused_killed` khi thành
   phần bị tắt (workflow-triggers:R1.4), nên bật lại mở chúng lại mà không ai phải nhớ; sự kiện gỡ không có việc gì cho lane. Móc hủy lượt (spec R8.10; H-22): ticket này khai Protocol `RunCancelHook`
   (`on_cancel(unit, run_id, *, actor, lane)`, `unit` là đơn vị giao dịch của lane, một Protocol hẹp khai cạnh nó mà
   adapter của móc ghi qua, không mở kết nối riêng, nên audit của móc cùng thành cùng lùi với lệnh hủy; đáp yêu cầu
   (a) của workflow-engine/08) trong `dw_agent_runtime.ports` và một sổ móc ở composition root của worker, đăng
   ký bằng `register` như `ConsumerRegistry`, không móc nào mặc định; lane gọi mọi móc đã đăng ký trong giao dịch hủy mỗi
   lượt, trước lệnh đặt `cancelled`, với `actor` là người tắt và `lane` `control_switch`; một móc ném lỗi thì giao dịch
   hủy lượt đó lùi và lần xử lý thử lại theo outbox, không lượt nào bị hủy mà bỏ qua móc. workflow-engine/08 đăng ký
   `record_unresolved_effects` vào sổ này (workflow-engine:R6.38; ticket 08 bước 5 của spec đó), nên audit
   `run.effect_unresolved` của một lượt đỗ ở `outcome_review` đứng tên người tắt.
4. Người đặt công tắc trong câu trả lời dừng (spec R8.11; H-22): ảnh chụp của `SqlRunControl` (ticket 01) giữ `set_by`
   của mỗi công tắc đang mở, và `RunHaltedError` mang `set_by` khi lý do là `artifact_killed`, `tenant_frozen` hay `platform_frozen`, để làn
   `studio_runs` ở đầu node xác nhận ghi audit `run.effect_unresolved` đứng tên người đó (workflow-engine:R6.38); với
   `platform_frozen` là người vận hành đặt Đóng băng, audit mang thêm `details.platform_freeze_id` (H-32); lý do khác (`principal_inactive`, `tenant_locked`, `tenant_offboarding`,
   `control_state_unavailable`) không mang `set_by`.
5. Lời gọi đang bay (spec R8.9; ADR-0120 (Accepted) quyết 7; V4.30), không đổi đường ghi kết quả có kiểu mà
   runtime-hardening/01 đã dựng ở executor, chỉ thêm test rằng Tắt khẩn và Đóng băng không đổi nó: Tắt khẩn hay Đóng băng không cắt một lời gọi nhà
   cung cấp đã qua bước công tắc điều khiển của sổ bước; `ToolExecutor` để lời gọi kết thúc và ghi dòng kết thúc của nó
   theo kết quả có kiểu mà egress trả (`succeeded`; `NotDispatchedError`, `RejectedError`, `OutcomeUnknownError` của
   runtime-hardening/01, khai ở `dw_agent_runtime`), `outcome_unknown` khi không rõ, không bao giờ `failed` hay
   `cancelled` thay; cửa kế tiếp của lượt hủy lượt với `artifact_killed`, `tenant_frozen` hay `platform_frozen`.
6. Hợp đồng `admission_state` cho lane gửi đi: trước khi gửi một tin đã xếp hàng, lane kiểm công tắc
   `artifact_killed` của thành phần gốc và không gọi nhà cung cấp nếu bị tắt; kèm test hợp đồng với lane
   giả. Lane gửi tin đã xếp hàng thật là của connections-and-vault ở W2 (spec R8.4); đường gửi W1 của lát đi qua
   cửa công cụ và được chứng minh ở marketing-pilot/05 (marketing-pilot:R6.4).
7. Người xin bật lại không tự duyệt được: luồng phê duyệt nghiêm từ chối 409 `conflict` với `details.reason_code`
   `second_person_required` khi người quyết là người xin, mã mà `_enforce_strict_rules` đã đặt cho mọi loại dưới tiền tố
   nghiêm (`approval_flow.py:139-152`; V4.P9; ADR-0104 (Accepted) quyết 11), và công tắc không gỡ; loại nghiêm đòi lời
   bình (`approval_flow.py:153-157`), nên test gửi `comment`.

## Tiêu chí chấp nhận

- [x] R8.1: sau kill, run `live` và `test` mới của thành phần → `cancelled` `artifact_killed`; lượt
      `datahub` đã xếp hàng của thành phần → `cancelled`, không giữ `queued`; lượt `simulate` vẫn chạy, kể cả một lượt
      `simulate` đang `waiting` khi lane chạy; kill lần hai → 409 `already_killed`, một audit; khi vừa Đóng băng của
      công ty do Q vừa Tắt khẩn do P → `tenant_frozen`, `set_by` Q.
- [x] R8.1 (AL16): người của tenant B gọi `kill` hay `revive-requests` với `artifact_id` của tenant A → 404 giống id ngẫu
      nhiên, không dòng công tắc, không audit ở A; người giữ `studio.lifecycle.kill` ở độ sâu `workspace` của ws1 với
      thành phần thuộc ws2 → 404; `agents` với id của một quy trình → 404; bỏ lọc độ sâu → test đỏ.
- [x] R8.2 (AL13): run `waiting_approval` của thành phần → `cancelled`, phê duyệt của nó → `cancelled`,
      audit `approval.cancelled` mang actor là người tắt và khóa `lane` trong `details`; một lượt Studio `waiting` của
      thành phần → `cancelled`; outbox `control.switch.changed` ghi cùng giao dịch với dòng công tắc; gỡ lane → test đỏ.
- [x] R8.9 (AL28): cửa giả của một công cụ không khóa giữ lời gọi đang bay, Tắt khẩn thành phần, rồi cửa trả
      `OutcomeUnknownError` → dòng kết thúc của lời gọi là `outcome_unknown`, không `failed` hay `cancelled`, nhà cung cấp
      nhận đúng 1 lời gọi, lượt `cancelled` `artifact_killed` ở cửa kế tiếp; cùng ca với Đóng băng của công ty → lượt
      `cancelled` `tenant_frozen`; cửa trả thành công sau Tắt khẩn → dòng `succeeded`; ghi `failed` cho lời gọi đang bay
      lúc Tắt khẩn → test đỏ.
- [x] R8.10 (AL29): một móc giả đăng ký vào sổ móc hủy lượt, Tắt khẩn một thành phần có một lượt `waiting` → móc nhận
      đúng một lời gọi với id lượt, `actor` là người tắt và `lane` `control_switch`, trong giao dịch đặt `cancelled`; móc
      ném lỗi → lượt vẫn `waiting`, lần xử lý thử lại; bỏ lời gọi sổ móc khỏi lane → móc nhận 0 lời gọi, test đỏ.
- [x] R8.11 (AL29): lượt chạy tới một cửa sau khi người P Tắt khẩn thành phần → `RunHaltedError` mang `artifact_killed`
      và `set_by` P; sau khi người Q đặt Đóng băng của công ty → `tenant_frozen` và `set_by` Q; sau khi người vận hành O đặt Đóng băng của nền tảng →
      `platform_frozen`, `set_by` O và audit có `details.platform_freeze_id`; lý do `tenant_locked` →
      `set_by` vắng; bỏ `set_by` khỏi ảnh chụp của `SqlRunControl` → test đỏ.
- [x] R8.3 (AL13): quyết định phê duyệt đến sau khi run đã bị hủy do kill → 409, không resume.
- [x] R8.4 (AL15): tin Zalo đã xếp hàng của thành phần bị tắt → lane gửi không gọi nhà cung cấp (test
      hợp đồng với lane giả).
- [x] R8.5 (AL15): agent bị tắt dùng làm agent liên kết trong agent khác → lời gọi bị từ chối trong
      stack con.
- [x] R8.6 (AL14): xin bật lại → mở yêu cầu phê duyệt `studio.lifecycle.revive` nghiêm với `switch_id`; duyệt bởi người
      khác → công tắc gỡ, `lift_approval_id` ghi; xin bật lại khi không bị tắt → 409 `not_killed`; xin lần hai khi yêu cầu
      đầu còn `pending` → 409 `lift_pending`; P tắt, xin bật lại, Q duyệt, P tắt lại, rồi sự kiện `.decided` cũ giao lại
      → công tắc mới vẫn mở; trình kích hoạt của thành phần ghi `refused_killed` khi bị tắt và xin lượt chạy lại sau khi
      bật lại, không bước nào bật lại trình kích hoạt.
- [x] R8.7 (AL14): người xin bật lại tự duyệt → 409 `conflict` với `details.reason_code` `second_person_required`,
      công tắc không gỡ.
- [x] R8.8: kill và bật lại ghi đúng một audit trong cùng giao dịch; rollback thì audit không còn.
- [x] Xong: `uv run python -m pytest packages/python/dw_agent_runtime/tests apps/api/tests apps/worker/tests -k "kill or revive or control_switch"` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/domain/approval.py:141-144`; spec: R8.2 (`ApprovalRequest.cancel()`
  chưa có caller production).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/sub_agents.py:95-120`; spec: R8.5
  (stack con của agent liên kết dựng riêng); ADR-0120 (Accepted) quyết 5.
- spec: R8.9-R8.11; workflow-engine:R6.38; runtime-hardening:R6.12 (kết quả có kiểu); ADR-0120 (Accepted) quyết 7;
  ADR-0011 (Accepted); V4.30; H-22.

## Comments

- 2026-10-23 (agent): từ B10a agent-lifecycle 10 và nút tắt trên trang phiên bản của 11. Dùng
  `platform.control_switches` và các cửa của ticket 01. MP14 phần W1: đóng băng sau chấm điểm, trước
  gửi → không gửi (kiểm ở ticket 01 và 04).
- 2026-10-23 (agent): áp quyết định của Đạt ngày 23/10/2026: actor của lane và handler theo OPS-a.1, outbox
  `control.switch.changed` (B:agent-lifecycle/05\~dữ-liệu), Tắt khẩn cấp hủy cả lượt đã xếp hàng (DO-28 C);
  test với lane gửi và trình kích hoạt thật chuyển sang marketing-pilot/05
  (I:agent-lifecycle/05\~workflow-triggers/01).
- 2026-10-24 (agent): áp quyết định của Đạt ngày 24/10/2026: lane gửi tin đã xếp hàng của R8.4 thuộc
  connections-and-vault ở W2, ticket này giữ test hợp đồng với lane giả; đăng ký hai khóa của ticket theo quy
  ước của tenant-rbac/01. workflow-engine/04 và workflow-triggers/01 chờ ticket này cho test `artifact_killed`
  ở làn thật (cạnh nằm ở hai ticket đó); ticket này không chờ ticket nào của hai spec đó.
- 2026-10-24 (agent): vòng sửa thứ tư: chờ tenant-rbac/02, vì INSERT hai khóa của ticket nêu mọi cột NOT NULL có lúc
  đó, gồm `tenant_grantable` (Quyết định tạm của spec).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt b: người xin tự quyết `studio.lifecycle.revive` nhận 409
  `second_person_required` (V4.P9; spec R8.7, AL14, Quyết định tạm cùng ngày).
- 2026-10-24 (agent): kiểm lượt b: bước 5 và tiêu chí R8.7 khẳng định mã mà tenant-config/05 đặt, trong khi ticket này
  không chờ ticket đó, trực tiếp hay qua ticket 01, 03; cạnh hay cách khác do người lập kế hoạch quyết, chưa thêm ở đây.
- 2026-10-24 (agent): vòng sửa thứ tư, lượt c, theo Quyết định tạm cùng ngày của spec: chờ tenant-config/05, vì bước
  5 và tiêu chí R8.7 khẳng định mã `second_person_required` mà ticket đó đặt ở `_enforce_strict_rules`; cạnh này thay
  câu "chưa thêm ở đây" của dòng trên.
- 2026-10-26 (agent): lượt h, đợt 2, theo V4.30 của Đạt và H-22: lời gọi đang bay khi Tắt khẩn hay Đóng băng ghi theo
  kết quả có kiểu (bước 5, spec R8.9, AL28; ADR-0120 (Accepted) quyết 7); lane `control_switch` hủy cả lượt Studio đỗ ở
  `waiting` và gọi sổ móc hủy lượt mà workflow-engine/08 đăng ký `record_unresolved_effects` vào (bước 3, spec R8.2,
  R8.10), và `RunHaltedError` mang người đặt công tắc (bước 4, spec R8.11, AL29), để audit `run.effect_unresolved` đứng
  tên người đó; người đứng tên khi Đóng băng của nền tảng hủy lượt là người vận hành đặt nó (H-32, sau đó). Không đổi cạnh: ticket này đã
  chờ ticket 01, mà nay chờ tools-and-skills/01 và qua đó runtime-hardening/01 (kết quả có kiểu); workflow-engine/08 đứng
  sau ticket này qua workflow-engine/04.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness trên `6b72166` (builder check và boundary walk trong một subagent, vì ticket có route; đối chiếu `approval.py`, `approval_flow.py`, ticket 01 và 03 đã ĐẠT, workflow-engine/08 và workflow-triggers; lượt xác nhận ngữ cảnh mới sau các sửa), 1 CRITICAL và 9 HIGH đã sửa theo khuyến nghị. CRITICAL: (1) `kill` và `revive-requests` không có test âm chéo tenant hay ngoài độ sâu: AL16 vào dòng Yêu cầu với tiêu chí riêng. HIGH: (2) yêu cầu bật lại ghim `switch_id`, handler gỡ đúng dòng và giao lại không lỗi; (3) `Idempotency-Key`, thân `reason_code`, `reason`, và `already_killed`; (4) `not_killed`, `lift_pending`; (5) bật lại là yêu cầu không lượt chạy nên không qua cửa `decide`; (6) `RunCancelHook` nhận đơn vị giao dịch của lane, đáp (a) của workflow-engine/08; (7) "tắt trình kích hoạt" là `refused_killed` ở workflow-triggers:R1.4, không trạng thái thứ hai, bật lại mở lại; (8) lane không hủy lượt `simulate` (R8.1); (9) độ sâu của khóa ở `owning_workspace_id`, yêu cầu ở workspace đó; (10) thứ tự lý do và `set_by` khi nhiều công tắc mở. Dẫn sai: `approval.py:132-135` thành `:141-144`; luật `simulate` là ADR-0120 (Accepted) quyết 7, không ADR-0125 (Accepted); `second_person_required` đã có, nên bỏ cạnh tới tenant-config/05. Nếu sai thì: (7) lane ghi trạng thái tắt lên trình kích hoạt và bật lại xóa nó; (8) lane hủy cả lượt `simulate` đang đỗ.
- 2026-11-04 (agent): MEDIUM để lại: (a) một móc hủy lỗi cố định làm lane thử lại theo backoff của outbox mà không có dead-letter riêng; cửa vẫn từ chối nên không mở toang; (b) yêu cầu bật lại chờ mãi khi người xin rời công ty; (c) cảnh báo collision của script với ticket 04: hai ticket chỉ thêm dòng mới vào `platform.permissions` và mã mới, mỗi revision trỏ lại `down_revision` lúc commit (`wave-close.md`), không sửa dòng của nhau.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (một subagent ngữ cảnh mới, mở đúng các tệp đã dẫn), 7 HIGH đã sửa, không dẫn sai: (11) lane hủy đúng các `status` `waiting_approval`, `waiting_timer`, `waiting`, `queued`; (12) agent liên kết và Quy trình con kiểm ở stack con và cửa đầu node với id thành phần từ bao đóng ghim, lượt cha hủy; (13) quyết định `rejected` không gỡ gì; (14) yêu cầu đã quyết khi lane chạy: bỏ qua phê duyệt, vẫn hủy lượt; (15) cột của `platform.platform_freezes` cho `set_by` nêu ở ticket 01; (16) `studio.lifecycle.revive` là loại phê duyệt, không khóa, spec sửa theo; (17) INSERT nêu `status`, vai mẫu `org_admin`, mã thành công và thân của hai route, payload outbox chỉ id; ở cửa nhận, `artifact_killed` trước Đóng băng. Nếu sai thì: (12) lane quét cả lượt cha đỗ; (16) đăng ký khóa và route bật lại đòi nó.
- 2026-11-04 (agent): MEDIUM thêm: người xin không tự rút yêu cầu bật lại (loại nghiêm chặn người xin cả khi từ chối, `approval_flow.py:284-286`), nên yêu cầu treo chặn lần xin sau tới khi người khác quyết.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-05 (agent): dựng xong. Revision `b735015cca5c` (sau `66777ec67d16`): khóa `studio.lifecycle.kill` (`workspace`,
  `standard`, `active`, `dw_platform`, `tenant_grantable`) vào `platform.permissions` và vai mẫu `org_admin`, chỉ mục
  `ix_approval_requests_tenant_id_run_id_pending` cho lane; bảng, trigger và chỉ mục một yêu cầu gỡ đã có từ ticket 01.
  `KillSwitchService` (`dw_studio.lifecycle.application.kill`) sau `ArtifactService.open_for` với khóa đó, dòng công tắc,
  `control.kill.set` và outbox `control.switch.changed` v1 `{tenant_id, switch_id}` trên phiên của vỏ thành phần
  (`control_switch_tx`); route `POST /studio/{agents|workflows}/{id}/kill` (201) và `.../revive-requests` (202),
  `Idempotency-Key`. `UnfreezeSettler` thành `SwitchLiftSettler` với hai dòng `SwitchLift` (`UNFREEZE_LIFT`,
  `REVIVE_LIFT`; bật lại ghi thêm outbox). Lane `control_switch` (`dw_agent_runtime.control_switch_lane`, `SqlKilledRuns`)
  là handler outbox của `control.switch.changed`; `RunCancelUnit`, `RunCancelHook` ở `dw_agent_runtime.ports`, sổ
  `RunCancelHooks` dựng và đóng ở `build_run_cancel_hooks()` của worker, rỗng. Test: `test_kill_switch.py` (unit, 51 ca),
  `test_kill_switch_db.py` (17), `test_kill_api.py` (10), hai ca ở `test_studio_runs.py`, hai ở `test_studio_runner.py`;
  `mutations/05.yaml` 23 đột biến chưa chạy, 12 phá tay đều đỏ.
- 2026-11-05 (agent, theo ủy quyền 31/10/2026): quyết khi dựng. (D1) Thành phần của chính lượt có một chủ:
  `RunContext.artifact_id`, đọc từ dòng lượt ở `SqlStudioRunStore.take` và `resume_context`; `SqlRunControl` hỏi nó ở
  mọi cửa (`reached_components`), nên bước công tắc của executor, đầu node, `start`, `resume`, `decide` và cửa model không
  phải tự nêu; cửa chỉ nêu thêm thành phần khác (agent liên kết), xếp sau. Nếu sai thì: mỗi cửa truyền `artifacts` riêng.
  (D2) Luật `simulate` ở cùng chỗ đó: lượt `simulate` không bị kill nào chặn, Đóng băng vẫn chặn; ở W1 trình kích hoạt
  `test` chạy `simulate` (workflow-triggers:R2.3), nên lượt chạy thử của người dựng không bị Tắt khẩn chặn. Nếu sai thì:
  kill chặn cả lượt `test` của trình kích hoạt `test`. (D3) Dịch vụ tắt nằm ở `dw_studio.lifecycle`, vì nó đọc thành
  phần; tên, sự kiện và lỗi chung ở `dw_platform.application.control_switches`, câu SQL công tắc một bản ở
  `control_switches_repo`. Nếu sai thì: dịch vụ ở `dw_platform` sau một Protocol đọc thành phần. (D4) Lane không vào sổ
  `tenant_wide_scope()`: `control_switches`, `worker_runs`, `approval_requests` chỉ lọc theo công ty, lane đọc một công
  ty. Nếu sai thì: thêm một dòng `TenantWideLane` có lý do. (D5) Mỗi lượt một giao dịch: đọc lại lượt `FOR UPDATE` và
  công tắc `FOR SHARE`, nên bật lại chờ hay thắng lần hủy. (D6) `error` của lượt bị lane hủy là
  `{code: artifact_killed, switch_id}`, dạng của `run_studio`, vì mọi lượt lane chạm là dòng Studio. Nếu sai thì: dạng
  `reason_code` của `_fail`. (D7) `RunCancelUnit` chỉ có `audit(event)`; workflow-engine/08 thêm lần đọc nó cần.
  (D8) Audit `control.kill.set` và yêu cầu bật lại ở `owning_workspace_id` của thành phần. (D9) Quy trình con: lượt con
  mang `artifact_id` của chính nó trên dòng, nên đầu node của nó tự hỏi; không có gì để nối tới workflow-engine/09.
  Agent liên kết: `SubAgentSpec.artifact_id`, `RunControlMiddleware(artifacts=...)` trong stack con. (D10) `agents` mount
  theo spec nhưng trả 404 tới khi loại `agent` có dòng `studio.artifact_kinds` (agent-builder).
- 2026-11-05 (agent): MEDIUM để lại: (a) lane không `pg_notify('dw_run_state')` khi hủy, trang đang xem lượt thấy ở lần
  đọc sau; (b) `SubAgentSpec.artifact_id` chưa có bên đặt production (chưa có agent Studio): agent-builder phải điền từ
  bao đóng ghim, không thì R8.5 chỉ có ở test (failure-modes #1); (c) bản nhân bản `org_admin` đã có không nhận khóa mới,
  như ticket 01; (d) offboarding chưa có test xóa công tắc `kill` riêng (bảng đã có trong bước của ticket 01).
  Còn nợ ở lần đóng hàng: `mutate.py` cho `mutations/05.yaml`; P50/P95/P99 của hai route mới, lần quyết bật lại và
  đường hủy của lane so với `ad311f38`; `code-review`; `reviewing-deployment-security` (route mới).
