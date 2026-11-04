# 06 — tool.call qua ToolExecutor và human.approval với quyền bắt buộc, khóa tham số

Status: ready-for-agent
Blocked by: 03, .claude/plans/studio/workflow-engine/issues/05-cho-nguoi-va-ghim-phien-ban.md, .claude/plans/studio/tools-and-skills/issues/02-toolset-va-cong-cu-ghim.md, .claude/plans/studio/compliance-pdpl/issues/04-san-gui-tin-marketing.md, .claude/plans/studio/tenant-config/issues/05-lien-ket-va-phien-ban-cau-hinh.md, .claude/plans/studio/agent-lifecycle/issues/03-hop-dong-vong-doi-va-niem-phong.md
Area: studio
Yêu cầu: R8.1, R8.2, R8.3, R8.4, R9.1, R9.2, R9.3, R9.5, R9.6, R9.7, R9.8, R9.9, R9.10, R9.11, R9.12, R9.13, R9.14, R9.15, R9.16, R9.17, WN6, WN7, WN8, WN9, WN11, WN17, WN18, WN20, WN21, WN27

## Mục tiêu

Bước `tool.call` đi qua `ToolExecutor` với khoá chống lặp; Bước phê duyệt là cổng do máy chủ thực thi,
với quyền bắt buộc, người duyệt khác người tạo lượt, tham số đã duyệt đúng là tham số được gửi, và trong lượt
mô phỏng thì đi theo quyết định giả lập mà không chờ người, còn dòng giao và dòng phê duyệt của Bước không trỏ được
tới lượt chạy hay yêu cầu của công ty khác; mỗi kết quả của phê duyệt là một làn Bước, làn `approved` chỉ chạy khi
quyết định là duyệt, và Bước phê duyệt không bao giờ đi tiếp qua lỗi như đã có quyết định
(workflow-nodes R8.1, R8.2, R8.3, R8.4, R9.1, R9.2, R9.3, R9.5, R9.6, R9.7, R9.8, R9.9, R9.10, R9.11, R9.12, R9.13,
R9.14, R9.15, R9.16, R9.17, WN6, WN7, WN8, WN9, WN11, WN17, WN18, WN20, WN21, WN27). Hết hạn riêng của Bước phê duyệt
(R9.4, WN10) ở W2; phê duyệt đang mở của một lượt bị hủy, kể cả lượt quá hạn chót của workflow-engine, bị hủy cùng
lượt (R9.15). Quy tắc `all` (mọi người được giao phải duyệt) là bậc B, ở ticket 07.

## Việc cần làm

0. **Hai loại của Studio, `tool.call@2` và `human.approval@2`, cạnh `@1` của wf-lite** (ticket 02 bước 1; dòng Quyết định
   4/11/2026 của spec).
    - `tool.call@1` và `human.approval@1` của wf-lite mang `decision_class`, `proposal`, `locked_fields` và cổng tự chủ
      của Digital Worker (wf-lite R6.17, `DecisionCall` của `ToolExecutor`). Bước của Studio mang `required_scope`,
      người được giao, chủ thể khóa bằng mã băm và quyết định giả lập. Hai hợp đồng cấu hình khác nhau, nên Studio đăng
      ký `tool.call@2` và `human.approval@2` trong `studio_node_types` của ticket 03; gói giữ nguyên `@1`.
    - `STUDIO_RULES.refused_types` (ticket 03) thêm `tool.call@1` và `human.approval@1` → `wf.unknown_type`; danh mục
      bỏ hai loại đó. Trong spec, R9, R10.4, R12 và các kiểm soát nói `human.approval@1` nay đọc là `human.approval@2`.
    - `human.approval@2`: `block` `choice`, Nhánh ra `approved` ("Duyệt") và `rejected` ("Từ chối"), `ends_run` và
      `exits_loop` sai, `opens_wait` đúng (khai cùng trường khi workflow-engine/06 thêm nó, hay ngay nếu trường đã có),
      `dependencies` `()`, `side_effect_level` `internal`, Khi lỗi chỉ `fail`, `route` (R9.17).
    - `tool.call@2`: `block` `none`, cả ba tính chất vị trí sai, `dependencies` `()` (công cụ ghim qua bộ công cụ của
      tools-and-skills/02), `side_effect_level` của công cụ, Khi lỗi `fail`, `continue`, `route`.
