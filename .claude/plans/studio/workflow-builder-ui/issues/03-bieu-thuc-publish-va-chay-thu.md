# 03 — Ô biểu thức, lỗi tại chỗ, gửi kiểm định, chạy mô phỏng và màn lượt chạy

Status: ready-for-agent
Blocked by: 02, .claude/plans/studio/workflow-nodes/issues/03-pham-vi-bien-va-buoc-logic.md, .claude/plans/studio/workflow-triggers/issues/01-so-kich-hoat-chay-tay-va-danh-tinh.md, .claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md, .claude/plans/studio/agent-lifecycle/issues/03-hop-dong-vong-doi-va-niem-phong.md
Area: studio
Yêu cầu: R3.1, R3.2, R3.3, R3.4, R3.5, R3.6, R3.7, R3.8, R3.9, R3.10, R3.11, R3.12, R3.13, R3.14, R3.15, R3.16, R3.17, R3.18, R3.19, R3.20, BU2, BU3, BU5, BU6, BU9, BU15, BU16, BU17

## Mục tiêu

Ô Biểu thức có Chọn biến có kiểu kiểm ở máy chủ, lỗi kiểm gắn về đúng Bước, nút gửi kiểm định nêu lý do
khi khóa và không tự phát hành, trang chỉ đọc khi một Bản ứng viên còn chờ, bản Nháp mới chỉ mở khi người dựng bấm Tạo
bản Nháp, và chạy mô phỏng với một lựa chọn duyệt hay từ chối cho mỗi Bước phê duyệt, kết quả hiện trên cùng Sơ đồ theo
lần lặp và làn, che theo bảo mật trường, cho người dựng đã xin lượt đó; cùng Sơ đồ chỉ đọc có lớp phần khác so với bản
Đang dùng theo id Bước, mà màn duyệt phát hành của agent-lifecycle/07 dùng (workflow-builder-ui R3.1, R3.2, R3.3, R3.4,
R3.5, R3.6, R3.7, R3.8, R3.9, R3.10, R3.11, R3.12, R3.13, R3.14, R3.15, R3.16, R3.17, R3.18, R3.19, R3.20, BU2, BU3,
BU5, BU6, BU9, BU15, BU16, BU17).

## Việc cần làm

1. Ô Biểu thức: Chọn biến chèn đường dẫn có kiểu từ cây `GET /api/v1/studio/workflows/{id}/draft/scope?node=`
   (chỉ Bước trội); kiểm qua `POST /api/v1/studio/expressions/check` khi rời ô; hiện kiểu; bỏ qua phím
   khi `isComposing`. Không nhúng thư viện CEL vào bundle — mọi tính toán ở máy chủ.
2. Lỗi tại chỗ: huy hiệu lỗi trên Bước (chữ và màu, không chỉ màu); lỗi trường qua antd `Form.setFields`;
   ngăn kéo "Còn N lỗi" (`role="status"`); bấm một lỗi đưa focus tới Bước. Lỗi lấy từ 422 của máy chủ: mỗi phần tử
   `errors[]` của phong bì ADR-0108 (Accepted) quyết 1 mang `pointer` (JSON pointer vào tài liệu, chính `path` của bộ
   kiểm, ADR-0112 (Accepted) quyết 3) và `code`; một hàm thuần của `workflow-graph.ts` giải `pointer` ra id Bước sâu nhất
   chứa nó (bước con trong làn thắng Bước cha). Lỗi không nằm dưới Bước nào (`/limits`, `/variables`, `/bindings`) hiện
   trong ngăn kéo dưới "Quy trình", được đếm vào N, không gắn vào thẻ nào.
3. Nút Gửi kiểm định: gọi route gửi kiểm định của agent-lifecycle (agent-lifecycle:R2.1) với `If-Match` là ETag của
   Nháp đã đọc (R3.9; agent-lifecycle:R2.12, agent-lifecycle:R2.13), như tự lưu của ticket 02; 412 thì giữ nội dung
   đang gõ và mời tải lại; 409 `candidate_exists`, khi một tab khác đã gửi chính bản Nháp đó (agent-lifecycle:R1.3), thì
   đọc lại giai đoạn và vào trạng thái chỉ đọc của bước 6; khi bị khóa, nêu lý do; không có đường nào trong trang gọi
   phát hành. Nút khóa, kèm lý do, khi một lần lưu đang bay, khi lần lưu cuối thất bại, và sau một 422 tới lần lưu thành
   công kế tiếp; khi tự lưu mới chờ debounce thì nút bấm được, và bấm thì trang lưu ngay trước, rồi gửi với ETag mà lần
   lưu đó trả, để không bao giờ niêm phong một nội dung cũ hơn nội dung trên trang. Huy hiệu lỗi và ngăn kéo của một 422
   giữ tới lần lưu thành công kế tiếp; `pointer` giải ra id Bước ngay lúc nhận, nên chèn hay dời Bước sau đó không làm
   lỗi nhảy sang Bước khác. `PUT .../draft` không trả cảnh báo nào, nên ngăn kéo chỉ có lỗi của 422. Gửi thành công thì trang đọc lại giai đoạn và vào
   trạng thái chỉ đọc của bước 6. Giai đoạn vòng đời hiện ở đầu trang, đọc từ `stage` của phiên bản ở bước 6, nguồn duy
   nhất của giai đoạn trên trang. Mọi lời gọi khác đọc bản Nháp đã lưu (chạy mô phỏng của bước 4, `draft/scope` và
   `/expressions/check` của bước 1) cũng xả tự lưu trước khi gọi.
