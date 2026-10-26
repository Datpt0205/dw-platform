# 04 — Bước dữ liệu đối tượng qua RecordsPort và bước giao người phụ trách

Status: needs-triage
Blocked by: 03, .claude/plans/studio/custom-objects/issues/04-truy-van-ban-ghi.md, .claude/plans/studio/record-access/issues/05-giao-nguoi-phu-trach.md, .claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md, .claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md
Area: studio
Yêu cầu: R2.1, R2.2, R5.1, R5.2, R5.4, R5.5, R6.1, R6.2, R6.3, R6.4, R6.5, WN4, WN16

## Mục tiêu

Các bước đọc và ghi bản ghi đi qua một `RecordsPort` do người dùng khai báo (RecordService đáp ứng), với
quyền của người chạy, và một bộ contract test của cổng đó chạy trên mọi bản cài, để bản giả mà workflow-engine dùng
không trôi khỏi bản thật; và một bước giao người phụ trách theo quy tắc, xoay vòng theo người lâu nhất chưa
nhận, không giao lại cho người kế tiếp khi chạy lại (workflow-nodes R2.1, R2.2, R5.1, R5.2, R5.4, R5.5, R6.1, R6.2,
R6.3, R6.4, R6.5, WN4, WN16).

## Việc cần làm

1. `RecordsPort` và `RecordAssignPort` do workflow-engine/03 khai trong `dw_studio.workflows.ports` (bên dùng là quy
   trình; H-30), thỏa bởi `RecordService` của custom-objects và `AssignRecordService` của record-access/05; ticket này
   chạy bộ contract test mà workflow-engine/03 khai cạnh Protocol
   (`packages/python/dw_studio/src/dw_studio/workflows/testing/records_port_contract.py`) trên hai bản thật: một bộ ca chạy qua tham số
   trên mọi bản cài, bản giả `dw_studio.workflows.testing.FakeRecordsPort` mà workflow-engine/03 dùng để thử
   workflow-engine:R4.7 và workflow-engine:R4.22, và `RecordService` thật nối như ở composition root (H-7), với các ca
   của hợp đồng R5: lệnh ghi ở `simulate` không ghi dòng, sự kiện hay audit nào (custom-objects:R5.4); gặp lại cùng
   khoá chống lặp thì trả kết quả đã lưu, không ghi lần hai (mức bảo đảm nội bộ, V4.30); lệnh sửa chỉ đổi các trường nó
   mang (PATCH theo trường, V4.34); chủ thể chạy thiếu quyền → `permission_denied`. Cùng bộ phủ `RecordAssignPort` của bước 5 trên bản giả mà workflow-engine/03 dùng cho ca `assign`
   và trên `AssignRecordService` thật: gặp lại cùng khoá thì trả người đã giao, không giao lần hai.
   Bốn bước `data.object.query|create|update|upsert`: ngữ cảnh actor lấy từ lượt chạy; khoá chống lặp là khoá wrapper
   nút dẫn theo workflow-engine:R4.5, Bước chỉ chuyển nó qua và không tự dựng khoá; lệnh sửa một bản ghi có sẵn của
   `update` và `upsert` chỉ mang các trường cấu hình của Bước nêu, không cả bản ghi đã đọc, vì workflow-engine:R7.3 dựa
   vào đó cho hai làn song song sửa cùng một bản ghi (R5.1; V4.34); `limit` 1-200 (200 nhận, 201 lỗi); tối đa 100
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
   `effective_grants`; người dự phòng cũng không hợp lệ → Bước kết thúc với lỗi theo Khi lỗi của nó (làn lỗi khi
   `route`), không giao. Giao bằng `AssignRecordService`
   của record-access/05 qua Protocol `RecordAssignPort` khai trong `dw_studio.workflows` và nối ở composition root;
   Bước không gọi `studio.assign_record`, không tự ghi audit: dịch vụ đó ghi audit và outbox
   `studio.record.assigned` trong một giao dịch (record-access:R8.7, record-access:R8.8). Bước chuyển đúng khoá chống
   lặp mà wrapper nút dẫn (workflow-engine:R4.5) qua `RecordAssignPort`; lần giao ghi khoá cùng giao dịch và phát lại
   người đã giao khi gặp lại khoá (V4.30 mục 10), nên một lần chạy lại sau khi worker chết không giao bản ghi cho người
   kế tiếp trong vòng xoay (R6.5).