1. `tool.call@2`: cấu hình `{tool, arguments}`, `tool` là `name@version` ghim lúc gửi kiểm định, `arguments` là đích
   `json` của bộ dựng mẫu (ticket 02). Gọi `ToolExecutor.execute` với đúng khoá mà wrapper nút dẫn (workflow-engine:R4.5),
   không tự dựng khoá.
    - Thiếu quyền → `permission_denied` từ executor; sàn gửi tin ở đường messaging của executor (compliance-pdpl, bước
      `send_floor` của `build_tool_executor_steps`), không ở bước.
    - Mức bảo đảm của lời gọi là của executor và hợp đồng giao nhận của Hành động (V4.30): Bước không tự thử lại hay gửi
      lại; hai lời gọi cùng khoá không cùng gửi khi claim còn hạn (R8.2); lời gọi không rõ kết quả làm theo `on_unknown`
      của Hành động, ở W1 chỉ là `review` (H-5), nên lượt đỗ ở điểm chờ `outcome_review` của workflow-engine/08 và không
      chạy làn lỗi của Bước, việc của wrapper nút (workflow-engine/03).
    - Luật sàn HITL (wf-lite R4) trên đường Studio: một `tool.call@2` mà công cụ có tác động `external` hay `critical`,
      hay mà sàn của loại hoặc chính sách duyệt của công cụ (ADR-0116 (Accepted) quyết 3) đòi một người, phải là chủ thể
      của một `human.approval@2` và là Bước đầu tiên trong làn `approved` của nó, không thì lần gửi kiểm định trả
      `wf.hitl_gate_missing` (mã wf-lite đã có). Vì vậy `tool.call@2` không bao giờ mở điểm chờ: chính sách duyệt của
      công cụ được thỏa bằng phê duyệt của Bước, executor nhận `approved=True` chỉ khi mã băm chủ thể khớp (bước 3).
      Executor vẫn đòi duyệt lúc chạy (vd. lượt đã nhiễm dữ liệu ngoài) thì trả `approval_missing`, Bước lỗi theo Khi
      lỗi, không gì được gửi.
2. **Bảng** `studio.step_assignments` và `studio.step_approvals` (mục Dữ liệu của spec):
    - chung: `tenant_id`, `workspace_id`, `run_id`, `node_id`, `interrupt_id text NOT NULL`, `created_at timestamptz`; FK
      `(tenant_id, run_id, interrupt_id)` tới `platform.run_waits (tenant_id, run_id, interrupt_id)` của
      workflow-engine/05 `ON DELETE CASCADE`, chỉ mục `(tenant_id, run_id, interrupt_id)`. Mỗi điểm chờ một lần giao, nên
      Bước phê duyệt trong thân vòng lặp có giao của riêng từng vòng;
    - `step_assignments`: `assignee_kind` CHECK (`user`) không DEFAULT ở W1, `assignee_id`, UNIQUE
      `(tenant_id, run_id, interrupt_id, assignee_id)`; `run_id` FK ghép `(tenant_id, run_id)` tới
      `platform.worker_runs (tenant_id, id)` (`uq_worker_runs_tenant_id_id` của workflow-engine/02) `ON DELETE CASCADE`.
      Không cột `required_scope`: tem ở `platform.approval_requests.required_scope` là chủ duy nhất
      (ADR-0004 (Accepted));
    - `step_approvals`: `approval_request_id`, `subject_node_id`, `subject_hash`, CHECK `ck_step_approvals_subject_hash`
      (`subject_node_id` NULL khi và chỉ khi `subject_hash` NULL); FK ghép `(tenant_id, workspace_id,
approval_request_id)` tới `platform.approval_requests (tenant_id, workspace_id, id)` qua
      `uq_approval_requests_tenant_id_workspace_id_id` đã có, nên ticket này không sửa `platform.approval_requests`,
      `ON DELETE CASCADE`, chỉ mục `(tenant_id, workspace_id, approval_request_id)`; UNIQUE
      `(tenant_id, run_id, interrupt_id)`, một yêu cầu mỗi điểm chờ với quy tắc `any` (ticket 07 thay nó);
    - RLS bật và FORCE theo policy workspace của CLAUDE.md; `updated_at` do trigger giữ, nhường giá trị câu lệnh nêu.
    - Migration sinh bằng `alembic revision -m "..."`, id hex ngẫu nhiên. Đáp ứng `StepWaitLookupPort` mà
      workflow-engine/05 khai: từ id yêu cầu trả `(run_id, interrupt_id)` của dòng `step_approvals`, nối ở composition
      root.
