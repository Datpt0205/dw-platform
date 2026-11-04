# 02 — Áp bảo mật trường ở API bản ghi, agent, workflow, phê duyệt và lịch sử chạy

Status: ready-for-agent
Blocked by: 01, .claude/plans/studio/custom-objects/issues/04-truy-van-ban-ghi.md, .claude/plans/studio/tools-and-skills/issues/03-cong-cu-du-lieu-doi-tuong.md, .claude/plans/studio/workflow-nodes/issues/03-pham-vi-bien-va-buoc-logic.md, .claude/plans/studio/workflow-nodes/issues/06-tool-call-va-human-approval.md, .claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md
Area: studio
Yêu cầu: R3.1, R3.2, R3.3, R3.4, R4.1, R4.2, R4.3, R4.4, R4.5, R4.6, R4.7, R4.8, R5.1, R5.2, FS2, FS3, FS4, FS5, FS6, FS8, FS9, FS10, FS14

## Mục tiêu

Áp `FieldAccess` của ticket 01 ở mọi đường phát giá trị bản ghi, nên một trường `hidden` với người xem vắng mặt khắp
nơi: API bản ghi (chiếu, lọc, sắp, nhóm, đếm, ghi, describe) (R3), công cụ agent, chuỗi mẫu quy trình, phê duyệt và
lịch sử chạy (R4), và một hàm là chủ duy nhất với test kiến trúc cùng kiểm mutation MP6 (R5). Vai Sales không được cấp
`fld.lead.phone.*` không lấy được số điện thoại qua bất kỳ đường nào của lát Marketing.

## Việc cần làm

0. **Mọi đường lấy `FieldAccess` từ `FieldAccessService.for_object` của ticket 01** trong giao dịch của chính yêu cầu
   hay lời gọi công cụ, không bộ đệm theo người gọi (spec R2.9). Fixture của các test rò dùng một vai chỉ giữ
   `obj.lead.read` (không `create`, `update`), để R2.6 không làm `phone` duy nhất hiện ra.
1. **API bản ghi.** Adapter bản ghi và bộ biên dịch truy vấn (custom-objects ticket 03, 04) nhận `FieldAccess` từ
   `resolve_field_access` của ticket 01:
    - SELECT luôn có `id`, `owner`, `workspace_id`, `version` và các mốc thời gian; trường `name`, mỗi slot và mỗi khóa
      `field_no` trong cột `data` chỉ khi `visible_fields` cho phép: cột `data` không bao giờ trả nguyên mà dựng trong SQL
      từ đúng các khóa được phép (hay bỏ khóa của trường `hidden`), vì trường không lọc được nằm trong `data`, không có
      cột riêng; giá trị trường `hidden` vắng khỏi thân trả về, tên của mọi trường `hidden` của đối tượng vào
      `hidden_fields`, kể cả trường không có giá trị;
    - bộ biên dịch lọc, `order_by`, nhóm, đếm từ chối một trường `hidden` với người gọi bằng 422 `validation_failed` với
      `errors[].code` `field_not_readable` và `errors[].pointer` trước khi sinh SQL, kể cả khi không bản ghi nào khớp;
    - đường ghi từ chối theo từng trường bằng 403 `field_not_editable` khi `FieldAccess` của trường là `read` hoặc
      `hidden`, và lùi giao dịch;
    - `describe` đánh dấu mỗi trường của đối tượng `hidden`, `read` hoặc `edit`; trường `hidden` chỉ có `api_name`, nhãn
      và `access: hidden`.
    - Mã lỗi và route thuộc custom-objects (`custom-objects:R3.2`, `custom-objects:R6.6`, `custom-objects:R8.4`);
      ticket này cài lớp áp `FieldAccess` trong adapter và bộ biên dịch mà chúng gọi.
