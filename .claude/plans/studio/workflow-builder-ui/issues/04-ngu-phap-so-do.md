# 04 — Ngữ pháp sơ đồ: nhánh, song song, vòng lặp, nhánh lỗi, quy trình con

Status: resolved
Blocked by: 02
Area: studio
Yêu cầu: R1.5, R1.7, R2.5, R2.6, BU7, BU8, BU11, BU14

## Mục tiêu

Sơ đồ vẽ mọi cấu trúc của cây Bước theo bảng ngữ pháp của R1.5, trên năm khối chung mà ticket 02 đặt chỗ: các làn của
`logic.switch` với làn "Khác", làn "Duyệt" và "Từ chối" của Bước phê duyệt, khung "Song song" với Điểm nối, khung vòng
lặp với mũi tên "Lặp lại", làn lỗi khi Khi lỗi là `route`, và thẻ Quy trình con; khung chứa thu gọn được; bàn phím và
Dạng danh sách đi qua làn và khung (workflow-builder-ui R1.5, R1.7, R2.5, R2.6, BU7, BU8, BU11, BU14). Đây là bậc A của
V4.26 và V4.33: ngữ pháp có trước bộ máy chạy song song, vòng lặp có trần và lượt con của bậc B, nên ticket không chờ
các Loại bước của bậc B; bảng Loại bước chỉ đưa chúng khi workflow-nodes đăng ký.

## Việc cần làm

