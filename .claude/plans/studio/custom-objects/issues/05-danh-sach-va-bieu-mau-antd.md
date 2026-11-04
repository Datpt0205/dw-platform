# 05 — Danh sách và biểu mẫu antd sinh từ describe

Status: ready-for-agent
Blocked by: 04, .claude/plans/studio/studio-skeleton/issues/03-seam-web-va-allowlist-antd.md, .claude/plans/studio/record-access/issues/05-giao-nguoi-phu-trach.md
Area: studio
Yêu cầu: R10.1, R10.2, R10.3, R10.4, R10.5, R10.6, R10.7

## Mục tiêu

Màn tối thiểu của lát Marketing: danh sách, chi tiết, tạo và sửa bản ghi, sinh từ describe theo người xem (R10).
Nhân viên Sales thấy lead được giao cho mình và không thấy lead khác; trường Đã ẩn hiện "Đã ẩn", không bao giờ để
trống.

## Việc cần làm

1. Trang trong `apps/web/app/studio/objects/[api_name]/`, dưới layout Studio của studio-skeleton/03:
    - `page.tsx`: antd `Table` với `pagination={false}` và nút "Tải thêm" theo `cursor`, `rowKey="id"`, `sticky`; cột
      là `name` cộng các trường mà describe của người xem đánh dấu lọc được, theo thứ tự của describe, nên một trường Đã
      ẩn với người xem không thành cột (gate 4/11/2026 (b)); sắp theo cột describe đánh dấu sắp được (W1: `name`,
      `created_at`, `updated_at`) bằng `order_by` của máy chủ, mặc định `created_at` giảm dần, `order_by` nằm trên URL
      của trang, không sắp lại ở trình duyệt; mọi lần nạp danh sách gọi `POST .../records/query` (ticket 04 bước 4: giá
      trị lọc và con trỏ không vào URL của API); ô tên là link thật tới bản ghi; không có ô tìm (tìm không dấu ở W2).
    - `name` Đã ẩn với người xem: ô tên là link có `HiddenValue` cộng 8 ký tự đầu của id, tên truy cập "Bản ghi đã ẩn
      tên, mã <8 ký tự>", và `<title>` của trang bản ghi là nhãn `vi` của đối tượng cộng "(tên đã ẩn)"; không chỗ nào
      của trang, kể cả `<title>`, breadcrumb và tên truy cập, mang giá trị của một trường Đã ẩn (gate (c);
      `.claude/rules/ui-quality.md` §6).
    - `[record_id]/page.tsx`: chi tiết và sửa; `<title>` là tên bản ghi khi người xem đọc được `name`. `permissions.update`
      sai → trang chỉ xem, mọi control `disabled`, không nút Lưu.
    - `new/page.tsx`: tạo bản ghi, sinh từ `describe?action=create` (ticket 03), không từ describe đọc, nên vai chỉ
      tạo thấy control sửa được cho trường nó ghi được.
    - `apps/web/app/studio/objects/page.tsx`: danh sách đối tượng người xem đọc được từ `GET /api/v1/studio/objects`
      (spec R3.5), mỗi dòng một link tới `/studio/objects/[api_name]`; một mục `{ key: "objects", href: "/studio/objects",
label: "Đối tượng", readKey: "studio.objects.manage" }` trong `STUDIO_SECTIONS` của studio-skeleton/03, vì
      `readKey` là khóa đọc mà mục registry của loại `object` khai; người chỉ giữ `obj.<api_name>.read` tới trang bản
      ghi qua link, còn mục điều hướng cho họ không thuộc ticket này (gate (h)).
2. `apps/web/components/records/field-registry.tsx`, một bảng kiểu sang control và cách hiển thị: `text`, `email`,
   `phone`, `url` → `Input` với `maxLength` từ describe; số `exact` và tiền → `InputNumber` với `stringMode` và
   `precision` bằng `scale` của describe, giá trị là chuỗi, đơn vị theo `currency_code`; số `float` →
   `InputNumber`; `date`, `datetime` → `DatePicker` qua `apps/web/lib/dates.ts`; `boolean` → `Switch`; `picklist`
   → `Select` các lựa chọn đang bật. Tiền hiển thị qua một hàm định dạng nhận chuỗi, thêm vào `apps/web/lib/money.ts`,
   không đổi sang số JS.
