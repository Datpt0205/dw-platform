# 02 — Áp bảo mật trường ở API bản ghi, agent, workflow, phê duyệt và lịch sử chạy

Status: needs-triage
Blocked by: 01, .claude/plans/studio/custom-objects/issues/04-truy-van-ban-ghi.md, .claude/plans/studio/tools-and-skills/issues/03-cong-cu-du-lieu-doi-tuong.md, .claude/plans/studio/workflow-nodes/issues/03-pham-vi-bien-va-buoc-logic.md, .claude/plans/studio/workflow-nodes/issues/06-tool-call-va-human-approval.md, .claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md
Area: studio
Yêu cầu: R3.1, R3.2, R3.3, R3.4, R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, R4.7, R5.1, R5.2, FS2, FS3, FS4, FS5, FS6, FS8, FS9, FS10

## Mục tiêu

Áp `FieldAccess` của ticket 01 ở mọi đường phát giá trị bản ghi, nên một trường `hidden` với người xem vắng mặt khắp
nơi: API bản ghi (chiếu, lọc, sắp, nhóm, đếm, ghi, describe) (R3), công cụ agent, chuỗi mẫu quy trình, phê duyệt và
lịch sử chạy (R4), và một hàm là chủ duy nhất với test kiến trúc cùng kiểm mutation MP6 (R5). Vai Sales không được cấp
`fld.lead.phone.*` không lấy được số điện thoại qua bất kỳ đường nào của lát Marketing.

## Việc cần làm

1. **API bản ghi.** Adapter bản ghi và bộ biên dịch truy vấn (custom-objects ticket 03, 04) nhận `FieldAccess` từ
   `resolve_field_access` của ticket 01:
    - SELECT chỉ cột hệ thống và slot mà `visible_fields` cho phép; giá trị trường `hidden` vắng khỏi thân trả về, tên
      của mọi trường `hidden` của đối tượng vào `hidden_fields`, kể cả trường không có giá trị;
    - bộ biên dịch lọc, `order_by`, nhóm, đếm từ chối một trường `hidden` với người gọi bằng 422 `validation_failed` với
      `errors[].code` `field_not_readable` và `errors[].pointer` trước khi sinh SQL, kể cả khi không bản ghi nào khớp;
    - đường ghi từ chối theo từng trường bằng 403 `field_not_editable` khi `FieldAccess` của trường là `read` hoặc
      `hidden`, và lùi giao dịch;
    - `describe` đánh dấu mỗi trường của đối tượng `hidden`, `read` hoặc `edit`; trường `hidden` chỉ có `api_name`, nhãn
      và `access: hidden`.
    - Mã lỗi và route thuộc custom-objects (`custom-objects:R3.2`, `custom-objects:R6.6`, `custom-objects:R8.4`);
      ticket này cài lớp áp `FieldAccess` trong adapter và bộ biên dịch mà chúng gọi.
2. **Công cụ agent.** Bộ dựng lược đồ công cụ đối tượng (tools-and-skills ticket 03) dựng JSON Schema chỉ từ
   `visible_fields(chủ thể)` giao với giới hạn dữ liệu của lượt chạy, khóa theo `fls_version`; đầu ra công cụ đối
   tượng chiếu cùng tập, trường ngoài tập vắng.
3. **Chuỗi mẫu quy trình.** Bộ dựng chuỗi mẫu `{{node.var}}` (workflow-nodes ticket 03) hỏi `resolve_field_access` cho
   chủ thể chạy; một tham chiếu trường `hidden` làm bước lỗi `template_field_hidden`, không gửi và không tác động.
4. **Phê duyệt.** Payload phê duyệt (workflow-nodes ticket 06) lưu tham chiếu bản ghi và tên trường, không lưu giá trị;
   trang duyệt dựng bản xem trước lấy giá trị sống theo quyền người xem và hiện `Đã ẩn` cho trường người xem không đọc
   được. Một hàm của `dw_studio.field_security` trả "người này giữ `Xem` trên mọi trường bước đã đóng dấu" (DO-36): bộ
   chọn người duyệt chỉ trả người qua hàm đó (R4.5), và ticket này thêm điều kiện đó vào
   `decision_guards["studio.step.approval"]` của workflow-nodes/06 ở composition root, đọc database qua guard async của
   tenant-config/05, nên người mất quyền đọc sau khi phê duyệt mở nhận 403 tại `decide` (R4.7; mã theo bảng mã từ chối
   người quyết: thấy được mà không đủ quyền là 403).
5. **Lịch sử chạy.** Lịch sử chạy theo bước (telemetry-and-audit ticket 03) hiện tên trường và lấy giá trị sống theo
   quyền người xem ở lúc xem, không giá trị đóng dấu lúc lượt chạy chạy.
