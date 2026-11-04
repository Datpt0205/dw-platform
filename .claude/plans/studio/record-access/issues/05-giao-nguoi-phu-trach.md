# 05 — Giao người phụ trách và đổi workspace sở hữu

Status: ready-for-agent
Blocked by: 03, 04, .claude/plans/studio/app-standards/issues/01-vo-loi-problem-json.md, .claude/plans/studio/app-standards/issues/02-khoa-chong-lap-gan-nguoi-goi.md, .claude/plans/studio/custom-objects/issues/03-record-service.md
Area: studio
Yêu cầu: R8.1, R8.2, R8.3, R8.4, R8.5, R8.6, R8.7, R8.8, R8.9, R8.10, R8.11, R8.12, RA24, RA25, RA26, RA28

## Mục tiêu

Trưởng kinh doanh, hay bước "Giao cho" của quy trình tiếp nhận, giao một lead của Marketing cho một nhân viên Sales
qua một hàm duy nhất được đổi người phụ trách, giữ workspace sở hữu trừ khi người giao chọn khác, có audit và outbox
trong cùng giao dịch (spec R8; ADR-0105 (Accepted) mục 2 và 3; DO-11 theo khuyến nghị (a), tạm).

## Việc cần làm

1. `AssignRecordService` trong `dw_studio`, một giao dịch mỗi lần giao, theo thứ tự (gate 4/11/2026 (b), (i)):
    - khóa hành động `obj.<api_name>.assign` của người gọi (tenant-rbac/04), thiếu → 403 `permission_denied` trước khi
      đọc bản ghi nào, như RecordService (custom-objects:R3.4);
    - đọc bản ghi qua adapter bản ghi bằng `SELECT ... FOR UPDATE` dưới RLS với ngữ cảnh actor của giao dịch: không
      thấy, đã xóa mềm, hay `object_id` khác đối tượng của `{api_name}` trên đường dẫn → 404 như id không tồn tại; dòng
      đọc được cho giá trị trước (người phụ trách, workspace sở hữu) mà audit cần, và `FOR UPDATE` xếp hàng hai lần giao
      đồng thời cùng bản ghi, nên lần sau kiểm trên trạng thái lần trước đã commit (gate, MEDIUM M1). Không kiểm thấy
      được nào chép policy SELECT vào hàm.