4. Chạy mô phỏng: biểu mẫu sinh từ JSON Schema ở `inputs` của tài liệu (ADR-0112 (Accepted) quyết 1), hay một ô JSON
   "Payload mẫu" khi tài liệu không khai `inputs`, chỉ có khi trang ở trạng thái sửa bản Nháp (bước 6), khóa với lý do
   khi `/me` không có `studio.workflows.test` (máy chủ vẫn trả 403, và trang hiện lỗi đó), cộng một lựa chọn bắt buộc
   "Duyệt" hay "Từ chối" (antd
   `Radio.Group`, nhãn từ khóa thông điệp) cho mỗi Bước phê duyệt của Nháp, gửi thành `simulated_decisions` theo id Bước
   (workflow-triggers:R2.7); trang chỉ gửi `simulate` ở W1, tới route `.../versions/{version_id}/test-runs` của
   workflow-triggers với id của phiên bản Nháp đang mở (route nhận bản `draft` ở chế độ `simulate`, bản kê ghim mã băm
   tạm của nội dung nháp, workflow-triggers:R2.3, tenant-config:R6.1; người gọi cần `studio.workflows.test`; route trả
   422 với `live`, với `test` tới W2, khi thiếu quyết định cho một Bước phê duyệt, và khi bộ kiểm khi gửi kiểm định báo
   lỗi `wf.*` trên nội dung nháp, ADR-0112 (Accepted) quyết 3, workflow-triggers:R2.2, workflow-triggers:R2.6,
   workflow-triggers:R2.8, workflow-triggers:R2.9). Mỗi lỗi `wf.*` của 422 đó gắn về đúng Bước như bước 2. Không Bước
   phê duyệt nào của lượt mô phỏng chờ người quyết (workflow-nodes:R9.9). Kết quả mở trên màn lượt chạy của bước 7.
5. Che theo bảo mật trường: máy chủ che, trang không che. `GET /api/v1/runs/{run_id}/steps` của telemetry-and-audit
   thay giá trị của trường người xem không đọc được bằng dấu `Đã ẩn` tại chỗ (telemetry-and-audit:R3.3, telemetry-and-audit:R4.4;
   ADR-0106 (Accepted) quyết 4), nên giá trị không bao giờ tới trình duyệt; trang vẽ dấu đó thành chữ "Đã ẩn" cùng biểu
   tượng trên màn lượt chạy (bước 7, nơi duy nhất hiện kết quả Bước), ở mọi lần lặp và mọi làn, và không có nhánh nào
   tự che hay tự bỏ che.
6. Trạng thái của trang đọc từ `GET /api/v1/studio/artifacts/{id}/versions` đã dựng của tenant-config/02 (mỗi phiên bản
   mang `stage`; `apps/api/src/dw_api/routes/v1/studio_artifacts.py:351`): phiên bản chưa phát hành ở `draft` → sửa
   (ticket 02); ở `evaluating` hay `awaiting_approval` → chỉ đọc của bước này; không có phiên bản chưa phát hành → chỉ
   đọc kèm "Tạo bản Nháp" của bước 8 trên phiên bản `live`, hay phiên bản có `version_no` lớn nhất khi không có `live`;
   404 của `GET .../draft` không bao giờ được đọc thành một trạng thái. Bản ứng viên đang chờ: khi giai đoạn là
   `evaluating` hay `awaiting_approval`, Sơ đồ,
   biểu mẫu và ô Biểu thức chỉ đọc, tự lưu của ticket 02 tắt, và trang không gọi `PUT .../draft` hay `POST .../draft` của
   tenant-config, vì thành phần không có bản Nháp nào khi một Bản ứng viên còn chờ (tenant-config:R2.20,
   tenant-config:R2.22). Một thông báo (khóa thông điệp) nêu "rút bản đang chờ về Nháp để sửa" kèm nút Rút về Nháp gọi
   `POST .../withdraw` của agent-lifecycle (agent-lifecycle:R2.4) chỉ khi người dựng bấm; route đó kiểm khóa gửi của loại,
   nên 403 giữ trang chỉ đọc và nêu lý do; rút xong, trang đọc lại bản Nháp cùng ETag của nó.
