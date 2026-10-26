# 08 — Bước Quy trình con flow.subworkflow@1

Status: needs-triage
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

1. Mục `NodeTypeSpec` `flow.subworkflow@1`, nhãn "Quy trình con", trong registry của ticket 02
   (`packages/python/dw_studio/src/dw_studio/workflows/node_registry.py`):
    - cấu hình: `workflow` bắt buộc, chuỗi khớp `^[a-z][a-z0-9_]{1,39}$` (luật `api_name` của ADR-0109 (Accepted) quyết
      1), là `api_name` của Quy trình được gọi; Quy trình nào gọi được chờ Q10 của spec; `inputs` tùy chọn, đối tượng từ
      tên trường tới Biểu thức CEL; `additionalProperties: false`, nên khóa `version`, `live` hay mọi khóa khác bị từ
      chối, vì phiên bản con chỉ do lần gửi kiểm định ghim (R13.1).
    - đầu ra: `outputs`, đối tượng có kiểu theo khai `outputs` của phiên bản con mà lần gửi kiểm định ghim
      (ADR-0112 (Accepted) quyết 1); `outcomes`, danh sách chuỗi, tên các mục `outcomes[]` của lượt con đúng khi nó
      kết thúc (H-14); `error` chỉ khi Khi lỗi là `continue` hay `route` (R1.5, R13.2). Schema đầu ra dựng theo từng Bước từ khai
      của phiên bản con, như `ai.llm` dựng từ JSON Schema của công ty, nên `draft/scope` của ticket 03 liệt kê
      `outputs.<tên>` với kiểu của phiên bản con.
    - schema theo Bước: schema của `inputs` (bước 2) và schema đầu ra là một thuộc tính mới của `NodeTypeSpec`, một hàm
      của cấu hình và khai `inputs`, `outputs` của phiên bản con mà phụ thuộc của Bước trỏ tới; bảng
      thuộc-tính-tới-nơi-đọc của ticket 02 thêm dòng của nó, với nơi đọc là bộ kiểm khi gửi kiểm định, nơi cả kiểm kiểu
      của R13.6 lẫn cây `draft/scope` của R13.2 dựng (R1.4, WN15).
    - Nhánh ra: không, ngoài làn lỗi khi Khi lỗi là `route`.
    - `side_effect_level` `internal`; Khi lỗi cho phép `fail`, `continue` và `route`, không `incident` (R13.4); ba tính
      chất vị trí bắt buộc của ticket 02: `opens_wait` đúng, `ends_run` sai, `exits_loop` sai (R13.3).
    - bộ trích phụ thuộc: một phụ thuộc `artifact` cho `workflow`, `usage` `invoke`, `path` là con trỏ JSON tới
      `config/workflow` của Bước, mà bộ trích của loại `workflow` ghi vào `studio.dependencies` (workflow-engine:R1.3) và
      lần gửi kiểm định ghim phiên bản con từ đó (workflow-engine/09; ADR-0109 (Accepted) quyết 4, 9).
    - nhãn năng lực: tín hiệu A, B, C của phiên bản con đã ghim, bắc cầu qua closure của nó, như `ai.agent` mang tín hiệu
      của agent; Phân tích năng lực của compliance-pdpl/05 đọc nó, và một loại nó chưa biết tính đủ ba tín hiệu
      (ADR-0125 (Accepted) quyết 1, 2).
2. Kiểm khi gửi kiểm định, bằng mã của bảng `wf.*`, không mã mới: schema của `inputs` dựng theo từng Bước từ khai
   `inputs` của phiên bản con, như schema đầu ra, nên bộ kiểm của workflow-engine kiểm mỗi Biểu thức theo kiểu trường đó
   khai và trả `wf.type_mismatch` với con trỏ tới trường khi thiếu một trường bắt buộc, có một trường không khai hay một
   Biểu thức sai kiểu (R13.6; workflow-engine:R2.6); vị trí: bộ kiểm của workflow-engine/06 đọc `opens_wait` để trả
   `wf.wait_in_parallel` cho một Bước Quy trình con ở bất kỳ độ sâu nào trong làn song song, và cho nó trong thân vòng
   lặp ngoài mọi làn song song (R13.3; workflow-engine:R2.16).
3. Hook biên dịch và lúc chạy: `compile(config)` trả cấu hình đã kiểm cho trình biên dịch; Bước xin lượt con qua cửa xin
   lượt con của workflow-engine/09 với `inputs` đã tính, đúng khoá chống lặp mà wrapper nút dẫn (workflow-engine:R4.5;
   R13.7) và nguyên Chế độ chạy của lượt cha, không tự đặt chế độ (R13.5); khi điểm chờ `child_run` được giải, Bước đọc
   `outputs` và `outcomes` mà workflow-engine/09 chuyển; lượt con lỗi hay bị hủy thì Bước lỗi `child_run_failed` của
   workflow-engine/09 theo Khi lỗi của nó, mã có nhãn trong catalog mã lý do (H-12). Lần xin lượt con là tác dụng phụ
   duy nhất của Bước và chỉ đi qua cửa xin lượt con (R2.1); mô-đun của loại không chứa SQL, không gọi
   `RunRequestService` trực tiếp, không import adapter cụ thể (R2.2).
