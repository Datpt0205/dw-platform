# 05 — Danh sách và biểu mẫu antd sinh từ describe

Status: needs-info (DO-16)
Blocked by: 04, .claude/plans/studio/studio-skeleton/issues/03-seam-web-va-allowlist-antd.md
Area: studio
Yêu cầu: R10.1, R10.2, R10.3, R10.4, R10.5, R10.6, R10.7

## Mục tiêu

Màn tối thiểu của lát Marketing: danh sách, chi tiết, tạo và sửa bản ghi, sinh từ describe theo người xem (R10).
Nhân viên Sales thấy lead được giao cho mình và không thấy lead khác; trường Đã ẩn hiện "Đã ẩn", không bao giờ để
trống.

## Việc cần làm

1. Trang trong `apps/web/app/studio/objects/[api_name]/`, dưới layout Studio của studio-skeleton/03:
    - `page.tsx`: antd `Table` với `pagination={false}` và nút "Tải thêm" theo `cursor`, `rowKey="id"`, `sticky`; cột
      lấy từ describe (`name` và trường lọc được); sắp theo cột sắp được bằng `order_by` của máy chủ, `order_by` nằm
      trên URL, không sắp lại ở trình duyệt; ô tên là link thật tới bản ghi; không có ô tìm (tìm không dấu ở W2).
    - `[record_id]/page.tsx`: chi tiết và sửa; `<title>` là tên bản ghi.
    - `new/page.tsx`: tạo bản ghi.
2. `apps/web/components/records/field-registry.tsx`, một bảng kiểu sang control và cách hiển thị: `text`, `email`,
   `phone`, `url` → `Input`; số `exact` và tiền → `InputNumber` với `stringMode`, giá trị là chuỗi; số `float` →
   `InputNumber`; `date`, `datetime` → `DatePicker` qua `apps/web/lib/dates.ts`; `boolean` → `Switch`; `picklist`
   → `Select` các lựa chọn đang bật. Tiền hiển thị qua một hàm định dạng nhận chuỗi, thêm vào `apps/web/lib/money.ts`,
   không đổi sang số JS.
3. `HiddenValue` trong `@dw/ui`: chữ "Đã ẩn" với `LockOutlined`, cho mọi tên trong `hidden_fields`
   (ADR-0106 (Proposed) quyết định 4). Trường describe đánh dấu không sửa được → control `disabled` với lý do trong
   `Tooltip`.
4. `RecordForm` trên antd `Form` theo quy ước biểu mẫu của `.claude/rules/ui-quality.md`: `validateTrigger="onBlur"`,
   `scrollToFirstError`, một `Alert` tổng hợp; `errors[].pointer` → `form.setFields`; lưu gửi `If-Match` bằng ETag
   đang giữ; 412 → vùng xung đột hiện giá trị máy chủ cạnh giá trị đã gõ và giữ nội dung đã gõ; một
   `Idempotency-Key` cho mỗi lần bấm.
5. Mọi lời gọi qua `ApiClient` sinh từ OpenAPI với zod chung; thông điệp lỗi dựng từ `code` và `errors[].code` qua
   `errorMessage()`; nhãn tiếng Việt lấy từ describe.
6. Playwright trong `apps/web/e2e/` ở hai dự án `phone-320` và `wide-992`; fixture tạo dữ liệu qua API công khai: một
   nhân viên Sales có quyền đọc Lead ở mức Của tôi, hai lead, một lead giao cho người đó.
7. vitest cho `field-registry` và cho ánh xạ `errors[]` sang trường.

## Tiêu chí chấp nhận

- [ ] R10.1: người có quyền đọc mở `/studio/objects/mkt_lead` thấy cột và nhãn tiếng Việt từ describe; "Tải thêm"
      nạp trang kế mà không lặp dòng nào.
- [ ] R10.2: nhân viên Sales chỉ thấy lead được giao cho mình; lead kia không có trong danh sách, và mở thẳng URL của
      nó → trạng thái "không tìm thấy".
- [ ] R10.3: trường Đã ẩn hiện "Đã ẩn" có biểu tượng khóa; giá trị không có trong DOM lẫn trong phản hồi mạng.
- [ ] R10.4: trường chỉ đọc bị khóa và `Tooltip` nêu lý do.
- [ ] R10.5: lưu một biểu mẫu có ba lỗi 422 → ba trường hiện lỗi đúng chỗ và `Alert` báo còn 3 trường cần sửa; vitest
      cho ánh xạ con trỏ đỏ khi bỏ ánh xạ.
- [ ] R10.6: hai tab cùng sửa một bản ghi, tab sau lưu → vùng xung đột có cả hai giá trị và nội dung đã gõ còn nguyên.
- [ ] R10.7: ở `phone-320` và `wide-992`, trang danh sách và trang bản ghi không cuộn ngang, có đúng một `h1`, console
      không có vi phạm CSP.
- [ ] Xong: `make test-web` xanh.

## Nguồn

- `apps/web/lib/money.ts:21`; `apps/web/lib/dates.ts:18`; spec: R10.1.
- `.claude/rules/ui-quality.md:85`; `.claude/rules/ui-quality.md:111`; `.claude/rules/ui-quality.md:282`; spec: R10.5,
  R10.6.
- `.claude/rules/ui-quality.md:126-128`; `.claude/rules/ui-quality.md:266`; spec: R10.1, R10.2.
- `packages/typescript/ui/src/region-state.tsx:34-43`; spec: R10.6.
- `apps/web/playwright.config.ts:46-48`; spec: R10.7.
- ADR-0106 (Proposed) quyết định 4.

## Comments

- 2026-10-23 (agent): `make test-web` chưa chạy trong CI (Makefile ghi rõ); đưa nó vào CI là quyết định Đạt còn nợ,
  nên dòng Xong chạy tay cho tới khi có quyết định đó.
