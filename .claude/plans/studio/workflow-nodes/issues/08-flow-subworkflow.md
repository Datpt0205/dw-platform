# 08 — Bước Quy trình con flow.subworkflow@1

Status: ready-for-agent
Blocked by: 02, 03, 07, .claude/plans/studio/workflow-engine/issues/09-quy-trinh-con.md
Area: studio
Yêu cầu: R1.4, R2.1, R2.2, R13.1, R13.2, R13.3, R13.4, R13.5, R13.6, R13.7, WN11, WN15, WN32, WN33, WN34, WN35

## Mục tiêu

Bậc B của W1 (V4.33): loại `flow.subworkflow@1` trong `NodeTypeRegistry`, để người dựng gọi một Quy trình dùng chung
làm Quy trình con, lượt cha chờ lượt con ở một điểm chờ `child_run` rồi đọc `outputs` và `outcomes` có kiểu của nó;
Bước không chọn phiên bản con, không bao giờ nằm trong làn song song, không cho lượt con của một lượt `simulate` chạy
`live` và không xin lượt con thứ hai khi chạy lại, với tác dụng phụ duy nhất là lần xin lượt con qua cửa xin lượt con
(workflow-nodes R1.4, R2.1, R2.2, R13.1, R13.2, R13.3, R13.4, R13.5, R13.6, R13.7, WN11, WN15, WN32, WN33, WN34,
WN35). Lượt con (ghim lúc gửi kiểm định, lồng tối đa 3 cấp, chu trình bị từ chối, hủy dây chuyền trong ≤ 5 giây,
điểm chờ `child_run`) là của workflow-engine/09. Không ticket thí điểm nào chờ ticket này.

## Việc cần làm