3. **`human.approval@2` ở chế độ `live`.**
    - Cấu hình: `required_scope` bắt buộc; `assignees` tùy chọn, danh sách id người hay một Biểu thức `x-dw-cel` kiểu
      `list[string]`; `subject` tùy chọn, id của `tool.call@2` là Bước đầu tiên của làn `approved`; `show_fields` tùy
      chọn, danh sách `<object>.<field>`. Cấu hình nêu nhóm → schema từ chối (nhóm ở W2).
    - Mở yêu cầu `approval_type` đúng bằng `studio.step.approval` (tiền tố nghiêm `studio.step.`), một dòng `|=` ở
      composition root của API và worker, không sửa dòng của ticket khác (agent-lifecycle/04 thêm `studio.publish.` cùng
      chỗ; `apps/api/src/dw_api/bootstrap/runtime.py:343`); workflow-engine/05 giữ dòng chờ và handler theo tiền tố.
    - Ứng viên tính lúc mở, từ `effective_grants` của tenant-rbac tại workspace của lượt chạy: người giữ cả
      `required_scope` lẫn `approvals.decide` (ADR-0004 (Accepted); ADR-0104 (Accepted) quyết 11), thu hẹp theo
      `assignees` khi có, bỏ người tạo lượt chạy, chủ thể chạy và tài khoản dịch vụ. `requested_by` của yêu cầu là
      `requested_by` của lượt chạy, nên luật tiền tố nghiêm trả 409 cho người đó; chủ thể chạy, khi là người khác, bị
      loại ở ảnh chụp ứng viên và nhận 403.
      Biểu thức `assignees` lỗi hay vượt ngân sách → Bước lỗi `expression_error` theo Khi lỗi, không bao giờ rơi về "mọi
      người giữ scope"; id không qua kiểm ứng viên bị bỏ (quy tắc `any`). Không còn ai → `no_approver`, đi làn lỗi khi Khi
      lỗi là `route`, lượt `failed` khi là `fail`, không yêu cầu nào mở (R9.13; ADR-0112 (Accepted) quyết 7).
    - Một giao dịch, dưới khoá mà wrapper nút dẫn: dòng `platform.run_waits` `open` mà đường chờ của workflow-engine/05
      ghi và trả `interrupt_id`, một dòng `platform.approval_requests`, một dòng `step_approvals`, một dòng
      `step_assignments` mỗi ứng viên (ảnh chụp lúc mở; người được cấp scope sau đó không quyết được). `interrupt_id` tất
      định theo `(node_id, iteration_path)`, nên Bước chạy lại sau khi worker chết gặp đúng dòng chờ và dòng
      `step_approvals` của nó và không mở lần hai (UNIQUE ở bước 2). Việc mở nằm ở node trước node chờ, vì
      `interrupt()` là câu đầu của node chờ (ADR-0112 (Accepted) quyết 4).
    - Đóng dấu vào yêu cầu tên mọi Trường trang duyệt hiển thị (R9.7), ở `payload.stamped_fields`, dạng
      `<object>.<field>`: `show_fields` cộng các Trường mà `arguments` của chủ thể tham chiếu. Không có AST, nên Trường
      được tham chiếu tìm bằng cơ chế của ticket 03 bước 2: `check` lại nguồn trong môi trường bỏ từng Trường của các kiểu
      bản ghi, Trường nào khi bỏ đi làm `undefined_field` nêu nó là Trường được tham chiếu (cache theo khóa của ticket
      01).
    - Mã băm chủ thể: lúc mở, Bước render `arguments` của `subject` trong môi trường của vị trí chủ thể, lưu đối số đã
      render ở `payload.subject.arguments` (trang duyệt hiện nguyên văn) và `content_hash` của nó trong `subject_hash`.
    - Đọc `payload`: một mục `payload_guards['studio.step.approval']` ở composition root, cạnh `decision_guards`, cùng hàm
      điều kiện (có dòng giao, giữ scope, đọc được mọi Trường đóng dấu); route đọc phê duyệt hỏi nó trước khi trả
      `payload`, và người giữ tem mà không qua nó thấy yêu cầu không có `payload` (field-security:R4.4; CLAUDE.md, field
      security applies).
    - Một mục `decision_guards['studio.step.approval']` qua guard async `ApprovalDecisionGuard` của tenant-config/05 trả
      403 `permission_denied` cho người không có dòng `step_assignments` của điểm chờ đó, hay không còn giữ
      `required_scope`, hay không đọc được một Trường đã đóng dấu (R9.8, luật của field-security:R4.5). Người tạo lượt
      chạy thiếu `required_scope` nhận 403 ở kiểm tem; mọi người khác không giữ tem nhận 404 vì không thấy yêu cầu;
      người tạo lượt chạy giữ scope nhận 409 `conflict` với `details.reason_code` `second_person_required` ở luật tiền
      tố nghiêm, mã mà `_enforce_strict_rules` của tenant-config/05 đặt cho mọi loại phê duyệt (V4.P9;
      ADR-0104 (Accepted) quyết 11; ADR-0004 (Accepted)).
    - Lúc lượt `live` tiếp tục sau quyết định, Bước chạy làn của quyết định đó và không chạy làn kia (R9.16).
    - Yêu cầu `studio.step.approval` không rút được ở W1: lệnh rút của người yêu cầu (ADR-0004 (Accepted)) trả 409
      `conflict` với `details.reason_code` `step_approval_not_withdrawable` qua một mục ở composition root cạnh
      `decision_guards`, vì rút một yêu cầu mà không đóng điểm chờ để lượt kẹt `open` tới hạn chót; dừng một lượt là
      route hủy lượt của W2. Yêu cầu chỉ rời `pending` bằng một quyết định hay trigger hủy của bước 6.
    - Lúc chủ thể chạy (Bước đầu của làn `approved`) ở `live`: `tool.call@2` render lại `arguments`, so `content_hash`
      với `subject_hash`; khác → `subject_changed`, không gửi; khớp → `ToolExecutor.execute(..., approved=True)` với đúng
      đối số đã duyệt (R9.3); không có dòng `step_approvals` của điểm chờ → `approval_missing`, không gửi. Ở chế độ khác
      `live` không có yêu cầu nào để so: chủ thể gọi executor với `approved=False`, và bước `run_mode` của executor, đứng
      trước bước `approval` trong `build_tool_executor_steps`, trả mẫu giả lập (tenant-config:R5.6).