3. `HiddenValue` trong `@dw/ui`: chữ "Đã ẩn" với `LockOutlined`, cho mọi tên trong `hidden_fields` và mọi trường
   describe đánh dấu `access: hidden`, ở ô `name` của danh sách (cột duy nhất có thể Đã ẩn, bước 1) và mọi trường của
   trang bản ghi, kể cả khi trường trống
   (ADR-0106 (Accepted) quyết định 4). Trường describe đánh dấu không sửa được → control `disabled` với lý do trong
   `Tooltip`: `access: read` → "Vai trò của bạn chỉ cho xem trường này"; cờ sửa được sai trong định nghĩa → "Trường này
   không sửa được".
4. `RecordForm` trên antd `Form` theo quy ước biểu mẫu của `.claude/rules/ui-quality.md`: `validateTrigger="onBlur"`,
   `scrollToFirstError`, một `Alert` tổng hợp; `errors[].pointer` → `form.setFields` qua `fieldErrors()` có sẵn của
   `apps/web/lib/error-message.ts`, không bộ ánh xạ thứ hai; lưu gửi `If-Match` bằng ETag đang giữ; 412 → biểu mẫu
   `GET` lại bản ghi, vùng xung đột trong chính biểu mẫu (không để `RegionState` thay chỗ biểu mẫu) hiện giá trị máy chủ
   cạnh giá trị đã gõ của mỗi trường khác nhau, giữ nội dung đã gõ, và cho hai lối ra: "Lưu bản của tôi" gửi lại với
   ETag mới, "Dùng bản trên máy chủ" bỏ nội dung đã gõ (gate (f)); vùng xung đột so ba bên (bản gốc lúc mở, đã gõ, máy
   chủ) và chỉ nêu trường cả hai bên cùng đổi, còn "Lưu bản của tôi" gửi Merge Patch chỉ các trường người dùng đã đổi
   so với bản gốc, không ghi đè trường chỉ tab kia đổi; 403 `field_not_editable` và 409 `duplicate_value` có con trỏ
   gắn vào trường như 422 và giữ nội dung đã gõ, không để `RegionState` thay biểu mẫu; 429 hiện `Alert` nêu lúc thử
   lại theo `Retry-After`; một `Idempotency-Key` cho mỗi lần bấm (lượt xác nhận (i)).
5. Mọi lời gọi qua `ApiClient` sinh từ OpenAPI với zod chung; thông điệp lỗi của trường dựng từ `errors[].code`
   (`required`, `invalid_type`, `max_length`, `value_not_allowed`, `scale_exceeded`, `unknown_field`,
   `field_not_editable`, `duplicate_value` của ticket 03) qua một bảng câu tiếng Việt cạnh `errorMessage()` trong
   `apps/web/lib/error-message.ts`, mã lạ thì dùng `errors[].detail` của lỗi đó khi có, không thì `message` cấp trên,
   và `fieldErrors()` có sẵn đọc thêm `detail` (gate (g)); nhãn tiếng Việt lấy từ describe. Trường hệ thống `owner`,
   `workspace_id`, `created_at`, `updated_at` hiện trên trang bản ghi từ thân `GET`, chỉ đọc, không qua field-registry;
   lựa chọn đã tắt (describe `active: false`) hiện nhãn kèm "(đã tắt)" và không có trong danh sách chọn; số theo `vi`:
   dấu thập phân `,`, nhóm hàng nghìn `.`, một bộ định dạng trong `apps/web/lib/money.ts` cho tiền mọi `currency_code`
   và số `exact`; nút "Tạo" và trang `new` khóa với lý do trong `Tooltip` khi `actions.create` của
   `GET /api/v1/studio/objects` sai (ticket 03 (x)); 403 của máy chủ vẫn là lời từ chối thật (lượt xác nhận (j)).