## Tiêu chí chấp nhận

- [ ] R2.1: mỗi bước bản ghi có đúng một tác dụng phụ, đi qua `RecordsPort`; test kiến trúc: mô-đun bước
      không có SQL nhắc `studio.records`.
- [ ] R2.2: mô-đun loại bước không import adapter cụ thể và không có SDK nhà cung cấp (test kiến trúc).
- [ ] R5.1: chạy lại `create` sau sập với cùng khoá do wrapper nút dẫn (workflow-engine:R4.5) không tạo bản ghi
      thứ hai; Bước không có chỗ nào tự dựng khoá (test kiến trúc).
- [ ] R5.2 (WN4): cấu hình bước có `run_as` → schema từ chối; chủ thể chạy thiếu quyền → `permission_denied`.
- [ ] R5.5: một `create` ở `simulate` → `RecordsPort` (spy) nhận `run_mode` `simulate`; với RecordService
      thật không có dòng, sự kiện hay audit nào (custom-objects:R5.4).
- [ ] R5.5: bộ contract test của `RecordsPort` chạy trên `RecordService` thật và trên bản giả của workflow-engine/03,
      cả hai xanh; sửa bản giả để lưu lệnh ghi nhận ở `simulate` → ca `simulate` đỏ trên bản giả, test đỏ.
- [ ] R5.1: ca phát lại của bộ contract test: gửi lại cùng khoá → kết quả lần đầu, không ghi lần hai, trên cả hai bản
      cài; sửa bản giả để ghi lần hai → ca đó đỏ trên bản giả, test đỏ.
- [ ] R5.1: một Bước `update` nêu `score` trên Lead có `score` và `status` → `RecordsPort` (spy) nhận lệnh chỉ mang
      `score`; ca PATCH của bộ contract test: hai lệnh sửa cùng một bản ghi, một nêu `score`, một nêu `status`, dưới hai
      khoá → bản ghi giữ cả hai giá trị trên cả hai bản cài; cho Bước gửi cả bản ghi đã đọc → giá trị của lệnh kia bị
      ghi đè, test đỏ.
- [ ] R5.4: "0901 234 567" và "+84901234567" tới cùng một Lead; cùng tên khác số tạo hai Lead.
- [ ] R6.2: 100 lead cho 3 ứng viên → số nhận lệch tối đa 1.
- [ ] R6.1 (WN16): một người không giữ quyền làm người phụ trách bản ghi không bao giờ được chọn; gỡ
      kiểm quyền ứng viên → test đỏ.
- [ ] R6.3 (WN16): không ứng viên nào hợp lệ → giao cho người dự phòng đã duyệt qua `RecordAssignPort`, với đúng một
      audit và một outbox `studio.record.assigned` do `AssignRecordService` ghi; Bước ghi thêm một audit hay gọi thẳng
      `studio.assign_record` → test đỏ.
- [ ] R6.4 (WN16): người dự phòng cũng không giữ quyền → Bước khai Khi lỗi `route` chạy làn lỗi, Bước khai `fail`
      làm lượt `failed`, bản ghi không có người phụ trách mới ở cả hai; bỏ kiểm quyền của người dự phòng → test đỏ.
- [ ] R6.5: worker chết sau khi lần giao commit mà trước checkpoint, rồi lượt chạy lại Bước giao → bản ghi vẫn của người
      đã giao lần đầu, với đúng một audit và một outbox `studio.record.assigned`; cho Bước không chuyển khoá hay dựng
      khoá khác → bản ghi sang người kế tiếp trong vòng xoay, test đỏ.