2. `studio.assign_record(p_record_id uuid, p_owner_kind text, p_owner_id uuid, p_workspace_id uuid, p_dry_run boolean)`:
   SECURITY DEFINER thuộc `dw_migrator`, `search_path` cố định, EXECUTE thu khỏi PUBLIC và cấp cho `dw_app`, không nhận
   tên bảng; tenant, chủ thể, loại actor và `app.boundary_id` lấy từ setting. Thứ tự kiểm, mỗi bước một SQLSTATE riêng
   mà adapter đổi ra mã lý do:
    - loại actor `user`, `agent` hay `workflow`, không thì `assign_not_permitted`; với `agent` và `workflow`, object
      trong `studio.acl_boundary_objects('assign')` của ticket 04, không thì `assign_not_permitted` (gate (c));
    - người gọi có tầm `assign` trên bản ghi: điều kiện là `reach_sql('assign')` mà module mẫu policy của ticket 03 dựng,
      chép vào thân hàm lúc viết revision như văn bản policy; test so thân hàm (`pg_proc.prosrc`) với văn bản module dựng,
      lệch là đỏ (không thì `assign_not_permitted`);
    - người nhận: không có dòng `platform.tenant_members` ở tenant đang gắn, ở bất kỳ trạng thái nào → 404 như id bản ghi
      không tồn tại, cùng mã và thông điệp cho một uuid không tồn tại lẫn người của tenant khác, và hàm không đọc dòng
      của tenant nào khác (gate (g); spec R8.6); có dòng mà không `active`, hay không giữ `read` trên object ở bất kỳ mức
      nào → `assign_target_out_of_reach`. Điều kiện người nhận là hàm SQL
      `studio.assign_recipient_ok(p_object_id, p_owner_id, p_workspace_id)` (STABLE, SECURITY DEFINER cùng chủ, cùng `search_path`, nhận id đối tượng chứ không
      id bản ghi nên không dò được bản ghi người gọi không thấy; điều nó cho biết, một thành viên có `read` trên một đối
      tượng không, là thông tin trong công ty; quyền `read` đọc từ `platform.effective_grants`, không từ sổ tầm, nên người
      nhận chưa mở Studio không bị từ chối oan; tài khoản dịch vụ là thành viên nên đủ điều kiện, còn việc loại nó khỏi
      vòng xoay là chính sách chọn ứng viên của Bước giao; không đòi người nhận là thành viên workspace sở hữu khi không
      đổi workspace, theo DO-11 (lượt xác nhận (h))), mà `studio.assign_record` gọi và Bước
      `data.object.assign` của workflow-nodes/04 gọi để lọc ứng viên, không bản sao (gate (e)). Người nhận có `read` ở
      bất kỳ mức nào thì thấy bản ghi mình phụ trách sau lần giao, vì nhánh `own` gồm mọi độ sâu từ Của tôi trở lên
      (ticket 02 bước 1);
    - khi `p_workspace_id` khác NULL: tầm `create` của người giao trên đúng cặp (object, workspace), tức object trong
      `studio.acl_objects('create', 'tenant')`, hay `access_key(object, p_workspace_id)` trong `studio.acl_keys('create')`
      hoặc `studio.acl_create_own_keys()` (ticket 02 bước 5), workspace chưa lưu trữ, và người nhận là thành viên của nó;
      không thì `assign_target_out_of_reach` (gate (f));
    - `p_owner_kind = 'team'` bị từ chối cho tới W2 với 422 `validation_failed`, `errors[].code`
      `owner_kind_not_supported`; route không có trường `owner_kind` nên luôn gửi `user`;
    - bản ghi thuộc một workspace đã lưu trữ mà không đổi workspace → `assign_target_out_of_reach`, vì workspace đã lưu
      trữ đóng với lần giao mới (glossary); `p_workspace_id` bằng workspace sở hữu hiện tại → coi như NULL; giao cho đúng
      người phụ trách hiện tại không đổi workspace → không ghi gì, trả kết quả hiện tại, không audit, không outbox
      (lượt xác nhận (i)).
      `p_dry_run` đúng thì chạy mọi kiểm trên rồi trả kết quả dự kiến (`version` cộng 1, người phụ trách và workspace mới)
      mà không UPDATE gì (gate (d)); sai thì cập nhật `owner_id`, `owner_kind`, `workspace_id` khi được chọn, tăng `version`
      của bản ghi, và trả `version`, `owner_id`, `workspace_id` mà không đọc lại qua RLS, nên người giao mất quyền thấy sau
      lần giao không làm giao dịch lùi.
3. `AssignRecordService` gọi hàm qua adapter bản ghi, rồi trong cùng giao dịch ghi audit `studio.record.assigned`
   (`object_id`, `record_id`, người phụ trách và workspace sở hữu trước, từ dòng của bước 1, và sau; `details.channel`
   `api` hay `workflow`, và `details.run_id`, `details.node_id` khi lần giao đến từ một Bước; không giá trị trường) và
   outbox `studio.record.assigned` (payload v1: cùng các id và `version`) vào `platform.outbox_events` (gate, MEDIUM M2;
   spec R8.7). Ở `simulate`, service chạy bước 1 rồi hàm với `p_dry_run` đúng, trả kết quả dự kiến hay đúng mã từ chối
   của lượt thật, không audit, không outbox, không dòng khóa; một `record_id` không có (như id mà một Bước `create` giả
   lập trả) → 404 như ở `live`, Bước đi `on_error` của nó (gate (d)).