1. Dưới `apps/web/app/studio/**/canvas/**`, vẽ mỗi cấu trúc bằng antd từ hình mà `apps/web/lib/workflow-layout.ts`
   (ticket 02) trả, đúng bảng ngữ pháp của R1.5. Hình của một Bước chọn theo cờ mà `GET /api/v1/studio/node-types` trả
   cho Loại bước, không theo tên Loại bước: `block` (`none`, `choice`, `parallel`, `loop`), `ends_run`, `exits_loop`
   (ADR-0112 (Accepted) Amendments 2026-11-03), nên `logic.map` của W2 chỉ thêm một mục danh mục; chỉ nội dung thẻ của
   từng loại W1 (thẻ người duyệt, tóm tắt `config.on`, dấu "Quy trình con", tiêu đề "Lặp lại khi …") chọn theo tên loại,
   và một loại có `block` mà trang không biết tên vẫn vẽ đúng khối với thẻ R1.8 chung. Sơ đồ vẽ đúng tài
   liệu, kể cả một bản Nháp chưa hợp lệ: không vẽ đường nào tài liệu không có, và lỗi của bộ kiểm hiện trên Bước như
   R3.4. Một làn mà Bước cuối có `ends_run` hay `exits_loop` không nối về điểm gộp hay Điểm nối của khối; Bước có
   `exits_loop` vẽ mũi tên tới lối ra của vòng lặp. Một Bước đứng sau một Bước có `ends_run` hay `exits_loop` trong
   cùng chuỗi vẫn vẽ ở chỗ của nó, không đường nối từ Bước trước, mang lỗi `wf.unreachable_node` của máy chủ; một khối
   mà mọi làn kết thúc như vậy không có điểm gộp và không nối tới Bước sau nó. Bước có `block` khác `none` có thẻ R1.8 của chính nó ở đầu khối (huy
   hiệu, menu "…", điểm dừng focus, huy hiệu lỗi), và khi thu gọn khối vẽ đúng thẻ đó:
    - `logic.switch`: thẻ điều kiện, tóm tắt cấu hình là `config.on` nguyên văn như máy chủ lưu (không rút gọn CEL ở
      trình duyệt); các làn treo dưới thẻ, cạnh nhau theo thứ tự tài liệu, mỗi làn dưới một antd `Tag` mang khóa của
      mục `cases` mà Bước so `on` với nó ("hot"), làn "Khác" dưới Tag "Khác"; mỗi Tag của một mục `cases` có menu "…"
      với "Bỏ nhánh", gọi thao tác làn của ticket 02; làn "Khác" luôn vẽ, cả khi trống (ô "Thêm Bước"); các làn gộp ở
      một điểm dưới các làn, không phải Điểm nối.
    - Bước phê duyệt: thẻ người duyệt nêu người được giao và phạm vi theo các trường mà workflow-nodes:R12.1 khai,
      "Cần cả N người duyệt" khi quy tắc duyệt là `all` và cấu hình liệt kê N ≥ 2 người cụ thể, "Cần mọi người được
      giao duyệt" khi quy tắc là `all` mà người được giao có một vai hay một phạm vi, vì N chỉ biết lúc chạy, và không
      dòng quy tắc nào khi quy tắc khác `all` hay chỉ một người cụ thể; làn "Duyệt" và "Từ chối" cho Nhánh ra
      `approved`, `rejected` (workflow-nodes:R9.9, workflow-nodes:R9.16) treo dưới thẻ, gộp ở một điểm dưới các làn.
    - Bước song song: khung "Song song" N làn cạnh nhau, mỗi làn dưới một nhãn là khóa của mục `branches` với menu "…"
      có "Bỏ nhánh", đáy khung là Điểm nối, một thanh "Chờ tất cả nhánh xong"; không
      có Bước gộp riêng.
    - Bước vòng lặp: khung "Lặp lại khi … (tối đa N lần)" quanh thân, "…" là điều kiện lặp nguyên văn từ trường cấu
      hình mà workflow-nodes:R11.1 khai, cắt bằng dấu … và đủ chữ qua Tooltip, N là `max_iterations`; menu "…" của thẻ
      đầu khung có "Thêm làn 'Đã đủ N lần'" hay "Bỏ làn 'Đã đủ N lần'" (thao tác làn của ticket 02); mũi tên "Lặp lại" dọc rãnh trái; dưới khung là
      lối ra thường, ở giữa; làn "Đã đủ N lần" cho Nhánh ra `max_reached`, khi Bước có làn đó, treo ở bên phải lối ra và
      gộp với nó ở một điểm bên dưới; Bước "Thoát vòng lặp" vẽ mũi tên tới lối ra thường, không bao giờ tới làn "Đã đủ
      N lần".
    - Làn lỗi (Khi lỗi là `route`): làn nét đứt ở rãnh phải của Bước, nhãn "Khi lỗi" theo token lỗi của theme, gộp lại
      dưới Bước, trừ khi làn kết thúc bằng một Bước có `ends_run`. Trong một làn song song, bộ kiểm của workflow-engine
      từ chối làn lỗi kết thúc và `flow.stop` (workflow-engine:R2.15); Sơ đồ vẫn vẽ làn đó kết thúc như tài liệu nói và
      chỉ hiện lỗi đó trên Bước như R3.4, không tự kiểm (ADR-0101 (Accepted) quyết 3). Làn lỗi là làn cuối của Bước,
      sau các làn của Nhánh ra, với ←/→ và trong `aria-posinset`, `aria-setsize` của `Tree`. Làn lỗi của một Bước song
      song hay vòng lặp nằm ở rãnh phải của cả khung và gộp lại dưới điểm gộp của lối ra thường và làn "Đã đủ N lần".
    - Quy trình con (`flow.subworkflow`): thẻ Bước cỡ cố định của R1.8 mang dấu "Quy trình con" (biểu tượng cùng chữ, từ
      bộ từ vựng của theme), tóm tắt cấu hình là `api_name` của Quy trình được gọi (`config.workflow`,
      workflow-nodes:R13.1), và dòng "Chờ Quy trình con xong", vì Bước mở một điểm chờ `child_run`; không vẽ Bước nào
      của Quy trình con trong Sơ đồ cha; không Tag phiên bản ghim, báo lệch hay nút Mở ở W1 (Ngoài phạm vi của spec).
      Một Bước Quy trình con trong làn song song bị bộ kiểm từ chối với `wf.wait_in_parallel` (workflow-nodes:R13.3);
      Sơ đồ chỉ hiện lỗi đó trên Bước như R3.4.
    - Nhãn lấy từ khóa thông điệp (DO-57) và nhãn Nhánh ra của `GET /api/v1/studio/node-types` (workflow-nodes:R1.2);
      màu, biểu tượng, cỡ thẻ và kiểu đường nối chỉ từ bộ từ vựng mà ticket 01 ghi trong theme của `@dw/ui`.
