# 07 — Bước song song, Bước vòng lặp, Thoát vòng lặp và Bước phê duyệt cần mọi người được giao

Status: needs-triage
Blocked by: 03, 06, .claude/plans/studio/workflow-engine/issues/06-song-song-vong-lap-co-tran-va-nhanh-loi.md, .claude/plans/studio/workflow-engine/issues/07-chay-tiep-tu-buoc-loi.md
Area: studio
Yêu cầu: R1.6, R3.2, R9.9, R10.1, R10.2, R10.3, R10.4, R11.1, R11.2, R11.3, R12.1, R12.2, R12.3, R12.4, R12.5, R12.6, R12.7, R12.8, R12.9, WN11, WN22, WN23, WN24, WN25, WN26, WN28, WN29, WN30, WN31

## Mục tiêu

Bậc B của W1 (V4.26), sau đường găng YC94: ba loại bước điều khiển `logic.parallel@1`, `logic.loop@1` và
`logic.break@1` trong `NodeTypeRegistry`, với kiểm vị trí của các loại spec này sở hữu, và quy tắc `approval_rule`
`all` của `human.approval@1`, để người dựng chạy các làn cùng lúc, lặp lại một đoạn quy trình có trần, kể cả vòng
làm lại có phê duyệt, và đòi mọi người được giao cùng duyệt một Bước với một điểm chờ (workflow-nodes R1.6, R3.2,
R9.9, R10, R11, R12, WN11, WN22-WN26, WN28-WN31). Cách chạy của khối là của trình biên dịch của workflow-engine. Không
ticket thí điểm nào chờ ticket này.

## Việc cần làm

1. Ba mục `NodeTypeSpec` mới trong registry của ticket 02
   (`packages/python/dw_studio/src/dw_studio/workflows/node_registry.py`), mỗi mục `side_effect_level` `none`, chỉ
   Khi lỗi `fail`, không đầu ra `error` (R1.6):
    - `logic.parallel@1`, nhãn "Song song": cấu hình `lanes` là danh sách từ 2 phần tử trở lên `{key, label}`, `key`
      khớp `^[a-z][a-z0-9_]{0,39}$` và duy nhất trong Bước, `label` tiếng Việt; mỗi `key` là một Nhánh ra, mỗi Nhánh
      ra một làn Bước (R10.1); gộp kiểu all ở Điểm nối cuối các làn, không có khóa chọn kiểu gộp; không có mục
      `logic.join@1` (R10.2).
    - `logic.loop@1`, nhãn "Lặp lại khi … (tối đa N lần)": cấu hình `condition` (CEL, kiểu `bool` theo R3.3) và
      `max_iterations` (số nguyên từ 1 trở lên) đều bắt buộc (R11.1); Nhánh ra `body` (thân) bắt buộc và
      `max_reached` ("Đã đủ N lần") tùy chọn (R11.2).
    - `logic.break@1`, nhãn "Thoát vòng lặp": cấu hình rỗng (`additionalProperties: false`), không Nhánh ra.
2. Hook biên dịch của ba loại chỉ trả cấu hình đã kiểm cho trình biên dịch của workflow-engine, chủ của cấu trúc khối
   trong `WorkflowIR` và trình biên dịch: mỗi làn một subgraph gộp bằng waiting edge, vòng lặp do-while có kênh đếm
   vòng, trần `max_iterations` với làn `max_reached` hay `loop_limit_reached`, cạnh có điều kiện tới lối ra cho Thoát
   vòng lặp, khóa chống lặp và điểm chờ theo vòng (ADR-0112 (Accepted) quyết 4-5).
3. Ba loại của ticket này khai ba tính chất vị trí mà ticket 02 đặt bắt buộc: `logic.break@1` khai `exits_loop`
   đúng, `opens_wait` và `ends_run` sai; `logic.parallel@1` và `logic.loop@1` khai cả ba sai. Bộ kiểm khi gửi kiểm
   định của workflow-engine/06 đọc `opens_wait` (đúng với `human.approval@1`, ticket 06), `ends_run` (đúng với
   `flow.stop@1`, ticket 03) và `exits_loop` để trả `wf.wait_in_parallel` (R10.4), `wf.stop_in_parallel` (R10.3) và
   `wf.break_outside_loop` (R11.3), không đọc danh sách tên loại; test của ticket này ghim giá trị của ba loại
   `human.approval@1`, `flow.stop@1`, `logic.break@1` bằng ca đột biến (R1.4, WN15).