4. Route `POST /api/v1/studio/objects/{api_name}/records/{record_id}/assign`: chống lặp bằng
   `idempotent(<khóa obj.<api_name>.assign theo tham số đường>, operation=...)` của app-standards/02
   (`apps/api/src/dw_api/dependencies/idempotency.py`), `Idempotency-Key` bắt buộc (thiếu → 422
   `idempotency_key_required`), và `idempotency.once(...)`: `PendingEffect` ghi dòng
   `platform.effect_keys` trong chính giao dịch giao, `reread` đọc lại bản ghi dưới quyền hiện tại của người gọi
   (app-standards:R2.16, R2.29). Gửi lại sau khi phản hồi đã lưu → phản hồi đã lưu, kể cả khi người giao không còn thấy
   bản ghi; gửi lại sau khi tiến trình chết giữa commit và lưu phản hồi → hiệu ứng đã có, đọc lại dưới quyền hiện tại,
   nên người giao không còn thấy bản ghi nhận 404 như app-standards:R2.29 định, không bao giờ một lần giao thứ hai (gate
   (a); spec R8.10). Thân `{"owner_id": "...", "workspace_id": "..."}`, `workspace_id` tùy chọn; 200 với `record_id`,
   `version`, `owner_id`, `workspace_id`; 403 `permission_denied`, 403 `assign_not_permitted`, 403
   `assign_target_out_of_reach`, 404, trong `details.reason_code` của lỗi; `make generate-contracts`. Route không đòi
   `If-Match`: nó vào danh sách miễn trừ đóng băng của app-standards:R3.12 với lý do "lệnh giao, hai lần giao đồng thời
   xếp hàng bằng `FOR UPDATE` và lần sau kiểm trên trạng thái đã commit; Bước giao không có ETag để gửi" (lượt xác nhận
   (j)).
5. Bước "Giao cho" của workflow-nodes gọi cùng `AssignRecordService` qua `RecordAssignPort`, Protocol mà
   workflow-engine/03 khai trong `dw_studio.workflows.ports` (H-30), nối ở gốc ghép; không đường nào khác đổi được người
   phụ trách vì `dw_app` không có UPDATE trên các cột đó (ticket 03).
6. Khóa của lần giao từ một Bước (R8.11, R8.12; V4.30): khi lời gọi qua `RecordAssignPort` mang khóa
   `wf:{run_id}:{node_id}:{iteration_path}`, `AssignRecordService` tra `studio.record_write_keys` của custom-objects/03
   trước bước 1 và trước khi đọc người nhận mới; có dòng của cùng chủ thể với cùng `record_id` thì trả `owner_kind`, `owner_id`,
   `workspace_id`, `version` đã lưu với `replayed: true` mà không gọi hàm, không audit, không outbox; dòng có
   `record_id` khác → 409 `idempotency_conflict` (gate, MEDIUM M3); không có thì gọi hàm, ghi audit, outbox và dòng khóa
   `op` `assign` trong cùng giao dịch; INSERT khóa vướng PK vì dòng của chủ thể khác → 409 `idempotency_conflict`; vướng
   PK vì dòng của cùng chủ thể (hai lần thử chạy cùng lúc) → giao dịch lùi và trả kết quả của lần thắng với
   `replayed: true`. Route HTTP không nhận khóa `wf:`; nó giữ `Idempotency-Key` gắn người gọi của bước 4. Ở `simulate`
   không gọi hàm ghi và không ghi dòng khóa.

## Tiêu chí chấp nhận

- [ ] R8.1 (RA26): người phụ trách có `read` và `assign` mức Của tôi giao lead của mình cho một nhân viên Sales → 200,
      người phụ trách mới, `version` tăng 1, dù sau lần giao người giao không còn thấy lead; thêm vào service một lần đọc
      lại kết quả qua RLS sau lần giao → test đỏ.
- [ ] R8.2: không gửi `workspace_id` → workspace sở hữu giữ nguyên Marketing.
- [ ] R8.3: gửi `workspace_id` của Sales khi người giao có tầm `create` trên Lead ở Sales và người nhận là thành viên
      Sales → workspace sở hữu thành Sales trong cùng giao dịch; người giao chỉ có `create` ở Sales trên Campaign →
      `assign_target_out_of_reach` (gate (f)).
- [ ] R8.4 (RA24): người thấy lead mà không có tầm `assign`, kể cả khi chỉ với tới qua `public_read_write` → 403
      `assign_not_permitted`, không cột nào đổi; người thiếu khóa `obj.mkt_lead.assign` → 403 `permission_denied`; gỡ
      kiểm `assign` trong hàm → test đỏ; thân hàm lệch văn bản `reach_sql('assign')` của module → test so văn bản đỏ.