4. Test: `packages/python/dw_studio/tests/workflows/test_subworkflow_node.py` cho schema, đầu ra, Khi lỗi, ba tính chất,
   bộ trích và kiểm khi gửi kiểm định; ca lượt cha `simulate` có Quy trình con gửi `email.send` và ca worker chết sau
   khi xin lượt con chạy trong `make test-integration`, trên cửa xin lượt con thật của workflow-engine/09.

## Tiêu chí chấp nhận

- [ ] R1.4 (WN15): thuộc tính schema theo Bước của mục `flow.subworkflow@1` có đúng một nơi đọc trong bảng
      thuộc-tính-tới-nơi-đọc, là bộ kiểm khi gửi kiểm định; xóa dòng của nó khỏi bảng → test bảng đỏ.
- [ ] R13.1 (WN32): cấu hình có `workflow` đúng mẫu và `inputs` → nhận; thiếu `workflow`, `workflow` là `Lead-Intake`,
      hay có khóa `version` hoặc `live` → schema từ chối; bộ trích của loại trả đúng một phụ thuộc `artifact` cho
      `workflow` với `usage` `invoke` và con trỏ tới Bước; bỏ `additionalProperties: false` → khóa `version` qua, test đỏ.
- [ ] R13.1 (WN35): tenant A gửi kiểm định một Quy trình mà Bước Quy trình con nêu `api_name` chỉ có ở tenant B → không niêm
      phong, không phụ thuộc nào trỏ tới thành phần của tenant B và 0 dòng `worker_runs` ở tenant B; tenant A cũng có
      `api_name` đó → phụ thuộc và lượt con trỏ tới thành phần của tenant A; chạy phép phân giải phụ thuộc dưới một vai
      bỏ qua RLS → phụ thuộc trỏ tới thành phần của tenant B, test đỏ (CLAUDE.md, Tenancy and authorization).
- [ ] R13.2: một Quy trình con khai `outputs` `{score: int}` và hai mục `outcomes[]` → `draft/scope` ở Bước sau Bước
      Quy trình con liệt kê `outputs.score` kiểu `int` và `outcomes` kiểu danh sách chuỗi; Bước khai `fail` không công
      bố `error`, Bước khai `route` công bố `error` mà các Bước của làn lỗi tham chiếu được; cho schema đầu ra là một
      đối tượng cố định thay vì dựng từ khai `outputs` của phiên bản con → `outputs.score` không có trong `draft/scope`,
      test đỏ.
- [ ] R2.1: một lần chạy Bước Quy trình con → đúng một lời gọi tới cửa xin lượt con và không lời gọi `ToolExecutor`,
      `RecordsPort` hay bộ phân giải model nào; cho mô-đun gọi thẳng `RunRequestService` thay cửa xin lượt con → test
      đỏ.
- [ ] R2.2: test kiến trúc: mô-đun của `flow.subworkflow@1` không import `RunRequestService`, adapter cụ thể hay SDK
      nào và không có SQL; cho mô-đun ghi `platform.worker_runs` bằng SQL → test kiến trúc đỏ.
- [ ] R13.3 (WN33): Bước Quy trình con ở làn 2 của một Bước song song, hay trong thân một Bước vòng lặp nằm trong làn
      đó → `wf.wait_in_parallel`, không `wf.stop_in_parallel`, không niêm phong; cùng Bước trong thân một Bước vòng lặp
      ngoài mọi làn → niêm phong; đặt `opens_wait` của `flow.subworkflow@1` về sai → tài liệu có Quy trình con trong làn
      niêm phong, test đỏ.
- [ ] R13.4 (WN11): Bước Quy trình con khai Khi lỗi `incident` → schema từ chối; `fail`, `continue` và `route` → nhận;
      thêm `incident` vào Khi lỗi cho phép của mục → `incident` qua, test đỏ.
- [ ] R13.5 (WN34): lượt cha `simulate` gọi một Quy trình con có `tool.call` `email.send` của `smtp@1.0.0` → dòng lượt
      con có `run_mode` `simulate`, 0 email rời egress; cho Bước chuyển `live`, hay bỏ chuyển chế độ để cửa dùng mặc
      định → test đỏ.
- [ ] R13.6 (WN32): `inputs` thiếu một trường bắt buộc của khai `inputs` của phiên bản con, mang một trường lạ, hay có
      Biểu thức trả `string` cho một trường `int` → `wf.type_mismatch` với con trỏ tới trường đó, không niêm phong;
      `inputs` đủ và đúng kiểu → niêm phong; bỏ kiểm `inputs` theo khai của phiên bản con → ba ca đầu niêm phong, test
      đỏ.
- [ ] R13.7: worker chết sau khi lượt con được xin mà trước checkpoint của lượt cha, rồi lượt cha được nhận lại → đúng
      một lượt con cho Bước đó và lượt cha chờ đúng lượt con ấy; cho Bước dựng khoá khác → hai lượt con, test đỏ.
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