2. **Công cụ agent.** Bộ dựng lược đồ công cụ đối tượng (tools-and-skills ticket 03) dựng JSON Schema từ lược đồ đầy đủ
   mà bộ đệm của `ObjectSchemaProjector` giữ theo `(tenant_id, object_id, schema_version)` (custom-objects/03 bước 9),
   rồi lọc theo `FieldAccess` của lượt (chủ thể giao mọi mắt xích giới hạn) ở mỗi lần dựng, sau bộ đệm, không bao giờ
   đệm lược đồ đã lọc; lược đồ có `additionalProperties: false`. Đầu ra công cụ đối tượng chiếu theo `FieldAccess` của
   giao dịch của chính lời gọi đó, nên trường đóng hay quyền thu giữa lượt vắng từ lời gọi kế tiếp kể cả khi lược đồ dựng
   lúc đầu lượt còn nêu nó. Tham số lọc, sắp, nhóm, đếm mà model đưa đi qua cùng bộ biên dịch truy vấn của bước 1 với
   `FieldAccess` đó, nên trường `hidden` → `field_not_readable`, 0 dòng (spec R4.8).
3. **Chuỗi mẫu và Biểu thức quy trình.** workflow-nodes/03 dựng kiểm `field_hidden` lúc chạy (bước 2 của nó) trên
   `FieldAccess` của lượt mà `FieldAccessService` trả cho actor `workflow`, nên giới hạn đã nằm trong đó; ticket này
   không viết bộ kiểm thứ hai mà thêm test rò FS6 cho cả hai nhánh (chủ thể thiếu quyền, giới hạn bỏ trường) và đột biến
   của nó. Mã lỗi là `field_hidden` của workflow-nodes (ADR-0106 (Accepted) sửa 4/11/2026).
4. **Phê duyệt.** Giá trị của các trường bước hiển thị không lưu trong payload: trang duyệt lấy chúng sống theo quyền
   người xem và hiện `Đã ẩn` cho trường người xem không đọc được (R4.4); đối số đã render của chủ thể mà workflow-nodes/06
   lưu ở `payload.subject.arguments` chỉ hiện cho người qua `payload_guards["studio.step.approval"]` của workflow-nodes/06.
   Luật người duyệt là `reads_all` của ticket 01 trên `payload.stamped_fields`: workflow-nodes/06 gọi nó trong
   `decision_guards` và `payload_guards` (WN17, R4.7); ticket này thêm nó vào ảnh chụp ứng viên lúc mở của
   workflow-nodes/06 (bước 2 của nó, "Ứng viên tính lúc mở"), một dòng lọc sau phép thu hẹp theo `assignees`, nên ứng
   viên thiếu quyền đọc một trường đóng dấu không có dòng `step_assignments` và không ai còn lại thì `no_approver` của
   workflow-nodes:R9.13 (R4.5).
5. **Lịch sử chạy.** Lịch sử chạy theo bước (telemetry-and-audit ticket 03) lưu payload đã che lúc ghi và che lại theo
   `FieldAccess` của người xem lúc đọc (telemetry-and-audit:R3.3, R3.14); ticket này thêm test rò FS9 và đột biến của
   nó trên route payload của ticket đó.
6. **Một hàm, một người đọc.** Test kiến trúc: ngoài adapter bản ghi, không mô-đun nào đọc `studio.records` hay một cột
   slot (mở rộng `custom-objects:R5.6` sang đọc giá trị); kiểm mutation MP6: gỡ áp `FieldAccess` ở từng đường (chiếu
   REST, lược đồ công cụ, chuỗi mẫu, phê duyệt, lịch sử chạy) làm test rò của đúng đường đó đỏ, ghi lại một lần đỏ mỗi
   đường.

## Tiêu chí chấp nhận

- [ ] R3.1 (FS5): list và get không có giá trị của trường `hidden` với người gọi, tên trường ẩn có trong
      `hidden_fields`; quét JSON của list, get → không có giá trị đã gieo, cả của một trường `hidden` không lọc được (nằm
      trong cột `data`) lẫn của `name` khi `name` `hidden`; gỡ chiếu cột, hay trả `data` nguyên → test đỏ.
- [ ] R3.2 (FS3): lọc theo `phone` ẩn → 422 `validation_failed` với `errors[].code` `field_not_readable` và con trỏ tới
      lá đó, cả khi 0 bản ghi khớp; `order_by` theo trường ẩn → 422 trước khi sinh SQL; gỡ kiểm trong bộ biên dịch → test
      đỏ.
