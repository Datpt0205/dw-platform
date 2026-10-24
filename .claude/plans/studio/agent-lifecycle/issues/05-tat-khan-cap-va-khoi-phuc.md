# 05 — Tắt khẩn cấp agent và quy trình, bật lại cần hai người, hủy việc đang chờ

Status: needs-triage
Blocked by: 01, 03, .claude/plans/studio/tenant-rbac/issues/02-vai-la-du-lieu-tenant.md, .claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md
Area: studio
Yêu cầu: R8.1, R8.2, R8.3, R8.4, R8.5, R8.6, R8.7, R8.8, AL13, AL14, AL15

## Mục tiêu

Người có quyền Tắt khẩn cấp một agent hay quy trình: cửa chặn lượt chạy `live` và `test` mới, lane hủy
lượt chạy và phê duyệt đang chờ cùng trình kích hoạt, và bật lại cần một người thứ hai; lượt `simulate`
vẫn chạy để người dựng sửa (spec R8). Dùng công tắc và các cửa của ticket 01, hợp đồng Giai đoạn của
ticket 03.

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
3. Lane `control_switch` nghe outbox `control.switch.changed`: hủy lượt chạy `waiting_approval` của
   thành phần (`cancelled`, sự kiện `run.cancelled`), hủy các yêu cầu phê duyệt của chúng bằng
   `ApprovalRequest.cancel()` (audit `approval.cancelled` với actor là người tắt và khóa `lane` của
   `details` là `control_switch`, vì lane thi hành quyết định của người đó), tắt trình kích hoạt của thành phần (hợp đồng
   với workflow-triggers).
4. Hợp đồng `admission_state` cho lane gửi đi: trước khi gửi một tin đã xếp hàng, lane kiểm công tắc
   `artifact_killed` của thành phần gốc và không gọi nhà cung cấp nếu bị tắt; kèm test hợp đồng với lane
   giả. Lane gửi tin đã xếp hàng thật là của connections-and-vault ở W2 (spec R8.4); đường gửi W1 của lát đi qua
   cửa công cụ và được chứng minh ở marketing-pilot/05 (marketing-pilot:R6.4).
5. Người xin bật lại không tự duyệt được: luồng phê duyệt nghiêm từ chối 409 `conflict` với `details.reason_code`
   `second_person_required` khi người quyết là người xin, mã mà `_enforce_strict_rules` của tenant-config/05 đặt một
   lần cho mọi loại dưới tiền tố nghiêm (V4.P9; ADR-0104 (Accepted) quyết 11), và công tắc không gỡ.

## Tiêu chí chấp nhận

- [ ] R8.1: sau kill, run `live` và `test` mới của thành phần → `cancelled` `artifact_killed`; lượt
      `datahub` đã xếp hàng của thành phần → `cancelled`, không giữ `queued`; lượt `simulate` vẫn chạy.
- [ ] R8.2 (AL13): run `waiting_approval` của thành phần → `cancelled`, phê duyệt của nó → `cancelled`,
      audit `approval.cancelled` mang actor là người tắt và khóa `lane` trong `details`; outbox `control.switch.changed`
      ghi cùng giao dịch với dòng công tắc; gỡ lane → test đỏ.
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
