# 05 — Tắt khẩn cấp agent và quy trình, bật lại cần hai người, hủy việc đang chờ

Status: needs-triage
Blocked by: 01, 03, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md, .claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md
Area: studio
Yêu cầu: R8.1, R8.2, R8.3, R8.4, R8.5, R8.6, R8.7, R8.8, R8.9, R8.10, R8.11, AL13, AL14, AL15, AL28, AL29

## Mục tiêu

Người có quyền Tắt khẩn cấp một agent hay quy trình: cửa chặn lượt chạy `live` và `test` mới, lane hủy
lượt chạy và phê duyệt đang chờ cùng trình kích hoạt, và bật lại cần một người thứ hai; lượt `simulate`
vẫn chạy để người dựng sửa (spec R8). Lời gọi nhà cung cấp đang bay khi Tắt khẩn hay Đóng băng được ghi theo kết quả
có kiểu của egress (ADR-0120 (Accepted) quyết 7; V4.30), và lượt bị hủy còn tác động chưa ai giải để lại audit đứng
tên người đặt công tắc (H-22). Dùng công tắc và các cửa của ticket 01, hợp đồng Giai đoạn của ticket 03.

## Việc cần làm

1. Route `POST /api/v1/studio/{agents|workflows}/{artifact_id}/kill` (`studio.lifecycle.kill`, lý do;
   một người cộng audit): ghi một dòng `platform.control_switches` `action='kill'` cho thành phần, audit
   `control.kill.set` và outbox `control.switch.changed` v1 chỉ id trong cùng giao dịch.
   `POST /api/v1/studio/{agents|workflows}/{artifact_id}/revive-requests`: mở một yêu cầu phê duyệt
   `studio.lifecycle.revive` nghiêm (tem `studio.lifecycle.kill`; tiền tố `studio.lifecycle.` của ticket
   01); handler gỡ công tắc khi duyệt, ghi outbox `control.switch.changed` và audit `control.kill.lifted`
   với actor là người quyết định, `details` có khóa `lane` là tên lane (ADR-0011 (Accepted)). Migration của
   ticket đăng ký khóa `studio.lifecycle.kill` và `studio.lifecycle.revive` trong `platform.permissions` của
   tenant-rbac/01 (nhãn tiếng Việt, `scope_kind` `workspace`, `risk` `standard` theo bảng phân loại của ticket
   đó); INSERT nêu mọi cột NOT NULL của bảng lúc đó, gồm `risk` của tenant-rbac/01 và `tenant_grantable` (`true`)
   của tenant-rbac/02, ticket này chờ ticket đó.
2. Kiểm `artifact_killed` ở mọi cửa của ticket 01 với thành phần của run và thành phần sau công cụ dùng
   quy trình hay agent liên kết; ở cửa nhận, lượt `live` và `test` của thành phần kết thúc `cancelled` kể cả
   lượt do trình kích hoạt đã xếp hàng (Tắt khẩn cấp không giữ `queued`, DO-28 C); lượt `simulate` không bị
   chặn bởi kill (ADR-0125 (Accepted) cho phép người dựng kiểm định bản sửa).
3. Lane `control_switch` nghe outbox `control.switch.changed`: hủy mọi lượt chạy đang đỗ của thành phần, cả
   `waiting_approval` lẫn lượt Studio ở `waiting` (`cancelled`, sự kiện `run.cancelled`), hủy các yêu cầu phê duyệt của
   chúng bằng `ApprovalRequest.cancel()` (audit `approval.cancelled` với actor là người tắt và khóa `lane` của
   `details` là `control_switch`, vì lane thi hành quyết định của người đó), tắt trình kích hoạt của thành phần (hợp đồng
   với workflow-triggers). Móc hủy lượt (spec R8.10; H-22): ticket này khai Protocol `RunCancelHook`
   (`on_cancel(run_id, *, actor, lane)`) trong `dw_agent_runtime.ports` và một sổ móc ở composition root của worker, đăng
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
5. Lời gọi đang bay (spec R8.9; ADR-0120 (Accepted) quyết 7; V4.30): Tắt khẩn hay Đóng băng không cắt một lời gọi nhà
   cung cấp đã qua bước công tắc điều khiển của sổ bước; `ToolExecutor` để lời gọi kết thúc và ghi dòng kết thúc của nó
   theo kết quả có kiểu mà egress trả (`succeeded`; `NotDispatchedError`, `RejectedError`, `OutcomeUnknownError` của
   runtime-hardening/01, khai ở `dw_agent_runtime`), `outcome_unknown` khi không rõ, không bao giờ `failed` hay
   `cancelled` thay; cửa kế tiếp của lượt hủy lượt với `artifact_killed`, `tenant_frozen` hay `platform_frozen`.