1. Mục `NodeTypeSpec` `flow.subworkflow@1`, nhãn "Quy trình con", trong `studio_node_types` của ticket 03
   (`packages/python/dw_studio/src/dw_studio/workflows/node_registry.py`):
    - cấu hình: `workflow` bắt buộc, chuỗi khớp `^[a-z][a-z0-9_]{1,39}$` (luật `api_name` của ADR-0109 (Accepted) quyết
      1), là `api_name` của Quy trình được gọi, một Quy trình khai mục `triggers[]` kind `call` (spec R13.1;
      workflow-engine:R2.21; Đạt, Q-h6); `inputs` tùy chọn, đối tượng từ tên trường tới Biểu thức CEL (`x-dw-cel`);
      `additionalProperties: false`, nên khóa `version`, `live` hay mọi khóa khác bị từ chối, vì phiên bản con chỉ do lần
      gửi kiểm định ghim (R13.1).
    - đầu ra: `outputs`, đối tượng có kiểu theo khai `outputs` của phiên bản con; `outcomes`, danh sách chuỗi, tên các
      mục `outcomes[]` của lượt con đúng khi nó kết thúc (H-14); `error` chỉ khi Khi lỗi là `continue` hay `route` (R1.5,
      R13.2).
    - Kiểu đầu ra theo phụ thuộc, đúng cơ chế của ticket 03 bước 4 (mục cuối), không thêm thuộc tính nào vào
      `NodeTypeSpec`: seam Studio đưa cho môi trường biểu thức ánh xạ `node_id → schema đầu ra` dựng từ khai `outputs` của
      phiên bản con mà phụ thuộc phân giải: lúc gửi kiểm định là phiên bản niêm phong ghim, ở lưu nháp và `draft/scope`
      là phiên bản `live` của Quy trình được gọi lúc gọi. Danh mục nêu đầu ra của loại là `dyn`, nên `catalogue_hash`
      không đổi theo Quy trình con nào.
    - Khai `inputs` và `outputs` của tài liệu (ADR-0112 (Accepted) quyết 1) là hai khóa mà workflow-engine/09 thêm vào
      mô hình tài liệu cùng kind `call`, nơi đầu tiên đọc chúng: mỗi khóa là đối tượng từ tên trường tới
      `{type, required}`, kiểu theo bảng ánh xạ kiểu của ticket 03. Một trường `required: false` là `optional[T]` trong cây
      kiểu, đọc an toàn bằng `has()` (ticket 03 bước 1).
    - Phiên bản con nào: lúc gửi kiểm định, phiên bản `live` của Quy trình được gọi được ghim (ADR-0109 (Accepted) quyết
      9); một lượt mô phỏng của nháp cha ghim phiên bản `live` của con lúc xin lượt, đúng phiên bản mà `draft/scope` và
      lưu nháp dùng, và kiểm của R13.6 chạy dưới quyền đọc của người xin lượt. Quy trình được gọi chưa có phiên bản `live`
      → `wf.ref_unknown` (lưu nháp cảnh báo, gửi kiểm định và xin lượt mô phỏng từ chối): phát hành con trước cha.
    - Nhánh ra: không, ngoài làn lỗi khi Khi lỗi là `route`.
    - `side_effect_level` `internal`; `block` `none`; `ends_run` và `exits_loop` sai (workflow-engine/01); `opens_wait`
      đúng (khai cùng trường khi workflow-engine/06 thêm nó, hay ngay nếu trường đã có) (R13.3); `allowed_on_error`
      (ticket 03) `fail`, `continue`, `route`, không bao giờ `incident`, kể cả khi workflow-engine/07 đưa `incident` vào
      mô hình (R13.4).
    - `dependencies(config)` (trường của workflow-engine/01): một phụ thuộc `artifact` cho `workflow`, `usage`
      `invoke`, `path` là con trỏ JSON tới `config/workflow` của Bước, mà bộ trích của loại `workflow` ghi vào
      `studio.dependencies` (workflow-engine:R1.3) và lần gửi kiểm định ghim phiên bản con từ đó (workflow-engine/09;
      ADR-0109 (Accepted) quyết 4, 9). Phụ thuộc phân giải dưới quyền đọc của người gửi kiểm định, trong công ty của
      người đó: Quy trình không có, hay người đó không đọc được (`studio.workflows.read`, kiểm theo workspace sở hữu của
      Quy trình được gọi) → `wf.ref_unknown` (mã wf-lite đã có) có con trỏ tới `config/workflow`; có và đọc được mà không
      khai kind `call` → `wf.subworkflow_not_callable` của workflow-engine/09. Quy trình là định nghĩa toàn tenant, nên
      một Quy trình của workspace khác cùng công ty gọi được; lượt con chạy trong workspace của lượt cha, với chủ thể chạy
      của lượt cha (workflow-engine:R8.1).
    - Nhãn năng lực (ADR-0125 (Accepted) quyết 1, 2): tín hiệu của phiên bản con đã ghim, bắc cầu qua closure của nó,
      như `ai.agent` mang tín hiệu của agent, với C chỉ khi một tác động ra ngoài của con không bị một phê duyệt bên
      trong con chặn, vì phân tích của phiên bản con đã chạy lúc con gửi kiểm định. Nhãn của loại này là một giá trị đánh
      dấu "theo phiên bản con", không phải ba tín hiệu tĩnh; Phân tích năng lực của compliance-pdpl/05, chủ của cách đọc,
      đọc kết quả phân tích đã lưu của phiên bản con đã ghim, như với `ai.agent`. Trường nhãn năng lực vào
      `NodeTypeSpec` cùng phân tích của compliance-pdpl/05 (ticket 02 bước 2): ticket nào đến sau trong hai ticket khai
      giá trị cho `flow.subworkflow@1`; trước đó Phân tích năng lực coi loại này là loại chưa biết, tính đủ ba tín hiệu.
2. Kiểm khi gửi kiểm định, bằng mã của bảng `wf.*`, không mã mới, ở seam Studio của ticket 03 (cần khai của phiên bản
   con): mỗi Biểu thức của `inputs` kiểm theo kiểu trường đó khai, và thiếu một trường bắt buộc, có một trường không
   khai hay một Biểu thức sai kiểu → `wf.type_mismatch` với con trỏ tới trường (R13.6; workflow-engine:R2.6); vị trí: bộ
   kiểm của workflow-engine/06 đọc `opens_wait` để trả `wf.wait_in_parallel` cho một Bước Quy trình con ở bất kỳ độ sâu
   nào trong làn song song, và cho nó trong thân vòng lặp ngoài mọi làn song song (R13.3; workflow-engine:R2.16).