4. **Kiểm khi gửi kiểm định.**
    - `subject` phải là Bước đầu tiên của làn `approved`, và `arguments` của nó chỉ tham chiếu Bước trội Bước phê duyệt,
      không thì `wf.unapproved_input` (mã wf-lite đã có): chen một Bước giữa phê duyệt và chủ thể, hay cho chủ thể đọc
      đầu ra tính sau khi duyệt, đều bị từ chối.
    - Kiểm theo loại `workflow` (R9.5), tính tại workspace sở hữu của quy trình, với "người chạy" là người gửi kiểm định
      tới khi điểm gắn run-as vào tài liệu (như ticket 03 bước 2), và `assignees` tĩnh áp khi có: ngoài người chạy của
      lượt không ai giữ `required_scope` và `approvals.decide` → lệnh gửi kiểm định trả
      422 với `details.reason_code` `no_second_approver` và phiên bản ở Nháp; đăng ký vào bảng kiểm theo loại mà
      agent-lifecycle/03 khai (agent-lifecycle:R2.7), ở composition root; không có khóa `studio.workflows.publish`.
5. **`human.approval@2` ở mọi chế độ khác `live`** (N2; ADR-0112 (Accepted) quyết 7): đọc quyết định giả lập của chính
   Bước từ đầu vào của lượt mô phỏng (`simulated_decisions[node_id]`, workflow-triggers:R2.7) hay từ Câu kiểm định của
   Cổng chất lượng (agent-lifecycle:R4.7); đi Nhánh ra của quyết định đó; không mở yêu cầu phê duyệt, không ghi dòng chờ;
   audit `studio.step.approval.simulated` với `details.run_mode`, `details.decision` và nguồn, trong cùng giao dịch ghi
   kết quả của Bước (R9.9, R9.10). Không có quyết định cho Bước, hay giá trị khác `approved` và `rejected` → lượt chạy
   `failed` với `simulated_decision_missing` (R9.12). Ở `live`, Bước bỏ qua mọi quyết định giả lập trong đầu vào và mở
   yêu cầu thật (R9.11).
6. **Huỷ cùng lượt** (R9.15): huỷ lượt chạy theo bất kỳ đường nào, kể cả Tắt khẩn và quá hạn chót (`deadline_exceeded`,
   workflow-engine:R5.23), huỷ phê duyệt đang mở trong cùng giao dịch: một trigger AFTER UPDATE OF `status` trên
   `platform.run_waits` nghe dòng chờ sang `cancelled`, việc mà trigger của workflow-engine/05 làm khi lượt chạy sang
   `cancelled` (workflow-engine:R6.13), và đặt yêu cầu `pending` nối qua `studio.step_approvals` sang `cancelled` (giá
   trị đã có trong CHECK trạng thái). Trigger chạy với quyền của người gọi (không SECURITY DEFINER), trong ngữ cảnh
   tenant mà mọi đường hủy đặt cho giao dịch của nó (lane reaper của workflow-engine/04 đặt `app.tenant_id` từng
   tenant), nên một đường hủy không đặt ngữ cảnh làm test R9.15 đỏ thay vì lặng lẽ không hủy gì. Bộ
   trả phiên bản chủ thể cho mã quyết định Zalo không đăng ký ở W1 (cùng nhắc, chuyển cấp và hết hạn ở W2), nên loại
   `studio.step.` quyết trên web.
7. **`effect_door`** (workflow-engine/03; bảng ở mục Trong phạm vi của spec, chủ duy nhất): `tool.call@2` khai `tool`, `human.approval@2` khai không cửa; thiếu trường thì sổ từ chối đăng ký, và `incident` của `allowed_on_error` do luật của workflow-engine/07 suy từ trường này, loại không tự khai.

## Tiêu chí chấp nhận

- [ ] R8.1: `tool.call@2` gọi `ToolExecutor.execute` với đúng khoá mà wrapper nút dẫn (workflow-engine:R4.5) và phiên
      bản công cụ đã ghim lúc gửi kiểm định. Tài liệu Studio dùng `tool.call@1` hay `human.approval@1` →
      `wf.unknown_type`; gói `lead_care@1.0.0` vẫn nạp.