2. Thu gọn: mỗi khung chứa ("Song song", "Lặp lại khi …") thu gọn và mở từ một antd `Button` ở đầu khung; trạng thái
   giữ theo người xem trong `localStorage` dưới khóa `wbui.collapsed.<user_id>.<artifact_id>` (danh sách id Bước;
   `user_id` từ phiên đã xác thực), mọi lần đọc, ghi bọc `try/catch`, trang vẽ đủ, mọi khung mở, khi bộ nhớ không dùng
   được, không bao giờ vào tài liệu; `workflow-layout.ts` đo khung thu gọn như một thẻ. Sơ đồ chỉ đọc của màn lượt chạy
   và màn duyệt phát hành không đọc trạng thái đó và mở mọi khung, để người duyệt không bỏ sót phần khác trong một khung
   đang thu gọn. Ctrl+K "Đi tới Bước" hay bấm một lỗi trỏ tới Bước trong khung thu gọn thì mở các khung bao nó và lưu
   như một lần mở tay. ↑/↓ bỏ qua Bước trong khung thu gọn; `expandedKeys` của `Tree` là cùng trạng thái thu gọn, một
   chủ; thẻ thu gọn mang huy hiệu "N lỗi" khi Bước bên trong có lỗi của bộ kiểm.
3. Bàn phím và Dạng danh sách qua cấu trúc, theo thứ tự trước và hình `Tree` của ticket 02: ←/→ đi giữa các làn kề
   nhau của một Bước, tới Bước đầu của làn kề hay ô "Thêm Bước" của nó khi rỗng; ↓ từ thẻ của một Bước có làn
   vào Bước đầu của làn đầu, ↑ từ Bước đầu của một làn về thẻ đó; `Tree` vẽ mỗi làn là một node lồng dưới Bước của nó,
   mang `aria-level`, `aria-posinset`, `aria-setsize`, với nhãn bằng chữ của Tag trên Sơ đồ, để NVDA đọc "nhánh 2 trên
   3: hot".
4. Fixture F2, F3, F4, F5 và F9 của ticket 01 thành snapshot test, cộng F10 của ticket này (một Bước Quy trình con ở
   chuỗi gốc và một trong thân một Bước vòng lặp); Playwright chỉ bàn phím dựng F5. Cả hai chạy trên một
   `GET /api/v1/studio/node-types` giả mang mọi Loại bước mà các fixture dùng, với cờ `block`, `ends_run`,
   `exits_loop` của mỗi loại, đúng Nhánh ra và cấu hình mà
   workflow-nodes khai, kể cả `human.approval@1` với quy tắc duyệt `all` và các loại của bậc B `logic.parallel@1`,
   `logic.loop@1`, `logic.break@1`, `flow.subworkflow@1` (workflow-nodes:R10.1, workflow-nodes:R11.2,
   workflow-nodes:R12.1, workflow-nodes:R13.1), vì ticket này chỉ chờ danh mục của workflow-nodes/02 qua ticket 02, không
   chờ workflow-nodes đăng ký các loại đó (V4.26, V4.33).
5. Học mẫu, không chép: đặc tả OpenFlow của Windmill (Apache-2.0) và luồng của Power Automate là danh sách kiểm cho ngữ
   pháp; không chép giao diện Dify, không chép mã Windmill hay n8n (V4.24, V4.29).

## Tiêu chí chấp nhận

