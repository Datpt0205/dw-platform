# 07 — Bước song song, Bước vòng lặp, Thoát vòng lặp và Bước phê duyệt cần mọi người được giao

Status: ready-for-agent
Blocked by: 03, 06, .claude/plans/studio/workflow-engine/issues/06-song-song-vong-lap-co-tran-va-nhanh-loi.md, .claude/plans/studio/workflow-engine/issues/07-chay-tiep-tu-buoc-loi.md
Area: studio
Yêu cầu: R1.6, R3.2, R3.3, R9.9, R10.1, R10.2, R10.3, R10.4, R11.1, R11.2, R11.3, R12.1, R12.2, R12.3, R12.4, R12.5, R12.6, R12.7, R12.8, R12.9, WN11, WN22, WN23, WN24, WN25, WN26, WN28, WN29, WN30, WN31

## Mục tiêu

Bậc B của W1 (V4.26), sau đường găng YC94: ba loại bước điều khiển `logic.parallel@1`, `logic.loop@1` và
`logic.break@1` trong `NodeTypeRegistry`, với kiểm vị trí của các loại spec này sở hữu, và quy tắc `approval_rule`
`all` của `human.approval@2`, để người dựng chạy các làn cùng lúc, lặp lại một đoạn quy trình có trần, kể cả vòng
làm lại có phê duyệt, và đòi mọi người được giao cùng duyệt một Bước với một điểm chờ (workflow-nodes R1.6, R3.2,
R9.9, R10, R11, R12, WN11, WN22-WN26, WN28-WN31). Cách chạy của khối là của trình biên dịch của workflow-engine. Không
ticket thí điểm nào chờ ticket này.

## Việc cần làm

1. **Ba mục mới trong `studio_node_types` của ticket 03** (`packages/python/dw_studio/src/dw_studio/workflows/node_registry.py`),
   mỗi mục `side_effect_level` `none`, `allowed_on_error` chỉ `fail`, không đầu ra `error` (R1.6), `dependencies` `()`,
   `opens_wait` và `ends_run` sai:
    - `logic.parallel@1`, nhãn "Song song", `block` `parallel`, `exits_loop` sai. Cấu hình `branches`: đối tượng từ
      khóa làn tới làn Bước, như `cases` của `logic.switch@1`, với `propertyNames` khớp `^[a-z][a-z0-9_]{0,39}$`,
      `minProperties: 2`, `maxProperties: 10` (trần nền tảng của W1); `labels` tùy chọn, đối tượng từ khóa làn tới nhãn
      tiếng Việt, mỗi khóa phải có trong `branches`, làn không có nhãn hiện khóa. Làn nằm trong `config` dưới tên Nhánh
      ra (ADR-0112 (Accepted) Amendments 2026-11-03): `lanes(config)` trả `branches.<khóa>`, nên phép hạ và con trỏ lỗi
      (`/config/branches/<khóa>/<n>`) đi như với `cases`, không cơ chế mới. Khóa là khóa của một đối tượng, nên hai làn
      cùng khóa không biểu diễn được (R10.1). Vi phạm → `wf.config_invalid`. Gộp kiểu all ở Điểm nối cuối các làn, không
      có khóa chọn kiểu gộp, không có mục `logic.join@1` (R10.2). Danh mục của ticket 02 nêu Nhánh ra của loại là "mỗi
      khóa của `branches` một Nhánh ra".
    - `logic.loop@1`, nhãn "Lặp lại khi … (tối đa N lần)", `block` `loop`, `exits_loop` sai. Cấu hình `condition` (Biểu
      thức `x-dw-cel` `["bool"]` của ticket 03) và `max_iterations` (số nguyên 1-100, `maximum: 100` là trần nền tảng
      của W1, như nhau mọi gói, tới khi usage-and-limits có cột gói cho nó) đều bắt buộc (R11.1). Nhánh
      ra `body` (thân, bắt buộc) và `max_reached` ("Đã đủ N lần", tùy chọn) (R11.2). Điều kiện tính sau thân (do-while),
      nên môi trường của nó là môi trường ở cuối thân: mọi Bước trội cuối thân, kể cả Bước của thân; `draft/scope?node=`
      của Bước vòng lặp trả đúng môi trường đó.
    - `logic.break@1`, nhãn "Thoát vòng lặp", `block` `none`, `exits_loop` đúng, cấu hình rỗng
      (`additionalProperties: false`), không Nhánh ra.