3. Hook biên dịch và lúc chạy: `compile(config)` trả cấu hình đã kiểm cho trình biên dịch; Bước xin lượt con qua cửa xin
   lượt con của workflow-engine/09 với `inputs` đã tính, đúng khoá chống lặp mà wrapper nút dẫn (workflow-engine:R4.5;
   R13.7) và nguyên Chế độ chạy của lượt cha, không tự đặt chế độ (R13.5); khi điểm chờ `child_run` được giải, Bước đọc
   `outputs` và `outcomes` mà workflow-engine/09 chuyển. Trước khi xin, một Biểu thức của trường `required` ra `null` →
   Bước lỗi `expression_error` theo Khi lỗi, không xin lượt con; trường tùy chọn ra `null` thì bỏ khỏi `inputs`. Lượt
   con lỗi hay bị hủy thì Bước lỗi `child_run_failed` của workflow-engine/09 theo Khi lỗi của nó; `error` giữ dạng
   `{code, message}` của ticket 02, và mã lỗi của lượt con đọc ở lịch sử chạy của lượt con, không ở môi trường biểu
   thức; nhãn của `child_run_failed` là của workflow-engine/09 (H-12), ticket này không thêm nhãn. Với `continue`, kênh
   của Bước là
   `{status: "error", error}` (ADR-0112 (Accepted) quyết 5), không có `outputs`, nên một Biểu thức sau đó đọc
   `outputs.<tên>` mà không `has()` ra `null` và lỗi theo luật của ticket 03, không bao giờ một giá trị mặc định. Lần
   xin lượt con là tác dụng phụ duy nhất của Bước và chỉ đi qua cửa xin lượt con (R2.1); mô-đun của loại không chứa
   SQL, không gọi `RunRequestService` trực tiếp, không import adapter cụ thể (R2.2).
4. Test: `packages/python/dw_studio/tests/workflows/test_subworkflow_node.py` cho schema, đầu ra, Khi lỗi, ba tính chất,
   bộ trích và kiểm khi gửi kiểm định; ca lượt cha `simulate` có Quy trình con gửi `email.send` và ca worker chết sau
   khi xin lượt con chạy trong `make test-integration`, trên cửa xin lượt con thật của workflow-engine/09.

## Tiêu chí chấp nhận

- [ ] R1.4 (WN15): mục `flow.subworkflow@1` khai mọi trường bắt buộc của `NodeTypeSpec` lúc đó; bỏ `opens_wait` hay
      `dependencies` khỏi mục → `build_node_registry` lỗi; ticket này không thêm thuộc tính nào, nên bảng `READERS` không
      đổi.
- [ ] R13.1 (WN32): cấu hình có `workflow` đúng mẫu và `inputs` → nhận; thiếu `workflow`, `workflow` là `Lead-Intake`,
      hay có khóa `version` hoặc `live` → schema từ chối; bộ trích của loại trả đúng một phụ thuộc `artifact` cho
      `workflow` với `usage` `invoke` và con trỏ tới Bước; bỏ `additionalProperties: false` → khóa `version` qua, test đỏ.
- [ ] R13.1 (WN35): tenant A gửi kiểm định một Quy trình mà Bước Quy trình con nêu `api_name` chỉ có ở tenant B →
      `wf.ref_unknown`, không niêm phong, không phụ thuộc nào trỏ tới thành phần của tenant B và 0 dòng `worker_runs` ở
      tenant B; tenant A cũng có `api_name` đó → phụ thuộc và lượt con trỏ tới thành phần của tenant A; Quy trình cùng
      công ty mà người gửi không đọc được → `wf.ref_unknown`; chạy phép phân giải phụ thuộc dưới một vai bỏ qua RLS → phụ
      thuộc trỏ tới thành phần của tenant B, test đỏ (CLAUDE.md, Tenancy and authorization).
- [ ] R13.2: một Quy trình con khai `outputs` `{score: int}` và hai mục `outcomes[]` → `draft/scope` ở Bước sau Bước
      Quy trình con liệt kê `outputs.score` kiểu `int` (theo phiên bản `live` của con) và `outcomes` kiểu danh sách
      chuỗi; Bước khai `fail` không công bố `error`, Bước khai `route` công bố `error` mà các Bước của làn lỗi tham chiếu
      được; cho schema đầu ra là một đối tượng cố định thay vì dựng từ khai `outputs` của phiên bản con → `outputs.score`
      không có trong `draft/scope`, test đỏ.
- [ ] R2.1: một lần chạy Bước Quy trình con → đúng một lời gọi tới cửa xin lượt con và không lời gọi `ToolExecutor`,
      `RecordsPort` hay bộ phân giải model nào; cho mô-đun gọi thẳng `RunRequestService` thay cửa xin lượt con → test
      đỏ.
- [ ] R2.2: test kiến trúc: mô-đun của `flow.subworkflow@1` không import `RunRequestService`, adapter cụ thể hay SDK
      nào và không có SQL; cho mô-đun ghi `platform.worker_runs` bằng SQL → test kiến trúc đỏ.
- [ ] R13.3 (WN33): Bước Quy trình con ở làn 2 của một Bước song song, hay trong thân một Bước vòng lặp nằm trong làn
      đó → `wf.wait_in_parallel`, không `wf.stop_in_parallel`, không niêm phong; cùng Bước trong thân một Bước vòng lặp
      ngoài mọi làn → niêm phong; đặt `opens_wait` của `flow.subworkflow@1` về sai → tài liệu có Quy trình con trong làn
      niêm phong, test đỏ.