- [ ] R1.5: snapshot F2 (`logic.switch` 8 làn lồng 2 tầng): mỗi làn dưới Tag điều kiện của nó, làn "Khác" có mặt, các
      làn của mỗi Bước gộp ở đúng một điểm; F3: khung "Song song" có thanh "Chờ tất cả nhánh xong" nằm trong khung "Lặp
      lại khi … (tối đa N lần)" có mũi tên "Lặp lại" và làn "Đã đủ N lần"; F4: mỗi Bước có làn "Khi lỗi" nét đứt ở rãnh
      phải, gộp lại dưới Bước; F5: làn "Duyệt" và "Từ chối", thẻ "Cần cả 3 người duyệt"; F9 vẽ xong, mỗi Bước "Thoát
      vòng lặp" có mũi tên tới lối ra dưới khung của nó, không hai thẻ chồng nhau; vẽ một điểm gộp của `logic.switch`
      bằng thanh "Chờ tất cả nhánh xong" → snapshot đỏ.
- [ ] R1.5: F9 → không đường nối nào từ một làn kết thúc bằng "Thoát vòng lặp" về điểm gộp của khối chứa nó, mũi tên
      của nó tới lối ra thường dưới khung, không tới làn "Đã đủ N lần"; F3 → khung "Song song" và khung "Lặp lại" mỗi
      khung có thẻ R1.8 của chính Bước đó ở đầu, với menu "…" và huy hiệu; một danh mục giả đổi tên `logic.parallel`
      thành `x.par@1` mà giữ `block: parallel` → F3 vẽ y hệt; chọn hình theo tên loại, hay nối làn kết thúc về điểm
      gộp → snapshot đỏ. Một bản Nháp có `flow.stop` cuối làn lỗi trong một làn song song → làn đó vẽ kết thúc, không
      đường gộp.
- [ ] R1.5: snapshot F10: mỗi Bước Quy trình con, ở chuỗi gốc và trong thân vòng lặp, là một thẻ mang dấu "Quy trình
      con", `api_name` của Quy trình được gọi và dòng "Chờ Quy trình con xong", và không thẻ nào của Quy trình con được
      vẽ trong Sơ đồ cha; vẽ các Bước của Quy trình con vào Sơ đồ cha, hay bỏ dòng "Chờ Quy trình con xong" → snapshot
      đỏ.
- [ ] R1.5 (BU14): một màu literal trong thành phần ngữ pháp → test đỏ; một nhãn làn, đầu khung hay dấu "Quy trình con"
      chỉ có màu, không chữ → test đỏ.
- [ ] R1.7 (BU8): thu gọn một khung → khung vẽ như thẻ R1.8 của Bước đó, tài liệu và Mã băm nội dung không đổi; tải
      lại → khung vẫn thu gọn với cùng người xem; người xem khác trên cùng trình duyệt → mọi khung mở; Sơ đồ chỉ đọc của
      màn duyệt với cùng khóa trong bộ nhớ → mọi khung mở; Ctrl+K tới một Bước trong khung thu gọn → khung mở; bộ nhớ
      trình duyệt không dùng được → trang vẽ đủ, mọi khung mở; ghi trạng thái thu gọn vào tài liệu, hay bỏ `user_id`
      khỏi khóa → test đỏ.
- [ ] R2.5 (BU7): Playwright dựng F5 chỉ bằng bàn phím: đặt Bước vào làn "Từ chối" của một Bước phê duyệt và vào thân
      vòng lặp, dời một Bước sang làn kế, vào và ra khung chứa, thu gọn rồi mở một khung, xóa khung "Lặp lại khi …" rồi
      hoàn tác; phím mũi tên không bao giờ dời node; bỏ đường bàn phím vào làn → test đỏ.
- [ ] R2.6 (BU11): `Tree` của F2 mang `aria-level`, `aria-posinset`, `aria-setsize` đúng cấp và vị trí của mỗi làn và
      mỗi Bước; `Tree` của F4 đếm làn lỗi là làn cuối của mỗi Bước trong `aria-setsize`; bỏ một thuộc tính ở node làn →
      test đỏ.
- [ ] Xong: `pnpm -C apps/web test` xanh.

## Nguồn

- ADR-0101 (Accepted) quyết 2, 3; ADR-0112 (Accepted) quyết 1; spec: R1.5, R1.7.
- workflow-nodes:R1.2, workflow-nodes:R9.9, workflow-nodes:R9.16; spec: R1.5 (Nhánh ra và nhãn của Loại bước, từ vựng
  `approved`, `rejected` và làn của mỗi kết quả phê duyệt).