6. Hợp đồng `admission_state` cho lane gửi đi: trước khi gửi một tin đã xếp hàng, lane kiểm công tắc
   `artifact_killed` của thành phần gốc và không gọi nhà cung cấp nếu bị tắt; kèm test hợp đồng với lane
   giả. Lane gửi tin đã xếp hàng thật là của connections-and-vault ở W2 (spec R8.4); đường gửi W1 của lát đi qua
   cửa công cụ và được chứng minh ở marketing-pilot/05 (marketing-pilot:R6.4).
7. Người xin bật lại không tự duyệt được: luồng phê duyệt nghiêm từ chối 409 `conflict` với `details.reason_code`
   `second_person_required` khi người quyết là người xin, mã mà `_enforce_strict_rules` của tenant-config/05 đặt một
   lần cho mọi loại dưới tiền tố nghiêm (V4.P9; ADR-0104 (Accepted) quyết 11), và công tắc không gỡ.

## Tiêu chí chấp nhận

- [ ] R8.1: sau kill, run `live` và `test` mới của thành phần → `cancelled` `artifact_killed`; lượt
      `datahub` đã xếp hàng của thành phần → `cancelled`, không giữ `queued`; lượt `simulate` vẫn chạy.
- [ ] R8.2 (AL13): run `waiting_approval` của thành phần → `cancelled`, phê duyệt của nó → `cancelled`,
      audit `approval.cancelled` mang actor là người tắt và khóa `lane` trong `details`; một lượt Studio `waiting` của
      thành phần → `cancelled`; outbox `control.switch.changed` ghi cùng giao dịch với dòng công tắc; gỡ lane → test đỏ.
- [ ] R8.9 (AL28): cửa giả của một công cụ không khóa giữ lời gọi đang bay, Tắt khẩn thành phần, rồi cửa trả
      `OutcomeUnknownError` → dòng kết thúc của lời gọi là `outcome_unknown`, không `failed` hay `cancelled`, nhà cung cấp
      nhận đúng 1 lời gọi, lượt `cancelled` `artifact_killed` ở cửa kế tiếp; cùng ca với Đóng băng của công ty → lượt
      `cancelled` `tenant_frozen`; cửa trả thành công sau Tắt khẩn → dòng `succeeded`; ghi `failed` cho lời gọi đang bay
      lúc Tắt khẩn → test đỏ.
- [ ] R8.10 (AL29): một móc giả đăng ký vào sổ móc hủy lượt, Tắt khẩn một thành phần có một lượt `waiting` → móc nhận
      đúng một lời gọi với id lượt, `actor` là người tắt và `lane` `control_switch`, trong giao dịch đặt `cancelled`; móc
      ném lỗi → lượt vẫn `waiting`, lần xử lý thử lại; bỏ lời gọi sổ móc khỏi lane → móc nhận 0 lời gọi, test đỏ.
- [ ] R8.11 (AL29): lượt chạy tới một cửa sau khi người P Tắt khẩn thành phần → `RunHaltedError` mang `artifact_killed`
      và `set_by` P; sau khi người Q đặt Đóng băng của công ty → `tenant_frozen` và `set_by` Q; sau khi người vận hành O đặt Đóng băng của nền tảng →
      `platform_frozen`, `set_by` O và audit có `details.platform_freeze_id`; lý do `tenant_locked` →
      `set_by` vắng; bỏ `set_by` khỏi ảnh chụp của `SqlRunControl` → test đỏ.
- [ ] R8.3 (AL13): quyết định phê duyệt đến sau khi run đã bị hủy do kill → 409, không resume.
- [ ] R8.4 (AL15): tin Zalo đã xếp hàng của thành phần bị tắt → lane gửi không gọi nhà cung cấp (test
      hợp đồng với lane giả).
- [ ] R8.5 (AL15): agent bị tắt dùng làm agent liên kết trong agent khác → lời gọi bị từ chối trong
      stack con.
- [ ] R8.6 (AL14): xin bật lại → mở yêu cầu phê duyệt `studio.lifecycle.revive` nghiêm; duyệt bởi người
      khác → công tắc gỡ.
- [ ] R8.7 (AL14): người xin bật lại tự duyệt → 409 `conflict` với `details.reason_code` `second_person_required`,
      công tắc không gỡ.
- [ ] R8.8: kill và bật lại ghi đúng một audit trong cùng giao dịch; rollback thì audit không còn.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/domain/approval.py:132-135`; spec: R8.2 (`ApprovalRequest.cancel()`
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