- [ ] R6.5: ca `RecordAssignPort` của bộ contract test: gửi lại cùng khoá → người đã giao lần đầu, không giao lần hai,
      trên bản giả và trên `AssignRecordService` thật; sửa bản giả để giao lại theo vòng xoay → ca đó đỏ trên bản giả.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/workflows/test_data_object_nodes.py packages/python/dw_studio/tests/workflows/test_assign_node.py packages/python/dw_studio/tests/workflows/test_records_port_contract.py && make test-integration` xanh.

## Nguồn

- custom-objects:R5.6, custom-objects:R8.9; `.claude/plans/studio/custom-objects/issues/04-truy-van-ban-ghi.md`.
- record-access:R6.4, record-access:R8.1; `.claude/plans/studio/record-access/issues/05-giao-nguoi-phu-trach.md`.
- ADR-0112 (Accepted) quyết 6; spec: R2.1, R5.1, R5.5.
- workflow-engine:R4.5, workflow-engine:R4.7; `.claude/plans/studio/workflow-engine/issues/03-bien-dich-va-wrapper-nut.md`;
  spec: R5.1, R5.5 (bản giả của `RecordsPort` mà bộ contract test phủ, H-7), R6.5 (khoá chống lặp, V4.30).
- workflow-engine:R7.3 (lệnh sửa trong làn song song là PATCH theo trường); spec: R5.1 (V4.34).

## Comments

- 2026-10-23 (agent): theo phiếu 23/10/2026: giả lập ghi bản ghi ở RecordService, R5.3 rút và R5.5 thay (D:custom-objects:R5.4~workflow-nodes:R5.3); người dự phòng là điểm gắn kind `principal` duyệt hai người, nhóm ở W2 (Q6), nên ticket chờ tenant-config/05.
- 2026-10-24 (agent): theo quyết định của Đạt ngày 24/10/2026: khoá chống lặp là của workflow-engine:R4.5; giao qua `AssignRecordService` (record-access/05), không qua `studio.assign_record`, không audit riêng.
- 2026-10-24 (agent): theo V4.24 của Đạt: làn lỗi chỉ có khi Khi lỗi là `route`, nên R6.4 nói Bước kết thúc với lỗi theo Khi lỗi của nó thay "đi Nhánh ra lỗi", và tiêu chí của nó thử cả `route` lẫn `fail`. Không thêm cạnh.
- 2026-10-25 (agent): lượt h: theo H-7, bộ contract test của `RecordsPort` khai cùng Protocol ở ticket này và chạy trên bản giả của workflow-engine/03 lẫn `RecordService` thật; thêm cạnh tới workflow-engine/03, ngoài bảng cạnh của lượt, vì hai ticket chưa có đường nào nối nhau nên bộ không chạy được trên bản giả khi ticket này đến trước (đã chạy g.py trên cây hiện tại cộng các cạnh của lượt: không vòng, marketing-pilot/03 vẫn ở độ sâu 15, ticket này vẫn ở độ sâu 14). Theo V4.30 (mục 10): Bước giao chuyển khoá của wrapper nút cho dịch vụ giao, để chạy lại không giao cho người kế tiếp (R6.5); dòng `Xong:` thêm `make test-integration` vì bộ contract và ca R6.5 cần PostgreSQL thật.
- 2026-10-26 (agent): lượt h, rà lại theo V4.34 của Đạt: workflow-engine:R7.3 (ngữ nghĩa thực thi, lệnh sửa trong làn song song là PATCH theo trường) dựa vào R5.1 của spec này, nên R5.1 nói lệnh sửa một bản ghi có sẵn của Bước chỉ mang các trường cấu hình của Bước nêu, bước 1 và bộ contract test thêm ca PATCH, và một tiêu chí mới của R5.1 có ca âm (gửi cả bản ghi đã đọc thì giá trị của lệnh kia bị ghi đè). Không thêm cạnh.
- 2026-10-26 (agent): lượt h, sau đợt 1: H-30, `RecordsPort` và `RecordAssignPort` khai ở workflow-engine/03 (người dùng đầu tiên, đứng trước workflow-nodes/04), workflow-nodes/04 chạy bộ contract test trên bản thật. Không thêm cạnh.