- [ ] R13.4 (WN11): Bước Quy trình con khai Khi lỗi `incident` → bị từ chối (`wf.config_invalid`, hay `wf.schema_invalid`
      khi mô hình chưa nhận `incident`); `fail`, `continue` và `route` → nhận; thêm `incident` vào Khi lỗi cho phép của
      mục → `incident` qua, test đỏ.
- [ ] R13.5 (WN34): lượt cha `simulate` gọi một Quy trình con có `tool.call@2` `email.send` của `smtp@1.0.0` → dòng lượt
      con có `run_mode` `simulate`, 0 email rời egress; cho Bước chuyển `live`, hay bỏ chuyển chế độ để cửa dùng mặc
      định → test đỏ.
- [ ] R13.6 (WN32): `inputs` thiếu một trường bắt buộc của khai `inputs` của phiên bản con, mang một trường lạ, hay có
      Biểu thức trả `string` cho một trường `int` → `wf.type_mismatch` với con trỏ tới trường đó, không niêm phong;
      `inputs` đủ và đúng kiểu → niêm phong; bỏ kiểm `inputs` theo khai của phiên bản con → ba ca đầu niêm phong, test
      đỏ.
- [ ] R13.7: worker chết sau khi lượt con được xin mà trước checkpoint của lượt cha, rồi lượt cha được nhận lại → đúng
      một lượt con cho Bước đó và lượt cha chờ đúng lượt con ấy; cho Bước dựng khoá khác → hai lượt con, test đỏ. Lượt
      con lỗi với Bước khai `route` → làn lỗi chạy, `steps.x.error.code` là `child_run_failed`. Biểu thức của một trường
      `required` ra `null` lúc chạy → `expression_error`, 0 lượt con.
- [ ] R13.1: Quy trình đọc được mà không khai kind `call` → `wf.subworkflow_not_callable`; Quy trình chưa có phiên bản
      `live` → `wf.ref_unknown` lúc gửi kiểm định và lúc xin lượt mô phỏng nháp cha; lượt mô phỏng nháp cha chạy đúng
      phiên bản `live` của con lúc xin.
- [ ] Xong: `uv run pytest packages/python/dw_studio/tests/workflows/test_subworkflow_node.py && make test-integration` xanh.

## Nguồn

- ADR-0109 (Accepted) quyết 1, 4, 9; ADR-0113 (Accepted) quyết 4, 9; spec: R13.1, R13.3, R13.5.
- ADR-0112 (Accepted) quyết 1, 2, 6; spec: R2.1 (một tác dụng phụ mỗi Bước, qua cửa xin lượt con), R13.2, R13.5.
- ADR-0125 (Accepted) quyết 1, 2; spec: Phụ thuộc (nhãn năng lực của loại).
- `packages/python/dw_agent_runtime/src/dw_agent_runtime/contracts.py:19`; spec: Trong phạm vi (`side_effect_level`
  `internal` trong vốn từ có sẵn).
- workflow-engine:R1.3, workflow-engine:R2.6, workflow-engine:R2.16, workflow-engine:R4.5, workflow-engine:R6.19;
  `.claude/plans/studio/workflow-engine/issues/09-quy-trinh-con.md`; spec: R13.

## Comments

- 2026-10-25 (agent): tạo ở lượt h theo V4.33 của Đạt (bậc B của W1), số và đường dẫn theo mục C của lượt: chờ ticket
  02 (ba tính chất vị trí bắt buộc) và workflow-engine/09 (lượt con, điểm chờ `child_run`, cửa xin lượt con), cộng hai
  cạnh ngoài mục C: ticket 03, vì R13.2 và R13.6 dùng cây kiểu và route `draft/scope` của nó, và ticket 07, vì R13.3
  dựng tài liệu có `logic.parallel@1` và `logic.loop@1` mà ticket đó đăng ký (đã chạy g.py trên cây hiện tại cộng các
  cạnh của lượt: không vòng, chuỗi dài nhất vẫn 18, marketing-pilot/03 vẫn ở độ sâu 15, ticket này ở độ sâu 17 và không
  ticket thí điểm nào chờ nó). Cấu hình, đầu ra, Khi lỗi không `incident`, `side_effect_level` `internal` và nhãn năng
  lực theo dòng Quyết định 25/10/2026 của spec (agent, tạm); Q10 của spec (Quy trình nào gọi được làm Quy trình con)
  chặn R13.1.