6. Playwright trong `apps/web/e2e/` ở hai dự án `phone-320` và `wide-992`; fixture tạo dữ liệu qua API công khai
   cho lần giao (route của record-access/05); đối tượng, người, vai và quyền trường gieo bằng một script
   `scripts/seed_e2e_records.py` (`uv run`, URL `dw_migrator` của database dev từ biến môi trường) mà `globalSetup` của
   Playwright gọi, tạo một công ty mới mỗi lần chạy và đăng nhập bằng `issue_dev_token.py`, đối tượng qua móc phát hành
   của ticket 02 với phê duyệt fixture như test của ticket 02, vai và quyền trường ghi thẳng vào bảng (dữ liệu gieo,
   không phải thứ đang thử; luồng phát hành là của ticket 06, luồng duyệt vai hai người là của tenant-rbac) (lượt xác
   nhận (k)): đối tượng
   `mkt_lead` với `phone` (`basic`, `secured`), `score` (số `exact` `scale` 2), `status` (danh sách chọn, bắt buộc) và
   `note` (chữ, `max_length` 20); một trưởng nhóm có đọc, tạo, sửa và giao Lead ở mức Toàn công ty, `phone` sửa được,
   `score` chỉ đọc; một nhân viên Sales có đọc Lead ở mức Của tôi, `phone` Đã ẩn; hai lead do trưởng nhóm tạo, một lead
   giao cho nhân viên Sales. Ca R10.4 tới R10.6 chạy dưới trưởng nhóm, ca R10.2, R10.3 dưới nhân viên Sales (gate (d),
   (e)).
7. vitest cho `field-registry` và cho ánh xạ `errors[]` sang trường.

## Tiêu chí chấp nhận

- [ ] R10.1: người có quyền đọc mở `/studio/objects/mkt_lead` thấy cột và nhãn tiếng Việt từ describe; "Tải thêm"
      nạp trang kế mà không lặp dòng nào.
- [ ] R10.2: nhân viên Sales chỉ thấy lead được giao cho mình; lead kia không có trong danh sách, và mở thẳng URL của
      nó → trạng thái "không tìm thấy".
- [ ] R10.3: trường Đã ẩn hiện "Đã ẩn" có biểu tượng khóa ở danh sách và trang bản ghi, kể cả trường trống; giá trị
      không có trong DOM lẫn trong phản hồi mạng.
- [ ] R10.4: trường chỉ đọc bị khóa và `Tooltip` nêu lý do.
- [ ] R10.5: máy chủ trả một 422 có ba lỗi (giả bằng `page.route`, vì kiểm ở trình duyệt chặn các lỗi đó trước khi gửi;
      hợp đồng máy chủ là của ticket 03) → ba trường hiện lỗi đúng chỗ và `Alert` báo còn 3 trường cần sửa, đếm cả lỗi
      của máy chủ; 409 `duplicate_value` con trỏ `/fields/phone` → lỗi dưới `phone`, nội dung đã gõ còn; vitest cho ánh
      xạ con trỏ đỏ khi bỏ ánh xạ.
- [ ] R10.6: hai tab cùng sửa một bản ghi, tab sau lưu → vùng xung đột có cả hai giá trị và nội dung đã gõ còn nguyên.
- [ ] R10.7: ở `phone-320` và `wide-992`, trang danh sách và trang bản ghi không cuộn ngang, có đúng một `h1`, console
      không có vi phạm CSP.
- [ ] R10.3: với nhân viên Sales mà `name` Đã ẩn (đối tượng thử thứ hai có `name_field` `basic`, `secured`), ô tên
      hiện "Đã ẩn" cùng mã ngắn, `<title>` và tên truy cập của link không chứa tên thật; tên thật không có trong DOM.
- [ ] R10.6: 412 rồi "Lưu bản của tôi" → lưu thành công với ETag mới; "Dùng bản trên máy chủ" → biểu mẫu mang giá
      trị máy chủ; trong lúc xung đột, biểu mẫu không bị thay bằng trạng thái lỗi của vùng.