4. `human.approval@1` thêm khóa tùy chọn `approval_rule` (`any` hay `all`, vắng là `any`; giá trị khác bị schema từ
   chối, k < n là W3) (R12.1). Ở `live`, với `all`: phân giải tập người được giao (người, hay Biểu thức) thành n
   người khác nhau; mỗi người qua đúng kiểm ứng viên của R9.13 (`effective_grants` của tenant-rbac: giữ
   `required_scope`, khác người tạo lượt chạy và chủ thể chạy); một người trượt thì Bước kết thúc với `no_approver`
   theo Khi lỗi của nó và không yêu cầu nào mở (R12.3); qua hết thì trong một giao dịch, dưới khóa chống lặp mà
   wrapper nút dẫn (workflow-engine:R4.5), mở n dòng `platform.approval_requests` loại `studio.step.approval` cùng
   `required_scope`, cùng danh sách Trường đóng dấu (R9.7) và cùng `subject_hash` (R9.3), n dòng
   `studio.step_assignments` và n dòng `studio.step_approvals` mang `assignee_id` của từng người, mọi dòng trỏ cùng
   một dòng `platform.run_waits` `(run_id, interrupt_id)` (R12.2). Ở `simulate`, Bước theo R9.9: một quyết định giả
   lập cho cả Bước, không yêu cầu nào mở.
5. Migration sinh bằng `alembic revision -m "studio step approvals assignee"` (id hex ngẫu nhiên, nối tiếp
   migration của ticket 06): `studio.step_approvals.assignee_id uuid` NULL (NULL khi `any`) và UNIQUE
   `(tenant_id, run_id, interrupt_id, assignee_id)`, tên theo `NAMING_CONVENTION`; trigger hủy của ticket 06
   (AFTER UPDATE OF `status` trên `platform.run_waits`) nghe mọi lần dòng chờ rời `open`, sang `resolved` hay
   `cancelled`, không chỉ `cancelled`, và đặt mọi yêu cầu `pending` nối qua `studio.step_approvals` sang `cancelled`
   trong cùng giao dịch (R12.7; R9.15 giữ nguyên).