- 2026-10-26 (agent): lượt h, rà lại: R2.1 của spec nay nêu cửa xin lượt con là cửa của Bước Quy trình con (V4.33), nên
  ticket nhận R2.1, R2.2 với một test kiến trúc có ca âm; tiêu chí của R13.2 thêm ca âm (schema đầu ra cố định thì
  `draft/scope` thiếu `outputs.score`); R13.1 thêm ca âm liên tenant cho tham chiếu `api_name` mới (CLAUDE.md, Tenancy
  and authorization), chạy trên lần gửi kiểm định và cửa xin lượt con thật, không nêu mã lỗi của bên phân giải. Kết quả
  ghim cho chính Bước Quy trình con ở lần thử của ca kịch bản là việc của wrapper nút (workflow-engine:R4.27; H-18),
  không của ticket này. Không thêm cạnh.
- 2026-10-26 (agent): áp Q-h6 của Đạt (theo khuyến nghị): R13.1 nay chỉ nhận Quy trình khai kind `call`; kiểm và kind do
  workflow-engine/09 dựng, ticket này đã chờ nó, nên không thêm cạnh và không thêm bước.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): gate `checking-plan-readiness` (builder check; không route, không
  migration). Lượt đầu: 0 CRITICAL, 8 HIGH, đều sửa ở ticket này và spec (Quyết định 4/11/2026):
    - Nhãn năng lực: một nút mang đủ ba tín hiệu của closure con, hay tác động đã được duyệt trong con thì thôi: nay C
      chỉ khi tác động của con không bị chặn trong con.
    - Trường nhãn năng lực mà không ai đọc khi compliance-pdpl/05 chưa có: nay vào cùng ticket đến sau trong hai.
    - `draft/scope` lấy kiểu từ phiên bản nào của con: phiên bản `live`, như ticket 03 bước 4.
    - "Thuộc tính mới của `NodeTypeSpec`" cho schema theo Bước, ở lõi không thấy phiên bản con: nay là seam Studio của
      ticket 03, không thuộc tính mới, danh mục nêu `dyn`.
    - Khai `inputs` của phiên bản con là khóa nào: `inputs`, `outputs` của tài liệu, workflow-engine/09 thêm.
    - Gọi Quy trình của workspace khác, và quyền của người gửi trên Quy trình con: nay toàn tenant, cần
      `studio.workflows.read`, không có thì `wf.ref_unknown`.
    - Đầu ra khi lượt con lỗi dưới `continue` hay `route`, và mã lỗi của con: nay `child_error_code`.
    - Ai thêm nhãn của `child_run_failed`: workflow-engine/09.

    Cùng đó: "registry của ticket 02" thành `studio_node_types` của ticket 03; ba tính chất vị trí đến từ
    workflow-engine/01 và 06; `block`, `allowed_on_error` khai; `tool.call@2` của ticket 06 trong ca R13.5.

- 2026-11-04 (agent): MEDIUM của gate, cho người làm và cho `checking-plan-consistency`:
    - (a) Một Biểu thức đọc `outputs.<tên>` của Bước khai `continue` mà không `has()` vẫn niêm phong được; lúc chạy nó
      lỗi khi lượt con lỗi. Người dựng bọc `has()` hay dùng `route`.
    - (b) Cha đã phát hành vẫn gọi phiên bản con cũ tới khi cha gửi kiểm định lại (ADR-0109 (Accepted) quyết 9); đúng
      thiết kế, nên ghi ở trợ giúp của builder.
    - (c) workflow-engine/09 cần thêm `inputs`, `outputs` vào mô hình tài liệu cùng kind `call`, với dạng
      `{tên: {type, required}}`.
    - (d) Dựng cha và con cùng lúc: con phải có phiên bản `live` trước khi cha gửi kiểm định hay chạy mô phỏng.
    - (e) compliance-pdpl/05 đọc nhãn "theo phiên bản con" của `flow.subworkflow@1` từ kết quả phân tích đã lưu của con.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): lượt xác nhận (builder check mới) tìm 8 câu, sửa theo khuyến nghị:
  phiên bản con của lượt mô phỏng nháp cha; con chưa có `live`; mã lỗi của con không vào `error`; nhãn năng lực là một
  giá trị đánh dấu do compliance-pdpl/05 đọc; workspace của lượt con và của phép kiểm quyền đọc; `inputs` `null` lúc
  chạy; `wf.subworkflow_not_callable`; đầu ra tùy chọn của con là `optional[T]`. Không còn CRITICAL hay HIGH.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