- [ ] R8.1: `tool.call@2` gọi `email.send` (tác động `external`) mà không là chủ thể của một `human.approval@2` →
      `wf.hitl_gate_missing`, không niêm phong; gỡ luật sàn trên đường Studio → test đỏ.
- [ ] R8.2 (WN6): hai lần chạy song song cùng khoá do wrapper nút dẫn, lần sau trong lúc claim của lần đầu còn hạn →
      nhà cung cấp giả nhận đúng một lời gọi; cho Bước tự dựng khoá khác → hai lời gọi, test đỏ.
- [ ] R8.3 (WN7): người chạy thiếu quyền công cụ → `permission_denied` từ executor, không từ bước.
- [ ] R8.4 (WN7): `tool.call@2` `email.send` của `smtp@1.0.0` tới địa chỉ chưa đồng ý → `blocked:no_consent`; gọi thẳng
      công cụ (bỏ qua bước) cũng bị chặn; gỡ sàn gửi khỏi executor → test đỏ.
- [ ] R9.1: Bước phê duyệt ở `live` mở đúng `approval_type` `studio.step.approval` với `required_scope` bắt buộc; cấu
      hình thu hẹp theo nhóm → schema từ chối; INSERT `assignee_kind = 'team'` → CHECK từ chối.
- [ ] R9.1: worker chết sau khi giao dịch mở yêu cầu commit mà trước checkpoint, rồi Bước chạy lại → vẫn đúng một dòng
      `platform.approval_requests` và một dòng `step_approvals` cho điểm chờ; bỏ UNIQUE `(tenant_id, run_id,
interrupt_id)` → hai yêu cầu, test đỏ.
- [ ] R9.2 (WN8): người giữ `required_scope` mà không có dòng `step_assignments` của điểm chờ → 403 qua
      `decision_guards`; Bước không khai `assignees`, hai người giữ scope → cả hai có dòng, một người quyết được; người
      được cấp scope sau lúc mở → 403; người tạo lượt chạy thiếu `required_scope` → 403; một người khác không giữ tem
      quyết hay đọc yêu cầu → 404; người của công ty khác quyết với id yêu cầu này → 404 giống hệt id không có; gỡ guard
      → test đỏ.
- [ ] R9.6 (WN8): nhân viên Sales tạo lượt chạy và giữ `required_scope` tự duyệt → 409 `conflict` với
      `details.reason_code` `second_person_required`; bỏ `studio.step.` khỏi tiền tố nghiêm → test đỏ.
- [ ] R9.13 (WN8): người được giao duy nhất giữ `required_scope` rời công ty sau khi phát hành, rồi một lượt `live` tới
      Bước phê duyệt khai Khi lỗi `route` → làn lỗi chạy với `no_approver`, không dòng `platform.approval_requests`
      nào; cùng tài liệu với Khi lỗi `fail` → lượt chạy `failed` với `no_approver`; Biểu thức `assignees` lỗi → Bước lỗi
      `expression_error`, không yêu cầu nào mở; gỡ kiểm ứng viên lúc mở → yêu cầu mở mà không ai duyệt được và lượt chờ
      tới hạn chót, test đỏ.
- [ ] R9.16 (WN27): lượt `live`, quyết định `rejected` → làn `rejected` chạy, `tool.call@2` trong làn `approved` có 0
      lời gọi; quyết định `approved` → làn `approved` chạy, làn `rejected` không chạy; đảo ánh xạ từ quyết định sang
      làn → test đỏ.
- [ ] R9.17 (WN11): Bước phê duyệt khai Khi lỗi `continue` → `wf.config_invalid`; `fail` và `route` → nhận; gỡ tập Khi
      lỗi cho phép khỏi mục `human.approval@2` → `continue` qua, test đỏ.
- [ ] R9.7: yêu cầu phê duyệt bước mang ở `payload.stamped_fields` danh sách `<object>.<field>` mà `arguments` của chủ
      thể tham chiếu cùng `show_fields`; `arguments` nêu `lead.phone` → `lead.phone` có trong danh sách; người giữ tem
      không đọc được `phone` đọc yêu cầu → không có `payload`.
- [ ] R9.8 (WN17): người được giao không đọc được `phone` đã đóng dấu quyết → 403, yêu cầu vẫn `pending`; gỡ điều kiện
      đọc trường khỏi guard → test đỏ.
- [ ] R9.3 (WN9): chen một bước giữa Bước phê duyệt và chủ thể, hay cho `arguments` của chủ thể tham chiếu một Bước
      đứng sau Bước phê duyệt → `wf.unapproved_input`, không niêm phong. Lúc chạy, đối số render lại khác đối số đã duyệt
      → `subject_changed`, nhà cung cấp giả nhận 0 lời gọi; khớp → đúng một lời gọi với `approved=True`; cho chủ thể
      gửi mà không so mã băm → test đỏ. Ở `simulate` với quyết định `approved`, chủ thể chạy, executor trả mẫu giả lập,
      Bước không lỗi.