- [ ] R8.4 (RA24): Bước giao của một quy trình có giới hạn dữ liệu không có `can_assign` trên Lead →
      `assign_not_permitted`, không cột nào đổi; giao dịch không gắn loại actor → 404; bỏ kiểm giới hạn khỏi hàm → test đỏ.
- [ ] R8.5 (RA24): người nhận không có `read` trên object, hay bị tạm khóa, hay `workspace_id` ngoài tầm `create` của
      người giao, hay người nhận không là thành viên workspace đích, hay workspace đích đã lưu trữ → 403
      `assign_target_out_of_reach`, không cột nào đổi.
- [ ] R8.6 (RA24): người nhận thuộc tenant B, và một uuid không tồn tại → cùng 404, cùng mã và thông điệp;
      bản ghi người gọi không thấy, bản ghi của tenant B, bản ghi đã xóa mềm, bản ghi của đối tượng khác `{api_name}` →
      404; không cột nào đổi.
- [ ] R8.7 (RA25): một lần giao → đúng một audit `studio.record.assigned` chỉ có id, `channel` và, từ một Bước, `run_id`,
      `node_id`; lỗi giả lập sau khi ghi audit → giao dịch lùi, 0 audit, người phụ trách cũ.
- [ ] R8.8 (RA25): một lần giao → đúng một dòng outbox `studio.record.assigned` cùng giao dịch; giao dịch lùi → 0 dòng
      outbox.
- [ ] R8.9 (RA26): người phụ trách cũ chỉ có `read` mức Của tôi SELECT bản ghi ở câu lệnh đầu tiên sau commit → 0 dòng.
- [ ] R8.10 (RA25): cùng người gọi gửi lại cùng `Idempotency-Key` → trả kết quả lần đầu, một audit, một outbox,
      `version` tăng một lần; tiến trình chết sau commit và trước khi lưu phản hồi, gửi lại → không lần giao thứ hai, một
      dòng `platform.effect_keys`; bỏ `PendingEffect` khỏi giao dịch giao → lần gửi lại giao lần hai, test đỏ; cùng khóa
      với `owner_id` khác → 409 `idempotency_conflict`.
- [ ] R8.7: hai lần giao đồng thời cùng bản ghi (hai giao dịch, đợi `pg_locks`) → lần sau thấy người phụ trách lần
      trước đã đặt, audit "trước" của nó đúng giá trị đó; bỏ `FOR UPDATE` → test đỏ.
- [ ] R8.1: ở `simulate`, giao cho người nhận hợp lệ → kết quả dự kiến, người phụ trách không đổi, 0 audit, 0 outbox;
      giao cho người không có `read` → `assign_target_out_of_reach` như ở `live`.
- [ ] R8.5: `studio.assign_recipient_ok` trả sai cho người nhận bị tạm khóa và đúng cho người nhận hợp lệ; hàm giao
      gọi đúng hàm đó (thay hàm bằng điều kiện khác → test của Bước giao ở workflow-nodes/04 và ở đây cùng đỏ).
- [ ] R8.11 (RA28): Bước giao qua `RecordAssignPort` với khóa `wf:` → một dòng `studio.record_write_keys` `op`
      `assign` mang người phụ trách mới, cùng giao dịch với lần giao, audit và outbox; lỗi giả lập sau khi ghi audit →
      giao dịch lùi, 0 dòng khóa; ghi dòng khóa trong giao dịch riêng → test đỏ.
- [ ] R8.12 (RA28): giết worker sau commit của lần giao và trước checkpoint, chạy lại cùng khóa khi người lâu nhất chưa
      nhận đã đổi → cùng người phụ trách với `replayed: true`, `version` tăng một lần, một audit, một outbox; gỡ bước tra
      khóa → lần chạy lại giao cho người kế tiếp trong vòng xoay, test đỏ; cùng khóa từ chủ thể khác → 409
      `idempotency_conflict`, không cột nào đổi; cùng khóa với `record_id` khác → 409.