- workflow-nodes:R10.1, workflow-nodes:R11.2, workflow-nodes:R12.1; spec: R1.5 (Nhánh ra của Bước song song và Bước
  vòng lặp, quy tắc duyệt `all`, cho danh mục giả của bước 4).
- workflow-engine:R1.1, workflow-engine:R2.15; spec: R1.5 (làn lồng theo Nhánh ra; trong làn song song, làn lỗi chỉ gộp
  lại).
- workflow-nodes:R13.1, workflow-nodes:R13.3; ADR-0113 (Accepted) quyết 4, 9; spec: R1.5 (cấu hình của Bước Quy trình
  con, điểm chờ `child_run` mà dòng "Chờ Quy trình con xong" nói).
- `.claude/rules/ui-quality.md:230-231`, `.claude/rules/ui-quality.md:370-376`; spec: R1.5 (không chỉ màu, tương phản).
- `packages/typescript/ui/src/theme.ts:3-6`; spec: R1.5 (một chủ của màu).

## Comments

- 2026-10-25 (agent): tạo ở lượt g theo V4.24, V4.26 (bậc A) và V4.27 của Đạt ngày 24/10/2026. Không cạnh tới spec khác: ngữ pháp vẽ từ cây tài liệu và danh mục Loại bước mà ticket 02 đã chờ (workflow-engine/01, workflow-nodes/02), không chờ Loại bước của bậc B.
- 2026-10-25 (agent): lượt h, theo V4.33 của Đạt: ngữ pháp thêm thẻ Quy trình con (bậc A vẽ, bậc B chạy ở workflow-engine/09 và workflow-nodes/08), với fixture F10 và danh mục giả mang `flow.subworkflow@1`; Tag phiên bản ghim, báo lệch và nút Mở ở W2 (dòng Quyết định 25/10/2026 của spec, agent, tạm). Không thêm cạnh: ticket không chờ workflow-nodes/08, như với các loại khác của bậc B.
- 2026-11-04 (agent, theo ủy quyền 31/10/2026): checking-plan-readiness trên `f884268` (builder check trong một subagent, không boundary walk: ticket không thêm migration hay route; lượt xác nhận ngữ cảnh mới sau các sửa), 0 CRITICAL, 17 HIGH đã sửa theo khuyến nghị (quyết định ở dòng gate ticket 04 của spec). Lượt đầu: (1) làn kết thúc bằng `flow.stop` hay "Thoát vòng lặp" không nối về điểm gộp; (2) hình theo cờ `block`, `ends_run`, `exits_loop` của danh mục, danh mục giả mang chúng; (3) Tag làn là khóa của `cases`, không rút gọn CEL ở trình duyệt; (4) chỗ của làn "Đã đủ N lần" và lối ra mà "Thoát vòng lặp" chỉ tới; (5) làn lỗi là làn cuối với ←/→ và `aria-setsize`; (6) Nháp chưa hợp lệ vẽ đúng tài liệu; (7) "Cần cả N người duyệt" chỉ khi N người cụ thể; (8) Bước khung có thẻ R1.8 riêng, thu gọn vẽ thẻ đó; (9) khóa thu gọn có người xem, Sơ đồ chỉ đọc mở mọi khung; mô hình phím từ lượt đầu đã theo ticket 02. Lượt xác nhận: (10) làn không bắt buộc (`max_reached`) không tạo sẵn, có "Thêm/Bỏ làn 'Đã đủ N lần'"; (11) bàn phím theo cấu trúc, có đường ra khỏi khung (ticket 02 sửa); (12) phần nào được theo tên loại; (13) đầu làn có "Bỏ nhánh", nhãn làn song song là khóa của `branches`; (14) tiêu đề vòng lặp là điều kiện nguyên văn; (15) Bước sau Bước kết thúc và khối không điểm gộp; (16) thu gọn với bàn phím, `Tree` và huy hiệu lỗi; (17) làn lỗi của một khung. Nếu sai thì: như `Nếu sai thì:` của dòng gate ticket 04 trong spec.
- 2026-11-04 (agent): MEDIUM để lại: (a) Ctrl+K hay bấm một lỗi trỏ vào khung thu gọn thì mở khung và lưu như mở tay; (b) ví dụ NVDA đổi thành "nhánh 2 trên 3: hot" theo khóa của `cases`; (c) thẻ phê duyệt với quy tắc khác `all` không có dòng quy tắc; (d) ngữ pháp vẽ khung song song cho mọi loại có `block: parallel`, nên khi workflow-nodes đăng ký `logic.parallel@1` với cờ khác danh mục giả, danh mục giả sửa cùng thay đổi đăng ký (spec "Kiểm lại khi").
- 2026-11-04 (agent): checking-plan-readiness ĐẠT; ready-for-agent.
- 2026-11-05 (agent): resolved, làn dựng 2, hai commit (mã, rồi test và ticket). Dựng: danh mục `GET /api/v1/studio/node-types`
  trả thêm `block`, `ends_run`, `exits_loop` (`_catalogue_entry` của wf-lite, `NodeTypeView`, OpenAPI và kiểu TS sinh lại);
  `lib/workflow-layout.ts` viết lại theo năm khối (chuỗi, làn, khung, mũi tên quay lại, làn lỗi) chọn theo cờ, làn kết thúc
  không về điểm gộp, Bước sau Bước kết thúc không đường vào, khối không làn nào ra thì không điểm gộp, "Thoát vòng lặp" chỉ
  tới `exit:<vòng lặp>`, làn lỗi gặp lại dưới cả khối (`rejoin:`), khung thu gọn đo như thẻ; `lib/workflow-shapes.ts` thêm
  khung, thanh Điểm nối, lối ra, mũi tên và nhãn; Sơ đồ vẽ khung, thanh "Chờ tất cả nhánh xong", nhãn "Lặp lại", đầu làn có
  "Bỏ nhánh", thẻ người duyệt, dấu "Quy trình con", huy hiệu "N lỗi"; `use-folded-frames.ts` giữ trạng thái thu gọn dưới
  `wbui.collapsed.<user_id>.<artifact_id>`; `navigate`, `stopsInOrder` bỏ qua khung thu gọn; Ctrl+K mở các khung bao Bước;
  `Tree` đọc cùng trạng thái; `CANVAS_MARKS` trong `@dw/ui`; fixture F10; danh mục giả mang ba cờ. Khác với ticket:
    - Quyết định (agent, theo ủy quyền 31/10/2026): route danh mục chưa trả ba cờ, nên ticket này thêm chúng vào
      `_catalogue_entry` và `NodeTypeView` (nơi đọc đầu tiên là Sơ đồ, workflow-nodes R1.4; mã băm danh mục đổi một lần
      cho mọi loại), có test ở `apps/api/tests/unit/test_studio_node_types.py`. Nếu sai thì: workflow-nodes thêm ba trường
      trong một ticket của nó và trang đọc y như vậy.
    - Quyết định (agent, theo ủy quyền 31/10/2026): tiêu đề khung nằm trên thẻ R1.8 ở đầu khung (dòng thứ hai của thẻ vòng
      lặp là "Lặp lại khi … (tối đa N lần)", thẻ song song mang nhãn "Song song"), khung là đường viền phía sau, không có
      dải đầu khung riêng, để đường nối vào không cắt chữ. Nếu sai thì: một dải tiêu đề trên thẻ, lệch trái.
    - Quyết định (agent, theo ủy quyền 31/10/2026): thân của khối `loop` là làn đầu của loại theo thứ tự danh mục, không
      đầu làn (khung bao nó); các làn còn lại ("Đã đủ N lần") treo dưới khung. Nếu sai thì: danh mục đánh dấu làn thân.
    - Quyết định (agent, theo ủy quyền 31/10/2026): làn cố định không bắt buộc có mục menu riêng "Thêm làn «Đã đủ N lần»",
      "Bỏ làn «Đã đủ N lần»", thay "Thêm nhánh"/"Bỏ nhánh…" mà ticket 02 cho loại làn cố định; "Thêm nhánh"/"Bỏ nhánh…" nay
      chỉ cho loại có làn theo khóa. Nếu sai thì: giữ cả hai đường.
    - Quyết định (agent, theo ủy quyền 31/10/2026): thu gọn và mở bằng nút ở hàng đầu của thẻ đầu khung (cả hai trạng thái)
      và bằng "Thu gọn khung"/"Mở khung" trong menu "…" (đường bàn phím, Shift+F10); tên truy cập của điểm dừng thêm "khung
      đang thu gọn". Nếu sai thì: một phím riêng trên thẻ.
    - Quyết định (agent, theo ủy quyền 31/10/2026): chỗ cho điểm gộp, thanh Điểm nối và lối ra luôn được giữ, có đường tới
      hay không, để một làn đổi từ kết thúc sang không kết thúc không dời gì (R1.6); khung thu gọn ẩn cả làn "Đã đủ N lần",
      làn lỗi của Bước vẫn vẽ. Nếu sai thì: khối co lại khi không có điểm gộp.
    - Quyết định (agent, theo ủy quyền 31/10/2026): một chủ là tập id Bước đã đóng; `Tree` ghi vào đó mọi Bước đóng ở đó,
      Sơ đồ chỉ thu gọn Bước khung; trạng thái mở của node làn trong `Tree` là của riêng `Tree`. Khi trang chưa biết người
      xem (`principalId` của `/me` chưa có) hay bộ nhớ không dùng được, thu gọn chỉ sống trong trang. Sơ đồ chỉ đọc không
      truyền `onToggleFrame` và không gọi hook, nên mở mọi khung. Nếu sai thì: `Tree` chỉ đóng được Bước khung.
    - Quyết định (agent, theo ủy quyền 31/10/2026): huy hiệu "N lỗi" đọc `warnings` của lần lưu Nháp gần nhất, mỗi `pointer`
      về Bước sâu nhất trên đường (`stepAtPointer` trong `workflow-graph.ts`, ticket 03 dùng lại cho 422 của R3.4); không gì
      có trước lần lưu đầu. Nếu sai thì: ticket 03 cấp lỗi và ticket này chỉ có chỗ hiện.
    - Quyết định (agent, theo ủy quyền 31/10/2026): danh mục giả dùng `human.approval@2` như fixture và workflow-nodes R12.1,
      không `human.approval@1` (loại gói của wf-lite, không có `approval_rule`); thẻ người duyệt đọc `required_scope`,
      `assignees` (danh sách hay Biểu thức), `approval_rule`. Nếu sai thì: thêm một mục `@1` vào danh mục giả.
    - Thêm ngoài ticket: "Di chuyển…" có ô tìm trong `TreeSelect` (đường bàn phím tới một ô sâu trong khung); `Tree` đặt
      `defaultExpandParent={false}` (rc-tree mở cha của khóa đang mở lúc gắn, mở lại khung đã thu gọn, đo bằng test); vitest
      `testTimeout` 20 s (test đầu của tệp trang F2 tốn ~3 s nạp lạnh, chạm 5 s khi máy bận); test fixture của ticket 01
      và pytest `test_builder_fixtures.py` nhận F10.
    - Test: vitest 44 tệp, 438 ca xanh (mới: `workflow-grammar.test.ts` 25 với snapshot F2, F3, F4, F5, F9, F10;
      `workflow-grammar-canvas.test.tsx` 15; `builder-grammar.test.tsx` 14; thêm ở `workflow-graph` 6, `workflow-layout` 2
      thuộc tính thu gọn trên 200 cây ngẫu nhiên có song song, kết thúc, thoát, `builder-model` 8, `builder-outline` 2);
      pytest `test_studio_node_types.py`, `test_node_registry.py`, unit `dw_agent_runtime` 1 109 xanh, `test_builder_fixtures.py`
      11; `pnpm run typecheck`, `pnpm run lint` sạch; Prettier sạch trên mọi tệp của ticket; `pnpm run build` biên dịch và
      sinh 23 trang rồi dừng ở bước standalone vì EPERM symlink (môi trường, như ticket 01, 02); JS gzip route builder 694,5
      kB trang và layout (687,5 ở ticket 02, +7,0) cộng 68,5 kB chunk Sơ đồ (67,0, +1,5); `generate_contracts.py --check`
      và test hợp đồng xanh. 15 đột biến tay đều đỏ (`lane2-wbu04-mutate-by-hand.log`), danh sách ở `mutations/04.yaml`.
    - `reviewing-feature-security` (đọc): ranh giới 1: không truy vấn, cache máy chủ hay đường lưu mới; khóa `localStorage`
      theo người xem và Quy trình, chỉ giữ id Bước của tài liệu người xem đã đọc, trong trình duyệt của họ; danh mục vẫn ở
      tầng nền tảng, như nhau cho mọi tenant (test sẵn có). Ranh giới 2: trang không quyết quyền nào, thu gọn không là quyền;
      403 của danh mục và của lần lưu vẫn vẽ như máy chủ gửi (test của ticket 02). Ranh giới 3: không tác động agent. Ranh
      giới 4: `config.on`, người được giao, `detail` của cảnh báo là chữ React, không `dangerouslySetInnerHTML`; `pointer`
      đọc phòng thủ; giá trị trong bộ nhớ qua `JSON.parse` trong `try`, lọc còn chuỗi. Ranh giới 5: không ghi mới; thu gọn
      không gửi gì nên không thêm dòng audit `draft_saved`. Ranh giới 6: mục bộ nhớ gỡ khi không còn khung thu gọn; bộ nhớ
      hỏng hay chặn thì mọi khung mở (hiện nhiều hơn, an toàn); ba trường mới của route là hằng của sổ nền tảng.
