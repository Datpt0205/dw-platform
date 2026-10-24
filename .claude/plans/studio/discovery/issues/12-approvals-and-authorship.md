# 12 — Phê duyệt và tách nhiệm: tự duyệt, guard quyết định, tác giả, độ mịn taint, duyệt kèm sửa

Type: grilling
Status: needs-triage
Area: studio · Viết: 23/10/2026
FOG: FOG-48 `self-approval`, FOG-63 `decision-guard`, FOG-66 `eval-semantics`, FOG-47 `taint-granularity`,
FOG-12 `approver-phone`

## Câu hỏi

Hỏi Đạt; câu 5 hỏi thêm khách thí điểm (ticket 02):

1. Người khởi chạy một lượt chạy có được duyệt phê duyệt `studio.step.` của chính lượt đó không, tức tiền tố này có vào
   `strict_approval_prefixes` (hôm nay chỉ `memory.`, `apps/api/src/dw_api/bootstrap/runtime.py:237`) không? YC51 đã đòi
   người duyệt tin tiếp thị khác người tạo lượt chạy; câu hỏi còn lại là mọi `studio.step.` khác (FOG-48).
2. Thay `DecisionGuard` đồng bộ (`packages/python/dw_agent_runtime/src/dw_agent_runtime/approval_flow.py:47`) bằng
   `ApprovalDecisionGuard` bất đồng bộ cùng `ProposedDecision` của dw-proterial, hay giữ guard đồng bộ và chỉ kiểm độ cũ
   lúc quyết toán (FOG-63)?
3. Khi phiên bản dựng có AI hỗ trợ hay tách từ mẫu, ai là tác giả; câu kiểm định của mẫu có tính vào số tối thiểu
   không; phụ thuộc nào phân giải lúc chạy (phiên bản cấu hình riêng, định nghĩa MCP đã ghim, nội dung tri thức, alias
   model của nhà cung cấp) làm một phiên bản đang dùng thành "chưa thật sự kiểm định" (FOG-66)?
4. Nội dung bản ghi đến từ nguồn bên ngoài (endpoint Data Hub, form) gắn run taint ở mức nào: cờ theo đối tượng hay
   nguồn gốc theo trường (FOG-47)?
5. Thí điểm có cần "duyệt kèm sửa" không, vì nó đổi quy tắc đóng băng nội dung được duyệt? Phép đo thời gian chờ p50 ≤ 10
   phút trên điện thoại qua mã Zalo (KQ2, YC52) cần mã quyết định qua Zalo của W2, nên chạy trong chạy bóng (FOG-12).

## Vì sao

Một bước người mà người khởi chạy tự duyệt là kiểm soát chỉ có vẻ ngoài. Guard chạm phê duyệt `memory.review` và mọi
loại phê duyệt sau này. Phát hành hai người (D11) và việc vô hiệu bằng chứng kiểm định phụ thuộc định nghĩa tác giả và
phụ thuộc. Taint quá thô buộc duyệt ở mọi nơi; quá mịn thì tốn theo dõi.

## Mở khóa

- Spec: `workflow-nodes` (06, bước phê duyệt), `tenant-config` (05, người đề xuất và người duyệt), `agent-lifecycle`
  (03, 04), `tools-and-skills` (run taint, W2), `compliance-pdpl` (05, bộ ba nguy hiểm), `marketing-pilot`.
- ADR: 0109 (Open 5), 0110, 0112, 0120, 0125.
- DO: DO-07 (D11), DO-29, DO-36 (Đạt chốt 23/10/2026), DO-31 (Đạt chốt 23/10/2026: hết hạn thì thất bại với
  `approval_expired`).

## Đầu ra

- Mỗi câu một quyết định kèm test âm sẽ có, ví dụ: người khởi chạy tự duyệt bị từ chối ở `decide`, và test đỏ khi bỏ
  tiền tố khỏi `strict_approval_prefixes`.
- Câu 3 ghi vào ADR 0109 (Open 5) và ADR 0120; câu 4 vào ADR 0125; câu 2 ghi phạm vi đổi cho `memory.review`.

## Nguồn

- Brief B6 (F8), B7a, B7b, B8b, B10a, B12.

## Comments