- [ ] Xong: `make ci test-integration` xanh.

## Nguồn

- `apps/api/src/dw_api/dependencies/idempotency.py:217`; spec: R8.10.
- `db/migrations/sql/0001_platform_baseline.sql:304`; spec: R8.8.
- `db/migrations/sql/0012_partition_maintenance.sql:45-48`; spec: R8.1.
- `docs/adr/0104-tenant-roles-with-depth-and-one-effective-grants-owner.md:65-69`; spec: R8.4, R8.5.
- `docs/adr/0105-record-reach-is-decided-by-postgresql.md:67-76`; spec: R8.1, R8.2.
- `docs/adr/0108-one-error-envelope-and-caller-bound-idempotency.md:111-123`; spec: R8.11, R8.12 (V4.30); workflow-nodes:R6.5; custom-objects:R5.9, R5.11.

## Comments

- 2026-10-23 (agent): DO-11 theo khuyến nghị (a), tạm: lần giao giữ workspace sở hữu mặc định, người giao chọn khác
  được; người phụ trách được ở workspace khác (lead của Marketing, người phụ trách ở Sales).
- 2026-10-23 (agent): DO-11 (a) đã được Đạt xác nhận ngày 23/10/2026; thêm app-standards/01, /02 vào Blocked by vì route
  giao dùng problem+json và `Idempotency-Key` gắn người gọi; người dự phòng khi giao là của workflow-nodes (Q6).
- 2026-10-25 (agent): lượt h, theo V4.30 của Đạt (mục 10): nhận R8.11, R8.12 và RA28, khóa `wf:` của Bước giao ghi cùng giao dịch với lần giao và phát lại người đã giao (bước 6); Bước giao đi qua `RecordAssignPort` mà workflow-engine/03 khai (H-30, bước 5). Blocked by thêm custom-objects/03, ticket tạo `studio.record_write_keys`; cạnh ngoài bảng mục B, đã chạy g.py: `marketing-pilot/03` vẫn ở độ sâu 15, chuỗi dài nhất 18.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check và boundary walk, hai subagent, vì ticket thêm
  migration và route), đọc cùng `idempotency.py` và R2.16-R2.37 của app-standards: 0 CRITICAL, 8 HIGH, sửa theo khuyến
  nghị (Quyết định 4/11/2026 của spec): (a) `once` và khóa hiệu ứng trong giao dịch giao (R8.10); (b) `FOR UPDATE` dưới
  RLS trước hàm; (c) loại actor và `can_assign`; (d) `p_dry_run` cho `simulate`; (e) `assign_recipient_ok` dùng chung;
  (f) tầm tạo đích theo cặp; (g) người ngoài công ty → 404 như id không có (R8.5, R8.6); (i) khóa
  `obj.<api_name>.assign` và đối tượng của đường dẫn.
- 2026-11-04 (agent): MEDIUM, đã sửa: (M1) hai lần giao đồng thời; (M2) audit mang kênh và lượt (R8.7); (M3) khóa `wf:`
  với `record_id` khác → 409. MEDIUM để lại: (M4) `simulate` của Bước tạo rồi giao luôn 404 ở Bước giao vì id giả lập
  không có; Bước đi `on_error`; (M5) `assign_recipient_ok` cho một thành viên biết thành viên khác có `read` trên một đối
  tượng không, thông tin trong công ty.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận: 0 CRITICAL, 3 HIGH, sửa: (h) chi tiết của `assign_recipient_ok` (definer, nhận id đối
  tượng, `read` từ `platform.effective_grants`, không đòi thành viên workspace sở hữu khi không đổi workspace, tài khoản
  dịch vụ đủ điều kiện); (i) workspace đã lưu trữ, giao không đổi gì, `team`; (j) `Idempotency-Key` bắt buộc, miễn
  `If-Match` có lý do. Sửa của lượt này không có người đọc mới: nhận rủi ro (agent, theo ủy quyền 31/10/2026). Nếu sai thì: ghi ở đây khi dựng. Thứ tự
  dựng: sau 03, 04, custom-objects/03, app-standards/01, /02 (đã xong); trước custom-objects/05, workflow-nodes/04.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