2. Hook biên dịch của ba loại chỉ trả cấu hình đã kiểm cho trình biên dịch của workflow-engine, chủ của cấu trúc khối
   trong `WorkflowIR` và trình biên dịch: mỗi làn một subgraph gộp bằng waiting edge, vòng lặp do-while có kênh đếm vòng,
   trần `max_iterations` với làn `max_reached` hay `loop_limit_reached`, cạnh có điều kiện tới lối ra cho Thoát vòng lặp,
   khóa chống lặp và điểm chờ theo vòng (ADR-0112 (Accepted) quyết 4-5).
3. Ba tính chất vị trí: `ends_run` và `exits_loop` của workflow-engine/01, `opens_wait` của workflow-engine/06. Bộ kiểm
   của workflow-engine/06 đọc `opens_wait` (đúng với `human.approval@2`, ticket 06), `ends_run` (đúng với `flow.stop@1`,
   ticket 03) và `exits_loop` để trả `wf.wait_in_parallel` (R10.4), `wf.stop_in_parallel` (R10.3) và
   `wf.break_outside_loop` (R11.3), không đọc danh sách tên loại; test của ticket này ghim giá trị của ba loại
   `human.approval@2`, `flow.stop@1`, `logic.break@1` bằng ca đột biến (R1.4, WN15).
4. **Quy tắc `all` của `human.approval@2`** (R12.1). Khóa tùy chọn `approval_rule` (`any` hay `all`, vắng là `any`;
   giá trị khác bị schema từ chối, k < n là W3). Với `all`, `assignees` bắt buộc (danh sách 1-10 id, hay Biểu thức
   `list[string]`); thiếu → schema từ chối; Biểu thức trả hơn 10 người → Bước lỗi `approver_limit_exceeded` theo Khi
   lỗi; trả danh sách rỗng, hay chỉ `null` và chuỗi rỗng → `no_approver`, không yêu cầu nào mở. Lúc gửi kiểm định,
   `assignees` tĩnh của `all` qua kiểm của R9.5 từng người: một người không giữ `required_scope` và `approvals.decide`
   ở workspace sở hữu, hay chính là người gửi kiểm định → 422 `no_second_approver` có con trỏ tới người đó. Ở `live`:
   phân giải `assignees` thành n người khác nhau (trùng thì gộp); mỗi người qua đúng kiểm ứng viên của ticket 06 bước 3
   (giữ `required_scope` và `approvals.decide` ở workspace của lượt, khác người tạo lượt chạy, chủ thể chạy và tài khoản
   dịch vụ); một người trượt thì Bước kết thúc với `no_approver` theo Khi lỗi của nó và không yêu cầu nào mở (R12.3); qua
   hết thì trong một giao dịch, dưới khóa chống lặp mà wrapper nút dẫn (workflow-engine:R4.5) và cùng dòng chờ của ticket
   06, mở n dòng `platform.approval_requests` loại `studio.step.approval` cùng `required_scope`, cùng
   `payload.stamped_fields` (R9.7) và cùng `subject_hash` (R9.3), n dòng `studio.step_assignments` và n dòng
   `studio.step_approvals` mang `assignee_id` của từng người và `approval_rule` `all`, mọi dòng trỏ cùng một dòng
   `platform.run_waits` `(run_id, interrupt_id)` (R12.2). Chủ thể của ticket 06 so mã băm với các dòng của điểm chờ:
   mọi dòng phải mang cùng `subject_hash`, khác nhau hay không có dòng nào → `approval_missing`, không gửi. Ở chế độ
   khác `live`, Bước theo R9.9: một quyết định giả lập cho cả Bước, không yêu cầu nào mở.