- [ ] R3.3 (FS4): `PATCH {status, phone}` khi `phone` chỉ `read` với người gọi → 403 `field_not_editable` trỏ tới
      `phone`, `status` không đổi; gỡ kiểm theo trường → test đỏ.
- [ ] R3.4 (FS5): `describe` trả trường `hidden` với người gọi chỉ với `api_name`, nhãn và `access: hidden`, mỗi trường
      còn lại đánh dấu `read` hoặc `edit`; một trường `hidden` trống vẫn có tên trong `hidden_fields` của `GET`.
- [ ] R4.1 (FS8): lược đồ công cụ đối tượng của một lượt chạy chỉ gồm trường trong `visible_fields(chủ thể)` giao với
      giới hạn dữ liệu; một trường chủ thể được cấp nhưng ngoài giới hạn vắng khỏi lược đồ.
- [ ] R4.2 (FS8): đầu ra công cụ đối tượng không có trường `hidden` với giao của chủ thể và giới hạn; thu
      `fld.lead.phone.read` của chủ thể giữa hai lời gọi của cùng lượt → lời gọi thứ hai không có `phone`; lượt `agent`
      có chuỗi giới hạn rỗng → đầu ra không có trường nào; mở rộng giới hạn dữ liệu của phiên bản → test đỏ.
- [ ] R4.8 (FS14): model gọi công cụ đối tượng với lọc theo `phone` mà giới hạn bỏ → `field_not_readable`, 0 dòng, cả
      khi không bản ghi nào khớp; thuộc tính lạ trong tham số → lược đồ từ chối; gọi bộ biên dịch không kèm `FieldAccess`
      của lượt → test đỏ.
- [ ] R4.3 (FS6): `{{lead.phone}}` khi chủ thể chạy không đọc được `phone`, và khi chủ thể đọc được mà giới hạn của lượt
      bỏ `phone` → bước lỗi `field_hidden`, 0 lần gửi; gỡ kiểm của workflow-nodes/03 → test đỏ.
- [ ] R4.4 (FS9): người duyệt không có `Xem` trên `phone` thấy `Đã ẩn` cho `phone` trong các trường bước hiển thị của
      tin nhắn chờ duyệt; payload phê duyệt không có giá trị của trường hiển thị; người không qua `payload_guards` nhận
      yêu cầu không có `payload.subject.arguments`.
- [ ] R4.5 (FS10): phê duyệt có `payload.stamped_fields` `["lead.phone"]` → ảnh chụp ứng viên chỉ có người giữ
      `fld.lead.phone.read`; không ứng viên nào còn → `no_approver`; bỏ dòng lọc `reads_all` khỏi ảnh chụp ứng viên →
      test đỏ.
- [ ] R4.7 (FS10): người duyệt mất `fld.lead.phone.read` sau khi phê duyệt bước mở, gọi `decide` → 403, không ghi quyết
      định, phê duyệt vẫn chờ; người còn quyền → quyết được; `reads_all` trả `True` vô điều kiện → test này và WN17 của
      workflow-nodes/06 cùng đỏ.
- [ ] R4.6 (FS9): người xem không có `Xem` trên `phone` gọi route payload lịch sử chạy của telemetry-and-audit/03 → giá
      trị `phone` đã lưu thành `Đã ẩn`; người xem mất `Xem` sau khi chạy → `Đã ẩn`; người còn quyền → thấy giá trị đã
      lưu; gỡ che lúc đọc → test đỏ.
- [ ] R5.1 (FS2): kiểm mutation — gỡ áp `FieldAccess` ở một đường trong (chiếu REST, lược đồ công cụ, chuỗi mẫu, phê
      duyệt, lịch sử chạy) → test rò của đúng đường đó đỏ.
- [ ] R5.2 (FS2): thêm một mô-đun ngoài adapter bản ghi đọc `studio.records` hay một cột slot → test kiến trúc đỏ.
- [ ] Xong: `make ci` xanh.

## Nguồn