- 2026-11-05 (agent): MEDIUM để lại: (a) mũi tên "Thoát vòng lặp" đi thẳng xuống rồi dọc đáy khung tới lối ra, có thể cắt
  một thẻ khi Bước thoát nằm ở làn giữa và thân còn Bước sau khối; ảnh F9 ở lượt cuối hàng đợi; (b) nhãn "Đã đủ N lần" lấy
  nguyên văn từ danh mục, N không thay bằng `max_iterations`; (c) "N lỗi" chỉ có sau lần lưu đầu, lúc mở trang chưa có;
  (d) jsdom không vẽ cạnh, nên nhãn "Lặp lại" và đầu mũi tên chỉ được test ở hình (`workflow-grammar.test.ts`) và
  `arrowHead`, mắt thường ở Playwright; (e) thẻ 256 × 120 có thêm dòng 12 px (người duyệt, "Chờ Quy trình con xong") với
  khoảng 2 px: kiểm ở ảnh; (f) workflow-nodes/07 phải liệt kê `body` trước `max_reached` của `logic.loop@1` (quyết định thân
  ở trên); (g) mỗi Quy trình người xem thu gọn để lại một khóa trong `localStorage`, không dọn theo thời gian. MEDIUM (c) của
  ticket 02 (bàn phím bỏ qua khung thu gọn) xong ở đây. Còn cho lượt cuối hàng đợi: `scripts/mutate.py` cho
  `mutations/04.yaml`; chạy `e2e/workflow-builder.spec.ts` "builds F5's lanes and frames with the keyboard only" trên stack
  thật; ảnh Playwright sáng, tối, desktop và dưới 992 px của F2, F3, F4, F5, F9, F10 (khung, thanh, nhãn "Lặp lại", mũi tên
  thoát, làn lỗi, thẻ người duyệt, thẻ Quy trình con, khung thu gọn có "N lỗi"); P50/P95/P99 của trang builder (tải F3,
  F7, thu gọn và mở một khung, Ctrl+K tới Bước trong khung thu gọn) và của `GET /studio/node-types`; `/code-review`;
  `reviewing-deployment-security` cho kiểu trả lời đổi của `node-types`.