- [ ] R9.5 (WN8): chỉ người chạy giữ `required_scope` → lệnh gửi kiểm định của agent-lifecycle trả 422
      `no_second_approver`, phiên bản ở Nháp; gỡ đăng ký kiểm → test đỏ.
- [ ] R9.15 (WN21): Tắt khẩn một lượt đang chờ ở Bước phê duyệt → yêu cầu `studio.step.` của nó `cancelled` trong cùng
      giao dịch; lượt chờ bị reaper kết thúc vì `deadline_exceeded` → như vậy, người được giao quyết sau đó bị từ chối,
      yêu cầu vẫn `cancelled`; gỡ trigger hủy yêu cầu → yêu cầu còn `pending`, test đỏ.
- [ ] R9.9: lượt `simulate` với quyết định giả lập `rejected` cho Bước phê duyệt → Nhánh ra từ chối chạy, không dòng
      `platform.approval_requests` hay `platform.run_waits` nào, lượt chạy không chờ; quyết định `approved` → Nhánh ra
      duyệt chạy.
- [ ] R9.10: mỗi quyết định giả lập dùng → đúng một audit `studio.step.approval.simulated` có `details.run_mode`,
      `details.decision` và nguồn.
- [ ] R9.11 (WN18): lượt `live` có `simulated_decisions` mang `approved` trong đầu vào → một yêu cầu phê duyệt
      `studio.step.approval` thật được mở và lượt chạy chờ; cho Bước đọc quyết định giả lập ở `live` → test đỏ.
- [ ] R9.12 (WN18): lượt `simulate` thiếu quyết định cho một Bước phê duyệt, hay mang giá trị `approve` → lượt chạy
      `failed` với `simulated_decision_missing`, Nhánh ra duyệt không chạy; coi thiếu là đã duyệt → test đỏ.
- [ ] R9.1: `StepWaitLookupPort` trả đúng `(run_id, interrupt_id)` cho id yêu cầu; dòng chờ của workflow-engine bị xóa
      theo lượt chạy thì dòng `step_approvals` và `step_assignments` đi theo CASCADE.
