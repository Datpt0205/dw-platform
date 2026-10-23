# 05 — Tắt khẩn cấp agent và quy trình, bật lại cần hai người, hủy việc đang chờ

Status: needs-triage
Blocked by: 01, 03
Area: studio
Yêu cầu: R8.1, R8.2, R8.3, R8.4, R8.5, R8.6, R8.7, R8.8, AL13, AL14, AL15

## Mục tiêu

Người có quyền Tắt khẩn cấp một agent hay quy trình: cửa chặn lượt chạy `live` và `test` mới, lane hủy
lượt chạy và phê duyệt đang chờ cùng trình kích hoạt, và bật lại cần một người thứ hai; lượt `simulate`
vẫn chạy để người dựng sửa (spec R8). Dùng công tắc và các cửa của ticket 01, hợp đồng Giai đoạn của
ticket 03.

## Việc cần làm

1. Route `POST /api/v1/studio/{agents|workflows}/{artifact_id}/kill` (`studio.lifecycle.kill`, lý do):
   ghi một dòng `platform.control_switches` `action='kill'` cho thành phần, audit `control.kill.set`.
   `POST /api/v1/studio/{agents|workflows}/{artifact_id}/revive-requests`: mở một yêu cầu phê duyệt
   `studio.lifecycle.revive` nghiêm (tem `studio.lifecycle.kill`); handler gỡ công tắc khi duyệt, audit
   `control.kill.lifted` actor là người quyết định.
2. Kiểm `artifact_killed` ở mọi cửa của ticket 01 với thành phần của run và thành phần sau công cụ dùng
   quy trình hay agent liên kết; lượt `simulate` không bị chặn bởi kill (ADR-0125 (Proposed) cho phép
   người dựng kiểm định bản sửa).
3. Lane `control_switch` nghe outbox `control.switch.changed`: hủy lượt chạy `waiting_approval` của
   thành phần (`cancelled`, sự kiện `run.cancelled`), hủy các yêu cầu phê duyệt của chúng bằng
   `ApprovalRequest.cancel()` (audit `approval.cancelled`, actor là người tắt), tắt trình kích hoạt của
   thành phần (hợp đồng với workflow-triggers).
4. Hợp đồng `admission_state` cho lane gửi đi: trước khi gửi một tin đã xếp hàng, lane kiểm công tắc
   `artifact_killed` của thành phần gốc và không gọi nhà cung cấp nếu bị tắt; kèm test hợp đồng với lane
   giả, rồi với lane thật khi connections-and-vault xong.
5. Người xin bật lại không tự duyệt được: luồng phê duyệt nghiêm từ chối 409 khi người quyết là người
   xin, và công tắc không gỡ.

## Tiêu chí chấp nhận

- [ ] R8.1: sau kill, run `live` và `test` mới của thành phần → 409 `artifact_killed`; lượt `simulate`
      vẫn chạy.
- [ ] R8.2 (AL13): run `waiting_approval` của thành phần → `cancelled`, phê duyệt của nó → `cancelled`;
      gỡ lane → test đỏ.
- [ ] R8.3 (AL13): quyết định phê duyệt đến sau khi run đã bị hủy do kill → 409, không resume.
- [ ] R8.4 (AL15): tin Zalo đã xếp hàng của thành phần bị tắt → lane gửi không gọi nhà cung cấp (test
      hợp đồng với lane giả).
- [ ] R8.5 (AL15): agent bị tắt dùng làm agent liên kết trong agent khác → lời gọi bị từ chối trong
      stack con.
- [ ] R8.6 (AL14): xin bật lại → mở yêu cầu phê duyệt `studio.lifecycle.revive` nghiêm; duyệt bởi người
      khác → công tắc gỡ.
- [ ] R8.7 (AL14): người xin bật lại tự duyệt → 409, công tắc không gỡ.
- [ ] R8.8: kill và bật lại ghi đúng một audit trong cùng giao dịch; rollback thì audit không còn.
- [ ] Xong: `make ci && make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/domain/approval.py:132-135`; spec: R8.2 (`ApprovalRequest.cancel()`
  chưa có caller production).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/sub_agents.py:95-120`; spec: R8.5
  (stack con của agent liên kết dựng riêng); ADR-0120 (Proposed) quyết 5.

## Comments

- 2026-10-23 (agent): từ B10a agent-lifecycle 10 và nút tắt trên trang phiên bản của 11. Dùng
  `platform.control_switches` và các cửa của ticket 01. MP14 phần W1: đóng băng sau chấm điểm, trước
  gửi → không gửi (kiểm ở ticket 01 và 04).