5. **Migration** (`alembic revision -m "studio step approvals all rule"`, id hex ngẫu nhiên, nối tiếp migration của
   ticket 06):
    - `studio.step_approvals.assignee_id uuid` NULL và `approval_rule text NOT NULL` CHECK (`any`, `all`): thêm với
      DEFAULT `'any'` để dòng của ticket 06 nhận đúng giá trị, rồi bỏ DEFAULT trong cùng migration, nên mọi dòng mới nêu
      quy tắc của mình (failure-modes #7); CHECK `ck_step_approvals_assignee_rule`
      `(approval_rule = 'all') = (assignee_id IS NOT NULL)`.
    - UNIQUE `(tenant_id, run_id, interrupt_id)` của ticket 06 thay bằng UNIQUE NULLS NOT DISTINCT
      `(tenant_id, run_id, interrupt_id, assignee_id)`, tên theo `NAMING_CONVENTION`.
    - Trigger hủy của ticket 06 (AFTER UPDATE OF `status` trên `platform.run_waits`) nghe mọi lần dòng chờ rời `open`
      (`OLD.status = 'open' AND NEW.status <> 'open'`), không liệt kê trạng thái, và đặt mọi yêu cầu `pending` nối qua
      `studio.step_approvals` sang `cancelled` trong cùng giao dịch (R12.7; R9.15 giữ nguyên).
    - `test_offboarding_coverage.py` nêu cột mới `assignee_id`: dòng đi theo lượt chạy qua FK CASCADE.
6. **Guard**: mục `decision_guards['studio.step.approval']` của ticket 06 đọc `approval_rule` của dòng
   `studio.step_approvals` của yêu cầu: `all` → chỉ người quyết là `assignee_id` của chính dòng đó; `any` → người quyết
   có dòng `step_assignments` của điểm chờ (ticket 06). Cả hai trả 403 `permission_denied` khi trượt (R12.4). CHECK của
   bước 5 làm một dòng `all` vắng `assignee_id` không tồn tại được, nên không có đường đọc nó thành `any`. Mọi điều kiện
   của R9.2, R9.6, R9.8 giữ nguyên cho từng yêu cầu. `payload_guards['studio.step.approval']` của ticket 06 dùng cùng
   hàm điều kiện, nên với `all` mỗi người chỉ đọc `payload` của yêu cầu của mình.
7. **Kết quả của điểm chờ** (R12.5, R12.6): một hàm thuần `wait_outcome(rows)` ở `dw_studio.workflows`, mà adapter của
   `StepWaitLookupPort` (workflow-engine/05 khai; workflow-engine/07 thêm kết quả vào hợp đồng) và Bước (bước 8) cùng
   gọi, không bản sao: `any` → quyết định của yêu cầu duy nhất; `all` → `approved` khi mọi yêu cầu `approved`,
   `rejected` khi có một yêu cầu `rejected`, `cancelled` hay `expired` (không bao giờ đọc thành duyệt), `pending` khi còn
   yêu cầu `pending` và không có yêu cầu nào như vừa nêu. Không có dòng nào, hay các dòng mang hai quy tắc khác nhau,
   thì `wait_outcome` ném lỗi, không bao giờ trả `approved`: handler giữ dòng chờ `open`, và Bước lúc tiếp tục làm lượt
   `failed` với `approval_incomplete`. Adapter khóa dòng `platform.run_waits` của điểm chờ
   (`SELECT ... FOR UPDATE`) rồi đọc mọi dòng `studio.step_approvals` của nó, nên hai lần quyết của cùng điểm chờ nối
   tiếp nhau. Handler theo tiền tố `studio.step.` của workflow-engine chỉ đặt dòng chờ `resolved` và lượt `queued` khi kết
   quả khác `pending`, và giữ dòng chờ `open` khi là `pending` (Phụ thuộc của spec; ADR-0112 (Accepted) quyết 7). Một lần
   từ chối và một lần duyệt cùng lúc có thể deadlock giữa khóa của yêu cầu và khóa của dòng chờ: PostgreSQL hủy một giao
   dịch (40P01), lần quyết đó trả 409 `conflict` và không đổi gì, người đó quyết lại và thấy yêu cầu đã `cancelled`.
   Phép ánh 40P01 sang 409 nằm ở `ApproveAndResumeService.decide` của `dw_platform`, một nhánh `except` cho mọi loại
   phê duyệt, không thử lại tự động; ticket này thêm nó cùng test, vì nó là ticket đầu tiên có hai giao dịch quyết tranh
   nhau trên một điểm chờ.
8. Lúc tiếp tục, Bước `all` đọc kết quả qua `StepWaitLookupPort` (cùng `wait_outcome`), không đọc giá trị tiếp tục, và
   không có SQL trong mô-đun loại bước (R2.2): `approved` thì làn `approved` (R9.16), `rejected` thì làn `rejected`, mọi
   trường hợp khác thì lượt `failed` với `error.code` `approval_incomplete` và không làn nào chạy (R12.8, R12.9). Hai mã
   mới, `approver_limit_exceeded` và `approval_incomplete`, có nhãn trong `configs/copy/run_reason_codes.d/workflow-nodes.yaml`
   (H-21).
9. Test: `packages/python/dw_studio/tests/workflows/test_control_nodes.py` cho ba loại điều khiển, tính chất vị trí và
   kiểm vị trí; `packages/python/dw_studio/tests/workflows/test_approval_all_rule.py` cho quy tắc `all`; ca đồng thời trên
   hai kết nối với thứ tự xen kẽ cố định, ca trigger và ca lượt chạy chờ rồi tiếp tục trong `make test-integration`.
10. **`effect_door`** (workflow-engine/03; bảng ở mục Trong phạm vi của spec, chủ duy nhất): `logic.parallel`, `logic.loop`, `logic.break` khai không cửa; thiếu trường thì sổ từ chối đăng ký, và `incident` của `allowed_on_error` do luật của workflow-engine/07 suy từ trường này, loại không tự khai.

## Tiêu chí chấp nhận

- [ ] R1.6 (WN11): Bước song song, Bước vòng lặp hay Thoát vòng lặp khai Khi lỗi `continue` hay `route` →
      `wf.config_invalid`; schema đầu ra của ba loại không có `error`; thêm `route` vào Khi lỗi cho phép của
      `logic.loop@1` → test đỏ.
- [ ] R10.1 (WN31): `logic.parallel@1` với một làn → `wf.config_invalid`; một khóa `Lane-1` → `wf.config_invalid`; 11
      làn → `wf.config_invalid`; `labels` nêu một khóa không có trong `branches` → `wf.config_invalid`; hai làn khóa khác
      nhau đúng mẫu → nhận, và `lanes(config)` trả hai Nhánh ra theo hai khóa đó, lỗi trong làn có con trỏ
      `/config/branches/<khóa>/<n>`; bỏ `minProperties` → một làn qua, test đỏ.
- [ ] R10.2 (WN22): tài liệu mang `logic.join@1` → `wf.unknown_type`, không niêm phong; đăng ký một mục `logic.join@1`
      vào registry → tài liệu đó niêm phong, test đỏ.
- [ ] R10.3 (WN23): `flow.stop` ở làn 2, hay trong làn lỗi của một Bước ở làn 2 → `wf.stop_in_parallel`, không niêm
      phong; `flow.stop` ở làn gốc sau Bước song song → niêm phong; đặt `ends_run` của `flow.stop@1` về sai → tài liệu
      có `flow.stop` trong làn niêm phong, test đỏ.
- [ ] R10.4 (WN24): Bước phê duyệt ở làn 2, kể cả trong thân một Bước vòng lặp nằm trong làn đó →
      `wf.wait_in_parallel`, không niêm phong; Bước phê duyệt trong thân một Bước vòng lặp ngoài mọi làn → niêm phong;
      đặt `opens_wait` của `human.approval@2` về sai → test đỏ.
- [ ] R11.1 (WN25): `logic.loop@1` thiếu `max_iterations`, `max_iterations = 0` hay thiếu `condition` → schema từ
      chối; `max_iterations = 1` và `100` → nhận, `101` → `wf.config_invalid`; bỏ `max_iterations` khỏi danh sách khóa
      bắt buộc → test đỏ.
- [ ] R3.3: `condition` của `logic.loop@1` trả `string` → `wf.type_mismatch`, không niêm phong; trả `bool` và tham chiếu
      một Bước của thân → qua.
- [ ] R11.2 (WN31): Bước vòng lặp không mang làn `body` → `wf.router_not_total` (workflow-engine:R2.2); không mang làn
      `max_reached` → niêm phong; danh mục trả `max_reached` là Nhánh ra tùy chọn và `body` là bắt buộc; đặt `body` về
      Nhánh ra tùy chọn → tài liệu không mang làn `body` niêm phong, test đỏ.
- [ ] R11.3 (WN26): Thoát vòng lặp ở làn gốc, hay trong một `logic.switch` ngoài mọi vòng lặp, hay trong một làn song
      song, kể cả của một vòng lặp nằm trọn trong làn → `wf.break_outside_loop`, không niêm phong; trong làn `rejected`
      của một Bước phê duyệt ở thân → niêm phong; đặt `exits_loop` của `logic.break@1` về sai → test đỏ.
- [ ] R3.2: Bước ở làn 1 tham chiếu một Bước ở làn 2 → `wf.ref_not_dominating`; Bước kế tiếp sau Bước song song tham
      chiếu Bước đó → qua; Bước sau Bước vòng lặp tham chiếu một Bước của thân đứng trước mọi Thoát vòng lặp → qua
      (do-while), tham chiếu một Bước của thân đứng sau một Thoát vòng lặp có điều kiện → `wf.ref_not_dominating`; cây
      `draft/scope` ở các vị trí đó, và ở chính Bước vòng lặp (môi trường của điều kiện), liệt kê đúng như vậy.
- [ ] R12.1 (WN31): `approval_rule` `all` có `assignees` và `any` → nhận; `all` thiếu `assignees`, `k_of_n` hay `2` →
      schema từ chối; vắng khóa → Bước chạy như `any`, tài liệu lead mẫu của ticket 06 cho cùng kết quả như trước ticket
      này; bỏ tập giá trị cho phép của `approval_rule` → `k_of_n` qua và Bước chạy như `any`, test đỏ.
- [ ] R12.2 (WN29): Bước `all` giao A, B, C ở `live` → đúng 3 yêu cầu `studio.step.approval` cùng `subject_hash`, 3 dòng
      `studio.step_approvals` mang `assignee_id` A, B, C và `approval_rule` `all`, 1 dòng chờ; worker chết sau khi mở rồi
      lượt được nhận lại → vẫn đúng 3 yêu cầu; chèn một dòng thứ hai cho A cùng điểm chờ → UNIQUE từ chối; Biểu thức trả
      11 người → `approver_limit_exceeded`, 0 yêu cầu; trả `[]` → `no_approver`, 0 yêu cầu; `assignees` `[A, B, A]` → 2
      yêu cầu. Lúc gửi kiểm định, `assignees` tĩnh nêu người gửi kiểm định → 422 `no_second_approver`.
- [ ] R12.3 (WN28): C rời công ty trước lúc mở → Bước kết thúc với `no_approver` theo Khi lỗi, 0 yêu cầu được mở;
      người được giao thứ ba là một người dùng của công ty B trong lượt của công ty A → `no_approver`, 0 yêu cầu ở cả
      hai công ty; cho Bước bỏ C rồi mở hai yêu cầu → test đỏ.
- [ ] R12.4 (WN28): B quyết yêu cầu của A → 403 `permission_denied`, yêu cầu của A vẫn `pending`; A quyết yêu cầu của
      chính mình → nhận; chèn một dòng `step_approvals` `approval_rule` `all` vắng `assignee_id` → CHECK từ chối; gỡ điều
      kiện `assignee_id` khỏi guard, hay cho guard bỏ qua `approval_rule` → B duyệt hai phần, test đỏ. Thân vòng lặp: vòng
      1 giao A, B, vòng 2 giao chỉ A; B quyết yêu cầu của vòng 2 → 403.
- [ ] R12.5 (WN29): A duyệt → `pending`, dòng chờ `open`, lượt chờ; B duyệt → `pending`; C duyệt → `approved`; A, B
      duyệt rồi C từ chối → `rejected`; một yêu cầu `cancelled` khi điểm chờ còn `open` → `rejected`; Bước `any` → kết quả
      là quyết định của yêu cầu duy nhất.
- [ ] R12.6 (WN29): sau A, hai giao dịch duyệt của B và C xen kẽ theo thứ tự cố định → đúng một lần quyết trả
      `approved`, dòng chờ sang `resolved` đúng một lần; bỏ khóa dòng chờ → cả hai trả `pending` và dòng chờ kẹt `open`,
      test đỏ. A từ chối cùng lúc B duyệt → một trong hai trả 409 `conflict` và không đổi gì, kết quả cuối `rejected`;
      gỡ phép ánh 40P01 → lần đó trả 500, test đỏ. `wait_outcome([])` → ném lỗi, không `approved`.
- [ ] R12.7 (WN30): A từ chối → `rejected`, yêu cầu của B và C `cancelled` trong cùng giao dịch; B quyết sau đó → bị
      từ chối, yêu cầu vẫn `cancelled`; cho trigger chỉ nghe `cancelled` như ticket 06 → yêu cầu của B còn `pending`,
      test đỏ.
- [ ] R12.8 (WN29): cả ba duyệt → làn `approved` chạy một lần, làn `rejected` không chạy; một người từ chối → làn
      `rejected` chạy, `tool.call@2` trong làn `approved` có 0 lời gọi.
- [ ] R12.9 (WN29): một handler giả đặt dòng chờ `resolved` ở lần duyệt đầu → lượt `failed` với `error.code`
      `approval_incomplete`, `tool.call@2` trong làn `approved` có 0 lời gọi; cho Bước đọc giá trị tiếp tục thay kết quả
      của `wait_outcome` → làn `approved` chạy, test đỏ.
- [ ] R9.9: Bước `all` ở `simulate` với quyết định giả lập `approved` → làn `approved` chạy, 0 dòng
      `platform.approval_requests` và 0 dòng `platform.run_waits`.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/workflows/test_control_nodes.py packages/python/dw_studio/tests/workflows/test_approval_all_rule.py && make test-integration` xanh.

## Nguồn

- ADR-0112 (Accepted) quyết 2, 3, 4, 5, 7; spec: R1.6, R10, R11, R12.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:217-235`; spec: R12.2
  (`approval_requests` giữ một trạng thái mỗi yêu cầu, nên mỗi người duyệt bắt buộc có một yêu cầu).
- `apps/api/src/dw_api/bootstrap/runtime.py:343-345`; spec: R12.4 (`decision_guards`).

## Comments

- 2026-10-24 (agent): ticket mới theo V4.26 của Đạt (bậc B của W1), thay vì mở rộng ticket 03: marketing-pilot/03 chờ
  workflow-nodes/04, 05 và 06, ba ticket đều chờ ticket 03, nên đặt bậc B ở ticket 03 làm đường găng YC94 chờ bậc B
  (dòng Quyết định cùng ngày của spec, agent, tạm). Cách chạy của ba loại điều khiển ở trình biên dịch của
  workflow-engine, nên ticket này không thử nó. Hai cạnh tới workflow-engine, đã kiểm không tạo vòng: ticket 06 của
  nó, nơi bộ kiểm trả `wf.stop_in_parallel`, `wf.wait_in_parallel` và `wf.break_outside_loop` (workflow-engine:R2.15,
  R2.16, R2.17) mà R10.3, R10.4, R11.3 thử; ticket 07 của nó, nơi `StepWaitLookupPort` khai kết quả của điểm chờ và
  handler `studio.step.` chỉ đóng điểm chờ khi kết quả khác `pending` (workflow-engine:R6.3, R6.29), mà R12.5-R12.9
  dựa vào.
- 2026-10-24 (agent): kiểm lượt g của vòng 4: R10.1, R11.2 và R12.1 là điều kiểm mới, nên mang kiểm soát WN31 với ca
  đột biến (failure-modes #3); guard của quy tắc `all` nhận ra yêu cầu của nó bằng điểm chờ có từ hai yêu cầu trở lên
  và không cho ai quyết một dòng vắng `assignee_id`, vì bản trước chỉ thêm điều kiện khi dòng mang `assignee_id`, nên
  một dòng `all` vắng cột đó đọc thành `any` (R12.4; failure-modes #7); bước 8 làm lượt `failed` ở mọi trường hợp
  chưa đủ duyệt, không chỉ khi còn yêu cầu `pending` (R12.9). Không thêm cạnh.
- 2026-10-25 (agent): ba tính chất vị trí là trường bắt buộc của `NodeTypeSpec` từ ticket 02, vì ticket này chờ
  workflow-engine/06, nơi bộ kiểm đọc chúng, nên không thể là nơi thêm chúng; bước 3 chỉ còn khai giá trị cho ba loại
  của ticket và ghim bằng ca đột biến giá trị của `human.approval@1`, `flow.stop@1`, `logic.break@1` (dòng Quyết định
  25/10/2026 của spec). Không thêm cạnh.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check cùng boundary walk; ticket
  có migration). Lượt đầu: 1 CRITICAL, 10 HIGH, đều sửa ở ticket này và spec (Quyết định 4/11/2026; R10.2, WN22, WN28,
  API, Dữ liệu):
    - CRITICAL: R10.2 dùng `wf.unknown_node_type`, mà ADR-0112 (Accepted) Amendments 2026-11-03 giữ `wf.unknown_type`
      của wf-lite: nay `wf.unknown_type`.
    - `logic.parallel@1` khai `lanes` là danh sách `{key, label}` trong khi làn nằm trong `config` dưới tên Nhánh ra:
      nay `branches` `{key, label, steps}`, khóa trùng do kiểm của loại.
    - Ba loại thiếu `block`, `dependencies`, `allowed_on_error` (trường bắt buộc của workflow-engine/01 và ticket 03).
    - `max_iterations` và số làn không có trần trên: nay 100 vòng, 10 làn, `wf.limit_above_plan`.
    - Điều kiện của vòng lặp tham chiếu được Bước của thân không, và `draft/scope` của Bước vòng lặp trả gì.
    - `all` không có người được giao, và n không trần: nay `assignees` bắt buộc, tối đa 10.
    - `approval_rule` trên đường gói: hết câu hỏi, vì Bước phê duyệt của Studio là `human.approval@2` (gate ticket 06).
    - Giao không khóa theo vòng: đã sửa ở ticket 06 (`interrupt_id`); guard nhận ra `all` bằng đếm dòng: nay cột
      `approval_rule` có CHECK.
    - Yêu cầu `cancelled` hay `expired` riêng lẻ đọc thế nào: nay như `rejected`.
    - Bước đọc trạng thái qua cửa nào, và luật "đủ n" có hai bản: nay một hàm `wait_outcome` qua `StepWaitLookupPort`.
    - Trigger liệt kê trạng thái: nay nghe mọi lần rời `open`.
- 2026-11-04 (agent): MEDIUM của gate, cho người làm và cho `checking-plan-consistency`:
    - (a) Người được giao của Bước `all` rời công ty sau lúc mở: yêu cầu của họ còn `pending`, lượt chờ tới hạn chót 30
      ngày; giao lại là W2.
    - (b) Yêu cầu của B và C bị hủy theo lần từ chối của A không có audit riêng; audit lần quyết của A là bản ghi của
      việc đó.
    - (c) workflow-engine/07 cần `StepWaitLookupPort` trả kết quả của điểm chờ theo `wait_outcome`, và adapter khóa dòng
      chờ trước khi đọc.
    - (d) Ticket 07 và 08 cũ viết "registry của ticket 02 (`node_registry.py`)"; nay là `studio_node_types` của ticket 03.
    - (e) Danh sách `/approvals` tính `can_decide` theo scope (ADR-0004 (Accepted)), nên với `all` B thấy yêu cầu của A
      như quyết được và nhận 403 khi bấm; đọc `payload` thì đã chặn. Cho workflow-builder-ui và `checking-plan-consistency`.
    - (f) Người tạo lượt nằm trong `assignees` của `all` làm mọi lượt của người đó `no_approver` (R12.3 cùng YC51);
      kiểm lúc gửi kiểm định chỉ bắt người gửi.
    - (g) Hai làn song song không gửi được tin ra ngoài: `tool.call@2` `external` phải là chủ thể của một phê duyệt, mà
      phê duyệt không nằm trong làn (R10.4; workflow-engine:R2.20). Đúng theo thiết kế của W1.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (builder check mới) tìm 9 câu, sửa theo khuyến nghị:
  `assignees` rỗng là `no_approver`, `wait_outcome` của tập rỗng hay trộn quy tắc ném lỗi; rút yêu cầu `studio.step.`
  bị từ chối (ticket 06); chủ thể so mã băm trên n dòng; `branches` thành đối tượng như `cases`, trần bằng schema, không
  cơ chế kiểm mới; `payload_guards` theo quy tắc; phép ánh 40P01 ở `ApproveAndResumeService.decide`; kiểm `assignees`
  tĩnh lúc gửi kiểm định. Không còn CRITICAL hay HIGH.
- 2026-11-04 (agent): bảng cặp cho hai cảnh báo va chạm của `check_plans.py`, ticket không có đường phụ thuộc với
  ticket này:
    - 04 × 07, `dw_studio.workflows`: tên gói chung, mỗi ticket thêm mô-đun riêng (`test_assign_node`,
      `test_control_nodes`); không bảng, migration hay tệp chung. Không va chạm.
    - 05 × 07, `configs/copy/run_reason_codes.d/workflow-nodes.yaml` và `wf.config_invalid`: mảnh nhãn do ticket 02 tạo,
      mỗi ticket thêm dòng mã của mình (H-21); `wf.config_invalid` là mã chung đã có. Va chạm vài dòng nối thêm vào một
      tệp; ticket sau rebase lên ticket trước.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