6. **Một hàm, một người đọc.** Test kiến trúc: ngoài adapter bản ghi, không mô-đun nào đọc `studio.records` hay một cột
   slot (mở rộng `custom-objects:R5.6` sang đọc giá trị); kiểm mutation MP6: gỡ áp `FieldAccess` ở từng đường (chiếu
   REST, lược đồ công cụ, chuỗi mẫu, phê duyệt, lịch sử chạy) làm test rò của đúng đường đó đỏ, ghi lại một lần đỏ mỗi
   đường.

## Tiêu chí chấp nhận

- [ ] R3.1 (FS5): list và get không có giá trị của trường `hidden` với người gọi, tên trường ẩn có trong
      `hidden_fields`; quét JSON của list, get → không có giá trị đã gieo; gỡ chiếu cột → test đỏ.
- [ ] R3.2 (FS3): lọc theo `phone` ẩn → 422 `validation_failed` với `errors[].code` `field_not_readable` và con trỏ tới
      lá đó, cả khi 0 bản ghi khớp; `order_by` theo trường ẩn → 422 trước khi sinh SQL; gỡ kiểm trong bộ biên dịch → test
      đỏ.
- [ ] R3.3 (FS4): `PATCH {status, phone}` khi `phone` chỉ `read` với người gọi → 403 `field_not_editable` trỏ tới
      `phone`, `status` không đổi; gỡ kiểm theo trường → test đỏ.
- [ ] R3.4 (FS5): `describe` trả trường `hidden` với người gọi chỉ với `api_name`, nhãn và `access: hidden`, mỗi trường
      còn lại đánh dấu `read` hoặc `edit`; một trường `hidden` trống vẫn có tên trong `hidden_fields` của `GET`.
- [ ] R4.1 (FS8): lược đồ công cụ đối tượng của một lượt chạy chỉ gồm trường trong `visible_fields(chủ thể)` giao với
      giới hạn dữ liệu; một trường chủ thể được cấp nhưng ngoài giới hạn vắng khỏi lược đồ.
- [ ] R4.2 (FS8): đầu ra công cụ đối tượng không có trường `hidden` với giao của chủ thể và giới hạn; mở rộng giới hạn
      dữ liệu của phiên bản → test đỏ.
- [ ] R4.3 (FS6): `{{lead.phone}}` khi chủ thể chạy không đọc được `phone` → bước lỗi `template_field_hidden`, 0 lần
      gửi; gỡ kiểm mẫu → test đỏ.
- [ ] R4.4 (FS9): người duyệt không có `Xem` trên `phone` thấy `Đã ẩn` trong nội dung tin nhắn chờ duyệt; payload phê
      duyệt không lưu giá trị `phone`.
- [ ] R4.5 (FS10): phê duyệt tham chiếu `phone` → bộ chọn người duyệt chỉ trả người giữ `fld.lead.phone.read`; thêm
      một người thiếu quyền vào danh sách → test đỏ.
- [ ] R4.7 (FS10): người duyệt mất `fld.lead.phone.read` sau khi phê duyệt bước mở, gọi `decide` → 403, không ghi quyết
      định, phê duyệt vẫn chờ; người còn quyền → quyết được; gỡ điều kiện đọc trường khỏi guard → test đỏ.
- [ ] R4.6 (FS9): lịch sử chạy hiện tên trường và giá trị sống theo quyền người xem; người xem mất `Xem` trên `phone`
      sau khi chạy → thấy `Đã ẩn`; đóng dấu giá trị lúc lượt chạy chạy → test đỏ.
- [ ] R5.1 (FS2): kiểm mutation — gỡ áp `FieldAccess` ở một đường trong (chiếu REST, lược đồ công cụ, chuỗi mẫu, phê
      duyệt, lịch sử chạy) → test rò của đúng đường đó đỏ.
- [ ] R5.2 (FS2): thêm một mô-đun ngoài adapter bản ghi đọc `studio.records` hay một cột slot → test kiến trúc đỏ.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `docs/adr/0106-field-access-follows-personal-data-category.md:62-77`; spec: R3, R4, R5.
- `.claude/plans/studio/custom-objects/spec.md:157`; spec: R5.2 (chỉ adapter bản ghi nhắc `studio.records`).
- `.claude/plans/studio/custom-objects/spec.md:219`; spec: R3.2 (lọc, sắp trên trường Đã ẩn → 422 `field_not_readable`).
- `packages/python/dw_observability/src/dw_observability/redaction.py:1`; spec: R4.6 (bộ che chỉ che bí mật, không che giá trị trường theo quyền).

## Comments

- 2026-10-23 (agent): `Blocked by` trỏ tới tools-and-skills ticket 03 và telemetry-and-audit ticket 03 đang viết cùng đợt; tệp sẽ có khi đợt này xong.
- 2026-10-23 (agent): DO-36 (a) và `B:custom-objects:R6.5~field-security:R3.3` (a) đã có lời đáp (Đạt, 23/10/2026): thêm R4.7 (guard tại `decide`), describe liệt kê trường ẩn với `access: hidden`, lỗi lọc là `errors[].code` `field_not_readable` dưới `validation_failed`.