7. Màn lượt chạy (R3.11, R3.12): cùng Sơ đồ của ticket 02 ở chế độ chỉ đọc, không bảng Loại bước, không ô "+", không
   menu sửa, không lưu Nháp và không thao tác cây. Mỗi thẻ Bước mang trạng thái, thời gian, token và chi phí của Bước chạy
   từ `run_steps` bằng chữ cùng biểu tượng; đường đã đi được tô, với làn đã đi của mỗi Bước rẽ nhánh, Bước phê duyệt
   (làn của quyết định giả lập nó đã đi) và làn lỗi đọc từ `port` của Bước chạy (V4.36), không suy từ Bước nào đã chạy;
   Bước chưa chạy ghi "Chưa chạy". Một bộ chọn lần lặp (antd `Select`) cho mỗi Bước vòng lặp đọc `iteration_path` mà
   mỗi Bước chạy mang, mọi làn của một Bước song song vẽ cùng lúc, qua `GET /api/v1/runs/{run_id}/steps`
   (telemetry-and-audit:R3.7, telemetry-and-audit:R4.2;
   `.claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md`). Màn mở từ id lượt mà route
   `test-runs` của bước 4 trả (H-17); route Bước chạy cho người giữ `studio.workflows.test` đọc lượt `simulate` do chính
   mình xin mà không cần `runs.read`, và trả 404 cho lượt của người khác, lượt `live` khi không giữ `runs.read` hay lượt
   của công ty khác (telemetry-and-audit:R4.4, telemetry-and-audit:R4.5; V4.41), nên màn không tự kiểm quyền nào. Khung, đầu làn và nhãn của từng cấu trúc là ticket 04; màn
   này dùng chúng khi có, không chờ chúng. Màn là một chế độ của trang builder ở
   `/studio/workflows/[id]/builder?run=<run_id>` và vẽ phiên bản mà trang sẽ hiện theo bước 6 (bản Nháp, hay Bản ứng
   viên, hay bản `live` hoặc bản mới nhất khi không có phiên bản chưa phát hành), kèm dòng cố định "Sơ đồ vẽ <tên phiên
   bản>; kết quả gắn theo id Bước", vì nội dung nháp mà lượt ghim mã băm không được lưu lại để vẽ (ADR-0109 (Accepted)
   quyết 6), và không mang nút sửa, "Tạo bản Nháp" hay chạy mô phỏng nào; Bước chạy có id không còn trong bản Nháp vào một antd `List` "Bước không còn trong bản Nháp" cạnh Sơ đồ, không thẻ
   ma. Chọn một thẻ mở antd `Drawer` chỉ đọc với `input_preview` và `result_preview` của Bước chạy mà route trả, nơi
   duy nhất trang hiện giá trị trường, nên dấu `Đã ẩn` của bước 5 hiện ở đó. Khi lượt chưa kết thúc (trạng thái của
   lượt từ `GET /api/v1/runs/{run_id}` dưới cùng quyền của V4.41), màn hiện antd `Alert` "Lượt đang chạy", đọc lại
   `GET .../steps` mỗi 2 s tới khi lượt kết thúc, và Bước chưa có Bước chạy ghi "Đang chờ", không "Chưa chạy"; "Chưa
   chạy" chỉ khi lượt đã kết thúc. Bộ chọn lần lặp mặc định chọn lần 1; với vòng lặp lồng nhau, danh sách lần của vòng trong chỉ gồm các
   `iteration_path` có tiền tố là lần đang chọn của vòng ngoài, và một Bước của thân hiện Bước chạy có `iteration_path`
   khớp đủ lựa chọn của mọi vòng bao nó.
8. Bản Nháp mới (R3.13, R3.14, R3.15): Quy trình không có bản Nháp hay Bản ứng viên mở phiên bản Đang dùng, hay phiên
   bản mới nhất khi không có bản Đang dùng, chỉ đọc kèm nút "Tạo bản Nháp"; trang không gọi route tạo bản Nháp khi mở.
   Bấm nút thì gọi `POST /api/v1/studio/artifacts/{id}/draft` của tenant-config đúng một lần (tenant-config:R2.21), route
   đã dựng nên trang gửi đúng điều kiện của nó: `If-Match` là ETag của thành phần (`version` của
   `GET /api/v1/studio/artifacts/{id}`, không phải của một phiên bản) và một `Idempotency-Key` sinh một lần cho mỗi lần
   bấm, dùng lại khi trang thử lại sau lỗi mạng, để một lần thử lại không tạo hai bản Nháp
   (`apps/api/src/dw_api/routes/v1/studio_artifacts.py:311-333`; ADR-0108 (Accepted) quyết 4); rồi mở bản Nháp trả về cùng ETag của nó; 409 `candidate_pending` (tenant-config:R2.22) thì đọc lại giai đoạn và vào trạng
   thái chỉ đọc của bước 6; 409 `draft_exists` (tenant-config:R2.23) thì đọc và mở bản Nháp đang có; không lần nào gọi
   lại route.