- [ ] R10.5: vitest: mỗi mã của bảng có câu tiếng Việt; mã lạ → `message` của máy chủ; bỏ một mã khỏi bảng → test đỏ.
- [ ] R10.1: người giữ `studio.objects.manage` thấy mục "Đối tượng" trong menu Studio và trang `/studio/objects`
      liệt kê đúng các đối tượng họ đọc được; người không giữ khóa đó không thấy mục.
- [ ] Xong: `make test-web` xanh.

## Nguồn

- `apps/web/lib/money.ts:21`; `apps/web/lib/dates.ts:18`; spec: R10.1.
- `.claude/rules/ui-quality.md:85`; `.claude/rules/ui-quality.md:111`; `.claude/rules/ui-quality.md:282`; spec: R10.5,
  R10.6.
- `.claude/rules/ui-quality.md:126-128`; `.claude/rules/ui-quality.md:266`; spec: R10.1, R10.2.
- `packages/typescript/ui/src/region-state.tsx:34-43`; spec: R10.6.
- `apps/web/playwright.config.ts:46-48`; spec: R10.7.
- ADR-0106 (Accepted) quyết định 4.

## Comments

- 2026-10-23 (agent): `make test-web` chưa chạy trong CI (Makefile ghi rõ); đưa nó vào CI là quyết định Đạt còn nợ,
  nên dòng Xong chạy tay cho tới khi có quyết định đó.
- 2026-10-23 (agent): DO-16.1 (a) đã có lời đáp (Đạt, 23/10/2026); Status về needs-triage. "Đã ẩn" hiện ở cả danh sách
  theo describe `access: hidden` (`B:custom-objects:R6.5~field-security:R3.3`).
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check, một subagent; ticket không thêm migration hay route,
  có màn hình): 0 CRITICAL, 8 HIGH, sửa theo khuyến nghị (Quyết định 4/11/2026 của spec): (a) describe trả thuộc tính số
  và độ dài (ticket 03); (b) cột theo describe của người xem; (c) `name` Đã ẩn không lọt qua `<title>`; (d) chờ
  record-access/05 cho lần giao, đối tượng gieo qua móc của ticket 02 vì ticket 06 đứng sau; (e) fixture đủ người, vai,
  trường; (f) 412 có hai lối ra; (g) một bảng câu theo mã; (h) mục "Đối tượng" của Studio và `/studio/objects`.
- 2026-11-04 (agent): MEDIUM để lại: (M1) mục điều hướng cho người chỉ đọc bản ghi, không giữ
  `studio.objects.manage`, không có ở W1: tới trang qua link; (M2) `make test-web` chưa trong CI (Comments 23/10/2026),
  dòng Xong chạy tay; (M3) ảnh Playwright sáng, tối, desktop và dưới 992px theo design v3 ở lần đóng hàng đợi.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận: 0 CRITICAL, 4 HIGH, sửa: R10.3 ở danh sách chỉ ô `name` (spec R10.3 sửa cùng); 422 của
  R10.5 giả bằng `page.route`; (i) vùng xung đột ba bên và Merge Patch, 403 và 409 có con trỏ gắn vào trường, 429 qua
  `Alert`; (k) script gieo e2e mỗi lần một công ty mới. Sửa luôn: (j) trường hệ thống, lựa chọn đã tắt, định dạng số
  `vi`, nút Tạo theo `actions.create`. Sửa của lượt này không có người đọc mới: nhận rủi ro (agent, theo ủy quyền 31/10/2026). Nếu sai thì: ghi ở đây
  khi dựng. Thứ tự dựng: sau 04, record-access/05, studio-skeleton/03; cuối của khu vực.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): `checking-plan-consistency` của vùng studio (B:custom-objects/03~field-security/01, HIGH): biểu mẫu tạo đọc `describe?action=create` của ticket 03. Nếu sai thì: biểu mẫu tạo gọi route riêng mà ticket 03 thêm.