- `docs/adr/0106-field-access-follows-personal-data-category.md:62-77`; spec: R3, R4, R5.
- `.claude/plans/studio/custom-objects/spec.md:161`; spec: R5.2 (chỉ adapter bản ghi nhắc `studio.records`).
- `.claude/plans/studio/custom-objects/spec.md:223`; spec: R3.2 (lọc, sắp trên trường Đã ẩn → 422 `field_not_readable`).
- `packages/python/dw_observability/src/dw_observability/redaction.py:1`; spec: R4.6 (bộ che chỉ che bí mật, không che giá trị trường theo quyền).

## Comments

- 2026-10-23 (agent): `Blocked by` trỏ tới tools-and-skills ticket 03 và telemetry-and-audit ticket 03 đang viết cùng đợt; tệp sẽ có khi đợt này xong.
- 2026-10-23 (agent): DO-36 (a) và `B:custom-objects:R6.5~field-security:R3.3` (a) đã có lời đáp (Đạt, 23/10/2026): thêm R4.7 (guard tại `decide`), describe liệt kê trường ẩn với `access: hidden`, lỗi lọc là `errors[].code` `field_not_readable` dưới `validation_failed`.
- 2026-10-24 (agent): vòng sửa 4, lượt bốn: hai neo tới spec của custom-objects ở Nguồn trỏ lại đúng dòng (R5.6 và R8.4 của spec đó), vì lượt bốn thêm dòng vào spec đó; nội dung được neo không đổi.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness, builder check (ticket không migration, không
  route, `wave-close.md`); cùng lượt, boundary walk của spec cho ticket 01 nêu cả phần của ticket này. Sửa ở spec
  (Quyết định 4/11/2026) và các bước ở trên: (a) CRITICAL: lịch sử chạy theo ADR-0106 (Accepted) quyết 4 sửa
  27/10/2026, payload lưu che lúc ghi và che lại lúc đọc, không "giá trị sống" (R4.6, FS9); (b) CRITICAL: lược đồ công
  cụ không đệm theo `fls_version` mà không có công ty, dùng bộ đệm `(tenant_id, object_id, schema_version)` của
  custom-objects/03 và lọc sau nó (CLAUDE.md, cache keys); (c) một tên lỗi `field_hidden` (ADR-0106 (Accepted) sửa 4/11/2026), kiểm
  lúc chạy là của workflow-nodes/03; (d) luật người duyệt qua `reads_all` trên `payload.stamped_fields`, guard là của
  workflow-nodes/06, ticket này thêm bộ lọc ứng viên; (e) đối số đã render của chủ thể chỉ qua `payload_guards`; (f)
  cột `data` không trả nguyên; (g) tham số lọc do model đưa qua cùng bộ biên dịch (R4.8, FS14); (h) fixture một vai chỉ
  `obj.lead.read`. Nếu sai thì: ghi ở đây khi dựng và sửa spec.
- 2026-11-04 (agent): MEDIUM của gate, chưa sửa. (M1) Ca eval `prompt_injection` cho tham số lọc trên trường ẩn của
  công cụ đối tượng thuộc bộ eval của tools-and-skills/03 (CLAUDE.md, công cụ mới đi kèm eval); báo cho gate của nó.
  (M2) Người duyệt không với tới bản ghi được tham chiếu qua RLS: trang duyệt lấy giá trị sống dưới RLS của người xem nên
  thấy `Đã ẩn` hết; workflow-nodes/06 đã giữ ứng viên theo `effective_grants` ở workspace của lượt, chưa theo tầm tới
  bản ghi. (M3) Trường đã đóng dấu bị bỏ khỏi đối tượng: custom-objects từ chối bỏ trường đã phát hành
  (`field_removed`), nên không xảy ra ở W1.
- 2026-11-04 (agent): bảng cặp. Mọi ticket chạm cùng tệp (custom-objects/03, /04, tools-and-skills/03, workflow-nodes/03,
  /06, telemetry-and-audit/03) đều ở `Blocked by` của ticket này, nên có đường; không còn cặp nào. Thứ tự dựng: cuối
  cùng của area, sau mọi ticket ở `Blocked by`; trước marketing-pilot/04.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