9. Lớp phần khác (R3.16-R3.20; V4.37): diff theo id Bước có một chủ, `diff_steps` của wf-lite
   (`packages/python/dw_agent_runtime/src/dw_agent_runtime/wflite/outline.py:164`, wf-ai R4.1), mà route của wf-ai đã
   trả (`apps/api/src/dw_api/routes/v1/digital_workers.py:553-590`) và đã so làn chứa cùng chỉ số giữa các Bước chung
   đúng như R3.16 đòi; ticket này mở rộng nó tại chỗ, không viết diff thứ hai trong TS (failure-modes #2):
    - phần riêng của Bước (`_own`) gồm `config` không làn, `description`, `retry`, `timeout_s`, `on_error` và tập tên
      làn của Bước (`NodeTypeSpec.lanes(config)`), nên thêm, bỏ hay đổi tên một làn, kể cả làn rỗng, làm Bước `changed`
      với `fields` có `lanes`;
    - `_place` đi cả `error_lane` của Bước (khóa của workflow-engine/01) dưới tên làn `<id Bước>.error_lane`;
    - mỗi `StepChange` loại `changed` mang `fields`, các khóa của phần riêng đã khác (khóa cấp đầu của `config` ghi là
      `config.<khóa>`);
    - một hàm `diff_sections(base, proposal)` cạnh nó trả tên các khóa cấp đầu ngoài `steps` (`triggers`, `variables`,
      `inputs`, `outputs`, `bindings`, `limits`, `outcomes`) có nội dung khác, so dạng chuẩn;
    - một id đổi Loại bước vẫn là `removed` cộng `added`, như `diff_steps` đã quyết (R3.16).
      Test đơn vị trong `packages/python/dw_agent_runtime/tests/unit/` cho từng mở rộng; test của wf-ai trên `diff_steps`
      giữ nguyên xanh (G: một thay đổi chỉ ở `retry` nay là `changed`, trước là không đổi). Cùng test pytest ghi đầu ra
      của hai hàm trên F1 và bản sửa của các tiêu chí dưới thành `apps/web/lib/__fixtures__/workflows/diff-f1.json` và
      đỏ khi tệp lệch đầu ra, nên test thành phần đọc đúng đầu ra của máy chủ.
      Thành phần Sơ đồ chỉ đọc dưới glob canvas nhận: tài liệu đang xem, tài liệu để so (cho giá trị trước và tên, Loại
      bước, làn cũ của Bước đã xóa), `step_changes` (đầu ra của `diff_steps`), `section_changes` (đầu ra của
      `diff_sections`), và trạng thái so, một trong ba giá trị màn gọi phải nêu rõ: `live`, `no_live` ("chưa có bản Đang
      dùng"), `read_error` ("đọc lỗi"); không giá trị nào suy từ giá trị khác, và thành phần không tính diff nào. Nhãn:
      `added` → antd `Tag` "Mới"; `changed` hay `moved` → "Đã sửa"; `removed` → một mục của antd `List` "Bước đã xóa" cạnh
      Sơ đồ (tên, Loại bước, làn cũ), không thẻ ma trong cây, nên `workflow-layout.ts` không đổi; chữ cùng biểu tượng từ
      khóa thông điệp, màu từ bộ từ vựng của theme. Chọn một thẻ "Đã sửa" mở antd `Drawer` chỉ đọc nêu đúng các khóa ở
      `fields`, trước và sau (antd `Descriptions`), và với một Bước chỉ `moved` thì nêu làn cũ và làn mới từ `from_lane`,
      `lane` của `StepChange`, hay "Đổi thứ tự trong làn" khi hai làn bằng nhau; `section_changes` hiện ở đầu Sơ đồ bằng antd `Alert` (`App.useApp()`
      không dùng cho nó vì nó không phải thông báo tạm). `no_live` thì mọi Bước "Mới"; `read_error` thì một `Alert`
      "Không so được với bản Đang dùng" và không nhãn nào. Màn này không gọi lưu Nháp hay thao tác cây nào, như màn lượt
      chạy; route, quyền, hai tài liệu và việc gọi `diff_steps`, `diff_sections` trên chúng là của agent-lifecycle/07.

## Tiêu chí chấp nhận

- [ ] R3.1: cây Chọn biến của một Bước chỉ liệt kê Bước trội; Bước phía sau không xuất hiện.
- [ ] R3.2 (BU2): bundle route builder không chứa thư viện CEL (test manifest); một Biểu thức sai kiểu
      báo lỗi từ `/expressions/check` của máy chủ, không từ trình duyệt.
- [ ] R3.3 (BU3): gửi kiểm định một Nháp lỗi qua API → 422 với mỗi lỗi mang mã Bước.
- [ ] R3.4: khi có 422, mỗi lỗi gắn về đúng Bước và nút gửi kiểm định nêu lý do bị khóa; một lỗi có `pointer`
      `/steps/2/config/cases/hot/0/config/to` gắn về Bước con trong làn, không về `logic.switch` cha; một lỗi `/limits`
      hiện dưới "Quy trình" trong ngăn kéo và được đếm vào N; gắn lỗi về Bước cha → test đỏ.
- [ ] R3.9: người dựng gõ rồi bấm Gửi kiểm định trước khi debounce của tự lưu chạy → đúng một `PUT .../draft`
      trước, rồi lời gửi mang ETag mà `PUT` đó trả; lần lưu cuối thất bại → nút khóa với lý do, không lời gửi nào; gửi
      với ETag cũ hơn nội dung trên trang → test thành phần đỏ.
- [ ] R3.5 (BU3): không đường nào trong trang builder gọi phát hành; grep mã trang không thấy lời gọi
      phát hành.
- [ ] R3.6 (BU5): trang builder chỉ gửi `simulate`, tới `.../versions/{version_id}/test-runs` với id của phiên bản
      Nháp đang mở; gọi thẳng route với `live` hay `test` → 422; bỏ giới hạn chế độ ở builder → test thành phần đỏ.
- [ ] R3.6: route trả 422 với một lỗi `wf.unreachable_node` có `path` của một Bước → lỗi gắn về đúng Bước đó và ngăn
      kéo "Còn N lỗi" đếm nó (test thành phần với route giả).
- [ ] R3.9: nút Gửi kiểm định gửi `If-Match` bằng ETag của Nháp đã đọc; route trả 412 vì một tab khác đã lưu → nội
      dung đang gõ giữ nguyên và trang mời tải lại; bỏ header → test thành phần đỏ.
- [ ] R3.7 (BU6): route Bước chạy giả trả dấu `Đã ẩn` tại `phone` ở lần lặp thứ hai của một khung vòng lặp và ở một
      làn song song → màn lượt chạy hiện "Đã ẩn" cùng biểu tượng ở cả hai chỗ, và trang không có mã nào đọc hay đổi dấu
      đó thành giá trị; vẽ dấu thành chuỗi rỗng → test thành phần đỏ. Phần "số không có trong payload mạng" là test âm
      của telemetry-and-audit:R4.4 trên route thật, không lặp ở đây.
- [ ] R3.8: Nháp có hai Bước phê duyệt → biểu mẫu chạy mô phỏng có hai lựa chọn bắt buộc; chưa chọn một Bước thì
      nút chạy khóa có lý do; chọn đủ → thân yêu cầu mang `simulated_decisions` đúng hai id và hai quyết định đã
      chọn (test thành phần).
- [ ] R3.10 (BU9): Quy trình có Bản ứng viên ở `awaiting_approval` → Sơ đồ và biểu mẫu chỉ đọc, trang nêu "rút bản đang
      chờ về Nháp để sửa", không lời gọi `PUT .../draft` hay `POST .../draft`, không lời gọi `withdraw` khi chưa bấm Rút
      về Nháp; bấm → đúng một lời gọi `POST .../withdraw`, rồi trang mở bản Nháp với ETag mới; route gửi kiểm định giả
      trả 409 `candidate_exists` → trang vào cùng trạng thái chỉ đọc; bỏ trạng thái chỉ đọc → test thành phần đỏ.
- [ ] R3.11 (BU16): lượt mô phỏng của F5 (test thành phần với `GET /api/v1/runs/{run_id}/steps` giả) → Sơ đồ chỉ
      đọc, mỗi thẻ có trạng thái, thời gian, token và chi phí bằng chữ cùng biểu tượng; làn của quyết định giả lập được
      tô, làn kia ghi "Chưa chạy"; một `logic.switch` có `port` là làn "Khác" rỗng → làn đó được tô; màn lượt chạy
      không gọi lưu Nháp hay thao tác cây nào; cho sửa trên màn lượt chạy, hay suy làn đã đi từ Bước chạy thay `port` →
      test thành phần đỏ.
- [ ] R3.11 (BU16): lượt giả chưa kết thúc → `Alert` "Lượt đang chạy", `GET .../steps` gọi lại sau 2 s, Bước chưa có
      Bước chạy ghi "Đang chờ"; lượt kết thúc → hết gọi lại, Bước không chạy ghi "Chưa chạy"; chọn một thẻ → `Drawer` chỉ
      đọc với `input_preview` và `result_preview`; ghi "Chưa chạy" khi lượt còn chạy → test thành phần đỏ.
- [ ] R3.12 (BU16): lượt mô phỏng của F3 (test thành phần với `GET /api/v1/runs/{run_id}/steps` giả) → chọn lần lặp
      2 → mỗi Bước của thân vòng lặp, ở mọi làn của một Bước song song trong thân, hiện Bước chạy có `iteration_path`
      của lần 2; bỏ lọc theo `iteration_path` → test đỏ.
- [ ] R3.10 (BU9): trạng thái đọc từ `GET .../versions` giả: phiên bản `draft` → sửa; `awaiting_approval` → chỉ đọc
      của R3.10; chỉ `live` → chỉ đọc kèm "Tạo bản Nháp"; không `live` mà có `version_no` 1 và 2 `retired` → hiện bản 2;
      suy trạng thái từ 404 của `GET .../draft` → test thành phần đỏ.
- [ ] R3.13 (BU15): Quy trình chỉ có bản Đang dùng → trang chỉ đọc kèm "Tạo bản Nháp", không lời gọi
      `POST .../draft` khi chưa bấm; bấm → đúng một lời gọi mang `If-Match` là ETag của thành phần và một
      `Idempotency-Key`, rồi trang mở bản Nháp với ETag route trả; lỗi mạng rồi thử lại → lời gọi thứ hai mang cùng
      `Idempotency-Key`; gọi route lúc mở trang, hay sinh khóa mới khi thử lại → test thành phần đỏ.
- [ ] R3.14 (BU15): route giả trả 409 `conflict` với `candidate_pending` → trang vào trạng thái chỉ đọc của R3.10, nêu
      "rút bản đang chờ về Nháp để sửa", không lời gọi thứ hai; gọi lại route sau 409 → test đỏ.
- [ ] R3.15 (BU15): route giả trả 409 `conflict` với `draft_exists` → trang đọc và mở bản Nháp đang có với ETag của nó,
      không lời gọi thứ hai; hiện lỗi thay vì mở bản Nháp → test đỏ.
- [ ] R3.16 (BU17): pytest của `diff_steps` và `diff_sections` mở rộng: đổi chỉ `retry` của một Bước →
      `changed` với `fields` `["retry"]`; một Bước trong `error_lane` bị xóa → `removed` ở làn `<id>.error_lane`; đổi
      `limits.max_steps` → `diff_sections` trả `["limits"]`; thêm một mục `cases` rỗng `warm` vào một `logic.switch` →
      Bước đó `changed` với `fields` có `lanes`; một id đổi Loại bước → `removed` cộng `added`; tệp
      `diff-f1.json` lệch đầu ra → test đỏ; mọi test của wf-ai trên `diff_steps` xanh.
- [ ] R3.16 (BU17): test thành phần trên F1 làm bản Đang dùng và một bản sửa của nó (thêm một Bước, đổi `config.on` của một
      `logic.switch`, đổi chỗ hai Bước trong một làn, dời một Bước sang làn khác), với `step_changes` của `diff-f1.json` → đúng một thẻ "Mới", nhãn "Đã sửa" ở
      Bước đổi ngưỡng, ở cả hai Bước đổi chỗ và ở Bước dời, không nhãn ở Bước đứng ngay sau Bước mới; bỏ so thứ tự trong
      làn → hai Bước đổi chỗ không mang nhãn, test đỏ; bỏ so làn chứa → Bước dời không mang nhãn, test đỏ; màn gọi đưa
      "chưa có bản Đang dùng" cùng F1 → mọi Bước của F1 mang "Mới"; cho giá trị đó vẽ như không phần khác → không thẻ
      nào mang nhãn, test đỏ.
- [ ] R3.17 (BU17): bản sửa xóa một Bước và một khung "Song song" chứa hai Bước → danh sách "Bước đã xóa" có đúng bốn
      mục (Bước đó, chính Bước song song và hai Bước trong các làn của nó), mỗi mục nêu tên, Loại bước và làn cũ; Sơ đồ
      không vẽ thẻ nào cho chúng, và tọa độ mọi Bước còn lại bằng tọa độ khi vẽ bản sửa không có lớp phần khác; bỏ danh
      sách → bốn Bước đó không hiện ở đâu, test đỏ.
- [ ] R3.18: chọn Bước đổi ngưỡng → Drawer chỉ đọc nêu đúng trường `config` đã khác với giá trị trước và sau, không
      trường nào khác, không nút lưu hay sửa nào; chọn một Bước chỉ dời làn → Drawer nêu làn cũ và làn mới từ `from_lane`,
      `lane`; cho Drawer nêu mọi trường của Bước, hay đặt một ô sửa trong Drawer →
      test thành phần đỏ.
- [ ] R3.19 (BU17): màn gọi đưa "đọc lỗi" → `Alert` "Không so được với bản Đang dùng", không nhãn nào trên Sơ đồ; cho
      "đọc lỗi" vẽ thành "không phần khác", hay thành cây rỗng → test đỏ.
- [ ] R3.20 (BU17): bản sửa chỉ đổi `limits.max_steps` và một mục `triggers[]` → đầu Sơ đồ nêu `limits` và `triggers`,
      không thẻ nào mang nhãn; bỏ so phần ngoài cây Bước → không gì hiện, test đỏ.
- [ ] Xong: `pnpm -C apps/web test && uv run python -m pytest packages/python/dw_agent_runtime/tests/unit -k "diff_steps or diff_sections"` xanh.

## Nguồn

- workflow-nodes:R3.2, workflow-nodes:R3.5;
  `.claude/plans/studio/workflow-nodes/issues/03-pham-vi-bien-va-buoc-logic.md`.
- workflow-triggers:R2.2, workflow-triggers:R2.3, workflow-triggers:R2.6, workflow-triggers:R2.9, tenant-config:R5.1,
  tenant-config:R6.1; ADR-0112 (Accepted) quyết 3; spec: R3.6.
- agent-lifecycle:R2.1, agent-lifecycle:R2.12, agent-lifecycle:R2.13; ADR-0108 (Accepted) quyết 3; spec: R3.9.
- agent-lifecycle:R1.3, agent-lifecycle:R2.4; tenant-config:R2.20, tenant-config:R2.22; spec: R3.10.
- tenant-config:R2.21, tenant-config:R2.22, tenant-config:R2.23; spec: R3.13, R3.14, R3.15.
- telemetry-and-audit:R3.7, telemetry-and-audit:R4.2;
  `.claude/plans/studio/telemetry-and-audit/issues/03-lich-su-chay-theo-buoc.md`; spec: R3.11, R3.12 (Bước chạy mang
  `lane_path` và `iteration_path`).
- ADR-0101 (Accepted), ADR-0114 (Accepted); spec: R3.2.
- ADR-0112 (Accepted) quyết 1 (id của Bước giữ nguyên qua các phiên bản);
  `.claude/plans/studio/agent-lifecycle/issues/07-man-duyet-phat-hanh.md`; spec: R3.16-R3.20 (lớp phần khác mà màn
  duyệt dùng, V4.37).
- telemetry-and-audit:R4.2 (`port` của V4.36), telemetry-and-audit:R4.4, telemetry-and-audit:R4.5 (quyền đọc của
  V4.41); spec: R3.11.

## Comments

- 2026-10-23 (agent): theo phiếu 23/10/2026: W1 chỉ chạy thử `simulate` và route chạy thử là của workflow-triggers (DO-26.1); route kiểm biểu thức theo dạng sub-resource của ADR-0108 (Accepted); nút là "Gửi kiểm định" và gọi route của agent-lifecycle.
- 2026-10-24 (agent): theo quyết định N2 của Đạt ngày 24/10/2026: biểu mẫu chạy mô phỏng đòi một lựa chọn duyệt hay từ chối cho mỗi Bước phê duyệt (R3.8), thay câu "người duyệt trong lượt chạy thử là chính người thử"; lượt `simulate` gọi là chạy mô phỏng.
- 2026-10-24 (agent): vòng sửa thứ tư, theo quyết định của Đạt cùng ngày: route `.../test-runs` nhận bản Nháp ở chế độ `simulate`, nên trang chạy mô phỏng chính phiên bản Nháp đang mở và giữ lựa chọn cho mỗi Bước phê duyệt của Nháp (R3.6, R3.8).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt b, theo các quyết định tạm cùng ngày của spec: lỗi `wf.*` mà route chạy mô phỏng trả khi nội dung nháp trượt bộ kiểm khi gửi kiểm định gắn về Bước (R3.6); nút Gửi kiểm định gửi `If-Match` là ETag của Nháp (R3.9).
- 2026-10-24 (agent): vòng sửa thứ tư, lượt f, theo quyết định V4.17 của Đạt cùng ngày: Quy trình có Bản ứng viên đang chờ thì trang chỉ đọc, nêu "rút bản đang chờ về Nháp để sửa" và chỉ gọi lệnh rút của agent-lifecycle khi người dựng bấm (R3.10, BU9). Không thêm cạnh: ticket đã chờ agent-lifecycle/03, nơi có lệnh rút.
- 2026-10-25 (agent): lượt g, theo V4.24 của Đạt và G-5 ngày 24/10/2026: kết quả lượt mô phỏng mở trên màn lượt chạy cùng Sơ đồ, chỉ đọc, chọn lần lặp và làn (R3.11, R3.12, BU16), thay lớp phủ trước đây; Quy trình không có bản Nháp hay Bản ứng viên mở bản Nháp mới chỉ khi người dựng bấm Tạo bản Nháp (R3.13, R3.14, R3.15, BU15). Không thêm cạnh: ticket đã chờ telemetry-and-audit/03 (làn và `iteration_path` của Bước chạy), và tenant-config/02 (route tạo bản Nháp) đã đứng trước nó qua ticket 02.
- 2026-10-25 (agent): màn lượt chạy thôi có bộ chọn làn (R3.12, BU16): id Bước là duy nhất trong cây (workflow-engine:R1.1) và mọi làn của một Bước song song vẽ cùng lúc, nên làn không phân biệt Bước chạy nào mà id chưa phân biệt, và ca âm của nó không đỏ được; bộ chọn chỉ số của `logic.map` đến ở W2 (dòng Quyết định 25/10/2026 của spec).
- 2026-10-25 (agent): lượt h, theo V4.37 của Đạt: ticket thêm lớp phần khác của Sơ đồ chỉ đọc so theo id Bước với bản Đang dùng (bước 9; R3.16-R3.20, BU17), mà agent-lifecycle/07 dùng và chờ ticket này; theo V4.41: màn lượt chạy mở từ id mà `test-runs` trả, dưới quyền đọc của người giữ `studio.workflows.test` cho lượt `simulate` do chính mình xin (R3.11); làn đã đi đọc từ `port` của Bước chạy (V4.36). Không thêm cạnh: ticket đã chờ telemetry-and-audit/03, nơi `port` và quyền đọc của V4.41 ra đời, và diff theo id Bước có ở ticket 02.
- 2026-10-26 (agent): lượt h, rà lại: quyền đọc của V4.41 dẫn đúng tiêu chí của telemetry-and-audit (R4.4 cho người dựng đọc lượt `simulate` của chính mình, R4.5 cho 404), thay R4.2, vốn là tiêu chí của route cho người giữ `runs.read`; tiêu chí R3.18 thêm ca âm. Không thêm cạnh.
- 2026-10-26 (agent): lượt h, kiểm: ca "chưa có bản Đang dùng" (mọi Bước "Mới") dời từ tiêu chí R3.19 sang R3.16, vì
  R3.16 của spec nay nêu ca đó còn R3.19 chỉ nói "đọc lỗi" và chưa rõ, và có ca âm riêng; tiêu chí R3.17 đếm đúng bốn
  mục, vì chính Bước song song bị xóa cũng có id chỉ ở bản Đang dùng. Không thêm cạnh.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness trên `523bc94` (builder check trong một subagent, không boundary walk: ticket không thêm migration hay route; lượt xác nhận ngữ cảnh mới sau các sửa), 0 CRITICAL, 15 HIGH đã sửa theo khuyến nghị (quyết định ở dòng gate ticket 03 của spec). Lượt đầu: (1) diff TS ở bước 9 trái dòng gate ticket 02: nay mở rộng `diff_steps` của wf-lite và nhận đầu ra của nó (failure-modes #2); (2) `pointer` của 422 giải ra id Bước sâu nhất, lỗi cấp tài liệu có chỗ trong ngăn kéo; (3) gửi kiểm định, chạy mô phỏng và các lời gọi đọc Nháp xả tự lưu trước; (4) điều kiện khóa nút Gửi kiểm định và trạng thái sau khi gửi; (5) che là của máy chủ (`Đã ẩn` của telemetry-and-audit), test của trang không đòi chứng minh điều nó không thấy; (6) màn lượt chạy vẽ phiên bản nào và Bước không còn trong bản Nháp; (7) trạng thái trang và giai đoạn từ `GET .../versions`, không từ 404; (8) bộ chọn lần lặp mặc định và vòng lồng nhau; (9) `POST .../draft` đã dựng đòi `If-Match` của thành phần và nhận `Idempotency-Key` (`apps/api/src/dw_api/routes/v1/studio_artifacts.py:311-333`). Lượt xác nhận: (10) nút bấm được khi chỉ chờ debounce; (11) thêm hay bỏ một làn rỗng làm Bước `changed` (`fields` có `lanes`), không im lặng; (12) giá trị trường chỉ trong Drawer của thẻ trên màn lượt chạy; (13) màn lượt chạy khi không còn bản Nháp; (14) lượt còn chạy: đọc lại, "Đang chờ"; (15) Drawer của Bước chỉ dời làn. Nếu sai thì: như `Nếu sai thì:` của dòng gate ticket 03 trong spec; với (10)-(15): nút khóa tới khi tự lưu xong, làn rỗng thêm vào không mang nhãn và màn duyệt nêu riêng, màn lượt chạy không có Drawer và R3.7 hiện dấu trên thẻ, màn lượt chạy báo lỗi khi không còn bản Nháp, lượt còn chạy chỉ hiện khi đã kết thúc, Bước dời không mở Drawer.
- 2026-11-04 (agent): MEDIUM để lại: (a) "đổi ngưỡng" của `logic.switch` trong tiêu chí là đổi `config.on`; khóa của `cases` là giá trị so, nên Tag làn hiện khóa đó (ticket 04); (b) ô "Payload mẫu" chỉ khi tài liệu không khai `inputs`; (c) nút chạy mô phỏng chỉ ở trạng thái sửa bản Nháp, khóa khi `/me` không có `studio.workflows.test`; (d) `simulated_decisions` mang một quyết định mỗi id Bước (workflow-triggers:R2.7), nên F5 "Từ chối lần 1, Duyệt lần 2" không mô phỏng được và vòng làm lại chạy tới `max_iterations`; quyết theo từng lần lặp là của workflow-triggers, ghi cho lần kiểm nhất quán; (e) `Stage` chỉ có năm giá trị (`packages/python/dw_studio/src/dw_studio/core/domain/artifacts.py:36-47`), nên phiên bản chưa phát hành chỉ là `draft`, `evaluating` hay `awaiting_approval`.
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