6. Guard: mục `decision_guards['studio.step.approval']` của ticket 06 thêm một điều kiện: yêu cầu của một điểm chờ có
   từ hai dòng `studio.step_approvals` trở lên (quy tắc `all`) chỉ nhận người quyết là `assignee_id` của chính dòng
   của nó, và một dòng như vậy vắng `assignee_id` thì không ai quyết được, cả hai trả 403 `permission_denied` (R12.4),
   để `assignee_id` vắng không bao giờ đọc thành `any` (failure-modes #7); mọi điều kiện của R9.2, R9.6, R9.8 giữ
   nguyên cho từng yêu cầu.
7. `StepWaitLookupPort` (workflow-engine/05 khai, workflow-engine/07 thêm kết quả vào hợp đồng, ticket 06 đáp ứng) trả
   thêm kết quả của điểm chờ, `approved`, `rejected` hay `pending`, tính sau `SELECT ... FOR UPDATE` trên các dòng
   `studio.step_approvals` của điểm chờ theo thứ tự `id`, để hai quyết định cuối đồng thời nối tiếp nhau (R12.5,
   R12.6); với `any`, kết quả là chính quyết định. Handler theo tiền tố `studio.step.` của workflow-engine đọc kết quả
   này, chỉ đặt dòng chờ `resolved` và lượt `queued` khi kết quả khác `pending`, và giữ dòng chờ `open` khi là
   `pending` (Phụ thuộc của spec; ADR-0112 (Accepted) quyết 7).
8. Lúc tiếp tục, Bước `all` đọc trạng thái n yêu cầu của điểm chờ, không đọc giá trị tiếp tục: cả n `approved` thì
   làn `approved` (R9.16), một `rejected` thì làn `rejected`, mọi trường hợp khác (còn yêu cầu chưa duyệt mà không ai
   từ chối) thì lượt `failed` với `error.code` `approval_incomplete` và không làn nào chạy (R12.8, R12.9).
9. Test: `packages/python/dw_studio/tests/workflows/test_control_nodes.py` cho ba loại điều khiển, tính chất vị trí
   và kiểm vị trí; `packages/python/dw_studio/tests/workflows/test_approval_all_rule.py` cho quy tắc `all`; ca đồng
   thời trên hai kết nối với thứ tự xen kẽ cố định, ca trigger và ca lượt chạy chờ rồi tiếp tục trong
   `make test-integration`.

## Tiêu chí chấp nhận

- [ ] R1.6 (WN11): Bước song song, Bước vòng lặp hay Thoát vòng lặp khai Khi lỗi `continue`, `route` hay `incident`
      → schema từ chối; schema đầu ra của ba loại không có `error`; thêm `route` vào Khi lỗi cho phép của
      `logic.loop@1` → test đỏ.
- [ ] R10.1 (WN31): `logic.parallel@1` với một làn → schema từ chối; hai làn cùng khóa, hay một khóa `Lane-1` → từ
      chối; hai làn khóa khác nhau đúng mẫu → nhận, và danh mục trả hai Nhánh ra theo hai khóa đó; bỏ kiểm khóa làn duy
      nhất → hai làn cùng khóa qua, test đỏ.
- [ ] R10.2 (WN22): tài liệu mang `logic.join@1` → `wf.unknown_node_type`, không niêm phong; đăng ký một mục
      `logic.join@1` vào registry → tài liệu đó niêm phong, test đỏ.
- [ ] R10.3 (WN23): `flow.stop` ở làn 2, hay trong làn lỗi của một Bước ở làn 2 → `wf.stop_in_parallel`, không niêm
      phong; `flow.stop` ở làn gốc sau Bước song song → niêm phong; đặt `ends_run` của `flow.stop@1` về sai → tài
      liệu có `flow.stop` trong làn niêm phong, test đỏ.
- [ ] R10.4 (WN24): Bước phê duyệt ở làn 2, kể cả trong thân một Bước vòng lặp nằm trong làn đó →
      `wf.wait_in_parallel`, không niêm phong; Bước phê duyệt trong thân một Bước vòng lặp ngoài mọi làn → niêm phong;
      đặt `opens_wait` của `human.approval@1` về sai → test đỏ.
- [ ] R11.1 (WN25): `logic.loop@1` thiếu `max_iterations`, `max_iterations = 0` hay thiếu `condition` → schema từ
      chối; `max_iterations = 1` → nhận; bỏ `max_iterations` khỏi danh sách khóa bắt buộc → test đỏ.
- [ ] R11.2 (WN31): Bước vòng lặp không mang làn `body` → `wf.router_not_total` (workflow-engine:R2.2); không mang
      làn `max_reached` → niêm phong; danh mục trả `max_reached` là Nhánh ra tùy chọn và `body` là bắt buộc; đặt `body`
      về Nhánh ra tùy chọn → tài liệu không mang làn `body` niêm phong, test đỏ.
- [ ] R11.3 (WN26): Thoát vòng lặp ở làn gốc, hay trong một `logic.switch` ngoài mọi vòng lặp, hay trong một làn song
      song, kể cả của một vòng lặp nằm trọn trong làn → `wf.break_outside_loop`, không niêm phong; trong làn `rejected`
      của một Bước phê duyệt ở thân → niêm phong; đặt `exits_loop` của `logic.break@1` về sai → test đỏ.
- [ ] R3.2: Bước ở làn 1 tham chiếu một Bước ở làn 2 → `wf.ref_not_dominating`; Bước kế tiếp sau Bước song song
      tham chiếu Bước đó → qua; Bước sau Bước vòng lặp tham chiếu một Bước của thân đứng trước mọi Thoát vòng lặp →
      qua (do-while), tham chiếu một Bước của thân đứng sau một Thoát vòng lặp có điều kiện → `wf.ref_not_dominating`;
      cây `draft/scope` ở các vị trí đó liệt kê đúng như vậy.
- [ ] R12.1 (WN31): `approval_rule` `all` và `any` → nhận; `k_of_n` hay `2` → schema từ chối; vắng khóa → Bước chạy
      như `any`, tài liệu lead mẫu của ticket 06 cho cùng kết quả như trước ticket này; bỏ tập giá trị cho phép của
      `approval_rule` → `k_of_n` qua và Bước chạy như `any`, test đỏ.
- [ ] R12.2 (WN29): Bước `all` giao A, B, C ở `live` → đúng 3 yêu cầu `studio.step.` cùng `subject_hash`, 3 dòng
      `studio.step_approvals` mang `assignee_id` A, B, C, 1 dòng chờ; worker chết sau khi mở rồi lượt được nhận lại →
      vẫn đúng 3 yêu cầu; chèn một dòng thứ hai cho A cùng điểm chờ → UNIQUE từ chối.
- [ ] R12.3 (WN28): C rời công ty trước lúc mở → Bước kết thúc với `no_approver` theo Khi lỗi, 0 yêu cầu được mở;
      người được giao thứ ba là một người dùng của công ty B trong lượt của công ty A → `no_approver`, 0 yêu cầu ở cả
      hai công ty; cho Bước bỏ C rồi mở hai yêu cầu → test đỏ.
- [ ] R12.4 (WN28): B quyết yêu cầu của A → 403 `permission_denied`, yêu cầu của A vẫn `pending`; A quyết yêu cầu
      của chính mình → nhận; một dòng `studio.step_approvals` của điểm chờ ba yêu cầu vắng `assignee_id` → A, B và C
      quyết yêu cầu đó đều 403, yêu cầu vẫn `pending`; gỡ điều kiện `assignee_id` khỏi guard, hay cho guard đọc dòng
      vắng `assignee_id` thành `any` → B duyệt hai phần, test đỏ.
- [ ] R12.5 (WN29): A duyệt → `pending`, dòng chờ `open`, lượt chờ; B duyệt → `pending`; C duyệt → `approved`; A, B
      duyệt rồi C từ chối → `rejected`; Bước `any` → kết quả là quyết định của yêu cầu duy nhất.
- [ ] R12.6 (WN29): sau A, hai giao dịch duyệt của B và C xen kẽ theo thứ tự cố định → đúng một lần quyết trả
      `approved`, dòng chờ sang `resolved` đúng một lần; bỏ khóa hàng → cả hai trả `pending` và dòng chờ kẹt `open`,
      test đỏ.
- [ ] R12.7 (WN30): A từ chối → `rejected`, yêu cầu của B và C `cancelled` trong cùng giao dịch; B quyết sau đó → bị
      từ chối, yêu cầu vẫn `cancelled`; cho trigger chỉ nghe `cancelled` như ticket 06 → yêu cầu của B còn `pending`,
      test đỏ.
- [ ] R12.8 (WN29): cả ba duyệt → làn `approved` chạy một lần, làn `rejected` không chạy; một người từ chối → làn
      `rejected` chạy, `tool.call` trong làn `approved` có 0 lời gọi.
- [ ] R12.9 (WN29): một handler giả đặt dòng chờ `resolved` ở lần duyệt đầu → lượt `failed` với `error.code`
      `approval_incomplete`, `tool.call` trong làn `approved` có 0 lời gọi; cho Bước đọc giá trị tiếp tục thay trạng
      thái các yêu cầu → làn `approved` chạy, test đỏ.
- [ ] R9.9: Bước `all` ở `simulate` với quyết định giả lập `approved` → làn `approved` chạy, 0 dòng
      `platform.approval_requests` và 0 dòng `platform.run_waits`.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/workflows/test_control_nodes.py packages/python/dw_studio/tests/workflows/test_approval_all_rule.py && make test-integration` xanh.

## Nguồn

- ADR-0112 (Accepted) quyết 2, 3, 4, 5, 7; spec: R1.6, R10, R11, R12.
- `packages/python/dw_platform/src/dw_platform/adapters/persistence/tables.py:217-235`; spec: R12.2
  (`approval_requests` giữ một trạng thái mỗi yêu cầu, nên mỗi người duyệt bắt buộc có một yêu cầu).
- `apps/api/src/dw_api/bootstrap/runtime.py:237-239`; spec: R12.4 (`decision_guards`).

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