- [ ] R9.14 (WN20): `dw_app` gắn tenant A chèn dòng `step_approvals` mang `approval_request_id` của một yêu cầu tenant
      B, hay dòng `step_assignments` mang `run_id` của một lượt chạy tenant B → lỗi FK, không dòng nào được ghi; đổi
      một trong hai FK về FK một cột → ca của nó qua, test đỏ. `test_rls_coverage.py`, `test_privileges.py` và
      `test_offboarding_coverage.py` xanh với hai bảng mới.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/workflows/test_tool_call_node.py packages/python/dw_studio/tests/workflows/test_human_approval_node.py && make test-integration` xanh.

## Nguồn

- `packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:217-235`; spec: R9.1
  (`approval_requests` thiếu cột giao, hạn, chuyển cấp).
- `db/migrations/versions/e399be8c0a2d_platform_approval_view_receipts_and_.py:127-129`; spec: Dữ liệu
  (`uq_approval_requests_tenant_id_workspace_id_id`, đích của FK ghép của `step_approvals`).
- `apps/api/src/dw_api/bootstrap/runtime.py:343-345`; spec: R9.2 (`strict_approval_prefixes`,
  `decision_guards`).
- `apps/api/src/dw_api/bootstrap/wiring.py:314`; spec: R9.4 (mã Zalo chỉ cho loại có người trả lời).
- ADR-0112 (Accepted) quyết 7; spec: R9.

## Comments

- 2026-10-23 (agent): theo phiếu 23/10/2026: hết hạn phê duyệt sang W2 (DO-31); bảng mã từ chối người quyết ở ADR-0004 (Accepted) tách R9.2 (403) và R9.6 (409); người duyệt phải đọc được Trường đóng dấu qua guard async (DO-36), nên ticket chờ tenant-config/05; khóa phát hành chung, R9.5 là kiểm đăng ký qua Protocol; chờ compliance-pdpl/04 và test WN7 dùng `email.send` của `smtp@1.0.0` (DO-48.1).
- 2026-10-24 (agent): theo quyết định của Đạt ngày 24/10/2026: bảng ba mã ở ADR-0104 (Accepted) quyết 11, người khác không giữ tem nhận 404 (R9.2); R9.5 là kiểm lúc gửi kiểm định trả 422 `no_second_approver`, ticket chờ agent-lifecycle/03; khoá chống lặp của workflow-engine:R4.5; W1 không giao theo nhóm; `step_approvals` là chủ liên kết tới yêu cầu và đáp ứng `StepWaitLookupPort`; Bước phê duyệt ở `simulate` theo quyết định giả lập (N2: R9.9-R9.12, WN18).
- 2026-10-24 (agent): vòng sửa thứ tư: luật tiền tố nghiêm trả 409 với `second_person_required` do tenant-config/05 đặt (V4.P9, agent tạm); lúc mở phê duyệt không còn ứng viên thì `no_approver` (R9.13, phát hiện F về ADR-0112 (Accepted) và R9.5); từ vựng `approved`, `rejected` của R9.9 là chủ cho route `test-runs` và Câu kiểm định.
- 2026-10-24 (agent): lượt c của vòng 4: `step_assignments.run_id` thành FK ghép tới `uq_worker_runs_tenant_id_id`, và `step_approvals.approval_request_id` thành FK ghép `(tenant_id, workspace_id, approval_request_id)` qua `uq_approval_requests_tenant_id_workspace_id_id` đã có, nên ticket này không thêm UNIQUE nào lên `platform.approval_requests`; R9.1 thêm ca chéo tenant (CLAUDE.md, Tenancy and authorization).
- 2026-10-24 (agent): kiểm lượt c của vòng 4: dòng `Xong:` thêm `make test-integration`, vì ca chéo tenant và ca CASCADE của R9.1 cần PostgreSQL thật, mà hai tệp test bước không chạy (failure-modes #1: ai chạy test này).
- 2026-10-24 (agent): lượt d của vòng 4: dòng Comments của lượt c thôi dẫn mã mục của lượt; ca chéo tenant của hai FK ghép rời tiêu chí R9.1 sang R9.14 (WN20), kèm test đột biến đổi mỗi FK về một cột (CLAUDE.md, Tenancy and authorization; failure-modes #3), vẫn chạy trong `make test-integration` của dòng `Xong:`, và Mục tiêu nêu R9.14, WN20 cạnh các mã khác; bước 2 nêu chỉ mục của hai FK (CLAUDE.md, Data model rules). Không thêm cạnh.
- 2026-10-24 (agent): theo V4.14 của Đạt: lượt chạy có hạn chót ở W1, nên bước 6 thôi ghi "W1 phê duyệt chờ không hạn" và
  việc huỷ phê duyệt đang mở cùng lượt thành tiêu chí R9.15 (WN21), có ca quá hạn chót, thay dòng tiêu chí cũ mang mã R9.2;
  tiêu chí R9.13 thôi nói "lượt chờ mãi". Không thêm cạnh: ticket này đã chờ workflow-engine/05, nơi trigger hủy dòng chờ
  ra đời, và workflow-engine/04, nơi reaper kết thúc lượt quá hạn, qua ticket đó.
- 2026-10-24 (agent): theo V4.24 của Đạt: hai kết quả của phê duyệt là hai làn Bước, nên tiêu chí R9.16 (WN27) thử
  làn `approved` chỉ chạy khi quyết định là duyệt; làn lỗi chỉ có khi Khi lỗi là `route`, nên R9.13 nói `no_approver`
  đi làn lỗi với `route` và làm lượt `failed` với `fail` thay "không nối Nhánh ra đó", và schema chỉ nhận `fail` hay
  `route` (R9.17, WN11; agent, tạm). Quy tắc `all` của V4.26 ở ticket 07, chờ ticket này, nên đường găng YC94 không
  chờ bậc B. Không thêm cạnh.
- 2026-10-25 (agent): `human.approval@1` khai `opens_wait` đúng và `tool.call@1` khai cả ba tính chất vị trí sai, theo
  trường bắt buộc của ticket 02 (dòng Quyết định 25/10/2026 của spec), để `wf.wait_in_parallel` của workflow-engine/06
  nhận ra Bước phê duyệt mà không đọc tên loại. Không thêm cạnh.
- 2026-10-25 (agent): lượt h, theo V4.30 của Đạt: R8.2 nói mức bảo đảm đồng thời (hai lời gọi cùng khoá không cùng gửi
  khi claim còn hạn) thay "tác động ngoài xảy ra đúng một lần", và bước 1 nói lời gọi không rõ kết quả là của wrapper
  nút và điểm chờ `outcome_review` của workflow-engine/08, không của Bước. Không thêm cạnh: R8.2 thử executor giành lượt
  của runtime-hardening/01, mà ticket này đã chờ qua tools-and-skills/02.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check cùng boundary walk; ticket
  có migration). Lượt đầu: 0 CRITICAL, 12 HIGH, đều sửa ở ticket này và spec (Quyết định 4/11/2026; Dữ liệu):
    - `tool.call@1`, `human.approval@1` của wf-lite (`decision_class`, `proposal`, cổng của Digital Worker) khác hẳn
      Bước của Studio (MEDIUM (b) của gate ticket 02): nay `tool.call@2`, `human.approval@2`.
    - Chủ thể là Bước nào, băm gì, đối số đã duyệt lưu ở đâu, gửi đối số đã lưu hay render lại: nay `subject` là Bước
      đầu của làn `approved`, đối số render lúc mở nằm trong `payload`, chủ thể render lại và so mã băm.
    - Luật "chen bước" không nêu phạm vi hay mã: nay `wf.unapproved_input` của wf-lite.
    - Quan hệ với chính sách duyệt của executor: nay luật sàn HITL `wf.hitl_gate_missing` trên đường Studio, và
      `approved=True` chỉ khi mã băm khớp, nên `tool.call@2` không mở điểm chờ.
    - "Được giao" khi không thu hẹp, và guard đọc gì khi không có dòng giao: nay ảnh chụp ứng viên lúc mở.
    - Giao khóa theo `(run_id, node_id)` nên vòng sau đọc giao của vòng trước: nay mỗi điểm chờ (`interrupt_id`) một
      lần giao; `required_scope` chép ở hai bảng: nay chỉ ở tem.
    - Ứng viên tính ở workspace nào: workspace của lượt chạy, nơi yêu cầu nằm (ADR-0004 (Accepted)).
    - Biểu thức thu hẹp: kiểu, môi trường, hành vi khi lỗi.
    - Chạy lại sau khi worker chết mở yêu cầu thứ hai: nay UNIQUE theo điểm chờ.
    - Bộ trả phiên bản chủ thể cho mã Zalo ở W1 không ai đọc: bỏ, W2.
    - `approval_type` cố định hay chỉ dưới tiền tố: cố định `studio.step.approval`.
    - Danh sách Trường đóng dấu lấy từ đâu: đối số của chủ thể cộng `show_fields`.
- 2026-11-04 (agent): MEDIUM của gate, cho người làm và cho `checking-plan-consistency`:
    - (a) Tắt khẩn và một lệnh quyết trên cùng yêu cầu cùng lúc: thứ tự do khóa hàng của `platform.approval_requests`
      quyết; không tiêu chí riêng.
    - (b) Yêu cầu bị trigger hủy không có audit riêng; audit của lượt bị hủy (`run.deadline_exceeded`, Tắt khẩn) là bản
      ghi của việc đó.
    - (c) Spec workflow-engine, workflow-builder-ui và ADR-0112 (Accepted) nói `human.approval@1` cho Bước phê duyệt của
      Studio; nay là `@2`. Cho `checking-plan-consistency`.
    - (d) Biểu thức `assignees` đọc dữ liệu bản ghi do bên ngoài ghi có thể lái yêu cầu tới một người giữ scope cụ thể;
      người đó vẫn phải giữ scope và qua mọi kiểm.
    - (e) Người được giao rời công ty sau lúc mở, và người được cấp scope sau đó không quyết được: lượt chờ tới hạn chót
      30 ngày. Giao lại và chuyển cấp là W2.
    - (f) Cho `checking-plan-consistency`: workflow-engine/05 cần một cửa mở dòng chờ trong giao dịch của Bước với
      `interrupt_id` tất định theo `(node_id, iteration_path)`; tenant-config/05 và field-security:R4.5 cần đọc Trường
      đóng dấu ở `payload.stamped_fields`; route đọc phê duyệt cần hỏi `payload_guards`.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (builder check mới) tìm 10 câu, sửa theo khuyến nghị:
  dòng chờ mở trong cùng giao dịch với `interrupt_id` tất định; ứng viên giữ cả `approvals.decide`; chủ thể ở chế độ khác
  `live`; Trường đóng dấu tìm bằng `check` lại; khóa `payload.stamped_fields`; `payload_guards` cho lần đọc; người tạo
  lượt và chủ thể chạy; trigger chạy trong ngữ cảnh tenant của đường hủy; kiểm R9.5 lúc gửi kiểm định; công cụ
  `internal` mà chính sách đòi người. Không còn CRITICAL hay HIGH.
- 2026-11-04 (agent): bảng cặp cho hai cảnh báo va chạm của `check_plans.py`, ticket không có đường phụ thuộc với
  ticket này:
    - 04 × 06, `app.tenant_id`: cả hai chỉ nêu ngữ cảnh RLS mà mọi giao dịch đặt; không bảng, migration hay tệp chung.
      Không va chạm.
    - 05 × 06, `wf.unknown_type` và `STUDIO_RULES.refused_types`: tập do ticket 03 thêm, mỗi ticket thêm một dòng của
      mình vào nó. Va chạm một dòng trong một tệp, như các dòng `|=` của composition root; ticket sau rebase lên ticket
      trước.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): theo lượt xác nhận của gate ticket 07: yêu cầu `studio.step.approval`
  không rút được ở W1 (bước 3), vì một lần rút không đóng điểm chờ. Không thêm cạnh.
