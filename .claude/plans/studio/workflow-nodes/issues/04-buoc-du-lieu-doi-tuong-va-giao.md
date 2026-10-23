# 04 — Bước dữ liệu đối tượng qua RecordsPort và bước giao người phụ trách

Status: needs-triage
Blocked by: 03, .claude/plans/studio/custom-objects/issues/04-truy-van-ban-ghi.md, .claude/plans/studio/record-access/issues/05-giao-nguoi-phu-trach.md, .claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md
Area: studio
Yêu cầu: R2.1, R2.2, R5.1, R5.2, R5.4, R5.5, R6.1, R6.2, R6.3, R6.4, WN4, WN16

## Mục tiêu

Các bước đọc và ghi bản ghi đi qua một `RecordsPort` do người dùng khai báo (RecordService đáp ứng), với
quyền của người chạy; và một bước giao người phụ trách theo quy tắc, xoay vòng theo người lâu nhất chưa
nhận (workflow-nodes R2.1, R2.2, R5.1, R5.2, R5.4, R5.5, R6.1, R6.2, R6.3, R6.4, WN4, WN16).

## Việc cần làm

1. `RecordsPort` khai báo trong `dw_studio.workflows` (bên dùng khai Protocol), thỏa bởi `RecordService`
   của custom-objects. Bốn bước `data.object.query|create|update|upsert`: ngữ cảnh actor lấy từ lượt
   chạy; khoá chống lặp `run_id:node_id:iteration`; `limit` 1-200 (200 nhận, 201 lỗi); tối đa 100
   trường mỗi lần ghi. `query` dùng cây lọc AST của custom-objects.
2. Schema loại bước bản ghi không có khoá `run_as` và không nhận chủ thể khác người chạy; một cấu hình
   mang khoá đó bị schema từ chối.
3. Chế độ chạy: bước bản ghi chuyển nguyên `run_mode` của lượt chạy qua `RecordsPort`; RecordService giả lập
   ở `simulate` (custom-objects:R5.4); bước không có nhánh giả lập riêng.
4. Hình chiếu kiểm trùng cho quy trình Tiếp nhận lead: so số điện thoại chuẩn hóa về `+84` (hàm CEL
   `phone.e164`) rồi email chữ thường; "0901 234 567" và "+84901234567" là một Lead; cùng tên khác số
   là hai Lead (MP10).
5. `data.object.assign`: ứng viên W1 là thành viên `active` của workspace trong tầm giao giữ quyền làm người
   phụ trách bản ghi, lọc theo cùng hàm kiểm quyền `effective_grants` mà cửa đọc dùng; quy tắc CEL chọn tầm
   và lọc thêm, không dùng nhóm (nhóm ở W2); "lâu nhất chưa nhận" từ `owner_assigned_at` qua hàm SECURITY
   DEFINER chỉ trả thời điểm; không ai hợp lệ → người dự phòng là giá trị đã duyệt của một điểm gắn kind
   `principal` trong Bộ giá trị gắn (tenant-config/05), đọc qua `RunBindingsPort` từ bản kê, qua cùng kiểm
   `effective_grants`; người dự phòng cũng không hợp lệ → Nhánh ra lỗi, không giao; gọi
   `studio.assign_record` của record-access; audit `studio.record.assigned`.

## Tiêu chí chấp nhận

- [ ] R2.1: mỗi bước bản ghi có đúng một tác dụng phụ, đi qua `RecordsPort`; test kiến trúc: mô-đun bước
      không có SQL nhắc `studio.records`.
- [ ] R2.2: mô-đun loại bước không import adapter cụ thể và không có SDK nhà cung cấp (test kiến trúc).
- [ ] R5.1: chạy lại `create` sau sập với cùng khoá `run_id:node_id:iteration` không tạo bản ghi thứ
      hai.
- [ ] R5.2 (WN4): cấu hình bước có `run_as` → schema từ chối; chủ thể chạy thiếu quyền → `permission_denied`.
- [ ] R5.5: một `create` ở `simulate` → `RecordsPort` (spy) nhận `run_mode` `simulate`; với RecordService
      thật không có dòng, sự kiện hay audit nào (custom-objects:R5.4).
- [ ] R5.4: "0901 234 567" và "+84901234567" tới cùng một Lead; cùng tên khác số tạo hai Lead.
- [ ] R6.2: 100 lead cho 3 ứng viên → số nhận lệch tối đa 1.
- [ ] R6.1 (WN16): một người không giữ quyền làm người phụ trách bản ghi không bao giờ được chọn; gỡ
      kiểm quyền ứng viên → test đỏ.
- [ ] R6.3 (WN16): không ứng viên nào hợp lệ → giao cho người dự phòng đã duyệt và ghi
      `studio.record.assigned`.
- [ ] R6.4 (WN16): người dự phòng cũng không giữ quyền → bước đi Nhánh ra lỗi, bản ghi không có người phụ
      trách mới; bỏ kiểm quyền của người dự phòng → test đỏ.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/workflows/test_data_object_nodes.py packages/python/dw_studio/tests/workflows/test_assign_node.py` xanh.

## Nguồn

- custom-objects:R5.6, custom-objects:R8.9; `.claude/plans/studio/custom-objects/issues/04-truy-van-ban-ghi.md`.
- record-access:R6.4, record-access:R8.1; `.claude/plans/studio/record-access/issues/05-giao-nguoi-phu-trach.md`.
- ADR-0112 (Accepted) quyết 6; spec: R2.1, R5.1, R5.5.

## Comments

- 2026-10-23 (agent): theo phiếu 23/10/2026: giả lập ghi bản ghi ở RecordService, R5.3 rút và R5.5 thay (D:custom-objects:R5.4~workflow-nodes:R5.3); người dự phòng là điểm gắn kind `principal` duyệt hai người, nhóm ở W2 (Q6), nên ticket chờ tenant-config/05.
